"""Read-only HF Hub metadata queries (no data download). Usage: python hfapi.py <out.json> <url>"""
import json, sys, urllib.request

out, url = sys.argv[1], sys.argv[2]
req = urllib.request.Request(url, headers={"User-Agent": "b5a-audit"})
with urllib.request.urlopen(req, timeout=60) as r:
    body = r.read()
open(out, "wb").write(body)
try:
    d = json.loads(body)
    print(type(d).__name__, len(d) if hasattr(d, "__len__") else "")
except Exception as e:
    print("non-json", len(body))
