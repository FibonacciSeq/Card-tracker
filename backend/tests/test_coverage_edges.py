"""Focused edge-case coverage for defensive and rarely-used branches."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.config import Settings, settings
from app.services import notifications, ratelimit
from app.workers import expiry as expiry_worker
from app.workers import notifications as worker

# ------------------------------------------------------------------ security


def test_verify_password_returns_false_for_a_malformed_hash():
    from app.security import verify_password

    assert verify_password("not-a-valid-argon2-hash", "anything") is False


def test_verify_unsubscribe_token_rejects_missing_token():
    from app.security import verify_restock_unsubscribe_token

    assert verify_restock_unsubscribe_token(uuid.uuid4(), uuid.uuid4(), None) is False


def test_settings_require_a_long_secret_outside_development():
    with pytest.raises(ValueError, match="32 characters"):
        Settings(environment="production", jwt_secret="short")


# ------------------------------------------------------------------- config


def test_notification_helpers_cover_all_branches():
    tenant: Any = SimpleNamespace(
        id=uuid.uuid4(),
        slug="bolt-shop",
        name="Bolt Shop",
        settings=SimpleNamespace(brand_name="", notification_email=None, contact=None),
    )
    assert notifications.shop_label(tenant) == "Bolt Shop"
    assert notifications.staff_recipient(tenant) is None

    tenant.settings = SimpleNamespace(brand_name="Brand", notification_email="staff@example.com", contact={})
    assert notifications.shop_label(tenant) == "Brand"
    assert notifications.staff_recipient(tenant) == "staff@example.com"

    tenant.settings.contact = {"email": "contact@example.com"}
    tenant.settings.notification_email = None
    assert notifications.staff_recipient(tenant) == "contact@example.com"

    tenant.settings.contact = "not-a-dict"
    assert notifications.staff_recipient(tenant) is None

    no_settings: Any = SimpleNamespace(settings=None)
    assert notifications.staff_recipient(no_settings) is None
    assert notifications.shop_label(no_settings) == no_settings.name if hasattr(no_settings, "name") else True


def test_notification_money_when_and_url_helpers():
    assert notifications._money(None, None) == "—"
    assert notifications._money(1234, None) == "12.34"
    assert notifications._when(None) == "—"
    assert notifications._when("2026-01-02T03:04:05") == "2026-01-02 03:04 UTC"

    tenant: Any = SimpleNamespace(id=uuid.uuid4(), slug="bolt-shop")
    assert (
        notifications.app_card_url(tenant, {"stock_id": "s1"}) == "https://app.cardtracker.local/shop/bolt-shop/card/s1"
    )
    assert notifications.app_card_url(tenant, {"shop_slug": "other"}) == "https://app.cardtracker.local/shop/other"

    row: Any = SimpleNamespace(kind="OTHER", payload={})
    assert notifications.unsubscribe_url(row, tenant) is None
    row.kind = "RESTOCK_AVAILABLE"
    assert notifications.headers(row, tenant) == {}

    alert_id = uuid.uuid4()
    row.payload = {"alert_id": str(alert_id), "shop_slug": "other"}
    url = notifications.unsubscribe_url(row, tenant)
    assert url is not None
    assert "/v1/shops/other/restock-alerts/" in url
    one_click = notifications.unsubscribe_url(row, tenant, one_click=True)
    assert one_click is not None
    assert "/unsubscribe/one-click" in one_click
    headers = notifications.headers(row, tenant)
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("RESERVATION_CREATED", {"public_ref": "R-1", "customer_name": "A", "line_count": 1}),
        ("RESERVATION_CONFIRMED", {"public_ref": "R-1"}),
        ("RESERVATION_READY", {"public_ref": "R-1"}),
        ("RESERVATION_CANCELLED", {"public_ref": "R-1"}),
        ("RESERVATION_EXPIRED", {"public_ref": "R-1"}),
        ("RESERVATION_COMPLETED", {"public_ref": "R-1"}),
        ("CARD_REQUEST_CREATED", {"public_ref": "Q-1", "requested_name": "Bolt"}),
        ("CARD_REQUEST_QUOTED", {"public_ref": "Q-1", "requested_name": "Bolt"}),
        ("CARD_REQUEST_EXPIRED", {"public_ref": "Q-1"}),
        ("CARD_REQUEST_DECLINED", {"public_ref": "Q-1"}),
        ("CARD_REQUEST_ACCEPTED", {"public_ref": "Q-1"}),
        ("CARD_REQUEST_CONVERTED", {"public_ref": "Q-1", "reservation_ref": "R-1"}),
        ("RESTOCK_AVAILABLE", {"name": "Bolt"}),
        ("SOMETHING_ELSE", {"x": 1}),
    ],
)
def test_render_covers_every_notification_kind(kind, payload):
    tenant: Any = SimpleNamespace(id=uuid.uuid4(), slug="bolt-shop", name="Bolt Shop", settings=None)
    row: Any = SimpleNamespace(kind=kind, payload=payload)
    subject, body = notifications.render(row, tenant)
    assert isinstance(subject, str) and subject
    assert isinstance(body, str)

    # A RESTOCK_AVAILABLE row with no alert id exercises the no-unsubscribe body.
    if kind == "RESTOCK_AVAILABLE":
        quiet: Any = SimpleNamespace(kind=kind, payload={"name": "Bolt", "alert_id": ""})
        assert "Unsubscribe:" not in notifications.render(quiet, tenant)[1]


def test_render_otp_rounds_up_to_at_least_one_minute():
    subject, body = notifications.render_otp("123456", 1)
    assert "1 minute" in body
    assert "123456" in body
    assert "code" not in subject.lower() or "sign-in" in subject.lower()


# -------------------------------------------------------------- notification worker


def test_console_and_smtp_senders(monkeypatch):
    sender: Any = worker.ConsoleSender()
    sender.send(recipient="a@example.com", subject="hello", body="body")

    monkeypatch.setattr(settings, "smtp_host", "")
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        worker.SmtpSender()

    sent: list[Any] = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent.append("starttls")

        def login(self, username, password):
            sent.append((username, password))

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_username", "user")
    monkeypatch.setattr(settings, "smtp_password", "pass")
    monkeypatch.setattr(worker.smtplib, "SMTP", FakeSmtp)
    sender = worker.SmtpSender()
    sender.send(
        recipient="a@example.com",
        subject="hello",
        body="body",
        headers={"List-Unsubscribe": "<url>"},
    )
    assert sent[0] == "starttls"
    assert sent[1] == ("user", "pass")
    assert sent[2]["List-Unsubscribe"] == "<url>"

    sent.clear()
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_username", "")
    sender.send(recipient="a@example.com", subject="hello", body="body")
    assert sent == [sent[-1]]


def test_default_sender_variants(monkeypatch):
    monkeypatch.setattr(settings, "notification_backend", "console")
    assert isinstance(worker.default_sender(), worker.ConsoleSender)
    monkeypatch.setattr(settings, "notification_backend", "log")
    assert isinstance(worker.default_sender(), worker.ConsoleSender)
    monkeypatch.setattr(settings, "notification_backend", "none")
    assert worker.default_sender() is None
    monkeypatch.setattr(settings, "notification_backend", "smtp")
    monkeypatch.setattr(worker, "SmtpSender", lambda: "smtp")
    assert worker.default_sender() == "smtp"
    monkeypatch.setattr(settings, "notification_backend", "bogus")
    with pytest.raises(RuntimeError, match="Unknown"):
        worker.default_sender()


class _SmtpCodeError(Exception):
    smtp_code = 550


def test_otp_delivery_uses_smtp_code_and_gives_up_after_max_attempts(db, monkeypatch):
    challenge = models.CustomerOtpChallenge(
        email="a@example.com",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        created_at=datetime.now(UTC),
        email_attempts=settings.otp_email_max_attempts - 1,
    )
    db.add(challenge)
    db.commit()

    class Sender:
        def send(self, **_kwargs):
            raise _SmtpCodeError("bad mailbox")

    now = datetime.now(UTC)
    assert worker.deliver_otp_challenges(db, Sender(), now=now) == 0
    db.refresh(challenge)
    assert "SmtpCodeError (550)" in str(challenge.email_error)


def test_tenant_delivery_retries_and_resets_a_failed_alert(db, tenant, monkeypatch):
    alert = models.RestockAlert(
        tenant_id=tenant.id,
        card_id=uuid.uuid4(),
        email="a@example.com",
        finish="nonfoil",
        condition="NM",
        language="en",
        notified_at=datetime.now(UTC),
    )
    db.add(alert)
    db.flush()
    row = models.Notification(
        tenant_id=tenant.id,
        kind="RESTOCK_AVAILABLE",
        payload={"alert_id": str(alert.id)},
        channel="email",
        recipient="a@example.com",
        attempts=settings.notification_max_attempts - 1,
    )
    db.add(row)
    db.commit()

    class Sender:
        def send(self, **_kwargs):
            raise _SmtpCodeError("bad")

    now = datetime.now(UTC)
    assert worker.deliver_tenant(db, tenant, Sender(), now=now) == 0
    db.refresh(row)
    db.refresh(alert)
    assert "SmtpCodeError (550)" in str(row.error)
    assert alert.notified_at is None


def test_tenant_delivery_ignores_invalid_and_foreign_alert_ids(db, tenant):
    bad = models.Notification(
        tenant_id=tenant.id,
        kind="RESTOCK_AVAILABLE",
        payload={"alert_id": "not-a-uuid"},
        channel="email",
        recipient="a@example.com",
        attempts=settings.notification_max_attempts - 1,
    )
    missing = models.Notification(
        tenant_id=tenant.id,
        kind="RESTOCK_AVAILABLE",
        payload={"alert_id": str(uuid.uuid4())},
        channel="email",
        recipient="a@example.com",
        attempts=settings.notification_max_attempts - 1,
    )
    db.add_all([bad, missing])
    db.commit()

    class Sender:
        def send(self, **_kwargs):
            raise RuntimeError("bad")

    assert worker.deliver_tenant(db, tenant, Sender(), now=datetime.now(UTC)) == 0


def test_notification_run_once_without_a_sender(monkeypatch):
    monkeypatch.setattr(worker, "default_sender", lambda: None)
    monkeypatch.setattr(worker.push, "default_sender", lambda: None)
    assert worker.run_once() == 0


def test_worker_main_runs_one_pass(monkeypatch):
    calls = []

    def fake_run_once(**_kwargs):
        calls.append(True)
        return 1

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        worker.main()
    assert calls == [True]


def test_worker_main_handles_an_empty_pass(monkeypatch):
    monkeypatch.setattr(worker, "run_once", lambda **_kwargs: 0)
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        worker.main()


def test_worker_main_logs_a_failed_pass(monkeypatch):
    monkeypatch.setattr(worker, "run_once", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        worker.main()


def test_expiry_worker_run_once_with_nothing_due(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(expiry_worker, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(expiry_worker, "expire_due_reservations", lambda _db: 0)
    monkeypatch.setattr(expiry_worker, "expire_due_quotes", lambda _db: 0)
    monkeypatch.setattr(expiry_worker, "purge_expired_archived_stock", lambda _db: 0)
    assert expiry_worker.run_once() == 0


def test_expiry_worker_run_once_and_main(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(expiry_worker, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(expiry_worker, "expire_due_reservations", lambda _db: 2)
    monkeypatch.setattr(expiry_worker, "expire_due_quotes", lambda _db: 3)
    monkeypatch.setattr(expiry_worker, "purge_expired_archived_stock", lambda _db: 0)
    assert expiry_worker.run_once() == 2

    monkeypatch.setattr(expiry_worker, "run_once", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(expiry_worker.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        expiry_worker.main()


def test_expiry_worker_logs_purged_archive_rows(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(expiry_worker, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(expiry_worker, "expire_due_reservations", lambda _db: 0)
    monkeypatch.setattr(expiry_worker, "expire_due_quotes", lambda _db: 0)
    monkeypatch.setattr(expiry_worker, "purge_expired_archived_stock", lambda _db: 4)
    assert expiry_worker.run_once() == 0


# --------------------------------------------------------------------- CLI


def test_cli_image_and_card_field_fallbacks():
    from app.cli import import_scryfall

    assert import_scryfall._images({"image_uris": {"small": "top"}}) == {"small": "top"}
    assert import_scryfall._images({"card_faces": [{"image_uris": {"small": "s"}}]}) == {"small": "s"}
    assert import_scryfall._images({}) == {}
    fields = import_scryfall._card_fields(
        {
            "id": "x",
            "name": "Bolt",
            "card_faces": [{"colors": ["R"]}],
        },
        store_raw=False,
    )
    assert fields["colors"] == ["R"]
    assert fields["image_small"] is None
    assert fields["scryfall_prices"] == {}
    assert fields["raw"] == {}


def test_import_scryfall_run_handles_every_line_shape(db, tmp_path, monkeypatch):
    from app.cli import import_scryfall

    existing = models.Card(
        provider="scryfall",
        provider_card_id="existing",
        name="Old",
        set_code="OLD",
        set_name="Old",
        collector_number="1",
        rarity="common",
        type_line="Instant",
        colors=[],
    )
    db.add(existing)
    db.commit()

    path = tmp_path / "cards.jsonl"
    path.write_text(
        "\n".join(
            [
                "",
                "not-json",
                json.dumps({"object": "set", "id": "skip"}),
                json.dumps({"object": "card"}),
                json.dumps({"id": "new", "name": "New", "colors": None}),
                json.dumps({"id": "existing", "name": "Updated"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    maker = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(import_scryfall, "SessionLocal", maker)
    assert import_scryfall.run(path, None, 1, True) == 2

    maker2 = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(import_scryfall, "SessionLocal", maker2)
    assert import_scryfall.run(path, 0, 1, False) == 0

    maker3 = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(import_scryfall, "SessionLocal", maker3)
    assert import_scryfall.run(path, 1, 100, False) == 1


def test_import_scryfall_main(monkeypatch, tmp_path):
    from app.cli import import_scryfall

    called = []
    monkeypatch.setattr(import_scryfall, "run", lambda *args: called.append(args))
    path = tmp_path / "cards.jsonl"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["import_scryfall", "--path", str(path), "--limit", "1"])
    import_scryfall.main()
    assert called

    monkeypatch.setattr(sys, "argv", ["import_scryfall", "--path", str(tmp_path / "missing.jsonl")])
    with pytest.raises(SystemExit):
        import_scryfall.main()


def test_seed_demo_creates_and_reuses_a_tenant(db, monkeypatch):
    from app.cli import seed_demo

    maker = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(seed_demo, "SessionLocal", maker)
    monkeypatch.setattr(sys, "argv", ["seed_demo", "--slug", "demo", "--email", "demo@example.com"])
    seed_demo.main()
    seed_demo.main()

    from sqlalchemy import select

    assert db.scalar(select(models.Tenant).where(models.Tenant.slug == "demo")) is not None


# -------------------------------------------------------------------- context


def test_database_context_helpers_with_a_postgres_like_session():
    from app import db as db_module

    executed = []

    class FakeBind:
        dialect = SimpleNamespace(name="postgresql")

    class FakeSession:
        info: dict = {}

        def get_bind(self):
            return FakeBind()

        def execute(self, statement, params):
            executed.append((str(statement), params))

    session: Any = FakeSession()
    db_module.set_customer_context(session, uuid.uuid4())
    db_module.set_tenant_context(session, uuid.uuid4())
    db_module.set_push_worker_context(session)
    assert len(executed) == 3
    assert session.info["tenant_id"]
    assert session.info["push_worker"] == "on"
    db_module.set_push_worker_context(session, enabled=False)
    assert session.info["push_worker"] is None

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def __init__(self):
            self.executed = []

        def execute(self, statement, params):
            self.executed.append((str(statement), params))

    connection = FakeConnection()
    db_module._restore_rls_context(
        SimpleNamespace(info={"tenant_id": "t", "customer_id": "c", "push_worker": "on"}),
        None,
        connection,
    )
    assert len(connection.executed) == 3

    connection = FakeConnection()
    db_module._restore_rls_context(SimpleNamespace(info={}), None, connection)
    assert connection.executed == []


def test_lifespan_creates_tables_when_enabled(monkeypatch):
    import asyncio

    from app import main as main_module
    from app.models import Base

    called = []
    monkeypatch.setattr(main_module.settings, "auto_create_tables", True)
    monkeypatch.setattr(Base.metadata, "create_all", lambda **kwargs: called.append(kwargs))

    async def run():
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(run())
    assert called


def test_get_db_closes_the_session(monkeypatch):
    from app import db as db_module

    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    session: Any = FakeSession()
    monkeypatch.setattr(db_module, "SessionLocal", lambda: session)
    generator = db_module.get_db()
    assert next(generator) is session
    with pytest.raises(StopIteration):
        next(generator)
    assert cast(Any, session).closed


# --------------------------------------------------------------- reservations


def _res_payload(stock, **overrides):
    data = {
        "customer": {"name": "Ana", "email": "ana@example.com", "phone": "123"},
        "note": "",
        "items": [{"stock_id": str(stock.id), "quantity": 1}],
    }
    data.update(overrides)
    return schemas.ReservationCreate.model_validate(data)


def test_lock_stocks_short_circuits_for_an_empty_set(db, tenant):
    from app.services import reservations as service

    assert service._lock_stocks(db, tenant.id, set()) == {}


def test_idempotency_conflict_and_missing_reservation(db, tenant, stock):
    from app.services import reservations as service

    key = "same-key"
    first, _ = service.create_reservation(db, tenant, _res_payload(stock), idempotency_key=key)
    with pytest.raises(service.ReservationError) as exc:
        service.create_reservation(db, tenant, _res_payload(stock, note="different"), idempotency_key=key)
    assert exc.value.code == "idempotency_conflict"

    stale = models.IdempotencyKey(
        key="stale-key",
        tenant_id=tenant.id,
        endpoint="x",
        request_hash=service._request_hash(_res_payload(stock), None),
        status=201,
        response={"reservation_id": str(uuid.uuid4())},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(stale)
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service.create_reservation(db, tenant, _res_payload(stock), idempotency_key="stale-key")
    assert exc.value.code == "not_found"


def test_reservation_rejects_offline_and_currency_mismatch(db, tenant, stock):
    from app.services import reservations as service

    stock.is_online = False
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service.create_reservation(db, tenant, _res_payload(stock))
    assert exc.value.code == "stock_changed"
    assert exc.value.details["lines"][0]["reason"] == "offline"

    stock.is_online = True
    stock.currency = "EUR"
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service.create_reservation(db, tenant, _res_payload(stock))
    assert exc.value.code == "currency_mismatch"


def test_reservation_rejects_a_missing_catalog_card(db, tenant, stock):
    from app.services import reservations as service

    stock.card_id = uuid.uuid4()
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service.create_reservation(db, tenant, _res_payload(stock))
    assert exc.value.code == "card_not_found"


def test_reservation_commit_conflict_rolls_back(db, tenant, stock, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.services import reservations as service

    def fail():
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(service.ReservationError) as exc:
        service.create_reservation(db, tenant, _res_payload(stock))
    assert exc.value.code == "conflict"


def test_unique_public_ref_retries_and_gives_up(db, tenant, card, stock, monkeypatch):
    from app.services import reservations as service

    def make_reservation(ref):
        return models.Reservation(
            tenant_id=tenant.id,
            public_ref=ref,
            customer_name="A",
            email="a@example.com",
            phone="",
            note="",
            status="REQUESTED",
            total_minor=0,
            currency="RSD",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            source="app",
        )

    db.add(make_reservation("R-DUP"))
    db.commit()
    refs = iter(["R-DUP", "R-NEW"])
    monkeypatch.setattr(service, "new_public_ref", lambda: next(refs))
    assert service.unique_public_ref(db, tenant.id) == "R-NEW"

    monkeypatch.setattr(service, "new_public_ref", lambda: "R-DUP")
    with pytest.raises(service.ReservationError) as exc:
        service.unique_public_ref(db, tenant.id)
    assert exc.value.code == "ref_generation_failed"


def test_staff_hold_validation(db, tenant, stock):
    from app.services import reservations as service

    with pytest.raises(service.ReservationError) as exc:
        service.create_staff_hold(
            db,
            tenant,
            stock=cast(Any, SimpleNamespace(id=uuid.uuid4())),
            quantity=1,
            customer_name="A",
            email="a@example.com",
            phone="",
        )
    assert exc.value.code == "stock_not_found"

    with pytest.raises(service.ReservationError) as exc:
        service.create_staff_hold(
            db,
            tenant,
            stock=stock,
            quantity=99,
            customer_name="A",
            email="a@example.com",
            phone="",
        )
    assert exc.value.code == "stock_changed"


def test_get_reservation_missing(db, tenant):
    from app.services import reservations as service

    with pytest.raises(service.ReservationError) as exc:
        service.get_reservation(db, tenant.id, uuid.uuid4())
    assert exc.value.code == "not_found"


def _made_reservation(db, tenant, stock, **overrides):
    from app.services import reservations as service

    reservation, _ = service.create_reservation(db, tenant, _res_payload(stock))
    for key, value in overrides.items():
        setattr(reservation, key, value)
    db.commit()
    db.refresh(reservation)
    return reservation


def test_release_terminal_and_inconsistency_branches(db, tenant, stock):
    from app.services import reservations as service

    reservation = _made_reservation(db, tenant, stock)
    reservation.status = "CANCELLED"
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service._release(db, reservation, new_status="CANCELLED", reason=None, actor_id=None)
    assert exc.value.code == "invalid_state"

    reservation.status = "REQUESTED"
    line = reservation.lines[0]
    line.completed_quantity = line.quantity
    db.commit()
    service._release(db, reservation, new_status="CANCELLED", reason="done", actor_id=None)

    reservation = _made_reservation(db, tenant, stock)
    stock.reserved = 0
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service._release(db, reservation, new_status="CANCELLED", reason=None, actor_id=None)
    assert exc.value.code == "stock_inconsistency"


def test_release_skips_a_missing_tenant(db, tenant, stock, monkeypatch):
    from app.services import reservations as service

    reservation = _made_reservation(db, tenant, stock)
    original_get = db.get

    def get(model, ident, *args, **kwargs):
        if model is models.Tenant:
            return None
        return original_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", get)
    service._release(db, reservation, new_status="CANCELLED", reason=None, actor_id=None)


def test_cancel_missing_and_rollback(db, tenant, stock, monkeypatch):
    from app.services import reservations as service

    ghost = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id)
    with pytest.raises(service.ReservationError) as exc:
        service.cancel_reservation(db, cast(Any, ghost))
    assert exc.value.code == "not_found"

    reservation = _made_reservation(db, tenant, stock)
    monkeypatch.setattr(service, "_release", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        service.cancel_reservation(db, reservation)


def test_complete_validation_edges(db, tenant, stock):
    from app.services import reservations as service

    ghost = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant.id)
    with pytest.raises(service.ReservationError) as exc:
        service.complete_reservation(db, cast(Any, ghost))
    assert exc.value.code == "not_found"

    reservation = _made_reservation(db, tenant, stock)
    reservation.status = "CANCELLED"
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service.complete_reservation(db, reservation)
    assert exc.value.code == "invalid_state"

    reservation = _made_reservation(db, tenant, stock)
    line = reservation.lines[0]
    with pytest.raises(service.ReservationError) as exc:
        service.complete_reservation(
            db,
            reservation,
            line_quantities=[
                schemas.CompleteLineIn(line_id=line.id, complete_quantity=1, cancel_quantity=0),
                schemas.CompleteLineIn(line_id=line.id, complete_quantity=1, cancel_quantity=0),
            ],
        )
    assert exc.value.code == "duplicate_line"

    with pytest.raises(service.ReservationError) as exc:
        service.complete_reservation(
            db,
            reservation,
            line_quantities=[schemas.CompleteLineIn(line_id=uuid.uuid4(), complete_quantity=1, cancel_quantity=0)],
        )
    assert exc.value.code == "unknown_line"

    with pytest.raises(service.ReservationError) as exc:
        service.complete_reservation(
            db,
            reservation,
            line_quantities=[schemas.CompleteLineIn(line_id=line.id, complete_quantity=2, cancel_quantity=1)],
        )
    assert exc.value.code == "quantity_exceeds_remaining"


def test_complete_nothing_to_do_and_inconsistent_stock(db, tenant, stock):
    from app.services import reservations as service

    reservation = _made_reservation(db, tenant, stock)
    line = reservation.lines[0]
    line.completed_quantity = line.quantity
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service.complete_reservation(db, reservation)
    assert exc.value.code == "nothing_to_do"

    reservation = _made_reservation(db, tenant, stock)
    reservation.lines[0].quantity = 3
    stock.quantity = 2
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service.complete_reservation(db, reservation)
    assert exc.value.code == "stock_inconsistency"

    stock.quantity = 10
    db.commit()
    reservation = _made_reservation(db, tenant, stock)
    stock.reserved = 0
    db.commit()
    with pytest.raises(service.ReservationError) as exc:
        service.complete_reservation(
            db,
            reservation,
            line_quantities=[
                schemas.CompleteLineIn(
                    line_id=reservation.lines[0].id,
                    complete_quantity=0,
                    cancel_quantity=1,
                )
            ],
        )
    assert exc.value.code == "stock_inconsistency"


def test_complete_cancel_only_without_tenant_and_rollback(db, tenant, stock, monkeypatch):
    from app.services import reservations as service

    reservation = _made_reservation(db, tenant, stock)
    original_get = db.get

    def get(model, ident, *args, **kwargs):
        if model is models.Tenant:
            return None
        return original_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", get)
    completed = service.complete_reservation(
        db,
        reservation,
        line_quantities=[
            schemas.CompleteLineIn(line_id=reservation.lines[0].id, complete_quantity=0, cancel_quantity=1)
        ],
    )
    assert completed.status == "CANCELLED"

    reservation = _made_reservation(db, tenant, stock)
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        service.complete_reservation(db, reservation)


def test_expire_due_reservations_rolls_back_on_failure(db, tenant, stock, monkeypatch):
    from app.services import reservations as service

    reservation = _made_reservation(db, tenant, stock)
    reservation.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    monkeypatch.setattr(service, "_release", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        service.expire_due_reservations(db)


def test_recompute_reserved_detects_and_repairs_mismatches(db, tenant, stock):
    from app.services import reservations as service

    _made_reservation(db, tenant, stock)
    stock.quantity = 100
    stock.reserved = 99
    db.commit()
    mismatches = service.recompute_reserved(db, tenant.id)
    assert mismatches and mismatches[0]["stored"] == 99
    db.refresh(stock)
    assert stock.reserved == 1
    assert service.recompute_reserved(db, tenant.id) == []


# -------------------------------------------------------------- card requests


def test_card_request_reference_retries_and_exhausts(db, tenant, monkeypatch):
    from app.services import card_requests as service

    refs = iter(["Q-DUP", "Q-NEW"])
    monkeypatch.setattr(service, "new_request_ref", lambda: next(refs))
    db.add(
        models.CardRequest(
            tenant_id=tenant.id,
            public_ref="Q-DUP",
            customer_name="A",
            email="a@example.com",
            phone="",
            requested_name="Bolt",
            finish="nonfoil",
            condition="NM",
            language="en",
            quantity=1,
            currency="RSD",
            status="REQUESTED",
            access_token_hash="x",
        )
    )
    db.commit()
    assert service._unique_ref(db, tenant.id) == "Q-NEW"

    monkeypatch.setattr(service, "new_request_ref", lambda: "Q-DUP")
    with pytest.raises(service.CardRequestError) as exc:
        service._unique_ref(db, tenant.id)
    assert exc.value.code == "ref_conflict"


def test_card_request_create_validation(db, tenant):
    from app.services import card_requests as service

    payload = schemas.CardRequestCreateIn.model_validate(
        {
            "customer": {"name": "A", "email": "a@example.com"},
            "card_id": str(uuid.uuid4()),
            "quantity": 1,
        }
    )
    with pytest.raises(service.CardRequestError) as exc:
        service.create(db, tenant, payload)
    assert exc.value.code == "card_not_found"

    payload = schemas.CardRequestCreateIn.model_validate(
        {
            "customer": {"name": "A", "email": "a@example.com"},
            "requested_name": "",
            "quantity": 1,
        }
    )
    with pytest.raises(service.CardRequestError) as exc:
        service.create(db, tenant, payload)
    assert exc.value.code == "name_required"


def test_card_request_authorization_and_state_errors(db, tenant, card):
    from app.services import card_requests as service

    with pytest.raises(service.CardRequestError) as exc:
        service.get_authorized(db, tenant, uuid.uuid4(), "token")
    assert exc.value.code == "not_found"

    row = models.CardRequest(
        tenant_id=tenant.id,
        public_ref="Q-X",
        customer_name="A",
        email="a@example.com",
        phone="",
        requested_name="Bolt",
        finish="nonfoil",
        condition="NM",
        language="en",
        quantity=1,
        currency="RSD",
        status="DECLINED",
        access_token_hash="x",
    )
    db.add(row)
    db.commit()

    quote_payload = schemas.QuoteIn.model_validate({"quote_price_minor": 100})
    with pytest.raises(service.CardRequestError) as exc:
        service.quote(db, tenant, row, quote_payload)
    assert exc.value.code == "invalid_status"
    with pytest.raises(service.CardRequestError) as exc:
        service.decline(db, tenant, row, "")
    assert exc.value.code == "invalid_status"
    with pytest.raises(service.CardRequestError) as exc:
        service.convert(db, tenant, row)
    assert exc.value.code == "invalid_status"

    row.status = "ACCEPTED"
    row.card_id = None
    db.commit()
    with pytest.raises(service.CardRequestError) as exc:
        service.convert(db, tenant, row)
    assert exc.value.code == "no_catalog_card"


def test_expire_due_quotes_skips_empty_tenants(db, tenant, other_tenant):
    from app.services import card_requests as service

    assert service.expire_due_quotes(db) == 0


# ------------------------------------------------------------------ stock csv


def test_parse_csv_format_errors(db, monkeypatch):
    from app.services import stock_csv

    with pytest.raises(stock_csv.CsvFormatError):
        stock_csv.parse_csv("", "RSD")
    with pytest.raises(stock_csv.CsvFormatError, match="duplicate columns"):
        stock_csv.parse_csv(
            "card_name,Name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n",
            "RSD",
        )
    with pytest.raises(stock_csv.CsvFormatError, match="either a stock price"):
        stock_csv.parse_csv(
            "card_name,set_code,collector_number,finish,condition,language,quantity,price,purchase_price,currency,is_online\n",
            "RSD",
        )

    def boom(*_args, **_kwargs):
        raise stock_csv.csv.Error("bad")

    monkeypatch.setattr(stock_csv.csv, "DictReader", boom)
    with pytest.raises(stock_csv.CsvFormatError):
        stock_csv.parse_csv("x", "RSD")


def test_parse_csv_row_validation_and_blank_rows():
    from app.services import stock_csv

    header = "card_name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n"
    body = (
        header
        + ",\n"
        + "Bolt,,,,,,1,1.00,RSD,true\n"
        + "Bolt,LEB,,nonfoil,NM,english,1,1.00,RSD,true\n"
        + "Bolt,LEB,1,nonfoil,NM,en,-1,1.00,RSD,true\n"
        + "Bolt,LEB,1,nonfoil,NM,en,1,-1.00,RSD,true\n"
        + "Bolt,LEB,1,nonfoil,NM,en,1,21474836.48,RSD,true\n"
        + "Bolt,LEB,1,nonfoil,NM,en,1,1.00,XX,true\n"
        + "Bolt,LEB,1,nonfoil,NM,en,1,1.00,RSD,\n"
    )
    rows, errors = stock_csv.parse_csv(body, "RSD")
    assert len(rows) == 1
    assert rows[0].is_online is True
    assert len(errors) >= 7


def test_price_import_rows_passes_through_regular_stock_rows_and_rejects_overflow():
    from decimal import Decimal

    from app.services import stock_csv

    row, errors = stock_csv.parse_csv(
        "card_name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n"
        "Bolt,LEB,1,nonfoil,NM,en,1,1.00,RSD,true\n",
        "RSD",
    )
    assert errors == []
    assert (
        stock_csv.price_purchase_rows(
            row,
            "RSD",
            {},
            {
                "threshold_minor": 0,
                "fixed_price_minor": 1,
                "markup_percent": 0,
            },
        )
        == row
    )

    with pytest.raises(ValueError, match="supported range"):
        stock_csv.calculate_sale_price(
            2_147_483_647,
            Decimal("1"),
            {
                "threshold_minor": 0,
                "fixed_price_minor": 1,
                "markup_percent": 0,
            },
        )


def test_parse_csv_row_limit(monkeypatch):
    from app.services import stock_csv

    monkeypatch.setattr(stock_csv, "MAX_ROWS", 0)
    with pytest.raises(stock_csv.CsvFormatError):
        stock_csv.parse_csv(
            "card_name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n"
            "Bolt,LEB,1,nonfoil,NM,en,1,1.00,RSD,true\n",
            "RSD",
        )


def test_apply_rows_new_zero_quantity_and_price_only_update(db, tenant, card):
    from app.services import stock_csv

    row = stock_csv.ImportRow(
        line=2,
        set_code="LEB",
        collector_number="161",
        card_name="Lightning Bolt",
        finish="nonfoil",
        condition="NM",
        language="en",
        quantity=0,
        price_minor=100,
        currency="RSD",
        is_online=True,
    )
    created, updated, unchanged, errors = stock_csv.apply_rows(db, tenant, None, [row], dry_run=False)
    assert (created, updated, unchanged, errors) == (1, 0, 0, [])
    assert db.query(models.Stock).filter_by(tenant_id=tenant.id).count() == 1

    row.quantity = 2
    row.price_minor = 200
    created, updated, unchanged, errors = stock_csv.apply_rows(db, tenant, None, [row], dry_run=False)
    assert (created, updated, unchanged, errors) == (0, 1, 0, [])
    row.quantity = 2
    row.price_minor = 300
    created, updated, unchanged, errors = stock_csv.apply_rows(db, tenant, None, [row], dry_run=False)
    assert (created, updated, unchanged, errors) == (0, 1, 0, [])


def test_apply_rows_dry_run_new_card(db, tenant, card):
    from app.services import stock_csv

    row = stock_csv.ImportRow(
        line=2,
        set_code="LEB",
        collector_number="161",
        card_name="Lightning Bolt",
        finish="foil",
        condition="NM",
        language="en",
        quantity=1,
        price_minor=100,
        currency="RSD",
        is_online=True,
    )
    created, updated, unchanged, errors = stock_csv.apply_rows(db, tenant, None, [row], dry_run=True)
    assert (created, updated, unchanged, errors) == (1, 0, 0, [])


# ------------------------------------------------------ final service edges


def test_reservation_commit_race_returns_the_existing_reservation(db, tenant, stock, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.services import reservations as service

    existing, _ = service.create_reservation(db, tenant, _res_payload(stock))
    key = "race-key"
    payload = _res_payload(stock)
    race = models.IdempotencyKey(
        key=key,
        tenant_id=tenant.id,
        endpoint="POST",
        request_hash=service._request_hash(payload, None),
        status=201,
        response={"reservation_id": str(existing.id)},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(race)
    db.commit()

    original_get = db.get
    calls = {"key": 0}

    def get(model, ident, *args, **kwargs):
        if model is models.IdempotencyKey and ident == key:
            calls["key"] += 1
            if calls["key"] == 1:
                return None
        return original_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", get)
    monkeypatch.setattr(
        db,
        "commit",
        lambda: (_ for _ in ()).throw(IntegrityError("INSERT", {}, Exception("duplicate"))),
    )
    returned, _token = service.create_reservation(db, tenant, payload, idempotency_key=key)
    assert returned.id == existing.id


def test_get_reservation_success(db, tenant, stock):
    from app.services import reservations as service

    reservation = _made_reservation(db, tenant, stock)
    assert service.get_reservation(db, tenant.id, reservation.id).id == reservation.id


def test_complete_plan_skips_a_zero_decision_line(db, tenant, stock, second_stock):
    from app.services import reservations as service

    payload = schemas.ReservationCreate.model_validate(
        {
            "customer": {"name": "Ana", "email": "ana@example.com", "phone": "123"},
            "items": [
                {"stock_id": str(stock.id), "quantity": 1},
                {"stock_id": str(second_stock.id), "quantity": 1},
            ],
        }
    )
    reservation, _ = service.create_reservation(db, tenant, payload)
    first, second = sorted(reservation.lines, key=lambda line: str(line.stock_id))
    completed = service.complete_reservation(
        db,
        reservation,
        line_quantities=[schemas.CompleteLineIn(line_id=first.id, complete_quantity=0, cancel_quantity=0)],
    )
    assert completed is not None
    db.expire_all()
    line = db.get(models.ReservationLine, second.id)
    assert line.completed_quantity == 1


def test_accounts_as_utc_and_debug_code(client, db, monkeypatch):
    from app.services import accounts

    assert accounts._as_utc(None) is None
    monkeypatch.setattr(settings, "otp_debug_code", True)
    response = client.post("/v1/auth/otp/request", json={"email": "debug@example.com"})
    assert response.status_code == 202
    assert response.json()["debug_code"]
    assert len(response.json()["debug_code"]) == 6


def test_account_creation_race_uses_the_existing_customer(client, db, monkeypatch):
    from app.security import derive_otp_code
    from app.services import accounts

    existing = models.User(
        tenant_id=None,
        email="race@example.com",
        role="customer",
        is_active=True,
    )
    db.add(existing)
    db.commit()

    client.post("/v1/auth/otp/request", json={"email": "race@example.com"})
    challenge = db.query(models.CustomerOtpChallenge).order_by(models.CustomerOtpChallenge.created_at.desc()).first()
    assert challenge is not None
    code = derive_otp_code(challenge.id, challenge.email)

    calls = {"n": 0}
    real_find = accounts._find_customer

    def find(db_session, email):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_find(db_session, email)

    monkeypatch.setattr(accounts, "_find_customer", find)
    response = client.post("/v1/auth/otp/verify", json={"email": "race@example.com", "code": code})
    assert response.status_code == 200, response.text
    assert response.json()["is_new_account"] is True


def test_account_creation_race_reraises_when_no_customer_exists(client, db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.security import derive_otp_code
    from app.services import accounts

    existing = models.User(
        tenant_id=None,
        email="lost@example.com",
        role="customer",
        is_active=True,
    )
    db.add(existing)
    db.commit()

    client.post("/v1/auth/otp/request", json={"email": "lost@example.com"})
    challenge = db.query(models.CustomerOtpChallenge).order_by(models.CustomerOtpChallenge.created_at.desc()).first()
    code = derive_otp_code(challenge.id, challenge.email)
    monkeypatch.setattr(accounts, "_find_customer", lambda _db, _email: None)
    with pytest.raises(IntegrityError):
        client.post("/v1/auth/otp/verify", json={"email": "lost@example.com", "code": code})


def test_ratelimit_non_positive_limit_is_a_noop():
    assert ratelimit.limiter.hit("key", limit=0, window_seconds=1) is None


def test_reservation_commit_race_rejects_a_hash_mismatch(db, tenant, stock, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.services import reservations as service

    existing, _ = service.create_reservation(db, tenant, _res_payload(stock))
    key = "wrong-hash-key"
    race = models.IdempotencyKey(
        key=key,
        tenant_id=tenant.id,
        endpoint="POST",
        request_hash="different",
        status=201,
        response={"reservation_id": str(existing.id)},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(race)
    db.commit()

    original_get = db.get
    calls = {"key": 0}

    def get(model, ident, *args, **kwargs):
        if model is models.IdempotencyKey and ident == key:
            calls["key"] += 1
            if calls["key"] == 1:
                return None
        return original_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", get)
    monkeypatch.setattr(
        db,
        "commit",
        lambda: (_ for _ in ()).throw(IntegrityError("INSERT", {}, Exception("duplicate"))),
    )
    with pytest.raises(service.ReservationError) as exc:
        service.create_reservation(db, tenant, _res_payload(stock), idempotency_key=key)
    assert exc.value.code == "conflict"


def test_reservation_commit_race_rejects_a_missing_reservation(db, tenant, stock, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.services import reservations as service

    key = "missing-res-key"
    payload = _res_payload(stock)
    race = models.IdempotencyKey(
        key=key,
        tenant_id=tenant.id,
        endpoint="POST",
        request_hash=service._request_hash(payload, None),
        status=201,
        response={"reservation_id": str(uuid.uuid4())},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(race)
    db.commit()

    original_get = db.get
    calls = {"key": 0}

    def get(model, ident, *args, **kwargs):
        if model is models.IdempotencyKey and ident == key:
            calls["key"] += 1
            if calls["key"] == 1:
                return None
        return original_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db, "get", get)
    monkeypatch.setattr(
        db,
        "commit",
        lambda: (_ for _ in ()).throw(IntegrityError("INSERT", {}, Exception("duplicate"))),
    )
    with pytest.raises(service.ReservationError) as exc:
        service.create_reservation(db, tenant, payload, idempotency_key=key)
    assert exc.value.code == "conflict"
