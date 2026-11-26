# Adapted from livetranslate (https://github.com/Sebzdead/livetranslate, a9ba615,
# src/livetranslate/segmenter.py). MIT License, Copyright (c) 2026 Sebastian Wittekindt.
# Changes: types from backend.live.types; language carried through to sentences.
"""Turn partial/final recognizer output into whole, append-only sentences.

Translating whole sentences instead of raw finals gives the translator enough
context and keeps one translation per caption line.

Known limits (from upstream): abbreviations such as "Dr." split early; when one
final yields several sentences, the later ones get approximate timestamps.
"""

from __future__ import annotations

import logging
import time

from .types import AsrEvent, Sentence

log = logging.getLogger(__name__)

TERMINALS = ".!?…。！？"  # noqa: RUF001 (CJK full-width marks end sentences)
SOFT_BREAKS = (",", ";", ":", "，", "、")  # noqa: RUF001


class Segmenter:
    DEDUPE_SLACK_MS = 250
    PARAGRAPH_GAP_MS = 4000

    def __init__(self, max_words: int = 45, max_pending_s: float = 12.0) -> None:
        self.max_words, self.max_pending_s = max_words, max_pending_s
        self._next_sid = 0
        self._buf: list[str] = []
        self._buf_start_ms: int | None = None
        self._buf_first_wall: float | None = None
        self._last_committed_end_ms = -(self.DEDUPE_SLACK_MS + 1)
        self._last_emitted_end_ms = -1
        self._last_emitted_tokens: list[str] = []
        self.language: str | None = None

    def on_event(self, ev: AsrEvent) -> list[Sentence]:
        if ev.kind == "partial":
            return []
        text = " ".join(ev.text.split())
        if not text:
            return []
        # A final that re-covers committed audio is a reconnect replay: drop it.
        if (
            ev.t_audio_start_ms < self._last_committed_end_ms
            and ev.t_audio_end_ms <= self._last_committed_end_ms + self.DEDUPE_SLACK_MS
        ):
            log.info("segmenter: dropped duplicate final %r", text)
            return []
        tokens = text.split()
        if ev.t_audio_start_ms < self._last_committed_end_ms:
            tokens = self._merge_overlap(tokens)
            if not tokens:
                return []
        if self._buf_start_ms is None:
            self._buf_start_ms = max(ev.t_audio_start_ms, self._last_committed_end_ms)
            self._buf_first_wall = ev.t_received_wall
        self._buf.extend(tokens)
        self._last_committed_end_ms = ev.t_audio_end_ms
        self.language = ev.language or self.language
        return self._emit_ready(ev.t_audio_end_ms)

    def _merge_overlap(self, tokens: list[str]) -> list[str]:
        """Drop the longest prefix of ``tokens`` that repeats the committed tail."""
        tail = self._buf if self._buf else self._last_emitted_tokens
        for n in range(min(len(tail), len(tokens)), 0, -1):
            if [t.lower() for t in tail[-n:]] == [t.lower() for t in tokens[:n]]:
                return tokens[n:]
        return tokens

    def _emit_ready(self, end_ms: int) -> list[Sentence]:
        out: list[Sentence] = []
        while (s := self._try_take_sentence(end_ms)) is not None:
            out.append(s)
        return out

    def _soft_cut(self, limit: int) -> int:
        for i in range(limit - 1, -1, -1):
            if self._buf[i].endswith(SOFT_BREAKS):
                return i + 1
        return limit

    def _try_take_sentence(self, end_ms: int) -> Sentence | None:
        for i, tok in enumerate(self._buf):
            if tok[-1] in TERMINALS:
                return self._emit(self._buf[: i + 1], end_ms)
        if len(self._buf) >= self.max_words:
            return self._emit(self._buf[: self._soft_cut(self.max_words)], end_ms)
        return None

    def check_pending(self, now_wall: float | None = None) -> list[Sentence]:
        """Force out text that has waited longer than ``max_pending_s``."""
        now_wall = time.monotonic() if now_wall is None else now_wall
        if not self._buf or self._buf_first_wall is None or now_wall - self._buf_first_wall < self.max_pending_s:
            return []
        cut = self._soft_cut(min(len(self._buf), self.max_words))
        forced = self._emit(self._buf[:cut], self._last_committed_end_ms)
        return [forced, *self._emit_ready(self._last_committed_end_ms)]

    def flush(self) -> list[Sentence]:
        if not self._buf:
            return []
        return [self._emit(self._buf[:], self._last_committed_end_ms)]

    def _emit(self, tokens: list[str], end_ms: int) -> Sentence:
        start_ms = self._buf_start_ms if self._buf_start_ms is not None else end_ms
        gap = start_ms - self._last_emitted_end_ms if self._last_emitted_end_ms >= 0 else 0
        sentence = Sentence(
            sid=self._next_sid,
            text=" ".join(tokens),
            t_audio_start_ms=start_ms,
            t_audio_end_ms=end_ms,
            t_finalized_wall=time.monotonic(),
            paragraph_break=gap > self.PARAGRAPH_GAP_MS,
        )
        self._next_sid += 1
        self._last_emitted_end_ms = end_ms
        self._last_emitted_tokens = tokens[-64:]
        del self._buf[: len(tokens)]
        if self._buf:
            self._buf_start_ms, self._buf_first_wall = end_ms, time.monotonic()
        else:
            self._buf_start_ms = self._buf_first_wall = None
        return sentence
