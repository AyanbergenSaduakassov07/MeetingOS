"""Org-wide copilot: ask a question across every meeting and document.

Distinct from ``POST /api/meetings/{id}/ask``, which answers from one
transcript. This one retrieves across the whole corpus, which is a wider
injection surface — a single poisoned source reaches every question anyone
asks, not just questions about that source. The defenses live in
``backend/memory/org_copilot.py``; this module is the HTTP edge.

Rate limited on the same bucket as the per-meeting copilot: each call costs an
embedding plus a generation, and neither endpoint is authenticated yet.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config
from ..database import Organization, get_db
from ..memory.org_copilot import OrgCopilotError, ask_corpus
from .limits import limit_ask

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class OrgAskRequest(BaseModel):
    """A question about the whole org. Untrusted text throughout."""

    question: str = Field(min_length=1, max_length=1000)
    org_id: str | None = None
    # Language for the answer. Citations stay in their source language — the
    # transcript is the record and must not be silently rewritten.
    answer_language: str | None = Field(default=None, max_length=40)


class OrgCitationOut(BaseModel):
    """One corpus record backing an answer, tagged by where it came from."""

    record_type: str
    record_id: str
    text: str
    # "meeting" or "document" — a reader must be able to tell a minuted
    # statement from a clause in a contract without inspecting ids.
    source_kind: str
    source_id: str | None = None
    source_title: str | None = None
    evidence_id: str | None = None
    verification_status: str | None = None
    start_ms: int | None = None
    language: str | None = None
    score: float = 0.0


class OrgAskResponse(BaseModel):
    question: str
    answer: str
    citations: list[OrgCitationOut] = []
    not_discussed: bool = False
    unsupported: bool = False
    records_considered: int = 0
    records_retrieved: int = 0
    sources_spanned: int = 0
    answer_language: str | None = None


def _resolve_org_id(db: Session, org_id: str | None) -> str:
    """The organisation to search, refusing to search someone else's.

    ``org_id`` arrives in the request body and nothing authenticates the
    caller, so on a multi-tenant install this one parameter reads a whole
    tenant's corpus. Real authentication and a server-side binding are the fix
    and are not built here; ``MEETINGOS_ORG_ID`` is the control that works
    without them. When it is set this process serves exactly one organisation
    and a request naming another is refused, so an operator running more than
    one tenant has something to reach for today.

    The id is also checked to exist. Passing an unknown one used to fall
    through to retrieval and come back "not discussed", which reads as an
    answer about the corpus rather than a mistake in the request.
    """
    pinned = config.pinned_org_id()
    if pinned:
        if org_id and org_id != pinned:
            logger.warning("Refused a copilot question scoped to org %s; this process serves one org", org_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This deployment serves a single organization and it is not the one requested.",
            )
        org_id = pinned

    if org_id:
        if db.query(Organization).filter_by(id=org_id).first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} not found",
            )
        return org_id

    orgs = db.query(Organization).limit(2).all()
    if len(orgs) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pass org_id explicitly: zero or multiple organizations exist.",
        )
    return orgs[0].id


@router.post("/ask", response_model=OrgAskResponse, dependencies=[Depends(limit_ask)])
async def ask_org(payload: OrgAskRequest, db: Session = Depends(get_db)) -> OrgAskResponse:
    """Answer a question from every meeting and document in the org.

    Read-only. Retrieves via the hybrid vector + keyword paths, reranks, and
    calls the model with only the retrieved excerpts. No tools are exposed, so
    an instruction planted in a retrieved chunk has no action to reach for.
    """
    org_id = _resolve_org_id(db, payload.org_id)
    try:
        result = await ask_corpus(
            payload.question,
            org_id=org_id,
            answer_language=payload.answer_language,
            db=db,
        )
    except OrgCopilotError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return OrgAskResponse(
        question=result.question,
        answer=result.answer,
        citations=[OrgCitationOut(**vars(c)) for c in result.citations],
        not_discussed=result.not_discussed,
        unsupported=result.unsupported,
        records_considered=result.records_considered,
        records_retrieved=result.records_retrieved,
        sources_spanned=result.meetings_spanned,
        answer_language=result.answer_language,
    )
