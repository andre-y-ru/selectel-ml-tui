"""Unit-тесты сервисного слоя."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import httpx

from selectel_ml_tui.config import Credentials, Settings
from selectel_ml_tui.models import Consumption, Metrics
from selectel_ml_tui.services import (
    DashboardData,
    DataService,
    parse_keys,
    parse_metrics,
    parse_models,
    parse_overview,
    parse_tokens,
)
from selectel_ml_tui.storage import Storage


def _summary_response(value: str = "85483") -> dict[str, Any]:
    return {
        "status": "success",
        "data": [{"value": value}],
    }


async def test_parse_tokens() -> None:
    tokens = parse_tokens(
        {"input_tokens": 10, "output_tokens": 20, "cache_read": 30, "cache_write": 40}
    )
    assert tokens.input_tokens == 10
    assert tokens.output_tokens == 20
    assert tokens.cache_read_tokens == 30
    assert tokens.cache_write_tokens == 40


async def test_parse_tokens_missing_fields_defaults() -> None:
    tokens = parse_tokens({})
    assert tokens.input_tokens == 0
    assert tokens.output_tokens == 0
    assert tokens.cache_read_tokens == 0
    assert tokens.cache_write_tokens == 0


async def test_parse_metrics() -> None:
    metrics = parse_metrics(
        {
            "global": {
                "requests": 1035,
                "success_rate_pct": 100,
                "avg_ttft_seconds": 3.67,
                "avg_latency_seconds": 11.85,
                "tokens": {
                    "input": 228542299,
                    "output": 747268,
                    "cached_input": 222355840,
                    "cache_write": 0,
                },
            }
        }
    )
    assert metrics is not None
    assert metrics.availability_pct == 100
    assert metrics.avg_ttft_ms == 3670
    assert metrics.avg_latency_ms == 11850
    assert metrics.requests == 1035
    assert metrics.input_tokens == 228542299
    assert metrics.output_tokens == 747268
    assert metrics.cache_read_tokens == 222355840
    assert metrics.cache_write_tokens == 0


async def test_parse_metrics_empty() -> None:
    assert parse_metrics({}) is None


async def test_parse_models() -> None:
    models = parse_models(
        {
            "by_model": [
                {
                    "model": "deepseek/deepseek-v4-flash",
                    "requests": 69,
                    "success_rate_pct": 100,
                    "avg_ttft_seconds": 3.35,
                },
                {
                    "model": "deepseek/deepseek-v4-pro",
                    "requests": 966,
                    "success_rate_pct": 100,
                    "avg_ttft_seconds": 3.69,
                },
            ]
        }
    )
    assert len(models) == 2
    assert models[0].model_name == "deepseek/deepseek-v4-flash"
    assert models[0].requests == 69
    assert models[0].availability_pct == 100
    assert models[0].avg_ttft_ms == 3350
    assert models[1].model_id == "deepseek/deepseek-v4-pro"


async def test_parse_overview() -> None:
    import datetime as _dt

    consumption = parse_overview(
        {
            "totals": {
                "requests": 1034,
                "cost_rub_nano": "1075311673934",
                "tokens": {
                    "input": 228314832,
                    "output": 746702,
                    "cached_input": 222128640,
                    "cache_write": 0,
                },
                "tokens_total": {"total": 451607518},
            }
        },
        _dt.datetime(2026, 8, 19, tzinfo=_dt.timezone.utc),
    )
    assert consumption.amount_rub == Decimal("1075.311673934")
    assert consumption.requests == 1034
    assert consumption.tokens_total == 451607518
    assert consumption.input_tokens == 228314832
    assert consumption.cache_read_tokens == 222128640


async def test_parse_keys() -> None:
    keys = parse_keys(
        [
            {
                "name": "Mei",
                "prefix": "sk-sl-v1-9dd61ec",
                "is_active": True,
                "budget": {
                    "spend_limit_rub_nano": "1300000000000",
                    "current_usage": {"spend_rub_nano": "1082949415164"},
                },
            },
            {
                "name": "Ollama Mac Air",
                "prefix": "sk-sl-v1-65fdb2e",
                "is_active": False,
                "budget": {"spend_limit_rub_nano": "100000000000"},
            },
        ]
    )
    assert len(keys) == 2
    assert keys[0].name == "Mei"
    assert keys[0].is_active is True
    assert keys[0].spend_limit_rub == Decimal("1300")
    assert keys[0].spend_rub == Decimal("1082.949415164")
    assert keys[0].remaining_rub == Decimal("217.050584836")
    assert keys[1].is_active is False
    assert keys[1].spend_limit_rub == Decimal("100")


async def test_refresh_billing_only(tmp_path) -> None:
    """Только billing (без IAM): стоимость за месяц есть, gateway отмечен."""
    settings = Settings()
    creds = Credentials(static_token="static-token")
    storage = Storage(tmp_path / "cache.db")
    seen_end: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "summary_stats" in request.url.path:
            seen_end["summary"] = request.url.params.get("end", "")
            return httpx.Response(200, json=_summary_response())
        if "consumption" in request.url.path:
            seen_end["consumption"] = request.url.params.get("end", "")
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": [{"period": "2026-08-19T00:00:00", "value": "7133"}],
                },
            )
        return httpx.Response(200, json=_summary_response())

    service = DataService(
        settings, creds, storage, transport=httpx.MockTransport(handler)
    )
    data = await service.refresh()
    assert data.month_consumption is not None
    assert data.month_consumption.amount_rub == Decimal("854.83")
    # Пункт A: end должен содержать время (не усечённую дату) и быть naive
    # (без смещения часового пояса — иначе API отвечает 422).
    assert "T" in seen_end["summary"]
    assert "T" in seen_end["consumption"]
    assert "+" not in seen_end["summary"]
    # Пункт B: дневная стоимость сегодня выделена отдельно.
    assert data.today_amount_rub == Decimal("71.33")
    assert not data.offline
    assert data.error is not None
    assert "сервисный пользователь" in data.error
    assert storage.get_latest_consumption() is not None
    history = storage.get_history(days=30)
    assert len(history) == 1
    # История хранит дневную стоимость (не месячную сумму).
    assert history[0].amount_rub == Decimal("71.33")


async def test_refresh_billing_failure_uses_cache(tmp_path) -> None:
    """Сбой billing + кэш → офлайн-данные из Storage."""
    settings = Settings()
    creds = Credentials(static_token="static-token")
    storage = Storage(tmp_path / "cache.db")
    storage.save_snapshot(
        consumption=Consumption(
            period=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
            amount_rub=Decimal("10.00"),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    service = DataService(
        settings, creds, storage, transport=httpx.MockTransport(handler)
    )
    data = await service.refresh()
    assert data.offline is True
    assert data.source == "cache"
    assert data.month_consumption is not None
    assert data.month_consumption.amount_rub == Decimal("10.00")
    assert data.error is not None


async def test_refresh_with_gateway(tmp_path) -> None:
    """Billing + gateway (IAM): заполнены метрики, модели, ключи, бюджет."""
    settings = Settings()
    creds = Credentials(
        static_token="static-token",
        service_user="svc",
        password="pwd",
        project_id="proj-1",
        domain_id="239633",
    )
    storage = Storage(tmp_path / "cache.db")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/tokens"):
            return httpx.Response(
                201,
                headers={"X-Subject-Token": "iam-token"},
                json={"token": {"expires_at": "2030-01-01T00:00:00Z"}},
            )
        if path.endswith("/gateways"):
            return httpx.Response(200, json={"data": [{"id": "gw-1"}]})
        if path.endswith("/overview"):
            return httpx.Response(
                200,
                json={
                    "totals": {
                        "requests": 1034,
                        "cost_rub_nano": "1075311673934",
                        "tokens": {"input": 100, "output": 200},
                        "tokens_total": {"total": 300},
                    },
                    "budget": {
                        "spend_limit_rub_nano": "2000000000000",
                        "spend_rub_nano": "1077874156239",
                    },
                },
            )
        if path.endswith("/metrics"):
            return httpx.Response(
                200,
                json={
                    "global": {"success_rate_pct": 99.5, "avg_ttft_seconds": 0.3},
                    "by_model": [
                        {"model": "deepseek/deepseek-v4-flash", "requests": 69}
                    ],
                },
            )
        if path.endswith("/keys"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "name": "Mei",
                            "prefix": "sk-sl-v1-9dd61ec",
                            "is_active": True,
                            "budget": {
                                "spend_limit_rub_nano": "1300000000000",
                                "current_usage": {"spend_rub_nano": "1082949415164"},
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json=_summary_response())

    service = DataService(
        settings, creds, storage, transport=httpx.MockTransport(handler)
    )
    data = await service.refresh()
    assert data.month_consumption is not None
    assert data.month_consumption.amount_rub == Decimal("1075.311673934")
    assert data.metrics is not None
    assert data.metrics.availability_pct == 99.5
    assert data.metrics.avg_ttft_ms == 300
    assert len(data.models) == 1
    assert data.models[0].model_name == "deepseek/deepseek-v4-flash"
    assert len(data.keys) == 1
    assert data.keys[0].name == "Mei"
    assert data.budget is not None
    assert data.budget.spend_limit_rub == Decimal("2000")


async def test_dashboard_data_has_data() -> None:
    empty = DashboardData()
    assert not empty.has_data
    full = DashboardData(metrics=Metrics())
    assert full.has_data
