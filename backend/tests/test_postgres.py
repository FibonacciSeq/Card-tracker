"""Postgres-only verification of row-level security and row locking.

These tests need a real PostgreSQL server: SQLite ignores RLS and `FOR UPDATE`,
so the default suite cannot prove tenant isolation or the last-copy race.

They are skipped unless both connection URLs are provided:

    CARDTRACKER_TEST_POSTGRES_ADMIN_URL  owner/superuser URL used for migrations
    CARDTRACKER_TEST_POSTGRES_URL        application role URL; RLS applies

The application role must not be the table owner or a superuser, otherwise
Postgres ignores RLS. See `backend/README.md` for the one-line setup.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, func, make_url, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app import models, schemas
from app.db import set_tenant_context
from app.services import reservations

ADMIN_URL = os.environ.get("CARDTRACKER_TEST_POSTGRES_ADMIN_URL")
APP_URL = os.environ.get("CARDTRACKER_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL),
    reason=(
        "set CARDTRACKER_TEST_POSTGRES_ADMIN_URL and CARDTRACKER_TEST_POSTGRES_URL "
        "to run the Postgres isolation and locking tests"
    ),
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _run_migrations(url: str) -> None:
    env = {
        **os.environ,
        "CARDTRACKER_DATABASE_URL": url,
        "CARDTRACKER_AUTO_CREATE_TABLES": "false",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")


def _prepare_app_role(admin: Engine, app_url: str) -> None:
    """Ensure the application role exists and can reach migrated tables."""
    role = make_url(app_url).username
    assert role, "CARDTRACKER_TEST_POSTGRES_URL must include a username"
    if not ROLE_PATTERN.match(role):
        raise RuntimeError(f"Unsupported application role name: {role!r}")

    with admin.begin() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role})
        if not exists:
            # Managed providers may forbid role creation; surface that clearly.
            conn.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{role}'"))
        conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
        conn.execute(text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))


@pytest.fixture(scope="module")
def admin_engine() -> Iterator[Engine]:
    assert ADMIN_URL
    engine = create_engine(ADMIN_URL, pool_pre_ping=True)
    _run_migrations(ADMIN_URL)
    _prepare_app_role(engine, APP_URL or "")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def app_engine(admin_engine: Engine) -> Iterator[Engine]:
    assert APP_URL
    engine = create_engine(APP_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def admin(admin_engine: Engine) -> Iterator[Session]:
    maker = sessionmaker(bind=admin_engine, autoflush=False, expire_on_commit=False)
    with maker() as session:
        yield session


@pytest.fixture
def app_session(app_engine: Engine) -> Iterator[Session]:
    maker = sessionmaker(bind=app_engine, autoflush=False, expire_on_commit=False)
    with maker() as session:
        yield session


def _make_shop(admin: Session, *, quantity: int = 1, reserved: int = 0) -> dict[str, uuid.UUID]:
    """Create a tenant, card, and stock row as the privileged role.

    Fixtures bypass RLS here on purpose: the assertions are about what the
    application role can see afterwards.
    """
    suffix = uuid.uuid4().hex[:8]
    tenant = models.Tenant(
        id=uuid.uuid4(),
        slug=f"shop-{suffix}",
        name=f"Shop {suffix}",
        currency="RSD",
        locale="en",
        status="active",
    )
    tenant.settings = models.TenantSettings(hold_hours=24, directory_opt_in=True, brand_name=f"Shop {suffix}")
    card = models.Card(
        id=uuid.uuid4(),
        provider_card_id=f"scryfall-{suffix}",
        name=f"Card {suffix}",
        set_code="LEB",
        collector_number=suffix,
    )
    admin.add_all([tenant, card])
    admin.flush()

    stock = models.Stock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        card_id=card.id,
        quantity=quantity,
        reserved=reserved,
        price_minor=125000,
        currency="RSD",
        is_online=True,
    )
    admin.add(stock)
    admin.commit()
    return {"tenant_id": tenant.id, "card_id": card.id, "stock_id": stock.id}


def _payload(stock_id: uuid.UUID, quantity: int = 1) -> schemas.ReservationCreate:
    return schemas.ReservationCreate.model_validate(
        {
            "customer": {"name": "Marko Petrovic", "email": "marko@example.com", "phone": "+381601234567"},
            "items": [{"stock_id": str(stock_id), "quantity": quantity}],
        }
    )


def test_rls_hides_other_tenants(app_session: Session, admin: Session) -> None:
    shop_a = _make_shop(admin)
    shop_b = _make_shop(admin)

    set_tenant_context(app_session, shop_a["tenant_id"])
    visible = app_session.scalars(select(models.Stock)).all()

    assert [row.id for row in visible] == [shop_a["stock_id"]]
    assert shop_b["stock_id"] not in {row.id for row in visible}


def test_no_tenant_context_sees_no_tenant_rows(app_session: Session, admin: Session) -> None:
    shop = _make_shop(admin)

    # No set_tenant_context call: current_setting() is NULL, so the policy
    # predicate is NULL and no rows are visible.
    count = app_session.scalar(select(func.count()).select_from(models.Stock))
    assert count == 0

    set_tenant_context(app_session, shop["tenant_id"])
    count = app_session.scalar(select(func.count()).select_from(models.Stock))
    assert count == 1


def test_tenant_settings_are_readable_without_tenant_context(admin: Session, app_engine: Engine) -> None:
    """The public shop directory must read branding across tenants.

    tenant_settings is deliberately outside RLS, so this asserts the exception
    stays intentional rather than becoming accidental.
    """
    shop = _make_shop(admin)
    with Session(app_engine) as session:
        brand = session.scalar(
            select(models.TenantSettings.brand_name).where(models.TenantSettings.tenant_id == shop["tenant_id"])
        )
        assert brand is not None


def test_rls_blocks_cross_tenant_write(app_session: Session, admin: Session) -> None:
    shop_a = _make_shop(admin)
    shop_b = _make_shop(admin)

    set_tenant_context(app_session, shop_a["tenant_id"])
    app_session.add(
        models.Stock(
            tenant_id=shop_b["tenant_id"],
            card_id=shop_b["card_id"],
            quantity=5,
            reserved=0,
            price_minor=100,
            currency="RSD",
        )
    )
    with pytest.raises(DBAPIError):
        app_session.commit()
    app_session.rollback()


def test_tenant_context_survives_commit(app_session: Session, admin: Session) -> None:
    """The after_begin hook must re-apply the RLS setting in the next transaction.

    Endpoints commit mid-request and then refresh ORM objects (see
    create_reservation); without the hook those refreshes run with no tenant
    context and RLS returns nothing.
    """
    shop_a = _make_shop(admin)
    _make_shop(admin)

    set_tenant_context(app_session, shop_a["tenant_id"])
    assert app_session.scalar(select(func.count()).select_from(models.Stock)) == 1

    app_session.commit()  # ends the transaction and clears the session setting

    assert app_session.scalar(select(func.count()).select_from(models.Stock)) == 1
    visible = app_session.scalars(select(models.Stock.id)).all()
    assert visible == [shop_a["stock_id"]]


def test_last_copy_race_has_exactly_one_winner(app_engine: Engine, admin_engine: Engine, admin: Session) -> None:
    """Two customers reserve the last copy simultaneously."""
    shop = _make_shop(admin, quantity=1)
    payload = _payload(shop["stock_id"])

    maker = sessionmaker(bind=app_engine, autoflush=False, expire_on_commit=False)
    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            with maker() as session:
                set_tenant_context(session, shop["tenant_id"])
                tenant = session.get(models.Tenant, shop["tenant_id"])
                assert tenant is not None
                barrier.wait(timeout=10)
                try:
                    reservations.create_reservation(session, tenant, payload)
                    outcome = "ok"
                except reservations.ReservationError as exc:
                    outcome = exc.code
        except BaseException as exc:  # pragma: no cover - surfaced below
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, f"unexpected thread failures: {errors}"
    assert sorted(results) == ["ok", "stock_changed"]

    with Session(admin_engine) as check:
        stock = check.get(models.Stock, shop["stock_id"])
        assert stock is not None
        assert stock.reserved == 1

        active = check.scalar(
            select(func.count())
            .select_from(models.Reservation)
            .where(
                models.Reservation.tenant_id == shop["tenant_id"],
                models.Reservation.status.in_(reservations.ACTIVE_STATUSES),
            )
        )
        assert active == 1
