"""Phase E N7 attack battery, TIMING detectors (item n7_timing; pre-registered in analysis/PREREG_E.md section 4,
analysis/prereg_e.json `n7_attack_battery`).

Run from the worktree root:
    PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n7_timing [--workers 5] [--smoke N]

What it does (nothing here is tuned; every threshold, seed, injector and detector comes from the pre-registration):
  * Detectors (the timing rows of the applicability matrix): R1_BRACKET (request-id bracket, stream L - U > 2,000 ms),
    P1_FLOOR (call delta <= 0 or < the Phase B A-split floor), P1_GEN (qualified W pair with r = latency / T_gen >= 1),
    N1 (within-session repeat residual outside the A bounds), N3 (session rho_s <= 0 over >= 20 reaction gaps),
    R3_GIT (generator-class commit claim whose commit_date lies outside [call - 2 s, result + 2 s]) and N4 (no per-session
    rule: every cell NA_BLIND_BY_CONSTRUCTION). Detector code = the frozen helpers of prereg_e_common / prereg_common /
    prereg_calibration (bracket_responses, bracket_streams, p1_qualified, qualify_pairs, n1_key, n1_residuals,
    n3_gaps, spearman, cold_start_values, commit_claims, git_cmd_class, git_window_ok).
  * Attacks: every attack x parameter of the prereg grid, injected with the frozen atk_* injectors, donors only from
    other real results of the same unit and split (pick_donor). Cells whose attack modifies nothing the detector reads
    are NA_BLIND_BY_CONSTRUCTION (applicable()).
  * Sessions: per unit x split x attack x parameter, every session with >= 1 eligible target, capped at 500 in the
    order of one seeded permutation per unit x split (rng_for('N7', unit, split)). Target rng_for(attack, param,
    session_id); donor rng_for('donor', attack, param, session_id). One tampered copy per session per cell; honest FPR on
    the same sessions untampered; session flag = >= 1 flagged decision unit; abstention = not flagged.
  * Statistics per cell: recall and FPR (Wilson over sessions), ADR (boot_stat session bootstrap), localization, and the
    mechanical n7_cell_label(). R1 also gets the stream-level rates (session-clustered) and the Phase D rule check.

Reads analysis/cache/<corpus>_{B,E}.parquet through prereg_e_common.read_cache only (never H, never A), the swechat
population/session metadata, and, for R3 only, data/swe-chat-pinned/{commits,checkpoints,sessions}.parquet (the external
commit table the prereg names; read-only, metadata columns only). Writes RAW NUMBERS ONLY to
analysis/out/phase_e/n7_timing.json. Interpretation: analysis/notes/phase_e_n7_timing.md.

cc_local is PRIVATE: aggregates only (no session ids, text, commands or paths leave this script). aiv_cc is one agent:
every aiv_cc row carries 'single-agent case study'.
"""
import argparse
import bisect
import json
import math
import multiprocessing as mp
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe
from analysis.probes import prereg_calibration as pcal

ITEM = "n7_timing"
OUT = pe.OUT_E / "n7_timing.json"
PREREG_B_JSON = pe.ROOT / "analysis" / "prereg.json"
DATA_SWE = Path("C:/Swarms/data/swe-chat-pinned")

COLS = ["session_id", "stratum", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "args", "command", "text",
        "stderr", "native_error", "exit_code", "usage_in", "usage_out", "api_msg_id", "request_id", "model",
        "is_subagent", "agent_id", "parent_call_id", "extra", "uuid", "parent_uuid"]

LAT_UNITS = list(pe.SPEC_E["n1_conditional_duration"]["units"])
UNIT_SPLITS = [("swechat/claude_code", "B"), ("swechat/claude_code", "E"), ("swechat/opencode", "B"),
               ("swechat/opencode", "E"), ("swechat/codex", "B"), ("swechat/codex", "E"), ("swechat/gemini", "B"),
               ("swechat/gemini", "E"), ("cc_local", "B"), ("aiv_cc", "B")]
TIMING_DETECTORS = ["R1_BRACKET", "P1_FLOOR", "P1_GEN", "N1", "N3", "N5g", "R3_GIT", "N4"]
DET_UNITS = {
    "R1_BRACKET": ["swechat/claude_code", "cc_local"],
    "P1_FLOOR": LAT_UNITS, "P1_GEN": LAT_UNITS, "N1": LAT_UNITS, "N3": LAT_UNITS, "N5g": LAT_UNITS,
    "R3_GIT": ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini"],
    "N4": LAT_UNITS,
}
NOT_TESTABLE = {  # (detector, unit) outside DET_UNITS, with the missing field (prereg_e.json resolved.n6_field_gate_A)
    "R1_BRACKET": {"swechat/codex": "no decodable request ids", "swechat/opencode": "no decodable request ids",
                   "swechat/gemini": "no decodable request ids", "aiv_cc": "no decodable request ids",
                   "aiv_cu": "no decodable request ids", "whowhen": "no stamps, no request ids",
                   "swechat/cursor": "no results, no stamps"},
    "P1_FLOOR": {"aiv_cu": "call and result share one stamp", "whowhen": "no stamps", "swechat/cursor": "no results"},
    "P1_GEN": {"aiv_cu": "call and result share one stamp", "whowhen": "no stamps", "swechat/cursor": "no results"},
    "N1": {"aiv_cu": "call and result share one stamp", "whowhen": "no stamps", "swechat/cursor": "no results"},
    "N3": {"aiv_cu": "row-insert / shared-turn stamps", "whowhen": "no stamps", "swechat/cursor": "no results"},
    "N5g": {"aiv_cu": "call and result share one stamp", "whowhen": "no stamps", "swechat/cursor": "no results"},
    "R3_GIT": {"cc_local": "no external commit table", "aiv_cc": "no external commit table",
               "aiv_cu": "no external commit table", "whowhen": "no external commit table",
               "swechat/cursor": "no results"},
    "N4": {"aiv_cu": "no per-call intervals", "whowhen": "no stamps", "swechat/cursor": "no results"},
}
NOT_TESTABLE_COMMON = {"swechat/copilot": "0 B sessions (prereg.json population_B)",
                       "swechat/simple_text": "0 B sessions (prereg.json population_B)"}

GRID_D, GRID_LATE = pe.GRID_D, pe.GRID_D_LATE_CHECK
ATTACKS = ([("time_result_early", GRID_D), ("time_result_late", GRID_D), ("time_tail_late", GRID_D),
            ("time_tail_early", GRID_D), ("time_response_early", GRID_D), ("time_response_late", GRID_LATE),
            ("id_swap_adjacent", ["-"]), ("id_splice_foreign", ["random", "nearest"]),
            ("sub_single_flip_error", ["-"]), ("sub_single_digit", ["-"]), ("sub_matched_bytes", ["base", "samecmd"]),
            ("rewrite_consistent_k", pe.REWRITE_K), ("reorder_adjacent_pairs", ["-"]), ("reorder_lines", ["-"]),
            ("delete_pair", ["-"]), ("delete_response", ["-"]), ("insert_pair_consistent", ["-"]),
            ("insert_pair_squeezed", ["-"]), ("inline_fabrication", ["-"]), ("image_relabel_gui", ["-"]),
            ("image_insert_screenshot", ["-"])])
assert [a for a, _ in ATTACKS] == list(pe.SPEC_E["n7_attack_battery"]["attacks"]), "attack list drifted from SPEC_E"
SINGLE_CALL = set(pe.SPEC_E["n7_attack_battery"]["single_call_types"])
AIV_CU_ONLY = {"image_relabel_gui", "image_insert_screenshot"}

