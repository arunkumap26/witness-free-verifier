"""B5e: fetch public HF dataset metadata (sha, gated, licence, file list with sizes) and the README head.

Read-only. No data files are downloaded here. Appends/updates meta/hf_info.json.
Usage: python hf_info.py <out.json> repo_id [repo_id ...]
"""
import json, sys, time, urllib.parse, urllib.request

def get(url, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": "research-audit"})
    r = urllib.request.urlopen(req, timeout=60)
    b = r.read()
    return b.decode("utf-8", "replace") if raw else json.loads(b)

out_path = sys.argv[1]
try:
    res = json.load(open(out_path, encoding="utf-8"))
except Exception:
    res = {}
for rid in sys.argv[2:]:
    e = {"id": rid, "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        d = get("https://huggingface.co/api/datasets/" + rid + "?blobs=true")
        cd = d.get("cardData") or {}
        sib = d.get("siblings", [])
        e.update(
            sha=d.get("sha"), gated=d.get("gated"), private=d.get("private"), disabled=d.get("disabled"),
            lastModified=d.get("lastModified"), createdAt=d.get("createdAt"),
            card_license=cd.get("license"), card_license_name=cd.get("license_name"), card_license_link=cd.get("license_link"),
            license_tags=[t for t in d.get("tags", []) if t.startswith("license:")],
            tags=[t for t in d.get("tags", []) if not t.startswith("region:")][:30],
            n_files=len(sib), total_bytes=sum((s.get("size") or 0) for s in sib),
            files=[{"path": s["rfilename"], "size": s.get("size"), "lfs_sha256": (s.get("lfs") or {}).get("sha256")} for s in sib[:400]],
            card_configs=cd.get("configs"),
        )
    except Exception as ex:
        e["error_meta"] = repr(ex)
    try:
        txt = get("https://huggingface.co/datasets/" + rid + "/raw/main/README.md", raw=True)
        e["readme_head"] = txt[:6000]
        e["readme_len"] = len(txt)
    except Exception as ex:
        e["readme_error"] = repr(ex)
    res[rid] = e
    print("==", rid, "sha", e.get("sha"), "gated", e.get("gated"), "lic", e.get("card_license"), e.get("license_tags"),
          "files", e.get("n_files"), "bytes", e.get("total_bytes"), e.get("error_meta", ""), e.get("readme_error", ""))
    for f in (e.get("files") or [])[:12]:
        print("     ", f["path"], f["size"])
    time.sleep(0.3)
json.dump(res, open(out_path, "w", encoding="utf-8"), indent=1)
