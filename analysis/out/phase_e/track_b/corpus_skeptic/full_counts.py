"""Corpus skeptic: full-population structural counts for the small CLI corpora and TraceLab, to check the headline
counts in CORPUS_INVENTORY.md 1.3 (sessions, tool calls, joins). Reuses the parsers in field_audit.py (this
directory), which were written independently of the B5 scripts. Structural only: no latency statistics.

Run:  PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/corpus_skeptic/full_counts.py
Out:  analysis/out/phase_e/track_b/corpus_skeptic/full_counts.json
"""
import collections
import glob
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_audit as fa  # noqa: E402

A = fa.A
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "full_counts.json")
res = {}

t = fa.Tally()
files = glob.glob(A + "/cli-claude-code-hf/**/*.jsonl", recursive=True)
fa.audit_cc_files(files, t)
sess = set()
for f in files:
    for o in fa.jl(f):
        if isinstance(o, dict) and o.get("sessionId"):
            sess.add(o["sessionId"])
res["cli-claude-code-hf"] = {"files": len(files), "distinct_sessionIds": len(sess), "tally": t.out()}

t = fa.Tally()
files = glob.glob(A + "/cli-pi-hf/**/*.jsonl", recursive=True)
fa.audit_pi(files, t)
heads = 0
sids = set()
for f in files:
    for o in fa.jl(f):
        if isinstance(o, dict) and o.get("type") == "session":
            heads += 1
            sids.add(o.get("id"))
            break
res["cli-pi-hf"] = {"files": len(files), "files_with_session_header_first": heads, "distinct_session_ids": len(sids), "tally": t.out()}

t = fa.Tally()
oc = glob.glob(A + "/agentcap-dacorvo/*opencode-traces*/data/**/*.json", recursive=True)
pi = glob.glob(A + "/agentcap-dacorvo/*pi-traces*/data/**/*.jsonl", recursive=True)
fa.audit_opencode(oc, t, "oc_")
fa.audit_pi(pi, t, "pi_")
res["agentcap-dacorvo"] = {"opencode_json": len(oc), "pi_jsonl": len(pi), "tally": t.out()}

c = collections.Counter()
sessions = collections.Counter()
with gzip.open(A + "/tracelab-uw/v0.0.2/syfi_coding_trace.jsonl.gz", "rb") as fh:
    for line in fh:
        o = json.loads(line)
        p = str(o.get("provider"))
        c["rows_" + p] += 1
        sessions[(p, o.get("session_id"))] += 1
        for tl in o.get("tools") or []:
            c["tools_" + p] += 1
            if tl.get("tool_call_id") and tl.get("emitted_at") and tl.get("result_at"):
                c["tools_with_id_and_both_stamps_" + p] += 1
sp = collections.Counter(p for p, s in sessions)
res["tracelab-uw"] = {"counts": dict(c), "sessions_by_provider": dict(sp), "sessions_total": len(sessions)}
json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1)
print(json.dumps(res, indent=1))
