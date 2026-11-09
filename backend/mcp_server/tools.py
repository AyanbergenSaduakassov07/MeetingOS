"""MeetingOS tools for MCP clients (Claude Code, Cursor, any MCP host).

Read-only by design: an agent can look things up and ask questions, never
create, edit, or delete. Each tool is a thin call into the same service layer
the REST API uses, so behaviour and safeguards match the web UI exactly.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .. import config
from ..database import Meeting, Organization, new_session
from ..meetings.commitments import list_commitments
from ..memory.org_copilot import ask_corpus

MAX_MEETINGS = 100
MAX_COMMITMENTS = 200


def _org_id(db) -> str:
    """The pinned org, or the only org. Ambiguity is an error, never a guess."""
    pinned = config.pinned_org_id()
    if pinned:
        return pinned
    orgs = db.query(Organization).limit(2).all()
    if len(orgs) != 1:
        raise ValueError("Set MEETINGOS_ORG_ID: this database holds zero or several organizations.")
    return orgs[0].id


def list_meetings_tool(limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    """Recent meetings, newest first."""
    with new_session() as db:
        query = db.query(Meeting).filter(Meeting.org_id == _org_id(db))
        if status:
            query = query.filter(Meeting.status == status)
        rows = query.order_by(Meeting.created_at.desc()).limit(max(1, min(limit, MAX_MEETINGS))).all()
        return [
            {
                "id": m.id,
                "title": m.title,
                "status": m.status,
                "language": m.language,
                "date": (m.actual_start or m.scheduled_start or m.created_at).isoformat()
                if (m.actual_start or m.scheduled_start or m.created_at)
                else None,
            }
            for m in rows
        ]


def list_commitments_tool(overdue: bool | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Commitments and action items across all meetings, most overdue first."""
    with new_session() as db:
        items = list_commitments(db, org_id=_org_id(db), overdue=overdue, limit=max(1, min(limit, MAX_COMMITMENTS)))
        return [vars(item) for item in items]


async def ask_tool(question: str, answer_language: str | None = None) -> dict[str, Any]:
    """Answer from every meeting and document, with citations back to the source."""
    with new_session() as db:
        result = await ask_corpus(question[:1000], org_id=_org_id(db), answer_language=answer_language, db=db)
        return {
            "answer": result.answer,
            "not_discussed": result.not_discussed,
            "citations": [vars(c) for c in result.citations],
        }


def register_tools(mcp: FastMCP) -> None:
    mcp.tool(name="list_meetings", description="List recent meetings (id, title, status, date). Newest first.")(
        list_meetings_tool
    )
    mcp.tool(
        name="list_commitments",
        description="Commitments and action items with owner, due date and overdue flag. overdue=true for late only.",
    )(list_commitments_tool)
    mcp.tool(
        name="ask",
        description=(
            "Ask a question across all meetings and documents. Returns an answer with citations "
            "(meeting, timestamp, quote). not_discussed=true means the record has no answer."
        ),
    )(ask_tool)