TARGET_RULES = {
    "time_result_early": "result of a qualified pair: prereg_e_common.qualify_pairs(unit, s, P) with its default scope "
                         "(shell + auto_read; Phase B rules 1, 3-6, delta > 0, not backgrounded)",
    "time_result_late": "result of any call/result pair whose two stamps parse (make_pairs delta_s finite)",
    "time_tail_late": "as time_result_late", "time_tail_early": "as time_result_late",
    "time_response_early": "first event (min seq) of one non-null request id of the session",
    "time_response_late": "as time_response_early",
    "id_swap_adjacent": "two consecutive decodable request ids (by first-event seq) of one bracket stream "
                        "(session, agent_id if is_subagent else 'main')",
    "id_splice_foreign": "one decodable request id; donor = a decodable request id of another session of the same unit "
                         "and split ('random': uniform; 'nearest': nearest decoded ms, ties by the donor rng); ids "
                         "present in the target session are not donors",
    "sub_single_flip_error": "result of a pair whose Phase B primary error class is True, with a successful (primary "
                             "False) same-tool_key donor result from another session within 5% bytes; native_error "
                             "set False (atk_substitute donor_error=False)",
    "sub_single_digit": "result of a pair whose text contains a digit",
    "sub_matched_bytes": "result of a pair (bytes > 0) with a same-tool_key donor result from another session within 5% "
                         "bytes ('samecmd': donor also has the same n1_key); donor native_error copied when not null",
    "rewrite_consistent_k": "k consecutive paired results of one thread (session, is_subagent, agent_id) in seq order, "
                            "each with a same-tool_key donor pair from another session within 5% bytes and a finite "
                            "positive donor latency",
    "reorder_adjacent_pairs": "two consecutive paired calls of one thread",
    "reorder_lines": "result of a pair with >= 3 lines and >= 1 adjacent pair of different lines",
    "delete_pair": "one paired call",
    "delete_response": "one non-null request id",
    "insert_pair_consistent": "after the result of a main-thread pair whose result stamp parses; donor = uniform over "
                              "main-thread, non-nested pairs of other sessions with latency > 0 and a call gap >= 0 "
                              "(call ts minus the latest earlier event stamp of its session)",
    "insert_pair_squeezed": "as insert_pair_consistent, and the immediately next event (by seq) has a stamp >= 2 ms later",
    "inline_fabrication": "not run here: no timing detector reads usage (NA_BLIND_BY_CONSTRUCTION)",
    "image_relabel_gui": "aiv_cu only; no timing detector reads tool labels (NA_BLIND_BY_CONSTRUCTION)",
    "image_insert_screenshot": "aiv_cu only; the applicable timing detectors (R1, N3) are NOT_TESTABLE on aiv_cu",
    "param_string": "rng parts use str(param); attacks without a parameter use param '-'",
}

PB = json.loads(PREREG_B_JSON.read_text(encoding="utf-8"))
G90 = {u: PB["resolved"]["probe1"]["generation_rate"][u]["G90"] for u in LAT_UNITS}
TPC = PB["probe1"]["separability"]["generation_time_model"]["tokens_per_char"]
T_GEN_MIN = 1.0  # prereg.json probe1.separability.generation_time_model.eligibility 'T_gen >= 1.0 s'
assert "T_gen >= 1.0 s" in PB["probe1"]["separability"]["generation_time_model"]["eligibility"]
assert abs(TPC - 0.25) < 1e-12


# ====================================================================================================== small helpers
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (set, frozenset)):
        return sorted(clean(v) for v in o)
    return o


def unit_corpus(unit):
    return "swechat" if unit.startswith("swechat/") else unit


def wil(k, n):
    p, lo, hi = stats.wilson(k, n)
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


def thread_of(is_sub, agent):
    sub = bool(is_sub) if (is_sub is not None and not (isinstance(is_sub, float) and math.isnan(is_sub))
                          and is_sub is not pd.NA) else False
    return (sub, agent if isinstance(agent, str) else "")


def stream_of(is_sub, agent):
    return pe._stream([is_sub], [agent])[0]


def is_true(x):
    """True for a primary-error value that is True (python or numpy bool); False for False/None/NaN/NA."""
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return False
    return bool(x)


def is_false(x):
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return False
    return not bool(x)


# ====================================================================================================== loading
def load_unit(unit, split):
    """Every IR row of the unit x split (no row dropped: the injectors see the untouched event stream)."""
    corpus = unit_corpus(unit)
    df = pe.read_cache(corpus, split, COLS)
    if corpus == "swechat":
        fm = pc.swechat_formats()
        df = df[df.session_id.map(fm) == unit.split("/", 1)[1]]
    df = df.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    import gc
    import pyarrow as pa
    gc.collect()
    pa.default_memory_pool().release_unused()  # return the parquet read buffers to the OS (RAM budget)
    return df


def session_ranges(df):
    sid = df.session_id.to_numpy()
    if not len(sid):
        return {}
    starts = np.flatnonzero(np.r_[True, sid[1:] != sid[:-1]])
    ends = np.r_[starts[1:], len(sid)]
    return {str(sid[a]): (int(a), int(b)) for a, b in zip(starts, ends)}


# ====================================================================================================== R3 context
class CommitCtx:
    """External commit table for R3 (swechat only): prefix resolution in the Phase C lens order (linked to the session,
    same repo, any ok commit; phase_c_commit_witness.py q4_match). Metadata columns only."""

    def __init__(self, session_ids):
        import pyarrow.parquet as pq
        ids = sorted(set(session_ids))
        sess = pq.read_table(DATA_SWE / "sessions.parquet", columns=["session_id", "repo_id", "checkpoint_ids"],
                             filters=[("session_id", "in", ids)]).to_pandas()
        cp = pd.read_parquet(DATA_SWE / "checkpoints.parquet", columns=["checkpoint_pk", "session_pks"])
        meta = pq.ParquetFile(DATA_SWE / "commits.parquet").read(
            columns=["commit_sha", "checkpoint_pk", "repo_id", "commit_date", "status"]).to_pandas()
        meta = meta.reset_index(drop=True)
        mine = set(ids)
        sess_cps = defaultdict(set)
        for pk, x in zip(cp.checkpoint_pk, cp.session_pks):
            for s in (json.loads(x) if isinstance(x, str) else []):
                if s in mine:
                    sess_cps[s].add(pk)
        del cp
        for sid, x in zip(sess.session_id.astype(str), sess.checkpoint_ids):
            sess_cps[sid] |= set(json.loads(x)) if isinstance(x, str) else set()
        self.repo = dict(zip(sess.session_id.astype(str), sess.repo_id.astype(str)))
        ok = meta[meta.status == "ok"]
        self.all_shas = sorted(set(ok.commit_sha))
        self.repo_shas = {rp: sorted(set(d.commit_sha)) for rp, d in ok.groupby("repo_id")}
        self.date = {}
        for sha, d in zip(ok.commit_sha, ok.commit_date):  # first row of each sha (Phase C first_row_of_sha)
            if sha not in self.date:
                self.date[sha] = d
        cp_shas = defaultdict(set)
        for pk, sha in zip(ok.checkpoint_pk, ok.commit_sha):
            cp_shas[pk].add(sha)
        self.linked = {s: sorted(set().union(*[cp_shas.get(pk, set()) for pk in cps])) if cps else []
                       for s, cps in sess_cps.items()}
        self.n_ok_commits = int(len(ok))

    @staticmethod
    def _pref(lst, s):
        i = bisect.bisect_left(lst, s)
        return lst[i] if i < len(lst) and lst[i].startswith(s) else None

    def resolve(self, sid, sha):
        hit = self._pref(self.linked.get(sid, []), sha)
        lvl = "linked"
        if hit is None:
            hit, lvl = self._pref(self.repo_shas.get(self.repo.get(sid), []), sha), "same_repo"
        if hit is None:
            hit, lvl = self._pref(self.all_shas, sha), "other_repo"
        return (self.date.get(hit), lvl) if hit is not None else (None, "none")


