"""Phase E B4: corpus field inventory, provider request-id column first.

Writes RAW COUNTS ONLY to analysis/out/phase_e/b4_inventory.json. Verdicts and interpretation live in
analysis/out/phase_e/track_b/b4.json (clearly marked fields) and later in analysis/CORPUS_INVENTORY.md.
Run from the worktree root:  python -m analysis.probes.phase_e_b4_inventory

What it measures: field PRESENCE and FILL RATES. No outcome variable, no threshold, no mechanism is tuned or scored.

Split hygiene. The held-out split H (analysis/cache/samples/{swechat,aiv_cu}_EH.json key "H") is never read:
  swechat  H transcripts are skipped by session id before the file is opened; the measured set is A u B u E.
  aiv_cu   population-table rows of H sessions are dropped on load; in the raw key scan of computer_use_turns.jsonl.gz an
           H row is skipped on its fixed-offset session_id prefix (bytes 59..95) before any parse or search of its content.
  cc_local, aiv_cc, whowhen have no E/H (HELDOUT_MANIFEST.json "no_heldout"); their A u B is the whole corpus.
Population-level session and tool-call counts (all sessions) are QUOTED from the committed build reports
(analysis/out/build/*_build.json), which were written before the H split existed; this script does not recompute them.

Privacy. cc_local is private: every cc_local output is an aggregate count; no id value, text, path or date is written.
The superseded SWE-chat mirror (data/swe-chat-mirror-cfahlgren1) is not opened (README rule 8).

Definitions, fixed before the run:
  provider request id     an id the LLM provider mints per HTTP request and the harness stores in the log (Anthropic's
                          `request-id` response header -> Claude Code `requestId`). Detected two ways: (a) the IR
                          request_id column (lib/cc_jsonl.py reads entry.requestId, nested subagent entries included);
                          (b) a raw-text scan for JSON keys matching REQ_KEY_RX, with the value classified.
  provider response id    an id the provider mints per response (Anthropic msg_, Gemini responseId, OpenAI output item
                          ids). Context only: B2's claim is about request ids, but a response id with an embedded clock is
                          the nearest substitute where request ids are absent.
  decodable time          the Phase C ids-lens layouts (analysis/probes/phase_c_ids_and_clocks_in_ids.py decode()). For
                          Anthropic ids: V>>80 inside 2024-01-01..2027-01-01 ("time_format"), plus RFC 9562 version-7 and
                          variant-2 bits. These layouts were inferred from data and are UNVERIFIED against vendor docs.
                          "agrees" = first carrying event's ts minus embedded time in [-2 s, +600 s] (-3 s for 1 s ids),
                          the ids lens's pre-registered agreement band.
  tool-call coverage      call events whose own row carries a non-null request id / all call events.
  ms timestamps           events whose ts has >= 3 fractional-second digits / events.
  tool_call_id join       calls with a same-session result on call_id; calls whose id is loader-synthetic.
  token counts            call events with usage_in not null.
  error markers           results with native_error not null / true; exit_code not null; lib.ir.error_marker(text).
  truncation markers      results whose text matches a loss-type marker of the Phase A3 catalogue
                          (analysis/probes/phase_a_a3.py MARKERS restricted to LOSS_TYPES).
"""
import glob
import gzip
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool

import numpy as np
import pandas as pd

from analysis.lib import ir
from analysis.lib.stats import cluster_rate, wilson
from analysis.loaders import load_swechat as LS
from analysis.probes import phase_a_a3 as A3
from analysis.probes import phase_c_ids_and_clocks_in_ids as IDS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # analysis/
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "out", "phase_e", "b4_inventory.json")
DATA = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
N_PROC = int(os.environ.get("B4_PROCS", "16"))

REQ_KEY_RX = re.compile(
    r'"((?:x-)?(?:anthropic-|openai-|goog-|amzn-|ms-)?request[-_]?id|requestid|req[-_]id|x-amzn-requestid|'
    r'apim-request-id|cf-ray)"\s*:\s*("(?:[^"\\]|\\.)*"|null|true|false|-?\d+)', re.I)
