"""verifier: witness-free verification of agent tool-log results (DESIGN.md).

From a transcript alone, every tool call gets `supported` / `contradicted` / `unconstrained` plus the deciding
evidence. No narration, no LLM, no external witness. `supported` means consistent with the fields the deciding check
reads, nothing more (§1.4).

Public API (§2.6; SCOPE.md §3 contract `verify_session(turns) -> list[Verdict]`):
    verify_session(turns_or_events, *, unit=None, calibration_unit=None, checks=None, source=None, sidecar=None,
                   strict=False) -> list[Verdict]
    verify_sessions(events, *, unit_of, calibration_unit_of, sidecar_of=..., checks=None, strict=False)
        -> Iterator[tuple[Session, list[Verdict]]]
    verify_file(path, *, fmt='auto', unit=None, checks=None, strict=False) -> list[tuple[Session, list[Verdict]]]

DESIGN.md places these in `verifier/api.py`; the scaffold assignment puts them here. Import isolation (§5.1): this
module imports only verifier.ir, verifier.session, verifier.checks.base, verifier.registry and verifier.compose at
module level. `verifier.loaders` / `verifier.render` (which pull in analysis.loaders) are imported only inside
`verify_file`, never on the `verify_session` path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence, Union

import pandas as pd

from verifier.checks.base import VERIFIER_VERSION, CallVerdict, EventRef, Verdict
from verifier import compose as _compose  # keep `verifier.compose` bound to the module
from verifier.registry import ENABLED_CHECKS, RunStats, kinds_of, resolve_names, run_checks
from verifier.session import Session, build_session, split_sessions

__version__ = VERIFIER_VERSION

BUILTIN_FORMATS = ("ir", "turns")


def run_session(session: Session, checks: Union[None, str, Sequence[str]] = None, *, strict: bool = False
                ) -> tuple[list[Verdict], RunStats]:
    """Run checks on a built Session and compose. Returns (verdicts, run stats) for callers that report check status."""
    stats = RunStats()
    by_check = run_checks(session, checks, strict=strict, stats=stats)
    return _compose.compose(session, by_check, kinds_of(by_check)), stats


def verify_session(turns_or_events: Union[list, pd.DataFrame], *, unit: Optional[str] = None,
                   calibration_unit: Optional[str] = None, checks: Optional[Sequence[str]] = None,
                   source: Optional[dict] = None, sidecar: Optional[Mapping[str, object]] = None,
                   strict: bool = False) -> list[Verdict]:
    """SCOPE §3 contract. list[dict] = SCOPE `turn` dicts of ONE session (turns_to_events); DataFrame = IR events of ONE
    session (IR COLUMNS; ValueError if it holds >1 session_id). unit defaults to 'turns' for turns and 'unknown' for
    frames. calibration_unit defaults to None, so statistical checks abstain (DA4) unless the caller names one.
    sidecar: harness records the IR drops (§2.7), validated; None = {}. checks=None runs ENABLED_CHECKS.
    Returns one Verdict per call in call seq order ([] if no calls)."""
    session = _session_from_input(turns_or_events, unit=unit, calibration_unit=calibration_unit, source=source,
                                  sidecar=sidecar)
    return run_session(session, checks, strict=strict)[0]


def _session_from_input(turns_or_events: Union[list, pd.DataFrame], *, unit: Optional[str],
                        calibration_unit: Optional[str], source: Optional[dict],
                        sidecar: Optional[Mapping[str, object]]) -> Session:
    if isinstance(turns_or_events, pd.DataFrame):
        return build_session(turns_or_events, unit=unit or "unknown", calibration_unit=calibration_unit,
                             source={"format": "ir", **(source or {})}, sidecar=sidecar)
    if isinstance(turns_or_events, (list, tuple)):
        from verifier.ir.turns import turns_to_events
        df, turn_ids, unmapped = turns_to_events(turns_or_events)
        return build_session(df, unit=unit or "turns", calibration_unit=calibration_unit,
                             source={"format": "turns", "unmapped": unmapped, **(source or {})},
                             turn_ids=turn_ids, sidecar=sidecar)
    raise TypeError(f"verify_session expects list[dict] (turns) or an IR DataFrame, got {type(turns_or_events).__name__}")


def verify_sessions(events: pd.DataFrame, *, unit_of: Callable[[str], str],
                    calibration_unit_of: Callable[[str], Optional[str]],
                    sidecar_of: Callable[[str], Optional[Mapping[str, object]]] = lambda sid: None,
                    checks: Optional[Sequence[str]] = None, strict: bool = False
                    ) -> Iterator[tuple[Session, list[Verdict]]]:
    """Multi-session IR frame -> (Session, verdicts) per session, sorted by session_id."""
    names = resolve_names(checks)
    for df in split_sessions(events):
        sid = str(df["session_id"].iat[0])
        s = build_session(df, unit=unit_of(sid), calibration_unit=calibration_unit_of(sid), source={"format": "ir"},
                          sidecar=sidecar_of(sid))
        yield s, run_session(s, names, strict=strict)[0]


# ------------------------------------------------------------------------------------------------ file input (CLI)
def refuse_heldout_path(path: Union[str, Path]) -> None:
    """The verifier has no notion of a held-out split: refuse any input whose file name marks one ('_H' followed by a
    non-alphanumeric or the end, as in '<corpus>_H.<ext>'; or 'heldout' / 'held-out'), the guard of
    prereg_e_common.read_cache narrowed so a name like 'my_HELPER.jsonl' still loads."""
    name = Path(path).name
    if re.search(r"_H(?![A-Za-z0-9])", name) or re.search(r"held.?out", name, re.I):
        raise PermissionError(f"refusing {name}: held-out inputs are read only by the eval's --final path (DESIGN §5.2)")


def sniff_builtin(path: Union[str, Path]) -> Optional[str]:
    """'ir' for a parquet with every IR column, 'turns' for a .jsonl/.json of SCOPE turn dicts, else None."""
    p = Path(path)
    if p.suffix == ".parquet":
        import pyarrow.parquet as pq
        from verifier.ir import COLUMNS
        names = set(pq.read_schema(p).names)
        return "ir" if set(COLUMNS) <= names else None
    if p.suffix in (".jsonl", ".json"):
        with p.open(encoding="utf-8") as f:
            head = f.read(65536).lstrip()
        first: Any = None
        try:
            if p.suffix == ".jsonl" or not head.startswith("["):
                first = json.loads(head.splitlines()[0]) if head else None
            else:
                first = (json.loads(p.read_text(encoding="utf-8")) or [None])[0]
        except (ValueError, IndexError):
            return None
        if isinstance(first, dict) and "role" in first and "turn_number" in first:
            return "turns"
    return None


def read_turns(path: Union[str, Path]) -> list[dict]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        return list(json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_builtin(path: Union[str, Path], fmt: str, *, session_id: Optional[str] = None) -> list[dict]:
    """Built-in readers for the two formats the verifier defines itself (IR parquet, SCOPE turns). Returns a list of
    {'events', 'turn_ids', 'source'} per session."""
    p = Path(path)
    if fmt == "ir":
        filters = [("session_id", "==", session_id)] if session_id else None
        df = pd.read_parquet(p, filters=filters)
        if len(df) == 0:
            raise ValueError(f"{p.name}: no IR rows" + (f" for session {session_id}" if session_id else ""))
        return [{"events": g, "turn_ids": None, "source": {"path": str(p), "format": "ir", "loader": "verifier.builtin"}}
                for g in split_sessions(df)]
    if fmt == "turns":
        from verifier.ir.turns import turns_to_events
        turns = read_turns(p)
        by_sid: dict[str, list[dict]] = {}
        for t in turns:
            by_sid.setdefault(str(t.get("session_id")), []).append(t)
        out = []
        for sid in sorted(by_sid):
            if session_id and sid != session_id:
                continue
            df, turn_ids, unmapped = turns_to_events(by_sid[sid])
            out.append({"events": df, "turn_ids": turn_ids,
                        "source": {"path": str(p), "format": "turns", "loader": "verifier.builtin", "unmapped": unmapped}})
        if not out:
            raise ValueError(f"{p.name}: no turns" + (f" for session {session_id}" if session_id else ""))
        return out
    raise ValueError(f"format {fmt!r} is not built in")


def load_sessions(path: Union[str, Path], *, fmt: str = "auto", unit: Optional[str] = None,
                  session_id: Optional[str] = None, sidecar: Optional[Mapping[str, object]] = None
                  ) -> list[tuple[Session, bool]]:
    """Path -> [(Session, calibration_borrowed)].

    When verifier.loaders exists, every format goes through `verifier.loaders.files.load_file` (Phase E units for IR
    rows of known corpora, calibration borrowed by format for raw transcripts, cc_numlines read from a Claude Code
    JSONL); `unit` overrides the calibration unit. Without it (the DA1 fallback, loaders not merged), only the two
    formats the verifier defines itself are readable here: IR parquet (unit = its corpus) and SCOPE turns (unit
    'turns'). Held-out file names are refused either way."""
    refuse_heldout_path(path)
    try:
        from verifier.loaders import files as _files  # type: ignore
    except ImportError:
        _files = None
    if _files is not None:
        sessions = _files.load_file(path, fmt, calibration_unit=unit, session=session_id, sidecar=sidecar)
        return [(s, unit is None and s.calibration_unit is not None and s.calibration_unit != s.unit) for s in sessions]
    fmt_used = sniff_builtin(path) if fmt == "auto" else fmt
    if fmt_used not in BUILTIN_FORMATS:
        raise ValueError(f"{Path(path).name}: format {fmt_used or 'unrecognized'!r} needs verifier.loaders, which is "
                         f"not available; built in: {', '.join(BUILTIN_FORMATS)}")
    out: list[tuple[Session, bool]] = []
    for item in load_builtin(path, fmt_used, session_id=session_id):
        ev = item["events"]
        u = str(ev["corpus"].iat[0]) if fmt_used == "ir" else "turns"
        out.append((build_session(ev, unit=u, calibration_unit=unit, source=item["source"], turn_ids=item["turn_ids"],
                                  sidecar=sidecar), False))
    return out


def verify_file(path: Union[str, Path], *, fmt: str = "auto", unit: Optional[str] = None,
                checks: Optional[Sequence[str]] = None, strict: bool = False) -> list[tuple[Session, list[Verdict]]]:
    """CLI path: one transcript file -> [(Session, verdicts)]. Borrows calibration by format (§4.5) unless `unit`."""
    return [(s, run_session(s, checks, strict=strict)[0]) for s, _ in load_sessions(path, fmt=fmt, unit=unit)]


__all__ = ["verify_session", "verify_sessions", "verify_file", "run_session", "load_sessions", "Verdict",
           "CallVerdict", "EventRef", "Session", "ENABLED_CHECKS", "__version__"]
