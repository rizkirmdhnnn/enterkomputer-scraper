"""Stage 2 — Discover semua URL detail produk.

Strategi (versi API):
  1. Solve Cloudflare sekali, dapat cookie + UA.
  2. Fetch sitemap.xml → extract semua KCODE dari URL /category/{id}/...
  3. Fetch satu category HTML → extract token + signature dari atribut
     `data-api-token` dan `data-api-signature`.
  4. Buat tiap KCODE, POST ke /jeanne/v2/product-list dengan paginasi
     (MPAGE=1, 2, 3, ...) sampai page balikin 0 produk baru.
  5. Build URL dari PCODE + PLINK: /detail/{PCODE}/{PLINK}.
  6. Dedupe + tulis ke output file.

Versi browser-based (lama) bisa dilihat di git history. API approach jauh
lebih cepat (~2 menit vs ~14 menit) dan dapat lebih banyak produk.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from curl_cffi import requests as cf_requests

from src.cf_bypass import get_clearance
from src.config import CONFIG


API_PRODUCT_LIST_PATH = "/jeanne/v2/product-list"
DETAIL_PATH_PATTERN = "/detail/"
LISTING_PATH_PATTERNS = ("/category/", "/subcategory/", "/category_brand/")
KCODE_RE = re.compile(r"/category/(\d+)/")
TOKEN_RE = re.compile(r'data-api-token="([^"]+)"')
SIGNATURE_RE = re.compile(r'data-api-signature="([^"]+)"')

# Reasonable defaults; can be tuned via env vars later if needed
MAX_PAGES_PER_CATEGORY = 100   # safety cap (terbesar yang teramati: ~21)
API_DELAY_SECS = 0.3           # jeda antar API call

log = logging.getLogger(__name__)


# ---------- Sitemap parsing (kept for backwards compat) ----------

def parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Returns (listing_urls, product_urls) — kompat dengan API lama untuk test."""
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


def extract_kcodes(listing_urls: list[str]) -> list[tuple[int, str]]:
    """Extract unique (kcode, sample_url) pairs from /category/{id}/... URLs.

    Hanya ambil top-level /category/ — /subcategory/ dan /category_brand/
    adalah subset, jadi nggak perlu di-crawl ulang.
    """
    seen: set[int] = set()
    out: list[tuple[int, str]] = []
    for url in listing_urls:
        path = urlparse(url).path
        if "/category/" not in path or "/category_brand/" in path:
            continue
        m = KCODE_RE.search(path)
        if not m:
            continue
        kcode = int(m.group(1))
        if kcode not in seen:
            seen.add(kcode)
            out.append((kcode, url))
    return out


# ---------- HTTP helpers ----------

def _build_session(cookies: dict, user_agent: str) -> cf_requests.Session:
    s = cf_requests.Session(impersonate=CONFIG.impersonate)
    s.headers.update({"User-Agent": user_agent})
    domain = "." + urlparse(CONFIG.base_url).netloc.lstrip("www.")
    for k, v in cookies.items():
        s.cookies.set(k, v, domain=domain)
    return s


