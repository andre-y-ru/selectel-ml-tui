"""Конфигурация приложения: настройки, пути, секреты.

Поддерживается чтение переменных окружения с префиксом SELCTEL_ и файла
конфигурации config.toml. Секреты (пароль сервисного пользователя,
статический токен) хранятся отдельно в файле credentials (права 0600).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "selectel-ml-tui"

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


class Settings(BaseSettings):
    """Несекретные настройки приложения.

    Источники: env (SELCTEL_*), затем config.toml.
    """

    model_config = SettingsConfigDict(
        env_prefix="SELCTEL_", env_file=".env", extra="ignore"
    )

    api_base_url: str = Field(
        default="https://api.selectel.ru",
        description="Базовый URL API Selectel",
    )
    identity_url: str = Field(
        default="https://cloud.api.selcloud.ru/identity/v3",
        description="URL сервиса IAM-авторизации",
    )
    refresh_interval: int = Field(
        default=60,
        ge=10,
        description="Интервал автообновления TUI, секунд",
    )
    router_id: str = Field(
        default="",
        description="ID ИИ-роутера (если не указан, берётся первый из списка)",
    )
    region: str = Field(
        default="",
        description="Регион/пул (необязательно, для совместимости)",
    )


class Credentials(BaseModel):
    """Учётные данные для доступа к API."""

    service_user: str = ""
    password: str = ""
    project_id: str = ""
    domain_id: str = ""
    static_token: str = ""


def config_dir() -> Path:
    """Каталог конфигурации (Linux: ~/.config, macOS: ~/Library/Application Support)."""
    return Path(user_config_dir(APP_NAME))


def data_dir() -> Path:
    """Каталог данных (Linux: ~/.local/share, macOS: ~/Library/Application Support)."""
    return Path(user_data_dir(APP_NAME))


def _config_file() -> Path:
    return config_dir() / "config.toml"


def _credentials_file() -> Path:
    return config_dir() / "credentials.json"


def load_settings() -> Settings:
    """Загрузить настройки: env > config.toml > значения по умолчанию.

    Дополнительные env-алиасы: SELCTEL_API_URL (для api_base_url).
    Некорректные значения (например, refresh_interval < 10 из старого
    конфига) не приводят к ошибке: поле приводится к допустимому значению.
    """
    base = _settings_from_env()
    cfg = _read_config_file()
    if not cfg:
        settings = base
    else:
        # Поля, заданные через env, имеют приоритет над файлом конфигурации.
        env_fields = {
            name: value
            for name, value in base.model_dump().items()
            if name in base.model_fields_set
        }
        settings = _validate_settings({**cfg, **env_fields})

    api_url = os.environ.get("SELCTEL_API_URL")
    if api_url:
        settings = settings.model_copy(update={"api_base_url": api_url})
    return settings


def _settings_from_env() -> Settings:
    """Настройки из переменных окружения (устойчиво к некорректным значениям)."""
    try:
        return Settings()
    except ValidationError:
        # Некорректное значение в env (например, SELCTEL_REFRESH_INTERVAL=5):
        # model_construct() не читает env и не валидирует — чистые дефолты.
        return Settings.model_construct()


def _validate_settings(data: dict[str, Any]) -> Settings:
    """Валидировать настройки; при ошибке починить и повторить."""
    try:
        return Settings.model_validate(data)
    except ValidationError:
        return Settings.model_validate(_sanitize_settings(data))


def _sanitize_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Привести некорректные значения к допустимым (refresh_interval >= 10)."""
    repaired = dict(data)
    interval = repaired.get("refresh_interval")
    if interval is not None:
        try:
            repaired["refresh_interval"] = max(10, int(interval))
        except (TypeError, ValueError):
            repaired["refresh_interval"] = 60
    return repaired


def save_settings(settings: Settings) -> None:
    """Сохранить настройки в config.toml."""
    path = _config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_config_file(path, settings.model_dump(exclude_defaults=True))


def _read_config_file() -> dict[str, Any]:
    path = _config_file()
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return dict(tomllib.load(fh))


def _write_config_file(path: Path, data: dict[str, Any]) -> None:
    try:
        import tomli_w
    except ImportError:  # pragma: no cover
        # tomli_w не установлен — пишем JSON (совместимый фолбэк)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return
    path.write_text(tomli_w.dumps(data))


def load_credentials() -> Credentials:
    """Загрузить секреты: env (SELCTEL_*) > файл credentials.json.

    Env-алиасы: SELCTEL_TOKEN (static_token), SELCTEL_SERVICE_USER,
    SELCTEL_PASSWORD, SELCTEL_PROJECT_ID, SELCTEL_DOMAIN_ID.
    """
    path = _credentials_file()
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            data: dict[str, Any] = json.load(fh)
    else:
        data = {}

    env_overrides = {
        "static_token": os.environ.get("SELCTEL_TOKEN"),
        "service_user": os.environ.get("SELCTEL_SERVICE_USER"),
        "password": os.environ.get("SELCTEL_PASSWORD"),
        "project_id": os.environ.get("SELCTEL_PROJECT_ID"),
        "domain_id": os.environ.get("SELCTEL_DOMAIN_ID"),
    }
    for name, value in env_overrides.items():
        if value is not None:
            data[name] = value
    return Credentials.model_validate(data)


def save_credentials(credentials: Credentials) -> None:
    """Сохранить секреты в файл credentials.json с правами 0600."""
    path = _credentials_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.model_dump_json(indent=2))
    _chmod_0600(path)


def _chmod_0600(path: Path) -> None:
    if os.name == "posix":  # pragma: no cover
        path.chmod(0o600)
