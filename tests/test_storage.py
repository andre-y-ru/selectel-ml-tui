"""Unit-тесты SQLite-кэша и истории."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from decimal import Decimal

import pytest

from selectel_ml_tui.models import (
    Consumption,
    HistoryPoint,
    Metrics,
    ModelMetrics,
    TokenUsage,
)
from selectel_ml_tui.storage import Storage, default_db_path


def _consumption(period: str, amount: str) -> Consumption:
    return Consumption.model_validate(
        {
            "period": period,
            "amount_rub": amount,
            "input_tokens": 100,
            "output_tokens": 200,
            "cache_read_tokens": 30,
            "cache_write_tokens": 40,
        }
    )


def _metrics() -> Metrics:
    return Metrics.model_validate(
        {
            "availability_pct": 99.9,
            "avg_ttft_ms": 0.4,
            "input_tokens": 1000,
            "output_tokens": 900,
            "cache_read_tokens": 800,
            "cache_write_tokens": 700,
        }
    )


def _models() -> list[ModelMetrics]:
    return [
        ModelMetrics.model_validate(
            {
                "model_id": "gpt-4o",
                "model_name": "GPT-4o",
                "availability_pct": 99.9,
                "avg_ttft_ms": 0.3,
            }
        ),
        ModelMetrics.model_validate({"model_id": "llama-3", "model_name": "Llama 3"}),
    ]


def test_default_db_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("selectel_ml_tui.storage.data_dir", lambda: tmp_path)
    assert default_db_path() == tmp_path / "cache.db"
    assert default_db_path().parent == tmp_path


def test_save_and_get_latest_consumption(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    item = _consumption("2026-08-01T00:00:00", "854.83")
    storage.save_consumption(item)
    latest = storage.get_latest_consumption()
    assert latest is not None
    assert latest.amount_rub == Decimal("854.83")
    assert latest.period == dt.datetime(2026, 8, 1)
    assert latest.input_tokens == 100
    storage.close()


def test_get_latest_empty(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    assert storage.get_latest_consumption() is None
    assert storage.get_latest_metrics() is None
    assert storage.get_latest_model_metrics() == []
    storage.close()


def test_save_and_get_latest_metrics(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.save_metrics(_metrics())
    latest = storage.get_latest_metrics()
    assert latest is not None
    assert latest.availability_pct == 99.9
    assert latest.input_tokens == 1000
    storage.close()


def test_save_and_get_latest_model_metrics(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.save_model_metrics(_models())
    latest = storage.get_latest_model_metrics()
    assert len(latest) == 2
    assert {m.model_id for m in latest} == {"gpt-4o", "llama-3"}
    gpt = next(m for m in latest if m.model_id == "gpt-4o")
    assert gpt.availability_pct == 99.9
    storage.close()


def test_history_upsert_same_day(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    point = HistoryPoint(
        timestamp=dt.datetime(2026, 8, 1, 12, 0),
        amount_rub=Decimal("10.00"),
        tokens=TokenUsage(input_tokens=5),
    )
    storage.save_history(point)
    point2 = HistoryPoint(
        timestamp=dt.datetime(2026, 8, 1, 12, 0),
        amount_rub=Decimal("15.00"),
        tokens=TokenUsage(input_tokens=8),
    )
    storage.save_history(point2)
    history = storage.get_history(days=30)
    assert len(history) == 1  # upsert, без дублей
    assert history[0].amount_rub == Decimal("15.00")
    storage.close()


def test_history_days_filter(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    now = dt.datetime.now(dt.timezone.utc)
    storage.save_history(
        HistoryPoint(timestamp=now, amount_rub=Decimal("1"), tokens=TokenUsage())
    )
    storage.save_history(
        HistoryPoint(
            timestamp=now - dt.timedelta(days=30),
            amount_rub=Decimal("2"),
            tokens=TokenUsage(),
        )
    )
    assert len(storage.get_history(days=7)) == 1
    assert len(storage.get_history(days=60)) == 2
    storage.close()


def test_save_snapshot_combined(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.save_snapshot(
        consumption=_consumption("2026-08-01T00:00:00", "854.83"),
        metrics=_metrics(),
        models=_models(),
        history_point=HistoryPoint(
            timestamp=dt.datetime(2026, 8, 1, 12, 0),
            amount_rub=Decimal("854.83"),
            tokens=TokenUsage(input_tokens=100),
        ),
    )
    assert storage.get_latest_consumption() is not None
    assert storage.get_latest_metrics() is not None
    assert len(storage.get_latest_model_metrics()) == 2
    assert len(storage.get_history(days=30)) == 1
    storage.close()


def test_cleanup_removes_old(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    old = dt.datetime(2020, 1, 1, 0, 0)
    storage.save_history(
        HistoryPoint(timestamp=old, amount_rub=Decimal("1"), tokens=TokenUsage())
    )
    storage.save_consumption(_consumption("2020-01-01T00:00:00", "1"))
    deleted = storage.cleanup(max_age_days=30)
    # history удаляется по timestamp; consumption_snapshots — по created_at (сейчас)
    assert deleted == 1
    assert storage.get_history(days=3650) == []
    assert storage.get_latest_consumption() is not None
    storage.close()


def test_export_json(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.save_history(
        HistoryPoint(
            timestamp=dt.datetime(2026, 8, 1, 12, 0),
            amount_rub=Decimal("854.83"),
            tokens=TokenUsage(input_tokens=100, output_tokens=200),
        )
    )
    out = tmp_path / "history.json"
    storage.export_json(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["amount_rub"] == "854.83"
    assert data[0]["input_tokens"] == 100
    storage.close()


def test_export_csv(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.save_history(
        HistoryPoint(
            timestamp=dt.datetime(2026, 8, 1, 12, 0),
            amount_rub=Decimal("854.83"),
            tokens=TokenUsage(input_tokens=100, output_tokens=200),
        )
    )
    out = tmp_path / "history.csv"
    storage.export_csv(out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("timestamp,amount_rub")
    assert "854.83" in lines[1]
    assert "100" in lines[1]
    storage.close()


def test_close_idempotent(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.close()
    with pytest.raises(sqlite3.ProgrammingError):
        storage.get_history()


def test_clear_removes_all_rows(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.save_history(
        HistoryPoint(
            timestamp=dt.datetime(2026, 8, 18),
            amount_rub=Decimal("1"),
            tokens=TokenUsage(input_tokens=1),
        )
    )
    storage.save_consumption(Consumption(period="2026-08-01T00:00:00"))
    assert storage.get_history() != []
    deleted = storage.clear()
    assert deleted >= 1
    assert storage.get_history() == []
    assert storage.get_latest_consumption() is None
