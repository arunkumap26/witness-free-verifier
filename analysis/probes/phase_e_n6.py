"""Phase E, Track A, item N6: cross-corpus transfer grid (prereg_e.json S:n6_transfer_grid; PREREG_E.md section 3).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n6
Check a notes file's numbers against the JSON:  python -m analysis.probes.phase_e_n6 --check analysis/notes/phase_e_n6.md

ASSEMBLY ONLY. No IR cache, raw source, sample file or split is opened: every cell is filled from a committed Phase B
or Phase E output file by the pre-registered fill rule. A cell that no item computed is NOT_RUN(<reason>) or
NOT_TESTABLE(<field>); nothing is guessed and no Phase B verdict is copied into a cell that was not re-run.

Fill rule (S:n6_transfer_grid.fill_rule), applied per (row, column) in this order:
 1. Field gate. NOT_TESTABLE(<field>) iff a required field (S:n6_transfer_grid.required_fields) is absent:
    resolved.n6_field_gate_A on A; the B re-check is taken from prereg.json population_B (units with no B or E session)
    and from the items' own B / E field checks (an item's NOT_TESTABLE stands).
 2. Run. The mechanism's own verdict rule on B and E as computed by its Phase E item: the E verdict where the unit has
    E and E is not INSUFFICIENT_N, else the B verdict ('B only'); both are stored. The cell carries the label after the
    pre-registered artifact checks / kill tests (they can only lower a label; the items' own n6 cells do the same); the
    label before them is stored as label_precheck and used in a sensitivity count.
    Probes 1-4: the A1 candidate's final label where an A1 candidate exists; units without E: the Phase B verdict,
    suffix 'B only (Phase B run)'; units with E that no Phase E item re-ran: NOT_RUN(not re-run on E) with the Phase B
    verdict beside it, never in it.
 3. Labels. aiv_cc 'single-agent'; cc_local 'private'.
R1: f1_bracket.json left the R1 verdict PENDING_N7 (n7 output absent when it ran). This script applies the
pre-registered proposal rule (S:a1.proposal_rules) to f1's honest leg / kill rule / artifact-check ceiling and the
R1_BRACKET cells of n7_timing.json (deviation logged).

Transfer statement (S:n6_transfer_grid.transfer_statement), evaluated mechanically per row over the loaded columns:
TRANSFERS = both cells >= WEAK; FAILS TO TRANSFER = one ALIVE and the other DEAD; counts of testable / ALIVE / WEAK /
DEAD cells and of failing pairs.

Writes analysis/out/phase_e/n6_grid.json (labels and raw numbers only), analysis/TRANSFER_MATRIX.md and the
'Phase E update' section appended to analysis/DECISION_TABLE.md (the A0 text above the marker is left byte-identical;
checked). Every number in both .md outputs is checked to occur in n6_grid.json.
cc_local: aggregates only (only labels and counts are copied). aiv_cc: single-agent case study.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from itertools import combinations
from pathlib import Path

from analysis.probes import prereg_e_common as pe

T0 = time.time()
ROOT = pe.ROOT
OUT_E = pe.OUT_E
OUT = OUT_E / "n6_grid.json"
MD_TRANSFER = ROOT / "analysis" / "TRANSFER_MATRIX.md"
MD_DECISION = ROOT / "analysis" / "DECISION_TABLE.md"
DT_MARKER = "## Phase E update"
LEVEL = dict(pe.LEVEL)                     # ALIVE 2, WEAK 1, DEAD 0
VERDICT = ("ALIVE", "WEAK", "DEAD")
BASES = ("ALIVE", "WEAK", "DEAD", "INSUFFICIENT_N", "INCONCLUSIVE", "NOT_TESTABLE", "NOT_RUN", "PER_STRATUM")

INPUT_PATHS = {
    "prereg_e": "analysis/prereg_e.json",
    "prereg_b": "analysis/prereg.json",
    "a0": "analysis/out/phase_e/decision_table.json",
    "probe_1": "analysis/out/probe_1.json", "probe_2": "analysis/out/probe_2.json",
    "probe_3": "analysis/out/probe_3.json", "probe_4": "analysis/out/probe_4.json",
    "f1": "analysis/out/phase_e/f1_bracket.json", "f2": "analysis/out/phase_e/f2_floor_shift.json",
    "f3": "analysis/out/phase_e/f3_round.json",
    "a1_p1_p3": "analysis/out/phase_e/a1_p1_p3.json", "a1_p2_p4_f3": "analysis/out/phase_e/a1_p2_p4_f3.json",
    "n1": "analysis/out/phase_e/n1.json", "n2": "analysis/out/phase_e/n2.json", "n3": "analysis/out/phase_e/n3.json",
    "n4_n5cg": "analysis/out/phase_e/n4_n5cg.json", "n5_battery": "analysis/out/phase_e/n5_battery.json",
    "n7_timing": "analysis/out/phase_e/n7_timing.json", "n7_content": "analysis/out/phase_e/n7_content.json",
    "r2_r3": "analysis/out/phase_e/r2_r3.json", "r4_r5": "analysis/out/phase_e/r4_r5.json",
}
TRACK_B_FILES = {  # Track B corpora with a B/E measurement (prereg_e.json change_log extensions + newcorp_register.json)
    "agentcap": "analysis/out/phase_e/newcorp_measure_agentcap.json",
    "glm_tb21": "analysis/out/phase_e/newcorp_measure_glm_tb21.json",
    "pub_cc_hf": "analysis/out/phase_e/newcorp_measure_pub_cc_hf.json",
    "pub_codex": "analysis/out/phase_e/newcorp_measure_pub_codex.json",
    "pub_trace_commons": "analysis/out/phase_e/newcorp_measure_pub_trace_commons.json",
    "tbench2": "analysis/out/phase_e/newcorp_measure_tbench2.json",
}
NAMES = {
    "P1_latency": "Probe 1: latency physics",
    "P2_knowledge": "Probe 2: knowledge precedence (main thread)",
    "P3a_zero_error": "Probe 3a: zero-error tail",
    "P3b_reaction": "Probe 3b: retry reaction to failure",
    "P4a_hex": "Probe 4a: hex digit uniformity",
    "P4b_round": "Probe 4b: round numbers",
    "R1_bracket": "R1: request-id clock bracket",
    "R2_image": "R2: image-token ledger",
    "R3_git": "R3: git execution window",
    "R4_dual": "R4: harness dual-rendering recount",
    "R5_ledger": "R5: usage-ledger reconciliation",
    "N1": "N1: conditional duration model",
    "N2": "N2: token accounting",
    "N3": "N3: reaction time to a result",
    "N4": "N4: concurrency physics",
    "N5a_determinism": "N5a: repeat-command determinism",
    "N5b_sort": "N5b: sort-order violations",
    "N5c_truncation": "N5c: truncation boundary",
    "N5d_whitespace": "N5d: whitespace fingerprints",
    "N5e_size": "N5e: output-size distribution",
    "N5f_error_fidelity": "N5f: error-message fidelity",
    "N5g_cold_start": "N5g: cold-start signature",
}
# Required fields (S:n6_transfer_grid.required_fields) -> keys of resolved.n6_field_gate_A. 'responses_A' is the
# per-response usage count of n2.json A_granularity (the A-split N2 granularity check). N5c's truncation markers and
# N5f's numbered Reads have no A gate key: their items decide (an item NOT_TESTABLE stands).
REQ = {
    "P1_latency": [("pairs_distinct_stamps", "distinct call/result stamps")],
    "P2_knowledge": [("pairs", "call/result pairs"), ("results_with_text", "result text")],
    "P3a_zero_error": [("error_definition", "error signal")],
    "P3b_reaction": [("error_definition", "error signal")],
    "P4a_hex": [("results_with_text", "result text")],
    "P4b_round": [("results_with_text", "result text")],
    "R1_bracket": [("request_ids_decodable", "provider request ids decodable to ms"), ("pairs_stamped", "event stamps")],
    "R2_image": [("image_usage_rows", "per-response prompt IMAGE token counts")],
    "R3_git": [("commit_claims", "shell results with commit lines"),
               ("external_commit_table", "external commit table linked by repo")],
    "R4_dual": [("raw_structured_counters", "harness structured counters (toolUseResult numLines)")],
    "R5_ledger": [("external_usage_tally", "external usage tally"), ("responses_A", "per-response usage")],
    "N1": [("pairs_distinct_stamps", "per-call stamps (distinct call/result stamps)")],
    "N2": [("usage_granular", "per-response usage_in and usage_out (GRANULAR)")],
    "N3": [("pairs_stamped", "event stamps for results and the next model event")],
    "N4": [("pairs_distinct_stamps", "per-call intervals (distinct call/result stamps)")],
    "N5a_determinism": [("results_with_text", "result text + commands")],
    "N5b_sort": [("results_with_text", "result text + commands")],
    "N5c_truncation": [("results_with_text", "result text with harness truncation markers")],
    "N5d_whitespace": [("results_with_text", "result text + commands")],
    "N5e_size": [("results_with_text", "result text")],
    "N5f_error_fidelity": [("error_definition", "error results"), ("results_with_text", "result text")],
    "N5g_cold_start": [("pairs_distinct_stamps", "per-call stamps (distinct call/result stamps)")],
}
A0KEY = {"P1_latency": "p1_latency", "P2_knowledge": "p2_main", "P3a_zero_error": "p3_tail",
         "P3b_reaction": "p3_retry", "P4a_hex": "p4_hex", "P4b_round": "p4_round", "R1_bracket": "d1_bracket",
         "R2_image": "d2_image", "R3_git": "d3_git", "R4_dual": "d4_dual", "R5_ledger": "d5_ledger"}
A1_PREFIX = {"P1": "P1_latency", "P3zero": "P3a_zero_error", "P2": "P2_knowledge", "P4round": "P4b_round"}
TAGS = {"cc_local": "private", "aiv_cc": "single-agent"}
NO_E_UNITS = ("cc_local", "aiv_cc", "whowhen")


# ============================================================================================================ helpers
def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def base_of(label):
    if label is None:
        return None
    for b in BASES:
        if label == b or label.startswith(b + "(") or label.startswith(b + " "):
            return b
    raise ValueError(f"label outside the vocabulary: {label!r}")


def lowest(labels):
    labs = [x for x in labels if x in LEVEL]
    return min(labs, key=LEVEL.get) if labs else None


def fx(x, nd=4):
    return "NA" if x is None else f"{x:.{nd}f}"


def fmt_val(v):
    if isinstance(v, bool) or v is None:
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(fmt_val(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + "; ".join(f"{k} {fmt_val(x)}" for k, x in v.items()) + "}"
    return str(v)


def fmt_dict(d, skip=()):
    if not isinstance(d, dict):
        return fmt_val(d)
    return "; ".join(f"{k} {fmt_val(v)}" for k, v in d.items() if k not in skip)


def resolve(obj, path):
    """Resolve a dotted JSON path whose keys may themselves contain dots or slashes (greedy longest-key match)."""
    cur, rest = obj, path
    while rest:
        if not isinstance(cur, dict):
            return None
        hit = None
        for k in sorted(cur.keys(), key=len, reverse=True):
            if rest == k or rest.startswith(k + "."):
                hit = k
                break
        if hit is None:
            return None
        cur, rest = cur[hit], rest[len(hit) + 1:]
    return cur


def rate_text(r, nd=4):
    """cluster_rate dict {rate, lo, hi, num, den, n_sessions} -> 'k/n = p [lo, hi], s sessions'."""
    if not isinstance(r, dict):
        return fmt_val(r)
    return (f"{int(r['num'])}/{int(r['den'])} = {fx(r['rate'], nd)} [{fx(r['lo'], nd)}, {fx(r['hi'], nd)}], "
            f"{r['n_sessions']} s")


def wilson_text(r, nd=4):
    return f"{r['k']}/{r['n']} = {fx(r['p'], nd)} W[{fx(r['lo'], nd)}, {fx(r['hi'], nd)}]"


def triple(t, nd=3):
    return f"{fx(t[0], nd)} [{fx(t[1], nd)}, {fx(t[2], nd)}]" if t and t[0] is not None else "NA"


# ============================================================================================================ inputs
def load_inputs():
    pj = pe.check_frozen()
    D, H = {}, {}
    for k, rel in INPUT_PATHS.items():
        D[k] = load(rel)
        H[rel] = sha256(ROOT / rel)
    TB = {}
    for c, rel in TRACK_B_FILES.items():
        TB[c] = load(rel)
        H[rel] = sha256(ROOT / rel)
    H["analysis/probes/prereg_e_common.py (sha256_lf)"] = pe.sha256_lf(Path(pe.__file__))
    return pj, D, TB, H


# ============================================================================================================ context
class Ctx:
    def __init__(self, pj, D, TB):
        self.pj, self.D, self.TB = pj, D, TB
        self.spec = pj["n6_transfer_grid"]
        self.rows = list(self.spec["rows"])
        self.units_b = [c for c in self.spec["columns"] if not c.startswith("+")]
        self.gate_a = pj["resolved"]["n6_field_gate_A"]
        self.n2_A = D["n2"]["A_granularity"]
        popB = D["prereg_b"]["population_B"]["sessions"]
        n4cells = D["n4_n5cg"]["n6_cells"]
        # B re-check: units with no B session (prereg.json population_B) that the items also found absent from E
        self.no_be = sorted(u for u in self.units_b if popB.get(u) == 0 and
                            all("no sessions in B or E" in (n4cells.get(u, {}).get(r, {}).get("label") or "")
                                for r in ("N4", "N5c_truncation", "N5g_cold_start")))
        self.no_be_source = {u: {"population_B_sessions": popB.get(u),
                                 "n4_n5cg_labels": {r: n4cells[u][r]["label"] for r in ("N4", "N5c_truncation",
                                                                                         "N5g_cold_start")}}
                             for u in self.no_be}
        self.has_e = {u: (u.startswith("swechat/") or u == "aiv_cu") and u not in self.no_be for u in self.units_b}
        # A0 (Phase B / Phase A-D consolidated) rows
        self.a0 = {(r["mechanism_key"], r["corpus"]): r for r in D["a0"]["rows"]}
        # A1 verdicts: key '<prefix>/<unit>[/<stratum>]'
        self.a1 = {}
        for src in ("a1_p1_p3", "a1_p2_p4_f3"):
            for k, v in D[src]["verdicts"].items():
                if "(pooled)" in k:
                    continue
                pre, rest = k.split("/", 1)
                row = A1_PREFIX[pre]
                stratum = None
                if pre == "P2":
                    rest, stratum = rest.rsplit("/", 1)
                self.a1[(row, rest, stratum)] = (src, k, v)
        # change_log decisions D1 / D6 / D7
        dec = [e for e in pj["change_log"] if e.get("kind", "").startswith("orchestrator decisions")]
        self.decisions = dec[0] if dec else {}
        d7 = self.decisions.get("D7_not_loaded", "")
        m = re.match(r"\s*(\S+) and the group-4 corpora \(([^)]*)\)", d7)
        self.not_loaded = ([m.group(1)] + [x.strip() for x in m.group(2).split(",")]) if m else []
        assert len(self.not_loaded) == 8, f"D7 parse: {self.not_loaded}"
        # Track B units
        self.tb_units = []
        for c, d in TB.items():
            cells = d["cells"]
            first = next(iter(cells.values()))
            if isinstance(first, dict) and "label" not in first:
                for u in first.keys():
                    if u != "all":
                        self.tb_units.append((c, u))
            else:
                self.tb_units.append((c, c))

    def a0_row(self, row, unit, key=None):
        k = key or A0KEY.get(row)
        if k is None:
            return None
        r = self.a0.get((k, unit))
        if r is None:
            return None
        return {"status": r["status"], "deciding_number": r["deciding_number"], "n": r["n"],
                "source": f"analysis/out/phase_e/decision_table.json rows[id={r['id']}]"}


# ============================================================================================================ cells
def cell(label, *, fill, source, unit=None, suffix="", label_E=None, label_B=None, label_BuE=None, precheck=None,
         deciding="", n="", beside=None, **extra):
    c = {"label": label, "base": base_of(label), "suffix": suffix.strip(), "fill_rule_step": fill, "source": source,
         "label_E": label_E, "label_B": label_B, "label_BuE": label_BuE,
         "label_precheck": precheck if precheck is not None else label,
         "deciding_number": deciding, "n": n}
    if unit in TAGS and TAGS[unit] not in c["suffix"]:
        c["suffix"] = (c["suffix"] + f" [{TAGS[unit]}]").strip()
    if beside is not None:
        c["phase_b_beside"] = beside
    c.update(extra)
    c["base_precheck"] = base_of(c["label_precheck"])
    return c


def field_gate(ctx, row, u):
    g = ctx.gate_a[u]
    for key, name in REQ[row]:
        if key == "responses_A":
            v = ctx.n2_A[u]["responses_A"]
            src = f"analysis/out/phase_e/n2.json A_granularity.{u}.responses_A"
        else:
            v = g[key]
            src = f"analysis/prereg_e.json resolved.n6_field_gate_A.{u}.{key}"
        ok = bool(v) if isinstance(v, bool) or v is None else v > 0
        if not ok:
            return {"label": f"NOT_TESTABLE({name})", "check": "A", "field": key, "value": v, "source": src}
    if u in ctx.no_be:
        return {"label": f"NOT_TESTABLE({REQ[row][0][1]}: no B or E session)", "check": "B re-check",
                "field": "sessions", "value": 0,
                "source": "analysis/prereg.json population_B.sessions; n4_n5cg.json n6_cells (no sessions in B or E)"}
    return None


def gate_cell(ctx, row, u, g, item_label=None, beside=None):
    return cell(g["label"], fill=f"field_gate ({g['check']})", source=g["source"], unit=u,
                deciding=f"{g['field']} = {fmt_val(g['value'])}", n="", beside=beside,
                **({"item_label": item_label} if item_label else {}))


# ---------------------------------------------------------------------------------------------------- Probes 1-4
def a1_text(row, v, cand):
    d = v["deciding"]
    if row == "P1_latency":
        fp, auc, G = d["fp_share"], d["auc"], d["G_eligible"]
        txt = (f"fp {fp['num']}/{fp['den']} = {fx(fp['rate'])} [{fx(fp['lo'])}, {fx(fp['verdict_hi'])}], "
               f"{fp['n_sessions']} s; AUC {fx(auc['auc'])} [{fx(auc['lo'])}, {fx(auc['hi'])}]; "
               f"G {G['n']} pairs from {G['sessions']} s")
        n = f"W {fp['den']} pairs from {fp['n_sessions']} s; G {G['n']} from {G['sessions']} s"
    elif row == "P3a_zero_error":
        ze, zb = d["Z_E"], d["Z_BuE"]
        txt = f"E: Z = {wilson_text({'k': ze['k'], 'n': ze['n'], 'p': ze['share'], 'lo': ze['lo'], 'hi': ze['hi']}, 3)}; " \
              f"B u E: Z = {wilson_text({'k': zb['k'], 'n': zb['n'], 'p': zb['share'], 'lo': zb['lo'], 'hi': zb['hi']}, 3)}"
        n = f"{ze['n']} long sessions (E); {zb['n']} (B u E)"
    elif row == "P2_knowledge":
        e, b = d["E_or_B"], d["BuE"]
        txt = (f"{e['deciding_statistic']} {e['k']}/{e['n']} = {fx(e['value'], 3)} [{fx(e['ci'][0], 3)}, "
               f"{fx(e['ci'][1], 3)}], {e['n_sessions']} s; B u E {b['k']}/{b['n']} = {fx(b['value'], 3)}")
        n = f"{e['n']} first-try accesses / first mentions from {e['n_sessions']} s"
    elif row == "P4b_round":
        popk = "BuE" if "BuE" in cand["populations"] else "B"
        rem = cand["populations"][popk]["F3"]["strict"]["remaining"]
        l0 = rem["round"]["last_0"]
        txt = (f"F3 (parameters excluded) {popk.replace('BuE', 'B u E')} {d['F3_label_BuE']}: g "
               f"{fx(d['g_BuE'], 4)} vs g_full "
               f"{fx(d['g_full_BuE'], 4)}; T_orig_noparam last-0 {l0['k']}/{l0['n']} = {fx(l0['rate'])} "
               f"[{fx(l0['lo'])}, {fx(l0['hi'])}]; full statistic on E {d['E_full_label']}")
        n = f"{rem['distinct_values']} distinct non-parameter values from {rem['sessions']} s ({popk})"
    else:
        txt, n = fmt_dict(d), ""
    txt += f". A1 {v['status']}" + (f": {', '.join(v['reasons'])}" if v.get("reasons") else "")
    return txt, n


def a1_cell(ctx, row, u, stratum=None):
    hit = ctx.a1.get((row, u, stratum))
    if hit is None:
        return None
    src, key, v = hit
    D = ctx.D[src]
    cand = D["candidates"][key]
    has_e = bool(cand.get("has_E"))
    e_lab = v.get("E_label")
    pre = e_lab if (has_e and e_lab in LEVEL) else v.get("phase_b")
    if not has_e:
        pre = v.get("BuE_label") or v.get("phase_b")
    txt, n = a1_text(row, v, cand)
    suffix = "" if has_e else "(B only, unreplicated)"
    if not has_e and row == "P2_knowledge":
        pre = cand["populations"]["B"].get("verdict", {}).get("label", pre) if isinstance(
            cand["populations"].get("B"), dict) else pre
    return cell(v["final_label"], fill="a1_final_label", unit=u, suffix=suffix,
                source=f"analysis/out/phase_e/{src}.json verdicts['{key}'] ({v['json_path']})",
                label_E=e_lab, label_B=v.get("phase_b"), label_BuE=v.get("BuE_label") or v.get("BuE_F3_label"),
                precheck=pre, deciding=txt, n=n, a1_status=v["status"], a1_reasons=v.get("reasons", []),
                beside=ctx.a0_row(row, u, "p2_sub" if stratum == "subagent" else None))


def phase_b_cell(ctx, row, u, key=None, corpus=None):
    a0 = ctx.a0_row(row, corpus or u, key)
    lab = a0["status"]
    if lab == "KILLED-in-A1":
        lab = "NOT_TESTABLE"
    if lab == "DEAD (by prereg)":
        lab = "DEAD"
    return cell(lab, fill="phase_b_run_B_only", unit=u, suffix="B only (Phase B run)", source=a0["source"],
                label_B=a0["status"], deciding=a0["deciding_number"], n=a0["n"])


def not_rerun_cell(ctx, row, u, key=None):
    a0 = ctx.a0_row(row, u, key)
    return cell("NOT_RUN(not re-run on E by any Phase E item)", fill="not_rerun_on_E", unit=u,
                source="no Phase E output holds this cell", deciding="", n="", beside=a0)


def fill_probe(ctx, row, u):
    beside = ctx.a0_row(row, u) if not (u == "whowhen" and row in ("P3a_zero_error", "P3b_reaction")) else None
    g = field_gate(ctx, row, u)
    if g:
        c = gate_cell(ctx, row, u, g, beside=beside)
    else:
        c = a1_cell(ctx, row, u, "main" if row == "P2_knowledge" else None)
        if c is None:
            if u in NO_E_UNITS:
                if u == "whowhen" and row in ("P3a_zero_error", "P3b_reaction"):
                    c = phase_b_cell(ctx, row, u, corpus="whowhen/Algorithm-Generated")
                    hc = ctx.a0_row(row, "whowhen/Hand-Crafted")
                    c["substrata"] = {"whowhen/Algorithm-Generated": c["label"],
                                      "whowhen/Hand-Crafted": {"phase_b": hc["status"], "source": hc["source"],
                                                               "n6_reading": "NOT_TESTABLE(error signal): Phase B "
                                                               "fixed it DEAD before running ('no failure signal', "
                                                               "prereg.json probe3.units.dead)"}}
                    c["deciding_number"] = "Algorithm-Generated sub-unit: " + c["deciding_number"]
                else:
                    c = phase_b_cell(ctx, row, u)
            else:
                c = not_rerun_cell(ctx, row, u)
    if row == "P2_knowledge":   # subagent stratum, never pooled with the main thread (prereg.json probe2.stream)
        sub = a1_cell(ctx, row, u, "subagent")
        if sub is None:
            a0s = ctx.a0_row(row, u, "p2_sub")
            if g:
                sub = {"label": c["label"], "fill_rule_step": "field_gate"}
            elif u in NO_E_UNITS:
                sub = phase_b_cell(ctx, row, u, key="p2_sub")
            else:
                sub = cell("NOT_RUN(not re-run on E by any Phase E item)", fill="not_rerun_on_E", unit=u,
                           source="no Phase E output holds this cell", beside=a0s)
        c["strata"] = {"subagent": sub}
    return c


# ---------------------------------------------------------------------------------------------------- R1 (composed)
def n7_leg(ctx, u, split):
    key = f"{u}|{split}|R1_BRACKET"
    v = ctx.D["n7_timing"]["verdicts"]["per_unit_split_detector"].get(key)
    if v is None:
        return None, {"path": f"n7_timing.json verdicts.per_unit_split_detector['{key}']", "present": False}
    sc, dp = v["single_call_types_detecting"], v["detects_or_partial"]
    leg = "ALIVE" if sc else ("WEAK" if dp else "DEAD")
    best = None
    for x in dp:
        if x["label"] == "DETECTS" and x["attack"] in ctx.pj["n7_attack_battery"]["single_call_types"]:
            if best is None or x["recall_lo"] > best["recall_lo"]:
                best = x
    info = {"path": f"analysis/out/phase_e/n7_timing.json verdicts.per_unit_split_detector['{key}']",
            "present": True, "label_counts": v["label_counts"], "single_call_types_detecting": sc,
            "n_detects_or_partial": len(dp), "leg": leg}
    if best is not None:
        cl = ctx.D["n7_timing"]["cells"][best["path"].split("cells.", 1)[1]]
        info["best_single_call_detects"] = {"attack": best["attack"], "param": best["param"],
                                            "recall_k": cl["recall"]["k"], "recall_n": cl["recall"]["n"],
                                            "recall_lo": best["recall_lo"], "fpr_k": cl["fpr"]["k"],
                                            "fpr_n": cl["fpr"]["n"], "fpr_hi": best["fpr_hi"],
                                            "path": "analysis/out/phase_e/n7_timing.json " + best["path"]}
    return leg, info


def fill_r1(ctx, u):
    g = field_gate(ctx, "R1_bracket", u)
    beside = ctx.a0_row("R1_bracket", u)
    if g:
        return gate_cell(ctx, "R1_bracket", u, g, beside=beside)
    f1 = ctx.D["f1"]["r1"][u]
    pooled = f1["verdict"]
    splits = list(f1["verdict_per_split"].keys())
    per = {}
    for s in splits:
        ps = f1["verdict_per_split"][s]
        leg, info = n7_leg(ctx, u, s)
        lab = lowest([ps["ceiling_before_n7"], leg]) if leg else "NOT_RUN(N7 R1_BRACKET cells absent)"
        per[s] = {"label": lab, "ceiling_before_n7": ps["ceiling_before_n7"], "honest_leg": ps["honest_leg"],
                  "honest_bar_hi": ps["honest_bar_hi"], "n7_leg": leg, "n7": info}
    dec_split = "E" if "E" in per else "B"
    cell_lab = lowest([per[dec_split]["label"], pooled["ceiling_after_checks"]])
    if per[dec_split]["label"] not in LEVEL:
        cell_lab = per[dec_split]["label"]
    has_e = "E" in per
    h = f1["honest"]
    hr = h["rate_by_session"]
    b7 = per[dec_split]["n7"].get("best_single_call_detects")
    pool_name = "B u E pooled" if has_e else "B"
    txt = (f"honest ({pool_name}) {h['inconsistent']}/{h['streams']} streams = {fx(hr['rate'], 5)} "
           f"[{fx(hr['lo'], 5)}, {fx(hr['hi'], 5)}], {h['sessions']} s; {dec_split} honest bar hi "
           f"{fx(per[dec_split]['honest_bar_hi'], 5)}; ceiling after checks {pooled['ceiling_after_checks']}; "
           f"N7 on {dec_split}: {len(per[dec_split]['n7']['single_call_types_detecting'])} single-call types DETECTS")
    if b7:
        txt += (f" (best {b7['attack']} {b7['param']}: recall {b7['recall_k']}/{b7['recall_n']}, CI lo "
                f"{fx(b7['recall_lo'])} vs FPR {b7['fpr_k']}/{b7['fpr_n']}, CI hi {fx(b7['fpr_hi'])})")
    n = f"{h['streams']} streams from {h['sessions']} s ({pool_name} honest leg)"
    suffix = "" if has_e else "(B only, unreplicated)"
    if ctx.D["f1"]["step0"]["result"] != "REPRODUCED":
        suffix += " (Step 0 NOT_REPRODUCED)"
    return cell(cell_lab, fill="composed_R1 (f1 honest leg / kill rule / checks + n7_timing N7 leg)", unit=u,
                suffix=suffix, source=f"analysis/out/phase_e/f1_bracket.json r1['{u}'].verdict, "
                                      f".verdict_per_split; analysis/out/phase_e/n7_timing.json verdicts."
                                      f"per_unit_split_detector['{u}|<split>|R1_BRACKET']",
                label_E=per.get("E", {}).get("label"), label_B=per.get("B", {}).get("label"),
                label_BuE=lowest([pooled["ceiling_after_checks"],
                                  per.get("E", per.get("B"))["n7_leg"]]),
                precheck=per[dec_split]["label"], deciding=txt, n=n, beside=beside,
                r1_composition={"f1_pooled": {k: pooled[k] for k in ("label", "ceiling_before_n7",
                                                                     "ceiling_after_checks", "honest_leg",
                                                                     "honest_bar_hi", "checks_effects", "reasons")},
                                "per_split": per,
                                "rule": ctx.pj["a1"]["proposal_rules"]["ALIVE"],
                                "single_call_types": ctx.pj["n7_attack_battery"]["single_call_types"]})


# ---------------------------------------------------------------------------------------------------- R2-R5
def r_n_text(dn, split):
    m = re.search(r"(\d+)/(\d+)", dn or "")
    return f"{m.group(2)} sessions decided ({split})" if m else ""


def fill_r_item(ctx, row, u):
    g = field_gate(ctx, row, u)
    beside = ctx.a0_row(row, u)
    if g:
        return gate_cell(ctx, row, u, g, beside=beside)
    src = "r2_r3" if row in ("R2_image", "R3_git") else "r4_r5"
    cand = {"R2_image": "R2", "R3_git": "R3", "R4_dual": "R4", "R5_ledger": "R5"}[row]
    vs = [v for v in ctx.D[src]["verdicts"]
          if v["candidate"].split("/")[0] == cand and (v["unit"] == u or v["unit"].startswith(u + " "))]
    if not vs:
        return cell("NOT_RUN(no Phase E item measured this unit)", fill="not_run", unit=u,
                    source=f"analysis/out/phase_e/{src}.json verdicts (unit absent)", beside=beside)
    by = {v["split"]: v for v in vs}
    surv = by.get("survival", {})
    lab_E, lab_B, lab_BuE = (by.get(s, {}).get("label") for s in ("E", "B", "BuE"))
    has_e = "E" in by
    if lab_E is not None and lab_E not in ("INSUFFICIENT_N", "NOT_RUN"):
        dec_split, pre = "E", lab_E
    else:
        dec_split, pre = "B", lab_B
    if surv.get("label") in LEVEL:
        lab = surv["label"]
    elif pre in (None, "NOT_RUN"):
        why = "N7 leg absent: n7_content.json computed R5_LEDGER cells for swechat/claude_code only; honest leg " \
              "measured" if row == "R5_ledger" else "no verdict"
        lab = f"NOT_RUN({why})"
        pre = lab
    else:
        lab = pre
    suffix = ""
    if has_e and dec_split == "B" and lab == "INSUFFICIENT_N":
        suffix = "(B only; E INSUFFICIENT_N: NOT_REPLICABLE_AT_N)"
    if not has_e:
        suffix = "(B only, unreplicated)"
    if row in ("R3_git", "R4_dual", "R5_ledger") and has_e:
        suffix = (suffix + " (E not blind)").strip()
    dn = by.get(dec_split, {}).get("deciding_number", "")
    if "BuE" in by:
        dn += f"; B u E: {by['BuE'].get('deciding_number', '')}"
    if surv:
        dn += f". Survival {surv.get('status')}" + (f": {'; '.join(surv.get('reasons') or [])}"
                                                     if surv.get("reasons") else "")
    return cell(lab, fill="item_cell", unit=u, suffix=suffix,
                source=f"analysis/out/phase_e/{src}.json verdicts[candidate {cand}, unit {u}] "
                       f"({surv.get('json_path') or by.get(dec_split, {}).get('json_path')})",
                label_E=lab_E, label_B=lab_B, label_BuE=lab_BuE, precheck=pre, deciding=dn,
                n=r_n_text(by.get(dec_split, {}).get("deciding_number", ""), dec_split), beside=beside,
                survival_status=surv.get("status"))


# ---------------------------------------------------------------------------------------------------- N1-N5
def summary_text(item, blk):
    if blk is None:
        return "", ""
    if item == "n1":
        t = (f"rho_hon {triple(blk['rho_hon'])}; rho_pc {triple(blk['rho_pc'])}; RR {fx(blk['RR'], 3)}; "
             f"honest flag rate {triple(blk['flag_rate'], 4)}")
        return t, f"{blk['residuals']} residuals from {blk['sessions']} s"
    if item == "n2":
        fr = blk.get("flag_rate")
        t = (f"honest flag {int(blk['flag_num'])}/{blk['eligible_responses']} = {triple(fr, 4)}; "
             f"recall(0.8 tau) {fx(blk.get('recall_0.8tau'), 3)}") if fr else blk.get("rule") or ""
        return t, (f"{blk['eligible_responses']} responses from {blk['eligible_sessions']} s"
                   if blk.get("eligible_responses") is not None else "")
    if item == "n3":
        t = (f"pooled rho {triple(blk['rho_pooled'])}; share(rho_s <= 0) {triple(blk['share_rho_s_le_0'])}; "
             f"permutation recall {fx(blk.get('recall_permutation'), 3)}")
        return t, f"{blk['eligible_gaps']} gaps from {blk['eligible_sessions']} s ({blk['n_defined']} with rho_s)"
    return fmt_dict(blk), ""


def fill_n123(ctx, row, u):
    item = {"N1": "n1", "N2": "n2", "N3": "n3"}[row]
    D = ctx.D[item]
    uu = D["units"].get(u)
    g = field_gate(ctx, row, u)
    if row == "N2" and u == "aiv_cu":
        g = None   # S:n2_token_accounting.granularity_check.aiv_cu: per model stratum, the N6 cell names the strata
    item_label = None
    if uu is not None:
        item_label = uu["cell_final"].get("label")
    elif row == "N1" and u in D.get("units_not_in_prereg_list", {}):
        item_label = f"NOT_TESTABLE({D['units_not_in_prereg_list'][u]})"
    if g:
        return gate_cell(ctx, row, u, g, item_label=item_label)
    if row == "N2" and u == "aiv_cu":
        cf = uu["cell_final"]
        strata = cf["by_stratum"]
        bases = {k: base_of(v if not v.startswith("DEAD(") else "DEAD") for k, v in strata.items()}
        cnt = {b: sum(1 for x in bases.values() if x == b) for b in VERDICT}
        lab = "PER_STRATUM(" + ", ".join(f"{b} {cnt[b]}" for b in VERDICT) + ")"
        parts = []
        for k in strata:
            e = D["units"][u]["groups"][k].get("results", {}).get("E") or {}
            fr, rc = e.get("honest_flag_rate"), e.get("recall_tau_prime_0.8")
            parts.append(f"{k.split('/', 1)[1]} {strata[k].split('(')[0]}" +
                         (f" (E honest flag {rate_text(fr)}; recall(0.8 tau) {fx(rc['rate'], 3)})"
                          if isinstance(fr, dict) and isinstance(rc, dict) else ""))
        pg = cf["pooled_aiv_cu_granularity"]
        txt = ("per model stratum: " + "; ".join(parts) +
               f". Pooled aiv_cu not GRANULAR: G1 B {fx(pg['B']['G1_share_both'], 4)}, E "
               f"{fx(pg['E']['G1_share_both'], 4)} (< 0.9)")
        return cell(lab, fill="per_stratum (S:n2_token_accounting.granularity_check.aiv_cu)", unit=u,
                    source="analysis/out/phase_e/n2.json units.aiv_cu.cell_final.by_stratum", precheck=lab,
                    deciding=txt, n=f"{len(strata)} model strata", strata_labels=strata,
                    stratum_counts=cnt)
    if uu is None:
        return cell("NOT_RUN(no Phase E item measured this unit)", fill="not_run", unit=u,
                    source=f"analysis/out/phase_e/{item}.json units (absent)")
    if row == "N2":
        grp = uu["groups"][u]
        cf, cb = grp["cell_final"], grp.get("cell_before_checks") or {}
    else:
        cf, cb = uu["cell_final"], uu.get("cell_before_checks") or {}
    lab = cf["label"]
    if base_of(lab) == "NOT_TESTABLE":
        return cell(lab, fill="item_cell (item field check)", unit=u,
                    source=f"analysis/out/phase_e/{item}.json units.{u}.cell_final")
    sm = D["summary_raw"].get(u, {})
    src_split = "E" if (cb.get("E") and cb.get("E") not in ("INSUFFICIENT_N",) and uu.get("has_E")) else "B"
    blk = sm.get(f"{src_split}.shell") if row == "N1" else sm.get(src_split)
    if row == "N1" and blk is None:
        blk = sm.get(f"{src_split}.shell")
    t, n = summary_text(item, blk)
    return cell(lab, fill="item_cell", unit=u, suffix=cf.get("suffix", ""),
                source=f"analysis/out/phase_e/{item}.json units.{u}" + (".groups." + u if row == "N2" else "") +
                       ".cell_final", label_E=cb.get("E"), label_B=cb.get("B"),
                precheck=cb.get("label", lab), deciding=(f"{src_split}: " + t) if t else "", n=n,
                checks_applied=cf.get("checks_applied", []))


def item_cell_precheck(c_units, row):
    if c_units is None:
        return None
    if "before_checks" in c_units:
        return c_units["before_checks"]
    subs = c_units.get("per_checker") or c_units.get("per_item")
    if subs:
        return lowest([s.get("cell") for s in subs.values() if isinstance(s, dict)]) or c_units.get("label")
    return c_units.get("label")


def n45_n_text(D, u, row, nc):
    """n from the item's result block: rate den / sessions on the source split, else from the deciding dict."""
    dn = nc.get("deciding_number")
    if isinstance(dn, dict) and "n" in dn and "sessions" in dn:
        return f"{dn['n']} from {dn['sessions']} s"
    p = nc.get("deciding_path")
    p0 = p[0] if isinstance(p, list) else p
    if p0:
        if row == "N4":
            blk = resolve(D, p0.rsplit(".delta.", 1)[0]) if ".delta." in p0 else None
            if isinstance(blk, dict) and "k_ge_2" in blk:
                return f"W {blk['pairs']} pairs from {blk['sessions']} s ({blk['k_ge_2']} with k >= 2)"
        if row == "N5g_cold_start" and isinstance(dn, dict) and "sessions" in dn:
            return f"{dn['sessions']} sessions"
        for tail in (".rate.rate", ".share_above"):
            if p0.endswith(tail):
                blk = resolve(D, p0[: -len(tail)])
                if isinstance(blk, dict):
                    r = blk.get("rate") if tail == ".rate.rate" else None
                    if isinstance(r, dict):
                        return f"{int(r['den'])} from {r['n_sessions']} s"
                    if "families_qualifying" in blk:
                        return f"{blk['families_qualifying']} command families"
    if isinstance(dn, dict) and "families_qualifying" in dn:
        return f"{dn['families_qualifying']} command families"
    if isinstance(dn, (int, float)) and not isinstance(dn, bool) and p0:
        return f"{p0.rsplit('.', 1)[1]} {fmt_val(dn)}"
    return ""


