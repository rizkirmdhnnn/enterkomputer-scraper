"""Tests bahwa State dan CsvWriter aman dipakai dari banyak thread bareng-
an: nggak ada URL yang hilang, header CSV nggak duplikat, baris nggak
overlap.
"""
import csv
import threading

import pytest

from src.csv_writer import CsvWriter, FIELDNAMES
from src.state import State


def _row(sku: str) -> dict:
    return {
        "sku": sku,
        "name": f"Product {sku}",
        "category": "Test",
        "subcategory": "",
        "price_idr": 1000,
        "stock_status": "in_stock",
        "description": "test",
        "specifications": "{}",
        "image_url": "",
        "product_url": f"https://example.com/p/{sku}",
        "scraped_at": "2026-01-01T00:00:00+00:00",
    }


def test_state_concurrent_mark_done_no_lost_writes(tmp_path):
    state = State(tmp_path / "state.json")
    n_threads = 20
    per_thread = 50

    def worker(tid: int) -> None:
        for i in range(per_thread):
            state.mark_done(f"https://example.com/t{tid}/u{i}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(state.completed_urls()) == n_threads * per_thread


def test_state_idempotent_under_concurrency(tmp_path):
    state = State(tmp_path / "state.json")
    url = "https://example.com/same"

    def worker():
        for _ in range(100):
            state.mark_done(url)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert state.completed_urls() == {url}


def test_csv_writer_concurrent_append_no_corrupt(tmp_path):
    path = tmp_path / "products.csv"
    writer = CsvWriter(path)
    n_threads = 10
    per_thread = 50

    def worker(tid: int) -> None:
        for i in range(per_thread):
            writer.append(_row(f"t{tid}-i{i}"))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads: t.start()
    for t in threads: t.join()

    rows = list(csv.DictReader(path.open()))
    assert len(rows) == n_threads * per_thread
    # Header written exactly once → CSV header is the first line of file
    first_line = path.read_text().splitlines()[0]
    assert first_line == ",".join(FIELDNAMES)
    # All SKUs unique
    skus = {r["sku"] for r in rows}
    assert len(skus) == n_threads * per_thread
