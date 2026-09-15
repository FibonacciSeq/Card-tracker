"""Konekcija ka SQL Server-u.

Podrzava dva drajvera:
  pyodbc  - standard na Windows-u (ODBC Driver 18 for SQL Server)
  pymssql - ne trazi ODBC, korisno na Linux-u i u testovima

Bira se automatski; moze da se forsira preko CARDTRACKER_MSSQL_DRIVER.
"""

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"


@dataclass(frozen=True)
class ConnectionSettings:
    host: str = "localhost"
    port: int = 1433
    database: str = "CardTracker"
    user: str | None = None
    password: str | None = None
    trusted: bool = False          # Windows autentikacija
    encrypt: bool = True
    trust_server_certificate: bool = True
    odbc_driver: str = DEFAULT_ODBC_DRIVER

    @classmethod
    def from_env(cls, database: str | None = None) -> "ConnectionSettings":
        """Cita CARDTRACKER_MSSQL_* promenljive okruzenja.

        Lozinka namerno ide samo kroz okruzenje - nikad kroz argumente
        komandne linije, koji se vide u listi procesa i u logu SQL Agent-a.
        """
        trusted = os.environ.get("CARDTRACKER_MSSQL_TRUSTED", "").lower() in ("1", "true", "yes")
        return cls(
            host=os.environ.get("CARDTRACKER_MSSQL_HOST", "localhost"),
            port=int(os.environ.get("CARDTRACKER_MSSQL_PORT", "1433")),
            database=database or os.environ.get("CARDTRACKER_MSSQL_DATABASE", "CardTracker"),
            user=os.environ.get("CARDTRACKER_MSSQL_USER"),
            password=os.environ.get("CARDTRACKER_MSSQL_PASSWORD"),
            trusted=trusted,
            encrypt=os.environ.get("CARDTRACKER_MSSQL_ENCRYPT", "1").lower() in ("1", "true", "yes"),
            trust_server_certificate=os.environ.get("CARDTRACKER_MSSQL_TRUST_CERT", "1").lower()
            in ("1", "true", "yes"),
            odbc_driver=os.environ.get("CARDTRACKER_MSSQL_ODBC_DRIVER", DEFAULT_ODBC_DRIVER),
        )

    def odbc_connection_string(self) -> str:
        parts = [
            f"DRIVER={{{self.odbc_driver}}}",
            f"SERVER={self.host},{self.port}",
            f"DATABASE={self.database}",
            f"Encrypt={'yes' if self.encrypt else 'no'}",
            f"TrustServerCertificate={'yes' if self.trust_server_certificate else 'no'}",
        ]
        if self.trusted:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={self.user or ''}")
            parts.append(f"PWD={self.password or ''}")
        return ";".join(parts)


def _available_driver() -> str:
    forced = os.environ.get("CARDTRACKER_MSSQL_DRIVER", "").lower()
    if forced in ("pyodbc", "pymssql"):
        return forced

    try:
        import pyodbc  # noqa: F401
        return "pyodbc"
    except ImportError:
        pass

    try:
        import pymssql  # noqa: F401
        return "pymssql"
    except ImportError as exc:
        raise RuntimeError(
            "Nije pronađen drajver za SQL Server. Instaliraj 'pyodbc' "
            "(uz ODBC Driver 18) ili 'pymssql'."
        ) from exc


def connect(settings: ConnectionSettings | None = None):
    """Otvara konekciju. Pozivalac je zaduzen da je zatvori."""
    settings = settings or ConnectionSettings.from_env()
    driver = _available_driver()

    if driver == "pyodbc":
        import pyodbc

        logger.debug("Povezivanje preko pyodbc na %s/%s", settings.host, settings.database)
        return pyodbc.connect(settings.odbc_connection_string())

    import pymssql

    logger.debug("Povezivanje preko pymssql na %s/%s", settings.host, settings.database)
    if settings.trusted:
        raise RuntimeError("pymssql ne podržava Windows autentikaciju - koristi pyodbc.")

    return pymssql.connect(
        server=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
    )


def uses_qmark(conn) -> bool:
    """pyodbc koristi ? kao placeholder, pymssql koristi %s."""
    return conn.__class__.__module__.split(".")[0] == "pyodbc"


def sql(conn, statement: str) -> str:
    """Prilagodjava placeholdere drajveru.

    Upiti se pisu sa %s; za pyodbc se pretvaraju u ?. Time se izbegava
    duplirani SQL po drajveru.
    """
    return statement.replace("%s", "?") if uses_qmark(conn) else statement


@contextmanager
def connection(settings: ConnectionSettings | None = None):
    """Konekcija kao context manager: commit na izlazu, rollback na gresci."""
    conn = connect(settings)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