CORR_KEY_RX = re.compile(
    r'"(trace[-_]?id|traceparent|interaction[-_]?id|response[-_]?id)"\s*:\s*("(?:[^"\\]|\\.)*"|null)', re.I)
ANTH_REQ_VALUE_RX = re.compile(r"req_(?:vrtx_|bdrk_)?01[1-9A-HJ-NP-Za-km-z]{22}(?![1-9A-HJ-NP-Za-km-z])")
SYNTH_RX = re.compile(r"^(?:synthetic:|turn:|step:)")
FRAC_RX = re.compile(r"T\d\d:\d\d:\d\d\.(\d+)")
LOSS = [(n, re.compile(p)) for n, t, p in A3.MARKERS if t in A3.LOSS_TYPES]
LOSS_PREFILTER = ("runcat", "RUNCAT", "persisted-output", "too large", "Too large", "mitted", "Total output lines",
                  "tool_output_masked", "bytes truncated")
WIN_LO, WIN_HI = IDS.WIN_LO, IDS.WIN_HI


# ------------------------------------------------------------------------------------------------------------ helpers

def value_class(v):
    """Classify a raw JSON value string from a key scan (without writing the value)."""
    if v in ("null", "true", "false"):
        return v
    if not v.startswith('"'):
        return "number"
    s = v[1:-1]
    if s == "":
        return "empty_string"
    fam = IDS.classify(s)
    return fam if fam != "other" else f"other_len{len(s)}"


def key_scan(text, acc):
    """Count request-id-like and correlation-id-like keys in raw text; values are classified, never stored."""
    if "equest" in text or "EQUEST" in text or "req_" in text:
        for m in REQ_KEY_RX.finditer(text):
            acc["req_keys"][(m.group(1).lower(), value_class(m.group(2)))] += 1
        acc["anth_req_value_occurrences"] += len(ANTH_REQ_VALUE_RX.findall(text))
    if re.search(r"(?i)trace|interaction|response", text):
        for m in CORR_KEY_RX.finditer(text):
            acc["corr_keys"][(m.group(1).lower(), value_class(m.group(2)))] += 1


def new_scan():
    return {"req_keys": Counter(), "corr_keys": Counter(), "anth_req_value_occurrences": 0}


def merge_scan(a, b):
    a["req_keys"].update(b["req_keys"])
    a["corr_keys"].update(b["corr_keys"])
    a["anth_req_value_occurrences"] += b["anth_req_value_occurrences"]


def scan_out(acc):
    return {"request_id_keys": {f"{k}|{c}": n for (k, c), n in sorted(acc["req_keys"].items())},
            "correlation_keys": {f"{k}|{c}": n for (k, c), n in sorted(acc["corr_keys"].items())},
            "anthropic_req_value_occurrences_anywhere": acc["anth_req_value_occurrences"]}


def ts_ms(s):
    d = ir.parse_ts(s) if s else None
    return d.timestamp() * 1000.0 if d else None


def anth_decode(s):
    """-> dict(time_format, v7, agree_possible) for an anthropic_req/msg id."""
    body = s.rsplit("_", 1)[1]
    v = IDS.b58(body[2:])
    top = v >> 80
    return {"time_format": WIN_LO <= top < WIN_HI, "v7": ((v >> 76) & 0xF) == 7 and ((v >> 62) & 0x3) == 2,
            "ms": float(top)}


def backend(api_msg_id):
    if api_msg_id is None:
        return "none"
    s = str(api_msg_id)
    if s.startswith("synthetic:"):
        return "loader_synthetic"
    fam = IDS.classify(s)
    if fam == "anthropic_msg":
        return ("anthropic_vertex" if s.startswith("msg_vrtx_") else "anthropic_bedrock" if s.startswith("msg_bdrk_")
                else "anthropic_first_party")
    return fam


def isnull(x):
    return x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NA or (isinstance(x, str) and x == "")


