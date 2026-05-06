"""CLI entry point for the scraper.

Stages:
  bypass   — solve Cloudflare challenge once, cache cookies + UA in-memory
  discover — write urls.txt by walking the sitemap + listing pages via nodriver
  scrape   — fetch each product URL via curl_cffi, parse, append to CSV
  all      — bypass + discover + scrape (default)

The pipeline is resumable: re-running with `urls.txt` and `state.json` present
skips discovery and continues scraping from where it left off.

Most knobs (Chrome path, polite delays, base URL, etc.) are configured via
environment variables — see `src/config.py` and `.env.example`.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.cf_bypass import get_clearance
from src.config import CONFIG
from src.discover import discover_product_urls
from src.scrape import scrape_all


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape enterkomputer.com catalog")
    p.add_argument("--stage", choices=["bypass", "discover", "scrape", "all"],
                   default="all")
    p.add_argument("--rate", type=float, default=None,
                   help="Seconds between detail-page requests "
                        "(default: 3.0, or EK_SCRAPE_RATE env var). "
                        "Higher = more polite.")
    p.add_argument("--output", default="output/products.csv")
    p.add_argument("--state", default="state.json")
    p.add_argument("--urls-file", default="urls.txt")
    p.add_argument("--failed-urls-file", default="failed_urls.txt")
    p.add_argument("--limit", type=int, default=None,
                   help="For discover: cap listing pages crawled. "
                        "For scrape: cap URLs scraped. Smoke testing only.")
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


def run_discover(urls_file: str, limit: int | None) -> None:
    if Path(urls_file).exists() and Path(urls_file).stat().st_size > 0 and limit is None:
        logging.info("urls.txt exists and --limit not set; skipping discovery "
                     "(delete urls.txt to re-run)")
        return
    n = discover_product_urls(Path(urls_file), limit=limit)
    logging.info("Discovery wrote %d URLs to %s", n, urls_file)


def _resolve_rate(cli_rate: float | None) -> float:
    """CLI flag wins; otherwise fall back to EK_SCRAPE_RATE env var, else 3.0."""
    if cli_rate is not None:
        return cli_rate
    import os
    raw = os.environ.get("EK_SCRAPE_RATE")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 3.0


def run_scrape(args: argparse.Namespace, cookies: dict, user_agent: str) -> None:
    urls_path = Path(args.urls_file)
    if args.limit is not None:
        # Truncate the URL queue for smoke testing — write a side file so we
        # don't mutate the canonical urls.txt
        full = urls_path.read_text().splitlines()
        limited_path = Path(args.urls_file + ".limited")
        limited_path.write_text("\n".join(full[:args.limit]) + "\n")
        urls_to_scrape = limited_path
    else:
        urls_to_scrape = urls_path

    rate = _resolve_rate(args.rate)
    logging.info("Scrape rate: %.2fs between requests", rate)

    counts = scrape_all(
        urls_file=urls_to_scrape,
        csv_path=Path(args.output),
        state_path=Path(args.state),
        cookies=cookies,
        user_agent=user_agent,
        rate=rate,
        refresh_cookies=get_clearance,
        failed_urls_path=Path(args.failed_urls_file),
    )
    logging.info("Done. Scraped=%d Skipped=%d Failed=%d",
                 counts["scraped"], counts["skipped"], counts["failed"])


def main() -> int:
    args = parse_args()
    configure_logging(args.log_file)

    if args.stage == "bypass":
        cookies, user_agent = get_clearance()
        logging.info("Got %d cookies, UA=%s", len(cookies), user_agent[:60])
        return 0

    if args.stage == "discover":
        run_discover(args.urls_file, args.limit)
        return 0

    if args.stage == "scrape":
        cookies, user_agent = get_clearance()
        logging.info("Got %d cookies, UA=%s", len(cookies), user_agent[:60])
        run_scrape(args, cookies, user_agent)
        return 0

    # all: discover + scrape (each calls get_clearance() itself, which is fine —
    # the browser only opens for ~10 seconds at the start of each stage)
    run_discover(args.urls_file, args.limit)
    cookies, user_agent = get_clearance()
    logging.info("Got %d cookies for scrape stage, UA=%s", len(cookies), user_agent[:60])
    run_scrape(args, cookies, user_agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
