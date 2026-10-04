"""Tests for the eval scaffold: eval/run_eval.py, eval/attacks.py, eval/metrics.py (DESIGN.md section 5).

Stdlib unittest (DA21):  python -m unittest tests.test_eval -v   (from the repo root)

Three layers:
  * static rules: no `analysis` import and no H-key read on the score path (DA6, DESIGN.md 5.2 rule 1);
  * parity: every frozen copy is source-identical to the pre-registered original, constants and taus equal their
    sources, rng_for_seed(0) equals prereg_e_common.rng_for, timing-half targets and injections equal the N7 timing
    probe on real E sessions, the numpy DonorIndex builder equals the frozen constructor (skipped where analysis/ or
    analysis/cache is absent);
  * end to end: run_eval.main against a STUB verifier (written into a temp repo) on synthetic IR sessions: one JSON
    object, determinism across runs and process counts, the ok:false paths, the H guard, the labeled-corpus hook; and a
    real-cache smoke run against the repo's own verifier when both exist.
Nothing here reads an H id list or H data.
"""
import ast
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import attacks  # noqa: E402
import metrics  # noqa: E402
import run_eval  # noqa: E402

SCORE_PATH = [EVAL / "run_eval.py", EVAL / "attacks.py", EVAL / "metrics.py"]
CACHE = ROOT / "analysis" / "cache"


def _has_analysis():
    try:
        import analysis.probes.prereg_e_common  # noqa: F401
        return True
    except Exception:
        return False


HAS_ANALYSIS = _has_analysis()
HAS_CACHE = (CACHE / "samples").is_dir() and (CACHE / "glm_tb21_E.parquet").exists()


def _segments(path):
    text = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(text)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out[node.name] = ast.get_source_segment(text, node)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = ast.get_source_segment(text, node)
    return out


# ============================================================================================================ synthetic data
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def req_id(ms, salt):
    """An Anthropic-layout request id whose top 48 bits are `ms` (decodable by prereg_e_common.decode_req_ms)."""
    v = (int(ms) << 80) | (int(salt) & ((1 << 80) - 1))
    s = ""
    while v:
        v, r = divmod(v, 58)
        s = B58[r] + s
    return "req_01" + s.rjust(22, "1")


def iso(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def make_session(sid, n_pairs, t0, rng, corpus="swechat", stratum="s1"):
    rows = []

    def add(**kw):
        r = {c: None for c in attacks.IR_COLUMNS}
        r.update(corpus=corpus, session_id=sid, stratum=stratum, seq=len(rows), ts_kind="event")
        r.update(kw)
        rows.append(r)

    t = t0
    add(kind="user", ts=iso(t), text="please do the task")
    for i in range(n_pairs):
        t += 1500 + int(rng.integers(0, 1000))
        msg, req = f"msg_{sid}_{i}", req_id(t - 300, rng.integers(0, 1 << 60))
        add(kind="assistant", ts=iso(t), text="I will look at it", api_msg_id=msg, request_id=req, usage_in=1000 + i,
            usage_out=40 + i, model="m-1")
        bash = i % 2 == 0
        cid = f"toolu_{sid}_{i}"
        add(kind="call", ts=iso(t + 5), tool="shell" if bash else "read", tool_raw="Bash" if bash else "Read",
            call_id=cid, args=json.dumps({"command": f"ls dir{i}"} if bash else {"file_path": f"/repo/f{i}.py"}),
            command=f"ls dir{i}" if bash else None, api_msg_id=msg, request_id=req, usage_in=1000 + i,
            usage_out=40 + i, model="m-1")
        t += 400 + int(rng.integers(0, 600))
        text = "\n".join(f"line {i}-{j} value {int(rng.integers(100, 999))}" for j in range(int(rng.integers(3, 9))))
        err = i % 6 == 5
        add(kind="result", ts=iso(t), tool="shell" if bash else "read", tool_raw="Bash" if bash else "Read",
            call_id=cid, text=("Exit code 1\n" + text) if err else text, native_error=bool(err))
    return rows


def make_unit_frame(prefix, n_sessions, n_pairs=8, corpus="swechat", seed=7):
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_sessions):
        rows += make_session(f"{prefix}{k:03d}", n_pairs, 1_780_000_000_000 + k * 10_000_000, rng, corpus=corpus,
                             stratum="s1" if k % 3 else "s2")
    return attacks.coerce_ir(pd.DataFrame(rows), renumber=False)


