"""Сервисный слой: агрегация данных для TUI.

Объединяет Billing API (стоимость за месяц) и Gateway API (метрики, токены,
модели). При недоступности API подставляет последние данные из SQLite-кэша
(офлайн-режим).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from selectel_ml_tui.api.billing import BillingClient
from selectel_ml_tui.api.client import SelectelApiError
from selectel_ml_tui.api.gateway import GatewayClient
from selectel_ml_tui.auth import IamClient, IamTokenManager
from selectel_ml_tui.config import Credentials, Settings
from selectel_ml_tui.models import (
    ApiKeyUsage,
    BudgetInfo,
    Consumption,
    HistoryPoint,
    Metrics,
    ModelMetrics,
    TokenUsage,
)
from selectel_ml_tui.storage import Storage

_NANO = Decimal("1000000000")


def _nano_to_rub(value: Any) -> Decimal:
    """Нанорубли (строка/число) -> рубли."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value)) / _NANO
    except (ValueError, ArithmeticError, TypeError):
        return Decimal("0")


def _pick(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _dict(value: Any) -> dict[str, Any]:
    """Привести произвольное значение к dict (иначе пустой dict)."""
    return value if isinstance(value, dict) else {}


def parse_tokens(data: dict[str, Any]) -> TokenUsage:
    """Извлечь токены из объекта ответа (устойчиво к разным ключам).

    Поддерживает как вложенную структуру Gateway (``tokens.input`` и т.п.),
    так и плоские ключи (``input_tokens`` и т.п.).
    """
    nested = _dict(data.get("tokens"))
    return TokenUsage(
        input_tokens=int(
            _pick(data, ("input_tokens", "input", "inputTokens", "tokens_in"))
            or _pick(nested, ("input", "input_tokens"))
            or 0
        ),
        output_tokens=int(
            _pick(data, ("output_tokens", "output", "outputTokens", "tokens_out"))
            or _pick(nested, ("output", "output_tokens"))
            or 0
        ),
        cache_read_tokens=int(
            _pick(data, ("cache_read_tokens", "cacheReadTokens", "cache_read"))
            or _pick(nested, ("cached_input", "cache_read_tokens", "cache_read"))
            or 0
        ),
        cache_write_tokens=int(
            _pick(data, ("cache_write_tokens", "cacheWriteTokens", "cache_write"))
            or _pick(nested, ("cache_write", "cache_write_tokens"))
            or 0
        ),
    )


def parse_overview(raw: dict[str, Any], period: dt.datetime) -> Consumption:
    """Разобрать /gateways/{id}/overview в Consumption.

    Сумма из ``totals.cost_rub_nano`` (нанорубли), токены из ``totals.tokens``,
    общее число токенов из ``totals.tokens_total.total``.
    """
    totals = _dict(raw.get("totals"))
    tokens_total = _dict(totals.get("tokens_total"))
    tokens = parse_tokens(totals)
    return Consumption(
        period=period,
        amount_rub=_nano_to_rub(totals.get("cost_rub_nano")),
        requests=int(totals.get("requests") or 0),
        tokens_total=int(tokens_total.get("total") or 0),
        **tokens.model_dump(),
    )


def parse_metrics(raw: dict[str, Any]) -> Metrics | None:
    """Разобрать /gateways/{id}/metrics в Metrics.

    Доступность из ``global.success_rate_pct``, TTFT/latency из секунд
    ``global.avg_ttft_seconds``/``avg_latency_seconds`` (в мс), токены из
    ``global.tokens``.
    """
    if not raw:
        return None
    global_ = _dict(raw.get("global")) or raw
    tokens = parse_tokens(global_)
    return Metrics(
        availability_pct=float(global_.get("success_rate_pct") or 100.0),
        avg_ttft_ms=float(global_.get("avg_ttft_seconds") or 0.0) * 1000,
        avg_latency_ms=float(global_.get("avg_latency_seconds") or 0.0) * 1000,
        requests=int(global_.get("requests") or 0),
        input_tokens=tokens.input_tokens,
        output_tokens=tokens.output_tokens,
        cache_read_tokens=tokens.cache_read_tokens,
        cache_write_tokens=tokens.cache_write_tokens,
    )


def parse_models(raw_metrics: dict[str, Any]) -> list[ModelMetrics]:
    """Построить метрики по моделям из ``by_model`` в /metrics.

    По модели API отдаёт: ``model``, ``requests``, ``success_rate_pct``,
    ``avg_ttft_seconds`` (токенов по модели нет).
    """
    by_model = raw_metrics.get("by_model", [])
    if not isinstance(by_model, list):
        by_model = []
    models: list[ModelMetrics] = []
    for item in by_model:
        model_id = str(item.get("model") or "") if isinstance(item, dict) else ""
        models.append(
            ModelMetrics(
                model_id=model_id,
                model_name=model_id,
                availability_pct=float(item.get("success_rate_pct") or 100.0)
                if isinstance(item, dict)
                else 100.0,
                avg_ttft_ms=(
                    float(item.get("avg_ttft_seconds") or 0.0) * 1000
                    if isinstance(item, dict)
                    else 0.0
                ),
                avg_latency_ms=(
                    float(item.get("avg_latency_seconds") or 0.0) * 1000
                    if isinstance(item, dict)
                    else 0.0
                ),
                requests=(
                    int(item.get("requests") or 0) if isinstance(item, dict) else 0
                ),
            )
        )
    return models


def parse_keys(raw_keys: list[dict[str, Any]]) -> list[ApiKeyUsage]:
    """Разобрать /keys в список лимитов по API-ключам."""
    keys: list[ApiKeyUsage] = []
    for item in raw_keys:
        budget = _dict(item.get("budget"))
        limit = _nano_to_rub(budget.get("spend_limit_rub_nano"))
        usage = _dict(budget.get("current_usage")) or _dict(item.get("usage"))
        spend = _nano_to_rub(usage.get("spend_rub_nano"))
        keys.append(
            ApiKeyUsage(
                name=str(item.get("name") or ""),
                prefix=str(item.get("prefix") or ""),
                is_active=bool(item.get("is_active", True)),
                spend_limit_rub=limit,
                spend_rub=spend,
                remaining_rub=max(limit - spend, Decimal("0")),
            )
        )
    return keys


def parse_budget(raw: dict[str, Any]) -> BudgetInfo | None:
    """Бюджет роутера из ``budget`` в /overview."""
    budget = _dict(raw.get("budget"))
    if not budget:
        return None
    limit = _nano_to_rub(budget.get("spend_limit_rub_nano"))
    spend = _nano_to_rub(budget.get("spend_rub_nano"))
    return BudgetInfo(
        spend_limit_rub=limit,
        spend_rub=spend,
        remaining_rub=max(limit - spend, Decimal("0")),
        window=str(budget.get("window") or ""),
    )


class DashboardData(BaseModel):
    """Данные для отображения на главном экране."""

    month_consumption: Consumption | None = None
    today_amount_rub: Decimal | None = None
    metrics: Metrics | None = None
    models: list[ModelMetrics] = Field(default_factory=list)
    keys: list[ApiKeyUsage] = Field(default_factory=list)
    budget: BudgetInfo | None = None
    offline: bool = False
    updated_at: dt.datetime | None = None
    error: str | None = None
    source: str = "live"

    @property
    def has_data(self) -> bool:
        return (
            self.month_consumption is not None
            or self.metrics is not None
            or bool(self.models)
        )


class DataService:
    """Собирает данные из API и сохраняет снимки в кэш."""

    def __init__(
        self,
        settings: Settings,
        credentials: Credentials,
        storage: Storage | None = None,
        transport: Any = None,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._storage = storage
        self._transport = transport

    async def refresh(self) -> DashboardData:
        """Получить актуальные данные (online) или последние из кэша (offline)."""
        now = dt.datetime.now(dt.timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        data = DashboardData(updated_at=now)
        errors: list[str] = []

        await self._load_billing(data, month_start, now, errors)
        await self._load_gateway(data, errors)

        if data.month_consumption is None and self._storage is not None:
            cached = self._storage.get_latest_consumption()
            if cached is not None:
                data.month_consumption = cached
                data.offline = True
                data.source = "cache"

        if errors:
            data.error = "; ".join(errors)

        if data.month_consumption is not None and self._storage is not None:
            history_amount = data.today_amount_rub
            if history_amount is None:
                history_amount = data.month_consumption.amount_rub
            self._storage.save_snapshot(
                consumption=data.month_consumption,
                metrics=data.metrics,
                models=data.models,
                history_point=HistoryPoint(
                    timestamp=now.replace(hour=0, minute=0, second=0, microsecond=0),
                    amount_rub=history_amount,
                    tokens=TokenUsage(
                        input_tokens=data.metrics.input_tokens if data.metrics else 0,
                        output_tokens=(
                            data.metrics.output_tokens if data.metrics else 0
                        ),
                        cache_read_tokens=(
                            data.metrics.cache_read_tokens if data.metrics else 0
                        ),
                        cache_write_tokens=(
                            data.metrics.cache_write_tokens if data.metrics else 0
                        ),
                    ),
                ),
            )
        return data

    async def _load_billing(
        self,
        data: DashboardData,
        month_start: dt.datetime,
        now: dt.datetime,
        errors: list[str],
    ) -> None:
        billing = BillingClient(
            self._settings.api_base_url,
            self._credentials.static_token,
            transport=self._transport,
        )
        try:
            # end — текущий момент с временем, чтобы включить сегодняшний день
            # (end = дата без времени отсекает текущий день из суммы).
            # API принимает только naive datetime (без смещения часового пояса).
            end_full = now.replace(tzinfo=None).isoformat(timespec="milliseconds")
            total_kop = await billing.get_summary(
                month_start.date().isoformat(), end_full
            )
            data.month_consumption = Consumption(period=now, amount_rub=total_kop / 100)
            # Дневная стоимость сегодняшнего дня — для точки истории.
            try:
                today_items = await billing.get_consumption(
                    now.date().isoformat(), end_full, period_group_type="day"
                )
                today_total = sum(
                    (item.value for item in today_items), start=Decimal("0")
                )
                data.today_amount_rub = today_total / 100
            except SelectelApiError:
                data.today_amount_rub = None
        except SelectelApiError as exc:
            errors.append(f"Billing: {exc}")
        finally:
            await billing.aclose()

    async def _load_gateway(self, data: DashboardData, errors: list[str]) -> None:
        """Gateway API требует IAM-доступ; недоступность не роняет дашборд."""
        if not self._credentials.service_user or not self._credentials.password:
            errors.append(
                "Gateway: не настроен сервисный пользователь (токены/модели недоступны)"
            )
            return
        try:
            iam = IamClient(
                self._settings, self._credentials, transport=self._transport
            )
            provider = IamTokenManager(iam)
            gateway = GatewayClient(
                self._settings.api_base_url,
                provider,
                self._credentials.project_id,
                self._credentials.domain_id,
                transport=self._transport,
            )
            try:
                gateways = await gateway.list_gateways()
                router_id = self._settings.router_id or (
                    str(gateways[0]["id"]) if gateways else ""
                )
                if router_id:
                    overview = await gateway.get_overview(router_id)
                    metrics = await gateway.get_metrics(router_id)
                    data.metrics = parse_metrics(metrics.raw)
                    data.models = parse_models(metrics.raw)
                    data.keys = parse_keys(await gateway.list_keys())
                    data.budget = parse_budget(overview.raw)
                    # Сумма за месяц из Gateway Overview (совпадает с вкладкой
                    # «Обзор»); биллинг используется как фолбэк.
                    data.month_consumption = parse_overview(
                        overview.raw, dt.datetime.now(dt.timezone.utc)
                    )
                else:
                    errors.append("Gateway: нет ИИ-роутеров")
            finally:
                await gateway.aclose()
        except Exception as exc:  # noqa: BLE001 - на уровне сервиса ловим всё
            errors.append(f"Gateway: {exc}")
