"""T0 structural integrity check for swarm-harness transcripts (SWE-chat turn format).

WHAT IT DECIDES
    Whether the *record* of a tool call is structurally possible for the harness that wrote it: every result has its
    call, ids are unique, the uuid/parent_uuid chain is the harness's linear chain, turn numbers are contiguous and
    timestamps never go backwards. A violation is evidence the transcript was edited (a turn deleted, re-parented,
    inserted, back-dated or spliced in from elsewhere). It says NOTHING about whether a structurally intact result's
    *content* is true: 'supported' here means only "this call's record satisfies every structural invariant".

WHERE THE INVARIANTS COME FROM
    Learned from ALL honest swarm transcripts (data/swarm/*/transcripts/*.jsonl, 6,232 sessions, 458,244 turns,
    179,349 tool results) before any rule was written; each one held on every honest turn (0 exceptions), except that
    16 honest sessions end on a tool_use with no result (harness killed mid-call), which is why a trailing unanswered
    call abstains instead of failing. The rules are zero-tolerance invariants; the only tunables are recorded in
    analysis/swarmds/frozen_t0_structural.json together with this file's sha256.

PROFILES (soundness gate)
    The invariants are specific to the swarm harness (one tool call per step, result immediately after its call,
    linear uuid chain, monotone ms timestamps). They are NOT true of e.g. Claude Code logs (parallel calls, sidechains,
    compaction). So rules run only under profile 'swarm': auto-detected when every turn carries source == 'swarm', or
    forced by the caller with profile='swarm'. Any other session gets 'unconstrained' / 'abstain:unvalidated_harness'
    for every call, never a contradiction.

ENTRYPOINT (integrator contract)
    check_session(turns, *, profile='auto') -> dict[str, dict]
        turns   : one session's turns, list of dicts in file order (keys used: turn_id, session_id, turn_number, role,
                  timestamp [ISO-8601 string or epoch ms number], tool_name, tool_call_id, uuid, parent_uuid, source).
                  File order is the evidence: do NOT sort before calling.
        returns : {tool_call_id: {"verdict": "contradicted"|"supported"|"unconstrained",
                                  "reason": "<prefix>:<detail>"   (prefix ok|violation|missing|abstain, as base.py),
                                  "confidence": float|None        (None unless contradicted),
                                  "rules": [rule names that fired on this call],
                                  "evidence": [{"turn_index", "turn_id", "rule", "detail"}...]}}
                  plus, when a violation could not be pinned to one call, the key "__session__" with
                  verdict 'contradicted' and localized False (no tool_call_id is blamed for it).
    Every tool_call_id that appears on a tool_use or tool_result turn gets an entry.

    verdict_for_call(turns, tool_call_id, *, profile='auto') -> dict   convenience wrapper for one row.
    check_claim(claim_row, turns=None) -> dict                          claim units: always unconstrained (T0 has no
                                                                        claim-level rule).

Stdlib only. Pure: never mutates its input.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

NAME = "t0_structural"
VERSION = "1.0.0"
SESSION_KEY = "__session__"

# Rule table. 'confidence' is filled from the honest validation at freeze time (Laplace: 1 - (fp+1)/(n+2) over the
# rule's honest opportunities); the values here are the frozen ones and must match frozen_t0_structural.json.
RULES: dict[str, dict] = {
    # pairing (localised to exactly one call id)
    "duplicate_call_id":    {"scope": "call",     "confidence": 0.99999},
    "orphan_result":        {"scope": "call",     "confidence": 0.99999},
    "result_before_call":   {"scope": "call",     "confidence": 0.99999},
    "missing_result":       {"scope": "call",     "confidence": 0.99999},
    "result_not_adjacent":  {"scope": "call",     "confidence": 0.99999},
    "tool_name_mismatch":   {"scope": "call",     "confidence": 0.99999},
    # record chain (localised to the tool turns that touch the broken boundary, else session-level)
    "parent_chain_break":   {"scope": "boundary", "confidence": 0.99999},
    "uuid_duplicate":       {"scope": "turn",     "confidence": 0.99999},
    "turn_number_gap":      {"scope": "boundary", "confidence": 0.99999},
    "turn_id_mismatch":     {"scope": "turn",     "confidence": 0.99999},
    "session_id_mismatch":  {"scope": "turn",     "confidence": 0.99999},
    "timestamp_regression": {"scope": "boundary", "confidence": 0.99999},
}
# Order in which a call's deciding reason is chosen when several rules fire on it (most specific first).
RULE_PRIORITY: tuple[str, ...] = (
    "orphan_result", "result_before_call", "duplicate_call_id", "missing_result", "result_not_adjacent",
    "tool_name_mismatch", "session_id_mismatch", "turn_id_mismatch", "uuid_duplicate", "parent_chain_break",
    "turn_number_gap", "timestamp_regression")
TIMESTAMP_TOLERANCE_S = 0.0   # the harness writes ms timestamps that never decrease; no slack is needed or granted
TOOL_ROLES = ("tool_use", "tool_result")


# ----------------------------------------------------------------------------------------------------------- helpers
def _ts(v: Any) -> Optional[float]:
    """Seconds since epoch from an ISO-8601 string or an epoch-ms number; None if absent or unparsable."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) / 1000.0
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def detect_profile(turns: Sequence[Mapping[str, Any]]) -> Optional[str]:
    if turns and all(t.get("source") == "swarm" for t in turns):
        return "swarm"
    return None


