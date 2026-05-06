"""Solves the Cloudflare Turnstile challenge using nodriver (CDP-based real
Chrome) and returns cookies + User-Agent for subsequent HTTP requests.

Why nodriver and not Playwright: the site uses Cloudflare's managed
challenge (Turnstile). Playwright is detected and never clears. nodriver
drives a real Chrome instance via CDP, which clears the challenge in seconds.

Why a visible (offscreen) window and not pure headless: --headless=new and
headless=True both still get flagged by CF Turnstile, so we run a normal
window but position it offscreen by default. Configurable via the env vars
documented in `src/config.py` (`EK_SHOW_BROWSER`, `EK_OFFSCREEN_POSITION`).

Workaround: nodriver==0.48 calls bool(json['sameParty']) when parsing
cookies, but newer Chrome no longer sends that field — the parse fails and
the awaited CDP response deadlocks. We monkey-patch network.Cookie.from_json
to tolerate the missing key.
"""
from __future__ import annotations

import asyncio
import logging

import nodriver as uc
from nodriver import cdp
from nodriver.cdp import network

from src.config import CONFIG, require_chrome_path


log = logging.getLogger(__name__)


def _patch_nodriver_cookie_parser() -> None:
    """Make Cookie.from_json tolerant of missing 'sameParty' key."""
    original = network.Cookie.from_json

    def patched(json):
        json.setdefault("sameParty", False)
        return original(json)

    network.Cookie.from_json = staticmethod(patched)


_patch_nodriver_cookie_parser()


def get_clearance() -> tuple[dict, str]:
    """Synchronous wrapper around the async clearance flow.

    Opens the site homepage via nodriver, waits for the Cloudflare challenge
    to clear, and returns (cookies_dict, user_agent_string).

    Returns:
        Tuple of (cookies, user_agent). Cookies dict will contain
        'cf_clearance' on success. user_agent is the Chrome UA string.

    Raises:
        RuntimeError: If Chrome is not installed, or the Cloudflare challenge
            does not clear within CONFIG.cf_wait_secs seconds.
    """
    return asyncio.run(_async_get_clearance())


async def _async_get_clearance() -> tuple[dict, str]:
    chrome_path = require_chrome_path()
    log.info("Starting nodriver to solve Cloudflare challenge "
             "(show_browser=%s)", CONFIG.show_browser)
    browser = await uc.start(
        headless=False,
        browser_executable_path=chrome_path,
        browser_args=CONFIG.browser_args(),
    )
    try:
        page = browser.tabs[0] if browser.tabs else await browser.get("about:blank")
        await page.get(CONFIG.base_url)
        await _wait_for_clearance(page)

        cookies_list = await page.send(cdp.storage.get_cookies())
        cookies = {c.name: c.value for c in cookies_list}

        user_agent = await page.evaluate("navigator.userAgent")
    finally:
        browser.stop()

    if "cf_clearance" not in cookies:
        log.warning(
            "cf_clearance cookie missing — Cloudflare may not have set it. "
            "Cookies present: %s", list(cookies.keys())
        )
    log.info("Got %d cookies. cf_clearance present: %s",
             len(cookies), "cf_clearance" in cookies)
    return cookies, user_agent


async def _wait_for_clearance(page) -> None:
    for i in range(CONFIG.cf_wait_secs):
        await asyncio.sleep(1)
        try:
            title = await page.evaluate("document.title")
            if title and "Just a moment" not in title and "Tunggu sebentar" not in title:
                log.info("Cloudflare cleared after %ds (title=%r)", i + 1, title)
                await asyncio.sleep(2)
                return
        except Exception:
            pass
    raise RuntimeError(
        f"Cloudflare challenge did not clear within {CONFIG.cf_wait_secs}s "
        f"on {CONFIG.base_url}"
    )
