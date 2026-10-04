"""Unit tests for the T0 structural check (verifier/checks/structural.py). Stdlib unittest, no data files.

    python -m unittest tests.test_structural -v      (from the worktree root)

The module is loaded by path so the tests run even where `import verifier` fails (verifier/__init__ imports pandas).
Turns are small hand-built dicts in the swarm turn format; nothing here reads data/.
"""
import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

_P = Path(__file__).resolve().parents[1] / "verifier" / "checks" / "structural.py"
_spec = importlib.util.spec_from_file_location("t0_structural_under_test", _P)
T0 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = T0
_spec.loader.exec_module(T0)

SID = "blk-s00-000"


def _session(n_calls: int = 3) -> list[dict]:
    turns, prev, k = [], None, 0

    def add(role, tool=None, cid=None, content=""):
        nonlocal prev, k
        k += 1
        u = f"u{k:03d}"
        turns.append({"turn_id": f"{SID}:{k}", "session_id": SID, "turn_number": k, "role": role,
                      "content": content, "timestamp": f"2026-10-04T03:00:{k:02d}.000+00:00", "tool_name": tool,
                      "tool_call_id": cid, "uuid": u, "parent_uuid": prev, "source": "swarm"})
        prev = u

    add("user", content="task")
    for i in range(n_calls):
        add("assistant", content="thinking")
        add("tool_use", "Bash", f"c{i}", json.dumps({"command": "ls"}))
        add("tool_result", "Bash", f"c{i}", "a\nb")
    return turns


def _contradicted(res):
    return {k: v["reason"] for k, v in res.items() if v["verdict"] == "contradicted"}


class StructuralTests(unittest.TestCase):
    def test_honest_session_is_supported(self):
        res = T0.check_session(_session())
        self.assertEqual({v["reason"] for v in res.values()}, {"ok:structure_intact"})
        self.assertEqual(set(res), {"c0", "c1", "c2"})

    def test_deleted_tool_use_is_orphan_result(self):  # the injected_I-struct signature
        t = _session()
        del t[5]  # tool_use of c1
        res = T0.check_session(t)
        self.assertEqual(_contradicted(res), {"c1": "violation:orphan_result"})
        self.assertEqual(set(res["c1"]["rules"]), {"orphan_result", "parent_chain_break", "turn_number_gap"})
        self.assertEqual(res["c0"]["reason"], "abstain:session_structure_broken")

    def test_orphan_caught_even_after_renumber_and_rechain(self):
        t = _session()
        del t[5]
        for i, x in enumerate(t):  # a careful forger repairs numbering and the parent chain
            x["turn_number"], x["turn_id"] = i + 1, f"{SID}:{i + 1}"
            x["parent_uuid"] = t[i - 1]["uuid"] if i else None
        res = T0.check_session(t)
        self.assertEqual(_contradicted(res), {"c1": "violation:orphan_result"})
        self.assertEqual(res["c1"]["rules"], ["orphan_result"])

    def test_deleted_result_is_missing_result(self):
        t = _session()
        del t[6]  # tool_result of c1
        self.assertEqual(_contradicted(T0.check_session(t)), {"c1": "violation:missing_result"})

    def test_trailing_unanswered_call_abstains(self):
        t = _session()[:-1]
        res = T0.check_session(t)
        self.assertEqual(res["c2"]["reason"], "missing:result_truncated_at_end")
        self.assertEqual(_contradicted(res), {})

    def test_result_stamped_before_its_call(self):
        t = _session()
        t[6]["timestamp"] = "2026-10-04T02:00:00.000+00:00"
        self.assertEqual(_contradicted(T0.check_session(t))["c1"], "violation:timestamp_regression")

    def test_epoch_ms_timestamps(self):
        t = _session()
        for i, x in enumerate(t):
            x["timestamp"] = 1_791_000_000_000 + 1000 * i
        self.assertEqual(_contradicted(T0.check_session(t)), {})
        t[6]["timestamp"] = 1_700_000_000_000
        self.assertIn("c1", _contradicted(T0.check_session(t)))

    def test_duplicate_call_id(self):
        t = _session()
        t[8]["tool_call_id"] = t[9]["tool_call_id"] = "c1"  # c2 pair relabelled as c1
        self.assertEqual(_contradicted(T0.check_session(t))["c1"], "violation:duplicate_call_id")

    def test_reparented_result(self):
        t = _session()
        t[6]["parent_uuid"] = t[1]["uuid"]
        self.assertEqual(_contradicted(T0.check_session(t)), {"c1": "violation:parent_chain_break"})

    def test_non_swarm_profile_abstains(self):
        t = [dict(x, source="claude_code") for x in _session()]
        del t[5]
        res = T0.check_session(t)
        self.assertEqual({v["reason"] for v in res.values()}, {"abstain:unvalidated_harness"})
        self.assertIn("c1", _contradicted(T0.check_session(t, profile="swarm")))

    def test_input_not_mutated(self):
        t = _session()
        before = copy.deepcopy(t)
        T0.check_session(t)
        self.assertEqual(t, before)

    def test_frozen_file_matches_module(self):
        f = Path(__file__).resolve().parents[1] / "analysis" / "swarmds" / "frozen_t0_structural.json"
        if not f.is_file():
            self.skipTest("frozen file not built")
        fz = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(fz["module_sha256"], T0.module_sha256())
        self.assertEqual(fz["rules"], {k: dict(v) for k, v in T0.RULES.items()})


if __name__ == "__main__":
    unittest.main()
