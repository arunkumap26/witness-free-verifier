"""Per-corpus capability table: which IR fields each corpus fills, measured on its IR caches.

    PYTHONIOENCODING=utf-8 python -m verifier.loaders.capabilities [--corpora a,b] [--splits A,B,E]
                                                                    [--out verifier/loaders/capabilities.json]
                                                                    [--print] [--check]

Day-time build step; nothing in the verifier reads the JSON at run time (checks decide from each Session's own
capabilities, DESIGN.md §4.3). It answers, per corpus, split and unit: ms timestamps, the call/result join, request ids
(and how many decode under the DA20 layout gate), usage, native error flags, truncation markers, and the share of
sessions holding each §4.3 capability.

What is read: `analysis/cache/<corpus>_<split>.parquet` for A, B and E through `CorpusAdapter.iter_frames` (which
refuses every other split), plus `swechat_population.parquet` (format of the cached swechat ids only) and
`tbench2_split_index.parquet` (log format). No raw transcript is opened, so the sidecar capabilities
(`sidecar.*`) are not measured here; `adapter.sidecar_sources` says which corpora can fill them.

Private corpora (cc_local) are excluded unless --include-private is given, and then the output must not be written
inside the repository (the default --out is refused). Gated corpora (aiv_*) appear as counts only.

Definitions (also written into the JSON under "definitions"):
  session-level   `verifier.session.detect_capabilities(events, sidecar={})`, the runtime predicate set (§4.3)
  pairing         `verifier.session.pair_calls`, the §3.1 rule (orphan iff no call with its call_id precedes it)
  ms stamp        call/result row whose ts has >= 3 fractional digits (`ir.frac_digits`)
  decodable id    `verifier.session.decode(v)` is not None (vendored idclock with the DA20 UUIDv7 gate)
  truncation      result text with a loss-type marker of the Phase A3 catalogue (frozen copy below, from
                  analysis/probes/phase_a_a3.py MARKERS/LOSS_TYPES; read_window and read_refusal excluded) or the
                  swechat dataset cap (text == 10,256 chars ending "\\n... [truncated]"); flag = extra.truncated is True
  error marker    `ir.error_marker(text)` is not None on a result
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd

from verifier.ir import IR_SCHEMA_SHA, error_marker, frac_digits
from verifier.loaders import units as U
from verifier.loaders.corpora import CORPUS_ADAPTERS, ROOT, file_sha256_lf

SCHEMA = "verifier.loaders.capabilities/1"
DEFAULT_OUT = Path(__file__).resolve().parent / "capabilities.json"

# Frozen copy of the Phase A3 loss-type markers (analysis/probes/phase_a_a3.py MARKERS where type in LOSS_TYPES).
TRUNCATION_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("cc_chars_truncated", "middle_elision", r"\.\.\. \[\d+ characters truncated\] \.\.\."),
    ("cc_lines_truncated", "tail_cut", r"\.\.\. \[\d+ lines truncated\] \.\.\."),
    ("cc_persisted_output", "spill", r"^<persisted-output>"),
    ("cc_output_too_large", "spill", r"Output too large \([\d.]+\s?[KMG]?B\)\. Full output saved to:"),
    ("cc_results_truncated", "list_cap", r"\(Results are truncated\. Consider using a more specific path or pattern\.\)"),
    ("cc_rg_omitted_long_line", "line_cap", r"\[Omitted long (?:matching )?line"),
    ("codex_tokens_truncated", "middle_elision", r"…\d+ tokens truncated…"),
    ("codex_chars_truncated", "middle_elision", r"…\d+ chars truncated…"),
    ("codex_total_output_lines", "middle_elision", r"(?m)^Total output lines: \d+"),
    ("codex_omitted_lines", "middle_elision", r"\[\.\.\. omitted \d+ of \d+ lines \.\.\.\]"),
    ("gem_tool_output_masked", "history_mask", r"^<tool_output_masked>"),
    ("gem_output_too_large_saved", "spill", r"Output too large\. Full output available at:"),
    ("gem_output_too_large_showing", "middle_elision", r"Output too large\. Showing first [\d,]+ and last [\d,]+ characters"),
    ("gem_truncated_tag", "middle_elision", r"\.\.\. \[TRUNCATED\] \.\.\."),
    ("gem_lines_omitted", "middle_elision", r"\.\.\. \[[\d,]+ lines omitted\] \.\.\."),
    ("gem_chars_omitted", "middle_elision", r"\.\.\. \[[\d,]+ characters omitted\] \.\.\."),
    ("oc_bytes_truncated", "spill", r"\.\.\.\d+ bytes truncated\.\.\."),
    ("oc_output_saved", "spill", r"The tool call succeeded but the output was truncated\. Full output saved to:"),
    ("oc_bash_metadata_truncated", "tail_cut", r"<bash_metadata>[^<]*truncat"),
    ("oc_grep_results_truncated", "list_cap", r"\(Results truncated: showing \d+ of \d+ matches"),
    ("oc_glob_results_truncated", "list_cap", r"\(Results are truncated: showing first \d+ results"),
    ("cop_output_too_large_saved", "spill", r"Output too large to read at once \([\d.]+ ?KB\)\. Saved to:"),
    ("generic_dots_output_truncated", "tail_cut", r"\.\.\.\[output truncated\]"),
)
_TRUNC_RX = [re.compile(p) for _, _, p in TRUNCATION_MARKERS]
# Every marker above (and the dataset cap) contains one of these, so texts without them are skipped (speed only).
_TRUNC_PREFILTER = re.compile(r"(?i)truncat|omitted|too large|persisted-output|tool_output_masked|total output lines")
SWE_CAP_LEN, SWE_CAP_SUFFIX = 10256, "\n... [truncated]"

FRAC_BUCKETS = ("0", "1-2", "3", "4-6", "7+")
TS_KINDS = ("event", "row_insert", "shared_turn", "none")

DEFINITIONS = {
    "sessions": "sessions in the cache (block scope)",
    "events": "IR rows",
    "calls": "rows with kind == 'call'",
    "results": "rows with kind == 'result'",
    "cr_ts_present": "call/result rows with ts not null",
    "cr_ts_event": "call/result rows with ts_kind == 'event'",
    "cr_ts_ms": "call/result rows whose ts has >= 3 fractional digits (ms or finer)",
    "cr_ts_frac_digits": "call/result rows with a ts, by number of fractional digits",
    "cr_ts_kind": "call/result rows by ts_kind",
    "results_joined": "results that are not orphans (a call with the same call_id precedes them; §3.1)",
    "results_orphan": "results with no preceding call of their call_id",
    "calls_paired": "calls with a paired result (first result of that call_id before the next call of that id)",
    "pairs_distinct_stamps": "paired calls where call and result both carry ts and neither is ts_kind 'shared_turn'",
    "request_id_eligible_rows": "rows of kind assistant/call/meta (where §4.3 looks for request_id)",
    "request_id_rows": "eligible rows with request_id not null",
    "request_id_distinct": "distinct request ids per session, summed over sessions",
    "request_id_decodable": "of those, decodable by verifier.session.decode (DA20 gate)",
    "request_id_families": "distinct request ids per session by id family (verifier.session.id_family), summed",
    "api_msg_id_rows": "rows with api_msg_id not null",
    "api_msg_id_distinct_provider": "distinct non-synthetic api_msg_ids per session, summed",
    "api_msg_id_decodable": "of those, decodable by verifier.session.decode",
    "api_msg_id_families": "distinct non-synthetic api_msg_ids per session by id family, summed",
    "usage_io_rows": "rows with usage_in and usage_out not null",
    "usage_out_rows": "rows with usage_out not null",
    "usage_cache_read_rows": "rows with usage_cache_read not null",
    "responses_with_usage": "distinct (session_id, api_msg_id) over rows with usage_in not null (ir.py USAGE DEDUPE)",
    "results_native_error": "results with native_error not null",
    "results_native_error_true": "results with native_error true",
    "exit_code_rows": "rows with exit_code not null",
    "results_error_marker": "results whose text matches ir.error_marker",
    "results_text": "results with text not null",
    "results_trunc_marker": "results with a loss-type truncation marker (A3 catalogue) or the swechat dataset cap",
    "results_trunc_flag": "results whose extra.truncated is true",
    "results_trunc_any": "results with a truncation marker or flag",
    "shell_command_calls": "calls with command not null",
    "subagent_rows": "rows with is_subagent true",
    "causal_uuid_rows": "rows with uuid and parent_uuid not null",
    "sessions_with": "sessions where the §4.3 capability holds (verifier.session.detect_capabilities, no sidecar)",
}


def _s(v) -> str | None:
    try:
        return None if v is None or pd.isna(v) else str(v)
    except (TypeError, ValueError):
        return str(v)


def _frac_bucket(fd: int) -> str:
    return "0" if fd == 0 else "1-2" if fd <= 2 else "3" if fd == 3 else "4-6" if fd <= 6 else "7+"


def truncation_marker(text: str) -> bool:
    """A loss-type marker of the frozen A3 catalogue, or the swechat dataset cap."""
    if not isinstance(text, str) or not _TRUNC_PREFILTER.search(text):
        return False
    if len(text) == SWE_CAP_LEN and text.endswith(SWE_CAP_SUFFIX):
        return True
    return any(rx.search(text) for rx in _TRUNC_RX)


def _flag_truncated(extra: str | None) -> bool:
    if not isinstance(extra, str) or '"truncated"' not in extra:
        return False
    try:
        d = json.loads(extra)
    except ValueError:
        return False
    return isinstance(d, dict) and d.get("truncated") is True


def session_counts(ev: pd.DataFrame) -> tuple[Counter, frozenset]:
    """Counts (DEFINITIONS keys) and the §4.3 capability set of one session's IR frame."""
    from verifier import session as S

    c: Counter = Counter()
    kinds = ev["kind"].astype(object).tolist()
    ts = [_s(v) for v in ev["ts"].astype(object).tolist()]
    tsk = [_s(v) for v in ev["ts_kind"].astype(object).tolist()]
    cids = [_s(v) for v in ev["call_id"].astype(object).tolist()]
    text = ev["text"].astype(object).tolist()
    extra = ev["extra"].astype(object).tolist()
    ne = ev["native_error"].astype(object).tolist()
    c["sessions"] = 1
    c["events"] = len(kinds)
    for i, k in enumerate(kinds):
        if k not in ("call", "result"):
            continue
        c["calls" if k == "call" else "results"] += 1
        c[f"cr_ts_kind.{tsk[i]}"] += 1
        if tsk[i] == "event":
            c["cr_ts_event"] += 1
        if ts[i] is not None:
            c["cr_ts_present"] += 1
            fd = frac_digits(ts[i])
            c[f"cr_ts_frac_digits.{_frac_bucket(fd)}"] += 1
            if fd >= 3:
                c["cr_ts_ms"] += 1
        if k == "result":
            t = text[i] if isinstance(text[i], str) else None
            if t is not None:
                c["results_text"] += 1
                if error_marker(t) is not None:
                    c["results_error_marker"] += 1
            if not _isna(ne[i]):
                c["results_native_error"] += 1
                c["results_native_error_true"] += int(bool(ne[i]))
            m, f = truncation_marker(t), _flag_truncated(extra[i] if isinstance(extra[i], str) else None)
            c["results_trunc_marker"] += int(m)
            c["results_trunc_flag"] += int(f)
            c["results_trunc_any"] += int(m or f)
    pairs, orphans = S.pair_calls(kinds, cids)
    c["results_orphan"] += len(orphans)
    c["results_joined"] += c["results"] - len(orphans)
    for cs, rs, _ in pairs:
        if rs is None:
            continue
        c["calls_paired"] += 1
        if ts[cs] is not None and ts[rs] is not None and tsk[cs] != "shared_turn" and tsk[rs] != "shared_turn":
            c["pairs_distinct_stamps"] += 1
    elig = ev["kind"].isin(["assistant", "call", "meta"]).to_numpy()
    rid = ev["request_id"]
    c["request_id_eligible_rows"] += int(elig.sum())
    c["request_id_rows"] += int((elig & rid.notna().to_numpy()).sum())
    for v in sorted({str(x) for x in rid[elig].dropna().tolist()}):
        c["request_id_distinct"] += 1
        c[f"request_id_families.{S.id_family(v)}"] += 1
        c["request_id_decodable"] += int(S.decode(v) is not None)
    am = ev["api_msg_id"]
    c["api_msg_id_rows"] += int(am.notna().sum())
    for v in sorted({str(x) for x in am.dropna().tolist()}):
        fam = S.id_family(v)
        if fam == "synthetic":
            continue
        c["api_msg_id_distinct_provider"] += 1
        c[f"api_msg_id_families.{fam}"] += 1
        c["api_msg_id_decodable"] += int(S.decode(v) is not None)
    ui, uo = ev["usage_in"].notna().to_numpy(), ev["usage_out"].notna().to_numpy()
    c["usage_io_rows"] += int((ui & uo).sum())
    c["usage_out_rows"] += int(uo.sum())
    c["usage_cache_read_rows"] += int(ev["usage_cache_read"].notna().sum())
    c["responses_with_usage"] += int(am[ui].dropna().nunique())
    c["exit_code_rows"] += int(ev["exit_code"].notna().sum())
    c["shell_command_calls"] += int((ev["kind"].eq("call").fillna(False).to_numpy(dtype=bool) & ev["command"].notna().to_numpy(dtype=bool)).sum())
    c["subagent_rows"] += int(ev["is_subagent"].fillna(False).astype(bool).sum())
    c["causal_uuid_rows"] += int((ev["uuid"].notna() & ev["parent_uuid"].notna()).sum())
    caps = S.detect_capabilities(ev, {})
    return c, caps


