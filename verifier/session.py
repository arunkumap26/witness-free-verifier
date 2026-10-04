"""verifier.session: one session's IR frame -> `Session` (DESIGN.md §4.2, §4.3, §3.1, §3.2, §2.7, §2.4).

DESIGN.md lays this out as a `verifier/session/` package (capabilities, pairs, responses, clocks, idclock, threads,
sidecar). The scaffold assignment names a single module, so the same names live here, in sections:

  idclock      provider id decoding, vendored from analysis/loaders/load_tbench2.py id_family/id_embedded_ms and
               analysis/probes/prereg_e_common.py _B58I/_WIN, plus the DA20 UUIDv7 version/variant gate
  sidecar      SIDECAR_KEYS, validate_sidecar (DA14)
  threads      stream_key (same rule as prereg_e_common._stream)
  pairs        pair_calls (pairing and orphan rule of §3.1)
  capabilities CAPABILITIES, detect_capabilities (§4.3)
  Session      ClockView, Session, build_session, split_sessions (§4.2)

Pure: no I/O. Imports verifier.ir, verifier.checks.base (EventRef only), numpy and pandas.
"""
from __future__ import annotations

import base64
import bisect
import functools
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional

import numpy as np
import pandas as pd

from verifier import ir
from verifier.checks.base import MAX_REF_VALUE_CHARS, ROLES, EventRef

# ================================================================================================ idclock (vendored)
# Layouts are inferred from data (Phase C / B5b / B4) and undocumented by every vendor, with no stability promise
# (PRIOR_ART.md B2: MATERIAL LIMITATION). A failed decode is lost coverage, never a detection (DA20).
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58I = {c: i for i, c in enumerate(_B58)}
_WIN = (1704067200000, 1798761600000)   # [2024-01-01, 2027-01-01) UTC in epoch ms, as prereg_e_common._WIN
ID_FAMILIES: list[tuple[str, re.Pattern]] = [
    ("anthropic_req", re.compile(r"^req_(?:vrtx_|bdrk_)?01[1-9A-HJ-NP-Za-km-z]{22}$")),
    ("anthropic_msg", re.compile(r"^msg_(?:vrtx_|bdrk_)?01[1-9A-HJ-NP-Za-km-z]{22}$")),
    ("openai_resp_hex50", re.compile(r"^resp_[0-9a-f]{50}$")),
    ("gemini_response_id_b64", re.compile(r"^[A-Za-z0-9_-]{16,24}$")),
    ("chatcmpl_operator", re.compile(r"^chatcmpl-")),
    ("uuid", re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")),
    ("synthetic", re.compile(r"^synthetic:")),
]
ANTHROPIC_FAMILIES = ("anthropic_req", "anthropic_msg")


def id_family(v: str) -> str:
    for name, rx in ID_FAMILIES:
        if rx.match(v):
            return name
    return "other"


def _b58_value(v: str) -> int:
    x = 0
    for ch in v.rsplit("_", 1)[1][2:]:
        x = x * 58 + _B58I[ch]
    return x


def _uuid7_bits_ok(x: int) -> bool:
    """RFC 9562 UUIDv7: version nibble (bits 76-79) == 7 and variant (bits 62-63) == 0b10."""
    return ((x >> 76) & 0xF) == 7 and ((x >> 62) & 0x3) == 0b10


def embedded_ms(fam: str, v: str) -> Optional[float]:
    """Ungated copy of load_tbench2.id_embedded_ms: embedded ms inside [2024-01-01, 2027-01-01), else None."""
    t = None
    if fam in ANTHROPIC_FAMILIES:
        t = float(_b58_value(v) >> 80)
    elif fam == "openai_resp_hex50":
        b = v.split("_", 1)[1]
        t = float(int(b[18:26], 16)) * 1000.0 if b[16:18] == "00" else None
    elif fam == "gemini_response_id_b64":
        try:
            b = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))
            t = float(int.from_bytes(b[:4], "little")) * 1000.0 if len(b) >= 4 else None
        except ValueError:
            t = None
    elif fam == "uuid" and v[14] == "7":
        t = float(int(v.replace("-", "")[:12], 16))
    return t if t is not None and _WIN[0] <= t < _WIN[1] else None


