"""CLI-интерфейс selectel-ml-tui."""

from __future__ import annotations

from pathlib import Path

import click

from selectel_ml_tui import __version__
from selectel_ml_tui.config import (
    Credentials,
    Settings,
    config_dir,
    data_dir,
    load_credentials,
    load_settings,
    save_credentials,
    save_settings,
)


def _mask(value: str) -> str:
    """Замаскировать секрет: показать первые 4 символа и длину."""
    if not value:
        return "(не задан)"
    return f"{value[:4]}…({len(value)})"


def _print_config(settings: Settings, credentials: Credentials) -> None:
    click.echo(f"API base URL:     {settings.api_base_url}")
    click.echo(f"Identity URL:     {settings.identity_url}")
    click.echo(f"Refresh interval: {settings.refresh_interval} c")
    router_id = settings.router_id or "(не задан, будет выбран первый)"
    click.echo(f"Router id:        {router_id}")
    if settings.region:
        click.echo(f"Region:           {settings.region}")
    click.echo(f"Service user:     {credentials.service_user or '(не задан)'}")
    click.echo(f"Project id:       {credentials.project_id or '(не задан)'}")
    click.echo(f"Domain id:        {credentials.domain_id or '(не задан)'}")
    click.echo(f"Static token:     {_mask(credentials.static_token)}")
    click.echo(f"Password:         {_mask(credentials.password)}")


def _prompt_str(
    label: str,
    current: str,
    hide_input: bool = False,
    default_note: str = "(Enter — оставить)",
) -> str:
    prompt = f"{label} [{current or 'пусто'}] {default_note}: "
    value: str = click.prompt(
        prompt, default="", hide_input=hide_input, show_default=False
    )
    if value == "":
        return current
    return value


@click.group()
@click.version_option(__version__, prog_name="selectel-ml-tui")
def main() -> None:
    """TUI-приложение для отображения потребления ИИ-роутера Selectel."""


@main.command()
@click.option("--path", is_flag=True, help="Показать пути к конфигурации и выйти")
@click.option("--show", is_flag=True, help="Показать текущие настройки и выйти")
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Не запрашивать ввод (эквивалентно --show)",
)
def config(path: bool, show: bool, non_interactive: bool) -> None:
    """Настроить приложение (интерактивный мастер) или показать настройки."""
    if path:
        click.echo(f"config dir: {config_dir()}")
        click.echo(f"data dir:   {data_dir()}")
        return

    settings = load_settings()
    credentials = load_credentials()

    if show or non_interactive:
        _print_config(settings, credentials)
        return

    click.echo("Настройка selectel-ml-tui. Пустые значения сохраняют текущие.")
    settings.api_base_url = _prompt_str("API base URL", settings.api_base_url)
    while True:
        raw = _prompt_str(
            "Интервал обновления (сек, min 10)",
            str(settings.refresh_interval),
        )
        try:
            value = int(raw)
        except ValueError:
            click.echo("Ошибка: введите целое число секунд")
            continue
        if value < 10:
            click.echo("Ошибка: интервал не может быть меньше 10 секунд")
            continue
        settings.refresh_interval = value
        break
    settings.router_id = _prompt_str(
        "ID ИИ-роутера (необязательно)", settings.router_id
    )
    settings.region = _prompt_str("Регион (необязательно)", settings.region)

    credentials.service_user = _prompt_str(
        "Сервисный пользователь", credentials.service_user
    )
    credentials.domain_id = _prompt_str(
        "Номер аккаунта (domain)", credentials.domain_id
    )
    credentials.project_id = _prompt_str("ID проекта (ML)", credentials.project_id)
    credentials.password = _prompt_str(
        "Пароль сервисного пользователя",
        credentials.password,
        hide_input=True,
    )
    credentials.static_token = _prompt_str(
        "Статический токен (X-Token)",
        credentials.static_token,
        hide_input=True,
    )

    save_settings(settings)
    save_credentials(credentials)
    click.echo(f"Сохранено: {config_dir()}")
    _print_config(settings, credentials)


@main.command()
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["csv", "json"]),
    default="json",
    help="Формат экспорта",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Путь к файлу экспорта (по умолчанию history.csv/json в каталоге данных)",
)
def export(fmt: str, output: Path | None) -> None:
    """Экспортировать историю потребления в CSV/JSON."""
    from selectel_ml_tui.storage import Storage

    path = output if output is not None else data_dir() / f"history.{fmt}"
    storage = Storage()
    try:
        if fmt == "csv":
            storage.export_csv(path)
        else:
            storage.export_json(path)
    finally:
        storage.close()
    click.echo(f"Экспортировано: {path}")


@main.command()
def doctor() -> None:
    """Проверить окружение (ОС, терминал, кодировку) и пути."""
    from selectel_ml_tui.platform import check_environment, get_platform_info

    info = get_platform_info()
    click.echo(f"ОС:                 {info.system}")
    click.echo(f"Python:             {info.python_version}")
    failed = False
    for check in check_environment():
        mark = "OK  " if check.ok else "WARN"
        failed = failed or not check.ok
        click.echo(f"[{mark}] {check.name}: {check.detail}")
    credentials = load_credentials()
    has_token = bool(credentials.static_token or credentials.password)
    hint = "не настроен — выполните: selectel-ml-tui config"
    token_status = "настроен" if has_token else hint
    click.echo(f"[{'OK  ' if has_token else 'WARN'}] token: {token_status}")
    click.echo(f"Config dir:         {config_dir()}")
    click.echo(f"Data dir:           {data_dir()}")
    if failed:
        raise click.exceptions.Exit(1)


@main.command()
def run() -> None:
    """Запустить TUI-интерфейс (дашборд)."""
    from selectel_ml_tui.ui.app import run_app

    credentials = load_credentials()
    if not credentials.static_token and not credentials.password:
        msg = "Учётные данные не настроены. Выполните: selectel-ml-tui config"
        click.echo(msg, err=True)
        raise click.exceptions.Exit(1)
    run_app()


if __name__ == "__main__":
    main()