# RSS SietekMalut

Generator **link feed RSS (XML) gratis** yang hasilnya disimpan dan disajikan
oleh GitHub Pages, sehingga bisa dibuka dari mana saja kapan saja:

```
https://sietekmalut.github.io/feeds/<nama-feed>.xml    ← RSS 2.0 (pembaca RSS)
https://sietekmalut.github.io/feeds/<nama-feed>.json   ← JSON Feed 1.1 (scraping)
```

Tidak ada server sendiri, tidak ada database, tidak ada langganan. GitHub
Actions mengambil halaman sumber tiap **15 menit**, menyusun ulang isinya
menjadi RSS 2.0 + JSON Feed yang valid, lalu meng-commit hasilnya ke repositori
ini. Begitu file baru masuk, `push` langsung memicu workflow sehingga feed baru
tersedia dalam ~1 menit, bukan menunggu jadwal berikutnya.

- Katalog feed: <https://sietekmalut.github.io/>
- Impor semua feed sekaligus: <https://sietekmalut.github.io/feeds/all.opml>
- Daftar mesin: <https://sietekmalut.github.io/feeds/index.json>

---

## Cara pakai

1. Buka katalog, pilih feed, tekan **Salin**.
2. Tempel link `.xml` ke pembaca RSS: Feedly, Inoreader, NetNewsWire, FreshRSS,
   Thunderbird, atau widget RSS di dashboard.
3. Selesai. Link tidak berubah; isinya yang diperbarui otomatis.

Ingin situs lain? Buka bagian **Buat feed baru** di halaman utama, isi alamat
halamannya, lalu tekan tombol GitHub yang muncul dan **Commit changes**.

---

## Memakai feed untuk scraping

Setiap feed punya dua bentuk dengan isi yang sama. Untuk scraping, pakai
`.json` — tidak perlu parser XML, dan `Content-Type`-nya sudah benar.

| Kebutuhan | Pakai | Alasan |
|---|---|---|
| Pembaca RSS / widget | `.xml` | RSS 2.0, kompatibel paling luas |
| Scraping / pipeline data | `.json` | JSON Feed 1.1, langsung jadi objek |
| Ambil teks lengkap artikel | buka `url` tiap item | feed berisi tautan + ringkasan |

```python
import json, urllib.request

data = json.load(urllib.request.urlopen(
    "https://sietekmalut.github.io/feeds/kompas.json"))
for item in data["items"]:
    print(item["date_published"], item["title"], item["url"])
```

```javascript
const feed = await fetch(
  "https://sietekmalut.github.io/feeds/kompas.json"
).then((r) => r.json());

feed.items.forEach((item) => {
  console.log(item.date_published, item.title, item.url);
});
```

Yang sudah dijamin oleh generator, supaya hasil scraping bersih:

- Tautan item sudah **kanonik**: parameter pelacak (`utm_*`, `fbclid`, `?ref=`)
  dibuang dan `&amp;` di dalam URL diperbaiki.
- `date_published` selalu **ISO 8601 UTC**; cap waktu yang salah zona (umum di
  media Indonesia yang menulis jam lokal sebagai GMT) dikoreksi otomatis.
- Item tanpa tanggal wajar, tautan iklan/subdomain promotor, dan tautan CTA
  seperti “baca juga” disaring.
- Teks dibersihkan dari entitas ganda dan karakter kontrol, jadi tidak ada
  `&amp;amp;` atau XML rusak di dalam JSON.
- **CORS `Access-Control-Allow-Origin: *`** dari GitHub Pages — bisa di-`fetch`
  langsung dari browser tanpa proxy.

Contoh skrip siap pakai yang membaca feed lalu mengambil teks utama setiap
artikel:

```powershell
python examples/scrape_from_feed.py https://sietekmalut.github.io/feeds/kompas.xml
python examples/scrape_from_feed.py https://sietekmalut.github.io/feeds/detik.json --fetch --limit 3
python examples/scrape_from_feed.py https://sietekmalut.github.io/feeds/all.opml --all
```

Contoh keluaran:

```
# Malutpost  (21 item, format rss)
 1. 2026-11-16 03:25 Foto Wapres Gibran Mulai Dihapus di Jakarta
    https://malutpost.id/berita/foto-wapres-gibran-mulai-dihapus-di-jakarta/
    14 paragraf · Malutpost.id – Pemandangan berbeda terlihat di berbagai kantor…
```

Tetap hormati `robots.txt` dan ketentuan situs sumber saat membuka halaman
artikel.

---

## Cara kerja

```
┌──────────────────────────┐
│ jadwal GitHub Actions    │  tiap 15 menit / push / Run workflow
│ .github/workflows/*.yml  │
└────────────┬─────────────┘
             │ python generator/generate.py --workers 8
             ▼
┌──────────────────────────┐
│ generator/               │  fetch → deteksi feed asli → ekstrak HTML
│  net.py  dom.py          │  → normalisasi item → RSS 2.0 + JSON Feed
│  extract.py render.py    │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ feeds/<slug>.xml         │  di-commit hanya bila isinya berubah
│ feeds/<slug>.json        │
│ feeds/index.json         │
│ feeds/all.opml           │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ GitHub Pages (statis)    │  https://sietekmalut.github.io/feeds/…
└──────────────────────────┘
```

Karena Pages hanya menyajikan file statis, "membuat feed" berarti menjalankan
generator di dalam GitHub Actions — bukan memanggil server saat ada
permintaan. Konsekuensinya:

