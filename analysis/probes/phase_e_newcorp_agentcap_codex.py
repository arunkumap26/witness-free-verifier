"""Phase E, new-corpus measurement, group agentcap_codex: corpora `agentcap` and `pub_codex`.
Item keys: newcorp_measure_agentcap, newcorp_measure_pub_codex.

Run from the worktree root (Git Bash):
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_newcorp_agentcap_codex             build B/E caches if absent
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_newcorp_agentcap_codex --rebuild   rebuild the B/E caches first

Law (binding, committed in 669124a before any new-corpus B/E read): analysis/PREREG_E.md, analysis/prereg_e.json
(incl. change_log: the pre-registered extensions and ORCHESTRATOR DECISIONS D1-D7), analysis/probes/prereg_e_common.py
(check_frozen() runs first), the corpus calibration files analysis/out/phase_e/prereg_e_calibration_<corpus>.json (their
sha256 must equal the change_log record), and the Phase B pre-registration analysis/prereg.json + prereg_common.py.

Units (D1: the unit argument passed to every frozen function is the one the corpus builder calibrated with):
  agentcap/opencode   agentcap sessions with stratum opencode/*   -> unit argument 'swechat/opencode'
  agentcap/pi         agentcap sessions with stratum pi/*         -> unit argument 'agentcap/pi' (no pre-registered analogue)
  pub_codex           every pub_codex session                     -> unit argument 'swechat/codex'

Steps
  1. Caches. analysis/cache/<corpus>_{B,E}.parquet are built with the corpus loader's own build_split() (loader code not
     edited). D5: the session ids listed in analysis/out/phase_e/newcorp_exclusions.json are removed from the split id
     list for the duration of that call (newcorp_common.split_ids is wrapped in-process), so they are never parsed in this
     phase. H is never built, read or listed. Build reports: analysis/out/phase_e/newcorp_build_<corpus>_<split>.json.
  2. Per unit x population (B, E, B u E): the N6 field gate re-checked on the data, then every N6 row
     (S:n6_transfer_grid.rows) under its own pre-registered statistic and verdict rule:
       P1 latency, P2 knowledge precedence, P3a zero-error tail, P3b reaction (Phase B code: probe_1 / prereg_calibration,
       probe_2, probe_3, probe_4, called with the D1 unit argument); R1-R5 (field gate); N1-N5 (prereg_e_common).
     D1 threshold rule: a quantity the corpus calibration did not produce takes the pre-registered pooled value where the
     prereg defines one, else the cell is NOT_TESTABLE. Where the frozen Phase B code would look the quantity up under the
     analogue unit name (Probe 1 G90/floors, Probe 3 L75, the N1 positive-control G90), that analogue run is computed and
     stored as `analog_unit_run` labelled 'post hoc, not a verdict'; it never fills a cell.
  3. Artifact checks (S:artifact_checks) on B u E for every N1-N5 cell whose label reaches WEAK or better: AC2
     truncation, AC3 join, AC4 dominance with the D2 cluster (= corpus stratum) plus model and single session, AC5 NOT_RUN
     (no registered population table for new corpora: prereg_e_common.population_cells raises), AC1 parser audit against
     the raw source (seeded sample of 30 decision events), and the four stratification axes (tool, model, repo = stratum,
     length tercile from the corpus calibration).
  4. agentcap only, EXPLORATORY and NOT pre-registered: two-clock consistency between the serving process's `created`
     (integer seconds, from the joined SSE/JSON capture body, keyed by the provider-format response id) and the harness
     event stamps. Labelled NOT_BLIND (D6).

Labels: P1, N1, N3, N4, N5g (call->result or result->next-event latency) and the bracket / two-clock cells carry
NOT_BLIND (D6). Cells read the E verdict where E is not INSUFFICIENT_N, else the B verdict with suffix 'B only'
(S:n6_transfer_grid.fill_rule); B, E and B u E are all stored.

Reads: analysis/cache/{agentcap,pub_codex}_{B,E}.parquet (through prereg_e_common.read_cache; never A, never H), the
corpus population tables (metadata), the raw corpus files of the AC1 audit sample only (read-only), analysis/prereg.json,
analysis/prereg_e.json, the calibration files, analysis/out/probe_2.json (Phase B instrument check, copied by path).
Writes RAW NUMBERS ONLY: analysis/out/phase_e/newcorp_measure_agentcap.json, newcorp_measure_pub_codex.json.
Interpretation: analysis/notes/phase_e_newcorp_agentcap_codex.md. Secrets: the loaders redact on load; nothing here
prints or stores a text value, only counts.
"""
from analysis.probes import prereg_e_common as E

PJ = E.check_frozen()  # first: the module must be the pre-registered one

import argparse  # noqa: E402
import gc  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.lib import stats  # noqa: E402
from analysis.lib.ir import parse_ts  # noqa: E402
from analysis.loaders import newcorp_common as nc  # noqa: E402
from analysis.probes import prereg_common as pc  # noqa: E402
from analysis.probes import prereg_calibration as cal  # noqa: E402
from analysis.probes import probe_1 as p1  # noqa: E402
from analysis.probes import probe_2 as p2  # noqa: E402
from analysis.probes import probe_3 as p3  # noqa: E402
from analysis.probes import probe_4 as p4  # noqa: E402

T0 = time.time()
ROOT = E.ROOT
GROUP = "agentcap_codex"
SCRIPT = "analysis/probes/phase_e_newcorp_agentcap_codex.py"
PR = json.loads((ROOT / "analysis" / "prereg.json").read_text(encoding="utf-8"))
p3.PRE = PR
CL = PJ["change_log"]
D_DEC = next(x for x in CL if "D1_calibration_unit_proxy" in x)
EXCL = json.loads((E.OUT_E / "newcorp_exclusions.json").read_text(encoding="utf-8"))
P2_PHASE_B = json.loads((ROOT / "analysis" / "out" / "probe_2.json").read_text(encoding="utf-8"))
INSTRUMENT_OK = bool(P2_PHASE_B["instrument_check"]["ok"])
D_POOLED = int(PR["resolved"]["probe2"]["depth_threshold"]["pooled"]["D"])
G90_PB = {u: v["G90"] for u, v in PR["resolved"]["probe1"]["generation_rate"].items()}
L_PB = PR["resolved"]["probe3"]["long_session"]
TPC = PR["probe1"]["separability"]["generation_time_model"]["tokens_per_char"]  # 0.25
TH1 = p1.TH
TOL_MS = E.BRACKET_TOL_MS
COLS = ["session_id", "stratum", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "args", "command", "text",
        "stderr", "native_error", "exit_code", "usage_in", "usage_out", "api_msg_id", "request_id", "model",
        "is_subagent", "agent_id", "parent_call_id", "extra"]

CORPORA = {
    "agentcap": {"loader": "agentcap", "units": [("agentcap/opencode", "swechat/opencode", "opencode/"),
                                                  ("agentcap/pi", "agentcap/pi", "pi/")]},
    "pub_codex": {"loader": "pub_codex", "units": [("pub_codex", "swechat/codex", None)]},
}
ROWS = PJ["n6_transfer_grid"]["rows"]
NOT_BLIND_ROWS = {"P1_latency": "latency (D6)", "R1_bracket": "request-id bracket (D6)", "N3": "reaction time (D6)",
                  "N1": "call->result latency (D6 latency)", "N4": "call->result latency (D6 latency)",
                  "N5g_cold_start": "call->result latency (D6 latency)"}
LEVEL = E.LEVEL

DEVIATIONS = [
    {"item": "B/E cache build with the D5 exclusions",
     "prereg_said": "D5: the 42 B and 15 E agentcap sessions parsed in an abandoned A build are EXCLUDED from B/E "
                    "measurement; the loaders' --split path builds every id of the split",
     "what_you_did": "called the loader's build_split() unchanged with newcorp_common.split_ids wrapped in-process so the "
                     "excluded ids are dropped from the list before parsing; the per-split build report is written to "
                     "analysis/out/phase_e/newcorp_build_<corpus>_<split>.json (the name the loader CLI uses) with the "
                     "exclusion counts. pub_codex has no exclusions (the wrapper is a no-op for it)",
     "why": "excluded sessions are never parsed in this phase; the loader file (whose sha256 is in the extension record) "
            "stays byte-identical", "effect_on_verdict": "none (the excluded sessions are simply absent)"},
    {"item": "D1 threshold rule applied to Phase B thresholds",
     "prereg_said": "D1: quantities calibrate_unit did not produce for a unit take the pre-registered pooled value where the "
                    "prereg defines one, else the cell is NOT_TESTABLE. splits.new_corpora.calibration lists Probe 1 "
                    "floors/G90, Probe 3 L75 and Probe 2 D_unit among the corpus-A quantities; calibrate_unit produced none "
                    "of them",
     "what_you_did": "Probe 2 D_unit -> pooled D = 6 (prereg.json resolved.probe2.depth_threshold.pooled). Probe 1 "
                     "G90/floors and Probe 3 L75 have no pooled value -> P1_latency and P3a_zero_error cells NOT_TESTABLE "
                     "(threshold absent, D1), unless the cell's own minimum n fails independently of the threshold "
                     "(then INSUFFICIENT_N). The N1 positive control needs G90 too: N1 is INSUFFICIENT_N / DEAD where those "
                     "rules decide without rho_pc, else NOT_TESTABLE. For units whose D1 argument has Phase B thresholds "
                     "(swechat/opencode, swechat/codex) the same frozen code is run with the ANALOGUE thresholds and stored "
                     "as analog_unit_run ('post hoc, not a verdict'; swechat A-split values, not this corpus's A)",
     "why": "D1 is binding; the analogue run lets the orchestrator see what the other reading would give",
     "effect_on_verdict": "P1, P3a and possibly N1 cells NOT_TESTABLE instead of a label"},
    {"item": "agentcap/pi under the generic unit 'agentcap/pi'",
     "prereg_said": "D1: Pi traces -> unit 'agentcap/pi' (no analogue). pc.error_classes returns 'no_definition' for it; "
                    "N1/N3/N4/N5 unit lists do not name it; S:n6_transfer_grid.fill_rule: NOT_TESTABLE iff a required "
                    "field is absent, otherwise run the mechanism's rule",
     "what_you_did": "error-signal rows (P3a, P3b, N5f) NOT_TESTABLE(no error definition registered for 'agentcap/pi'; "
                     "Pi records a native isError that the frozen code does not read for this unit). Rows whose rule "
                     "needs no unit-calibrated quantity (P2 with pooled D, P4, N2 with the corpus tau, N3, N5a/b/d/e/g) run "
                     "with the generic unit; N1 runs with the pooled bounds (D1); P1 and N4 need the Phase B no-human-wait "
                     "filter, which has no allowed-class list for this unit (prereg_calibration.p1_qualified KeyError) -> "
                     "NOT_TESTABLE",
     "why": "the field gate and D1 decide; nothing is registered for Pi", "effect_on_verdict": "stated per cell"},
    {"item": "Probe 2 instrument check and antecedent status for new units",
     "prereg_said": "instrument_check is defined on swechat/claude_code main-thread S_symbol_ref (<= 0.10); its failure "
                    "caps every Probe 2 verdict",
     "what_you_did": "the Phase B instrument result (analysis/out/probe_2.json instrument_check.ok = true) is carried as "
                     "the instrument status; each unit's own main-thread S_symbol_ref is reported as context. New units are "
                     "treated as 'full' antecedent units (no DEAD -> INCONCLUSIVE relabel)",
     "why": "the instrument is a property of the matching code, validated once in Phase B", "effect_on_verdict": "none"},
    {"item": "Probe 4 redaction cap",
     "prereg_said": "swechat: verdict stands only if the redaction sensitivity run gives the same label, else WEAK",
     "what_you_did": "not applied (the cap is written for swechat units); the noredact re-run labels are stored beside "
                     "the verdict", "why": "the cap names swechat", "effect_on_verdict": "none unless a rerun differs "
                                                                                          "(stored)"},
    {"item": "N5e comparator minimum (as Track A phase_e_n5_battery)",
     "prereg_said": "WEAK if >= 0.5 of families have IQR above the comparator's CI hi; no comparator minimum stated",
     "what_you_did": "comparator = assistant text events + subagent-class call results; IQR CI = session bootstrap "
                     "(boot_stat); comparator needs >= 30 texts from >= 5 sessions (global p50 rule) else INCONCLUSIVE",
     "why": "same reading as the Track A N5 script", "effect_on_verdict": "only if the comparator is that small"},
    {"item": "N5c truncation markers",
     "prereg_said": "required field: result text with harness truncation markers (the Claude Code catalogue)",
     "what_you_did": "count results carrying a Claude Code marker (truncation_info); 0 -> NOT_TESTABLE(field absent)",
     "why": "these harnesses do not write the Claude Code elision markers", "effect_on_verdict": "none"},
    {"item": "N1 / N5g / N4 labelled NOT_BLIND",
     "prereg_said": "D6 names bracket, latency (Probe 1) and N3",
     "what_you_did": "N1, N4 and N5g also read call->result latency, which Track B B5e summarised over the full corpora; "
                     "they carry NOT_BLIND as well", "why": "same exposure", "effect_on_verdict": "label only"},
    {"item": "AC1 parser audit",
     "prereg_said": "audit_sample(): 30 decision events looked up in the raw source by (session, call_id); compare stamps, "
                    "join, text length, error flag, request id",
     "what_you_did": "implemented for the pair-based decision units of any N cell that reaches WEAK on B, E or B u E: "
                     "the raw OpenCode document / Pi JSONL / Codex rollout of the audited session is re-read and, by "
                     "call_id, the call and result stamps (ms) and the result text length are compared with the IR; "
                     "agentcap also compares the error flag and (N2) the issuing message's output-token count; N3 rows "
                     "also compare the next call's stamp. Codex error flags (joined from exec/patch/mcp end events) and "
                     "token_count usage are not compared. A text-length difference on a result carrying a loader "
                     "redaction marker counts as explained", "why": "prereg AC1",
     "effect_on_verdict": "FAIL at >= 2 of 30 -> lower label"},
]


# ================================================================================================== helpers
def clean(o):
    return p1.clean(o)


def sha(path):
    return E.sha256_file(path)


