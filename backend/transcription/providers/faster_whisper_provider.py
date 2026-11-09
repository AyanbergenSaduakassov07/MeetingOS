"""Local Whisper transcription via faster-whisper: audio never leaves the machine.

Optional dependency (``pip install faster-whisper``); the model downloads on
first use and is cached by the library. No diarization: segments stay
unattributed unless a diarizer is added later.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

from ..base import (
    DiarizationResult,
    TranscribedSegment,
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionResult,
)

INSTALL_HINT = "faster-whisper is not installed. Run `uv pip install faster-whisper` to transcribe locally."


def default_config() -> TranscriptionConfig:
    """Config for local Whisper, overridable by environment."""
    return TranscriptionConfig(
        name="faster_whisper",
        model=os.environ.get("FASTER_WHISPER_MODEL", "small"),
        api_key_env=None,
        supports_diarization=False,
        supports_word_timestamps=False,
        max_upload_bytes=None,
    )


class FasterWhisperProvider(TranscriptionProvider):
    """Runs Whisper on the local CPU/GPU; the model loads once per process."""

    def __init__(self, config: TranscriptionConfig | None = None) -> None:
        super().__init__(config or default_config())
        self._model = None

    def is_configured(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def _load_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscriptionError(INSTALL_HINT) from exc
            device = os.environ.get("FASTER_WHISPER_DEVICE", "auto")
            compute_type = os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "default")
            self._model = WhisperModel(self.config.model, device=device, compute_type=compute_type)
        return self._model

    def _transcribe_sync(self, audio_path: Path, language: str | None, prompt: str | None) -> TranscriptionResult:
        model = self._load_model()
        segments, info = model.transcribe(str(audio_path), language=language, initial_prompt=prompt)
        # segments is a lazy generator: decoding happens while iterating, so keep this in the worker thread.
        out = [
            TranscribedSegment(
                start_ms=round(s.start * 1000),
                end_ms=round(s.end * 1000),
                text=s.text.strip(),
                confidence=None,
                language=info.language,
                speaker_label=None,
            )
            for s in segments
            if s.text.strip()
        ]
        return TranscriptionResult(
            segments=out,
            language=info.language,
            duration_seconds=info.duration,
            provider=self.config.name,
            model=self.config.model,
            raw=None,
        )

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language, prompt)

    async def diarize(self, audio_path: Path) -> DiarizationResult:
        raise TranscriptionError("faster_whisper does not diarize.")
