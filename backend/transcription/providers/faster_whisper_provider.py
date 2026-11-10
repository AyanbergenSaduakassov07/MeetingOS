"""Local Whisper transcription via faster-whisper: audio never leaves the machine.

Optional dependency (``pip install faster-whisper``); the model downloads on
first use and is cached by the library. No diarization: segments stay
unattributed unless a diarizer is added later.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
from pathlib import Path

from ..base import (
    DiarizationResult,
    TranscribedSegment,
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionResult,
)

INSTALL_HINT = (
    "faster-whisper is not installed. Run `uv pip install -r backend/requirements-local.txt` to transcribe locally."
)

_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
_KAZAKH_ONLY = re.compile(r"[әғқңөұүһіӘҒҚҢӨҰҮҺІ]")  # letters Kazakh Cyrillic has and Russian lacks
_LETTER = re.compile(r"[^\W\d_]")


def _segment_language(text: str, file_language: str | None) -> str | None:
    """Tag each line's language from its script; meetings here mix EN, RU and KZ.

    faster-whisper detects language per window but does not report it per segment.
    shortcut: script-based. A Cyrillic line with no Kazakh-only letter reads as "ru",
    unless the whole file is Kazakh (short KZ lines often lack those letters);
    switch to per-segment detection if mixed RU/KZ tagging matters.
    """
    letters = len(_LETTER.findall(text))
    if not letters or len(_CYRILLIC.findall(text)) * 2 <= letters:
        return file_language
    if _KAZAKH_ONLY.search(text):
        return "kk"
    return "kk" if file_language == "kk" else "ru"


def default_config() -> TranscriptionConfig:
    """Config for local Whisper, overridable by environment."""
    return TranscriptionConfig(
        name="faster_whisper",
        # small (~0.5 GB) is faster but garbles Kazakh (85% WER vs 38% on FLEURS kk).
        model=os.environ.get("FASTER_WHISPER_MODEL", "large-v3-turbo"),
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
        # Tested on a messy 4-speaker recording: without VAD a segment after a long pause starts ~8 s early,
        # without multilingual a Russian aside in an English meeting is dropped, and word timestamps
        # tighten segment ends so citation jumps land on speech.
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            initial_prompt=prompt,
            vad_filter=True,
            multilingual=True,
            word_timestamps=True,
        )
        # segments is a lazy generator: decoding happens while iterating, so keep this in the worker thread.
        out = [
            TranscribedSegment(
                start_ms=round(s.start * 1000),
                end_ms=round(s.end * 1000),
                text=s.text.strip(),
                confidence=None,
                language=_segment_language(s.text, info.language),
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
