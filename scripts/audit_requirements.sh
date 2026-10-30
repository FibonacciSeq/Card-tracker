#!/usr/bin/env bash
# Audit requirements.txt without assuming the running Python has ensurepip.
#
# `pip-audit -r` creates a throwaway virtualenv internally. Some slim Python
# installations (notably Debian/Ubuntu python3.14 without python3.14-venv) have
# no ensurepip module, so that bootstrap fails. In that case we create the
# throwaway environment with virtualenv, install the requirements, and audit
# that isolated environment instead.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ -n "${PYTHON:-}" ]]; then
  python="$PYTHON"
elif [[ -x .venv/bin/python ]]; then
  python=.venv/bin/python
else
  python=python3
fi

if "$python" -c "import ensurepip" >/dev/null 2>&1; then
  exec "$python" -m pip_audit -r requirements.txt --progress-spinner off
fi

if ! "$python" -c "import virtualenv" >/dev/null 2>&1; then
  echo "ensurepip is unavailable and virtualenv is not installed." >&2
  echo "Install python3-venv (or the interpreter's venv package) and retry." >&2
  exit 2
fi

tmp_dir="${TMPDIR:-/tmp}/cardtracker-audit-venv"
rm -rf "$tmp_dir"
"$python" -m virtualenv -q "$tmp_dir"
"$tmp_dir/bin/pip" -q install -r requirements.txt pip-audit
env -u VIRTUAL_ENV PIPAPI_PYTHON_LOCATION="$tmp_dir/bin/python" \
  "$tmp_dir/bin/pip-audit" --local --progress-spinner off