def _call_ids(turns: Sequence[Mapping[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for t in turns:
        if t.get("role") in TOOL_ROLES and t.get("tool_call_id") is not None:
            seen.setdefault(str(t["tool_call_id"]), None)
    return list(seen)


# --------------------------------------------------------------------------------------------------- violation scan
def find_violations(turns: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Every structural violation in one swarm-profile session, as
    {"rule", "turn_index", "calls": [tool_call_id...], "detail"}. `calls` empty = not attributable to one call."""
    out: list[dict] = []
    n = len(turns)
    if n == 0:
        return out

    def tid(i: int) -> Any:
        return turns[i].get("turn_id")

    def role(i: int) -> Any:
        return turns[i].get("role") if 0 <= i < n else None

    def cid(i: int) -> Optional[str]:
        c = turns[i].get("tool_call_id") if 0 <= i < n else None
        return None if c is None else str(c)

    def add(rule: str, i: int, calls: Iterable[Optional[str]], detail: dict) -> None:
        out.append({"rule": rule, "turn_index": i, "turn_id": tid(i),
                    "calls": sorted({c for c in calls if c is not None}), "detail": detail})

    # boundary attribution: the call(s) whose own record touches the broken boundary (i-1, i) and is thereby left
    # incomplete -- a result whose predecessor link is broken, or a call whose successor link is broken. A break
    # between two complete pairs (result | use, result | assistant, ...) blames no single call.
    def boundary_calls(i: int) -> list[Optional[str]]:
        calls: list[Optional[str]] = []
        if role(i) == "tool_result":
            calls.append(cid(i))
        if role(i - 1) == "tool_use":
            calls.append(cid(i - 1))
        return calls

    # ---- pairing
    uses: dict[str, list[int]] = defaultdict(list)
    results: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(turns):
        c = cid(i)
        if c is None:
            continue
        if t.get("role") == "tool_use":
            uses[c].append(i)
        elif t.get("role") == "tool_result":
            results[c].append(i)
    for c in sorted(set(uses) | set(results)):
        u, r = uses.get(c, []), results.get(c, [])
        if len(u) > 1 or len(r) > 1:
            add("duplicate_call_id", (u + r)[0], [c], {"n_tool_use": len(u), "n_tool_result": len(r),
                                                       "turn_indexes": sorted(u + r)})
        for ri in r:
            if not any(ui < ri for ui in u):
                if u:
                    add("result_before_call", ri, [c], {"call_index": u[0], "result_index": ri})
                else:
                    add("orphan_result", ri, [c], {"result_index": ri})
        for ui in u:
            later = [ri for ri in r if ri > ui]
            if not later:
                if ui == n - 1:
                    continue  # transcript ends on this call: truncated, not tampered (16 honest cases)
                add("missing_result", ui, [c], {"call_index": ui, "next_role": role(ui + 1)})
            elif later[0] != ui + 1:
                add("result_not_adjacent", ui, [c], {"call_index": ui, "result_index": later[0]})
        if u and r:
            names_u = {turns[i].get("tool_name") for i in u}
            names_r = {turns[i].get("tool_name") for i in r}
            if names_u != names_r and None not in names_u and None not in names_r:
                add("tool_name_mismatch", r[0], [c], {"call_tool": sorted(map(str, names_u)),
                                                      "result_tool": sorted(map(str, names_r))})

    # ---- identity fields
    sid0 = turns[0].get("session_id")
    for i, t in enumerate(turns):
        if sid0 is not None and t.get("session_id") is not None and t.get("session_id") != sid0:
            add("session_id_mismatch", i, [cid(i)] if role(i) in TOOL_ROLES else [],
                {"session_id": str(t.get("session_id"))[:120], "expected": str(sid0)[:120]})
        tn, ti, sid = t.get("turn_number"), t.get("turn_id"), t.get("session_id")
        if tn is not None and ti is not None and sid is not None and ti != f"{sid}:{tn}":
            add("turn_id_mismatch", i, [cid(i)] if role(i) in TOOL_ROLES else [],
                {"turn_id": str(ti)[:120], "expected": f"{sid}:{tn}"[:120]})

    # ---- uuid chain
    uu = [t.get("uuid") for t in turns]
    first_at: dict[Any, int] = {}
    for i, u in enumerate(uu):
        if u is None:
            continue
        if u in first_at:
            add("uuid_duplicate", i, [cid(i)] if role(i) in TOOL_ROLES else [], {"first_index": first_at[u]})
        else:
            first_at[u] = i
    if all(u is not None for u in uu):
        if "parent_uuid" in turns[0] and turns[0].get("parent_uuid") is not None:
            add("parent_chain_break", 0, [cid(0)] if role(0) in TOOL_ROLES else [],
                {"kind": "first_turn_has_parent"})
        for i in range(1, n):
            if "parent_uuid" not in turns[i]:
                continue
            p = turns[i].get("parent_uuid")
            if p != uu[i - 1]:
                kind = ("dangling" if p not in first_at else "earlier_turn" if first_at[p] < i - 1
                        else "later_turn" if first_at[p] >= i else "none") if p is not None else "null"
                add("parent_chain_break", i, boundary_calls(i), {"kind": kind})

    # ---- turn numbers
    tns = [t.get("turn_number") for t in turns]
    if all(isinstance(x, int) and not isinstance(x, bool) for x in tns):
        if tns[0] != 1:
            add("turn_number_gap", 0, [cid(0)] if role(0) in TOOL_ROLES else [], {"first": tns[0]})
        for i in range(1, n):
            if tns[i] - tns[i - 1] != 1:
                add("turn_number_gap", i, boundary_calls(i), {"prev": tns[i - 1], "this": tns[i]})

    # ---- timestamps (harness is monotone non-decreasing over the whole session)
    ts = [_ts(t.get("timestamp")) for t in turns]
    for i in range(1, n):
        a, b = ts[i - 1], ts[i]
        if a is None or b is None or b >= a - TIMESTAMP_TOLERANCE_S:
            continue
        calls: list[Optional[str]] = []
        if role(i) == "tool_result" and role(i - 1) == "tool_use" and cid(i) == cid(i - 1):
            calls.append(cid(i))  # result stamped before its own call
            who = "result_before_its_call"
        else:
            # which side is the outlier? turn i back-dated if dropping it restores order; turn i-1 forward-dated if
            # dropping that one does. Blame the tool turn(s) among the outliers; else no single call.
            back = i + 1 >= n or ts[i + 1] is None or ts[i + 1] >= a
            fwd = i - 2 < 0 or ts[i - 2] is None or b >= ts[i - 2]
            who = "back_dated" if back and not fwd else "forward_dated" if fwd and not back else "ambiguous"
            if who in ("back_dated", "ambiguous") and role(i) in TOOL_ROLES:
                calls.append(cid(i))
            if who in ("forward_dated", "ambiguous") and role(i - 1) in TOOL_ROLES:
                calls.append(cid(i - 1))
        add("timestamp_regression", i, calls, {"kind": who, "delta_s": round(a - b, 3)})
    return out


# ------------------------------------------------------------------------------------------------------- entrypoint
def check_session(turns: Sequence[Mapping[str, Any]], *, profile: str = "auto") -> dict[str, dict]:
    """See module docstring. {tool_call_id: {verdict, reason, confidence, rules, evidence}} (+ '__session__')."""
    turns = list(turns)
    ids = _call_ids(turns)
    prof = detect_profile(turns) if profile == "auto" else profile
    if prof != "swarm":
        return {c: {"verdict": "unconstrained", "reason": "abstain:unvalidated_harness", "confidence": None,
                    "rules": [], "evidence": []} for c in ids}
    viol = find_violations(turns)
    per_call: dict[str, list[dict]] = defaultdict(list)
    unattributed: list[dict] = []
    for v in viol:
        if v["calls"]:
            for c in v["calls"]:
                per_call[c].append(v)
        else:
            unattributed.append(v)
    last = len(turns) - 1
    use_idx: dict[str, list[int]] = defaultdict(list)
    res_idx: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(turns):
        if t.get("tool_call_id") is not None:
            if t.get("role") == "tool_use":
                use_idx[str(t["tool_call_id"])].append(i)
            elif t.get("role") == "tool_result":
                res_idx[str(t["tool_call_id"])].append(i)

    out: dict[str, dict] = {}
    for c in ids:
        vs = per_call.get(c)
        if vs:
            rules = sorted({v["rule"] for v in vs}, key=RULE_PRIORITY.index)
            top = rules[0]
            out[c] = {"verdict": "contradicted", "reason": f"violation:{top}",
                      "confidence": RULES[top]["confidence"], "rules": rules,
                      "evidence": [{"turn_index": v["turn_index"], "turn_id": v["turn_id"], "rule": v["rule"],
                                    "detail": v["detail"]} for v in vs]}
        elif not res_idx.get(c) and use_idx.get(c) and use_idx[c][-1] == last:
            out[c] = {"verdict": "unconstrained", "reason": "missing:result_truncated_at_end", "confidence": None,
                      "rules": [], "evidence": []}
        elif viol:
            # the session record is broken somewhere else: this call's own record is intact, but an edited transcript
            # does not vouch for anything in it
            out[c] = {"verdict": "unconstrained", "reason": "abstain:session_structure_broken", "confidence": None,
                      "rules": [], "evidence": []}
        else:
            out[c] = {"verdict": "supported", "reason": "ok:structure_intact", "confidence": None,
                      "rules": [], "evidence": []}
    if unattributed:
        rules = sorted({v["rule"] for v in unattributed}, key=RULE_PRIORITY.index)
        out[SESSION_KEY] = {"verdict": "contradicted", "reason": f"violation:{rules[0]}",
                            "confidence": RULES[rules[0]]["confidence"], "rules": rules, "localized": False,
                            "evidence": [{"turn_index": v["turn_index"], "turn_id": v["turn_id"], "rule": v["rule"],
                                          "detail": v["detail"]} for v in unattributed]}
    return out


def verdict_for_call(turns: Sequence[Mapping[str, Any]], tool_call_id: str, *, profile: str = "auto") -> dict:
    """One call's verdict; 'missing:call_not_in_session' when the id appears on no tool turn."""
    res = check_session(turns, profile=profile)
    return res.get(str(tool_call_id), {"verdict": "unconstrained", "reason": "missing:call_not_in_session",
                                       "confidence": None, "rules": [], "evidence": []})


def check_claim(claim_row: Mapping[str, Any], turns: Optional[Sequence[Mapping[str, Any]]] = None) -> dict:
    """Claim units (v_blind unit='claim'): T0 has no claim-level rule, so always an abstention."""
    return {"verdict": "unconstrained", "reason": "abstain:claim_unit", "confidence": None, "rules": [],
            "evidence": []}


def explain(v: Mapping[str, Any]) -> str:
    """One plain-English sentence for a verdict dict returned by check_session."""
    r = v.get("reason", "")
    text = {
        "violation:orphan_result": "This tool result has no tool call with its id anywhere before it: the call record "
                                   "is missing, so nothing in the transcript shows the result was produced by a call.",
        "violation:result_before_call": "This tool result appears before the call with its id.",
        "violation:duplicate_call_id": "This call id appears on more than one call or result turn.",
        "violation:missing_result": "This call has no result although the session continues past it.",
        "violation:result_not_adjacent": "This call's result does not immediately follow it, which the harness always does.",
        "violation:tool_name_mismatch": "The result names a different tool than its call.",
        "violation:parent_chain_break": "The uuid/parent_uuid chain is broken at this call's record: a turn next to it "
                                        "was deleted, inserted or re-parented.",
        "violation:turn_number_gap": "Turn numbers skip or repeat next to this call's record: a turn was removed or added.",
        "violation:timestamp_regression": "A timestamp next to this call's record runs backwards, which the harness never writes.",
        "violation:turn_id_mismatch": "This turn's id does not match its session and turn number.",
        "violation:session_id_mismatch": "This turn carries a different session id than the rest of the session.",
        "violation:uuid_duplicate": "This turn reuses another turn's uuid.",
        "ok:structure_intact": "The call and its result satisfy every structural invariant (says nothing about content).",
        "missing:result_truncated_at_end": "The transcript ends on this call before any result: truncated, not judged.",
        "abstain:session_structure_broken": "This call's record is intact, but the session is edited elsewhere.",
        "abstain:unvalidated_harness": "Structural invariants are validated only for the swarm harness; not judged.",
    }
    return text.get(r, r)


def module_sha256() -> str:
    import hashlib
    from pathlib import Path
    return hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


__all__ = ["NAME", "VERSION", "RULES", "RULE_PRIORITY", "SESSION_KEY", "check_session", "verdict_for_call",
           "check_claim", "find_violations", "detect_profile", "explain", "module_sha256"]
