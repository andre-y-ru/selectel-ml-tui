"""Headless-тесты TUI (Textual pilot)."""

from __future__ import annotations

import asyncio
import datetime as dt
from decimal import Decimal

from textual.widgets import DataTable, Input, Static

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
from selectel_ml_tui.services import DashboardData
from selectel_ml_tui.storage import Storage
from selectel_ml_tui.ui.app import DogLoader, SelectelMLTUI


class FakeService:
    """Сервис-заглушка: возвращает готовые данные."""

    def __init__(self, data: DashboardData) -> None:
        self.data = data
        self.refresh_count = 0

    async def refresh(self) -> DashboardData:
        self.refresh_count += 1
        return self.data


class BlockingService:
    """Сервис-заглушка: блокирует refresh до снятия события."""

    def __init__(self, data: DashboardData, release: asyncio.Event) -> None:
        self.data = data
        self.release = release
        self.started = asyncio.Event()

    async def refresh(self) -> DashboardData:
        self.started.set()
        await self.release.wait()
        return self.data


def _dashboard_data() -> DashboardData:
    return DashboardData(
        month_consumption=Consumption.model_validate(
            {
                "period": "2026-08-01T00:00:00",
                "amount_rub": "854.83",
                "requests": 1034,
                "tokens_total": 451607518,
                "input_tokens": 100,
                "output_tokens": 200,
                "cache_read_tokens": 30,
                "cache_write_tokens": 40,
            }
        ),
        metrics=Metrics.model_validate(
            {
                "availability_pct": 99.9,
                "avg_ttft_ms": 0.4,
                "avg_latency_ms": 1.2,
                "requests": 1035,
                "input_tokens": 5,
            }
        ),
        models=[
            ModelMetrics.model_validate(
                {
                    "model_id": "gpt-4o",
                    "model_name": "GPT-4o",
                    "requests": 69,
                    "availability_pct": 100.0,
                    "avg_ttft_ms": 3.35,
                }
            )
        ],
        keys=[
            ApiKeyUsage(
                name="Mei",
                prefix="sk-sl-v1-9dd61ec",
                is_active=True,
                spend_limit_rub=Decimal("1300"),
                spend_rub=Decimal("1082.95"),
                remaining_rub=Decimal("217.05"),
            )
        ],
        budget=BudgetInfo(
            spend_limit_rub=Decimal("2000"),
            spend_rub=Decimal("1077.87"),
            remaining_rub=Decimal("922.13"),
        ),
    )


def _make_app(tmp_path, data: DashboardData | None = None) -> SelectelMLTUI:
    settings = Settings(refresh_interval=3600)
    creds = Credentials(static_token="tok")
    storage = Storage(tmp_path / "cache.db")
    service = FakeService(data or _dashboard_data())
    return SelectelMLTUI(
        settings=settings,
        credentials=creds,
        storage=storage,
        service=service,
    )


