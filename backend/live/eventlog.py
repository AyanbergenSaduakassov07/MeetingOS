"""Per-session event stream: monotonic ``seq``, bounded replay, bounded fan-out.

Clients load a snapshot (which carries the ``seq`` it was taken at), then
subscribe after that ``seq``. A client too far behind the ring gets
``session.reset`` and reloads the snapshot; a subscriber too slow to drain its
queue is dropped and reconnects with ``Last-Event-ID``. Nothing here blocks the
publisher, so one stuck viewer cannot stall the pipeline.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass

RING_SIZE = 2000
QUEUE_SIZE = 500
CLOSED = None  # sentinel put on a queue when the stream ends or the subscriber is dropped


@dataclass(frozen=True)
class LiveEvent:
    seq: int
    type: str
    data: dict
    ts: float

    def sse(self) -> str:
        payload = json.dumps({"seq": self.seq, "type": self.type, "ts": self.ts, **self.data}, ensure_ascii=False)
        return f"id: {self.seq}\nevent: {self.type}\ndata: {payload}\n\n"


class EventLog:
    def __init__(self, ring_size: int = RING_SIZE, queue_size: int = QUEUE_SIZE) -> None:
        self.seq = 0
        self._ring: deque[LiveEvent] = deque(maxlen=ring_size)
        self._subs: set[asyncio.Queue] = set()
        self._queue_size = queue_size
        self.closed = False

    def publish(self, type_: str, data: dict) -> LiveEvent:
        self.seq += 1
        event = LiveEvent(self.seq, type_, data, time.time())
        self._ring.append(event)
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._drop(q)
        return event

    def subscribe(self, after_seq: int) -> tuple[list[LiveEvent], asyncio.Queue]:
        """Events after ``after_seq`` still in the ring, plus a queue for new ones."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        oldest = self._ring[0].seq if self._ring else self.seq + 1
        if after_seq < oldest - 1:
            backlog = [LiveEvent(self.seq, "session.reset", {"reason": "behind"}, time.time())]
        else:
            backlog = [e for e in self._ring if e.seq > after_seq]
        if self.closed:
            q.put_nowait(CLOSED)
        else:
            self._subs.add(q)
        return backlog, q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def close(self) -> None:
        """End every stream after the events already queued, so viewers still see the last state."""
        self.closed = True
        for q in list(self._subs):
            self._subs.discard(q)
            try:
                q.put_nowait(CLOSED)
            except asyncio.QueueFull:
                self._drop(q)  # too slow anyway; it reloads the snapshot

    def _drop(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)
        while not q.empty():
            q.get_nowait()
        q.put_nowait(CLOSED)
