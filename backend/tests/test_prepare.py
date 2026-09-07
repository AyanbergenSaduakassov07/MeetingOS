"""Meeting preparation briefs.

Acceptance:
- `test_brief_for_a_recurring_project_pulls_open_items_and_changes` — accurate
  open items and recent changes, each with a working citation.
- `test_new_project_with_no_history_says_so_plainly` — nothing invented to
  fill the gap.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.ai.base import Completion, ProviderConfig, Usage
from backend.app import create_app
from backend.database import (
    Commitment,
    Decision,
    Evidence,
    Meeting,
    MeetingStatus,
    Organization,
    TranscriptSegment,
    User,
)
from backend.meetings.prepare import assemble_brief, write_brief
from backend.memory import index_meeting, reset_backends

NOW = datetime.now(UTC)


class FakeEmbedder:
    VOCAB = [
        "aktau",
        "expansion",
        "terminal",
        "phase",
        "capex",
        "budget",
        "dredging",
        "survey",
        "jetty",
        "canteen",
        "hiring",
        "greenfield",
    ]

    def __init__(self) -> None:
        self.config = ProviderConfig(
            name="fake",
            model="fake",
            api_key_env="NONE",
            embedding_model="fake",
            supports_embeddings=True,
        )

    async def embed(self, texts):
        out = []
        for entry in texts:
            words = {w.strip(".,()'\"").lower() for w in entry.split()}
            vector = [1.0 if term in words else 0.0 for term in self.VOCAB]
            out.append(vector if any(vector) else [0.01] * len(self.VOCAB))
        return out


class FakeLLM:
    def __init__(self, reply="Dana is 14 days overdue on the sponsor invoice."):
        self.reply = reply
        self.config = ProviderConfig(name="fake", model="fake", api_key_env="NONE")
        self.prompts: list[tuple[str | None, str]] = []

    async def generate(self, prompt, *, system=None, max_tokens=None, temperature=None):
        self.prompts.append((system, prompt))
        return Completion(text=self.reply, model="fake", usage=Usage(1, 1))


@pytest.fixture(autouse=True)
def _fresh_backend():
    reset_backends()
    yield
    reset_backends()


@pytest.fixture
def org(db):
    organization = Organization(name="KMG", slug="kmg")
    db.add(organization)
    db.commit()
    return organization


@pytest.fixture
def people(db, org):
    users = {}
    for name, email in (("Dana", "dana@x.io"), ("Priya", "priya@x.io")):
        user = User(org_id=org.id, email=email, full_name=name)
        db.add(user)
        db.flush()
        users[name] = user
    db.commit()
    return users


def add_meeting(db, org, title, days_ago) -> Meeting:
    meeting = Meeting(
        org_id=org.id,
        title=title,
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
        created_at=NOW - timedelta(days=days_ago),
    )
    db.add(meeting)
    db.commit()
    return meeting


def evidence_for(db, org, meeting, text) -> Evidence:
    segment = TranscriptSegment(meeting_id=meeting.id, sequence=0, start_ms=27000, end_ms=35000, text=text)
    db.add(segment)
    db.flush()
    evidence = Evidence(
        org_id=org.id,
        meeting_id=meeting.id,
        claim_text=text,
        quote=text,
        confidence=0.91,
        verification_status="verified",
    )
    evidence.cite(segment)
    db.add(evidence)
    db.flush()
    return evidence


@pytest.fixture
def project_history(db, org, people):
    """A recurring project: two meetings, a chain, and an overdue promise."""
    january = add_meeting(db, org, "January board", 120)
    march = add_meeting(db, org, "March board", 30)

    first = Decision(
        org_id=org.id,
        meeting_id=january.id,
        status="agreed",
        title="Approve the Aktau expansion phase two capex of 500,000",
        evidence=evidence_for(db, org, january, "Approve the Aktau expansion phase two capex of 500,000"),
    )
    db.add(first)
    db.flush()
    second = Decision(
        org_id=org.id,
        meeting_id=march.id,
        status="deferred",
        supersedes_id=first.id,
        title="Defer the Aktau expansion phase two capex of 750,000",
        evidence=evidence_for(db, org, march, "Defer the Aktau expansion phase two capex of 750,000"),
    )
    db.add(second)

    db.add(
        Commitment(
            org_id=org.id,
            meeting_id=march.id,
            committer_id=people["Dana"].id,
            text="I will chase the Aktau dredging survey",
            status="pending",
            due_date=NOW - timedelta(days=14),
            evidence=evidence_for(db, org, march, "I will chase the Aktau dredging survey"),
        )
    )
    db.add(
        Commitment(
            org_id=org.id,
            meeting_id=march.id,
            committer_id=people["Priya"].id,
            text="I will circulate the jetty drawings",
            status="kept",
            due_date=NOW - timedelta(days=20),
            evidence=evidence_for(db, org, march, "I will circulate the jetty drawings"),
        )
    )
    db.commit()

    embedder = FakeEmbedder()
    for meeting in (january, march):
        asyncio.run(index_meeting(meeting.id, embedder=embedder, db=db))
    return {"january": january, "march": march, "first": first, "second": second, "embedder": embedder}


# -- acceptance ------------------------------------------------------------


def test_brief_for_a_recurring_project_pulls_open_items_and_changes(db, org, people, project_history):
    """Acceptance: accurate open items and recent changes, each cited."""
    brief = asyncio.run(
        assemble_brief(
            db,
            org_id=org.id,
            attendee_ids=[people["Dana"].id, people["Priya"].id],
            project="Aktau expansion",
            embedder=project_history["embedder"],
        )
    )

    assert not brief.is_empty
    assert brief.attendee_names == ["Dana", "Priya"] or set(brief.attendee_names) == {"Dana", "Priya"}

    # Open commitments: Dana's overdue one in, Priya's kept one out.
    texts = {item.text for item in brief.open_commitments}
    assert "I will chase the Aktau dredging survey" in texts
    assert "I will circulate the jetty drawings" not in texts, "a settled promise was included"
    assert brief.open_commitments[0].overdue is True, "overdue item is not first"

    # Unresolved decisions: the deferred one, not the agreed one.
    statuses = {d.status for d in brief.unresolved_decisions}
    assert statuses == {"deferred"}
    assert any("Aktau" in d.title for d in brief.unresolved_decisions)

    # Changes since the last related meeting.
    assert brief.last_related_meeting_title == "January board"
    fields = {c.field_name for c in brief.recent_changes}
    assert "status" in fields and "amount" in fields

    # Working citations on every single line.
    for item in (*brief.open_commitments, *brief.unresolved_decisions, *brief.recent_changes):
        assert item.evidence_id, f"brief line without a citation: {item}"
        assert db.query(Evidence).filter_by(id=item.evidence_id).one() is not None
        assert item.start_ms == 27000


def test_new_project_with_no_history_says_so_plainly(db, org, people, project_history):
    """Acceptance: nothing invented to fill the gap."""
    brief = asyncio.run(
        assemble_brief(
            db,
            org_id=org.id,
            project="Greenfield refinery",
            embedder=project_history["embedder"],
        )
    )

    assert brief.is_empty
    assert brief.open_commitments == []
    assert brief.unresolved_decisions == []
    assert brief.recent_changes == []
    assert any("no prior history" in note.lower() for note in brief.notes)

    # And the prose path says so without calling a model.
    llm = FakeLLM()
    prose = asyncio.run(write_brief(brief, provider=llm))
    assert "No prior history" in prose
    assert llm.prompts == [], "spent a model call to pad an empty brief"


# -- provenance ------------------------------------------------------------


def test_an_uncitable_item_is_dropped_not_shown_unsourced(db, org, people, project_history):
    db.add(
        Commitment(
            org_id=org.id,
            meeting_id=project_history["march"].id,
            committer_id=people["Dana"].id,
            text="Promise with no evidence",
            status="pending",
            due_date=NOW - timedelta(days=2),
        )
    )
    db.commit()

    brief = asyncio.run(
        assemble_brief(
            db,
            org_id=org.id,
            attendee_ids=[people["Dana"].id],
            project="Aktau expansion",
            embedder=project_history["embedder"],
        )
    )

    assert "Promise with no evidence" not in {i.text for i in brief.open_commitments}
    assert any("no transcript citation" in note for note in brief.notes)


def test_assembly_calls_no_model(db, org, people, project_history, monkeypatch):
    """Assembly must be deterministic; only the prose layer may call out."""

    def explode(*args, **kwargs):
        raise AssertionError("assemble_brief reached an LLM provider")

    monkeypatch.setattr("backend.ai.get_llm_provider", explode)
    brief = asyncio.run(
        assemble_brief(
            db,
            org_id=org.id,
            attendee_ids=[people["Dana"].id],
            project="Aktau expansion",
            embedder=project_history["embedder"],
        )
    )
    assert brief.item_count > 0


def test_prose_receives_only_assembled_material(db, org, people, project_history):
    brief = asyncio.run(
        assemble_brief(
            db,
            org_id=org.id,
            attendee_ids=[people["Dana"].id],
            project="Aktau expansion",
            embedder=project_history["embedder"],
        )
    )
    llm = FakeLLM()
    asyncio.run(write_brief(brief, provider=llm))

    system, prompt = llm.prompts[0]
    assert "BEGIN ASSEMBLED MATERIAL (untrusted data)" in prompt
    assert "Use only the material given" in system
    # Every non-header line in the prompt corresponds to an assembled item.
    lines = [line for line in prompt.splitlines() if line.startswith("- ")]
    assert len(lines) == brief.item_count


def test_prose_failure_does_not_lose_the_brief(db, org, people, project_history):
    class Broken:
        config = ProviderConfig(name="broken", model="x", api_key_env="NONE")

        async def generate(self, *args, **kwargs):
            raise RuntimeError("provider down")

    brief = asyncio.run(
        assemble_brief(
            db,
            org_id=org.id,
            attendee_ids=[people["Dana"].id],
            project="Aktau expansion",
            embedder=project_history["embedder"],
        )
    )
    assert asyncio.run(write_brief(brief, provider=Broken())) is None
    assert brief.item_count > 0, "structured sections were lost with the prose"


# -- scoping ---------------------------------------------------------------


def test_attendee_from_another_org_is_skipped_and_noted(db, org, people, project_history):
    other = Organization(name="Other", slug="other")
    db.add(other)
    db.flush()
    outsider = User(org_id=other.id, email="x@other.io", full_name="Outsider")
    db.add(outsider)
    db.commit()

    brief = asyncio.run(
        assemble_brief(
            db,
            org_id=org.id,
            attendee_ids=[people["Dana"].id, outsider.id],
            project="Aktau expansion",
            embedder=project_history["embedder"],
        )
    )
    assert outsider.id not in brief.attendee_ids
    assert any("not in this organisation" in note for note in brief.notes)


# -- endpoint --------------------------------------------------------------


def test_prepare_endpoint_returns_a_cited_brief(data_dir, db, org, people, project_history):
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/meetings/prepare",
            json={
                "attendee_ids": [people["Dana"].id, people["Priya"].id],
                "project": "Aktau expansion",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["is_empty"] is False
    assert body["item_count"] > 0
    assert body["summary"] is None, "prose was generated without being asked for"

    for section in ("open_commitments", "unresolved_decisions", "recent_changes"):
        for item in body[section]:
            assert item["evidence_id"], f"{section} entry without a citation"
            assert item["start_ms"] == 27000


def test_prepare_endpoint_requires_attendees_or_a_project(data_dir, db, org):
    with TestClient(create_app()) as client:
        assert client.post("/api/meetings/prepare", json={}).status_code == 422


def test_prepare_endpoint_reports_an_empty_brief_honestly(data_dir, db, org, project_history):
    with TestClient(create_app()) as client:
        body = client.post("/api/meetings/prepare", json={"project": "Greenfield refinery"}).json()

    assert body["is_empty"] is True
    assert body["item_count"] == 0
    assert any("no prior history" in note.lower() for note in body["notes"])
