"""Live captions end to end with the stub recognizer, plus access control (PLAN §5.2)."""

from __future__ import annotations

import asyncio
import time
import wave

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend import config
from backend.app import create_app
from backend.auth import API_KEY_ENV
from backend.database import Meeting, Organization, TranscriptSegment
from backend.database.models import LiveJoinToken, LiveSession, SegmentTranslation
from backend.live import session as live_session
from backend.meetings import retention
from backend.routes import live as live_routes

KEY = "test-key-0123456789abcdef"
SECOND = b"\x00\x00" * 16_000  # 1 s of silent 16 kHz PCM16


class FakeTranslator:
    name = "fake"

    def __init__(self):
        self.calls = []

    async def translate(self, text, *, source, targets, context):
        self.calls.append((text, tuple(targets)))
        return {t: f"[{t}] {text}" for t in targets}


class FailingTranslator(FakeTranslator):
    async def translate(self, text, *, source, targets, context):
        raise RuntimeError("provider down")


@pytest.fixture
def live(monkeypatch, data_dir):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setenv("MEETINGOS_LIVE_ASR", "stub")
    translator = FakeTranslator()
    monkeypatch.setattr(live_routes, "get_translator", lambda: translator)
    with TestClient(create_app()) as client:
        yield client, translator


def _start(client, **extra):
    body = {"title": "Standup", "consent_confirmed": True, **extra}
    return client.post("/api/live/sessions", json=body)


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def test_refuses_to_start_without_consent(live):
    client, _ = live
    assert client.post("/api/live/sessions", json={"title": "x"}).status_code == 422


def test_rejects_unknown_source_language(live):
    client, _ = live
    assert _start(client, source_language="xx").status_code == 400


def test_audio_becomes_stored_captions_and_translations(live, db):
    client, translator = live
    started = _start(client, source_language="en").json()
    sid = started["session_id"]
    live_session.get_runtime(sid).join("ru")  # a viewer with Russian open

    with client.websocket_connect(f"/api/live/sessions/{sid}/audio") as ws:
        for _ in range(7):
            ws.send_bytes(SECOND)

    def translated():
        snap = client.get(f"/api/live/view/{sid}/snapshot", params={"lang": "ru"}).json()
        return snap if len(snap["segments"]) == 2 and all(s["translation"] for s in snap["segments"]) else None

    snap = _wait(translated)
    assert [s["text"] for s in snap["segments"]] == ["Test caption 1.", "Test caption 2."]
    assert snap["segments"][0]["translation"] == "[ru] Test caption 1."
    assert snap["last_seq"] > 0
    assert all(targets == ("ru",) for _, targets in translator.calls), "translated into a language nobody opened"

    assert client.post(f"/api/live/sessions/{sid}/end").status_code == 200
    db.expire_all()
    meeting = db.get(Meeting, started["meeting_id"])
    assert meeting.source == "live" and meeting.recording_path and meeting.audio_duration_seconds == 7
    assert db.query(TranscriptSegment).filter_by(meeting_id=meeting.id, is_final=True).count() == 2
    assert db.query(LiveSession).filter_by(id=sid).one().state == "ended"
    assert client.get(f"/api/live/view/{sid}/events").status_code == 410


def test_failed_translation_keeps_the_source_caption(monkeypatch, live):
    client, _ = live
    monkeypatch.setattr(live_routes, "get_translator", lambda: FailingTranslator())
    sid = _start(client).json()["session_id"]
    runtime = live_session.get_runtime(sid)
    runtime.join("de")
    with client.websocket_connect(f"/api/live/sessions/{sid}/audio") as ws:
        for _ in range(4):
            ws.send_bytes(SECOND)
    failed = _wait(lambda: [e for e in runtime.log._ring if e.type == "translation.failed"])
    assert failed[0].data["langs"] == ["de"]
    snap = client.get(f"/api/live/view/{sid}/snapshot", params={"lang": "de"}).json()
    assert snap["segments"][0]["text"] == "Test caption 1." and snap["segments"][0]["translation"] is None
    client.post(f"/api/live/sessions/{sid}/end")


def test_language_channel_stays_warm_for_a_grace_period(live):
    client, _ = live
    runtime = live_session.get_runtime(_start(client).json()["session_id"])
    runtime.join("kk")
    runtime.leave("kk")
    assert runtime.active_languages() == {"kk"}
    runtime._left_at["kk"] -= live_session.GRACE_S + 1
    assert runtime.active_languages() == set()


