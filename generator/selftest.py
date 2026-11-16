"""Tes offline: tidak menyentuh jaringan sama sekali.

Jalankan dari akar repositori:
    python generator/selftest.py
"""

from __future__ import annotations

import json
import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import extract as ex
import generate
import net
import render
from dom import parse

NOW = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)

NEWS_HTML = """
<!DOCTYPE html>
<html lang="id"><head>
  <title>Berita Maluku Utara - Contoh News</title>
  <meta name="description" content="Kumpulan berita terbaru.">
  <meta property="og:description" content="Kumpulan berita terbaru dari Maluku Utara.">
  <link rel="alternate" type="application/rss+xml" href="/feed.xml">
  <script type="application/ld+json">
  {"@type": "NewsArticle", "headline": "Gubernur Resmikan Jalan Baru",
   "url": "https://news.example.com/2026/11/15/jalan-baru", "datePublished": "2026-11-15T08:30:00+09:00",
   "description": "Peresmian jalan penghubung dua kecamatan.",
   "image": "https://news.example.com/img/jalan.jpg", "author": {"name": "Redaksi"}}
  </script>
</head>
<body>
  <nav><a href="/">Beranda</a><a href="/tag/politik">Politik</a><a href="/login">Masuk</a></nav>
  <main>
    <div class="list">
      <div class="card post-101">
        <h2 class="title"><a href="/berita/gubernur-resmikan-jalan-baru/">Gubernur Resmikan Jalan Baru</a></h2>
        <time datetime="2026-11-15T08:30:00+07:00">15 November 2026</time>
        <p>Peresmian jalan penghubung dua kecamatan berlangsung pagi ini dan dihadiri warga.</p>
        <img src="/img/jalan.jpg" width="640" height="360" alt="">
      </div>
      <div class="card post-102">
        <h2 class="title"><a href="/berita/harga-ikan-naik/">Harga Ikan di Pasar Ternate Naik</a></h2>
        <time datetime="2026-11-15T07:10:00+07:00">15 November 2026</time>
        <p>Kenaikan disebabkan cuaca buruk yang menghambat nelayan selama sepekan terakhir ini.</p>
      </div>
      <div class="card post-103">
        <h2 class="title"><a href="/berita/sekolah-roboh/">Angin Kencang Rusak Atap Sekolah</a></h2>
        <span class="post-date">2 jam lalu</span>
        <p>Sebanyak tiga ruang kelas tidak bisa dipakai sampai perbaikan selesai dilakukan.</p>
      </div>
      <div class="card post-104">
        <h2 class="title"><a href="/berita/gubernur-resmikan-jalan-baru/">Gubernur Resmikan Jalan Baru</a></h2>
        <time datetime="2026-11-15T08:30:00+07:00">15 November 2026</time>
      </div>
    </div>
    <aside>
      <a href="https://event.example.com/promo?utm_source=home">Lihat Info Selengkapnya!</a>
      <a href="https://www.facebook.com/share/abc">Bagikan ke Facebook</a>
    </aside>
  </main>
</body></html>
"""

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>Contoh News</title>
  <description><![CDATA[Berita <b>terbaru</b>]]></description>
  <language>id</language>
  <item>
    <title>Judul Pertama &amp; Lanjutan</title>
    <link>https://news.example.com/berita/pertama/?utm_source=rss</link>
    <pubDate>Sun, 15 Nov 2026 03:00:00 GMT</pubDate>
    <description><![CDATA[<p>Ringkasan <b>pertama</b> yang cukup panjang untuk dibaca.</p>]]></description>
    <content:encoded><![CDATA[<p>Isi lengkap pertama.</p>]]></content:encoded>
    <dc:creator>Redaksi</dc:creator>
    <category>Nasional</category>
    <enclosure url="https://news.example.com/img/a.png" type="image/png"/>
  </item>
  <item>
    <title>Judul Kedua</title>
    <link>https://news.example.com/berita/kedua/</link>
    <pubDate>Sat, 14 Nov 2026 20:00:00 GMT</pubDate>
    <description>Ringkasan kedua.</description>
  </item>
