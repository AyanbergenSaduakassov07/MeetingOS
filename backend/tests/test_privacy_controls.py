"""Redaction, egress allowlist, rate limits, and retention.

These cover the high-severity findings from the LLM Top 10 and AI data privacy
reviews. Each one is a control that is easy to add and easy to silently break.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.app import create_app
from backend.database import (
    Decision,
    Evidence,
    EvidenceCitation,
    Meeting,
    MeetingStatus,
    Organization,
    Speaker,
    TranscriptSegment,
)
from backend.meetings import redaction, retention
from backend.routes import limits

# -- redaction -------------------------------------------------------------


@pytest.mark.parametrize(
    "text,rule",
    [
        ("email me at priya.sharma@example.org please", "email"),
        ("call me on 07700 900123 tonight", "phone"),
        ("the card is 4111 1111 1111 1111", "card"),
        ("account GB29NWBK60161331926819 is the one", "iban"),
        ("his NI number is AB 12 34 56 C", "ni_number"),
        ("SSN 123-45-6789 on the form", "ssn"),
        ("sort code 60-16-13 for the transfer", "sort_code"),
        ("posted to SW1A 1AA last week", "postcode"),
        ("see https://internal.example.org/board/minutes", "url"),
    ],
)
def test_identifier_shapes_are_redacted(text, rule):
    result = redaction.redact(text)
    assert rule in result.counts, f"{rule} not detected in {text!r} -> {result.text!r}"
    assert f"[redacted:{rule}]" in result.text


def test_ordinary_meeting_speech_is_left_alone():
    """Redaction must not eat the substance of a meeting record."""
    text = "Priya will chase the sponsor invoice before Friday and report back."
    result = redaction.redact(text)
    assert not result.changed, f"redacted ordinary speech: {result.text!r}"
    assert result.text == text


def test_names_are_deliberately_not_redacted():
    """Documented limitation, asserted so it cannot be mistaken for anonymisation."""
    result = redaction.redact("Dana Okonkwo agreed to run the induction session.")
    assert "Dana Okonkwo" in result.text


def test_redaction_is_off_unless_opted_in(monkeypatch):
    monkeypatch.delenv(redaction.ENV_FLAG, raising=False)
    assert redaction.is_enabled() is False
    assert redaction.redact_for_egress("call 07700 900123") == "call 07700 900123"

    monkeypatch.setenv(redaction.ENV_FLAG, "1")
    assert redaction.is_enabled() is True
    assert "[redacted:phone]" in redaction.redact_for_egress("call 07700 900123")


def test_redaction_applies_on_the_extraction_egress_path(monkeypatch):
    """The prompt built for the model must carry redacted text, not raw."""
    from backend.meetings import intelligence

    monkeypatch.setenv(redaction.ENV_FLAG, "1")

    class Segment:
        id = "seg-1"
        start_ms, end_ms = 0, 8000
        speaker = None
        text = "Wire it to GB29NWBK60161331926819 and call 07700 900123."

    rendered = intelligence._render_segments([Segment()])
    assert "GB29NWBK60161331926819" not in rendered
    assert "07700 900123" not in rendered
    assert "[redacted:" in rendered


def test_redaction_applies_on_the_copilot_egress_path(monkeypatch):
    from backend.meetings import copilot

    monkeypatch.setenv(redaction.ENV_FLAG, "1")

    class Segment:
        id = "seg-1"
        start_ms, end_ms = 0, 8000
        speaker_id = None
        text = "Reach me at priya@example.org about the invoice."

    rendered = copilot._render_excerpt([Segment()], {})
    assert "priya@example.org" not in rendered
    assert "[redacted:email]" in rendered


# -- egress allowlist ------------------------------------------------------


def test_allowlisted_inference_host_is_accepted():
    assert (
        config.validate_inference_base_url("https://openrouter.ai/api/v1", provider="test")
        == "https://openrouter.ai/api/v1"
    )


def test_unknown_inference_host_is_refused():
    with pytest.raises(ValueError, match="allowlist"):
        config.validate_inference_base_url("https://exfil.example/v1", provider="test")


def test_plaintext_http_to_a_remote_host_is_refused():
    with pytest.raises(ValueError, match="unencrypted"):
        config.validate_inference_base_url("http://api.openai.com/v1", provider="test")


def test_localhost_is_allowed_for_local_models():
    assert config.validate_inference_base_url("http://localhost:11434/v1", provider="test")


def test_allowlist_can_be_extended_deliberately(monkeypatch):
    monkeypatch.setenv(config.INFERENCE_HOST_ALLOWLIST_ENV, "inference.mycorp.example")
    assert config.validate_inference_base_url("https://inference.mycorp.example/v1", provider="test")


# -- rate limiting ---------------------------------------------------------


def test_ask_endpoint_is_rate_limited(data_dir, db, monkeypatch):
    monkeypatch.setattr(limits, "ASK_PER_MINUTE", 3)
    limits.reset()

    org = Organization(name="Org", slug="org")
    db.add(org)
    db.flush()
    meeting = Meeting(
        org_id=org.id,
        title="m",
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
    )
    db.add(meeting)
    db.commit()

    with TestClient(create_app()) as client:
        codes = [
            client.post(f"/api/meetings/{meeting.id}/ask", json={"question": "what?"}).status_code for _ in range(5)
        ]

    assert 429 in codes, f"no request was rate limited: {codes}"
    assert codes.count(429) == 2, f"expected 2 rejections after 3 allowed, got {codes}"


def test_upload_endpoint_is_rate_limited(data_dir, db, monkeypatch):
    monkeypatch.setattr(limits, "UPLOAD_PER_MINUTE", 2)
    limits.reset()
    db.add(Organization(name="Org", slug="org"))
    db.commit()

    with TestClient(create_app()) as client:
        codes = [
            client.post(
                "/api/meetings/upload",
                files={"file": ("a.wav", b"\x00" * 128, "audio/wav")},
                data={"title": "t", "consent_confirmed": "true"},
            ).status_code
            for _ in range(4)
        ]

    assert codes.count(429) == 2, codes


def test_rate_limit_response_tells_the_client_when_to_retry(data_dir, db, monkeypatch):
    monkeypatch.setattr(limits, "ASK_PER_MINUTE", 1)
    limits.reset()
    org = Organization(name="Org", slug="org")
    db.add(org)
    db.flush()
    meeting = Meeting(org_id=org.id, title="m", status="completed", source="upload")
    db.add(meeting)
    db.commit()

    with TestClient(create_app()) as client:
        client.post(f"/api/meetings/{meeting.id}/ask", json={"question": "q"})
        blocked = client.post(f"/api/meetings/{meeting.id}/ask", json={"question": "q"})

    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


# -- retention -------------------------------------------------------------


def _aged_meeting(db, org, days_old: int) -> Meeting:
    meeting = Meeting(
        org_id=org.id,
        title=f"{days_old}d old",
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
        created_at=datetime.now(UTC) - timedelta(days=days_old),
    )
    db.add(meeting)
    db.flush()
    speaker = Speaker(meeting_id=meeting.id, display_label="A", voice_embedding=b"\x00" * 16)
    db.add(speaker)
    db.flush()
    segment = TranscriptSegment(
        meeting_id=meeting.id,
        speaker_id=speaker.id,
        sequence=0,
        start_ms=0,
        end_ms=8000,
        text="something said",
        embedding=b"\x00" * 16,
        embedding_dim=4,
    )
    db.add(segment)
    db.flush()

    # An extracted item with real Evidence citing that segment. Without this
    # the purge never exercised the delete ordering that the citation ->
    # segment foreign key constrains.
    evidence = Evidence(org_id=org.id, meeting_id=meeting.id, claim_text="something was decided")
    evidence.cite(segment)
    db.add(Decision(org_id=org.id, meeting_id=meeting.id, title="something was decided", evidence=evidence))
    db.commit()
    return meeting


def test_purge_is_a_dry_run_by_default(data_dir, db):
    org = Organization(name="Org", slug="org", retention_days=30)
    db.add(org)
    db.flush()
    _aged_meeting(db, org, days_old=90)

    report = retention.purge_expired(db)
    assert report.meetings == 1
    assert report.committed is False
    assert db.query(Meeting).count() == 1, "dry run deleted data"


def test_purge_removes_expired_meetings_and_their_embeddings(data_dir, db):
    org = Organization(name="Org", slug="org", retention_days=30)
    db.add(org)
    db.flush()
    _aged_meeting(db, org, days_old=90)
    _aged_meeting(db, org, days_old=5)

    report = retention.purge_expired(db, commit=True)

    assert report.meetings == 1
    assert db.query(Meeting).count() == 1, "wrong number of meetings survived"
    assert db.query(TranscriptSegment).count() == 1, "segment embeddings outlived their transcript"
    assert db.query(Speaker).count() == 1, "voice embeddings outlived their meeting"


def test_zero_retention_days_means_keep_indefinitely(data_dir, db):
    org = Organization(name="Org", slug="org", retention_days=0)
    db.add(org)
    db.flush()
    _aged_meeting(db, org, days_old=9999)

    report = retention.purge_expired(db, commit=True)
    assert report.meetings == 0
    assert db.query(Meeting).count() == 1


def test_purge_deletes_evidence_and_citations_with_the_transcript(data_dir, db):
    """Regression: citations reference segments, so they must be deleted first.

    Without the ordering, the purge raises FOREIGN KEY constraint failed and
    the meeting survives — retention silently stops working. Evidence must also
    not outlive the transcript it cites: an embedding or quote that survives its
    source is retained personal data with nothing to audit it against.
    """
    org = Organization(name="Org", slug="org", retention_days=30)
    db.add(org)
    db.flush()
    _aged_meeting(db, org, days_old=90)
    _aged_meeting(db, org, days_old=5)

    assert db.query(Evidence).count() == 2
    assert db.query(EvidenceCitation).count() == 2

    report = retention.purge_expired(db, commit=True)

    assert report.meetings == 1
    assert db.query(Evidence).count() == 1, "Evidence outlived the transcript it cites"
    assert db.query(EvidenceCitation).count() == 1, "orphaned citation rows survived the purge"
    assert db.query(Decision).count() == 1
    assert db.query(TranscriptSegment).count() == 1


def test_purge_removes_documents_filed_against_the_meeting(data_dir, db):
    """A contract's text must not outlive the meeting it belongs to."""
    from backend.database import Document, DocumentChunk

    org = Organization(name="Org", slug="org", retention_days=30)
    db.add(org)
    db.flush()
    old = _aged_meeting(db, org, days_old=90)
    recent = _aged_meeting(db, org, days_old=5)

    for meeting in (old, recent):
        document = Document(
            org_id=org.id,
            meeting_id=meeting.id,
            title="Supply contract",
            doc_type="contract",
            storage_path=f"docs/{meeting.id}.txt",
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentChunk(
                org_id=org.id,
                document_id=document.id,
                ordinal=0,
                page=1,
                text="The notice period is ninety days.",
            )
        )
    db.commit()
    assert db.query(Document).count() == 2

    retention.purge_expired(db, commit=True)

    assert db.query(Document).count() == 1, "a document outlived its purged meeting"
    assert db.query(DocumentChunk).count() == 1, "orphaned chunks survived the purge"
