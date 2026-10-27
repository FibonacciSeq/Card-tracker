from __future__ import annotations

import uuid

from app import models
from app.security import create_access_token, hash_password


def _make_user(db, tenant, *, role="staff", email=None, active=True):
    row = models.User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=email or f"{role}-{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("secret-password"),
        role=role,
        is_active=active,
        display_name=role.title(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _token(row, tenant):
    return {"Authorization": f"Bearer {create_access_token(row.id, tenant.id, row.role)}"}


def test_owner_lists_the_team(client, auth, owner):
    response = client.get("/v1/staff/users", headers=auth)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["email"] == owner.email
    assert data[0]["role"] == "owner"
    assert data[0]["is_active"] is True


def test_owner_creates_a_staff_member_who_can_sign_in(client, auth, tenant):
    created = client.post(
        "/v1/staff/users",
        headers=auth,
        json={
            "email": "ana@example.com",
            "display_name": "Ana",
            "password": "long-enough-password",
            "role": "staff",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "staff"

    events = client.get("/v1/staff/audit?action=staff.create", headers=auth).json()
    assert events[0]["entity_id"] == created.json()["id"]

    login = client.post(
        "/v1/staff/auth/login",
        json={"tenant_slug": tenant.slug, "email": "ana@example.com", "password": "long-enough-password"},
    )
    assert login.status_code == 200, login.text

    me = client.get("/v1/staff/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.json()["email"] == "ana@example.com"


def test_duplicate_email_is_a_conflict(client, auth, owner):
    response = client.post(
        "/v1/staff/users",
        headers=auth,
        json={"email": owner.email.upper(), "password": "long-enough-password"},
    )
    assert response.status_code == 409


def test_staff_cannot_manage_the_team(client, db, tenant):
    staff = _make_user(db, tenant)
    headers = _token(staff, tenant)
    assert client.get("/v1/staff/users", headers=headers).status_code == 403
    assert client.get("/v1/staff/audit", headers=headers).status_code == 403


def test_short_passwords_are_rejected(client, auth):
    response = client.post(
        "/v1/staff/users",
        headers=auth,
        json={"email": "new@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_deactivated_staff_lose_access(client, auth, db, tenant):
    staff = _make_user(db, tenant)
    headers = _token(staff, tenant)
    assert client.get("/v1/staff/me", headers=headers).status_code == 200

    updated = client.patch(f"/v1/staff/users/{staff.id}", headers=auth, json={"is_active": False})
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False

    assert client.get("/v1/staff/me", headers=headers).status_code == 401
    assert client.get("/v1/staff/stock", headers=headers).status_code == 401

    login = client.post(
        "/v1/staff/auth/login",
        json={"tenant_slug": tenant.slug, "email": staff.email, "password": "secret-password"},
    )
    assert login.status_code == 401


def test_cannot_deactivate_yourself(client, auth, owner):
    response = client.patch(f"/v1/staff/users/{owner.id}", headers=auth, json={"is_active": False})
    assert response.status_code == 400
    assert "your own account" in response.json()["detail"]


def test_cannot_remove_the_last_active_owner(client, auth, owner):
    response = client.patch(f"/v1/staff/users/{owner.id}", headers=auth, json={"role": "staff"})
    assert response.status_code == 409
    assert "at least one active owner" in response.json()["detail"]


def test_a_second_owner_can_be_promoted_and_demoted(client, auth, db, tenant):
    staff = _make_user(db, tenant)
    promoted = client.patch(f"/v1/staff/users/{staff.id}", headers=auth, json={"role": "owner"})
    assert promoted.status_code == 200

    demoted = client.patch(f"/v1/staff/users/{staff.id}", headers=auth, json={"role": "staff"})
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "staff"


def test_password_reset_invalidates_the_old_password(client, auth, db, tenant):
    staff = _make_user(db, tenant, email="reset@example.com")
    response = client.patch(f"/v1/staff/users/{staff.id}", headers=auth, json={"password": "brand-new-password"})
    assert response.status_code == 200

    old = client.post(
        "/v1/staff/auth/login",
        json={"tenant_slug": tenant.slug, "email": staff.email, "password": "secret-password"},
    )
    assert old.status_code == 401

    new = client.post(
        "/v1/staff/auth/login",
        json={"tenant_slug": tenant.slug, "email": staff.email, "password": "brand-new-password"},
    )
    assert new.status_code == 200


def test_audit_trail_records_staff_actions(client, auth, stock, tenant):
    adjusted = client.post(
        f"/v1/staff/stock/{stock.id}/adjust",
        headers=auth,
        json={"delta": 2, "reason": "restock"},
    )
    assert adjusted.status_code == 200

    activity = client.get("/v1/staff/audit", headers=auth)
    assert activity.status_code == 200
    events = activity.json()
    assert events[0]["action"] == "stock.adjust"
    assert "restock" in events[0]["summary"]
    assert events[0]["actor_email"] == "owner@example.com"
    assert events[0]["data"]["delta"] == 2

    filtered = client.get("/v1/staff/audit?action=staff", headers=auth)
    assert filtered.json() == []


def test_audit_trail_is_tenant_scoped(client, auth, db, other_tenant):
    other_owner = _make_user(db, other_tenant, role="owner")
    other_headers = _token(other_owner, other_tenant)
    # An owner at another shop sees their own (empty) trail, never ours.
    assert client.get("/v1/staff/audit", headers=other_headers).json() == []


def test_reservation_and_settings_changes_are_audited(client, auth, stock, reservation_payload):
    created = client.post("/v1/shops/bolt-shop/reservations", json=reservation_payload)
    assert created.status_code == 201
    reservation_id = created.json()["id"]

    confirmed = client.post(
        f"/v1/staff/reservations/{reservation_id}/status",
        headers=auth,
        json={"status": "CONFIRMED"},
    )
    assert confirmed.status_code == 200

    settings = client.patch("/v1/staff/settings", headers=auth, json={"hold_hours": 48})
    assert settings.status_code == 200

    events = client.get("/v1/staff/audit", headers=auth).json()
    actions = [event["action"] for event in events]
    assert "reservation.status" in actions
    assert "settings.update" in actions
    reservation_event = next(event for event in events if event["action"] == "reservation.status")
    assert reservation_event["data"]["to"] == "CONFIRMED"
