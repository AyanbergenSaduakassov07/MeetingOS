"""Check that each extracted claim is supported by the segment it cites.

The failure this catches is the expensive one. An extraction that invents a
decision nobody made, or attaches a real decision to the wrong moment, is
worse than no extraction at all: it looks authoritative, it lands in a board
pack, and nobody re-reads the transcript to check. So every item is scored
against its own citation before anyone sees it.

Method: two signals. First, does the verbatim ``quote`` the extractor was
required to supply actually appear in the cited segment — an exact, free,
model-free test that catches invented words outright. Second, cosine
similarity between the claim and the segment, which catches a real quote
attached to an unrelated claim. An item passes on either.

The quote gate exists because similarity alone produced false positives on
correct extractions: a well-written title legitimately shares almost no
surface words with the utterance it summarises, so a low similarity could not
distinguish "hallucinated" from "well summarised". A verbatim quote can.

Neither signal is a fact-checker. This verifies *attribution* — that the words
are real and the claim belongs to them — not truth. A participant who says
something false produces a correctly-attributed false claim, and no score here
will tell you that. It also will not catch a plausible paraphrase of a
slightly different statement in the same segment.

Nothing is ever deleted. An item below threshold is flagged
``low_confidence`` and still returned, because a verifier that silently drops
rows is a verifier that quietly loses real decisions on its bad days — and
the reviewer who could have caught it never learns it existed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..database import (
    ActionItem,
    Commitment,
    Decision,
    Risk,
    TranscriptSegment,
    VerificationStatus,
)
from .redaction import redact_many_for_egress
from .segmentation import cosine_similarity

logger = logging.getLogger(__name__)

# Below this, the claim and its citation are treated as unrelated enough to
# need a human look. Deliberately permissive: a false "low_confidence" costs
# one review, a false "verified" costs credibility.
DEFAULT_THRESHOLD = 0.55

# A quote at or above this share of words present in the cited segment is
# treated as genuinely quoted. Below it the quote was largely invented and
# no embedding score should rescue the item.
QUOTE_SUPPORT_THRESHOLD = 0.8

# The models under verification and the attribute holding the claim text.
_VERIFIABLE: tuple[tuple[type, str], ...] = (
    (Decision, "title"),
    (ActionItem, "title"),
    (Risk, "title"),
    (Commitment, "text"),
)


@dataclass
class VerificationReport:
    """Outcome of one verification pass."""

    meeting_id: str
    verified: int = 0
    low_confidence: int = 0
    unsupported: int = 0
    skipped: int = 0

    @property
    def checked(self) -> int:
        return self.verified + self.low_confidence


def _claim_text(item, attribute: str) -> str:
    """The text to compare against the citation, richest form first."""
    parts = [getattr(item, attribute, None) or ""]
    description = getattr(item, "description", None)
    if description:
        parts.append(description)
    return " ".join(part for part in parts if part).strip()


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for quote matching."""
    kept = [character if character.isalnum() or character.isspace() else " " for character in text.lower()]
    return " ".join("".join(kept).split())


def quote_support(quote: str | None, segment_text: str) -> float:
    """How much of the cited quote actually appears in the cited segment.

    Returns 1.0 for a verbatim (normalized) substring, otherwise the fraction
    of the quote's words present in the segment, 0.0 for no quote at all.

    This runs before any embedding because it answers the question that
    actually matters — "did the extractor make these words up?" — exactly,
    for free, and without a model. Embedding similarity cannot do that: a
    paraphrased title legitimately shares few words with its source, so a low
    similarity is ambiguous between "hallucinated" and "well summarised".
    The quote is specified as verbatim, so here a low score is not ambiguous.
    """
    if not quote:
        return 0.0
    normalized_quote = _normalize(quote)
    normalized_segment = _normalize(segment_text)
    if not normalized_quote:
        return 0.0
    if normalized_quote in normalized_segment:
        return 1.0

    quote_words = normalized_quote.split()
    if not quote_words:
        return 0.0
    segment_words = set(normalized_segment.split())
    present = sum(1 for word in quote_words if word in segment_words)
    return present / len(quote_words)


async def verify_meeting(
    meeting_id: str,
    *,
    embedder=None,
    threshold: float = DEFAULT_THRESHOLD,
) -> VerificationReport:
    """Score every extracted item in a meeting against its cited segment.

    ``embedder`` is anything with an async ``embed(texts) -> list[list[float]]``.
    All claims and all cited segments are embedded in a single batched call.
    """
    from ..database import new_session

    db: Session = new_session()
    report = VerificationReport(meeting_id=meeting_id)

    try:
        pending: list[tuple[object, str]] = []
        for model, attribute in _VERIFIABLE:
            for item in db.query(model).filter_by(meeting_id=meeting_id).all():
                pending.append((item, attribute))

        if not pending:
            return report

        # An item whose citation was already rejected as fabricated has
        # nothing to verify against — leave it flagged and do not spend an
        # embedding on it.
        checkable: list[tuple[object, str, TranscriptSegment]] = []
        for item, attribute in pending:
            if item.verification_status == VerificationStatus.UNSUPPORTED.value:
                report.unsupported += 1
                continue
            if not item.source_segment_id:
                item.verification_status = VerificationStatus.UNSUPPORTED.value
                item.verification_score = None
                report.unsupported += 1
                continue
            segment = (
                db.query(TranscriptSegment)
                .filter(
                    TranscriptSegment.id == item.source_segment_id,
                    # Scoped to this meeting: a citation must not be able to
                    # reach another meeting's transcript even if the id is real.
                    TranscriptSegment.meeting_id == meeting_id,
                )
                .first()
            )
            if segment is None:
                item.verification_status = VerificationStatus.UNSUPPORTED.value
                item.verification_score = None
                report.unsupported += 1
                continue
            checkable.append((item, attribute, segment))

        if not checkable:
            db.commit()
            return report

        if embedder is None:
            from ..ai import get_embedding_provider

            embedder = get_embedding_provider()

        claims = [_claim_text(item, attribute) for item, attribute, _ in checkable]
        citations = [segment.text for _, _, segment in checkable]

        # One call for both halves; the split is positional.
        vectors = await embedder.embed(redact_many_for_egress(claims + citations))
        if len(vectors) != len(claims) + len(citations):
            raise ValueError(f"Embedder returned {len(vectors)} vectors for {len(claims) + len(citations)} texts")
        claim_vectors = vectors[: len(claims)]
        citation_vectors = vectors[len(claims) :]

        for (item, _, segment), claim_vector, citation_vector in zip(
            checkable, claim_vectors, citation_vectors, strict=True
        ):
            # Two independent signals, and the deterministic one leads.
            quoted = quote_support(item.source_quote, segment.text)
            similarity = cosine_similarity(claim_vector, citation_vector)

            # The score reported is the stronger of the two: a verbatim quote
            # is proof the words are real even when the title paraphrases them
            # far enough that embeddings disagree.
            score = max(quoted, similarity)
            item.verification_score = score

            supported = quoted >= QUOTE_SUPPORT_THRESHOLD or similarity >= threshold
            if supported:
                item.verification_status = VerificationStatus.VERIFIED.value
                report.verified += 1
            else:
                item.verification_status = VerificationStatus.LOW_CONFIDENCE.value
                report.low_confidence += 1

        db.commit()

    finally:
        db.close()

    logger.info(
        "Verified meeting %s: %d verified, %d low confidence, %d unsupported",
        meeting_id,
        report.verified,
        report.low_confidence,
        report.unsupported,
    )
    return report
