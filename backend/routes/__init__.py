"""Route registration for the MeetingOS API.

The voice-cloning routers (profiles, generations, captures, stories, effects,
audio, channels, history, speak, transcription, models, cuda, rocm, llm,
cloud, mcp_bindings) are gone rather than stubbed — a registered router that
raises is worse than no router, because it still publishes an endpoint in the
OpenAPI schema that clients can find.

They were unregistered first and left on disk, which is a different thing from
gone: `routes/models.py` still carried HuggingFace download machinery, reachable
the moment anyone added it back to the list below. The files are deleted now,
along with `backend/{backends,services,utils,mcp_shim}` and the PyInstaller
packaging that referenced them. Everything in that cluster only referred to
itself, which is why none of it showed up as broken while it sat there.

``events`` went for the same reason, less obviously: ``GET /events/speak``
streams speak-start/speak-end for the desktop speaking pill. Its emitters
(the MCP speak tool, ``POST /speak``) and its only consumer (DictateWindow)
are both gone, so it would have published a stream that can never emit. The
underlying pub/sub in ``mcp_server.events`` is domain-neutral and stays —
meeting processing progress is the obvious next thing to broadcast over it.
"""

from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    """Include all domain routers on the application."""
    from .commitments import router as commitments_router
    from .copilot import router as copilot_router
    from .dashboard import router as dashboard_router
    from .decisions import router as decisions_router
    from .documents import router as documents_router
    from .health import router as health_router
    from .meetings import router as meetings_router
    from .privacy import router as privacy_router

    app.include_router(health_router)
    app.include_router(meetings_router)
    app.include_router(decisions_router)
    app.include_router(commitments_router)
    app.include_router(copilot_router)
    app.include_router(documents_router)
    app.include_router(dashboard_router)
    app.include_router(privacy_router)
