.PHONY: help install dev install-backend run run-customer run-owner dev-api test cov coverage \
	lint typecheck security format check test-backend coverage-backend \
	test-backend-postgres test-admin coverage-admin test-mobile coverage-mobile \
	test-sqlserver test-matrix test-all clean refresh-db

# Prefer the project virtualenv so Make targets do not depend on the caller's
# shell having activated it. An explicit `make PYTHON=...` still wins.
PYTHON ?= $(if $(wildcard .venv/bin/python),$(CURDIR)/.venv/bin/python,python3)
RUFF ?= $(PYTHON) -m ruff
MYPY ?= $(PYTHON) -m mypy
BANDIT ?= $(PYTHON) -m bandit
PIP_AUDIT ?= $(PYTHON) -m pip_audit
TOX ?= $(PYTHON) -m tox

help:  ## Prikazi dostupne komande
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Instaliraj runtime zavisnosti
	$(PYTHON) -m pip install -r requirements.txt

dev:  ## Instaliraj dev zavisnosti + pre-commit hookove
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pre_commit install

install-backend:  ## Instaliraj backend u editable rezimu (kao CI)
	$(PYTHON) -m pip install -e "backend[dev]"

run:  ## Pokreni staru kombinovanu aplikaciju (kolekcija)
	$(PYTHON) main.py

run-customer:  ## Pokreni kupacku aplikaciju
	$(PYTHON) customer_app.py

run-owner:  ## Pokreni vlasnicku aplikaciju
	$(PYTHON) owner_app.py

dev-api:  ## Pokreni API sa workerima (migracije + notifications + expiry)
	./scripts/dev_api.sh

test:  ## Pokreni testove
	$(PYTHON) -m pytest

cov:  ## Testovi + izvestaj o pokrivenosti (100% gate)
	$(PYTHON) -m pytest --cov --cov-report=term-missing

coverage: cov  ## Alias za cov

test-backend:  ## Pokreni backend testove (SQLite)
	cd backend && $(PYTHON) -m pytest

coverage-backend:  ## Backend testovi + coverage (SQLite)
	cd backend && $(PYTHON) -m pytest --cov=app --cov-branch --cov-report=term-missing

test-backend-postgres:  ## Backend testovi + coverage nad lokalnim PostgreSQL
	./scripts/test_backend_postgres.sh

test-admin:  ## Admin lint, typecheck, unit coverage, build i Playwright E2E
	cd admin && npm audit --audit-level=high && npm run lint && npm run typecheck && npm run test:coverage && npm run build && npm run test:e2e

coverage-admin:  ## Admin logic coverage (100% gate)
	cd admin && npm run test:coverage

test-mobile:  ## Mobile lint, typecheck, unit coverage i web export
	cd mobile && npm audit --audit-level=high && npm run lint && npm run typecheck && npm run test:coverage && npm run export:web

coverage-mobile:  ## Mobile logic coverage (100% gate)
	cd mobile && npm run test:coverage

test-sqlserver:  ## SQL Server E2E (preskace se ako Docker nije dostupan)
	./scripts/test_sqlserver.sh

test-matrix:  ## Pokreni root testove na svim dostupnim Python verzijama
	$(TOX)

test-all: check coverage security test-backend test-backend-postgres test-admin test-mobile test-sqlserver  ## Sve provere

lint:  ## Provera formata i lint pravila (bez izmena)
	$(RUFF) check .
	$(RUFF) format --check .

typecheck:  ## Provera tipova
	$(MYPY) .

security:  ## Bandit + provera zavisnosti
	$(BANDIT) -q -c pyproject.toml -r .
	./scripts/audit_requirements.sh

format:  ## Formatiraj i sredi importe
	$(RUFF) check --fix .
	$(RUFF) format .

check: lint typecheck test  ## Sve provere koje vrti i CI

clean:  ## Obrisi privremene fajlove
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov build dist *.egg-info

refresh-db:  ## Ponovo preuzmi Scryfall bazu
	$(PYTHON) downloader.py
