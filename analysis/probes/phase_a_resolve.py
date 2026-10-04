"""Phase A synthesis: the synthesizer's own checks of the discrepancies that the A1-A6 verifiers reported.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_resolve
Writes analysis/out/phase_a/resolve.json (raw counts only; interpretation lives in analysis/PHASE_A.md).

Data: Phase A caches only (analysis/cache/<corpus>_A.parquet; no *_B file is opened), the measurers' own JSON files
(analysis/out/phase_a/a*.json) and build reports, plus ONE targeted read of data/swe-chat-pinned/conversations.parquet
restricted to one split-A session (check R_A2.salvaged_opencode_session). cc_local outputs are aggregates only: no text,
no command, no path; tool names outside the public Claude Code tool list are collapsed.

Every check names the discrepancy it settles (DISPUTES) and the definition it uses (DEFS). Definitions were written
before the outcome of each check was computed; where a check needs a choice (a threshold, a regex), the choice is
recorded in DEFS with its reason. Nothing here changes a measurer's pre-registered verdict rule.
"""
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import error_marker, parse_ts

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUTDIR = os.path.join(ROOT, "analysis", "out", "phase_a")
OUT = os.path.join(OUTDIR, "resolve.json")
DATA = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
SEED = stats.SEED

PUBLIC_CC_TOOLS = {"shell", "read", "write", "edit", "glob", "grep", "ls", "todo", "subagent", "webfetch", "websearch",
                   "taskcreate", "taskupdate", "tasklist", "taskget", "taskoutput", "taskstop", "toolsearch",
                   "askuserquestion", "exitplanmode", "enterplanmode", "skill", "sendmessage", "notebookedit", "workflow",
                   "killshell", "bashoutput", "killbash", "monitor"}

DEFS = {
    "pairing": "first call and first result per (session_id, call_id), inner join; delta = parse_ts(result) - parse_ts(call) "
               "in integer microseconds; pairs need both stamps",
    "rates": "stats.cluster_rate (session bootstrap, 1000 draws, stats.SEED) for event rates; stats.wilson for shares of "
             "sessions; stats.cluster_quantile for quantiles",
    "A1.permission_gated_rejection": "cc_interrupt_reject result whose text starts with \"The user doesn't want to proceed\" "
                                     "or 'User rejected' (not '[Request interrupted') on a tool other than ExitPlanMode, "
                                     "EnterPlanMode, AskUserQuestion. Reason: those three wait for the human by design (A1 "
                                     "class_reason); '[Request interrupted' is an interrupt, not a permission answer",
    "A1.bash_progress_offset": "as A1: min over the call's linked bash_progress events of ((progress.ts - call.ts) - "
                               "elapsedTimeSeconds); split by the linked call's IR tool",
    "A1.not_last_block": "aiv_cc call that is not the last call row of its (session_id, api_msg_id) in seq order; its result "
                         "minus the last call row's stamp < 0 means the result was stamped before the later block",
    "A1.last_digit": "last fractional digit of distinct OpenCode ts strings (all event kinds); chi2 against uniform",
    "A2.wilson_verdict": "the A2 rule (usable if all four rates' upper bound <= 0.01) re-applied with the per-call Wilson "
                         "upper bound in place of the cluster-bootstrap upper bound; per-call Wilson ignores clustering, "
                         "so it is a second reading, not a replacement",
    "A3.loss_types": "A3's catalogue (a3.json markers_catalogue) with A3's loss types; OLD_SPILL is added as type 'spill'",
    "A3.old_spill_regex": r"^Error: result \([^)]*\) exceeds maximum allowed tokens\. Output has been saved to",
    "A3.old_spill_reason": "pattern fixed from the public corpora (aiv_cc, swechat) after the A3 verifier named the format; "
                           "applied blind to cc_local (counts only)",
    "A3.old_spill_regex_change_after_first_run": {
        "before": r"^Error: result \([\d,]+ characters\) exceeds maximum allowed tokens\. Output has been saved to",
        "after": r"^Error: result \([^)]*\) exceeds maximum allowed tokens\. Output has been saved to",
        "effect": "aiv_cc 5 -> 5; cc_local 0 -> 1",
        "reason": "the verifier described the format as 'Error: result (N characters ...)'; the first regex required the "
                  "parenthesis to hold only '<digits> characters'. A count-only probe of cc_local (no text read) found 1 "
                  "result that starts 'Error: result (' and contains 'exceeds maximum allowed tokens. Output has been "
                  "saved to' but fails the narrow form, so the parenthesis content was relaxed"},
    "A3.cc_exit_line": r"^Exit code \d+ (A3 rules.exit_line.claude_code)",
    "A3.gemini_exit_line": r"(?m)^Exit Code: (\d+)",
    "A3.glob_shape": "Glob result with exactly 101 lines whose last line starts with '(' (the shape A3 recorded for the "
                     "cc_local flag-true results; lines and last line as in A3: text.rstrip('\\n') split on '\\n')",
    "A4.codex_exit_header": "A3's Codex exit line: (?m)^(?:Exit code: (\\d+)|Process exited with code (\\d+)) within the first "
                            "600 chars; predictor H = header present with N != 0",
    "A4.codex_timeout": "(?m)^(?:timed out: |sandbox error: command timed out) (A4 supplementary family harness_timeout)",
    "A4.rule_label": "A4 prereg verdict_rule_for_a_text_proxy, read from each predictor's stored prereg_rule flags: usable "
                     "if meets_usable, partial if meets_partial, else absent",
    "A5.random_splits": "50 random 2-fold session splits: each session goes to fold 0/1 by a Bernoulli(0.5) draw from "
                        "np.random.default_rng(SEED + i), i = 0..49; Theil-Sen fit on one fold (A5 ts_fit), residual on the "
                        "other; statistic = median |cross-fit residual|; splits with < 10 pairs in a fold are skipped. "
                        "Reason: the A5 verifier reported that the single sha1 split is unrepresentative for small groups",
    "A5.codex_full_usage_out": "POST HOC (not pre-registered in A5): Codex result-only form with y = delta - usage_out_k "
                               "(reasoning tokens included) instead of delta - (usage_out_k - reasoning_k); x = appended "
                               "input chars; A5 fit, cross-fit and typical-result code paths",
    "A6.value_fill": "census 'types' counts: non-null share = 1 - types['null'] / sum(types); entries whose types carry no "
                     "null count (arrow types) are 'no_value_counts'",
}

