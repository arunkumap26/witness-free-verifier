"""B5e pinned downloader (data only; nothing downloaded is executed).

For each (corpus, repo, sha, include-regex) in the plan:
  1. list the repo's files AT THE PINNED SHA via the public HF API;
  2. check caps BEFORE downloading: shared total under C:/Swarms/data/acquired must stay <= 25e9 bytes, and the
     corpus directory <= 5e9 bytes; if either would be exceeded, the repo is skipped and recorded as LISTED;
  3. stream each file from /resolve/<sha>/<path>, hashing sha256 on the fly; LFS files are checked against the Hub's
     LFS sha256; append-only (an existing file with the same sha256 is kept, a differing one is never overwritten);
  4. write <dest>/_b5e_manifest.json (url, size, sha256, lfs match) and append a row to the global manifest.
Usage: python pinned_dl.py <plan.json> <global_manifest.json>
"""
import hashlib, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error

ROOT = "C:/Swarms/data/acquired"
TOTAL_CAP, CORPUS_CAP = 25_000_000_000, 5_000_000_000


def dir_bytes(p):
    t = 0
    for dp, dn, fn in os.walk(p):
        for f in fn:
            try:
                t += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return t


def api(url):
    for k in range(6):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research-audit"}), timeout=120).read())
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(15 * (k + 1)); continue
            raise
    raise RuntimeError("429 persisted")


def fetch(url, dest):
    tmp = dest + ".part"
    for k in range(6):
        try:
            h = hashlib.sha256(); n = 0
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research-audit"}), timeout=600) as r, open(tmp, "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    h.update(b); f.write(b); n += len(b)
            os.replace(tmp, dest)
            return h.hexdigest(), n
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(15 * (k + 1)); continue
            raise
    raise RuntimeError("429 persisted")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


plan = json.load(open(sys.argv[1], encoding="utf-8"))
gpath = sys.argv[2]
try:
    G = json.load(open(gpath, encoding="utf-8"))
except Exception:
    G = {"repos": []}
done = {(r["repo"], r["sha"]) for r in G["repos"] if r.get("status") == "DOWNLOADED"}
for item in plan:
    corpus, repo, sha = item["corpus"], item["repo"], item["sha"]
    inc = re.compile(item.get("include", ".*"))
    if (repo, sha) in done:
        print("skip (already)", repo); continue
    rec = {"corpus": corpus, "repo": repo, "sha": sha, "include": item.get("include", ".*"), "licence": item.get("licence"),
           "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        meta = api(f"https://huggingface.co/api/datasets/{repo}/revision/{sha}?blobs=true")
        files = [s for s in meta.get("siblings", []) if inc.search(s["rfilename"]) and s["rfilename"] != ".gitattributes"]
        want = sum(s.get("size") or 0 for s in files)
        cdir = os.path.join(ROOT, corpus)
        tot, cb = dir_bytes(ROOT), dir_bytes(cdir) if os.path.isdir(cdir) else 0
        rec.update(n_files=len(files), bytes_planned=want, acquired_total_before=tot, corpus_bytes_before=cb)
        if tot + want > TOTAL_CAP or cb + want > CORPUS_CAP:
            rec["status"] = "LISTED_CAP"; G["repos"].append(rec); print("CAP", repo, tot, cb, want); continue
        dest_root = os.path.join(cdir, repo.replace("/", "__") + "@" + sha[:8])
        mani = []
        for s in files:
            p = s["rfilename"]; dest = os.path.join(dest_root, *p.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            url = f"https://huggingface.co/datasets/{repo}/resolve/{sha}/{urllib.parse.quote(p)}"
            lfs = (s.get("lfs") or {}).get("sha256")
            if os.path.exists(dest):
                hx, n = sha256_file(dest), os.path.getsize(dest)
                state = "existing_kept"
            else:
                hx, n = fetch(url, dest); state = "downloaded"
            mani.append({"path": p, "url": url, "size": n, "hub_size": s.get("size"), "sha256": hx, "lfs_sha256": lfs,
                         "lfs_match": (hx == lfs) if lfs else None, "state": state})
        json.dump({"repo": repo, "revision": sha, "licence": item.get("licence"), "files": mani,
                   "note": "B5e download; data only, never executed; append-only"},
                  open(os.path.join(dest_root, "_b5e_manifest.json"), "w", encoding="utf-8"), indent=1)
        rec.update(status="DOWNLOADED", dest=dest_root, bytes=sum(m["size"] for m in mani),
                   lfs_checked=sum(1 for m in mani if m["lfs_sha256"]), lfs_mismatch=sum(1 for m in mani if m["lfs_match"] is False),
                   size_mismatch=sum(1 for m in mani if m["hub_size"] is not None and m["size"] != m["hub_size"]),
                   manifest=os.path.join(dest_root, "_b5e_manifest.json"))
        print("OK", repo, rec["bytes"], "lfs_mismatch", rec["lfs_mismatch"], "size_mismatch", rec["size_mismatch"], flush=True)
    except Exception as ex:
        rec["status"] = "ERROR"; rec["error"] = repr(ex); print("ERR", repo, ex, flush=True)
    rec["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    G["repos"].append(rec)
    json.dump(G, open(gpath, "w", encoding="utf-8"), indent=1)
json.dump(G, open(gpath, "w", encoding="utf-8"), indent=1)
