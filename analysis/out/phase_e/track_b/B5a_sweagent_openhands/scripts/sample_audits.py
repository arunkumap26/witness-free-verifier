"""Field audits on small samples of NON-downloaded sources (single files / byte ranges fetched to scratchpad).
Writes one JSON with per-source field presence. Samples themselves are third-party content and stay in scratchpad.
Sources: SWE-bench S3 (mini-swe-agent v2.1 bash-only; SWE-agent 0.x and 1.1; OpenHands flat-message trajs),
livesweagent mini-swe-agent v1.14 (gpt-5, claude-sonnet-4-5), CooperBench solo mini v2, OpenHands Index V1 archives."""
import json, os, re, sys, io, tarfile, collections

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
A62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
out = {}


def load(p):
    return json.load(open(os.path.join(S, p), encoding="utf-8"))


def mini(p):
    d = load(p)
    info = d.get("info") or {}
    msgs = d.get("messages") or []
    r = collections.Counter()
    ids, rid_created, ts_vals = set(), [], []
    for m in msgs:
        ex = m.get("extra") if isinstance(m.get("extra"), dict) else {}
        role = m.get("role")
        r[role] += 1
        if "timestamp" in ex:
            r[role + "_ts"] += 1
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                ids.add(tc.get("id"))
            resp = ex.get("response")
            if isinstance(resp, dict):
                rid_created.append((resp.get("id"), resp.get("created")))
        if role == "tool":
            r["tool_joined"] += m.get("tool_call_id") in ids
            r["tool_returncode"] += "returncode" in ex
    ocm = [x for x in rid_created if x[0] and re.fullmatch(r"chatcmpl-[A-Za-z0-9]{29}", x[0])]
    dec_ok = 0
    for i, c in ocm:
        v = 0
        for ch in i[9:14]:
            v = v * 62 + A62.index(ch)
        dec_ok += (v + 1_576_800_000 == c)
    return {"mini_version": info.get("mini_version"), "trajectory_format": d.get("trajectory_format"),
            "model": ((info.get("config") or {}).get("model") or {}).get("model_name"), "counts": dict(r),
            "response_id_examples": [x[0] for x in rid_created[:2]],
            "openai_style_chatcmpl_ids": len(ocm), "openai_chatcmpl_created_decode_matches": dec_ok}


for key, p in [("s3_bashonly_mini_v2.1_claude-sonnet-4-5", "s3_mini200_sonnet45_12907.json"),
               ("livesweagent_gpt-5_mini_v1.14", "livesweagent__gpt-5_swebench_verified_traj.sample.json"),
               ("livesweagent_claude-sonnet-4-5_mini_v1.14", "livesweagent__claude-sonnet-4-5_swebench_verified_traj.sample.json"),
               ("cooperbench_solo_qwen9b_mini_v2", "CooperBench__qwen9b-solo-mini-swe-agent.sample.json")]:
    out[key] = mini(p)

# SWE-agent 0.x and 1.1 .traj
for key, p in [("s3_sweagent_0x_claude3.5sonnet", "s3_swea_35s_14096.traj"), ("s3_sweagent_1.1_claude-4-sonnet", "s3_swea1x_small.traj")]:
    d = load(p)
    t = d.get("trajectory") or []
    keys = collections.Counter(k for s in t for k in s.keys())
    hist = d.get("history") or []
    out[key] = {"steps": len(t), "step_keys": dict(keys),
                "has_execution_time": all("execution_time" in s for s in t) and bool(t),
                "history_items": len(hist), "history_with_tool_call_ids": sum(1 for h in hist if h.get("tool_call_ids")),
                "wallclock_timestamp_keys": sorted(set(re.findall(r'"(\w*(?:timestamp|created)\w*)":', json.dumps(d)))),
                "info_version": (d.get("info") or {}).get("swe_agent_version")}

# OpenHands flat-message trajs in S3
for key, p in [("s3_openhands_20241029_codeact2.1", "s3_oh_20241029_14096.json"), ("s3_openhands_20250415", "s3_oh_20250415_14096.json"),
               ("s3_openhands_20251127_opus-4-5", "s3_oh_opus45_12907.json")]:
    d = load(p)
    keys = collections.Counter(tuple(sorted(m.keys())) for m in d)
    out[key] = {"messages": len(d), "key_sets": [[list(k), v] for k, v in keys.most_common(5)],
                "timestamp_keys": sorted(set(re.findall(r'"(\w*(?:timestamp|created)\w*)":', json.dumps(d))))}

# OpenHands Index V1 archive peeks
raw = open(os.path.join(S, "ohindex_ds.2.member"), "rb").read().split(b"\n")[0]
r = json.loads(raw)
h = r.get("history") or []
kinds = collections.Counter(e.get("kind") for e in h)
acts = {e.get("id") for e in h if e.get("kind") == "ActionEvent"}
obs = [e for e in h if e.get("kind") == "ObservationEvent"]
out["openhands_index_v1.8.3_deepseek-reasoner_swebench"] = {
    "event_kinds": dict(kinds), "events_with_timestamp": sum(1 for e in h if e.get("timestamp")),
    "observations_joined_by_action_id": sum(1 for e in obs if e.get("action_id") in acts), "observations": len(obs),
    "observations_with_exit_code": sum(1 for e in obs if isinstance(e.get("observation"), dict) and "exit_code" in e["observation"]),
    "metrics_keys": list((r.get("metrics") or {}).keys()),
    "response_latencies_n": len((r.get("metrics") or {}).get("response_latencies") or []),
    "llm_response_id_examples": [e.get("llm_response_id") for e in h if e.get("llm_response_id")][:2]}
b = open(os.path.join(S, "ohindex_opus48.3.member"), "rb").read()
tf = tarfile.open(fileobj=io.BytesIO(b), mode="r:gz")
evs = []
for m in tf.getmembers():
    if m.isfile() and m.name.endswith(".json"):
        try:
            evs.append(json.load(tf.extractfile(m)))
        except Exception:
            pass
evs = [e for e in evs if isinstance(e, dict)]
out["openhands_index_v1.24.0_claude-opus-4-8_swebench_one_conversation"] = {
    "event_files": len(evs), "kinds": dict(collections.Counter(e.get("kind") for e in evs)),
    "llm_response_id_shapes": sorted({re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", e["llm_response_id"]) for e in evs if e.get("llm_response_id")}),
    "tool_call_id_prefixes": sorted({e["tool_call_id"][:6] for e in evs if e.get("tool_call_id")})}
json.dump(out, sys.stdout, indent=1)
