"""Deterministic fake provider, for exercising the harness without credentials.

**This is not a quality signal.** It is a crude keyword matcher standing in for
a model so that `run_eval.py` can be developed, debugged, and regression-tested
on a machine with no API key. A score produced with `--stub` says the harness
computes precision, recall and citation accuracy correctly; it says nothing
whatsoever about extraction quality.

`--baseline` should never be run against it. `run_eval.py` records the provider
name in `thresholds.json` so a stub-derived baseline is visible as such.
"""

from __future__ import annotations

import re

from backend.ai.base import Completion, ProviderConfig, Usage

# [<segment-id>] (0s-8s) Speaker: text
_LINE = re.compile(r"^\[([^\]]+)\]\s+\([^)]*\)\s+([^:]+):\s*(.*)$")

_DECISION_CUES = (
    "let's take",
    "let's lock",
    "we're agreed",
    "it is",
    "we'll leave",
    "going with",
    "we hold",
    "let's agree",
    "let's park",
    "we go ahead",
)
_DEFER_CUES = ("park", "defer", "next week", "until")
_ACTION_CUES = ("i'll ", "i will ", "send it", "chase", "fill in")
_RISK_CUES = ("that's a problem", "back-ordered", "has not cleared", "can't buy", "won't work", "not landed")
_HEDGES = ("might be able", "don't count on me", "probably", "not sure")


def _parse(prompt: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in prompt.splitlines():
        match = _LINE.match(line.strip())
        if match:
            rows.append((match.group(1), match.group(2).strip(), match.group(3).strip()))
    return rows


class StubEmbedder:
    """Bag-of-words cosine. Enough for the matcher to pair obvious rewordings."""

    def __init__(self) -> None:
        self.config = ProviderConfig(
            name="stub",
            model="stub-embed",
            api_key_env="NONE",
            embedding_model="stub-embed",
            supports_embeddings=True,
        )

    def is_configured(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vocab: dict[str, int] = {}
        tokenised = []
        for text in texts:
            words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2]
            tokenised.append(words)
            for word in words:
                vocab.setdefault(word, len(vocab))
        vectors = []
        for words in tokenised:
            vector = [0.0] * max(1, len(vocab))
            for word in words:
                vector[vocab[word]] += 1.0
            vectors.append(vector)
        return vectors


class StubProvider:
    """Keyword-rule extractor shaped like an LLMProvider."""

    def __init__(self) -> None:
        self.config = ProviderConfig(name="stub", model="stub-llm", api_key_env="NONE")

    def is_configured(self) -> bool:
        return True

    async def generate(self, prompt, *, system=None, max_tokens=None, temperature=None):
        return Completion(text="{}", model="stub-llm", usage=Usage(0, 0))

    async def embed(self, texts):
        return await StubEmbedder().embed(texts)

    async def extract(self, prompt, schema, *, system=None, max_tokens=None):
        name = schema.__name__

        # The comparator asks a different question with a different schema.
        # This rule is crude on purpose — it exists so the harness can be run
        # and debugged without credentials, not to approximate judgement.
        if name == "ClaimRelationship":
            return self._compare(prompt, schema)

        rows = _parse(prompt)
        items = []

        for segment_id, speaker, text in rows:
            lower = text.lower()
            if any(hedge in lower for hedge in _HEDGES):
                continue

            if name == "DecisionList" and any(cue in lower for cue in _DECISION_CUES):
                status = "deferred" if any(c in lower for c in _DEFER_CUES) else "agreed"
                items.append(
                    {
                        "segment_id": segment_id,
                        "quote": text[:120],
                        "confidence": 0.8,
                        "title": text[:90],
                        "description": None,
                        "rationale": None,
                        "status": status,
                    }
                )
            elif name == "ActionItemList" and any(cue in lower for cue in _ACTION_CUES):
                items.append(
                    {
                        "segment_id": segment_id,
                        "quote": text[:120],
                        "confidence": 0.8,
                        "title": text[:90],
                        "description": None,
                        "assignee_name": speaker,
                        "due_date_text": None,
                        "priority": "medium",
                    }
                )
            elif name == "RiskList" and any(cue in lower for cue in _RISK_CUES):
                items.append(
                    {
                        "segment_id": segment_id,
                        "quote": text[:120],
                        "confidence": 0.75,
                        "title": text[:90],
                        "description": None,
                        "category": None,
                        "severity": "medium",
                        "mitigation": None,
                    }
                )
            elif name == "CommitmentList" and lower.startswith(("i'll", "i will", "i promise")):
                items.append(
                    {
                        "segment_id": segment_id,
                        "quote": text[:120],
                        "confidence": 0.85,
                        "text": text[:120],
                        "committer_name": speaker,
                        "due_date_text": None,
                    }
                )

        return schema(items=items)

    # -- comparator ---------------------------------------------------------

    _REVERSAL_CUES = ("cancel", "not proceeding", "overturn", "instead of waiting", "without waiting")
    _REFINE_CUES = ("is set at", "is commissioned", "reports in")

    def _compare(self, prompt: str, schema):
        """Keyword rule standing in for a judgement call. Not a quality signal."""
        lower = prompt.lower()
        new_half = lower.split("new claim:", 1)[-1]

        if any(cue in new_half for cue in self._REVERSAL_CUES):
            relationship = "reversed"
        elif any(cue in new_half for cue in self._REFINE_CUES):
            relationship = "refined"
        else:
            relationship = "consistent"

        ids = [line.split("evidence_id:")[1].strip() for line in prompt.splitlines() if "evidence_id:" in line]
        cite = relationship in ("contradicted", "reversed") and len(ids) >= 2
        return schema(
            relationship=relationship,
            reasoning="stub rule",
            prior_evidence_id=ids[0] if cite else None,
            new_evidence_id=ids[1] if cite else None,
            confidence=0.5,
        )
