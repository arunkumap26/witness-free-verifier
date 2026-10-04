"""Phase E, Track A, item A1 (second pass) for the Phase D proposals R2 (Gemini image-token ledger) and R3 (git execution
window).  Item key: r2_r3.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_r2_r3 [--no-raw-audit]

Pre-registration (the law): analysis/PREREG_E.md sections 1.1 and 1.4, analysis/prereg_e.json (a1.proposal_rules,
artifact_checks, stratification, survival_rule) and analysis/probes/prereg_e_common.py, committed in 55fc556.
check_frozen() runs before anything else. Every threshold comes from prereg_e.json / prereg.json; nothing is tuned here.

R2 image-token ledger (aiv_cu Gemini strata gemini-pro + gemini-flash; B, E and B u E):
  windows = prereg_e_common.image_windows() (consecutive usage-bearing calls of a session; d_image = change in prompt
  IMAGE tokens; n_gui = GUI calls in the window), decided per window by image_window_violation(d_image, n_gui, unit)
  with the lattice unit of the window's model from prereg_e.json resolved.image_units_A.rule (model unit, else the
  generation family's A unit; a model whose family is absent from A abstains). Session flag = >= 1 violating window.
  Verdict: a1.proposal_rules (ALIVE / WEAK / DEAD on the session-level honest flag rate + N7 R2_IMAGE cells) with the
  Phase D kill rule: session-level honest flag rate > 0.05 -> DEAD (stop the line).
R3 git execution window (swechat formats with shell: claude_code, codex, opencode, gemini; B, E, B u E; "E not blind"):
  claims = commit_claims() on shell results, command class git_cmd_class() == 'generator' only; SHA resolved by prefix
  in the Phase C lens order (linked to the session, same repo, any ok commit; data/swe-chat-pinned commits/checkpoints/
  sessions, metadata columns only); non-resolving SHAs abstain; decided claim flagged if git_window_ok() is False
  ([call ts - 2 s, result ts + 2 s]). Session flag = >= 1 flagged claim. Verdict: a1.proposal_rules + the coverage stop
  rule (claims cover < 0.005 of tool results -> capped at WEAK). The detector code is the same as the R3_GIT branch of
  analysis/probes/phase_e_n7_timing.py evaluate() (whose N7 cells this item reads), re-implemented here over claim-bearing
  results only.
For both: artifact checks AC1-AC5 on B u E, the four stratification axes (+ R2's model generation and <= 40 / > 40 GUI
windows strata), the survival rule (survival_status()), and the N7 cells of the proposal's detector read from
analysis/out/phase_e/n7_timing.json (R3_GIT) and analysis/out/phase_e/n7_content_shards/aiv_cu_{B,E}.json (R2_IMAGE).

Reads: analysis/cache/aiv_cu_{B,E}.parquet and swechat_{B,E}.parquet through prereg_e_common.read_cache only (never A,
never H), aiv_cu_sessions.parquet / swechat_population.parquet (population metadata), swe-chat-pinned sessions /
checkpoints / commits parquet (metadata columns), raw sources for the AC1 audit sample only (data/ai-village/
computer_use_turns.jsonl.gz streamed and filtered to the audited sessions; swe-chat-pinned transcripts of audited
sessions). Never reads anything of the local Qwen swarm. Writes RAW NUMBERS ONLY to analysis/out/phase_e/r2_r3.json.
Interpretation: analysis/notes/phase_e_r2_r3.md.
"""
from analysis.probes import prereg_e_common as E

PJ = E.check_frozen()  # first: the module must be the pre-registered one (AssertionError otherwise)

import argparse  # noqa: E402
import bisect  # noqa: E402
import gc  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import zlib  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.lib import stats  # noqa: E402
from analysis.lib.ir import parse_ts  # noqa: E402
from analysis.probes import prereg_common as pc  # noqa: E402

ITEM = "r2_r3"
OUT = E.OUT_E / "r2_r3.json"
N7_TIMING = E.OUT_E / "n7_timing.json"
N7_SHARDS = E.OUT_E / "n7_content_shards"
DATA_SWE = Path("C:/Swarms/data/swe-chat-pinned")
AIV_TURNS = Path("C:/Swarms/data/ai-village/computer_use_turns.jsonl.gz")
PREREG_B = json.loads((E.ROOT / "analysis" / "prereg.json").read_text(encoding="utf-8"))
LEVEL = E.LEVEL

# ------------------------------------------------------------------------------------------------ frozen rule constants
RULES = PJ["a1"]["proposal_rules"]
assert "honest flag rate <= 0.05 with CI hi <= 0.10" in RULES["ALIVE"]
assert ">= 1 single-call or single-response attack type DETECTS in N7 on E" in RULES["ALIVE"]
assert RULES["WEAK"].startswith("honest flag rate <= 0.20 and >= 1 attack type is DETECTS or PARTIAL")
assert "honest flag rate > 0.20, or no attack type clears its honest rate" in RULES["DEAD"]
assert "session-level honest flag rate > 0.05 -> DEAD" in RULES["R2_specific"]
assert "< 0.005 of tool results in the unit, the verdict is capped at WEAK" in RULES["R3_specific"]
assert "git_cmd_class == 'generator'" in RULES["R3_specific"] and "[call ts - 2 s, result ts + 2 s]" in RULES["R3_specific"]
FLAG_ALIVE, FLAG_ALIVE_HI, FLAG_WEAK = 0.05, 0.10, 0.20
R2_KILL = 0.05
R3_COVERAGE_MIN = 0.005
MINN = PREREG_B["global"]["min_n"]["rate_reportable"]
MIN_DEN, MIN_SESS = int(MINN["den_min"]), int(MINN["sessions_min"])
assert (MIN_DEN, MIN_SESS) == (30, 5)
SINGLE = set(PJ["n7_attack_battery"]["single_call_types"])
DOM = PJ["artifact_checks"]["AC4_dominance"]
assert "> 0.25" in DOM["threshold"] and "> 0.1 " in DOM["threshold"]
CUTS = PJ["resolved"]["length_terciles_A"]
IMG_RULE = PJ["resolved"]["image_units_A"]["rule"]
IMG_PER_MODEL = {m: v["unit"] for m, v in IMG_RULE["per_model"].items()}
IMG_FAMILY = IMG_RULE["family_units"]
GEM_STRATA = ("gemini-pro", "gemini-flash")
GUI40 = 40  # a1.proposal_rules.R2_specific "sessions with <= 40 vs > 40 GUI windows"
assert "<= 40 vs > 40 GUI windows" in RULES["R2_specific"]
R3_UNITS = ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini"]
FM = pc.swechat_formats()
SPLITS = ("B", "E")
CHUNK = 250  # sessions per swechat read (RAM budget)
# a superset prefilter of RX_E['commit_claim'] (a commit line needs '[<branch> <sha>]' on one line); the frozen regex is
# applied afterwards to every row that passes, so the prefilter only saves memory and cannot change a claim
PRE_CLAIM = re.compile(r"\[[^\]\n]{1,200}? (?:\(root-commit\) )?[0-9a-f]{7,40}\]")

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


# ====================================================================================================== verdict machinery
def honest_part(k, n, kill=None):
    """The honest-flag-rate half of a1.proposal_rules on a session share k/n (Wilson; global.ci_methods 'wilson for
    session shares'). min n: global.min_n.rate_reportable (>= 30 decided sessions, hence >= 5 sessions)."""
    if n < MIN_DEN:
        return "INSUFFICIENT_N"
    p, lo, hi = stats.wilson(k, n)
    if kill is not None and p > kill:
        return "DEAD"
    if p <= FLAG_ALIVE and hi <= FLAG_ALIVE_HI:
        return "ALIVE"
    if p <= FLAG_WEAK:
        return "WEAK"
    return "DEAD"


def n7_part(cells):
    """The N7 half of a1.proposal_rules from {attack|param: label}. ALIVE: >= 1 single-call/single-response attack type
    DETECTS; WEAK: >= 1 attack type DETECTS or PARTIAL; DEAD: none clears its honest rate. None if no cell exists."""
    if not cells:
        return None, {}
    det_single = sorted(k for k, v in cells.items() if v == "DETECTS" and k.split("|")[0] in SINGLE)
    dp = sorted(k for k, v in cells.items() if v in ("DETECTS", "PARTIAL"))
    lab = "ALIVE" if det_single else ("WEAK" if dp else "DEAD")
    return lab, {"single_call_DETECTS": det_single, "DETECTS_or_PARTIAL": dp,
                 "label_counts": dict(Counter(cells.values()))}


def combine(hp, n7p, cap_weak=False):
    if hp == "INSUFFICIENT_N":
        return "INSUFFICIENT_N"
    if hp == "DEAD":
        return "DEAD"
    if n7p is None:
        return "NOT_RUN"
    lab = lower(hp, n7p)
    if cap_weak and LEVEL.get(lab, 0) > 1:
        lab = "WEAK"
    return lab


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
    """Holds the decision units of one candidate (B u E) and recomputes its label on any subset."""

    def __init__(self, name, U, S, n7_cells_by_split, kill=None, cap_by_split=None):
        self.name, self.U, self.S, self.kill = name, U, S, kill
        self.n7 = {sp: n7_part(c) for sp, c in n7_cells_by_split.items()}
        self.cap = cap_by_split or {}

    def n7_for(self, split):
        # B u E uses the E cells ("N7 on E"); B uses B cells
        return self.n7.get("E" if split == "BuE" else split, (None, {}))[0]

    def label(self, U, split="BuE", weights=None):
        f = sess_flags(U)
        n, k = int(len(f)), int(f.sum())
        hp = honest_part(k, n, self.kill)
        return combine(hp, self.n7_for(split), self.cap.get(split, False)), hp, k, n

    def block(self, U, split):
        lab, hp, k, n = self.label(U, split)
        rb = rate_block(U)
        rb.update({"honest_part": hp, "n7_part": self.n7_for(split), "coverage_cap_weak": self.cap.get(split, False),
                   "label": lab})
        return rb


def min_check(name, ref_label, check_label, running):
    """AC2 / AC3 / AC5 semantics (as phase_e_a1_p1_p3.min_check): FAIL if the label changes (only a lower label counts:
    no rescue); the candidate then takes the lower label."""
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


