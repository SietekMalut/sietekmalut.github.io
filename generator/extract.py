"""Turn a web page (or an existing feed) into a list of FeedItem objects.

Two paths:
  * native feeds are parsed with ElementTree and normalised,
  * HTML pages are scanned with a few complementary strategies
    (JSON-LD -> <article> -> repeated blocks -> link clustering).
"""

from __future__ import annotations

import json
import re
import urllib.parse as up
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape

from dom import Node, parse

# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------


@dataclass
class FeedItem:
    title: str
    link: str
    summary: str = ""
    content: str = ""
    published: datetime | None = None
    image: str = ""
    author: str = ""
    guid: str = ""
    categories: list[str] = field(default_factory=list)

    def fingerprint(self) -> str:
        when = self.published.isoformat() if self.published else ""
        return "|".join((canonical_link(self.link) or self.guid, self.title.strip(), when))


@dataclass
class Discovery:
    feeds: list[str] = field(default_factory=list)
    title: str = ""
    description: str = ""
    language: str = ""


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------

_WS = re.compile(r"[\s\u00a0\u200b]+")
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff\u00ad]")

_ID_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "agu": 8,
    "agt": 8, "ags": 8, "sep": 9, "sept": 9, "okt": 10, "nop": 11, "nov": 11,
    "des": 12, "peb": 2,
}
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTHS = {**_EN_MONTHS, **_ID_MONTHS}

_TZ_ALIASES = {
    "wib": "+07:00", "wita": "+08:00", "wit": "+09:00",
    "utc": "+00:00", "gmt": "+00:00", "z": "+00:00",
    "est": "-05:00", "edt": "-04:00", "cst": "-06:00", "cdt": "-05:00",
    "mst": "-07:00", "mdt": "-06:00", "pst": "-08:00", "pdt": "-07:00",
}

_DATE_PATTERNS = [
    # 2024-05-12T08:30:00+07:00 / 2024-05-12 08:30
    re.compile(r"(?P<y>19|20\d\d)[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})(?:[T ](?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?)?\s*(?P<tz>Z|[+-]\d{2}:?\d{2}|WIB|WITA|WIT|UTC|GMT)?", re.I),
    # 12 May 2024 / 12 Mei 2024 08:30 WIB
    re.compile(r"(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<y>19|20\d\d)(?:,?\s+(?P<H>\d{1,2}):(?P<M>\d{2}))?\s*(?P<tz>WIB|WITA|WIT|UTC|GMT|[+-]\d{2}:?\d{2})?", re.I),
    # May 12, 2024
    re.compile(r"(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<d>\d{1,2}),?\s+(?P<y>19|20\d\d)", re.I),
    # 12/05/2024 08:30
    re.compile(r"(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>19|20\d\d)(?:\s+(?P<H>\d{1,2}):(?P<M>\d{2}))?"),
]

_RELATIVE = re.compile(
    r"(?P<n>\d+)\s*(?P<unit>detik|menit|jam|hari|minggu|bulan|tahun|"
    r"second|minute|hour|day|week|month|year)s?\s*(?:yang\s+)?(?:lalu|ago)",
    re.I,
)
_RELATIVE_WORD = re.compile(r"\b(kemarin|yesterday|baru saja|just now|today|hari ini)\b", re.I)


def clean_text(value: str) -> str:
    if not value:
        return ""
    value = _INVISIBLE.sub("", value)
    value = value.replace("\u00a0", " ")
    return _WS.sub(" ", value).strip()


_TAG = re.compile(r"<[^>]{1,400}>")
_SCRIPTISH = re.compile(r"<(script|style|iframe)[^>]*>.*?</\1\s*>", re.S | re.I)


def plain(value: str) -> str:
    """Decode entities and strip markup so text is safe inside <description>."""
    if not value:
        return ""
    value = _SCRIPTISH.sub(" ", value)
    value = _TAG.sub(" ", value)
    value = unescape(value)
    return clean_text(value)


def strip_site_suffix(title: str, site_names: list[str]) -> str:
    title = clean_text(title)
    lowered = title.lower()
    for name in site_names:
        name = clean_text(name).lower()
        if not name or len(name) < 3:
            continue
        for sep in (" | ", " - ", " — ", " :: ", " » ", " · "):
            tail = sep + name
            if lowered.endswith(tail.lower()):
                return title[: -len(tail)].strip()
    return title


