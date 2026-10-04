"""B5e HF Hub sweep: search public dataset listings for CLI coding-agent trace releases.

Read-only metadata queries against the public HF API (no auth, no downloads of data files).
Writes meta/hf_sweep.json with every hit per query (id, gated, downloads, lastModified, tags).
Usage: python hf_sweep.py <out.json> q1 q2 ...
"""
import json, sys, time, urllib.parse, urllib.request

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research-audit"})
    return json.load(urllib.request.urlopen(req, timeout=60))

out_path = sys.argv[1]
queries = sys.argv[2:]
try:
    res = json.load(open(out_path, encoding="utf-8"))
except Exception:
    res = {"queries": {}}
for q in queries:
    if q.startswith("tag:"):
        url = "https://huggingface.co/api/datasets?filter=" + urllib.parse.quote(q[4:]) + "&limit=200&full=true"
    elif q.startswith("author:"):
        url = "https://huggingface.co/api/datasets?author=" + urllib.parse.quote(q[7:]) + "&limit=200&full=true"
    else:
        url = "https://huggingface.co/api/datasets?search=" + urllib.parse.quote(q) + "&limit=200&full=true"
    try:
        hits = get(url)
        res["queries"][q] = [
            {
                "id": d["id"],
                "gated": d.get("gated"),
                "private": d.get("private"),
                "downloads": d.get("downloads"),
                "likes": d.get("likes"),
                "lastModified": (d.get("lastModified") or "")[:10],
                "license_tags": [t for t in d.get("tags", []) if t.startswith("license:")],
                "size_tags": [t for t in d.get("tags", []) if t.startswith("size_categories:")],
                "other_tags": [t for t in d.get("tags", []) if not t.startswith(("license:", "size_categories:", "region:"))][:12],
            }
            for d in hits
        ]
        print("==", q, len(hits))
        for h in res["queries"][q]:
            print("  ", h["id"], "gated=", h["gated"], "dl=", h["downloads"], h["lastModified"], h["license_tags"], h["size_tags"])
    except Exception as e:
        res["queries"][q] = {"error": repr(e)}
        print("ERR", q, e)
    time.sleep(0.5)
res["retrieved_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
json.dump(res, open(out_path, "w", encoding="utf-8"), indent=1)
