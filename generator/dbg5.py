import sys
from datetime import datetime, timezone
sys.path.insert(0,'.')
import generate, render, extract as ex
from pathlib import Path

feeds = Path("..")/"feeds"
now = datetime.now(timezone.utc).replace(microsecond=0)
for slug in ["malutpost","kompas"]:
    src = [s for s in generate.load_config()["sources"] if s["slug"]==slug][0]
    prev = render.parse_own_feed((feeds/f"{slug}.xml").read_text(encoding="utf-8"))
    def oldfp(r):
        m = ex.parse_date(r.get("published",""))
        return f"{generate.link_key(r['link'])}|{r.get('title','').strip()}|{m.isoformat() if m else ''}"
    items, mode, meta, final = generate.collect(src, generate.load_config()["defaults"], now)
    print("="*60, slug, mode, len(items), "prev", len(prev))
    for r in prev[:3]: print("  OLD:", oldfp(r)[:150])
    for i in items[:3]: print("  NEW:", i.fingerprint()[:150])
    print("  raw pubDate:", prev[0].get("published"))
    print("  parsed:", ex.parse_date(prev[0].get("published")))
