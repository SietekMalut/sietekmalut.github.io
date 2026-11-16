import sys
from datetime import datetime, timezone
sys.path.insert(0,'.')
import generate, render, extract as ex
from pathlib import Path
feeds = Path("..")/"feeds"
src = [s for s in generate.load_config()["sources"] if s["slug"]=="detik"][0]
now = datetime.now(timezone.utc).replace(microsecond=0)
a,_,_,_ = generate.collect(src, {}, now)
b,_,_,_ = generate.collect(src, {}, now)
ka = {ex.canonical_link(i.link) for i in a}; kb = {ex.canonical_link(i.link) for i in b}
print("A", len(ka), "B", len(kb), "onlyA", len(ka-kb), "onlyB", len(kb-ka))
for k in list(ka-kb)[:5]: print("  onlyA", k)
for k in list(kb-ka)[:5]: print("  onlyB", k)
prev = render.parse_own_feed((feeds/"detik.xml").read_text(encoding="utf-8"))
kp = {ex.canonical_link(r["link"]) for r in prev}
print("prev", len(kp), "in prev not in A", len(kp-ka), "in A not prev", len(ka-kp))
for k in list(ka-kp)[:8]: print("  new-vs-prev", k)
