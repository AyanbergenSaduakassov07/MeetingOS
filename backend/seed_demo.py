"""Seed a deterministic demo dataset: one org, three recorded meetings, no API calls.

The Playwright suites in ``web/tests`` need a completed meeting with a playable
recording, cited decisions (one verified, one low-confidence), action items,
a risk and commitments including an overdue one. CI has no model keys, so this
writes those rows directly instead of running the pipeline.

The other two meetings are real pipeline output frozen into ``backend/demo/*.json``
(transcript, speakers and the extracted, fact-checked items) next to their audio.

    python -m backend.seed_demo --data-dir data
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import shutil
import struct
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import config, database
from .database.models import (
    ActionItem,
    Commitment,
    Decision,
    Evidence,
    Meeting,
    MeetingStatus,
    Organization,
    Risk,
    Speaker,
    TranscriptSegment,
    User,
)

logger = logging.getLogger(__name__)

DEMO_DIR = Path(__file__).parent / "demo"
FIXTURES = ("akorda-kz-ru-talks.json", "clinic-app-release.json")
SEGMENT_MS = 8000
SAMPLE_RATE = 8000
PEOPLE = (("Priya", "priya@demo.local"), ("Dana", "dana@demo.local"), ("Sam", "sam@demo.local"))
TRANSCRIPT = (
    ("Dana", "Okay, let's start. Three things today: the venue, the sponsor and the robot parts."),
    ("Sam", "For the venue, the main hall is free on the fourteenth, the lab is free on the twenty-first."),
    ("Dana", "Let's take the main hall on the fourteenth. More space for the audience."),
    ("Priya", "The sponsor agreed verbally, but the money has not cleared yet."),
    ("Priya", "If it hasn't cleared by Friday we can't order the parts, and they take two weeks."),
    ("Sam", "Then we should maybe ask the university for a small grant as a backup."),
    ("Dana", "I think we go with the grant only if the sponsor falls through, not yet."),
    ("Priya", "I'll send the sponsor a reminder email today and update everyone tomorrow."),
    ("Sam", "I will book the main hall by Wednesday."),
    ("Dana", "Good. Next meeting same time next week."),
)


def write_tone_wav(path: Path, duration_ms: int) -> None:
    """A quiet sine tone, so the player has real audio to decode and seek."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = SAMPLE_RATE * duration_ms // 1000
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 * i / SAMPLE_RATE))) for i in range(frames)
            )
        )


def _evidence(org: Organization, meeting: Meeting, segment: TranscriptSegment, status: str, score: float) -> Evidence:
    evidence = Evidence(
        org_id=org.id,
        meeting_id=meeting.id,
        claim_text=segment.text,
        quote=segment.text,
        confidence=score,
        verification_status=status,
        verification_score=score,
    )
    evidence.cite(segment)
    return evidence


def _seed_fixture(db, org: Organization, users: dict[str, User], data_dir: Path, name: str) -> Meeting:
    """One meeting from a frozen pipeline run: audio, speakers, segments and cited items."""
    fx = json.loads((DEMO_DIR / name).read_text(encoding="utf-8"))
    for person in fx["people"]:
        if person not in users:
            slug = person.lower().replace(" ", ".").replace("-", ".")
            users[person] = User(org_id=org.id, email=f"{slug}@demo.local", full_name=person)
            db.add(users[person])
    db.flush()

    recording = data_dir / "recordings" / fx["recording"]
    recording.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEMO_DIR / fx["recording"], recording)
    start = datetime.fromisoformat(fx["actual_start"])
    meeting = Meeting(
        org_id=org.id,
        title=fx["title"],
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language=fx["language"],
        recording_path=config.to_storage_path(recording),
        audio_duration_seconds=fx["duration_seconds"],
        actual_start=start,
        created_at=start,  # the list sorts by created_at; keeps robotics (seeded "now") first
        summary=fx["summary"],
        consent_confirmed_at=start,
        consent_note=fx["consent_note"],
    )
    db.add(meeting)
    db.flush()

    labels = dict.fromkeys(s["speaker"] for s in fx["segments"])
    speakers = {
        label: Speaker(meeting_id=meeting.id, user_id=users[label].id if label in users else None, display_label=label)
        for label in labels
    }
    db.add_all(speakers.values())
    db.flush()
    segments = [
        TranscriptSegment(
            meeting_id=meeting.id,
            speaker_id=speakers[s["speaker"]].id,
            sequence=i,
            start_ms=round(s["start"] * 1000),
            end_ms=round(s["end"] * 1000),
            text=s["text"],
            confidence=0.9,
            language=s.get("language", fx["language"]),
        )
        for i, s in enumerate(fx["segments"])
    ]
    db.add_all(segments)
    db.flush()

    def cite(item: dict) -> Evidence:
        return _evidence(org, meeting, segments[item["segment"]], item["verification_status"], item["score"])

    def person(name: str | None) -> str | None:
        return users[name].id if name in users else None

    base = {"org_id": org.id, "meeting_id": meeting.id}
    db.add_all(
        [
            Decision(**base, title=d["title"], status=d["status"], decision_maker_id=person(d["decision_maker"]),
                     decided_at=start if d["status"] == "agreed" else None, evidence=cite(d))
            for d in fx["decisions"]
        ]
        + [ActionItem(**base, title=a["title"], assignee_id=person(a["assignee"]), evidence=cite(a)) for a in fx["action_items"]]
        + [Risk(**base, title=r["title"], severity=r["severity"], owner_id=person(r["owner"]), evidence=cite(r)) for r in fx["risks"]]
        # Due dates stay in the text ("due as stated: ..."): dated rows would drift into overdue as the demo ages.
        + [Commitment(**base, committer_id=person(c["committer"]), text=c["text"], evidence=cite(c)) for c in fx["commitments"]]
    )
    return meeting