def ac4(cand, U, cmaps):
    """AC4 dominance on the session-level statistic: denominator events = decided sessions (weight 1 each). Window/claim
    weighted shares are reported as context. Leave-outs per dominated kind: the dominant cluster, then each of the 5
    largest clusters of that kind one at a time."""
    ref, _, _, _ = cand.label(U)
    if ref not in LEVEL:
        return {"ref_label": ref, "result": "UNTESTABLE", "effect": "pass",
                "why": f"the candidate's B u E label is {ref}, so no leave-out can lower it"}
    sess = sorted(U.session_id.unique())
    w1 = {s: 1.0 for s in sess}
    wu = U.groupby("session_id").size().to_dict()
    out = {"ref_label": ref, "kinds": {}}
    worst = None
    untestable = False
    for kind, cm in cmaps.items():
        d = E.dominance(w1, cm)
        dctx = E.dominance(wu, cm)
        ent = {"dominance": {k: d.get(k) for k in ("top_share_events", "top_share_sessions", "top_session_share_events",
                                                   "dominated", "n_clusters")},
               "dominance_unit_weighted_context": {k: dctx.get(k) for k in ("top_share_events", "top_share_sessions",
                                                                           "top_session_share_events", "dominated")}}
        top = [c for c, _, _ in d.get("top_clusters", [])]
        ent["top_cluster_rank_shares"] = [(f"#{i + 1}" if c != "unknown" else "unknown", sh_e, sh_s)
                                          for i, (c, sh_e, sh_s) in enumerate(d.get("top_clusters", []))]
        if d.get("dominated"):
            lo = []
            for i, c in enumerate(top[:5]):
                keep = [s for s in sess if cm.get(s, "unknown") != c]
                lab, hp, k, n = cand.label(U[U.session_id.isin(keep)])
                lo.append({"left_out": f"#{i + 1}" if c != "unknown" else "unknown", "label": lab, "honest_part": hp,
                           "k": k, "n": n})
                if lab == "INSUFFICIENT_N":
                    untestable = True
                elif lab in LEVEL and ref in LEVEL and LEVEL[lab] < LEVEL[ref]:
                    worst = lab if worst is None else lower(worst, lab)
            ent["leave_outs"] = lo
        out["kinds"][kind] = ent
    if worst is not None:
        out["result"] = "DOMINATED"
        out["effect"] = "downgrade"
    elif untestable:
        out["result"] = "UNTESTABLE_WITHOUT_DOMINANT"
        out["effect"] = "cap_weak"
    else:
        out["result"] = "PASS" if any(v["dominance"]["dominated"] for v in out["kinds"].values()) else "NOT_DOMINATED"
        out["effect"] = "pass"
    return out


def ac5(cand, U, corpus, Usplit):
    """AC5: post-stratified session flag rate (weighted_cluster_rate, one indicator per decided session) and its label;
    SHIFT if the B point lies outside the E CI."""
    f = sess_flags(U)
    sids = list(f.index)
    cells = E.population_cells(corpus)
    w = E.post_strat_weights(corpus, sids, cells=cells)
    wr = E.weighted_cluster_rate(f.astype(float).to_numpy(), np.ones(len(f)), [w[s] for s in sids])
    n, k = int(len(f)), int(f.sum())
    if n < MIN_DEN:
        hp = "INSUFFICIENT_N"
    else:
        p, hi = wr["rate"], wr["hi"]
        if cand.kill is not None and p > cand.kill:
            hp = "DEAD"
        elif p <= FLAG_ALIVE and hi <= FLAG_ALIVE_HI:
            hp = "ALIVE"
        elif p <= FLAG_WEAK:
            hp = "WEAK"
        else:
            hp = "DEAD"
    lab = combine(hp, cand.n7_for("BuE"), cand.cap.get("BuE", False))
    out = {"weighted_session_rate": wr, "honest_part": hp, "label": lab,
           "cells_used": int(len(set(cells.get(s, "unknown") for s in sids))),
           "sessions_without_cell": int(sum(1 for s in sids if s not in cells))}
    fb = sess_flags(Usplit["B"])
    fe = sess_flags(Usplit["E"])
    if len(fb) and len(fe):
        pb = float(fb.mean())
        we = stats.wilson(int(fe.sum()), int(len(fe)))
        out["shift"] = {"B_point": pb, "E_ci": [we[1], we[2]], "SHIFT": bool(pb < we[1] or pb > we[2])}
    return out


def strata_block(cand, U, axes):
    """axes: {axis: (kind, mapping)}; kind 'session' (session -> stratum) or 'unit' (column of U). A stratum is
    reportable if >= 30 decided sessions. Confinement via prereg_e_common.confinement()."""
    out = {}
    for axis, (kind, mp) in axes.items():
        labs = {}
        rows = {}
        if kind == "session":
            strata = defaultdict(list)
            for s in U.session_id.unique():
                strata[mp.get(s, "unknown")].append(s)
            groups = {st: U[U.session_id.isin(ss)] for st, ss in strata.items()}
        else:
            groups = {st: g for st, g in U.groupby(mp)}
        anon = axis.startswith("repo") or axis.startswith("user")
        order = sorted(groups, key=lambda st: -groups[st].session_id.nunique())
        for i, st in enumerate(order):
            g = groups[st]
            lab, hp, k, n = cand.label(g)
            name = (f"#{i + 1}" if st != "unknown" else "unknown") if anon else str(st)
            rows[name] = {"sessions_decided": n, "sessions_flagged": k, "session_rate": wil(k, n),
                          "units": int(len(g)), "units_flagged": int(g.flag.sum()), "honest_part": hp,
                          "label": lab if n >= MIN_DEN else None, "reportable": n >= MIN_DEN}
            labs[name] = lab if n >= MIN_DEN else None
        conf = E.confinement(labs)
        out[axis] = {"strata": rows, "confinement": conf,
                     "n_reportable": sum(1 for v in labs.values() if v is not None),
                     "signal_bearing": sorted(k for k, v in labs.items() if v in LEVEL and LEVEL[v] >= 1)}
    return out


def assemble_survival(cand, e_label, ref_bue, checks_raw, e_seen):
    """Apply survival_status() mechanically: min-type checks (AC2, AC3, AC5) first converted with min_check relative to
    the running label (starting at the E label), then AC1 / AC4 / confinement / kill effects."""
    running = e_label if e_label in LEVEL else ref_bue
    checks = []
    for name, chk_label, kind in checks_raw:
        if kind == "min":
            c, running = min_check(name, ref_bue, chk_label, running)
            checks.append(c)
        else:
            checks.append({"name": name, "effect": kind, "result": chk_label})
            if kind == "downgrade":
                running = E.downgrade(running) if running in LEVEL else running
            elif kind == "kill":
                running = "DEAD"
            elif kind == "cap_weak" and LEVEL.get(running, 0) > 1:
                running = "WEAK"
    # Phase D proposals have no Phase B verdict, so survival_status() gets no base label and starts from the E label.
    # If the E label is not a level (INSUFFICIENT_N, or NOT_RUN because the N7 cells are absent), the status comes from
    # B u E with the suffix (survival_rule.NOT_REPLICABLE_AT_N), so the B u E label is passed as the base.
    base = "untested (Phase D proposal)" if e_label in LEVEL else ref_bue
    status, final, reasons = E.survival_status(base, e_label, [c for c in checks if c["effect"] != "pass"],
                                               has_e=True, e_seen=e_seen)
    return {"status": status, "final_label": final, "reasons": reasons, "checks": checks,
            "survival_status_base": base if base in LEVEL else None,
            "phase_b_label": "untested (Phase D proposal; survival_status base = None unless E is not a level, then the "
                             "B u E label)", "e_label": e_label, "BuE_label": ref_bue}


# ====================================================================================================== N7 cells
DETAIL = {}


def _kn(x):
    """recall / fpr in either shape: dict {k, n, p, lo, hi} (n7_timing) or [p, lo, hi] (n7_content)."""
    if isinstance(x, dict):
        return {k: x.get(k) for k in ("k", "n", "p", "lo", "hi")}
    if isinstance(x, (list, tuple)) and len(x) == 3:
        return {"p": x[0], "lo": x[1], "hi": x[2]}
    return None


def cell_detail(c):
    out = {"label": c.get("label"), "n_tampered": c.get("n_tampered"), "recall": _kn(c.get("recall")),
           "fpr": _kn(c.get("fpr"))}
    for k in ("k_tampered_flagged", "k_honest_flagged", "n_honest"):
        if k in c:
            out[k] = c[k]
    return out