def _isna(v) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _block(c: Counter, caps: Counter) -> dict:
    """Counter -> JSON block with nested dict for dotted keys; sessions_with from the capability counter."""
    out: dict = {}
    for k in sorted(c):
        if "." in k:
            a, b = k.split(".", 1)
            out.setdefault(a, {})[b] = int(c[k])
        else:
            out[k] = int(c[k])
    for k in ("cr_ts_frac_digits", "cr_ts_kind"):
        d = out.setdefault(k, {})
        for b in (FRAC_BUCKETS if k == "cr_ts_frac_digits" else TS_KINDS):
            d.setdefault(b, 0)
        out[k] = {b: d[b] for b in (FRAC_BUCKETS if k == "cr_ts_frac_digits" else TS_KINDS)}
    for k in DEFINITIONS:
        if k not in ("sessions_with", "request_id_families", "api_msg_id_families", "cr_ts_frac_digits",
                     "cr_ts_kind"):
            out.setdefault(k, 0)
    out.setdefault("request_id_families", {})
    out.setdefault("api_msg_id_families", {})
    out["sessions_with"] = {name: int(caps.get(name, 0)) for name in _cap_names()}
    return {k: out[k] for k in sorted(out)}


def _cap_names() -> list[str]:
    from verifier import session as S

    return sorted(n for n in S.CAPABILITIES if not n.startswith("sidecar."))