DISPUTES = {
    "A1.rejections": "measurer: 34/126 swechat CC sessions with a permission rejection; verifier: 20/126 counting "
                     "permission-gated tools only",
    "A1.marker_speed": "measurer: cc_permission_denied machine-fast in cc_local but cc_interrupt_reject human in swechat, "
                       "'the same marker means different things'; verifier: the two markers differ, not the corpora",
    "A1.bash_progress": "measurer: 15.0% of long shell commands start > 2 s after the call; verifier: 6 of the 373 are Task "
                        "calls, shell only 13.6%",
    "A1.max_delta": "measurer: max delta is a subagent; verifier: main-thread Task call",
    "A1.not_last_block": "measurer: non-last blocks absorb later-block generation time in aiv_cc; verifier: a one-session "
                         "Write effect",
    "A1.opencode_digit": "notes: last digit uniform; verifier: OpenCode alone p 0.039",
    "A2.structural": "summary 694 vs JSON 695",
    "A2.copilot": "copilot usable on a 2-cluster bootstrap; verifier: per-call Wilson hi 0.021 > 0.01",
    "A2.zero_counts": "zero-count usable verdicts rest on a degenerate [0, 0] bootstrap",
    "A2.salvaged_session": "measurer: 162 table ids missing from raw are OpenCode REDACTED-id handling; verifier: one "
                           "salvaged, truncated OpenCode session",
    "A3.gemini_mask": "measurer: 844 masked; verifier: 840 masked + 4 unmasked head/tail cuts; masked shell 97/266",
    "A3.exit_baseline": "measurer baseline 282/285 (any marker); verifier like-for-like 'Exit code N' 233/285",
    "A3.gemini_exit_zero": "verifier: Gemini never writes 'Exit Code: 0', so masked vs unmasked compares failure rates",
    "A3.glob_flag": "verifier: the CC Glob flag is absent on 34/44 text-marked swechat Glob truncations",
    "A3.old_spill": "verifier: the catalogue misses an older CC spill format (aiv_cc 5, cc_local 1)",
    "A3.glob_shape": "measurer: text-only detection misses all 186 cc_local Glob truncations; verifier: a text shape separates them",
    "A4.rule_labels": "verifier: unit verdicts do not follow the pre-registered text-proxy rule",
    "A4.codex": "verifier: header alone R 47/49; 49/49 needs the timeout string; header on 826/842 shell results",
    "A4.aiv_cc_dependence": "verifier: 33,473/33,475 aiv_cc results share one sdk_session_id",
    "A4.cc_local_nonshell_false": "verifier: 9 non-shell cc_local results are native False (Workflow)",
    "A5.fold_variance": "verifier: single sha1 split residuals sit outside the random-split range for Gemini CLI and Codex",
    "A5.codex_full_usage_out": "verifier: subtracting full usage_out gives a 45-token residual for Codex",
    "A5.aiv_cc_dependence": "verifier: all aiv_cc fit pairs come from one sdk_session_id",
    "A6.value_fill": "verifier: fills are key presence; stop_reason / stop_sequence are mostly null",
    "A6.read_rows": "verifier: 1,794 of 4,043 A Read rows are subagent rows",
    "A6.marker_value": "verifier: extra.marker present on 0.646 of swechat results but non-null on 488/21,025",
    "A6.linkage_ids": "verifier: sourceToolAssistantUUID is already carried as IR parent_uuid",
    "A6.whowhen_hash": "verifier: Who&When question_ID is census class HASH_ID",
}

OLD_SPILL = re.compile(DEFS["A3.old_spill_regex"])
CC_EXIT = re.compile(r"^Exit code \d+")
GEM_EXIT = re.compile(r"(?m)^Exit Code: (\d+)")
CODEX_EXIT = re.compile(r"(?m)^(?:Exit code: (\d+)|Process exited with code (\d+))")
CODEX_TIMEOUT = re.compile(r"(?m)^(?:timed out: |sandbox error: command timed out)")


# ---------------------------------------------------------------------------------------------------------------- utils
def jl(s):
    if isinstance(s, str):
        try:
            v = json.loads(s)
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return {}


def sobj(series):
    return [x if isinstance(x, str) else None for x in series.astype(object)]


def load(corpus, columns, filters=None):
    path = os.path.join(CACHE, f"{corpus}_A.parquet")
    assert path.endswith("_A.parquet")
    return pd.read_parquet(path, columns=columns, filters=filters)


def with_format(df):
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
    return df.merge(pop, on="session_id", how="left")


def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "rate": p, "lo": lo, "hi": hi}


def crate_mask(mask, sids):
    mask = np.asarray(mask, dtype=bool)
    sids = np.asarray(sids, dtype=object)
    den, num = Counter(sids.tolist()), Counter(sids[mask].tolist())
    keys = list(den)
    r = stats.cluster_rate([num.get(k, 0) for k in keys], [den[k] for k in keys])
    return {k: (int(v) if k in ("num", "den") and v is not None else v) for k, v in r.items()}


def q50(values, sids):
    v = np.asarray(values, float)
    if len(v) == 0:
        return {"n": 0}
    out = stats.cluster_quantile(v, np.asarray(sids, dtype=object).astype(str), 0.5)
    out["min"], out["max"] = float(v.min()), float(v.max())
    return out


def us(a, b):
    td = b - a
    return td.days * 86_400_000_000 + td.seconds * 1_000_000 + td.microseconds


def pairs_of(df):
    """df: call + result rows. Returns the pair frame with delta_s (NaN when a stamp is missing)."""
    c = df[df.kind == "call"].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"], keep="first")
    r = df[(df.kind == "result") & df.call_id.notna()].sort_values(["session_id", "seq"]).drop_duplicates(
        ["session_id", "call_id"], keep="first")
    p = c.merge(r, on=["session_id", "call_id"], suffixes=("_c", "_r"))
    d = []
    for a, b in zip(sobj(p.ts_c), sobj(p.ts_r)):
        pa, pb = (parse_ts(a), parse_ts(b)) if (a and b) else (None, None)
        d.append(us(pa, pb) / 1e6 if (pa is not None and pb is not None) else np.nan)
    p["delta_s"] = d
    p["session_id"] = p.session_id.astype(str)
    return p


