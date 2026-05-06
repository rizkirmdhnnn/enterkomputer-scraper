# Enterkomputer Scraper

Tool untuk ngambil katalog produk dari [enterkomputer.com](https://www.enterkomputer.com/)
ke file CSV. Bisa lewat proteksi Cloudflare, jalan dengan jeda antar request
biar nggak ngebebanin server, dan kalau di tengah jalan terputus bisa
dilanjut dari tempat berhenti.

> ⚠️ **Catatan penting.** `robots.txt` situs ini tidak mengizinkan scraping
> selain Googlebot. Project ini dibikin **buat belajar dan eksperimen
> teknis**. Pakai cuma di situs sendiri, server test, atau dengan izin dari
> pemilik situs. Jangan dipakai buat republish data secara komersial. Default
> setting-nya kasih jeda 3 detik antar request supaya nggak agresif ke server.

---

## Cara kerja singkat

```
┌─────────────┐   ┌────────────────┐   ┌──────────────┐   ┌──────────┐
│ 1. Lewat CF │──▶│ 2. Kumpulin    │──▶│ 3. Ambil     │──▶│ 4. Tulis │
│  (nodriver) │   │    URL produk  │   │    detail    │   │    CSV   │
│  → cookie   │   │  (sitemap +    │   │  (curl_cffi  │   │          │
│  + UA       │   │   nodriver)    │   │   + cookie)  │   │          │
└─────────────┘   └────────────────┘   └──────────────┘   └──────────┘
```

1. **Lewat Cloudflare** — buka homepage di Chrome lewat nodriver, tunggu
   challenge selesai, ambil cookie `cf_clearance` + User-Agent yang dipakai.
2. **Kumpulin URL** — fetch `/sitemap.xml`, ambil URL kategori
   (`/category/`, `/subcategory/`, `/category_brand/`), lalu kunjungi tiap
   kategori di nodriver, klik "Lihat Selengkapnya" sampai habis, kumpulin
   semua link `/detail/`. Hasil: `urls.txt` (~5.000 URL).
3. **Ambil detail** — buat tiap URL, fetch via `curl_cffi` dengan cookie +
   UA tadi. Parse JSON produk yang sudah di-embed di HTML (field `PPRCZ`,
   `PDISP`, `PIMGZ`) plus breadcrumb. Tulis ke `output/products.csv`.
4. **Tulis CSV** — bertahap; kalau crash atau Ctrl-C, progress nggak hilang.

Beberapa catatan teknis:

- Window Chrome dibuka **di luar layar** (`--window-position=-2400,-2400`)
  jadi nggak keliatan. Headless murni ke-block Cloudflare; trik ini bikin
  user nggak liat browser tapi Chrome-nya tetap "asli" buat CF.
- `nodriver` ada bug kecil dimana parsing cookie nge-stuck karena Chrome
  terbaru nggak ngirim field `sameParty`. Di-patch otomatis.
- Detail page sudah masukin JSON produk di HTML (`<div class="d-none context-json">`)
  berisi harga/stok/gambar. Jauh lebih reliable daripada CSS selector yang
  bisa berubah karena AJAX.

---

## Setup

**Butuh:** Python 3.11+, Google Chrome (atau Chromium/Brave) terinstall.

```bash
git clone https://github.com/rizkirmdhnnn/enterkomputer-scraper.git
cd enterkomputer-scraper
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Selesai. Nggak perlu `playwright install`, nggak perlu download browser
terpisah — pakai Chrome yang sudah ada di komputer kamu.

### Custom Chrome path

Scraper otomatis nyari Chrome di lokasi standar (macOS/Linux/Windows). Kalau
Chrome kamu di lokasi lain, copy `.env.example` jadi `.env`:

```bash
cp .env.example .env
# edit .env, contoh:
EK_CHROME_PATH=/snap/bin/chromium
```

`.env` udah di-gitignore. Lihat [`.env.example`](.env.example) untuk semua
opsi yang bisa diatur.

---

## Cara pakai

```bash
# Pipeline lengkap (default jeda 3 detik, browser disembunyikan)
python -m src.main --stage all

# Cuma test apakah Cloudflare bisa lewat
python -m src.main --stage bypass

# Cuma kumpulin URL produk (tulis ke urls.txt)
python -m src.main --stage discover

# Cuma ambil detail produk (asumsi urls.txt udah ada)
python -m src.main --stage scrape

# Test cepat: ambil 5 produk pertama
python -m src.main --stage scrape --limit 5

# Lebih cepat (1 detik antar request) — pastikan kamu punya izin dulu
python -m src.main --stage scrape --rate 1.0

# Kalau mau lihat browser-nya saat run (buat debug)
EK_SHOW_BROWSER=1 python -m src.main --stage all
```

### Bisa dilanjut kalau terputus

Pipeline-nya bisa dilanjut:

- Kalau `urls.txt` udah ada → tahap discover di-skip (hapus filenya kalau
  mau ulang dari awal).
- `state.json` mencatat URL yang sudah berhasil → re-run akan skip yang
  sudah selesai.

Kalau run terhenti di tengah, tinggal jalanin command yang sama lagi. Data
yang udah masuk CSV tetap aman.

---

## Pengaturan

Semua setting punya nilai default. Override via environment variable atau
file `.env`:

| Variabel | Default | Fungsi |
|---|---|---|
| `EK_CHROME_PATH` | auto-detect | Path ke binary Chrome/Chromium/Brave |
| `EK_SHOW_BROWSER` | `0` (sembunyi) | Set `1` buat tampilin window Chrome |
| `EK_OFFSCREEN_POSITION` | `-2400,-2400` | Koordinat `x,y` saat browser disembunyiin |
| `EK_WINDOW_SIZE` | `1280,800` | Ukuran `w,h` window Chrome |
| `EK_CF_WAIT_SECS` | `30` | Maksimal detik nunggu Cloudflare selesai |
| `EK_BASE_URL` | `https://www.enterkomputer.com/` | Homepage situs |
| `EK_SITEMAP_URL` | (auto) | Lokasi sitemap |
| `EK_DISCOVER_DELAY` | `3.0` | Detik antar kunjungan listing page |
| `EK_LOAD_MORE_MAX_CLICKS` | `50` | Batas klik "Lihat Selengkapnya" |
| `EK_LOAD_MORE_WAIT` | `1.5` | Detik tunggu setelah tiap klik loadMore |
| `EK_SCRAPE_RATE` | `3.0` | Detik antar request ke detail page |
| `EK_IMPERSONATE` | `chrome120` | Profile browser buat curl_cffi |

Flag CLI selalu menang dari env var.

---

## File output

| File | Isi |
|---|---|
| `output/products.csv` | Satu baris per produk (11 kolom, lihat di bawah) |
| `state.json` | URL yang sudah berhasil di-ambil (buat lanjut) |
| `urls.txt` | Daftar URL detail produk hasil discovery |
| `failed_urls.txt` | URL yang gagal (bisa di-retry pakai `--stage scrape`) |
| `logs/scraper.log` | Log run (INFO + WARN + ERROR) |

### Schema CSV

| Kolom | Tipe | Catatan |
|---|---|---|
| `sku` | string | ID produk dari URL atau halaman |
| `name` | string | Nama produk |
| `category` | string | Kategori utama |
| `subcategory` | string | Sub-kategori (kalau ada) |
| `price_idr` | integer | Harga dalam IDR (sudah dibersihin) |
| `stock_status` | string | `in_stock` / `out_of_stock` / `preorder` |
| `description` | string | Deskripsi (fallback ke `og:description`) |
| `specifications` | string | Spec table dalam JSON (bisa kosong) |
| `image_url` | string | URL absolut gambar utama |
| `product_url` | string | URL halaman detail |
| `scraped_at` | string | Timestamp ISO 8601 UTC |

---

## Development

```bash
# Jalanin semua test (nggak butuh internet — pakai HTML fixture)
.venv/bin/pytest tests/ -v
```

### Struktur project

```
src/
├── config.py        # konfigurasi (semua setting di sini)
├── cf_bypass.py     # solver Cloudflare via nodriver
├── discover.py      # cari URL produk dari sitemap + listing page
├── scrape.py        # fetch detail page + tulis CSV
├── parsers.py       # parser HTML→dict (HTML masuk, data keluar)
├── csv_writer.py    # tulis CSV bertahap (header sekali)
├── state.py         # helper resume-state JSON
└── main.py          # CLI entry point
tests/               # unit test + HTML fixture
scripts/             # script helper
```

---

## Yang nggak bisa

- Cuma jalan di komputer dengan tampilan grafis (macOS/Linux/Windows desktop).
  Server Linux tanpa display nggak bisa kecuali pakai Xvfb — trik offscreen
  tetap butuh display server buat dibohongi.
- **Deskripsi panjang** dan **tabel spesifikasi detail** per produk
  di-load via AJAX dan nggak ada di HTML statis. Scraper fallback ke
  `og:description` buat field tersebut.
- nodriver ngeluarin warning `RuntimeError: Event loop is closed` saat
  shutdown. Cosmetic doang, hasil scrape tetap valid.

---

## Lisensi

MIT. Lihat [LICENSE](LICENSE).

Project ini disediakan apa adanya buat tujuan belajar dan riset. Authors
nggak bertanggung jawab atas penyalahgunaan. Hormati `robots.txt` dan ToS
situs target; minta izin dulu kalau mau scraping komersial.
