"""SQLite corpus index: brute-force cosine plus FTS5 keyword search.

Two retrieval paths over the same rows.

**Vector.** Embeddings are stored as little-endian float32 blobs on
``memory_records``, matching how ``TranscriptSegment.embedding`` and
``Speaker.voice_embedding`` are already stored. Similarity is cosine, computed
in Python over every candidate in the org. That is O(corpus) per query and
exact — no recall loss, no index to tune, no dependency. For a club or a small
team's corpus it is comfortably fast; past roughly ten thousand records it will
not be, and that is the point at which ``MemoryIndexConfig.supports_ann_index``
stops being a description and starts being a prompt to swap the backend.

**Keyword.** SQLite's own FTS5, as the brief asked — Postgres full-text search
is not available here, and adding a search dependency for one feature would be
worse than using what ships with the database. FTS5 gives stemming-free but
prefix- and phrase-capable matching with BM25 ranking, which is exactly what
the vector path is bad at: proper nouns, project codenames, and numbers.

**Why both.** They fail in opposite directions. Embeddings find "the Aktau
expansion" when someone said "the Kazakhstan site rollout", and miss it when
the only shared token is a codename the embedding model has never seen. BM25
does the reverse. Hybrid takes the max of the two normalised scores rather than
a weighted sum, so a strong hit on either path survives instead of being
diluted by a zero from the other.
"""

from __future__ import annotations

import logging
import struct

from sqlalchemy import text as sql_text

from ..base import (
    RECORD_TYPES,
    IndexReport,
    MatchKind,
    MemoryIndex,
    MemoryIndexConfig,
    MemoryRecord,
    RecordType,
)

logger = logging.getLogger(__name__)

# Weight applied to a keyword hit before it is compared with a vector score.
# BM25 is unbounded and cosine is [-1, 1], so the two are normalised into a
# common range before the max is taken.
KEYWORD_CEILING = 20.0


def pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


