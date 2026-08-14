"""Unit tests for User Service auth flow.

Run with: `pytest` from the user-service directory.

Uses SQLite in-memory (no real Postgres needed) — the schema search_path
trick is bypassed by setting DATABASE_URL to a SQLite path before import.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make the service's `app/` package importable — pytest is invoked from
# the user-service directory. The repo root is needed for `services.shared`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(scope="module")
def client():
    # SQLite + a test JWT secret. Init before app import so settings pick them up.
    os.environ["DATABASE_URL"] = "sqlite:///./test_user.db"
    os.environ["JWT_SECRET"] = "test-secret-not-for-prod"
    os.environ["ENV"] = "local"

    # Import after env vars are set
    import importlib
    import app.main as app_module  # type: ignore
    importlib.reload(app_module)

    with TestClient(app_module.app) as c:
        yield c

    Path("./test_user.db").unlink(missing_ok=True)


def test_signup_and_login(client):
    r = client.post("/auth/signup", json={
        "email": "alice@example.com",
        "full_name": "Alice",
        "password": "supersecret123",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"

    r = client.post("/auth/login", json={
        "email": "alice@example.com",
        "password": "supersecret123",
    })
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_signup_duplicate_email(client):
    payload = {
        "email": "bob@example.com",
        "full_name": "Bob",
        "password": "supersecret123",
    }
    assert client.post("/auth/signup", json=payload).status_code == 201
    assert client.post("/auth/signup", json=payload).status_code == 409


def test_login_wrong_password(client):
    client.post("/auth/signup", json={
        "email": "carol@example.com",
        "full_name": "Carol",
        "password": "supersecret123",
    })
    r = client.post("/auth/login", json={
        "email": "carol@example.com",
        "password": "wrong-password",
    })
    assert r.status_code == 401


def test_refresh_token_flow(client):
    r = client.post("/auth/signup", json={
        "email": "dave@example.com",
        "full_name": "Dave",
        "password": "supersecret123",
    })
    refresh = r.json()["refresh_token"]
    r2 = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 200
    assert "access_token" in r2.json()


def test_health_endpoint(client):
    assert client.get("/health").status_code == 200
