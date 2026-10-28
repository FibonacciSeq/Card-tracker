"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import models  # noqa: F401  (registers models with Base)
from app.api import public, staff
from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base
from app.services.card_requests import CardRequestError
from app.services.reservations import ReservationError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Card Tracker Platform API",
    version="0.1.0",
    description="Multi-tenant API for vendor storefronts, stock, and reservations.",
    lifespan=lifespan,
)

origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(staff.router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return validation errors without echoing the submitted value.

    FastAPI's default handler includes ``input`` (and sometimes ``ctx``) for
    every error. For auth and staff-creation payloads that means a password
    can end up in the response, browser devtools, and client error logs.
    """
    errors = [
        {
            "type": error.get("type", "value_error"),
            "loc": error.get("loc", ()),
            "msg": error.get("msg", "Invalid value"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(ReservationError)
async def reservation_error_handler(_request: Request, exc: ReservationError) -> JSONResponse:
    content = {
        "type": f"https://api.cardtracker.local/problems/{exc.code}",
        "title": exc.code.replace("_", " ").title(),
        "status": exc.status_code,
        "code": exc.code,
        "detail": exc.message,
    }
    content.update(exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        media_type="application/problem+json",
    )


@app.exception_handler(CardRequestError)
async def card_request_error_handler(_request: Request, exc: CardRequestError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": f"https://api.cardtracker.local/problems/{exc.code}",
            "title": exc.code.replace("_", " ").title(),
            "status": exc.status_code,
            "code": exc.code,
            "detail": exc.message,
        },
        media_type="application/problem+json",
    )


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready"}