def n7_cells_timing(unit, detector):
    if not N7_TIMING.exists():
        return {}, {"source": str(N7_TIMING.relative_to(E.ROOT)), "present": False}
    d = json.loads(N7_TIMING.read_text(encoding="utf-8"))
    out = {"B": {}, "E": {}}
    for k, c in d["cells"].items():
        if c["unit"] == unit and c["detector"] == detector and c["split"] in out:
            out[c["split"]][f"{c['attack']}|{c['param']}"] = c["label"]
            DETAIL[(unit, detector, c["split"], f"{c['attack']}|{c['param']}")] = cell_detail(c)
    meta = {"source": "analysis/out/phase_e/n7_timing.json", "present": True, "smoke": d.get("smoke"),
            "cap": d.get("cap"), "prereg_e_json_sha256": d.get("prereg_e_json_sha256"),
            "file_sha256_lf": sha_lf(N7_TIMING),
            "file_mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(N7_TIMING.stat().st_mtime))}
    return out, meta


def n7_cells_content(unit_file, detector):
    out, meta = {}, {}
    for sp in SPLITS:
        f = N7_SHARDS / f"{unit_file}_{sp}.json"
        if not f.exists():
            meta[sp] = {"source": str(f.relative_to(E.ROOT)).replace("\\", "/"), "present": False}
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        r = d.get("result", d)
        cells = {}
        for k, c in r.get("cells", {}).items():
            if c.get("detector") == detector:
                cells[f"{c['attack']}|{c['param']}"] = c.get("label")
                DETAIL[(unit_file, detector, sp, f"{c['attack']}|{c['param']}")] = cell_detail(c)
        out[sp] = cells
        meta[sp] = {"source": str(f.relative_to(E.ROOT)).replace("\\", "/"), "present": True,
                    "file_sha256_lf": sha_lf(f), "limit": r.get("limit"),
                    "file_mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(f.stat().st_mtime)),
                    "prereg_e_json_sha256": d.get("prereg_e_json_sha256"),
                    "detector_status": (r.get("detector_status") or {}).get(detector)}
    return out, meta


def n7_table(cells_by_split, unit_key, detector):
    return {sp: {k: DETAIL.get((unit_key, detector, sp, k), {"label": v}) for k, v in sorted(c.items())}
            for sp, c in cells_by_split.items()}


# ====================================================================================================== R2
R2_COLS = ["session_id", "stratum", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "model", "extra", "text", "uuid"]


def usage_bearing(ex):
    """Same test as image_windows(): extra holds usage_detail.promptTokensDetails as a dict."""
    if isinstance(ex, str) and "promptTokensDetails" in ex:
        det = (pc.jl(ex).get("usage_detail") or {}).get("promptTokensDetails") or {}
        return isinstance(det, dict)
    return False


def img_unit(model):
    """Lattice unit of a model string (resolved.image_units_A.rule): its model unit, else its generation family's A
    unit; a 'models/' resource prefix is stripped before the family match (logged deviation)."""
    if not isinstance(model, str):
        return None, "no model string (abstain)"
    if model in IMG_PER_MODEL and IMG_PER_MODEL[model]:
        st = IMG_RULE["per_model"][model]["status"]
        return float(IMG_PER_MODEL[model]), st
    m2 = model[len("models/"):] if model.startswith("models/") else model
    if m2 in IMG_PER_MODEL and IMG_PER_MODEL[m2]:
        return float(IMG_PER_MODEL[m2]), "model unit after stripping 'models/' (deviation)"
    for fam, u_ in IMG_FAMILY.items():
        if m2.startswith(fam):
            return float(u_), f"family unit ({fam}; absent from A)" + (" after stripping 'models/' (deviation)"
                                                                       if m2 != model else "")
    return None, "family absent from A: NOT_TESTABLE (abstain)"


def generation(model):
    if not isinstance(model, str):
        return "unknown"
    m2 = model[len("models/"):] if model.startswith("models/") else model
    for fam in IMG_FAMILY:
        if m2.startswith(fam):
            return fam
    return "other"


def vio_type(d, n_gui, unit):
    if n_gui >= 1 and d == 0:
        return "gui_no_increment"
    if n_gui >= 1 and d < 0:
        return "gui_negative"
    if n_gui == 0 and d > 0:
        return "nongui_increment"
    if n_gui == 0 and d < 0:
        return "nongui_negative"
    if unit and d > 0 and abs(d / unit - round(d / unit)) > 1e-9:
        return "off_lattice"
    return "other"


def r2_split(split):
    u = E.read_cache("aiv_cu", split, R2_COLS, filters=[("stratum", "in", list(GEM_STRATA))])
    ids = set(E.split_ids("aiv_cu", split))
    assert set(u.session_id.unique()) <= ids, "aiv_cu rows outside the split id list"
    u = u.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    log(f"R2 {split}: {len(u)} rows, {u.session_id.nunique()} Gemini-stratum sessions")
    W = E.image_windows(u)  # frozen helper
    c = u[u.kind == "call"].sort_values(["session_id", "seq"])
    res = u[(u.kind == "result") & u.call_id.notna()]
    trunc = set((s, ci) for s, ci, t, x in zip(res.session_id, res.call_id.astype(str), res.text.astype(object),
                                               res.extra.astype(object)) if E.truncated_result(t, x))
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])][["session_id", "seq", "kind", "ts", "call_id"]])
    paired = P.groupby("session_id").size().to_dict()
    rows = []
    wi = 0
    Wsid = W.session_id.to_numpy() if len(W) else np.array([])
    Wseq = W.seq.to_numpy() if len(W) else np.array([])
    for sid, g in c.groupby("session_id", sort=False):
        ub_mask = np.array([usage_bearing(x) for x in g.extra.astype(object)], dtype=bool)
        seqs = g.seq.astype(int).to_numpy()
        ub = seqs[ub_mask]
        uu = g.uuid.astype(object).to_numpy()
        cids = g.call_id.astype(str).to_numpy()
        tools = g.tool.astype(object).to_numpy()
        models = g.model.astype(object).to_numpy()
        for j in range(1, len(ub)):
            lo, hi = int(ub[j - 1]), int(ub[j])
            assert Wsid[wi] == sid and int(Wseq[wi]) == hi, "window alignment with image_windows() broke"
            w = W.iloc[wi]
            wi += 1
            m = (seqs >= lo) & (seqs < hi)
            unit, ustat = img_unit(w.model)
            d, n_gui = float(w.d_image), int(w.n_gui)
            assert n_gui == int(sum(1 for t in tools[m] if t == "gui"))
            lo_i = int(np.flatnonzero(seqs == lo)[0])
            hi_i = int(np.flatnonzero(seqs == hi)[0])
            rows.append({
                "split": split, "session_id": sid, "seq_lo": lo, "seq": hi, "d_image": d, "n_gui": n_gui,
                "n_calls": int(m.sum()), "model": w.model if isinstance(w.model, str) else None,
                "model_lo": models[lo_i] if isinstance(models[lo_i], str) else None,
                "unit": unit, "unit_status": ustat, "decided": unit is not None,
                "flag": bool(unit is not None and E.image_window_violation(d, n_gui, unit)),
                "first_tool": str(tools[m][0]) if m.any() else "none",
                "has_trunc": any((sid, ci) in trunc for ci in cids[m]),
                "call_ids": list(cids[m]), "uuid_lo": uu[lo_i], "uuid_hi": uu[hi_i], "uuids": list(uu[m])})
    assert wi == len(W), "not every image_windows() row was aligned"
    D = pd.DataFrame(rows)
    D["vtype"] = [vio_type(d, n, un) if f else None for d, n, un, f in zip(D.d_image, D.n_gui, D.unit, D.flag)]
    D["k_units"] = [(d / un) if (un and d > 0) else (0.0 if d == 0 else None) for d, un in zip(D.d_image, D.unit)]
    ses = sorted(u.session_id.unique())
    mm = E.session_model_map(u)
    agent = E.session_cluster_map("aiv_cu", u, "repo")
    strat = u.groupby("session_id").stratum.first().astype(str).to_dict()
    S = pd.DataFrame({"session_id": ses, "split": split})
    S["model"] = S.session_id.map(mm)
    S["generation"] = S.model.map(generation)
    S["agent"] = S.session_id.map(agent)
    S["stratum"] = S.session_id.map(strat)
    S["paired_calls"] = S.session_id.map(paired).fillna(0).astype(int)
    lo_c, hi_c = CUTS["aiv_cu"]["cuts"]
    S["length"] = ["short" if n <= lo_c else "mid" if n <= hi_c else "long" for n in S.paired_calls]
    dec = D[D.decided]
    gw = dec[dec.n_gui >= 1].groupby("session_id").size()
    S["gui_windows"] = S.session_id.map(gw).fillna(0).astype(int)
    S["gui40"] = np.where(S.gui_windows > GUI40, ">40", "<=40")
    S["n_windows"] = S.session_id.map(D.groupby("session_id").size()).fillna(0).astype(int)
    S["n_decided"] = S.session_id.map(dec.groupby("session_id").size()).fillna(0).astype(int)
    # join-clean pairs for AC3 (copied ids computed by the caller)
    return u, D, S, P


def r2_context(D, S):
    """Descriptive tables (no verdict effect)."""
    dec = D[D.decided]
    out = {"windows": int(len(D)), "windows_decided": int(len(dec)), "windows_abstained": int((~D.decided).sum()),
           "abstain_reasons": dict(Counter(D.unit_status[~D.decided])),
           "unit_status_counts": dict(Counter(D.unit_status)),
           "sessions_gemini_strata": int(len(S)), "sessions_with_windows": int((S.n_windows > 0).sum()),
           "sessions_decided": int((S.n_decided > 0).sum()),
           "gui_windows": int((dec.n_gui >= 1).sum()), "nongui_windows": int((dec.n_gui == 0).sum()),
           "gui_windows_no_increment": wil(int(((dec.n_gui >= 1) & (dec.d_image <= 0)).sum()), int((dec.n_gui >= 1).sum())),
           "nongui_windows_with_change": wil(int(((dec.n_gui == 0) & (dec.d_image != 0)).sum()),
                                             int((dec.n_gui == 0).sum())),
           "off_lattice_positive": wil(int((dec.vtype == "off_lattice").sum()), int((dec.d_image > 0).sum())),
           "violation_types": dict(Counter(dec.vtype.dropna())),
           "windows_with_model_switch": int(sum(1 for a, b in zip(D.model, D.model_lo) if a != b)),
           "off_lattice_d_image_values": {str(k): v for k, v in Counter(dec.d_image[dec.vtype == "off_lattice"]).items()},
           "violations_per_flagged_session": stats.describe(dec[dec.flag].groupby("session_id").size().to_numpy())
           if dec.flag.any() else {"n": 0}}
    by_model = {}
    for m, g in dec.groupby(dec.model.fillna("None")):
        by_model[m] = {"windows": int(len(g)), "sessions": int(g.session_id.nunique()), "unit": float(g.unit.iloc[0]),
                       "unit_status": g.unit_status.iloc[0], "gui_windows": int((g.n_gui >= 1).sum()),
                       "violations": int(g.flag.sum()), "violation_types": dict(Counter(g.vtype.dropna())),
                       "sessions_flagged": int(g.groupby("session_id").flag.any().sum())}
    out["by_model"] = by_model
    # k (increment in units) vs n_gui, positive-increment lattice windows only: context for 'counts images'
    ct = Counter()
    for n, k in zip(dec.n_gui, dec.k_units):
        if k is None or (isinstance(k, float) and not np.isfinite(k)):
            continue
        kk = round(k) if abs(k - round(k)) < 1e-9 else "off"
        ct[(min(int(n), 5), kk if kk == "off" else min(int(kk), 5))] += 1
    out["k_units_by_n_gui"] = [{"n_gui(5=5+)": a, "k_units(5=5+)": b, "windows": c} for (a, b), c in sorted(
        ct.items(), key=lambda x: (x[0][0], str(x[0][1])))]
    out["gui_windows_per_session"] = stats.describe(S.gui_windows.to_numpy())
    out["sessions_gt40_gui_windows"] = int((S.gui_windows > GUI40).sum())
    return out


