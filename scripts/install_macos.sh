#!/usr/bin/env bash
# Установка selectel-ml-tui на macOS (Homebrew)
set -euo pipefail

brew install python@3.11

cd "$(dirname "$0")/.."
make install

echo "Готово. Запуск: make run или .venv/bin/selectel-ml-tui run"