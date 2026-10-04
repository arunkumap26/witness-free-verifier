"""Check plugin contract and verdict records (DESIGN.md §3.3, §4.1, §4.5, §4.7).

Holds the `Check` Protocol, the `EventRef` / `CallVerdict` / `Verdict` records, the reason vocabulary and its
machine-checked prefixes, and the constructors that are the only sanctioned way for a check to build a `CallVerdict`
(`supported`, `contradicted`, `unconstrained`, `all_unconstrained`). It also loads frozen calibration files
(`calib_for`) and defines the copied prereg vocabularies (`READ_FIELDS`, `ATTACK_NAMES_DECLARED`).

Imports: stdlib only at module level. `verifier.session` is imported for typing only, so `verifier.session` can import
`EventRef` from here without a cycle.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import (TYPE_CHECKING, Any, ClassVar, Literal, Mapping, Optional, Protocol, Sequence,
                    runtime_checkable)

if TYPE_CHECKING:  # pragma: no cover
    from verifier.session import Session

VERIFIER_VERSION = "0.1.0"

Status = Literal["supported", "contradicted", "unconstrained"]
Strength = Literal["strong", "format", "none"]
STATUSES: tuple[str, ...] = ("supported", "contradicted", "unconstrained")
STRENGTH_RANK: dict[str, int] = {"strong": 2, "format": 1, "none": 0}
CHECK_KINDS: tuple[str, ...] = ("identity", "statistical", "reference")
CHECK_STRENGTHS: tuple[str, ...] = ("strong", "format")
UNIT_KINDS: tuple[str, ...] = ("call", "pair", "response", "stream", "output", "session")
ROLES: tuple[str, ...] = ("subject", "witness", "conflict")
MAX_CORE = 6                      # judgment constant (§3.2): a localized verdict cites at most 6 distinct seqs
MAX_REF_VALUE_CHARS = 200         # EventRef.value is a short rendered value (§3.3)

# Reason vocabulary (§3.3): '<prefix>:<detail>'. The prefix fixes the verdict.
REASON_PREFIXES: dict[str, str] = {
    "ok": "supported",            # the rule constrained the call and it held
    "violation": "contradicted",  # the rule constrained the call and it failed
    "missing": "unconstrained",   # data the rule needs is absent (a capability or this call's field)
    "abstain": "unconstrained",   # data present, but the rule does not decide here
    "error": "unconstrained",     # the check raised or broke the contract (registry-written)
}
REASON_RX = re.compile(r"^(ok|violation|missing|abstain|error):[^\s]+$")
SCREENED_REASON = "abstain:below_threshold"   # a statistical check screened the call and found nothing (§4.6)

# prereg_e.json n7_attack_battery.detector_fields values (union) and the 21 n7_attack_battery.attacks keys.
# Copied, not imported: verifier never imports eval or analysis.probes. tests/test_verifier_core.py checks equality.
READ_FIELDS: frozenset[str] = frozenset({"ts", "order", "request_id", "text", "args", "error", "usage", "events", "tool"})
ATTACK_NAMES_DECLARED: frozenset[str] = frozenset({
    "time_result_early", "time_result_late", "time_tail_late", "time_tail_early", "time_response_early",
    "time_response_late", "id_swap_adjacent", "id_splice_foreign", "sub_single_flip_error", "sub_single_digit",
    "sub_matched_bytes", "rewrite_consistent_k", "reorder_adjacent_pairs", "reorder_lines", "delete_pair",
    "delete_response", "insert_pair_consistent", "insert_pair_squeezed", "inline_fabrication", "image_relabel_gui",
    "image_insert_screenshot"})

# prereg_e.json change_log D1 calibration-unit proxies (DA19: consulted only for quantities a unit's own entry lacks,
# and only those the proxy entry lists in `proxy_ok`).
D1_PROXY_UNIT: dict[str, str] = {"pub_cc_hf": "cc_local", "pub_trace_commons": "cc_local",
                                 "pub_codex": "swechat/codex", "agentcap/opencode": "swechat/opencode"}

REPO_ROOT = Path(__file__).resolve().parents[2]


class ContractError(Exception):
    """A check (or a hand-built record) broke the CallVerdict contract. The registry records it as
    'error:ContractError' and re-raises it under strict=True."""


# --------------------------------------------------------------------------------------------------- records (§3.3)
def _round_floats(o: Any) -> Any:
    if isinstance(o, float):
        return o if not math.isfinite(o) else round(o, 6)
    if isinstance(o, dict):
        return {k: _round_floats(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round_floats(v) for v in o]
    return o


@dataclass(frozen=True)
class EventRef:
    seq: int                                   # IR seq in this session
    field: Optional[str] = None                # IR column or 'extra.<dotted.key>' / 'sidecar.<key>' the evidence reads
    role: Literal["subject", "witness", "conflict"] = "witness"
    value: Optional[str] = None                # short rendered value (<= 200 chars); render redacts before display

    def to_dict(self) -> dict:
        return {"seq": self.seq, "field": self.field, "role": self.role, "value": self.value}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "EventRef":
        return cls(seq=int(d["seq"]), field=d.get("field"), role=d.get("role", "witness"), value=d.get("value"))


@dataclass(frozen=True)
class CallVerdict:                             # one check's verdict on one call
    session_id: str
    call_key: str
    check: str
    check_version: str                         # Check.version + '+' + calib sha[:12] (or 'nocalib')
    verdict: Status
    reason: str
    confidence: Optional[float]
    evidence: tuple[EventRef, ...] = ()
    unit_kind: str = "call"
    unit_id: Optional[str] = None
    localized: bool = True
    strength: Strength = "none"
    detail: Optional[dict] = None

    def to_dict(self) -> dict:
        return _round_floats({"session_id": self.session_id, "call_key": self.call_key, "check": self.check,
                              "check_version": self.check_version, "verdict": self.verdict, "reason": self.reason,
                              "confidence": self.confidence, "evidence": [e.to_dict() for e in self.evidence],
                              "unit_kind": self.unit_kind, "unit_id": self.unit_id, "localized": self.localized,
                              "strength": self.strength, "detail": self.detail})

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "CallVerdict":
        return cls(session_id=d["session_id"], call_key=d["call_key"], check=d["check"],
                   check_version=d["check_version"], verdict=d["verdict"], reason=d["reason"],
                   confidence=d.get("confidence"), evidence=tuple(EventRef.from_dict(e) for e in d.get("evidence", ())),
                   unit_kind=d.get("unit_kind", "call"), unit_id=d.get("unit_id"), localized=bool(d.get("localized", True)),
                   strength=d.get("strength", "none"), detail=d.get("detail"))


@dataclass(frozen=True)
class Verdict:                                 # composed per call (compose.py)
    session_id: str
    call_id: str                               # raw IR call_id (join key; SCOPE 'call_id')
    call_key: str                              # unique within the session (§3.2)
    seq: int                                   # call event seq
    result_seq: Optional[int]
    tool: Optional[str]
    verdict: Status
    strength: Strength
    confidence: Optional[float]
    rule: Optional[str]                        # deciding check name; None if unconstrained
    reason: str
    core: tuple[int, ...]                      # seqs of the deciding evidence
    blame_seq: Optional[int]
    localized: bool
    disagreement: bool
    detail: Optional[dict]
    checks: tuple[CallVerdict, ...]            # every check's verdict on this call, sorted by check name
    version: str                               # 'verifier/<v> ir/<sha12> checks/<checkset_sha12>'

    def to_scope_dict(self, turn_ids: Mapping[int, str] | None = None) -> dict:
        """SCOPE.md §3 verdict: {session_id, call_id, tool, verdict, strength, tiers, core, rule, detail}."""
        if turn_ids:
            core = [turn_ids.get(s, f"seq:{s}") for s in self.core]
        else:
            core = [f"seq:{s}" for s in self.core]
        return {"session_id": self.session_id, "call_id": self.call_id, "tool": self.tool, "verdict": self.verdict,
                "strength": self.strength, "tiers": [cv.check for cv in self.checks if cv.verdict != "unconstrained"],
                "core": core, "rule": self.rule, "detail": self.detail}

    def to_dict(self) -> dict:
        """verdicts.jsonl row: fixed key order (dataclass field order), floats rounded to 6 places."""
        d = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        d["core"] = list(self.core)
        d["checks"] = [cv.to_dict() for cv in self.checks]
        return _round_floats(d)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Verdict":
        kw = {f.name: d.get(f.name) for f in dataclasses.fields(cls)}
        kw["core"] = tuple(int(s) for s in d.get("core") or ())
        kw["checks"] = tuple(CallVerdict.from_dict(c) for c in d.get("checks") or ())
        kw["localized"] = bool(d.get("localized", True))
        kw["disagreement"] = bool(d.get("disagreement", False))
        return cls(**kw)


# ------------------------------------------------------------------------------------------------- Protocol (§4.1)
@runtime_checkable
class Check(Protocol):
    name: ClassVar[str]                          # unique snake_case, stable across versions
    version: ClassVar[str]                       # semver; bump on ANY logic or threshold change
    kind: ClassVar[Literal["identity", "statistical", "reference"]]
    strength: ClassVar[Literal["strong", "format"]]
    requires: ClassVar[frozenset[str]]           # capability names (§4.3)
    reads: ClassVar[frozenset[str]]              # subset of READ_FIELDS
    targets: ClassVar[frozenset[str]]            # subset of ATTACK_NAMES_DECLARED
    unit_kind: ClassVar[str]                     # call | pair | response | stream | output | session
    calibration: ClassVar[Optional[str]]         # 'verifier/checks/calib/<name>.json'; None only for reference checks

    def applicable(self, session: "Session") -> bool:
        """Cheap. Called only when requires ⊆ session capabilities."""
        ...

    def run(self, session: "Session") -> list[CallVerdict]:
        """Pure; at most one CallVerdict per call_key; omitted calls become 'abstain:not_decided'."""
        ...

    def explain(self, cv: CallVerdict) -> str:
        """One plain-English sentence built only from cv.reason / cv.detail / cv.evidence."""
        ...


# ---------------------------------------------------------------------------------------------- calibration (§4.7)
def _calib_path(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else REPO_ROOT / p


@functools.lru_cache(maxsize=None)
def _load_calib_file(path: str) -> tuple[Optional[dict], Optional[str]]:
    p = Path(path)
    if not p.is_file():
        return None, None
    b = p.read_bytes().replace(b"\r\n", b"\n")
    return json.loads(b.decode("utf-8")), hashlib.sha256(b).hexdigest()


def load_calibration(check: Any) -> tuple[Optional[dict], Optional[str]]:
    """(parsed calibration JSON, LF-normalised sha256) for a check class or instance; (None, None) when the check has no
    calibration file (reference checks) or the file is not built yet."""
    rel = getattr(check, "calibration", None)
    if not rel:
        return None, None
    return _load_calib_file(str(_calib_path(rel)))


def check_version(check: Any) -> str:
    _, sha = load_calibration(check)
    return f"{check.version}+{sha[:12] if sha else 'nocalib'}"


def calib_for(check: Any, unit: Optional[str], stratum: Optional[str] = None) -> Optional[dict]:
    """Frozen calibration slice for a calibration unit (DA19 lookup order):
    units['<unit>/<stratum>'] if present, else units[unit]; quantities that entry lacks are filled from the D1 proxy
    unit's entry, but only those the proxy entry lists in `proxy_ok`. None when nothing applies.
    The returned dict is a copy; `_borrowed` lists quantities taken from the proxy, `_unit_key` the entry used."""
    if unit is None:
        return None
    cal, _ = load_calibration(check)
    if not cal:
        return None
    units = cal.get("units") or {}
    own_key = f"{unit}/{stratum}" if stratum and f"{unit}/{stratum}" in units else (unit if unit in units else None)
    entry: dict = dict(units[own_key]) if own_key else {}
    borrowed: list[str] = []
    proxy = D1_PROXY_UNIT.get(unit)
    if proxy and proxy in units:
        pe = units[proxy]
        for q in sorted(pe.get("proxy_ok") or ()):
            if q not in entry and q in pe:
                entry[q] = pe[q]
                borrowed.append(q)
    if not entry:
        return None
    entry["_unit_key"] = own_key
    entry["_borrowed"] = borrowed
    if borrowed:
        entry["_borrowed_from"] = proxy
    return entry


# --------------------------------------------------------------------------------------------- constructors (§4.1)
def reason_status(reason: str) -> Optional[str]:
    """Verdict a reason implies, from its prefix; None if the reason is malformed."""
    if not isinstance(reason, str) or not REASON_RX.match(reason):
        return None
    return REASON_PREFIXES.get(reason.split(":", 1)[0])


def _cls(check: Any) -> Any:
    return check if isinstance(check, type) else type(check)


def _json_safe(detail: Any) -> None:
    if detail is None:
        return
    if not isinstance(detail, dict):
        raise ContractError(f"detail must be a dict or None, got {type(detail).__name__}")
    try:
        json.dumps(detail, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise ContractError(f"detail is not JSON-safe: {e}") from None


def _n_events(s: Any) -> int:
    return len(s.events)


def validate_call_verdict(cv: CallVerdict, session: Any, check: Any, *, call_keys: Optional[frozenset] = None) -> None:
    """Every invariant a CallVerdict must satisfy (§4.1). Raises ContractError. Used by the constructors and again by
    the registry on whatever a check returns."""
    c = _cls(check)
    if not isinstance(cv, CallVerdict):
        raise ContractError(f"{c.name}: run() returned {type(cv).__name__}, not CallVerdict")
    if cv.check != c.name:
        raise ContractError(f"{c.name}: CallVerdict.check is {cv.check!r}")
    if cv.check_version != check_version(c):
        raise ContractError(f"{c.name}: check_version {cv.check_version!r} != {check_version(c)!r}")
    if cv.session_id != session.session_id:
        raise ContractError(f"{c.name}: session_id {cv.session_id!r} != {session.session_id!r}")
    keys = call_keys if call_keys is not None else getattr(session, "call_key_set", None)
    if keys is None:
        keys = set(session.call_keys)
    if cv.call_key not in keys:
        raise ContractError(f"{c.name}: unknown call_key {cv.call_key!r}")
    if cv.verdict not in STATUSES:
        raise ContractError(f"{c.name}: verdict {cv.verdict!r}")
    st = reason_status(cv.reason)
    if st is None:
        raise ContractError(f"{c.name}: malformed reason {cv.reason!r}")
    if st != cv.verdict:
        raise ContractError(f"{c.name}: reason {cv.reason!r} implies {st}, verdict is {cv.verdict}")
    if cv.unit_kind not in UNIT_KINDS:
        raise ContractError(f"{c.name}: unit_kind {cv.unit_kind!r}")
    _json_safe(cv.detail)
    n = _n_events(session)
    for r in cv.evidence:
        if not isinstance(r, EventRef):
            raise ContractError(f"{c.name}: evidence item {type(r).__name__} is not EventRef")
        if not (isinstance(r.seq, int) and 0 <= r.seq < n):
            raise ContractError(f"{c.name}: evidence seq {r.seq!r} not in session (n={n})")
        if r.role not in ROLES:
            raise ContractError(f"{c.name}: evidence role {r.role!r}")
        if r.value is not None and (not isinstance(r.value, str) or len(r.value) > MAX_REF_VALUE_CHARS):
            raise ContractError(f"{c.name}: evidence value must be a str of <= {MAX_REF_VALUE_CHARS} chars")
    if cv.verdict == "unconstrained":
        if cv.evidence:
            raise ContractError(f"{c.name}: unconstrained verdict carries evidence")
        if cv.confidence is not None:
            raise ContractError(f"{c.name}: unconstrained verdict carries a confidence")
        if cv.strength != "none":
            raise ContractError(f"{c.name}: unconstrained verdict has strength {cv.strength!r}")
        return
    if not cv.evidence or not any(r.role == "subject" for r in cv.evidence):
        raise ContractError(f"{c.name}: decided verdict needs evidence with a role='subject' ref")
    if cv.confidence is not None and not (isinstance(cv.confidence, (int, float)) and 0.0 <= cv.confidence <= 1.0):
        raise ContractError(f"{c.name}: confidence {cv.confidence!r} not in [0, 1]")
    if cv.strength not in CHECK_STRENGTHS or STRENGTH_RANK[cv.strength] > STRENGTH_RANK[c.strength]:
        raise ContractError(f"{c.name}: strength {cv.strength!r} may only lower class strength {c.strength!r} (DA18)")
    if cv.localized and len({r.seq for r in cv.evidence}) > MAX_CORE:
        raise ContractError(f"{c.name}: localized verdict cites > {MAX_CORE} distinct seqs (§3.2)")
    if cv.verdict == "supported" and c.kind == "statistical":
        raise ContractError(f"{c.name}: statistical checks never emit supported (§4.6)")


def _decided(verdict: str, s: "Session", call_key: str, check: Any, reason: str, evidence: Sequence[EventRef], *,
             confidence: Optional[float], unit_kind: str, unit_id: Optional[str], localized: bool,
             detail: Optional[dict], strength: Optional[str]) -> CallVerdict:
    c = _cls(check)
    cv = CallVerdict(session_id=s.session_id, call_key=call_key, check=c.name, check_version=check_version(c),
                     verdict=verdict, reason=reason, confidence=None if confidence is None else float(confidence),
                     evidence=tuple(evidence), unit_kind=unit_kind, unit_id=unit_id, localized=bool(localized),
                     strength=strength or c.strength, detail=detail)
    validate_call_verdict(cv, s, c)
    return cv


def supported(s: "Session", call_key: str, check: Any, reason: str, evidence: Sequence[EventRef], *,
              confidence: Optional[float], unit_kind: str = "call", unit_id: Optional[str] = None,
              localized: bool = True, detail: Optional[dict] = None, strength: Optional[Strength] = None) -> CallVerdict:
    if _cls(check).kind == "statistical":
        raise ContractError(f"{_cls(check).name}: statistical checks never emit supported (§4.6)")
    return _decided("supported", s, call_key, check, reason, evidence, confidence=confidence, unit_kind=unit_kind,
                    unit_id=unit_id, localized=localized, detail=detail, strength=strength)


def contradicted(s: "Session", call_key: str, check: Any, reason: str, evidence: Sequence[EventRef], *,
                 confidence: Optional[float], unit_kind: str = "call", unit_id: Optional[str] = None,
                 localized: bool = True, detail: Optional[dict] = None,
                 strength: Optional[Strength] = None) -> CallVerdict:
    return _decided("contradicted", s, call_key, check, reason, evidence, confidence=confidence, unit_kind=unit_kind,
                    unit_id=unit_id, localized=localized, detail=detail, strength=strength)


def unconstrained(s: "Session", call_key: str, check: Any, reason: str, detail: Optional[dict] = None) -> CallVerdict:
    c = _cls(check)
    cv = CallVerdict(session_id=s.session_id, call_key=call_key, check=c.name, check_version=check_version(c),
                     verdict="unconstrained", reason=reason, confidence=None, evidence=(), detail=detail)
    validate_call_verdict(cv, s, c)
    return cv


def all_unconstrained(s: "Session", check: Any, reason: str, detail: Optional[dict] = None) -> list[CallVerdict]:
    return [unconstrained(s, k, check, reason, detail) for k in s.call_keys]


def verdict_version(checkset_sha: str) -> str:
    """'verifier/<__version__> ir/<IR_SCHEMA_SHA[:12]> checks/<checkset_sha[:12]>' (§3.3)."""
    from verifier.ir import IR_SCHEMA_SHA12
    return f"verifier/{VERIFIER_VERSION} ir/{IR_SCHEMA_SHA12} checks/{checkset_sha[:12]}"


def checkset_sha(check_versions: Mapping[str, str]) -> str:
    """sha256('\\n'.join(sorted(f'{check}@{check_version}'))) over the checks run (§3.3)."""
    return hashlib.sha256("\n".join(sorted(f"{k}@{v}" for k, v in check_versions.items())).encode()).hexdigest()