# ------------------------------------------------------------------------------------------------ R2 AC1 (raw audit)
SID_RX = re.compile(rb'"session_id":"([0-9a-f-]{36})"')


def scan_aiv_rows(session_ids):
    """Stream computer_use_turns.jsonl.gz once and return the parsed raw rows of the given sessions only."""
    want = {s.encode() for s in session_ids}
    out = defaultdict(list)
    n_lines = 0

    def take(lines):
        nonlocal n_lines
        for ln in lines:
            n_lines += 1
            m = SID_RX.search(ln, 0, 160)
            if m and m.group(1) in want:
                out[m.group(1).decode()].append(json.loads(ln))

    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    buf = b""
    with open(AIV_TURNS, "rb") as f:
        while True:
            chunk = f.read(32 << 20)
            if not chunk:
                break
            data = d.decompress(chunk)
            while d.eof and d.unused_data:  # concatenated gzip members
                rest = d.unused_data
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                data += d.decompress(rest)
            data = buf + data
            lines = data.split(b"\n")
            buf = lines.pop()
            take(lines)
        data = buf + d.flush()
        take([x for x in data.split(b"\n") if x.strip()])
    return out, n_lines


def raw_image(row):
    am = row.get("agent_messages")
    if not isinstance(am, dict):
        return None
    um = am.get("usageMetadata")
    if not isinstance(um, dict):
        return None
    det = um.get("promptTokensDetails")
    if det is None:
        return 0
    tot = 0
    for x in det if isinstance(det, list) else []:
        if isinstance(x, dict) and x.get("modality") == "IMAGE":
            tot += int(x.get("tokenCount") or 0)
    return tot


GUI_ACTIONS_RAW = {"left_click", "right_click", "middle_click", "double_click", "triple_click", "key", "type", "scroll",
                   "mouse_move", "screenshot", "wait", "left_click_drag", "hold_key", "cursor_position",
                   "left_mouse_down", "left_mouse_up", "zoom", "drag", "keypress", "click", "move"}


def raw_is_gui(row):
    a = row.get("agent_action")
    if not isinstance(a, dict):
        return None  # talk-only turn
    if "command" in a or a.get("restart") is not None:
        return False
    return a.get("action") in GUI_ACTIONS_RAW


def audit_r2(D, do_raw):
    num = D[D.flag].sort_values(["split", "session_id", "seq"])
    keys = list(zip(num.split, num.session_id, num.seq))
    sample = E.audit_sample(keys, seed_parts=("audit", ITEM, "R2"))
    out = {"numerator_events": int(len(num)), "audited": len(sample), "seed_parts": ["audit", ITEM, "R2"],
           "fields_compared": "prompt IMAGE tokens of the two bounding usage-bearing rows (raw usageMetadata."
                              "promptTokensDetails), GUI class of every window row (raw agent_action), raw rows with an "
                              "executed action between the bounding rows (created_at order) that the IR window lacks"}
    if not sample:
        out["result"] = "PASS"
        out["note"] = "empty numerator: nothing to audit"
        return out
    if not do_raw:
        out["result"] = "NOT_RUN"
        return out
    sids = sorted({s for _, s, _ in sample})
    t = time.time()
    raw, n_lines = scan_aiv_rows(sids)
    out["raw_scan"] = {"lines_scanned": n_lines, "sessions_found": len(raw), "seconds": round(time.time() - t, 1)}
    rows = []
    for sp, sid, q in sample:
        w = num[(num.split == sp) & (num.session_id == sid) & (num.seq == q)].iloc[0]
        rr = {r.get("id"): r for r in raw.get(sid, [])}
        ent = {"split": sp, "session": sid, "seq": int(q), "ir_d_image": w.d_image, "ir_n_gui": int(w.n_gui),
               "ir_vtype": w.vtype}
        lo_r, hi_r = rr.get(w.uuid_lo), rr.get(w.uuid_hi)
        win_rows = [rr.get(x) for x in w.uuids]
        if lo_r is None or hi_r is None or any(x is None for x in win_rows):
            ent.update({"found": False, "contribution_changed": True, "field_differs": True})
            rows.append(ent)
            continue
        il, ih = raw_image(lo_r), raw_image(hi_r)
        gui = [raw_is_gui(x) for x in win_rows]
        n_gui_raw = int(sum(1 for g in gui if g))
        ids_in = set(w.uuids) | {w.uuid_hi}
        ca, cb = str(lo_r.get("created_at")), str(hi_r.get("created_at"))
        extra_rows = [r for r in raw.get(sid, []) if ca <= str(r.get("created_at")) < cb and r.get("id") not in ids_in
                      and isinstance(r.get("agent_action"), dict)]
        extra_gui = int(sum(1 for r in extra_rows if raw_is_gui(r)))
        d_raw = (ih - il) if (il is not None and ih is not None) else None
        viol_raw = (E.image_window_violation(d_raw, n_gui_raw + extra_gui, w.unit) if d_raw is not None else None)
        ent.update({"found": True, "raw_d_image": d_raw, "raw_n_gui": n_gui_raw,
                    "raw_action_rows_not_in_ir_window": len(extra_rows), "raw_gui_rows_not_in_ir_window": extra_gui,
                    "raw_model_hi": (hi_r.get("agent_messages") or {}).get("modelVersion")
                    if isinstance(hi_r.get("agent_messages"), dict) else None,
                    "field_differs": bool(d_raw != w.d_image or n_gui_raw != int(w.n_gui) or extra_rows),
                    "contribution_changed": bool(viol_raw is not True)})
        rows.append(ent)
    n_diff = sum(1 for r in rows if r["contribution_changed"])
    out.update({"found": sum(1 for r in rows if r.get("found")), "field_differs": sum(1 for r in rows if r["field_differs"]),
                "contribution_changed": n_diff,
                "result": "FAIL" if n_diff >= E.AUDIT_FAIL else "PARSER_NOTE" if n_diff == 1 else "PASS",
                "rows": rows})
    return out


def copied_call_ids_aiv():
    seen = defaultdict(set)
    for sp in SPLITS:
        x = E.read_cache("aiv_cu", sp, ["session_id", "kind", "call_id"], filters=[("kind", "==", "call")])
        for s, ci in zip(x.session_id, x.call_id.astype(object)):
            if isinstance(ci, str):
                seen[ci].add(s)
        del x
    return frozenset(c for c, ss in seen.items() if len(ss) > 1)


