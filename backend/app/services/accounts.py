"""Customer OTP authentication and guest-row claiming."""

from __future__ import annotations

import hashlib
import hmac
import uuid
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
    create_customer_refresh_token,
    derive_otp_code,
    normalize_email,
)
from app.services import audit, ratelimit


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
            models.CustomerOtpChallenge.user_id.is_(None),
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
            models.CustomerOtpChallenge.user_id.is_(None),
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

    set_customer_context(db, customer.id)
    audit.record_customer(
        db,
        customer_id=customer.id,
        action="account.login",
        summary="Customer signed in",
        data={"is_new_account": created},
    )
    claimed = _claim_guest_rows(db, customer)
    db.commit()

    # Keep the response independent of any tenant context left by claiming.
    set_customer_context(db, customer.id)
    refresh_token = _issue_refresh_token(db, customer.id)
    db.commit()
    return schemas.CustomerTokenOut(
        access_token=create_customer_access_token(customer.id),
        expires_in=settings.customer_access_token_minutes * 60,
        refresh_token=refresh_token,
        refresh_expires_in=settings.customer_refresh_token_minutes * 60,
        is_new_account=created,
        customer=schemas.CustomerOut.model_validate(customer),
        claimed=claimed,
    )


def request_email_change(
    db: Session,
    customer: models.User,
    email: str,
    request: Request,
) -> schemas.OtpRequestOut:
    """Send a confirmation code to the new address before changing it."""
    new_email = normalize_email(email)

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
        extra=_email_rate_key(new_email),
    )

    if new_email == customer.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This is already your email address.",
        )

    other = _find_customer(db, new_email)
    if other is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email address is already in use.",
        )

    now = _now()
    latest = _latest_challenge(db, new_email)
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

    # One pending change per account; an older target address must not remain
    # redeemable after the customer asks for a different one.
    db.execute(
        update(models.CustomerOtpChallenge)
        .where(
            models.CustomerOtpChallenge.user_id == customer.id,
            models.CustomerOtpChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    challenge = models.CustomerOtpChallenge(
        email=new_email,
        user_id=customer.id,
        expires_at=now + timedelta(seconds=settings.otp_expiry_seconds),
        created_at=now,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    debug_code = None
    if settings.otp_debug_code and settings.environment in ("development", "test"):
        debug_code = derive_otp_code(challenge.id, new_email)

    return schemas.OtpRequestOut(
        expires_in=settings.otp_expiry_seconds,
        resend_after=settings.otp_resend_seconds,
        debug_code=debug_code,
    )


def verify_email_change(
    db: Session,
    customer: models.User,
    email: str,
    code: str,
    request: Request,
) -> schemas.CustomerTokenOut:
    """Apply an email change after the customer proves control of the address."""
    new_email = normalize_email(email)
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
        extra=_email_rate_key(new_email),
    )

    now = _now()
    challenge = db.scalar(
        select(models.CustomerOtpChallenge)
        .where(
            models.CustomerOtpChallenge.email == new_email,
            models.CustomerOtpChallenge.user_id == customer.id,
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

    expected = derive_otp_code(challenge.id, new_email)
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
    other = _find_customer(db, new_email)
    if other is not None:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email address is already in use.",
        )

    old_email = customer.email
    customer.email = new_email
    customer.email_verified_at = now
    db.flush()

    claimed = _claim_guest_rows(db, customer)
    # Email is an account identifier, so a change ends every other session.
    revoke_customer_refresh_tokens(
        db,
        customer.id,
        commit=False,
        action="account.sessions_revoked",
    )
    refresh_token = _issue_refresh_token(db, customer.id)
    audit.record_customer(
        db,
        customer_id=customer.id,
        action="account.email_changed",
        summary="Customer email changed",
        data={
            "old_email": old_email,
            "new_email": new_email,
            "claimed": claimed.model_dump(),
        },
    )
    db.commit()

    set_customer_context(db, customer.id)
    return schemas.CustomerTokenOut(
        access_token=create_customer_access_token(customer.id),
        expires_in=settings.customer_access_token_minutes * 60,
        refresh_token=refresh_token,
        refresh_expires_in=settings.customer_refresh_token_minutes * 60,
        is_new_account=False,
        customer=schemas.CustomerOut.model_validate(customer),
        claimed=claimed,
    )


def _refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_refresh_token(db: Session, customer_id: uuid.UUID) -> str:
    token = create_customer_refresh_token()
    row = models.CustomerRefreshToken(
        user_id=customer_id,
        token_hash=_refresh_token_hash(token),
        issued_at=_now(),
        expires_at=_now() + timedelta(minutes=settings.customer_refresh_token_minutes),
    )
    db.add(row)
    db.flush()
    return token


def revoke_customer_refresh_tokens(
    db: Session,
    customer_id: uuid.UUID,
    refresh_token: str | None = None,
    *,
    action: str = "account.sessions_revoked",
    commit: bool = True,
) -> None:
    stmt = select(models.CustomerRefreshToken).where(models.CustomerRefreshToken.user_id == customer_id)
    if refresh_token is not None:
        stmt = stmt.where(models.CustomerRefreshToken.token_hash == _refresh_token_hash(refresh_token))
    rows = db.scalars(stmt).all()
    for row in rows:
        row.revoked_at = _now()
    audit.record_customer(
        db,
        customer_id=customer_id,
        action=action,
        summary="Customer signed out" if action == "account.logout" else "Customer sessions revoked",
        data={"token_count": len(rows), "single_token": refresh_token is not None},
    )
    if commit:
        db.commit()


def refresh_customer_session(db: Session, refresh_token: str) -> schemas.CustomerTokenOut:
    token_hash = _refresh_token_hash(refresh_token)
    row = db.scalar(
        select(models.CustomerRefreshToken)
        .where(models.CustomerRefreshToken.token_hash == token_hash)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    expires_at = _as_utc(row.expires_at)
    if row.revoked_at is not None or expires_at is None or expires_at <= _now():
        row.revoked_at = _now()
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    customer = db.get(models.User, row.user_id)
    if customer is None or not customer.is_active or customer.role != "customer" or customer.tenant_id is not None:
        row.revoked_at = _now()
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid customer session")

    row.revoked_at = _now()
    new_refresh = _issue_refresh_token(db, customer.id)
    db.flush()
    row.replaced_by = db.scalar(
        select(models.CustomerRefreshToken.id).where(
            models.CustomerRefreshToken.token_hash == _refresh_token_hash(new_refresh)
        )
    )
    set_customer_context(db, customer.id)
    audit.record_customer(
        db,
        customer_id=customer.id,
        action="account.session_refreshed",
        summary="Customer session refreshed",
    )
    db.commit()
    access_token = create_customer_access_token(customer.id)
    return schemas.CustomerTokenOut(
        access_token=access_token,
        expires_in=settings.customer_access_token_minutes * 60,
        refresh_token=new_refresh,
        refresh_expires_in=settings.customer_refresh_token_minutes * 60,
        is_new_account=False,
        customer=schemas.CustomerOut.model_validate(customer),
        claimed=schemas.ClaimedOut(),
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
