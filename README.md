# Card-tracker

A desktop app for browsing the [Scryfall](https://scryfall.com) card database and
keeping track of a Magic: The Gathering collection — with prices converted to EUR
and RSD, foil/non-foil tracking, and Excel import/export.

Built with Python + Tkinter.

## Features

- **Search** the full Scryfall bulk database through a local SQLite FTS5 index, ranked by relevance
- **Collection tracking** with separate foil and non-foil entries, quantities, and running totals
- **Pricing** in EUR and RSD, using live exchange rates with a per-tier retail margin
- **Import** decklists as plain text (`4 Lightning Bolt (LEB) 161`) or from Excel
- **Export** your collection to a formatted `.xlsx` with totals
- **Card previews** on hover, cached to disk

## SQL Server backend

Alongside the local SQLite index there is a SQL Server database for running
this as a shop: stock levels, customer orders, and an automatic restock list
that replaces checking spreadsheets by hand. It ships as numbered T-SQL
scripts plus a scheduled job that refreshes the Scryfall catalog and imports
spreadsheets from a drop folder.

See [`database/README.md`](database/README.md).

## Requirements

- Python **3.10+**
- Tkinter — bundled with Python on Windows/macOS; on Debian/Ubuntu: `sudo apt install python3-tk`

## Getting started

```bash
git clone https://github.com/aleksacvele/card-tracker.git
cd card-tracker

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python main.py
```

On first launch the app downloads the Scryfall bulk data file (~2 GB uncompressed)
and builds a local SQLite index. This takes a few minutes. Subsequent launches
open the index directly and start immediately — cards are read a page at a
time rather than loaded into memory, so the app stays at tens of MB of RAM
regardless of database size.

If you already have an index from an older version, it is detected by schema
version and rebuilt automatically on next launch.

## Usage

| Tab | What it does |
| --- | --- |
| **Sve Kartice** | Search the database; add a card as foil or non-foil |
| **Moja Kolekcija** | Review the collection, see totals, save to JSON or Excel |
| **Import Lista** | Paste a decklist or import an `.xlsx` file |

### Search

Search runs against an FTS5 index over card name, set, type line and collector
number. Every term must match (`lightning beta` finds only Bolts from Beta).

It tries word-prefix matching first, which is fast and ranked by relevance
(bm25), so `light` finds *Lightning Bolt* and the closest matches come first.
If a prefix query returns nothing, it falls back to a trigram index that
matches anywhere inside a word — so `ning` still finds *Lightning Bolt*. The
trigram index is what makes the on-disk index roughly twice the size; that is
the trade for mid-word search.

### Decklist format

The text importer accepts the common export formats:

```
4 Forest
2 Lightning Bolt
1 Lightning Bolt (LEB) 161
// lines starting with // or # are ignored
```

When a set code and collector number are given, that exact printing is matched.
Otherwise the cheapest printing of that name is used.

### Collection file

The collection is stored as JSON (`my_collection.json` by default) and saved
automatically on every add or remove. See
[`examples/sample_collection.json`](examples/sample_collection.json) for the format.

## Development

```bash
make dev      # install dev dependencies + pre-commit hooks
make test     # run the test suite
make cov      # tests with a coverage report
make lint     # ruff checks
make format   # apply ruff autofixes + formatting
make check    # everything CI runs
make help     # list all targets
```

Without `make`:

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

Tests pin exchange rates and assert that nothing touches the network, so the
suite is fast, offline, and deterministic.

## Project layout

```
main.py               Entry point: downloads data if needed, starts the UI
downloader.py         Fetches and decompresses Scryfall bulk data
collection.py         Collection persistence (JSON/Excel)
importer.py           Decklist parsing and database matching
models/card.py        Card model: parsing, pricing, identity, sorting
services/
  sqlite_database.py  SQLite-backed card database with FTS search (used by the app)
  card_database.py    Plain JSONL-backed database, kept in memory (no index)
  card_lookup.py      Lookup contract shared by both database backends
  card_query.py       Lazy, pageable result set over SQLite
  card_collection.py  Collection operations and totals
  mssql.py            SQL Server connection (pyodbc or pymssql)
  spreadsheet.py      Header detection shared by the spreadsheet importers
  pricing.py          Exchange rates and RSD retail pricing
  excel_importer.py   Excel -> collection
  excel_exporter.py   Collection -> Excel
  image_loader.py     Threaded image fetching with an LRU disk cache
ui/
  app.py              Main window and tabs
  card_list.py        Paginated card list with hover previews
tools/
  etl_scryfall.py     Scryfall bulk file -> SQL Server staging -> catalog
  etl_stock.py        Excel/CSV drop folder -> SQL Server staging -> stock
database/             SQL Server schema, procedures, views and Agent job
tests/                Test suite
```

## Pricing

USD prices from Scryfall are converted to EUR, then to RSD using live rates from
[open.er-api.com](https://open.er-api.com), with a margin that depends on the
card's value (a flat 50 RSD floor for cards under €0.35, a fixed markup up to
€10, then a percentage above that). Final prices are rounded up to the nearest
10 RSD. Rates are fetched once per day and fall back to hardcoded defaults when
the API is unreachable.

## License

[MIT](LICENSE)