def run_r2(do_raw):
    t = time.time()
    parts, sess, frames = {}, {}, {}
    for sp in SPLITS:
        u, D, S, P = r2_split(sp)
        parts[sp], sess[sp] = D, S
        frames[sp] = (u[["session_id", "seq", "kind", "call_id"]].copy(), P)
        del u
        gc.collect()
    copied = copied_call_ids_aiv()
    jc = {}
    for sp in SPLITS:
        f, P = frames[sp]
        m = E.join_clean_mask(f, P, copied)
        jc[sp] = set(zip(P.session_id[m], P.call_id.astype(str)[m]))
    D = pd.concat([parts[s] for s in SPLITS], ignore_index=True)
    S = pd.concat([sess[s] for s in SPLITS], ignore_index=True)
    D["join_clean"] = [all((sid, ci) in jc[sp] for ci in cids) for sp, sid, cids in zip(D.split, D.session_id, D.call_ids)]
    U = D[D.decided].copy()
    log(f"R2 windows: {len(D)} ({len(U)} decided) in {S.session_id.nunique()} sessions; joins done")

    n7c, n7meta = n7_cells_content("aiv_cu", "R2_IMAGE")
    cand = Candidate("R2/aiv_cu (Gemini strata)", U, S, n7c, kill=R2_KILL)
    Us = {"B": U[U.split == "B"], "E": U[U.split == "E"], "BuE": U}
    verdict = {sp: cand.block(Us[sp], sp) for sp in ("B", "E", "BuE")}
    # effect of the 'models/' prefix deviation: the same rates with those windows abstaining (as phase_e_n7_content does)
    pref = U.model.astype(object).map(lambda m: isinstance(m, str) and m.startswith("models/")).astype(bool)
    dev_eff = {"windows": int(pref.sum()), "sessions": int(U.session_id[pref].nunique()),
               "flagged_windows": int(U.flag[pref].sum()),
               "if_abstaining": {sp: rate_block(Us[sp][~pref.loc[Us[sp].index]])["session_rate"]
                                 for sp in ("B", "E", "BuE")}}
    kill = {"rule": "Phase D kill rule adopted (a1.proposal_rules.R2_specific): session-level honest flag rate > 0.05 -> "
                    "DEAD (stop the line); evaluated on B u E (the re-measurement population) and on E",
            "BuE_rate": verdict["BuE"]["session_rate"]["p"], "E_rate": verdict["E"]["session_rate"]["p"],
            "fires_BuE": bool((verdict["BuE"]["session_rate"]["p"] or 0) > R2_KILL),
            "fires_E": bool((verdict["E"]["session_rate"]["p"] or 0) > R2_KILL)}
    ref = verdict["BuE"]["label"]
    # artifact checks
    ac = {}
    ac["AC1_parser"] = audit_r2(U, do_raw)
    a2_lab = cand.label(U[~U.has_trunc])[0]
    ac["AC2_truncation"] = {"windows_dropped": int(U.has_trunc.sum()), "label": a2_lab,
                            "rate": rate_block(U[~U.has_trunc])["session_rate"]}
    a3_lab = cand.label(U[U.join_clean])[0]
    ac["AC3_join"] = {"windows_dropped": int((~U.join_clean).sum()), "copied_call_ids_in_corpus_BuE": len(copied),
                      "label": a3_lab, "rate": rate_block(U[U.join_clean])["session_rate"]}
    smap = S.set_index("session_id")
    cm = {"repo (agent_id)": smap.agent.to_dict(), "model": smap.model.to_dict()}
    ac["AC4_dominance"] = ac4(cand, U, cm)
    ac["AC4_dominance"]["note"] = "aiv_cu has no user cluster (prereg_e.json artifact_checks.AC4_dominance.clusters)"
    ac["AC5_sampling"] = ac5(cand, U, "aiv_cu", {"B": Us["B"], "E": Us["E"]})
    # stratification on B u E
    axes = {"tool (first call of the window)": ("unit", "first_tool"),
            "model (session modal)": ("session", smap.model.to_dict()),
            "repo (agent_id)": ("session", smap.agent.to_dict()),
            "length tercile (A cuts 29 / 40)": ("session", smap.length.to_dict()),
            "model generation (R2 stratum)": ("session", smap.generation.to_dict()),
            "GUI windows <=40 / >40 (R2 stratum)": ("session", smap.gui40.to_dict())}
    strata = strata_block(cand, U, axes)
    confined = [a for a, v in strata.items() if v["confinement"] == "CONFINED"]
    # survival
    checks_raw = []
    if ac["AC1_parser"].get("result") == "FAIL":
        checks_raw.append(("AC1_parser_FAIL", "FAIL", "downgrade"))
    checks_raw += [("AC2_truncation", a2_lab, "min"), ("AC3_join", a3_lab, "min"),
                   ("AC5_sampling", ac["AC5_sampling"]["label"], "min")]
    if ac["AC4_dominance"]["effect"] != "pass":
        checks_raw.append((f"AC4 {ac['AC4_dominance']['result']}", ac["AC4_dominance"]["result"],
                           ac["AC4_dominance"]["effect"]))
    if confined:
        checks_raw.append(("CONFINED on " + ", ".join(confined), "CONFINED", "downgrade"))
    if kill["fires_BuE"]:
        checks_raw.append(("R2 Phase D kill rule fired on B u E (session-level honest flag rate > 0.05)", "KILL", "kill"))
    surv = assemble_survival(cand, verdict["E"]["label"], ref, checks_raw, e_seen=False)
    out = {"candidate": cand.name, "population": "aiv_cu sessions of strata gemini-pro and gemini-flash (aiv_cu_sessions "
                                                 "stratum from model_string), splits B and E",
           "unit_rule": IMG_RULE, "n7_cells": n7_table(n7c, "aiv_cu", "R2_IMAGE"), "n7_meta": n7meta,
           "n7_part": {sp: {"label": cand.n7[sp][0], **cand.n7[sp][1]} for sp in cand.n7},
           "context": {sp: r2_context(parts[sp], sess[sp]) for sp in SPLITS},
           "context_BuE": r2_context(D, S),
           "verdict_blocks": verdict, "kill_test": kill, "deviation_models_prefix_effect": dev_eff, "artifact_checks": ac, "stratification": strata,
           "confined_axes": confined, "survival": surv,
           "flagged_windows": [{"split": r.split, "session": r.session_id, "seq": int(r.seq), "model": r.model,
                                "d_image": r.d_image, "n_gui": int(r.n_gui), "n_calls": int(r.n_calls),
                                "unit": r.unit, "vtype": r.vtype, "first_tool": r.first_tool}
                               for r in U[U.flag].itertuples()],
           "runtime_s": round(time.time() - t, 1)}
    return out


# ====================================================================================================== R3
class CommitCtx:
    """External commit table for R3 (swechat only): prefix resolution in the Phase C lens order (linked to the session,
    same repo, any ok commit; phase_c_commit_witness.py q4_match). Metadata columns only. Same code as
    phase_e_n7_timing.CommitCtx (copied, not imported, so that this item does not depend on another item's module)."""

    def __init__(self, session_ids):
        import pyarrow.parquet as pq
        ids = sorted(set(session_ids))
        sess = pq.read_table(DATA_SWE / "sessions.parquet", columns=["session_id", "repo_id", "checkpoint_ids"],
                             filters=[("session_id", "in", ids)]).to_pandas()
        cp = pd.read_parquet(DATA_SWE / "checkpoints.parquet", columns=["checkpoint_pk", "session_pks"])
        meta = pq.ParquetFile(DATA_SWE / "commits.parquet").read(
            columns=["commit_sha", "checkpoint_pk", "repo_id", "commit_date", "status"]).to_pandas()
        meta = meta.reset_index(drop=True)
        mine = set(ids)
        sess_cps = defaultdict(set)
        for pk, x in zip(cp.checkpoint_pk, cp.session_pks):
            for s in (json.loads(x) if isinstance(x, str) else []):
                if s in mine:
                    sess_cps[s].add(pk)
        del cp
        for sid, x in zip(sess.session_id.astype(str), sess.checkpoint_ids):
            sess_cps[sid] |= set(json.loads(x)) if isinstance(x, str) else set()
        self.repo = dict(zip(sess.session_id.astype(str), sess.repo_id.astype(str)))
        ok = meta[meta.status == "ok"]
        self.all_shas = sorted(set(ok.commit_sha))
        self.repo_shas = {rp: sorted(set(d.commit_sha)) for rp, d in ok.groupby("repo_id")}
        self.date = {}
        for sha, d in zip(ok.commit_sha, ok.commit_date):  # first row of each sha (Phase C first_row_of_sha)
            if sha not in self.date:
                self.date[sha] = d
        cp_shas = defaultdict(set)
        for pk, sha in zip(ok.checkpoint_pk, ok.commit_sha):
            cp_shas[pk].add(sha)
        self.linked = {s: sorted(set().union(*[cp_shas.get(pk, set()) for pk in cps])) if cps else []
                       for s, cps in sess_cps.items()}
        self.n_ok_commits = int(len(ok))

    @staticmethod
    def _pref(lst, s):
        i = bisect.bisect_left(lst, s)
        return lst[i] if i < len(lst) and lst[i].startswith(s) else None

    def resolve(self, sid, sha):
        hit = self._pref(self.linked.get(sid, []), sha)
        lvl = "linked"
        if hit is None:
            hit, lvl = self._pref(self.repo_shas.get(self.repo.get(sid), []), sha), "same_repo"
        if hit is None:
            hit, lvl = self._pref(self.all_shas, sha), "other_repo"
        return (self.date.get(hit), lvl) if hit is not None else (None, "none")


def is_shell_key(k):
    return k == "shell" or k in pc.CODEX_SHELL_RAW or str(k).endswith("__bash")


LIGHT = ["session_id", "seq", "kind", "call_id", "tool", "tool_raw", "model", "stratum"]


def r3_split(split):
    """One pass over the swechat split in contiguous session-id ranges (the cache is sorted by session_id, so a range
    filter touches one or two row groups): light per-session tables for every R3 unit, and, for the (session, call_id)
    keys whose result passes the claim prefilter, every call row and every result row of that key."""
    ids_all = sorted(E.split_ids("swechat", split))
    unit_of = {s: "swechat/" + str(FM.get(s)) for s in ids_all if "swechat/" + str(FM.get(s)) in R3_UNITS}
    by_unit = {u: sorted(s for s, x in unit_of.items() if x == u) for u in R3_UNITS}
    lt_parts, sub_parts = defaultdict(list), defaultdict(list)
    call_sessions = defaultdict(set)
    n_chunks = max(1, math.ceil(len(ids_all) / CHUNK))
    for ch in np.array_split(np.array(ids_all, dtype=object), n_chunks):
        if not len(ch):
            continue
        flt = [("session_id", ">=", str(ch[0])), ("session_id", "<=", str(ch[-1]))]
        lt = E.read_cache("swechat", split, LIGHT, filters=flt)
        for s, ci, k in zip(lt.session_id, lt.call_id.astype(object), lt.kind):
            if k == "call" and isinstance(ci, str):
                call_sessions[ci].add(s)
        lt = lt[lt.session_id.isin(unit_of)]
        rs = E.read_cache("swechat", split, ["session_id", "seq", "kind", "ts", "call_id", "text", "extra"],
                          filters=flt + [("kind", "==", "result")])
        rs = rs[rs.session_id.isin(unit_of) & rs.call_id.notna()]
        hit = np.array([isinstance(t, str) and bool(PRE_CLAIM.search(t)) for t in rs.text.astype(object)], dtype=bool)
        keys = set(zip(rs.session_id[hit], rs.call_id[hit].astype(str)))
        rk = rs[[(s, str(ci)) in keys for s, ci in zip(rs.session_id, rs.call_id.astype(object))]]
        del rs
        cs = E.read_cache("swechat", split, ["session_id", "seq", "kind", "ts", "call_id", "tool", "tool_raw", "args",
                                             "command"], filters=flt + [("kind", "==", "call")])
        cs = cs[[(s, str(ci)) in keys for s, ci in zip(cs.session_id, cs.call_id.astype(object))]]
        for unit in R3_UNITS:
            lt_parts[unit].append(lt[lt.session_id.map(unit_of) == unit])
            sub = pd.concat([cs[cs.session_id.map(unit_of) == unit], rk[rk.session_id.map(unit_of) == unit]],
                            ignore_index=True)
            sub_parts[unit].append(sub)
        del lt, rk, cs
        gc.collect()
    light, subs = {}, {}
    for unit in R3_UNITS:
        light[unit] = pd.concat(lt_parts[unit], ignore_index=True) if lt_parts[unit] else pd.DataFrame(columns=LIGHT)
        subs[unit] = pd.concat(sub_parts[unit], ignore_index=True) if sub_parts[unit] else pd.DataFrame()
        log(f"R3 {split} {unit}: {len(by_unit[unit])} sessions, {len(light[unit])} rows, "
            f"{int((subs[unit].kind == 'result').sum()) if len(subs[unit]) else 0} result rows of prefilter keys")
    return by_unit, light, subs, call_sessions


def r3_pairs(sub):
    """make_pairs() on every call and result row of the prefilter keys: identical to the full-session make_pairs for
    those keys (make_pairs pairs per (session, call_id) key, first call and first result by seq)."""
    if not len(sub) or not (sub.kind == "call").any():
        return pd.DataFrame()
    return pc.make_pairs(sub)


