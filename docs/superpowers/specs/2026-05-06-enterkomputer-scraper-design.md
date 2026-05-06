# Enterkomputer.com Scraper — Design

**Date:** 2026-05-06
**Status:** Draft, awaiting review

## Goal

Scrape the full product catalog from `https://www.enterkomputer.com` (an Indonesian PC parts e-commerce site) into a single CSV file. Site is protected by Cloudflare challenge (`cf-mitigated: challenge`), so the scraper must handle the bypass while remaining polite.

## Scope

**In scope:**
- All product categories listed in the site's main navigation
- Full per-product field set (see Data Model)
- One-shot run with resume capability if interrupted
- CSV output

**Out of scope:**
- Recurring / scheduled runs (can be added later by re-running the script)
- Price-history tracking
- Stock-change notifications
- Image downloading (image URLs are captured, but binaries are not fetched)
- Multi-format output (CSV only)

## Data Model

Each row in `products.csv` represents one product:

| Field | Type | Notes |
|---|---|---|
| `sku` | string | Product code from the site |
| `name` | string | Product name |
| `category` | string | Top-level category (breadcrumb leaf or parent) |
| `subcategory` | string | If breadcrumb has multiple levels; empty otherwise |
| `price_idr` | integer | Price in IDR, parsed from text (commas/dots stripped) |
| `stock_status` | string | "in_stock" / "out_of_stock" / "preorder" / raw label if other |
| `description` | string | Plain-text product description |
| `specifications` | string | JSON-encoded `{"key": "value"}` spec table |
| `image_url` | string | Primary product image (absolute URL) |
| `product_url` | string | Canonical absolute URL of the product page |
| `scraped_at` | ISO 8601 string | UTC timestamp when this row was captured |

Field selectors will be finalized empirically after first inspection of the live HTML; see Implementation Notes.

## Architecture

Four-stage pipeline:

```
┌──────────────┐   ┌────────────┐   ┌──────────────┐   ┌─────────┐
│ 1. CF Bypass │──▶│ 2. Discover │──▶│ 3. Scrape    │──▶│ 4. Output│
│  (Playwright)│   │ (categories │   │  (detail     │   │  (CSV +  │
│              │   │  + listing) │   │   pages)     │   │   state) │
└──────────────┘   └────────────┘   └──────────────┘   └─────────┘
       │                  │                 │
       │                  ▼                 ▼
       │           urls.txt          state.json
       │           (URL queue)       (resume marker)
       └──────────cookie+UA shared in memory ─────────┘
```

### Stage 1 — CF Bypass (`cf_bypass.py`)
- Launch headless Chromium via Playwright.
- Navigate to `https://www.enterkomputer.com/`.
- Wait for the Cloudflare challenge to resolve (poll for absence of challenge markers, max 30 s).
- Extract `cf_clearance` cookie (and any other CF cookies set on the response) plus the exact `User-Agent` string used by the browser.
- Return `(cookies_dict, user_agent_str)`.

This function is called once at startup, and again on demand whenever a request returns 403 mid-run (cookie expired).

### Stage 2 — Discovery (`discover.py`)
- Using `requests` with the bypass cookies/UA, fetch the homepage.
- Parse main-navigation links to enumerate category URLs.
- For each category URL, paginate (follow "next page" links or `?page=N` until no more results) and collect product detail URLs.
- Write all unique product URLs to `urls.txt`.

If `urls.txt` already exists from a previous run, this stage is skipped (resume).

### Stage 3 — Detail Scraping (`scrape.py`)
- Read `urls.txt`. Filter out URLs already present in `state.json` (resume).
- For each remaining URL:
  - GET via `requests` with cookies + UA.
  - Parse the HTML with BeautifulSoup (`lxml` parser).
  - Extract the fields listed in the Data Model.
  - Append the row to `products.csv` (open in append mode).
  - Append the URL to `state.json`.
  - Sleep ~1 second (configurable rate limit).
- Retry up to 3 times with exponential backoff (1s, 2s, 4s) on transient errors.
- On 403: re-run Stage 1 to refresh cookies, then retry the failed URL.

