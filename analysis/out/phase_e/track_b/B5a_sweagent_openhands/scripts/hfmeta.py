"""Read-only metadata for HF datasets: info (sha, gated, license tag), recursive tree with sizes, README text.
Writes meta/<id>.json and meta/<id>.README.md. No data rows are downloaded."""
import json, os, sys, urllib.request, urllib.parse

D = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(D, "meta"), exist_ok=True)


def get(url, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": "b5a-audit"})
    b = urllib.request.urlopen(req, timeout=120).read()
    return b if raw else json.loads(b)


for ds in sys.argv[1:]:
    safe = ds.replace("/", "__")
    out = {"id": ds}
    try:
        info = get(f"https://huggingface.co/api/datasets/{ds}")
        out["sha"] = info.get("sha")
        out["gated"] = info.get("gated")
        out["private"] = info.get("private")
        out["lastModified"] = info.get("lastModified")
        out["license_tags"] = [t for t in info.get("tags", []) if t.startswith("license:")]
        out["cardData_license"] = (info.get("cardData") or {}).get("license")
        out["cardData_configs"] = (info.get("cardData") or {}).get("configs")
        out["dataset_info"] = (info.get("cardData") or {}).get("dataset_info")
    except Exception as e:
        out["info_error"] = str(e)
        print(ds, "INFO ERR", e)
        json.dump(out, open(os.path.join(D, "meta", safe + ".json"), "w"), indent=1)
        continue
    files = []
    try:
        url = f"https://huggingface.co/api/datasets/{ds}/tree/{out['sha']}?recursive=true&expand=false"
        while url:
            req = urllib.request.Request(url, headers={"User-Agent": "b5a-audit"})
            r = urllib.request.urlopen(req, timeout=120)
            files += json.loads(r.read())
            link = r.headers.get("Link")
            url = None
            if link and 'rel="next"' in link:
                url = link.split(";")[0].strip("<> ")
    except Exception as e:
        out["tree_error"] = str(e)
    out["files"] = [{"path": f["path"], "size": f.get("size"), "type": f["type"],
                     "lfs_sha256": (f.get("lfs") or {}).get("oid")} for f in files if f["type"] == "file"]
    out["total_bytes"] = sum((f.get("size") or 0) for f in out["files"])
    out["n_files"] = len(out["files"])
    try:
        rd = get(f"https://huggingface.co/datasets/{ds}/resolve/{out['sha']}/README.md", raw=True)
        open(os.path.join(D, "meta", safe + ".README.md"), "wb").write(rd)
        out["readme_bytes"] = len(rd)
    except Exception as e:
        out["readme_error"] = str(e)
    json.dump(out, open(os.path.join(D, "meta", safe + ".json"), "w"), indent=1)
    exts = {}
    for f in out["files"]:
        e = os.path.splitext(f["path"])[1]
        exts[e] = exts.get(e, 0) + 1
    print(f"{ds:60s} sha={str(out['sha'])[:10]} gated={out['gated']} lic={out['license_tags']} files={out['n_files']} "
          f"GB={out['total_bytes']/1e9:.3f} exts={exts}")