def priv(t):
    if not isinstance(t, str):
        return None
    t = t.lower()
    if t.startswith("mcp__"):
        return "mcp__*"
    return t if t in PUBLIC_CC_TOOLS else "other_tool"


# --------------------------------------------------------------------------------------------------------------- A1
def a1_checks():
    out = {}
    cols = ["session_id", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "is_subagent", "text"]
    sw = with_format(load("swechat", cols, filters=[("kind", "in", ["call", "result"])]))
    sw = sw[sw.format == "claude_code"]
    P = pairs_of(sw.drop(columns=["format"]))
    P = P[P.delta_s.notna()].copy()
    P["marker"] = [error_marker(t) if isinstance(t, str) else None for t in P.text_r.astype(object)]
    P["tool_l"] = P.tool_raw_c.astype(object).map(lambda s: s.lower() if isinstance(s, str) else None)
    n_sess = int(P.session_id.nunique())

    # A1.rejections
    rej = P[P.marker == "cc_interrupt_reject"].copy()

    def kind_of(t):
        t = t or ""
        if t.startswith("[Request interrupted"):
            return "request_interrupted"
        if t.startswith("The user doesn't want to proceed"):
            return "user_doesnt_want_to_proceed"
        if t.startswith("User rejected"):
            return "user_rejected"
        return "other"

    rej["rk"] = [kind_of(t) for t in rej.text_r.astype(object)]
    by_design = {"exitplanmode", "enterplanmode", "askuserquestion"}
    gated = rej[(rej.rk != "request_interrupted") & (~rej.tool_l.isin(by_design))]
    out["swechat_cc_interrupt_reject"] = {
        "pairs_with_both_stamps": int(len(P)), "sessions_with_pairs": n_sess,
        "results": int(len(rej)), "sessions": wil(rej.session_id.nunique(), n_sess),
        "by_text_kind": dict(Counter(rej.rk)), "by_tool": dict(Counter(rej.tool_l.fillna("<none>"))),
        "sessions_with_doesnt_want_to_proceed_text": int(rej[rej.rk == "user_doesnt_want_to_proceed"].session_id.nunique()),
        "latency_s": q50(rej.delta_s, rej.session_id),
        "permission_gated": {"results": int(len(gated)), "sessions": wil(gated.session_id.nunique(), n_sess),
                             "latency_s": q50(gated.delta_s, gated.session_id),
                             "by_tool": dict(Counter(gated.tool_l.fillna("<none>")))},
    }

    # A1.max_delta
    i = int(np.argmax(P.delta_s.to_numpy()))
    row = P.iloc[i]
    out["swechat_cc_max_delta"] = {"delta_s": float(row.delta_s), "tool": row.tool_c, "is_subagent_call": bool(row.is_subagent_c)}

    # A1.marker_speed (per corpus, per marker)
    ms = {"swechat_claude_code": {}}
    for m in ("cc_permission_denied", "cc_interrupt_reject"):
        sel = P[P.marker == m]
        ms["swechat_claude_code"][m] = {"results": int(len(sel)), "sessions": wil(sel.session_id.nunique(), n_sess),
                                        "latency_s": q50(sel.delta_s, sel.session_id),
                                        "shell_results": int((sel.tool_c == "shell").sum())}
    for corpus in ("cc_local", "aiv_cc"):
        df = load(corpus, cols, filters=[("kind", "in", ["call", "result"])])
        Q = pairs_of(df)
        Q = Q[Q.delta_s.notna()].copy()
        Q["marker"] = [error_marker(t) if isinstance(t, str) else None for t in Q.text_r.astype(object)]
        ns = int(Q.session_id.nunique())
        ms[corpus] = {}
        for m in ("cc_permission_denied", "cc_interrupt_reject"):
            sel = Q[Q.marker == m]
            ms[corpus][m] = {"results": int(len(sel)), "sessions": wil(sel.session_id.nunique(), ns),
                             "latency_s": q50(sel.delta_s, sel.session_id),
                             "shell_results": int((sel.tool_c == "shell").sum())}
        if corpus == "aiv_cc":
            out["aiv_cc_not_last_block"] = not_last_block(Q)
        del df, Q
    out["marker_latency_by_corpus"] = ms

    # A1.bash_progress
    meta = with_format(load("swechat", ["session_id", "kind", "ts", "parent_call_id", "extra"],
                            filters=[("kind", "==", "meta")]))
    meta = meta[(meta.format == "claude_code") & meta.parent_call_id.notna()]
    prog = defaultdict(list)
    for sid, ts, pc, e in zip(meta.session_id.astype(str), sobj(meta.ts), meta.parent_call_id.astype(str), meta.extra.astype(object)):
        x = jl(e)
        if x.get("type") == "bash_progress" and ts and isinstance(x.get("elapsedTimeSeconds"), (int, float)):
            prog[(sid, pc)].append((ts, x["elapsedTimeSeconds"]))
    keyed = {(s, c): (t, tool) for s, c, t, tool in zip(P.session_id, P.call_id.astype(str), sobj(P.ts_c), P.tool_c.astype(object))}
    rows = []
    for k, lst in prog.items():
        if k not in keyed:
            continue
        c0 = parse_ts(keyed[k][0])
        o = min(us(c0, parse_ts(ts)) / 1e6 - el for ts, el in lst)
        rows.append((k[0], keyed[k][1], o))
    bp = pd.DataFrame(rows, columns=["sid", "tool", "off"])
    bpo = {"linked_paired_calls": int(len(bp)), "by_tool": dict(Counter(bp.tool.fillna("<none>")))}
    for lab, g in (("all", bp), ("shell", bp[bp.tool == "shell"]), ("subagent", bp[bp.tool == "subagent"])):
        bpo[lab] = {"n": int(len(g)), "share_gt_2s": crate_mask((g.off > 2).to_numpy(), g.sid.to_numpy()) if len(g) else None,
                    "gt_2s_count": int((g.off > 2).sum()), "offset_s": q50(g.off, g.sid) if len(g) else None}
    out["swechat_cc_bash_progress_offset"] = bpo

    # A1.opencode_digit
    oc = with_format(load("swechat", ["session_id", "ts"]))
    oc = oc[(oc.format == "opencode") & oc.ts.notna()]
    distinct = sorted(set(sobj(oc.ts)))
    digits = Counter()
    for s in distinct:
        m = re.search(r"\.(\d+)", s)
        if m:
            digits[int(m.group(1)[-1])] += 1
    out["opencode_last_digit_distinct_stamps"] = {"n_stamps": int(len(oc)), "n_distinct": len(distinct),
                                                  "digit_counts": {str(k): digits.get(k, 0) for k in range(10)},
                                                  "chi2": stats.chi2_uniform([digits.get(k, 0) for k in range(10)])}
    return out


