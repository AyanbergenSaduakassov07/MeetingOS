"""Fixtures shared across the meeting test modules.

``data_dir`` and ``db`` were originally duplicated per module; they live here
so a new test module gets a real, isolated SQLite database without copying the
setup and drifting from it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import config, database


@pytest.fixture
def data_dir(tmp_path: Path):
    """Point the app at a throwaway data directory and initialise the schema."""
    previous = config.get_data_dir()
    config.set_data_dir(tmp_path)
    database.init_db()
    yield tmp_path
    config.set_data_dir(previous)


@pytest.fixture
def db(data_dir):
    session = database.new_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Counters are process-global; without this, test N+1 inherits test N's hits."""
    from backend.routes import limits

    limits.reset()
    yield
    limits.reset()
