"""Sidecar readers: harness-written records the IR drops (DESIGN.md §2.7, DA14).

The schema and its validation live in `verifier.session.sidecar` (SIDECAR_KEYS, validate_sidecar). This module only
reads the sources, read-only, and returns plain Python values in that schema:

  cc_numlines         dict[str call_id, int]   toolUseResult.file.numLines of Read results in raw Claude Code JSONL
  entire_tally        dict {api, in, cc, cr, out} | None   SWE-chat sessions.parquet, gated on session_logs token_usage
  copied_request_ids  dict[str request_id, str smallest_holder_session_id]   corpus-level index

Each reader is a port of the Track A function named in §2.7, so a parity test can compare them value for value:
  read_cc_numlines    <- analysis/probes/phase_e_n7_content.py raw_swechat_cc / raw_cc_local / _numlines_from_entry
  read_entire_tally   <- analysis/probes/phase_e_n7_content.py swechat_tallies (phase_c_swechat_tables._i for ints)
  copied_request_ids  <- analysis/probes/phase_e_f1_bracket.py copied_ids (the `keep` map)
Attacks never touch a sidecar (§2.7).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

TALLY_KEYS = ("api", "in", "cc", "cr", "out")

# Readable dev splits per corpus for the copied-request-id index (F1 deviation 1: "another session of the readable
# corpus" = swechat B u E, cc_local B; A is calibration-only). Other corpora: B, plus E where the corpus has one.
COPY_INDEX_SPLITS: dict[str, tuple[str, ...]] = {"swechat": ("B", "E"), "cc_local": ("B",)}


def _swe_data_dir() -> Path:
    from analysis.loaders import load_swechat as lsw

    return Path(lsw.DATA)


def _tally_int(x) -> int:
    """phase_c_swechat_tables._i: int(x or 0), 0 on any failure (None, NaN, pd.NA, junk)."""
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------------------------------------------- cc_numlines
def _numlines_from_entry(d: Mapping, nl: dict) -> None:
    tur = d.get("toolUseResult")
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
    tr = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"), None)
    if not isinstance(tur, dict) or tr is None:
        return
    f = tur.get("file")
    if isinstance(f, dict) and type(f.get("numLines")) is int and tr.get("tool_use_id"):
        nl.setdefault(str(tr["tool_use_id"]), f["numLines"])


def read_cc_numlines(raw_path: str | os.PathLike | Iterable[str | os.PathLike]) -> dict[str, int]:
    """{tool_use_id: numLines} from one raw Claude Code JSONL file, or several read in the order given (a main session
    file plus its subagent files). The first value per id wins. A missing file contributes nothing.

    Rule (exact port of N7's `_numlines_from_entry`): a line that contains '"numLines"' and parses to a dict counts when
    its `toolUseResult` is a dict, its `message.content` holds a `tool_result` block, and `toolUseResult.file.numLines`
    is an int (`type(...) is int`, so a bool is not). The key is that first tool_result block's `tool_use_id`."""
    paths = [raw_path] if isinstance(raw_path, (str, os.PathLike)) else list(raw_path)
    nl: dict[str, int] = {}
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip() or '"numLines"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    _numlines_from_entry(d, nl)
    return nl


# ------------------------------------------------------------------------------------------------------ entire_tally
def read_entire_tally(session_ids: Iterable[str], *, sessions_path: str | os.PathLike | None = None,
                      logs_path: str | os.PathLike | None = None) -> dict[str, dict | None]:
    """{session_id: {api, in, cc, cr, out} | None} for SWE-chat sessions (the Entire capture tool's session tally).

    Port of N7's `swechat_tallies`: `sessions.parquet` columns api_call_count, input_tokens, cache_creation_tokens,
    cache_read_tokens, output_tokens, kept only when `session_logs.parquet` `session_metadata_raw` parses to an object
    whose `token_usage` is a dict (the gate). Every requested id is a key; None when the gate fails or the id is not
    in the tables."""
    import pyarrow.parquet as pq

    ids = sorted({str(s) for s in session_ids})
    out: dict[str, dict | None] = {s: None for s in ids}
    if not ids:
        return out
    base = _swe_data_dir()
    sp = Path(sessions_path) if sessions_path else base / "sessions.parquet"
    lp = Path(logs_path) if logs_path else base / "session_logs.parquet"
    s = pq.read_table(sp, columns=["session_id", "input_tokens", "output_tokens", "cache_creation_tokens",
                                   "cache_read_tokens", "api_call_count"],
                      filters=[("session_id", "in", ids)]).to_pandas()
    logs = pq.read_table(lp, columns=["session_id", "session_metadata_raw"],
                         filters=[("session_id", "in", ids)]).to_pandas()
    md = dict(zip(logs.session_id.astype(str), logs.session_metadata_raw))
    for r in s.itertuples(index=False):
        try:
            raw = json.loads(md.get(str(r.session_id)) or "{}")
        except (ValueError, TypeError):
            raw = {}
        tu = raw.get("token_usage") if isinstance(raw, dict) else None
        if isinstance(tu, dict):
            out[str(r.session_id)] = {"api": _tally_int(r.api_call_count), "in": _tally_int(r.input_tokens),
                                      "cc": _tally_int(r.cache_creation_tokens), "cr": _tally_int(r.cache_read_tokens),
                                      "out": _tally_int(r.output_tokens)}
    return out


# ------------------------------------------------------------------------------------------------ copied_request_ids
def copied_request_ids(frames: Iterable[pd.DataFrame]) -> dict[str, str]:
    """{request_id: smallest session_id holding it} for every request id present in more than one session across
    `frames` (each with at least columns session_id, request_id; any number of sessions). Port of F1's `copied_ids`
    (`keep` map): rows with a request id, deduplicated per frame and again after concatenation."""
    parts = []
    for d in frames:
        d = d[["session_id", "request_id"]]
        d = d[d.request_id.notna()].drop_duplicates()
        parts.append(pd.DataFrame({"session_id": d.session_id.astype(str).to_numpy(),
                                   "request_id": d.request_id.astype(str).to_numpy()}))
    if not parts:
        return {}
    d = pd.concat(parts, ignore_index=True).drop_duplicates()
    if d.empty:
        return {}
    ns = d.groupby("request_id").session_id.nunique()
    cop = ns[ns > 1].index
    keep = d[d.request_id.isin(cop)].groupby("request_id").session_id.min()
    return {str(k): str(v) for k, v in keep.sort_index().items()}


def copy_index_splits(corpus: str) -> tuple[str, ...]:
    """The readable dev splits a corpus's copied-request-id index is computed over (see COPY_INDEX_SPLITS)."""
    if corpus in COPY_INDEX_SPLITS:
        return COPY_INDEX_SPLITS[corpus]
    from verifier.loaders.corpora import CORPUS_ADAPTERS

    have = CORPUS_ADAPTERS[corpus].available_splits()
    return tuple(s for s in ("B", "E") if s in have)


def copied_request_ids_for_corpus(corpus: str, splits: Iterable[str] | None = None) -> dict[str, str]:
    """copied_request_ids over the IR caches of `corpus` (default: copy_index_splits(corpus)). Reads only the
    session_id and request_id columns, through the corpus adapter (which refuses any split but A, B and E)."""
    from verifier.loaders.corpora import CORPUS_ADAPTERS

    ad = CORPUS_ADAPTERS[corpus]
    sp = tuple(splits) if splits is not None else copy_index_splits(corpus)
    return copied_request_ids(ad.read_columns(s, ["session_id", "request_id"]) for s in sp)
