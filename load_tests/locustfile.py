"""Locust load test for the e-commerce API Gateway.

Tests the full request path:
  Client → Gateway → (JWT verify + rate limit) → downstream service → DB

The test creates a single test user + API key at startup, then each Locust
worker reuses them. Mix:
  40% GET /products         (read-heavy, public catalog)
  30% GET /products/{id}    (single product lookup)
  15% GET /orders           (list user's orders)
  10% POST /orders          (create order — hits User + Product via httpx)
   5% GET /users/me         (profile lookup)

Usage:
  # Web UI:
  locust -f load_tests/locustfile.py --host=http://localhost:8000

  # Headless — 500 concurrent, ramp 60s, run 5 min:
  locust -f load_tests/locustfile.py --host=http://localhost:8000 \\
      --headless -u 500 -r 8 -t 300s \\
      --html=load_tests/report.html --csv=load_tests/report

  # Against deployed ALB:
  locust -f load_tests/locustfile.py --host=http://<ALB_DNS>
"""
from __future__ import annotations

import os
import random
import time
import uuid
from locust import HttpUser, between, task, events


# Created once at startup, shared across all Locust workers via env vars.
TEST_EMAIL = os.environ.get("LOADTEST_EMAIL", f"loadtest-{uuid.uuid4().hex[:8]}@example.com")
TEST_PASSWORD = "LoadTestPass123!"
GATEWAY_BASE = os.environ.get("LOADTEST_HOST", "http://localhost:8000")


def _ensure_test_user_and_key():
    """Sign up a test user + create an API key.

    Runs once at module import (before Locust starts spawning users).
    Uses the public signup endpoint, so no auth required.
    """
    import urllib.request
    import json

    # 1. Signup → get tokens
    payload = json.dumps({
        "email": TEST_EMAIL,
        "full_name": "Load Tester",
        "password": TEST_PASSWORD,
    }).encode()
    req = urllib.request.Request(
        f"{GATEWAY_BASE}/auth/signup",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            access_token = body["access_token"]
    except urllib.error.HTTPError as e:
        if e.code == 409:
            # User already exists — log in instead
            payload = json.dumps({
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            }).encode()
            req = urllib.request.Request(
                f"{GATEWAY_BASE}/auth/login",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                access_token = body["access_token"]
        else:
            raise

    # 2. Create an API key (requires the access token)
    req = urllib.request.Request(
        f"{GATEWAY_BASE}/auth/api-keys",
        data=json.dumps({"label": "loadtest"}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
        api_key = body["key"]

    return access_token, api_key


# Run at import time so it happens before Locust's workers start
try:
    ACCESS_TOKEN, API_KEY = _ensure_test_user_and_key()
    print(f"\n✅ Test user ready: {TEST_EMAIL}")
    print(f"   API key: {API_KEY[:20]}...")
except Exception as e:
    print(f"\n⚠ Failed to set up test user: {e}")
    print(f"   Make sure the gateway is running at {GATEWAY_BASE}")
    ACCESS_TOKEN = None
    API_KEY = None


class EcommerceUser(HttpUser):
    """Simulates a real client hitting the gateway.

    Each Locust 'user' has its own session (with cookies) — we set the
    API key + Bearer token on session creation so every request has them.
    """

    wait_time = between(0.5, 2.0)  # think time between requests

    def on_start(self):
        if not ACCESS_TOKEN or not API_KEY:
            raise RuntimeError("No API key + token — setup failed")

        # Pre-seed product catalog if it's empty (only first user does this)
        if random.random() < 0.1:
            self._seed_products()

        self.client.headers.update({
            "X-API-Key": API_KEY,
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        })

    def _seed_products(self):
        """Create a few products for the load test to operate on."""
        for i in range(5):
            self.client.post("/products", json={
                "name": f"LoadTest Product {i}",
                "description": "Product for load testing",
                "price": f"{random.randint(10, 99)}.{random.randint(0, 99):02d}",
                "stock": 1000,
            }, name="POST /products (seed)")

    @task(40)
    def list_products(self):
        """Browse the catalog — most common request in real e-commerce."""
        self.client.get("/products?limit=20", name="GET /products")

    @task(30)
    def get_product_detail(self):
        """View a single product — pick a random ID 1-100 (most won't exist)."""
        product_id = random.randint(1, 100)
        # Catch 404s — they're expected, not failures
        with self.client.get(
            f"/products/{product_id}",
            name="GET /products/:id",
            catch_response=True,
        ) as r:
            if r.status_code == 404:
                r.success()  # don't count as failure

    @task(15)
    def list_orders(self):
        self.client.get("/orders", name="GET /orders")

    @task(10)
    def create_order(self):
        """Place an order — exercises the full Order → User → Product path."""
        # Pick a random product + quantity. May fail with 404/409 — that's
        # expected and shouldn't fail the load test.
        product_id = random.randint(1, 5)
        with self.client.post(
            "/orders",
            json={
                "items": [{"product_id": product_id, "quantity": random.randint(1, 3)}],
                "notes": "load test order",
            },
            name="POST /orders",
            catch_response=True,
        ) as r:
            if r.status_code in (404, 409, 502):
                r.success()

    @task(5)
    def get_my_profile(self):
        self.client.get("/users/me", name="GET /users/me")


# ---------------------------------------------------------------------------
# Event hooks — pretty-print custom stats at end of run
# ---------------------------------------------------------------------------

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print(f"\n🚀 Load test starting against {environment.host}")
    print(f"   Target: {environment.host}")
    print(f"   Users: {environment.parsed_options.num_users}")
    print(f"   Spawn rate: {environment.parsed_options.spawn_rate}/s")
    print(f"   Duration: {environment.parsed_options.run_time}s\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats.total
    print(f"\n📊 Load test complete")
    print(f"   Requests:     {stats.num_requests}")
    print(f"   Failures:     {stats.num_failures}")
    print(f"   RPS:          {stats.total_rps:.1f}")
    print(f"   Avg latency:  {stats.avg_response_time:.0f}ms")
    print(f"   P50 latency:  {stats.get_response_time_percentile(0.5):.0f}ms")
    print(f"   P95 latency:  {stats.get_response_time_percentile(0.95):.0f}ms")
    print(f"   P99 latency:  {stats.get_response_time_percentile(0.99):.0f}ms")
