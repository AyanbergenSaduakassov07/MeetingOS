"""Document upload, linking, and indexing.

Documents join meetings in the corpus index, so a question can be answered by
cross-referencing the two. Linking a document to a meeting is explicit: working
out that "the contract we discussed" refers to a particular file is its own
extraction problem, and a wrong guess files a contract against the wrong
meeting — worse than no link.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config
from ..database import Document, DocumentChunk, DocumentType, Organization, get_db
from ..meetings.documents import (
    ALLOWED_SUFFIXES,
    DocumentError,
    checksum,
    ingest_document,
    link_document_to_meeting,
)
from .limits import limit_upload
from .meetings import MAX_UPLOAD_BYTES, UPLOAD_CHUNK_SIZE, UploadTooLargeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])


class DocumentOut(BaseModel):
    id: str
    org_id: str
    meeting_id: str | None = None
    title: str
    doc_type: str
    mime_type: str | None = None
    size_bytes: int | None = None
    language: str | None = None
    is_sensitive: bool = False
    chunk_count: int = 0
    indexed: bool = False
    notes: list[str] = []


class LinkRequest(BaseModel):
    meeting_id: str
    note: str | None = None


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


async def _store(upload: UploadFile, document_id: str, suffix: str) -> Path:
    """Stream to disk with the size cap enforced during the stream."""
    destination = config.get_data_dir() / "documents" / f"{document_id}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise UploadTooLargeError(written)
                handle.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


@router.post(
    "",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_upload)],
)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_type: str = Form(DocumentType.OTHER.value),
    meeting_id: str | None = Form(None),
    org_id: str | None = Form(None),
    is_sensitive: bool = Form(False),
    db: Session = Depends(get_db),
) -> DocumentOut:
    """Upload a document, extract its text, chunk it, and index it.

    ``is_sensitive`` marks contracts and financials for an operator's own
    triage. It does not currently change what is sent to the model — that is a
    deliberate gap, reported rather than papered over.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported type {suffix or file.filename!r}. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}",
        )

    organization = _resolve_org(db, org_id)
    document = Document(
        org_id=organization.id,
        meeting_id=meeting_id,
        title=title,
        doc_type=doc_type,
        storage_path="",
        mime_type=file.content_type,
        is_sensitive=is_sensitive,
    )
    db.add(document)
    db.flush()

    try:
        stored = await _store(file, document.id, suffix)
    except UploadTooLargeError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Document exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to store document upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not store the uploaded document.",
        ) from exc

    document.storage_path = config.to_storage_path(stored)
    document.size_bytes = stored.stat().st_size
    document.checksum = checksum(stored)
    db.commit()

    notes: list[str] = []
    chunk_count = 0
    try:
        report = ingest_document(db, document.id)
        chunk_count = report.chunks
        notes.extend(report.notes)
    except DocumentError as exc:
        notes.append(f"Text extraction failed: {exc}")

    indexed = False
    if chunk_count:
        try:
            from ..memory import index_document

            await index_document(document.id, db=db)
            indexed = True
        except Exception as exc:
            logger.warning("Document %s not indexed: %s", document.id, exc)
            notes.append(f"Not yet searchable: {exc}")

    return DocumentOut(
        id=document.id,
        org_id=document.org_id,
        meeting_id=document.meeting_id,
        title=document.title,
        doc_type=document.doc_type,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        language=document.language,
        is_sensitive=bool(document.is_sensitive),
        chunk_count=chunk_count,
        indexed=indexed,
        notes=notes,
    )


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    org_id: str | None = Query(None),
    meeting_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    """Documents in the org, optionally those linked to one meeting."""
    from ..database import MeetingDocument

    query = db.query(Document)
    if org_id:
        query = query.filter(Document.org_id == org_id)
    if meeting_id:
        linked = {row[0] for row in db.query(MeetingDocument.document_id).filter_by(meeting_id=meeting_id).all()}
        query = query.filter((Document.meeting_id == meeting_id) | (Document.id.in_(linked or {""})))

    return [
        DocumentOut(
            id=d.id,
            org_id=d.org_id,
            meeting_id=d.meeting_id,
            title=d.title,
            doc_type=d.doc_type,
            mime_type=d.mime_type,
            size_bytes=d.size_bytes,
            language=d.language,
            is_sensitive=bool(d.is_sensitive),
            chunk_count=db.query(DocumentChunk).filter_by(document_id=d.id).count(),
        )
        for d in query.all()
    ]


@router.post("/{document_id}/link", status_code=status.HTTP_201_CREATED)
async def link_document(document_id: str, payload: LinkRequest, db: Session = Depends(get_db)) -> dict:
    """Record that a document was referenced in a meeting. Explicit, not inferred."""
    try:
        link = link_document_to_meeting(db, document_id, payload.meeting_id, note=payload.note)
    except DocumentError as exc:
        code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return {"id": link.id, "document_id": document_id, "meeting_id": payload.meeting_id}
