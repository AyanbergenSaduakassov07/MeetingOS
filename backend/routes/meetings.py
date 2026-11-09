"""Meeting CRUD.

v0.1 scaffolding.  ``list`` and ``get`` are real queries — they are what the
web client polls and what proves the schema and session wiring work
end-to-end.  The mutating endpoints are declared but not implemented: creating
a meeting means deciding how audio arrives (upload, bot join, live stream) and
which org the caller belongs to, and neither is settled.  They return 501 so
the shape is visible in the OpenAPI schema without pretending to work.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import config
from ..database import (
    ActionItem,
    Commitment,
    Decision,
    Meeting,
    MeetingSource,
    MeetingStatus,
    Organization,
    Risk,
    Speaker,
    Topic,
    TranscriptSegment,
    get_db,
)
from ..meetings.board import ensure_board_template, is_board_meeting, polish_minutes, render_minutes, to_markdown
from ..meetings.copilot import CopilotError, answer_question
from ..meetings.ingestion import schedule_processing
from ..meetings.prepare import assemble_brief, write_brief
from .limits import limit_ask, limit_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

NOT_IMPLEMENTED_DETAIL = "Not implemented in v0.1."

# Streamed in 1 MB chunks so a two-hour recording never sits in memory whole.
UPLOAD_CHUNK_SIZE = 1024 * 1024

# Hard ceiling on one upload. Without it the streaming loop writes whatever it
# is given until the disk fills, and every accepted byte also buys transcription
# and extraction calls at a third party. Roughly eight hours of 64kbps audio,
# which is longer than any meeting this is built for.
MAX_UPLOAD_BYTES = int(os.environ.get("MEETINGOS_MAX_UPLOAD_BYTES", 250 * 1024 * 1024))

# Containers a decoder can actually open. The stored file keeps its uploaded
# extension because decoders select by suffix, so the allowlist is also what
# determines the name on disk.
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm", ".opus"}


class MeetingSummary(BaseModel):
    """A meeting as it appears in a list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    title: str
    status: str
    source: str
    visibility: str
    language: str | None = None
    scheduled_start: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    audio_duration_seconds: float | None = None
    created_at: datetime | None = None


class MeetingDetail(MeetingSummary):
    """A single meeting, with the fields a list view omits."""

    description: str | None = None
    summary: str | None = None
    sentiment_score: float | None = None
    template_id: str | None = None
    created_by_id: str | None = None
    processing_error: str | None = None
    consent_confirmed_at: datetime | None = None
    consent_note: str | None = None
    updated_at: datetime | None = None


class TopicOut(BaseModel):
    """A topic window within the meeting."""

    id: str
    label: str
    start_ms: int | None = None
    end_ms: int | None = None
    salience: float | None = None
    keywords: list[str] = []


class ExtractedItem(BaseModel):
    """One extracted claim, carried together with the evidence for it.

    ``source_segment_text`` is inlined deliberately: a reader judging whether
    to trust an item should not have to fetch the transcript separately to see
    what it was based on.
    """

    id: str
    title: str
    description: str | None = None
    status: str | None = None
    severity: str | None = None
    priority: str | None = None
    source_segment_id: str | None = None
    source_segment_text: str | None = None
    source_start_ms: int | None = None
    source_end_ms: int | None = None
    extraction_confidence: float | None = None
    verification_status: str
    verification_score: float | None = None
    # Set on a Decision that supersedes an earlier one, so the report card can
    # show "revisited" without a second request. Display only — the comparator
    # computes it, this just carries it.
    supersedes_id: str | None = None


class AskRequest(BaseModel):
    """A question about one meeting. Treated as untrusted text throughout."""

    question: str = Field(min_length=1, max_length=1000)


class CitationOut(BaseModel):
    """A transcript segment backing part of an answer."""

    segment_id: str
    start_ms: int
    end_ms: int
    speaker_label: str | None = None
    text: str


