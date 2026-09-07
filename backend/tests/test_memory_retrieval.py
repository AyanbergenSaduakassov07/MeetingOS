"""Corpus-wide retrieval.

Seam under test: ``backend.memory.retrieval``'s three verbs and the
``MemoryIndex`` contract behind them. Tests go through ``search_corpus`` /
``index_meeting``, never against the SQLite backend's internals — a pgvector
backend must be able to pass this file unchanged.

The acceptance case is `test_query_spans_multiple_meetings_with_citations`:
"Aktau expansion" returns ranked results from more than one meeting, each with
a real Evidence citation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC

import pytest

from backend.ai.base import ProviderConfig
from backend.database import (
    Commitment,
    Decision,
    Evidence,
    Meeting,
    MeetingStatus,
    Organization,
    Topic,
    TranscriptSegment,
)
from backend.memory import (
    CapabilityError,
    MemoryRecord,
    get_memory_index,
    index_meeting,
    purge_meeting,
    reset_backends,
    retrieval as retrieval_module,
    search_corpus,
)


class FakeEmbedder:
    """Bag-of-words over a shared vocabulary axis.

    Deterministic so ranking assertions are about the retrieval code, not a
    model's judgement on any given day.
    """

    VOCAB = [
        "aktau",
        "expansion",
        "terminal",
        "kazakhstan",
        "site",
        "budget",
        "capex",
        "hiring",
        "salary",
        "canteen",
        "drilling",
        "rig",
        "safety",
        "audit",
        "invoice",
    ]

    def __init__(self) -> None:
        self.config = ProviderConfig(
            name="fake",
            model="fake-embed",
            api_key_env="NONE",
            embedding_model="fake-embed",
            supports_embeddings=True,
        )
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for entry in texts:
            words = {w.strip(".,()") for w in entry.lower().split()}
            vector = [1.0 if term in words else 0.0 for term in self.VOCAB]
            out.append(vector if any(vector) else [0.01] * len(self.VOCAB))
        return out


@pytest.fixture(autouse=True)
def _fresh_backend():
    reset_backends()
    yield
    reset_backends()


@pytest.fixture
def org(db):
    organization = Organization(name="KMG", slug="kmg")
    db.add(organization)
    db.commit()
    return organization


def build_meeting(db, org, title: str, claims: list[tuple[str, str]], topic_label: str) -> Meeting:
    """One meeting with a topic, and a Decision/Commitment per claim."""
    meeting = Meeting(
        org_id=org.id,
        title=title,
        status=MeetingStatus.COMPLETED.value,
        source="upload",
        language="en",
    )
    db.add(meeting)
    db.flush()
    db.add(Topic(meeting_id=meeting.id, label=topic_label, start_ms=0, end_ms=16000))

    for index, (kind, claim) in enumerate(claims):
        segment = TranscriptSegment(
            meeting_id=meeting.id,
            sequence=index,
            start_ms=index * 8000,
            end_ms=(index + 1) * 8000,
            text=claim,
        )
        db.add(segment)
        db.flush()
        evidence = Evidence(
            org_id=org.id,
            meeting_id=meeting.id,
            claim_text=claim,
            quote=claim,
            confidence=0.9,
            verification_status="verified",
        )
        evidence.cite(segment)
        db.add(evidence)
        if kind == "decision":
            db.add(Decision(org_id=org.id, meeting_id=meeting.id, title=claim, evidence=evidence))
        else:
            db.add(Commitment(org_id=org.id, meeting_id=meeting.id, text=claim, evidence=evidence))
    db.commit()
    return meeting


@pytest.fixture
def corpus(db, org):
    """Three meetings. Two discuss the Aktau expansion; one does not."""
    january = build_meeting(
        db,
        org,
        "January board",
        [
            ("decision", "Approve the Aktau expansion capex budget"),
            ("commitment", "I will circulate the Aktau terminal drawings"),
        ],
        topic_label="Aktau expansion",
    )
    march = build_meeting(
        db,
        org,
        "March board",
        [("decision", "Defer the Aktau expansion until the safety audit closes")],
        topic_label="Aktau site safety",
    )
    april = build_meeting(
        db,
        org,
        "April ops",
        [("decision", "Increase the canteen budget"), ("commitment", "I will review the drilling rig hiring plan")],
        topic_label="canteen and hiring",
    )
    embedder = FakeEmbedder()
    for meeting in (january, march, april):
        asyncio.run(index_meeting(meeting.id, embedder=embedder, db=db))
    return {"january": january, "march": march, "april": april, "embedder": embedder}


# -- acceptance ------------------------------------------------------------


def test_query_spans_multiple_meetings_with_citations(db, org, corpus):
    """Acceptance: ranked results across meetings, each with real Evidence."""
    results = asyncio.run(
        search_corpus("Aktau expansion", org_id=org.id, embedder=corpus["embedder"], db=db, min_score=0.1)
    )

    assert results, "no results for a query the corpus plainly covers"
    meetings = {record.meeting_id for record in results}
    assert len(meetings) >= 2, f"results came from only {len(meetings)} meeting(s)"
    assert corpus["january"].id in meetings
    assert corpus["march"].id in meetings

    # Ranked.
    scores = [record.score for record in results]
    assert scores == sorted(scores, reverse=True)

    # Every non-topic hit resolves to a real Evidence row.
    for record in results:
        assert record.meeting_title
        if record.record_type == "topic":
            continue
        assert record.evidence_id, f"{record.record_type} came back with no citation"
        assert db.query(Evidence).filter_by(id=record.evidence_id).one() is not None


def test_unrelated_meeting_is_not_returned(db, org, corpus):
    """Budgeted retrieval: the canteen meeting must not ride along."""
    results = asyncio.run(search_corpus("Aktau expansion", org_id=org.id, embedder=corpus["embedder"], db=db))
    assert corpus["april"].id not in {r.meeting_id for r in results}


# -- budgeting -------------------------------------------------------------


def test_limit_is_respected(db, org, corpus):
    results = asyncio.run(
        search_corpus("Aktau", org_id=org.id, limit=2, min_score=0.0, embedder=corpus["embedder"], db=db)
    )
    assert len(results) <= 2


def test_min_score_drops_weak_matches(db, org, corpus):
    generous = asyncio.run(
        search_corpus("Aktau", org_id=org.id, min_score=0.0, limit=50, embedder=corpus["embedder"], db=db)
    )
    strict = asyncio.run(
        search_corpus("Aktau", org_id=org.id, min_score=0.9, limit=50, embedder=corpus["embedder"], db=db)
    )
    assert len(strict) < len(generous), "min_score did not filter anything"
    assert all(record.score >= 0.9 for record in strict)


def test_limit_is_capped_regardless_of_caller(db, org, corpus):
    """A retrieval API that returns 1000 rows on request is a context bomb."""
    results = asyncio.run(
        search_corpus("Aktau", org_id=org.id, limit=100_000, min_score=0.0, embedder=corpus["embedder"], db=db)
    )
    assert len(results) <= retrieval_module.MAX_LIMIT


def test_empty_query_returns_nothing(db, org, corpus):
    assert asyncio.run(search_corpus("   ", org_id=org.id, embedder=corpus["embedder"], db=db)) == []


# -- scoping ---------------------------------------------------------------


def test_search_is_scoped_to_one_org(db, org, corpus):
    other = Organization(name="Other", slug="other")
    db.add(other)
    db.commit()
    secret = build_meeting(
        db,
        other,
        "Other org board",
        [("decision", "Approve the Aktau expansion for a different company")],
        topic_label="Aktau expansion",
    )
    asyncio.run(index_meeting(secret.id, embedder=corpus["embedder"], db=db))

    results = asyncio.run(
        search_corpus("Aktau expansion", org_id=org.id, min_score=0.0, limit=50, embedder=corpus["embedder"], db=db)
    )
    assert secret.id not in {r.meeting_id for r in results}, "cross-org leak"


def test_record_types_filter(db, org, corpus):
    results = asyncio.run(
        search_corpus(
            "Aktau expansion",
            org_id=org.id,
            record_types=("decision",),
            min_score=0.0,
            limit=50,
            embedder=corpus["embedder"],
            db=db,
        )
    )
    assert results
    assert {r.record_type for r in results} == {"decision"}


# -- the two retrieval paths ----------------------------------------------


def test_keyword_path_finds_a_term_the_embedder_cannot_represent(db, org, corpus):
    """A codename outside the embedding vocabulary is exactly BM25's job."""
    meeting = build_meeting(
        db,
        org,
        "Codename meeting",
        [("decision", "Proceed with project Zhaik under the existing mandate")],
        topic_label="project Zhaik",
    )
    asyncio.run(index_meeting(meeting.id, embedder=corpus["embedder"], db=db))

    keyword_only = asyncio.run(
        search_corpus("Zhaik", org_id=org.id, mode="keyword", min_score=0.0, embedder=corpus["embedder"], db=db)
    )
    assert meeting.id in {r.meeting_id for r in keyword_only}
    assert all(r.match == "keyword" for r in keyword_only)