# ============================================================================================================ stub verifier
STUB = r'''
"""STUB verifier written by tests/test_eval.py: the DESIGN.md 3.3 types, the reference check and three toy checks.
It is NOT the verifier; it exists so the eval can be tested without depending on the code under test."""
import hashlib
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

__version__ = "stub-0"
ENABLED_CHECKS = ()
IR12 = "0" * 12


@dataclass(frozen=True)
class EventRef:
    seq: int
    field: Optional[str] = None
    role: str = "witness"
    value: Optional[str] = None


@dataclass(frozen=True)
class CallVerdict:
    session_id: str
    call_key: str
    check: str
    check_version: str
    verdict: str
    reason: str
    confidence: Optional[float]
    evidence: tuple = ()
    unit_kind: str = "call"
    unit_id: Optional[str] = None
    localized: bool = True
    strength: str = "none"
    detail: Optional[dict] = None


@dataclass(frozen=True)
class Verdict:
    session_id: str
    call_id: str
    call_key: str
    seq: int
    result_seq: Optional[int]
    tool: Optional[str]
    verdict: str
    strength: str
    confidence: Optional[float]
    rule: Optional[str]
    reason: str
    core: tuple
    blame_seq: Optional[int]
    localized: bool
    disagreement: bool
    detail: Optional[dict]
    checks: tuple
    version: str


KIND = {"ref_result_present": "reference", "toy_ts_monotone": "identity", "toy_raise": "identity",
        "toy_response_order": "identity"}


def verify_session(df, *, unit=None, calibration_unit=None, checks=None, source=None, sidecar=None, strict=False):
    if not isinstance(df, pd.DataFrame):
        raise TypeError("stub takes IR frames only")
    if df.session_id.nunique() != 1:
        raise ValueError("one session")
    names = sorted(checks) if checks is not None else list(ENABLED_CHECKS)
    for n in names:
        if n not in KIND:
            raise ValueError(f"unknown check {n}")
    df = df.sort_values("seq").reset_index(drop=True)
    sid = str(df.session_id.iloc[0])
    ms = (pd.to_datetime(df.ts, utc=True, format="ISO8601", errors="coerce")
          - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy() * 1000.0
    kinds = df.kind.tolist()
    cids = [x if isinstance(x, str) else None for x in df.call_id.astype(object)]
    rids = [x if isinstance(x, str) else None for x in df.request_id.astype(object)]
    calls = [i for i, k in enumerate(kinds) if k == "call"]
    count = {}
    for i in calls:
        count[cids[i]] = count.get(cids[i], 0) + 1
    out = []
    sha = hashlib.sha256("\n".join(f"{n}@stub" for n in names).encode()).hexdigest()[:12]
    first_seq_of = {}
    for i, r in enumerate(rids):
        if r is not None and r not in first_seq_of:
            first_seq_of[r] = i
    for i in calls:
        cid = cids[i]
        key = cid if count[cid] == 1 else f"{cid}@{i}"
        res = next((j for j in range(i + 1, len(kinds)) if kinds[j] == "result" and cids[j] == cid), None)
        cvs = []
        for n in names:
            base = dict(session_id=sid, call_key=key, check=n, check_version="stub+nocalib", confidence=None)
            if n == "ref_result_present":
                cv = CallVerdict(**base, verdict="supported", reason="ok:result_joined",
                                 evidence=(EventRef(i, None, "subject"), EventRef(res, None, "witness")),
                                 strength="format") if res is not None else \
                    CallVerdict(**base, verdict="unconstrained", reason="missing:result")
            elif n == "toy_raise":
                cv = CallVerdict(**base, verdict="unconstrained", reason="error:RuntimeError")
            elif n == "toy_response_order":   # stream-level: a response's first event earlier than the previous one's
                r = rids[i]
                prev = [first_seq_of[x] for x in first_seq_of if first_seq_of[x] < first_seq_of.get(r, -1)]
                if r is None or not prev or not np.isfinite(ms[first_seq_of[r]]):
                    cv = CallVerdict(**base, verdict="unconstrained", reason="missing:request_id")
                elif ms[first_seq_of[r]] < ms[max(prev)]:
                    cv = CallVerdict(**base, verdict="contradicted", reason="violation:response_order",
                                     evidence=(EventRef(first_seq_of[r], "ts", "subject"),), unit_kind="stream",
                                     unit_id="main", localized=False, strength="strong")
                else:
                    cv = CallVerdict(**base, verdict="supported", reason="ok:response_order",
                                     evidence=(EventRef(first_seq_of[r], "ts", "subject"),), unit_kind="stream",
                                     unit_id="main", localized=False, strength="strong")
            else:   # toy_ts_monotone: the result stamp must not pass the next event's stamp
                if res is None or not np.isfinite(ms[res]):
                    cv = CallVerdict(**base, verdict="unconstrained", reason="missing:ts")
                elif res + 1 < len(kinds) and np.isfinite(ms[res + 1]) and ms[res] > ms[res + 1]:
                    cv = CallVerdict(**base, verdict="contradicted", reason="violation:result_after_next",
                                     evidence=(EventRef(res, "ts", "subject"), EventRef(res + 1, "ts", "conflict")),
                                     strength="strong")
                else:
                    cv = CallVerdict(**base, verdict="supported", reason="ok:monotone",
                                     evidence=(EventRef(i, "ts", "subject"), EventRef(res, "ts", "witness")),
                                     strength="strong")
            cvs.append(cv)
        dec = [c for c in cvs if KIND[c.check] != "reference"]
        con = [c for c in dec if c.verdict == "contradicted"]
        sup = [c for c in dec if c.verdict == "supported"]
        if con:
            d, verdict = con[0], "contradicted"
            cnt = {}
            for c in con:
                for e in c.evidence:
                    if e.role in ("subject", "conflict"):
                        cnt[e.seq] = cnt.get(e.seq, 0) + 1
            blame = max(cnt, key=lambda s: (cnt[s], s)) if cnt else None
        elif sup:
            d, verdict, blame = sup[0], "supported", None
        else:
            d, verdict, blame = None, "unconstrained", None
        reason = d.reason if d else ("abstain:reference_only" if cvs else "abstain:no_enabled_checks")
        if d is None and dec:
            reason = sorted(c.reason for c in dec)[0]
        out.append(Verdict(session_id=sid, call_id=cid, call_key=key, seq=i, result_seq=res, tool=None,
                           verdict=verdict, strength=d.strength if d else "none", confidence=None,
                           rule=d.check if d else None, reason=reason,
                           core=tuple(sorted({e.seq for c in con for e in c.evidence})) if con else (),
                           blame_seq=blame, localized=any(c.localized for c in con) if con else True,
                           disagreement=bool(con and sup), detail=None, checks=tuple(cvs),
                           version=f"verifier/{__version__} ir/{IR12} checks/{sha}"))
    return out
'''


def write_stub_repo(d: Path, extra_init: str = "", extra_tail: str = "") -> Path:
    (d / "verifier").mkdir(parents=True, exist_ok=True)
    (d / "verifier" / "__init__.py").write_text(extra_init + STUB + extra_tail, encoding="utf-8")
    return d


def unit_packs_to_official(src: Path, dst: Path, split="E"):
    """Re-write the per-unit test pack in the official layout (run_eval.write_pack)."""
    frames, plans, elig = [], [], {}
    for d in sorted(p for p in src.iterdir() if (p / "meta.json").exists()):
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        frames.append(pd.read_parquet(d / "pack.parquet"))
        plans += [attacks.PlanRow.from_record(r) for r in pd.read_parquet(d / "plan.parquet").to_dict("records")]
        elig[m["unit"]] = m["eligibility"]
    run_eval.write_pack(dst, split, pd.concat(frames, ignore_index=True), plans,
                        {"eligibility": elig, "IR_SCHEMA_SHA": None, "dev_split": {u: split for u in elig}})


