"""A small, forgiving HTML tree builder built on html.parser.

It is intentionally not a full DOM: enough structure to group repeated blocks
and read text, attributes and nesting. Malformed markup is tolerated by closing
whatever is still open when an end tag does not match.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "canvas"}

BLOCK = {
    "address", "article", "aside", "blockquote", "div", "dl", "dd", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}

# Tags that may legally stay open when a sibling of the same kind starts.
AUTO_CLOSE = {"li": {"li"}, "p": {"p"}, "td": {"td", "th"}, "th": {"td", "th"}, "tr": {"tr"}}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list = []
        self.parent = parent

    # -- attributes ---------------------------------------------------------
    def get(self, name: str, default: str = "") -> str:
        value = self.attrs.get(name)
        return default if value is None else value

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").lower().split())

    @property
    def id(self) -> str:
        return (self.attrs.get("id") or "").lower()

    # -- traversal ----------------------------------------------------------
    def __iter__(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child

    def walk(self):
        for child in self:
            yield child
            yield from child.walk()

    def find_all(self, tag=None, limit: int | None = None):
        found = []
        for node in self.walk():
            if tag is None or node.tag == tag:
                found.append(node)
                if limit and len(found) >= limit:
                    break
        return found

    def find(self, tag=None):
        for node in self.walk():
            if tag is None or node.tag == tag:
                return node
        return None

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    # -- text ---------------------------------------------------------------
    def text(self, sep: str = " ") -> str:
        parts: list[str] = []

        def collect(node: Node):
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                else:
                    if child.tag in SKIP:
                        continue
                    if child.tag in BLOCK:
                        parts.append(sep)
                    collect(child)
                    if child.tag in BLOCK:
                        parts.append(sep)

        collect(self)
        joined = "".join(parts)
        return " ".join(joined.split())

    def own_text(self) -> str:
        return " ".join(" ".join(c for c in self.children if isinstance(c, str)).split())

    def signature(self) -> str:
        """Structural fingerprint used to group repeated list items.

        CMS templates vary per item in classes such as ``post-1835``,
        ``category-berita`` or ``gb-container-ed66b9fb``; those must not split
        a list into singleton groups.
        """
        volatile = (
            "post-", "page-", "category-", "tag-", "type-", "format-", "status-",
            "attachment-", "author-", "hentry", "has-post-thumbnail", "sticky",
        )
        stable = set()
        for name in self.classes:
            if re.search(r"\d", name):
                continue
            if name.startswith(volatile):
                continue
            if len(name) > 3 and re.search(r"[a-f0-9]{6,}$", name):
                continue
            stable.add(name)
        return f"{self.tag}|{'.'.join(sorted(stable))}|{self.get('role')}|{self.get('itemtype')}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.tag} {self.signature()}>"


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack = [self.root]
        self.skip_depth = 0

    # -- helpers ------------------------------------------------------------
    def _append(self, node: Node):
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)

    # -- parser hooks -------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SKIP:
            if tag in VOID:
                return
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag in AUTO_CLOSE:
            closers = AUTO_CLOSE[tag]
            for index in range(len(self.stack) - 1, 0, -1):
                if self.stack[index].tag in closers:
                    del self.stack[index:]
                    break

        node = Node(tag, {k.lower(): (v or "") for k, v in attrs})
        self._append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if self.skip_depth or tag in SKIP:
            return
        self._append(Node(tag, {k.lower(): (v or "") for k, v in attrs}))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP:
            if not tag in VOID and self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return

        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return
        # Unmatched end tag: ignore it rather than corrupting the tree.

    def handle_data(self, data):
        if self.skip_depth or not data:
            return
        if data.strip():
            self.stack[-1].children.append(data)


def parse(html: str) -> Node:
    builder = _Builder()
    try:
        builder.feed(html)
        builder.close()
    except Exception:  # html.parser is tolerant; keep whatever was built
        pass
    return builder.root
