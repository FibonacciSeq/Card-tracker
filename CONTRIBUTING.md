# Contributing

Thanks for helping improve Card Tracker. This project is a desktop Tkinter
application with a local SQLite catalog and shop database, so changes should
preserve offline operation and existing user data.

## Development setup

Requirements: Python 3.10–3.14 and Tkinter.

```bash
git clone https://github.com/aleksacvele/card-tracker.git
cd card-tracker

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
pre-commit install
```

Run the apps:

```bash
python owner_app.py       # add stock first
python customer_app.py    # browse stock and submit an order
python main.py            # original combined collection app
```

## Quality gates

Before opening a pull request, run:

```bash
make check          # Ruff (lint + format) + mypy + pytest
make security       # Bandit + pip-audit
```

The individual commands are:

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
- `my_collection.json`, `my_collection.xlsx`
- `scryfall.db`, `scryfall_default_cards.jsonl`, `temp_scryfall_data.jsonl.gz`
- `image_cache/`

These paths are already in `.gitignore`. If you need sample data, use
`examples/sample_collection.json` or create synthetic fixtures in `tests/`.

## Pull requests

- Keep each PR focused and describe the user-visible change.
- Include the commands you ran and note any platform-specific UI testing.
- Update `README.md` when behaviour, setup, or commands change.
- Make sure CI is green. The required jobs are lint/format, type check,
  security, tests (Python 3.10–3.14), and the import smoke test.

For security issues, follow [`SECURITY.md`](SECURITY.md) instead of opening a
public issue.