def not_last_block(Q):
    """aiv_cc: calls that are not the last call row of their API message."""
    c = load("aiv_cc", ["session_id", "seq", "kind", "call_id", "api_msg_id", "ts"], filters=[("kind", "==", "call")])
    c["session_id"] = c.session_id.astype(str)
    c = c.sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"], keep="first")
    c = c[c.api_msg_id.notna()]
    c["last"] = ~c.duplicated(["session_id", "api_msg_id"], keep="last")
    last_ts = {(s, m): t for s, m, t, l in zip(c.session_id, c.api_msg_id.astype(str), sobj(c.ts), c["last"]) if l}
    c["last_ts"] = [last_ts.get((s, m)) for s, m in zip(c.session_id, c.api_msg_id.astype(str))]
    q = Q[["session_id", "call_id", "tool_c", "ts_r", "delta_s"]].merge(
        c[["session_id", "call_id", "last", "last_ts"]], on=["session_id", "call_id"], how="inner")
    nl = q[~q["last"]].copy()
    nl["from_last"] = [us(parse_ts(lt), parse_ts(tr)) / 1e6 if (lt and tr) else np.nan for lt, tr in zip(sobj(nl.last_ts), sobj(nl.ts_r))]
    out = {"pairs_matched": int(len(q)), "not_last_pairs": int(len(nl)), "not_last_sessions": int(nl.session_id.nunique()),
           "by_tool": {}}
    for t, g in nl.groupby(nl.tool_c.astype(object).fillna("<none>")):
        if len(g) < 20:
            continue
        top = g.session_id.value_counts()
        lastg = q[q["last"] & (q.tool_c.astype(object) == t)]
        out["by_tool"][t] = {"not_last_n": int(len(g)), "sessions": int(g.session_id.nunique()),
                             "top_session_share": wil(int(top.iloc[0]), len(g)),
                             "result_before_last_block_stamp": int((g.from_last < 0).sum()),
                             "not_last_delta_p50_s": float(np.median(g.delta_s)),
                             "last_block_delta_p50_s": float(np.median(lastg.delta_s)) if len(lastg) else None,
                             "last_block_n": int(len(lastg))}
    return out


# --------------------------------------------------------------------------------------------------------------- A2
def a2_checks():
    out = {}
    a2 = json.load(open(os.path.join(OUTDIR, "a2.json"), encoding="utf-8"))
    rs = a2["by_corpus"]["swechat"]["all"]["unpaired_call_reasons"]
    structural = ["session_has_no_results", "source_has_no_results", "server_side_tool"]
    out["swechat_structural_unpaired"] = {"reasons": rs, "structural_sum": int(sum(rs.get(k, 0) for k in structural)),
                                          "unpaired_total": int(sum(rs.values()))}
    # per-call Wilson re-reading of the A2 verdict rule
    units = {f"swechat/{f}": a2["swechat_by_format"][f]["all"] for f in a2["swechat_by_format"]}
    units.update({c: a2["by_corpus"][c]["all"] for c in ("cc_local", "aiv_cc", "aiv_cu", "whowhen")})
    wv = {}
    for u, a in units.items():
        if "rates" not in a:
            continue
        row = {}
        his = []
        for m in ("orphan_results", "calls_without_result", "duplicate_call_ids", "calls_with_multi_results"):
            r = a["rates"].get(m)
            if not r:
                continue
            w = wil(r["num"], r["den"]) if r["den"] else None
            row[m] = {"num": r["num"], "den": r["den"], "bootstrap_hi": r["hi"], "wilson_hi": w["hi"] if w else None,
                      "sessions_affected": r.get("sessions_affected")}
            if w:
                his.append(w["hi"])
        row["verdict_bootstrap"] = (a2["swechat_by_format"][u.split("/")[1]]["verdict"]["verdict"] if u.startswith("swechat/")
                                    else a2["by_corpus"][u]["verdict"]["verdict"])
        row["verdict_wilson_hi"] = (row["verdict_bootstrap"] if (row["verdict_bootstrap"] == "absent" or not his) else
                                    ("usable" if max(his) <= 0.01 else "partial"))
        wv[u] = row
    out["verdict_rule_with_per_call_wilson"] = wv
    out["salvaged_opencode_session"] = salvaged_session()
    return out