def lvl(x):
    return LEVEL.get(x)


def lower(a, b):
    if a not in LEVEL:
        return b if b in LEVEL else a
    if b not in LEVEL:
        return a
    return a if LEVEL[a] <= LEVEL[b] else b


def zrate(flags, sids, min_n=(30, 5)):
    """Session-clustered rate (stats.cluster_rate) with the global zero-count rule; reportable vs min n."""
    flags = np.asarray(flags, dtype=bool)
    sids = np.asarray(sids, dtype=object).astype(str)
    n, k, ns = int(len(flags)), int(flags.sum()), int(len(set(sids.tolist())))
    out = {"k": k, "n": n, "n_sessions": ns, "min_n": list(min_n)}
    if n == 0:
        out.update({"rate": None, "reportable": False})
        return out
    r = E.rate_by_session(flags, sids)
    out.update({"rate": r.get("rate"), "lo": r.get("lo"), "hi": r.get("hi")})
    if k == 0:
        out["wilson_hi_per_event"] = stats.wilson(0, n)[2]
        out["wilson_hi_per_session"] = stats.wilson(0, ns)[2]
        out["hi_used"] = out["wilson_hi_per_event"]
    else:
        out["hi_used"] = r.get("hi")
    out["reportable"] = bool(n >= max(min_n[0], 30) and ns >= max(min_n[1], 5))
    return out


def wil(k, n):
    if n == 0:
        return {"k": 0, "n": 0, "share": None}
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "share": p, "lo": lo, "hi": hi}


def rate_label(r, alive_pt, alive_hi, weak_pt):
    if not r.get("reportable"):
        return "INSUFFICIENT_N"
    if r["rate"] <= alive_pt and r["hi_used"] <= alive_hi:
        return "ALIVE"
    if r["rate"] <= weak_pt:
        return "WEAK"
    return "DEAD"


def shellish(k):
    return k == "shell" or k in pc.CODEX_SHELL_RAW or str(k).endswith("__bash")


def shell_cmd(unit, k, a, cmd):
    return pc.shell_command(unit, k, pc.jl(a) if isinstance(a, str) else {}, cmd) if shellish(k) else None


def tbytes(t):
    return len(t.encode("utf-8")) if isinstance(t, str) else 0


# ================================================================================================== caches (step 1)
def loader_module(corpus):
    if corpus == "agentcap":
        from analysis.loaders import load_agentcap as m
    else:
        from analysis.loaders import load_pub_codex as m
    return m


def build_cache(corpus, split, force):
    path = E.CACHE / f"{corpus}_{split}.parquet"
    excl = set(EXCL.get(corpus, {}).get(split, []))
    ids_all = E.split_ids(corpus, split)
    want = sorted(set(ids_all) - excl)
    info = {"split": split, "split_ids": len(ids_all), "excluded_D5": len(excl & set(ids_all)),
            "excluded_D5_listed": len(excl), "sessions_wanted": len(want)}
    if force or not path.exists():
        mod = loader_module(corpus)
        orig = nc.split_ids

        def wrapped(c, s):
            ids = orig(c, s)
            if c == corpus and s == split:
                return [i for i in ids if i not in excl]
            return ids
        nc.split_ids = wrapped
        try:
            t = time.time()
            binfo = mod.build_split(split)
            binfo["runtime_s"] = round(time.time() - t, 1)
        finally:
            nc.split_ids = orig
        binfo["D5_exclusions"] = {"listed": len(excl), "in_split": info["excluded_D5"],
                                  "source": "analysis/out/phase_e/newcorp_exclusions.json", "decision": "D5",
                                  "how": "newcorp_common.split_ids wrapped in-process by " + SCRIPT}
        (E.OUT_E / f"newcorp_build_{corpus}_{split}.json").write_text(json.dumps(binfo, indent=1, default=str),
                                                                      encoding="utf-8")
        info["built_now"] = True
    else:
        info["built_now"] = False
    bpath = E.OUT_E / f"newcorp_build_{corpus}_{split}.json"
    if bpath.exists():
        b = json.loads(bpath.read_text(encoding="utf-8"))
        info["build_report"] = {k: b.get(k) for k in ("rows", "sessions", "join", "secret_redactions", "parser_stats",
                                                      "D5_exclusions", "surrogate_cells_replaced")}
        info["build_report_path"] = str(bpath.relative_to(ROOT).as_posix())
    df = E.read_cache(corpus, split, ["session_id"])
    got = set(df.session_id.unique())
    info["cache_sessions"] = len(got)
    info["cache_sha256"] = sha(path)
    info["cache_path"] = str(path.relative_to(ROOT).as_posix())
    assert not (got & excl), "an excluded D5 session is in the cache"
    assert got <= set(want), "cache holds a session outside the split id list"
    info["sessions_without_events"] = len(set(want) - got)
    return info


def load_frame(corpus, split):
    df = E.read_cache(corpus, split, COLS).reset_index(drop=True)
    return df.assign(_split=split)


# ================================================================================================== per-unit prep
def prep(unit, u):
    """Pairs with every per-pair attribute the mechanisms and checks need."""
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    Q = E.qualify_pairs(unit, u, P)
    Q["n1"] = [E.n1_key(unit, k, a, c) for k, a, c in zip(Q.key, Q.args.astype(object), Q.command.astype(object))]
    res = [pc.error_classes(unit, k, tr, t, e, n, x, st) for k, tr, t, e, n, x, st in
           zip(Q.key, Q.tool_raw.astype(object), Q.text_r.astype(object), Q.stderr_r.astype(object),
               Q.native_error_r.astype(object), Q.exit_code_r.astype(object), Q.stratum.astype(object))]
    Q["err"] = [bool(r[0]) for r in res]
    Q["err_defined"] = [r[0] is not None for r in res]
    Q["trunc"] = [E.truncated_result(t, x) for t, x in zip(Q.text_r.astype(object), Q.extra_r.astype(object))]
    Q["jc0"] = E.join_clean_mask(u, Q)
    Q["call_id"] = Q.call_id.astype(str)
    return Q


def copied_ids(frames):
    rows = []
    for u in frames:
        c = u[(u.kind == "call") & u.call_id.notna()][["session_id", "call_id"]].drop_duplicates()
        rows.append(c)
    c = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["session_id", "call_id"])
    c = c[~c.call_id.astype(str).str.startswith("synthetic:")]
    n = c.groupby("call_id").session_id.nunique()
    return set(n[n > 1].index.astype(str))


def session_meta(u, Q, cuts):
    model = E.session_model_map(u)
    strat = u.groupby("session_id").stratum.first().astype(str).to_dict()
    npairs = Q.groupby("session_id").size().to_dict()
    allp = {s: npairs.get(s, 0) for s in u.session_id.unique()}
    lt = E.length_tercile_map(allp, cuts) if cuts else {s: "unknown" for s in allp}
    return {"model": model, "stratum": strat, "length": lt}


# ================================================================================================== field gate
def field_gate(unit, u, Q, cal_unit):
    d = Q.delta_s.to_numpy() if len(Q) else np.array([])
    req = u.request_id.dropna().astype(str)
    dec = int(sum(1 for x in req.unique() if E.decode_req_ms(x) is not None))
    img = int(u.extra.astype(object).map(lambda e: isinstance(e, str) and '"IMAGE"' in e).sum())
    resp = E.response_table(unit, u)
    gr = E.granularity(resp)
    err_def = unit in pc.SPEC["error_definitions"] and pc.SPEC["error_definitions"][unit].get("primary") is not None
    claims = 0
    for k, a, cmd, t in zip(Q.key, Q.args.astype(object), Q.command.astype(object), Q.text_r.astype(object)):
        if shellish(k) and isinstance(t, str):
            claims += len(E.commit_claims(t))
    marks = sum(1 for t in Q.text_r.astype(object) if E.truncation_info(t))
    return {"pairs": int(len(Q)), "pairs_stamped": int(np.isfinite(d).sum()),
            "pairs_distinct_stamps": int((np.isfinite(d) & (d != 0)).sum()),
            "request_ids_rows": int(len(req)), "request_ids_distinct": int(req.nunique()),
            "request_ids_decodable": dec, "image_usage_rows": img, "usage_granular": bool(gr.get("GRANULAR")),
            "granularity": gr, "error_definition": bool(err_def),
            "results_with_text": int(Q.text_r.notna().sum()) if len(Q) else 0, "commit_claims": int(claims),
            "cc_truncation_marked_results": int(marks),
            "external_commit_table": False, "raw_structured_counters": False, "external_usage_tally": False,
            "note": "external tables / raw structured counters: none exist for this corpus (calibration "
                    "n6_field_gate_corrections; prereg_e_calibration_<corpus>.json)",
            "calibration_A": cal_unit["resolved"]["n6_field_gate_A"]}


# ================================================================================================== artifact checks
def run_checks(row, D, verdict_fn, smeta, base_label, has_trunc=True, has_join=True, audit_fn=None):
    """S:artifact_checks on B u E for a cell >= WEAK. D: decision rows (session_id, tool, trunc, jc, ...);
    verdict_fn(D) -> label. Returns dict with per-check results and the effect on the label."""
    out = {"population": "B u E", "base_label_BuE": base_label}
    eff = []
    # AC2 truncation
    if has_trunc and "trunc" in D:
        lab = verdict_fn(D[~D.trunc.astype(bool)])
        fail = lab != base_label
        out["AC2_truncation"] = {"label": lab, "rows_dropped": int(D.trunc.astype(bool).sum()), "FAIL": bool(fail)}
        if fail:
            eff.append(("AC2", lab))
    else:
        out["AC2_truncation"] = {"status": "NOT_APPLICABLE", "why": "the statistic reads no result text"}
    # AC3 join
    if has_join and "jc" in D:
        lab = verdict_fn(D[D.jc.astype(bool)])
        fail = lab != base_label
        out["AC3_join"] = {"label": lab, "rows_dropped": int((~D.jc.astype(bool)).sum()), "FAIL": bool(fail)}
        if fail:
            eff.append(("AC3", lab))
    else:
        out["AC3_join"] = {"status": "NOT_APPLICABLE", "why": "decision units are not call/result joins"}
    # AC4 dominance (D2: cluster = corpus stratum; plus model and single session)
    w = D.groupby("session_id").size().to_dict()
    ac4 = {"clusters": {}}
    dominated_any, untestable, downgraded = False, False, False
    for kind in ("stratum", "model", "session"):
        cmap = {s: (s if kind == "session" else smeta[kind].get(s, "unknown")) for s in w}
        dm = E.dominance(w, cmap)
        if kind == "session":
            dom = dm.get("top_session_share_events", 0) > E.DOM_SESSION
        else:
            dom = max(dm.get("top_share_events", 0), dm.get("top_share_sessions", 0)) > E.DOM_SHARE
        ent = {"top_share_events": dm.get("top_share_events"), "top_share_sessions": dm.get("top_share_sessions"),
               "top_session_share_events": dm.get("top_session_share_events"), "n_clusters": dm.get("n_clusters"),
               "dominated": bool(dom)}
        if kind != "session":
            ent["top_cluster"] = dm.get("top_cluster")
        if dom:
            dominated_any = True
            tops = [c for c, _, _ in dm.get("top_clusters", [])][:5]
            lo_out = []
            for i, c in enumerate(tops):
                keep = [s for s in w if cmap[s] != c]
                lab = verdict_fn(D[D.session_id.isin(keep)])
                lo_out.append({"left_out": (f"session#{i + 1}" if kind == "session" else c), "label": lab})
                if i == 0 and lab == "INSUFFICIENT_N":
                    untestable = True
                if lab in LEVEL and base_label in LEVEL and LEVEL[lab] < LEVEL[base_label]:
                    downgraded = True
            ent["leave_outs"] = lo_out
        ac4["clusters"][kind] = ent
    ac4["dominated"] = dominated_any
    ac4["result"] = ("DOMINATED" if downgraded else "UNTESTABLE_WITHOUT_DOMINANT" if untestable
                     else "dominated, label stable" if dominated_any else "not dominated")
    out["AC4_dominance"] = ac4
    out["AC5_sampling"] = {"status": "NOT_RUN", "why": "no population table registered for new corpora "
                                                       "(prereg_e_common.population_cells raises for them)"}
    # AC1 parser audit
    if audit_fn is not None:
        out["AC1_parser"] = audit_fn(D)
        if out["AC1_parser"].get("FAIL"):
            eff.append(("AC1", "DEAD" if base_label == "WEAK" else E.downgrade(base_label)))
    else:
        out["AC1_parser"] = {"status": "NOT_RUN", "why": "no raw lookup implemented for this decision unit"}
    # stratification
    strata = {}
    conf = []
    for axis in ("tool", "model", "repo", "length"):
        if axis == "tool":
            keyf = D["tool"].astype(str) if "tool" in D else None
        else:
            m = smeta["stratum" if axis == "repo" else axis]
            keyf = D.session_id.map(lambda s: m.get(s, "unknown"))
        if keyf is None:
            strata[axis] = {"status": "UNTESTABLE", "why": "no tool attribute"}
            continue
        labs = {}
        for val in sorted(set(keyf)):
            lab = verdict_fn(D[(keyf == val).to_numpy()])
            labs[str(val)] = lab
        rep = {k: (v if v in LEVEL else None) for k, v in labs.items()}
        c = E.confinement(rep)
        strata[axis] = {"labels": labs, "status": c}
        if c == "CONFINED":
            conf.append(axis)
    out["stratification"] = strata
    label = base_label
    for name, lab in eff:
        label = lower(label, lab)
    if downgraded:
        label = E.downgrade(label)
    elif untestable and LEVEL.get(label, 0) > 1:
        label = "WEAK"
    if conf:
        label = E.downgrade(label)
    out["effects"] = {"failed_checks": [n for n, _ in eff], "failed_check_labels": {n: lab for n, lab in eff},
                      "dominance": ac4["result"], "confined_axes": conf}
    out["label_after_checks_BuE"] = label
    return out


