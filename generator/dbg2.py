import sys, collections, re
sys.path.insert(0, '.')
import net
from dom import parse, Node
r = net.fetch("https://malutpost.id/")
page = parse(r.text)
print("len html", len(r.text))
# count anchors with text
anchors = [(a.get("href"), a.text()[:60]) for a in page.find_all("a")]
print("anchors", len(anchors))
for h,t in anchors[:25]: print("  ", t, "|", h[:80])
print("--- repeated groups ---")
for parent in page.walk():
    kids = [c for c in parent if isinstance(c, Node)]
    if len(kids) < 3: continue
    buckets = collections.Counter(k.signature() for k in kids)
    for sig, n in buckets.most_common(2):
        if n >= 3:
            print(n, sig, "| sample text:", [k.text()[:40] for k in kids if k.signature()==sig][:2])
