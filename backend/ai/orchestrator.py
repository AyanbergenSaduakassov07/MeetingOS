"""Provider selection.

``AI_PROVIDER`` picks the text/JSON provider; everything downstream asks for
``get_llm_provider()`` and never names a vendor.

``AI_EMBEDDING_PROVIDER`` exists as a second knob because the default text
provider cannot embed — Anthropic has no embeddings endpoint — and a
deployment should not be forced onto one vendor for both jobs.  When it is
unset, the text provider is used if it supports embeddings, otherwise the
first configured provider that does.

Providers are constructed once and cached: the clients hold connection pools,
and rebuilding one per request throws that away.
"""

from __future__ import annotations

import logging
import os

from .base import LLMProvider
from .providers.anthropic_provider import AnthropicProvider
from .providers.openai_compatible_provider import OpenAICompatibleProvider
from .providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "anthropic"

PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "openai_compatible": OpenAICompatibleProvider,
}

# Order used when auto-selecting an embedding provider.
EMBEDDING_PREFERENCE = ("openai", "openai_compatible")

_instances: dict[str, LLMProvider] = {}


class UnknownProviderError(ValueError):
    """``AI_PROVIDER`` named something that is not registered."""


def available_providers() -> list[str]:
    """Names accepted by ``AI_PROVIDER``."""
    return sorted(PROVIDERS)


def _build(name: str) -> LLMProvider:
    """Return the cached instance for ``name``, constructing it on first use."""
    if name not in PROVIDERS:
        raise UnknownProviderError(f"Unknown AI provider {name!r}. Available: {', '.join(available_providers())}")
    if name not in _instances:
        _instances[name] = PROVIDERS[name]()
        logger.info("AI provider initialized: %s", name)
    return _instances[name]


def get_llm_provider(name: str | None = None) -> LLMProvider:
    """Resolve the text/JSON provider.

    Explicit ``name`` wins, then ``AI_PROVIDER``, then the default.  Selection
    does not require credentials — an unconfigured provider constructs fine and
    fails at call time with a clear message, so ``/health`` can report the
    problem instead of the process refusing to boot.
    """
    resolved = (name or os.environ.get("AI_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    return _build(resolved)


def get_embedding_provider() -> LLMProvider:
    """Resolve the provider used for ``embed``.

    Prefers a provider that both supports embeddings and has credentials; if
    none is credentialed, still returns one that *supports* embeddings rather
    than falling back to the text provider.  That choice is about the error
    the caller sees: an uncredentialed OpenAI provider fails with
    "OPENAI_API_KEY is not set", which names the fix, whereas falling back to
    Anthropic fails with "Anthropic exposes no embeddings endpoint", which
    sends the reader after the wrong problem.
    """
    explicit = os.environ.get("AI_EMBEDDING_PROVIDER")
    if explicit:
        return _build(explicit.strip().lower())

    text_provider = get_llm_provider()
    if text_provider.config.supports_embeddings:
        return text_provider

    fallback: LLMProvider | None = None
    for candidate in EMBEDDING_PREFERENCE:
        provider = _build(candidate)
        if not provider.config.supports_embeddings:
            continue
        if provider.is_configured():
            logger.info("Embeddings routed to %s (%s cannot embed)", candidate, text_provider.config.name)
            return provider
        fallback = fallback or provider

    if fallback is not None:
        logger.warning(
            "Embeddings routed to %s, which has no credentials (%s cannot embed)",
            fallback.config.name,
            text_provider.config.name,
        )
        return fallback

    return text_provider


def reset_providers() -> None:
    """Drop cached instances. Used by tests that swap environment variables."""
    _instances.clear()
