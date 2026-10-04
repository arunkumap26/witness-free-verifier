"""Raw-file entry point: one transcript file -> IR -> `Session`s (DESIGN.md §2.5, §6.1).

This is the CLI path for an arbitrary transcript: `python -m verifier verify PATH` calls `load_file(PATH)`.

Formats (detect.py decides 'auto'):
  claude_code, codex, opencode, gemini, cursor, copilot, simple_text
            one file = one session, session_id = file stem (as swechat names its transcripts). Parsed by the swechat
            loader exactly as it built the caches: `load_swechat.parse_session(sid, fmt, None, ctx, path)` with an
            empty cross-session ctx ({"opencode_task": {}, "codex_spawn": {}}), which runs `PARSERS[fmt]` (Claude
            Code via `analysis.lib.cc_jsonl.Parser`) and the usage-id safety net, then the same surrogate clean-up the
            cache writer applies. A Claude Code JSONL or a Codex rollout (`~/.codex/sessions/.../rollout-*.jsonl`)
            loads this way.
  atif      one Harbor ATIF `trajectory.json` = one session, through `load_tbench2.parse_session` (ATIF branch: the
            same parse_atif, trial result.json when it sits in the Harbor layout <trial>/agent/<file>, credential
            redaction). In that layout the session id is the trial directory name, not the shared stem.
  ir        a parquet file with exactly the IR COLUMNS; one session per session_id (sorted). The corpus column is
            kept as Session.corpus, so a private corpus (cc_local) stays private downstream.
  turns     JSONL of SCOPE.md §3 turn dicts, one session per session_id (rows without one use the file stem), through
            `verifier.ir.turns.turns_to_events`.

Units and calibration (§4.5): raw formats get unit 'file/<fmt>' and borrow calibration by format
(units.DEFAULT_CALIBRATION_BY_FORMAT); `calibration_unit=` overrides. IR rows of a known corpus get that corpus's
Phase E unit and calibrate as it (or its D1 proxy). Turns calibrate as nothing unless told.

Sidecar (§2.7): a Claude Code JSONL fills `cc_numlines` from the same file; `sidecar=` adds or overrides keys
(validated by `verifier.session.sidecar.validate_sidecar` inside `build_session`).

Errors: every input problem (missing file, unknown or empty format, parser failure, a session with no events, a
`session=` filter that matches nothing) raises `LoadError` (a ValueError); the CLI maps it to exit code 2.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import pandas as pd

from verifier.ir import COLUMNS, to_frame, validate
from verifier.loaders import units as U
from verifier.loaders.detect import FILE_FORMATS, SWECHAT_PARSED, sniff

LOADER_SWECHAT = "analysis/loaders/load_swechat.py"
LOADER_TBENCH2 = "analysis/loaders/load_tbench2.py"
LOADER_TURNS = "verifier/ir/turns.py"
LOADER_IR = "verifier/loaders/files.py"

_HELD_NAME = re.compile(r"held.?out", re.I)


class LoadError(ValueError):
    """An input the loaders cannot turn into at least one non-empty session (CLI exit code 2)."""


@dataclass
class LoadedSession:
    """One session's IR plus everything `build_session` needs; produced without importing verifier.session."""
    events: pd.DataFrame                 # exactly COLUMNS, seq 0..n-1, RangeIndex, validated
    corpus: str                          # 'file' | 'turns' | the IR corpus value
    unit: str
    calibration_unit: str | None
    fmt: str
    source: dict                         # {'path', 'format', 'loader', 'loader_sha256', 'split'}
    turn_ids: dict[int, str] | None = None
    sidecar: dict = field(default_factory=dict)
    stat: dict = field(default_factory=dict)   # parser counters (bad_lines, salvaged lines, ...), for the header

    @property
    def session_id(self) -> str:
        return str(self.events["session_id"].iat[0])

    @property
    def calibration_borrowed(self) -> bool:
        return self.calibration_unit is not None and self.calibration_unit != self.unit


def _sha(loader: str | None) -> str | None:
    if loader is None:
        return None
    from verifier.loaders.corpora import file_sha256_lf

    return file_sha256_lf(loader)


def _source(path: Path, fmt: str, loader: str | None) -> dict:
    return {"path": str(path), "format": fmt, "loader": loader, "loader_sha256": _sha(loader), "split": None}


def _finish(events: list[dict]) -> pd.DataFrame:
    """IR dicts -> typed, surrogate-clean, validated frame (the cache writers' sequence)."""
    from analysis.loaders import load_swechat as lsw

    df = to_frame(events)
    lsw._sanitize_surrogates(df)  # lone UTF-16 surrogates -> U+FFFD, as every cache writer does
    try:
        validate(df)
    except AssertionError as ex:
        raise LoadError(f"IR validation failed: {ex}") from None
    return df