_TRACKING_PARAMS = {
    "source", "position", "ref", "referrer", "campaign", "cmpid", "cid", "fbclid",
    "gclid", "msclkid", "yclid", "igshid", "s", "si", "spm", "share", "shared",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_reader", "wt_mc", "at_medium", "at_campaign",
}


def canonical_link(url: str) -> str:
    """Identity of an article, ignoring query strings, fragments and slashes."""
    return re.sub(r"[?#].*$", "", url or "").rstrip("/").lower()


def _strip_tracking(url: str) -> str:
    parts = up.urlsplit(url)
    if not parts.query:
        return url
    pairs = up.parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")]
    if len(kept) == len(pairs):
        return url
    return up.urlunsplit((parts.scheme, parts.netloc, parts.path, up.urlencode(kept), ""))


def absolutize(base: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return ""
    try:
        url = up.urljoin(base, href)
    except ValueError:
        return ""
    parts = up.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return ""
    return _strip_tracking(
        up.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    )


def _apply_tz(moment: datetime, tz: str | None) -> datetime:
    if not tz:
        return moment.replace(tzinfo=timezone.utc)
    tz = tz.upper()
    if tz in _TZ_ALIASES:
        tz = _TZ_ALIASES[tz]
    if tz.startswith(("+", "-")):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        if len(body) == 4 and body.isdigit():
            delta = timedelta(hours=int(body[:2]), minutes=int(body[2:]))
            return moment.replace(tzinfo=timezone(sign * delta))
    return moment.replace(tzinfo=timezone.utc)


def _relative_moment(text: str, now: datetime) -> datetime | None:
    match = _RELATIVE.search(text)
    if match:
        amount = int(match.group("n"))
        unit = match.group("unit").lower()
        unit = {"detik": "second", "menit": "minute", "jam": "hour", "hari": "day",
                "minggu": "week", "bulan": "month", "tahun": "year"}.get(unit, unit)
        days = {"second": 0, "minute": 0, "hour": 0, "day": 1, "week": 7,
                "month": 30, "year": 365}[unit]
        if days:
            return now - timedelta(days=days * amount)
        seconds = {"second": amount, "minute": amount * 60, "hour": amount * 3600}[unit]
        return now - timedelta(seconds=seconds)
    word = _RELATIVE_WORD.search(text)
    if word:
        token = word.group(1).lower()
        if token in ("kemarin", "yesterday"):
            return now - timedelta(days=1)
        return now
    return None


def parse_date(value: str, *, now: datetime | None = None) -> datetime | None:
    """Best-effort date parsing for Indonesian and English formats."""
    if not value:
        return None
    now = now or datetime.now(timezone.utc)
    text = clean_text(value)

    iso = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass

    relative = _relative_moment(text, now)
    if relative:
        return relative.astimezone(timezone.utc)

    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groupdict()
        try:
            day = int(groups.get("d") or 1)
            year = int(groups.get("y") or 1970)
            month_raw = groups.get("m")
            month = int(month_raw) if month_raw else _MONTHS.get((groups.get("mon") or "").lower()[:9])
            if not month:
                continue
            hour = int(groups.get("H") or 0)
            minute = int(groups.get("M") or 0)
            second = int(groups.get("S") or 0)
            if not (1 <= day <= 31 and 1 <= month <= 12 and 1990 <= year <= 2100):
                continue
            moment = datetime(year, month, day, hour, minute, second)
            return _apply_tz(moment, groups.get("tz")).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


_URL_DATE = re.compile(r"/(20\d\d)/(\d{1,2})(?:/(\d{1,2}))?/")
_URL_STAMP = re.compile(r"/(20\d\d)(\d\d)(\d\d)(?:\d{6})?[-/_.]")


def date_from_url(url: str) -> datetime | None:
    match = _URL_DATE.search(url)
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3) or 1),
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass
    match = _URL_STAMP.search(url)
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass
    return None


# --------------------------------------------------------------------------
# URL quality filters
# --------------------------------------------------------------------------

