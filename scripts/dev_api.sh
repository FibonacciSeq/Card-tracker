#!/usr/bin/env bash
# Start the local development API together with its background workers.
#
# Applies migrations, starts the notification and expiry workers in the
# background, and runs the API in the foreground. Ctrl+C (or any exit of the
# API) stops the workers too. Extra arguments are passed to uvicorn, e.g.:
#
#     ./scripts/dev_api.sh --port 8011
#
# Worker logs are kept outside the repository, next to the runbook:
#     ~/Desktop/Card-tracker-worker.log          (notification worker)
#     ~/Desktop/Card-tracker-expiry-worker.log   (expiry worker)
set -euo pipefail

backend="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"
cd "$backend"

worker_log="$HOME/Desktop/Card-tracker-worker.log"
expiry_log="$HOME/Desktop/Card-tracker-expiry-worker.log"

# Exactly one set of workers: replace any leftovers from a previous run
# (including one started with plain nohup or a detached terminal).
pkill -f -- '-m app\.workers\.notifications' 2>/dev/null || true
pkill -f -- '-m app\.workers\.expiry' 2>/dev/null || true
sleep 1

../.venv/bin/alembic upgrade head

nohup ../.venv/bin/python -m app.workers.notifications > "$worker_log" 2>&1 &
notifications_pid=$!
nohup ../.venv/bin/python -m app.workers.expiry > "$expiry_log" 2>&1 &
expiry_pid=$!

echo "API:     http://127.0.0.1:8000  (Ctrl+C stops the API and both workers)"
echo "Workers: notifications -> $worker_log"
echo "         expiry        -> $expiry_log"

../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 "$@" &
api_pid=$!

cleanup() {
  kill "$api_pid" "$notifications_pid" "$expiry_pid" 2>/dev/null || true
}
trap cleanup EXIT

wait "$api_pid"
