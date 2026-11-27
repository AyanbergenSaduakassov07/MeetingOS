"""OpenAI-wire endpoint the operator chooses: OpenRouter, vLLM, Ollama, TGI, Azure OpenAI.

A subclass of ``OpenAIProvider`` that differs where these servers differ:

- No credential is required — many self-hosted deployments are unauthenticated
  behind a VPC — so ``is_configured`` keys off the URL, not an API key.
- Strict ``json_schema`` support is uneven, so ``extract`` sends the schema in
  the prompt and parses the first JSON object out of the reply (fenced or not).
  Pydantic validation still rejects anything that does not fit.
- Embedding models are whatever the operator deployed, so embeddings are off
  unless ``OPENAI_COMPATIBLE_EMBEDDING_MODEL`` is set; ``AI_EMBEDDING_PROVIDER``
  can route them elsewhere.
"""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel

from ...config import validate_inference_base_url
from ..base import ProviderConfig, ProviderError
from .openai_provider import DEFAULT_MAX_TOKENS, OpenAIProvider

JSON_INSTRUCTION = "Reply with one JSON object and nothing else. It must validate against this JSON Schema:\n{schema}"


def default_config() -> ProviderConfig:
    """Config for an operator-chosen OpenAI-compatible endpoint."""
    embedding_model = os.environ.get("OPENAI_COMPATIBLE_EMBEDDING_MODEL") or None
    return ProviderConfig(
        name="openai_compatible",
        model=os.environ.get("OPENAI_COMPATIBLE_MODEL", ""),
        api_key_env="OPENAI_COMPATIBLE_API_KEY",
        base_url=validate_inference_base_url(os.environ.get("OPENAI_COMPATIBLE_BASE_URL"), provider="openai_compatible")
        or None,
        embedding_model=embedding_model,
        max_tokens=int(os.environ.get("OPENAI_COMPATIBLE_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
        supports_embeddings=embedding_model is not None,
        supports_native_json_schema=False,
    )


class OpenAICompatibleProvider(OpenAIProvider):
    """``OpenAIProvider`` without strict structured outputs or a mandatory key."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        super().__init__(config or default_config())

    def is_configured(self) -> bool:
        return bool(self.config.base_url)

    def _default_host(self) -> str:
        return "localhost"

    def _extract_request(
        self, prompt: str, schema: type[BaseModel], system: str | None
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        instruction = JSON_INSTRUCTION.format(schema=json.dumps(schema.model_json_schema()))
        return self._messages(prompt, f"{system}\n\n{instruction}" if system else instruction), {}

    @staticmethod
    def _parse_json(content: str) -> Any:
        # Models wrap JSON in prose or ``` fences; take the outermost object.
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end < start:
            raise json.JSONDecodeError("no JSON object in reply", content, 0)
        return json.loads(content[start : end + 1])

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.config.embedding_model:
            raise ProviderError(
                "openai_compatible has no embedding model: set OPENAI_COMPATIBLE_EMBEDDING_MODEL "
                "or route embeddings with AI_EMBEDDING_PROVIDER."
            )
        return await super().embed(texts)
