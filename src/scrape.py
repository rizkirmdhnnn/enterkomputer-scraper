"""Stage 3 — fetch each product detail URL via curl_cffi (Chrome TLS
fingerprint mimicry) and write a CSV row.

Why curl_cffi and not plain requests: the site is behind Cloudflare which
fingerprints TLS handshakes. Plain `requests` is detected and blocked.
curl_cffi impersonates Chrome's TLS fingerprint, so the cf_clearance cookie
plus matching fingerprint is enough to pass.

Concurrency: when `workers > 1`, URLs are processed in parallel via a
ThreadPoolExecutor. Each worker has its own curl_cffi Session. When CF
returns 403, a single shared refresh path runs (lock-protected) and the
new cookies are propagated to all workers' next requests.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


log = logging.getLogger(__name__)


def _cookie_domain() -> str:
    """Return the apex domain (with leading dot) for cookie scope."""
    netloc = urlparse(CONFIG.base_url).netloc
    return "." + netloc.lstrip("www.")


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


class _SharedCreds:
    """Cookies + UA shared across all workers, with lock-protected refresh."""

    def __init__(self, cookies: dict, user_agent: str,
                 refresh_fn: Callable[[], tuple[dict, str]] | None):
        self._cookies = dict(cookies)
        self._user_agent = user_agent
        self._refresh_fn = refresh_fn
        self._version = 0  # bumps each time refresh succeeds
        self._lock = threading.Lock()

    def snapshot(self) -> tuple[dict, str, int]:
        with self._lock:
            return dict(self._cookies), self._user_agent, self._version

    def refresh_if_stale(self, seen_version: int) -> tuple[dict, str, int]:
        """Trigger a browser-backed refresh, but only if no other thread already
        did one since `seen_version`. Returns the latest creds + version.
        """
        with self._lock:
            if self._refresh_fn is None:
                raise RuntimeError("Cannot refresh cookies: no refresh_fn provided")
            if self._version > seen_version:
                # Another thread already refreshed; reuse its result
                return dict(self._cookies), self._user_agent, self._version
            log.warning("Refreshing cf_clearance via browser (version %d → %d)",
                        self._version, self._version + 1)
            new_cookies, new_ua = self._refresh_fn()
            self._cookies = dict(new_cookies)
            self._user_agent = new_ua
            self._version += 1
            return dict(self._cookies), self._user_agent, self._version


def _apply_creds_to_session(session, cookies: dict, user_agent: str) -> None:
    session.headers["User-Agent"] = user_agent
    session.cookies.clear()
    domain = _cookie_domain()
    for k, v in cookies.items():
        session.cookies.set(k, v, domain=domain)


def _fetch_with_shared_refresh(session, session_version: int, url: str,
                               creds: _SharedCreds) -> tuple:
    """Returns (response, new_session_version)."""
    try:
        return _get(session, url), session_version
    except CloudflareBlocked:
        new_cookies, new_ua, new_version = creds.refresh_if_stale(session_version)
        _apply_creds_to_session(session, new_cookies, new_ua)
        return _get(session, url), new_version


def scrape_all(
    urls_file: Path,
    csv_path: Path,
    state_path: Path,
    cookies: dict,
    user_agent: str,
    rate: float = 3.0,
    workers: int = 1,
    refresh_cookies: Callable[[], tuple[dict, str]] | None = None,
    failed_urls_path: Path | None = None,
) -> dict:
    """Returns {"scraped": N, "skipped": N, "failed": N}.

    With `workers > 1`, URLs are scraped in parallel. Each worker sleeps
    `rate` seconds between its own requests, so aggregate throughput is
    roughly `workers / rate` requests per second.
    """
    urls = [u.strip() for u in Path(urls_file).read_text().splitlines() if u.strip()]
    state = State(state_path)
    csv = CsvWriter(csv_path)
    failed_urls_path = failed_urls_path or Path("failed_urls.txt")
    failed_urls_lock = threading.Lock()

    creds = _SharedCreds(cookies, user_agent, refresh_cookies)

    completed = state.completed_urls()
    pending: list[tuple[int, str]] = []
    skipped = 0
    for idx, url in enumerate(urls, 1):
        if url in completed:
            skipped += 1
        else:
            pending.append((idx, url))

    counts = {"scraped": 0, "skipped": skipped, "failed": 0}
    counts_lock = threading.Lock()
    total = len(urls)

    log.info("Scrape: %d total, %d already done, %d pending, workers=%d, rate=%.2fs",
             total, skipped, len(pending), workers, rate)

    def write_failed(url: str) -> None:
        with failed_urls_lock:
            with failed_urls_path.open("a", encoding="utf-8") as f:
                f.write(url + "\n")

    # Thread-local session storage — each worker thread builds its session once
    _thread_local = threading.local()

    def init_worker() -> None:
        cookies_snap, ua_snap, version_snap = creds.snapshot()
        _thread_local.session = _build_session(cookies_snap, ua_snap)
        _thread_local.version = version_snap

    def scrape_one(idx: int, url: str) -> None:
        session = _thread_local.session
        session_version = _thread_local.version

        try:
            resp, session_version = _fetch_with_shared_refresh(
                session, session_version, url, creds
            )
            _thread_local.version = session_version
        except Exception as e:
            log.error("[%d/%d] giving up on %s: %s", idx, total, url, e)
            write_failed(url)
            with counts_lock:
                counts["failed"] += 1
            return

        try:
            row = parse_product(resp.text, url)
            row["scraped_at"] = datetime.now(timezone.utc).isoformat()
            csv.append(row)
            state.mark_done(url)
            with counts_lock:
                counts["scraped"] += 1
            log.info("[%d/%d] scraped: %s (%s)", idx, total,
                     row.get("name", "?")[:60], url)
        except Exception as e:
            log.error("[%d/%d] parse failed for %s: %s", idx, total, url, e)
            write_failed(url)
            with counts_lock:
                counts["failed"] += 1

        if rate > 0:
            time.sleep(rate)

    if workers <= 1:
        # Single-threaded path — no executor overhead
        init_worker()
        for idx, url in pending:
            scrape_one(idx, url)
    else:
        # Parallel path — ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers, initializer=init_worker) as ex:
            futures = [ex.submit(scrape_one, idx, url) for idx, url in pending]
            for f in as_completed(futures):
                f.result()  # propagate any exception escaped from scrape_one

    return counts
