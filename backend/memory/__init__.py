"""Corpus-wide memory: index and retrieve records across every meeting in an org."""

from .base import (
    RECORD_TYPES,
    CapabilityError,
    IndexReport,
    MemoryIndex,
    MemoryIndexConfig,
    MemoryRecord,
    RecordType,
)
from .orchestrator import (
    UnknownBackendError,
    available_backends,
    get_memory_index,
    reset_backends,
)
from .retrieval import (
    index_document,
    index_meeting,
    purge_document,
    purge_meeting,
    search_corpus,
)

__all__ = [
    "RECORD_TYPES",
    "CapabilityError",
    "IndexReport",
    "MemoryIndex",
    "MemoryIndexConfig",
    "MemoryRecord",
    "RecordType",
    "UnknownBackendError",
    "available_backends",
    "get_memory_index",
    "index_document",
    "index_meeting",
    "purge_document",
    "purge_meeting",
    "reset_backends",
    "search_corpus",
]
