"""Guest viewer links: 32 random bytes, only the SHA-256 stored, scoped to one
session, viewer-only, expiring, revocable."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from ..database.models import LiveJoinToken

TOKEN_TTL = timedelta(hours=12)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(db: Session, session_id: str, ttl: timedelta = TOKEN_TTL) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(LiveJoinToken(session_id=session_id, token_hash=_hash(raw), expires_at=datetime.now(UTC) + ttl))
    db.commit()
    return raw


def token_valid(db: Session, session_id: str, raw: str | None) -> bool:
    if not raw or len(raw) > 128:
        return False
    row = db.query(LiveJoinToken).filter_by(token_hash=_hash(raw)).first()
    if row is None or row.session_id != session_id or row.revoked_at is not None:
        return False
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)  # SQLite drops tz
    return expires > datetime.now(UTC)


def revoke_all(db: Session, session_id: str) -> int:
    count = (
        db.query(LiveJoinToken)
        .filter_by(session_id=session_id, revoked_at=None)
        .update({"revoked_at": datetime.now(UTC)})
    )
    db.commit()
    return count