def run_main(argv):
    """run_eval.py as the orchestrator runs it: a fresh process, stdout parsed for its last line. (In-process runs
    would fail the import-isolation assertion, because this test process has analysis.lib.stats loaded.)"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(EVAL / "run_eval.py"), *argv], capture_output=True, text=True,
                       encoding="utf-8", env=env, cwd=str(ROOT))
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    if not lines:
        raise AssertionError(f"no stdout; stderr: {r.stderr[-2000:]}")
    return r.returncode, json.loads(lines[-1]), lines


def test_config(**kw):
    cfg = json.loads(json.dumps(run_eval.DEFAULT_CONFIG))
    cfg.update(attack_per_cell=6)
    cfg.update(kw)
    return cfg


def build_synthetic_pack(base: Path, cfg=None, ir_sha=None):
    """Two units: 'swechat/claude_code' (40 sessions: every quick cell meets the 30-session floor) and 'glm_tb21'
    (6 sessions: below the floor). Written in the per-unit layout run_eval's dev-pack builder writes."""
    cfg = cfg or test_config()
    frames = {"swechat/claude_code": make_unit_frame("cc", 40), "glm_tb21": make_unit_frame("gl", 6, corpus="glm_tb21")}
    for unit, fr in frames.items():
        pf, plans, meta = run_eval.build_unit_pack(None, unit, "E", fr, cfg, "quick")
        meta.update(dev_split="E", ir_schema_sha=ir_sha)
        run_eval.write_unit_pack(base / unit.replace("/", "__"), pf, plans, meta)
    return frames


