"""Commitment rollups across the org.

A query layer, deliberately. No extraction, no model, no new inference — the
data already exists in ``Commitment``, ``ActionItem`` and ``Evidence``; what
was missing was any way to ask about it across meetings.

Two kinds of obligation, kept apart
-----------------------------------
``Commitment`` is a promise a person made about themselves ("I'll chase the
invoice"). ``ActionItem`` is tracked work someone was given. They are scored
differently — a broken promise says something about follow-through that an
unfinished task does not — so they are surfaced side by side with a ``kind``
rather than merged into one list.

Overdue is computed here, not in the client
-------------------------------------------
The rule is: a deadline in the past and a status that is still open. Both parts
matter, and both live server-side, because a frontend computing "overdue" from
a date string will drift from whatever the reports and alerts use. Two clients
disagreeing about who is late is a worse failure than either being wrong.

Items with no deadline are never overdue. That is a deliberate choice over
guessing one: "I'll get to it" is a real commitment with no date, and inventing
a deadline in order to call it late would manufacture the accusation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from ..database import ActionItem, Commitment, Evidence, Meeting, User

logger = logging.getLogger(__name__)

Kind = Literal["commitment", "action_item"]

# Statuses that mean the obligation is still outstanding. Anything else — kept,
# done, cancelled, renegotiated — is settled and cannot be overdue.
OPEN_COMMITMENT_STATUSES = frozenset({"pending"})
OPEN_ACTION_STATUSES = frozenset({"open", "in_progress", "blocked"})

# Statuses that count as honoured when computing a completion rate.
COMPLETED_COMMITMENT_STATUSES = frozenset({"kept"})
COMPLETED_ACTION_STATUSES = frozenset({"done"})

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


@dataclass
class CommitmentView:
    """One obligation, with its provenance and computed state."""

    id: str
    kind: Kind
    text: str
    status: str
    owner_id: str | None
    owner_name: str | None

    due_date: str | None
    overdue: bool
    days_overdue: int | None

    meeting_id: str | None
    meeting_title: str | None

    evidence_id: str | None
    verification_status: str | None
    start_ms: int | None

    created_at: str | None = None


@dataclass
class PersonCommitments:
    """One person's full history, with a completion rate."""

    person_id: str
    person_name: str | None
    person_email: str | None

    total: int = 0
    open: int = 0
    completed: int = 0
    overdue: int = 0
    # Completed / (completed + settled-but-not-completed). None when the person
    # has nothing settled yet — a rate over zero closed items is not a rate,
    # and 0% would read as a damning finding about someone with no history.
    completion_rate: float | None = None
    items: list[CommitmentView] = field(default_factory=list)


def _is_open(kind: Kind, status: str | None) -> bool:
    statuses = OPEN_COMMITMENT_STATUSES if kind == "commitment" else OPEN_ACTION_STATUSES
    return (status or "") in statuses


def _is_completed(kind: Kind, status: str | None) -> bool:
    statuses = COMPLETED_COMMITMENT_STATUSES if kind == "commitment" else COMPLETED_ACTION_STATUSES
    return (status or "") in statuses


def compute_overdue(
    kind: Kind, status: str | None, due_date: datetime | None, *, now: datetime | None = None
) -> tuple[bool, int | None]:
    """Overdue when the deadline has passed and the item is still open.

    Returns ``(overdue, days_overdue)``. An item with no deadline is never
    overdue, and a settled item is never overdue however late it was.
    """
    if due_date is None or not _is_open(kind, status):
        return False, None

    now = now or datetime.now(UTC)
    # Rows written by SQLite come back naive; treat them as UTC rather than
    # letting a comparison raise.
    if due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=UTC)
    if due_date >= now:
        return False, None
    return True, max(0, (now - due_date).days)