# ------------------------------------------------------------------------------------- per-session event aggregation

def agg_events(events, want_ids=True):
    """events: list of IR dicts of ONE session. Returns counters (and distinct request ids if want_ids)."""
    c = Counter()
    res_ids = set()
    for e in events:
        if e["kind"] == "result" and not isnull(e["call_id"]):
            res_ids.add(e["call_id"])
    call_ids = set()
    resp_has_req = {}
    req_first_ts = {}
    for e in events:
        k = e["kind"]
        c["events"] += 1
        ts = e["ts"]
        if not isnull(ts):
            c["events_ts"] += 1
            m = FRAC_RX.search(str(ts))
            if m and len(m.group(1)) >= 3:
                c["events_ts_ms"] += 1
        rq = None if isnull(e["request_id"]) else str(e["request_id"])
        if rq:
            c["events_with_request_id"] += 1
            t = ts_ms(ts) if not isnull(ts) else None
            if rq not in req_first_ts or (t is not None and (req_first_ts[rq] is None or t < req_first_ts[rq])):
                req_first_ts[rq] = t
        am = None if isnull(e["api_msg_id"]) else str(e["api_msg_id"])
        if am and not am.startswith("synthetic:") and k in ("call", "assistant", "meta"):
            resp_has_req[am] = resp_has_req.get(am, False) or bool(rq)
        if k == "call":
            c["calls"] += 1
            cid = None if isnull(e["call_id"]) else str(e["call_id"])
            if cid is None:
                c["calls_null_id"] += 1
            elif SYNTH_RX.match(cid):
                c["calls_synthetic_id"] += 1
            if cid and cid in res_ids:
                c["calls_joined"] += 1
            if cid:
                call_ids.add(cid)
            if not isnull(e["usage_in"]):
                c["calls_with_usage_in"] += 1
            b = backend(am)
            c[f"calls_backend|{b}"] += 1
            if rq:
                c["calls_with_request_id"] += 1
                c[f"calls_backend_with_req|{b}"] += 1
        elif k == "result":
            c["results"] += 1
            text = e["text"] if not isnull(e["text"]) else ""
            if not isnull(e["native_error"]):
                c["results_native_nonnull"] += 1
                if bool(e["native_error"]):
                    c["results_native_true"] += 1
            if not isnull(e["exit_code"]):
                c["results_exit_code_nonnull"] += 1
            if text and ir.error_marker(text):
                c["results_error_marker_text"] += 1
            if text and any(p in text for p in LOSS_PREFILTER):
                for _, rx in LOSS:
                    if rx.search(text):
                        c["results_loss_marker"] += 1
                        break
    c["results_without_call"] = sum(1 for r in res_ids if r not in call_ids)
    c["responses"] = len(resp_has_req)
    c["responses_with_request_id"] = sum(resp_has_req.values())
    for am in resp_has_req:
        c[f"responses_backend|{backend(am)}"] += 1
        if resp_has_req[am]:
            c[f"responses_backend_with_req|{backend(am)}"] += 1
    ids = {}
    if want_ids:
        for rq, t in req_first_ts.items():
            fam = IDS.classify(rq)
            d = {"fam": fam, "prefix": ("req_vrtx_" if rq.startswith("req_vrtx_") else "req_bdrk_" if rq.startswith("req_bdrk_")
                                        else "req_" if rq.startswith("req_") else "other")}
            if fam == "anthropic_req":
                dd = anth_decode(rq)
                d["time_format"], d["v7"] = dd["time_format"], dd["v7"]
                if dd["time_format"] and t is not None:
                    off = t - dd["ms"]
                    d["within_1day"] = abs(off) <= 86400000
                    d["agrees"] = -2000 <= off <= 600000
            ids[rq] = d
    return c, ids


