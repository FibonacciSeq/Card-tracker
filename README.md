# Card-tracker

[![CI](https://github.com/FibonacciSeq/Card-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/FibonacciSeq/Card-tracker/actions/workflows/ci.yml)

A desktop shop for Magic: The Gathering cards, split into a **customer** app
and an **owner** app on top of the [Scryfall](https://scryfall.com) database —
with prices converted to EUR and RSD, foil/non-foil tracking, stock and order
management, plus Excel import/export for the original collection tool.

Built with Python + Tkinter.

> **Platform rewrite in progress.** The `backend/` FastAPI service and the
> `admin/` vendor web app are the new multi-vendor platform; see
> [`STATUS.md`](STATUS.md) for what is implemented, verification results,
> and the roadmap. The Tkinter apps described below remain the legacy
> single-shop desktop version.

## Features

- **Search** the full Scryfall bulk database through a local SQLite FTS5 index, ranked by relevance
- **Collection tracking** with separate foil and non-foil entries, quantities, and running totals
- **Full-market ordering** with backorders for cards that are not currently in stock
- **Pricing** in EUR and RSD, using live exchange rates with a per-tier retail margin
- **Import** decklists as plain text (`4 Lightning Bolt (LEB) 161`) or from Excel
- **Export** your collection to a formatted `.xlsx` with totals
- **Card previews** on hover, cached to disk

## Customer and owner apps

The shop is split into two separate programs that share one local SQLite
database (`cardtracker_shop.db`):

| Program | Start it with | What it does |
| --- | --- | --- |
| **Owner** | `python owner_app.py` | Add cards to stock, change quantities/prices, review orders, and mark them as *ordered*, *fulfilled*, *delivered* or *cancelled*. Missing cards and quantities are highlighted in red |
| **Customer** | `python customer_app.py` | Search the full Scryfall market, see RSD prices and availability, build a cart, and submit an order with contact details |

The customer app lists every card in the market, not only the owner's current
stock. Cards that are not in stock can still be ordered; the owner sees them as
missing and can add the required copies before delivery. Both programs use the
same `ShopDatabase` service and the same pricing rules as the rest of the
project.

### Order life cycle

```
NEW  ->  ORDERED  ->  FULFILLED  ->  DELIVERED
  \          \            \
   +----------+------------+------->  CANCELLED
```

* **Nova** — the customer submitted the order. Available copies are reserved;
  anything beyond current stock is recorded as a supplier backorder.
* **Karte naručene** — the owner has ordered/reserved the cards with a supplier.
* **Ispunjeno** — the cards are ready; they stay reserved for this customer.
* **Isporučeno** — the cards leave stock, the quantity is deducted and the order closes.
* **Otkazano** — the reservation is released and the cards become available again.

The customer app shows the full Scryfall market, including cards that have no
stock row at all. Ordering more than is available is allowed; the excess stays
reserved for that customer but cannot be delivered until the owner adds enough
stock. When a customer orders a card that was never in stock, the shop creates
a zero-quantity SKU for it, so the missing card and the missing quantity appear
in red in the owner's stock table and order details. Physical copies cannot be promised twice,
and the owner cannot reduce stock below the number of reserved copies. The SQL
Server schema in `database/` remains the reference for the full multi-user
shop; the two desktop programs use a local SQLite mirror so they run without
any server setup.

Set `CARDTRACKER_SHOP_DB` to use a different shop database file (useful if the
owner and customer apps run from different folders).

The local shop database contains customer contact details. It is deliberately
git-ignored; back it up securely and do not attach it to issues. See
[`SECURITY.md`](SECURITY.md) for the full data-handling notes.

## SQL Server backend

Alongside the local SQLite index there is a SQL Server database for running
this as a shop: stock levels, customer orders, and an automatic restock list
that replaces checking spreadsheets by hand. It ships as numbered T-SQL
scripts plus a scheduled job that refreshes the Scryfall catalog and imports
spreadsheets from a drop folder.

See [`database/README.md`](database/README.md).

## Requirements

- Python **3.10–3.14**
- Tkinter — bundled with Python on Windows/macOS; on Debian/Ubuntu: `sudo apt install python3-tk`

## Getting started

```bash
git clone https://github.com/FibonacciSeq/Card-tracker.git
cd card-tracker

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

python owner_app.py      # manage stock and orders
python customer_app.py   # browse the full market and order
```

Both shop apps share the local Scryfall card index. The first launch of either
app builds that index (or downloads it when it is missing), the same as the
original combined app; later launches open the index directly.

The original combined collection app is still available with `python main.py`.

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
make dev        # install dev dependencies + pre-commit hooks
make test       # run the test suite
make cov        # tests with branch coverage (fails below 80%)
make lint       # ruff check + format check
make typecheck  # mypy
make security   # bandit + pip-audit
make format     # apply ruff autofixes + formatting
make check      # lint + typecheck + tests (the main CI gate)
make help       # list all targets
```

Without `make`:

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
mypy .
pytest --cov --cov-report=term-missing
bandit -q -c pyproject.toml -r .
pip-audit -r requirements.txt
```

The pre-commit configuration runs Ruff, formatting, mypy, Bandit, and the
standard file hygiene hooks. Install it once with `pre-commit install`.

Tests pin exchange rates and assert that nothing touches the network, so the
suite is fast, offline, and deterministic. UI code is excluded from the
coverage denominator; the service, model, and importer layers must stay above
the 80% threshold configured in `pyproject.toml`.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow and
[`SECURITY.md`](SECURITY.md) for vulnerability reporting and data-handling
notes.

## Project layout

```
customer_app.py       Entry point: customer shop window (market, cart, checkout)
owner_app.py          Entry point: owner window (stock and orders)
main.py               Entry point: original combined collection app
downloader.py         Fetches and decompresses Scryfall bulk data
collection.py         Collection persistence (JSON/Excel)
importer.py           Decklist parsing and database matching
models/card.py        Card model: parsing, pricing, identity, sorting
services/
  shop_database.py    Shared shop database: stock, reservations, orders, contacts
  catalog_bootstrap.py  Shared Scryfall index setup for both shop apps
  sqlite_database.py  SQLite-backed card database with FTS search (used by the app)
  card_database.py    Plain JSONL-backed database, kept in memory (no index)
  card_lookup.py      Lookup contract shared by both database backends
  card_query.py       Lazy, pageable result set over SQLite
  card_collection.py  Collection operations and totals
  mssql.py            SQL Server connection (pyodbc or pymssql)
  mssql_database.py   SQL Server-backed catalog (optional backend)
  spreadsheet.py      Header detection shared by the spreadsheet importers
  pricing.py          Exchange rates and RSD retail pricing
  excel_importer.py   Excel -> collection
  excel_exporter.py   Collection -> Excel
  image_loader.py     Threaded image fetching with a bounded disk cache
ui/
  customer_app.py     Customer window: full market search, cart, checkout dialog
  owner_app.py        Owner window: stock editing and order statuses
  shop_widgets.py     Shared RSD/date formatting and card preview
  dispatch.py         Thread-safe worker -> Tk main-thread callback bridge
  app.py              Original combined collection window
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
