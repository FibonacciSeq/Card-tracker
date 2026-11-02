from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import settings
from app.services import push


class FakeCredentials:
    def __init__(self, *, valid: bool = False, token: str | None = "access-token") -> None:
        self.valid = valid
        self.token = token
        self.refreshes = 0

    def refresh(self, request: object) -> None:
        self.refreshes += 1
        self.valid = True


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _apns_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def test_fcm_sends_notification_and_refreshes_credentials():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"name": "projects/demo/messages/1"})

    credentials = FakeCredentials()
    sender = push.FcmSender(project_id="demo", credentials=credentials, client=_client(handler))
    sender.send(
        token="fcm-token",
        platform="android",
        title="Back in stock",
        body="Lightning Bolt is available.",
        url="cardtracker://shop/bolt-shop/card/1",
    )

    assert credentials.refreshes == 1
    assert requests[0].url == "https://fcm.googleapis.com/v1/projects/demo/messages:send"
    assert requests[0].headers["authorization"] == "Bearer access-token"
    assert requests[0].content == (
        b'{"message":{"token":"fcm-token","notification":{"title":"Back in stock",'
        b'"body":"Lightning Bolt is available."},"data":{"url":'
        b'"cardtracker://shop/bolt-shop/card/1"},"android":{"priority":"high"}}}'
    )


def test_fcm_reuses_a_valid_access_token():
    credentials = FakeCredentials(valid=True, token="cached-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer cached-token"
        return httpx.Response(200)

    sender = push.FcmSender(project_id="demo", credentials=credentials, client=_client(handler))
    sender.send(token="fcm-token", platform="android", title="Title", body="Body")
    assert credentials.refreshes == 0


def test_fcm_requires_an_access_token():
    sender = push.FcmSender(
        project_id="demo",
        credentials=FakeCredentials(valid=True, token=None),
        client=_client(lambda request: httpx.Response(200)),
    )
    with pytest.raises(push.PushTransientError, match="did not produce"):
        sender.send(token="fcm-token", platform="android", title="Title", body="Body")


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (404, {"error": {"status": "UNREGISTERED"}}, push.PushTokenInvalid),
        (400, {"error": {"status": "INVALID_ARGUMENT"}}, push.PushTokenInvalid),
        (400, {"unexpected": "shape"}, push.PushTokenInvalid),
        (401, {}, push.PushTransientError),
        (500, [], push.PushTransientError),
        (503, "not-json", push.PushTransientError),
    ],
)
def test_fcm_maps_provider_failures(status, body, expected):
    sender = push.FcmSender(
        project_id="demo",
        credentials=FakeCredentials(valid=True),
        client=_client(lambda request: httpx.Response(status, json=body)),
    )
    with pytest.raises(expected):
        sender.send(token="fcm-token", platform="android", title="Title", body="Body")


def test_provider_error_without_a_json_body_is_a_transient_failure():
    sender = push.FcmSender(
        project_id="demo",
        credentials=FakeCredentials(valid=True),
        client=_client(lambda request: httpx.Response(500, content=b"not-json")),
    )
    with pytest.raises(push.PushTransientError):
        sender.send(token="fcm-token", platform="android", title="Title", body="Body")


def test_provider_transport_failures_are_transient():
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    fcm = push.FcmSender(
        project_id="demo",
        credentials=FakeCredentials(valid=True),
        client=_client(fail),
    )
    with pytest.raises(push.PushTransientError, match="FCM transport"):
        fcm.send(token="fcm-token", platform="android", title="Title", body="Body")

    apns = push.ApnsSender(
        team_id="TEAM123",
        key_id="KEY123",
        private_key=_apns_key(),
        bundle_id="com.example.cardtracker",
        client=_client(fail),
    )
    with pytest.raises(push.PushTransientError, match="APNs transport"):
        apns.send(token="apns-token", platform="ios", title="Title", body="Body")


def test_fcm_credential_refresh_failure_is_transient():
    class BrokenCredentials(FakeCredentials):
        def refresh(self, request: object) -> None:
            raise RuntimeError("metadata service unavailable")

    sender = push.FcmSender(
        project_id="demo",
        credentials=BrokenCredentials(),
        client=_client(lambda request: httpx.Response(200)),
    )
    with pytest.raises(push.PushTransientError, match="credentials refresh"):
        sender.send(token="fcm-token", platform="android", title="Title", body="Body")


def test_apns_sends_alert_and_caches_the_provider_jwt():
    requests: list[httpx.Request] = []
    now = [datetime(2026, 10, 30, 12, 0, tzinfo=UTC)]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    sender = push.ApnsSender(
        team_id="TEAM123",
        key_id="KEY123",
        private_key=_apns_key(),
        bundle_id="com.example.cardtracker",
        client=_client(handler),
        now=lambda: now[0],
    )
    sender.send(token="apns-token", platform="ios", title="Ready", body="Your cards are ready.", url="app://x")
    first_auth = requests[0].headers["authorization"]
    assert requests[0].url == "https://api.sandbox.push.apple.com/3/device/apns-token"
    assert requests[0].headers["apns-topic"] == "com.example.cardtracker"
    assert requests[0].headers["apns-push-type"] == "alert"

    sender.send(token="apns-token", platform="ios", title="Ready", body="Again")
    assert requests[1].headers["authorization"] == first_auth

    now[0] += timedelta(seconds=push.APNS_JWT_TTL_SECONDS + 1)
    sender.send(token="apns-token", platform="ios", title="Ready", body="Refresh")
    assert requests[2].headers["authorization"] != first_auth


