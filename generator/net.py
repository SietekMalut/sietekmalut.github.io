"""HTTP fetching with SSRF protection, redirect validation, charset detection.

Standard library only so it runs on GitHub Actions and on a plain Windows PC
without `pip install`.
"""

from __future__ import annotations

import gzip
import ipaddress
import re
import socket
import urllib.error
import urllib.parse as up
import urllib.request as ur
import zlib
from dataclasses import dataclass, field

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
    "SietekMalutRSS/1.0 (+https://sietekmalut.github.io/)"
)

MAX_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = 25

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}

_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.I
)
_META_HTTP_EQUIV = re.compile(
    rb"""content\s*=\s*["'][^"']*charset\s*=\s*([a-zA-Z0-9_\-]+)""", re.I
)


class FetchError(Exception):
    """Raised when a page cannot be retrieved safely."""


@dataclass
class Response:
    url: str
    status: int
    content_type: str
    charset: str
    body: bytes
    headers: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return decode(self.body, self.charset)

    @property
    def is_xml(self) -> bool:
        ctype = self.content_type.lower()
        if "xml" in ctype or "rss" in ctype or "atom" in ctype:
            return True
        head = self.body[:512].lstrip().lower()
        return head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<feed")


def decode(body: bytes, charset: str | None = None) -> str:
    candidates = []
    if charset:
        candidates.append(charset)
    candidates += ["utf-8", "cp1252", "latin-1"]
    for name in candidates:
        try:
            return body.decode(name, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _charset_from(headers, body: bytes) -> str:
    ctype = headers.get("Content-Type", "") or ""
    match = re.search(r"charset\s*=\s*[\"']?([\w\-]+)", ctype, re.I)
    if match:
        return match.group(1).strip().lower()
    sample = body[:8192]
    match = _META_CHARSET.search(sample) or _META_HTTP_EQUIV.search(sample)
    if match:
        return match.group(1).decode("ascii", "ignore").strip().lower()
    return ""


def _assert_public_host(url: str) -> None:
    parsed = up.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"skema URL tidak didukung: {parsed.scheme or '(kosong)'}")
    host = (parsed.hostname or "").strip().lower().strip(".")
    if not host:
        raise FetchError("URL tanpa nama host")
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        raise FetchError(f"host diblokir: {host}")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise FetchError(f"DNS gagal untuk {host}: {exc}") from exc

    if not infos:
        raise FetchError(f"DNS tidak memberi alamat untuk {host}")

    for info in infos:
        raw_ip = info[4][0].split("%")[0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise FetchError(f"alamat non-publik ditolak: {host} -> {ip}")


class _RedirectHandler(ur.HTTPRedirectHandler):
    """Validate every redirect hop instead of trusting urllib."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, *, timeout: int = TIMEOUT, max_bytes: int = MAX_BYTES) -> Response:
    if not url or not url.strip():
        raise FetchError("URL kosong")

    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url

    _assert_public_host(url)

    request = ur.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "application/rss+xml,application/atom+xml;q=0.8,*/*;q=0.7"
            ),
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        },
    )

    opener = ur.build_opener(_RedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            headers = {k: v for k, v in response.headers.items()}
            status = response.status
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} dari {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"tidak bisa menghubungi {url}: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise FetchError(f"timeout saat mengambil {url}") from exc
    except ssl.SSLError as exc:
        raise FetchError(f"masalah TLS di {url}: {exc}") from exc

    if len(raw) > max_bytes:
        raw = raw[:max_bytes]

    encoding = (headers.get("Content-Encoding") or "").lower()
    if encoding == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                pass

    return Response(
        url=final_url,
        status=status,
        content_type=headers.get("Content-Type", ""),
        charset=_charset_from(headers, raw),
        body=raw,
        headers=headers,
    )