def fetch_sitemap(session: cf_requests.Session) -> str:
    r = session.get(CONFIG.sitemap_url, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_api_credentials(session: cf_requests.Session, sample_category_url: str
                          ) -> tuple[str, str]:
    """Ambil token + signature dari atribut HTML di category page mana saja."""
    r = session.get(sample_category_url, timeout=30)
    r.raise_for_status()
    token_m = TOKEN_RE.search(r.text)
    sig_m = SIGNATURE_RE.search(r.text)
    if not token_m or not sig_m:
        raise RuntimeError(
            f"Could not extract API token/signature from {sample_category_url}. "
            f"Site HTML may have changed."
        )
    return token_m.group(1), sig_m.group(1)


def _api_url() -> str:
    return CONFIG.base_url.rstrip("/") + API_PRODUCT_LIST_PATH


def fetch_category_page(session: cf_requests.Session, kcode: int, page: int,
                        token: str, signature: str, referer: str) -> dict:
    payload = {
        "KCODE": str(kcode),
        "SCODE": "all",
        "BCODE": "all",
        "BNAME": "",
        "MORDR": "default",
        "MSTGE": "mapping",
        "MKYWD": "",
        "MTAGS": "",
        "MSGMN": "category",
        "MPAGE": page,
        "token": token,
        "signature": signature,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": CONFIG.base_url.rstrip("/"),
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    }
    r = session.post(_api_url(), json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def extract_products(api_response: dict) -> list[dict]:
    """Walk nested PPRNT/PCHLD/PLIST structure and return flat product dicts."""
    out: list[dict] = []
    for kgroup in api_response.get("result", []):
        for pp in kgroup.get("PPRNT", []):
            for pc in pp.get("PCHLD", []):
                for prod in pc.get("PLIST", []):
                    if isinstance(prod, dict):
                        out.append(prod)
    return out


def _normalize_url(url: str) -> str:
    """Normalisasi URL: hilangin 'www.' supaya dedup konsisten antara
    URL dari sitemap (tanpa www) dan dari API (pakai CONFIG.base_url)."""
    return url.replace("https://www.", "https://").replace("http://www.", "http://")


def product_to_url(prod: dict) -> str | None:
    pcode = prod.get("PCODE")
    plink = prod.get("PLINK")
    if not pcode or not plink:
        return None
    raw = f"{CONFIG.base_url.rstrip('/')}/detail/{pcode}/{plink}"
    return _normalize_url(raw)


# ---------- Main entry ----------

def discover_product_urls(output_path, limit: int | None = None) -> int:
    """Synchronous entry point. Returns the number of unique product URLs found."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Solving Cloudflare challenge")
    cookies, user_agent = get_clearance()

    session = _build_session(cookies, user_agent)

    log.info("Fetching sitemap")
    sitemap_xml = fetch_sitemap(session)
    listings, direct_products = parse_sitemap(sitemap_xml)
    kcode_pairs = extract_kcodes(listings)
    log.info("Sitemap: %d listings, %d direct products, %d unique KCODEs",
             len(listings), len(direct_products), len(kcode_pairs))

    if not kcode_pairs:
        log.error("No KCODEs found in sitemap — aborting")
        return 0

    if limit is not None:
        kcode_pairs = kcode_pairs[:limit]
        log.info("Limiting to first %d categories", len(kcode_pairs))

    # Get API credentials from the first category page
    sample_url = kcode_pairs[0][1]
    log.info("Extracting API token + signature from %s", sample_url)
    token, signature = fetch_api_credentials(session, sample_url)
    log.info("Got token (%d chars) + signature (%d chars)", len(token), len(signature))

    # Initial set with any direct product URLs from sitemap
    seen: set[str] = {_normalize_url(u) for u in direct_products}
    output_path.write_text("\n".join(sorted(seen)) + "\n" if seen else "")

    for idx, (kcode, ref_url) in enumerate(kcode_pairs, 1):
        added_in_category = 0
        log.info("[%d/%d] KCODE=%s (%s)", idx, len(kcode_pairs), kcode, ref_url)

        for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
            try:
                data = fetch_category_page(session, kcode, page, token, signature, ref_url)
            except Exception as e:
                log.warning("  page %d error: %s — stopping this KCODE", page, e)
                break

            if not data.get("status"):
                log.warning("  page %d API status=False, RC=%s — stopping this KCODE",
                            page, data.get("RC"))
                break

            products = extract_products(data)
            page_added = 0
            for prod in products:
                url = product_to_url(prod)
                if url and url not in seen:
                    seen.add(url)
                    page_added += 1

            if not products:
                log.info("  page %d empty, stopping pagination", page)
                break
            if page_added == 0:
                log.info("  page %d has no new products, stopping pagination", page)
                break

            added_in_category += page_added
            time.sleep(API_DELAY_SECS)
        else:
            log.warning("  hit MAX_PAGES_PER_CATEGORY (%d) for KCODE=%s",
                        MAX_PAGES_PER_CATEGORY, kcode)

        if added_in_category > 0:
            output_path.write_text("\n".join(sorted(seen)) + "\n")
        log.info("  +%d new (total unique: %d)", added_in_category, len(seen))

    log.info("Discovery complete: %d unique product URLs", len(seen))
    return len(seen)
