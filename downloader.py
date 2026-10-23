import gzip
import logging
import os
import shutil
import sys
from contextlib import suppress
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# (connect timeout, read timeout) in seconds.
METADATA_TIMEOUT = (10, 30)
DOWNLOAD_TIMEOUT = (10, 300)


class ScryfallDownloader:
    BASE_API_URL = "https://api.scryfall.com/bulk-data"

    def __init__(
        self,
        data_type: str = "default_cards",
        user_agent: str = "MyMTGApp/1.0 (myemail@example.com)",
        temp_file: str = "temp_scryfall_data.jsonl.gz",
    ):
        self.data_type = data_type
        self.temp_file = temp_file
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    @property
    def target_url(self) -> str:
        return f"{self.BASE_API_URL}/{self.data_type}"

    @staticmethod
    def _is_https_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme == "https" and bool(parsed.netloc)

    def _get_download_link(self) -> str | None:
        logger.info("Preuzimanje metapodataka sa Scryfall-a...")
        response = requests.get(self.target_url, headers=self.headers, timeout=METADATA_TIMEOUT)
        response.raise_for_status()

        bulk_data = response.json()
        download_uri = bulk_data.get("download_uri") or bulk_data.get("jsonl_download_uri")

        if not download_uri:
            logger.error("Greška: Nije pronađen validan link za preuzimanje u API odgovoru.")
            return None
        if not self._is_https_url(download_uri):
            logger.error("Odbijen link za preuzimanje koji nije HTTPS: %s", download_uri)
            return None

        return download_uri

    def _stream_download(self, download_uri: str) -> None:
        if not self._is_https_url(download_uri):
            raise ValueError("Download link must use HTTPS.")
        logger.info("Pronađen direktan link: %s", download_uri)
        logger.info("Preuzimanje kompresovanih podataka u toku...")

        with requests.get(download_uri, headers=self.headers, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            with open(self.temp_file, "wb") as f_out:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f_out.write(chunk)

    def _decompress(self, output_filename: str) -> None:
        """Dekompresuje u privremeni fajl, pa ga atomski zameni.

        Prekinuta dekompresija tako ne ostavlja ostecen JSONL preko kojeg bi
        se indeks sledeci put gradio.
        """
        logger.info("Dekompresija i prepisivanje sadržaja u '%s'...", output_filename)
        partial = output_filename + ".part"
        try:
            with gzip.open(self.temp_file, "rb") as f_in, open(partial, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.replace(partial, output_filename)
        except Exception:
            if os.path.exists(partial):
                with suppress(OSError):
                    os.remove(partial)
            raise

    def _cleanup_temp_file(self) -> None:
        try:
            os.remove(self.temp_file)
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("Privremena arhiva nije obrisana: %s", exc)
            return
        logger.info("Privremena arhiva je uspešno izbrisana sa diska.")

    def download_and_extract(self, output_filename: str = "scryfall_default_cards.jsonl") -> bool:
        try:
            download_uri = self._get_download_link()
            if not download_uri:
                return False

            self._stream_download(download_uri)
            self._decompress(output_filename)

            logger.info("Uspešno ažurirano i prepisano!")
            return True

        except Exception:
            logger.exception("Greška tokom ažuriranja")
            return False

        finally:
            self._cleanup_temp_file()


def download_and_extract_scryfall(output_filename: str = "scryfall_default_cards.jsonl") -> bool:
    downloader = ScryfallDownloader()
    return downloader.download_and_extract(output_filename)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    target_file = sys.argv[1] if len(sys.argv) > 1 else "scryfall_default_cards.jsonl"

    downloader = ScryfallDownloader()
    downloader.download_and_extract(target_file)