class AskResponse(BaseModel):
    """A copilot answer, with everything needed to judge whether to trust it."""

    meeting_id: str
    question: str
    answer: str
    citations: list[CitationOut] = []
    not_discussed: bool = False
    unsupported: bool = False
    segments_considered: int = 0
    segments_retrieved: int = 0


class TranscriptSegmentOut(BaseModel):
    """One utterance, with the times the player needs to seek to it."""

    id: str
    sequence: int
    start_ms: int
    end_ms: int
    speaker_label: str | None = None
    text: str


class MeetingIntelligence(BaseModel):
    """Everything extracted from one meeting."""

    meeting_id: str
    meeting_status: str
    # True when any topic was too long to extract in full. The counts below are
    # then a floor, not a total.
    extraction_truncated: bool = False
    topics: list[TopicOut] = []
    decisions: list[ExtractedItem] = []
    action_items: list[ExtractedItem] = []
    risks: list[ExtractedItem] = []
    commitments: list[ExtractedItem] = []


class MeetingCreate(BaseModel):
    """Request body for creating a meeting."""

    title: str
    description: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    source: str | None = None
    language: str | None = None
    template_id: str | None = None
    visibility: str | None = None


class MeetingUpdate(BaseModel):
    """Partial update. Unset fields are left alone."""

    title: str | None = None
    description: str | None = None
    status: str | None = None
    visibility: str | None = None
    summary: str | None = None


def _validate_audio_suffix(filename: str | None) -> str:
    """Return the uploaded file's extension, or refuse it.

    The rejection names both what arrived and what would work — a caller
    getting "unsupported file type" alone has to go read the source.
    """
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload has no filename, so its format cannot be determined. Allowed: {_allowed_list()}",
        )

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio format '{suffix or filename}'. Allowed: {_allowed_list()}",
        )
    return suffix


def _allowed_list() -> str:
    return ", ".join(sorted(ALLOWED_AUDIO_EXTS))


def _resolve_org(db: Session, org_id: str | None) -> Organization:
    """Resolve the owning organization.

    Explicit ``org_id`` wins.  Otherwise the single existing org is used —
    a convenience for single-tenant installs that deliberately refuses to
    guess once there is more than one, and never creates an org as a side
    effect of an upload.  This whole function goes away when auth lands and
    the org comes from the caller's identity.
    """
    if org_id:
        organization = db.query(Organization).filter(Organization.id == org_id).first()
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {org_id} not found")
        return organization

    organizations = db.query(Organization).limit(2).all()
    if not organizations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No organization exists. Create one, then pass org_id.",
        )
    if len(organizations) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Multiple organizations exist; pass org_id explicitly.",
        )
    return organizations[0]


class UploadTooLargeError(Exception):
    """The upload exceeded MAX_UPLOAD_BYTES and was abandoned mid-stream."""

    def __init__(self, written: int) -> None:
        super().__init__(f"Upload exceeded {MAX_UPLOAD_BYTES} bytes")
        self.written = written


async def _store_recording(upload: UploadFile, meeting_id: str, suffix: str) -> Path:
    """Stream the upload to the recordings directory, named by meeting id.

    The size ceiling is enforced *during* the stream, not from a Content-Length
    header: the header is client-supplied and a chunked upload need not send
    one, so trusting it would leave the cap trivially bypassable.
    """
    destination = config.get_recordings_dir() / f"{meeting_id}{suffix}"
    written = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise UploadTooLargeError(written)
                handle.write(chunk)
    except Exception:
        # Don't leave a half-written file behind for the pipeline to choke on.
        destination.unlink(missing_ok=True)
        raise
    return destination


