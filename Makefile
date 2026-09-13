.PHONY: help install dev run test cov lint format check clean refresh-db

help:  ## Prikazi dostupne komande
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Instaliraj runtime zavisnosti
	pip install -r requirements.txt

dev:  ## Instaliraj dev zavisnosti + pre-commit hookove
	pip install -r requirements-dev.txt
	pre-commit install

run:  ## Pokreni aplikaciju
	python main.py

test:  ## Pokreni testove
	pytest

cov:  ## Testovi + izvestaj o pokrivenosti
	pytest --cov --cov-report=term-missing

lint:  ## Provera koda (bez izmena)
	ruff check .

format:  ## Formatiraj i sredi importe
	ruff check --fix .
	ruff format .

check: lint test  ## Sve provere koje vrti i CI

clean:  ## Obrisi privremene fajlove
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov build dist *.egg-info

refresh-db:  ## Ponovo preuzmi Scryfall bazu
	python downloader.py
