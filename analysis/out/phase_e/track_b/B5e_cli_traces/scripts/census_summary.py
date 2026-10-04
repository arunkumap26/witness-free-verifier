"""B5e: summarise meta/hf_files_census.json by harness class x licence status. Writes census/hf_census_summary.json."""
import json, sys
from collections import Counter, defaultdict
D = json.load(open(sys.argv[1], encoding="utf-8"))["datasets"]
OK = {"mit", "apache-2.0", "cc-by-4.0", "cc0-1.0", "bsd-3-clause", "agpl-3.0", "cc-by-sa-4.0", "odc-by", "cdla-permissive-2.0", "gpl-3.0", "bsd-2-clause", "unlicense"}
NC = {"cc-by-nc-4.0", "cc-by-nc-sa-4.0"}
def lic_status(e):
    t = [x.split(":", 1)[1] for x in e.get("license_tags", [])]
    if not t: return "none"
    if t[0] in OK: return "permissive_or_copyleft"
    if t[0] in NC: return "noncommercial"
    return "other_or_unknown"
HARN = ["claude_code", "claude_code_subagent", "codex", "pi", "opencode", "cline_roo_ui", "atif", "jsonl_other", "json_other", "parquet"]
summ = {"n_datasets": len(D), "n_errors": sum(1 for e in D.values() if "error" in e)}
by = defaultdict(lambda: Counter())
gated = Counter()
for rid, e in D.items():
    if "error" in e: continue
    ls = lic_status(e); g = "gated" if e.get("gated") else "open"
    gated[(g, ls)] += 1
    for h in HARN:
        n = (e.get("class_counts") or {}).get(h, 0)
        if n:
            by[h][f"{g}|{ls}|datasets"] += 1
            by[h][f"{g}|{ls}|files"] += n
            by[h][f"{g}|{ls}|bytes"] += (e.get("class_bytes") or {}).get(h, 0)
summ["datasets_by_gate_and_licence"] = {f"{a}|{b}": c for (a, b), c in gated.items()}
summ["by_harness_class"] = {h: dict(by[h]) for h in HARN}
# list of open, licensed datasets with any native CLI session files
rows = []
for rid, e in D.items():
    if "error" in e or e.get("gated"): continue
    cc = e.get("class_counts") or {}
    nat = {h: cc.get(h, 0) for h in ["claude_code", "claude_code_subagent", "codex", "pi", "opencode", "cline_roo_ui", "atif"] if cc.get(h)}
    if not nat: continue
    rows.append({"id": rid, "licence": (e.get("license_tags") or ["none"])[0], "status": lic_status(e), "native_files": nat,
                 "total_bytes": e.get("total_bytes"), "sha": e.get("sha"), "lastModified": e.get("lastModified")})
rows.sort(key=lambda r: (r["status"] != "permissive_or_copyleft", -sum(r["native_files"].values())))
summ["open_datasets_with_native_cli_files"] = rows
json.dump(summ, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
print(json.dumps({k: summ[k] for k in ["n_datasets", "n_errors", "datasets_by_gate_and_licence"]}, indent=1))
for h in HARN: print(h, dict(by[h]))
print("open datasets with native cli files:", len(rows), "of which licensed:", sum(1 for r in rows if r["status"] in ("permissive_or_copyleft",)))
for r in rows:
    if r["status"] == "permissive_or_copyleft": print("  ", r["id"], r["licence"], r["native_files"], r["total_bytes"])
