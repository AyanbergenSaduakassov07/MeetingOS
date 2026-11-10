"""Capture real MeetingOS screens for the launch film.

Drives the running app (Vite on :5174, backend on :8470) with Playwright at 2x
device scale. Nothing here is mocked except the copilot stream transport: the
free model's daily quota was spent, so the copilot frames replay a real answer
the model gave on 2026-11-10 (question, text and the five cited segments are
verbatim from that run) through the app's real streaming UI.

Usage (from the repo root, with the app running):
    set -a; . path/to/app.env; set +a
    .venv/bin/python marketing-video/scripts/capture.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import wave
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("FILM_BASE_URL", "http://localhost:5174")
OUT = Path(__file__).resolve().parent.parent / "public" / "screenshots"
AMI_WAV = Path(os.environ.get("FILM_AMI_WAV", ""))
AMI_ID = "1ecc4c32-c10d-43f3-8ceb-bac5c026646c"
KK_ID = "282f97a6-f7ae-4ff1-908d-9cbe5e72e984"
RU_ID = "d90441bc-21ec-4ae4-b794-f758021a6eef"  # FLEURS ru_ru dev clips, CC BY 4.0
VIEWPORT = {"width": 1600, "height": 1000}

QUESTION = "What price and production cost did they agree on?"
ANSWER = (
    "Based on the transcript, they agreed on a selling price of 25 euros and a production "
    "cost of 12.50 euros (which is 50% of the selling price)."
)
# The five segments that real answer cited, in its order.
CITED = [
    (
        "d4447a7c-5d9a-454a-8745-a005c2857411",
        471970,
        476450,
        "So according to the brief, we're going to be selling this remote control for 25 euro.",
    ),
    (
        "27363d5b-45c8-453b-a6ba-b54d5dc17a3d",
        487330,
        491690,
        "And we don't want it to cost any more than 12.50 euro.",
    ),
    (
        "beaa0ace-f927-43bd-a67b-c080dd9702f4",
        491970,
        494570,
        "So 50% of the selling price.",
    ),
    (
        "30da0f2b-c5a4-4a1c-96ad-b922e08b46b0",
        504930,
        507730,
        "So cost, like production cost is.",
    ),
    ("5b6d55dd-3962-4415-a433-694a24c70e74", 509010, 509210, "12.50."),
]

STREAM_SHIM = """
(() => {
  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    if (!url.includes('/ask/stream')) return realFetch(input, init);
    const enc = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        window.__filmPush = (event) => controller.enqueue(enc.encode(JSON.stringify(event) + '\\n'));
        window.__filmClose = () => controller.close();
      },
    });
    return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
  };
})();
"""

logger = logging.getLogger("capture")


def shot(page: Page, name: str, *, full: bool = False) -> None:
    page.wait_for_timeout(400)  # let transitions settle
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    logger.info("captured %s", name)


def element(page: Page, selector: str, name: str, has_text: str | None = None) -> None:
    locator = page.locator(selector)
    if has_text:
        locator = locator.filter(has_text=has_text)
    locator.first.scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    locator.first.screenshot(path=str(OUT / f"{name}.png"))
    logger.info("captured %s", name)


def make_clip(destination: Path) -> Path:
    """22 s of the AMI meeting (CC BY 4.0) where the team sets the price."""
    with wave.open(str(AMI_WAV)) as source:
        rate = source.getframerate()
        source.setpos(int(464 * rate))
        frames = source.readframes(int(22 * rate))
        params = source.getparams()
    with wave.open(str(destination), "wb") as clip:
        clip.setparams(params)
        clip.writeframes(frames)
    return destination


def new_page(browser, key: str, lang: str) -> Page:
    context = browser.new_context(
        viewport=VIEWPORT, device_scale_factor=2, locale="en-US"
    )
    if key:  # a local dev backend may run without a key
        response = context.request.post(f"{BASE}/api/session", data={"api_key": key})
        if not response.ok:
            raise RuntimeError(f"sign-in failed: {response.status}")
    context.add_init_script(
        f"localStorage.setItem('meetingos:lang', {json.dumps(lang)})"
    )
    return context.new_page()


def capture_english(browser, key: str) -> None:
    page = new_page(browser, key, "en")
    page.goto(f"{BASE}/dashboard")
    page.get_by_test_id("dashboard").wait_for()
    shot(page, "dashboard")

    page.goto(f"{BASE}/meetings/{AMI_ID}")
    page.get_by_test_id("meeting-detail").wait_for()
    page.wait_for_timeout(1500)  # waveform decode
    shot(page, "detail-summary")

    page.get_by_test_id("tab-decisions").click()
    element(
        page, "article, li, div.rounded-lg", "card-price", "Selling price of 25 euros"
    )
    element(
        page,
        "article, li, div.rounded-lg",
        "card-cost",
        "Maximum production cost of 12.50",
    )
    element(
        page,
        "article, li, div.rounded-lg",
        "card-profit",
        "Target profit of 50 million",
    )
    page.get_by_test_id("tab-risks").click()
    element(page, "article, li, div.rounded-lg", "card-risk", "wholesale vs. retail")
    page.get_by_test_id("tab-actions").click()
    element(
        page,
        "article, li, div.rounded-lg",
        "card-action",
        "user interface and technical",
    )
    page.context.close()


def capture_copilot(browser, key: str) -> None:
    page = new_page(browser, key, "en")
    page.add_init_script(STREAM_SHIM)
    page.goto(f"{BASE}/meetings/{AMI_ID}")
    page.get_by_test_id("copilot-panel").wait_for()
    page.wait_for_timeout(1500)
    shot(page, "copilot-00-empty")

    page.get_by_test_id("copilot-input").click()
    for index in range(1, len(QUESTION) + 1, 6):
        page.get_by_test_id("copilot-input").fill(QUESTION[:index])
    page.get_by_test_id("copilot-input").fill(QUESTION)
    shot(page, "copilot-01-typed")
    page.get_by_test_id("copilot-send").click()
    page.wait_for_function("() => typeof window.__filmPush === 'function'")
    shot(page, "copilot-02-thinking")

    words = ANSWER.split(" ")
    for frame, end in enumerate(range(2, len(words) + 1, 2), start=3):
        page.evaluate(
            "t => window.__filmPush({type: 'partial', text: t})", " ".join(words[:end])
        )
        shot(page, f"copilot-{frame:02d}-partial")
    response = {
        "meeting_id": AMI_ID,
        "question": QUESTION,
        "answer": ANSWER,
        "citations": [
            {
                "segment_id": sid,
                "start_ms": start,
                "end_ms": end,
                "speaker_label": None,
                "text": text,
            }
            for sid, start, end, text in CITED
        ],
        "not_discussed": False,
        "unsupported": False,
        "segments_considered": 371,
        "segments_retrieved": 12,
    }
    page.evaluate(
        "r => { window.__filmPush({type: 'done', response: r}); window.__filmClose(); }",
        response,
    )
    page.locator('[data-state="grounded"]').wait_for()
    shot(page, "copilot-99-answer")
    page.context.close()


def capture_languages(browser, key: str) -> None:
    for lang, meeting_id in (("kk", KK_ID), ("ru", RU_ID)):
        page = new_page(browser, key, lang)
        page.goto(f"{BASE}/meetings/{meeting_id}")
        page.get_by_test_id("meeting-detail").wait_for()
        page.wait_for_timeout(1200)
        page.get_by_test_id("tab-transcript").click()
        shot(page, f"lang-{lang}-transcript")
        page.context.close()


def capture_fresh_transcript(page: Page) -> None:
    page.wait_for_timeout(1500)
    page.get_by_test_id("tab-transcript").click()
    page.get_by_test_id("transcript-list").wait_for()
    shot(page, "upload-transcript")


def capture_upload(browser, key: str) -> None:
    """A real upload: consent dialog, then processing, then the fresh transcript."""
    clip = make_clip(OUT.parent / "pricing-clip.wav")
    page = new_page(browser, key, "en")
    page.goto(f"{BASE}/meetings")
    page.get_by_test_id("meeting-list").wait_for()
    page.get_by_test_id("upload-input").set_input_files(str(clip))
    page.get_by_test_id("consent-dialog").wait_for()
    shot(page, "upload-consent")
    page.locator("#consent-agree").click()
    shot(page, "upload-consent-checked")
    page.get_by_test_id("consent-confirm").click()
    page.wait_for_url("**/meetings/*", timeout=30_000)
    page.get_by_test_id("state-processing").wait_for(timeout=30_000)
    shot(page, "upload-processing")
    page.get_by_test_id("meeting-detail").wait_for(timeout=240_000)
    capture_fresh_transcript(page)
    page.context.close()
    clip.unlink()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    key = os.environ.get("MEETINGOS_API_KEY", "")
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for name, step in (
            ("english", capture_english),
            ("copilot", capture_copilot),
            ("languages", capture_languages),
            ("upload", capture_upload),
        ):
            if not only or name in only:
                step(browser, key)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
