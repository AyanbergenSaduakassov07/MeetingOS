"""Stub: OpenAI-compatible endpoint owned by the customer.

Not implemented for v0.1.  This exists because the enterprise ask — "our
transcripts never leave our network" — is answered by pointing MeetingOS at a
self-hosted inference server (vLLM, Ollama, TGI, Azure OpenAI) that speaks the
OpenAI wire format.

Deliberately a separate class rather than ``OpenAIProvider`` with a different
``base_url``.  The wire format matches; the operating assumptions do not:

- No credential is required — many self-hosted deployments are unauthenticated
  behind a VPC — so ``is_configured`` must key off the URL, not an API key.
- Strict ``json_schema`` support is uneven across servers.  This provider has
  to detect support and fall back to prompt-and-repair, which is exactly the
  branch ``OpenAIProvider`` should not carry.
- Embedding models and dimensions are whatever the customer deployed, so
  ``embedding_dim`` cannot be defaulted and must be probed or configured.

Implement by subclassing ``OpenAIProvider`` and overriding ``is_configured``,
``extract``, and ``embed`` once a real endpoint exists to test against.
"""

from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel

from ...config import validate_inference_base_url
from ..base import Completion, LLMProvider, ProviderConfig, ProviderError

TModel = TypeVar("TModel", bound=BaseModel)

NOT_IMPLEMENTED = "The openai_compatible provider is not implemented yet (planned post-v0.1)."


def default_config() -> ProviderConfig:
    """Config for a customer-hosted OpenAI-compatible endpoint."""
    return ProviderConfig(
        name="openai_compatible",
        model=os.environ.get("OPENAI_COMPATIBLE_MODEL", ""),
        api_key_env="OPENAI_COMPATIBLE_API_KEY",
        base_url=validate_inference_base_url(os.environ.get("OPENAI_COMPATIBLE_BASE_URL"), provider="openai_compatible")
        or None,
        embedding_model=os.environ.get("OPENAI_COMPATIBLE_EMBEDDING_MODEL") or None,
        supports_embeddings=False,
        supports_native_json_schema=False,
    )


class OpenAICompatibleProvider(LLMProvider):
    """Placeholder so the orchestrator can name this provider before it exists."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        super().__init__(config or default_config())

    def is_configured(self) -> bool:
        # Keyed off the endpoint, not a key: these deployments are commonly
        # unauthenticated inside a private network.
        return bool(self.config.base_url)

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Completion:
        raise ProviderError(NOT_IMPLEMENTED)

    async def extract(
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> TModel:
        raise ProviderError(NOT_IMPLEMENTED)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderError(NOT_IMPLEMENTED)
