"""SietekMalut RSS Feed Generator.

Builds static RSS 2.0 feeds from a list of websites and writes them into
./feeds so GitHub Pages can serve them at
https://sietekmalut.github.io/feeds/<slug>.xml

Usage (from the repository root):
    python generator/generate.py                 # refresh every enabled source
    python generator/generate.py --slug detik    # one source
    python generator/generate.py --check         # fetch + report, write nothing
    python generator/generate.py --add https://example.com/berita --name "Example"
    python generator/generate.py --process-requests
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract as ex
import net
import render
from dom import parse

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FEEDS_DIR = ROOT / "feeds"
CONFIG_PATH = ROOT / "sources.json"
REQUESTS_DIR = ROOT / "requests"
DEFAULT_SITE = "https://sietekmalut.github.io"

MAX_ITEMS = 100
MIN_ITEMS = 60


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def log(message: str) -> None:
    print(message, flush=True)


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-{2,}", "-", value).strip("-")[:60] or "feed"


def link_key(url: str) -> str:
    return ex.canonical_link(url)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"meta": {"site_url": DEFAULT_SITE, "title": "SietekMalut RSS"}, "defaults": {}, "sources": []}
    with CONFIG_PATH.open(encoding="utf-8-sig") as handle:
        config = json.load(handle)
    config.setdefault("meta", {}).setdefault("site_url", DEFAULT_SITE)
    config.setdefault("defaults", {})
    config.setdefault("sources", [])
    return config


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


@dataclass
class Result:
    slug: str
    name: str
    status: str = "ok"          # ok | error | skipped
    mode: str = ""
    items: int = 0
    message: str = ""
    changed: bool = False
    title: str = ""
    description: str = ""
    site_url: str = ""
    language: str = "id"
    source_url: str = ""
    final_url: str = ""
    latest: str = ""


# --------------------------------------------------------------------------
# building one source
# --------------------------------------------------------------------------


def _pick_limit(source: dict, defaults: dict) -> int:
    limit = source.get("limit", defaults.get("limit", 30))
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 30
    return max(1, min(MAX_ITEMS, limit))


def _apply_filters(items: list[ex.FeedItem], source: dict) -> list[ex.FeedItem]:
    include = source.get("include")
    exclude = source.get("exclude")
    title_exclude = source.get("title_exclude")
    if include:
        pattern = re.compile(include, re.I)
        items = [i for i in items if pattern.search(i.link)]
    if exclude:
        pattern = re.compile(exclude, re.I)
        items = [i for i in items if not pattern.search(i.link)]
    if title_exclude:
        pattern = re.compile(title_exclude, re.I)
        items = [i for i in items if not pattern.search(i.title)]
    return items


def _try_parse_feed(text: str, base_url: str) -> tuple[list[ex.FeedItem], dict] | None:
    try:
        items, meta = ex.parse_feed(text, base_url)
    except Exception:
        return None
    if not items:
        return None
    return items, meta


_COMMON_FEED_PATHS = (
    "/feed",
    "/rss",
    "/rss.xml",
    "/feed.xml",
    "/index.xml",
    "/atom.xml",
    "/?feed=rss2",
)


def _dated_ratio(items: list[ex.FeedItem]) -> float:
    if not items:
        return 0.0
    return sum(1 for i in items if i.published) / len(items)


def fix_clock_skew(items: list[ex.FeedItem], now: datetime) -> int:
    """Correct feeds that label local time as GMT.

    Many Indonesian newsrooms publish ``09:42 GMT`` for 09:42 WIB. If most
    timestamps sit hours in the future, the whole feed is shifted by a whole
    number of hours. Returns the applied shift (0 when nothing changed).
    """
    stamps = [i.published for i in items if i.published]
    if len(stamps) < 3:
        return 0
    future = [moment for moment in stamps if moment > now + timedelta(minutes=30)]
    if len(future) < max(2, int(len(stamps) * 0.4)):
        return 0
    deltas = sorted((moment - now).total_seconds() / 3600 for moment in future)
    shift = int(round(deltas[len(deltas) // 2]))
    if not 1 <= shift <= 14:
        return 0
    for item in items:
        if item.published:
            item.published -= timedelta(hours=shift)
    return shift


def collect(source: dict, defaults: dict, now: datetime) -> tuple[list[ex.FeedItem], str, dict, str]:
    """Return (items, mode, meta, final_url). Raises FetchError/ValueError."""
    url = (source.get("url") or "").strip()
    if not url:
        raise ValueError("sumber tanpa URL")

    mode = (source.get("mode") or defaults.get("mode") or "auto").lower()
    if mode not in ("auto", "feed", "html"):
        mode = "auto"

    response = net.fetch(url)

    if response.is_xml:
        parsed = _try_parse_feed(response.text, response.url)
        if parsed:
            items, meta = parsed
            return items, "feed", meta, response.url
        if mode == "feed":
            raise ValueError("URL mengembalikan XML yang tidak bisa dibaca sebagai feed")

    page = parse(response.text)
    info = ex.discover(page, response.url)

    html_items: list[ex.FeedItem] = []
    if mode in ("auto", "html"):
        html_items = ex.scrape(
            page,
            response.url,
            now=now,
            min_items=int(source.get("min_items", defaults.get("min_items", 3))),
            site_names=[source.get("name", ""), info.title],
        )

    def native_is_better(candidate: list[ex.FeedItem]) -> bool:
        if not candidate:
            return False
        if not html_items:
            return True
        if _dated_ratio(candidate) > _dated_ratio(html_items):
            return True
        return len(candidate) >= max(3, len(html_items))

    candidates = list(info.feeds[:3])
    origin = _origin(response.url)
    is_root = urlsplit(response.url).path in ("", "/")
    probe_common = mode == "feed" or (
        mode == "auto" and (len(html_items) < 6 or _dated_ratio(html_items) < 0.5)
    )
    common: list[str] = []
    if probe_common:
        common = [origin + path for path in _COMMON_FEED_PATHS]

    # On a site root the whole-site feed usually represents the front page
    # better than the first category feed found in <link rel=alternate>.
    ordered = (common + candidates) if is_root else (candidates + common)
    seen: set[str] = set()
    ordered = [c for c in ordered if not (c in seen or seen.add(c))]

    for candidate_url in ordered[:6]:
        try:
            feed_response = net.fetch(candidate_url)
        except net.FetchError:
            continue
        parsed = _try_parse_feed(feed_response.text, feed_response.url)
        if not parsed:
            continue
        items, meta = parsed
        if mode == "feed" or native_is_better(items):
            return items, "native", meta, feed_response.url

    if mode == "feed":
        raise ValueError("tidak menemukan feed RSS/Atom di halaman itu")

    meta = {"title": info.title, "description": info.description, "language": info.language}
    if not html_items:
        raise ValueError(
            "tidak ada artikel yang bisa diekstrak (halaman mungkin butuh JavaScript)"
        )
    return html_items, "html", meta, response.url


def _existing_items(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return render.parse_own_feed(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def _to_item(record: dict) -> ex.FeedItem:
    return ex.FeedItem(
        title=record.get("title", ""),
        link=record.get("link", ""),
        summary=record.get("description", ""),
        guid=record.get("guid", ""),
        published=ex.parse_date(record.get("published", "")),
    )


def build_source(
    source: dict,
    defaults: dict,
    *,
    feeds_dir: Path,
    site_url: str,
    now: datetime,
    write: bool = True,
    verbose: bool = False,
) -> Result:
    slug = slugify(source.get("slug") or source.get("name") or source.get("url", "feed"))
    name = (source.get("name") or slug).strip()
    result = Result(slug=slug, name=name, source_url=source.get("url", ""))
    out_path = feeds_dir / f"{slug}.xml"

    try:
        items, mode, meta, final_url = collect(source, defaults, now)
    except (net.FetchError, ValueError) as exc:
        result.status = "error"
        result.message = str(exc)
        if out_path.exists():
            result.items = len(_existing_items(out_path))
            result.changed = False
            result.message += " (feed lama dipertahankan)"
        return result

    items = _apply_filters(items, source)
    limit = _pick_limit(source, defaults)
    fix_clock_skew(items, now)

    previous = _existing_items(out_path)
    previous_keys = {link_key(r["link"]) for r in previous}
    merged = list(items)
    if previous:
        # Keep items that disappeared from the page (pagination, A/B tests,
        # transient flakiness) instead of shrinking the feed every run.
        old_items = [_to_item(r) for r in previous]
        old_by_key = {link_key(o.link): o for o in old_items}
        for item in merged:
            old = old_by_key.get(link_key(item.link))
            if old is None or old.published is None:
                continue
            if item.published is None:
                item.published = old.published
            elif abs((item.published - old.published).total_seconds()) <= 2 * 3600:
                # Relative timestamps ("5 menit lalu") drift on every run.
                # Keep the first-seen moment so the feed stays byte-stable.
                item.published = old.published
        new_keys = {link_key(i.link) for i in merged}
        merged += [o for o in old_items if link_key(o.link) not in new_keys]

    seen: set[str] = set()
    unique: list[ex.FeedItem] = []
    for item in merged:
        key = link_key(item.link)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(
        key=lambda i: i.published or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True
    )
    unique = unique[:limit]

    if not unique:
        result.status = "error"
        result.message = "tidak ada artikel yang bisa diekstrak"
        return result

    def _old_fingerprint(record: dict) -> str:
        moment = ex.parse_date(record.get("published", ""))
        return f"{link_key(record['link'])}|{record.get('title', '').strip()}|{moment.isoformat() if moment else ''}"

    new_fingerprints = sorted(i.fingerprint() for i in unique)
    old_fingerprints = sorted(_old_fingerprint(r) for r in previous)
    changed = new_fingerprints != old_fingerprints

    result.mode = mode
    result.items = len(unique)
    result.changed = changed
    result.title = (source.get("title") or meta.get("title") or name).strip()[:200]
    result.description = (
        source.get("description")
        or meta.get("description")
        or f"Feed RSS otomatis untuk {name}."
    ).strip()[:500]
    result.site_url = (source.get("site_url") or _origin(final_url)).rstrip("/")
    result.language = (source.get("language") or meta.get("language") or "id").strip()[:12].split("-")[0] or "id"
    result.final_url = final_url
    latest = max((i.published for i in unique if i.published), default=None)
    result.latest = render.iso(latest) if latest else ""

    if not write:
        return result

    feeds_dir.mkdir(parents=True, exist_ok=True)
    json_path = feeds_dir / f"{slug}.json"
    # XML ditulis hanya bila isinya berubah (commit tetap kecil), tetapi JSON
    # selalu dipastikan ada karena dipakai untuk scraping dan bisa saja baru
    # ditambahkan pada versi generator yang lebih baru.
    if changed or not out_path.exists() or not json_path.exists():
        xml = render.render_rss(
            slug=slug,
            title=result.title,
            description=result.description,
            site_url=result.site_url,
            self_url=f"{site_url}/feeds/{slug}.xml",
            items=unique,
            language=result.language,
            ttl=int(source.get("ttl", defaults.get("ttl", 30))),
            last_build=now,
        )
        out_path.write_text(xml, encoding="utf-8", newline="\n")
        json_path.write_text(
            render.render_json_feed(
                title=result.title,
                description=result.description,
                site_url=result.site_url,
                feed_url=f"{site_url}/feeds/{slug}.json",
                items=unique,
                language=result.language,
            ),
            encoding="utf-8",
            newline="\n",
        )
    return result


def _origin(url: str) -> str:
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else (url or DEFAULT_SITE)


# --------------------------------------------------------------------------
# catalog
# --------------------------------------------------------------------------


def write_catalog(config: dict, results: list[Result], feeds_dir: Path, now: datetime) -> bool:
    site_url = config["meta"]["site_url"].rstrip("/")
    index_path = feeds_dir / "index.json"

    previous: dict = {}
    if index_path.exists():
        try:
            previous = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}

    by_slug = {r.slug: r for r in results}
    previous_by_slug = {f.get("slug"): f for f in previous.get("feeds", [])}

    feeds_payload = []
    for source in config["sources"]:
        if source.get("enabled") is False:
            continue
        slug = slugify(source.get("slug") or source.get("name") or source.get("url", "feed"))
        result = by_slug.get(slug)
        old = previous_by_slug.get(slug, {})
        xml_path = feeds_dir / f"{slug}.xml"
        has_file = xml_path.exists()
        if result is None and not has_file:
            continue

        entry = {
            "slug": slug,
            "name": (source.get("name") or slug).strip(),
            "title": (result.title if result and result.title else old.get("title") or source.get("name") or slug),
            "description": (
                result.description
                if result and result.description
                else old.get("description", "")
            ),
            "source_url": source.get("url", ""),
            "site_url": (
                result.site_url if result and result.site_url else old.get("site_url", "")
            ),
            "xml_url": f"{site_url}/feeds/{slug}.xml",
            "json_url": f"{site_url}/feeds/{slug}.json",
            "mode": (result.mode if result and result.mode else old.get("mode", "")),
            "language": (result.language if result and result.language else old.get("language", "id")),
            "items": (result.items if result else old.get("items", 0)),
            "latest": (result.latest if result and result.latest else old.get("latest", "")),
            "updated": (
                datetime.fromtimestamp(xml_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if has_file
                else ""
            ),
            "status": (
                "error"
                if result and result.status == "error" and not has_file
                else old.get("status", "ok") if result is None else "ok"
            ),
            "error": (result.message if result and result.status == "error" else old.get("error", "") if result is None else ""),
            "stale": bool(
                (result and result.status == "error" and has_file)
                or (result is None and old.get("stale"))
            ),
        }
        feeds_payload.append(entry)

    payload = {
        "site": site_url,
        "generated": render.iso(now),
        "count": len(feeds_payload),
        "feeds": feeds_payload,
    }
    opml = render.render_opml(config["meta"].get("title", "SietekMalut RSS"), feeds_payload)

    changed = False
    if not index_path.exists():
        changed = True
    else:
        try:
            old = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = {}
        old.pop("generated", None)
        probe = json.loads(json.dumps(payload))
        probe.pop("generated", None)
        if old != probe:
            changed = True

    if changed:
        feeds_dir.mkdir(parents=True, exist_ok=True)
        index_path.write_text(render.render_index(payload), encoding="utf-8", newline="\n")
        opml_path = feeds_dir / "all.opml"
        opml_path.write_text(opml, encoding="utf-8", newline="\n")
    return changed


# --------------------------------------------------------------------------
# requests + CLI
# --------------------------------------------------------------------------


def process_requests(config: dict) -> list[str]:
    """Merge requests/*.json into sources.json. Returns affected slugs."""
    if not REQUESTS_DIR.exists():
        return []
    touched: list[str] = []
    existing = {
        slugify(s.get("slug") or s.get("name") or s.get("url", "")): s
        for s in config["sources"]
    }
    for path in sorted(REQUESTS_DIR.glob("*.json")):
        try:
            # utf-8-sig: toleran terhadap BOM, yang mudah muncul saat file
            # dibuat dari Notepad / PowerShell di Windows.
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            log(f"  ! lewati {path.name}: {exc}")
            path.unlink(missing_ok=True)
            continue
        if isinstance(payload, list):
            entries = payload
        else:
            entries = [payload]
        for entry in entries:
            url = (entry.get("url") or "").strip()
            if not url:
                log(f"  ! {path.name}: tanpa url")
                continue
            slug = slugify(entry.get("slug") or entry.get("name") or url)
            record = existing.get(slug)
            if record is None:
                record = {"slug": slug, "name": (entry.get("name") or slug).strip(), "url": url}
                config["sources"].append(record)
                existing[slug] = record
            else:
                record["url"] = url
                if entry.get("name"):
                    record["name"] = entry["name"].strip()
            for key in ("mode", "limit", "language", "include", "exclude", "title_exclude", "min_items", "ttl"):
                if key in entry and entry[key] not in (None, ""):
                    record[key] = entry[key]
            record.setdefault("enabled", True)
            touched.append(slug)
        path.unlink(missing_ok=True)
    return touched


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate static RSS feeds for GitHub Pages.")
    parser.add_argument("--slug", action="append", help="hanya proses slug ini (boleh berulang)")
    parser.add_argument("--check", action="store_true", help="ambil & laporkan saja, tanpa menulis file")
    parser.add_argument("--add", metavar="URL", help="tambahkan sumber baru ke sources.json")
    parser.add_argument("--name", help="nama tampilan untuk --add")
    parser.add_argument("--limit", type=int, help="jumlah item maksimum untuk --add")
    parser.add_argument("--mode", choices=["auto", "feed", "html"], help="mode untuk --add")
    parser.add_argument("--process-requests", action="store_true", help="proses folder requests/")
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="hanya perbarui sources.json (dipakai sebelum membangun semua feed)",
    )
    parser.add_argument("--feeds-dir", help="folder output (default: ./feeds)")
    parser.add_argument("--workers", type=int, default=8, help="jumlah unduhan paralel")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = load_config()
    site_url = config["meta"]["site_url"].rstrip("/")
    defaults = config.get("defaults", {})
    now = datetime.now(timezone.utc)
    feeds_dir = Path(args.feeds_dir) if args.feeds_dir else DEFAULT_FEEDS_DIR

    if args.process_requests:
        touched = process_requests(config)
        if touched:
            save_config(config)
            log(f"permintaan diproses: {', '.join(touched)}")
            args.slug = (args.slug or []) + touched

    if args.add:
        slug = slugify(args.name or args.add)
        record = {"slug": slug, "name": (args.name or slug).strip(), "url": args.add.strip()}
        if args.limit:
            record["limit"] = args.limit
        if args.mode:
            record["mode"] = args.mode
        config["sources"] = [s for s in config["sources"] if slugify(s.get("slug") or "") != slug]
        config["sources"].append(record)
        save_config(config)
        log(f"sumber ditambahkan: {slug}")
        args.slug = (args.slug or []) + [slug]
        config = load_config()

    if args.config_only:
        log("konfigurasi diperbarui; feed akan dibangun pada langkah berikutnya")
        return 0

    selected = [s for s in config["sources"] if s.get("enabled", True) is not False]
    if args.slug:
        wanted = {slugify(s) for s in args.slug}
        selected = [
            s
            for s in selected
            if slugify(s.get("slug") or s.get("name") or "") in wanted
        ]
        if not selected:
            log("tidak ada sumber yang cocok dengan --slug")
            return 1

    if not selected:
        log("sources.json masih kosong. Tambahkan sumber dengan --add atau lewat UI.")
        return 0

    log(f"{'MEMERIKSA' if args.check else 'MEMBUAT'} {len(selected)} feed"
        f" -> {feeds_dir}{' (dry-run)' if args.check else ''}")

    def work(source: dict) -> Result:
        return build_source(
            source,
            defaults,
            feeds_dir=feeds_dir,
            site_url=site_url,
            now=now,
            write=not args.check,
            verbose=args.verbose,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(8, args.workers))) as pool:
        results = list(pool.map(work, selected))

    order = {slugify(s.get("slug") or s.get("name") or ""): index for index, s in enumerate(selected)}
    results.sort(key=lambda r: order.get(r.slug, 999))

    for result in results:
        icon = {"ok": "OK ", "error": "ERR", "skipped": "--"}[result.status]
        state = "baru" if result.changed else "tetap"
        detail = f"  {result.message}" if result.message else ""
        log(f"  [{icon}] {result.slug:<24} {result.items:>3} item  {state:<5} {result.mode:<6}{detail}")

    catalog_changed = False
    if not args.check:
        catalog_changed = write_catalog(config, results, feeds_dir, now)

    failures = [r for r in results if r.status == "error"]
    changed = [r for r in results if r.changed]
    log(
        f"selesai: {len(results) - len(failures)} sukses, {len(failures)} gagal, "
        f"{len(changed)} feed berubah, katalog {'diperbarui' if catalog_changed else 'tidak berubah'}"
    )

    if args.slug and len(results) == 1 and not args.check:
        result = results[0]
        if result.status == "ok":
            log(f"URL feed: {site_url}/feeds/{result.slug}.xml")

    if args.check and failures:
        return 2
    if failures and len(failures) == len(results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
