"""FastAPI application factory, middleware, and lifecycle events."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, auth, config, database
from .routes import register_routers


class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors matching uvicorn's style."""

    COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


# Configure logging to match uvicorn's format with colors
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(ColoredFormatter("%(levelname)s:     %(message)s"))
logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
)

logger = logging.getLogger(__name__)


def safe_content_disposition(disposition_type: str, filename: str) -> str:
    """Build a Content-Disposition header safe for non-ASCII filenames.

    Uses RFC 5987 ``filename*`` parameter so browsers can decode UTF-8
    filenames while the ``filename`` fallback stays ASCII-only.
    """
    ascii_name = "".join(c for c in filename if c.isascii() and (c.isalnum() or c in " -_.")).strip() or "download"
    utf8_name = quote(filename, safe="")
    return f"{disposition_type}; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 without echoing the input: the default handler crashes (500) on binary bodies."""
    errors = [{key: error[key] for key in ("loc", "msg", "type") if key in error} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from .mcp_server.server import build_mcp_server, compose_lifespan

    # Build the MCP app up-front so we can wire its lifespan into FastAPI's —
    # FastMCP's Streamable HTTP transport only works if its session manager
    # runs inside the parent ASGI lifespan.
    mcp = build_mcp_server()
    mcp_app = mcp.http_app(path="/", transport="http")

    @asynccontextmanager
    async def meetingos_lifespan(app: FastAPI):
        await _run_startup(app)
        try:
            yield
        finally:
            # Paired with _run_startup via try/finally so a partial startup
            # still runs its teardown.
            await _run_shutdown()

    # compose_lifespan enters factories in order (MeetingOS startup → MCP
    # startup) and exits in LIFO, so FastMCP cancels in-flight session tasks
    # before the application tears its own state down.
    lifespan = compose_lifespan(meetingos_lifespan, mcp_app.router.lifespan_context)

    application = FastAPI(
        title="MeetingOS API",
        description="Meeting intelligence: transcription, extraction, and decision lineage",
        version=__version__,
        lifespan=lifespan,
    )

    # Starlette wraps each added middleware around the previous ones, so CORS
    # (added second) is outermost: preflights and 401s still get CORS headers.
    application.add_middleware(auth.ApiKeyMiddleware)
    _configure_cors(application)
    application.include_router(auth.router)
    register_routers(application)
    application.add_exception_handler(RequestValidationError, _validation_error)
    application.mount("/mcp", mcp_app)
    logger.info("MCP: mounted at /mcp")
    _mount_frontend(application)

    return application


def _configure_cors(application: FastAPI) -> None:
    """Set up CORS middleware with local-first defaults.

    Allowed by default: the Vite dev server and the API's own origin.
    """
    default_origins = [
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",
        "http://localhost:8470",
        "http://127.0.0.1:8470",
    ]
    env_origins = os.environ.get("MEETINGOS_CORS_ORIGINS", "")
    extra_origins = [o.strip() for o in env_origins.split(",") if o.strip()]

    # "*" with allow_credentials=True turns any page the user visits into a
    # reader of this API. Browsers reject that pairing themselves, but the
    # request still leaves and the misconfiguration stays invisible, so refuse
    # it here and say why.
    if "*" in extra_origins:
        logger.warning(
            "MEETINGOS_CORS_ORIGINS contains '*', which is refused because credentials "
            "are allowed. List the origins explicitly instead."
        )
        extra_origins = [o for o in extra_origins if o != "*"]

    all_origins = default_origins + extra_origins

    application.add_middleware(
        CORSMiddleware,
        allow_origins=all_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _mount_frontend(application: FastAPI) -> None:
    """Serve the built web frontend when present (Docker / web deployment).

    The Dockerfile copies the Vite build output to ``/app/frontend/``.  When
    that directory exists we mount static assets and add a catch-all route so
    the React SPA handles client-side routing.  In dev or API-only mode the
    directory is absent and this function is a no-op.
    """
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if not frontend_dir.is_dir():
        return

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # Mount hashed assets (JS, CSS, images) that Vite places under /assets
    assets_dir = frontend_dir / "assets"
    if assets_dir.is_dir():
        application.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="frontend-assets",
        )

    # SPA catch-all: serve files if they exist, otherwise index.html for
    # client-side routes.
    @application.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = (frontend_dir / full_path).resolve()
        # Guard against path traversal — only serve files inside frontend_dir
        if full_path and file_path.is_file() and file_path.is_relative_to(frontend_dir):
            return FileResponse(file_path)
        return FileResponse(frontend_dir / "index.html", media_type="text/html")

    logger.info("Frontend: serving SPA from %s", frontend_dir)


async def _run_startup(application: FastAPI) -> None:
    """Database init and environment logging. Runs on lifespan entry."""
    import platform

    logger.info("MeetingOS v%s starting up", __version__)
    logger.info(
        "Python %s on %s %s (%s)",
        sys.version.split()[0],
        platform.system(),
        platform.release(),
        platform.machine(),
    )

    database.init_db()
    database.ensure_default_org()
    from .meetings.ingestion import resume_interrupted

    resume_interrupted()
    logger.info("Data directory: %s", config.get_data_dir())

    _log_provider_selection()

    logger.info("Ready")


def _log_provider_selection() -> None:
    """Log which providers are selected, and whether they have credentials.

    Startup is where a missing API key should become visible — not the first
    time a meeting finishes uploading. Logged rather than raised so the API
    still boots for read-only work with no credentials at all.
    """
    try:
        from .ai import get_llm_provider

        provider = get_llm_provider()
        logger.info(
            "AI provider: %s (%s)%s",
            provider.config.name,
            provider.config.model,
            "" if provider.is_configured() else f" — {provider.config.api_key_env} not set",
        )
    except Exception as exc:
        logger.warning("AI provider unavailable: %s", exc)

    try:
        from .transcription import get_transcription_provider

        transcriber = get_transcription_provider()
        logger.info(
            "Transcription provider: %s (%s)%s",
            transcriber.config.name,
            transcriber.config.model,
            "" if transcriber.is_configured() else f" — {transcriber.config.api_key_env or 'dependency'} not set",
        )
    except Exception as exc:
        logger.warning("Transcription provider unavailable: %s", exc)


async def _run_shutdown() -> None:
    """Release resources on lifespan exit."""
    logger.info("MeetingOS shutting down")


app = create_app()
