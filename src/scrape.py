"""Stage 3 — fetch each product detail URL via curl_cffi (Chrome TLS
fingerprint mimicry) and write a CSV row.

Why curl_cffi and not plain requests: the site is behind Cloudflare which
fingerprints TLS handshakes. Plain `requests` is detected and blocked.
curl_cffi impersonates Chrome's TLS fingerprint, so the cf_clearance cookie
plus matching fingerprint is enough to pass.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from curl_cffi import requests as cf_requests
from curl_cffi.requests.exceptions import RequestException, Timeout
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt,
    wait_exponential,
)

from src.config import CONFIG
from src.csv_writer import CsvWriter
from src.parsers import parse_product
from src.state import State


def _cookie_domain() -> str:
    """Return the apex domain (with leading dot) for cookie scope."""
    netloc = urlparse(CONFIG.base_url).netloc
    return "." + netloc.lstrip("www.")


log = logging.getLogger(__name__)


class CloudflareBlocked(Exception):
    """Raised when a 403 indicates the cf_clearance cookie expired."""


@retry(
    retry=retry_if_exception_type((RequestException, Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def _get(session, url: str):
    resp = session.get(url, timeout=30)
    if resp.status_code == 403:
        raise CloudflareBlocked(url)
    if resp.status_code >= 500:
        # 5xx — let tenacity retry by raising a RequestException
        raise RequestException(f"Server error {resp.status_code} for {url}")
    resp.raise_for_status()
    return resp


def _build_session(cookies: dict, user_agent: str):
    s = cf_requests.Session(impersonate=CONFIG.impersonate)
    s.headers.update({"User-Agent": user_agent})
    domain = _cookie_domain()
    for k, v in cookies.items():
        # Cookies set on the apex domain so subdomain requests pick them up
        s.cookies.set(k, v, domain=domain)
    return s


def scrape_all(
    urls_file: Path,
    csv_path: Path,
    state_path: Path,
    cookies: dict,
    user_agent: str,
    rate: float = 3.0,
    refresh_cookies: Callable[[], tuple[dict, str]] | None = None,
    failed_urls_path: Path | None = None,
) -> dict:
    """Returns {"scraped": N, "skipped": N, "failed": N}."""
    urls = [u.strip() for u in Path(urls_file).read_text().splitlines() if u.strip()]
    state = State(state_path)
    csv = CsvWriter(csv_path)
    failed_urls_path = failed_urls_path or Path("failed_urls.txt")

    session = _build_session(cookies, user_agent)
    completed = state.completed_urls()

    counts = {"scraped": 0, "skipped": 0, "failed": 0}

    for i, url in enumerate(urls, 1):
        if url in completed:
            counts["skipped"] += 1
            continue

        try:
            resp = _fetch_with_refresh(session, url, refresh_cookies)
        except Exception as e:
            log.error("[%d/%d] giving up on %s: %s", i, len(urls), url, e)
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
            log.info("[%d/%d] scraped: %s (%s)", i, len(urls),
                     row.get("name", "?")[:60], url)
        except Exception as e:
            log.error("[%d/%d] parse failed for %s: %s", i, len(urls), url, e)
            with failed_urls_path.open("a", encoding="utf-8") as f:
                f.write(url + "\n")
            counts["failed"] += 1

        time.sleep(rate)

    return counts


def _fetch_with_refresh(
    session,
    url: str,
    refresh_cookies: Callable[[], tuple[dict, str]] | None,
):
    try:
        return _get(session, url)
    except CloudflareBlocked:
        if not refresh_cookies:
            raise
        log.warning("403 from Cloudflare — refreshing cookies via browser")
        cookies, ua = refresh_cookies()
        session.headers["User-Agent"] = ua
        session.cookies.clear()
        domain = _cookie_domain()
        for k, v in cookies.items():
            session.cookies.set(k, v, domain=domain)
        return _get(session, url)
