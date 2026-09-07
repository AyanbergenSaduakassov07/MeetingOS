"""Provider-agnostic contract for corpus-wide retrieval.

Shaped after ``backend/ai/base.py`` and ``backend/transcription/base.py``: a
dataclass of static capability metadata beside an ``abc.ABC``, with an
orchestrator that picks the implementation from an environment variable. The
three now read the same way, so knowing one means knowing all three.

Why a seam here at all
----------------------
Normally one implementation means a hypothetical seam, not a real one, and
inventing an interface for a single adapter is speculative generality. This is
the exception, for a reason that is already visible rather than imagined: the
original blueprint said Postgres + pgvector and the implementation is SQLite.
That gap is not theoretical — it has already caused confusion twice in this
project's history.

The concrete forcing function is scale. The SQLite backend scores by
brute-force cosine over every candidate row: exact, dependency-free, and
entirely adequate for a club or a small team. It is O(corpus) per query, so at
some corpus size it stops being adequate, and at that point the answer is a
real ANN index — pgvector, or something like it. Putting the seam here now
means that day is a backend swap behind ``get_memory_index()``, not a rewrite
of every call site.

What crosses the seam
---------------------
``MemoryRecord`` is the currency: a scored hit with the meeting and timestamp
it came from and, where the record type has one, the Evidence backing it. It is
deliberately not an ORM object — a backend that never loads SQLAlchemy (a
remote vector service, say) must still be able to return one.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# What kinds of record the corpus holds. Fixed here rather than discovered at
# runtime: a caller filtering by type should get a name error for a typo, not
# a silently empty result.
RecordType = Literal["topic", "evidence", "decision", "commitment", "document"]
RECORD_TYPES: tuple[RecordType, ...] = (
    "topic",
    "evidence",
    "decision",
    "commitment",
    "document",
)

MatchKind = Literal["vector", "keyword", "hybrid"]


@dataclass(frozen=True)
class MemoryRecord:
    """One scored hit from the corpus.

    ``evidence_id`` is what makes a hit auditable: a result the reader cannot
    trace back to a transcript is a claim without provenance, which is the
    failure this whole system exists to prevent. Topics have no Evidence and
    carry ``None``; every other type must carry one.
    """

    record_type: RecordType
    record_id: str
    text: str

    meeting_id: str | None = None
    meeting_title: str | None = None
    org_id: str | None = None

    start_ms: int | None = None
    end_ms: int | None = None

    evidence_id: str | None = None
    verification_status: str | None = None

    # Source language of this record, as tagged at ingestion. Carried through
    # so a citation can be shown in the language it was actually said or
    # written in, rather than silently presented as if it were the query's.
    language: str | None = None
    # For a document record: which document, and where inside it.
    document_id: str | None = None
    page: int | None = None

    score: float = 0.0
    match: MatchKind = "vector"
    # Per-signal scores, kept so a caller can see *why* something ranked.
    vector_score: float | None = None
    keyword_score: float | None = None

    def __repr__(self) -> str:
        return f"<MemoryRecord {self.record_type}:{self.record_id[:8]} score={self.score:.3f} match={self.match}>"


@dataclass
class IndexReport:
    """What one indexing pass did."""

    org_id: str | None = None
    meeting_id: str | None = None
    embedded: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class MemoryIndexConfig:
    """Static description of a backend, read once at startup."""

    name: str
    # Whether the backend can do each retrieval path at all. A caller asking
    # for a hybrid search against a keyword-only backend should get a clear
    # capability error, not silently degraded results.
    supports_vector: bool = True
    supports_keyword: bool = True
    # True when similarity is served by a real index rather than a full scan.
    # False here is not a defect; it is the honest description of a brute-force
    # backend, and the signal that tells an operator when to move.
    supports_ann_index: bool = False
    embedding_dim: int | None = None
    notes: str = ""


class MemoryIndex(ABC):
    """Interface every corpus-retrieval backend implements."""

    config: MemoryIndexConfig

    def __init__(self, config: MemoryIndexConfig) -> None:
        self.config = config

    # -- required ----------------------------------------------------------

    @abstractmethod
    async def index_document(self, document_id: str, *, embedder=None) -> IndexReport:
        """Make one document's chunks searchable. Idempotent.

        Separate from ``index_meeting`` because documents are ingested on their
        own schedule — a contract is uploaded once and referenced by several
        meetings, and re-indexing every linked meeting to pick it up would be
        both wasteful and easy to forget.
        """

    @abstractmethod
    async def delete_document(self, document_id: str) -> int:
        """Remove a document's chunks from the index. Returns rows removed."""

    @abstractmethod
    async def index_meeting(self, meeting_id: str, *, embedder=None) -> IndexReport:
        """Make one meeting's records searchable. Idempotent.

        Re-running must not duplicate rows or re-embed what is already indexed;
        callers reindex after every extraction and cannot track state for the
        backend.
        """

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        org_id: str | None = None,
        record_types: tuple[RecordType, ...] = RECORD_TYPES,
        limit: int = 10,
        min_score: float = 0.0,
        mode: MatchKind = "hybrid",
        embedder=None,
    ) -> list[MemoryRecord]:
        """Top-``limit`` records across the whole corpus, best first.

        Scoped to ``org_id`` when given. Results below ``min_score`` are
        dropped rather than returned as weak matches — a budgeted retrieval
        returns few good rows, not everything above zero.
        """

    @abstractmethod
    async def delete_meeting(self, meeting_id: str) -> int:
        """Remove a meeting's records from the index. Returns rows removed.

        Required, not optional: retention deletes meetings, and an index entry
        that outlives its transcript is retained personal data that no purge
        will find.
        """

    # -- shared ------------------------------------------------------------

    async def health(self) -> dict:
        """Cheap description for ``/health``. Does not touch the corpus."""
        return {
            "backend": self.config.name,
            "supports_vector": self.config.supports_vector,
            "supports_keyword": self.config.supports_keyword,
            "supports_ann_index": self.config.supports_ann_index,
            "notes": self.config.notes,
        }

    def _check_mode(self, mode: MatchKind) -> None:
        """Fail loudly when a backend is asked for a path it does not have."""
        if mode in ("vector", "hybrid") and not self.config.supports_vector:
            raise CapabilityError(f"{self.config.name} cannot do vector search.")
        if mode in ("keyword", "hybrid") and not self.config.supports_keyword:
            raise CapabilityError(f"{self.config.name} cannot do keyword search.")

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.config.name}>"


class CapabilityError(RuntimeError):
    """A backend was asked for a retrieval path it does not implement."""