# ------------------------------------------------------------------------------------------------ AC1 raw lookups
def _raw_index(corpus, sid):
    """{call_id: {call_ms, result_ms, result_chars, error}} from the raw source of one session (read-only)."""
    out = {}
    if corpus == "agentcap":
        pop = pd.read_parquet(E.CACHE / "agentcap_population.parquet", columns=["session_id", "agent", "source"])
        row = pop[pop.session_id == sid]
        if not len(row):
            return None
        path = nc.DATA / row.source.iloc[0]
        agent = row.agent.iloc[0]
        text = open(path, encoding="utf-8", errors="replace").read()
        if agent == "opencode":
            doc = json.loads(text)
            for m in doc.get("messages") or []:
                parts = (m.get("parts") or []) if isinstance(m, dict) else []
                uo = [((p.get("tokens") or {}).get("output")) for p in parts
                      if isinstance(p, dict) and p.get("type") == "step-finish"]
                uo = max([x for x in uo if isinstance(x, (int, float))], default=None)
                for part in parts:
                    if isinstance(part, dict) and part.get("type") == "tool":
                        st = part.get("state") or {}
                        tt = st.get("time") or {}
                        o = st.get("output") if st.get("status") == "completed" else st.get("error")
                        if o is not None and not isinstance(o, str):
                            o = json.dumps(o)
                        md = st.get("metadata") if isinstance(st.get("metadata"), dict) else {}
                        ec = md.get("exit")
                        out[str(part.get("callID"))] = {
                            "call_ms": tt.get("start"), "result_ms": tt.get("end"), "usage_out": uo,
                            "result_chars": len(o) if isinstance(o, str) else None,
                            "error": (st.get("status") == "error") or (isinstance(ec, int) and not isinstance(ec, bool)
                                                                       and ec != 0)}
        else:
            call_ms, call_uo = {}, {}
            for line in text.splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or d.get("type") != "message":
                    continue
                m = d.get("message") or {}
                t = parse_ts(d.get("timestamp")) if isinstance(d.get("timestamp"), str) else None
                ms = t.timestamp() * 1000 if t else None
                if m.get("role") == "assistant":
                    u_ = (m.get("usage") or {}).get("output") if isinstance(m.get("usage"), dict) else None
                    for c in m.get("content") or []:
                        if isinstance(c, dict) and c.get("type") == "toolCall":
                            call_ms[str(c.get("id"))] = ms
                            call_uo[str(c.get("id"))] = u_
                elif m.get("role") == "toolResult":
                    cid = str(m.get("toolCallId"))
                    txt = "\n".join((c.get("text") or "") if c.get("type") == "text" else "[image]"
                                    for c in (m.get("content") or []) if isinstance(c, dict)
                                    and c.get("type") in ("text", "image"))
                    out[cid] = {"call_ms": call_ms.get(cid), "result_ms": ms, "result_chars": len(txt),
                                "error": bool(m.get("isError")), "usage_out": call_uo.get(cid)}
            for cid, ms in call_ms.items():
                out.setdefault(cid, {"call_ms": ms, "result_ms": None, "result_chars": None, "error": None,
                                     "usage_out": call_uo.get(cid)})
    elif corpus == "pub_codex":
        from analysis.lib import ir as _ir
        from analysis.loaders import load_swechat as _sw
        pop = pd.read_parquet(E.CACHE / "pub_codex_population.parquet", columns=["session_id", "source"])
        row = pop[pop.session_id == sid]
        if not len(row):
            return None
        text = open(nc.DATA / row.source.iloc[0], encoding="utf-8", errors="replace").read()
        for line in text.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("type") != "response_item" or not isinstance(d.get("payload"), dict):
                continue
            q = d["payload"]
            pt = q.get("type")
            t = parse_ts(d.get("timestamp")) if isinstance(d.get("timestamp"), str) else None
            ms = t.timestamp() * 1000 if t else None
            cid = q.get("call_id")
            if not cid:
                continue
            ent = out.setdefault(str(cid), {"call_ms": None, "result_ms": None, "result_chars": None, "error": None,
                                            "usage_out": None})
            if pt in ("function_call", "custom_tool_call", "tool_search_call") and ent["call_ms"] is None:
                ent["call_ms"] = ms
            elif pt in ("function_call_output", "custom_tool_call_output", "tool_search_output") \
                    and ent["result_ms"] is None:
                o = q.get("output") if pt != "tool_search_output" else q.get("tools")
                if isinstance(o, str):
                    txt = o
                elif isinstance(o, list) and pt != "tool_search_output":
                    txt = _sw._codex_items_text(o)
                else:
                    txt = _ir.j(o)
                ent["result_ms"], ent["result_chars"] = ms, len(txt)
    return out


def make_audit(corpus, unit, Qall):
    """AC1 for pair-based decision rows (columns session_id, call_id)."""
    def audit(D):
        if corpus not in ("agentcap", "pub_codex") or "call_id" not in D:
            return {"status": "NOT_RUN", "why": "raw lookup implemented for pair-based decision units only"}
        Dd = D[D.call_id.notna()]
        keys = sorted(set(zip(Dd.session_id, Dd.call_id.astype(str))))
        uo_map = (dict(zip(zip(Dd.session_id, Dd.call_id.astype(str)), Dd.usage_out)) if "usage_out" in Dd else None)
        c2_map = (dict(zip(zip(Dd.session_id, Dd.call_id.astype(str)), Dd.call_id2)) if "call_id2" in Dd else None)
        samp = E.audit_sample(keys, seed_parts=("AC1", GROUP, unit))
        Qi = Qall.set_index(["session_id", "call_id"])
        diffs, checked, cache = 0, 0, {}
        detail = Counter()
        for s, c in samp:
            if s not in cache:
                cache[s] = _raw_index(corpus, s)
            raw = (cache[s] or {}).get(c)
            if raw is None or (s, c) not in Qi.index:
                detail["not_found"] += 1
                continue
            r = Qi.loc[(s, c)]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[0]
            checked += 1
            ir_c = parse_ts(r.ts).timestamp() * 1000 if isinstance(r.ts, str) and parse_ts(r.ts) else None
            ir_r = parse_ts(r.ts_r).timestamp() * 1000 if isinstance(r.ts_r, str) and parse_ts(r.ts_r) else None
            bad = []
            if raw["call_ms"] is not None and ir_c is not None and abs(raw["call_ms"] - ir_c) > 1:
                bad.append("call_ts")
            if raw["result_ms"] is not None and ir_r is not None and abs(raw["result_ms"] - ir_r) > 1:
                bad.append("result_ts")
            t = r.text_r if isinstance(r.text_r, str) else ""
            if raw["result_chars"] is not None and raw["result_chars"] != len(t) and "[REDACTED:loader" not in t:
                bad.append("text_length")
            if raw["error"] is not None and \
                    bool(raw["error"]) != bool(r.native_error_r if not pd.isna(r.native_error_r) else False):
                bad.append("error_flag")
            if corpus == "agentcap" and uo_map is not None and uo_map.get((s, c)) is not None \
                    and raw.get("usage_out") is not None \
                    and not pd.isna(uo_map[(s, c)]) and float(raw["usage_out"]) != float(uo_map[(s, c)]):
                bad.append("usage_out")
            c2 = c2_map.get((s, c)) if c2_map else None
            if isinstance(c2, str):
                raw2 = (cache[s] or {}).get(c2)
                r2 = Qi.loc[(s, c2)] if (s, c2) in Qi.index else None
                if isinstance(r2, pd.DataFrame):
                    r2 = r2.iloc[0]
                if raw2 is not None and r2 is not None and isinstance(r2.ts, str) and parse_ts(r2.ts) \
                        and raw2.get("call_ms") is not None \
                        and abs(raw2["call_ms"] - parse_ts(r2.ts).timestamp() * 1000) > 1:
                    bad.append("next_event_ts")
            for b in bad:
                detail[b] += 1
            diffs += int(bool(bad))
        return {"sampled": len(samp), "checked": checked, "differing": diffs, "by_field": dict(detail),
                "fields_compared": ["call_ts", "result_ts", "text_length"]
                + (["error_flag"] if corpus == "agentcap" else [])
                + (["usage_out"] if (uo_map is not None and corpus == "agentcap") else [])
                + (["next_event_ts"] if c2_map is not None else []),
                "FAIL": diffs >= E.AUDIT_FAIL, "PARSER_NOTE": diffs == 1,
                "rule": "FAIL if >= 2 of 30 differ on a field the statistic uses"}
    return audit


# ================================================================================================== Phase B probes
def run_p1_analog(unit, u):
    """Probe 1 separability with the ANALOGUE unit's Phase B thresholds (post hoc, not a verdict)."""
    if unit not in G90_PB:
        return {"status": "NOT_AVAILABLE", "why": f"no Phase B Probe 1 thresholds for unit argument {unit!r}"}
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    P = cal.p1_qualified(unit, u, P)
    G90 = G90_PB[unit]
    chars = np.array([len(t) if isinstance(t, str) else 0 for t in P.text_r.astype(object)], dtype=float)
    P = P.assign(chars_r=chars)
    Q = P[P.qualified & (P.delta_s > 0)]
    W = Q[Q.key.isin(cal.W_KEYS[unit])] if unit in cal.W_KEYS else Q[Q.cls == "auto_read"]
    W = W.assign(T=W.chars_r * TPC / G90)
    W = W.assign(r=W.delta_s / W["T"].replace(0, np.nan))
    We = W[W["T"] >= TH1["T_gen_min_s"]]
    nested = p1.nested_bad_set(unit, u)
    rows = []
    for k, d, x, s, c, mk, ch in zip(P.key, P.delta_s, P._rx, P.session_id, P.call_id.astype(str), P.marker, P.chars_r):
        if k not in cal.G_TOOLS.get(unit, set()) or mk in ("cc_permission_denied", "cc_interrupt_reject") \
                or (s, c) in nested:
            continue
        lat = cal.g_latency(unit, k, d, x)
        if lat is None or not np.isfinite(lat) or lat <= 0:
            continue
        rows.append((s, k, lat, ch))
    G = pd.DataFrame(rows, columns=["session_id", "key", "lat", "chars_r"])
    G = G.assign(T=G.chars_r * TPC / G90)
    G = G.assign(r=G.lat / G["T"].replace(0, np.nan))
    Ge = G[G["T"] >= TH1["T_gen_min_s"]]
    nW, sW, nG, sG = len(We), We.session_id.nunique(), len(Ge), Ge.session_id.nunique()
    w_ok = nW >= TH1["W_min_pairs"] and sW >= TH1["W_min_sessions"]
    g_ok = nG >= TH1["G_min_pairs"] and sG >= TH1["G_min_sessions"]
    out = {"status": "post hoc, not a verdict (analogue thresholds: prereg.json resolved.probe1 for %s, swechat A)"
                     % unit, "G90_analog": G90, "W_eligible": {"n": int(nW), "sessions": int(sW)},
           "G_eligible": {"n": int(nG), "sessions": int(sG)}, "W_qualified_positive": int(len(W)),
           "G_usable": int(len(G))}
    if w_ok:
        fp = p1.rate_from_mask(We.r.to_numpy() >= 1, We.session_id.to_numpy())
        fpl = ("ALIVE" if fp["rate"] <= TH1["fp_alive_point"] and fp["verdict_hi"] <= TH1["fp_alive_hi"]
               else "WEAK" if fp["rate"] <= TH1["fp_weak_point"] else "DEAD")
    else:
        fp, fpl = {"num": int((We.r >= 1).sum()), "den": int(nW)}, "INSUFFICIENT_N"
    if w_ok and g_ok:
        a = p1.auc_ci(np.log10(Ge.r.to_numpy()), Ge.session_id.to_numpy(), np.log10(We.r.to_numpy()),
                      We.session_id.to_numpy())
        al = ("ALIVE" if a["auc"] >= TH1["auc_alive_point"] and a.get("lo") is not None and a["lo"] >= TH1["auc_alive_lo"]
              else "WEAK" if a["auc"] >= TH1["auc_weak_point"] else "DEAD")
    else:
        a = {"auc_point_unreportable": (p1.auc_value(np.log10(Ge.r.to_numpy()), np.log10(We.r.to_numpy()))
                                        if nG and nW else None)}
        al = "INSUFFICIENT_N"
    sv = ("INSUFFICIENT_N" if fpl == "INSUFFICIENT_N" else "DEAD" if "DEAD" in (fpl, al) else
          "ALIVE" if (fpl, al) == ("ALIVE", "ALIVE") else "WEAK")
    out.update({"fp_share": fp, "fp_label": fpl, "auc": a, "auc_label": al, "separability_label_analog": sv,
                "note": "separability only; the Phase B kill tests (flat, floor step, transfer, A1 recheck) not run"})
    return out


def run_p2(unit, u):
    kinds = ["user", "system", "call", "result"] + (["assistant"] if unit == "swechat/codex" else [])
    uu = u[u.kind.isin(kinds)]
    A = {"sessions": set(), "threads": {"main": set(), "sub": set()}, "refs": [], "access": [],
         "calls": Counter(), "calls_with_any_reference": Counter(), "calls_with": Counter(),
         "redacted_path": Counter(), "redacted_ref": Counter(), "redacted_ref_first": Counter(),
         "root_status": Counter()}
    p2.process_unit(unit, uu, A)
    R = p2.ref_frame(A["refs"]) if A["refs"] else p2.ref_frame([])
    X = p2.acc_frame(A["access"]) if A["access"] else p2.acc_frame([])
    out = {"D_unit": D_POOLED, "D_source": "prereg.json resolved.probe2.depth_threshold.pooled (D1 pooled value)",
           "instrument_ok_phase_b": INSTRUMENT_OK, "sessions": len(A["sessions"]),
           "threads_with_calls": {k: len(v) for k, v in A["threads"].items()}, "strata": {}}
    for st in ("main", "sub"):
        b, sd, sa = p2.stratum_block(unit, st, R, X, D_POOLED, False)
        v = p2.verdict(unit, sd, sa, INSTRUMENT_OK, st)
        if st == "sub" and out["threads_with_calls"].get("sub", 0) == 0:
            v["note"] = "no subagent threads with calls in this unit"
        out["strata"][st] = {"verdict": v, "S_deep": sd, "S_path_any": sa,
                             "S_symbol_ref_context": b.get("S_symbol_ref"),
                             "first_try_success": (b.get("deep_first_try") or {}).get("first_try_success"),
                             "n_deep_success": (b.get("deep_first_try") or {}).get("n_deep_success"),
                             "n_deep_success_sessions": (b.get("deep_first_try") or {}).get("n_deep_success_sessions")}
    return out


