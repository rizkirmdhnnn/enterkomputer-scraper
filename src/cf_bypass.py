"""Solves the Cloudflare Turnstile challenge on enterkomputer.com using
nodriver (CDP-based real Chrome) and returns cookies + User-Agent for
subsequent HTTP requests.

Why nodriver and not Playwright: enterkomputer.com uses Cloudflare's managed
challenge (Turnstile). Playwright is detected and never clears. nodriver
uses real Chrome via CDP and clears the challenge within ~3-10 seconds.

Known limitation: CHROME_PATH is hardcoded to macOS. Adjust for Linux/Windows.

Workaround: nodriver==0.48 calls bool(json['sameParty']) when parsing cookies,
but newer Chrome no longer sends that field, causing the parse to fail and
the awaited CDP response to deadlock forever. We monkey-patch
network.Cookie.from_json to tolerate the missing key.
"""
import asyncio
import logging

import nodriver as uc
from nodriver import cdp
from nodriver.cdp import network


HOMEPAGE = "https://www.enterkomputer.com/"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CF_WAIT_SECS = 30

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

    Opens enterkomputer.com via nodriver, waits for the Cloudflare challenge
    to clear, and returns (cookies_dict, user_agent_string).

    Returns:
        Tuple of (cookies, user_agent). Cookies dict will contain
        'cf_clearance' on success. user_agent is the Chrome UA string.

    Raises:
        RuntimeError: If the Cloudflare challenge does not clear within
            CF_WAIT_SECS seconds.
    """
    return asyncio.run(_async_get_clearance())


async def _async_get_clearance() -> tuple[dict, str]:
    log.info("Starting nodriver to solve Cloudflare challenge")
    browser = await uc.start(
        headless=False,
        browser_executable_path=CHROME_PATH,
    )
    try:
        page = browser.tabs[0] if browser.tabs else await browser.get("about:blank")
        await page.get(HOMEPAGE)
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
    for i in range(CF_WAIT_SECS):
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
        f"Cloudflare challenge did not clear within {CF_WAIT_SECS}s "
        f"on {HOMEPAGE}"
    )
