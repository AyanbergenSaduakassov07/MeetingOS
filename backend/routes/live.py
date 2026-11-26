"""Live captions API.

Host (API key, like every /api route): start, end, audio WebSocket, viewer links.
Viewer (/api/live/view/*): snapshot + SSE stream, open to a valid join token
or the API key. The auth middleware skips /api/live/view/ and the audio
WebSocket, so both check access here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import auth
from ..database import Meeting, MeetingSource, MeetingStatus, TranscriptSegment, get_db, new_session
from ..database.models import LiveSession, SegmentTranslation
from ..live import access
from ..live.asr import get_asr
from ..live.eventlog import CLOSED
from ..live.languages import codes, languages
from ..live.session import get_runtime, start_runtime
from ..live.translate import get_translator
from .limits import limit_live_view, limit_upload
from .meetings import _resolve_org

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])

MAX_FRAME_BYTES = 64 * 1024  # 2 s of 16 kHz PCM16; the client sends ~100 ms frames
KEEPALIVE_S = 15.0
RECHECK_S = 15.0  # a revoked or expired link stops streaming within this long


class StartIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    consent_confirmed: bool = False
    source_language: str | None = None
    org_id: str | None = None


class StartOut(BaseModel):
    session_id: str
    meeting_id: str
    viewer_token: str
    asr: str
    translator: str | None


class LinkOut(BaseModel):
    viewer_token: str


def _validate_lang(lang: str | None) -> str | None:
    if lang and lang not in codes():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported language '{lang}'.")
    return lang or None


def _session_or_404(db: Session, session_id: str) -> LiveSession:
    row = db.query(LiveSession).filter_by(id=session_id).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")
    return row


def _viewer_access(request: Request, session_id: str, t: str | None, db: Session) -> LiveSession:
    row = _session_or_404(db, session_id)
    if not (auth.has_access(dict(request.scope["headers"])) or access.token_valid(db, session_id, t)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This viewer link is invalid, expired or revoked.")
    return row


@router.get("/languages")
async def list_languages() -> list[dict]:
    return languages()


@router.post("/sessions", response_model=StartOut, status_code=201, dependencies=[Depends(limit_upload)])
async def start_session(body: StartIn, db: Session = Depends(get_db)) -> StartOut:
    if not body.consent_confirmed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Confirm that everyone in the meeting agreed to live captioning (consent_confirmed=true).",
        )
    source = _validate_lang(body.source_language)
    organization = _resolve_org(db, body.org_id)
    now = datetime.now(UTC)
    meeting = Meeting(
        org_id=organization.id,
        title=body.title,
        status=MeetingStatus.RECORDING.value,
        source=MeetingSource.LIVE.value,
        language=source,
        actual_start=now,
        consent_confirmed_at=now,
    )
    db.add(meeting)
    db.flush()
    row = LiveSession(meeting_id=meeting.id, org_id=organization.id, source_language=source)
    db.add(row)
    db.commit()
    try:
        asr, translator = get_asr(), get_translator()
        await start_runtime(row, asr, translator)
    except Exception as exc:
        logger.exception("Could not start live session %s", row.id)
        db.delete(row)
        db.delete(meeting)
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Live captioning is unavailable: {exc}") from exc
    token = access.issue_token(db, row.id)
    return StartOut(
        session_id=row.id, meeting_id=meeting.id, viewer_token=token, asr=asr.name, translator=translator.name
    )


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str, db: Session = Depends(get_db)) -> dict:
    row = _session_or_404(db, session_id)
    runtime = get_runtime(session_id)
    if runtime is not None:
        await runtime.end()
    return {"session_id": session_id, "meeting_id": row.meeting_id, "state": "ended"}


@router.post("/sessions/{session_id}/links", response_model=LinkOut)
async def new_link(session_id: str, db: Session = Depends(get_db)) -> LinkOut:
    _session_or_404(db, session_id)
    return LinkOut(viewer_token=access.issue_token(db, session_id))


@router.post("/sessions/{session_id}/links/revoke")
async def revoke_links(session_id: str, db: Session = Depends(get_db)) -> dict:
    _session_or_404(db, session_id)
    return {"revoked": access.revoke_all(db, session_id)}


@router.websocket("/sessions/{session_id}/audio")
async def audio_ingest(websocket: WebSocket, session_id: str) -> None:
    # The HTTP auth middleware does not see WebSockets: check here, before accepting.
    if not auth.has_access(dict(websocket.scope["headers"])):
        await websocket.close(code=4401)
        return
    runtime = get_runtime(session_id)
    if runtime is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    try:
        while not runtime.ending:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is None:
                continue
            if len(data) > MAX_FRAME_BYTES:
                await websocket.close(code=1009)
                break
            await runtime.ingest(data)
    except WebSocketDisconnect:
        pass  # the host may reconnect; ending is explicit


@router.get("/view/{session_id}/snapshot", dependencies=[Depends(limit_live_view)])
async def snapshot(
    request: Request,
    session_id: str,
    t: str | None = Query(None),
    lang: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    row = _viewer_access(request, session_id, t, db)
    lang = _validate_lang(lang)
    runtime = get_runtime(session_id)
    last_seq = runtime.log.seq if runtime else 0  # taken before the read, so nothing falls between
    meeting = db.query(Meeting).filter_by(id=row.meeting_id).first()
    segments = (
        db.query(TranscriptSegment).filter_by(meeting_id=row.meeting_id).order_by(TranscriptSegment.sequence).all()
    )
    translated: dict[str, str] = {}
    if lang and segments:
        rows = (
            db.query(SegmentTranslation)
            .filter(SegmentTranslation.segment_id.in_([s.id for s in segments]), SegmentTranslation.target_lang == lang)
            .order_by(SegmentTranslation.revision)
            .all()
        )
        translated = {r.segment_id: r.text for r in rows}  # highest revision wins
    return {
        "session_id": session_id,
        "meeting_id": row.meeting_id,
        "title": meeting.title if meeting else "",
        "state": row.state if runtime is None else "live",
        "source_language": row.source_language,
        "last_seq": last_seq,
        "segments": [
            {
                "segment_id": s.id,
                "sequence": s.sequence,
                "text": s.text,
                "language": s.language,
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "translation": translated.get(s.id),
            }
            for s in segments
        ],
    }


def _wanted(event, lang: str | None) -> bool:
    if event.type == "translation.final":
        return event.data.get("lang") == lang
    if event.type == "translation.failed":
        return lang in event.data.get("langs", [])
    return True


def _token_still_valid(session_id: str, t: str | None) -> bool:
    db = new_session()
    try:
        return access.token_valid(db, session_id, t)
    finally:
        db.close()


async def _stream(runtime, after: int, lang: str | None, recheck=None):
    backlog, queue = runtime.log.subscribe(after)
    runtime.join(lang)
    checked = time.monotonic()
    try:
        for event in backlog:
            if _wanted(event, lang):
                yield event.sse()
        while True:
            if recheck is not None and time.monotonic() - checked > RECHECK_S:
                if not recheck():
                    return
                checked = time.monotonic()
            try:
                event = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if event is CLOSED:
                return
            if _wanted(event, lang):
                yield event.sse()
    finally:
        runtime.log.unsubscribe(queue)
        runtime.leave(lang)


@router.get("/view/{session_id}/events")
async def events(
    request: Request,
    session_id: str,
    t: str | None = Query(None),
    lang: str | None = Query(None),
    after: int = Query(0, ge=0),
    last_event_id: str | None = Header(None),
) -> StreamingResponse:
    # Own short session: a Depends(get_db) connection stays checked out until the stream ends.
    db = new_session()
    try:
        _viewer_access(request, session_id, t, db)
    finally:
        db.close()
    keyed = auth.has_access(dict(request.scope["headers"]))
    recheck = None if keyed else (lambda: _token_still_valid(session_id, t))
    lang = _validate_lang(lang)
    runtime = get_runtime(session_id)
    if runtime is None:
        raise HTTPException(status.HTTP_410_GONE, "This live session has ended.")
    if last_event_id and last_event_id.isdigit():
        after = int(last_event_id)  # EventSource reconnect resumes from the last event it saw
    return StreamingResponse(
        _stream(runtime, after, lang, recheck),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
