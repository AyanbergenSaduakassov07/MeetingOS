"""App-level behaviour shared by every route."""

import os

from fastapi.testclient import TestClient

from backend.app import app


def test_binary_body_on_a_json_route_is_a_422_not_a_crash(data_dir):
    """Audio posted to the JSON create route used to 500 while echoing the bytes back."""
    with TestClient(app) as client:
        response = client.post("/api/meetings", files={"file": ("a.wav", os.urandom(512), "audio/wav")})

    assert response.status_code == 422
    assert "input" not in response.json()["detail"][0]
