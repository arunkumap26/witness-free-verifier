"""Field audit stats for legacy OpenHands eval output.jsonl lines (v1.9 pair format and v2.x flat format).
Reads complete lines from partial range samples. Prints per-file: n instances, events, timestamp parse rate,
observation->action join rate (cause), tool_call_id presence, exit_code presence, truncation markers,
model_response.id shapes, created-vs-timestamp delta, metrics keys."""
import json, sys, re, collections, datetime as dt

TRUNC = re.compile(r"(truncated|Observation truncated|\[\.\.\..*?\]|<response clipped>)", re.I)


def events(rec):
    h = rec.get("history") or []
    out = []
    for e in h:
        if isinstance(e, list):
            out += [x for x in e if isinstance(x, dict)]
        elif isinstance(e, dict):
            out.append(e)
    return out


def idshape(s):
    if s is None:
        return None
    s = str(s)
    s = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", s)
    s = re.sub(r"[A-Za-z0-9]{20,}", lambda m: f"<b62x{len(m.group())}>", s)
    return s


for path in sys.argv[1:]:
    raw = open(path, "rb").read()
    lines = [l for l in raw.split(b"\n")[:-1] if l.strip()]
    recs = [json.loads(l) for l in lines]
    st = collections.Counter()
    shapes = collections.Counter()
    deltas = []
    mkeys = collections.Counter()
    for r in recs:
        mkeys.update((r.get("metrics") or {}).keys())
        ev = events(r)
        ids = {str(e.get("id")) for e in ev}
        for e in ev:
            st["events"] += 1
            ts = e.get("timestamp")
            try:
                t = dt.datetime.fromisoformat(ts)
                st["ts_ok"] += 1
            except Exception:
                t = None
            is_obs = "observation" in e
            if is_obs:
                st["obs"] += 1
                if e.get("cause") is not None and str(e.get("cause")) in ids:
                    st["obs_cause_joined"] += 1
                ex = e.get("extras") or {}
                if isinstance(ex, dict) and "exit_code" in ex:
                    st["obs_exit_code"] += 1
                if TRUNC.search(str(e.get("content") or "")):
                    st["obs_trunc_marker"] += 1
                if e.get("observation") == "error":
                    st["obs_error_type"] += 1
            if "action" in e and e.get("source") == "agent":
                st["agent_actions"] += 1
            tcm = e.get("tool_call_metadata")
            if isinstance(tcm, dict):
                st["tcm"] += 1
                mr = tcm.get("model_response") or {}
                if "action" in e:
                    shapes[idshape(mr.get("id"))] += 1
                    if mr.get("created") and t:
                        deltas.append(t.replace(tzinfo=dt.timezone.utc).timestamp() - float(mr["created"]))
    print("=====", path)
    print(" instances(complete lines):", len(recs), dict(st))
    print(" metrics keys:", dict(mkeys))
    print(" model_response.id shapes (actions):", shapes.most_common(5))
    if deltas:
        deltas.sort()
        q = lambda p: round(deltas[int(p * (len(deltas) - 1))], 3)
        print(" action.timestamp - model_response.created (s): n=%d p0=%s p5=%s p50=%s p95=%s p100=%s" % (
            len(deltas), q(0), q(.05), q(.5), q(.95), q(1)))
