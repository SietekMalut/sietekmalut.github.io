import sys
from datetime import datetime, timezone
sys.path.insert(0,'.')
import generate
now = datetime.now(timezone.utc).replace(microsecond=0)
for u in ["https://www.cnnindonesia.com/","https://indotimur.com/","https://maluttoday.com/","https://poskomalut.com/","https://malutsatu.com/","https://malutpost.id/","https://www.tagar.id/","https://www.detik.com/","https://www.antaranews.com/","https://www.kompas.com/"]:
    try:
        items, mode, meta, final = generate.collect({"url":u,"name":u}, {"limit":30}, now)
        top = items[0] if items else None
        print(f"{u:34} {mode:6} {len(items):3}  {str(top.published)[:19] if top else '':19}  {(top.title[:55] if top else '')}")
    except Exception as e:
        print(f"{u:34} ERR    {str(e)[:80]}")