@router.post(
    "/upload",
    response_model=MeetingDetail,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_upload)],
)
async def upload_meeting(
    file: UploadFile = File(...),
    title: str = Form(...),
    org_id: str | None = Form(None),
    language: str | None = Form(None),
    consent_confirmed: bool = Form(False),
    consent_note: str | None = Form(None, max_length=500),
    db: Session = Depends(get_db),
) -> Meeting:
    """Accept a recording and queue it for processing.

    Refused unless ``consent_confirmed`` is true: the audio and transcript go to
    a third-party API, and recording people who did not agree is the one
    failure no later control can undo.

    Returns 202 with the meeting in ``processing`` as soon as the bytes are on
    disk. Transcription runs in the background — a meeting recording takes
    minutes to transcribe, which is far longer than any client will hold a
    request open.
    """
    if not consent_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Confirm that everyone in the recording consented to it (consent_confirmed=true).",
        )
    suffix = _validate_audio_suffix(file.filename)
    organization = _resolve_org(db, org_id)

    meeting = Meeting(
        org_id=organization.id,
        title=title,
        status=MeetingStatus.PROCESSING.value,
        source=MeetingSource.UPLOAD.value,
        language=language or "en",
        consent_confirmed_at=datetime.now(UTC),
        consent_note=(consent_note or "").strip() or None,
    )
    db.add(meeting)
    db.flush()  # assign the id that names the file on disk

    try:
        stored = await _store_recording(file, meeting.id, suffix)
    except UploadTooLargeError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Recording exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit. "
                "Split the recording or raise MEETINGOS_MAX_UPLOAD_BYTES."
            ),
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to store upload for meeting %s", meeting.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not store the uploaded recording.",
        ) from exc

    meeting.recording_path = config.to_storage_path(stored)
    db.commit()
    db.refresh(meeting)

    schedule_processing(meeting.id)
    logger.info("Queued meeting %s (%s) for processing", meeting.id, stored.name)
    return meeting


@router.get("", response_model=list[MeetingSummary])
async def list_meetings(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    meeting_status: str | None = Query(None, alias="status"),
) -> list[Meeting]:
    """List meetings, newest first.

    Returns ``[]`` on an empty database rather than 404 — an empty collection
    is a valid collection.
    """
    query = db.query(Meeting)
    if meeting_status:
        query = query.filter(Meeting.status == meeting_status)
    return query.order_by(Meeting.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{meeting_id}", response_model=MeetingDetail)
async def get_meeting(meeting_id: str, db: Session = Depends(get_db)) -> Meeting:
    """Fetch one meeting by id."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Meeting {meeting_id} not found")
    return meeting


@router.get("/{meeting_id}/intelligence", response_model=MeetingIntelligence)
async def get_meeting_intelligence(meeting_id: str, db: Session = Depends(get_db)) -> MeetingIntelligence:
    """Everything extracted from a meeting, with its provenance.

    Low-confidence and unsupported items are included, not filtered out. The
    verifier's job is to label them; deciding whether to act on a weak claim
    belongs to whoever is reading, and hiding them here would mean the review
    that catches a bad extraction never happens.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Meeting {meeting_id} not found")

    cited_segments = {
        segment.id: segment for segment in db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).all()
    }

    def _items(model, title_attr: str) -> list[ExtractedItem]:
        rows = db.query(model).filter_by(meeting_id=meeting_id).all()
        items = []
        for row in rows:
            segment = cited_segments.get(row.source_segment_id)
            items.append(
                ExtractedItem(
                    id=row.id,
                    title=getattr(row, title_attr),
                    description=getattr(row, "description", None),
                    status=getattr(row, "status", None),
                    severity=getattr(row, "severity", None),
                    priority=getattr(row, "priority", None),
                    source_segment_id=row.source_segment_id,
                    source_segment_text=segment.text if segment else None,
                    source_start_ms=segment.start_ms if segment else None,
                    source_end_ms=segment.end_ms if segment else None,
                    extraction_confidence=row.extraction_confidence,
                    verification_status=row.verification_status,
                    verification_score=row.verification_score,
                    supersedes_id=getattr(row, "supersedes_id", None),
                )
            )
        return items

    topics = db.query(Topic).filter_by(meeting_id=meeting_id).order_by(Topic.start_ms).all()

    # A topic longer than the extraction cap means the counts are a floor.
    # Recomputed here rather than stored, so it stays true if segments change.
    from ..meetings.intelligence import MAX_SEGMENTS_PER_CALL

    truncated = any(
        db.query(TranscriptSegment)
        .filter(
            TranscriptSegment.meeting_id == meeting_id,
            TranscriptSegment.end_ms > (topic.start_ms or 0),
            TranscriptSegment.start_ms < (topic.end_ms or 2**31),
        )
        .count()
        > MAX_SEGMENTS_PER_CALL
        for topic in topics
    )

    return MeetingIntelligence(
        meeting_id=meeting_id,
        meeting_status=meeting.status,
        extraction_truncated=truncated,
        topics=[
            TopicOut(
                id=topic.id,
                label=topic.label,
                start_ms=topic.start_ms,
                end_ms=topic.end_ms,
                salience=topic.salience,
                keywords=topic.keywords or [],
            )
            for topic in topics
        ],
        decisions=_items(Decision, "title"),
        action_items=_items(ActionItem, "title"),
        risks=_items(Risk, "title"),
        commitments=_items(Commitment, "text"),
    )


