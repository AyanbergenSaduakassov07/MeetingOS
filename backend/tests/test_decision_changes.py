"""Field-level diffs across a decision chain.

Acceptance: asking for changes since a specific meeting returns accurate
field-level diffs matching what is actually in the database —
`test_changes_match_what_is_in_the_database`.

The load-bearing property is determinism. Every assertion here compares the
diff against rows the test itself wrote, so a diff that drifted from the data
fails rather than reading plausibly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.ai.base import Completion, ProviderConfig, Usage
from backend.app import create_app
from backend.database import (
    ActionItem,
    Decision,
    Evidence,
    Meeting,
    MeetingStatus,
    Organization,
    Risk,
    TranscriptSegment,
    User,
)
from backend.meetings.changes import diff_since, parse_amount, summarise_changes


@pytest.fixture
def org(db):
    organization = Organization(name="KMG", slug="kmg")
    db.add(organization)
    db.commit()
    return organization


def add_meeting(db, org, title, days_ago) -> Meeting:
    meeting = Meeting(
        org_id=org.id,
        title=title,
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(meeting)
    db.commit()
    return meeting


def add_decision(db, org, meeting, title, status_value, *, supersedes=None, rationale=None):
    segment = TranscriptSegment(meeting_id=meeting.id, sequence=0, start_ms=12000, end_ms=20000, text=title)
    db.add(segment)
    db.flush()
    evidence = Evidence(
        org_id=org.id,
        meeting_id=meeting.id,
        claim_text=title,
        quote=title,
        confidence=0.9,
        verification_status="verified",
    )
    evidence.cite(segment)
    db.add(evidence)
    decision = Decision(
        org_id=org.id,
        meeting_id=meeting.id,
        title=title,
        status=status_value,
        rationale=rationale,
        evidence=evidence,
        supersedes_id=supersedes.id if supersedes else None,
    )
    db.add(decision)
    db.commit()
    return decision


@pytest.fixture
def chain(db, org):
    """January approves; March defers, changes owner, date and amount."""
    january = add_meeting(db, org, "January board", 90)
    march = add_meeting(db, org, "March board", 30)

    dana = User(org_id=org.id, email="dana@example.org", full_name="Dana")
    priya = User(org_id=org.id, email="priya@example.org", full_name="Priya")
    db.add_all([dana, priya])
    db.flush()

    first = add_decision(
        db,
        org,
        january,
        "Approve the Aktau expansion capex of 500,000",
        "agreed",
        rationale="Board is satisfied with the survey",
    )
    db.add(
        ActionItem(
            org_id=org.id,
            meeting_id=january.id,
            title="Place the order",
            assignee_id=dana.id,
            description="Due as stated: before Friday",
        )
    )
    db.add(Risk(org_id=org.id, meeting_id=january.id, title="Funding gap", severity="medium"))

    second = add_decision(
        db,
        org,
        march,
        "Approve the Aktau expansion capex of 750,000",
        "deferred",
        supersedes=first,
        rationale="Costs rose after the dredging survey",
    )
    db.add(
        ActionItem(
            org_id=org.id,
            meeting_id=march.id,
            title="Place the order",
            assignee_id=priya.id,
            description="Due as stated: end of April",
        )
    )
    db.add(Risk(org_id=org.id, meeting_id=march.id, title="Funding gap", severity="high"))
    db.commit()

    return {
        "january": january,
        "march": march,
        "first": first,
        "second": second,
        "dana": dana,
        "priya": priya,
    }


def field_map(result):
    return {change.field: (change.old_value, change.new_value) for change in result.changes}


# -- acceptance ------------------------------------------------------------


def test_changes_match_what_is_in_the_database(db, org, chain):
    """Acceptance: every reported change is checkable against stored rows."""
    result = diff_since(db, chain["second"].id, chain["january"].id)

    assert result.changed
    assert result.out_of_chain is False
    changes = field_map(result)

    assert changes["status"] == ("agreed", "deferred")
    assert changes["owner"] == (chain["dana"].id, chain["priya"].id)
    assert changes["target_date"] == ("before Friday", "end of April")
    assert changes["risk_severity"] == ("medium", "high")
    assert changes["amount"] == ("500000", "750000")

    # Cross-check each reported value against the database itself.
    assert db.query(Decision).filter_by(id=chain["first"].id).one().status == "agreed"
    assert db.query(Decision).filter_by(id=chain["second"].id).one().status == "deferred"

    # Every change says which meeting introduced it, and cites evidence.
    for change in result.changes:
        assert change.changed_in_meeting_id == chain["march"].id
        assert change.changed_in_meeting_title == "March board"
        assert change.evidence_id
        assert change.start_ms == 12000


def test_diff_is_deterministic_across_repeated_calls(db, org, chain):
    """Same question, same answer — the point of not generating it."""
    runs = [field_map(diff_since(db, chain["second"].id, chain["january"].id)) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


# -- edges -----------------------------------------------------------------


def test_no_changes_when_nothing_moved(db, org):
    january = add_meeting(db, org, "January board", 90)
    march = add_meeting(db, org, "March board", 30)
    first = add_decision(db, org, january, "Approve the plan", "agreed")
    add_decision(db, org, march, "Approve the plan", "agreed", supersedes=first)

    result = diff_since(db, first.id, january.id)
    assert result.changed is False
    assert result.changes == []


def test_since_a_meeting_outside_the_chain_is_reported_not_guessed(db, org, chain):
    unrelated = add_meeting(db, org, "Unrelated ops", 5)
    result = diff_since(db, chain["second"].id, unrelated.id)
    assert result.out_of_chain is True
    assert result.changes == []


def test_since_the_newest_point_reports_no_changes(db, org, chain):
    result = diff_since(db, chain["second"].id, chain["march"].id)
    assert result.changed is False
    assert result.out_of_chain is False


def test_two_hops_report_both_steps(db, org):
    """A field that moved twice must not collapse to first-vs-last."""
    january = add_meeting(db, org, "January board", 90)
    march = add_meeting(db, org, "March board", 60)
    june = add_meeting(db, org, "June board", 30)

    first = add_decision(db, org, january, "Approve the plan", "proposed")
    second = add_decision(db, org, march, "Approve the plan", "agreed", supersedes=first)
    add_decision(db, org, june, "Approve the plan", "reversed", supersedes=second)

    result = diff_since(db, first.id, january.id)
    statuses = [(c.old_value, c.new_value) for c in result.changes if c.field == "status"]
    assert statuses == [("proposed", "agreed"), ("agreed", "reversed")]


def test_unknown_decision_raises(db, org, chain):
    with pytest.raises(ValueError, match="not found"):
        diff_since(db, "nope", chain["january"].id)


# -- amount parsing --------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("capex of 500,000", 500000),
        ("budget is $1.5m", 1500000),
        ("£250k for the works", 250000),
        ("2 billion tenge", 2_000_000_000),
        ("no numbers at all", None),
        ("", None),
        (None, None),
    ],
)
def test_amount_parsing(text, expected):
    assert parse_amount(text) == expected


def test_unparseable_amount_produces_no_change_rather_than_a_false_one(db, org):
    january = add_meeting(db, org, "January board", 90)
    march = add_meeting(db, org, "March board", 30)
    first = add_decision(db, org, january, "Approve the plan", "agreed")
    add_decision(db, org, march, "Approve the revised plan", "agreed", supersedes=first)

    result = diff_since(db, first.id, january.id)
    assert "amount" not in field_map(result), "reported a money change with no money in it"


# -- the prose summary is downstream, never load-bearing -------------------


class FakeLLM:
    def __init__(self, reply="Costs rose and the decision was deferred."):
        self.reply = reply
        self.config = ProviderConfig(name="fake", model="fake", api_key_env="NONE")
        self.prompts = []

    async def generate(self, prompt, *, system=None, max_tokens=None, temperature=None):
        self.prompts.append((system, prompt))
        return Completion(text=self.reply, model="fake", usage=Usage(1, 1))


def test_summary_is_generated_from_the_computed_diff_only(db, org, chain):
    """The model sees the field list, not the transcript — it phrases, not decides."""
    result = diff_since(db, chain["second"].id, chain["january"].id)
    llm = FakeLLM()
    summary = asyncio.run(summarise_changes(result, provider=llm))

    assert summary
    system, prompt = llm.prompts[0]
    assert "Changes computed from the database" in prompt

    # The prompt is exactly the computed diff, one line per change, and nothing
    # else. Asserted structurally rather than by keyword: values that appear in
    # a diffed field (a rationale, say) legitimately reach the prompt, so the
    # property that matters is that no line exists which the diff did not put
    # there.
    change_lines = [line for line in prompt.splitlines() if line.startswith("- ")]
    assert len(change_lines) == len(result.changes)
    for line, change in zip(change_lines, result.changes, strict=True):
        assert change.field in line
        assert repr(change.old_value) in line
        assert repr(change.new_value) in line

    # And the model is told it is phrasing, not deciding.
    assert "computed from a database by comparison, not by you" in " ".join(system.split())


def test_summary_failure_does_not_lose_the_diff(db, org, chain):
    class Broken:
        config = ProviderConfig(name="broken", model="x", api_key_env="NONE")

        async def generate(self, *args, **kwargs):
            raise RuntimeError("provider down")

    result = diff_since(db, chain["second"].id, chain["january"].id)
    assert asyncio.run(summarise_changes(result, provider=Broken())) is None
    assert result.changed, "the structured diff was lost with the summary"


def test_no_summary_when_nothing_changed(db, org, chain):
    result = diff_since(db, chain["second"].id, chain["march"].id)
    llm = FakeLLM()
    assert asyncio.run(summarise_changes(result, provider=llm)) is None
    assert llm.prompts == [], "spent a model call to say nothing changed"


# -- endpoint --------------------------------------------------------------


def test_changes_endpoint_returns_the_structured_diff(data_dir, db, org, chain):
    with TestClient(create_app()) as client:
        response = client.get(
            f"/api/decisions/{chain['second'].id}/changes",
            params={"since": chain["january"].id},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert body["since_meeting_title"] == "January board"
    assert body["current_meeting_title"] == "March board"
    assert body["summary"] is None, "a summary was generated without being asked for"

    by_field = {c["field"]: (c["old_value"], c["new_value"]) for c in body["changes"]}
    assert by_field["status"] == ("agreed", "deferred")
    assert by_field["amount"] == ("500000", "750000")
    for change in body["changes"]:
        assert change["evidence_id"]


def test_changes_endpoint_404s_for_unknown_decision(data_dir):
    with TestClient(create_app()) as client:
        assert client.get("/api/decisions/nope/changes", params={"since": "x"}).status_code == 404


def test_changes_endpoint_requires_since(data_dir, db, org, chain):
    with TestClient(create_app()) as client:
        assert client.get(f"/api/decisions/{chain['second'].id}/changes").status_code == 422
