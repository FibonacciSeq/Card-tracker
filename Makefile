.PHONY: help install dev run run-customer run-owner test cov lint typecheck security format check clean refresh-db

PYTHON ?= python3
RUFF ?= $(PYTHON) -m ruff
MYPY ?= $(PYTHON) -m mypy
BANDIT ?= $(PYTHON) -m bandit
PIP_AUDIT ?= $(PYTHON) -m pip_audit

help:  ## Prikazi dostupne komande
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Instaliraj runtime zavisnosti
	$(PYTHON) -m pip install -r requirements.txt

dev:  ## Instaliraj dev zavisnosti + pre-commit hookove
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pre_commit install

run:  ## Pokreni staru kombinovanu aplikaciju (kolekcija)
	$(PYTHON) main.py

run-customer:  ## Pokreni kupacku aplikaciju
	$(PYTHON) customer_app.py

run-owner:  ## Pokreni vlasnicku aplikaciju
	$(PYTHON) owner_app.py

test:  ## Pokreni testove
	$(PYTHON) -m pytest

cov:  ## Testovi + izvestaj o pokrivenosti
	$(PYTHON) -m pytest --cov --cov-report=term-missing

lint:  ## Provera formata i lint pravila (bez izmena)
	$(RUFF) check .
	$(RUFF) format --check .

typecheck:  ## Provera tipova
	$(MYPY) .

security:  ## Bandit + provera zavisnosti
	$(BANDIT) -q -c pyproject.toml -r .
	$(PIP_AUDIT) -r requirements.txt --progress-spinner off

format:  ## Formatiraj i sredi importe
	$(RUFF) check --fix .
	$(RUFF) format .

check: lint typecheck test  ## Sve provere koje vrti i CI

clean:  ## Obrisi privremene fajlove
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov build dist *.egg-info

refresh-db:  ## Ponovo preuzmi Scryfall bazu
	$(PYTHON) downloader.py