def test_opening_a_language_translates_recent_earlier_lines_once(live):
    client, translator = live
    sid = _start(client, source_language="en").json()["session_id"]
    with client.websocket_connect(f"/api/live/sessions/{sid}/audio") as ws:
        for _ in range(7):
            ws.send_bytes(SECOND)
    _wait(lambda: len(client.get(f"/api/live/view/{sid}/snapshot").json()["segments"]) == 2)
    assert translator.calls == []  # nobody watching in another language yet

    runtime = live_session.get_runtime(sid)
    client.portal.call(runtime.join, "ru")  # join runs on the event loop in production
    client.portal.call(runtime.join, "ru")  # a second viewer must not translate again

    def translated():
        snap = client.get(f"/api/live/view/{sid}/snapshot", params={"lang": "ru"}).json()
        return all(s["translation"] for s in snap["segments"])

    _wait(translated)
    assert sorted(text for text, _ in translator.calls) == ["Test caption 1.", "Test caption 2."]


# -- access control ----------------------------------------------------------


@pytest.fixture
def keyed(monkeypatch, data_dir):
    monkeypatch.setenv(API_KEY_ENV, KEY)
    monkeypatch.setenv("MEETINGOS_LIVE_ASR", "stub")
    monkeypatch.setattr(live_routes, "get_translator", FakeTranslator)
    with TestClient(create_app()) as client:
        yield client


AUTH = {"Authorization": f"Bearer {KEY}"}


def test_host_routes_need_the_key(keyed):
    assert _start(keyed).status_code == 401
    started = keyed.post("/api/live/sessions", json={"title": "x", "consent_confirmed": True}, headers=AUTH)
    assert started.status_code == 201
    assert keyed.post(f"/api/live/sessions/{started.json()['session_id']}/end").status_code == 401


def test_audio_websocket_rejects_missing_or_viewer_credentials(keyed):
    started = keyed.post("/api/live/sessions", json={"title": "x", "consent_confirmed": True}, headers=AUTH).json()
    sid, token = started["session_id"], started["viewer_token"]
    for url in (f"/api/live/sessions/{sid}/audio", f"/api/live/sessions/{sid}/audio?t={token}"):
        with pytest.raises(WebSocketDisconnect) as closed, keyed.websocket_connect(url) as ws:
            ws.receive_bytes()
        assert closed.value.code == 4401
    with keyed.websocket_connect(f"/api/live/sessions/{sid}/audio", headers=AUTH) as ws:
        ws.send_bytes(SECOND)


def test_viewer_token_is_scoped_expiring_and_revocable(keyed, db):
    first = keyed.post("/api/live/sessions", json={"title": "a", "consent_confirmed": True}, headers=AUTH).json()
    other = keyed.post("/api/live/sessions", json={"title": "b", "consent_confirmed": True}, headers=AUTH).json()
    sid, token = first["session_id"], first["viewer_token"]
    snap = f"/api/live/view/{sid}/snapshot"

    assert keyed.get(snap).status_code == 401
    assert keyed.get(snap, params={"t": "nope"}).status_code == 401
    assert keyed.get(snap, params={"t": token}).status_code == 200
    assert keyed.get(snap, headers=AUTH).status_code == 200, "the host uses the same view with the key"
    assert keyed.get(f"/api/live/view/{other['session_id']}/snapshot", params={"t": token}).status_code == 401

    assert keyed.post(f"/api/live/sessions/{sid}/links/revoke", headers=AUTH).json()["revoked"] == 1
    assert keyed.get(snap, params={"t": token}).status_code == 401

    fresh = keyed.post(f"/api/live/sessions/{sid}/links", headers=AUTH).json()["viewer_token"]
    assert keyed.get(snap, params={"t": fresh}).status_code == 200
    row = db.query(LiveJoinToken).filter_by(revoked_at=None, session_id=sid).one()
    assert fresh not in row.token_hash, "raw token stored"
    from datetime import UTC, datetime, timedelta

    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert keyed.get(snap, params={"t": fresh}).status_code == 401


def test_no_provider_secret_in_viewer_responses(monkeypatch, keyed):
    monkeypatch.setenv("GOOGLE_TRANSLATE_API_KEY", "sk-secret-value")
    started = keyed.post("/api/live/sessions", json={"title": "x", "consent_confirmed": True}, headers=AUTH).json()
    body = keyed.get(f"/api/live/view/{started['session_id']}/snapshot", params={"t": started["viewer_token"]}).text
    assert "sk-secret-value" not in body and "sk-secret-value" not in str(started)


# -- restart and retention ---------------------------------------------------


