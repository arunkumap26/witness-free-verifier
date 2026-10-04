"""Schema census of a downloaded directory of mini-swe-agent v2 *.traj.json files (tarsur385 corpus).
Counts messages by role, timestamp presence, tool_call_id join (tool msg -> earlier assistant tool_calls id),
returncode presence, not-executed padding markers, response id shapes, assistant timestamp - created deltas."""
import json, sys, os, re, glob, collections


def idshape(s):
    if s is None:
        return "None"
    s = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", str(s))
    s = re.sub(r"[0-9a-f]{16}", "<hex16>", s)
    return s


root = sys.argv[1]
files = sorted(glob.glob(os.path.join(root, "**", "*.traj.json"), recursive=True))
st = collections.Counter()
roles = collections.Counter()
shapes = collections.Counter()
vers = collections.Counter()
models = collections.Counter()
exits = collections.Counter()
deltas, gaps = [], []
for fp in files:
    if os.sep + ".cache" + os.sep in fp:
        continue
    d = json.load(open(fp, encoding="utf-8"))
    st["trajectories"] += 1
    info = d.get("info") or {}
    vers[info.get("mini_version")] += 1
    exits[info.get("exit_status")] += 1
    models[((info.get("config") or {}).get("model") or {}).get("model_name")] += 1
    call_ids = set()
    last_assistant_ts = None
    for m in d.get("messages", []):
        roles[m.get("role")] += 1
        ex = m.get("extra") or {}
        ts = ex.get("timestamp") if isinstance(ex, dict) else None
        if m.get("role") == "assistant":
            st["assistant"] += 1
            if ts is not None:
                st["assistant_ts"] += 1
            for tc in m.get("tool_calls") or []:
                call_ids.add(tc.get("id"))
                st["tool_calls"] += 1
            resp = ex.get("response") if isinstance(ex, dict) else None
            if isinstance(resp, dict):
                shapes[idshape(resp.get("id"))] += 1
                if resp.get("usage"):
                    st["assistant_with_usage"] += 1
                if resp.get("created") and ts:
                    deltas.append(ts - resp["created"])
            last_assistant_ts = ts
        if m.get("role") == "tool":
            st["tool_results"] += 1
            if ts is not None:
                st["tool_ts"] += 1
            if m.get("tool_call_id") in call_ids:
                st["tool_joined"] += 1
            if isinstance(ex, dict) and "returncode" in ex:
                st["tool_returncode"] += 1
                if ex.get("returncode") not in (0, None):
                    st["tool_nonzero_rc"] += 1
            if isinstance(ex, dict) and ex.get("exception_info") == "action was not executed":
                st["tool_not_executed_padding"] += 1
            if ts is not None and last_assistant_ts is not None:
                gaps.append(ts - last_assistant_ts)
deltas.sort()
gaps.sort()
q = lambda xs, p: round(xs[int(p * (len(xs) - 1))], 3) if xs else None
print(json.dumps({"root": root, "counts": dict(st), "roles": dict(roles), "mini_versions": dict(vers),
                  "models": dict(models), "exit_status": dict(exits), "response_id_shapes": shapes.most_common(5),
                  "assistant_ts_minus_created_s": {"n": len(deltas), **{f"p{int(p*100)}": q(deltas, p) for p in (0, .05, .5, .95, 1)}},
                  "tool_ts_minus_assistant_ts_s": {"n": len(gaps), **{f"p{int(p*100)}": q(gaps, p) for p in (0, .05, .5, .95, 1)},
                                                   "n_negative": sum(1 for g in gaps if g < 0)}}, indent=1))
