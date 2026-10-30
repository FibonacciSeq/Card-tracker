"""Database engine and session handling."""

from collections.abc import Generator
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

connect_args: dict = {}
if settings.database_url.startswith("sqlite"):  # pragma: no cover - dialect selected at import
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

if settings.database_url.startswith("sqlite"):  # pragma: no cover - dialect selected at import

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


def set_customer_context(db: Session, customer_id: UUID) -> None:
    """Set the RLS customer for the current Postgres transaction.

    Customer-owned rows are visible across tenants, but only when their
    ``customer_id`` matches this setting.
    """
    db.info["customer_id"] = str(customer_id)
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.customer_id', :customer_id, true)"),
            {"customer_id": str(customer_id)},
        )


@event.listens_for(Session, "after_begin")
def _restore_rls_context(session: Session, _transaction, connection) -> None:
    """Re-apply transaction-local RLS settings after a commit/rollback.

    `set_config(..., true)` is transaction-local. Endpoints often commit and
    then refresh an ORM object, which starts a new transaction; without this
    hook that refresh would run with no tenant/customer context and be blocked
    by RLS.
    """
    tenant_id = session.info.get("tenant_id")
    if tenant_id is not None and connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
    customer_id = session.info.get("customer_id")
    if customer_id is not None and connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.customer_id', :customer_id, true)"),
            {"customer_id": str(customer_id)},
        )


def set_tenant_context(db: Session, tenant_id: UUID) -> None:
    """Set the RLS tenant for the current Postgres transaction.

    SQLite has no row-level security, so this is a no-op there. On Postgres
    every request must call this after resolving the tenant.
    """
    db.info["tenant_id"] = str(tenant_id)
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
