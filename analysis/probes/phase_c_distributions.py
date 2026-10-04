"""Phase C lens: distributions. Shape of every numeric quantity derivable per event or per session, per corpus.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_distributions
Reads only analysis/cache (Phase B split *_B.parquet, plus swechat_population.parquet, aiv_cu_sessions.parquet and
whowhen_labels.json). Writes analysis/out/phase_c/distributions.json (raw counts and shape statistics only).

What is profiled (families; every one is split by STRATUM, never pooled across strata):
  STRATUM   swechat = content format (claude_code/opencode/codex/gemini/cursor); aiv_cu = loader stratum (provider family);
            whowhen = split (Algorithm-Generated / Hand-Crafted); cc_local, aiv_cc = 'all'.
  E1 latency_ms         call -> first result with the same (session_id, call_id), ts difference. Not for aiv_cu (shared_turn:
                        call and result share one stamp, so the difference is 0 by construction; counted, not profiled) or
                        whowhen (no ts). Also split by tool (top tools with >= MIN_N pairs).
  E2 gap_ms             consecutive timestamped events in seq order within a session. Also split by transition
                        prev_kind>kind (meta events labelled by their extra type). aiv_cu: gap between consecutive TURNS
                        (rows; events of one row share a stamp).
  E3 *_chars            utf8 length of text by kind (result/assistant/user/system), of args (calls), command (shell calls),
                        stderr (where not null). Result text also split by tool.
  E4 usage_*            one row per API response (ir.py USAGE DEDUPE: rows with usage_in not null, dedupe on
                        (session_id, api_msg_id), max usage_out); prompt_total = in + cache_read + cache_create.
  E5 extra.<kind>.<key> every numeric leaf of the extra JSON (nested dicts flattened with '.'), minus EXCLUDED_EXTRA_KEYS
                        (identifiers, clocks, indices). Keys in CATEGORICAL_KEYS get value counts only.
                        Derived: aiv_cu result extra.updated_at - ts (ms); aiv_cu call extra.timing.http_date - ts (ms).
  E6 args.<tool>.<key>  numeric top-level keys of call args JSON. cc_local: only built-in tool names (PUBLIC_TOOLS); other
                        tools' keys are never written (private corpus).
  E7 cmd.*              numbers written inside shell commands: `sleep N` (seconds), `head|tail -n N` / `-N` (lines).
  S  session.*          per session: events, calls, results, assistant/user events, API responses, span_s (last - first ts),
                        distinct tools, tool-mix entropy (bits, sessions with >= 1 call), calls per user event, summed
                        result/assistant/thinking chars, summed usage_out. Population tables: swechat_population length/bytes
                        (all 5,850 sessions), aiv_cu_sessions turn counts and span (all 78k sessions), whowhen mistake_step.

Shape rules are in PREREG (written into the JSON). They were fixed before the first run. Everything computed after looking at
the first run is under the JSON key `posthoc` and listed in POSTHOC with its motivation.
cc_local is private: no text, args, commands, paths, session ids or non-built-in tool names leave this script; only numbers
and harness enum labels (kinds, built-in tool classes, entry types).
"""
import json, math, re, os, sys, time, gc, zlib
from collections import Counter, defaultdict
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.compute as pc

from analysis.lib import stats, ir

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.environ.get("DIST_OUT") or os.path.join(ROOT, "analysis", "out", "phase_c", "distributions.json")  # DIST_OUT: test runs only

CORPORA = ["whowhen", "aiv_cc", "cc_local", "aiv_cu", "swechat"]
PUBLIC_TOOLS = {"shell", "read", "write", "edit", "glob", "grep", "ls", "subagent", "webfetch", "websearch", "todo", "gui"}
EXCLUDED_EXTRA_KEYS = {"family_member", "step", "log_leak_at", "started_at", "completed_at", "compacted_at", "sort_ts"}
CATEGORICAL_KEYS = {"exit_code", "exit", "code", "output_metadata_exit_code", "source.subagent.thread_spawn.depth"}

PREREG = {
    "fixed_before_first_run": True,
    "min_n": 200, "min_sessions": 5,
    "note_min": "a quantity-stratum with fewer than min_n values or min_sessions sessions gets describe() and top exact values only",
    "quantization_step": "ladder [1024,1000,512,500,256,128,100,64,50,32,16,10,8,5,4,2,1,0.5,0.1,0.01,1e-3..1e-9]; step = largest "
                         "ladder value s such that >= 99% of nonzero |v| are integer multiples of s (|v/s - round(v/s)| <= 1e-6 + "
                         "1e-12|v/s|). No ladder value -> step 0 (continuous). Shares for every ladder value >= 1 are reported.",
    "spike_rule": "on the step grid r: value v with v/r >= 10, count c(v) >= 10 and c(v) >= 5 x (count in [v/1.25, v*1.25] excluding v) / "
                  "(grid points in that interval excluding v). Continuous quantities (step 0): any nonzero value repeated >= 10 "
                  "times is reported as continuous_repeat (ratio null). Up to 10 spikes reported, largest count first, with "
                  "n_sessions holding the value, the largest single session's share of c(v), and the top 3 labels (tool / transition).",
    "small_values": "values with v/r < 10 are outside the spike rule; their top 5 exact values and shares are listed.",
    "dequantization": "for mode/tail/quantile statistics positive values on a step grid r > 0 get seeded uniform jitter in [-r/2, r/2) "
                      "(values < r are not jittered). Zeros and negatives are reported as their own masses.",
    "modes": "log10 histogram of positive (jittered) values, 8 bins per decade, edges 10^(k/8); counts smoothed with [1,2,1]/4; "
             "candidate modes = local maxima (>= left, > right) with smoothed height >= max(10, 0.01 n_pos); adjacent candidates "
             "are merged (lower one dropped) while the minimum smoothed height between them is > 0.7 x the lower peak. "
             "n_modes and its distribution over B_SHAPE session-bootstrap resamples (stability = share equal to the point value).",
    "tail": "n_pos >= 500: Hill estimator alpha on the top k = max(20, floor(0.02 n_pos)) positive values; session-bootstrap CI "
            "(B_SHAPE resamples, tail pool = values above the pooled 0.94 quantile; a resample whose pool cannot supply k+1 values is "
            "dropped and counted). p99/p50 with CI from a 64-bins-per-decade histogram bootstrap (CI endpoints at bin resolution, "
            "about +-1.8%). Tail concentration: share of the top-k values coming from the single largest contributing session.",
    "round_numbers": "divisors by unit: ms [10,100,1000,60000]; s [1,10,60]; tokens/chars/count/lines/bytes [10,100,1000] (+1024 for "
                     "bytes). Only values >= 10 d; at least 50 such values; d must be a multiple of the step r with d/r >= 2. "
                     "expected share = r/d (step 0: expected null). Session-clustered CI (lib/stats.cluster_rate; Wilson when every "
                     "session contributes exactly one value). Flag: lower CI >= 2 x expected and >= 10 hits (step 0: lower CI >= 0.01).",
    "rates": "zero and negative shares with session-clustered CI (cluster_rate; Wilson for one value per session).",
    "B_SHAPE": 400,
    "ts_quantization": "per corpus x stratum: share of timestamps whose ms field is 000 (expected 0.001) and whose ms is a multiple of "
                       "10 (expected 0.1); for sources with microseconds, share with us % 1000 == 0. Fractional-digit counts.",
    "score": "sorting aid only (ranking in the notes is judgment informed by it): S = spike + modes + round + tail + quant + neg; "
             "spike = log10(1 + top_spike_share/0.001) if any spike; modes = (n_modes-1) x stability; round = max log10(ratio) over "
             "flagged divisors (step 0 flagged: 2); tail = 1 if Hill CI hi < 1, 0.5 if hi < 2; quant = 1 if step/nominal >= 10, 0.5 "
             "if >= 2 (nominal: ms 1 for ms-stamped sources and 0.001 for us-stamped, s 0.001, tokens/chars/count 1); neg = 1 if "
             "a nonnegative-by-meaning quantity has negative values.",
    "cmd_regex": {"sleep": r"(?<![\w.-])sleep\s+(\d+(?:\.\d+)?)(?![\w.])", "head_tail": r"(?<![\w.-])(?:head|tail)\s+-(?:n\s*)?(\d+)(?![\w.])"},
    "excluded_extra_keys": sorted(EXCLUDED_EXTRA_KEYS), "categorical_keys": sorted(CATEGORICAL_KEYS),
    "public_tools_cc_local": sorted(PUBLIC_TOOLS),
}
POSTHOC = []  # filled below when post-hoc measurements are added (motivation recorded with each)
CHANGES_AFTER_TEST_RUN = [
    {"change": "min_n for session-level quantities (one value per session) lowered from 200 to 100",
     "reason": "test run on whowhen+aiv_cc: aiv_cc has 189 and cc_local 186 Phase B sessions, so every session-level shape "
               "would be suppressed; the change concerns coverage, not any outcome value"},
    {"change": "timestamps converted to microseconds unit-agnostically", "reason": "pandas 3 parses ISO strings to datetime64[us]; "
               "the first test run divided by 1000 twice (aiv_cc call->result median read 0.417 ms instead of 417 ms)"},
]
MIN_N_SESSION = 100

