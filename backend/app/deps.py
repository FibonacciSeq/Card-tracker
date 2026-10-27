"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import get_db, set_tenant_context
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


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
    if user is None or user.role not in ("owner", "staff"):
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
    if tenant is None or tenant.status not in ("active", "trialing"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    set_tenant_context(db, tenant.id)
    return tenant
