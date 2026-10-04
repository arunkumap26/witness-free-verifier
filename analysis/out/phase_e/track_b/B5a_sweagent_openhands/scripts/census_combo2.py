"""Schema census of a downloaded combo2 trajectories shard (.tar.gz), streamed member by member (never extracted
to disk). Counts trajectories, messages, timestamps, tool_call_id joins, returncode-in-content, and harness
`synthetic` flags by kind, plus result latency (tool ts - assistant ts) for synthetic vs non-synthetic results."""
import json, sys, tarfile, re, collections

path = sys.argv[1]
st = collections.Counter()
syn = collections.Counter()
roles = collections.Counter()
exits = collections.Counter()
lat = {"synthetic": [], "executed": []}
RC = re.compile(r"<returncode>(-?\d+)</returncode>")
with tarfile.open(path, "r|gz") as tf:
    for m in tf:
        if not m.isfile() or not m.name.endswith(".json"):
            continue
        d = json.load(tf.extractfile(m))
        st["trajectories"] += 1
        exits[d.get("exit_status")] += 1
        ids = set()
        last_a = None
        for msg in d.get("messages", []):
            roles[msg.get("role")] += 1
            ts = msg.get("timestamp")
            st["messages"] += 1
            if isinstance(ts, (int, float)):
                st["messages_ts"] += 1
            ex = msg.get("extra") or {}
            if msg.get("role") == "assistant":
                for a in (ex.get("actions") or []):
                    if a.get("tool_call_id"):
                        ids.add(a["tool_call_id"])
                        st["actions"] += 1
                last_a = ts
            if msg.get("role") == "tool":
                st["tool_results"] += 1
                if msg.get("tool_call_id") in ids:
                    st["tool_joined"] += 1
                if RC.search(str(msg.get("content") or "")):
                    st["tool_rc_in_content"] += 1
                kind = ex.get("synthetic")
                if kind:
                    syn["tool:" + str(kind)] += 1
                if isinstance(ts, (int, float)) and isinstance(last_a, (int, float)):
                    lat["synthetic" if kind else "executed"].append(ts - last_a)
            elif ex.get("synthetic"):
                syn[msg.get("role") + ":" + str(ex.get("synthetic"))] += 1
q = lambda xs, p: round(xs[int(p * (len(xs) - 1))], 4) if xs else None
for k in lat:
    lat[k].sort()
print(json.dumps({"shard": path, "counts": dict(st), "roles": dict(roles), "exit_status": dict(exits.most_common(10)),
                  "synthetic_flags": dict(syn),
                  "tool_ts_minus_assistant_ts_s": {k: {"n": len(v), **{f"p{int(p*100)}": q(v, p) for p in (0, .05, .5, .95, 1)}}
                                                   for k, v in lat.items()}}, indent=1))
