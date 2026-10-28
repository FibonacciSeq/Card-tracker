from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import models


def _add_stock(db, tenant, card, *, condition: str, price_minor: int, created_at: datetime) -> None:
    db.add(
        models.Stock(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            card_id=card.id,
            finish="nonfoil",
            condition=condition,
            language="en",
            quantity=1,
            price_minor=price_minor,
            currency=tenant.currency,
            is_online=True,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def test_price_and_newest_cursors_do_not_repeat_rows(client, tenant, card, stock, db):
    base = datetime.now(UTC).replace(microsecond=0)
    _add_stock(db, tenant, card, condition="LP", price_minor=300, created_at=base - timedelta(minutes=3))
    _add_stock(db, tenant, card, condition="MP", price_minor=100, created_at=base - timedelta(minutes=2))
    _add_stock(db, tenant, card, condition="HP", price_minor=200, created_at=base - timedelta(minutes=1))
    _add_stock(db, tenant, card, condition="DMG", price_minor=100, created_at=base)
    db.commit()

    for sort in ("price_asc", "price_desc", "newest", "name"):
        seen: list[str] = []
        cursor = None
        while True:
            params = {"limit": 2, "sort": sort}
            if cursor:
                params["cursor"] = cursor
            response = client.get(f"/v1/shops/{tenant.slug}/stock", params=params)
            assert response.status_code == 200, response.text
            body = response.json()
            seen.extend(item["stock_id"] for item in body["items"])
            cursor = body["next_cursor"]
            if not cursor:
                break

        assert len(seen) == 5, (sort, seen)
        assert len(seen) == len(set(seen)), (sort, seen)


def test_validation_errors_do_not_echo_the_password(client, owner):
    response = client.post(
        "/v1/staff/auth/login",
        json={"email": owner.email, "password": "super-secret"},
    )
    assert response.status_code == 422
    assert "super-secret" not in response.text
    assert all("input" not in error for error in response.json()["detail"])
