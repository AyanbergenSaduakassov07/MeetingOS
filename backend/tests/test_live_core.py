"""Live captions: segmenter and event-log rules (ARCHITECTURE §3, PLAN §5.1)."""

from __future__ import annotations

import asyncio

from backend.live.eventlog import CLOSED, EventLog
from backend.live.segmenter import Segmenter
from backend.live.types import AsrEvent


def _final(text, start, end, wall=0.0):
    return AsrEvent("final", text, start, end, "en", t_received_wall=wall)


# -- segmenter ---------------------------------------------------------------


def test_segmenter_emits_whole_sentences_and_keeps_the_remainder():
    seg = Segmenter()
    out = seg.on_event(_final("We ship Friday. The budget is", 0, 2000))
    assert [s.text for s in out] == ["We ship Friday."]
    out = seg.on_event(_final("40 million tenge.", 2000, 3000))
    assert [s.text for s in out] == ["The budget is 40 million tenge."]
    assert [s.sid for s in out] == [1]


def test_segmenter_drops_a_replayed_final_after_reconnect():
    seg = Segmenter()
    seg.on_event(_final("Hello there.", 0, 1000))
    assert seg.on_event(_final("Hello there.", 0, 1000)) == []


def test_segmenter_merges_boundary_overlap():
    seg = Segmenter()
    seg.on_event(_final("we agreed to move", 0, 2000))
    out = seg.on_event(_final("to move the launch.", 1500, 3000))
    assert [s.text for s in out] == ["we agreed to move the launch."]


def test_segmenter_cuts_long_unpunctuated_speech_at_a_comma():
    seg = Segmenter(max_words=6)
    out = seg.on_event(_final("one two three, four five six seven", 0, 3000))
    assert [s.text for s in out] == ["one two three,"]


def test_segmenter_forces_out_stale_text_and_flushes_at_end():
    seg = Segmenter(max_pending_s=5)
    seg.on_event(_final("no punctuation here", 0, 1000, wall=100.0))
    assert seg.check_pending(now_wall=101.0) == []
    assert [s.text for s in seg.check_pending(now_wall=106.0)] == ["no punctuation here"]
    seg.on_event(_final("tail", 1000, 1500, wall=107.0))
    assert [s.text for s in seg.flush()] == ["tail"]


def test_segmenter_ignores_partials_and_carries_language():
    seg = Segmenter()
    assert seg.on_event(AsrEvent("partial", "Сәлем", 0, 500, "kk")) == []
    seg.on_event(AsrEvent("final", "Сәлем.", 0, 600, "kk"))
    assert seg.language == "kk"


# -- event log ---------------------------------------------------------------


def test_seq_is_monotonic_and_resume_replays_only_missed_events():
    async def run():
        log = EventLog()
        for i in range(5):
            log.publish("transcript.final", {"i": i})
        backlog, _ = log.subscribe(after_seq=3)
        return [e.seq for e in backlog]

    assert asyncio.run(run()) == [4, 5]


def test_client_behind_the_ring_is_told_to_reload():
    async def run():
        log = EventLog(ring_size=3)
        for i in range(10):
            log.publish("transcript.final", {"i": i})
        backlog, _ = log.subscribe(after_seq=2)
        return [e.type for e in backlog]

    assert asyncio.run(run()) == ["session.reset"]


def test_slow_subscriber_is_dropped_without_blocking_the_publisher():
    async def run():
        log = EventLog(queue_size=2)
        _, slow = log.subscribe(after_seq=0)
        for i in range(5):
            log.publish("transcript.final", {"i": i})  # must not raise or block
        return await slow.get(), log._subs

    first, subs = asyncio.run(run())
    assert first is CLOSED and not subs


def test_close_ends_every_subscriber_and_late_subscribers():
    async def run():
        log = EventLog()
        _, q = log.subscribe(0)
        log.publish("session.state", {"state": "ended"})
        log.close()
        _, late = log.subscribe(0)
        return [await q.get(), await q.get()], await late.get()

    (first, second), late = asyncio.run(run())
    assert first.type == "session.state" and second is CLOSED and late is CLOSED


def test_sse_frame_carries_id_for_last_event_id_resume():
    frame = EventLog().publish("translation.final", {"lang": "ru", "text": "Привет"}).sse()
    assert frame.startswith("id: 1\nevent: translation.final\n") and "Привет" in frame
