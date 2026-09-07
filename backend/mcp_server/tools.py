"""MeetingOS MCP tool implementations.

All four voicebox tools are gone.  Why each, since three of them were
predictable and the fourth was not:

``voicebox.speak`` and ``voicebox.list_profiles``
    Removed with the TTS surface.  Both are voice-profile operations and
    there is nothing in the meeting domain they map onto.

``voicebox.list_captures``
    Removed.  "Captures" were push-to-talk dictation clips.  The nearest
    meeting concept is a ``Meeting``, but the two are not the same object and
    an agent listing meetings wants filters ("last week's board meetings"),
    not a reverse-chronological clip feed.  Reusing the name would have
    shipped a misleading tool.

``voicebox.transcribe``
    Removed, and this one is worth explaining because Phase 0 identified it
    as the tool that could survive.  On a closer read it does not generalize:
    it resolved a *local* Whisper model, validated the requested size against
    ``WHISPER_HF_REPOS``, checked the model was already downloaded, and told
    failing callers to "open Voicebox → Settings → Models".  Every one of
    those references is gone.  What remained after stripping them was a
    thin base64/path wrapper shaped for short dictation clips — a 200 MB
    ceiling, one-shot, no diarization, no speaker attribution, no job
    tracking.  A two-hour board recording needs all four.  Rewriting it
    against ``backend.transcription`` would not be adapting the tool, it
    would be writing a new one under an old name.

Future work, explicitly not v0.1: an ``ask_meeting`` tool that takes a
question and a meeting id and answers over the stored transcript, decisions,
and action items.  That is the tool an agent actually wants, and it depends on
extraction and retrieval that do not exist yet.  Adding it before then would
mean shipping an endpoint with nothing behind it.

The MCP server itself stays mounted and running — the transport, client-id
middleware, and event stream are all still wired — so registering the first
meeting tool is a one-function change.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """Attach MeetingOS tools to the given FastMCP instance.

    Intentionally empty for v0.1: the server exposes no tools until
    ``ask_meeting`` lands.  A FastMCP server with zero tools is valid — it
    completes the handshake and returns an empty tool list — so clients
    connect cleanly and simply see nothing to call.
    """
    logger.info("MCP: no tools registered (v0.1 — meeting tools are future work)")
