"""Render FeedItem lists as RSS 2.0, plus the OPML and JSON catalog."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from html import unescape

from extract import FeedItem

_BAD_XML = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff\ufffe\uffff]"
)
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def esc(value: str) -> str:
    value = _BAD_XML.sub("", value or "")
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def cdata(value: str) -> str:
    value = _BAD_XML.sub("", value or "").replace("]]>", "]]&gt;")
    return f"<![CDATA[{value}]]>"


def rfc822(moment: datetime | None) -> str:
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return format_datetime(moment.astimezone(timezone.utc), usegmt=True)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def guid_for(slug: str, link: str) -> str:
    digest = hashlib.sha1(link.encode("utf-8", "replace")).hexdigest()[:16]
    return f"tag:sietekmalut.github.io,2026:rss/{slug}/{digest}"


_MIME_BY_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "avif": "image/avif",
    "svg": "image/svg+xml",
}


def image_mime(url: str) -> str:
    match = re.search(r"\.([a-z0-9]{2,5})(?:\?|#|$)", url or "", re.I)
    if match:
        return _MIME_BY_EXT.get(match.group(1).lower(), "image/jpeg")
    return "image/jpeg"


def render_rss(
    *,
    slug: str,
    title: str,
    description: str,
    site_url: str,
    self_url: str,
    items: list[FeedItem],
    language: str = "id",
    ttl: int = 30,
    last_build: datetime | None = None,
    generator: str = "SietekMalut RSS Feed Generator",
) -> str:
    last_build = last_build or datetime.now(timezone.utc)
    published = max((i.published for i in items if i.published), default=None) or last_build

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">',
        "  <channel>",
        f"    <title>{esc(title)}</title>",
        f"    <link>{esc(site_url)}</link>",
        f"    <description>{esc(description)}</description>",
        f"    <language>{esc(language or 'id')}</language>",
        f"    <lastBuildDate>{rfc822(last_build)}</lastBuildDate>",
        f"    <pubDate>{rfc822(published)}</pubDate>",
        f"    <ttl>{int(ttl)}</ttl>",
        f"    <generator>{esc(generator)}</generator>",
        f'    <atom:link href="{esc(self_url)}" rel="self" type="application/rss+xml"/>',
        "  </channel>",
        "</rss>",
    ]

    item_lines: list[str] = []
    for item in items:
        item_lines.append("    <item>")
        item_lines.append(f"      <title>{esc(item.title)}</title>")
        item_lines.append(f"      <link>{esc(item.link)}</link>")
        item_lines.append(
            f'      <guid isPermaLink="false">{esc(item.guid or guid_for(slug, item.link))}</guid>'
        )
        if item.published:
            item_lines.append(f"      <pubDate>{rfc822(item.published)}</pubDate>")
        if item.summary:
            item_lines.append(f"      <description>{esc(item.summary)}</description>")
        if item.content and item.content.strip() != item.summary.strip():
            item_lines.append(f"      <content:encoded>{cdata(item.content)}</content:encoded>")
        if item.author:
            item_lines.append(f"      <dc:creator>{esc(item.author)}</dc:creator>")
        for category in item.categories[:4]:
            item_lines.append(f"      <category>{esc(category)}</category>")
        if item.image:
            item_lines.append(
                f'      <enclosure url="{esc(item.image)}" type="{image_mime(item.image)}" length="0"/>'
            )
        item_lines.append("    </item>")

    start = lines.index("  </channel>")
    return "\n".join(lines[:start] + item_lines + lines[start:]) + "\n"


def render_opml(title: str, feeds: list[dict]) -> str:
    outlines = []
    for feed in feeds:
        if feed.get("status") == "error" and not feed.get("items"):
            continue
        outlines.append(
            '    <outline type="rss" text="{}" title="{}" xmlUrl="{}" htmlUrl="{}"/>'.format(
                esc(feed["name"]), esc(feed["name"]), esc(feed["xml_url"]), esc(feed["site_url"])
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<opml version="2.0">\n'
        "  <head>\n"
        f"    <title>{esc(title)}</title>\n"
        "  </head>\n"
        "  <body>\n"
        + "\n".join(outlines)
        + "\n  </body>\n</opml>\n"
    )


def render_index(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def render_json_feed(
    *,
    title: str,
    description: str,
    site_url: str,
    feed_url: str,
    items: list[FeedItem],
    language: str = "id",
) -> str:
    """JSON Feed 1.1 mirror: jauh lebih mudah dipakai untuk scraping."""
    entries = []
    for item in items:
        entry = {
            "id": item.guid or item.link,
            "url": item.link,
            "title": item.title,
        }
        if item.summary:
            entry["summary"] = item.summary
        if item.content:
            entry["content_html"] = item.content
        elif item.summary:
            entry["content_text"] = item.summary
        if item.published:
            entry["date_published"] = iso(item.published)
        if item.image:
            entry["image"] = item.image
        if item.author:
            entry["authors"] = [{"name": item.author}]
        if item.categories:
            entry["tags"] = item.categories[:4]
        entries.append(entry)

    payload = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": title,
        "home_page_url": site_url,
        "feed_url": feed_url,
        "description": description,
        "language": language or "id",
        "items": entries,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def parse_own_feed(xml_text: str) -> list[dict]:
    """Read back a previously generated file so a flaky source keeps its items."""
    records = []
    for match in re.finditer(r"<item>(.*?)</item>", xml_text, re.S | re.I):
        block = match.group(1)

        def tag(name: str) -> str:
            found = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S | re.I)
            if not found:
                return ""
            value = found.group(1).strip()
            if value.startswith("<![CDATA["):
                value = value[9:-3] if value.endswith("]]>") else value[9:]
                return value
            return unescape(value)

        link = tag("link")
        if not link:
            continue
        records.append(
            {
                "title": tag("title"),
                "link": link,
                "guid": tag("guid"),
                "description": tag("description"),
                "published": tag("pubDate"),
                "category": [],
            }
        )
    return records