def summarize_ids(id_maps):
    """id_maps: list of {id: info} per session -> aggregate counts over distinct ids (global) and per-session copies."""
    glob_ids = {}
    copies = 0
    for m in id_maps:
        for k, v in m.items():
            copies += 1
            if k not in glob_ids:
                glob_ids[k] = v
    c = Counter()
    for v in glob_ids.values():
        c["distinct"] += 1
        c[f"family|{v['fam']}"] += 1
        c[f"prefix|{v['prefix']}"] += 1
        if v.get("time_format"):
            c["time_format"] += 1
        if v.get("v7"):
            c["v7_version_and_variant"] += 1
        if v.get("within_1day"):
            c["time_format_within_1day_of_event"] += 1
        if v.get("agrees"):
            c["agrees_minus2s_plus600s"] += 1
    c["session_copies"] = copies
    return dict(sorted(c.items()))


def corpus_block(per_session, id_maps, sessions_total, want_ci=True):
    """per_session: list of (session_id, Counter). Returns sums + session-clustered rates for the key columns."""
    tot = Counter()
    for _, c in per_session:
        tot.update(c)
    out = {"sessions_measured": len(per_session), "sessions_total_in_corpus": sessions_total,
           "sums": dict(sorted(tot.items()))}

    def cr(num, den):
        if not want_ci:
            return None
        return cluster_rate([c.get(num, 0) for _, c in per_session], [c.get(den, 0) for _, c in per_session])
    out["rates"] = {
        "calls_with_request_id/calls": cr("calls_with_request_id", "calls"),
        "responses_with_request_id/responses": cr("responses_with_request_id", "responses"),
        "events_ts_ms/events": cr("events_ts_ms", "events"),
        "calls_joined/calls": cr("calls_joined", "calls"),
        "calls_with_usage_in/calls": cr("calls_with_usage_in", "calls"),
        "results_native_nonnull/results": cr("results_native_nonnull", "results"),
        "results_error_marker_text/results": cr("results_error_marker_text", "results"),
        "results_loss_marker/results": cr("results_loss_marker", "results"),
    }
    out["sessions_with_ge1_request_id"] = sum(1 for _, c in per_session if c.get("events_with_request_id", 0) > 0)
    out["sessions_with_ge1_call"] = sum(1 for _, c in per_session if c.get("calls", 0) > 0)
    out["sessions_with_ge1_call_and_ge1_request_id"] = sum(
        1 for _, c in per_session if c.get("calls", 0) > 0 and c.get("events_with_request_id", 0) > 0)
    out["request_ids"] = summarize_ids(id_maps)
    return out


# --------------------------------------------------------------------------------------------------------- swechat

def sw_worker(args):
    sid, fmt, stratum = args
    path = os.path.join(LS.TRANS, sid + ".jsonl")
    events, stat, text = LS.parse_session(sid, fmt, stratum, {}, path)
    c, ids = agg_events(events)
    if stat.get("exception"):
        c["parser_exception"] += 1
    acc = new_scan()
    key_scan(text, acc)
    return sid, fmt, c, ids, acc


def run_swechat():
    t0 = time.time()
    eh = json.load(open(os.path.join(CACHE, "samples", "swechat_EH.json"), encoding="utf-8"))
    ab = json.load(open(os.path.join(CACHE, "samples", "swechat.json"), encoding="utf-8"))
    H = set(eh["H"])
    allowed = set(ab["A"]) | set(ab["B"]) | set(eh["E"])
    assert not (allowed & H)
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "stratum", "format"])
    pop = pop[pop.session_id.isin(allowed)]
    assert not set(pop.session_id) & H
    jobs = sorted(zip(pop.session_id, pop.format, pop.stratum))
    by_fmt = defaultdict(list)
    ids_fmt = defaultdict(list)
    scan_fmt = defaultdict(new_scan)
    with Pool(N_PROC) as pool:
        for sid, fmt, c, ids, acc in pool.imap_unordered(sw_worker, jobs, chunksize=4):
            by_fmt[fmt].append((sid, c))
            ids_fmt[fmt].append(ids)
            merge_scan(scan_fmt[fmt], acc)
    out = {"measured_set": "A u B u E (H never opened)", "n_H_skipped": len(H), "sessions_measured": len(jobs),
           "by_format": {}, "raw_key_scan_by_format": {}}
    allc = []
    alli = []
    for fmt in sorted(by_fmt):
        out["by_format"][fmt] = corpus_block(by_fmt[fmt], ids_fmt[fmt], None)
        out["raw_key_scan_by_format"][fmt] = scan_out(scan_fmt[fmt])
        allc += by_fmt[fmt]
        alli += ids_fmt[fmt]
    out["all_formats"] = corpus_block(allc, alli, None)
    out["wall_s"] = round(time.time() - t0, 1)
    return out


