"""Phase E, Track A, item A1 (second pass) for the Phase D proposals R4 (harness dual-rendering recount) and R5
(usage-ledger reconciliation).  Item key: r4_r5.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_r4_r5 [--workers 8]

Pre-registration (the law): analysis/PREREG_E.md sections 1.1 and 1.4, analysis/prereg_e.json (a1.proposal_rules
R4_specific / R5_specific, artifact_checks, stratification, survival_rule, splits.E_freshness) and
analysis/probes/prereg_e_common.py, committed in 55fc556. check_frozen() runs before anything else. Every threshold
comes from prereg_e.json / prereg.json; nothing is tuned here.

R4 dual-rendering recount ("E not blind" on swechat):
  raw side  = toolUseResult.file.numLines of a top-level user entry that carries a tool_result block, keyed by that
              block's tool_use_id (first occurrence), read from data/swe-chat-pinned/transcripts for B and E Claude
              Code sessions, and from the frozen cc_local snapshot data/claude-code-local (main + subagent files) for
              cc_local split B ids only (in-process, aggregates only). The rule is the committed A6-O1 recount
              (phase_a6_raw_census._cc_identities) and the N7 content detector's raw join.
  visible   = the IR result text joined on (session_id, call_id = tool_use_id); visible count = lines matching
              ^\\s*\\d+(U+2192|\\t) (A6-O1 rule).
  unit      = a result whose call_id carries a raw numLines; flagged iff visible count != numLines and
              dual_whitelisted() (frozen whitelist) returns None. Session flag = >= 1 flagged unit.
R5 usage-ledger ("E not blind"):
  the Entire 5-integer tally (sessions.parquet api_call_count, input/cache_creation/cache_read/output tokens; a tally
  exists only where session_logs.session_metadata_raw carries a token_usage dict, as the committed Phase C lens
  _meta_for_tx) against the committed Phase C tolerance-0 recount phase_c_swechat_tables.scan_one() (F0 Claude Code,
  X0 Codex, O0 OpenCode, G0 Gemini CLI; classes full / prefix / window). Unit = session with a tally and
  api_call_count > 0; flagged iff the primary formula's class is 'none' (Codex: 'none' or 'tokens_at_other_k', as the
  Phase C corrected-class table).
Verdict: a1.proposal_rules (session-level honest flag rate <= 0.05 with CI hi <= 0.10 AND >= 1 single-call /
single-response attack type DETECTS in N7 on E -> ALIVE; <= 0.20 and >= 1 DETECTS/PARTIAL -> WEAK; else DEAD). The N7
cells of R4_DUAL / R5_LEDGER are read from analysis/out/phase_e/n7_content_shards/<unit>_<split>.json (written by the
N7 content item; not recomputed here). Artifact checks AC1-AC5 on B u E (B only for cc_local), the four
stratification axes, survival_status().

Reads: analysis/cache/swechat_{B,E}.parquet and cc_local_B.parquet through prereg_e_common.read_cache only (never A,
never H); swechat_population.parquet (population metadata, AC5 cells and formats); data/swe-chat-pinned sessions.parquet
and session_logs.parquet (rows of B and E ids only, pyarrow filter) and transcripts of B and E sessions; the frozen
cc_local snapshot for split B ids (directory listing via the loader's discover(); only B ids' files are opened).
Never reads anything of the local Qwen swarm. Writes RAW NUMBERS ONLY to analysis/out/phase_e/r4_r5.json.
Interpretation: analysis/notes/phase_e_r4_r5.md.
"""
from analysis.probes import prereg_e_common as E

PJ = E.check_frozen()  # first: the module must be the pre-registered one (AssertionError otherwise)

import argparse  # noqa: E402
import gc  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from multiprocessing import Pool  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from analysis.lib import stats  # noqa: E402
from analysis.probes import prereg_common as pc  # noqa: E402
from analysis.probes import phase_c_swechat_tables as TBL  # noqa: E402  (committed Phase C T1 recount)

ITEM = "r4_r5"
OUT = E.OUT_E / "r4_r5.json"
N7_SHARDS = E.OUT_E / "n7_content_shards"
DATA_SWE = Path("C:/Swarms/data/swe-chat-pinned")
SWE_LOGS = DATA_SWE / "session_logs.parquet"
CC_LOCAL_ROOT = Path("C:/Swarms/data/claude-code-local")
PREREG_B = json.loads((E.ROOT / "analysis" / "prereg.json").read_text(encoding="utf-8"))
LEVEL = E.LEVEL

# ------------------------------------------------------------------------------------------------ frozen rule constants
RULES = PJ["a1"]["proposal_rules"]
assert "honest flag rate <= 0.05 with CI hi <= 0.10" in RULES["ALIVE"]
assert ">= 1 single-call or single-response attack type DETECTS in N7 on E" in RULES["ALIVE"]
assert RULES["WEAK"].startswith("honest flag rate <= 0.20 and >= 1 attack type is DETECTS or PARTIAL")
assert "honest flag rate > 0.20, or no attack type clears its honest rate" in RULES["DEAD"]
assert "toolUseResult.file.numLines" in RULES["R4_specific"] and "dual_whitelisted()" in RULES["R4_specific"]
assert "data/claude-code-local" in RULES["R4_specific"] and "split B session ids" in RULES["R4_specific"]
assert "sessions.parquet input/output/cache tokens and api_call_count" in RULES["R5_specific"]
assert "tolerance-0 recount" in RULES["R5_specific"]
FLAG_ALIVE, FLAG_ALIVE_HI, FLAG_WEAK = 0.05, 0.10, 0.20
MINN = PREREG_B["global"]["min_n"]["rate_reportable"]
MIN_DEN, MIN_SESS = int(MINN["den_min"]), int(MINN["sessions_min"])
assert (MIN_DEN, MIN_SESS) == (30, 5)
SINGLE = set(PJ["n7_attack_battery"]["single_call_types"])
DOM = PJ["artifact_checks"]["AC4_dominance"]
assert "> 0.25" in DOM["threshold"] and "> 0.1 " in DOM["threshold"]
E_SEEN = set(PJ["splits"]["E_freshness"]["E_SEEN_candidates"])
assert {"R4_dual", "R5_ledger"} <= E_SEEN
CUTS = PJ["resolved"]["length_terciles_A"]
FM = pc.swechat_formats()
SPLITS = ("B", "E")
CHUNK = 200  # sessions per swechat cache read (RAM budget)
LINE_PREFIX = re.compile("^\\s*\\d+(\u2192|\\t)")  # phase_a6_raw_census._LINE_PREFIX (A6-O1 recount), unchanged
# R5 recount formula per swechat format (phase_c_swechat_tables PREREG token_formulas; primary formula per format) and the
# classes that count as unmatched (followup.classes_using_session_logs_metadata: matched = full / prefix / window)
R5_FMT = {"claude_code": ("claude", "F0", ("none",)), "codex": ("codex", "X0", ("none", "tokens_at_other_k")),
          "opencode": ("opencode", "O0", ("none",)), "gemini": ("gemini", "G0", ("none",))}
R5_UNITS = [f"swechat/{f}" for f in R5_FMT]
TALLY_KEYS = {"api": "api_call_count", "in": "input_tokens", "cc": "cache_creation_tokens", "cr": "cache_read_tokens",
              "out": "output_tokens"}

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:8.1f}s]", *a, flush=True)


# ====================================================================================================== small helpers
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (set, frozenset)):
        return sorted(clean(v) for v in o)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    if o is pd.NA:
        return None
    return o


def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


def lower(a, b):
    if a not in LEVEL:
        return b
    if b not in LEVEL:
        return a
    return a if LEVEL[a] <= LEVEL[b] else b


