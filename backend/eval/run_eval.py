#!/usr/bin/env python3
"""Score the extraction pipeline against the frozen eval cases.

    python -m backend.eval.run_eval                  # score with the configured provider
    python -m backend.eval.run_eval --ci             # same, non-zero exit if below threshold
    python -m backend.eval.run_eval --baseline       # write thresholds.json from this run
    python -m backend.eval.run_eval --case 04        # one case, verbose

What it measures
----------------
Per kind (decision / action_item / risk / commitment), matching extracted items
to expected ones by embedding similarity against the expected ``gist`` — not by
string equality. Two humans write the same decision two ways; so does a model,
and a scorer that demands exact text measures phrasing, not extraction.

Four dimensions are reported separately, because one number hides the failure
that matters. An extraction that finds every decision but cites the wrong
segment scores well on recall and badly on citation accuracy, and only the
second of those makes the product untrustworthy:

- **precision** — of what was extracted, how much was real
- **recall** — of what was there, how much was found
- **citation accuracy** — of matched items, how many cite the right segment
- **honesty** — on cases expecting nothing, how often nothing was returned

Scores are also broken out by complexity stratum, so three easy cases cannot
paper over failures on the hard ones.

Thresholds
----------
``thresholds.json`` is written by ``--baseline`` from a real run and read by
``--ci``. It is deliberately not hand-guessed: a threshold invented before
seeing a real number either passes everything or fails everything. Until a
baseline exists against a live provider, ``--ci`` says so and exits non-zero
rather than pretending to a verdict.

Provenance caveat
-----------------
The cases are hand-authored, not cut from real recordings — see
``backend/tests/eval_cases/README.md``. Scores here bound extraction behaviour
on clean text; they do not measure performance on real speech.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("eval")

CASES_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval_cases"
THRESHOLDS_PATH = Path(__file__).resolve().parent / "thresholds.json"

KINDS = ("decisions", "action_items", "risks", "commitments")

# An extracted item counts as the expected one when its text is at least this
# similar to the expected gist. Tuned so a legitimate rewording matches while
# two genuinely different decisions do not.
MATCH_THRESHOLD = 0.62

# Margin applied when writing thresholds from a baseline: CI fails on a real
# regression, not on ordinary run-to-run variation in a non-deterministic model.
REGRESSION_MARGIN = 0.10


@dataclass
class KindScore:
    expected: int = 0
    extracted: int = 0
    matched: int = 0
    correctly_cited: int = 0

    @property
    def precision(self) -> float:
        return self.matched / self.extracted if self.extracted else 1.0

    @property
    def recall(self) -> float:
        return self.matched / self.expected if self.expected else 1.0

    @property
    def citation_accuracy(self) -> float:
        return self.correctly_cited / self.matched if self.matched else 1.0


@dataclass
class CaseResult:
    name: str
    complexity: str
    scores: dict[str, KindScore] = field(default_factory=dict)
    forbidden_hits: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def totals(self) -> KindScore:
        total = KindScore()
        for score in self.scores.values():
            total.expected += score.expected
            total.extracted += score.extracted
            total.matched += score.matched
            total.correctly_cited += score.correctly_cited
        return total

    @property
    def expects_nothing(self) -> bool:
        return self.totals.expected == 0

    @property
    def honest(self) -> bool:
        """For a case expecting nothing, did it return nothing?"""
        return self.totals.extracted == 0


COMPARATOR_DIR = CASES_DIR / "comparator"
CROSSLINGUAL_DIR = CASES_DIR / "crosslingual"


async def run_crosslingual_suite(*, embedder=None, verbose: bool = False) -> dict:
    """Measure whether the configured embedding model actually aligns languages.

    This exists because "use a multilingual model" is an assumption, and the
    brief was explicit about not shipping on one. Each case indexes a
    should-retrieve and a should-not-retrieve record in the source language,
    then queries in a different language and checks the right one ranks first.

    A model that passes RU<->EN and fails KZ is a useful finding, not a
    failure of the harness: Kazakh is far less represented in embedding
    training data, and knowing that before a customer discovers it is the
    entire point of running this.
    """
    import json as _json
    import tempfile
    import uuid as _uuid

    from backend import config as _config
    from backend.database import (
        Evidence,
        Meeting,
        Organization,
        TranscriptSegment,
        init_db,
        new_session,
    )
    from backend.memory import index_meeting, reset_backends, search_corpus

    cases = [_json.loads(p.read_text()) for p in sorted(CROSSLINGUAL_DIR.glob("*.json"))]
    if not cases:
        return {"cases": 0}

    # Its own database: this indexes throwaway records and must not touch the
    # extraction eval's corpus, let alone a real one.
    _config.set_data_dir(Path(tempfile.mkdtemp(prefix="meetingos-crosslingual-")))
    init_db()
    reset_backends()

    if embedder is None:
        from backend.ai import get_embedding_provider

        embedder = get_embedding_provider()

    db = new_session()
    rows = []
    try:
        org = Organization(name="Crosslingual", slug=f"xl-{_uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()

        for case in cases:
            meeting = Meeting(
                org_id=org.id,
                title=f"xl:{case['name']}",
                status="completed",
                source="upload",
                language=case["source_language"],
            )
            db.add(meeting)
            db.flush()
            wanted_id = None
            for index, text in enumerate((case["should_retrieve"], case["should_not_retrieve"])):
                segment = TranscriptSegment(
                    meeting_id=meeting.id,
                    sequence=index,
                    start_ms=index * 10000,
                    end_ms=(index + 1) * 10000,
                    text=text,
                    language=case["source_language"],
                )
                db.add(segment)
                db.flush()
                evidence = Evidence(
                    org_id=org.id,
                    meeting_id=meeting.id,
                    claim_text=text,
                    quote=text,
                    verification_status="verified",
                )
                evidence.cite(segment)
                db.add(evidence)
                db.flush()
                if index == 0:
                    wanted_id = evidence.id
            db.commit()

            await index_meeting(meeting.id, embedder=embedder, db=db)

            try:
                results = await search_corpus(
                    case["query"],
                    org_id=org.id,
                    record_types=("evidence",),
                    limit=5,
                    min_score=0.0,
                    mode="vector",
                    embedder=embedder,
                    db=db,
                )
                top = results[0].record_id if results else None
                hit = top == wanted_id
                error = None
            except Exception as exc:
                hit, error = False, f"{type(exc).__name__}: {exc}"

            rows.append(
                {
                    "name": case["name"],
                    "query_language": case["query_language"],
                    "source_language": case["source_language"],
                    "retrieved_correctly": hit,
                    "error": error,
                }
            )
            if verbose:
                mark = "ok " if hit else "MISS"
                print(f"    {mark} {case['name']:<36} {case['query_language']}->{case['source_language']}")
    finally:
        db.close()

    correct = sum(1 for r in rows if r["retrieved_correctly"])
    by_pair: dict[str, list[bool]] = {}
    for row in rows:
        by_pair.setdefault(f"{row['query_language']}->{row['source_language']}", []).append(row["retrieved_correctly"])
    return {
        "cases": len(rows),
        "accuracy": round(correct / len(rows), 4),
        "by_language_pair": {k: round(sum(v) / len(v), 4) for k, v in by_pair.items()},
        "missed": [r["name"] for r in rows if not r["retrieved_correctly"]],
        "rows": rows,
    }


COPILOT_DIR = CASES_DIR / "copilot"
FUSION_DIR = CASES_DIR / "fusion"


def _corpus_metrics(rows: list[dict]) -> dict:
    """Precision and recall over citations, plus the behaviours that gate them.

    Citations are scored as a retrieval problem because that is what they are:
    of the records the answer cited, how many were the ones that actually
    answer the question (precision), and of the records that do, how many were
    cited (recall). Both are computed over the pooled record set rather than
    averaged per case, so a case citing ten records cannot be outvoted by one
    citing a single record.

    Answered and refused cases are separated everywhere. A model that refuses
    everything scores perfect precision on citations it never made, and one
    that answers everything scores perfect recall on questions it should have
    declined. Neither number means anything without the other two below it.
    """
    # Cases that never reached the model are excluded from every quality number
    # and reported as coverage instead. Scoring them folded a rate limit into
    # "citation precision 0.00", which does not read as "not measured" — it
    # reads as "the copilot cites nothing", and that is a false statement about
    # the product dressed up as a metric.
    scored = [r for r in rows if not r["error"]]
    answered = [r for r in scored if r["expects_answer"]]
    refusals = [r for r in scored if not r["expects_answer"]]

    cited = sum(len(r["cited_keys"]) for r in answered)
    correct = sum(len(set(r["cited_keys"]) & set(r["relevant_keys"])) for r in answered)
    wanted = sum(len(r["must_cite"]) for r in answered)
    found = sum(len(set(r["cited_keys"]) & set(r["must_cite"])) for r in answered)

    grounded = [r for r in answered if r["must_contain_any"]]
    return {
        "cases": len(rows),
        "scored": len(scored),
        "coverage": round(len(scored) / len(rows), 4) if rows else 0.0,
        "answerable": len(answered),
        "unanswerable": len(refusals),
        "citation_precision": round(correct / cited, 4) if cited else 0.0,
        "citation_recall": round(found / wanted, 4) if wanted else 1.0,
        "answer_accuracy": round(sum(1 for r in grounded if r["contains_required"]) / len(grounded), 4)
        if grounded
        else 1.0,
        "refusal_accuracy": round(sum(1 for r in refusals if r["refused"]) / len(refusals), 4) if refusals else 1.0,
        "false_answer_rate": round(sum(1 for r in refusals if not r["refused"]) / len(refusals), 4)
        if refusals
        else 0.0,
        "span_accuracy": round(sum(1 for r in answered if r["spanned_ok"]) / len(answered), 4) if answered else 1.0,
        "injection_failures": [r["name"] for r in scored if r["forbidden_hits"]],
        "errors": [f"{r['name']}: {r['error']}" for r in rows if r["error"]],
        "rows": rows,
    }


async def run_corpus_suite(
    directory,
    *,
    provider=None,
    embedder=None,
    mode: str = "hybrid",
    verbose: bool = False,
) -> dict:
    """Score org-wide copilot answers over a corpus built from each case.

    Serves both the cross-meeting suite and the document-fusion suite: a fusion
    case is a cross-meeting case that also carries ``documents``, and the code
    that builds, indexes and scores them is identical. Keeping one runner means
    a scoring change cannot silently apply to one suite and not the other.

    Each case gets its own throwaway database *and* its own org. Sharing either
    would let one case's records answer another case's question, which would
    turn a retrieval failure into a pass.
    """
    import json as _json
    import tempfile as _tempfile
    import uuid as _uuid

    from backend import config as _config
    from backend.database import (
        Document,
        DocumentChunk,
        Evidence,
        Meeting,
        Organization,
        TranscriptSegment,
        init_db,
        new_session,
    )
    from backend.memory import index_document, index_meeting, reset_backends
    from backend.memory.org_copilot import ask_corpus

    cases = [_json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]
    if not cases:
        return {"cases": 0}

    if provider is None:
        from backend.ai import get_llm_provider

        provider = get_llm_provider()

    _config.set_data_dir(Path(_tempfile.mkdtemp(prefix=f"meetingos-{directory.name}-")))
    init_db()
    reset_backends()

    rows = []
    for case in cases:
        db = new_session()
        try:
            org = Organization(name=case["name"], slug=f"{directory.name}-{_uuid.uuid4().hex[:8]}")
            db.add(org)
            db.flush()

            # record_id -> case key, so scoring never depends on generated ids.
            key_of: dict[str, str] = {}
            kind_of: dict[str, str] = {}
            relevant: set[str] = set()

            for meeting_case in case.get("meetings", []):
                meeting = Meeting(
                    org_id=org.id,
                    title=meeting_case["title"],
                    status="completed",
                    source="upload",
                    language=meeting_case.get("language", "en"),
                )
                db.add(meeting)
                db.flush()
                for index, record in enumerate(meeting_case["records"]):
                    segment = TranscriptSegment(
                        meeting_id=meeting.id,
                        sequence=index,
                        start_ms=index * 10000,
                        end_ms=(index + 1) * 10000,
                        text=record["text"],
                        language=meeting_case.get("language", "en"),
                    )
                    db.add(segment)
                    db.flush()
                    evidence = Evidence(
                        org_id=org.id,
                        meeting_id=meeting.id,
                        claim_text=record["text"],
                        quote=record["text"],
                        verification_status=record.get("verification_status", "verified"),
                    )
                    evidence.cite(segment)
                    db.add(evidence)
                    db.flush()
                    key_of[evidence.id] = record["key"]
                    kind_of[record["key"]] = "meeting"
                    if record.get("relevant"):
                        relevant.add(record["key"])
                db.commit()
                await index_meeting(meeting.id, embedder=embedder, db=db)

            for document_case in case.get("documents", []):
                document = Document(
                    org_id=org.id,
                    title=document_case["title"],
                    storage_path=f"eval/{_uuid.uuid4().hex}.pdf",
                    language=document_case.get("language", "en"),
                )
                db.add(document)
                db.flush()
                for ordinal, chunk_case in enumerate(document_case["chunks"]):
                    chunk = DocumentChunk(
                        org_id=org.id,
                        document_id=document.id,
                        ordinal=ordinal,
                        page=1,
                        text=chunk_case["text"],
                        language=document_case.get("language", "en"),
                    )
                    db.add(chunk)
                    db.flush()
                    key_of[chunk.id] = chunk_case["key"]
                    kind_of[chunk_case["key"]] = "document"
                    if chunk_case.get("relevant"):
                        relevant.add(chunk_case["key"])
                db.commit()
                await index_document(document.id, embedder=embedder, db=db)

            error = None
            try:
                answer = await ask_corpus(
                    case["question"],
                    org_id=org.id,
                    provider=provider,
                    embedder=embedder,
                    db=db,
                )
                cited_keys = [key_of[c.record_id] for c in answer.citations if c.record_id in key_of]
                unknown = [c.record_id for c in answer.citations if c.record_id not in key_of]
                answer_text = answer.answer or ""
                refused = answer.not_discussed
                spanned = {kind_of.get(k) for k in cited_keys}
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                cited_keys, unknown, answer_text, refused, spanned = [], [], "", False, set()

            lowered = answer_text.lower()
            forbidden = [p for p in case.get("must_not_contain", []) if p.lower() in lowered]
            wanted_any = case.get("must_contain_any", [])
            contains = (not wanted_any) or any(p.lower() in lowered for p in wanted_any)

            required_kinds = set(case.get("must_span_kinds", []))
            if not required_kinds and case.get("min_meetings_spanned", 0) > 1:
                spanned_ok = len({k for k in cited_keys}) >= case["min_meetings_spanned"]
            else:
                spanned_ok = required_kinds <= spanned if required_kinds else True

            rows.append(
                {
                    "name": case["name"],
                    "complexity": case.get("complexity", "unknown"),
                    "expects_answer": case["expects_answer"],
                    "must_cite": case.get("must_cite", []),
                    "relevant_keys": sorted(relevant),
                    "cited_keys": cited_keys,
                    "unknown_citations": unknown,
                    "refused": refused,
                    "contains_required": contains and not refused if case["expects_answer"] else True,
                    "must_contain_any": wanted_any,
                    "spanned_ok": spanned_ok,
                    "forbidden_hits": forbidden,
                    "answer": answer_text[:400],
                    "error": error,
                }
            )
            if verbose:
                verdict = "REFUSED" if refused else f"cited {cited_keys}"
                print(f"    {case['name']:<38} {verdict}")
                if forbidden:
                    print(f"      !! forbidden text in answer: {forbidden}")
        finally:
            db.close()

    return _corpus_metrics(rows)


async def run_comparator_suite(*, provider=None, verbose: bool = False) -> dict:
    """Score the claim comparator against its hand-built cases.

    Reported separately from extraction because it measures a different thing:
    extraction asks "did you find what was said", the comparator asks "is this
    a conflict". A near-miss false positive matters more here than a miss —
    a wrongly reported contradiction sends a board to re-litigate a decision
    that was never in question, so precision on the near-miss set is the
    number to watch.
    """
    import json as _json

    from backend.memory.comparator import CONFLICTING, ClaimRelationship, _build_prompt

    cases = [_json.loads(p.read_text()) for p in sorted(COMPARATOR_DIR.glob("*.json"))]
    if not cases:
        return {"cases": 0}

    if provider is None:
        from backend.ai import get_llm_provider

        provider = get_llm_provider()

    rows = []
    for case in cases:
        prompt = _build_prompt(
            case["prior"]["claim"],
            "prior-evidence-id",
            case["prior"]["meeting"],
            case["new"]["claim"],
            "new-evidence-id",
            case["new"]["meeting"],
        )
        try:
            from backend.memory.comparator import _SYSTEM_PROMPT

            result = await provider.extract(prompt, ClaimRelationship, system=_SYSTEM_PROMPT)
            got = result.relationship
            error = None
        except Exception as exc:
            got, error = None, f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "name": case["name"],
                "kind": case["kind"],
                "expected": case["expected"],
                "got": got,
                "error": error,
            }
        )
        if verbose:
            print(f"    {case['name']:<34} expected={case['expected']:<13} got={got}")

    correct = sum(1 for r in rows if r["got"] == r["expected"])
    near = [r for r in rows if r["kind"] == "near_miss"]
    false_positives = [r for r in near if r["got"] in CONFLICTING]
    genuine = [r for r in rows if r["kind"] == "genuine"]
    missed = [r for r in genuine if r["got"] not in CONFLICTING]

    return {
        "cases": len(rows),
        "accuracy": round(correct / len(rows), 4),
        "false_positive_rate": round(len(false_positives) / len(near), 4) if near else 0.0,
        "missed_conflict_rate": round(len(missed) / len(genuine), 4) if genuine else 0.0,
        "false_positives": [r["name"] for r in false_positives],
        "missed": [r["name"] for r in missed],
        "rows": rows,
    }


def load_cases(filter_text: str | None = None) -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.json")):  # top level only; comparator/ is separate
        case = json.loads(path.read_text())
        if filter_text and filter_text not in case["name"]:
            continue
        cases.append(case)
    if not cases:
        raise SystemExit(f"No eval cases matched in {CASES_DIR}")
    return cases


def _cosine(left: list[float], right: list[float]) -> float:
    from backend.meetings.segmentation import cosine_similarity

    return cosine_similarity(left, right)


async def _score_kind(
    embedder,
    expected: list[dict],
    extracted: list,
    segment_ids: list[str],
    text_of,
) -> KindScore:
    """Greedy best-match between extracted items and expected gists."""
    score = KindScore(expected=len(expected), extracted=len(extracted))
    if not expected or not extracted:
        return score

    gists = [item["gist"] for item in expected]
    texts = [text_of(item) for item in extracted]
    vectors = await embedder.embed(gists + texts)
    gist_vectors = vectors[: len(gists)]
    text_vectors = vectors[len(gists) :]

    pairs = sorted(
        ((_cosine(gist_vectors[gi], text_vectors[ti]), gi, ti) for gi in range(len(gists)) for ti in range(len(texts))),
        reverse=True,
    )

    used_expected: set[int] = set()
    used_extracted: set[int] = set()
    for similarity, gi, ti in pairs:
        if similarity < MATCH_THRESHOLD:
            break
        if gi in used_expected or ti in used_extracted:
            continue
        used_expected.add(gi)
        used_extracted.add(ti)
        score.matched += 1

        want_index = expected[gi].get("cites_segment")
        got = getattr(extracted[ti], "source_segment_id", None)
        if want_index is not None and 0 <= want_index < len(segment_ids):
            if got == segment_ids[want_index]:
                score.correctly_cited += 1
        else:
            score.correctly_cited += 1

    return score


async def run_case(case: dict, *, provider=None, embedder=None, verbose: bool = False) -> CaseResult:
    """Build a throwaway meeting from the case, extract, and score."""
    from backend.database import (
        ActionItem,
        Commitment,
        Decision,
        Meeting,
        MeetingStatus,
        Organization,
        Risk,
        Speaker,
        TranscriptSegment,
        new_session,
    )
    from backend.meetings.intelligence import extract_meeting_intelligence

    result = CaseResult(name=case["name"], complexity=case.get("complexity", "unknown"))
    db = new_session()
    meeting_id: str | None = None
    try:
        org = db.query(Organization).first()
        if org is None:
            org = Organization(name="Eval", slug="eval")
            db.add(org)
            db.flush()

        meeting = Meeting(
            org_id=org.id,
            title=f"eval:{case['name']}",
            status=MeetingStatus.COMPLETED.value,
            source="upload",
            language="en",
        )
        db.add(meeting)
        db.flush()
        meeting_id = meeting.id

        speakers: dict[str, str] = {}
        segment_ids: list[str] = []
        for index, raw in enumerate(case["segments"]):
            label = raw["speaker"]
            if label not in speakers:
                speaker = Speaker(meeting_id=meeting.id, display_label=label)
                db.add(speaker)
                db.flush()
                speakers[label] = speaker.id
            segment = TranscriptSegment(
                meeting_id=meeting.id,
                speaker_id=speakers[label],
                sequence=index,
                start_ms=raw["start_ms"],
                end_ms=raw["end_ms"],
                text=raw["text"],
            )
            db.add(segment)
            db.flush()
            segment_ids.append(segment.id)
        db.commit()

        try:
            await extract_meeting_intelligence(meeting.id, provider=provider, run_verification=False)
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"

        if embedder is None:
            from backend.ai import get_embedding_provider

            embedder = get_embedding_provider()

        models = {
            "decisions": (Decision, lambda item: f"{item.title} {item.description or ''}".strip()),
            "action_items": (ActionItem, lambda item: f"{item.title} {item.description or ''}".strip()),
            "risks": (Risk, lambda item: f"{item.title} {item.description or ''}".strip()),
            "commitments": (Commitment, lambda item: item.text or ""),
        }
        all_text: list[str] = []
        for kind, (model, text_of) in models.items():
            rows = db.query(model).filter_by(meeting_id=meeting.id).all()
            all_text.extend(text_of(row) for row in rows)
            result.scores[kind] = await _score_kind(
                embedder, case["expected"].get(kind, []), rows, segment_ids, text_of
            )
            if verbose:
                for row in rows:
                    print(f"      [{kind}] {text_of(row)[:90]}")

        blob = " ".join(all_text).lower()
        result.forbidden_hits = [phrase for phrase in case.get("must_not_contain", []) if phrase.lower() in blob]

        return result
    finally:
        # Leave no eval meetings behind, on any path. This used to sit after an
        # early `return` on extraction failure, so a failing case leaked its
        # synthetic meeting into whatever database the run was pointed at — and
        # the default was the operator's real one. Both halves of that are fixed:
        # cleanup is unconditional here, and `--data-dir` now defaults to a
        # scratch directory.
        try:
            from backend.database import Evidence, EvidenceCitation

            if meeting_id is not None:
                evidence_ids = [row.id for row in db.query(Evidence).filter_by(meeting_id=meeting_id).all()]
                if evidence_ids:
                    # Citations reference segments, so they go before them.
                    db.query(EvidenceCitation).filter(EvidenceCitation.evidence_id.in_(evidence_ids)).delete(
                        synchronize_session=False
                    )
                for model in (Decision, ActionItem, Risk, Commitment):
                    db.query(model).filter_by(meeting_id=meeting_id).delete(synchronize_session=False)
                for model in (Evidence, TranscriptSegment, Speaker):
                    db.query(model).filter_by(meeting_id=meeting_id).delete(synchronize_session=False)
                db.query(Meeting).filter_by(id=meeting_id).delete(synchronize_session=False)
                db.commit()
        except Exception as exc:  # cleanup must not mask the real result
            logger.warning("Eval cleanup failed for %s: %s", meeting_id, exc)
            db.rollback()
        db.close()


def aggregate(results: list[CaseResult]) -> dict:
    """Overall and per-stratum metrics."""

    def metrics(subset: list[CaseResult]) -> dict:
        # Same rule as the corpus suites: a case that never reached the model
        # is missing data, not a recall of zero. Scoring 429s as misses turned
        # an exhausted rate limit into "extraction finds nothing", which is a
        # false statement about the pipeline printed as a metric.
        scored_count, subset = len(subset), [case for case in subset if not case.error]
        total = KindScore()
        for case in subset:
            case_total = case.totals
            total.expected += case_total.expected
            total.extracted += case_total.extracted
            total.matched += case_total.matched
            total.correctly_cited += case_total.correctly_cited
        honesty_cases = [case for case in subset if case.expects_nothing]
        honesty = sum(1 for case in honesty_cases if case.honest) / len(honesty_cases) if honesty_cases else 1.0
        return {
            "precision": round(total.precision, 4),
            "recall": round(total.recall, 4),
            "citation_accuracy": round(total.citation_accuracy, 4),
            "honesty": round(honesty, 4),
            "cases": scored_count,
            "scored": len(subset),
            "coverage": round(len(subset) / scored_count, 4) if scored_count else 0.0,
            "expected_items": total.expected,
            "extracted_items": total.extracted,
        }

    per_kind = {}
    clean = [case for case in results if not case.error]
    for kind in KINDS:
        total = KindScore()
        for case in clean:
            score = case.scores.get(kind)
            if score is None:
                continue
            total.expected += score.expected
            total.extracted += score.extracted
            total.matched += score.matched
            total.correctly_cited += score.correctly_cited
        per_kind[kind] = {
            "precision": round(total.precision, 4),
            "recall": round(total.recall, 4),
            "expected": total.expected,
            "extracted": total.extracted,
        }

    strata = sorted({case.complexity for case in results})
    return {
        "overall": metrics(results),
        "by_complexity": {
            stratum: metrics([case for case in results if case.complexity == stratum]) for stratum in strata
        },
        "by_kind": per_kind,
        "errors": [f"{case.name}: {case.error}" for case in results if case.error],
        "forbidden_content": [f"{case.name}: {case.forbidden_hits}" for case in results if case.forbidden_hits],
    }


def report(summary: dict, results: list[CaseResult]) -> None:
    print("\n" + "=" * 74)
    print("EXTRACTION EVAL")
    print("=" * 74)
    print(f"{'case':<34}{'stratum':<13}{'prec':>7}{'rec':>7}{'cite':>7}")
    print("-" * 74)
    for case in results:
        total = case.totals
        flag = "  ERROR" if case.error else ("  FORBIDDEN" if case.forbidden_hits else "")
        print(
            f"{case.name:<34}{case.complexity:<13}"
            f"{total.precision:>7.2f}{total.recall:>7.2f}{total.citation_accuracy:>7.2f}{flag}"
        )

    print("-" * 74)
    overall = summary["overall"]
    print(
        f"{'OVERALL':<34}{'':<13}"
        f"{overall['precision']:>7.2f}{overall['recall']:>7.2f}{overall['citation_accuracy']:>7.2f}"
    )
    print(f"\nhonesty (cases expecting nothing that returned nothing): {overall['honesty']:.2f}")
    if overall["scored"] < overall["cases"]:
        print(
            f"\nPARTIAL — {overall['scored']} of {overall['cases']} case(s) reached the model. "
            "Every number above covers only those; see ERRORS below."
        )

    print("\nby complexity:")
    for stratum, metrics in summary["by_complexity"].items():
        print(
            f"  {stratum:<13} precision {metrics['precision']:.2f}  "
            f"recall {metrics['recall']:.2f}  cite {metrics['citation_accuracy']:.2f}  "
            f"({metrics['cases']} case(s))"
        )

    print("\nby kind:")
    for kind, metrics in summary["by_kind"].items():
        print(
            f"  {kind:<14} precision {metrics['precision']:.2f}  recall {metrics['recall']:.2f}  "
            f"(expected {metrics['expected']}, extracted {metrics['extracted']})"
        )

    if summary["errors"]:
        print("\nERRORS:")
        for line in summary["errors"]:
            print(f"  {line}")
    if summary["forbidden_content"]:
        print("\nFORBIDDEN CONTENT (injection payload reached an extracted item):")
        for line in summary["forbidden_content"]:
            print(f"  {line}")


def _report_corpus(label: str, summary: dict) -> None:
    """Print one corpus suite's numbers, refusals kept beside the answers."""
    if not summary.get("cases"):
        print(f"  no {label} cases found")
        return
    if not summary.get("scored"):
        print(
            f"  NOT MEASURED — all {summary['cases']} case(s) failed before reaching the model.\n"
            "  No score is reported: a provider failure is missing data, not a result."
        )
        for line in summary["errors"][:2]:
            print(f"  ERROR {line[:150]}")
        return
    if summary["scored"] < summary["cases"]:
        print(
            f"  PARTIAL — {summary['scored']} of {summary['cases']} case(s) reached the model; "
            "the numbers below cover only those."
        )
    print(
        f"  citation precision {summary['citation_precision']:.2f}  "
        f"citation recall {summary['citation_recall']:.2f}  "
        f"answer accuracy {summary['answer_accuracy']:.2f}"
    )
    print(
        f"  refusal accuracy   {summary['refusal_accuracy']:.2f}  "
        f"false answers {summary['false_answer_rate']:.2f}  "
        f"source-span accuracy {summary['span_accuracy']:.2f}"
    )
    print(
        f"  ({summary['answerable']} answerable, {summary['unanswerable']} unanswerable, "
        f"coverage {summary['coverage']:.2f} of {summary['cases']} case(s))"
    )
    if summary["injection_failures"]:
        print(f"  INJECTION FAILURES: {summary['injection_failures']}")
    for line in summary["errors"]:
        print(f"  ERROR {line}")