async def test_dashboard_renders_data(tmp_path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        month = app.screen.query_one("#month-panel", Static)
        rendered = str(month.render())
        assert "854,83" in rendered
        assert "Потребление за месяц" in rendered
        metrics = app.screen.query_one("#metrics-panel", Static)
        assert "99,9%" in str(metrics.render())
        table = app.screen.query_one("#models-table", DataTable)
        assert table.row_count == 1
        assert "GPT-4o" in table.get_row_at(0)


async def test_refresh_hotkey_reruns_service(tmp_path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        service = app._service
        assert service.refresh_count == 1
        await pilot.press("r")
        await pilot.pause()
        assert service.refresh_count == 2


async def test_navigate_to_history_and_settings(tmp_path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # history
        await pilot.press("h")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "HistoryScreen"
        # назад
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "DashboardScreen"
        # settings
        await pilot.press("s")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "SettingsScreen"
        info = app.screen.query_one("#settings-info", Static).render()
        assert "API base URL" in str(info)
        assert "tok" in str(info)
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "DashboardScreen"


async def test_history_screen_shows_points(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.save_history(
        HistoryPoint(
            timestamp=dt.datetime(2026, 8, 18, 0, 0),
            amount_rub=Decimal("854.83"),
            tokens=TokenUsage(input_tokens=100),
        )
    )
    app = _make_app(tmp_path)
    app._storage = storage
    async with app.run_test() as pilot:
        await pilot.press("h")
        await pilot.pause()
        table = app.screen.query_one("#history-table", DataTable)
        assert table.row_count == 1
        cells = [str(cell) for cell in table.get_row_at(0)]
        assert any("854,83" in cell for cell in cells)
        bars = app.screen.query_one("#history-bars")
        assert bars.render() != "Нет данных для графика"


async def test_history_period_switch(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    for day in range(20):
        storage.save_history(
            HistoryPoint(
                timestamp=dt.datetime(2026, 8, day + 1, 0, 0),
                amount_rub=Decimal(str(day + 1)),
                tokens=TokenUsage(input_tokens=day + 1),
            )
        )
    app = _make_app(tmp_path)
    app._storage = storage
    async with app.run_test() as pilot:
        await pilot.press("h")
        await pilot.pause()
        title = app.screen.query_one("#history-title", Static)
        assert "30 дней" in str(title.render())
        table = app.screen.query_one("#history-table", DataTable)
        rows_30 = table.row_count
        await pilot.click("#period-7")
        await pilot.pause()
        title = app.screen.query_one("#history-title", Static)
        assert "7 дней" in str(title.render())
        table = app.screen.query_one("#history-table", DataTable)
        assert table.row_count < rows_30
        await pilot.click("#period-90")
        await pilot.pause()
        assert "90 дней" in str(app.screen.query_one("#history-title", Static).render())
        assert app.screen.query_one("#history-table", DataTable).row_count >= rows_30


async def test_model_detail_on_enter(tmp_path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ModelDetailScreen"
        detail = app.screen.query_one("#model-detail", Static)
        rendered = str(detail.render())
        assert "GPT-4o" in rendered
        assert "Запросы" in rendered
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "DashboardScreen"


async def test_settings_save_interval(tmp_path, monkeypatch) -> None:
    saved = {}

    def fake_save(settings) -> None:
        saved["interval"] = settings.refresh_interval

    monkeypatch.setattr("selectel_ml_tui.ui.app.save_settings", fake_save)
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause()
        inp = app.screen.query_one("#interval-input", Input)
        inp.value = "120"
        await pilot.click("#save-settings")
        await pilot.pause()
        assert app._settings.refresh_interval == 120
        assert saved["interval"] == 120


async def test_settings_clear_cache(tmp_path) -> None:
    storage = Storage(tmp_path / "cache.db")
    storage.save_history(
        HistoryPoint(
            timestamp=dt.datetime(2026, 8, 18, 0, 0),
            amount_rub=Decimal("854.83"),
            tokens=TokenUsage(input_tokens=100),
        )
    )
    app = _make_app(tmp_path)
    app._storage = storage
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause()
        await pilot.click("#clear-cache")
        await pilot.pause()
        assert storage.get_history(days=30) == []


async def test_offline_status_in_subtitle(tmp_path) -> None:
    data = _dashboard_data()
    data.offline = True
    app = _make_app(tmp_path, data)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "offline" in app.sub_title


async def test_window_resize(tmp_path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.screen.__class__.__name__ == "DashboardScreen"
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert app.screen.__class__.__name__ == "DashboardScreen"
        month = app.screen.query_one("#month-panel", Static)
        assert "854,83" in str(month.render())


async def test_keys_screen(tmp_path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "KeysScreen"
        table = app.screen.query_one("#keys-table", DataTable)
        assert table.row_count == 1
        cells = [str(cell) for cell in table.get_row_at(0)]
        assert any("Mei" in cell for cell in cells)
        assert any("1 300" in cell for cell in cells)
        budget = app.screen.query_one("#keys-budget", Static)
        assert "Бюджет роутера" in str(budget.render())
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "DashboardScreen"


async def test_dog_loader_hidden_when_idle(tmp_path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        loader = app.screen.query_one("#dog-loader", DogLoader)
        assert not loader.has_class("visible")
        assert loader.display is False
        assert not loader.running
        # встроенный loading Textual не должен активироваться (иначе — точки)
        assert app.screen.loading is False


async def test_dog_loader_shown_during_refresh(tmp_path) -> None:
    release = asyncio.Event()
    settings = Settings(refresh_interval=3600)
    creds = Credentials(static_token="tok")
    storage = Storage(tmp_path / "cache.db")
    service = BlockingService(_dashboard_data(), release)
    app = SelectelMLTUI(
        settings=settings,
        credentials=creds,
        storage=storage,
        service=service,  # type: ignore[arg-type]
    )
    async with app.run_test() as pilot:
        await service.started.wait()
        await pilot.pause()
        loader = app.screen.query_one("#dog-loader", DogLoader)
        assert loader.has_class("visible")
        assert loader.display is True
        assert loader.running
        assert app.screen.loading is False
        # overlay покрывает весь экран
        assert loader.region == app.screen.region

        release.set()
        await pilot.pause(0.1)
        assert not loader.has_class("visible")
        assert loader.display is False
        assert not loader.running


async def test_input_blocked_during_refresh(tmp_path) -> None:
    release = asyncio.Event()
    settings = Settings(refresh_interval=3600)
    creds = Credentials(static_token="tok")
    storage = Storage(tmp_path / "cache.db")
    service = BlockingService(_dashboard_data(), release)
    app = SelectelMLTUI(
        settings=settings,
        credentials=creds,
        storage=storage,
        service=service,  # type: ignore[arg-type]
    )
    async with app.run_test() as pilot:
        await service.started.wait()
        await pilot.pause()
        # во время загрузки горячие клавиши заблокированы
        await pilot.press("h")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "DashboardScreen"

        release.set()
        await pilot.pause(0.1)
        # после загрузки навигация снова работает
        await pilot.press("h")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "HistoryScreen"


async def test_dog_loader_animates(tmp_path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        loader = app.screen.query_one("#dog-loader", DogLoader)
        loader.add_class("visible")
        loader.start()
        assert loader.running
        first = loader.render()
        await pilot.pause(0.4)
        second = loader.render()
        assert first != second
        loader.stop()
        assert not loader.running
