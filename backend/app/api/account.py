"""Customer authentication and account endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import models, schemas, serializers
from app.db import get_db, set_tenant_context
from app.deps import get_current_customer
from app.services import accounts, audit, notifications
from app.services import card_requests as card_request_service
from app.services import reservations as reservation_service

router = APIRouter(prefix="/v1", tags=["customer-account"])

MAX_ACCOUNT_ROWS = 200


@router.post("/auth/otp/request", response_model=schemas.OtpRequestOut, status_code=status.HTTP_202_ACCEPTED)
def request_otp(
    payload: schemas.OtpRequestIn,
    request: Request,
    db: Session = Depends(get_db),
):
    return accounts.request_otp(db, str(payload.email), request)


@router.post("/auth/otp/verify", response_model=schemas.CustomerTokenOut)
def verify_otp(
    payload: schemas.OtpVerifyIn,
    request: Request,
    db: Session = Depends(get_db),
):
    return accounts.verify_otp(db, str(payload.email), payload.code, request)


@router.post(
    "/auth/signup/request",
    response_model=schemas.OtpRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_signup(
    payload: schemas.OtpRequestIn,
    request: Request,
    db: Session = Depends(get_db),
):
    return accounts.request_signup_otp(db, str(payload.email), request)


@router.post("/auth/signup/verify", response_model=schemas.CustomerTokenOut)
def verify_signup(
    payload: schemas.SignupVerifyIn,
    request: Request,
    db: Session = Depends(get_db),
):
    return accounts.verify_signup(
        db,
        str(payload.email),
        payload.code,
        payload.password,
        request,
    )


@router.post("/auth/login", response_model=schemas.CustomerTokenOut)
def login_with_password(
    payload: schemas.PasswordLoginIn,
    request: Request,
    db: Session = Depends(get_db),
):
    return accounts.login_with_password(
        db,
        str(payload.email),
        payload.password,
        request,
    )


@router.post(
    "/auth/password/reset/request",
    response_model=schemas.OtpRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_password_reset(
    payload: schemas.OtpRequestIn,
    request: Request,
    db: Session = Depends(get_db),
):
    return accounts.request_password_reset(db, str(payload.email), request)


@router.post("/auth/password/reset/verify", response_model=schemas.CustomerTokenOut)
def reset_password(
    payload: schemas.PasswordResetVerifyIn,
    request: Request,
    db: Session = Depends(get_db),
):
    return accounts.reset_password(
        db,
        str(payload.email),
        payload.code,
        payload.password,
        request,
    )


@router.post("/me/password", response_model=schemas.CustomerTokenOut)
def change_password(
    payload: schemas.PasswordChangeIn,
    request: Request,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return accounts.change_password(
        db,
        customer,
        payload.current_password,
        payload.new_password,
        request,
    )


@router.post("/auth/refresh", response_model=schemas.CustomerTokenOut)
def refresh_customer_token(
    payload: schemas.CustomerRefreshIn,
    db: Session = Depends(get_db),
):
    return accounts.refresh_customer_session(db, payload.refresh_token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_customer(
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
    payload: schemas.CustomerLogoutIn | None = None,
):
    accounts.revoke_customer_refresh_tokens(
        db,
        customer.id,
        payload.refresh_token if payload else None,
        action="account.logout",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/sessions/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
def revoke_all_customer_sessions(
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    accounts.revoke_customer_refresh_tokens(db, customer.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/email", response_model=schemas.OtpRequestOut, status_code=status.HTTP_202_ACCEPTED)
def request_customer_email_change(
    payload: schemas.EmailChangeRequestIn,
    request: Request,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return accounts.request_email_change(db, customer, str(payload.email), request)


@router.post("/me/email/verify", response_model=schemas.CustomerTokenOut)
def verify_customer_email_change(
    payload: schemas.EmailChangeVerifyIn,
    request: Request,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return accounts.verify_email_change(db, customer, str(payload.email), payload.code, request)


@router.get("/me", response_model=schemas.CustomerOut)
def get_me(customer: models.User = Depends(get_current_customer)):
    return schemas.CustomerOut.model_validate(customer)


@router.patch("/me", response_model=schemas.CustomerOut)
def update_me(
    payload: schemas.CustomerProfileUpdateIn,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    changed: list[str] = []
    if payload.display_name is not None:
        customer.display_name = payload.display_name.strip() or None
        changed.append("display_name")
    if payload.phone is not None:
        customer.phone = payload.phone.strip() or None
        changed.append("phone")
    if payload.push_notifications_enabled is not None:
        customer.push_notifications_enabled = payload.push_notifications_enabled
        changed.append("push_notifications_enabled")
    if payload.email_notifications_enabled is not None:
        customer.email_notifications_enabled = payload.email_notifications_enabled
        changed.append("email_notifications_enabled")
    if payload.quiet_hours_enabled is not None:
        customer.quiet_hours_enabled = payload.quiet_hours_enabled
        changed.append("quiet_hours_enabled")
    if payload.notifications_opt_out is not None:
        customer.notifications_opt_out = payload.notifications_opt_out
        changed.append("notifications_opt_out")
    if changed:
        audit.record_customer(
            db,
            customer_id=customer.id,
            action="account.profile_updated",
            summary="Customer profile updated",
            data={"fields": changed},
        )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return schemas.CustomerOut.model_validate(customer)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    customer.is_active = False
    accounts.revoke_customer_refresh_tokens(
        db,
        customer.id,
        commit=False,
        action="account.sessions_revoked",
    )
    audit.record_customer(
        db,
        customer_id=customer.id,
        action="account.deleted",
        summary="Customer deleted account",
    )
    db.add(customer)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/push-tokens", response_model=schemas.PushTokenOut, status_code=status.HTTP_201_CREATED)
def register_push_token(
    payload: schemas.PushTokenIn,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return accounts.register_push_token(db, customer, payload)


@router.delete("/me/push-tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
def unregister_push_token(
    token: str,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    accounts.unregister_push_token(db, customer, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/push-tokens", response_model=schemas.PushTokenListOut)
def list_my_push_tokens(
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(models.PushToken)
        .where(models.PushToken.user_id == customer.id)
        .order_by(models.PushToken.created_at.desc())
        .limit(MAX_ACCOUNT_ROWS)
    ).all()
    return schemas.PushTokenListOut(items=[schemas.PushTokenOut.model_validate(row) for row in rows])


@router.get("/me/notifications", response_model=schemas.MeNotificationListOut)
def list_my_notifications(
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    stmt = (
        select(models.Notification, models.Tenant)
        .join(models.Tenant, models.Tenant.id == models.Notification.tenant_id)
        .where(models.Notification.user_id == customer.id)
    )
    if cursor is not None:
        stmt = stmt.where(models.Notification.id < cursor)
    rows = list(db.execute(stmt.order_by(models.Notification.id.desc()).limit(limit + 1)).all())

    next_cursor = None
    if len(rows) > limit:
        next_cursor = str(rows[limit - 1][0].id)
        rows = rows[:limit]

    items = []
    for row, tenant in rows:
        title, _body = notifications.render(row, tenant)
        items.append(
            schemas.MeNotificationOut(
                id=row.id,
                kind=row.kind,
                channel=row.channel,
                status=notifications.delivery_status(row),
                title=title,
                shop={"slug": tenant.slug, "name": tenant.name},
                attempts=row.attempts,
                created_at=row.created_at,
                sent_at=row.sent_at,
                next_attempt_at=row.next_attempt_at,
                error=row.error,
            )
        )
    return schemas.MeNotificationListOut(items=items, next_cursor=next_cursor)


@router.get("/me/reservations", response_model=schemas.MeReservationListOut)
def list_my_reservations(
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(models.Reservation, models.Tenant)
        .join(models.Tenant, models.Tenant.id == models.Reservation.tenant_id)
        .where(models.Reservation.customer_id == customer.id)
        .order_by(models.Reservation.created_at.desc())
        .limit(MAX_ACCOUNT_ROWS)
    ).all()
    counts = _line_counts(db, {reservation.tenant_id for reservation, _tenant in rows})
    items = []
    for reservation, tenant in rows:
        summary = serializers.reservation_summary_out(
            reservation,
            line_count=counts.get(reservation.id, 0),
        )
        items.append(
            schemas.MeReservationSummaryOut(
                **summary.model_dump(),
                shop={"slug": tenant.slug, "name": tenant.name},
            )
        )
    return schemas.MeReservationListOut(items=items)


def _line_counts(db: Session, tenant_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
    counts: dict[uuid.UUID, int] = {}
    for tenant_id in tenant_ids:
        set_tenant_context(db, tenant_id)
        rows = db.execute(
            select(models.ReservationLine.reservation_id, func.count())
            .where(models.ReservationLine.tenant_id == tenant_id)
            .group_by(models.ReservationLine.reservation_id)
        ).all()
        counts.update({reservation_id: int(count) for reservation_id, count in rows})
    return counts


def _owned_reservation(
    db: Session,
    customer: models.User,
    reservation_id: uuid.UUID,
    *,
    with_lines: bool = False,
) -> tuple[models.Reservation, models.Tenant]:
    stmt = select(models.Reservation).where(
        models.Reservation.id == reservation_id,
        models.Reservation.customer_id == customer.id,
    )
    reservation = db.scalar(stmt)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    # Resolve ownership first; only then enter the tenant context needed for
    # reservation_lines, which stays tenant-only under RLS.
    set_tenant_context(db, reservation.tenant_id)
    detail_stmt = (
        select(models.Reservation)
        .where(
            models.Reservation.id == reservation_id,
            models.Reservation.customer_id == customer.id,
            models.Reservation.tenant_id == reservation.tenant_id,
        )
        .execution_options(populate_existing=True)
    )
    if with_lines:
        detail_stmt = detail_stmt.options(joinedload(models.Reservation.lines))
    reservation = db.scalar(detail_stmt)
    tenant = db.get(models.Tenant, reservation.tenant_id) if reservation is not None else None
    if reservation is None or tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    return reservation, tenant


@router.get("/me/reservations/{reservation_id}", response_model=schemas.ReservationOut)
def get_my_reservation(
    reservation_id: uuid.UUID,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    reservation, tenant = _owned_reservation(db, customer, reservation_id, with_lines=True)
    return serializers.reservation_out(reservation, tenant)


@router.post("/me/reservations/{reservation_id}/cancel", response_model=schemas.ReservationOut)
def cancel_my_reservation(
    reservation_id: uuid.UUID,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    reservation, tenant = _owned_reservation(db, customer, reservation_id, with_lines=True)
    reservation = reservation_service.cancel_reservation(
        db,
        reservation,
        reason="cancelled by customer",
        actor_id=None,
    )
    return serializers.reservation_out(reservation, tenant)


@router.get("/me/card-requests", response_model=schemas.MeCardRequestListOut)
def list_my_card_requests(
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(models.CardRequest, models.Tenant)
        .join(models.Tenant, models.Tenant.id == models.CardRequest.tenant_id)
        .where(models.CardRequest.customer_id == customer.id)
        .options(joinedload(models.CardRequest.reservation))
        .order_by(models.CardRequest.created_at.desc())
        .limit(MAX_ACCOUNT_ROWS)
    ).all()
    items = []
    for row, tenant in rows:
        base = serializers.card_request_out(row, tenant)
        items.append(
            schemas.MeCardRequestOut(
                **base.model_dump(),
                shop={"slug": tenant.slug, "name": tenant.name},
            )
        )
    return schemas.MeCardRequestListOut(items=items)


def _owned_card_request(
    db: Session,
    customer: models.User,
    request_id: uuid.UUID,
) -> tuple[models.CardRequest, models.Tenant]:
    row = db.scalar(
        select(models.CardRequest)
        .where(
            models.CardRequest.id == request_id,
            models.CardRequest.customer_id == customer.id,
        )
        .options(joinedload(models.CardRequest.reservation))
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    tenant = db.get(models.Tenant, row.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return row, tenant


@router.get("/me/card-requests/{request_id}", response_model=schemas.MeCardRequestOut)
def get_my_card_request(
    request_id: uuid.UUID,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    row, tenant = _owned_card_request(db, customer, request_id)
    base = serializers.card_request_out(row, tenant)
    return schemas.MeCardRequestOut(
        **base.model_dump(),
        shop={"slug": tenant.slug, "name": tenant.name},
    )


@router.post("/me/card-requests/{request_id}/accept", response_model=schemas.MeCardRequestOut)
def accept_my_card_request(
    request_id: uuid.UUID,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    row, tenant = _owned_card_request(db, customer, request_id)
    set_tenant_context(db, tenant.id)
    row = card_request_service.accept(db, tenant, row)
    base = serializers.card_request_out(row, tenant)
    return schemas.MeCardRequestOut(
        **base.model_dump(),
        shop={"slug": tenant.slug, "name": tenant.name},
    )


@router.post("/me/card-requests/{request_id}/cancel", response_model=schemas.MeCardRequestOut)
def cancel_my_card_request(
    request_id: uuid.UUID,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    row, tenant = _owned_card_request(db, customer, request_id)
    set_tenant_context(db, tenant.id)
    row = card_request_service.cancel(db, tenant, row)
    base = serializers.card_request_out(row, tenant)
    return schemas.MeCardRequestOut(
        **base.model_dump(),
        shop={"slug": tenant.slug, "name": tenant.name},
    )


@router.get("/me/restock-alerts", response_model=schemas.MeRestockAlertListOut)
def list_my_restock_alerts(
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(models.RestockAlert, models.Card, models.Tenant)
        .join(models.Card, models.Card.id == models.RestockAlert.card_id)
        .join(models.Tenant, models.Tenant.id == models.RestockAlert.tenant_id)
        .where(models.RestockAlert.customer_id == customer.id)
        .order_by(models.RestockAlert.created_at.desc())
        .limit(MAX_ACCOUNT_ROWS)
    ).all()
    return schemas.MeRestockAlertListOut(
        items=[
            schemas.MeRestockAlertOut(
                id=alert.id,
                card_id=alert.card_id,
                stock_id=alert.stock_id,
                card_name=card.name,
                set_code=card.set_code,
                collector_number=card.collector_number,
                finish=alert.finish,
                condition=alert.condition,
                language=alert.language,
                email=alert.email,
                shop={"slug": tenant.slug, "name": tenant.name},
                created_at=alert.created_at,
                notified_at=alert.notified_at,
            )
            for alert, card, tenant in rows
        ]
    )


@router.delete("/me/restock-alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_restock_alert(
    alert_id: uuid.UUID,
    customer: models.User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    alert = db.scalar(
        select(models.RestockAlert).where(
            models.RestockAlert.id == alert_id,
            models.RestockAlert.customer_id == customer.id,
        )
    )
    if alert is not None:
        db.delete(alert)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
