"""Backend selection for corpus retrieval.

``MEETINGOS_MEMORY_BACKEND`` picks the implementation; everything downstream
asks for ``get_memory_index()`` and never names a storage engine. Same shape as
``backend/ai/orchestrator.py``.

Instances are cached because a backend may hold connection state, and the
SQLite one lazily creates its schema on first use — rebuilding it per request
would repeat that check on every query.
"""

from __future__ import annotations

import logging
import os

from .backends.sqlite_index import SqliteMemoryIndex
from .base import MemoryIndex

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "sqlite"

BACKENDS: dict[str, type[MemoryIndex]] = {
    "sqlite": SqliteMemoryIndex,
    # "pgvector": PgVectorMemoryIndex — the swap this seam exists for. It needs
    # only to satisfy MemoryIndex; no call site changes.
}

_instances: dict[str, MemoryIndex] = {}


class UnknownBackendError(ValueError):
    """``MEETINGOS_MEMORY_BACKEND`` named something that is not registered."""


def available_backends() -> list[str]:
    return sorted(BACKENDS)


def get_memory_index(name: str | None = None) -> MemoryIndex:
    """Resolve the corpus-retrieval backend."""
    resolved = (name or os.environ.get("MEETINGOS_MEMORY_BACKEND") or DEFAULT_BACKEND).strip().lower()
    if resolved not in BACKENDS:
        raise UnknownBackendError(f"Unknown memory backend {resolved!r}. Available: {', '.join(available_backends())}")
    if resolved not in _instances:
        _instances[resolved] = BACKENDS[resolved]()
        logger.info("Memory backend initialized: %s", resolved)
    return _instances[resolved]


def reset_backends() -> None:
    """Drop cached instances. Used by tests that swap environment variables."""
    _instances.clear()
