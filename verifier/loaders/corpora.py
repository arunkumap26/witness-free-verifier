"""Corpus adapters: Phase E IR caches -> per-session IR frames and `Session`s (DESIGN.md §2.5).

One `CorpusAdapter` per corpus we hold a loader for. Each wraps the analysis loader that built its caches
(`analysis/loaders/*.py`, named in `loader` / `parser`) and reads that loader's IR cache
`analysis/cache/<corpus>_<split>.parquet` with pyarrow, one row group at a time. Nothing is re-parsed: the rows are the
loader's own output, already validated with `ir.validate` when the cache was written.

Splits. Only A (calibration), B and E (development) exist for the verifier. Every read goes through `cache_path`,
which raises AssertionError for any other split name and for any file name that looks like the held-out split
(`_H`, 'held out'), as `prereg_e_common.read_cache` does. The verifier has no notion of the held-out split
(§5.2 rule 1); `eval/heldout.py` builds those caches by its own path, after the freeze.

Privacy and licences (§6.3). `cc_local` is private: its adapter exists (aggregates, calibration on A, the B dev pack),
but `private=True` and it is excluded from `public_corpora()`, so a published or demo path that iterates the public
corpora never reaches it. `aiv_cu` / `aiv_cc` are gated (metrics only, never rendered). `PUBLISHABLE` is DESIGN.md
§6.3's set; swechat is in it but its HF gate terms still need a human check before a derivative is published.

Record schema: the IR rows are exactly `verifier.ir.COLUMNS` (analysis/lib/ir.py), typed as `ir.to_frame` types them,
sorted by seq with a RangeIndex. `iter_sessions` turns each frame into a `verifier.session.Session` with
`build_session(events, unit=, source=, calibration_unit=, sidecar=)` (§4.2).
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, Sequence

import pandas as pd

from verifier.ir import COLUMNS
from verifier.loaders import units as U

ROOT = U.ROOT
CACHE_DIR = U.CACHE_DIR
READABLE_SPLITS = ("A", "B", "E")
PUBLISHABLE = frozenset({"swechat", "tbench2", "pub_trace_commons", "glm_tb21"})  # DESIGN.md §6.3

_HELD_NAME = re.compile(r"held.?out", re.I)


def _refuse_split(split: str) -> None:
    if split not in READABLE_SPLITS:
        raise AssertionError(f"split {split!r} is not readable by verifier.loaders (only {READABLE_SPLITS})")


def _refuse_path(path: Path) -> None:
    name = path.name
    if "_H" in name or _HELD_NAME.search(name):
        raise AssertionError(f"refusing {name}: looks like the held-out split")


@functools.lru_cache(maxsize=64)
def file_sha256_lf(rel_or_abs: str) -> str | None:
    """sha256 of a file's bytes with CRLF normalised to LF (the IR_SCHEMA_SHA rule); None when absent."""
    p = Path(rel_or_abs)
    p = p if p.is_absolute() else ROOT / p
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a cache read to exactly COLUMNS with `ir.to_frame`'s dtypes (no-op when the parquet carried them)."""
    out = {}
    for c, t in COLUMNS.items():
        s = df[c]
        if t == "int64":
            s = s.astype("int64")
        elif t == "Int64":
            s = s.astype("Int64")
        elif t == "boolean":
            s = s.astype("boolean")
        else:
            s = s.astype("string")
        out[c] = s
    return pd.DataFrame(out)


def _session_frame(df: pd.DataFrame) -> pd.DataFrame:
    s = df.reset_index(drop=True)
    if not s["seq"].is_monotonic_increasing:
        s = s.sort_values("seq", kind="stable").reset_index(drop=True)
    return s


