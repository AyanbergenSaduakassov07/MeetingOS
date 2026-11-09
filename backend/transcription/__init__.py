"""Transcription layer — audio to attributed text.

``TRANSCRIPTION_PROVIDER`` selects the implementation, mirroring how
``AI_PROVIDER`` works in ``backend.ai.orchestrator``.
"""

from __future__ import annotations

import logging
import os

from .base import (
    DiarizationResult,
    SpeakerTurn,
    TranscribedSegment,
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionResult,
    merge_diarization,
)
from .providers.assemblyai_provider import AssemblyAIProvider
from .providers.faster_whisper_provider import FasterWhisperProvider
from .providers.pyannote_local_provider import PyannoteLocalProvider
from .providers.whisper_cloud_provider import WhisperCloudProvider

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "whisper_cloud"

PROVIDERS: dict[str, type[TranscriptionProvider]] = {
    "whisper_cloud": WhisperCloudProvider,
    "assemblyai": AssemblyAIProvider,
    "faster_whisper": FasterWhisperProvider,
    "pyannote_local": PyannoteLocalProvider,
}

_instances: dict[str, TranscriptionProvider] = {}


def available_providers() -> list[str]:
    """Names accepted by ``TRANSCRIPTION_PROVIDER``."""
    return sorted(PROVIDERS)


def get_transcription_provider(name: str | None = None) -> TranscriptionProvider:
    """Resolve the transcription provider, caching the instance."""
    resolved = (name or os.environ.get("TRANSCRIPTION_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if resolved not in PROVIDERS:
        raise ValueError(f"Unknown transcription provider {resolved!r}. Available: {', '.join(available_providers())}")
    if resolved not in _instances:
        _instances[resolved] = PROVIDERS[resolved]()
        logger.info("Transcription provider initialized: %s", resolved)
    return _instances[resolved]


def reset_providers() -> None:
    """Drop cached instances. Used by tests that swap environment variables."""
    _instances.clear()


__all__ = [
    "AssemblyAIProvider",
    "DiarizationResult",
    "FasterWhisperProvider",
    "PyannoteLocalProvider",
    "SpeakerTurn",
    "TranscribedSegment",
    "TranscriptionConfig",
    "TranscriptionError",
    "TranscriptionProvider",
    "TranscriptionResult",
    "WhisperCloudProvider",
    "available_providers",
    "get_transcription_provider",
    "merge_diarization",
    "reset_providers",
]
