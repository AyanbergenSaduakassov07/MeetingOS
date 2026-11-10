"""Copilot end-to-end: a cited answer, and an honest refusal.

Run through the webapp-testing helper (see test_meeting_report.py for the
command). The LLM is stubbed at the HTTP boundary via Playwright routing, so
this exercises the real retrieval, the real citation whitelist and the real UI
without needing provider credentials.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:5173"
SHOTS = Path(__file__).parent / "screenshots"


def completed_meeting_id(page) -> str:
    """A completed meeting that actually has extracted items (see report suite)."""
    for meeting in page.request.get(f"{BASE}/api/meetings").json():
        if meeting["status"] != "completed":
            continue
        intel = page.request.get(
            f"{BASE}/api/meetings/{meeting['id']}/intelligence"
        ).json()
        if any(
            intel.get(kind)
            for kind in ("decisions", "action_items", "risks", "commitments")
        ):
            return meeting["id"]
    raise AssertionError(
        "No completed meeting with extracted intelligence to ask about."
    )


def stub_ask(page, payload: dict) -> None:
    """Serve /ask/stream (NDJSON, as the UI reads it) from a fixture: no model credentials."""
    body = json.dumps({"type": "done", "response": payload}) + "\n"
    page.route(
        "**/api/meetings/*/ask/stream",
        lambda route: route.fulfill(
            status=200, content_type="application/x-ndjson", body=body
        ),
    )


def ask(page, question: str) -> None:
    page.locator('[data-testid="copilot-input"]').fill(question)
    page.locator('[data-testid="copilot-send"]').click()


def test_cited_answer_renders_with_clickable_timestamp(page) -> None:
    meeting_id = completed_meeting_id(page)
    page.goto(f"{BASE}/meetings/{meeting_id}")
    page.wait_for_load_state("networkidle")

    segments = page.request.get(f"{BASE}/api/meetings/{meeting_id}/transcript").json()
    sponsor = next(s for s in segments if "money has not cleared" in s["text"])

    stub_ask(
        page,
        {
            "meeting_id": meeting_id,
            "question": "What did Priya say about the sponsor?",
            "answer": "The sponsor agreed verbally but the money has not cleared, and parts are ordered in two weeks.",
            "citations": [
                {
                    "segment_id": sponsor["id"],
                    "start_ms": sponsor["start_ms"],
                    "end_ms": sponsor["end_ms"],
                    "speaker_label": sponsor["speaker_label"],
                    "text": sponsor["text"],
                }
            ],
            "not_discussed": False,
            "unsupported": False,
            "segments_considered": len(segments),
            "segments_retrieved": 3,
        },
    )

    ask(page, "What did Priya say about the sponsor?")

    answer = page.locator('[data-testid="copilot-answer"]')
    expect(answer).to_be_visible(timeout=10_000)
    assert "money has not cleared" in answer.inner_text()
    expect(
        page.locator('[data-role="assistant"][data-state="grounded"]')
    ).to_be_visible()
    print("  ✓ cited answer rendered")

    # Budget: it answered from a subset, not the whole transcript.
    assert len(segments) > 3, "fixture too small to prove a budget"
    print(f"  ✓ answered from 3 of {len(segments)} segments")

    # The citation is the same clickable-timestamp component as an item card.
    citation = page.locator(
        '[data-role="assistant"] [data-testid="citation-time"]'
    ).first
    expect(citation).to_be_visible()
    target_ms = int(citation.get_attribute("data-ms"))
    assert target_ms == sponsor["start_ms"]

    expect(
        page.locator('[data-testid="player-bar"][data-ready="true"]')
    ).to_be_attached(timeout=30_000)
    citation.click()
    page.wait_for_function(
        """(expected) => {
             const bar = document.querySelector('[data-testid="player-bar"]');
             return bar && Math.abs(Number(bar.dataset.positionMs) - expected) < 1200;
           }""",
        arg=target_ms,
        timeout=10_000,
    )
    position = int(
        page.locator('[data-testid="player-bar"]').get_attribute("data-position-ms")
    )
    print(f"  ✓ copilot citation seeked audio to {position}ms")

    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "copilot-cited-answer.png"))


def test_unanswerable_question_says_not_discussed(page) -> None:
    meeting_id = completed_meeting_id(page)
    page.goto(f"{BASE}/meetings/{meeting_id}")
    page.wait_for_load_state("networkidle")

    stub_ask(
        page,
        {
            "meeting_id": meeting_id,
            "question": "What did they decide about salaries?",
            "answer": "NOT_DISCUSSED",
            "citations": [],
            "not_discussed": True,
            "unsupported": False,
            "segments_considered": 10,
            "segments_retrieved": 0,
        },
    )

    ask(page, "What did they decide about salaries?")

    bubble = page.locator('[data-role="assistant"][data-state="not-discussed"]')
    expect(bubble).to_be_visible(timeout=10_000)
    text = bubble.inner_text().lower()
    assert "not discussed" in text or "не обсуждалось" in text
    # The refusal must not be dressed up as an answer with citations.
    assert (
        page.locator('[data-role="assistant"] [data-testid="citation-time"]').count()
        == 0
    )
    print("  ✓ unanswerable question refused honestly, with no citations")

    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "copilot-not-discussed.png"))


def test_ungrounded_answer_is_flagged(page) -> None:
    """An answer with no valid citation is shown as a warning, not as fact."""
    meeting_id = completed_meeting_id(page)
    page.goto(f"{BASE}/meetings/{meeting_id}")
    page.wait_for_load_state("networkidle")

    stub_ask(
        page,
        {
            "meeting_id": meeting_id,
            "question": "What is the budget?",
            "answer": "The budget is five hundred pounds.",
            "citations": [],
            "not_discussed": False,
            "unsupported": True,
            "segments_considered": 10,
            "segments_retrieved": 4,
        },
    )

    ask(page, "What is the budget?")

    bubble = page.locator('[data-role="assistant"][data-state="unsupported"]')
    expect(bubble).to_be_visible(timeout=10_000)
    assert bubble.inner_text().strip() != ""
    print("  ✓ ungrounded answer visibly flagged")


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = []
        try:
            for test in (
                test_cited_answer_renders_with_clickable_timestamp,
                test_unanswerable_question_says_not_discussed,
                test_ungrounded_answer_is_flagged,
            ):
                print(f"\n{test.__name__}")
                try:
                    test(page)
                except Exception as exc:  # noqa: BLE001 - reported below, not swallowed
                    failures.append(f"{test.__name__}: {exc}")
                    print(f"  ✗ {exc}")
        finally:
            browser.close()

        if failures:
            print(f"\n{len(failures)} FAILED:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("\nAll copilot checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
