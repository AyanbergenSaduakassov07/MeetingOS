"""Enforce ``Organization.retention_days``.

``retention_days`` has existed on the org since the first schema, defaulting to
365, and nothing has ever read it. A retention period that no code enforces is
worse than none: it reads as a commitment in the model, appears in any
privacy review as a control, and deletes nothing.

What a purge removes
--------------------
Everything derived from a meeting past its retention date, in dependency order:
extracted items, topics, transcript segments (**including their embeddings**),
speakers (**including voice embeddings**), the meeting row, and the recording
file on disk.

Embeddings are deleted with the text rather than left behind. A vector is not
an anonymous artefact — text embeddings can be partially inverted to recover
their source — so an embedding that outlives the transcript it was made from is
retained personal data wearing a disguise. The same applies to
``Speaker.voice_embedding``, which is biometric.

Dry run by default
------------------
``purge_expired`` reports what it would delete unless ``commit=True``. This is
irreversible deletion of the only copy of a governance record; the default has
to be the one that cannot lose a board pack to a misconfigured
``retention_days``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from .. import config
from ..database import (
    ActionItem,
    Commitment,
    Decision,
    DocumentChunk,
    Evidence,
    EvidenceCitation,
    Meeting,
    MeetingDocument,
    Organization,
    Risk,
    Speaker,
    Topic,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)


@dataclass
class PurgeReport:
    committed: bool = False
    meetings: int = 0
    segments: int = 0
    speakers: int = 0
    extracted_items: int = 0
    recordings_deleted: int = 0
    recordings_missing: int = 0
    details: list[str] = field(default_factory=list)


def _cutoff(org: Organization, now: datetime) -> datetime | None:
    days = org.retention_days
    if not days or days <= 0:
        return None  # 0 or null means "keep indefinitely", an explicit choice
    return now - timedelta(days=days)


def purge_expired(
    db: Session,
    *,
    commit: bool = False,
    now: datetime | None = None,
) -> PurgeReport:
    """Delete meetings past their organization's retention period.

    Dry run unless ``commit=True``.
    """
    now = now or datetime.now(UTC)
    report = PurgeReport(committed=commit)

    for org in db.query(Organization).all():
        cutoff = _cutoff(org, now)
        if cutoff is None:
            continue

        expired = db.query(Meeting).filter(Meeting.org_id == org.id, Meeting.created_at < cutoff).all()
        for meeting in expired:
            segment_count = db.query(TranscriptSegment).filter_by(meeting_id=meeting.id).count()
            speaker_count = db.query(Speaker).filter_by(meeting_id=meeting.id).count()
            item_count = sum(
                db.query(model).filter_by(meeting_id=meeting.id).count()
                for model in (Decision, ActionItem, Risk, Commitment)
            )

            report.meetings += 1
            report.segments += segment_count
            report.speakers += speaker_count
            report.extracted_items += item_count
            report.details.append(
                f"{meeting.id[:8]} {meeting.title!r} (created {meeting.created_at:%Y-%m-%d}, {segment_count} segments)"
            )

            recording = config.resolve_storage_path(meeting.recording_path)
            if recording and recording.is_file():
                if commit:
                    recording.unlink()
                report.recordings_deleted += 1
            elif meeting.recording_path:
                report.recordings_missing += 1

            if commit:
                # The corpus index holds a copy of the claim text and its
                # embedding. An index entry that outlives the transcript it
                # describes is retained personal data no transcript purge finds.
                try:
                    import asyncio

                    from ..database import Document
                    from ..memory import purge_document, purge_meeting

                    asyncio.run(purge_meeting(meeting.id, db=db))
                    # Documents filed against this meeting go with it. A
                    # contract's text and embedding outliving the meeting it
                    # belongs to is retained personal data no purge would find.
                    for document in db.query(Document).filter_by(meeting_id=meeting.id).all():
                        asyncio.run(purge_document(document.id, db=db))
                except Exception as exc:  # index absence must not block a purge
                    logger.warning("Could not purge corpus index for %s: %s", meeting.id, exc)

                # Children first: the segment rows carry the embeddings, and a
                # cascade is not configured on every relationship. Evidence
                # citations reference segments, so they must go before them.
                evidence_ids = [row.id for row in db.query(Evidence).filter_by(meeting_id=meeting.id).all()]
                if evidence_ids:
                    db.query(EvidenceCitation).filter(EvidenceCitation.evidence_id.in_(evidence_ids)).delete(
                        synchronize_session=False
                    )
                # Document chunks reference documents, so they go first.
                document_ids = [row.id for row in db.query(Document).filter_by(meeting_id=meeting.id).all()]
                if document_ids:
                    db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(document_ids)).delete(
                        synchronize_session=False
                    )
                    db.query(MeetingDocument).filter(MeetingDocument.document_id.in_(document_ids)).delete(
                        synchronize_session=False
                    )
                db.query(MeetingDocument).filter_by(meeting_id=meeting.id).delete(synchronize_session=False)
                for model in (
                    Decision,
                    ActionItem,
                    Risk,
                    Commitment,
                    Evidence,
                    Topic,
                    Document,
                    TranscriptSegment,
                    Speaker,
                ):
                    db.query(model).filter_by(meeting_id=meeting.id).delete(synchronize_session=False)
                db.query(Meeting).filter_by(id=meeting.id).delete(synchronize_session=False)

    if commit:
        db.commit()
        logger.info(
            "Retention purge: removed %d meeting(s), %d segment(s), %d speaker(s), %d item(s), %d recording(s)",
            report.meetings,
            report.segments,
            report.speakers,
            report.extracted_items,
            report.recordings_deleted,
        )
    else:
        logger.info("Retention dry run: %d meeting(s) are past retention", report.meetings)

    return report


def main() -> int:
    """``python -m backend.meetings.retention [--commit]``"""
    import argparse

    from ..database import init_db, new_session

    parser = argparse.ArgumentParser(description="Delete meetings past their retention period.")
    parser.add_argument("--commit", action="store_true", help="actually delete (default: dry run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    init_db()
    db = new_session()
    try:
        report = purge_expired(db, commit=args.commit)
    finally:
        db.close()

    mode = "DELETED" if report.committed else "would delete (dry run)"
    print(f"\nRetention purge — {mode}:")
    print(f"  meetings         {report.meetings}")
    print(f"  segments         {report.segments}  (with their embeddings)")
    print(f"  speakers         {report.speakers}  (with voice embeddings)")
    print(f"  extracted items  {report.extracted_items}")
    print(f"  recordings       {report.recordings_deleted} deleted, {report.recordings_missing} already gone")
    for line in report.details:
        print(f"    {line}")
    if not report.committed and report.meetings:
        print("\nRe-run with --commit to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
