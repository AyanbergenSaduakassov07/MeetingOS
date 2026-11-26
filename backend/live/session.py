"""One running live session: audio in, captions and translations out.

Pipeline: host PCM -> WAV on disk + recognizer -> segmenter -> final
``TranscriptSegment`` row + ``transcript.final`` -> one translator call per
sentence for every language a viewer has open -> ``segment_translations`` +
``translation.final``. Ending the session runs the existing topic and
extraction steps on the stored transcript.

shortcut: runtimes live in this process's memory; a second worker would not see
them. Move fan-out to Redis before running more than one worker.
"""

from __future__ import annotations

import asyncio
import logging
import time
import wave
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from .. import config
from ..database import Meeting, MeetingStatus, TranscriptSegment, new_session
from ..database.models import LiveSession, SegmentTranslation
from .eventlog import EventLog
from .segmenter import Segmenter
from .types import Sentence, StreamingASR, Translator

logger = logging.getLogger(__name__)

GRACE_S = 60.0  # keep translating a language this long after its last viewer leaves
TRANSLATE_TIMEOUT_S = 15.0
TRANSLATE_CONCURRENCY = 4
END_DRAIN_TIMEOUT_S = 120.0  # local recognition may still be working through the tail
BACKFILL_LINES = 20  # a newly opened language also gets this many earlier lines translated
IDLE_END_S = 600.0  # no audio this long (host closed the tab) ends the session

_runtimes: dict[str, LiveRuntime] = {}
_background: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


