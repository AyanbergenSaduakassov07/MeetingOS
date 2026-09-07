"""Commitment rollups, overdue computation, and per-person history.

Acceptance: "show me overdue commitments for the executive team" returns
correct, real results with working citations —
`test_overdue_rollup_for_a_team_is_correct_and_cited`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.database import (
    ActionItem,
    Commitment,
    Evidence,
    Meeting,
    MeetingStatus,
    Organization,
    TranscriptSegment,
    User,
)
from backend.meetings.commitments import (
    compute_overdue,
    list_commitments,
    person_commitments,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def org(db):
    organization = Organization(name="KMG", slug="kmg")
    db.add(organization)
    db.commit()
    return organization


@pytest.fixture
def people(db, org):
    users = {}
    for name, email in (("Dana", "dana@x.io"), ("Priya", "priya@x.io"), ("Sam", "sam@x.io")):
        user = User(org_id=org.id, email=email, full_name=name)
        db.add(user)
        db.flush()
        users[name] = user
    db.commit()
    return users


@pytest.fixture
def meeting(db, org):
    row = Meeting(
        org_id=org.id,
        title="September board",
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
    )
    db.add(row)
    db.commit()
    return row


def add_evidence(db, org, meeting, text: str) -> Evidence:
    segment = TranscriptSegment(meeting_id=meeting.id, sequence=0, start_ms=31000, end_ms=39000, text=text)
    db.add(segment)
    db.flush()
    evidence = Evidence(
        org_id=org.id,
        meeting_id=meeting.id,
        claim_text=text,
        quote=text,
        confidence=0.92,
        verification_status="verified",
    )
    evidence.cite(segment)
    db.add(evidence)
    db.flush()
    return evidence


def add_commitment(db, org, meeting, owner, text, status_value, days_from_now):
    due = NOW + timedelta(days=days_from_now) if days_from_now is not None else None
    db.add(
        Commitment(
            org_id=org.id,
            meeting_id=meeting.id,
            committer_id=owner.id,
            text=text,
            status=status_value,
            due_date=due,
            evidence=add_evidence(db, org, meeting, text),
        )
    )
    db.commit()


def add_action(db, org, meeting, owner, title, status_value, days_from_now):
    due = NOW + timedelta(days=days_from_now) if days_from_now is not None else None
    db.add(
        ActionItem(
            org_id=org.id,
            meeting_id=meeting.id,
            assignee_id=owner.id,
            title=title,
            status=status_value,
            due_date=due,
            evidence=add_evidence(db, org, meeting, title),
        )
    )
    db.commit()


# -- the overdue rule ------------------------------------------------------


@pytest.mark.parametrize(
    "kind,status_value,days,expected",
    [
        ("commitment", "pending", -5, True),  # past deadline, still open
        ("commitment", "pending", 5, False),  # deadline not yet reached
        ("commitment", "kept", -5, False),  # settled, however late
        ("commitment", "broken", -5, False),  # settled
        ("commitment", "pending", None, False),  # no deadline is never overdue
        ("action_item", "open", -5, True),
        ("action_item", "in_progress", -5, True),
        ("action_item", "blocked", -5, True),
        ("action_item", "done", -5, False),
        ("action_item", "cancelled", -5, False),
        ("action_item", "open", None, False),
    ],
)
def test_overdue_rule(kind, status_value, days, expected):
    due = NOW + timedelta(days=days) if days is not None else None
    overdue, _ = compute_overdue(kind, status_value, due, now=NOW)
    assert overdue is expected


def test_days_overdue_is_reported():
    overdue, days = compute_overdue("commitment", "pending", NOW - timedelta(days=12), now=NOW)
    assert overdue is True
    assert days == 12


def test_naive_datetime_from_sqlite_does_not_raise():
    """SQLite returns naive datetimes; comparing them must not blow up."""
    overdue, _ = compute_overdue("commitment", "pending", datetime(2026, 1, 1), now=NOW)
    assert overdue is True


# -- acceptance ------------------------------------------------------------


def test_overdue_rollup_for_a_team_is_correct_and_cited(db, org, people, meeting):
    """Acceptance: overdue commitments across the org, each with a citation."""
    add_commitment(db, org, meeting, people["Dana"], "I will chase the sponsor invoice", "pending", -14)
    add_commitment(db, org, meeting, people["Priya"], "I will circulate the drawings", "pending", -3)
    add_commitment(db, org, meeting, people["Sam"], "I will book the venue", "pending", 10)
    add_commitment(db, org, meeting, people["Dana"], "I will file the return", "kept", -30)
    add_action(db, org, meeting, people["Priya"], "Place the parts order", "open", -7)

    overdue = list_commitments(db, org_id=org.id, overdue=True, now=NOW)

    texts = {item.text for item in overdue}
    assert texts == {
        "I will chase the sponsor invoice",
        "I will circulate the drawings",
        "Place the parts order",
    }
    assert "I will book the venue" not in texts, "a future deadline was called overdue"
    assert "I will file the return" not in texts, "a settled item was called overdue"

    # Working citations on every row.
    for item in overdue:
        assert item.evidence_id, f"{item.text!r} has no citation"
        assert db.query(Evidence).filter_by(id=item.evidence_id).one() is not None
        assert item.start_ms == 31000
        assert item.verification_status == "verified"
        assert item.meeting_title == "September board"
        assert item.owner_name

    # Most overdue first.
    assert [item.days_overdue for item in overdue] == [14, 7, 3]


def test_overdue_false_returns_only_the_rest(db, org, people, meeting):
    add_commitment(db, org, meeting, people["Dana"], "Late one", "pending", -5)
    add_commitment(db, org, meeting, people["Sam"], "Future one", "pending", 5)

    not_overdue = list_commitments(db, org_id=org.id, overdue=False, now=NOW)
    assert {item.text for item in not_overdue} == {"Future one"}


# -- filters ---------------------------------------------------------------


def test_filter_by_owner(db, org, people, meeting):
    add_commitment(db, org, meeting, people["Dana"], "Dana's promise", "pending", -1)
    add_commitment(db, org, meeting, people["Priya"], "Priya's promise", "pending", -1)

    items = list_commitments(db, org_id=org.id, owner_id=people["Dana"].id, now=NOW)
    assert {item.text for item in items} == {"Dana's promise"}


def test_filter_by_status(db, org, people, meeting):
    add_commitment(db, org, meeting, people["Dana"], "Kept one", "kept", -1)
    add_commitment(db, org, meeting, people["Dana"], "Pending one", "pending", -1)

    items = list_commitments(db, org_id=org.id, status="kept", now=NOW)
    assert {item.text for item in items} == {"Kept one"}


def test_filter_by_kind_keeps_promises_and_tasks_apart(db, org, people, meeting):
    add_commitment(db, org, meeting, people["Dana"], "A promise", "pending", -1)
    add_action(db, org, meeting, people["Dana"], "A task", "open", -1)

    promises = list_commitments(db, org_id=org.id, kinds=("commitment",), now=NOW)
    tasks = list_commitments(db, org_id=org.id, kinds=("action_item",), now=NOW)
    assert {i.text for i in promises} == {"A promise"}
    assert {i.text for i in tasks} == {"A task"}
    assert promises[0].kind == "commitment" and tasks[0].kind == "action_item"


def test_another_orgs_commitments_are_not_returned(db, org, people, meeting):
    other = Organization(name="Other", slug="other")
    db.add(other)
    db.flush()
    their_meeting = Meeting(org_id=other.id, title="Theirs", status="completed", source="upload")
    db.add(their_meeting)
    db.flush()
    their_user = User(org_id=other.id, email="x@other.io", full_name="X")
    db.add(their_user)
    db.flush()
    add_commitment(db, other, their_meeting, their_user, "Their secret promise", "pending", -5)
    add_commitment(db, org, meeting, people["Dana"], "Our promise", "pending", -5)

    items = list_commitments(db, org_id=org.id, now=NOW)
    assert {i.text for i in items} == {"Our promise"}


# -- per-person view -------------------------------------------------------


def test_person_history_and_completion_rate(db, org, people, meeting):
    dana = people["Dana"]
    add_commitment(db, org, meeting, dana, "Kept one", "kept", -30)
    add_commitment(db, org, meeting, dana, "Kept two", "kept", -20)
    add_commitment(db, org, meeting, dana, "Broken one", "broken", -10)
    add_commitment(db, org, meeting, dana, "Still open", "pending", -2)

    result = person_commitments(db, dana.id, now=NOW)

    assert result.person_name == "Dana"
    assert result.total == 4
    assert result.open == 1
    assert result.completed == 2
    assert result.overdue == 1
    # 2 kept of 3 settled. The still-open item is not counted as a failure.
    assert result.completion_rate == pytest.approx(2 / 3, abs=1e-4)


def test_completion_rate_is_none_with_no_settled_items(db, org, people, meeting):
    """0% would read as a finding about someone who has simply not finished yet."""
    add_commitment(db, org, meeting, people["Sam"], "Not due yet", "pending", 10)
    result = person_commitments(db, people["Sam"].id, now=NOW)
    assert result.completion_rate is None
    assert result.total == 1


def test_person_with_no_history_is_not_an_error(db, org, people):
    result = person_commitments(db, people["Sam"].id, now=NOW)
    assert result.total == 0
    assert result.completion_rate is None


def test_unknown_person_raises(db, org):
    with pytest.raises(ValueError, match="not found"):
        person_commitments(db, "nope")


# -- endpoints -------------------------------------------------------------


def test_commitments_endpoint_filters_overdue(data_dir, db, org, people, meeting):
    add_commitment(db, org, meeting, people["Dana"], "Late promise", "pending", -9)
    add_commitment(db, org, meeting, people["Sam"], "Future promise", "pending", 9)

    with TestClient(create_app()) as client:
        response = client.get("/api/commitments", params={"overdue": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["overdue_count"] == 1
    item = body["items"][0]
    assert item["text"] == "Late promise"
    assert item["owner_name"] == "Dana"
    assert item["evidence_id"] and item["start_ms"] == 31000
    assert item["days_overdue"] >= 1


def test_commitments_endpoint_filters_by_owner(data_dir, db, org, people, meeting):
    add_commitment(db, org, meeting, people["Dana"], "Dana's", "pending", -1)
    add_commitment(db, org, meeting, people["Priya"], "Priya's", "pending", -1)

    with TestClient(create_app()) as client:
        body = client.get("/api/commitments", params={"owner": people["Dana"].id}).json()

    assert {i["text"] for i in body["items"]} == {"Dana's"}


def test_commitments_endpoint_rejects_an_unknown_kind(data_dir, db, org):
    with TestClient(create_app()) as client:
        assert client.get("/api/commitments", params={"kind": "wishes"}).status_code == 422


def test_person_endpoint_returns_history_with_citations(data_dir, db, org, people, meeting):
    dana = people["Dana"]
    add_commitment(db, org, meeting, dana, "Kept one", "kept", -30)
    add_commitment(db, org, meeting, dana, "Still open", "pending", -2)

    with TestClient(create_app()) as client:
        response = client.get(f"/api/people/{dana.id}/commitments")

    assert response.status_code == 200
    body = response.json()
    assert body["person_name"] == "Dana"
    assert body["total"] == 2
    assert body["overdue"] == 1
    assert body["completion_rate"] == 1.0
    for item in body["items"]:
        assert item["evidence_id"], "history entry without a citation"


def test_person_endpoint_404s_for_unknown_person(data_dir):
    with TestClient(create_app()) as client:
        assert client.get("/api/people/nope/commitments").status_code == 404