@dataclass(frozen=True)
class CorpusAdapter:
    corpus: str
    loader: str                          # repo-relative path of the analysis loader that wrote the caches
    parser: str                          # per-session parser that produced the rows (DESIGN.md §2.5 table)
    cache_splits: tuple[str, ...]        # splits with an IR cache today (§2.5)
    units: tuple[str, ...]               # Phase E units of this corpus (units.py)
    licence: str
    default_format: str | None = None    # format when it does not vary per session
    publishable: bool = False
    private: bool = False
    gated: bool = False
    notes: str = ""
    raw_numlines: bool = False           # raw Claude Code JSONL reachable for the cc_numlines sidecar

    # ---------------------------------------------------------------------------------------------------- paths
    def cache_path(self, split: str) -> Path:
        _refuse_split(split)
        p = CACHE_DIR / f"{self.corpus}_{split}.parquet"
        _refuse_path(p)
        return p

    def available_splits(self) -> tuple[str, ...]:
        return tuple(s for s in self.cache_splits if self.cache_path(s).exists())

    def cache_relpath(self, split: str) -> str:
        p = self.cache_path(split)
        try:
            return p.relative_to(ROOT).as_posix()
        except ValueError:
            return p.as_posix()

    # ---------------------------------------------------------------------------------------------------- reads
    def read_columns(self, split: str, columns: Sequence[str], session_ids: Iterable[str] | None = None
                     ) -> pd.DataFrame:
        """A column subset of the split's cache (all sessions, or `session_ids`), session_id as str."""
        import pyarrow.parquet as pq

        filters = None
        if session_ids is not None:
            filters = [("session_id", "in", sorted({str(s) for s in session_ids}))]
        df = pq.read_table(self.cache_path(split), columns=list(columns), filters=filters).to_pandas()
        if "session_id" in df.columns:
            df["session_id"] = df["session_id"].astype(str)
        return df

    def session_ids(self, split: str) -> list[str]:
        """Distinct session ids of the split's cache, in file order."""
        d = self.read_columns(split, ["session_id"])
        return [str(s) for s in pd.unique(d["session_id"])]

    def iter_frames(self, split: str, session_ids: Iterable[str] | None = None) -> Iterator[pd.DataFrame]:
        """One IR frame per session (exactly COLUMNS, ir.to_frame dtypes, seq order, RangeIndex), in cache file order.

        Streams one parquet row group at a time; a session that continues into the next row group is joined. Ids not
        present in the cache are skipped. Raises ValueError if a session's rows are not contiguous in the file.
        The split is checked when this is called, not when the iterator is first advanced."""
        path = self.cache_path(split)  # raises AssertionError now for any split but A, B, E
        ids = None if session_ids is None else sorted({str(s) for s in session_ids})
        return self._frames(path, split, ids)

    def _frames(self, path: Path, split: str, ids: list[str] | None) -> Iterator[pd.DataFrame]:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        pf = pq.ParquetFile(path)
        want = None if ids is None else pa.array(ids, type=pa.large_string())
        done: set[str] = set()
        held_id, held = None, []
        cols = list(COLUMNS)
        for g in range(pf.num_row_groups):
            mask = None
            if want is not None:
                ids_g = pf.read_row_group(g, columns=["session_id"]).column(0)
                mask = pc.is_in(ids_g.cast(pa.large_string()), value_set=want)
                if not pc.any(mask).as_py():
                    continue
            t = pf.read_row_group(g, columns=cols)
            if mask is not None:
                t = t.filter(mask)
            if t.num_rows == 0:
                continue
            df = _typed(t.to_pandas())
            sid_col = df["session_id"].astype(str)
            order = list(pd.unique(sid_col))
            pos = sid_col.groupby(sid_col, sort=False).indices
            for k, sid in enumerate(order):
                part = df.iloc[pos[sid]]
                if sid == held_id:
                    held.append(part)
                    if k < len(order) - 1:  # the held session ended inside this row group
                        yield _session_frame(pd.concat(held, ignore_index=True))
                        done.add(sid)
                        held_id, held = None, []
                    continue
                if held_id is not None:  # previous row group's last session did not continue here
                    yield _session_frame(pd.concat(held, ignore_index=True))
                    done.add(held_id)
                    held_id, held = None, []
                if sid in done:
                    raise ValueError(f"{self.corpus}_{split}: session {sid} is not contiguous in the cache")
                if k == len(order) - 1:  # may continue into the next row group
                    held_id, held = sid, [part]
                else:
                    yield _session_frame(part)
                    done.add(sid)
        if held_id is not None:
            yield _session_frame(pd.concat(held, ignore_index=True))

    # ------------------------------------------------------------------------------------------- units, formats
    def formats(self, split: str, session_ids: Iterable[str]) -> dict[str, str]:
        """{session_id: log format} for sessions of this split (reporting only; it decides the unit for swechat)."""
        ids = [str(s) for s in session_ids]
        if self.corpus == "swechat":
            return U.swechat_formats(ids)
        if self.corpus in ("tbench2", "glm_tb21"):
            idx = _split_index(self.corpus)
            return {s: idx[s]["format"] for s in ids if s in idx}
        if self.corpus == "agentcap":
            st = self.read_columns(split, ["session_id", "stratum"], ids).drop_duplicates("session_id")
            return {r.session_id: str(r.stratum).split("/", 1)[0] for r in st.itertuples(index=False)
                    if isinstance(r.stratum, str)}
        return {s: self.default_format for s in ids} if self.default_format else {}

    def unit_of(self, session_id: str, stratum: str | None, fmt: str | None = None) -> str:
        return U.unit_of(self.corpus, session_id, stratum, fmt)

    def source(self, split: str, fmt: str | None) -> dict:
        """Session.source for a cached session (§4.2): {'path', 'format', 'loader', 'loader_sha256', 'split'}."""
        return {"path": self.cache_relpath(split), "format": fmt, "loader": self.loader,
                "loader_sha256": file_sha256_lf(self.loader), "split": split}

    # ------------------------------------------------------------------------------------------------ raw files
    def raw_paths(self, session_id: str) -> list[Path]:
        """Raw transcript file(s) of a cached session, for sidecar readers (§2.7). [] when the corpus keeps none we can
        reach (aiv_*, whowhen, agentcap) or when private (cc_local: its raw files are never opened here)."""
        sid = str(session_id)
        if self.corpus == "swechat":
            from analysis.loaders import load_swechat as lsw

            return [Path(lsw.TRANS) / f"{sid}.jsonl"]
        if self.corpus in ("tbench2", "glm_tb21"):
            row = _split_index(self.corpus).get(sid)
            if row is None:
                return []
            root = _tb_data_root(self.corpus)
            tdir = Path(root, row["submission"], row["job"], row["trial"]) if row.get("submission") \
                else Path(root, row["trial"])
            return [tdir / f for f in json.loads(row["files"])]
        if self.corpus in ("pub_cc_hf", "pub_trace_commons"):
            idx = _pub_cc_index(self.corpus)
            ent = idx["sessions"].get(sid)
            if ent is None:
                return []
            return [Path(idx["corpus_root"]) / f[1] for f in ent.get("files", [])]
        return []

    def numlines_sidecar(self, session_id: str, fmt: str | None) -> dict:
        """{'cc_numlines': {...}} for a Claude Code-format session whose raw JSONL we can reach, else {}."""
        if not self.raw_numlines or fmt not in ("claude_code", "cc_jsonl"):
            return {}
        from verifier.loaders.sidecar import read_cc_numlines

        paths = self.raw_paths(session_id)
        if not any(p.is_file() for p in paths):
            return {}
        return {"cc_numlines": read_cc_numlines(paths)}

    def sidecars(self, split: str, frames_meta: Sequence[tuple[str, str | None]], *, numlines: bool = True
                 ) -> dict[str, dict]:
        """Auto-filled sidecars for (session_id, format) pairs (§2.7). What each corpus can fill:
          cc_numlines         Claude Code-format sessions whose raw JSONL we can reach (swechat claude_code, tbench2
                              cc_jsonl, pub_cc_hf, pub_trace_commons); one raw read per session
          entire_tally        swechat (None when the token_usage gate fails); one bulk read
          copied_request_ids  swechat (index over B u E) and cc_local (B), as F1 computed it; each session gets the
                              entries for its own request ids (the dedupe rule reads no others), possibly {}
        """
        from verifier.loaders import sidecar as SC

        out: dict[str, dict] = {sid: {} for sid, _ in frames_meta}
        if numlines:
            for sid, fmt in frames_meta:
                out[sid].update(self.numlines_sidecar(sid, fmt))
        if self.corpus == "swechat":
            tallies = SC.read_entire_tally([sid for sid, _ in frames_meta])
            for sid, _ in frames_meta:
                out[sid]["entire_tally"] = tallies.get(sid)
        if self.corpus in SC.COPY_INDEX_SPLITS:
            index = _copy_index(self.corpus)
            rid = self.read_columns(split, ["session_id", "request_id"], [sid for sid, _ in frames_meta])
            rid = rid[rid.request_id.notna()]
            by_s = rid.groupby("session_id").request_id.agg(lambda x: set(map(str, x))).to_dict()
            for sid, _ in frames_meta:
                out[sid]["copied_request_ids"] = {r: index[r] for r in sorted(by_s.get(sid, ())) if r in index}
        return out

    # ------------------------------------------------------------------------------------------------- sessions
    def iter_sessions(self, split: str, session_ids: Sequence[str] | None = None, *,
                      calibration_unit_of: Callable[[str], str | None] | None = None,
                      with_sidecar: bool = False,
                      sidecar_of: Callable[[str], Mapping[str, object] | None] | None = None) -> Iterator:
        """`Session`s of one split (DESIGN.md §2.5), in cache file order.

        calibration_unit_of: unit -> calibration unit; default None for every session (the API default borrows
          nothing, §4.5; the eval passes its D1 map, a census may pass `lambda u: u`).
        with_sidecar: fill the sidecar from its sources (see `sidecars`); sidecar_of(session_id) adds or overrides keys.
        Refuses any split but A, B and E (AssertionError, raised when this is called)."""
        self.cache_path(split)
        return self._sessions(split, session_ids, calibration_unit_of, with_sidecar, sidecar_of)

    def _sessions(self, split, session_ids, calibration_unit_of, with_sidecar, sidecar_of) -> Iterator:
        from verifier.session import build_session

        ids = list(session_ids) if session_ids is not None else self.session_ids(split)
        fm = self.formats(split, ids)
        auto = self.sidecars(split, [(s, fm.get(s)) for s in ids], numlines=False) if with_sidecar else {}
        for ev in self.iter_frames(split, ids if session_ids is not None else None):
            sid = str(ev["session_id"].iat[0])
            stratum = ev["stratum"].iat[0]
            stratum = None if pd.isna(stratum) else str(stratum)
            fmt = fm.get(sid)
            unit = self.unit_of(sid, stratum, fmt if self.corpus in ("swechat", "agentcap") else None)
            sc = dict(auto.get(sid, {}))
            if with_sidecar:
                sc.update(self.numlines_sidecar(sid, fmt))   # raw read per session, as it is consumed
            if sidecar_of is not None:
                sc.update(sidecar_of(sid) or {})
            yield build_session(ev, unit=unit, source=self.source(split, fmt),
                                calibration_unit=calibration_unit_of(unit) if calibration_unit_of else None,
                                sidecar=sc)


