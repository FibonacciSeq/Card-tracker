import logging
import os
import threading
import urllib.request
from contextlib import suppress
from importlib import import_module
from typing import Any, cast
from urllib.parse import urlparse

from PIL import Image

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_SCHEMES = {"http", "https"}
# urllib only follows these schemes; anything else could read local files.
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class ImageLoader:
    """Preuzima slike kartica u pozadini, uz kes na disku.

    Tk nije thread-safe: PhotoImage se pravi tek na glavnoj niti, preko
    `schedule` (obicno `widget.after`). Preuzimanje i dekodiranje PIL-om
    ostaju u pozadinskoj niti.
    """

    _cache_dir = "image_cache"
    _max_cache_files = 2000
    _max_image_bytes = 8 * 1024 * 1024
    _lock = threading.Lock()

    @classmethod
    def _ensure_cache_dir(cls):
        os.makedirs(cls._cache_dir, exist_ok=True)

    @classmethod
    def _cache_path(cls, image_url: str) -> str:
        filename = os.path.basename(urlparse(image_url).path)
        filename = "".join(ch for ch in filename if ch.isalnum() or ch in "._-")[:120]
        if not filename:
            filename = "image"
        if not filename.lower().endswith(tuple(ALLOWED_IMAGE_EXTENSIONS)):
            filename += ".jpg"
        return os.path.join(cls._cache_dir, filename)

    @classmethod
    def _download(cls, image_url: str, local_path: str) -> None:
        """Skida u .part pa preimenuje, da prekid ne ostavi polovicnu sliku."""
        parsed = urlparse(image_url)
        if parsed.scheme not in ALLOWED_IMAGE_SCHEMES or not parsed.netloc:
            raise ValueError("Image URL must use HTTP or HTTPS.")

        partial = local_path + ".part"
        request = urllib.request.Request(image_url, headers={"User-Agent": "MyMTGApp/1.0"})

        try:
            # The scheme is restricted to http(s) above, so urlopen is safe.
            with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
                final = urlparse(response.geturl())
                if final.scheme not in ALLOWED_IMAGE_SCHEMES or not final.netloc:
                    raise ValueError("Image URL redirected to a non-HTTP(S) location.")
                data = response.read(cls._max_image_bytes + 1)
                if len(data) > cls._max_image_bytes:
                    raise ValueError("Image is larger than the allowed limit.")
            with open(partial, "wb") as f:
                f.write(data)
            os.replace(partial, local_path)
        except Exception:
            if os.path.exists(partial):
                with suppress(OSError):
                    os.remove(partial)
            raise

    @classmethod
    def _trim_cache(cls) -> None:
        """Zadrzava najskorije koriscene fajlove, ostale brise."""
        with cls._lock:
            try:
                entries = [
                    os.path.join(cls._cache_dir, name)
                    for name in os.listdir(cls._cache_dir)
                    if os.path.splitext(name)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
                ]
                if len(entries) <= cls._max_cache_files:
                    return

                entries.sort(key=os.path.getmtime)
                for path in entries[: len(entries) - cls._max_cache_files]:
                    with suppress(OSError):
                        os.remove(path)
            except OSError as exc:
                logger.warning("Neuspelo ciscenje kes foldera: %s", exc)

    @staticmethod
    def _dispatch(schedule, func) -> None:
        if schedule is None:
            func()
        else:
            schedule(0, func)

    @staticmethod
    def _make_photo_image(pil_img):
        """PIL slika -> Tk PhotoImage, uz fallback kada ImageTk nije instaliran.

        Debian/Ubuntu cesto isporucuju Pillow bez `PIL.ImageTk` (odvojen paket
        `python3-pil.imagetk`). U tom slucaju pravimo PNG u memoriji, jer Tk
        8.6 ume da ucita PNG preko `PhotoImage(data=...)`.
        """
        try:
            image_tk = import_module("PIL.ImageTk")
            return cast(Any, image_tk).PhotoImage(pil_img)
        except ImportError:
            import base64
            import io
            import tkinter as tk

            buffer = io.BytesIO()
            pil_img.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return tk.PhotoImage(data=encoded)

    @classmethod
    def load_card_image(cls, image_url: str, callback, size=(200, 280), on_error=None, schedule=None):
        """Ucitaj sliku i pozovi callback(photo_image, local_path).

        on_error(exception) se poziva ako preuzimanje ili dekodiranje ne uspe,
        tako da UI nikad ne ostane zaglavljen na "Učitavam sliku...".
        """
        if not image_url:
            return

        cls._ensure_cache_dir()
        local_path = cls._cache_path(image_url)

        def worker():
            try:
                if not os.path.exists(local_path):
                    cls._download(image_url, local_path)
                    cls._trim_cache()

                with Image.open(local_path) as source:
                    pil_img: Image.Image = source.resize(size, Image.Resampling.LANCZOS)
                    pil_img.load()  # dekodiraj ovde, van glavne niti
            except Exception as exc:
                logger.warning("Greška pri učitavanju slike (%s): %s", image_url, exc)
                if on_error is not None:
                    # `exc` nestaje na kraju except bloka - vezujemo ga odmah.
                    error = exc
                    cls._dispatch(schedule, lambda: on_error(error))
                return

            def finish():
                # PhotoImage se pravi na glavnoj niti. Fallback u
                # _make_photo_image pokriva Pillow bez ImageTk modula.
                try:
                    photo = cls._make_photo_image(pil_img)
                except Exception as exc:
                    logger.warning("Ne mogu da napravim Tk sliku: %s", exc)
                    if on_error is not None:
                        error = exc
                        cls._dispatch(schedule, lambda: on_error(error))
                    return

                callback(photo, local_path)

            if callback is not None:
                cls._dispatch(schedule, finish)

        threading.Thread(target=worker, daemon=True).start()
