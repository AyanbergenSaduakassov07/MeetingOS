"""Anthropic provider — the default for MeetingOS extraction.

Structured extraction goes through forced tool use: the target Pydantic model
becomes a single tool's ``input_schema`` with ``strict: true``, and
``tool_choice`` forces Claude to call it.  The model therefore cannot answer
in prose, and ``tool_use.input`` is guaranteed to satisfy the schema.

Two model-family constraints are handled here rather than left to callers:

- Sampling parameters (``temperature``, ``top_p``, ``top_k``) are **removed**
  on Opus 5 / Opus 4.8 / Opus 4.7 / Sonnet 5 / Fable 5 and return a 400.
  ``_supports_sampling`` gates the parameter instead of sending it blindly.
- Thinking is adaptive by default on Opus 5, so the ``thinking`` parameter is
  omitted entirely rather than configured with the removed ``budget_tokens``.
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

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000

# Model families that reject temperature/top_p/top_k with a 400.
SAMPLING_UNSUPPORTED_PREFIXES = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)

EXTRACT_TOOL_NAME = "record_extraction"


def default_config() -> ProviderConfig:
    """Config for the Anthropic provider, overridable by environment."""
    return ProviderConfig(
        name="anthropic",
        model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        api_key_env="ANTHROPIC_API_KEY",
        max_tokens=int(os.environ.get("ANTHROPIC_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
        # No embeddings endpoint. Pair with an embedding-capable provider
        # rather than pretending otherwise — speaker and topic retrieval
        # both need vectors.
        supports_embeddings=False,
        supports_native_json_schema=True,
    )


def _strict_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Render a Pydantic model as a strict JSON Schema.

    Strict tool use requires ``additionalProperties: false`` on every object
    node, including the ``$defs`` that nested models generate.
    """
    rendered = schema.model_json_schema()

    def _tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                _tighten(value)
        elif isinstance(node, list):
            for item in node:
                _tighten(item)

    _tighten(rendered)
    return rendered


class AnthropicProvider(LLMProvider):
    """``LLMProvider`` backed by the Anthropic Messages API."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        super().__init__(config or default_config())
        self._client = None

    # -- plumbing ----------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.config.api_key_env))

    def _supports_sampling(self) -> bool:
        return not self.config.model.startswith(SAMPLING_UNSUPPORTED_PREFIXES)

    def _get_client(self):
        """Build the async client lazily so import never requires credentials."""
        if self._client is not None:
            return self._client
        try:
            from anthropic import AsyncAnthropic  # lazy: optional dependency
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise ProviderError("The `anthropic` package is not installed.") from exc

        if not self.is_configured():
            raise ProviderError(f"{self.config.api_key_env} is not set.")

        # base_url is passed explicitly, even when it is None. The Anthropic
        # SDK reads ANTHROPIC_BASE_URL from the environment on its own, so
        # leaving it out did not mean "use the default" — it meant "use
        # whatever the environment says, unchecked". Since anthropic is the
        # DEFAULT provider, that left the inference-host allowlist bypassed on
        # the path most deployments actually take.
        self._client = AsyncAnthropic(
            timeout=self.config.timeout_seconds,
            base_url=validate_inference_base_url(os.environ.get("ANTHROPIC_BASE_URL") or None, provider="anthropic"),
        )
        return self._client

    @staticmethod
    def _wrap_error(exc: Exception) -> ProviderError:
        """Classify an SDK exception into a retryable//terminal ProviderError.

        Most-specific first: a rate limit and a 500 are worth another attempt,
        a bad key or a malformed request never is.
        """
        import anthropic  # lazy: only needed on the error path

        if isinstance(exc, anthropic.RateLimitError):
            return ProviderError(f"Anthropic rate limited: {exc}", retryable=True, status_code=429)
        if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
            return ProviderError(f"Anthropic connection error: {exc}", retryable=True)
        if isinstance(exc, anthropic.APIStatusError):
            status = exc.status_code
            return ProviderError(f"Anthropic API error {status}: {exc}", retryable=status >= 500, status_code=status)
        return ProviderError(f"Anthropic call failed: {exc}")

    def _request_kwargs(self, max_tokens: int | None, temperature: float | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.resolved_max_tokens(max_tokens),
        }
        if self._supports_sampling():
            kwargs["temperature"] = self.resolved_temperature(temperature)
        return kwargs

    @staticmethod
    def _usage(response: Any) -> Usage:
        usage = getattr(response, "usage", None)
        if usage is None:
            return Usage()
        return Usage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
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
        kwargs = self._request_kwargs(max_tokens, temperature)
        if system:
            kwargs["system"] = system

        async def _call():
            try:
                return await client.messages.create(messages=[{"role": "user", "content": prompt}], **kwargs)
            except Exception as exc:
                raise self._wrap_error(exc) from exc

        response = await retry_with_backoff(_call, description="anthropic.generate")

        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise ProviderError(f"Anthropic declined the request (category={category}).")

        text = "".join(block.text for block in response.content if block.type == "text")
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
        kwargs = self._request_kwargs(max_tokens, None)
        if system:
            kwargs["system"] = system

        tool = {
            "name": EXTRACT_TOOL_NAME,
            "description": schema.__doc__ or f"Record the extracted {schema.__name__}.",
            "input_schema": _strict_schema(schema),
            "strict": True,
        }

        async def _call():
            try:
                return await client.messages.create(
                    messages=[{"role": "user", "content": prompt}],
                    tools=[tool],
                    tool_choice={"type": "tool", "name": EXTRACT_TOOL_NAME},
                    **kwargs,
                )
            except Exception as exc:
                raise self._wrap_error(exc) from exc

        response = await retry_with_backoff(_call, description="anthropic.extract")

        for block in response.content:
            if block.type == "tool_use" and block.name == EXTRACT_TOOL_NAME:
                # Escaping differs across model families, so the input is
                # always parsed rather than string-matched. It arrives as a
                # dict from the SDK; the str branch covers raw passthrough.
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                try:
                    return schema.model_validate(payload)
                except ValidationError as exc:
                    raise ProviderError(f"Extraction did not satisfy {schema.__name__}: {exc}") from exc

        raise ProviderError(f"Anthropic returned no {EXTRACT_TOOL_NAME} tool call.")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from ...meetings.egress_log import host_of, logged_call

        with logged_call(
            self.config.name,
            "embed",
            model=self.config.embedding_model or self.config.model,
            endpoint_host=host_of(self.config.base_url, default=self._default_host()),
            texts=texts,
        ):
            return await self._embed(texts)

    def _default_host(self) -> str:
        return "api.openai.com" if self.config.name == "openai" else "api.anthropic.com"

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderError(
            "Anthropic exposes no embeddings endpoint. Set AI_EMBEDDING_PROVIDER "
            "to a provider whose config reports supports_embeddings=True."
        )
