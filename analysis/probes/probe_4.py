"""Phase B Probe 4: entropy / incidental detail (prereg.json probe4).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.probe_4

Question (prereg): is hex (and are numbers / timestamps) typed by the model distinguishable from machine-produced values
in honest logs? If yes, a model-written fake tool result would carry that signature.

What this script does, in order:
  0. Refuses to run unless sha256(prereg_common.py) == prereg.json provenance.spec_module_sha256 (and the same for
     prereg_calibration.py, whose digit_test_ci is the pre-registered CI implementation reused here).
  1. Implementation check on split A: re-runs this script's extraction on the A caches and compares ONLY the token /
     value COUNTS that prereg_calibration.json already holds (no digit test, no round share of any model-typed class is
     computed on A). This shows the extraction below is the one the thresholds were calibrated with.
  2. Split B (analysis/cache/<corpus>_B.parquet): per unit
       - census: share of results (and calls, assistant events) carrying >= 1 valid hex token, large integer, embedded
         timestamp, UUID; per tool_key too;
       - hex classes M_git, M_all, T_copy, T_orig, A_copy, A_orig, U, S (prereg probe4.hex.classes) with the digit test
         (chi2, df 15, w_adj, session-bootstrap CI) where the class has >= N_min symbols; below N_min raw counts only;
       - large-integer classes with round-number shares (last 0 / 00 / 000 / 0-or-5) vs uniform and vs M_all;
       - timestamp classes (iso, epoch_s, epoch_ms) with their uniform expectations (no verdict);
       - EXPLORATORY, NOT PRE-REGISTERED (no verdict): durations with an all-zero fraction ("2.0s"), ls-style mtimes at
         minute :00, "N bytes" counts ending 00 - requested by the Phase B task, labelled as such;
       - redaction handling: tokens inside REDACTED runs dropped and counted (pre-mask), and the pre-registered
         redaction-sensitivity rerun on events with no 'REDACTED' at all.
  3. Pooled cells swechat/* and public/* (pre-registered; label 'pooled'; never replace a unit verdict).
  4. Verdicts computed mechanically from prereg.json probe4.verdict, each stored with its deciding numbers.

Outputs (raw numbers only; interpretation is in analysis/notes/probe_4.md):
  analysis/out/probe_4.json            (path named by the Phase B task)
  analysis/out/phase_b/probe_4.json    (identical copy at the path in prereg.json data_rules.output_contract)
cc_local is private: only aggregates are written for it (no tokens, values, text, paths; tool names via private_key).
"""
import gc
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.probes import prereg_common as pc

ROOT = pc.ROOT
PREREG = ROOT / "analysis" / "prereg.json"
OUT = ROOT / "analysis" / "out" / "probe_4.json"
OUT_PB = ROOT / "analysis" / "out" / "phase_b" / "probe_4.json"
CALIB_JSON = ROOT / "analysis" / "out" / "phase_a" / "prereg_calibration.json"

COLS = ["session_id", "seq", "kind", "tool", "tool_raw", "call_id", "args", "command", "text", "stderr"]
KINDS = ["user", "system", "assistant", "call", "result"]  # meta rows are never model-visible text
HEX_CLASSES = ("M_git", "M_all", "T_copy", "T_orig", "A_copy", "A_orig", "U", "S")
VAL_CLASSES = ("M_all", "T_copy", "T_orig", "A_copy", "A_orig")
VARIANTS = ("main", "noredact", "noredact_strict")
# main            : every event (tokens inside REDACTED runs already dropped by pc.hex_tokens)
# noredact        : prereg redaction_sensitivity - only tokens from events whose text has no 'REDACTED' at all;
#                   sourcing (copy/orig) still uses every earlier event of the session (the record as it is)
# noredact_strict : as noredact, and events containing 'REDACTED' are also removed from the sourcing antecedents
TS_KINDS = ("iso", "epoch_s", "epoch_ms")

# ---- EXPLORATORY patterns: NOT in the pre-registration; written here before any B number was computed; no verdict.
RX_X = {
    "duration_frac": re.compile(r"(?<![\w.])(\d+)\.(\d+)\s?(?:ms|s|sec|secs|seconds)\b"),
    "ls_mtime_hhmm": re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+(\d{2}):(\d{2})(?![:\d])"),
    "byte_count": re.compile(r"(?<![\w.,])([1-9]\d{2,})\s?bytes?\b"),
}
X_EXPECT = {"duration_frac": "share whose fractional digits are all 0; uniform expectation = mean over values of 10^-d",
            "ls_mtime_hhmm": "share with minute == 00; uniform expectation 1/60",
            "byte_count": "share with last two digits 00 (uniform 0.01) and last digit 0 (uniform 0.1)"}

PUBLIC_EXAMPLE_LENGTHS = (7, 8)  # descriptive examples only for public units and only short (git-hash-like) tokens


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ============================================================================================ prereg gate + thresholds
def load_prereg():
    pr = json.load(open(PREREG, encoding="utf-8"))
    want = pr["provenance"]["spec_module_sha256"]
    got = sha256(ROOT / "analysis" / "probes" / "prereg_common.py")
    if want != got:
        print(f"PREREG SHA MISMATCH: prereg_common.py {got} != prereg.json {want}. Stopping.", file=sys.stderr)
        sys.exit(2)
    want_c = pr["provenance"]["calibration_script_sha256"]
    got_c = sha256(ROOT / "analysis" / "probes" / "prereg_calibration.py")
    if want_c != got_c:
        print(f"CALIBRATION SHA MISMATCH: {got_c} != {want_c}. Stopping.", file=sys.stderr)
        sys.exit(2)
    assert pr["global"]["bootstrap"]["seed"] == stats.SEED and pr["global"]["bootstrap"]["n_boot"] == stats.N_BOOT
    v = pr["probe4"]["verdict"]
    hex_rule = v["hex (primary)"]
    rn_rule = v["round_numbers (secondary)"]
    th = {
        "N_min": int(pr["resolved"]["probe4"]["N_min"]["value"]),
        "instrument_ceiling": float(re.search(r"CI hi <= ([0-9.]+)", pr["probe4"]["hex"]["instrument_check"]).group(1)),
        "alive_w": float(re.search(r"T_orig w_adj point >= ([0-9.]+)", hex_rule).group(1)),
        "round_margin": float(re.search(r"CI hi \+ ([0-9.]+)", rn_rule).group(1)),
        "round_min_values": int(re.search(r">= (\d+) distinct values", rn_rule).group(1)),
        "round_min_sessions": int(re.search(r"from >= (\d+) sessions", rn_rule).group(1)),
        "rate_den_min": int(pr["global"]["min_n"]["rate_reportable"]["den_min"]),
        "rate_sessions_min": int(pr["global"]["min_n"]["rate_reportable"]["sessions_min"]),
        "expected_uniform_last_digits": pr["probe4"]["numbers"]["expected_uniform_last_digits"],
        "small_n_sessions": 30,
        "source": {
            "N_min": "prereg.json resolved.probe4.N_min.value",
            "instrument_ceiling": "prereg.json probe4.hex.instrument_check ('CI hi <= x')",
            "alive_w": "prereg.json probe4.verdict['hex (primary)'] ('T_orig w_adj point >= x')",
            "round_margin / round_min_values / round_min_sessions": "prereg.json probe4.verdict['round_numbers (secondary)']",
            "rate_den_min / rate_sessions_min": "prereg.json global.min_n.rate_reportable",
            "small_n_sessions": "prereg.json global.min_n.small_n_label ('< 30 B sessions')",
        },
    }
    assert th["N_min"] == pc.n_min_power(), "N_min in prereg.json differs from the power calculation"
    prov = {"prereg_json_sha256": sha256(PREREG), "spec_module_sha256": got, "spec_module_sha256_expected": want,
            "spec_sha_ok": want == got, "calibration_script_sha256": got_c, "calibration_sha_ok": want_c == got_c,
            "prereg_commit": "3df8d28"}
    return pr, th, prov


