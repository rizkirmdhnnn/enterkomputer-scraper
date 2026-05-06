"""Stage 2 — Discover all product detail URLs on enterkomputer.com.

Strategy:
  1. Fetch sitemap.xml (fast, polite — one HTTP request via curl_cffi).
  2. Parse it to extract listing URLs (categories, subcategories, brand pages)
     and any direct product detail URLs.
  3. For each listing URL, use nodriver to JS-render the page, click any
     "Lihat Selengkapnya" / loadMore buttons until exhausted, then extract
     all <a href*='/detail/'> URLs.
  4. Write deduplicated product URLs to the output file incrementally.

Why nodriver here and not curl_cffi: listing pages render products via the
internal /jeanne/v2/ API after page load — no product links are in the
initial HTML. Reverse-engineering that API requires rotating tokens; using
a real browser is more robust.
"""
import asyncio
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree as ET

import nodriver as uc
from curl_cffi import requests as cf_requests

from src.cf_bypass import (
    get_clearance, CHROME_PATH, _patch_nodriver_cookie_parser,
    _async_get_clearance, _browser_args,
)


SITEMAP_URL = "https://www.enterkomputer.com/sitemap.xml"
BASE_URL = "https://enterkomputer.com"
LISTING_PATH_PATTERNS = ("/category/", "/subcategory/", "/category_brand/")
DETAIL_PATH_PATTERN = "/detail/"
POLITE_DELAY = 3.0          # seconds between page navigations
LOAD_MORE_MAX_CLICKS = 50   # safety cap; categories shouldn't have more than this
LOAD_MORE_WAIT = 1.5        # seconds to wait after each loadMore click

log = logging.getLogger(__name__)


def parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Returns (listing_urls, product_urls). Listings are dedup, in order."""
    # Strip XML namespace for simpler parsing
    xml_text = re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)
    listings: list[str] = []
    products: list[str] = []
    seen_l: set[str] = set()
    seen_p: set[str] = set()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []
    for url_node in root.iter("url"):
        loc_node = url_node.find("loc")
        if loc_node is None or not loc_node.text:
            continue
        u = loc_node.text.strip()
        path = urlparse(u).path
        if any(p in path for p in LISTING_PATH_PATTERNS):
            if u not in seen_l:
                seen_l.add(u)
                listings.append(u)
        elif DETAIL_PATH_PATTERN in path:
            if u not in seen_p:
                seen_p.add(u)
                products.append(u)
    return listings, products


def fetch_sitemap(cookies: dict, user_agent: str) -> str:
    s = cf_requests.Session(impersonate="chrome120")
    s.headers.update({"User-Agent": user_agent})
    for k, v in cookies.items():
        s.cookies.set(k, v, domain=".enterkomputer.com")
    r = s.get(SITEMAP_URL, timeout=30)
    r.raise_for_status()
    return r.text


def discover_product_urls(output_path, limit: int | None = None) -> int:
    """Synchronous entry point. Returns the number of unique product URLs found."""
    return asyncio.run(_async_discover(Path(output_path), limit))


async def _async_discover(output_path: Path, limit: int | None) -> int:
    log.info("Solving Cloudflare challenge for sitemap fetch")
    cookies, user_agent = await _async_get_clearance()
    log.info("Fetching sitemap")
    sitemap_xml = fetch_sitemap(cookies, user_agent)
    listings, direct_products = parse_sitemap(sitemap_xml)
    log.info("Sitemap: %d listings, %d direct products",
             len(listings), len(direct_products))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set(direct_products)
    # Initial write of direct products
    output_path.write_text("\n".join(sorted(seen)) + "\n" if seen else "")

    if limit is not None:
        listings = listings[:limit]

    log.info("Crawling %d listing pages with nodriver (polite mode, %ss between pages)",
             len(listings), POLITE_DELAY)

    browser = await uc.start(
        headless=False,
        browser_executable_path=CHROME_PATH,
        browser_args=_browser_args(),
    )
    try:
        page = browser.tabs[0] if browser.tabs else await browser.get("about:blank")
        for i, listing_url in enumerate(listings, 1):
            log.info("[%d/%d] %s", i, len(listings), listing_url)
            try:
                new_urls = await _crawl_listing(page, listing_url)
            except Exception as e:
                log.warning("Skipped %s due to error: %s", listing_url, e)
                new_urls = []
            added = 0
            for u in new_urls:
                if u not in seen:
                    seen.add(u)
                    added += 1
            if added:
                output_path.write_text("\n".join(sorted(seen)) + "\n")
                log.info("  +%d new (%d total)", added, len(seen))
            else:
                log.info("  +0 new (%d total)", len(seen))
            await asyncio.sleep(POLITE_DELAY)
    finally:
        browser.stop()

    log.info("Discovery complete: %d unique product URLs", len(seen))
    return len(seen)


async def _crawl_listing(page, listing_url: str) -> list[str]:
    await page.get(listing_url)
    # Wait for initial render (and possible CF challenge if cookie expired)
    for _ in range(20):
        await asyncio.sleep(1)
        title = await page.evaluate("document.title")
        # nodriver may return {'type': 'string', 'value': '...'} or a plain str
        if isinstance(title, dict):
            title = title.get("value", "")
        if title and "Just a moment" not in title and "Tunggu sebentar" not in title:
            break
    await asyncio.sleep(2)  # stabilization

    # Click "Lihat Selengkapnya" / .loadMore until no more remain
    for _ in range(LOAD_MORE_MAX_CLICKS):
        clicked = await page.evaluate(
            """
            (() => {
                const btns = Array.from(document.querySelectorAll('.loadMore'));
                const visible = btns.filter(b => b.offsetParent !== null);
                if (visible.length === 0) return 0;
                visible.forEach(b => b.click());
                return visible.length;
            })()
            """
        )
        # nodriver may return a dict like {'type': 'number', 'value': 4}
        if isinstance(clicked, dict):
            clicked = clicked.get("value", 0)
        if not clicked:
            break
        await asyncio.sleep(LOAD_MORE_WAIT)

    # Extract product detail URLs
    hrefs = await page.evaluate(
        """
        Array.from(document.querySelectorAll("a[href*='/detail/']"))
             .map(a => a.href)
        """
    )
    if not hrefs:
        return []
    # Normalize + dedupe within the page
    # nodriver evaluate() returns array items as {'type': 'string', 'value': '...'}
    seen: set[str] = set()
    out: list[str] = []
    for h in hrefs:
        # Unwrap nodriver CDP remote object if needed
        if isinstance(h, dict):
            h = h.get("value", "")
        if not isinstance(h, str) or not h:
            continue
        full = urljoin(BASE_URL, h)
        if "/detail/" in full and full not in seen:
            seen.add(full)
            out.append(full)
    return out
