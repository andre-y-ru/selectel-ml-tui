"""TUI-приложение selectel-ml-tui на Textual.

Экраны: Dashboard (главный), History (история), Settings (настройки).
Автообновление по таймеру, асинхронная загрузка через workers, офлайн-режим
с показом последних данных из SQLite-кэша.
"""

from __future__ import annotations

from typing import Any

from rich.align import Align
from rich.panel import Panel
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.events import InputEvent
from textual.reactive import reactive
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Static,
)

from selectel_ml_tui.config import (
    config_dir,
    data_dir,
    load_credentials,
    load_settings,
    save_settings,
)
from selectel_ml_tui.models import (
    ApiKeyUsage,
    ModelMetrics,
    format_percent,
    format_rub,
    format_tokens,
)
from selectel_ml_tui.services import DashboardData, DataService
from selectel_ml_tui.storage import Storage

PERIOD_OPTIONS = (7, 30, 90)


def _mask_token(value: str) -> str:
    if not value:
        return "(не задан)"
    return f"{value[:4]}…({len(value)})"


class DogLoader(Static):
    """Полноэкранный индикатор загрузки: бегущая ASCII-собачка.

    overlay поверх всего дашборда с полупрозрачным затемнением; собака
    «бежит» (переставляет лапы, виляет хвостом), под ней — дорожка из 🐾.
    Показывается на время обновления статистики и блокирует ввод.
    """

    BODY = (
        "            __",
        "       ____/  \\___",
        "      / oo        \\____",
        "     |      __         \\____",
        "      \\____/  \\____________/",
    )
    LEGS = (
        ("      ||    ||        \\   ~", "      ||    ||         \\_/"),
        ("     //    \\\\       \\   ~~", "     //    \\\\        \\_/"),
        ("      ||    ||        \\     ~", "      ||    ||         \\_/"),
        ("     \\\\    //       \\    ~~", "     \\\\    //        \\_/"),
    )
    CAPTION = "Обновление статистики…"
    INTERVAL = 0.12

    frame = reactive(0)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._timer: Timer | None = None

    @property
    def running(self) -> bool:
        """Идёт ли анимация."""
        return self._timer is not None

    def start(self) -> None:
        """Запустить анимацию (идемпотентно)."""
        if self._timer is None:
            self._timer = self.set_interval(self.INTERVAL, self._next_frame)

    def stop(self) -> None:
        """Остановить анимацию (идемпотентно)."""
        if self._timer is not None:
            self._timer.pause()
            self._timer = None

    def _next_frame(self) -> None:
        self.frame = (self.frame + 1) % len(self.LEGS)

    def _art(self) -> str:
        index = self.frame % len(self.LEGS)
        legs1, legs2 = self.LEGS[index]
        return "\n".join([*self.BODY, legs1, legs2])

    def _paws(self) -> str:
        index = self.frame % len(self.LEGS)
        return " ".join("🐾" if (i + index) % 2 == 0 else "  " for i in range(8))

    def render(self) -> Any:
        theme = self.app.current_theme
        body = Text(self._art(), style=f"bold {theme.accent}", justify="center")
        paws = Text(self._paws(), style=str(theme.secondary), justify="center")
        caption = Text(self.CAPTION, style=f"bold {theme.foreground}", justify="center")
        content = Text("\n").join([body, Text(), paws, Text(), caption])
        return Panel(
            Align.center(content, vertical="middle"),
            title="[b]🐕 selectel-ml-tui[/b]",
            border_style=str(theme.primary),
            padding=(1, 4),
        )

    @on(InputEvent)
    def _block_input(self, event: InputEvent) -> None:
        """Перехватить ввод, пока показывается индикатор загрузки."""
        if self.has_class("visible"):
            event.stop()
            event.prevent_default()