@router.get("/{meeting_id}/transcript", response_model=list[TranscriptSegmentOut])
async def get_meeting_transcript(meeting_id: str, db: Session = Depends(get_db)) -> list[TranscriptSegmentOut]:
    """The full transcript in speaking order.

    Separate from ``/intelligence`` because it is the bulky half: a reader
    opening the Decisions tab should not pay for the whole transcript, and the
    Transcript tab should not re-fetch every extracted item.
    """
    if db.query(Meeting).filter(Meeting.id == meeting_id).first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Meeting {meeting_id} not found")

    labels = {speaker.id: speaker.display_label for speaker in db.query(Speaker).filter_by(meeting_id=meeting_id).all()}
    segments = db.query(TranscriptSegment).filter_by(meeting_id=meeting_id).order_by(TranscriptSegment.sequence).all()
    return [
        TranscriptSegmentOut(
            id=segment.id,
            sequence=segment.sequence,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            speaker_label=labels.get(segment.speaker_id),
            text=segment.text,
        )
        for segment in segments
    ]


@router.get("/{meeting_id}/audio")
async def get_meeting_audio(meeting_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Stream the stored recording so the waveform has something to draw.

    The path is read from the meeting row and resolved through ``config``;
    the client never supplies a path, so there is nothing here to traverse.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Meeting {meeting_id} not found")
    if not meeting.recording_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id} has no stored recording.",
        )

    path = config.resolve_storage_path(meeting.recording_path)
    if path is None or not path.is_file():
        logger.warning("Recording for meeting %s missing at %s", meeting_id, path)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The stored recording is no longer on disk.",
        )
    return FileResponse(path, media_type="audio/wav", filename=path.name)


class PrepareRequest(BaseModel):
    """Context for an upcoming meeting. At least one of the two is required."""

    attendee_ids: list[str] = []
    project: str | None = None
    org_id: str | None = None
    summarise: bool = False


class BriefItemOut(BaseModel):
    """One brief line, always carrying the citation it came from."""

    kind: str
    text: str
    detail: str | None = None
    owner_name: str | None = None
    due_date: str | None = None
    overdue: bool = False
    days_overdue: int | None = None
    status: str | None = None
    meeting_id: str | None = None
    meeting_title: str | None = None
    evidence_id: str | None = None
    start_ms: int | None = None


