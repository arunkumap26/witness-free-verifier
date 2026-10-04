"""Shared plumbing for the Phase E new-corpus loaders (Track B corpora): split, secret redaction, IR cache writer,
build report, A-split calibration hand-off. Each analysis/loaders/load_<corpus>.py supplies only the corpus-specific
population census and session parser.

Pre-registered split rule (analysis/prereg_e.json splits.new_corpora, applied here verbatim):
  N = sessions that pass the loader's field audit. A = min(200, floor(0.2 N)). R = N - A.
  B = min(2000, floor(R / 3)), E = min(2000, floor(R / 3)), H = the remainder.
  Cells = lib/sample cells: stratum x length tercile, terciles from rank(method='first', pct=True) over the whole
  population table (sorted by session_id), the same rule as prereg_e_common.population_cells(). The population is
  permuted once with numpy default_rng(SEED_NEW_CORPUS = 20261006); each split takes the head of each cell of what is
  left, in the order A, B, E; H is everything left after E.
  Allocation reuses lib/sample._alloc (proportional to cell size, largest remainder). FLOOR: lib/sample's floor is
  min(5, cell size); for a small corpus the floors alone can exceed the split total (e.g. 46 sessions, A = 9, 6 cells),
  and _alloc would then return MORE sessions than the rule allows. The floor used is therefore
  min(5, floor(split_total / n_cells)) (recorded per split as `floor_used`), which equals 5 whenever the floors fit.

Split files (ids): analysis/cache/samples/<corpus>.json (keys A, B), analysis/cache/samples/<corpus>_EH.json (keys E, H).
Held-out manifest for the new corpus: analysis/out/phase_e/heldout_manifest_<corpus>.json (sha256 of the sorted H ids
joined by '\n', the same digest phase_e_split.py writes into HELDOUT_MANIFEST.json, which is NOT edited here).
Index of A/B/E sessions (ids, split, source path; no content): analysis/cache/<corpus>_index.parquet. H is never indexed.

Secrets: the public sources carry credential-like values (CORPUS_INVENTORY.md 2.4). Every string that goes into the IR
(text, args, command, stderr, extra) passes through redact() before the frame is built. A match is replaced by
'[REDACTED:loader:<type>]' and counted by type and column (counts only; values are never printed or stored).
"""
import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from analysis.lib import ir, sample

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "analysis" / "cache"
SAMPLES = CACHE / "samples"
OUT_E = ROOT / "analysis" / "out" / "phase_e"
EXT_DIR = OUT_E / "prereg_e_extensions"
DATA = Path(os.environ.get("SWARMS_DATA", "C:/Swarms/data")) / "acquired"
SEED_NEW_CORPUS = 20261006  # == prereg_e_common.SEED_NEW_CORPUS (asserted in calibrate())
A_MAX, A_FRAC, BE_MAX = 200, 0.2, 2000

SCHEMA = pa.schema([(c, {"str": pa.string(), "int64": pa.int64(), "Int64": pa.int64(), "boolean": pa.bool_()}[t])
                    for c, t in ir.COLUMNS.items()])

# ------------------------------------------------------------------------------------------------------------ secrets
SECRET_RX = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-|None-)?[A-Za-z0-9_\-]{20,}")),
    ("openrouter_key", re.compile(r"\bsk-or-v1-[A-Za-z0-9]{20,}")),
    ("hf_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("aws_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("bearer", re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9_\-\.=+/]{20,}")),
    ("auth_header", re.compile(r"(?i)((?:x-api-key|api[-_]?key|authorization|access[-_]?token|auth[-_]?token)"
                               r"[\"']?\s*[:=]\s*[\"']?)(?!\[REDACTED)[A-Za-z0-9_\-\.=+/]{20,}")),
]


def redact(s, counter=None, col="?"):
    """Replace credential-like substrings. Returns the redacted string (None-safe)."""
    if not isinstance(s, str) or not s:
        return s
    for name, rx in SECRET_RX:
        if name in ("bearer", "auth_header"):
            s2, n = rx.subn(lambda m: m.group(1) + f"[REDACTED:loader:{name}]", s)
        else:
            s2, n = rx.subn(f"[REDACTED:loader:{name}]", s)
        if n:
            s = s2
            if counter is not None:
                counter[f"{col}:{name}"] += n
    return s


