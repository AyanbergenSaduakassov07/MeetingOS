"""Redact identifiers from transcript text before it leaves the machine.

Why this exists
---------------
Everything MeetingOS knows about a meeting is sent to a third-party inference
API: the audio file itself goes to transcription, and the transcript then goes
out again for extraction, topic titling, embedding, and every copilot question.
For a student club discussing showcase dates, that is a defensible trade. For a
meeting where someone reads out a phone number, a home address, a bank
reference, or a medical detail, it is a disclosure to a vendor — and, with the
default configuration pointing at an aggregator, to whichever inference host
that aggregator routes to.

So: a redaction pass IS needed before this is pointed at anything beyond the
author's own meetings. This module is that pass.

What it does and does not do
----------------------------
This is pattern-based redaction — emails, phone numbers, long digit strings
(card and account numbers), IBANs, national insurance and social security
numbers, postcodes, and URLs. Those are the identifiers that appear verbatim in
speech-to-text output and that carry the most direct re-identification risk.

It deliberately does **not** try to redact names. Names are the substance of a
meeting record: "Priya will chase the invoice" is the action item, and a
transcript with the names stripped extracts to nothing useful. Removing names
is a product decision about what MeetingOS is for, not a regex problem, and
pretending a regex had solved it would be worse than saying so.

That means REDACT_TRANSCRIPTS is a mitigation, not anonymisation. It lowers the
identifier surface; it does not make a transcript safe to send anywhere. A
meeting that must not leave the machine needs a local model, not this.

Off by default
--------------
Redaction changes what the model sees, and a redacted transcript extracts
slightly worse — a phone number becomes ``[redacted:phone]`` and any action
item about it loses its detail. Silently degrading extraction quality is not a
default anyone should get without asking for it, so this is opt-in via
``MEETINGOS_REDACT_TRANSCRIPTS=1`` and logged loudly when it engages.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Rules now live in redaction_rules.py, where they can be configured per org.
# The names and behaviour of everything below are unchanged, so no call site
# needed to move.
from .redaction_rules import ALL_RULES, RedactionConfig, Rule  # noqa: E402

RULES: tuple[Rule, ...] = ALL_RULES

ENV_FLAG = "MEETINGOS_REDACT_TRANSCRIPTS"


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def changed(self) -> bool:
        return self.total > 0


# Set by the settings layer at startup, or by a caller for one operation. When
# None the environment flag decides, which keeps the original behaviour for
# anyone who never opens the privacy page.
_active_config: RedactionConfig | None = None


def set_active_config(config: RedactionConfig | None) -> None:
    """Install the org's redaction config as the process default."""
    global _active_config
    _active_config = config
    if config is not None:
        logger.info(
            "Redaction config: enabled=%s, %d rule(s) active",
            config.enabled,
            len(config.active_rules()),
        )


def active_config() -> RedactionConfig:
    """The config in force, falling back to the environment flag."""
    if _active_config is not None:
        return _active_config
    return RedactionConfig(
        enabled=os.environ.get(ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"},
        rules=[rule.name for rule in ALL_RULES],
    )


def is_enabled() -> bool:
    """Opt-in, because redaction trades extraction detail for exposure."""
    return active_config().enabled


def redact(text: str, *, config: RedactionConfig | None = None) -> RedactionResult:
    """Replace identifier-shaped spans with typed placeholders.

    The placeholder keeps the *type* so the model can still reason about the
    shape of the statement — "call [redacted:phone] before Friday" is still a
    recognisable action item, where blanking it entirely would not be.
    """
    if not text:
        return RedactionResult(text=text)

    counts: dict[str, int] = {}
    redacted = text
    for rule in (config or active_config()).active_rules():
        # A placeholder from an earlier rule must not be re-matched by a later
        # one, so match around the already-substituted spans.
        parts = re.split(r"(\[redacted:[a-z_]+\])", redacted)
        rebuilt = []
        for part in parts:
            if part.startswith("[redacted:"):
                rebuilt.append(part)
                continue
            replaced, count = rule.pattern.subn(rule.placeholder(), part)
            if count:
                counts[rule.name] = counts.get(rule.name, 0) + count
            rebuilt.append(replaced)
        redacted = "".join(rebuilt)

    return RedactionResult(text=redacted, counts=counts)


def redact_many_for_egress(texts: list[str]) -> list[str]:
    """Redact a batch before it goes to an embedding endpoint.

    Embeddings were the hole in this module's original claim to be "the single
    call site for outbound text". Prompts were redacted; the embedding calls
    that send *every* segment and chunk were not — so with the flag on, the
    complete unredacted transcript still left the machine, one vector at a
    time. Embedding text is egress like any other.
    """
    if not is_enabled():
        return list(texts)
    return [redact_for_egress(text) for text in texts]


def redact_for_egress(text: str, *, force: bool = False) -> str:
    """Redact when the flag is set — or when the caller says this text is
    sensitive whatever the flag says.

    ``force`` exists for content an operator has explicitly marked, where the
    org-wide opt-in is the wrong question. Someone who ticks "sensitive" on a
    contract has already answered it for that file.
    """
    if not (force or is_enabled()):
        return text
    result = redact(text)
    if result.changed:
        logger.info(
            "Redacted %d identifier(s) before egress: %s",
            result.total,
            ", ".join(f"{name}x{count}" for name, count in sorted(result.counts.items())),
        )
    return result.text