# --------------------------------------------------------------------------------------------- per-format readers
def read_swechat_format(path: Path, fmt: str, session_id: str) -> tuple[pd.DataFrame, dict]:
    """One transcript in a swechat-parsed format -> (IR frame, parser stat). corpus = 'file', stratum = None."""
    from analysis.loaders import load_swechat as lsw

    ctx = {"opencode_task": {}, "codex_spawn": {}}
    events, stat, _ = lsw.parse_session(session_id, fmt, None, ctx, str(path))
    stat = {k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v)) for k, v in stat.items()}
    if stat.get("exception"):
        raise LoadError(f"{fmt} parser failed on {path.name}: {stat['exception']}")
    if not events:
        raise LoadError(f"empty session: {path.name} parsed as {fmt} has no events")
    for e in events:
        e["corpus"] = "file"
    return _finish(events), stat


def read_atif(path: Path, session_id: str) -> tuple[pd.DataFrame, dict]:
    """One ATIF trajectory -> (IR frame, parser counters), through load_tbench2.parse_session's ATIF branch."""
    from analysis.loaders import load_tbench2 as T

    p = path.resolve()
    if p.parent.name == "agent" and (p.parent.parent / "result.json").is_file():
        tdir, rel = p.parent.parent, f"agent/{p.name}"   # Harbor layout: <trial>/agent/trajectory.json + result.json
    else:
        tdir, rel = p.parent, p.name
    row = {"session_id": session_id, "stratum": None, "submission": None, "job": None, "trial": tdir.name,
           "format": "atif", "files": json.dumps([rel])}
    try:
        events, cnt = T.parse_session(row, data_root=str(tdir.parent), corpus="file")
    except Exception as ex:  # noqa: BLE001  any parser failure is an input error for one file
        raise LoadError(f"atif parser failed on {path.name}: {type(ex).__name__}: {str(ex)[:200]}") from None
    if not events:
        raise LoadError(f"empty session: {path.name} parsed as atif has no events")
    return _finish(events), dict(cnt)


def read_ir_parquet(path: Path, session: str | None = None) -> list[pd.DataFrame]:
    """IR parquet -> one validated frame per session_id (sorted). Refuses held-out-looking paths."""
    import pyarrow.parquet as pq

    from verifier.loaders.corpora import _typed

    if "_H" in path.name or _HELD_NAME.search(str(path)) or path.parent.name == "H":
        raise LoadError(f"refusing {path}: looks like the held-out split (the verifier never reads it)")
    names = pq.read_schema(path).names
    if list(names) != list(COLUMNS):
        raise LoadError(f"{path.name}: parquet columns are not exactly the IR COLUMNS")
    filters = [("session_id", "==", str(session))] if session is not None else None
    df = _typed(pq.read_table(path, columns=list(COLUMNS), filters=filters).to_pandas())
    out = []
    for _, g in df.groupby(df["session_id"].astype(str), sort=True):
        ev = g.sort_values("seq", kind="stable").reset_index(drop=True)
        try:
            validate(ev)
        except AssertionError as ex:
            raise LoadError(f"{path.name}: session {ev['session_id'].iat[0]} fails IR validation: {ex}") from None
        out.append(ev)
    return out


def read_turns(path: Path, session: str | None = None) -> list[tuple[pd.DataFrame, dict[int, str], int]]:
    """Turns JSONL -> [(IR frame, {seq: turn_id}, n_unmapped)] per session_id (sorted)."""
    from verifier.ir.turns import turns_to_events

    by_sid: dict[str, list[dict]] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                raise LoadError(f"{path.name}:{n}: not a JSON object") from None
            if not isinstance(r, dict):
                raise LoadError(f"{path.name}:{n}: not a JSON object")
            sid = r.get("session_id")
            sid = path.stem if sid is None or sid == "" else str(sid)
            r = dict(r, session_id=sid)
            by_sid.setdefault(sid, []).append(r)
    out = []
    for sid in sorted(by_sid):
        if session is not None and sid != str(session):
            continue
        try:
            df, turn_ids, unmapped = turns_to_events(by_sid[sid])
        except (ValueError, AssertionError) as ex:
            raise LoadError(f"{path.name}: session {sid}: {ex}") from None
        out.append((df, turn_ids, unmapped))
    return out


# ------------------------------------------------------------------------------------------------------ dispatch
def session_id_for_file(path: Path, fmt: str) -> str:
    """The file stem (DESIGN.md §6.1: one file = one session, named as swechat names its transcripts). Exception: an
    ATIF file in the Harbor layout (<trial>/agent/trajectory.json) is named after its trial directory, because every
    such file has the same stem; this is the trial part of a tbench2 / glm_tb21 session id."""
    p = Path(path)
    if fmt == "atif" and p.parent.name == "agent" and (p.parent.parent / "result.json").is_file():
        return p.parent.parent.name
    return p.stem


