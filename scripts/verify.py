#!/usr/bin/env python
"""Verify one agent transcript, witness-free: for every tool call, is the recorded result consistent with the rest of
the session? Stdlib only. No dataset, no network, no model.

    python scripts/verify.py examples/tampered.jsonl
    python scripts/verify.py examples/honest.jsonl --json

Input: one session as turn JSONL (one JSON object per line, in file order), the swarm / SWE-chat format the dataset
uses: role in {user, assistant, tool_use, tool_result}, tool_name, tool_call_id, content (tool_use: the input JSON),
timestamp, uuid, parent_uuid, turn_number, source. See DATASET_README.md for the format.

Checks (frozen rules, the same ones scored on the dataset, see analysis/FLOWCHARTS.md):
  T0 structural          the record is structurally possible for the harness (pairing, ids, chain, clock)
  T1 recompute           the result can be recomputed from the call's own inputs / earlier reads, and matches
  T3 shadow state        the result is consistent with the file state the session itself built up
  TC token conservation  the result's size is consistent with the token counts the model server billed
Per call the verdict is CONTRADICTED if any check contradicts it, else SUPPORTED if T1 or T3 vouches for its content
(T0 'structure intact' alone does not), else UNCONSTRAINED (no check could decide: an abstention, not a pass).
Published-claim checks (claim provenance) need the dataset's claim rows and are not run here.

Exit code: 1 if any call (or the session structure) is contradicted, 0 otherwise, 2 on bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SHORT = {"t0_structural": "T0", "t1_recompute": "T1", "t3_shadow_state": "T3", "token_conservation": "TC"}
CONTENT_SUPPORT = ("t1_recompute", "t3_shadow_state")
GLOSS = {   # plain-English reading of the rules that fire most often (rule docstrings in verifier/checks/*.py)
    "orphan_result": "a result with no matching call (a turn was deleted or re-parented)",
    "duplicate_call_id": "two calls or results share one id",
    "missing_result": "a call whose result is missing or out of place",
    "read_numbering": "Read output is not numbered the way the Read tool numbers lines",
    "ack_path": "the write acknowledgement names a different path than the call wrote",
    "ack_id": "the submit acknowledgement names a different id than the call submitted",
    "exit_code": "the output proves a non-zero exit but carries no 'Exit code N' header (or the reverse)",
    "pure_bash": "a pure command's output (echo, arithmetic, seq, ...) is not what it computes",
    "known_file": "output disagrees with file content the session already established",
    "pytest_counts": "the pytest summary disagrees with its own per-test lines",
    "pytest_replay": "same pytest selection, no file changed in between, different result",
    "presence_after_absence": "a path shown absent here is present later, and nothing in between created it",
    "listing_missing": "the listing omits a file the session established exists in that directory",
    "read_content": "read content disagrees with what the session last wrote or read there",
    "git_status_flip": "git status changed with no edit in between",
    "git_clean_after_edit": "git reports clean right after the session changed a tracked file",
    "exit_status": "output that implies a non-zero exit, delivered without the 'Exit code N' header",
    "rerun_exit": "same read-only command, no change in between, different exit status",
    "token_growth_logged_text_smaller": "the logged result is far smaller than the tokens the server billed for it",
    "token_growth_logged_text_larger": "the logged result is far larger than the tokens the server billed for it",
}


def load_turns(path: Path) -> list[dict]:
    turns = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if line.strip():
                try:
                    turns.append(json.loads(line))
                except ValueError as e:
                    raise SystemExit(f"{path}:{i}: not JSON ({e})") from None
    return turns


def call_index(turns: list[dict]) -> list[dict]:
    """Tool calls in order of first appearance: {id, turn, tool, input}."""
    seen, out = set(), []
    for t in turns:
        cid = t.get("tool_call_id")
        if not cid or cid in seen or t.get("role") not in ("tool_use", "tool_result"):
            continue
        seen.add(cid)
        inp = ""
        if t.get("role") == "tool_use":
            try:
                a = json.loads(t.get("content") or t.get("tool_input_json") or "{}")
            except (TypeError, ValueError):
                a = {}
            if isinstance(a, dict):
                inp = a.get("command") or a.get("file_path") or a.get("path") or a.get("pattern") or \
                    json.dumps(a, ensure_ascii=False)
        out.append({"id": cid, "turn": t.get("turn_number"), "tool": t.get("tool_name") or "?",
                    "input": " ".join(str(inp).split())})
    return out


def verify(turns: list[dict]) -> dict:
    from analysis.swarmds.score import load_checks            # frozen rules, pinned exactly as the scorer pins them
    runners, _prov, _mods = load_checks()
    res = {name: fn(turns) for name, fn in runners.items()}
    calls = call_index(turns)
    num = {c["id"]: i for i, c in enumerate(calls, 1)}
    rows = []
    for i, c in enumerate(calls, 1):
        per = {name: res[name].get(c["id"]) or {"verdict": "unconstrained", "reason": "missing:call_not_seen"}
               for name in runners}
        contra = [n for n, v in per.items() if v["verdict"] == "contradicted"]
        supp = [n for n in CONTENT_SUPPORT if per[n]["verdict"] == "supported"]
        if contra:
            verdict, by = "CONTRADICTED", contra
        elif supp:
            verdict, by = "SUPPORTED", supp
        else:
            verdict, by = "UNCONSTRAINED", []
        reasons = []
        for n in by:
            v = per[n]
            r = v.get("reason") or ""
            rule = v.get("rule") or (v.get("rules") or [None])[0]
            if rule and rule not in r:
                r += f" [{rule}]"
            cw = [f"#{num[x]}" if x in num else x for x in (v.get("conflict_with") or [])]
            if cw:
                r += " (conflicts with call " + ", ".join(cw) + ")"
            key = rule or r.split(":", 1)[-1].split(" ")[0]
            if v["verdict"] == "contradicted" and key in GLOSS:
                r += ": " + GLOSS[key]
            reasons.append(f"{SHORT[n]} {r}")
        if not by:
            reasons.append("no check could decide: " + ", ".join(
                f"{SHORT[n]} {per[n].get('reason')}" for n in ("t1_recompute", "t3_shadow_state")))
        rows.append({"n": i, "turn": c["turn"], "call_id": c["id"], "tool": c["tool"], "input": c["input"],
                     "verdict": verdict, "checks": [SHORT[n] for n in by], "reason": "; ".join(reasons),
                     "per_check": {SHORT[n]: {"verdict": v["verdict"], "reason": v.get("reason")}
                                   for n, v in per.items()}})
    session = []
    for name, r in res.items():
        if "__session__" in r:
            session.append({"check": SHORT[name], "reason": r["__session__"].get("reason")})
    return {"calls": rows, "session_violations": session}


def clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 3] + "..."


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Witness-free verification of one transcript (turn JSONL).")
    ap.add_argument("transcript", help="path to a session transcript, one JSON turn per line")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--flagged-only", action="store_true", help="only list contradicted calls")
    a = ap.parse_args(argv)
    p = Path(a.transcript)
    if not p.is_file():
        print(f"no such file: {p}", file=sys.stderr)
        return 2
    turns = load_turns(p)
    if not turns:
        print(f"{p}: empty transcript", file=sys.stderr)
        return 2
    out = verify(turns)
    calls = out["calls"]
    n_c = sum(r["verdict"] == "CONTRADICTED" for r in calls) + len(out["session_violations"])
    if a.json:
        print(json.dumps({"file": a.transcript, **out}, indent=1, ensure_ascii=False))
        return 1 if n_c else 0
    sid = next((t.get("session_id") for t in turns if t.get("session_id")), "?")
    print(f"{a.transcript}  (session {sid}, {len(turns)} turns, {len(calls)} tool calls)\n")
    print(f"  {'#':>3} {'turn':>4}  {'tool':8s} {'input':38s} {'verdict':13s} {'check':5s}  reason")
    for r in calls:
        if a.flagged_only and r["verdict"] != "CONTRADICTED":
            continue
        print(f"  {r['n']:>3} {str(r['turn']):>4}  {clip(r['tool'], 8):8s} {clip(r['input'], 38):38s} "
              f"{r['verdict']:13s} {','.join(r['checks']) or '-':5s}  {r['reason']}")
    for s in out["session_violations"]:
        print(f"  session-level: {s['check']} {s['reason']}")
    k = {v: sum(r["verdict"] == v for r in calls) for v in ("CONTRADICTED", "SUPPORTED", "UNCONSTRAINED")}
    overall = "CONTRADICTED" if n_c else "no contradiction found"
    print(f"\n  {k['CONTRADICTED']} contradicted, {k['SUPPORTED']} supported, {k['UNCONSTRAINED']} unconstrained"
          f"{', ' + str(len(out['session_violations'])) + ' session-level violation(s)' if out['session_violations'] else ''}"
          f"  ->  {overall} (exit {1 if n_c else 0})")
    return 1 if n_c else 0


if __name__ == "__main__":
    sys.exit(main())