# --------------------------------------------------------------------------------------------- IR caches (A u B)

def cache_sessions(corpus):
    df = pd.concat([pd.read_parquet(os.path.join(CACHE, f"{corpus}_{s}.parquet")) for s in ("A", "B")], ignore_index=True)
    df = df.astype(object).where(df.notna(), None)
    per, idm = [], []
    for sid, g in df.groupby("session_id", sort=True):
        c, ids = agg_events(g.to_dict("records"))
        per.append((sid, c))
        idm.append(ids)
    return per, idm, df


def raw_scan_files(paths, opener=open):
    acc = new_scan()
    for p in paths:
        with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key_scan(line, acc)
    return acc


def _cc_scan_worker(p):
    acc = new_scan()
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            key_scan(line, acc)
    return acc


def run_cc_local():
    t0 = time.time()
    per, idm, df = cache_sessions("cc_local")
    blk = corpus_block(per, idm, None)
    files = sorted(glob.glob(os.path.join(DATA, "claude-code-local", "**", "*.jsonl"), recursive=True))
    acc = new_scan()
    with Pool(min(N_PROC, 8)) as pool:
        for a in pool.imap_unordered(_cc_scan_worker, files, chunksize=4):
            merge_scan(acc, a)
    blk["raw_key_scan"] = scan_out(acc)
    blk["raw_key_scan_files"] = len(files)
    blk["privacy"] = "aggregates only; no id value, text, path or date written"
    blk["wall_s"] = round(time.time() - t0, 1)
    return blk


def run_aiv_cc():
    t0 = time.time()
    per, idm, df = cache_sessions("aiv_cc")
    blk = corpus_block(per, idm, None)
    acc = raw_scan_files([os.path.join(DATA, "ai-village", "claude_code_messages.jsonl.gz")], opener=gzip.open)
    blk["raw_key_scan"] = scan_out(acc)
    # Anthropic message ids (provider response ids): decodable time?
    am = [str(x) for x in df.loc[df.api_msg_id.notna(), "api_msg_id"].unique()]
    fam = Counter(IDS.classify(x) for x in am)
    tf = sum(1 for x in am if IDS.classify(x) == "anthropic_msg" and anth_decode(x)["time_format"])
    blk["provider_response_ids"] = {"distinct_api_msg_id": len(am), "families": dict(fam),
                                    "anthropic_msg_time_format": tf,
                                    "anthropic_msg_expected_by_chance": round(
                                        fam.get("anthropic_msg", 0) * (WIN_HI - WIN_LO) / 2 ** 48, 2)}
    blk["wall_s"] = round(time.time() - t0, 1)
    return blk


def run_whowhen():
    t0 = time.time()
    per, idm, df = cache_sessions("whowhen")
    blk = corpus_block(per, idm, None)
    files = sorted(glob.glob(os.path.join(DATA, "who-and-when", "Who&When", "**", "*.json"), recursive=True))
    acc = raw_scan_files(files)
    blk["raw_key_scan"] = scan_out(acc)
    blk["raw_key_scan_files"] = len(files)
    blk["wall_s"] = round(time.time() - t0, 1)
    return blk


# ---------------------------------------------------------------------------------------------------------- aiv_cu

_H_AIV = None


def _aiv_init(hset):
    global _H_AIV
    _H_AIV = hset


