"""Meeting ingestion pipeline tests.

Written before the implementation. Everything upstream of the provider call is
exercised for real — the route, the upload write, the DB rows, the status
transitions — while the providers themselves are faked. That boundary is
deliberate: the value of these tests is that a failed transcription marks a
meeting failed and that segments land with the right speakers and timestamps,
and none of that should depend on a network call or an API key.
"""

from __future__ import annotations

import asyncio
import io
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import config, database
from backend.database import (
    Meeting,
    MeetingStatus,
    Organization,
    Speaker,
    TranscriptSegment,
)
from backend.transcription.base import (
    DiarizationResult,
    SpeakerTurn,
    TranscribedSegment,
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionResult,
)

# ── fixtures ──────────────────────────────────────────────────────────────


def _wav_bytes(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """A real, decodable WAV file — silence, but structurally valid."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buffer.getvalue()


@pytest.fixture
def data_dir(tmp_path: Path):
    """Point the app at a throwaway data directory and build a fresh schema."""
    previous = config.get_data_dir()
    config.set_data_dir(tmp_path)
    database.init_db()
    yield tmp_path
    config.set_data_dir(previous)


@pytest.fixture
def db(data_dir):
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def org(db) -> Organization:
    organization = Organization(name="Test Org", slug="test-org")
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def client(data_dir):
    from backend.app import app

    with TestClient(app) as test_client:
        yield test_client


# ── fake providers ────────────────────────────────────────────────────────


class FakeTranscriber(TranscriptionProvider):
    """A ``TranscriptionProvider`` that returns canned results or raises."""

    def __init__(
        self,
        *,
        segments: list[TranscribedSegment] | None = None,
        diarization: DiarizationResult | None = None,
        transcribe_error: Exception | None = None,
        diarize_error: Exception | None = None,
        supports_diarization: bool = True,
    ) -> None:
        super().__init__(
            TranscriptionConfig(
                name="fake",
                model="fake-1",
                supports_diarization=supports_diarization,
            )
        )
        self._segments = segments or []
        self._diarization = diarization
        self._transcribe_error = transcribe_error
        self._diarize_error = diarize_error
        self.transcribe_calls = 0

    def is_configured(self) -> bool:
        return True

    async def transcribe(self, audio_path, *, language=None, prompt=None) -> TranscriptionResult:
        self.transcribe_calls += 1
        if self._transcribe_error:
            raise self._transcribe_error
        return TranscriptionResult(
            segments=list(self._segments),
            language=language or "en",
            duration_seconds=(self._segments[-1].end_ms / 1000) if self._segments else 0.0,
            provider="fake",
            model="fake-1",
        )

    async def diarize(self, audio_path) -> DiarizationResult:
        if self._diarize_error:
            raise self._diarize_error
        if self._diarization is None:
            raise TranscriptionError("no diarization configured")
        return self._diarization


class FakeEmbedder:
    """Minimal stand-in for the embedding half of ``LLMProvider``."""

    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self._vectors = vectors
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self._vectors is not None:
            return self._vectors[: len(texts)]
        # Deterministic filler so callers that don't care still get vectors.
        return [[float(len(text)), 1.0, 0.0] for text in texts]


def _three_segments() -> list[TranscribedSegment]:
    return [
        TranscribedSegment(start_ms=0, end_ms=2000, text="Welcome everyone to the club meeting."),
        TranscribedSegment(start_ms=2000, end_ms=5000, text="Can we start with the budget?"),
        TranscribedSegment(start_ms=5000, end_ms=9000, text="Yes, we spent forty on snacks."),
    ]


def _two_speaker_diarization() -> DiarizationResult:
    return DiarizationResult(
        turns=[
            SpeakerTurn(start_ms=0, end_ms=2000, speaker_label="SPEAKER_00"),
            SpeakerTurn(start_ms=2000, end_ms=5000, speaker_label="SPEAKER_01"),
            SpeakerTurn(start_ms=5000, end_ms=9000, speaker_label="SPEAKER_00"),
        ],
        speaker_count=2,
        provider="fake",
    )


# ── 1. upload creates a Meeting in `processing` ───────────────────────────


def test_upload_creates_meeting_with_processing_status(client, db, org, monkeypatch):
    """A valid upload persists the audio and returns immediately."""
    scheduled: list[str] = []
    monkeypatch.setattr(
        "backend.routes.meetings.schedule_processing",
        lambda meeting_id: scheduled.append(meeting_id),
    )

    response = client.post(
        "/api/meetings/upload",
        files={"file": ("club-meeting.wav", _wav_bytes(), "audio/wav")},
        data={"title": "Club meeting", "org_id": org.id, "consent_confirmed": "true"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == MeetingStatus.PROCESSING.value
    assert body["title"] == "Club meeting"

    meeting = db.query(Meeting).filter(Meeting.id == body["id"]).one()
    assert meeting.status == MeetingStatus.PROCESSING.value
    assert meeting.org_id == org.id
    assert meeting.recording_path

    stored = config.resolve_storage_path(meeting.recording_path)
    assert stored is not None and stored.is_file()
    assert stored.suffix == ".wav"

    # The request returns before any processing runs; the work is handed off.
    assert scheduled == [meeting.id]


def test_upload_preserves_uploaded_extension(client, db, org, monkeypatch):
    """The stored file keeps its container — decoders pick codecs by suffix."""
    monkeypatch.setattr("backend.routes.meetings.schedule_processing", lambda meeting_id: None)

    response = client.post(
        "/api/meetings/upload",
        files={"file": ("standup.m4a", _wav_bytes(), "audio/mp4")},
        data={"title": "Standup", "org_id": org.id, "consent_confirmed": "true"},
    )

    assert response.status_code == 202
    meeting = db.query(Meeting).filter(Meeting.id == response.json()["id"]).one()
    assert config.resolve_storage_path(meeting.recording_path).suffix == ".m4a"


# ── 2. unsupported file types are rejected clearly ────────────────────────


def test_upload_rejects_unsupported_file_type(client, db, org, monkeypatch):
    """A non-audio upload is refused with a message naming what is allowed."""
    monkeypatch.setattr("backend.routes.meetings.schedule_processing", lambda meeting_id: None)

    before = db.query(Meeting).count()
    response = client.post(
        "/api/meetings/upload",
        files={"file": ("notes.txt", b"not audio at all", "text/plain")},
        data={"title": "Notes", "org_id": org.id, "consent_confirmed": "true"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert ".txt" in detail
    assert ".wav" in detail  # the error tells the caller what would work

    # Rejected before anything is persisted — no orphan row, no orphan file.
    assert db.query(Meeting).count() == before


def test_upload_rejects_missing_filename(client, db, org, monkeypatch):
    """An upload with no filename has no extension to validate, so it is refused."""
    monkeypatch.setattr("backend.routes.meetings.schedule_processing", lambda meeting_id: None)

    response = client.post(
        "/api/meetings/upload",
        files={"file": ("", _wav_bytes(), "audio/wav")},
        data={"title": "Nameless", "org_id": org.id, "consent_confirmed": "true"},
    )
    assert response.status_code in (400, 422)


# ── 3. transcription failure fails the meeting, and does not hang ─────────


def test_transcription_failure_marks_meeting_failed(db, org, data_dir):
    """A provider error transitions the meeting to `failed` with the reason."""
    from backend.meetings import ingestion

    meeting = Meeting(org_id=org.id, title="Doomed", status=MeetingStatus.PROCESSING.value)
    meeting.recording_path = "recordings/missing.wav"
    db.add(meeting)
    db.commit()
    meeting_id = meeting.id

    provider = FakeTranscriber(transcribe_error=TranscriptionError("upstream exploded"))

    # wait_for is the point of this test: a provider that raises must not
    # leave the pipeline awaiting something that never resolves.
    asyncio.run(
        asyncio.wait_for(
            ingestion.process_meeting(meeting_id, provider=provider),
            timeout=10,
        )
    )

    db.expire_all()
    failed = db.query(Meeting).filter(Meeting.id == meeting_id).one()
    assert failed.status == MeetingStatus.FAILED.value
    assert "upstream exploded" in (failed.processing_error or "")
    assert db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).count() == 0


def test_unexpected_error_also_marks_failed(db, org, data_dir):
    """Not just TranscriptionError — any exception must land the meeting in `failed`."""
    from backend.meetings import ingestion

    meeting = Meeting(org_id=org.id, title="Doomed too", status=MeetingStatus.PROCESSING.value)
    meeting.recording_path = "recordings/missing.wav"
    db.add(meeting)
    db.commit()
    meeting_id = meeting.id

    provider = FakeTranscriber(transcribe_error=ValueError("something unexpected"))
    asyncio.run(asyncio.wait_for(ingestion.process_meeting(meeting_id, provider=provider), timeout=10))

    db.expire_all()
    assert db.query(Meeting).filter(Meeting.id == meeting_id).one().status == MeetingStatus.FAILED.value


# ── 4. a successful run writes segments with speakers and timestamps ──────


def test_successful_run_writes_segments_with_speakers_and_timestamps(db, org, data_dir):
    """The happy path: segments, speakers, timings, and a completed meeting."""
    from backend.meetings import ingestion

    audio = data_dir / "recordings" / "club.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(_wav_bytes(seconds=9))

    meeting = Meeting(org_id=org.id, title="Club meeting", status=MeetingStatus.PROCESSING.value)
    meeting.recording_path = config.to_storage_path(audio)
    db.add(meeting)
    db.commit()
    meeting_id = meeting.id

    provider = FakeTranscriber(segments=_three_segments(), diarization=_two_speaker_diarization())

    asyncio.run(
        asyncio.wait_for(ingestion.process_meeting(meeting_id, provider=provider, run_segmentation=False), timeout=10)
    )

    db.expire_all()
    processed = db.query(Meeting).filter(Meeting.id == meeting_id).one()
    assert processed.status == MeetingStatus.COMPLETED.value
    assert processed.processing_error is None
    assert processed.audio_duration_seconds == pytest.approx(9.0)

    segments = db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).order_by(TranscriptSegment.sequence).all()
    assert len(segments) == 3

    # Timestamps survive intact and in order.
    assert [(s.start_ms, s.end_ms) for s in segments] == [(0, 2000), (2000, 5000), (5000, 9000)]
    assert [s.sequence for s in segments] == [0, 1, 2]
    assert segments[0].text == "Welcome everyone to the club meeting."

    # Two distinct voices become two Speaker rows, reused across turns.
    speakers = db.query(Speaker).filter_by(meeting_id=meeting_id).all()
    assert len(speakers) == 2
    assert {s.display_label for s in speakers} == {"SPEAKER_00", "SPEAKER_01"}

    by_id = {s.id: s.display_label for s in speakers}
    assert [by_id[s.speaker_id] for s in segments] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]

    # Talk time is attributed per speaker: 2s + 4s for 00, 3s for 01.
    talk = {s.display_label: s.talk_time_seconds for s in speakers}
    assert talk["SPEAKER_00"] == pytest.approx(6.0)
    assert talk["SPEAKER_01"] == pytest.approx(3.0)


def test_run_without_diarization_still_writes_segments(db, org, data_dir):
    """A provider that cannot diarize yields unattributed segments, not a failure."""
    from backend.meetings import ingestion

    audio = data_dir / "recordings" / "solo.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(_wav_bytes(seconds=9))

    meeting = Meeting(org_id=org.id, title="No diarization", status=MeetingStatus.PROCESSING.value)
    meeting.recording_path = config.to_storage_path(audio)
    db.add(meeting)
    db.commit()
    meeting_id = meeting.id

    provider = FakeTranscriber(segments=_three_segments(), supports_diarization=False)
    asyncio.run(asyncio.wait_for(ingestion.process_meeting(meeting_id, provider=provider), timeout=10))

    db.expire_all()
    assert db.query(Meeting).filter(Meeting.id == meeting_id).one().status == MeetingStatus.COMPLETED.value
    segments = db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).all()
    assert len(segments) == 3
    assert all(s.speaker_id is None for s in segments)
    assert db.query(Speaker).filter_by(meeting_id=meeting_id).count() == 0


def test_diarization_failure_does_not_fail_the_meeting(db, org, data_dir):
    """Losing speaker labels degrades the result; it does not discard the transcript."""
    from backend.meetings import ingestion

    audio = data_dir / "recordings" / "partial.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(_wav_bytes(seconds=9))

    meeting = Meeting(org_id=org.id, title="Partial", status=MeetingStatus.PROCESSING.value)
    meeting.recording_path = config.to_storage_path(audio)
    db.add(meeting)
    db.commit()
    meeting_id = meeting.id

    provider = FakeTranscriber(
        segments=_three_segments(),
        diarize_error=TranscriptionError("diarizer unavailable"),
    )
    asyncio.run(asyncio.wait_for(ingestion.process_meeting(meeting_id, provider=provider), timeout=10))

    db.expire_all()
    assert db.query(Meeting).filter(Meeting.id == meeting_id).one().status == MeetingStatus.COMPLETED.value
    assert db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).count() == 3


def test_reprocessing_replaces_prior_segments(db, org, data_dir):
    """Re-running a meeting must not double up its transcript."""
    from backend.meetings import ingestion

    audio = data_dir / "recordings" / "again.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(_wav_bytes(seconds=9))

    meeting = Meeting(org_id=org.id, title="Again", status=MeetingStatus.PROCESSING.value)
    meeting.recording_path = config.to_storage_path(audio)
    db.add(meeting)
    db.commit()
    meeting_id = meeting.id

    provider = FakeTranscriber(segments=_three_segments(), diarization=_two_speaker_diarization())
    for _ in range(2):
        asyncio.run(asyncio.wait_for(ingestion.process_meeting(meeting_id, provider=provider), timeout=10))

    db.expire_all()
    assert db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).count() == 3
    assert db.query(Speaker).filter_by(meeting_id=meeting_id).count() == 2


# ── end-to-end: upload through the real background task ───────────────────


def test_upload_runs_the_real_background_task_to_completion(client, db, org, monkeypatch):
    """Upload → 202 → background task → transcript, with nothing stubbed but the provider.

    The other upload tests replace ``schedule_processing`` so they can assert
    on the `processing` state. This one leaves it alone, so the asyncio task
    the route creates actually runs — which is the part most likely to break
    silently, since a task nobody holds a reference to can be collected
    mid-flight.
    """
    provider = FakeTranscriber(segments=_three_segments(), diarization=_two_speaker_diarization())
    monkeypatch.setattr(
        "backend.meetings.ingestion.get_transcription_provider",
        lambda: provider,
    )

    response = client.post(
        "/api/meetings/upload",
        files={"file": ("club.wav", _wav_bytes(seconds=9), "audio/wav")},
        data={"title": "Club meeting", "org_id": org.id, "consent_confirmed": "true"},
    )
    assert response.status_code == 202
    meeting_id = response.json()["id"]

    # Poll the API the way a client would, rather than reaching into the DB.
    for _ in range(50):
        current = client.get(f"/api/meetings/{meeting_id}").json()
        if current["status"] != MeetingStatus.PROCESSING.value:
            break
        time.sleep(0.1)

    assert current["status"] == MeetingStatus.COMPLETED.value, current.get("processing_error")
    assert provider.transcribe_calls == 1

    db.expire_all()
    segments = db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).order_by(TranscriptSegment.sequence).all()
    assert [(s.start_ms, s.end_ms) for s in segments] == [(0, 2000), (2000, 5000), (5000, 9000)]
    assert db.query(Speaker).filter_by(meeting_id=meeting_id).count() == 2


# ── segmentation ──────────────────────────────────────────────────────────


def test_detect_boundaries_splits_where_similarity_drops():
    """Two coherent blocks with an orthogonal jump between them split once."""
    from backend.meetings import segmentation

    # Six segments: three about one thing, three about another.
    vectors = [
        [1.0, 0.0, 0.0],
        [0.99, 0.1, 0.0],
        [0.98, 0.05, 0.0],
        [0.0, 1.0, 0.0],
        [0.05, 0.99, 0.0],
        [0.0, 0.98, 0.1],
    ]
    boundaries = segmentation.detect_boundaries(vectors, window=2, threshold=0.5)
    assert boundaries == [3]


def test_detect_boundaries_returns_none_for_uniform_content():
    """A single coherent discussion produces no split."""
    from backend.meetings import segmentation

    vectors = [[1.0, 0.0, 0.0], [0.99, 0.01, 0.0], [0.98, 0.02, 0.0], [1.0, 0.01, 0.0]]
    assert segmentation.detect_boundaries(vectors, window=2, threshold=0.5) == []


def test_detect_boundaries_handles_short_input():
    """Fewer segments than the window is not an error."""
    from backend.meetings import segmentation

    assert segmentation.detect_boundaries([], window=2, threshold=0.5) == []
    assert segmentation.detect_boundaries([[1.0, 0.0]], window=2, threshold=0.5) == []


def test_segment_meeting_writes_topic_rows(db, org, data_dir):
    """Topics are persisted with spans that cover their segments."""
    from backend.meetings import segmentation

    meeting = Meeting(org_id=org.id, title="Two topics", status=MeetingStatus.COMPLETED.value)
    db.add(meeting)
    db.commit()

    texts = ["budget line one", "budget line two", "venue booking", "venue parking"]
    for index, text in enumerate(texts):
        db.add(
            TranscriptSegment(
                meeting_id=meeting.id,
                sequence=index,
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                text=text,
            )
        )
    db.commit()
    meeting_id = meeting.id

    embedder = FakeEmbedder(vectors=[[1.0, 0.0, 0.0], [0.99, 0.05, 0.0], [0.0, 1.0, 0.0], [0.05, 0.99, 0.0]])
    topics = asyncio.run(
        asyncio.wait_for(
            segmentation.segment_meeting(meeting_id, embedder=embedder, window=1, threshold=0.5),
            timeout=10,
        )
    )

    assert len(topics) == 2
    assert embedder.calls == 1  # one batched embed call, not one per segment
    assert topics[0].start_ms == 0 and topics[0].end_ms == 2000
    assert topics[1].start_ms == 2000 and topics[1].end_ms == 4000
    assert sum(topic.salience for topic in topics) == pytest.approx(1.0)


def test_segment_meeting_with_no_segments_is_a_noop(db, org, data_dir):
    """An empty transcript produces no topics and no embed call."""
    from backend.meetings import segmentation

    meeting = Meeting(org_id=org.id, title="Empty", status=MeetingStatus.COMPLETED.value)
    db.add(meeting)
    db.commit()

    embedder = FakeEmbedder()
    topics = asyncio.run(segmentation.segment_meeting(meeting.id, embedder=embedder))
    assert topics == []
    assert embedder.calls == 0


def _completed_meeting(db, org) -> str:
    meeting = Meeting(org_id=org.id, title="Extraction outcome", status=MeetingStatus.COMPLETED.value)
    db.add(meeting)
    db.commit()
    return meeting.id


def test_failed_extraction_is_recorded_not_shown_as_empty(db, org, monkeypatch):
    """No API key used to yield a 'completed' meeting with zero items and no hint why."""
    from backend.meetings import ingestion, intelligence

    meeting_id = _completed_meeting(db, org)

    async def failing(mid):
        report = intelligence.ExtractionReport(meeting_id=mid)
        report.errors = [
            f"{kind} extraction failed: ANTHROPIC_API_KEY is not set." for kind in ("decision", "risk")
        ] + ["verification failed: no embedder"]
        return report

    monkeypatch.setattr(intelligence, "extract_meeting_intelligence", failing)
    asyncio.run(ingestion._try_extract(meeting_id))

    db.expire_all()
    meeting = db.get(Meeting, meeting_id)
    assert meeting.status == MeetingStatus.COMPLETED.value
    assert meeting.processing_error == (
        "Extraction incomplete. decision, risk not extracted: ANTHROPIC_API_KEY is not set. "
        "verification failed: no embedder"
    )


def test_clean_extraction_clears_an_old_problem(db, org, monkeypatch):
    from backend.meetings import ingestion, intelligence

    meeting_id = _completed_meeting(db, org)
    db.get(Meeting, meeting_id).processing_error = "Extraction incomplete. stale"
    db.commit()

    async def ok(mid):
        return intelligence.ExtractionReport(meeting_id=mid)

    monkeypatch.setattr(intelligence, "extract_meeting_intelligence", ok)
    asyncio.run(ingestion._try_extract(meeting_id))

    db.expire_all()
    assert db.get(Meeting, meeting_id).processing_error is None