R3_ROW_COLS = ["split", "session_id", "call_id", "sha", "sha_len", "cls", "tool_key", "level", "resolved", "window_ok",
               "off_call_s", "off_result_s", "delta_s", "trunc", "join_clean", "ts", "ts_r", "call_id_in_other_session",
               "command_programs"]


def r3_unit(unit, data, ctx_by_unit, copied):
    rows, nonshell, cover = [], Counter(), {}
    S_parts = []
    for split in SPLITS:
        by_unit, light, subs, _ = data[split]
        L, ids = light[unit], by_unit[unit]
        cc = ctx_by_unit[unit]
        n_results = int((L.kind == "result").sum())
        P = r3_pairs(subs[unit])
        res_with_gen, res_with_gen_decided, res_with_any_claim = set(), set(), set()
        if len(P):
            # AC3 flags on the claim pairs: unique keys, result after call, both stamps parse, no copied call id
            jm = E.join_clean_mask(L, P, copied)
            P = P.assign(join_clean=jm)
            for r in P.itertuples():
                txt = r.text_r if isinstance(r.text_r, str) else None
                if txt is None:
                    continue
                cl = E.commit_claims(txt)
                if not cl:
                    continue
                k = pc.tool_key(unit, r.tool, r.tool_raw)
                if not is_shell_key(k):
                    nonshell[str(k)] += 1
                    continue
                res_with_any_claim.add((r.session_id, r.call_id))
                sc = pc.shell_command(unit, k, pc.jl(r.args) if isinstance(r.args, str) else {}, r.command)
                cls = E.git_cmd_class(sc)
                if cls == "generator":
                    res_with_gen.add((r.session_id, r.call_id))
                trunc = E.truncated_result(txt, r.extra_r if isinstance(r.extra_r, str) else None)
                for sha in sorted({x for x, _ in cl}):
                    d, lvl = cc.resolve(r.session_id, sha)
                    ok = None
                    off_call = off_res = None
                    if d is not None:
                        ok = E.git_window_ok(r.ts if isinstance(r.ts, str) else None,
                                             r.ts_r if isinstance(r.ts_r, str) else None, d)
                        ct, rt = parse_ts(r.ts), parse_ts(r.ts_r)
                        dd = pd.Timestamp(d)
                        dd = dd.tz_convert("UTC") if dd.tzinfo else dd.tz_localize("UTC")
                        if ct is not None:
                            off_call = (dd - ct).total_seconds()
                        if rt is not None:
                            off_res = (dd - rt).total_seconds()
                    if cls == "generator" and ok is not None:
                        res_with_gen_decided.add((r.session_id, r.call_id))
                    rows.append({"split": split, "session_id": r.session_id, "call_id": str(r.call_id), "sha": sha,
                                 "sha_len": len(sha), "cls": cls, "tool_key": str(k), "level": lvl,
                                 "resolved": d is not None, "window_ok": ok, "off_call_s": off_call,
                                 "off_result_s": off_res, "delta_s": r.delta_s, "trunc": bool(trunc),
                                 "join_clean": bool(r.join_clean), "ts": r.ts, "ts_r": r.ts_r,
                                 "call_id_in_other_session": str(r.call_id) in copied,
                                 "command_programs": " | ".join(p_ for p_, _ in E.command_programs(sc or ""))[:120]})
        cover[split] = {"tool_results": n_results,
                        "results_with_generator_claim": len(res_with_gen),
                        "results_with_decided_generator_claim": len(res_with_gen_decided),
                        "results_with_any_shell_commit_claim": len(res_with_any_claim),
                        "share_generator": (len(res_with_gen) / n_results) if n_results else None,
                        "share_decided_generator": (len(res_with_gen_decided) / n_results) if n_results else None}
        # session table
        ses = sorted(set(L.session_id))
        mm = E.session_model_map(L)
        Lp = L[L.kind.isin(["call", "result"]) & L.call_id.notna()]
        kc = set(zip(Lp.session_id[Lp.kind == "call"], Lp.call_id[Lp.kind == "call"].astype(str)))
        kr = set(zip(Lp.session_id[Lp.kind == "result"], Lp.call_id[Lp.kind == "result"].astype(str)))
        paired = Counter(s for s, _ in kc & kr)
        Sx = pd.DataFrame({"session_id": ses, "split": split})
        Sx["model"] = Sx.session_id.map(mm)
        Sx["paired_calls"] = Sx.session_id.map(paired).fillna(0).astype(int)
        cuts = CUTS.get(unit, {}).get("cuts")
        Sx["length"] = (["short" if n <= cuts[0] else "mid" if n <= cuts[1] else "long" for n in Sx.paired_calls]
                        if cuts else "no A cuts")
        S_parts.append(Sx)
    S = pd.concat(S_parts, ignore_index=True)
    meta = E.swechat_session_meta(S.session_id.tolist())
    rmap = {s: (v if isinstance(v, str) and v not in ("", "nan", "None") else "unknown")
            for s, v in zip(meta.session_id.astype(str), meta.repo_id)}
    umap = {s: (v if isinstance(v, str) and v not in ("", "nan", "None") else "unknown")
            for s, v in zip(meta.session_id.astype(str), meta.user_id)}
    S["repo"] = S.session_id.map(lambda s: rmap.get(s, "unknown"))
    S["user"] = S.session_id.map(lambda s: umap.get(s, "unknown"))
    Cl = pd.DataFrame(rows)
    tot = {"tool_results": sum(cover[s]["tool_results"] for s in SPLITS)}
    for k in ("results_with_generator_claim", "results_with_decided_generator_claim",
              "results_with_any_shell_commit_claim"):
        tot[k] = sum(cover[s][k] for s in SPLITS)
    tot["share_generator"] = tot["results_with_generator_claim"] / tot["tool_results"] if tot["tool_results"] else None
    tot["share_decided_generator"] = (tot["results_with_decided_generator_claim"] / tot["tool_results"]
                                      if tot["tool_results"] else None)
    cover["BuE"] = tot
    return Cl, S, cover, dict(nonshell)


def r3_context(Cl):
    if not len(Cl):
        return {"claims": 0}
    out = {"claims_shell": int(len(Cl)), "claims_by_class": dict(Counter(Cl.cls)),
           "sessions_with_claims": int(Cl.session_id.nunique())}
    per = {}
    for cls, g in Cl.groupby("cls"):
        res = g[g.resolved]
        dec = res[res.window_ok.notna()]
        per[cls] = {"claims": int(len(g)), "sessions": int(g.session_id.nunique()),
                    "resolved": wil(int(g.resolved.sum()), int(len(g))),
                    "non_resolving": int((~g.resolved).sum()),
                    "resolution_level": dict(Counter(g.level)),
                    "decided": int(len(dec)),
                    "out_of_window": wil(int((dec.window_ok == False).sum()), int(len(dec))),  # noqa: E712
                    "out_of_window_by_level": {lv: wil(int((d2.window_ok == False).sum()), int(len(d2)))  # noqa: E712
                                               for lv, d2 in dec.groupby("level")}}
        if len(dec):
            per[cls]["offset_commit_minus_call_s"] = stats.describe(dec.off_call_s.dropna().to_numpy())
            per[cls]["offset_commit_minus_result_s"] = stats.describe(dec.off_result_s.dropna().to_numpy())
    out["by_class"] = per
    gen = Cl[Cl.cls == "generator"]
    if len(gen):
        out["generator_sha_len"] = dict(Counter(gen.sha_len))
    return out


# ------------------------------------------------------------------------------------------------ R3 AC1 (raw audit)
def _walk_cc(o, ts, calls, results):
    if isinstance(o, dict):
        t = o["timestamp"] if isinstance(o.get("timestamp"), str) else ts
        typ = o.get("type")
        if typ in ("tool_use", "server_tool_use") and isinstance(o.get("id"), str):
            calls.setdefault(o["id"], (t, o.get("input")))
        elif typ == "tool_result" and isinstance(o.get("tool_use_id"), str):
            results.setdefault(o["tool_use_id"], (t, o.get("content")))
        for k, v in o.items():
            if k == "normalizedMessages":
                continue
            if isinstance(v, (dict, list)):
                _walk_cc(v, t, calls, results)
    elif isinstance(o, list):
        for v in o:
            if isinstance(v, (dict, list)):
                _walk_cc(v, ts, calls, results)


def _raw_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out = []
    for b in content if isinstance(content, list) else [content]:
        if isinstance(b, dict):
            if b.get("type") == "text":
                out.append(b.get("text") or "")
            elif "text" in b:
                out.append(str(b.get("text")))
        else:
            out.append(str(b))
    return "\n".join(out)


def _parse_lines(path, want):
    objs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if want and not any(w in line for w in want):
                continue
            try:
                objs.append(json.loads(line))
            except ValueError:
                dec, i, s = json.JSONDecoder(strict=False), 0, line.strip()
                while i < len(s):
                    try:
                        o, j = dec.raw_decode(s, i)
                    except ValueError:
                        break
                    objs.append(o)
                    i = j
                    while i < len(s) and s[i].isspace():
                        i += 1
    return objs