def run_p3(unit, u):
    uu = u[u.kind.isin(["call", "result"])][p3.LOAD_COLS + ["ts"]].copy()
    o = p3.analyse_unit(unit, uu)
    keep = {k: o.get(k) for k in ("calls", "results", "paired_calls", "sessions_with_paired_calls",
                                  "error_status_defined_pairs", "error_rate_per_call", "sessions_with_any_primary_error",
                                  "retry", "early_late")}
    keep["zero_error_tail_analog"] = {"status": "post hoc, not a verdict (analogue L75/L90: prereg.json "
                                                "resolved.probe3.long_session.%s, swechat A)" % unit,
                                      "L75_analog": o.get("L75"), "L90_analog": o.get("L90"),
                                      "L75": o["zero_error_tail"]["L75"], "verdict_analog": o["verdict"]["zero_error_tail"]}
    keep["reaction_verdict"] = o["verdict"]["reaction"]
    keep["labels"] = o["verdict"]["labels"]
    n_calls = uu[uu.kind == "call"].groupby("session_id").size()
    keep["calls_per_session_quantiles"] = stats.describe(n_calls.to_numpy(dtype=float)) if len(n_calls) else {"n": 0}
    return keep


P4_PR, P4_TH, P4_PROV = p4.load_prereg()


def run_p4(unit, u):
    uu = u[u.kind.isin(p4.KINDS)][p4.COLS].copy()
    acc = p4.extract(unit, uu, False)
    s = p4.unit_summary(acc, P4_TH, [], swechat_cap=False)
    vals = p4.summarise_values(acc.hex, acc.ints, P4_TH)
    reruns = {}
    for var in ("noredact", "noredact_strict"):
        reruns[var] = {"hex": p4.hex_verdict(vals[var]["hex"]["T_orig"], vals[var]["hex"]["M_git"],
                                             vals[var]["hex"]["M_all"], P4_TH)[0],
                       "round": p4.round_verdict(vals[var]["ints"]["T_orig"], vals[var]["ints"]["M_all"], P4_TH)[0]}
    v = s["verdicts"]
    return {"hex": {"verdict": v["hex_primary"]["verdict"], "reason": v["hex_primary"]["reason"],
                    "deciding": v["hex_primary"]["deciding"]},
            "round": {"verdict": v["round_numbers_secondary"]["verdict"],
                      "reason": v["round_numbers_secondary"]["reason"],
                      "deciding": v["round_numbers_secondary"]["deciding"]},
            "redaction_reruns_context": reruns, "sessions": s["sessions"], "git_calls": s["git_calls"],
            "N_min": P4_TH["N_min"]}


# ================================================================================================== N1
N1_SPEC = PJ["n1_conditional_duration"]


def run_n1(unit, Q, bounds, G90_analog):
    q = Q[Q.qualified]
    out = {"bounds": bounds, "scopes": {}}
    for scope in ("shell", "auto_read"):
        qs = q[q.cls == scope]
        o = {"qualified_calls": int(len(qs)), "sessions": int(qs.session_id.nunique())}
        if len(qs):
            grp = qs[qs.n1.notna()].groupby(["session_id", "key", "n1"]).seq.transform("size") >= 2
            ing = pd.Series(False, index=qs.index)
            ing.loc[grp.index] = grp.to_numpy()
            num = ing.groupby(qs.session_id).sum()
            den = qs.groupby("session_id").size()
            o["RR"] = stats.cluster_rate(num.reindex(den.index).to_numpy(), den.to_numpy())
        R = E.n1_residuals(qs, unit) if len(qs) else pd.DataFrame()
        o["residuals"] = int(len(R))
        o["residual_sessions"] = int(R.session_id.nunique()) if len(R) else 0
        if len(R) >= 3:
            o["rho_hon"] = E.session_spearman(R.residual.to_numpy(), R.log_bytes.to_numpy(), R.session_id.to_numpy())
            o["rho_secondary_dlogbytes"] = E.session_spearman(R.residual.to_numpy(), R.d_log_bytes.to_numpy(),
                                                              R.session_id.to_numpy())
            fl = (R.residual < bounds[0]) | (R.residual > bounds[1])
            o["flag_rate"] = zrate(fl.to_numpy(), R.session_id.to_numpy())
            # positive control with the analogue G90 (post hoc) - one tampered instance per repeat group
            if G90_analog:
                pcr = []
                for (s, k, nk), g in qs[qs.n1.notna()].groupby(["session_id", "key", "n1"], sort=False):
                    if len(g) < 2:
                        continue
                    er = g.err.to_numpy()
                    elig = [i for i in range(len(g)) if any(er[j] == er[i] for j in range(len(g)) if j != i)]
                    if not elig:
                        continue
                    i = elig[int(E.rng_for("N1pc", s, nk).integers(0, len(elig)))]
                    ch = float(g.result_chars.iloc[i])
                    if ch <= 0:
                        continue
                    d2 = ch * TPC / G90_analog
                    ref = [math.log10(g.delta_s.iloc[j]) for j in range(len(g)) if j != i and er[j] == er[i]]
                    pcr.append((s, math.log10(d2) - float(np.median(ref)), math.log10(g.result_bytes.iloc[i] + 1)))
                if len(pcr) >= 3:
                    pr = pd.DataFrame(pcr, columns=["s", "r", "lb"])
                    o["rho_pc_analog"] = E.session_spearman(pr.r.to_numpy(), pr.lb.to_numpy(), pr.s.to_numpy())
                    o["rho_pc_analog"]["n_tampered"] = int(len(pr))
                    o["rho_pc_analog"]["G90_analog"] = G90_analog
        out["scopes"][scope] = o
    # verdict on the primary scope (shell)
    o = out["scopes"]["shell"]
    n, ns = o["residuals"], o["residual_sessions"]
    if n < 200 or ns < 20:
        lab, why = "INSUFFICIENT_N", f"shell residuals {n} from {ns} sessions (< 200 from 20)"
    elif o.get("rho_hon", {}).get("value") is not None and o["rho_hon"]["value"] > 0.15:
        lab, why = "DEAD", f"rho_hon {o['rho_hon']['value']:.3f} > 0.15"
    else:
        lab, why = "NOT_TESTABLE", "rho_pc needs G90 (not calibrated on the corpus's A; no pooled value; D1)"
    out["verdict"] = {"label": lab, "rule": why}
    if G90_analog and lab == "NOT_TESTABLE":
        out["verdict"]["analog_note"] = "rho_pc_analog stored (post hoc, not a verdict)"
    return out


# ================================================================================================== N2
def n2_rows(unit, u, Q, tau):
    resp = E.response_table(unit, u)
    gr = E.granularity(resp)
    rc = {(s, c): int(ch) for s, c, ch in zip(Q.session_id, Q.call_id, Q.result_chars)}
    meta = Q.set_index(["session_id", "call_id"])[["key", "trunc", "jc"]]
    if not len(resp) or tau is None:
        return gr, pd.DataFrame(columns=["session_id", "resp", "flag_h", "flag_pc1", "flag_pc08", "tool", "trunc",
                                         "jc", "call_id", "usage_out"])
    resp = resp.assign(last_call_id=resp.last_call_id.astype(str))
    h = E.n2_flags(resp, rc, tau)
    ex1 = {(s, r): tau * rc.get((s, c), 0) for s, r, c in zip(resp.session_id, resp.resp, resp.last_call_id)}
    ex8 = {(s, r): 0.8 * tau * rc.get((s, c), 0) for s, r, c in zip(resp.session_id, resp.resp, resp.last_call_id)}
    f1 = {(s, r): f for s, r, f in E.n2_flags(resp, rc, tau, ex1)}
    f8 = {(s, r): f for s, r, f in E.n2_flags(resp, rc, tau, ex8)}
    lc = dict(zip(zip(resp.session_id, resp.resp), resp.last_call_id))
    uo = dict(zip(zip(resp.session_id, resp.resp), resp.usage_out))
    rows = []
    for s, r, f in h:
        c = lc[(s, r)]
        m = meta.loc[(s, c)] if (s, c) in meta.index else None
        if isinstance(m, pd.DataFrame):
            m = m.iloc[0]
        rows.append({"session_id": s, "resp": r, "flag_h": f, "flag_pc1": f1[(s, r)], "flag_pc08": f8[(s, r)],
                     "tool": m["key"] if m is not None else "unknown",
                     "trunc": bool(m["trunc"]) if m is not None else False,
                     "jc": bool(m["jc"]) if m is not None else False, "call_id": c, "usage_out": uo[(s, r)]})
    return gr, pd.DataFrame(rows)


def n2_eval(D, granular=True):
    hr = zrate(D.flag_h.to_numpy(dtype=bool), D.session_id.to_numpy(), (100, 10)) if len(D) else zrate([], [], (100, 10))
    r8 = zrate(D.flag_pc08.to_numpy(dtype=bool), D.session_id.to_numpy(), (100, 10)) if len(D) else zrate([], [], (100, 10))
    r1 = zrate(D.flag_pc1.to_numpy(dtype=bool), D.session_id.to_numpy(), (100, 10)) if len(D) else zrate([], [], (100, 10))
    if not granular:
        lab, why = "DEAD", "not GRANULAR"
    elif not hr["reportable"]:
        lab, why = "INSUFFICIENT_N", f"eligible responses {hr['n']} from {hr['n_sessions']} sessions (< 100 from 10)"
    elif hr["rate"] <= 0.05 and hr["hi_used"] <= 0.10 and r8["rate"] >= 0.90:
        lab, why = "ALIVE", "honest <= 0.05 (hi <= 0.10) and recall(0.8 tau) >= 0.90"
    elif hr["rate"] <= 0.20 and r8["rate"] >= 0.50:
        lab, why = "WEAK", "honest <= 0.20 and recall(0.8 tau) >= 0.50, ALIVE fails"
    else:
        lab, why = "DEAD", "honest > 0.20 or recall(0.8 tau) < 0.50"
    return {"label": lab, "rule": why, "honest_flag_rate": hr, "recall_tau": r1, "recall_0.8tau": r8}


# ================================================================================================== N3
def n3_rows(u, Q):
    """n3_gaps() reproduced with the batch's last result tool and truncation flag (asserted identical)."""
    out = []
    tk = dict(zip(zip(Q.session_id, Q.seq_r), Q.key))
    tcid = dict(zip(zip(Q.session_id, Q.seq_r), Q.call_id))
    tr = dict(zip(zip(Q.session_id, Q.seq_r), Q.trunc))
    us = u.sort_values(["session_id", "seq"])
    thr = list(zip(us.session_id, us.is_subagent.astype("boolean").fillna(False), us.agent_id.astype(object).fillna("")))
    us = us.assign(_thr=thr)
    for _, g in us.groupby("_thr", sort=False):
        last_t, nbytes, blocked, last_seq, anytr = None, 0, False, None, False
        for kind, ts, txt, sq, ncid in zip(g.kind, g.ts.astype(object), g.text.astype(object), g.seq,
                                           g.call_id.astype(object)):
            if kind == "result":
                t = parse_ts(ts) if isinstance(ts, str) else None
                if t is not None:
                    last_t = t
                nbytes += len(txt.encode("utf-8")) if isinstance(txt, str) else 0
                last_seq = int(sq)
                anytr = anytr or bool(tr.get((g.session_id.iloc[0], int(sq)), False))
            elif kind in ("user", "system"):
                blocked = True
            elif kind in ("assistant", "call"):
                if last_t is not None and not blocked and isinstance(ts, str):
                    t = parse_ts(ts)
                    if t is not None:
                        gap = (t - last_t).total_seconds()
                        if 0 < gap <= 600:
                            s = g.session_id.iloc[0]
                            out.append({"session_id": s, "gap": gap, "bytes": nbytes,
                                        "tool": tk.get((s, last_seq), "unknown"), "trunc": anytr,
                                        "call_id": tcid.get((s, last_seq)),
                                        "call_id2": str(ncid) if kind == "call" and isinstance(ncid, str) else None})
                last_t, nbytes, blocked, last_seq, anytr = None, 0, False, None, False
    D = pd.DataFrame(out, columns=["session_id", "gap", "bytes", "tool", "trunc", "call_id", "call_id2"])
    ref = E.n3_gaps(u)
    assert len(ref) == len(D) and all(a == b for a, b in zip(ref, zip(D.session_id, D.gap, D.bytes))), \
        "n3 rows differ from prereg_e_common.n3_gaps()"
    return D


def n3_eval(D, permute=False):
    rhos = {}
    keep = []
    for s, g in D.groupby("session_id", sort=True):
        if len(g) < 20:
            continue
        gap = g.gap.to_numpy()
        if permute:
            gap = gap[E.rng_for("N3pc", s, "gaps").permutation(len(gap))]
        rhos[s] = E.spearman(gap, g.bytes.to_numpy())
        keep.append(pd.DataFrame({"s": s, "gap": gap, "bytes": g.bytes.to_numpy()}))
    elig = len(rhos)
    out = {"sessions_ge_20_gaps": elig, "gaps_total": int(len(D)), "sessions_with_gaps": int(D.session_id.nunique())}
    if elig < 20:
        out.update({"label": "INSUFFICIENT_N", "rule": f"{elig} sessions with >= 20 gaps (< 20)"})
        if elig:
            K = pd.concat(keep, ignore_index=True)
            out["rho_pooled"] = E.session_spearman(K.gap.to_numpy(), K.bytes.to_numpy(), K.s.to_numpy())
            vals = [v for v in rhos.values() if v is not None]
            out["share_rho_s_le_0"] = wil(sum(1 for v in vals if v <= 0), len(vals))
        return out
    K = pd.concat(keep, ignore_index=True)
    rp = E.session_spearman(K.gap.to_numpy(), K.bytes.to_numpy(), K.s.to_numpy())
    vals = [v for v in rhos.values() if v is not None]
    sh = wil(sum(1 for v in vals if v <= 0), len(vals))
    out.update({"rho_pooled": rp, "share_rho_s_le_0": sh, "rho_s_quantiles": stats.describe(np.array(vals, float))})
    lo = rp.get("lo")
    if lo is None:
        out.update({"label": "INSUFFICIENT_N", "rule": "pooled rho CI not reportable (< 900 valid draws)"})
    elif lo >= 0.30 and sh["share"] <= 0.10 and sh["hi"] <= 0.20:
        out.update({"label": "ALIVE", "rule": "pooled rho CI lo >= 0.30 and share(rho_s <= 0) <= 0.10 (W hi <= 0.20)"})
    elif lo > 0:
        out.update({"label": "WEAK", "rule": "pooled rho CI lo > 0; ALIVE condition fails"})
    else:
        out.update({"label": "DEAD", "rule": "pooled rho CI lo <= 0"})
    return out