@functools.lru_cache(maxsize=1 << 16)
def decode(v: Any) -> Optional[tuple[str, float]]:
    """(family, embedded ms) or None. Anthropic req_/msg_ ids must also pass the UUIDv7 layout gate (DA20)."""
    if not isinstance(v, str) or not v:
        return None
    fam = id_family(v)
    if fam in ANTHROPIC_FAMILIES and not _uuid7_bits_ok(_b58_value(v)):
        return None
    t = embedded_ms(fam, v)
    return None if t is None else (fam, t)


def layout_report(ids: Iterable[Any]) -> dict:
    """{'n_shaped', 'n_decoded'} over distinct 'req_'-shaped ids; session.json id_layout_unrecognized is
    n_shaped > 0 and n_decoded == 0 (§2.4)."""
    shaped = {v for v in ids if isinstance(v, str) and v.startswith("req_")}
    return {"n_shaped": len(shaped), "n_decoded": sum(1 for v in shaped if decode(v) is not None)}


# ===================================================================================================== sidecar (DA14)
SIDECAR_KEYS: dict[str, str] = {
    "cc_numlines": "dict[str call_id, int]   toolUseResult.file.numLines of Read results (raw Claude Code JSONL)",
    "entire_tally": "dict {api, in, cc, cr, out} (ints) | None   SWE-chat sessions.parquet, gated on session_logs token_usage",
    "copied_request_ids": "dict[str request_id, str smallest_holder_session_id]   corpus-level index (F1 dedupe rule)",
}
TALLY_KEYS = ("api", "in", "cc", "cr", "out")


class FrozenDict(dict):
    """A dict that refuses mutation and still pickles (ProcessPoolExecutor workers)."""

    def _ro(self, *a: Any, **k: Any) -> None:
        raise TypeError("frozen sidecar: attacks and checks never mutate it")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _ro  # type: ignore[assignment]

    def __reduce__(self):  # noqa: D105
        return (type(self), (dict(self),))

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(tuple(sorted(self.items(), key=lambda kv: str(kv[0]))))


def _is_int(v: Any) -> bool:
    return isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_))


def validate_sidecar(sc: Optional[Mapping[str, Any]]) -> FrozenDict:
    """Unknown keys or wrong types -> ValueError. Returns a frozen copy ({} for None)."""
    if sc is None:
        return FrozenDict()
    if not isinstance(sc, Mapping):
        raise ValueError(f"sidecar must be a mapping, got {type(sc).__name__}")
    unknown = sorted(set(sc) - set(SIDECAR_KEYS))
    if unknown:
        raise ValueError(f"unknown sidecar keys {unknown}; allowed: {sorted(SIDECAR_KEYS)}")
    out: dict[str, Any] = {}
    if "cc_numlines" in sc:
        v = sc["cc_numlines"]
        if not isinstance(v, Mapping) or not all(isinstance(k, str) and _is_int(n) for k, n in v.items()):
            raise ValueError("sidecar.cc_numlines must map str call_id -> int")
        out["cc_numlines"] = FrozenDict({k: int(n) for k, n in v.items()})
    if "entire_tally" in sc:
        v = sc["entire_tally"]
        if v is not None:
            if not isinstance(v, Mapping) or set(v) != set(TALLY_KEYS) or not all(_is_int(v[k]) for k in TALLY_KEYS):
                raise ValueError(f"sidecar.entire_tally must be None or a dict with int keys {list(TALLY_KEYS)}")
            v = FrozenDict({k: int(v[k]) for k in TALLY_KEYS})
        out["entire_tally"] = v
    if "copied_request_ids" in sc:
        v = sc["copied_request_ids"]
        if not isinstance(v, Mapping) or not all(isinstance(k, str) and isinstance(s, str) for k, s in v.items()):
            raise ValueError("sidecar.copied_request_ids must map str request_id -> str session_id")
        out["copied_request_ids"] = FrozenDict(v)
    return FrozenDict(out)


