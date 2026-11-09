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

        statuses = {d.verification_status for d in db.query(Decision).all()}
        assert statuses == {"verified", "low_confidence"}
        assert all(d.source_segment_id for d in db.query(Decision).all())

        overdue = [c for c in db.query(Commitment).all() if compute_overdue("commitment", c.status, c.due_date)[0]]
        assert len(overdue) == 1
    finally:
        db.close()


def test_seed_refuses_a_non_empty_data_dir(tmp_path, restore_data_dir):
    seed(tmp_path)
    with pytest.raises(SystemExit):
        seed(tmp_path)
