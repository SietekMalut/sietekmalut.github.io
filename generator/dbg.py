import sys, json
from datetime import datetime, timezone
sys.path.insert(0, '.')
import net, extract as ex
from dom import parse

for url in ["https://www.kompas.com/", "https://malutpost.id/", "https://kumparan.com/", "https://www.cnnindonesia.com/"]:
    print("="*70); print(url)
    r = net.fetch(url)
    page = parse(r.text)
    info = ex.discover(page, r.url)
    print("discovered:", info.feeds, "| title:", info.title[:60])
    items = ex.scrape(page, r.url, min_items=1)
    print("scraped:", len(items))
    for it in items[:6]:
        print("   -", it.published, "|", it.title[:70], "|", it.link[:80])
