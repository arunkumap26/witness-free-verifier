"""Corpus skeptic: independent sampled field audit of the 14 corpora downloaded in Phase E B5.

Written from scratch (does not import the B5 scripts or analysis/lib) so that a parser bug shared with the B5 tasks
cannot make both audits agree. Read-only over C:/Swarms/data/acquired. Never executes downloaded code. Prints no
secrets (credential-like values are counted, never echoed).

What it measures per corpus, on a seeded random sample of its natural unit (file / instance / trajectory / row):
  - events, events carrying a timestamp, and timestamps with sub-second resolution (ms or finer)
  - calls, results, calls whose result is found by the corpus's join key (or positional pairing where that is the
    only join), results that point at no call
  - entries carrying an Anthropic-layout request id (req_01 + 22 base58), where the format has a requestId field
Sample sizes are stated in the output. The sample is structural only: no latency, gap or duration statistic is
computed, so it does not consume the held-out budget of any later timing test.

Run:  PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/corpus_skeptic/field_audit.py
Out:  analysis/out/phase_e/track_b/corpus_skeptic/field_audit.json
"""
import collections
import datetime as dt
import glob
import gzip
import io
import json
import os
import random
import re
import sys
import tarfile
import time

A = "C:/Swarms/data/acquired"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "field_audit.json")
SEED = 20261004
REQ_RX = re.compile(r"^req_(?:vrtx_|bdrk_)?01[1-9A-HJ-NP-Za-km-z]{22}$")
ISO_FRAC = re.compile(r"T\d\d:\d\d:\d\d[.,](\d+)")


def rng_for(name):
    return random.Random("%d:%s" % (SEED, name))


