"""OpenAI provider.

Carries the embedding workload for MeetingOS — speaker matching, topic
clustering, and transcript retrieval all need vectors, and this is the
provider that has them.  It also implements ``generate`` and ``extract`` so a
deployment can run entirely on OpenAI without a second vendor.

``extract`` uses native structured outputs (``response_format`` of type
``json_schema`` with ``strict: true``), which constrains decoding to the
schema rather than asking the model to behave.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ...config import validate_inference_base_url
from ..base import Completion, LLMProvider, ProviderConfig, ProviderError, Usage, retry_with_backoff

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

DEFAULT_MODEL = "gpt-4o"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIM = 1536
DEFAULT_MAX_TOKENS = 4096

# The embeddings endpoint accepts a batch, but a whole meeting's segments in
# one request will exceed the payload limit. Chunk instead.
EMBED_BATCH_SIZE = 96


def default_config() -> ProviderConfig:
    """Config for the OpenAI provider, overridable by environment."""
    return ProviderConfig(
        name="openai",
        model=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        api_key_env="OPENAI_API_KEY",
        base_url=validate_inference_base_url(os.environ.get("OPENAI_BASE_URL") or None, provider="openai"),
        embedding_model=os.environ.get("OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        embedding_dim=int(os.environ.get("OPENAI_EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM)),
        max_tokens=int(os.environ.get("OPENAI_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
        supports_embeddings=True,
        supports_native_json_schema=True,
    )


def _strict_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Render a Pydantic model as a JSON Schema that strict mode accepts.

    Strict mode requires ``additionalProperties: false`` on every object and
    demands that *every* property be listed in ``required`` — optional fields
    are expressed as nullable types instead, which Pydantic already emits.
    """
    rendered = schema.model_json_schema()

    def _tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                properties = node.get("properties")
                if isinstance(properties, dict):
                    node["required"] = list(properties.keys())
            for value in node.values():
                _tighten(value)
        elif isinstance(node, list):
            for item in node:
                _tighten(item)

    _tighten(rendered)
    return rendered


class OpenAIProvider(LLMProvider):
    """``LLMProvider`` backed by the OpenAI chat-completions and embeddings APIs."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        super().__init__(config or default_config())
        self._client = None

    # -- plumbing ----------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.config.api_key_env))

    def _get_client(self):
        """Build the async client lazily so import never requires credentials."""
        if self._client is not None:
            return self._client
        try:
            from openai import AsyncOpenAI  # lazy: optional dependency
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise ProviderError("The `openai` package is not installed.") from exc

        if not self.is_configured():
            raise ProviderError(f"{self.config.api_key_env} is not set.")

        self._client = AsyncOpenAI(
            api_key=os.environ[self.config.api_key_env],
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )
        return self._client

    @staticmethod
    def _wrap_error(exc: Exception) -> ProviderError:
        """Classify an SDK exception into a retryable/terminal ProviderError."""
        import openai  # lazy: only needed on the error path

        if isinstance(exc, openai.RateLimitError):
            return ProviderError(f"OpenAI rate limited: {exc}", retryable=True, status_code=429)
        if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
            return ProviderError(f"OpenAI connection error: {exc}", retryable=True)
        if isinstance(exc, openai.APIStatusError):
            status = exc.status_code
            return ProviderError(f"OpenAI API error {status}: {exc}", retryable=status >= 500, status_code=status)
        return ProviderError(f"OpenAI call failed: {exc}")

    def _messages(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _usage(response: Any) -> Usage:
        usage = getattr(response, "usage", None)
        if usage is None:
            return Usage()
        return Usage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    # -- interface ---------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Completion:
        client = self._get_client()

        async def _call():
            try:
                return await client.chat.completions.create(
                    model=self.config.model,
                    messages=self._messages(prompt, system),
                    max_tokens=self.resolved_max_tokens(max_tokens),
                    temperature=self.resolved_temperature(temperature),
                )
            except Exception as exc:
                raise self._wrap_error(exc) from exc

        response = await retry_with_backoff(_call, description="openai.generate")
        text = response.choices[0].message.content or ""
        return Completion(text=text, model=response.model, usage=self._usage(response))

    async def extract(
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> TModel:
        client = self._get_client()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": _strict_schema(schema),
                "strict": True,
            },
        }

        async def _call():
            try:
                return await client.chat.completions.create(
                    model=self.config.model,
                    messages=self._messages(prompt, system),
                    max_tokens=self.resolved_max_tokens(max_tokens),
                    response_format=response_format,
                )
            except Exception as exc:
                raise self._wrap_error(exc) from exc

        response = await retry_with_backoff(_call, description="openai.extract")

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ProviderError(
                f"Extraction hit the {self.resolved_max_tokens(max_tokens)}-token ceiling and was truncated."
            )

        content = choice.message.content or ""
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Extraction returned non-JSON content: {exc}") from exc

        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            raise ProviderError(f"Extraction did not satisfy {schema.__name__}: {exc}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        client = self._get_client()
        model = self.config.embedding_model or DEFAULT_EMBEDDING_MODEL
        vectors: list[list[float]] = []

        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[start : start + EMBED_BATCH_SIZE]

            async def _call(batch=batch):
                try:
                    return await client.embeddings.create(model=model, input=batch)
                except Exception as exc:
                    raise self._wrap_error(exc) from exc

            response = await retry_with_backoff(_call, description="openai.embed")
            # The API documents order preservation, but sorting by index is
            # cheap and makes that guarantee local rather than assumed.
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)

        return vectors
