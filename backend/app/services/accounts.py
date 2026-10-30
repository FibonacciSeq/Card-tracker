"""Customer OTP authentication and guest-row claiming."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.db import set_customer_context, set_tenant_context
from app.security import (
    create_customer_access_token,
    derive_otp_code,
    normalize_email,
)
from app.services import ratelimit


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _email_rate_key(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]


def _latest_challenge(db: Session, email: str) -> models.CustomerOtpChallenge | None:
    return db.scalar(
        select(models.CustomerOtpChallenge)
        .where(models.CustomerOtpChallenge.email == email)
        .order_by(models.CustomerOtpChallenge.created_at.desc())
        .limit(1)
    )


def _find_customer(db: Session, email: str) -> models.User | None:
    return db.scalar(
        select(models.User).where(
            models.User.tenant_id.is_(None),
            models.User.role == "customer",
            func.lower(models.User.email) == email,
        )
    )


def request_otp(db: Session, email: str, request: Request) -> schemas.OtpRequestOut:
    email = normalize_email(email)
    email_key = _email_rate_key(email)

    ratelimit.enforce(
        request,
        scope="otp-request-ip",
        limit=settings.otp_request_ip_limit,
        window_seconds=settings.otp_request_ip_window_seconds,
    )
    ratelimit.enforce(
        request,
        scope="otp-request-email",
        limit=settings.otp_request_email_limit,
        window_seconds=settings.otp_request_email_window_seconds,
        extra=email_key,
    )

    now = _now()
    latest = _latest_challenge(db, email)
    latest_created = _as_utc(latest.created_at) if latest else None
    if latest_created is not None:
        elapsed = (now - latest_created).total_seconds()
        if elapsed < settings.otp_resend_seconds:
            retry_after = max(1, int(settings.otp_resend_seconds - elapsed))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Please wait before requesting another code.",
                headers={"Retry-After": str(retry_after)},
            )

    # Only the newest challenge can be used. Consuming unsent rows also stops
    # the worker from delivering a code the customer can no longer redeem.
    db.execute(
        update(models.CustomerOtpChallenge)
        .where(
            models.CustomerOtpChallenge.email == email,
            models.CustomerOtpChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    challenge = models.CustomerOtpChallenge(
        email=email,
        expires_at=now + timedelta(seconds=settings.otp_expiry_seconds),
        created_at=now,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    debug_code = None
    if settings.otp_debug_code and settings.environment in ("development", "test"):
        debug_code = derive_otp_code(challenge.id, email)

    return schemas.OtpRequestOut(
        expires_in=settings.otp_expiry_seconds,
        resend_after=settings.otp_resend_seconds,
        debug_code=debug_code,
    )


def _claim_guest_rows(db: Session, customer: models.User) -> schemas.ClaimedOut:
    """Attach unowned rows with the verified email, one tenant at a time.

    RLS hides tenant-owned rows without a tenant context, so a global email
    update is not possible. Shop counts are small enough for this loop.
    """
    counts = schemas.ClaimedOut()
    tenant_ids = list(db.scalars(select(models.Tenant.id)).all())
    for tenant_id in tenant_ids:
        set_tenant_context(db, tenant_id)
        counts.reservations += _updated(
            getattr(
                db.execute(
                    update(models.Reservation)
                    .where(
                        models.Reservation.tenant_id == tenant_id,
                        models.Reservation.customer_id.is_(None),
                        func.lower(models.Reservation.email) == customer.email,
                    )
                    .values(customer_id=customer.id)
                    .execution_options(synchronize_session=False)
                ),
                "rowcount",
                0,
            )
        )
        counts.card_requests += _updated(
            getattr(
                db.execute(
                    update(models.CardRequest)
                    .where(
                        models.CardRequest.tenant_id == tenant_id,
                        models.CardRequest.customer_id.is_(None),
                        func.lower(models.CardRequest.email) == customer.email,
                    )
                    .values(customer_id=customer.id)
                    .execution_options(synchronize_session=False)
                ),
                "rowcount",
                0,
            )
        )
        counts.restock_alerts += _updated(
            getattr(
                db.execute(
                    update(models.RestockAlert)
                    .where(
                        models.RestockAlert.tenant_id == tenant_id,
                        models.RestockAlert.customer_id.is_(None),
                        func.lower(models.RestockAlert.email) == customer.email,
                    )
                    .values(customer_id=customer.id)
                    .execution_options(synchronize_session=False)
                ),
                "rowcount",
                0,
            )
        )
        db.flush()
    return counts


def _updated(rowcount: int | None) -> int:
    return max(0, int(rowcount or 0))


def verify_otp(
    db: Session,
    email: str,
    code: str,
    request: Request,
) -> schemas.CustomerTokenOut:
    email = normalize_email(email)
    email_key = _email_rate_key(email)

    ratelimit.enforce(
        request,
        scope="otp-verify-ip",
        limit=settings.otp_verify_ip_limit,
        window_seconds=settings.otp_verify_ip_window_seconds,
    )
    ratelimit.enforce(
        request,
        scope="otp-verify-email",
        limit=settings.otp_verify_email_limit,
        window_seconds=settings.otp_verify_email_window_seconds,
        extra=email_key,
    )

    now = _now()
    challenge = db.scalar(
        select(models.CustomerOtpChallenge)
        .where(
            models.CustomerOtpChallenge.email == email,
            models.CustomerOtpChallenge.consumed_at.is_(None),
        )
        .order_by(models.CustomerOtpChallenge.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    expires_at = _as_utc(challenge.expires_at) if challenge else None
    if challenge is None or expires_at is None or expires_at <= now or challenge.attempts >= settings.otp_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired code",
        )

    expected = derive_otp_code(challenge.id, email)
    if not hmac.compare_digest(expected, code):
        challenge.attempts += 1
        if challenge.attempts >= settings.otp_max_attempts:
            challenge.consumed_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired code",
        )

    challenge.consumed_at = now
    customer = _find_customer(db, email)
    created = customer is None
    if customer is None:
        candidate = models.User(
            tenant_id=None,
            email=email,
            role="customer",
            is_active=True,
            email_verified_at=now,
        )
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            customer = candidate
        except IntegrityError:
            # Another verification created the account first. The savepoint
            # rolled back only the failed insert; the challenge is still ours.
            customer = _find_customer(db, email)
            if customer is None:
                raise

    if not customer.is_active:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is unavailable.",
        )

    if customer.email_verified_at is None:
        customer.email_verified_at = now
    customer.email = email
    db.flush()

    claimed = _claim_guest_rows(db, customer)
    db.commit()

    # Keep the response independent of any tenant context left by claiming.
    set_customer_context(db, customer.id)
    return schemas.CustomerTokenOut(
        access_token=create_customer_access_token(customer.id),
        expires_in=settings.customer_access_token_minutes * 60,
        is_new_account=created,
        customer=schemas.CustomerOut.model_validate(customer),
        claimed=claimed,
    )


def _push_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_push_token(
    db: Session,
    customer: models.User,
    payload: schemas.PushTokenIn,
) -> schemas.PushTokenOut:
    """Register or refresh one native APNs/FCM token for the signed-in customer."""
    token = payload.token.strip()
    token_hash = _push_token_hash(token)
    now = _now()
    row = db.scalar(select(models.PushToken).where(models.PushToken.token_hash == token_hash))
    if row is not None:
        if row.user_id != customer.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This device token is registered to another account.",
            )
        row.token = token
        row.platform = payload.platform
        row.last_seen_at = now
        row.revoked_at = None
    else:
        row = models.PushToken(
            user_id=customer.id,
            token=token,
            token_hash=token_hash,
            platform=payload.platform,
            created_at=now,
            last_seen_at=now,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return schemas.PushTokenOut.model_validate(row)


def unregister_push_token(db: Session, customer: models.User, token: str) -> None:
    """Idempotently revoke a token; unknown or foreign tokens are ignored."""
    token_hash = _push_token_hash(token.strip())
    row = db.scalar(
        select(models.PushToken).where(
            models.PushToken.user_id == customer.id,
            models.PushToken.token_hash == token_hash,
        )
    )
    if row is None or row.revoked_at is not None:
        return
    row.revoked_at = _now()
    db.commit()
