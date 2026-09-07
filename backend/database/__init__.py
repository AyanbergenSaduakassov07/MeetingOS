"""Database package — ORM models, session management, and migrations.

Re-exports the public symbols so importers can use ``from .database import
get_db`` and ``from .database import Meeting`` without reaching into
submodules.
"""

from .models import (
    ActionItem,
    ActionItemStatus,
    Base,
    Commitment,
    CommitmentStatus,
    Decision,
    DecisionEvent,
    DecisionEventType,
    DecisionStatus,
    Document,
    DocumentChunk,
    DocumentType,
    EvalCase,
    EvalTask,
    Evidence,
    EvidenceCitation,
    Meeting,
    MeetingDocument,
    MeetingSource,
    MeetingStatus,
    MeetingTemplate,
    Organization,
    Priority,
    Risk,
    RiskSeverity,
    RiskStatus,
    Speaker,
    Topic,
    TranscriptSegment,
    User,
    UserRole,
    VerificationStatus,
    Visibility,
)
from .session import get_db, init_db, new_session

# ``engine``, ``SessionLocal``, and ``_db_path`` are deliberately NOT imported
# by value: ``init_db`` rebinds them inside ``session``, and a value imported
# here would stay pinned to the pre-init ``None``. PEP 562 module __getattr__
# forwards the attribute lookup so ``database.SessionLocal`` always resolves
# to the live object. Prefer ``new_session()`` in new code.
_FORWARDED = {"engine", "SessionLocal", "_db_path"}


def __getattr__(name: str):
    if name in _FORWARDED:
        from . import session

        return getattr(session, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DocumentChunk",
    "Evidence",
    "EvidenceCitation",
    "MeetingDocument",
    # Entities
    "Base",
    "Organization",
    "User",
    "Meeting",
    "Speaker",
    "TranscriptSegment",
    "Topic",
    "Decision",
    "DecisionEvent",
    "ActionItem",
    "Risk",
    "Commitment",
    "MeetingTemplate",
    "Document",
    "EvalCase",
    # Enumerations
    "UserRole",
    "MeetingStatus",
    "MeetingSource",
    "Visibility",
    "DecisionStatus",
    "DecisionEventType",
    "ActionItemStatus",
    "Priority",
    "RiskSeverity",
    "RiskStatus",
    "CommitmentStatus",
    "DocumentType",
    "EvalTask",
    "VerificationStatus",
    # Session
    "engine",
    "SessionLocal",
    "_db_path",
    "init_db",
    "get_db",
    "new_session",
]
