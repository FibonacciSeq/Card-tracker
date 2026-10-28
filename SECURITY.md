# Security policy

## Supported versions

Card Tracker is currently a pre-1.0 project with a legacy Tkinter desktop app
and a multi-vendor platform (`backend/`, `admin/`, `mobile/`). Security fixes
are applied to the latest release and to `main`.

| Version | Supported |
| --- | --- |
| `0.1.x` | Yes |
| older | No |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's
private vulnerability reporting:

<https://github.com/aleksacvele/card-tracker/security/advisories/new>

Include:

- the affected version or commit,
- steps to reproduce,
- the impact you believe it has, and
- any suggested fix or mitigation.

You can expect an acknowledgement within a few business days. Please allow time
for a fix before publishing details.

## Local customer data

The customer and owner apps share `cardtracker_shop.db` (or the file named by
`CARDTRACKER_SHOP_DB`). It contains names, e-mail addresses, phone numbers,
order notes, and order history. It is intentionally excluded from Git.

- Keep the database on a trusted, access-controlled machine or share.
- Restrict filesystem permissions to the account that runs the shop.
- Do not attach the database, exports, or screenshots containing customer data
  to public issues or pull requests.
- Back it up securely. The SQLite file is not encrypted at rest; use full-disk
  or volume encryption if the machine is shared or portable.
- Delete customer data when it is no longer needed, and follow applicable local
  privacy rules.

The SQL Server schema in `database/` stores the same kind of data in a
multi-user deployment. Apply the same access control, backup, and retention
rules there.

The platform backend stores shop, customer, reservation, and special-order data
in PostgreSQL in production (SQLite locally). Treat database dumps, API logs,
and notification payloads as sensitive. The mobile app keeps only a local cart
and the guest reservation metadata needed to reopen a hold.

## Mobile app tokens

- A guest reservation access token is a credential. Native builds store it in
  Expo SecureStore; the web preview falls back to AsyncStorage because
  SecureStore has no web implementation. Do not use the web preview as a
  production customer channel.
- The app sends an idempotency key when creating a reservation and reuses it
  while a submission is retried, preventing duplicate holds after a lost
  response.
- `EXPO_PUBLIC_*` environment variables are embedded in the client bundle and
  are not secret. Never put API secrets, SMTP credentials, or staff tokens in
  a mobile environment file.
- The customer app does not collect or transmit payment details; payment stays
  with the shop.

## Secrets and environment variables

SQL Server credentials are read only from environment variables:

| Variable | Purpose |
| --- | --- |
| `CARDTRACKER_MSSQL_HOST` | Server host name |
| `CARDTRACKER_MSSQL_PORT` | Server port |
| `CARDTRACKER_MSSQL_DATABASE` | Database name |
| `CARDTRACKER_MSSQL_USER` | SQL login |
| `CARDTRACKER_MSSQL_PASSWORD` | SQL password |
| `CARDTRACKER_MSSQL_TRUSTED` | Use Windows authentication |
| `CARDTRACKER_MSSQL_ENCRYPT` | Encrypt the connection |
| `CARDTRACKER_MSSQL_TRUST_CERT` | Trust a server certificate |
| `CARDTRACKER_MSSQL_ODBC_DRIVER` | ODBC driver name |
| `CARDTRACKER_MSSQL_DRIVER` | Force `pyodbc` or `pymssql` |

Do not commit credentials, `.env` files, or connection strings. `.env` and
`.env.*` are git-ignored; `.env.example` contains placeholders only.

`CARDTRACKER_MSSQL_TRUST_CERT` defaults to `1` for local development with a
self-signed SQL Server certificate. In production, use a trusted certificate
and set it to `0`. `CARDTRACKER_MSSQL_ENCRYPT` defaults to `1`.

## Application hardening already in place

- Card downloads require HTTPS; image downloads allow only HTTP(S). Image
  cache names are sanitized before use and image downloads are capped at 8 MiB.
- Remote requests use timeouts. Images and the extracted Scryfall catalog are
  written to a temporary file and atomically renamed, so an interrupted
  download cannot leave a partial file in place.
- SQL values are parameterized. The few statically assembled SQL fragments are
  built from fixed tuples; Bandit's `B608` heuristic is explicitly skipped
  after review, with the rationale recorded in `pyproject.toml`.
- Shop input is trimmed and bounded; e-mail addresses receive basic format
  validation.
- The local shop schema records a `user_version`; a database created by a
  newer application version is rejected instead of being modified blindly.
- Tk callbacks from worker threads go through `ui.dispatch.TkDispatcher`, so
  background work never touches widgets directly.

These measures reduce risk but do not make untrusted data safe. Treat the local
database and any spreadsheet imports as sensitive input.

## Dependency and code checks

Every pull request runs the checks for the parts it touches. The legacy
desktop workflow runs:

```bash
ruff check .
ruff format --check .
mypy .
pytest --cov --cov-report=term-missing
bandit -q -c pyproject.toml -r .
pip-audit -r requirements.txt --progress-spinner off
```

The platform workflows run backend Ruff/mypy/pytest (SQLite and PostgreSQL),
admin ESLint/typecheck/build/Playwright, and mobile ESLint/typecheck/web export.
See [`STATUS.md`](STATUS.md) and the component READMEs for the exact commands.

Dependabot checks Python dependencies and GitHub Actions monthly. If you add a
dependency, pin a lower bound that contains the current security fixes and
update `requirements-dev.txt` as well as `pyproject.toml` when applicable.