def test_vector_path_finds_a_paraphrase_keywords_would_miss(db, org, corpus):
    """No shared token with the query, but the same subject."""
    results = asyncio.run(
        search_corpus(
            "terminal site kazakhstan", org_id=org.id, mode="vector", min_score=0.1, embedder=corpus["embedder"], db=db
        )
    )
    assert results
    assert all(r.vector_score is not None for r in results)


def test_hybrid_reports_which_path_matched(db, org, corpus):
    results = asyncio.run(
        search_corpus(
            "Aktau expansion", org_id=org.id, mode="hybrid", min_score=0.0, limit=50, embedder=corpus["embedder"], db=db
        )
    )
    assert {r.match for r in results} <= {"vector", "keyword", "hybrid"}
    assert any(r.keyword_score is not None for r in results), "keyword path contributed nothing"


def test_fts_query_with_punctuation_does_not_blow_up(db, org, corpus):
    """FTS5 treats punctuation as syntax; the query must be sanitised."""
    for hostile in ["Aktau expansion (Q3)", 'budget: "final"', "NEAR/2 OR AND", "*"]:
        assert isinstance(
            asyncio.run(search_corpus(hostile, org_id=org.id, min_score=0.0, embedder=corpus["embedder"], db=db)),
            list,
        )


# -- indexing lifecycle ----------------------------------------------------