# digit_test_ci is the pre-registered CI implementation (it produced resolved.probe4.control_A); reused unchanged.
from analysis.probes.prereg_calibration import digit_test_ci  # noqa: E402


# ============================================================================================ extraction
class Acc:
    """Per-unit accumulator. Token / value dicts map value -> (session_id, seq, tool_key) of the first occurrence in
    (session_id, seq) order (prereg dedupe rule)."""

    def __init__(self, unit, private):
        self.unit = unit
        self.private = private
        self.hex = {v: {c: {} for c in HEX_CLASSES} for v in VARIANTS}
        self.ints = {v: {c: {} for c in VAL_CLASSES} for v in VARIANTS}
        self.ts = {k: {c: {} for c in VAL_CLASSES} for k in TS_KINDS}
        self.x = {k: {c: {} for c in VAL_CLASSES} for k in RX_X}
        self.cnt = Counter()
        self.occ = {"T_orig": Counter(), "A_orig": Counter()}  # occurrence counts (public descriptive examples)
        # POST-HOC DESCRIPTIVE (added after the first full run, which produced the verdicts; feeds no verdict):
        # where model-originated large integers come from (JSON-number args vs digits inside arg strings)
        self.int_origin = {"T_copy": {}, "T_orig": {}}
        self.occ_int = {"T_orig": Counter(), "A_orig": Counter()}
        # census: per session counters
        self.cen_res = defaultdict(Counter)          # sid -> Counter
        self.cen_res_tool = defaultdict(lambda: defaultdict(Counter))  # tool -> sid -> Counter
        self.cen_call = defaultdict(Counter)
        self.cen_call_tool = defaultdict(lambda: defaultdict(Counter))
        self.cen_asst = defaultdict(Counter)
        self.hex_per_result = []                     # number of valid hex tokens per result (all results)
        self.int_per_result = []
        self.sessions = set()
        self.git_calls = 0

    def tk(self, tool, tool_raw):
        k = pc.tool_key(self.unit, tool, tool_raw)
        return pc.private_key(k) if self.private else k


def _s(x):
    return x if isinstance(x, str) else None


