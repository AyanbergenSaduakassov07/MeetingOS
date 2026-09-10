"""Record every outbound call to a third-party model or transcription API.

The question this answers is the one an operator otherwise cannot: *what left
this machine, to whom, and when.* Until now the only record of a cloud call was
a log line that scrolled away.

What is recorded, and what is deliberately not
-----------------------------------------------
The shape of the call: provider, model, operation, destination host, how many
characters and items went out, whether redaction was on and how many spans it
removed, token cost, and outcome.

**Not the content.** No prompts, no transcript text, no answers. A log holding
the payloads would double the exposure it exists to document, and would be the
first thing an attacker who got database access would read. Character counts
are enough to answer "was that whole board pack sent?" without becoming a
second copy of the board pack.

Failure to log never fails the call. An audit trail that can take down
transcription is a worse trade than a trail with a gap in it — so every write
here is wrapped, and a failure is logged rather than raised.
"""

from __future__ import annotations

import contextlib
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Hosts that are this machine. Calls to these are not cloud egress, and the
# privacy page says so.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


@dataclass
class CallRecord:
    """One outbound call in progress."""

    provider: str
    operation: str
    model: str | None = None
    endpoint_host: str | None = None
    org_id: str | None = None
    meeting_id: str | None = None
    characters_sent: int = 0
    items_sent: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    redaction_enabled: bool = False
    redactions_applied: int = 0
    succeeded: bool = True
    error: str | None = None
    duration_ms: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def is_cloud(self) -> bool:
        return (self.endpoint_host or "") not in LOCAL_HOSTS


def host_of(base_url: str | None, *, default: str | None = None) -> str | None:
    """The host a base URL points at, for the audit record."""
    if not base_url:
        return default
    try:
        return (urlparse(base_url).hostname or default or "").lower() or default
    except Exception:
        return default


def record(call: CallRecord, *, db=None) -> None:
    """Persist one call record. Never raises."""
    from ..database import ProviderCall, new_session

    owns = db is None
    try:
        db = db or new_session()
        db.add(
            ProviderCall(
                org_id=call.org_id,
                meeting_id=call.meeting_id,
                provider=call.provider,
                model=call.model,
                operation=call.operation,
                endpoint_host=call.endpoint_host,
                is_cloud=call.is_cloud,
                characters_sent=call.characters_sent,
                items_sent=call.items_sent,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                redaction_enabled=call.redaction_enabled,
                redactions_applied=call.redactions_applied,
                succeeded=call.succeeded,
                error=(call.error or None) and call.error[:500],
                duration_ms=call.duration_ms,
            )
        )
        db.commit()
    except Exception as exc:
        # An audit trail that can take down transcription is the wrong trade.
        logger.warning("Could not record provider call (%s/%s): %s", call.provider, call.operation, exc)
    finally:
        if owns and db is not None:
            with contextlib.suppress(Exception):
                db.close()


@contextmanager
def logged_call(
    provider: str,
    operation: str,
    *,
    model: str | None = None,
    endpoint_host: str | None = None,
    texts: list[str] | None = None,
    org_id: str | None = None,
    meeting_id: str | None = None,
    db=None,
):
    """Time an outbound call and record it, whatever happens to it.

    Yields the ``CallRecord`` so the caller can attach token usage after the
    response lands.
    """
    from .redaction import is_enabled

    call = CallRecord(
        provider=provider,
        operation=operation,
        model=model,
        endpoint_host=endpoint_host,
        org_id=org_id,
        meeting_id=meeting_id,
        characters_sent=sum(len(text or "") for text in (texts or [])),
        items_sent=len(texts or []),
        redaction_enabled=is_enabled(),
    )
    started = time.monotonic()
    try:
        yield call
    except Exception as exc:
        call.succeeded = False
        call.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        call.duration_ms = int((time.monotonic() - started) * 1000)
        record(call, db=db)