def _spread(runs: list[dict]) -> dict:
    """Mean, min and max of each headline metric across repeated runs.

    A single run of a non-deterministic model is a sample, not a measurement.
    Two runs of this suite over identical inputs returned recall 0.38 and 0.92,
    and extracted three risks one time and ten the next — so a threshold set
    from one run either passes everything or fails everything, which is the
    same failure `thresholds.json` already refuses to commit for a different
    reason. Reporting the spread makes the variance visible instead of letting
    whichever run happened to be last stand in for the model's behaviour.
    """
    metrics = ("precision", "recall", "citation_accuracy", "honesty")
    out: dict[str, dict] = {"runs": len(runs)}
    for metric in metrics:
        values = [run["overall"][metric] for run in runs]
        out[metric] = {
            "mean": round(sum(values) / len(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "values": [round(v, 4) for v in values],
        }
    return out


def report_spread(spread: dict) -> None:
    print("\n" + "=" * 74)
    print(f"ACROSS {spread['runs']} RUNS")
    print("=" * 74)
    print(f"{'metric':<20}{'mean':>8}{'min':>8}{'max':>8}   values")
    for metric in ("precision", "recall", "citation_accuracy", "honesty"):
        row = spread[metric]
        values = " ".join(f"{v:.2f}" for v in row["values"])
        print(f"{metric:<20}{row['mean']:>8.2f}{row['min']:>8.2f}{row['max']:>8.2f}   {values}")
        band = row["max"] - row["min"]
        if band >= 0.25:
            print(f"{'':20}   ^ spread of {band:.2f} — one run of this is not a measurement")


def check_thresholds(summary: dict) -> tuple[bool, list[str]]:
    if not THRESHOLDS_PATH.exists():
        return False, [
            f"No {THRESHOLDS_PATH.name}. Thresholds must come from a real baseline run, not a "
            "guess: run `python -m backend.eval.run_eval --baseline` against a live provider "
            "first. Refusing to emit a pass/fail verdict without one."
        ]

    thresholds = json.loads(THRESHOLDS_PATH.read_text())
    failures = []
    overall = summary["overall"]
    for metric, floor in thresholds.get("overall", {}).items():
        if overall.get(metric, 0.0) < floor:
            failures.append(f"overall {metric} {overall.get(metric):.3f} < {floor:.3f}")
    for stratum, metrics in thresholds.get("by_complexity", {}).items():
        actual = summary["by_complexity"].get(stratum, {})
        for metric, floor in metrics.items():
            if actual.get(metric, 0.0) < floor:
                failures.append(f"{stratum} {metric} {actual.get(metric):.3f} < {floor:.3f}")

    if summary["errors"]:
        failures.append(f"{len(summary['errors'])} case(s) raised")
    if summary["forbidden_content"]:
        failures.append("injection payload text reached an extracted item")

    return not failures, failures


def write_baseline(summary: dict, provider_name: str) -> None:
    worst = summary.get("spread")

    def floors(metrics: dict) -> dict:
        return {
            metric: round(
                max(0.0, (worst[metric]["min"] if worst and metric in worst else metrics[metric]) - REGRESSION_MARGIN),
                4,
            )
            for metric in ("precision", "recall", "citation_accuracy", "honesty")
        }

    observed = summary.get("spread")
    payload = {
        "_comment": (
            "Written by --baseline from observed runs, minus a "
            f"{REGRESSION_MARGIN} margin for model non-determinism. Where several runs "
            "were made, the floor is taken from the WORST run, not the mean: CI should "
            "fail on a regression, and a mean hides the run that already regressed. "
            "Regenerate when the provider, model, or case set changes."
        ),
        "runs": observed["runs"] if observed else 1,
        "spread": observed,
        "recorded_at": datetime.now(UTC).isoformat(),
        "provider": provider_name,
        "observed": summary["overall"],
        "overall": floors(summary["overall"]),
        "by_complexity": {stratum: floors(metrics) for stratum, metrics in summary["by_complexity"].items()},
    }
    THRESHOLDS_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nWrote {THRESHOLDS_PATH}")


async def main_async(args: argparse.Namespace) -> int:
    from backend import config
    from backend.database import init_db

    # Scratch by default. Passing --data-dir is how you opt in to somewhere
    # else; there is deliberately no way to land on the real one by accident.
    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.gettempdir()) / "meetingos-eval"
    data_dir.mkdir(parents=True, exist_ok=True)
    config.set_data_dir(data_dir)
    init_db()
    logger.info("Eval database: %s", data_dir)

    provider = None
    provider_name = "configured"
    if args.stub:
        from backend.eval.stub_provider import StubEmbedder, StubProvider

        provider = StubProvider()
        embedder = StubEmbedder()
        provider_name = "stub"
    else:
        from backend.ai import get_embedding_provider, get_llm_provider

        provider = get_llm_provider()
        provider_name = f"{provider.config.name}:{provider.config.model}"
        if not provider.is_configured():
            print(
                f"\nProvider {provider_name} has no credentials. Configure it, or run with "
                "--stub to exercise the harness against a deterministic fake.",
                file=sys.stderr,
            )
            return 2
        embedder = get_embedding_provider()

    if args.embedder == "stub" and not args.stub:
        # A real LLM paired with the local embedder. This is the only way to
        # score a provider that generates but does not embed (OpenRouter), and
        # it splits the result cleanly: extraction and answering are real, the
        # similarity matching behind them is not. Printed so no reader has to
        # infer it from the flags.
        from backend.eval.stub_provider import StubEmbedder

        embedder = StubEmbedder()
        provider_name = f"{provider_name} (embeddings: stub)"

    cases = load_cases(args.case)
    print(f"Running {len(cases)} case(s) against {provider_name}")

    repeats = max(1, args.repeat)
    every_run: list[dict] = []
    for attempt in range(repeats):
        if repeats > 1:
            print(f"\n--- run {attempt + 1} of {repeats} ---")
        results = []
        for case in cases:
            if args.verbose:
                print(f"\n  {case['name']}: {case.get('notes', '')}")
            results.append(await run_case(case, provider=provider, embedder=embedder, verbose=args.verbose))

        summary = aggregate(results)
        summary["provider"] = provider_name
        report(summary, results)
        every_run.append(summary)

    if repeats > 1:
        summary = every_run[-1]
        summary["spread"] = _spread(every_run)
        summary["runs"] = every_run
        report_spread(summary["spread"])

    if args.comparator:
        print("\ncomparator suite")
        comparator_summary = await run_comparator_suite(
            provider=None if not args.stub else provider, verbose=args.verbose
        )
        summary["comparator"] = comparator_summary
        if comparator_summary.get("cases"):
            print(
                f"  accuracy {comparator_summary['accuracy']:.2f}  "
                f"false positives {comparator_summary['false_positive_rate']:.2f} "
                f"{comparator_summary['false_positives'] or ''}  "
                f"missed {comparator_summary['missed_conflict_rate']:.2f} "
                f"{comparator_summary['missed'] or ''}"
            )

    if args.crosslingual:
        print("\ncross-language retrieval")
        if args.stub or args.embedder == "stub":
            print(
                "  SKIPPED — cross-language retrieval is a property of the embedding\n"
                "  model. Scoring it against a bag-of-words stub measures the stub.\n"
                "  Run with a real embeddings provider to get a number here."
            )
            summary["crosslingual"] = {"cases": 0, "skipped": "no real embedding provider"}
            xl = {}
        else:
            xl = await run_crosslingual_suite(embedder=None, verbose=args.verbose)
            summary["crosslingual"] = xl
        if xl.get("cases"):
            print(f"  accuracy {xl['accuracy']:.2f} over {xl['cases']} case(s)")
            for pair, score in sorted(xl["by_language_pair"].items()):
                print(f"    {pair:<14} {score:.2f}")
            if xl["missed"]:
                print(f"  missed: {xl['missed']}")

    for flag, label, directory in (
        (args.copilot, "copilot", COPILOT_DIR),
        (args.fusion, "fusion", FUSION_DIR),
    ):
        if not flag:
            continue
        print(f"\n{label} suite (cross-corpus answers)")
        corpus_summary = await run_corpus_suite(
            directory,
            provider=provider,
            embedder=embedder if args.stub or args.embedder == "stub" else None,
            verbose=args.verbose,
        )
        summary[label] = corpus_summary
        _report_corpus(label, corpus_summary)

    if args.json:
        # Written last. This used to run before the comparator, copilot, fusion
        # and cross-language suites, so the saved summary was missing every one
        # of them and only the terminal output ever had the full picture.
        Path(args.json).write_text(json.dumps(summary, indent=2) + "\n")
        print(f"\nWrote {args.json}")

    if args.baseline:
        if args.stub:
            # stub_provider.py says this in its own docstring; enforce it here
            # rather than trusting the reader. A stub-derived thresholds.json is
            # a CI gate calibrated against a keyword matcher, and it would pass
            # forever while saying nothing about the model.
            print(
                "\nRefusing to write a baseline from the stub provider. It is a "
                "keyword matcher, not a model; thresholds taken from it would gate "
                "CI on nothing. Run --baseline against a real provider.",
                file=sys.stderr,
            )
            return 2
        if repeats < 3:
            print(
                "\nRefusing to write a baseline from "
                f"{repeats} run(s). This suite returned recall 0.38 and 0.92 on "
                "consecutive runs of the same model over the same cases, so a "
                "threshold taken from one sample is noise with a decimal point. "
                "Re-run with --repeat 3 or more.",
                file=sys.stderr,
            )
            return 2
        write_baseline(summary, provider_name)
        return 0

    if args.ci:
        passed, failures = check_thresholds(summary)
        print("\n" + "=" * 74)
        if passed:
            print("PASS — all thresholds met")
            return 0
        print("FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci", action="store_true", help="exit non-zero if below threshold")
    parser.add_argument("--baseline", action="store_true", help="write thresholds.json from this run")
    parser.add_argument("--stub", action="store_true", help="use the deterministic fake provider")
    parser.add_argument("--case", help="substring filter on case name")
    parser.add_argument("--json", help="write the summary to this path")
    parser.add_argument(
        "--data-dir",
        help=(
            "Database directory. Defaults to a scratch directory, never the "
            "configured data dir: eval creates and destroys synthetic meetings "
            "and must not touch real ones."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Run the extraction suite N times and report the spread. A single "
            "run of a non-deterministic model is a sample, not a measurement; "
            "use at least 3 before writing a baseline."
        ),
    )
    parser.add_argument("--comparator", action="store_true", help="also score the claim comparator suite")
    parser.add_argument("--copilot", action="store_true", help="also score cross-meeting copilot answers")
    parser.add_argument("--fusion", action="store_true", help="also score document+meeting fusion answers")
    parser.add_argument(
        "--all",
        action="store_true",
        help="run every suite: extraction, comparator, copilot, fusion, cross-language",
    )
    parser.add_argument(
        "--embedder",
        choices=("auto", "stub"),
        default="auto",
        help=(
            "Matching and retrieval embeddings. 'stub' pairs a real LLM with the "
            "deterministic local embedder, which is how a provider with no "
            "embeddings endpoint (OpenRouter) is scored. Reported in the output."
        ),
    )
    parser.add_argument(
        "--crosslingual",
        action="store_true",
        help="also measure cross-language retrieval (RU/KZ query -> EN source, and back)",
    )
    args = parser.parse_args()
    if args.all:
        args.comparator = args.copilot = args.fusion = args.crosslingual = True

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
