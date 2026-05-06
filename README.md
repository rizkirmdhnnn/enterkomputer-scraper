# Enterkomputer Scraper

Scraper polite dan resumable untuk katalog produk [enterkomputer.com](https://www.enterkomputer.com/).
Pakai **`nodriver`** untuk bypass Cloudflare Turnstile dan **`curl_cffi`**
(Chrome TLS fingerprint mimicry) buat fetch detail produk dengan cepat.
Output berupa satu file CSV berisi info produk lengkap.

> ⚠️ **Disclaimer.** `robots.txt` situs ini melarang scraping non-Googlebot
> (`User-agent: * / Disallow: /`). Project ini dipublikasikan **untuk tujuan
> edukasi dan riset saja**. Pakai di situs milik sendiri, target test, atau
> dengan izin eksplisit dari pemilik situs. Default-nya jalan polite mode
> single-thread (3 detik antar request). Jangan dipakai untuk republish data
> secara komersial.

---

## Kenapa project ini ada

Banyak resep scraper publik nggak jalan lagi melawan stack Cloudflare modern:

- `requests` biasa → 403 (TLS fingerprint mismatch).
- `Playwright` (bahkan dengan stealth plugin) → ke-detect Turnstile.
- Pure headless Chrome → juga ke-detect.
- Listing page situs target render produk via internal JSON API dengan
  rotating signed token — reverse-engineering rapuh dan ribet.

Project ini mendokumentasikan kombinasi hybrid yang terbukti jalan dan tetap
sederhana:

| Tahap | Tool | Kenapa |
|---|---|---|
| Cloudflare bypass | [`nodriver`](https://github.com/ultrafunkamsterdam/nodriver) + Chrome asli | Kontrol penuh real Chrome via CDP; clear Turnstile dalam 5–10 detik. |
| URL discovery | nodriver (browser navigation) | Listing page butuh JS. Sitemap.xml jadi sumber URL kategori untuk di-crawl. |
| Detail fetch | [`curl_cffi`](https://github.com/lexiforest/curl_cffi) (`impersonate="chrome120"`) | Mimik TLS handshake Chrome — dipasangkan dengan cookie `cf_clearance` cukup buat lewat CF tanpa launch browser per request. |

Hasilnya: **5.089 produk dalam ±2 jam** di rate polite 3 detik, di laptop
biasa, dengan zero failed request dan resume support penuh kalau terinterupsi.

---

## Cara kerjanya

```
┌─────────────┐   ┌────────────────┐   ┌──────────────┐   ┌──────────┐
│ 1. CF bypass│──▶│ 2. Discover    │──▶│ 3. Scrape    │──▶│ 4. Output│
│  (nodriver) │   │  (sitemap +    │   │  (curl_cffi  │   │  (CSV +  │
│  → cookies  │   │   nodriver     │   │   + cookies) │   │   state) │
│  + UA       │   │   untuk listing│   │              │   │          │
└─────────────┘   └────────────────┘   └──────────────┘   └──────────┘
```

1. **Bypass** — buka homepage di Chrome lewat nodriver, tunggu challenge
   Turnstile clear, ekstrak cookie `cf_clearance` + User-Agent yang cocok.
2. **Discover** — fetch `/sitemap.xml`, parse URL listing
   (`/category/`, `/subcategory/`, `/category_brand/`), lalu buka tiap
   listing di nodriver, klik "Lihat Selengkapnya" sampai habis, kumpulkan
   semua link `/detail/`. Output: `urls.txt` (~5.000 URL unik).
3. **Scrape** — untuk tiap URL, fetch via `curl_cffi` dengan cookies + UA,
   parse JSON produk yang di-embed (`PPRCZ`, `PDISP`, `PIMGZ`) plus
   breadcrumb. Append ke `output/products.csv`. Mark done di `state.json`.
4. **Output** — incremental write; crash atau Ctrl-C nggak akan kehilangan
   progress.

Detail engineering yang menarik:

- Window Chrome **dibuka offscreen** (`--window-position=-2400,-2400`)
  secara default supaya nggak mengganggu visual. Pure headless di-block
  Cloudflare; offscreen UX-nya sama persis tapi GPU pipeline-nya tetap
  terlihat oleh CF.
- nodriver punya [bug deadlock](https://github.com/ultrafunkamsterdam/nodriver/issues/)
  di mana `Cookie.from_json` gagal karena Chrome nggak ngirim field
  `sameParty`; di-monkey-patch.
- Detail page meng-embed JSON server-side (`<div class="d-none context-json">`)
  berisi harga/stok/gambar. Target ini jauh lebih robust daripada DOM
  selector yang di-rewrite oleh AJAX setelah page load.

---

## Setup

**Persyaratan:** Python 3.11+, Google Chrome (atau Chromium/Brave) terinstall.

```bash
git clone https://github.com/rizkirmdhnnn/enterkomputer-scraper.git
cd enterkomputer-scraper
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Selesai. Nggak perlu `playwright install`, nggak perlu download browser
terpisah — scraper-nya pakai Chrome yang sudah ada di komputer kamu.

### Custom Chrome path

Scraper akan auto-detect Chrome di lokasi standar untuk macOS, Linux, dan
Windows. Kalau Chrome kamu di lokasi lain, copy `.env.example` ke `.env`
dan set:

```bash
cp .env.example .env
# lalu edit .env, contoh:
EK_CHROME_PATH=/snap/bin/chromium
```

`.env` sudah di-gitignore. Lihat [`.env.example`](.env.example) untuk semua
opsi config (rate limit, posisi offscreen window, base URL, dst).

---

## Cara pakai

```bash
# Pipeline lengkap (default rate: 3s, polite, browser tersembunyi)
python -m src.main --stage all

# Cuma solve Cloudflare challenge (smoke test)
python -m src.main --stage bypass

# Cuma discover URL (tulis ke urls.txt)
python -m src.main --stage discover

# Cuma scrape (asumsi urls.txt sudah ada dari discover sebelumnya)
python -m src.main --stage scrape

# Smoke test: scrape 5 URL pertama
python -m src.main --stage scrape --limit 5

# Lebih cepat (1 detik antar request). Hanya kalau ada izin / situs sendiri.
python -m src.main --stage scrape --rate 1.0

# Tampilkan window Chrome saat run (untuk debug)
EK_SHOW_BROWSER=1 python -m src.main --stage all
```

### Resumable

Pipeline-nya fully resumable:

- Kalau `urls.txt` sudah ada → discovery di-skip (hapus filenya kalau mau
  ulang dari awal).
- `state.json` mencatat URL yang sudah selesai → re-run akan skip yang
  sudah selesai dan lanjut dari tempat berhenti.

Kalau run di-kill di tengah, tinggal jalankan command yang sama lagi. Nggak
ada data hilang.

---

## Konfigurasi

Setiap knob punya default yang masuk akal. Override via environment variable
(atau file `.env`):

| Variabel | Default | Fungsi |
|---|---|---|
| `EK_CHROME_PATH` | auto-detect | Path ke binary Chrome/Chromium/Brave |
| `EK_SHOW_BROWSER` | `0` (offscreen) | Set `1` untuk munculin window Chrome |
| `EK_OFFSCREEN_POSITION` | `-2400,-2400` | Koordinat `x,y` saat hidden mode |
| `EK_WINDOW_SIZE` | `1280,800` | Ukuran `w,h` window Chrome |
| `EK_CF_WAIT_SECS` | `30` | Maksimal detik tunggu CF challenge clear |
| `EK_BASE_URL` | `https://www.enterkomputer.com/` | Homepage situs |
| `EK_SITEMAP_URL` | (auto) | Lokasi sitemap |
| `EK_DISCOVER_DELAY` | `3.0` | Detik antar kunjungan listing page |
| `EK_LOAD_MORE_MAX_CLICKS` | `50` | Safety cap untuk klik "Lihat Selengkapnya" |
| `EK_LOAD_MORE_WAIT` | `1.5` | Detik tunggu setelah tiap klik loadMore |
| `EK_SCRAPE_RATE` | `3.0` | Detik antar request ke detail page |
| `EK_IMPERSONATE` | `chrome120` | Profile browser curl_cffi |

CLI flag selalu menang dari env var.

---

## Output

| File | Isi |
|---|---|
| `output/products.csv` | Satu row per produk (11 kolom, lihat di bawah) |
| `state.json` | URL yang sudah berhasil di-scrape (untuk resume) |
| `urls.txt` | URL detail produk hasil discovery (satu per baris) |
| `failed_urls.txt` | URL yang gagal setelah retry — bisa di-replay dengan `--stage scrape` |
| `logs/scraper.log` | Log run (INFO + WARN + ERROR) |

### Schema CSV

| Kolom | Tipe | Catatan |
|---|---|---|
| `sku` | string | ID produk dari URL atau halaman |
| `name` | string | Nama produk |
| `category` | string | Kategori utama dari breadcrumb / embedded JSON |
| `subcategory` | string | Sub-kategori kalau ada |
| `price_idr` | integer | Harga IDR (sudah dibersihkan dari pemisah) |
| `stock_status` | string | `in_stock` / `out_of_stock` / `preorder` / label asli |
| `description` | string | Deskripsi plain-text (fallback ke `og:description`) |
| `specifications` | string | Spec table dalam JSON (bisa kosong) |
| `image_url` | string | URL absolut gambar utama produk |
| `product_url` | string | URL kanonik halaman detail |
| `scraped_at` | string | Timestamp ISO 8601 UTC |

---

## Development

```bash
# Jalankan semua test (nggak butuh network — pakai HTML fixture)
.venv/bin/pytest tests/ -v
```

Test parser berbasis fixture ada di `tests/test_parsers.py`. Untuk regenerate
fixture dari snapshot halaman terbaru, lihat `scripts/capture_fixtures.py`.

### Struktur project

```
src/
├── config.py        # konfigurasi env-driven (single source of truth)
├── cf_bypass.py     # bypass Cloudflare Turnstile via nodriver
├── discover.py      # kumpulin URL dari sitemap + listing page
├── scrape.py        # fetch detail page + tulis row CSV
├── parsers.py       # parser HTML→dict murni (HTML in, data out)
├── csv_writer.py    # incremental CSV write (header sekali tulis)
├── state.py         # helper resume-state JSON
└── main.py          # entry point CLI
tests/               # unit test + HTML fixture
scripts/             # script helper (mis. capture fixture)
```

---

## Adaptasi ke situs lain

Arsitektur project ini (nodriver + curl_cffi + sitemap-driven discovery)
bisa di-reuse untuk banyak situs katalog yang dilindungi Cloudflare. Cara
adaptasi:

1. Update `EK_BASE_URL` dan `EK_SITEMAP_URL` (di `.env` atau `src/config.py`).
2. Sesuaikan `LISTING_PATH_PATTERNS` dan `DETAIL_PATH_PATTERN` di
   `src/discover.py` agar match dengan skema URL situs baru.
3. Rewrite CSS selector di `src/parsers.py` agar match dengan layout HTML
   situs baru (capture fixture dulu pakai `scripts/capture_fixtures.py`).

`cf_bypass.py`, `state.py`, `csv_writer.py`, dan `main.py` kemungkinan besar
nggak perlu diubah.

---

## Limitasi yang diketahui

- Cuma jalan di desktop macOS/Linux/Windows dengan graphical session — nggak
  jalan di Linux server headless kecuali pakai Xvfb (trik offscreen tetap
  butuh display server untuk dibohongi).
- **Deskripsi** dan **tabel spesifikasi** per produk di-load via AJAX dan
  nggak ada di HTML statis. Scraper fallback ke `og:description` untuk
  field tersebut. Hit endpoint AJAX per produk akan lebih lengkap tapi
  butuh reverse-engineering rotating token.
- nodriver mengeluarkan warning `RuntimeError: Event loop is closed` saat
  shutdown (interaksi cleanup Python 3.13 / asyncio). Cosmetic doang.

---

## Lisensi

MIT. Lihat [LICENSE](LICENSE).

Project ini disediakan apa adanya, untuk tujuan edukasi dan riset.
Authors tidak bertanggung jawab atas penyalahgunaan. Hormati `robots.txt`
dan ToS situs target; minta izin sebelum scraping komersial.
