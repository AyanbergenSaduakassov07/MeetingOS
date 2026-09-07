"""Meeting ingestion: audio in, attributed transcript out.

Runs detached from the request that triggered it, so it owns its own database
session — the request's session is closed long before this finishes.

Failure policy, which is most of what this module is:

- Transcription failing fails the meeting.  Without text there is nothing.
- Diarization failing does **not**.  Losing speaker labels degrades the
  result; discarding a transcript that cost real money and minutes to produce
  because the diarizer was down would be worse than serving it unattributed.
- Segmentation failing does not either, for the same reason — topics are
  derived data and can be recomputed later.
- Any unexpected exception still lands the meeting in ``failed`` with the
  reason recorded.  A meeting stuck in ``processing`` forever is the one
  outcome with no recovery path from the UI.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..database import Meeting, MeetingStatus, Speaker, TranscriptSegment
from ..transcription import TranscriptionProvider, get_transcription_provider
from ..transcription.base import DiarizationResult, TranscriptionResult, merge_diarization

logger = logging.getLogger(__name__)

# asyncio holds only a weak reference to a bare task, so a task nobody keeps
# can be garbage-collected mid-flight. Holding them here until they finish is
# what backend/services/task_queue.py did before it was stripped.
_background_tasks: set[asyncio.Task] = set()

# Concurrency ceiling for transcription. Without it, N uploads start N
# transcriptions at once: N times the third-party spend in the same instant,
# and enough event-loop pressure to make the API unresponsive while it happens.
# Queued meetings still run, just one after another.
MAX_CONCURRENT_PROCESSING = int(os.environ.get("MEETINGOS_MAX_CONCURRENT_PROCESSING", "2"))

_processing_slots: asyncio.Semaphore | None = None


def _slots() -> asyncio.Semaphore:
    """Created lazily so the semaphore binds to the running loop, not import time."""
    global _processing_slots
    if _processing_slots is None:
        _processing_slots = asyncio.Semaphore(MAX_CONCURRENT_PROCESSING)
    return _processing_slots


async def _process_when_a_slot_frees(meeting_id: str) -> None:
    async with _slots():
        await process_meeting(meeting_id)


def schedule_processing(meeting_id: str) -> None:
    """Hand a meeting off to the background and return immediately.

    Called from the upload route, which must not block on transcription. The
    meeting waits for a processing slot rather than starting instantly.
    """
    task = asyncio.create_task(_process_when_a_slot_frees(meeting_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def process_meeting(
    meeting_id: str,
    *,
    provider: TranscriptionProvider | None = None,
    run_segmentation: bool = True,
) -> None:
    """Transcribe, diarize, and persist the transcript for one meeting.

    Never raises: the outcome is recorded on the meeting row instead, because
    the only caller is a background task with nowhere to report an exception.
    """
    from ..database import new_session

    provider = provider or get_transcription_provider()
    db: Session = new_session()

    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting is None:
            logger.warning("Ingestion skipped: meeting %s no longer exists", meeting_id)
            return

        audio_path = config.resolve_storage_path(meeting.recording_path)
        if audio_path is None:
            _mark_failed(db, meeting, "Meeting has no recording to process.")
            return

        meeting.status = MeetingStatus.PROCESSING.value
        meeting.processing_error = None
        db.commit()

        result = await provider.transcribe(audio_path, language=meeting.language)
        diarization = await _try_diarize(provider, audio_path)
        if diarization is not None:
            merge_diarization(result, diarization)

        _write_transcript(db, meeting, result)

        meeting.status = MeetingStatus.COMPLETED.value
        meeting.audio_duration_seconds = _duration_seconds(result)
        meeting.language = result.language or meeting.language
        meeting.processing_error = None
        db.commit()

        logger.info(
            "Ingested meeting %s: %d segments, %d speakers",
            meeting_id,
            len(result.segments),
            len({s.speaker_label for s in result.segments if s.speaker_label}),
        )

    except Exception as exc:
        logger.exception("Ingestion failed for meeting %s", meeting_id)
        db.rollback()
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting is not None:
            _mark_failed(db, meeting, str(exc))
        return
    finally:
        db.close()

    if run_segmentation:
        await _try_segment(meeting_id)
        await _try_extract(meeting_id)


async def _try_diarize(provider: TranscriptionProvider, audio_path: Path) -> DiarizationResult | None:
    """Diarize if the provider can, returning None instead of raising."""
    if not provider.config.supports_diarization:
        logger.info("Provider %s does not diarize; segments stay unattributed", provider.config.name)
        return None
    try:
        return await provider.diarize(audio_path)
    except Exception as exc:
        logger.warning("Diarization failed, continuing without speaker labels: %s", exc)
        return None


async def _try_extract(meeting_id: str) -> None:
    """Extract decisions/actions/risks/commitments, swallowing failures.

    Best-effort for the same reason as segmentation: a transcript that exists
    is worth serving even when the extraction provider is down or
    uncredentialed. The meeting stays ``completed``; the intelligence endpoint
    simply returns fewer items until it is re-run.
    """
    from . import intelligence

    try:
        report = await intelligence.extract_meeting_intelligence(meeting_id)
        logger.info("Extracted %d intelligence item(s) for meeting %s", report.total, meeting_id)
    except Exception as exc:
        logger.warning("Intelligence extraction skipped for meeting %s: %s", meeting_id, exc)


async def _try_segment(meeting_id: str) -> None:
    """Derive topics, swallowing failures — they are recomputable."""
    from . import segmentation

    try:
        topics = await segmentation.segment_meeting(meeting_id)
        logger.info("Segmented meeting %s into %d topic(s)", meeting_id, len(topics))
    except Exception as exc:
        logger.warning("Topic segmentation skipped for meeting %s: %s", meeting_id, exc)


def _duration_seconds(result: TranscriptionResult) -> float | None:
    """Prefer the provider's duration; fall back to the last segment's end."""
    if result.duration_seconds is not None:
        return float(result.duration_seconds)
    if result.segments:
        return max(segment.end_ms for segment in result.segments) / 1000
    return None


def _write_transcript(db: Session, meeting: Meeting, result: TranscriptionResult) -> None:
    """Replace the meeting's transcript with ``result``.

    Reprocessing is a supported operation (a better model, a fixed diarizer),
    so this clears prior rows rather than appending to them. Segments go
    before speakers because segments reference them.
    """
    db.query(TranscriptSegment).filter_by(meeting_id=meeting.id).delete(synchronize_session=False)
    db.query(Speaker).filter_by(meeting_id=meeting.id).delete(synchronize_session=False)
    db.flush()

    speakers = _create_speakers(db, meeting, result)

    for sequence, segment in enumerate(result.segments):
        speaker = speakers.get(segment.speaker_label) if segment.speaker_label else None
        db.add(
            TranscriptSegment(
                meeting_id=meeting.id,
                speaker_id=speaker.id if speaker else None,
                sequence=sequence,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=segment.text,
                confidence=segment.confidence,
                # Per-segment first; the meeting-level detection is the
                # fallback for providers that report only one language.
                language=segment.language or result.language,
            )
        )

    db.flush()


def _create_speakers(db: Session, meeting: Meeting, result: TranscriptionResult) -> dict[str, Speaker]:
    """Create one ``Speaker`` per distinct label, with talk time and word counts.

    Labels come from the segments rather than the diarization turns: a turn
    that overlapped no segment attributes no speech, and a speaker row with
    zero segments is noise in the UI.
    """
    speakers: dict[str, Speaker] = {}

    for segment in result.segments:
        label = segment.speaker_label
        if not label:
            continue
        if label not in speakers:
            speaker = Speaker(meeting_id=meeting.id, display_label=label, talk_time_seconds=0.0, word_count=0)
            db.add(speaker)
            speakers[label] = speaker
        speakers[label].talk_time_seconds += max(0, segment.end_ms - segment.start_ms) / 1000
        speakers[label].word_count += len(segment.text.split())

    if speakers:
        db.flush()  # assign ids before segments reference them
    return speakers


def _mark_failed(db: Session, meeting: Meeting, reason: str) -> None:
    """Record a terminal failure on the meeting."""
    meeting.status = MeetingStatus.FAILED.value
    meeting.processing_error = reason
    db.commit()
    logger.error("Meeting %s failed: %s", meeting.id, reason)
