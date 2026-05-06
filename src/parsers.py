"""Pure-function HTML parsers for enterkomputer.com.

Selectors below are derived from fixtures captured 2026-05-06.
If the site's HTML changes, update the SELECTOR_* constants.

URL patterns observed:
  - Categories: /category/{id}/{slug}
  - Products:   /detail/{id}/{slug}
"""
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


# --- Selectors (derived from fixture inspection — update if site changes) ---

# Product name is in <h1 class="d-inline-block mb-0 share-title">
SELECTOR_NAME = "h1.share-title"

# Price: <span class="ps-product__price--current" data-price="850000">Rp850.000</span>
# We prefer the data-price attribute since it's already numeric
SELECTOR_PRICE = ".ps-product__price--current"

# Breadcrumb: <div class="ps-breadcrumb"><ul class="breadcrumb"><li>...<li>
SELECTOR_BREADCRUMB = ".ps-breadcrumb .breadcrumb li"

# Stock badge: <span class="ps-sbadge badge--empty"> or badge--ready
# This is inside .ps-product-status — only the first one is the product's own status
SELECTOR_STOCK = ".ps-product-status .ps-sbadge"

# Description: the meta description is the most consistent field (the
# product-specific description tab content is loaded via AJAX at runtime).
# Using itemprop="description" on the page-level meta tag would give site desc.
# Better: use the meta property="og:description" which is the same site desc.
# Actually the best parseable description is the og:description (site-level)
# or meta[itemprop="description"]. These all contain the same generic text.
# The product page has no separate product-specific description in the fixture.
# We'll use the og:description meta tag — empty string is acceptable if absent.
SELECTOR_DESCRIPTION = 'meta[property="og:description"]'

# Spec table: <table class="table table-striped specs-table">
SELECTOR_SPEC_TABLE = "table.specs-table"

# Image: primary image in the gallery slider. data-src has the real URL.
# Both fixtures show noimage.svg — we also try og:image as fallback.
SELECTOR_IMAGE = ".ps-gallery-slider .swiper-slide:first-child img"

# SKU: <b id="sku-{id}"> inside .product-id paragraph
SELECTOR_SKU = "p.product-id b[id^='sku-']"

# Listing product links
SELECTOR_LISTING_PRODUCT_LINK = "a[href*='/detail/']"


def parse_product(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    name = _parse_name(soup)
    price_idr = _parse_price_element(soup)
    category, subcategory = _parse_breadcrumb(soup)
    stock_status = _parse_stock(_attr(soup.select_one(SELECTOR_STOCK), ["class"]))
    description = _parse_description(soup)
    specifications = json.dumps(_parse_specs(soup), ensure_ascii=False)
    image_url = _absolute_image(soup, url)
    sku = _parse_sku(soup, url)

    return {
        "sku": sku,
        "name": name,
        "category": category,
        "subcategory": subcategory,
        "price_idr": price_idr,
        "stock_status": stock_status,
        "description": description,
        "specifications": specifications,
        "image_url": image_url,
        "product_url": url,
    }


def parse_listing_page(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[str] = []
    for a in soup.select(SELECTOR_LISTING_PRODUCT_LINK):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        if "/detail/" not in full:
            continue
        if full not in seen:
            seen.add(full)
            out.append(full)
    return out


# --- Helpers ---

def _text(node) -> str:
    return node.get_text(strip=True) if node else ""


def _attr(node, attrs: list[str]) -> str:
    if not node:
        return ""
    for a in attrs:
        v = node.get(a)
        if v:
            # attrs can return a list (e.g., class); join to string
            if isinstance(v, list):
                return " ".join(v)
            return v
    return ""


def _parse_name(soup) -> str:
    """Extract name from h1.share-title, stripping inner div text."""
    node = soup.select_one(SELECTOR_NAME)
    if not node:
        return ""
    # The h1 contains a nested div (.ps-product__act) with icons — strip it
    for child in node.find_all("div"):
        child.decompose()
    return node.get_text(strip=True)


def _parse_price_element(soup) -> int:
    """Extract price as integer IDR from data-price attribute or text."""
    node = soup.select_one(SELECTOR_PRICE)
    if not node:
        return 0
    # Prefer data-price attribute (already numeric)
    data_price = node.get("data-price", "")
    if data_price:
        digits = re.sub(r"[^\d]", "", data_price)
        return int(digits) if digits else 0
    # Fallback: parse text like "Rp850.000"
    return _parse_price(node.get_text(strip=True))


def _parse_price(text: str) -> int:
    if not text:
        return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def _parse_description(soup) -> str:
    """Try og:description meta tag; fallback to meta[name=description]."""
    node = soup.select_one('meta[property="og:description"]')
    if node:
        content = node.get("content", "")
        if content:
            return content
    node = soup.select_one('meta[name="description"]')
    if node:
        return node.get("content", "")
    return ""


def _parse_breadcrumb(soup) -> tuple[str, str]:
    """
    Breadcrumb structure:
      <li><a href="...">Home</a></li>
      <li><a href="...">Detail</a></li>
      <li class="last-bread">Product Name</li>

    The breadcrumb only has Home / Detail / Product Name — no category crumb.
    Fall back to .product-category and .product-subcategory paragraphs.
    """
    # Try structured category paragraph first
    cat_node = soup.select_one("p.product-category a")
    cat = cat_node.get_text(strip=True) if cat_node else ""

    subcat_node = soup.select_one("p.product-subcategory a")
    subcat = subcat_node.get_text(strip=True) if subcat_node else ""

    return cat, subcat


def _parse_stock(class_str: str) -> str:
    """Derive stock status from badge CSS class."""
    if not class_str:
        return ""
    c = class_str.lower()
    if "ready" in c:
        return "in_stock"
    if "empty" in c:
        return "out_of_stock"
    if "preorder" in c or "pre-order" in c:
        return "preorder"
    return ""


def _parse_specs(soup) -> dict:
    table = soup.select_one(SELECTOR_SPEC_TABLE)
    if not table:
        return {}
    out: dict[str, str] = {}
    # Only look at tbody rows to skip thead header row
    tbody = table.select_one("tbody")
    row_source = tbody if tbody else table
    for row in row_source.select("tr"):
        cells = row.select("td")
        if len(cells) >= 2:
            key = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            if key:
                out[key] = value
    return out


def _absolute_image(soup, page_url: str) -> str:
    """
    Try to get the primary product image in this order:
    1. Gallery slider first img data-src (lazy-loaded real URL)
    2. Gallery slider first img src
    3. og:image meta tag
    """
    node = soup.select_one(SELECTOR_IMAGE)
    if node:
        src = node.get("data-src") or node.get("src", "")
        if src and "noimage" not in src:
            return urljoin(page_url, src)

    # Fallback: og:image
    og = soup.select_one('meta[property="og:image"]')
    if og:
        content = og.get("content", "")
        if content:
            return urljoin(page_url, content)

    # Return the noimage URL if that's all we have
    if node:
        src = node.get("src", "")
        if src:
            return urljoin(page_url, src)

    return ""


def _parse_sku(soup, url: str) -> str:
    """Try explicit SKU element first; fallback to URL ID."""
    if SELECTOR_SKU:
        node = soup.select_one(SELECTOR_SKU)
        if node:
            text = node.get_text(strip=True)
            if text:
                return text
    # Fallback: extract product ID from URL pattern /detail/{id}/...
    m = re.search(r"/detail/(\d+)/", url)
    return m.group(1) if m else ""