# ===================================================================================================== threads
def stream_key(is_sub: Any, agent: Any) -> str:
    """'main' for the main thread, else the subagent's agent_id ('?' when unknown); prereg_e_common._stream's rule."""
    if _truthy(is_sub):
        return agent if isinstance(agent, str) and agent else "?"
    return "main"


# ===================================================================================================== helpers
def _isna(v: Any) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _str(v: Any) -> Optional[str]:
    return None if _isna(v) else str(v)


def _truthy(v: Any) -> bool:
    return False if _isna(v) else bool(v)


def _mask(series: pd.Series, fn: Callable[[Any], bool]) -> np.ndarray:
    return np.fromiter((fn(v) for v in series.tolist()), dtype=bool, count=len(series))


def _eq(series: pd.Series, value: str) -> np.ndarray:
    return _mask(series, lambda v: (not _isna(v)) and v == value)


def _notna(series: pd.Series) -> np.ndarray:
    return series.notna().to_numpy(dtype=bool)


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@functools.lru_cache(maxsize=1 << 16)
def ts_to_ms(s: Any) -> float:
    """ISO stamp -> float epoch ms through analysis.lib.ir.parse_ts (naive = UTC); NaN when missing or unparsable."""
    if not isinstance(s, str) or not s:
        return math.nan
    dt = ir.parse_ts(s)
    if dt is None:
        return math.nan
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return ((dt - _EPOCH) // timedelta(microseconds=1)) / 1000.0


def _dig(d: Any, dotted: str) -> bool:
    for part in dotted.split("."):
        if not isinstance(d, dict) or part not in d:
            return False
        d = d[part]
    return True


def _parse_extra(v: Any) -> dict:
    if not isinstance(v, str) or not v:
        return {}
    try:
        o = json.loads(v)
    except ValueError:
        return {}
    return o if isinstance(o, dict) else {}


# ===================================================================================================== pairs (§3.1)
def pair_calls(kinds: list, call_ids: list) -> tuple[list[tuple[int, Optional[int], int]], list[int]]:
    """Pairing rule (§3.1). A call pairs with the first `result` after it with the same call_id that comes before the
    next call with that call_id; n_results counts results in that window. A result is an orphan iff no call with its
    call_id precedes it. Returns ([(call_seq, result_seq | None, n_results)] in call seq order, orphan result seqs)."""
    call_pos: dict[str, list[int]] = {}
    res_pos: dict[str, list[int]] = {}
    results_all: list[tuple[int, Optional[str]]] = []
    for seq, (k, cid) in enumerate(zip(kinds, call_ids)):
        if k == "call":
            call_pos.setdefault(cid, []).append(seq)
        elif k == "result":
            results_all.append((seq, cid))
            if cid is not None:
                res_pos.setdefault(cid, []).append(seq)
    pairs: list[tuple[int, Optional[int], int]] = []
    for seq, (k, cid) in enumerate(zip(kinds, call_ids)):
        if k != "call":
            continue
        cs = call_pos[cid]
        i = bisect.bisect_left(cs, seq)
        nxt = cs[i + 1] if i + 1 < len(cs) else math.inf
        rs = res_pos.get(cid, [])
        lo = bisect.bisect_right(rs, seq)
        hi = bisect.bisect_left(rs, nxt) if nxt != math.inf else len(rs)
        pairs.append((seq, rs[lo] if hi > lo else None, hi - lo))
    orphans = [seq for seq, cid in results_all if cid is None or cid not in call_pos or call_pos[cid][0] > seq]
    return pairs, orphans


def make_call_keys(call_seqs: list[int], call_ids: list[str]) -> list[str]:
    """call_id when it occurs on exactly one call of the session, else f'{call_id}@{call_seq}' for every call carrying
    it (§3.2)."""
    n: dict[str, int] = {}
    for c in call_ids:
        n[c] = n.get(c, 0) + 1
    return [c if n[c] == 1 else f"{c}@{s}" for s, c in zip(call_seqs, call_ids)]


# ============================================================================================ capabilities (§4.3)
class _CapCtx:
    """Column views shared by the capability predicates; computed once per session."""

    def __init__(self, ev: pd.DataFrame, sidecar: Mapping[str, Any]):
        self.ev = ev
        self.sidecar = sidecar
        self.kind = ev["kind"].astype(object).tolist()
        self.is_cr = np.array([k in ("call", "result") for k in self.kind], dtype=bool)
        self.is_result = np.array([k == "result" for k in self.kind], dtype=bool)
        self.call_ids = [_str(v) for v in ev["call_id"].tolist()]
        self.call_id_set = {c for c, k in zip(self.call_ids, self.kind) if k == "call"}

    @functools.cached_property
    def pairs(self) -> list[tuple[int, Optional[int], int]]:
        return pair_calls(self.kind, self.call_ids)[0]


def _pair_distinct(c: _CapCtx) -> bool:
    ts = c.ev["ts"].tolist()
    tk = c.ev["ts_kind"].tolist()
    for cs, rs, _ in c.pairs:
        if rs is None:
            continue
        if _isna(ts[cs]) or _isna(ts[rs]):
            continue
        if tk[cs] != "shared_turn" and tk[rs] != "shared_turn":
            return True
    return False


def _any_decodable(c: _CapCtx, col: str) -> bool:
    return any(decode(v) is not None for v in set(c.ev[col].dropna().astype(str).tolist()))


def _cc_numlines(c: _CapCtx) -> bool:
    m = c.sidecar.get("cc_numlines")
    return bool(m) and any(k in c.call_id_set for k in m)


CAPABILITIES: dict[str, Callable[[_CapCtx], bool]] = {
    "ts.any": lambda c: bool(_notna(c.ev["ts"]).any()),
    "ts.event": lambda c: bool((c.is_cr & _eq(c.ev["ts_kind"], "event")).any()),
    "ts.ms": lambda c: bool((c.is_cr & _mask(c.ev["ts"], lambda v: (not _isna(v)) and ir.frac_digits(v) >= 3)).any()),
    "ts.pair_distinct": _pair_distinct,
    "join.call_id": lambda c: any(cid in c.call_id_set for cid, r in zip(c.call_ids, c.is_result) if r and cid),
    "join.unique": lambda c: bool(c.call_id_set) and sum(1 for k in c.kind if k == "call") == len(c.call_id_set),
    "result.text": lambda c: bool((c.is_result & _notna(c.ev["text"])).any()),
    "error.native": lambda c: bool((c.is_result & _notna(c.ev["native_error"])).any()),
    "error.exit_code": lambda c: bool(_notna(c.ev["exit_code"]).any()),
    "error.marker": lambda c: any(ir.error_marker(t) is not None for t, r in zip(c.ev["text"].tolist(), c.is_result)
                                  if r and isinstance(t, str)),
    "shell.command": lambda c: bool(_notna(c.ev["command"]).any()),
    "request_id": lambda c: bool((np.array([k in ("assistant", "call", "meta") for k in c.kind], dtype=bool)
                                  & _notna(c.ev["request_id"])).any()),
    "request_id.decodable": lambda c: _any_decodable(c, "request_id"),
    "api_msg_id": lambda c: bool(_notna(c.ev["api_msg_id"]).any()),
    "api_msg_id.decodable": lambda c: _any_decodable(c, "api_msg_id"),
    "usage.io": lambda c: bool((_notna(c.ev["usage_in"]) & _notna(c.ev["usage_out"])).any()),
    "usage.out": lambda c: bool(_notna(c.ev["usage_out"]).any()),
    "usage.cache": lambda c: bool(_notna(c.ev["usage_cache_read"]).any()),
    "subagent": lambda c: any(_truthy(v) for v in c.ev["is_subagent"].tolist()),
    "causal.uuid": lambda c: bool((_notna(c.ev["uuid"]) & _notna(c.ev["parent_uuid"])).any()),
    "sidecar.cc_numlines": _cc_numlines,
    "sidecar.entire_tally": lambda c: isinstance(c.sidecar.get("entire_tally"), dict),
    "sidecar.copied_request_ids": lambda c: "copied_request_ids" in c.sidecar,
}
EXTRA_CAP_PREFIX = "extra:"   # 'extra:<dotted.key>' capabilities are evaluated lazily by Session.has_capability


def is_capability_name(name: str) -> bool:
    return name in CAPABILITIES or (name.startswith(EXTRA_CAP_PREFIX) and len(name) > len(EXTRA_CAP_PREFIX))


def detect_capabilities(events: pd.DataFrame, sidecar: Optional[Mapping[str, Any]] = None) -> frozenset[str]:
    """Names in CAPABILITIES whose predicate holds for at least one event of the session (no thresholds)."""
    ctx = _CapCtx(events, sidecar or {})
    return frozenset(name for name, pred in sorted(CAPABILITIES.items()) if pred(ctx))


# ============================================================================================== Session (§4.2)
# Derived frames keep text columns as object dtype with None for missing (pandas 3 would otherwise infer the 'str'
# dtype and turn None into NaN), ids/counts as nullable Int64, clocks as float64 with NaN.
PAIRS_DTYPES: dict[str, str] = {
    "call_key": "object", "call_id": "object", "call_seq": "int64", "result_seq": "Int64", "n_results": "int64",
    "tool": "object", "tool_raw": "object", "command": "object", "args": "object", "text": "object",
    "native_error": "boolean", "exit_code": "Int64", "t_call_ms": "float64", "t_result_ms": "float64",
    "latency_ms": "float64", "thread": "object", "is_subagent": "bool"}
RESPONSES_DTYPES: dict[str, str] = {
    "resp_key": "object", "request_id": "object", "api_msg_id": "object", "first_seq": "int64", "last_seq": "int64",
    "t_first_ms": "float64", "t_last_ms": "float64", "usage_in": "Int64", "usage_out": "Int64",
    "usage_cache_read": "Int64", "usage_cache_create": "Int64", "provider_ms": "float64", "provider_family": "object",
    "stream": "object", "call_keys": "object", "n_rows": "int64"}


def _typed_frame(rows: list[dict], dtypes: Mapping[str, str]) -> pd.DataFrame:
    cols = {}
    for c, t in dtypes.items():
        vals = [r[c] for r in rows]
        if t in ("Int64", "boolean"):
            cols[c] = pd.array(vals, dtype=t)
        elif t == "object":
            arr = np.empty(len(vals), dtype=object)
            for i, v in enumerate(vals):   # element-wise: tuples (call_keys) must not broadcast
                arr[i] = v
            cols[c] = pd.Series(arr, dtype=object)
        else:
            cols[c] = pd.Series(vals, dtype=t)
    return pd.DataFrame(cols)
@dataclass(frozen=True, eq=False)
class ClockView:
    ts_ms: np.ndarray            # float64 epoch ms per seq, NaN when missing
    ts_kind: np.ndarray          # per seq
    resolution_ms: float         # 10 ** (3 - MIN frac digits over call/result stamps present); NaN when none
    provider_ms: np.ndarray      # per seq: decode(request_id or api_msg_id), NaN when undecodable
    provider_family: np.ndarray  # per seq: id family of that id ('' when the row carries none)


SOURCE_KEYS = ("path", "format", "loader", "loader_sha256", "split")


@dataclass(frozen=True, eq=False)
class Session:
    corpus: str                               # 'swechat', ..., 'file' for CLI inputs, 'turns' for turn dicts
    session_id: str
    unit: str                                 # 'swechat/claude_code', 'tbench2', 'file/claude_code', 'turns', ...
    calibration_unit: Optional[str]           # == unit, the D1 proxy (eval), borrowed by format (CLI), or None (API)
    stratum: Optional[str]
    events: pd.DataFrame                      # IR COLUMNS, sorted by seq, RangeIndex == seq, validated
    capabilities: frozenset                   # §4.3 (extra:<key> capabilities are lazy: use has_capability)
    source: dict = field(default_factory=dict)    # {'path', 'format', 'loader', 'loader_sha256', 'split', ...}
    turn_ids: Optional[dict] = None           # seq -> SCOPE turn_id when built from turns
    sidecar: Mapping = field(default_factory=FrozenDict)   # §2.7; validated, frozen; {} when none

    # ---- derived structures (cached; callers must not mutate the frames) -------------------------------------
    @functools.cached_property
    def _kinds(self) -> list:
        return self.events["kind"].astype(object).tolist()

    @functools.cached_property
    def _call_ids(self) -> list:
        return [_str(v) for v in self.events["call_id"].tolist()]

    @functools.cached_property
    def _pairing(self) -> tuple[list[tuple[int, Optional[int], int]], list[int]]:
        return pair_calls(self._kinds, self._call_ids)

    @functools.cached_property
    def calls(self) -> pd.DataFrame:
        return self.events[np.array([k == "call" for k in self._kinds], dtype=bool)]

    @functools.cached_property
    def results(self) -> pd.DataFrame:
        return self.events[np.array([k == "result" for k in self._kinds], dtype=bool)]

    @functools.cached_property
    def call_keys(self) -> tuple[str, ...]:
        pairs = self._pairing[0]
        return tuple(make_call_keys([p[0] for p in pairs], [self._call_ids[p[0]] for p in pairs]))

    @functools.cached_property
    def call_key_set(self) -> frozenset:
        return frozenset(self.call_keys)

    @functools.cached_property
    def _key_index(self) -> dict[str, tuple[int, Optional[int], int]]:
        return dict(zip(self.call_keys, self._pairing[0]))

    @functools.cached_property
    def key_of_seq(self) -> dict[int, str]:
        """call seq -> call_key."""
        return {p[0]: k for k, p in self._key_index.items()}

    @functools.cached_property
    def orphans(self) -> tuple[int, ...]:
        return tuple(self._pairing[1])

    @functools.cached_property
    def threads(self) -> pd.Series:
        """seq -> (is_subagent, agent_id or '')."""
        sub = [_truthy(v) for v in self.events["is_subagent"].tolist()]
        ag = [_str(v) or "" for v in self.events["agent_id"].tolist()]
        return pd.Series(list(zip(sub, ag)), index=self.events.index, dtype=object, name="thread")

    @functools.cached_property
    def streams(self) -> list[str]:
        """seq -> stream key ('main' | agent_id | '?'), the key Track A's bracket used."""
        return [stream_key(s, a or None) for s, a in self.threads.tolist()]

    @functools.cached_property
    def clocks(self) -> ClockView:
        ev = self.events
        ts = ev["ts"].tolist()
        ts_ms = np.array([ts_to_ms(_str(v)) for v in ts], dtype=float)
        fds = [ir.frac_digits(t) for t, k in zip(ts, self._kinds) if k in ("call", "result") and not _isna(t)]
        res = (1000.0 if min(fds) == 0 else 10.0 ** (3 - min(fds))) if fds else math.nan
        pms = np.full(len(ev), math.nan)
        fam = np.array([""] * len(ev), dtype=object)
        for i, (rq, mg) in enumerate(zip(ev["request_id"].tolist(), ev["api_msg_id"].tolist())):
            v = _str(rq) or _str(mg)
            if v is None:
                continue
            fam[i] = id_family(v)
            d = decode(v)
            if d is not None:
                pms[i] = d[1]
        return ClockView(ts_ms=ts_ms, ts_kind=np.array([_str(v) or "none" for v in ev["ts_kind"].tolist()], dtype=object),
                         resolution_ms=res, provider_ms=pms, provider_family=fam)

    @functools.cached_property
    def pairs(self) -> pd.DataFrame:
        """One row per call (§3.1)."""
        ev = self.events
        col = {c: ev[c].tolist() for c in ("tool", "tool_raw", "command", "args", "text", "native_error", "exit_code",
                                            "is_subagent")}
        tms = self.clocks.ts_ms
        rows = []
        for key, (cs, rs, n) in self._key_index.items():
            t_c = tms[cs]
            t_r = tms[rs] if rs is not None else math.nan
            rows.append({
                "call_key": key, "call_id": self._call_ids[cs], "call_seq": cs, "result_seq": rs, "n_results": n,
                "tool": _str(col["tool"][cs]), "tool_raw": _str(col["tool_raw"][cs]), "command": _str(col["command"][cs]),
                "args": _str(col["args"][cs]),
                "text": _str(col["text"][rs]) if rs is not None else None,
                "native_error": (None if rs is None or _isna(col["native_error"][rs]) else bool(col["native_error"][rs])),
                "exit_code": (None if rs is None or _isna(col["exit_code"][rs]) else int(col["exit_code"][rs])),
                "t_call_ms": t_c, "t_result_ms": t_r, "latency_ms": t_r - t_c,
                "thread": self.streams[cs], "is_subagent": _truthy(col["is_subagent"][cs]),
            })
        return _typed_frame(rows, PAIRS_DTYPES)

    @functools.cached_property
    def responses(self) -> pd.DataFrame:
        """One row per provider response (§3.1): resp_key = request_id, else api_msg_id; rows carrying neither belong
        to no response. Usage: rows with usage_in not null, deduped on api_msg_id within the response (max usage_out,
        first non-null of the others in seq order), summed over distinct api_msg_ids."""
        ev = self.events
        rq = [_str(v) for v in ev["request_id"].tolist()]
        mg = [_str(v) for v in ev["api_msg_id"].tolist()]
        u = {c: ev[c].tolist() for c in ("usage_in", "usage_out", "usage_cache_read", "usage_cache_create")}
        groups: dict[str, list[int]] = {}
        for i, (r, m) in enumerate(zip(rq, mg)):
            k = r or m
            if k is not None:
                groups.setdefault(k, []).append(i)
        tms = self.clocks.ts_ms
        rows = []
        for k, seqs in groups.items():
            first, last = seqs[0], seqs[-1]
            per_msg: dict[Optional[str], dict[str, Any]] = {}
            for i in seqs:
                if _isna(u["usage_in"][i]):
                    continue
                d = per_msg.setdefault(mg[i], {})
                for c in ("usage_in", "usage_cache_read", "usage_cache_create"):
                    if c not in d and not _isna(u[c][i]):
                        d[c] = int(u[c][i])
                if not _isna(u["usage_out"][i]):
                    d["usage_out"] = max(d.get("usage_out", int(u["usage_out"][i])), int(u["usage_out"][i]))
            usage = {}
            for c in ("usage_in", "usage_out", "usage_cache_read", "usage_cache_create"):
                vals = [d[c] for d in per_msg.values() if c in d]
                usage[c] = sum(vals) if vals else None
            r0 = next((rq[i] for i in seqs if rq[i]), None)
            m0 = next((mg[i] for i in seqs if mg[i]), None)
            dec = decode(r0) if r0 else (decode(m0) if m0 else None)
            rows.append({"resp_key": k, "request_id": r0, "api_msg_id": m0, "first_seq": first, "last_seq": last,
                         "t_first_ms": tms[first], "t_last_ms": tms[last], **usage,
                         "provider_ms": dec[1] if dec else math.nan, "provider_family": dec[0] if dec else "",
                         "stream": self.streams[first],
                         "call_keys": tuple(self.key_of_seq[i] for i in seqs if self._kinds[i] == "call"),
                         "n_rows": len(seqs)})
        rows.sort(key=lambda r: r["first_seq"])
        return _typed_frame(rows, RESPONSES_DTYPES)

    @functools.cached_property
    def id_layout(self) -> dict:
        """layout_report over this session's request ids, plus id_layout_unrecognized (§1.6 consequence 2)."""
        rep = layout_report(self.events["request_id"].dropna().astype(str).tolist())
        rep["id_layout_unrecognized"] = rep["n_shaped"] > 0 and rep["n_decoded"] == 0
        return rep

    # ---- accessors -------------------------------------------------------------------------------------------
    @functools.cached_property
    def _extra_cache(self) -> dict[int, dict]:
        return {}

    def extra(self, seq: int) -> dict:
        """Parsed `extra` JSON of one event; {} when null or invalid. Cached; do not mutate the returned dict."""
        c = self._extra_cache
        if seq not in c:
            c[seq] = _parse_extra(_str(self.events["extra"].iat[seq]))
        return c[seq]

    @functools.cached_property
    def _extra_caps(self) -> dict[str, bool]:
        return {}

    def has_capability(self, name: str) -> bool:
        """Membership in `capabilities`, with 'extra:<dotted.key>' evaluated lazily on the parsed extras."""
        if name in self.capabilities:
            return True
        if name.startswith(EXTRA_CAP_PREFIX):
            c = self._extra_caps
            if name not in c:
                key = name[len(EXTRA_CAP_PREFIX):]
                c[name] = any(_dig(self.extra(s), key) for s in range(len(self.events)))
            return c[name]
        return False

    def ref(self, seq: int, field: Optional[str] = None, role: str = "witness", value: Optional[str] = None) -> EventRef:
        if role not in ROLES:
            raise ValueError(f"role {role!r} not in {ROLES}")
        seq = int(seq)
        if not 0 <= seq < len(self.events):
            raise ValueError(f"seq {seq} not in session {self.session_id} (n={len(self.events)})")
        if value is not None:
            value = str(value)
            if len(value) > MAX_REF_VALUE_CHARS:
                value = value[:MAX_REF_VALUE_CHARS - 1] + "…"
        return EventRef(seq=seq, field=field, role=role, value=value)  # type: ignore[arg-type]

    def call_seq(self, call_key: str) -> int:
        return self._key_index[call_key][0]

    def result_seq(self, call_key: str) -> Optional[int]:
        return self._key_index[call_key][1]

    def call_id_of(self, call_key: str) -> str:
        """Raw IR call_id of a call_key."""
        return self._call_ids[self._key_index[call_key][0]]


def build_session(events: pd.DataFrame, *, unit: str, source: Optional[dict] = None,
                  calibration_unit: Optional[str] = None, turn_ids: Optional[dict] = None,
                  sidecar: Optional[Mapping[str, Any]] = None) -> Session:
    """Validate, sort and wrap ONE session's IR events. ValueError on a frame that is empty, lacks an IR column, holds
    more than one session_id, has seq other than 0..n-1, or fails analysis.lib.ir.validate. Extra columns (e.g. an eval
    pack's `unit`) are dropped."""
    if not isinstance(events, pd.DataFrame):
        raise TypeError(f"build_session expects a DataFrame, got {type(events).__name__}")
    missing = [c for c in ir.COLUMNS if c not in events.columns]
    if missing:
        raise ValueError(f"IR frame lacks columns {missing}")
    if len(events) == 0:
        raise ValueError("empty session: no events")
    df = events[list(ir.COLUMNS)]
    if df["session_id"].isna().any():
        raise ValueError("IR frame has rows with a null session_id")
    sids = sorted(set(df["session_id"].astype(str).tolist()))
    if len(sids) != 1:
        raise ValueError(f"IR frame holds {len(sids)} sessions; pass one session (split_sessions)")
    df = df.sort_values("seq", kind="mergesort").reset_index(drop=True)
    if not np.array_equal(df["seq"].to_numpy(dtype="int64"), np.arange(len(df), dtype="int64")):
        raise ValueError("seq must be exactly 0..n-1 within the session")
    try:
        ir.validate(df)
    except AssertionError as e:
        raise ValueError(f"IR validation failed: {e}") from None
    sc = validate_sidecar(sidecar)
    src = {k: None for k in SOURCE_KEYS}
    src.update(dict(source or {}))
    return Session(corpus=_str(df["corpus"].iat[0]) or "unknown", session_id=sids[0], unit=unit,
                   calibration_unit=calibration_unit, stratum=_str(df["stratum"].iat[0]), events=df,
                   capabilities=detect_capabilities(df, sc), source=src,
                   turn_ids=dict(turn_ids) if turn_ids else None, sidecar=sc)


def split_sessions(df: pd.DataFrame) -> Iterator[pd.DataFrame]:
    """groupby session_id (sorted), each group sorted by seq with a fresh RangeIndex."""
    if df["session_id"].isna().any():
        raise ValueError("IR frame has rows with a null session_id")
    for _, g in df.groupby(df["session_id"].astype(str), sort=True):
        yield g.sort_values("seq", kind="mergesort").reset_index(drop=True)
