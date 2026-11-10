"""Board mode: the template variant and the minutes generator.

Acceptance: a board-type meeting produces minutes an executive would recognise,
with every claim traceable to a citation —
`test_board_meeting_produces_usable_minutes_with_citations`.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.ai.base import Completion, ProviderConfig, Usage
from backend.app import create_app
from backend.database import (
    ActionItem,
    Commitment,
    Decision,
    Evidence,
    Meeting,
    MeetingStatus,
    MeetingTemplate,
    Organization,
    Risk,
    TranscriptSegment,
    User,
)
from backend.meetings import board
from backend.meetings.board import (
    BOARD_EXTRACTORS,
    ensure_board_template,
    is_board_meeting,
    polish_minutes,
    render_minutes,
    to_markdown,
)
from backend.meetings.intelligence import _EXTRACTORS, extractors_for


@pytest.fixture
def org(db):
    organization = Organization(name="KMG", slug="kmg")
    db.add(organization)
    db.commit()
    return organization


@pytest.fixture
def board_meeting(db, org):
    template = ensure_board_template(db, org.id)
    meeting = Meeting(
        org_id=org.id,
        title="Q3 Board Meeting",
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
        template_id=template.id,
    )
    db.add(meeting)
    db.commit()
    return meeting


def add_evidence(db, org, meeting, text, *, at_ms=30000, status_value="verified") -> Evidence:
    segment = TranscriptSegment(meeting_id=meeting.id, sequence=0, start_ms=at_ms, end_ms=at_ms + 8000, text=text)
    db.add(segment)
    db.flush()
    evidence = Evidence(
        org_id=org.id,
        meeting_id=meeting.id,
        claim_text=text,
        quote=text,
        confidence=0.93,
        verification_status=status_value,
    )
    evidence.cite(segment)
    db.add(evidence)
    db.flush()
    return evidence


# -- the template variant --------------------------------------------------


def test_board_template_is_created_idempotently(db, org):
    first = ensure_board_template(db, org.id)
    second = ensure_board_template(db, org.id)
    assert first.id == second.id
    assert db.query(MeetingTemplate).filter_by(org_id=org.id).count() == 1
    assert "Resolutions" in first.agenda


def test_board_meeting_extracts_three_extra_kinds(db, org, board_meeting):
    extractors = extractors_for(db, board_meeting)
    assert set(extractors) == set(_EXTRACTORS) | set(BOARD_EXTRACTORS)
    assert {"resolution", "dissent", "financial_implication"} <= set(extractors)


def test_a_normal_meeting_gets_only_the_standard_four(db, org):
    meeting = Meeting(org_id=org.id, title="Standup", status=MeetingStatus.COMPLETED.value, source="upload")
    db.add(meeting)
    db.commit()
    assert set(extractors_for(db, meeting)) == set(_EXTRACTORS)
    assert is_board_meeting(db, meeting) is False


@pytest.mark.parametrize("schema_name", sorted(BOARD_EXTRACTORS))
def test_board_schemas_reject_an_invented_enum(schema_name):
    """A transcript must not be able to widen an outcome or a direction."""
    from pydantic import ValidationError

    if schema_name == "resolution":
        with pytest.raises(ValidationError):
            board.ExtractedResolution(segment_id="s", quote="q", confidence=0.5, title="t", outcome="rubber_stamped")
    elif schema_name == "financial_implication":
        with pytest.raises(ValidationError):
            board.ExtractedFinancialImplication(
                segment_id="s", quote="q", confidence=0.5, description="d", direction="magic"
            )
    else:
        # Dissent has no enum; assert its required field instead.
        with pytest.raises(ValidationError):
            board.ExtractedDissent(segment_id="s", quote="q", confidence=0.5)


# -- acceptance ------------------------------------------------------------


@pytest.fixture
def minuted_board(db, org, board_meeting):
    """A board meeting with the full range of extracted items."""
    dana = User(org_id=org.id, email="dana@x.io", full_name="Dana Okoye")
    db.add(dana)
    db.flush()

    db.add(
        Decision(
            org_id=org.id,
            meeting_id=board_meeting.id,
            status="agreed",
            title="Approve the Aktau expansion capex of 500,000",
            description="Moved by Dana Okoye. Seconded by Priya Raman. Vote: for 5, against 1.",
            evidence=add_evidence(db, org, board_meeting, "Resolved, the Aktau capex is approved", at_ms=30000),
        )
    )
    db.add(
        Decision(
            org_id=org.id,
            meeting_id=board_meeting.id,
            status="deferred",
            title="Defer the auditor reappointment",
            evidence=add_evidence(db, org, board_meeting, "We defer the auditor question", at_ms=60000),
        )
    )
    db.add(
        Risk(
            org_id=org.id,
            meeting_id=board_meeting.id,
            severity="medium",
            category="governance",
            title="Dissent recorded — Sam Levy",
            description="Objected that the capex exceeds the approved envelope.",
            evidence=add_evidence(db, org, board_meeting, "I want my objection minuted", at_ms=90000),
        )
    )
    db.add(
        Risk(
            org_id=org.id,
            meeting_id=board_meeting.id,
            severity="medium",
            category="financial",
            title="Financial cost (500,000): Aktau expansion capex",
            evidence=add_evidence(db, org, board_meeting, "That is five hundred thousand", at_ms=120000),
        )
    )
    db.add(
        ActionItem(
            org_id=org.id,
            meeting_id=board_meeting.id,
            assignee_id=dana.id,
            title="Circulate the revised capex schedule",
            status="open",
            evidence=add_evidence(db, org, board_meeting, "Dana will circulate the schedule", at_ms=150000),
        )
    )
    db.add(
        Commitment(
            org_id=org.id,
            meeting_id=board_meeting.id,
            committer_id=dana.id,
            text="I will brief the audit committee before month end",
            evidence=add_evidence(db, org, board_meeting, "I will brief the audit committee", at_ms=180000),
        )
    )
    db.commit()
    return board_meeting


def test_board_meeting_produces_usable_minutes_with_citations(db, org, minuted_board):
    """Acceptance: recognisable minutes, every claim traceable."""
    minutes = render_minutes(db, minuted_board.id)

    headings = [section.heading for section in minutes.sections]
    for expected in ("Resolutions", "Deferred", "Actions", "Risks noted", "Undertakings given"):
        assert expected in headings, f"minutes are missing a {expected!r} section"

    # Every line in every section traces to a real Evidence row.
    assert minutes.line_count >= 6
    assert minutes.cited_line_count == minutes.line_count, "an uncited line reached the minutes"
    for section in minutes.sections:
        for line in section.lines:
            assert line.evidence_id, f"{line.text!r} has no citation"
            assert db.query(Evidence).filter_by(id=line.evidence_id).one() is not None
            assert line.start_ms is not None

    # The rendered document reads like minutes.
    text = to_markdown(minutes)
    assert text.startswith("# Minutes — Q3 Board Meeting")
    assert "RESOLVED: Approve the Aktau expansion capex" in text
    assert "Dissent recorded — Sam Levy" in text
    assert "Dana Okoye: Circulate the revised capex schedule" in text
    # Timestamps are printed, so a citation is findable without leaving the page.
    assert "[0:30]" in text and "[2:30]" in text


def test_untraceable_items_are_listed_separately_not_folded_in(db, org, board_meeting):
    """A reader must be able to tell what the recording backs."""
    db.add(
        Decision(
            org_id=org.id,
            meeting_id=board_meeting.id,
            status="agreed",
            title="Approve something nobody can trace",
        )
    )
    db.add(
        Decision(
            org_id=org.id,
            meeting_id=board_meeting.id,
            status="agreed",
            title="Approve the traceable thing",
            evidence=add_evidence(db, org, board_meeting, "Resolved, approved"),
        )
    )
    db.commit()

    minutes = render_minutes(db, board_meeting.id)
    resolutions = next(s for s in minutes.sections if s.heading == "Resolutions")
    assert [line.text for line in resolutions.lines] == ["RESOLVED: Approve the traceable thing"]
    assert len(minutes.uncited) == 1
    assert "nobody can trace" in minutes.uncited[0].text
    assert any("could not be traced" in note for note in minutes.notes)

    text = to_markdown(minutes)
    assert "## Not traceable to the recording" in text
    assert "should not be relied on" in text


def test_empty_meeting_says_so_rather_than_producing_blank_minutes(db, org, board_meeting):
    minutes = render_minutes(db, board_meeting.id)
    assert minutes.sections == []
    assert any("Nothing was extracted" in note for note in minutes.notes)


# -- the summary is downstream, never load-bearing -------------------------


class FakeLLM:
    def __init__(self, reply="The board approved the Aktau capex over one objection."):
        self.reply = reply
        self.config = ProviderConfig(name="fake", model="fake", api_key_env="NONE")
        self.prompts: list[tuple[str | None, str]] = []

    async def generate(self, prompt, *, system=None, max_tokens=None, temperature=None):
        self.prompts.append((system, prompt))
        return Completion(text=self.reply, model="fake", usage=Usage(1, 1))


def test_summary_receives_only_the_assembled_minutes(db, org, minuted_board):
    minutes = render_minutes(db, minuted_board.id)
    llm = FakeLLM()
    summary = asyncio.run(polish_minutes(minutes, provider=llm))

    assert summary
    system, prompt = llm.prompts[0]
    assert "BEGIN MINUTES (untrusted data)" in prompt
    assert "State only what the minutes contain" in " ".join(system.split())
    # The instruction not to drop dissent is explicit, because that is the
    # first thing a summariser loses.
    assert "dissent" in system.lower()


def test_summary_failure_does_not_lose_the_minutes(db, org, minuted_board):
    class Broken:
        config = ProviderConfig(name="broken", model="x", api_key_env="NONE")

        async def generate(self, *args, **kwargs):
            raise RuntimeError("provider down")

    minutes = render_minutes(db, minuted_board.id)
    assert asyncio.run(polish_minutes(minutes, provider=Broken())) is None
    assert minutes.line_count >= 6, "minutes were lost with the summary"


def test_no_summary_for_empty_minutes(db, org, board_meeting):
    minutes = render_minutes(db, board_meeting.id)
    llm = FakeLLM()
    assert asyncio.run(polish_minutes(minutes, provider=llm)) is None
    assert llm.prompts == [], "spent a model call on empty minutes"


# -- endpoint --------------------------------------------------------------


def test_minutes_endpoint_returns_a_cited_document(data_dir, db, org, minuted_board):
    with TestClient(create_app()) as client:
        response = client.post(f"/api/meetings/{minuted_board.id}/minutes")

    assert response.status_code == 200
    body = response.json()
    assert body["is_board_meeting"] is True
    assert body["meeting_title"] == "Q3 Board Meeting"
    assert body["line_count"] == body["cited_line_count"]
    assert body["summary"] is None, "a summary was generated without being asked for"
    assert body["markdown"].startswith("# Minutes — Q3 Board Meeting")

    for section in body["sections"]:
        assert section["lines"], f"empty section {section['heading']!r} shipped"
        for line in section["lines"]:
            assert line["evidence_id"], f"{line['text']!r} has no citation"


def test_minutes_endpoint_404s_for_unknown_meeting(data_dir):
    with TestClient(create_app()) as client:
        assert client.post("/api/meetings/nope/minutes").status_code == 404


def test_board_template_endpoint_is_idempotent(data_dir, db, org):
    with TestClient(create_app()) as client:
        first = client.post("/api/meetings/templates/board").json()
        second = client.post("/api/meetings/templates/board").json()
    assert first["id"] == second["id"]
    assert db.query(MeetingTemplate).count() == 1


def test_summary_can_be_asked_for_in_another_language(db, org, minuted_board):
    """A Kazakh reader of a Russian meeting asks for the summary in Kazakh."""
    llm = FakeLLM()
    asyncio.run(polish_minutes(render_minutes(db, minuted_board.id), provider=llm, language="kk"))

    assert "ISO code 'kk'" in llm.prompts[0][1]
