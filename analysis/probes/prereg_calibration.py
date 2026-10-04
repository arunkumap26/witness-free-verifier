"""Phase B pre-registration: calibration on the Phase A split, then write analysis/prereg.json.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.prereg_calibration

Reads only analysis/cache/<corpus>_A.parquet (+ swechat_population.parquet) and analysis/out/phase_a/*.json.
Never opens *_B.parquet: every load goes through load_A(), which asserts the split. Writes:
  analysis/out/phase_a/prereg_calibration.json   raw counts and A-split threshold inputs (no interpretation)
  analysis/prereg.json                           SPEC (analysis/probes/prereg_common.py) + `resolved` thresholds
                                                 derived from the calibration by the rules written in SPEC.

What this script computes on A, and what it deliberately does NOT compute:
  computed  - Probe 1: qualified-pair counts, per-tool floors (p1/p5/p10/p50), IQRs, generation rates (G50/G90),
              counts of pairs eligible for the separability test, change-point eligible series counts.
            - Probe 2: extraction yields per field and class, first-mention counts, depth distribution of access
              paths, workspace-root detection counts.
            - Probe 3: paired calls per session (L75/L90), counts of failed calls with a successor, eligible sessions.
            - Probe 4: hex/integer/timestamp token counts per class, redaction drops, and the machine-control digit
              test (M_git, M_all) as instrument calibration; N_min by power calculation.
  NOT computed (these are Phase B outcomes): r / fp_share / AUC, any sourced-vs-unsourced share, zero-error shares,
              retry rates, early/late differences, any digit test or round-number share of model-typed classes.
"""
import gc
import hashlib
import json
import math
import time
from bisect import bisect_left
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import error_marker, parse_ts
from analysis.probes import prereg_common as pc

OUT = pc.ROOT / "analysis" / "out" / "phase_a" / "prereg_calibration.json"
PREREG = pc.ROOT / "analysis" / "prereg.json"
COLS = ["session_id", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "args", "command", "text", "stderr",
        "native_error", "exit_code", "usage_out", "api_msg_id", "is_subagent", "agent_id", "parent_call_id", "extra",
        "stratum"]
P1_UNITS = pc.SPEC["probe1"]["units_alive_after_A1"]
P2_UNITS = pc.SPEC["probe2"]["units"]["full"] + list(pc.SPEC["probe2"]["units"]["antecedents_incomplete"])
P3_UNITS = ["swechat/claude_code", "cc_local", "aiv_cc", "swechat/codex", "swechat/opencode", "swechat/gemini",
            "aiv_cu", "whowhen"]
P4_UNITS = pc.SPEC["probe4"]["units"]["testable"] + ["swechat/cursor"]


def load_A(corpus, columns):
    split = "A"
    assert split == "A"
    return pc.load_split(corpus, split, columns)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def qstats(values, sids, qs=(0.01, 0.05, 0.10, 0.25, 0.5, 0.75, 0.95), ci_qs=(0.01, 0.05, 0.10, 0.5, 0.95)):
    """Quantiles with session-clustered bootstrap CIs (same draws as stats.cluster_quantile)."""
    v = np.asarray(values, dtype=float)
    s = np.asarray(sids, dtype=object).astype(str)
    out = {"n": int(len(v)), "n_sessions": int(len(set(s.tolist())))}
    if len(v) == 0:
        return out
    out["min"], out["max"] = float(v.min()), float(v.max())
    pts = np.quantile(v, qs)
    uniq, inv = np.unique(s, return_inverse=True)
    boots = None
    if len(uniq) >= 2:
        order = np.argsort(inv, kind="stable")
        bounds = np.searchsorted(inv[order], np.arange(len(uniq) + 1))
        groups = [v[order[bounds[i]:bounds[i + 1]]] for i in range(len(uniq))]
        rng = np.random.default_rng(stats.SEED)
        boots = np.empty((stats.N_BOOT, len(ci_qs)))
        for b in range(stats.N_BOOT):
            pick = rng.integers(0, len(groups), size=len(groups))
            boots[b] = np.quantile(np.concatenate([groups[i] for i in pick]), ci_qs)
    for i, q in enumerate(qs):
        d = {"value": float(pts[i])}
        if boots is not None and q in ci_qs:
            j = ci_qs.index(q)
            d["lo"], d["hi"] = float(np.quantile(boots[:, j], 0.025)), float(np.quantile(boots[:, j], 0.975))
        out[f"p{round(q * 100, 2):g}"] = d
    return out


def reportable(n, sessions, q):
    need = {"p50": (30, 5), "p5": (100, 5), "p95": (100, 5), "p10": (100, 5), "p1": (500, 5)}[q]
    return n >= need[0] and sessions >= need[1]


