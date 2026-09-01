"""Tests for CORS origin allowlist and credential behavior in FileMind backend."""

import pytest
from fastapi.testclient import TestClient
from app.main import app, ALLOWED_ORIGINS

client = TestClient(app)

@pytest.mark.parametrize("origin", [
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
])
def test_allowed_origins_receive_permissive_cors_headers(origin):
    headers = {"Origin": origin}
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"

@pytest.mark.parametrize("origin", [
    "http://malicious-site.com",
    "https://evil.org",
    "http://localhost:8000",
    "http://127.0.0.1:8080",
    "https://attacker.io",
])
def test_unauthorized_origins_do_not_receive_cors_headers(origin):
    headers = {"Origin": origin}
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    # Unauthorized origins must not receive access-control-allow-origin
    assert response.headers.get("access-control-allow-origin") is None

def test_preflight_options_for_allowed_origin():
    headers = {
        "Origin": "http://localhost:1420",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    response = client.options("/search", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:1420"
    assert response.headers.get("access-control-allow-credentials") == "true"

def test_preflight_options_for_unauthorized_origin():
    headers = {
        "Origin": "http://unauthorized-evil.com",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    response = client.options("/search", headers=headers)
    # CORSMiddleware responds to disallowed preflights without allow-origin headers
    assert response.headers.get("access-control-allow-origin") is None