class SqliteMemoryIndex(MemoryIndex):
    """The default backend. Exact similarity, no ANN index."""

    def __init__(self) -> None:
        super().__init__(
            MemoryIndexConfig(
                name="sqlite",
                supports_vector=True,
                supports_keyword=True,
                supports_ann_index=False,
                notes=(
                    "Brute-force cosine over the org's records plus FTS5 keyword search. "
                    "Exact but O(corpus) per query; move to a pgvector backend when the "
                    "corpus outgrows a full scan."
                ),
            )
        )

    # -- schema ------------------------------------------------------------

    def _ensure_schema(self, db) -> None:
        """Create the index tables on first use. Idempotent."""
        db.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    org_id TEXT,
                    meeting_id TEXT,
                    record_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    evidence_id TEXT,
                    verification_status TEXT,
                    start_ms INTEGER,
                    end_ms INTEGER,
                    embedding BLOB,
                    embedding_dim INTEGER,
                    language TEXT,
                    document_id TEXT,
                    page INTEGER,
                    UNIQUE (record_type, record_id)
                )
                """
            )
        )
        for statement in (
            "CREATE INDEX IF NOT EXISTS ix_memory_org ON memory_records (org_id)",
            "CREATE INDEX IF NOT EXISTS ix_memory_meeting ON memory_records (meeting_id)",
            "CREATE INDEX IF NOT EXISTS ix_memory_type ON memory_records (record_type)",
            "CREATE INDEX IF NOT EXISTS ix_memory_document ON memory_records (document_id)",
        ):
            db.execute(sql_text(statement))

        # Columns added after the table shipped. SQLite has no
        # "ADD COLUMN IF NOT EXISTS", so this checks first.
        existing = {row[1] for row in db.execute(sql_text("PRAGMA table_info(memory_records)"))}
        for column, ddl in (
            ("language", "language TEXT"),
            ("document_id", "document_id TEXT"),
            ("page", "page INTEGER"),
        ):
            if column not in existing:
                db.execute(sql_text(f"ALTER TABLE memory_records ADD COLUMN {ddl}"))

        # FTS5 mirror. `content=` would avoid duplicating the text, but an
        # external-content table needs triggers kept in sync by hand; at this
        # corpus size a plain copy is the simpler thing that cannot drift.
        db.execute(
            sql_text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts "
                "USING fts5(text, record_key UNINDEXED, tokenize='porter unicode61')"
            )
        )
        db.commit()

    # -- indexing ----------------------------------------------------------

    def _collect(self, db, meeting_id: str) -> list[dict]:
        """Every indexable record for one meeting, flattened."""
        from ...database import Commitment, Decision, Evidence, Meeting, Topic, TranscriptSegment

        meeting = db.query(Meeting).filter_by(id=meeting_id).first()
        if meeting is None:
            return []

        rows: list[dict] = []

        for topic in db.query(Topic).filter_by(meeting_id=meeting_id).all():
            if not (topic.label or "").strip():
                continue
            rows.append(
                {
                    "record_type": "topic",
                    "record_id": topic.id,
                    "text": topic.label,
                    "evidence_id": None,
                    "verification_status": None,
                    "start_ms": topic.start_ms,
                    "end_ms": topic.end_ms,
                }
            )

        for evidence in db.query(Evidence).filter_by(meeting_id=meeting_id).all():
            claim = (evidence.claim_text or evidence.quote or "").strip()
            if not claim:
                continue
            rows.append(
                {
                    "record_type": "evidence",
                    "record_id": evidence.id,
                    "text": claim,
                    "evidence_id": evidence.id,
                    "verification_status": evidence.verification_status,
                    "start_ms": evidence.start_ms,
                    "end_ms": evidence.end_ms,
                }
            )

        for model, kind, attribute in (
            (Decision, "decision", "title"),
            (Commitment, "commitment", "text"),
        ):
            for item in db.query(model).filter_by(meeting_id=meeting_id).all():
                claim = (getattr(item, attribute, None) or "").strip()
                if not claim:
                    continue
                description = getattr(item, "description", None)
                evidence = item.evidence
                rows.append(
                    {
                        "record_type": kind,
                        "record_id": item.id,
                        "text": f"{claim} {description}".strip() if description else claim,
                        "evidence_id": evidence.id if evidence else None,
                        "verification_status": item.verification_status,
                        "start_ms": evidence.start_ms if evidence else None,
                        "end_ms": evidence.end_ms if evidence else None,
                    }
                )

        # Language is tagged per segment, so a meeting's records inherit the
        # language of the segment they cite rather than the meeting's default.
        # A bilingual meeting is the norm here, not the exception.
        segment_language = {
            row[0]: row[1]
            for row in db.query(TranscriptSegment.id, TranscriptSegment.language).filter_by(meeting_id=meeting_id).all()
        }
        citation_language = {}
        for evidence in db.query(Evidence).filter_by(meeting_id=meeting_id).all():
            for citation in evidence.citations:
                language = segment_language.get(citation.segment_id)
                if language:
                    citation_language[evidence.id] = language
                    break

        for row in rows:
            row["org_id"] = meeting.org_id
            row["meeting_id"] = meeting_id
            row.setdefault("document_id", None)
            row.setdefault("page", None)
            row["language"] = citation_language.get(row.get("evidence_id")) or meeting.language
        return rows

    def _collect_document(self, db, document_id: str) -> list[dict]:
        """Every indexable chunk of one document."""
        from ...database import Document, DocumentChunk

        document = db.query(Document).filter_by(id=document_id).first()
        if document is None:
            return []

        rows = []
        for chunk in db.query(DocumentChunk).filter_by(document_id=document_id).order_by(DocumentChunk.ordinal).all():
            text = (chunk.text or "").strip()
            if not text:
                continue
            rows.append(
                {
                    "record_type": "document",
                    "record_id": chunk.id,
                    "text": text,
                    "evidence_id": None,
                    "verification_status": None,
                    # A document has no timeline; page is its coordinate.
                    "start_ms": None,
                    "end_ms": None,
                    "org_id": document.org_id,
                    # meeting_id carries the document's home meeting so a
                    # citation can name where it was filed; document_id is what
                    # actually identifies the source.
                    "meeting_id": document.meeting_id,
                    "document_id": document_id,
                    "page": chunk.page,
                    "language": chunk.language or document.language,
                }
            )
        return rows

    async def index_meeting(self, meeting_id: str, *, embedder=None, db=None) -> IndexReport:
        return await self._index(
            lambda session: self._collect(session, meeting_id),
            scope_column="meeting_id",
            scope_value=meeting_id,
            embedder=embedder,
            db=db,
        )

    async def index_document(self, document_id: str, *, embedder=None, db=None) -> IndexReport:
        return await self._index(
            lambda session: self._collect_document(session, document_id),
            scope_column="document_id",
            scope_value=document_id,
            embedder=embedder,
            db=db,
        )

    async def _index(self, collect, *, scope_column: str, scope_value: str, embedder=None, db=None) -> IndexReport:
        from ...database import new_session

        owns = db is None
        db = db or new_session()
        try:
            self._ensure_schema(db)
            report = IndexReport()
            if scope_column == "meeting_id":
                report.meeting_id = scope_value
            rows = collect(db)
            if not rows:
                return report
            report.org_id = rows[0]["org_id"]

            # Only embed what changed. Re-indexing after every extraction is
            # the normal path, and re-embedding an unchanged corpus would make
            # that cost real money each time.
            existing = {
                (r[0], r[1]): r[2]
                for r in db.execute(
                    sql_text(f"SELECT record_type, record_id, text FROM memory_records WHERE {scope_column} = :scope"),
                    {"scope": scope_value},
                )
            }
            stale = [row for row in rows if existing.get((row["record_type"], row["record_id"])) != row["text"]]
            report.skipped = len(rows) - len(stale)

            vectors: list[list[float]] = []
            if stale:
                if embedder is None:
                    from ...ai import get_embedding_provider

                    embedder = get_embedding_provider()
                vectors = await embedder.embed([row["text"] for row in stale])
                if len(vectors) != len(stale):
                    raise ValueError(f"Embedder returned {len(vectors)} vectors for {len(stale)} records")

            for row, vector in zip(stale, vectors, strict=True):
                key = f"{row['record_type']}:{row['record_id']}"
                db.execute(sql_text("DELETE FROM memory_fts WHERE record_key = :k"), {"k": key})
                db.execute(
                    sql_text(
                        "INSERT INTO memory_records (id, org_id, meeting_id, record_type, "
                        "record_id, text, evidence_id, verification_status, start_ms, end_ms, "
                        "embedding, embedding_dim, language, document_id, page) VALUES "
                        "(:id, :org, :meeting, :type, :rid, :text, :ev, :vs, :start, :end, "
                        ":emb, :dim, :lang, :doc, :page) "
                        "ON CONFLICT(record_type, record_id) DO UPDATE SET "
                        "text=excluded.text, evidence_id=excluded.evidence_id, "
                        "verification_status=excluded.verification_status, "
                        "start_ms=excluded.start_ms, end_ms=excluded.end_ms, "
                        "embedding=excluded.embedding, embedding_dim=excluded.embedding_dim, "
                        "language=excluded.language, document_id=excluded.document_id, "
                        "page=excluded.page"
                    ),
                    {
                        "id": key,
                        "org": row["org_id"],
                        "meeting": row["meeting_id"],
                        "type": row["record_type"],
                        "rid": row["record_id"],
                        "text": row["text"],
                        "ev": row["evidence_id"],
                        "vs": row["verification_status"],
                        "start": row["start_ms"],
                        "end": row["end_ms"],
                        "emb": pack(vector),
                        "dim": len(vector),
                        "lang": row.get("language"),
                        "doc": row.get("document_id"),
                        "page": row.get("page"),
                    },
                )
                db.execute(
                    sql_text("INSERT INTO memory_fts (text, record_key) VALUES (:t, :k)"),
                    {"t": row["text"], "k": key},
                )
                report.embedded += 1

            db.commit()
            if report.embedded:
                logger.info(
                    "Indexed %d record(s) for %s=%s (%d unchanged)",
                    report.embedded,
                    scope_column,
                    scope_value,
                    report.skipped,
                )
            return report
        finally:
            if owns:
                db.close()

    async def delete_document(self, document_id: str, *, db=None) -> int:
        return await self._delete("document_id", document_id, db=db)

    async def delete_meeting(self, meeting_id: str, *, db=None) -> int:
        return await self._delete("meeting_id", meeting_id, db=db)

    async def _delete(self, scope_column: str, scope_value: str, *, db=None) -> int:
        from ...database import new_session

        owns = db is None
        db = db or new_session()
        try:
            self._ensure_schema(db)
            keys = [
                r[0]
                for r in db.execute(
                    sql_text(f"SELECT id FROM memory_records WHERE {scope_column} = :scope"),
                    {"scope": scope_value},
                )
            ]
            for key in keys:
                db.execute(sql_text("DELETE FROM memory_fts WHERE record_key = :k"), {"k": key})
            db.execute(
                sql_text(f"DELETE FROM memory_records WHERE {scope_column} = :scope"),
                {"scope": scope_value},
            )
            db.commit()
            return len(keys)
        finally:
            if owns:
                db.close()

    # -- retrieval ---------------------------------------------------------

    def _keyword_hits(self, db, query: str, limit: int) -> dict[str, float]:
        """FTS5 BM25 scores, normalised to [0, 1]. Lower BM25 = better match."""
        # FTS5 treats punctuation as syntax; quote each term so a query like
        # "Aktau expansion (Q3)" cannot become a malformed MATCH expression.
        terms = [t for t in "".join(c if c.isalnum() else " " for c in query).split() if t]
        if not terms:
            return {}
        expression = " OR ".join(f'"{term}"' for term in terms)
        try:
            rows = db.execute(
                sql_text(
                    "SELECT record_key, bm25(memory_fts) AS rank FROM memory_fts "
                    "WHERE memory_fts MATCH :q ORDER BY rank LIMIT :n"
                ),
                {"q": expression, "n": limit * 4},
            ).fetchall()
        except Exception as exc:
            logger.warning("FTS query failed for %r: %s", query, exc)
            return {}
        return {
            key: max(0.0, min(1.0, 1.0 - (abs(rank) / KEYWORD_CEILING))) if rank is not None else 0.0
            for key, rank in rows
        }

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
        db=None,
    ) -> list[MemoryRecord]:
        from ...database import new_session
        from ...meetings.segmentation import cosine_similarity

        self._check_mode(mode)
        query = (query or "").strip()
        if not query:
            return []

        owns = db is None
        db = db or new_session()
        try:
            self._ensure_schema(db)

            # Record types are a fixed Literal from base.py, never caller
            # text, but they are still bound rather than interpolated so the
            # query has exactly one way to reach the database.
            type_params = {f"t{i}": value for i, value in enumerate(record_types)}
            clauses = [f"record_type IN ({', '.join(':' + k for k in type_params)})"]
            params: dict = dict(type_params)
            if org_id:
                clauses.append("org_id = :org")
                params["org"] = org_id

            rows = db.execute(
                sql_text(
                    "SELECT id, org_id, meeting_id, record_type, record_id, text, evidence_id, "
                    "verification_status, start_ms, end_ms, embedding, embedding_dim, "
                    "language, document_id, page "
                    f"FROM memory_records WHERE {' AND '.join(clauses)}"
                ),
                params,
            ).fetchall()
            if not rows:
                return []

            keyword_scores: dict[str, float] = {}
            if mode in ("keyword", "hybrid"):
                keyword_scores = self._keyword_hits(db, query, limit)

            vector_scores: dict[str, float] = {}
            if mode in ("vector", "hybrid"):
                if embedder is None:
                    from ...ai import get_embedding_provider

                    embedder = get_embedding_provider()
                query_vector = (await embedder.embed([query]))[0]
                for row in rows:
                    if not row[10] or (row[11] and row[11] != len(query_vector)):
                        continue
                    vector_scores[row[0]] = cosine_similarity(unpack(row[10]), query_vector)

            titles = {r[0]: r[1] for r in db.execute(sql_text("SELECT id, title FROM meetings")).fetchall()}
            doc_titles = {r[0]: r[1] for r in db.execute(sql_text("SELECT id, title FROM documents")).fetchall()}

            results: list[MemoryRecord] = []
            for row in rows:
                key = row[0]
                vector_score = vector_scores.get(key)
                keyword_score = keyword_scores.get(key)
                # Max, not a weighted sum: the two paths fail in opposite
                # directions, so a strong hit on either is real signal and must
                # not be halved by the other returning nothing.
                candidates = [s for s in (vector_score, keyword_score) if s is not None]
                if not candidates:
                    continue
                score = max(candidates)
                if score < min_score:
                    continue

                if vector_score is not None and keyword_score is not None:
                    match: MatchKind = "hybrid"
                elif keyword_score is not None and (vector_score is None or keyword_score > vector_score):
                    match = "keyword"
                else:
                    match = "vector"

                document_id = row[13]
                # A document record is titled by its document, not its meeting:
                # a citation has to say which file it came from.
                title = doc_titles.get(document_id) if document_id else titles.get(row[2])
                results.append(
                    MemoryRecord(
                        record_type=row[3],
                        record_id=row[4],
                        text=row[5],
                        meeting_id=document_id or row[2],
                        meeting_title=title,
                        org_id=row[1],
                        start_ms=row[8],
                        end_ms=row[9],
                        evidence_id=row[6],
                        verification_status=row[7],
                        language=row[12],
                        document_id=document_id,
                        page=row[14],
                        score=score,
                        match=match,
                        vector_score=vector_score,
                        keyword_score=keyword_score,
                    )
                )

            results.sort(key=lambda record: record.score, reverse=True)
            return results[:limit]
        finally:
            if owns:
                db.close()
