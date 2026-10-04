"""B5e: enumerate every public HF dataset carrying format:agent-traces (the Hub's native trace-viewer format),
following Link-header pagination. Read-only metadata. Writes meta/hf_format_agent_traces.json.
"""
import json, re, sys, time, urllib.request

out = sys.argv[1]
url = "https://huggingface.co/api/datasets?filter=format:agent-traces&limit=1000&full=true"
rows, pages = [], 0
while url and pages < 50:
    req = urllib.request.Request(url, headers={"User-Agent": "research-audit"})
    r = urllib.request.urlopen(req, timeout=120)
    batch = json.loads(r.read())
    pages += 1
    for d in batch:
        rows.append({
            "id": d["id"], "gated": d.get("gated"), "private": d.get("private"), "downloads": d.get("downloads"),
            "likes": d.get("likes"), "lastModified": (d.get("lastModified") or "")[:10], "createdAt": (d.get("createdAt") or "")[:10],
            "license_tags": [t for t in d.get("tags", []) if t.startswith("license:")],
            "size_tags": [t for t in d.get("tags", []) if t.startswith("size_categories:")],
            "format_tags": [t for t in d.get("tags", []) if t.startswith("format:")],
        })
    link = r.headers.get("Link") or ""
    m = re.search(r'<([^>]+)>;\s*rel="next"', link)
    url = m.group(1) if m else None
    time.sleep(0.5)
res = {"query": "filter=format:agent-traces", "pages": pages, "n": len(rows),
       "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": rows}
json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
from collections import Counter
print("n", len(rows), "pages", pages)
print("gated", Counter(str(r["gated"]) for r in rows))
print("licence", Counter((r["license_tags"] or ["none"])[0] for r in rows).most_common(20))
print("ungated+licensed", sum(1 for r in rows if not r["gated"] and r["license_tags"] and r["license_tags"][0] not in ("license:other", "license:unknown")))
