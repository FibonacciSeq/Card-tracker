#!/usr/bin/env bash
# Run the SQL Server schema and end-to-end checks in a disposable container.
#
# This is optional on developer machines: when Docker is unavailable the script
# exits successfully with a clear skip message. CI runs it on a runner with
# Docker, where it is a real gate.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  if [ "${CARDTRACKER_REQUIRE_SQLSERVER:-0}" = "1" ]; then
    echo "ERROR: Docker is required but not available." >&2
    exit 1
  fi
  echo "SKIP: Docker is not available; SQL Server E2E was not run."
  exit 0
fi

if ! docker compose version >/dev/null 2>&1; then
  if [ "${CARDTRACKER_REQUIRE_SQLSERVER:-0}" = "1" ]; then
    echo "ERROR: Docker Compose is required but not available." >&2
    exit 1
  fi
  echo "SKIP: docker compose is not available; SQL Server E2E was not run."
  exit 0
fi

export MSSQL_HOST=localhost
export MSSQL_USER=sa
export MSSQL_PASSWORD='CardTracker!Test123'
export MSSQL_DB=CardTracker
export MSSQL_CONTAINER=cardtracker-sqlserver-test

cleanup() {
  docker compose -f docker-compose.test.yml down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose -f docker-compose.test.yml up -d --wait

# 01 creates the database, so it must connect to master first.
export MSSQL_DB=master
./database/run.sh database/01_database_and_schemas.sql
export MSSQL_DB=CardTracker
for script in \
  database/02_tables_catalog.sql \
  database/03_tables_inventory.sql \
  database/04_tables_sales.sql \
  database/05_tables_planning_and_etl.sql \
  database/06_functions.sql \
  database/07_views.sql \
  database/08_procedures_inventory.sql \
  database/09_procedures_sales.sql \
  database/10_procedures_etl.sql \
  database/11_procedures_stock_import.sql; do
  ./database/run.sh "$script"
done

./database/run.sh database/tests/01_end_to_end.sql
