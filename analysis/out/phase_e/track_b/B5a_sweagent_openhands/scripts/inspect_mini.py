"""Field audit of a mini-swe-agent style trajectory JSON: per-message keys, timestamp fields, id joins, response ids."""
import json, sys, collections, re

for path in sys.argv[1:]:
    d = json.load(open(path, encoding="utf-8"))
    print("=====", path)
    print(" top:", list(d.keys()) if isinstance(d, dict) else type(d).__name__, "format:", d.get("trajectory_format") if isinstance(d, dict) else None)
    info = d.get("info", {}) if isinstance(d, dict) else {}
    print(" info keys:", list(info.keys()), "mini_version:", info.get("mini_version"), "model_stats:", info.get("model_stats"))
    cfg = info.get("config", {})
    model = (cfg.get("model") or {}) if isinstance(cfg, dict) else {}
    print(" model cfg:", {k: model.get(k) for k in ("model_name", "model_class", "model_kwargs")})
    msgs = d.get("messages") or d.get("trajectory") or []
    print(" n msgs:", len(msgs))
    kc = collections.Counter()
    ekc = collections.Counter()
    for m in msgs:
        kc[(m.get("role"), tuple(sorted(m.keys())))] += 1
        ex = m.get("extra")
        if isinstance(ex, dict):
            ekc[(m.get("role"), tuple(sorted(ex.keys())))] += 1
    for k, v in kc.most_common(6):
        print("  msgkeys", v, k)
    for k, v in ekc.most_common(6):
        print("  extrakeys", v, k)
    # response ids and created
    rids = []
    for m in msgs:
        ex = m.get("extra") or {}
        resp = ex.get("response") if isinstance(ex, dict) else None
        if isinstance(resp, dict):
            rids.append((resp.get("id"), resp.get("created"), ex.get("timestamp")))
    print(" response id/created/timestamp samples:", rids[:3], "n:", len(rids))
    txt = json.dumps(d)
    print(" time-like keys anywhere:", sorted(set(re.findall(r'"(\w*(?:time|stamp|created|date|latenc)\w*)":', txt)))[:20])
    print(" tool_call ids sample:", re.findall(r'"tool_call_id": "([^"]+)"', txt)[:3])