def _aiv_block_worker(block):
    acc = new_scan()
    n = nh = nbad = 0
    for line in block.split(b"\n"):
        if not line:
            continue
        n += 1
        if line[43:59] != b'","session_id":"':
            nbad += 1
            sid = None
        else:
            sid = line[59:95].decode("ascii", "replace")
        if sid in _H_AIV:
            nh += 1
            continue
        if b"equest" in line or b"EQUEST" in line or b"req_" in line or b"race" in line or b"nteraction" in line \
                or b"esponse" in line:
            key_scan(line.decode("utf-8", "replace"), acc)
    return n, nh, nbad, acc


def _aiv_blocks(path, size=64 << 20):
    with gzip.open(path, "rb") as fh:
        rest = b""
        while True:
            b = fh.read(size)
            if not b:
                if rest:
                    yield rest
                return
            b = rest + b
            cut = b.rfind(b"\n")
            yield b[:cut + 1]
            rest = b[cut + 1:]


def run_aiv_cu():
    t0 = time.time()
    eh = json.load(open(os.path.join(CACHE, "samples", "aiv_cu_EH.json"), encoding="utf-8"))
    H = set(eh["H"])
    cols = ["session_id", "created_at", "shape", "synthetic", "api_msg_id", "n_calls", "action", "has_usage",
            "server_timing_dur_ms", "http_date", "has_error", "has_output"]
    t = pd.read_parquet(os.path.join(CACHE, "aiv_cu_turns.parquet"), columns=cols)
    n_all = len(t)
    t = t[~t.session_id.isin(H)].reset_index(drop=True)
    out = {"measured_set": "all sessions except H", "n_H_sessions_excluded": len(H), "turn_rows_population": n_all,
           "turn_rows_measured": len(t), "sessions_measured": int(t.session_id.nunique()), "by_shape": {}}
    t["_ts"] = pd.to_datetime(t["created_at"], utc=True, format="ISO8601", errors="coerce")
    t["_ms"] = (t["_ts"] - IDS.EPOCH).dt.total_seconds() * 1000.0
    for shape, g in t.groupby("shape", sort=True):
        real = g[g.synthetic.isna()]  # synthetic holds the rule name, NaN for real rows (load_aiv_cu.py convention)
        blk = {"rows": len(g), "rows_non_synthetic": len(real), "sessions": int(g.session_id.nunique()),
               "tool_calls_n_calls_sum": int(pd.to_numeric(real.n_calls, errors="coerce").fillna(0).sum()),
               "rows_action_not_none": int((real.action.fillna("none") != "none").sum()),
               "rows_has_usage": int(real.has_usage.fillna(False).astype(bool).sum()),
               "rows_server_timing": int(real.server_timing_dur_ms.notna().sum()),
               "rows_http_date": int(real.http_date.notna().sum()),
               "rows_has_error_channel": int(real.has_error.fillna(False).astype(bool).sum()),
               "rows_api_msg_id": int(real.api_msg_id.notna().sum())}
        fam_c, res_c, dec_c = Counter(), Counter(), Counter()
        sess_dec = set()
        ids = real.loc[real.api_msg_id.notna(), ["api_msg_id", "_ms", "session_id"]]
        first = ids.groupby("api_msg_id", sort=False).agg(ms=("_ms", "min"), sid=("session_id", "first"))
        for aid, row_ms, row_sid in zip(first.index, first["ms"], first["sid"]):
            row = {"ms": row_ms, "sid": row_sid}
            fam = IDS.classify(aid, "aiv_cu", "api_msg_id")
            fam_c[fam] += 1
            emb, res, info = IDS.decode(fam, aid)
            if fam in ("anthropic_msg",):
                if not info.get("time_format"):
                    continue
                d = anth_decode(aid)
                dec_c["anthropic_v7_version_and_variant"] += int(d["v7"])
            if emb is None or not (WIN_LO <= emb < WIN_HI):
                continue
            res_c[res] += 1
            dec_c["decodable_in_window"] += 1
            sess_dec.add(row["sid"])
            off = row["ms"] - emb
            tol = 3000 if res == "s" else 2000
            if -tol <= off <= 600000:
                dec_c["agrees"] += 1
        blk["provider_response_ids"] = {"distinct": int(len(first)), "families": dict(fam_c),
                                        "decodable_in_window": dec_c["decodable_in_window"],
                                        "decodable_resolution": dict(res_c),
                                        "agrees_with_row_created_at": dec_c["agrees"],
                                        "anthropic_v7_version_and_variant": dec_c["anthropic_v7_version_and_variant"],
                                        "sessions_with_ge1_decodable": len(sess_dec)}
        out["by_shape"][shape] = blk
    # raw key scan (H rows skipped on the session_id prefix before any search of their content)
    path = os.path.join(DATA, "ai-village", "computer_use_turns.jsonl.gz")
    acc = new_scan()
    n = nh = nbad = 0
    nproc = min(N_PROC, 12)
    with Pool(nproc, initializer=_aiv_init, initargs=(H,)) as pool:
        pending = []  # bounded submission: Pool.imap would drain the generator (8.3 GB) into its task queue

        def drain(k):
            nonlocal n, nh, nbad
            while len(pending) > k:
                a, b, c_, s = pending.pop(0).get()
                n, nh, nbad = n + a, nh + b, nbad + c_
                merge_scan(acc, s)
        for blk in _aiv_blocks(path):
            pending.append(pool.apply_async(_aiv_block_worker, (blk,)))
            drain(2 * nproc)
        drain(0)
    out["raw_key_scan"] = scan_out(acc)
    out["raw_key_scan_rows"] = {"rows_read": n, "rows_skipped_H": nh, "rows_prefix_mismatch": nbad}
    out["wall_s"] = round(time.time() - t0, 1)
    return out


