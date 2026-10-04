"""Corpus skeptic: history shape per OpenHands eval run, over every instance (not a sample).

CORPUS_INVENTORY.md 5.3 says v2.x = 8 runs with a flat event list and v1.9 = 11 runs with [action, observation]
pairs. The sampled audit found a run named v1.9 whose history is flat. This counts, per run and over all lines:
history shape, presence of tool_call_metadata, and observations joined to an action by `cause`. Structural only.

Run:  PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/corpus_skeptic/openhands_shapes.py
Out:  analysis/out/phase_e/track_b/corpus_skeptic/openhands_shapes.json
"""
import collections
import glob
import json
import os

A = "C:/Swarms/data/acquired/openhands-evaluation-outputs/outputs/SWE-bench_Lite-test/CodeActAgent"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openhands_shapes.json")
res = {}
for f in sorted(glob.glob(A + "/*/output.jsonl")):
    run = os.path.basename(os.path.dirname(f))
    c = collections.Counter()
    with open(f, "rb") as fh:
        for line in fh:
            d = json.loads(line)
            h = d.get("history") or []
            if not h:
                c["empty_history"] += 1
                continue
            shape = "pairs" if isinstance(h[0], list) else "flat"
            c["instances_" + shape] += 1
            if shape == "flat":
                ids = {e.get("id") for e in h}
                for e in h:
                    if "tool_call_metadata" in e:
                        c["events_with_tool_call_metadata"] += 1
                    if "observation" in e:
                        c["observations"] += 1
                        if e.get("cause") in ids and e.get("cause") is not None:
                            c["observations_cause_resolves"] += 1
    res[run] = dict(c)
summary = collections.Counter()
for run, c in res.items():
    flat = c.get("instances_flat", 0)
    pairs = c.get("instances_pairs", 0)
    kind = "flat" if flat and not pairs else "pairs" if pairs and not flat else "mixed"
    summary["runs_" + kind] += 1
    if kind == "flat" and not c.get("events_with_tool_call_metadata"):
        summary["flat_runs_without_tool_call_metadata"] += 1
json.dump({"produced_by": "analysis/out/phase_e/track_b/corpus_skeptic/openhands_shapes.py", "summary": dict(summary),
           "per_run": res}, open(OUT, "w"), indent=1)
print(json.dumps(summary), flush=True)
for run, c in res.items():
    print(run[:70], c)
