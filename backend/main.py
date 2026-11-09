"""MeetingOS server entry point.

Imports the configured FastAPI app and provides a ``python -m backend.main``
entry point for development.
"""

import argparse
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# Before importing the app: providers and auth read the environment.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import config, database  # noqa: E402
from .app import app  # noqa: E402, F401 -- re-export for uvicorn "backend.main:app"
from .auth import require_safe_bind  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MeetingOS server")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (use 0.0.0.0 for remote access)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8470,
        help="Port to bind to",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Data directory for the database and meeting recordings",
    )
    args = parser.parse_args()

    require_safe_bind(args.host)

    if args.data_dir:
        config.set_data_dir(args.data_dir)

    database.init_db()

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=False,
    )