_BAD_HOSTS = {
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "tiktok.com", "whatsapp.com", "wa.me", "t.me", "telegram.me", "linkedin.com",
    "pinterest.com", "threads.net", "google.com", "play.google.com",
    "apps.apple.com", "apple.com", "amazon.com",
}
_BAD_PATH = re.compile(
    r"(^/?(tag|tags|label|labels|kategori|category|categories|topik|topic|author|penulis|"
    r"page|halaman|search|pencarian|login|masuk|daftar|register|signup|subscribe|"
    r"privacy|policy|about|tentang|contact|kontak|disclaimer|sitemap|rss|feed|"
    r"index\.php|wp-admin|wp-login)(/|$))",
    re.I,
)
_BAD_SUBDOMAIN = ("event.", "promo.", "iklan.", "ads.", "adv.", "campaign.", "marketing.")
_ASSET_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|ico|css|js|pdf|zip|mp3|mp4|xml|json)$", re.I)
_CTA_TITLE = re.compile(
    r"^(lihat|baca|klik|selengkapnya|info|informasi|download|unduh|beli|pesan|daftar|"
    r"lihat info|baca juga|klik di sini|selengkapnya di|more info|read more|learn more)\b",
    re.I,
)


def _host_key(host: str) -> str:
    host = (host or "").lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def same_site(host_a: str, host_b: str) -> bool:
    a, b = _host_key(host_a), _host_key(host_b)
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def looks_like_article(url: str, base_host: str) -> bool:
    parts = up.urlsplit(url)
    host = _host_key(parts.netloc)
    if not host:
        return False
    base = _host_key(base_host)
    root_domain = ".".join(base.split(".")[-2:]) if base.count(".") >= 1 else base
    if any(host == bad or host.endswith("." + bad) for bad in _BAD_HOSTS):
        return False
    if host.startswith(_BAD_SUBDOMAIN):
        return False
    if not (host == root_domain or host.endswith("." + root_domain)):
        return False
    path = parts.path or "/"
    if path in ("", "/"):
        return bool(re.search(r"[?&](p|page_id|id|story|artikel)=", parts.query))
    if _BAD_PATH.search(path):
        return False
    if _ASSET_EXT.search(path):
        return False
    return len(path.strip("/")) >= 3


# --------------------------------------------------------------------------
# HTML scraping
# --------------------------------------------------------------------------

_IMG_ATTRS = ("src", "data-src", "data-lazy-src", "data-original", "data-url")
_ARTICLE_TYPES = {"article", "newsarticle", "blogposting", "reportagenewsarticle",
                  "analysisnewsarticle", "opinionnewsarticle", "techarticle"}


def _meta(root: Node, *names: str) -> str:
    for node in root.find_all("meta"):
        key = (node.get("property") or node.get("name") or node.get("itemprop") or "").lower()
        if key in names:
            return clean_text(node.get("content"))
    return ""


def discover(page: Node, base_url: str) -> Discovery:
    info = Discovery()
    for node in page.find_all("link"):
        rel = (node.get("rel") or "").lower()
        ctype = (node.get("type") or "").lower()
        if "alternate" in rel and ("rss" in ctype or "atom" in ctype or "xml" in ctype):
            href = absolutize(base_url, node.get("href"))
            if href and href not in info.feeds:
                info.feeds.append(href)

    title_node = page.find("title")
    info.title = clean_text(title_node.text() if title_node else "")
    info.description = _meta(page, "og:description", "description", "twitter:description")
    language = ""
    html_node = page.find("html")
    if html_node is not None:
        language = (html_node.get("lang") or "").strip()
    info.language = language[:12]

    if not info.feeds:
        for anchor in page.find_all("a"):
            href = absolutize(base_url, anchor.get("href"))
            if not href:
                continue
            lowered = href.lower()
            if re.search(r"(/feed/?$|/rss/?$|/rss\.xml$|/feed\.xml$|/atom\.xml$|/index\.xml$|feeds/posts/default)", lowered):
                if href not in info.feeds:
                    info.feeds.append(href)
            if len(info.feeds) >= 3:
                break
    return info


