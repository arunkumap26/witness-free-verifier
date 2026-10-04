"""Tests for the verifier core scaffold (DESIGN.md §2.4, §2.6, §3, §4; DA21: stdlib unittest, pytest can discover).

Run from the repo (worktree) root:
    python -m unittest tests.test_verifier_core -v        (or: python tests/test_verifier_core.py, or pytest tests)

Data: synthetic frames everywhere, plus two day-time tests that read split-A IR caches (analysis/cache/*_A.parquet)
when they exist and skip otherwise. Nothing here reads E or H.
"""
from __future__ import annotations

import glob
import io
import json
import pickle
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

import verifier  # noqa: E402
from verifier import cli, labels  # noqa: E402
from verifier import compose as comp  # noqa: E402
from verifier import ir as vir  # noqa: E402
from verifier import registry  # noqa: E402
from verifier import session as vs  # noqa: E402
from verifier.checks import base  # noqa: E402
from verifier.ir.turns import turns_to_events  # noqa: E402

CACHE = REPO / "analysis" / "cache"
OWNED = ["verifier/__init__.py", "verifier/ir/__init__.py", "verifier/ir/turns.py", "verifier/session.py",
         "verifier/checks/base.py", "verifier/checks/reference.py", "verifier/registry.py", "verifier/compose.py",
         "verifier/labels.py", "verifier/cli.py"]


# ------------------------------------------------------------------------------------------------------ fixtures
def ev(seq, kind, sid="s1", **kw):
    row = {c: None for c in vir.COLUMNS}
    row.update(corpus="t", session_id=sid, stratum="x", seq=seq, kind=kind, ts_kind="none")
    if kw.get("ts"):
        row["ts_kind"] = "event"
    row.update(kw)
    return row


def frame(rows):
    return vir.to_frame(rows)


def basic_rows(sid="s1"):
    """call c1 (+result), call c2 (no result), call c3 (+result), with ms stamps."""
    return [
        ev(0, "user", sid, text="go", ts="2026-01-01T00:00:00.000Z"),
        ev(1, "assistant", sid, text="ok", usage_in=10, usage_out=5, api_msg_id="m1", request_id="r1",
           ts="2026-01-01T00:00:01.000Z"),
        ev(2, "call", sid, tool="shell", tool_raw="Bash", call_id="c1", command="ls", args='{"command":"ls"}',
           request_id="r1", api_msg_id="m1", ts="2026-01-01T00:00:01.100Z"),
        ev(3, "result", sid, tool="shell", tool_raw="Bash", call_id="c1", text="a\nb", ts="2026-01-01T00:00:01.400Z"),
        ev(4, "call", sid, tool="read", tool_raw="Read", call_id="c2", args='{"file_path":"x"}',
           ts="2026-01-01T00:00:02.000Z"),
        ev(5, "call", sid, tool="shell", tool_raw="Bash", call_id="c3", command="pwd", ts="2026-01-01T00:00:03.000Z"),
        ev(6, "result", sid, tool="shell", tool_raw="Bash", call_id="c3", text="/x", ts="2026-01-01T00:00:03.250Z",
           extra='{"durationMs": 12, "nested": {"k": 1}}'),
    ]


def turns_fixture(sid="s1"):
    return [
        {"turn_id": "t1", "session_id": sid, "turn_number": 1, "role": "user", "turn_type": "user_prompt",
         "content": "hi", "timestamp": "2026-01-01T00:00:00.000Z", "source": "swarm"},
        {"turn_id": "t2", "session_id": sid, "turn_number": 2, "role": "assistant", "turn_type": "assistant_response",
         "content": "ok", "input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3, "model": "m",
         "timestamp": "2026-01-01T00:00:01.000Z"},
        {"turn_id": "t3", "session_id": sid, "turn_number": 3, "role": "tool_use", "turn_type": "tool_use",
         "tool_name": "Bash", "tool_call_id": "c1", "command": "ls", "tool_input_json": {"command": "ls"},
         "timestamp": "2026-01-01T00:00:02.000Z"},
        {"turn_id": "t4", "session_id": sid, "turn_number": 4, "role": "tool_result", "turn_type": "tool_result",
         "tool_call_id": "c1", "content": "a b", "timestamp": "2026-01-01T00:00:02.500Z"},
        {"turn_id": "t6", "session_id": sid, "turn_number": 6, "role": "metadata", "turn_type": "progress",
         "timestamp": "2026-01-01T00:00:03.500Z"},
        {"turn_id": "t5", "session_id": sid, "turn_number": 5, "role": "tool_use", "turn_type": "tool_use",
         "tool_name": "Read", "tool_call_id": None, "timestamp": "2026-01-01T00:00:03.000Z"},
        {"turn_id": "t7", "session_id": sid, "turn_number": 7, "role": "assistant", "turn_type": "assistant_thinking",
         "content": "hmm"},
        {"turn_id": "t8", "session_id": sid, "turn_number": 8, "role": "weird", "turn_type": "other"},
    ]


def build(rows, **kw):
    return vs.build_session(frame(rows), unit=kw.pop("unit", "t"), source={}, **kw)


class _DummyBase:
    version = "1.0.0"
    kind = "identity"
    strength = "strong"
    requires = frozenset({"join.call_id"})
    reads = frozenset({"ts"})
    targets = frozenset({"time_result_early"})
    unit_kind = "call"

    def applicable(self, s):
        return True

    def run(self, s):
        return []

    def explain(self, cv):
        return "dummy"


def make_check(name, **attrs):
    attrs.setdefault("calibration", None if attrs.get("kind") == "reference" else f"verifier/checks/calib/{name}.json")
    cls = type(name, (_DummyBase,), {"name": name, **attrs})
    cls.__module__ = f"verifier.checks.{name}"
    return cls


