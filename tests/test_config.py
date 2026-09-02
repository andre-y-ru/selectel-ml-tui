"""Тесты модуля конфигурации."""

from __future__ import annotations

from selectel_ml_tui.config import (
    Credentials,
    Settings,
    load_credentials,
    load_settings,
    save_credentials,
    save_settings,
)


def test_settings_defaults() -> None:
    settings = load_settings()
    assert settings.api_base_url == "https://api.selectel.ru"
    assert settings.refresh_interval >= 10


def test_save_settings_roundtrip(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.toml"
    monkeypatch.setattr("selectel_ml_tui.config._config_file", lambda: cfg_file)
    settings = Settings(router_id="gw-test", refresh_interval=30)
    save_settings(settings)
    loaded = load_settings()
    assert loaded.router_id == "gw-test"
    assert loaded.refresh_interval == 30


def test_load_settings_repairs_small_interval(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("refresh_interval = 5\n", encoding="utf-8")
    monkeypatch.setattr("selectel_ml_tui.config._config_file", lambda: cfg_file)
    settings = load_settings()
    assert settings.refresh_interval == 10


def test_load_settings_repairs_garbage_interval(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('refresh_interval = "abc"\n', encoding="utf-8")
    monkeypatch.setattr("selectel_ml_tui.config._config_file", lambda: cfg_file)
    settings = load_settings()
    assert settings.refresh_interval == 60


def test_load_settings_ignores_bad_env_interval(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.toml"
    monkeypatch.setattr("selectel_ml_tui.config._config_file", lambda: cfg_file)
    monkeypatch.setenv("SELCTEL_REFRESH_INTERVAL", "5")
    settings = load_settings()
    assert settings.refresh_interval == 60


def test_credentials_defaults() -> None:
    creds = Credentials()
    assert creds.service_user == ""
    assert creds.static_token == ""


def test_settings_env_api_url(monkeypatch, tmp_path) -> None:
    cfg_file = tmp_path / "config.toml"
    monkeypatch.setattr("selectel_ml_tui.config._config_file", lambda: cfg_file)
    monkeypatch.setenv("SELCTEL_API_URL", "https://api.example.test")
    settings = load_settings()
    assert settings.api_base_url == "https://api.example.test"


def test_credentials_env(monkeypatch, tmp_path) -> None:
    cred_file = tmp_path / "credentials.json"
    monkeypatch.setattr("selectel_ml_tui.config._credentials_file", lambda: cred_file)
    monkeypatch.setenv("SELCTEL_TOKEN", "tok123")
    monkeypatch.setenv("SELCTEL_SERVICE_USER", "svc-user")
    monkeypatch.setenv("SELCTEL_DOMAIN_ID", "239633")
    creds = load_credentials()
    assert creds.static_token == "tok123"
    assert creds.service_user == "svc-user"
    assert creds.domain_id == "239633"


def test_credentials_file_precedence(monkeypatch, tmp_path) -> None:
    cred_file = tmp_path / "credentials.json"
    monkeypatch.setattr("selectel_ml_tui.config._credentials_file", lambda: cred_file)
    save_credentials(Credentials(static_token="from-file", service_user="file-user"))
    monkeypatch.setenv("SELCTEL_TOKEN", "from-env")
    creds = load_credentials()
    # env имеет приоритет над файлом
    assert creds.static_token == "from-env"
    assert creds.service_user == "file-user"
