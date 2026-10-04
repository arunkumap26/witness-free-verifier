"""DEV evaluation of check T3 SHADOW STATE (verifier/checks/shadow_state.py) on data/eval/spoof_v1.db.

Protocol (binding): split by session, dev iff int(sha256(session_id), 16) % 2 == 0. Labels (v_answers) are read ONLY
for dev rows and only here, never inside the check. Honest false positives are measured on ALL honest real calls
(both splits, no labels needed): every tool call in every honest swarm transcript under data/swarm/*/transcripts, plus
the execlog rows of the DB (scored in their own session). The test split is NOT scored here.

Views given to the check (all read-only):
  injected        data/eval/injected_v1/<session>/<class>-seed<k>.jsonl (the whole tampered transcript)
  tiered / cf     the honest transcript with that call's tool_result content replaced by claimed_output
  execlog         the honest transcript as is
items.call_id is read only to locate the row's call in its session (it is provenance, not an answer column).

Usage:  python analysis/swarmds/dev_t3_state.py [--disable rule,rule] [--out PATH] [--no-honest]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("SWARMS_DATA", r"C:\Swarms\data"))
DB = DATA / "eval" / "spoof_v1.db"


def _load_t3():
    """shadow_state.py is stdlib-only, but `import verifier...` runs verifier/__init__.py (pandas, blocked on this
    host by Application Control). Load the file directly."""
    try:
        sys.path.insert(0, str(ROOT))
        from verifier.checks import shadow_state as mod  # noqa: F401
        return mod
    except Exception:
        import importlib.util
        p = ROOT / "verifier" / "checks" / "shadow_state.py"
        spec = importlib.util.spec_from_file_location("t3_shadow_state_standalone", p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod


def is_dev(session_id: str) -> bool:
    return int(hashlib.sha256(session_id.encode()).hexdigest(), 16) % 2 == 0


def load_jsonl(p) -> list[dict]:
    out = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    return out


def honest_index() -> dict[str, Path]:
    idx = {}
    for p in glob.glob(str(DATA / "swarm" / "*" / "transcripts" / "*.jsonl")):
        idx.setdefault(Path(p).stem, Path(p))
    return idx


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--disable", default="")
    ap.add_argument("--frozen", default=str(ROOT / "analysis" / "swarmds" / "frozen_t3_state.json"))
    ap.add_argument("--use-frozen", action="store_true", help="take disabled_rules from the frozen file")
    ap.add_argument("--out", default=str(ROOT / "analysis" / "swarmds" / "dev_t3_state.json"))
    ap.add_argument("--no-honest", action="store_true")
    a = ap.parse_args(argv)
    t3 = _load_t3()
    disabled = [r for r in a.disable.split(",") if r]
    if a.use_frozen:
        disabled = json.load(open(a.frozen, encoding="utf-8"))["disabled_rules"]
    params = {"disabled_rules": disabled}
    t0 = time.time()
    hidx = honest_index()

    # ---------------------------------------------------------------- honest FP on ALL honest real calls
    honest = {"n_sessions": 0, "n_calls": 0, "contradicted": 0, "supported": 0, "by_rule": Counter(),
              "by_block": Counter(), "examples": []}
    if not a.no_honest:
        for sid, p in sorted(hidx.items()):
            turns = load_jsonl(p)
            v = t3.check_session(turns, params)
            honest["n_sessions"] += 1
            honest["n_calls"] += len(v)
            for cid, r in v.items():
                if r["verdict"] == "contradicted":
                    honest["contradicted"] += 1
                    honest["by_rule"][r["rule"]] += 1
                    honest["by_block"][p.parent.parent.name] += 1
                    if len(honest["examples"]) < 40:
                        honest["examples"].append({"session": sid, "call": cid, **r})
                elif r["verdict"] == "supported":
                    honest["supported"] += 1

    # ---------------------------------------------------------------- dataset rows
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT b.row_id, b.source, b.unit, b.session_id, b.claimed_output, b.instructed_to_lie, "
                      "i.call_id FROM v_blind b JOIN items i ON i.row_id = b.row_id "
                      "WHERE b.unit = 'tool_output'").fetchall()
    sess_cache: dict[str, dict] = {}
    preds: dict[str, dict] = {}
    split_n = Counter()
    for r in rows:
        sid, src, cid = r["session_id"], r["source"], r["call_id"]
        split_n[("dev" if is_dev(sid) else "test", src)] += 1
        if src == "execlog":
            # honest rows: scored on BOTH splits (no labels needed for the FP count; label joined only on dev)
            if sid not in sess_cache:
                p = hidx.get(sid)
                sess_cache.clear()
                sess_cache[sid] = t3.check_session(load_jsonl(p), params) if p else {}
            preds[r["row_id"]] = sess_cache[sid].get(cid, {"verdict": "unconstrained", "reason": "missing:no_session"})
            continue
        if not is_dev(sid):
            continue
        if src == "injected":
            _, call_id, cls, seed = r["row_id"].split(":")
            p = DATA / "eval" / "injected_v1" / sid / f"{cls}-{seed}.jsonl"
            if not p.exists():
                preds[r["row_id"]] = {"verdict": "unconstrained", "reason": "missing:no_transcript"}
                continue
            v = t3.check_session(load_jsonl(p), params)
            preds[r["row_id"]] = v.get(call_id, {"verdict": "unconstrained", "reason": "missing:call"})
            # misattribution: contradicted verdicts on OTHER (untampered) calls of the tampered session
            preds[r["row_id"]]["_others_contra"] = sum(1 for k, x in v.items() if k != call_id
                                                       and x["verdict"] == "contradicted")
            preds[r["row_id"]]["_others_contra_localized"] = sum(1 for k, x in v.items() if k != call_id
                                                                 and x["verdict"] == "contradicted" and x.get("localized"))
        elif src in ("tiered", "counterfactual"):
            p = hidx.get(sid)
            if p is None or not cid:
                preds[r["row_id"]] = {"verdict": "unconstrained", "reason": "missing:no_transcript"}
                continue
            preds[r["row_id"]] = t3.check_call(load_jsonl(p), cid, r["claimed_output"], params)
        else:
            preds[r["row_id"]] = {"verdict": "unconstrained", "reason": "abstain:source_not_modelled"}

    # ---------------------------------------------------------------- labels (dev only) + honest execlog rows (all)
    strata = defaultdict(lambda: Counter())
    execlog_fp = Counter()
    for r in rows:
        rid, sid = r["row_id"], r["session_id"]
        if rid not in preds:
            continue
        pr = preds[rid]
        if r["source"] == "execlog":
            execlog_fp["n"] += 1
            execlog_fp[pr["verdict"]] += 1
            if not is_dev(sid):
                continue
        ans = db.execute("SELECT label, spoof_class, consistency FROM v_answers "
                         "WHERE row_id=?", (rid,)).fetchone()
        key_sets = [("spoof_class", ans["spoof_class"]), ("source", r["source"]),
                    ("source|consistency", f"{r['source']}|{ans['consistency']}"),
                    ("class|consistency", f"{ans['spoof_class']}|{ans['consistency']}"),
                    ("instructed_to_lie", f"{r['source']}|{r['instructed_to_lie']}")]
        for kname, kval in key_sets:
            c = strata[(kname, kval, ans["label"])]
            c["n"] += 1
            c[pr["verdict"]] += 1
            if pr["verdict"] == "contradicted":
                c["contra_rule:" + str(pr.get("rule"))] += 1
                c["contra_localized" if pr.get("localized", True) else "contra_pair"] += 1
            if "_others_contra" in pr:
                c["sessions_with_other_contra"] += int(pr["_others_contra"] > 0)
                c["sessions_with_other_contra_localized"] += int(pr["_others_contra_localized"] > 0)

    def fmt(c: Counter) -> dict:
        n = c["n"]
        d = {"n": n, "contradicted": c["contradicted"], "supported": c["supported"],
             "unconstrained": c["unconstrained"], "recall_contradicted": round(c["contradicted"] / n, 4) if n else None}
        d.update({k: v for k, v in c.items() if k.startswith(("contra_", "sessions_"))})
        return d

    report = {
        "check": "T3 shadow state (verifier/checks/shadow_state.py)",
        "check_version": t3.CHECK_VERSION,
        "split_rule": "dev iff int(sha256(session_id),16) % 2 == 0",
        "params": params,
        "rows_by_split_source": {f"{k[0]}|{k[1]}": v for k, v in sorted(split_n.items())},
        "honest_all_real_calls": {"n_sessions": honest["n_sessions"], "n_calls": honest["n_calls"],
                                  "contradicted_FP": honest["contradicted"], "supported": honest["supported"],
                                  "fp_by_rule": dict(honest["by_rule"]), "fp_by_block": dict(honest["by_block"]),
                                  "fp_examples": honest["examples"]},
        "honest_execlog_rows_both_splits": dict(execlog_fp),
        "dev_strata": {},
        "notes": [
            "recall_contradicted = contradicted / n; unconstrained is an abstention, not a miss (TESTER_HANDOFF s4).",
            "On spoofed rows, contra_pair counts verdicts with localized=False (jointly unsatisfiable pair, blame "
            "not localizable; the honest co-member of the pair is also flagged).",
            "sessions_with_other_contra: tampered injected sessions where some OTHER (untampered) call was also "
            "contradicted -- misattribution inside a tampered session (not an honest-session FP).",
            "claim-unit rows are out of scope for this check (tool-call check); not scored.",
        ],
        "elapsed_s": round(time.time() - t0, 1),
    }
    for (kname, kval, label), c in sorted(strata.items()):
        report["dev_strata"].setdefault(kname, {})[f"{kval} [{label}]"] = fmt(c)
    Path(a.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    hp = report["honest_all_real_calls"]
    print(f"honest: {hp['contradicted_FP']} FP / {hp['n_calls']} calls in {hp['n_sessions']} sessions; by rule {hp['fp_by_rule']}")
    print("execlog rows:", dict(execlog_fp))
    for k, v in report["dev_strata"].get("spoof_class", {}).items():
        print(f"  {k:45s} n={v['n']:5d} contra={v['contradicted']:4d} rec={v['recall_contradicted']} "
              f"sup={v['supported']} " + " ".join(f"{x}={y}" for x, y in v.items() if x.startswith(('contra_', 'sessions_'))))
    print("elapsed", report["elapsed_s"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