# ================================================================================================== N4
def run_n4(unit, u):
    if unit not in pc.SPEC["probe1"]["no_human_wait_filter"]["allowed_classes"]:
        return {"label": "NOT_TESTABLE", "rule": "Phase B W/G populations undefined for unit %r (no allowed-class list "
                                                 "in prereg.json probe1.no_human_wait_filter; D1)" % unit}
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    PB = cal.p1_qualified(unit, u, P)
    W = PB[PB.qualified & (PB.delta_s > 0)]
    W = W[W.key.isin(cal.W_KEYS[unit])] if unit in cal.W_KEYS else W[W.cls == "auto_read"]
    G = PB[PB.key.isin(cal.G_TOOLS.get(unit, set())) & ~PB.marker.isin(["cc_permission_denied", "cc_interrupt_reject"])]
    nb = p1.nested_bad_set(unit, u)
    G = G.loc[np.array([(s, str(c)) not in nb for s, c in zip(G.session_id, G.call_id)], dtype=bool)]
    gl = [cal.g_latency(unit, k, d, x) for k, d, x in zip(G.key, G.delta_s, G._rx)]
    G = G.assign(_lat=gl)
    G = G.loc[np.array([x is not None and np.isfinite(x) and x > 0 for x in G._lat], dtype=bool)]
    out = {}
    for name, X, col in (("W", W, "delta_s"), ("G", G, "_lat")):
        k = E.inflight_counts(X) if len(X) else np.array([], dtype=int)
        X = X.assign(_k=k)
        m = X[X._k >= 2]
        o = {"pairs": int(len(X)), "pairs_k_ge_2": int(len(m)), "sessions_k_ge_2": int(m.session_id.nunique()),
             "pairs_k_ge_4": int((X._k >= 4).sum()), "k_hist": {str(a): int(b) for a, b in
                                                               sorted(Counter(X._k.tolist()).items())}}
        o["meets_min_n"] = bool(o["pairs_k_ge_2"] >= 100 and o["sessions_k_ge_2"] >= 10)
        if o["meets_min_n"]:
            def delta(groups, X=X, col=col):
                D = pd.concat(groups, ignore_index=True) if groups else X.iloc[:0]
                num, den = 0.0, 0
                for tkey, g in D.groupby("key"):
                    a, b = g[g._k >= 2][col], g[g._k == 1][col]
                    if len(a) >= 30 and len(b) >= 30:
                        num += (len(a) + len(b)) * (np.median(np.log10(a)) - np.median(np.log10(b)))
                        den += len(a) + len(b)
                return num / den if den else None
            groups = [g for _, g in X.groupby("session_id")]
            o["Delta"] = E.boot_stat(groups, delta)
        out[name] = o
    if not out["W"]["meets_min_n"]:
        out.update({"label": "INSUFFICIENT_N", "rule": f"W pairs at k >= 2: {out['W']['pairs_k_ge_2']} from "
                                                       f"{out['W']['sessions_k_ge_2']} sessions (< 100 from 10)"})
        return out
    dw = out["W"].get("Delta", {})
    if not out["G"]["meets_min_n"]:
        if dw.get("lo") is not None and (dw["lo"] > 0 or dw["hi"] < 0):
            out.update({"label": "WEAK", "rule": "Delta_W CI excludes 0 with G below min n"})
        else:
            out.update({"label": "INSUFFICIENT_N", "rule": "G below min n and Delta_W CI includes 0"})
        return out
    dg = out["G"].get("Delta", {})
    if None in (dw.get("lo"), dg.get("lo")):
        out.update({"label": "INSUFFICIENT_N", "rule": "Delta CI not reportable"})
    elif dw["hi"] < dg["lo"] or dg["hi"] < dw["lo"]:
        lab = "ALIVE" if abs(dw["value"] - dg["value"]) >= 0.10 else "WEAK"
        out.update({"label": lab, "rule": "CIs disjoint"})
    else:
        out.update({"label": "DEAD", "rule": "CIs overlap"})
    return out


# ================================================================================================== N5
def n5_rows(unit, u, Q):
    """Per-output rows for N5a-f decision units."""
    out = {}
    # a determinism
    dp = E.determinism_pairs(unit, u, Q)
    qi = Q.set_index(["session_id", "seq"])
    a = []
    for s, i, j, nk, ti, tj in dp:
        drift = E.mask_volatile(ti) != E.mask_volatile(tj)
        tmp = pd.DataFrame({"text": [tj]})
        tmp2, ok = E.atk_digit(tmp, 0)
        pcf = (E.mask_volatile(ti) != E.mask_volatile(tmp2.at[0, "text"])) if ok else False
        r = qi.loc[(s, j)] if (s, j) in qi.index else None
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        a.append({"session_id": s, "flag": bool(drift), "byte_identical": ti == tj, "pc_flag": bool(pcf),
                  "pc_applicable": bool(ok), "tool": r["key"] if r is not None else "unknown",
                  "trunc": False, "jc": bool(r["jc"]) if r is not None else False,
                  "call_id": r["call_id"] if r is not None else None})
    out["a"] = pd.DataFrame(a, columns=["session_id", "flag", "byte_identical", "pc_flag", "pc_applicable", "tool",
                                        "trunc", "jc", "call_id"])
    # b sort, d whitespace, c truncation, e families
    b, d, c, fam = [], [], [], []
    for s, k, a_, cmd, t, sq, tr, jc, cid in zip(Q.session_id, Q.key, Q.args.astype(object), Q.command.astype(object),
                                                 Q.text_r.astype(object), Q.seq, Q.trunc, Q.jc, Q.call_id):
        sc = shell_cmd(unit, k, a_, cmd)
        if sc:
            for name, fn in (("ls", E.ls_order_violation), ("git_log", E.gitlog_order_violation),
                             ("grep_n", E.grepn_order_violation)):
                v = fn(sc, t)
                if v is not None:
                    tmp2, ok = E.atk_reorder_lines(pd.DataFrame({"text": [t]}), 0, E.rng_for("N5bpc", s, sq, name))
                    pv = fn(sc, tmp2.at[0, "text"]) if ok else None
                    b.append({"session_id": s, "checker": name, "flag": bool(v), "pc_flag": bool(pv),
                              "pc_applicable": bool(ok), "tool": k, "trunc": bool(tr), "jc": bool(jc), "call_id": cid})
            ws = E.ws_violations(sc, t)
            if ws:
                wsn = E.ws_violations(sc, E.normalize_ws(t))
                for name, v in ws.items():
                    d.append({"session_id": s, "checker": name, "flag": bool(v), "pc_flag": bool(wsn.get(name, False)),
                              "pc_applicable": name in wsn, "tool": k, "trunc": bool(tr), "jc": bool(jc),
                              "call_id": cid})
            progs = E.command_programs(sc)
            if progs:
                f = progs[0][0]
                if f == "git":
                    m = re.search(r"\bgit\s+(?:-C\s+\S+\s+|--no-pager\s+)*([a-z\-]+)", progs[0][1])
                    f = "git " + (m.group(1) if m else "?")
                fam.append({"session_id": s, "family": f, "log_b": math.log10(tbytes(t) + 1), "tool": k,
                            "trunc": bool(tr), "jc": bool(jc), "call_id": cid})
        if k == "grep":
            v = E.grepn_order_violation(a_, t, is_grep_tool=True)
            if v is not None:
                tmp2, ok = E.atk_reorder_lines(pd.DataFrame({"text": [t]}), 0, E.rng_for("N5bpc", s, sq, "grep_tool"))
                pv = E.grepn_order_violation(a_, tmp2.at[0, "text"], is_grep_tool=True) if ok else None
                b.append({"session_id": s, "checker": "grep_n", "flag": bool(v), "pc_flag": bool(pv),
                          "pc_applicable": bool(ok), "tool": k, "trunc": bool(tr), "jc": bool(jc), "call_id": cid})
        ti = E.truncation_info(t)
        if ti:
            c.append({"session_id": s, "item": ti["item"], **{kk: vv for kk, vv in ti.items() if kk != "item"}})
    cols = ["session_id", "checker", "flag", "pc_flag", "pc_applicable", "tool", "trunc", "jc", "call_id"]
    out["b"] = pd.DataFrame(b, columns=cols)
    out["d"] = pd.DataFrame(d, columns=cols)
    out["c"] = pd.DataFrame(c)
    out["e_fam"] = pd.DataFrame(fam, columns=["session_id", "family", "log_b", "tool", "trunc", "jc", "call_id"])
    # comparator: assistant text + subagent-class call results
    comp = [(s, math.log10(tbytes(t) + 1)) for s, k, t in zip(u.session_id, u.kind, u.text.astype(object))
            if k == "assistant" and isinstance(t, str) and t.strip()]
    sub = Q[Q.cls == "subagent"]
    comp += [(s, math.log10(tbytes(t) + 1)) for s, t in zip(sub.session_id, sub.text_r.astype(object))
             if isinstance(t, str)]
    out["e_comp"] = pd.DataFrame(comp, columns=["session_id", "log_b"])
    # f error fidelity
    out["f"] = E.error_fidelity_checks(unit, u, Q)
    return out


def n5_rate_eval(D, alive_pt, alive_hi, weak_pt, min_n=(100, 20)):
    r = zrate(D.flag.to_numpy(dtype=bool), D.session_id.to_numpy(), min_n) if len(D) else zrate([], [], min_n)
    lab = rate_label(r, alive_pt, alive_hi, weak_pt)
    out = {"label": lab, "violation": r}
    pa = D[D.pc_applicable.astype(bool)] if len(D) and "pc_applicable" in D else D.iloc[:0]
    if len(pa):
        out["positive_control_recall"] = zrate(pa.pc_flag.to_numpy(dtype=bool), pa.session_id.to_numpy(), (1, 1))
    return out


def iqr(v):
    v = np.asarray(v, dtype=float)
    return float(np.quantile(v, 0.75) - np.quantile(v, 0.25)) if len(v) else None


def iqr_boot(D):
    groups = [g.log_b.to_numpy() for _, g in D.groupby("session_id", sort=True)]
    return E.boot_stat(groups, lambda gs: iqr(np.concatenate(gs)) if gs else None)


def n5e_eval(F, C):
    comp = {"texts": int(len(C)), "sessions": int(C.session_id.nunique()) if len(C) else 0}
    if comp["texts"] < 30 or comp["sessions"] < 5:
        return {"label": "INCONCLUSIVE", "rule": "comparator < 30 texts from 5 sessions", "comparator": comp}
    comp["iqr"] = iqr_boot(C)
    g = F.groupby("family").agg(n=("session_id", "size"), s=("session_id", "nunique")) if len(F) else pd.DataFrame()
    fams = [f for f, r in g.iterrows() if r.n >= 100 and r.s >= 10] if len(g) else []
    out = {"comparator": comp, "families_meeting_min": len(fams), "families_total": int(len(g))}
    if not fams:
        out.update({"label": "INSUFFICIENT_N", "rule": "no family with >= 100 results from >= 10 sessions"})
        return out
    hi = comp["iqr"].get("hi")
    if hi is None:
        out.update({"label": "INSUFFICIENT_N", "rule": "comparator CI not reportable"})
        return out
    per = {}
    above = 0
    for f in fams:
        b = iqr_boot(F[F.family == f])
        per[f] = {"n": int(g.loc[f, "n"]), "sessions": int(g.loc[f, "s"]), "iqr": b}
        above += int(b["value"] > hi)
    out["families"] = per
    out["share_above"] = above / len(fams)
    out.update({"label": "WEAK" if above / len(fams) >= 0.5 else "DEAD",
                "rule": ">= 0.5 of families above comparator CI hi -> WEAK (cap), else DEAD"})
    return out


def n5f_eval(rows):
    if not rows:
        return {"label": "INSUFFICIENT_N", "rule": "0 checkable frames (< 100 from 20 sessions)", "frames": 0}
    D = pd.DataFrame(rows, columns=["session_id", "seq", "pk", "line", "faithful"])
    r = zrate(~D.faithful.to_numpy(dtype=bool), D.session_id.to_numpy(), (100, 20))
    return {"label": rate_label(r, 0.02, 0.05, 0.10), "infidelity": r, "frames": int(len(D))}


def n5g_eval(Qq):
    cs = E.cold_start_values(Qq)
    out = {"eligible_sessions": len(cs)}
    if len(cs) < 30:
        out.update({"label": "INSUFFICIENT_N", "rule": f"{len(cs)} eligible sessions (< 30)"})
        if cs:
            out["share_c_le_0"] = wil(sum(1 for _, _, c in cs if c <= 0), len(cs))
            out["median_c"] = float(np.median([c for _, _, c in cs]))
        return out
    v = np.array([c for _, _, c in cs], dtype=float)
    s = [x for x, _, _ in cs]
    med = stats.cluster_quantile(v, s, 0.5)
    sh = wil(int((v <= 0).sum()), len(v))
    # positive control: the first call's delta replaced by a later call's delta (no cold start)
    rec = []
    for sid, g in Qq.sort_values(["session_id", "seq"]).groupby("session_id", sort=False):
        if not len(g):
            continue
        t = g.key.value_counts().index[0]
        h = g[g.key == t]
        if len(h) < 6:
            continue
        lg = np.log10(h.delta_s.to_numpy())
        j = 1 + int(E.rng_for("N5gpc", sid).integers(0, len(lg) - 1))
        rec.append(float(lg[j] - np.median(lg[1:])) <= 0)
    out.update({"median_c": med, "share_c_le_0": sh, "positive_control_recall": wil(sum(rec), len(rec))})
    if med.get("lo") is not None and med["lo"] >= math.log10(1.5) and sh["share"] <= 0.05:
        out.update({"label": "ALIVE", "rule": "median c CI lo >= log10 1.5 and share(c <= 0) <= 0.05"})
    elif med.get("lo") is not None and med["lo"] > 0:
        out.update({"label": "WEAK", "rule": "median c CI lo > 0"})
    else:
        out.update({"label": "DEAD", "rule": "median c CI lo <= 0"})
    return out