def raw_claim_lookup(unit, sid, call_id):
    """Raw call stamp, result stamp, command and result text of one call (swechat public transcript)."""
    p = E.SWE_TRANSCRIPTS / f"{sid}.jsonl"
    if not p.exists():
        return {"found": False, "why": "no transcript"}
    if unit == "swechat/claude_code":
        calls, results = {}, {}
        for o in _parse_lines(p, [call_id]):
            _walk_cc(o, None, calls, results)
        if call_id in calls and call_id in results:
            (ct, inp), (rt, content) = calls[call_id], results[call_id]
            cmd = inp.get("command") if isinstance(inp, dict) else None
            return {"found": True, "by": "tool_use_id", "call_ts": ct, "result_ts": rt, "command": cmd,
                    "text": _raw_text(content), "stamps_compared": True}
        return {"found": False, "why": "tool_use / tool_result not located"}
    if unit == "swechat/opencode":
        try:
            doc = json.load(open(p, encoding="utf-8"))
        except (ValueError, OSError):
            return {"found": False, "why": "unparseable"}
        for msg in doc.get("messages", []):
            for pt in msg.get("parts") or []:
                if isinstance(pt, dict) and pt.get("type") == "tool" and pt.get("callID") == call_id:
                    st = pt.get("state") or {}
                    tm = st.get("time") or {}
                    inp = st.get("input") or {}

                    def iso(x):
                        return pd.Timestamp(x, unit="ms", tz="UTC").isoformat() if isinstance(x, (int, float)) else x
                    return {"found": True, "by": "callID", "call_ts": iso(tm.get("start")), "result_ts": iso(tm.get("end")),
                            "command": inp.get("command") if isinstance(inp, dict) else None,
                            "text": st.get("output") or st.get("error") or "", "stamps_compared": True}
        return {"found": False, "why": "callID not located"}
    # codex / gemini: locate the call id and the claim text only (stamps not compared)
    txt = p.read_text(encoding="utf-8", errors="replace")
    return {"found": call_id in txt, "by": "substring", "stamps_compared": False, "raw_contains_call_id": call_id in txt,
            "text": txt}


def audit_r3(unit, rows, sample_parts, do_raw):
    out = {"numerator_events": int(len(rows)), "seed_parts": list(sample_parts),
           "fields_compared": "call stamp, result stamp, command class (git_cmd_class on the raw command), the claimed "
                              "SHA in the raw result text, and the window decision recomputed from raw stamps"}
    keys = sorted(zip(rows.split, rows.session_id, rows.call_id, rows.sha))
    sample = E.audit_sample(keys, seed_parts=sample_parts)
    out["audited"] = len(sample)
    if not sample:
        out["result"] = "PASS"
        out["note"] = "empty set: nothing to audit"
        return out
    if not do_raw:
        out["result"] = "NOT_RUN"
        return out
    res = []
    for sp, sid, cid, sha in sample:
        r = rows[(rows.split == sp) & (rows.session_id == sid) & (rows.call_id == cid) & (rows.sha == sha)].iloc[0]
        raw = raw_claim_lookup(unit, sid, cid)
        ent = {"split": sp, "found": raw.get("found"), "by": raw.get("by"), "ir_window_ok": r.window_ok}
        if not raw.get("found"):
            ent.update({"contribution_changed": True, "field_differs": True, "why": raw.get("why")})
            res.append(ent)
            continue
        sha_in = bool(re.search(r"\b" + re.escape(sha) + r"\b", raw.get("text") or ""))
        ent["sha_in_raw_text"] = sha_in
        if raw.get("stamps_compared"):
            cls_raw = E.git_cmd_class(raw.get("command")) if raw.get("command") else "no raw command"
            ok_raw = None
            dts = []
            for a, b in ((raw.get("call_ts"), r.ts), (raw.get("result_ts"), r.ts_r)):
                pa, pb = parse_ts(a) if isinstance(a, str) else None, parse_ts(b) if isinstance(b, str) else None
                dts.append(abs((pa - pb).total_seconds()) if pa is not None and pb is not None else None)
            d, _ = CTX_FOR_AUDIT[unit].resolve(sid, sha)
            if d is not None and isinstance(raw.get("call_ts"), str) and isinstance(raw.get("result_ts"), str):
                ok_raw = E.git_window_ok(raw["call_ts"], raw["result_ts"], d)
            ent.update({"raw_cls": cls_raw, "abs_call_ts_diff_s": dts[0], "abs_result_ts_diff_s": dts[1],
                        "raw_window_ok": ok_raw,
                        "field_differs": bool(not sha_in or cls_raw != r.cls or (dts[0] or 0) > 0.0015
                                              or (dts[1] or 0) > 0.0015),
                        "contribution_changed": bool(not sha_in or cls_raw != r.cls or ok_raw != r.window_ok)})
        else:
            ent.update({"field_differs": not sha_in, "contribution_changed": not sha_in})
        res.append(ent)
    n_diff = sum(1 for x in res if x["contribution_changed"])
    out.update({"found": sum(1 for x in res if x.get("found")), "field_differs": sum(1 for x in res if x["field_differs"]),
                "contribution_changed": n_diff,
                "result": "FAIL" if n_diff >= E.AUDIT_FAIL else "PARSER_NOTE" if n_diff == 1 else "PASS", "rows": res})
    return out


CTX_FOR_AUDIT = {}


def run_r3(do_raw):
    t = time.time()
    data = {}
    for sp in SPLITS:
        data[sp] = r3_split(sp)
        gc.collect()
    call_sessions = defaultdict(set)
    for sp in SPLITS:
        for ci, ss in data[sp][3].items():
            call_sessions[ci] |= ss
    copied = frozenset(c for c, ss in call_sessions.items() if len(ss) > 1)
    del call_sessions
    for sp in SPLITS:
        data[sp] = data[sp][:3] + (None,)
    gc.collect()
    n7all = {}
    out_units = {}
    for unit in R3_UNITS:
        ids = data["B"][0][unit] + data["E"][0][unit]
        ctx = CommitCtx(ids)
        CTX_FOR_AUDIT[unit] = ctx
        Cl, S, cover, nonshell = r3_unit(unit, data, {unit: ctx}, copied)
        n7c, n7meta = n7_cells_timing(unit, "R3_GIT")
        n7all[unit] = n7c
        cap = {sp: bool(cover[sp]["share_generator"] is not None and cover[sp]["share_generator"] < R3_COVERAGE_MIN)
               for sp in ("B", "E", "BuE")}
        if len(Cl):
            U = Cl[(Cl.cls == "generator") & Cl.resolved & Cl.window_ok.notna()].copy()
        else:
            U = pd.DataFrame(columns=R3_ROW_COLS)
        U["flag"] = (U.window_ok == False).astype(bool) if len(U) else pd.Series(dtype=bool)  # noqa: E712
        if not len(U):
            U = U.astype({"trunc": bool, "join_clean": bool})
        cand = Candidate(f"R3/{unit}", U, S, n7c, kill=None, cap_by_split=cap)
        Us = {"B": U[U.split == "B"], "E": U[U.split == "E"], "BuE": U}
        verdict = {sp: cand.block(Us[sp], sp) for sp in ("B", "E", "BuE")}
        ref = verdict["BuE"]["label"]
        ac = {}
        ac["AC1_parser"] = audit_r3(unit, U[U.flag] if len(U) else U, ("audit", ITEM, "R3", unit), do_raw)
        den_ctx = None
        if len(U):
            den_ctx = audit_r3(unit, U[~U.flag], ("audit", ITEM, "R3den", unit), do_raw)
            den_ctx["note"] = ("CONTEXT, no verdict effect: the same comparison on 30 decided in-window claims (the "
                               "prereg's AC1 samples the numerator only)")
        ac["AC1_denominator_context"] = den_ctx
        a2 = U[~U.trunc] if len(U) else U
        a3 = U[U.join_clean] if len(U) else U
        a2_lab, a3_lab = cand.label(a2)[0], cand.label(a3)[0]
        ac["AC2_truncation"] = {"claims_dropped": int(U.trunc.sum()) if len(U) else 0, "label": a2_lab,
                                "rate": rate_block(a2)["session_rate"]}
        ac["AC3_join"] = {"claims_dropped": int((~U.join_clean).sum()) if len(U) else 0, "label": a3_lab,
                          "copied_call_ids_in_swechat_BuE": len(copied), "rate": rate_block(a3)["session_rate"]}
        smap = S.set_index("session_id")
        if len(U):
            ac["AC4_dominance"] = ac4(cand, U, {"repo": smap.repo.to_dict(), "user": smap.user.to_dict(),
                                                "model": smap.model.to_dict()})
            ac["AC5_sampling"] = ac5(cand, U, "swechat", {"B": Us["B"], "E": Us["E"]})
            axes = {"tool (tool_key)": ("unit", "tool_key"), "model (session modal)": ("session", smap.model.to_dict()),
                    "repo": ("session", smap.repo.to_dict()),
                    "length tercile (unit A cuts)": ("session", smap.length.to_dict())}
            strata = strata_block(cand, U, axes)
        else:
            ac["AC4_dominance"] = {"result": "NOT_RUN", "effect": "pass", "why": "no decided claims"}
            ac["AC5_sampling"] = {"label": "INSUFFICIENT_N", "why": "no decided claims"}
            strata = {}
        confined = [a for a, v in strata.items() if v["confinement"] == "CONFINED"]
        checks_raw = []
        if ac["AC1_parser"].get("result") == "FAIL":
            checks_raw.append(("AC1_parser_FAIL", "FAIL", "downgrade"))
        checks_raw += [("AC2_truncation", a2_lab, "min"), ("AC3_join", a3_lab, "min"),
                       ("AC5_sampling", ac["AC5_sampling"]["label"], "min")]
        if ac["AC4_dominance"]["effect"] != "pass":
            checks_raw.append((f"AC4 {ac['AC4_dominance']['result']}", ac["AC4_dominance"]["result"],
                               ac["AC4_dominance"]["effect"]))
        if confined:
            checks_raw.append(("CONFINED on " + ", ".join(confined), "CONFINED", "downgrade"))
        surv = assemble_survival(cand, verdict["E"]["label"], ref, checks_raw, e_seen=True)
        flagged = U[U.flag] if len(U) else U
        out_units[unit] = {
            "candidate": cand.name, "label_suffix": "(E not blind)",
            "coverage": cover, "coverage_rule": {"threshold": R3_COVERAGE_MIN, "cap_weak": cap,
                                                 "statistic": "results with >= 1 generator-class commit claim / all tool "
                                                              "results of the unit (share_generator); the decided "
                                                              "share is reported beside it"},
            "commit_ctx": {"ok_commit_rows": ctx.n_ok_commits, "sessions_linked_to_ok_commit": int(
                sum(1 for s in ids if ctx.linked.get(s)))},
            "claim_results_in_non_shell_tools": nonshell,
            "context": {sp: r3_context(Cl[Cl.split == sp]) if len(Cl) else {"claims": 0} for sp in SPLITS},
            "context_BuE": r3_context(Cl),
            "n7_cells": n7_table(n7c, unit, "R3_GIT"), "n7_meta": n7meta,
            "n7_part": {sp: {"label": cand.n7[sp][0], **cand.n7[sp][1]} for sp in cand.n7},
            "verdict_blocks": verdict, "artifact_checks": ac, "stratification": strata, "confined_axes": confined,
            "survival": surv,
            "flagged_claims": [{"split": r.split, "session": r.session_id, "call_id": r.call_id, "sha": r.sha,
                                "level": r.level, "off_call_s": r.off_call_s, "off_result_s": r.off_result_s,
                                "delta_s": r.delta_s, "command_programs": r.command_programs, "trunc": r.trunc,
                                "join_clean": r.join_clean, "call_id_in_other_session": r.call_id_in_other_session}
                               for r in flagged.itertuples()],
            "non_generator_out_of_window": ([{"split": r.split, "cls": r.cls, "level": r.level, "off_call_s": r.off_call_s,
                                              "off_result_s": r.off_result_s, "command_programs": r.command_programs}
                                             for r in Cl[(Cl.cls != "generator") & (Cl.window_ok == False)].itertuples()]  # noqa: E712
                                            if len(Cl) else []),
        }
        log(f"R3 {unit}: claims {len(Cl)}, decided generator {len(U)}, flagged {int(U.flag.sum()) if len(U) else 0}; "
            f"E label {verdict['E']['label']}, survival {surv['status']}")
        del Cl
        gc.collect()
    return {"units": out_units, "runtime_s": round(time.time() - t, 1)}