class BriefOut(BaseModel):
    """Assembled preparation material. Every entry traces to Evidence."""

    project: str | None = None
    attendee_ids: list[str] = []
    attendee_names: list[str] = []
    open_commitments: list[BriefItemOut] = []
    unresolved_decisions: list[BriefItemOut] = []
    recent_changes: list[BriefItemOut] = []
    last_related_meeting_id: str | None = None
    last_related_meeting_title: str | None = None
    item_count: int = 0
    # True when there is genuinely no prior history — said plainly rather than
    # padded with generalities.
    is_empty: bool = False
    notes: list[str] = []
    summary: str | None = None


# Registered before the "/{meeting_id}" routes: "prepare" is a literal path
# segment, and a parameterised route declared first would swallow it.
class MinuteLineOut(BaseModel):
    """One minuted line, with the citation behind it."""

    text: str
    detail: str | None = None
    evidence_id: str | None = None
    start_ms: int | None = None
    verification_status: str | None = None


class MinuteSectionOut(BaseModel):
    heading: str
    lines: list[MinuteLineOut] = []


class MinutesOut(BaseModel):
    """Board minutes assembled from extracted items."""

    meeting_id: str
    meeting_title: str
    meeting_date: str | None = None
    is_board_meeting: bool = False
    sections: list[MinuteSectionOut] = []
    # Extracted but untraceable to a transcript segment. Kept separate so a
    # reader can tell what is backed by the recording and what is not.
    uncited: list[MinuteLineOut] = []
    line_count: int = 0
    cited_line_count: int = 0
    notes: list[str] = []
    markdown: str = ""
    summary: str | None = None


