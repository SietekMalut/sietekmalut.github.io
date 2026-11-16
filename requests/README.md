# Folder permintaan feed

Setiap file `*.json` di folder ini adalah satu permintaan feed yang akan
diproses otomatis oleh `.github/workflows/update-feeds.yml`.

Bentuk file:

```json
{
  "name": "Nama Feed",
  "url": "https://contoh.com/berita",
  "limit": 30,
  "mode": "auto"
}
```

- `name` — nama tampilan di katalog (juga menentukan nama file XML).
- `url` — halaman yang dijadikan sumber.
- `limit` — jumlah item maksimum, 5 sampai 100 (opsional).
- `mode` — `auto` (default), `feed`, atau `html` (opsional).

Alur kerja:

1. File masuk ke folder ini lewat commit.
2. GitHub Actions menjalankan `python generator/generate.py --process-requests`.
3. Sumber ditambahkan ke `sources.json`, file permintaan dihapus, feed XML dibuat.
4. Hasilnya di-commit otomatis, lalu muncul di katalog beberapa detik kemudian.

Cara termudah membuat file ini: buka halaman utama situs, isi formulir
**Buat feed baru**, lalu tekan tombol GitHub yang muncul.
