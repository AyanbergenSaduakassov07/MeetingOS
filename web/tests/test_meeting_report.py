"""End-to-end coverage for the meeting report page.

Run through the webapp-testing helper, which owns both server lifecycles:

    python3 ~/.claude/skills/webapp-testing/scripts/with_server.py \
      --server ".venv/bin/uvicorn backend.main:app --port 8470" --port 8470 \
      --server "cd web && bun run dev --port 5173" --port 5173 \
      -- backend/venv/bin/python web/tests/test_meeting_report.py

Two flows are covered, deliberately against different meetings:

- **Upload → processing.** A freshly uploaded recording proves the 202 path and
  the processing state card. It cannot then reach `completed` here, because
  transcription needs an API key this machine does not have.
- **Completed report.** The seeded meeting is the one with extracted items, so
  the report, citation-seek and EN/RU assertions run against it.
"""

from __future__ import annotations

import struct
import sys
import wave
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:5173"
SHOTS = Path(__file__).parent / "screenshots"
FIXTURE = Path(__file__).parent / "fixtures" / "upload-sample.wav"


def make_fixture_wav() -> Path:
    """A 2-second tone. Small enough to upload fast, real enough to be accepted."""
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    if FIXTURE.exists():
        return FIXTURE
    rate = 16000
    with wave.open(str(FIXTURE), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * ((i // 40) % 2 * 2 - 1)))
                for i in range(rate * 2)
            )
        )
    return FIXTURE


def completed_meeting_id(page) -> str:
    """A completed meeting that actually has extracted items.

    Status alone is not enough: any process that creates and abandons a
    completed-but-empty meeting (a stray eval run, say) would otherwise be
    picked first and every assertion below would fail for the wrong reason.
    """
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
        "No completed meeting with extracted intelligence to report on."
    )


def test_upload_returns_processing(page) -> None:
    """Upload accepts the file and creates a meeting in `processing`.

    Asserted against the API response rather than the rendered card, because on
    a machine with no transcription key the meeting flips to `failed` within
    milliseconds — faster than the browser can paint. The processing card gets
    its own deterministic test below.
    """
    page.goto(f"{BASE}/meetings")
    page.wait_for_load_state("networkidle")

    page.locator('[data-testid="upload-input"]').set_input_files(
        str(make_fixture_wav())
    )
    dialog = page.locator('[data-testid="consent-dialog"]')
    confirm = dialog.locator('[data-testid="consent-confirm"]')
    expect(confirm).to_be_disabled()  # no upload until consent is given
    dialog.locator("#consent-agree").check()

    with page.expect_response(
        lambda response: (
            "/api/meetings/upload" in response.url and response.request.method == "POST"
        )
    ) as captured:
        confirm.click()

    response = captured.value
    assert response.status == 202, f"expected 202 Accepted, got {response.status}"
    body = response.json()
    assert body["status"] == "processing", (
        f"expected 'processing', got {body['status']!r}"
    )

    page.wait_for_url("**/meetings/**", timeout=15_000)
    print(f"  ✓ upload → 202 {body['status']!r}, redirected to the meeting")

    # Whatever it settles into, the reader must be told — never a blank page.
    settled = page.locator(
        '[data-testid="state-processing"], [data-testid="state-failed"]'
    )
    expect(settled.first).to_be_visible(timeout=15_000)
    which = settled.first.get_attribute("data-testid")
    print(f"  ✓ settled state rendered: {which}")


def test_processing_state_card(page) -> None:
    """The processing card renders while a meeting is still being processed.

    The status is pinned by intercepting the meeting request, so the assertion
    does not depend on real transcription latency.
    """
    meeting_id = completed_meeting_id(page)

    def pin_processing(route):
        response = route.fetch()
        body = response.json()
        body["status"] = "processing"
        route.fulfill(response=response, json=body)

    page.route(f"**/api/meetings/{meeting_id}", pin_processing)
    try:
        page.goto(f"{BASE}/meetings/{meeting_id}")
        expect(page.locator('[data-testid="state-processing"]')).to_be_visible(
            timeout=15_000
        )
        print("  ✓ processing state card renders")
    finally:
        page.unroute(f"**/api/meetings/{meeting_id}")


