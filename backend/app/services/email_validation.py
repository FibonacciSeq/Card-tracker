"""Reject email addresses that cannot belong to a real mailbox domain.

Syntax is already enforced by Pydantic's ``EmailStr`` at the API boundary. This
module adds the checks that a plain format validator cannot do:

* the domain must publish MX records, and
* the domain must not be a known disposable/temporary provider.

The check deliberately stops at DNS. Connecting to a stranger's SMTP server
from a public API is slow, unreliable, and an SSRF risk. Mailbox ownership is
still proven by the signup/reset/email-change OTP flows. DNS failures are
logged and allowed through so a resolver outage does not block every signup.
"""

from __future__ import annotations

import functools
import logging
from typing import Final

import dns.exception
import dns.resolver
from email_validator import EmailNotValidError
from email_validator import validate_email as _validate_email

from app.config import settings
from app.security import normalize_email

logger = logging.getLogger(__name__)

# Curated list of well-known disposable/temporary mailbox providers. Matching
# is suffix-based, so their subdomains are blocked too.
DISPOSABLE_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "10minutemail.com",
        "10minutemail.net",
        "20minutemail.com",
        "33mail.com",
        "anonbox.net",
        "burnermail.io",
        "discard.email",
        "dispostable.com",
        "dropmail.me",
        "einmalmail.de",
        "emailfake.com",
        "emailnator.com",
        "emailondeck.com",
        "fakeinbox.com",
        "generator.email",
        "getairmail.com",
        "getnada.com",
        "guerrillamail.biz",
        "guerrillamail.com",
        "guerrillamail.de",
        "guerrillamail.info",
        "guerrillamail.net",
        "guerrillamail.org",
        "guerrillamailblock.com",
        "grr.la",
        "harakirimail.com",
        "inboxkitten.com",
        "jetable.org",
        "kurzepost.de",
        "luxusmail.org",
        "mail-temp.com",
        "mailcatch.com",
        "maildrop.cc",
        "mailforspam.com",
        "mailinator.com",
        "mailinator.net",
        "mailinator2.com",
        "mailnesia.com",
        "mailsac.com",
        "mailnull.com",
        "mega.zik.dj",
        "mintemail.com",
        "mohmal.com",
        "moakt.com",
        "mytemp.email",
        "no-spam.ws",
        "nomail.xl.cx",
        "sharklasers.com",
        "spam4.me",
        "spamfree24.org",
        "spamgourmet.com",
        "temp-mail.io",
        "temp-mail.org",
        "tempail.com",
        "tempemail.net",
        "tempinbox.com",
        "tempmail.com",
        "tempmail.net",
        "tempmailo.com",
        "tempomail.fr",
        "temporaryemail.net",
        "tempr.email",
        "throwawaymail.com",
        "trash-mail.at",
        "trash-mail.com",
        "trashmail.com",
        "trashmail.de",
        "trbvm.com",
        "wegwerfmail.de",
        "yopmail.com",
        "yopmail.fr",
        "yopmail.net",
    }
)

# Reserved domains used by the local demo and the automated tests. They never
# publish MX records, so skip the DNS lookup outside production. Production
# does not get this exemption.
_RESERVED_DOMAINS: Final[frozenset[str]] = frozenset({"example.com", "example.org", "example.net", "localhost"})
_RESERVED_SUFFIXES: Final[tuple[str, ...]] = (
    ".example",
    ".test",
    ".invalid",
    ".localhost",
)


class EmailValidationError(ValueError):
    """An address that is syntactically valid but not plausible as a mailbox."""


def _is_disposable(domain: str) -> bool:
    return any(domain == provider or domain.endswith(f".{provider}") for provider in DISPOSABLE_DOMAINS)


def _domain_check_exempt(domain: str) -> bool:
    if settings.environment not in ("development", "test"):
        return False
    return domain in _RESERVED_DOMAINS or domain.endswith(_RESERVED_SUFFIXES)


@functools.lru_cache(maxsize=1024)
def domain_has_mx(domain: str) -> bool | None:
    """Return whether ``domain`` publishes MX records.

    ``True`` means mail can be routed, ``False`` means the domain definitively
    cannot receive mail, and ``None`` means DNS could not answer right now.
    The small per-process cache keeps repeated signup attempts cheap; restart
    the API to clear a stale result.
    """

    resolver = dns.resolver.Resolver()
    resolver.timeout = settings.email_domain_check_timeout_seconds
    resolver.lifetime = settings.email_domain_check_timeout_seconds
    try:
        resolver.resolve(domain, "MX")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except dns.exception.DNSException:
        return None
    return True


def validate_email_address(value: str) -> str:
    """Normalize an address and verify that its domain looks deliverable."""

    try:
        parsed = _validate_email(
            value.strip(),
            check_deliverability=False,
            test_environment=settings.environment in ("development", "test"),
        )
    except EmailNotValidError as exc:
        raise EmailValidationError("Enter a valid email address.") from exc

    email = normalize_email(parsed.normalized)
    domain = email.rsplit("@", 1)[1]

    if _is_disposable(domain):
        raise EmailValidationError(
            "Disposable or temporary email addresses are not supported. Use a real email address."
        )

    if not settings.email_domain_check_enabled or _domain_check_exempt(domain):
        return email

    result = domain_has_mx(domain)
    if result is True:
        return email
    if result is False:
        raise EmailValidationError("This email domain cannot receive mail. Use a real email address.")
    logger.warning("Could not verify MX records for email domain %s", domain)
    return email