- Link **stabil dan permanen** (file sungguhan, bukan hasil render sesaat).
- Pembaruan terjadi tiap 15 menit, bukan real-time.
- Sumber harus terdaftar di `sources.json` (tidak bisa `?url=` sembarang).
- Untuk kecepatan, 10 sumber diproses paralel (8 worker) — satu putaran
  penuh ± 17 detik.

---

## Menambah feed

### 1. Lewat halaman web (paling mudah)

Buka <https://sietekmalut.github.io/#buat>, isi formulir, tekan
**Buka GitHub & publikasikan**, lalu **Commit changes**. File permintaan masuk
ke `requests/<slug>.json`, Actions memprosesnya, dan feed muncul di katalog
dalam 1–2 menit.

### 2. Lewat Actions (tanpa mengedit file)

Buka tab **Actions → Perbarui feed RSS → Run workflow**, isi `url` dan `name`.

### 3. Lewat `sources.json`

```json
{
  "slug": "kompas",
  "name": "Kompas.com",
  "url": "https://www.kompas.com/",
  "language": "id",
  "limit": 30,
  "mode": "auto",
  "enabled": true
}
```

| Field | Wajib | Keterangan |
|---|---|---|
| `slug` | tidak | Nama file XML. Default: dari `name`/`url`. |
| `name` | ya | Nama tampilan di katalog. |
| `url` | ya | Halaman beranda, kategori, atau URL feed. |
| `mode` | tidak | `auto` (default), `feed`, `html`. |
| `limit` | tidak | 1–100 item, default 30. |
| `language` | tidak | Kode bahasa, default `id`. |
| `include` | tidak | Regex; hanya URL artikel yang cocok. |
| `exclude` | tidak | Regex; buang URL yang cocok. |
| `title_exclude` | tidak | Regex untuk membuang judul tertentu. |
| `min_items` | tidak | Minimum item agar dianggap sukses, default 3. |
| `ttl` | tidak | Nilai `<ttl>` di RSS, default 30 menit. |
| `enabled` | tidak | `false` untuk menonaktifkan tanpa menghapus. |

Setelah mengubah file, jalankan workflow sekali atau tunggu jadwal berikutnya.

---

## Menjalankan di PC

Butuh Python 3.9+ (tanpa `pip install` apa pun).

```powershell
# perbarui semua feed ke folder feeds/
python generator/generate.py

# periksa saja, tanpa menulis file
python generator/generate.py --check

# satu sumber saja
python generator/generate.py --slug kompas

# tambah sumber lalu langsung buat feed-nya
python generator/generate.py --add https://contoh.com/berita --name "Contoh"

# proses file di folder requests/
python generator/generate.py --process-requests

# daftarkan permintaan + sumber baru tanpa langsung mengunduh (cepat)
python generator/generate.py --add https://contoh.com/berita --name "Contoh" --config-only

# atur jumlah unduhan paralel (default 8)
python generator/generate.py --workers 12

# tes offline (tanpa jaringan)
python generator/selftest.py
```

Pratinjau katalog di browser:

```powershell
python -m http.server 8080
# buka http://localhost:8080/
```

Di Windows ada dua launcher: **`Perbarui Feed (lokal).cmd`** dan
**`Jalankan Lokal.cmd`**.

---

## Struktur repositori

```
index.html                 katalog + formulir pembuat feed
assets/                    CSS & JS tanpa dependensi
feeds/                     hasil: <slug>.xml, <slug>.json, index.json, all.opml
examples/
  scrape_from_feed.py      contoh scraping dari hasil feed
generator/
  net.py                   HTTP + perlindungan SSRF + charset
  dom.py                   parser HTML kecil yang toleran
  extract.py               deteksi feed, ekstraksi artikel, parsing tanggal
  render.py                RSS 2.0, JSON Feed 1.1, OPML, katalog JSON
  generate.py              orkestrasi + CLI
  selftest.py              22 tes offline
sources.json               konfigurasi sumber
requests/                  kotak masuk permintaan feed dari halaman web
.github/workflows/         penjadwal, pemroses permintaan, tes
```

---

## Batasan yang perlu diketahui

- **Halaman JavaScript** (React/Vue penuh, dashboard, login) tidak bisa dibaca;
  tidak ada browser headless.
- **Situs yang memblokir bot** (403/405/429, Cloudflare challenge) akan gagal.
  Feed lama tetap tersedia dan ditandai “tertahan” di katalog.
- **Penjadwalan** mengikuti cron GitHub; bisa mundur 5–15 menit saat jam sibuk.
  Build Pages dibatasi 10 per jam — commit hanya dibuat bila isi feed berubah,
  jadi dalam praktiknya jauh di bawah batas itu.
- **Batas item** 100 per feed agar ukuran file dan waktu muat wajar.
- **Konten** milik situs sumber. Feed ini hanya menyusun ulang tautan yang
  sudah publik; tidak menyalin seluruh artikel untuk dijual ulang.
- **Repo publik**: siapa pun bisa membaca XML-nya. Jangan menambahkan sumber
  internal, berbayar, atau di balik login.

## Keamanan

- Guard SSRF: `localhost`, IP privat/loopback/link-local, dan endpoint metadata
  cloud ditolak; setiap lompatan redirect divalidasi ulang.
- Batas ukuran 4 MB dan timeout 25 detik per permintaan.
- Tidak ada eksekusi kode dari halaman sumber: hanya parsing teks.
- Workflow memakai `GITHUB_TOKEN` bawaan dengan izin `contents: write` saja.
- HTML dari sumber dibersihkan sebelum masuk XML (`esc`/CDATA + pembuangan
  karakter kontrol), sehingga tidak bisa menyuntik markup ke feed.

## Lisensi

MIT — lihat [LICENSE](LICENSE).
