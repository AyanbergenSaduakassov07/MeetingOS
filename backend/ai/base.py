"""Provider-agnostic contract for the text/JSON side of MeetingOS.

Shaped after ``backend/backends/__init__.py``'s ``TTSBackend`` — a dataclass
of static capability metadata next to an async interface — with two
deliberate differences:

- It is an ``abc.ABC`` rather than a ``Protocol``.  The audio backends were
  structurally typed because they were selected by platform detection and
  never shared code.  Providers here *do* share code (retry policy, schema
  coercion, token accounting), so inheritance buys something.
- The unit of work is text and JSON, not numpy audio buffers.

``extract`` is the method that matters.  Meeting intelligence is a structured
extraction problem: everything downstream — decisions, action items, risks,
commitments — is a Pydantic model the provider must fill.  Providers
implement it with native structured-output support where they have it and
fall back to prompt-and-parse where they do not, but the contract is the
same: return a validated instance of ``schema`` or raise.
"""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

# Retries cover transient upstream failures (429, 5xx, connection resets).
# Deterministic failures — bad API key, malformed schema — must not be
# retried, so providers raise ``ProviderError`` with ``retryable=False``.
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 0.5


class ProviderError(RuntimeError):
    """A provider call failed.

    ``retryable`` tells ``retry_with_backoff`` whether another attempt could
    plausibly succeed.  Defaults to False so an unclassified error fails fast
    rather than burning three attempts and triple the latency.
    """

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass
class ProviderConfig:
    """Static description of a provider, read once at startup."""

    name: str
    model: str
    api_key_env: str
    base_url: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout_seconds: float = 120.0
    supports_native_json_schema: bool = False
    supports_embeddings: bool = False
    languages: list[str] = field(default_factory=lambda: ["en"])


@dataclass
class Usage:
    """Token accounting for one call. Surfaced so cost is measurable per meeting."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Completion:
    """A ``generate`` result: the text plus what it cost."""

    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)


async def retry_with_backoff(operation, *, description: str, max_attempts: int = MAX_ATTEMPTS):
    """Run ``operation`` (a zero-arg coroutine factory) with exponential backoff.

    Jittered so a burst of parallel segment extractions on one meeting does
    not synchronize its retries into a second thundering herd.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except ProviderError as exc:
            last_error = exc
            if not exc.retryable or attempt == max_attempts:
                raise
            delay = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            delay += random.uniform(0, delay / 2)
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                description,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    raise ProviderError(f"{description} exhausted {max_attempts} attempts") from last_error


class LLMProvider(ABC):
    """Interface every text/JSON provider implements."""

    config: ProviderConfig

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    # -- required ----------------------------------------------------------

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Completion:
        """Free-form completion. Used for summaries and narrative output."""

    @abstractmethod
    async def extract(
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> TModel:
        """Fill ``schema`` from ``prompt`` and return a validated instance.

        Raises ``ProviderError`` if the model's output cannot be coerced into
        ``schema`` after the provider's own repair attempt.  Callers get a
        typed object or an exception — never a dict to re-validate.
        """

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts``, returning one vector per input, order preserved.

        Providers without an embedding endpoint raise ``ProviderError``;
        check ``config.supports_embeddings`` before calling.
        """

    # -- shared ------------------------------------------------------------

    def resolved_max_tokens(self, override: int | None) -> int:
        """Every call sends an explicit token ceiling — never the API default."""
        return override if override is not None else self.config.max_tokens

    def resolved_temperature(self, override: float | None) -> float:
        return override if override is not None else self.config.temperature

    async def health(self) -> dict[str, Any]:
        """Cheap liveness probe for ``/health``. Does not call the upstream API."""
        return {
            "provider": self.config.name,
            "model": self.config.model,
            "configured": self.is_configured(),
            "supports_embeddings": self.config.supports_embeddings,
        }

    @abstractmethod
    def is_configured(self) -> bool:
        """True when credentials are present and the client could be built."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} model={self.config.model!r}>"
