import csv
from pathlib import Path

from src.csv_writer import CsvWriter, FIELDNAMES


SAMPLE_ROW = {
    "sku": "ABC123",
    "name": "Test Product",
    "category": "Processor",
    "subcategory": "Intel",
    "price_idr": 1500000,
    "stock_status": "in_stock",
    "description": "A test product.",
    "specifications": '{"socket": "LGA1700"}',
    "image_url": "https://example.com/img.jpg",
    "product_url": "https://example.com/p/abc",
    "scraped_at": "2026-05-06T10:00:00+00:00",
}


def test_writes_header_on_first_append(tmp_path):
    path = tmp_path / "products.csv"
    writer = CsvWriter(path)
    writer.append(SAMPLE_ROW)

    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 1
    assert rows[0]["sku"] == "ABC123"
    assert rows[0]["price_idr"] == "1500000"


def test_does_not_rewrite_header_on_subsequent_appends(tmp_path):
    path = tmp_path / "products.csv"
    writer = CsvWriter(path)
    writer.append(SAMPLE_ROW)
    writer.append({**SAMPLE_ROW, "sku": "XYZ"})

    lines = path.read_text().splitlines()
    # 1 header + 2 data rows
    assert len(lines) == 3
    assert lines[0] == ",".join(FIELDNAMES)


def test_resumes_existing_file_without_duplicating_header(tmp_path):
    path = tmp_path / "products.csv"
    CsvWriter(path).append(SAMPLE_ROW)

    # Simulate restart
    CsvWriter(path).append({**SAMPLE_ROW, "sku": "XYZ"})

    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 2
    assert {r["sku"] for r in rows} == {"ABC123", "XYZ"}