# ============================================================================================================ PROBE 1
def p1_qualified(unit, u, P):
    """Adds key, cls, qualified, marker columns to the pair frame P (pre-registered no-human-wait filter)."""
    P = P.copy()
    P["key"] = [pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    if unit == "cc_local":
        P["key"] = [pc.private_key(k) for k in P.key]
    P["cls"] = [pc.tool_class(k) for k in P.key]
    txt = pc.sobj(P.text_r)
    P["marker"] = [error_marker(t) for t in txt]
    rx = [pc.jl(e) for e in P.extra_r.astype(object)]
    ok = np.isfinite(P.delta_s.to_numpy())
    # rule 2: allowed classes
    allowed = pc.SPEC["probe1"]["no_human_wait_filter"]["allowed_classes"][unit]
    if unit == "aiv_cc":
        cls_ok = ~P.cls.isin(["human_interactive", "subagent"])
    elif unit == "swechat/codex":
        cls_ok = ~P.key.isin(["spawn_agent", "wait_agent", "close_agent", "list_agents", "write_stdin"])
    else:
        cls_ok = P.cls.isin(allowed)
    # rule 3: last (CC) / only (Gemini) call of its API message
    msg = [a if isinstance(a, str) else f"__solo__{c}" for a, c in zip(P.api_msg_id.astype(object), P.call_id.astype(str))]
    P["_msg"] = msg
    if unit in pc.CC_FORMAT_UNITS or unit == "swechat/gemini":
        calls = u[u.kind == "call"].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
        cm = [a if isinstance(a, str) else f"__solo__{c}" for a, c in zip(calls.api_msg_id.astype(object), calls.call_id.astype(str))]
        calls = calls.assign(_msg=cm)
        last = ~calls.duplicated(["session_id", "_msg"], keep="last")
        nin = calls.groupby(["session_id", "_msg"]).call_id.transform("size")
        lk = dict(zip(zip(calls.session_id, calls.call_id.astype(str)), last))
        nk = dict(zip(zip(calls.session_id, calls.call_id.astype(str)), nin))
        keys = list(zip(P.session_id, P.call_id.astype(str)))
        if unit == "swechat/gemini":
            msg_ok = np.array([nk.get(k, 1) == 1 for k in keys])
        else:
            msg_ok = np.array([bool(lk.get(k, True)) for k in keys])
    else:
        msg_ok = np.ones(len(P), dtype=bool)
    # rule 4: markers / declined / cancelled
    mk_ok = ~P.marker.isin(["cc_permission_denied", "cc_interrupt_reject"]).to_numpy()
    if unit == "swechat/codex":
        mk_ok &= np.array([x.get("exec_status") != "declined" and not x.get("unified_exec_running") for x in rx])
    if unit == "swechat/gemini":
        mk_ok &= np.array([x.get("status") != "cancelled" for x in rx])
    # rule 5: hooks
    hook_ok = np.ones(len(P), dtype=bool)
    if unit == "swechat/claude_code":
        m = u[(u.kind == "meta") & u.parent_call_id.notna()]
        hooked = {(s, str(pcid)) for s, pcid, e in zip(m.session_id, m.parent_call_id.astype(object), m.extra.astype(object))
                  if pc.jl(e).get("type") == "hook_progress"}
        hook_ok = np.array([k not in hooked for k in zip(P.session_id, P.call_id.astype(str))])
    elif unit == "cc_local":
        a = u[u.extra.notna() & u.kind.isin(["system", "meta", "user"])]
        hooked = set()
        for s, e in zip(a.session_id, a.extra.astype(object)):
            x = pc.jl(e)
            at = x.get("attachment_type")
            if at and str(at).startswith("hook") and x.get("toolUseID"):
                hooked.add((s, str(x["toolUseID"])))
        hook_ok = np.array([k not in hooked for k in zip(P.session_id, P.call_id.astype(str))])
    # rule 6: codex approval policy
    pol_ok = np.ones(len(P), dtype=bool)
    if unit == "swechat/codex":
        m = u[(u.kind == "meta") & u.extra.notna()]
        pol = defaultdict(list)
        for s, q, e in zip(m.session_id, m.seq, m.extra.astype(object)):
            x = pc.jl(e)
            if "approval_policy" in x:
                pol[s].append((int(q), x.get("approval_policy")))
        for s in pol:
            pol[s].sort()
        res = []
        for s, q in zip(P.session_id, P.seq):
            lst = pol.get(s, [])
            i = bisect_left([a for a, _ in lst], int(q)) - 1
            res.append(i >= 0 and lst[i][1] == "never")
        pol_ok = np.array(res)
    P["qualified"] = ok & cls_ok.to_numpy() & msg_ok & mk_ok & hook_ok & pol_ok
    P["_rx"] = rx
    P["_rule_fail"] = [
        "no_ts" if not a else "class" if not b else "not_last_or_only_in_msg" if not c else "marker_declined_cancelled"
        if not d else "hook" if not e else "approval_policy" if not f else "qualified"
        for a, b, c, d, e, f in zip(ok, cls_ok.to_numpy(), msg_ok, mk_ok, hook_ok, pol_ok)]
    return P


def generation_rates(unit, u):
    """Per-response output-token rates (usage-based and char-based), pre-registered definition."""
    ts_all = pc.sobj(u.ts)
    u = u.assign(_ts=[parse_ts(t) if t else None for t in ts_all])
    u["_thr"] = list(zip(u.session_id, u.is_subagent.astype("boolean").fillna(False).astype(bool),
                         u.agent_id.astype(object).fillna("").astype(str)))
    # antecedent index per thread: (seq, ts) of result/user events with ts
    anc = defaultdict(list)
    sub = u[u.kind.isin(["result", "user"]) & u._ts.notna()]
    for thr, q, t in zip(sub._thr, sub.seq, sub._ts):
        anc[thr].append((int(q), t))
    for k in anc:
        anc[k].sort(key=lambda x: x[0])
    anc_seq = {k: [a for a, _ in v] for k, v in anc.items()}
    resp = []  # dicts: session, thread, out_tokens, chars, t_end, min_seq
    if unit == "swechat/codex":
        uu = u.sort_values(["session_id", "seq"])
        for sid, g in uu.groupby("session_id", sort=False):
            pend = []
            for kind, q, t, uo, thr, a in zip(g.kind, g.seq, g._ts, g.usage_out, g._thr, g.args.astype(object)):
                if kind == "call":
                    pend.append((int(q), t, thr, len(a) if isinstance(a, str) else 0))
                elif kind == "meta" and not pd.isna(uo):
                    if pend:
                        tt = [x[1] for x in pend if x[1] is not None]
                        if tt:
                            resp.append({"sid": sid, "thr": pend[0][2], "tok": float(uo), "chars": None,
                                         "t_end": max(tt), "min_seq": min(x[0] for x in pend)})
                    pend = []
    else:
        calls = u[u.kind == "call"]
        rows = u[u.api_msg_id.notna()]
        tok = rows[rows.usage_out.notna()].groupby(["session_id", "api_msg_id"]).usage_out.max()
        thk = defaultdict(int)
        chars = defaultdict(int)
        for s, a, kind, txt, args, e in zip(rows.session_id, rows.api_msg_id.astype(str), rows.kind, rows.text.astype(object),
                                            rows.args.astype(object), rows.extra.astype(object)):
            if kind == "assistant" and isinstance(txt, str):
                chars[(s, a)] += len(txt)
            if kind == "call" and isinstance(args, str):
                chars[(s, a)] += len(args)
            if isinstance(e, str) and "thinking_chars" in e:
                v = pc.jl(e).get("thinking_chars")
                if isinstance(v, (int, float)):
                    thk[(s, a)] += int(v)
        c = calls[calls.api_msg_id.notna() & calls._ts.notna()]
        for (s, a), g in c.groupby(["session_id", "api_msg_id"]):
            k = (s, str(a))
            t_end = max(g._ts)
            tk = tok.get((s, a))
            resp.append({"sid": s, "thr": g._thr.iloc[0], "tok": None if tk is None or pd.isna(tk) else float(tk),
                         "chars": chars.get(k, 0) + thk.get(k, 0), "t_end": t_end, "min_seq": int(g.seq.min())})
    out_tok, out_chr = [], []
    for r in resp:
        lst = anc_seq.get(r["thr"], [])
        i = bisect_left(lst, r["min_seq"]) - 1
        if i < 0:
            continue
        t0 = anc[r["thr"]][i][1]
        td = r["t_end"] - t0
        gap = td.days * 86400 + td.seconds + td.microseconds / 1e6
        if not (0 < gap <= 600):
            continue
        if r["tok"] is not None and r["tok"] >= 50:
            out_tok.append((r["sid"], r["tok"] / gap))
        if r["chars"] is not None:
            ct = r["chars"] * pc.SPEC["probe1"]["separability"]["generation_time_model"]["tokens_per_char"]
            if ct >= 50:
                out_chr.append((r["sid"], ct / gap))
    toks = [r["tok"] for r in resp if r["tok"] is not None]
    med_tok = float(np.median(toks)) if toks else None
    method = "usage" if (med_tok is not None and med_tok >= 20) else "chars"
    use = out_tok if method == "usage" else out_chr
    res = {"responses_with_calls": len(resp), "responses_with_usage": len(toks),
           "median_output_tokens_per_response": med_tok, "method": method,
           "usage_based": qstats([v for _, v in out_tok], [s for s, _ in out_tok], qs=(0.1, 0.5, 0.9), ci_qs=(0.5, 0.9))
           if out_tok else {"n": 0},
           "char_based": qstats([v for _, v in out_chr], [s for s, _ in out_chr], qs=(0.1, 0.5, 0.9), ci_qs=(0.5, 0.9))
           if out_chr else {"n": 0}}
    chosen = res["usage_based"] if method == "usage" else res["char_based"]
    res["G50"] = chosen.get("p50", {}).get("value")
    res["G90"] = chosen.get("p90", {}).get("value")
    res["n_rates"] = chosen.get("n", 0)
    res["n_sessions"] = chosen.get("n_sessions", 0)
    return res


G_TOOLS = {
    "swechat/claude_code": {"subagent", "webfetch", "websearch"},
    "cc_local": {"subagent", "webfetch", "websearch", "workflow"},
    "aiv_cc": {"websearch", "webfetch", "mcp__village__search_history"},
    "swechat/opencode": {"subagent", "websearch"},
    "swechat/gemini": {"websearch"},
    "swechat/codex": set(),
}
W_KEYS = {
    "aiv_cc": {"read", "glob", "grep", "ls", "shell", "edit", "write"},
    "swechat/codex": {"shell_command", "exec_command", "apply_patch", "mcp__filesystem__read_text_file",
                      "mcp__filesystem__read_multiple_files"},
}


def g_latency(unit, key, delta, x):
    """Pre-registered latency for a generation-bound pair (None = excluded)."""
    if unit in pc.CC_FORMAT_UNITS:
        if key == "webfetch":
            v = x.get("durationMs")
            if isinstance(v, (int, float)):
                return v / 1000
            return delta if unit == "aiv_cc" else None
        if key == "websearch":
            v = x.get("durationSeconds")
            if isinstance(v, (int, float)):
                return float(v)
            return delta if unit == "aiv_cc" else None
        if key in ("subagent", "workflow"):
            v = x.get("totalDurationMs")
            return v / 1000 if isinstance(v, (int, float)) else delta
    return delta


def probe1_unit(unit, u):
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    P = p1_qualified(unit, u, P)
    out = {"pairs": int(len(P)), "pairs_with_delta": int(np.isfinite(P.delta_s).sum()),
           "sessions": int(P.session_id.nunique())}
    out["filter_outcome"] = dict(Counter(P._rule_fail))
    out["qualified_by_class"] = {c: int(g.qualified.sum()) for c, g in P.groupby("cls")}
    out["all_by_class"] = {c: int(len(g)) for c, g in P.groupby("cls")}
    Q = P[P.qualified & (P.delta_s > 0)]
    tools = {}
    for k, g in Q.groupby("key"):
        d = g.delta_s.to_numpy()
        s = g.session_id.to_numpy()
        row = qstats(d, s)
        lq = np.log10(d)
        row["iqr_s"] = float(np.quantile(d, 0.75) - np.quantile(d, 0.25))
        row["iqr_log10"] = float(np.quantile(lq, 0.75) - np.quantile(lq, 0.25))
        row["below_0.1s"] = int((d < 0.1).sum())
        sc = g.groupby("session_id").size()
        row["series_n_ge_40"] = int((sc >= 40).sum())
        row["reportable"] = {q: reportable(row["n"], row["n_sessions"], q) for q in ("p1", "p5", "p50")}
        tools[k] = row
    out["qualified_by_tool"] = tools
    out["negative_deltas"] = int((P.delta_s < 0).sum())
    # generation rate
    gr = generation_rates(unit, u)
    out["generation_rate"] = gr
    G90 = gr.get("G90")
    tpc = pc.SPEC["probe1"]["separability"]["generation_time_model"]["tokens_per_char"]
    P["chars_r"] = [len(t) if isinstance(t, str) else 0 for t in P.text_r.astype(object)]
    # W eligible counts
    if unit in W_KEYS:
        W = Q[Q.key.isin(W_KEYS[unit])]
    else:
        W = Q[Q.cls == "auto_read"]
    Wc = P.loc[W.index]
    # G set
    nested_bad = set()
    if unit in ("swechat/claude_code", "cc_local"):
        nn = u[u.parent_call_id.notna() & u.kind.isin(["result", "call"])]
        for s, pcid, kind, txt, tl in zip(nn.session_id, nn.parent_call_id.astype(str), nn.kind, nn.text.astype(object),
                                          nn.tool.astype(object)):
            if kind == "result" and error_marker(txt if isinstance(txt, str) else "") in ("cc_permission_denied", "cc_interrupt_reject"):
                nested_bad.add((s, pcid))
            if kind == "call" and pc.tool_class(tl if isinstance(tl, str) else "") == "human_interactive":
                nested_bad.add((s, pcid))
    gl, gsid, gch, gkey = [], [], [], []
    for k, d, x, s, cid, mk, ch in zip(P.key, P.delta_s, P._rx, P.session_id, P.call_id.astype(str), P.marker, P.chars_r):
        if k not in G_TOOLS.get(unit, set()):
            continue
        if mk in ("cc_permission_denied", "cc_interrupt_reject") or (s, cid) in nested_bad:
            continue
        lat = g_latency(unit, k, d, x)
        if lat is None or not np.isfinite(lat) or lat <= 0:
            continue
        gl.append(lat), gsid.append(s), gch.append(ch), gkey.append(k)
    out["G_pairs_usable"] = {"n": len(gl), "sessions": len(set(gsid)), "by_tool": dict(Counter(gkey))}
    if G90:
        Tw = Wc.chars_r.to_numpy() * tpc / G90
        Tg = np.array(gch) * tpc / G90
        out["eligible_T_gen_ge_1s"] = {
            "W": {"n": int((Tw >= 1).sum()), "sessions": int(Wc[Tw >= 1].session_id.nunique()), "n_all_W": int(len(Wc))},
            "G": {"n": int((Tg >= 1).sum()), "sessions": int(len(set(np.array(gsid, dtype=object)[Tg >= 1].tolist())))
                  if len(gsid) else 0, "n_all_G": len(gl)},
            "note": "counts only; r, fp_share and AUC are Phase B outcomes and were not computed"}
    return out


# ============================================================================================================ PROBE 2
ACCESS_READ = {"read", "mcp__filesystem__read_text_file", "mcp__filesystem__read_multiple_files"}
ACCESS_EDIT = {"edit"}


def probe2_unit(unit, u):
    calls = u[u.kind == "call"].sort_values(["session_id", "seq"])
    cnt = Counter()
    first = defaultdict(set)  # (thread, cls) -> keys seen
    depth_main = []
    depth_sid = []
    root_status = Counter()
    access_paths_by_session = defaultdict(list)
    rows = []
    for s, q, tl, tr, a, cmd, sub, ag in zip(calls.session_id, calls.seq, calls.tool.astype(object), calls.tool_raw.astype(object),
                                             calls.args.astype(object), calls.command.astype(object),
                                             calls.is_subagent.astype("boolean").fillna(False), calls.agent_id.astype(object)):
        key = pc.tool_key(unit, tl, tr)
        try:
            obj = json.loads(a) if isinstance(a, str) else None
        except ValueError:
            obj = None
        thr = (s, bool(sub), ag if isinstance(ag, str) else "")
        refs = defaultdict(list)
        sp = pc.structured_paths(obj, tr) if isinstance(obj, dict) else []
        targets = []
        for p, how in sp:
            if how == "patch_update":
                kind = "edit"
            elif how == "patch_add":
                kind = "create"
            elif how == "patch_delete":
                kind = "other"
            elif key in ACCESS_EDIT:
                kind = "edit"
            elif key in ACCESS_READ:
                kind = "read"
            elif key == "write":
                kind = "create"
            else:
                kind = "other"
            refs["structured_path"].append((p, kind))
            targets.append(p)
        shell = None
        if key == "shell" or key in pc.CODEX_SHELL_RAW or key.endswith("__bash"):
            shell = pc.shell_command(unit, key, obj, cmd)
        free_src = []
        if shell:
            free_src.append(shell)
        if unit == "whowhen":
            strs, _ = pc.args_strings(a)
            free_src += strs
        for t in free_src:
            for p in pc.free_paths(t):
                refs["free_path"].append((p, "free"))
        rt = pc.symbol_ref_text(obj)
        refs["symbol_ref"] = [(x, None) for x in pc.symbols(rt)]
        if shell:
            refs["symbol_shell"] = [(x, None) for x in pc.symbols(shell)]
        if isinstance(obj, dict) and isinstance(obj.get("pattern"), str) and key in ("grep", "grep_search", "glob"):
            refs["symbol_search"] = [(x, None) for x in pc.symbols(obj["pattern"])]
        refs["env_var"] = [(x, None) for x in pc.env_vars((shell or "") + "\n" + rt)]
        refs["cfg_key"] = [(x, None) for x in pc.cfg_keys(rt, targets, shell)]
        any_ref = False
        for cls, lst in refs.items():
            if not lst:
                continue
            any_ref = True
            cnt[f"calls_with_{cls}"] += 1
            for x, kind in lst:
                if cls in ("structured_path", "free_path"):
                    if "<R>" in x:
                        cnt["redacted_path"] += 1
                        continue
                    k = pc.path_key(x)
                    if not k:
                        continue
                    fk = (thr, "path")
                    if k in first[fk]:
                        continue
                    first[fk].add(k)
                    cnt[f"first_mention_path/{'sub' if sub else 'main'}"] += 1
                    if cls == "structured_path" and kind in ("read", "edit"):
                        cnt[f"first_mention_access/{'sub' if sub else 'main'}"] += 1
                        if not sub:
                            rows.append((s, x))
                else:
                    fk = (thr, cls)
                    if x in first[fk]:
                        continue
                    first[fk].add(x)
                    cnt[f"first_mention_{cls}/{'sub' if sub else 'main'}"] += 1
        if any_ref:
            cnt["calls_with_any_reference"] += 1
        cnt["calls"] += 1
        if isinstance(obj, dict) and not sub:
            for p, how in sp:
                if pc.is_absolute(p) and (key in ACCESS_READ or key in ACCESS_EDIT or how == "patch_update"):
                    access_paths_by_session[s].append(p)
    roots = {s: pc.workspace_root(v) for s, v in access_paths_by_session.items()}
    for s, p in rows:
        d = pc.path_depth(p, roots.get(s))
        if d is None:
            root_status["depth_unknown"] += 1
            continue
        root_status["depth_known"] += 1
        depth_main.append(d)
        depth_sid.append(s)
    thr_sub = calls[calls.is_subagent.astype("boolean").fillna(False)]
    out = {"counts": dict(cnt), "depth_status": dict(root_status),
           "sessions_with_calls": int(calls.session_id.nunique()),
           "subagent_threads": int(thr_sub.groupby(["session_id", "agent_id"], dropna=False).ngroups) if len(thr_sub) else 0,
           "sessions_with_root": int(sum(1 for v in roots.values() if v is not None))}
    if depth_main:
        out["access_depth"] = qstats(depth_main, depth_sid, qs=(0.25, 0.5, 0.75, 0.9), ci_qs=(0.5, 0.75))
        out["access_depth_hist"] = {str(k): int(v) for k, v in sorted(Counter(depth_main).items())}
    return out, depth_main, depth_sid


# ============================================================================================================ PROBE 3
def probe3_unit(unit, u):
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    strat = None
    if unit == "whowhen":
        P = P[(P.stratum == "Algorithm-Generated") & (P.tool == "code_exec")]
    keys = [pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    errs = [pc.error_classes(unit, k, tr, t, e, n, x, st)[0] for k, tr, t, e, n, x, st in
            zip(keys, P.tool_raw.astype(object), P.text_r.astype(object), P.stderr_r.astype(object),
                P.native_error_r.astype(object), P.exit_code_r.astype(object), P.stratum.astype(object))]
    P = P.assign(err=[bool(x) for x in errs])
    n_calls = P.groupby("session_id").size()
    out = {"sessions_with_paired_calls": int(len(n_calls)), "paired_calls": int(len(P)),
           "calls_per_session": stats.describe(n_calls.to_numpy(), qs=(0.0, 0.25, 0.5, 0.75, 0.9, 1.0))}
    out["L75"] = int(math.ceil(np.quantile(n_calls.to_numpy(), 0.75))) if len(n_calls) else None
    out["L90"] = int(math.ceil(np.quantile(n_calls.to_numpy(), 0.90))) if len(n_calls) else None
    out["A_sessions_at_or_above_L75"] = int((n_calls >= out["L75"]).sum()) if len(n_calls) else 0
    out["A_sessions_ge_20_calls"] = int((n_calls >= 20).sum())
    # feasibility: failed calls with a successor in the same thread
    P = P.sort_values(["session_id", "seq"])
    thr = list(zip(P.session_id, P.is_subagent.astype("boolean").fillna(False), P.agent_id.astype(object).fillna("")))
    P["_thr"] = thr
    nxt = P.groupby("_thr").seq.shift(-1)
    has_next = nxt.notna().to_numpy()
    out["failed_with_successor"] = {"n": int((P.err.to_numpy() & has_next).sum()),
                                    "sessions": int(P[P.err.to_numpy() & has_next].session_id.nunique())}
    out["ok_with_successor"] = int((~P.err.to_numpy() & has_next).sum())
    out["note"] = "counts only; zero-error shares, retry rates and early/late differences are Phase B outcomes"
    if unit == "aiv_cu":
        out["L75_by_stratum"] = {}
        for st, g in P.groupby("stratum"):
            c = g.groupby("session_id").size().to_numpy()
            out["L75_by_stratum"][st] = {"sessions": int(len(c)), "L75": int(math.ceil(np.quantile(c, 0.75)))}
    return out


# ============================================================================================================ PROBE 4
def probe4_unit(unit, u, private):
    u = u.sort_values(["session_id", "seq"])
    git_calls = set()
    calls = u[u.kind == "call"]
    for s, cid, cmd, a, tl, tr in zip(calls.session_id, calls.call_id.astype(str), calls.command.astype(object),
                                      calls.args.astype(object), calls.tool.astype(object), calls.tool_raw.astype(object)):
        try:
            obj = json.loads(a) if isinstance(a, str) else None
        except ValueError:
            obj = None
        k = pc.tool_key(unit, tl, tr)
        if not (k == "shell" or k in pc.CODEX_SHELL_RAW or k.endswith("__bash")):
            continue
        sh = pc.shell_command(unit, k, obj, cmd)
        if sh and pc._C["git_cmd"].search(sh):
            git_calls.add((s, cid))
    seen_tok = {}  # class -> {token: session}
    for c in ("M_git", "M_all", "T_copy", "T_orig", "A_copy", "A_orig", "U", "S"):
        seen_tok[c] = {}
    ints = {c: {} for c in ("M_all", "T_copy", "T_orig", "A_copy", "A_orig")}
    tscnt = Counter()
    cnt = Counter()
    for sid, g in u.groupby("session_id", sort=False):
        anc = set()
        anc_pref = set()
        anc_int = set()
        for kind, txt, err, a, cid in zip(g.kind, g.text.astype(object), g.stderr.astype(object), g.args.astype(object),
                                          g.call_id.astype(object)):
            if kind in ("result", "user", "system"):
                pieces = [txt] + ([err] if kind == "result" else [])
                for t in pieces:
                    if not isinstance(t, str):
                        continue
                    toks, nu, nd = pc.hex_tokens(t)
                    cnt["uuid_masked"] += nu
                    cnt["hex_dropped_redaction"] += nd
                    if "REDACTED" in t:
                        cnt[f"events_with_REDACTED/{kind}"] += 1
                    cls = "M_all" if kind == "result" else ("U" if kind == "user" else "S")
                    for tk in toks:
                        seen_tok[cls].setdefault(tk, sid)
                        anc.add(tk)
                        for L in (7, 8, 32, 40):
                            if len(tk) > L:
                                anc_pref.add(tk[:L])
                    if kind == "result":
                        for v in pc.large_ints(t):
                            ints["M_all"].setdefault(v, sid)
                        tscnt["M_all/iso"] += len(pc._C["iso_ts"].findall(t))
                        tscnt["M_all/epoch_s"] += len(pc._C["epoch_s"].findall(t))
                        tscnt["M_all/epoch_ms"] += len(pc._C["epoch_ms"].findall(t))
                    anc_int.update(pc.large_ints(t))
                if kind == "result" and (sid, str(cid)) in git_calls and isinstance(txt, str):
                    for tk in pc.git_hashes(txt):
                        seen_tok["M_git"].setdefault(tk, sid)
            elif kind == "call":
                strs, nums = pc.args_strings(a)
                for t in strs:
                    toks, nu, nd = pc.hex_tokens(t)
                    cnt["uuid_masked"] += nu
                    cnt["hex_dropped_redaction"] += nd
                    for tk in toks:
                        cls = "T_copy" if (tk in anc or tk in anc_pref) else "T_orig"
                        seen_tok[cls].setdefault(tk, sid)
                    for v in pc.large_ints(t):
                        ints["T_copy" if v in anc_int else "T_orig"].setdefault(v, sid)
                    tscnt["T/iso"] += len(pc._C["iso_ts"].findall(t))
                for v in nums:
                    if pc._C["large_int"].fullmatch(v):
                        ints["T_copy" if v in anc_int else "T_orig"].setdefault(v, sid)
            elif kind == "assistant" and isinstance(txt, str):
                toks, nu, nd = pc.hex_tokens(txt)
                cnt["hex_dropped_redaction"] += nd
                for tk in toks:
                    cls = "A_copy" if (tk in anc or tk in anc_pref) else "A_orig"
                    seen_tok[cls].setdefault(tk, sid)
                for v in pc.large_ints(txt):
                    ints["A_copy" if v in anc_int else "A_orig"].setdefault(v, sid)
    out = {"counts": dict(cnt), "git_calls": len(git_calls), "timestamp_counts": dict(tscnt), "classes": {}}
    nmin = n_min_power()
    for cls, d in seen_tok.items():
        toks = list(d)
        lens = Counter(len(t) for t in toks)
        n_sym = int(sum(len(t) for t in toks))
        row = {"distinct_tokens": len(toks), "by_length": {str(k): int(v) for k, v in sorted(lens.items())},
               "symbols": n_sym, "sessions": len(set(d.values())), "meets_N_min": n_sym >= nmin}
        if cls in ("M_git", "M_all") and n_sym > 0:
            row["digit_test"] = digit_test_ci(d)
        out["classes"][cls] = row
    for cls, d in ints.items():
        row = {"distinct_values": len(d), "sessions": len(set(d.values()))}
        if cls == "M_all" and d:
            sids = list(d.values())
            last0 = [v.endswith("0") for v in d]
            row["last_0_share_control"] = stats.cluster_rate(*_by_session(last0, sids))
        out["classes"].setdefault("ints/" + cls, row)
    return out


def _by_session(mask, sids):
    num, den = Counter(), Counter()
    for m, s in zip(mask, sids):
        den[s] += 1
        num[s] += int(m)
    keys = list(den)
    return [num[k] for k in keys], [den[k] for k in keys]


def digit_test_ci(tok2sid):
    toks = list(tok2sid)
    obs, exp = pc.hex_counts(toks)
    w, stat, p, n = pc.w_adj_from_counts(obs, exp)
    by_s = defaultdict(list)
    for t, s in tok2sid.items():
        by_s[s].append(t)
    sess = sorted(by_s)
    per = [pc.hex_counts(by_s[s]) for s in sess]
    O = np.array([o for o, _ in per])
    E = np.array([e for _, e in per])
    rng = np.random.default_rng(stats.SEED)
    boots = []
    if len(sess) >= 2:
        for _ in range(stats.N_BOOT):
            pick = rng.integers(0, len(sess), size=len(sess))
            o, e = O[pick].sum(0), E[pick].sum(0)
            if o.sum() > 0:
                boots.append(pc.w_adj_from_counts(o, e)[0])
    res = {"w_adj": w, "chi2": stat, "p": p, "n_symbols": n, "n_tokens": len(toks), "n_sessions": len(sess)}
    if len(boots) >= 900:
        res["w_adj_lo"], res["w_adj_hi"] = float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))
    res["n_valid_boot"] = len(boots)
    return res


