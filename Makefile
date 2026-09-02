PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: help venv install run test lint typecheck format build clean install-ubuntu install-macos

help: ## Показать доступные цели
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Создать виртуальное окружение
	$(PYTHON) -m venv $(VENV)

install: venv ## Установить проект в режиме разработки
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

run: ## Запустить TUI-приложение
	$(PY) -m selectel_ml_tui run

test: ## Запустить тесты
	$(PY) -m pytest -v --cov=selectel_ml_tui --cov-report=term-missing

lint: ## Проверить стиль кода (ruff)
	$(VENV)/bin/ruff check .

typecheck: ## Проверить типы (mypy)
	$(VENV)/bin/mypy src

format: ## Форматировать код (ruff format)
	$(VENV)/bin/ruff format .

build: ## Собрать однофайловый исполняемый файл (PyInstaller)
	$(PIP) install pyinstaller
	$(PY) -m PyInstaller --noconfirm --clean --onefile --console \
	    --name selectel-ml-tui \
	    --collect-all textual \
	    --paths src \
	    src/selectel_ml_tui/__main__.py

install-ubuntu: ## Установить на Ubuntu (apt)
	./scripts/install_ubuntu.sh

install-macos: ## Установить на macOS (Homebrew)
	./scripts/install_macos.sh

clean: ## Удалить артефакты и виртуальное окружение
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist *.egg-info