"""Input format detection for one file (DESIGN.md §6.1, `verifier/loaders/detect.py`).

Rules, in order:
  1. `.parquet` whose schema has exactly the IR COLUMNS (in order)                       -> 'ir'
  2. `.json` whose top-level object has a `steps` list (Harbor ATIF trajectory)          -> 'atif'
  3. a JSONL file whose first object has `role` and `turn_number` (SCOPE.md §3 turns)    -> 'turns'
  4. otherwise `load_swechat.sniff_text(load_swechat.read_head(path))`: claude_code, codex, opencode, gemini, cursor,
     copilot, simple_text, or 'empty' / 'unknown' (content sniffing, never the file name; first 4 KB).

`cursor` and `simple_text` load, but carry no results or no clock, so every call comes out unconstrained.
A directory (a Claude Code project with subagent files) is not an input in this build (§6.1: cut).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

Format = Literal["claude_code", "codex", "opencode", "gemini", "cursor", "copilot", "simple_text", "atif", "ir", "turns",
                 "empty", "unknown"]

# Formats load_file can read. The first five plus atif are the ones with a default calibration (units.py).
FILE_FORMATS: tuple[str, ...] = ("claude_code", "codex", "opencode", "gemini", "cursor", "copilot", "simple_text",
                                 "atif", "ir", "turns")
# The swechat parsers (load_swechat.PARSERS) cover these.
SWECHAT_PARSED: tuple[str, ...] = ("claude_code", "codex", "opencode", "gemini", "cursor", "copilot", "simple_text")
# `--format` choices of the CLI (§6.1); cursor / copilot / simple_text are reachable through 'auto' only.
CLI_FORMATS: tuple[str, ...] = ("auto", "claude_code", "codex", "opencode", "gemini", "atif", "ir", "turns")

_HEAD_BYTES = 4096


def _is_ir_parquet(path: Path) -> bool:
    import pyarrow.parquet as pq

    from verifier.ir import COLUMNS

    try:
        names = pq.read_schema(path).names
    except Exception:  # noqa: BLE001  not a readable parquet file
        return False
    return list(names) == list(COLUMNS)


def _first_json_object(path: Path) -> dict | None:
    """First non-empty line of a text file parsed as JSON (None if it is not one JSON object)."""
    try:
        with open(path, "rb") as f:
            for raw in f:
                line = raw.decode("utf-8", errors="replace").strip().lstrip("﻿")
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    return None
                return o if isinstance(o, dict) else None
    except OSError:
        return None
    return None


def _is_atif(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            doc = json.loads(f.read().decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and isinstance(doc.get("steps"), list)


def sniff(path: str | Path) -> Format:
    """Format of one input file (rules in the module docstring). Never raises for a readable file."""
    from analysis.loaders import load_swechat as lsw

    p = Path(path)
    if p.is_dir():
        return "unknown"
    suffix = p.suffix.lower()
    if suffix == ".parquet":
        return "ir" if _is_ir_parquet(p) else "unknown"
    if suffix == ".json" and _is_atif(p):
        return "atif"
    if suffix != ".json":
        o = _first_json_object(p)
        if isinstance(o, dict) and "role" in o and "turn_number" in o:
            return "turns"
    fmt = lsw.sniff_text(lsw.read_head(str(p), _HEAD_BYTES))
    return fmt if fmt in SWECHAT_PARSED or fmt in ("empty", "unknown") else "unknown"
