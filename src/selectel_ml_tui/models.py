"""Pydantic-модели данных Selectel ML.

Модели ответов Billing Statistics API и Gateway API ИИ-роутера, а также
агрегированные структуры для TUI (потребление, метрики, история).

Все модели устойчивы к отсутствующим полям (значения по умолчанию) и
валидируют неотрицательные числа.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def parse_iso_dt(value: str) -> datetime:
    """Распарсить ISO-дату, допускающую 'Z' и нативные (без tz) значения."""
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Некорректная дата: {value!r}") from exc


def _validate_dt(value: Any) -> Any:
    if isinstance(value, str):
        return parse_iso_dt(value)
    return value


def format_rub(amount: Decimal | int | float | str) -> str:
    """Сумма в рублях: 854.83 -> '854,83 ₽', 1234.5 -> '1 234,50 ₽'."""
    value = Decimal(str(amount))
    rub, kop = f"{value:.2f}".split(".")
    rub = f"{int(rub):,}".replace(",", " ")
    return f"{rub},{kop} ₽"


def format_tokens(value: int) -> str:
    """Число токенов с разделителями: 1234567 -> '1 234 567'."""
    return f"{int(value):,}".replace(",", " ")


def format_percent(value: float) -> str:
    """Процент: 99.912 -> '99,9%'."""
    return f"{float(value):.1f}".replace(".", ",") + "%"


class TokenUsage(BaseModel):
    """Метрики токенов (все неотрицательные)."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)


class Consumption(TokenUsage):
    """Потребление за период: стоимость + токены."""

    period: datetime
    amount_rub: Decimal = Field(default=Decimal("0"), ge=0)
    requests: int = Field(default=0, ge=0)
    tokens_total: int = Field(default=0, ge=0)

    _validate_period = field_validator("period", mode="before")(_validate_dt)


class Metrics(TokenUsage):
    """Общие метрики роутера за 24 часа."""

    availability_pct: float = Field(default=100.0, ge=0, le=100)
    avg_ttft_ms: float = Field(default=0.0, ge=0)
    avg_latency_ms: float = Field(default=0.0, ge=0)
    requests: int = Field(default=0, ge=0)


class ModelMetrics(Metrics):
    """Метрики по конкретной модели."""

    model_id: str = ""
    model_name: str = ""


class ApiKeyUsage(BaseModel):
    """Лимиты и расход по одному API-ключу роутера."""

    name: str = ""
    prefix: str = ""
    is_active: bool = True
    spend_limit_rub: Decimal = Field(default=Decimal("0"), ge=0)
    spend_rub: Decimal = Field(default=Decimal("0"), ge=0)
    remaining_rub: Decimal = Field(default=Decimal("0"), ge=0)


class BudgetInfo(BaseModel):
    """Бюджет роутера: лимит, расход, остаток."""

    spend_limit_rub: Decimal = Field(default=Decimal("0"), ge=0)
    spend_rub: Decimal = Field(default=Decimal("0"), ge=0)
    remaining_rub: Decimal = Field(default=Decimal("0"), ge=0)
    window: str = ""


class HistoryPoint(BaseModel):
    """Точка истории для графика: время, стоимость, токены."""

    timestamp: datetime
    amount_rub: Decimal = Field(default=Decimal("0"), ge=0)
    tokens: TokenUsage = Field(default_factory=TokenUsage)

    _validate_timestamp = field_validator("timestamp", mode="before")(_validate_dt)


class MetricInfo(BaseModel):
    """Информация о метрике из billing statistics API."""

    id: str = ""
    name: str = ""
    unit: str = ""
    quantity: Decimal | None = None
    locale: str | None = None
    region: str | None = None


class ProjectRef(BaseModel):
    """Ссылка на проект (ML)."""

    id: str = ""
    name: str = ""


class ObjectRef(BaseModel):
    """Ссылка на объект (ключ/роутер)."""

    id: str = ""
    name: str = ""
    parent_id: str | None = None
    parent_name: str | None = None
    type: str | None = None
    type_name: str | None = None


class ConsumptionItem(BaseModel):
    """Элемент потребления из /v1/cloud_billing/statistic/consumption.

    ``project`` и ``object`` могут быть строкой (id), объектом или null.
    """

    model_config = ConfigDict(populate_by_name=True)

    account_id: str = ""
    period: str = ""
    provider_key: str = ""
    metric: MetricInfo | None = None
    value: Decimal = Decimal("0")
    project: ProjectRef | str | None = Field(default=None, alias="project")
    object: ObjectRef | str | None = Field(default=None, alias="object")
    balance: Decimal | None = None
    provision_start: str | None = None
    provision_end: str | None = None

    @property
    def project_id(self) -> str | None:
        """ID проекта (из строки или объекта)."""
        if isinstance(self.project, ProjectRef):
            return self.project.id
        return self.project

    @property
    def object_id(self) -> str | None:
        """ID объекта (из строки или объекта)."""
        if isinstance(self.object, ObjectRef):
            return self.object.id
        return self.object


class RouterOverview(BaseModel):
    """Потребление ИИ-роутера (GET /aig/gateway/v1/gateways/{id}/overview).

    ``raw`` хранит необработанные данные до полного описания схемы.
    """

    raw: dict[str, Any] = Field(
        default_factory=dict, description="Необработанные данные ответа"
    )


class RouterMetrics(BaseModel):
    """Метрики ИИ-роутера за 24 часа (GET /aig/gateway/v1/gateways/{id}/metrics)."""

    raw: dict[str, Any] = Field(
        default_factory=dict, description="Необработанные данные ответа"
    )
