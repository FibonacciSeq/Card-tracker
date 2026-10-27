#!/usr/bin/env bash
# Run a disposable PostgreSQL for development without Docker or root access.
#
# Downloads a portable PostgreSQL build into a cache directory, initialises a
# cluster, and starts it on a non-default port. Nothing is installed system-wide
# and nothing outside the cache directory is touched.
#
#   ./scripts/local_postgres.sh start    # download + init + start
#   eval "$(./scripts/local_postgres.sh env)"   # export test/admin URLs
#   ./scripts/local_postgres.sh stop
#   ./scripts/local_postgres.sh reset    # delete the cluster and start over
#
# Intended for local verification of RLS, migrations, and row locking. CI and
# production use a managed/real PostgreSQL instead.
set -euo pipefail

PG_VERSION="${CARDTRACKER_PG_VERSION:-18.6.1}"
PG_PORT="${CARDTRACKER_PG_PORT:-55432}"
BASE_DIR="${CARDTRACKER_PG_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/cardtracker/postgres}"
PGDATA="$BASE_DIR/data"
LOGFILE="$BASE_DIR/postgres.log"
DB_NAME="${CARDTRACKER_PG_DATABASE:-cardtracker}"
DB_USER="cardtracker_app"
DB_PASSWORD="cardtracker_app"
RELEASE="https://github.com/theseus-rs/postgresql-binaries/releases/download"

platform() {
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) echo "x86_64-unknown-linux-gnu" ;;
    Linux-aarch64 | Linux-arm64) echo "aarch64-unknown-linux-gnu" ;;
    Darwin-arm64) echo "aarch64-apple-darwin" ;;
    Darwin-x86_64) echo "x86_64-apple-darwin" ;;
    *)
      echo "unsupported platform: $(uname -s) $(uname -m)" >&2
      echo "install PostgreSQL manually or point CARDTRACKER_TEST_POSTGRES_URL at an existing server" >&2
      exit 1
      ;;
  esac
}

pkg_dir() { echo "$BASE_DIR/postgresql-$PG_VERSION-$(platform)"; }
pg_bin() { echo "$(pkg_dir)/bin"; }

fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$1" -O "$2"
  else
    echo "need curl or wget to download PostgreSQL" >&2
    exit 1
  fi
}

is_running() {
  [ -f "$PGDATA/postmaster.pid" ] && "$(pg_bin)/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1
}

ensure_binaries() {
  local name tarball url checksum
  name="postgresql-$PG_VERSION-$(platform)"
  [ -x "$BASE_DIR/$name/bin/pg_ctl" ] && return 0

  mkdir -p "$BASE_DIR"
  tarball="$BASE_DIR/$name.tar.gz"
  url="$RELEASE/$PG_VERSION/$name.tar.gz"
  echo "Downloading PostgreSQL $PG_VERSION for $(platform)..." >&2
  fetch "$url" "$tarball"
  if fetch "$url.sha256" "$tarball.sha256" 2>/dev/null; then
    (cd "$BASE_DIR" && sha256sum -c "$tarball.sha256" >/dev/null 2>&1) ||
      (cd "$BASE_DIR" && shasum -a 256 -c "$tarball.sha256" >/dev/null)
  fi
  tar -xzf "$tarball" -C "$BASE_DIR"
  rm -f "$tarball"
}

init_cluster() {
  [ -d "$PGDATA" ] && return 0
  echo "Initialising cluster in $PGDATA..." >&2
  mkdir -p "$BASE_DIR"
  "$(pg_bin)/initdb" -D "$PGDATA" -U postgres --auth=trust -E UTF8 >/dev/null
  printf "%s\n" "$PG_VERSION" >"$PGDATA/.cardtracker-version"
}

ensure_database() {
  local psql=("$(pg_bin)/psql" -h 127.0.0.1 -p "$PG_PORT" -U postgres -v ON_ERROR_STOP=1 -tA)
  if [ "$("${psql[@]}" -c "SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER'")" != "1" ]; then
    "${psql[@]}" -c "CREATE ROLE \"$DB_USER\" LOGIN PASSWORD '$DB_PASSWORD'"
  fi
  if [ "$("${psql[@]}" -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")" != "1" ]; then
    "${psql[@]}" -c "CREATE DATABASE \"$DB_NAME\""
  fi
}

main() {
  case "${1:-start}" in
    start)
      ensure_binaries
      init_cluster
      if is_running; then
        echo "PostgreSQL already running on port $PG_PORT." >&2
      else
        "$(pg_bin)/pg_ctl" -D "$PGDATA" -l "$LOGFILE" \
          -o "-p $PG_PORT -c listen_addresses=127.0.0.1" start >/dev/null
      fi
      ensure_database
      echo "PostgreSQL $PG_VERSION ready on 127.0.0.1:$PG_PORT (database: $DB_NAME)." >&2
      ;;
    stop)
      if is_running; then
        "$(pg_bin)/pg_ctl" -D "$PGDATA" stop -m fast >/dev/null
        echo "PostgreSQL stopped." >&2
      else
        echo "PostgreSQL is not running." >&2
      fi
      ;;
    status)
      if is_running; then
        echo "running on 127.0.0.1:$(sed -n '4p' "$PGDATA/postmaster.pid")"
      else
        echo "stopped"
      fi
      ;;
    env)
      echo "export CARDTRACKER_TEST_POSTGRES_ADMIN_URL='postgresql+psycopg://postgres@127.0.0.1:$PG_PORT/$DB_NAME'"
      echo "export CARDTRACKER_TEST_POSTGRES_URL='postgresql+psycopg://$DB_USER:$DB_PASSWORD@127.0.0.1:$PG_PORT/$DB_NAME'"
      echo "export CARDTRACKER_DATABASE_URL='postgresql+psycopg://$DB_USER:$DB_PASSWORD@127.0.0.1:$PG_PORT/$DB_NAME'"
      ;;
    reset)
      is_running && "$(pg_bin)/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null || true
      rm -rf "$PGDATA"
      echo "Cluster removed. Run 'start' to recreate it." >&2
      ;;
    *)
      echo "usage: $0 {start|stop|status|env|reset}" >&2
      exit 2
      ;;
  esac
}

main "$@"
