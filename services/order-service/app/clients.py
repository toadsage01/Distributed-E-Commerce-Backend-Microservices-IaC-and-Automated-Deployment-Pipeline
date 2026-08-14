"""HTTP clients for calling User Service and Product Service.

This is the part that makes the system genuinely "microservices" — Order
Service calls the other services over HTTP (with retries + timeouts)
instead of reaching into their DB schemas directly.

Design notes:
  - Async httpx client (FastAPI is async-native; using sync requests would
    block the event loop).
  - Short timeouts (3s) — under degraded conditions we'd rather fail fast
    than hang the order flow.
  - Bounded retries (2 attempts) with exponential backoff. Beyond 2 retries
    you're usually just piling on load to a struggling service.
  - The X-User-Id header is propagated from the gateway so the downstream
    services can attribute the call to a user.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("order-service.clients")


class ServiceClientError(Exception):
    """Raised when a downstream service call fails after all retries."""

    def __init__(self, service: str, status_code: int | None, detail: str) -> None:
        self.service = service
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{service}] HTTP {status_code}: {detail}")


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make an HTTP request with retries on transient failures.

    Retries on:
      - httpx.ConnectError / http.ReadTimeout (network blips)
      - 5xx responses (server errors)
    Does NOT retry on 4xx (client errors — won't fix themselves).
    """
    last_exc: Exception | None = None
    last_status: int | None = None
    last_detail: str = ""

    for attempt in range(settings.http_retry_max + 1):
        try:
            resp = await client.request(
                method, url, headers=headers, json=json, params=params,
                timeout=settings.http_timeout_seconds,
            )
            if resp.status_code < 500:
                if resp.status_code >= 400:
                    try:
                        last_detail = resp.json().get("detail", resp.text)
                    except Exception:
                        last_detail = resp.text
                    last_status = resp.status_code
                    raise ServiceClientError(
                        service=url, status_code=resp.status_code, detail=last_detail
                    )
                # Success
                try:
                    return resp.json()
                except Exception:
                    return {"raw": resp.text}
            # 5xx → retryable
            last_status = resp.status_code
            try:
                last_detail = resp.json().get("detail", resp.text)
            except Exception:
                last_detail = resp.text
            log.warning("Retryable %s from %s (attempt %d): %s",
                        resp.status_code, url, attempt + 1, last_detail)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
            last_exc = exc
            log.warning("Network error to %s (attempt %d): %s", url, attempt + 1, exc)

        if attempt < settings.http_retry_max:
            # Exponential backoff: 0.2s, 0.4s, ...
            await asyncio.sleep(settings.http_retry_backoff_seconds * (2 ** attempt))

    raise ServiceClientError(
        service=url,
        status_code=last_status,
        detail=last_detail or f"Exhausted retries: {last_exc}",
    )


class UserClient:
    """Calls User Service over HTTP."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.user_service_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url)
        return self._client

    async def get_user(self, user_id: int, x_user_id: int) -> dict[str, Any]:
        """Verify a user exists (used during order creation).

        Returns the user dict, raises ServiceClientError if not found.
        """
        client = await self._get_client()
        return await _request_with_retry(
            client, "GET", f"/users/{user_id}",
            headers={"X-User-Id": str(x_user_id)},
        )

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class ProductClient:
    """Calls Product Service over HTTP."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.product_service_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url)
        return self._client

    async def get_product(self, product_id: int, x_user_id: int) -> dict[str, Any]:
        client = await self._get_client()
        return await _request_with_retry(
            client, "GET", f"/products/{product_id}",
            headers={"X-User-Id": str(x_user_id)},
        )

    async def reserve_stock(self, product_id: int, quantity: int) -> dict[str, Any]:
        """Reserve stock atomically — decrements Product.stock if available."""
        client = await self._get_client()
        return await _request_with_retry(
            client, "POST", f"/products/{product_id}/reserve",
            params={"quantity": quantity},
        )

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Module-level singletons (reuse across requests — httpx AsyncClient is
# designed for this, with connection pooling built in).
user_client = UserClient()
product_client = ProductClient()