def load_events(path: str | Path, fmt: str = "auto", *, calibration_unit: str | None = None,
                session: str | None = None, sidecar: Mapping[str, object] | None = None) -> list[LoadedSession]:
    """One input file -> its sessions' IR and metadata (no verifier.session import). See module docstring."""
    p = Path(path)
    if not p.exists():
        raise LoadError(f"no such file: {p}")
    if p.is_dir():
        raise LoadError(f"{p} is a directory; directory input is not supported in this build (one file = one input)")
    if fmt == "auto":
        fmt = sniff(p)
    if fmt not in FILE_FORMATS:
        raise LoadError(f"{p.name}: unrecognized input format ({fmt}); use --format "
                        f"{{{','.join(f for f in FILE_FORMATS)}}}")
    user_sc = dict(sidecar or {})
    out: list[LoadedSession] = []
    if fmt in SWECHAT_PARSED or fmt == "atif":
        sid = session_id_for_file(p, fmt)
        if session is not None and str(session) != sid:
            raise LoadError(f"session {session} is not in {p.name} (its one session is {sid})")
        if fmt == "atif":
            ev, stat = read_atif(p, sid)
            loader = LOADER_TBENCH2
        else:
            ev, stat = read_swechat_format(p, fmt, sid)
            loader = LOADER_SWECHAT
        sc = {}
        if fmt == "claude_code":
            from verifier.loaders.sidecar import read_cc_numlines

            sc["cc_numlines"] = read_cc_numlines(p)
        sc.update(user_sc)
        out.append(LoadedSession(events=ev, corpus="file", unit=U.unit_of("file", sid, None, fmt),
                                 calibration_unit=calibration_unit or U.calibration_unit_for_file(fmt), fmt=fmt,
                                 source=_source(p, fmt, loader), sidecar=sc, stat=stat))
    elif fmt == "ir":
        from verifier.loaders.corpora import CORPUS_ADAPTERS

        frames = read_ir_parquet(p, session)
        corpus_of = [str(ev["corpus"].iat[0]) if pd.notna(ev["corpus"].iat[0]) else "file" for ev in frames]
        sw_fmt = U.swechat_formats(str(ev["session_id"].iat[0]) for ev, c in zip(frames, corpus_of) if c == "swechat")
        for ev, corpus in zip(frames, corpus_of):
            sid = str(ev["session_id"].iat[0])
            stratum = None if pd.isna(ev["stratum"].iat[0]) else str(ev["stratum"].iat[0])
            if corpus in CORPUS_ADAPTERS:
                unit = U.unit_of(corpus, sid, stratum, sw_fmt.get(sid) if corpus == "swechat" else None)
                calib = calibration_unit or U.calibration_unit_for_corpus_unit(unit)
                loader = CORPUS_ADAPTERS[corpus].loader
            elif corpus == "turns":
                unit, calib, loader = "turns", calibration_unit, LOADER_TURNS
            else:
                unit, calib, loader = "file/ir", calibration_unit, None
            out.append(LoadedSession(events=ev, corpus=corpus, unit=unit, calibration_unit=calib, fmt="ir",
                                     source=_source(p, "ir", loader), sidecar=dict(user_sc)))
    else:  # turns
        for ev, turn_ids, unmapped in read_turns(p, session):
            out.append(LoadedSession(events=ev, corpus="turns", unit="turns", calibration_unit=calibration_unit,
                                     fmt="turns", source=_source(p, "turns", LOADER_TURNS), turn_ids=turn_ids,
                                     sidecar=dict(user_sc), stat={"unmapped": unmapped}))
    if not out:
        raise LoadError(f"{p.name}: no session" + (f" {session}" if session is not None else "") + " found")
    if any(len(ls.events) == 0 for ls in out):
        raise LoadError(f"{p.name}: a session has no events")
    return out


def load_file(path: str | Path, fmt: str = "auto", *, calibration_unit: str | None = None,
              session: str | None = None, sidecar: Mapping[str, object] | None = None) -> list:
    """One input file -> list[Session] (DESIGN.md §2.3 'loaders.files.load_file'). Raises LoadError on bad input."""
    from verifier.session import build_session

    return [to_session(ls, build_session) for ls in
            load_events(path, fmt, calibration_unit=calibration_unit, session=session, sidecar=sidecar)]


def to_session(ls: LoadedSession, build_session=None):
    """LoadedSession -> verifier.session.Session."""
    if build_session is None:
        from verifier.session import build_session
    return build_session(ls.events, unit=ls.unit, source=ls.source, calibration_unit=ls.calibration_unit,
                         turn_ids=ls.turn_ids, sidecar=ls.sidecar)
