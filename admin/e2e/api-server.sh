#!/usr/bin/env bash
# Start a throwaway API with demo data for the Playwright suite.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend="$here/../../backend"
python="${CARDTRACKER_E2E_PYTHON:-$here/../../.venv/bin/python}"
db="${CARDTRACKER_E2E_DB:-/tmp/cardtracker-e2e.db}"

rm -f "$db"
cd "$backend"

export CARDTRACKER_ENVIRONMENT=test
export CARDTRACKER_AUTO_CREATE_TABLES=true
export CARDTRACKER_DATABASE_URL="sqlite+pysqlite:///$db"
export CARDTRACKER_JWT_SECRET="e2e-secret-e2e-secret-e2e-secret-32"

# Create the schema before seeding: the app only auto-creates tables on startup,
# which happens after this script has already seeded demo data.
"$python" -c "from app.db import engine; from app.models import Base; Base.metadata.create_all(engine)"

"$python" -m app.cli.seed_demo \
  --slug bolt-shop \
  --name "Bolt Shop" \
  --email owner@example.com \
  --password secret-password >/dev/null

exec "$python" -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level warning