def test_reindexing_is_idempotent_and_skips_unchanged(db, org, corpus):
    embedder = FakeEmbedder()
    first = asyncio.run(index_meeting(corpus["january"].id, embedder=embedder, db=db))
    assert first.embedded == 0, "nothing changed, yet records were re-embedded"
    assert first.skipped > 0


def test_changed_text_is_reindexed(db, org, corpus):
    decision = db.query(Decision).filter_by(meeting_id=corpus["january"].id).first()
    decision.title = "Approve the Aktau expansion capex budget and the hiring plan"
    db.commit()

    report = asyncio.run(index_meeting(corpus["january"].id, embedder=corpus["embedder"], db=db))
    assert report.embedded >= 1


def test_purging_a_meeting_removes_it_from_the_corpus(db, org, corpus):
    removed = asyncio.run(purge_meeting(corpus["january"].id, db=db))
    assert removed > 0

    results = asyncio.run(
        search_corpus("Aktau expansion", org_id=org.id, min_score=0.0, limit=50, embedder=corpus["embedder"], db=db)
    )
    assert corpus["january"].id not in {r.meeting_id for r in results}


# -- the seam itself -------------------------------------------------------


def test_backend_is_swappable_through_the_orchestrator(monkeypatch):
    """A future pgvector backend must drop in without touching call sites."""
    from backend.memory import orchestrator
    from backend.memory.base import MemoryIndex, MemoryIndexConfig

    class StubIndex(MemoryIndex):
        def __init__(self):
            super().__init__(MemoryIndexConfig(name="stub", supports_ann_index=True))

        async def index_meeting(self, meeting_id, *, embedder=None, db=None):
            return None

        async def index_document(self, document_id, *, embedder=None, db=None):
            return None

        async def search(self, query, **kwargs):
            return [MemoryRecord(record_type="decision", record_id="x", text="stub")]

        async def delete_meeting(self, meeting_id, *, db=None):
            return 0

        async def delete_document(self, document_id, *, db=None):
            return 0

    monkeypatch.setitem(orchestrator.BACKENDS, "stub", StubIndex)
    monkeypatch.setenv("MEETINGOS_MEMORY_BACKEND", "stub")
    reset_backends()

    assert get_memory_index().config.name == "stub"
    results = asyncio.run(search_corpus("anything"))
    assert results[0].text == "stub"


