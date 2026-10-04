"""Tests for verifier/loaders (DESIGN.md §2.5, §2.7, §6.1). stdlib unittest (DA21):

    python -m unittest tests.test_loaders            (from the repo root)
    VERIFIER_SLOW_TESTS=1 python -m unittest tests.test_loaders    (adds the raw-transcript sidecar parity, ~10 s)

Three groups:
  * synthetic: sniffing, file loading, errors, sidecar readers, units; no data needed.
  * cache / raw data: need analysis/cache (the analysis worktree) and C:/Swarms/data (SWARMS_DATA); skipped, not
    failed, when absent. They read splits A, B and E only.
  * parity: the loaders reproduce Track A's own counts (numbers cite committed analysis/out files).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from verifier.ir import COLUMNS, to_frame, validate  # noqa: E402
from verifier.loaders import corpora as C  # noqa: E402
from verifier.loaders import detect as D  # noqa: E402
from verifier.loaders import files as F  # noqa: E402
from verifier.loaders import sidecar as SC  # noqa: E402
from verifier.loaders import units as U  # noqa: E402

CACHE = ROOT / "analysis" / "cache"
DATA = Path(os.environ.get("SWARMS_DATA", "C:/Swarms/data"))
TRANS = DATA / "swe-chat-pinned" / "transcripts"
SLOW = os.environ.get("VERIFIER_SLOW_TESTS") == "1"


def have_cache(corpus: str, split: str) -> bool:
    return (CACHE / f"{corpus}_{split}.parquet").exists()


def _w(d: Path, name: str, lines) -> Path:
    p = d / name
    if isinstance(lines, str):
        p.write_text(lines, encoding="utf-8")
    else:
        p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return p


CC_LINES = [
    {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": "s", "timestamp": "2026-01-01T00:00:00.000Z",
     "message": {"role": "user", "content": "read x.py"}},
    {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "sessionId": "s", "timestamp": "2026-01-01T00:00:01.000Z",
     "requestId": "req_011CSHt1Ww6fW8JNP9Mm2XUc",
     "message": {"id": "msg_01AAAAAAAAAAAAAAAAAAAAAA", "model": "claude-test", "role": "assistant",
                 "content": [{"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "/x.py"}}],
                 "usage": {"input_tokens": 10, "output_tokens": 5}}},
    {"type": "user", "uuid": "u2", "parentUuid": "a1", "sessionId": "s", "timestamp": "2026-01-01T00:00:01.500Z",
     "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                              "content": "     1\tprint(1)\n     2\tprint(2)\n"}]},
     "toolUseResult": {"type": "text", "file": {"filePath": "/x.py", "content": "print(1)\nprint(2)\n", "numLines": 2,
                                                "startLine": 1, "totalLines": 2}}},
]

CODEX_LINES = [
    {"timestamp": "2026-01-01T00:00:00.000Z", "type": "session_meta",
     "payload": {"id": "0199-test", "timestamp": "2026-01-01T00:00:00.000Z", "cwd": "/w", "originator": "codex_cli_rs",
                 "cli_version": "0.1.0"}},
    {"timestamp": "2026-01-01T00:00:00.100Z", "type": "turn_context", "payload": {"model": "gpt-test", "cwd": "/w"}},
    {"timestamp": "2026-01-01T00:00:00.200Z", "type": "response_item",
     "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "list files"}]}},
    {"timestamp": "2026-01-01T00:00:00.200Z", "type": "event_msg",
     "payload": {"type": "user_message", "message": "list files"}},
    {"timestamp": "2026-01-01T00:00:01.000Z", "type": "response_item",
     "payload": {"type": "function_call", "name": "shell", "arguments": json.dumps({"command": ["bash", "-lc", "ls"]}),
                 "call_id": "call_1"}},
    {"timestamp": "2026-01-01T00:00:01.400Z", "type": "response_item",
     "payload": {"type": "function_call_output", "call_id": "call_1", "output": "a\nb\n"}},
    {"timestamp": "2026-01-01T00:00:01.500Z", "type": "event_msg",
     "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 10, "output_tokens": 3},
                                                 "last_token_usage": {"input_tokens": 10, "cached_input_tokens": 0,
                                                                      "output_tokens": 3}}}},
]

TURNS = [
    {"turn_id": "t1", "session_id": "S1", "turn_number": 1, "role": "user", "turn_type": "user_prompt",
     "content": "hi", "timestamp": "2026-01-01T00:00:00Z"},
    {"turn_id": "t2", "session_id": "S1", "turn_number": 2, "role": "tool_use", "turn_type": "tool_use",
     "tool_name": "Bash", "tool_call_id": "c1", "command": "ls", "tool_input_json": "{\"command\": \"ls\"}",
     "timestamp": "2026-01-01T00:00:01Z"},
    {"turn_id": "t3", "session_id": "S1", "turn_number": 3, "role": "tool_result", "turn_type": "tool_result",
     "tool_call_id": "c1", "content": "a", "timestamp": "2026-01-01T00:00:02Z"},
    {"turn_id": "t4", "session_id": "S2", "turn_number": 1, "role": "user", "turn_type": "user_prompt",
     "content": "other session"},
]

ATIF = {"schema_version": "ATIF-v1.2", "session_id": "x", "agent": {"name": "test-agent", "version": "0"},
        "steps": [{"step_id": 1, "source": "user", "message": "do it", "timestamp": "2026-01-01T00:00:00.000Z"},
                  {"step_id": 2, "source": "agent", "message": "ok", "timestamp": "2026-01-01T00:00:01.000Z",
                   "tool_calls": [{"tool_call_id": "c1", "function_name": "bash", "arguments": {"command": "ls"}}],
                   "observation": {"results": [{"source_call_id": "c1", "content": "a b"}]}}]}


def _ir_events(sid: str, corpus: str = "swechat", n_calls: int = 1) -> list[dict]:
    evs = []
    for i in range(n_calls):
        base = {c: None for c in COLUMNS}
        evs.append(dict(base, corpus=corpus, session_id=sid, seq=2 * i, kind="call", tool="shell", tool_raw="Bash",
                        call_id=f"c{i}", ts="2026-01-01T00:00:00.000Z", ts_kind="event", is_subagent=False))
        evs.append(dict(base, corpus=corpus, session_id=sid, seq=2 * i + 1, kind="result", tool="shell",
                        call_id=f"c{i}", text="ok", ts="2026-01-01T00:00:00.500Z", ts_kind="event", is_subagent=False))
    return evs


# ================================================================================================= synthetic
class TestUnits(unittest.TestCase):
    def test_unit_of(self):
        self.assertEqual(U.unit_of("swechat", "x", "Claude Code", "claude_code"), "swechat/claude_code")
        self.assertEqual(U.unit_of("agentcap", "x", "pi/hf-router"), "agentcap/pi")
        self.assertEqual(U.unit_of("agentcap", "x", "opencode/local"), "agentcap/opencode")
        self.assertEqual(U.unit_of("tbench2", "x", "Terminus2__GLM-5", "atif"), "tbench2")
        self.assertEqual(U.unit_of("aiv_cu", "x", "gemini-pro"), "aiv_cu")
        self.assertEqual(U.unit_of("file", "x", None, "codex"), "file/codex")
        self.assertEqual(U.unit_of("turns", "x", None), "turns")

    def test_design_constants(self):
        # DESIGN.md §4.5 (CLI borrowing) and prereg_e.json change_log D1 (proxy map)
        self.assertEqual(U.DEFAULT_CALIBRATION_BY_FORMAT, {"claude_code": "swechat/claude_code", "codex": "swechat/codex",
                                                           "opencode": "swechat/opencode", "gemini": "swechat/gemini",
                                                           "atif": "tbench2"})
        self.assertEqual(U.D1_PROXY_UNIT, {"pub_cc_hf": "cc_local", "pub_trace_commons": "cc_local",
                                           "pub_codex": "swechat/codex", "agentcap/opencode": "swechat/opencode"})
        for a in C.CORPUS_ADAPTERS.values():
            for u in a.units:
                self.assertIn(u, U.PHASE_E_UNITS)

    def test_units_match_prereg_and_calibration_files(self):
        pj = json.loads((ROOT / "analysis" / "prereg_e.json").read_text(encoding="utf-8"))
        cols = [c for c in pj["n6_transfer_grid"]["columns"] if not c.startswith("+")]
        self.assertTrue(set(cols) <= set(U.PHASE_E_UNITS))
        cal = ROOT / "analysis" / "out" / "phase_e"
        for p in sorted(cal.glob("prereg_e_calibration_*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            names = list(d["units"]) if isinstance(d.get("units"), dict) else [d["unit"]]
            for u in names:
                self.assertIn(u, U.PHASE_E_UNITS, p.name)

    def test_reporting_stratum(self):
        self.assertEqual(U.reporting_stratum("tbench2", "Terminus2__GLM-5", "atif"), "atif")
        self.assertEqual(U.reporting_stratum("agentcap", "pi/hf-router"), "hf-router")
        self.assertEqual(U.reporting_stratum("aiv_cu", "gemini-pro"), "gemini-pro")


class TestRegistry(unittest.TestCase):
    def test_every_corpus_has_an_adapter(self):
        want = {"swechat", "aiv_cc", "aiv_cu", "whowhen", "pub_cc_hf", "pub_trace_commons", "tbench2", "glm_tb21",
                "pub_codex", "agentcap", "cc_local"}
        self.assertEqual(set(C.CORPUS_ADAPTERS), want)

    def test_private_and_publishable(self):
        self.assertEqual(C.PRIVATE_CORPORA, frozenset({"cc_local"}))
        self.assertNotIn("cc_local", C.public_corpora())
        self.assertEqual(C.PUBLISHABLE, frozenset({"swechat", "tbench2", "pub_trace_commons", "glm_tb21"}))
        for c, a in C.CORPUS_ADAPTERS.items():
            self.assertEqual(a.publishable, c in C.PUBLISHABLE, c)
            self.assertTrue(set(a.cache_splits) <= set(C.READABLE_SPLITS))

    def test_refuses_other_splits(self):
        ad = C.get_adapter("swechat")
        for bad in ("H", "h", "AB", ""):
            with self.assertRaises(AssertionError):
                ad.cache_path(bad)
            with self.assertRaises(AssertionError):
                ad.iter_sessions(bad)          # raised at call time, not at first next()
            with self.assertRaises(AssertionError):
                ad.iter_frames(bad)
            with self.assertRaises(AssertionError):
                ad.read_columns(bad, ["session_id"])

    def test_refuses_held_out_names(self):
        for name in ("swechat_H.parquet", "x_Held_Out.parquet", "heldout_cache.parquet"):
            with self.assertRaises(AssertionError):
                C._refuse_path(Path(name))
        for name in ("pub_cc_hf_A.parquet", "swechat_E.parquet", "tbench2_B.parquet"):
            C._refuse_path(Path(name))

    def test_no_held_out_strings_in_loaders(self):
        # mirrors DESIGN.md §5.2 rule 1 (tests/test_no_heldout_access.py) for this package
        bad = ["_EH.json", "HELD" + "OUT", "_H.parquet", "H_pack"]
        for p in sorted(q for q in (ROOT / "verifier" / "loaders").iterdir() if q.suffix in (".py", ".json")):
            txt = p.read_text(encoding="utf-8")
            for b in bad:
                self.assertNotIn(b, txt, f"{p.name} contains {b!r}")

    def test_import_isolation(self):
        # verifier.loaders may import analysis.loaders.*, never analysis.probes (DESIGN.md §2.2, §2.4)
        code = ("import sys, verifier.loaders, verifier.loaders.capabilities, verifier.loaders.sidecar; "
                "print(sorted(m for m in sys.modules if m.startswith('analysis.probes')))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[]")
        import ast
        for p in sorted((ROOT / "verifier" / "loaders").glob("*.py")):
            mods = set()
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    mods |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module)
                    mods |= {f"{node.module}.{a.name}" for a in node.names}
            self.assertFalse({m for m in mods if m.startswith("analysis.probes")}, p.name)
            self.assertNotIn("analysis.lib.ir", mods, p.name)   # the IR comes through verifier.ir (DA1)
            self.assertFalse({m for m in mods if m.startswith(("verifier.checks", "eval"))}, p.name)


class TestSniff(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_formats(self):
        self.assertEqual(D.sniff(_w(self.d, "a.jsonl", CC_LINES)), "claude_code")
        self.assertEqual(D.sniff(_w(self.d, "rollout-x.jsonl", CODEX_LINES)), "codex")
        self.assertEqual(D.sniff(_w(self.d, "t.jsonl", TURNS)), "turns")
        self.assertEqual(D.sniff(_w(self.d, "trajectory.json", json.dumps(ATIF))), "atif")
        self.assertEqual(D.sniff(_w(self.d, "empty.jsonl", "")), "empty")
        self.assertEqual(D.sniff(_w(self.d, "u.jsonl", [{"foo": 1}])), "unknown")
        self.assertEqual(D.sniff(_w(self.d, "oc.json", json.dumps({"info": {"id": "ses_1"}, "messages": []}))),
                         "opencode")
        df = to_frame(_ir_events("s1"))
        p = self.d / "x.parquet"
        df.to_parquet(p, index=False)
        self.assertEqual(D.sniff(p), "ir")
        df.drop(columns=["extra"]).to_parquet(self.d / "y.parquet", index=False)
        self.assertEqual(D.sniff(self.d / "y.parquet"), "unknown")
        self.assertEqual(D.sniff(self.d), "unknown")


class TestLoadFile(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def _check_frame(self, ev):
        self.assertEqual(list(ev.columns), list(COLUMNS))
        validate(ev)
        self.assertEqual(ev["seq"].tolist(), list(range(len(ev))))
        self.assertEqual(list(ev.index), list(range(len(ev))))

    def test_claude_code(self):
        p = _w(self.d, "abc-123.jsonl", CC_LINES)
        [ls] = F.load_events(p)
        self._check_frame(ls.events)
        self.assertEqual((ls.corpus, ls.unit, ls.calibration_unit, ls.fmt, ls.session_id),
                         ("file", "file/claude_code", "swechat/claude_code", "claude_code", "abc-123"))
        self.assertTrue(ls.calibration_borrowed)
        self.assertEqual(ls.sidecar, {"cc_numlines": {"toolu_1": 2}})
        self.assertEqual(set(ls.events["corpus"]), {"file"})
        ev = ls.events
        self.assertEqual(ev.loc[ev.kind == "call", "call_id"].tolist(), ["toolu_1"])
        self.assertEqual(ev.loc[ev.kind == "result", "call_id"].tolist(), ["toolu_1"])
        self.assertEqual(ev.loc[ev.kind == "call", "request_id"].tolist(), ["req_011CSHt1Ww6fW8JNP9Mm2XUc"])
        self.assertEqual(ls.source["format"], "claude_code")
        self.assertEqual(ls.source["loader"], "analysis/loaders/load_swechat.py")
        self.assertIsNone(ls.source["split"])
        self.assertEqual(len(ls.source["loader_sha256"]), 64)
        # explicit calibration and an extra sidecar key
        [ls2] = F.load_events(p, calibration_unit="cc_local", sidecar={"entire_tally": None})
        self.assertEqual(ls2.calibration_unit, "cc_local")
        self.assertEqual(set(ls2.sidecar), {"cc_numlines", "entire_tally"})

    def test_claude_code_session(self):
        p = _w(self.d, "abc-123.jsonl", CC_LINES)
        [s] = F.load_file(p)
        self.assertEqual((s.corpus, s.session_id, s.unit, s.calibration_unit), ("file", "abc-123", "file/claude_code",
                                                                                 "swechat/claude_code"))
        self.assertIn("sidecar.cc_numlines", s.capabilities)
        self.assertIn("join.call_id", s.capabilities)
        self.assertEqual(set(s.source), {"path", "format", "loader", "loader_sha256", "split"})

    def test_codex(self):
        p = _w(self.d, "rollout-2026.jsonl", CODEX_LINES)
        [ls] = F.load_events(p)
        self._check_frame(ls.events)
        self.assertEqual((ls.unit, ls.calibration_unit, ls.fmt), ("file/codex", "swechat/codex", "codex"))
        ev = ls.events
        self.assertEqual(ev.loc[ev.kind == "call", "command"].tolist(), ["ls"])
        self.assertEqual(ev.loc[ev.kind == "result", "call_id"].tolist(), ["call_1"])
        self.assertEqual(ls.sidecar, {})

    def test_atif(self):
        tdir = self.d / "task__abc"
        (tdir / "agent").mkdir(parents=True)
        p = _w(tdir / "agent", "trajectory.json", json.dumps(ATIF))
        [ls] = F.load_events(p)
        self._check_frame(ls.events)
        self.assertEqual((ls.unit, ls.calibration_unit, ls.session_id), ("file/atif", "tbench2", "trajectory"))
        (tdir / "result.json").write_text(json.dumps({"task_name": "t"}), encoding="utf-8")
        [ls] = F.load_events(p)
        self.assertEqual(ls.session_id, "task__abc")   # Harbor layout: named after the trial directory
        self.assertEqual(ls.events["kind"].tolist()[-1], "meta")  # the trial result row, as the cache has it

    def test_ir_parquet(self):
        df = pd.concat([to_frame(_ir_events("b", "cc_local")), to_frame(_ir_events("a", "pub_cc_hf", 2))],
                       ignore_index=True)
        p = self.d / "pack.parquet"
        df.to_parquet(p, index=False)
        out = F.load_events(p)
        self.assertEqual([x.session_id for x in out], ["a", "b"])
        a, b = out
        self.assertEqual((a.corpus, a.unit, a.calibration_unit), ("pub_cc_hf", "pub_cc_hf", "cc_local"))
        self.assertEqual((b.corpus, b.unit, b.calibration_unit), ("cc_local", "cc_local", "cc_local"))
        self.assertFalse(b.calibration_borrowed)
        for x in out:
            self._check_frame(x.events)
        [only] = F.load_events(p, session="b")
        self.assertEqual(only.session_id, "b")
        with self.assertRaises(F.LoadError):
            F.load_events(p, session="zzz")
        for bad in ("x_H.parquet", "my_heldout.parquet"):
            q = self.d / bad
            df.to_parquet(q, index=False)
            with self.assertRaises(F.LoadError):
                F.load_events(q)

    def test_turns(self):
        p = _w(self.d, "turns.jsonl", TURNS)
        out = F.load_events(p)
        self.assertEqual([x.session_id for x in out], ["S1", "S2"])
        s1 = out[0]
        self.assertEqual((s1.corpus, s1.unit, s1.calibration_unit, s1.fmt), ("turns", "turns", None, "turns"))
        self.assertEqual(s1.turn_ids, {0: "t1", 1: "t2", 2: "t3"})
        self._check_frame(s1.events)
        [s] = F.load_file(p, session="S1")
        self.assertEqual(s.turn_ids, {0: "t1", 1: "t2", 2: "t3"})

    def test_errors(self):
        with self.assertRaises(F.LoadError):
            F.load_events(self.d / "missing.jsonl")
        with self.assertRaises(F.LoadError):
            F.load_events(self.d)
        with self.assertRaises(F.LoadError):
            F.load_events(_w(self.d, "empty.jsonl", ""))
        with self.assertRaises(F.LoadError):
            F.load_events(_w(self.d, "u.jsonl", [{"foo": 1}]))
        with self.assertRaises(F.LoadError):
            F.load_events(_w(self.d, "a.jsonl", CC_LINES), session="not-this-one")
        with self.assertRaises(F.LoadError):
            F.load_events(_w(self.d, "b.jsonl", CC_LINES), fmt="nonsense")
        # a Claude Code file whose lines carry no event (only skipped entry types) is an empty session
        with self.assertRaises(F.LoadError):
            F.load_events(_w(self.d, "c.jsonl", [{"type": "summary", "summary": "x", "leafUuid": "u"}]),
                          fmt="claude_code")
        self.assertTrue(issubclass(F.LoadError, ValueError))


class TestSidecarReaders(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_read_cc_numlines_rules(self):
        def entry(tid, n, *, block=True, file_key="file"):
            content = [{"type": "tool_result", "tool_use_id": tid, "content": "x"}] if block else "x"
            return {"type": "user", "message": {"role": "user", "content": content},
                    "toolUseResult": {file_key: {"numLines": n}}}
        lines = [entry("t1", 3), entry("t1", 9), entry("t2", True), entry("t3", 4, block=False),
                 entry("t4", 5, file_key="other"), entry("t5", 2.0), entry("t6", 0)]
        p = _w(self.d, "x.jsonl", lines)
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"numLines": broken\n')
        self.assertEqual(SC.read_cc_numlines(p), {"t1": 3, "t6": 0})
        q = _w(self.d, "y.jsonl", [entry("t7", 1), entry("t1", 99)])
        self.assertEqual(SC.read_cc_numlines([p, q, self.d / "absent.jsonl"]), {"t1": 3, "t6": 0, "t7": 1})

    def test_copied_request_ids(self):
        f1 = pd.DataFrame({"session_id": ["s2", "s2", "s3", "s4"], "request_id": ["r1", "r1", "r2", None]})
        f2 = pd.DataFrame({"session_id": ["s1", "s5", "s3"], "request_id": ["r1", "r3", "r2"]})
        self.assertEqual(SC.copied_request_ids([f1, f2]), {"r1": "s1"})
        self.assertEqual(SC.copied_request_ids([]), {})

    def test_tally_int(self):
        for v, want in ((None, 0), (float("nan"), 0), (pd.NA, 0), ("7", 7), (3, 3), ("x", 0)):
            self.assertEqual(SC._tally_int(v), want)


class TestCapabilitiesJson(unittest.TestCase):
    PATH = ROOT / "verifier" / "loaders" / "capabilities.json"

    @classmethod
    def setUpClass(cls):
        if not cls.PATH.exists():
            raise unittest.SkipTest("capabilities.json not built")
        cls.doc = json.loads(cls.PATH.read_text(encoding="utf-8"))

    def test_shape(self):
        d = self.doc
        self.assertEqual(d["schema"], "verifier.loaders.capabilities/1")
        self.assertIn("cc_local", d["excluded"])
        self.assertNotIn("cc_local", d["corpora"])
        self.assertNotIn("cc_local", d["summary"])
        self.assertEqual(set(d["corpora"]), set(C.public_corpora()))
        for c, v in d["corpora"].items():
            self.assertTrue(set(v["splits"]) <= {"A", "B", "E"}, c)
            for sp, blk in v["splits"].items():
                self.assertGreater(blk["all"]["sessions"], 0, (c, sp))
            for k in ("ms_timestamps", "call_result_join", "request_ids", "usage", "native_error",
                      "truncation_markers"):
                self.assertIn(k, d["summary"][c])
        for k in d["provenance"]["caches"]:
            self.assertRegex(k, r"_[ABE]$")

    def test_block_reproduces(self):
        # recompute one small split and compare, when the cache is the one the JSON was built from
        key = "glm_tb21_A"
        rec = self.doc["provenance"]["caches"].get(key)
        if rec is None or not have_cache("glm_tb21", "A"):
            self.skipTest("glm_tb21 A not available")
        from verifier import session as S
        from verifier.loaders import capabilities as CAP
        if rec.get("sha256") and CAP._sha256(CACHE / "glm_tb21_A.parquet") != rec["sha256"]:
            self.skipTest("cache rebuilt since capabilities.json")
        if C.file_sha256_lf(str(Path(S.__file__).resolve())) != self.doc["provenance"]["session_module_sha256_lf"]:
            self.skipTest("verifier.session changed since capabilities.json: rebuild it "
                          "(python -m verifier.loaders.capabilities)")
        self.assertEqual(CAP.measure_split("glm_tb21", "A"), self.doc["corpora"]["glm_tb21"]["splits"]["A"])


# ================================================================================================ cache / raw data
@unittest.skipUnless(have_cache("glm_tb21", "A"), "analysis/cache not present")
class TestCacheAdapters(unittest.TestCase):
    def test_iter_frames_glm(self):
        ad = C.get_adapter("glm_tb21")
        ids = ad.session_ids("A")
        frames = list(ad.iter_frames("A"))
        self.assertEqual([str(f["session_id"].iat[0]) for f in frames], ids)
        ref = to_frame(_ir_events("x")).dtypes
        for f in frames:
            self.assertEqual(list(f.columns), list(COLUMNS))
            self.assertEqual(f["seq"].tolist(), list(range(len(f))))
            self.assertTrue((f.dtypes == ref).all())
            validate(f)
        sub = list(ad.iter_frames("A", [ids[3], ids[1], "no-such-id"]))
        self.assertEqual([str(f["session_id"].iat[0]) for f in sub], [ids[1], ids[3]])  # file order

    @unittest.skipUnless(have_cache("swechat", "A"), "swechat A cache not present")
    def test_iter_sessions_swechat_a(self):
        ad = C.get_adapter("swechat")
        ss = list(ad.iter_sessions("A", calibration_unit_of=lambda u: u))
        self.assertEqual(len(ss), len(ad.session_ids("A")))
        for s in ss:
            self.assertEqual(s.corpus, "swechat")
            self.assertTrue(s.unit.startswith("swechat/"))
            self.assertEqual(s.calibration_unit, s.unit)
            self.assertEqual(s.source["split"], "A")
            self.assertEqual(s.source["path"], "analysis/cache/swechat_A.parquet")
            self.assertEqual(dict(s.sidecar), {})
        units = {s.unit for s in ss}
        self.assertTrue(units <= set(ad.units) | {"swechat/unknown"})

    @unittest.skipUnless(have_cache("swechat", "A") and TRANS.exists(), "swechat A cache or transcripts absent")
    def test_iter_sessions_with_sidecar(self):
        ad = C.get_adapter("swechat")
        ids = ad.session_ids("A")
        fm = U.swechat_formats(ids)
        cc = [s for s in ids if fm.get(s) == "claude_code"][:5]
        cx = [s for s in ids if fm.get(s) == "codex"][:2]
        ss = {s.session_id: s for s in ad.iter_sessions("A", cc + cx, with_sidecar=True)}
        self.assertEqual(set(ss), set(cc + cx))
        for sid in cc:
            self.assertIn("cc_numlines", ss[sid].sidecar)
            self.assertIn("entire_tally", ss[sid].sidecar)
            self.assertIn("copied_request_ids", ss[sid].sidecar)
            self.assertIn("sidecar.copied_request_ids", ss[sid].capabilities)
        for sid in cx:
            self.assertNotIn("cc_numlines", ss[sid].sidecar)

    @unittest.skipUnless(have_cache("agentcap", "A"), "agentcap A cache not present")
    def test_agentcap_units(self):
        ad = C.get_adapter("agentcap")
        ids = ad.session_ids("A")
        fm = ad.formats("A", ids)
        self.assertEqual(set(fm.values()), {"opencode", "pi"})
        units = {ad.unit_of(s, None, fm[s]) for s in ids}
        self.assertEqual(units, {"agentcap/opencode", "agentcap/pi"})


@unittest.skipUnless(have_cache("swechat", "A") and TRANS.exists(), "swechat A cache or transcripts absent")
class TestRawFileParity(unittest.TestCase):
    """The raw-file path reproduces the cached IR of the same session (all columns but corpus and stratum)."""

    @staticmethod
    def _same(a: pd.DataFrame, b: pd.DataFrame) -> list[str]:
        cols = [c for c in COLUMNS if c not in ("corpus", "stratum")]
        x = a[cols].astype(object).where(a[cols].notna(), None)
        y = b[cols].astype(object).where(b[cols].notna(), None)
        return [c for c in cols if not x[c].equals(y[c])]

    def test_swechat_formats(self):
        ad = C.get_adapter("swechat")
        ids = ad.session_ids("A")
        fm = U.swechat_formats(ids)
        for fmt in ("claude_code", "codex", "opencode", "gemini"):
            sid = sorted(s for s in ids if fm.get(s) == fmt)[0]
            p = TRANS / f"{sid}.jsonl"
            self.assertEqual(D.sniff(p), fmt)
            [ls] = F.load_events(p)
            [cached] = list(ad.iter_frames("A", [sid]))
            self.assertEqual(len(ls.events), len(cached), fmt)
            self.assertEqual(self._same(ls.events, cached), [], fmt)

    @unittest.skipUnless(have_cache("glm_tb21", "A"), "glm_tb21 A cache not present")
    def test_atif(self):
        ad = C.get_adapter("glm_tb21")
        sid = ad.session_ids("A")[0]
        [p] = ad.raw_paths(sid)
        if not p.exists():
            self.skipTest("glm_tb21 raw data absent")
        [ls] = F.load_events(p)
        self.assertEqual(ls.session_id, sid)
        [cached] = list(ad.iter_frames("A", [sid]))
        self.assertEqual(self._same(ls.events, cached), [])


# ======================================================================================================== parity
@unittest.skipUnless(have_cache("swechat", "B") and have_cache("swechat", "E"), "swechat B/E caches absent")
class TestSidecarParity(unittest.TestCase):
    def test_copied_request_ids_swechat(self):
        # 1,385 [analysis/out/phase_e/f1_bracket.json units."swechat/claude_code|B".copied_ids.copied_ids_readable_corpus]
        idx = SC.copied_request_ids_for_corpus("swechat")
        self.assertEqual(len(idx), 1385)
        self.assertEqual(SC.copy_index_splits("swechat"), ("B", "E"))

    @unittest.skipUnless(SLOW and TRANS.exists(), "set VERIFIER_SLOW_TESTS=1 (reads ~1,500 raw transcripts)")
    def test_numlines_and_tally_e(self):
        ad = C.get_adapter("swechat")
        ids = ad.session_ids("E")
        # E sessions with zero IR events are not in the cache; the build report lists them
        build = json.loads((ROOT / "analysis" / "out" / "phase_e" / "swechat_E_build.json").read_text(encoding="utf-8"))
        ids = ids + list(build["cache"]["sessions_with_zero_events"])
        fm = U.swechat_formats(ids)
        cc = [s for s in ids if fm.get(s) == "claude_code"]
        # [analysis/out/phase_e/r4_r5.json R4.units."swechat/claude_code".raw_join_coverage.E]: 1,546 sessions,
        # 1,444 with numLines, 28,198 counters
        self.assertEqual(len(cc), 1546)
        nl = [SC.read_cc_numlines(ad.raw_paths(s)) for s in cc]
        self.assertEqual(sum(1 for n in nl if n), 1444)
        self.assertEqual(sum(len(n) for n in nl), 28198)
        # [r4_r5.json R5.gate_counts]: E|claude_code decided 1,520 + api_call_count_zero 3; no_token_usage 23
        tally = SC.read_entire_tally(cc)
        dicts = [v for v in tally.values() if v is not None]
        self.assertEqual(len(dicts), 1520 + 3)
        self.assertEqual(sum(1 for v in dicts if v["api"] == 0), 3)
        self.assertEqual(sum(1 for v in tally.values() if v is None), 23)


if __name__ == "__main__":
    unittest.main()
