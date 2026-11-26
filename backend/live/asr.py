"""Streaming recognizers behind ``StreamingASR``.

``local``: faster-whisper on this machine, cut at pauses. Audio never leaves it,
so it is the default while no cloud key is configured. Finals only, no partials.
``stub``: a fixed caption per few seconds of audio, for UI work and tests.
Cloud adapters (Google Chirp 3, Azure) plug in here once a key exists.
"""

from __future__ import annotations

import asyncio
import logging
import os
from array import array
from collections.abc import AsyncIterator

from .types import AsrEvent

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BYTES_PER_MS = SAMPLE_RATE * 2 // 1000
SPEECH_RMS = 500  # int16 RMS; ~-36 dBFS, above room noise on a laptop mic
PAUSE_MS = 700  # silence that ends an utterance
MIN_UTTERANCE_MS = 1000
MAX_UTTERANCE_MS = 15_000  # cut long monologues so captions keep flowing
MAX_PENDING_UTTERANCES = 8  # ~2 min of speech queued at most
_END = object()
_models: dict[str, object] = {}
_model_lock = asyncio.Lock()


def _rms(pcm16: bytes) -> float:
    samples = array("h", pcm16[: len(pcm16) // 2 * 2])
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


class _QueueASR:
    """Shared event-queue plumbing."""

    name = "base"

    def __init__(self) -> None:
        self._events: asyncio.Queue = asyncio.Queue()
        self.language: str | None = None

    async def start(self, *, language: str | None) -> None:
        self.language = language

    async def events(self) -> AsyncIterator[AsrEvent]:
        while (item := await self._events.get()) is not _END:
            yield item


class StubASR(_QueueASR):
    name = "stub"

    def __init__(self, every_ms: int = 3000) -> None:
        super().__init__()
        self.every_ms, self._received_ms, self._n = every_ms, 0, 0

    async def send(self, pcm16: bytes) -> None:
        self._received_ms += len(pcm16) // BYTES_PER_MS
        while self._received_ms >= (self._n + 1) * self.every_ms:
            start = self._n * self.every_ms
            self._n += 1
            await self._events.put(
                AsrEvent("final", f"Test caption {self._n}.", start, start + self.every_ms, self.language or "en")
            )

    async def close(self) -> None:
        await self._events.put(_END)


class LocalWhisperASR(_QueueASR):
    """Pause-cut pseudo-streaming over the batch faster-whisper model."""

    name = "faster_whisper"

    def __init__(self) -> None:
        super().__init__()
        self._buf = bytearray()
        self._buf_start_ms = 0  # audio time of _buf[0]
        self._total_ms = 0
        self._silence_ms = 0
        self._has_speech = False
        self._jobs: asyncio.Queue = asyncio.Queue(maxsize=MAX_PENDING_UTTERANCES)
        self._worker: asyncio.Task | None = None
        self._model = None

    async def start(self, *, language: str | None) -> None:
        from ..transcription.providers.faster_whisper_provider import FasterWhisperProvider, default_config

        await super().start(language=language)
        config = default_config()
        config.model = os.environ.get("MEETINGOS_LIVE_WHISPER_MODEL", config.model)
        async with _model_lock:  # one copy per model name, shared by every session
            if config.model not in _models:
                _models[config.model] = await asyncio.to_thread(FasterWhisperProvider(config)._load_model)
        self._model = _models[config.model]
        self._worker = asyncio.create_task(self._run())

    async def send(self, pcm16: bytes) -> None:
        chunk_ms = len(pcm16) // BYTES_PER_MS
        self._buf.extend(pcm16)
        self._total_ms += chunk_ms
        if _rms(pcm16) >= SPEECH_RMS:
            self._has_speech, self._silence_ms = True, 0
        else:
            self._silence_ms += chunk_ms
        buf_ms = len(self._buf) // BYTES_PER_MS
        if not self._has_speech and buf_ms > PAUSE_MS:
            self._cut(keep_ms=300)  # drop leading silence, keep a little lead-in
        elif self._has_speech and (
            (self._silence_ms >= PAUSE_MS and buf_ms >= MIN_UTTERANCE_MS) or buf_ms >= MAX_UTTERANCE_MS
        ):
            try:
                self._jobs.put_nowait((bytes(self._buf), self._buf_start_ms))
            except asyncio.QueueFull:  # the machine cannot keep up; drop rather than lag without bound
                logger.warning("live: recognizer is behind, dropped %d ms of audio", buf_ms)
            self._cut(keep_ms=0)
            self._has_speech = False

    def _cut(self, keep_ms: int) -> None:
        keep = keep_ms * BYTES_PER_MS
        dropped = len(self._buf) - keep
        if dropped > 0:
            del self._buf[:dropped]
            self._buf_start_ms += dropped // BYTES_PER_MS

    async def _run(self) -> None:
        while (job := await self._jobs.get()) is not _END:
            pcm, start_ms = job
            try:
                for event in await asyncio.to_thread(self._transcribe, pcm, start_ms):
                    await self._events.put(event)
            except Exception:  # one bad utterance must not end the session
                logger.exception("live: local transcription failed for one utterance")
        await self._events.put(_END)

    def _transcribe(self, pcm: bytes, start_ms: int) -> list[AsrEvent]:
        import numpy as np

        from ..transcription.providers.faster_whisper_provider import _segment_language

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = self._model.transcribe(audio, language=self.language, vad_filter=True)
        return [
            AsrEvent(
                "final",
                s.text.strip(),
                start_ms + round(s.start * 1000),
                start_ms + round(s.end * 1000),
                _segment_language(s.text, info.language),
            )
            for s in segments
            if s.text.strip()
        ]

    async def close(self) -> None:
        if self._has_speech and self._buf:
            await self._jobs.put((bytes(self._buf), self._buf_start_ms))
        self._buf.clear()
        await self._jobs.put(_END)
        if self._worker is None:
            await self._events.put(_END)

    def abort(self) -> None:
        """Stop transcribing whatever is still queued (end of session gave up waiting)."""
        if self._worker is not None:
            self._worker.cancel()


ASR_PROVIDERS = {"local": LocalWhisperASR, "stub": StubASR}


def get_asr(name: str | None = None):
    resolved = (name or os.environ.get("MEETINGOS_LIVE_ASR") or "local").strip().lower()
    if resolved not in ASR_PROVIDERS:
        raise ValueError(f"Unknown live ASR '{resolved}'. Use one of: {', '.join(ASR_PROVIDERS)}")
    return ASR_PROVIDERS[resolved]()
