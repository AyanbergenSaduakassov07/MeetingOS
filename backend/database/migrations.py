"""Column-level migrations for the MeetingOS SQLite database.

Why not Alembic?  Inherited from voicebox, and still true for v0.1: the
column-existence checks below are idempotent, run in <50 ms on startup, and
need no extra files to survive packaging.  ``Base.metadata.create_all`` in
``session.py`` handles *new* tables; this module handles changes to tables
that already exist in a deployed database.

That calculus changes the moment MeetingOS runs multi-tenant on Postgres
rather than one SQLite file per install — at that point migration ordering,
rollback, and team coordination start to matter and this should become
Alembic.  Treat this file as deliberately temporary.

Adding a new migration:
    1. Append a new ``_migrate_*`` helper at the bottom of this file.
    2. Call it from ``run_migrations()`` in the appropriate spot.
    3. The helper must check column/table existence before acting
       (idempotent) and log a short message when it does real work.
"""

import logging
import uuid

from sqlalchemy import inspect, text

from .models import Base, DocumentChunk, Evidence, EvidenceCitation, MeetingDocument, ProviderCall

logger = logging.getLogger(__name__)


def run_migrations(engine) -> None:
    """Run all schema migrations.  Safe to call on every startup.

    Empty for v0.1 — the schema is new, so there is no deployed database to
    migrate from.  The helpers below are the supported way to add the first
    one; keep them rather than deleting them for being unused.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if not tables:
        logger.debug("Fresh database, no migrations to run")
        return

    _migrate_verification_columns(engine, inspector, tables)
    _migrate_segment_embeddings(engine, inspector, tables)
    _migrate_evidence(engine, inspector, tables)
    _migrate_documents(engine, inspector, tables)
    _migrate_provider_calls(engine, inspector, tables)


# -- helpers ---------------------------------------------------------------


def _get_columns(inspector, table: str) -> set[str]:
    """Return the column names of ``table``."""
    return {col["name"] for col in inspector.get_columns(table)}


def _add_column(engine, table: str, column_sql: str, label: str) -> None:
    """Add a column unconditionally; callers check existence first.

    ``column_sql`` is a trusted literal written in this file, never user
    input — SQLite cannot parameterize DDL identifiers.
    """
    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_sql}"))
        conn.commit()
    logger.info("Added %s column to %s", label, table)


def _ensure_column(engine, inspector, tables: set[str], table: str, column: str, column_sql: str) -> None:
    """Idempotently add ``column`` to ``table`` if the table exists without it."""
    if table not in tables:
        return
    if column in _get_columns(inspector, table):
        return
    _add_column(engine, table, column_sql, column)


def _migrate_verification_columns(engine, inspector, tables: set[str]) -> None:
    """Superseded by Evidence (see ``_migrate_evidence``). Deliberately inert.

    This used to add ``verification_status`` / ``verification_score`` /
    ``source_quote`` to the four extracted-item tables. Evidence now owns those
    fields, and the item models expose them as properties rather than columns —
    so re-adding them here put the two migrations in a loop, one creating what
    the other dropped on every startup.

    Kept as a named no-op rather than deleted so the history is legible: a
    database migrated before Evidence still has these columns, and
    ``_drop_legacy_citation_columns`` is what removes them.
    """
    return


def _migrate_segment_embeddings(engine, inspector, tables: set[str]) -> None:
    """Add the copilot's retrieval index to transcript_segments (v0.1.0).

    Segments transcribed before the copilot existed have no vector; they are
    backfilled lazily on the first question asked about their meeting rather
    than in a migration, because embedding costs an API call per segment and a
    startup migration is the wrong place to spend one.
    """
    _ensure_column(engine, inspector, tables, "transcript_segments", "embedding", "embedding BLOB")
    _ensure_column(engine, inspector, tables, "transcript_segments", "embedding_model", "embedding_model VARCHAR")
    _ensure_column(engine, inspector, tables, "transcript_segments", "embedding_dim", "embedding_dim INTEGER")


def _migrate_evidence(engine, inspector, tables: set[str]) -> None:
    """Move loose citation columns onto Evidence records (v0.1.0).

    Extracted items used to carry ``source_segment_id``, ``source_quote``,
    ``extraction_confidence``, ``verification_status`` and ``verification_score``
    inline. Those five columns are now one Evidence row per claim.

    The old columns are left in place rather than dropped: SQLite cannot drop a
    column without rewriting the table, and a half-finished rewrite of a
    governance record is a worse outcome than a few dead columns. They stop
    being read the moment this runs.
    """
    if "evidence" not in inspector.get_table_names():
        Base.metadata.create_all(engine, tables=[Evidence.__table__, EvidenceCitation.__table__])
        logger.info("Created evidence and evidence_citations tables")
        inspector = inspect(engine)

    for table in ("decisions", "action_items", "risks", "commitments"):
        _ensure_column(engine, inspector, tables, table, "evidence_id", "evidence_id VARCHAR")

    _backfill_evidence(engine)
    _drop_legacy_citation_columns(engine)


def _backfill_evidence(engine) -> None:
    """Create one Evidence row per already-extracted item that lacks one.

    Idempotent: an item that already has ``evidence_id`` is skipped, so this is
    safe to run on every startup.
    """
    migrated = 0
    with engine.connect() as conn:
        for table in ("decisions", "action_items", "risks", "commitments"):
            columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if "evidence_id" not in columns:
                continue
            # Every legacy column must still be present to backfill from. Once
            # `_drop_legacy_citation_columns` has run there is nothing left to
            # read, and selecting a dropped column raises — which previously
            # aborted the whole migration before the drop could finish.
            legacy = {
                "source_segment_id",
                "source_quote",
                "extraction_confidence",
                "verification_status",
                "verification_score",
            }
            if not legacy <= columns:
                continue

            rows = conn.execute(
                text(
                    f"SELECT id, org_id, meeting_id, source_segment_id, source_quote, "
                    f"extraction_confidence, verification_status, verification_score "
                    f"FROM {table} WHERE evidence_id IS NULL"
                )
            ).fetchall()

            for row in rows:
                item_id, org_id, meeting_id, segment_id, quote, confidence, status, score = row
                evidence_id = str(uuid.uuid4())
                start_ms = end_ms = None
                if segment_id:
                    span = conn.execute(
                        text("SELECT start_ms, end_ms FROM transcript_segments WHERE id = :sid"),
                        {"sid": segment_id},
                    ).fetchone()
                    if span:
                        start_ms, end_ms = span

                conn.execute(
                    text(
                        "INSERT INTO evidence (id, org_id, meeting_id, quote, start_ms, end_ms, "
                        "confidence, verification_status, verification_score) VALUES "
                        "(:id, :org, :meeting, :quote, :start, :end, :conf, :status, :score)"
                    ),
                    {
                        "id": evidence_id,
                        "org": org_id,
                        "meeting": meeting_id,
                        "quote": quote,
                        "start": start_ms,
                        "end": end_ms,
                        "conf": confidence,
                        "status": status or "unverified",
                        "score": score,
                    },
                )
                if segment_id:
                    conn.execute(
                        text(
                            "INSERT INTO evidence_citations (id, evidence_id, segment_id, sequence) "
                            "VALUES (:id, :ev, :seg, 0)"
                        ),
                        {"id": str(uuid.uuid4()), "ev": evidence_id, "seg": segment_id},
                    )
                conn.execute(
                    text(f"UPDATE {table} SET evidence_id = :ev WHERE id = :id"),
                    {"ev": evidence_id, "id": item_id},
                )
                migrated += 1
        conn.commit()

    if migrated:
        logger.info("Backfilled %d extracted item(s) onto Evidence records", migrated)


def _migrate_documents(engine, inspector, tables: set[str]) -> None:
    """Add document chunking, language tagging, and meeting links (v0.1.0).

    Chunks and links are new tables. ``language`` lands on both documents and
    transcript segments: language was previously tracked per meeting only,
    which cannot represent a bilingual meeting — and those are the norm here,
    not the exception.
    """
    for table, model in (
        ("document_chunks", DocumentChunk),
        ("meeting_documents", MeetingDocument),
    ):
        if table not in inspector.get_table_names():
            Base.metadata.create_all(engine, tables=[model.__table__])
            logger.info("Created %s table", table)

    inspector = inspect(engine)
    _ensure_column(engine, inspector, tables, "documents", "language", "language VARCHAR")
    _ensure_column(engine, inspector, tables, "documents", "is_sensitive", "is_sensitive BOOLEAN DEFAULT 0")
    _ensure_column(engine, inspector, tables, "documents", "updated_at", "updated_at DATETIME")
    # transcript_segments.language already exists in the model; this covers
    # databases created before it was declared.
    _ensure_column(engine, inspector, tables, "transcript_segments", "language", "language VARCHAR")


# Columns superseded by Evidence. Left in place by the original migration on the
# reasoning that SQLite cannot drop a column cleanly — which was true of older
# SQLite and is no longer true of 3.35+.
# `source_segment_id` is deliberately absent: SQLite refuses to drop a column
# named in a foreign key definition, and the drop fails on every startup if it
# is attempted. It is nullable and unread, so it is harmless where it sits —
# unlike `verification_status`, which was NOT NULL and broke every insert.
_LEGACY_CITATION_COLUMNS = (
    "source_quote",
    "extraction_confidence",
    "verification_status",
    "verification_score",
)


def _drop_legacy_citation_columns(engine) -> None:
    """Drop the pre-Evidence citation columns from the extracted-item tables.

    Leaving them was a mistake, not merely untidy. ``verification_status`` was
    declared ``NOT NULL`` with no default, and once the ORM stopped writing it
    (it became a property delegating to Evidence) **every insert into a
    migrated database failed** with a NOT NULL constraint error. Fresh
    databases were fine, because the model no longer declares the column and
    ``create_all`` never creates it — so the fault only appeared on databases
    that had actually been through the migration, which is the worst place for
    it to hide.

    SQLite 3.35+ supports ``ALTER TABLE ... DROP COLUMN``. Older builds cannot,
    so the drop is attempted and a failure is logged rather than raised: a
    startup that refuses to boot over a dead column would be a worse outcome
    than carrying it.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dropped = 0

    for table in ("decisions", "action_items", "risks", "commitments"):
        if table not in tables:
            continue
        columns = _get_columns(inspector, table)
        for column in _LEGACY_CITATION_COLUMNS:
            if column not in columns:
                continue
            try:
                with engine.connect() as conn:
                    # An index over the column blocks the drop, so it goes
                    # first. These indexes served queries that now run against
                    # Evidence instead.
                    for index in inspector.get_indexes(table):
                        if column in index.get("column_names", []):
                            conn.execute(text(f'DROP INDEX IF EXISTS "{index["name"]}"'))
                    conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
                    conn.commit()
                dropped += 1
            except Exception as exc:
                # Keep going rather than breaking: `source_segment_id` carries a
                # foreign key that SQLite will not let go of, and stopping there
                # would skip `verification_status` — the NOT NULL column that is
                # actually breaking inserts.
                logger.warning("Could not drop legacy column %s.%s: %s", table, column, exc)
                continue

    if dropped:
        logger.info("Dropped %d legacy citation column(s) superseded by Evidence", dropped)


def _migrate_provider_calls(engine, inspector, tables: set[str]) -> None:
    """Add the outbound-call audit log (v0.1.0)."""
    if "provider_calls" not in inspector.get_table_names():
        Base.metadata.create_all(engine, tables=[ProviderCall.__table__])
        logger.info("Created provider_calls table")