def salvaged_session():
    sid = "ses_3353a8139ffeLXvY9MIuOitgt6"
    import pyarrow.parquet as pq
    ir = load("swechat", ["session_id", "kind", "call_id", "is_subagent", "parent_call_id"], filters=[("session_id", "==", sid)])
    calls = ir[ir.kind == "call"]
    cid = [c for c in calls.call_id.astype(object) if isinstance(c, str)]
    raw_ids = {c for c in cid if not c.startswith("synthetic:")}
    out = {"session_id": sid, "in_split_A": bool(len(ir) > 0), "ir_rows": int(len(ir)), "ir_calls": int(len(calls)),
           "ir_calls_synthetic_id": int(sum(c.startswith("synthetic:") for c in cid)), "ir_calls_raw_id": len(raw_ids)}
    path = os.path.join(DATA, "swe-chat-pinned", "conversations.parquet")
    pf = pq.ParquetFile(path)
    rows, red, ids = 0, 0, set()
    for g in range(pf.num_row_groups):
        t = pf.read_row_group(g, columns=["session_id", "role", "tool_call_id"]).to_pandas()
        t = t[(t.session_id == sid) & (t.role == "tool_use")]
        for c in t.tool_call_id.astype(object):
            rows += 1
            if not isinstance(c, str):
                continue
            if "REDACTED" in c:
                red += 1
                continue
            ids.add(c)
        del t
    out.update({"table_tool_use_rows": rows, "table_REDACTED_ids": red, "table_distinct_non_redacted_ids": len(ids),
                "table_ids_not_in_raw": len(ids - raw_ids), "raw_ids_not_in_table": len(raw_ids - ids),
                "build_report_document_parse_not_ok": None})
    b = json.load(open(os.path.join(ROOT, "analysis", "out", "build", "swechat_build.json"), encoding="utf-8"))
    out["build_report_document_parse_not_ok"] = b["full_population_pass"].get("document_parse_not_ok") if isinstance(
        b.get("full_population_pass"), dict) else None
    oc = b["crosscheck_conversations"]["by_format"]["opencode"]
    out["build_crosscheck_opencode"] = {k: oc.get(k) for k in ("sessions_raw_fewer", "table_minus_raw_where_raw_fewer",
                                                                "table_ids_not_in_raw", "raw_ids_not_in_table",
                                                                "table_REDACTED_ids_skipped", "raw_synthetic_ids_skipped")}
    return out


# --------------------------------------------------------------------------------------------------------------- A3
def a3_checks():
    out = {}
    a3 = json.load(open(os.path.join(OUTDIR, "a3.json"), encoding="utf-8"))
    loss = set(a3["rules"]["loss_types"])
    cat = [(m["name"], m["type"], re.compile(m["pattern"])) for m in a3["markers_catalogue"]]
    cols = ["session_id", "kind", "tool", "tool_raw", "text", "native_error", "extra"]

    def loss_hit(t):
        return any(ty in loss and rx.search(t) for _, ty, rx in cat)

    old = {}
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        r = load(corpus, cols, filters=[("kind", "==", "result")])
        if corpus == "swechat":
            r = with_format(r)
        texts = [t if isinstance(t, str) else "" for t in r.text.astype(object)]
        sids = r.session_id.astype(str).to_numpy()
        lh = np.array([loss_hit(t) for t in texts])
        osp = np.array([bool(OLD_SPILL.match(t)) for t in texts])
        tools = r.tool.astype(object).to_numpy()
        old[corpus] = {"results": int(len(r)), "sessions": int(len(set(sids))),
                       "old_spill": int(osp.sum()), "old_spill_sessions": int(len(set(sids[osp]))),
                       "old_spill_also_catalogue_loss": int((osp & lh).sum()),
                       "old_spill_by_tool": dict(Counter(priv(t) if corpus == "cc_local" else str(t) for t in tools[osp])),
                       "any_truncation_catalogue": crate_mask(lh, sids),
                       "any_truncation_catalogue_sessions": int(len(set(sids[lh]))),
                       "any_truncation_with_old_spill": crate_mask(lh | osp, sids),
                       "any_truncation_with_old_spill_sessions": int(len(set(sids[lh | osp])))}
        if corpus in ("swechat", "aiv_cc"):
            fmt = r.format.to_numpy() if corpus == "swechat" else np.array(["claude_code"] * len(r))
            ne = r.native_error.astype("boolean")
            is_cc = fmt == "claude_code"
            shell_true = is_cc & (tools == "shell") & ne.fillna(False).to_numpy()
            base = shell_true & ~lh
            k_exit = np.array([bool(CC_EXIT.match(t)) for t in texts])
            k_mark = np.array([error_marker(t) is not None for t in texts])
            elided = np.array([bool(re.search(r"\.\.\. \[\d+ characters truncated\] \.\.\.", t)) for t in texts])
            out[f"{corpus}_cc_exit_line_baseline"] = {
                "untruncated_shell_native_true": int(base.sum()), "sessions": int(len(set(sids[base]))),
                "exit_line_at_start": crate_mask(k_exit[base], sids[base]) if base.any() else None,
                "any_error_marker": crate_mask(k_mark[base], sids[base]) if base.any() else None,
                "char_elided_shell_native_true": int((shell_true & elided).sum()),
                "char_elided_exit_line_at_start": int((shell_true & elided & k_exit).sum()),
                "char_elided_sessions": int(len(set(sids[shell_true & elided])))}
            # Glob flag vs text marker
            gl = is_cc & (tools == "glob")
            tm = np.array([("(Results are truncated. Consider using a more specific path or pattern.)" in t) for t in texts])
            fl = [jl(e).get("truncated", "<absent>") for e in r.extra.astype(object)]
            fl = np.array([str(v) for v in fl], dtype=object)
            out[f"{corpus}_cc_glob_flag_vs_text"] = {
                "glob_results": int(gl.sum()),
                "text_marked": dict(Counter(fl[gl & tm].tolist())),
                "text_unmarked": dict(Counter(fl[gl & ~tm].tolist()))}
        if corpus == "cc_local":
            gl = tools == "glob"
            fl = np.array([str(jl(e).get("truncated", "<absent>")) for e in r.extra.astype(object)], dtype=object)
            shape = np.array([(t.rstrip("\n").count("\n") + 1 == 101 and t.rstrip("\n").split("\n")[-1].startswith("("))
                              if t else False for t in texts])
            out["cc_local_glob_shape_vs_flag"] = {"glob_results": int(gl.sum()),
                                                  "shape_true_by_flag": dict(Counter(fl[gl & shape].tolist())),
                                                  "shape_false_by_flag": dict(Counter(fl[gl & ~shape].tolist()))}
            ft = fl == "True"
            out["cc_local_truncation_union"] = {
                "catalogue_or_flag": crate_mask(lh | ft, sids), "catalogue_or_flag_sessions": int(len(set(sids[lh | ft]))),
                "catalogue_or_old_spill_or_flag": crate_mask(lh | osp | ft, sids),
                "catalogue_or_old_spill_or_flag_sessions": int(len(set(sids[lh | osp | ft])))}
        if corpus == "swechat":
            g = r.format.to_numpy() == "gemini"
            masked = np.array([t.startswith("<tool_output_masked>") for t in texts])
            showing = np.array([bool(re.search(r"Output too large\. Showing first [\d,]+ and last [\d,]+ characters", t)) for t in texts])
            sh = tools == "shell"
            ex = [GEM_EXIT.findall(t) for t in texts]
            has_exit = np.array([len(e) > 0 for e in ex])
            exit_zero = np.array([any(v == "0" for v in e) for e in ex])
            ne = r.native_error.astype("boolean").fillna(False).to_numpy()
            out["swechat_gemini_masking"] = {
                "results": int(g.sum()), "sessions": int(len(set(sids[g]))),
                "masked": crate_mask(masked[g], sids[g]), "masked_sessions": int(len(set(sids[g & masked]))),
                "showing_first_last": int((g & showing).sum()), "showing_and_masked": int((g & showing & masked).sum()),
                "masked_or_showing": int((g & (masked | showing)).sum()),
                "shell_results": int((g & sh).sum()), "masked_shell": int((g & sh & masked).sum()),
                "masked_shell_with_exit_line": int((g & sh & masked & has_exit).sum()),
                "unmasked_shell": int((g & sh & ~masked).sum()),
                "unmasked_shell_with_exit_line": int((g & sh & ~masked & has_exit).sum()),
                "shell_with_exit_line": int((g & sh & has_exit).sum()),
                "shell_with_exit_code_0_line": int((g & sh & exit_zero).sum()),
                "masked_shell_exit_line_native_true": int((g & sh & masked & has_exit & ne).sum())}
        del r, texts
    out["old_spill_by_corpus"] = old
    return out


