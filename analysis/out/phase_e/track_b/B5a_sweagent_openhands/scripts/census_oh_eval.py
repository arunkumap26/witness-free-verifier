"""Schema census of downloaded OpenHands/openhands-evaluation-outputs: streams every outputs/**/output.jsonl.
Per run: instances, events, timestamp parse, action/observation counts, observation->action join via `cause`,
tool_call_metadata presence, tool_call_id shapes, model_response.id shapes, created-vs-timestamp delta,
exit_code presence, error observations, truncation markers, usage presence. No content is printed."""
import json, sys, os, re, collections, datetime as dt, glob

root = sys.argv[1]
TRUNC = re.compile(r"(Observation truncated|\[\.\.\..{0,40}truncated|<response clipped>|truncated due to length)", re.I)


def idshape(s):
    if s is None:
        return "None"
    s = str(s)
    s = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", s)
    s = re.sub(r"[A-Za-z0-9_-]{16,}", lambda m: f"<x{len(m.group())}>", s)
    s = re.sub(r"\d+", "<n>", s)
    return s


def q(xs, p):
    return round(xs[int(p * (len(xs) - 1))], 3) if xs else None


out = {}
for path in sorted(glob.glob(os.path.join(root, "outputs", "**", "output.jsonl"), recursive=True)):
    run = os.path.relpath(os.path.dirname(path), os.path.join(root, "outputs")).replace("\\", "/")
    st = collections.Counter()
    rid, tcid = collections.Counter(), collections.Counter()
    deltas, models = [], collections.Counter()
    first_ts, last_ts = None, None
    fmt = collections.Counter()
    with open(path, "rb") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                st["bad_lines"] += 1
                continue
            st["instances"] += 1
            models[((r.get("metadata") or {}).get("llm_config") or {}).get("model")] += 1
            h = r.get("history") or []
            evs = []
            for e in h:
                if isinstance(e, list):
                    fmt["pair"] += 1
                    evs += [x for x in e if isinstance(x, dict)]
                elif isinstance(e, dict):
                    fmt["flat"] += 1
                    evs.append(e)
            ids = {str(e.get("id")) for e in evs}
            for e in evs:
                st["events"] += 1
                t = None
                try:
                    t = dt.datetime.fromisoformat(e.get("timestamp"))
                    st["ts_ok"] += 1
                    s = t.isoformat()
                    first_ts = s if first_ts is None or s < first_ts else first_ts
                    last_ts = s if last_ts is None or s > last_ts else last_ts
                except Exception:
                    pass
                if "action" in e and e.get("source") == "agent" and e.get("action") not in ("message", "finish", "change_agent_state", "system", "think", "recall", "condensation"):
                    st["agent_tool_actions"] += 1
                if "observation" in e and e.get("observation") not in ("agent_state_changed", "null", "recall", "think", "condensation"):
                    st["observations"] += 1
                    c = e.get("cause")
                    if c is not None and str(c) in ids:
                        st["obs_cause_joined"] += 1
                    ex = e.get("extras") or {}
                    if isinstance(ex, dict) and ("exit_code" in ex or "metadata" in ex and isinstance(ex.get("metadata"), dict) and "exit_code" in ex["metadata"]):
                        st["obs_exit_code"] += 1
                    if e.get("observation") == "error":
                        st["obs_error"] += 1
                    if TRUNC.search(str(e.get("content") or "")):
                        st["obs_trunc_marker"] += 1
                tcm = e.get("tool_call_metadata")
                if isinstance(tcm, dict):
                    st["events_with_tcm"] += 1
                    if "action" in e:
                        tcid[idshape(tcm.get("tool_call_id"))] += 1
                        mr = tcm.get("model_response") or {}
                        rid[idshape(mr.get("id"))] += 1
                        if mr.get("usage"):
                            st["actions_with_usage"] += 1
                        if mr.get("created") and t is not None:
                            deltas.append(t.replace(tzinfo=dt.timezone.utc).timestamp() - float(mr["created"]))
    deltas.sort()
    out[run] = {"counts": dict(st), "history_format": dict(fmt), "models": dict(models),
                "event_ts_range": [first_ts, last_ts],
                "tool_call_id_shapes": rid and tcid.most_common(4), "model_response_id_shapes": rid.most_common(4),
                "action_ts_minus_created_s": {"n": len(deltas), "p0": q(deltas, 0), "p5": q(deltas, .05), "p50": q(deltas, .5),
                                              "p95": q(deltas, .95), "p100": q(deltas, 1),
                                              "n_negative": sum(1 for d in deltas if d < 0)}}
    print(run, json.dumps(out[run]["counts"]), file=sys.stderr)
tot = collections.Counter()
for v in out.values():
    tot.update(v["counts"])
json.dump({"root": root, "n_runs": len(out), "totals": dict(tot), "per_run": out}, sys.stdout, indent=1, default=str)