# ====================================================================================================== main
DEVIATIONS = [
    {"item": "output file names",
     "prereg_said": "outputs.A1: phase_e_a1_<candidate>.py -> a1_<candidate>.json",
     "what_you_did": "analysis/probes/phase_e_r2_r3.py -> analysis/out/phase_e/r2_r3.json (R2 and R3 in one file)",
     "why": "the orchestrator assigned the item key r2_r3 for both proposals",
     "effect_on_verdict": "none"},
    {"item": "denominator of the session-level honest flag rate",
     "prereg_said": "a1.proposal_rules: 'session-level honest flag rate' (denominator not spelled out); N7 counts an "
                    "abstaining session as not flagged",
     "what_you_did": "the verdict rate is flagged sessions / sessions in which the detector decides >= 1 unit (window "
                     "or claim), Wilson CI; the rate over all sessions of the population is not used for the verdict",
     "why": "a session in which the detector decides nothing cannot be a false positive; counting it would dilute the "
            "rate. This choice can only raise the rate relative to the all-session denominator",
     "effect_on_verdict": "conservative (raises the honest rate)"},
    {"item": "R2 model strings with a 'models/' resource prefix",
     "prereg_said": "resolved.image_units_A.rule: a model absent from A uses its generation family's A unit "
                    "('gemini-2.5' 258, 'gemini-3' 1,064)",
     "what_you_did": "'models/gemini-2.5-pro-preview-05-06' (absent from A) is matched to its family after stripping the "
                     "'models/' prefix, so it uses the gemini-2.5 unit 258 instead of abstaining; the N7 content detector "
                     "(phase_e_n7_content.Ctx.img_unit) does not strip the prefix and abstains on these windows",
     "why": "the prereg assigns a family unit to every model of a family present on A; the prefix is a resource-path "
            "spelling of a gemini-2.5 model, not a different family",
     "effect_on_verdict": "R2.deviation_models_prefix_effect: windows / sessions / flagged windows decided by this rule, "
                          "and the session rates if those windows abstained instead"},
    {"item": "R2 AC1 raw comparison",
     "prereg_said": "AC1: look up each audited event in the raw source and compare the fields the statistic uses",
     "what_you_did": "raw rows are matched by IR uuid = raw turn id; the window is recomputed from the raw IMAGE counts of "
                     "the two bounding rows and the raw GUI class of each row (agent_action.action in the loader's "
                     "GUI_ACTIONS list; bash/restart = not GUI), plus any raw row with an executed action between the "
                     "bounding rows (created_at order) that the IR window lacks",
     "why": "this is the field set image_window_violation() reads",
     "effect_on_verdict": "none unless AC1 FAILs"},
    {"item": "R3 AC1 for codex and gemini formats",
     "prereg_said": "AC1: compare stamps, join, text length, error flag, request id with the raw source",
     "what_you_did": "for swechat/codex and swechat/gemini the raw lookup only checks that the call id and the claimed "
                     "SHA occur in the raw transcript (stamps not compared); claude_code (tool_use_id walk) and "
                     "opencode (part callID) compare stamps, command class and the window decision",
     "why": "no raw-format stamp parser for those two formats exists in the committed code; see AC1 'audited' counts "
            "for whether any such claim was audited",
     "effect_on_verdict": "none unless a codex/gemini claim is audited"},
    {"item": "AC1 FAIL effect and AC4 / confinement aggregation",
     "prereg_said": "AC1 FAIL; AC4 DOMINATED -> one-level downgrade; confinement costs one level",
     "what_you_did": "as phase_e_a1_p1_p3: AC1 FAIL = one-level downgrade; confinement on any number of axes = one "
                     "downgrade; AC2/AC3/AC5 FAIL = the lower label (min_check)",
     "why": "same mechanics as the sibling A1 item",
     "effect_on_verdict": "none unless those checks fire"},
    {"item": "AC4 weights for a session-level statistic",
     "prereg_said": "dominated if one cluster holds > 0.25 of the denominator events or contributing sessions, or one "
                    "session holds > 0.10 of the denominator events",
     "what_you_did": "denominator events = decided sessions (weight 1 each); the window- or claim-weighted shares are "
                     "reported as context only",
     "why": "the statistic's denominator is the session",
     "effect_on_verdict": "a single session cannot exceed 0.10 unless fewer than 10 sessions decide"},
    {"item": "R2 stratification on the tool axis",
     "prereg_said": "stratification axis tool = tool_key",
     "what_you_did": "a window can hold several calls; its tool stratum is the tool_key of the window's first call",
     "why": "the decision unit is a window, not a call",
     "effect_on_verdict": "only through confinement on that axis"},
    {"item": "WEAK rule split for N7 cells",
     "prereg_said": "ALIVE needs a single-call DETECTS 'in N7 on E (B for units without E)'; WEAK 'and >= 1 attack type "
                    "is DETECTS or PARTIAL' (split not named)",
     "what_you_did": "the E and B u E verdicts read the E cells, the B verdict reads the B cells, for both halves of the "
                     "rule",
     "why": "keeps the replication verdict on E-only evidence",
     "effect_on_verdict": "see n7_part per split"},
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-raw-audit", action="store_true")
    ap.add_argument("--only", choices=["R2", "R3"], default=None)
    ap.add_argument("--out", default=None, help="development runs only: write somewhere other than the official path")
    a = ap.parse_args(argv)
    out_path = Path(a.out) if a.out else OUT
    do_raw = not a.no_raw_audit
    out = {"item": ITEM, "generated_by": "analysis/probes/phase_e_r2_r3.py",
           "prereg_e_json_sha256": E.sha256_file(E.PREREG_E_JSON),
           "spec_module_sha256_lf": E.sha256_lf(Path(E.__file__)),
           "spec_module_sha256_lf_prereg": PJ["provenance"]["spec_module_sha256_lf"],
           "script_sha256_lf": sha_lf(Path(__file__)),
           "rules_used": {"proposal_rules": RULES, "min_n": MINN, "single_call_types": sorted(SINGLE),
                          "image_units_A_rule": IMG_RULE, "length_terciles_A": {k: CUTS[k] for k in
                                                                              ["aiv_cu"] + R3_UNITS if k in CUTS},
                          "survival_rule": PJ["survival_rule"], "stratification": PJ["stratification"],
                          "artifact_checks": PJ["artifact_checks"]},
           "deviations": DEVIATIONS, "raw_audit": do_raw}
    if a.only in (None, "R2"):
        log("R2 start")
        out["R2"] = run_r2(do_raw)
        gc.collect()
    if a.only in (None, "R3"):
        log("R3 start")
        out["R3"] = run_r3(do_raw)
    verdicts = []

    def vrow(cand, unit, blk, split, path):
        sr = blk["session_rate"]
        verdicts.append({"candidate": cand, "unit": unit, "split": split, "label": blk["label"],
                         "deciding_number": (f"session honest flag rate {sr['k']}/{sr['n']} = "
                                             f"{sr['p'] if sr['p'] is None else round(sr['p'], 4)} W[{_r(sr['lo'])}, "
                                             f"{_r(sr['hi'])}]; honest part {blk['honest_part']}; N7 part "
                                             f"{blk['n7_part']}; coverage cap {blk['coverage_cap_weak']}"),
                         "json_path": path})
    if "R2" in out:
        for sp in ("B", "E", "BuE"):
            vrow(out["R2"]["candidate"], "aiv_cu (Gemini strata)", out["R2"]["verdict_blocks"][sp], sp,
                 f"R2.verdict_blocks.{sp}")
        s = out["R2"]["survival"]
        verdicts.append({"candidate": out["R2"]["candidate"], "unit": "aiv_cu (Gemini strata)", "split": "survival",
                         "label": s["final_label"], "status": s["status"], "reasons": s["reasons"],
                         "json_path": "R2.survival"})
    if "R3" in out:
        for unit, v in out["R3"]["units"].items():
            for sp in ("B", "E", "BuE"):
                vrow(v["candidate"] + " (E not blind)", unit, v["verdict_blocks"][sp], sp,
                     f"R3.units.{unit}.verdict_blocks.{sp}")
            s = v["survival"]
            verdicts.append({"candidate": v["candidate"] + " (E not blind)", "unit": unit, "split": "survival",
                             "label": s["final_label"] if s["final_label"] is not None else s["BuE_label"],
                             "status": s["status"], "reasons": s["reasons"],
                             "json_path": f"R3.units.{unit}.survival"})
    out["verdicts"] = verdicts
    out["n_verdict_cells"] = len(verdicts)
    out["runtime_s"] = round(time.time() - T0, 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(clean(out), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"wrote {out_path}")


def _r(x):
    return None if x is None else round(x, 4)


if __name__ == "__main__":
    main(sys.argv[1:])
