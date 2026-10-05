"""Claude as a judge vs our frozen checks vs the rule-based baseline, on the SAME 120 test-split rows.

    PYTHONIOENCODING=utf-8 python -m analysis.probes.claude_judge_compare [--data DIR]      (from the repo root)

Inputs (read-only):
  analysis/out/claude_judge/claude_verdicts.json  Claude's raw verdicts, opaque ids J001..J120 (as returned)
  analysis/out/claude_judge/key.json              opaque id -> row_id (written by analysis/swarmds/judge_subset.py)
  analysis/out/claude_judge/subset.json           per-item sampling stratum + per-stratum test pool sizes
  analysis/out/swarmds/row_verdicts.jsonl         ours (frozen v1), the baseline replay, ours OR baseline; every row
  analysis/out/swarmds/row_verdicts_v2.jsonl      optional: ours with T3 v2 rules (POST-HOC); skipped if absent
  <data>/spoof_v1.db  v_answers                   labels (scoring only), v_blind source/unit (honest-trap strata)
Writes analysis/out/claude_judge/compare.json and compare.txt.

Verdicts are three-valued for every system: contradicted (= flagged as spoofed), supported, unconstrained (abstain).
On a spoofed row only 'contradicted' counts as caught; 'supported' is a miss (a wrong pass), 'unconstrained' an
abstention. On an honest row 'contradicted' is a false positive. The rule baseline never abstains on tool outputs:
its 'supported' there means "no rule fired", not that it vouched for the content.
Systems marked combination=True are combinations of the observed verdicts, not pre-registered systems.
Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from analysis.swarmds import data as D
from analysis.swarmds.judge_subset import STRATA

ROOT = Path(__file__).resolve().parents[2]
CJ = ROOT / "analysis" / "out" / "claude_judge"
SW = ROOT / "analysis" / "out" / "swarmds"
VERDICTS = ("contradicted", "supported", "unconstrained")
Z95 = 1.959963984540054
JUDGE = {"model": "Claude Opus 5.5 (claude-opus-5-5)",
         "harness": "subagents launched by the orchestrator session; each read only its own batch file",
         "items_per_call": 5, "n_calls": 24}


# ------------------------------------------------------------------------------------------------------ helpers
def wilson(k: int, n: int) -> list | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + Z95 ** 2 / n
    c = (p + Z95 ** 2 / (2 * n)) / den
    h = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / den
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if p.is_file() else None


def load_jsonl(p: Path, keep: set | None = None) -> dict:
    out = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if keep is None or r["row_id"] in keep:
                out[r["row_id"]] = r
    return out


def r4(x):
    return None if x is None else round(x, 4)


def tally(items: list[dict], s: str) -> dict:
    hon = Counter(it["v"][s] for it in items if it["label"] == "not_spoofed")
    spo = Counter(it["v"][s] for it in items if it["label"] == "spoofed")
    nh, ns = sum(hon.values()), sum(spo.values())
    tp, fp = spo["contradicted"], hon["contradicted"]
    decided = tp + spo["supported"] + fp + hon["supported"]
    return {
        "honest": {"n": nh, "false_positives": fp, "supported": hon["supported"], "abstain": hon["unconstrained"],
                   "fp_rate": r4(fp / nh) if nh else None, "fp_rate_wilson95": wilson(fp, nh)},
        "spoofed": {"n": ns, "caught": tp, "missed_supported": spo["supported"], "abstain": spo["unconstrained"],
                    "recall": r4(tp / ns) if ns else None, "recall_wilson95": wilson(tp, ns)},
        "precision": r4(tp / (tp + fp)) if tp + fp else None, "precision_wilson95": wilson(tp, tp + fp),
        "decided": decided,
        "correct_when_decided": r4((tp + hon["supported"]) / decided) if decided else None,
    }


def outcome(label: str, v: str) -> str:
    if v == "unconstrained":
        return "abstain"
    return "correct" if (v == "contradicted") == (label == "spoofed") else "wrong"


# ------------------------------------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="dataset root (default: WFV_DATA / SWARMS_DATA / ./dataset)")
    a = ap.parse_args()
    D.set_root(a.data)
    D.require()

    raw = json.loads((CJ / "claude_verdicts.json").read_text(encoding="utf-8"))
    key = json.loads((CJ / "key.json").read_text(encoding="utf-8"))
    subset = json.loads((CJ / "subset.json").read_text(encoding="utf-8"))
    claude = {x["id"]: x for x in raw}
    assert len(claude) == len(raw) == len(key) == subset["n_items"], "verdict / key / subset sizes differ"
    assert set(claude) == set(key), "verdict ids do not match the key"
    assert all(x["verdict"] in VERDICTS for x in raw), "unknown verdict value"
    sub_items = {x["id"]: x for x in subset["items"]}
    assert all(sub_items[j]["row_id"] == key[j] for j in key), "key.json and subset.json disagree"

    rids = set(key.values())
    v1 = load_jsonl(SW / "row_verdicts.jsonl")
    p2 = SW / "row_verdicts_v2.jsonl"
    v2 = load_jsonl(p2) if p2.is_file() else None

    db = D.connect()
    labs = D.labels(db)
    blind = D.blind_rows(db)
    meta = {r["row_id"]: r for r in blind if r["row_id"] in rids}

    systems = {
        "claude_judge": {"what": "Claude Opus 5.5 as a judge on blinded evidence (see CLAUDE_JUDGE_COMPARISON.md)"},
        "ours_v1": {"what": "ours_combined, frozen v1 rules (T0+T1+T3+TC+claim provenance), row_verdicts.jsonl"},
        "rule_baseline": {"what": "swarm/delta.py oracles via eval/score_detector.py:detect, replayed per row"},
        "ours_v1_or_baseline": {"what": "shipped union: contradicted if ours_v1 or the baseline contradicts"},
    }
    if v2 is not None:
        systems["ours_v2_posthoc"] = {"what": "ours_combined with T3 v2 rules; POST-HOC (frozen after v1 test "
                                              "numbers were seen)", "post_hoc": True}
        systems["ours_v2_or_baseline_posthoc"] = {"what": "union of ours_v2 and the baseline; POST-HOC",
                                                  "post_hoc": True}
    systems["ours_v1_or_claude"] = {"what": "contradicted if ours_v1 or Claude contradicts; else supported if either "
                                            "supports; else unconstrained", "combination": True}
    systems["ours_v1_then_claude"] = {"what": "cascade: ours_v1's verdict where it decides; Claude's verdict only "
                                              "where ours_v1 abstains", "combination": True}

    items = []
    for jid in sorted(key):
        rid = key[jid]
        lab = labs[rid]
        assert lab["label"] == sub_items[jid]["label"], f"label mismatch {jid}"
        r1 = v1[rid]
        assert r1["split"] == "test", f"{jid} not in test split"
        cv = claude[jid]["verdict"]
        v = {"claude_judge": cv, "ours_v1": r1["ours_combined"], "rule_baseline": r1["baseline"],
             "ours_v1_or_baseline": r1["union_ours_baseline"]}
        if v2 is not None:
            r2 = v2[rid]
            assert r2["baseline"] == r1["baseline"], f"baseline differs between v1 and v2 files for {rid}"
            v["ours_v2_posthoc"] = r2["ours_combined"]
            v["ours_v2_or_baseline_posthoc"] = r2["union_ours_baseline"]
        o = r1["ours_combined"]
        v["ours_v1_or_claude"] = ("contradicted" if "contradicted" in (o, cv) else
                                  "supported" if "supported" in (o, cv) else "unconstrained")
        v["ours_v1_then_claude"] = o if o != "unconstrained" else cv
        m = meta[rid]
        trap = m["source"] in D.HONEST_TRAPS or lab["spoof_class"] in D.HONEST_TRAPS
        stratum = sub_items[jid]["stratum"]
        if lab["label"] == "spoofed":
            group = ("spoofed/claims" if m["unit"] == "claim" else
                     "spoofed/injected" if lab["spoof_class"].startswith("injected_") else
                     "spoofed/tiered" if lab["spoof_class"].startswith("tiered_") else
                     "spoofed/counterfactual" if lab["spoof_class"] == "counterfactual" else "spoofed/other")
        else:
            group = ("honest/tool_outputs" if m["unit"] == "tool_output" else
                     "honest/claims_traps" if trap else "honest/claims_other")
        items.append({"id": jid, "row_id": rid, "label": lab["label"], "spoof_class": lab["spoof_class"],
                      "unit": m["unit"], "source": m["source"], "stratum": stratum, "group": group,
                      "honest_trap": trap, "v": v, "ours_why": r1.get("why"),
                      "claude_reason": claude[jid]["reason"]})

    names = list(systems)
    overall = {s: tally(items, s) for s in names}
    by_unit = {u: {s: tally([i for i in items if i["unit"] == u], s) for s in names}
               for u in ("tool_output", "claim")}
    groups = sorted({i["group"] for i in items})
    by_group = {g: {"n": sum(1 for i in items if i["group"] == g),
                    "verdicts": {s: dict(Counter(i["v"][s] for i in items if i["group"] == g)) for s in names}}
                for g in groups}

    # fine strata, with ours on the WHOLE test pool of each stratum for context (same predicates as the sampler)
    test_rows = [r for r in blind if D.split_of(r["session_id"]) == "test"]
    pool_def = {d["stratum"]: d for d in subset["strata_definition"]}
    by_stratum = {}
    for name, want, pred, _n in STRATA:
        its = [i for i in items if i["stratum"] == name]
        pool = [r for r in test_rows if labs[r["row_id"]]["label"] == want and pred(r, labs[r["row_id"]])]
        assert len(pool) == pool_def[name]["test_pool_size"], f"pool size changed for {name}"
        pc = {m: Counter(v1[r["row_id"]][k] for r in pool)
              for m, k in (("ours_v1", "ours_combined"), ("rule_baseline", "baseline"),
                           ("ours_v1_or_baseline", "union_ours_baseline"))}
        by_stratum[name] = {
            "label": want, "n_in_subset": len(its), "test_pool_size": len(pool),
            "verdicts_in_subset": {s: dict(Counter(i["v"][s] for i in its)) for s in names},
            "contradicted_rate_in_subset": {s: r4(sum(i["v"][s] == "contradicted" for i in its) / len(its))
                                            for s in names},
            "whole_test_pool_contradicted_rate": {m: r4(c["contradicted"] / len(pool)) for m, c in pc.items()},
        }

    # stratum-weighted recall on spoofed tool outputs: weight each subset stratum by its test pool size
    tool_strata = [n for n, w, *_ in STRATA if n.startswith("spoofed_tool/")]
    wsum = sum(by_stratum[n]["test_pool_size"] for n in tool_strata)
    pool_weighted = {s: r4(sum(by_stratum[n]["test_pool_size"] * by_stratum[n]["contradicted_rate_in_subset"][s]
                               for n in tool_strata) / wsum) for s in names}
    ours_pool_actual = sum(by_stratum[n]["test_pool_size"] * by_stratum[n]["whole_test_pool_contradicted_rate"]["ours_v1"]
                           for n in tool_strata) / wsum

    disagreements = []
    for i in items:
        if i["v"]["claude_judge"] != i["v"]["ours_v1"]:
            d = {"id": i["id"], "row_id": i["row_id"], "label": i["label"], "stratum": i["stratum"],
                 "claude": i["v"]["claude_judge"], "ours_v1": i["v"]["ours_v1"]}
            if v2 is not None:
                d["ours_v2_posthoc"] = i["v"]["ours_v2_posthoc"]
            d.update({"rule_baseline": i["v"]["rule_baseline"],
                      "claude_outcome": outcome(i["label"], i["v"]["claude_judge"]),
                      "ours_v1_outcome": outcome(i["label"], i["v"]["ours_v1"]),
                      "ours_why": i["ours_why"], "claude_reason": i["claude_reason"]})
            disagreements.append(d)
    dis_kinds = Counter(f"claude={d['claude_outcome']}|ours={d['ours_v1_outcome']}|label={d['label']}"
                        for d in disagreements)
    v1_v2_diff = ([{"id": i["id"], "row_id": i["row_id"], "ours_v1": i["v"]["ours_v1"],
                    "ours_v2_posthoc": i["v"]["ours_v2_posthoc"]}
                   for i in items if i["v"]["ours_v1"] != i["v"]["ours_v2_posthoc"]] if v2 is not None else None)
    cascade_calls = sum(1 for i in items if i["v"]["ours_v1"] == "unconstrained")
    # whole test split: how many rows a cascade (ours first, Claude only where ours abstains) would send to Claude
    unit_of = {r["row_id"]: r["unit"] for r in test_rows}
    nat = defaultdict(Counter)
    for rid, r in v1.items():
        if r["split"] == "test":
            nat[f"{unit_of[rid]}|{labs[rid]['label']}"]["rows"] += 1
            nat[f"{unit_of[rid]}|{labs[rid]['label']}"]["ours_v1_abstains"] += r["ours_combined"] == "unconstrained"
    nat_tot = Counter()
    for c in nat.values():
        nat_tot.update(c)

    J = {
        "what": "Claude as a judge vs our frozen checks vs the rule-based baseline on the same 120 test-split rows",
        "script": "analysis/probes/claude_judge_compare.py",
        "judge": JUDGE,
        "subset": {"builder": subset["builder"], "seed": subset["seed"], "split": subset["split"],
                   "n_items": subset["n_items"], "counts_by_label": subset["counts_by_label"],
                   "counts_by_unit_label": subset["counts_by_unit_label"],
                   "items_with_omitted_turns": subset["items_with_omitted_turns"],
                   "leak_audit_leaks": len(subset["leak_audit"]["leaks"])},
        "inputs_sha256_lf": {p: sha(ROOT / p) for p in (
            "analysis/out/claude_judge/claude_verdicts.json", "analysis/out/claude_judge/key.json",
            "analysis/out/claude_judge/subset.json", "analysis/out/swarmds/row_verdicts.jsonl",
            "analysis/out/swarmds/row_verdicts_v2.jsonl")},
        "verdict_semantics": ("contradicted = flagged as spoofed; supported = passed; unconstrained = abstained. "
                              "Spoofed row: only contradicted is caught; supported is a miss (wrong pass). Honest "
                              "row: contradicted is a false positive. The rule baseline never abstains on tool "
                              "outputs ('supported' = no rule fired)."),
        "systems": systems,
        "overall": overall,
        "by_unit": by_unit,
        "by_group": by_group,
        "by_stratum": by_stratum,
        "pool_weighted_recall_spoofed_tool_outputs": {
            "how": ("each spoofed tool-output stratum's caught rate in the subset, weighted by that stratum's size "
                    "in the whole test split (rough: 4 to 6 rows per stratum)"),
            "strata": tool_strata, "total_pool": wsum, "estimate": pool_weighted,
            "ours_v1_actual_on_these_pools": r4(ours_pool_actual)},
        "cascade_claude_calls_needed": {
            "subset": {"rows_sent_to_claude": cascade_calls, "of": len(items)},
            "whole_test_split": {"by_unit_label": {k: dict(c) for k, c in sorted(nat.items())},
                                 "total": dict(nat_tot),
                                 "share_sent_to_claude": r4(nat_tot["ours_v1_abstains"] / nat_tot["rows"])}},
        "disagreements_claude_vs_ours_v1": {"n": len(disagreements), "kinds": dict(dis_kinds.most_common()),
                                            "rows": disagreements},
        "ours_v1_vs_v2_differences_in_subset": v1_v2_diff,
        "per_item": [{k: i[k] for k in ("id", "row_id", "label", "spoof_class", "unit", "stratum", "group",
                                         "honest_trap")} | {"verdicts": i["v"]} for i in items],
    }
    CJ.mkdir(parents=True, exist_ok=True)
    (CJ / "compare.json").write_text(json.dumps(J, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---- text summary
    L = []
    w = L.append
    w("CLAUDE AS A JUDGE vs OURS vs RULE BASELINE -- same 120 test-split rows (60 honest, 60 spoofed)")
    w(f"{'system':32s} {'FP/60':>6s} {'FP 95% CI':>15s} {'caught/60':>9s} {'recall':>7s} {'recall 95% CI':>15s} "
      f"{'miss':>5s} {'abst(s)':>7s} {'abst(h)':>7s} {'prec':>6s}")
    for s in names:
        t = overall[s]
        h, p = t["honest"], t["spoofed"]
        w(f"{s:32s} {h['false_positives']:>6d} {str(h['fp_rate_wilson95']):>15s} {p['caught']:>9d} "
          f"{p['recall']:>7.3f} {str(p['recall_wilson95']):>15s} {p['missed_supported']:>5d} {p['abstain']:>7d} "
          f"{h['abstain']:>7d} {str(t['precision']):>6s}")
    w("")
    w("caught per group (contradicted / n)")
    w(f"{'group':26s} {'n':>3s} " + " ".join(f"{s[:14]:>14s}" for s in names))
    for g in groups:
        n = by_group[g]["n"]
        w(f"{g:26s} {n:>3d} " + " ".join(f"{by_group[g]['verdicts'][s].get('contradicted', 0):>14d}" for s in names))
    w("")
    w(f"pool-weighted recall on spoofed tool outputs (rough): {pool_weighted}  "
      f"(ours_v1 actual on those pools: {ours_pool_actual:.4f})")
    w(f"disagreements Claude vs ours_v1: {len(disagreements)}  {dict(dis_kinds.most_common())}")
    w(f"cascade ours_v1 -> Claude: Claude needed on {cascade_calls}/{len(items)} subset rows; on the whole test "
      f"split {nat_tot['ours_v1_abstains']}/{nat_tot['rows']} rows")
    txt = "\n".join(L) + "\n"
    (CJ / "compare.txt").write_text(txt, encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