# -------------------------------------------------------------------------------------------- per-corpus indexes
@functools.lru_cache(maxsize=4)
def _split_index(corpus: str) -> dict[str, dict]:
    """tbench2 / glm_tb21 `<corpus>_split_index.parquet` (A/B/E rows only) keyed by session_id."""
    import pyarrow.parquet as pq

    p = CACHE_DIR / f"{corpus}_split_index.parquet"
    if not p.exists():
        return {}
    d = pq.read_table(p).to_pandas()
    d = d[d["split"].isin(READABLE_SPLITS)]
    return {str(r["session_id"]): r for r in d.to_dict("records")}


def _tb_data_root(corpus: str) -> str:
    if corpus == "glm_tb21":
        from analysis.loaders import load_glm_tb21 as G

        return G.DATA_ROOT
    from analysis.loaders import load_tbench2 as T

    return T.DATA_ROOT


@functools.lru_cache(maxsize=4)
def _pub_cc_index(corpus: str) -> dict:
    """`<corpus>_index.json` (pub_cc_common.write_index): A/B/E sessions only, files relative to corpus_root."""
    p = CACHE_DIR / f"{corpus}_index.json"
    if not p.exists():
        return {"corpus_root": "", "sessions": {}}
    d = json.loads(p.read_text(encoding="utf-8"))
    d["sessions"] = {k: v for k, v in d.get("sessions", {}).items() if v.get("split") in READABLE_SPLITS}
    return d


