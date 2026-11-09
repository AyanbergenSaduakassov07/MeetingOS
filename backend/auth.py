"""API-key authentication.

One deployment serves one team, guarded by one key (``MEETINGOS_API_KEY``).
Agents and scripts send ``Authorization: Bearer <key>``. The browser exchanges
the key once at ``POST /api/session`` for an HttpOnly, SameSite=Strict cookie,
so ``<audio src>`` and the OpenAPI page work without the key living in JS.

Without a key the server is open, which is only acceptable on loopback:
``require_safe_bind`` refuses to start on any other interface. Per-user
accounts are on the roadmap; this is the control that must exist before them.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from http.cookies import SimpleCookie

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

API_KEY_ENV = "MEETINGOS_API_KEY"
SESSION_COOKIE = "meetingos_session"
MIN_KEY_LENGTH = 16
SESSION_MAX_AGE_S = 7 * 24 * 3600
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

PROTECTED_PREFIXES = ("/api", "/mcp", "/docs", "/redoc", "/openapi.json")
# Login has to be reachable without credentials, or nobody can log in.
PUBLIC_PATHS = frozenset({"/api/session"})


def configured_key() -> str | None:
    return os.environ.get(API_KEY_ENV, "").strip() or None


def _session_token(key: str) -> str:
    # Derived, not the key: a leaked cookie cannot be replayed as a bearer key,
    # and rotating the key logs every browser out.
    return hmac.new(key.encode(), b"meetingos-session-v1", hashlib.sha256).hexdigest()


def _matches(candidate: str | None, expected: str) -> bool:
    return bool(candidate) and secrets.compare_digest(candidate.encode(), expected.encode())


def _bearer(headers: dict[bytes, bytes]) -> str | None:
    value = headers.get(b"authorization", b"").decode("latin-1")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None


def _cookie(headers: dict[bytes, bytes]) -> str | None:
    raw = headers.get(b"cookie", b"").decode("latin-1")
    morsel = SimpleCookie(raw).get(SESSION_COOKIE) if raw else None
    return morsel.value if morsel else None


def is_authenticated(headers: dict[bytes, bytes], key: str) -> bool:
    return _matches(_bearer(headers), key) or _matches(_cookie(headers), _session_token(key))


def _is_protected(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return False
    return any(path == p or path.startswith(p + "/") for p in PROTECTED_PREFIXES)


class ApiKeyMiddleware:
    """Pure ASGI so streaming responses (MCP over HTTP) pass through untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        key = configured_key()
        if scope["type"] != "http" or key is None or not _is_protected(scope["path"]):
            await self.app(scope, receive, send)
            return
        if is_authenticated(dict(scope["headers"]), key):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "Authentication required"},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


def require_safe_bind(host: str) -> None:
    """Exit before serving if the bind would expose an open or weakly keyed API."""
    if host in LOOPBACK_HOSTS:
        if configured_key() is None:
            logger.warning("%s not set: API is open to anything on this machine.", API_KEY_ENV)
        return
    key = configured_key()
    if key is None or len(key) < MIN_KEY_LENGTH:
        raise SystemExit(
            f"Refusing to bind {host}: set {API_KEY_ENV} to at least {MIN_KEY_LENGTH} characters "
            "(generate one with `just gen-key`). Meeting audio and transcripts must not be served "
            "unauthenticated beyond this machine."
        )


# -- session endpoints -------------------------------------------------------

router = APIRouter(prefix="/api/session", tags=["auth"])


class LoginRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


class SessionOut(BaseModel):
    auth_required: bool
    authenticated: bool


@router.get("", response_model=SessionOut)
async def session_status(request: Request) -> SessionOut:
    key = configured_key()
    if key is None:
        return SessionOut(auth_required=False, authenticated=True)
    headers = {k.lower(): v for k, v in request.headers.raw}
    return SessionOut(auth_required=True, authenticated=is_authenticated(headers, key))


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def login(payload: LoginRequest, request: Request) -> Response:
    key = configured_key()
    if key is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if not _matches(payload.api_key, key):
        logger.warning("Failed login from %s", request.client.host if request.client else "unknown")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        SESSION_COOKIE,
        _session_token(key),
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
