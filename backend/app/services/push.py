"""Native Android (FCM HTTP v1) and iOS (APNs HTTP/2) delivery.

The API stores native device tokens; this module owns provider authentication
and the small amount of provider-specific payload shaping. The notification
worker treats token rejection as permanent and provider/network failures as
retryable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
import jwt
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

from app.config import settings

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
APNS_JWT_TTL_SECONDS = 50 * 60


class PushError(Exception):
    """Base class for push delivery failures."""


class PushTokenInvalid(PushError):
    """The provider rejected the device token; revoke it."""


class PushTransientError(PushError):
    """A network, rate-limit, or provider failure worth retrying."""


class PushSender(Protocol):
    def send(
        self,
        *,
        token: str,
        platform: str,
        title: str,
        body: str,
        url: str | None = None,
    ) -> None: ...


class _Credentials(Protocol):
    valid: bool
    token: str | None

    def refresh(self, request: object) -> None: ...


class ConsolePushSender:
    """Development sink that never logs a token or message body."""

    def send(
        self,
        *,
        token: str,
        platform: str,
        title: str,
        body: str,
        url: str | None = None,
    ) -> None:
        logger.info("Push notification rendered for %s", platform)


class FcmSender:
    """FCM HTTP v1 sender using a service-account credential."""

    def __init__(
        self,
        *,
        project_id: str,
        credentials: _Credentials,
        client: httpx.Client | None = None,
    ) -> None:
        self.project_id = project_id
        self.credentials = credentials
        self.client = client or httpx.Client(timeout=settings.push_timeout_seconds)

    def _access_token(self) -> str:
        if not self.credentials.valid:
            try:
                self.credentials.refresh(GoogleRequest())
            except Exception as exc:
                raise PushTransientError("FCM credentials refresh failed") from exc
        token = self.credentials.token
        if not token:
            raise PushTransientError("FCM credentials did not produce an access token")
        return token

    def send(
        self,
        *,
        token: str,
        platform: str,
        title: str,
        body: str,
        url: str | None = None,
    ) -> None:
        payload = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": {"url": url or ""},
                "android": {"priority": "high"},
            }
        }
        try:
            response = self.client.post(
                f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send",
                headers={
                    "authorization": f"Bearer {self._access_token()}",
                    "content-type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise PushTransientError("FCM transport failed") from exc
        if response.status_code == 200:
            return

        data = _json(response)
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        status = str(error.get("status") or "")
        if response.status_code in (400, 404) or status in (
            "INVALID_ARGUMENT",
            "NOT_FOUND",
            "UNREGISTERED",
        ):
            raise PushTokenInvalid(f"FCM rejected the device token ({status or response.status_code})")
        raise PushTransientError(f"FCM delivery failed ({response.status_code})")


class ApnsSender:
    """APNs HTTP/2 sender using token-based ES256 authentication."""

    def __init__(
        self,
        *,
        team_id: str,
        key_id: str,
        private_key: str,
        bundle_id: str,
        use_sandbox: bool = True,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.team_id = team_id
        self.key_id = key_id
        self.private_key = private_key
        self.bundle_id = bundle_id
        self.use_sandbox = use_sandbox
        self.client = client or httpx.Client(http2=True, timeout=settings.push_timeout_seconds)
        self._now = now or (lambda: datetime.now(UTC))
        self._jwt: str | None = None
        self._jwt_iat: datetime | None = None

    def _provider_jwt(self) -> str:
        now = self._now()
        if (
            self._jwt is not None
            and self._jwt_iat is not None
            and (now - self._jwt_iat).total_seconds() < APNS_JWT_TTL_SECONDS
        ):
            return self._jwt
        self._jwt = jwt.encode(
            {"iss": self.team_id, "iat": int(now.timestamp())},
            self.private_key,
            algorithm="ES256",
            headers={"kid": self.key_id},
        )
        self._jwt_iat = now
        return self._jwt

    def send(
        self,
        *,
        token: str,
        platform: str,
        title: str,
        body: str,
        url: str | None = None,
    ) -> None:
        host = "api.sandbox.push.apple.com" if self.use_sandbox else "api.push.apple.com"
        try:
            response = self.client.post(
                f"https://{host}/3/device/{token}",
                headers={
                    "authorization": f"bearer {self._provider_jwt()}",
                    "apns-topic": self.bundle_id,
                    "apns-push-type": "alert",
                    "apns-priority": "10",
                },
                json={
                    "aps": {
                        "alert": {"title": title, "body": body},
                        "sound": "default",
                    },
                    "url": url or "",
                },
            )
        except httpx.HTTPError as exc:
            raise PushTransientError("APNs transport failed") from exc
        if response.status_code == 200:
            return

        reason = str(_json(response).get("reason") or "")
        if response.status_code == 410 or reason in (
            "BadDeviceToken",
            "Unregistered",
            "DeviceTokenNotForTopic",
        ):
            raise PushTokenInvalid(f"APNs rejected the device token ({reason or response.status_code})")
        raise PushTransientError(f"APNs delivery failed ({reason or response.status_code})")


class NativePushSender:
    """Dispatch to FCM or APNs based on the registered token platform."""

    def __init__(self, *, fcm: FcmSender | None, apns: ApnsSender | None) -> None:
        self.fcm = fcm
        self.apns = apns

    def send(
        self,
        *,
        token: str,
        platform: str,
        title: str,
        body: str,
        url: str | None = None,
    ) -> None:
        provider = self.fcm if platform == "android" else self.apns
        if provider is None:
            raise PushTransientError(f"{platform} push credentials are not configured")
        provider.send(token=token, platform=platform, title=title, body=body, url=url)


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def default_sender() -> PushSender | None:
    """Build the configured sender; ``none`` leaves the outbox untouched."""
    backend = settings.push_backend.lower().strip()
    if backend in ("console", "log"):
        return ConsolePushSender()
    if backend == "none":
        return None
    if backend != "native":
        raise RuntimeError(f"Unknown CARDTRACKER_PUSH_BACKEND: {backend!r}")

    fcm = None
    if settings.fcm_project_id and settings.fcm_credentials_file:
        credentials = service_account.Credentials.from_service_account_file(
            settings.fcm_credentials_file,
            scopes=[FCM_SCOPE],
        )
        fcm = FcmSender(project_id=settings.fcm_project_id, credentials=credentials)

    apns = None
    if settings.apns_team_id and settings.apns_key_id and settings.apns_private_key_file and settings.apns_bundle_id:
        apns = ApnsSender(
            team_id=settings.apns_team_id,
            key_id=settings.apns_key_id,
            private_key=Path(settings.apns_private_key_file).read_text(),
            bundle_id=settings.apns_bundle_id,
            use_sandbox=settings.apns_use_sandbox,
        )

    return NativePushSender(fcm=fcm, apns=apns)
