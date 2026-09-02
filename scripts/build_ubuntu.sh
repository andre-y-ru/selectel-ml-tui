#!/usr/bin/env bash
# Сборка однофайлового исполняемого файла selectel-ml-tui для Linux (Ubuntu).
set -euo pipefail

cd "$(dirname "$0")/.."
make build
echo "Готово: dist/selectel-ml-tui (запуск: ./dist/selectel-ml-tui doctor)"