MIN_N, MIN_S, B_SHAPE = PREREG["min_n"], PREREG["min_sessions"], PREREG["B_SHAPE"]
LADDER = [1024, 1000, 512, 500, 256, 128, 100, 64, 50, 32, 16, 10, 8, 5, 4, 2, 1, 0.5, 0.1, 0.01, 1e-3, 1e-4, 1e-5, 1e-6,
          1e-7, 1e-8, 1e-9]
ROUND_DIV = {"ms": [10, 100, 1000, 60000], "s": [1, 10, 60], "tokens": [10, 100, 1000], "chars": [10, 100, 1000],
             "count": [10, 100, 1000], "lines": [10, 100, 1000], "bytes": [10, 100, 1000, 1024]}
RX_SLEEP = re.compile(PREREG["cmd_regex"]["sleep"])
RX_HT = re.compile(PREREG["cmd_regex"]["head_tail"])


# ----------------------------------------------------------------------------------------------------------------- shape
def _r(x, nd=6):
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        if not np.isfinite(x):
            return None
        return float(round(float(x), nd)) if abs(x) < 1e15 else float(x)
    return x


def rate_ci(num_s, den_s):
    """Session-clustered rate; Wilson when every session has exactly one value."""
    num_s = np.asarray(num_s, float)
    den_s = np.asarray(den_s, float)
    if len(den_s) and np.all(den_s == 1):
        k, n = int(num_s.sum()), int(den_s.sum())
        p, lo, hi = stats.wilson(k, n)
        return {"rate": _r(p), "lo": _r(lo), "hi": _r(hi), "num": k, "den": n, "ci": "wilson"}
    r = stats.cluster_rate(num_s, den_s)
    return {"rate": _r(r["rate"]), "lo": _r(r["lo"]), "hi": _r(r["hi"]), "num": int(r["num"]), "den": int(r["den"]),
            "n_sessions": r["n_sessions"], "ci": "cluster"}


def detect_step(v):
    a = np.abs(v[v != 0])
    if len(a) == 0:
        return 0.0, {}
    shares = {}
    step = 0.0
    for s in LADDER:
        q = a / s
        ok = np.abs(q - np.round(q)) <= (1e-6 + 1e-12 * q)
        sh = float(ok.mean())
        if s >= 1:
            shares[str(s)] = _r(sh, 4)
        if step == 0.0 and sh >= 0.99:
            step = float(s)
    return step, shares


def boot_weights(ns, rng, B):
    """B x ns matrix of session multiplicities (float32), generated row by row."""
    W = np.empty((B, ns), dtype=np.float32)
    for b in range(B):
        W[b] = np.bincount(rng.integers(0, ns, size=ns), minlength=ns)
    return W


def hist_by_session(lv, s, ns, lo_k, nb, per_dec):
    """lv = log10 values; returns ns x nb count matrix."""
    k = np.floor(lv * per_dec).astype(np.int64) - lo_k
    k = np.clip(k, 0, nb - 1)
    H = np.zeros((ns, nb), dtype=np.float32)
    np.add.at(H, (s, k), 1)
    return H


def count_modes(counts, n_pos):
    c = np.asarray(counts, float)
    if len(c) == 0:
        return []
    p = np.concatenate([[0], c, [0]])
    sm = (p[:-2] + 2 * p[1:-1] + p[2:]) / 4.0
    thr = max(10.0, 0.01 * n_pos)
    peaks = []
    for i in range(len(sm)):
        left = sm[i - 1] if i > 0 else -1
        right = sm[i + 1] if i + 1 < len(sm) else -1
        if sm[i] >= left and sm[i] > right and sm[i] >= thr:
            peaks.append(i)
    changed = True
    while changed and len(peaks) > 1:
        changed = False
        for j in range(len(peaks) - 1):
            a, b = peaks[j], peaks[j + 1]
            valley = sm[a:b + 1].min()
            low = min(sm[a], sm[b])
            if valley > 0.7 * low:
                peaks.pop(j if sm[a] < sm[b] else j + 1)
                changed = True
                break
    return [(i, float(sm[i])) for i in peaks]


def hill(xs_desc, k):
    """xs_desc sorted descending positive values; Hill alpha on top k."""
    if len(xs_desc) < k + 1:
        return None
    top = np.log(xs_desc[:k])
    return float(1.0 / (top.mean() - math.log(xs_desc[k])))


def profile(v, sess, unit, labels=None, nonneg=True, nominal=None, seed_key="", min_n=None):
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v)
    v = v[m]
    sess = np.asarray(sess)[m]
    lab = None if labels is None else np.asarray(labels, dtype=object)[m]
    n = int(len(v))
    out = {"unit": unit, "n": n}
    if n == 0:
        out["n_sessions"] = 0
        return out
    uniq, s = np.unique(sess, return_inverse=True)
    ns = int(len(uniq))
    out["n_sessions"] = ns
    out["describe"] = {k: _r(x) for k, x in stats.describe(v).items()}
    vc = pd.Series(v).value_counts()
    out["top_exact_values"] = [[_r(float(x)), int(c)] for x, c in vc.head(5).items()]
    out["n_distinct"] = int(len(vc))
    mn = min_n or MIN_N
    if n < mn or ns < MIN_S:
        out["too_small"] = True
        return out
    rng = np.random.default_rng(stats.SEED + zlib.crc32(seed_key.encode("utf-8")) % 100000)
    cnt_s = np.bincount(s, minlength=ns).astype(float)
    out["zero"] = rate_ci(np.bincount(s, weights=(v == 0).astype(float), minlength=ns), cnt_s)
    out["negative"] = rate_ci(np.bincount(s, weights=(v < 0).astype(float), minlength=ns), cnt_s)
    step, shares = detect_step(v)
    out["step"] = step
    out["step_shares"] = shares
    score = {}
    # ---- spikes
    sv = np.sort(v)
    spikes = []
    small = []
    if step > 0:
        for val, c in vc.items():
            if c < 10:
                break
            if val <= 0:
                continue
            if val / step < 10:
                small.append([_r(float(val)), int(c), _r(c / n, 5)])
                continue
            lo, hi = val / 1.25, val * 1.25
            win = int(np.searchsorted(sv, hi, "right") - np.searchsorted(sv, lo, "left")) - int(c)
            gp = int(math.floor(hi / step + 1e-9) - math.ceil(lo / step - 1e-9) + 1) - 1
            lm = win / gp if gp > 0 else 0.0
            if c >= 5 * lm:
                spikes.append({"value": _r(float(val)), "count": int(c), "share": _r(c / n, 5), "local_mean_per_grid": _r(lm, 3),
                               "ratio": _r(c / lm, 2) if lm > 0 else None})
    else:
        for val, c in vc.items():
            if c < 10:
                break
            if val == 0:
                continue
            spikes.append({"value": _r(float(val)), "count": int(c), "share": _r(c / n, 5), "local_mean_per_grid": None,
                           "ratio": None, "continuous_repeat": True})
    spikes.sort(key=lambda d: -d["count"])
    out["n_spikes"] = len(spikes)
    sp_vals = [d["value"] for d in spikes]
    for d in spikes[:10]:
        mk = v == d["value"]
        per = np.bincount(s[mk], minlength=ns)
        d["n_sessions_with_value"] = int((per > 0).sum())
        d["top_session_share"] = _r(per.max() / d["count"], 4)
        if lab is not None:
            d["labels_top3"] = [[str(a), int(b)] for a, b in Counter(lab[mk]).most_common(3)]
    out["spikes"] = spikes[:10]
    out["small_values_top5"] = small[:5]
    if spikes:
        mk = np.isin(v, np.array([d["value"] for d in spikes], dtype=float))
        out["spike_mass"] = rate_ci(np.bincount(s, weights=mk.astype(float), minlength=ns), cnt_s)
        score["spike"] = math.log10(1 + max(d["share"] for d in spikes) / 0.001)
    # ---- positives: jitter, modes, quantiles, tail
    pos = v > 0
    vp = v[pos].copy()
    spp = s[pos]
    n_pos = int(len(vp))
    out["n_pos"] = n_pos
    if step > 0 and n_pos:
        jm = vp >= step
        vp[jm] = vp[jm] + rng.uniform(-step / 2, step / 2, size=int(jm.sum()))
    if n_pos >= mn:
        lv = np.log10(vp)
        per_dec = 8
        lo_k, hi_k = int(math.floor(lv.min() * per_dec)), int(math.floor(lv.max() * per_dec))
        nb = hi_k - lo_k + 1
        H = hist_by_session(lv, spp, ns, lo_k, nb, per_dec)
        tot = H.sum(0)
        modes = count_modes(tot, n_pos)
        out["hist8"] = {"lo_k": lo_k, "per_decade": 8, "counts": [int(x) for x in tot]}
        out["modes"] = [{"center": _r(10 ** ((lo_k + i + 0.5) / 8), 4), "smoothed_height": _r(h, 1)} for i, h in modes]
        out["n_modes"] = len(modes)
        W = boot_weights(ns, rng, B_SHAPE)
        BT = W @ H
        nm = [len(count_modes(BT[b], BT[b].sum())) for b in range(B_SHAPE)]
        out["n_modes_boot"] = {str(k): int(c) for k, c in sorted(Counter(nm).items())}
        stab = sum(1 for x in nm if x == len(modes)) / B_SHAPE
        out["n_modes_stability"] = _r(stab, 4)
        if len(modes) >= 2:
            score["modes"] = (len(modes) - 1) * stab
        # quantiles from 64/decade histogram
        pd64 = 64
        lo64, hi64 = int(math.floor(lv.min() * pd64)), int(math.floor(lv.max() * pd64))
        H64 = hist_by_session(lv, spp, ns, lo64, hi64 - lo64 + 1, pd64)
        BT64 = W @ H64
        del H64

        def qb(bt, q):
            cs = np.cumsum(bt)
            i = int(np.searchsorted(cs, q * cs[-1]))
            return 10 ** ((lo64 + i + 0.5) / pd64)
        p50, p99 = float(np.quantile(vp, 0.5)), float(np.quantile(vp, 0.99))
        ratios = np.array([qb(BT64[b], 0.99) / qb(BT64[b], 0.5) for b in range(B_SHAPE)])
        out["p99_over_p50"] = {"value": _r(p99 / p50, 4), "lo": _r(float(np.quantile(ratios, 0.025)), 4),
                               "hi": _r(float(np.quantile(ratios, 0.975)), 4)}
        del BT64
        if n_pos >= 500:
            order = np.argsort(-vp)
            xs = vp[order]
            ss = spp[order]
            k = max(20, int(0.02 * n_pos))
            a = hill(xs, k)
            topk_sess = np.bincount(ss[:k], minlength=ns)
            pool = int(math.ceil(0.06 * n_pos))
            xs_p, ss_p = xs[:pool], ss[:pool]
            lx = np.log(xs_p)
            npos_s = np.bincount(spp, minlength=ns).astype(np.float32)
            boots, dropped = [], 0
            for b in range(B_SHAPE):
                w = W[b]
                wt = w[ss_p]
                cw = np.cumsum(wt)
                kb = max(20, int(0.02 * float(w @ npos_s)))
                j = int(np.searchsorted(cw, kb))
                if j >= len(cw) or cw[-1] < kb + 1:
                    dropped += 1
                    continue
                prev = cw[j - 1] if j > 0 else 0.0
                sl = float((wt[:j] * lx[:j]).sum() + (kb - prev) * lx[j])
                jx = j if cw[j] >= kb + 1 else j + 1
                if jx >= len(cw):
                    dropped += 1
                    continue
                d = sl / kb - lx[jx]
                if d > 0:
                    boots.append(1.0 / d)
                else:
                    dropped += 1
            out["tail"] = {"k": k, "hill_alpha": _r(a, 4),
                           "lo": _r(float(np.quantile(boots, 0.025)), 4) if boots else None,
                           "hi": _r(float(np.quantile(boots, 0.975)), 4) if boots else None,
                           "boot_dropped": dropped, "topk_top_session_share": _r(topk_sess.max() / k, 4),
                           "topk_n_sessions": int((topk_sess > 0).sum()),
                           "max_over_p99": _r(float(vp.max()) / p99, 4)}
            if boots:
                hi_a = float(np.quantile(boots, 0.975))
                score["tail"] = 1.0 if hi_a < 1 else (0.5 if hi_a < 2 else 0.0)
        del W, BT, H
    # ---- round numbers
    rnd = {}
    for d in ROUND_DIV.get(unit, []):
        if step > 0:
            if d < step or abs(d / step - round(d / step)) > 1e-9 or d / step < 2:
                continue
            exp = step / d
        else:
            exp = None
        mk = v >= 10 * d
        if mk.sum() < 50:
            continue
        q = v[mk] / d
        hit = (np.abs(q - np.round(q)) <= 1e-6 + 1e-12 * q).astype(float)
        num = np.bincount(s[mk], weights=hit, minlength=ns)
        den = np.bincount(s[mk], minlength=ns).astype(float)
        r = rate_ci(num, den)
        r["expected"] = _r(exp, 8) if exp is not None else None
        r["ratio"] = _r(r["rate"] / exp, 3) if exp else None
        if exp is not None:
            r["flag"] = bool(r["lo"] is not None and r["lo"] >= 2 * exp and r["num"] >= 10)
        else:
            r["flag"] = bool(r["lo"] is not None and r["lo"] >= 0.01)
        rnd[str(d)] = r
    if rnd:
        out["round"] = rnd
        fl = [math.log10(max(x["ratio"], 1.0)) if x["ratio"] else 2.0 for x in rnd.values() if x["flag"]]
        if fl:
            score["round"] = max(fl)
    if nominal and step > 0 and step / nominal >= 2:
        score["quant"] = 1.0 if step / nominal >= 10 else 0.5
    if nonneg and out["negative"]["num"] > 0:
        score["neg"] = 1.0
    out["score_parts"] = {k: _r(x, 3) for k, x in score.items()}
    out["score"] = _r(sum(score.values()), 3)
    return out


