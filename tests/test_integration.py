"""Integration tests across the scaffold lanes: verifier core <-> eval attacks/metrics <-> CLI entry point.

    python -m unittest tests.test_integration -v          (or: python -m unittest discover tests)

Each lane's own tests run against stand-ins (tests/test_eval.py scores a STUB verifier). These tests join the real
pieces where the stand-ins could hide a mismatch:
  * eval/metrics.summarize_session reads the REAL verifier record types (verifier.checks.base Verdict / CallVerdict
    built by verifier.compose.compose);
  * an eval/attacks.py Tamper localizes against the real verifier's raw call_id, blame_seq and stream keys
    (DESIGN.md 5.5 flag_loc), including inserted pairs, deletions and stream-level verdicts;
  * verifier.session stream keys equal the prereg stream key the attacks use ('main' | agent_id | '?');
  * `python -m verifier` exists (DESIGN.md 2.1, 6.1).
No detection check is implemented. The contradictions below are hand-made CallVerdicts, built with the real
constructors for a test-only check class that is never registered. Synthetic sessions only: no corpus, no H.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(Path(__file__).resolve().parent), str(ROOT / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from test_eval import make_unit_frame  # noqa: E402  (synthetic IR sessions; reused, not redefined)
import attacks  # noqa: E402
import metrics  # noqa: E402
from verifier.checks import base  # noqa: E402
from verifier.compose import compose  # noqa: E402
from verifier.session import build_session  # noqa: E402

UNIT = "swechat/claude_code"


class _ToyIdentity:
    """Test-only identity check (never registered, never imported by the verifier)."""
    name = "toy_integration"
    version = "0.0.1"
    kind = "identity"
    strength = "strong"
    requires = frozenset()
    reads = frozenset()
    targets = frozenset()
    unit_kind = "call"
    calibration = None


def _verdicts(session, contra: dict):
    """contra: call_key -> dict(evidence seqs, unit_kind, unit_id, localized). Every other call is unconstrained."""
    cvs = {}
    for k in session.call_keys:
        if k in contra:
            c = contra[k]
            ev = [base.EventRef(seq=int(q), field="ts", role="subject") for q in c["seqs"]]
            cvs[k] = base.contradicted(session, k, _ToyIdentity, "violation:toy", ev, confidence=0.99,
                                       unit_kind=c.get("unit_kind", "call"), unit_id=c.get("unit_id"),
                                       localized=c.get("localized", True))
        else:
            cvs[k] = base.unconstrained(session, k, _ToyIdentity, "abstain:toy_not_target")
    return compose(session, {_ToyIdentity.name: cvs}, {_ToyIdentity.name: "identity"})


class TestRealVerdictsThroughEvalMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.u = make_unit_frame("it", 40)
        cls.pools = attacks.UnitPools(UNIT, cls.u)
        cls.frames = {s: g.reset_index(drop=True) for s, g in cls.u.groupby("session_id")}
        cls.sids = sorted(cls.frames)

    def _tamper(self, attack, param, k=0):
        for sid in self.sids[k:]:
            row = attacks.plan(attack, param, 0, UNIT, self.frames[sid], self.pools)
            if row is not None and "fail" not in row.payload:
                tf, tam = attacks.apply(row, self.frames[sid])
                return tf, tam, build_session(tf, unit=UNIT)
        self.fail(f"no synthetic session admits {attack}:{param}")

    def _key_of(self, s, call_id):
        return next(k for k in s.call_keys if s.call_id_of(k) == call_id)

    def test_record_types_match_what_metrics_reads(self):
        tf, tam, s = self._tamper("sub_single_digit", "-")
        v = _verdicts(s, {})
        self.assertTrue(v and all(isinstance(x, base.Verdict) for x in v))
        out = metrics.summarize_session(v, tamper=tam)
        self.assertEqual(out["n_calls"], len(s.call_keys))
        self.assertEqual(out["comp"]["unconstrained"], len(v))
        self.assertFalse(out["comp"]["flag"])
        self.assertRegex(out["version"], r"\bir/[0-9a-f]{12}\b.*\bchecks/[0-9a-f]{12}\b")   # run_eval parses these

    def test_target_call_is_localized(self):
        tf, tam, s = self._tamper("sub_single_digit", "-")
        key = self._key_of(s, tam.target_call_ids[0])
        out = metrics.summarize_session(_verdicts(s, {key: {"seqs": [s.result_seq(key)]}}), tamper=tam)
        self.assertTrue(out["comp"]["flag"])
        self.assertTrue(out["comp"]["flag_loc"])
        self.assertTrue(out["checks"][_ToyIdentity.name]["flag_loc"])

    def test_other_call_flags_but_does_not_localize(self):
        tf, tam, s = self._tamper("sub_single_digit", "-")
        other = next(k for k in s.call_keys if s.call_id_of(k) not in tam.target_call_ids
                     and s.call_seq(k) not in tam.tampered_seqs and s.result_seq(k) not in tam.tampered_seqs)
        out = metrics.summarize_session(_verdicts(s, {other: {"seqs": [s.call_seq(other)]}}), tamper=tam)
        self.assertTrue(out["comp"]["flag"])
        self.assertFalse(out["comp"]["flag_loc"])

    def test_blame_seq_localizes_when_the_call_differs(self):
        tf, tam, s = self._tamper("time_result_late", "30")
        other = next(k for k in s.call_keys if s.call_id_of(k) not in tam.target_call_ids)
        v = _verdicts(s, {other: {"seqs": [tam.tampered_seqs[0], tam.tampered_seqs[0]]}})
        vv = next(x for x in v if x.call_key == other)
        self.assertEqual(vv.blame_seq, tam.tampered_seqs[0])
        self.assertTrue(metrics.summarize_session(v, tamper=tam)["comp"]["flag_loc"])

    def test_stream_level_verdict_localizes_by_stream_key(self):
        tf, tam, s = self._tamper("time_response_early", "5")
        self.assertTrue(tam.target_streams)
        for q in tam.tampered_seqs:
            self.assertIn(s.streams[q], tam.target_streams)
        other = next(k for k in s.call_keys if s.call_id_of(k) not in tam.target_call_ids
                     and s.call_seq(k) not in tam.tampered_seqs)
        hit = {other: {"seqs": [s.call_seq(other)], "unit_kind": "stream", "unit_id": s.streams[s.call_seq(other)],
                       "localized": False}}
        self.assertTrue(metrics.summarize_session(_verdicts(s, hit), tamper=tam)["comp"]["flag_loc"])
        miss = {other: dict(hit[other], unit_id="not-a-stream")}
        self.assertFalse(metrics.summarize_session(_verdicts(s, miss), tamper=tam)["comp"]["flag_loc"])

    def test_inserted_pair_call_id_matches(self):
        tf, tam, s = self._tamper("insert_pair_consistent", "-")
        self.assertTrue(tam.target_call_ids[0].startswith("inserted:"))
        key = self._key_of(s, tam.target_call_ids[0])
        out = metrics.summarize_session(_verdicts(s, {key: {"seqs": [s.call_seq(key)]}}), tamper=tam)
        self.assertTrue(out["comp"]["flag_loc"])

    def test_deletion_neighbors_are_targets(self):
        tf, tam, s = self._tamper("delete_pair", "-")
        key = self._key_of(s, tam.target_call_ids[0])
        out = metrics.summarize_session(_verdicts(s, {key: {"seqs": [s.call_seq(key)]}}), tamper=tam)
        self.assertTrue(out["comp"]["flag_loc"])


class TestStreamKeyParity(unittest.TestCase):
    def test_session_streams_equal_attack_streams(self):
        u = make_unit_frame("sk", 3)
        g = u[u.session_id == sorted(u.session_id.unique())[0]].reset_index(drop=True).copy()
        n = len(g)
        g["is_subagent"] = [i % 4 == 1 or i % 4 == 2 for i in range(n)]
        g["agent_id"] = [("a7" if i % 8 < 4 else None) if i % 4 in (1, 2) else None for i in range(n)]
        g = attacks.coerce_ir(g, renumber=False)
        s = build_session(g, unit=UNIT)
        self.assertEqual(list(s.streams), attacks._stream(g.is_subagent, g.agent_id))
        self.assertEqual({"main", "a7", "?"}, set(s.streams))


class TestEvalReportToFigures(unittest.TestCase):
    """DESIGN.md 6.4: the figures read the eval report JSON. Run run_eval (test_eval's STUB verifier with its toy
    deciding checks, on the synthetic pack) and render its report."""

    def test_recall_and_transfer_from_eval_report(self):
        import shutil
        import tempfile
        from test_eval import build_synthetic_pack, run_main, write_stub_repo
        from verifier import figures
        tmp = Path(tempfile.mkdtemp(prefix="test_integration_"))
        try:
            repo = write_stub_repo(tmp / "repo")
            build_synthetic_pack(tmp / "pack")
            code, out, _ = run_main(["--repo", str(repo), "--pack", str(tmp / "pack"), "--procs", "1", "--checks",
                                     "ref_result_present,toy_ts_monotone", "--report-dir", str(tmp / "r")])
            self.assertEqual(code, 0, out)
            rep = figures.load_report(out["report"])
            self.assertNotIn("ref_result_present", rep["recall"])          # reference checks never decide
            key = "swechat/claude_code|time_result_late|30"
            src = json.loads(Path(out["report"]).read_text(encoding="utf-8"))["cells"][key]["per_check"][
                "toy_ts_monotone"]["0"]
            got = rep["recall"]["toy_ts_monotone"]["time_result_late"]["30"]["swechat/claude_code"]
            self.assertEqual((got["k"], got["n"], got["label"]), (src["recall"]["k"], src["recall"]["n"],
                                                                 src["cell_label"]))
            produced = figures.write_figures(rep, tmp / "fig")
            self.assertEqual(set(produced), {"transfer_matrix.svg", "recall_per_attack.svg", "recall_per_attack.html"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestEntryPoints(unittest.TestCase):
    def test_python_m_verifier(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-m", "verifier", "checks", "--json"], capture_output=True, text=True,
                           encoding="utf-8", env=env, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr[-1000:])
        self.assertIn("ref_result_present", [c["name"] for c in json.loads(r.stdout)])


if __name__ == "__main__":
    unittest.main()
