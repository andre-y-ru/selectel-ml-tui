"""Unit-тесты API-клиентов с моками httpx.MockTransport."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from selectel_ml_tui.api.billing import (
    BillingApiError,
    BillingClient,
    normalize_dt,
)
from selectel_ml_tui.api.client import SelectelApiError
from selectel_ml_tui.api.gateway import GatewayApiError, GatewayClient


class NoopSleep:
    """Пауза-заглушка для ретраев (не ждём в тестах)."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _billing_client(
    handler: Any, max_retries: int = 2, sleep: NoopSleep | None = None
) -> BillingClient:
    return BillingClient(
        api_base_url="https://api.selectel.ru",
        static_token="static-token",
        max_retries=max_retries,
        transport=_transport(handler),
        sleep=sleep or NoopSleep(),
    )


def _ok_consumption() -> dict[str, Any]:
    return {
        "status": "success",
        "data": [
            {
                "account_id": "239633",
                "period": "2026-08-01",
                "provider_key": "aig",
                "metric": {
                    "id": "air_tokens_cost",
                    "name": "Стоимость токенов",
                    "unit": "nanorub",
                    "quantity": "85483000000",
                },
                "value": 854.83,
                "project": "7bf2d2a328494e25b13d05a1926ca75a",
            }
        ],
    }


async def test_billing_normalize_dt() -> None:
    assert normalize_dt("2026-08-01") == "2026-08-01T00:00:00.000"
    assert normalize_dt("2026-08-01T10:30:00") == "2026-08-01T10:30:00"
    assert normalize_dt("2026-08-01T00:00:00.000") == "2026-08-01T00:00:00.000"


async def test_billing_gets_normalized_dates() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_ok_consumption())

    client = _billing_client(handler)
    await client.get_consumption("2026-08-01", "2026-08-19")
    assert seen["start"] == "2026-08-01T00:00:00.000"
    assert seen["end"] == "2026-08-19T00:00:00.000"
    await client.aclose()


async def test_billing_get_consumption() -> None:
    client = _billing_client(
        lambda request: httpx.Response(200, json=_ok_consumption())
    )
    items = await client.get_consumption("2026-08-01", "2026-08-19")
    assert len(items) == 1
    assert items[0].value == Decimal("854.83")
    assert items[0].metric is not None
    assert items[0].metric.id == "air_tokens_cost"
    assert items[0].project_id == "7bf2d2a328494e25b13d05a1926ca75a"
    await client.aclose()


async def test_billing_get_summary_sums_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "provider_keys=aig" in request.url.query.decode()
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {"value": "100.25"},
                    {"value": 42.5},
                    {"value": 0},
                ],
            },
        )

    client = _billing_client(handler)
    total = await client.get_summary("2026-08-01", "2026-08-19")
    assert total == Decimal("142.75")
    await client.aclose()


async def test_billing_5xx_retries_then_success() -> None:
    sleep = NoopSleep()
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(500, text="internal error")
        return httpx.Response(200, json=_ok_consumption())

    client = _billing_client(handler, sleep=sleep)
    items = await client.get_consumption("2026-08-01", "2026-08-19")
    assert attempts["count"] == 2
    assert len(items) == 1
    assert sleep.calls == [0.5]
    await client.aclose()


async def test_billing_429_retries_then_raises() -> None:
    sleep = NoopSleep()
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(429, text="rate limit")

    client = _billing_client(handler, max_retries=2, sleep=sleep)
    with pytest.raises(SelectelApiError) as exc_info:
        await client.get_consumption("2026-08-01", "2026-08-19")
    assert exc_info.value.status_code == 429
    assert attempts["count"] == 3
    assert sleep.calls == [0.5, 1.0]
    await client.aclose()


async def test_billing_4xx_no_retry() -> None:
    sleep = NoopSleep()
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(400, text="bad request")

    client = _billing_client(handler, sleep=sleep)
    with pytest.raises(BillingApiError) as exc_info:
        await client.get_consumption("2026-08-01", "2026-08-19")
    assert exc_info.value.status_code == 400
    assert "HTTP 400" in str(exc_info.value)
    assert attempts["count"] == 1
    assert sleep.calls == []
    await client.aclose()


async def test_billing_network_error_retries() -> None:
    sleep = NoopSleep()
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json=_ok_consumption())

    client = _billing_client(handler, sleep=sleep)
    items = await client.get_consumption("2026-08-01", "2026-08-19")
    assert attempts["count"] == 2
    assert len(items) == 1
    await client.aclose()


async def test_billing_timeout_retries_then_raises() -> None:
    sleep = NoopSleep()
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ReadTimeout("timed out")

    client = _billing_client(handler, max_retries=2, sleep=sleep)
    with pytest.raises(SelectelApiError) as exc_info:
        await client.get_consumption("2026-08-01", "2026-08-19")
    assert exc_info.value.status_code is None
    assert "Ошибка сети" in str(exc_info.value)
    assert attempts["count"] == 3
    assert sleep.calls == [0.5, 1.0]
    await client.aclose()


async def test_billing_non_success_status_raises() -> None:
    client = _billing_client(
        lambda request: httpx.Response(200, json={"status": "error", "data": []})
    )
    with pytest.raises(BillingApiError):
        await client.get_consumption("2026-08-01", "2026-08-19")
    await client.aclose()


class FakeTokenProvider:
    """Токен-провайдер для GatewayClient в тестах."""

    def __init__(self, tokens: list[str] | None = None) -> None:
        self._tokens = tokens or ["token-1"]
        self._index = 0
        self.calls = 0

    async def get_token(self) -> str:
        self.calls += 1
        token = self._tokens[min(self._index, len(self._tokens) - 1)]
        self._index += 1
        return token

    def invalidate(self) -> None:
        pass


async def test_gateway_list_gateways() -> None:
    provider = FakeTokenProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Auth-Token"] == "token-1"
        assert request.headers["X-Project-Id"] == "proj-1"
        assert request.headers["X-Roles"] == "reader"
        return httpx.Response(200, json={"data": [{"id": "gw-1", "name": "Router"}]})

    client = GatewayClient(
        api_base_url="https://api.selectel.ru",
        token_provider=provider,
        project_id="proj-1",
        domain_id="239633",
        transport=_transport(handler),
    )
    gateways = await client.list_gateways()
    assert gateways == [{"id": "gw-1", "name": "Router"}]
    assert provider.calls == 1
    await client.aclose()


async def test_gateway_401_refreshes_token() -> None:
    provider = FakeTokenProvider(tokens=["token-old", "token-new"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["X-Auth-Token"] == "token-old":
            return httpx.Response(401, text="unauthorized")
        return httpx.Response(200, json={"data": [{"id": "gw-2"}]})

    client = GatewayClient(
        api_base_url="https://api.selectel.ru",
        token_provider=provider,
        project_id="proj-1",
        domain_id="239633",
        transport=_transport(handler),
    )
    gateways = await client.list_gateways()
    assert gateways == [{"id": "gw-2"}]
    assert provider.calls == 2
    await client.aclose()


async def test_gateway_401_without_refresh_raises() -> None:
    provider = FakeTokenProvider(tokens=["token-only"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = GatewayClient(
        api_base_url="https://api.selectel.ru",
        token_provider=provider,
        project_id="proj-1",
        domain_id="239633",
        max_retries=0,
        transport=_transport(handler),
    )
    with pytest.raises(GatewayApiError) as exc_info:
        await client.list_gateways()
    assert exc_info.value.status_code == 401
    await client.aclose()