# --------------------------------------------------------------------------------------------------------------- A4
def a4_checks():
    out = {}
    a4 = json.load(open(os.path.join(OUTDIR, "a4.json"), encoding="utf-8"))
    prim = {"swechat/claude_code": "native_null_neg", "cc_local": "native_null_neg", "aiv_cc": "native_null_neg",
            "swechat/codex": "native_strict", "swechat/opencode": "native_strict", "swechat/gemini": "native_strict",
            "swechat/copilot": "native_strict", "whowhen": "native_strict"}
    labels = {}
    for u, ref in prim.items():
        unit = a4["units"].get(u, {})
        row = {"primary_reference": ref}
        for sub in ("all", "shell", "other"):
            pr = ((unit.get(sub) or {}).get("pr") or {}).get(ref)
            if not pr:
                continue
            row[sub] = {}
            for name, p in pr["predictors"].items():
                f = p.get("prereg_rule") or {}
                lab = "usable" if f.get("meets_usable") else ("partial" if f.get("meets_partial") else "absent")
                row[sub][name] = {"label": lab, "min_n_met": f.get("min_n_met"), "tp": p["tp"], "fp": p["fp"], "fn": p["fn"],
                                  "precision": p["precision"]["rate"], "recall": p["recall"]["rate"],
                                  "precision_cluster_lo": p["precision"]["cluster_lo"], "recall_cluster_lo": p["recall"]["cluster_lo"]}
        labels[u] = row
    out["prereg_rule_labels"] = labels

    # Codex exit header
    r = with_format(load("swechat", ["session_id", "kind", "tool", "tool_raw", "text", "native_error"], filters=[("kind", "==", "result")]))
    r = r[(r.format == "codex") & (r.tool == "shell")]
    texts = [t if isinstance(t, str) else "" for t in r.text.astype(object)]
    sids = r.session_id.astype(str).to_numpy()
    hdr = [CODEX_EXIT.search(t[:600]) for t in texts]
    has = np.array([h is not None for h in hdr])
    nz = np.array([h is not None and int(h.group(1) or h.group(2)) != 0 for h in hdr])
    to = np.array([bool(CODEX_TIMEOUT.search(t)) for t in texts])
    ne = r.native_error.astype("boolean")
    strict = ne.notna().to_numpy()
    pos = ne.fillna(False).to_numpy()

    def pr_of(pred):
        m = strict
        tp, fp, fn = int((pred & pos & m).sum()), int((pred & ~pos & m).sum()), int((~pred & pos & m).sum())
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": crate_mask((pos & m)[pred & m], sids[pred & m]) if (pred & m).any() else None,
                "recall": crate_mask(pred[pos & m], sids[pos & m]) if (pos & m).any() else None}

    out["codex_shell"] = {"shell_results": int(len(r)), "sessions": int(len(set(sids))),
                          "header_any_value": int(has.sum()), "header_by_tool_raw": dict(Counter(r.tool_raw.astype(object)[has])),
                          "no_header_by_tool_raw": dict(Counter(r.tool_raw.astype(object)[~has])),
                          "native_strict_results": int(strict.sum()), "native_true": int(pos.sum()),
                          "H_header_nonzero": pr_of(nz), "H_or_timeout": pr_of(nz | to),
                          "positives_with_timeout_text_and_no_nonzero_header": int((pos & to & ~nz).sum()),
                          "native_null_with_nonzero_header": int((~strict & nz).sum()),
                          "native_null_with_zero_header": int((~strict & has & ~nz).sum())}
    del r, texts

    # aiv_cc sdk-session concentration
    r = load("aiv_cc", ["session_id", "kind"], filters=[("kind", "==", "result")])
    sdk = r.session_id.astype(str).str.split("/").str[0]
    vc = sdk.value_counts()
    out["aiv_cc_results_by_sdk_session"] = {"results": int(len(r)), "runs": int(r.session_id.nunique()),
                                            "distinct_sdk_sessions": int(vc.size), "top_sdk_session_results": int(vc.iloc[0]),
                                            "top_sdk_session_runs": int(r[sdk == vc.index[0]].session_id.nunique())}
    # cc_local non-shell native False (aggregates)
    r = load("cc_local", ["session_id", "kind", "tool", "native_error"], filters=[("kind", "==", "result")])
    ns = r[r.tool != "shell"]
    ne = ns.native_error.astype("boolean")
    out["cc_local_nonshell_native"] = {"true": int((ne == True).sum()), "false": int((ne == False).sum()),
                                       "null": int(ne.isna().sum()),
                                       "false_by_tool": dict(Counter(priv(t) for t in ns.tool.astype(object)[(ne == False).fillna(False).to_numpy()])),
                                       "false_sessions": int(ns[(ne == False).fillna(False).to_numpy()].session_id.nunique())}
    return out


