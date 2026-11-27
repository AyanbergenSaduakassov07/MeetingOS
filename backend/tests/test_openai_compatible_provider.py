"""OpenAI-wire endpoints without strict json_schema (OpenRouter, vLLM, Ollama)."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from backend.ai.base import ProviderConfig, ProviderError
from backend.ai.providers.openai_compatible_provider import OpenAICompatibleProvider


class _Out(BaseModel):
    translations: dict[str, str]


def _provider(reply: str, sent: dict) -> OpenAICompatibleProvider:
    class _Completions:
        async def create(self, **kwargs):
            sent.update(kwargs)
            message = SimpleNamespace(content=reply)
            return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])

    provider = OpenAICompatibleProvider(
        ProviderConfig(name="openai_compatible", model="m", api_key_env="UNSET_KEY", base_url="http://x/v1")
    )
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    return provider


def test_extract_parses_fenced_json_without_strict_schema():
    sent: dict = {}
    reply = 'Sure:\n```json\n{"translations": {"ru": "Релиз в понедельник."}}\n```'
    out = asyncio.run(_provider(reply, sent).extract("translate", _Out))
    assert out.translations == {"ru": "Релиз в понедельник."}
    assert "response_format" not in sent  # many servers reject strict json_schema
    assert "translations" in sent["messages"][0]["content"]  # schema travels in the prompt


def test_extract_rejects_reply_without_json():
    with pytest.raises(ProviderError):
        asyncio.run(_provider("no idea", {}).extract("translate", _Out))


def test_configured_by_url_alone(monkeypatch):
    monkeypatch.delenv("UNSET_KEY", raising=False)
    assert _provider("{}", {}).is_configured()
