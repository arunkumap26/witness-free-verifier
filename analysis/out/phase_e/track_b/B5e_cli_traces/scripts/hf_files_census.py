"""B5e step 1: per-dataset file listing for every format:agent-traces dataset plus extra name-search candidates.

Read-only HF API metadata (no data bytes). Classifies each file by basename pattern into a harness guess.
Writes meta/hf_files_census.json.
Usage: python hf_files_census.py <format_census.json> <out.json> [extra_id ...]
"""
import json, re, sys, time, urllib.request
from collections import Counter

PAT = [
    ("codex", re.compile(r"(^|/)rollout-\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-[0-9a-f-]{36}\.jsonl$")),
    ("pi", re.compile(r"(^|/)\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d(-\d{3})?Z?_[0-9a-f-]{36}\.jsonl$")),
    ("claude_code_subagent", re.compile(r"(^|/)agent-[0-9a-f]{6,}\.jsonl$")),
    ("claude_code", re.compile(r"(^|/)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$")),
    ("opencode", re.compile(r"(^|/)ses_[A-Za-z0-9]+\.json$")),
    ("cline_roo_ui", re.compile(r"(^|/)(ui_messages|api_conversation_history)\.json$")),
    ("atif", re.compile(r"(^|/)trajectory\.json$")),
    ("parquet", re.compile(r"\.parquet$")),
    ("jsonl_other", re.compile(r"\.jsonl$")),
    ("json_other", re.compile(r"\.json$")),
]

def classify(p):
    for name, rx in PAT:
        if rx.search(p):
            return name
    return "other"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research-audit"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

fmt = json.load(open(sys.argv[1], encoding="utf-8"))
out = sys.argv[2]
ids = [r["id"] for r in fmt["rows"]] + [i for i in sys.argv[3:] if i not in {r["id"] for r in fmt["rows"]}]
res = {}
for i, rid in enumerate(ids):
    e = {"id": rid, "in_format_agent_traces": rid in {r["id"] for r in fmt["rows"]}}
    try:
        d = get("https://huggingface.co/api/datasets/" + rid + "?blobs=true")
        cd = d.get("cardData") or {}
        sib = d.get("siblings", [])
        cls = Counter(); clsb = Counter()
        for s in sib:
            c = classify(s["rfilename"]); cls[c] += 1; clsb[c] += s.get("size") or 0
        e.update(sha=d.get("sha"), gated=d.get("gated"), private=d.get("private"), lastModified=(d.get("lastModified") or "")[:19],
                 card_license=cd.get("license"), license_tags=[t for t in d.get("tags", []) if t.startswith("license:")],
                 n_files=len(sib), total_bytes=sum((s.get("size") or 0) for s in sib),
                 class_counts=dict(cls), class_bytes=dict(clsb),
                 files=[{"path": s["rfilename"], "size": s.get("size"), "cls": classify(s["rfilename"]),
                         "lfs_sha256": (s.get("lfs") or {}).get("sha256")} for s in sib])
    except Exception as ex:
        e["error"] = repr(ex)
    res[rid] = e
    if i % 25 == 0:
        print(i, rid, e.get("class_counts"), e.get("error", ""), flush=True)
    time.sleep(0.2)
json.dump({"retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n": len(res), "datasets": res},
          open(out, "w", encoding="utf-8"), indent=0)
print("done", len(res))
