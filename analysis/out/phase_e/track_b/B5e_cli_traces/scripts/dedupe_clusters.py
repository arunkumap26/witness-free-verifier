"""B5e: cluster open datasets by overlap of native session-file content hashes (LFS sha256, else path+size).
A dataset whose native files are >=90% contained in an earlier-created dataset's set is marked a copy.
Writes census/dedupe_clusters.json."""
import json, sys
D = json.load(open(sys.argv[1], encoding="utf-8"))["datasets"]
NAT = {"claude_code", "claude_code_subagent", "codex", "pi", "opencode"}
sets = {}
for rid, e in D.items():
    if "error" in e or e.get("gated"): continue
    s = {(f.get("lfs_sha256") or f"{f['path'].rsplit('/',1)[-1]}:{f['size']}") for f in e["files"] if f["cls"] in NAT}
    if s: sets[rid] = s
order = sorted(sets, key=lambda r: (D[r].get("lastModified") or "", r))
canon, copies = [], {}
for r in order:
    for c in canon:
        inter = len(sets[r] & sets[c])
        if inter >= 0.9 * len(sets[r]):
            copies[r] = {"copy_of": c, "overlap": inter, "n": len(sets[r])}; break
    else:
        canon.append(r)
# global distinct native files
allh = set().union(*sets.values()) if sets else set()
json.dump({"n_with_native": len(sets), "n_canonical": len(canon), "n_copies": len(copies), "distinct_native_files_all_open": len(allh),
           "canonical": canon, "copies": copies}, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
print("with native", len(sets), "canonical", len(canon), "copies", len(copies), "distinct native files", len(allh))
