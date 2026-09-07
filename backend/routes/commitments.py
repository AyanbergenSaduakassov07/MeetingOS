"""Commitment rollups across the org, and per-person history.

Read-only query surface over data that already exists. Overdue is computed
server-side so every client, report and alert agrees on who is late.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import Organization, User, get_db
from ..meetings.commitments import list_commitments, person_commitments

logger = logging.getLogger(__name__)

router = APIRouter(tags=["commitments"])


class CommitmentOut(BaseModel):
    """One obligation with its provenance and computed state."""

    id: str
    kind: str
    text: str
    status: str
    owner_id: str | None = None
    owner_name: str | None = None
    due_date: str | None = None
    overdue: bool = False
    days_overdue: int | None = None
    meeting_id: str | None = None
    meeting_title: str | None = None
    evidence_id: str | None = None
    verification_status: str | None = None
    start_ms: int | None = None
    created_at: str | None = None


class CommitmentListOut(BaseModel):
    items: list[CommitmentOut] = []
    total: int = 0
    overdue_count: int = 0


class PersonCommitmentsOut(BaseModel):
    person_id: str
    person_name: str | None = None
    person_email: str | None = None
    total: int = 0
    open: int = 0
    completed: int = 0
    overdue: int = 0
    # Null when nothing has settled yet — a rate over zero closed items is not
    # a rate, and 0% would read as a finding about someone with no history.
    completion_rate: float | None = None
    items: list[CommitmentOut] = []


def _resolve_org_id(db: Session, org_id: str | None) -> str | None:
    if org_id:
        return org_id
    orgs = db.query(Organization).limit(2).all()
    return orgs[0].id if len(orgs) == 1 else None


@router.get("/api/commitments", response_model=CommitmentListOut)
async def get_commitments(
    owner: str | None = Query(None, description="Filter to one person's obligations."),
    status_filter: str | None = Query(None, alias="status", description="Exact status match."),
    overdue: bool | None = Query(None, description="true = only overdue; false = only not."),
    kind: str | None = Query(None, description="'commitment' or 'action_item'."),
    org_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> CommitmentListOut:
    """Commitment and action-item rollups across the whole org.

    Overdue means a deadline in the past and a status still open. Items with no
    deadline are never overdue — inventing one to call someone late would
    manufacture the accusation.
    """
    kinds = ("commitment", "action_item") if kind is None else (kind,)
    if kind is not None and kind not in ("commitment", "action_item"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="kind must be 'commitment' or 'action_item'.",
        )

    items = list_commitments(
        db,
        org_id=_resolve_org_id(db, org_id),
        owner_id=owner,
        status=status_filter,
        overdue=overdue,
        kinds=kinds,  # type: ignore[arg-type]
        limit=limit,
    )
    return CommitmentListOut(
        items=[CommitmentOut(**vars(item)) for item in items],
        total=len(items),
        overdue_count=sum(1 for item in items if item.overdue),
    )


@router.get("/api/people/{person_id}/commitments", response_model=PersonCommitmentsOut)
async def get_person_commitments(person_id: str, db: Session = Depends(get_db)) -> PersonCommitmentsOut:
    """One person's full obligation history, with a completion rate."""
    if db.query(User).filter_by(id=person_id).first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Person {person_id} not found")
    result = person_commitments(db, person_id)
    return PersonCommitmentsOut(
        person_id=result.person_id,
        person_name=result.person_name,
        person_email=result.person_email,
        total=result.total,
        open=result.open,
        completed=result.completed,
        overdue=result.overdue,
        completion_rate=result.completion_rate,
        items=[CommitmentOut(**vars(item)) for item in result.items],
    )
