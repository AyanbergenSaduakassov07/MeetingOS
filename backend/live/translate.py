"""Translators behind ``Translator``: one call per sentence covers every target.

``google``: Cloud Translation v2 REST (``GOOGLE_TRANSLATE_API_KEY``), one request
per target, run concurrently. ``llm``: the configured MeetingOS LLM provider,
all targets in one structured call. Default: google when its key is set.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
from pydantic import BaseModel

from ..meetings.egress_log import logged_call
from .languages import language_name

GOOGLE_URL = "https://translation.googleapis.com/language/translate/v2"
GOOGLE_KEY_ENV = "GOOGLE_TRANSLATE_API_KEY"
TIMEOUT_S = 10.0


class TranslationError(RuntimeError):
    pass


class GoogleTranslator:
    name = "google_translate"

    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key or os.environ.get(GOOGLE_KEY_ENV)
        if not self._key:
            raise TranslationError(f"{GOOGLE_KEY_ENV} is not set")
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT_S)

    async def _one(self, text: str, source: str | None, target: str) -> str:
        body = {"q": text, "target": target, "format": "text"}
        if source:
            body["source"] = source
        with logged_call(self.name, "translate", endpoint_host="translation.googleapis.com", texts=[text]):
            response = await self._client.post(GOOGLE_URL, json=body, headers={"X-Goog-Api-Key": self._key})
            if response.status_code != 200:
                raise TranslationError(f"Google Translate HTTP {response.status_code}")
            return response.json()["data"]["translations"][0]["translatedText"]

    async def translate(self, text: str, *, source: str | None, targets: list[str], context: list[str]) -> dict:
        results = await asyncio.gather(*(self._one(text, source, t) for t in targets))
        return dict(zip(targets, results, strict=True))


class _Item(BaseModel):
    lang: str
    text: str


class _Out(BaseModel):
    translations: list[_Item]


SYSTEM = (
    "You are a live meeting interpreter. Translate the CURRENT line into each requested language. "
    "Keep numbers, names, dates and amounts exactly. Do not add or omit content. "
    "The PREVIOUS lines are context only; never translate them."
)


class LLMTranslator:
    name = "llm"

    def __init__(self, provider=None) -> None:
        from ..ai.orchestrator import get_llm_provider

        self._provider = provider or get_llm_provider()

    async def translate(self, text: str, *, source: str | None, targets: list[str], context: list[str]) -> dict:
        prompt = json.dumps(
            {
                "source_language": language_name(source) if source else "auto-detect",
                "targets": {t: language_name(t) for t in targets},
                "previous": context[-3:],
                "current": text,
            },
            ensure_ascii=False,
        )
        out = await self._provider.extract(prompt, _Out, system=SYSTEM)
        got = {item.lang: item.text for item in out.translations if item.lang in targets}
        missing = set(targets) - set(got)
        if missing:
            raise TranslationError(f"translator returned no text for {sorted(missing)}")
        return got


def get_translator(name: str | None = None):
    resolved = (name or os.environ.get("MEETINGOS_LIVE_TRANSLATOR") or "").strip().lower()
    if not resolved:
        resolved = "google" if os.environ.get(GOOGLE_KEY_ENV) else "llm"
    if resolved == "google":
        return GoogleTranslator()
    if resolved == "llm":
        return LLMTranslator()
    raise ValueError(f"Unknown live translator '{resolved}'. Use google or llm.")