def test_unknown_backend_fails_with_a_useful_message(monkeypatch):
    from backend.memory import UnknownBackendError

    monkeypatch.setenv("MEETINGOS_MEMORY_BACKEND", "pineconeish")
    reset_backends()
    with pytest.raises(UnknownBackendError, match="Available"):
        get_memory_index()


def test_backend_refuses_a_path_it_does_not_support():
    """A keyword-only backend asked for vector search must say so, not degrade."""
    from backend.memory.base import MemoryIndex, MemoryIndexConfig

    class KeywordOnly(MemoryIndex):
        def __init__(self):
            super().__init__(MemoryIndexConfig(name="kw", supports_vector=False))

        async def index_meeting(self, meeting_id, *, embedder=None, db=None):
            return None

        async def index_document(self, document_id, *, embedder=None, db=None):
            return None

        async def search(self, query, **kwargs):
            return []

        async def delete_meeting(self, meeting_id, *, db=None):
            return 0

        async def delete_document(self, document_id, *, db=None):
            return 0

    with pytest.raises(CapabilityError, match="vector"):
        KeywordOnly()._check_mode("hybrid")


def test_health_describes_the_backend_honestly():
    index = get_memory_index()
    health = asyncio.run(index.health())
    assert health["backend"] == "sqlite"
    # The SQLite backend must not claim an ANN index it does not have.
    assert health["supports_ann_index"] is False


def test_retention_purge_removes_corpus_index_entries(db, org, corpus):
    """A purged meeting must not remain findable in cross-meeting search."""
    from datetime import datetime, timedelta

    from backend.meetings import retention

    january_id = corpus["january"].id  # captured before the row is deleted
    org.retention_days = 30
    january = db.query(Meeting).filter_by(id=january_id).one()
    january.created_at = datetime.now(UTC) - timedelta(days=90)
    db.commit()

    retention.purge_expired(db, commit=True)

    results = asyncio.run(
        search_corpus("Aktau expansion", org_id=org.id, min_score=0.0, limit=50, embedder=corpus["embedder"], db=db)
    )
    assert january_id not in {r.meeting_id for r in results}, "purged meeting still in the index"


def test_duplicate_records_for_one_claim_collapse_to_the_most_specific(db, org, corpus):
    """A claim indexed as both Decision and Evidence must not take two slots."""
    results = asyncio.run(
        search_corpus("Aktau expansion", org_id=org.id, min_score=0.0, limit=50, embedder=corpus["embedder"], db=db)
    )
    evidence_ids = [r.evidence_id for r in results if r.evidence_id]
    assert len(evidence_ids) == len(set(evidence_ids)), "same claim returned more than once"
    # The Decision survives, not the bare Evidence row.
    assert "evidence" not in {r.record_type for r in results if r.evidence_id}


def test_collapsing_can_be_turned_off(db, org, corpus):
    raw = asyncio.run(
        search_corpus(
            "Aktau expansion",
            org_id=org.id,
            min_score=0.0,
            limit=50,
            collapse_duplicates=False,
            embedder=corpus["embedder"],
            db=db,
        )
    )
    assert "evidence" in {r.record_type for r in raw}
