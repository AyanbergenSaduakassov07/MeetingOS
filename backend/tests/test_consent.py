"""A recording is only accepted once the uploader confirms everyone agreed to it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.database import Meeting, Organization
from backend.tests.test_meeting_pipeline import _wav_bytes


@pytest.fixture
def org(db) -> Organization:
    organization = Organization(name="Club", slug="club")
    db.add(organization)
    db.commit()
    return organization


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setattr("backend.routes.meetings.schedule_processing", lambda meeting_id: None)
    from backend.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _upload(client, org, **extra):
    return client.post(
        "/api/meetings/upload",
        files={"file": ("m.wav", _wav_bytes(), "audio/wav")},
        data={"title": "Weekly", "org_id": org.id, **extra},
    )


def test_upload_without_consent_is_refused_and_stores_nothing(client, db, org):
    response = _upload(client, org)

    assert response.status_code == 422
    assert "consent" in response.text.lower()
    assert db.query(Meeting).count() == 0


def test_upload_with_consent_records_when_and_how(client, db, org):
    response = _upload(client, org, consent_confirmed="true", consent_note="Verbal, start of call")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["consent_confirmed_at"] is not None
    assert body["consent_note"] == "Verbal, start of call"
    meeting = db.query(Meeting).one()
    assert meeting.consent_confirmed_at is not None
