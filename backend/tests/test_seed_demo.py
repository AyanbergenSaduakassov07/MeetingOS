"""The demo seed is what the CI browser tests stand on; keep its shape pinned."""

from __future__ import annotations

import wave

import pytest

from backend import config, database
from backend.database.models import Commitment, Decision, Meeting
from backend.meetings.commitments import compute_overdue
from backend.seed_demo import seed


@pytest.fixture
def restore_data_dir():
    previous = config.get_data_dir()
    yield
    config.set_data_dir(previous)
    database.init_db()


def test_seed_builds_a_playable_cited_meeting(tmp_path, restore_data_dir):
    meeting_id = seed(tmp_path)

    db = database.new_session()
    try:
        meeting = db.get(Meeting, meeting_id)
        assert meeting.status == "completed"
        with wave.open(str(config.resolve_storage_path(meeting.recording_path))) as audio:
            assert audio.getnframes() / audio.getframerate() == meeting.audio_duration_seconds

        decisions = db.query(Decision).filter_by(meeting_id=meeting_id).all()
        statuses = {d.verification_status for d in decisions}
        assert statuses == {"verified", "low_confidence"}
        assert all(d.source_segment_id for d in db.query(Decision).all())  # every meeting's decisions are cited

        overdue = [c for c in db.query(Commitment).all() if compute_overdue("commitment", c.status, c.due_date)[0]]
        assert len(overdue) == 1
    finally:
        db.close()


def test_seed_opens_with_three_recorded_meetings(tmp_path, restore_data_dir):
    robotics_id = seed(tmp_path)

    db = database.new_session()
    try:
        meetings = db.query(Meeting).order_by(Meeting.created_at.desc()).all()
        assert len(meetings) == 3
        assert meetings[0].id == robotics_id  # the browser suites open the newest meeting
        assert any("Токаев" in m.title for m in meetings)
        for meeting in meetings:
            assert meeting.status == "completed"
            assert config.resolve_storage_path(meeting.recording_path).stat().st_size > 0
            assert meeting.segments
            assert db.query(Decision).filter_by(meeting_id=meeting.id).count()
    finally:
        db.close()


def test_seed_refuses_a_non_empty_data_dir(tmp_path, restore_data_dir):
    seed(tmp_path)
    with pytest.raises(SystemExit):
        seed(tmp_path)
