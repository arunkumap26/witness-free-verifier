"""Split hygiene disclosure: which aiv_cu splits (A, B, E, H, none) the B2a raw-file scans touched.
The scans read the first 20,000 Gemini rows (rows carrying agent_messages.responseId) of computer_use_turns.jsonl.gz in
file order, without split filtering. Counts sessions and rows per split. Aggregates only."""
import gzip, json, collections, os
AN = r"C:\Swarms\.claude\worktrees\analysis\analysis"
ab = json.load(open(os.path.join(AN, "cache", "samples", "aiv_cu.json"), encoding="utf-8"))
eh = json.load(open(os.path.join(AN, "cache", "samples", "aiv_cu_EH.json"), encoding="utf-8"))
split = {}
for k in ("A", "B"):
    for s in ab[k]: split[s] = k
for k in ("E", "H"):
    for s in eh[k]: split[s] = k
rows = collections.Counter(); sess = collections.defaultdict(set); n = 0
with gzip.open(r"C:\Swarms\data\ai-village\computer_use_turns.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        if "responseId" not in line:
            continue
        d = json.loads(line); am = d.get("agent_messages")
        if not isinstance(am, dict) or not am.get("responseId"):
            continue
        sp = split.get(d["session_id"], "none"); rows[sp] += 1; sess[sp].add(d["session_id"]); n += 1
        if n >= 20000:
            break
print(json.dumps({"gemini_rows_scanned": n, "rows_by_split": dict(rows), "sessions_by_split": {k: len(v) for k, v in sess.items()}}, indent=1))