def _view(
    row, kind: Kind, *, owner: User | None, meeting: Meeting | None, evidence: Evidence | None, now: datetime | None
) -> CommitmentView:
    status = row.status
    due = row.due_date
    overdue, days = compute_overdue(kind, status, due, now=now)
    return CommitmentView(
        id=row.id,
        kind=kind,
        text=(row.text if kind == "commitment" else row.title) or "",
        status=status or "",
        owner_id=owner.id if owner else None,
        owner_name=owner.full_name if owner else None,
        due_date=due.isoformat() if due else None,
        overdue=overdue,
        days_overdue=days,
        meeting_id=row.meeting_id,
        meeting_title=meeting.title if meeting else None,
        evidence_id=evidence.id if evidence else None,
        verification_status=evidence.verification_status if evidence else None,
        start_ms=evidence.start_ms if evidence else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def _lookup_tables(db: Session, org_id: str | None) -> tuple[dict, dict]:
    users = {user.id: user for user in db.query(User).filter(*([User.org_id == org_id] if org_id else [])).all()}
    meetings = {
        meeting.id: meeting
        for meeting in db.query(Meeting).filter(*([Meeting.org_id == org_id] if org_id else [])).all()
    }
    return users, meetings


def list_commitments(
    db: Session,
    *,
    org_id: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,
    overdue: bool | None = None,
    kinds: tuple[Kind, ...] = ("commitment", "action_item"),
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
) -> list[CommitmentView]:
    """Obligations across the org, filtered and with overdue computed.

    ``overdue=True`` returns only items past a real deadline and still open;
    ``overdue=False`` returns only those that are not.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    users, meetings = _lookup_tables(db, org_id)
    results: list[CommitmentView] = []

    if "commitment" in kinds:
        query = db.query(Commitment)
        if org_id:
            query = query.filter(Commitment.org_id == org_id)
        if owner_id:
            query = query.filter(Commitment.committer_id == owner_id)
        if status:
            query = query.filter(Commitment.status == status)
        for row in query.all():
            results.append(
                _view(
                    row,
                    "commitment",
                    owner=users.get(row.committer_id),
                    meeting=meetings.get(row.meeting_id),
                    evidence=row.evidence,
                    now=now,
                )
            )

    if "action_item" in kinds:
        query = db.query(ActionItem)
        if org_id:
            query = query.filter(ActionItem.org_id == org_id)
        if owner_id:
            query = query.filter(ActionItem.assignee_id == owner_id)
        if status:
            query = query.filter(ActionItem.status == status)
        for row in query.all():
            results.append(
                _view(
                    row,
                    "action_item",
                    owner=users.get(row.assignee_id),
                    meeting=meetings.get(row.meeting_id),
                    evidence=row.evidence,
                    now=now,
                )
            )

    if overdue is not None:
        results = [item for item in results if item.overdue is overdue]

    # Most overdue first, then soonest due, then undated. A rollup is read
    # top-down and the thing most at risk belongs at the top.
    results.sort(
        key=lambda item: (
            0 if item.overdue else 1,
            -(item.days_overdue or 0),
            item.due_date or "9999",
        )
    )
    return results[:limit]


def person_commitments(
    db: Session,
    person_id: str,
    *,
    now: datetime | None = None,
) -> PersonCommitments:
    """One person's full obligation history and completion rate."""
    person = db.query(User).filter_by(id=person_id).first()
    if person is None:
        raise ValueError(f"Person {person_id} not found")

    items = list_commitments(db, org_id=person.org_id, owner_id=person_id, limit=MAX_LIMIT, now=now)

    result = PersonCommitments(
        person_id=person.id,
        person_name=person.full_name,
        person_email=person.email,
        items=items,
        total=len(items),
    )
    result.open = sum(1 for item in items if _is_open(item.kind, item.status))
    result.completed = sum(1 for item in items if _is_completed(item.kind, item.status))
    result.overdue = sum(1 for item in items if item.overdue)

    # Rate over *settled* items only. Counting still-open work as a failure
    # would punish someone for having a deadline that has not arrived.
    settled = [item for item in items if not _is_open(item.kind, item.status)]
    result.completion_rate = round(result.completed / len(settled), 4) if settled else None
    return result