class ConsumptionBars(Static):
    """Unicode-бар-график потребления (столбцы)."""

    data: reactive[list[float]] = reactive([])

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.height = 7

    def render(self) -> Any:
        values = self.data
        if not values:
            return "Нет данных для графика"
        maximum = max(values)
        if maximum <= 0:
            return "Нет данных для графика"
        lines: list[str] = []
        for level in range(self.height, 0, -1):
            row = ""
            for value in values:
                bar_height = max(1, int(value / maximum * self.height))
                row += "█" if bar_height >= level else " "
            lines.append(row)
        return "\n".join(lines) + f"\nmax: {maximum:.0f} ₽"


class DashboardScreen(Screen[Any]):
    """Главный экран: потребление за месяц, метрики, модели."""

    BINDINGS = [
        Binding("r", "refresh", "Обновить", show=True),
        Binding("h", "history", "История", show=True),
        Binding("k", "keys", "Ключи", show=True),
        Binding("s", "settings", "Настройки", show=True),
    ]

    data = reactive(DashboardData())
    refreshing = reactive(False)

    def __init__(
        self,
        service: DataService,
        refresh_interval: int,
        storage: Storage,
        settings: Any,
        credentials: Any,
    ) -> None:
        super().__init__()
        self._service = service
        self._refresh_interval = refresh_interval
        self._storage = storage
        self._settings = settings
        self._credentials = credentials

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="dashboard"):
            with Horizontal(id="panels"):
                yield Static("", id="month-panel", classes="panel")
                yield Static("", id="metrics-panel", classes="panel")
            yield Static("По моделям", id="models-title")
            yield DataTable(id="models-table")
        yield DogLoader(id="dog-loader")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(self._refresh_interval, self._refresh)
        self._refresh()

    @work(exclusive=True, group="refresh")
    async def _refresh(self) -> None:
        self.refreshing = True
        try:
            self.data = await self._service.refresh()
        except Exception as exc:  # noqa: BLE001 - показываем toast при ошибке
            self.notify(f"Ошибка обновления: {exc}", severity="error")
        finally:
            self.refreshing = False

    def watch_refreshing(self, refreshing: bool) -> None:
        """Показать/скрыть полноэкранную собачку при обновлении."""
        try:
            loader = self.query_one("#dog-loader", DogLoader)
        except NoMatches:  # watcher может сработать до монтирования детей
            return
        if refreshing:
            loader.add_class("visible")
            loader.start()
            self.set_focus(None)
        else:
            loader.remove_class("visible")
            loader.stop()
            try:
                self.query_one("#models-table", DataTable).focus()
            except NoMatches:  # pragma: no cover - на всякий случай
                pass

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Заблокировать горячие клавиши на время обновления."""
        if self.refreshing:
            return False
        return super().check_action(action, parameters)

    def watch_data(self, data: DashboardData) -> None:
        status = "offline" if data.offline else "online"
        amount = (
            format_rub(data.month_consumption.amount_rub)
            if data.month_consumption
            else "—"
        )
        self.app.sub_title = f"{status} · {amount}"
        self._update_month_panel(data)
        self._update_metrics_panel(data)
        self._update_models_table(data)

    def _update_month_panel(self, data: DashboardData) -> None:
        text = "[bold]Потребление за месяц[/]\n\n"
        if data.month_consumption is None:
            text += "Нет данных"
        else:
            c = data.month_consumption
            text += f"Сумма: [b]{format_rub(c.amount_rub)}[/]\n"
            text += f"Запросы: {format_tokens(c.requests)}\n"
            text += f"Токены: {format_tokens(c.tokens_total)}\n"
            if data.today_amount_rub is not None:
                text += f"[dim]Сегодня: {format_rub(data.today_amount_rub)}[/]\n"
            if data.metrics is not None:
                m = data.metrics
                text += f"Input: {format_tokens(m.input_tokens)}\n"
                text += f"Output: {format_tokens(m.output_tokens)}\n"
                text += f"Cache read: {format_tokens(m.cache_read_tokens)}\n"
                text += f"Cache write: {format_tokens(m.cache_write_tokens)}"
            else:
                text += "\n[dim](токены — только через IAM)[/]"
        if data.budget is not None:
            b = data.budget
            text += (
                f"\n\n[bold]Бюджет[/]\n"
                f"Лимит: {format_rub(b.spend_limit_rub)}\n"
                f"Потрачено: {format_rub(b.spend_rub)}\n"
                f"Остаток: {format_rub(b.remaining_rub)}"
            )
        if data.offline:
            text += "\n\n[dim]офлайн (данные из кэша)[/]"
        if data.error:
            text += f"\n\n[red]{data.error}[/]"
        self.query_one("#month-panel", Static).update(text)

    def _update_metrics_panel(self, data: DashboardData) -> None:
        text = "[bold]Метрики за 24 часа[/]\n\n"
        if data.metrics is None:
            text += "Нет данных"
        else:
            m = data.metrics
            text += f"Доступность: {format_percent(m.availability_pct)}\n"
            text += f"Средний TTFT: {m.avg_ttft_ms:.1f} мс\n"
            text += f"Средняя задержка: {m.avg_latency_ms:.1f} мс\n"
            text += f"Запросы: {format_tokens(m.requests)}\n"
            text += f"Input: {format_tokens(m.input_tokens)}\n"
            text += f"Output: {format_tokens(m.output_tokens)}\n"
            text += f"Cache read: {format_tokens(m.cache_read_tokens)}\n"
            text += f"Cache write: {format_tokens(m.cache_write_tokens)}"
        self.query_one("#metrics-panel", Static).update(text)

    def _update_models_table(self, data: DashboardData) -> None:
        table = self.query_one("#models-table", DataTable)
        if not table.columns:
            table.add_columns(
                "Модель",
                "Запросы",
                "Доступность",
                "TTFT, мс",
                "Задержка, мс",
            )
            table.cursor_type = "row"
        table.clear()
        for model in data.models:
            table.add_row(
                model.model_name,
                format_tokens(model.requests),
                format_percent(model.availability_pct),
                f"{model.avg_ttft_ms:.1f}",
                f"{model.avg_latency_ms:.1f}",
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if not self.data.models:
            return
        row = event.cursor_row
        if row is None or row >= len(self.data.models):
            return
        self.app.push_screen(ModelDetailScreen(self.data.models[row]))

    def action_refresh(self) -> None:
        self._refresh()

    def action_history(self) -> None:
        self.app.push_screen(HistoryScreen(self._storage))

    def action_keys(self) -> None:
        self.app.push_screen(KeysScreen(self.data.keys, self.data.budget))

    def action_settings(self) -> None:
        self.app.push_screen(
            SettingsScreen(self._settings, self._credentials, self._storage)
        )

    def action_model_detail(self) -> None:
        if not self.data.models:
            return
        table = self.query_one("#models-table", DataTable)
        row = table.cursor_row
        if row is None:
            row = 0
        if row >= len(self.data.models):
            return
        self.app.push_screen(ModelDetailScreen(self.data.models[row]))


class KeysScreen(Screen[Any]):
    """Лимиты и расход по API-ключам роутера."""

    BINDINGS = [
        Binding("escape", "back", "Назад", show=True),
    ]

    def __init__(self, keys: list[ApiKeyUsage], budget: Any | None = None) -> None:
        super().__init__()
        self._keys = keys
        self._budget = budget

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("API-ключи и лимиты", id="keys-title")
        if self._budget is not None:
            yield Static("", id="keys-budget")
        yield DataTable(id="keys-table")
        yield Footer()

    def on_mount(self) -> None:
        if self._budget is not None:
            b = self._budget
            self.query_one("#keys-budget", Static).update(
                f"[bold]Бюджет роутера[/]\n"
                f"Лимит: {format_rub(b.spend_limit_rub)}  "
                f"Потрачено: {format_rub(b.spend_rub)}  "
                f"Остаток: {format_rub(b.remaining_rub)}"
            )
        table = self.query_one("#keys-table", DataTable)
        table.add_columns("Ключ", "Префикс", "Статус", "Лимит", "Потрачено", "Остаток")
        for key in self._keys:
            table.add_row(
                key.name,
                key.prefix,
                "активен" if key.is_active else "неактивен",
                format_rub(key.spend_limit_rub),
                format_rub(key.spend_rub),
                format_rub(key.remaining_rub),
            )

    def action_back(self) -> None:
        self.app.pop_screen()


class HistoryScreen(Screen[Any]):
    """История потребления: бар-график и таблица по дням."""

    BINDINGS = [
        Binding("escape", "back", "Назад", show=True),
        Binding("r", "refresh", "Обновить", show=True),
    ]

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self._storage = storage
        self._days = 30

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("История потребления", id="history-title")
        with Horizontal(id="period-buttons"):
            for days in PERIOD_OPTIONS:
                yield Button(
                    f"{days} дней",
                    id=f"period-{days}",
                    variant="primary" if days == self._days else "default",
                )
        yield Static("Стоимость, руб. (по дням)", id="bars-title")
        yield ConsumptionBars("", id="history-bars")
        yield DataTable(id="history-table")
        yield Footer()

    def on_mount(self) -> None:
        self._reload()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id and button_id.startswith("period-"):
            self._days = int(button_id.split("-", 1)[1])
            for days in PERIOD_OPTIONS:
                button = self.query_one(f"#period-{days}", Button)
                button.variant = "primary" if days == self._days else "default"
            self._reload()

    def action_refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        points = self._storage.get_history(days=self._days)
        self.query_one("#history-title", Static).update(
            f"История потребления (последние {self._days} дней)"
        )
        values = [float(point.amount_rub) for point in points]
        self.query_one("#history-bars", ConsumptionBars).data = values

        table = self.query_one("#history-table", DataTable)
        if not table.columns:
            table.add_columns("Дата", "Сумма", "Input", "Output", "Cache")
        table.clear()
        for point in reversed(points):
            table.add_row(
                str(point.timestamp.date()),
                format_rub(point.amount_rub),
                format_tokens(point.tokens.input_tokens),
                format_tokens(point.tokens.output_tokens),
                format_tokens(
                    point.tokens.cache_read_tokens + point.tokens.cache_write_tokens
                ),
            )

    def action_back(self) -> None:
        self.app.pop_screen()


class ModelDetailScreen(Screen[Any]):
    """Детализация метрик конкретной модели."""

    BINDINGS = [
        Binding("escape", "back", "Назад", show=True),
    ]

    def __init__(self, model: ModelMetrics) -> None:
        super().__init__()
        self._model = model

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="model-detail")
        yield Footer()

    def on_mount(self) -> None:
        m = self._model
        body = f"[b]{m.model_name}[/b]\nID: {m.model_id}\n\n"
        body += f"Доступность: {format_percent(m.availability_pct)}\n"
        body += f"Запросы: {format_tokens(m.requests)}\n"
        body += f"Средний TTFT: {m.avg_ttft_ms:.1f} мс\n"
        body += f"Средняя задержка: {m.avg_latency_ms:.1f} мс"
        self.query_one("#model-detail", Static).update(body)

    def action_back(self) -> None:
        self.app.pop_screen()


class SettingsScreen(Screen[Any]):
    """Настройки: интервал обновления, очистка кэша, пути и токен."""

    BINDINGS = [
        Binding("escape", "back", "Назад", show=True),
    ]

    def __init__(self, settings: Any, credentials: Any, storage: Storage) -> None:
        super().__init__()
        self._settings = settings
        self._credentials = credentials
        self._storage = storage

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Настройки", id="settings-title")
        with Vertical(id="settings-body"):
            yield Static("Интервал обновления, сек:", id="interval-label")
            yield Input(
                value=str(self._settings.refresh_interval),
                id="interval-input",
                type="integer",
            )
            with Horizontal(id="settings-actions"):
                yield Button("Сохранить", id="save-settings", variant="primary")
                yield Button("Очистить кэш", id="clear-cache", variant="error")
            yield Static("", id="settings-info")
        yield Footer()

    def on_mount(self) -> None:
        info = (
            f"API base URL: {self._settings.api_base_url}\n"
            f"Router id: {self._settings.router_id or '(авто)'}\n"
            f"Сервисный пользователь: "
            f"{self._credentials.service_user or '(не задан)'}\n"
            f"Токен: {_mask_token(self._credentials.static_token)}\n"
            f"Config dir: {config_dir()}\n"
            f"Data dir: {data_dir()}"
        )
        self.query_one("#settings-info", Static).update(info)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "save-settings":
            self._save_interval()
        elif button_id == "clear-cache":
            self._clear_cache()

    def _save_interval(self) -> None:
        raw = self.query_one("#interval-input", Input).value
        try:
            interval = int(raw)
        except ValueError:
            self.notify("Некорректное значение интервала", severity="error")
            return
        if interval < 10:
            self.notify("Интервал должен быть не менее 10 секунд", severity="error")
            return
        if interval == self._settings.refresh_interval:
            return
        self._settings.refresh_interval = interval
        save_settings(self._settings)
        self.notify("Настройки сохранены")

    def _clear_cache(self) -> None:
        deleted = self._storage.clear()
        self.notify(f"Кэш очищен: удалено записей: {deleted}", severity="information")

    def action_back(self) -> None:
        self._save_interval()
        self.app.pop_screen()


class SelectelMLTUI(App[Any]):
    """Главное приложение."""

    TITLE = "Selectel ML Tokens"
    BINDINGS = [
        Binding("q", "quit", "Выход", show=False),
    ]

    async def action_quit(self) -> None:
        self.exit()

    CSS = """
    #panels {
        height: 10;
    }
    .panel {
        width: 1fr;
        height: 100%;
        border: round $primary;
        padding: 1 2;
        margin: 0 1 0 0;
    }
    #models-title {
        margin: 1 0 0 0;
        text-style: bold;
    }
    #models-table {
        height: 8;
    }
    #keys-title {
        margin: 1 0 0 0;
        text-style: bold;
    }
    #keys-budget {
        margin: 1 0;
        padding: 1 2;
        border: round $primary;
    }
    #keys-table {
        height: 60%;
        margin: 1 0 0 0;
    }
    #history-bars {
        height: 9;
        margin: 1 0;
        border: round $secondary;
        padding: 0 1;
    }
    #history-table {
        height: 40%;
        margin: 1 0 0 0;
    }
    #period-buttons {
        height: 3;
        margin: 1 0 0 0;
    }
    #period-buttons Button {
        width: 10;
        margin: 0 1 0 0;
    }
    #bars-title {
        margin: 1 0 0 0;
        text-style: bold;
    }
    #settings-body {
        margin: 1 2;
    }
    #interval-label {
        margin: 1 0 0 0;
    }
    #interval-input {
        width: 20;
    }
    #settings-actions {
        margin: 1 0;
    }
    #settings-actions Button {
        width: 16;
        margin: 0 1 0 0;
    }
    #settings-info {
        margin: 1 0 0 0;
    }
    #model-detail {
        margin: 2 4;
        padding: 1 2;
        border: round $primary;
    }
    #dog-loader {
        display: none;
        dock: top;
        layer: _loading;
        width: 100%;
        height: 100%;
        background: $background 80%;
        content-align: center middle;
        text-align: center;
    }
    #dog-loader.visible {
        display: block;
    }
    """

    def __init__(
        self,
        settings: Any | None = None,
        credentials: Any | None = None,
        storage: Storage | None = None,
        service: DataService | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings if settings is not None else load_settings()
        self._credentials = (
            credentials if credentials is not None else load_credentials()
        )
        self._storage = storage if storage is not None else Storage()
        self._service = (
            service
            if service is not None
            else DataService(self._settings, self._credentials, self._storage)
        )

    def on_mount(self) -> None:
        self.push_screen(
            DashboardScreen(
                self._service,
                self._settings.refresh_interval,
                self._storage,
                self._settings,
                self._credentials,
            )
        )


def run_app() -> None:
    """Запустить TUI-приложение (entry point)."""
    app = SelectelMLTUI()
    app.run()