def test_restart_marks_running_sessions_interrupted(data_dir, db, monkeypatch):
    org = Organization(name="Org", slug="org")
    db.add(org)
    db.flush()
    meeting = Meeting(org_id=org.id, title="m", status="recording", source="live")
    db.add(meeting)
    db.flush()
    db.add(LiveSession(meeting_id=meeting.id, org_id=org.id, state="live"))
    db.commit()
    finalized = []
    monkeypatch.setattr(live_session, "_spawn", lambda coro: (finalized.append(coro), coro.close()))

    assert live_session.recover_interrupted() == 1
    db.expire_all()
    assert db.query(LiveSession).one().state == "interrupted"
    assert db.get(Meeting, meeting.id).status == "analyzing"


def test_restart_repairs_and_links_the_half_written_recording(data_dir, db, monkeypatch):
    org = Organization(name="Org", slug="org")
    db.add(org)
    db.flush()
    meeting = Meeting(org_id=org.id, title="m", status="recording", source="live")
    db.add(meeting)
    db.flush()
    db.add(LiveSession(meeting_id=meeting.id, org_id=org.id, state="live"))
    db.commit()
    wav = config.get_recordings_dir() / f"{meeting.id}.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    wav.write_bytes(b"\0" * 44 + SECOND)  # header never finalised by the crash
    monkeypatch.setattr(live_session, "_spawn", lambda coro: coro.close())

    live_session.recover_interrupted()

    db.expire_all()
    recovered = db.get(Meeting, meeting.id)
    assert recovered.recording_path and recovered.audio_duration_seconds == 1
    with wave.open(str(wav)) as w:
        assert w.getnframes() == 16_000


def test_storage_failure_still_ends_the_session_cleanly(monkeypatch, live, db):
    client, _ = live
    started = _start(client, source_language="en").json()
    sid = started["session_id"]

    def broken(*args):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(live_session, "_store_segment", broken)
    with client.websocket_connect(f"/api/live/sessions/{sid}/audio") as ws:
        for _ in range(4):
            ws.send_bytes(SECOND)

    assert client.post(f"/api/live/sessions/{sid}/end").status_code == 200
    db.expire_all()
    assert db.query(LiveSession).filter_by(id=sid).one().state == "ended"
    assert db.get(Meeting, started["meeting_id"]).status != "recording"
    assert live_session.get_runtime(sid) is None


def test_abandoned_session_ends_itself(monkeypatch, live, db):
    client, _ = live
    monkeypatch.setattr(live_session, "IDLE_END_S", 0.0)
    sid = _start(client, source_language="en").json()["session_id"]

    _wait(lambda: live_session.get_runtime(sid) is None)
    db.expire_all()
    assert db.query(LiveSession).filter_by(id=sid).one().state == "ended"


def test_revoked_link_stops_an_open_stream(monkeypatch):
    class Log:
        def subscribe(self, after):
            return [], asyncio.Queue()

        def unsubscribe(self, queue):
            pass

    class Runtime:
        log = Log()
        left = False

        def join(self, lang):
            pass

        def leave(self, lang):
            Runtime.left = True

    monkeypatch.setattr(live_routes, "RECHECK_S", -1.0)

    async def drain():
        return [chunk async for chunk in live_routes._stream(Runtime(), 0, None, recheck=lambda: False)]

    assert asyncio.run(asyncio.wait_for(drain(), 2)) == []
    assert Runtime.left


def test_retention_purge_removes_live_rows(data_dir, db):
    from datetime import UTC, datetime, timedelta

    org = Organization(name="Org", slug="org", retention_days=30)
    db.add(org)
    db.flush()
    meeting = Meeting(
        org_id=org.id, title="old", status="completed", source="live", created_at=datetime.now(UTC) - timedelta(days=90)
    )
    db.add(meeting)
    db.flush()
    seg = TranscriptSegment(meeting_id=meeting.id, sequence=1, start_ms=0, end_ms=1, text="hi")
    live = LiveSession(meeting_id=meeting.id, org_id=org.id, state="ended")
    db.add_all([seg, live])
    db.flush()
    db.add(SegmentTranslation(segment_id=seg.id, target_lang="ru", text="привет"))
    db.add(LiveJoinToken(session_id=live.id, token_hash="h", expires_at=datetime.now(UTC)))
    db.commit()

    retention.purge_expired(db, commit=True)
    for model in (Meeting, TranscriptSegment, SegmentTranslation, LiveSession, LiveJoinToken):
        assert db.query(model).count() == 0, f"{model.__name__} outlived its meeting"