def n45_text(D, u, row, nc):
    dn = nc.get("deciding_number")
    p = nc.get("deciding_path")
    p0 = p[0] if isinstance(p, list) else p
    txt = ""
    if isinstance(dn, float) and p0 and p0.endswith(".rate.rate"):
        r = resolve(D, p0[: -len(".rate")])
        txt = rate_text(r) if isinstance(r, dict) else fmt_val(dn)
    elif isinstance(dn, (int, float)) and not isinstance(dn, bool) and p0:
        txt = f"{p0.rsplit('.', 1)[1]} {fmt_val(dn)}"
    elif dn is not None:
        txt = fmt_dict(dn) if isinstance(dn, dict) else fmt_val(dn)
    who = nc.get("deciding_checker") or nc.get("deciding_item")
    if who:
        txt = f"{who}: {txt}"
    if nc.get("per_checker_final"):
        txt += " (per checker: " + ", ".join(f"{k} {v}" for k, v in nc["per_checker_final"].items()) + ")"
    if nc.get("per_item_final"):
        txt += " (per sub-item: " + ", ".join(f"{k} {v}" for k, v in nc["per_item_final"].items()) + ")"
    sp = nc.get("source_split")
    if sp is None and p0:
        m = re.search(r"\.(B|E)\.", p0)
        sp = m.group(1) if m else None
    return (f"{sp}: " + txt) if sp and txt else txt


