"""Executive command centre: aggregate stats over the whole org.

Every number here is computed from the same queries the drill-through pages
use, and every number ships with the query params that reproduce it. That is
the design constraint: a dashboard figure a reader cannot get behind is a
number they have to take on faith, and this product exists to stop people
taking claims on faith.

So each stat carries a ``link`` — the path and filter that returns exactly the
rows counted. If the count and the list ever disagree, the bug is visible
rather than silent.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import (
    Commitment,
    Decision,
    Evidence,
    Meeting,
    Organization,
    Risk,
    User,
    get_db,
)
from ..meetings.commitments import list_commitments

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

DEFAULT_PERIOD_DAYS = 90

# Decision statuses grouped for the headline counters.
APPROVED = frozenset({"agreed"})
PENDING = frozenset({"proposed", "deferred"})
REVERSED = frozenset({"reversed", "superseded"})

# Risk severities worth surfacing on a board dashboard.
TOP_RISK_SEVERITIES = ("critical", "high")

MAX_PEOPLE = 5
MAX_RISKS = 5


class StatLink(BaseModel):
    """Where to go to see the rows behind a number.

    ``path`` plus ``query`` must return exactly what was counted. This is what
    makes a stat auditable rather than decorative.
    """

    path: str
    query: dict[str, str] = {}


class Stat(BaseModel):
    label: str
    value: int
    link: StatLink
    tone: str = "neutral"  # neutral | good | warn | destructive


def _toned(label: str, value: int, tone: str, link: StatLink) -> Stat:
    """A stat whose colour reflects whether there is anything to react to.

    Zero is always neutral. "Reversed: 0" painted in alarm-red trains a reader
    to ignore the colour, which costs the one time it is 3.
    """
    return Stat(label=label, value=value, tone=tone if value else "neutral", link=link)


class PersonActivity(BaseModel):
    person_id: str
    name: str | None = None
    meetings: int = 0
    decisions: int = 0
    commitments: int = 0
    total: int = 0
    link: StatLink


class RiskSummary(BaseModel):
    id: str
    title: str
    severity: str | None = None
    meeting_id: str | None = None
    meeting_title: str | None = None
    evidence_id: str | None = None
    start_ms: int | None = None
    verification_status: str | None = None


class ExtractionQuality(BaseModel):
    """Aggregate confidence across everything extracted in the period.

    Surfaces what the verifier already computed. No new scoring — the numbers
    are counts of existing verification statuses, and ``low_confidence`` plus
    ``unsupported`` are reported rather than folded into a single score that
    would hide them.
    """

    total_items: int = 0
    verified: int = 0
    low_confidence: int = 0
    unsupported: int = 0
    unverified: int = 0
    # verified / total. None when nothing has been extracted — a rate over zero
    # items is not a rate.
    verified_rate: float | None = None
    mean_confidence: float | None = None
    # True when the verifier has not run on some items, so the picture is
    # incomplete rather than clean.
    has_unverified: bool = False
    link: StatLink


class DashboardOut(BaseModel):
    org_id: str
    period_days: int
    period_start: str
    meetings_in_period: int
    decisions_approved: Stat
    decisions_pending: Stat
    decisions_reversed: Stat
    overdue_commitments: Stat
    open_risks: Stat
    top_risks: list[RiskSummary] = []
    most_active_people: list[PersonActivity] = []
    extraction_quality: ExtractionQuality


def _resolve_org(db: Session, org_id: str | None) -> Organization:
    if org_id:
        organization = db.query(Organization).filter_by(id=org_id).first()
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {org_id} not found")
        return organization
    organizations = db.query(Organization).limit(2).all()
    if len(organizations) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pass org_id explicitly: zero or multiple organizations exist.",
        )
    return organizations[0]


@router.get("", response_model=DashboardOut)
async def get_dashboard(
    org_id: str | None = Query(None),
    period_days: int = Query(DEFAULT_PERIOD_DAYS, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> DashboardOut:
    """Aggregate stats for the executive dashboard.

    Every counter is paired with the link that reproduces it, so no figure is
    a dead end.
    """
    organization = _resolve_org(db, org_id)
    cutoff = datetime.now(UTC) - timedelta(days=period_days)

    meetings = db.query(Meeting).filter(Meeting.org_id == organization.id, Meeting.created_at >= cutoff).all()
    meeting_ids = [m.id for m in meetings]
    meeting_titles = {m.id: m.title for m in meetings}

    decisions = db.query(Decision).filter(Decision.meeting_id.in_(meeting_ids)).all() if meeting_ids else []

    def decision_stat(label: str, statuses: frozenset[str], tone: str) -> Stat:
        return _toned(
            label,
            sum(1 for d in decisions if (d.status or "") in statuses),
            tone,
            StatLink(
                path="/decisions",
                query={"status": ",".join(sorted(statuses)), "period_days": str(period_days)},
            ),
        )

    overdue = list_commitments(db, org_id=organization.id, overdue=True, limit=500)

    risks = db.query(Risk).filter(Risk.meeting_id.in_(meeting_ids)).all() if meeting_ids else []
    open_risks = [r for r in risks if (r.status or "open") not in ("closed", "mitigated")]
    ranked_risks = sorted(
        open_risks,
        key=lambda r: (
            TOP_RISK_SEVERITIES.index(r.severity) if r.severity in TOP_RISK_SEVERITIES else 99,
            r.title or "",
        ),
    )

    top_risks = []
    for risk in ranked_risks[:MAX_RISKS]:
        evidence = risk.evidence
        top_risks.append(
            RiskSummary(
                id=risk.id,
                title=risk.title or "",
                severity=risk.severity,
                meeting_id=risk.meeting_id,
                meeting_title=meeting_titles.get(risk.meeting_id),
                evidence_id=evidence.id if evidence else None,
                start_ms=evidence.start_ms if evidence else None,
                verification_status=risk.verification_status,
            )
        )

    # -- most active people ------------------------------------------------
    people = {u.id: u for u in db.query(User).filter(User.org_id == organization.id).all()}
    activity: dict[str, dict[str, int]] = {pid: {"meetings": 0, "decisions": 0, "commitments": 0} for pid in people}

    # Meetings attended, inferred from speaker rows resolved to a user.
    from ..database import Speaker

    if meeting_ids:
        for speaker in db.query(Speaker).filter(Speaker.meeting_id.in_(meeting_ids)).all():
            if speaker.user_id in activity:
                activity[speaker.user_id]["meetings"] += 1
        for decision in decisions:
            if decision.decision_maker_id in activity:
                activity[decision.decision_maker_id]["decisions"] += 1
        for commitment in db.query(Commitment).filter(Commitment.meeting_id.in_(meeting_ids)).all():
            if commitment.committer_id in activity:
                activity[commitment.committer_id]["commitments"] += 1

    most_active = sorted(
        (
            PersonActivity(
                person_id=pid,
                name=people[pid].full_name or people[pid].email,
                meetings=counts["meetings"],
                decisions=counts["decisions"],
                commitments=counts["commitments"],
                total=sum(counts.values()),
                link=StatLink(path=f"/people/{pid}/commitments"),
            )
            for pid, counts in activity.items()
        ),
        key=lambda person: person.total,
        reverse=True,
    )
    most_active = [person for person in most_active if person.total > 0][:MAX_PEOPLE]

    # -- extraction quality ------------------------------------------------
    evidence_rows = db.query(Evidence).filter(Evidence.meeting_id.in_(meeting_ids)).all() if meeting_ids else []
    counts = {"verified": 0, "low_confidence": 0, "unsupported": 0, "unverified": 0}
    confidences = []
    for row in evidence_rows:
        counts[row.verification_status] = counts.get(row.verification_status, 0) + 1
        if row.confidence is not None:
            confidences.append(row.confidence)

    total_items = len(evidence_rows)
    quality = ExtractionQuality(
        total_items=total_items,
        verified=counts.get("verified", 0),
        low_confidence=counts.get("low_confidence", 0),
        unsupported=counts.get("unsupported", 0),
        unverified=counts.get("unverified", 0),
        verified_rate=(round(counts.get("verified", 0) / total_items, 4) if total_items else None),
        mean_confidence=(round(sum(confidences) / len(confidences), 4) if confidences else None),
        has_unverified=counts.get("unverified", 0) > 0,
        link=StatLink(path="/quality", query={"period_days": str(period_days)}),
    )

    return DashboardOut(
        org_id=organization.id,
        period_days=period_days,
        period_start=cutoff.isoformat(),
        meetings_in_period=len(meetings),
        decisions_approved=decision_stat("Approved", APPROVED, "good"),
        decisions_pending=decision_stat("Pending", PENDING, "warn"),
        decisions_reversed=decision_stat("Reversed", REVERSED, "destructive"),
        overdue_commitments=_toned(
            "Overdue commitments", len(overdue), "destructive",
            StatLink(path="/commitments", query={"overdue": "true"}),
        ),
        open_risks=_toned(
            "Open risks", len(open_risks), "warn",
            StatLink(path="/risks", query={"period_days": str(period_days)}),
        ),
        top_risks=top_risks,
        most_active_people=most_active,
        extraction_quality=quality,
    )
