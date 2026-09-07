"""Provider-agnostic contract for turning meeting audio into attributed text.

Transcription and diarization are separate methods because they are separate
capabilities, and few providers do both well.  OpenAI's Whisper API
transcribes but has no notion of who spoke; pyannote diarizes but does not
transcribe; AssemblyAI does both in one pass.  Splitting the interface lets
the pipeline mix them — Whisper for words, pyannote for turns — instead of
forcing every provider to fake the half it lacks.

``speaker_label`` is the join key.  A ``TranscribedSegment`` carries one only
when the provider produced it; otherwise the pipeline merges diarization turns
onto segments by time overlap.  Labels are provider-local strings
("SPEAKER_00"), not MeetingOS speaker ids — resolving a label to a ``User`` is
the identification step's job, not the provider's.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    """A transcription or diarization call failed.

    Mirrors ``backend.ai.base.ProviderError``: ``retryable`` distinguishes a
    rate limit or a 5xx from a file the provider will never accept.
    """

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass
class TranscriptionConfig:
    """Static description of a transcription provider."""

    name: str
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    supports_diarization: bool = False
    supports_word_timestamps: bool = False
    supports_streaming: bool = False
    # Providers reject oversized uploads outright; the pipeline chunks long
    # meetings ahead of the call rather than discovering the limit at runtime.
    max_upload_bytes: int | None = None
    languages: list[str] = field(default_factory=lambda: ["en"])


@dataclass
class TranscribedSegment:
    """One contiguous run of speech, in milliseconds from the start of the audio."""

    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None
    # Per-segment language, not per-meeting. A bilingual meeting — EN chair,
    # RU finance report, KZ site update — is the normal case here, and a single
    # meeting-level tag cannot represent it. Providers that report only one
    # language for the whole file leave this None and the caller falls back.
    language: str | None = None
    speaker_label: str | None = None


@dataclass
class TranscriptionResult:
    """Everything a transcribe call produced."""

    segments: list[TranscribedSegment]
    language: str | None = None
    duration_seconds: float | None = None
    provider: str = ""
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """The full transcript as one string."""
        return " ".join(segment.text.strip() for segment in self.segments if segment.text.strip())


@dataclass
class SpeakerTurn:
    """A span attributed to one speaker by diarization."""

    start_ms: int
    end_ms: int
    speaker_label: str
    confidence: float | None = None


@dataclass
class DiarizationResult:
    """Speaker turns, plus the voice fingerprints that let speakers be matched.

    ``embeddings`` maps a provider-local label to a raw float32 vector, which
    is what ``Speaker.voice_embedding`` stores.  Providers that diarize without
    exposing embeddings leave it empty; identification then falls back to
    manual confirmation.
    """

    turns: list[SpeakerTurn]
    speaker_count: int = 0
    embeddings: dict[str, bytes] = field(default_factory=dict)
    embedding_model: str | None = None
    embedding_dim: int | None = None
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class TranscriptionProvider(ABC):
    """Interface every speech provider implements."""

    config: TranscriptionConfig

    def __init__(self, config: TranscriptionConfig) -> None:
        self.config = config

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe ``audio_path``.

        ``prompt`` seeds vocabulary — attendee names, product names, acronyms —
        which is the cheapest accuracy win available on meeting audio.
        """

    @abstractmethod
    async def diarize(self, audio_path: Path) -> DiarizationResult:
        """Segment ``audio_path`` by speaker.

        Providers without diarization raise ``TranscriptionError``; check
        ``config.supports_diarization`` before calling.
        """

    @abstractmethod
    def is_configured(self) -> bool:
        """True when credentials and models are present."""

    def check_upload_size(self, audio_path: Path) -> None:
        """Fail before upload when the file exceeds the provider's limit."""
        if self.config.max_upload_bytes is None:
            return
        if not audio_path.is_file():
            raise TranscriptionError(f"Audio file not found: {audio_path}")
        size = audio_path.stat().st_size
        if size > self.config.max_upload_bytes:
            limit_mb = self.config.max_upload_bytes / (1024 * 1024)
            raise TranscriptionError(
                f"{audio_path.name} is {size / (1024 * 1024):.1f} MB, over the "
                f"{limit_mb:.0f} MB limit for {self.config.name}. Chunk the audio first."
            )

    async def health(self) -> dict[str, Any]:
        """Cheap liveness probe. Does not call the upstream API."""
        return {
            "provider": self.config.name,
            "model": self.config.model,
            "configured": self.is_configured(),
            "supports_diarization": self.config.supports_diarization,
        }

    def __repr__(self) -> str:
        return f"<{type(self).__name__} model={self.config.model!r}>"


def merge_diarization(
    result: TranscriptionResult,
    diarization: DiarizationResult,
) -> TranscriptionResult:
    """Attach speaker labels to segments by maximum time overlap.

    Used when transcription and diarization come from different providers.
    A segment takes the label of the turn it overlaps most; segments with no
    overlapping turn keep ``speaker_label = None`` rather than being guessed at.
    """
    if not diarization.turns:
        return result

    for segment in result.segments:
        best_label: str | None = None
        best_overlap = 0
        for turn in diarization.turns:
            overlap = min(segment.end_ms, turn.end_ms) - max(segment.start_ms, turn.start_ms)
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = turn.speaker_label
        if best_label is not None:
            segment.speaker_label = best_label

    return result
