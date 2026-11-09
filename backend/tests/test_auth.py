"""API-key authentication: bearer header for agents, session cookie for the browser."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auth import API_KEY_ENV, SESSION_COOKIE, require_safe_bind

KEY = "test-key-0123456789abcdef"


@pytest.fixture
def keyed(monkeypatch, data_dir):
    monkeypatch.setenv(API_KEY_ENV, KEY)
    with TestClient(create_app()) as client:
        yield client


def test_open_when_no_key_is_configured(monkeypatch, data_dir):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/api/meetings").status_code == 200


def test_rejects_api_request_without_credentials(keyed):
    response = keyed.get("/api/meetings")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_rejects_wrong_bearer_key(keyed):
    assert keyed.get("/api/meetings", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_accepts_correct_bearer_key(keyed):
    assert keyed.get("/api/meetings", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200


def test_protects_mcp_and_openapi(keyed):
    assert keyed.post("/mcp/", json={}).status_code == 401
    assert keyed.get("/openapi.json").status_code == 401


def test_health_stays_public(keyed):
    assert keyed.get("/health").status_code == 200


def test_login_sets_cookie_that_authenticates_later_requests(keyed):
    assert keyed.get("/api/session").json() == {"auth_required": True, "authenticated": False}

    login = keyed.post("/api/session", json={"api_key": KEY})
    assert login.status_code == 204
    cookie = login.cookies.get(SESSION_COOKIE)
    assert cookie and KEY not in cookie  # cookie is derived from the key, never the key itself

    assert keyed.get("/api/meetings").status_code == 200
    assert keyed.get("/api/session").json() == {"auth_required": True, "authenticated": True}


def test_login_with_wrong_key_is_refused(keyed):
    assert keyed.post("/api/session", json={"api_key": "wrong"}).status_code == 401
    assert keyed.get("/api/meetings").status_code == 401


def test_logout_clears_session(keyed):
    keyed.post("/api/session", json={"api_key": KEY})
    assert keyed.delete("/api/session").status_code == 204
    assert keyed.get("/api/meetings").status_code == 401


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_bind_needs_no_key(monkeypatch, host):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    require_safe_bind(host)


def test_public_bind_without_key_refuses_to_start(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with pytest.raises(SystemExit):
        require_safe_bind("0.0.0.0")


def test_public_bind_with_short_key_refuses_to_start(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "short")
    with pytest.raises(SystemExit):
        require_safe_bind("0.0.0.0")


def test_public_bind_with_key_is_allowed(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, KEY)
    require_safe_bind("0.0.0.0")


def test_privacy_page_reports_real_access_state(monkeypatch, data_dir, keyed):
    notes = keyed.get("/api/privacy", headers={"Authorization": f"Bearer {KEY}"}).json()
    assert any("Access requires MEETINGOS_API_KEY" in n for n in notes["residency"]["notes"])

    monkeypatch.delenv(API_KEY_ENV)
    notes = keyed.get("/api/privacy").json()
    assert any("No API key is set" in n for n in notes["residency"]["notes"])
