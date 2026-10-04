"""Phase A5: token accounting. Which per-turn token fields exist, does any field account tool-result tokens separately
from model-generated tokens, and is "token conservation" (context growth between consecutive API calls vs the chars the
log says were appended) tight enough to be worth a Phase C probe?

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_a5
Writes RAW COUNTS ONLY to analysis/out/phase_a/a5.json. Interpretation lives in analysis/notes/phase_a_a5.md.

Inputs
  analysis/cache/<corpus>_A.parquet for swechat, cc_local, aiv_cc, aiv_cu, whowhen (Phase A split only; *_B never opened)
  analysis/cache/swechat_population.parquet (session -> format)
  analysis/out/phase_a/a6_raw_census.json (copied: raw token paths the IR does not carry; A6's own sample)
  Raw files, read-only, Phase A sessions only, for fields the IR drops (section part1.raw_A_checks):
    data/swe-chat-pinned/transcripts/<sid>.jsonl for split-A gemini sessions (tokens.* incl. tokens.tool) and split-A
    claude_code sessions (message.usage.iterations[]); data/claude-code-local/*/<sid>.jsonl (+ <sid>/**/*.jsonl) for
    split-A cc_local sessions (iterations[] lengths and type enums only: aggregates, no content).

Sections
  part1.ir_usage_fill            usage_* fill per group x kind (session-clustered CI)
  part1.extra_token_fields       every extra.* path whose name mentions token/usage/cost/turns, per group x kind
  part1.semantics                does usage_in include cached tokens; exact identities between token fields
  part1.raw_A_checks             Gemini CLI tokens.{thoughts,tool,total}; Claude usage.iterations[]
  part1.a6_uncaptured_token_paths  A6 census rows (copied, not recomputed)
  part1.separate_tool_result_accounting  counts behind the "does any field split tool-result tokens" answer
  part2.<group>                  token-conservation pairs per corpus/format/stratum (rules in PREREG)
  part2_not_feasible             groups whose usage does not allow a context measure
"""
import glob
import hashlib
import json
import os
import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from scipy.stats import rankdata, theilslopes

