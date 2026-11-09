"""MCP tools are scoped to one organisation and never guess between several."""

from __future__ import annotations

import pytest

from backend.database import Meeting, Organization
from backend.mcp_server.tools import list_commitments_tool, list_meetings_tool


def _org(db, slug: str) -> Organization:
    org = Organization(name=slug.upper(), slug=slug)
    db.add(org)
    db.commit()
    return org


def test_list_meetings_returns_only_the_single_orgs_meetings(db):
    org = _org(db, "kmg")
    db.add(Meeting(org_id=org.id, title="Board", status="completed", source="upload"))
    db.commit()

    meetings = list_meetings_tool()

    assert [m["title"] for m in meetings] == ["Board"]
    assert meetings[0]["date"] is not None


def test_refuses_to_guess_between_organisations(db, monkeypatch):
    monkeypatch.delenv("MEETINGOS_ORG_ID", raising=False)
    _org(db, "a")
    _org(db, "b")

    with pytest.raises(ValueError, match="MEETINGOS_ORG_ID"):
        list_meetings_tool()


def test_pinned_org_scopes_results(db, monkeypatch):
    a, b = _org(db, "a"), _org(db, "b")
    db.add_all(
        [
            Meeting(org_id=a.id, title="A sync", status="completed", source="upload"),
            Meeting(org_id=b.id, title="B sync", status="completed", source="upload"),
        ]
    )
    db.commit()
    monkeypatch.setenv("MEETINGOS_ORG_ID", b.id)

    assert [m["title"] for m in list_meetings_tool()] == ["B sync"]
    assert list_commitments_tool() == []