def extract(unit, u, private, counts_only=False):
    """Walks one unit's events in (session_id, seq) order. Mirrors prereg_calibration.probe4_unit for the hex and
    large-int classes; adds census, timestamps, exploratory patterns and the redaction variants."""
    acc = Acc(unit, private)
    u = u.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    sids = u.session_id.to_numpy()
    seqs = u.seq.to_numpy()
    kinds = u.kind.astype(object).tolist()
    tools = u.tool.astype(object).tolist()
    traws = u.tool_raw.astype(object).tolist()
    cids = u.call_id.astype(object).tolist()
    argsl = u.args.astype(object).tolist()
    cmds = u.command.astype(object).tolist()
    texts = u.text.astype(object).tolist()
    errs = u.stderr.astype(object).tolist()
    n = len(u)
    # ---- git calls (calibration rule: shell-family tool_key whose command matches git_cmd)
    git_calls = set()
    for i in range(n):
        if kinds[i] != "call":
            continue
        k = pc.tool_key(unit, _s(tools[i]), _s(traws[i]))
        if not (k == "shell" or k in pc.CODEX_SHELL_RAW or k.endswith("__bash")):
            continue
        a = argsl[i]
        try:
            obj = json.loads(a) if isinstance(a, str) else None
        except ValueError:
            obj = None
        sh = pc.shell_command(unit, k, obj, _s(cmds[i]))
        if sh and pc._C["git_cmd"].search(sh):
            git_calls.add((sids[i], str(cids[i])))
    acc.git_calls = len(git_calls)
    if n == 0:
        return acc
    starts = np.flatnonzero(np.r_[True, sids[1:] != sids[:-1]])
    ends = np.r_[starts[1:], n]
    rx_iso, rx_es, rx_ems = pc._C["iso_ts"], pc._C["epoch_s"], pc._C["epoch_ms"]

    def put(d, val, key):
        if val not in d:
            d[val] = key

    for s0, e0 in zip(starts, ends):
        sid = sids[s0]
        acc.sessions.add(sid)
        # antecedent sets: full record / record without REDACTED events
        anc = {"all": set(), "clean": set()}
        anc_pref = {"all": set(), "clean": set()}
        anc_int = {"all": set(), "clean": set()}
        anc_ts = {"all": set(), "clean": set()}
        anc_x = {"all": {k: set() for k in RX_X}, "clean": {k: set() for k in RX_X}}
        for i in range(s0, e0):
            kind = kinds[i]
            seq = int(seqs[i])
            if kind in ("result", "user", "system"):
                txt = _s(texts[i])
                pieces = [txt] + ([_s(errs[i])] if kind == "result" else [])
                pieces = [p for p in pieces if p]
                red = any("REDACTED" in p for p in pieces)
                if red:
                    acc.cnt[f"events_with_REDACTED/{kind}"] += 1
                tool = acc.tk(_s(tools[i]), _s(traws[i])) if kind == "result" else None
                cls = "M_all" if kind == "result" else ("U" if kind == "user" else "S")
                n_hex = n_int = n_ts = n_uuid = 0
                for t in pieces:
                    toks, nu, nd = pc.hex_tokens(t)
                    acc.cnt["uuid_masked"] += nu
                    acc.cnt["hex_dropped_redaction"] += nd
                    acc.cnt[f"hex_dropped_redaction/{kind}"] += nd
                    n_hex += len(toks)
                    n_uuid += nu
                    for tok in toks:
                        key = (sid, seq, tool)
                        put(acc.hex["main"][cls], tok, key)
                        if not red:
                            put(acc.hex["noredact"][cls], tok, key)
                            put(acc.hex["noredact_strict"][cls], tok, key)
                        for scope in (("all", "clean") if not red else ("all",)):
                            anc[scope].add(tok)
                            for L in (7, 8, 32, 40):
                                if len(tok) > L:
                                    anc_pref[scope].add(tok[:L])
                    li = pc.large_ints(t)
                    n_int += len(li)
                    for scope in (("all", "clean") if not red else ("all",)):
                        anc_int[scope].update(li)
                    if counts_only:
                        if kind == "result":
                            for v in li:
                                put(acc.ints["main"]["M_all"], v, (sid, seq, tool))
                        continue
                    tsv = [("iso", m.group(0)) for m in rx_iso.finditer(t)] + \
                          [("epoch_s", m.group(0)) for m in rx_es.finditer(t)] + \
                          [("epoch_ms", m.group(0)) for m in rx_ems.finditer(t)]
                    n_ts += len(tsv)
                    xv = [(k, m.group(0)) for k, rx in RX_X.items() for m in rx.finditer(t)]
                    for scope in (("all", "clean") if not red else ("all",)):
                        anc_ts[scope].update(v for _, v in tsv)
                        for k, v in xv:
                            anc_x[scope][k].add(v)
                    if kind == "result":
                        key = (sid, seq, tool)
                        for v in li:
                            put(acc.ints["main"]["M_all"], v, key)
                            if not red:
                                put(acc.ints["noredact"]["M_all"], v, key)
                                put(acc.ints["noredact_strict"]["M_all"], v, key)
                        for k, v in tsv:
                            put(acc.ts[k]["M_all"], v, key)
                        for k, v in xv:
                            put(acc.x[k]["M_all"], v, key)
                if kind == "result" and txt and (sid, str(cids[i])) in git_calls:
                    for tok in pc.git_hashes(txt):
                        key = (sid, seq, tool)
                        put(acc.hex["main"]["M_git"], tok, key)
                        if not red:
                            put(acc.hex["noredact"]["M_git"], tok, key)
                            put(acc.hex["noredact_strict"]["M_git"], tok, key)
                if kind == "result" and not counts_only:
                    c = acc.cen_res[sid]
                    ct = acc.cen_res_tool[tool][sid]
                    flags = {"n": 1, "hex": int(n_hex > 0), "large_int": int(n_int > 0), "timestamp": int(n_ts > 0),
                             "uuid": int(n_uuid > 0), "any_hex_int_ts": int(n_hex + n_int + n_ts > 0),
                             "redacted": int(red)}
                    c.update(flags)
                    ct.update(flags)
                    acc.hex_per_result.append(n_hex)
                    acc.int_per_result.append(n_int)
            elif kind == "call":
                a = argsl[i]
                strs, nums = pc.args_strings(a)
                red = isinstance(a, str) and "REDACTED" in a
                if red:
                    acc.cnt["events_with_REDACTED/call"] += 1
                tool = acc.tk(_s(tools[i]), _s(traws[i]))
                key = (sid, seq, tool)
                f = Counter()
                for t in strs:
                    toks, nu, nd = pc.hex_tokens(t)
                    acc.cnt["uuid_masked"] += nu
                    acc.cnt["hex_dropped_redaction"] += nd
                    acc.cnt["hex_dropped_redaction/call"] += nd
                    for tok in toks:
                        f["hex"] += 1
                        c_all = "T_copy" if (tok in anc["all"] or tok in anc_pref["all"]) else "T_orig"
                        put(acc.hex["main"][c_all], tok, key)
                        if c_all == "T_orig":
                            f["hex_T_orig"] += 1
                            acc.occ["T_orig"][tok] += 1
                        if not red:
                            put(acc.hex["noredact"][c_all], tok, key)
                            c_cl = "T_copy" if (tok in anc["clean"] or tok in anc_pref["clean"]) else "T_orig"
                            put(acc.hex["noredact_strict"][c_cl], tok, key)
                    for v in pc.large_ints(t):
                        f["large_int"] += 1
                        c_all = "T_copy" if v in anc_int["all"] else "T_orig"
                        put(acc.ints["main"][c_all], v, key)
                        acc.int_origin[c_all].setdefault(v, "args_string")
                        if c_all == "T_orig":
                            acc.occ_int["T_orig"][v] += 1
                        if not red:
                            put(acc.ints["noredact"][c_all], v, key)
                            put(acc.ints["noredact_strict"]["T_copy" if v in anc_int["clean"] else "T_orig"], v, key)
                    if counts_only:
                        continue
                    for k, rx in (("iso", rx_iso), ("epoch_s", rx_es), ("epoch_ms", rx_ems)):
                        for m in rx.finditer(t):
                            f["timestamp"] += 1
                            v = m.group(0)
                            put(acc.ts[k]["T_copy" if v in anc_ts["all"] else "T_orig"], v, key)
                    for k, rx in RX_X.items():
                        for m in rx.finditer(t):
                            v = m.group(0)
                            put(acc.x[k]["T_copy" if v in anc_x["all"][k] else "T_orig"], v, key)
                for v0 in nums:
                    # JSON numbers: SPEC numbers.classes 'JSON numbers included as their decimal string'; large_int is
                    # applied through pc.large_ints, which also applies the SPEC epoch exclusion.
                    li = pc.large_ints(v0)
                    if pc._C["large_int"].fullmatch(v0) and not li:
                        acc.cnt["json_number_epoch_excluded"] += 1
                    for v in li:
                        f["large_int"] += 1
                        c_all = "T_copy" if v in anc_int["all"] else "T_orig"
                        put(acc.ints["main"][c_all], v, key)
                        acc.int_origin[c_all].setdefault(v, "json_number")
                        if c_all == "T_orig":
                            acc.occ_int["T_orig"][v] += 1
                        if not red:
                            put(acc.ints["noredact"][c_all], v, key)
                            put(acc.ints["noredact_strict"]["T_copy" if v in anc_int["clean"] else "T_orig"], v, key)
                    if counts_only:
                        continue
                    for k, rx in (("epoch_s", rx_es), ("epoch_ms", rx_ems)):
                        if rx.fullmatch(v0):
                            f["timestamp"] += 1
                            put(acc.ts[k]["T_copy" if v0 in anc_ts["all"] else "T_orig"], v0, key)
                if not counts_only:
                    flags = {"n": 1, "hex": int(f["hex"] > 0), "hex_T_orig": int(f["hex_T_orig"] > 0),
                             "large_int": int(f["large_int"] > 0), "timestamp": int(f["timestamp"] > 0)}
                    acc.cen_call[sid].update(flags)
                    acc.cen_call_tool[tool][sid].update(flags)
            elif kind == "assistant":
                txt = _s(texts[i])
                if not txt:
                    continue
                red = "REDACTED" in txt
                if red:
                    acc.cnt["events_with_REDACTED/assistant"] += 1
                key = (sid, seq, None)
                toks, nu, nd = pc.hex_tokens(txt)
                acc.cnt["hex_dropped_redaction"] += nd
                acc.cnt["hex_dropped_redaction/assistant"] += nd
                f = Counter()
                for tok in toks:
                    f["hex"] += 1
                    c_all = "A_copy" if (tok in anc["all"] or tok in anc_pref["all"]) else "A_orig"
                    put(acc.hex["main"][c_all], tok, key)
                    if c_all == "A_orig":
                        f["hex_A_orig"] += 1
                        acc.occ["A_orig"][tok] += 1
                    if not red:
                        put(acc.hex["noredact"][c_all], tok, key)
                        c_cl = "A_copy" if (tok in anc["clean"] or tok in anc_pref["clean"]) else "A_orig"
                        put(acc.hex["noredact_strict"][c_cl], tok, key)
                for v in pc.large_ints(txt):
                    f["large_int"] += 1
                    c_all = "A_copy" if v in anc_int["all"] else "A_orig"
                    put(acc.ints["main"][c_all], v, key)
                    if c_all == "A_orig":
                        acc.occ_int["A_orig"][v] += 1
                    if not red:
                        put(acc.ints["noredact"][c_all], v, key)
                        put(acc.ints["noredact_strict"]["A_copy" if v in anc_int["clean"] else "A_orig"], v, key)
                if counts_only:
                    continue
                for k, rx in (("iso", rx_iso), ("epoch_s", rx_es), ("epoch_ms", rx_ems)):
                    for m in rx.finditer(txt):
                        f["timestamp"] += 1
                        v = m.group(0)
                        put(acc.ts[k]["A_copy" if v in anc_ts["all"] else "A_orig"], v, key)
                for k, rx in RX_X.items():
                    for m in rx.finditer(txt):
                        v = m.group(0)
                        put(acc.x[k]["A_copy" if v in anc_x["all"][k] else "A_orig"], v, key)
                acc.cen_asst[sid].update({"n": 1, "hex": int(f["hex"] > 0), "hex_A_orig": int(f["hex_A_orig"] > 0),
                                          "large_int": int(f["large_int"] > 0), "timestamp": int(f["timestamp"] > 0)})
    return acc