# --------------------------------------------------------------------------------------------------------------- A5
def a5_checks():
    from analysis.probes import phase_a_a5 as A5
    out = {}
    a5 = json.load(open(os.path.join(OUTDIR, "a5.json"), encoding="utf-8"))
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
    want = ["aiv_cc", "swechat/claude_code", "swechat/opencode", "swechat/gemini", "swechat/codex", "cc_local"]
    cache = {}
    for name, corpus, flt, ctx_rule, image_rule, codex, ro, mod in A5.GROUPS:
        if name not in want:
            continue
        if corpus not in cache:
            cache[corpus] = A5.load(corpus, pop)
        D = cache[corpus]
        if flt:
            D = D[D[flt[0]].isin(flt[1])]
        P, RES, cnt = A5.build_pairs(D, ctx_rule, image_rule, codex, aiv_cu=False)
        F = P[(P.cat == "non_image") & (P.delta > 0)].reset_index(drop=True)
        x, y, s = F.x.values.astype(float), F.delta.values.astype(float), F.session_id.values
        _, cres, cok = A5.cross_fit(x, y, s)
        sha1_med = float(np.median(np.abs(cres[cok])))
        rep = a5["part2"][name]
        typ = (rep.get("typical_result") or {}).get("median_result_tokens")
        meds = random_split_medians(x, y, s, A5)
        g = {"fit_pairs": int(len(F)), "fit_sessions": int(F.session_id.nunique()),
             "sha1_split_median_abs_resid": sha1_med,
             "a5_json_median_abs_resid": ((rep["non_image_growth"]["cross_fit"]["resid"] or {}).get("median_abs") or {}).get("value"),
             "random_splits": describe_splits(meds, sha1_med),
             "typical_result_tokens_a5": typ,
             "spearman_a5": rep["non_image_growth"]["corr"]["spearman"]}
        if typ:
            g["ratio_sha1"] = sha1_med / typ
            g["ratio_random_p50"] = g["random_splits"]["p50"] / typ if g["random_splits"]["n_splits"] else None
            g["ratio_random_p95"] = g["random_splits"]["p95"] / typ if g["random_splits"]["n_splits"] else None
            g["ratio_ci_a5"] = rep["typical_result"]["cross_fit_median_abs_resid_over_median_result_tokens"]
        if ro:
            vis = (F.uout_k - F.reason_k) if codex else F.uout_k
            y2 = (F.delta - vis).values.astype(float)
            m2 = random_split_medians(F.in_chars.values.astype(float), y2, s, A5)
            _, c2, k2 = A5.cross_fit(F.in_chars.values.astype(float), y2, s)
            rtyp = (rep.get("result_only_variant") or {}).get("median_result_tokens")
            g["result_only_preregistered"] = {"sha1_split_median_abs_resid": float(np.median(np.abs(c2[k2]))),
                                              "random_splits": describe_splits(m2, float(np.median(np.abs(c2[k2])))),
                                              "typical_result_tokens_a5": rtyp}
        if name == "swechat/codex":
            g["full_usage_out_variant_POST_HOC"] = codex_full_usage_out(F, RES, s, A5)
        if name == "aiv_cc":
            sdk = pd.Series(F.session_id.astype(str)).str.split("/").str[0]
            vc = sdk.value_counts()
            g["fit_pairs_by_sdk_session"] = {"distinct_sdk_sessions": int(vc.size), "top_sdk_session_pairs": int(vc.iloc[0]),
                                             "fit_pairs": int(len(F))}
        out[name] = g
        print(f"[resolve] a5 {name} done", flush=True)
    return out


def random_split_medians(x, y, s, A5, n=50):
    uniq = np.unique(np.asarray(s).astype(str))
    sa = np.asarray(s).astype(str)
    meds = []
    for i in range(n):
        rng = np.random.default_rng(SEED + i)
        fold = dict(zip(uniq, rng.integers(0, 2, size=len(uniq))))
        h = np.array([fold[v] for v in sa])
        res = np.full(len(x), np.nan)
        ok_split = True
        for side in (0, 1):
            tr, te = h == side, h != side
            if tr.sum() < 10 or te.sum() < 10:
                ok_split = False
                break
            ft = A5.ts_fit(x[tr], y[tr])
            if ft is None:
                ok_split = False
                break
            res[te] = y[te] - (ft["intercept"] + ft["slope"] * x[te])
        if ok_split:
            meds.append(float(np.median(np.abs(res[np.isfinite(res)]))))
    return meds


def describe_splits(meds, ref):
    if not meds:
        return {"n_splits": 0}
    m = np.asarray(meds)
    return {"n_splits": int(len(m)), "p5": float(np.quantile(m, .05)), "p50": float(np.quantile(m, .5)),
            "p95": float(np.quantile(m, .95)), "min": float(m.min()), "max": float(m.max()),
            "share_of_splits_below_sha1_value": float((m < ref).mean())}


def codex_full_usage_out(F, RES, s, A5):
    y = (F.delta - F.uout_k).values.astype(float)
    x = F.in_chars.values.astype(float)
    out = {"label": "POST HOC, not pre-registered", "y_definition": "delta - usage_out_k (reasoning included)",
           "n": int(len(F)), "n_sessions": int(F.session_id.nunique()), "y_le_0_count": int((y <= 0).sum())}
    c = A5.corr(x, y, s)
    out["spearman"] = c["spearman"]
    ft = A5.ts_fit(x, y)
    out["theil_sen"] = ft
    _, cres, cok = A5.cross_fit(x, y, s)
    out["sha1_split_median_abs_resid"] = float(np.median(np.abs(cres[cok])))
    out["random_splits"] = describe_splits(random_split_medians(x, y, s, A5), out["sha1_split_median_abs_resid"])
    keep = set(zip(F.th, F.k))
    rr = RES[[t in keep for t in zip(RES.th, RES.k)]]
    if len(rr) and ft:
        rs = np.array([t.split("|")[0] for t in rr.th])
        out["median_result_tokens"] = float(np.median(rr.tlen.values) * ft["slope"])
        out["ratio_cross_fit_resid_over_typical_result"] = A5.ratio_of_medians(
            np.abs(cres[cok]), F.session_id.values[cok], rr.tlen.values * ft["slope"], rs)
    return out


