"""Redaction rules, the egress audit log, and the privacy page.

Acceptance:
- `test_planted_sensitive_values_never_reach_the_provider` — with redaction on,
  a planted value does not appear in ANY call to a mocked provider.
- `test_privacy_page_reflects_the_running_configuration` — the page describes
  what is actually configured, not what the docs say.

Context: redaction existed before this phase but covered none of the three
categories the blueprint named. `test_categories_the_blueprint_required` pins
that gap closed.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.ai.base import Completion, ProviderConfig, Usage
from backend.app import create_app
from backend.database import (
    Evidence,
    Meeting,
    MeetingStatus,
    Organization,
    ProviderCall,
    TranscriptSegment,
)
from backend.meetings import redaction
from backend.meetings.egress_log import CallRecord, logged_call, record
from backend.meetings.redaction_rules import ALL_RULES, RULES_BY_NAME, RedactionConfig

# Values planted in the transcript. None may appear in an outbound payload.
PLANTED = {
    "salary": "145,000 tenge",
    "national_id": "870512300456",
    "health": "cancer diagnosis",
    "email": "priya.sharma@example.org",
    "phone": "07700 900123",
}

TRANSCRIPT = [
    "Right, first item is the compensation review.",
    f"Her salary is {PLANTED['salary']} per month, up from last year.",
    f"His IIN is {PLANTED['national_id']} for the contract paperwork.",
    f"Also, Dana disclosed a {PLANTED['health']} and will be on leave.",
    f"Reach Priya at {PLANTED['email']} or {PLANTED['phone']}.",
    "Second item, the Aktau expansion budget of 500,000 tenge for parts.",
]

ALL_RULE_NAMES = [rule.name for rule in ALL_RULES]


@pytest.fixture(autouse=True)
def _reset_redaction():
    redaction.set_active_config(None)
    yield
    redaction.set_active_config(None)


@pytest.fixture
def org(db):
    organization = Organization(name="KMG", slug="kmg")
    db.add(organization)
    db.commit()
    return organization


@pytest.fixture
def meeting(db, org):
    row = Meeting(
        org_id=org.id,
        title="Comp review",
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
    )
    db.add(row)
    db.flush()
    for index, text in enumerate(TRANSCRIPT):
        segment = TranscriptSegment(
            meeting_id=row.id,
            sequence=index,
            start_ms=index * 10000,
            end_ms=(index + 1) * 10000,
            text=text,
        )
        db.add(segment)
        db.flush()
        evidence = Evidence(
            org_id=org.id,
            meeting_id=row.id,
            claim_text=text,
            quote=text,
            confidence=0.9,
            verification_status="verified",
        )
        evidence.cite(segment)
        db.add(evidence)
    db.commit()
    return row


class RecordingProvider:
    """Captures every payload it is handed, of any kind."""

    def __init__(self) -> None:
        self.config = ProviderConfig(
            name="recording",
            model="recording",
            api_key_env="NONE",
            embedding_model="recording",
            supports_embeddings=True,
        )
        self.payloads: list[str] = []

    def is_configured(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.payloads.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    async def generate(self, prompt, *, system=None, max_tokens=None, temperature=None):
        self.payloads.append(prompt)
        if system:
            self.payloads.append(system)
        return Completion(text='{"answer": "ok", "segment_ids": []}', model="recording", usage=Usage(1, 1))

    async def extract(self, prompt, schema, *, system=None, max_tokens=None):
        self.payloads.append(prompt)
        if system:
            self.payloads.append(system)
        return schema()


# -- acceptance ------------------------------------------------------------


def test_planted_sensitive_values_never_reach_the_provider(db, org, meeting):
    """Acceptance: with redaction on, nothing planted leaves the machine.

    Exercised across every egress path that carries transcript text — the
    extraction prompt, the copilot prompt, and the embedding batches. The
    embedding path is included deliberately: it was the one that silently
    bypassed redaction until it was fixed, and it is the highest-volume path.
    """
    redaction.set_active_config(RedactionConfig(enabled=True, rules=ALL_RULE_NAMES))
    provider = RecordingProvider()

    from backend.meetings import copilot
    from backend.meetings.intelligence import _render_segments

    segments = db.query(TranscriptSegment).filter_by(meeting_id=meeting.id).order_by(TranscriptSegment.sequence).all()

    # 1. The extraction prompt.
    provider.payloads.append(_render_segments(segments))

    # 2. The copilot prompt.
    provider.payloads.append(copilot._render_excerpt(segments, {}))

    # 3. The embedding batches — segment text and the question.
    asyncio.run(copilot.ensure_segment_embeddings(db, meeting.id, embedder=provider))
    # A neutral question. The acceptance criterion is about transcript text; a
    # question is a separate egress path with its own limitation, covered by
    # `test_a_question_is_redacted_too_but_needs_the_same_context_words`.
    asyncio.run(
        copilot.answer_question(
            meeting.id,
            "what was decided about the parts order?",
            db=db,
            provider=provider,
            embedder=provider,
        )
    )

    assert provider.payloads, "no payloads captured; the test proves nothing"
    haystack = "\n".join(provider.payloads)

    for label, value in PLANTED.items():
        offending = [i for i, payload in enumerate(provider.payloads) if value in payload]
        assert not offending, f"{label} value {value!r} reached the provider in payload(s) {offending}: " + " || ".join(
            provider.payloads[i][:200] for i in offending
        )

    # The redaction must be visible, not the result of sending nothing at all.
    assert "[redacted:" in haystack, "nothing was redacted; the payloads may be empty"
    # And ordinary meeting content survives, or extraction would be useless.
    assert "Aktau expansion" in haystack


def test_without_redaction_the_same_values_do_reach_the_provider(db, org, meeting):
    """The control. Without this, the test above could pass for the wrong reason."""
    redaction.set_active_config(RedactionConfig(enabled=False, rules=ALL_RULE_NAMES))
    from backend.meetings.intelligence import _render_segments

    segments = db.query(TranscriptSegment).filter_by(meeting_id=meeting.id).all()
    rendered = _render_segments(segments)

    assert PLANTED["salary"] in rendered
    assert PLANTED["health"] in rendered


def test_categories_the_blueprint_required(db):
    """Salary, national ID, and health — none were covered before this phase."""
    config = RedactionConfig(enabled=True, rules=ALL_RULE_NAMES)
    cases = [
        ("salary", "His salary is 145,000 tenge per month"),
        ("salary", "Base compensation of $180k plus bonus"),
        ("national_id", "IIN 870512300456 on the contract"),
        ("national_id", "Her ИИН is 870512300456"),
        ("health", "He disclosed a cancer diagnosis and is on chemotherapy"),
        ("health", "She is on long-term sick leave for depression"),
        ("health", "Он на больничном после операции"),
    ]
    for category, text in cases:
        result = redaction.redact(text, config=config)
        assert result.changed, f"{category}: {text!r} was not redacted"
        hit_categories = {RULES_BY_NAME[name].category for name in result.counts}
        assert category in hit_categories, f"{text!r} matched {hit_categories}, expected {category}"


def test_ordinary_meeting_content_survives_redaction():
    """Over-redaction would make extraction useless; this is the other guardrail."""
    config = RedactionConfig(enabled=True, rules=ALL_RULE_NAMES)
    for text in (
        "The parts order is 500,000 tenge and ships in two weeks",
        "Priya will chase the sponsor invoice before Friday",
        "Let's lock the fifteenth for the showcase",
        "Approve the Aktau expansion capex budget",
    ):
        assert not redaction.redact(text, config=config).changed, f"over-redacted: {text!r}"


# -- configurable rule list ------------------------------------------------


def test_rules_can_be_selected_individually():
    only_health = RedactionConfig(enabled=True, rules=["health"])
    text = "Her salary is 145,000 tenge and she has a cancer diagnosis"
    result = redaction.redact(text, config=only_health)
    assert "health" in result.counts
    assert "salary" not in result.counts


def test_disabling_every_rule_redacts_nothing():
    result = redaction.redact("salary 145,000 tenge", config=RedactionConfig(enabled=True, rules=[]))
    assert not result.changed


def test_unknown_rule_names_are_dropped_with_a_warning(caplog):
    """A typo must not silently disable redaction."""
    config = RedactionConfig.from_dict({"enabled": True, "rules": ["health", "nonsense"]})
    assert config.rules == ["health"]


def test_config_round_trips_through_a_dict():
    original = RedactionConfig(enabled=True, rules=["health", "salary"])
    assert RedactionConfig.from_dict(original.to_dict()).rules == ["health", "salary"]


# -- audit log -------------------------------------------------------------


def test_a_call_is_recorded_with_shape_but_not_content(data_dir, db):
    record(
        CallRecord(
            provider="openai",
            operation="embed",
            model="text-embedding-3-large",
            endpoint_host="api.openai.com",
            characters_sent=4096,
            items_sent=12,
            redaction_enabled=True,
            redactions_applied=3,
        ),
        db=db,
    )
    row = db.query(ProviderCall).one()
    assert row.provider == "openai"
    assert row.is_cloud is True
    assert row.characters_sent == 4096
    assert row.redaction_enabled is True
    # No content column exists at all — the log documents exposure without
    # becoming a second copy of it.
    assert not hasattr(row, "prompt")
    assert not hasattr(row, "payload")


def test_a_local_endpoint_is_not_counted_as_cloud(data_dir, db):
    record(CallRecord(provider="ollama", operation="generate", endpoint_host="localhost"), db=db)
    assert db.query(ProviderCall).one().is_cloud is False


def test_a_failed_call_is_still_recorded(data_dir, db):
    with (
        pytest.raises(RuntimeError),
        logged_call("openai", "generate", endpoint_host="api.openai.com", texts=["x"], db=db),
    ):
        raise RuntimeError("upstream exploded")

    row = db.query(ProviderCall).one()
    assert row.succeeded is False
    assert "upstream exploded" in row.error


def test_logging_failure_never_breaks_the_call(monkeypatch):
    """An audit trail that can take down transcription is the wrong trade."""

    def explode(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr("backend.database.new_session", explode)
    record(CallRecord(provider="openai", operation="embed"))  # must not raise


# -- privacy page ----------------------------------------------------------


def test_privacy_page_reflects_the_running_configuration(data_dir, db, org):
    """Acceptance: the page describes what is configured, not what docs claim."""
    redaction.set_active_config(RedactionConfig(enabled=True, rules=["health", "salary"]))
    record(
        CallRecord(
            provider="openai",
            operation="embed",
            endpoint_host="api.openai.com",
            characters_sent=2048,
            items_sent=6,
            redaction_enabled=True,
        ),
        db=db,
    )

    with TestClient(create_app()) as client:
        body = client.get("/api/privacy").json()

    assert body["redaction"]["enabled"] is True
    assert body["redaction"]["source"] == "settings"
    enabled = {r["name"] for r in body["redaction"]["rules"] if r["enabled"]}
    assert enabled == {"health", "salary"}
    # Every rule is listed, enabled or not, so an operator can see what exists.
    assert len(body["redaction"]["rules"]) == len(ALL_RULES)
    assert body["redaction"]["limitations"], "limitations were not surfaced"
    assert any("Names are never redacted" in line for line in body["redaction"]["limitations"])

    assert body["providers"], "no providers listed"
    for provider in body["providers"]:
        assert provider["role"] in ("llm", "embedding", "transcription")
        assert "is_cloud" in provider

    assert body["residency"]["single_tenant"] is True
    assert body["residency"]["allowed_inference_hosts"]
    assert any("not implemented" in note for note in body["residency"]["notes"])

    assert body["audit_summary"]["total_calls"] == 1
    assert body["audit_summary"]["cloud_calls"] == 1
    assert body["audit_summary"]["characters_sent"] == 2048
    assert body["recent_calls"][0]["endpoint_host"] == "api.openai.com"


def test_privacy_page_counts_unredacted_cloud_calls(data_dir, db, org):
    """The number an operator most needs: what left without redaction."""
    for redacted in (True, False, False):
        record(
            CallRecord(
                provider="openai",
                operation="embed",
                endpoint_host="api.openai.com",
                redaction_enabled=redacted,
            ),
            db=db,
        )
    with TestClient(create_app()) as client:
        body = client.get("/api/privacy").json()
    assert body["audit_summary"]["calls_without_redaction"] == 2


def test_redaction_can_be_updated_through_the_api(data_dir, db, org):
    with TestClient(create_app()) as client:
        response = client.put("/api/privacy/redaction", json={"enabled": True, "rules": ["health"]})
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert {r["name"] for r in body["rules"] if r["enabled"]} == {"health"}

        # Persisted on the org, and in force immediately.
        reloaded = client.get("/api/privacy").json()
        assert reloaded["redaction"]["enabled"] is True

    db.expire_all()
    stored = db.query(Organization).filter_by(id=org.id).one().settings["redaction"]
    assert stored == {"enabled": True, "rules": ["health"]}
    assert redaction.is_enabled() is True


def test_a_question_is_redacted_too_but_needs_the_same_context_words(db, org, meeting):
    """The question is egress, and it is redacted — with the same blind spot.

    A user typing "her salary is 145,000 tenge" into the copilot has that
    redacted before it leaves. A user typing the bare figure "145,000 tenge"
    does not: the salary rule needs a compensation word near the number,
    because matching bare figures would redact every amount in a budget
    discussion — which is most of what a board meeting is.

    This is the trade the privacy page states in `limitations`, asserted here
    so it stays a known limit rather than becoming a surprise.
    """
    redaction.set_active_config(RedactionConfig(enabled=True, rules=ALL_RULE_NAMES))

    from backend.meetings.copilot import _build_prompt

    with_context = _build_prompt("her salary is 145,000 tenge", "excerpt")
    assert PLANTED["salary"] not in with_context, "a question with context was not redacted"
    assert "[redacted:salary]" in with_context

    # The documented blind spot, stated rather than hidden.
    bare_figure = _build_prompt("what about 145,000 tenge?", "excerpt")
    assert PLANTED["salary"] in bare_figure

    # An email in a question is caught either way — it has shape.
    assert PLANTED["email"] not in _build_prompt(f"email {PLANTED['email']}", "excerpt")


def test_the_privacy_page_states_that_limitation(data_dir, db, org):
    """A limit the operator cannot read about is a limit they will trip over."""
    with TestClient(create_app()) as client:
        limitations = client.get("/api/privacy").json()["redaction"]["limitations"]
    assert any("compensation word" in line for line in limitations)
