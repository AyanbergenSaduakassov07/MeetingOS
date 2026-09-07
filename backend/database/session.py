"""Engine creation, initialization, and session management."""

import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .. import config
from .migrations import run_migrations
from .models import Base

logger = logging.getLogger(__name__)

# Initialized by init_db()
engine = None
SessionLocal = None
_db_path = None


def init_db() -> None:
    """Initialize the database engine, run migrations, and create tables."""
    global engine, SessionLocal, _db_path

    _db_path = config.get_db_path()
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{_db_path}",
        connect_args={"check_same_thread": False},
    )

    # SQLite ignores foreign keys unless asked per-connection. The schema
    # leans on FKs (cascade deletes from Meeting down to segments), so this
    # has to be on for every pooled connection, not just the first.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    run_migrations(engine)
    Base.metadata.create_all(bind=engine)

    logger.info("Database ready: %s", _db_path)


def new_session():
    """Return a new Session, or explain why one cannot be made.

    ``init_db`` rebinds the module-level ``SessionLocal``, so anything that
    captured that name at import time holds ``None`` forever. Callers outside
    a request — background tasks especially — must go through this accessor,
    which reads the live binding at call time.
    """
    if SessionLocal is None:
        raise RuntimeError("Database is not initialized — call backend.database.init_db() first.")
    return SessionLocal()


def get_db():
    """Yield a database session (FastAPI dependency)."""
    db = new_session()
    try:
        yield db
    finally:
        db.close()