def seed(data_dir: Path) -> str:
    """Create the dataset in ``data_dir`` and return the robotics meeting id. Refuses a non-empty DB."""
    config.set_data_dir(data_dir)
    database.init_db()
    db = database.new_session()
    try:
        if db.query(Organization).count():
            raise SystemExit(f"{data_dir} already has data; seed an empty data dir.")

        now = datetime.now(UTC).replace(microsecond=0)
        org = Organization(name="Demo workspace", slug="demo")
        db.add(org)
        db.flush()
        users = {name: User(org_id=org.id, email=email, full_name=name) for name, email in PEOPLE}
        db.add_all(users.values())

        duration_ms = SEGMENT_MS * len(TRANSCRIPT)
        recording = data_dir / "recordings" / "demo-meeting.wav"
        write_tone_wav(recording, duration_ms)
        meeting = Meeting(
            org_id=org.id,
            title="Robotics club weekly sync",
            status=MeetingStatus.COMPLETED.value,
            source="upload",
            language="en",
            recording_path=config.to_storage_path(recording),
            audio_duration_seconds=duration_ms / 1000,
            actual_start=now - timedelta(days=3),
            summary="Venue set for the 14th; sponsor money still pending; parts order depends on it.",
            consent_confirmed_at=now - timedelta(days=3),
            consent_note="Demo data, no real people.",
        )
        db.add(meeting)
        db.flush()

        speakers = {name: Speaker(meeting_id=meeting.id, user_id=users[name].id, display_label=name) for name in users}
        db.add_all(speakers.values())
        db.flush()
        segments = [
            TranscriptSegment(
                meeting_id=meeting.id,
                speaker_id=speakers[who].id,
                sequence=i,
                start_ms=i * SEGMENT_MS,
                end_ms=(i + 1) * SEGMENT_MS,
                text=text,
                confidence=0.95,
                language="en",
            )
            for i, (who, text) in enumerate(TRANSCRIPT)
        ]
        db.add_all(segments)
        db.flush()

        def cite(index: int, status: str = "verified", score: float = 0.93) -> Evidence:
            return _evidence(org, meeting, segments[index], status, score)

        db.add_all(
            [
                Decision(
                    org_id=org.id,
                    meeting_id=meeting.id,
                    title="Hold the demo day in the main hall on the 14th",
                    status="agreed",
                    decided_at=meeting.actual_start,
                    decision_maker_id=users["Dana"].id,
                    evidence=cite(2),
                ),
                Decision(
                    org_id=org.id,
                    meeting_id=meeting.id,
                    title="Apply for a university grant as a backup",
                    status="proposed",
                    evidence=cite(5, "low_confidence", 0.41),
                ),
                ActionItem(
                    org_id=org.id,
                    meeting_id=meeting.id,
                    title="Book the main hall",
                    assignee_id=users["Sam"].id,
                    due_date=now + timedelta(days=2),
                    evidence=cite(8),
                ),
                Risk(
                    org_id=org.id,
                    meeting_id=meeting.id,
                    title="Parts order slips if sponsor money is late",
                    severity="high",
                    owner_id=users["Priya"].id,
                    evidence=cite(4),
                ),
                Commitment(
                    org_id=org.id,
                    meeting_id=meeting.id,
                    committer_id=users["Priya"].id,
                    text="Send the sponsor a reminder email",
                    due_date=now - timedelta(days=2),  # overdue on purpose
                    evidence=cite(7),
                ),
                Commitment(
                    org_id=org.id,
                    meeting_id=meeting.id,
                    committer_id=users["Sam"].id,
                    text="Book the main hall by Wednesday",
                    due_date=now + timedelta(days=2),
                    evidence=cite(8),
                ),
            ]
        )
        for name in FIXTURES:
            _seed_fixture(db, org, users, data_dir, name)
        db.commit()
        return meeting.id
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Seed a deterministic MeetingOS demo dataset")
    parser.add_argument("--data-dir", default="data", help="Empty data directory to seed")
    meeting_id = seed(Path(parser.parse_args().data_dir))
    logger.info("Seeded demo meeting %s", meeting_id)
