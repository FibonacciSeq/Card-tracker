"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.constants import STAFF_ROLES, TENANT_ACTIVE_STATUSES
from app.db import get_db, set_customer_context, set_tenant_context
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def _resolve_customer(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> models.User | None:
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        if payload.get("scope") != "customer" or payload.get("role") != "customer":
            raise ValueError("not a customer token")
        if "tenant_id" in payload:
            raise ValueError("customer token must not have a tenant")
        customer_id = uuid.UUID(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    set_customer_context(db, customer_id)
    customer = db.get(models.User, customer_id)
    if customer is None or not customer.is_active or customer.role != "customer" or customer.tenant_id is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return customer


def get_current_customer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    customer = _resolve_customer(credentials, db)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return customer


def get_optional_customer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User | None:
    """Optional customer auth for public create endpoints.

    A missing header keeps the guest flow. A malformed or expired header is an
    error rather than silently creating an unowned guest row.
    """
    return _resolve_customer(credentials, db)


def get_current_staff(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tenant_id"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    set_tenant_context(db, tenant_id)
    user = db.get(models.User, user_id)
    if user is None or not user.is_active or user.role not in STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid tenant")
    return user


def require_owner(user: models.User = Depends(get_current_staff)) -> models.User:
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return user


def get_tenant_by_slug(slug: str, db: Session) -> models.Tenant:
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug))
    if tenant is None or tenant.status not in TENANT_ACTIVE_STATUSES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    set_tenant_context(db, tenant.id)
    return tenant
