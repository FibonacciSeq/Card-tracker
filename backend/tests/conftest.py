"""Shared fixtures for API tests."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ["CARDTRACKER_DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["CARDTRACKER_AUTO_CREATE_TABLES"] = "false"
os.environ["CARDTRACKER_JWT_SECRET"] = "test-secret-test-secret-test-secret-32"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402
from app.services.ratelimit import limiter  # noqa: E402

engine = create_engine(
    "sqlite+pysqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    # Rate-limit keys are per client IP, and every test shares "testclient".
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def tenant(db):
    row = models.Tenant(
        id=uuid.uuid4(),
        slug="bolt-shop",
        name="Bolt Shop",
        currency="RSD",
        locale="en",
        status="active",
    )
    row.settings = models.TenantSettings(
        hold_hours=24,
        directory_opt_in=True,
        brand_name="Bolt Shop",
        payment_instructions="Pay in store.",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def other_tenant(db):
    row = models.Tenant(
        id=uuid.uuid4(),
        slug="other-shop",
        name="Other Shop",
        currency="RSD",
        locale="en",
        status="active",
    )
    row.settings = models.TenantSettings(hold_hours=24, directory_opt_in=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def card(db):
    row = models.Card(
        id=uuid.uuid4(),
        provider_card_id="scryfall-lightning-bolt",
        name="Lightning Bolt",
        set_code="LEB",
        set_name="Limited Edition Beta",
        collector_number="161",
        rarity="common",
        type_line="Instant",
        colors=["R"],
        image_small="https://example.test/bolt-small.jpg",
        image_normal="https://example.test/bolt-normal.jpg",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def stock(db, tenant, card):
    row = models.Stock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        card_id=card.id,
        finish="nonfoil",
        condition="NM",
        language="en",
        quantity=3,
        price_minor=125000,
        currency="RSD",
        is_online=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def second_stock(db, tenant, card):
    row = models.Stock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        card_id=card.id,
        finish="foil",
        condition="NM",
        language="en",
        quantity=1,
        price_minor=450000,
        currency="RSD",
        is_online=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def owner(db, tenant):
    row = models.User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="owner@example.com",
        password_hash=hash_password("secret-password"),
        role="owner",
        display_name="Owner",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def auth(owner, tenant):
    token = create_access_token(owner.id, tenant.id, owner.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def reservation_payload(stock):
    return {
        "customer": {
            "name": "Marko Petrovic",
            "email": "marko@example.com",
            "phone": "+381601234567",
        },
        "note": "Collecting on Saturday.",
        "items": [{"stock_id": str(stock.id), "quantity": 2}],
    }
