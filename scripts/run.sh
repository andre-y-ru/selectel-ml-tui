#!/usr/bin/env bash
# Запуск selectel-ml-tui с корректным окружением терминала.
# Использование: scripts/run.sh [doctor|run|...]
set -euo pipefail

cd "$(dirname "$0")/.."

# Подстраховка для минималистичных терминалов (tmux/screen, ssh).
if [[ -z "${TERM:-}" ]]; then
    export TERM=xterm-256color
fi
if [[ -z "${LANG:-}" ]]; then
    export LANG=C.UTF-8
fi

if command -v uv >/dev/null 2>&1; then
    exec uv run selectel-ml-tui "$@"
elif command -v selectel-ml-tui >/dev/null 2>&1; then
    exec selectel-ml-tui "$@"
else
    echo "selectel-ml-tui не найден. Установите через 'pip install .' или 'uv sync'" >&2
    exit 1
fi