"""Stub: AssemblyAI transcription + diarization.

Not implemented for v0.1.  Planned as the single-call path — AssemblyAI
returns words, timings, and speaker labels from one upload, which removes the
Whisper + pyannote join and its overlap-matching failure modes.

Implementation notes for whoever picks this up:

- The API is job-based, not request/response: upload, POST a transcript job,
  then poll ``status`` until ``completed`` or ``error``.  ``transcribe`` has to
  own that polling loop with a timeout; a two-hour board meeting will not
  return inside one HTTP request.
- Diarization is a request flag (``speaker_labels``), so ``transcribe`` and
  ``diarize`` would submit the same job.  Cache the result by upload URL or
  the pipeline pays for the meeting twice.
- Speaker labels come back as "A", "B", "C" with no embeddings, so
  ``DiarizationResult.embeddings`` stays empty and cross-meeting speaker
  matching needs a separate embedding step.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..base import (
    DiarizationResult,
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionResult,
)

NOT_IMPLEMENTED = "The assemblyai provider is not implemented yet (planned post-v0.1)."


def default_config() -> TranscriptionConfig:
    """Config for AssemblyAI, overridable by environment."""
    return TranscriptionConfig(
        name="assemblyai",
        model=os.environ.get("ASSEMBLYAI_MODEL", "best"),
        api_key_env="ASSEMBLYAI_API_KEY",
        supports_diarization=True,
        supports_word_timestamps=True,
        supports_streaming=True,
    )


class AssemblyAIProvider(TranscriptionProvider):
    """Placeholder so the pipeline can name this provider before it exists."""

    def __init__(self, config: TranscriptionConfig | None = None) -> None:
        super().__init__(config or default_config())

    def is_configured(self) -> bool:
        return bool(self.config.api_key_env and os.environ.get(self.config.api_key_env))

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        raise TranscriptionError(NOT_IMPLEMENTED)

    async def diarize(self, audio_path: Path) -> DiarizationResult:
        raise TranscriptionError(NOT_IMPLEMENTED)
