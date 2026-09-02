"""Локальный кэш и история данных (SQLite).

База данных в каталоге данных платформы (Linux: ~/.local/share,
macOS: ~/Library/Application Support). Хранит снимки потребления и метрик
при каждом успешном обновлении, а также историю по периодам для графиков.
При недоступности API TUI может показать последние данные из кэша.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from selectel_ml_tui.config import data_dir
from selectel_ml_tui.models import (
    Consumption,
    HistoryPoint,
    Metrics,
    ModelMetrics,
    TokenUsage,
    parse_iso_dt,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS consumption_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    period TEXT NOT NULL,
    amount_rub TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    availability_pct REAL NOT NULL DEFAULT 100,
    avg_ttft_ms REAL NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS model_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL DEFAULT '',
    availability_pct REAL NOT NULL DEFAULT 100,
    avg_ttft_ms REAL NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS history (
    timestamp TEXT PRIMARY KEY,
    amount_rub TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0
);
"""


def default_db_path() -> Path:
    """Путь к базе данных по умолчанию (каталог данных платформы)."""
    return data_dir() / "cache.db"


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _history_columns(point: HistoryPoint) -> tuple[Any, ...]:
    return (
        point.timestamp.isoformat(),
        str(point.amount_rub),
        point.tokens.input_tokens,
        point.tokens.output_tokens,
        point.tokens.cache_read_tokens,
        point.tokens.cache_write_tokens,
    )


def _history_from_row(row: sqlite3.Row) -> HistoryPoint:
    return HistoryPoint(
        timestamp=parse_iso_dt(cast(str, row["timestamp"])),
        amount_rub=Decimal(str(row["amount_rub"])),
        tokens=TokenUsage(
            input_tokens=cast(int, row["input_tokens"]),
            output_tokens=cast(int, row["output_tokens"]),
            cache_read_tokens=cast(int, row["cache_read_tokens"]),
            cache_write_tokens=cast(int, row["cache_write_tokens"]),
        ),
    )


