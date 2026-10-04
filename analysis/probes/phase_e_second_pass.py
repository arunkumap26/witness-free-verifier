"""Phase E, Track A, A1 write-up: assembly for analysis/SECOND_PASS.md (prereg_e.json S:a1, S:survival_rule,
S:followups; PREREG_E.md section 1).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_second_pass
Check the write-up's numbers:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_second_pass --check analysis/SECOND_PASS.md

ASSEMBLY ONLY. No IR cache, raw source, sample file or split is opened. Every label and number is copied, by an
explicit JSON path, from the Phase E item outputs under analysis/out/phase_e/ (each written by its own committed
script under the frozen pre-registration). Two things are derived here, both mechanically:
 1. The R1 survival status. f1_bracket.json left R1 at PENDING_N7 and n6_grid.json composed the R1 label from f1's
    honest leg / kill rule / artifact-check ceiling and the n7_timing.json R1_BRACKET cells, but no item called the
    frozen survival_status() for R1. It is called here on the n6-composed labels and f1's artifact-check effects, with
    the conventions the sibling items used (Phase D proposals have no Phase B label: base None and the E label; a unit
    without E starts from its B label with has_e=False, as r4_r5.json did for R4 cc_local).
 2. The N7 walk-through over both halves: the attack types with no DETECTS cell in any detector, unit or split
    (n7_timing.json cells + n7_content.json cells). A set count, no new statistic.
Writes analysis/out/phase_e/second_pass.json (labels, copied numbers, the two derivations, input sha256).
With --check, every number token in the given .md files is looked up among the numbers of analysis/out/phase_e/*.json
(+ n7_content_shards) and, for thresholds, analysis/prereg_e.json / analysis/prereg.json; misses are listed.
cc_local: labels and aggregates only. aiv_cc: single-agent case study.
"""
import argparse
import bisect
import hashlib
import json
import re
import time
from pathlib import Path

from analysis.probes import prereg_e_common as pe

T0 = time.time()
ROOT = pe.ROOT
OUT_E = pe.OUT_E
OUT = OUT_E / "second_pass.json"

ITEMS = ["a1_p1_p3", "a1_p2_p4_f3", "f1_bracket", "f2_floor_shift", "f3_round", "r2_r3", "r4_r5", "n6_grid",
         "n7_timing", "n7_content", "n1", "n2", "n3", "n4_n5cg", "n5_battery"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name):
    return json.loads((OUT_E / f"{name}.json").read_text(encoding="utf-8"))


def at(obj, path):
    """Resolve an explicit path (list of keys / indices); raises if any step is missing."""
    cur = obj
    for k in path:
        if isinstance(cur, list):
            cur = cur[int(k)]
        else:
            if k not in cur:
                raise KeyError(f"missing {k!r} in path {path}")
            cur = cur[k]
    return cur


def pstr(file, path):
    s = ""
    for p in path:
        p = str(p)
        if "/" in p or "|" in p or " " in p:
            s += f"[{p!r}]"
        else:
            s += ("." if s else "") + p
    return f"{file}.json {s}"


# ============================================================================================================ A1 rows
A1_VERDICT_ROWS = [
    # (candidate, unit, item, key in verdicts)
    ("P1 latency physics", "swechat/opencode", "a1_p1_p3", "P1/swechat/opencode"),
    ("P1 latency physics", "cc_local", "a1_p1_p3", "P1/cc_local"),
    ("P1 latency physics", "swechat/claude_code", "a1_p1_p3", "P1/swechat/claude_code"),
    ("P3 zero-error tail", "swechat/claude_code", "a1_p1_p3", "P3zero/swechat/claude_code"),
    ("P2 knowledge precedence", "swechat/claude_code main", "a1_p2_p4_f3", "P2/swechat/claude_code/main"),
    ("P2 knowledge precedence", "swechat/claude_code subagent", "a1_p2_p4_f3", "P2/swechat/claude_code/subagent"),
    ("P2 knowledge precedence", "swechat/opencode subagent", "a1_p2_p4_f3", "P2/swechat/opencode/subagent"),
    ("P2 knowledge precedence", "swechat/codex subagent", "a1_p2_p4_f3", "P2/swechat/codex/subagent"),
    ("P2 knowledge precedence", "aiv_cc main (single-agent case study)", "a1_p2_p4_f3", "P2/aiv_cc/main"),
    ("P4 round numbers", "swechat/claude_code", "a1_p2_p4_f3", "P4round/swechat/claude_code"),
    ("P4 round numbers", "cc_local", "a1_p2_p4_f3", "P4round/cc_local"),
    ("P4 round numbers", "swechat/* (pooled)", "a1_p2_p4_f3", "P4round/swechat/* (pooled)"),
]


