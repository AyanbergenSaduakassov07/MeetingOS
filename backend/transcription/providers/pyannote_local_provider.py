"""Stub: local pyannote diarization.

Not implemented for v0.1.  Planned as the on-premise answer and as the source
of the voice embeddings that ``Speaker.voice_embedding`` stores — pyannote is
the only option here that returns them, which is what makes cross-meeting
speaker identification possible at all.

Implementation notes for whoever picks this up:

- Diarization only.  ``transcribe`` stays unimplemented on purpose; pair this
  with ``whisper_cloud`` (or a local Whisper) and join via
  ``base.merge_diarization``.
- Requires torch, the pyannote.audio package, and a HuggingFace token for the
  gated pipeline weights.  That dependency is exactly what v0.1 avoids
  shipping, so it belongs behind an optional extra rather than in the default
  requirements.
- The pipeline is synchronous and CPU/GPU-bound; run it through
  ``asyncio.to_thread`` so it does not block the event loop.
- Emit embeddings as float32 bytes and set ``embedding_model`` /
  ``embedding_dim`` on the result — vectors from different models are not
  comparable, and ``Speaker`` records both for that reason.
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

NOT_IMPLEMENTED = "The pyannote_local provider is not implemented yet (planned post-v0.1)."


def default_config() -> TranscriptionConfig:
    """Config for local pyannote diarization, overridable by environment."""
    return TranscriptionConfig(
        name="pyannote_local",
        model=os.environ.get("PYANNOTE_MODEL", "pyannote/speaker-diarization-3.1"),
        api_key_env="HUGGINGFACE_TOKEN",
        supports_diarization=True,
        supports_word_timestamps=False,
        # Runs locally: no upload, so no upload ceiling.
        max_upload_bytes=None,
    )


class PyannoteLocalProvider(TranscriptionProvider):
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
        raise TranscriptionError("pyannote_local diarizes only — use a transcription provider for text.")

    async def diarize(self, audio_path: Path) -> DiarizationResult:
        raise TranscriptionError(NOT_IMPLEMENTED)
