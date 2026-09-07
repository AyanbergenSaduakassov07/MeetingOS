"""Link decisions across meetings, and walk the resulting chain.

``DecisionEvent`` has been in the domain model since the first schema and
nothing ever wrote to it. Without it, a board that revisits the same question in
January, March and June has three unrelated Decision rows and no way to ask
what actually happened to that question — which is most of the value of keeping
minutes at all.

How a link is made
------------------
When a meeting's decisions are extracted, each one is matched against decisions
from *earlier* meetings in the same org using the Part 2 corpus retrieval. If a
prior decision scores above ``LINK_THRESHOLD``, the new decision is recorded as
succeeding it: ``supersedes_id`` gives a directly walkable chain, and a
``DecisionEvent`` of type ``revisited`` is appended to the prior decision's
trail so the audit history says which meeting reopened it.

The chain is linear on purpose. A decision revisited twice produces
January <- March <- June, not a tree: "what happened to this question" has one
answer per point in time, and a branching structure would make
``/changes?since=`` ambiguous.

Untrusted input
---------------
This step processes transcript-derived text, and it is treated exactly as
``intelligence.py`` treats it.

**There is no model call anywhere in this module.** Matching is cosine
similarity and BM25 over stored records — arithmetic, not judgement. That is
the strongest available answer to "can transcript content influence which
records get linked": there is no instruction channel to influence, because
nothing here is instructed. A transcript can move its own similarity score by
containing particular words, which is the intended mechanism and the only one.

The remaining controls are structural:

- Candidates are restricted in SQL to the same ``org_id`` and to meetings
  strictly earlier than the one being linked. A transcript cannot widen that
  scope by saying anything.
- ``LINK_THRESHOLD`` is a module constant. No text can lower it.
- A returned record id is checked against the candidate set before it is used
  to load a row, so a value that did not come from this query cannot address
  another org's decision.
- Nothing extracted becomes a callable, an attribute name, or a query fragment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..database import Decision, DecisionEvent, DecisionEventType, Meeting
from ..memory import search_corpus

logger = logging.getLogger(__name__)

# Above this score two decisions are treated as the same subject revisited.
# Deliberately high: wrongly chaining two unrelated decisions produces a
# fabricated history, which is worse than leaving a real chain unlinked. A
# missed link shows up as two separate rows a reader can still see; a false
# link silently rewrites what the board decided.
LINK_THRESHOLD = 0.72

# How many prior candidates to consider per new decision. The best match wins,
# so this only needs to be wide enough that the right one is in the pool.
CANDIDATE_LIMIT = 10


@dataclass
class LinkReport:
    meeting_id: str
    linked: int = 0
    considered: int = 0
    details: list[str] = field(default_factory=list)


@dataclass
class TimelineEntry:
    """One point in a decision's life, oldest first."""

    decision_id: str
    meeting_id: str | None
    meeting_title: str | None
    occurred_at: str | None
    title: str
    status: str
    event_type: str
    evidence_id: str | None
    start_ms: int | None
    is_current: bool


def _earlier_meeting_ids(db: Session, meeting: Meeting) -> set[str]:
    """Meetings in the same org that happened before this one.

    Ordered by ``created_at``, falling back to nothing when it is null — a
    meeting with no timestamp cannot be placed in a sequence, and guessing
    would invent an ordering the data does not support.
    """
    if meeting.created_at is None:
        return set()
    rows = (
        db.query(Meeting.id)
        .filter(
            Meeting.org_id == meeting.org_id,
            Meeting.id != meeting.id,
            Meeting.created_at < meeting.created_at,
        )
        .all()
    )
    return {row[0] for row in rows}