# ================================================================================================== EXPLORATORY two-clock
def two_clock(u, D_list=(5, 30)):
    """EXPLORATORY, NOT pre-registered. Inequality per joined response k (one provider-format response id):
         ts(prev input of the stream) <= server_time(first chunk) <= ts(first harness event of the response)
       with server_time in [c_k, c_k + 1 s) (`created` is integer seconds) and an unknown constant harness-minus-server
       offset theta per stream:  lo_k = prev_ms - (c_k + 1 s) <= theta <= hi_k = first_ms - c_k.
       Stream inconsistent if max lo - min hi > 2,000 ms (the frozen R1 tolerance; prereg_e_common.bracket_streams).
       Absolute variant (theta = 0): response violates if lo_k > 2,000 ms or hi_k < -2,000 ms."""
    u = u.assign(_ms=E._ms(u.ts), _stream=E._stream(u.is_subagent, u.agent_id))
    R = u[u.request_id.notna() & np.isfinite(u._ms)].sort_values(["session_id", "seq"])
    R = R.drop_duplicates(["session_id", "request_id"])
    caps = []
    for e in R.extra.astype(object):
        x = pc.jl(e)
        c = x.get("capture") or {}
        caps.append((c.get("resp_created_first_s"), c.get("resp_created_last_s"), c.get("join"), c.get("provider"),
                     c.get("served_by"), x.get("request_start_ms")))
    R = R.assign(c_first=[a[0] for a in caps], c_last=[a[1] for a in caps], join=[a[2] for a in caps],
                 provider=[a[3] for a in caps], served_by=[a[4] for a in caps], req_start_ms=[a[5] for a in caps])
    n_ids = int(len(R))
    R = R[R.c_first.notna()]
    inp = u[u.kind.isin(["result", "user"]) & np.isfinite(u._ms)][["session_id", "_stream", "seq", "_ms", "kind"]]
    inp = inp.sort_values("seq").rename(columns={"seq": "prev_seq", "_ms": "prev_ms", "kind": "prev_kind"})
    M = pd.merge_asof(R.sort_values("seq")[["session_id", "_stream", "seq", "_ms", "c_first", "c_last", "join",
                                            "provider", "served_by", "req_start_ms", "request_id", "stratum"]],
                      inp, left_on="seq", right_on="prev_seq", by=["session_id", "_stream"], direction="backward",
                      allow_exact_matches=False)
    M = M.rename(columns={"_stream": "stream", "_ms": "first_ms"})
    M["emb"] = M.c_first.astype(float) * 1000.0
    M["lo"] = M.prev_ms - (M.emb + 1000.0)
    M["hi"] = M.first_ms - M.emb
    M = M.sort_values(["session_id", "stream", "seq"]).reset_index(drop=True)
    out = {"inequality": ("per joined response k: ts(last result/user event of the stream before the response) <= "
                          "server time of the first chunk <= ts(first harness event of the response); server time "
                          "in [created_k, created_k + 1 s); one unknown constant harness-minus-server offset theta per "
                          "stream: max_k(prev_ms_k - created_k - 1 s) - min_k(first_ms_k - created_k) <= 2,000 ms "
                          "(R1 tolerance). Absolute variant: theta = 0."),
           "clock_witness": "created = integer seconds of the serving process (local llama.cpp-style server or the HF "
                            "Router), from the capture body joined by response id / tool-call id / position; operator-side, "
                            "not a first-party provider clock",
           "responses_with_id": n_ids, "responses_with_created": int(len(M)),
           "responses_with_prev_input": int(M.prev_ms.notna().sum()),
           "by_join": {str(k): int(v) for k, v in M["join"].value_counts().items()}}
    if not len(M):
        out["label"] = "INSUFFICIENT_N"
        return out, M
    Mi = M[np.isfinite(M.lo)]
    viol = (Mi.lo > TOL_MS) | (Mi.hi < -TOL_MS)
    out["absolute_theta0"] = {"violation": zrate(viol.to_numpy(), Mi.session_id.to_numpy()),
                              "lower_bound_violated": int((Mi.lo > TOL_MS).sum()),
                              "upper_bound_violated": int((Mi.hi < -TOL_MS).sum()),
                              "lo_ms_quantiles": stats.describe(Mi.lo.to_numpy(float)),
                              "hi_ms_quantiles": stats.describe(Mi.hi.to_numpy(float))}
    S = E.bracket_streams(M, tol_ms=TOL_MS)
    out["absolute_theta0"]["violation_tol0"] = zrate(((Mi.lo > 0) | (Mi.hi < 0)).to_numpy(), Mi.session_id.to_numpy())
    out["streams_ge2"] = int(len(S))
    S0 = E.bracket_streams(M, tol_ms=0.0)
    out["stream_inconsistent_tol0"] = wil(int(S0.inconsistent.sum()), int(len(S0))) if len(S0) else None
    if len(S):
        out["stream_inconsistent"] = zrate(S.inconsistent.to_numpy(), S.session_id.to_numpy())
        out["stream_inconsistent_wilson"] = wil(int(S.inconsistent.sum()), int(len(S)))
        cons = S[~S.inconsistent]
        out["slack_U_minus_L_consistent_ms"] = stats.describe((cons.U - cons.L).to_numpy(float),
                                                              qs=(0.05, 0.25, 0.5, 0.75, 0.95))
        out["gap_L_minus_U_inconsistent_ms"] = stats.describe(S[S.inconsistent].gap.to_numpy(float))
        pl = {}
        for D in D_list:
            Sp = E.bracket_streams(E.placebo_shift(M, D * 1000.0, tag="TWOCLOCK"), tol_ms=TOL_MS)
            pl[f"{D}s_earlier"] = wil(int(Sp.inconsistent.sum()), int(len(Sp)))
        out["placebo_response_backdate_power"] = pl
        out["label_rule"] = "descriptive (exploratory; no verdict rule pre-registered)"
    return out, M


def two_clock_strata(M):
    out = {}
    for col in ("stratum", "join", "provider"):
        o = {}
        for val, g in M.groupby(col):
            g = g.reset_index(drop=True)
            S = E.bracket_streams(g, tol_ms=TOL_MS)
            gi = g[np.isfinite(g.lo)]
            viol = (gi.lo > TOL_MS) | (gi.hi < -TOL_MS)
            o[str(val)] = {"responses": int(len(g)), "sessions": int(g.session_id.nunique()),
                           "absolute_violation": zrate(viol.to_numpy(), gi.session_id.to_numpy()),
                           "streams_ge2": int(len(S)),
                           "stream_inconsistent": wil(int(S.inconsistent.sum()), int(len(S))) if len(S) else None}
        out[col] = o
    return out


def two_clock_pi_tight(M):
    """Pi only: request start (message.timestamp, epoch ms) as the lower bound and created_last <= response end."""
    g = M[M.req_start_ms.notna()].copy()
    if not len(g):
        return {"responses": 0}
    g["lo"] = g.req_start_ms.astype(float) - (g.emb + 1000.0)
    g["hi"] = g.first_ms - g.c_last.astype(float) * 1000.0
    S = E.bracket_streams(g.reset_index(drop=True), tol_ms=TOL_MS)
    viol = (g.lo > TOL_MS) | (g.hi < -TOL_MS)
    return {"definition": "lo_k = request_start_ms - (created_first + 1 s); hi_k = response end (Pi entry stamp) - "
                          "created_last", "responses": int(len(g)), "sessions": int(g.session_id.nunique()),
            "absolute_violation": zrate(viol.to_numpy(), g.session_id.to_numpy()),
            "streams_ge2": int(len(S)),
            "stream_inconsistent": wil(int(S.inconsistent.sum()), int(len(S))) if len(S) else None,
            "slack_U_minus_L_consistent_ms": stats.describe((S[~S.inconsistent].U - S[~S.inconsistent].L)
                                                            .to_numpy(float), qs=(0.05, 0.5, 0.95)) if len(S) else None}


# ================================================================================================== one unit
def measure_unit(corpus, label, unit, frames, cal_unit, smeta_all):
    """frames: {split: frame of this unit}. Returns {mechanism: {pop: result}} and per-pop prepared data."""
    pops = {"B": frames["B"], "E": frames["E"], "BuE": pd.concat([frames["B"], frames["E"]], ignore_index=True)}
    copied = copied_ids(list(frames.values()))
    res = defaultdict(dict)
    prepd = {}
    cuts = (cal_unit["resolved"].get("length_terciles_A") or {}).get("cuts")
    bounds = (cal_unit["resolved"].get("n1") or {}).get("bounds")
    n1_bounds = bounds or PJ["resolved"]["n1"]["swechat/codex"]["bounds"]  # pooled (D1) where the unit had none
    n1_bsrc = (cal_unit["resolved"].get("n1") or {}).get("source") if bounds else \
        "pooled bounds (prereg_e.json resolved.n1 pooled; D1: unit not in N1 units)"
    tau = (cal_unit["resolved"].get("n2") or {}).get("tau")
    for pop, u in pops.items():
        t = time.time()
        u = u.reset_index(drop=True)
        Q = prep(unit, u)
        Q["jc"] = Q.jc0.to_numpy(dtype=bool) & ~Q.call_id.isin(copied).to_numpy()
        prepd[pop] = (u, Q)
        res["_meta"][pop] = {"sessions": int(u.session_id.nunique()), "rows": int(len(u)), "pairs": int(len(Q)),
                             "qualified_pairs": int(Q.qualified.sum())}
        res["_field_gate"][pop] = field_gate(unit, u, Q, cal_unit)
        # ---- Phase B probes
        res["P1_latency"][pop] = {"analog_unit_run": run_p1_analog(unit, u) if unit in G90_PB else
                                  {"status": "NOT_AVAILABLE", "why": "no analogue unit"}}
        res["P2_knowledge"][pop] = run_p2(unit, u)
        if unit in pc.SPEC["error_definitions"]:
            res["P3"][pop] = run_p3(unit, u)
        res["P4"][pop] = run_p4(unit, u)
        # ---- N1
        res["N1"][pop] = run_n1(unit, Q, n1_bounds, G90_PB.get(unit))
        res["N1"][pop]["bounds_source"] = n1_bsrc
        # ---- N2
        gran, D2 = n2_rows(unit, u, Q, tau)
        res["N2"][pop] = {"granularity": gran, "tau": tau, **n2_eval(D2, bool(gran.get("GRANULAR")))}
        prepd[pop + "_N2"] = D2
        # ---- N3
        D3 = n3_rows(u, Q)
        res["N3"][pop] = n3_eval(D3)
        res["N3"][pop]["positive_control_permutation"] = {k: v for k, v in n3_eval(D3, permute=True).items()
                                                          if k in ("share_rho_s_le_0", "rho_pooled",
                                                                   "sessions_ge_20_gaps")}
        prepd[pop + "_N3"] = D3
        # ---- N4
        res["N4"][pop] = run_n4(unit, u)
        # ---- N5
        R5 = n5_rows(unit, u, Q)
        prepd[pop + "_N5"] = R5
        res["N5a_determinism"][pop] = n5_rate_eval(R5["a"], 0.05, 0.10, 0.20)
        if len(R5["a"]):
            res["N5a_determinism"][pop]["byte_identical"] = zrate(R5["a"].byte_identical.to_numpy(dtype=bool),
                                                                  R5["a"].session_id.to_numpy(), (1, 1))
        res["N5b_sort"][pop] = {ck: n5_rate_eval(R5["b"][R5["b"].checker == ck], 0.01, 0.03, 0.05)
                                for ck in ("ls", "git_log", "grep_n")}
        res["N5d_whitespace"][pop] = {ck: n5_rate_eval(R5["d"][R5["d"].checker == ck], 0.01, 0.03, 0.05)
                                      for ck in ("ls_long_alignment", "git_status_tab", "wc_alignment", "pytest_banner")}
        res["N5c_truncation"][pop] = {"cc_marked_results": int(len(R5["c"])),
                                      "by_item": ({k: int(v) for k, v in R5["c"]["item"].value_counts().items()}
                                                  if len(R5["c"]) else {})}
        res["N5e_size"][pop] = n5e_eval(R5["e_fam"], R5["e_comp"])
        if pc.SPEC["error_definitions"].get(unit, {}).get("primary") is not None:
            res["N5f_error_fidelity"][pop] = n5f_eval(R5["f"])
        res["N5g_cold_start"][pop] = n5g_eval(Q[Q.qualified])
        print(f"[{time.time() - T0:7.1f}s] {label} {pop}: {res['_meta'][pop]} ({time.time() - t:.1f}s)", flush=True)
        gc.collect()
    return res, prepd


# ================================================================================================== cells
def combine(lb, le, has_e=True):
    """S:n6_transfer_grid.fill_rule: E verdict where E is not INSUFFICIENT_N, else the B verdict 'B only'."""
    if has_e and le not in (None, "INSUFFICIENT_N"):
        return le, ""
    if lb is None:
        return le, ""
    return lb, (" (B only)" if lb != "INSUFFICIENT_N" and le == "INSUFFICIENT_N" else "")


def mk_cell(row, label, lb, le, lbe, dec, n, ns, ci, path, extra=None, nb=False):
    c = {"label": label, "label_B": lb, "label_E": le, "label_BuE": lbe, "deciding_number": dec, "n": n,
         "sessions": ns, "ci": ci, "json_path": path}
    sfx = []
    if nb or row in NOT_BLIND_ROWS:
        sfx.append("NOT_BLIND")
        c["not_blind_reason"] = NOT_BLIND_ROWS.get(row, "D6")
        if not str(label).startswith("NOT_TESTABLE"):
            c["label"] = f"{label} (NOT_BLIND)"
    c["suffixes"] = sfx
    if extra:
        c.update(extra)
    return c


