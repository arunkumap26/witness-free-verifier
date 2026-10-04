"""Eval entry point for the witness-free verifier (DESIGN.md section 5). Prints ONE JSON object as the last stdout line.

    python eval/run_eval.py [--repo PATH] [--split E|H] [--mode quick|full] [--seeds 0,1,2] [--checks a,b]
                            [--labeled DIR] [--final --freeze SHA] [--procs 8] [--pack DIR] [--limit N]
                            [--units u1,u2] [--report-dir DIR]

Contract (eval/core.py): deterministic per seed, >= 3 seeds by default, no GPU, the last stdout line is one JSON object
{"ok", "headline", "stdev", "seeds", "split", "mode", "gate", "metrics", "per_check", "per_corpus", "timing", "report"};
progress goes to stderr. Crashes and contract failures print {"ok": false, "error": ...} and exit 1; a gate breach is a
clean reject: ok true, headline -1.0, exit 0 (DA10).

Data (DESIGN.md 5.2-5.3). The eval scores a PACK: a fixed, seed-independent stratified subsample per unit (IR rows +
unit) plus an attack plan (every random choice of every tamper resolved, eval/attacks.py `PlanRow`). Lookup order:
  1. --pack DIR (tests, or an explicit pack);
  2. --split H: <MAIN>/<pack_dir>/H_pack.parquet, only under --final --freeze SHA (built by eval/heldout.py after the
     freeze; this script never reads an H id list and never builds an H pack);
  3. the official dev pack <MAIN>/<pack_dir>/<split>_pack.parquet when eval/heldout.py has built it;
  4. otherwise a DEV PACK built here from the IR caches (analysis/cache/<corpus>_E.parquet, B for units without E) and
     the split files (analysis/cache/samples/<corpus>_EH.json key "E" only, <corpus>.json key "B"), cached per unit
     under <MAIN>/ops/state/eval/devpack/<key>/ (runtime state; keyed by the source files, this file and attacks.py).
The score path imports only `verifier.verify_session` / `verifier.__version__` from the code under test and nothing
from `analysis` (DA6); module origins are asserted before scoring.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zlib
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

import attacks  # noqa: E402
import metrics  # noqa: E402

RUN_EVAL_SHA = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
SEED_E = attacks.SEED_E

# ============================================================================================================ config
# Frozen defaults (DESIGN.md 5.3-5.5). eval/config_eval.json, when it exists (written by day, owned by the freeze
# step), overrides these key by key; its sha256 goes into the report.
QUICK_CELLS = [
    ["time_result_early", "5"], ["time_result_early", "30"], ["time_result_late", "30"], ["time_tail_late", "30"],
    ["time_response_early", "5"], ["id_swap_adjacent", "-"], ["id_splice_foreign", "nearest"],
    ["sub_single_flip_error", "-"], ["sub_single_digit", "-"], ["sub_matched_bytes", "any"],
    ["rewrite_consistent_k", "2"], ["reorder_adjacent_pairs", "-"], ["delete_pair", "-"],
    ["insert_pair_consistent", "-"], ["inline_fabrication", "tau"], ["image_relabel_gui", "-"],
]
DEFAULT_CONFIG = {
    "config_version": "scaffold-defaults-1",
    "seeds": [0, 1, 2],
    "pack_dir": "data/eval/verifier_v1",
    "pack_per_unit": 150,
    "attack_per_cell": 40,
    "min_cell_sessions": 30,
    "n7_cap_sessions": attacks.N7_CAP_SESSIONS,
    "quick_cells": QUICK_CELLS,
    "EXEC_CREDIT": {"inline_fabrication": ["inline_output_accounting"]},
    "EVAL_CALIBRATION_UNIT": {"pub_cc_hf": "cc_local", "pub_trace_commons": "cc_local", "pub_codex": "swechat/codex",
                              "agentcap/opencode": "swechat/opencode"},
    "fpr_cap": {},
    "CLEAN_CAP": None,
    "h_exposure": {},
    "check_reads": {},
    "private_units": ["cc_local"],
    "corpora": ["swechat", "tbench2", "glm_tb21", "pub_cc_hf", "pub_trace_commons", "pub_codex", "agentcap", "aiv_cu",
                "aiv_cc", "cc_local", "whowhen"],
    "labeled_join_min_ok_share": 0.99,
    "reference_checks": ["ref_result_present"],
    "change_log": [],
}
FORBIDDEN_MODULE_PREFIXES = ("analysis.lib.stats", "analysis.lib.sample", "analysis.loaders", "analysis.probes")
IR_COLS = list(attacks.IR_COLUMNS)


class EvalError(Exception):
    """A contract failure: printed as {"ok": false, "error": str(e)}, exit 1."""


def load_config() -> tuple[dict, str]:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    p = EVAL_DIR / "config_eval.json"
    src = "defaults"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
        src = "config_eval.json"
    sha = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()
    return cfg, f"{src}:{sha[:16]}"


def log(msg):
    print(f"[run_eval {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ============================================================================================================ git / paths
def _git(repo: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        raise EvalError(f"git {' '.join(args)} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def main_checkout(repo: Path) -> Path:
    """DESIGN.md 5.1: MAIN = parent of `git rev-parse --git-common-dir` (works from any worktree and from the
    orchestrator's eval_snapshot). A --repo that is not a git checkout is its own MAIN (tests)."""
    try:
        common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        return Path(common).parent
    except EvalError:
        return repo


def lf_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ============================================================================================================ verifier
def import_verifier(repo: Path):
    """DA6 import isolation: eval dir first on sys.path, --repo second; verifier must come from --repo, and the
    statistics / loaders / probes of `analysis` must not be loaded on the score path."""
    rs = str(repo)
    loaded = sys.modules.get("verifier")
    if loaded is not None and repo.resolve() not in Path(getattr(loaded, "__file__", "") or ".").resolve().parents:
        for m in [m for m in sys.modules if m == "verifier" or m.startswith("verifier.")]:
            del sys.modules[m]          # a verifier from another --repo (in-process callers such as eval/core.py)
    if rs in sys.path:
        sys.path.remove(rs)
    sys.path.insert(1 if sys.path and sys.path[0] == str(EVAL_DIR) else 0, rs)
    try:
        import verifier  # noqa: F401
        from verifier import verify_session  # noqa: F401
    except Exception as e:  # the system under test does not import: a failed candidate
        raise EvalError(f"verifier_import: {type(e).__name__}: {e}"[:400])
    vf = Path(verifier.__file__).resolve()
    if repo.resolve() not in vf.parents:
        raise EvalError(f"import_isolation: verifier loaded from {vf}, not under --repo {repo}")
    assert_isolation()
    return verifier


def assert_isolation():
    bad = sorted(m for m in sys.modules if m.startswith(FORBIDDEN_MODULE_PREFIXES))
    if bad:
        raise EvalError(f"import_isolation: score path loaded {bad[:5]}")


# ============================================================================================================ sampling
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


FROZEN_COPIES = {"_alloc": "analysis/lib/sample.py"}


def pack_sample(unit: str, split: str, pop: pd.DataFrame, k: int) -> list:
    """DESIGN.md 5.3: min(|split_unit|, k) sessions, stratified on stratum x length tercile with lib.sample._alloc,
    rng default_rng([SEED_E, crc32('pack|<split>|<unit>')]). pop: session_id, stratum, length. The per-cell floor is
    min(5, k // n_cells), prereg_e.json change_log D3 (_alloc does not cap floors: tbench2's many submission x tercile
    cells would otherwise draw 367 sessions for k = 150)."""
    pop = pop.sort_values("session_id", kind="mergesort").reset_index(drop=True).copy()
    if len(pop) <= k:
        return list(pop.session_id)
    pop["stratum"] = pop["stratum"].fillna("unknown").astype(str)
    q = pop["length"].rank(method="first", pct=True)
    pop["cell"] = pop["stratum"] + "|" + np.where(q <= 1 / 3, "short", np.where(q <= 2 / 3, "mid", "long"))
    rng = np.random.default_rng([SEED_E, zlib.crc32(f"pack|{split}|{unit}".encode("utf-8"))])
    pop = pop.iloc[rng.permutation(len(pop))].reset_index(drop=True)
    sizes = pop.groupby("cell").size().to_dict()
    alloc = _alloc(sizes, k, floor=min(5, k // max(1, len(sizes))))
    ids = []
    for cell, n in alloc.items():
        ids += pop.loc[pop.cell == cell, "session_id"].head(n).tolist()
    return sorted(ids)


# ============================================================================================================ sources
def find_cache_dir(repo: Path, main: Path, override: str | None) -> Path:
    """The IR caches (gitignored) exist only in the analysis worktree: --cache, else <repo>/analysis/cache, else the
    analysis worktree of MAIN, else <MAIN>/analysis/cache."""
    cands = [Path(override)] if override else []
    cands += [repo / "analysis" / "cache", main / ".claude" / "worktrees" / "analysis" / "analysis" / "cache",
              main / "analysis" / "cache"]
    for c in cands:
        if (c / "samples").is_dir():
            return c.resolve()
    raise EvalError("missing_pack: no pack and no IR cache directory (analysis/cache) to build a dev pack from")


def dev_split_of(cache: Path, corpus: str, split: str) -> str | None:
    """E when the corpus has an E split on disk, else B (DESIGN.md 5.2 rule 2); None when neither exists."""
    if split == "E" and (cache / "samples" / f"{corpus}_EH.json").exists() and (cache / f"{corpus}_E.parquet").exists():
        return "E"
    if (cache / "samples" / f"{corpus}.json").exists() and (cache / f"{corpus}_B.parquet").exists():
        return "B"
    return None


def split_ids(cache: Path, corpus: str, dev_split: str) -> list:
    """Session ids of a development split: key "E" of <corpus>_EH.json, or key "B" of <corpus>.json. Never H."""
    assert dev_split in ("B", "E")
    if dev_split == "B":
        return [str(x) for x in json.loads((cache / "samples" / f"{corpus}.json").read_text(encoding="utf-8"))["B"]]
    eh = json.loads((cache / "samples" / f"{corpus}_EH.json").read_text(encoding="utf-8"))
    ids = [str(x) for x in eh["E"]]
    del eh
    return ids


def exclusions(cache: Path, corpus: str, dev_split: str) -> set:
    """prereg_e.json change_log D5: agentcap B/E sessions parsed in an abandoned A build stay excluded."""
    p = cache.parent / "out" / "phase_e" / "newcorp_exclusions.json"
    if not p.exists():
        return set()
    x = json.loads(p.read_text(encoding="utf-8")).get(corpus, {})
    return {str(s) for s in (x.get(dev_split) or [])} if isinstance(x, dict) else set()


def unit_assignments(cache: Path, corpus: str, dev_split: str, ids: list) -> dict:
    """session_id -> Phase E unit (DESIGN.md 2.5): swechat/<format> from swechat_population.parquet,
    agentcap/<opencode|pi> from the session's stratum in the split cache, else the corpus name."""
    if corpus == "swechat":
        pop = pd.read_parquet(cache / "swechat_population.parquet", columns=["session_id", "format"])
        fm = dict(zip(pop.session_id.astype(str), pop.format.astype(str)))
        return {s: f"swechat/{fm[s]}" for s in ids if s in fm}
    if corpus == "agentcap":
        t = pq.read_table(cache / f"agentcap_{dev_split}.parquet", columns=["session_id", "stratum"]).to_pandas()
        t["session_id"] = t["session_id"].astype(str)
        st = t.dropna(subset=["stratum"]).groupby("session_id").stratum.first().to_dict()
        return {s: f"agentcap/{str(st[s]).split('/', 1)[0]}" for s in ids if s in st}
    return {s: corpus for s in ids}


def source_stats(paths) -> list:
    out = []
    for p in sorted({Path(x) for x in paths}):
        if p.exists():
            s = p.stat()
            out.append([p.name, s.st_size, s.st_mtime_ns])
    return out


# ============================================================================================================ packs
class Pack:
    """A loaded pack: per-unit frame locations, plan rows, metadata. Frames are read lazily (workers read their own)."""

    def __init__(self, split, units, plans, meta, sidecar=None):
        self.split, self.units, self.plans, self.meta = split, units, plans, meta
        self.sidecar = sidecar or {}

    def sessions(self, unit):
        return self.units[unit]["sessions"]


def _read_frames(path: str, unit: str | None, sids=None) -> dict:
    filt = []
    if unit is not None:
        filt.append(("unit", "=", unit))
    if sids is not None:
        filt.append(("session_id", "in", sorted(sids)))
    df = pd.read_parquet(path, filters=filt or None)
    df["session_id"] = df["session_id"].astype(str)
    out = {}
    for sid, g in df.groupby("session_id", sort=True):
        out[str(sid)] = g.sort_values("seq", kind="mergesort").reset_index(drop=True)
    return out


def write_unit_pack(d: Path, frame: pd.DataFrame, plans: list, meta: dict):
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".tmp"
    tmp.mkdir(exist_ok=True)
    tab = pa.Table.from_pandas(frame.reset_index(drop=True), preserve_index=False)
    pq.write_table(tab, tmp / "pack.parquet", row_group_size=50_000, compression="zstd")
    recs = [r.to_record() for r in plans]
    pt = pd.DataFrame(recs, columns=["seed", "attack", "param", "unit", "session_id", "target_json", "payload_json"])
    pq.write_table(pa.Table.from_pandas(pt, preserve_index=False), tmp / "plan.parquet", compression="zstd")
    (tmp / "meta.json").write_text(json.dumps(meta, sort_keys=True, indent=1), encoding="utf-8")
    for n in ("pack.parquet", "plan.parquet", "meta.json"):     # meta.json last: its presence marks a complete unit
        os.replace(tmp / n, d / n)
    tmp.rmdir()


def build_unit_pack(cache: Path, unit: str, split: str, frame: pd.DataFrame, config: dict, mode: str) -> tuple:
    """Sample (quick) or take every session (full), compute attack eligibility per cell, and plan the tampers."""
    t0 = time.time()
    frame = frame.copy()
    frame["session_id"] = frame["session_id"].astype(str)
    frame = frame.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    pools = attacks.UnitPools(unit, frame)
    by = {s: g for s, g in frame.groupby("session_id", sort=True)}
    pop = pd.DataFrame({"session_id": list(by),
                        "stratum": [next((x for x in g.stratum.astype(object) if isinstance(x, str)), None)
                                    for g in by.values()],
                        "length": [len(g) for g in by.values()]})
    if mode == "quick":
        sids = pack_sample(unit, split, pop, int(config["pack_per_unit"]))
        cells = [tuple(c) for c in config["quick_cells"]]
        seeds = [int(s) for s in config["seeds"]]
    else:
        sids = sorted(by)
        cells = [(a, p) for a, sp in attacks.ATTACKS.items() if sp.ported for p in sp.params]
        seeds = [0]
    cells = [(a, p) for a, p in cells if not (attacks.ATTACKS[a].aiv_cu_only and unit != "aiv_cu")]
    ctx = {s: attacks.session_context(unit, by[s], pools) for s in sids}
    elig = {}
    for a, p in cells:
        elig[f"{a}|{p}"] = sorted(s for s in sids if attacks.targets_ctx(a, p, ctx[s]))
    plans = []
    floor = int(config["min_cell_sessions"])
    for a, p in cells:
        E = elig[f"{a}|{p}"]
        if len(E) < floor:
            continue
        for s in seeds:
            if mode == "quick":
                k = min(int(config["attack_per_cell"]), len(E))
                perm = attacks.rng_for_seed(s, a, p, unit).permutation(len(E))
                chosen = [E[i] for i in perm[:k]]
            else:   # N7 order: rng_for('N7', unit, split).permutation(sorted ids), first 500 eligible
                order = [sids[i] for i in attacks.rng_for_seed(0, "N7", unit, split).permutation(len(sids))]
                es = set(E)
                chosen = [x for x in order if x in es][:int(config["n7_cap_sessions"])]
            for sid in chosen:
                row = attacks.plan_ctx(a, p, s, ctx[sid])
                if row is not None:
                    plans.append(row)
    keep = set(sids)
    pf = frame[frame.session_id.isin(keep)].copy()
    pf["unit"] = unit
    meta = {"unit": unit, "split": split, "mode": mode, "n_split_sessions": len(by), "n_pack": len(sids),
            "sessions": sids, "eligibility": {k: len(v) for k, v in elig.items()}, "seeds": seeds,
            "cells": [[a, p] for a, p in cells], "min_cell_sessions": floor,
            "n_plans": len(plans), "build_s": round(time.time() - t0, 1)}
    return pf[IR_COLS + ["unit"]], plans, meta


def load_dev_frames(cache: Path, corpus: str, split: str, units_wanted=None) -> dict:
    """unit -> every IR row of that unit in the corpus's development split (E, or B without E)."""
    ds = dev_split_of(cache, corpus, split)
    if ds is None:
        return {}
    ids = [s for s in split_ids(cache, corpus, ds) if s not in exclusions(cache, corpus, ds)]
    ua = unit_assignments(cache, corpus, ds, ids)
    want = sorted({u for u in ua.values() if units_wanted is None or u in units_wanted})
    out = {}
    for u in want:
        uids = sorted(s for s, x in ua.items() if x == u)
        df = pd.read_parquet(cache / f"{corpus}_{ds}.parquet", filters=[("session_id", "in", uids)])
        df["session_id"] = df["session_id"].astype(str)
        out[u] = (ds, df[IR_COLS])
    return out


def dev_pack(cache: Path, main: Path, split: str, mode: str, config: dict, units_wanted, root: Path | None) -> Pack:
    """Build-or-load the per-unit dev pack (step 4 of the module docstring)."""
    key_src ={"split": split, "mode": mode, "attacks_sha": attacks.ATTACKS_SHA, "builder_sha": builder_sha(),
               "cfg": {k: config[k] for k in ("seeds", "pack_per_unit", "attack_per_cell", "min_cell_sessions",
                                              "n7_cap_sessions", "quick_cells", "corpora")},
               "cache": str(cache).lower()}
    key = hashlib.sha256(json.dumps(key_src, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    root = root or (main / "ops" / "state" / "eval" / "devpack")
    base = root / f"{split}_{mode}_{key}"
    built = []
    for corpus in config["corpora"]:
        ds = dev_split_of(cache, corpus, split)
        if ds is None:
            continue
        srcs = [cache / f"{corpus}_{ds}.parquet", cache / "samples" / f"{corpus}_EH.json",
                cache / "samples" / f"{corpus}.json", cache / "swechat_population.parquet",
                cache.parent / "out" / "phase_e" / "newcorp_exclusions.json"]
        stats = source_stats(srcs)
        frames = None
        ids = [s for s in split_ids(cache, corpus, ds) if s not in exclusions(cache, corpus, ds)]
        for unit in sorted(set(unit_assignments(cache, corpus, ds, ids).values())):
            if units_wanted is not None and unit not in units_wanted:
                continue
            d = base / unit.replace("/", "__")
            m = None
            if (d / "meta.json").exists():
                m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                if m.get("source_stats") != stats:
                    m = None
            if m is None:
                if frames is None:
                    log(f"dev pack: loading {corpus} {ds} from {cache}")
                    frames = load_dev_frames(cache, corpus, split, units_wanted)
                log(f"dev pack: building {unit} ({ds}, mode {mode}); one-time, cached under {d}")
                pf, pl, m = build_unit_pack(cache, unit, ds, frames[unit][1], config, mode)
                m.update(dev_split=ds, source_stats=stats, ir_schema_sha=_ir_sha(cache), key=key, key_src=key_src)
                write_unit_pack(d, pf, pl, m)
            built.append(unit)
    if not built:
        raise EvalError("missing_pack: no unit could be built from the IR caches")
    pack = read_unit_packs(base, split, set(built))
    pack.meta.update(kind="dev_pack", key=key)
    return pack


UNIT_META_VOLATILE = ("sessions", "key_src", "build_s", "source_stats")


def read_unit_packs(base: Path, split: str, units_wanted=None) -> Pack:
    """The per-unit pack layout this file writes (<base>/<unit slug>/{pack,plan}.parquet + meta.json)."""
    units, plans, metas, build_s = {}, [], {}, {}
    for d in sorted(p for p in base.iterdir() if (p / "meta.json").exists()):
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if units_wanted is not None and m["unit"] not in units_wanted:
            continue
        units[m["unit"]] = {"path": str(d / "pack.parquet"), "filter_unit": False, "sessions": m["sessions"],
                            "dev_split": m.get("dev_split", split)}
        metas[m["unit"]] = {k: v for k, v in m.items() if k not in UNIT_META_VOLATILE}
        build_s[m["unit"]] = m.get("build_s")
        pt = pd.read_parquet(d / "plan.parquet")
        plans += [attacks.PlanRow.from_record(r) for r in pt.to_dict("records")]
    if not units:
        raise EvalError(f"missing_pack:{split} (no unit pack under {base})")
    shas = sorted({m.get("ir_schema_sha") for m in metas.values() if m.get("ir_schema_sha")})
    if len(shas) > 1:
        raise EvalError(f"ir_schema_mismatch: unit packs were built under different IR schemas {shas}")
    meta = {"kind": "unit_packs", "root": str(base), "units": metas, "ir_schema_sha": shas[0] if shas else None,
            "build_s": build_s}
    return Pack(split, units, plans, meta)


BUILDER_FUNCS = ("_alloc", "pack_sample", "dev_split_of", "split_ids", "exclusions", "unit_assignments",
                 "build_unit_pack", "load_dev_frames", "write_unit_pack")


def builder_sha() -> str:
    """sha256 over the source of the functions that decide a dev pack's content (the dev-pack cache key), so an edit
    elsewhere in this file does not force a rebuild and an edit to any of them does."""
    import inspect
    src = "\n".join(inspect.getsource(globals()[n]) for n in BUILDER_FUNCS)
    return hashlib.sha256(src.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _ir_sha(cache: Path):
    p = cache.parent / "lib" / "ir.py"
    return lf_sha(p) if p.exists() else None


def write_pack(d: Path, split: str, frame: pd.DataFrame, plans: list, build: dict) -> None:
    """The official pack layout read_pack() reads (DESIGN.md 5.3), for eval/heldout.py build-pack and the tests.
    frame: IR COLUMNS + unit, every pack session; build: BUILD.json, which must carry 'eligibility' ({unit:
    {'attack|param': n_eligible_sessions}}), 'IR_SCHEMA_SHA' and 'dev_split' ({unit: 'E'|'B'})."""
    for k in ("eligibility", "IR_SCHEMA_SHA", "dev_split"):
        if k not in build:
            raise ValueError(f"BUILD.json needs {k!r}")
    d.mkdir(parents=True, exist_ok=True)
    f = frame.sort_values(["unit", "session_id", "seq"], kind="mergesort").reset_index(drop=True)
    pq.write_table(pa.Table.from_pandas(f[IR_COLS + ["unit"]], preserve_index=False), d / f"{split}_pack.parquet",
                   row_group_size=50_000, compression="zstd")
    pt = pd.DataFrame([r.to_record() for r in plans],
                      columns=["seed", "attack", "param", "unit", "session_id", "target_json", "payload_json"])
    pq.write_table(pa.Table.from_pandas(pt, preserve_index=False), d / f"{split}_attack_plan.parquet",
                   compression="zstd")
    (d / "BUILD.json").write_text(json.dumps(build, sort_keys=True, indent=1), encoding="utf-8")


def read_pack(d: Path, split: str) -> Pack:
    """An official pack written by eval/heldout.py build-pack: <split>_pack.parquet (IR + unit), <split>_attack_plan
    .parquet, optional <split>_sidecar.parquet, BUILD.json (DESIGN.md 5.3, 2.7)."""
    pk, pl = d / f"{split}_pack.parquet", d / f"{split}_attack_plan.parquet"
    if not pk.exists() or not pl.exists():
        raise EvalError(f"missing_pack:{split} ({pk})")
    build = json.loads((d / "BUILD.json").read_text(encoding="utf-8")) if (d / "BUILD.json").exists() else {}
    ids = pq.read_table(pk, columns=["unit", "session_id"]).to_pandas().drop_duplicates()
    units = {}
    for u, g in ids.groupby("unit", sort=True):
        units[str(u)] = {"path": str(pk), "filter_unit": True, "sessions": sorted(g.session_id.astype(str)),
                         "dev_split": (build.get("dev_split") or {}).get(str(u), split)}
    pt = pd.read_parquet(pl)
    plans = [attacks.PlanRow.from_record(r) for r in pt.to_dict("records")]
    sidecar = {}
    sc = d / f"{split}_sidecar.parquet"
    if sc.exists():
        for sid, k, js in pq.read_table(sc).to_pandas()[["session_id", "key", "json"]].itertuples(index=False):
            sidecar.setdefault(str(sid), {})[str(k)] = json.loads(js)
    meta = {"kind": "pack", "dir": str(d), "build": build, "ir_schema_sha": build.get("IR_SCHEMA_SHA")}
    return Pack(split, units, plans, meta, sidecar)


# ============================================================================================================ H path
def freeze_check(repo: Path, sha: str, purpose: str, main: Path, argv: list) -> None:
    """DESIGN.md 5.2 rule 3, checked before any H event is read: HEAD == SHA, no uncommitted change under verifier/,
    eval/, analysis/lib, analysis/loaders, and every eval file this process loaded equals eval/<file> at SHA."""
    if not sha or len(sha) < 7:
        raise EvalError("freeze_sha_missing: --final needs --freeze <commit sha>")
    head = _git(repo, "rev-parse", "HEAD").strip()
    if not head.startswith(sha):
        raise EvalError(f"freeze_sha_mismatch: HEAD {head[:12]} != {sha[:12]}")
    dirty = _git(repo, "status", "--porcelain", "--", "verifier/", "eval/", "analysis/lib", "analysis/loaders").strip()
    if dirty:
        raise EvalError(f"freeze_dirty: {dirty.splitlines()[0][:120]}")
    loaded = [EVAL_DIR / "run_eval.py", EVAL_DIR / "attacks.py", EVAL_DIR / "metrics.py"]
    loaded += [EVAL_DIR / n for n in ("config_eval.json", "_stats.py", "labeled.py") if (EVAL_DIR / n).exists()]
    for f in loaded:
        r = subprocess.run(["git", "-C", str(repo), "show", f"{head}:eval/{f.name}"], capture_output=True)
        if r.returncode != 0 or hashlib.sha256(r.stdout.replace(b"\r\n", b"\n")).hexdigest() != lf_sha(f):
            raise EvalError(f"freeze_eval_mismatch: eval/{f.name} differs from {head[:12]}")


def log_h_access(main: Path, sha: str, argv: list, purpose: str) -> None:
    p = main / "reports" / "eval" / "h_access_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha": sha, "argv": argv,
                            "purpose": purpose}, sort_keys=True) + "\n")


def blind_on_h(lineage: str | None, unit: str) -> bool | None:
    """DESIGN.md 5.2 rule 7 from config_eval.json h_exposure (check -> lineage). None = lineage not recorded."""
    if lineage is None:
        return None
    if lineage in ("R3_GIT", "R4_DUAL", "R5_LEDGER"):
        return False
    new = ("tbench2", "glm_tb21", "pub_cc_hf", "pub_trace_commons", "pub_codex", "agentcap/opencode", "agentcap/pi")
    if lineage in ("R1_BRACKET", "F1", "P1_FLOOR", "P1_GEN", "N3") and unit in new:
        return False
    return True


# ============================================================================================================ workers
_W = {}


def _init_worker(repo: str, checks, config: dict, units: dict, sidecar: dict):
    import_verifier(Path(repo))
    import verifier
    _W.update(verify=verifier.verify_session, checks=checks, config=config, units=units, sidecar=sidecar, frames={})


def _frames(unit: str) -> dict:
    fr = _W["frames"]
    if unit not in fr:
        if len(fr) >= 3:          # bounded memory for full-mode packs
            fr.pop(next(iter(fr)))
        u = _W["units"][unit]
        fr[unit] = _read_frames(u["path"], unit if u["filter_unit"] else None)
    return fr[unit]


def _verify(frame: pd.DataFrame, unit: str, sid: str):
    cu = _W["config"]["EVAL_CALIBRATION_UNIT"].get(unit, unit)
    with contextlib.redirect_stdout(sys.stderr):       # the last stdout line belongs to the JSON result
        return _W["verify"](frame[IR_COLS].reset_index(drop=True), unit=unit, calibration_unit=cu,
                            checks=_W["checks"], sidecar=_W["sidecar"].get(sid), strict=False)


def _run_job(job):
    kind, unit = job[0], job[1]
    fr = _frames(unit)
    out = []
    if kind == "honest":
        for sid in job[2]:
            try:
                v = _verify(fr[sid], unit, sid)
            except Exception as e:
                out.append([sid, {"verify_exception": f"{type(e).__name__}: {e}"[:300]}])
                continue
            out.append([sid, metrics.summarize_session(v, keep_contradictions=True)])
    else:
        credited = job[3]
        for rec in job[2]:
            row = attacks.PlanRow.from_record(rec)
            key = [row.seed, row.attack, row.param, row.unit, row.session_id]
            try:
                tf, tam = attacks.apply(row, fr[row.session_id])
            except attacks.InjectFailed as e:
                out.append([key, {"inject_failed": str(e)}])
                continue
            except Exception as e:  # an eval-side injector crash is an eval failure, never hidden
                out.append([key, {"inject_exception": f"{type(e).__name__}: {e}"[:300]}])
                continue
            try:
                v = _verify(tf, unit, row.session_id)
            except Exception as e:
                out.append([key, {"verify_exception": f"{type(e).__name__}: {e}"[:300]}])
                continue
            s = metrics.summarize_session(v, tamper=tam, credited=credited)
            s.update(seed=row.seed, sid=row.session_id)
            out.append([key, s])
    assert_isolation()
    return job[0], job[1], out


def run_jobs(jobs: list, procs: int, init_args: tuple) -> list:
    if procs <= 1:
        _init_worker(*init_args)
        return [_run_job(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=procs, initializer=_init_worker, initargs=init_args) as ex:
        return list(ex.map(_run_job, jobs))


# ============================================================================================================ evaluation
class Evaluator:
    """One eval run. main() drives it; run_seed() exposes one seed for eval/core.py compatibility."""

    def __init__(self, args, config, cfg_id):
        self.a, self.config, self.cfg_id = args, config, cfg_id
        self.repo = Path(args.repo).resolve()
        self.main = main_checkout(self.repo)
        self.timing = {}
        self.checks = None if args.checks in (None, "", "enabled") else [c for c in args.checks.split(",") if c]
        self.seeds = [int(s) for s in (args.seeds.split(",") if args.seeds else config["seeds"])]
        self.honest = None

    # ---------------------------------------------------------------- pack
    def load(self):
        t0 = time.time()
        a, cfg = self.a, self.config
        units_wanted = set(a.units.split(",")) if a.units else None
        if a.pack:
            pd_ = Path(a.pack)
            if not pd_.is_dir():
                raise EvalError(f"missing_pack:{a.split} (--pack {a.pack})")
            if (pd_ / f"{a.split}_pack.parquet").exists():
                pack = read_pack(pd_, a.split)
            else:
                pack = read_unit_packs(pd_, a.split, units_wanted)
        elif a.split == "H":
            pack = read_pack(self.main / cfg["pack_dir"], "H")
        else:
            off = self.main / cfg["pack_dir"]
            if a.mode == "quick" and (off / f"{a.split}_pack.parquet").exists():
                pack = read_pack(off, a.split)
            else:
                cache = find_cache_dir(self.repo, self.main, a.cache)
                pack = dev_pack(cache, self.main, a.split, a.mode, cfg, units_wanted,
                                Path(a.devpack_root) if a.devpack_root else None)
        if units_wanted is not None:
            pack.units = {u: v for u, v in pack.units.items() if u in units_wanted}
            pack.plans = [p for p in pack.plans if p.unit in units_wanted]
        if a.limit:
            for u in pack.units:
                pack.units[u]["sessions"] = sorted(pack.units[u]["sessions"])[:a.limit]
            keep = {(u, s) for u, v in pack.units.items() for s in v["sessions"]}
            pack.plans = [p for p in pack.plans if (p.unit, p.session_id) in keep]
        seeds_in = sorted({p.seed for p in pack.plans})
        missing = [s for s in self.seeds if a.mode == "quick" and pack.plans and s not in seeds_in]
        if missing:
            raise EvalError(f"seed_not_in_plan: seeds {missing} have no attack plan in this pack ({seeds_in})")
        self.pack = pack
        self.timing["load_s"] = round(time.time() - t0, 2)
        log(f"pack: {pack.meta.get('kind')} units={len(pack.units)} sessions="
            f"{sum(len(v['sessions']) for v in pack.units.values())} plans={len(pack.plans)}")

    def init_args(self):
        return (str(self.repo), self.checks, self.config, self.pack.units, self.pack.sidecar)

    # ---------------------------------------------------------------- honest pass (seed-independent)
    def run_honest(self):
        if self.honest is not None:
            return
        t0 = time.time()
        jobs = []
        for u in sorted(self.pack.units):
            ss = self.pack.units[u]["sessions"]
            for i in range(0, len(ss), 25):
                jobs.append(("honest", u, ss[i:i + 25]))
        res = run_jobs(jobs, self.a.procs, self.init_args())
        H = {}
        for _, u, out in sorted(res, key=lambda r: (r[1], r[2][0][0] if r[2] else "")):
            for sid, s in out:
                if "verify_exception" in s:
                    raise EvalError(f"verify_session raised on honest {u} session: {s['verify_exception']}")
                H.setdefault(u, {})[sid] = s
        self.honest = {u: dict(sorted(S.items())) for u, S in sorted(H.items())}
        self.timing["honest_s"] = round(time.time() - t0, 2)

    # ---------------------------------------------------------------- attack pass (seed-dependent)
    def run_attacks(self, seeds):
        t0 = time.time()
        by = {}
        for p in self.pack.plans:
            if p.seed in seeds:
                by.setdefault((p.unit, p.attack, p.param, p.seed), []).append(p.to_record())
        jobs = []
        for (u, a, p, s), recs in sorted(by.items()):
            cred = self.config["EXEC_CREDIT"].get(a, []) if attacks.ATTACKS[a].cls == "exec" else []
            jobs.append(("attack", u, sorted(recs, key=lambda r: r["session_id"]), cred))
        res = run_jobs(jobs, self.a.procs, self.init_args()) if jobs else []
        copies, fails, errs = {}, {}, []
        for _, u, out in res:
            for key, s in out:
                seed, a, p, uu, sid = key
                ck = f"{uu}|{a}|{p}"
                if "inject_failed" in s:
                    fails.setdefault(ck, Counter())[s["inject_failed"]] += 1
                elif "inject_exception" in s or "verify_exception" in s:
                    errs.append(f"{ck}|seed{seed}: {s.get('inject_exception') or s.get('verify_exception')}")
                else:
                    copies.setdefault(ck, []).append(s)
        if errs:
            raise EvalError(f"attack pass failed on {len(errs)} copies; first: {errs[0]}")
        for ck in copies:
            copies[ck].sort(key=lambda c: (c["seed"], c["sid"]))
        self.timing["attack_s"] = round(self.timing.get("attack_s", 0) + time.time() - t0, 2)
        return copies, {k: dict(v) for k, v in fails.items()}

    # ---------------------------------------------------------------- tables
    def tables(self, copies, fails, seeds):
        t0 = time.time()
        H, cfg = self.honest, self.config
        all_checks = sorted({c for S in H.values() for s in S.values() for c in s["checks"]}
                            | {c for C in copies.values() for s in C for c in s["checks"]})
        per_unit = {u: metrics.unit_table(list(S.values())) for u, S in sorted(H.items())}
        per_check = {c: {u: metrics.check_unit_table(list(S.values()), c) for u, S in sorted(H.items())}
                     for c in all_checks}
        floor = int(cfg["min_cell_sessions"])
        cells, headline_cells, below = {}, {}, {}
        elig_all = {}
        for u in sorted(self.pack.units):
            el = (self.pack.meta.get("units", {}).get(u, {}) or {}).get("eligibility")
            if el is None:
                el = ((self.pack.meta.get("build") or {}).get("eligibility") or {}).get(u, {})
            elig_all[u] = el
            for ck, n in sorted(el.items()):
                a, p = ck.split("|", 1)
                key = f"{u}|{a}|{p}"
                if n < floor:
                    below[key] = n
                    continue
                cls = attacks.ATTACKS[a].cls
                cred = cfg["EXEC_CREDIT"].get(a, []) if cls == "exec" else []
                ct = metrics.cell_table(copies.get(key, []), H[u], all_checks, cls, seeds, cfg.get("check_reads"), a,
                                        credited=cred)
                ct.update(n_eligible=n, inject_failures=fails.get(key, {}))
                cells[key] = ct
                headline_cells[key] = ct
        hl = metrics.headline(headline_cells, seeds) if headline_cells else {
            "per_seed": {str(s): {"headline": 0.0} for s in seeds}, "headline": 0.0, "stdev": 0.0,
            "adr_loc_macro_exec": None, "adr_loc_macro_edit": None, "edit_artifact_adr_exec": None}
        transfer = {}
        refs = set(cfg.get("reference_checks") or [])
        for c in all_checks:
            for u in sorted(H):
                labels = {k.split("|", 1)[1]: v["per_check"][c][str(seeds[0])].get("cell_label")
                          for k, v in cells.items() if k.startswith(u + "|") and c in v["per_check"]}
                transfer.setdefault(c, {})[u] = ({"label": "NOT_APPLICABLE(reference)"} if c in refs else
                                                 metrics.transfer_cell(per_check[c].get(u), labels))
        pooled_n = sum(t["n_sessions"] for t in per_unit.values())
        pooled_k = sum(t["fpr_session_any"]["k"] for t in per_unit.values() if t["fpr_session_any"])
        pooled_calls = sum(t["n_calls"] for t in per_unit.values())
        pooled_cov = sum(t["covered_calls"] for t in per_unit.values())
        errors = sum(s["errors"] for S in H.values() for s in S.values()) + sum(
            s["errors"] for C in copies.values() for s in C)
        self.timing["metrics_s"] = round(time.time() - t0, 2)
        return {"per_unit": per_unit, "per_check": per_check, "cells": cells, "headline": hl, "transfer": transfer,
                "cells_below_floor": below, "eligibility": elig_all, "checks_seen": all_checks,
                "disagreement": metrics.disagreement({u: list(S.values()) for u, S in H.items()}),
                "pooled": {"fpr_session_any": metrics.wil(pooled_k, pooled_n) if pooled_n else None,
                           "coverage_any": (pooled_cov / pooled_calls) if pooled_calls else None,
                           "n_sessions": pooled_n, "n_calls": pooled_calls},
                "check_errors": errors}

    def versions(self):
        vs = sorted({s["version"] for S in self.honest.values() for s in S.values() if s.get("version")})
        return vs


def run_seed(repo, seed: int, _cache={}) -> dict:
    """eval/core.py compatibility (DESIGN.md 5.1): per-seed metrics; the honest pass is memoized per repo (checks =
    the verifier's ENABLED_CHECKS, as the orchestrator runs it)."""
    key = (str(Path(repo).resolve()),)
    if key not in _cache:
        args = parse_args(["--repo", str(repo)])
        cfg, cid = load_config()
        ev = Evaluator(args, cfg, cid)
        import_verifier(ev.repo)
        ev.load()
        ev.run_honest()
        _cache[key] = ev
    ev = _cache[key]
    copies, fails = ev.run_attacks([int(seed)])
    t = ev.tables(copies, fails, [int(seed)])
    ps = t["headline"]["per_seed"][str(int(seed))]
    return {"headline": ps["headline"], "adr_loc_macro_exec": ps.get("adr_loc_macro_exec"),
            "adr_loc_macro_edit": ps.get("adr_loc_macro_edit")}


# ============================================================================================================ labeled
def run_labeled(ev: Evaluator, d: Path) -> dict:
    """DESIGN.md 3.4 / 5.8 on development splits: verify the labeled corpus's B/E sessions with the same verifier,
    join labels, compute labeled.* metrics. Fails closed when the corpus has no split registration."""
    man = d / "manifest.json"
    lab = d / "labels.jsonl" if d.is_dir() else d
    if not d.is_dir():
        raise EvalError("labeled_corpus_layout: --labeled takes a directory (manifest.json, labels.jsonl, sessions/)")
    if not man.exists() or not lab.exists():
        raise EvalError(f"labeled_corpus_layout: {d} needs manifest.json and labels.jsonl")
    m = json.loads(man.read_text(encoding="utf-8"))
    if m.get("schema") != "labeled_call/1":
        raise EvalError(f"labeled_corpus_schema: {m.get('schema')!r} != 'labeled_call/1'")
    reg = d / "splits.json"
    if not reg.exists():
        raise EvalError("labeled_corpus_unregistered: run eval/labeled.py register before the first read (DESIGN.md 3.4)")
    sp = json.loads(reg.read_text(encoding="utf-8"))
    dev = {str(x) for k in ("B", "E") for x in (sp.get(k) or [])}
    del sp
    labels = pd.DataFrame([json.loads(x) for x in lab.read_text(encoding="utf-8").splitlines() if x.strip()])
    for c in ("call_id", "seq", "ir_sha", "class"):
        if c not in labels:
            labels[c] = None
    labels["session_id"] = labels["session_id"].astype(str)
    labels = labels[labels.session_id.isin(dev)].reset_index(drop=True)
    frames = {}
    sd = d / "sessions"
    for p in sorted(sd.glob("*.parquet")):
        df = pd.read_parquet(p)
        df["session_id"] = df["session_id"].astype(str)
        for sid, g in df[df.session_id.isin(dev)].groupby("session_id", sort=True):
            frames[str(sid)] = ("ir", g.sort_values("seq", kind="mergesort").reset_index(drop=True))
    for p in sorted((sd / "turns").glob("*.jsonl")) if (sd / "turns").is_dir() else []:
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        for r in rows:
            if str(r.get("session_id")) in dev:
                frames.setdefault(str(r["session_id"]), ("turns", []))[1].append(r)
    import verifier
    unit = f"labeled:{m.get('name', d.name)}"
    rows = []
    for sid in sorted(frames):
        kind, x = frames[sid]
        with contextlib.redirect_stdout(sys.stderr):
            v = verifier.verify_session(x[IR_COLS] if kind == "ir" else x, unit=unit,
                                        calibration_unit=m.get("calibration_unit"), checks=ev.checks, strict=False)
        sha = metrics.session_ir_sha(x) if kind == "ir" else None
        rows += [{"session_id": sid, "call_id": vv.call_id, "seq": vv.seq, "contradicted": vv.verdict == "contradicted",
                  "ir_sha": sha} for vv in v]
    vdf = pd.DataFrame(rows, columns=["session_id", "call_id", "seq", "contradicted", "ir_sha"])
    joined = metrics.join_labels(vdf, labels)
    out = metrics.labeled_metrics(joined)
    out.update(name=m.get("name"), sessions_verified=len(frames), labels_in_dev_split=int(len(labels)),
               split="B+E (development numbers)")
    return out


# ============================================================================================================ main
def parse_args(argv):
    ap = argparse.ArgumentParser(prog="run_eval.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--split", default="E", choices=["E", "H"])
    ap.add_argument("--mode", default="quick", choices=["quick", "full"])
    ap.add_argument("--seeds", default=None, nargs="+",
                    help="'0,1,2' or '0 1 2' (default: config seeds 0,1,2)")
    ap.add_argument("--checks", default=None, help="comma list of check names; default: the verifier's ENABLED_CHECKS")
    ap.add_argument("--labeled", default=None, help="labeled-corpus directory (DESIGN.md 3.4); optional")
    ap.add_argument("--final", action="store_true", help="required for any H read")
    ap.add_argument("--freeze", default=None, help="the frozen commit sha (with --final)")
    ap.add_argument("--procs", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--pack", default=None, help="read this pack directory (tests)")
    ap.add_argument("--limit", type=int, default=None, help="sessions per unit (smoke runs)")
    ap.add_argument("--units", default=None, help="comma list of units (development smoke runs)")
    ap.add_argument("--report-dir", default=None)
    ap.add_argument("--cache", default=None, help="IR cache directory for the dev pack (default: found)")
    ap.add_argument("--devpack-root", default=None, help="where dev packs are cached (default <MAIN>/ops/state/eval/devpack)")
    a = ap.parse_args(argv)
    if a.seeds is not None:  # accept both the DESIGN form (--seeds 0,1,2) and the space form (--seeds 0 1 2)
        a.seeds = ",".join(x.strip() for s in a.seeds for x in s.split(",") if x.strip()) or None
    return a


def _fail(msg: str) -> int:
    print(json.dumps({"ok": False, "error": str(msg)[:600]}))
    return 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    t0 = time.time()
    try:
        a = parse_args(argv)
    except SystemExit:
        return _fail("bad_arguments")
    try:
        cfg, cid = load_config()
        if a.split == "H" and not (a.final and a.freeze):
            raise EvalError("h_requires_final: --split H reads held-out data; it needs --final --freeze <sha>")
        if a.final and a.split != "H":
            raise EvalError("final_requires_split_H: --final is only for the one H read after the freeze")
        if a.labeled and a.split == "H":
            raise EvalError("h_labeled_unavailable: labeled H sessions are read by eval/labeled.py tooling after the "
                            "freeze, which is not built yet")
        ev = Evaluator(a, cfg, cid)
        if a.split == "H":
            freeze_check(ev.repo, a.freeze, "run_eval --split H", ev.main, argv)
            if not (ev.main / cfg["pack_dir"] / "H_pack.parquet").exists():
                raise EvalError(f"missing_pack:H ({ev.main / cfg['pack_dir']}); build it with eval/heldout.py after the freeze")
            log_h_access(ev.main, a.freeze, argv, "run_eval --split H")
        verifier = import_verifier(ev.repo)
        vversion = getattr(verifier, "__version__", None)
        ev.load()
        ev.run_honest()
        copies, fails = ev.run_attacks(ev.seeds)
        T = ev.tables(copies, fails, ev.seeds)
        versions = ev.versions()
        if T["check_errors"] > 0:
            raise EvalError(f"check_errors: {T['check_errors']} error: verdicts (a check raised or broke the contract)")
        exp = ev.pack.meta.get("ir_schema_sha")
        got = {m_.group(1) for v in versions for m_ in [re.search(r"\bir/([0-9a-f]{12})", v)] if m_}
        if exp and got and got != {exp[:12]}:
            raise EvalError(f"ir_schema_mismatch: verdicts carry ir/{sorted(got)}, pack built under ir/{exp[:12]}")
        checkset = sorted({m_.group(1) for v in versions for m_ in [re.search(r"\bchecks/([0-9a-f]{12})", v)] if m_})
        checkset12 = checkset[0] if len(checkset) == 1 else hashlib.sha256(
            ",".join(checkset or [a.checks or "enabled"]).encode()).hexdigest()[:12]
        labeled = None
        if a.labeled:
            labeled = run_labeled(ev, Path(a.labeled))
            if labeled["join_ok_share"] is not None and labeled["join_ok_share"] < cfg["labeled_join_min_ok_share"]:
                raise EvalError(f"labeled_join: ok share {labeled['join_ok_share']:.4f} < "
                                f"{cfg['labeled_join_min_ok_share']}")
        hl = T["headline"]
        refs = set(cfg.get("reference_checks") or [])
        gate = metrics.gates({c: v for c, v in T["per_check"].items() if c not in refs},
                             T["pooled"]["fpr_session_any"], cfg)
        headline_val, stdev = hl["headline"], hl["stdev"]
        if gate:
            headline_val, stdev = -1.0, 0.0
        report_dir = Path(a.report_dir) if a.report_dir else ev.main / "ops" / "state" / "eval" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        rpath = report_dir / f"run_eval_{a.split}_{a.mode}_{checkset12}.json"
        private = set(cfg.get("private_units") or [])
        report = {
            "schema": "run_eval_report/1", "split": a.split, "mode": a.mode, "seeds": ev.seeds,
            "checks_requested": ev.checks, "checks_seen": T["checks_seen"], "checkset_sha12": checkset12,
            "verifier": {"version": vversion, "verdict_versions": versions},
            "eval": {"run_eval_sha": RUN_EVAL_SHA, "attacks_sha": attacks.ATTACKS_SHA, "config": cid,
                     "config_change_log": cfg.get("change_log", []), "eval_deviations": attacks.EVAL_DEVIATIONS,
                     "exec_credit": cfg["EXEC_CREDIT"], "calibration_proxy": cfg["EVAL_CALIBRATION_UNIT"],
                     "not_ported_attacks": sorted(k for k, s in attacks.ATTACKS.items() if not s.ported)},
            "pack": {k: v for k, v in ev.pack.meta.items() if k not in ("load_s", "build_s")},
            "limits": {"limit": a.limit, "units": a.units},
            "headline": hl, "gate": gate, "per_unit": T["per_unit"], "per_check": T["per_check"],
            "cells": T["cells"], "cells_below_floor": T["cells_below_floor"], "transfer": T["transfer"],
            "disagreement": T["disagreement"], "pooled": T["pooled"], "check_errors": T["check_errors"],
            "labeled": labeled, "footer": metrics.SYNTHETIC_FOOTER,
        }
        if a.split == "H":
            report["blind_on_H"] = {c: {u: blind_on_h((cfg.get("h_exposure") or {}).get(c), u) for u in T["per_unit"]}
                                    for c in T["checks_seen"]}
        report = metrics.round_floats(report)
        report["content_sha256"] = metrics.content_sha(report)
        ev.timing["total_s"] = round(time.time() - t0, 2)
        if ev.pack.meta.get("build_s"):
            ev.timing["pack_build_s"] = ev.pack.meta["build_s"]
        report["timing"] = ev.timing
        rpath.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=1), encoding="utf-8")
        _write_contradictions(report_dir / f"honest_contradictions_{checkset12}.jsonl", ev.honest, private)
        per_check = {}
        for c in T["checks_seen"]:
            rows = T["per_check"][c].values()
            k = sum(r["fpr_session"]["k"] for r in rows if r["fpr_session"])
            n = sum(r["fpr_session"]["n"] for r in rows if r["fpr_session"])
            per_check[c] = {"kind": "reference" if c in refs else "decides",
                            "fpr_session": metrics.round_floats(metrics.wil(k, n)) if n else None,
                            "decided_calls": sum(r["decided_calls"] for r in rows),
                            "screened_calls": sum(r["screened_calls"] for r in rows),
                            "contradicted_calls": sum(r["contradicted_calls"] for r in rows),
                            "errors": sum(r["errors"] for r in rows)}
        per_corpus = {u: {"n_sessions": t["n_sessions"], "n_calls": t["n_calls"],
                          "fpr_session_any": round(t["fpr_session_any"]["p"], 6) if t["fpr_session_any"] else None,
                          "coverage_any": None if t["coverage_any"] is None else round(t["coverage_any"], 6)}
                      for u, t in T["per_unit"].items()}
        out = {"ok": True, "headline": round(float(headline_val), 6), "stdev": round(float(stdev), 6),
               "seeds": ev.seeds, "split": a.split, "mode": a.mode, "gate": gate,
               "metrics": metrics.round_floats({
                   "adr_loc_macro": hl["headline"], "adr_loc_macro_exec": hl["adr_loc_macro_exec"],
                   "adr_loc_macro_edit": hl["adr_loc_macro_edit"], "edit_artifact_adr_exec": hl["edit_artifact_adr_exec"],
                   "fpr_session_any": T["pooled"]["fpr_session_any"]["p"] if T["pooled"]["fpr_session_any"] else None,
                   "coverage_any": T["pooled"]["coverage_any"], "check_errors": T["check_errors"],
                   "headline_cells": len(T["cells"]), "runtime_s": ev.timing["total_s"],
                   **({"headline_ungated": hl["headline"]} if gate else {}),
                   **({"labeled_recall_macro": labeled["labeled_recall_macro"]} if labeled else {})}),
               "per_check": per_check, "per_corpus": per_corpus, "timing": ev.timing,
               "report": str(rpath), "content_sha256": report["content_sha256"]}
        print(json.dumps(out, sort_keys=True))
        return 0
    except EvalError as e:
        return _fail(str(e))
    except Exception as e:  # any crash of the eval or the system under test is a failed run, never a silent pass
        return _fail(f"{type(e).__name__}: {e}")


def _write_contradictions(path: Path, H: dict, private: set) -> None:
    """Every honest-pack contradiction, refs only (no content), for the daytime manual review. Private units are
    aggregated to per-(check, reason) counts (analysis/README.md rule 7)."""
    lines = []
    for u in sorted(H):
        agg = Counter()
        for sid in sorted(H[u]):
            for cid, chk, reason in H[u][sid].get("contradictions", []):
                if u in private:
                    agg[(chk, reason)] += 1
                else:
                    lines.append({"corpus": u.split("/", 1)[0], "unit": u, "session_id": sid, "call_id": cid,
                                  "check": chk, "reason": reason})
        for (chk, reason), n in sorted(agg.items()):
            lines.append({"corpus": u.split("/", 1)[0], "unit": u, "check": chk, "reason": reason, "n": n,
                          "note": "private unit: aggregate only"})
    path.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