# --------------------------------------------------------------------------------------------------------------- A6
def a6_checks():
    out = {}
    a6 = json.load(open(os.path.join(OUTDIR, "a6.json"), encoding="utf-8"))
    cen = json.load(open(os.path.join(OUTDIR, "a6_raw_census.json"), encoding="utf-8"))
    types = {(e["source"], e["group"], e["path"]): e.get("types") or {} for e in cen["flagged"]}

    def nonnull(t):
        vals = {k: v for k, v in (t or {}).items() if k != "type" and isinstance(v, (int, float))}
        tot = sum(vals.values())
        if not vals or tot == 0:
            return None
        return 1 - vals.get("null", 0) / tot

    cand = a6["part1_candidates"]["not_in_ir"]
    hm = [e for e in cand if e["tags"] == ["harness_measured"] and (e["raw_fill"]["rate"] or 0) >= 0.3]
    rows = Counter()
    examples, not_in_census = [], []
    for e in hm:
        t = types.get((e["source"], e["group"], e["path"]))
        v = nonnull(t) if t is not None else None
        if t is None:
            rows["not_in_census_flagged"] += 1
            not_in_census.append({"source": e["source"], "group": e["group"], "path": e["path"],
                                  "raw_fill_key_presence": e["raw_fill"]["rate"], "status": e["status"]})
        elif v is None:
            rows["no_value_counts"] += 1
        elif v < 0.5:
            rows["majority_null"] += 1
            examples.append({"source": e["source"], "group": e["group"], "path": e["path"], "types": t,
                             "raw_fill_key_presence": e["raw_fill"]["rate"], "status": e["status"]})
        else:
            rows["majority_non_null"] += 1
    out["harness_measured_fill_ge_0.3_value_fill"] = {"candidates": len(hm), "by_value_fill": dict(rows),
                                                      "majority_null_entries": examples,
                                                      "not_in_census_flagged_entries": not_in_census}
    out["stop_fields_census_types"] = [{"source": k[0], "group": k[1], "path": k[2], "types": v}
                                       for k, v in types.items() if k[2] in ("message.stop_reason", "message.stop_sequence")]
    out["whowhen_census_classes"] = [{"group": e["group"], "path": e["path"], "classes": e["classes"]}
                                     for e in cen["flagged"] if e["source"].startswith("who")]
    # Read rows by is_subagent (swechat CC) and marker value
    r = with_format(load("swechat", ["session_id", "kind", "tool", "is_subagent", "extra", "parent_uuid", "call_id", "uuid"],
                         filters=[("kind", "in", ["call", "result"])]))
    res = r[r.kind == "result"]
    cc = res[res.format == "claude_code"]
    rd = cc[cc.tool == "read"]
    out["swechat_cc_read_results"] = {"total": int(len(rd)), "is_subagent_true": int(rd.is_subagent.fillna(False).sum()),
                                      "is_subagent_false": int((~rd.is_subagent.fillna(False)).sum()),
                                      "sessions": int(rd.session_id.nunique())}
    mk = [jl(e).get("marker", "<absent>") for e in res.extra.astype(object)]
    vals = Counter("<absent>" if m == "<absent>" else ("<null>" if m is None else m) for m in mk)
    out["swechat_result_extra_marker"] = {"results": int(len(res)), "values": dict(vals),
                                          "key_present": int(sum(v for k, v in vals.items() if k != "<absent>")),
                                          "non_null": int(sum(v for k, v in vals.items() if k not in ("<absent>", "<null>")))}
    # IR link result.parent_uuid -> call.uuid (swechat CC)
    rr = r[r.format == "claude_code"]
    c = rr[rr.kind == "call"].drop_duplicates(["session_id", "call_id"])
    q = rr[rr.kind == "result"].drop_duplicates(["session_id", "call_id"])
    p = c.merge(q, on=["session_id", "call_id"], suffixes=("_c", "_r"))
    link = {}
    for lab, g in (("is_subagent_false", p[~p.is_subagent_c.fillna(False)]), ("is_subagent_true", p[p.is_subagent_c.fillna(False)])):
        link[lab] = {"pairs": int(len(g)), "result_parent_uuid_null": int(g.parent_uuid_r.isna().sum()),
                     "result_parent_uuid_eq_call_uuid": int((g.parent_uuid_r.astype(object) == g.uuid_c.astype(object)).sum())}
    out["swechat_cc_result_parent_uuid_link"] = link
    b = json.load(open(os.path.join(ROOT, "analysis", "out", "build", "swechat_build.json"), encoding="utf-8"))
    cx = b["crosscheck_conversations"]["by_format"]
    out["build_crosscheck_raw_ids_not_in_table"] = {f: cx[f].get("raw_ids_not_in_table") for f in cx}
    out["build_crosscheck_codex"] = {k: cx["codex"].get(k) for k in ("raw_calls", "raw_synthetic_ids_skipped", "raw_ids_not_in_table")}
    # census O2 encoding of the uncheckable subagent results
    ident = cen["parts"]["identities"]["swechat_sample"]
    out["census_I5_no_nested_traffic_entry"] = ident.get("I5_cc_agent_toolcount_no_nested_traffic")
    return out


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main():
    t0 = time.time()
    res = {"script": "analysis/probes/phase_a_resolve.py", "split": "A only", "seed": SEED, "DEFS": DEFS, "DISPUTES": DISPUTES}
    for name, fn in (("A1", a1_checks), ("A2", a2_checks), ("A3", a3_checks), ("A4", a4_checks), ("A5", a5_checks),
                     ("A6", a6_checks)):
        res[name] = fn()
        print(f"[resolve] {name} done {time.time() - t0:.1f}s", flush=True)
    res["runtime_s"] = round(time.time() - t0, 1)
    os.makedirs(OUTDIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(clean(res), fh, indent=1, ensure_ascii=False, allow_nan=False)
    print("wrote", OUT)


if __name__ == "__main__":
    sys.exit(main())