def fill_n45(ctx, row, u):
    src = "n4_n5cg" if row in ("N4", "N5c_truncation", "N5g_cold_start") else "n5_battery"
    D = ctx.D[src]
    nc = D["n6_cells"].get(u, {}).get(row)
    g = field_gate(ctx, row, u)
    item_label = nc.get("label") if nc else None
    if g:
        return gate_cell(ctx, row, u, g, item_label=item_label)
    if nc is None:
        return cell("NOT_RUN(no Phase E item measured this unit)", fill="not_run", unit=u,
                    source=f"analysis/out/phase_e/{src}.json n6_cells (absent)")
    lab = nc["label"]
    if base_of(lab) == "NOT_TESTABLE":
        return cell(lab, fill="item_cell (item field check)", unit=u,
                    source=f"analysis/out/phase_e/{src}.json n6_cells['{u}']['{row}']")
    cu = D["units"].get(u, {}).get("cells", {}).get(row)
    pre = item_cell_precheck(cu, row) or lab
    return cell(lab, fill="item_cell", unit=u, suffix=nc.get("suffix", ""),
                source=f"analysis/out/phase_e/{src}.json n6_cells['{u}']['{row}']",
                label_E=nc.get("E") or (cu or {}).get("E"), label_B=nc.get("B") or (cu or {}).get("B"),
                precheck=pre, deciding=n45_text(D, u, row, nc), n=n45_n_text(D, u, row, nc),
                checks_applied=nc.get("checks_applied", []))


