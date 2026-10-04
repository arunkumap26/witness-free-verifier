"""Unit tests for the 'swarm' verifier profile (verifier/swarm_profile.py + verifier/registry.py profiles).

    python -m unittest tests.test_swarm_profile -v      (from the worktree root)

Stdlib only, no data files. swarm_profile.py is loaded by path; the registry is imported with a stub `verifier`
package object so verifier/__init__.py (which imports pandas, blocked on the dev host) does not run.
"""
import copy
import importlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("swarm_profile_under_test", ROOT / "verifier" / "swarm_profile.py")
SP = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = SP
_spec.loader.exec_module(SP)

SID = "blk-s00-000"


def _session(n_calls=3):
    turns, prev, k = [], None, 0

    def add(role, tool=None, cid=None, content="", inp=None):
        nonlocal prev, k
        k += 1
        u = f"u{k:03d}"
        turns.append({"turn_id": f"{SID}:{k}", "session_id": SID, "turn_number": k, "role": role, "content": content,
                      "timestamp": f"2026-10-04T03:00:{k:02d}.000+00:00", "tool_name": tool, "tool_call_id": cid,
                      "tool_input_json": inp, "uuid": u, "parent_uuid": prev, "source": "swarm"})
        prev = u

    add("user", content="task")
    for i in range(n_calls):
        add("assistant", content="thinking")
        inp = json.dumps({"file_path": f"/workspace/f{i}.py", "content": "x = 1\n"})
        add("tool_use", "Write", f"c{i}", inp, inp)
        add("tool_result", "Write", f"c{i}", f"File created successfully at: /workspace/f{i}.py")
    return turns


def _registry():
    """Import verifier.registry without running verifier/__init__.py (pandas)."""
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "verifier" or k.startswith("verifier.")}
    for k in saved:
        del sys.modules[k]
    pkg = types.ModuleType("verifier")
    pkg.__path__ = [str(ROOT / "verifier")]
    sys.modules["verifier"] = pkg
    try:
        return importlib.import_module("verifier.registry")
    finally:
        for k in [k for k in sys.modules if k == "verifier" or k.startswith("verifier.")]:
            del sys.modules[k]
        sys.modules.update(saved)


class TestSwarmProfile(unittest.TestCase):
    def test_frozen_files_and_shas(self):
        self.assertEqual(SP.SWARM_ENABLED_CHECKS, ("t0_structural", "t1_recompute", "t3_shadow_state",
                                                   "token_conservation", "claim_provenance"))
        for n in SP.SWARM_ENABLED_CHECKS:
            self.assertTrue((SP.FROZEN_DIR / SP.SWARM_CHECKS[n]["frozen"]).is_file(), n)
            self.assertIn(SP.frozen_sha_ok(n), (True, None), f"{n}: module changed since its rules were frozen")

    def test_honest_session_not_contradicted(self):
        turns = _session()
        per = SP.run_session(turns)
        self.assertEqual(set(per), set(SP.SESSION_CHECKS))
        comb = SP.combine(per)
        self.assertEqual(set(comb), {"c0", "c1", "c2"})
        self.assertNotIn("contradicted", comb.values())
        # T0 'structure intact' alone never makes the combined verdict 'supported'
        only_t0 = SP.combine({"t0_structural": per["t0_structural"]})
        self.assertEqual(set(only_t0.values()), {"unconstrained"})

    def test_deleted_call_is_contradicted(self):
        turns = copy.deepcopy(_session())
        del turns[5]                                   # the tool_use of c1: its result is now an orphan
        comb = SP.combine(SP.run_session(turns, ("t0_structural",)))
        self.assertEqual(comb["c1"], "contradicted")

    def test_ack_path_mismatch_is_contradicted(self):
        turns = copy.deepcopy(_session())
        turns[-1]["content"] = "File created successfully at: /workspace/other.py"
        per = SP.run_session(turns, ("t1_recompute",))
        self.assertEqual(per["t1_recompute"]["c2"]["verdict"], "contradicted")
        self.assertEqual(SP.combine(per)["c2"], "contradicted")

    def test_claim_check_abstains_without_transcript(self):
        v = SP.verify_claim({"row_id": "claim:x", "source": "execlog", "unit": "tool_output",
                             "claimed_output": "ok"}, [], None)
        self.assertEqual(v["verdict"], "unconstrained")

    def test_registry_profiles_static(self):
        """Runs everywhere: reads verifier/registry.py's literals with ast (the module itself needs pandas)."""
        import ast
        tree = ast.parse((ROOT / "verifier" / "registry.py").read_text(encoding="utf-8"))
        lit = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                lit[node.target.id] = node.value
        self.assertEqual(ast.literal_eval(lit["ENABLED_CHECKS"]), (), "default profile must stay unchanged")
        self.assertEqual(ast.literal_eval(lit["SWARM_PROFILE_CHECKS"]), SP.SWARM_ENABLED_CHECKS)
        prof = lit["PROFILES"]
        self.assertIsInstance(prof, ast.Dict)
        got = {ast.literal_eval(k): v.id for k, v in zip(prof.keys, prof.values)}
        self.assertEqual(got, {"default": "ENABLED_CHECKS", "swarm": "SWARM_PROFILE_CHECKS"})

    def test_registry_profiles(self):
        try:
            R = _registry()
        except ImportError as e:              # pragma: no cover - only if a stdlib-only module grows a heavy import
            self.skipTest(f"verifier.registry not importable here: {e}")
        self.assertEqual(R.enabled_checks("default"), R.ENABLED_CHECKS)
        self.assertEqual(R.enabled_checks("swarm"), SP.SWARM_ENABLED_CHECKS)
        with self.assertRaises(KeyError):
            R.enabled_checks("nope")


if __name__ == "__main__":
    unittest.main()