</channel>
</rss>
"""

ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Contoh</title>
  <subtitle>Feed contoh</subtitle>
  <entry>
    <title>Entri Atom Pertama</title>
    <link rel="alternate" href="https://atom.example.org/p/1"/>
    <id>tag:atom.example.org,2026:1</id>
    <updated>2026-11-15T01:00:00Z</updated>
    <summary>Ringkasan atom.</summary>
  </entry>
</feed>
"""


class DomTests(unittest.TestCase):
    def test_tree_and_text(self):
        root = parse("<div><p>Halo <b>dunia</b><p>Kedua")
        div = root.find("div")
        self.assertIsNotNone(div)
        self.assertEqual(len(div.find_all("p")), 2)
        self.assertIn("Halo", div.text())
        self.assertIn("Kedua", div.text())

    def test_head_metadata_is_visible_to_discovery(self):
        page = parse(NEWS_HTML)
        info = ex.discover(page, "https://news.example.com/")
        self.assertIn("https://news.example.com/feed.xml", info.feeds)
        self.assertEqual(info.title, "Berita Maluku Utara - Contoh News")
        self.assertEqual(info.language, "id")
        self.assertTrue(info.description)


class DateTests(unittest.TestCase):
    def test_indonesian_and_iso(self):
        self.assertEqual(ex.parse_date("15 November 2026 08:30", now=NOW).hour, 8)
        self.assertEqual(ex.parse_date("2026-11-15T08:30:00+07:00").hour, 1)
        self.assertEqual(ex.parse_date("15/11/2026", now=NOW).day, 15)
        self.assertEqual(ex.parse_date("Sun, 15 Nov 2026 03:00:00 GMT").hour, 3)

    def test_relative(self):
        self.assertEqual(ex.parse_date("2 jam lalu", now=NOW).hour, 8)
        self.assertEqual(ex.parse_date("kemarin", now=NOW).day, 14)

    def test_url_dates(self):
        self.assertEqual(ex.date_from_url("https://a.test/2026/11/13/x").day, 13)
        self.assertEqual(ex.date_from_url("https://a.test/nasional/20261115070202-1/x").day, 15)

    def test_invalid(self):
        self.assertIsNone(ex.parse_date(""))
        self.assertIsNone(ex.parse_date("tidak ada tanggal"))


class LinkTests(unittest.TestCase):
    def test_tracking_params_removed(self):
        url = ex.absolutize("https://a.test/x", "/berita/1/?utm_source=feed&source=home&id=7")
        self.assertTrue(url.endswith("/berita/1/?id=7"), url)

    def test_relative_and_junk(self):
        self.assertEqual(ex.absolutize("https://a.test/x/", "/y"), "https://a.test/y")
        self.assertEqual(ex.absolutize("https://a.test/x/", "mailto:hi@a.test"), "")
        self.assertEqual(ex.absolutize("https://a.test/x/", "javascript:void(0)"), "")

    def test_article_filter(self):
        self.assertFalse(ex.looks_like_article("https://a.test/tag/politik", "a.test"))
        self.assertFalse(ex.looks_like_article("https://facebook.com/x", "a.test"))
        self.assertFalse(ex.looks_like_article("https://event.a.test/promo", "a.test"))
        self.assertFalse(ex.looks_like_article("https://other.test/berita/1", "a.test"))
        self.assertTrue(ex.looks_like_article("https://a.test/berita/1", "a.test"))

    def test_slugify(self):
        self.assertEqual(generate.slugify("https://www.Kompas.com/"), "www-kompas-com")
        self.assertEqual(generate.slugify("Berita   Malut!!"), "berita-malut")
        self.assertEqual(generate.slugify(""), "feed")