class RegistryTestCase(unittest.TestCase):
    """Registers throwaway checks and removes them afterwards."""

    def reg(self, cls):
        registry.register(cls)
        self.addCleanup(registry.REGISTRY.pop, cls.name, None)
        return cls


# ------------------------------------------------------------------------------------------------------------- IR
class TestIR(unittest.TestCase):
    def test_schema_pin(self):
        self.assertEqual(vir.IR_SCHEMA_SHA, vir.EXPECTED_IR_SCHEMA_SHA,
                         "analysis/lib/ir.py changed: bump EXPECTED_IR_SCHEMA_SHA deliberately (DA1)")

    def test_reexport_is_the_analysis_module(self):
        from analysis.lib import ir as air
        self.assertIs(vir.COLUMNS, air.COLUMNS)
        self.assertIs(vir.validate, air.validate)

    def test_import_isolation(self):
        code = ("import sys, json, verifier; verifier.verify_session(json.loads(sys.argv[1]), checks=['ref_result_present']);"
                "bad=[m for m in sys.modules if m.startswith('analysis.loaders') or m in ('analysis.lib.stats','analysis.lib.sample')];"
                "print(bad)")
        out = subprocess.run([sys.executable, "-c", code, json.dumps(turns_fixture())], cwd=REPO, capture_output=True,
                             text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "[]")


class TestTurns(unittest.TestCase):
    def test_mapping(self):
        df, tids, unmapped = turns_to_events(turns_fixture())
        self.assertEqual(list(df.columns), list(vir.COLUMNS))
        self.assertEqual(unmapped, 1)
        kinds = df["kind"].tolist()
        self.assertEqual(kinds, ["user", "assistant", "call", "result", "call", "meta", "meta", "meta"])
        self.assertEqual(tids[4], "t5")  # sorted by turn_number: t5 (5) before t6 (6)
        call2 = df.iloc[4]
        self.assertEqual(call2["call_id"], "turn:t5")
        self.assertEqual(call2["tool"], "read")
        self.assertEqual(df.iloc[3]["tool_raw"], "Bash")            # copied from the matching call
        self.assertEqual(df.iloc[2]["args"], '{"command":"ls"}')
        self.assertEqual(int(df.iloc[1]["usage_cache_read"]), 3)
        thinking = json.loads(df.iloc[6]["extra"])
        self.assertEqual(thinking, {"thinking_chars": 3, "turn_id": "t7", "turn_type": "assistant_thinking"})
        self.assertTrue(pd.isna(df.iloc[6]["text"]))
        self.assertEqual(json.loads(df.iloc[7]["extra"])["role"], "weird")
        self.assertEqual(df.iloc[0]["stratum"], "swarm")
        self.assertEqual(df.iloc[6]["ts_kind"], "none")
        self.assertTrue(df["request_id"].isna().all())

    def test_one_session_only(self):
        t = turns_fixture() + turns_fixture("s2")
        with self.assertRaises(ValueError):
            turns_to_events(t)
        with self.assertRaises(ValueError):
            turns_to_events([])


# ------------------------------------------------------------------------------------------------------- idclock
def _b58encode(x, width=22):
    s = ""
    while x:
        x, r = divmod(x, 58)
        s = vs._B58[r] + s
    return s.rjust(width, "1")


def _uuid7_value(ms, version=7, variant=0b10):
    return (ms << 80) | (version << 76) | (0xABC << 64) | (variant << 62) | 0x123456789


class TestIdclock(unittest.TestCase):
    def test_window_matches_prereg(self):
        from analysis.probes import prereg_e_common as pe
        self.assertEqual(vs._WIN, pe._WIN)
        self.assertEqual(vs._B58, pe._B58)

    def test_gate(self):
        ms = 1767225600123  # 2026-01-01T00:00:00.123Z
        good = "req_01" + _b58encode(_uuid7_value(ms))
        self.assertEqual(vs.id_family(good), "anthropic_req")
        self.assertEqual(vs.decode(good), ("anthropic_req", float(ms)))
        self.assertIsNone(vs.decode("req_01" + _b58encode(_uuid7_value(ms, version=4))))
        self.assertIsNone(vs.decode("req_01" + _b58encode(_uuid7_value(ms, variant=0b11))))
        old = 1600000000000  # 2020: outside the window
        self.assertIsNone(vs.decode("req_01" + _b58encode(_uuid7_value(old))))
        self.assertIsNone(vs.decode(None))
        self.assertEqual(vs.layout_report([good, "req_bogus", None]), {"n_shaped": 2, "n_decoded": 1})

    @unittest.skipUnless(list(CACHE.glob("*_A.parquet")), "split-A IR caches not present")
    def test_split_a_parity(self):
        """DESIGN §2.4 test_idclock_parity, on every distinct request_id / api_msg_id of split A:
        - anthropic_req: decode == prereg_e_common.decode_req_ms, and the DA20 gate rejects 0 ids it accepts;
        - every id: decode == load_tbench2.id_embedded_ms(id_family(v), v), EXCEPT anthropic_msg ids that fail the
          UUIDv7 bits (pre-2026-07-06 random msg ids whose ungated decode lands in the window by chance): the gate
          drops those by design."""
        import pyarrow.parquet as pq
        from analysis.loaders import load_tbench2 as lt
        from analysis.probes import prereg_e_common as pe
        n, gate_rejects_req, other_mismatch, msg_gated = 0, 0, 0, 0
        for p in sorted(glob.glob(str(CACHE / "*_A.parquet"))):
            self.assertNotIn("_H", Path(p).name)
            if "request_id" not in pq.read_schema(p).names:
                continue
            tb = pq.read_table(p, columns=["request_id", "api_msg_id"])
            ids = {v for c in ("request_id", "api_msg_id") for v in tb.column(c).to_pylist() if isinstance(v, str)}
            for v in ids:
                n += 1
                fam = vs.id_family(v)
                self.assertEqual(fam, lt.id_family(v))
                d = vs.decode(v)
                mine = d[1] if d else None
                if fam == "anthropic_req":
                    ref = pe.decode_req_ms(v)
                    gate_rejects_req += int(ref is not None and mine is None)
                    self.assertEqual(mine, ref, v)
                ref = lt.id_embedded_ms(lt.id_family(v), v)
                if mine != ref:
                    if fam == "anthropic_msg" and not vs._uuid7_bits_ok(vs._b58_value(v)) and mine is None:
                        msg_gated += 1
                    else:
                        other_mismatch += 1
        self.assertGreater(n, 0)
        self.assertEqual(gate_rejects_req, 0, "layout differs from what Track A measured: stop the build (§2.4)")
        self.assertEqual(other_mismatch, 0)


