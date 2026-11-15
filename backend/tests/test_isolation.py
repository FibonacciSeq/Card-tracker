from __future__ import annotations

import uuid

from app import models


def _make_other_stock(db, other_tenant):
    card = models.Card(
        id=uuid.uuid4(),
        provider_card_id="scryfall-other-card",
        name="Counterspell",
        set_code="LEB",
        set_name="Limited Edition Beta",
        collector_number="60",
        rarity="common",
        type_line="Instant",
        colors=["U"],
    )
    db.add(card)
    db.flush()
    stock = models.Stock(
        id=uuid.uuid4(),
        tenant_id=other_tenant.id,
        card_id=card.id,
        quantity=4,
        price_minor=90000,
        currency="RSD",
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


def test_shop_directory_lists_opted_in_shops(client, tenant, other_tenant):
    response = client.get("/v1/shops")
    assert response.status_code == 200
    slugs = {shop["slug"] for shop in response.json()}
    assert slugs == {tenant.slug, other_tenant.slug}


def test_shop_directory_filters_and_sorts_by_distance(client, tenant, other_tenant, db):
    tenant.settings.latitude = 44.8125
    tenant.settings.longitude = 20.4612
    other_tenant.settings.latitude = 45.2671
    other_tenant.settings.longitude = 19.8335
    db.commit()

    nearby = client.get(
        "/v1/shops",
        params={"near_lat": 44.82, "near_lng": 20.46, "radius_km": 10},
    )
    assert nearby.status_code == 200
    assert [shop["slug"] for shop in nearby.json()] == [tenant.slug]
    assert nearby.json()[0]["distance_km"] < 2
    assert nearby.json()[0]["latitude"] == 44.8125
    assert nearby.json()[0]["longitude"] == 20.4612

    wider = client.get(
        "/v1/shops",
        params={"near_lat": 44.82, "near_lng": 20.46, "radius_km": 100},
    )
    assert wider.status_code == 200
    assert [shop["slug"] for shop in wider.json()] == [tenant.slug, other_tenant.slug]
    assert wider.json()[0]["distance_km"] < wider.json()[1]["distance_km"]


def test_shop_directory_skips_shops_without_coordinates(client, tenant, other_tenant, db):
    other_tenant.settings.latitude = 45.2671
    other_tenant.settings.longitude = 19.8335
    db.commit()

    response = client.get(
        "/v1/shops",
        params={"near_lat": 44.82, "near_lng": 20.46, "radius_km": 100},
    )
    assert response.status_code == 200
    assert [shop["slug"] for shop in response.json()] == [other_tenant.slug]
    assert response.json()[0]["distance_km"] > 0


def test_shop_directory_requires_a_complete_location(client):
    missing_pair = client.get("/v1/shops", params={"near_lat": 44.82})
    assert missing_pair.status_code == 422
    assert missing_pair.json()["detail"] == "near_lat and near_lng must be provided together."

    missing_origin = client.get("/v1/shops", params={"radius_km": 10})
    assert missing_origin.status_code == 422
    assert missing_origin.json()["detail"] == "radius_km requires near_lat and near_lng."


def test_stock_is_scoped_to_shop(client, tenant, other_tenant, stock, db):
    _make_other_stock(db, other_tenant)

    response = client.get(f"/v1/shops/{tenant.slug}/stock")
    assert response.status_code == 200
    names = {item["card"]["name"] for item in response.json()["items"]}
    assert names == {"Lightning Bolt"}

    response = client.get(f"/v1/shops/{other_tenant.slug}/stock")
    assert response.status_code == 200
    names = {item["card"]["name"] for item in response.json()["items"]}
    assert names == {"Counterspell"}


def test_reservation_cannot_use_another_shops_stock(client, tenant, other_tenant, stock, db):
    other_stock = _make_other_stock(db, other_tenant)
    payload = {
        "customer": {"name": "Test", "email": "test@example.com", "phone": ""},
        "items": [{"stock_id": str(other_stock.id), "quantity": 1}],
    }
    response = client.post(f"/v1/shops/{tenant.slug}/reservations", json=payload)
    assert response.status_code == 404
    assert response.json()["code"] == "stock_not_found"


def test_shop_profile_is_public_but_not_other_settings(client, tenant):
    response = client.get(f"/v1/shops/{tenant.slug}")
    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == tenant.slug
    assert data["hold_hours"] == 24


def test_search_and_facets(client, tenant, stock):
    response = client.get(f"/v1/shops/{tenant.slug}/stock", params={"query": "bolt"})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

    response = client.get(f"/v1/shops/{tenant.slug}/facets")
    assert response.status_code == 200, response.text
    assert response.json()["sets"][0]["value"] == "LEB"


def test_stock_pagination(client, tenant, stock, db):
    card = models.Card(
        id=uuid.uuid4(),
        provider_card_id="scryfall-pagination-card",
        name="Counterspell",
        set_code="LEB",
        set_name="Limited Edition Beta",
        collector_number="60",
        rarity="common",
        type_line="Instant",
        colors=["U"],
    )
    db.add(card)
    db.flush()
    db.add(
        models.Stock(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            card_id=card.id,
            quantity=1,
            price_minor=90000,
            currency="RSD",
        )
    )
    db.commit()

    first = client.get(f"/v1/shops/{tenant.slug}/stock", params={"limit": 1, "sort": "name"})
    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 1
    assert first.json()["next_cursor"]

    second = client.get(
        f"/v1/shops/{tenant.slug}/stock",
        params={"limit": 1, "sort": "name", "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 1
    assert second.json()["items"][0]["stock_id"] != first.json()["items"][0]["stock_id"]


def test_unknown_shop_returns_404(client):
    assert client.get("/v1/shops/nope").status_code == 404
    response = client.post(
        "/v1/shops/nope/reservations",
        json={
            "customer": {"name": "Test", "email": "test@example.com", "phone": ""},
            "items": [{"stock_id": str(uuid.uuid4()), "quantity": 1}],
        },
    )
    assert response.status_code == 404
