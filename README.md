# Enterkomputer Scraper

A polite, resumable scraper for the [enterkomputer.com](https://www.enterkomputer.com/)
PC-parts catalog. Uses **`nodriver`** to solve Cloudflare Turnstile and **`curl_cffi`**
(Chrome TLS fingerprint mimicry) for fast detail-page fetches. Output is a
single CSV with full product info.

> ⚠️ **Disclaimer.** The site's `robots.txt` disallows non-Googlebot scraping
> (`User-agent: * / Disallow: /`). This project is published for **educational
> and research purposes only**. Use it on a site you own, on a test target,
> or with the site owner's explicit permission. The defaults run in
> single-threaded "polite" mode (3 seconds between requests). Do not republish
> the scraped data commercially.

---

## Why this exists

Most public scraper recipes break against Cloudflare's modern stack:

- Plain `requests` → 403 (TLS fingerprint mismatch).
- `Playwright` (even with stealth plugins) → blocked by Turnstile.
- Pure headless Chrome → also detected.
- Listing pages on the target render products via an internal JSON API with
  rotating signed tokens — reverse-engineering it is fragile.

This project documents a working hybrid that keeps things simple:

| Stage | Tool | Why |
|---|---|---|
| Cloudflare bypass | [`nodriver`](https://github.com/ultrafunkamsterdam/nodriver) + real Chrome | Pure CDP control of a real binary; clears Turnstile in 5–10 s. |
| URL discovery | nodriver (browser navigation) | Listing pages need JS. Sitemap.xml gives navigation URLs to crawl. |
| Detail fetch | [`curl_cffi`](https://github.com/lexiforest/curl_cffi) (`impersonate="chrome120"`) | Mimics Chrome TLS handshake — pairs with the `cf_clearance` cookie to pass CF without launching a browser per request. |

The result: **5 089 products in ~2 hours** at 3 s polite rate, on a single
laptop, with zero failed requests and full resume support if interrupted.

---

## How it works

```
┌─────────────┐   ┌───────────────┐   ┌──────────────┐   ┌──────────┐
│ 1. CF bypass│──▶│ 2. Discover    │──▶│ 3. Scrape    │──▶│ 4. Output│
│  (nodriver) │   │  (sitemap +    │   │  (curl_cffi  │   │  (CSV +  │
│  → cookies  │   │   nodriver     │   │   + cookies) │   │   state) │
│  + UA       │   │   for listings)│   │              │   │          │
└─────────────┘   └───────────────┘   └──────────────┘   └──────────┘
```

1. **Bypass** — open the homepage in Chrome via nodriver, wait for the
   Turnstile challenge to clear, extract `cf_clearance` cookie + matching
   User-Agent.
2. **Discover** — fetch `/sitemap.xml`, parse listing-page URLs
   (`/category/`, `/subcategory/`, `/category_brand/`), then visit each
   listing in nodriver, click "Lihat Selengkapnya" until exhausted, and
   collect every `/detail/` link. Output: `urls.txt` (~5 000 unique URLs).
3. **Scrape** — for each URL, fetch via `curl_cffi` with the cookies + UA,
   parse the embedded product JSON (`PPRCZ`, `PDISP`, `PIMGZ`) plus the
   breadcrumb. Append to `output/products.csv`. Mark done in `state.json`.
4. **Output** — incremental writes; a crash/Ctrl-C never loses progress.

Notable engineering details:

- Chrome window is **launched offscreen** (`--window-position=-2400,-2400`)
  by default so it's not visually intrusive. Pure headless gets blocked by
  Cloudflare; offscreen has the same UX with a visible (to CF) GPU pipeline.
- nodriver has [a deadlock bug](https://github.com/ultrafunkamsterdam/nodriver/issues/)
  where `Cookie.from_json` fails on Chrome's missing `sameParty` field;
  we monkey-patch it.
- Detail pages embed a server-side JSON blob (`<div class="d-none context-json">`)
  with prices/stock/images. Targeting that is far more robust than DOM
  selectors that get rewritten by AJAX after page load.

---

## Setup

**Requirements:** Python 3.11+, Google Chrome (or Chromium/Brave) installed.

```bash
git clone https://github.com/rizkirmdhnnn/enterkomputer-scraper.git
cd enterkomputer-scraper
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

That's it. No `playwright install`, no separate browser download — the
scraper drives your local Chrome.

### Custom Chrome path

The scraper auto-detects Chrome in standard locations on macOS, Linux, and
Windows. If yours is elsewhere, copy `.env.example` to `.env` and set:

```bash
cp .env.example .env
# then edit .env, e.g.:
EK_CHROME_PATH=/snap/bin/chromium
```

`.env` is git-ignored. See [`.env.example`](.env.example) for every knob
(rate limits, offscreen window position, base URL, etc.).

---

## Usage

```bash
# Full pipeline (default rate: 3s, polite, browser hidden)
python -m src.main --stage all

# Only solve the Cloudflare challenge (smoke test)
python -m src.main --stage bypass

# Only discover URLs (writes urls.txt)
python -m src.main --stage discover

# Only scrape (assumes urls.txt exists from a prior discover run)
python -m src.main --stage scrape

# Smoke test on first 5 URLs
python -m src.main --stage scrape --limit 5

# Faster (1 second between requests). Only with permission/own site.
python -m src.main --stage scrape --rate 1.0

# Show the Chrome window during the run (debug)
EK_SHOW_BROWSER=1 python -m src.main --stage all
```

### Resumability

The pipeline is fully resumable:

- `urls.txt` exists → discovery is skipped (delete it to re-run).
- `state.json` tracks completed URLs → re-running skips them and continues
  from where you left off.

If a run is killed mid-way, just rerun the same command. No data loss.

---

## Configuration

Every knob has a sensible default. Override via environment variables (or
a `.env` file):

| Variable | Default | What it does |
|---|---|---|
| `EK_CHROME_PATH` | auto-detect | Path to Chrome/Chromium/Brave binary |
| `EK_SHOW_BROWSER` | `0` (hidden offscreen) | `1` to show the browser window |
| `EK_OFFSCREEN_POSITION` | `-2400,-2400` | `x,y` for hidden mode |
| `EK_WINDOW_SIZE` | `1280,800` | `w,h` of the Chrome window |
| `EK_CF_WAIT_SECS` | `30` | Max seconds for the CF challenge to clear |
| `EK_BASE_URL` | `https://www.enterkomputer.com/` | Site homepage |
| `EK_SITEMAP_URL` | (auto) | Sitemap location |
| `EK_DISCOVER_DELAY` | `3.0` | Seconds between listing-page visits |
| `EK_LOAD_MORE_MAX_CLICKS` | `50` | Safety cap on "Lihat Selengkapnya" clicks |
| `EK_LOAD_MORE_WAIT` | `1.5` | Seconds to wait after each loadMore click |
| `EK_SCRAPE_RATE` | `3.0` | Seconds between detail-page requests |
| `EK_IMPERSONATE` | `chrome120` | curl_cffi browser profile |

CLI flags always override env vars.

---

## Output

| File | Contents |
|---|---|
| `output/products.csv` | One row per product (11 columns, see below) |
| `state.json` | URLs that have been successfully scraped (resume marker) |
| `urls.txt` | Discovered product detail URLs (one per line) |
| `failed_urls.txt` | URLs that failed after retries — replay with `--stage scrape` |
| `logs/scraper.log` | Run log (INFO + WARN + ERROR) |

### CSV schema

| Column | Type | Notes |
|---|---|---|
| `sku` | string | Product ID from the URL or page |
| `name` | string | Product title |
| `category` | string | Top-level category from breadcrumb/embedded JSON |
| `subcategory` | string | Second-level category if present |
| `price_idr` | integer | Price in IDR (cleaned of separators) |
| `stock_status` | string | `in_stock` / `out_of_stock` / `preorder` / raw label |
| `description` | string | Plain-text description (falls back to `og:description`) |
| `specifications` | string | JSON-encoded spec table (may be empty) |
| `image_url` | string | Absolute URL of the primary product image |
| `product_url` | string | Canonical detail-page URL |
| `scraped_at` | string | ISO 8601 UTC timestamp |

---

## Development

```bash
# Run all tests (no network needed — uses captured HTML fixtures)
.venv/bin/pytest tests/ -v
```

The fixture-based parser tests live in `tests/test_parsers.py`. To regenerate
fixtures against a fresh page snapshot, see `scripts/capture_fixtures.py`.

### Project layout

```
src/
├── config.py        # env-driven configuration (single source of truth)
├── cf_bypass.py     # Cloudflare Turnstile bypass via nodriver
├── discover.py      # Sitemap + listing-page URL collection
├── scrape.py        # Detail-page fetching + CSV row writing
├── parsers.py       # Pure HTML→dict parsers (HTML in, data out)
├── csv_writer.py    # Incremental CSV writes (single-shot header)
├── state.py         # Resume-state JSON helpers
└── main.py          # CLI entry point
tests/               # Unit tests + HTML fixtures
scripts/             # Helper scripts (e.g. fixture capture)
```

---

## Adapting to other sites

This project's architecture (nodriver + curl_cffi + sitemap-driven discovery)
is reusable for many Cloudflare-protected catalog sites. To adapt:

1. Update `EK_BASE_URL` and `EK_SITEMAP_URL` (in `.env` or `src/config.py`).
2. Adjust the `LISTING_PATH_PATTERNS` and `DETAIL_PATH_PATTERN` in
   `src/discover.py` to match the new site's URL scheme.
3. Rewrite the CSS selectors in `src/parsers.py` to match the new HTML
   layout (capture fixtures with `scripts/capture_fixtures.py` first).

You'll likely keep `cf_bypass.py`, `state.py`, `csv_writer.py`, and `main.py`
nearly verbatim.

---

## Known limitations

- Only macOS/Linux/Windows desktops with a graphical session — won't work
  on a headless Linux server unless you run it under Xvfb (the offscreen
  trick still needs a display server to lie to).
- Per-product **descriptions** and **specifications tables** load via AJAX
  and aren't in the static HTML. The scraper falls back to `og:description`
  for those. Hitting the AJAX endpoint per product would be more thorough
  but requires reverse-engineering rotating tokens.
- nodriver prints a benign `RuntimeError: Event loop is closed` warning on
  shutdown (Python 3.13 / asyncio cleanup interaction). Cosmetic only.

---

## License

MIT. See [LICENSE](LICENSE) if present, otherwise treat as MIT.

This project is provided as-is, for educational and research purposes. The
authors take no responsibility for misuse. Respect target-site `robots.txt`
and ToS; obtain permission before commercial scraping.
