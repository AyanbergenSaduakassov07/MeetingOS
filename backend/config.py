"""
Configuration module for voicebox backend.

Handles data directory configuration for production bundling.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Allow users to override the HuggingFace model download directory.
# Set VOICEBOX_MODELS_DIR to an absolute path before starting the server.
# This sets HF_HUB_CACHE so all huggingface_hub downloads go to that path.
_custom_models_dir = os.environ.get("VOICEBOX_MODELS_DIR")
if _custom_models_dir:
    os.environ["HF_HUB_CACHE"] = _custom_models_dir
    logger.info("Model download path set to: %s", _custom_models_dir)

# Default data directory (used in development)
_data_dir = Path("data").resolve()


def _path_relative_to_any_data_dir(path: Path) -> Path | None:
    """Extract the path within a data dir from an absolute or relative path."""
    parts = path.parts
    for idx, part in enumerate(parts):
        if part != "data":
            continue

        tail = parts[idx + 1 :]
        if tail:
            return Path(*tail)
        return Path()

    return None


def set_data_dir(path: str | Path):
    """
    Set the data directory path.

    Args:
        path: Path to the data directory
    """
    global _data_dir
    _data_dir = Path(path).resolve()
    _data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Data directory set to: %s", _data_dir)


def get_data_dir() -> Path:
    """
    Get the data directory path.

    Returns:
        Path to the data directory
    """
    return _data_dir


def to_storage_path(path: str | Path) -> str:
    """Convert a filesystem path to a DB-safe path relative to the data dir."""
    resolved_path = Path(path).resolve()

    relative_to_any_data_dir = _path_relative_to_any_data_dir(resolved_path)
    if relative_to_any_data_dir is not None:
        return str(relative_to_any_data_dir)

    try:
        return str(resolved_path.relative_to(_data_dir))
    except ValueError:
        return str(resolved_path)


def resolve_storage_path(path: str | Path | None) -> Path | None:
    """Resolve a DB-stored path against the configured data dir."""
    if path is None:
        return None

    stored_path = Path(path)
    # Empty paths (e.g. failed generations) must not resolve to the data
    # dir itself, which exists and would defeat the callers' 404 guards.
    # Path("") is truthy, so check parts rather than the raw value.
    if not stored_path.parts:
        return None
    if stored_path.is_absolute():
        rebased_path = _path_relative_to_any_data_dir(stored_path)
        if rebased_path is not None:
            candidate = (_data_dir / rebased_path).resolve()
            if candidate.exists() or not stored_path.exists():
                return candidate

        return stored_path

    # 0.3.0 records sometimes stored relative paths with the data-dir name
    # baked in (e.g. "data/profiles/..."). Joining those directly with
    # _data_dir produces a spurious "<data_dir>/data/profiles/..." nest.
    if stored_path.parts and stored_path.parts[0] == "data":
        stored_path = Path(*stored_path.parts[1:]) if len(stored_path.parts) > 1 else Path()

    return (_data_dir / stored_path).resolve()


def get_db_path() -> Path:
    """Get database file path."""
    return _data_dir / "meetingos.db"


def get_profiles_dir() -> Path:
    """Get profiles directory path."""
    path = _data_dir / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_generations_dir() -> Path:
    """Get generations directory path."""
    path = _data_dir / "generations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_captures_dir() -> Path:
    """Get captures directory path."""
    path = _data_dir / "captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_recordings_dir() -> Path:
    """Get meeting recordings directory path."""
    path = _data_dir / "recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_dir() -> Path:
    """Get cache directory path."""
    path = _data_dir / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_models_dir() -> Path:
    """Get models directory path."""
    path = _data_dir / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Voicebox Cloud (backup & sync). Two hosts: the web app owns auth + device
# pairing (voicebox.sh), the API owns sync + account endpoints
# (api.voicebox.sh). Override both for local development, e.g.
# VOICEBOX_CLOUD_URL=http://localhost:17592 VOICEBOX_CLOUD_API_URL=http://localhost:17593
def get_cloud_web_url() -> str:
    """Base URL of the Voicebox Cloud web app (auth + /connect + exchange)."""
    return os.environ.get("VOICEBOX_CLOUD_URL", "https://voicebox.sh").rstrip("/")


def get_cloud_api_url() -> str:
    """Base URL of the Voicebox Cloud API (bearer-authenticated sync/account)."""
    return os.environ.get("VOICEBOX_CLOUD_API_URL", "https://api.voicebox.sh").rstrip("/")


# -- outbound inference endpoints -----------------------------------------

# Every recording and every transcript this system processes is sent to
# whatever host ``OPENAI_BASE_URL`` names. Read unvalidated, that env var is a
# one-line data-exfiltration switch: point it anywhere and all meeting audio
# and text follows, with nothing in the logs saying the destination changed.
#
# The allowlist is not a strong control — anyone who can set OPENAI_BASE_URL
# can usually also set this — but it turns a silent redirect into a deliberate,
# logged act, which is the difference between a mistake and a decision.
DEFAULT_ALLOWED_INFERENCE_HOSTS = (
    "api.openai.com",
    "api.anthropic.com",
    "openrouter.ai",
)

INFERENCE_HOST_ALLOWLIST_ENV = "MEETINGOS_ALLOWED_INFERENCE_HOSTS"


def allowed_inference_hosts() -> set[str]:
    """Hosts meeting audio and transcripts may be sent to."""
    extra = os.environ.get(INFERENCE_HOST_ALLOWLIST_ENV, "")
    return set(DEFAULT_ALLOWED_INFERENCE_HOSTS) | {host.strip().lower() for host in extra.split(",") if host.strip()}


def validate_inference_base_url(base_url: str | None, *, provider: str) -> str | None:
    """Refuse a base URL whose host is not allowlisted.

    Returns the URL unchanged when it is acceptable (including ``None``, which
    means the SDK default). Raises ``ValueError`` otherwise, at startup rather
    than mid-meeting.
    """
    if not base_url:
        return base_url

    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    allowed = allowed_inference_hosts()

    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"{provider}: base URL {base_url!r} is not http(s).")
    if parsed.scheme == "http" and host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            f"{provider}: refusing plaintext http to {host!r}. Meeting audio and "
            "transcripts must not cross the network unencrypted."
        )
    if host not in allowed and host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            f"{provider}: host {host!r} is not in the inference allowlist "
            f"({', '.join(sorted(allowed))}). Every recording and transcript is sent "
            f"to this host, so adding one is a data-residency decision: set "
            f"{INFERENCE_HOST_ALLOWLIST_ENV} explicitly to accept it."
        )

    logger.info("%s: outbound inference endpoint is %s", provider, host)
    return base_url


# Tenant pinning.
#
# There is no authentication in v0.1, and every route that takes an ``org_id``
# takes it from the request. For the org-wide copilot that is a whole-tenant
# read behind one parameter: pass another org's id and its entire corpus
# answers your question.
#
# Authentication plus a server-side binding is the real fix and is not built
# here. ``MEETINGOS_ORG_ID`` is the control that can exist without it: set it,
# and the process serves exactly one organisation — a request naming any other
# is refused rather than answered. Unset, behaviour is unchanged, which keeps
# single-org development installs working as they do today.
#
# This bounds a misdirected or curious request. It does not stop anyone who can
# reach the port and set the variable, because nothing here can.
PINNED_ORG_ENV = "MEETINGOS_ORG_ID"


def pinned_org_id() -> str | None:
    """The single organisation this process serves, if one was pinned."""
    return os.environ.get(PINNED_ORG_ENV, "").strip() or None