# ---------------------------------------------------------------------------------------------------- Track B
def split_labels_tb(c):
    out = {}
    for s in ("B", "E", "BuE"):
        v = c.get(f"label_{s}")
        if v is None and isinstance(c.get("by_split"), dict):
            v = c["by_split"].get(s)
            if isinstance(v, dict):
                v = v.get("label")
        out[s] = v
    return out


def fill_tb(ctx, corpus, unit, row):
    d = ctx.TB[corpus]
    cells = d["cells"]
    raw = cells.get(row)
    nested = raw is not None and "label" not in raw
    if nested:
        raw = raw.get(unit)
    if raw is None:
        return cell("NOT_RUN(row absent from the corpus output)", fill="not_run", unit=unit,
                    source=f"{TRACK_B_FILES[corpus]} cells (row absent)")
    lab_full = raw["label"]
    b = base_of(lab_full)
    if b in ("NOT_TESTABLE", "NOT_RUN"):
        lab, suffix = lab_full, ""
    else:
        lab, suffix = b, lab_full[len(b):].strip()
    sl = split_labels_tb(raw)
    pre = raw.get("split_label_before_checks")
    if pre is None:
        pre = sl["E"] if sl["E"] in LEVEL else (sl["B"] if sl["B"] in LEVEL else lab)
    extra_sfx = []
    for k in ("suffixes", "flags"):
        for x in raw.get(k) or []:
            if isinstance(x, str) and x not in suffix:
                extra_sfx.append(x)
    if isinstance(raw.get("blind"), str) and "NOT_BLIND" in raw["blind"] and "NOT_BLIND" not in suffix:
        extra_sfx.append("NOT_BLIND (D6)")
    suffix = " ".join([suffix] + [f"[{x}]" for x in extra_sfx]).strip()
    dn = raw.get("deciding_number")
    txt = fmt_dict(dn) if isinstance(dn, dict) else ("" if dn is None else fmt_val(dn))
    if raw.get("ci") is not None:
        txt += f"; CI {fmt_val(raw['ci'])}"
    n = ""
    if raw.get("n") is not None:
        n = f"{raw['n']}" + (f" from {raw['sessions']} s" if raw.get("sessions") is not None else "")
    extra = {}
    if row == "P2_knowledge":
        sub = cells.get("P2_knowledge_subagent")
        if sub is not None and "label" not in sub:
            sub = sub.get(unit)
        if sub is not None:
            extra["strata"] = {"subagent": {"label": sub["label"], "source": f"{TRACK_B_FILES[corpus]} "
                                                                             "cells.P2_knowledge_subagent"}}
        elif isinstance(raw.get("subagent_stratum"), dict):
            extra["strata"] = {"subagent": {"label": raw["subagent_stratum"].get("E") or
                                            raw["subagent_stratum"].get("B"),
                                            "by_split": raw["subagent_stratum"],
                                            "source": f"{TRACK_B_FILES[corpus]} cells.P2_knowledge.subagent_stratum"}}
    return cell(lab, fill="item_cell (Track B corpus measurement)", unit=unit, suffix=suffix,
                source=f"{TRACK_B_FILES[corpus]} cells['{row}']" + (f"['{unit}']" if nested else "") +
                       (f" ({raw.get('json_path')})" if raw.get("json_path") else ""),
                label_E=sl["E"], label_B=sl["B"], label_BuE=sl["BuE"], precheck=pre, deciding=txt, n=n, **extra)


