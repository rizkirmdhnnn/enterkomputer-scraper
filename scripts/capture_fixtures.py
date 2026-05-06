"""
Capture HTML fixtures from enterkomputer.com for offline parser development.

Uses nodriver (CDP-based, uses real Chrome) to bypass Cloudflare Turnstile.

Saves 4 files under tests/fixtures/:
  homepage.html        — site homepage
  category_sample.html — one category listing page
  product_sample_1.html — one product detail page
  product_sample_2.html — another product detail page
"""

import asyncio
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import nodriver as uc
from bs4 import BeautifulSoup

BASE_URL = "https://www.enterkomputer.com/"
FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CF_WAIT_SECS = 30   # max seconds to wait for CF challenge to clear
POLITE_DELAY = 3    # seconds between page loads


def save_html(content: str, filename: str) -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    filepath = FIXTURES_DIR / filename
    filepath.write_text(content, encoding="utf-8")
    lines = content.count("\n")
    print(f"  Saved {filepath} ({lines} lines, {len(content)//1024}KB)")


def is_cf_challenge(title: str) -> bool:
    return "Just a moment" in title or "Tunggu sebentar" in title or title == ""


def find_category_urls(html: str) -> list[str]:
    """Parse homepage HTML to find category page URLs."""
    soup = BeautifulSoup(html, "lxml")
    candidates = []
    seen = set()

    # enterkomputer.com uses /category/<slug> or similar patterns
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href:
            continue
        full_url = urljoin(BASE_URL, href)
        parsed = urlparse(full_url)
        if parsed.netloc not in ("www.enterkomputer.com", "enterkomputer.com"):
            continue
        path = parsed.path.strip("/")
        # Skip empty, anchors, and known non-category paths
        if not path or path in ("cart", "checkout", "login", "register"):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)

        # Prefer explicit category patterns
        if re.search(r"/(category|kategori|cat|c)/", parsed.path, re.IGNORECASE):
            candidates.insert(0, full_url)
        else:
            candidates.append(full_url)

    return candidates


def find_product_urls(html: str, base_url: str) -> list[str]:
    """Parse category/homepage HTML to find product detail URLs."""
    soup = BeautifulSoup(html, "lxml")
    candidates = []
    seen = set()
    skip_paths = {"cart", "checkout", "login", "register", "wishlist", "compare", "search"}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href:
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc not in ("www.enterkomputer.com", "enterkomputer.com"):
            continue
        path = parsed.path.strip("/")
        parts = path.split("/")
        if not path or parts[0] in skip_paths:
            continue
        if full_url in seen:
            continue
        seen.add(full_url)

        # Prefer explicit product patterns
        if re.search(r"/(product|produk|item|detail|p)/", parsed.path, re.IGNORECASE):
            candidates.insert(0, full_url)
        elif len(parts) >= 2:
            # Likely a product page (category/slug)
            candidates.append(full_url)

    return candidates


async def wait_for_page(page, max_secs: int = CF_WAIT_SECS) -> str:
    """Wait for CF challenge to clear and return rendered HTML."""
    for i in range(max_secs):
        await asyncio.sleep(1)
        try:
            title = await page.evaluate("document.title")
            if not is_cf_challenge(title):
                print(f"  CF cleared after {i+1}s. Title: {title}")
                break
        except Exception:
            pass
        if i % 10 == 9:
            try:
                title = await page.evaluate("document.title")
                print(f"  Still waiting at {i+1}s... title={title!r}")
            except Exception:
                print(f"  Still waiting at {i+1}s... (eval failed)")
    else:
        print(f"  WARNING: CF challenge did not clear in {max_secs}s!")

    # Extra stabilization wait
    await asyncio.sleep(2)
    content = await page.evaluate("document.documentElement.outerHTML")
    return content


async def fetch_and_save(page, url: str, filename: str) -> str:
    """Navigate to URL, wait for CF, save HTML. Returns the HTML."""
    print(f"\nFetching {url} → {filename}")
    await page.get(url)
    html = await wait_for_page(page)

    if "Just a moment" in html or "Tunggu sebentar" in html or "cf_challenge" in html:
        print("  WARNING: CF challenge still present in saved content!")

    save_html(html, filename)
    return html


async def main():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print("Starting nodriver with real Chrome...")
    browser = await uc.start(
        headless=False,
        browser_executable_path=CHROME_PATH,
    )

    try:
        # ── Step 1: Homepage ──────────────────────────────────────────────────
        # Get the first page (nodriver launches with a blank tab)
        tabs = browser.tabs
        page = tabs[0] if tabs else await browser.get("about:blank")

        homepage_html = await fetch_and_save(page, BASE_URL, "homepage.html")

        # ── Step 2: Discover URL structure ───────────────────────────────────
        print("\nInspecting homepage for URL patterns...")
        soup = BeautifulSoup(homepage_html, "lxml")
        sample_hrefs = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "enterkomputer.com" in href or href.startswith("/"):
                sample_hrefs.append(href[:80])
        print(f"  Sample hrefs (first 20): {sample_hrefs[:20]}")

        category_urls = find_category_urls(homepage_html)
        print(f"  Found {len(category_urls)} category URLs")
        print(f"  First 5: {category_urls[:5]}")

        if not category_urls:
            print("  ERROR: No category URLs found!")
            return

        # ── Step 3: Category page ─────────────────────────────────────────────
        await asyncio.sleep(POLITE_DELAY)
        category_url = category_urls[0]
        category_html = await fetch_and_save(page, category_url, "category_sample.html")

        # ── Step 4: Find product URLs ──────────────────────────────────────────
        product_urls = find_product_urls(category_html, category_url)
        print(f"\n  Found {len(product_urls)} product URLs from category page")
        print(f"  First 5: {product_urls[:5]}")

        if len(product_urls) < 2:
            print("  Not enough products; also searching homepage...")
            more = find_product_urls(homepage_html, BASE_URL)
            seen = set(product_urls)
            for u in more:
                if u not in seen:
                    product_urls.append(u)
                    seen.add(u)
            print(f"  After augmenting: {len(product_urls)} product URLs")

        # ── Step 5: Product 1 ──────────────────────────────────────────────────
        if len(product_urls) >= 1:
            await asyncio.sleep(POLITE_DELAY)
            await fetch_and_save(page, product_urls[0], "product_sample_1.html")
        else:
            print("  ERROR: No product URLs found!")

        # ── Step 6: Product 2 (different from product 1) ──────────────────────
        if len(product_urls) >= 2:
            await asyncio.sleep(POLITE_DELAY)
            await fetch_and_save(page, product_urls[1], "product_sample_2.html")
        elif len(category_urls) >= 2:
            # Try a second category
            print("  Only 1 product found; trying second category...")
            await asyncio.sleep(POLITE_DELAY)
            cat2_html = await fetch_and_save(page, category_urls[1], "_cat2_tmp.html")
            more_products = find_product_urls(cat2_html, category_urls[1])
            if more_products:
                await asyncio.sleep(POLITE_DELAY)
                await fetch_and_save(page, more_products[0], "product_sample_2.html")
            # Clean up temp file
            tmp = FIXTURES_DIR / "_cat2_tmp.html"
            if tmp.exists():
                tmp.unlink()
        else:
            print("  ERROR: Could not find a second product URL!")

    finally:
        browser.stop()
        print("\nDone! Check tests/fixtures/ for the captured HTML files.")


if __name__ == "__main__":
    asyncio.run(main())