def a1_rows(J):
    rows = []
    for cand, unit, item, key in A1_VERDICT_ROWS:
        v = at(J[item], ["verdicts", key])
        bue = v.get("BuE_label")
        if bue is None and key.startswith("P2/"):
            bue = at(v, ["deciding", "BuE", "label"])          # B only for aiv_cc (BuE block = B)
        if bue is None and key.startswith("P4round/"):
            sv = at(J["f3_round"], ["candidates", key, "survival"])
            bue = f"{sv['BuE_label_full_statistic']} (full statistic); F3 {sv['BuE_F3_label']}"
        rows.append({"candidate": cand, "unit": unit, "source": pstr(item, ["verdicts", key]),
                     "phase_b": v.get("phase_b"), "E_label": v.get("E_label"), "BuE_label": bue,
                     "status": v["status"], "final_label": v["final_label"], "reasons": v.get("reasons", []),
                     "deciding": v.get("deciding")})
    return rows


def r_rows(J):
    rows = []
    s = at(J["r2_r3"], ["R2", "survival"])
    rows.append({"candidate": "R2 image-token ledger", "unit": "aiv_cu (Gemini strata)",
                 "source": pstr("r2_r3", ["R2", "survival"]), "phase_b": None, "E_label": s["e_label"],
                 "BuE_label": s["BuE_label"], "status": s["status"], "final_label": s["final_label"],
                 "reasons": s["reasons"]})
    for u in ("swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini"):
        s = at(J["r2_r3"], ["R3", "units", u, "survival"])
        rows.append({"candidate": "R3 git execution window", "unit": u,
                     "source": pstr("r2_r3", ["R3", "units", u, "survival"]), "phase_b": None,
                     "E_label": s.get("e_label"), "BuE_label": s.get("BuE_label"), "status": s["status"],
                     "final_label": s.get("final_label"), "reasons": s.get("reasons", [])})
    for cand, name, units in (("R4", "R4 dual-rendering recount", ("swechat/claude_code", "cc_local")),
                              ("R5", "R5 usage-ledger reconciliation",
                               ("swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini"))):
        for u in units:
            s = at(J["r4_r5"], [cand, "units", u, "survival"])
            rows.append({"candidate": name, "unit": u, "source": pstr("r4_r5", [cand, "units", u, "survival"]),
                         "phase_b": None, "E_label": s.get("e_label"),
                         "BuE_label": s.get("BuE_label", s.get("pooled_label")), "status": s["status"],
                         "final_label": s.get("final_label"), "reasons": s.get("reasons", [])})
    return rows


# ============================================================================================================ R1 survival
def r1_checks(f1, u):
    """f1 artifact-check results -> survival_status() check list (NOT_RUN checks are left out, as the siblings did)."""
    ac = at(f1, ["r1", u, "artifact_checks"])
    out = []
    for name in ("AC1_parser", "AC2_truncation", "AC3_join", "AC4_dominance", "AC5_post_strat"):
        blk = ac[name]
        if name == "AC1_parser":
            res = [b.get("result") for b in blk]
            if all(r == "NOT_RUN" for r in res):
                continue
            eff = "pass" if all(r == "PASS" for r in res if r != "NOT_RUN") else "downgrade"
            out.append({"name": name, "effect": eff, "result": res})
        elif name == "AC4_dominance":
            eff = blk["effect"]
            out.append({"name": "AC4_UNTESTABLE_WITHOUT_DOMINANT" if eff == "cap_weak" else name, "effect": eff})
        else:
            r = blk.get("result")
            if r == "NOT_RUN":
                continue
            out.append({"name": name, "effect": "pass" if r == "PASS" else "downgrade", "result": r})
    if at(f1, ["r1", u, "verdict", "confined"]):
        out.append({"name": "CONFINED", "effect": "downgrade"})
    return out


