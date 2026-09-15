# Card-tracker — SQL Server database

Replaces manual checking in Excel/CSV with a real database: what's in stock,
what customers are waiting for, and what needs ordering — computed rather than
eyeballed.

## What's in here

Run the numbered scripts in order in SSMS. Every script is idempotent, so
re-running is safe.

| Script | What it creates |
| --- | --- |
| `01_database_and_schemas.sql` | Database + the six schemas |
| `02_tables_catalog.sql` | Card catalog, price history, exchange rates |
| `03_tables_inventory.sql` | Conditions, stock, stock movement ledger |
| `04_tables_sales.sql` | Customers, orders, order lines, allocations |
| `05_tables_planning_and_etl.sql` | Reorder rules, load audit, staging tables |
| `06_functions.sql` | RSD retail pricing, parsing helpers |
| `07_views.sql` | Stock on hand, open demand, **restock suggestion** |
| `08_procedures_inventory.sql` | `usp_AdjustStock` |
| `09_procedures_sales.sql` | Order creation, allocation, delivery |
| `10_procedures_etl.sql` | Scryfall catalog merge |
| `11_procedures_stock_import.sql` | Spreadsheet import with validation |
| `12_agent_job.sql` | The scheduled job (**edit the paths at the top first**) |

Then `tests/01_end_to_end.sql` exercises the whole flow and fails loudly if
anything is wrong.

## Schemas

- **`catalog`** — reference data from Scryfall: what a card *is*, and what it costs
- **`inv`** — stock: what you *have*
- **`sales`** — customers, orders, allocations: what you *owe*
- **`purchasing`** — reorder rules: what you should *buy*
- **`staging`** — raw loaded rows, before validation
- **`etl`** — load history and rejected rows

(`purchasing` rather than `plan` because `PLAN` is a reserved T-SQL keyword.)

## The three questions it answers

```sql
-- 1. What do I have, and how much of it is actually free?
SELECT * FROM inv.vw_StockOnHand WHERE QuantityAvailable > 0;

-- 2. What do customers want that I haven't reserved yet?
SELECT * FROM sales.vw_OpenDemand ORDER BY PlacedUtc;

-- 3. What should I order?  <- this is the one that replaces the spreadsheet
SELECT * FROM purchasing.vw_RestockSuggestion
WHERE QuantityToOrder > 0
ORDER BY QuantityToOrder DESC;
```

`vw_RestockSuggestion` takes the larger of two needs per card:

1. **Customer demand** you can't cover from free stock
2. **Stock level** — if available has dropped below a reorder rule's
   `MinQuantity`, top it back up to `TargetQuantity`

A card only appears when something is genuinely needed.

## Two rules the schema enforces

**Stock quantity is never set directly.** Every change goes through
`inv.usp_AdjustStock`, which writes to `inv.StockMovement` in the same
transaction. You can always answer "where did these 12 copies come from".

```sql
EXEC inv.usp_AdjustStock
    @CardId = 42, @QuantityDelta = 10,
    @MovementType = N'PURCHASE', @UnitCostRsd = 200;
```

**Reserved stock can't be taken away.** Once stock is allocated to an order,
`usp_AdjustStock` refuses any adjustment that would drop below the allocated
quantity, so you can't accidentally sell the same card twice.

## Allocation

`sales.usp_AllocateStock` reserves free stock against open order lines,
oldest order first. It deliberately spends the *worst acceptable* condition
first — if a customer will take LP, they get LP, and your NM copies stay
available for customers who ask for NM.

```sql
EXEC sales.usp_AllocateStock;                 -- all open orders
EXEC sales.usp_AllocateStock @OrderId = 7;    -- just one
EXEC sales.usp_DeliverOrderLine @OrderLineId = 12;   -- ships + decrements stock
```

## Pricing

`catalog.fn_RetailPriceRsd` is the same margin ladder as `services/pricing.py`
— flat 50 RSD under €0.35, fixed markups to €10, percentages above — rounded
up to the nearest 10 RSD. Verified against the Python implementation across
420 prices.

It computes in `DECIMAL`, not `FLOAT`, so it doesn't have the rounding
artifact the Python version has (`20.00 EUR` at some rates lands a tier 10 RSD
high there).

`inv.fn_RetailPriceForCondition` applies the condition factor on top
(NM 100%, LP 85%, MP 70%, HP 50%, DMG 30%) — edit `inv.Condition` to change them.

