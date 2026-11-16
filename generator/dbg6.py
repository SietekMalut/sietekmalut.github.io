import sys, json, difflib
from datetime import datetime, timezone
sys.path.insert(0,'.')
import generate, render, extract as ex
from pathlib import Path
feeds = Path("..")/"feeds"
src = [s for s in generate.load_config()["sources"] if s["slug"]=="detik"][0]
prev = render.parse_own_feed((feeds/"detik.xml").read_text(encoding="utf-8"))
now = datetime.now(timezone.utc).replace(microsecond=0)
items, mode, meta, final = generate.collect(src, {}, now)
def fp_old(r):
    m = ex.parse_date(r.get("published",""))
    return f"{ex.canonical_link(r['link'])}|{r.get('title','').strip()}|{m.isoformat() if m else ''}"
a = [fp_old(r) for r in prev]; b = [i.fingerprint() for i in items]
print("prev", len(a), "new", len(b))
for line in list(difflib.unified_diff(a,b,lineterm="",n=0))[:25]: print(line[:180])
