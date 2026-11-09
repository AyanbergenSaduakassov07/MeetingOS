"""Privacy and data-governance control centre in the browser.

Part 4 acceptance, second half: *the privacy page accurately reflects current
config.* The first half — a planted sensitive value never reaching a mocked
provider call — is proven in `backend/tests/test_privacy_center.py`.

Every assertion here compares the rendered page against `GET /api/privacy`
rather than against a fixture, so the test fails if the page ever drifts from
what the install is really configured to do. A privacy page that looks right
but reports stale settings is worse than no page at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:5173"
SHOTS = Path(__file__).parent / "screenshots"


def privacy_json(page) -> dict:
    return page.request.get(f"{BASE}/api/privacy").json()


def open_page(page) -> None:
    page.goto(f"{BASE}/settings/privacy")
    page.wait_for_load_state("networkidle")
    expect(page.locator('[data-testid="privacy-settings"]')).to_be_visible(
        timeout=15_000
    )


def test_page_loads_and_lists_every_provider(page) -> None:
    open_page(page)
    api = privacy_json(page)

    rows = page.locator('[data-testid="provider-row"]')
    assert rows.count() == len(api["providers"]), (
        f"page shows {rows.count()} providers, API reports {len(api['providers'])}"
    )

    # Cloud vs local is the one distinction an operator reads first; it must
    # come from the API, not from a hardcoded label.
    rendered = [
        rows.nth(i).get_attribute("data-cloud") == "true" for i in range(rows.count())
    ]
    assert rendered == [p["is_cloud"] for p in api["providers"]]
    print(f"  ✓ {rows.count()} provider(s) listed, cloud/local flags match the API")


def test_rule_list_matches_the_active_config(page) -> None:
    """Acceptance: the page reflects current config, rule by rule."""
    open_page(page)
    api = privacy_json(page)["redaction"]

    toggles = page.locator('[data-testid="rule-toggle"]')
    assert toggles.count() == len(api["rules"]), (
        f"page shows {toggles.count()} rules, config has {len(api['rules'])}"
    )

    shown = {
        toggles.nth(i).get_attribute("data-rule"): toggles.nth(i).get_attribute(
            "data-enabled"
        )
        == "true"
        for i in range(toggles.count())
    }
    expected = {rule["name"]: rule["enabled"] for rule in api["rules"]}
    assert shown == expected, (
        f"rule states drifted: {set(shown.items()) ^ set(expected.items())}"
    )

    master = page.locator('[data-testid="redaction-toggle"]')
    assert (master.get_attribute("data-enabled") == "true") == api["enabled"]
    print(f"  ✓ {len(shown)} rule(s) and the master switch match the active config")


def test_rules_do_not_look_live_when_redaction_is_off(page) -> None:
    """Selection is not effect.

    Fourteen green ticks under a switch reading "Redaction off" is the exact
    misreading this page exists to prevent, so a rule is only styled as running
    when the master switch is on too.
    """
    open_page(page)
    api = privacy_json(page)["redaction"]
    toggles = page.locator('[data-testid="rule-toggle"]')

    running = [
        toggles.nth(i).get_attribute("data-running") == "true"
        for i in range(toggles.count())
    ]
    if api["enabled"]:
        assert running == [r["enabled"] for r in api["rules"]]
        assert page.locator('[data-testid="rules-inert-notice"]').count() == 0
        print(f"  ✓ redaction on: {sum(running)} rule(s) shown as running")
    else:
        assert not any(running), "rules render as running while redaction is off"
        notice = page.locator('[data-testid="rules-inert-notice"]')
        expect(notice).to_be_visible()
        assert notice.inner_text().strip()
        print(
            f"  ✓ redaction off: no rule looks live, notice shown — {notice.inner_text()[:60]!r}"
        )


def test_limitations_are_stated_not_buried(page) -> None:
    """An operator who cannot read the limits will over-trust the control."""
    open_page(page)
    api = privacy_json(page)["redaction"]

    panel = page.locator('[data-testid="redaction-limitations"]')
    expect(panel).to_be_visible()
    text = panel.inner_text()
    assert api["limitations"], "the API reports no limitations, which cannot be true"
    for line in api["limitations"]:
        assert line in text, f"limitation not shown on the page: {line!r}"
    print(f"  ✓ all {len(api['limitations'])} limitation(s) rendered in view")


def test_toggling_a_rule_changes_the_real_config_and_the_page_follows(page) -> None:
    """The page is a control, not a picture of one — and it restores itself."""
    open_page(page)
    before = privacy_json(page)["redaction"]
    target = next((r["name"] for r in before["rules"] if r["enabled"]), None)
    assert target, "no enabled rule to toggle"

    toggle = page.locator(f'[data-testid="rule-toggle"][data-rule="{target}"]')
    try:
        toggle.click()
        expect(toggle).to_have_attribute("data-enabled", "false", timeout=10_000)

        after = privacy_json(page)["redaction"]
        assert not next(r for r in after["rules"] if r["name"] == target)["enabled"], (
            f"{target} still enabled server-side after the UI said it was off"
        )
        print(f"  ✓ turning {target!r} off reached the server and the page followed")
    finally:
        # Leave the install exactly as it was found.
        page.request.put(
            f"{BASE}/api/privacy/redaction",
            data={
                "enabled": before["enabled"],
                "rules": [r["name"] for r in before["rules"] if r["enabled"]],
            },
        )
    restored = privacy_json(page)["redaction"]
    assert {r["name"] for r in restored["rules"] if r["enabled"]} == {
        r["name"] for r in before["rules"] if r["enabled"]
    }
    print("  ✓ original configuration restored")


def test_audit_summary_matches_the_api(page) -> None:
    open_page(page)
    api = privacy_json(page)

    summary = page.locator('[data-testid="audit-summary"] dd')
    values = [int(summary.nth(i).inner_text()) for i in range(summary.count())]
    assert values == [
        api["audit_summary"]["total_calls"],
        api["audit_summary"]["cloud_calls"],
        api["audit_summary"]["failed_calls"],
        api["audit_summary"]["calls_without_redaction"],
    ], f"audit tiles show {values}"

    rows = page.locator('[data-testid="audit-row"]')
    assert rows.count() == len(api["recent_calls"])
    print(f"  ✓ audit summary matches; {rows.count()} recent call(s) tabulated")

    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "privacy-settings.png"), full_page=True)


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        try:
            for test in (
                test_page_loads_and_lists_every_provider,
                test_rule_list_matches_the_active_config,
                test_rules_do_not_look_live_when_redaction_is_off,
                test_limitations_are_stated_not_buried,
                test_toggling_a_rule_changes_the_real_config_and_the_page_follows,
                test_audit_summary_matches_the_api,
            ):
                print(f"\n{test.__name__}")
                try:
                    test(page)
                except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                    failures.append(f"{test.__name__}: {exc}")
                    print(f"  ✗ {exc}")
        finally:
            browser.close()

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("all privacy page checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