# ============================================================================================ statistics helpers
def rate_cell(num_by_s, den_by_s, th):
    """cluster_rate with the prereg zero-count and min-n rules."""
    num = np.asarray(num_by_s, dtype=float)
    den = np.asarray(den_by_s, dtype=float)
    k, nn, ns = int(num.sum()), int(den.sum()), int((den > 0).sum())
    out = {"k": k, "n": nn, "n_sessions": ns}
    if nn < th["rate_den_min"] or ns < th["rate_sessions_min"]:
        out["label"] = "insufficient n"
        return out
    out.update({kk: v for kk, v in stats.cluster_rate(num, den).items() if kk in ("rate", "lo", "hi")})
    if k == 0:
        out["wilson_hi_per_event"] = stats.wilson(0, nn)[2]
        out["wilson_hi_per_session"] = stats.wilson(0, ns)[2]
    return out


def by_session(mask, sids):
    num, den = Counter(), Counter()
    for m, s in zip(mask, sids):
        den[s] += 1
        num[s] += int(m)
    keys = list(den)
    return [num[k] for k in keys], [den[k] for k in keys]


def hex_class_row(d, th, do_test=True):
    toks = list(d)
    lens = Counter(len(t) for t in toks)
    n_sym = int(sum(len(t) for t in toks))
    sess = {v[0] for v in d.values()}
    row = {"distinct_tokens": len(toks), "by_length": {str(k): int(v) for k, v in sorted(lens.items())},
           "symbols": n_sym, "sessions": len(sess), "meets_N_min": n_sym >= th["N_min"]}
    if toks:
        obs, exp = pc.hex_counts(toks)
        row["observed_symbol_counts"] = {pc.HEX_SYMBOLS[i]: int(obs[i]) for i in range(16)}
        row["expected_symbol_counts"] = {pc.HEX_SYMBOLS[i]: round(float(exp[i]), 3) for i in range(16)}
        row["digit_share_observed"] = float(obs[:10].sum() / obs.sum())
        row["digit_share_expected"] = float(exp[:10].sum() / exp.sum())
    if do_test and n_sym >= th["N_min"]:
        row["digit_test"] = digit_test_ci({t: v[0] for t, v in d.items()})
    else:
        row["digit_test"] = None
        if n_sym < th["N_min"]:
            row["label"] = f"insufficient n (symbols {n_sym} < N_min {th['N_min']}): raw counts only"
    return row


def by_tool_counts(d):
    c, sy = Counter(), Counter()
    for t, v in d.items():
        c[str(v[2])] += 1
        sy[str(v[2])] += len(t)
    return {k: {"distinct_tokens": int(c[k]), "symbols": int(sy[k])} for k, _ in c.most_common()}


def int_class_row(d, th):
    vals = list(d)
    sids = [d[v][0] for v in vals]
    exp = th["expected_uniform_last_digits"]
    row = {"distinct_values": len(vals), "sessions": len(set(sids))}
    if not vals:
        return row
    row["last_digit_hist"] = {str(k): int(v) for k, v in sorted(Counter(v[-1] for v in vals).items())}
    row["n_digits_hist"] = {str(k): int(v) for k, v in sorted(Counter(len(v) for v in vals).items())}
    row["log10_hist"] = stats.log_histogram([float(v) for v in vals], per_decade=1)
    row["quantiles"] = stats.describe([float(v) for v in vals])
    tests = {"last_0": lambda v: v.endswith("0"), "last_00": lambda v: v.endswith("00"),
             "last_000": lambda v: v.endswith("000"), "last_0_or_5": lambda v: v[-1] in "05"}
    row["round"] = {}
    for name, fn in tests.items():
        cell = rate_cell(*by_session([fn(v) for v in vals], sids), th)
        cell["expected_uniform"] = exp[name]
        if cell.get("rate") is not None:
            cell["excess_over_uniform"] = cell["rate"] - exp[name]
        row["round"][name] = cell
    return row