def test_completed_report_and_citation_seek(page) -> None:
    meeting_id = completed_meeting_id(page)
    page.goto(f"{BASE}/meetings/{meeting_id}")
    page.wait_for_load_state("networkidle")

    expect(page.locator('[data-testid="meeting-detail"]')).to_be_visible()
    expect(page.locator('[data-testid="meeting-title"]')).not_to_be_empty()
    print("  ✓ completed report renders")

    # Decisions tab: cards carry a chip, a confidence badge and a citation.
    page.locator('[data-testid="tab-decisions"]').click()
    cards = page.locator('[data-testid="item-card"]')
    expect(cards.first).to_be_visible()
    assert cards.count() >= 1, "expected at least one decision card"
    expect(cards.first.locator('[data-testid="confidence-badge"]')).to_be_visible()
    print(f"  ✓ {cards.count()} decision card(s) with chip + confidence badge")

    # The waveform must have decoded before a seek can land.
    expect(
        page.locator('[data-testid="player-bar"][data-ready="true"]')
    ).to_be_attached(timeout=30_000)

    citation = cards.first.locator('[data-testid="citation-time"]').first
    target_ms = int(citation.get_attribute("data-ms"))
    assert target_ms > 0, "fixture needs a citation at a non-zero timestamp"

    citation.click()

    # Assert on the store-backed position the player publishes, so this checks
    # wavesurfer actually moved rather than that a label was rewritten.
    page.wait_for_function(
        """(expected) => {
             const bar = document.querySelector('[data-testid="player-bar"]');
             if (!bar) return false;
             return Math.abs(Number(bar.dataset.positionMs) - expected) < 1200;
           }""",
        arg=target_ms,
        timeout=10_000,
    )
    position = int(
        page.locator('[data-testid="player-bar"]').get_attribute("data-position-ms")
    )
    print(f"  ✓ citation click seeked audio to {position}ms (asked for {target_ms}ms)")


def test_language_toggle_switches_chrome_only(page) -> None:
    meeting_id = completed_meeting_id(page)
    page.goto(f"{BASE}/meetings/{meeting_id}")
    page.wait_for_load_state("networkidle")
    page.locator('[data-testid="tab-decisions"]').click()

    tab = page.locator('[data-testid="tab-decisions"]')
    title = page.locator('[data-testid="item-title"]').first
    quote = page.locator('[data-testid="item-quote"]').first

    en_tab = tab.inner_text().strip()
    en_title = title.inner_text().strip()
    en_quote = quote.inner_text().strip()

    page.get_by_role("button", name="RU", exact=True).click()
    page.wait_for_function(
        "(before) => document.querySelector('[data-testid=\"tab-decisions\"]').innerText.trim() !== before",
        arg=en_tab,
        timeout=5_000,
    )

    ru_tab = tab.inner_text().strip()
    ru_title = title.inner_text().strip()
    ru_quote = quote.inner_text().strip()

    assert ru_tab != en_tab, f"chrome did not switch: {en_tab!r} stayed {ru_tab!r}"
    assert ru_tab == "Решения", f"expected 'Решения', got {ru_tab!r}"
    assert ru_title == en_title, (
        f"decision CONTENT was translated: {en_title!r} -> {ru_title!r}"
    )
    assert ru_quote == en_quote, (
        f"transcript CONTENT was translated: {en_quote!r} -> {ru_quote!r}"
    )
    print(f"  ✓ chrome {en_tab!r} -> {ru_tab!r}; content unchanged ({en_title[:40]!r})")

    # And the choice survives a reload, via localStorage.
    page.reload()
    page.wait_for_load_state("networkidle")
    expect(page.locator('[data-testid="tab-decisions"]')).to_have_text("Решения")
    print("  ✓ language persisted across reload")

    page.get_by_role("button", name="EN", exact=True).click()


def capture_screenshots(page) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    meeting_id = completed_meeting_id(page)

    for theme in ("light", "dark"):
        for language in ("en", "ru"):
            page.goto(f"{BASE}/meetings/{meeting_id}")
            page.wait_for_load_state("networkidle")
            page.evaluate(
                "(t) => document.documentElement.classList.toggle('dark', t === 'dark')",
                theme,
            )
            page.get_by_role("button", name=language.upper(), exact=True).click()
            page.locator('[data-testid="tab-decisions"]').click()
            expect(
                page.locator('[data-testid="player-bar"][data-ready="true"]')
            ).to_be_attached(timeout=30_000)
            page.wait_for_timeout(400)  # let the waveform finish painting
            path = SHOTS / f"meeting-{theme}-{language}.png"
            page.screenshot(path=str(path))
            print(f"  ✓ {path.name}")


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = []
        try:
            for test in (
                test_upload_returns_processing,
                test_processing_state_card,
                test_completed_report_and_citation_seek,
                test_language_toggle_switches_chrome_only,
            ):
                print(f"\n{test.__name__}")
                try:
                    test(page)
                except Exception as exc:  # noqa: BLE001 - keep going so one failure reports the rest
                    failures.append(f"{test.__name__}: {exc}")
                    print(f"  ✗ {exc}")
            print("\ncapture_screenshots")
            capture_screenshots(page)
        finally:
            browser.close()

        if failures:
            print(f"\n{len(failures)} FAILED:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("\nAll checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
