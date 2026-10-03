"""Recon: compare the SWE-chat mirror (cfahlgren1@f6cbfbbc93) with the pinned SALT-NLP@f66cca95 tables,
plus a light look at the pinned raw transcripts/. Reads the outputs of recon_swechat_scan.py.
Writes analysis/out/recon/swechat_compare.txt."""
import glob, json, os, random, re
import pandas as pd, pyarrow.parquet as pq

D = os.path.join(os.path.dirname(__file__), "..", "out", "recon")
ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
o = open(f"{D}/swechat_compare.txt", "w", encoding="utf-8")
w = lambda *a: print(*a, file=o)
m, p = (json.load(open(f"{D}/swechat_scan_{x}.json")) for x in ("mirror", "pinned"))

w("## Side-by-side counts (mirror vs pinned)")
w(f"{'metric':45s} {'mirror':>14s} {'pinned':>14s}  same?")
for k in m:
    if k in ("label", "path") or isinstance(m[k], dict):
        continue
    w(f"{k:45s} {m[k]:>14,} {p.get(k, 'n/a'):>14,}  {'yes' if m[k] == p.get(k) else 'NO'}")
for k in ("roles", "tool_use_by_agent", "exit_code_prefix_on_results", "turn_types"):
    w(f"{k}: identical={m[k] == p[k]}")
    if m[k] != p[k]:
        for kk in sorted(set(m[k]) | set(p[k])):
            if m[k].get(kk) != p[k].get(kk):
                w(f"   {kk}: mirror {m[k].get(kk)} pinned {p[k].get(kk)}")

w("\n## Row-level diff on turn_id")
hm = pq.read_table(f"{D}/swechat_rowhash_mirror.parquet").to_pandas()
hp = pq.read_table(f"{D}/swechat_rowhash_pinned.parquet").to_pandas()
w(f"duplicate turn_id: mirror {hm.turn_id.duplicated().sum()} pinned {hp.turn_id.duplicated().sum()}")
j = hm.drop_duplicates("turn_id").merge(hp.drop_duplicates("turn_id"), on="turn_id", how="outer", suffixes=("_m", "_p"), indicator=True)
w("turn_id presence", j["_merge"].value_counts().to_dict())
b = j[j["_merge"] == "both"]
w(f"rows in both: {len(b):,}; identical content: {(b.h_content_m == b.h_content_p).sum():,}; identical other fields: {(b.h_meta_m == b.h_meta_p).sum():,}")
w(f"same row order (position-wise turn_id equal): {(hm.turn_id.values == hp.turn_id.values).sum():,} of {len(hp):,}" if len(hm) == len(hp) else "row counts differ")

w("\n## Pinned raw transcripts/")
pin = pq.read_table(f"{ROOT}/swe-chat-pinned/sessions.parquet", columns=["session_id", "transcript_path", "agent"]).to_pandas()
files = glob.glob(f"{ROOT}/swe-chat-pinned/transcripts/*.jsonl")
stems = {os.path.basename(f)[:-6] for f in files}
w(f"transcript files {len(files)}; sessions {len(pin)}")
w("transcript_path examples", pin.transcript_path.dropna().head(3).tolist())
w(f"session_ids with a transcript file named <session_id>.jsonl: {pin.session_id.isin(stems).sum()}")
missing = pin[~pin.session_id.isin(stems)]
w("sessions without such a file (session_id, agent):", missing[["session_id", "agent"]].values.tolist()[:10])
w(f"files not matching any session_id: {len(stems - set(pin.session_id))}")

# Light check of the orphan question on a seeded sample: does an orphaned result's id appear as a tool_use in the raw file?
conv = pq.ParquetFile(f"{ROOT}/swe-chat-pinned/conversations.parquet")
use, res = set(), {}
for g in range(conv.num_row_groups):
    t = conv.read_row_group(g, columns=["session_id", "role", "tool_call_id"]).to_pandas()
    for s, r, c in zip(t.session_id.values, t.role.values, t.tool_call_id.values):
        if c and r == "tool_use":
            use.add((s, c))
        elif c and r == "tool_result":
            res.setdefault(s, set()).add(c)
orph_sessions = {s: {c for c in cs if (s, c) not in use} for s, cs in res.items()}
orph_sessions = {s: v for s, v in orph_sessions.items() if v}
random.seed(20261003)
sample = random.sample(sorted(orph_sessions), min(50, len(orph_sessions)))
n_ids = found = nofile = 0
loc = {"top-level assistant": 0, "inside progress/other": 0}
for s in sample:
    f = f"{ROOT}/swe-chat-pinned/transcripts/{s}.jsonl"
    if not os.path.exists(f):
        nofile += 1
        continue
    top, nested = set(), set()
    for line in open(f, encoding="utf-8", errors="replace"):
        if "toolu_" not in line:
            continue
        ids = set(re.findall(r'"id":\s*"(toolu_[A-Za-z0-9]+)"', line))
        try:
            e = json.loads(line)
        except Exception:
            nested.update(ids)
            continue
        blocks = (e.get("message") or {}).get("content") if e.get("type") == "assistant" else None
        own = {b.get("id") for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"} if isinstance(blocks, list) else set()
        top.update(own)
        nested.update(ids - own)
    for c in orph_sessions[s]:
        n_ids += 1
        if c in top or c in nested:
            found += 1
            loc["top-level assistant" if c in top else "inside progress/other"] += 1
w(f"\norphan check, seeded sample of {len(sample)} sessions with orphans ({len(orph_sessions)} such sessions in total)")
w(f"  sessions without transcript file: {nofile}; orphan ids checked: {n_ids}; found as a tool_use id in the raw file: {found}; where: {loc}")
o.close()
print(open(f"{D}/swechat_compare.txt", encoding="utf-8").read())