# ============================================================================================================ grid
def build_grid(ctx):
    grid = {}
    for row in ctx.rows:
        grid[row] = {}
        for u in ctx.units_b:
            if row.startswith("P"):
                c = fill_probe(ctx, row, u)
            elif row == "R1_bracket":
                c = fill_r1(ctx, u)
            elif row.startswith("R"):
                c = fill_r_item(ctx, row, u)
            elif row in ("N1", "N2", "N3"):
                c = fill_n123(ctx, row, u)
            else:
                c = fill_n45(ctx, row, u)
            grid[row][u] = c
        for corpus, unit in ctx.tb_units:
            grid[row][unit] = fill_tb(ctx, corpus, unit, row)
        for corpus in ctx.not_loaded:
            grid[row][corpus] = cell("NOT_RUN(not loaded: time budget)", fill="not_loaded",
                                     source="analysis/prereg_e.json change_log D7_not_loaded",
                                     deciding="", n="")
    return grid


# ============================================================================================================ transfer
def transfer_block(grid, rows, cols, key="base", stratum=None, override=None):
    out = {}
    for row in rows:
        labs = {}
        for c in cols:
            cl = grid[row][c]
            if stratum:
                s = (cl.get("strata") or {}).get(stratum)
                lab = base_of(s["label"]) if s and s.get("label") else None
            else:
                lab = cl[key]
            if override and (row, c) in override:
                lab = override[(row, c)]
            labs[c] = lab
        cnt = {b: sorted(c for c, l in labs.items() if l == b) for b in BASES}
        dec = sorted(c for c, l in labs.items() if l in VERDICT)
        pairs = list(combinations(dec, 2))
        tr = [(a, b) for a, b in pairs if LEVEL[labs[a]] >= 1 and LEVEL[labs[b]] >= 1]
        fl = [(a, b) for a, b in pairs if {labs[a], labs[b]} == {"ALIVE", "DEAD"}]
        wd = [(a, b) for a, b in pairs if {labs[a], labs[b]} == {"WEAK", "DEAD"}]
        dd = [(a, b) for a, b in pairs if labs[a] == "DEAD" and labs[b] == "DEAD"]
        out[row] = {
            "columns": len(cols),
            "testable_field_gate": len(cols) - len(cnt["NOT_TESTABLE"]) - sum(
                1 for c in cnt["NOT_RUN"] if "not loaded" in (grid[row][c]["label"] or "")),
            "decided": len(dec),
            **{f"n_{b}": len(cnt[b]) for b in BASES},
            "cells_by_label": {b: v for b, v in cnt.items() if v},
            "pairs_decided": len(pairs), "transfer_pairs": len(tr), "failing_pairs": len(fl),
            "weak_dead_pairs": len(wd), "dead_dead_pairs": len(dd),
            "transfer_pair_list": [list(p) for p in tr], "failing_pair_list": [list(p) for p in fl],
            "statement": ("FAILS TO TRANSFER in >= 1 pair" if fl else
                          ("TRANSFERS in every decided pair" if pairs and len(tr) == len(pairs) else
                           ("no decided pair" if not pairs else "no failing pair; not every pair transfers"))),
        }
    tot = {k: sum(v[k] for v in out.values()) for k in ("pairs_decided", "transfer_pairs", "failing_pairs",
                                                       "weak_dead_pairs", "dead_dead_pairs", "decided",
                                                       "testable_field_gate", "n_ALIVE", "n_WEAK", "n_DEAD",
                                                       "n_INSUFFICIENT_N", "n_INCONCLUSIVE", "n_NOT_TESTABLE",
                                                       "n_NOT_RUN", "n_PER_STRATUM")}
    tot["rows"] = len(out)
    tot["rows_with_failing_pair"] = sum(1 for v in out.values() if v["failing_pairs"])
    tot["rows_with_decided_pair"] = sum(1 for v in out.values() if v["pairs_decided"])
    tot["rows_all_decided_pairs_transfer"] = sum(1 for v in out.values()
                                                 if v["pairs_decided"] and v["transfer_pairs"] == v["pairs_decided"])
    tot["rows_alive_in_ge2_units"] = sum(1 for v in out.values() if v["n_ALIVE"] >= 2)
    tot["rows_ge_weak_in_ge2_units"] = sum(1 for v in out.values() if v["n_ALIVE"] + v["n_WEAK"] >= 2)
    tot["rows_no_cell_ge_weak"] = sum(1 for v in out.values() if v["n_ALIVE"] + v["n_WEAK"] == 0)
    tot["cells"] = tot["rows"] * (len(cols))
    tot["pairs_neither"] = tot["weak_dead_pairs"] + tot["dead_dead_pairs"]
    top = max(out.items(), key=lambda kv: kv[1]["transfer_pairs"]) if out else (None, {"transfer_pairs": 0})
    tot["top_transfer_row"] = top[0]
    tot["top_transfer_row_pairs"] = top[1]["transfer_pairs"]
    tot["failing_pairs_all"] = [[r] + p for r, v in out.items() for p in v["failing_pair_list"]]
    return {"per_row": out, "totals": tot}


def per_column(grid, rows, cols):
    return {c: {b: sum(1 for r in rows if grid[r][c]["base"] == b) for b in BASES} for c in cols}


# ============================================================================================================ A0 diff
def a0_norm(status):
    if status is None:
        return None
    if status == "KILLED-in-A1":
        return "NOT_TESTABLE"
    if status.startswith("EXPLORATORY"):
        return "EXPLORATORY"
    if status.startswith("GATE"):
        return status
    return base_of(status) if not status.startswith("DEAD (by prereg)") else "DEAD (by prereg)"


def update_kinds(ctx, grid):
    kinds = {}
    for row in ctx.rows:
        for col, c in grid[row].items():
            if c["fill_rule_step"] == "not_loaded":
                k = "not_loaded"
            elif col not in ctx.units_b:
                k = "new_column"
            elif row not in A0KEY:
                k = "new_row"
            elif c["fill_rule_step"] == "not_rerun_on_E":
                k = "not_rerun_phase_b_stands"
            else:
                a0 = ctx.a0_row(row, col) if not (col == "whowhen" and row in ("P3a_zero_error", "P3b_reaction")) \
                    else ctx.a0_row(row, "whowhen/Algorithm-Generated")
                a0s = a0_norm(a0["status"]) if a0 else None
                if a0s != c["base"]:
                    k = "changed"
                elif c["fill_rule_step"].startswith(("a1_final", "item_cell", "composed")):
                    k = "remeasured_same_label"
                else:
                    k = "unchanged"
            c["update_kind"] = k
            if col in ctx.units_b and row in A0KEY:
                a0 = c.get("phase_b_beside") or ctx.a0_row(row, col) or (
                    ctx.a0_row(row, "whowhen/Algorithm-Generated") if col == "whowhen" else None)
                c["a0_status"] = a0["status"] if a0 else None
            kinds.setdefault(k, 0)
            kinds[k] += 1
    return kinds


# ============================================================================================================ numbers check
NUM_RX = re.compile(r"(?<![A-Za-z0-9_.])-?\d[\d,]*(?:\.\d+)?(?:e-?\d+)?(?![A-Za-z0-9_])")


def num_tokens(text):
    out = set()
    for t in NUM_RX.findall(text):
        t = t.replace(",", "")
        out.add(t)
    return out


def json_tokens(obj):
    txt = json.dumps(obj, ensure_ascii=False)
    toks = num_tokens(txt)
    # also every string value's numbers (json.dumps escapes do not hide digits) and ints formatted plainly
    return toks


def check_numbers(md_text, js_tokens):
    missing = sorted(t for t in num_tokens(md_text) if t not in js_tokens and t.lstrip("-") not in js_tokens)
    return missing


# ============================================================================================================ render
CODE = {"ALIVE": "ALIVE", "WEAK": "WEAK", "DEAD": "DEAD", "INSUFFICIENT_N": "ins-n", "INCONCLUSIVE": "INCONC",
        "NOT_TESTABLE": "n/t", "NOT_RUN": "n/r", "PER_STRATUM": "strata"}


def short(c):
    s = CODE[c["base"]]
    sfx = c.get("suffix") or ""
    marks = ""
    if "B only" in sfx:
        marks += "ᴮ"
    if "not blind" in sfx.lower() or "NOT_BLIND" in sfx:
        marks += "*"
    if c["base"] == "PER_STRATUM":
        cnt = c.get("stratum_counts", {})
        s = f"strata {cnt.get('ALIVE', 0)}A/{cnt.get('WEAK', 0)}W/{cnt.get('DEAD', 0)}D"
    if c["base"] in VERDICT and c.get("label_precheck") and c["label_precheck"] in LEVEL and \
            c["label_precheck"] != c["base"]:
        marks += "↓"
    return s + marks