# ------------------------------------------------------------------------------------------------------- session
class TestSession(unittest.TestCase):
    def test_pairing_rule_and_call_keys(self):
        rows = [ev(0, "call", call_id="c1"), ev(1, "result", call_id="c1"), ev(2, "call", call_id="c1"),
                ev(3, "result", call_id="c1"), ev(4, "result", call_id="c1"), ev(5, "result", call_id="x"),
                ev(6, "result", call_id="c9"), ev(7, "call", call_id="c9"), ev(8, "result", call_id=None)]
        s = build(rows)
        self.assertEqual(s.call_keys, ("c1@0", "c1@2", "c9"))
        p = s.pairs.set_index("call_key")
        self.assertEqual(int(p.loc["c1@0", "result_seq"]), 1)
        self.assertEqual(int(p.loc["c1@0", "n_results"]), 1)
        self.assertEqual(int(p.loc["c1@2", "result_seq"]), 3)
        self.assertEqual(int(p.loc["c1@2", "n_results"]), 2)
        self.assertTrue(pd.isna(p.loc["c9", "result_seq"]))
        self.assertEqual(s.orphans, (5, 6, 8))
        self.assertNotIn("join.unique", s.capabilities)
        self.assertIn("join.call_id", s.capabilities)
        self.assertEqual(s.call_seq("c1@2"), 2)
        self.assertEqual(s.result_seq("c9"), None)
        self.assertEqual(s.call_id_of("c1@2"), "c1")

    def test_capabilities_and_clocks(self):
        s = build(basic_rows())
        for cap in ("ts.any", "ts.event", "ts.ms", "ts.pair_distinct", "join.call_id", "join.unique", "result.text",
                    "shell.command", "request_id", "api_msg_id", "usage.io", "usage.out"):
            self.assertIn(cap, s.capabilities)
        for cap in ("request_id.decodable", "subagent", "error.native", "sidecar.entire_tally", "usage.cache"):
            self.assertNotIn(cap, s.capabilities)
        self.assertTrue(s.has_capability("extra:durationMs"))
        self.assertTrue(s.has_capability("extra:nested.k"))
        self.assertFalse(s.has_capability("extra:nested.z"))
        self.assertEqual(s.clocks.resolution_ms, 1.0)
        self.assertEqual(s.clocks.ts_ms[0], 1767225600000.0)
        self.assertEqual(float(s.pairs.set_index("call_key").loc["c1", "latency_ms"]), 300.0)
        self.assertEqual(s.extra(6)["durationMs"], 12)
        self.assertEqual(s.extra(0), {})
        whole = [dict(r, ts=r["ts"].replace(".000Z", "Z").replace(".100Z", "Z").replace(".400Z", "Z")
                      .replace(".250Z", "Z")) for r in basic_rows()]
        self.assertEqual(build(whole).clocks.resolution_ms, 1000.0)
        self.assertNotIn("ts.ms", build(whole).capabilities)

    def test_responses_usage_dedupe(self):
        rows = basic_rows()
        rows.insert(2, ev(2, "assistant", text="more", usage_in=10, usage_out=9, api_msg_id="m1", request_id="r1",
                          ts="2026-01-01T00:00:01.050Z"))
        for i, r in enumerate(rows):
            r["seq"] = i
        s = build(rows)
        r = s.responses.set_index("resp_key").loc["r1"]
        self.assertEqual(int(r["usage_out"]), 9)
        self.assertEqual(int(r["usage_in"]), 10)
        self.assertEqual(r["call_keys"], ("c1",))
        self.assertEqual(r["stream"], "main")
        self.assertTrue(pd.isna(r["provider_ms"]))

    def test_build_errors(self):
        with self.assertRaises(ValueError):
            vs.build_session(frame(basic_rows()).iloc[0:0], unit="t", source={})
        with self.assertRaises(ValueError):
            vs.build_session(frame(basic_rows("a") + basic_rows("b")), unit="t", source={})
        with self.assertRaises(ValueError):
            vs.build_session(frame(basic_rows()).drop(columns=["extra"]), unit="t", source={})
        bad = basic_rows()
        bad[3]["seq"] = 2
        with self.assertRaises(ValueError):
            vs.build_session(frame(bad), unit="t", source={})

    def test_sidecar(self):
        with self.assertRaises(ValueError):
            vs.validate_sidecar({"nope": 1})
        with self.assertRaises(ValueError):
            vs.validate_sidecar({"cc_numlines": {"c1": "3"}})
        with self.assertRaises(ValueError):
            vs.validate_sidecar({"entire_tally": {"api": 1}})
        sc = vs.validate_sidecar({"cc_numlines": {"c1": 3}, "entire_tally": {"api": 1, "in": 2, "cc": 3, "cr": 4, "out": 5},
                                  "copied_request_ids": {}})
        with self.assertRaises(TypeError):
            sc["cc_numlines"]["c1"] = 4
        self.assertEqual(pickle.loads(pickle.dumps(sc)), sc)
        s = build(basic_rows(), sidecar=sc)
        for cap in ("sidecar.cc_numlines", "sidecar.entire_tally", "sidecar.copied_request_ids"):
            self.assertIn(cap, s.capabilities)
        s2 = build(basic_rows(), sidecar={"cc_numlines": {"other": 3}, "entire_tally": None})
        self.assertNotIn("sidecar.cc_numlines", s2.capabilities)
        self.assertNotIn("sidecar.entire_tally", s2.capabilities)

    def test_ref(self):
        s = build(basic_rows())
        r = s.ref(2, "ts", "subject", "x" * 500)
        self.assertEqual(len(r.value), base.MAX_REF_VALUE_CHARS)
        with self.assertRaises(ValueError):
            s.ref(99)
        with self.assertRaises(ValueError):
            s.ref(1, role="judge")