def ts_class_row(kind, d, th):
    vals = list(d)
    sids = [d[v][0] for v in vals]
    row = {"distinct_values": len(vals), "sessions": len(set(sids))}
    if not vals:
        return row
    if kind == "iso":
        ms = [pc._C["iso_ts"].match(v) for v in vals]
        secs = [m.group(6) for m in ms]
        fr = [m.group(7) for m in ms]
        row["seconds_hist"] = {k: int(v) for k, v in sorted(Counter(secs).items())}
        row["seconds_00"] = rate_cell(*by_session([s == "00" for s in secs], sids), th)
        row["seconds_00"]["expected_uniform"] = 1 / 60
        with_fr = [(f, s) for f, s in zip(fr, sids) if f]
        row["fraction_present"] = {"k": len(with_fr), "n": len(vals)}
        if with_fr:
            row["fraction_all_zero"] = rate_cell(*by_session([set(f) == {"0"} for f, _ in with_fr], [s for _, s in with_fr]), th)
            row["fraction_all_zero"]["expected_uniform"] = float(np.mean([10.0 ** (-len(f)) for f, _ in with_fr]))
            row["fraction_digits_hist"] = {str(k): int(v) for k, v in sorted(Counter(len(f) for f, _ in with_fr).items())}
    elif kind == "epoch_s":
        row["last_0"] = rate_cell(*by_session([v.endswith("0") for v in vals], sids), th)
        row["last_0"]["expected_uniform"] = 0.1
    else:
        row["last_000"] = rate_cell(*by_session([v.endswith("000") for v in vals], sids), th)
        row["last_000"]["expected_uniform"] = 0.001
    return row


def x_class_row(kind, d, th):
    """EXPLORATORY (not pre-registered)."""
    vals = list(d)
    sids = [d[v][0] for v in vals]
    row = {"distinct_values": len(vals), "sessions": len(set(sids))}
    if not vals:
        return row
    if kind == "duration_frac":
        ms = [RX_X[kind].match(v) for v in vals]
        fr = [m.group(2) for m in ms]
        row["fraction_all_zero"] = rate_cell(*by_session([set(f) == {"0"} for f in fr], sids), th)
        row["fraction_all_zero"]["expected_uniform"] = float(np.mean([10.0 ** (-len(f)) for f in fr]))
        row["fraction_digits_hist"] = {str(k): int(v) for k, v in sorted(Counter(len(f) for f in fr).items())}
        row["last_fraction_digit_hist"] = {k: int(v) for k, v in sorted(Counter(f[-1] for f in fr).items())}
    elif kind == "ls_mtime_hhmm":
        mins = [RX_X[kind].search(v).group(2) for v in vals]
        row["minute_00"] = rate_cell(*by_session([m == "00" for m in mins], sids), th)
        row["minute_00"]["expected_uniform"] = 1 / 60
        row["minute_last_digit_hist"] = {k: int(v) for k, v in sorted(Counter(m[-1] for m in mins).items())}
    else:
        nums = [RX_X[kind].search(v).group(1) for v in vals]
        row["last_00"] = rate_cell(*by_session([x.endswith("00") for x in nums], sids), th)
        row["last_00"]["expected_uniform"] = 0.01
        row["last_0"] = rate_cell(*by_session([x.endswith("0") for x in nums], sids), th)
        row["last_0"]["expected_uniform"] = 0.1
        row["last_digit_hist"] = {k: int(v) for k, v in sorted(Counter(x[-1] for x in nums).items())}
    return row


def census_block(per_s, fields, th):
    keys = list(per_s)
    out = {"n": int(sum(per_s[k]["n"] for k in keys)), "n_sessions": len(keys)}
    for f in fields:
        out[f] = rate_cell([per_s[k][f] for k in keys], [per_s[k]["n"] for k in keys], th)
    return out


# ============================================================================================ verdicts
ORDER = {"DEAD": 0, "WEAK": 1, "ALIVE": 2}


def hex_verdict(T, C_git, C_all, th):
    ctrl_name = "M_git" if C_git["symbols"] >= th["N_min"] else "M_all"
    C = C_git if ctrl_name == "M_git" else C_all
    dt_c = C.get("digit_test") or {}
    dt_t = T.get("digit_test") or {}
    dec = {"N_min": th["N_min"], "T_orig_symbols": T["symbols"], "T_orig_tokens": T["distinct_tokens"],
           "T_orig_sessions": T["sessions"], "control": ctrl_name, "control_symbols": C["symbols"],
           "control_sessions": C["sessions"], "control_w_adj": dt_c.get("w_adj"), "control_w_adj_hi": dt_c.get("w_adj_hi"),
           "instrument_ceiling": th["instrument_ceiling"], "alive_w": th["alive_w"],
           "T_orig_w_adj": dt_t.get("w_adj"), "T_orig_w_adj_lo": dt_t.get("w_adj_lo"),
           "T_orig_w_adj_hi": dt_t.get("w_adj_hi"), "T_orig_chi2": dt_t.get("chi2"), "T_orig_p": dt_t.get("p")}
    if T["symbols"] < th["N_min"]:
        return "INSUFFICIENT_N", f"T_orig symbols {T['symbols']} < N_min {th['N_min']}", dec
    if C["symbols"] < th["N_min"]:
        return "INSUFFICIENT_N", f"control {ctrl_name} symbols {C['symbols']} < N_min {th['N_min']}", dec
    h = dt_c.get("w_adj_hi")
    if h is None:
        return "INSUFFICIENT_N", f"control {ctrl_name} w_adj CI not reportable (< 900 valid bootstrap draws)", dec
    if h > th["instrument_ceiling"]:
        return "DEAD", f"instrument: control {ctrl_name} w_adj CI hi {h:.4f} > {th['instrument_ceiling']}", dec
    w, lo = dt_t.get("w_adj"), dt_t.get("w_adj_lo")
    if w is not None and w >= th["alive_w"] and lo is not None and lo > h:
        return "ALIVE", f"T_orig w_adj {w:.4f} >= {th['alive_w']} and CI lo {lo:.4f} > control hi {h:.4f}", dec
    if w is not None and w > h:
        return "WEAK", f"T_orig w_adj {w:.4f} > control hi {h:.4f}, ALIVE condition not met", dec
    return "DEAD", f"T_orig w_adj {w if w is None else round(w, 4)} <= control hi {h:.4f}", dec