def interp_change(c, row):
    """INTERPRETATION column for the decision table (templated; not data)."""
    b = c["base"]
    if b == "NOT_TESTABLE":
        return "The record lacks a required field; only a re-export that carries it would make this cell testable."
    if b == "NOT_RUN":
        if c["fill_rule_step"] == "not_rerun_on_E":
            return ("Not re-run on E in Phase E; running the frozen Phase B code on E would fill it. The Phase B "
                    "verdict stands for split B only.")
        if c["fill_rule_step"] == "not_loaded":
            return "Corpus acquired but not loaded (time budget); loading it under its own A calibration would fill it."
        return "Not computed in Phase E (see the label); computing the missing leg under the frozen rule would fill it."
    if b == "INSUFFICIENT_N":
        return "Below the pre-registered minimum n; more sessions of this unit would let the frozen rule decide."
    if b == "PER_STRATUM":
        return ("Decided per model stratum by the prereg; a single unit label would need a pooling rule that was not "
                "pre-registered.")
    pre = c.get("label_precheck")
    down = pre in LEVEL and pre != b
    syn = (" No corpus holds a known real fabricated result: recall here comes from synthetic tampering, and "
           "honest-baseline rates are not detections.")
    if b == "ALIVE":
        return ("Passed its rule and every artifact check here; a DEAD result on held-out H or a dominance failure on "
                "more data would lower it." + syn)
    if b == "WEAK":
        return (("Lowered from " + pre + " by an artifact check, kill test or cap; " if down else
                 "Meets the WEAK bar only; ") + "no post-hoc rescue can raise it, only a fresh pre-registered run." +
                syn)
    if b == "DEAD":
        return (("Lowered from " + pre + " by an artifact check or kill test; " if down else
                 "Fails its pre-registered rule on this unit; ") +
                "only a changed record or a newly pre-registered rule could revive it here.")
    return ""


def corpus_label(col, c):
    tag = {"cc_local": " (private: aggregates only)", "aiv_cc": " (one agent: case study)"}.get(col, "")
    return col + tag


def status_text(c):
    s = f"**{c['base']}**" if c["base"] in VERDICT else c["label"]
    if c["base"] == "PER_STRATUM":
        s = c["label"]
    if c["base"] in VERDICT and c["label"] != c["base"]:
        s += " " + c["label"][len(c["base"]):]
    if c.get("suffix"):
        s += " " + c["suffix"]
    return s.replace("|", "/")


def md_cell_text(x):
    return (x or "").replace("|", "/").replace("\n", " ")


