import gzip
import json

import pytest

from downloader import ScryfallDownloader


class FakeResponse:
    def __init__(self, payload=None, status_code=200, content=b""):
        self._payload = payload or {}
        self.status_code = status_code
        self._content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def downloader(tmp_path):
    return ScryfallDownloader(temp_file=str(tmp_path / "temp.jsonl.gz"))


def test_target_url_includes_the_data_type():
    assert ScryfallDownloader(data_type="oracle_cards").target_url.endswith("/oracle_cards")


def test_sends_a_user_agent():
    """Scryfall odbija zahteve bez User-Agent zaglavlja."""
    headers = ScryfallDownloader().headers
    assert headers["User-Agent"]
    assert headers["Accept"] == "application/json"


def test_get_download_link_reads_the_uri(downloader, monkeypatch):
    monkeypatch.setattr(
        "downloader.requests.get",
        lambda *a, **k: FakeResponse({"download_uri": "https://data.example/cards.gz"}),
    )
    assert downloader._get_download_link() == "https://data.example/cards.gz"


def test_get_download_link_accepts_the_jsonl_field(downloader, monkeypatch):
    monkeypatch.setattr(
        "downloader.requests.get",
        lambda *a, **k: FakeResponse({"jsonl_download_uri": "https://data.example/cards.jsonl.gz"}),
    )
    assert downloader._get_download_link() == "https://data.example/cards.jsonl.gz"


def test_get_download_link_returns_none_when_absent(downloader, monkeypatch):
    monkeypatch.setattr("downloader.requests.get", lambda *a, **k: FakeResponse({}))
    assert downloader._get_download_link() is None


def test_download_and_extract_writes_decompressed_jsonl(downloader, tmp_path, monkeypatch):
    rows = [{"name": "Forest"}, {"name": "Island"}]
    payload = gzip.compress("\n".join(json.dumps(r) for r in rows).encode("utf-8"))

    def fake_get(url, **kwargs):
        if url.endswith("/default_cards"):
            return FakeResponse({"download_uri": "https://data.example/cards.gz"})
        return FakeResponse(content=payload)

    monkeypatch.setattr("downloader.requests.get", fake_get)

    out = tmp_path / "cards.jsonl"
    assert downloader.download_and_extract(str(out)) is True

    names = [json.loads(line)["name"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert names == ["Forest", "Island"]


def test_temp_archive_is_cleaned_up(downloader, tmp_path, monkeypatch):
    payload = gzip.compress(b'{"name": "Forest"}')

    def fake_get(url, **kwargs):
        if url.endswith("/default_cards"):
            return FakeResponse({"download_uri": "https://data.example/cards.gz"})
        return FakeResponse(content=payload)

    monkeypatch.setattr("downloader.requests.get", fake_get)
    downloader.download_and_extract(str(tmp_path / "cards.jsonl"))

    assert not (tmp_path / "temp.jsonl.gz").exists()


def test_network_failure_is_reported_not_raised(downloader, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr("downloader.requests.get", boom)
    assert downloader.download_and_extract(str(tmp_path / "cards.jsonl")) is False


def test_missing_link_aborts_cleanly(downloader, tmp_path, monkeypatch):
    monkeypatch.setattr("downloader.requests.get", lambda *a, **k: FakeResponse({}))
    out = tmp_path / "cards.jsonl"

    assert downloader.download_and_extract(str(out)) is False
    assert not out.exists()
