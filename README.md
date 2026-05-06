# Enterkomputer Scraper

Scrapes the full product catalog from enterkomputer.com into `output/products.csv`.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
python -m src.main             # full pipeline (bypass + discover + scrape)
python -m src.main --stage discover
python -m src.main --stage scrape --rate 1.5
```

Resumable: re-running picks up where it left off via `state.json`.