## The scheduled job

`12_agent_job.sql` creates **CardTracker - Dnevno osvežavanje**, daily at 04:00:

1. **Refresh the Scryfall catalog** — `python -m tools.etl_scryfall`
2. **Import stock from the drop folder** — `python -m tools.etl_stock`
3. **Check the results** — fails the job if any load failed

Steps 1 and 2 both continue on failure so one broken source doesn't block the
other; step 3 decides whether the job as a whole passed.

**Before running it, edit the paths at the top of the script** — `@PythonExe`
and `@ProjectDir` point at a default Windows install.

Credentials come from `CARDTRACKER_MSSQL_*` environment variables, never from
command-line arguments — arguments show up in the process list and in the
Agent job history.

| Variable | Meaning |
| --- | --- |
| `CARDTRACKER_MSSQL_HOST` | Server name (default `localhost`) |
| `CARDTRACKER_MSSQL_DATABASE` | Database (default `CardTracker`) |
| `CARDTRACKER_MSSQL_USER` / `_PASSWORD` | SQL login |
| `CARDTRACKER_MSSQL_TRUSTED` | `1` for Windows authentication |
| `CARDTRACKER_DROP_FOLDER` | Where spreadsheets are picked up from |

For the Agent job, set these as machine-level environment variables, or use
Windows authentication and run the job under a proxy account.

## Dropping spreadsheets

Put `.xlsx`, `.xlsm`, `.csv` or `.tsv` files in the drop folder. The loader
finds the header row even if it isn't the first row, tolerates blank leading
columns, and accepts `Da`/`Yes`/`1`/`true` for foil.

Files move to `archive/` when processed, `failed/` when unreadable — so the job
never trips over the same file twice.

Two modes:

- `--mode DELTA` (default) — quantities are **added** to stock (a new purchase)
- `--mode ABSOLUTE` — quantities **become** the stock level (a stocktake)

Rows that can't be resolved don't stop the load; they land in `etl.LoadError`
with the original row number:

```sql
SELECT * FROM etl.vw_RecentLoads;     -- what ran, and how it went

SELECT le.SourceRowNo, le.ErrorMessage, le.RawData
FROM etl.LoadError le
WHERE le.LoadRunId = (SELECT MAX(LoadRunId) FROM etl.LoadRun);
```

## Using SQL Server as the app's card catalog

`services/mssql_database.py` implements the same `CardLookup` interface as the
SQLite backend, so collection loading and decklist import work against it
unchanged.

**Search is the caveat, and it's a big one.** SQL Server Full-Text Search is an
optional component and often isn't installed — the standard Docker image
doesn't have it. Without it, catalog search falls back to `LIKE '%term%'`,
which no index can accelerate. Measured on 100,000 cards:

| Query | SQLite FTS5 | SQL Server, no full-text |
| --- | --- | --- |
| `light` | 38 ms | 719 ms |
| `lightning bolt` | 12 ms | 433 ms |
| `ning` | 26 ms | 362 ms |

Lookups by name or printing are unaffected (~19 ms) — those use real indexes.
It's specifically the free-text search box.

Run `13_fulltext_optional.sql` to set up a full-text index if your instance has
the feature; the backend detects it and switches to `CONTAINS` with prefix
matching automatically. If the feature isn't installed the script explains how
to add it and changes nothing.

Because of this, the recommended split is SQL Server for stock, orders and
restocking — where it's clearly the right tool — with the local SQLite index
kept for card search, where it's 10–30x faster and works with no server at all.

## Running it locally

```bash
export MSSQL_PASSWORD='...'
./database/run.sh database/01_database_and_schemas.sql master
./database/run.sh database/02_tables_catalog.sql
# ... through 12
./database/run.sh database/tests/01_end_to_end.sql
```

`run.sh` also works against a container — set `MSSQL_CONTAINER` to its name.

## Python driver

`services/mssql.py` supports both `pyodbc` (the normal choice on Windows, with
*ODBC Driver 18 for SQL Server*) and `pymssql` (no ODBC needed). It picks
whichever is installed; force one with `CARDTRACKER_MSSQL_DRIVER`.

```bash
pip install pyodbc     # Windows
pip install pymssql    # Linux/macOS, or when you'd rather skip ODBC
```