# ------------------------------------------------------------------------------------------- base + registry
class TestBaseAndRegistry(RegistryTestCase):
    def test_vocabularies_match_prereg(self):
        pre = json.loads((REPO / "analysis" / "prereg_e.json").read_text(encoding="utf-8"))["n7_attack_battery"]
        self.assertEqual(base.READ_FIELDS, frozenset(f for v in pre["detector_fields"].values() for f in v))
        self.assertEqual(base.ATTACK_NAMES_DECLARED, frozenset(pre["attacks"]))
        self.assertEqual(len(base.ATTACK_NAMES_DECLARED), 21)

    def test_reference_registered_not_enabled(self):
        registry.load_checks()
        self.assertIn("ref_result_present", registry.REGISTRY)
        self.assertEqual(registry.ENABLED_CHECKS, ())  # scaffold state: nothing enabled before gate G0 (§7.3)
        self.assertEqual(registry.resolve_names("all"), tuple(sorted(registry.REGISTRY)))
        self.assertEqual(registry.resolve_names(None), ())
        with self.assertRaises(KeyError):
            registry.resolve_names("nope")
        cls = registry.REGISTRY["ref_result_present"]
        self.assertEqual(base.check_version(cls), "1.0.0+nocalib")
        self.assertTrue(registry.check_module_file("ref_result_present").endswith("reference.py"))

    def test_register_rules(self):
        for bad in (make_check("bad_caps", requires=frozenset({"swechat"})),
                    make_check("bad_reads", reads=frozenset({"narration"})),
                    make_check("bad_targets", targets=frozenset({"new_attack"})),
                    make_check("bad_calib", calibration=None),
                    make_check("bad_kind", kind="vote"),
                    make_check("bad_version", version="1"),
                    make_check("BadName")):
            with self.assertRaises(base.ContractError, msg=bad.name):
                registry.register(bad)
        wrong_mod = make_check("wrong_mod")
        wrong_mod.__module__ = "verifier.checks.elsewhere"
        with self.assertRaises(base.ContractError):
            registry.register(wrong_mod)
        ok = self.reg(make_check("dummy_ok", requires=frozenset({"join.call_id", "extra:durationMs"})))
        with self.assertRaises(base.ContractError):
            registry.register(ok)  # duplicate

    def test_constructor_invariants(self):
        s = build(basic_rows())
        chk = make_check("inv_identity", strength="format")
        stat = make_check("inv_stat", kind="statistical")
        subj = [s.ref(2, "ts", "subject")]
        with self.assertRaises(base.ContractError):
            base.supported(s, "c1", chk, "violation:x", subj, confidence=None)
        with self.assertRaises(base.ContractError):
            base.contradicted(s, "c1", chk, "violation:x", [], confidence=None)
        with self.assertRaises(base.ContractError):
            base.contradicted(s, "c1", chk, "violation:x", [s.ref(2)], confidence=None)  # no subject
        with self.assertRaises(base.ContractError):
            base.contradicted(s, "c1", chk, "violation:x", subj, confidence=1.5)
        with self.assertRaises(base.ContractError):
            base.contradicted(s, "c1", chk, "violation:x", subj, confidence=None, strength="strong")  # raise (DA18)
        with self.assertRaises(base.ContractError):
            base.supported(s, "c1", stat, "ok:x", subj, confidence=None)
        with self.assertRaises(base.ContractError):
            base.unconstrained(s, "c1", chk, "ok:x")
        with self.assertRaises(base.ContractError):
            base.unconstrained(s, "nokey", chk, "missing:x")
        with self.assertRaises(base.ContractError):
            base.contradicted(s, "c1", chk, "violation:x", subj, confidence=None, detail={"x": float("nan")})
        many = [s.ref(i, role="subject") for i in range(7)]
        with self.assertRaises(base.ContractError):
            base.contradicted(s, "c1", chk, "violation:x", many, confidence=None)
        cv = base.contradicted(s, "c1", chk, "violation:x", many, confidence=0.5, localized=False, unit_kind="session",
                               unit_id="s1")
        self.assertEqual(cv.strength, "format")
        self.assertEqual(cv.check_version, "1.0.0+nocalib")
        self.assertEqual(base.CallVerdict.from_dict(cv.to_dict()), cv)
        self.assertEqual(base.reason_status("abstain:below_threshold"), "unconstrained")
        self.assertIsNone(base.reason_status("maybe:x"))

    def test_run_checks_paths(self):
        s = build(basic_rows())

        class Boom(_DummyBase):
            def run(self, s):
                raise KeyError("boom")

        class Partial(_DummyBase):
            def run(self, s):
                return [base.supported(s, "c1", self, "ok:fine", [s.ref(2, role="subject")], confidence=0.9)]

        class Dup(_DummyBase):
            def run(self, s):
                cv = base.supported(s, "c1", self, "ok:fine", [s.ref(2, role="subject")], confidence=None)
                return [cv, cv]

        class NotApp(_DummyBase):
            def applicable(self, s):
                return False

        checks = {}
        for name, b, extra in (("t_boom", Boom, {}), ("t_partial", Partial, {}), ("t_dup", Dup, {}),
                               ("t_notapp", NotApp, {}),
                               ("t_missing", _DummyBase, {"requires": frozenset({"subagent", "request_id.decodable"})})):
            cls = type(name, (b,), {"name": name, "calibration": f"verifier/checks/calib/{name}.json", **extra})
            cls.__module__ = f"verifier.checks.{name}"
            checks[name] = self.reg(cls)
        stats = registry.RunStats()
        out = registry.run_checks(s, list(checks), stats=stats)
        self.assertEqual(set(out["t_boom"]), set(s.call_keys))
        self.assertEqual(out["t_boom"]["c1"].reason, "error:KeyError")
        self.assertEqual(out["t_dup"]["c1"].reason, "error:ContractError")
        self.assertEqual(out["t_partial"]["c1"].verdict, "supported")
        self.assertEqual(out["t_partial"]["c2"].reason, "abstain:not_decided")
        self.assertEqual(out["t_notapp"]["c3"].reason, "abstain:not_applicable")
        self.assertEqual(out["t_missing"]["c1"].reason, "missing:request_id.decodable")
        self.assertEqual(out["t_missing"]["c1"].detail, {"missing": ["request_id.decodable", "subagent"]})
        self.assertEqual(stats.errors, {"t_boom": 1, "t_dup": 1})
        self.assertEqual(stats.status["t_missing"], "missing")
        self.assertEqual([r["name"] for r in stats.checks_run()], sorted(checks))
        with self.assertRaises(KeyError):
            registry.run_checks(s, ["t_boom"], strict=True)
        empty = build([ev(0, "user", text="x")])
        self.assertEqual(registry.run_checks(empty, ["t_partial"]), {"t_partial": {}})

    def test_calib_for_lookup(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cal.json"
            p.write_text(json.dumps({"units": {
                "aiv_cu/gemini": {"fpr_hi": 0.01},
                "aiv_cu": {"fpr_hi": 0.02, "tau": 1.0},
                "cc_local": {"fpr_hi": 0.03, "tau": 0.5, "floor": 7, "proxy_ok": ["tau"]},
                "pub_cc_hf": {"fpr_hi": 0.04}}}), encoding="utf-8")
            chk = make_check("cal_test", calibration=str(p))
            self.assertEqual(base.calib_for(chk, "aiv_cu", "gemini")["fpr_hi"], 0.01)
            self.assertEqual(base.calib_for(chk, "aiv_cu", "other")["fpr_hi"], 0.02)
            e = base.calib_for(chk, "pub_cc_hf")
            self.assertEqual((e["fpr_hi"], e["tau"], e["_borrowed"]), (0.04, 0.5, ["tau"]))
            self.assertNotIn("floor", e)
            e2 = base.calib_for(chk, "pub_trace_commons")
            self.assertEqual((e2["tau"], e2["_unit_key"]), (0.5, None))
            self.assertIsNone(base.calib_for(chk, "tbench2"))
            self.assertIsNone(base.calib_for(chk, None))
            self.assertTrue(base.check_version(chk).startswith("1.0.0+") and "nocalib" not in base.check_version(chk))


# ------------------------------------------------------------------------------------------------------- compose
class TestCompose(RegistryTestCase):
    def setUp(self):
        self.s = build(basic_rows())
        self.a = make_check("cmp_a", strength="strong")
        self.b = make_check("cmp_b", strength="format")
        self.st = make_check("cmp_s", kind="statistical", strength="format")
        self.ref = make_check("cmp_ref", kind="reference", strength="format")

    def test_lattice_and_disagreement(self):
        s, a, b, st, ref = self.s, self.a, self.b, self.st, self.ref
        by = {
            "cmp_a": {"c1": base.contradicted(s, "c1", a, "violation:x", [s.ref(2, role="subject"), s.ref(3, role="conflict")],
                                              confidence=0.99),
                      "c2": base.unconstrained(s, "c2", a, "missing:result"),
                      "c3": base.unconstrained(s, "c3", a, "missing:request_id")},
            "cmp_b": {"c1": base.supported(s, "c1", b, "ok:y", [s.ref(2, role="subject"), s.ref(1)], confidence=0.8),
                      "c2": base.supported(s, "c2", b, "ok:y", [s.ref(4, role="subject")], confidence=None),
                      "c3": base.unconstrained(s, "c3", b, "missing:request_id")},
            "cmp_s": {"c1": base.contradicted(s, "c1", st, "violation:z", [s.ref(3, role="subject")], confidence=0.7),
                      "c2": base.unconstrained(s, "c2", st, "abstain:uncalibrated_unit"),
                      "c3": base.unconstrained(s, "c3", st, "abstain:below_threshold")},
            "cmp_ref": {k: base.supported(s, k, ref, "ok:result_joined", [s.ref(s.call_seq(k), role="subject")],
                                          confidence=None) for k in s.call_keys},
        }
        kinds = {"cmp_a": "identity", "cmp_b": "identity", "cmp_s": "statistical", "cmp_ref": "reference"}
        v1, v2, v3 = comp.compose(s, by, kinds)
        self.assertEqual((v1.verdict, v1.rule, v1.strength, v1.disagreement), ("contradicted", "cmp_a", "strong", True))
        self.assertEqual(v1.core, (2, 3))
        self.assertEqual(v1.blame_seq, 3)          # seq 3 is cited twice among subject/conflict refs
        self.assertEqual([c.check for c in v1.checks], ["cmp_a", "cmp_b", "cmp_ref", "cmp_s"])
        self.assertEqual(v1.to_scope_dict()["tiers"], ["cmp_a", "cmp_b", "cmp_ref", "cmp_s"])
        self.assertEqual(v1.to_scope_dict({2: "t3", 3: "t4"})["core"], ["t3", "t4"])
        self.assertEqual(v1.to_scope_dict()["core"], ["seq:2", "seq:3"])
        self.assertEqual((v2.verdict, v2.rule, v2.core, v2.blame_seq), ("supported", "cmp_b", (4,), None))
        self.assertEqual((v3.verdict, v3.reason), ("unconstrained", "missing:request_id"))
        self.assertEqual(v3.detail, {"unconstrained_reasons": {"abstain:below_threshold": 1, "missing:request_id": 2}})
        self.assertEqual(comp.summarize([v1, v2, v3]),
                         {"supported": 1, "contradicted_localized": 1, "contradicted_unit": 0, "unconstrained": 1,
                          "screened": 1})
        self.assertRegex(v1.version, r"^verifier/0\.1\.0 ir/[0-9a-f]{12} checks/[0-9a-f]{12}$")
        self.assertEqual(base.Verdict.from_dict(json.loads(json.dumps(v1.to_dict()))), v1)
        shown = comp.apply_min_confidence([v1], 0.995)
        self.assertTrue(shown[0][1])

    def test_reference_only_and_nothing(self):
        s, ref = self.s, self.ref
        by = {"cmp_ref": {k: base.unconstrained(s, k, ref, "missing:result") for k in s.call_keys}}
        out = comp.compose(s, by, {"cmp_ref": "reference"})
        self.assertTrue(all(v.reason == "abstain:reference_only" and v.verdict == "unconstrained" for v in out))
        out = comp.compose(s, {}, {})
        self.assertTrue(all(v.reason == "abstain:no_enabled_checks" for v in out))
        self.assertEqual([v.call_key for v in out], list(s.call_keys))

    def test_unit_level_contradiction(self):
        s, a = self.s, self.a
        by = {"cmp_a": {k: base.contradicted(s, k, a, "violation:x", [s.ref(s.call_seq(k), role="subject")],
                                             confidence=None, localized=False, unit_kind="session", unit_id="s1")
                        for k in s.call_keys}}
        out = comp.compose(s, by, {"cmp_a": "identity"})
        self.assertTrue(all(v.verdict == "contradicted" and not v.localized for v in out))
        self.assertEqual(comp.summarize(out)["contradicted_unit"], 3)


# ------------------------------------------------------------------------------------------------- end to end
class TestVerifySession(RegistryTestCase):
    def test_turns_end_to_end(self):
        out = verifier.verify_session(turns_fixture(), checks=["ref_result_present"])
        self.assertEqual([v.call_id for v in out], ["c1", "turn:t5"])
        self.assertTrue(all(v.verdict == "unconstrained" and v.reason == "abstain:reference_only" for v in out))
        self.assertEqual(out[0].checks[0].reason, "ok:result_joined")
        self.assertEqual(out[1].checks[0].reason, "missing:result")
        self.assertEqual(out[0].to_scope_dict()["tiers"], ["ref_result_present"])
        default = verifier.verify_session(turns_fixture())
        self.assertTrue(all(v.reason == "abstain:no_enabled_checks" and v.checks == () for v in default))

    def test_frame_input_and_errors(self):
        out = verifier.verify_session(frame(basic_rows()), checks="all")
        self.assertEqual([v.call_key for v in out], ["c1", "c2", "c3"])
        self.assertEqual([v.result_seq for v in out], [3, None, 6])
        self.assertEqual(verifier.verify_session(frame([ev(0, "user", text="x")])), [])
        with self.assertRaises(ValueError):
            verifier.verify_session(frame(basic_rows("a") + basic_rows("b")))
        with self.assertRaises(TypeError):
            verifier.verify_session("not a session")

    def test_determinism_and_pickle(self):
        a = [v.to_dict() for v in verifier.verify_session(frame(basic_rows()), checks="all")]
        b = [v.to_dict() for v in verifier.verify_session(frame(list(reversed(basic_rows()))), checks="all")]
        self.assertEqual(a, b)
        vv = verifier.verify_session(frame(basic_rows()), checks="all")
        self.assertEqual(pickle.loads(pickle.dumps(vv)), vv)

    def test_verify_sessions(self):
        rows = basic_rows("b") + basic_rows("a")
        got = list(verifier.verify_sessions(frame(rows), unit_of=lambda sid: "u", calibration_unit_of=lambda sid: None,
                                            checks=["ref_result_present"]))
        self.assertEqual([s.session_id for s, _ in got], ["a", "b"])
        self.assertTrue(all(len(v) == 3 for _, v in got))

    def test_strict_and_contradiction(self):
        class Contra(_DummyBase):
            def run(self, s):
                return [base.contradicted(s, k, self, "violation:test", [s.ref(s.call_seq(k), "ts", "subject")],
                                          confidence=0.9) for k in s.call_keys]

        class Boom(_DummyBase):
            def run(self, s):
                raise RuntimeError("x")
        for name, b in (("e2e_contra", Contra), ("e2e_boom", Boom)):
            cls = type(name, (b,), {"name": name, "calibration": f"verifier/checks/calib/{name}.json"})
            cls.__module__ = f"verifier.checks.{name}"
            self.reg(cls)
        out = verifier.verify_session(frame(basic_rows()), checks=["e2e_contra", "ref_result_present"])
        self.assertTrue(all(v.verdict == "contradicted" and v.rule == "e2e_contra" for v in out))
        out = verifier.verify_session(frame(basic_rows()), checks=["e2e_boom"])
        self.assertTrue(all(v.reason == "error:RuntimeError" for v in out))
        with self.assertRaises(RuntimeError):
            verifier.verify_session(frame(basic_rows()), checks=["e2e_boom"], strict=True)


# ---------------------------------------------------------------------------------------------------------- labels
class TestLabels(unittest.TestCase):
    def setUp(self):
        self.s = build(basic_rows())
        rows2 = [ev(0, "call", "s2", call_id="d"), ev(1, "result", "s2", call_id="d"), ev(2, "call", "s2", call_id="d")]
        self.s2 = build(rows2)
        v = verifier.verify_session(self.s.events, checks="all") + verifier.verify_session(self.s2.events, checks="all")
        self.shas = {"s1": labels.session_ir_sha(self.s.events), "s2": labels.session_ir_sha(self.s2.events)}
        self.vf = labels.verdicts_frame(v, self.shas)

    def test_absent_and_empty(self):
        for p in (None, "does/not/exist.jsonl"):
            lab = labels.read_labels(p)
            self.assertEqual(len(lab), 0)
            j = labels.join_labels(self.vf, lab)
            self.assertEqual(set(j["join_status"]), {"unknown"})
            self.assertEqual(len(j), len(self.vf))
            st = labels.join_stats(j)
            self.assertEqual((st["n_labels"], st["ok_share"], st["join_ok"]), (0, None, None))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "labels.jsonl").write_text("\n", encoding="utf-8")
            self.assertEqual(len(labels.read_labels(d)), 0)

    def test_join_rules(self):
        base_l = {"set": "x", "corpus": "t", "provenance": "test", "label_version": "1", "label": "pos", "class": "c"}
        recs = [dict(base_l, session_id="s1", call_id="c1"),                                  # ok
                dict(base_l, session_id="s2", call_id="d"),                                   # ambiguous (two calls)
                dict(base_l, session_id="s1", call_id=None, seq=4, ir_sha=self.shas["s1"]),   # ok via seq
                dict(base_l, session_id="s1", call_id=None, seq=5, ir_sha="stale"),           # seq_mismatch
                dict(base_l, session_id="zz", call_id="c1"),                                  # orphan_label
                dict(base_l, session_id="s1", call_id="nope")]                                # no_match
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "labels.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
            lab = labels.read_labels(p)
        j = labels.join_labels(self.vf, lab)
        self.assertEqual(j["join_status"].tolist()[:6], ["ok", "ambiguous", "ok", "seq_mismatch", "orphan_label",
                                                          "no_match"])
        self.assertEqual(j.iloc[2]["v_call_key"], "c2")
        unk = j[j.join_status == "unknown"]
        self.assertEqual(sorted(unk["v_call_key"].tolist()), ["c3", "d@0", "d@2"])
        self.assertTrue((unk["label"] == "unknown").all())
        st = labels.join_stats(j)
        self.assertEqual(st["counts"]["ok"], 2)
        self.assertAlmostEqual(st["ok_share"], 2 / 6)
        self.assertFalse(st["join_ok"])

    def test_malformed_and_sha(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "labels.jsonl"
            p.write_text('{"set":"x"}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                labels.read_labels(p)
        lc = labels.LabeledCall(set="x", corpus="t", session_id="s1", call_id="c1", seq=None, label="neg", cls=None,
                                provenance="p", label_version="1", tampered_seqs=(3,))
        self.assertEqual(labels.LabeledCall.from_json(lc.to_json()), lc)
        self.assertEqual(labels.session_ir_sha(self.s.events), labels.session_ir_sha(self.s.events.iloc[::-1]))
        changed = frame(basic_rows())
        changed.loc[3, "text"] = "tampered"
        self.assertNotEqual(labels.session_ir_sha(changed), self.shas["s1"])


# ------------------------------------------------------------------------------------------------------------- CLI
def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCLI(RegistryTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.turns = self.d / "sess.jsonl"
        self.turns.write_text("\n".join(json.dumps(t) for t in turns_fixture()), encoding="utf-8")
        self.ir = self.d / "two.parquet"
        frame(basic_rows("a") + basic_rows("b")).to_parquet(self.ir, index=False)

    def test_verify_json_html_render(self):
        out_j, out_h = self.d / "v.jsonl", self.d / "v.html"
        code, out, err = run_cli([str(self.turns), "--checks", "all", "--json", str(out_j), "--html", str(out_h),
                                  "--no-color", "--show", "all", "--explain", "c1"])
        self.assertEqual(code, 0, err)
        self.assertIn("ref_result_present", out)
        self.assertIn("summary: 2 calls", out)
        lines = out_j.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["call_id"], "c1")
        sj = json.loads((self.d / "v.session.json").read_text(encoding="utf-8"))
        self.assertEqual((sj["n_calls"], sj["counts"]["unconstrained"]), (2, 2))
        self.assertEqual(sj["checks_run"][0]["status"], "ran")
        self.assertTrue(out_h.read_text(encoding="utf-8").startswith("<!doctype html>"))
        out_r = self.d / "r.html"
        code, out, err = run_cli(["render", str(out_j), "--source", str(self.turns), "--html", str(out_r)])
        self.assertEqual(code, 0, err)
        self.assertIn("c1", out_r.read_text(encoding="utf-8"))
        code, out, err = run_cli(["render", str(out_j), "--html", str(self.d / "r2.html")])
        self.assertEqual(code, 0, err)

    def test_ir_input_and_session_filter(self):
        code, out, err = run_cli(["verify", str(self.ir), "--checks", "ref_result_present", "--no-color"])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("summary: 3 calls"), 2)
        code, out, err = run_cli(["verify", str(self.ir), "--session", "b", "--no-color"])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("summary:"), 1)
        self.assertIn("checks: none enabled", out)

    def test_exit_codes(self):
        class Contra(_DummyBase):
            def run(self, s):
                return [base.contradicted(s, k, self, "violation:test", [s.ref(s.call_seq(k), "ts", "subject")],
                                          confidence=0.9) for k in s.call_keys]

        class Boom(_DummyBase):
            def run(self, s):
                raise RuntimeError("x")
        for name, b in (("cli_contra", Contra), ("cli_boom", Boom)):
            cls = type(name, (b,), {"name": name, "calibration": f"verifier/checks/calib/{name}.json"})
            cls.__module__ = f"verifier.checks.{name}"
            self.reg(cls)
        self.assertEqual(run_cli([str(self.turns), "--checks", "cli_contra", "--no-color"])[0], 1)
        code, _, err = run_cli([str(self.turns), "--checks", "cli_boom", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("became error: verdicts", err)
        self.assertEqual(run_cli([str(self.turns), "--checks", "cli_boom", "--strict"])[0], 3)
        self.assertEqual(run_cli([str(self.turns), "--checks", "nope"])[0], 2)
        self.assertEqual(run_cli([str(self.d / "missing.jsonl")])[0], 2)
        held = self.d / ("sess" + "_H" + ".jsonl")
        held.write_text(self.turns.read_text(encoding="utf-8"), encoding="utf-8")
        code, _, err = run_cli([str(held)])
        self.assertEqual(code, 2)
        self.assertIn("held-out", err)
        for name in ("x_heldout.jsonl", "x_Held-Out.jsonl", "x" + "_H"):
            with self.assertRaises(PermissionError):
                verifier.refuse_heldout_path(name)
        verifier.refuse_heldout_path("my_HELPER.jsonl")
        junk = self.d / "junk.parquet"
        junk.write_bytes(b"not a parquet file")
        self.assertEqual(run_cli([str(junk)])[0], 2)

    def test_builtin_fallback_without_loaders(self):
        """DA1 fallback: with verifier.loaders unavailable, IR parquet and SCOPE turns still load."""
        from unittest import mock
        with mock.patch.dict(sys.modules, {"verifier.loaders": None, "verifier.loaders.files": None}):
            got = verifier.load_sessions(self.ir, session_id="b")
            self.assertEqual([(s.session_id, s.unit, b) for s, b in got], [("b", "t", False)])
            got = verifier.load_sessions(self.turns)
            self.assertEqual([(s.session_id, s.unit, s.source["format"]) for s, _ in got], [("s1", "turns", "turns")])
            code, out, err = run_cli([str(self.turns), "--checks", "all", "--no-color"])
            self.assertEqual(code, 0, err)
            junk = self.d / "x.jsonl"
            junk.write_text('{"type": "something else"}' + chr(10), encoding="utf-8")
            with self.assertRaises(ValueError):
                verifier.load_sessions(junk)

    def test_checks_and_inspect(self):
        code, out, _ = run_cli(["checks", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("ref_result_present", [r["name"] for r in json.loads(out)])
        code, out, _ = run_cli(["inspect", str(self.turns), "--json"])
        self.assertEqual(code, 0)
        info = json.loads(out)
        self.assertEqual(info["checks"]["ref_result_present"], "applicable")
        self.assertEqual(info["n_calls"], 2)

    def test_private_corpus_never_rendered(self):
        rows = basic_rows()
        for r in rows:
            r["corpus"] = "cc_local"
        p = self.d / "priv.parquet"
        frame(rows).to_parquet(p, index=False)
        code, out, err = run_cli([str(p), "--checks", "all", "--show", "all", "--html", str(self.d / "p.html")])
        self.assertEqual(code, 2)
        self.assertIn("never rendered", err)
        self.assertIn("[private corpus]", out)
        self.assertNotIn('{"command":"ls"}', out)


# ------------------------------------------------------------------------------------------------- held-out rule
class TestNoHeldoutAccess(unittest.TestCase):
    def test_owned_files_name_no_heldout_paths(self):
        """DESIGN §5.2 rule 1, for the files this scaffold owns."""
        for rel in OWNED:
            text = (REPO / rel).read_text(encoding="utf-8")
            for pat in ("_EH.json", "HELDOUT", "_H.parquet", "H_pack"):
                self.assertNotIn(pat, text, f"{rel} mentions {pat}")


# -------------------------------------------------------------------------------------------- split-A smoke (day)
@unittest.skipUnless((CACHE / "swechat_A.parquet").exists(), "split-A swechat cache not present")
class TestSplitASmoke(unittest.TestCase):
    def test_reference_check_on_real_sessions(self):
        import pyarrow.parquet as pq
        p = CACHE / "swechat_A.parquet"
        sids = sorted(set(pq.ParquetFile(p).read_row_group(0, columns=["session_id"]).column(0).to_pylist()))[:8]
        df = pd.read_parquet(p, filters=[("session_id", "in", sids)])
        for g in vs.split_sessions(df):
            s = vs.build_session(g, unit="swechat", source={"split": "A"})
            v1, st = verifier.run_session(s, "all", strict=True)
            v2, _ = verifier.run_session(vs.build_session(g.iloc[::-1], unit="swechat", source={"split": "A"}), "all")
            self.assertEqual([v.to_dict() for v in v1], [v.to_dict() for v in v2])
            self.assertEqual(len(v1), len(s.call_keys))
            n_sup = sum(1 for v in v1 if v.checks[0].verdict == "supported")
            self.assertEqual(n_sup, int(s.pairs["result_seq"].notna().sum()))
            self.assertFalse(st.errors)


if __name__ == "__main__":
    unittest.main()