def _share(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def headline(b: dict) -> dict:
    """The six fields the task names, as {k, n, share} per field (from one block)."""
    sw = b["sessions_with"]
    n_s = b["sessions"]

    def f(k, n):
        return {"k": k, "n": n, "share": _share(k, n)}

    return {
        "ms_timestamps": {"call_result_rows": f(b["cr_ts_ms"], b["calls"] + b["results"]),
                          "sessions_ts.ms": f(sw["ts.ms"], n_s)},
        "call_result_join": {"results_joined": f(b["results_joined"], b["results"]),
                             "calls_paired": f(b["calls_paired"], b["calls"]),
                             "sessions_join.call_id": f(sw["join.call_id"], n_s)},
        "request_ids": {"eligible_rows": f(b["request_id_rows"], b["request_id_eligible_rows"]),
                        "distinct_decodable": f(b["request_id_decodable"], b["request_id_distinct"]),
                        "sessions_request_id.decodable": f(sw["request_id.decodable"], n_s)},
        "usage": {"sessions_usage.io": f(sw["usage.io"], n_s), "sessions_usage.out": f(sw["usage.out"], n_s),
                  "responses_with_usage": b["responses_with_usage"]},
        "native_error": {"results": f(b["results_native_error"], b["results"]),
                         "sessions_error.native": f(sw["error.native"], n_s)},
        "truncation_markers": {"results_marker": f(b["results_trunc_marker"], b["results"]),
                               "results_flag": f(b["results_trunc_flag"], b["results"]),
                               "results_any": f(b["results_trunc_any"], b["results"])},
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _strata_key(corpus: str) -> bool:
    return corpus in ("tbench2", "aiv_cu", "agentcap")


def measure_split(corpus: str, split: str, session_ids: Iterable[str] | None = None) -> dict:
    """{'all': block, 'units': {unit: block}, 'strata': {stratum: block} (tbench2 log format, aiv_cu provider
    family, agentcap route)} for one corpus split."""
    ad = CORPUS_ADAPTERS[corpus]
    ids = list(session_ids) if session_ids is not None else ad.session_ids(split)
    fm = ad.formats(split, ids)
    tot, tot_caps = Counter(), Counter()
    by_u: dict[str, Counter] = defaultdict(Counter)
    by_u_caps: dict[str, Counter] = defaultdict(Counter)
    by_s: dict[str, Counter] = defaultdict(Counter)
    by_s_caps: dict[str, Counter] = defaultdict(Counter)
    for ev in ad.iter_frames(split, ids if session_ids is not None else None):
        sid = str(ev["session_id"].iat[0])
        stratum = _s(ev["stratum"].iat[0])
        fmt = fm.get(sid)
        unit = ad.unit_of(sid, stratum, fmt if corpus in ("swechat", "agentcap") else None)
        c, caps = session_counts(ev)
        tot.update(c)
        tot_caps.update(caps)
        by_u[unit].update(c)
        by_u_caps[unit].update(caps)
        if _strata_key(corpus):
            st = U.reporting_stratum(corpus, stratum, fmt) or "unknown"
            by_s[st].update(c)
            by_s_caps[st].update(caps)
    out = {"all": _block(tot, tot_caps)}
    if len(ad.units) > 1 or set(by_u) - set(ad.units):
        out["units"] = {u: _block(by_u[u], by_u_caps[u]) for u in sorted(by_u)}
    if by_s:
        out["strata"] = {s: _block(by_s[s], by_s_caps[s]) for s in sorted(by_s)}
    return out


def _pool(blocks: list[dict]) -> dict:
    """Sum blocks (same keys) - sessions are disjoint across A/B/E."""
    def add(a, b):
        for k, v in b.items():
            if isinstance(v, dict):
                add(a.setdefault(k, {}), v)
            else:
                a[k] = a.get(k, 0) + v
    acc: dict = {}
    for b in blocks:
        add(acc, b)
    return acc


def sidecar_sources(corpus: str) -> dict:
    ad = CORPUS_ADAPTERS[corpus]
    from verifier.loaders.sidecar import COPY_INDEX_SPLITS

    return {
        "cc_numlines": ("raw Claude Code JSONL reachable: " + {"swechat": "claude_code sessions",
                                                               "tbench2": "cc_jsonl sessions"}.get(corpus, "all sessions")
                        if ad.raw_numlines else None),
        "entire_tally": "SWE-chat sessions.parquet, gated on session_logs token_usage" if corpus == "swechat" else None,
        "copied_request_ids": (f"index over {'+'.join(COPY_INDEX_SPLITS[corpus])}" if corpus in COPY_INDEX_SPLITS
                               else None),
        "note": "static (from the adapter), not measured: no raw transcript is opened by this builder",
    }


def build(corpora: Iterable[str] | None = None, splits: Iterable[str] | None = None, *, include_private: bool = False,
          hash_caches: bool = True, progress: bool = False) -> dict:
    from verifier import session as S

    names = list(corpora) if corpora is not None else [c for c in CORPUS_ADAPTERS
                                                       if include_private or not CORPUS_ADAPTERS[c].private]
    want = tuple(splits) if splits is not None else ("A", "B", "E")
    excluded = {c: "private corpus (DESIGN.md §6.3): adapter available, never in a published path"
                for c, a in CORPUS_ADAPTERS.items() if a.private and c not in names}
    out_c, summary, caches = {}, {}, {}
    for corpus in names:
        ad = CORPUS_ADAPTERS[corpus]
        sp_out = {}
        for sp in ad.available_splits():
            if sp not in want:
                continue
            t0 = time.time()
            sp_out[sp] = measure_split(corpus, sp)
            p = ad.cache_path(sp)
            caches[f"{corpus}_{sp}"] = {"path": ad.cache_relpath(sp), "bytes": p.stat().st_size,
                                        "sha256": _sha256(p) if hash_caches else None}
            if progress:
                print(f"{corpus} {sp}: {sp_out[sp]['all']['sessions']} sessions, {time.time() - t0:.1f}s",
                      file=sys.stderr, flush=True)
        pooled_all = _pool([v["all"] for v in sp_out.values()])
        pooled_units = defaultdict(list)
        for v in sp_out.values():
            for u, b in v.get("units", {}).items():
                pooled_units[u].append(b)
        summary[corpus] = {"splits": sorted(sp_out), "unit": "all" if len(ad.units) > 1 else ad.units[0],
                           **headline(pooled_all)} if sp_out else {"splits": []}
        if pooled_units:
            summary[corpus]["units"] = {u: headline(_pool(bs)) for u, bs in sorted(pooled_units.items())}
        out_c[corpus] = {
            "adapter": {"loader": ad.loader, "parser": ad.parser, "units": list(ad.units), "licence": ad.licence,
                        "publishable": ad.publishable, "private": ad.private, "gated": ad.gated,
                        "notes": ad.notes, "sidecar_sources": sidecar_sources(corpus)},
            "pooled": pooled_all if sp_out else None,
            "splits": sp_out,
        }
    return {
        "schema": SCHEMA,
        "generated_by": "python -m verifier.loaders.capabilities",
        "scope": "IR caches of splits A, B and E only (the verifier never reads the held-out split). Counts are raw.",
        "provenance": {
            "ir_schema_sha": IR_SCHEMA_SHA,
            "session_module_sha256_lf": file_sha256_lf(str(Path(S.__file__).resolve())),
            "capabilities_module_sha256_lf": file_sha256_lf(str(Path(__file__).resolve())),
            "caches": caches,
        },
        "definitions": DEFINITIONS,
        "capability_names": _cap_names(),
        "truncation_markers": [{"name": n, "type": t, "pattern": p} for n, t, p in TRUNCATION_MARKERS]
        + [{"name": "swechat_dataset_cap", "type": "dataset_cap", "pattern": f"len == {SWE_CAP_LEN} and endswith "
                                                                               f"{SWE_CAP_SUFFIX!r}"}],
        "excluded": excluded,
        "summary": summary,
        "corpora": out_c,
    }


def render_table(doc: dict) -> str:
    """Plain-text summary table (one line per corpus, or per unit for multi-unit corpora)."""
    hdr = f"{'corpus/unit':28} {'sess':>6} {'ms ts':>7} {'join':>7} {'req id':>7} {'decod.':>7} {'usage':>7} " \
          f"{'nat.err':>7} {'trunc':>7}"
    lines = [hdr, "-" * len(hdr)]

    def pct(x):
        return "   -   " if x is None else f"{100 * x:6.1f}%"

    def row(name, h, n_s):
        return (f"{name:28} {n_s:>6} {pct(h['ms_timestamps']['call_result_rows']['share'])} "
                f"{pct(h['call_result_join']['results_joined']['share'])} "
                f"{pct(h['request_ids']['eligible_rows']['share'])} "
                f"{pct(h['request_ids']['distinct_decodable']['share'])} "
                f"{pct(h['usage']['sessions_usage.io']['share'])} {pct(h['native_error']['results']['share'])} "
                f"{pct(h['truncation_markers']['results_any']['share'])}")

    for corpus, s in doc["summary"].items():
        if not s.get("splits"):
            continue
        pooled = doc["corpora"][corpus]["pooled"]
        lines.append(row(corpus, s, pooled["sessions"]))
        for u, h in s.get("units", {}).items():
            n_s = h["ms_timestamps"]["sessions_ts.ms"]["n"]
            lines.append(row("  " + u, h, n_s))
    lines.append("ms ts: call/result rows with ms stamps; join: results joined to a call; req id: assistant/call/meta "
                 "rows with a request id; decod.: distinct request ids decodable (DA20); usage: sessions with "
                 "usage_in+usage_out; nat.err: results with native_error; trunc: results with a truncation marker/flag")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m verifier.loaders.capabilities", description=__doc__.split("\n\n")[0])
    ap.add_argument("--corpora", default=None, help="comma list (default: every non-private corpus)")
    ap.add_argument("--splits", default="A,B,E")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--include-private", action="store_true", help="add cc_local; --out must then be outside the repo")
    ap.add_argument("--no-hash", action="store_true", help="skip the cache sha256s (faster)")
    ap.add_argument("--print", dest="do_print", action="store_true", help="print the summary table")
    ap.add_argument("--check", action="store_true", help="rebuild and compare with --out; exit 1 on any difference")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    corpora = [c.strip() for c in a.corpora.split(",")] if a.corpora else None
    out = Path(a.out).resolve()
    if a.include_private or any(CORPUS_ADAPTERS[c].private for c in (corpora or [])):
        if out == DEFAULT_OUT.resolve() or ROOT.resolve() in out.parents:
            print("refusing: a private corpus may not be written inside the repository; pass --out outside it",
                  file=sys.stderr)
            return 2
    doc = build(corpora, [s.strip() for s in a.splits.split(",")], include_private=a.include_private,
                hash_caches=not a.no_hash, progress=True)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if a.check:
        old = out.read_text(encoding="utf-8") if out.exists() else ""
        same = old == text
        print("capabilities.json: up to date" if same else "capabilities.json: DIFFERS from a fresh build")
        return 0 if same else 1
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out}", file=sys.stderr)
    if a.do_print:
        print(render_table(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
