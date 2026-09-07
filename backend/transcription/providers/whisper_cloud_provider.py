"""OpenAI Whisper API transcription.

The v0.1 default: no GPU, no model download, no cold start — the three things
that made the local Whisper path in the old codebase painful to operate.

It does not diarize.  The Whisper API returns words and timings with no
speaker attribution at all, so ``diarize`` raises rather than inventing turns.
A meeting that needs "who said what" runs this for text and a diarizing
provider for turns, joined by ``base.merge_diarization``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from pathlib import Path
from typing import Any

from ...config import validate_inference_base_url
from ..base import (
    DiarizationResult,
    TranscribedSegment,
    TranscriptionConfig,
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionResult,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "whisper-1"
# The endpoint rejects uploads over 25 MB.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 1.0


def default_config() -> TranscriptionConfig:
    """Config for the hosted Whisper provider, overridable by environment."""
    return TranscriptionConfig(
        name="whisper_cloud",
        model=os.environ.get("WHISPER_CLOUD_MODEL", DEFAULT_MODEL),
        api_key_env="OPENAI_API_KEY",
        base_url=validate_inference_base_url(os.environ.get("OPENAI_BASE_URL") or None, provider="whisper_cloud"),
        supports_diarization=False,
        supports_word_timestamps=True,
        max_upload_bytes=MAX_UPLOAD_BYTES,
    )


class WhisperCloudProvider(TranscriptionProvider):
    """``TranscriptionProvider`` backed by OpenAI's hosted Whisper endpoint."""

    def __init__(self, config: TranscriptionConfig | None = None) -> None:
        super().__init__(config or default_config())
        self._client = None

    # -- plumbing ----------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.config.api_key_env and os.environ.get(self.config.api_key_env))

    def _get_client(self):
        """Build the async client lazily so import never requires credentials."""
        if self._client is not None:
            return self._client
        try:
            from openai import AsyncOpenAI  # lazy: optional dependency
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise TranscriptionError("The `openai` package is not installed.") from exc

        if not self.is_configured():
            raise TranscriptionError(f"{self.config.api_key_env} is not set.")

        self._client = AsyncOpenAI(
            api_key=os.environ[self.config.api_key_env],
            base_url=self.config.base_url,
        )
        return self._client

    @staticmethod
    def _wrap_error(exc: Exception) -> TranscriptionError:
        """Classify an SDK exception into a retryable/terminal TranscriptionError."""
        import openai  # lazy: only needed on the error path

        if isinstance(exc, openai.RateLimitError):
            return TranscriptionError(f"Whisper rate limited: {exc}", retryable=True, status_code=429)
        if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
            return TranscriptionError(f"Whisper connection error: {exc}", retryable=True)
        if isinstance(exc, openai.APIStatusError):
            status = exc.status_code
            return TranscriptionError(
                f"Whisper API error {status}: {exc}",
                retryable=status >= 500,
                status_code=status,
            )
        return TranscriptionError(f"Whisper call failed: {exc}")

    async def _call_with_retry(self, operation, *, description: str):
        """Retry transient failures with jittered exponential backoff."""
        last_error: TranscriptionError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await operation()
            except TranscriptionError as exc:
                last_error = exc
                if not exc.retryable or attempt == MAX_ATTEMPTS:
                    raise
                delay = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                delay += random.uniform(0, delay / 2)
                logger.warning("%s failed (attempt %d/%d): %s", description, attempt, MAX_ATTEMPTS, exc)
                await asyncio.sleep(delay)

        raise TranscriptionError(f"{description} exhausted {MAX_ATTEMPTS} attempts") from last_error

    @staticmethod
    def _to_segments(payload: dict[str, Any]) -> list[TranscribedSegment]:
        """Convert verbose_json segments into ``TranscribedSegment``s.

        Whisper reports seconds as floats; MeetingOS stores integer
        milliseconds so segment boundaries stay exact under arithmetic.

        Language is tagged **per segment**. Whisper's ``verbose_json`` reports a
        single top-level ``language`` for the file, and where a per-segment
        ``language`` key is present it is preferred — a meeting that runs EN
        chair / RU finance / KZ site update is the normal case here, and one
        meeting-level tag cannot represent it. When the provider offers only the
        file-level value every segment inherits it, which is honest about what
        was actually detected rather than guessing per utterance.
        """
        file_language = payload.get("language")
        segments: list[TranscribedSegment] = []
        for raw in payload.get("segments") or []:
            # avg_logprob is a log probability (<= 0), not a 0..1 confidence.
            # Exponentiating it gives a comparable per-segment score.
            logprob = raw.get("avg_logprob")
            confidence = None
            if isinstance(logprob, (int, float)):
                confidence = min(1.0, max(0.0, 2.718281828 ** float(logprob)))

            segments.append(
                TranscribedSegment(
                    start_ms=round(float(raw.get("start", 0.0) * 1000)),
                    end_ms=round(float(raw.get("end", 0.0) * 1000)),
                    text=(raw.get("text") or "").strip(),
                    confidence=confidence,
                    language=raw.get("language") or file_language,
                )
            )

        # Fall back to one segment covering the whole clip when the response
        # carries only flat text.
        if not segments and payload.get("text"):
            duration = float(payload.get("duration") or 0.0)
            segments.append(
                TranscribedSegment(
                    start_ms=0,
                    end_ms=round(duration * 1000),
                    text=str(payload["text"]).strip(),
                )
            )
        return segments

    # -- interface ---------------------------------------------------------

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        self.check_upload_size(audio_path)
        client = self._get_client()

        async def _call():
            try:
                # Opened per attempt: a retry needs the handle rewound, and
                # reusing a consumed file object silently uploads zero bytes.
                with audio_path.open("rb") as handle:
                    return await client.audio.transcriptions.create(
                        model=self.config.model,
                        file=handle,
                        response_format="verbose_json",
                        timestamp_granularities=["segment"],
                        **({"language": language} if language else {}),
                        **({"prompt": prompt} if prompt else {}),
                    )
            except Exception as exc:
                raise self._wrap_error(exc) from exc

        response = await self._call_with_retry(_call, description="whisper_cloud.transcribe")

        payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        return TranscriptionResult(
            segments=self._to_segments(payload),
            language=payload.get("language") or language,
            duration_seconds=payload.get("duration"),
            provider=self.config.name,
            model=self.config.model,
            raw=payload,
        )

    async def diarize(self, audio_path: Path) -> DiarizationResult:
        raise TranscriptionError(
            "The Whisper API does not diarize. Pair this provider with a "
            "diarizing one (assemblyai, pyannote_local) and join the results "
            "with backend.transcription.base.merge_diarization."
        )