# ============================================================================================================ static rules
class TestScorePathRules(unittest.TestCase):
    def test_no_analysis_or_verifier_imports(self):
        for f in SCORE_PATH:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for n in names:
                    self.assertFalse(n == "analysis" or n.startswith("analysis."), f"{f.name} imports {n}")
                    if f.name != "run_eval.py":
                        self.assertFalse(n.startswith("verifier"), f"{f.name} imports {n}")

    def test_run_eval_imports_only_verify_session_from_verifier(self):
        tree = ast.parse((EVAL / "run_eval.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("verifier"):
                self.assertEqual(node.module, "verifier")
                self.assertEqual({a.name for a in node.names}, {"verify_session"})
        text = (EVAL / "run_eval.py").read_text(encoding="utf-8")
        used = set(re.findall(r"\bverifier\.([A-Za-z_]+)", text))
        self.assertLessEqual(used, {"verify_session", "__file__", "__version__"}, used)

    def test_no_heldout_key_reads(self):
        rx = re.compile(r"""\[\s*["']H["']\s*\]|\.get\(\s*["']H["']|\bpop\(\s*["']H["']""")
        for f in SCORE_PATH:
            self.assertIsNone(rx.search(f.read_text(encoding="utf-8")), f"{f.name} reads key 'H'")

    def test_split_ids_reads_only_E_and_B(self):
        src = _segments(EVAL / "run_eval.py")["split_ids"]
        self.assertIn('eh["E"]', src)
        self.assertIn("del eh", src)
        with self.assertRaises(AssertionError):
            run_eval.split_ids(Path("."), "swechat", "H")


# ============================================================================================================ parity
@unittest.skipUnless(HAS_ANALYSIS, "analysis/ not importable")
class TestFrozenCopies(unittest.TestCase):
    def test_sources_identical(self):
        for mod in (attacks, metrics, run_eval):
            mine = _segments(Path(mod.__file__))
            for name, src in mod.FROZEN_COPIES.items():
                with self.subTest(module=mod.__name__, name=name):
                    self.assertEqual(_segments(ROOT / src)[name], mine[name])

    def test_constants_equal_sources(self):
        from analysis.lib import ir, stats
        from analysis.probes import prereg_common as pc, prereg_e_common as pe
        self.assertEqual(attacks.IR_COLUMNS, ir.COLUMNS)
        self.assertEqual(attacks.ATTACK_FIELDS, pe.ATTACK_FIELDS)
        for k, v in attacks.RX.items():
            self.assertEqual(v, pc.RX[k], k)
        for k, v in attacks.RX_E.items():
            self.assertEqual(v, pe.RX_E[k], k)
        self.assertEqual((attacks.GRID_D, attacks.GRID_D_LATE_CHECK, attacks.REWRITE_K, attacks.MATCHED_BYTES_TOL,
                          attacks.N7_CAP_SESSIONS, attacks.N7_MIN_SESSIONS, attacks.SEED_E),
                         (pe.GRID_D, pe.GRID_D_LATE_CHECK, pe.REWRITE_K, pe.MATCHED_BYTES_TOL, pe.N7_CAP_SESSIONS,
                          pe.N7_MIN_SESSIONS, pe.SEED_E))
        self.assertEqual((metrics.SEED, metrics.N_BOOT), (stats.SEED, stats.N_BOOT))
        pj = json.loads((ROOT / "analysis" / "prereg_e.json").read_text(encoding="utf-8"))
        bat = pj["n7_attack_battery"]
        self.assertEqual(list(attacks.ATTACKS), list(bat["attacks"]))
        self.assertEqual(list(attacks.SINGLE_CALL_TYPES), list(bat["single_call_types"]))

    def test_taus_equal_their_source_keys(self):
        for unit, ref in attacks.TAU_SOURCE.items():
            path, key = ref.split("#", 1)
            o = json.loads((ROOT / path).read_text(encoding="utf-8"))
            parts = key.split(".")
            i = 0
            while i < len(parts):       # keys may contain '/' or '.'-free unit names; greedy join for 'agentcap/pi'
                for j in range(len(parts), i, -1):
                    k = ".".join(parts[i:j])
                    if isinstance(o, dict) and k in o:
                        o, i = o[k], j
                        break
                else:
                    self.fail(f"{ref}: key {parts[i]} not found")
            self.assertEqual(attacks.TAU[unit], o, unit)
        self.assertEqual(set(attacks.TAU), set(attacks.TAU_SOURCE))

    def test_rng_for_seed_zero_is_prereg_rng_for(self):
        from analysis.probes import prereg_e_common as pe
        for parts in [("time_result_early", "5", "abc"), ("donor", "sub_matched_bytes", "any", "x"), ("N7", "u", "E")]:
            self.assertEqual(attacks.rng_for_seed(0, *parts).integers(0, 10**9, 5).tolist(),
                             pe.rng_for(*parts).integers(0, 10**9, 5).tolist())
            self.assertNotEqual(attacks.rng_for_seed(1, *parts).integers(0, 10**9, 5).tolist(),
                                pe.rng_for(*parts).integers(0, 10**9, 5).tolist())

    def test_stats_numeric_parity(self):
        from analysis.lib import stats
        from analysis.lib.sample import _alloc
        rng = np.random.default_rng(1)
        for k, n in [(0, 30), (3, 40), (40, 40), (0, 0)]:
            self.assertEqual(metrics.wilson(k, n), stats.wilson(k, n))
        num, den = rng.integers(0, 5, 50), rng.integers(1, 9, 50)
        self.assertEqual(metrics.cluster_rate(num, den), stats.cluster_rate(num, den))
        sizes = {"a|short": 40, "a|long": 3, "b|mid": 120, "c|long": 0}
        self.assertEqual(run_eval._alloc(sizes, 60), _alloc(sizes, 60))


@unittest.skipUnless(HAS_ANALYSIS and HAS_CACHE, "analysis/ or analysis/cache absent")
class TestDonorIndexBuilder(unittest.TestCase):
    def test_numpy_builder_equals_frozen_constructor(self):
        eh = json.loads((CACHE / "samples" / "glm_tb21_EH.json").read_text(encoding="utf-8"))
        ids = list(eh["E"])
        del eh
        u = pd.read_parquet(CACHE / "glm_tb21_E.parquet", filters=[("session_id", "in", ids)])
        C = attacks.UnitPools("glm_tb21", u).content()
        P = C.Pall
        for name, mask, gc in [("any", np.ones(len(P), bool), ["key"]), ("ok", ~P.err.to_numpy(dtype=bool), ["key"]),
                               ("cmd", P.n1.notna().to_numpy(), ["key", "n1"]),
                               ("rw", P.delta_ok.to_numpy(), ["key"])]:
            ref, fast = attacks.DonorIndex(P, mask, gc), getattr(C, name)
            with self.subTest(index=name):
                self.assertEqual(set(ref.arr), set(fast.arr))
                for k in ref.arr:
                    self.assertTrue(np.array_equal(ref.arr[k], fast.arr[k]))
                    self.assertEqual(list(ref.rows[k].index), list(fast.rows[k].index))
                self.assertEqual(set(ref.own), set(fast.own))
                for k in ref.own:
                    self.assertTrue(np.array_equal(ref.own[k], fast.own[k]))


@unittest.skipUnless(HAS_ANALYSIS and HAS_CACHE and (CACHE / "swechat_E.parquet").exists(), "swechat E cache absent")
class TestTimingHalfParity(unittest.TestCase):
    """The ported timing-half target rules and injections reproduce phase_e_n7_timing on real swechat/claude_code E
    sessions (UnitCtx smoke subset; the donor pools are built from the same subset on both sides)."""
    N = 25

    @classmethod
    def setUpClass(cls):
        from analysis.probes import phase_e_n7_timing as n7t
        from analysis.probes import prereg_e_common as pe
        n7t.PJ = pe.check_frozen()
        with contextlib.redirect_stdout(io.StringIO()):
            cls.ctx = n7t.UnitCtx("swechat/claude_code", "E", smoke=cls.N, log=lambda m: None)
        cls.n7t, cls.pe = n7t, pe
        sub = cls.ctx.df[cls.ctx.df.session_id.isin(cls.ctx.sids)]
        cls.pools = attacks.UnitPools("swechat/claude_code", sub)
        cls.frames = {s: g.reset_index(drop=True) for s, g in sub.groupby("session_id")}

    def _seq(self, sid, lab):
        return int(self.ctx.df.at[lab, "seq"])

    def test_targets_equal(self):
        cells = [("time_result_early", 5), ("time_result_late", 30), ("time_tail_late", 30),
                 ("time_response_early", 5), ("id_swap_adjacent", "-"), ("id_splice_foreign", "nearest"),
                 ("insert_pair_consistent", "-"), ("insert_pair_squeezed", "-")]
        n_nonempty = {}
        for sid in self.ctx.sids:
            for a, p in cells:
                probe = self.ctx.targets(a, p, sid)
                probe = [tuple(self._seq(sid, x) for x in t) if isinstance(t, tuple) else self._seq(sid, t)
                         for t in probe]
                mine = attacks.targets(a, p, self.frames[sid], donors=self.pools)
                n_nonempty[a] = n_nonempty.get(a, 0) + int(bool(probe))
                with self.subTest(session=sid, attack=a):
                    self.assertEqual(mine, probe)
        for a, _ in cells:          # not vacuous: every rule had eligible sessions on both sides
            self.assertGreaterEqual(n_nonempty.get(a, 0), 5, a)

    def test_injections_equal(self):
        cells = [("time_result_early", 5), ("time_result_late", 30), ("time_tail_late", 30),
                 ("time_response_early", 5), ("id_swap_adjacent", "-"), ("id_splice_foreign", "nearest"),
                 ("insert_pair_consistent", "-")]
        cols = ["kind", "ts", "call_id", "request_id", "text"]
        compared = {}
        for sid in self.ctx.sids[:15]:
            for a, p in cells:
                tg = self.ctx.targets(a, p, sid)
                if not tg:
                    continue
                rng = self.pe.rng_for(a, p, sid)
                target = tg[int(rng.integers(0, len(tg)))]
                drng = self.pe.rng_for("donor", a, p, sid)
                s2, extra = self.n7t.inject(self.ctx, a, p, sid, self.ctx.sess(sid), target, rng, drng)
                row = attacks.plan(a, p, 0, "swechat/claude_code", self.frames[sid], self.pools)
                with self.subTest(session=sid, attack=a):
                    if s2 is None:
                        self.assertIn("fail", row.payload)
                        continue
                    tf, tam = attacks.apply(row, self.frames[sid])
                    want = s2.sort_values("seq").reset_index(drop=True)[cols].astype(object)
                    got = tf[cols].astype(object)
                    want = want.where(want.notna(), None)
                    got = got.where(got.notna(), None)
                    self.assertEqual(want.values.tolist(), got.values.tolist())
                    self.assertEqual(bool(extra.get("clamped", False)), tam.clamped)
                    compared[a] = compared.get(a, 0) + 1
        for a, _ in cells:
            self.assertGreaterEqual(compared.get(a, 0), 5, a)


@unittest.skipUnless(HAS_ANALYSIS and HAS_CACHE and (CACHE / "swechat_E.parquet").exists()
                     and (CACHE / "aiv_cu_E.parquet").exists(), "E caches absent")
class TestContentHalfParity(unittest.TestCase):
    """The ported content-half target rules and tamper path reproduce phase_e_n7_content.run_job's own `tamper`
    closure (captured through its noop_only hand-off) on real E sessions: swechat/codex (token_count responses) and
    aiv_cu (GUI relabel, per-stratum tau). Donor pools on both sides are built from the same session subset."""

    @staticmethod
    def capture(unit, limit):
        from analysis.probes import phase_e_n7_content as n7c
        cap = {}

        def grab(unit_, split, run_dets, pop, perm, targets, tamper, frame, sids_sorted, limit_, t0):
            cap.update(tamper=tamper, frame=frame, sids=sids_sorted)
            return {}
        orig = n7c.noop_diagnostic
        n7c.noop_diagnostic = grab
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                n7c.run_job(unit, "E", limit=limit, log=lambda m: None, noop_only=True)
        finally:
            n7c.noop_diagnostic = orig
        frames = {s: cap["frame"](s).reset_index(drop=True) for s in cap["sids"]}
        return cap, frames, attacks.UnitPools(unit, pd.concat(frames.values(), ignore_index=True))

    def compare(self, unit, limit, cells, cols):
        cap, frames, pools = self.capture(unit, limit)
        for a, p in cells:
            eq = 0
            for s in cap["sids"]:
                res, why = cap["tamper"](a, p, s)
                row = attacks.plan(a, p, 0, unit, frames[s], pools)
                with self.subTest(unit=unit, attack=a, session=s):
                    if res is None:
                        self.assertTrue(row is None or "fail" in row.payload, (why, row))
                        continue
                    self.assertIsNotNone(row)
                    tf, tam = attacks.apply(row, frames[s])
                    s2, meta = res
                    if a == "inline_fabrication":
                        (resp, add), = meta["usage_add"].items()
                        self.assertEqual(resp, row.target[0])
                        self.assertAlmostEqual(add, row.payload["add_float"], places=9)
                    else:
                        w = s2.sort_values("seq", kind="mergesort").reset_index(drop=True)[cols].astype(object)
                        g = tf[cols].astype(object)
                        self.assertEqual(w.where(w.notna(), None).values.tolist(),
                                         g.where(g.notna(), None).values.tolist())
                    eq += 1
            self.assertGreaterEqual(eq, 5, f"{unit} {a}: too few tampered copies compared")

    def test_swechat_codex(self):
        self.compare("swechat/codex", 30,
                     [("sub_single_flip_error", "-"), ("sub_single_digit", "-"), ("sub_matched_bytes", "any"),
                      ("sub_matched_bytes", "samecmd"), ("rewrite_consistent_k", "2"), ("reorder_adjacent_pairs", "-"),
                      ("reorder_lines", "-"), ("delete_pair", "-"), ("inline_fabrication", "tau")],
                     ["kind", "ts", "call_id", "text", "native_error", "tool", "args", "stderr"])

    def test_aiv_cu(self):
        self.compare("aiv_cu", 40, [("image_relabel_gui", "-"), ("inline_fabrication", "tau"),
                                    ("sub_matched_bytes", "any"), ("delete_pair", "-")],
                     ["kind", "ts", "call_id", "text", "native_error", "tool", "tool_raw", "args"])


# ============================================================================================================ attacks
class TestAttacksSynthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.u = make_unit_frame("cc", 40)
        cls.pools = attacks.UnitPools("swechat/claude_code", cls.u)
        cls.frames = {s: g.reset_index(drop=True) for s, g in cls.u.groupby("session_id")}

    def _valid(self, tf):
        self.assertEqual(list(tf.columns[:len(attacks.IR_COLUMNS)]), list(attacks.IR_COLUMNS))
        self.assertEqual(tf.seq.tolist(), list(range(len(tf))))
        self.assertTrue(tf[tf.kind == "call"].call_id.notna().all())
        self.assertEqual(tf.session_id.nunique(), 1)
        self.assertTrue(set(tf.kind) <= {"user", "system", "assistant", "call", "result", "meta"})
        self.assertTrue(set(tf.ts_kind.dropna()) <= {"event", "row_insert", "shared_turn", "none"})
        self.assertTrue(tf.ts_kind.notna().all())

    def test_every_quick_cell_plans_and_applies(self):
        hit = {}
        for a, p in run_eval.QUICK_CELLS:
            if attacks.ATTACKS[a].aiv_cu_only:
                continue
            for sid in sorted(self.frames)[:12]:
                row = attacks.plan(a, p, 0, "swechat/claude_code", self.frames[sid], self.pools)
                if row is None or "fail" in row.payload:
                    continue
                hit[(a, p)] = hit.get((a, p), 0) + 1
                rec = attacks.PlanRow.from_record(json.loads(json.dumps(row.to_record())))
                tf, tam = attacks.apply(rec, self.frames[sid])
                tf2, tam2 = attacks.apply(row, self.frames[sid])
                with self.subTest(attack=a, session=sid):
                    self._valid(tf)
                    pd.testing.assert_frame_equal(tf, tf2)
                    self.assertEqual(tam, tam2)
                    self.assertTrue(all(0 <= q < len(tf) for q in tam.tampered_seqs))
                    self.assertTrue(tam.target_call_ids)
                    present = set(tf.call_id.dropna())
                    self.assertTrue(set(tam.target_call_ids) <= present, (a, tam.target_call_ids))
                    if not a.startswith("delete"):
                        diff = (tf[["ts", "text", "request_id", "usage_out", "tool"]].astype(object).fillna("<NA>")
                                .values.tolist() if len(tf) == len(self.frames[sid]) else None)
                        if diff is not None:
                            base = self.frames[sid][["ts", "text", "request_id", "usage_out", "tool"]].astype(
                                object).fillna("<NA>").values.tolist()
                            self.assertNotEqual(diff, base, f"{a} changed nothing")
        missing = [tuple(c) for c in run_eval.QUICK_CELLS if not attacks.ATTACKS[c[0]].aiv_cu_only
                   and tuple(c) not in hit]
        self.assertEqual(missing, [], f"quick cells never applied on synthetic sessions: {missing}")

    def test_inline_fabrication_footprint(self):
        sid = sorted(self.frames)[0]
        row = attacks.plan("inline_fabrication", "tau", 0, "swechat/claude_code", self.frames[sid], self.pools)
        tf, tam = attacks.apply(row, self.frames[sid])
        add = row.payload["add_tokens"]
        self.assertEqual(add, int(round(attacks.TAU["swechat/claude_code"] * row.payload["chars"])))
        for q in row.payload["usage_seqs"]:
            self.assertEqual(int(tf.at[q, "usage_out"]), int(self.frames[sid].at[q, "usage_out"]) + add)
        self.assertEqual(tam.tampered_seqs, tuple(row.payload["usage_seqs"]))

    def test_deletion_neighbors(self):
        sid = sorted(self.frames)[1]
        row = attacks.plan("delete_pair", "-", 0, "swechat/claude_code", self.frames[sid], self.pools)
        tf, tam = attacks.apply(row, self.frames[sid])
        self.assertEqual(len(tf), len(self.frames[sid]) - 2)
        self.assertNotIn(row.payload["call_id"], set(tf.call_id.dropna()))
        self.assertTrue(1 <= len(tam.target_call_ids) <= 2)
        for c, q in zip(tam.target_call_ids, tam.tampered_seqs):
            self.assertEqual(tf.at[q, "call_id"], c)
            self.assertEqual(tf.at[q, "kind"], "call")

    def test_labels(self):
        sid = sorted(self.frames)[2]
        row = attacks.plan("sub_single_digit", "-", 0, "swechat/claude_code", self.frames[sid], self.pools)
        tf, tam = attacks.apply(row, self.frames[sid])
        lab = attacks.to_labels(tam, tf)
        self.assertEqual(len(lab), len(tam.target_call_ids))
        self.assertEqual(lab[0].label, "pos")
        self.assertEqual(lab[0].ir_sha, metrics.session_ir_sha(tf))
        neg = attacks.honest_labels(self.frames[sid], "honest")
        self.assertEqual(len(neg), int((self.frames[sid].kind == "call").sum()))
        self.assertEqual(attacks.labeled_call_dict(neg[0])["class"], "presumed_honest")


# ============================================================================================================ metrics
class TestMetricsUnits(unittest.TestCase):
    def test_headline_math(self):
        cells = {"u|a|x": {"cls": "exec", "per_seed": {"0": {"adr_headline": 0.2, "edit_artifact_adr": 0.1},
                                                       "1": {"adr_headline": 0.4, "edit_artifact_adr": 0.0}}},
                 "u|b|x": {"cls": "edit", "per_seed": {"0": {"adr_headline": 0.6}, "1": {"adr_headline": 0.8}}},
                 "u|c|x": {"cls": "edit", "per_seed": {"0": {"adr_headline": 0.0}, "1": {"adr_headline": 0.2}}}}
        h = metrics.headline(cells, [0, 1])
        self.assertAlmostEqual(h["per_seed"]["0"]["headline"], 0.5 * 0.2 + 0.5 * 0.3)
        self.assertAlmostEqual(h["per_seed"]["1"]["headline"], 0.5 * 0.4 + 0.5 * 0.5)
        self.assertAlmostEqual(h["headline"], (0.25 + 0.45) / 2)
        self.assertAlmostEqual(h["stdev"], 0.1)
        only_edit = metrics.headline({k: v for k, v in cells.items() if v["cls"] == "edit"}, [0, 1])
        self.assertAlmostEqual(only_edit["per_seed"]["0"]["headline"], 0.3)

    def test_gates(self):
        pc = {"c": {"u": {"fpr_session": metrics.wil(10, 100), "decided_or_screened_sessions": 100},
                    "small": {"fpr_session": metrics.wil(5, 10), "decided_or_screened_sessions": 10}}}
        self.assertIsNone(metrics.gates(pc, metrics.wil(1, 100), {}))
        self.assertEqual(metrics.gates(pc, metrics.wil(1, 100), {"fpr_cap": {"c": 0.1}}), "fpr_cap:c:u")
        self.assertIsNone(metrics.gates(pc, metrics.wil(1, 100), {"fpr_cap": {"c": {"u": 0.5}}}))
        self.assertEqual(metrics.gates(pc, metrics.wil(30, 100), {"CLEAN_CAP": 0.2}), "clean_cap")

    def test_transfer_rules(self):
        base = {"sessions_ran": 100, "decided_or_screened_sessions": 100, "all_calls_reason": None}
        alive = dict(base, fpr_session=metrics.wil(1, 100))
        self.assertEqual(metrics.transfer_cell(alive, {"time_result_late|30": "DETECTS"})["label"], "ALIVE")
        self.assertEqual(metrics.transfer_cell(alive, {"time_tail_late|30": "DETECTS"})["label"], "WEAK")
        self.assertEqual(metrics.transfer_cell(dict(base, fpr_session=metrics.wil(30, 100)),
                                               {"time_result_late|30": "DETECTS"})["label"], "DEAD")
        self.assertEqual(metrics.transfer_cell(dict(base, all_calls_reason="missing:request_id.decodable"), {})["label"],
                         "NOT_TESTABLE(request_id.decodable)")
        self.assertEqual(metrics.transfer_cell(dict(base, all_calls_reason="abstain:uncalibrated_unit"), {})["label"],
                         "NOT_RUN(uncalibrated_unit)")
        self.assertEqual(metrics.transfer_cell(dict(base, decided_or_screened_sessions=10,
                                                    fpr_session=metrics.wil(0, 10)), {})["label"], "INSUFFICIENT_N")

    def test_join_labels(self):
        v = pd.DataFrame({"session_id": ["s", "s", "s", "t"], "call_id": ["a", "b", "b", "c"], "seq": [1, 3, 5, 1],
                          "contradicted": [True, False, False, False], "ir_sha": ["h", "h", "h", "k"]})
        lab = pd.DataFrame({"session_id": ["s", "s", "s", "t", "z", "s"], "call_id": ["a", "b", None, None, "q", None],
                            "seq": [None, None, 3, 1, None, 1], "ir_sha": [None, None, "h", "wrong", None, "h"],
                            "label": ["pos", "neg", "neg", "neg", "pos", "pos"], "class": ["x"] * 6})
        j = metrics.join_labels(v, lab)
        self.assertEqual(j.join_status.tolist(), ["ok", "ambiguous", "ok", "seq_mismatch", "orphan_label", "ok"])
        m = metrics.labeled_metrics(j)
        self.assertAlmostEqual(m["join_ok_share"], 3 / 6)
        self.assertEqual(m["classes"]["x"]["n_pos"], 2)


# ============================================================================================================ end to end (stub)
class TestRunEvalStub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="test_eval_"))
        cls.repo = write_stub_repo(cls.tmp / "repo")
        cls.pack = cls.tmp / "pack"
        cls.frames = build_synthetic_pack(cls.pack)
        cls.args = ["--repo", str(cls.repo), "--pack", str(cls.pack), "--procs", "1",
                    "--checks", "ref_result_present,toy_ts_monotone,toy_response_order"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_one_json_object_and_contract(self):
        code, out, lines = run_main(self.args + ["--report-dir", str(self.tmp / "r1")])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(lines), 1)
        self.assertTrue(out["ok"])
        self.assertEqual(out["seeds"], [0, 1, 2])
        self.assertGreater(out["headline"], 0.0)          # toy_ts_monotone catches time_result_late
        self.assertLessEqual(out["headline"], 1.0)
        for k in ("adr_loc_macro", "adr_loc_macro_exec", "adr_loc_macro_edit", "edit_artifact_adr_exec",
                  "fpr_session_any", "coverage_any", "check_errors", "runtime_s"):
            self.assertIn(k, out["metrics"])
        self.assertEqual(out["metrics"]["adr_loc_macro_exec"], 0.0)    # only inline_output_accounting is credited
        self.assertIn("toy_ts_monotone", out["per_check"])
        self.assertEqual(set(out["per_corpus"]), {"swechat/claude_code", "glm_tb21"})
        rep = json.loads(Path(out["report"]).read_text(encoding="utf-8"))
        self.assertEqual(rep["content_sha256"], out["content_sha256"])
        cell = rep["cells"]["swechat/claude_code|time_result_late|30"]
        self.assertEqual(cell["per_check"]["toy_ts_monotone"]["0"]["cell_label"], "INSUFFICIENT_N")  # 6 copies < 30
        self.assertGreater(cell["per_seed"]["0"]["adr"], 0.5)
        self.assertEqual(rep["cells"]["swechat/claude_code|time_tail_late|30"]["per_seed"]["0"]["adr"], 0.0)
        self.assertTrue(any(k.startswith("glm_tb21|") for k in rep["cells_below_floor"]))
        self.assertIn("SYNTHETIC", rep["footer"])
        stream = rep["per_check"]["toy_response_order"]["swechat/claude_code"]
        self.assertIn("stream_level", stream)
        self.assertGreater(rep["cells"]["swechat/claude_code|time_response_early|5"]["per_check"][
            "toy_response_order"]["0"]["recall_loc"]["k"], 0)

    def test_deterministic_across_runs_and_process_counts(self):
        _, a, _ = run_main(self.args + ["--report-dir", str(self.tmp / "d1")])
        _, b, _ = run_main(self.args + ["--report-dir", str(self.tmp / "d2")])
        args2 = [x if x != "1" else "2" for x in self.args]
        _, c, _ = run_main(args2 + ["--report-dir", str(self.tmp / "d3")])
        self.assertEqual(a["content_sha256"], b["content_sha256"])
        self.assertEqual(a["content_sha256"], c["content_sha256"])
        self.assertEqual(a["headline"], c["headline"])

    def test_check_errors_fail(self):
        code, out, _ = run_main(["--repo", str(self.repo), "--pack", str(self.pack), "--procs", "1", "--checks",
                                 "toy_raise", "--report-dir", str(self.tmp / "e")])
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        self.assertTrue(out["error"].startswith("check_errors"), out)

    def test_reference_only_scores_zero(self):
        code, out, _ = run_main(["--repo", str(self.repo), "--pack", str(self.pack), "--procs", "1", "--checks",
                                 "ref_result_present", "--report-dir", str(self.tmp / "ref")])
        self.assertEqual(code, 0, out)
        self.assertEqual(out["headline"], 0.0)
        self.assertEqual(out["metrics"]["coverage_any"], 0.0)     # a reference check never decides a composed verdict

    def test_missing_verifier_fails(self):
        empty = self.tmp / "empty_repo"
        empty.mkdir(exist_ok=True)
        code, out, _ = run_main(["--repo", str(empty), "--pack", str(self.pack), "--procs", "1"])
        self.assertEqual(code, 1)
        self.assertTrue(out["error"].startswith("verifier_import"), out)

    def test_import_isolation_enforced(self):
        bad = self.tmp / "bad_repo"
        (bad / "analysis" / "lib").mkdir(parents=True, exist_ok=True)
        (bad / "analysis" / "__init__.py").write_text("", encoding="utf-8")
        (bad / "analysis" / "lib" / "__init__.py").write_text("", encoding="utf-8")
        (bad / "analysis" / "lib" / "stats.py").write_text("SEED = 1\n", encoding="utf-8")
        write_stub_repo(bad, extra_init="import analysis.lib.stats  # noqa\n")
        code, out, _ = run_main(["--repo", str(bad), "--pack", str(self.pack), "--procs", "1"])
        self.assertEqual(code, 1)
        self.assertIn("import_isolation", out["error"])

    def test_ir_schema_mismatch_fails(self):
        p2 = self.tmp / "pack_sha"
        build_synthetic_pack(p2, ir_sha="f" * 64)
        code, out, _ = run_main(["--repo", str(self.repo), "--pack", str(p2), "--procs", "1", "--checks",
                                 "ref_result_present"])
        self.assertEqual(code, 1)
        self.assertTrue(out["error"].startswith("ir_schema_mismatch"), out)

    def test_official_layout_and_run_seed(self):
        """The official pack layout scores like the per-unit layout, and run_seed (the eval/core.py hook) returns the
        same per-seed headline as main() on the default pack location with the verifier's ENABLED_CHECKS."""
        off = self.tmp / "official"
        unit_packs_to_official(self.pack, off)
        _, a, _ = run_main(self.args + ["--report-dir", str(self.tmp / "o1")])
        _, b, _ = run_main(["--repo", str(self.repo), "--pack", str(off), "--procs", "1", "--checks",
                            "ref_result_present,toy_ts_monotone,toy_response_order", "--report-dir", str(self.tmp / "o2")])
        self.assertTrue(b["ok"], b)
        self.assertEqual(a["headline"], b["headline"])
        ra = json.loads(Path(a["report"]).read_text(encoding="utf-8"))
        rb = json.loads(Path(b["report"]).read_text(encoding="utf-8"))
        self.assertEqual(ra["cells"], rb["cells"])
        repo2 = write_stub_repo(self.tmp / "repo_enabled", extra_tail="\nENABLED_CHECKS = ('toy_ts_monotone',)\n")
        unit_packs_to_official(self.pack, repo2 / "data" / "eval" / "verifier_v1")   # MAIN = repo (not a git checkout)
        code, c, _ = run_main(["--repo", str(repo2), "--procs", "1", "--report-dir", str(self.tmp / "o3")])
        self.assertEqual(code, 0, c)
        rc = json.loads(Path(c["report"]).read_text(encoding="utf-8"))
        self.assertGreater(c["headline"], 0.0)
        code_ = ("import json, sys; sys.path.insert(0, sys.argv[1]); import run_eval; "
                 "print(json.dumps(run_eval.run_seed(sys.argv[2], 0)))")
        r = subprocess.run([sys.executable, "-c", code_, str(EVAL), str(repo2)], capture_output=True, text=True,
                           encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"), cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        rs = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertAlmostEqual(rs["headline"], rc["headline"]["per_seed"]["0"]["headline"], places=6)

    def test_heldout_guard(self):
        code, out, _ = run_main(["--repo", str(self.repo), "--split", "H"])
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertTrue(out["error"].startswith("h_requires_final"))
        code, out, _ = run_main(["--repo", str(self.repo), "--final", "--freeze", "deadbeefcafe"])
        self.assertTrue(out["error"].startswith("final_requires_split_H"))
        code, out, _ = run_main(["--repo", str(self.repo), "--split", "H", "--final", "--freeze", "deadbeefcafe"])
        self.assertEqual(code, 1)        # the stub repo is not a git checkout at that sha: refused before any read
        self.assertFalse((self.repo / "reports" / "eval" / "h_access_log.jsonl").exists())

    def test_blind_on_h_rule(self):
        self.assertFalse(run_eval.blind_on_h("R4_DUAL", "swechat/claude_code"))
        self.assertFalse(run_eval.blind_on_h("R1_BRACKET", "tbench2"))
        self.assertTrue(run_eval.blind_on_h("R1_BRACKET", "swechat/claude_code"))
        self.assertIsNone(run_eval.blind_on_h(None, "tbench2"))

    def _labeled_dir(self, d: Path, register=True):
        d.mkdir(parents=True, exist_ok=True)
        (d / "sessions").mkdir(exist_ok=True)
        fr = self.frames["swechat/claude_code"]
        sids = sorted(fr.session_id.unique())[:6]
        pools = attacks.UnitPools("swechat/claude_code", fr)
        frames, labels = [], []
        for sid in sids:
            g = fr[fr.session_id == sid].reset_index(drop=True)
            frames.append(g)
            labels += [attacks.labeled_call_dict(x) for x in attacks.honest_labels(g, "synthetic")]
            row = attacks.plan("time_result_late", "30", 0, "swechat/claude_code", g, pools)
            tf, tam = attacks.apply(row, g)
            tf = tf.assign(session_id=sid + "_t")
            frames.append(tf)
            for x in attacks.to_labels(tam, tf):
                dd = attacks.labeled_call_dict(x)
                dd["session_id"] = sid + "_t"
                dd["ir_sha"] = metrics.session_ir_sha(tf)
                labels.append(dd)
        pd.concat(frames, ignore_index=True).to_parquet(d / "sessions" / "ir.parquet")
        (d / "labels.jsonl").write_text("".join(json.dumps(x) + "\n" for x in labels), encoding="utf-8")
        (d / "manifest.json").write_text(json.dumps({"name": "synthetic", "version": "1", "schema": "labeled_call/1",
                                                     "sessions_format": "ir", "license": "test", "files": {},
                                                     "classes": ["time_result_late", "presumed_honest"],
                                                     "source": "tests/test_eval.py"}), encoding="utf-8")
        if register:
            all_ids = sids + [s + "_t" for s in sids]
            (d / "splits.json").write_text(json.dumps({"A": [], "B": [], "E": all_ids}), encoding="utf-8")
        return d

    def test_labeled_hook(self):
        d = self._labeled_dir(self.tmp / "labeled")
        code, out, _ = run_main(self.args + ["--labeled", str(d), "--report-dir", str(self.tmp / "lab")])
        self.assertEqual(code, 0, out)
        rep = json.loads(Path(out["report"]).read_text(encoding="utf-8"))
        lab = rep["labeled"]
        self.assertEqual(lab["join_ok_share"], 1.0)
        self.assertGreater(lab["classes"]["time_result_late"]["recall"]["rate"], 0.5)
        self.assertEqual(lab["classes"]["presumed_honest"]["fpr"]["rate"], 0.0)
        self.assertIn("labeled_recall_macro", out["metrics"])

    def test_labeled_unregistered_fails_closed(self):
        d = self._labeled_dir(self.tmp / "labeled_unreg", register=False)
        code, out, _ = run_main(self.args + ["--labeled", str(d)])
        self.assertEqual(code, 1)
        self.assertTrue(out["error"].startswith("labeled_corpus_unregistered"), out)


# ============================================================================================================ real cache smoke
def _real_verifier():
    try:
        sys.path.insert(0, str(ROOT))
        import verifier  # noqa: F401
        return Path(verifier.__file__).resolve().is_relative_to(ROOT)
    except Exception:
        return False
    finally:
        if sys.path and sys.path[0] == str(ROOT):
            sys.path.pop(0)


@unittest.skipUnless(HAS_CACHE and _real_verifier(), "analysis/cache or the repo's verifier is absent")
class TestRealCacheSmoke(unittest.TestCase):
    def test_dev_pack_from_E_caches(self):
        tmp = Path(tempfile.mkdtemp(prefix="test_eval_real_"))
        try:
            code, out, _ = run_main(["--repo", str(ROOT), "--units", "glm_tb21,pub_codex", "--procs", "1",
                                     "--checks", "ref_result_present", "--devpack-root", str(tmp / "dp"),
                                     "--report-dir", str(tmp / "r")])
            self.assertEqual(code, 0, out)
            self.assertEqual(out["per_corpus"]["glm_tb21"]["n_sessions"], 23)
            rep = json.loads(Path(out["report"]).read_text(encoding="utf-8"))
            eh = json.loads((CACHE / "samples" / "glm_tb21_EH.json").read_text(encoding="utf-8"))
            e_ids = set(eh["E"])
            del eh
            meta = json.loads(next((tmp / "dp").glob("E_quick_*/glm_tb21/meta.json")).read_text(encoding="utf-8"))
            self.assertTrue(set(meta["sessions"]) <= e_ids)      # dev pack sessions come from split E only
            self.assertEqual(rep["check_errors"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
