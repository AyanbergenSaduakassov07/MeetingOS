"""Org-configurable redaction rules, and the categories Part 4 asked for.

What was already here, and what was not
---------------------------------------
``redaction.py`` shipped nine identifier patterns — email, URL, IBAN, card,
NI number, SSN, sort code, phone, postcode — behind one boolean environment
flag. It ran before every cloud call, including embeddings.

Three things the original blueprint specified were **not** implemented, and
this module is what implements them:

1. **Salary and compensation figures.** Not covered at all. A number spoken in
   a pay discussion looked like any other number.
2. **Health mentions.** Not covered at all, and the highest-sensitivity
   category in the list — a diagnosis disclosed in a meeting is special
   category data under GDPR Art. 9.
3. **A configurable rule list.** The rules were a module constant. An operator
   could turn redaction on or off and nothing else.

National ID was half-covered: UK NI and US SSN had patterns, but a Kazakh IIN
matched only by accident, via the phone rule. It has its own rule now.

Why health is a keyword list and not a pattern
-----------------------------------------------
The other categories have shape — a card number looks like a card number. A
health disclosure has no shape at all; it is ordinary sentences about ordinary
words. So this matches a keyword list and redacts the *clause* around a hit.

That is a blunt instrument and it is stated plainly rather than sold as more:
it will miss euphemism ("he's been having a rough time") and it will over-match
("the project is in critical condition"). Over-matching is the safer error and
the one this is tuned for. A meeting where health is discussed in earnest needs
a local model, not a keyword list.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rule:
    """One redaction rule. ``pattern`` is compiled once at import."""

    name: str
    pattern: re.Pattern[str]
    category: str
    description: str
    # Off by default when the rule is noisy enough that an operator should opt
    # in knowingly rather than discover it eating their transcripts.
    default_enabled: bool = True

    def placeholder(self) -> str:
        return f"[redacted:{self.name}]"


# ── Identifier rules (the original nine, unchanged in behaviour) ──────────

IDENTIFIER_RULES: tuple[Rule, ...] = (
    Rule("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "identifier", "Email addresses"),
    Rule("url", re.compile(r"\bhttps?://\S+|\bwww\.[\w.-]+\.\w{2,}\S*"), "identifier", "URLs"),
    Rule("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"), "financial", "IBANs"),
    # Separators sit *between* digits. The earlier `(?:\d[ -]?){13,19}` also ate
    # the space after the last digit, so a redacted card ran into the next word
    # ("[redacted:card]was used") in everything the model was shown.
    Rule("card", re.compile(r"\b\d(?:[ -]?\d){12,18}\b"), "financial", "Card numbers"),
    Rule("sort_code", re.compile(r"\b\d{2}-\d{2}-\d{2}\b"), "financial", "UK sort codes"),
    Rule(
        "phone",
        re.compile(r"(?:\+\d{1,3}[ -]?)?(?:\(?\d{2,5}\)?[ -]?){2,4}\d{2,4}\b"),
        "identifier",
        "Phone numbers",
    ),
    Rule(
        "postcode",
        re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b", re.IGNORECASE),
        "identifier",
        "UK postcodes",
    ),
)

# ── National ID ───────────────────────────────────────────────────────────

NATIONAL_ID_RULES: tuple[Rule, ...] = (
    Rule(
        "ni_number",
        re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b"),
        "national_id",
        "UK National Insurance numbers",
    ),
    Rule("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "national_id", "US Social Security numbers"),
    # Kazakh IIN / BIN: 12 digits. Previously matched only by accident via the
    # phone rule, which is not the same as being covered.
    Rule(
        "kz_iin",
        re.compile(r"\b\d{12}\b"),
        "national_id",
        "Kazakh IIN / BIN (12 digits)",
    ),
    # Labelled ID of any national scheme: "passport AB123456", "ИИН 8705...".
    Rule(
        "labelled_id",
        re.compile(
            r"\b(?:passport|паспорт|ии?н|iin|bin|inn|инн|tax\s*id|national\s*id)\b"
            r"[\s:№#-]*[A-Z0-9-]{6,20}",
            re.IGNORECASE,
        ),
        "national_id",
        "Identifiers introduced by a label (passport, IIN, INN, tax ID)",
    ),
)

# ── Salary and compensation ───────────────────────────────────────────────
#
# A pay figure has no distinguishing shape, so these match the *context* — a
# compensation word within a short distance of an amount — rather than the
# number alone. Matching bare numbers would redact every figure in a budget
# discussion, which is most of what a board meeting is.

_MONEY = r"(?:[$£€₸]\s?)?\d[\d ,.]*(?:\s?(?:k|m|bn|thousand|million|тысяч|млн|тенге|tenge))?"
_PAY_WORDS = (
    r"salar(?:y|ies)|compensation|remuneration|package|bonus|wage|payroll|"
    r"зарплат\w*|оклад\w*|премия|вознаграждени\w*|жалақы"
)

SALARY_RULES: tuple[Rule, ...] = (
    Rule(
        "salary",
        re.compile(rf"(?:{_PAY_WORDS})\b[^.!?\n]{{0,40}}?{_MONEY}", re.IGNORECASE),
        "salary",
        "Pay figures stated near a compensation word",
    ),
    Rule(
        "salary_reversed",
        re.compile(rf"{_MONEY}[^.!?\n]{{0,30}}?\b(?:{_PAY_WORDS})", re.IGNORECASE),
        "salary",
        "Amounts stated before a compensation word",
    ),
)

# ── Health ────────────────────────────────────────────────────────────────
#
# No shape to match, so this matches keywords and redacts the surrounding
# clause. Blunt by construction — see the module docstring.

_HEALTH_WORDS = (
    r"diagnos\w*|cancer|chemo\w*|tumou?r|surgery|operation|hospitali[sz]\w*|"
    r"depress\w*|anxiety|therapy|psychiatr\w*|medication|prescription|"
    r"disabilit\w*|sick\s*leave|sick\s*note|medical\s*leave|maternity|paternity|"
    r"pregnan\w*|miscarriage|HIV|diabet\w*|epilep\w*|stroke|heart\s*attack|"
    r"диагноз\w*|болезн\w*|больнич\w*|беременн\w*|операци\w*|терапи\w*"
)

HEALTH_RULES: tuple[Rule, ...] = (
    Rule(
        "health",
        # The clause around the hit, bounded by sentence punctuation so the
        # redaction does not swallow the rest of the paragraph.
        re.compile(rf"[^.!?\n]*\b(?:{_HEALTH_WORDS})\b[^.!?\n]*", re.IGNORECASE),
        "health",
        "Clauses mentioning health, medical leave, or a diagnosis",
    ),
)

ALL_RULES: tuple[Rule, ...] = (
    *IDENTIFIER_RULES,
    *NATIONAL_ID_RULES,
    *SALARY_RULES,
    *HEALTH_RULES,
)

RULES_BY_NAME: dict[str, Rule] = {rule.name: rule for rule in ALL_RULES}

CATEGORIES: tuple[str, ...] = ("identifier", "financial", "national_id", "salary", "health")

# Applied in this order so a more specific rule wins. Health runs first because
# it redacts a whole clause, and a clause containing a phone number should be
# gone entirely rather than leaving "[redacted:phone]" as a hint that something
# was there.
RULE_ORDER: tuple[str, ...] = (
    "health",
    "labelled_id",
    "salary",
    "salary_reversed",
    "email",
    "url",
    "iban",
    "ni_number",
    "ssn",
    "kz_iin",
    "card",
    "sort_code",
    "phone",
    "postcode",
)


@dataclass
class RedactionConfig:
    """Which rules an org runs. Serialisable to and from the settings row."""

    enabled: bool = False
    rules: list[str] = field(default_factory=lambda: [r.name for r in ALL_RULES])

    @classmethod
    def from_dict(cls, payload: dict | None) -> RedactionConfig:
        payload = payload or {}
        requested = payload.get("rules")
        if requested is None:
            rules = [r.name for r in ALL_RULES]
        else:
            # Silently dropping an unknown rule name would let a typo disable
            # redaction without telling anyone.
            rules = []
            for name in requested:
                if name in RULES_BY_NAME:
                    rules.append(name)
                else:
                    logger.warning("Unknown redaction rule %r in config; ignoring it", name)
        return cls(enabled=bool(payload.get("enabled", False)), rules=rules)

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "rules": list(self.rules)}

    def active_rules(self) -> list[Rule]:
        """Enabled rules, in application order."""
        chosen = set(self.rules)
        return [RULES_BY_NAME[name] for name in RULE_ORDER if name in chosen]
