"""Phase E split: carve the sessions never used in A or B into
  E = Phase E analysis split (larger-n re-measurement and new candidates; fresh relative to Phase C, which read B), and
  H = held-out split for the Track C eval harness (manifest only; nothing reads its sessions during tuning).
Only corpora with a remainder get E/H: swechat (all remaining sessions, halved) and aiv_cu (2,000 + 2,000 stratified from the
remainder). cc_local, aiv_cc and whowhen were fully used by A+B, so they have no E or H (stated in the manifest).
Stratification reuses lib/sample.py's cell rule (stratum x length tercile, floor 5 per cell); seed = SEED + 1.
Writes analysis/cache/samples/<corpus>_EH.json and analysis/HELDOUT_MANIFEST.json (H ids + sha256 of the sorted id list).
Reads only population tables and the existing A/B sample files; opens no event data."""
import hashlib, json, os
import numpy as np
import pandas as pd

from analysis.lib import sample
from analysis.lib.stats import SEED

AN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMP = os.path.join(AN, "cache", "samples")
E_MAX = {"swechat": None, "aiv_cu": 2000}   # None = half of the remainder
H_MAX = {"swechat": None, "aiv_cu": 2000}


def population(corpus):
    if corpus == "swechat":
        p = pd.read_parquet(os.path.join(AN, "cache", "swechat_population.parquet"), columns=["session_id", "stratum", "length"])
    else:
        p = pd.read_parquet(os.path.join(AN, "cache", "aiv_cu_sessions.parquet"), columns=["session_id", "stratum", "n_turns"])
        p = p.rename(columns={"n_turns": "length"})
    return p.drop_duplicates("session_id").reset_index(drop=True)


def draw_eh(corpus):
    ab = json.load(open(os.path.join(SAMP, f"{corpus}.json"), encoding="utf-8"))
    used = set(ab["A"]) | set(ab["B"])
    pop = population(corpus)
    rest = pop[~pop.session_id.isin(used)].copy()
    rest["stratum"] = rest["stratum"].fillna("unknown").astype(str)
    q = rest["length"].rank(method="first", pct=True)
    rest["cell"] = rest["stratum"] + "|" + np.where(q <= 1 / 3, "short", np.where(q <= 2 / 3, "mid", "long"))
    rng = np.random.default_rng(SEED + 1)
    rest = rest.iloc[rng.permutation(len(rest))].reset_index(drop=True)
    n_e = E_MAX[corpus] or len(rest) // 2
    alloc_e = sample._alloc(rest.groupby("cell").size().to_dict(), min(n_e, len(rest)))
    e_ids = []
    for cell, k in alloc_e.items():
        e_ids += rest.loc[rest.cell == cell, "session_id"].head(k).tolist()
    rest2 = rest[~rest.session_id.isin(set(e_ids))]
    n_h = H_MAX[corpus] or len(rest2)
    alloc_h = sample._alloc(rest2.groupby("cell").size().to_dict(), min(n_h, len(rest2)))
    h_ids = []
    for cell, k in alloc_h.items():
        h_ids += rest2.loc[rest2.cell == cell, "session_id"].head(k).tolist()
    assert not (set(e_ids) & set(h_ids)) and not ((set(e_ids) | set(h_ids)) & used)
    out = {"corpus": corpus, "seed": SEED + 1, "population_sessions": int(len(pop)), "used_by_A_B": len(used),
           "remainder": int(len(rest)), "E": sorted(e_ids), "H": sorted(h_ids), "alloc_E": alloc_e, "alloc_H": alloc_h,
           "rule": "remainder after A+B; stratum x length tercile; floor 5 per cell; E first, H from what is left"}
    json.dump(out, open(os.path.join(SAMP, f"{corpus}_EH.json"), "w", encoding="utf-8"), indent=1)
    return out


def main():
    man = {"purpose": "Held-out split H for the Track C eval harness. Never read during tuning or analysis.",
           "corpora": {}, "no_heldout": {"cc_local": "all 309 sessions used by A+B", "aiv_cc": "all 314 runs used by A+B",
                                         "whowhen": "all 184 tasks used by A+B"}}
    for c in ("swechat", "aiv_cu"):
        o = draw_eh(c)
        ids = "\n".join(o["H"]).encode()
        man["corpora"][c] = {"n_H": len(o["H"]), "n_E": len(o["E"]), "sha256_sorted_H_ids": hashlib.sha256(ids).hexdigest(),
                             "ids_file": f"analysis/cache/samples/{c}_EH.json#H"}
        print(c, "remainder", o["remainder"], "E", len(o["E"]), "H", len(o["H"]))
    json.dump(man, open(os.path.join(AN, "HELDOUT_MANIFEST.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