@functools.lru_cache(maxsize=4)
def _copy_index(corpus: str) -> dict[str, str]:
    from verifier.loaders import sidecar as SC

    return SC.copied_request_ids_for_corpus(corpus)


# ------------------------------------------------------------------------------------------------------ registry
_SW_FMT = ", ".join(U.SWECHAT_FORMATS)

CORPUS_ADAPTERS: dict[str, CorpusAdapter] = {a.corpus: a for a in (
    CorpusAdapter(
        corpus="swechat", loader="analysis/loaders/load_swechat.py",
        parser="load_swechat.parse_session(sid, fmt, stratum, ctx, path) -> PARSERS[fmt]",
        cache_splits=("A", "B", "E"), units=tuple(f"swechat/{f}" for f in U.SWECHAT_FORMATS),
        licence="ODC-BY (HF SALT-NLP/SWE-chat@f66cca95; HF gate terms to confirm before publishing a derivative)",
        publishable=True, raw_numlines=True,
        notes=f"unit = swechat/<content format> from swechat_population.parquet ({_SW_FMT}); IR stratum = agent "
              "label"),
    CorpusAdapter(
        corpus="tbench2", loader="analysis/loaders/load_tbench2.py",
        parser="load_tbench2.parse_session(row) (atif: parse_atif; cc_jsonl: parse_cc; gemini_cli; hookele)",
        cache_splits=("A", "B", "E"), units=("tbench2",),
        licence="Apache-2.0 (HF harborframework/terminal-bench-2-leaderboard@572b2614)", publishable=True,
        raw_numlines=True,
        notes="log format (atif, cc_jsonl, gemini_cli, hookele) from tbench2_split_index.parquet is a reporting "
              "stratum; IR stratum = submission"),
    CorpusAdapter(
        corpus="glm_tb21", loader="analysis/loaders/load_glm_tb21.py",
        parser="load_tbench2.build_frame(rows) (ATIF)", cache_splits=("A", "B", "E"), units=("glm_tb21",),
        licence="MIT (HF 0xSero/glm-5.2-nf3-hybrid-terminal-bench-2.1-traces@6020a41c)", publishable=True,
        default_format="atif", raw_numlines=False),
    CorpusAdapter(
        corpus="pub_cc_hf", loader="analysis/loaders/load_pub_cc_hf.py",
        parser="pub_cc_common.parse_session(s, corpus, C, R)", cache_splits=("A", "B", "E"), units=("pub_cc_hf",),
        licence="per repo (12 HF repos); a per-repo check is needed before publishing", default_format="claude_code",
        raw_numlines=True, notes="eval calibration unit: cc_local (D1 proxy)"),
    CorpusAdapter(
        corpus="pub_trace_commons", loader="analysis/loaders/load_pub_trace_commons.py",
        parser="pub_cc_common.parse_session(s, corpus, C, R)", cache_splits=("A", "B", "E"),
        units=("pub_trace_commons",), licence="CC BY 4.0 (HF trace-commons/agent-traces@112ebd4d)", publishable=True,
        default_format="claude_code", raw_numlines=True, notes="eval calibration unit: cc_local (D1 proxy)"),
    CorpusAdapter(
        corpus="pub_codex", loader="analysis/loaders/load_pub_codex.py",
        parser="load_pub_codex.parse_one(row, red) -> load_swechat.parse_codex", cache_splits=("A", "B", "E"),
        units=("pub_codex",), licence="per repo (6 HF repos)", default_format="codex",
        notes="eval calibration unit: swechat/codex (D1 proxy)"),
    CorpusAdapter(
        corpus="agentcap", loader="analysis/loaders/load_agentcap.py",
        parser="load_agentcap.parse_pi / load_swechat.parse_opencode + join_session (wire captures)",
        cache_splits=("A", "B", "E"), units=("agentcap/opencode", "agentcap/pi"),
        licence="Apache-2.0 (9 HF repos dacorvo/*)",
        notes="caches already exclude the D5 parse-exposed B/E sessions (newcorp_exclusions.json); "
              "agentcap/opencode calibrates as swechat/opencode (D1 proxy)"),
    CorpusAdapter(
        corpus="aiv_cu", loader="analysis/loaders/load_aiv_cu.py",
        parser="load_aiv_cu.build_session(sid, stratum, model_string, raw_lines, counters)",
        cache_splits=("A", "B", "E"), units=("aiv_cu",), licence="custom research terms (HF gated)", gated=True,
        default_format="aiv_cu", notes="metrics only, never rendered; provider family is a reporting stratum"),
    CorpusAdapter(
        corpus="aiv_cc", loader="analysis/loaders/load_aiv_cc.py", parser="cc_jsonl.Parser (load_aiv_cc.parse_session)",
        cache_splits=("A", "B"), units=("aiv_cc",), licence="custom research terms (HF gated)", gated=True,
        default_format="claude_code", notes="one agent (case study); no E"),
    CorpusAdapter(
        corpus="cc_local", loader="analysis/loaders/load_cc_local.py", parser="load_cc_local.process_session",
        cache_splits=("A", "B"), units=("cc_local",), licence="private (local ~/.claude/projects snapshot)",
        private=True, default_format="claude_code",
        notes="PRIVATE: never rendered, never in a published or demo path; aggregates only; no E"),
    CorpusAdapter(
        corpus="whowhen", loader="analysis/loaders/load_whowhen.py", parser="load_whowhen.parse_ag / parse_hc",
        cache_splits=("A", "B"), units=("whowhen",), licence="MIT (GitHub; HF Kevin355/Who_and_When@59b9fcba)",
        default_format="whowhen", notes="no clock (ts_kind none); no E"),
)}

PRIVATE_CORPORA = frozenset(c for c, a in CORPUS_ADAPTERS.items() if a.private)


def public_corpora() -> tuple[str, ...]:
    """Every corpus except the private ones, in registry order. Published and demo paths iterate only these."""
    return tuple(c for c, a in CORPUS_ADAPTERS.items() if not a.private)


def get_adapter(corpus: str) -> CorpusAdapter:
    try:
        return CORPUS_ADAPTERS[corpus]
    except KeyError:
        raise KeyError(f"no adapter for corpus {corpus!r}; known: {sorted(CORPUS_ADAPTERS)}") from None


def iter_sessions(corpus: str, split: str, session_ids: Sequence[str] | None = None, **kw) -> Iterator:
    """Shorthand for CORPUS_ADAPTERS[corpus].iter_sessions(split, session_ids, **kw)."""
    return get_adapter(corpus).iter_sessions(split, session_ids, **kw)

