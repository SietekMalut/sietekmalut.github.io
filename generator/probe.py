import sys, json
from datetime import datetime, timezone
sys.path.insert(0, '.')
import generate, net
from concurrent.futures import ThreadPoolExecutor

urls = [
 "https://www.detik.com/",
 "https://www.kompas.com/",
 "https://www.cnnindonesia.com/",
 "https://www.antaranews.com/",
 "https://malutpost.id/",
 "https://www.kabarmalut.co.id/",
 "https://beritamalut.co.id/",
 "https://www.tempo.co/",
 "https://kumparan.com/",
 "https://www.tagar.id/",
]
defaults = {"limit": 5}
now = datetime.now(timezone.utc)
def probe(u):
    src = {"url": u, "name": u}
    try:
        items, mode, meta, final = generate.collect(src, defaults, now)
        top = items[0] if items else None
        return (u, mode, len(items), (top.title[:50] if top else ""), (str(top.published) if top else ""))
    except Exception as e:
        return (u, "ERR", 0, str(e)[:80], "")
with ThreadPoolExecutor(max_workers=5) as p:
    for row in p.map(probe, urls):
        print(" | ".join(str(x) for x in row))
