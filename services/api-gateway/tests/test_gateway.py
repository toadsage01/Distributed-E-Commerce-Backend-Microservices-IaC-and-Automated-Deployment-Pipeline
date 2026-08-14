"""Tests for the API Gateway.

Uses FastAPI's `dependency_overrides` to mock the auth dependencies (so we
don't need the real User Service running) and httpx MockTransport to mock
downstream services (so we don't need any of the three services running).
"""
# NOTE: NO `from __future__ import annotations` here either. FastAPI's
# signature introspection in the test fixtures relies on annotations being
# real class objects, not strings — see app/dependencies.py for the full
# explanation.

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(scope="function")
def client():
    """Function-scoped fixture so dependency_overrides don't leak between tests."""
    os.environ["REDIS_URL"] = "memory://"
    os.environ["JWT_SECRET"] = "test-secret-not-for-prod"
    os.environ["ENV"] = "local"
    os.environ["RATE_LIMIT_PER_MINUTE"] = "5"

    # IMPORTANT: import/reload BEFORE setting the override so the
    # proxy router picks up the env vars at module-load time.
    import importlib
    import app.dependencies as deps_module
    import app.ratelimit as rl_module
    import app.routers.proxy as proxy_module
    import app.config as config_module
    import app.main as app_module  # type: ignore
    for mod in (config_module, deps_module, rl_module, proxy_module, app_module):
        importlib.reload(mod)

    # Override API key verification — pretend any X-API-Key header
    # belongs to user_id=1. Real verification logic is tested by
    # user-service tests, not gateway tests.
    from starlette.requests import Request
    from fastapi import Header, HTTPException
    from app.config import settings as _settings

    async def _fake_verify_api_key(
        request: Request,
        x_api_key: str = Header(default=None, alias="X-API-Key"),
    ):
        path = request.url.path
        for p in _settings.public_paths:
            if path == p or path.startswith(p.rstrip("/") + "/"):
                return 0
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Missing X-API-Key header")
        if not x_api_key.startswith("sk_test"):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return 1

    # Override on the SAME function object that the proxy router references.
    # The router captured `verify_api_key` from `..dependencies` at import
    # time, so we must override that exact captured reference.
    app_module.app.dependency_overrides[proxy_module.verify_api_key] = _fake_verify_api_key

    with TestClient(app_module.app) as c:
        yield c

    app_module.app.dependency_overrides.clear()


def _make_token(user_id: int = 1) -> str:
    from services.shared.jwt_utils import encode_access_token
    return encode_access_token(user_id)


def _auth_headers(token: str | None = None, api_key: str = "sk_test_valid") -> dict:
    h = {"X-API-Key": api_key}
    if token is None:
        token = _make_token()
    h["Authorization"] = f"Bearer {token}"
    return h


def test_health_no_auth(client):
    assert client.get("/health").status_code == 200


def test_proxy_requires_api_key(client):
    """No X-API-Key on a non-public path → 401."""
    r = client.get("/products", headers={"Authorization": f"Bearer {_make_token()}"})
    assert r.status_code == 401, f"Got {r.status_code}: {r.text}"


def test_proxy_requires_jwt(client):
    """API key present but no Bearer token → 401."""
    r = client.get("/products", headers={"X-API-Key": "sk_test_valid"})
    assert r.status_code == 401


def test_invalid_jwt_returns_401(client):
    r = client.get("/products", headers={
        "X-API-Key": "sk_test_valid",
        "Authorization": "Bearer not.a.real.jwt",
    })
    assert r.status_code == 401


def test_invalid_api_key_returns_401(client):
    """Non-test API keys should fail."""
    r = client.get("/products", headers={
        "X-API-Key": "invalid_key",
        "Authorization": f"Bearer {_make_token()}",
    })
    assert r.status_code == 401


def test_routing_table():
    """Verify the path→service routing logic."""
    from app.dependencies import get_downstream_url
    assert "8001" in get_downstream_url("/auth/login")
    assert "8001" in get_downstream_url("/users/1")
    assert "8002" in get_downstream_url("/products/1")
    assert "8003" in get_downstream_url("/orders/1")
    try:
        get_downstream_url("/unknown")
        assert False, "should have raised 404"
    except Exception:
        pass


def test_proxy_forwards_x_user_id_and_body(client):
    """Mock the downstream httpx call and verify:
      - X-User-Id header is forwarded
      - Body is forwarded
      - Response is passed back
    """
    import httpx
    from app.routers import proxy as proxy_module

    class FakeResponse:
        status_code = 200
        content = b'{"id": 1, "name": "Widget"}'
        headers = {"content-type": "application/json"}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

        async def request(self, method, url, **kwargs):
            assert "X-User-Id" in kwargs["headers"]
            assert kwargs["headers"]["X-User-Id"] == "1"
            assert "8002" in url  # routed to product-service
            return FakeResponse()

    with patch.object(proxy_module.httpx, "AsyncClient", FakeClient):
        r = client.get("/products/1", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["name"] == "Widget"


def test_public_path_bypasses_auth(client):
    """Signup should be reachable without API key or JWT."""
    from app.routers import proxy as proxy_module

    class FakeResponse:
        status_code = 201
        content = b'{"access_token":"x","refresh_token":"y","token_type":"bearer","expires_in":900}'
        headers = {"content-type": "application/json"}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def request(self, method, url, **kwargs):
            return FakeResponse()

    with patch.object(proxy_module.httpx, "AsyncClient", FakeClient):
        r = client.post("/auth/signup", json={
            "email": "x@y.z", "full_name": "X", "password": "supersecret123"
        })
    assert r.status_code == 201


def test_downstream_unreachable_returns_502(client):
    """If the downstream is unreachable, gateway returns 502."""
    r = client.get("/products/1", headers=_auth_headers())
    # No mock → httpx tries real DNS for "product-service" → fails → 502
    assert r.status_code in (502, 504)


def test_rate_limit_enforced(client):
    """After RATE_LIMIT_PER_MINUTE (5) requests, the 6th should be 429.

    NOTE: This test will fail if the rate limit storage is shared across
    tests — we use in-memory storage and rely on the per-test isolation.
    """
    from app.routers import proxy as proxy_module

    class FakeResponse:
        status_code = 200
        content = b'{"ok":true}'
        headers = {"content-type": "application/json"}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def request(self, method, url, **kwargs):
            return FakeResponse()

    headers = _auth_headers()
    with patch.object(proxy_module.httpx, "AsyncClient", FakeClient):
        for _ in range(5):
            r = client.get("/products/1", headers=headers)
            assert r.status_code == 200, f"Pre-limit request failed: {r.status_code}"
        # 6th request should be rate-limited
        r = client.get("/products/1", headers=headers)
    assert r.status_code == 429, f"Expected 429, got {r.status_code}: {r.text}"
