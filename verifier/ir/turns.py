"""SCOPE.md §3 `turn` dicts -> IR events (DESIGN.md §2.6, `TURN_TO_IR`).

A `turn` is one row of the SWE-chat conversations table (`turn_id, session_id, turn_number, role, turn_type, content,
model, timestamp, tool_name, tool_call_id, file_path, command, tool_input_json`, token counts) plus `uuid`,
`parent_uuid`, `source`. Rows are sorted by `turn_number`, then input order; `seq` is that order.

`request_id`, `api_msg_id`, `native_error` and `exit_code` stay null: the turn contract has no field for them
(DESIGN open item 3), so checks that need them read `missing:` on turn input.
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable, Mapping

import pandas as pd

from verifier.ir import COLUMNS, iso, normalize_tool, to_frame, validate

# (role, turn_type) -> IR kind. '*' = any turn_type for that role. Values from analysis/out/recon/swechat_scan_pinned.json.
TURN_TO_IR: dict[tuple[str, str], str] = {
    ("tool_use", "tool_use"): "call",
    ("tool_result", "tool_result"): "result",
    ("user", "user_prompt"): "user",
    ("user", "system_injected"): "system",
    ("assistant", "assistant_response"): "assistant",
    ("assistant", "assistant_thinking"): "meta",
    ("metadata", "*"): "meta",
}
CORPUS = "turns"


def _null(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    try:
        return bool(pd.isna(v)) if not isinstance(v, (str, bytes, list, dict, tuple)) else False
    except (TypeError, ValueError):
        return False


def _s(v: Any) -> str | None:
    return None if _null(v) else str(v)


def _int(v: Any) -> int | None:
    if _null(v):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> str | None:
    if _null(v):
        return None
    if hasattr(v, "isoformat") and not isinstance(v, str):  # datetime / pandas Timestamp from a parquet read
        v = v.isoformat()
    return iso(v)


def _json(v: Any) -> str | None:
    if _null(v):
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)


def _extra(d: Mapping[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _kind_of(role: str | None, turn_type: str | None) -> str | None:
    k = TURN_TO_IR.get((role or "", turn_type or ""))
    if k is None:
        k = TURN_TO_IR.get((role or "", "*"))
    return k


def turns_to_events(turns: Iterable[Mapping[str, Any]]) -> tuple[pd.DataFrame, dict[int, str], int]:
    """One session's turn dicts -> (IR frame with exactly COLUMNS, {seq: turn_id}, n_unmapped).

    Raises ValueError on an empty input or on turns of more than one session_id."""
    rows = [dict(t) for t in turns]
    if not rows:
        raise ValueError("turns_to_events: no turns")
    sids = {_s(r.get("session_id")) for r in rows}
    if len(sids) != 1 or None in sids:
        raise ValueError(f"turns_to_events: expected exactly one session_id, got {sorted(map(str, sids))}")
    sid = sids.pop()
    order = sorted(range(len(rows)), key=lambda i: (_int(rows[i].get("turn_number")) is None,
                                                      _int(rows[i].get("turn_number")) or 0, i))
    calls_by_id: dict[str, list[tuple[int, str | None, str | None]]] = {}
    events: list[dict] = []
    turn_ids: dict[int, str] = {}
    unmapped = 0
    for seq, i in enumerate(order):
        r = rows[i]
        role, ttype = _s(r.get("role")), _s(r.get("turn_type"))
        kind = _kind_of(role, ttype)
        turn_id = _s(r.get("turn_id"))
        ts = _ts(r.get("timestamp"))
        ev: dict[str, Any] = {c: None for c in COLUMNS}
        ev.update(corpus=CORPUS, session_id=sid, stratum=_s(r.get("source")), seq=seq, ts=ts,
                  ts_kind="event" if ts else "none", uuid=_s(r.get("uuid")), parent_uuid=_s(r.get("parent_uuid")))
        extra: dict[str, Any] = {"turn_id": turn_id}
        content = _s(r.get("content"))
        if kind == "call":
            raw = _s(r.get("tool_name"))
            cid = _s(r.get("tool_call_id")) or f"turn:{turn_id}"
            ev.update(kind="call", tool_raw=raw, tool=normalize_tool(raw), call_id=cid,
                      args=_json(r.get("tool_input_json")), command=_s(r.get("command")))
            calls_by_id.setdefault(cid, []).append((seq, ev["tool"], raw))
        elif kind == "result":
            cid = _s(r.get("tool_call_id"))
            ev.update(kind="result", call_id=cid, text=content)
            prior = [c for c in calls_by_id.get(cid, []) if c[0] < seq] if cid else []
            if prior:
                ev.update(tool=prior[-1][1], tool_raw=prior[-1][2])
        elif kind in ("user", "system"):
            ev.update(kind=kind, text=content)
        elif kind == "assistant":
            ev.update(kind="assistant", text=content, usage_in=_int(r.get("input_tokens")),
                      usage_out=_int(r.get("output_tokens")), model=_s(r.get("model")),
                      usage_cache_read=_int(r.get("cache_read_input_tokens")),
                      usage_cache_create=_int(r.get("cache_creation_input_tokens")))
        elif kind == "meta" and (role, ttype) == ("assistant", "assistant_thinking"):
            extra.update(turn_type="assistant_thinking", thinking_chars=len(content or ""))
            ev.update(kind="meta")
        elif kind == "meta":
            extra.update(turn_type=ttype)
            ev.update(kind="meta")
        else:
            unmapped += 1
            extra.update(role=role, turn_type=ttype)
            ev.update(kind="meta")
        ev["extra"] = _extra(extra)
        if turn_id is not None:
            turn_ids[seq] = turn_id
        events.append(ev)
    # a result may precede its call in input order; copy tool names from any call of that id as a last resort
    for ev in events:
        if ev["kind"] == "result" and ev["tool_raw"] is None and ev["call_id"] in calls_by_id:
            c = calls_by_id[ev["call_id"]][0]
            ev.update(tool=c[1], tool_raw=c[2])
    df = to_frame(events)
    validate(df)
    return df, turn_ids, unmapped
