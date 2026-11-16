import sys
sys.path.insert(0,'.')
import net, extract as ex
for u in ["https://www.cnnindonesia.com/rss","https://www.kompas.com/rss","https://www.detik.com/rss","https://www.antaranews.com/rss","https://malutpost.id/feed/","https://www.tagar.id/rss","https://kumparan.com/rss"]:
    try:
        r = net.fetch(u)
        ok = r.is_xml
        info = ""
        if ok:
            try:
                items, meta = ex.parse_feed(r.text, r.url)
                info = f"{len(items)} items | {meta['title'][:40]}"
            except Exception as e:
                info = "parse-fail " + str(e)[:50]
        print(f"{u:45} {r.status} {r.content_type[:35]:35} xml={ok} {info}")
    except Exception as e:
        print(f"{u:45} ERR {str(e)[:70]}")
