"""Email authenticity checks shared by every email entry point."""

from __future__ import annotations

import logging
import sys

import dns.exception
import dns.resolver
import pytest
from pydantic import ValidationError

from app import schemas
from app.cli import seed_demo
from app.config import settings
from app.services import email_validation
from app.services.email_validation import (
    EmailValidationError,
    domain_has_mx,
    validate_email_address,
)


def _resolver_returns(*_args, **_kwargs):
    return object()


def _resolver_raises(error: Exception):
    def _raise(*_args, **_kwargs):
        raise error

    return _raise


def test_accepts_normalized_address_with_mx(monkeypatch):
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", _resolver_returns)

    assert validate_email_address("  Owner@Gmail.COM  ") == "owner@gmail.com"


def test_rejects_invalid_syntax():
    with pytest.raises(EmailValidationError, match="valid email"):
        validate_email_address("not-an-email")


@pytest.mark.parametrize(
    "domain",
    ["mailinator.com", "inbox.mailinator.com", "YOPMAIL.com"],
)
def test_rejects_disposable_domains(monkeypatch, domain):
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", _resolver_raises(AssertionError("DNS should not run")))

    with pytest.raises(EmailValidationError, match="Disposable"):
        validate_email_address(f"person@{domain}")


def test_reserved_domain_skips_dns_in_development(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", _resolver_raises(AssertionError("DNS should not run")))

    assert validate_email_address("Owner@Example.com") == "owner@example.com"
    assert validate_email_address("person@shop.test") == "person@shop.test"


def test_reserved_domain_is_checked_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(
        dns.resolver.Resolver,
        "resolve",
        _resolver_raises(dns.resolver.NoAnswer()),
    )

    with pytest.raises(EmailValidationError, match="cannot receive mail"):
        validate_email_address("owner@example.com")


def test_domain_check_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "email_domain_check_enabled", False)
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", _resolver_raises(AssertionError("DNS should not run")))

    assert validate_email_address("person@unverified-domain.com") == "person@unverified-domain.com"


def test_transient_dns_failure_allows_the_address(monkeypatch, caplog):
    monkeypatch.setattr(
        dns.resolver.Resolver,
        "resolve",
        _resolver_raises(dns.exception.Timeout()),
    )

    with caplog.at_level(logging.WARNING):
        assert validate_email_address("person@gmail.com") == "person@gmail.com"

    assert "Could not verify MX records" in caplog.text


def test_domain_has_mx_results(monkeypatch):
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", _resolver_returns)
    assert domain_has_mx("gmail.com") is True

    email_validation.domain_has_mx.cache_clear()
    monkeypatch.setattr(
        dns.resolver.Resolver,
        "resolve",
        _resolver_raises(dns.resolver.NXDOMAIN()),
    )
    assert domain_has_mx("missing.invalid") is False

    email_validation.domain_has_mx.cache_clear()
    monkeypatch.setattr(
        dns.resolver.Resolver,
        "resolve",
        _resolver_raises(dns.resolver.NoAnswer()),
    )
    assert domain_has_mx("empty.invalid") is False

    email_validation.domain_has_mx.cache_clear()
    monkeypatch.setattr(
        dns.resolver.Resolver,
        "resolve",
        _resolver_raises(dns.exception.DNSException()),
    )
    assert domain_has_mx("broken.invalid") is None


def test_domain_lookup_is_cached(monkeypatch):
    calls = 0

    def _count(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", _count)

    assert domain_has_mx("cached.example.org") is True
    assert domain_has_mx("cached.example.org") is True
    assert calls == 1


def test_schema_rejects_disposable_address():
    with pytest.raises(ValidationError, match="Disposable"):
        schemas.OtpRequestIn(email="person@mailinator.com")


def test_signup_request_rejects_disposable_address(client):
    response = client.post(
        "/v1/auth/signup/request",
        json={"email": "person@mailinator.com"},
    )

    assert response.status_code == 422
    assert "Disposable" in response.text


def test_seed_demo_rejects_disposable_address(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_demo", "--email", "person@mailinator.com"],
    )

    with pytest.raises(SystemExit) as exc:
        seed_demo.main()

    assert exc.value.code == 2