def r1_rows(J):
    rows = []
    f1, n6 = J["f1_bracket"], J["n6_grid"]
    for u, has_e in (("swechat/claude_code", True), ("cc_local", False)):
        c = at(n6, ["cells", "R1_bracket", u])
        checks = r1_checks(f1, u)
        if has_e:
            status, final, reasons = pe.survival_status(None, c["label_E"], checks, has_e=True, e_seen=False)
            inputs = {"phase_b_label": None, "e_label": c["label_E"], "has_e": True, "e_seen": False}
        else:
            status, final, reasons = pe.survival_status(c["label_B"], None, checks, has_e=False, e_seen=False)
            inputs = {"phase_b_label (B label, r4_r5 convention)": c["label_B"], "e_label": None, "has_e": False,
                      "e_seen": False}
        rows.append({"candidate": "R1 request-id clock bracket", "unit": u,
                     "source": "computed here: prereg_e_common.survival_status() on "
                               + pstr("n6_grid", ["cells", "R1_bracket", u]) + " label_E / label_B and "
                               + pstr("f1_bracket", ["r1", u, "artifact_checks"]),
                     "phase_b": None, "E_label": c["label_E"], "B_label": c["label_B"], "BuE_label": c["label_BuE"],
                     "n6_cell_label": c["label"], "f1_label": at(f1, ["r1", u, "verdict", "label"]),
                     "status": status, "final_label": final, "reasons": reasons,
                     "survival_inputs": inputs, "checks": checks,
                     "agrees_with_n6_cell": final == c["base"]})
    return rows


# ============================================================================================================ follow-ups
def followups(J):
    f1, f2, f3 = J["f1_bracket"], J["f2_floor_shift"], J["f3_round"]
    out = {
        "F1": {
            "step0_result": at(f1, ["step0", "result"]),
            "honest": {k: at(f1, ["units", k, "honest"]) for k in ("swechat/claude_code|B", "swechat/claude_code|E",
                                                                     "cc_local|B")},
            "categories_meeting_shared_cause_rule": {
                k: sorted(c for c, v in at(f1, ["units", k, "benign", "categories"]).items()
                          if v.get("shared_benign_cause"))
                for k in ("swechat/claude_code|B", "swechat/claude_code|E", "cc_local|B")},
            "effective_fp": at(f1, ["f1_effective_fp"]),
            "source": "f1_bracket.json step0; units.<unit|split>.honest / .benign; f1_effective_fp",
        },
        "F2": {"verdicts": at(f2, ["verdicts"]), "verdict_effect": at(f2, ["verdict_effect"]),
               "source": "f2_floor_shift.json verdicts; verdict_effect"},
        "F3": {c: {"kill_test_result": at(f3, ["candidates", c, "kill_test", "result"]),
                   "label_used": at(f3, ["candidates", c, "kill_test", "label_used"]),
                   "status": at(f3, ["candidates", c, "survival", "status"]),
                   "final_label": at(f3, ["candidates", c, "survival", "final_label"])}
               for c in at(f3, ["candidates"])},
    }
    out["F3"]["source"] = "f3_round.json candidates.<c>.kill_test / .survival"
    return out


# ============================================================================================================ N7 walk-through
def n7_union(J):
    attacks = None
    try:
        attacks = json.loads((OUT_E / "fig_data.json").read_text(encoding="utf-8"))["n7_recall"]["attacks"]
    except Exception:  # noqa: BLE001
        attacks = None
    per = {}
    for half in ("n7_timing", "n7_content"):
        for key, c in at(J[half], ["cells"]).items():
            parts = key.split("|")
            if len(parts) != 5 or not isinstance(c, dict):
                continue
            unit, split, det, atk, prm = parts
            d = per.setdefault(atk, {"DETECTS_cells": 0, "DETECTS_cells_replication_split": 0,
                                     "detectors_with_DETECTS": set(), "halves": set()})
            if c.get("label") == "DETECTS":
                d["DETECTS_cells"] += 1
                d["detectors_with_DETECTS"].add(det)
                d["halves"].add(half)
                rep = "E" if unit.startswith("swechat/") or unit == "aiv_cu" else "B"
                if split == rep:
                    d["DETECTS_cells_replication_split"] += 1
    if attacks is None:
        attacks = sorted(per)
    rows = {a: {"DETECTS_cells": per.get(a, {}).get("DETECTS_cells", 0),
                "DETECTS_cells_replication_split": per.get(a, {}).get("DETECTS_cells_replication_split", 0),
                "detectors_with_DETECTS": sorted(per.get(a, {}).get("detectors_with_DETECTS", set())),
                "halves": sorted(per.get(a, {}).get("halves", set()))} for a in attacks}
    dets = sorted({d for a in rows for d in rows[a]["detectors_with_DETECTS"]})
    none_any = [a for a in attacks if rows[a]["DETECTS_cells"] == 0]
    none_rep = [a for a in attacks if rows[a]["DETECTS_cells_replication_split"] == 0]
    return {"rule": "an attack type 'walks through' if no cell of any detector, unit, split and parameter in "
                    "n7_timing.json cells or n7_content.json cells is labelled DETECTS; the replication-split reading "
                    "counts only E cells (B for cc_local, aiv_cc, whowhen)",
            "attack_types": attacks, "n_attack_types": len(attacks), "per_attack": rows,
            "detectors_with_any_DETECTS_cell": dets,
            "no_DETECTS_any_split": none_any, "n_no_DETECTS_any_split": len(none_any),
            "no_DETECTS_replication_split": none_rep, "n_no_DETECTS_replication_split": len(none_rep)}


