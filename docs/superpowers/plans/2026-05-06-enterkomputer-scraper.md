# Enterkomputer.com Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrape the full product catalog from enterkomputer.com (Cloudflare-protected) into a CSV file, with resume support and polite rate limiting.

**Architecture:** Four-stage pipeline. Stage 1 uses Playwright once to solve the Cloudflare challenge and extract a `cf_clearance` cookie + matching `User-Agent`. Stages 2 (discover product URLs) and 3 (scrape detail pages) use plain `requests` with that cookie/UA. Stage 4 writes CSV incrementally so a crash never loses progress.

**Tech Stack:** Python 3.11+, Playwright (Chromium), requests, BeautifulSoup4 + lxml, tenacity, pytest.

---

## File Structure

```
enterkomputer.com/
├── src/
│   ├── __init__.py
│   ├── cf_bypass.py       # Stage 1 — Playwright cookie acquisition
│   ├── discover.py        # Stage 2 — category enumeration + URL collection
│   ├── parsers.py         # Field extractors (one function per field group)
│   ├── scrape.py          # Stage 3 — detail-page scraping loop
│   ├── csv_writer.py      # Stage 4 — incremental CSV writing
│   ├── state.py           # state.json read/write helpers
│   └── main.py            # CLI entry orchestrating all stages
├── tests/
│   ├── __init__.py
│   ├── fixtures/
│   │   ├── product_sample_1.html
│   │   ├── product_sample_2.html
│   │   └── category_sample.html
│   ├── test_parsers.py
│   ├── test_csv_writer.py
│   ├── test_state.py
│   └── test_discover.py
├── output/                # generated, .gitignored
├── logs/                  # generated, .gitignored
├── requirements.txt
├── .gitignore
└── README.md
```

Each module has one responsibility:
- `cf_bypass.py` — only knows about Playwright + Cloudflare
- `parsers.py` — pure functions: HTML in → field dict out (no I/O)
- `csv_writer.py` — only file I/O for the CSV
- `state.py` — only file I/O for resume state
- `discover.py` and `scrape.py` — orchestration that wires the pure modules to HTTP

---

## Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`, `.gitignore`, `README.md`, `src/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Initialize git repo**

```bash
cd /Users/rizkirmdhn/Documents/Code/05-Lain-lain/enterkomputer.com
git init
git branch -M main
```

- [ ] **Step 2: Create `requirements.txt`**

```
requests==2.32.3
beautifulsoup4==4.12.3
lxml==5.3.0
playwright==1.49.0
tenacity==9.0.0
pytest==8.3.4
```

- [ ] **Step 3: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.env
output/
logs/
state.json
urls.txt
failed_urls.txt
.pytest_cache/
.DS_Store
```

- [ ] **Step 4: Create empty `src/__init__.py` and `tests/__init__.py`**

```bash
touch src/__init__.py tests/__init__.py
mkdir -p tests/fixtures output logs
```

- [ ] **Step 5: Create `README.md`**

````markdown
# Enterkomputer Scraper

Scrapes the full product catalog from enterkomputer.com into `output/products.csv`.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
python -m src.main             # full pipeline (bypass + discover + scrape)
python -m src.main --stage discover
python -m src.main --stage scrape --rate 1.5
```

Resumable: re-running picks up where it left off via `state.json`.
````

- [ ] **Step 6: Set up venv and install**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```
Expected: all installs succeed, `playwright install` downloads Chromium.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .gitignore README.md src/__init__.py tests/__init__.py
git commit -m "chore: scaffold enterkomputer scraper project"
```

---

## Task 2: State module (resume support)

**Files:**
- Create: `src/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:
```python
import json
from pathlib import Path

import pytest

from src.state import State


def test_load_returns_empty_set_when_file_missing(tmp_path):
    state = State(tmp_path / "state.json")
    assert state.completed_urls() == set()


