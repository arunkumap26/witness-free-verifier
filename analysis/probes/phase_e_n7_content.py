"""Phase E, N7 attack battery: the CONTENT / ACCOUNTING detectors (item key n7_content).

Pre-registration: analysis/PREREG_E.md section 4, analysis/prereg_e.json `n7_attack_battery`, and the frozen code in
analysis/probes/prereg_e_common.py (injectors atk_*, pick_donor, applicable, n7_cell_label, rng_for, the N2/N5/R2/R4
helpers). check_frozen() runs before anything else and the script stops if it fails.

This script covers the detectors of the applicability matrix that read content or accounting fields:
  P2_KFN (Probe 2 knowledge_from_nowhere), P3_ZERO (Probe 3 zero-error long session), N2 (token accounting),
  N5a (determinism), N5b (sort order), N5c (truncation boundary), N5d (whitespace), N5f (error fidelity),
  R2_IMAGE (aiv_cu Gemini image-token ledger), R4_DUAL (Claude Code numLines dual rendering, raw join),
  R5_LEDGER (Entire usage tally, raw join, Claude format).
The timing detectors (R1_BRACKET, P1_FLOOR, P1_GEN, N1, N3, N5g, R3_GIT, N4) are measured by the timing half of the
battery and are not computed here. Probe 4 has no N7 detector in the pre-registration (see DEVIATIONS).

Output (RAW NUMBERS ONLY): analysis/out/phase_e/n7_content.json, assembled from per unit x split shards in
analysis/out/phase_e/n7_content_shards/ (prereg_e.json outputs.N7 allows per unit x split shards). Interpretation lives in
analysis/notes/phase_e_n7_content.md, never here.

Run (worktree root, Git Bash):
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n7_content --jobs <unit:split,...>   # writes shards
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n7_content --merge                   # writes n7_content.json
  --limit N (debug only) caps the sessions per job and writes to --out-dir instead of analysis/out.

Data: analysis/cache/<corpus>_{B,E}.parquet through prereg_e_common.read_cache (never A, never H). Raw joins named by the
prereg: data/swe-chat-pinned transcripts (R4 numLines, R5 assistant usage records), sessions.parquet + session_logs.parquet
(R5 tally), data/claude-code-local snapshot for cc_local split B ids (R4; in-process, aggregates only).
cc_local is private: only aggregate counts leave this script. aiv_cc numbers carry "single-agent case study".
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import parse_ts
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe
from analysis.probes import probe_2 as p2
from analysis.probes.phase_c_swechat_tables import _i as tally_int
from analysis.probes.phase_c_swechat_tables import _match as tally_match

ROOT = pe.ROOT
ITEM = "n7_content"
SCRIPT_SHA_AT_START = pe.sha256_lf(Path(__file__))   # the code this process runs (recorded in every shard)
OUT_JSON = pe.OUT_E / "n7_content.json"
SHARD_DIR = pe.OUT_E / "n7_content_shards"
PREREG_B = json.loads((ROOT / "analysis" / "prereg.json").read_text(encoding="utf-8"))
SWE_LOGS = Path("C:/Swarms/data/swe-chat-pinned/session_logs.parquet")
CC_LOCAL_ROOT = Path("C:/Swarms/data/claude-code-local")

DETECTORS = ["P2_KFN", "P3_ZERO", "N2", "N5a", "N5b", "N5c", "N5d", "N5f", "R2_IMAGE", "R4_DUAL", "R5_LEDGER"]
TIMING_HALF = ["R1_BRACKET", "P1_FLOOR", "P1_GEN", "N1", "N3", "N5g", "R3_GIT", "N4"]
DECISION_UNIT = {"P2_KFN": "call (deep first-try successful access, any thread)", "P3_ZERO": "session (long, >= L75)",
                 "N2": "response (last call's result >= 800 chars)", "N5a": "determinism pair", "N5b": "output (per checker)",
                 "N5c": "marked output (cc_chars_mid, cc_glob_cap)", "N5d": "output (per whitespace check)",
                 "N5f": "traceback frame", "R2_IMAGE": "image window", "R4_DUAL": "result with a raw numLines counter",
                 "R5_LEDGER": "session with an Entire tally"}
E_NOT_BLIND = {"R4_DUAL", "R5_LEDGER"}   # prereg_e.json splits.E_freshness.E_SEEN_candidates (R3 is in the timing half)

UNIT_CFG = {
    "swechat/claude_code": {"corpus": "swechat", "fmt": "claude_code", "splits": ["B", "E"]},
    "swechat/opencode": {"corpus": "swechat", "fmt": "opencode", "splits": ["B", "E"]},
    "swechat/codex": {"corpus": "swechat", "fmt": "codex", "splits": ["B", "E"]},
    "swechat/gemini": {"corpus": "swechat", "fmt": "gemini", "splits": ["B", "E"]},
    "swechat/cursor": {"corpus": "swechat", "fmt": "cursor", "splits": ["B", "E"]},
    "cc_local": {"corpus": "cc_local", "splits": ["B"]},
    "aiv_cc": {"corpus": "aiv_cc", "splits": ["B"]},
    "aiv_cu": {"corpus": "aiv_cu", "splits": ["B", "E"]},
    "whowhen": {"corpus": "whowhen", "splits": ["B"]},
}
ZERO_SESSION_UNITS = ["swechat/copilot", "swechat/simple_text"]
LOAD_COLS = ["session_id", "stratum", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "args", "command", "text",
             "stderr", "native_error", "exit_code", "usage_in", "usage_out", "api_msg_id", "request_id", "model",
             "is_subagent", "parent_call_id", "agent_id", "uuid", "parent_uuid", "extra"]
LIGHT_COLS = ["session_id", "call_id", "seq", "tool", "key", "n1", "err", "bytes", "chars", "delta_s", "_ix", "_ix_r",
              "is_subagent", "agent_id"]
PALL_COLS = ["session_id", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "args", "command", "text",
             "stderr", "native_error", "exit_code", "stratum", "is_subagent", "agent_id"]
P2_COLS = ["session_id", "seq", "kind", "tool", "tool_raw", "call_id", "args", "command", "text", "stderr",
           "native_error", "exit_code", "is_subagent", "agent_id", "extra", "stratum"]

LINE_PREFIX = re.compile("^\\s*\\d+(\u2192|\\t)")   # phase_a6_raw_census._LINE_PREFIX (A6-O1 recount), unchanged
DIGIT = re.compile(r"\d")
FRAME_HINT = (pe._R["py_frame"], pe._R["rust_frame"])
PJ_RESOLVED = json.loads(pe.PREREG_E_JSON.read_text(encoding="utf-8"))["resolved"]
TRUNC = PJ_RESOLVED["n5"]["truncation_constants_pooled"]


def attack_grid():
    g = []
    for a in ("time_result_early", "time_result_late", "time_tail_late", "time_tail_early", "time_response_early"):
        g += [(a, f"{d:g}") for d in pe.GRID_D]
    g += [("time_response_late", f"{d:g}") for d in pe.GRID_D_LATE_CHECK]
    g += [("id_swap_adjacent", "-"), ("id_splice_foreign", "random"), ("id_splice_foreign", "nearest"),
          ("sub_single_flip_error", "-"), ("sub_single_digit", "-"), ("sub_matched_bytes", "any"),
          ("sub_matched_bytes", "samecmd"), ("rewrite_consistent_k", "2"), ("rewrite_consistent_k", "5"),
          ("reorder_adjacent_pairs", "-"), ("reorder_lines", "-"), ("delete_pair", "-"), ("delete_response", "-"),
          ("insert_pair_consistent", "-"), ("insert_pair_squeezed", "-"), ("inline_fabrication", "tau"),
          ("image_relabel_gui", "-"), ("image_insert_screenshot", "-")]
    return g


ATTACKS = attack_grid()
NO_LOCALIZATION = {"delete_pair", "delete_response"}   # the tampered unit no longer exists in the tampered copy

DEVIATIONS = [
    {"item": "output file names",
     "prereg_said": "outputs.N7: phase_e_n7_attacks.py -> n7_attacks.json (per unit x split shards allowed)",
     "what_you_did": "the battery was split by the orchestrator into a timing half and this content/accounting half; this "
                     "half is analysis/probes/phase_e_n7_content.py -> analysis/out/phase_e/n7_content.json, assembled "
                     "from per unit x split shards in analysis/out/phase_e/n7_content_shards/",
     "why": "two concurrent agents write the two halves; distinct file names avoid overwriting",
     "effect_on_verdict": "none"},
    {"item": "Probe 4 (entropy / round numbers) has no N7 detector",
     "prereg_said": "n7_attack_battery.detectors and the applicability matrix (ATTACK_FIELDS x DETECTOR_FIELDS) list no "
                    "Probe 4 detector; the task brief for this item names Probe 4 among the detectors",
     "what_you_did": "Probe 4 is reported as NOT_RUN for every unit and attack; no Probe 4 decision rule was invented",
     "why": "defining a per-session Probe 4 detector and threshold now would be a threshold set after the battery started",
     "effect_on_verdict": "no Probe 4 cells; NOT_RUN is never a null"},
    {"item": "rewrite_consistent_k error fields",
     "prereg_said": "attacks.rewrite_consistent_k: k results 'replaced by matched-bytes donors'; ATTACK_FIELDS declares "
                    "{text, error, ts}; the frozen injector atk_rewrite_consistent() replaces text and stamps only",
     "what_you_did": "after atk_rewrite_consistent(), each replaced result takes its donor's native_error (pd.NA when the "
                     "donor has none) and stderr is cleared, exactly as atk_substitute() does for sub_matched_bytes",
     "why": "the declared attack fields include error and the attack text says the results are replaced by the donors; "
            "keeping the original error flag would leave an inconsistent record (success text, error flag)",
     "effect_on_verdict": "rewrite_consistent_k cells of detectors that read the error field (P2_KFN first-try success, "
                          "P3_ZERO, N5f); other cells unaffected"},
    {"item": "insert_pair_* and image_insert_screenshot: donor usage stripped",
     "prereg_said": "attacks.image_insert_screenshot: 'a donor GUI call+result inserted with usage untouched'; the frozen "
                    "atk_insert_pair() nulls the usage columns (usage_in, usage_out, request_id, api_msg_id) of every "
                    "inserted row but copies the donor's `extra`, which in aiv_cu holds the donor response's "
                    "usage_detail.promptTokensDetails",
     "what_you_did": "for every insert attack the key usage_detail is removed from the donor call's extra before "
                     "atk_insert_pair() is called (only aiv_cu calls carry it)",
     "why": "otherwise image_windows() reads the donor session's cumulative IMAGE count as a usage-bearing call of the "
            "target session, and R2 would 'detect' an injector artifact rather than the missing screenshot accounting",
     "effect_on_verdict": "R2_IMAGE cells of insert_pair_consistent, insert_pair_squeezed and image_insert_screenshot "
                          "(aiv_cu); no other detector reads a call's usage_detail"},
    {"item": "insert_pair_*: thread of the inserted pair",
     "prereg_said": "attacks.insert_pair_consistent: 'a donor call+result pair (another session, same unit) inserted after "
                    "a result event'; silent on the thread fields of the inserted rows",
     "what_you_did": "the donor rows' is_subagent, agent_id and parent_call_id are set to those of the anchor result before "
                     "atk_insert_pair() is called, so the pair lands in the anchor's thread",
     "why": "a donor from another session's subagent would otherwise create a foreign thread id in the target session",
     "effect_on_verdict": "thread-scoped detectors (P2_KFN sourcing, N5a intervening events) on insert_* cells"},
    {"item": "session sample per detector population",
     "prereg_said": "sessions: every session with >= 1 eligible target for the attack, capped at 500 by a seeded draw "
                    "rng_for('N7', unit, split)",
     "what_you_did": "the sorted session ids of the unit x split are permuted once with rng_for('N7', unit, split); per "
                     "attack x parameter x detector the cell takes the first 500 sessions in that order that have an "
                     "eligible target AND belong to the detector's population (R2_IMAGE: aiv_cu Gemini strata; N2 on "
                     "aiv_cu: GRANULAR strata; P3_ZERO on whowhen: Algorithm-Generated stratum; all sessions otherwise)",
     "why": "R2, aiv_cu N2 and whowhen P3 are defined on sub-populations of their unit; one seeded order keeps the "
            "samples nested and reproducible",
     "effect_on_verdict": "none beyond the stated populations"},
    {"item": "FPR denominator and abstention",
     "prereg_said": "recall: abstention counted as not flagged; FPR on the same sessions untampered (same aggregation)",
     "what_you_did": "FPR uses the same session set as recall and counts an abstaining untampered session as not "
                     "flagged; abstention counts are reported for both copies",
     "why": "the prereg states that the same aggregation is used on both copies",
     "effect_on_verdict": "none"},
    {"item": "ADR confidence interval",
     "prereg_said": "ADR gets the session bootstrap (boot_stat)",
     "what_you_did": "ADR = mean over sessions of [flag tampered AND NOT flag honest]; CI from stats.cluster_rate with one "
                     "indicator per session (vectorised session bootstrap, seed 20261003, 1,000 draws)",
     "why": "same resampling unit, seed and draw count as boot_stat; vectorised for the ~10^3 cells",
     "effect_on_verdict": "none (ADR does not enter n7_cell_label)"},
    {"item": "R5_LEDGER scope and tamper propagation",
     "prereg_said": "R5: Entire 5-integer tally (sessions.parquet) vs a tolerance-0 recount of deduplicated per-response "
                    "usage; NOT_RUN if not implemented",
     "what_you_did": "implemented for the Claude Code format only, with the committed Phase C recount (phase_c_swechat_"
                     "tables F0: assistant records of the raw transcript, distinct message.id in first-occurrence order, "
                     "usage of the last record per id; _match() full/prefix/window/none; tally gated on session_logs "
                     "token_usage like _meta_for_tx). Flag = class 'none'. Sessions with api_call_count 0 abstain (the "
                     "check is vacuous). A tampered IR copy removes every raw record whose uuid no longer occurs in it "
                     "(records never represented in the IR stay); inline_fabrication adds round(tau x chars) to the "
                     "message's output tokens. swechat codex/opencode/gemini/cursor: NOT_RUN (X0/O0/G0 recounts not "
                     "implemented here)",
     "why": "smallest faithful recount; the IR carries record uuids for every assistant record (checked on 3 B sessions)",
     "effect_on_verdict": "R5 cells exist for swechat/claude_code only; label 'E not blind' on E"},
    {"item": "R4_DUAL visible text and inserted pairs",
     "prereg_said": "R4: raw toolUseResult.file.numLines joined on tool_use_id; mismatch inside dual_whitelisted() excused",
     "what_you_did": "numLines from raw (swechat transcripts; cc_local snapshot main + subagent files, B ids, in-process); "
                     "the visible line count is computed on the IR result text with the A6-O1 rule (lines matching "
                     "^\\s*\\d+(U+2192|\\t)); a decision unit is a result whose call_id carries a raw numLines; inserted "
                     "pairs get a new call_id and therefore no counter (abstain)",
     "why": "tampering acts on the IR, so the visible side must be the IR text; the structured copy stays with its id",
     "effect_on_verdict": "honest R4 rates include any IR-vs-raw text difference (reported as the honest rate)"},
    {"item": "P2_KFN decision units",
     "prereg_said": "detector P2_KFN: 'call: knowledge_from_nowhere (Phase B definition, D_unit)'",
     "what_you_did": "Probe 2 process_unit() (committed Phase B code) on the session; decision units = first accesses by an "
                     "access tool (not the secondary read-shell rows) with known depth >= D_unit and first-try success, "
                     "in every thread (main and subagent); flagged if unsourced",
     "why": "knowledge_from_nowhere is defined per thread in Phase B; S_deep restricts the RATE to main threads, the "
            "detector does not",
     "effect_on_verdict": "none beyond the stated unit"},
    {"item": "P2_KFN localization on cc_local",
     "prereg_said": "localization = whether the flagged unit is the tampered one",
     "what_you_did": "not computed for cc_local (Probe 2's per-access debug hook, which carries the call seq, is disabled "
                     "for the private unit); null with reason",
     "why": "privacy guard in committed Phase B code",
     "effect_on_verdict": "none (localization does not enter n7_cell_label)"},
]

IMPLEMENTATION = {
    "seeds": "session order rng_for('N7', unit, split).permutation(sorted session ids); target rng_for(attack, param, "
             "session_id); donor rng_for('donor', attack, param, session_id); param strings: '-' for attacks without a "
             "parameter, 'any'/'samecmd', '2'/'5', 'tau'",
    "targets": {
        "sub_single_flip_error": "a paired result whose primary error (pc.error_classes) is True and whose tool_key has a "
                                 "successful donor result in another session within 5% bytes",
        "sub_single_digit": "a result event whose text contains a digit",
        "sub_matched_bytes": "a paired result with a same-tool_key donor (any status) in another session within 5% bytes; "
                             "samecmd: donor with the same n1_key",
        "rewrite_consistent_k": "k consecutive paired results of one thread (seq order), each with a same-tool_key donor "
                                "within 5% bytes that has a finite call->result latency",
        "reorder_adjacent_pairs": "two consecutive paired calls of one thread whose (tool, args, result text) differ",
        "reorder_lines": "a result event with >= 3 lines and >= 1 adjacent differing line pair",
        "delete_pair": "a paired call", "delete_response": "a request id present in the session",
        "insert_pair_consistent": "anchor = a result event; donor = a paired call from another session (uniform); donor "
                                  "gap = donor call ts - previous event ts of the donor session, latency = its delta",
        "insert_pair_squeezed": "as consistent, anchor restricted to results whose next event is >= 2 ms later",
        "inline_fabrication": "an API response (response_table) whose last call has a result with >= 1 char, in a unit or "
                              "aiv_cu stratum with a tau",
        "image_relabel_gui": "a GUI call (aiv_cu)", "image_insert_screenshot": "anchor = a result event; donor = a GUI "
                                                                              "pair from another session",
    },
    "pairs_for_detectors": "pc.make_pairs() without the delta_s column (the content detectors never read it)",
    "n5_eligibility": "as prereg_e_calibration.cal_n5: sort/whitespace checks on shell-family commands, grep_n also on the "
                      "Grep tool with -n and output_mode content, truncation_info on every paired result; N5c items "
                      "cc_chars_mid (prefix and suffix must equal 5002 / 5002 UTF-16 units) and cc_glob_cap (100 lines); "
                      "cc_lines_tail NOT_RUN (n_A 4 < 5)",
    "missing_stamps": "before an injector runs, missing stamps of the session copy are passed as None instead of pd.NA "
                      "(pandas 3 string dtype); the frozen injectors call parse_ts(), which accepts None only",
    "n5f_prefilter": "error_fidelity_checks() is called only when an error result carries a py_frame or rust_frame match "
                     "(otherwise it returns no frame by construction)",
}


# ====================================================================================================== helpers
def sha256_lf(p):
    return pe.sha256_lf(p)


def wil(k, n):
    p, lo, hi = stats.wilson(k, n)
    return [p, lo, hi]


def thread_key(is_sub, agent):
    b = False if (is_sub is None or is_sub is pd.NA or (isinstance(is_sub, float) and math.isnan(is_sub))) else bool(is_sub)
    return (b, (agent if isinstance(agent, str) else "") if b else "")


def native_val(x):
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return pd.NA
    return bool(x)


def key_of(unit, tool, tool_raw):
    k = pc.tool_key(unit, tool if isinstance(tool, str) else None, tool_raw if isinstance(tool_raw, str) else None)
    return pc.private_key(k) if unit == "cc_local" else k


def pairs_nodelta(s):
    """pc.make_pairs() without delta_s: calls joined to results on (session_id, call_id), first by seq each."""
    calls = s[s.kind == "call"].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
    res = s[(s.kind == "result") & s.call_id.notna()].sort_values(["session_id", "seq"]).drop_duplicates(
        ["session_id", "call_id"])
    keep_r = [c for c in res.columns if c not in ("kind",)]
    return calls.merge(res[keep_r], on=["session_id", "call_id"], suffixes=("", "_r"))


def enrich_pairs(unit, P):
    """key, n1, err (primary), bytes/chars of the result text."""
    if not len(P):
        for c in ("key", "n1", "err", "bytes", "chars"):
            P[c] = pd.Series(dtype=object)
        return P
    keys = [key_of(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    raw_keys = [pc.tool_key(unit, t if isinstance(t, str) else None, tr if isinstance(tr, str) else None)
                for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    txt = pc.sobj(P.text_r)
    P = P.assign(key=keys)
    P["n1"] = [pe.n1_key(unit, k, a, c) for k, a, c in zip(keys, P.args.astype(object), P.command.astype(object))]
    err = []
    for k, tr, t, e, n, x, st in zip(raw_keys, P.tool_raw.astype(object), txt, P.stderr_r.astype(object),
                                     P.native_error_r.astype(object), P.exit_code_r.astype(object),
                                     P.stratum.astype(object)):
        r = pc.error_classes(unit, k, tr if isinstance(tr, str) else None, t, e if isinstance(e, str) else None,
                             None if n is pd.NA else n, None if x is pd.NA else x, st if isinstance(st, str) else None)
        err.append(bool(r[0]) if r[0] is not None else False)
    P["err"] = err
    P["bytes"] = [len(t.encode("utf-8")) if t else 0 for t in txt]
    P["chars"] = [len(t) if t else 0 for t in txt]
    return P


def shell_of(unit, k, args, cmd):
    shellish = k == "shell" or k in pc.CODEX_SHELL_RAW or str(k).endswith("__bash")
    if not shellish:
        return None
    return pc.shell_command(unit, k, pc.jl(args) if isinstance(args, str) else {}, cmd if isinstance(cmd, str) else None)


# ====================================================================================================== session view
class View:
    """One session (honest or tampered) and the lazily computed tables the detectors share."""

    def __init__(self, unit, sid, frame, usage_add=None):
        self.unit, self.sid = unit, sid
        self.s = frame.sort_values("seq", kind="stable")
        self.usage_add = usage_add or {}
        self._P = None
        self._resp = None

    @property
    def P(self):
        if self._P is None:
            self._P = enrich_pairs(self.unit, pairs_nodelta(self.s))
        return self._P

    @property
    def resp(self):
        if self._resp is None:
            self._resp = pe.response_table(self.unit, self.s)
        return self._resp

    def seq2cid(self):
        return dict(zip(self.P.seq.astype(int), self.P.call_id.astype(str)))


# ====================================================================================================== raw joins
def raw_swechat_cc(sid):
    """(numLines by tool_use_id, assistant records [(uuid, msg_id, (in, cc, cr, out))]) from the raw transcript."""
    p = pe.SWE_TRANSCRIPTS / f"{sid}.jsonl"
    nl, recs = {}, []
    if not p.exists():
        return None
    idx = -1
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            idx += 1
            has_nl = '"numLines"' in line
            has_as = '"assistant"' in line
            if not (has_nl or has_as):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if d.get("type") == "assistant":
                m = d.get("message") or {}
                if isinstance(m, dict):
                    mid = m.get("id") or f"__noid_{idx}"
                    u = m.get("usage") or {}
                    tup = (tally_int(u.get("input_tokens")), tally_int(u.get("cache_creation_input_tokens")),
                           tally_int(u.get("cache_read_input_tokens")), tally_int(u.get("output_tokens")))
                    recs.append((d.get("uuid"), mid, tup))
            if has_nl:
                _numlines_from_entry(d, nl)
    return {"numlines": nl, "recs": recs}


def _numlines_from_entry(d, nl):
    tur = d.get("toolUseResult")
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
    tr = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"), None)
    if not isinstance(tur, dict) or tr is None:
        return
    f = tur.get("file")
    if isinstance(f, dict) and type(f.get("numLines")) is int and tr.get("tool_use_id"):
        nl.setdefault(str(tr["tool_use_id"]), f["numLines"])


def raw_cc_local(sid, files):
    """numLines by tool_use_id from the frozen cc_local snapshot (main + subagent files). In-process only."""
    nl = {}
    for _, rel in files:
        p = CC_LOCAL_ROOT / rel
        if not p.exists():
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"numLines"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    _numlines_from_entry(d, nl)
    return {"numlines": nl, "recs": None}


def swechat_tallies(sids):
    """{session_id: meta} for R5, as phase_c_swechat_tables._meta_for_tx (tally only when token_usage is a dict)."""
    import pyarrow.parquet as pq
    ids = sorted(set(sids))
    s = pq.read_table(pe.SWE_SESSIONS, columns=["session_id", "input_tokens", "output_tokens", "cache_creation_tokens",
                                                "cache_read_tokens", "api_call_count"],
                      filters=[("session_id", "in", ids)]).to_pandas()
    logs = pq.read_table(SWE_LOGS, columns=["session_id", "session_metadata_raw"],
                         filters=[("session_id", "in", ids)]).to_pandas()
    md = dict(zip(logs.session_id.astype(str), logs.session_metadata_raw))
    out = {}
    for r in s.itertuples(index=False):
        try:
            raw = json.loads(md.get(str(r.session_id)) or "{}")
        except (ValueError, TypeError):
            raw = {}
        tu = raw.get("token_usage") if isinstance(raw, dict) else None
        if isinstance(tu, dict):
            out[str(r.session_id)] = {"api": tally_int(r.api_call_count), "in": tally_int(r.input_tokens),
                                      "cc": tally_int(r.cache_creation_tokens), "cr": tally_int(r.cache_read_tokens),
                                      "out": tally_int(r.output_tokens)}
    return out


# ====================================================================================================== detectors
class Ctx:
    """Unit x split context: thresholds, raw joins, populations."""

    def __init__(self, unit, split):
        self.unit, self.split = unit, split
        self.corpus = UNIT_CFG[unit]["corpus"]
        self.D = p2.D_UNIT.get(unit)
        L = PREREG_B["resolved"]["probe3"]["long_session"].get(unit)
        self.L75 = int(L["L75"]) if L else None
        self.n2 = PJ_RESOLVED["n2"].get(unit, {})
        self.tau_by_stratum = {}
        if unit == "aiv_cu":
            for st, v in (self.n2.get("by_stratum") or {}).items():
                if v.get("GRANULAR") and v.get("tau") is not None:
                    self.tau_by_stratum[st] = float(v["tau"])
        self.tau_unit = float(self.n2["tau"]) if self.n2.get("GRANULAR") and self.n2.get("tau") is not None else None
        iu = PJ_RESOLVED["image_units_A"]["rule"]
        self.img_per_model = {m: v["unit"] for m, v in iu["per_model"].items()}
        self.img_family = iu["family_units"]
        self.raw = {}           # sid -> raw dict (R4/R5)
        self.tally = {}         # sid -> meta (R5)
        self.ir_uuids = {}      # sid -> set of uuids in the honest IR (R5)
        self.stratum = {}

    def tau(self, sid):
        if self.unit == "aiv_cu":
            return self.tau_by_stratum.get(self.stratum.get(sid))
        return self.tau_unit

    def img_unit(self, model):
        if not isinstance(model, str):
            return None
        if model in self.img_per_model and self.img_per_model[model]:
            return float(self.img_per_model[model])
        for fam, u_ in self.img_family.items():
            if model.startswith(fam):
                return float(u_)
        return None


def det_P2(ctx, v):
    unit = ctx.unit
    kinds = ["user", "system", "call", "result"] + (["assistant"] if ctx.corpus in ("swechat", "whowhen") else [])
    s = v.s[v.s.kind.isin(kinds)][P2_COLS]
    if not len(s):
        return []
    A = {"sessions": set(), "threads": {"main": set(), "sub": set()}, "refs": [], "access": [], "calls": Counter(),
         "calls_with_any_reference": Counter(), "calls_with": Counter(), "redacted_path": Counter(),
         "redacted_ref": Counter(), "redacted_ref_first": Counter(), "root_status": Counter()}
    p2.DEBUG_ACCESS = [] if unit != "cc_local" else None
    p2.process_unit(unit, s, A)
    dbg = p2.DEBUG_ACCESS
    p2.DEBUG_ACCESS = None
    seq2cid = dict(zip(s[s.kind == "call"].seq.astype(int), s[s.kind == "call"].call_id.astype(str)))
    out = []
    for j, r in enumerate(A["access"]):
        st, _s, tool, kind, secondary, fm, pair, success, ecls, depth, uns = r[:11]
        if secondary or depth < 0 or not success or depth < ctx.D:
            continue
        cids = set()
        if dbg is not None and j < len(dbg):
            cids = {seq2cid.get(int(dbg[j][4]), "")}
        out.append((("kfn", j), bool(uns), cids if dbg is not None else None))
    return out


def det_P3(ctx, v):
    P = v.P
    if ctx.unit == "whowhen":
        P = P[(P.stratum.astype(object) == "Algorithm-Generated") & (P.tool.astype(object) == "code_exec")]
    n = len(P)
    if ctx.L75 is None or n < ctx.L75:
        return []
    n_err = int(np.sum(P.err.to_numpy(dtype=bool))) if n else 0
    return [(("session",), n_err == 0, {"__session__"})]


def det_N2(ctx, v):
    tau = ctx.tau(v.sid)
    if tau is None:
        return []
    R = v.resp
    if not len(R):
        return []
    P = v.P
    rc = {(s, c): len(t) for s, c, t in zip(P.session_id, P.call_id.astype(str), P.text_r.astype(object))
          if isinstance(t, str)}
    R = R.assign(last_call_id=R.last_call_id.astype(str))
    extra = {(v.sid, r): a for r, a in v.usage_add.items()}
    fl = pe.n2_flags(R, rc, tau, extra_out=extra)
    lc = dict(zip(R.resp.astype(str), R.last_call_id))
    return [(("resp", str(r)), bool(f), {lc.get(str(r), ""), "__resp__" + str(r)}) for _, r, f in fl]


def det_N5a(ctx, v):
    P = v.P
    if not len(P):
        return []
    dp = pe.determinism_pairs(ctx.unit, v.s, P)
    if not dp:
        return []
    m = v.seq2cid()
    return [(("pair", a, b, "<R>" in str(nk)), pe.mask_volatile(ti) != pe.mask_volatile(tj), {m.get(a, ""), m.get(b, "")})
            for _, a, b, nk, ti, tj in dp]


def det_N5b(ctx, v):
    out = []
    P = v.P
    for cid, k, a, cmd, t in zip(P.call_id.astype(str), P.key, P.args.astype(object), P.command.astype(object),
                                 P.text_r.astype(object)):
        sc = shell_of(ctx.unit, k, a, cmd)
        if sc:
            for name, fn in (("ls", pe.ls_order_violation), ("git_log", pe.gitlog_order_violation),
                             ("grep_n", pe.grepn_order_violation)):
                r = fn(sc, t)
                if r is not None:
                    out.append(((name, cid), bool(r), {cid}))
        if k == "grep":
            r = pe.grepn_order_violation(a, t, is_grep_tool=True)
            if r is not None:
                out.append((("grep_tool", cid), bool(r), {cid}))
    return out


def det_N5c(ctx, v):
    out = []
    P = v.P
    cm, gc_ = TRUNC["cc_chars_mid"], TRUNC["cc_glob_cap"]
    for cid, t in zip(P.call_id.astype(str), P.text_r.astype(object)):
        ti = pe.truncation_info(t)
        if not ti:
            continue
        if ti["item"] == "cc_chars_mid":
            out.append((("chars_mid", cid), not (ti["prefix_u16"] == cm["prefix_u16"] and
                                                  ti["suffix_u16"] == cm["suffix_u16"]), {cid}))
        elif ti["item"] == "cc_glob_cap":
            out.append((("glob_cap", cid), ti["lines"] != gc_["lines"], {cid}))
    return out


def det_N5d(ctx, v):
    out = []
    P = v.P
    for cid, k, a, cmd, t in zip(P.call_id.astype(str), P.key, P.args.astype(object), P.command.astype(object),
                                 P.text_r.astype(object)):
        sc = shell_of(ctx.unit, k, a, cmd)
        if sc:
            for name, val in pe.ws_violations(sc, t).items():
                out.append(((name, cid), bool(val), {cid}))
    return out


def det_N5f(ctx, v):
    P = v.P
    if not len(P):
        return []
    hit = False
    for e, t in zip(P.err, P.text_r.astype(object)):
        if e and isinstance(t, str) and any(rx.search(t) for rx in FRAME_HINT):
            hit = True
            break
    if not hit:
        return []
    ef = pe.error_fidelity_checks(ctx.unit, v.s, P)
    m = v.seq2cid()
    return [(("frame", q, pk, ln, i), not faithful, {m.get(q, "")}) for i, (_, q, pk, ln, faithful) in enumerate(ef)]


def _usage_bearing(ex):
    if isinstance(ex, str) and "promptTokensDetails" in ex:
        det = (pc.jl(ex).get("usage_detail") or {}).get("promptTokensDetails") or {}
        if isinstance(det, dict):
            return True
    return False


def det_R2(ctx, v):
    W = pe.image_windows(v.s)
    if not len(W):
        return []
    c = v.s[v.s.kind == "call"].sort_values(["session_id", "seq"])
    ub = [int(q) for q, ex in zip(c.seq, c.extra.astype(object)) if _usage_bearing(ex)]
    cseq = c.seq.astype(int).to_numpy()
    ccid = c.call_id.astype(str).to_numpy()
    out = []
    for j, (q, d, n, m) in enumerate(zip(W.seq, W.d_image, W.n_gui, W.model)):
        unit_tokens = ctx.img_unit(m)
        if unit_tokens is None:
            continue
        lo, hi = ub[j], ub[j + 1]
        assert hi == int(q)
        cids = set(ccid[(cseq >= lo) & (cseq < hi)].tolist())
        out.append((("win", int(q)), bool(pe.image_window_violation(d, n, unit_tokens)), cids))
    return out


def det_R4(ctx, v):
    raw = ctx.raw.get(v.sid)
    if not raw or not raw.get("numlines"):
        return []
    nl = raw["numlines"]
    r = v.s[(v.s.kind == "result") & v.s.call_id.notna()].drop_duplicates("call_id")
    out = []
    for cid, t in zip(r.call_id.astype(str), r.text.astype(object)):
        if cid not in nl:
            continue
        t = t if isinstance(t, str) else ""
        L = sum(1 for ln in t.split("\n") if LINE_PREFIX.match(ln))
        mismatch = L != nl[cid]
        flagged = mismatch and pe.dual_whitelisted(t, "cc_local" if ctx.unit == "cc_local" else "swechat") is None
        out.append((("read", cid), bool(flagged), {cid}))
    return out


def det_R5(ctx, v):
    meta = ctx.tally.get(v.sid)
    raw = ctx.raw.get(v.sid)
    if meta is None or not raw or raw.get("recs") is None or meta["api"] == 0:
        return []
    present = set(x for x in v.s.uuid.astype(object) if isinstance(x, str))
    ir_u = ctx.ir_uuids.get(v.sid, set())
    order, last = [], {}
    for uu, mid, tup in raw["recs"]:
        if isinstance(uu, str) and uu in ir_u and uu not in present:
            continue
        if mid not in last:
            order.append(mid)
        last[mid] = tup
    add = {k: int(round(a)) for k, a in v.usage_add.items()}
    seq = np.array([(last[m][0], last[m][1], last[m][2], last[m][3] + add.get(m, 0)) for m in order],
                   dtype=np.int64).reshape(-1, 4)
    cls = tally_match(seq, meta)["cls"]
    return [(("session",), cls == "none", {"__session__"})]


DET_FN = {"P2_KFN": det_P2, "P3_ZERO": det_P3, "N2": det_N2, "N5a": det_N5a, "N5b": det_N5b, "N5c": det_N5c,
          "N5d": det_N5d, "N5f": det_N5f, "R2_IMAGE": det_R2, "R4_DUAL": det_R4, "R5_LEDGER": det_R5}


def detector_status(unit):
    """{detector: ('RUN', note) | ('NOT_TESTABLE', reason) | ('NOT_RUN', reason)} for one unit."""
    st = {}
    p2u = PREREG_B["probe2"]["units"]
    if unit in p2.RUN_UNITS:
        st["P2_KFN"] = ("RUN", f"D_unit {p2.D_UNIT.get(unit)}" + ("; antecedents incomplete (prereg probe2)"
                                                                if unit in p2.INCOMPLETE else ""))
    else:
        st["P2_KFN"] = ("NOT_TESTABLE", p2u["not_testable"].get(unit, "not a Probe 2 unit"))
    L = PREREG_B["resolved"]["probe3"]["long_session"].get(unit)
    if L and unit != "swechat/cursor":
        st["P3_ZERO"] = ("RUN", f"L75 {L['L75']}" + ("; Algorithm-Generated code_exec pairs only" if unit == "whowhen"
                                                   else ""))
    else:
        st["P3_ZERO"] = ("NOT_TESTABLE", PREREG_B["probe3"]["units"]["dead"].get(unit, "no L75 for the unit"))
    n2r = PJ_RESOLVED["n2"].get(unit, {})
    if n2r.get("GRANULAR"):
        st["N2"] = ("RUN", f"tau {n2r.get('tau')}")
    elif unit == "aiv_cu":
        g = sorted(k for k, v in (n2r.get("by_stratum") or {}).items() if v.get("GRANULAR"))
        st["N2"] = ("RUN", "GRANULAR strata only: " + ", ".join(g))
    else:
        st["N2"] = ("NOT_TESTABLE", f"per-response usage not GRANULAR (G1 {n2r.get('G1_share_both')}, median usage_out "
                                    f"{n2r.get('G2_median_usage_out')})")
    for d in ("N5a", "N5b", "N5c", "N5d", "N5f"):
        st[d] = ("NOT_TESTABLE", "no tool results") if unit == "swechat/cursor" else ("RUN", "")
    st["R2_IMAGE"] = ("RUN", "Gemini strata") if unit == "aiv_cu" else ("NOT_TESTABLE", "no prompt IMAGE usage")
    if unit in ("swechat/claude_code", "cc_local"):
        st["R4_DUAL"] = ("RUN", "raw numLines join" + ("; E not blind" if unit.startswith("swechat") else ""))
    else:
        st["R4_DUAL"] = ("NOT_TESTABLE", "no harness structured counters (numLines) in the raw source")
    if unit == "swechat/claude_code":
        st["R5_LEDGER"] = ("RUN", "Claude-format F0 recount vs Entire tally; E not blind")
    elif unit.startswith("swechat/"):
        st["R5_LEDGER"] = ("NOT_RUN", "recount implemented for the Claude Code format (F0) only; X0/O0/G0 not "
                                      "implemented in this item")
    else:
        st["R5_LEDGER"] = ("NOT_TESTABLE", "no external usage tally")
    return st


# ====================================================================================================== unit job
def load_unit(unit, split):
    cfg = UNIT_CFG[unit]
    if cfg["corpus"] == "swechat":
        fm = pc.swechat_formats()
        ids = [s for s in pe.split_ids("swechat", split) if fm.get(str(s)) == cfg["fmt"]]
        u = pe.read_cache("swechat", split, LOAD_COLS, filters=[("session_id", "in", ids)]) if ids else \
            pd.DataFrame(columns=LOAD_COLS)
    else:
        u = pe.read_cache(cfg["corpus"], split, LOAD_COLS)
    u = u.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    return u


def session_bounds(u):
    sid = u.session_id.to_numpy(dtype=object)
    if not len(sid):
        return {}
    b = np.flatnonzero(np.r_[True, sid[1:] != sid[:-1], True])
    return {sid[b[i]]: (int(b[i]), int(b[i + 1])) for i in range(len(b) - 1)}


class DonorIndex:
    """Matched-bytes donor lookups over the unit x split pairs (pool = other REAL results, same tool_key)."""

    def __init__(self, Pall, mask, group_cols):
        self.group_cols = group_cols
        pool = Pall[mask & (Pall.bytes.to_numpy() > 0)]
        self.pool = pool
        self.arr, self.own, self.rows = {}, {}, {}
        for k, g in pool.groupby(group_cols, sort=False):
            k = k if isinstance(k, tuple) else (k,)
            o = np.argsort(g.bytes.to_numpy(), kind="stable")
            self.arr[k] = g.bytes.to_numpy()[o]
            self.rows[k] = g.iloc[o]
            for s, gs in g.groupby("session_id", sort=False):
                self.own[k + (s,)] = np.sort(gs.bytes.to_numpy())

    def exists(self, k, sid, b):
        if b <= 0 or k not in self.arr:
            return False
        tol = b // 20
        a = self.arr[k]
        n = np.searchsorted(a, b + tol, "right") - np.searchsorted(a, b - tol, "left")
        o = self.own.get(k + (sid,))
        if o is not None:
            n -= np.searchsorted(o, b + tol, "right") - np.searchsorted(o, b - tol, "left")
        return n > 0

    def pick(self, k, sid, b, rng):
        a = self.arr[k]
        tol = b // 20
        lo, hi = np.searchsorted(a, b - tol, "left"), np.searchsorted(a, b + tol, "right")
        sub = self.rows[k].iloc[lo:hi]
        return pe.pick_donor(sub, b, rng, exclude_session=sid)


def run_job(unit, split, limit=None, log=print, noop_only=False):
    t0 = time.time()
    ctx = Ctx(unit, split)
    u = load_unit(unit, split)
    bounds = session_bounds(u)
    sids_sorted = sorted(bounds)
    if limit:
        sids_sorted = sids_sorted[:limit]
        keep = set(sids_sorted)
        u = u[u.session_id.isin(keep)].reset_index(drop=True)
        bounds = session_bounds(u)
    ctx.stratum = dict(u.groupby("session_id").stratum.first().astype(object)) if len(u) else {}
    log(f"[{time.time() - t0:6.0f}s] {unit} {split}: {len(sids_sorted)} sessions, {len(u)} rows")
    status = detector_status(unit)
    run_dets = [d for d in DETECTORS if status[d][0] == "RUN"]

    # ---------------------------------------------------------------- populations
    pop = {}
    for d in run_dets:
        if d == "R2_IMAGE":
            pop[d] = {s for s in sids_sorted if str(ctx.stratum.get(s, "")).startswith("gemini")}
        elif d == "N2" and unit == "aiv_cu":
            pop[d] = {s for s in sids_sorted if ctx.stratum.get(s) in ctx.tau_by_stratum}
        elif d == "P3_ZERO" and unit == "whowhen":
            pop[d] = {s for s in sids_sorted if ctx.stratum.get(s) == "Algorithm-Generated"}
        else:
            pop[d] = set(sids_sorted)

    # ---------------------------------------------------------------- raw joins (R4 / R5)
    raw_stats = {}
    if "R4_DUAL" in run_dets or "R5_LEDGER" in run_dets:
        if unit == "cc_local":
            from analysis.loaders import load_cc_local as L
            files = {x["sid"]: x["files"] for x in L.discover()}
            for s in sids_sorted:
                if s in files:
                    ctx.raw[s] = raw_cc_local(s, files[s])
        else:
            for s in sids_sorted:
                r = raw_swechat_cc(s)
                if r is not None:
                    ctx.raw[s] = r
            ctx.tally = swechat_tallies(sids_sorted)
            for s, (a, b) in bounds.items():
                ctx.ir_uuids[s] = set(x for x in u.uuid.iloc[a:b].astype(object) if isinstance(x, str))
        raw_stats = {"sessions_with_raw": len(ctx.raw),
                     "sessions_with_numlines": sum(1 for r in ctx.raw.values() if r.get("numlines")),
                     "numlines_counters": int(sum(len(r.get("numlines") or {}) for r in ctx.raw.values())),
                     "sessions_with_tally": len(ctx.tally) if unit != "cc_local" else None,
                     "sessions_with_tally_api_gt0": (sum(1 for m in ctx.tally.values() if m["api"] > 0)
                                                     if unit != "cc_local" else None)}
        log(f"[{time.time() - t0:6.0f}s] raw joins: {raw_stats}")

    def frame(s):
        a, b = bounds[s]
        return u.iloc[a:b]

    # ---------------------------------------------------------------- honest detector outputs (whole population)
    # The same per-session pass builds the light unit-level pair table (no text) used for targets and donor lookups;
    # donor texts are read from `u` by row label when a donor is drawn (memory: the unit frame is held once).
    honest = {d: {} for d in run_dets}
    resp_cache = {}
    light = []
    for i, s in enumerate(sids_sorted):
        fr = frame(s)
        Pf = enrich_pairs(unit, pc.make_pairs(fr.assign(_ix=fr.index)))
        v = View(unit, s, fr)
        v._P = Pf
        for d in run_dets:
            if s in pop[d] and not noop_only:
                honest[d][s] = DET_FN[d](ctx, v)
        if v._resp is not None:
            resp_cache[s] = v._resp
        if len(Pf):
            L = Pf[LIGHT_COLS].copy()
            L["chash"] = [hash((a, b, c)) for a, b, c in zip(pc.sobj(Pf.tool), pc.sobj(Pf.args), pc.sobj(Pf.text_r))]
            light.append(L)
        del v, Pf
        if (i + 1) % 500 == 0:
            log(f"[{time.time() - t0:6.0f}s] honest {i + 1}/{len(sids_sorted)}")
    honest_pop = {}
    for d in run_dets:
        H = honest[d]
        n = len(H)
        dec = sum(1 for x in H.values() if x)
        fl = sum(1 for x in H.values() if any(f for _, f, _ in x))
        units_n = [len(x) for x in H.values()]
        units_k = [sum(1 for _, f, _ in x if f) for x in H.values()]
        honest_pop[d] = {"population_sessions": n, "deciding_sessions": dec, "flagged_sessions": fl,
                         "session_flag_rate_all": wil(fl, n), "session_flag_rate_deciding": wil(fl, dec),
                         "decision_units": int(sum(units_n)), "flagged_units": int(sum(units_k)),
                         "unit_flag_rate": stats.cluster_rate(units_k, units_n) if sum(units_n) else None}
        if d == "N5a":   # descriptive (not a verdict input): pairs whose n1 key contains a dataset redaction marker
            honest_pop[d]["descriptive_pairs_with_redacted_key"] = {
                "pairs": int(sum(1 for x in H.values() for uid, _, _ in x if uid[3])),
                "flagged": int(sum(1 for x in H.values() for uid, f, _ in x if uid[3] and f))}
    log(f"[{time.time() - t0:6.0f}s] honest pass done")

    # ---------------------------------------------------------------- unit-level pairs and donor indexes
    Pall = pd.concat(light, ignore_index=True) if light else pd.DataFrame(columns=LIGHT_COLS + ["chash"])
    del light
    if len(Pall):
        Pall["thread"] = [thread_key(a, b) for a, b in zip(Pall.is_subagent.astype(object), Pall.agent_id.astype(object))]
        Pall["delta_ok"] = np.isfinite(Pall.delta_s.to_numpy(dtype=float)) & (Pall.delta_s.to_numpy(dtype=float) >= 0)
        don_any = DonorIndex(Pall, np.ones(len(Pall), bool), ["key"])
        don_ok = DonorIndex(Pall, ~Pall.err.to_numpy(dtype=bool), ["key"])
        don_cmd = DonorIndex(Pall, Pall.n1.notna().to_numpy(), ["key", "n1"])
        don_rw = DonorIndex(Pall, Pall.delta_ok.to_numpy(), ["key"])
        Pall["has_any"] = [don_any.exists((k,), s, b) for k, s, b in zip(Pall.key, Pall.session_id, Pall.bytes)]
        Pall["has_ok"] = [don_ok.exists((k,), s, b) for k, s, b in zip(Pall.key, Pall.session_id, Pall.bytes)]
        Pall["has_cmd"] = [n is not None and don_cmd.exists((k, n), s, b)
                           for k, n, s, b in zip(Pall.key, Pall.n1, Pall.session_id, Pall.bytes)]
        Pall["has_rw"] = [don_rw.exists((k,), s, b) for k, s, b in zip(Pall.key, Pall.session_id, Pall.bytes)]
        gui_pool = Pall[(Pall.tool.astype(object) == "gui")] if unit == "aiv_cu" else Pall.iloc[0:0]
    P_by = {s: g for s, g in Pall.groupby("session_id", sort=False)} if len(Pall) else {}
    log(f"[{time.time() - t0:6.0f}s] pairs {len(Pall)}; donor indexes built")

    perm = list(pe.rng_for("N7", unit, split).permutation(np.array(sids_sorted, dtype=object))) if sids_sorted else []

    # ---------------------------------------------------------------- per-session target lists
    def gap_before(ix):
        """seconds between event ix and the previous event of the same session in u (donor call gap)."""
        if ix == 0 or u.session_id.iat[ix - 1] != u.session_id.iat[ix]:
            return None
        a, b = parse_ts(u.ts.iat[ix - 1]) if isinstance(u.ts.iat[ix - 1], str) else None, \
            parse_ts(u.ts.iat[ix]) if isinstance(u.ts.iat[ix], str) else None
        if a is None or b is None:
            return None
        return (b - a).total_seconds()

    def honest_resp(s):
        if s not in resp_cache:
            resp_cache[s] = pe.response_table(unit, frame(s))
        return resp_cache[s]

    def targets(attack, param, s):
        """Deterministically ordered candidate targets of `attack` in session s (empty = not eligible)."""
        f = frame(s)
        Ps = P_by.get(s)
        if attack == "sub_single_flip_error":
            return [] if Ps is None else list(Ps[Ps.err & Ps.has_ok].index)
        if attack == "sub_matched_bytes":
            col = "has_any" if param == "any" else "has_cmd"
            return [] if Ps is None else list(Ps[Ps[col]].index)
        if attack == "sub_single_digit":
            r = f[f.kind == "result"]
            return [ix for ix, t in zip(r.index, r.text.astype(object)) if isinstance(t, str) and DIGIT.search(t)]
        if attack == "reorder_lines":
            r = f[f.kind == "result"]
            out = []
            for ix, t in zip(r.index, r.text.astype(object)):
                if isinstance(t, str):
                    ls = t.split("\n")
                    if len(ls) >= 3 and any(ls[i] != ls[i + 1] for i in range(len(ls) - 1)):
                        out.append(ix)
            return out
        if attack == "rewrite_consistent_k":
            if Ps is None:
                return []
            k = int(param)
            out = []
            for _, g in Ps.sort_values("seq").groupby("thread", sort=False):
                ok = g.has_rw.to_numpy()
                ixs = list(g.index)
                for i in range(len(g) - k + 1):
                    if ok[i:i + k].all():
                        out.append(tuple(ixs[i:i + k]))
            return out
        if attack == "reorder_adjacent_pairs":
            if Ps is None:
                return []
            out = []
            for _, g in Ps.sort_values("seq").groupby("thread", sort=False):
                rows = list(zip(g.index, g.chash))
                for a, b in zip(rows, rows[1:]):
                    if a[1] != b[1]:      # (tool, args, result text) differ
                        out.append((a[0], b[0]))
            return out
        if attack == "delete_pair":
            return [] if Ps is None else list(Ps.index)
        if attack == "delete_response":
            rid = f.request_id.astype(object)
            seen, out = set(), []
            for ix, r in zip(f.index, rid):
                if isinstance(r, str) and r not in seen:
                    seen.add(r)
                    out.append(ix)
            return out
        if attack in ("insert_pair_consistent", "image_insert_screenshot", "insert_pair_squeezed"):
            if not len(Pall):
                return []
            pool = gui_pool if attack == "image_insert_screenshot" else Pall
            if not (pool.session_id != s).any():
                return []
            r = f[f.kind == "result"]
            if attack != "insert_pair_squeezed":
                return list(r.index)
            out = []
            ts = f.ts.astype(object).tolist()
            idx = list(f.index)
            pos = {ix: i for i, ix in enumerate(idx)}
            for ix in r.index:
                i = pos[ix]
                if i + 1 >= len(idx) or not isinstance(ts[i], str) or not isinstance(ts[i + 1], str):
                    continue
                a, b = parse_ts(ts[i]), parse_ts(ts[i + 1])
                if a is not None and b is not None and (b - a).total_seconds() >= 0.002:
                    out.append(ix)
            return out
        if attack == "inline_fabrication":
            tau = ctx.tau(s)
            if tau is None or Ps is None:
                return []
            R = honest_resp(s)
            if not len(R):
                return []
            rc = dict(zip(Ps.call_id.astype(str), Ps.chars))
            return [(str(r), str(c)) for r, c in zip(R.resp.astype(str), R.last_call_id.astype(str))
                    if rc.get(c, 0) >= 1]
        if attack == "image_relabel_gui":
            c = f[(f.kind == "call") & (f.tool.astype(object) == "gui")]
            return list(c.index)
        return []

    # ---------------------------------------------------------------- one tampered copy
    def tamper(attack, param, s):
        cands = targets(attack, param, s)
        if not cands:
            return None, "no_target"
        rng = pe.rng_for(attack, param, s)
        drng = pe.rng_for("donor", attack, param, s)
        t = cands[int(rng.integers(0, len(cands)))]
        f = frame(s).copy()
        # the frozen injectors call parse_ts() on stamps; pd.NA (pandas 3 string dtype) is not a valid input there,
        # so missing stamps are passed as None (same content, object dtype)
        f["ts"] = pd.Series([x if isinstance(x, str) else None for x in f.ts.astype(object)], index=f.index, dtype=object)
        meta = {"targets": {"__session__"}, "usage_add": {}, "rel": []}
        if attack in ("sub_single_flip_error", "sub_matched_bytes"):
            r = Pall.loc[t]
            if attack == "sub_single_flip_error":
                i, rel = don_ok.pick((r.key,), s, int(r.bytes), drng)
            elif param == "any":
                i, rel = don_any.pick((r.key,), s, int(r.bytes), drng)
            else:
                i, rel = don_cmd.pick((r.key, r.n1), s, int(r.bytes), drng)
            if i is None:
                return None, "no_donor"
            d = Pall.loc[i]
            de = False if attack == "sub_single_flip_error" else native_val(u.at[int(d._ix_r), "native_error"])
            s2 = pe.atk_substitute(f, int(r._ix_r), u.at[int(d._ix_r), "text"], donor_error=de)
            meta["targets"] |= {str(r.call_id)}
            meta["rel"] = [rel]
            return (s2, meta), None
        if attack == "sub_single_digit":
            s2, ok = pe.atk_digit(f, t)
            if not ok:
                return None, "inject_failed"
            meta["targets"] |= {str(f.at[t, "call_id"])}
            return (s2, meta), None
        if attack == "reorder_lines":
            s2, ok = pe.atk_reorder_lines(f, t, rng)
            if not ok:
                return None, "inject_failed"
            meta["targets"] |= {str(f.at[t, "call_id"])}
            return (s2, meta), None
        if attack == "rewrite_consistent_k":
            rows = [Pall.loc[i] for i in t]
            texts, lats, natives, rel = [], [], [], []
            for r in rows:
                i, rl = don_rw.pick((r.key,), s, int(r.bytes), drng)
                if i is None:
                    return None, "no_donor"
                d = Pall.loc[i]
                texts.append(u.at[int(d._ix_r), "text"])
                lats.append(float(d.delta_s))
                natives.append(native_val(u.at[int(d._ix_r), "native_error"]))
                rel.append(rl)
            ridx = [int(r._ix_r) for r in rows]
            s2 = pe.atk_rewrite_consistent(f, ridx, texts, lats)
            changed = sum(1 for ri, tx in zip(ridx, texts) if s2.at[ri, "text"] == tx)
            if changed < len(ridx):
                return None, "inject_failed"
            for ri, nv in zip(ridx, natives):           # DEVIATIONS: rewrite error fields
                s2.at[ri, "native_error"] = nv
                s2.at[ri, "stderr"] = None
            meta["targets"] |= {str(r.call_id) for r in rows}
            meta["rel"] = rel
            return (s2, meta), None
        if attack == "reorder_adjacent_pairs":
            a, b = t
            ra, rb = Pall.loc[a], Pall.loc[b]
            s2 = pe.atk_reorder_pairs(f, int(ra._ix), int(rb._ix))
            meta["targets"] |= {str(ra.call_id), str(rb.call_id)}
            return (s2, meta), None
        if attack == "delete_pair":
            r = Pall.loc[t]
            s2 = pe.atk_delete_pair(f, int(r._ix))
            meta["targets"] |= {str(r.call_id)}
            return (s2, meta), None
        if attack == "delete_response":
            s2 = pe.atk_delete_response(f, t)
            meta["targets"] |= set(f[f.request_id.astype(object) == f.at[t, "request_id"]].call_id.dropna().astype(str))
            return (s2, meta), None
        if attack in ("insert_pair_consistent", "insert_pair_squeezed", "image_insert_screenshot"):
            pool = gui_pool if attack == "image_insert_screenshot" else Pall
            pool = pool[pool.session_id != s]
            if not len(pool):
                return None, "no_donor"
            d = pool.iloc[int(drng.integers(0, len(pool)))]
            dc, dr = u.loc[int(d._ix)].copy(), u.loc[int(d._ix_r)].copy()
            for col in ("is_subagent", "agent_id", "parent_call_id"):     # DEVIATIONS: thread of the inserted pair
                dc[col] = f.at[t, col]
                dr[col] = f.at[t, col]
            if isinstance(dc["extra"], str) and "usage_detail" in dc["extra"]:   # DEVIATIONS: donor usage stripped
                ex = pc.jl(dc["extra"])
                ex.pop("usage_detail", None)
                dc["extra"] = json.dumps(ex, ensure_ascii=False) if ex else None
            gap = gap_before(int(d._ix))
            lat = float(d.delta_s) if np.isfinite(float(d.delta_s)) else None
            mode = "squeezed" if attack == "insert_pair_squeezed" else "consistent"
            s2 = pe.atk_insert_pair(f, t, dc, dr, mode=mode, donor_gap_s=gap if gap is not None and gap >= 0 else None,
                                    donor_lat_s=lat if lat is not None and lat >= 0 else None)
            if s2 is None:
                return None, "inject_failed"
            meta["targets"] |= {f"inserted:{d.call_id}"}
            return (s2, meta), None
        if attack == "inline_fabrication":
            resp, cid = t
            Ps = P_by[s]
            ch = int(Ps[Ps.call_id.astype(str) == cid].chars.iloc[0])
            add = pe.atk_inline_fabrication(None, ch, ctx.tau(s))
            meta["usage_add"] = {resp: add}
            meta["targets"] |= {cid, "__resp__" + resp}
            return (f, meta), None
        if attack == "image_relabel_gui":
            s2 = pe.atk_image_relabel(f, t)
            meta["targets"] |= {str(f.at[t, "call_id"])}
            return (s2, meta), None
        return None, "unknown_attack"

    # ---------------------------------------------------------------- cells
    cells = {}
    eligibility = {}
    if noop_only:
        return noop_diagnostic(unit, split, run_dets, pop, perm, targets, tamper, frame, sids_sorted, limit, t0)
    content_attacks = [(a, p) for a, p in ATTACKS if any(pe.applicable(a, d) for d in run_dets)
                       and (unit == "aiv_cu" or not a.startswith("image_"))]
    for attack, param in content_attacks:
        ta = time.time()
        dets = [d for d in run_dets if pe.applicable(attack, d)]
        elig = [s for s in perm if targets(attack, param, s)]
        eligibility[f"{attack}|{param}"] = {"eligible_sessions": len(elig), "unit_sessions": len(sids_sorted)}
        samples = {d: [s for s in elig if s in pop[d]][:pe.N7_CAP_SESSIONS] for d in dets}
        need = sorted(set().union(*samples.values())) if samples else []
        res = {d: {} for d in dets}
        fails = Counter()
        rels = []
        for s in need:
            out, why = tamper(attack, param, s)
            if out is None:
                fails[why] += 1
                continue
            s2, meta = out
            rels += [x for x in meta["rel"] if x is not None]
            v = View(unit, s, s2, usage_add=meta["usage_add"])
            for d in dets:
                if s in samples[d]:
                    res[d][s] = (DET_FN[d](ctx, v), meta["targets"])
        for d in dets:
            rows = []
            for s in samples[d]:
                if s not in res[d]:
                    continue
                tu, tg = res[d][s]
                hu = honest[d].get(s, [])
                h_flag = any(f for _, f, _ in hu)
                t_flag = any(f for _, f, _ in tu)
                if attack in NO_LOCALIZATION:
                    loc = None
                else:
                    ids = [c for _, f, c in tu if f]
                    loc = None if any(c is None for c in ids) else any((c & tg) for c in ids) if t_flag else None
                rows.append((s, h_flag, t_flag, bool(hu), bool(tu), loc))
            n = len(rows)
            k_t = sum(1 for r in rows if r[2])
            k_h = sum(1 for r in rows if r[1])
            label, _ = pe.n7_cell_label(n, k_t, n, k_h)
            adr_ind = [int(r[2] and not r[1]) for r in rows]
            locs = [r[5] for r in rows if r[2]]
            loc_known = [x for x in locs if x is not None]
            rec, fpr = wil(k_t, n), wil(k_h, n)
            cell = {"unit": unit, "split": split, "detector": d, "attack": attack, "param": param,
                    "sample_sessions": len(samples[d]), "n_tampered": n, "k_tampered_flagged": k_t,
                    "recall": rec, "n_honest": n, "k_honest_flagged": k_h, "fpr": fpr,
                    "adr": stats.cluster_rate(adr_ind, [1] * n) if n else None,
                    "localization": (None if attack in NO_LOCALIZATION or not loc_known else
                                     {"k": int(sum(loc_known)), "n": len(loc_known), "share": wil(int(sum(loc_known)),
                                                                                                  len(loc_known))}),
                    "localization_unavailable": int(sum(1 for x in locs if x is None)) if attack not in NO_LOCALIZATION
                    else None,
                    "abstain_honest": int(sum(1 for r in rows if not r[3])),
                    "abstain_tampered": int(sum(1 for r in rows if not r[4])),
                    "label": label,
                    "deciding_number": {"recall_point": rec[0], "recall_ci_lo": rec[1], "fpr_ci_hi": fpr[2],
                                        "rule": "DETECTS if recall >= 0.5 and recall CI lo > FPR CI hi; PARTIAL if "
                                                "recall CI lo > FPR CI hi; BLIND otherwise; INSUFFICIENT_N < 30"},
                    "labels": cell_labels(unit, split, d)}
            cells[f"{unit}|{split}|{d}|{attack}|{param}"] = cell
        eligibility[f"{attack}|{param}"].update({
            "tampered_sessions_attempted": len(need), "inject_failures": dict(fails),
            "donor_rel_byte_diff": stats.describe(np.array(rels, dtype=float), qs=(0.0, 0.5, 0.9, 1.0)) if rels else None,
            "seconds": round(time.time() - ta, 1)})
        log(f"[{time.time() - t0:6.0f}s] {attack}|{param}: eligible {len(elig)}, tampered {len(need)}, "
            f"fails {dict(fails)}")
    return {"unit": unit, "split": split, "sessions": len(sids_sorted), "rows": int(len(u)),
            "detector_status": {d: list(v) for d, v in status.items()},
            "populations": {d: len(pop[d]) for d in run_dets},
            "raw_joins": raw_stats, "honest_population": honest_pop, "attack_eligibility": eligibility,
            "cells": cells, "runtime_s": round(time.time() - t0, 1), "limit": limit}


NOOP_ATTACKS = [("sub_single_flip_error", "-"), ("sub_matched_bytes", "any"), ("sub_matched_bytes", "samecmd"),
                ("rewrite_consistent_k", "2"), ("rewrite_consistent_k", "5")]


def _same_text(a, b):
    a = a if isinstance(a, str) else None
    b = b if isinstance(b, str) else None
    return a == b


def noop_diagnostic(unit, split, run_dets, pop, perm, targets, tamper, frame, sids_sorted, limit, t0):
    """DESCRIPTIVE diagnostic (added after the first cell shards existed; it changes no cell): for the substitution
    attacks, replay the same seeded target and donor draws as the cells and count tampered copies in which every
    replaced result text equals the original text (a byte-identical donor makes the substitution a no-op)."""
    out = {}
    for attack, param in NOOP_ATTACKS:
        dets = [d for d in run_dets if pe.applicable(attack, d)]
        elig = [s for s in perm if targets(attack, param, s)]
        samples = {d: [s for s in elig if s in pop[d]][:pe.N7_CAP_SESSIONS] for d in dets}
        need = sorted(set().union(*samples.values())) if samples else []
        noop, partial = {}, {}
        for s in need:
            res, _ = tamper(attack, param, s)
            if res is None:
                continue
            s2, meta = res
            f = frame(s)
            r = f[(f.kind == "result") & f.call_id.astype(object).isin(list(meta["targets"]))]
            same = [_same_text(a, s2.at[ix, "text"]) for ix, a in zip(r.index, r.text.astype(object))]
            noop[s] = bool(same) and all(same)
            partial[s] = any(same)
        ent = {"tampered_sessions": len(noop), "all_replaced_texts_identical": int(sum(noop.values())),
               "some_replaced_text_identical": int(sum(partial.values())),
               "by_detector_sample": {d: {"n": int(sum(1 for s in samples[d] if s in noop)),
                                          "noop": int(sum(1 for s in samples[d] if noop.get(s)))} for d in dets}}
        ent["share_noop"] = wil(ent["all_replaced_texts_identical"], ent["tampered_sessions"])
        out[f"{attack}|{param}"] = ent
    return {"unit": unit, "split": split, "sessions": len(sids_sorted), "noop_diagnostic": out,
            "runtime_s": round(time.time() - t0, 1), "limit": limit}


def cell_labels(unit, split, d):
    lab = []
    if unit == "aiv_cc":
        lab.append("single-agent case study")
    if unit == "cc_local":
        lab.append("private (aggregates only)")
    if d in E_NOT_BLIND and split == "E":
        lab.append("E not blind")
    if d == "P2_KFN" and unit in p2.INCOMPLETE:
        lab.append("antecedents incomplete")
    if d == "P3_ZERO" and unit == "aiv_cu":
        lab.append("proxy error definition")
    if d == "P3_ZERO" and unit == "swechat/gemini":
        lab.append("union of two unvalidated-together classes")
    if unit in ("swechat/gemini", "swechat/cursor"):
        lab.append("small unit (< 30 sessions per split)")
    return lab


# ====================================================================================================== merge
def na_table():
    out = []
    for d in DETECTORS:
        for a in sorted({a for a, _ in ATTACKS}):
            if not pe.applicable(a, d):
                out.append({"detector": d, "attack": a, "attack_fields": sorted(pe.ATTACK_FIELDS[a]),
                            "detector_fields": sorted(pe.DETECTOR_FIELDS[d]), "cell": "NA_BLIND_BY_CONSTRUCTION",
                            "params": [p for aa, p in ATTACKS if aa == a]})
    return out


def merge(shard_dir, out_path, repro_dir=None):
    shards = sorted(Path(shard_dir).glob("*.json"))
    units, cells = {}, {}
    prov = []
    for p in shards:
        j = json.loads(p.read_text(encoding="utf-8"))
        r = j["result"]
        units.setdefault(r["unit"], {})[r["split"]] = {k: v for k, v in r.items() if k != "cells"}
        cells.update(r["cells"])
        prov.append({"shard": p.relative_to(ROOT).as_posix() if Path(p).resolve().is_relative_to(ROOT) else str(p),
                     "sha256": pe.sha256_file(p),
                     "script_sha256_lf": j["script_sha256_lf"], "spec_module_sha256_lf": j["spec_module_sha256_lf"],
                     "limit": r.get("limit")})
    noop = {}
    for p in sorted((Path(shard_dir) / "noop").glob("*.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        r = j["result"]
        noop.setdefault(r["unit"], {})[r["split"]] = r["noop_diagnostic"]
        prov.append({"shard": p.relative_to(ROOT).as_posix() if Path(p).resolve().is_relative_to(ROOT) else str(p),
                     "sha256": pe.sha256_file(p), "script_sha256_lf": j["script_sha256_lf"],
                     "spec_module_sha256_lf": j["spec_module_sha256_lf"], "limit": r.get("limit"),
                     "kind": "noop_diagnostic"})
    for zu in ZERO_SESSION_UNITS:
        units[zu] = {"B": {"sessions": 0, "detector_status": {d: ["NOT_TESTABLE", "0 sessions in B and E"]
                                                              for d in DETECTORS}},
                     "E": {"sessions": 0}}
    # walk-through: per attack x param, the content-detector cells by label
    walk = {}
    for a, p in ATTACKS:
        ks = [k for k, c in cells.items() if c["attack"] == a and c["param"] == p]
        lab = Counter(cells[k]["label"] for k in ks)
        walk[f"{a}|{p}"] = {"cells_computed": len(ks), "labels": dict(lab),
                            "DETECTS": sorted(k for k in ks if cells[k]["label"] == "DETECTS"),
                            "PARTIAL": sorted(k for k in ks if cells[k]["label"] == "PARTIAL"),
                            "no_DETECTS_cell_in_this_half": lab.get("DETECTS", 0) == 0,
                            "applicable_detectors_this_half": [d for d in DETECTORS if pe.applicable(a, d)]}
    # per unit x split x detector: label counts, attacks reaching DETECTS / PARTIAL, honest session flag rate
    summ = {}
    for k, c in cells.items():
        e = summ.setdefault(f"{c['unit']}|{c['split']}|{c['detector']}", {"labels": Counter(), "DETECTS": [],
                                                                          "PARTIAL": []})
        e["labels"][c["label"]] += 1
        if c["label"] in ("DETECTS", "PARTIAL"):
            e[c["label"]].append(f"{c['attack']}|{c['param']}")
    for key, e in summ.items():
        un, sp, d = key.split("|")
        hp = (units.get(un, {}).get(sp, {}).get("honest_population") or {}).get(d)
        e["labels"] = dict(e["labels"])
        e["honest_session_flag_rate_all"] = hp["session_flag_rate_all"] if hp else None
        e["honest_flagged_of_population"] = [hp["flagged_sessions"], hp["population_sessions"]] if hp else None
    proposals = proposal_inputs(units, cells)
    pj_sha = pe.sha256_file(pe.PREREG_E_JSON)
    out = {
        "item": ITEM,
        "script": "analysis/probes/phase_e_n7_content.py",
        "script_sha256_lf": sha256_lf(Path(__file__)),
        "prereg_e_json_sha256": pj_sha,
        "spec_module_sha256_lf": pe.sha256_lf(Path(pe.__file__)),
        "check_frozen": "passed",
        "prereg_section": "S:n7_attack_battery (PREREG_E.md section 4)",
        "scope": {"detectors_this_half": DETECTORS, "decision_units": DECISION_UNIT,
                  "detectors_other_half_not_computed_here": TIMING_HALF,
                  "P4_round_entropy": "NOT_RUN: no Probe 4 detector in prereg_e.json n7_attack_battery.detectors",
                  "attack_grid": [f"{a}|{p}" for a, p in ATTACKS],
                  "cell_label_rule": "n7_cell_label(): DETECTS if recall >= 0.5 and recall Wilson lo > FPR Wilson hi; "
                                     "PARTIAL if recall lo > FPR hi; BLIND otherwise; INSUFFICIENT_N below 30 tampered "
                                     "sessions",
                  "session_flag": "a session is flagged iff >= 1 of its decision units is flagged; no decided unit = "
                                  "abstain (counted as not flagged on both copies)"},
        "deviations": DEVIATIONS,
        "implementation": IMPLEMENTATION,
        "na_blind_by_construction": na_table(),
        "units": units,
        "cells": cells,
        "walkthrough": walk,
        "summary_by_unit_split_detector": summ,
        "proposal_rule_inputs": proposals,
        "diagnostics_noop_substitution": {
            "note": "DESCRIPTIVE, not a verdict input (added to the script after a first run had shown how often "
                    "matched-bytes donors are exact copies): for the substitution attacks, the share of tampered copies "
                    "whose replaced result texts are all identical to the originals (the nearest-bytes real donor had the "
                    "same text), replayed with the same seeds and samples as the cells",
            "by_unit": noop},
        "reproduction_check": repro_check(repro_dir, cells, units) if repro_dir else None,
        "verdict_cells_computed": len(cells),
        "label_counts": dict(Counter(c["label"] for c in cells.values())),
        "shards": prov,
        "script_revisions_note": "every shard records script_sha256_lf = the hash of this script when its process "
                                 "started (the code it ran). all_shards_same_script is True when every shard equals the "
                                 "script_sha256_lf above; reproduction_check compares cell shards re-run in a separate "
                                 "directory, when one is given",
        "all_shards_same_script": (len({x["script_sha256_lf"] for x in prov}) == 1
                                   and prov[0]["script_sha256_lf"] == sha256_lf(Path(__file__))) if prov else None,
    }
    Path(out_path).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=_json_default), encoding="utf-8")
    print(f"merged {len(shards)} shards, {len(cells)} cells -> {out_path}")


PROPOSAL_DETECTORS = {"R2_IMAGE": ["aiv_cu"], "R4_DUAL": ["swechat/claude_code", "cc_local"],
                      "R5_LEDGER": ["swechat/claude_code"]}


def proposal_inputs(units, cells):
    """S:a1.proposal_rules inputs for the Phase D proposals measured in this half (R2, R4, R5): the session-level
    honest flag rate on B, on E and on B u E (B and E hold disjoint sessions, so the pooled rate is a Wilson share over
    their union), and the N7 attack types reaching DETECTS / PARTIAL on E (B for units without E). The mechanical rule
    is applied for reference only; the A1 proposal items own the verdict (and add Step 0 / kill-rule context)."""
    single = set(json.loads(pe.PREREG_E_JSON.read_text(encoding="utf-8"))["n7_attack_battery"]["single_call_types"])
    out = {}
    for d, us in PROPOSAL_DETECTORS.items():
        for un in us:
            sp = units.get(un, {})
            hp = {k: (v.get("honest_population") or {}).get(d) for k, v in sp.items()}
            hp = {k: v for k, v in hp.items() if v}
            if not hp:
                continue
            k_all = sum(v["flagged_sessions"] for v in hp.values())
            n_all = sum(v["population_sessions"] for v in hp.values())
            ref = "E" if "E" in hp else "B"
            ref_cells = [c for c in cells.values() if c["unit"] == un and c["split"] == ref and c["detector"] == d]
            det_single = sorted({c["attack"] for c in ref_cells if c["label"] == "DETECTS" and c["attack"] in single})
            det_any = sorted({c["attack"] for c in ref_cells if c["label"] in ("DETECTS", "PARTIAL")})
            pooled = wil(k_all, n_all)
            rate, hi = pooled[0], pooled[2]
            if rate is not None and rate <= 0.05 and hi <= 0.10 and det_single:
                lab = "ALIVE"
            elif rate is not None and rate <= 0.20 and det_any:
                lab = "WEAK"
            else:
                lab = "DEAD"
            if d == "R2_IMAGE" and rate is not None and rate > 0.05:
                lab = "DEAD"
            out[f"{d}|{un}"] = {
                "honest_session_flag_rate": {k: {"k": v["flagged_sessions"], "n": v["population_sessions"],
                                                 "wilson": v["session_flag_rate_all"]} for k, v in hp.items()},
                "honest_session_flag_rate_B_union_E": {"k": k_all, "n": n_all, "wilson": pooled,
                                                       "splits": sorted(hp)},
                "n7_reference_split": ref,
                "single_call_or_response_types_DETECTS": det_single,
                "types_DETECTS_or_PARTIAL": det_any,
                "mechanical_label_reference_only": lab,
                "rule": "S:a1.proposal_rules: ALIVE if honest <= 0.05 with CI hi <= 0.10 and >= 1 single-call/response "
                        "type DETECTS on E (B without E); WEAK if honest <= 0.20 and >= 1 type DETECTS or PARTIAL; DEAD "
                        "otherwise; R2: honest > 0.05 -> DEAD (Phase D kill rule)",
                "labels": (["E not blind"] if d in E_NOT_BLIND and "E" in hp else [])
                          + (["B only, unreplicated"] if "E" not in hp else [])
                          + (["private (aggregates only)"] if un == "cc_local" else [])}
    return out


def repro_check(repro_dir, cells, units):
    """Cell shards of another run (e.g. the superseded first run of this script, kept outside the repo) compared with
    the merged shards: per shard, how many cells agree on every counted field and whether the honest populations agree."""
    keys = ["n_tampered", "k_tampered_flagged", "k_honest_flagged", "label", "abstain_honest", "abstain_tampered",
            "localization"]
    out = []
    for p in sorted(Path(repro_dir).glob("*.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        r = j["result"]
        if "cells" not in r:
            continue
        rc = r["cells"]
        same = sum(1 for k, c in rc.items() if k in cells and all(c[x] == cells[k][x] for x in keys))
        hp_same = r.get("honest_population") == (units.get(r["unit"], {}).get(r["split"], {}) or {}).get(
            "honest_population")
        out.append({"unit": r["unit"], "split": r["split"], "script_sha256_lf": j["script_sha256_lf"],
                    "cells_compared": len(rc), "cells_identical": same, "honest_population_identical": bool(hp_same)})
    return out


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, set):
        return sorted(o)
    if o is pd.NA:
        return None
    raise TypeError(type(o))


def slug(unit):
    return unit.replace("/", "__")


def main():
    pe.check_frozen()
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default="", help="comma list of unit:split")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--repro-dir", default=None, help="merge: compare re-run cell shards in this dir")
    ap.add_argument("--noop-diag", action="store_true", help="descriptive no-op diagnostic shards (no detector runs)")
    a = ap.parse_args()
    shard_dir = Path(a.out_dir) if a.out_dir else SHARD_DIR
    if a.limit and not a.out_dir:
        raise SystemExit("--limit is a debug option: give --out-dir outside analysis/out")
    shard_dir.mkdir(parents=True, exist_ok=True)
    if a.jobs:
        for job in a.jobs.split(","):
            unit, split = job.rsplit(":", 1)
            assert unit in UNIT_CFG and split in UNIT_CFG[unit]["splits"], job
            r = run_job(unit, split, limit=a.limit, log=lambda m: print(m, flush=True), noop_only=a.noop_diag)
            j = {"item": ITEM, "script_sha256_lf": SCRIPT_SHA_AT_START,
                 "script_sha256_lf_at_write": sha256_lf(Path(__file__)),
                 "spec_module_sha256_lf": pe.sha256_lf(Path(pe.__file__)),
                 "prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON), "result": r}
            p = (shard_dir / "noop" if a.noop_diag else shard_dir) / f"{slug(unit)}_{split}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(j, indent=1, ensure_ascii=False, default=_json_default), encoding="utf-8")
            print(f"wrote {p}", flush=True)
    if a.merge:
        merge(shard_dir, (shard_dir / "n7_content.json") if a.out_dir else OUT_JSON, repro_dir=a.repro_dir)


if __name__ == "__main__":
    main()