def r3_n7_recheck(J):
    """r2_r3.json read n7_timing.json while a re-run was in progress (its R3.units.*.n7_meta.file_mtime); compare the
    R3_GIT cells it used with the final n7_timing.json (label and recall k)."""
    cells = at(J["n7_timing"], ["cells"])
    same, diff, missing = 0, [], []
    for u, blk in at(J["r2_r3"], ["R3", "units"]).items():
        for split, cs in (blk.get("n7_cells") or {}).items():
            if not isinstance(cs, dict):
                continue
            for key, v in cs.items():
                k2 = f"{u}|{split}|R3_GIT|{key}"
                t = cells.get(k2)
                if t is None:
                    missing.append(k2)
                    continue
                a = (v.get("label"), (v.get("recall") or {}).get("k"))
                b = (t.get("label"), (t.get("recall") or {}).get("k"))
                if a == b:
                    same += 1
                else:
                    diff.append({"cell": k2, "r2_r3": a, "n7_timing": b})
    return {"rule": "label and recall k of every R3_GIT cell r2_r3.json used, against the final n7_timing.json cells",
            "r2_r3_read_mtime": {u: (b.get("n7_meta") or {}).get("file_mtime")
                                 for u, b in at(J["r2_r3"], ["R3", "units"]).items()},
            "n_same": same, "n_differ": len(diff), "differ": diff, "missing_in_final": missing}


# ============================================================================================================ numbers check
NUM_RX = re.compile(r"(?<![A-Za-z0-9_.])-?\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9_])")


def md_tokens(text):
    text = text.replace("−", "-")
    toks = []
    for t in NUM_RX.findall(text):
        t2 = t.replace(",", "")
        if t2 in ("-",):
            continue
        toks.append(t2)
    return sorted(set(toks))


def collect_numbers(obj, acc):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
        return
    if isinstance(obj, str):
        for t in NUM_RX.findall(obj.replace("−", "-")):
            try:
                acc.append(float(t.replace(",", "")))
            except ValueError:
                pass
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            collect_numbers(str(k), acc)
            collect_numbers(v, acc)
        return
    if isinstance(obj, list):
        for v in obj:
            collect_numbers(v, acc)


def number_index(paths):
    acc = []
    for p in paths:
        collect_numbers(json.loads(Path(p).read_text(encoding="utf-8")), acc)
    vals = sorted(set(acc))
    return vals


def found(tok, vals):
    x = float(tok)
    if "." not in tok:
        i = bisect.bisect_left(vals, x)
        return i < len(vals) and vals[i] == x or (i > 0 and vals[i - 1] == x)
    d = len(tok.split(".")[1])
    half = 0.5 * 10 ** (-d) + 1e-12
    for y in (x, -x):
        i = bisect.bisect_left(vals, y - half)
        if i < len(vals) and vals[i] <= y + half:
            return True
    return False


FRAC_RX = re.compile(r"(?<![A-Za-z0-9_.])(\d[\d,]*)/(\d[\d,]*)(?![\d,]*[A-Za-z_])")