def test_mark_done_persists_url(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.mark_done("https://example.com/a")
    state.mark_done("https://example.com/b")

    reloaded = State(path)
    assert reloaded.completed_urls() == {
        "https://example.com/a",
        "https://example.com/b",
    }


def test_mark_done_is_idempotent(tmp_path):
    state = State(tmp_path / "state.json")
    state.mark_done("https://example.com/a")
    state.mark_done("https://example.com/a")
    assert state.completed_urls() == {"https://example.com/a"}


def test_state_file_is_json_with_expected_shape(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.mark_done("https://example.com/a")

    payload = json.loads(path.read_text())
    assert "completed_urls" in payload
    assert "last_updated" in payload
    assert payload["completed_urls"] == ["https://example.com/a"]
```

- [ ] **Step 2: Run tests, expect failure**

```bash
pytest tests/test_state.py -v
```
Expected: ImportError / ModuleNotFoundError for `src.state`.

- [ ] **Step 3: Implement `src/state.py`**

```python
import json
from datetime import datetime, timezone
from pathlib import Path


class State:
    """Persists the set of already-scraped URLs to a JSON file for resume support."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._completed: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self._completed = set(data.get("completed_urls", []))

    def completed_urls(self) -> set[str]:
        return set(self._completed)

    def mark_done(self, url: str) -> None:
        if url in self._completed:
            return
        self._completed.add(url)
        self._flush()

    def _flush(self) -> None:
        payload = {
            "completed_urls": sorted(self._completed),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2))
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/test_state.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat: add resumable State module"
```

---

## Task 3: CSV writer module

**Files:**
- Create: `src/csv_writer.py`
- Test: `tests/test_csv_writer.py`

The CSV header must be written exactly once (when the file is first created or empty). Subsequent appends must not re-write the header.

- [ ] **Step 1: Write the failing test**

`tests/test_csv_writer.py`:
```python
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
```

- [ ] **Step 2: Run tests, expect failure**

```bash
pytest tests/test_csv_writer.py -v
```
Expected: ImportError for `src.csv_writer`.

- [ ] **Step 3: Implement `src/csv_writer.py`**

```python
import csv
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
    """Appends product rows to a CSV file, writing the header exactly once."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, row: dict) -> None:
        needs_header = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if needs_header:
                writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/test_csv_writer.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/csv_writer.py tests/test_csv_writer.py
git commit -m "feat: add incremental CsvWriter with one-shot header"
```

---

## Task 4: Capture HTML fixtures

We need real HTML samples to develop the parser without hammering the live site. We'll grab them via Playwright (which already handles Cloudflare) and save to `tests/fixtures/`.

**Files:**
- Create: `scripts/capture_fixtures.py`

- [ ] **Step 1: Write the capture script**

`scripts/capture_fixtures.py`:
```python
"""One-off helper: opens enterkomputer.com via Playwright and saves a few
sample HTML pages to tests/fixtures/ for offline parser development.

Run once manually:
    python scripts/capture_fixtures.py
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


FIXTURE_DIR = Path("tests/fixtures")
TARGETS = {
    "homepage.html": "https://www.enterkomputer.com/",
    "category_sample.html": None,  # filled in interactively below
    "product_sample_1.html": None,
    "product_sample_2.html": None,
}


def main() -> int:
    if len(sys.argv) >= 4:
        TARGETS["category_sample.html"] = sys.argv[1]
        TARGETS["product_sample_1.html"] = sys.argv[2]
        TARGETS["product_sample_2.html"] = sys.argv[3]
    else:
        print(
            "Usage: python scripts/capture_fixtures.py "
            "<category_url> <product_url_1> <product_url_2>"
        )
        return 1

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for filename, url in TARGETS.items():
            print(f"Fetching {url} -> {filename}")
            page.goto(url, wait_until="networkidle", timeout=60_000)
            (FIXTURE_DIR / filename).write_text(page.content(), encoding="utf-8")

        browser.close()

    print("Done. Fixtures saved to tests/fixtures/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the script with three URLs picked manually**

The engineer should browse to enterkomputer.com once, copy:
- One category list URL (e.g., processor list)
- Two product detail URLs from different categories

Then:
```bash
mkdir -p scripts
# (paste script above)
python scripts/capture_fixtures.py \
  "https://www.enterkomputer.com/category/processor.html" \
  "https://www.enterkomputer.com/product/<some-product-1>.html" \
  "https://www.enterkomputer.com/product/<some-product-2>.html"
```
Expected: 4 HTML files appear under `tests/fixtures/`.

If the URLs above are wrong (path scheme differs), run `python scripts/capture_fixtures.py` once with no args, follow the printed usage, and substitute real URLs you found by browsing the live site.

- [ ] **Step 3: Verify fixtures look real**

```bash
ls -la tests/fixtures/
wc -l tests/fixtures/*.html
```
Expected: 4 files, each at least a few hundred lines.

- [ ] **Step 4: Commit fixtures and the capture script**

```bash
git add scripts/capture_fixtures.py tests/fixtures/
git commit -m "test: capture HTML fixtures for offline parser development"
```

---

## Task 5: Parser — extract product fields

**Files:**
- Create: `src/parsers.py`
- Test: `tests/test_parsers.py`

The parser is a pure function: HTML string in → field dict out. Selectors are determined by inspecting the saved fixtures. The plan below shows the parser **interface** and shape; concrete CSS selectors must be filled in based on what the fixtures actually contain.

- [ ] **Step 1: Inspect a fixture to identify selectors**

Open `tests/fixtures/product_sample_1.html` in a browser or editor and identify CSS selectors for each field. Record them in a comment block at the top of `src/parsers.py` for future maintenance. Typical patterns to look for:
- Name: `<h1>` or `[itemprop="name"]`
- Price: `[itemprop="price"]` or `.price`
- Breadcrumb: `.breadcrumb a`
- Stock: text like "In Stock" / "Out of Stock" near the buy button
- Description: `[itemprop="description"]` or `#description`
- Specifications: a `<table>` with key/value rows
- Image: `[itemprop="image"]` or `.product-image img`
- SKU: `[itemprop="sku"]` or text near the title

- [ ] **Step 2: Write the failing tests**

`tests/test_parsers.py`:
```python
import json
from pathlib import Path

import pytest

from src.parsers import parse_product, parse_listing_page


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_product_returns_all_fields():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://www.enterkomputer.com/product/sample.html")

    expected_keys = {
        "sku", "name", "category", "subcategory", "price_idr",
        "stock_status", "description", "specifications",
        "image_url", "product_url",
    }
    assert expected_keys.issubset(product.keys())


def test_parse_product_name_is_non_empty():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://www.enterkomputer.com/product/sample.html")
    assert product["name"]
    assert isinstance(product["name"], str)


def test_parse_product_price_is_integer():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://www.enterkomputer.com/product/sample.html")
    assert isinstance(product["price_idr"], int)
    assert product["price_idr"] > 0


def test_parse_product_specifications_is_json_string():
    html = _read("product_sample_1.html")
    product = parse_product(html, url="https://www.enterkomputer.com/product/sample.html")
    parsed = json.loads(product["specifications"])
    assert isinstance(parsed, dict)


def test_parse_product_url_is_preserved():
    html = _read("product_sample_2.html")
    url = "https://www.enterkomputer.com/product/another.html"
    product = parse_product(html, url=url)
    assert product["product_url"] == url


def test_parse_listing_page_returns_product_urls():
    html = _read("category_sample.html")
    urls = parse_listing_page(html, base_url="https://www.enterkomputer.com")
    assert len(urls) > 0
    assert all(u.startswith("https://www.enterkomputer.com") for u in urls)
```

- [ ] **Step 3: Run tests, expect failure**

```bash
pytest tests/test_parsers.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `src/parsers.py`**

The selectors below are placeholders. Replace each `SELECTOR_*` constant with the actual selector you identified in Step 1. The `_parse_price` and `_parse_specs` helpers are concrete; only the selector constants need adjustment.

```python
"""Pure-function HTML parsers for enterkomputer.com.

Selectors below are derived from fixtures captured 2026-05-06.
If the site's HTML changes, update the SELECTOR_* constants.
"""
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


# --- Selectors (update these to match the live site's HTML) ---
SELECTOR_NAME = "h1"
SELECTOR_PRICE = ".price, [itemprop='price']"
SELECTOR_BREADCRUMB = ".breadcrumb a, nav.breadcrumb li a"
SELECTOR_STOCK = ".stock, [itemprop='availability']"
SELECTOR_DESCRIPTION = "[itemprop='description'], #description"
SELECTOR_SPEC_TABLE = "table.spec, table.specifications, #specifications table"
SELECTOR_IMAGE = "[itemprop='image'], .product-image img"
SELECTOR_SKU = "[itemprop='sku'], .sku"
SELECTOR_LISTING_PRODUCT_LINK = "a.product-card, .product-list a.product-link"


def parse_product(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    name = _text(soup.select_one(SELECTOR_NAME))
    price_idr = _parse_price(_text(soup.select_one(SELECTOR_PRICE)))
    category, subcategory = _parse_breadcrumb(soup)
    stock_status = _parse_stock(_text(soup.select_one(SELECTOR_STOCK)))
    description = _text(soup.select_one(SELECTOR_DESCRIPTION))
    specifications = json.dumps(_parse_specs(soup), ensure_ascii=False)
    image_url = _attr(soup.select_one(SELECTOR_IMAGE), ["src", "content", "data-src"])
    sku = _text(soup.select_one(SELECTOR_SKU))

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
    out: list[str] = []
    for a in soup.select(SELECTOR_LISTING_PRODUCT_LINK):
        href = a.get("href")
        if href:
            out.append(urljoin(base_url, href))
    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


# --- Helpers ---
def _text(node) -> str:
    return node.get_text(strip=True) if node else ""


def _attr(node, attrs: list[str]) -> str:
    if not node:
        return ""
    for a in attrs:
        v = node.get(a)
        if v:
            return v
    return ""


def _parse_price(text: str) -> int:
    if not text:
        return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def _parse_breadcrumb(soup) -> tuple[str, str]:
    links = soup.select(SELECTOR_BREADCRUMB)
    parts = [a.get_text(strip=True) for a in links if a.get_text(strip=True)]
    # Drop "Home" if present
    parts = [p for p in parts if p.lower() != "home"]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    # Drop the product name (last item is typically the product itself)
    if len(parts) >= 3:
        return parts[0], parts[1]
    return parts[0], ""


def _parse_stock(text: str) -> str:
    t = text.lower()
    if "out" in t or "habis" in t:
        return "out_of_stock"
    if "preorder" in t or "pre-order" in t or "po" == t.strip():
        return "preorder"
    if t:
        return "in_stock"
    return ""


def _parse_specs(soup) -> dict:
    table = soup.select_one(SELECTOR_SPEC_TABLE)
    if not table:
        return {}
    out: dict[str, str] = {}
    for row in table.select("tr"):
        cells = row.select("th, td")
        if len(cells) >= 2:
            key = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            if key:
                out[key] = value
    return out
```

- [ ] **Step 5: Run tests against fixtures, refine selectors until green**

```bash
pytest tests/test_parsers.py -v
```
Expected: 6 passed. If any fail, adjust the `SELECTOR_*` constants in `src/parsers.py` based on what you see in the fixture HTML, then re-run. Repeat until all green.

- [ ] **Step 6: Commit**

```bash
git add src/parsers.py tests/test_parsers.py
git commit -m "feat: add pure-function parsers for product and listing pages"
```

---

## Task 6: CF bypass module

**Files:**
- Create: `src/cf_bypass.py`

This module is hard to unit-test (real network + real browser). We test it by integration during smoke testing in Task 9. The interface is: `get_clearance() -> (cookies: dict, user_agent: str)`.

- [ ] **Step 1: Implement `src/cf_bypass.py`**

```python
"""Solves the Cloudflare challenge on enterkomputer.com using Playwright
and returns the cookies + user-agent needed for subsequent requests."""
import logging

from playwright.sync_api import sync_playwright


HOMEPAGE = "https://www.enterkomputer.com/"
CHALLENGE_TIMEOUT_MS = 30_000

log = logging.getLogger(__name__)


def get_clearance() -> tuple[dict, str]:
    """Open the homepage, wait for Cloudflare to clear, and return cookies + UA."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        log.info("Navigating to %s to solve Cloudflare challenge", HOMEPAGE)
        page.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=CHALLENGE_TIMEOUT_MS)

        # Cloudflare's challenge clears once the real DOM loads. We wait for
        # a stable element that only appears on the real page.
        try:
            page.wait_for_selector("a[href*='product'], a[href*='category'], nav",
                                   timeout=CHALLENGE_TIMEOUT_MS)
        except Exception as e:
            html = page.content()[:500]
            browser.close()
            raise RuntimeError(
                f"Cloudflare challenge did not clear within "
                f"{CHALLENGE_TIMEOUT_MS}ms. First 500 chars: {html}"
            ) from e

        cookies = {c["name"]: c["value"] for c in context.cookies()}
        user_agent = page.evaluate("() => navigator.userAgent")

        browser.close()

    if "cf_clearance" not in cookies:
        log.warning(
            "cf_clearance cookie not found — Cloudflare may not have set it. "
            "Cookies present: %s", list(cookies.keys())
        )

    return cookies, user_agent
```

- [ ] **Step 2: Smoke test manually**

```bash
python -c "
import logging
logging.basicConfig(level=logging.INFO)
from src.cf_bypass import get_clearance
cookies, ua = get_clearance()
print('Cookies:', list(cookies.keys()))
print('UA:', ua[:80])
print('Has cf_clearance:', 'cf_clearance' in cookies)
"
```
Expected: prints cookie names including `cf_clearance` and a Chrome UA string. If it raises `RuntimeError`, the wait selector needs adjustment based on the live page (inspect `tests/fixtures/homepage.html`).

- [ ] **Step 3: Commit**

```bash
git add src/cf_bypass.py
git commit -m "feat: add Playwright-based Cloudflare bypass"
```

---

## Task 7: Discover module

**Files:**
- Create: `src/discover.py`
- Test: `tests/test_discover.py`

The discover module orchestrates HTTP + parsing to enumerate all product URLs across all categories, with pagination. The HTTP client is injected so tests can stub it.

- [ ] **Step 1: Write the failing test**

`tests/test_discover.py`:
```python
from src.discover import discover_product_urls


class FakeClient:
    """Minimal stand-in for requests.Session — returns canned HTML by URL."""
    def __init__(self, pages: dict):
        self.pages = pages

    def get(self, url, **_):
        class R:
            def __init__(self, text, status):
                self.text = text
                self.status_code = status
        if url in self.pages:
            return R(self.pages[url], 200)
        return R("<html></html>", 404)


HOME = "https://www.enterkomputer.com/"
CAT = "https://www.enterkomputer.com/category/processor.html"
HOMEPAGE_HTML = f"""
<html><body>
  <nav><a href="/category/processor.html">Processor</a></nav>
</body></html>
"""
CATEGORY_PAGE_1 = f"""
<html><body>
  <a class="product-card" href="/product/p1.html">P1</a>
  <a class="product-card" href="/product/p2.html">P2</a>
  <a class="next" href="/category/processor.html?page=2">Next</a>
</body></html>
"""
CATEGORY_PAGE_2 = f"""
<html><body>
  <a class="product-card" href="/product/p3.html">P3</a>
</body></html>
"""


def test_discover_walks_categories_and_pagination():
    client = FakeClient({
        HOME: HOMEPAGE_HTML,
        CAT: CATEGORY_PAGE_1,
        CAT + "?page=2": CATEGORY_PAGE_2,
    })
    urls = discover_product_urls(client, base_url=HOME)
    assert set(urls) == {
        "https://www.enterkomputer.com/product/p1.html",
        "https://www.enterkomputer.com/product/p2.html",
        "https://www.enterkomputer.com/product/p3.html",
    }


def test_discover_deduplicates_urls_across_categories():
    cat2 = "https://www.enterkomputer.com/category/motherboard.html"
    home = """
<html><body><nav>
  <a href="/category/processor.html">P</a>
  <a href="/category/motherboard.html">M</a>
</nav></body></html>
"""
    same_product = """
<html><body>
  <a class="product-card" href="/product/shared.html">S</a>
</body></html>
"""
    client = FakeClient({
        HOME: home,
        CAT: same_product,
        cat2: same_product,
    })
    urls = discover_product_urls(client, base_url=HOME)
    assert urls.count("https://www.enterkomputer.com/product/shared.html") == 1
```

- [ ] **Step 2: Run tests, expect failure**

```bash
pytest tests/test_discover.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/discover.py`**

Selectors for category-link extraction and "next page" link must match the live site. Adjust the constants below based on the homepage and category fixtures.

```python
"""Walks enterkomputer.com to enumerate every product URL."""
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.parsers import parse_listing_page


SELECTOR_CATEGORY_LINK = "nav a[href*='/category/']"
SELECTOR_NEXT_PAGE = "a.next, a[rel='next']"

log = logging.getLogger(__name__)


def discover_product_urls(client, base_url: str) -> list[str]:
    """Returns a deduplicated list of product URLs found across all categories."""
    category_urls = _find_category_urls(client, base_url)
    log.info("Found %d categories", len(category_urls))

    seen: set[str] = set()
    out: list[str] = []
    for cat_url in category_urls:
        for product_url in _walk_category(client, cat_url, base_url):
            if product_url not in seen:
                seen.add(product_url)
                out.append(product_url)
    return out


def _find_category_urls(client, base_url: str) -> list[str]:
    resp = client.get(base_url)
    soup = BeautifulSoup(resp.text, "lxml")
    urls: list[str] = []
    seen: set[str] = set()
    for a in soup.select(SELECTOR_CATEGORY_LINK):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def _walk_category(client, start_url: str, base_url: str):
    url = start_url
    while url:
        log.info("Listing page: %s", url)
        resp = client.get(url)
        if resp.status_code != 200:
            log.warning("Listing returned %s for %s", resp.status_code, url)
            return
        for product_url in parse_listing_page(resp.text, base_url):
            yield product_url
        url = _next_page_url(resp.text, base_url)


def _next_page_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    nxt = soup.select_one(SELECTOR_NEXT_PAGE)
    if nxt and nxt.get("href"):
        return urljoin(base_url, nxt["href"])
    return None
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/test_discover.py -v
```
Expected: 2 passed. If they fail, the FakeClient's HTML uses selectors `nav a[href*='/category/']` and `a.product-card` and `a.next` — make sure the constants match.

- [ ] **Step 5: Commit**

```bash
git add src/discover.py tests/test_discover.py
git commit -m "feat: add category + pagination URL discovery"
```

---

## Task 8: Scrape module (Stage 3 orchestrator)

**Files:**
- Create: `src/scrape.py`

This module reads `urls.txt`, filters via `State`, fetches each URL with retry/backoff, parses, and appends to the CsvWriter. It's the most I/O-heavy module; we test it via the Task 9 smoke test rather than mocking out every dependency.

- [ ] **Step 1: Implement `src/scrape.py`**

```python
"""Stage 3: fetch each product detail URL and write a CSV row."""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt,
    wait_exponential,
)

