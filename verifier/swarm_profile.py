"""The 'swarm' verifier profile: the five checks validated on the swarm harness (spoof_v1.db), pinned to their frozen
rule files. Stdlib only; every check module is loaded BY PATH, so this works where `import verifier` cannot (the
package __init__ imports pandas, which Windows Application Control blocks on the dev host).

These checks read the swarm/SWE-chat turn format directly (dicts with turn_id, session_id, turn_number, role, content,
timestamp, tool_name, tool_call_id, tool_input_json, input_tokens/output_tokens, uuid, parent_uuid, source). They are
not IR-Session `Check` classes, so they are listed here and exposed through `verifier.registry.enabled_checks('swarm')`
rather than in REGISTRY / ENABLED_CHECKS; the default profile is unchanged.

    from verifier import swarm_profile as SP          # or load this file by path
    per_check = SP.run_session(turns)                  # {check: {tool_call_id: verdict dict}}
    combined = SP.combine(per_check)                   # {tool_call_id: 'contradicted'|'supported'|'unconstrained'}
    SP.verify_claim(row, turns, observed)              # claim units (claim_provenance only)

Combination rule (analysis/SWARM_DATASET_RESULTS.md): contradicted if any check contradicts; else supported if a
content check (t1_recompute, t3_shadow_state, claim_provenance) supports; else unconstrained. t0_structural's
'supported' (ok:structure_intact) is format-level and never vouches for content; token_conservation never supports.
Every check fired on 0 of 179,365 honest real calls before freezing (analysis/out/swarmds/test_scores.json).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN_DIR = REPO_ROOT / "analysis" / "swarmds"
PROFILE = "swarm"

# name -> (module file, frozen rule file, unit, strength). Order = run order.
SWARM_CHECKS: dict[str, dict] = {
    "t0_structural": {"module": "verifier/checks/structural.py", "frozen": "frozen_t0_structural.json",
                      "unit": "tool_output", "strength": "format"},
    "t1_recompute": {"module": "verifier/checks/recompute.py", "frozen": "frozen_t1_recompute.json",
                     "unit": "tool_output", "strength": "strong"},
    "t3_shadow_state": {"module": "verifier/checks/shadow_state.py", "frozen": "frozen_t3_state.json",
                        "unit": "tool_output", "strength": "strong"},
    "token_conservation": {"module": "verifier/checks/token_conservation.py",
                           "frozen": "frozen_token_conservation.json", "unit": "tool_output", "strength": "format"},
    "claim_provenance": {"module": "verifier/checks/claims.py", "frozen": "frozen_claims.json",
                         "unit": "claim", "strength": "strong"},
}
SWARM_ENABLED_CHECKS: tuple[str, ...] = tuple(SWARM_CHECKS)
SESSION_CHECKS: tuple[str, ...] = tuple(k for k, v in SWARM_CHECKS.items() if v["unit"] == "tool_output")
CONTENT_SUPPORT: tuple[str, ...] = ("t1_recompute", "t3_shadow_state", "claim_provenance")

_MODS: dict[str, Any] = {}
_FROZEN: dict[str, dict] = {}


def module_sha256(name: str) -> str:
    b = (REPO_ROOT / SWARM_CHECKS[name]["module"]).read_bytes()
    return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()


def frozen(name: str) -> dict:
    if name not in _FROZEN:
        _FROZEN[name] = json.loads((FROZEN_DIR / SWARM_CHECKS[name]["frozen"]).read_text(encoding="utf-8"))
    return _FROZEN[name]


def frozen_sha_ok(name: str) -> Optional[bool]:
    """True/False when the frozen file records a module sha (LF-normalised or raw bytes), None when it records none."""
    want = frozen(name).get("module_sha256")
    if not want:
        return None
    raw = (REPO_ROOT / SWARM_CHECKS[name]["module"]).read_bytes()
    return want in (module_sha256(name), hashlib.sha256(raw).hexdigest(),  # + CRLF form: checkout EOLs don't matter
                    hashlib.sha256(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")).hexdigest())


def load(name: str):
    """The check module, loaded by path and pinned to its frozen rules."""
    if name in _MODS:
        return _MODS[name]
    p = REPO_ROOT / SWARM_CHECKS[name]["module"]
    spec = importlib.util.spec_from_file_location(f"swarm_profile_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    if name == "t1_recompute":
        mod.load_frozen(str(FROZEN_DIR / SWARM_CHECKS[name]["frozen"]))
    _MODS[name] = mod
    return mod


def _run_one(name: str, turns: list[dict]) -> dict:
    m = load(name)
    if name == "t3_shadow_state":
        return m.check_session(turns, {"disabled_rules": list(frozen(name).get("disabled_rules", []))})
    if name == "token_conservation":
        return m.check_session(turns, m.load_frozen(str(FROZEN_DIR / SWARM_CHECKS[name]["frozen"])))
    return m.check_session(turns)


def run_session(turns: list[dict], checks: Optional[tuple[str, ...]] = None) -> dict[str, dict]:
    """{check: {tool_call_id: verdict dict}} for the session-level (tool_output) checks of the swarm profile."""
    names = checks or SESSION_CHECKS
    return {n: _run_one(n, turns) for n in names if n in SESSION_CHECKS}


def combine(per_check: Mapping[str, Mapping[str, Mapping]]) -> dict[str, str]:
    out: dict[str, str] = {}
    cids = {cid for res in per_check.values() for cid in res if cid != "__session__"}
    for cid in cids:
        vs = {n: (res.get(cid) or {}).get("verdict", "unconstrained") for n, res in per_check.items()}
        if "contradicted" in vs.values():
            out[cid] = "contradicted"
        elif any(vs.get(n) == "supported" for n in CONTENT_SUPPORT):
            out[cid] = "supported"
        else:
            out[cid] = "unconstrained"
    return out


def verify_claim(row: Mapping, turns: list[dict], observed: Optional[Mapping] = None, *, population=None) -> dict:
    """claim_provenance on one claim unit, with the frozen rules."""
    m = load("claim_provenance")
    return m.verify_claim(row, turns, observed, population=population, rules=dict(frozen("claim_provenance")["rules"]))


__all__ = ["PROFILE", "SWARM_CHECKS", "SWARM_ENABLED_CHECKS", "SESSION_CHECKS", "CONTENT_SUPPORT", "load", "frozen",
           "frozen_sha_ok", "module_sha256", "run_session", "combine", "verify_claim"]
