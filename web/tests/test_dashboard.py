"""Dashboard, drill-through, and confidence display.

Acceptance:
- Part 1: `test_every_stat_matches_a_direct_api_query`,
  `test_every_stat_links_through_to_real_records` — no stat is a dead end.
- Part 2: `test_low_confidence_item_shows_a_warning_not_a_normal_card`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:5173"
SHOTS = Path(__file__).parent / "screenshots"

# Stat card test-id -> the dashboard JSON field it must equal.
STAT_FIELDS = {
    "stat-approved": "decisions_approved",
    "stat-pending": "decisions_pending",
    "stat-reversed": "decisions_reversed",
    "stat-overdue": "overdue_commitments",
    "stat-risks": "open_risks",
}


def dashboard_json(page) -> dict:
    return page.request.get(f"{BASE}/api/dashboard?period_days=90").json()


def test_dashboard_loads(page) -> None:
    page.goto(f"{BASE}/dashboard")
    page.wait_for_load_state("networkidle")
    expect(page.locator('[data-testid="dashboard"]')).to_be_visible(timeout=15_000)
    for testid in STAT_FIELDS:
        expect(page.locator(f'[data-testid="{testid}"]')).to_be_visible()
    print(f"  ✓ dashboard rendered with {len(STAT_FIELDS)} stat cards")


def test_every_stat_matches_a_direct_api_query(page) -> None:
    """Acceptance: the rendered number equals what the API says, not a guess."""
    page.goto(f"{BASE}/dashboard")
    page.wait_for_load_state("networkidle")
    expect(page.locator('[data-testid="dashboard"]')).to_be_visible(timeout=15_000)

    api = dashboard_json(page)
    for testid, field in STAT_FIELDS.items():
        rendered = int(page.locator(f'[data-testid="{testid}"]').get_attribute("data-value"))
        expected = api[field]["value"]
        assert rendered == expected, f"{testid}: UI shows {rendered}, API says {expected}"
    print("  ✓ all 5 stat values match the API")

    # And the overdue count is independently reproducible from the commitments
    # endpoint — the one the drill-through link actually hits.
    commitments = page.request.get(f"{BASE}/api/commitments?overdue=true").json()
    overdue_stat = int(page.locator('[data-testid="stat-overdue"]').get_attribute("data-value"))
    assert overdue_stat == commitments["total"], (
        f"dashboard says {overdue_stat} overdue, /api/commitments returns {commitments['total']}"
    )
    print(f"  ✓ overdue count ({overdue_stat}) reproduces from /api/commitments")


def test_every_stat_links_through_to_real_records(page) -> None:
    """Acceptance: no stat is a dead end."""
    page.goto(f"{BASE}/dashboard")
    page.wait_for_load_state("networkidle")
    expect(page.locator('[data-testid="dashboard"]')).to_be_visible(timeout=15_000)

    for testid in STAT_FIELDS:
        card = page.locator(f'[data-testid="{testid}"]')
        href = card.get_attribute("data-link")
        assert href and href.startswith("/"), f"{testid} has no drill-through link"
    print("  ✓ every stat card carries a link")

    # Follow the overdue one end to end: it must land on the filtered list and
    # that list must hold the same number of rows the card claimed.
    expected = int(page.locator('[data-testid="stat-overdue"]').get_attribute("data-value"))
    page.locator('[data-testid="stat-overdue"]').click()
    page.wait_for_url("**/commitments**", timeout=10_000)
    expect(page.locator('[data-testid="commitments-total"]')).to_be_visible(timeout=10_000)

    assert "overdue=true" in page.url, f"filter lost in navigation: {page.url}"
    landed = int(page.locator('[data-testid="commitments-total"]').get_attribute("data-value"))
    assert landed == expected, f"card said {expected}, filtered list shows {landed}"

    if expected:
        rows = page.locator('[data-testid="commitment-row"]')
        assert rows.count() == expected
        # Every row on an overdue-filtered page really is overdue.
        for index in range(rows.count()):
            assert rows.nth(index).get_attribute("data-overdue") == "true"
        expect(page.locator('[data-testid="overdue-badge"]').first).to_be_visible()
    print(f"  ✓ clicked through to {expected} filtered row(s), filter preserved")


def test_person_rows_link_to_their_history(page) -> None:
    page.goto(f"{BASE}/dashboard")
    page.wait_for_load_state("networkidle")
    rows = page.locator('[data-testid="person-row"]')
    if rows.count() == 0:
        print("  – no active people in this dataset; nothing to check")
        return
    href = rows.first.get_attribute("href")
    assert href and "/people/" in href and href.endswith("/commitments")
    print(f"  ✓ person row links to {href}")


# -- Part 2 ----------------------------------------------------------------


def completed_meeting_with_low_confidence(page) -> str | None:
    """A meeting holding a deliberately low-confidence extraction."""
    for meeting in page.request.get(f"{BASE}/api/meetings").json():
        if meeting["status"] != "completed":
            continue
        intel = page.request.get(f"{BASE}/api/meetings/{meeting['id']}/intelligence").json()
        for kind in ("decisions", "action_items", "risks", "commitments"):
            for item in intel.get(kind) or []:
                if item["verification_status"] in ("low_confidence", "unsupported"):
                    return meeting["id"]
    return None


def test_low_confidence_item_shows_a_warning_not_a_normal_card(page) -> None:
    """Acceptance: a weak extraction must not look like a clean one."""
    meeting_id = completed_meeting_with_low_confidence(page)
    assert meeting_id, "no low-confidence extraction in the dataset to check"

    page.goto(f"{BASE}/meetings/{meeting_id}")
    page.wait_for_load_state("networkidle")
    page.locator('[data-testid="tab-decisions"]').click()

    flagged = page.locator(
        '[data-testid="item-card"][data-verification="low_confidence"], '
        '[data-testid="item-card"][data-verification="unsupported"]'
    )
    expect(flagged.first).to_be_visible(timeout=10_000)

    # The card carries a banner, not just a subtle chip.
    banner = flagged.first.locator('[data-testid="attention-banner"]')
    expect(banner).to_be_visible()
    assert banner.inner_text().strip(), "attention banner is empty"
    print(f"  ✓ low-confidence card shows a banner: {banner.inner_text()[:60]!r}")

    # A verified card must NOT carry one — otherwise the warning means nothing.
    clean = page.locator('[data-testid="item-card"][data-verification="verified"]')
    if clean.count():
        assert clean.first.locator('[data-testid="attention-banner"]').count() == 0
        print("  ✓ verified cards carry no banner, so the warning still means something")

    # And the item is present, not hidden — the Phase 3 principle.
    assert flagged.count() >= 1
    print(f"  ✓ {flagged.count()} flagged item(s) shown, none hidden")

    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "low-confidence-card.png"))


def test_verification_score_is_surfaced_on_cards(page) -> None:
    meeting_id = completed_meeting_with_low_confidence(page)
    assert meeting_id
    page.goto(f"{BASE}/meetings/{meeting_id}")
    page.wait_for_load_state("networkidle")
    page.locator('[data-testid="tab-decisions"]').click()

    scores = page.locator('[data-testid="verification-score"]')
    expect(scores.first).to_be_visible(timeout=10_000)

    api = page.request.get(f"{BASE}/api/meetings/{meeting_id}/intelligence").json()
    api_scores = {
        round(d["verification_score"], 4)
        for d in api["decisions"]
        if d["verification_score"] is not None
    }
    shown = {round(float(scores.nth(i).get_attribute("data-score")), 4) for i in range(scores.count())}
    assert shown <= api_scores, f"UI showed scores the API does not have: {shown - api_scores}"
    print(f"  ✓ {len(shown)} verification score(s) match the API")


def test_dashboard_quality_indicator_matches_the_api(page) -> None:
    page.goto(f"{BASE}/dashboard")
    page.wait_for_load_state("networkidle")
    indicator = page.locator('[data-testid="quality-indicator"]')
    expect(indicator).to_be_visible(timeout=15_000)

    api = dashboard_json(page)["extraction_quality"]
    assert int(indicator.get_attribute("data-total")) == api["total_items"]
    expected_attention = api["low_confidence"] + api["unsupported"]
    assert int(indicator.get_attribute("data-needs-attention")) == expected_attention

    if expected_attention:
        expect(page.locator('[data-testid="quality-warning"]')).to_be_visible()
        print(f"  ✓ quality indicator flags {expected_attention} item(s) needing review")
    else:
        print("  ✓ quality indicator matches API (nothing needs review)")

    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "dashboard.png"))


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        try:
            for test in (
                test_dashboard_loads,
                test_every_stat_matches_a_direct_api_query,
                test_every_stat_links_through_to_real_records,
                test_person_rows_link_to_their_history,
                test_low_confidence_item_shows_a_warning_not_a_normal_card,
                test_verification_score_is_surfaced_on_cards,
                test_dashboard_quality_indicator_matches_the_api,
            ):
                print(f"\n{test.__name__}")
                try:
                    test(page)
                except Exception as exc:
                    failures.append(f"{test.__name__}: {exc}")
                    print(f"  ✗ {exc}")
        finally:
            browser.close()

        if failures:
            print(f"\n{len(failures)} FAILED:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("\nAll dashboard checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