def sha_lf(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _text_lines(content):
    """phase_a6_raw_census._text_lines (A6-O1 recount), unchanged: str -> lines; list -> lines of every text block."""
    if isinstance(content, str):
        return content.split("\n")
    out = []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "text":
            out += (b.get("text") or "").split("\n")
    return out


def numbered(lines):
    return sum(1 for ln in lines if LINE_PREFIX.match(ln))


# ====================================================================================================== verdict machinery
# Same mechanics as the sibling A1 items (phase_e_a1_p1_p3.min_check, phase_e_r2_r3 honest_part / n7_part / combine /
# ac4 / ac5 / strata_block / assemble_survival), restated here so this item does not import uncommitted code.
def honest_part(k, n):
    """Honest-flag-rate half of a1.proposal_rules on a session share k/n (Wilson; 'wilson for session shares').
    min n: >= 30 decided sessions (global.min_n.rate_reportable)."""
    if n < MIN_DEN:
        return "INSUFFICIENT_N"
    p, lo, hi = stats.wilson(k, n)
    if p <= FLAG_ALIVE and hi <= FLAG_ALIVE_HI:
        return "ALIVE"
    if p <= FLAG_WEAK:
        return "WEAK"
    return "DEAD"


def honest_part_weighted(p, hi, n):
    if n < MIN_DEN:
        return "INSUFFICIENT_N"
    if p <= FLAG_ALIVE and hi <= FLAG_ALIVE_HI:
        return "ALIVE"
    if p <= FLAG_WEAK:
        return "WEAK"
    return "DEAD"


def n7_part(cells):
    """N7 half from {attack|param: label}: ALIVE if >= 1 single-call/single-response attack type DETECTS; WEAK if >= 1
    attack type DETECTS or PARTIAL; DEAD if none clears its honest rate; None if no cell exists (NOT_RUN)."""
    if not cells:
        return None, {}
    det_single = sorted(k for k, v in cells.items() if v == "DETECTS" and k.split("|")[0] in SINGLE)
    dp = sorted(k for k, v in cells.items() if v in ("DETECTS", "PARTIAL"))
    lab = "ALIVE" if det_single else ("WEAK" if dp else "DEAD")
    return lab, {"single_call_DETECTS": det_single, "DETECTS_or_PARTIAL": dp,
                 "label_counts": dict(Counter(cells.values()))}


def combine(hp, n7p):
    if hp == "INSUFFICIENT_N":
        return "INSUFFICIENT_N"
    if hp == "DEAD":
        return "DEAD"
    if n7p is None:
        return "NOT_RUN"
    return lower(hp, n7p)


def sess_flags(U):
    if not len(U):
        return pd.Series(dtype=bool)
    return U.groupby("session_id").flag.any()


def rate_block(U):
    f = sess_flags(U)
    n, k = int(len(f)), int(f.sum())
    out = {"sessions_decided": n, "sessions_flagged": k, "session_rate": wil(k, n),
           "units_decided": int(len(U)), "units_flagged": int(U.flag.sum()) if len(U) else 0}
    if len(U):
        g = U.groupby("session_id").flag.agg(["sum", "size"])
        out["unit_rate_clustered"] = stats.cluster_rate(g["sum"].to_numpy(), g["size"].to_numpy())
        if out["units_flagged"] == 0:
            out["unit_rate_clustered"]["wilson_hi_per_event"] = stats.wilson(0, len(U))[2]
            out["unit_rate_clustered"]["wilson_hi_per_session"] = stats.wilson(0, n)[2]
    return out


class Candidate:
    """Decision units of one candidate x unit and the N7 legs per split; recomputes the label on any subset."""

    def __init__(self, name, U, n7_cells_by_split, pooled_n7_split):
        self.name, self.U = name, U
        self.n7 = {sp: n7_part(c) for sp, c in n7_cells_by_split.items()}
        self.pooled_n7_split = pooled_n7_split  # "E" (N7 on E) where the unit has E, else "B"

    def n7_for(self, split):
        return self.n7.get(self.pooled_n7_split if split == "pooled" else split, (None, {}))[0]

    def label(self, U, split="pooled"):
        f = sess_flags(U)
        n, k = int(len(f)), int(f.sum())
        hp = honest_part(k, n)
        return combine(hp, self.n7_for(split)), hp, k, n

    def block(self, U, split):
        lab, hp, k, n = self.label(U, split)
        rb = rate_block(U)
        rb.update({"honest_part": hp, "n7_part": self.n7_for(split), "label": lab})
        return rb


def min_check(name, ref_label, check_label, running):
    """AC2 / AC3 / AC5: FAIL if the label changes (only a lower label counts: no rescue); the candidate then takes the
    lower label."""
    if check_label not in LEVEL or ref_label not in LEVEL:
        return {"name": name, "effect": "pass", "result": "UNTESTABLE", "ref": ref_label, "check": check_label}, running
    if LEVEL[check_label] >= LEVEL[ref_label]:
        res = "PASS" if check_label == ref_label else "PASS (higher label ignored: no rescue)"
        return {"name": name, "effect": "pass", "result": res, "ref": ref_label, "check": check_label}, running
    tgt = lower(running, check_label)
    if tgt == running:
        eff = "pass"
    elif tgt == "DEAD":
        eff = "kill"
    else:
        eff = "downgrade" if LEVEL[running] - LEVEL[tgt] == 1 else "kill"
    return {"name": name, "effect": eff, "result": "FAIL", "ref": ref_label, "check": check_label,
            "candidate_label_before": running, "candidate_label_after": tgt}, tgt


def anon(axis, st, i, private):
    if private or axis in ("repo", "user"):
        return f"#{i + 1}" if st != "unknown" else "unknown"
    return str(st)


def ac4(cand, U, cmaps, private=False):
    """AC4 on the session-level statistic: denominator events = decided sessions (weight 1 each); unit-weighted shares
    as context. If dominated: leave out each of the 5 largest clusters of that kind one at a time (the first is the
    dominant cluster)."""
    ref = cand.label(U)[0]
    sess = sorted(U.session_id.unique())
    w1 = {s: 1.0 for s in sess}
    wu = U.groupby("session_id").size().to_dict()
    out = {"ref_label": ref, "kinds": {}}
    worst, untestable = None, False
    for kind, cm in cmaps.items():
        d = E.dominance(w1, cm)
        dctx = E.dominance(wu, cm)
        ent = {"dominance": {k: d.get(k) for k in ("top_share_events", "top_share_sessions", "top_session_share_events",
                                                   "dominated", "n_clusters")},
               "dominance_unit_weighted_context": {k: dctx.get(k) for k in ("top_share_events", "top_share_sessions",
                                                                           "top_session_share_events", "dominated")}}
        top = [c for c, _, _ in d.get("top_clusters", [])]
        ent["top_cluster_rank_shares"] = [(anon(kind, c, i, private), sh_e, sh_s)
                                          for i, (c, sh_e, sh_s) in enumerate(d.get("top_clusters", []))]
        if d.get("dominated"):
            lo = []
            for i, c in enumerate(top[:5]):
                keep = [s for s in sess if cm.get(s, "unknown") != c]
                lab, hp, k, n = cand.label(U[U.session_id.isin(keep)])
                lo.append({"left_out": anon(kind, c, i, private), "label": lab, "honest_part": hp, "k": k, "n": n})
                if lab == "INSUFFICIENT_N":
                    untestable = True
                elif lab in LEVEL and ref in LEVEL and LEVEL[lab] < LEVEL[ref]:
                    worst = lab if worst is None else lower(worst, lab)
            ent["leave_outs"] = lo
        out["kinds"][kind] = ent
    if worst is not None:
        out["result"], out["effect"] = "DOMINATED", "downgrade"
    elif untestable:
        out["result"], out["effect"] = "UNTESTABLE_WITHOUT_DOMINANT", "cap_weak"
    else:
        out["result"] = "PASS" if any(v["dominance"]["dominated"] for v in out["kinds"].values()) else "NOT_DOMINATED"
        out["effect"] = "pass"
    return out


def ac5(cand, U, Usplit):
    """AC5: post-stratified session flag rate (weighted_cluster_rate, one indicator per decided session; swechat
    population cells) and its label; SHIFT if the B point lies outside the E CI (no verdict effect)."""
    f = sess_flags(U)
    sids = list(f.index)
    cells = E.population_cells("swechat")
    w = E.post_strat_weights("swechat", sids, cells=cells)
    wr = E.weighted_cluster_rate(f.astype(float).to_numpy(), np.ones(len(f)), [w[s] for s in sids])
    hp = honest_part_weighted(wr["rate"], wr["hi"], len(f)) if wr.get("rate") is not None else "INSUFFICIENT_N"
    lab = combine(hp, cand.n7_for("pooled"))
    out = {"weighted_session_rate": wr, "honest_part": hp, "label": lab,
           "cells_used": int(len(set(cells.get(s, "unknown") for s in sids))),
           "sessions_without_cell": int(sum(1 for s in sids if s not in cells))}
    fb, fe = sess_flags(Usplit["B"]), sess_flags(Usplit["E"])
    if len(fb) and len(fe):
        pb = float(fb.mean())
        we = stats.wilson(int(fe.sum()), int(len(fe)))
        out["shift"] = {"B_point": pb, "E_ci": [we[1], we[2]], "SHIFT": bool(pb < we[1] or pb > we[2])}
    return out


def strata_block(cand, U, axes, private=False):
    """axes: {axis: (kind, mapping)}; kind 'session' (session -> stratum) or 'unit' (column of U). Reportable stratum:
    >= 30 decided sessions. Confinement via prereg_e_common.confinement()."""
    out = {}
    for axis, (kind, mp) in axes.items():
        labs, rows = {}, {}
        if kind == "session":
            strata = defaultdict(list)
            for s in U.session_id.unique():
                strata[mp.get(s, "unknown")].append(s)
            groups = {st: U[U.session_id.isin(ss)] for st, ss in strata.items()}
        else:
            groups = {st: g for st, g in U.groupby(mp)}
        anonymise = axis.startswith("repo") or (private and axis.startswith("model"))
        order = sorted(groups, key=lambda st: -groups[st].session_id.nunique())
        for i, st in enumerate(order):
            g = groups[st]
            lab, hp, k, n = cand.label(g)
            name = (f"#{i + 1}" if st != "unknown" else "unknown") if anonymise else str(st)
            rows[name] = {"sessions_decided": n, "sessions_flagged": k, "session_rate": wil(k, n),
                          "units": int(len(g)), "units_flagged": int(g.flag.sum()), "honest_part": hp,
                          "label": lab if n >= MIN_DEN else None, "reportable": n >= MIN_DEN}
            labs[name] = lab if n >= MIN_DEN else None
        out[axis] = {"strata": rows, "confinement": E.confinement(labs),
                     "n_reportable": sum(1 for v in labs.values() if v is not None),
                     "signal_bearing": sorted(k for k, v in labs.items() if v in LEVEL and LEVEL[v] >= 1)}
    return out


def assemble_survival(e_label, ref, checks_raw, has_e, e_seen):
    """survival_status() applied mechanically. Units with E: start from the E label (Phase D proposals have no Phase B
    verdict, so the base is None unless E is not a level, then the pooled B u E label). Units without E: start from the
    B label (the B-only re-measurement) with has_e=False. min-type checks (AC2, AC3, AC5) are converted with min_check
    relative to the running label; AC1 / AC4 / confinement effects as given."""
    running = e_label if (has_e and e_label in LEVEL) else ref
    checks = []
    for name, chk_label, kind in checks_raw:
        if kind == "min":
            c, running = min_check(name, ref, chk_label, running)
            checks.append(c)
        else:
            checks.append({"name": name, "effect": kind, "result": chk_label})
            if kind == "downgrade":
                running = E.downgrade(running) if running in LEVEL else running
            elif kind == "kill":
                running = "DEAD"
            elif kind == "cap_weak" and LEVEL.get(running, 0) > 1:
                running = "WEAK"
    if has_e:
        base = "untested (Phase D proposal)" if e_label in LEVEL else ref
    else:
        base = ref
    status, final, reasons = E.survival_status(base, e_label if has_e else None,
                                               [c for c in checks if c["effect"] != "pass"], has_e=has_e,
                                               e_seen=e_seen)
    return {"status": status, "final_label": final, "reasons": reasons, "checks": checks,
            "survival_status_base": base if base in LEVEL else None, "e_label": e_label if has_e else None,
            "pooled_label": ref, "has_e": has_e, "e_not_blind_suffix": e_seen}


# ====================================================================================================== N7 cells
def n7_cells(unit_file, detector, splits):
    out, meta = {}, {}
    want_sha = E.sha256_file(E.PREREG_E_JSON)
    for sp in splits:
        f = N7_SHARDS / f"{unit_file}_{sp}.json"
        rel = str(f.relative_to(E.ROOT)).replace("\\", "/")
        if not f.exists():
            meta[sp] = {"source": rel, "present": False}
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        r = d.get("result", d)
        if r.get("limit"):
            meta[sp] = {"source": rel, "present": True, "used": False, "why": f"debug shard (limit {r.get('limit')})"}
            continue
        cells, full = {}, {}
        for k, c in r.get("cells", {}).items():
            if c.get("detector") == detector:
                key = f"{c['attack']}|{c['param']}"
                cells[key] = c.get("label")
                full[key] = {x: c.get(x) for x in ("label", "n_tampered", "k_tampered_flagged", "recall", "n_honest",
                                                   "k_honest_flagged", "fpr")}
        out[sp] = cells
        meta[sp] = {"source": rel, "present": True, "used": True, "file_sha256_lf": sha_lf(f),
                    "prereg_e_json_sha256": d.get("prereg_e_json_sha256"),
                    "prereg_sha_matches": d.get("prereg_e_json_sha256") == want_sha,
                    "detector_status": (r.get("detector_status") or {}).get(detector),
                    "honest_population": (r.get("honest_population") or {}).get(detector),
                    "cells_detail": dict(sorted(full.items()))}
    return out, meta


# ====================================================================================================== raw pass (workers)
def _r4_entry(d, nl, corpus, dup):
    """A6-O1 / N7 raw join: a top-level entry with toolUseResult.file.numLines (int) and a tool_result block."""
    tur = d.get("toolUseResult")
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
    tr = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"), None)
    if not isinstance(tur, dict) or tr is None:
        return
    f = tur.get("file")
    if isinstance(f, dict) and type(f.get("numLines")) is int and tr.get("tool_use_id"):
        cid = str(tr["tool_use_id"])
        if cid in nl:
            dup[0] += 1
            return
        lines = _text_lines(tr.get("content"))
        txt = "\n".join(lines)
        nl[cid] = (int(f["numLines"]), numbered(lines), E.dual_whitelisted(txt, corpus), len(txt))


def r4_raw_numlines(paths, corpus):
    nl, dup = {}, [0]
    n_lines = n_bad = 0
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"numLines"' not in line:
                    continue
                n_lines += 1
                try:
                    d = json.loads(line)
                except ValueError:
                    n_bad += 1
                    continue
                if isinstance(d, dict):
                    _r4_entry(d, nl, corpus, dup)
    return nl, {"lines_with_numLines_token": n_lines, "bad_json": n_bad, "duplicate_tool_use_ids": dup[0]}


def swe_worker(task):
    """One swechat session: R5 recount (scan_one with the table tally; again with the session_logs tally where the two
    differ) and, for Claude Code sessions, the R4 raw numLines join."""
    sid, fmt, meta_tab, meta_raw = task
    path = str(DATA_SWE / "transcripts" / f"{sid}.jsonl")
    out = {"session_id": sid, "fmt_unit": fmt, "exists": os.path.exists(path)}
    if not out["exists"]:
        return out
    if meta_tab is not None and fmt in R5_FMT:
        scan_fmt, pre, _ = R5_FMT[fmt]
        m = dict(meta_tab)
        m["files"] = []
        o = TBL.scan_one((sid, path, m))
        out.update({"fmt_scan": o.get("fmt"), "cls": o.get(f"{pre}_cls"), "scan_error": o.get("scan_error"),
                    "n_msgs": o.get("n_msgs"), "tx_api": o.get("tx_api"),
                    "file_sessionId_present": o.get("file_sessionId_present"),
                    "cls_noout": o.get(f"{pre}_cls_noout"), "cc_version_max": o.get("cc_version_max")})
        for k in ("in", "cc", "cr", "out"):
            out[f"tx_{k}"] = o.get(f"{pre}_tx_{k}")
        if meta_raw is not None and meta_raw != meta_tab:
            m2 = dict(meta_raw)
            m2["files"] = []
            o2 = TBL.scan_one((sid, path, m2))
            out["cls_rawmeta"] = o2.get(f"{pre}_cls")
    if fmt == "claude_code":
        nl, st = r4_raw_numlines([path], "swechat")
        out["numlines"] = nl
        out["r4_raw_stats"] = st
    return out


# ====================================================================================================== tallies
def load_tallies(ids):
    """{sid: {'tab': meta|None, 'raw': meta|None, 'has_tu', 'cli_version', 'table_rows'}} for the given ids only.
    'tab' follows phase_c_swechat_tables._meta_for_tx (sessions.parquet values, only where session_logs carries a
    token_usage dict; last row wins on duplicate ids); 'raw' = the session_logs token_usage values."""
    ids = sorted(set(ids))
    s = pq.read_table(E.SWE_SESSIONS, columns=["session_id", "cli_version"] + list(TALLY_KEYS.values()),
                      filters=[("session_id", "in", ids)]).to_pandas()
    logs = pq.read_table(SWE_LOGS, columns=["session_id", "session_metadata_raw"],
                         filters=[("session_id", "in", ids)]).to_pandas()
    md = dict(zip(logs.session_id.astype(str), logs.session_metadata_raw))
    rows = Counter(s.session_id.astype(str))
    out = {}
    for r in s.itertuples(index=False):
        sid = str(r.session_id)
        try:
            raw = json.loads(md.get(sid) or "{}")
        except (ValueError, TypeError):
            raw = {}
        tu = raw.get("token_usage") if isinstance(raw, dict) else None
        ent = {"has_tu": isinstance(tu, dict), "cli_version": r.cli_version if isinstance(r.cli_version, str) else None,
               "table_rows": int(rows[sid]), "tab": None, "raw": None}
        if isinstance(tu, dict):
            ent["tab"] = {k: TBL._i(getattr(r, c)) for k, c in TALLY_KEYS.items()}
            ent["raw"] = {k: TBL._i(tu.get(c)) for k, c in TALLY_KEYS.items()}
        out[sid] = ent
    return out


# ====================================================================================================== IR pass (swechat)
LIGHT = ["session_id", "seq", "kind", "ts", "call_id", "tool", "tool_raw", "model"]


def ir_pass_swechat(split, raw_res, cc_ids):
    """Chunked pass over the swechat split (cache sorted by session_id; range filters). Returns the R4 decision units of
    the Claude Code sessions, the per-session table (model, paired calls) of every Claude Code session, call ids by
    session over the whole split (for AC3 copied ids) and IR-side join counts."""
    ids_all = sorted(E.split_ids("swechat", split))
    cc = set(cc_ids)
    units, sess_rows = [], []
    call_sessions = defaultdict(set)
    raw_only = Counter()
    n_chunks = max(1, math.ceil(len(ids_all) / CHUNK))
    for ch in np.array_split(np.array(ids_all, dtype=object), n_chunks):
        if not len(ch):
            continue
        flt = [("session_id", ">=", str(ch[0])), ("session_id", "<=", str(ch[-1]))]
        lt = E.read_cache("swechat", split, LIGHT, filters=flt)
        cm = lt[(lt.kind == "call") & lt.call_id.notna()]
        for s, ci in zip(cm.session_id, cm.call_id.astype(str)):
            call_sessions[ci].add(s)
        lt = lt[lt.session_id.isin(cc)]
        if not len(lt):
            continue
        mm = E.session_model_map(lt)
        Lp = lt[lt.kind.isin(["call", "result"]) & lt.call_id.notna()]
        kc = set(zip(Lp.session_id[Lp.kind == "call"], Lp.call_id[Lp.kind == "call"].astype(str)))
        kr = set(zip(Lp.session_id[Lp.kind == "result"], Lp.call_id[Lp.kind == "result"].astype(str)))
        paired = Counter(s for s, _ in kc & kr)
        for s in sorted(set(lt.session_id)):
            sess_rows.append({"split": split, "session_id": s, "model": mm.get(s, "unknown"),
                              "paired_calls": int(paired.get(s, 0))})
        keys = set()
        for s in sorted(set(lt.session_id)):
            for cid in (raw_res.get(s, {}).get("numlines") or {}):
                keys.add((s, cid))
        if not keys:
            continue
        rs = E.read_cache("swechat", split, ["session_id", "seq", "kind", "call_id", "text", "extra"],
                          filters=flt + [("kind", "==", "result")])
        rs = rs[rs.session_id.isin(cc) & rs.call_id.notna()]
        rs = rs.assign(call_id=rs.call_id.astype(str))
        km = np.array([(s, c) in keys for s, c in zip(rs.session_id, rs.call_id)], dtype=bool)
        rs = rs[km].sort_values(["session_id", "seq"], kind="stable").drop_duplicates(["session_id", "call_id"])
        present = set(zip(rs.session_id, rs.call_id))
        for s, c in keys - present:
            raw_only[s] += 1
        # AC3: make_pairs on every call and result row of the decision keys (identical to the full-session pairing for
        # those keys), then join_clean_mask without the copied-id leg (added after all chunks)
        sub = Lp.assign(call_id=Lp.call_id.astype(str))
        sub = sub[[(s, c) in present for s, c in zip(sub.session_id, sub.call_id)]]
        P = pc.make_pairs(sub) if len(sub) and (sub.kind == "call").any() else pd.DataFrame()
        jc = {}
        if len(P):
            m0 = E.join_clean_mask(sub, P, frozenset())
            jc = dict(zip(zip(P.session_id, P.call_id.astype(str)), m0))
        tool_of = dict(zip(zip(sub.session_id[sub.kind == "call"], sub.call_id[sub.kind == "call"]),
                           zip(sub.tool[sub.kind == "call"].astype(object), sub.tool_raw[sub.kind == "call"].astype(object))))
        for s, c, t, ex in zip(rs.session_id, rs.call_id, rs.text.astype(object), rs.extra.astype(object)):
            t = t if isinstance(t, str) else ""
            nlv, L_raw, wl_raw, raw_len = raw_res[s]["numlines"][c]
            L_ir = sum(1 for ln in t.split("\n") if LINE_PREFIX.match(ln))
            wl_ir = E.dual_whitelisted(t, "swechat")
            tool, tool_raw = tool_of.get((s, c), (None, None))
            units.append({"split": split, "session_id": s, "call_id": c, "numLines": nlv, "L_ir": L_ir,
                          "wl_ir": wl_ir, "mismatch": L_ir != nlv, "flag": (L_ir != nlv) and wl_ir is None,
                          "L_raw": L_raw, "wl_raw": wl_raw, "flag_raw": (L_raw != nlv) and wl_raw is None,
                          "ir_len": len(t), "raw_len": raw_len,
                          "trunc": bool(E.truncated_result(t, ex if isinstance(ex, str) else None)),
                          "join_clean0": bool(jc.get((s, c), False)), "has_call": (s, c) in tool_of,
                          "tool_key": str(pc.tool_key("swechat/claude_code", tool if isinstance(tool, str) else None,
                                                      tool_raw if isinstance(tool_raw, str) else None)),
                          "tool_raw": tool_raw if isinstance(tool_raw, str) else None})
        del lt, rs, sub, P, Lp
        gc.collect()
    return pd.DataFrame(units), pd.DataFrame(sess_rows), call_sessions, raw_only


# ====================================================================================================== R4
def r4_whitelist_table(U, side):
    """Whitelist coverage among mismatches (side 'ir' or 'raw')."""
    if not len(U):
        return {"mismatches": 0}
    if side == "ir":
        mis = U[U.mismatch]
        cls = mis.wl_ir.fillna("UNEXPLAINED")
    else:
        mis = U[U.L_raw != U.numLines]
        cls = mis.wl_raw.fillna("UNEXPLAINED")
    out = {"units": int(len(U)), "mismatches": int(len(mis)), "mismatch_rate": wil(len(mis), len(U)),
           "by_class": dict(Counter(cls)), "mismatch_sessions": int(mis.session_id.nunique())}
    wl_all = (U.wl_ir if side == "ir" else U.wl_raw).map(_str_or_none)
    out["all_units_matching_a_whitelist_class"] = {
        "k": int(wl_all.notna().sum()), "by_class": dict(Counter(wl_all.dropna())),
        "note": "CONTEXT: units whose visible text matches a whitelist regex whether or not the counts differ (a "
                "mismatch on these is excused, so this is the share of decision units an editor could also excuse)"}
    return out


def _str_or_none(x):
    return x if isinstance(x, str) else None


def audit_r4(U, seed_parts, private):
    """AC1 for R4: numerator = flagged units (all of them if < 30). Each audited unit is compared with the raw
    transcript side read in the raw pass: visible numbered-line count (A6 _text_lines on the raw tool_result content vs
    the IR text), whitelist class, text length, and the call/result join (IR call row present). A unit 'changes its
    contribution' if its raw-side flag differs from its IR-side flag."""
    keys = list(zip(U.split, U.session_id, U.call_id))
    pick = E.audit_sample(keys, seed_parts=seed_parts)
    idx = U.set_index(["split", "session_id", "call_id"])
    rows, changed, field_diff = [], 0, Counter()
    for k in pick:
        r = idx.loc[k]
        diffs = []
        if int(r.L_ir) != int(r.L_raw):
            diffs.append("numbered_lines")
        if _str_or_none(r.wl_ir) != _str_or_none(r.wl_raw):
            diffs.append("whitelist_class")
        if int(r.ir_len) != int(r.raw_len):
            diffs.append("text_length")
        if not bool(r.has_call):
            diffs.append("no_ir_call_row")
        ch = bool(r.flag) != bool(r.flag_raw)
        changed += ch
        for d in diffs:
            field_diff[d] += 1
        if not private:
            rows.append({"split": k[0], "session_id": k[1], "call_id": k[2], "numLines": int(r.numLines),
                         "L_ir": int(r.L_ir), "L_raw": int(r.L_raw), "flag_ir": bool(r.flag),
                         "flag_raw": bool(r.flag_raw), "field_differences": diffs, "contribution_changed": ch})
    res = "FAIL" if changed >= E.AUDIT_FAIL else ("PARSER_NOTE" if changed == 1 else "PASS")
    return {"population": int(len(U)), "audited": len(pick), "contribution_changed": int(changed),
            "field_difference_counts": dict(field_diff), "result": res, "rows": rows if not private else None}


def r4_candidate(unit, U, S, n7c, n7meta, has_e, private, copied=None):
    """Verdict blocks, artifact checks, strata and survival for R4 on one unit. U: decision units with columns split,
    session_id, flag, trunc, join_clean, tool_key, ...; S: per-session table (split, session_id, model, repo, user,
    length)."""
    pooled_split = "E" if has_e else "B"
    cand = Candidate(f"R4/{unit}", U, n7c, pooled_split)
    splits = ("B", "E") if has_e else ("B",)
    Us = {sp: U[U.split == sp] for sp in splits}
    verdict = {sp: cand.block(Us[sp], sp) for sp in splits}
    if has_e:
        verdict["BuE"] = cand.block(U, "pooled")
    ref = verdict["BuE" if has_e else "B"]["label"]
    ac = {}
    # AC1 parser
    flagged = U[U.flag]
    ac["AC1_parser"] = audit_r4(flagged, ("audit", ITEM, "R4", unit), private)
    ac["AC1_parser"]["note"] = "numerator = flagged units (prereg AC1: all of them if < 30)"
    ac["AC1_supplementary_decision_units"] = audit_r4(U[~U.flag], ("audit", ITEM, "R4den", unit), private)
    ac["AC1_supplementary_decision_units"]["note"] = (
        "DEVIATION (see deviations): the numerator has < 30 events, so 30 unflagged decision units are audited with "
        "the same fail rule; a FAIL here is applied like an AC1 FAIL")
    ac["AC1_full_population_parity"] = {
        "units": int(len(U)), "flag_ir": int(U.flag.sum()), "flag_raw": int(U.flag_raw.sum()),
        "flag_differs": int((U.flag != U.flag_raw).sum()),
        "numbered_lines_differ": int((U.L_ir != U.L_raw).sum()),
        "text_length_differs": int((U.ir_len != U.raw_len).sum()),
        "whitelist_class_differs": int((U.wl_ir.fillna("") != U.wl_raw.fillna("")).sum()),
        "no_ir_call_row": int((~U.has_call).sum()),
        "note": "CONTEXT: every decision unit, IR text vs raw tool_result text (no verdict effect beyond AC1)"}
    ac1_fail = ac["AC1_parser"]["result"] == "FAIL" or ac["AC1_supplementary_decision_units"]["result"] == "FAIL"
    # AC2 / AC3
    a2 = U[~U.trunc]
    a3 = U[U.join_clean]
    ac["AC2_truncation"] = {"units_dropped": int(U.trunc.sum()), "label": cand.label(a2)[0],
                            "rate": rate_block(a2)["session_rate"]}
    ac["AC3_join"] = {"units_dropped": int((~U.join_clean).sum()), "label": cand.label(a3)[0],
                      "rate": rate_block(a3)["session_rate"],
                      "copied_call_ids_considered": copied}
    smap = S.set_index("session_id")
    cmaps = {"repo": smap.repo.to_dict(), "model": smap.model.to_dict()}
    if "user" in smap:
        cmaps["user"] = smap.user.to_dict()
    ac["AC4_dominance"] = ac4(cand, U, cmaps, private=private)
    if has_e:
        ac["AC5_sampling"] = ac5(cand, U, Us)
    else:
        ac["AC5_sampling"] = {"result": "NOT_RUN", "why": "no population table for this corpus (prereg AC5)"}
    axes = {"tool (tool_key)": ("unit", "tool_key"), "model (session modal)": ("session", smap.model.to_dict()),
            "repo": ("session", smap.repo.to_dict()), "length tercile (unit A cuts)": ("session", smap.length.to_dict())}
    strata = strata_block(cand, U, axes, private=private)
    confined = sorted(a for a, v in strata.items() if v["confinement"] == "CONFINED")
    checks_raw = []
    if ac1_fail:
        checks_raw.append(("AC1_parser_FAIL", "FAIL", "downgrade"))
    checks_raw.append(("AC2_truncation", ac["AC2_truncation"]["label"], "min"))
    checks_raw.append(("AC3_join", ac["AC3_join"]["label"], "min"))
    if ac["AC4_dominance"]["effect"] != "pass":
        checks_raw.append(("AC4_" + ac["AC4_dominance"]["result"], ac["AC4_dominance"]["result"],
                           ac["AC4_dominance"]["effect"]))
    if has_e:
        checks_raw.append(("AC5_sampling", ac["AC5_sampling"]["label"], "min"))
    if confined:
        checks_raw.append(("CONFINED:" + ",".join(confined), "CONFINED", "downgrade"))
    surv = assemble_survival(verdict["E"]["label"] if has_e else None, ref, checks_raw, has_e=has_e,
                             e_seen=has_e)
    return cand, verdict, ac, strata, confined, surv


def run_r4(raw_res, ir, n7, args):
    t = time.time()
    out = {}
    # ---------------------------------------------------------------- swechat/claude_code (B, E)
    unit = "swechat/claude_code"
    U = pd.concat([ir[sp]["units"] for sp in SPLITS], ignore_index=True)
    S = pd.concat([ir[sp]["sess"] for sp in SPLITS], ignore_index=True)
    call_sessions = defaultdict(set)
    for sp in SPLITS:
        for c, ss in ir[sp]["call_sessions"].items():
            call_sessions[c] |= ss
    copied = {c for c, ss in call_sessions.items() if len(ss) > 1}
    U["copied"] = U.call_id.isin(copied)
    U["join_clean"] = U.join_clean0 & ~U.copied
    meta = E.swechat_session_meta(S.session_id.tolist())
    rmap = {s: (v if isinstance(v, str) and v not in ("", "nan", "None") else "unknown")
            for s, v in zip(meta.session_id.astype(str), meta.repo_id)}
    umap = {s: (v if isinstance(v, str) and v not in ("", "nan", "None") else "unknown")
            for s, v in zip(meta.session_id.astype(str), meta.user_id)}
    S["repo"] = S.session_id.map(lambda s: rmap.get(s, "unknown"))
    S["user"] = S.session_id.map(lambda s: umap.get(s, "unknown"))
    cuts = CUTS[unit]["cuts"]
    S["length"] = ["short" if n <= cuts[0] else "mid" if n <= cuts[1] else "long" for n in S.paired_calls]
    n7c, n7meta = n7["R4"][unit]
    cand, verdict, ac, strata, confined, surv = r4_candidate(unit, U, S, n7c, n7meta, has_e=True, private=False,
                                                             copied=len(copied))
    raw_cov = {}
    for sp in SPLITS:
        ids = ir[sp]["cc_ids"]
        with_raw = [s for s in ids if raw_res.get(s, {}).get("exists")]
        nl_sess = [s for s in ids if raw_res.get(s, {}).get("numlines")]
        n_counters = sum(len(raw_res[s]["numlines"]) for s in nl_sess)
        st = Counter()
        for s in nl_sess:
            st.update(raw_res[s].get("r4_raw_stats") or {})
        Usp = U[U.split == sp]
        raw_cov[sp] = {"sessions": len(ids), "sessions_with_transcript": len(with_raw),
                       "sessions_with_numLines": len(nl_sess), "raw_numLines_counters": int(n_counters),
                       "counters_joined_to_ir_result": int(len(Usp)),
                       "counters_without_ir_result": int(sum(ir[sp]["raw_only"].values())),
                       "sessions_deciding": int(Usp.session_id.nunique()), "raw_parse_stats": dict(st)}
    flagged = U[U.flag]
    out[unit] = {
        "candidate": cand.name, "label_suffix": "(E not blind)",
        "raw_join_coverage": raw_cov,
        "whitelist_coverage_ir": {sp: r4_whitelist_table(U[U.split == sp], "ir") for sp in SPLITS},
        "whitelist_coverage_ir_BuE": r4_whitelist_table(U, "ir"),
        "whitelist_coverage_raw_BuE": r4_whitelist_table(U, "raw"),
        "unexplained_mismatch_diff_L_minus_numLines": dict(Counter((flagged.L_ir - flagged.numLines).astype(int)))
        if len(flagged) else {},
        "decision_unit_tools": dict(Counter(U.tool_raw.fillna("<no call row>"))),
        "n7_cells": {sp: dict(sorted(c.items())) for sp, c in n7c.items()}, "n7_meta": n7meta,
        "n7_part": {sp: {"label": cand.n7[sp][0], **cand.n7[sp][1]} for sp in cand.n7},
        "verdict_blocks": verdict, "artifact_checks": ac, "stratification": strata, "confined_axes": confined,
        "survival": surv,
        "flagged_units": [{"split": r.split, "session_id": r.session_id, "call_id": r.call_id,
                           "numLines": int(r.numLines), "L_ir": int(r.L_ir), "L_raw": int(r.L_raw),
                           "flag_raw": bool(r.flag_raw), "trunc": bool(r.trunc), "join_clean": bool(r.join_clean)}
                          for r in flagged.itertuples()],
    }
    log(f"R4 {unit}: units {len(U)}, flagged {int(U.flag.sum())}; E {verdict['E']['label']}; "
        f"survival {surv['status']}")
    # ---------------------------------------------------------------- cc_local (B only, private, aggregates only)
    unit = "cc_local"
    Uc, Sc, cov_c = cc_local_r4(args)
    n7c, n7meta = n7["R4"][unit]
    cand, verdict, ac, strata, confined, surv = r4_candidate(unit, Uc, Sc, n7c, n7meta, has_e=False, private=True,
                                                             copied=cov_c.pop("copied_call_ids"))
    out[unit] = {
        "candidate": cand.name, "label_suffix": "(B only, unreplicated); private: aggregates only",
        "raw_join_coverage": {"B": cov_c},
        "whitelist_coverage_ir": {"B": r4_whitelist_table(Uc, "ir")},
        "whitelist_coverage_raw": {"B": r4_whitelist_table(Uc, "raw")},
        "n7_cells": {sp: dict(sorted(c.items())) for sp, c in n7c.items()},
        "n7_meta": n7meta,
        "n7_part": {sp: {"label": cand.n7[sp][0], **cand.n7[sp][1]} for sp in cand.n7},
        "verdict_blocks": verdict, "artifact_checks": ac, "stratification": strata, "confined_axes": confined,
        "survival": surv,
        "flagged_units_count": int(Uc.flag.sum()) if len(Uc) else 0,
    }
    log(f"R4 cc_local: units {len(Uc)}, flagged {int(Uc.flag.sum()) if len(Uc) else 0}; B {verdict['B']['label']}; "
        f"survival {surv['status']}")
    return {"units": out, "runtime_s": round(time.time() - t, 1)}


def cc_local_r4(args):
    """cc_local split B: raw numLines from the frozen snapshot (main + subagent files of B ids; in-process) joined to the
    IR results. Returns (U, S, coverage) with no ids, text, paths or names leaving this function except inside U/S,
    which are reduced to aggregates by the caller (strata/cluster names anonymised)."""
    from analysis.loaders import load_cc_local as LCC
    assert Path(LCC.ROOT).resolve() == CC_LOCAL_ROOT.resolve(), "cc_local raw source must be the frozen snapshot"
    ids = sorted(str(s) for s in E.split_ids("cc_local", "B"))
    files = {x["sid"]: x["files"] for x in LCC.discover() if x["sid"] in set(ids)}
    u = E.read_cache("cc_local", "B", ["session_id", "seq", "kind", "ts", "call_id", "tool", "tool_raw", "model",
                                       "stratum"])
    rs = E.read_cache("cc_local", "B", ["session_id", "seq", "kind", "call_id", "text", "extra"],
                      filters=[("kind", "==", "result")])
    raw_nl, raw_stats = {}, Counter()
    for s in ids:
        if s not in files:
            continue
        nl, st = r4_raw_numlines([str(CC_LOCAL_ROOT / rel) for _, rel in files[s]], "cc_local")
        raw_nl[s] = nl
        raw_stats.update(st)
    mm = E.session_model_map(u)
    Lp = u[u.kind.isin(["call", "result"]) & u.call_id.notna()].assign(call_id=lambda d: d.call_id.astype(str))
    kc = set(zip(Lp.session_id[Lp.kind == "call"], Lp.call_id[Lp.kind == "call"]))
    kr = set(zip(Lp.session_id[Lp.kind == "result"], Lp.call_id[Lp.kind == "result"]))
    paired = Counter(s for s, _ in kc & kr)
    call_sessions = defaultdict(set)
    for s, c in kc:
        call_sessions[c].add(s)
    copied = {c for c, ss in call_sessions.items() if len(ss) > 1}
    keys = {(s, c) for s, nl in raw_nl.items() for c in nl}
    rs = rs.assign(call_id=rs.call_id.astype(str))
    rs = rs[[(s, c) in keys for s, c in zip(rs.session_id, rs.call_id)]]
    rs = rs.sort_values(["session_id", "seq"], kind="stable").drop_duplicates(["session_id", "call_id"])
    present = set(zip(rs.session_id, rs.call_id))
    sub = Lp[[(s, c) in present for s, c in zip(Lp.session_id, Lp.call_id)]]
    P = pc.make_pairs(sub) if len(sub) and (sub.kind == "call").any() else pd.DataFrame()
    jc = dict(zip(zip(P.session_id, P.call_id.astype(str)), E.join_clean_mask(sub, P, copied))) if len(P) else {}
    tool_of = dict(zip(zip(sub.session_id[sub.kind == "call"], sub.call_id[sub.kind == "call"]),
                       zip(sub.tool[sub.kind == "call"].astype(object), sub.tool_raw[sub.kind == "call"].astype(object))))
    units = []
    for s, c, t, ex in zip(rs.session_id, rs.call_id, rs.text.astype(object), rs.extra.astype(object)):
        t = t if isinstance(t, str) else ""
        nlv, L_raw, wl_raw, raw_len = raw_nl[s][c]
        L_ir = sum(1 for ln in t.split("\n") if LINE_PREFIX.match(ln))
        wl_ir = E.dual_whitelisted(t, "cc_local")
        tool, tool_raw = tool_of.get((s, c), (None, None))
        k = pc.tool_key("cc_local", tool if isinstance(tool, str) else None, tool_raw if isinstance(tool_raw, str) else None)
        units.append({"split": "B", "session_id": s, "call_id": c, "numLines": nlv, "L_ir": L_ir, "wl_ir": wl_ir,
                      "mismatch": L_ir != nlv, "flag": (L_ir != nlv) and wl_ir is None, "L_raw": L_raw,
                      "wl_raw": wl_raw, "flag_raw": (L_raw != nlv) and wl_raw is None, "ir_len": len(t),
                      "raw_len": raw_len, "trunc": bool(E.truncated_result(t, ex if isinstance(ex, str) else None)),
                      "join_clean": bool(jc.get((s, c), False)), "has_call": (s, c) in tool_of,
                      "tool_key": str(pc.private_key(k)), "tool_raw": None})
    U = pd.DataFrame(units)
    st_map = u.groupby("session_id").stratum.first().astype(object).to_dict()
    S = pd.DataFrame({"session_id": sorted(set(u.session_id))})
    S["split"] = "B"
    S["model"] = S.session_id.map(lambda s: mm.get(s, "unknown"))
    S["repo"] = S.session_id.map(lambda s: str(st_map.get(s, "unknown")))
    S["paired_calls"] = S.session_id.map(lambda s: int(paired.get(s, 0)))
    cuts = CUTS["cc_local"]["cuts"]
    S["length"] = ["short" if n <= cuts[0] else "mid" if n <= cuts[1] else "long" for n in S.paired_calls]
    cov = {"sessions": len(ids), "sessions_with_snapshot_files": len(files),
           "sessions_with_numLines": sum(1 for nl in raw_nl.values() if nl),
           "raw_numLines_counters": int(sum(len(nl) for nl in raw_nl.values())),
           "counters_joined_to_ir_result": int(len(U)),
           "counters_without_ir_result": int(len(keys - present)),
           "sessions_deciding": int(U.session_id.nunique()) if len(U) else 0, "raw_parse_stats": dict(raw_stats),
           "copied_call_ids": len(copied)}
    del u, rs, Lp, sub
    gc.collect()
    return U, S, cov


# ====================================================================================================== R5
def indep_claude_recount(path):
    """AC1 independent parser (written for the audit, shares no code with phase_c_swechat_tables): per distinct
    assistant message.id in first-occurrence order, the usage of its LAST record; ids missing -> one per record."""
    order, last = [], {}
    k = -1
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            s = raw.strip()
            if not s:
                continue
            k += 1
            try:
                d = json.loads(s)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("type") != "assistant":
                continue
            m = d.get("message")
            if not isinstance(m, dict):
                continue
            mid = m.get("id") or ("noid", k)
            u = m.get("usage") if isinstance(m.get("usage"), dict) else {}

            def g(x):
                try:
                    return int(u.get(x) or 0)
                except (TypeError, ValueError):
                    return 0
            if mid not in last:
                order.append(mid)
            last[mid] = (g("input_tokens"), g("cache_creation_input_tokens"), g("cache_read_input_tokens"),
                         g("output_tokens"))
    return [last[m] for m in order]


def indep_match(seq, tally):
    """full / prefix / window / none with plain loops (independent of phase_c_swechat_tables._match)."""
    api = tally["api"]
    tok = (tally["in"], tally["cc"], tally["cr"], tally["out"])
    n = len(seq)
    if api > n:
        return "none"

    def tot(a, b):
        return tuple(sum(x[j] for x in seq[a:b]) for j in range(4))
    if api == n and tot(0, n) == tok:
        return "full"
    if tot(0, api) == tok:
        return "prefix"
    for st in range(0, n - api + 1):
        if tot(st, st + api) == tok:
            return "window"
    return "none"


def audit_r5(U, tallies, seed_parts):
    """AC1 for R5 (Claude Code format): numerator = flagged sessions (all if < 30). Each is re-read from the raw sources
    by independent code: the transcript recount (indep_claude_recount + indep_match) and the tally re-read from
    sessions.parquet and session_logs. Contribution changed if the independent flag differs."""
    keys = list(zip(U.split, U.session_id))
    pick = E.audit_sample(keys, seed_parts=seed_parts)
    ids = sorted({s for _, s in pick})
    fresh = load_tallies(ids) if ids else {}
    idx = U.set_index(["split", "session_id"])
    rows, changed, field = [], 0, Counter()
    for sp, s in pick:
        r = idx.loc[(sp, s)]
        ft = fresh.get(s, {})
        tab_same = ft.get("tab") == tallies[s]["tab"]
        seq = indep_claude_recount(str(DATA_SWE / "transcripts" / f"{s}.jsonl"))
        cls_i = indep_match(seq, ft["tab"]) if ft.get("tab") else None
        flag_i = cls_i == "none"
        ch = flag_i != bool(r.flag)
        changed += ch
        diffs = []
        if not tab_same:
            diffs.append("tally_reread_differs")
        if cls_i != r.cls:
            diffs.append("class_differs")
        if len(seq) != (r.n_msgs if r.n_msgs == r.n_msgs else -1):
            diffs.append("message_count_differs")
        for d in diffs:
            field[d] += 1
        rows.append({"split": sp, "session_id": s, "cls_primary": r.cls, "cls_independent": cls_i,
                     "n_msgs_primary": None if r.n_msgs != r.n_msgs else int(r.n_msgs), "n_msgs_independent": len(seq),
                     "tally_api": tallies[s]["tab"]["api"], "field_differences": diffs, "contribution_changed": ch})
    res = "FAIL" if changed >= E.AUDIT_FAIL else ("PARSER_NOTE" if changed == 1 else "PASS")
    return {"population": int(len(U)), "audited": len(pick), "contribution_changed": int(changed),
            "field_difference_counts": dict(field), "result": res, "rows": rows}


def r5_units(raw_res, tallies, ids_by_split):
    """Per-session R5 decision table over every swechat B / E session of the four recount formats."""
    rows = []
    gate = Counter()
    for sp in SPLITS:
        for s in ids_by_split[sp]:
            fmt = FM.get(s)
            if fmt not in R5_FMT:
                gate[(sp, str(fmt), "format_without_recount")] += 1
                continue
            t = tallies.get(s)
            if t is None:
                gate[(sp, fmt, "no_sessions_row")] += 1
                continue
            if not t["has_tu"]:
                gate[(sp, fmt, "no_token_usage_in_session_logs")] += 1
                continue
            if t["tab"]["api"] == 0:
                gate[(sp, fmt, "api_call_count_zero")] += 1
                continue
            r = raw_res.get(s, {})
            if not r.get("exists"):
                gate[(sp, fmt, "no_transcript")] += 1
                continue
            scan_fmt, pre, bad = R5_FMT[fmt]
            if r.get("fmt_scan") != scan_fmt or r.get("cls") is None:
                gate[(sp, fmt, f"scan_format_{r.get('fmt_scan')}")] += 1
                continue
            gate[(sp, fmt, "decided")] += 1
            cls_raw = r.get("cls_rawmeta", r["cls"])
            rows.append({"split": sp, "session_id": s, "unit": f"swechat/{fmt}", "cls": r["cls"],
                         "flag": r["cls"] in bad, "cls_rawmeta": cls_raw, "flag_rawmeta": cls_raw in bad,
                         "tab_eq_raw": t["tab"] == t["raw"], "table_rows": t["table_rows"],
                         "file_sessionId_present": r.get("file_sessionId_present"),
                         "cls_noout": r.get("cls_noout"), "n_msgs": r.get("n_msgs"),
                         "cli_version": t["cli_version"], "api": t["tab"]["api"],
                         "scan_error": r.get("scan_error")})
    return pd.DataFrame(rows), {f"{a}|{b}|{c}": n for (a, b, c), n in sorted(gate.items())}


def r5_descriptive(U):
    if not len(U):
        return {}
    f = U.flag
    out = {"class_counts": dict(Counter(U.cls)),
           "unmatched_output_only_share": wil(int((f & U.cls_noout.isin(["full", "prefix", "window"])).sum()),
                                              int(f.sum())) if f.sum() else None,
           "by_cli_version_minor": {}}
    mv = U.cli_version.fillna("unknown").map(lambda v: ".".join(v.split(".")[:2]) if v != "unknown" else v)
    for v, g in U.groupby(mv):
        out["by_cli_version_minor"][v] = wil(int(g.flag.sum()), int(len(g)))
    out["tab_ne_raw_sessions"] = int((~U.tab_eq_raw).sum())
    out["flag_among_tab_ne_raw"] = wil(int(U.flag[~U.tab_eq_raw].sum()), int((~U.tab_eq_raw).sum()))
    out["duplicate_sessions_rows"] = int((U.table_rows > 1).sum())
    out["scan_errors"] = int(U.scan_error.notna().sum())
    return out


def run_r5(raw_res, tallies, ids_by_split, ir, n7):
    t = time.time()
    U5, gate = r5_units(raw_res, tallies, ids_by_split)
    out = {"gate_counts": gate, "units": {}}
    # pooled swechat (descriptive; no verdict: N7 cells exist per unit)
    pooled = {}
    for sp in ("B", "E", "BuE"):
        g = U5 if sp == "BuE" else U5[U5.split == sp]
        pooled[sp] = {"primary_sessions_parquet_tally": rate_block(g.assign(flag=g.flag))["session_rate"],
                      "join_fix_session_logs_tally": rate_block(g.assign(flag=g.flag_rawmeta))["session_rate"]}
    out["pooled_swechat_four_formats_descriptive"] = pooled
    for unit in R5_UNITS:
        U = U5[U5.unit == unit].reset_index(drop=True)
        fmt = unit.split("/", 1)[1]
        n7c, n7meta = n7["R5"].get(unit, ({}, {}))
        cand = Candidate(f"R5/{unit}", U, n7c, "E")
        verdict = {sp: cand.block(U[U.split == sp], sp) for sp in SPLITS}
        verdict["BuE"] = cand.block(U, "pooled")
        ref = verdict["BuE"]["label"]
        ent = {"candidate": cand.name, "label_suffix": "(E not blind)",
               "descriptive": {sp: r5_descriptive(U[U.split == sp]) for sp in SPLITS} | {"BuE": r5_descriptive(U)},
               "join_fix_variant": {sp: rate_block((U if sp == "BuE" else U[U.split == sp]).assign(
                   flag=lambda d: d.flag_rawmeta))["session_rate"] for sp in ("B", "E", "BuE")},
               "join_fix_variant_note": "session_logs token_usage as the tally (Phase C T3 join fix); reported beside "
                                        "the pre-registered sessions.parquet tally, not a verdict",
               "n7_cells": {sp: dict(sorted(c.items())) for sp, c in n7c.items()}, "n7_meta": n7meta,
               "n7_part": {sp: {"label": cand.n7[sp][0], **cand.n7[sp][1]} for sp in cand.n7},
               "verdict_blocks": verdict}
        has_level = verdict["E"]["label"] in LEVEL or ref in LEVEL
        if fmt == "claude_code" and has_level and len(U):
            S = pd.concat([ir[sp]["sess"] for sp in SPLITS], ignore_index=True).set_index("session_id")
            meta = E.swechat_session_meta(U.session_id.tolist())
            rmap = {s: (v if isinstance(v, str) and v not in ("", "nan", "None") else "unknown")
                    for s, v in zip(meta.session_id.astype(str), meta.repo_id)}
            umap = {s: (v if isinstance(v, str) and v not in ("", "nan", "None") else "unknown")
                    for s, v in zip(meta.session_id.astype(str), meta.user_id)}
            cuts = CUTS[unit]["cuts"]
            model = {s: (S.model.get(s, "unknown") if s in S.index else "unknown") for s in U.session_id}
            length = {s: ("short" if n <= cuts[0] else "mid" if n <= cuts[1] else "long")
                      for s, n in ((s, int(S.paired_calls.get(s, 0)) if s in S.index else 0) for s in U.session_id)}
            ac = {}
            ac["AC1_parser"] = audit_r5(U[U.flag], tallies, ("audit", ITEM, "R5", unit))
            ac["AC1_parser"]["note"] = "numerator = flagged sessions (prereg AC1: all of them if < 30)"
            ac["AC2_truncation"] = {"result": "NOT_APPLICABLE", "effect": "pass",
                                    "why": "R5 reads no tool-result text: the A3 truncation catalogue has no event in "
                                           "the statistic"}
            a3 = U[U.tab_eq_raw & (U.table_rows == 1) & (U.file_sessionId_present.fillna(False).astype(bool))]
            ac["AC3_join"] = {"sessions_dropped": int(len(U) - len(a3)), "label": cand.label(a3)[0],
                              "rate": rate_block(a3)["session_rate"],
                              "definition": "sessions whose sessions.parquet tally equals the session_logs token_usage "
                                            "tally, whose session id has one sessions.parquet row, and whose transcript "
                                            "records carry the session's own sessionId (DEVIATION: session-level join)"}
            ac["AC4_dominance"] = ac4(cand, U, {"repo": rmap, "user": umap, "model": model})
            ac["AC5_sampling"] = ac5(cand, U, {"B": U[U.split == "B"], "E": U[U.split == "E"]})
            axes = {"model (session modal)": ("session", model), "repo": ("session", rmap),
                    "length tercile (unit A cuts)": ("session", length)}
            strata = strata_block(cand, U, axes)
            strata["tool (tool_key)"] = {"confinement": "NOT_APPLICABLE",
                                         "why": "session-level statistic over the whole transcript; no tool stratum"}
            confined = sorted(a for a, v in strata.items() if v.get("confinement") == "CONFINED")
            checks_raw = []
            if ac["AC1_parser"]["result"] == "FAIL":
                checks_raw.append(("AC1_parser_FAIL", "FAIL", "downgrade"))
            checks_raw.append(("AC3_join", ac["AC3_join"]["label"], "min"))
            if ac["AC4_dominance"]["effect"] != "pass":
                checks_raw.append(("AC4_" + ac["AC4_dominance"]["result"], ac["AC4_dominance"]["result"],
                                   ac["AC4_dominance"]["effect"]))
            checks_raw.append(("AC5_sampling", ac["AC5_sampling"]["label"], "min"))
            if confined:
                checks_raw.append(("CONFINED:" + ",".join(confined), "CONFINED", "downgrade"))
            surv = assemble_survival(verdict["E"]["label"], ref, checks_raw, has_e=True, e_seen=True)
            ent.update({"artifact_checks": ac, "stratification": strata, "confined_axes": confined, "survival": surv})
        else:
            why = ("no N7 R5_LEDGER cells for this unit (N7 content item ran the recount for the Claude Code format "
                   "only)" if not n7c else "no level")
            surv = assemble_survival(verdict["E"]["label"], ref, [], has_e=True, e_seen=True)
            surv["artifact_checks_not_run"] = (f"verdict is {verdict['E']['label']} / {ref}: {why}; a check can only "
                                               "lower a label, so none is run on a NOT_RUN / INSUFFICIENT_N / DEAD cell")
            ent["survival"] = surv
        ent["flagged_sessions"] = [{"split": r.split, "session_id": r.session_id, "cls": r.cls,
                                    "cls_noout": r.cls_noout, "cli_version": r.cli_version,
                                    "tab_eq_raw": bool(r.tab_eq_raw), "cls_rawmeta": r.cls_rawmeta}
                                   for r in U[U.flag].itertuples()]
        out["units"][unit] = ent
        log(f"R5 {unit}: decided {len(U)}, flagged {int(U.flag.sum()) if len(U) else 0}; E {verdict['E']['label']}; "
            f"survival {ent['survival']['status']}")
    out["runtime_s"] = round(time.time() - t, 1)
    return out


# ====================================================================================================== deviations
DEVIATIONS = [
    {"item": "output file names",
     "prereg_said": "outputs.A1: phase_e_a1_<candidate>.py -> a1_<candidate>.json",
     "what_you_did": "analysis/probes/phase_e_r4_r5.py -> analysis/out/phase_e/r4_r5.json (R4 and R5 in one file)",
     "why": "the orchestrator assigned the item key r4_r5 for both proposals",
     "effect_on_verdict": "none"},
    {"item": "N7 legs read, not recomputed",
     "prereg_said": "a1.proposal_rules: the verdict needs the N7 recall cells of the proposal's detector",
     "what_you_did": "R4_DUAL / R5_LEDGER cells are read from analysis/out/phase_e/n7_content_shards/<unit>_<split>.json "
                     "(the N7 content item, run concurrently); a missing shard leaves that split's N7 leg NOT_RUN. The "
                     "shard's honest_population for the detector is copied beside this item's honest rate as a "
                     "consistency check (n7_meta.<split>.honest_population)",
     "why": "one N7 implementation per detector; re-running the battery here would duplicate it",
     "effect_on_verdict": "a split whose shard is absent gets NOT_RUN, never a null"},
    {"item": "denominator of the session-level honest flag rate",
     "prereg_said": "a1.proposal_rules: 'session-level honest flag rate' (denominator not spelled out)",
     "what_you_did": "flagged sessions / sessions in which the detector decides >= 1 unit (R4: >= 1 result with a raw "
                     "numLines joined to an IR result; R5: a session with a tally, api_call_count > 0 and a recount of "
                     "its format), Wilson CI",
     "why": "a session in which the detector decides nothing cannot be a false positive (same choice as the R2/R3 item)",
     "effect_on_verdict": "conservative (can only raise the rate relative to the all-session denominator)"},
    {"item": "R4 AC1 when the numerator is (nearly) empty",
     "prereg_said": "AC1: 30 events from the statistic's numerator or flagged set; if the numerator has < 30 events, "
                    "all of them",
     "what_you_did": "the flagged units are audited as written (possibly 0); in addition 30 unflagged decision units are "
                     "audited with the same fields and the same fail rule (>= 2 contribution changes), and a FAIL there "
                     "is applied like an AC1 FAIL; every decision unit's IR-vs-raw parity is reported as context",
     "why": "with 0 flagged units the literal AC1 audits nothing; the decision units are the only events whose parsing "
            "can be wrong",
     "effect_on_verdict": "can only lower the label (one level) if the supplementary audit FAILs"},
    {"item": "R5 AC2 truncation",
     "prereg_said": "AC2: recompute without results matching truncated_result()",
     "what_you_did": "not applicable: R5 reads usage records and the tally, no tool-result text",
     "why": "the statistic has no result event to drop",
     "effect_on_verdict": "none"},
    {"item": "R5 AC3 join",
     "prereg_said": "AC3: recompute on call/result pairs passing join_clean_mask()",
     "what_you_did": "R5 is session-level and joins a session's transcript to its tally; AC3 recomputes on sessions whose "
                     "sessions.parquet tally equals the session_logs token_usage tally (the Phase C T3 join artifact), "
                     "whose id has one sessions.parquet row and whose transcript records carry the session's own "
                     "sessionId",
     "why": "smallest faithful analogue of 'clean join' for a session-level detector",
     "effect_on_verdict": "lower label if the label changes (min_check)"},
    {"item": "R5 tally variant",
     "prereg_said": "R5_specific: 'Entire 5-integer tally (sessions.parquet input/output/cache tokens and "
                    "api_call_count)'; Phase C context '33/5,701 after the join fix'",
     "what_you_did": "the verdict uses the sessions.parquet tally as written; the session_logs (join-fix) tally is "
                     "reported beside it as join_fix_variant, not a verdict",
     "why": "the JSON names sessions.parquet; choosing the variant after seeing both would be a post-hoc choice",
     "effect_on_verdict": "none (the variant is descriptive)"},
    {"item": "R5 units without N7 cells",
     "prereg_said": "R5: ledger over swechat (formats not restricted); verdict needs N7 recall cells",
     "what_you_did": "the honest rate is measured for swechat claude_code, codex, opencode and gemini with the committed "
                     "Phase C recount (F0/X0/O0/G0); the N7 content item computed R5_LEDGER cells for claude_code only, "
                     "so the other three get NOT_RUN unless their honest rate alone makes them DEAD (> 0.20)",
     "why": "the verdict rule needs both legs; DEAD on the honest rate needs no N7 leg",
     "effect_on_verdict": "codex / opencode / gemini: NOT_RUN or DEAD"},
    {"item": "survival base for Phase D proposals",
     "prereg_said": "survival_status(): 'E >= Phase B'; R1-R5 have no Phase B verdict ('untested')",
     "what_you_did": "units with E start from the E label (base None, as the R2/R3 item); cc_local (no E) starts from the "
                     "B label with has_e=False ('B only, unreplicated'); the B u E label is the reference for the "
                     "min-type checks",
     "why": "survival_status() returns NOT_RUN for a no-E unit whose base is not a level",
     "effect_on_verdict": "cc_local R4 gets a B-only status instead of NOT_RUN"},
    {"item": "AC1 FAIL effect, AC4 weights, confinement aggregation, WEAK rule split",
     "prereg_said": "AC1 FAIL (effect unnamed); AC4 on 'denominator events or contributing sessions'; confinement costs "
                    "one level; ALIVE needs DETECTS 'in N7 on E (B for units without E)'",
     "what_you_did": "as the sibling A1 items: AC1 FAIL = one-level downgrade; AC4 denominator events = decided sessions "
                     "(unit-weighted shares as context); confinement on any number of axes = one downgrade; the E and "
                     "B u E verdicts read the E cells, the B verdict reads the B cells (cc_local: B cells)",
     "why": "same mechanics as phase_e_a1_p1_p3 / phase_e_r2_r3",
     "effect_on_verdict": "none unless those checks fire"},
    {"item": "R4 cc_local raw files",
     "prereg_said": "cc_local raw fields from the frozen snapshot data/claude-code-local for split B session ids",
     "what_you_did": "the loader's discover() lists the snapshot's session files (directory listing); only the main and "
                     "subagent files of split B ids are opened; numLines read from top-level entries of every file of "
                     "the session (first occurrence per tool_use_id)",
     "why": "subagent Read results live in their own files in current Claude Code",
     "effect_on_verdict": "none"},
]

IMPLEMENTATION = {
    "R4_raw_join": "top-level entry with toolUseResult (key 'toolUseResult') whose file.numLines is an int and whose "
                   "message.content holds a tool_result block (the first one); key = that block's tool_use_id; first "
                   "occurrence wins (duplicates counted in raw_parse_stats). Lines containing the token '\"numLines\"' "
                   "are the only ones parsed (prefilter, cannot drop a qualifying entry)",
    "R4_visible": "IR result rows (kind result, call_id = tool_use_id), first by seq per (session, call_id); visible "
                  "count on the IR text; raw-side count on the raw tool_result content (A6 _text_lines) for parity",
    "R4_AC3": "join_clean_mask() on make_pairs() of every call and result row of the decision keys (light columns), "
              "plus 'call_id not present in another session' over every swechat B and E call id (cc_local: B)",
    "R5_recount": "phase_c_swechat_tables.scan_one((sid, path, meta)) with meta = the 5-integer tally (files []): F0 "
                  "(Claude Code: distinct assistant message.id, last record's usage), X0 (Codex token_count events), "
                  "O0 (OpenCode assistant tokens), G0 (Gemini CLI messages); class full/prefix/window (Codex: "
                  "full/prefix/tokens_at_other_k); where sessions.parquet and session_logs tallies differ the scan is "
                  "repeated with the session_logs tally (join_fix_variant)",
    "R5_gate": "a tally exists iff session_logs.session_metadata_raw carries a token_usage dict (Phase C _meta_for_tx); "
               "decided iff api_call_count > 0, the transcript exists and scan_one sniffs the expected format",
    "length_tercile": "paired calls per session = (session, call_id) keys present among IR calls and IR results; cut "
                      "points = resolved.length_terciles_A of the unit",
    "model": "prereg_e_common.session_model_map() over the IR rows of the session",
}


# ====================================================================================================== main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=None, help="development runs only: write somewhere other than the official path")
    a = ap.parse_args(argv)
    out_path = Path(a.out) if a.out else OUT
    out = {"item": ITEM, "generated_by": "analysis/probes/phase_e_r4_r5.py",
           "prereg_e_json_sha256": E.sha256_file(E.PREREG_E_JSON),
           "spec_module_sha256_lf": E.sha256_lf(Path(E.__file__)),
           "spec_module_sha256_lf_prereg": PJ["provenance"]["spec_module_sha256_lf"],
           "script_sha256_lf": sha_lf(Path(__file__)),
           "phase_c_recount_module_sha256_lf": sha_lf(Path(TBL.__file__)),
           "rules_used": {"proposal_rules": {k: RULES[k] for k in ("verdict_from", "ALIVE", "WEAK", "DEAD",
                                                                   "R4_specific", "R5_specific")},
                          "min_n": MINN, "single_call_types": sorted(SINGLE),
                          "length_terciles_A": {k: CUTS[k] for k in ("swechat/claude_code", "cc_local") if k in CUTS},
                          "survival_rule": PJ["survival_rule"], "stratification": PJ["stratification"],
                          "artifact_checks": PJ["artifact_checks"], "E_freshness": PJ["splits"]["E_freshness"],
                          "dual_whitelist_regexes": {k: v for k, v in E.RX_E.items() if k.startswith("dual_")},
                          "numbered_line_regex": LINE_PREFIX.pattern},
           "deviations": DEVIATIONS, "implementation": IMPLEMENTATION,
           "phase_c_references": {k: PJ["references"][k] for k in ("ledger_unmatched", "dual_population")
                                  if k in PJ["references"]}}
    # ---------------------------------------------------------------- ids and tallies
    ids_by_split = {sp: sorted(str(s) for s in E.split_ids("swechat", sp)) for sp in SPLITS}
    overlap = set(ids_by_split["B"]) & set(ids_by_split["E"])
    assert not overlap, "B and E overlap"
    all_ids = ids_by_split["B"] + ids_by_split["E"]
    tallies = load_tallies(all_ids)
    log(f"ids B {len(ids_by_split['B'])} E {len(ids_by_split['E'])}; tallies {sum(1 for t in tallies.values() if t['has_tu'])}")
    # ---------------------------------------------------------------- raw pass (parallel)
    tasks = []
    for s in all_ids:
        fmt = FM.get(s)
        t = tallies.get(s) or {}
        if fmt == "claude_code" or (fmt in R5_FMT and t.get("tab") is not None):
            tasks.append((s, fmt, t.get("tab"), t.get("raw")))

    def size(tk):
        p = DATA_SWE / "transcripts" / f"{tk[0]}.jsonl"
        return p.stat().st_size if p.exists() else 0
    tasks.sort(key=lambda tk: -size(tk))
    raw_res = {}
    with Pool(a.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(swe_worker, tasks, chunksize=1)):
            raw_res[r["session_id"]] = r
            if (i + 1) % 500 == 0:
                log(f"raw {i + 1}/{len(tasks)}")
    log(f"raw pass done: {len(raw_res)} sessions")
    # ---------------------------------------------------------------- IR pass (swechat Claude Code)
    ir = {}
    for sp in SPLITS:
        cc_ids = [s for s in ids_by_split[sp] if FM.get(s) == "claude_code"]
        U, S, cs, ro = ir_pass_swechat(sp, raw_res, cc_ids)
        ir[sp] = {"units": U, "sess": S, "call_sessions": cs, "raw_only": ro, "cc_ids": cc_ids}
        log(f"IR {sp}: R4 units {len(U)}, sessions {len(S)}")
    # ---------------------------------------------------------------- N7 legs
    n7 = {"R4": {"swechat/claude_code": n7_cells("swechat__claude_code", "R4_DUAL", SPLITS),
                 "cc_local": n7_cells("cc_local", "R4_DUAL", ("B",))},
          "R5": {u: n7_cells("swechat__" + u.split("/", 1)[1], "R5_LEDGER", SPLITS) for u in R5_UNITS}}
    # ---------------------------------------------------------------- R4, R5
    out["R4"] = run_r4(raw_res, ir, n7, a)
    out["R5"] = run_r5(raw_res, tallies, ids_by_split, ir, n7)
    out["inputs"] = {"swechat_ids": {sp: len(v) for sp, v in ids_by_split.items()},
                     "swechat_ids_by_format": {sp: dict(Counter(FM.get(s) for s in v)) for sp, v in ids_by_split.items()},
                     "raw_tasks": len(tasks), "raw_missing_transcripts": int(sum(1 for r in raw_res.values()
                                                                                   if not r.get("exists"))),
                     "sessions_parquet_rows_read": len(tallies),
                     "never_read": "split A caches, H ids (EH 'H' key), *_A.parquet, live Claude Code stores, anything "
                                   "under swarm/ or data/swarm/"}
    # ---------------------------------------------------------------- verdict rows
    verdicts = []

    def vrow(cand, unit, blk, split, path, suffix):
        r = blk["session_rate"]
        n7p = blk.get("n7_part")
        num = (f"{r['k']}/{r['n']} = {r['p']:.4f} [{r['lo']:.4f}, {r['hi']:.4f}]" if r["n"] else f"{r['k']}/0")
        verdicts.append({"candidate": cand, "unit": unit, "split": split, "label": blk["label"],
                         "honest_part": blk["honest_part"], "n7_part": n7p, "suffix": suffix,
                         "deciding_number": f"honest session flag rate {num}; N7 leg {n7p}",
                         "json_path": path})
    for cand_key, block in (("R4", out["R4"]), ("R5", out["R5"])):
        for unit, ent in block["units"].items():
            suffix = ent.get("label_suffix")
            for sp, blk in ent["verdict_blocks"].items():
                vrow(cand_key, unit, blk, sp, f"r4_r5.json: {cand_key}.units.{unit}.verdict_blocks.{sp}", suffix)
            s = ent["survival"]
            verdicts.append({"candidate": cand_key, "unit": unit, "split": "survival", "label": s["final_label"],
                             "status": s["status"], "reasons": s["reasons"],
                             "deciding_number": "see verdict_blocks and artifact_checks",
                             "json_path": f"r4_r5.json: {cand_key}.units.{unit}.survival"})
    out["verdicts"] = verdicts
    out["n_verdict_cells"] = len(verdicts)
    out["runtime_s"] = round(time.time() - T0, 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(clean(out), indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
