"""Audit the frozen-check verdicts (analysis/out/swarmds/row_verdicts.jsonl) after scoring; writes audit.json.

    PYTHONIOENCODING=utf-8 python -m analysis.swarmds.audit

Scoring-time only (joins v_answers). Reports, per split:
  * honest trap rows by SOURCE and by spoof_class (the trap names appear as either), with our verdicts;
  * spoofed rows our combined verdict calls 'supported' (a real miss, not an abstention), with the deciding check;
  * how many contradicted spoofed rows each check localized to the row's own call (T3 pair / TC window verdicts
    with localized=False name a set of calls that contains the tampered one, not the call itself).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from analysis.swarmds import data as D

OUT = Path(__file__).resolve().parents[2] / "analysis" / "out" / "swarmds"


def main() -> int:
    db = D.connect()
    lab = D.labels(db)
    meta = {r["row_id"]: r for r in D.blind_rows(db)}
    rows = [json.loads(l) for l in open(OUT / "row_verdicts.jsonl", encoding="utf-8")]
    res = {}
    for split in ("test", "dev"):
        traps = defaultdict(Counter)
        supp_on_spoof = []
        loc = defaultdict(Counter)
        for r in rows:
            if r["split"] != split:
                continue
            a, m = lab[r["row_id"]], meta[r["row_id"]]
            for key in (m["source"], a["spoof_class"]):
                if key in D.HONEST_TRAPS:
                    traps[f"{key}|{a['label']}"][r["ours_combined"]] += 1
            if a["label"] == "spoofed" and r["ours_combined"] == "supported":
                supp_on_spoof.append({"row_id": r["row_id"], "spoof_class": a["spoof_class"], "source": m["source"],
                                      "supported_by": [k for k in ("t1_recompute", "t3_shadow_state",
                                                                   "claim_provenance") if r[k] == "supported"],
                                      "claimed": (m["claimed_output"] or "")[:160]})
            if a["label"] == "spoofed" and r["ours_combined"] == "contradicted":
                for part in (r["why"] or "").split(";"):
                    chk = part.split(":", 1)[0]
                    if "|loc=0" in part:
                        loc[chk]["not_localized"] += 1
                    else:
                        loc[chk]["localized_or_call_scoped"] += 1
        res[split] = {"honest_trap_rows_by_source_or_class": {k: dict(v) for k, v in sorted(traps.items())},
                      "spoofed_rows_called_supported": supp_on_spoof,
                      "contradicted_spoofed_localization": {k: dict(v) for k, v in sorted(loc.items())}}
    (OUT / "audit.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