def build_cells(corpus, label, unit, res, prepd, smeta, Qall_BuE):
    base = f"units.{label}.mechanisms"
    fgB = res["_field_gate"]["B"]
    cells = {}
    is_pi = unit == "agentcap/pi"
    err_ok = pc.SPEC["error_definitions"].get(unit, {}).get("primary") is not None
    ntd = lambda why: {"label": f"NOT_TESTABLE({why})"}  # noqa: E731

    # ---- P1
    pr = f"{base}.P1_latency"
    if is_pi:
        cells["P1_latency"] = mk_cell("P1_latency", "NOT_TESTABLE(Probe 1 no-human-wait filter and G90 undefined for "
                                      "unit 'agentcap/pi'; D1)", None, None, None, "no analogue unit", None, None, None,
                                      pr)
    else:
        a = {p: res["P1_latency"][p]["analog_unit_run"] for p in ("B", "E", "BuE")}
        cells["P1_latency"] = mk_cell(
            "P1_latency", "NOT_TESTABLE(G90/floors not calibrated on the corpus's A; no pooled value; D1)", None, None,
            None, {p: {"separability_label_analog": a[p].get("separability_label_analog"),
                       "fp": {k: a[p]["fp_share"].get(k) for k in ("num", "den", "rate", "verdict_hi")},
                       "auc": a[p]["auc"].get("auc", a[p]["auc"].get("auc_point_unreportable")),
                       "W_eligible": a[p]["W_eligible"], "G_eligible": a[p]["G_eligible"]} for p in a},
            a["BuE"]["W_eligible"]["n"], a["BuE"]["W_eligible"]["sessions"], None, pr + ".<pop>.analog_unit_run",
            {"analog_note": "post hoc, not a verdict: analogue thresholds prereg.json resolved.probe1.%s" % unit})
    # ---- P2
    pr = f"{base}.P2_knowledge"
    v = {p: res["P2_knowledge"][p]["strata"]["main"]["verdict"] for p in ("B", "E", "BuE")}
    lab, sfx = combine(v["B"]["verdict"], v["E"]["verdict"])
    src = "E" if v["E"]["verdict"] != "INSUFFICIENT_N" else "B"
    vv = v[src]
    cells["P2_knowledge"] = mk_cell(
        "P2_knowledge", lab + sfx, v["B"]["verdict"], v["E"]["verdict"], v["BuE"]["verdict"],
        {"statistic": vv.get("deciding_statistic"), "value": vv.get("value"), "k": vv.get("k"),
         "S_deep_n": res["P2_knowledge"][src]["strata"]["main"]["S_deep"].get("n"),
         "S_path_any_n": res["P2_knowledge"][src]["strata"]["main"]["S_path_any"].get("n")},
        vv.get("n", vv.get("S_path_any_n")), vv.get("n_sessions", vv.get("S_path_any_sessions")), vv.get("ci"),
        f"{pr}.{src}.strata.main.verdict",
        {"sub_stratum": {p: res["P2_knowledge"][p]["strata"]["sub"]["verdict"].get("verdict") for p in ("B", "E", "BuE")},
         "D_unit": D_POOLED, "checks": "artifact checks not required (applies_to: A1 candidates and N1-N5 cells)"})
    # ---- P3a / P3b
    if not err_ok:
        cells["P3a_zero_error"] = mk_cell("P3a_zero_error", "NOT_TESTABLE(error signal: no error definition for unit "
                                          "'agentcap/pi')", None, None, None, None, None, None, None, None)
        cells["P3b_reaction"] = mk_cell("P3b_reaction", "NOT_TESTABLE(error signal: no error definition for unit "
                                        "'agentcap/pi')", None, None, None, None, None, None, None, None)
    else:
        pr = f"{base}.P3"
        z = {p: res["P3"][p]["zero_error_tail_analog"] for p in ("B", "E", "BuE")}
        cells["P3a_zero_error"] = mk_cell(
            "P3a_zero_error", "NOT_TESTABLE(L75 not calibrated on the corpus's A; no pooled value; D1)", None, None, None,
            {p: {"analog_verdict": z[p]["verdict_analog"]["verdict"], "n_long_at_analog_L75": z[p]["L75"].get("n_long"),
                 "L75_analog": z[p]["L75_analog"]} for p in z}, None, None, None, f"{pr}.<pop>.zero_error_tail_analog",
            {"analog_note": "post hoc, not a verdict: analogue L75 prereg.json resolved.probe3.long_session.%s" % unit})
        r = {p: res["P3"][p]["reaction_verdict"] for p in ("B", "E", "BuE")}
        lab, sfx = combine(r["B"]["verdict"], r["E"]["verdict"])
        src = "E" if r["E"]["verdict"] != "INSUFFICIENT_N" else "B"
        eff = res["P3"][src]["retry"].get("effect") or {}
        dn = r[src]["deciding_number"]
        cells["P3b_reaction"] = mk_cell(
            "P3b_reaction", lab + sfx, r["B"]["verdict"], r["E"]["verdict"], r["BuE"]["verdict"],
            {"effect_R_fail_minus_R_ok": eff.get("value"), "n_fail_with_successor": dn.get("n_fail_with_successor"),
             "sessions_fail_with_successor": dn.get("sessions_fail_with_successor"),
             "n_ok_with_successor": dn.get("n_ok_with_successor")},
            dn.get("n_fail_with_successor"), dn.get("sessions_fail_with_successor"),
            [eff.get("lo"), eff.get("hi")], f"{pr}.{src}.reaction_verdict",
            {"checks": "artifact checks not required (applies_to: A1 candidates and N1-N5 cells)"})
    # ---- P4
    pr = f"{base}.P4"
    for row, key in (("P4a_hex", "hex"), ("P4b_round", "round")):
        v = {p: res["P4"][p][key] for p in ("B", "E", "BuE")}
        lab, sfx = combine(v["B"]["verdict"], v["E"]["verdict"])
        src = "E" if v["E"]["verdict"] != "INSUFFICIENT_N" else "B"
        d = v[src]["deciding"]
        if key == "hex":
            dec = {k: d.get(k) for k in ("T_orig_symbols", "N_min", "control", "control_symbols", "T_orig_w_adj",
                                         "control_w_adj_hi")}
            n, ns, ci = d.get("T_orig_symbols"), d.get("T_orig_sessions"), [d.get("T_orig_w_adj_lo"),
                                                                            d.get("T_orig_w_adj_hi")]
        else:
            dec = {k: d.get(k) for k in ("T_orig_distinct", "T_orig_last0", "M_all_last0", "M_all_last0_hi",
                                         "min_values")}
            n, ns, ci = d.get("T_orig_distinct"), d.get("T_orig_sessions"), [d.get("T_orig_last0_lo"),
                                                                             d.get("T_orig_last0_hi")]
        cells[row] = mk_cell(row, lab + sfx, v["B"]["verdict"], v["E"]["verdict"], v["BuE"]["verdict"], dec, n, ns, ci,
                             f"{pr}.{src}.{key}.deciding",
                             {"checks": "artifact checks not required (applies_to: A1 candidates and N1-N5 cells)"})
    # ---- R1-R5 (field gate)
    fg = res["_field_gate"]
    cells["R1_bracket"] = mk_cell(
        "R1_bracket", "NOT_TESTABLE(provider request ids decodable to ms)", None, None, None,
        {p: {"request_ids_distinct": fg[p]["request_ids_distinct"], "decodable": fg[p]["request_ids_decodable"]}
         for p in ("B", "E")}, None, None, None, f"units.{label}.field_gate.<pop>.request_ids_decodable",
        {"see": "exploratory_two_clock (agentcap) for the server-clock analogue" if corpus == "agentcap" else
         "Codex rollouts log no provider request id"})
    cells["R2_image"] = mk_cell("R2_image", "NOT_TESTABLE(per-response prompt IMAGE token counts)", None, None, None,
                                {p: fg[p]["image_usage_rows"] for p in ("B", "E")}, None, None, None,
                                f"units.{label}.field_gate.<pop>.image_usage_rows")
    cells["R3_git"] = mk_cell("R3_git", "NOT_TESTABLE(external commit table linked by repo)", None, None, None,
                              {p: {"commit_claims": fg[p]["commit_claims"]} for p in ("B", "E")}, None, None, None,
                              f"units.{label}.field_gate.<pop>.commit_claims")
    cells["R4_dual"] = mk_cell("R4_dual", "NOT_TESTABLE(harness structured counters toolUseResult numLines)", None,
                               None, None, None, None, None, None, f"units.{label}.field_gate.<pop>.raw_structured_counters")
    cells["R5_ledger"] = mk_cell("R5_ledger", "NOT_TESTABLE(external usage tally)", None, None, None, None, None, None,
                                 None, f"units.{label}.field_gate.<pop>.external_usage_tally")
    # ---- N1
    pr = f"{base}.N1"
    v = {p: res["N1"][p]["verdict"]["label"] for p in ("B", "E", "BuE")}
    lab, sfx = combine(v["B"], v["E"])
    src = "E" if v["E"] != "INSUFFICIENT_N" else "B"
    sh = res["N1"][src]["scopes"]["shell"]
    cells["N1"] = mk_cell("N1", lab + sfx, v["B"], v["E"], v["BuE"],
                          {"shell_residuals": sh["residuals"], "residual_sessions": sh["residual_sessions"],
                           "RR_shell": (sh.get("RR") or {}).get("rate"),
                           "rho_hon": (sh.get("rho_hon") or {}).get("value"),
                           "rule": res["N1"][src]["verdict"]["rule"]},
                          sh["residuals"], sh["residual_sessions"],
                          [(sh.get("rho_hon") or {}).get("lo"), (sh.get("rho_hon") or {}).get("hi")],
                          f"{pr}.{src}.scopes.shell", {"bounds_source": res["N1"]["B"]["bounds_source"]})
    # ---- N2
    pr = f"{base}.N2"
    v = {p: res["N2"][p]["label"] for p in ("B", "E", "BuE")}
    lab, sfx = combine(v["B"], v["E"])
    src = "E" if v["E"] != "INSUFFICIENT_N" else "B"
    h = res["N2"][src]["honest_flag_rate"]
    cells["N2"] = mk_cell("N2", lab + sfx, v["B"], v["E"], v["BuE"],
                          {"honest_flag_rate": h.get("rate"), "k": h.get("k"),
                           "recall_0.8tau": res["N2"][src]["recall_0.8tau"].get("rate"), "tau": res["N2"][src]["tau"]},
                          h.get("n"), h.get("n_sessions"), [h.get("lo"), h.get("hi_used")], f"{pr}.{src}")
    cells["N2"]["_check"] = ("N2", lambda D: n2_eval(D)["label"], prepd["BuE_N2"])
    # ---- N3
    pr = f"{base}.N3"
    v = {p: res["N3"][p]["label"] for p in ("B", "E", "BuE")}
    lab, sfx = combine(v["B"], v["E"])
    src = "E" if v["E"] != "INSUFFICIENT_N" else "B"
    rp = res["N3"][src].get("rho_pooled") or {}
    cells["N3"] = mk_cell("N3", lab + sfx, v["B"], v["E"], v["BuE"],
                          {"rho_pooled": rp.get("value"), "share_rho_s_le_0": (res["N3"][src].get("share_rho_s_le_0")
                                                                                or {}).get("share"),
                           "sessions_ge_20_gaps": res["N3"][src]["sessions_ge_20_gaps"]},
                          res["N3"][src]["gaps_total"], res["N3"][src]["sessions_ge_20_gaps"],
                          [rp.get("lo"), rp.get("hi")], f"{pr}.{src}",
                          {"unit_note": "unit not in S:n3_reaction_time.units; run under the N6 fill rule (field gate "
                                        "passes, no calibrated quantity needed)" if is_pi else None})
    cells["N3"]["_check"] = ("N3", lambda D: n3_eval(D)["label"], prepd["BuE_N3"])
    # ---- N4
    pr = f"{base}.N4"
    v = {p: res["N4"][p]["label"] for p in ("B", "E", "BuE")}
    if v["B"].startswith("NOT_TESTABLE"):
        cells["N4"] = mk_cell("N4", "NOT_TESTABLE(Phase B W/G populations undefined for unit 'agentcap/pi'; D1)",
                              None, None, None, None, None, None, None, f"{pr}.B")
    else:
        lab, sfx = combine(v["B"], v["E"])
        src = "E" if v["E"] != "INSUFFICIENT_N" else "B"
        w = res["N4"][src]["W"]
        cells["N4"] = mk_cell("N4", lab + sfx, v["B"], v["E"], v["BuE"],
                              {"W_pairs_k_ge_2": w["pairs_k_ge_2"], "W_sessions_k_ge_2": w["sessions_k_ge_2"],
                               "G_pairs_k_ge_2": res["N4"][src]["G"]["pairs_k_ge_2"],
                               "W_share_k_ge_4": (w["pairs_k_ge_4"] / w["pairs"]) if w["pairs"] else None},
                              w["pairs_k_ge_2"], w["sessions_k_ge_2"], None, f"{pr}.{src}")
    # ---- N5
    for row, key in (("N5a_determinism", None),):
        pr = f"{base}.{row}"
        v = {p: res[row][p]["label"] for p in ("B", "E", "BuE")}
        lab, sfx = combine(v["B"], v["E"])
        src = "E" if v["E"] != "INSUFFICIENT_N" else "B"
        r = res[row][src]["violation"]
        cells[row] = mk_cell(row, lab + sfx, v["B"], v["E"], v["BuE"], {"drift": r.get("rate"), "k": r.get("k")},
                             r.get("n"), r.get("n_sessions"), [r.get("lo"), r.get("hi_used")], f"{pr}.{src}.violation")
        cells[row]["_check"] = (row, lambda D: n5_rate_eval(D, 0.05, 0.10, 0.20)["label"], prepd["BuE_N5"]["a"])
    for row, cks, th in (("N5b_sort", ("ls", "git_log", "grep_n"), (0.01, 0.03, 0.05)),
                         ("N5d_whitespace", ("ls_long_alignment", "git_status_tab", "wc_alignment", "pytest_banner"),
                          (0.01, 0.03, 0.05))):
        pr = f"{base}.{row}"
        sub = {}
        best = None
        for ck in cks:
            v = {p: res[row][p][ck]["label"] for p in ("B", "E", "BuE")}
            lab, sfx = combine(v["B"], v["E"])
            src = "E" if v["E"] != "INSUFFICIENT_N" else "B"
            r = res[row][src][ck]["violation"]
            sub[ck] = {"label": lab + sfx, "label_B": v["B"], "label_E": v["E"], "label_BuE": v["BuE"],
                       "violation": r.get("rate"), "k": r.get("k"), "n": r.get("n"), "sessions": r.get("n_sessions"),
                       "json_path": f"{pr}.{src}.{ck}.violation"}
            if lab in LEVEL and (best is None or LEVEL[lab] > LEVEL.get(best[0], -1)):
                best = (lab + sfx, ck)
        tested = [ck for ck in cks if sub[ck]["label"].split(" ")[0] in LEVEL]
        if best:
            lab = best[0]
            dec = {"best_checker": best[1], **{ck: (sub[ck]["violation"], sub[ck]["n"]) for ck in cks}}
        else:
            lab = "INSUFFICIENT_N"
            dec = {ck: {"n": sub[ck]["n"], "sessions": sub[ck]["sessions"]} for ck in cks}
        cells[row] = mk_cell(row, lab, None, None, None, dec, sum((sub[c]["n"] or 0) for c in cks), None, None,
                             f"{pr}.<pop>.<checker>",
                             {"per_checker": sub, "aggregation": "row label = best per-checker label (each checker is "
                                                                 "its own pre-registered sub-item); per-checker labels "
                                                                 "stored", "checkers_testable": tested})
        ck = best[1] if best else None
        if ck is None:  # no combined label: the checker whose B u E label is highest (checks run on B u E)
            be = [(LEVEL[sub[c]["label_BuE"]], c) for c in cks if sub[c]["label_BuE"] in LEVEL]
            ck = max(be)[1] if be else None
        if ck is not None:
            Dk = prepd["BuE_N5"][row[2]][prepd["BuE_N5"][row[2]].checker == ck]
            cells[row]["_check"] = (row, lambda D, th=th: n5_rate_eval(D, *th)["label"], Dk)
            cells[row]["checked_checker"] = ck
    # N5c
    pr = f"{base}.N5c_truncation"
    nm = {p: res["N5c_truncation"][p]["cc_marked_results"] for p in ("B", "E")}
    if sum(nm.values()) == 0:
        cells["N5c_truncation"] = mk_cell("N5c_truncation", "NOT_TESTABLE(result text with harness truncation markers: "
                                          "0 Claude Code markers)", None, None, None, nm, 0, None, None,
                                          f"{pr}.<pop>.cc_marked_results")
    else:
        cells["N5c_truncation"] = mk_cell("N5c_truncation", "INSUFFICIENT_N" if max(nm.values()) < 50 else "NOT_RUN("
                                          "markers present; constants check not implemented)", None, None, None, nm,
                                          sum(nm.values()), None, None, f"{pr}.<pop>.cc_marked_results")
    # N5e
    pr = f"{base}.N5e_size"
    v = {p: res["N5e_size"][p]["label"] for p in ("B", "E", "BuE")}
    lab, sfx = combine(v["B"], v["E"])
    src = "E" if v["E"] not in ("INSUFFICIENT_N",) else "B"
    C_be = prepd["BuE_N5"]["e_comp"]
    _e_fn = lambda D, C=C_be: n5e_eval(D, C)["label"]  # noqa: E731
    cells["N5e_size"] = mk_cell("N5e_size", lab + sfx, v["B"], v["E"], v["BuE"],
                                {"families_meeting_min": res["N5e_size"][src].get("families_meeting_min"),
                                 "share_above": res["N5e_size"][src].get("share_above"),
                                 "comparator_iqr": (res["N5e_size"][src].get("comparator", {}).get("iqr") or {})
                                 .get("value")}, res["N5e_size"][src].get("families_total"), None, None, f"{pr}.{src}",
                                {"check_note": "checks hold the comparator fixed (the full B u E comparator)"})
    cells["N5e_size"]["_check"] = ("N5e_size", _e_fn, prepd["BuE_N5"]["e_fam"])
    # N5f
    pr = f"{base}.N5f_error_fidelity"
    if not err_ok:
        cells["N5f_error_fidelity"] = mk_cell("N5f_error_fidelity", "NOT_TESTABLE(error results: no error definition "
                                              "for unit 'agentcap/pi')", None, None, None, None, None, None, None, None)
    else:
        v = {p: res["N5f_error_fidelity"][p]["label"] for p in ("B", "E", "BuE")}
        lab, sfx = combine(v["B"], v["E"])
        cells["N5f_error_fidelity"] = mk_cell("N5f_error_fidelity", lab + sfx, v["B"], v["E"], v["BuE"],
                                              {p: res["N5f_error_fidelity"][p]["frames"] for p in ("B", "E")},
                                              res["N5f_error_fidelity"]["BuE"]["frames"], None, None, f"{pr}.<pop>")
    # N5g
    pr = f"{base}.N5g_cold_start"
    v = {p: res["N5g_cold_start"][p]["label"] for p in ("B", "E", "BuE")}
    lab, sfx = combine(v["B"], v["E"])
    src = "E" if v["E"] != "INSUFFICIENT_N" else "B"
    g = res["N5g_cold_start"][src]
    med = g.get("median_c")
    cells["N5g_cold_start"] = mk_cell("N5g_cold_start", lab + sfx, v["B"], v["E"], v["BuE"],
                                      {"median_c": med.get("value") if isinstance(med, dict) else med,
                                       "share_c_le_0": (g.get("share_c_le_0") or {}).get("share"),
                                       "eligible_sessions": g["eligible_sessions"]},
                                      g["eligible_sessions"], g["eligible_sessions"],
                                      [med.get("lo"), med.get("hi")] if isinstance(med, dict) else None, f"{pr}.{src}")
    Qg = Qall_BuE[Qall_BuE.qualified][["session_id", "call_id", "key", "seq", "delta_s", "trunc", "jc"]].copy()
    cells["N5g_cold_start"]["_check"] = ("N5g_cold_start", lambda D: n5g_eval(D)["label"], Qg.assign(tool=Qg.key))
    return cells