# ---------------------------------------------------------------------------------- external witnesses (no tool calls)

def run_collusion_wiki():
    base = os.path.join(DATA, "collusion-wiki", "full-wiki-logs")
    out = {}
    for name in ("events.jsonl", "revisions.jsonl", "pages.jsonl", "labels.jsonl"):
        fill, n = Counter(), 0
        acc = new_scan()
        tgrade = Counter()
        with open(os.path.join(base, name), encoding="utf-8") as fh:
            for line in fh:
                n += 1
                key_scan(line, acc)
                o = json.loads(line)
                for k, v in o.items():
                    if v is not None and v != "":
                        fill[k] += 1
                if "time_grade" in o:
                    tgrade[o["time_grade"]] += 1
        keep = {k: fill[k] for k in sorted(fill) if re.search(r"(?i)time|date|request|clock|uncertainty|id$|_id", k)}
        out[name] = {"rows": n, "time_and_id_field_fill": keep, "time_grade": dict(tgrade), "raw_key_scan": scan_out(acc)}
    return out


def run_urlquery():
    base = os.path.join(DATA, "urlquery-agent-activity", "urlquery-agent-activity-2026-09-22-v5")
    df = pd.read_csv(os.path.join(base, "all-reports.csv"), dtype=str)
    rid = df["report_id"].dropna()
    shape = Counter(IDS.classify(x) for x in rid)
    uv = Counter()
    for x in rid:
        if re.fullmatch(IDS.UUID_RE, x):
            uv[IDS.uuid_version(x)[0]] += 1
    acc = new_scan()
    for f in sorted(glob.glob(os.path.join(base, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            key_scan(fh.read(), acc)
    return {"rows": len(df), "columns": list(df.columns), "report_id_families": dict(shape), "report_id_uuid_versions": dict(uv),
            "timestamp_precision": dict(Counter(df["timestamp_precision"].fillna("null"))),
            "raw_key_scan_json_files": scan_out(acc)}


# ------------------------------------------------------------------------------------------------------------ main

def quoted_population():
    """Population counts quoted from committed build reports (not recomputed)."""
    sw = json.load(open(os.path.join(HERE, "out", "build", "swechat_build.json"), encoding="utf-8"))
    cc = json.load(open(os.path.join(HERE, "out", "build", "cc_local_build.json"), encoding="utf-8"))
    ac = json.load(open(os.path.join(HERE, "out", "build", "aiv_cc_build.json"), encoding="utf-8"))
    au = json.load(open(os.path.join(HERE, "out", "build", "aiv_cu_build.json"), encoding="utf-8"))
    ww = json.load(open(os.path.join(HERE, "out", "build", "whowhen_build.json"), encoding="utf-8"))
    fp = sw["full_population_pass"]
    return {
        "swechat": {"source": "analysis/out/build/swechat_build.json", "snapshot": sw["snapshot"],
                    "session_rows": sw["population"]["sessions_parquet_rows"],
                    "transcript_files": sw["population"]["transcript_files"],
                    "by_format": {f: {"files": v["files"], "calls": v["calls"], "results": v["results"]}
                                  for f, v in fp["by_format"].items()},
                    "totals": {k: fp["totals"][k] for k in ("calls", "results", "calls_without_result", "results_without_call")}},
        "cc_local": {"source": "analysis/out/build/cc_local_build.json", "sessions": cc["population"]["sessions"],
                     "calls": cc["full_corpus_ir"]["events_by_kind"]["call"],
                     "results": cc["full_corpus_ir"]["events_by_kind"]["result"],
                     "usage_fill_request_id": cc["full_corpus_ir"]["usage_fill"]},
        "aiv_cc": {"source": "analysis/out/build/aiv_cc_build.json", "runs": ac["population"]["sessions"],
                   "distinct_sdk_session_id": ac["sdk_sessions"]["distinct_sdk_session_id"],
                   "largest_sdk_session_share": ac["sdk_sessions"]["largest_sdk_session_share"],
                   "calls": ac["full_corpus_ir"]["events_by_kind"]["call"],
                   "results": ac["full_corpus_ir"]["events_by_kind"]["result"]},
        "aiv_cu": {"source": "analysis/out/build/aiv_cu_build.json", "turn_rows": au["population"]["turn_rows"],
                   "sessions_with_turns": au["population"]["sessions_with_turns"],
                   "turns_by_shape": au["population"]["turns_by_shape"],
                   "sessions_by_shape": au["population"]["sessions_by_shape"],
                   "fields_by_shape_non_synthetic": au["population"]["fields_by_shape_non_synthetic"]},
        "whowhen": {"source": "analysis/out/build/whowhen_build.json", "sessions": ww["population_sessions"],
                    "full_population_validate": ww["full_population_validate"]},
    }


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return o


def main():
    t0 = time.time()
    out = {"probe": "phase_e_b4_inventory", "script": "analysis/probes/phase_e_b4_inventory.py",
           "definitions": __doc__.split("Definitions, fixed before the run:")[1].strip(),
           "split_hygiene": "H (swechat, aiv_cu) never read; see module docstring",
           "population_quoted_from_builds": quoted_population()}
    for name, fn in (("whowhen", run_whowhen), ("aiv_cc", run_aiv_cc), ("cc_local", run_cc_local),
                     ("collusion_wiki", run_collusion_wiki), ("urlquery", run_urlquery), ("swechat", run_swechat),
                     ("aiv_cu", run_aiv_cu)):
        t1 = time.time()
        print(time.strftime("%H:%M:%S"), "start", name, file=sys.stderr, flush=True)
        out[name] = fn()
        print(time.strftime("%H:%M:%S"), "done", name, round(time.time() - t1, 1), "s", file=sys.stderr, flush=True)
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(clean(out), f, indent=1)
    out["swechat_mirror"] = {"opened": False, "reason": "superseded (analysis/README.md rule 8); note only"}
    out["runtime_s"] = round(time.time() - t0, 1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(clean(out), f, indent=1)
    print("wrote", OUT, out["runtime_s"], "s")


if __name__ == "__main__":
    main()
