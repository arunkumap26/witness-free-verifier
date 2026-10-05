#!/usr/bin/env python
"""Reproduce the swarm-dataset results table (test split) from ./dataset. Stdlib only; a few minutes on a laptop.

    python scripts/score_dataset.py                     # dataset at ./dataset
    python scripts/score_dataset.py --data D:/data/wfv  # or set WFV_DATA

Runs analysis/swarmds/score.py (the frozen checks + the rule-based baseline on every row of spoof_v1.db, labels joined
only after every verdict exists), writes the full outputs to ./results/ (test_scores.json, test_scores.txt,
row_verdicts.jsonl, score_log.txt), prints the headline table, and compares it with the recorded numbers in
analysis/out/swarmds/test_scores.json.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RECORDED = ROOT / "analysis" / "out" / "swarmds" / "test_scores.json"
METHODS = (("ours_combined", "ours (T0+T1+T3+TC+CLM)"), ("baseline", "rule-based baseline"),
           ("union_ours_baseline", "ours OR baseline"))
CLASSES = ("injected_I-struct", "injected_I-recompute", "injected_I-state", "injected_I-launder", "injected_I-forge",
           "injected_I-grammar", "tiered_easy", "tiered_medium", "tiered_hard", "counterfactual",
           "mode_claim_unperformed_step", "mode_claim_prompted", "fabricated_line_count", "fabricated_digest",
           "chore_answer", "scope_substitution")


def rel(p) -> str:
    """p relative to the current directory when it is inside it (shorter, machine-independent output)."""
    p = Path(p).resolve()
    return p.relative_to(Path.cwd().resolve()).as_posix() if p.is_relative_to(Path.cwd().resolve()) else str(p)


def headline(J: dict) -> dict:
    S = J["splits"]["test"]["scores"]
    out = {"honest_calls": {k: v["contradicted_FP"] for k, v in J["honest_all_real_calls"]["per_check"].items()},
           "n_honest_calls": J["honest_all_real_calls"]["per_check"]["t0_structural"]["calls"],
           "methods": {}}
    for m, _ in METHODS:
        out["methods"][m] = {u: {k: S[m]["by_unit"][u][k] for k in ("n_spoofed", "contradicted", "recall",
                                                                     "n_honest", "honest_FP", "precision")}
                             for u in ("tool_output", "claim")}
        out["methods"][m]["classes"] = {c: S[m]["strata"]["spoof_class"].get(c, {}).get("recall") for c in CLASSES}
    return out


def table(H: dict) -> str:
    L = []
    w = L.append
    fp = sum(H["honest_calls"].values())
    w(f"SOUNDNESS: {fp} false positives on {H['n_honest_calls']:,} honest tool calls "
      f"(6,232 honest transcripts, every check)")
    w("")
    w("TEST SPLIT (rules frozen on dev)        tool outputs                      claims")
    w(f"  {'method':28s} {'caught':>13s} {'recall':>7s} {'FP':>3s}    {'caught':>9s} {'recall':>7s} {'FP':>3s}")
    for m, name in METHODS:
        t, c = H["methods"][m]["tool_output"], H["methods"][m]["claim"]
        w(f"  {name:28s} {t['contradicted']:>5,}/{t['n_spoofed']:<7,} {t['recall']:7.3f} {t['honest_FP']:>3d}    "
          f"{c['contradicted']:>3d}/{c['n_spoofed']:<5d} {c['recall']:7.3f} {c['honest_FP']:>3d}")
    w(f"  (honest rows in test: {H['methods']['ours_combined']['tool_output']['n_honest']:,} tool outputs, "
      f"{H['methods']['ours_combined']['claim']['n_honest']} claims)")
    w("")
    w(f"  recall by spoof_class        {'ours':>6s} {'base':>6s} {'union':>6s}")
    for cl in CLASSES:
        r = [H["methods"][m]["classes"].get(cl) for m, _ in METHODS]
        if all(x is None for x in r):
            continue
        w(f"  {cl:28s} " + " ".join(f"{x:6.3f}" if x is not None else "     -" for x in r))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reproduce the swarm-dataset test-split table.")
    ap.add_argument("--data", default=None, help="dataset root (default: env WFV_DATA, else ./dataset)")
    ap.add_argument("--out", default=str(ROOT / "results"), help="output dir (default: ./results)")
    a = ap.parse_args(argv)
    from analysis.swarmds import data as D
    from analysis.swarmds import score as S
    D.set_root(a.data)
    D.require()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"dataset: {rel(D.DATA)} ({D.LAYOUT} layout)")
    print("scoring every row with the frozen checks and the baseline; full log -> "
          f"{rel(out / 'score_log.txt')} (takes a few minutes) ...", flush=True)
    t0 = time.time()
    with open(out / "score_log.txt", "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        rc = S.main(["--out", str(out), "--data", str(D.DATA)])
    if rc:
        print(f"score.py failed (exit {rc}); see {rel(out / 'score_log.txt')}")
        return rc
    J = json.loads((out / "test_scores.json").read_text(encoding="utf-8"))
    H = headline(J)
    print(f"done in {time.time() - t0:.0f}s\n")
    print(table(H))
    if RECORDED.is_file():
        R = headline(json.loads(RECORDED.read_text(encoding="utf-8")))
        same = R == H
        print(f"\nmatches the recorded results (analysis/out/swarmds/test_scores.json): {'yes' if same else 'NO'}")
        if not same:
            for m in H["methods"]:
                for u in ("tool_output", "claim"):
                    if H["methods"][m][u] != R["methods"][m][u]:
                        print(f"  {m} {u}: now {H['methods'][m][u]}  recorded {R['methods'][m][u]}")
    print(f"\nfull per-stratum tables: {rel(out / 'test_scores.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
