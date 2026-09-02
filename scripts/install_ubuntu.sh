#!/usr/bin/env bash
# Установка selectel-ml-tui на Ubuntu (22.04+)
set -euo pipefail

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip

cd "$(dirname "$0")/.."
make install

echo "Готово. Запуск: make run или .venv/bin/selectel-ml-tui run"