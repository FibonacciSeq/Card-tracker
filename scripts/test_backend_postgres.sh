#!/usr/bin/env bash
# Run the backend suite against the disposable local PostgreSQL instance.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [[ -n "${PYTHON:-}" ]]; then
  python="$PYTHON"
elif [[ -x "$root/.venv/bin/python" ]]; then
  python="$root/.venv/bin/python"
else
  python=python3
fi

pg_script="$root/backend/scripts/local_postgres.sh"
was_running=0
if "$pg_script" status | grep -q '^running'; then
  was_running=1
fi

"$pg_script" start
cleanup() {
  if [ "$was_running" -eq 0 ]; then
    "$pg_script" stop >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

eval "$("$pg_script" env)"
cd "$root/backend"
"$python" -m pytest --cov=app --cov-branch --cov-report=term-missing
