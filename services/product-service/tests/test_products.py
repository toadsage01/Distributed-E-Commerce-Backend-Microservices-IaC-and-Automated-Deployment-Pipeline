"""Tests for Product Service."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = "sqlite:///./test_product.db"
    os.environ["JWT_SECRET"] = "test-secret"
    os.environ["ENV"] = "local"

    import importlib
    import app.main as app_module  # type: ignore
    importlib.reload(app_module)

    with TestClient(app_module.app) as c:
        yield c

    Path("./test_product.db").unlink(missing_ok=True)


def _auth_headers(user_id: int = 1) -> dict:
    return {"X-User-Id": str(user_id)}


def test_create_product(client):
    r = client.post("/products", json={
        "name": "Widget",
        "description": "A useful widget",
        "price": "19.99",
        "stock": 100,
    }, headers=_auth_headers())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Widget"
    assert body["price"] == 19.99
    assert body["stock"] == 100
    assert body["is_active"] is True


def test_create_requires_user_id(client):
    """Writes should be rejected without X-User-Id header."""
    r = client.post("/products", json={
        "name": "No auth widget",
        "price": "1.00",
        "stock": 1,
    })
    assert r.status_code == 422  # missing header


def test_list_products(client):
    # Create a few products first
    for i in range(3):
        client.post("/products", json={
            "name": f"Item-{i}",
            "price": "5.00",
            "stock": 10,
        }, headers=_auth_headers())

    r = client.get("/products")
    assert r.status_code == 200
    assert len(r.json()) >= 3


def test_get_product_404(client):
    assert client.get("/products/999999").status_code == 404


def test_update_product(client):
    r = client.post("/products", json={
        "name": "ToUpdate",
        "price": "10.00",
        "stock": 5,
    }, headers=_auth_headers())
    pid = r.json()["id"]

    r2 = client.patch(f"/products/{pid}", json={"price": "12.50", "stock": 3}, headers=_auth_headers())
    assert r2.status_code == 200
    assert r2.json()["price"] == 12.50
    assert r2.json()["stock"] == 3
    # Name shouldn't change since we didn't include it
    assert r2.json()["name"] == "ToUpdate"


def test_soft_delete(client):
    r = client.post("/products", json={
        "name": "ToDelete",
        "price": "1.00",
        "stock": 1,
    }, headers=_auth_headers())
    pid = r.json()["id"]

    assert client.delete(f"/products/{pid}", headers=_auth_headers()).status_code == 204
    # active_only=True by default → soft-deleted products don't show in list
    assert client.get(f"/products/{pid}").status_code == 404


def test_reserve_stock(client):
    r = client.post("/products", json={
        "name": "Reservable",
        "price": "1.00",
        "stock": 10,
    }, headers=_auth_headers())
    pid = r.json()["id"]

    r2 = client.post(f"/products/{pid}/reserve?quantity=3")
    assert r2.status_code == 200
    assert r2.json()["remaining_stock"] == 7

    # Insufficient stock
    r3 = client.post(f"/products/{pid}/reserve?quantity=100")
    assert r3.status_code == 409