def test_apns_uses_the_production_host_when_sandbox_is_disabled():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    sender = push.ApnsSender(
        team_id="TEAM123",
        key_id="KEY123",
        private_key=_apns_key(),
        bundle_id="com.example.cardtracker",
        use_sandbox=False,
        client=_client(handler),
    )
    sender.send(token="apns-token", platform="ios", title="Title", body="Body")
    assert seen == ["https://api.push.apple.com/3/device/apns-token"]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (410, {"reason": "Unregistered"}, push.PushTokenInvalid),
        (400, {"reason": "BadDeviceToken"}, push.PushTokenInvalid),
        (400, {"reason": "DeviceTokenNotForTopic"}, push.PushTokenInvalid),
        (400, {"reason": "BadTopic"}, push.PushTransientError),
        (403, {}, push.PushTransientError),
        (429, {}, push.PushTransientError),
        (503, "not-json", push.PushTransientError),
    ],
)
def test_apns_maps_provider_failures(status, body, expected):
    sender = push.ApnsSender(
        team_id="TEAM123",
        key_id="KEY123",
        private_key=_apns_key(),
        bundle_id="com.example.cardtracker",
        client=_client(lambda request: httpx.Response(status, json=body)),
    )
    with pytest.raises(expected):
        sender.send(token="apns-token", platform="ios", title="Title", body="Body")


def test_console_and_native_senders():
    push.ConsolePushSender().send(token="token", platform="android", title="Title", body="Body")

    class Provider:
        def __init__(self) -> None:
            self.platforms: list[str] = []

        def send(self, *, token, platform, title, body, url=None) -> None:
            self.platforms.append(platform)

    fcm = Provider()
    apns = Provider()
    native = push.NativePushSender(fcm=fcm, apns=apns)  # type: ignore[arg-type]
    native.send(token="a", platform="android", title="T", body="B")
    native.send(token="i", platform="ios", title="T", body="B")
    assert fcm.platforms == ["android"]
    assert apns.platforms == ["ios"]

    with pytest.raises(push.PushTransientError, match="credentials"):
        push.NativePushSender(fcm=None, apns=None).send(token="i", platform="ios", title="T", body="B")


def test_default_sender_honors_console_none_and_invalid_backends(monkeypatch):
    monkeypatch.setattr(settings, "push_backend", "console")
    assert isinstance(push.default_sender(), push.ConsolePushSender)

    monkeypatch.setattr(settings, "push_backend", "none")
    assert push.default_sender() is None

    monkeypatch.setattr(settings, "push_backend", "bogus")
    with pytest.raises(RuntimeError, match="Unknown"):
        push.default_sender()


def test_default_sender_builds_native_providers(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "push_backend", "native")
    monkeypatch.setattr(settings, "fcm_project_id", "")
    monkeypatch.setattr(settings, "fcm_credentials_file", "")
    monkeypatch.setattr(settings, "apns_team_id", "")
    monkeypatch.setattr(settings, "apns_key_id", "")
    monkeypatch.setattr(settings, "apns_private_key_file", "")
    monkeypatch.setattr(settings, "apns_bundle_id", "")

    empty = push.default_sender()
    assert isinstance(empty, push.NativePushSender)
    assert empty.fcm is None and empty.apns is None

    credentials = FakeCredentials(valid=True)
    monkeypatch.setattr(
        push.service_account.Credentials,
        "from_service_account_file",
        lambda *args, **kwargs: credentials,
    )
    monkeypatch.setattr(settings, "fcm_project_id", "demo")
    monkeypatch.setattr(settings, "fcm_credentials_file", "service-account.json")

    assert isinstance(push.default_sender().fcm, push.FcmSender)  # type: ignore[union-attr]

    key_file = tmp_path / "AuthKey.p8"
    key_file.write_text(_apns_key())
    monkeypatch.setattr(settings, "apns_team_id", "TEAM123")
    monkeypatch.setattr(settings, "apns_key_id", "KEY123")
    monkeypatch.setattr(settings, "apns_private_key_file", str(key_file))
    monkeypatch.setattr(settings, "apns_bundle_id", "com.example.cardtracker")
    monkeypatch.setattr(settings, "apns_use_sandbox", False)

    sender = push.default_sender()
    assert isinstance(sender, push.NativePushSender)
    assert isinstance(sender.fcm, push.FcmSender)
    assert isinstance(sender.apns, push.ApnsSender)
    assert sender.apns.use_sandbox is False
