"""Unit-тесты pydantic-моделей данных."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from selectel_ml_tui.models import (
    Consumption,
    ConsumptionItem,
    HistoryPoint,
    Metrics,
    ModelMetrics,
    ProjectRef,
    format_percent,
    format_rub,
    format_tokens,
)


class TestConsumption:
    def test_parse_with_z_timestamp(self) -> None:
        item = Consumption.model_validate(
            {
                "period": "2026-08-01T00:00:00.000Z",
                "amount_rub": "854.83",
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 10,
                "cache_write_tokens": 5,
            }
        )
        assert item.period == datetime(2026, 8, 1, tzinfo=timezone.utc)
        assert item.amount_rub == Decimal("854.83")
        assert item.input_tokens == 100

    def test_parse_naive_timestamp(self) -> None:
        item = Consumption.model_validate({"period": "2026-08-01T00:00:00"})
        assert item.period == datetime(2026, 8, 1)
        assert item.amount_rub == Decimal("0")
        assert item.input_tokens == 0

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Consumption.model_validate(
                {"period": "2026-08-01T00:00:00", "amount_rub": "-1"}
            )

    def test_negative_tokens_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Consumption.model_validate(
                {
                    "period": "2026-08-01T00:00:00",
                    "input_tokens": -5,
                }
            )

    def test_invalid_date_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Consumption.model_validate({"period": "not-a-date"})


class TestMetrics:
    def test_parse_metrics(self) -> None:
        metrics = Metrics.model_validate(
            {
                "availability_pct": 99.912,
                "avg_ttft_ms": 0.45,
                "input_tokens": 1000,
                "output_tokens": 900,
                "cache_read_tokens": 800,
                "cache_write_tokens": 700,
            }
        )
        assert metrics.availability_pct == 99.912
        assert metrics.avg_ttft_ms == 0.45
        assert metrics.input_tokens == 1000

    def test_missing_fields_defaults(self) -> None:
        metrics = Metrics.model_validate({})
        assert metrics.availability_pct == 100.0
        assert metrics.input_tokens == 0
        assert metrics.avg_ttft_ms == 0.0

    def test_availability_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Metrics.model_validate({"availability_pct": 101})
        with pytest.raises(ValidationError):
            Metrics.model_validate({"availability_pct": -1})


class TestModelMetrics:
    def test_parse_model_metrics(self) -> None:
        model = ModelMetrics.model_validate(
            {
                "model_id": "gpt-4o",
                "model_name": "GPT-4o",
                "availability_pct": 99.5,
                "avg_ttft_ms": 0.3,
            }
        )
        assert model.model_id == "gpt-4o"
        assert model.model_name == "GPT-4o"
        assert model.availability_pct == 99.5


class TestHistoryPoint:
    def test_parse(self) -> None:
        point = HistoryPoint.model_validate(
            {
                "timestamp": "2026-08-01T12:00:00Z",
                "amount_rub": "12.5",
                "tokens": {
                    "input_tokens": 100,
                    "output_tokens": 200,
                    "cache_read_tokens": 30,
                    "cache_write_tokens": 40,
                },
            }
        )
        assert point.timestamp == datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        assert point.amount_rub == Decimal("12.5")
        assert point.tokens.output_tokens == 200

    def test_missing_tokens_defaults(self) -> None:
        point = HistoryPoint.model_validate({"timestamp": "2026-08-01T00:00:00"})
        assert point.tokens.input_tokens == 0
        assert point.amount_rub == Decimal("0")


class TestConsumptionItem:
    def _base(self, **overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            "account_id": "239633",
            "period": "2026-08-01T00:00:00",
            "provider_key": "aig",
            "value": 854.83,
        }
        data.update(overrides)
        return data

    def test_project_as_string(self) -> None:
        item = ConsumptionItem.model_validate(
            self._base(project="7bf2d2a328494e25b13d05a1926ca75a")
        )
        assert item.project_id == "7bf2d2a328494e25b13d05a1926ca75a"

    def test_project_as_object(self) -> None:
        item = ConsumptionItem.model_validate(
            self._base(
                project={"id": "proj-1", "name": "239633"},
            )
        )
        assert isinstance(item.project, ProjectRef)
        assert item.project_id == "proj-1"
        assert item.project.name == "239633"

    def test_project_null(self) -> None:
        item = ConsumptionItem.model_validate(self._base(project=None))
        assert item.project_id is None

    def test_object_as_object(self) -> None:
        item = ConsumptionItem.model_validate(
            self._base(
                object={
                    "id": "obj-1",
                    "name": "key-1",
                    "type": "ai_api_key",
                    "type_name": "Api ключ",
                }
            )
        )
        assert item.object_id == "obj-1"
        assert item.object.type == "ai_api_key"  # type: ignore[union-attr]

    def test_object_as_string(self) -> None:
        item = ConsumptionItem.model_validate(self._base(object="obj-1"))
        assert item.object_id == "obj-1"

    def test_metric_info(self) -> None:
        item = ConsumptionItem.model_validate(
            self._base(
                metric={
                    "id": "air_tokens_cost",
                    "name": "Стоимость",
                    "unit": "nanorub",
                    "quantity": "854857248637",
                }
            )
        )
        assert item.metric is not None
        assert item.metric.id == "air_tokens_cost"
        assert item.metric.quantity == Decimal("854857248637")

    def test_value_decimal(self) -> None:
        item = ConsumptionItem.model_validate(self._base(value=42.5))
        assert item.value == Decimal("42.5")


class TestFormatting:
    def test_format_rub(self) -> None:
        assert format_rub(Decimal("854.83")) == "854,83 ₽"
        assert format_rub(0) == "0,00 ₽"
        assert format_rub("1234.5") == "1 234,50 ₽"

    def test_format_tokens(self) -> None:
        assert format_tokens(0) == "0"
        assert format_tokens(1234567) == "1 234 567"

    def test_format_percent(self) -> None:
        assert format_percent(99.912) == "99,9%"
        assert format_percent(100.0) == "100,0%"
