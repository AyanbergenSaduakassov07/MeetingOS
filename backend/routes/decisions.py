"""Decision timeline and cross-meeting diffs.

Separate router from ``meetings`` because these are questions about a decision
across its whole life, not about one meeting. ``/api/meetings/{id}/...`` would
have to pick an arbitrary meeting from the chain to hang them off.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import Decision, get_db
from ..meetings.changes import diff_since, summarise_changes
from ..meetings.timeline import build_timeline
from ..memory.comparator import find_conflicts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


class TimelineEntryOut(BaseModel):
    """One point in a decision's life."""

    decision_id: str
    meeting_id: str | None = None
    meeting_title: str | None = None
    occurred_at: str | None = None
    title: str
    status: str
    event_type: str
    evidence_id: str | None = None
    start_ms: int | None = None
    is_current: bool


class TimelineOut(BaseModel):
    decision_id: str
    entries: list[TimelineEntryOut] = []
    length: int = 0


@router.get("/{decision_id}/timeline", response_model=TimelineOut)
async def get_decision_timeline(decision_id: str, db: Session = Depends(get_db)) -> TimelineOut:
    """The linked chain this decision belongs to, oldest first.

    A decision nobody revisited returns a single entry — "decided once" is an
    answer, not an empty result.
    """
    if db.query(Decision).filter_by(id=decision_id).first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision {decision_id} not found")
    entries = build_timeline(db, decision_id)
    return TimelineOut(
        decision_id=decision_id,
        entries=[TimelineEntryOut(**vars(entry)) for entry in entries],
        length=len(entries),
    )


class FieldChangeOut(BaseModel):
    """One field that differs between two points in the chain."""

    field: str
    old_value: str | None = None
    new_value: str | None = None
    changed_in_meeting_id: str | None = None
    changed_in_meeting_title: str | None = None
    evidence_id: str | None = None
    start_ms: int | None = None


class ChangesOut(BaseModel):
    """A structured, deterministic diff. `summary` is decoration."""

    decision_id: str
    since_meeting_id: str
    since_meeting_title: str | None = None
    current_meeting_id: str | None = None
    current_meeting_title: str | None = None
    changes: list[FieldChangeOut] = []
    changed: bool = False
    # True when `since` names a meeting outside this decision's chain. The
    # caller asked about a point this decision never passed through.
    out_of_chain: bool = False
    # Prose rendering of `changes`, generated from the computed diff. Null when
    # the model is unavailable — the diff above is the answer either way.
    summary: str | None = None


@router.get("/{decision_id}/changes", response_model=ChangesOut)
async def get_decision_changes(
    decision_id: str,
    since: str = Query(..., description="Meeting id to diff from."),
    summarise: bool = Query(False, description="Also return a prose rendering of the diff."),
    db: Session = Depends(get_db),
) -> ChangesOut:
    """Field-level changes to this decision since a given meeting.

    The diff is computed from stored data by comparison. `summarise=true` adds
    a prose paragraph generated *from* that diff; it never replaces it, and a
    model failure leaves the structured result intact.
    """
    if db.query(Decision).filter_by(id=decision_id).first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision {decision_id} not found")

    try:
        result = diff_since(db, decision_id, since)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    summary = await summarise_changes(result) if summarise else None
    return ChangesOut(
        decision_id=result.decision_id,
        since_meeting_id=result.since_meeting_id,
        since_meeting_title=result.since_meeting_title,
        current_meeting_id=result.current_meeting_id,
        current_meeting_title=result.current_meeting_title,
        changes=[FieldChangeOut(**vars(change)) for change in result.changes],
        changed=result.changed,
        out_of_chain=result.out_of_chain,
        summary=summary,
    )


class ConflictOut(BaseModel):
    """One classified relationship between two claims, with both citations."""

    relationship: str
    reasoning: str
    confidence: float
    is_conflict: bool

    prior_decision_id: str
    prior_evidence_id: str | None = None
    prior_meeting_id: str | None = None
    prior_meeting_title: str | None = None
    prior_claim: str
    prior_start_ms: int | None = None

    new_decision_id: str
    new_evidence_id: str | None = None
    new_meeting_id: str | None = None
    new_meeting_title: str | None = None
    new_claim: str
    new_start_ms: int | None = None

    # True when a conflicting verdict could not cite both sides and was
    # downgraded. `downgraded_from` keeps the original for audit.
    low_confidence: bool = False
    downgraded_from: str | None = None


class ConflictsOut(BaseModel):
    decision_id: str
    conflicts: list[ConflictOut] = []
    # Only those classified contradicted or reversed.
    conflicting: list[ConflictOut] = []
    compared: int = 0
    errors: list[str] = []


@router.get("/{decision_id}/conflicts", response_model=ConflictsOut)
async def get_decision_conflicts(decision_id: str, db: Session = Depends(get_db)) -> ConflictsOut:
    """How this decision stands against each earlier link in its chain.

    Every entry carries both claims and both Evidence ids, so a reported
    contradiction can be heard in the recording on both sides. A conflicting
    verdict that could not cite both is downgraded and marked `low_confidence`
    rather than shown as a conflict.
    """
    if db.query(Decision).filter_by(id=decision_id).first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision {decision_id} not found")

    report = await find_conflicts(decision_id, db=db)

    def out(conflict) -> ConflictOut:
        return ConflictOut(is_conflict=conflict.is_conflict, **vars(conflict))

    return ConflictsOut(
        decision_id=decision_id,
        conflicts=[out(c) for c in report.conflicts],
        conflicting=[out(c) for c in report.conflicting],
        compared=report.compared,
        errors=report.errors,
    )
