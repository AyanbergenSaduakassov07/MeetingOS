"""Evidence as a first-class record.

Seam under test: the ``Evidence`` model itself, plus the ``.evidence``
relationship on each extracted item. The five loose citation fields
(``source_segment_id``, ``source_quote``, ``extraction_confidence``,
``verification_status``, ``verification_score``) stay as the compatibility
interface and must keep behaving exactly as before — that is the whole point of
the migration, so it is asserted here rather than assumed.
"""

from __future__ import annotations

import pytest

from backend.database import (
    ActionItem,
    Commitment,
    Decision,
    Evidence,
    Meeting,
    MeetingStatus,
    Organization,
    Risk,
    TranscriptSegment,
    VerificationStatus,
)

ITEM_MODELS = (Decision, ActionItem, Risk, Commitment)


@pytest.fixture
def meeting(db):
    org = Organization(name="Org", slug="org")
    db.add(org)
    db.flush()
    meeting = Meeting(
        org_id=org.id,
        title="Weekly",
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
    )
    db.add(meeting)
    db.flush()
    for index, text in enumerate(
        [
            "Let's lock the fifteenth for the showcase.",
            "I'll chase the sponsor invoice tonight.",
            "The money has not cleared yet.",
        ]
    ):
        db.add(
            TranscriptSegment(
                meeting_id=meeting.id,
                sequence=index,
                start_ms=index * 8000,
                end_ms=(index + 1) * 8000,
                text=text,
            )
        )
    db.commit()
    return meeting


def segments(db, meeting):
    return db.query(TranscriptSegment).filter_by(meeting_id=meeting.id).order_by(TranscriptSegment.sequence).all()


# -- the record itself -----------------------------------------------------


def test_evidence_is_queryable_on_its_own(db, meeting):
    """Acceptance: an Evidence record stands alone, not only via its item."""
    source = segments(db, meeting)[0]
    evidence = Evidence(
        org_id=meeting.org_id,
        meeting_id=meeting.id,
        claim_text="Hold the showcase on the fifteenth",
        quote="Let's lock the fifteenth",
        confidence=0.94,
    )
    evidence.cite(source)
    db.add(evidence)
    db.commit()

    found = db.query(Evidence).filter_by(meeting_id=meeting.id).one()
    assert found.claim_text == "Hold the showcase on the fifteenth"
    assert found.confidence == pytest.approx(0.94)
    assert found.verification_status == VerificationStatus.UNVERIFIED.value


def test_evidence_carries_the_span_of_the_segments_it_cites(db, meeting):
    """start/end come from the cited segments, not from the caller."""
    first, second, _ = segments(db, meeting)
    evidence = Evidence(org_id=meeting.org_id, meeting_id=meeting.id, claim_text="c")
    evidence.cite(first)
    evidence.cite(second)
    db.add(evidence)
    db.commit()

    assert evidence.start_ms == first.start_ms
    assert evidence.end_ms == second.end_ms
    assert [c.segment_id for c in evidence.citations] == [first.id, second.id]


def test_evidence_supports_multiple_source_segments(db, meeting):
    """A claim can span more than one utterance — the whole point of id(s)."""
    all_three = segments(db, meeting)
    evidence = Evidence(org_id=meeting.org_id, meeting_id=meeting.id, claim_text="c")
    for segment in all_three:
        evidence.cite(segment)
    db.add(evidence)
    db.commit()

    assert len(evidence.segment_ids) == 3
    assert evidence.segment_ids[0] == all_three[0].id


def test_evidence_with_no_citation_is_unsupported(db, meeting):
    """A claim citing nothing real is categorically unsupported, not merely weak."""
    evidence = Evidence(org_id=meeting.org_id, meeting_id=meeting.id, claim_text="invented")
    db.add(evidence)
    db.commit()

    assert evidence.segment_ids == []
    assert evidence.start_ms is None
    assert evidence.is_grounded is False


# -- items reference it ----------------------------------------------------


@pytest.mark.parametrize("model", ITEM_MODELS, ids=lambda m: m.__name__)
def test_every_item_kind_resolves_to_a_real_evidence_record(db, meeting, model):
    """Acceptance: every extracted item resolves to a real Evidence record."""
    source = segments(db, meeting)[0]
    evidence = Evidence(
        org_id=meeting.org_id,
        meeting_id=meeting.id,
        claim_text="claim",
        quote="Let's lock the fifteenth",
        confidence=0.9,
    )
    evidence.cite(source)

    kwargs = {"org_id": meeting.org_id, "meeting_id": meeting.id, "evidence": evidence}
    kwargs["text" if model is Commitment else "title"] = "claim"
    item = model(**kwargs)
    db.add(item)
    db.commit()

    reloaded = db.query(model).one()
    assert reloaded.evidence is not None
    assert reloaded.evidence.id == evidence.id
    assert db.query(Evidence).filter_by(id=reloaded.evidence_id).one() is not None


# -- the old interface still works -----------------------------------------