def pair_index(paths):
    """Every (k, n) pair that sits together in one JSON container (dict values or list items, incl. one level of nested
    dicts such as {'k':..,'n':..}) or is written as 'k/n' inside a string."""
    pairs = set()

    def add_container(vals):
        nums = [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        s = set(nums)
        for a in s:
            for b in s:
                pairs.add((a, b))

    def walk(o):
        if isinstance(o, dict):
            add_container(list(o.values()))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            if len(o) <= 64:
                add_container(o)
            for v in o:
                walk(v)
        elif isinstance(o, str):
            for a, b in FRAC_RX.findall(o):
                pairs.add((float(a.replace(",", "")), float(b.replace(",", ""))))
    for p in paths:
        walk(json.loads(Path(p).read_text(encoding="utf-8")))
    return pairs


# Decimals SECOND_PASS.md cites per section, looked up only inside the subtree that section names as its source.
SUBTREE_CHECKS = [
    ("2.1 P1 opencode", "a1_p1_p3", ["candidates", "P1/swechat/opencode"],
     "0.0018 0.0050 0.9986 0.9958 1.0000 0.0017 0.0004 0.0033 0.9990 0.9981 0.9996 0.863 0.951 0.837 0.970 0.9988 "
     "0.0016 0.9991 0.213 0.9992 0.9982 0.9998 0.99916"),
    ("2.2 P1 cc_local", "a1_p1_p3", ["candidates", "P1/cc_local"],
     "0.0010 0.0033 0.919 0.881 0.971 0.932 0.983 0.968 0.996 0.982 0.963 0.999 0.814"),
    ("2.3 P1 claude_code", "a1_p1_p3", ["candidates", "P1/swechat/claude_code"],
     "0.0035 0.0024 0.0046 0.986 0.973 0.995 0.081 0.045 0.143 0.0034 0.0027 0.0042 0.9866 0.9794 0.9922 0.125 0.092 "
     "0.169 0.713 0.815 0.392 0.991 0.012 0.98702 0.135"),
    ("2.4 P2", "a1_p2_p4_f3", ["candidates"],
     "0.144 0.125 0.163 0.136 0.117 0.156 0.140 0.127 0.153 0.077 0.062 0.091 0.061 0.097 0.067 0.089 0.073 0.020 "
     "0.150 0.043 0.004 0.095 0.058 0.024 0.101 0.131 0.099 0.163 0.119 0.086 0.153 0.126 0.103 0.149 0.192 0.081 "
     "0.351 0.147 0.072 0.933 0.202 0.212 0.505 0.449"),
    ("2.4 P2 instrument", "a1_p2_p4_f3", ["instrument_check"], "0.028 0.030"),
    ("2.5 P3", "a1_p1_p3", ["candidates", "P3zero/swechat/claude_code"],
     "0.022 0.012 0.041 0.021 0.011 0.00074 28.4 0.013 0.034 0.078 0.061 0.099 0.074 0.051 0.104 0.802 0.024 0.169 "
     "0.033 0.363 0.045"),
    ("2.6 P4", "a1_p2_p4_f3", ["candidates"],
     "0.423 0.334 0.520 0.116 0.110 0.122 0.367 0.289 0.454 0.113 0.648 0.435 0.786 0.121 0.553 0.131 0.731 0.736 "
     "0.664 0.071 0.075 0.301 0.118 0.464 0.255"),
    ("4.3 F3", "f3_round", [],
     "0.270 0.160 0.403 0.154 0.501 0.308 0.199 0.288 0.086 0.338 0.254 0.368 0.305 0.437 0.109 0.118 0.231 0.158 "
     "0.316 0.820 0.462 0.263 0.546 0.0692 0.0656"),
    ("3.1/4.1 R1 and F1", "f1_bracket", [],
     "0.00272 0.00112 0.00466 0.00330 0.00145 0.00540 0.00300 0.00173 0.00443 0.00118 0.00248 0.00021 0.00666 0.3939 "
     "0.3726 0.4150 0.3923 0.9761 0.9703 0.9817 0.9750 0.9746 0.874 0.9539 0.9481 0.809 0.352 0.00298 0.00171 0.9988 "
     "0.0031 0.4051 0.8980 0.9790 0.9922 0.9997 0.28 0.3934 0.9760 0.3936 0.9755 0.3319 0.8909 0.00191 0.00057 "
     "0.00349 0.3931 0.00331 0.00551 0.4144 0.3916 0.4386 0.9805 0.9753 0.9853 0.2562 0.9008 0.00136 0.00240"),
    ("3.1 R1 N7 cells", "n7_timing", ["cells"], "0.9585 0.0175 0.9414 0.0259 0.9536 0.5002 0.9784 0.0318"),
    ("4.2 F2", "f2_floor_shift", [],
     "0.135 0.090 0.197 0.081 0.045 0.143 0.111 0.079 0.153 0.125 0.092 0.169 0.110 0.033 0.249 0.751 0.967 0.581 "
     "0.343 0.238 0.048 0.427 0.097 0.194 0.149 0.247 0.161 0.081"),
    ("3.2 R2", "r2_r3", ["R2"],
     "0.0644 0.0443 0.0926 0.0447 0.0284 0.0695 0.0545 0.0409 0.0724 0.0033 0.0016 0.0054 0.0390 0.0700 0.470 0.367 "
     "0.938 0.573"),
    ("3.3 R3", "r2_r3", ["R3"], "0.0156 0.428 0.0020 0.0006 0.0074 0.0078 0.0016 0.0040 0.818 0.0033 0.0022 0.0061"),
    ("3.4 R4", "r4_r5", ["R4"], "0.0013 0.41 0.368 0.454 0.0076 0.46 0.775"),
    ("3.5 R5", "r4_r5", ["R5"],
     "0.0079 0.0046 0.0135 0.0066 0.0036 0.0121 0.0073 0.0048 0.0109 0.792 0.754 0.825 0.748 0.708 0.784 0.438 0.0026 "
     "0.0013 0.0051 0.0072 0.0047 0.0101 0.0317 0.0124 0.0788 0.0099 0.0038 0.0251 0.008"),
    ("6 N1", "n1", [], "0.031 0.016 0.046 0.474 0.425 0.175 0.0103 0.0143 0.039 0.002 0.074 0.707 0.0058 0.172 0.057"),
    ("6 N2", "n2", [], "0.0269 0.932 0.891 0.882 0.900"),
    ("6 N3", "n3", [], "-0.039 -0.054 -0.024 0.483 0.223 0.485"),
    ("6 N5abdef", "n5_battery", [], "0.281 0.195"),
    ("6 N4/N5c/N5g", "n4_n5cg", [], "0.845 0.996 0.502"),
]


def subtree_check(J):
    out = []
    for name, item, path, toks in SUBTREE_CHECKS:
        acc = []
        collect_numbers(at(J[item], path), acc)
        vals = sorted(set(acc))
        tl = toks.split()
        miss = [t for t in tl if not found(t, vals)]
        out.append({"section": name, "subtree": pstr(item, path) if path else f"{item}.json (whole file)",
                    "n_tokens": len(tl), "not_found_in_subtree": miss})
    return out


def check_md(md_paths):
    data_files = sorted(p for p in OUT_E.glob("*.json")) + sorted((OUT_E / "n7_content_shards").glob("*.json"))
    data_files = [p for p in data_files if p.name != OUT.name]
    vals_data = number_index(data_files)
    pairs = pair_index(data_files)
    vals_prereg = number_index([ROOT / "analysis" / "prereg_e.json", ROOT / "analysis" / "prereg.json"])
    rep = {}
    for mp in md_paths:
        toks = md_tokens(Path(mp).read_text(encoding="utf-8"))
        miss, prereg_only = [], []
        for t in toks:
            if found(t, vals_data):
                continue
            if found(t, vals_prereg):
                prereg_only.append(t)
            else:
                miss.append(t)
        fr = sorted(set(FRAC_RX.findall(Path(mp).read_text(encoding="utf-8"))))
        fr_miss = [f"{a}/{b}" for a, b in fr
                   if (float(a.replace(",", "")), float(b.replace(",", ""))) not in pairs]
        rep[str(mp)] = {"n_number_tokens": len(toks), "found_in_phase_e_outputs": len(toks) - len(miss) - len(prereg_only),
                        "found_only_in_prereg": prereg_only, "not_found": miss,
                        "n_fractions_k_over_n": len(fr), "fractions_not_found_as_a_pair": fr_miss,
                        "fraction_rule": "k/n matches if k and n sit together in one JSON container (dict values or a "
                                         "short list) or appear as 'k/n' inside a string of a Phase E output",
                        "rule": "a token matches if some number in analysis/out/phase_e/*.json (+ n7_content_shards) "
                                "rounds to it at the token's decimals (integers: exact); else prereg_e.json / "
                                "prereg.json (thresholds); commas stripped, U+2212 read as minus"}
    return rep


# ============================================================================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", nargs="*", help="check that every number in these .md files occurs in the Phase E outputs")
    args = ap.parse_args()
    pj = pe.check_frozen()
    J = {n: load(n) for n in ITEMS}
    out = {
        "item": "second_pass (A1 write-up assembly for analysis/SECOND_PASS.md)",
        "script": "analysis/probes/phase_e_second_pass.py",
        "prereg_section": "prereg_e.json a1, survival_rule, followups; PREREG_E.md section 1",
        "check_frozen": "passed",
        "prereg_e_json_sha256": sha256(ROOT / "analysis" / "prereg_e.json"),
        "spec_module_sha256_lf": pe.sha256_lf(Path(pe.__file__)),
        "spec_module_sha256_lf_prereg": pj["provenance"]["spec_module_sha256_lf"],
        "assembly_only": "no IR cache, raw source, sample file or split opened; every label/number copied by path",
        "a1_rows": a1_rows(J),
        "r1_rows": r1_rows(J),
        "r2_r5_rows": r_rows(J),
        "followups": followups(J),
        "n7_walkthrough_union": n7_union(J),
        "r3_n7_recheck": r3_n7_recheck(J),
        "deviations": [
            {"item": "R1 survival status computed in this assembly",
             "prereg_said": "survival_rule.function survival_status(); a1.proposal_rules for R1",
             "what_you_did": "f1_bracket.json labelled R1 PENDING_N7 (N7 absent when it ran); n6_grid.json composed the "
                             "label from f1 + n7_timing.json but computed no status. survival_status() is called here on "
                             "the n6-composed E label (swechat/claude_code; base None as r2_r3 did for R2/R3) or B label "
                             "(cc_local, has_e=False, the r4_r5 convention for R4 cc_local) with f1's artifact-check "
                             "effects (NOT_RUN checks left out, as the siblings did)",
             "why": "smallest faithful completion: every input is a committed item output; the function is the frozen one",
             "effect_on_verdict": "none: the final labels equal the n6 cells (agrees_with_n6_cell)"},
            {"item": "assembly script and JSON for SECOND_PASS.md",
             "prereg_said": "outputs: interpretation goes to SECOND_PASS.md; no SECOND_PASS script is named",
             "what_you_did": "this assembly script writes second_pass.json (copied labels, two mechanical derivations, "
                             "input sha256) and checks the .md numbers against the Phase E outputs",
             "why": "traceability of the R1 status and of the combined N7 walk-through",
             "effect_on_verdict": "none"},
        ],
        "inputs_sha256": {f"analysis/out/phase_e/{n}.json": sha256(OUT_E / f"{n}.json") for n in ITEMS},
    }
    out["inputs_sha256"]["analysis/out/phase_e/fig_data.json"] = sha256(OUT_E / "fig_data.json")
    allrows = out["a1_rows"] + out["r1_rows"] + out["r2_r5_rows"]
    st, fl = {}, {}
    for r in allrows:
        s = r["status"].split(" (")[0]
        st[s] = st.get(s, 0) + 1
        f = r["final_label"] or "none (NOT_RUN)"
        fl[f] = fl.get(f, 0) + 1
    out["counts"] = {"rule": "one row per candidate x unit in a1_rows + r1_rows + r2_r5_rows; status read without its "
                             "suffix", "n_rows": len(allrows), "status": st, "final_label": fl}
    if args.check:
        out["md_number_check"] = check_md([ROOT / p for p in args.check])
        out["md_number_check"]["subtree_checks"] = subtree_check(J)
    out["runtime_s"] = round(time.time() - T0, 2)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=sorted), encoding="utf-8")
    for r in out["r1_rows"]:
        print("R1", r["unit"], r["status"], r["final_label"], "n6:", r["n6_cell_label"], "agree:", r["agrees_with_n6_cell"])
    w = out["n7_walkthrough_union"]
    print("N7 no DETECTS any split:", w["n_no_DETECTS_any_split"], "/", w["n_attack_types"], w["no_DETECTS_any_split"])
    print("N7 no DETECTS replication split:", w["n_no_DETECTS_replication_split"], w["no_DETECTS_replication_split"])
    if args.check:
        for k, v in out["md_number_check"].items():
            if k == "subtree_checks":
                for s in v:
                    print("subtree", s["section"], s["n_tokens"], "miss", s["not_found_in_subtree"])
                continue
            print(k, "tokens", v["n_number_tokens"], "prereg-only", v["found_only_in_prereg"], "NOT FOUND", v["not_found"])
            print("fractions", v["n_fractions_k_over_n"], "pairs NOT FOUND", v["fractions_not_found_as_a_pair"])


if __name__ == "__main__":
    main()