class ScrapeTests(unittest.TestCase):
    def test_scrapes_articles(self):
        page = parse(NEWS_HTML)
        items = ex.scrape(page, "https://news.example.com/", now=NOW)
        self.assertGreaterEqual(len(items), 3)
        titles = [item.title for item in items]
        self.assertIn("Gubernur Resmikan Jalan Baru", titles)
        self.assertIn("Harga Ikan di Pasar Ternate Naik", titles)
        self.assertEqual(len(titles), len(set(titles)), "item duplikat harus dibuang")
        for item in items:
            self.assertTrue(item.link.startswith("https://news.example.com/"), item.link)
        first = next(i for i in items if i.title.startswith("Gubernur"))
        self.assertEqual(first.published.hour, 1)  # 08:30 +07:00 -> 01:30 UTC
        self.assertIn("jalan penghubung", first.summary)

    def test_native_feed(self):
        items, meta = ex.parse_feed(RSS_FEED, "https://news.example.com/feed.xml")
        self.assertEqual(meta["title"], "Contoh News")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "Judul Pertama & Lanjutan")
        self.assertEqual(items[0].link, "https://news.example.com/berita/pertama/")
        self.assertEqual(items[0].summary, "Ringkasan pertama yang cukup panjang untuk dibaca.")
        self.assertEqual(items[0].author, "Redaksi")
        self.assertEqual(items[0].published.hour, 3)

    def test_atom_feed(self):
        items, meta = ex.parse_feed(ATOM_FEED, "https://atom.example.org/feed")
        self.assertEqual(meta["title"], "Atom Contoh")
        self.assertEqual(items[0].link, "https://atom.example.org/p/1")
        self.assertEqual(items[0].title, "Entri Atom Pertama")


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            ex.FeedItem(
                title='Judul <script> & "kutip"',
                link="https://a.test/1",
                summary="Ringkasan <b>tebal</b> & aman",
                content="<p>Konten ]]> aman</p>",
                published=NOW,
                image="https://a.test/img/a.webp",
                author="Redaksi",
                categories=["Nasional"],
                guid="urn:test:1",
            )
        ]

    def test_rss_is_valid_xml(self):
        xml = render.render_rss(
            slug="contoh",
            title="Contoh & Uji",
            description="Deskripsi <uji>",
            site_url="https://a.test",
            self_url="https://sietekmalut.github.io/feeds/contoh.xml",
            items=self.items,
            last_build=NOW,
        )
        root = ET.fromstring(xml.encode("utf-8"))
        self.assertEqual(root.tag, "rss")
        channel = root.find("channel")
        self.assertEqual(channel.findtext("title"), "Contoh & Uji")
        item = channel.find("item")
        self.assertEqual(item.findtext("title"), 'Judul <script> & "kutip"')
        self.assertEqual(item.findtext("guid"), "urn:test:1")
        self.assertIn("<p>Konten ]]&gt; aman</p>", item.find("{http://purl.org/rss/1.0/modules/content/}encoded").text)
        enclosure = item.find("enclosure")
        self.assertEqual(enclosure.get("type"), "image/webp")

    def test_control_characters_are_removed(self):
        xml = render.render_rss(
            slug="x",
            title="Judul\x07aneh",
            description="d",
            site_url="https://a.test",
            self_url="https://a.test/x.xml",
            items=[],
            last_build=NOW,
        )
        ET.fromstring(xml.encode("utf-8"))
        self.assertNotIn("\x07", xml)

    def test_json_feed_mirror(self):
        payload = json.loads(
            render.render_json_feed(
                title="Contoh & Uji",
                description="Deskripsi",
                site_url="https://a.test",
                feed_url="https://sietekmalut.github.io/feeds/contoh.json",
                items=self.items,
            )
        )
        self.assertEqual(payload["version"], "https://jsonfeed.org/version/1.1")
        self.assertEqual(payload["feed_url"], "https://sietekmalut.github.io/feeds/contoh.json")
        entry = payload["items"][0]
        self.assertEqual(entry["url"], "https://a.test/1")
        self.assertEqual(entry["title"], 'Judul <script> & "kutip"')
        self.assertEqual(entry["id"], "urn:test:1")
        self.assertEqual(entry["authors"][0]["name"], "Redaksi")
        self.assertIn("date_published", entry)
        self.assertEqual(entry["image"], "https://a.test/img/a.webp")

    def test_opml_and_own_feed_roundtrip(self):
        payload = [{
            "name": "A & B", "xml_url": "https://sietekmalut.github.io/feeds/a.xml",
            "site_url": "https://a.test", "status": "ok", "items": 1,
        }]
        opml = render.render_opml("Katalog", payload)
        self.assertEqual(ET.fromstring(opml.encode("utf-8")).tag, "opml")

        xml = render.render_rss(
            slug="contoh", title="Contoh", description="d", site_url="https://a.test",
            self_url="https://sietekmalut.github.io/feeds/contoh.xml", items=self.items,
            last_build=NOW,
        )
        recovered = render.parse_own_feed(xml)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["link"], "https://a.test/1")
        self.assertEqual(recovered[0]["title"], 'Judul <script> & "kutip"')


