"""B5e: download one GitHub release asset (data only) with cap checks and sha256 verification against the
GitHub-published asset digest. Append-only. Usage: python dl_github_release.py <url> <expected_sha256> <size> <dest_dir> <manifest.json>"""
import hashlib, json, os, sys, time, urllib.request
url, exp, size, dest_dir, mpath = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
ROOT = "C:/Swarms/data/acquired"
def dir_bytes(p):
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, dn, fn in os.walk(p) for f in fn) if os.path.isdir(p) else 0
tot = dir_bytes(ROOT); corp = dir_bytes(os.path.dirname(dest_dir.rstrip("/\\")))
rec = {"url": url, "expected_sha256": exp, "size": size, "acquired_total_before": tot, "corpus_bytes_before": corp,
       "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
if tot + size > 25_000_000_000 or corp + size > 5_000_000_000:
    rec["status"] = "LISTED_CAP"
else:
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, url.rsplit("/", 1)[1])
    if os.path.exists(dest):
        h = hashlib.sha256(open(dest, "rb").read()).hexdigest(); rec["state"] = "existing_kept"
    else:
        h = hashlib.sha256()
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research-audit"}), timeout=900) as r, open(dest + ".part", "wb") as f:
            for b in iter(lambda: r.read(1 << 20), b""):
                h.update(b); f.write(b)
        h = h.hexdigest(); os.replace(dest + ".part", dest); rec["state"] = "downloaded"
    rec.update(status="DOWNLOADED", dest=dest, sha256=h, sha256_match=(h == exp), bytes=os.path.getsize(dest))
rec["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
try:
    M = json.load(open(mpath, encoding="utf-8"))
except Exception:
    M = {"assets": []}
M["assets"].append(rec); json.dump(M, open(mpath, "w", encoding="utf-8"), indent=1)
print(rec)
