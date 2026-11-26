"""Static language registry. ``verified`` moves to ``eval_passed`` only after the
live eval in PLAN §5.3 passes with human review; vendor lists alone are not proof."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

_PATH = Path(__file__).with_name("languages.json")


@cache
def languages() -> list[dict]:
    return json.loads(_PATH.read_text(encoding="utf-8"))


@cache
def codes() -> frozenset[str]:
    return frozenset(row["code"] for row in languages())


def language_name(code: str) -> str:
    return next((row["name"] for row in languages() if row["code"] == code), code)
