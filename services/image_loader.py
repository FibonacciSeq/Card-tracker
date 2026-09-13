import logging
import os
import threading
import urllib.request

from PIL import Image

logger = logging.getLogger(__name__)


class ImageLoader:
    """Preuzima slike kartica u pozadini, uz kes na disku.

    Tk nije thread-safe: PhotoImage se pravi tek na glavnoj niti, preko
    `schedule` (obicno `widget.after`). Preuzimanje i dekodiranje PIL-om
    ostaju u pozadinskoj niti.
    """

    _cache_dir = "image_cache"
    _max_cache_files = 2000
    _lock = threading.Lock()

    @classmethod
    def _ensure_cache_dir(cls):
        os.makedirs(cls._cache_dir, exist_ok=True)

    @classmethod
    def _cache_path(cls, image_url: str) -> str:
        filename = image_url.split("/")[-1].split("?")[0]
        if not filename.endswith(".jpg"):
            filename += ".jpg"
        return os.path.join(cls._cache_dir, filename)

    @classmethod
    def _download(cls, image_url: str, local_path: str) -> None:
        """Skida u .part pa preimenuje, da prekid ne ostavi polovicnu sliku."""
        partial = local_path + ".part"
        request = urllib.request.Request(image_url, headers={"User-Agent": "MyMTGApp/1.0"})

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                with open(partial, "wb") as f:
                    f.write(response.read())
            os.replace(partial, local_path)
        except Exception:
            if os.path.exists(partial):
                try:
                    os.remove(partial)
                except OSError:
                    pass
            raise

    @classmethod
    def _trim_cache(cls) -> None:
        """Zadrzava najskorije koriscene fajlove, ostale brise."""
        with cls._lock:
            try:
                entries = [
                    os.path.join(cls._cache_dir, name)
                    for name in os.listdir(cls._cache_dir)
                    if name.endswith(".jpg")
                ]
                if len(entries) <= cls._max_cache_files:
                    return

                entries.sort(key=os.path.getmtime)
                for path in entries[: len(entries) - cls._max_cache_files]:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            except OSError as exc:
                logger.warning("Neuspelo ciscenje kes foldera: %s", exc)

    @staticmethod
    def _dispatch(schedule, func) -> None:
        if schedule is None:
            func()
        else:
            schedule(0, func)

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

                pil_img = Image.open(local_path)
                pil_img = pil_img.resize(size, Image.Resampling.LANCZOS)
                pil_img.load()  # dekodiraj ovde, van glavne niti
            except Exception as exc:
                logger.warning("Greška pri učitavanju slike (%s): %s", image_url, exc)
                if on_error is not None:
                    # `exc` nestaje na kraju except bloka - vezujemo ga odmah.
                    error = exc
                    cls._dispatch(schedule, lambda: on_error(error))
                return

            def finish():
                # PhotoImage se pravi na glavnoj niti. ImageTk se uvozi ovde
                # da modul ostane upotrebljiv (i testabilan) bez Tk-a.
                from PIL import ImageTk

                callback(ImageTk.PhotoImage(pil_img), local_path)

            if callback is not None:
                cls._dispatch(schedule, finish)

        threading.Thread(target=worker, daemon=True).start()