from src.csv_writer import CsvWriter
from src.parsers import parse_product
from src.state import State


log = logging.getLogger(__name__)


class CloudflareBlocked(Exception):
    """Raised when a 403 indicates the cf_clearance cookie expired."""


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _get(session: requests.Session, url: str) -> requests.Response:
    resp = session.get(url, timeout=30)
    if resp.status_code == 403:
        raise CloudflareBlocked(url)
    resp.raise_for_status()
    return resp


def scrape_all(
    urls_file: Path,
    csv_path: Path,
    state_path: Path,
    cookies: dict,
    user_agent: str,
    rate: float = 1.0,
    refresh_cookies: Callable[[], tuple[dict, str]] | None = None,
    failed_urls_path: Path | None = None,
) -> dict:
    """Returns {"scraped": N, "skipped": N, "failed": N}."""
    urls = [u.strip() for u in Path(urls_file).read_text().splitlines() if u.strip()]
    state = State(state_path)
    csv = CsvWriter(csv_path)
    failed_urls_path = failed_urls_path or Path("failed_urls.txt")

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    session.cookies.update(cookies)

    counts = {"scraped": 0, "skipped": 0, "failed": 0}
    completed = state.completed_urls()

    for url in urls:
        if url in completed:
            counts["skipped"] += 1
            continue

        try:
            resp = _fetch_with_refresh(session, url, refresh_cookies)
        except Exception as e:
            log.error("Giving up on %s: %s", url, e)
            with failed_urls_path.open("a", encoding="utf-8") as f:
                f.write(url + "\n")
            counts["failed"] += 1
            continue

        try:
            row = parse_product(resp.text, url)
            row["scraped_at"] = datetime.now(timezone.utc).isoformat()
            csv.append(row)
            state.mark_done(url)
            counts["scraped"] += 1
            log.info("Scraped %s (%s)", row.get("name", "?")[:60], url)
        except Exception as e:
            log.error("Parse failed for %s: %s", url, e)
            with failed_urls_path.open("a", encoding="utf-8") as f:
                f.write(url + "\n")
            counts["failed"] += 1

        time.sleep(rate)

    return counts


