"""Corpus skeptic: where does combo2's `synthetic` flag sit, and how many tool results carry it?

The raw-byte count of `"synthetic": "<value>"` in shard 00 is exactly twice the per-message count reported in
CORPUS_INVENTORY.md for the two tool-result values. This script parses every member of trajectories_00.tar.gz and
counts the flag per JSON path, so the doubling is explained rather than guessed. Structural only (no latency).

Run:  PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/corpus_skeptic/combo2_synthetic.py
Out:  analysis/out/phase_e/track_b/corpus_skeptic/combo2_synthetic.json
"""
import collections
import json
import os
import tarfile

A = "C:/Swarms/data/acquired/sweagent-combo2-rl-rollouts/trajectories_00.tar.gz"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "combo2_synthetic.json")


def walk(o, path, hits):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "synthetic" and isinstance(v, str):
                hits.append((path + "/synthetic", v))
            walk(v, path + "/" + k, hits)
    elif isinstance(o, list):
        for x in o:
            walk(x, path + "[]", hits)


by_path = collections.Counter()
by_role_value = collections.Counter()
members = 0
members_with_flag = 0
tool_results_total = 0
with tarfile.open(A, "r|gz") as tf:
    for ti in tf:
        if not ti.isfile() or not ti.name.endswith(".json"):
            continue
        d = json.load(tf.extractfile(ti))
        members += 1
        hits = []
        walk(d, "", hits)
        for p, v in hits:
            by_path[p + "=" + v] += 1
        any_flag = False
        for m in d.get("messages") or []:
            if m.get("role") == "tool":
                tool_results_total += 1
            s = (m.get("extra") or {}).get("synthetic")
            if s:
                by_role_value["%s:%s" % (m.get("role"), s)] += 1
                any_flag = True
        members_with_flag += int(any_flag)
json.dump({"produced_by": "analysis/out/phase_e/track_b/corpus_skeptic/combo2_synthetic.py", "members": members,
           "members_with_any_flag": members_with_flag, "tool_messages_total": tool_results_total,
           "messages_extra_synthetic_by_role_value": dict(by_role_value),
           "raw_occurrences_by_json_path": dict(by_path)}, open(OUT, "w"), indent=1)
print(json.dumps({"by_role_value": by_role_value, "by_path": by_path, "members": members}, default=dict, indent=1))
