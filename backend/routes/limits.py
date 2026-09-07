"""Rate limits for the endpoints that spend money at a third party.

``POST /ask`` costs an embedding call plus a generation call every time it is
hit, and ``POST /upload`` buys a transcription plus four extraction calls per
topic. Neither is authenticated. Without a limit, anyone who can reach the port
can run up an arbitrary bill — the denial-of-wallet case, which needs no
cleverness and leaves no obvious trace beyond the invoice.

This is a fixed-window counter held in process memory. That is the right size
for a single-process v0.1 and honestly the wrong shape for anything else: it
resets when the process restarts, and it does not coordinate across workers.
When this runs behind more than one worker, move it to Redis or the gateway.

Identity is the client IP, because there is no authentication yet. An IP is a
weak key — it is shared behind NAT and trivially rotated — so this bounds
accidental and casual abuse, not a determined attacker. The real fix is auth
plus a per-account quota; this is the stopgap that keeps the bill finite until
then, and it is deliberately generous enough not to interrupt normal use.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60.0

# Per client, per window. Asking a dozen questions a minute is a busy human;
# six hundred is a script.
ASK_PER_MINUTE = int(os.environ.get("MEETINGOS_ASK_PER_MINUTE", "20"))
UPLOAD_PER_MINUTE = int(os.environ.get("MEETINGOS_UPLOAD_PER_MINUTE", "5"))

_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request, bucket: str) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{bucket}:{client}"


def _check(request: Request, bucket: str, limit: int) -> None:
    now = time.monotonic()
    key = _client_key(request, bucket)
    hits = _hits[key]

    while hits and now - hits[0] > WINDOW_SECONDS:
        hits.popleft()

    if len(hits) >= limit:
        retry_after = int(WINDOW_SECONDS - (now - hits[0])) + 1
        logger.warning("Rate limit hit on %s by %s", bucket, key.split(":", 1)[1])
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit: at most {limit} {bucket} requests per minute. Retry in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    hits.append(now)

    # Unbounded growth of the key space is its own small denial of service.
    if len(_hits) > 10_000:
        stale = [key for key, window in _hits.items() if not window or now - window[-1] > WINDOW_SECONDS]
        for key in stale:
            del _hits[key]


async def limit_ask(request: Request) -> None:
    """FastAPI dependency for the copilot endpoint."""
    _check(request, "ask", ASK_PER_MINUTE)


async def limit_upload(request: Request) -> None:
    """FastAPI dependency for the upload endpoint."""
    _check(request, "upload", UPLOAD_PER_MINUTE)


def reset() -> None:
    """Drop all counters. For tests."""
    _hits.clear()
