"""Tests for Order Service.

Tests the order flow including the httpx inter-service calls. We mock the
downstream User/Product clients so the tests don't require those services
to actually be running.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = "sqlite:///./test_order.db"
    os.environ["JWT_SECRET"] = "test-secret"
    os.environ["ENV"] = "local"

    import importlib
    import app.main as app_module  # type: ignore
    importlib.reload(app_module)

    with TestClient(app_module.app) as c:
        yield c

    Path("./test_order.db").unlink(missing_ok=True)


def _auth_headers(user_id: int = 1) -> dict:
    return {"X-User-Id": str(user_id)}


def test_create_order_success(client):
    """Happy path: user exists, products in stock, order gets created."""
    # Mock the inter-service calls
    async def fake_get_user(uid, _): return {"id": uid, "email": "a@b.c"}
    async def fake_get_product(pid, _): return {"id": pid, "name": f"P{pid}", "price": "10.00"}
    async def fake_reserve(pid, qty): return {"product_id": pid, "remaining_stock": 100 - qty}

    with patch("app.routers.orders.user_client.get_user", new=AsyncMock(side_effect=fake_get_user)), \
         patch("app.routers.orders.product_client.get_product", new=AsyncMock(side_effect=fake_get_product)), \
         patch("app.routers.orders.product_client.reserve_stock", new=AsyncMock(side_effect=fake_reserve)):
        r = client.post("/orders", json={
            "items": [
                {"product_id": 1, "quantity": 2},
                {"product_id": 2, "quantity": 3},
            ],
            "notes": "please ship quickly",
        }, headers=_auth_headers())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["total_amount"] == 50.0  # (2*10) + (3*10) = 50
    assert len(body["items"]) == 2
    assert body["items"][0]["product_name"] == "P1"


def test_create_order_user_not_found(client):
    async def fake_get_user(uid, _):
        from app.clients import ServiceClientError
        raise ServiceClientError("user", 404, "not found")

    with patch("app.routers.orders.user_client.get_user", new=AsyncMock(side_effect=fake_get_user)):
        r = client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]},
                        headers=_auth_headers())
    assert r.status_code == 400
    assert "not found" in r.json()["detail"].lower()


def test_create_order_insufficient_stock(client):
    async def fake_get_user(uid, _): return {"id": uid}
    async def fake_get_product(pid, _): return {"id": pid, "name": "P", "price": "5.00"}
    async def fake_reserve(pid, qty):
        from app.clients import ServiceClientError
        raise ServiceClientError("product", 409, f"need {qty}, have 1")

    with patch("app.routers.orders.user_client.get_user", new=AsyncMock(side_effect=fake_get_user)), \
         patch("app.routers.orders.product_client.get_product", new=AsyncMock(side_effect=fake_get_product)), \
         patch("app.routers.orders.product_client.reserve_stock", new=AsyncMock(side_effect=fake_reserve)):
        r = client.post("/orders", json={"items": [{"product_id": 1, "quantity": 10}]},
                        headers=_auth_headers())
    assert r.status_code == 409


def test_list_orders_only_own(client):
    """A user should only see their own orders."""
    # Create an order as user 1
    async def fake_get_user(uid, _): return {"id": uid}
    async def fake_get_product(pid, _): return {"id": pid, "name": "P", "price": "1.00"}
    async def fake_reserve(pid, qty): return {"remaining_stock": 99}

    with patch("app.routers.orders.user_client.get_user", new=AsyncMock(side_effect=fake_get_user)), \
         patch("app.routers.orders.product_client.get_product", new=AsyncMock(side_effect=fake_get_product)), \
         patch("app.routers.orders.product_client.reserve_stock", new=AsyncMock(side_effect=fake_reserve)):
        r1 = client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]},
                         headers=_auth_headers(1))

    # User 2 should NOT see user 1's order
    r2 = client.get("/orders", headers=_auth_headers(2))
    assert r2.status_code == 200
    assert len(r2.json()) == 0  # user 2 has no orders


def test_get_order_404_when_not_owner(client):
    """Don't leak existence of other users' orders — return 404 not 403."""
    async def fake_get_user(uid, _): return {"id": uid}
    async def fake_get_product(pid, _): return {"id": pid, "name": "P", "price": "1.00"}
    async def fake_reserve(pid, qty): return {"remaining_stock": 99}

    with patch("app.routers.orders.user_client.get_user", new=AsyncMock(side_effect=fake_get_user)), \
         patch("app.routers.orders.product_client.get_product", new=AsyncMock(side_effect=fake_get_product)), \
         patch("app.routers.orders.product_client.reserve_stock", new=AsyncMock(side_effect=fake_reserve)):
        # Create as user 1
        created = client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]},
                              headers=_auth_headers(1)).json()
        order_id = created["id"]
        # Try to fetch as user 2 → 404, not 403
        r = client.get(f"/orders/{order_id}", headers=_auth_headers(2))
    assert r.status_code == 404


def test_status_transition_validation(client):
    """Test that invalid status transitions are rejected."""
    async def fake_get_user(uid, _): return {"id": uid}
    async def fake_get_product(pid, _): return {"id": pid, "name": "P", "price": "1.00"}
    async def fake_reserve(pid, qty): return {"remaining_stock": 99}

    with patch("app.routers.orders.user_client.get_user", new=AsyncMock(side_effect=fake_get_user)), \
         patch("app.routers.orders.product_client.get_product", new=AsyncMock(side_effect=fake_get_product)), \
         patch("app.routers.orders.product_client.reserve_stock", new=AsyncMock(side_effect=fake_reserve)):
        # Create as confirmed
        created = client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]},
                              headers=_auth_headers(1)).json()
        order_id = created["id"]

        # Invalid: confirmed → fulfilled (skipping paid)
        r = client.patch(f"/orders/{order_id}/status", json={"status": "fulfilled"},
                         headers=_auth_headers(1))
        assert r.status_code == 400

        # Valid: confirmed → paid
        r2 = client.patch(f"/orders/{order_id}/status", json={"status": "paid"},
                          headers=_auth_headers(1))
        assert r2.status_code == 200
        assert r2.json()["status"] == "paid"


def test_health(client):
    assert client.get("/health").status_code == 200
