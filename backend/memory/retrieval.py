"""Corpus retrieval — the surface callers use.

Three verbs over the whole org, not one meeting:

- ``search_corpus(query, org_id=...)`` — top-k relevant records, ranked
- ``index_meeting(meeting_id)`` — make a meeting's records findable
- ``purge_meeting(meeting_id)`` — remove them again

Everything here delegates to whichever ``MemoryIndex`` ``get_memory_index()``
resolves. Callers never name a storage engine, never see a blob, and never
write SQL, which is what makes a future pgvector backend a swap rather than a
rewrite.

Budgeting
---------
``DEFAULT_LIMIT`` and ``DEFAULT_MIN_SCORE`` are the reason this is a module and
not a thin passthrough. Retrieval that returns everything above zero is not
retrieval; it moves the filtering problem to the caller, who then puts fifty
weak rows into a context window. The floor is deliberately above noise: better
to return four good records and say so than forty and let the reader sort it
out.

Untrusted input
---------------
Both the query and every indexed record derive from transcript text, so the
same rule as extraction applies — this is data, never instructions. Nothing
here interpolates a record into a prompt, selects code by its content, or lets
it choose what gets returned beyond its own similarity score. The query reaches
the database only as a bound parameter and, for the keyword path, as a
term-quoted FTS expression built from alphanumerics.
"""

from __future__ import annotations

import logging

from .base import RECORD_TYPES, IndexReport, MatchKind, MemoryRecord, RecordType
from .orchestrator import get_memory_index

logger = logging.getLogger(__name__)

# How many records one search returns. Sized for a context budget, not for
# completeness: a copilot answer grounded in eight records is auditable, one
# grounded in eighty is not.
DEFAULT_LIMIT = 8

# Below this, a record is not related enough to be worth a reader's attention
# or a slot in a prompt. Tuned to sit above incidental word overlap.
DEFAULT_MIN_SCORE = 0.35

# Hard ceiling regardless of what a caller asks for. A retrieval API that will
# return a thousand rows on request is a denial-of-context vector once it is
# wired to anything user-facing.
MAX_LIMIT = 50

# When a Decision and its Evidence both match, they are the same claim indexed
# twice and returning both spends two budget slots to say one thing. The more
# specific record wins: a Decision carries status and ownership an Evidence row
# does not, and it still resolves to the same citation.
_SPECIFICITY = {"decision": 3, "commitment": 3, "topic": 2, "evidence": 1}


async def search_corpus(
    query: str,
    *,
    org_id: str | None = None,
    record_types: tuple[RecordType, ...] = RECORD_TYPES,
    limit: int = DEFAULT_LIMIT,
    min_score: float = DEFAULT_MIN_SCORE,
    mode: MatchKind = "hybrid",
    collapse_duplicates: bool = True,
    embedder=None,
    db=None,
) -> list[MemoryRecord]:
    """Rank records from every meeting in ``org_id`` against ``query``.

    Returns at most ``limit`` records, best first, each carrying the meeting and
    timestamp it came from and — for everything but a topic — the Evidence id
    backing it.

    ``collapse_duplicates`` folds records that share an Evidence id down to the
    most specific one, so a claim indexed as both a Decision and its Evidence
    does not occupy two slots of a budget sized for eight.
    """
    index = get_memory_index()
    limit = max(1, min(limit, MAX_LIMIT))
    # Over-fetch before collapsing, or folding duplicates would return fewer
    # than `limit` distinct claims.
    fetch = min(MAX_LIMIT, limit * 3) if collapse_duplicates else limit
    results = await index.search(
        query,
        org_id=org_id,
        record_types=record_types,
        limit=fetch,
        min_score=min_score,
        mode=mode,
        embedder=embedder,
        db=db,
    )
    if collapse_duplicates:
        results = _collapse(results)[:limit]
    logger.debug(
        "corpus search %r -> %d record(s) across %d meeting(s)",
        query[:60],
        len(results),
        len({r.meeting_id for r in results}),
    )
    return results


async def index_meeting(meeting_id: str, *, embedder=None, db=None) -> IndexReport:
    """Make one meeting's topics, evidence, decisions and commitments findable.

    Idempotent — safe to call after every extraction. Only records whose text
    changed are re-embedded.
    """
    return await get_memory_index().index_meeting(meeting_id, embedder=embedder, db=db)


async def index_document(document_id: str, *, embedder=None, db=None) -> IndexReport:
    """Make one document's chunks findable across the corpus.

    Separate from ``index_meeting``: a contract is uploaded once and referenced
    by several meetings, and re-indexing every linked meeting to pick it up
    would be both wasteful and easy to forget.
    """
    return await get_memory_index().index_document(document_id, embedder=embedder, db=db)


async def purge_document(document_id: str, *, db=None) -> int:
    """Remove a document's chunks from the corpus index."""
    return await get_memory_index().delete_document(document_id, db=db)


async def purge_meeting(meeting_id: str, *, db=None) -> int:
    """Remove a meeting's records from the corpus index.

    Called by retention: an index entry that outlives the transcript it
    describes is retained personal data that no transcript purge will find.
    """
    return await get_memory_index().delete_meeting(meeting_id, db=db)


def _collapse(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """Fold records sharing an Evidence id down to the most specific one.

    Ties on specificity break on score, then on the original order, so the
    result stays deterministic. Records without an Evidence id (topics) are
    never folded — they have nothing to be a duplicate of.
    """
    best: dict[str, MemoryRecord] = {}
    passthrough: list[MemoryRecord] = []
    for record in records:
        if not record.evidence_id:
            passthrough.append(record)
            continue
        incumbent = best.get(record.evidence_id)
        if incumbent is None or (
            _SPECIFICITY.get(record.record_type, 0),
            record.score,
        ) > (_SPECIFICITY.get(incumbent.record_type, 0), incumbent.score):
            best[record.evidence_id] = record

    merged = [*best.values(), *passthrough]
    merged.sort(key=lambda record: record.score, reverse=True)
    return merged