def round_verdict(T, M, th):
    tl, ml = T.get("round", {}).get("last_0", {}), M.get("round", {}).get("last_0", {})
    dec = {"T_orig_distinct": T.get("distinct_values", 0), "T_orig_sessions": T.get("sessions", 0),
           "M_all_distinct": M.get("distinct_values", 0), "M_all_sessions": M.get("sessions", 0),
           "T_orig_last0": tl.get("rate"), "T_orig_last0_lo": tl.get("lo"), "T_orig_last0_hi": tl.get("hi"),
           "T_orig_last0_k_n": [tl.get("k"), tl.get("n")],
           "M_all_last0": ml.get("rate"), "M_all_last0_lo": ml.get("lo"), "M_all_last0_hi": ml.get("hi"),
           "M_all_last0_k_n": [ml.get("k"), ml.get("n")], "margin": th["round_margin"],
           "min_values": th["round_min_values"], "min_sessions": th["round_min_sessions"]}
    for nm, row in (("T_orig", T), ("M_all", M)):
        if row.get("distinct_values", 0) < th["round_min_values"] or row.get("sessions", 0) < th["round_min_sessions"]:
            return "INSUFFICIENT_N", (f"{nm} has {row.get('distinct_values', 0)} distinct values from "
                                      f"{row.get('sessions', 0)} sessions (< {th['round_min_values']} / "
                                      f"{th['round_min_sessions']})"), dec
    mh = ml.get("hi")
    if ml.get("k") == 0:
        mh = ml.get("wilson_hi_per_event")
    dec["M_all_hi_used"] = mh
    if tl.get("lo") is not None and tl["lo"] > mh + th["round_margin"]:
        return "ALIVE", f"T_orig last-0 CI lo {tl['lo']:.4f} > M_all CI hi {mh:.4f} + {th['round_margin']}", dec
    if tl.get("rate") is not None and tl["rate"] > mh:
        return "WEAK", f"T_orig last-0 {tl['rate']:.4f} > M_all CI hi {mh:.4f}", dec
    return "DEAD", f"T_orig last-0 {tl.get('rate')} <= M_all CI hi {mh}", dec


def apply_redaction_cap(main_label, rerun_label):
    """prereg probe4.verdict.caps: 'swechat: verdict stands only if the redaction sensitivity run gives the same
    label, else WEAK'. Applied literally (fixed before any B number): a differing rerun label gives WEAK."""
    if main_label in ("INSUFFICIENT_N", "NOT_TESTABLE"):
        return main_label, "cap not applicable"
    if rerun_label == main_label:
        return main_label, "redaction rerun gives the same label: verdict stands"
    return "WEAK", f"redaction rerun label {rerun_label} != {main_label}: WEAK (literal cap)"


# ============================================================================================ unit / pooled summaries
def summarise_values(hexd, intd, th, tests=True):
    """hexd: {variant: {class: dict}}, intd: same for ints. Returns per-variant class rows."""
    out = {}
    for var in VARIANTS:
        hx = {c: hex_class_row(hexd[var][c], th, do_test=tests and (var == "main" or c in ("M_git", "M_all", "T_orig")))
              for c in HEX_CLASSES}
        it = {c: int_class_row(intd[var][c], th) for c in VAL_CLASSES}
        out[var] = {"hex": hx, "ints": it}
    return out


def verdict_block(vals, th, swechat_cap, labels):
    res = {}
    hv, hreason, hdec = hex_verdict(vals["main"]["hex"]["T_orig"], vals["main"]["hex"]["M_git"],
                                    vals["main"]["hex"]["M_all"], th)
    rv, rreason, rdec = round_verdict(vals["main"]["ints"]["T_orig"], vals["main"]["ints"]["M_all"], th)
    res["hex_primary"] = {"verdict_uncapped": hv, "reason": hreason, "deciding": hdec}
    res["round_numbers_secondary"] = {"verdict_uncapped": rv, "reason": rreason, "deciding": rdec}
    for name, (lab, fn) in (("hex_primary", (hv, None)), ("round_numbers_secondary", (rv, None))):
        final = lab
        if swechat_cap:
            reruns = {}
            for var in ("noredact", "noredact_strict"):
                if name == "hex_primary":
                    reruns[var] = hex_verdict(vals[var]["hex"]["T_orig"], vals[var]["hex"]["M_git"],
                                              vals[var]["hex"]["M_all"], th)
                else:
                    reruns[var] = round_verdict(vals[var]["ints"]["T_orig"], vals[var]["ints"]["M_all"], th)
            final, cap_note = apply_redaction_cap(lab, reruns["noredact"][0])
            alt, _ = apply_redaction_cap(lab, reruns["noredact_strict"][0])
            res[name]["redaction_rerun"] = {var: {"verdict": r[0], "reason": r[1], "deciding": r[2]}
                                            for var, r in reruns.items()}
            res[name]["redaction_cap"] = cap_note
            res[name]["verdict_if_strict_rerun_used"] = alt
        res[name]["verdict"] = final
        res[name]["labels"] = list(labels)
    return res