### Stage 4 — Output
- `output/products.csv` — final result, written incrementally so a crash never loses already-scraped rows. CSV header is written once when the file is first created; subsequent rows are appended without re-writing the header (file existence + non-empty check at startup).
- `state.json` — `{"completed_urls": ["..."], "last_updated": "..."}`.
- `logs/scraper.log` — INFO/WARNING/ERROR log of the run.

## File Layout

```
enterkomputer.com/
├── docs/superpowers/specs/2026-05-06-enterkomputer-scraper-design.md
├── src/
│   ├── cf_bypass.py
│   ├── discover.py
│   ├── scrape.py
│   ├── parsers.py        # field-extraction helpers (one per field group)
│   └── main.py           # CLI entry: orchestrates the four stages
├── output/
│   └── products.csv      # generated
├── state.json            # generated (resume state)
├── logs/
│   └── scraper.log       # generated
├── urls.txt              # generated (URL queue)
├── requirements.txt
└── README.md             # how to install + run
```

## Tech Stack

- Python 3.11+
- `playwright` (Chromium) — Cloudflare bypass only
- `requests` — bulk HTTP
- `beautifulsoup4` + `lxml` — HTML parsing
- `tenacity` — retry with exponential backoff
- stdlib `csv`, `json`, `logging`, `argparse`

## Configuration

CLI flags on `main.py`:

| Flag | Default | Purpose |
|---|---|---|
| `--rate` | `1.0` | Seconds between requests |
| `--concurrency` | `1` | Parallel workers (kept at 1 by default to stay polite) |
| `--output` | `output/products.csv` | Output CSV path |
| `--state` | `state.json` | State file path |
| `--resume / --no-resume` | `--resume` | Whether to skip completed URLs |
| `--stage` | `all` | One of `bypass`, `discover`, `scrape`, `all` |

## Politeness & Compliance

- Default rate: 1 request/second, single-threaded.
- Honor `robots.txt` (check at startup; warn and allow user override).
- Identify the scraper via a custom comment in `User-Agent`? — **No**, because CF requires the UA match the one used to solve the challenge. Identification is via reasonable rate limiting instead.
- This design is for personal/research use. Commercial republishing of the scraped data would require permission from enterkomputer.com.

## Error Handling

| Failure | Response |
|---|---|
| Cloudflare 403 mid-run | Re-run Stage 1 to refresh cookies; retry URL up to 3 times |
| Network timeout / 5xx | Exponential backoff (1s, 2s, 4s); after 3 fails, log and skip URL (recorded in `failed_urls.txt`) |
| HTML structure changed (selector miss) | Log a WARNING with URL + missing field; write row with empty value for that field; continue |
| Playwright fails to solve challenge in 30 s | Abort with clear error; user can re-run later |
| Disk full / write error | Crash; resume on next run picks up where state.json left off |

## Testing

- **Unit tests** (`pytest`) for `parsers.py`: feed saved HTML fixtures (3-5 real product pages saved to `tests/fixtures/`) and assert each field is extracted correctly.
- **Smoke test**: `main.py --stage scrape --limit 5` runs the full pipeline against the first 5 URLs and verifies CSV output schema.
- No mocked HTTP — fixtures are real saved HTML. CF bypass is exercised manually during smoke test.

## Open Questions

None blocking — selectors will be finalized during implementation by inspecting live pages.

## Risks

1. **Cloudflare upgrades protection** — could break Stage 1. Mitigation: keep Playwright stealth options in mind; document fallback to `playwright-stealth` plugin if needed.
2. **HTML structure changes mid-scrape** — parser breaks for some pages. Mitigation: per-field WARNING + continue, plus visible failed-URL list at end.
3. **IP ban from CF for aggressive scraping** — Mitigation: 1 req/s default, no concurrency by default.
4. **Site has very large catalog** (estimate unknown — likely thousands of SKUs) — at 1 req/s a 5k catalog takes ~90 minutes. Acceptable for a one-shot run.