def _fetch_with_refresh(
    session: requests.Session,
    url: str,
    refresh_cookies: Callable[[], tuple[dict, str]] | None,
) -> requests.Response:
    try:
        return _get(session, url)
    except CloudflareBlocked:
        if not refresh_cookies:
            raise
        log.warning("403 from Cloudflare — refreshing cookies")
        cookies, ua = refresh_cookies()
        session.headers["User-Agent"] = ua
        session.cookies.clear()
        session.cookies.update(cookies)
        return _get(session, url)
```

- [ ] **Step 2: Quick syntax check**

```bash
python -c "from src.scrape import scrape_all; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/scrape.py
git commit -m "feat: add detail-page scraping with retry and cookie refresh"
```

---

## Task 9: Main CLI orchestrator

**Files:**
- Create: `src/main.py`

- [ ] **Step 1: Implement `src/main.py`**

```python
"""CLI entry point for the enterkomputer scraper."""
import argparse
import logging
from pathlib import Path

import requests

from src.cf_bypass import get_clearance
from src.discover import discover_product_urls
from src.scrape import scrape_all


BASE_URL = "https://www.enterkomputer.com/"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape enterkomputer.com catalog")
    p.add_argument("--stage", choices=["bypass", "discover", "scrape", "all"],
                   default="all")
    p.add_argument("--rate", type=float, default=1.0,
                   help="Seconds between detail-page requests")
    p.add_argument("--output", default="output/products.csv")
    p.add_argument("--state", default="state.json")
    p.add_argument("--urls-file", default="urls.txt")
    p.add_argument("--failed-urls-file", default="failed_urls.txt")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap total URLs scraped (for smoke testing)")
    p.add_argument("--log-file", default="logs/scraper.log")
    return p.parse_args()