def unit_summary(acc, th, unit_labels, swechat_cap):
    vals = summarise_values(acc.hex, acc.ints, th)
    out = {"sessions": len(acc.sessions), "labels": unit_labels, "git_calls": acc.git_calls,
           "counts": dict(sorted(acc.cnt.items()))}
    # census
    rfields = ["hex", "large_int", "timestamp", "uuid", "any_hex_int_ts", "redacted"]
    out["census"] = {"results": census_block(acc.cen_res, rfields, th),
                     "calls": census_block(acc.cen_call, ["hex", "hex_T_orig", "large_int", "timestamp"], th),
                     "assistant": census_block(acc.cen_asst, ["hex", "hex_A_orig", "large_int", "timestamp"], th),
                     "results_by_tool": {}, "calls_by_tool": {}}
    for tool, per_s in sorted(acc.cen_res_tool.items(), key=lambda kv: -sum(c["n"] for c in kv[1].values())):
        out["census"]["results_by_tool"][str(tool)] = census_block(per_s, ["hex", "large_int", "timestamp", "uuid",
                                                                           "any_hex_int_ts"], th)
    for tool, per_s in sorted(acc.cen_call_tool.items(), key=lambda kv: -sum(c["n"] for c in kv[1].values())):
        out["census"]["calls_by_tool"][str(tool)] = census_block(per_s, ["hex", "hex_T_orig", "large_int", "timestamp"], th)
    hp = np.asarray(acc.hex_per_result, dtype=float)
    ip = np.asarray(acc.int_per_result, dtype=float)
    out["census"]["hex_tokens_per_result"] = {"all_results": stats.describe(hp),
                                              "given_any": stats.describe(hp[hp > 0]),
                                              "given_any_log_hist": stats.log_histogram(hp[hp > 0], per_decade=4)}
    out["census"]["large_ints_per_result"] = {"all_results": stats.describe(ip), "given_any": stats.describe(ip[ip > 0]),
                                              "given_any_log_hist": stats.log_histogram(ip[ip > 0], per_decade=4)}
    out["hex"] = {var: vals[var]["hex"] for var in VARIANTS}
    out["hex_by_tool_first_occurrence"] = {c: by_tool_counts(acc.hex["main"][c]) for c in ("M_git", "M_all", "T_copy", "T_orig")}
    out["ints"] = {var: vals[var]["ints"] for var in VARIANTS}
    if acc.private:  # cc_local: quantiles (min/max) of integer values would expose individual values
        for var in VARIANTS:
            for row in out["ints"][var].values():
                row.pop("quantiles", None)
    out["timestamps"] = {k: {c: ts_class_row(k, acc.ts[k][c], th) for c in VAL_CLASSES} for k in TS_KINDS}
    out["exploratory_not_preregistered"] = {
        "note": "Requested by the Phase B task, not in prereg.json. Descriptive only; feeds no verdict.",
        "expectations": X_EXPECT,
        "patterns": {k: v.pattern for k, v in RX_X.items()},
        "classes": {k: {c: x_class_row(k, acc.x[k][c], th) for c in VAL_CLASSES} for k in RX_X}}
    # POST-HOC DESCRIPTIVE (added after the first full run produced the verdicts; feeds no verdict, changes none)
    ph = {"note": "added after the verdicts were first computed, to describe what the round T_orig large integers are; "
                  "feeds no verdict", "ints_T_by_origin": {}, "ints_by_tool_first_occurrence": {}}
    for cls in ("T_copy", "T_orig"):
        d = acc.ints["main"][cls]
        ph["ints_T_by_origin"][cls] = {}
        for origin in ("json_number", "args_string"):
            ov = [v for v in d if acc.int_origin[cls].get(v) == origin]
            sids_ = [d[v][0] for v in ov]
            ph["ints_T_by_origin"][cls][origin] = {
                "distinct_values": len(ov), "sessions": len(set(sids_)),
                "last_0": rate_cell(*by_session([v.endswith("0") for v in ov], sids_), th),
                "last_000": rate_cell(*by_session([v.endswith("000") for v in ov], sids_), th)}
    for cls in ("M_all", "T_copy", "T_orig", "A_orig"):
        ph["ints_by_tool_first_occurrence"][cls] = {k: v["distinct_tokens"] for k, v in by_tool_counts(acc.ints["main"][cls]).items()}
    out["post_hoc_descriptive"] = ph
    if not acc.private:
        out["examples_descriptive_ints"] = {
            "note": "public units only; top occurrence counts of model-originated large integers; POST-HOC; feeds no verdict",
            "T_orig_top": [[v, int(n)] for v, n in acc.occ_int["T_orig"].most_common(15)],
            "A_orig_top": [[v, int(n)] for v, n in acc.occ_int["A_orig"].most_common(15)]}
        out["examples_descriptive"] = {
            "note": "public units only; top occurrence counts of model-originated tokens of length 7/8 (git-hash-like); "
                    "feeds no verdict",
            "T_orig_top": [[t, int(n)] for t, n in acc.occ["T_orig"].most_common(200) if len(t) in PUBLIC_EXAMPLE_LENGTHS][:15],
            "A_orig_top": [[t, int(n)] for t, n in acc.occ["A_orig"].most_common(200) if len(t) in PUBLIC_EXAMPLE_LENGTHS][:15]}
    out["verdicts"] = verdict_block(vals, th, swechat_cap, unit_labels)
    return out


def pool(accs, units):
    hexd = {v: {c: {} for c in HEX_CLASSES} for v in VARIANTS}
    intd = {v: {c: {} for c in VAL_CLASSES} for v in VARIANTS}
    for unit in units:
        a = accs.get(unit)
        if a is None:
            continue
        for v in VARIANTS:
            for c in HEX_CLASSES:
                dst = hexd[v][c]
                for t, (s, q, tl) in a.hex[v][c].items():
                    cur = dst.get(t)
                    if cur is None or (s, q) < (cur[3], cur[4]):
                        dst[t] = (f"{unit}|{s}", q, tl, s, q)
            for c in VAL_CLASSES:
                dst = intd[v][c]
                for t, (s, q, tl) in a.ints[v][c].items():
                    cur = dst.get(t)
                    if cur is None or (s, q) < (cur[3], cur[4]):
                        dst[t] = (f"{unit}|{s}", q, tl, s, q)
    return hexd, intd


# ============================================================================================ A implementation check
def implementation_check_A(th):
    """Counts only (already present in prereg_calibration.json); no digit test, no round share on A."""
    cal = json.load(open(CALIB_JSON, encoding="utf-8"))
    out = {"note": "this script's extraction re-run on split A; compares only token/value COUNTS that "
                   "prereg_calibration.json already holds. No digit test or round share is computed on A.",
           "units": {}}
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        df = pc.load_split(corpus, "A", COLS, filters=[("kind", "in", KINDS)])
        for unit, u in pc.unit_frames(corpus, df).items():
            c = cal["units"].get(unit, {}).get("probe4")
            if not c:
                continue
            acc = extract(unit, u, unit == "cc_local", counts_only=True)
            rows = {}
            for cls in HEX_CLASSES:
                d = acc.hex["main"][cls]
                mine = {"distinct_tokens": len(d), "symbols": int(sum(len(t) for t in d)),
                        "sessions": len({v[0] for v in d.values()})}
                ref = {k: c["classes"][cls][k] for k in ("distinct_tokens", "symbols", "sessions")}
                rows[cls] = {"mine": mine, "calibration": ref, "match": mine == ref}
            for cls in VAL_CLASSES:
                d = acc.ints["main"][cls]
                mine = {"distinct_values": len(d), "sessions": len({v[0] for v in d.values()})}
                ref = {k: c["classes"]["ints/" + cls][k] for k in ("distinct_values", "sessions")}
                rows["ints/" + cls] = {"mine": mine, "calibration": ref, "match": mine == ref}
            rows["git_calls"] = {"mine": acc.git_calls, "calibration": c["git_calls"], "match": acc.git_calls == c["git_calls"]}
            rows["hex_dropped_redaction"] = {"mine": acc.cnt["hex_dropped_redaction"],
                                             "calibration": c["counts"].get("hex_dropped_redaction", 0)}
            rows["json_number_epoch_excluded_A"] = acc.cnt["json_number_epoch_excluded"]
            out["units"][unit] = rows
        del df
        gc.collect()
    mism = [(u, k) for u, r in out["units"].items() for k, v in r.items() if isinstance(v, dict) and v.get("match") is False]
    out["mismatches"] = [f"{u}:{k}" for u, k in mism]
    return out


