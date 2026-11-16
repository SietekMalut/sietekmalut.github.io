"""Contoh memakai feed hasil generator untuk scraping.

Membuktikan bahwa link XML/JSON yang dihasilkan benar-benar bisa dipakai
sebagai sumber scraping: ambil daftar artikel, lalu (opsional) buka tiap
artikel dan tarik teks utamanya.

Contoh:
    python examples/scrape_from_feed.py https://sietekmalut.github.io/feeds/kompas.xml
    python examples/scrape_from_feed.py https://sietekmalut.github.io/feeds/malutpost.json --json
    python examples/scrape_from_feed.py https://sietekmalut.github.io/feeds/detik.xml --fetch --limit 3
    python examples/scrape_from_feed.py https://sietekmalut.github.io/feeds/all.opml --all

Hanya memakai pustaka standar. Mohon tetap menghormati robots.txt dan
ketentuan situs sumber saat mengambil halaman artikel.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "generator"))

import extract as ex  # noqa: E402
import net  # noqa: E402
from dom import parse  # noqa: E402


def load_items(feed_url: str) -> tuple[list[dict], dict]:
    """Baca RSS 2.0, JSON Feed 1.1, atau OPML."""
    response = net.fetch(feed_url)
    lowered = feed_url.lower()
    looks_json = lowered.endswith(".json") or "json" in response.content_type.lower()

    if looks_json:
        data = json.loads(response.text)
        items = [
            {
                "title": entry.get("title", ""),
                "url": entry.get("url") or entry.get("external_url", ""),
                "published": entry.get("date_published", ""),
                "summary": entry.get("summary", ""),
                "content": entry.get("content_text", ""),
            }
            for entry in data.get("items", [])
        ]
        return items, {"title": data.get("title", ""), "kind": "json"}

    if lowered.endswith(".opml"):
        root = parse(response.text)
        outlines = [n for n in root.walk() if n.tag == "outline" and n.get("xmlUrl")]
        return (
            [{"title": o.get("title"), "url": o.get("xmlUrl"), "published": "", "summary": ""} for o in outlines],
            {"title": "OPML", "kind": "opml"},
        )

    items, meta = ex.parse_feed(response.text, feed_url)
    return (
        [
            {
                "title": item.title,
                "url": item.link,
                "published": item.published.isoformat() if item.published else "",
                "summary": item.summary,
                "content": item.content,
            }
            for item in items
        ],
        {"title": meta.get("title", ""), "kind": "rss"},
    )


def scrape_article(url: str) -> dict:
    """Ambil teks utama satu artikel: pilih wadah dengan teks terbanyak."""
    response = net.fetch(url)
    page = parse(response.text)

    candidates = page.find_all("article") or page.find_all("main") or [page]
    best = max(candidates, key=lambda node: len(node.text()))
    paragraphs = [ex.clean_text(p.text()) for p in best.find_all("p")]
    body = "\n\n".join(p for p in paragraphs if len(p) > 40)

    return {
        "url": url,
        "final_url": response.url,
        "title": ex.clean_text((page.find("title").text() if page.find("title") else ""))[:200],
        "paragraphs": len(paragraphs),
        "text": (body or best.text())[:6000],
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Scrape artikel dari feed SietekMalut.")
    parser.add_argument("feed", help="URL feed .xml, .json, atau .opml")
    parser.add_argument("--limit", type=int, default=10, help="jumlah artikel (default 10)")
    parser.add_argument("--fetch", action="store_true", help="buka tiap artikel dan ambil teksnya")
    parser.add_argument("--json", action="store_true", help="cetak JSON, bukan tabel")
    parser.add_argument("--out", help="simpan hasil ke file JSON")
    parser.add_argument("--all", action="store_true", help="untuk OPML: proses semua feed di dalamnya")
    args = parser.parse_args(argv)

    items, meta = load_items(args.feed)
    print(f"# {meta['title']}  ({len(items)} item, format {meta['kind']})")

    if meta["kind"] == "opml" and args.all:
        collected = []
        for outline in items:
            try:
                child_items, _ = load_items(outline["url"])
            except (net.FetchError, ValueError) as exc:
                print(f"  ! {outline['url']}: {exc}")
                continue
            for entry in child_items:
                entry["feed"] = outline["title"]
            collected.extend(child_items)
            print(f"  ok {outline['title']}: {len(child_items)} item")
        items = collected

    items = items[: max(1, args.limit)]
    results = []
    for index, item in enumerate(items, 1):
        record = dict(item)
        if args.fetch and item.get("url"):
            try:
                record["scraped"] = scrape_article(item["url"])
            except (net.FetchError, ValueError) as exc:
                record["scraped"] = {"error": str(exc)}
        results.append(record)

        if not args.json:
            when = (item.get("published") or "")[:16].replace("T", " ")
            print(f"{index:>2}. {when:<16} {item.get('title', '')[:80]}")
            print(f"    {item.get('url', '')}")
            if args.fetch:
                text = record.get("scraped", {})
                if text.get("error"):
                    print(f"    ! {text['error']}")
                else:
                    preview = text.get("text", "").replace("\n", " ")[:160]
                    print(f"    {text.get('paragraphs', 0)} paragraf · {preview}…")

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))

    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nDisimpan ke {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
