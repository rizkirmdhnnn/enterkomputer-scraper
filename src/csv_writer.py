import csv
import threading
from pathlib import Path


FIELDNAMES = [
    "sku",
    "name",
    "category",
    "subcategory",
    "price_idr",
    "stock_status",
    "description",
    "specifications",
    "image_url",
    "product_url",
    "scraped_at",
]


class CsvWriter:
    """Appends product rows to a CSV file, writing the header exactly once.

    Thread-safe: concurrent calls to `append` are serialized via an internal
    lock so multiple worker threads can write without interleaving rows or
    duplicating the header.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, row: dict) -> None:
        with self._lock:
            needs_header = not self.path.exists() or self.path.stat().st_size == 0
            with self.path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                if needs_header:
                    writer.writeheader()
                writer.writerow({k: row.get(k, "") for k in FIELDNAMES})
