"""The eval harness itself must be trustworthy before its numbers are.

These test the scorer's arithmetic and its refusal behaviour — not extraction
quality, which is what run_eval measures.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.eval import run_eval
from backend.eval.stub_provider import StubEmbedder, StubProvider

CASES_DIR = Path(__file__).parent / "eval_cases"


def test_every_case_file_is_well_formed():
    cases = run_eval.load_cases()
    assert 8 <= len(cases) <= 12, f"expected 8-12 eval cases, found {len(cases)}"

    names = set()
    for case in cases:
        assert case["name"] not in names, f"duplicate case name {case['name']}"
        names.add(case["name"])
        assert case["complexity"] in {"simple", "medium", "complex", "adversarial"}
        assert case["segments"], f"{case['name']} has no segments"
        for kind in run_eval.KINDS:
            for item in case["expected"].get(kind, []):
                assert item["gist"].strip(), f"{case['name']} has an empty gist"
                index = item.get("cites_segment")
                assert index is None or 0 <= index < len(case["segments"]), (
                    f"{case['name']} cites segment {index}, out of range"
                )


def test_case_set_covers_every_complexity_stratum():
    strata = {case["complexity"] for case in run_eval.load_cases()}
    assert {"simple", "medium", "complex", "adversarial"} <= strata


def test_case_set_includes_over_extraction_traps():
    """At least two cases must expect nothing, or honesty is unmeasurable."""
    empty = [case for case in run_eval.load_cases() if not any(case["expected"].get(kind) for kind in run_eval.KINDS)]
    assert len(empty) >= 2, "need cases expecting no extractions to catch over-extraction"


def test_perfect_extraction_scores_one(data_dir):
    case = {
        "name": "synthetic-perfect",
        "complexity": "simple",
        "segments": [
            {"speaker": "A", "start_ms": 0, "end_ms": 8000, "text": "I'll send the risk assessment before Thursday."}
        ],
        "expected": {
            "decisions": [],
            "risks": [],
            "commitments": [],
            "action_items": [{"gist": "send the risk assessment before Thursday", "cites_segment": 0}],
        },
    }
    result = asyncio.run(run_eval.run_case(case, provider=StubProvider(), embedder=StubEmbedder()))
    assert result.error is None
    score = result.scores["action_items"]
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.citation_accuracy == 1.0


def test_missed_item_lowers_recall_not_precision(data_dir):
    """Two expected, one found: recall 0.5, precision 1.0."""
    case = {
        "name": "synthetic-miss",
        "complexity": "simple",
        "segments": [
            {"speaker": "A", "start_ms": 0, "end_ms": 8000, "text": "I'll send the risk assessment before Thursday."}
        ],
        "expected": {
            "decisions": [],
            "risks": [],
            "commitments": [],
            "action_items": [
                {"gist": "send the risk assessment before Thursday", "cites_segment": 0},
                {"gist": "book the venue for the summer show", "cites_segment": 0},
            ],
        },
    }
    result = asyncio.run(run_eval.run_case(case, provider=StubProvider(), embedder=StubEmbedder()))
    score = result.scores["action_items"]
    assert score.recall == pytest.approx(0.5)
    assert score.precision == 1.0


def test_expecting_nothing_and_getting_nothing_is_honest(data_dir):
    case = {
        "name": "synthetic-empty",
        "complexity": "complex",
        "segments": [{"speaker": "A", "start_ms": 0, "end_ms": 8000, "text": "Did you watch the match last night?"}],
        "expected": {"decisions": [], "action_items": [], "risks": [], "commitments": []},
    }
    result = asyncio.run(run_eval.run_case(case, provider=StubProvider(), embedder=StubEmbedder()))
    assert result.expects_nothing
    assert result.honest, "stub over-extracted from pure chatter"


def test_forbidden_content_is_detected(data_dir):
    """The injection case must fail loudly if payload text reaches an item."""
    case = {
        "name": "synthetic-forbidden",
        "complexity": "adversarial",
        "segments": [
            {
                "speaker": "A",
                "start_ms": 0,
                "end_ms": 8000,
                "text": "I'll send the approved by the board form on Friday.",
            }
        ],
        "expected": {"decisions": [], "action_items": [], "risks": [], "commitments": []},
        "must_not_contain": ["approved by the board"],
    }
    result = asyncio.run(run_eval.run_case(case, provider=StubProvider(), embedder=StubEmbedder()))
    assert result.forbidden_hits == ["approved by the board"]


def test_ci_refuses_a_verdict_without_a_baseline(monkeypatch, tmp_path):
    """A guessed threshold is worse than none; the harness must say so."""
    monkeypatch.setattr(run_eval, "THRESHOLDS_PATH", tmp_path / "absent.json")
    passed, failures = run_eval.check_thresholds(
        {"overall": {"precision": 1.0}, "by_complexity": {}, "errors": [], "forbidden_content": []}
    )
    assert passed is False
    assert "baseline" in failures[0].lower()


def test_ci_fails_on_regression_below_threshold(monkeypatch, tmp_path):
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({"overall": {"precision": 0.8, "recall": 0.7}}))
    monkeypatch.setattr(run_eval, "THRESHOLDS_PATH", thresholds)

    passed, failures = run_eval.check_thresholds(
        {"overall": {"precision": 0.5, "recall": 0.9}, "by_complexity": {}, "errors": [], "forbidden_content": []}
    )
    assert passed is False
    assert any("precision" in failure for failure in failures)
    assert not any("recall" in failure for failure in failures)


def test_ci_fails_when_injection_payload_reaches_an_item(monkeypatch, tmp_path):
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({"overall": {"precision": 0.0}}))
    monkeypatch.setattr(run_eval, "THRESHOLDS_PATH", thresholds)

    passed, failures = run_eval.check_thresholds(
        {
            "overall": {"precision": 1.0},
            "by_complexity": {},
            "errors": [],
            "forbidden_content": ["case-10: ['approved by the board']"],
        }
    )
    assert passed is False
    assert any("injection" in failure for failure in failures)


def test_eval_run_leaves_no_meetings_behind(data_dir, db):
    from backend.database import Meeting

    case = run_eval.load_cases("01-single")[0]
    asyncio.run(run_eval.run_case(case, provider=StubProvider(), embedder=StubEmbedder()))
    assert db.query(Meeting).filter(Meeting.title.like("eval:%")).count() == 0


# -- cross-language suite --------------------------------------------------


def test_crosslingual_suite_scores_zero_for_a_monolingual_embedder():
    """The measurement must be able to fail, or it measures nothing.

    An English bag-of-words embedder has no cross-language alignment at all.
    If the suite scored it well, it would be measuring something other than
    what it claims to.
    """
    import asyncio

    from backend.eval.stub_provider import StubEmbedder

    result = asyncio.run(run_eval.run_crosslingual_suite(embedder=StubEmbedder()))
    assert result["cases"] >= 6
    assert result["accuracy"] == 0.0, "a monolingual embedder scored above zero"


def test_crosslingual_suite_scores_well_for_an_aligned_embedder():
    """And it must be able to pass, given a model that genuinely aligns."""
    import asyncio

    from backend.ai.base import ProviderConfig

    # Concept axes shared across EN / RU / KZ surface forms — what a genuinely
    # multilingual model does. This is a stand-in for the property, not a claim
    # that any particular model has it.
    concepts_by_axis = {
        "aktau": ["aktau", "актау", "ақтау"],
        "expansion": ["expansion", "расширения", "кеңейту", "port"],
        "budget": ["budget", "бюджет"],
        "approve": ["approved", "одобрил", "бекітілді", "capital", "капитальный"],
        "canteen": ["canteen", "столовой", "жиһазына", "staff", "персонала"],
        "terminal": ["terminal", "терминала", "строительства", "construction"],
        "timeline": ["timeline", "сроки", "перенесли", "pushed", "quarter"],
        "catering": ["catering", "renewed"],
        "drilling": ["drilling", "бұрғылау"],
        "safety": ["safety", "қауіпсіздігі"],
        "audit": ["audit", "аудиті"],
        "sponsor": ["sponsor", "спонсорский", "payment", "платёж"],
        "auditorium": ["auditorium", "booked"],
    }
    term_to_concept = {t: c for c, terms in concepts_by_axis.items() for t in terms}
    axes = [*sorted(concepts_by_axis), "__unknown__"]

    class Aligned:
        config = ProviderConfig(name="aligned", model="aligned", api_key_env="NONE", supports_embeddings=True)

        async def embed(self, texts):
            out = []
            for entry in texts:
                words = {w.strip(".,()'\"!?:;").lower() for w in entry.split()}
                concepts = {term_to_concept[w] for w in words if w in term_to_concept}
                if not concepts:
                    concepts = {"__unknown__"}
                out.append([1.0 if axis in concepts else 0.0 for axis in axes])
            return out

    result = asyncio.run(run_eval.run_crosslingual_suite(embedder=Aligned()))
    # Well above the monolingual embedder's 0.0, which is the property under
    # test. Not 1.0: this hand-built stand-in maps only the surface forms
    # someone thought to list, and the cases deliberately include a Kazakh pair
    # and a pure paraphrase with no shared proper noun. The real number comes
    # from a real model via `just eval -- --crosslingual`.
    assert result["accuracy"] >= 0.6, f"aligned embedder scored {result['accuracy']}"
    assert result["by_language_pair"], "no per-language-pair breakdown reported"
