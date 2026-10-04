"""Stratified, seeded, disjoint session samples.

Split A (Phase A): min(200, 40% of sessions). Split B (Phase B): up to 2,000 sessions from the remainder.
A and B never share a session, so Phase B thresholds set from Phase A are not tuned on Phase B data.

Strata = stratum label x length tercile (terciles of event or turn count within the corpus).
Allocation is proportional to stratum size with a floor of min(5, stratum size) per stratum, so small
scaffolds/models are represented. Every sample file records the population, the allocation and the seed.
"""
import json
import numpy as np
import pandas as pd

from .stats import SEED

A_MAX, A_FRAC, B_MAX = 200, 0.40, 2000


def _alloc(sizes, total, floor=5):
    sizes = {k: v for k, v in sizes.items() if v > 0}
    base = {k: min(v, floor) for k, v in sizes.items()}
    left = max(0, total - sum(base.values()))
    room = {k: sizes[k] - base[k] for k in sizes}
    tot_room = sum(room.values())
    alloc = dict(base)
    if tot_room > 0 and left > 0:
        raw = {k: left * room[k] / tot_room for k in sizes}
        for k in sizes:
            alloc[k] += min(room[k], int(np.floor(raw[k])))
        rem = total - sum(alloc.values())
        for k in sorted(sizes, key=lambda k: -(raw[k] - np.floor(raw[k]))):
            if rem <= 0:
                break
            if alloc[k] < sizes[k]:
                alloc[k] += 1
                rem -= 1
    return alloc


def draw(pop: pd.DataFrame, corpus: str):
    """pop: one row per session with columns session_id, stratum, length (int). Returns dict with A, B lists + metadata."""
    pop = pop.drop_duplicates("session_id").reset_index(drop=True).copy()
    pop["stratum"] = pop["stratum"].fillna("unknown").astype(str)
    q = pop["length"].rank(method="first", pct=True)
    pop["tercile"] = np.where(q <= 1 / 3, "short", np.where(q <= 2 / 3, "mid", "long"))
    pop["cell"] = pop["stratum"] + "|" + pop["tercile"]
    rng = np.random.default_rng(SEED)
    pop = pop.iloc[rng.permutation(len(pop))].reset_index(drop=True)
    n_a = min(A_MAX, int(np.floor(A_FRAC * len(pop))))
    sizes = pop.groupby("cell").size().to_dict()
    alloc_a = _alloc(sizes, n_a)
    a_ids = []
    for cell, k in alloc_a.items():
        a_ids += pop.loc[pop.cell == cell, "session_id"].head(k).tolist()
    rest = pop[~pop.session_id.isin(set(a_ids))]
    n_b = min(B_MAX, len(rest))
    alloc_b = _alloc(rest.groupby("cell").size().to_dict(), n_b)
    b_ids = []
    for cell, k in alloc_b.items():
        b_ids += rest.loc[rest.cell == cell, "session_id"].head(k).tolist()
    assert not set(a_ids) & set(b_ids)
    return {"corpus": corpus, "seed": SEED, "population_sessions": int(len(pop)),
            "population_by_cell": {k: int(v) for k, v in sizes.items()},
            "A": sorted(a_ids), "B": sorted(b_ids), "alloc_A": alloc_a, "alloc_B": alloc_b,
            "rule": "A=min(200,40%); B=up to 2000 from remainder; stratum x length tercile; floor 5 per cell"}


def save(sample, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=1)
