"""Тесты платформенно-зависимой диагностики (platform.py)."""

from __future__ import annotations

from selectel_ml_tui import platform as pl


def test_platform_info_fields(monkeypatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    info = pl.get_platform_info()
    assert info.system in ("Linux", "Darwin", "Windows")
    assert info.term == "xterm-256color"
    assert info.lang == "ru_RU.UTF-8"
    assert info.utf8 is True
    assert info.python_version


def test_check_environment_ok(monkeypatch) -> None:
    monkeypatch.setenv("TERM", "tmux-256color")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    results = {c.name: c for c in pl.check_environment()}
    assert all(r.ok for r in results.values())
    assert results["python"].ok


def test_check_environment_warns_without_term_and_lang(monkeypatch) -> None:
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    results = {c.name: c for c in pl.check_environment()}
    assert not results["TERM"].ok
    assert not results["LANG"].ok


def test_check_environment_warns_wrong_term(monkeypatch) -> None:
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("LANG", "C")
    results = {c.name: c for c in pl.check_environment()}
    assert not results["TERM"].ok


def test_min_python_version() -> None:
    assert pl.MIN_PYTHON == (3, 10)