def redact_events(events, counter):
    for e in events:
        for col in ("text", "args", "command", "stderr", "extra"):
            v = e.get(col)
            if isinstance(v, str) and v:
                e[col] = redact(v, counter, col)
    return events


# ------------------------------------------------------------------------------------------------------------ splits
def _take(df, n):
    sizes = df.groupby("cell").size().to_dict()
    n = min(n, len(df))
    floor = min(5, n // max(1, len(sizes)))
    alloc = sample._alloc(sizes, n, floor=floor)
    ids = []
    for cell, k in alloc.items():
        ids += df.loc[df.cell == cell, "session_id"].head(k).tolist()
    assert len(ids) == n, (len(ids), n)
    return ids, {k: int(v) for k, v in alloc.items()}, floor


def split_population(pop):
    """pop: session_id, stratum, length. Returns the split dict (A, B, E, H + allocations)."""
    pop = pop.drop_duplicates("session_id").sort_values("session_id").reset_index(drop=True).copy()
    pop["session_id"] = pop.session_id.astype(str)
    pop["stratum"] = pop["stratum"].fillna("unknown").astype(str)
    q = pop["length"].rank(method="first", pct=True)
    pop["tercile"] = np.where(q <= 1 / 3, "short", np.where(q <= 2 / 3, "mid", "long"))
    pop["cell"] = pop["stratum"] + "|" + pop["tercile"]
    cells = dict(zip(pop.session_id, pop.cell))
    rng = np.random.default_rng(SEED_NEW_CORPUS)
    perm = pop.iloc[rng.permutation(len(pop))].reset_index(drop=True)
    N = len(perm)
    nA = min(A_MAX, int(math.floor(A_FRAC * N)))
    a, alloc_a, fa = _take(perm, nA)
    rest = perm[~perm.session_id.isin(set(a))]
    R = len(rest)
    nB = min(BE_MAX, R // 3)
    nE = min(BE_MAX, R // 3)
    b, alloc_b, fb = _take(rest, nB)
    rest2 = rest[~rest.session_id.isin(set(b))]
    e, alloc_e, fe = _take(rest2, nE)
    h = rest2[~rest2.session_id.isin(set(e))].session_id.tolist()
    alloc_h = {k: int(v) for k, v in Counter(cells[s] for s in h).items()}
    assert len(set(a) | set(b) | set(e) | set(h)) == N and len(a) + len(b) + len(e) + len(h) == N
    return {"N": N, "R": R, "A": sorted(a), "B": sorted(b), "E": sorted(e), "H": sorted(h),
            "alloc_A": alloc_a, "alloc_B": alloc_b, "alloc_E": alloc_e, "alloc_H": alloc_h,
            "floor_used": {"A": fa, "B": fb, "E": fe},
            "population_by_cell": {k: int(v) for k, v in Counter(cells.values()).items()}, "cells": cells}


def sha_ids(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def write_splits(corpus, sp, loader_path):
    """Writes samples/<corpus>.json, samples/<corpus>_EH.json and out/phase_e/heldout_manifest_<corpus>.json."""
    SAMPLES.mkdir(parents=True, exist_ok=True)
    rule = ("prereg_e.json splits.new_corpora: A=min(200,floor(0.2N)); R=N-A; B=E=min(2000,floor(R/3)); H=remainder; "
            "stratum x length tercile (population terciles); lib/sample._alloc with floor=min(5,floor(n/n_cells)); "
            "seed SEED_NEW_CORPUS=20261006; one permutation, A then B then E take cell heads, H = rest")
    ab = {"corpus": corpus, "seed": SEED_NEW_CORPUS, "population_sessions": sp["N"],
          "population_by_cell": sp["population_by_cell"], "A": sp["A"], "B": sp["B"], "alloc_A": sp["alloc_A"],
          "alloc_B": sp["alloc_B"], "floor_used": {k: sp["floor_used"][k] for k in ("A", "B")}, "rule": rule,
          "loader": loader_path}
    eh = {"corpus": corpus, "seed": SEED_NEW_CORPUS, "population_sessions": sp["N"],
          "used_by_A_B": len(sp["A"]) + len(sp["B"]), "remainder": sp["R"] - len(sp["B"]), "E": sp["E"], "H": sp["H"],
          "alloc_E": sp["alloc_E"], "alloc_H": sp["alloc_H"], "floor_used": {"E": sp["floor_used"]["E"]}, "rule": rule}
    p_ab, p_eh = SAMPLES / f"{corpus}.json", SAMPLES / f"{corpus}_EH.json"
    p_ab.write_text(json.dumps(ab, indent=1), encoding="utf-8")
    p_eh.write_text(json.dumps(eh, indent=1), encoding="utf-8")
    man = {"purpose": "Held-out split H of a Track B corpus for the Track C eval harness. Never read during tuning or "
                      "analysis. Kept outside analysis/HELDOUT_MANIFEST.json until the orchestrator merges it.",
           "corpus": corpus, "n_H": len(sp["H"]), "n_E": len(sp["E"]), "sha256_sorted_H_ids": sha_ids(sp["H"]),
           "digest_rule": "sha256('\\n'.join(sorted(H ids)).encode()) as analysis/probes/phase_e_split.py",
           "ids_file": f"analysis/cache/samples/{corpus}_EH.json#H"}
    p_man = OUT_E / f"heldout_manifest_{corpus}.json"
    p_man.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return {"samples": str(p_ab.relative_to(ROOT).as_posix()), "samples_EH": str(p_eh.relative_to(ROOT).as_posix()),
            "heldout_manifest": str(p_man.relative_to(ROOT).as_posix()),
            "sha256_samples": sha256_file(p_ab), "sha256_samples_EH": sha256_file(p_eh)}


def split_sizes_by_stratum(sp):
    out = {}
    for k in ("A", "B", "E", "H"):
        c = Counter(sp["cells"][s].split("|")[0] for s in sp[k])
        out[k] = {"total": len(sp[k]), "by_stratum": dict(sorted(c.items()))}
    return out


def write_index(corpus, sp, pop, source_col="source"):
    """A/B/E ids with their source path (no content). H is not indexed."""
    rows = []
    src = dict(zip(pop.session_id.astype(str), pop[source_col].astype(str)))
    for k in ("A", "B", "E"):
        for s in sp[k]:
            rows.append({"session_id": s, "split": k, "source": src[s]})
    df = pd.DataFrame(rows)
    path = CACHE / f"{corpus}_index.parquet"
    df.to_parquet(path, index=False)
    return str(path.relative_to(ROOT).as_posix())


def split_ids(corpus, split):
    """A, B from samples/<corpus>.json; E from <corpus>_EH.json key 'E'. Refuses H."""
    assert split in ("A", "B", "E"), f"split {split!r} refused (H is never built in Phase E)"
    if split in ("A", "B"):
        return list(json.loads((SAMPLES / f"{corpus}.json").read_text(encoding="utf-8"))[split])
    return list(json.loads((SAMPLES / f"{corpus}_EH.json").read_text(encoding="utf-8"))["E"])


# ------------------------------------------------------------------------------------------------------------ cache
_SURR = re.compile("[\ud800-\udfff]")


def _fix_surrogates(events):
    n = 0
    for e in events:
        for c, t in ir.COLUMNS.items():
            v = e.get(c)
            if t == "str" and isinstance(v, str) and _SURR.search(v):
                e[c] = v.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
                n += 1
    return n


def session_frame(events, corpus):
    """Events of one session -> validated IR frame (corpus column set, seq re-numbered 0..n-1 in list order)."""
    for i, e in enumerate(events):
        e["corpus"] = corpus
        e["seq"] = i
    nsur = _fix_surrogates(events)
    df = ir.to_frame(events)
    ir.validate(df)
    return df, nsur


def write_cache(frames, path):
    df = pd.concat(frames, ignore_index=True) if frames else ir.to_frame([])
    tbl = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    tmp = str(path) + ".tmp"
    pq.write_table(tbl, tmp, compression="zstd")
    os.replace(tmp, path)
    back = pq.read_table(path).to_pandas(types_mapper={pa.string(): pd.StringDtype(), pa.int64(): pd.Int64Dtype(),
                                                       pa.bool_(): pd.BooleanDtype()}.get)
    back["seq"] = back["seq"].astype("int64")
    v = ir.validate(back)
    return {"path": str(Path(path).relative_to(ROOT).as_posix()) if str(path).startswith(str(ROOT)) else str(path),
            "rows": int(len(df)), "sessions": int(df.session_id.nunique()) if len(df) else 0,
            "bytes": os.path.getsize(path), "validate": {k: int(x) for k, x in v.items()}}


# ------------------------------------------------------------------------------------------------------------ report
_REQ_FAMILIES = [("anthropic_req", re.compile(r"^req_")), ("openai_chatcmpl", re.compile(r"^chatcmpl-")),
                 ("openai_resp", re.compile(r"^resp_")), ("anthropic_msg", re.compile(r"^msg_")),
                 ("openrouter_gen", re.compile(r"^gen-")),
                 ("uuid", re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I))]


def id_family(s):
    if not isinstance(s, str):
        return None
    for name, rx in _REQ_FAMILIES:
        if rx.search(s):
            return name
    return "other"


def cache_report(df):
    """Counts on an IR frame: kinds, pairing, ts, error/usage/request-id fill."""
    from analysis.probes import prereg_e_common as pe
    out = {"rows": int(len(df)), "sessions": int(df.session_id.nunique())}
    out["events_by_kind"] = {k: int(v) for k, v in df.kind.value_counts().items()}
    calls = df[df.kind == "call"]
    res = df[df.kind == "result"]
    ck = set(zip(calls.session_id, calls.call_id.astype(str)))
    rk = set(zip(res.session_id, res.call_id.astype(str)))
    out["pairing"] = {"calls": int(len(calls)), "results": int(len(res)),
                      "calls_with_result": int(sum(1 for k in ck if k in rk)),
                      "calls_without_result": int(sum(1 for k in ck if k not in rk)),
                      "results_without_call": int(sum(1 for k in rk if k not in ck)) + int(res.call_id.isna().sum()),
                      "duplicate_call_ids": int(len(calls) - len(ck)),
                      "synthetic_call_ids": int(calls.extra.astype(object).map(
                          lambda e: isinstance(e, str) and '"synthetic_call_id":true' in e).sum())}
    out["ts_kind"] = {k: int(v) for k, v in df.ts_kind.value_counts().items()}
    fr = Counter(ir.frac_digits(t) for t in df.ts.dropna().astype(str))
    out["ts_fractional_digits"] = {str(k): int(v) for k, v in sorted(fr.items())}
    out["ts_null_by_kind"] = {k: int(v) for k, v in df[df.ts.isna()].kind.value_counts().items()}
    from analysis.probes import prereg_common as pc
    P = pc.make_pairs(df[df.kind.isin(["call", "result"])])
    d = P.delta_s.to_numpy() if len(P) else np.array([])
    out["pairs_delta"] = {"pairs": int(len(P)), "stamped": int(np.isfinite(d).sum()),
                          "delta_gt_0": int((d > 0).sum()), "delta_eq_0": int((d == 0).sum()),
                          "delta_lt_0": int((d < 0).sum()),
                          "q50_s": float(np.nanmedian(d)) if np.isfinite(d).any() else None}
    out["native_error"] = {"results": int(len(res)), "nonnull": int(res.native_error.notna().sum()),
                           "true": int((res.native_error == True).sum()),  # noqa: E712
                           "exit_code_nonnull": int(res.exit_code.notna().sum()),
                           "stderr_nonnull": int(res.stderr.notna().sum())}
    u = df[df.usage_in.notna() | df.usage_out.notna()]
    out["usage"] = {"rows_with_usage": int(len(u)), "by_kind": {k: int(v) for k, v in u.kind.value_counts().items()},
                    "distinct_session_api_msg_id": int(u[["session_id", "api_msg_id"]].drop_duplicates().shape[0]),
                    "api_msg_id_null_on_usage_rows": int(u.api_msg_id.isna().sum()),
                    "cache_read_nonnull": int(df.usage_cache_read.notna().sum())}
    rid = df.request_id.dropna().astype(str)
    fam = Counter(id_family(x) for x in rid.unique())
    dec = sum(1 for x in rid.unique() if pe.decode_req_ms(x) is not None)
    out["request_id"] = {"rows_nonnull": int(len(rid)), "distinct": int(rid.nunique()),
                         "sessions_with_any": int(df[df.request_id.notna()].session_id.nunique()),
                         "families_distinct": dict(fam), "decodable_anthropic_req_ms": int(dec)}
    am = df.api_msg_id.dropna().astype(str)
    am = am[~am.str.startswith("synthetic:")]
    out["api_msg_id"] = {"rows_nonnull_nonsynthetic": int(len(am)), "distinct": int(am.nunique()),
                         "families_distinct": dict(Counter(id_family(x) for x in am.unique()))}
    out["tools"] = {k: int(v) for k, v in calls.tool.value_counts().head(25).items()}
    out["models"] = {k: int(v) for k, v in df.model.dropna().value_counts().head(15).items()}
    out["is_subagent_rows"] = int((df.is_subagent == True).sum())  # noqa: E712
    return out


def cluster_dominance(df, cluster_by_session):
    """AC4-style dominance with a real cluster label (e.g. uploader), weight = calls per session (context only)."""
    from analysis.probes import prereg_e_common as pe
    w = df[df.kind == "call"].groupby("session_id").size().to_dict()
    d = pe.dominance(w, {s: cluster_by_session.get(s, "unknown") for s in w})
    return {k: d.get(k) for k in ("top_cluster", "top_share_events", "top_share_sessions", "top_session_share_events",
                                  "n_clusters", "dominated")}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------------------ calibration
def _resolve_unit(res, pj, corpus, unit_as):
    resolved = {}
    if "n1" in res:
        q = res["n1"]["residuals"].get("quantiles", {})
        if res["n1"]["bounds_ok"]:
            resolved["n1"] = {"bounds": [q["q0.005"], q["q0.995"]], "source": "unit", "n_A": q["n"],
                              "sessions_A": q.get("n_sessions")}
        else:
            pool = [v for v in pj["resolved"]["n1"].values() if isinstance(v, dict) and "pooled_n_A" in v]
            pb = pool[0] if pool else {}
            resolved["n1"] = {"bounds": pb.get("bounds"),
                              "source": "pooled bounds from prereg_e.json resolved.n1 (unit has < 500 A residuals or "
                                        "< 5 sessions)", "n_A": q.get("n", 0), "sessions_A": q.get("n_sessions", 0),
                              "pooled_n_A": pb.get("pooled_n_A"), "pooled_sessions_A": pb.get("pooled_sessions_A")}
    else:
        resolved["n1"] = {"bounds": None, "source": f"not computed: '{unit_as}' is not in SPEC_E N1 units (LAT_UNITS)"}
    n2 = res.get("n2", {})
    resolved["n2"] = {"GRANULAR": n2.get("granularity", {}).get("GRANULAR"),
                      "G1_share_both": n2.get("granularity", {}).get("G1_share_both"),
                      "G2_median_usage_out": n2.get("granularity", {}).get("G2_median_usage_out"),
                      "responses_A": n2.get("granularity", {}).get("responses"), "tau": n2.get("tau"),
                      "tau_n_A": n2.get("tau_n")}
    resolved["length_terciles_A"] = res.get("length_terciles")
    fg = dict(res.get("n6_field_gate") or {})
    corr = {}
    # field_gate() derives corpus-level facts from unit.split('/')[0]; with an analogue unit 'swechat/<fmt>' it would
    # claim swechat's external tables for the new corpus. The raw unit_result keeps the uncorrected value.
    if unit_as.split("/")[0] != corpus:
        for k in ("external_commit_table", "external_usage_tally"):
            if fg.get(k):
                corr[k] = {"calibrate_unit": True, "corrected": False,
                           "reason": f"{corpus} has no external table (the True came from unit '{unit_as}')"}
                fg[k] = False
        if fg.get("raw_structured_counters") and unit_as != "swechat/claude_code":
            corr["raw_structured_counters"] = {"calibrate_unit": True, "corrected": False}
            fg["raw_structured_counters"] = False
    resolved["n6_field_gate_A"] = fg
    resolved["n6_field_gate_corrections"] = corr
    if "bracket" in res:
        resolved["bracket_A"] = res["bracket"]
    if "n5" in res:
        resolved["n5_truncation_A"] = res["n5"].get("c_truncation_A")
    return resolved


def calibrate(corpus, units, loader_path, splits_info):
    """Run prereg_e_calibration.calibrate_unit() on <corpus>_A.parquet (A only) and write
    out/phase_e/prereg_e_calibration_<corpus>.json + out/phase_e/prereg_e_extensions/<corpus>.json.
    units: [(unit_label, unit_as, session_ids or None)]. unit_as = the pre-registered unit whose format rules apply
    (tool keys, error classes, qualification filters, N2 response table, LAT_UNITS / N5_UNITS membership); a label
    with no analogue passes its own name (generic rules). The corpus name is passed as `corpus`."""
    from analysis.probes import prereg_e_calibration as cal
    from analysis.probes import prereg_e_common as pe
    assert pe.SEED_NEW_CORPUS == SEED_NEW_CORPUS
    t0 = time.time()
    U = pe.read_cache(corpus, "A", cal.COLS, allowed=("A",)).reset_index(drop=True)
    pj = json.loads(pe.PREREG_E_JSON.read_text(encoding="utf-8"))
    out_units = {}
    for label, unit_as, sids in units:
        u = U if sids is None else U[U.session_id.isin(set(sids))].reset_index(drop=True)
        res, R = cal.calibrate_unit(corpus, unit_as, u)
        out_units[label] = {"calibrated_as_unit": unit_as, "sessions_A": int(u.session_id.nunique()),
                            "unit_result": res, "resolved": _resolve_unit(res, pj, corpus, unit_as)}
    doc = {"corpus": corpus, "units": out_units,
           "calibrated_as_unit_reason": "calibrate_unit() keys its format rules on the unit name; a new corpus parsed "
                                        "by the same format parser as a pre-registered unit is calibrated under that "
                                        "unit name so its rules (tool keys, error classes, qualification filters, "
                                        "response table, N1/N5 membership) apply unchanged. corpus=<new corpus> makes "
                                        "the AC4 cluster map one cluster (session_cluster_map fallback).",
           "script": "analysis/probes/prereg_e_calibration.py:calibrate_unit (called, not re-implemented)",
           "loader": loader_path, "split": "A only (analysis/cache/%s_A.parquet via prereg_e_common.read_cache "
                                           "allowed=('A',)); B/E/H never opened" % corpus,
           "not_computed": "Phase E outcomes: N1/N3 correlations, detector flag or violation rates, determinism drift, "
                           "round-number shares, recalls, tamper results",
           "splits": {k: splits_info[k] for k in ("samples", "samples_EH", "sha256_samples", "sha256_samples_EH")},
           "prereg_e_json_sha256": sha256_file(pe.PREREG_E_JSON),
           "spec_module_sha256_lf": pe.sha256_lf(Path(pe.__file__)),
           "spec_module_matches_prereg": pe.sha256_lf(Path(pe.__file__)) == pj["provenance"]["spec_module_sha256_lf"],
           "calibration_script_sha256_lf": pe.sha256_lf(Path(cal.__file__)),
           "a_cache_sha256": sha256_file(CACHE / f"{corpus}_A.parquet"),
           "runtime_s": round(time.time() - t0, 1)}
    OUT_E.mkdir(parents=True, exist_ok=True)
    p = OUT_E / f"prereg_e_calibration_{corpus}.json"
    p.write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    ext = {"corpus": corpus, "calibration_file": str(p.relative_to(ROOT).as_posix()),
           "calibration_sha256": sha256_file(p),
           "splits_sha256": {"samples": splits_info["sha256_samples"], "samples_EH": splits_info["sha256_samples_EH"]},
           "heldout_manifest": splits_info["heldout_manifest"],
           "heldout_manifest_sha256": sha256_file(ROOT / splits_info["heldout_manifest"]),
           "loader": loader_path, "loader_sha256_lf": pe.sha256_lf(ROOT / loader_path),
           "common_sha256_lf": pe.sha256_lf(Path(__file__)),
           "units": {k: v["calibrated_as_unit"] for k, v in out_units.items()},
           "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (EXT_DIR / f"{corpus}.json").write_text(json.dumps(ext, indent=1), encoding="utf-8")
    return doc, ext
