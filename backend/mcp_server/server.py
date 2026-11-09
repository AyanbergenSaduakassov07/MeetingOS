"""FastMCP server mounted at ``/mcp`` (Streamable HTTP), behind the same API key as REST."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from fastmcp import FastMCP

from .tools import register_tools


def build_mcp_server() -> FastMCP:
    mcp = FastMCP(
        name="meetingos",
        instructions=(
            "MeetingOS holds an organisation's meetings: transcripts, decisions, commitments and "
            "documents. Use `ask` for questions and cite what it returns; use `list_meetings` and "
            "`list_commitments` to browse. All tools are read-only."
        ),
    )
    register_tools(mcp)
    return mcp


def compose_lifespan(*lifespans):
    """Enter lifespans in order, exit in reverse. FastMCP's session manager must run inside the ASGI lifespan."""

    @asynccontextmanager
    async def _combined(app):
        async with AsyncExitStack() as stack:
            for factory in lifespans:
                await stack.enter_async_context(factory(app))
            yield

    return _combined
