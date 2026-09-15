#!/usr/bin/env bash
# Run a .sql file (or inline -q "query") against the target server.
# Env: MSSQL_HOST MSSQL_USER MSSQL_PASSWORD MSSQL_DB MSSQL_CONTAINER
set -euo pipefail

HOST="${MSSQL_HOST:-localhost}"
USER="${MSSQL_USER:-sa}"
PASS="${MSSQL_PASSWORD:?set MSSQL_PASSWORD}"
DB="${MSSQL_DB:-CardTracker}"
CONTAINER="${MSSQL_CONTAINER:-}"

sqlcmd_run() {
  if [[ -n "$CONTAINER" ]]; then
    docker exec -i "$CONTAINER" /opt/mssql-tools18/bin/sqlcmd -S "$HOST" -U "$USER" -P "$PASS" -C -b "$@"
  else
    sqlcmd -S "$HOST" -U "$USER" -P "$PASS" -C -b "$@"
  fi
}

if [[ "${1:-}" == "-q" ]]; then
  sqlcmd_run -d "$DB" -Q "$2"
else
  sqlcmd_run -d "${2:-$DB}" -i /dev/stdin < "$1"
fi