def categorical(v, sess):
    v = np.asarray(v, dtype=float)
    m = np.isfinite(v)
    vc = Counter(v[m].tolist())
    return {"n": int(m.sum()), "n_sessions": int(len(set(np.asarray(sess)[m]))),
            "value_counts_top10": [[_r(k), int(c)] for k, c in vc.most_common(10)], "n_distinct": len(vc)}


# ----------------------------------------------------------------------------------------------------------------- load
def load(corpus):
    pf = pq.ParquetFile(os.path.join(CACHE, f"{corpus}_B.parquet"))
    cols = ["session_id", "seq", "kind", "ts", "ts_kind", "tool", "tool_raw", "call_id", "usage_in", "usage_out",
            "usage_cache_read", "usage_cache_create", "api_msg_id", "extra", "stratum", "uuid"]
    parts = []
    for rg in range(pf.num_row_groups):
        t = pf.read_row_group(rg, columns=cols + ["text", "args", "stderr", "command"])
        lens = {f"{c}_len": pc.utf8_length(t[c]).to_numpy(zero_copy_only=False) for c in ["text", "args", "stderr", "command"]}
        kind = t["kind"].to_numpy(zero_copy_only=False)
        tool = t["tool"].to_numpy(zero_copy_only=False)
        cmd = t["command"].to_pandas()
        keep_cmd = (kind == "call") & (tool == "shell")
        df = t.select(cols).to_pandas()
        for k, a in lens.items():
            df[k] = pd.to_numeric(pd.Series(a), errors="coerce").astype(float).values
        df["command"] = cmd.where(keep_cmd, None).values
        parts.append(df)
        del t
        gc.collect()
    df = pd.concat(parts, ignore_index=True)
    del parts
    for c in df.columns:
        if c.endswith("_len") or c in ("seq",) or c.startswith("usage_"):
            continue
        if not (df[c].dtype == object):
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    for c in ["usage_in", "usage_out", "usage_cache_read", "usage_cache_create"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["seq"] = df["seq"].astype(np.int64)
    df = df.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    dt = pd.to_datetime(df["ts"], utc=True, format="ISO8601", errors="coerce")
    ok = dt.notna()
    us = np.full(len(df), np.iinfo(np.int64).min, dtype=np.int64)
    us[ok.values] = ((dt[ok] - EPOCH) // pd.Timedelta(microseconds=1)).astype(np.int64).values  # unit-agnostic (pandas 3: us)
    df["ts_us"] = us
    df["ts_ok"] = ok.values
    df["frac_digits"] = [ir.frac_digits(x) if isinstance(x, str) else -1 for x in df["ts"].values]
    df.drop(columns=["ts"], inplace=True)
    if corpus == "swechat":
        pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
        df = df.merge(pop, on="session_id", how="left")
        df["strat"] = df["format"].fillna("unknown")
        df.drop(columns=["format"], inplace=True)
    elif corpus in ("aiv_cu", "whowhen"):
        df["strat"] = df["stratum"]
    else:
        df["strat"] = "all"
    if corpus == "cc_local":
        df["tool"] = df["tool"].where(df["tool"].isna() | df["tool"].isin(PUBLIC_TOOLS), "other")
        df["tool_raw"] = None
    return df


EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def to_us(t):
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return int((t - EPOCH) // pd.Timedelta(microseconds=1))


def meta_label(e):
    if not isinstance(e, str):
        return "meta"
    try:
        d = json.loads(e)
    except Exception:
        return "meta"
    for k in ("type", "entry_type", "part_type"):
        if isinstance(d.get(k), str):
            if k == "entry_type" and isinstance(d.get("subtype"), str):
                return f"{d[k]}/{d['subtype']}"
            return d[k]
    return "meta"


def flat_num(d, pre=""):
    for k, v in d.items():
        p = pre + k
        if isinstance(v, dict):
            yield from flat_num(v, p + ".")
        elif isinstance(v, bool) or v is None:
            continue
        elif isinstance(v, (int, float)):
            yield p, float(v)


# ----------------------------------------------------------------------------------------------------------------- quantities
class Collector:
    def __init__(self):
        self.res = {}
        self.cat = {}

    def add(self, corpus, strat, name, v, sess, unit, labels=None, nonneg=True, nominal=None):
        key = f"{corpus}|{strat}|{name}"
        t0 = time.time()
        mn = MIN_N_SESSION if name.startswith("session.") else None
        self.res[key] = profile(v, sess, unit, labels, nonneg, nominal, key, min_n=mn)
        self.res[key]["family"] = name.split("[")[0].split(".")[0]
        dt = time.time() - t0
        if dt > 5:
            print(f"   slow profile {key}: {dt:.1f}s n={self.res[key]['n']}", flush=True)

    def add_cat(self, corpus, strat, name, v, sess):
        self.cat[f"{corpus}|{strat}|{name}"] = categorical(v, sess)


def nominal_ms(df):
    """1 ms for ms-stamped sources, 0.001 ms when the stamps carry microseconds."""
    fd = df.loc[df.ts_ok, "frac_digits"]
    return 0.001 if len(fd) and (fd >= 4).mean() > 0.5 else 1.0


def run_corpus(corpus, C, extra_out):
    t0 = time.time()
    df = load(corpus)
    print(f"[{corpus}] loaded {len(df)} rows in {time.time() - t0:.1f}s", flush=True)
    info = {"rows": int(len(df)), "sessions": int(df.session_id.nunique()),
            "sessions_by_stratum": {str(k): int(v) for k, v in df.groupby("strat").session_id.nunique().items()}}
    for strat, g in df.groupby("strat", sort=True):
        g = g.reset_index(drop=True)
        sid = g["session_id"].values
        nom_ms = nominal_ms(g)
        si = {"rows": int(len(g)), "sessions": int(g.session_id.nunique()), "nominal_ms": nom_ms}
        # ---- ts quantization
        tsg = g[g.ts_ok]
        if len(tsg):
            us = tsg.ts_us.values
            ms_field = (us // 1000) % 1000
            per_s = tsg.session_id.values
            u, sc = np.unique(per_s, return_inverse=True)
            den = np.bincount(sc).astype(float)
            si["ts_quant"] = {
                "n": int(len(tsg)), "frac_digits": {str(k): int(v) for k, v in Counter(tsg.frac_digits.tolist()).items()},
                "ms_eq_000": rate_ci(np.bincount(sc, weights=(ms_field == 0).astype(float)), den),
                "ms_mult_10": rate_ci(np.bincount(sc, weights=(ms_field % 10 == 0).astype(float)), den),
                "us_mult_1000": rate_ci(np.bincount(sc, weights=((us % 1000) == 0).astype(float)), den),
            }
        ts_kinds = Counter(g.ts_kind.tolist())
        si["ts_kind"] = {str(k): int(v) for k, v in ts_kinds.items()}
        # ---- E1 latency
        calls = g[(g.kind == "call") & g.call_id.notna()][["session_id", "call_id", "seq", "ts_us", "ts_ok", "tool"]]
        res = g[(g.kind == "result") & g.call_id.notna()][["session_id", "call_id", "seq", "ts_us", "ts_ok"]]
        res1 = res.sort_values("seq").drop_duplicates(["session_id", "call_id"], keep="first")
        pr = calls.merge(res1, on=["session_id", "call_id"], suffixes=("_c", "_r"))
        si["call_result_pairs"] = int(len(pr))
        pr = pr[pr.ts_ok_c & pr.ts_ok_r]
        si["call_result_pairs_timestamped"] = int(len(pr))
        if corpus == "aiv_cu":
            lat0 = (pr.ts_us_r - pr.ts_us_c).values
            si["shared_turn_latency"] = {"n": int(len(lat0)), "eq_0": int((lat0 == 0).sum())}
        elif len(pr):
            lat = (pr.ts_us_r - pr.ts_us_c).values / 1000.0
            tl = pr.tool.fillna("none").values
            C.add(corpus, strat, "latency_ms", lat, pr.session_id.values, "ms", labels=tl, nominal=nom_ms)
            for tool, c in Counter(tl).most_common(10):
                if c >= MIN_N:
                    mk = tl == tool
                    C.add(corpus, strat, f"latency_ms[{tool}]", lat[mk], pr.session_id.values[mk], "ms", nominal=nom_ms)
            # result order inversions vs seq: result seq before call seq
            si["result_seq_before_call"] = int((pr.seq_r < pr.seq_c).sum())
        # ---- E2 gaps
        if corpus == "aiv_cu":
            tg = g[g.ts_ok].drop_duplicates(["session_id", "uuid"], keep="first")
            dd = np.diff(tg.ts_us.values)
            same = tg.session_id.values[1:] == tg.session_id.values[:-1]
            gap = dd[same] / 1000.0
            gs = tg.session_id.values[1:][same]
            C.add(corpus, strat, "turn_gap_ms", gap, gs, "ms", nominal=nom_ms)
        else:
            tg = g[g.ts_ok]
            if len(tg) > 1:
                labs = np.where(tg.kind.values == "meta", [f"meta:{meta_label(e)}" for e in tg.extra.values], tg.kind.values)
                dd = np.diff(tg.ts_us.values)
                same = tg.session_id.values[1:] == tg.session_id.values[:-1]
                gap = dd[same] / 1000.0
                gs = tg.session_id.values[1:][same]
                trans = np.array([f"{a}>{b}" for a, b in zip(labs[:-1], labs[1:])], dtype=object)[same]
                C.add(corpus, strat, "gap_ms", gap, gs, "ms", labels=trans, nominal=nom_ms)
                for tr, c in Counter(trans.tolist()).most_common(10):
                    if c >= 1000:
                        mk = trans == tr
                        C.add(corpus, strat, f"gap_ms[{tr}]", gap[mk], gs[mk], "ms", nominal=nom_ms)
        # ---- E3 lengths
        for kind in ["result", "assistant", "user", "system"]:
            mk = (g.kind == kind).values & ~np.isnan(g.text_len.values)
            if mk.sum():
                lab = g.tool.fillna("none").values[mk] if kind == "result" else None
                C.add(corpus, strat, f"{kind}_text_chars", g.text_len.values[mk], sid[mk], "chars", labels=lab)
        mk = (g.kind == "result").values & ~np.isnan(g.text_len.values)
        tl = g.tool.fillna("none").values
        for tool, c in Counter(tl[mk].tolist()).most_common(8):
            if c >= MIN_N:
                m2 = mk & (tl == tool)
                C.add(corpus, strat, f"result_text_chars[{tool}]", g.text_len.values[m2], sid[m2], "chars")
        mk = (g.kind == "call").values & ~np.isnan(g.args_len.values)
        if mk.sum():
            C.add(corpus, strat, "args_chars", g.args_len.values[mk], sid[mk], "chars", labels=tl[mk])
        mk = ~np.isnan(g.command_len.values) & (g.kind == "call").values & (tl == "shell")
        if mk.sum():
            C.add(corpus, strat, "command_chars", g.command_len.values[mk], sid[mk], "chars")
        mk = ~np.isnan(g.stderr_len.values)
        if mk.sum():
            C.add(corpus, strat, "stderr_chars", g.stderr_len.values[mk], sid[mk], "chars", labels=g.kind.values[mk])
        # ---- E4 usage
        u = g[g.usage_in.notna()].copy()
        if len(u):
            u["api_key"] = u.api_msg_id.where(u.api_msg_id.notna(), "row:" + u.seq.astype(str))
            agg = u.groupby(["session_id", "api_key"], sort=False).agg(
                usage_in=("usage_in", "first"), usage_out=("usage_out", "max"), usage_cache_read=("usage_cache_read", "first"),
                usage_cache_create=("usage_cache_create", "first"), n_rows=("seq", "size")).reset_index()
            si["api_responses"] = int(len(agg))
            si["api_rows_per_response"] = {str(k): int(v) for k, v in Counter(agg.n_rows.clip(upper=10).tolist()).items()}
            for c in ["usage_in", "usage_out", "usage_cache_read", "usage_cache_create"]:
                vals = pd.to_numeric(agg[c], errors="coerce").astype(float).values
                if np.isfinite(vals).sum():
                    C.add(corpus, strat, c, vals, agg.session_id.values, "tokens")
            tot = (pd.to_numeric(agg.usage_in, errors="coerce").astype(float) + pd.to_numeric(agg.usage_cache_read, errors="coerce").astype(float)
                   + pd.to_numeric(agg.usage_cache_create, errors="coerce").astype(float)).values
            if np.isfinite(tot).sum():
                C.add(corpus, strat, "usage_prompt_total", tot, agg.session_id.values, "tokens")
        # ---- E5 extra numeric
        buckets = defaultdict(lambda: ([], [], []))
        upd, httpd = ([], []), ([], [])
        for kind, e, s_, tool, tsu, tok in zip(g.kind.values, g.extra.values, sid, tl, g.ts_us.values, g.ts_ok.values):
            if not isinstance(e, str) or len(e) < 3:
                continue
            try:
                d = json.loads(e)
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            lab = f"meta:{meta_label(e)}" if kind == "meta" else tool
            for p, x in flat_num(d):
                if p in EXCLUDED_EXTRA_KEYS:
                    continue
                if corpus == "aiv_cu" and p.startswith("action."):
                    continue
                b = buckets[(kind, p)]
                b[0].append(x)
                b[1].append(s_)
                b[2].append(lab)
            if corpus == "aiv_cu" and tok:
                if kind == "result" and isinstance(d.get("updated_at"), str):
                    t2 = pd.Timestamp(ir.iso(d["updated_at"]))
                    upd[0].append((to_us(t2) - tsu) / 1000.0)
                    upd[1].append(s_)
                tm = d.get("timing")
                if kind in ("call", "assistant") and isinstance(tm, dict) and isinstance(tm.get("http_date"), str):
                    t2 = pd.Timestamp(tm["http_date"])
                    if t2.tzinfo is None:
                        t2 = t2.tz_localize("UTC")
                    httpd[0].append((to_us(t2) - tsu) / 1000.0)
                    httpd[1].append(s_)
        for (kind, p), (vals, ss, labs) in sorted(buckets.items()):
            name = f"extra.{kind}.{p}"
            if p.split(".")[-1] in CATEGORICAL_KEYS or p in CATEGORICAL_KEYS:
                C.add_cat(corpus, strat, name, vals, ss)
                continue
            low = p.lower()
            if any(t in low for t in ("tokens", "token_count", "tokencount", "usage_in", "usage_out", "usage_cache", "pre_tokens",
                                      "pretokens", "posttokens", "droppedtokens", "thinking_tokens", "totaltokens", "context_window")):
                unit = "tokens"
            elif "chars" in low:
                unit = "chars"
            elif low.endswith("seconds") or low.endswith("duration_s") or low == "seconds":
                unit = "s"
            elif low.endswith("ms") or low.endswith("_ms") or "durationms" in low:
                unit = "ms"
            elif "bytes" in low or "outputsize" in low:
                unit = "bytes"
            elif "cost" in low or "usd" in low:
                unit = "usd"
            elif "lines" in low:
                unit = "lines"
            else:
                unit = "count"
            C.add(corpus, strat, name, vals, ss, unit, labels=labs, nominal=(nom_ms if unit == "ms" else (0.001 if unit == "s" else 1)))
        if upd[0]:
            C.add(corpus, strat, "derived.result.updated_at_minus_ts_ms", upd[0], upd[1], "ms", nonneg=False, nominal=nom_ms)
        if httpd[0]:
            C.add(corpus, strat, "derived.call.http_date_minus_ts_ms", httpd[0], httpd[1], "ms", nonneg=False, nominal=nom_ms)
        # ---- E6 args numeric: run_args() (separate pass over the args column)
        cm = (g.kind == "call").values
        # ---- E7 commands
        cmds = g.command.values[cm & (tl == "shell")]
        css = sid[cm & (tl == "shell")]
        sl, sls, ht, hts = [], [], [], []
        n_cmd = 0
        for c, s_ in zip(cmds, css):
            if not isinstance(c, str):
                continue
            n_cmd += 1
            for x in RX_SLEEP.findall(c):
                sl.append(float(x))
                sls.append(s_)
            for x in RX_HT.findall(c):
                ht.append(float(x))
                hts.append(s_)
        si["shell_commands"] = n_cmd
        if sl:
            C.add(corpus, strat, "cmd.sleep_s", sl, sls, "s", nominal=1)
        if ht:
            C.add(corpus, strat, "cmd.head_tail_n", ht, hts, "lines")
        # ---- S session level
        sess = g.groupby("session_id", sort=False)
        S = pd.DataFrame({
            "n_events": sess.size(),
            "n_calls": sess.kind.apply(lambda k: int((k == "call").sum())),
            "n_results": sess.kind.apply(lambda k: int((k == "result").sum())),
            "n_assistant": sess.kind.apply(lambda k: int((k == "assistant").sum())),
            "n_user": sess.kind.apply(lambda k: int((k == "user").sum())),
        })
        tsg = g[g.ts_ok].groupby("session_id").ts_us.agg(["min", "max"])
        S["span_s"] = ((tsg["max"] - tsg["min"]) / 1e6).reindex(S.index)
        cg = g[g.kind == "call"].assign(t=lambda x: x.tool.fillna("none")).groupby(["session_id", "t"]).size()
        ent, ndt = {}, {}
        for k_, cnt in cg.groupby(level=0):
            p_ = cnt.values.astype(float) / cnt.values.sum()
            ent[k_] = float(-(p_ * np.log2(p_)).sum()) + 0.0
            ndt[k_] = int(len(cnt))
        S["tool_entropy_bits"] = pd.Series(ent).reindex(S.index)
        S["n_distinct_tools"] = pd.Series(ndt).reindex(S.index)
        S["calls_per_user_event"] = S.n_calls / S.n_user.clip(lower=1)
        S["result_chars_total"] = g[g.kind == "result"].groupby("session_id").text_len.sum().reindex(S.index)
        S["assistant_chars_total"] = g[g.kind == "assistant"].groupby("session_id").text_len.sum().reindex(S.index)
        if "api_responses" in si:
            S["n_api_responses"] = agg.groupby("session_id").size().reindex(S.index)
            S["usage_out_total"] = agg.groupby("session_id").usage_out.sum().astype(float).reindex(S.index)
        for c in S.columns:
            unit = "s" if c == "span_s" else ("chars" if "chars" in c else ("tokens" if "usage" in c else "count"))
            vals = S[c].astype(float).values
            if c == "tool_entropy_bits" or c == "calls_per_user_event":
                unit = "ratio"
            C.add(corpus, strat, f"session.{c}", vals, S.index.values, unit, nominal=(0.001 if unit == "s" else 1))
        extra_out.setdefault("strata", {}).setdefault(corpus, {})[strat] = si
        print(f"[{corpus}|{strat}] done {time.time() - t0:.1f}s, profiles so far {len(C.res)}", flush=True)
    extra_out.setdefault("corpus_info", {})[corpus] = info
    del df
    gc.collect()


def run_args(corpus, C):
    """E6: numeric top-level keys of call args (separate pass so the big args column is read once, calls only)."""
    pf = pq.ParquetFile(os.path.join(CACHE, f"{corpus}_B.parquet"))
    strat_map = None
    if corpus == "swechat":
        pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
        strat_map = dict(zip(pop.session_id, pop.format))
    ab = defaultdict(lambda: ([], []))
    for rg in range(pf.num_row_groups):
        t = pf.read_row_group(rg, columns=["session_id", "kind", "tool", "args", "stratum"])
        t = t.filter(pc.equal(t["kind"], "call"))
        for s_, tool, a, st in zip(t["session_id"].to_pylist(), t["tool"].to_pylist(), t["args"].to_pylist(), t["stratum"].to_pylist()):
            if corpus == "cc_local" and tool not in PUBLIC_TOOLS:
                continue
            if not a:
                continue
            try:
                d = json.loads(a)
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            strat = strat_map.get(s_, "unknown") if strat_map else (st if corpus in ("aiv_cu", "whowhen") else "all")
            for k, x in d.items():
                if isinstance(x, bool) or not isinstance(x, (int, float)):
                    continue
                b = ab[(strat, tool, k)]
                b[0].append(float(x))
                b[1].append(s_)
        del t
    for (strat, tool, k), (vals, ss) in sorted(ab.items()):
        if len(vals) < 50:
            continue
        low = k.lower()
        unit = ("ms" if ("timeout" in low or low.endswith("_ms") or low.endswith("ms")) else
                "s" if low in ("seconds", "duration", "time") else
                "lines" if low in ("limit", "offset", "head_limit", "-a", "-b", "-c", "context", "start_line", "end_line", "head") else
                "tokens" if "tokens" in low else "count")
        if corpus == "aiv_cu" and tool == "pause":
            unit = "s"
        C.add(corpus, strat, f"args.{tool}.{k}", vals, ss, unit, nominal=1)


def run_population(C, extra_out):
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"))
    for fmt, g in pop.groupby("format"):
        C.add("swechat_population", fmt, "session.length", g.length.values.astype(float), g.session_id.values, "count")
        C.add("swechat_population", fmt, "session.bytes", g.bytes.values.astype(float), g.session_id.values, "bytes")
    s = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"),
                        columns=["session_id", "n_turns", "n_bash_turns", "n_gui_turns", "n_talk_only_turns", "n_synthetic_turns",
                                 "first_created_at", "last_created_at", "stratum"])
    f = pd.to_datetime(s.first_created_at.map(ir.iso), utc=True, format="ISO8601", errors="coerce")
    l = pd.to_datetime(s.last_created_at.map(ir.iso), utc=True, format="ISO8601", errors="coerce")
    s["span_s"] = (l - f).dt.total_seconds()
    for st, g in s.groupby("stratum"):
        for c in ["n_turns", "n_bash_turns", "n_gui_turns", "n_talk_only_turns", "n_synthetic_turns", "span_s"]:
            C.add("aiv_cu_population", st, f"session.{c}", g[c].values.astype(float), g.session_id.values,
                  "s" if c == "span_s" else "count", nominal=(0.001 if c == "span_s" else 1))
    extra_out["population_tables"] = {"swechat_population_sessions": int(len(pop)), "aiv_cu_sessions": int(len(s)),
                                      "aiv_cu_sessions_by_stratum": {str(k): int(v) for k, v in s.stratum.value_counts().items()}}
    lab = json.load(open(os.path.join(CACHE, "whowhen_labels.json"), encoding="utf-8"))
    ww = pd.read_parquet(os.path.join(CACHE, "whowhen_B.parquet"), columns=["session_id", "stratum", "extra"])
    nsteps = {}
    for sid_, e in zip(ww.session_id, ww.extra):
        try:
            st = json.loads(e).get("step")
        except Exception:
            st = None
        if isinstance(st, int):
            nsteps[sid_] = max(nsteps.get(sid_, -1), st)
    rows = []
    for sid_, d in lab.items():
        if sid_ in nsteps and isinstance(d.get("mistake_step"), int):
            rows.append((sid_, d["split"], d["mistake_step"], d["mistake_step"] / (nsteps[sid_] + 1)))
    r = pd.DataFrame(rows, columns=["session_id", "split", "mstep", "mrel"])
    for sp, g in r.groupby("split"):
        C.add("whowhen", sp, "session.mistake_step", g.mstep.values.astype(float), g.session_id.values, "count")
        C.add("whowhen", sp, "session.mistake_step_rel", g.mrel.values.astype(float), g.session_id.values, "ratio")


# ----------------------------------------------------------------------------------------------------------------- post hoc
POSTHOC.extend([
    {"key": "ph1_caps", "motivation": "first run: result_text_chars tails end at hard maxima (cc_local shell max 30000; opencode shell "
     "p99 51541 vs max 51551; swechat CC shell spikes at 10039/10040 chars, all starting 'Exit code')"},
    {"key": "ph2_edit_5s_plateau", "motivation": "first run: swechat CC latency_ms[edit] second mode at ~4870 ms with exact-value spikes "
     "5014-5021 ms, and gap call>meta:hook_progress spikes at 5015-5023 ms. Bands [0,1000),[1000,4900),[4900,5200),[5200,inf) ms "
     "chosen after seeing the spikes"},
    {"key": "ph3_updated_at", "motivation": "first run: aiv_cu derived updated_at - created_at has p50 0.002 ms but max up to 1.29e7 ms"},
    {"key": "ph4_turn_cap", "motivation": "first run: aiv_cu_population session.n_turns spike at exactly 41 in 9 of 10 strata"},
    {"key": "ph5_reasoning_lattice", "motivation": "first run: swechat codex reasoning_output_tokens spikes at 516 and 1034; neighbouring "
     "values inspected, lattice 516 + 518k found by eye before this block was written"},
    {"key": "ph6_timeout_hits", "motivation": "first run: shell latency tails (Hill alpha ~1) and timeout args are round; checks how much "
     "of the tail sits at the requested timeout"},
    {"key": "ph7_interrupt_markers_as_user", "motivation": "first run: swechat CC user_text_chars spikes at 29 and 42 chars; inspection "
     "showed the harness strings '[Request interrupted by user]' and '[Request interrupted by user for tool use]'"},
    {"key": "ph8_gemini_image_tokens", "motivation": "first run: aiv_cu Gemini promptTokensDetails.IMAGE has 99% of mass in spikes at "
     "258/516/1032/1064/2128/... tokens"},
    {"key": "ph9_codex_yield", "motivation": "first run: swechat codex latency spikes at 1158-1161 ms and 5002-5003 ms; args.yield_time_ms "
     "is 1000 in 89% of calls"},
])
PUBLIC_CAP_TOOLS = ["shell", "read", "grep", "glob", "edit", "write", "webfetch", "subagent"]
INTERRUPT_TEXTS = ("[Request interrupted by user]", "[Request interrupted by user for tool use]")


def pa_array(x):
    import pyarrow as pa
    return pa.array(x)


def _ts_us(series):
    dt = pd.to_datetime(series, utc=True, format="ISO8601", errors="coerce")
    out = np.full(len(series), np.nan)
    ok = dt.notna().values
    out[ok] = ((dt[ok] - EPOCH) // pd.Timedelta(microseconds=1)).astype(np.int64).values
    return out


def _read(corpus, cols, filt=None):
    pf = pq.ParquetFile(os.path.join(CACHE, f"{corpus}_B.parquet"))
    parts = []
    for rg in range(pf.num_row_groups):
        t = pf.read_row_group(rg, columns=cols)
        if filt is not None:
            t = t.filter(filt(t))
        df = t.to_pandas()
        for c in df.columns:
            if df[c].dtype != object and not pd.api.types.is_numeric_dtype(df[c]):
                df[c] = df[c].astype(object).where(df[c].notna(), None)
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def _fmt_map():
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
    return dict(zip(pop.session_id, pop.format))


def _rate_by_session(flag, sess):
    flag = np.asarray(flag, float)
    u, sc = np.unique(np.asarray(sess), return_inverse=True)
    return rate_ci(np.bincount(sc, weights=flag), np.bincount(sc).astype(float))


def _num_arg(a, key):
    try:
        v = json.loads(a).get(key) if isinstance(a, str) else None
    except Exception:
        v = None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else np.nan


def ph_caps_and_markers(fmt):
    ph1, ph7 = {}, {}
    for corpus in ["swechat", "cc_local", "aiv_cc", "aiv_cu"]:
        pf = pq.ParquetFile(os.path.join(CACHE, f"{corpus}_B.parquet"))
        rows = []
        for rg in range(pf.num_row_groups):
            t = pf.read_row_group(rg, columns=["session_id", "kind", "tool", "text", "stratum"])
            t = t.filter(pc.is_in(t["kind"], pa_array(["result", "user"])))
            ln = pc.utf8_length(t["text"]).to_numpy(zero_copy_only=False)
            txt = t["text"].to_pylist()
            ec = [isinstance(x, str) and x.startswith("Exit code") for x in txt]
            intr = [isinstance(x, str) and x in INTERRUPT_TEXTS for x in txt]
            rows.append(pd.DataFrame({"session_id": t["session_id"].to_pylist(), "kind": t["kind"].to_pylist(),
                                      "tool": t["tool"].to_pylist(), "len": pd.to_numeric(pd.Series(ln), errors="coerce").values,
                                      "exit_code_prefix": ec, "interrupt": intr, "stratum": t["stratum"].to_pylist()}))
            del t, txt
        df = pd.concat(rows, ignore_index=True)
        if corpus == "swechat":
            df["strat"] = df.session_id.map(fmt).fillna("unknown")
        elif corpus == "aiv_cu":
            df["strat"] = df.stratum
        else:
            df["strat"] = "all"
        if corpus == "cc_local":
            df["tool"] = df.tool.where(df.tool.isna() | df.tool.isin(PUBLIC_TOOLS), "other")
        for strat, g in df.groupby("strat"):
            r = g[(g.kind == "result") & g.len.notna()]
            for tool in PUBLIC_CAP_TOOLS:
                q = r[r.tool == tool]
                if len(q) < MIN_N:
                    continue
                for part, qq in (("all", q), ("exit_code_prefix", q[q.exit_code_prefix]), ("no_exit_code_prefix", q[~q.exit_code_prefix])):
                    if len(qq) < 20 or (part != "all" and tool != "shell"):
                        continue
                    mx = float(qq.len.max())
                    near = qq[qq.len >= 0.99 * mx]
                    vc = near.len.value_counts().head(5)
                    ph1[f"{corpus}|{strat}|{tool}|{part}"] = {
                        "n": int(len(qq)), "n_sessions": int(qq.session_id.nunique()), "max": mx,
                        "n_at_max": int((qq.len == mx).sum()), "n_ge_0.99max": int(len(near)),
                        "sessions_ge_0.99max": int(near.session_id.nunique()),
                        "top_values_ge_0.99max": [[float(a), int(b)] for a, b in vc.items()],
                        "p99": float(np.quantile(qq.len, 0.99))}
            if corpus in ("swechat", "cc_local") and strat in ("claude_code", "all"):
                u = g[g.kind == "user"]
                ph7[f"{corpus}|{strat}"] = {"user_events": int(len(u)), "interrupt_marker_events": int(u.interrupt.sum()),
                                            "sessions_with_marker": int(u[u.interrupt].session_id.nunique()),
                                            "share": _rate_by_session(u.interrupt.values, u.session_id.values)}
        del df
        gc.collect()
    return ph1, ph7


def ph_latency_attribution(fmt):
    ph2, ph6 = {}, {}
    for corpus in ["swechat", "cc_local"]:
        t = _read(corpus, ["session_id", "seq", "kind", "tool", "call_id", "parent_call_id", "extra", "ts", "args"],
                  filt=lambda t: pc.is_in(t["kind"], pa_array(["call", "result", "meta"])))
        if corpus == "swechat":
            t = t[t.session_id.map(fmt) == "claude_code"]
        t["ts_us"] = _ts_us(t.ts)
        calls = t[t.kind == "call"][["session_id", "call_id", "tool", "ts_us", "args"]]
        res = t[t.kind == "result"].sort_values("seq").drop_duplicates(["session_id", "call_id"])[["session_id", "call_id", "ts_us"]]
        pr = calls.merge(res, on=["session_id", "call_id"], suffixes=("_c", "_r"))
        pr = pr[np.isfinite(pr.ts_us_c.astype(float)) & np.isfinite(pr.ts_us_r.astype(float))]
        pr["lat"] = (pr.ts_us_r - pr.ts_us_c) / 1000.0
        if corpus == "swechat":
            hk = t[(t.kind == "meta") & t.extra.fillna("").str.contains('"hook_progress"', regex=False)].copy()
            hk["ev"] = [json.loads(e).get("hookEvent") for e in hk.extra]
            hk = hk[["session_id", "parent_call_id", "ev", "ts_us"]].rename(columns={"parent_call_id": "call_id", "ts_us": "ts_h"})
            for tool in ["edit", "write", "read", "shell"]:
                p = pr[pr.tool == tool]
                for lo, hi in [(0, 1000), (1000, 4900), (4900, 5200), (5200, float("inf"))]:
                    q = p[(p.lat >= lo) & (p.lat < hi)]
                    j = q.merge(hk, on=["session_id", "call_id"], how="left")
                    post, pre = j[j.ev == "PostToolUse"], j[j.ev == "PreToolUse"]
                    ph2[f"{tool}|{lo}-{hi}"] = {
                        "n": int(len(q)), "n_sessions": int(q.session_id.nunique()),
                        "calls_with_PostToolUse_progress": int(post.drop_duplicates(["session_id", "call_id"]).shape[0]),
                        "calls_with_PreToolUse_progress": int(pre.drop_duplicates(["session_id", "call_id"]).shape[0]),
                        "median_ms_call_to_PostToolUse": _r(float(((post.ts_h - post.ts_us_c) / 1000).median())) if len(post) else None,
                        "median_ms_PostToolUse_minus_result_ts": _r(float(((post.ts_h - post.ts_us_r) / 1000).median())) if len(post) else None}
            ed = pr[pr.tool == "edit"]
            ph2["edit_share_in_4900_5200"] = _rate_by_session(((ed.lat >= 4900) & (ed.lat < 5200)).values, ed.session_id.values)
            wr = pr[pr.tool == "write"]
            ph2["write_share_in_4900_5200"] = _rate_by_session(((wr.lat >= 4900) & (wr.lat < 5200)).values, wr.session_id.values)
            rd = pr[pr.tool == "read"]
            ph2["read_share_in_4900_5200"] = _rate_by_session(((rd.lat >= 4900) & (rd.lat < 5200)).values, rd.session_id.values)
        sh = pr[pr.tool == "shell"].copy()
        sh["timeout"] = [_num_arg(a, "timeout") for a in sh.args.values]
        w, wo = sh[sh.timeout.notna()], sh[sh.timeout.isna()]
        key = f"{corpus}|{'claude_code' if corpus == 'swechat' else 'all'}"
        d = {"shell_pairs": int(len(sh)), "with_timeout_arg": int(len(w)), "without_timeout_arg": int(len(wo)),
             "timeout_arg_gt_600000": int((w.timeout > 600000).sum()), "latency_gt_600000": int((sh.lat > 600000).sum())}
        if len(w):
            d["with_timeout_latency_ge_timeout"] = _rate_by_session((w.lat >= w.timeout).values, w.session_id.values)
            d["with_timeout_latency_in_timeout_to_plus_5s"] = _rate_by_session(((w.lat >= w.timeout) & (w.lat < w.timeout + 5000)).values, w.session_id.values)
        if len(wo):
            d["without_timeout_latency_ge_120000"] = _rate_by_session((wo.lat >= 120000).values, wo.session_id.values)
            d["without_timeout_latency_in_120000_to_125000"] = _rate_by_session(((wo.lat >= 120000) & (wo.lat < 125000)).values, wo.session_id.values)
        if len(sh):
            p99 = float(np.quantile(sh.lat, 0.99))
            top = sh[sh.lat >= p99]
            hit = ((top.timeout.notna() & (top.lat >= top.timeout) & (top.lat < top.timeout + 5000)) |
                   (top.timeout.isna() & (top.lat >= 120000) & (top.lat < 125000)))
            d["top1pct_latency_at_timeout"] = {"p99_ms": p99, "n": int(len(top)), "at_timeout": int(hit.sum())}
        ph6[key] = d
        del t
        gc.collect()
    return ph2, ph6


def ph_aiv_cu():
    t = _read("aiv_cu", ["session_id", "kind", "extra", "ts", "stratum"], filt=lambda t: pc.is_in(t["kind"], pa_array(["result", "call"])))
    t["ts_us"] = _ts_us(t.ts)
    ph3, ph8 = {}, {}
    rr = t[t.kind == "result"]
    off, red, ovr = [], [], []
    for e, tsu in zip(rr.extra.values, rr.ts_us.values):
        d = json.loads(e) if isinstance(e, str) else {}
        u = d.get("updated_at")
        off.append((to_us(pd.Timestamp(ir.iso(u))) - tsu) / 1000.0 if isinstance(u, str) and np.isfinite(tsu) else np.nan)
        red.append(bool(d.get("screenshot_is_redacted")))
        ovr.append(bool(d.get("has_redaction_been_overruled")))
    rr = rr.assign(off=off, red=red, ovr=ovr)
    for st, g in list(rr.groupby("stratum")) + [("ALL", rr)]:
        g = g[g.off.notna()]
        big = g[g.off > 1000]
        ph3[st] = {"n": int(len(g)), "n_sessions": int(g.session_id.nunique()), "le_0.01ms": int((g.off <= 0.01).sum()),
                   "gt_1ms": int((g.off > 1).sum()), "gt_1s": int(len(big)), "gt_1s_sessions": int(big.session_id.nunique()),
                   "negative": int((g.off < 0).sum()), "gt_1s_share": _rate_by_session((g.off > 1000).values, g.session_id.values),
                   "redacted_among_gt_1s": int(big.red.sum()), "redacted_among_all": int(g.red.sum()),
                   "overruled_among_gt_1s": int(big.ovr.sum()), "overruled_among_all": int(g.ovr.sum())}
    cl = t[(t.kind == "call") & t.stratum.isin(["gemini-pro", "gemini-flash"])]
    for st, g in cl.groupby("stratum"):
        for field in ["promptTokensDetails", "cacheTokensDetails"]:
            vals, ss = [], []
            for e, s_ in zip(g.extra.values, g.session_id.values):
                d = json.loads(e) if isinstance(e, str) else {}
                v = ((d.get("usage_detail") or {}).get(field) or {}).get("IMAGE")
                if isinstance(v, (int, float)) and v > 0:
                    vals.append(float(v))
                    ss.append(s_)
            vals = np.array(vals)
            if len(vals) == 0:
                continue
            ph8[f"{st}|{field}.IMAGE"] = {
                "n": int(len(vals)), "n_sessions": int(len(set(ss))),
                "div_258": _rate_by_session(vals % 258 == 0, ss), "div_1064": _rate_by_session(vals % 1064 == 0, ss),
                "div_258_or_1064": _rate_by_session((vals % 258 == 0) | (vals % 1064 == 0), ss),
                "div_2": _rate_by_session(vals % 2 == 0, ss)}
    del t, rr
    gc.collect()
    return ph3, ph8


def ph_turn_cap():
    s = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"), columns=["session_id", "n_turns", "n_synthetic_turns", "stratum"])
    ph4 = {}
    for st, g in list(s.groupby("stratum")) + [("ALL", s)]:
        n = len(g)
        k41 = int((g.n_turns == 41).sum())
        p, lo, hi = stats.wilson(k41, n)
        g41 = g[g.n_turns == 41]
        ph4[st] = {"sessions": int(n), "n_turns_eq_41": k41, "rate": _r(p), "lo": _r(lo), "hi": _r(hi),
                   "n_turns_40": int((g.n_turns == 40).sum()), "n_turns_42": int((g.n_turns == 42).sum()),
                   "n_turns_gt_41": int((g.n_turns > 41).sum()),
                   "eq41_synthetic_turns": {str(k): int(v) for k, v in g41.n_synthetic_turns.value_counts().items()},
                   "model_turns_eq_40": int(((g.n_turns - g.n_synthetic_turns) == 40).sum())}
    return ph4


def ph_codex(fmt):
    t = _read("swechat", ["session_id", "seq", "kind", "extra", "usage_in", "model", "tool", "tool_raw", "call_id", "args", "ts"])
    t = t[t.session_id.map(fmt) == "codex"]
    tc = t[(t.kind == "meta") & t.usage_in.notna()].copy()
    tc["r"] = [json.loads(e).get("reasoning_output_tokens") for e in tc.extra]
    vc = tc.r.value_counts()
    lat = {}
    for k in range(0, 8):
        c = 516 + 518 * k
        lat[str(c)] = {"count": int(vc.get(c, 0)), "neighbour_counts_pm4": [int(vc.get(c + d, 0)) for d in (-4, -3, -2, -1, 1, 2, 3, 4)],
                       "sessions": int(tc[tc.r == c].session_id.nunique())}
    on = tc.r.isin([516 + 518 * k for k in range(0, 20)])
    ph5 = {"token_count_rows": int(len(tc)), "rows_with_reasoning_gt0": int((tc.r > 0).sum()), "lattice_516_plus_518k": lat,
           "on_lattice_by_model": {str(k): int(v) for k, v in tc[on].model.value_counts().items()},
           "rows_by_model": {str(k): int(v) for k, v in tc.model.value_counts().items()},
           "on_lattice_share": _rate_by_session(on.values, tc.session_id.values)}
    t["ts_us"] = _ts_us(t.ts)
    calls = t[(t.kind == "call") & (t.tool_raw == "exec_command")][["session_id", "call_id", "ts_us", "args"]]
    res = t[t.kind == "result"].sort_values("seq").drop_duplicates(["session_id", "call_id"])[["session_id", "call_id", "ts_us"]]
    pr = calls.merge(res, on=["session_id", "call_id"], suffixes=("_c", "_r"))
    pr["lat"] = (pr.ts_us_r - pr.ts_us_c) / 1000.0
    pr["y"] = [_num_arg(a, "yield_time_ms") for a in pr.args.values]
    ph9 = {"exec_command_pairs": int(len(pr)), "with_yield": int(pr.y.notna().sum())}
    for y in [1000.0, 5000.0, 10000.0, 30000.0]:
        q = pr[pr.y == y]
        if len(q) == 0:
            continue
        d = (q.lat - y).values
        ph9[str(int(y))] = {"n": int(len(q)), "n_sessions": int(q.session_id.nunique()),
                            "latency_in_y_to_y_plus_300ms": _rate_by_session(((d >= 0) & (d < 300)), q.session_id.values),
                            "latency_lt_y": int((d < 0).sum()), "median_latency_minus_y_ms": _r(float(np.median(d))),
                            "p10_latency_minus_y_ms": _r(float(np.quantile(d, 0.1))), "p90_latency_minus_y_ms": _r(float(np.quantile(d, 0.9)))}
    del t
    gc.collect()
    return ph5, ph9



POSTHOC.append({"key": "summary", "motivation": "tallies of the PREREG flags over all profiles, added after the first run; the "
                "'featureless' tally (exactly 1 mode, no spike, no round-number flag, no negative value) and the thinking/reasoning "
                "subset are definitions chosen after the first run, to count nulls"})
POSTHOC.append({"key": "ph10_template_attribution", "motivation": "first run: many length spikes; this block records which harness "
                "template or enum label produces each length spike cited in the notes (cc_local: enum labels only, no text)"})
PH10_TARGETS = [
    ("swechat", "claude_code", "user", None, [29, 42]), ("swechat", "claude_code", "system", None, [245, 134]),
    ("swechat", "claude_code", "result", None, [31, 160, 16, 22, 14, 10039, 10040]),
    ("swechat", "opencode", "user", None, [4657]), ("swechat", "opencode", "result", None, [14, 791]),
    ("swechat", "gemini", "result", None, [751, 747]),
    ("aiv_cc", "all", "result", None, [7, 3764, 3679]), ("aiv_cc", "all", "stderr", None, [93]),
    ("aiv_cu", None, "result", None, [38, 22, 23, 9]),
    ("whowhen", "Hand-Crafted", "assistant", None, [22]), ("whowhen", "Algorithm-Generated", "system", None, [258]),
    ("cc_local", "all", "system", None, [86, 49]), ("cc_local", "all", "user", None, [2074]), ("cc_local", "all", "result", None, [131, 39, 9839]),
]


def ph_templates(fmt):
    out = {}
    cache = {}
    for corpus, strat, kind, _, lens in PH10_TARGETS:
        if corpus not in cache:
            cols = ["session_id", "kind", "tool", "text", "stderr", "extra", "stratum"]
            df = _read(corpus, cols)
            df["strat"] = (df.session_id.map(fmt).fillna("unknown") if corpus == "swechat" else
                           (df.stratum if corpus in ("aiv_cu", "whowhen") else "all"))
            if corpus == "cc_local":
                df["tool"] = df.tool.where(df.tool.isna() | df.tool.isin(PUBLIC_TOOLS), "other")
            cache = {corpus: df}
        df = cache[corpus]
        g = df if strat is None else df[df.strat == strat]
        col = "stderr" if kind == "stderr" else "text"
        g = g[g.kind == "result"] if kind == "stderr" else g[g.kind == kind]
        L = g[col].str.len()
        for n in lens:
            h = g[L == n]
            rec = {"n": int(len(h)), "n_sessions": int(h.session_id.nunique()),
                   "tools_top3": [[str(a), int(b)] for a, b in Counter(h.tool.fillna("none")).most_common(3)]}
            lab = Counter()
            for e in h.extra.values:
                try:
                    d = json.loads(e) if isinstance(e, str) else {}
                except Exception:
                    d = {}
                lab[(d.get("entry_type"), d.get("attachment_type"))] += 1
            rec["entry_attachment_type_top3"] = [[str(a), int(b)] for a, b in lab.most_common(3)]
            if corpus != "cc_local":
                pref = Counter(re.sub(r"(/Users/|/home/)[^/\s]+", r"\g<1><user>", x[:40]) for x in h[col].values if isinstance(x, str))
                rec["prefix40_top3"] = [[a, int(b)] for a, b in pref.most_common(3)]
            if corpus == "aiv_cu":
                rec["by_stratum"] = {str(a): int(b) for a, b in Counter(h.strat).most_common(10)}
            out[f"{corpus}|{strat or 'ALL'}|{kind}|{n}"] = rec
    return out


def run_posthoc():
    fmt = _fmt_map()
    PH = {}
    PH["ph1_caps"], PH["ph7_interrupt_markers_as_user"] = ph_caps_and_markers(fmt)
    print("[posthoc] caps done", flush=True)
    PH["ph2_edit_5s_plateau"], PH["ph6_timeout_hits"] = ph_latency_attribution(fmt)
    print("[posthoc] latency attribution done", flush=True)
    PH["ph3_updated_at"], PH["ph8_gemini_image_tokens"] = ph_aiv_cu()
    PH["ph4_turn_cap"] = ph_turn_cap()
    PH["ph5_reasoning_lattice"], PH["ph9_codex_yield"] = ph_codex(fmt)
    PH["ph10_template_attribution"] = ph_templates(fmt)
    print("[posthoc] done", flush=True)
    return PH


def main():
    t0 = time.time()
    C = Collector()
    extra_out = {}
    only = sys.argv[1:] or CORPORA
    for corpus in only:
        if corpus in CORPORA:
            run_corpus(corpus, C, extra_out)
            run_args(corpus, C)
            print(f"[{corpus}] args done, profiles {len(C.res)}", flush=True)
    if not sys.argv[1:] or "population" in sys.argv[1:]:
        run_population(C, extra_out)
    posthoc = run_posthoc() if (not sys.argv[1:] or "posthoc" in sys.argv[1:]) else {}
    # summary counts over profiles (raw counts of the flags defined in PREREG)
    full = {k: p for k, p in C.res.items() if p.get("n") and not p.get("too_small") and "step" in p}

    def _flags(p):
        rf = any(v["flag"] for v in p.get("round", {}).values())
        hi = (p.get("tail") or {}).get("hi")
        return {"spike": p.get("n_spikes", 0) > 0, "round": rf, "neg": p["negative"]["num"] > 0,
                "multimodal": (p.get("n_modes") or 0) >= 2, "hill_hi_lt1": hi is not None and hi < 1,
                "hill_hi_lt2": hi is not None and hi < 2, "tail_measured": hi is not None,
                "featureless": p.get("n_modes") == 1 and p.get("n_spikes", 0) == 0 and not rf and p["negative"]["num"] == 0}
    fl = {k: _flags(p) for k, p in full.items()}
    summary = {"profiles_total": len(C.res), "too_small": sum(1 for p in C.res.values() if p.get("too_small")),
               "empty": sum(1 for p in C.res.values() if not p.get("n")), "profiled": len(full),
               "n_modes_distribution": {str(k): v for k, v in sorted(Counter(str(p.get("n_modes")) for p in full.values()).items())},
               **{f"with_{f}": sum(1 for x in fl.values() if x[f]) for f in ["spike", "round", "neg", "multimodal", "hill_hi_lt1",
                                                                              "hill_hi_lt2", "tail_measured", "featureless"]},
               "featureless_by_family": dict(Counter(full[k]["family"] for k, x in fl.items() if x["featureless"]).most_common()),
               "profiled_by_family": dict(Counter(p["family"] for p in full.values()).most_common())}
    tr = {k: x for k, x in fl.items() if ("thinking" in k or "reasoning_chars" in k or "thoughtsTokenCount" in k) and not k.split("|")[2].startswith("gap_ms")}
    summary["thinking_reasoning"] = {"profiled": len(tr), "with_spike": sum(1 for x in tr.values() if x["spike"]),
                                     "multimodal": sum(1 for x in tr.values() if x["multimodal"]),
                                     "featureless": sum(1 for x in tr.values() if x["featureless"])}
    ranking = sorted(((v.get("score") or 0, k) for k, v in C.res.items() if v.get("score")), reverse=True)
    out = {
        "lens": "distributions", "split": "B", "prereg": PREREG, "changes_after_test_run": CHANGES_AFTER_TEST_RUN,
        "min_n_session": MIN_N_SESSION, "posthoc_rules": POSTHOC,
        "n_profiles": len(C.res), "n_categorical": len(C.cat),
        **extra_out,
        "ranking_by_prereg_score": [{"key": k, "score": s, "parts": C.res[k].get("score_parts"), "n": C.res[k]["n"],
                                     "n_sessions": C.res[k]["n_sessions"]} for s, k in ranking[:80]],
        "summary": summary,
        "posthoc": posthoc,
        "profiles": C.res, "categorical": C.cat,
        "wall_seconds": round(time.time() - t0, 1),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, default=lambda o: _r(float(o)) if isinstance(o, (np.floating, np.integer)) else str(o))
    print(f"wrote {OUT} profiles={len(C.res)} wall={time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
