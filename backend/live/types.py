"""Contracts between the live pipeline and its providers."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True)
class AsrEvent:
    """One recognizer output. Partials may be revised; finals never are."""

    kind: Literal["partial", "final"]
    text: str
    t_audio_start_ms: int
    t_audio_end_ms: int
    language: str | None = None
    t_received_wall: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class Sentence:
    sid: int
    text: str
    t_audio_start_ms: int
    t_audio_end_ms: int
    t_finalized_wall: float
    paragraph_break: bool = False


class StreamingASR(Protocol):
    name: str

    async def start(self, *, language: str | None) -> None: ...  # None = auto-detect
    async def send(self, pcm16: bytes) -> None: ...  # 16 kHz mono little-endian
    def events(self) -> AsyncIterator[AsrEvent]: ...  # ends after close()
    async def close(self) -> None: ...


class Translator(Protocol):
    name: str

    async def translate(
        self, text: str, *, source: str | None, targets: list[str], context: list[str]
    ) -> dict[str, str]: ...