# ============================================================================================ main
def main():
    t0 = time.time()
    pr, th, prov = load_prereg()
    print(f"prereg OK: spec sha {prov['spec_module_sha256'][:12]}, N_min {th['N_min']}", flush=True)
    result = {"probe": "probe4 entropy / incidental detail", "script": "analysis/probes/probe_4.py",
              "split": "B (analysis/cache/<corpus>_B.parquet); split A read only for the implementation count check",
              "provenance": prov, "thresholds_used": th,
              "population_B_prereg": pr["population_B"]["sessions"],
              "prereg_reference": {
                  "note": "copied verbatim from prereg.json for side-by-side reading; A-split values, not B results",
                  "feasibility_projection_p4": {u: {k: v for k, v in cells.items() if k.startswith("p4_")}
                                                for u, cells in pr["resolved"]["feasibility_projection"]["cells"].items()},
                  "control_A": {u: {c: {"symbols": e[c]["symbols"],
                                        "w_adj": (e[c]["digit_test"] or {}).get("w_adj"),
                                        "w_adj_hi": (e[c]["digit_test"] or {}).get("w_adj_hi")}
                                    for c in ("M_git", "M_all")}
                                for u, e in pr["resolved"]["probe4"]["control_A"].items()}}}
    print("implementation check on A (counts only) ...", flush=True)
    result["implementation_check_A"] = implementation_check_A(th)
    print(f"[{time.time() - t0:6.1f}s] A check mismatches: {result['implementation_check_A']['mismatches']}", flush=True)

    accs = {}
    units_out = {}
    sessions_B = {}
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        if corpus == "swechat":
            # one format at a time (RAM): rows of the format's B sessions, model-visible kinds only
            fm = pc.swechat_formats()
            allb = pd.read_parquet(pc.CACHE / "swechat_B.parquet", columns=["session_id"]).session_id.astype(str).unique()
            by_fmt = defaultdict(list)
            for s in allb:
                by_fmt[fm.get(s)].append(s)
            sessions_B.update({f"swechat/{f}": len(v) for f, v in by_fmt.items()})
            frames = ((f"swechat/{f}", pc.load_split(corpus, "B", COLS, filters=[("session_id", "in", v),
                                                                                  ("kind", "in", KINDS)]))
                      for f, v in sorted(by_fmt.items(), key=lambda kv: str(kv[0])) if f is not None)
        else:
            sessions_B[corpus] = int(pd.read_parquet(pc.CACHE / f"{corpus}_B.parquet", columns=["session_id"]).session_id.nunique())
            frames = iter([(corpus, pc.load_split(corpus, "B", COLS, filters=[("kind", "in", KINDS)]))])
        for unit, u in frames:
            print(f"[{time.time() - t0:6.1f}s] {unit}: {len(u)} rows, {u.session_id.nunique()} sessions", flush=True)
            acc = extract(unit, u, unit == "cc_local")
            accs[unit] = acc
            labels = []
            nsess = sessions_B.get(unit, len(acc.sessions))
            if nsess < th["small_n_sessions"]:
                labels.append("small n")
            if unit == "aiv_cc":
                labels.append("single-agent case study")
            if unit == "swechat/cursor":
                labels.append("control_missing: no results, so no machine class (prereg probe4.units.control_missing)")
            units_out[unit] = unit_summary(acc, th, labels, swechat_cap=unit.startswith("swechat/"))
            if unit == "cc_local":
                units_out[unit].pop("examples_descriptive", None)
                units_out[unit].pop("examples_descriptive_ints", None)
            del u
            gc.collect()
    for unit, why in pr["probe4"]["units"]["not_testable"].items():
        units_out[unit] = {"verdicts": {"hex_primary": {"verdict": "NOT_TESTABLE", "reason": why},
                                        "round_numbers_secondary": {"verdict": "NOT_TESTABLE", "reason": why}},
                           "sessions": sessions_B.get(unit, 0)}
    # aiv_cc rule
    a = pd.read_parquet(pc.CACHE / "aiv_cc_A.parquet", columns=["session_id"]).session_id.astype(str).unique()
    b = pd.read_parquet(pc.CACHE / "aiv_cc_B.parquet", columns=["session_id"]).session_id.astype(str).unique()
    sa = {s.rsplit("/", 1)[0] for s in a}
    sb = {s.rsplit("/", 1)[0] for s in b}
    result["aiv_cc_rule"] = {"B_runs": int(len(b)), "B_distinct_sdk_session_id": len(sb), "A_distinct_sdk_session_id": len(sa),
                             "B_runs_sharing_sdk_session_with_A": int(sum(1 for s in b if s.rsplit("/", 1)[0] in sa)),
                             "label": "single-agent case study"}
    result["sessions_B_observed"] = sessions_B
    result["units"] = units_out

    # pooled cells
    sw_units = [u for u in accs if u.startswith("swechat/")]
    pub_units = [u for u in accs if u != "cc_local"]
    pooled = {}
    for name, members in (("swechat/*", sw_units), ("public/*", pub_units)):
        hexd, intd = pool(accs, members)
        vals = summarise_values(hexd, intd, th)
        pooled[name] = {"members": members, "labels": ["pooled"],
                        "sessions": int(sum(len(accs[m].sessions) for m in members)),
                        "hex": {var: vals[var]["hex"] for var in VARIANTS},
                        "ints": {var: vals[var]["ints"] for var in VARIANTS},
                        "verdicts": verdict_block(vals, th, swechat_cap=True, labels=["pooled"])}
        if name == "public/*":
            pooled[name]["labels"].append("contains aiv_cc (single-agent case study) and swechat")
    result["pooled"] = pooled

    # verdict table
    table = {}
    n_cells = 0
    for unit, r in list(units_out.items()) + list(pooled.items()):
        vv = r["verdicts"]
        table[unit] = {k: vv[k]["verdict"] for k in ("hex_primary", "round_numbers_secondary")}
        n_cells += 2
    result["verdict_table"] = table
    result["n_verdict_cells"] = n_cells
    result["runtime_s"] = round(time.time() - t0, 1)
    txt = json.dumps(result, indent=1, default=str, ensure_ascii=False)
    OUT.write_text(txt, encoding="utf-8")
    OUT_PB.parent.mkdir(parents=True, exist_ok=True)
    OUT_PB.write_text(txt, encoding="utf-8")
    print(json.dumps(table, indent=1))
    print(f"done in {time.time() - t0:.1f}s -> {OUT} and {OUT_PB}")


if __name__ == "__main__":
    main()
