"""Schema census of the downloaded OpenHands feedback parquet (whole file; it is small).
Join rule audited: an observation event (observation set, not agent_state_changed/null) is 'paired' if the nearest
preceding agent action event has id == obs.id - 1 (OpenHands assigns consecutive ids to an action and its observation)
and, when both carry a command/code, the observation's extras echo the action's command/code."""
import json, sys, collections, re
import pyarrow.parquet as pq

p = sys.argv[1]
t = pq.read_table(p)
rows = t.to_pylist()
st = collections.Counter()
models = collections.Counter()
versions = collections.Counter()
perms = collections.Counter()
fb = collections.Counter()
kinds = collections.Counter()
dates = []
TRUNC = re.compile(r"truncated|\[\.\.\.", re.I)
for r in rows:
    st["sessions"] += 1
    versions[r["version"]] += 1
    perms[r["permissions"]] += 1
    fb[r["feedback"]] += 1
    if r["timestamp"]:
        dates.append(r["timestamp"])
    traj = r["trajectory"] or []
    last_action = None
    for e in traj:
        st["events"] += 1
        if e.get("timestamp") is not None:
            st["events_with_ts"] += 1
        ex = e.get("extras")
        try:
            exd = json.loads(ex) if isinstance(ex, str) else (ex or {})
        except Exception:
            exd = {}
        if e.get("action") == "initialize" and isinstance(exd, dict) and exd.get("LLM_MODEL"):
            models[exd["LLM_MODEL"]] += 1
        a, o = e.get("action"), e.get("observation")
        kinds[(e.get("source"), a, o)] += 1
        if a and e.get("source") == "agent" and a not in ("message", "finish", "change_agent_state"):
            st["agent_tool_actions"] += 1
            if e.get("timestamp") is not None:
                st["agent_tool_actions_ts"] += 1
            last_action = (e, exd)
        if o and o not in ("agent_state_changed", "null", "user_rejected"):
            st["observations"] += 1
            if e.get("timestamp") is not None:
                st["observations_ts"] += 1
            if TRUNC.search(str(e.get("content") or "")):
                st["obs_trunc_marker"] += 1
            if isinstance(exd, dict) and "exit_code" in exd:
                st["obs_exit_code"] += 1
            if o == "error":
                st["obs_error"] += 1
            if last_action is not None:
                ae, aex = last_action
                try:
                    consecutive = int(e["id"]) == int(ae["id"]) + 1
                except Exception:
                    consecutive = False
                cmd_a = (aex.get("command") or aex.get("code")) if isinstance(aex, dict) else None
                cmd_o = (exd.get("command") or exd.get("code")) if isinstance(exd, dict) else None
                echo_ok = (cmd_a is None or cmd_o is None or cmd_a == cmd_o)
                if consecutive and echo_ok:
                    st["obs_paired_strict"] += 1
                if cmd_a is not None and cmd_o is not None:
                    st["obs_with_both_cmds"] += 1
                    st["obs_cmd_echo_match"] += (cmd_a == cmd_o)
                last_action = None
print(json.dumps({"counts": dict(st), "versions": dict(versions), "permissions": dict(perms), "feedback": dict(fb),
                  "submitted_ts_min": str(min(dates)) if dates else None, "submitted_ts_max": str(max(dates)) if dates else None,
                  "models_top": models.most_common(15), "n_models": len(models),
                  "event_kinds_top": [[list(k), v] for k, v in kinds.most_common(25)]}, indent=1, default=str))