# ====================================================================================================== detectors
def _res(n_units, flagged):
    return {"decided": n_units > 0, "flag": len(flagged) > 0, "n_units": int(n_units), "flagged": frozenset(flagged)}


ABSTAIN = {"decided": False, "flag": False, "n_units": 0, "flagged": frozenset()}


def evaluate(unit, sid, s, dets, ctx):
    """Run the timing detectors `dets` on one session frame s. Returns {det: result dict}."""
    out = {}
    need_pairs = any(d in dets for d in ("P1_FLOOR", "P1_GEN", "N1", "R3_GIT"))
    P = pc.make_pairs(s[s.kind.isin(["call", "result"])]) if need_pairs else None
    have_pairs = P is not None and len(P) > 0
    if "P1_FLOOR" in dets or "P1_GEN" in dets:
        if have_pairs:
            PBq = pcal.p1_qualified(unit, s, P)
            Qall = PBq[PBq.qualified.to_numpy()]
        if "P1_FLOOR" in dets:
            thr = ctx["floors"]
            if have_pairs and len(Qall):
                sub = Qall[Qall.key.isin(list(thr)).to_numpy()]
                d = sub.delta_s.to_numpy(dtype=float)
                th = np.array([thr[k] for k in sub.key], dtype=float)
                fl = (d <= 0) | (d < th)
                cids = sub.call_id.astype(str).to_numpy()
                out["P1_FLOOR"] = _res(len(sub), set(cids[fl]))
            else:
                out["P1_FLOOR"] = ABSTAIN
        if "P1_GEN" in dets:
            if have_pairs and len(Qall):
                Q = Qall[Qall.delta_s.to_numpy(dtype=float) > 0]
                W = Q[Q.key.isin(list(pcal.W_KEYS[unit])).to_numpy()] if unit in pcal.W_KEYS else Q[Q.cls == "auto_read"]
                ch = np.array([len(t) if isinstance(t, str) else 0 for t in W.text_r.astype(object)], dtype=float)
                tg = ch * TPC / G90[unit]
                e = tg >= T_GEN_MIN
                r = W.delta_s.to_numpy(dtype=float)[e] / tg[e]
                cids = W.call_id.astype(str).to_numpy()[e]
                out["P1_GEN"] = _res(int(e.sum()), set(cids[r >= 1]))
            else:
                out["P1_GEN"] = ABSTAIN
    if ("N1" in dets or "N5g" in dets) and have_pairs:
        Qe = pe.qualify_pairs(unit, s, P)
        qe = Qe[Qe.qualified.to_numpy()]
    if "N5g" in dets:
        res = ABSTAIN
        if have_pairs and len(qe):
            cs = pe.cold_start_values(qe)
            if cs:
                res = _res(1, {"session"} if cs[0][2] <= 0 else set())
                res = dict(res, c_s=cs[0][2])
        out["N5g"] = res
    if "N1" in dets:
        res = ABSTAIN
        if have_pairs:
            q = qe
            if len(q):
                q = q.assign(
                    n1=[pe.n1_key(unit, k, a, c) for k, a, c in zip(q.key, q.args.astype(object), q.command.astype(object))],
                    err=[bool(pc.error_classes(unit, k, tr, t, e, n, x, st)[0]) for k, tr, t, e, n, x, st in
                         zip(q.key, q.tool_raw.astype(object), q.text_r.astype(object), q.stderr_r.astype(object),
                             q.native_error_r.astype(object), q.exit_code_r.astype(object), q.stratum.astype(object))])
                R = pe.n1_residuals(q, unit)
                if len(R):
                    lo, hi = ctx["n1_bounds"]
                    seq2cid = dict(zip(q.seq.astype(int), q.call_id.astype(str)))
                    fl = (R.residual.to_numpy() < lo) | (R.residual.to_numpy() > hi)
                    res = _res(len(R), {seq2cid[int(x)] for x in R.seq.to_numpy()[fl]})
        out["N1"] = res
    if "N3" in dets:
        gaps = pe.n3_gaps(s)
        res = ABSTAIN
        if len(gaps) >= 20:
            rho = pe.spearman([g for _, g, _ in gaps], [b for _, _, b in gaps])
            if rho is not None:
                res = _res(1, {"session"} if rho <= 0 else set())
                res = dict(res, rho=rho)
        out["N3"] = res
    if "R1_BRACKET" in dets:
        res = ABSTAIN
        if s.request_id.notna().any():
            R = pe.bracket_responses(s)
            if len(R):
                S = pe.bracket_streams(R)
                if len(S):
                    res = _res(len(S), set(S.stream[S.inconsistent.to_numpy()].astype(str)))
        out["R1_BRACKET"] = res
    if "R3_GIT" in dets:
        res = ABSTAIN
        cc = ctx.get("commits")
        if have_pairs and cc is not None:
            units, flagged = 0, set()
            keys = [pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
            for k, cid, a, cmd, txt, cts, rts in zip(keys, P.call_id.astype(str), P.args.astype(object),
                                                     P.command.astype(object), P.text_r.astype(object),
                                                     P.ts.astype(object), P.ts_r.astype(object)):
                if not (k == "shell" or k in pc.CODEX_SHELL_RAW or str(k).endswith("__bash")) or not isinstance(txt, str):
                    continue
                cl = pe.commit_claims(txt)
                if not cl:
                    continue
                sc = pc.shell_command(unit, k, pc.jl(a) if isinstance(a, str) else {}, cmd)
                if pe.git_cmd_class(sc) != "generator":
                    continue
                for sha in sorted({x for x, _ in cl}):
                    d, _lvl = cc.resolve(sid, sha)
                    if d is None:
                        continue  # non-resolving SHA abstains
                    ok = pe.git_window_ok(cts if isinstance(cts, str) else None, rts if isinstance(rts, str) else None, d)
                    if ok is None:
                        continue
                    units += 1
                    if ok is False:
                        flagged.add((cid, sha))
            res = _res(units, flagged)
        out["R3_GIT"] = res
    return out


# ====================================================================================================== per-session info
def session_info(unit, sid, s):
    """Honest per-session tables used for target eligibility and donor pools (no detector statistic)."""
    calls = s[s.kind == "call"].sort_values("seq").drop_duplicates("call_id")
    resr = s[(s.kind == "result") & s.call_id.notna()].sort_values("seq").drop_duplicates("call_id")
    cidx = dict(zip(calls.call_id.astype(str), calls.index))
    ridx = dict(zip(resr.call_id.astype(str), resr.index))
    P = pc.make_pairs(s[s.kind.isin(["call", "result"])])
    info = {"pairs": None, "responses": None, "nrows": len(s)}
    if len(P):
        Q = pe.qualify_pairs(unit, s, P)
        cid = Q.call_id.astype(str).to_numpy()
        txt = Q.text_r.astype(object).to_numpy()
        prim = [pc.error_classes(unit, k, tr, t, e, n, x, st)[0] for k, tr, t, e, n, x, st in
                zip(Q.key, Q.tool_raw.astype(object), txt, Q.stderr_r.astype(object), Q.native_error_r.astype(object),
                    Q.exit_code_r.astype(object), Q.stratum.astype(object))]
        n1 = [pe.n1_key(unit, k, a, c) for k, a, c in zip(Q.key, Q.args.astype(object), Q.command.astype(object))]
        thr = [thread_of(a, b) for a, b in zip(Q.is_subagent.astype(object), Q.agent_id.astype(object))]
        ms = pe._ms(s.ts)
        seqs = s.seq.to_numpy()
        pos = {ix: i for i, ix in enumerate(s.index)}
        # latest earlier stamp before each row (for the donor call gap) and the next row's stamp (for squeezing)
        prev_ms = np.full(len(s), np.nan)
        last = np.nan
        for i in range(len(s)):
            prev_ms[i] = last
            if np.isfinite(ms[i]):
                last = ms[i]
        next_ms = np.r_[ms[1:], np.nan]
        ci = np.array([cidx.get(c, -1) for c in cid])
        ri = np.array([ridx.get(c, -1) for c in cid])
        rows = pd.DataFrame({
            "session_id": sid, "cid": cid, "ci": ci, "ri": ri, "key": Q.key.to_numpy(), "seq": Q.seq.to_numpy(),
            "seq_r": Q.seq_r.to_numpy(), "delta_s": Q.delta_s.to_numpy(dtype=float),
            "qualified": Q.qualified.to_numpy(), "bytes": Q.result_bytes.to_numpy(), "text": txt,
            "err": prim, "n1": n1, "main": [not t[0] for t in thr], "thread": [f"{int(t[0])}|{t[1]}" for t in thr],
            "nested": Q.parent_call_id.notna().to_numpy(),
            "native_error": Q.native_error_r.astype(object).to_numpy(),
            "res_ms": [ms[pos[x]] if x in pos else np.nan for x in ri],
            "call_gap_s": [(ms[pos[x]] - prev_ms[pos[x]]) / 1000.0 if x in pos else np.nan for x in ci],
            "next_gap_s": [(next_ms[pos[x]] - ms[pos[x]]) / 1000.0 if x in pos else np.nan for x in ri],
            "has_next": [pos[x] + 1 < len(s) if x in pos else False for x in ri],
        })
        rows = rows[(rows.ci >= 0) & (rows.ri >= 0)].sort_values("seq").reset_index(drop=True)
        info["pairs"] = rows
    rid = s[s.request_id.notna()].sort_values("seq").drop_duplicates("request_id")
    if len(rid):
        emb = [pe.decode_req_ms(x) for x in rid.request_id.astype(object)]
        info["responses"] = pd.DataFrame({
            "idx": rid.index.to_numpy(), "seq": rid.seq.to_numpy(), "request_id": rid.request_id.astype(str).to_numpy(),
            "emb": np.array([np.nan if e is None else e for e in emb], dtype=float),
            "stream": pe._stream(rid.is_subagent, rid.agent_id)})
    return info


# ====================================================================================================== unit context
class UnitCtx:
    def __init__(self, unit, split, smoke=0, log=print):
        t0 = time.time()
        self.unit, self.split = unit, split
        self.df = load_unit(unit, split)
        self.ranges = session_ranges(self.df)
        sids = sorted(self.ranges)
        if smoke:
            sids = sids[:smoke]
            self.ranges = {s: self.ranges[s] for s in sids}
        self.sids = sids
        perm = pe.rng_for("N7", unit, split).permutation(len(sids))
        self.order = [sids[i] for i in perm]
        log(f"[{unit}|{split}] loaded {len(self.df)} rows, {len(sids)} sessions ({time.time() - t0:.1f}s)")
        self.info = {s: session_info(unit, s, self.sess(s)) for s in sids}
        log(f"[{unit}|{split}] session info ({time.time() - t0:.1f}s)")
        pr = [i["pairs"] for i in self.info.values() if i["pairs"] is not None]
        self.pool = pd.concat(pr, ignore_index=True) if pr else pd.DataFrame()
        if len(self.pool):
            self.pool.index = self.pool.ri.to_numpy()  # pool index = result row label (pick_donor returns it)
        rs = [i["responses"].assign(session_id=s) for s, i in self.info.items() if i["responses"] is not None]
        self.resp_pool = pd.concat(rs, ignore_index=True) if rs else pd.DataFrame()
        self.resp_sessions = (set(self.resp_pool.session_id[np.isfinite(self.resp_pool.emb.to_numpy())])
                              if len(self.resp_pool) else set())
        pj = PJ or pe.check_frozen()
        self.ctx = {"floors": {k: v["threshold_s"] for k, v in
                               pj["resolved"]["n7"]["floor_thresholds"].get(unit, {}).items()},
                    "n1_bounds": tuple(pj["resolved"]["n1"][unit]["bounds"]) if unit in pj["resolved"]["n1"] else None,
                    "commits": None}
        if "R3_GIT" in self.dets():
            self.ctx["commits"] = CommitCtx(sids)
        self._pools = {}
        self._targets = {}
        self.honest = {}
        log(f"[{unit}|{split}] context ready ({time.time() - t0:.1f}s)")

    def sess(self, sid):
        a, b = self.ranges[sid]
        return self.df.iloc[a:b]

    def dets(self):
        return [d for d in TIMING_DETECTORS if d != "N4" and self.unit in DET_UNITS[d]]

    def honest_eval(self, sid):
        if sid not in self.honest:
            self.honest[sid] = evaluate(self.unit, sid, self.sess(sid), self.dets(), self.ctx)
        return self.honest[sid]

    # ---------------------------------------------------------------- donor pools and availability
    def pool_for(self, name, key, n1=None):
        """Donor pool (DataFrame indexed by result row label) for one tool_key (and n1_key for 'samecmd'), plus an
        availability index. Pools hold other REAL results of the same unit and split only."""
        k = (name, key, n1)
        if k in self._pools:
            return self._pools[k]
        p = self.pool
        if not len(p):
            self._pools[k] = (p, None)
            return self._pools[k]
        if name == "samecmd":
            if "_sc" not in self._pools:
                q = p[(p.bytes.to_numpy() > 0) & p.n1.notna().to_numpy()].sort_values(["key", "n1", "bytes"],
                                                                                        kind="stable")
                ks = list(zip(q.key, q.n1))
                bounds, start = {}, 0
                for i in range(1, len(ks) + 1):
                    if i == len(ks) or ks[i] != ks[start]:
                        bounds[ks[start]] = (start, i)
                        start = i
                self._pools["_sc"] = (q, bounds)
            q, bounds = self._pools["_sc"]
            a, b = bounds.get((key, n1), (0, 0))
            sub = q.iloc[a:b]
            return sub, ("slice", sub.bytes.to_numpy(), sub.session_id.to_numpy())
        m = (p.key == key).to_numpy() & (p.bytes.to_numpy() > 0)
        if name == "flip":
            m &= p.err.map(is_false).astype(bool).to_numpy()
        elif name == "rewrite":
            m &= np.isfinite(p.delta_s.to_numpy()) & (np.nan_to_num(p.delta_s.to_numpy(), nan=-1) > 0)
        sub = p[m]
        by = np.sort(sub.bytes.to_numpy())
        per = {s_: np.sort(g.bytes.to_numpy()) for s_, g in sub.groupby("session_id")}
        self._pools[k] = (sub, ("bisect", by, per))
        return self._pools[k]

    def donor_available(self, name, key, sid, b, n1=None):
        """True iff pick_donor() would find a donor within MATCHED_BYTES_TOL (another session, same pool)."""
        sub, idx = self.pool_for(name, key, n1)
        if idx is None or b <= 0 or not len(sub):
            return False
        lo, hi = b - pe.MATCHED_BYTES_TOL * b, b + pe.MATCHED_BYTES_TOL * b
        if idx[0] == "slice":
            by, ss = idx[1], idx[2]
            i0, i1 = np.searchsorted(by, lo, side="left"), np.searchsorted(by, hi, side="right")
            return bool((ss[i0:i1] != sid).any())
        by, per = idx[1], idx[2]
        n_all = bisect.bisect_right(by, hi) - bisect.bisect_left(by, lo)
        mine = per.get(sid)
        n_me = (bisect.bisect_right(mine, hi) - bisect.bisect_left(mine, lo)) if mine is not None else 0
        return n_all - n_me > 0

    # ---------------------------------------------------------------- targets
    def targets(self, attack, param, sid):
        key = (attack, param if attack in ("id_splice_foreign", "sub_matched_bytes", "rewrite_consistent_k") else "")
        memo = self._targets.setdefault(key, {})
        if sid in memo:
            return memo[sid]
        inf = self.info[sid]
        P = inf["pairs"]
        R = inf["responses"]
        t = []
        if attack == "time_result_early":
            if P is not None:
                t = [int(x) for x in P.ri[P.qualified.to_numpy()]]
        elif attack in ("time_result_late", "time_tail_late", "time_tail_early"):
            if P is not None:
                t = [int(x) for x in P.ri[np.isfinite(P.delta_s.to_numpy())]]
        elif attack in ("time_response_early", "time_response_late", "delete_response"):
            if R is not None:
                t = [int(x) for x in R.idx]
        elif attack == "id_swap_adjacent":
            if R is not None:
                d = R[np.isfinite(R.emb.to_numpy())].sort_values("seq")
                for _, g in d.groupby("stream", sort=True):
                    ix = g.idx.tolist()
                    t += [(int(ix[i]), int(ix[i + 1])) for i in range(len(ix) - 1)]
        elif attack == "id_splice_foreign":
            if R is not None and (self.resp_sessions - {sid}):
                t = [int(x) for x in R.idx[np.isfinite(R.emb.to_numpy())]]
        elif attack == "sub_single_flip_error":
            if P is not None:
                t = [int(r) for r, e, k, b in zip(P.ri, P.err, P.key, P.bytes)
                     if is_true(e) and self.donor_available("flip", k, sid, b)]
        elif attack == "sub_single_digit":
            if P is not None:
                t = [int(r) for r, x in zip(P.ri, P.text) if isinstance(x, str) and re.search(r"\d", x)]
        elif attack == "sub_matched_bytes":
            if P is not None:
                if param == "samecmd":
                    t = [int(r) for r, k, b, n in zip(P.ri, P.key, P.bytes, P.n1)
                         if n is not None and self.donor_available("samecmd", k, sid, b, n)]
                else:
                    t = [int(r) for r, k, b in zip(P.ri, P.key, P.bytes) if self.donor_available("base", k, sid, b)]
        elif attack == "rewrite_consistent_k":
            if P is not None:
                ok = np.array([self.donor_available("rewrite", k, sid, b) for k, b in zip(P.key, P.bytes)], dtype=bool)
                Pk = P.assign(_ok=ok)
                for _, g in Pk.sort_values("seq_r").groupby("thread", sort=True):
                    ri, oo = g.ri.tolist(), g._ok.tolist()
                    for i in range(len(ri) - int(param) + 1):
                        if all(oo[i:i + int(param)]):
                            t.append(tuple(int(x) for x in ri[i:i + int(param)]))
        elif attack == "reorder_adjacent_pairs":
            if P is not None:
                for _, g in P.sort_values("seq").groupby("thread", sort=True):
                    ci = g.ci.tolist()
                    t += [(int(ci[i]), int(ci[i + 1])) for i in range(len(ci) - 1)]
        elif attack == "reorder_lines":
            if P is not None:
                for r, x in zip(P.ri, P.text):
                    if isinstance(x, str):
                        ls = x.split("\n")
                        if len(ls) >= 3 and any(ls[i] != ls[i + 1] for i in range(len(ls) - 1)):
                            t.append(int(r))
        elif attack == "delete_pair":
            if P is not None:
                t = [int(x) for x in P.ci]
        elif attack in ("insert_pair_consistent", "insert_pair_squeezed"):
            if P is not None and len(self.insert_donors(exclude=sid)):
                m = P.main.to_numpy() & np.isfinite(P.res_ms.to_numpy())
                if attack == "insert_pair_squeezed":
                    m &= P.has_next.to_numpy() & (np.nan_to_num(P.next_gap_s.to_numpy(), nan=-1) >= 0.002)
                t = [int(x) for x in P.ri[m]]
        memo[sid] = t
        return t

    def insert_donors(self, exclude=None):
        if "_ins" not in self._pools:
            p = self.pool
            if len(p):
                m = (p.main.to_numpy() & ~p.nested.to_numpy() & np.isfinite(p.delta_s.to_numpy()) & (p.delta_s.to_numpy() > 0)
                     & np.isfinite(p.call_gap_s.to_numpy()) & (np.nan_to_num(p.call_gap_s.to_numpy(), nan=-1) >= 0))
                self._pools["_ins"] = p[m].sort_values(["session_id", "seq"]).reset_index(drop=True)
            else:
                self._pools["_ins"] = p
        d = self._pools["_ins"]
        return d[d.session_id != exclude] if exclude is not None and len(d) else d


# ====================================================================================================== injection
def target_units(ctx, attack, s, target, extra):
    """(call_ids, streams) the attack touched in the tampered copy, for localization; None where undefined."""
    if attack in ("delete_pair", "delete_response"):
        return None, None
    if attack.startswith("insert_pair"):
        return {extra["inserted_cid"]}, {"main"}
    if attack in ("time_response_early", "time_response_late", "id_splice_foreign", "id_swap_adjacent"):
        idxs = target if isinstance(target, tuple) else (target,)
        rids = {ctx.df.at[i, "request_id"] for i in idxs}
        sub = s[s.request_id.isin(list(rids)) & (s.kind == "call")]
        streams = {stream_of(ctx.df.at[i, "is_subagent"], ctx.df.at[i, "agent_id"]) for i in idxs}
        return set(sub.call_id.astype(str)), streams
    if attack == "reorder_adjacent_pairs":
        idxs = target
    elif attack == "rewrite_consistent_k":
        idxs = target
    else:
        idxs = (target,)
    cids = {str(ctx.df.at[i, "call_id"]) for i in idxs}
    streams = {stream_of(ctx.df.at[i, "is_subagent"], ctx.df.at[i, "agent_id"]) for i in idxs}
    return cids, streams


def inject(ctx, attack, param, sid, s, target, rng, drng):
    """Returns (tampered frame, extra dict) or (None, failure reason)."""
    extra = {}
    if attack.startswith("time_"):
        mode = attack[len("time_"):]
        s2, info = pe.atk_time(s, target, float(param), mode)
        extra["clamped"] = bool(info.get("clamped"))
        return s2, extra
    if attack == "id_swap_adjacent":
        return pe.atk_id_swap(s, target[0], target[1]), extra
    if attack == "id_splice_foreign":
        rp = ctx.resp_pool
        own = set(s.request_id.dropna().astype(str))
        cand = rp[(rp.session_id != sid) & np.isfinite(rp.emb.to_numpy()) & ~rp.request_id.isin(list(own)).to_numpy()]
        if not len(cand):
            return None, "no_donor_id"
        if param == "random":
            j = int(drng.integers(0, len(cand)))
        else:
            te = pe.decode_req_ms(ctx.df.at[target, "request_id"])
            diff = (cand.emb.to_numpy() - te).__abs__()
            best = np.flatnonzero(diff == diff.min())
            j = int(best[int(drng.integers(0, len(best)))])
            extra["nearest_abs_ms"] = float(diff.min())
        return pe.atk_id_splice(s, target, cand.request_id.iloc[j]), extra
    if attack in ("sub_single_flip_error", "sub_matched_bytes"):
        row = ctx.pool.loc[target]
        name = "flip" if attack == "sub_single_flip_error" else ("samecmd" if param == "samecmd" else "base")
        sub, _ = ctx.pool_for(name, row.key, row.n1 if name == "samecmd" else None)
        i, rel = pe.pick_donor(sub, int(row.bytes), drng, exclude_session=sid)
        if i is None:
            return None, "donor_out_of_tolerance"
        extra["rel_byte_diff"] = rel
        if attack == "sub_single_flip_error":
            return pe.atk_substitute(s, target, sub.at[i, "text"], donor_error=False), extra
        de = sub.at[i, "native_error"]
        de = None if (de is None or de is pd.NA or (isinstance(de, float) and math.isnan(de))) else bool(de)
        return pe.atk_substitute(s, target, sub.at[i, "text"], donor_error=de), extra
    if attack == "sub_single_digit":
        s2, ok = pe.atk_digit(s, target)
        return (s2, extra) if ok else (None, "no_digit")
    if attack == "rewrite_consistent_k":
        texts, lats, rels = [], [], []
        for ri in target:
            row = ctx.pool.loc[ri]
            sub, _ = ctx.pool_for("rewrite", row.key)
            i, rel = pe.pick_donor(sub, int(row.bytes), drng, exclude_session=sid)
            if i is None:
                return None, "donor_out_of_tolerance"
            texts.append(sub.at[i, "text"])
            lats.append(float(sub.at[i, "delta_s"]))
            rels.append(rel)
        extra["rel_byte_diff"] = max(rels)
        return pe.atk_rewrite_consistent(s, list(target), texts, lats), extra
    if attack == "reorder_adjacent_pairs":
        return pe.atk_reorder_pairs(s, target[0], target[1]), extra
    if attack == "reorder_lines":
        s2, ok = pe.atk_reorder_lines(s, target, rng)
        return (s2, extra) if ok else (None, "no_line_pair")
    if attack == "delete_pair":
        return pe.atk_delete_pair(s, target), extra
    if attack == "delete_response":
        return pe.atk_delete_response(s, target), extra
    if attack.startswith("insert_pair"):
        don = ctx.insert_donors(exclude=sid)
        if not len(don):
            return None, "no_donor_pair"
        j = int(drng.integers(0, len(don)))
        d = don.iloc[j]
        dc = ctx.df.loc[int(d.ci)].copy()
        dr = ctx.df.loc[int(d.ri)].copy()
        mode = "consistent" if attack == "insert_pair_consistent" else "squeezed"
        s2 = pe.atk_insert_pair(s, target, dc, dr, mode=mode, donor_gap_s=float(d.call_gap_s),
                                donor_lat_s=float(d.delta_s))
        if s2 is None:
            return None, "gap_below_2ms_or_unparseable"
        extra["inserted_cid"] = f"inserted:{dc.get('call_id')}"
        return s2, extra
    return None, "attack_not_run_here"


# ====================================================================================================== cells
def run_cell(ctx, attack, param, cap, log):
    unit, split = ctx.unit, ctx.split
    dets_all = ctx.dets()
    dets = [d for d in dets_all if pe.applicable(attack, d)]
    elig = [s for s in ctx.order if ctx.targets(attack, param, s)]
    sel = elig[:cap]
    per = []  # per session dict
    fails = Counter()
    clamped = 0
    rels, near = [], []
    for sid in sel:
        tg = ctx.targets(attack, param, sid)
        rng = pe.rng_for(attack, param, sid)
        target = tg[int(rng.integers(0, len(tg)))]
        drng = pe.rng_for("donor", attack, param, sid)
        s = ctx.sess(sid)
        try:
            s2, extra = inject(ctx, attack, param, sid, s, target, rng, drng)
        except Exception as ex:  # an injector crash is counted, never hidden
            fails[f"injector_exception:{type(ex).__name__}"] += 1
            continue
        if s2 is None:
            fails[extra] += 1
            continue
        clamped += int(extra.get("clamped", False))
        if "rel_byte_diff" in extra:
            rels.append(extra["rel_byte_diff"])
        if "nearest_abs_ms" in extra:
            near.append(extra["nearest_abs_ms"])
        tc, ts_ = target_units(ctx, attack, s2, target, extra)
        h = ctx.honest_eval(sid)
        tv = evaluate(unit, sid, s2, dets, ctx.ctx)
        per.append({"h": h, "t": tv, "tc": tc, "ts": ts_})
    rows = {}
    n_t = len(per)
    for d in TIMING_DETECTORS:
        base = {"unit": unit, "split": split, "detector": d, "attack": attack, "param": str(param)}
        if d == "N4":
            rows[d] = dict(base, label="NA_BLIND_BY_CONSTRUCTION",
                           reason="N4 has no per-session decision rule (prereg_e.json n4_concurrency.n7)")
            continue
        if d not in dets_all:
            continue
        if not pe.applicable(attack, d):
            rows[d] = dict(base, label="NA_BLIND_BY_CONSTRUCTION",
                           reason=f"attack modifies {sorted(pe.ATTACK_FIELDS[attack])}; detector reads "
                                  f"{sorted(pe.DETECTOR_FIELDS[d])} (applicable() False)")
            continue
        kt = sum(1 for x in per if x["t"][d]["flag"])
        kh = sum(1 for x in per if x["h"][d]["flag"])
        lab, ci = pe.n7_cell_label(n_t, kt, n_t, kh)
        row = dict(base, label=lab, n_eligible_sessions=len(elig), n_selected=len(sel), n_tampered=n_t,
                   injection_failures=dict(fails), recall=wil(kt, n_t), fpr=wil(kh, n_t),
                   n_decided_tampered=sum(1 for x in per if x["t"][d]["decided"]),
                   n_decided_honest=sum(1 for x in per if x["h"][d]["decided"]),
                   k_flagged_both=sum(1 for x in per if x["t"][d]["flag"] and x["h"][d]["flag"]))
        if n_t:
            ind = [int(x["t"][d]["flag"] and not x["h"][d]["flag"]) for x in per]
            adr = pe.boot_stat(ind, lambda g: float(np.mean(g)) if len(g) else None)
            row["adr"] = adr
            # localization: a flagged unit of the tampered copy is (or sits in) the tampered one
            if d in ("N3", "N5g"):
                row["localization"] = {"note": "session-level detector: the decision unit is the session"}
            else:
                kl, kf, und, coll = 0, 0, 0, 0
                for x in per:
                    if not x["t"][d]["flag"]:
                        continue
                    kf += 1
                    if x["tc"] is None:
                        und += 1
                        continue
                    fu = x["t"][d]["flagged"]
                    if d == "R1_BRACKET":
                        hit = bool(fu & x["ts"])
                    elif d == "R3_GIT":
                        hit = any(u[0] in x["tc"] for u in fu)
                    else:
                        hit = bool(fu & x["tc"])
                    kl += int(hit)
                    coll += int((not hit) and not x["h"][d]["flag"])
                row["localization"] = {"k_localized": kl, "k_flagged": kf, "k_undefined_deleted_target": und,
                                       "share": (kl / (kf - und)) if (kf - und) > 0 else None,
                                       "k_new_flag_not_on_target": coll,
                                       "note": "k_new_flag_not_on_target = tampered copy flagged, honest copy not "
                                               "flagged, and no flagged unit is the tampered one (collateral flag)"}
            if d == "R1_BRACKET":
                hn = [x["h"][d]["n_units"] for x in per]
                hk = [len(x["h"][d]["flagged"]) for x in per]
                tn = [x["t"][d]["n_units"] for x in per]
                tk = [len(x["t"][d]["flagged"]) for x in per]
                hr = stats.cluster_rate(hk, hn)
                if hr.get("num") == 0 and hr.get("den", 0) > 0:
                    hr["wilson_hi_per_event"] = stats.wilson(0, int(hr["den"]))[2]
                tr = stats.cluster_rate(tk, tn)
                hi = hr.get("wilson_hi_per_event", hr.get("hi")) if hr.get("num") == 0 else hr.get("hi")
                row["r1_stream_level"] = {
                    "honest_streams": hr, "tampered_streams": tr, "honest_verdict_hi": hi,
                    "phase_d_rule_tampered_lo_gt_honest_hi": (bool(tr["lo"] > hi) if (tr.get("lo") is not None
                                                                                       and hi is not None) else None),
                    "target_stream_flagged": int(sum(1 for x in per if x["ts"] and (x["t"][d]["flagged"] & x["ts"]))),
                    "target_stream_defined": int(sum(1 for x in per if x["ts"]))}
            if d == "R3_GIT":
                row["r3_decided_units_tampered"] = int(sum(x["t"][d]["n_units"] for x in per))
                row["r3_decided_units_honest"] = int(sum(x["h"][d]["n_units"] for x in per))
        if attack == "time_result_early":
            row["clamped_draws"] = clamped
        if rels:
            row["donor_rel_byte_diff"] = {"n": len(rels), "p50": float(np.median(rels)), "max": float(np.max(rels))}
        if near:
            row["splice_nearest_abs_ms"] = {"n": len(near), "p50": float(np.median(near)), "max": float(np.max(near))}
        if unit == "aiv_cc":
            row["label_note"] = "single-agent case study"
        if unit == "cc_local":
            row["label_note"] = "private (aggregates only)"
        rows[d] = row
    return rows, {s: ctx.honest[s] for s in sel if s in ctx.honest}


# ====================================================================================================== jobs
_CTX = {}
PJ = None


def _init_worker():
    global PJ
    PJ = pe.check_frozen()


def attack_params(unit):
    out = []
    for a, ps in ATTACKS:
        for p in ps:
            out.append((a, p))
    return out


def run_job(job):
    unit, split, aps, smoke, cap, do_check = job
    global PJ
    if PJ is None:
        PJ = pe.check_frozen()
    t0 = time.time()
    key = (unit, split)
    if key not in _CTX:
        _CTX.clear()
        _CTX[key] = UnitCtx(unit, split, smoke=smoke, log=lambda m: print(m, flush=True))
    ctx = _CTX[key]
    cells = {}
    honest_union = {}
    for a, p in aps:
        if a in ("inline_fabrication", "image_relabel_gui", "image_insert_screenshot"):
            rows = {}
            for d in TIMING_DETECTORS:
                if d != "N4" and d not in ctx.dets():
                    continue
                base = {"unit": unit, "split": split, "detector": d, "attack": a, "param": str(p)}
                if a in AIV_CU_ONLY and pe.applicable(a, d) and d != "N4":
                    rows[d] = dict(base, label="NOT_RUN", reason="attack defined on aiv_cu only (GUI calls / image "
                                                                   "usage); not injectable in this unit")
                elif d == "N4":
                    rows[d] = dict(base, label="NA_BLIND_BY_CONSTRUCTION",
                                   reason="N4 has no per-session decision rule (prereg_e.json n4_concurrency.n7)")
                else:
                    rows[d] = dict(base, label="NA_BLIND_BY_CONSTRUCTION",
                                   reason=f"attack modifies {sorted(pe.ATTACK_FIELDS[a])}; detector reads "
                                          f"{sorted(pe.DETECTOR_FIELDS[d])} (applicable() False)")
        else:
            t1 = time.time()
            rows, hu = run_cell(ctx, a, p, cap, print)
            honest_union.update(hu)
            print(f"[{unit}|{split}] {a}|{p}: n={next((r.get('n_tampered') for r in rows.values() if 'n_tampered' in r), None)} "
                  f"({time.time() - t1:.1f}s)", flush=True)
        for d, r in rows.items():
            cells[f"{unit}|{split}|{d}|{a}|{p}"] = r
    extra = {}
    if do_check:
        extra["sessions_in_split_unit"] = len(ctx.sids)
        extra["ir_rows"] = int(len(ctx.df))
        if ctx.ctx.get("commits") is not None:
            extra["r3_commit_table_ok_rows"] = ctx.ctx["commits"].n_ok_commits
    # honest flags (for the union summary) without session ids
    hsum = {}
    for sid, h in honest_union.items():
        hsum[sid] = {d: (h[d]["decided"], h[d]["flag"], h[d]["n_units"], len(h[d]["flagged"])) for d in h}
    return {"unit": unit, "split": split, "cells": cells, "honest": hsum, "extra": extra,
            "runtime_s": time.time() - t0}


def chunk(lst, n):
    k = max(1, math.ceil(len(lst) / n))
    return [lst[i:i + k] for i in range(0, len(lst), k)]


# ====================================================================================================== summary
def summarize(cells, honest_by_us):
    lab_order = ["DETECTS", "PARTIAL", "BLIND", "NA_BLIND_BY_CONSTRUCTION", "INSUFFICIENT_N", "NOT_RUN"]
    by_uds = defaultdict(lambda: Counter())
    detecting = defaultdict(list)
    for k, r in cells.items():
        uds = f"{r['unit']}|{r['split']}|{r['detector']}"
        by_uds[uds][r["label"]] += 1
        if r["label"] in ("DETECTS", "PARTIAL"):
            detecting[uds].append({"attack": r["attack"], "param": r["param"], "label": r["label"],
                                   "recall_lo": r["recall"]["lo"], "fpr_hi": r["fpr"]["hi"], "path": f"cells.{k}"})
    per_uds = {}
    for uds, c in by_uds.items():
        u, sp, d = uds.split("|")
        det = [x for x in detecting.get(uds, []) if x["label"] == "DETECTS"]
        per_uds[uds] = {"label_counts": {l: c.get(l, 0) for l in lab_order if c.get(l, 0)},
                        "detects_or_partial": detecting.get(uds, []),
                        "single_call_types_detecting": sorted({x["attack"] for x in det if x["attack"] in SINGLE_CALL}),
                        "attack_types_detecting": sorted({x["attack"] for x in det})}
        hs = honest_by_us.get(f"{u}|{sp}", {})
        if d != "N4" and hs:
            vals = [v[d] for v in hs.values() if d in v]
            k_ = sum(1 for v in vals if v[1])
            per_uds[uds]["honest_union_of_selected_sessions"] = {
                "sessions": len(vals), "flagged": k_, "fpr": wil(k_, len(vals)),
                "decided_sessions": sum(1 for v in vals if v[0]),
                "decided_units": int(sum(v[2] for v in vals)), "flagged_units": int(sum(v[3] for v in vals))}
    # walk-through: attack types with no DETECTS cell in any timing detector x unit x split x param
    walk = []
    for a, _ in ATTACKS:
        rs = [r for r in cells.values() if r["attack"] == a]
        labs = Counter(r["label"] for r in rs)
        det = [r for r in rs if r["label"] == "DETECTS"]
        entry = {"attack": a, "single_call_type": a in SINGLE_CALL, "label_counts": dict(labs),
                 "detecting_cells": sorted(f"{r['unit']}|{r['split']}|{r['detector']}|{r['param']}" for r in det)}
        if not det:
            reasons = []
            if labs.get("NA_BLIND_BY_CONSTRUCTION", 0) == len(rs):
                reasons.append("no timing detector reads a field this attack modifies (all cells NA)")
            if labs.get("NOT_RUN", 0):
                reasons.append("NOT_RUN cells (attack not injectable in a timing unit)")
            if labs.get("INSUFFICIENT_N", 0):
                reasons.append("INSUFFICIENT_N cells")
            if labs.get("BLIND", 0):
                reasons.append("BLIND cells")
            if labs.get("PARTIAL", 0):
                reasons.append("PARTIAL cells only")
            entry["walks_through_timing_detectors"] = True
            entry["reasons"] = reasons
        else:
            entry["walks_through_timing_detectors"] = False
        walk.append(entry)
    return per_uds, walk


# ====================================================================================================== main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--smoke", type=int, default=0, help="first N sessions per unit x split (scratch test only)")
    ap.add_argument("--cap", type=int, default=pe.N7_CAP_SESSIONS)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--units", default="")
    ap.add_argument("--attacks", default="")
    ap.add_argument("--cc_chunks", type=int, default=5)
    a = ap.parse_args(argv)
    t0 = time.time()
    pj = pe.check_frozen()
    if not a.smoke and a.cap != pe.N7_CAP_SESSIONS:
        raise SystemExit("the cap is pre-registered (500); --cap is for smoke tests only")
    if not a.smoke and Path(a.out).resolve() != OUT.resolve():
        print("note: non-default output path", flush=True)
    us = [x for x in UNIT_SPLITS if (not a.units or x[0] in a.units.split(","))]
    aps_all = attack_params(None)
    if a.attacks:
        aps_all = [x for x in aps_all if x[0] in a.attacks.split(",")]
    jobs = []
    for unit, split in us:
        n = a.cc_chunks if unit == "swechat/claude_code" else (3 if unit in ("cc_local", "aiv_cc") else 1)
        # interleave cheap and expensive attack-params across chunks
        parts = [aps_all[i::n] for i in range(n)]
        for i, part in enumerate(parts):
            if part:
                jobs.append((unit, split, part, a.smoke, a.cap, i == 0))
    jobs.sort(key=lambda j: 0 if j[0] == "swechat/claude_code" else 1)
    print(f"{len(jobs)} jobs, {a.workers} workers", flush=True)
    results = []
    if a.workers <= 1:
        for j in jobs:
            results.append(run_job(j))
    else:
        with mp.get_context("spawn").Pool(a.workers, initializer=_init_worker, maxtasksperchild=1) as pool:
            for r in pool.imap_unordered(run_job, jobs):
                print(f"job done {r['unit']}|{r['split']} {r['runtime_s']:.0f}s; elapsed {time.time() - t0:.0f}s",
                      flush=True)
                results.append(r)
    cells, honest_by_us, extras = {}, defaultdict(dict), {}
    for r in results:
        cells.update(r["cells"])
        honest_by_us[f"{r['unit']}|{r['split']}"].update(r["honest"])
        if r["extra"]:
            extras[f"{r['unit']}|{r['split']}"] = r["extra"]
    cells = dict(sorted(cells.items()))
    per_uds, walk = summarize(cells, honest_by_us)
    not_testable = []
    for d, m in NOT_TESTABLE.items():
        for u, why in m.items():
            not_testable.append({"detector": d, "unit": u, "cell": f"NOT_TESTABLE({why})"})
    for u, why in NOT_TESTABLE_COMMON.items():
        not_testable.append({"detector": "all timing detectors", "unit": u, "cell": f"NOT_TESTABLE({why})"})
    out = {
        "item": ITEM,
        "generated_by": "analysis/probes/phase_e_n7_timing.py",
        "prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
        "spec_module_sha256_lf": pe.sha256_lf(Path(pe.__file__)),
        "spec_module_sha256_lf_prereg": pj["provenance"]["spec_module_sha256_lf"],
        "phase_b_prereg_json_sha256": pe.sha256_file(PREREG_B_JSON),
        "script_sha256_lf": pe.sha256_lf(Path(__file__)),
        "smoke": a.smoke, "cap": a.cap, "workers": a.workers,
        "runtime_s": None,
        "scope": {"detectors": TIMING_DETECTORS, "unit_splits": [f"{u}|{s}" for u, s in us],
                  "detector_units": DET_UNITS, "not_testable": not_testable,
                  "N5g_note": "N5g (cold start, session c_s <= 0) is a timing row of the applicability matrix; the "
                              "content half (phase_e_n7_content.py TIMING_HALF) assigns it to this item"},
        "prereg_paths": {"attacks": "prereg_e.json n7_attack_battery.attacks", "detectors":
                         "prereg_e.json n7_attack_battery.detectors", "cell_label": "n7_cell_label()",
                         "session_flag": "prereg_e.json n7_attack_battery.session_flag",
                         "floors": "prereg_e.json resolved.n7.floor_thresholds",
                         "G90": "prereg.json resolved.probe1.generation_rate.<unit>.G90",
                         "n1_bounds": "prereg_e.json resolved.n1.<unit>.bounds",
                         "r1_tol_ms": pe.BRACKET_TOL_MS, "r3_window": "git_window_ok(tol_s=2.0)",
                         "n3_rule": "session flagged if rho_s <= 0 with >= 20 gaps (n3_reaction_time.detector)"},
        "thresholds_used": {
            "floors_s": {u: {k: v["threshold_s"] for k, v in pj["resolved"]["n7"]["floor_thresholds"].get(u, {}).items()}
                         for u in LAT_UNITS},
            "G90_tok_per_s": G90, "tokens_per_char": TPC, "T_gen_min_s": T_GEN_MIN,
            "n1_bounds": {u: pj["resolved"]["n1"][u]["bounds"] for u in LAT_UNITS},
            "n1_bounds_source": {u: pj["resolved"]["n1"][u]["source"] for u in LAT_UNITS},
            "W_keys": {u: (sorted(pcal.W_KEYS[u]) if u in pcal.W_KEYS else "class auto_read") for u in LAT_UNITS},
            "bracket_tol_ms": pe.BRACKET_TOL_MS, "cap_sessions": pe.N7_CAP_SESSIONS, "min_sessions": pe.N7_MIN_SESSIONS,
            "matched_bytes_tol": pe.MATCHED_BYTES_TOL, "grid_D": GRID_D, "grid_D_late_check": GRID_LATE,
            "rewrite_k": pe.REWRITE_K},
        "target_rules": TARGET_RULES,
        "seeds": {"session_order": "rng_for('N7', unit, split).permutation(sorted session ids)",
                  "target": "rng_for(attack, str(param), session_id).integers(0, n_targets)",
                  "donor": "rng_for('donor', attack, str(param), session_id)", "bootstrap": stats.SEED,
                  "SEED_E": pe.SEED_E},
        "unit_split_checks": extras,
        "n_cells": len(cells),
        "n_verdict_cells": sum(1 for r in cells.values() if r["label"] in ("DETECTS", "PARTIAL", "BLIND",
                                                                          "INSUFFICIENT_N")),
        "cells": cells,
        "verdicts": {"rule": "n7_cell_label(): DETECTS if recall >= 0.5 and recall CI lo > FPR CI hi; PARTIAL if recall "
                             "CI lo > FPR CI hi; BLIND otherwise; INSUFFICIENT_N below 30 tampered sessions. Deciding "
                             "numbers: cells.<key>.recall.lo, cells.<key>.recall.p and cells.<key>.fpr.hi",
                     "per_unit_split_detector": per_uds,
                     "walk_through_timing_only": walk},
    }
    out["runtime_s"] = time.time() - t0
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(clean(out), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.out} ({len(cells)} cells) in {out['runtime_s']:.0f}s", flush=True)


if __name__ == "__main__":
    PJ = pe.check_frozen()
    main()