def configure_logging(log_file: str) -> None:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def make_session(cookies: dict, user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent})
    s.cookies.update(cookies)
    return s


def run_discover(cookies: dict, user_agent: str, urls_file: str) -> None:
    if Path(urls_file).exists() and Path(urls_file).stat().st_size > 0:
        logging.info("urls.txt exists, skipping discovery (delete it to re-run)")
        return
    session = make_session(cookies, user_agent)
    urls = discover_product_urls(session, base_url=BASE_URL)
    Path(urls_file).write_text("\n".join(urls))
    logging.info("Discovered %d product URLs -> %s", len(urls), urls_file)


def main() -> int:
    args = parse_args()
    configure_logging(args.log_file)

    cookies: dict = {}
    user_agent = ""

    if args.stage in ("bypass", "discover", "scrape", "all"):
        cookies, user_agent = get_clearance()
        logging.info("Got %d cookies, UA=%s", len(cookies), user_agent[:60])
        if args.stage == "bypass":
            return 0

    if args.stage in ("discover", "all"):
        run_discover(cookies, user_agent, args.urls_file)
        if args.stage == "discover":
            return 0

    if args.stage in ("scrape", "all"):
        if args.limit is not None:
            # Truncate the URL queue for smoke testing
            full = Path(args.urls_file).read_text().splitlines()
            Path(args.urls_file + ".limited").write_text("\n".join(full[:args.limit]))
            urls_path = Path(args.urls_file + ".limited")
        else:
            urls_path = Path(args.urls_file)

        counts = scrape_all(
            urls_file=urls_path,
            csv_path=Path(args.output),
            state_path=Path(args.state),
            cookies=cookies,
            user_agent=user_agent,
            rate=args.rate,
            refresh_cookies=get_clearance,
            failed_urls_path=Path(args.failed_urls_file),
        )
        logging.info("Done. Scraped=%d Skipped=%d Failed=%d",
                     counts["scraped"], counts["skipped"], counts["failed"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke test bypass + discover only**

```bash
rm -f urls.txt
python -m src.main --stage discover
head -20 urls.txt
wc -l urls.txt
```
Expected: `urls.txt` contains ≥ a few hundred product URLs. Sample lines look like real product URLs.

- [ ] **Step 3: Smoke test scrape on 5 URLs**

```bash
rm -f output/products.csv state.json failed_urls.txt
python -m src.main --stage scrape --limit 5 --rate 1.0
cat output/products.csv | head -10
```
Expected: header + 5 data rows; `state.json` has 5 completed URLs.

If any field comes through empty for all 5 rows, the corresponding selector in `src/parsers.py` is wrong. Fix the selector and re-run (delete `state.json` and `output/products.csv` first).

- [ ] **Step 4: Commit**

```bash
git add src/main.py
git commit -m "feat: add CLI orchestrator for full pipeline"
```

---

## Task 10: Full run

- [ ] **Step 1: Reset any partial state**

```bash
rm -f output/products.csv state.json failed_urls.txt urls.txt urls.txt.limited
```

- [ ] **Step 2: Run the full pipeline**

```bash
python -m src.main --stage all --rate 1.0
```
Expected runtime: depends on catalog size. At 1 req/s, 5,000 products = ~85 minutes. Watch `logs/scraper.log` in another terminal:
```bash
tail -f logs/scraper.log
```
The run is resumable: if it crashes or you Ctrl-C, just rerun the same command.

- [ ] **Step 3: Verify output**

```bash
wc -l output/products.csv          # rows count
head -3 output/products.csv         # header + 2 sample rows
wc -l failed_urls.txt 2>/dev/null   # any failures (ideally 0 or low)
```
Expected: CSV row count ≈ URL count, low/zero failures.

- [ ] **Step 4: Commit final state (optional, or just keep CSV out of git)**

`output/`, `state.json`, `urls.txt`, `failed_urls.txt` are already in `.gitignore`. Only the source code is in git. You can tag the run:
```bash
git tag -a "first-full-run-$(date +%Y%m%d)" -m "Initial full catalog scrape"
```

---

## Self-review checklist (already done by author)

- ✅ Spec coverage: every spec section maps to a task
  - Stage 1 (CF Bypass) → Task 6
  - Stage 2 (Discover) → Task 7
  - Stage 3 (Scrape) → Task 8
  - Stage 4 (Output: CSV + state) → Tasks 2, 3
  - Data Model → Task 5 (parsers) + Task 3 (FIELDNAMES)
  - File layout → Task 1
  - Configuration (CLI flags) → Task 9
  - Politeness (rate limit, retry, backoff) → Task 8
  - Error handling (403 refresh, parse fail, failed_urls) → Task 8
  - Testing (parser unit tests with fixtures, smoke test) → Tasks 5, 9
- ✅ Placeholder scan: no TBDs. Selectors are explicitly flagged for empirical adjustment with the exact step where you adjust them.
- ✅ Type consistency: `cookies: dict`, `user_agent: str`, `parse_product(html, url) -> dict` used consistently across cf_bypass, scrape, main.
