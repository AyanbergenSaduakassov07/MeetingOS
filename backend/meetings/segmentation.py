"""Group consecutive transcript segments into topics.

This is TextTiling with embeddings rather than word counts, which is the
standard way to do the job and deliberately not a topic model.  LDA and
friends assign documents to a fixed set of latent topics; a meeting needs the
opposite — where does the conversation *change subject*, in order, with no
prior idea of how many subjects there are.  Boundary detection answers that,
needs no training, and no corpus.

The method, in one paragraph: embed every segment once, slide a window along
the transcript, and at each gap compare the mean vector of the ``window``
segments before it with the mean of the ``window`` after.  Cosine similarity
between those two block means falls when the subject changes.  Where it falls
below ``threshold``, cut.  Everything between two cuts becomes one ``Topic``.

Two properties worth keeping if this is rewritten: all embeddings come from a
single batched ``embed`` call (one round trip per meeting, not one per
segment), and windowing means a single off-topic aside does not split a topic
— it takes a sustained shift to move the block mean.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..database import Topic, TranscriptSegment
from .redaction import redact_many_for_egress

logger = logging.getLogger(__name__)

# Two segments of context on each side of a gap. Smaller reacts to every
# aside; larger smooths over genuinely short topics.
DEFAULT_WINDOW = 3
# Cosine below this between adjacent blocks counts as a subject change.
# Tuned to be forgiving: a missed boundary merges two topics, a spurious one
# fragments the timeline, and merged reads better than shredded.
DEFAULT_THRESHOLD = 0.6
# Stop-word-ish tokens that would otherwise dominate keyword extraction.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "we",
        "were",
        "will",
        "with",
        "you",
        "your",
        "this",
        "they",
        "them",
        "he",
        "she",
        "do",
        "does",
        "did",
        "not",
        "no",
        "yes",
        "so",
        "if",
        "then",
        "than",
        "there",
        "here",
        "what",
        "when",
        "who",
        "how",
        "why",
        "can",
        "could",
        "should",
        "would",
        "just",
        "about",
    ]
)


@dataclass
class _Window:
    """A contiguous run of segment indices forming one topic."""

    start_index: int
    end_index: int  # inclusive


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 if either is degenerate."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    """Element-wise mean of a non-empty list of equal-length vectors."""
    count = len(vectors)
    return [sum(values) / count for values in zip(*vectors, strict=True)]


def detect_boundaries(
    vectors: list[list[float]],
    *,
    window: int = DEFAULT_WINDOW,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[int]:
    """Return the indices where a new topic starts.

    An index ``i`` in the result means "segment ``i`` begins a new topic".
    Index 0 is never returned — the first segment always starts the first
    topic, so reporting it would be redundant.

    Gaps closer to either end than ``window`` are not evaluated: a block mean
    computed from fewer segments than its counterpart is not comparable, and
    guessing there produces boundaries in the first ten seconds of every
    meeting.
    """
    count = len(vectors)
    if count < 2 * window or window < 1:
        return []

    boundaries: list[int] = []
    for index in range(window, count - window + 1):
        before = _mean_vector(vectors[index - window : index])
        after = _mean_vector(vectors[index : index + window])
        similarity = cosine_similarity(before, after)
        if similarity < threshold:
            # Suppress a boundary adjacent to one already taken; a real
            # subject change registers across several gaps and would
            # otherwise produce a cluster of one-segment topics.
            if boundaries and index - boundaries[-1] < window:
                continue
            boundaries.append(index)

    return boundaries


def _windows(boundaries: list[int], count: int) -> list[_Window]:
    """Turn boundary indices into inclusive index ranges covering all segments."""
    starts = [0, *boundaries]
    windows: list[_Window] = []
    for position, start in enumerate(starts):
        end = (starts[position + 1] - 1) if position + 1 < len(starts) else count - 1
        if start <= end:
            windows.append(_Window(start_index=start, end_index=end))
    return windows


def _keywords(texts: list[str], limit: int = 6) -> list[str]:
    """Most frequent content words in a topic, as a cheap label hint.

    Frequency counting, not an LLM call: a topic label is worth one API call
    per meeting at most, and that call belongs in the summarization pass where
    it can see the whole transcript. This just gives the UI something to show.
    """
    counts: dict[str, int] = {}
    for text in texts:
        for raw in text.lower().split():
            word = raw.strip(".,!?;:'\"()[]")
            if len(word) < 3 or word in _STOPWORDS:
                continue
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:limit]]


async def segment_meeting(
    meeting_id: str,
    *,
    embedder=None,
    window: int = DEFAULT_WINDOW,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Topic]:
    """Embed a meeting's segments, find topic boundaries, and persist ``Topic`` rows.

    ``embedder`` is anything with an async ``embed(texts) -> list[list[float]]``
    — an ``LLMProvider`` in production, a fake in tests. Returns the persisted
    topics, detached from the session so callers can read them freely.
    """
    from ..database import new_session

    db: Session = new_session()
    try:
        segments = (
            db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).order_by(TranscriptSegment.sequence).all()
        )
        if not segments:
            logger.debug("No segments to segment for meeting %s", meeting_id)
            return []

        if embedder is None:
            from ..ai import get_embedding_provider

            embedder = get_embedding_provider()

        # One batched call for the whole meeting.
        vectors = await embedder.embed(redact_many_for_egress([segment.text for segment in segments]))
        if len(vectors) != len(segments):
            raise ValueError(f"Embedder returned {len(vectors)} vectors for {len(segments)} segments")

        boundaries = detect_boundaries(vectors, window=window, threshold=threshold)
        windows = _windows(boundaries, len(segments))

        db.query(Topic).filter_by(meeting_id=meeting_id).delete(synchronize_session=False)
        db.flush()

        total_ms = max(segment.end_ms for segment in segments) - min(segment.start_ms for segment in segments)
        topics: list[Topic] = []

        for position, span in enumerate(windows, start=1):
            members = segments[span.start_index : span.end_index + 1]
            start_ms = members[0].start_ms
            end_ms = members[-1].end_ms
            keywords = _keywords([segment.text for segment in members])

            topic = Topic(
                meeting_id=meeting_id,
                label=", ".join(keywords[:3]) or f"Topic {position}",
                summary=None,  # filled by the summarization pass, not here
                start_ms=start_ms,
                end_ms=end_ms,
                salience=((end_ms - start_ms) / total_ms) if total_ms else None,
                keywords=keywords,
            )
            db.add(topic)
            topics.append(topic)

        db.commit()

        # Load every column, then detach, so the caller can read the rows
        # after this session closes.
        for topic in topics:
            db.refresh(topic)
        db.expunge_all()
        return topics

    finally:
        db.close()
