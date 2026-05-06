# Enterkomputer Scraper

Scrapes the product catalog from enterkomputer.com into `output/products.csv`.

## Disclaimer

The site's `robots.txt` disallows non-Googlebot scraping site-wide. This
scraper runs in **polite mode** by default (3 second delays, single thread,
single-session cookie, sitemap-driven URL discovery). Use it only for
personal/research purposes and at your own risk. Do not republish the
scraped data or use it commercially without permission from enterkomputer.com.

## How it works

The site is behind Cloudflare Turnstile (`cf-mitigated: challenge`). Plain
HTTP requests get a 403, and even Playwright is detected. The scraper uses
a hybrid stack:

- **`nodriver`** + real Chrome (CDP) — solves the Turnstile challenge once
  per run and extracts the `cf_clearance` cookie + matching User-Agent.
  Also drives JS-rendered listing pages during URL discovery.
- **`curl_cffi`** with `impersonate="chrome120"` — Chrome TLS fingerprint
  mimicry. Combined with the `cf_clearance` cookie, plain HTTP requests
  pass Cloudflare. Used for fast detail-page fetching.

Pipeline:

1. **bypass** — solve CF, cache cookies + UA in memory.
2. **discover** — fetch `sitemap.xml` (one request), parse for listing URLs
   (`/category/`, `/subcategory/`, `/category_brand/`), navigate each
   listing page in nodriver, click "Lihat Selengkapnya" until exhausted,
   collect every `/detail/` link. Output: `urls.txt`.
3. **scrape** — for each URL in `urls.txt`, fetch via curl_cffi, parse the
   embedded product JSON (`PPRCZ`, `PDISP`, `PIMGZ`) plus the breadcrumb
   and spec sections, append a row to `output/products.csv`. Records each
   completed URL in `state.json` for resume support.

## Setup

```bash
# Requires Python 3.11+ and Google Chrome at /Applications/Google Chrome.app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`nodriver` uses your local Chrome installation — no additional browser
download needed (unlike Playwright).

## Run

```bash
# Full pipeline (discover + scrape) at the default 3s polite rate
python -m src.main --stage all

# Just discovery (writes urls.txt)
python -m src.main --stage discover

# Just scraping (assumes urls.txt exists)
python -m src.main --stage scrape

# Smoke test on the first 5 URLs
python -m src.main --stage scrape --limit 5

# Faster (NOT polite — only with site owner's permission)
python -m src.main --rate 1.0
```

Resumable: re-running picks up where it left off via `state.json` and
the existing `urls.txt`. Delete `urls.txt` to re-run discovery.

## Output

| File | Contents |
|---|---|
| `output/products.csv` | One row per product, 11 columns |
| `state.json` | URLs that have been successfully scraped (for resume) |
| `urls.txt` | Discovered product detail URLs (one per line) |
| `failed_urls.txt` | URLs where scrape failed after retries |
| `logs/scraper.log` | Run log |

CSV columns: `sku`, `name`, `category`, `subcategory`, `price_idr`,
`stock_status`, `description`, `specifications` (JSON string),
`image_url`, `product_url`, `scraped_at` (ISO 8601 UTC).

## Tests

```bash
.venv/bin/pytest tests/ -v
```

Parser tests run against captured HTML fixtures in `tests/fixtures/`.
The `cf_bypass`, `discover`, and `scrape` modules are integration-tested
via the `--limit` smoke flow above.

## Known limitations

- `CHROME_PATH` is hardcoded to macOS in `src/cf_bypass.py` and
  `src/discover.py`. Adjust for Linux/Windows.
- A nodriver/asyncio cleanup warning (`Event loop is closed`) prints at
  the end of each run. Cosmetic; does not affect correctness.
- The `description` field falls back to the site-level `og:description`
  meta tag (per-product descriptions load via AJAX after page load and
  are not present in the initial HTML).
- The `specifications` field is empty for products whose spec table is
  AJAX-loaded.