def apply_checks(corpus, unit, cells, smeta, Qall):
    """Artifact checks for every N1-N5 cell whose label reaches WEAK or better (on any of B, E, B u E)."""
    for row, c in cells.items():
        chk = c.pop("_check", None)
        if not row.startswith("N"):
            continue
        labs = [c.get("label_B"), c.get("label_E"), c.get("label_BuE")]
        if "per_checker" in c:
            labs = [x for ck in c["per_checker"].values() for x in (ck["label_B"], ck["label_E"], ck["label_BuE"])]
        if not any(x in ("ALIVE", "WEAK") for x in labs):
            c["artifact_checks"] = "not required (no label >= WEAK on B, E or B u E)"
            continue
        if chk is None:
            c["artifact_checks"] = {"status": "NOT_RUN", "why": "no decision-row recomputation implemented"}
            continue
        name, fn, D = chk
        base = fn(D)
        audit = make_audit(corpus, unit, Qall) if "call_id" in D else None
        r = run_checks(row, D, fn, smeta, base, has_trunc="trunc" in D, has_join="jc" in D, audit_fn=audit)
        c["artifact_checks"] = r
        lab0 = c["label"].split(" ")[0]
        if lab0 in LEVEL:
            new = lab0
            for lab in r["effects"]["failed_check_labels"].values():
                new = lower(new, lab)
            if r["effects"]["dominance"] == "DOMINATED":
                new = E.downgrade(new)
            elif r["effects"]["dominance"] == "UNTESTABLE_WITHOUT_DOMINANT" and LEVEL.get(new, 0) > 1:
                new = "WEAK"
            if r["effects"]["confined_axes"]:
                new = E.downgrade(new)
            r["effect_rule"] = ("applied to the cell label: failed AC -> lower label; DOMINATED -> one level down; "
                                "UNTESTABLE_WITHOUT_DOMINANT -> cap WEAK; CONFINED -> one level down")
            if new != lab0:
                c["label_before_checks"] = c["label"]
                c["label"] = c["label"].replace(lab0, new, 1)
    return cells


# ================================================================================================== main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args(argv)
    run_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for corpus, spec in CORPORA.items():
        t0 = time.time()
        calp = E.OUT_E / f"prereg_e_calibration_{corpus}.json"
        cal_sha = sha(calp)
        rec = next(x for x in CL if x.get("corpus") == corpus and "calibration_sha256" in x)
        assert cal_sha == rec["calibration_sha256"], f"{corpus} calibration changed since registration"
        CALD = json.loads(calp.read_text(encoding="utf-8"))
        build = {sp: build_cache(corpus, sp, args.rebuild) for sp in ("B", "E")}
        frames = {sp: load_frame(corpus, sp) for sp in ("B", "E")}
        doc = {"item": f"newcorp_measure_{corpus}", "group": GROUP, "corpus": corpus, "script": SCRIPT, "run_utc": run_utc,
               "prereg_e_json_sha256": sha(E.PREREG_E_JSON),
               "spec_module_sha256_lf": E.sha256_lf(Path(E.__file__)),
               "spec_module_matches_prereg": E.sha256_lf(Path(E.__file__)) == PJ["provenance"]["spec_module_sha256_lf"],
               "prereg_json_sha256": sha(ROOT / "analysis" / "prereg.json"),
               "calibration_file": str(calp.relative_to(ROOT).as_posix()), "calibration_sha256": cal_sha,
               "calibration_sha256_matches_change_log": True,
               "decisions_applied": {k: D_DEC[k] for k in D_DEC if k.startswith("D")},
               "splits_read": ["B", "E"], "H": "never built, read or listed",
               "build": build, "deviations": DEVIATIONS, "units": {}, "cells": {}}
        Qall = {}
        for label, unit, prefix in spec["units"]:
            cal_unit = CALD["units"][label if label in CALD["units"] else corpus]
            fr = {}
            for sp in ("B", "E"):
                f = frames[sp]
                fr[sp] = f[f.stratum.astype(str).str.startswith(prefix)] if prefix else f
            res, prepd = measure_unit(corpus, label, unit, fr, cal_unit, None)
            uB, QB = prepd["BuE"]
            cuts = (cal_unit["resolved"].get("length_terciles_A") or {}).get("cuts")
            smeta = session_meta(uB, QB, cuts)
            cells = build_cells(corpus, label, unit, res, prepd, smeta, QB)
            cells = apply_checks(corpus, unit, cells, smeta, QB)
            mech = {k: v for k, v in res.items() if not k.startswith("_")}
            doc["units"][label] = {"unit_argument": unit, "calibration_unit": cal_unit["calibrated_as_unit"],
                                   "sessions": res["_meta"], "field_gate": res["_field_gate"], "mechanisms": mech,
                                   "length_tercile_cuts_A": cuts,
                                   "session_strata": {p: dict(Counter(fr[p].groupby("session_id").stratum.first()
                                                                      .astype(str))) for p in ("B", "E")}}
            for row, c in cells.items():
                doc["cells"].setdefault(row, {})[label] = c
            Qall[label] = (uB, QB)
        # exploratory two-clock (agentcap)
        if corpus == "agentcap":
            ex = {"status": "EXPLORATORY, NOT pre-registered; descriptive only (no verdict rule); NOT_BLIND (D6: Track B "
                            "B5e computed request-id / clock deltas over the full corpus; the A build report holds A "
                            "quantiles of the same clocks)", "by_population": {}}
            for pop in ("B", "E", "BuE"):
                f = pd.concat([frames["B"], frames["E"]], ignore_index=True) if pop == "BuE" else frames[pop]
                o, M = two_clock(f.reset_index(drop=True))
                o["strata"] = two_clock_strata(M) if len(M) else {}
                o["by_harness"] = {}
                for h, pref in (("opencode", "opencode/"), ("pi", "pi/")):
                    oh, Mh = two_clock(f[f.stratum.astype(str).str.startswith(pref)].reset_index(drop=True))
                    o["by_harness"][h] = {k: oh.get(k) for k in ("responses_with_created", "responses_with_prev_input",
                                                                 "absolute_theta0", "streams_ge2", "stream_inconsistent",
                                                                 "stream_inconsistent_wilson",
                                                                 "slack_U_minus_L_consistent_ms",
                                                                 "placebo_response_backdate_power")}
                    if h == "pi" and len(Mh):
                        o["by_harness"]["pi"]["tight_variant"] = two_clock_pi_tight(Mh)
                ex["by_population"][pop] = o
            doc["exploratory_two_clock"] = ex
            e = ex["by_population"]
            dec = {p: {"stream_inconsistent": (e[p].get("stream_inconsistent") or {}).get("rate"),
                       "k": (e[p].get("stream_inconsistent") or {}).get("k"),
                       "streams": e[p].get("streams_ge2"),
                       "absolute_violation": (e[p].get("absolute_theta0") or {}).get("violation", {}).get("rate")}
                   for p in e}
            si = e["BuE"].get("stream_inconsistent") or {}
            doc["cells"]["X_two_clock_created"] = {"all": {
                "label": "EXPLORATORY (not pre-registered; descriptive)", "deciding_number": dec,
                "n": e["BuE"].get("streams_ge2"), "sessions": si.get("n_sessions"),
                "ci": [si.get("lo"), si.get("hi_used")], "json_path": "exploratory_two_clock.by_population.<pop>",
                "suffixes": ["NOT_BLIND"], "inequality": e["BuE"].get("inequality")}}
        n_cells = sum(len(v) for v in doc["cells"].values())
        doc["n_cells"] = n_cells
        doc["n_verdict_cells_computed"] = sum(1 for v in doc["cells"].values() for c in v.values()
                                              if str(c["label"]).split(" ")[0] in LEVEL)
        doc["runtime_s"] = round(time.time() - t0, 1)
        out = E.OUT_E / f"newcorp_measure_{corpus}.json"
        out.write_text(json.dumps(clean(doc), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"[{time.time() - T0:7.1f}s] wrote {out.relative_to(ROOT).as_posix()} ({n_cells} cells)", flush=True)
        for row, v in doc["cells"].items():
            print("   ", row, {k: c["label"] for k, c in v.items()})
        del frames
        gc.collect()


if __name__ == "__main__":
    main()