class StabilityTests(unittest.TestCase):
    def test_fingerprint_ignores_tracking_and_slash(self):
        a = ex.FeedItem(title="Sama", link="https://a.test/berita/1/?utm_source=x", published=NOW)
        b = ex.FeedItem(title="Sama", link="https://a.test/berita/1", published=NOW)
        self.assertEqual(a.fingerprint(), b.fingerprint())

    def test_canonical_link(self):
        self.assertEqual(
            ex.canonical_link("https://A.test/Berita/1/?x=1#top"),
            "https://a.test/berita/1",
        )

    def test_clock_skew_is_corrected(self):
        items = [
            ex.FeedItem(title=f"Berita {i}", link=f"https://a.test/{i}", published=NOW + timedelta(hours=7, minutes=-5 * i))
            for i in range(6)
        ]
        self.assertEqual(generate.fix_clock_skew(items, NOW), 7)
        self.assertTrue(all(item.published <= NOW for item in items))

    def test_clock_skew_ignores_isolated_future_item(self):
        items = [
            ex.FeedItem(title=f"Berita {i}", link=f"https://a.test/{i}", published=NOW - timedelta(hours=i + 1))
            for i in range(6)
        ]
        items.append(ex.FeedItem(title="Terjadwal", link="https://a.test/x", published=NOW + timedelta(hours=2)))
        self.assertEqual(generate.fix_clock_skew(items, NOW), 0)


class RequestTests(unittest.TestCase):
    """File permintaan dari Windows sering membawa BOM; jangan sampai ditolak."""

    def test_bom_request_is_accepted(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            requests_dir = Path(tmp)
            (requests_dir / "contoh.json").write_bytes(
                '\ufeff{"name":"Contoh","url":"https://contoh.test/berita"}'.encode("utf-8")
            )
            config = {"meta": {}, "defaults": {}, "sources": []}
            original = generate.REQUESTS_DIR
            generate.REQUESTS_DIR = requests_dir
            try:
                touched = generate.process_requests(config)
            finally:
                generate.REQUESTS_DIR = original

        self.assertEqual(touched, ["contoh"])
        self.assertEqual(config["sources"][0]["url"], "https://contoh.test/berita")
        self.assertEqual(config["sources"][0]["name"], "Contoh")


class SafetyTests(unittest.TestCase):
    def test_private_hosts_blocked(self):
        for url in (
            "http://127.0.0.1/",
            "http://localhost:8000/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "file:///etc/passwd",
        ):
            with self.assertRaises(net.FetchError, msg=url):
                net.fetch(url, timeout=3)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"\n{'LULUS' if result.wasSuccessful() else 'GAGAL'}: "
          f"{result.testsRun - len(result.failures) - len(result.errors)}/{result.testsRun} tes")
    raise SystemExit(0 if result.wasSuccessful() else 1)
