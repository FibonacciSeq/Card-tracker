from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import models


def _ids(response) -> list[str]:
    return [item["stock_id"] for item in response.json()["items"]]


def test_stale_filter_only_returns_untouched_online_stock(client, tenant, stock, second_stock, auth, db):
    stock.updated_at = datetime.now(UTC) - timedelta(days=8)
    second_stock.updated_at = datetime.now(UTC)
    db.commit()

    stale = client.get("/v1/staff/stock?stale=true", headers=auth)
    assert stale.status_code == 200
    assert _ids(stale) == [str(stock.id)]

    # Offline rows never count as stale, even when they are old.
    stock.is_online = False
    db.commit()
    assert _ids(client.get("/v1/staff/stock?stale=true", headers=auth)) == []

    # The archived view ignores the stale switch.
    stock.is_online = True
    stock.archived_at = datetime.now(UTC)
    db.commit()
    archived = client.get("/v1/staff/stock?stale=true&archived=true", headers=auth)
    assert _ids(archived) == [str(stock.id)]


def test_confirm_stock_refreshes_updated_at_and_is_audited(client, stock, auth, db):
    old = datetime.now(UTC) - timedelta(days=8)
    stock.updated_at = old
    db.commit()

    response = client.post(f"/v1/staff/stock/{stock.id}/confirm", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["on_hand"] == 3
    assert body["reserved"] == 0
    assert body["available"] == 3
    confirmed = datetime.fromisoformat(body["updated_at"])
    if confirmed.tzinfo is None:
        confirmed = confirmed.replace(tzinfo=UTC)
    assert confirmed > old

    db.expire_all()
    row = db.get(models.Stock, stock.id)
    assert row is not None
    refreshed = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=UTC)
    assert refreshed > old

    events = client.get("/v1/staff/audit?action=stock.confirm", headers=auth).json()
    assert len(events) == 1
    assert events[0]["action"] == "stock.confirm"
    assert events[0]["data"] == {"on_hand": 3, "reserved": 0, "available": 3}

    assert client.get("/v1/staff/stock?stale=true", headers=auth).json()["items"] == []


def test_confirm_rejects_archived_stock(client, stock, auth, db):
    stock.archived_at = datetime.now(UTC)
    db.commit()

    response = client.post(f"/v1/staff/stock/{stock.id}/confirm", headers=auth)
    assert response.status_code == 409
    assert "Archived stock" in response.json()["detail"]


def test_confirm_is_tenant_scoped(client, stock, auth, db, other_tenant):
    other_stock = models.Stock(
        id=uuid.uuid4(),
        tenant_id=other_tenant.id,
        card_id=stock.card_id,
        finish="foil",
        condition="NM",
        language="en",
        quantity=1,
        price_minor=100,
        currency=other_tenant.currency,
        is_online=True,
    )
    db.add(other_stock)
    db.commit()

    response = client.post(f"/v1/staff/stock/{other_stock.id}/confirm", headers=auth)
    assert response.status_code == 404