def render_transfer_md(G):
    L = []
    rows, cols = G["rows"], G["columns_loaded"]
    T, Tb = G["transfer"]["primary"], G["transfer"]["phase_b_units_only"]
    L += ["# Transfer matrix: every mechanism × every corpus (Phase E, N6)", "",
          f"Built by `python -m analysis.probes.phase_e_n6` (`{G['script']}`) from committed Phase B and Phase E "
          f"outputs only (assembly: no cache, raw source or split was opened). Every cell, its source path, its B / E / "
          f"pre-check labels and its deciding number are in `analysis/out/phase_e/n6_grid.json` "
          f"(`cells.<row>.<column>`). The script checks that every number in this file occurs in that JSON. "
          f"Pre-registration: `analysis/PREREG_E.md` section 3, `prereg_e.json` `n6_transfer_grid`.", "",
          "- **Cell vocabulary** (prereg): ALIVE, WEAK, DEAD, INSUFFICIENT_N (ins-n), INCONCLUSIVE, "
          "NOT_TESTABLE(<missing field>) (n/t), NOT_RUN(<reason>) (n/r). One added reading: `strata` = the N2 aiv_cu "
          "cell, which the prereg decides per model stratum (A/W/D = strata ALIVE/WEAK/DEAD).",
          "- **Marks.** ᴮ = B only (unit has no E, or E was INSUFFICIENT_N); * = not blind (R3–R5 'E not blind'; "
          "Track B corpora 'NOT_BLIND', change_log D6); ↓ = the label after the pre-registered artifact checks / "
          "kill tests is lower than the rule's own E (or B) verdict.",
          "- **Fill rule.** Field gate first; then the E verdict where the unit has E (B where E is INSUFFICIENT_N or "
          "absent). Probes 1–4: an A1 candidate's final label where one exists, the Phase B verdict for units "
          "without E ('B only (Phase B run)'), and NOT_RUN where the unit has E but no Phase E item re-ran it (the "
          "Phase B verdict is beside it in the JSON, never in it). R1 is composed here from f1_bracket.json and "
          "n7_timing.json (see deviations in the JSON).",
          "- **Every positive in this grid is a synthetic tamper or an honest-baseline rate.** No corpus contains a "
          "known real fabricated tool result.", ""]
    L += ["## Grid", ""]
    hdr = "| Mechanism | " + " | ".join(cols) + " |"
    L += [hdr, "|---|" + "---|" * len(cols)]
    for r in rows:
        L.append(f"| {NAMES[r]} | " + " | ".join(short(G["cells"][r][c]) for c in cols) + " |")
    L += ["", f"Not loaded (change_log D7, time budget): {', '.join(G['columns_not_loaded'])}. "
              f"All {len(rows)} cells of each of these {len(G['columns_not_loaded'])} columns are NOT_RUN(not loaded) "
              f"and are left out of every count below.", ""]
    L += ["## Transfer statement, evaluated mechanically", "",
          f"Rule (prereg): a mechanism TRANSFERS between two testable units if both cells are ≥ WEAK; it FAILS TO "
          f"TRANSFER if one is ALIVE and the other DEAD. Pairs are formed among the decided cells (ALIVE / WEAK / DEAD) "
          f"of the {len(cols)} loaded columns. 'Testable' = passed the field gate (NOT_RUN cells that passed it count "
          f"as testable but undecided).", "",
          "| Mechanism | testable | decided | ALIVE | WEAK | DEAD | ins-n | n/r | n/t | decided pairs | TRANSFER pairs "
          "| FAIL pairs (ALIVE–DEAD) | WEAK–DEAD | DEAD–DEAD | statement |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        v = T["per_row"][r]
        L.append(f"| {NAMES[r]} | {v['testable_field_gate']} | {v['decided']} | {v['n_ALIVE']} | {v['n_WEAK']} | "
                 f"{v['n_DEAD']} | {v['n_INSUFFICIENT_N']} | {v['n_NOT_RUN']} | {v['n_NOT_TESTABLE']} | "
                 f"{v['pairs_decided']} | {v['transfer_pairs']} | {v['failing_pairs']} | {v['weak_dead_pairs']} | "
                 f"{v['dead_dead_pairs']} | {v['statement']} |")
    t = T["totals"]
    L += ["", "**Totals over the grid** "
              f"({t['rows']} mechanisms × {len(cols)} loaded columns = {t['cells']} cells): "
              f"testable {t['testable_field_gate']}, decided {t['decided']} (ALIVE {t['n_ALIVE']}, WEAK {t['n_WEAK']}, "
              f"DEAD {t['n_DEAD']}), INSUFFICIENT_N {t['n_INSUFFICIENT_N']}, INCONCLUSIVE {t['n_INCONCLUSIVE']}, "
              f"NOT_RUN {t['n_NOT_RUN']}, NOT_TESTABLE {t['n_NOT_TESTABLE']}, per-stratum {t['n_PER_STRATUM']}. "
              f"Decided pairs {t['pairs_decided']}: TRANSFER {t['transfer_pairs']}, FAIL TO TRANSFER "
              f"{t['failing_pairs']}, WEAK–DEAD {t['weak_dead_pairs']}, DEAD–DEAD {t['dead_dead_pairs']}.", "",
          f"- Mechanisms with at least one decided pair: {t['rows_with_decided_pair']} of {t['rows']}.",
          f"- Mechanisms that FAIL TO TRANSFER in at least one pair: {t['rows_with_failing_pair']}.",
          f"- Mechanisms whose every decided pair TRANSFERS: {t['rows_all_decided_pairs_transfer']}.",
          f"- Mechanisms ALIVE in ≥ 2 units: {t['rows_alive_in_ge2_units']}; ≥ WEAK in ≥ 2 units: "
          f"{t['rows_ge_weak_in_ge2_units']}; no cell ≥ WEAK anywhere: {t['rows_no_cell_ge_weak']}.", ""]
    L += ["### Failing pairs (one ALIVE, one DEAD)", ""]
    any_f = False
    for r in rows:
        v = T["per_row"][r]
        if v["failing_pair_list"]:
            any_f = True
            L.append(f"- {NAMES[r]}: " + "; ".join(f"{a} ({G['cells'][r][a]['base']}) vs {b} "
                                                   f"({G['cells'][r][b]['base']})" for a, b in v["failing_pair_list"]))
    if not any_f:
        L.append("- none")
    L += ["", "### Transferring pairs (both ≥ WEAK)", ""]
    for r in rows:
        v = T["per_row"][r]
        if v["transfer_pair_list"]:
            L.append(f"- {NAMES[r]}: " + "; ".join(f"{a} – {b}" for a, b in v["transfer_pair_list"]))
    L += ["", "## Sensitivity readings (same rule, different inputs; none is the grid)", ""]
    S = G["transfer"]
    for k, title in (("phase_b_units_only", "The 11 Phase B units only (Track B columns left out)"),
                     ("precheck_labels", "Labels before artifact checks / kill tests (the rule's own E-or-B verdict)"),
                     ("n2_aiv_cu_best_stratum", "N2 aiv_cu read as its best stratum (ALIVE)"),
                     ("n2_aiv_cu_worst_stratum", "N2 aiv_cu read as its worst stratum (DEAD)"),
                     ("p2_subagent_stratum", "Probe 2 subagent stratum in place of the main thread")):
        tt = S[k]["totals"]
        L.append(f"- **{title}.** decided {tt['decided']} (ALIVE {tt['n_ALIVE']}, WEAK {tt['n_WEAK']}, DEAD "
                 f"{tt['n_DEAD']}); decided pairs {tt['pairs_decided']}: TRANSFER {tt['transfer_pairs']}, FAIL "
                 f"{tt['failing_pairs']}; mechanisms with a failing pair {tt['rows_with_failing_pair']}.")
    L += ["", "## Per-column counts", "",
          "| Column | ALIVE | WEAK | DEAD | ins-n | INCONC | n/r | n/t | strata |", "|---|---|---|---|---|---|---|---|---|"]
    for c in cols:
        v = G["per_column"][c]
        L.append(f"| {c} | {v['ALIVE']} | {v['WEAK']} | {v['DEAD']} | {v['INSUFFICIENT_N']} | {v['INCONCLUSIVE']} | "
                 f"{v['NOT_RUN']} | {v['NOT_TESTABLE']} | {v['PER_STRATUM']} |")
    L += ["", "## Where nothing is decided, plainly", ""]
    nod = [c for c in cols if sum(G["per_column"][c][b] for b in VERDICT) == 0]
    L.append(f"- Loaded columns with no decided cell at all: {', '.join(nod) if nod else 'none'}.")
    noweak = [c for c in cols if G["per_column"][c]["ALIVE"] + G["per_column"][c]["WEAK"] == 0 and c not in nod]
    L.append(f"- Columns with decided cells but none ≥ WEAK: {', '.join(noweak) if noweak else 'none'}.")
    deadrows = [NAMES[r] for r in rows if T["per_row"][r]["n_ALIVE"] + T["per_row"][r]["n_WEAK"] == 0]
    L.append(f"- Mechanisms with no cell ≥ WEAK in any loaded column: {'; '.join(deadrows) if deadrows else 'none'}.")
    nr = T["totals"]["n_NOT_RUN"]
    L.append(f"- {nr} loaded cells are NOT_RUN: the field gate passed but no Phase E item produced a verdict "
             f"(mostly Probes 1–4 on units with E that no A1 candidate covered). They are not nulls.")
    L += ["", "## INTERPRETATION (not data)", "",
          G["interpretation_transfer_md"], ""]
    L += ["## Sources", ""] + [f"- `{k}` sha256 `{v[:16]}…`" for k, v in sorted(G["inputs_sha256"].items())]
    return "\r\n".join(L) + "\r\n"


def render_decision_md(G, ctx):
    rows, cols = G["rows"], G["columns_loaded"]
    L = [DT_MARKER + " (N6 transfer grid; appended by `analysis/probes/phase_e_n6.py`)", "",
         "This section is appended to the A0 table above, which is unchanged. Every row below is a mechanism × corpus "
         "cell of `analysis/out/phase_e/n6_grid.json` that is new in Phase E or whose label or deciding number changed: "
         "new mechanisms (N1–N5), the five Phase D proposals now under a pre-registered rule (R1–R5), A1 re-measures, "
         "and the Track B corpora. The status is the N6 cell (the E verdict where the unit has E; label after the "
         "pre-registered artifact checks / kill tests); 'A0:' names the A0 status it replaces. Every number in this "
         "section occurs in n6_grid.json (checked by the script). The last column is INTERPRETATION, templated, "
         "not data.", "",
         f"Counts of the grid cells by update kind: " + ", ".join(f"{k} {v}" for k, v in
                                                                  sorted(G["update_kind_counts"].items())) + ".", ""]
    hdr = ["| Mechanism | Corpus | ALIVE / WEAK / DEAD | Deciding number | n | What would change this (INTERPRETATION) |",
           "|---|---|---|---|---|---|"]

    def rowline(r, c, cl):
        dn = md_cell_text(cl["deciding_number"])
        if cl.get("a0_status") and cl["update_kind"] == "changed":
            dn = (dn + "; " if dn else "") + f"A0: {cl['a0_status']}"
        if cl.get("strata", {}).get("subagent", {}).get("label") and r == "P2_knowledge":
            dn += f"; subagent stratum: {cl['strata']['subagent']['label']}"
        if cl.get("item_label") and cl["base"] == "NOT_TESTABLE":
            dn += f" (item's own label: {cl['item_label']})"
        return (f"| {NAMES[r]} | {corpus_label(c, cl)} | {status_text(cl)} | {dn} | {md_cell_text(cl['n'])} | "
                f"{interp_change(cl, r)} |")

    groups = {"v": [], "i": [], "x": []}
    for r in rows:
        for c in cols:
            cl = G["cells"][r][c]
            if cl["update_kind"] not in ("new_row", "new_column", "changed", "remeasured_same_label"):
                continue
            g = "v" if cl["base"] in VERDICT + ("INCONCLUSIVE", "PER_STRATUM") else (
                "i" if cl["base"] == "INSUFFICIENT_N" else "x")
            groups[g].append(rowline(r, c, cl))
    L += ["### Cells with a verdict (ALIVE / WEAK / DEAD / INCONCLUSIVE / per stratum)", ""] + hdr + groups["v"]
    L += ["", "### INSUFFICIENT_N cells", ""] + hdr + groups["i"]
    L += ["", "### NOT_TESTABLE and NOT_RUN cells (new or changed)", ""] + hdr + groups["x"]
    nr = [(r, c) for r in rows for c in cols if G["cells"][r][c]["update_kind"] == "not_rerun_phase_b_stands"]
    L += ["", "### Probe 1–4 cells not re-run on E (the A0 Phase B verdict above still stands, for B only)", "",
          f"{len(nr)} cells: " + "; ".join(f"{NAMES[r]} × {c} (A0 {G['cells'][r][c].get('a0_status')})"
                                           for r, c in nr) + ". In the N6 grid they are NOT_RUN(not re-run on E).", ""]
    L += ["### Track B corpora acquired but not loaded", "",
          "| Mechanism | Corpus | ALIVE / WEAK / DEAD | Deciding number | n | What would change this (INTERPRETATION) |",
          "|---|---|---|---|---|---|"]
    for c in G["columns_not_loaded"]:
        L.append(f"| all {len(rows)} N6 rows | {c} | NOT_RUN(not loaded: time budget) | change_log D7 |  | "
                 f"Loading it under its own A calibration would fill these cells. |")
    t = G["transfer"]["primary"]["totals"]
    L += ["", "### Phase E strongest finding and transfer (INTERPRETATION, three sentences)", "",
          G["interpretation_decision_md"], ""]
    return "\r\n".join(L) + "\r\n"


# ============================================================================================================ main
def interpretation_texts(G):
    """Short interpretation paragraphs; numbers are taken from G only (checked against the JSON afterwards)."""
    T = G["transfer"]["primary"]["totals"]
    P = G["transfer"]["precheck_labels"]["totals"]
    rows = G["rows"]
    alive = [(r, c) for r in rows for c in G["columns_loaded"] if G["cells"][r][c]["base"] == "ALIVE"]
    alive_txt = "; ".join(f"{NAMES[r]} in {c}" for r, c in alive)
    fails = T["failing_pairs_all"]
    fail_txt = "; ".join(f"{NAMES[r]}: {a} {G['cells'][r][a]['base']} vs {b} {G['cells'][r][b]['base']}"
                         for r, a, b in fails) or "none"
    tr = (f"A failure to transfer needs an ALIVE cell opposite a DEAD one, and ALIVE cells are rare ({T['n_ALIVE']} "
          f"of {T['decided']} decided cells), so only {T['failing_pairs']} of {T['pairs_decided']} decided pairs fails "
          f"to transfer ({fail_txt}). {T['transfer_pairs']} pairs transfer (both >= WEAK), "
          f"{T['top_transfer_row_pairs']} of them from {NAMES[T['top_transfer_row']]} alone; the other "
          f"{T['pairs_neither']} are WEAK–DEAD ({T['weak_dead_pairs']}) or DEAD–DEAD ({T['dead_dead_pairs']}), which "
          f"the pre-registered statement counts as neither. {T['rows_with_failing_pair']} of {T['rows']} mechanisms "
          f"{'fails' if T['rows_with_failing_pair'] == 1 else 'fail'} to transfer in at least one pair, "
          f"{T['rows_alive_in_ge2_units']} "
          f"are ALIVE in two or more units, and {T['rows_no_cell_ge_weak']} have no cell at WEAK or better anywhere. "
          f"The artifact checks and kill tests matter: before them the same cells hold {P['n_ALIVE']} ALIVE, after "
          f"them {T['n_ALIVE']}. Most of the grid cannot be decided at all: {T['n_NOT_TESTABLE']} NOT_TESTABLE, "
          f"{T['n_NOT_RUN']} NOT_RUN and {T['n_INSUFFICIENT_N']} INSUFFICIENT_N of {T['cells']} loaded cells. Read "
          f"strictly, the grid does not show widespread failure to transfer; it shows that strong signals are confined "
          f"to one or two units per mechanism and that most mechanism × corpus cells are undecidable or at most WEAK. "
          f"ALIVE cells ({len(alive)}): {alive_txt}.")
    dm = (f"1. Phase E leaves {len(alive)} ALIVE cells in the {T['rows']} × {len(G['columns_loaded'])} loaded grid "
          f"({alive_txt}); none is a detection of a real fabrication (recall comes from synthetic tampering, and "
          f"Probes 3a and 4b are honest-baseline rates). "
          f"2. Under the pre-registered transfer statement {T['failing_pairs']} of {T['pairs_decided']} decided pairs "
          f"fails to transfer ({fail_txt}), {T['transfer_pairs']} transfer and {T['pairs_neither']} are WEAK–DEAD or "
          f"DEAD–DEAD, so the strict claim that signals do not transfer is not supported; what the grid supports is "
          f"that ALIVE signals stay inside one or two units per mechanism. "
          f"3. Coverage still bounds everything: {T['n_NOT_TESTABLE']} of {T['cells']} loaded cells are NOT_TESTABLE, "
          f"{T['n_NOT_RUN']} NOT_RUN and {T['n_INSUFFICIENT_N']} INSUFFICIENT_N, and the "
          f"{G['n_columns_not_loaded']} acquired-but-not-loaded corpora add {G['n_cells_not_loaded']} NOT_RUN cells.")
    return tr, dm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", nargs="*", help="check that every number in these files occurs in n6_grid.json")
    a = ap.parse_args()
    if a.check is not None:
        G = json.loads(OUT.read_text(encoding="utf-8"))
        toks = json_tokens(G)
        bad = 0
        for f in a.check:
            miss = check_numbers(Path(f).read_text(encoding="utf-8"), toks)
            print(f"{f}: {len(miss)} numbers not in n6_grid.json" + (f": {miss}" if miss else ""))
            bad += len(miss)
        sys.exit(1 if bad else 0)

    pj, D, TB, H = load_inputs()
    ctx = Ctx(pj, D, TB)
    grid = build_grid(ctx)
    cols_loaded = ctx.units_b + [u for _, u in ctx.tb_units]
    kinds = update_kinds(ctx, grid)

    # transfer: primary and sensitivity readings
    rows = ctx.rows
    prim = transfer_block(grid, rows, cols_loaded)
    pbo = transfer_block(grid, rows, ctx.units_b)
    pre = transfer_block(grid, rows, cols_loaded, key="base_precheck")
    ov_best = {("N2", "aiv_cu"): "ALIVE"}
    ov_worst = {("N2", "aiv_cu"): "DEAD"}
    best = transfer_block(grid, rows, cols_loaded, override=ov_best)
    worst = transfer_block(grid, rows, cols_loaded, override=ov_worst)
    p2s = transfer_block(grid, ["P2_knowledge"], cols_loaded, stratum="subagent")
    # p2 subagent sensitivity on the whole grid: replace the P2 row by its subagent stratum
    ov_p2 = {}
    for c in cols_loaded:
        s = (grid["P2_knowledge"][c].get("strata") or {}).get("subagent")
        ov_p2[("P2_knowledge", c)] = base_of(s["label"]) if s and s.get("label") else grid["P2_knowledge"][c]["base"]
    p2_grid = transfer_block(grid, rows, cols_loaded, override=ov_p2)

    deviations = [
        {"item": "script name", "prereg_said": "outputs.N6: phase_e_n6_grid.py -> n6_grid.json",
         "what_you_did": "analysis/probes/phase_e_n6.py -> analysis/out/phase_e/n6_grid.json",
         "why": "the orchestrating task names the script phase_e_n6.py; the output file name is the prereg's",
         "effect_on_verdict": "none"},
        {"item": "assembly only; Probes 1-4 not re-run on E",
         "prereg_said": "fill_rule 2: where a unit has E, Probes 1-4 are re-run on E with the Phase B code; a cell "
                        "not re-run is NOT_RUN(reason) with the Phase B verdict beside it. PREREG_E 1.2: cells not "
                        "carried into A1 'are re-run on E in the N6 grid where the unit has E'",
         "what_you_did": "no Probe 1-4 code was run on E here. Cells covered by an A1 candidate take its final label; "
                         "every other Probe 1-4 cell of a unit with E is NOT_RUN(not re-run on E by any Phase E item) "
                         "with the Phase B (A0) verdict stored beside it",
         "why": "the orchestrating task scopes N6 to filling cells from committed outputs ('never guessed'); re-running "
                "Phase B code on E is a separate measurement",
         "effect_on_verdict": f"{kinds.get('not_rerun_phase_b_stands', 0)} cells NOT_RUN instead of an E verdict; "
                              "no label raised or lowered"},
        {"item": "R1 verdict composed here",
         "prereg_said": "a1.proposal_rules: verdict from the honest flag rate and the N7 recall cells of the "
                        "detector (ALIVE needs >= 1 single-call / single-response type DETECTS on E, B for units "
                        "without E); f1_bracket.json computed every leg except N7 and labelled R1 PENDING_N7",
         "what_you_did": "per split: lowest of f1 verdict_per_split.<s>.ceiling_before_n7 and the N7 leg from "
                         "n7_timing.json verdicts.per_unit_split_detector['<unit>|<s>|R1_BRACKET'] (ALIVE if "
                         "single_call_types_detecting is non-empty, WEAK if any DETECTS/PARTIAL, else DEAD); cell = "
                         "lowest of the E split label (B for cc_local) and f1's pooled ceiling_after_checks (artifact "
                         "checks and strata were run on the pooled splits by f1)",
         "why": "smallest faithful completion of the pre-registered rule from two committed outputs; no new number",
         "effect_on_verdict": "R1 swechat/claude_code and cc_local move from PENDING_N7 to the labels in cells.R1_bracket"},
        {"item": "check-adjusted label fills the cell",
         "prereg_said": "fill_rule 2: 'the cell shows the E verdict'; artifact_checks run 'for any N cell that "
                        "reaches WEAK or better' and can only lower a label",
         "what_you_did": "the cell carries the label after the pre-registered artifact checks, confinement and kill "
                         "tests (the items' own n6 cells and A1 final labels do the same); the rule's own E-or-B "
                         "verdict before them is stored as label_precheck and the transfer statement is also "
                         "reported on it (transfer.precheck_labels)",
         "why": "a check-failed label is not the mechanism's verdict on this unit; reporting both shows the effect",
         "effect_on_verdict": "see transfer.precheck_labels vs transfer.primary"},
        {"item": "one P2 cell for two strata",
         "prereg_said": "rows: one P2_knowledge row; prereg.json probe2.stream: main thread and subagent threads are "
                        "separate strata, never pooled",
         "what_you_did": "the cell is the main-thread stratum; the subagent stratum is stored in cells.P2_knowledge."
                         "<col>.strata.subagent and the transfer statement is also reported with it in place of the "
                         "main thread (transfer.p2_subagent_stratum)",
         "why": "the main thread is the primary stream of every unit; pooling the strata is forbidden",
         "effect_on_verdict": "none on any stratum label"},
        {"item": "N2 aiv_cu cell",
         "prereg_said": "S:n2_token_accounting.granularity_check.aiv_cu: N2 runs per GRANULAR model stratum; 'the N6 "
                        "cell names the strata'",
         "what_you_did": "the cell is PER_STRATUM(ALIVE k, WEAK k, DEAD k) with every stratum label stored; it is "
                         "left out of the ALIVE/WEAK/DEAD counts and pairs, and the transfer statement is reported "
                         "with it read as its best (ALIVE) and worst (DEAD) stratum",
         "why": "the vocabulary has no per-stratum label and no pooling rule was registered",
         "effect_on_verdict": "see transfer.n2_aiv_cu_best_stratum / _worst_stratum"},
        {"item": "field gate overrides an item's DEAD",
         "prereg_said": "fill_rule 1: NOT_TESTABLE iff a required field is absent (checked on A); N2: 'a unit that "
                        "is not GRANULAR is DEAD for N2'",
         "what_you_did": "where the A gate finds a required field absent the N6 cell is NOT_TESTABLE(<field>) and the "
                         "item's own label is stored as item_label (N2 on non-GRANULAR units; Probe 3 'DEAD (by "
                         "prereg)' cells of swechat/cursor and swechat/simple_text; Probe 4 INSUFFICIENT_N on "
                         "swechat/cursor, which has no result text)",
         "why": "the N6 fill rule is specific to the grid and states the field gate first",
         "effect_on_verdict": "those cells leave the DEAD / INSUFFICIENT_N counts; the items' verdicts are unchanged"},
        {"item": "whowhen Probe 3 column",
         "prereg_said": "one column per Phase B unit; Phase B ran Probe 3 on whowhen/Algorithm-Generated and fixed "
                        "whowhen/Hand-Crafted DEAD ('no failure signal')",
         "what_you_did": "the whowhen cell is the Algorithm-Generated sub-unit's Phase B verdict; the Hand-Crafted "
                         "sub-unit is stored in substrata as NOT_TESTABLE(error signal)",
         "why": "Hand-Crafted lacks the required field (error signal); Algorithm-Generated is the testable part",
         "effect_on_verdict": "none"},
        {"item": "agentcap columns",
         "prereg_said": "columns: '+ one column per Track B corpus'",
         "what_you_did": "agentcap has two columns (agentcap/opencode, agentcap/pi): change_log D1 calibrates them as "
                         "two units and newcorp_measure_agentcap.json reports two cells per row",
         "why": "one column would need a pooling no item computed",
         "effect_on_verdict": "none"},
        {"item": "not-loaded Track B corpora",
         "prereg_said": "one column per Track B corpus; change_log D7: N6 cells NOT_LOADED",
         "what_you_did": "eight columns whose 22 cells are NOT_RUN(not loaded: time budget) (NOT_LOADED is not in the "
                         "cell vocabulary); left out of every count and pair",
         "why": "D7", "effect_on_verdict": "none"},
        {"item": "B re-check of the field gate",
         "prereg_said": "field gate checked on A and re-checked on B",
         "what_you_did": "no cache was opened: the B re-check is prereg.json population_B (units with 0 B sessions, "
                         "which the items also found absent from E) plus each item's own B / E field checks (an item's "
                         "NOT_TESTABLE stands)",
         "why": "assembly only", "effect_on_verdict": "none known; listed in field_gate.B_recheck"},
    ]
    G = {
        "item": "n6_transfer_grid",
        "script": "analysis/probes/phase_e_n6.py",
        "prereg_section": "prereg_e.json n6_transfer_grid; PREREG_E.md section 3",
        "prereg_e_json_sha256": sha256(ROOT / "analysis" / "prereg_e.json"),
        "spec_module_sha256_lf": pe.sha256_lf(Path(pe.__file__)),
        "check_frozen": "passed",
        "fill_rule": ctx.spec["fill_rule"],
        "transfer_statement_rule": ctx.spec["transfer_statement"],
        "cell_vocabulary": ctx.spec["cell_vocabulary"] + ["PER_STRATUM(...) (N2 aiv_cu only; see deviations)"],
        "rows": rows, "row_names": {r: NAMES[r] for r in rows},
        "columns_phase_b": ctx.units_b,
        "columns_track_b": [u for _, u in ctx.tb_units],
        "columns_loaded": cols_loaded,
        "columns_not_loaded": ctx.not_loaded,
        "n_rows": len(rows), "n_columns_loaded": len(cols_loaded), "n_columns_not_loaded": len(ctx.not_loaded),
        "n_cells_loaded": len(rows) * len(cols_loaded),
        "n_cells_total": len(rows) * (len(cols_loaded) + len(ctx.not_loaded)),
        "n_cells_not_loaded": len(rows) * len(ctx.not_loaded),
        "field_gate": {"A": "analysis/prereg_e.json resolved.n6_field_gate_A", "required_fields_map": REQ,
                       "B_recheck": {"units_without_B_or_E_sessions": ctx.no_be, "evidence": ctx.no_be_source}},
        "track_b_sources": TRACK_B_FILES,
        "track_b_decisions": {k: ctx.decisions.get(k) for k in ("D1_calibration_unit_proxy", "D6_blindness",
                                                                "D7_not_loaded")},
        "cells": grid,
        "update_kind_counts": kinds,
        "transfer": {"primary": prim, "phase_b_units_only": pbo, "precheck_labels": pre,
                     "n2_aiv_cu_best_stratum": best, "n2_aiv_cu_worst_stratum": worst,
                     "p2_subagent_stratum": p2_grid, "p2_subagent_row_only": p2s},
        "per_column": per_column(grid, rows, cols_loaded),
        "deviations": deviations,
        "inputs_sha256": H,
        "opened_files": sorted(H.keys()),
    }
    tr, dm = interpretation_texts(G)
    G["interpretation_transfer_md"] = tr        # INTERPRETATION text rendered into the .md (kept for the number check)
    G["interpretation_decision_md"] = dm
    G["runtime_s"] = round(time.time() - T0, 2)
    OUT.write_text(json.dumps(G, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---- markdown outputs
    toks = json_tokens(G)
    tm = render_transfer_md(G)
    dt_sec = render_decision_md(G, ctx)
    for name, txt in (("TRANSFER_MATRIX.md", tm), ("DECISION_TABLE.md Phase E section", dt_sec)):
        miss = check_numbers(txt, toks)
        assert not miss, f"{name}: numbers not in n6_grid.json: {miss[:40]}"
    MD_TRANSFER.write_bytes(tm.encode("utf-8"))
    old = MD_DECISION.read_bytes()
    marker = ("\r\n" + DT_MARKER).encode("utf-8")
    i = old.find(marker)
    prefix = old if i < 0 else old[: i + 2]
    if not prefix.endswith(b"\r\n"):
        prefix += b"\r\n"
    new = prefix + b"\r\n" + dt_sec.encode("utf-8") if i < 0 else prefix + dt_sec.encode("utf-8")
    MD_DECISION.write_bytes(new)
    chk = MD_DECISION.read_bytes()
    a0_part = old if i < 0 else old[: i + 2]
    assert chk.startswith(a0_part.rstrip(b"\r\n")), "A0 sections of DECISION_TABLE.md changed"
    print(f"wrote {OUT.relative_to(ROOT)}, {MD_TRANSFER.relative_to(ROOT)}, {MD_DECISION.relative_to(ROOT)} "
          f"(A0 prefix {len(a0_part)} bytes unchanged); {len(rows)} rows x {len(cols_loaded)} loaded columns; "
          f"{G['runtime_s']} s")
    t = prim["totals"]
    print(json.dumps({k: t[k] for k in ("decided", "n_ALIVE", "n_WEAK", "n_DEAD", "n_INSUFFICIENT_N", "n_NOT_RUN",
                                        "n_NOT_TESTABLE", "pairs_decided", "transfer_pairs", "failing_pairs",
                                        "rows_with_failing_pair")}))


if __name__ == "__main__":
    main()
