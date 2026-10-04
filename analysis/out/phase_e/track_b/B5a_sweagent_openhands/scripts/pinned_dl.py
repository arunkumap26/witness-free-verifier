"""Pinned HF dataset downloader that only fetches files missing locally (keeps resolver requests low).
Uses the tree listing saved by hfmeta.py (meta/<repo>.json: full sha, paths, sizes, LFS sha256).
Verifies size for every file and sha256 for LFS files; writes a manifest with sha256 of every file.
Append-only: never deletes or overwrites a file whose size already matches. Backs off on HTTP 429.
Usage: pinned_dl.py <repo_id> <dest_dir> <cap_bytes_total_acquired> [glob ...]"""
import json, os, sys, time, hashlib, fnmatch, urllib.request, urllib.error

D = os.path.dirname(os.path.abspath(__file__))
repo, dest, cap = sys.argv[1], sys.argv[2], int(sys.argv[3])
globs = sys.argv[4:]
meta = json.load(open(os.path.join(D, "meta", repo.replace("/", "__") + ".json")))
sha = meta["sha"]
files = [f for f in meta["files"] if not globs or any(fnmatch.fnmatch(f["path"], g) for g in globs)]
ACQ = os.path.dirname(os.path.abspath(dest))


def du(p):
    t = 0
    for r, _, fs in os.walk(p):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return t


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


need = sum(f["size"] for f in files if not (os.path.exists(os.path.join(dest, f["path"])) and
                                           os.path.getsize(os.path.join(dest, f["path"])) == f["size"]))
used = du(ACQ)
print(f"repo={repo}@{sha} files={len(files)} need_bytes={need} acquired_used={used} cap={cap}", flush=True)
if used + need > cap:
    print("CAP WOULD BE EXCEEDED; aborting", flush=True)
    sys.exit(2)
manifest = []
for f in files:
    lp = os.path.join(dest, f["path"])
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    if not (os.path.exists(lp) and os.path.getsize(lp) == f["size"]):
        if os.path.exists(lp):
            print("size mismatch on existing partial file, writing .part alongside:", lp, flush=True)
        url = f"https://huggingface.co/datasets/{repo}/resolve/{sha}/{f['path']}"
        for attempt in range(40):
            try:
                tmp = lp + ".part"
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "b5a-audit"}), timeout=600) as r, open(tmp, "wb") as o:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        o.write(b)
                if os.path.getsize(tmp) != f["size"]:
                    raise IOError(f"size {os.path.getsize(tmp)} != {f['size']}")
                if os.path.exists(lp):
                    raise IOError("refusing to overwrite existing file " + lp)
                os.replace(tmp, lp)
                break
            except urllib.error.HTTPError as e:
                wait = 70 if e.code == 429 else 20
                print(f"HTTP {e.code} on {f['path']} attempt {attempt}; sleep {wait}", flush=True)
                time.sleep(wait)
            except Exception as e:
                print(f"ERR {e} on {f['path']} attempt {attempt}; sleep 20", flush=True)
                time.sleep(20)
        else:
            print("GAVE UP", f["path"], flush=True)
            continue
    h = sha256(lp)
    ok = (f.get("lfs_sha256") is None) or (h == f["lfs_sha256"])
    manifest.append({"path": f["path"], "size": f["size"], "sha256": h, "lfs_sha256_expected": f.get("lfs_sha256"), "sha256_ok": ok})
    if not ok:
        print("SHA256 MISMATCH", f["path"], flush=True)
mf = {"repo": repo, "revision": sha, "source": f"https://huggingface.co/datasets/{repo}/tree/{sha}",
      "license_tags": meta.get("license_tags"), "gated": meta.get("gated"), "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
      "include_globs": globs or None, "n_files": len(manifest), "total_bytes": sum(m["size"] for m in manifest),
      "all_sha256_ok": all(m["sha256_ok"] for m in manifest), "files": manifest}
json.dump(mf, open(os.path.join(dest, "_b5a_manifest.json"), "w"), indent=1)
print(f"DONE files={len(manifest)} bytes={mf['total_bytes']} all_sha256_ok={mf['all_sha256_ok']}", flush=True)
