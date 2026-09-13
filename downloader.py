import gzip
import logging
import os
import shutil
import sys

import requests

logger = logging.getLogger(__name__)


class ScryfallDownloader:
    BASE_API_URL = "https://api.scryfall.com/bulk-data"

    def __init__(
        self,
        data_type: str = "default_cards",
        user_agent: str = "MyMTGApp/1.0 (myemail@example.com)",
        temp_file: str = "temp_scryfall_data.jsonl.gz"
    ):
        self.data_type = data_type
        self.temp_file = temp_file
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json"
        }

    @property
    def target_url(self) -> str:
        return f"{self.BASE_API_URL}/{self.data_type}"

    def _get_download_link(self) -> str | None:
        logger.info("Preuzimanje metapodataka sa Scryfall-a...")
        response = requests.get(self.target_url, headers=self.headers)
        response.raise_for_status()

        bulk_data = response.json()
        download_uri = bulk_data.get("download_uri") or bulk_data.get("jsonl_download_uri")

        if not download_uri:
            logger.error("Greška: Nije pronađen validan link za preuzimanje u API odgovoru.")
            return None

        return download_uri

    def _stream_download(self, download_uri: str) -> None:
        logger.info(f"Pronađen direktan link: {download_uri}")
        logger.info("Preuzimanje kompresovanih podataka u toku...")

        with requests.get(download_uri, headers=self.headers, stream=True) as response:
            response.raise_for_status()
            with open(self.temp_file, "wb") as f_out:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f_out.write(chunk)

    def _decompress(self, output_filename: str) -> None:
        logger.info(f"Dekompresija i prepisivanje sadržaja u '{output_filename}'...")
        with gzip.open(self.temp_file, "rb") as f_in:
            with open(output_filename, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _cleanup_temp_file(self) -> None:
        if os.path.exists(self.temp_file):
            os.remove(self.temp_file)
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

        except Exception as e:
            logger.error(f"Greška tokom ažuriranja: {e}")
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