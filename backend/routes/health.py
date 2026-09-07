"""Health and readiness.

Reports whether the database is reachable and which AI/transcription
providers are selected and credentialed.  Deliberately does not call either
upstream API: ``/health`` is polled by the dev tooling and by container
orchestration, and a probe that costs money or blocks on a third party is a
probe that gets disabled.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import __version__
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _provider_status() -> dict[str, Any]:
    """Describe the configured providers without calling them.

    Import failures and bad provider names are reported as status rather than
    raised — a misconfigured provider should make ``/health`` say so, not make
    the health check itself 500.
    """
    status: dict[str, Any] = {}

    try:
        from ..ai import get_llm_provider

        provider = get_llm_provider()
        status["ai"] = {
            "provider": provider.config.name,
            "model": provider.config.model,
            "configured": provider.is_configured(),
        }
    except Exception as exc:
        status["ai"] = {"error": str(exc)}

    try:
        from ..transcription import get_transcription_provider

        transcriber = get_transcription_provider()
        status["transcription"] = {
            "provider": transcriber.config.name,
            "model": transcriber.config.model,
            "configured": transcriber.is_configured(),
            "supports_diarization": transcriber.config.supports_diarization,
        }
    except Exception as exc:
        status["transcription"] = {"error": str(exc)}

    return status


@router.get("/health")
async def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Liveness and dependency status."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.warning("Health check could not reach the database: %s", exc)
        db_status = "error"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "version": __version__,
        "db": db_status,
        **_provider_status(),
    }