def b_session_counts():
    """B-split session counts per unit from the build reports (session counts only; no B data is read)."""
    b = {}
    sw = json.load(open(pc.ROOT / "analysis" / "out" / "build" / "swechat_build.json", encoding="utf-8"))
    for f, n in sw["sample"]["B_by_format"].items():
        b[f"swechat/{f}"] = n
    for f in ("copilot", "simple_text"):
        b.setdefault(f"swechat/{f}", 0)
    for c in ("aiv_cc", "cc_local", "aiv_cu"):
        bj = json.load(open(pc.ROOT / "analysis" / "out" / "build" / f"{c}_build.json", encoding="utf-8"))
        b[c] = bj["splits"]["B"]["sessions"]
    ww = json.load(open(pc.ROOT / "analysis" / "out" / "build" / "whowhen_build.json", encoding="utf-8"))
    b["whowhen"] = ww["sample"]["B_n"]
    b["whowhen/Algorithm-Generated"] = ww["sample"]["B_by_split"]["Algorithm-Generated"]
    b["whowhen/Hand-Crafted"] = ww["sample"]["B_by_split"]["Hand-Crafted"]
    return b


_NMIN = None


def n_min_power():
    global _NMIN
    if _NMIN is None:
        _NMIN = pc.n_min_power()
    return _NMIN