class Storage:
    """SQLite-кэш: снимки потребления/метрик и история для графиков."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    @property
    def path(self) -> Path:
        return self._path

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def save_consumption(self, item: Consumption) -> None:
        """Сохранить снимок потребления."""
        self._conn.execute(
            """
            INSERT INTO consumption_snapshots
                (created_at, period, amount_rub, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                item.period.isoformat(),
                str(item.amount_rub),
                item.input_tokens,
                item.output_tokens,
                item.cache_read_tokens,
                item.cache_write_tokens,
            ),
        )
        self._conn.commit()

    def save_metrics(self, metrics: Metrics) -> None:
        """Сохранить снимок общих метрик."""
        self._conn.execute(
            """
            INSERT INTO metrics_snapshots
                (created_at, availability_pct, avg_ttft_ms, input_tokens,
                 output_tokens, cache_read_tokens, cache_write_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                metrics.availability_pct,
                metrics.avg_ttft_ms,
                metrics.input_tokens,
                metrics.output_tokens,
                metrics.cache_read_tokens,
                metrics.cache_write_tokens,
            ),
        )
        self._conn.commit()

    def save_model_metrics(self, models: list[ModelMetrics]) -> None:
        """Сохранить снимок метрик по моделям (один пакет = один created_at)."""
        batch = _utc_now()
        for model in models:
            self._conn.execute(
                """
                INSERT INTO model_metrics
                    (created_at, model_id, model_name, availability_pct,
                     avg_ttft_ms, input_tokens, output_tokens,
                     cache_read_tokens, cache_write_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch,
                    model.model_id,
                    model.model_name,
                    model.availability_pct,
                    model.avg_ttft_ms,
                    model.input_tokens,
                    model.output_tokens,
                    model.cache_read_tokens,
                    model.cache_write_tokens,
                ),
            )
        self._conn.commit()

    def save_history(self, point: HistoryPoint) -> None:
        """Сохранить/обновить точку истории (upsert по timestamp)."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO history
                (timestamp, amount_rub, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            _history_columns(point),
        )
        self._conn.commit()

    def save_snapshot(
        self,
        *,
        consumption: Consumption | None = None,
        metrics: Metrics | None = None,
        models: list[ModelMetrics] | None = None,
        history_point: HistoryPoint | None = None,
    ) -> None:
        """Сохранить полный снимок данных после успешного обновления."""
        if consumption is not None:
            self.save_consumption(consumption)
        if metrics is not None:
            self.save_metrics(metrics)
        if models:
            self.save_model_metrics(models)
        if history_point is not None:
            self.save_history(history_point)

    def get_latest_consumption(self) -> Consumption | None:
        """Последний снимок потребления (для офлайн-режима)."""
        row = self._conn.execute(
            "SELECT * FROM consumption_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return Consumption(
            period=parse_iso_dt(cast(str, row["period"])),
            amount_rub=Decimal(str(row["amount_rub"])),
            input_tokens=cast(int, row["input_tokens"]),
            output_tokens=cast(int, row["output_tokens"]),
            cache_read_tokens=cast(int, row["cache_read_tokens"]),
            cache_write_tokens=cast(int, row["cache_write_tokens"]),
        )

    def get_latest_metrics(self) -> Metrics | None:
        """Последний снимок общих метрик."""
        row = self._conn.execute(
            "SELECT * FROM metrics_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return Metrics(
            availability_pct=cast(float, row["availability_pct"]),
            avg_ttft_ms=cast(float, row["avg_ttft_ms"]),
            input_tokens=cast(int, row["input_tokens"]),
            output_tokens=cast(int, row["output_tokens"]),
            cache_read_tokens=cast(int, row["cache_read_tokens"]),
            cache_write_tokens=cast(int, row["cache_write_tokens"]),
        )

    def get_latest_model_metrics(self) -> list[ModelMetrics]:
        """Снимок метрик по моделям за последнее обновление."""
        rows = self._conn.execute(
            """
            SELECT * FROM model_metrics
            WHERE created_at = (SELECT MAX(created_at) FROM model_metrics)
            ORDER BY model_id
            """
        ).fetchall()
        models: list[ModelMetrics] = []
        for row in rows:
            models.append(
                ModelMetrics(
                    model_id=cast(str, row["model_id"]),
                    model_name=cast(str, row["model_name"]),
                    availability_pct=cast(float, row["availability_pct"]),
                    avg_ttft_ms=cast(float, row["avg_ttft_ms"]),
                    input_tokens=cast(int, row["input_tokens"]),
                    output_tokens=cast(int, row["output_tokens"]),
                    cache_read_tokens=cast(int, row["cache_read_tokens"]),
                    cache_write_tokens=cast(int, row["cache_write_tokens"]),
                )
            )
        return models

    def get_history(self, days: int = 7) -> list[HistoryPoint]:
        """Серия точек истории за последние ``days`` дней для графика."""
        cutoff = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        ).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM history WHERE timestamp >= ? ORDER BY timestamp ASC",
            (cutoff,),
        ).fetchall()
        return [_history_from_row(row) for row in rows]

    def cleanup(self, max_age_days: int = 180) -> int:
        """Удалить записи старше ``max_age_days`` дней. Возвращает число удалённых."""
        cutoff = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)
        ).isoformat()
        deleted = 0
        for table, column in (
            ("consumption_snapshots", "created_at"),
            ("metrics_snapshots", "created_at"),
            ("model_metrics", "created_at"),
            ("history", "timestamp"),
        ):
            cursor = self._conn.execute(
                f"DELETE FROM {table} WHERE {column} < ?", (cutoff,)
            )
            deleted += cursor.rowcount
        self._conn.commit()
        return deleted

    def export_json(self, path: Path) -> None:
        """Экспортировать всю историю в JSON."""
        points = self.get_history(days=3650)
        data = [
            {
                "timestamp": point.timestamp.isoformat(),
                "amount_rub": str(point.amount_rub),
                "input_tokens": point.tokens.input_tokens,
                "output_tokens": point.tokens.output_tokens,
                "cache_read_tokens": point.tokens.cache_read_tokens,
                "cache_write_tokens": point.tokens.cache_write_tokens,
            }
            for point in points
        ]
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def export_csv(self, path: Path) -> None:
        """Экспортировать всю историю в CSV."""
        points = self.get_history(days=3650)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "timestamp",
                    "amount_rub",
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                ]
            )
            for point in points:
                writer.writerow(_history_columns(point))

    def clear(self) -> int:
        """Полностью очистить кэш. Возвращает число удалённых записей."""
        deleted = 0
        for table in (
            "consumption_snapshots",
            "metrics_snapshots",
            "model_metrics",
            "history",
        ):
            cursor = self._conn.execute(f"DELETE FROM {table}")
            deleted += cursor.rowcount
        self._conn.commit()
        return deleted

    def close(self) -> None:
        self._conn.close()