async def link_meeting_decisions(
    meeting_id: str,
    *,
    db: Session | None = None,
    embedder=None,
    threshold: float = LINK_THRESHOLD,
) -> LinkReport:
    """Chain this meeting's decisions onto matching earlier ones.

    Idempotent: a decision that already has ``supersedes_id`` is skipped, so
    re-running after a re-extraction does not double-link or duplicate events.
    """
    from ..database import new_session

    owns = db is None
    db = db or new_session()
    try:
        meeting = db.query(Meeting).filter_by(id=meeting_id).first()
        if meeting is None:
            raise ValueError(f"Meeting {meeting_id} not found")

        report = LinkReport(meeting_id=meeting_id)
        earlier = _earlier_meeting_ids(db, meeting)
        if not earlier:
            logger.debug("Meeting %s is the earliest in its org; nothing to link", meeting_id)
            return report

        for decision in db.query(Decision).filter_by(meeting_id=meeting_id).all():
            if decision.supersedes_id:
                continue
            claim = (decision.title or "").strip()
            if not claim:
                continue
            report.considered += 1

            # Vector only, deliberately. Hybrid retrieval takes the max of the
            # two paths, and BM25 scores a shared common noun highly — "budget"
            # alone was enough to chain a canteen decision onto an Aktau capex
            # one. That is the right trade for *search*, where a spurious hit
            # costs the reader a glance, and the wrong one for *linking*, where
            # it fabricates a decision history. Semantic similarity is the
            # signal that actually means "same subject".
            candidates = await search_corpus(
                claim,
                org_id=meeting.org_id,
                record_types=("decision",),
                limit=CANDIDATE_LIMIT,
                min_score=threshold,
                mode="vector",
                embedder=embedder,
                db=db,
            )

            # Only earlier meetings, and never this decision matching itself.
            prior = next(
                (record for record in candidates if record.meeting_id in earlier and record.record_id != decision.id),
                None,
            )
            if prior is None:
                continue

            # Whitelist check: the id must resolve inside the scope this query
            # was allowed to search, not merely look plausible.
            predecessor = (
                db.query(Decision)
                .filter(
                    Decision.id == prior.record_id,
                    Decision.org_id == meeting.org_id,
                    Decision.meeting_id.in_(earlier),
                )
                .first()
            )
            if predecessor is None:
                logger.warning("Discarded candidate %s: outside the searchable scope", prior.record_id)
                continue

            # Attach to the head of the predecessor's chain, not to whichever
            # link happened to score highest. Linking mid-chain would fork it,
            # and a forked history has no single answer to "what happened to
            # this question", which is the whole point of the timeline.
            predecessor = _chain_head(db, predecessor, exclude=decision.id)
            if predecessor.id == decision.id:
                continue

            decision.supersedes_id = predecessor.id
            db.add(
                DecisionEvent(
                    decision_id=predecessor.id,
                    meeting_id=meeting_id,
                    event_type=DecisionEventType.REVISITED.value,
                    occurred_at=meeting.created_at,
                    notes=f"Revisited in {meeting.title!r}",
                    # The successor id lives in the payload rather than in a
                    # second foreign key: DecisionEvent is append-only history,
                    # and adding a column for one edge would change its shape.
                    payload={
                        "linked_decision_id": decision.id,
                        "match_score": round(prior.score, 4),
                        "match_kind": prior.match,
                    },
                )
            )
            report.linked += 1
            report.details.append(f"{decision.id[:8]} -> {predecessor.id[:8]} (score {prior.score:.3f})")

        db.commit()
        if report.linked:
            logger.info(
                "Linked %d of %d decision(s) in meeting %s to earlier ones",
                report.linked,
                report.considered,
                meeting_id,
            )
        return report
    finally:
        if owns:
            db.close()


def _chain_head(db: Session, decision: Decision, *, exclude: str | None = None) -> Decision:
    """Follow successors forward to the newest link in this chain."""
    seen = {decision.id}
    head = decision
    while True:
        successor = (
            db.query(Decision)
            .filter(
                Decision.supersedes_id == head.id,
                Decision.id.notin_(seen | ({exclude} if exclude else set())),
            )
            .order_by(Decision.created_at)
            .first()
        )
        if successor is None:
            return head
        head = successor
        seen.add(successor.id)


def _chain(db: Session, decision: Decision) -> list[Decision]:
    """The full chain containing ``decision``, oldest first.

    Walks back through ``supersedes_id`` to the root, then forward through
    successors. Guarded against cycles: a corrupted link must not hang a
    request.
    """
    seen: set[str] = set()
    root = decision
    while root.supersedes_id and root.supersedes_id not in seen:
        seen.add(root.id)
        predecessor = db.query(Decision).filter_by(id=root.supersedes_id).first()
        if predecessor is None:
            break
        root = predecessor

    chain = [root]
    seen = {root.id}
    while True:
        successor = (
            db.query(Decision)
            .filter(Decision.supersedes_id == chain[-1].id, Decision.id.notin_(seen))
            .order_by(Decision.created_at)
            .first()
        )
        if successor is None:
            break
        chain.append(successor)
        seen.add(successor.id)
    return chain


def build_timeline(db: Session, decision_id: str) -> list[TimelineEntry]:
    """The linked chain containing ``decision_id``, in order.

    A decision with no links returns a one-entry timeline rather than an empty
    list — "this was decided once and never revisited" is an answer.
    """
    decision = db.query(Decision).filter_by(id=decision_id).first()
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")

    chain = _chain(db, decision)
    current_id = chain[-1].id

    # One query for every event on the chain, rather than one per link.
    events = {
        event.decision_id: event
        for event in db.query(DecisionEvent)
        .filter(DecisionEvent.decision_id.in_([item.id for item in chain]))
        .order_by(DecisionEvent.occurred_at)
        .all()
    }
    titles = {
        row[0]: row[1]
        for row in db.query(Meeting.id, Meeting.title)
        .filter(Meeting.id.in_([item.meeting_id for item in chain if item.meeting_id]))
        .all()
    }

    entries: list[TimelineEntry] = []
    for index, item in enumerate(chain):
        event = events.get(item.id)
        if index == 0:
            event_type = DecisionEventType.PROPOSED.value
        elif item.id == current_id:
            event_type = item.status if item.status else DecisionEventType.AGREED.value
        else:
            event_type = DecisionEventType.REVISITED.value

        entries.append(
            TimelineEntry(
                decision_id=item.id,
                meeting_id=item.meeting_id,
                meeting_title=titles.get(item.meeting_id),
                occurred_at=item.created_at.isoformat() if item.created_at else None,
                title=item.title or "",
                status=item.status or "",
                event_type=event.event_type if event and index > 0 else event_type,
                evidence_id=item.evidence_id,
                start_ms=item.evidence.start_ms if item.evidence else None,
                is_current=item.id == current_id,
            )
        )
    return entries
