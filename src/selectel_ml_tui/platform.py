"""Платформенно-зависимые проверки и диагностика окружения.

Изолирует код, зависящий от ОС и терминала (Python, TERM, LANG, кодировка),
чтобы его можно было тестировать на любой платформе.
"""

from __future__ import annotations

import os
import platform as _platform
import sys
from dataclasses import dataclass

MIN_PYTHON = (3, 10)

# TERM-значения, которые Textual считает пригодными для TUI.
_SUPPORTED_TERM_MARKERS = ("xterm", "linux", "tmux", "screen")


@dataclass(frozen=True)
class PlatformInfo:
    """Снимок окружения, на котором запущено приложение."""

    system: str
    python_version: str
    term: str
    lang: str
    encoding: str
    utf8: bool


@dataclass(frozen=True)
class CheckResult:
    """Результат одной проверки окружения."""

    ok: bool
    name: str
    detail: str


def get_platform_info() -> PlatformInfo:
    """Собрать информацию об ОС и терминале."""
    encoding = sys.stdout.encoding or sys.getdefaultencoding() or ""
    return PlatformInfo(
        system=_platform.system(),
        python_version=_platform.python_version(),
        term=os.environ.get("TERM", ""),
        lang=os.environ.get("LANG", ""),
        encoding=encoding,
        utf8=encoding.lower().replace("-", "").replace("_", "") == "utf8",
    )


def check_environment() -> list[CheckResult]:
    """Проверить окружение: Python, TERM, LANG, кодировку UTF-8."""
    info = get_platform_info()
    major, minor = (int(x) for x in _platform.python_version_tuple()[:2])
    checks: list[CheckResult] = [
        CheckResult(
            ok=(major, minor) >= MIN_PYTHON,
            name="python",
            detail=(
                f"{info.python_version} (требуется >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})"
            ),
        ),
        CheckResult(
            ok=bool(info.term)
            and any(marker in info.term for marker in _SUPPORTED_TERM_MARKERS),
            name="TERM",
            detail=info.term or "не задан (рекомендуется xterm-256color)",
        ),
        CheckResult(
            ok=bool(info.lang),
            name="LANG",
            detail=info.lang or "не задан (рекомендуется *.UTF-8)",
        ),
        CheckResult(
            ok=info.utf8,
            name="UTF-8",
            detail=f"{info.encoding} (stdout)",
        ),
    ]
    return checks
