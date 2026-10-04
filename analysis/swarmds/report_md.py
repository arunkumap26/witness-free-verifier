"""Render analysis/out/swarmds/test_scores.json as Markdown tables (analysis/out/swarmds/test_tables.md).

    PYTHONIOENCODING=utf-8 python -m analysis.swarmds.report_md [--split test|dev]

Pure formatting: every number comes from test_scores.json; nothing is recomputed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "analysis" / "out" / "swarmds"
METHODS = ("t0_structural", "t1_recompute", "t3_shadow_state", "token_conservation", "claim_provenance",
           "ours_combined", "baseline", "union_ours_baseline")
SHORT = {"t0_structural": "T0", "t1_recompute": "T1", "t3_shadow_state": "T3", "token_conservation": "TC",
         "claim_provenance": "CLM", "ours_combined": "**ours**", "baseline": "baseline",
         "union_ours_baseline": "union"}
STRATA = ("source", "spoof_class", "unit", "instructed_to_lie", "consistency", "difficulty_tiered")


def cell(x: dict) -> str:
    if not x["n_spoofed"]:
        return "-"
    return f"{x['contradicted']} ({x['recall']:.3f})"


def render(J: dict, split: str) -> str:
    S = J["splits"][split]["scores"]
    L = [f"### {split.upper()} split ({J['splits'][split]['role']})", ""]
    L.append("**Soundness on this split's honest rows** (FP = honest row called contradicted)")
    L.append("")
    L.append("| method | unit | honest n | FP | honest supported | honest abstained | TP | precision |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for m in METHODS:
        for u in ("tool_output", "claim"):
            s = S[m]["by_unit"][u]
            L.append(f"| {SHORT[m]} | {u} | {s['n_honest']} | {s['honest_FP']} | {s['honest_supported']} | "
                     f"{s['honest_unconstrained']} | {s['contradicted']} | {s['precision']} |")
    L.append("")
    for sk in STRATA:
        vals = S["ours_combined"]["strata"].get(sk)
        if not vals:
            continue
        L.append(f"**Recall by `{sk}`**: contradicted (contradicted / n spoofed). Last column: ours abstained / "
                 f"ours said supported, on spoofed rows.")
        L.append("")
        L.append("| " + sk + " | n spoofed | " + " | ".join(SHORT[m] for m in METHODS) + " | ours abst / supp |")
        L.append("|---|---:|" + "---:|" * len(METHODS) + "---:|")
        for sv, s in vals.items():
            if not s["n_spoofed"]:
                continue
            L.append(f"| {sv} | {s['n_spoofed']} | " + " | ".join(cell(S[m]["strata"][sk][sv]) for m in METHODS) +
                     f" | {s['unconstrained_on_spoofed']} / {s['supported_on_spoofed']} |")
        L.append("")
    L.append("**Honest trap classes** (label not_spoofed; verdict counts)")
    L.append("")
    for m in ("ours_combined", "baseline"):
        L.append(f"- {SHORT[m]}: `{S[m]['honest_trap_classes']}`")
    L.append("")
    nc = J["splits"][split]["newly_caught"]
    L.append("**Spoofed rows newly caught over the baseline** (the baseline did not contradict them)")
    L.append("")
    L.append("| method | total | by spoof_class |")
    L.append("|---|---:|---|")
    for m, c in nc["newly_caught_over_baseline"].items():
        L.append(f"| {SHORT.get(m, m)} | {c.get('__total__', 0)} | " +
                 ", ".join(f"{k} {v}" for k, v in c.items() if k != "__total__") + " |")
    L.append("")
    L.append(f"Baseline-only catches (baseline contradicted, ours did not): `{nc['baseline_only_catches']}`")
    L.append("")
    uc = J["splits"][split]["unique_contribution"]
    L.append("**Unique to one check** (spoofed rows contradicted by exactly one of our checks): " +
             ", ".join(f"{SHORT[m]} {c.get('__total__', 0)}" for m, c in uc.items()))
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="both")
    a = ap.parse_args(argv)
    J = json.loads((OUT / "test_scores.json").read_text(encoding="utf-8"))
    splits = ("test", "dev") if a.split == "both" else (a.split,)
    md = "\n".join(render(J, s) for s in splits)
    (OUT / "test_tables.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