# ============================================================================================================ main
def main():
    t0 = time.time()
    for c in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        assert (pc.CACHE / f"{c}_A.parquet").exists()
    cal = {"script": "analysis/probes/prereg_calibration.py", "split": "A only (asserted; *_B.parquet never opened)",
           "not_computed": "Phase B outcomes: r/fp_share/AUC, sourced-vs-unsourced shares, zero-error shares, retry "
                           "rates, early/late differences, digit tests and round shares of model-typed classes",
           "units": {}, "sessions_A": {}}
    depth_pool, depth_pool_sid = [], []
    depth_by_unit = {}
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        df = load_A(corpus, COLS)
        for unit, u in pc.unit_frames(corpus, df).items():
            u = u.reset_index(drop=True)
            private = unit == "cc_local"
            res = {}
            cal["sessions_A"][unit] = int(u.session_id.nunique())
            print(f"[{time.time() - t0:6.1f}s] {unit}: {len(u)} rows", flush=True)
            if unit in P1_UNITS:
                res["probe1"] = probe1_unit(unit, u)
            if unit in P2_UNITS:
                r2, dm, ds = probe2_unit(unit, u)
                res["probe2"] = r2
                depth_by_unit[unit] = (dm, ds)
                if unit in pc.SPEC["probe2"]["units"]["full"]:
                    depth_pool += dm
                    depth_pool_sid += ds
            if unit in P3_UNITS:
                res["probe3"] = probe3_unit(unit, u)
            if unit in P4_UNITS:
                res["probe4"] = probe4_unit(unit, u, private)
            cal["units"][unit] = res
        if corpus == "whowhen":
            cal["sessions_A"]["whowhen/Algorithm-Generated"] = int(df[df.stratum == "Algorithm-Generated"].session_id.nunique())
            cal["sessions_A"]["whowhen/Hand-Crafted"] = int(df[df.stratum == "Hand-Crafted"].session_id.nunique())
        del df
        gc.collect()
    # ---------------------------------------------------------------- resolved thresholds (rules from SPEC)
    a_out = pc.ROOT / "analysis" / "out" / "phase_a"
    a1 = json.load(open(a_out / "a1.json", encoding="utf-8"))
    resolved = {"probe1": {"floors": {}, "generation_rate": {}, "iqr_log10": {}},
                "probe2": {}, "probe3": {"long_session": {}}, "probe4": {}}
    for unit in P1_UNITS:
        r = cal["units"].get(unit, {}).get("probe1")
        if not r:
            continue
        fl = {}
        for k, row in r["qualified_by_tool"].items():
            ent = {"n_A": row["n"], "sessions_A": row["n_sessions"]}
            for q in ("p1", "p5", "p10", "p50"):
                if reportable(row["n"], row["n_sessions"], q):
                    ent[q] = row[q]["value"]
            fl[k] = ent
            resolved["probe1"]["iqr_log10"].setdefault(unit, {})[k] = {"iqr_log10": row["iqr_log10"],
                                                                     "iqr_s": row["iqr_s"], "n_A": row["n"]}
        resolved["probe1"]["floors"][unit] = fl
        g = r["generation_rate"]
        resolved["probe1"]["generation_rate"][unit] = {"method": g["method"], "G50": g["G50"], "G90": g["G90"],
                                                       "n_rates_A": g["n_rates"], "sessions_A": g["n_sessions"],
                                                       "unit": "output tokens per second"}
    resolved["probe1"]["stamp_resolution_check_A"] = {
        "source": "a1.json groups.<unit>.<sub>.gcd_abs_nonzero_delta_us (first found per unit)"}
    d = np.array(depth_pool, dtype=float)
    p75 = float(np.quantile(d, 0.75)) if len(d) else None
    pooled = int(max(3, math.ceil(p75))) if p75 is not None else None
    dt = {"rule": pc.SPEC["probe2"]["deep_first_try"]["deep"],
          "pooled": {"p75_A": p75, "n_A": int(len(d)), "sessions_A": int(len(set(depth_pool_sid))), "D": pooled,
                     "depth_quantiles_A": qstats(d, depth_pool_sid, qs=(0.25, 0.5, 0.75, 0.9), ci_qs=(0.75,))
                     if len(d) else None}}
    for unit in P2_UNITS:
        dm, ds = depth_by_unit.get(unit, ([], []))
        n, ns = len(dm), len(set(ds))
        if n >= 50 and ns >= 5:
            q = float(np.quantile(np.array(dm, dtype=float), 0.75))
            dt[unit] = {"D": int(max(3, math.ceil(q))), "p75_A": q, "n_A": n, "sessions_A": ns, "source": "unit"}
        else:
            dt[unit] = {"D": pooled, "n_A": n, "sessions_A": ns, "source": "pooled fallback (< 50 depths or < 5 sessions)"}
    resolved["probe2"]["depth_threshold"] = dt
    for unit in P3_UNITS:
        r = cal["units"].get(unit, {}).get("probe3")
        if r:
            resolved["probe3"]["long_session"][unit] = {"L75": r["L75"], "L90": r["L90"],
                                                        "sessions_A": r["sessions_with_paired_calls"]}
    nmin = n_min_power()
    resolved["probe4"]["N_min"] = {"value": nmin, "rule": "smallest N with power >= 0.80 for w = 0.15, alpha 0.01, df 15"}
    resolved["probe4"]["control_A"] = {}
    for unit in P4_UNITS:
        r = cal["units"].get(unit, {}).get("probe4")
        if not r:
            continue
        ent = {}
        for cls in ("M_git", "M_all"):
            row = r["classes"].get(cls, {})
            ent[cls] = {"symbols": row.get("symbols"), "meets_N_min": row.get("meets_N_min"),
                        "digit_test": row.get("digit_test")}
        ent["T_orig_symbols_A"] = r["classes"].get("T_orig", {}).get("symbols")
        resolved["probe4"]["control_A"][unit] = ent
    # stamp resolution from A1
    res_map = {}
    for gk, gv in a1.get("groups", {}).items():
        if isinstance(gv, dict):
            for sk, sv in gv.items():
                if isinstance(sv, dict) and "gcd_abs_nonzero_delta_us" in sv:
                    res_map.setdefault(gk, sv["gcd_abs_nonzero_delta_us"])
    resolved["probe1"]["stamp_resolution_check_A"]["values_us"] = res_map
    # ---------------------------------------------------------------- feasibility projection (informational)
    b_sess = b_session_counts()
    proj = {"formula": "A count x (B sessions / A sessions of the unit); a projection, not a measurement; it sets no "
                       "threshold and only flags cells likely to be INSUFFICIENT_N", "cells": {}}

    def add(unit, name, a_count, a_sess_unit=None):
        a_s = a_sess_unit or cal["sessions_A"].get(unit)
        b_s = b_sess.get(unit)
        if a_count is None or not a_s or b_s is None:
            return
        proj["cells"].setdefault(unit, {})[name] = {"A": a_count, "A_sessions": a_s, "B_sessions": b_s,
                                                    "projected_B": round(a_count * b_s / a_s, 1)}
    for unit, r in cal["units"].items():
        r1 = r.get("probe1")
        if r1 and "eligible_T_gen_ge_1s" in r1:
            add(unit, "p1_W_eligible_pairs", r1["eligible_T_gen_ge_1s"]["W"]["n"])
            add(unit, "p1_G_eligible_pairs", r1["eligible_T_gen_ge_1s"]["G"]["n"])
        if unit in depth_by_unit:
            D = resolved["probe2"]["depth_threshold"][unit]["D"]
            dm = depth_by_unit[unit][0]
            add(unit, "p2_deep_first_access_main", int(sum(1 for x in dm if x >= D)) if D is not None else None)
            cts = r["probe2"]["counts"]
            add(unit, "p2_first_mention_paths_main", cts.get("first_mention_path/main", 0))
        r3 = r.get("probe3")
        if r3:
            u3 = "whowhen/Algorithm-Generated" if unit == "whowhen" else unit
            a3 = cal["sessions_A"].get(u3)
            add(u3, "p3_long_sessions_L75", r3["A_sessions_at_or_above_L75"], a3)
            add(u3, "p3_failed_with_successor", r3["failed_with_successor"]["n"], a3)
        r4 = r.get("probe4")
        if r4:
            add(unit, "p4_T_orig_hex_symbols", r4["classes"]["T_orig"]["symbols"])
            add(unit, "p4_M_git_hex_symbols", r4["classes"]["M_git"]["symbols"])
            add(unit, "p4_T_orig_large_int_values", r4["classes"]["ints/T_orig"]["distinct_values"])
    resolved["feasibility_projection"] = proj
    cal["resolved_preview"] = resolved
    cal["runtime_s"] = round(time.time() - t0, 1)
    OUT.write_text(json.dumps(cal, indent=1, default=str), encoding="utf-8")
    # ---------------------------------------------------------------- prereg.json
    spec = json.loads(json.dumps(pc.SPEC))
    spec["regexes"] = pc.RX
    spec["constants"] = {"PATH_KEYS": list(pc.PATH_KEYS), "REF_CONTENT_KEYS": list(pc.REF_CONTENT_KEYS),
                         "CONFIG_EXT": sorted(pc.CONFIG_EXT), "CONSTANT_HEX": sorted(pc.CONSTANT_HEX),
                         "HEX_LENGTHS": list(pc.HEX_LENGTHS), "CODEX_SHELL_RAW": sorted(pc.CODEX_SHELL_RAW),
                         "PUBLIC_CC_TOOLS": sorted(pc.PUBLIC_CC_TOOLS),
                         "G_TOOLS": {k: sorted(v) for k, v in G_TOOLS.items()},
                         "W_KEYS": {k: sorted(v) for k, v in W_KEYS.items()},
                         "ACCESS_READ": sorted(ACCESS_READ), "ACCESS_EDIT": sorted(ACCESS_EDIT)}
    b_sessions = b_session_counts()
    aiv_cu_b = json.load(open(pc.ROOT / "analysis" / "out" / "build" / "aiv_cu_build.json", encoding="utf-8"))
    spec["population_B"] = {
        "rule": "all sessions in analysis/cache/<corpus>_B.parquet; swechat units by format from swechat_population.parquet",
        "sessions": b_sessions,
        "aiv_cu_by_stratum": aiv_cu_b["splits"]["B"]["sessions_by_stratum"],
        "sessions_A": cal["sessions_A"],
        "source": "analysis/out/build/*_build.json (sample / splits sections: session counts only)"}
    spec["resolved"] = resolved

    inputs = {}
    for name in ("a1.json", "a2.json", "a3.json", "a4.json", "a5.json", "resolve.json"):
        inputs[f"analysis/out/phase_a/{name}"] = sha256(a_out / name)
    inputs["analysis/out/phase_a.json"] = sha256(pc.ROOT / "analysis" / "out" / "phase_a.json")
    for c in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        inputs[f"analysis/cache/{c}_A.parquet"] = sha256(pc.CACHE / f"{c}_A.parquet")
    spec["provenance"] = {
        "generated_by": "analysis/probes/prereg_calibration.py",
        "spec_module": "analysis/probes/prereg_common.py",
        "spec_module_sha256": sha256(pc.ROOT / "analysis" / "probes" / "prereg_common.py"),
        "calibration_script_sha256": sha256(pc.ROOT / "analysis" / "probes" / "prereg_calibration.py"),
        "calibration_json": "analysis/out/phase_a/prereg_calibration.json",
        "calibration_json_sha256": sha256(OUT),
        "inputs_sha256": inputs,
        "phase_b_must": "assert prereg.json provenance.spec_module_sha256 == sha256(prereg_common.py) before running",
    }
    PREREG.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"done in {time.time() - t0:.1f}s -> {OUT} and {PREREG}")


if __name__ == "__main__":
    main()
