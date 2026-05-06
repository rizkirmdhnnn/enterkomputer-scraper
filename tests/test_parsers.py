import json
from pathlib import Path

import pytest

from src.parsers import parse_product, parse_listing_page


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_product_returns_all_fields():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://enterkomputer.com/detail/180977/PANEL-LED-14-Slim-30Pin-Small-Frame-for-Acer")

    expected_keys = {
        "sku", "name", "category", "subcategory", "price_idr",
        "stock_status", "description", "specifications",
        "image_url", "product_url",
    }
    assert expected_keys.issubset(product.keys())


def test_parse_product_name_is_non_empty():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://enterkomputer.com/detail/180977/PANEL-LED-14-Slim-30Pin-Small-Frame-for-Acer")
    assert product["name"]
    assert isinstance(product["name"], str)


def test_parse_product_price_is_integer():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://enterkomputer.com/detail/180977/PANEL-LED-14-Slim-30Pin-Small-Frame-for-Acer")
    assert isinstance(product["price_idr"], int)
    assert product["price_idr"] > 0


def test_parse_product_specifications_is_json_string():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://enterkomputer.com/detail/180977/PANEL-LED-14-Slim-30Pin-Small-Frame-for-Acer")
    parsed = json.loads(product["specifications"])
    assert isinstance(parsed, dict)


def test_parse_product_url_is_preserved():
    html = _read("product_sample_2.html")
    url = "https://enterkomputer.com/detail/183843/Notebook-Keyboard-For-ACER-Swift-3"
    product = parse_product(html, url=url)
    assert product["product_url"] == url


def test_parse_product_image_url_is_absolute():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://enterkomputer.com/detail/180977/test")
    if product["image_url"]:
        assert product["image_url"].startswith("http"), \
            f"image_url should be absolute, got {product['image_url']!r}"


def test_parse_listing_page_returns_product_urls():
    html = _read("category_sample.html")
    urls = parse_listing_page(html, base_url="https://enterkomputer.com")
    assert len(urls) > 0
    for u in urls:
        assert u.startswith("http"), f"URL should be absolute: {u!r}"
        assert "/detail/" in u, f"URL should be a product detail URL: {u!r}"


def test_parse_listing_page_dedupes():
    html = _read("category_sample.html")
    urls = parse_listing_page(html, base_url="https://enterkomputer.com")
    assert len(urls) == len(set(urls))