def ts_res(v):
    """-> None (absent), 's' (whole seconds), 'sub' (ms or finer)."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int,)):
        # 13-digit epoch ms / 16-digit us count as sub-second; 10-digit epoch s as seconds
        return "sub" if v > 10**11 else "s"
    if isinstance(v, float):
        return "sub" if v != int(v) else "s"
    if isinstance(v, str):
        m = ISO_FRAC.search(v)
        if m:
            return "sub" if len(m.group(1)) >= 3 else "s"
        if re.match(r"^\d{8}@\d{6}$", v):
            return "s"
        if re.match(r"^\d{8}@\d{7,}$", v):
            return "sub"
        if re.match(r"^\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d", v):
            return "s"
        return "unparsed"
    if hasattr(v, "microsecond"):  # pyarrow -> datetime
        return "sub" if v.microsecond else "s"
    return "unparsed"


class Tally:
    def __init__(self):
        self.c = collections.Counter()

    def ts(self, prefix, v):
        r = ts_res(v)
        self.c[prefix + "_n"] += 1
        if r is not None:
            self.c[prefix + "_with_ts"] += 1
        if r == "sub":
            self.c[prefix + "_ts_subsecond"] += 1
        if r == "unparsed":
            self.c[prefix + "_ts_unparsed"] += 1

    def __getitem__(self, k):
        return self.c[k]

    def add(self, k, n=1):
        self.c[k] += n

    def out(self):
        return dict(sorted(self.c.items()))


def sample(lst, k, name):
    lst = sorted(lst)
    r = rng_for(name)
    if len(lst) <= k:
        return lst
    return sorted(r.sample(lst, k))


def jl(path):
    """yield parsed JSON lines; count bad lines in a side counter."""
    with open(path, "rb") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except Exception:
                yield {"__bad__": True}


# ---------------------------------------------------------------- Claude Code JSONL
def audit_cc_files(files, t):
    for f in files:
        t.add("files")
        calls, results = set(), set()
        for o in jl(f):
            if o.get("__bad__"):
                t.add("bad_lines")
                continue
            typ = o.get("type")
            if typ not in ("user", "assistant"):
                continue
            t.ts("ua_entries", o.get("timestamp"))
            msg = o.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if typ == "assistant":
                t.add("assistant_entries")
                rid = o.get("requestId")
                if isinstance(rid, str) and rid.startswith("req_"):
                    t.add("assistant_entries_with_req")
                    if REQ_RX.match(rid):
                        t.add("assistant_entries_with_req_anthropic_layout")
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use" and b.get("id"):
                        calls.add(b["id"])
                    elif b.get("type") == "tool_result" and b.get("tool_use_id"):
                        results.add(b["tool_use_id"])
        t.add("calls", len(calls))
        t.add("results", len(results))
        t.add("calls_joined", len(calls & results))
        t.add("results_without_call", len(results - calls))


# ---------------------------------------------------------------- Codex rollout
def audit_codex(files, t):
    for f in files:
        t.add("files")
        calls, results = set(), set()
        for o in jl(f):
            if o.get("__bad__"):
                t.add("bad_lines")
                continue
            t.ts("lines", o.get("timestamp"))
            p = o.get("payload") or {}
            if o.get("type") == "response_item" and isinstance(p, dict):
                pt = p.get("type")
                if pt in ("function_call", "custom_tool_call", "local_shell_call") and p.get("call_id"):
                    calls.add(p["call_id"])
                elif pt in ("function_call_output", "custom_tool_call_output") and p.get("call_id"):
                    results.add(p["call_id"])
            for k in ("requestId", "request_id"):
                if k in o or (isinstance(p, dict) and k in p):
                    t.add("entries_with_request_id_key")
        t.add("calls", len(calls))
        t.add("results", len(results))
        t.add("calls_joined", len(calls & results))
        t.add("results_without_call", len(results - calls))


# ---------------------------------------------------------------- Pi session JSONL
def audit_pi(files, t, prefix=""):
    for f in files:
        t.add(prefix + "files")
        calls, results = set(), set()
        for o in jl(f):
            if o.get("__bad__"):
                t.add(prefix + "bad_lines")
                continue
            t.ts(prefix + "entries", o.get("timestamp"))
            if o.get("type") != "message":
                continue
            m = o.get("message") or {}
            t.ts(prefix + "messages_epoch", m.get("timestamp"))
            role = m.get("role")
            if role == "assistant":
                t.add(prefix + "assistant_messages")
                if m.get("responseId"):
                    t.add(prefix + "assistant_with_responseId")
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "toolCall" and b.get("id"):
                        calls.add(b["id"])
            elif role == "toolResult" and m.get("toolCallId"):
                results.add(m["toolCallId"])
        t.add(prefix + "calls", len(calls))
        t.add(prefix + "results", len(results))
        t.add(prefix + "calls_joined", len(calls & results))
        t.add(prefix + "results_without_call", len(results - calls))


# ---------------------------------------------------------------- OpenCode export JSON
def audit_opencode(files, t, prefix="oc_"):
    for f in files:
        t.add(prefix + "files")
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            t.add(prefix + "bad_files")
            continue
        for m in d.get("messages") or []:
            info = m.get("info") or {}
            t.ts(prefix + "messages_created", (info.get("time") or {}).get("created"))
            for p in m.get("parts") or []:
                if p.get("type") != "tool":
                    continue
                t.add(prefix + "tool_parts")
                st = p.get("state") or {}
                tm = st.get("time") or {}
                t.ts(prefix + "tool_start", tm.get("start"))
                t.ts(prefix + "tool_end", tm.get("end"))
                if p.get("callID"):
                    t.add(prefix + "tool_parts_with_callID")
                    if st.get("output") is not None:
                        t.add(prefix + "tool_parts_with_callID_and_output")
                st_ = st.get("status")
                t.add(prefix + "status_" + str(st_))


# ---------------------------------------------------------------- ATIF
def audit_atif(files, t, prefix=""):
    for f in files:
        t.add(prefix + "files")
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            t.add(prefix + "bad_files")
            continue
        steps = d.get("steps") or []
        calls, results = set(), set()
        for s in steps:
            t.ts(prefix + "steps", s.get("timestamp"))
            met = s.get("metrics")
            if isinstance(met, dict):
                t.add(prefix + "steps_with_metrics")
                if (met.get("prompt_tokens") or 0) > 0 or (met.get("completion_tokens") or 0) > 0:
                    t.add(prefix + "steps_with_nonzero_tokens")
            tcs = s.get("tool_calls") or []
            for tc in tcs:
                t.add(prefix + "tool_calls")
                if tc.get("tool_call_id"):
                    calls.add((s.get("step_id"), tc["tool_call_id"]))
            obs = s.get("observation") or {}
            rs = obs.get("results") or [] if isinstance(obs, dict) else []
            for r in rs:
                t.add(prefix + "obs_results")
                sc = r.get("source_call_id") if isinstance(r, dict) else None
                if sc:
                    t.add(prefix + "obs_results_with_source_call_id")
                    results.add((s.get("step_id"), sc))
                elif tcs:
                    t.add(prefix + "obs_results_step_paired")
                else:
                    t.add(prefix + "obs_results_no_call_in_step")
        t.add(prefix + "calls_with_id", len(calls))
        t.add(prefix + "calls_joined_same_step", len(calls & results))
        t.add(prefix + "results_with_id_without_call_same_step", len(results - calls))


# ---------------------------------------------------------------- Gemini CLI
def audit_gemini(files, t):
    for f in files:
        t.add("gem_files")
        d = json.load(open(f, encoding="utf-8"))
        for m in d.get("messages") or []:
            t.ts("gem_messages", m.get("timestamp"))
            for tc in m.get("toolCalls") or []:
                t.add("gem_calls")
                t.ts("gem_toolcall", tc.get("timestamp"))
                ok = False
                for r in tc.get("result") or []:
                    fr = (r or {}).get("functionResponse") or {}
                    if fr.get("id") == tc.get("id") and tc.get("id"):
                        ok = True
                t.add("gem_calls_joined", int(ok))


# ---------------------------------------------------------------- hookele
def audit_hookele(files, t):
    for f in files:
        t.add("hk_files")
        calls, results = set(), set()
        for o in jl(f):
            if o.get("__bad__"):
                t.add("hk_bad_lines")
                continue
            t.ts("hk_lines", o.get("ts"))
            if o.get("type") == "raw_response":
                for tc in o.get("tool_calls") or []:
                    if tc.get("call_id"):
                        calls.add(tc["call_id"])
            elif o.get("type") == "tool_execution" and o.get("call_id"):
                results.add(o["call_id"])
            if o.get("type") == "stream_summary":
                t.add("hk_stream_summaries")
                if str(o.get("response_id", "")).startswith("resp_"):
                    t.add("hk_stream_summaries_with_resp_id")
        t.add("hk_calls", len(calls))
        t.add("hk_results", len(results))
        t.add("hk_calls_joined", len(calls & results))
        t.add("hk_results_without_call", len(results - calls))


# ---------------------------------------------------------------- per corpus drivers
def tb2(res):
    root = A + "/terminal-bench-2-leaderboard/hf_repo/submissions/terminal-bench/2.0"
    subs = sorted(os.listdir(root))
    atif, cc, gem, hk, results_json = [], [], [], [], collections.Counter()
    for s in subs:
        for dp, dn, fn in os.walk(os.path.join(root, s)):
            for f in fn:
                p = os.path.join(dp, f).replace("\\", "/")
                if f == "trajectory.json" and "/agent/" in p:
                    atif.append(p)
                elif p.endswith(".jsonl") and "/agent/sessions/" in p:
                    cc.append(p)
                elif f == "gemini-cli.trajectory.json":
                    gem.append(p)
                elif p.endswith("/.hookele/traj.jsonl"):
                    hk.append(p)
                elif f == "result.json":
                    results_json[s] += 1
    def sub_of(p):
        return p[len(root) + 1:].split("/")[0]
    subs_with = collections.defaultdict(set)
    for kind, lst in (("atif", atif), ("cc", cc), ("gemini", gem), ("hookele", hk)):
        for p in lst:
            subs_with[kind].add(sub_of(p))
    any_logs = set().union(*subs_with.values())
    census = {
        "submissions": len(subs),
        "submissions_with_any_structured_log": len(any_logs),
        "submissions_without_structured_log": len(subs) - len(any_logs),
        "submissions_with": {k: len(v) for k, v in subs_with.items()},
        "native_only_submissions": sorted(any_logs - subs_with["atif"]),
        "files": {"atif": len(atif), "cc_jsonl": len(cc), "gemini": len(gem), "hookele": len(hk)},
        "trial_result_json_total": sum(results_json.values()),
    }
    t = Tally()
    # stratified: 2 ATIF files per ATIF submission, 3 CC JSONL per CC submission, 6 gemini, 6 hookele
    by_sub = collections.defaultdict(list)
    for p in atif:
        by_sub[sub_of(p)].append(p)
    atif_s = []
    for s in sorted(by_sub):
        atif_s += sample(by_sub[s], 2, "tb2atif:" + s)
    audit_atif(atif_s, t, "atif_")
    by_sub = collections.defaultdict(list)
    for p in cc:
        by_sub[sub_of(p)].append(p)
    cc_s = []
    for s in sorted(by_sub):
        cc_s += sample(by_sub[s], 4, "tb2cc:" + s)
    tcc = Tally()
    audit_cc_files(cc_s, tcc)
    audit_gemini(sample(gem, 8, "tb2gem"), t)
    audit_hookele(sample(hk, 8, "tb2hk"), t)
    res["terminal-bench-2-leaderboard"] = {
        "census": census,
        "sample": {"atif_files": len(atif_s), "cc_jsonl_files": len(cc_s), "gemini_files": min(8, len(gem)),
                   "hookele_files": min(8, len(hk)), "rule": "2 ATIF per ATIF submission, 4 CC JSONL per CC submission"},
        "tally": t.out(), "cc_tally": tcc.out(),
    }


def glm(res):
    files = glob.glob(A + "/glm52-nf3-tb21-traces/hf_repo/traces/*/agent/trajectory.json")
    t = Tally()
    s = sample(files, 20, "glm")
    audit_atif(s, t, "atif_")
    res["glm52-nf3-tb21-traces"] = {"census": {"atif_files": len(files)}, "sample": {"atif_files": len(s)}, "tally": t.out()}


def openhands_eval(res):
    runs = sorted(glob.glob(A + "/openhands-evaluation-outputs/outputs/SWE-bench_Lite-test/CodeActAgent/*/output.jsonl"))
    t = Tally()
    per_run = {}
    K = 6
    for f in runs:
        name = f.split("/")[-2] if "/" in f else f
        name = os.path.basename(os.path.dirname(f))
        # reservoir sample K lines per run (stream the whole file; parse only the kept lines)
        r = rng_for("oh:" + name)
        keep, n = [], 0
        with open(f, "rb") as fh:
            for line in fh:
                n += 1
                if len(keep) < K:
                    keep.append(line)
                else:
                    j = r.randrange(n)
                    if j < K:
                        keep[j] = line
        rt = Tally()
        for line in keep:
            d = json.loads(line)
            h = d.get("history") or []
            shape = "pairs" if h and isinstance(h[0], list) else "flat"
            rt.add("instances_" + shape)
            if shape == "flat":
                acts = {}
                obs_causes = []
                for e in h:
                    rt.ts("events", e.get("timestamp"))
                    if "action" in e and e.get("source") == "agent" and e.get("action") not in ("message", "finish", "think", "system", "recall", "condensation"):
                        acts[e.get("id")] = e
                    if "observation" in e:
                        if e.get("cause") is not None:
                            obs_causes.append(e.get("cause"))
                        rt.add("observations")
                ids = set(acts)
                rt.add("agent_tool_actions", len(ids))
                rt.add("agent_tool_actions_with_obs_by_cause", len(ids & set(obs_causes)))
                rt.add("observations_with_cause", len(obs_causes))
                all_ids = {e.get("id") for e in h}
                rt.add("observations_cause_resolves", sum(1 for c in obs_causes if c in all_ids))
                for e in h:
                    tcm = e.get("tool_call_metadata")
                    if "action" in e and isinstance(tcm, dict):
                        mr = tcm.get("model_response") or {}
                        rt.add("actions_with_model_response")
                        if str(mr.get("id", "")).startswith("chatcmpl-"):
                            rt.add("model_response_id_chatcmpl")
            else:
                for pair in h:
                    if not isinstance(pair, list) or len(pair) != 2:
                        rt.add("malformed_pairs")
                        continue
                    a, o = pair
                    rt.ts("events", (a or {}).get("timestamp"))
                    rt.ts("events", (o or {}).get("timestamp"))
                    if (a or {}).get("source") == "agent" and (a or {}).get("action") not in ("message", "finish", None):
                        rt.add("agent_tool_actions")
                        if o and o.get("observation") not in (None, "null"):
                            rt.add("agent_tool_actions_with_obs_positional")
        per_run[name] = {"lines_in_file": n, "sampled": len(keep), "tally": rt.out()}
        for k, v in rt.c.items():
            t.add(k, v)
    res["openhands-evaluation-outputs"] = {"census": {"runs": len(runs)}, "sample": {"instances_per_run": K},
                                           "tally": t.out(), "per_run": per_run}


def openhands_feedback(res):
    import pyarrow.parquet as pq
    tbl = pq.read_table(A + "/openhands-feedback/data/train-00000-of-00001.parquet")
    n = tbl.num_rows
    idx = sample(list(range(n)), 40, "ohf")
    t = Tally()
    for i in idx:
        row = tbl.slice(i, 1).to_pylist()[0]
        traj = row.get("trajectory") or []
        byid = {}
        for e in traj:
            if e.get("id") is not None:
                byid[e["id"]] = e
        NON_TOOL_ACT = {"message", "finish", "change_agent_state", "initialize", "null", None}
        NON_TOOL_OBS = {"agent_state_changed", "null", None}
        for e in traj:
            is_act = e.get("action") not in NON_TOOL_ACT and e.get("source") == "agent"
            is_obs = e.get("observation") not in NON_TOOL_OBS
            if is_act:
                t.ts("tool_actions", e.get("timestamp"))
            if is_obs:
                t.ts("tool_observations", e.get("timestamp"))
                prev = byid.get((e.get("id") if e.get("id") is not None else -99) - 1)
                if prev is not None and prev.get("action") not in NON_TOOL_ACT:
                    t.add("tool_observations_paired_id_minus_1_to_tool_action")
    res["openhands-feedback"] = {"census": {"rows": n}, "sample": {"sessions": len(idx)}, "tally": t.out()}


def miniswe(res):
    files = glob.glob(A + "/miniswe-v2-qwen3-30b-swebv-tarsur385/trajectories/*.traj.json")
    s = sample(files, 40, "mini")
    t = Tally()
    for f in s:
        d = json.load(open(f, encoding="utf-8"))
        calls, results = set(), set()
        for m in d.get("messages") or []:
            role = m.get("role")
            ex = m.get("extra") or {}
            if role in ("assistant", "tool"):
                t.ts(role, ex.get("timestamp"))
            if role == "assistant":
                for tc in m.get("tool_calls") or []:
                    if tc.get("id"):
                        calls.add(tc["id"])
            elif role == "tool" and m.get("tool_call_id"):
                results.add(m["tool_call_id"])
        t.add("calls", len(calls))
        t.add("results", len(results))
        t.add("calls_joined", len(calls & results))
        t.add("results_without_call", len(results - calls))
        t.add("exit_" + str((d.get("info") or {}).get("exit_status")))
    res["miniswe-v2-qwen3-30b-swebv-tarsur385"] = {"census": {"traj_files": len(files)}, "sample": {"traj_files": len(s)}, "tally": t.out()}


def combo2(res):
    path = A + "/sweagent-combo2-rl-rollouts/trajectories_00.tar.gz"
    # pass 1 is the same stream: count members, and sample by member ordinal with a seeded reservoir of parsed docs
    t = Tally()
    full = collections.Counter()
    K = 40
    r = rng_for("combo2")
    keep, n = [], 0
    rx_syn = re.compile(rb'"synthetic"\s*:\s*"([^"]{1,40})"')
    with tarfile.open(path, "r|gz") as tf:
        for ti in tf:
            if not ti.isfile() or not ti.name.endswith(".json"):
                continue
            raw = tf.extractfile(ti).read()
            n += 1
            for m in rx_syn.finditer(raw):
                full["synthetic:" + m.group(1).decode()] += 1
            if len(keep) < K:
                keep.append(raw)
            else:
                j = r.randrange(n)
                if j < K:
                    keep[j] = raw
    for raw in keep:
        d = json.loads(raw)
        calls, results = set(), set()
        for m in d.get("messages") or []:
            role = m.get("role")
            if role in ("assistant", "tool"):
                t.ts(role, m.get("timestamp"))
            ex = m.get("extra") or {}
            if role == "assistant":
                for a in ex.get("actions") or []:
                    if isinstance(a, dict) and a.get("tool_call_id"):
                        calls.add(a["tool_call_id"])
            elif role == "tool" and m.get("tool_call_id"):
                results.add(m["tool_call_id"])
        t.add("calls", len(calls))
        t.add("results", len(results))
        t.add("calls_joined", len(calls & results))
        t.add("results_without_call", len(results - calls))
    res["sweagent-combo2-rl-rollouts"] = {"census": {"members": n, "synthetic_flag_values_full_shard": dict(full)},
                                          "sample": {"trajectories": len(keep)}, "tally": t.out()}


def osworld(res):
    files = glob.glob(A + "/osworld_verified_trajs/*/tasks/*/*/traj.jsonl")
    by_sub = collections.defaultdict(list)
    for f in files:
        by_sub[f.replace("\\", "/").split("/osworld_verified_trajs/")[1].split("/")[0]].append(f)
    t = Tally()
    per = {}
    for sname in sorted(by_sub):
        st = Tally()
        for f in sample(by_sub[sname], 4, "osw:" + sname):
            for o in jl(f):
                if o.get("__bad__"):
                    st.add("bad_lines")
                    continue
                st.ts("rows", o.get("action_timestamp"))
                a = o.get("action")
                if isinstance(a, dict) and (a.get("id") or a.get("call_id")):
                    st.add("rows_with_call_id")
                if o.get("screenshot_file"):
                    st.add("rows_with_screenshot_ref")
        per[sname] = st.out()
        for k, v in st.c.items():
            t.add(k, v)
    res["osworld_verified_trajs"] = {"census": {"submissions": len(by_sub), "traj_files": len(files)},
                                     "sample": {"traj_files_per_submission": 4}, "tally": t.out(), "per_submission": per}


def webarena(res):
    files = glob.glob(A + "/webarena_infinity_trajs/data/gemini/*/*/history.json")
    s = sample(files, 40, "wai")
    t = Tally()
    for f in s:
        d = json.load(open(f, encoding="utf-8"))
        for st in d.get("history") or []:
            md = st.get("metadata") or {}
            t.ts("step_start", md.get("step_start_time"))
            t.ts("step_end", md.get("step_end_time"))
            acts = ((st.get("model_output") or {}).get("action")) or []
            rs = st.get("result") or []
            t.add("steps")
            t.add("actions", len(acts))
            t.add("results", len(rs))
            if len(acts) == len(rs):
                t.add("steps_action_result_count_match")
    res["webarena_infinity_trajs"] = {"census": {"history_files": len(files)}, "sample": {"history_files": len(s)}, "tally": t.out()}


def tracelab(res):
    path = A + "/tracelab-uw/v0.0.2/syfi_coding_trace.jsonl.gz"
    K = 3000
    r = rng_for("tracelab")
    keep, n = [], 0
    with gzip.open(path, "rb") as fh:
        for line in fh:
            n += 1
            if len(keep) < K:
                keep.append(line)
            else:
                j = r.randrange(n)
                if j < K:
                    keep[j] = line
    t = Tally()
    for line in keep:
        o = json.loads(line)
        prov = o.get("provider")
        for ev in o.get("timing_events") or []:
            t.ts("timing_events", ev.get("timestamp"))
        for tl in o.get("tools") or []:
            t.add("tools_" + str(prov))
            if tl.get("tool_call_id"):
                t.add("tools_with_id_" + str(prov))
            t.ts("tool_emitted_" + str(prov), tl.get("emitted_at"))
            t.ts("tool_result_" + str(prov), tl.get("result_at"))
            if tl.get("emitted_at") and tl.get("result_at") and tl.get("tool_call_id"):
                t.add("tools_with_id_and_both_stamps_" + str(prov))
    res["tracelab-uw"] = {"census": {"rows": n}, "sample": {"rows": len(keep)}, "tally": t.out()}


def cli_simple(res, name, pattern, fn, k):
    files = [f for f in glob.glob(A + "/" + name + "/" + pattern, recursive=True)]
    s = sample(files, k, name)
    t = Tally()
    fn(s, t)
    res[name] = {"census": {"files": len(files)}, "sample": {"files": len(s)}, "tally": t.out()}


def agentcap(res):
    import pyarrow.parquet as pq
    oc = glob.glob(A + "/agentcap-dacorvo/*opencode-traces*/data/**/*.json", recursive=True)
    pi = glob.glob(A + "/agentcap-dacorvo/*pi-traces*/data/**/*.jsonl", recursive=True)
    caps = glob.glob(A + "/agentcap-dacorvo/*captures*/data/*.parquet")
    t = Tally()
    audit_opencode(sample(oc, 40, "agoc"), t, "oc_")
    audit_pi(sample(pi, 40, "agpi"), t, "pi_")
    ct = Tally()
    rows = 0
    for f in caps:
        tb = pq.read_table(f, columns=["request_id", "captured_at", "run_id"])
        rows += tb.num_rows
        for v in tb.column("captured_at").to_pylist()[:5000]:
            ct.ts("captured_at", v)
        for v in tb.column("request_id").to_pylist():
            ct.add("request_id_present" if v else "request_id_missing")
            if v and REQ_RX.match(str(v)):
                ct.add("request_id_anthropic_layout")
            if v and re.fullmatch(r"[0-9a-f]{32}", str(v)):
                ct.add("request_id_hex32_uuid")
    res["agentcap-dacorvo"] = {"census": {"opencode_json": len(oc), "pi_jsonl": len(pi), "capture_parquets": len(caps), "capture_rows": rows},
                               "sample": {"opencode_json": min(40, len(oc)), "pi_jsonl": min(40, len(pi)), "captures": "all rows (request_id), first 5000 per file (captured_at)"},
                               "tally": t.out(), "captures_tally": ct.out()}


def main():
    res = {}
    timings = {}
    jobs = [
        ("cli-trace-commons", lambda: cli_simple(res, "cli-trace-commons", "*/sessions/**/*.jsonl", audit_cc_files, 40)),
        ("cli-claude-code-hf", lambda: cli_simple(res, "cli-claude-code-hf", "**/*.jsonl", audit_cc_files, 60)),
        ("cli-codex-hf", lambda: cli_simple(res, "cli-codex-hf", "**/*.jsonl", audit_codex, 46)),
        ("cli-pi-hf", lambda: cli_simple(res, "cli-pi-hf", "**/*.jsonl", audit_pi, 60)),
        ("agentcap-dacorvo", lambda: agentcap(res)),
        ("tracelab-uw", lambda: tracelab(res)),
        ("webarena_infinity_trajs", lambda: webarena(res)),
        ("osworld_verified_trajs", lambda: osworld(res)),
        ("miniswe", lambda: miniswe(res)),
        ("openhands-feedback", lambda: openhands_feedback(res)),
        ("glm", lambda: glm(res)),
        ("tb2", lambda: tb2(res)),
        ("combo2", lambda: combo2(res)),
        ("openhands-evaluation-outputs", lambda: openhands_eval(res)),
    ]
    only = set(sys.argv[1:])
    for name, fn in jobs:
        if only and name not in only:
            continue
        t0 = time.time()
        try:
            fn()
        except Exception as e:  # record, do not hide
            res.setdefault("_errors", {})[name] = repr(e)
        timings[name] = round(time.time() - t0, 1)
        print(name, timings[name], "s", flush=True)
    prev = {}
    if only and os.path.exists(OUT):
        prev = json.load(open(OUT, encoding="utf-8"))
    out = prev.get("results", {})
    out.update(res)
    doc = {"produced_by": "analysis/out/phase_e/track_b/corpus_skeptic/field_audit.py", "seed": SEED,
           "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "timings_s": {**prev.get("timings_s", {}), **timings}, "results": out}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), indent=1, sort_keys=False, default=str)


if __name__ == "__main__":
    main()
