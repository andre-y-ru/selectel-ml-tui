"""Базовые тесты CLI."""

from __future__ import annotations

import subprocess
import sys

from click.testing import CliRunner

from selectel_ml_tui import __version__
from selectel_ml_tui.cli import main
from selectel_ml_tui.config import load_credentials, load_settings


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_main_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "selectel_ml_tui", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "doctor" in result.stdout
    assert "run" in result.stdout


def test_config_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("selectel_ml_tui.config.config_dir", lambda: tmp_path)
    monkeypatch.setattr("selectel_ml_tui.cli.config_dir", lambda: tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["config", "--path"])
    assert result.exit_code == 0
    assert str(tmp_path) in result.output


def test_config_show_masks_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("selectel_ml_tui.config.config_dir", lambda: tmp_path)
    monkeypatch.setattr("selectel_ml_tui.cli.config_dir", lambda: tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["config", "--show"])
    assert result.exit_code == 0
    assert "Static token" in result.output
    assert "секрет" not in result.output.lower()


def test_config_wizard_saves(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("selectel_ml_tui.config.config_dir", lambda: tmp_path)
    monkeypatch.setattr("selectel_ml_tui.cli.config_dir", lambda: tmp_path)
    input_data = "\n".join(
        [
            "https://api.example.test",  # API base URL
            "30",  # интервал обновления
            "gw-test",  # ID роутера
            "ru-3",  # регион
            "svc-user",  # сервисный пользователь
            "239633",  # домен (аккаунт)
            "7bf2d2a328494e25b13d05a1926ca75a",  # project id
            "secret-pass",  # пароль
            "secret-token",  # статический токен
        ]
    )
    runner = CliRunner()
    result = runner.invoke(main, ["config"], input=input_data)
    assert result.exit_code == 0, result.output
    assert "Сохранено" in result.output

    settings = load_settings()
    assert settings.router_id == "gw-test"
    assert settings.refresh_interval == 30
    assert settings.api_base_url == "https://api.example.test"
    assert settings.region == "ru-3"

    creds = load_credentials()
    assert creds.service_user == "svc-user"
    assert creds.domain_id == "239633"
    assert creds.project_id == "7bf2d2a328494e25b13d05a1926ca75a"
    assert creds.password == "secret-pass"
    assert creds.static_token == "secret-token"


def test_run_requires_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("selectel_ml_tui.config.config_dir", lambda: tmp_path)
    monkeypatch.setattr("selectel_ml_tui.cli.config_dir", lambda: tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["run"])
    assert result.exit_code == 1
    assert "не настроены" in result.output


def test_config_wizard_rejects_small_interval(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("selectel_ml_tui.config.config_dir", lambda: tmp_path)
    monkeypatch.setattr("selectel_ml_tui.cli.config_dir", lambda: tmp_path)
    input_data = "\n".join(
        [
            "https://api.example.test",  # API base URL
            "5",  # интервал < 10 — будет отклонён
            "30",  # повторный ввод, валидный
            "gw-test",  # ID роутера
            "",  # регион (оставить)
            "",  # сервисный пользователь (оставить)
            "",  # домен (оставить)
            "",  # project id (оставить)
            "",  # пароль (оставить)
            "",  # статический токен (оставить)
            "",  # хвостовая строка (CliRunner отбрасывает последний пустой элемент)
        ]
    )
    runner = CliRunner()
    result = runner.invoke(main, ["config"], input=input_data)
    assert result.exit_code == 0, result.output
    assert "не может быть меньше 10" in result.output
    settings = load_settings()
    assert settings.refresh_interval == 30