def _jsonld_items(page: Node, base_url: str) -> list[FeedItem]:
    items: list[FeedItem] = []
    for script in page.find_all("script"):
        if "ld+json" not in (script.get("type") or "").lower():
            continue
        raw = "".join(c for c in script.children if isinstance(c, str))
        if not raw.strip():
            continue
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for record in _walk_jsonld(data):
            kind = record.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if not any(str(k).lower() in _ARTICLE_TYPES for k in kinds if k):
                continue
            link = ""
            for key in ("url", "@id", "mainEntityOfPage"):
                value = record.get(key)
                if isinstance(value, dict):
                    value = value.get("@id") or value.get("url")
                if isinstance(value, str) and value:
                    link = absolutize(base_url, value)
                    if link:
                        break
            if not link:
                continue
            title = clean_text(record.get("headline") or record.get("name") or "")
            if not title:
                continue
            summary = clean_text(record.get("description") or "")
            image = record.get("image") or record.get("thumbnailUrl") or ""
            if isinstance(image, dict):
                image = image.get("url") or ""
            if isinstance(image, list):
                image = image[0] if image else ""
                if isinstance(image, dict):
                    image = image.get("url") or ""
            items.append(
                FeedItem(
                    title=title,
                    link=link,
                    summary=summary,
                    image=absolutize(base_url, str(image)) if image else "",
                    published=parse_date(str(record.get("datePublished") or record.get("dateModified") or "")),
                    author=_jsonld_author(record),
                )
            )
    return items


def _jsonld_author(record: dict) -> str:
    author = record.get("author") or record.get("creator") or ""
    if isinstance(author, list):
        author = author[0] if author else ""
    if isinstance(author, dict):
        author = author.get("name") or ""
    return clean_text(str(author))[:120]


def _walk_jsonld(data):
    if isinstance(data, dict):
        yield data
        for key in ("@graph", "itemListElement", "item", "mainEntity", "hasPart"):
            if key in data:
                yield from _walk_jsonld(data[key])
    elif isinstance(data, list):
        for entry in data:
            yield from _walk_jsonld(entry)


def _first_image(node: Node, base_url: str) -> str:
    for img in node.find_all("img", limit=6):
        width = (img.get("width") or "").strip()
        height = (img.get("height") or "").strip()
        if width.isdigit() and int(width) < 48 or height.isdigit() and int(height) < 48:
            continue
        for attr in _IMG_ATTRS:
            src = img.get(attr)
            if src:
                url = absolutize(base_url, src)
                if url and not re.search(r"(spacer|blank|pixel|1x1|transparent)", url, re.I):
                    return url
        srcset = img.get("srcset")
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            url = absolutize(base_url, first)
            if url:
                return url
    return ""


def _date_in(node: Node, base_url: str, now: datetime) -> datetime | None:
    for time_node in node.find_all("time", limit=3):
        for attr in ("datetime", "content", "title"):
            parsed = parse_date(time_node.get(attr), now=now)
            if parsed:
                return parsed
        parsed = parse_date(time_node.text(), now=now)
        if parsed:
            return parsed

    for meta in node.find_all("meta", limit=4):
        key = (meta.get("itemprop") or meta.get("property") or "").lower()
        if "date" in key or "time" in key:
            parsed = parse_date(meta.get("content"), now=now)
            if parsed:
                return parsed

    for klass in node.find_all("span", limit=8) + node.find_all("div", limit=8):
        classes = " ".join(klass.classes)
        if re.search(r"date|time|tanggal|waktu|published|post-meta|meta", classes, re.I):
            parsed = parse_date(klass.text()[:120], now=now)
            if parsed:
                return parsed

    own = node.text()[:200]
    parsed = parse_date(own, now=now)
    if parsed:
        return parsed
    return None


def _heading(node: Node) -> Node | None:
    for level in ("h1", "h2", "h3", "h4"):
        for heading in node.find_all(level, limit=2):
            if len(heading.text()) >= 15:
                return heading
    return None


def _summary(node: Node, title: str, limit: int = 420) -> str:
    paragraphs = []
    for paragraph in node.find_all("p", limit=4):
        text = clean_text(paragraph.text())
        if len(text) < 40 or text.strip() == title.strip():
            continue
        paragraphs.append(text)
        if sum(len(p) for p in paragraphs) >= limit:
            break
    if not paragraphs:
        body = clean_text(node.text())
        if body.lower().startswith(title.lower()):
            body = body[len(title):].strip(" -–—:|")
        paragraphs = [body[:limit]] if body else []
    joined = " ".join(paragraphs)
    if len(joined) > limit:
        cut = joined[:limit].rsplit(" ", 1)[0]
        joined = cut + "…"
    return joined