from analysis.lib import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.path.join(ROOT, "analysis", "out", "phase_a", "a5.json")
A6 = os.path.join(ROOT, "analysis", "out", "phase_a", "a6_raw_census.json")
DATA = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
SEED, N_BOOT = stats.SEED, stats.N_BOOT
CORPORA = ["swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
USAGE = ["usage_in", "usage_out", "usage_cache_read", "usage_cache_create"]
IMG = "[image]"

# All rules below were fixed before any conservation outcome (delta, correlation, residual) was computed. The two
# definitional checks run before writing them (usage_in vs cache_read per format; image marker spelling per corpus) do not
# involve outcomes; their results are in part1.semantics.usage_in_includes_cache and part1.image_markers.
PREREG = {
    "thread": {"value": "(session_id, is_subagent, agent_id)", "reason": "task definition; subagent streams have their own context"},
    "usage_dedupe": {"value": "rows with usage_in not null; one response per (session_id, api_msg_id); usage_out = max over its rows; "
                              "in/cache_read/cache_create taken from the first row (variation across rows counted)",
                     "reason": "USAGE DEDUPE rule in analysis/lib/ir.py"},
    "ctx": {"value": {"in+cr+cc": "usage_in + usage_cache_read + usage_cache_create (Anthropic: claude_code formats, aiv_cu anthropic-*; "
                                  "OpenCode, which stores input net of cache)",
                      "in": "usage_in only (Codex last_token_usage.input_tokens and Gemini promptTokenCount include cached tokens)"},
            "reason": "provider semantics; verified per format in part1.semantics.usage_in_includes_cache (in >= cache_read on every row "
                      "with cache_read > 0 iff the field includes cache)"},
    "zero_ctx": {"value": "responses with ctx == 0 are dropped before pairing (counted); their output rows contribute nothing",
                 "reason": "synthetic / API-error placeholders carry all-zero usage"},
    "response_rows": {"value": "non-Codex: rows of kind assistant/call/meta with the response's api_msg_id; Codex: assistant/call rows "
                               "are assigned to the first later usage-bearing token_count of the same thread (Codex writes a response's "
                               "items, then its token_count, then the tool outputs)",
                      "reason": "Codex logs no response id; token_count closes each API call"},
    "send_point": {"value": "send_k = min seq over response k's rows (Codex: its assigned output rows and its token_count)",
                   "reason": "the request is sent before any of its response rows are written"},
    "appended_chars": {"value": "out_chars(response k) + in_chars(gap) where out_chars = len(text) of its assistant rows + "
                                "len(args) + len(tool_raw) of its call rows, and in_chars = len(text) of result/user/system rows with "
                                "send_k < seq < send_{k+1} in the same thread (+ len(stderr) on aiv_cu results only) + out_chars of "
                                "orphan assistant/call rows (no usage-bearing response) in that gap. meta rows never count.",
                       "reason": "task definition. aiv_cu 'stderr' is the turn's separate 'error' field, assumed shown to the model; in "
                                 "the other corpora stderr is already inside the result text"},
    "thinking_variant": {"value": "x + thinking chars of response k (extra.thinking_chars on assistant/call rows; aiv_cu extra.reasoning_chars)",
                         "reason": "whether earlier thinking stays in context is not recorded; reported as a variant only"},
    "image_flag": {"value": {"marker": "some input row in the gap contains the parser marker '[image]' (count = occurrences)",
                             "gui_proxy": "aiv_cu only: some result in the gap belongs to a 'gui' call (the export keeps no image; GUI "
                                          "actions are assumed to return a screenshot)"},
                   "reason": "images cost tokens but have no chars; aiv_cu stores no image marker (part1.image_markers)"},
    "compaction_flag": {"value": "a meta row in the gap with extra.subtype == compact_boundary (Claude Code), entry_type == compacted or "
                                 "type == context_compacted (Codex), part_type == compaction (OpenCode)",
                        "reason": "compaction replaces context; such pairs are reported apart"},
    "categories": {"value": "compaction (flag) > image (flag) > non_image; the fit set = non_image pairs with delta > 0",
                   "reason": "task asks for an image split; negative deltas are reported as shares, not fitted"},
    "robust_fit": {"value": "Theil-Sen (scipy.stats.theilslopes) of delta on x over a seeded random subsample of at most 2000 fit-set pairs; "
                            "secondary: median-ratio fit b = median(delta/x) over x>0, a = median(delta - b x)",
                   "reason": "Theil-Sen is O(n^2); 2000 pairs keep it at ~2M slopes"},
    "cross_fit": {"value": "sessions split by sha1(session_id) parity; fit on one half, residuals on the other, both directions pooled",
                  "reason": "out-of-sample residual"},
    "typical_result": {"value": "median len(text) over result events in fit-set pairs, converted to tokens with the Theil-Sen slope",
                       "reason": "task asks for the residual relative to typical result size"},
    "result_only_variant": {"value": "groups whose per-response usage_out is final (Codex, OpenCode, Gemini CLI, aiv_cu gemini-*): "
                                     "y = delta - visible_out_k (Codex: usage_out - reasoning_output_tokens; others usage_out, which "
                                     "excludes reasoning/thoughts there), x = in_chars only",
                            "reason": "removes model-output chars->tokens error; Claude Code-format usage_out is a streaming snapshot"},
    "bootstrap": {"value": f"session-clustered, {N_BOOT} resamples, seed {SEED}; correlations recomputed exactly per resample; residual "
                           "CIs keep the full-sample fit fixed",
                  "reason": "lib/stats.py convention"},
    "verdict_rule": {"value": "on non_image fit-set pairs: TIGHT if Spearman CI low >= 0.90 and cross-fit median |residual| <= 0.25 x "
                              "typical result tokens; LOOSE if Spearman >= 0.70 and cross-fit median |residual| <= 1.0 x typical result "
                              "tokens; otherwise NOT_TIGHT; INSUFFICIENT if < 10 sessions or < 200 fit-set pairs",
                     "reason": "a length check on logged tool results is only useful if its typical error is a small fraction of one "
                               "result; 0.25 = a result changed by more than a quarter of a typical result exceeds the median residual. "
                               "Applied in the notes, not in this file"},
}

# Rules added after the first run of this script. Each is reported with its before/after effect in part2.<group>.post_hoc.
POST_HOC = {
    "usage_row_without_api_msg_id": {
        "active": True,
        "rule": "a usage-bearing row whose api_msg_id is null is its own API response (id = session + seq); assistant/call rows with "
                "a null api_msg_id and the same uuid (aiv_cu: the turn row id) are its output rows; other null-id rows stay orphans",
        "why_added": "first run: aiv_cu/gemini-pro has 119 of 752 usage rows without an id (Gemini rows with no responseId and one "
                     "call: the loader groups by md5 only for rows with >= 2 calls, so each such row is one response). The USAGE "
                     "DEDUPE rule cannot apply to them; dropping them spliced two API steps into one pair",
        "before": "rows dropped (counted in build_counts.usage_rows_without_api_msg_id); part2.<group>.post_hoc_rule_off holds the "
                  "headline numbers with the rule off for every group that has such rows"},
    "residual_diagnostics": {
        "rule": "on the fit set: Spearman of the cross-fit residual with usage_out_k (max over the response's rows) and with the "
                "thinking chars of response k",
        "why_added": "first run: Theil-Sen intercepts differ widely (about 123 to 2269 tokens per pair); diagnostic only, it changes "
                     "no other number"},
    "result_only_typical_ratio": {
        "rule": "result_only_variant also reports cross-fit median |residual| / typical result tokens (its own slope)",
        "why_added": "first run reported the variant's residual without the relative measure the task asks for"},
}

GROUPS = [
    # name, corpus, filter (column, values) or None, ctx, image rule, codex, result-only variant, gemini modality
    ("swechat/claude_code", "swechat", ("format", ["claude_code"]), "in+cr+cc", "marker", False, False, False),
    ("cc_local", "cc_local", None, "in+cr+cc", "marker", False, False, False),
    ("aiv_cc", "aiv_cc", None, "in+cr+cc", "marker", False, False, False),
    ("aiv_cu/anthropic-opus", "aiv_cu", ("stratum", ["anthropic-opus"]), "in+cr+cc", "gui_proxy", False, False, False),
    ("aiv_cu/anthropic-sonnet", "aiv_cu", ("stratum", ["anthropic-sonnet"]), "in+cr+cc", "gui_proxy", False, False, False),
    ("aiv_cu/anthropic-haiku", "aiv_cu", ("stratum", ["anthropic-haiku"]), "in+cr+cc", "gui_proxy", False, False, False),
    ("aiv_cu/anthropic-fable", "aiv_cu", ("stratum", ["anthropic-fable"]), "in+cr+cc", "gui_proxy", False, False, False),
    ("aiv_cu/anthropic-claude-code", "aiv_cu", ("stratum", ["anthropic-claude-code"]), "in+cr+cc", "gui_proxy", False, False, False),
    ("aiv_cu/anthropic_all", "aiv_cu", ("stratum", ["anthropic-opus", "anthropic-sonnet", "anthropic-haiku", "anthropic-fable",
                                                    "anthropic-claude-code"]), "in+cr+cc", "gui_proxy", False, False, False),
    ("swechat/codex", "swechat", ("format", ["codex"]), "in", "marker", True, True, False),
    ("swechat/opencode", "swechat", ("format", ["opencode"]), "in+cr+cc", "marker", False, True, False),
    ("swechat/gemini", "swechat", ("format", ["gemini"]), "in", "marker", False, True, False),
    ("aiv_cu/gemini-pro", "aiv_cu", ("stratum", ["gemini-pro"]), "in", "gui_proxy", False, True, True),
    ("aiv_cu/gemini-flash", "aiv_cu", ("stratum", ["gemini-flash"]), "in", "gui_proxy", False, True, True),
]
TOKEN_PATH_RX = re.compile(r"(?i)token|usage|cost|turns")


# ------------------------------------------------------------------------------------------------------------- helpers
def jl(s):
    if not isinstance(s, str):
        return None
    try:
        x = json.loads(s)
    except ValueError:
        return None
    return x if isinstance(x, dict) else None


def flat(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, f"{p}.{k}" if p else str(k))
    elif isinstance(o, list):
        for v in o:
            yield from flat(v, p + "[]")
    else:
        yield p, o


def half(s):
    return int(hashlib.sha1(str(s).encode()).hexdigest(), 16) % 2


def f(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "rate": p, "lo": lo, "hi": hi}


def crate(num, den, sids):
    """cluster_rate from row-level 0/1 (num) and 1 (den) arrays aggregated per session."""
    df = pd.DataFrame({"s": np.asarray(sids), "n": np.asarray(num, float), "d": np.asarray(den, float)}).groupby("s").sum()
    return stats.cluster_rate(df.n.values, df.d.values)


def cq(values, sids, q=0.5):
    v = np.asarray(values, float)
    if len(v) == 0:
        return {"q": q, "value": None, "lo": None, "hi": None, "n": 0, "n_sessions": 0}
    return stats.cluster_quantile(v, np.asarray(sids), q)


def groups_of(sids):
    uniq, inv = np.unique(np.asarray(sids), return_inverse=True)
    order = np.argsort(inv, kind="stable")
    cuts = np.cumsum(np.bincount(inv, minlength=len(uniq)))[:-1]
    return uniq, np.split(order, cuts)


def boot_iter(sids, n_boot=N_BOOT, seed=SEED):
    uniq, grp = groups_of(sids)
    rng = np.random.default_rng(seed)
    for _ in range(n_boot):
        pick = rng.integers(0, len(grp), size=len(grp))
        yield np.concatenate([grp[i] for i in pick])


def _pear(a, b):
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def _spear(a, b):
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return np.nan
    return float(np.corrcoef(rankdata(a), rankdata(b))[0, 1])


def corr(x, y, sids):
    x, y, s = np.asarray(x, float), np.asarray(y, float), np.asarray(sids)
    out = {"n": int(len(x)), "n_sessions": int(len(set(s.tolist())))}
    if len(x) < 4:
        return {**out, "pearson": None, "spearman": None}
    pp, ss = _pear(x, y), _spear(x, y)
    bp, bs = [], []
    for ii in boot_iter(s):
        bp.append(_pear(x[ii], y[ii]))
        bs.append(_spear(x[ii], y[ii]))
    bp, bs = np.asarray(bp), np.asarray(bs)
    bp, bs = bp[np.isfinite(bp)], bs[np.isfinite(bs)]
    return {**out, "pearson": {"r": f(pp), "lo": f(np.quantile(bp, .025)) if len(bp) else None, "hi": f(np.quantile(bp, .975)) if len(bp) else None},
            "spearman": {"r": f(ss), "lo": f(np.quantile(bs, .025)) if len(bs) else None, "hi": f(np.quantile(bs, .975)) if len(bs) else None}}


def ratio_of_medians(a, sa, b, sb):
    """median(a) / median(b) with a joint session bootstrap (a and b are row arrays of different units)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0 or len(b) == 0 or np.median(b) == 0:
        return {"value": None, "lo": None, "hi": None}
    ua, ga = groups_of(sa)
    ub, gb = groups_of(sb)
    ia, ib = {u: g for u, g in zip(ua, ga)}, {u: g for u, g in zip(ub, gb)}
    allu = sorted(set(ia) | set(ib))
    rng = np.random.default_rng(SEED)
    boots = []
    for _ in range(N_BOOT):
        pick = [allu[i] for i in rng.integers(0, len(allu), size=len(allu))]
        xa = np.concatenate([a[ia[u]] for u in pick if u in ia] or [np.array([])])
        xb = np.concatenate([b[ib[u]] for u in pick if u in ib] or [np.array([])])
        if len(xa) and len(xb) and np.median(xb) > 0:
            boots.append(np.median(xa) / np.median(xb))
    return {"value": f(np.median(a) / np.median(b)), "lo": f(np.quantile(boots, .025)) if boots else None,
            "hi": f(np.quantile(boots, .975)) if boots else None, "n_a": int(len(a)), "n_b": int(len(b)), "n_sessions": len(allu)}


def ts_fit(x, y, seed=SEED, cap=2000):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 10 or np.ptp(x) == 0:
        return None
    idx = np.arange(len(x))
    if len(x) > cap:
        idx = np.sort(np.random.default_rng(seed).choice(len(x), cap, replace=False))
    r = theilslopes(y[idx], x[idx])
    return {"slope": float(r.slope), "intercept": float(r.intercept), "slope_lo": float(r.low_slope), "slope_hi": float(r.high_slope),
            "n_fit": int(len(idx)), "n_available": int(len(x))}


def mr_fit(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = x > 0
    if ok.sum() < 10:
        return None
    b = float(np.median(y[ok] / x[ok]))
    a = float(np.median(y - b * x))
    return {"slope": b, "intercept": a, "n": int(ok.sum())}


def resid_summary(res, sids):
    a = np.abs(np.asarray(res, float))
    if len(a) == 0:
        return {"n": 0}
    return {"n": int(len(a)), "n_sessions": int(len(set(np.asarray(sids).tolist()))), "median_abs": cq(a, sids, 0.5),
            "p90_abs": f(np.quantile(a, .9)), "p99_abs": f(np.quantile(a, .99)),
            "signed_median": f(np.median(np.asarray(res, float))), "signed_mean": f(np.mean(np.asarray(res, float)))}


def cross_fit(x, y, sids):
    x, y, s = np.asarray(x, float), np.asarray(y, float), np.asarray(sids)
    h = np.array([half(v) for v in s])
    res = np.full(len(x), np.nan)
    fits = {}
    for side in (0, 1):
        tr, te = h == side, h != side
        ft = ts_fit(x[tr], y[tr])
        fits[f"fit_on_half{side}"] = ft
        if ft is not None:
            res[te] = y[te] - (ft["intercept"] + ft["slope"] * x[te])
    ok = np.isfinite(res)
    return fits, res, ok


# ------------------------------------------------------------------------------------------------------------- loading
COLS = ["session_id", "stratum", "seq", "kind", "tool", "tool_raw", "args", "text", "stderr", "uuid", "usage_in", "usage_out",
        "usage_cache_read", "usage_cache_create", "api_msg_id", "model", "is_subagent", "agent_id", "extra"]


def load(corpus, pop):
    d = pd.read_parquet(os.path.join(CACHE, f"{corpus}_A.parquet"), columns=COLS)
    if corpus == "swechat":
        d = d.merge(pop[["session_id", "format"]], on="session_id", how="left")
        d["grp"] = "swechat/" + d["format"].astype(str)
    elif corpus == "aiv_cu":
        d["format"] = "aiv_cu"
        d["grp"] = "aiv_cu/" + d["stratum"].astype(str)
    else:
        d["format"] = corpus
        d["grp"] = corpus
    t = d["text"].astype(object)
    d["tlen"] = t.map(lambda s: len(s) if isinstance(s, str) else 0).astype(np.int64)
    d["n_img"] = t.map(lambda s: s.count(IMG) if isinstance(s, str) else 0).astype(np.int64)
    d["slen"] = d["stderr"].astype(object).map(lambda s: len(s) if isinstance(s, str) else 0).astype(np.int64)
    d["alen"] = (d["args"].astype(object).map(lambda s: len(s) if isinstance(s, str) else 0)
                 + d["tool_raw"].astype(object).map(lambda s: len(s) if isinstance(s, str) else 0)).astype(np.int64)
    d = d.drop(columns=["text", "args", "stderr"])
    d["ex"] = d["extra"].map(jl)
    d = d.drop(columns=["extra"])
    for c in USAGE:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
    d["th"] = (d["session_id"].astype(str) + "|" + d["is_subagent"].astype(str) + "|" + d["agent_id"].astype(object).fillna("").astype(str))
    return d.sort_values(["session_id", "seq"]).reset_index(drop=True)


# -------------------------------------------------------------------------------------------------------------- part 1
def part1_fill(d):
    out = {}
    for (g, k), x in d.groupby(["grp", "kind"]):
        row = {"rows": int(len(x)), "sessions": int(x.session_id.nunique())}
        for c in USAGE + ["api_msg_id"]:
            nn = x[c].notna().values
            row[c] = {"rows_notnull": int(nn.sum()), "fill": crate(nn, np.ones(len(x)), x.session_id.values)}
            if c in USAGE:
                row[c]["rows_gt0"] = int((x[c].fillna(0) > 0).sum())
        out.setdefault(g, {})[k] = row
    return out


def part1_extra(d):
    cnt = defaultdict(lambda: {"rows": 0, "sess": set(), "numeric": 0, "nonzero": 0})
    for g, k, s, ex in zip(d.grp, d.kind, d.session_id, d.ex):
        if not ex:
            continue
        seen = set()
        for p, v in flat(ex):
            if not TOKEN_PATH_RX.search(p) or p in seen:
                continue
            seen.add(p)
            c = cnt[(g, k, p)]
            c["rows"] += 1
            c["sess"].add(s)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                c["numeric"] += 1
                c["nonzero"] += int(v != 0)
    out = {}
    for (g, k, p), c in sorted(cnt.items()):
        out.setdefault(g, {}).setdefault(k, {})[p] = {"rows": c["rows"], "sessions": len(c["sess"]), "numeric_rows": c["numeric"],
                                                      "nonzero_rows": c["nonzero"]}
    return out


def part1_semantics(d):
    out = {"usage_in_includes_cache": {}, "identities": {}, "usage_constancy_within_response": {}}
    u = d[d.usage_in.notna()]
    for g, x in u.groupby("grp"):
        cr = x.usage_cache_read.fillna(0)
        m = cr > 0
        out["usage_in_includes_cache"][g] = {"usage_rows": int(len(x)), "rows_cache_read_gt0": int(m.sum()),
                                             "rows_in_ge_cache_read": int((x.usage_in[m] >= cr[m]).sum())}
        rr = x.groupby(["session_id", "api_msg_id"]).agg(a=("usage_in", "nunique"), b=("usage_cache_read", "nunique"),
                                                         c=("usage_cache_create", "nunique"), o=("usage_out", "nunique"), n=("seq", "size"))
        out["usage_constancy_within_response"][g] = {"responses": int(len(rr)), "responses_multi_row": int((rr.n > 1).sum()),
                                                     "in_cr_cc_vary": int(((rr.a > 1) | (rr.b > 1) | (rr.c > 1)).sum()),
                                                     "usage_out_varies": int((rr.o > 1).sum())}
    ids = out["identities"]
    # aiv_cu gemini usageMetadata
    for g in ("aiv_cu/gemini-pro", "aiv_cu/gemini-flash"):
        x = u[u.grp == g]
        c = Counter()
        for _, r in x.iterrows():
            ud = (r.ex or {}).get("usage_detail") or {}
            tot = ud.get("totalTokenCount")
            if tot is None:
                continue
            c["rows_with_total"] += 1
            th = ud.get("thoughtsTokenCount") or 0
            tu = ud.get("toolUsePromptTokenCount") or 0
            c["rows_with_toolUsePromptTokenCount"] += int("toolUsePromptTokenCount" in ud)
            c["total_eq_in_out_thoughts_tooluse"] += int(tot == r.usage_in + r.usage_out + th + tu)
            pd_ = ud.get("promptTokensDetails")
            if isinstance(pd_, dict):
                c["rows_with_prompt_details"] += 1
                c["prompt_details_sum_eq_usage_in"] += int(sum(v for v in pd_.values() if isinstance(v, (int, float))) == r.usage_in)
                c["rows_prompt_image_gt0"] += int((pd_.get("IMAGE") or 0) > 0)
            cd = ud.get("cacheTokensDetails")
            if isinstance(cd, dict) and pd.notna(r.usage_cache_read):
                c["rows_with_cache_details"] += 1
                c["cache_details_sum_eq_cache_read"] += int(sum(v for v in cd.values() if isinstance(v, (int, float))) == r.usage_cache_read)
        ids[g + ":usageMetadata"] = dict(c)
    # aiv_cu anthropic thinking_tokens vs output
    c = Counter()
    for _, r in u[u.grp.str.startswith("aiv_cu/anthropic")].iterrows():
        tt = (((r.ex or {}).get("usage_detail") or {}).get("output_tokens_details") or {}).get("thinking_tokens")
        if tt is None:
            continue
        c["rows_with_thinking_tokens"] += 1
        c["thinking_tokens_gt0"] += int(tt > 0)
        c["thinking_tokens_le_usage_out"] += int(tt <= r.usage_out)
    ids["aiv_cu/anthropic:output_tokens_details.thinking_tokens"] = dict(c)
    # codex
    c = Counter()
    for _, r in d[(d.grp == "swechat/codex") & (d.kind == "meta")].iterrows():
        ex = r.ex or {}
        tt = ex.get("total_token_usage")
        if isinstance(tt, dict) and tt.get("total_tokens") is not None:
            c["token_count_rows_with_total"] += 1
            c["cum_total_eq_in_plus_out"] += int(tt["total_tokens"] == (tt.get("input_tokens") or 0) + (tt.get("output_tokens") or 0))
            c["cum_reasoning_le_cum_out"] += int((tt.get("reasoning_output_tokens") or 0) <= (tt.get("output_tokens") or 0))
        if pd.notna(r.usage_in) and ex.get("reasoning_output_tokens") is not None:
            c["last_rows_with_reasoning"] += 1
            c["last_reasoning_gt0"] += int(ex["reasoning_output_tokens"] > 0)
            c["last_reasoning_le_usage_out"] += int(ex["reasoning_output_tokens"] <= r.usage_out)
    ids["swechat/codex:token_count"] = dict(c)
    # opencode
    c = Counter()
    for _, r in u[u.grp == "swechat/opencode"].iterrows():
        ex = r.ex or {}
        c["step_finish_rows"] += 1
        c["reasoning_tokens_gt0"] += int((ex.get("reasoning_tokens") or 0) > 0)
        c["cost_gt0"] += int((ex.get("cost") or 0) > 0)
        c["cost_present"] += int(ex.get("cost") is not None)
    ids["swechat/opencode:step_finish"] = dict(c)
    # aiv_cc result rows
    c = Counter()
    for _, r in d[(d.grp == "aiv_cc") & (d.kind == "meta")].iterrows():
        ex = r.ex or {}
        if ex.get("entry_type") != "result":
            continue
        c["result_rows"] += 1
        for k in ("num_turns", "total_cost_usd", "duration_ms", "duration_api_ms"):
            c[f"{k}_present"] += int(ex.get(k) is not None)
        c["usage_columns_on_result_rows"] += int(pd.notna(r.usage_in))
    ids["aiv_cc:result_rows"] = dict(c)
    return out


def part1_image_markers(d):
    out = {}
    for (g, k), x in d.groupby(["grp", "kind"]):
        n = int((x.n_img > 0).sum())
        if n:
            out.setdefault(g, {})[k] = {"rows_with_[image]": n, "occurrences": int(x.n_img.sum()), "sessions": int(x[x.n_img > 0].session_id.nunique())}
    return out


def raw_gemini(sids):
    c = Counter()
    sess = defaultdict(set)
    vals = defaultdict(list)
    for s in sids:
        p = os.path.join(DATA, "swe-chat-pinned", "transcripts", f"{s}.jsonl")
        try:
            doc = json.load(open(p, encoding="utf-8"))
        except (ValueError, OSError):
            c["files_unreadable"] += 1
            continue
        c["files"] += 1
        for m in doc.get("messages", []) if isinstance(doc, dict) else []:
            if not isinstance(m, dict) or m.get("type") != "gemini":
                continue
            c["gemini_messages"] += 1
            tk = m.get("tokens")
            if not isinstance(tk, dict):
                continue
            c["messages_with_tokens"] += 1
            for k, v in tk.items():
                c[f"key:{k}"] += 1
                sess[k].add(s)
                if isinstance(v, (int, float)):
                    vals[k].append(v)
                    c[f"nonzero:{k}"] += int(v != 0)
            if all(isinstance(tk.get(k), (int, float)) for k in ("input", "output", "thoughts", "tool", "total")):
                c["total_eq_input_output_thoughts_tool"] += int(tk["total"] == tk["input"] + tk["output"] + tk["thoughts"] + tk["tool"])
                c["total_eq_input_output_thoughts"] += int(tk["total"] == tk["input"] + tk["output"] + tk["thoughts"])
                c["identity_rows"] += 1
            if isinstance(tk.get("input"), (int, float)) and isinstance(tk.get("cached"), (int, float)):
                c["input_ge_cached"] += int(tk["input"] >= tk["cached"])
    return {"counts": dict(c), "sessions_per_key": {k: len(v) for k, v in sess.items()},
            "describe": {k: stats.describe(v) for k, v in vals.items()}}


def _iter_usage_dicts(o, loc=""):
    if isinstance(o, dict):
        if isinstance(o.get("iterations"), list):
            yield loc, o
        for k, v in o.items():
            if k != "iterations":
                yield from _iter_usage_dicts(v, k if k in ("message", "toolUseResult", "data") and not loc else loc)
    elif isinstance(o, list):
        for v in o:
            yield from _iter_usage_dicts(v, loc)


def raw_iterations(paths):
    """Aggregate-only census of usage.iterations[] lists (lengths, iteration type enums, equality with the parent usage)."""
    c = Counter()
    lens = Counter()
    types = Counter()
    for p in paths:
        c["files"] += 1
        try:
            fh = open(p, encoding="utf-8", errors="replace")
        except OSError:
            c["files_unreadable"] += 1
            continue
        with fh:
            for line in fh:
                if '"iterations"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    c["bad_lines"] += 1
                    continue
                for loc, u in _iter_usage_dicts(e):
                    it = u["iterations"]
                    lens[len(it)] += 1
                    c[f"lists_at:{loc or 'root'}"] += 1
                    for x in it:
                        if isinstance(x, dict):
                            t = x.get("type")
                            types[t if isinstance(t, str) and re.fullmatch(r"[a-z_]{1,40}", t) else "<other>"] += 1
                    if len(it) == 1 and isinstance(it[0], dict):
                        c["single_iteration_lists"] += 1
                        c["single_iteration_equals_parent_in_cr_cc"] += int(all(it[0].get(k) == u.get(k) for k in
                                                                               ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")))
    return {"counts": dict(c), "list_length": {str(k): v for k, v in sorted(lens.items())}, "iteration_type": dict(types)}


def part1_raw(pop, d_sw, a_cc_local):
    out = {}
    a_sw = set(d_sw.session_id.unique())
    p = pop[pop.session_id.isin(a_sw)]
    out["swechat_gemini_tokens_A"] = {"sessions": int((p.format == "gemini").sum()),
                                      **raw_gemini(sorted(p[p.format == "gemini"].session_id))}
    cc_paths = [os.path.join(DATA, "swe-chat-pinned", "transcripts", f"{s}.jsonl") for s in sorted(p[p.format == "claude_code"].session_id)]
    out["swechat_claude_code_usage_iterations_A"] = {"sessions": len(cc_paths), **raw_iterations(cc_paths)}
    root = os.path.join(DATA, "claude-code-local")
    paths = []
    found = 0
    for s in sorted(a_cc_local):
        m = glob.glob(os.path.join(root, "*", f"{s}.jsonl"))
        found += int(bool(m))
        paths += m
        for dd in glob.glob(os.path.join(root, "*", s)):
            paths += glob.glob(os.path.join(dd, "**", "*.jsonl"), recursive=True)
    out["cc_local_usage_iterations_A"] = {"sessions": len(a_cc_local), "sessions_root_file_found": found,
                                          "scope": "root main file + its directory JSONL per split-A session (other family members' "
                                                   "main files not read)", **raw_iterations(paths)}
    return out


def part1_a6():
    try:
        a6 = json.load(open(A6, encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "a6_raw_census.json unreadable"}
    rows = []
    for r in a6.get("flagged", []):
        if "TOKEN" not in (r.get("classes") or []) and not re.search(r"(?i)token|usage", r.get("path", "")):
            continue
        rows.append({k: r.get(k) for k in ("source", "group", "path", "classes", "n_rec", "n_records", "captured", "fill")})
    return {"source": "analysis/out/phase_a/a6_raw_census.json (flagged rows; A6's own sample, see its meta.rules.samples; "
                      "not restricted to split A)", "n_rows": len(rows),
            "uncaptured_rows": [r for r in rows if r["captured"] in (None, "not_ir_source")],
            "captured_rows": [r for r in rows if r["captured"] not in (None, "not_ir_source")]}


# -------------------------------------------------------------------------------------------------------------- part 2
def is_compaction(ex):
    if not ex:
        return False
    return (ex.get("subtype") == "compact_boundary" or ex.get("entry_type") == "compacted"
            or (ex.get("entry_type") == "event_msg" and ex.get("type") == "context_compacted") or ex.get("part_type") == "compaction")


def think_of(ex):
    if not ex:
        return 0
    return int(ex.get("thinking_chars") or 0) + int(ex.get("reasoning_chars") or 0)


def build_pairs(D, ctx_rule, image_rule, codex, aiv_cu, noid_rule=True):
    cnt = Counter()
    D = D.copy()
    D["rid"] = [f"{s}{m}" if isinstance(m, str) else None for s, m in zip(D.session_id, D.api_msg_id)]
    noid = (D.usage_in.notna() & D.rid.isna()).values
    cnt["usage_rows"] = int(D.usage_in.notna().sum())
    cnt["usage_rows_without_api_msg_id"] = int(noid.sum())
    if noid_rule and noid.any():  # each such row is its own API response (POST_HOC.usage_row_without_api_msg_id)
        nid = {(s, u): f"{s}noid:{q}" for s, u, q in zip(D.session_id[noid], D.uuid.astype(object)[noid], D.seq[noid])}
        D.loc[noid, "rid"] = [nid[(s, u)] for s, u in zip(D.session_id[noid], D.uuid.astype(object)[noid])]
        sib = (D.rid.isna() & D.kind.isin(["assistant", "call"])).values
        cand = [nid.get((s, u)) if isinstance(u, str) else None for s, u in zip(D.session_id[sib], D.uuid.astype(object)[sib])]
        D.loc[sib, "rid"] = cand
        cnt["noid_sibling_rows_attached"] = int(sum(c is not None for c in cand))
    U = D[D.usage_in.notna() & D.rid.notna()]
    R = U.groupby("rid", sort=False).agg(
        sid=("session_id", "first"), th=("th", "first"), seq0=("seq", "min"), uin=("usage_in", "first"), ucr=("usage_cache_read", "first"),
        ucc=("usage_cache_create", "first"), uout=("usage_out", "max"), nth=("th", "nunique"))
    cnt["responses"] = int(len(R))
    cnt["responses_in_gt1_thread"] = int((R.nth > 1).sum())
    R["ctx"] = R.uin + ((R.ucr.fillna(0) + R.ucc.fillna(0)) if ctx_rule == "in+cr+cc" else 0)
    # reasoning tokens (codex) and gemini modality details, from the first usage row of each response
    first = U.drop_duplicates("rid")
    exm = dict(zip(first.rid, first.ex))
    R["reason_tok"] = [float(((exm.get(i) or {}).get("reasoning_output_tokens")) or 0) for i in R.index]
    R["img_tok"] = [float((((exm.get(i) or {}).get("usage_detail") or {}).get("promptTokensDetails") or {}).get("IMAGE") or 0) for i in R.index]
    R["txt_tok"] = [float((((exm.get(i) or {}).get("usage_detail") or {}).get("promptTokensDetails") or {}).get("TEXT") or 0) for i in R.index]
    R["has_mod"] = [isinstance(((exm.get(i) or {}).get("usage_detail") or {}).get("promptTokensDetails"), dict) for i in R.index]
    outk = D.kind.isin(["assistant", "call"]).values
    if not codex:
        rset = set(R.index)
        okk = outk | (D.kind == "meta").values
        D["resp"] = [r if (o and r is not None and r in rset) else None for r, o in zip(D.rid, okk)]
    else:
        resp = [None] * len(D)
        for th, idx in D.groupby("th", sort=False).indices.items():
            sub = D.iloc[idx]
            tcm = (sub.usage_in.notna() & sub.rid.notna()).values
            tcs = sub.seq.values[tcm]
            tid = sub.rid.values[tcm]
            for i, sq, k, isu in zip(idx, sub.seq.values, sub.kind.values, tcm):
                if isu:
                    resp[i] = tid[np.searchsorted(tcs, sq)]
                elif k in ("assistant", "call"):
                    p = np.searchsorted(tcs, sq)
                    if p < len(tcs):
                        resp[i] = tid[p]
        D["resp"] = resp
    send = D[D.resp.notna()].groupby("resp").seq.min()
    R["send"] = [send.get(i, np.nan) for i in R.index]
    O = D[outk & D.resp.notna().values]
    o_chars = (O.tlen.where(O.kind == "assistant", 0) + O.alen.where(O.kind == "call", 0)).groupby(O.resp).sum()
    o_think = O.ex.map(think_of).groupby(O.resp).sum()
    o_nrows = O.groupby("resp").size()
    R["out_chars"] = [float(o_chars.get(i, 0)) for i in R.index]
    R["think"] = [float(o_think.get(i, 0)) for i in R.index]
    R["out_rows"] = [int(o_nrows.get(i, 0)) for i in R.index]
    orph = D[outk & D.resp.isna().values]
    cnt["orphan_output_rows"] = int(len(orph))
    zero = R.ctx <= 0
    cnt["responses_ctx_zero_dropped"] = int(zero.sum())
    cnt["responses_ctx_null"] = int(R.ctx.isna().sum())
    cnt["responses_without_output_rows"] = int((R.out_rows == 0).sum())
    R = R[~zero & R.ctx.notna() & R.send.notna()]
    # input-type rows
    I = D[D.kind.isin(["result", "user", "system"])].copy()
    I["chars"] = I.tlen + (I.slen.where(I.kind == "result", 0) if aiv_cu else 0)
    I["is_res"] = (I.kind == "result").astype(int)
    I["gui"] = ((I.kind == "result") & (I.tool == "gui")).astype(int)
    orph = orph.assign(chars=orph.tlen.where(orph.kind == "assistant", 0) + orph.alen.where(orph.kind == "call", 0), is_res=0, gui=0)
    I = pd.concat([I[["th", "seq", "chars", "is_res", "gui", "n_img", "tlen", "session_id"]],
                   orph[["th", "seq", "chars", "is_res", "gui", "n_img", "tlen", "session_id"]]])
    I["orphan"] = np.r_[np.zeros(len(I) - len(orph)), np.ones(len(orph))]
    M = D[(D.kind == "meta") & D.ex.map(is_compaction)][["th", "seq"]]
    Ig = I.groupby("th").indices
    Mg = M.groupby("th").indices
    pairs, results = [], []
    for th, Rt in R.groupby("th", sort=False):
        Rt = Rt.sort_values("send")
        sends = Rt.send.values
        n = len(sends)
        if n < 2:
            cnt["threads_lt2_responses"] += 1
            continue
        cnt["threads_used"] += 1
        agg = np.zeros((n, 7))  # chars, n_inputs, n_res, res_chars, n_img, n_gui, orphan chars
        if th in Ig:
            Ii = I.iloc[Ig[th]]
            k = np.searchsorted(sends, Ii.seq.values, side="right") - 1
            ok = (k >= 0) & (k < n - 1)
            cnt["input_rows_before_first_response"] += int((k < 0).sum())
            cnt["input_rows_after_last_response"] += int((k >= n - 1).sum())
            kk = k[ok]
            Iv = Ii[ok]
            np.add.at(agg[:, 0], kk, Iv.chars.values)
            np.add.at(agg[:, 1], kk, 1)
            np.add.at(agg[:, 2], kk, Iv.is_res.values)
            np.add.at(agg[:, 3], kk, (Iv.tlen * Iv.is_res).values)
            np.add.at(agg[:, 4], kk, Iv.n_img.values)
            np.add.at(agg[:, 5], kk, Iv.gui.values)
            np.add.at(agg[:, 6], kk, (Iv.chars * Iv.orphan).values)
            rr = Iv[Iv.is_res == 1]
            for kx, tl in zip(kk[(Iv.is_res == 1).values], rr.tlen.values):
                results.append((th, int(kx), float(tl)))
        comp = np.zeros(n)
        if th in Mg:
            Mi = M.iloc[Mg[th]]
            k = np.searchsorted(sends, Mi.seq.values, side="right") - 1
            ok = (k >= 0) & (k < n - 1)
            np.add.at(comp, k[ok], 1)
        sid = Rt.sid.values[0]
        ctx = Rt.ctx.values
        for j in range(n - 1):
            pairs.append({"session_id": sid, "th": th, "k": j, "ctx_k": ctx[j], "ctx_k1": ctx[j + 1], "delta": ctx[j + 1] - ctx[j],
                          "out_chars": Rt.out_chars.values[j], "think": Rt.think.values[j], "in_chars": agg[j, 0],
                          "n_inputs": agg[j, 1], "n_res": agg[j, 2], "res_chars": agg[j, 3], "n_img": agg[j, 4], "n_gui": agg[j, 5],
                          "orphan_chars": agg[j, 6], "comp": comp[j], "uout_k": Rt.uout.values[j], "reason_k": Rt.reason_tok.values[j],
                          "d_img": Rt.img_tok.values[j + 1] - Rt.img_tok.values[j], "d_txt": Rt.txt_tok.values[j + 1] - Rt.txt_tok.values[j],
                          "has_mod": bool(Rt.has_mod.values[j] and Rt.has_mod.values[j + 1])})
    P = pd.DataFrame(pairs)
    RES = pd.DataFrame(results, columns=["th", "k", "tlen"])
    if len(P):
        P["x"] = P.out_chars + P.in_chars
        P["image"] = (P.n_img > 0) if image_rule == "marker" else (P.n_gui > 0)
        P["cat"] = np.where(P.comp > 0, "compaction", np.where(P.image, "image", "non_image"))
    return P, RES, cnt


def analyze_xy(x, y, s, label_x="x"):
    """Correlation, ratio, fits and residuals for one (x, y) definition on the fit set."""
    x, y, s = np.asarray(x, float), np.asarray(y, float), np.asarray(s)
    out = {"n": int(len(x)), "n_sessions": int(len(set(s.tolist())))}
    if len(x) < 10:
        return out
    out["corr"] = corr(x, y, s)
    ok = y > 0
    out[f"{label_x}_over_delta"] = {"describe": stats.describe(x[ok] / y[ok]), "median": cq(x[ok] / y[ok], s[ok]),
                                    "pooled": stats.cluster_rate(*_per_sess(x[ok], y[ok], s[ok]))}
    ft = ts_fit(x, y)
    out["theil_sen"] = ft
    out["median_ratio_fit"] = mr_fit(x, y)
    if ft:
        res = y - (ft["intercept"] + ft["slope"] * x)
        out["resid_in_sample"] = resid_summary(res, s)
        out["abs_resid_over_delta"] = cq(np.abs(res[ok]) / y[ok], s[ok]) if ok.sum() else None
    mr = out["median_ratio_fit"]
    if mr:
        out["resid_median_ratio_fit"] = resid_summary(y - (mr["intercept"] + mr["slope"] * x), s)
    fits, cres, cok = cross_fit(x, y, s)
    out["cross_fit"] = {**fits, "resid": resid_summary(cres[cok], s[cok])}
    out["_res_cross"] = cres
    return out


def _per_sess(num, den, s):
    df = pd.DataFrame({"s": s, "a": num, "b": den}).groupby("s").sum()
    return df.a.values, df.b.values


def strip_private(o):
    if isinstance(o, dict):
        return {k: strip_private(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [strip_private(v) for v in o]
    return o


def analyze_group(name, D, ctx_rule, image_rule, codex, result_only, modality, noid_rule=True):
    P, RES, cnt = build_pairs(D, ctx_rule, image_rule, codex, aiv_cu=name.startswith("aiv_cu"), noid_rule=noid_rule)
    out = {"ctx_rule": ctx_rule, "image_rule": image_rule, "sessions": int(D.session_id.nunique()),
           "threads": int(D.th.nunique()), "build_counts": dict(cnt)}
    if not len(P):
        out["pairs"] = 0
        return out
    out["pairs"] = int(len(P))
    out["pair_sessions"] = int(P.session_id.nunique())
    out["pair_threads"] = int(P.th.nunique())
    out["ctx_describe"] = stats.describe(P.ctx_k.values)
    out["category_counts"] = P.cat.value_counts().to_dict()
    s = P.session_id.values
    one = np.ones(len(P))
    out["delta_sign_all_pairs"] = {"neg": crate((P.delta < 0).values, one, s), "zero": crate((P.delta == 0).values, one, s),
                                   "neg_count": int((P.delta < 0).sum()), "zero_count": int((P.delta == 0).sum())}
    out["delta_sign_by_category"] = {}
    for c, g in P.groupby("cat"):
        o1 = np.ones(len(g))
        out["delta_sign_by_category"][c] = {"n": int(len(g)), "n_sessions": int(g.session_id.nunique()),
                                            "neg": crate((g.delta < 0).values, o1, g.session_id.values),
                                            "zero": crate((g.delta == 0).values, o1, g.session_id.values),
                                            "neg_count": int((g.delta < 0).sum()), "zero_count": int((g.delta == 0).sum()),
                                            "delta_describe": stats.describe(g.delta.values)}
    neg = P[P.delta < 0]
    out["negative_deltas"] = {"n": int(len(neg)), "with_compaction_marker": int((neg.comp > 0).sum()),
                              "delta_describe": stats.describe(neg.delta.values),
                              "ctx_k1_over_ctx_k_describe": stats.describe((neg.ctx_k1 / neg.ctx_k).values)}
    # split by image, fit on non_image growth pairs
    F = P[(P.cat == "non_image") & (P.delta > 0)]
    out["fit_set"] = {"n": int(len(F)), "n_sessions": int(F.session_id.nunique())}
    main = analyze_xy(F.x.values, F.delta.values, F.session_id.values)
    res_cross = main.pop("_res_cross", None)
    out["non_image_growth"] = main
    out["non_image_all_pairs_corr"] = corr(P[P.cat == "non_image"].x.values, P[P.cat == "non_image"].delta.values,
                                           P[P.cat == "non_image"].session_id.values)
    ft = main.get("theil_sen")
    # image pairs under the non-image fit
    G = P[(P.cat == "image")]
    img = {"n": int(len(G)), "n_sessions": int(G.session_id.nunique())}
    if len(G) >= 10:
        Gp = G[G.delta > 0]
        img["growth_corr"] = corr(Gp.x.values, Gp.delta.values, Gp.session_id.values) if len(Gp) >= 10 else None
        img["x_over_delta_median"] = cq((Gp.x / Gp.delta).values, Gp.session_id.values) if len(Gp) else None
        if ft:
            r = G.delta.values - (ft["intercept"] + ft["slope"] * G.x.values)
            img["resid_under_non_image_fit"] = resid_summary(r, G.session_id.values)
            per = G.n_img.values if image_rule == "marker" else G.n_gui.values
            ok = per > 0
            img["resid_per_image_tokens"] = {"median": cq(r[ok] / per[ok], G.session_id.values[ok]),
                                             "describe": stats.describe(r[ok] / per[ok]),
                                             "unit": "images ('[image]' occurrences)" if image_rule == "marker" else "gui results in the gap"}
    out["image"] = img
    # typical result size and residual relative to it
    if ft and len(F):
        keep = set(zip(F.th, F.k))
        rr = RES[[t in keep for t in zip(RES.th, RES.k)]] if len(RES) else RES
        rs = np.array([t.split("|")[0] for t in rr.th]) if len(rr) else np.array([])
        typ = {"result_events": int(len(rr)), "median_result_chars": cq(rr.tlen.values, rs) if len(rr) else None,
               "result_chars_describe": stats.describe(rr.tlen.values) if len(rr) else None,
               "slope_tokens_per_char": ft["slope"]}
        if len(rr):
            typ["median_result_tokens"] = f(np.median(rr.tlen.values) * ft["slope"])
            ok = np.isfinite(res_cross)
            typ["cross_fit_median_abs_resid_over_median_result_tokens"] = ratio_of_medians(
                np.abs(res_cross[ok]), F.session_id.values[ok], rr.tlen.values * ft["slope"], rs)
            single = F[F.n_res == 1]
            if len(single) >= 10:
                typ["single_result_pairs"] = {"n": int(len(single)), "median_in_chars": cq(single.in_chars.values, single.session_id.values)}
        out["typical_result"] = typ
    # thinking variant
    tv = analyze_xy((F.x + F.think).values, F.delta.values, F.session_id.values)
    tv.pop("_res_cross", None)
    out["non_image_growth_with_thinking"] = {k: tv.get(k) for k in ("n", "n_sessions", "corr", "x_over_delta", "theil_sen", "cross_fit")}
    out["thinking_chars_share_of_fit_set_x"] = f(F.think.sum() / max((F.x + F.think).sum(), 1))
    out["orphan_chars_share_of_fit_set_x"] = f(F.orphan_chars.sum() / max(F.x.sum(), 1))
    # result-only variant
    if result_only:
        vis = (F.uout_k - F.reason_k) if codex else F.uout_k
        y2 = (F.delta - vis).values
        rv = analyze_xy(F.in_chars.values, y2, F.session_id.values, label_x="in_chars")
        rv.pop("_res_cross", None)
        rv["y_definition"] = "delta - (usage_out_k - reasoning_output_tokens_k)" if codex else "delta - usage_out_k"
        rv["y_le_0_count"] = int((y2 <= 0).sum())
        rts = rv.get("theil_sen")
        if rts and ft and len(F):
            keep = set(zip(F.th, F.k))
            rr = RES[[t in keep for t in zip(RES.th, RES.k)]] if len(RES) else RES
            if len(rr):
                rs = np.array([t.split("|")[0] for t in rr.th])
                _, cres2, cok2 = cross_fit(F.in_chars.values, y2, F.session_id.values)
                rv["median_result_tokens"] = f(np.median(rr.tlen.values) * rts["slope"])
                rv["cross_fit_median_abs_resid_over_median_result_tokens"] = ratio_of_medians(
                    np.abs(cres2[cok2]), F.session_id.values[cok2], rr.tlen.values * rts["slope"], rs)
        out["result_only_variant"] = rv
    # post-hoc diagnostics (POST_HOC.residual_diagnostics)
    if res_cross is not None and len(F):
        ok = np.isfinite(res_cross)
        out["post_hoc_residual_diagnostics"] = {
            "spearman_resid_vs_usage_out_k": corr(res_cross[ok], F.uout_k.values[ok], F.session_id.values[ok]),
            "spearman_resid_vs_thinking_chars_k": corr(res_cross[ok], F.think.values[ok], F.session_id.values[ok]),
            "usage_out_k_describe": stats.describe(F.uout_k.values),
            "share_pairs_with_thinking_chars_gt0": crate((F.think > 0).values, np.ones(len(F)), F.session_id.values)}
    # gemini modality split (aiv_cu)
    if modality:
        Q = P[P.has_mod & (P.cat != "compaction")]
        mo = {"pairs_with_modality_details": int(len(Q)), "n_sessions": int(Q.session_id.nunique())}
        for lab, g in (("gap_has_gui_result", Q[Q.n_gui > 0]), ("gap_has_no_gui_result", Q[Q.n_gui == 0])):
            o1 = np.ones(len(g))
            mo[lab] = {"n": int(len(g)), "n_sessions": int(g.session_id.nunique()),
                       "share_d_image_gt0": crate((g.d_img > 0).values, o1, g.session_id.values) if len(g) else None,
                       "share_d_image_lt0": crate((g.d_img < 0).values, o1, g.session_id.values) if len(g) else None,
                       "d_image_describe": stats.describe(g.d_img.values)}
            gp = g[g.d_txt > 0]
            if len(gp) >= 10:
                tv2 = analyze_xy(gp.x.values, gp.d_txt.values, gp.session_id.values)
                tv2.pop("_res_cross", None)
                mo[lab]["text_modality_growth"] = {k: tv2.get(k) for k in ("n", "n_sessions", "corr", "x_over_delta", "theil_sen", "cross_fit")}
        out["gemini_modality"] = mo
    return out


# ---------------------------------------------------------------------------------------------------------------- main
def main():
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
    res = {"meta": {"script": "analysis/probes/phase_a_a5.py", "split": "A only (analysis/cache/*_A.parquet)", "seed": SEED,
                    "n_boot": N_BOOT, "generated_utc": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")},
           "PREREG": PREREG, "POST_HOC": {k: {kk: vv for kk, vv in v.items() if kk != "active"} for k, v in POST_HOC.items()},
           "inputs": {}, "part1": {}, "part2": {}, "part2_not_feasible": {}}
    p1 = res["part1"]
    for k in ("ir_usage_fill", "extra_token_fields", "semantics", "image_markers"):
        p1[k] = {}
    cache = {}
    for c in CORPORA:
        d = load(c, pop)
        res["inputs"][c] = {"rows": int(len(d)), "sessions": int(d.session_id.nunique()),
                            "groups": {g: int(x.session_id.nunique()) for g, x in d.groupby("grp")}}
        p1["ir_usage_fill"].update(part1_fill(d))
        p1["extra_token_fields"].update(part1_extra(d))
        sem = part1_semantics(d)
        for k, v in sem.items():
            p1["semantics"].setdefault(k, {}).update({kk: vv for kk, vv in v.items() if vv})
        p1["image_markers"].update(part1_image_markers(d))
        cache[c] = d
        print(f"loaded {c}: {len(d)} rows", flush=True)
    p1["raw_A_checks"] = part1_raw(pop, cache["swechat"], set(cache["cc_local"].session_id.unique()))
    print("raw checks done", flush=True)
    p1["a6_uncaptured_token_paths"] = part1_a6()
    # counts behind the "separate tool-result accounting" answer
    sep = {}
    cu = cache["aiv_cu"]
    for g in ("aiv_cu/gemini-pro", "aiv_cu/gemini-flash"):
        x = cu[(cu.grp == g) & cu.usage_in.notna()]
        n_det = int(sum(isinstance(((e or {}).get("usage_detail") or {}).get("promptTokensDetails"), dict) for e in x.ex))
        n_img = int(sum((((e or {}).get("usage_detail") or {}).get("promptTokensDetails") or {}).get("IMAGE", 0) > 0 for e in x.ex))
        n_tu = int(sum("toolUsePromptTokenCount" in ((e or {}).get("usage_detail") or {}) for e in x.ex))
        sep[g] = {"usage_rows": int(len(x)), "rows_with_promptTokensDetails": n_det, "rows_with_IMAGE_gt0": n_img,
                  "rows_with_toolUsePromptTokenCount_key": n_tu, "sessions": int(x.session_id.nunique())}
    sw = cache["swechat"]
    x = sw[(sw.grp == "swechat/claude_code") & (sw.kind == "result")]
    sep["swechat/claude_code:result.extra.totalTokens(subagent)"] = {
        "result_rows": int(len(x)), "rows_with_totalTokens": int(sum("totalTokens" in (e or {}) for e in x.ex)),
        "rows_with_subagent_usage": int(sum("subagent_usage" in (e or {}) for e in x.ex)),
        "tools": dict(Counter(t for t, e in zip(x.tool_raw, x.ex) if "totalTokens" in (e or {})))}
    for c in ("cc_local", "aiv_cc"):
        x = cache[c][cache[c].kind == "result"]
        sep[f"{c}:result.extra.totalTokens(subagent)"] = {"result_rows": int(len(x)),
                                                           "rows_with_totalTokens": int(sum("totalTokens" in (e or {}) for e in x.ex))}
    p1["separate_tool_result_accounting"] = sep
    # part 2
    for name, corpus, flt, ctx_rule, image_rule, codex, ro, mod in GROUPS:
        d = cache[corpus]
        if flt:
            d = d[d[flt[0]].isin(flt[1])]
        print(f"part2 {name}: {len(d)} rows", flush=True)
        res["part2"][name] = strip_private(analyze_group(name, d, ctx_rule, image_rule, codex, ro, mod))
        if res["part2"][name]["build_counts"].get("usage_rows_without_api_msg_id"):
            off = strip_private(analyze_group(name, d, ctx_rule, image_rule, codex, ro, mod, noid_rule=False))
            m = off.get("non_image_growth", {})
            res["part2"][name]["post_hoc_rule_off"] = {
                "rule": "usage_row_without_api_msg_id", "pairs": off.get("pairs"), "build_counts": off.get("build_counts"),
                "fit_set": off.get("fit_set"), "spearman": (m.get("corr") or {}).get("spearman"),
                "cross_fit_median_abs_resid": ((m.get("cross_fit") or {}).get("resid") or {}).get("median_abs"),
                "typical_ratio": (off.get("typical_result") or {}).get("cross_fit_median_abs_resid_over_median_result_tokens")}
    for g, why in (("swechat/copilot", "usage_out only (outputTokens); no input/context field per call"),
                   ("swechat/cursor", "no usage fields"), ("swechat/simple_text", "no usage fields"), ("whowhen", "no usage fields"),
                   ("aiv_cu/openai-responses", "the OpenAI shapes carry no usage in computer_use_turns"),
                   ("aiv_cu/openai-chat", "the OpenAI shapes carry no usage in computer_use_turns"),
                   ("aiv_cu/compat-chat", "the OpenAI shapes carry no usage in computer_use_turns")):
        c = g.split("/")[0]
        d = cache[c][cache[c].grp == g] if "/" in g else cache[c]
        res["part2_not_feasible"][g] = {"reason": why, "sessions": int(d.session_id.nunique()), "rows": int(len(d)),
                                        "rows_usage_in": int(d.usage_in.notna().sum()), "rows_usage_out": int(d.usage_out.notna().sum())}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
