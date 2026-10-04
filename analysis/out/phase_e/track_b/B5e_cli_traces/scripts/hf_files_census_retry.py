"""B5e step 1b: re-fetch census entries that hit HTTP 429, with backoff. Same classification as hf_files_census.py."""
import json, sys, time, urllib.request, urllib.error
from collections import Counter
sys.argv_saved = sys.argv
from hf_files_census_lib import classify
path = sys.argv[1]
D = json.load(open(path, encoding="utf-8"))
def get(url):
    for k in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-audit"})
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(10 * (k + 1)); continue
            raise
    raise RuntimeError("429 persisted")
for rid, e in D["datasets"].items():
    if "error" not in e: continue
    try:
        d = get("https://huggingface.co/api/datasets/" + rid + "?blobs=true")
        cd = d.get("cardData") or {}
        sib = d.get("siblings", [])
        cls = Counter(); clsb = Counter()
        for s in sib:
            c = classify(s["rfilename"]); cls[c] += 1; clsb[c] += s.get("size") or 0
        e.pop("error")
        e.update(sha=d.get("sha"), gated=d.get("gated"), private=d.get("private"), lastModified=(d.get("lastModified") or "")[:19],
                 card_license=cd.get("license"), license_tags=[t for t in d.get("tags", []) if t.startswith("license:")],
                 n_files=len(sib), total_bytes=sum((s.get("size") or 0) for s in sib),
                 class_counts=dict(cls), class_bytes=dict(clsb),
                 files=[{"path": s["rfilename"], "size": s.get("size"), "cls": classify(s["rfilename"]),
                         "lfs_sha256": (s.get("lfs") or {}).get("sha256")} for s in sib])
        print("ok", rid, dict(cls))
    except Exception as ex:
        e["error"] = repr(ex); print("ERR", rid, ex)
    time.sleep(1.5)
json.dump(D, open(path, "w", encoding="utf-8"), indent=0)