def _item_from_container(container: Node, base_url: str, now: datetime) -> FeedItem | None:
    heading = _heading(container)
    anchors = []
    for anchor in container.find_all("a", limit=25):
        href = absolutize(base_url, anchor.get("href"))
        text = clean_text(anchor.text())
        if href and len(text) >= 12:
            anchors.append((anchor, href, text))
    if not anchors:
        return None

    title = clean_text(heading.text()) if heading is not None else ""
    chosen = None
    if title:
        for anchor, href, text in anchors:
            if text == title or title in text or text in title:
                chosen = (href, text)
                break
    if chosen is None:
        best = max(anchors, key=lambda a: (len(a[2]), len(a[1])))
        chosen = (best[1], best[2])
    if not title:
        title = chosen[1]
    link = chosen[0]

    if not title or len(title) < 12:
        return None

    item = FeedItem(
        title=title,
        link=link,
        summary=_summary(container, title),
        image=_first_image(container, base_url),
        published=_date_in(container, base_url, now),
    )
    if item.published is None:
        item.published = date_from_url(link)
    return item


def _repeated_groups(page: Node) -> list[list[Node]]:
    groups: list[list[Node]] = []
    for parent in page.walk():
        if parent.tag in ("body", "html", "#document"):
            continue
        buckets: dict[str, list[Node]] = {}
        for child in parent:
            buckets.setdefault(child.signature(), []).append(child)
        for signature, members in buckets.items():
            if len(members) < 3 or len(members) > 120:
                continue
            rich = 0
            for member in members:
                headings = member.find_all("h1") + member.find_all("h2") + member.find_all("h3") + member.find_all("h4")
                long_anchor = any(len(clean_text(a.text())) >= 20 for a in member.find_all("a", limit=6))
                if headings or long_anchor:
                    rich += 1
            if rich >= max(3, int(len(members) * 0.6)):
                groups.append(members)
    # prefer the largest groups
    groups.sort(key=len, reverse=True)
    return groups[:12]


def _cluster_anchors(page: Node, base_url: str) -> list[Node]:
    buckets: dict[str, list[Node]] = {}
    for anchor in page.find_all("a"):
        href = absolutize(base_url, anchor.get("href"))
        text = clean_text(anchor.text())
        if not href or len(text) < 20:
            continue
        parts = up.urlsplit(href)
        shape = re.sub(r"\d+", "#", parts.path)
        buckets.setdefault(f"{parts.netloc}{shape}", []).append(anchor)
    ranked = sorted(buckets.values(), key=len, reverse=True)
    return ranked[0] if ranked and len(ranked[0]) >= 3 else []


def _dedupe(items: list[FeedItem]) -> list[FeedItem]:
    seen: set[str] = set()
    unique: list[FeedItem] = []
    for item in items:
        key = re.sub(r"[?#].*$", "", item.link).rstrip("/").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _score(items: list[FeedItem]) -> float:
    if not items:
        return 0.0
    dated = sum(1 for i in items if i.published) / len(items)
    summarised = sum(1 for i in items if len(i.summary) > 60) / len(items)
    return len(items) * 6 + dated * 35 + summarised * 20


