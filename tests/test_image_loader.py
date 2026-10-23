import os
import threading

import pytest
from PIL import Image

from services.image_loader import ImageLoader


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ImageLoader, "_cache_dir", str(tmp_path / "cache"))
    ImageLoader._ensure_cache_dir()
    return tmp_path / "cache"


def test_cache_path_strips_query_strings():
    path = ImageLoader._cache_path("https://cards.example/front/a/b/abc-123.jpg?1562404626")
    assert os.path.basename(path) == "abc-123.jpg"


def test_cache_path_adds_a_jpg_extension():
    assert ImageLoader._cache_path("https://cards.example/img/xyz").endswith("xyz.jpg")


def test_cache_path_cannot_escape_the_cache_directory():
    path = ImageLoader._cache_path("https://cards.example/../../etc/passwd")
    assert os.path.dirname(path) == ImageLoader._cache_dir
    assert ".." not in os.path.basename(path)


class FakeResponse:
    def __init__(self, payload, final_url="https://cards.example/card.jpg"):
        self._payload = payload
        self._final_url = final_url

    def read(self, size=-1):
        return self._payload if size < 0 else self._payload[:size]

    def geturl(self):
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_writes_the_file(cache_dir, monkeypatch):
    monkeypatch.setattr(
        "services.image_loader.urllib.request.urlopen",
        lambda *a, **k: FakeResponse(b"image-bytes"),
    )
    target = cache_dir / "card.jpg"
    ImageLoader._download("https://cards.example/card.jpg", str(target))

    assert target.read_bytes() == b"image-bytes"


def test_download_rejects_non_http_schemes(cache_dir):
    target = cache_dir / "card.jpg"

    with pytest.raises(ValueError):
        ImageLoader._download("file:///etc/passwd", str(target))

    assert not target.exists()
    assert list(cache_dir.glob("*.part")) == []


def test_download_rejects_a_redirect_to_a_local_file(cache_dir, monkeypatch):
    monkeypatch.setattr(
        "services.image_loader.urllib.request.urlopen",
        lambda *a, **k: FakeResponse(b"image-bytes", final_url="file:///etc/passwd"),
    )
    target = cache_dir / "card.jpg"

    with pytest.raises(ValueError):
        ImageLoader._download("https://cards.example/card.jpg", str(target))

    assert not target.exists()
    assert list(cache_dir.glob("*.part")) == []


def test_download_rejects_an_oversized_image(cache_dir, monkeypatch):
    monkeypatch.setattr(ImageLoader, "_max_image_bytes", 4)
    monkeypatch.setattr(
        "services.image_loader.urllib.request.urlopen",
        lambda *a, **k: FakeResponse(b"too-large"),
    )
    target = cache_dir / "card.jpg"

    with pytest.raises(ValueError, match="larger"):
        ImageLoader._download("https://cards.example/card.jpg", str(target))

    assert not target.exists()
    assert list(cache_dir.glob("*.part")) == []


def test_failed_download_leaves_no_partial_file(cache_dir, monkeypatch):
    """Regresija: prekinuto preuzimanje je ostavljalo polovicnu sliku u kesu."""

    def boom(*a, **k):
        raise OSError("connection reset")

    monkeypatch.setattr("services.image_loader.urllib.request.urlopen", boom)
    target = cache_dir / "card.jpg"

    with pytest.raises(OSError):
        ImageLoader._download("https://cards.example/card.jpg", str(target))

    assert not target.exists()
    assert list(cache_dir.glob("*.part")) == []


def test_trim_cache_evicts_the_oldest_files(cache_dir, monkeypatch):
    monkeypatch.setattr(ImageLoader, "_max_cache_files", 3)

    extensions = (".jpg", ".png", ".webp")
    for i in range(6):
        path = cache_dir / f"card{i}{extensions[i % len(extensions)]}"
        path.write_bytes(b"x")
        os.utime(path, (1_600_000_000 + i, 1_600_000_000 + i))

    ImageLoader._trim_cache()

    remaining = sorted(p.name for p in cache_dir.iterdir())
    assert remaining == ["card3.jpg", "card4.png", "card5.webp"]


def test_trim_cache_keeps_everything_under_the_limit(cache_dir, monkeypatch):
    monkeypatch.setattr(ImageLoader, "_max_cache_files", 10)
    for i in range(4):
        (cache_dir / f"card{i}.jpg").write_bytes(b"x")

    ImageLoader._trim_cache()
    assert len(list(cache_dir.glob("*.jpg"))) == 4


def test_no_url_does_nothing():
    calls = []
    ImageLoader.load_card_image("", lambda *a: calls.append(a))
    assert calls == []


def test_make_photo_image_uses_imagetk_when_available(monkeypatch):
    class FakeImageTk:
        @staticmethod
        def PhotoImage(image):
            return ("imagetk", image.size)

    monkeypatch.setattr("services.image_loader.import_module", lambda _name: FakeImageTk)
    assert ImageLoader._make_photo_image(Image.new("RGB", (3, 4))) == ("imagetk", (3, 4))


def test_make_photo_image_falls_back_to_png_data(monkeypatch):
    def no_imagetk(_name):
        raise ImportError("PIL.ImageTk is not installed")

    monkeypatch.setattr("services.image_loader.import_module", no_imagetk)
    monkeypatch.setattr("tkinter.PhotoImage", lambda data: {"data": data})

    photo = ImageLoader._make_photo_image(Image.new("RGB", (2, 2)))

    assert photo["data"]


def test_load_card_image_reports_the_loaded_photo(cache_dir, monkeypatch):
    image_path = cache_dir / "card.png"
    Image.new("RGB", (8, 8), "red").save(image_path)
    monkeypatch.setattr(ImageLoader, "_make_photo_image", staticmethod(lambda _image: "photo"))

    done = threading.Event()
    results = []

    def callback(photo, path):
        results.append((photo, path))
        done.set()

    ImageLoader.load_card_image(
        "https://cards.example/card.png",
        callback,
        size=(4, 4),
        schedule=lambda _delay, func: func(),
    )

    assert done.wait(timeout=5)
    assert results == [("photo", str(image_path))]


def test_on_error_fires_when_the_download_fails(monkeypatch):
    """Regresija: neuspeh je ostavljao pregled zaglavljen na 'Učitavam sliku...'."""

    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr("services.image_loader.urllib.request.urlopen", boom)

    done = threading.Event()
    errors = []

    def on_error(exc):
        errors.append(exc)
        done.set()

    ImageLoader.load_card_image(
        "https://cards.example/missing.jpg",
        callback=lambda *a: None,
        on_error=on_error,
    )

    assert done.wait(timeout=5), "on_error nije pozvan"
    assert isinstance(errors[0], OSError)


def test_dispatch_uses_the_scheduler_when_given():
    scheduled = []
    ImageLoader._dispatch(lambda delay, fn: scheduled.append((delay, fn)), lambda: None)
    assert scheduled and scheduled[0][0] == 0


def test_dispatch_runs_inline_without_a_scheduler():
    ran = []
    ImageLoader._dispatch(None, lambda: ran.append(True))
    assert ran == [True]