def test_loose_citation_fields_read_through_to_evidence(db, meeting):
    """Phase 3 code reads these five names; they must keep answering."""
    source = segments(db, meeting)[0]
    evidence = Evidence(
        org_id=meeting.org_id,
        meeting_id=meeting.id,
        claim_text="claim",
        quote="Let's lock the fifteenth",
        confidence=0.88,
    )
    evidence.cite(source)
    decision = Decision(org_id=meeting.org_id, meeting_id=meeting.id, title="claim", evidence=evidence)
    db.add(decision)
    db.commit()

    assert decision.source_segment_id == source.id
    assert decision.source_quote == "Let's lock the fifteenth"
    assert decision.extraction_confidence == pytest.approx(0.88)
    assert decision.verification_status == VerificationStatus.UNVERIFIED.value
    assert decision.verification_score is None


def test_writing_a_loose_field_updates_the_evidence_record(db, meeting):
    """The verifier writes item.verification_status; it must land on Evidence."""
    source = segments(db, meeting)[0]
    evidence = Evidence(org_id=meeting.org_id, meeting_id=meeting.id, claim_text="c")
    evidence.cite(source)
    decision = Decision(org_id=meeting.org_id, meeting_id=meeting.id, title="c", evidence=evidence)
    db.add(decision)
    db.commit()

    decision.verification_status = VerificationStatus.VERIFIED.value
    decision.verification_score = 0.91
    db.commit()

    assert db.query(Evidence).filter_by(id=evidence.id).one().verification_status == "verified"
    assert db.query(Evidence).filter_by(id=evidence.id).one().verification_score == pytest.approx(0.91)


def test_setting_source_segment_id_on_a_bare_item_creates_evidence(db, meeting):
    """Older code assigns the loose field directly; that must still work."""
    source = segments(db, meeting)[0]
    decision = Decision(org_id=meeting.org_id, meeting_id=meeting.id, title="c")
    db.add(decision)
    db.flush()

    decision.source_segment_id = source.id
    db.commit()

    assert decision.evidence is not None
    assert decision.evidence.segment_ids == [source.id]


def test_item_without_evidence_reports_none_not_an_error(db, meeting):
    """A bare item must not raise on the compatibility fields."""
    decision = Decision(org_id=meeting.org_id, meeting_id=meeting.id, title="c")
    db.add(decision)
    db.commit()

    assert decision.source_segment_id is None
    assert decision.source_quote is None
    assert decision.extraction_confidence is None
    assert decision.verification_status == VerificationStatus.UNVERIFIED.value


# -- Phase 3 pipeline populates it -----------------------------------------


def test_reextraction_does_not_orphan_evidence(db, meeting):
    """A re-run must replace Evidence, not accumulate it."""
    from backend.meetings.intelligence import _clear_previous

    source = segments(db, meeting)[0]
    for _ in range(3):
        evidence = Evidence(org_id=meeting.org_id, meeting_id=meeting.id, claim_text="c")
        evidence.cite(source)
        db.add(Decision(org_id=meeting.org_id, meeting_id=meeting.id, title="c", evidence=evidence))
    db.commit()
    assert db.query(Evidence).count() == 3

    _clear_previous(db, meeting.id)
    db.commit()

    assert db.query(Decision).count() == 0
    assert db.query(Evidence).count() == 0, "evidence rows orphaned by re-extraction"


def test_items_can_be_inserted_after_the_legacy_columns_are_dropped(db, meeting):
    """Regression: a migrated database rejected every insert.

    The Evidence migration originally left the pre-Evidence citation columns in
    place. One of them, `verification_status`, was NOT NULL with no default,
    and the ORM stopped writing it the moment it became a property — so INSERT
    failed on any database that had actually been migrated. Fresh databases
    were unaffected, because the model no longer declares the column, which is
    exactly why the test suite did not catch it.
    """
    for model, kwargs in (
        (Decision, {"title": "t", "status": "agreed"}),
        (ActionItem, {"title": "t"}),
        (Risk, {"title": "t"}),
        (Commitment, {"text": "t"}),
    ):
        row = model(org_id=meeting.org_id, meeting_id=meeting.id, **kwargs)
        db.add(row)
    db.commit()

    for model in ITEM_MODELS:
        assert db.query(model).count() >= 1, f"{model.__name__} insert did not persist"


def test_legacy_citation_columns_are_gone_from_a_migrated_database(data_dir):
    """The drop must actually happen, not merely be attempted."""
    from sqlalchemy import inspect

    from backend.database import session as db_session

    inspector = inspect(db_session.engine)
    for table in ("decisions", "action_items", "risks", "commitments"):
        columns = {c["name"] for c in inspector.get_columns(table)}
        # source_segment_id survives: SQLite will not drop an FK-named column.
        # It is nullable and unread, so it is inert.
        for dead in ("verification_status", "verification_score", "source_quote", "extraction_confidence"):
            assert dead not in columns, f"{table}.{dead} survived the migration"
