# Contributing

Thanks for helping improve Card Tracker. The repository contains the legacy
Tkinter desktop app and the multi-vendor platform (`backend/`, `admin/`, and
`mobile/`). Changes should preserve offline operation and existing local user
data for the desktop app, and keep the platform API as the single source of
truth for the web and mobile clients.

## Development setup

The legacy desktop app requires Python 3.10–3.14 and Tkinter.

```bash
git clone https://github.com/aleksacvele/card-tracker.git
cd card-tracker

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
pre-commit install
```

Run the legacy apps:

```bash
python owner_app.py       # add stock first
python customer_app.py    # browse stock and submit an order
python main.py            # original combined collection app
```

The platform components have separate setup instructions:

- [`backend/README.md`](backend/README.md) — FastAPI API, migrations, demo seed,
  PostgreSQL/Compose, RLS, workers.
- [`admin/README.md`](admin/README.md) — Vite shop admin, Playwright, security
  headers.
- [`mobile/README.md`](mobile/README.md) — Expo customer app, API host
  resolution, guest flow, current scope.

## Quality gates

Before opening a pull request, run the checks for the parts you changed. The
legacy desktop gate is:

```bash
make check          # Ruff (lint + format) + mypy + pytest
make security       # Bandit + pip-audit
```

The platform checks are:

```bash
# From the repository root
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/mypy app tests
../.venv/bin/python -m pytest

cd ../admin
npm run lint
npm run typecheck
npm run build
npm run test:e2e

cd ../mobile
npm run lint
npm run typecheck
npm run export:web
npm run doctor
```

The individual legacy commands are:

```bash
ruff check .
ruff format --check .
mypy .
pytest --cov --cov-report=term-missing
bandit -q -c pyproject.toml -r .
pip-audit -r requirements.txt
```

Coverage is branch-aware and has an 80% minimum for the non-UI modules. Add
tests for behaviour changes, especially order-state transitions, stock
reservations, contact validation, and database migrations.

## Code guidelines

- Keep the service layer free of Tkinter imports; UI code lives under `ui/`.
- Never call Tk widgets or `widget.after` from a worker thread. Use
  `ui.dispatch.TkDispatcher` (it queues work onto the Tk main thread).
- Keep SQL parameterized. Static SQL fragments assembled from fixed tuples are
  the only exception; Bandit's `B608` heuristic is skipped globally for those
  reviewed cases, so a new dynamic query needs an explicit review.
- Validate and bound user input before writing it to SQLite.
- Prefer small, typed functions and explicit exception handling. Log failures
  with context instead of silently swallowing them.
- Preserve the existing local database format. Add a schema version bump and a
  migration path when changing the shop database.

## Data and generated files

Do not commit:

- `cardtracker_shop.db*` (customer contact data)
- `cardtracker_platform.db*` (platform customer data)
- `my_collection.json`, `my_collection.xlsx`
- `scryfall.db`, `scryfall_default_cards.jsonl`, `temp_scryfall_data.jsonl.gz`
- `image_cache/`
- `node_modules/`, `mobile/.expo/`, `mobile/dist/`

These paths are already in `.gitignore`. If you need sample data, use
`examples/sample_collection.json` or create synthetic fixtures in `tests/`.

## Pull requests

- Keep each PR focused and describe the user-visible change.
- Include the commands you ran and note any platform-specific UI testing.
- Update the relevant README, `STATUS.md`, or mobile app docs when behaviour,
  setup, or commands change.
- Make sure CI is green. The required jobs cover the legacy desktop checks,
  backend SQLite/PostgreSQL tests, admin build and Playwright, and mobile
  lint/typecheck/web export.

For security issues, follow [`SECURITY.md`](SECURITY.md) instead of opening a
public issue.