@router.post("/{meeting_id}/minutes", response_model=MinutesOut)
async def generate_minutes(
    meeting_id: str,
    summarise: bool = Query(False, description="Also generate a prose summary."),
    db: Session = Depends(get_db),
) -> MinutesOut:
    """Assemble board minutes from this meeting's extracted items.

    Deterministic: every line is an existing row carried through with its
    Evidence id. ``summarise=true`` adds a paragraph generated *from* the
    assembled document, which cannot add a resolution nobody passed.
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Meeting {meeting_id} not found")

    minutes = render_minutes(db, meeting_id)
    if summarise:
        minutes.polished = await polish_minutes(minutes)

    def line(entry) -> MinuteLineOut:
        return MinuteLineOut(
            text=entry.text,
            detail=entry.detail,
            evidence_id=entry.evidence_id,
            start_ms=entry.start_ms,
            verification_status=entry.verification_status,
        )

    return MinutesOut(
        meeting_id=meeting_id,
        meeting_title=minutes.meeting_title,
        meeting_date=minutes.meeting_date,
        is_board_meeting=is_board_meeting(db, meeting),
        sections=[
            MinuteSectionOut(heading=s.heading, lines=[line(entry) for entry in s.lines]) for s in minutes.sections
        ],
        uncited=[line(entry) for entry in minutes.uncited],
        line_count=minutes.line_count,
        cited_line_count=minutes.cited_line_count,
        notes=minutes.notes,
        markdown=to_markdown(minutes),
        summary=minutes.polished,
    )


@router.post("/templates/board", status_code=status.HTTP_201_CREATED)
async def create_board_template(org_id: str | None = Query(None), db: Session = Depends(get_db)) -> dict:
    """Ensure the board template exists for this org. Idempotent."""
    organization = _resolve_org(db, org_id)
    template = ensure_board_template(db, organization.id)
    return {"id": template.id, "name": template.name, "org_id": template.org_id}


@router.post("/prepare", response_model=BriefOut)
async def prepare_meeting(payload: PrepareRequest, db: Session = Depends(get_db)) -> BriefOut:
    """Assemble a preparation brief for an upcoming meeting.

    Assembly is deterministic: every line is an existing row carried through
    with its Evidence id. ``summarise=true`` adds a prose rendering generated
    from that assembled material, which can never add an item to it.
    """
    if not payload.attendee_ids and not payload.project:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide attendee_ids, a project, or both.",
        )

    organization = _resolve_org(db, payload.org_id)
    brief = await assemble_brief(
        db,
        org_id=organization.id,
        attendee_ids=payload.attendee_ids,
        project=payload.project,
    )
    summary = await write_brief(brief) if payload.summarise else None

    return BriefOut(
        project=brief.project,
        attendee_ids=brief.attendee_ids,
        attendee_names=brief.attendee_names,
        open_commitments=[
            BriefItemOut(
                kind=item.kind,
                text=item.text,
                owner_name=item.owner_name,
                due_date=item.due_date,
                overdue=item.overdue,
                days_overdue=item.days_overdue,
                status=item.status,
                meeting_id=item.meeting_id,
                meeting_title=item.meeting_title,
                evidence_id=item.evidence_id,
                start_ms=item.start_ms,
            )
            for item in brief.open_commitments
        ],
        unresolved_decisions=[
            BriefItemOut(
                kind="decision",
                text=d.title,
                status=d.status,
                meeting_id=d.meeting_id,
                meeting_title=d.meeting_title,
                evidence_id=d.evidence_id,
                start_ms=d.start_ms,
            )
            for d in brief.unresolved_decisions
        ],
        recent_changes=[
            BriefItemOut(
                kind="change",
                text=c.field_name,
                detail=f"{c.old_value} -> {c.new_value}",
                meeting_id=c.meeting_id,
                meeting_title=c.meeting_title,
                evidence_id=c.evidence_id,
                start_ms=c.start_ms,
            )
            for c in brief.recent_changes
        ],
        last_related_meeting_id=brief.last_related_meeting_id,
        last_related_meeting_title=brief.last_related_meeting_title,
        item_count=brief.item_count,
        is_empty=brief.is_empty,
        notes=brief.notes,
        summary=summary,
    )


@router.post(
    "/{meeting_id}/ask",
    response_model=AskResponse,
    dependencies=[Depends(limit_ask)],
)
async def ask_meeting(meeting_id: str, payload: AskRequest) -> AskResponse:
    """Answer a question about this meeting from its transcript.

    Read-only. The copilot retrieves segments and writes prose; it invokes no
    tools and changes nothing about the meeting. The response carries the
    citations, and the flags saying whether the answer is grounded, so the
    client can refuse to present an ungrounded answer as fact.
    """
    try:
        result = await answer_question(meeting_id, payload.question)
    except CopilotError as exc:
        message = str(exc)
        # "not found" is the caller's mistake; everything else is ours.
        code = status.HTTP_404_NOT_FOUND if "not found" in message.lower() else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code, detail=message) from exc

    return AskResponse(
        meeting_id=result.meeting_id,
        question=result.question,
        answer=result.answer,
        citations=[
            CitationOut(
                segment_id=citation.segment_id,
                start_ms=citation.start_ms,
                end_ms=citation.end_ms,
                speaker_label=citation.speaker_label,
                text=citation.text,
            )
            for citation in result.citations
        ],
        not_discussed=result.not_discussed,
        unsupported=result.unsupported,
        segments_considered=result.segments_considered,
        segments_retrieved=result.segments_retrieved,
    )


@router.post("", response_model=MeetingDetail, status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def create_meeting(payload: MeetingCreate, db: Session = Depends(get_db)) -> MeetingDetail:
    """Create a meeting. Blocked on org resolution and the audio intake path."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=NOT_IMPLEMENTED_DETAIL)


@router.patch("/{meeting_id}", response_model=MeetingDetail, status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def update_meeting(meeting_id: str, payload: MeetingUpdate, db: Session = Depends(get_db)) -> MeetingDetail:
    """Update a meeting."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=NOT_IMPLEMENTED_DETAIL)


@router.delete("/{meeting_id}", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def delete_meeting(meeting_id: str, db: Session = Depends(get_db)) -> None:
    """Delete a meeting and its transcript. Must honour org retention policy."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=NOT_IMPLEMENTED_DETAIL)
