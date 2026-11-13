"""Customer OTP authentication and guest-row claiming."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta

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
    hash_password,
    normalize_email,
    verify_password,
)
from app.services import audit, ratelimit
from app.timeutils import as_utc

# Kept as a private alias for callers and tests that already use this name.
_as_utc = as_utc


def _email_rate_key(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]


def _latest_challenge(
    db: Session,
    email: str,
) -> models.CustomerOtpChallenge | None:
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


def _request_challenge(
    db: Session,
    email: str,
    request: Request,
    *,
    purpose: str,
    user_id: uuid.UUID | None = None,
) -> schemas.OtpRequestOut:
    """Queue one OTP challenge for a single purpose.

    The cooldown is shared by every purpose so one address cannot be used to
    spray several emails at once. Replacing pending challenges is scoped:
    account flows keep one live code per purpose, while an email change
    invalidates any pending change for the account.
    """
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

    now = models.utcnow()
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

    # Only the newest challenge for a flow can be used. Consuming unsent rows
    # also stops the worker from delivering a code the customer can no longer
    # redeem.
    if user_id is None:
        consume = update(models.CustomerOtpChallenge).where(
            models.CustomerOtpChallenge.email == email,
            models.CustomerOtpChallenge.purpose == purpose,
            models.CustomerOtpChallenge.user_id.is_(None),
            models.CustomerOtpChallenge.consumed_at.is_(None),
        )
    else:
        # One pending email change per account; an older target address must
        # not remain redeemable after the customer asks for a different one.
        consume = update(models.CustomerOtpChallenge).where(
            models.CustomerOtpChallenge.user_id == user_id,
            models.CustomerOtpChallenge.consumed_at.is_(None),
        )
    db.execute(consume.values(consumed_at=now))
    challenge = models.CustomerOtpChallenge(
        email=email,
        purpose=purpose,
        user_id=user_id,
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


def request_otp(db: Session, email: str, request: Request) -> schemas.OtpRequestOut:
    return _request_challenge(db, email, request, purpose="login")


def request_signup_otp(db: Session, email: str, request: Request) -> schemas.OtpRequestOut:
    return _request_challenge(db, email, request, purpose="signup")


def request_password_reset(db: Session, email: str, request: Request) -> schemas.OtpRequestOut:
    return _request_challenge(db, email, request, purpose="password_reset")


def _validate_password(password: str) -> None:
    if not password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password cannot be blank.",
        )


def _verified_challenge(
    db: Session,
    email: str,
    code: str,
    request: Request,
    *,
    purpose: str,
    user_id: uuid.UUID | None = None,
) -> tuple[models.CustomerOtpChallenge, datetime]:
    """Rate-limit and validate one challenge without consuming it yet."""
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

    now = models.utcnow()
    stmt = select(models.CustomerOtpChallenge).where(
        models.CustomerOtpChallenge.email == email,
        models.CustomerOtpChallenge.purpose == purpose,
        models.CustomerOtpChallenge.consumed_at.is_(None),
    )
    if user_id is None:
        stmt = stmt.where(models.CustomerOtpChallenge.user_id.is_(None))
    else:
        stmt = stmt.where(models.CustomerOtpChallenge.user_id == user_id)
    challenge = db.scalar(stmt.order_by(models.CustomerOtpChallenge.created_at.desc()).limit(1).with_for_update())

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
    return challenge, now


def _create_customer_if_missing(
    db: Session,
    email: str,
    now: datetime,
    *,
    password_hash: str | None = None,
) -> tuple[models.User, bool]:
    customer = _find_customer(db, email)
    created = customer is None
    if customer is None:
        candidate = models.User(
            tenant_id=None,
            email=email,
            role="customer",
            is_active=True,
            email_verified_at=now,
            password_hash=password_hash,
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
    return customer, created


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


def _finish_session(
    db: Session,
    customer: models.User,
    *,
    is_new_account: bool,
    claimed: schemas.ClaimedOut,
) -> schemas.CustomerTokenOut:
    """Issue a fresh access/refresh pair and build the shared token response."""
    # Keep the response independent of any tenant context left by claiming.
    set_customer_context(db, customer.id)
    refresh_token = _issue_refresh_token(db, customer.id)
    db.commit()
    return schemas.CustomerTokenOut(
        access_token=create_customer_access_token(customer.id),
        expires_in=settings.customer_access_token_minutes * 60,
        refresh_token=refresh_token,
        refresh_expires_in=settings.customer_refresh_token_minutes * 60,
        is_new_account=is_new_account,
        customer=schemas.CustomerOut.model_validate(customer),
        claimed=claimed,
    )


def verify_otp(
    db: Session,
    email: str,
    code: str,
    request: Request,
) -> schemas.CustomerTokenOut:
    email = normalize_email(email)
    challenge, now = _verified_challenge(db, email, code, request, purpose="login")
    challenge.consumed_at = now

    customer, created = _create_customer_if_missing(db, email, now)
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
    return _finish_session(db, customer, is_new_account=created, claimed=claimed)


def verify_signup(
    db: Session,
    email: str,
    code: str,
    password: str,
    request: Request,
) -> schemas.CustomerTokenOut:
    """Create an account (or set the first password on a legacy one)."""
    email = normalize_email(email)
    _validate_password(password)
    challenge, now = _verified_challenge(db, email, code, request, purpose="signup")
    challenge.consumed_at = now

    password_hash = hash_password(password)
    customer, created = _create_customer_if_missing(db, email, now, password_hash=password_hash)
    if not customer.is_active:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is unavailable.",
        )
    if not created and customer.password_hash is not None:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Sign in instead.",
        )

    if customer.password_hash is None:
        customer.password_hash = password_hash
    if customer.email_verified_at is None:
        customer.email_verified_at = now
    customer.email = email
    db.flush()

    set_customer_context(db, customer.id)
    audit.record_customer(
        db,
        customer_id=customer.id,
        action="account.signup",
        summary="Customer created a password account",
        data={"is_new_account": created},
    )
    claimed = _claim_guest_rows(db, customer)
    db.commit()
    return _finish_session(db, customer, is_new_account=created, claimed=claimed)


def login_with_password(
    db: Session,
    email: str,
    password: str,
    request: Request,
) -> schemas.CustomerTokenOut:
    """Sign in an existing password account, without leaking which part failed."""
    email = normalize_email(email)
    ratelimit.enforce(
        request,
        scope="password-login-ip",
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
    )
    ratelimit.enforce(
        request,
        scope="password-login-email",
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
        extra=_email_rate_key(email),
    )

    customer = _find_customer(db, email)
    if (
        customer is None
        or not customer.is_active
        or customer.password_hash is None
        or not verify_password(customer.password_hash, password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    now = models.utcnow()
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
        data={"method": "password"},
    )
    claimed = _claim_guest_rows(db, customer)
    db.commit()
    return _finish_session(db, customer, is_new_account=False, claimed=claimed)


def reset_password(
    db: Session,
    email: str,
    code: str,
    password: str,
    request: Request,
) -> schemas.CustomerTokenOut:
    """Set a new password after proving control of the email address."""
    email = normalize_email(email)
    _validate_password(password)
    challenge, now = _verified_challenge(db, email, code, request, purpose="password_reset")
    challenge.consumed_at = now

    customer = _find_customer(db, email)
    if customer is None:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired code",
        )
    if not customer.is_active:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is unavailable.",
        )

    customer.password_hash = hash_password(password)
    if customer.email_verified_at is None:
        customer.email_verified_at = now
    customer.email = email
    db.flush()

    set_customer_context(db, customer.id)
    # A reset is a recovery event: end every other session first.
    revoke_customer_refresh_tokens(db, customer.id, commit=False)
    claimed = _claim_guest_rows(db, customer)
    audit.record_customer(
        db,
        customer_id=customer.id,
        action="account.password_reset",
        summary="Customer reset their password",
    )
    db.commit()
    return _finish_session(db, customer, is_new_account=False, claimed=claimed)


def change_password(
    db: Session,
    customer: models.User,
    current_password: str | None,
    new_password: str,
    request: Request,
) -> schemas.CustomerTokenOut:
    """Change a signed-in customer's password and rotate their session."""
    _validate_password(new_password)
    ratelimit.enforce(
        request,
        scope="password-change-ip",
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
    )

    if customer.password_hash is not None and (
        current_password is None or not verify_password(customer.password_hash, current_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect",
        )

    now = models.utcnow()
    customer.password_hash = hash_password(new_password)
    if customer.email_verified_at is None:
        customer.email_verified_at = now
    db.flush()

    set_customer_context(db, customer.id)
    revoke_customer_refresh_tokens(db, customer.id, commit=False)
    audit.record_customer(
        db,
        customer_id=customer.id,
        action="account.password_changed",
        summary="Customer changed their password",
    )
    db.commit()
    return _finish_session(
        db,
        customer,
        is_new_account=False,
        claimed=schemas.ClaimedOut(),
    )


def request_email_change(
    db: Session,
    customer: models.User,
    email: str,
    request: Request,
) -> schemas.OtpRequestOut:
    """Send a confirmation code to the new address before changing it."""
    new_email = normalize_email(email)

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

    return _request_challenge(
        db,
        new_email,
        request,
        purpose="email_change",
        user_id=customer.id,
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
    challenge, now = _verified_challenge(
        db,
        new_email,
        code,
        request,
        purpose="email_change",
        user_id=customer.id,
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
    return _finish_session(db, customer, is_new_account=False, claimed=claimed)


def _refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_refresh_token(db: Session, customer_id: uuid.UUID) -> str:
    token = create_customer_refresh_token()
    row = models.CustomerRefreshToken(
        user_id=customer_id,
        token_hash=_refresh_token_hash(token),
        issued_at=models.utcnow(),
        expires_at=models.utcnow() + timedelta(minutes=settings.customer_refresh_token_minutes),
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
        row.revoked_at = models.utcnow()
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
    if row.revoked_at is not None or expires_at is None or expires_at <= models.utcnow():
        row.revoked_at = models.utcnow()
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    customer = db.get(models.User, row.user_id)
    if customer is None or not customer.is_active or customer.role != "customer" or customer.tenant_id is not None:
        row.revoked_at = models.utcnow()
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid customer session")

    row.revoked_at = models.utcnow()
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
    now = models.utcnow()
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
    row.revoked_at = models.utcnow()
    db.commit()