class LiveRuntime:
    def __init__(
        self,
        *,
        session_id: str,
        meeting_id: str,
        source_language: str | None,
        asr: StreamingASR,
        translator: Translator | None,
        recording_path: Path,
    ) -> None:
        self.session_id, self.meeting_id = session_id, meeting_id
        self.source_language = source_language
        self.asr, self.translator = asr, translator
        self.log = EventLog()
        self.recording_path = recording_path
        self._segmenter = Segmenter()
        self._refs: dict[str, int] = {}
        self._left_at: dict[str, float] = {}
        self._context: deque[str] = deque(maxlen=3)
        # (segment_id, text, language, langs already translated or in flight)
        self._recent: deque[tuple[str, str, str | None, set[str]]] = deque(maxlen=BACKFILL_LINES)
        self._sequence = 0
        self._audio_ms = 0
        self._translations: set[asyncio.Task] = set()
        self._sem = asyncio.Semaphore(TRANSLATE_CONCURRENCY)
        self._wav: wave.Wave_write | None = None
        self._tasks: list[asyncio.Task] = []
        self._last_audio = time.monotonic()
        self.ending = False

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        await self.asr.start(language=self.source_language)
        self.recording_path.parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(str(self.recording_path), "wb")  # noqa: SIM115 (closed in end())
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(16_000)
        self._tasks = [asyncio.create_task(self._consume()), asyncio.create_task(self._tick())]
        self.log.publish("session.state", {"state": "live"})

    async def ingest(self, pcm16: bytes) -> None:
        if self.ending or not pcm16:
            return
        pcm16 = pcm16[: len(pcm16) // 2 * 2]
        self._wav.writeframes(pcm16)
        self._audio_ms += len(pcm16) // 32
        self._last_audio = time.monotonic()
        await self.asr.send(pcm16)

    async def end(self, state: str = "ended") -> None:
        if self.ending:
            return
        self.ending = True
        self._tasks[1].cancel()
        try:
            await self._drain()
        except Exception:  # whatever broke, the file, rows and viewers below must still be closed
            logger.exception("live %s: error while draining", self.session_id)
        finally:
            self._wav.close()
            has_transcript = self._sequence > 0
            try:
                _close_rows(
                    self.session_id, self.meeting_id, state, self._audio_ms, self.recording_path, has_transcript
                )
            finally:
                self.log.publish("session.state", {"state": state})
                self.log.close()
                _runtimes.pop(self.session_id, None)
        if has_transcript:
            _spawn(_finalize(self.meeting_id))

    # -- viewers -----------------------------------------------------------

    def join(self, lang: str | None) -> None:
        if lang:
            if lang not in self.active_languages():
                self._backfill(lang)
            self._refs[lang] = self._refs.get(lang, 0) + 1
        self._publish_count()

    def _backfill(self, lang: str) -> None:
        if self.translator is None or self.ending:
            return
        for segment_id, text, language, done in self._recent:
            if language != lang and lang not in done:
                done.add(lang)
                self._spawn_translation(segment_id, text, language, [lang], [])

    def leave(self, lang: str | None) -> None:
        if lang and self._refs.get(lang):
            self._refs[lang] -= 1
            if not self._refs[lang]:
                self._left_at[lang] = time.monotonic()
        self._publish_count()

    def active_languages(self) -> set[str]:
        now = time.monotonic()
        return {
            lang
            for lang in set(self._refs) | set(self._left_at)
            if self._refs.get(lang, 0) > 0 or now - self._left_at.get(lang, -GRACE_S) < GRACE_S
        }

    def viewer_count(self) -> int:
        return sum(self._refs.values())

    def _publish_count(self) -> None:
        if not self.log.closed:
            self.log.publish("participant.count", {"viewers": self.viewer_count()})

    # -- pipeline ----------------------------------------------------------

    async def _drain(self) -> None:
        await self.asr.close()
        try:
            await asyncio.wait_for(self._tasks[0], END_DRAIN_TIMEOUT_S)
        except TimeoutError:
            logger.warning("live %s: recognizer did not drain in time", self.session_id)
            getattr(self.asr, "abort", lambda: None)()
        except Exception:
            logger.exception("live %s: caption pipeline had failed", self.session_id)
        await self._commit_all(self._segmenter.flush())
        if self._translations:
            await asyncio.wait(self._translations, timeout=TRANSLATE_TIMEOUT_S)

    async def _consume(self) -> None:
        async for event in self.asr.events():
            if event.kind == "partial":
                self.log.publish("transcript.partial", {"text": event.text, "language": event.language})
                continue
            await self._commit_all(self._segmenter.on_event(event))

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if time.monotonic() - self._last_audio > IDLE_END_S:
                logger.info("live %s: no audio for %.0f s, ending", self.session_id, IDLE_END_S)
                _spawn(self.end())
                return
            await self._commit_all(self._segmenter.check_pending())

    async def _commit_all(self, sentences: list[Sentence]) -> None:
        for sentence in sentences:
            try:
                await self._commit(sentence)
            except Exception:  # a failed write loses one line, not the rest of the meeting
                logger.exception("live %s: could not store a caption", self.session_id)

    async def _commit(self, sentence: Sentence) -> None:
        language = self._segmenter.language or self.source_language
        self._sequence += 1
        segment_id = _store_segment(self.meeting_id, self._sequence, sentence, language)
        self.log.publish(
            "transcript.final",
            {
                "segment_id": segment_id,
                "sequence": self._sequence,
                "text": sentence.text,
                "language": language,
                "start_ms": sentence.t_audio_start_ms,
                "end_ms": sentence.t_audio_end_ms,
                "paragraph_break": sentence.paragraph_break,
            },
        )
        targets = sorted(self.active_languages() - {language}) if self.translator is not None else []
        if targets:
            self._spawn_translation(segment_id, sentence.text, language, targets, list(self._context))
        self._recent.append((segment_id, sentence.text, language, set(targets)))
        self._context.append(sentence.text)

    def _spawn_translation(self, segment_id: str, text: str, source: str | None, targets: list[str], context) -> None:
        task = asyncio.create_task(self._translate(segment_id, text, source, targets, context))
        self._translations.add(task)
        task.add_done_callback(self._translations.discard)

    async def _translate(self, segment_id: str, text: str, source: str | None, targets: list[str], context) -> None:
        async with self._sem:
            started = time.monotonic()
            try:
                out = await asyncio.wait_for(
                    self.translator.translate(text, source=source, targets=targets, context=context),
                    TRANSLATE_TIMEOUT_S,
                )
            except Exception as exc:
                logger.warning("live %s: translation failed: %s", self.session_id, exc)
                self.log.publish(
                    "translation.failed", {"segment_id": segment_id, "langs": targets, "error": type(exc).__name__}
                )
                return
        _store_translations(segment_id, out, self.translator.name)
        latency_ms = int((time.monotonic() - started) * 1000)
        for lang, translated in out.items():
            self.log.publish(
                "translation.final",
                {"segment_id": segment_id, "lang": lang, "revision": 0, "text": translated, "latency_ms": latency_ms},
            )


# -- persistence (sync, short transactions, like the rest of the codebase) ---


def _store_segment(meeting_id: str, sequence: int, sentence: Sentence, language: str | None) -> str:
    db = new_session()
    try:
        row = TranscriptSegment(
            meeting_id=meeting_id,
            sequence=sequence,
            start_ms=sentence.t_audio_start_ms,
            end_ms=sentence.t_audio_end_ms,
            text=sentence.text,
            language=language,
            is_final=True,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _store_translations(segment_id: str, out: dict[str, str], provider: str) -> None:
    db = new_session()
    try:
        for lang, text in out.items():
            db.add(
                SegmentTranslation(segment_id=segment_id, target_lang=lang, revision=0, text=text, provider=provider)
            )
        db.commit()
    finally:
        db.close()


def _close_rows(session_id, meeting_id, state, audio_ms, recording_path: Path, has_transcript: bool) -> None:
    db = new_session()
    try:
        now = datetime.now(UTC)
        db.query(LiveSession).filter_by(id=session_id).update({"state": state, "ended_at": now})
        meeting = db.query(Meeting).filter_by(id=meeting_id).first()
        if meeting is not None:
            meeting.actual_end = now
            meeting.audio_duration_seconds = audio_ms / 1000
            meeting.recording_path = config.to_storage_path(recording_path)
            meeting.status = (MeetingStatus.ANALYZING if has_transcript else MeetingStatus.COMPLETED).value
        db.commit()
    finally:
        db.close()


async def _finalize(meeting_id: str) -> None:
    from ..meetings.ingestion import _try_extract, _try_segment

    await _try_segment(meeting_id)
    await _try_extract(meeting_id)


# -- registry ----------------------------------------------------------------


def get_runtime(session_id: str) -> LiveRuntime | None:
    return _runtimes.get(session_id)


async def start_runtime(row: LiveSession, asr: StreamingASR, translator: Translator | None) -> LiveRuntime:
    runtime = LiveRuntime(
        session_id=row.id,
        meeting_id=row.meeting_id,
        source_language=row.source_language,
        asr=asr,
        translator=translator,
        recording_path=config.get_recordings_dir() / f"{row.meeting_id}.wav",
    )
    await runtime.start()
    _runtimes[row.id] = runtime
    return runtime


def _repair_wav(path: Path) -> float:
    """Rewrite the header of a WAV a crash left open (it claims 0 frames). Returns seconds."""
    pcm = path.read_bytes()[44:]  # wave writes a 44-byte header for mono PCM16
    pcm = pcm[: len(pcm) // 2 * 2]
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16_000)
        out.writeframes(pcm)
    return len(pcm) / 32_000


def recover_interrupted() -> int:
    """After a restart, close sessions whose runtime died and analyse what was captured."""
    db = new_session()
    try:
        rows = db.query(LiveSession).filter_by(state="live").all()
        meeting_ids = [row.meeting_id for row in rows]
        for row in rows:
            row.state, row.ended_at = "interrupted", datetime.now(UTC)
        stuck = db.query(Meeting).filter(Meeting.id.in_(meeting_ids)).all() if meeting_ids else []
        for meeting in stuck:
            meeting.status = MeetingStatus.ANALYZING.value
            wav = config.get_recordings_dir() / f"{meeting.id}.wav"
            if wav.exists():  # link it so playback works and retention can delete it
                meeting.audio_duration_seconds = _repair_wav(wav)
                meeting.recording_path = config.to_storage_path(wav)
        db.commit()
        # A live meeting left mid-analysis by the restart, too.
        pending = [m.id for m in db.query(Meeting).filter_by(source="live", status=MeetingStatus.ANALYZING.value)]
    finally:
        db.close()
    for meeting_id in pending:
        logger.info("Finishing live meeting %s interrupted by a restart", meeting_id)
        _spawn(_finalize(meeting_id))
    return len(pending)