def scrape(
    page: Node,
    base_url: str,
    *,
    now: datetime | None = None,
    min_items: int = 3,
    site_names: list[str] | None = None,
) -> list[FeedItem]:
    now = now or datetime.now(timezone.utc)
    site_names = site_names or []
    base_host = up.urlsplit(base_url).netloc

    candidates: list[list[FeedItem]] = []

    jsonld = [i for i in _jsonld_items(page, base_url) if looks_like_article(i.link, base_host)]
    if len(jsonld) >= min_items:
        candidates.append(jsonld)

    for node in page.find_all("article")[:80]:
        item = _item_from_container(node, base_url, now)
        if item and looks_like_article(item.link, base_host):
            candidates.append([item])
    if candidates and len(candidates[-1]) and sum(len(c) for c in candidates) >= min_items:
        merged = [i for group in candidates for i in group]
        candidates.append(merged)

    for group in _repeated_groups(page):
        items = []
        for member in group:
            item = _item_from_container(member, base_url, now)
            if item and looks_like_article(item.link, base_host):
                items.append(item)
        if len(items) >= min_items:
            candidates.append(items)

    anchors = _cluster_anchors(page, base_url)
    if anchors:
        items = []
        for anchor in anchors[:80]:
            container = anchor
            for _ in range(3):
                if container.parent is None:
                    break
                container = container.parent
            item = _item_from_container(container, base_url, now)
            if item and looks_like_article(item.link, base_host):
                items.append(item)
        if len(items) >= min_items:
            candidates.append(items)

    best: list[FeedItem] = []
    best_score = 0.0
    for group in candidates:
        group = _dedupe(group)
        score = _score(group)
        if score > best_score:
            best, best_score = group, score

    if not best:
        return []

    horizon = now + timedelta(days=3)
    cleaned: list[FeedItem] = []
    for item in best:
        item.title = strip_site_suffix(item.title, site_names)[:300]
        item.guid = item.link
        if len(item.title) < 12 or _CTA_TITLE.match(item.title):
            continue
        if item.published and item.published > horizon:
            # dates far in the future are almost always event promos
            continue
        cleaned.append(item)
    best = cleaned
    if any(i.published for i in best):
        best.sort(key=lambda i: i.published or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return best


# --------------------------------------------------------------------------
# native feed parsing
# --------------------------------------------------------------------------

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rss1": "http://purl.org/rss/1.0/",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node, *names: str) -> str:
    for child in list(node):
        if _local(child.tag) in names:
            if child.text and child.text.strip():
                return clean_text(child.text)
            if len(child):
                return clean_text(" ".join(t.text or "" for t in child.iter()))
    return ""


def _atom_link(node) -> str:
    for child in list(node):
        if _local(child.tag) == "link":
            rel = (child.get("rel") or "alternate").lower()
            if rel == "alternate" and child.get("href"):
                return child.get("href")
    for child in list(node):
        if _local(child.tag) == "link" and child.get("href"):
            return child.get("href")
    return ""


def _feed_image(node) -> str:
    for child in node.iter():
        name = _local(child.tag)
        if name in ("content", "thumbnail", "enclosure") and child.get("url"):
            kind = (child.get("type") or "").lower()
            if name != "enclosure" or kind.startswith("image") or re.search(r"\.(jpe?g|png|webp|gif)$", child.get("url", ""), re.I):
                return child.get("url")
    for child in node.iter():
        if _local(child.tag) in ("content", "description", "summary", "encoded") and child.text:
            match = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", child.text, re.I)
            if match:
                return match.group(1)
    return ""


def parse_feed(xml_text: str, base_url: str) -> tuple[list[FeedItem], dict]:
    xml_text = xml_text.lstrip("\ufeff \t\r\n")
    root = ET.fromstring(xml_text)
    meta: dict = {"title": "", "description": "", "language": ""}

    entries = [n for n in root.iter() if _local(n.tag) in ("item", "entry")]
    channel = None
    for node in root.iter():
        if _local(node.tag) in ("channel", "feed"):
            channel = node
            break
    if channel is not None:
        meta["title"] = plain(_child_text(channel, "title"))
        meta["description"] = plain(_child_text(channel, "description", "subtitle", "tagline"))
        meta["language"] = _child_text(channel, "language")

    items: list[FeedItem] = []
    for entry in entries:
        title = plain(_child_text(entry, "title"))
        link = _child_text(entry, "link") or _atom_link(entry)
        if not link:
            link = _child_text(entry, "guid", "id")
        link = absolutize(base_url, link) or link

        summary = plain(_child_text(entry, "description", "summary", "abstract"))
        content = _child_text(entry, "encoded", "content")
        published = parse_date(
            _child_text(entry, "pubdate", "published", "updated", "date", "created")
        )
        author = plain(_child_text(entry, "creator", "author", "name"))
        if not author:
            for child in list(entry):
                if _local(child.tag) == "author":
                    author = plain(_child_text(child, "name"))
                    break

        categories = [plain(c.text or "") for c in entry if _local(c.tag) == "category"]
        guid = _child_text(entry, "guid", "id") or link

        if not title or not link:
            continue
        items.append(
            FeedItem(
                title=strip_site_suffix(title, [meta["title"]])[:300],
                link=link,
                summary=summary,
                content=content,
                published=published,
                image=absolutize(base_url, _feed_image(entry)),
                author=author[:120],
                guid=guid,
                categories=[c for c in categories if c][:4],
            )
        )

    items = _dedupe(items)
    return items, meta
