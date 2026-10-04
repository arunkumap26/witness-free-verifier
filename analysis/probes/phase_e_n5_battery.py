"""Phase E, Track A, item N5 lightweight battery, items a, b, d, e, f (prereg_e.json S:n5_battery).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n5_battery

Items measured here (the other two battery items, c truncation boundary and g cold start, are not part of this item):
  a determinism      determinism_pairs(); drift = differ after mask_volatile(); also the unmasked byte-identical share.
                     Positive control: the second result's last digit edited (atk_digit = sub_single_digit) -> recall.
  b sort order       ls_order_violation / gitlog_order_violation / grepn_order_violation, per checker.
                     Positive control: atk_reorder_lines (adjacent line swap) -> recall.
  d whitespace       ws_violations(): ls_long_alignment, git_status_tab, wc_alignment, pytest_banner, per check.
                     Positive control: normalize_ws() -> recall.
  e size             IQR of log10(result bytes + 1) per command family (>= 100 results from >= 10 sessions) against the
                     IQR of model-generated text (assistant text events + subagent final results); capped at WEAK.
  f error fidelity   error_fidelity_checks(); infidelity share; coverage = checkable frames / error results.
                     Positive control: the frame's line number + 7 in the error text -> recall.
Extraction is the calibration's code path (prereg_e_calibration.cal_n5): P = pc.make_pairs(call/result rows), tool key
(cc_local private_key), n1_key, primary error flag; sort / whitespace / family checks on shell-family commands, grep_n
also on the Grep tool with -n and output_mode content.

Per unit x split (B; E where the corpus has one; B u E pooled for the artifact checks), the verdict of each item is
computed mechanically from S:n5_battery.verdict; the N6 cell is the E verdict where E exists and is not INSUFFICIENT_N,
else the B verdict ("B only"). For every item cell at WEAK or better on B or E: AC1-AC5 and the four stratification
axes on B u E (S:artifact_checks, S:stratification).

Reads: analysis/cache/<corpus>_{B,E}.parquet through prereg_e_common.read_cache (never A, never H); population metadata
(swechat_population.parquet, swe-chat-pinned sessions.parquet repo_id/user_id, aiv_cu_sessions.parquet agent_id) through
prereg_e_common helpers; raw sources for AC1 only (swe-chat-pinned transcripts, ai-village claude_code_messages.jsonl.gz),
read-only, through analysis/probes/phase_e_n1.py raw_lookup (the committed N1 AC1 reader).
Writes: analysis/out/phase_e/n5_battery.json (raw numbers only). Interpretation: analysis/notes/phase_e_n5_battery.md.
cc_local: aggregates only (no command, path, text or cluster name is written). aiv_cc: single-agent case study.
"""
import gc
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe
from analysis.probes import prereg_e_calibration as pecal  # COLS: the column set the calibration (cal_n5) read

T0 = time.time()
PJ = pe.check_frozen()
SPEC = PJ["n5_battery"]
TERC = PJ["resolved"]["length_terciles_A"]
CAL_A = json.loads((pe.OUT_E / "prereg_e_calibration.json").read_text(encoding="utf-8"))
OUT = pe.OUT_E / "n5_battery.json"
ITEMS = ("a", "b", "d", "e", "f")
ITEM_NAME = {"a": "a_determinism", "b": "b_sort_order", "d": "d_whitespace", "e": "e_size_distribution",
             "f": "f_error_fidelity"}
N6_ROW = {"a": "N5a_determinism", "b": "N5b_sort", "d": "N5d_whitespace", "e": "N5e_size", "f": "N5f_error_fidelity"}
CHECKERS = {"b": ("ls", "git_log", "grep_n"), "d": ("ls_long_alignment", "git_status_tab", "wc_alignment", "pytest_banner")}

# ---- verdict thresholds: S:n5_battery.*.verdict and min_n (judgment calls fixed at pre-registration, PREREG_E section 9)
MIN = {"a": (100, 20), "b": (100, 20), "d": (100, 20), "f": (100, 20)}   # (events, sessions)
TH = {"a": {"alive_pt": 0.05, "alive_hi": 0.10, "weak_pt": 0.20},
      "b": {"alive_pt": 0.01, "alive_hi": 0.03, "weak_pt": 0.05},
      "d": {"alive_pt": 0.01, "alive_hi": 0.03, "weak_pt": 0.05},
      "f": {"alive_pt": 0.02, "alive_hi": 0.05, "weak_pt": 0.10}}
E_FAM_MIN = (100, 10)        # S:n5_battery.e_size_distribution.families
E_SHARE = 0.5                # >= 0.5 of families above the comparator's CI hi -> WEAK
E_COMP_MIN = (30, 5)         # comparator quantiles: prereg.json global.min_n p50 rule (deviation logged)
PY_FRAME, RUST_FRAME = pe._R["py_frame"], pe._R["rust_frame"]

UNITS = ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "swechat/cursor",
         "swechat/copilot", "swechat/simple_text", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
CORPUS_OF = {u: ("swechat" if u.startswith("swechat/") else u) for u in UNITS}
LABELS = {"cc_local": ["private: aggregates only", "B only, unreplicated (no E split)"],
          "aiv_cc": ["single-agent case study", "B only, unreplicated (no E split)"],
          "whowhen": ["B only, unreplicated (no E split)"]}
CHUNK = 250
FAST_IQR = True   # iqr_boot_fast == boot_stat(IQR) exactly (checked by --selftest)
OPENED = []
BOOL_COLS = ("drift", "identical", "pc_tamperable", "pc_flag", "pc_eligible", "join_clean", "trunc", "err_any",
             "redaction_in_key", "violation", "cmd_mentions_pytest", "faithful", "unfaithful")
EMPTY_COLS = {"a": ["session_id", "seq_a", "seq_b", "key", "drift", "identical", "pc_tamperable", "pc_flag", "join_clean",
                    "trunc", "err_any", "redaction_in_key"],
              "b": ["session_id", "call_id", "seq", "checker", "via", "key", "violation", "pc_tamperable", "pc_eligible",
                    "pc_flag", "trunc", "join_clean", "alt_colon_only"],
              "d": ["session_id", "call_id", "seq", "checker", "key", "violation", "pc_eligible", "pc_flag", "trunc",
                    "join_clean", "cmd_mentions_pytest"],
              "e": ["session_id", "call_id", "seq", "family", "bytes", "log_b", "key", "trunc", "join_clean"],
              "e_comp": ["session_id", "source", "bytes", "log_b"],
              "f": ["session_id", "seq", "call_id", "line", "faithful", "unfaithful", "pc_eligible", "pc_flag", "trunc",
                    "join_clean", "key"]}
LVL = {"ALIVE": 2, "WEAK": 1, "DEAD": 0}

# ================================================================================================== deviations / choices
DEVIATIONS = [
    {"item": "output file names",
     "prereg_said": "prereg_e.json outputs 'N1-N5': phase_e_n<k>.py -> n<k>.json",
     "what_you_did": "analysis/probes/phase_e_n5_battery.py -> analysis/out/phase_e/n5_battery.json (the orchestrator's "
                     "item key n5_battery); this file covers battery items a, b, d, e, f only",
     "why": "the battery was split across agents (c and g are not in this item); a distinct name avoids two agents "
            "writing n5.json", "effect_on_verdict": "none"},
    {"item": "item cell for multi-checker items (b sort order, d whitespace)",
     "prereg_said": "statistic and verdict per checker (b) / per check (d); N6 has one row per item (N5b_sort, "
                    "N5d_whitespace); no rule combines the checkers",
     "what_you_did": "each checker gets its own verdict, N6 cell (E where testable, else B) and artifact checks; the "
                     "item cell is the LOWEST cell label among checkers whose cell is ALIVE/WEAK/DEAD (INSUFFICIENT_N "
                     "if none); every checker's label is stored next to it",
     "why": "smallest faithful combination that cannot raise a label (PREREG_E 1.1 'no rescue'); taking the best "
            "checker would be a post-hoc selection", "effect_on_verdict": "the item cell can only be lower than its "
                                                                        "best checker; see cells.*.per_checker"},
    {"item": "zero-numerator CI for the verdict",
     "prereg_said": "global.ci_methods: zero numerators report the per-event and per-session Wilson upper bounds; "
                    "verdicts use the per-event Wilson upper bound",
     "what_you_did": "when the numerator is 0 the CI hi used by the ALIVE rule is wilson_hi_per_event (the session "
                     "bootstrap gives hi = 0); the bootstrap CI is still stored",
     "why": "as written", "effect_on_verdict": "applied wherever num = 0 (see verdict.deciding_number)"},
    {"item": "e: log of zero-byte texts",
     "prereg_said": "IQR of log10(result bytes) per family; comparator IQR of log10 bytes of model-generated text",
     "what_you_did": "log10(bytes + 1) on both sides (the N1 convention, S:n1 'log10(bytes + 1)'); zero-byte results "
                     "and empty assistant text events are kept on both sides",
     "why": "log10(0) is undefined and empty results are real outcomes (e.g. a grep with no match)",
     "effect_on_verdict": "none expected: the +1 changes log values only below ~10 bytes; counts of zero-byte texts "
                          "are reported per family and for the comparator"},
    {"item": "e: comparator CI and minimum n",
     "prereg_said": "WEAK if >= 0.5 of families have IQR above the comparator's CI hi; no comparator minimum stated",
     "what_you_did": "comparator IQR CI = session bootstrap (boot_stat, seed 20261003, >= 900 valid draws); the "
                     "comparator needs >= 30 texts from >= 5 sessions (prereg.json global.min_n p50 rule, the closest "
                     "quantile rule) else the cell is INCONCLUSIVE; 'above' = family IQR point > comparator CI hi; "
                     "0 qualifying families -> INSUFFICIENT_N",
     "why": "the rule needs a comparator CI; global min-n rules are the pre-registered minimum for quantiles",
     "effect_on_verdict": "none unless a comparator falls below 30 texts / 5 sessions (listed per cell)"},
    {"item": "e: model-generated text",
     "prereg_said": "assistant text events and subagent final results",
     "what_you_did": "every IR event with kind 'assistant' and a string text (thinking is not in the IR text), plus the "
                     "result text of every paired call whose tool key is 'subagent'",
     "why": "IR definitions (lib/ir.py kind 'assistant' = model-generated text blocks)", "effect_on_verdict": "none"},
    {"item": "positive controls: seeds and abstention",
     "prereg_said": "outputs.seeds: positive controls rng_for('<item>pc', session_id, key)",
     "what_you_did": "b: rng_for('N5bpc', session_id, call_id, checker) drives atk_reorder_lines (the frozen injector, "
                     "applied to a one-row copy of the result); a: atk_digit on the second result (deterministic); d: "
                     "normalize_ws (deterministic); f: the frame's line number + 7 in the error text (deterministic). "
                     "A control that cannot be applied (no digit, < 3 lines, check no longer eligible after the edit, "
                     "line + 7 not shown) abstains and counts as NOT flagged, as in N7. Recall is reported over all "
                     "eligible events and over honest-non-flagged events",
     "why": "'key' is read as the decision unit's id; abstention follows the N7 convention",
     "effect_on_verdict": "none: positive-control recall is reported, it is not a verdict input in S:n5_battery"},
    {"item": "f: positive-control implementation",
     "prereg_said": "line number shifted by +7 in the error text -> recall",
     "what_you_did": "for each checkable frame the first py_frame / rust_frame match in that error result whose (path "
                     "key, line) equals the frame gets line + 7 written into its line-number group (rust: both the "
                     "--> line and the gutter number), then error_fidelity_checks() is re-run on the session; flagged "
                     "if the frame at (seq, path, line + 7) is checkable and unfaithful",
     "why": "no frozen injector exists for this control", "effect_on_verdict": "none (control only)"},
    {"item": "f: pre-filter",
     "prereg_said": "error_fidelity_checks() over the session",
     "what_you_did": "error_fidelity_checks() is called only for sessions where some error result carries a py_frame or "
                     "rust_frame match (it returns no frame otherwise, by construction); coverage's denominator (error "
                     "results) is counted on every session",
     "why": "runtime; identical output", "effect_on_verdict": "none"},
    {"item": "field gate (NOT_TESTABLE)",
     "prereg_said": "N6 fill rule: NOT_TESTABLE iff a required field is absent (N5a/b/d: result text + commands; N5e: "
                    "result text; N5f: error results + earlier Read results with line numbers)",
     "what_you_did": "checked on B (and E) per unit: 'commands' = >= 1 shell-family call with a command string; "
                     "'results' = >= 1 paired result; for N5e the family rule needs shell commands too (families are "
                     "first programs of shell commands); for N5f 'numbered Read results' = >= 1 read-tool result with "
                     "a read_numbered_line match. Units with 0 sessions in B and E (swechat/copilot, simple_text) are "
                     "NOT_TESTABLE(no sessions in B or E)",
     "why": "the A field gate (resolved.n6_field_gate_A) has no N5-specific field", "effect_on_verdict":
         "NOT_TESTABLE instead of INSUFFICIENT_N where the field is absent"},
    {"item": "AC3 'call_id not present in another session'",
     "prereg_said": "join_clean_mask(): call_id not present in another session",
     "what_you_did": "copied ids computed over the corpus's B and E caches (B only for cc_local, aiv_cc, whowhen), as N1",
     "why": "the population event table is not loaded", "effect_on_verdict": "none expected"},
    {"item": "AC1 numerator and diagnostic",
     "prereg_said": "audit_sample() draws 30 numerator (or flagged) events with SEED_E; FAIL at >= 2 of 30 differing",
     "what_you_did": "numerator = drifting pairs (a), violating outputs (b, d), unfaithful frames (f); fewer than 30 -> "
                     "all; seed_parts ('N5', item, checker, 'AC1', 'numerator', unit). A second sample of 30 "
                     "denominator events is a diagnostic only. Compared with the raw source: result text (exact), "
                     "result bytes, command string (normalised) and, for f, the error flag. AC1 FAIL = one-level "
                     "downgrade. Raw readers exist for the Claude Code formats (swechat/claude_code transcripts, aiv_cc "
                     "gz) only; other units: AC1 NOT_RUN with the reason",
     "why": "the prereg does not name N5's numerator or AC1's label effect; raw parsers for codex/opencode/gemini/aiv_cu "
            "/cc_local are not committed", "effect_on_verdict": "listed per cell"},
    {"item": "AC4 / strata / AC5 details",
     "prereg_said": "S:artifact_checks AC4, AC5; S:stratification",
     "what_you_did": "AC4 denominator events = the item's decision units per session (pairs, outputs, frames; for e the "
                     "family results); leave-outs recompute the item's statistic and verdict on every session outside "
                     "the left-out cluster; aiv_cc one-agent kinds are labelled only (as N1). AC5: weighted_cluster_rate "
                     "with post_strat_weights over the contributing sessions (for e: weighted quantiles with the same "
                     "weights and a weighted session bootstrap). Strata: tool_key = the decision unit's tool key (for b "
                     "also shell vs Grep tool), model, repo, length tercile of paired calls (A cuts); e has a single "
                     "tool class (shell families) so its tool_key axis is UNTESTABLE",
     "why": "smallest faithful reading, matching phase_e_n1.py", "effect_on_verdict": "listed per cell"},
]


# ================================================================================================== loading
def unit_chunks():
    """Yields (corpus, unit, split, frame, n_sessions_in_split, chunk_index). One chunk of <= CHUNK sessions at a time."""
    fm = pc.swechat_formats()
    OPENED.append("analysis/cache/swechat_population.parquet (format column)")
    for split in ("B", "E"):
        OPENED.append(f"analysis/cache/swechat_{split}.parquet")
        sids = sorted(pe.read_cache("swechat", split, ["session_id"]).session_id.unique())
        by = defaultdict(list)
        for s in sids:
            by[fm.get(s, "?")].append(s)
        for f in ("claude_code", "codex", "opencode", "gemini", "cursor", "copilot", "simple_text"):
            ids = by.get(f, [])
            unit = f"swechat/{f}"
            if not ids:
                yield "swechat", unit, split, None, 0, 0
                continue
            for ci in range(0, len(ids), CHUNK):
                df = pe.read_cache("swechat", split, pecal.COLS, filters=[("session_id", "in", ids[ci:ci + CHUNK])])
                yield "swechat", unit, split, df, len(ids), ci // CHUNK
    for c in ("cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        for split in (("B", "E") if c in pe.CORPORA_WITH_E else ("B",)):
            OPENED.append(f"analysis/cache/{c}_{split}.parquet")
            sids = sorted(pe.read_cache(c, split, ["session_id"]).session_id.unique())
            for ci in range(0, len(sids), CHUNK):
                df = pe.read_cache(c, split, pecal.COLS, filters=[("session_id", "in", sids[ci:ci + CHUNK])])
                yield c, c, split, df, len(sids), ci // CHUNK


def copied_call_ids(corpus):
    """call_ids that occur in more than one session across the corpus's B and E caches (AC3), as phase_e_n1.py."""
    parts = []
    for split in (("B", "E") if corpus in pe.CORPORA_WITH_E else ("B",)):
        d = pe.read_cache(corpus, split, ["session_id", "kind", "call_id"], filters=[("kind", "==", "call")])
        parts.append(d[d.call_id.notna()][["session_id", "call_id"]].drop_duplicates())
    d = pd.concat(parts, ignore_index=True)
    n = d.groupby("call_id").session_id.nunique()
    return frozenset(str(x) for x in n[n > 1].index)


# ================================================================================================== extraction
def shellish(k):
    return k == "shell" or k in pc.CODEX_SHELL_RAW or str(k).endswith("__bash")


def family_of(sc):
    """cal_n5 family rule: first program; git -> 'git <subcommand>'."""
    progs = pe.command_programs(sc)
    if not progs:
        return None
    f = progs[0][0]
    if f == "git":
        m = re.search(r"\bgit\s+(?:-C\s+\S+\s+|--no-pager\s+)*([a-z\-]+)", progs[0][1])
        f = "git " + (m.group(1) if m else "?")
    return f


def _frame_shift(text, pk, ln, add=7):
    """Positive control for f: write line + add into the first py/rust frame of `text` whose (path key, line) is
    (pk, ln); for a rustc frame the gutter number (a backreference in the frozen regex) is rewritten too.
    Returns the edited text or None."""
    for rx in (PY_FRAME, RUST_FRAME):
        for m in rx.finditer(text):
            k = pc.path_key(pc.normalize_path(m.group("path")) or "")
            if k != pk or int(m.group("line")) != ln:
                continue
            a, b = m.span("line")
            new = text[:a] + str(ln + add) + text[b:]
            if rx is RUST_FRAME:
                e = m.end() + (len(str(ln + add)) - (b - a))
                seg = new[a:e]
                seg2 = re.sub(r"(\n\s*)" + str(ln) + r"(\s*\|)", lambda mm: mm.group(1) + str(ln + add) + mm.group(2),
                              seg, count=1)
                new = new[:a] + seg2 + new[e:]
            return new
    return None


_GREP_COLON_ONLY = re.compile(r"^(?:(?P<path>[^\n:]+):)?(?P<line>\d+):")


def grepn_colon_only(text):
    """POST HOC diagnostic only (not a verdict): grepn_order_violation's loop with a match-line regex whose path is
    delimited by ':' only (context lines skipped), to size how many frozen-checker violations come from hyphenated
    file names such as step-04-x.md, which the frozen lazy path group splits at '-04-'."""
    prev_path, prev_line, n = None, None, 0
    for line in (text if isinstance(text, str) else "").splitlines():
        m = _GREP_COLON_ONLY.match(line)
        if not m:
            continue
        n += 1
        pth, ln = m.group("path"), int(m.group("line"))
        if pth == prev_path and prev_line is not None and ln <= prev_line:
            return True
        prev_path, prev_line = pth, ln
    return False if n >= 3 else None


def extract(unit, split, u, copied):
    """One chunk of one unit x split -> record frames (no text kept except what AC1 needs: ids and seqs)."""
    u = u.reset_index(drop=True)
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    model = pe.session_model_map(u)
    if not len(P):
        ps = pd.DataFrame({"session_id": sorted(u.session_id.unique())})
        ps["pairs"], ps["err_results"], ps["numbered_reads"] = 0, 0, 0
        gate = {"pairs": 0, "results_with_text": 0, "shell_calls_with_command": 0, "read_results": 0,
                "grep_tool_results": 0, "numbered_read_results": 0, "error_results": 0, "truncated_results": 0,
                "join_unclean_pairs": 0}
        return {k: pd.DataFrame() for k in ("a", "b", "d", "e", "e_comp", "f")}, ps, gate, model
    P["key"] = [pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    if unit == "cc_local":
        P["key"] = [pc.private_key(k) for k in P.key]
    P["n1"] = [pe.n1_key(unit, k, a, c) for k, a, c in zip(P.key, P.args.astype(object), P.command.astype(object))]
    P["err"] = [bool(pc.error_classes(unit, k, tr, t, e, n, x, st)[0]) for k, tr, t, e, n, x, st in
                zip(P.key, P.tool_raw.astype(object), P.text_r.astype(object), P.stderr_r.astype(object),
                    P.native_error_r.astype(object), P.exit_code_r.astype(object), P.stratum.astype(object))]
    P["join_clean"] = pe.join_clean_mask(u, P, copied) if len(P) else np.zeros(0, dtype=bool)
    P["trunc"] = [pe.truncated_result(t, x) for t, x in zip(P.text_r.astype(object), P.extra_r.astype(object))]
    P["call_id"] = P.call_id.astype(str)
    rec = {}
    by_seq = {(s, int(q)): i for i, (s, q) in enumerate(zip(P.session_id, P.seq))}
    # ---------------------------------------------------------------- a determinism
    rows = []
    for sid, qa, qb, nk, ti, tj in pe.determinism_pairs(unit, u, P):
        ia, ib = by_seq[(sid, qa)], by_seq[(sid, qb)]
        mi, mj = pe.mask_volatile(ti), pe.mask_volatile(tj)
        drift = mi != mj
        s2, ok = pe.atk_digit(pd.DataFrame({"text": [tj]}, dtype=object), 0)
        pcf = bool(ok and pe.mask_volatile(s2.at[0, "text"]) != mi)
        rows.append({"session_id": sid, "seq_a": qa, "seq_b": qb, "call_id_a": P.call_id.iat[ia],
                     "call_id_b": P.call_id.iat[ib], "key": P.key.iat[ia], "n1": nk if unit != "cc_local" else None,
                     "drift": bool(drift), "identical": bool(ti == tj), "pc_tamperable": bool(ok), "pc_flag": pcf,
                     "join_clean": bool(P.join_clean.iat[ia] and P.join_clean.iat[ib]),
                     "trunc": bool(P.trunc.iat[ia] or P.trunc.iat[ib]), "bytes_b": len(tj.encode("utf-8")),
                     "err_any": bool(P.err.iat[ia] or P.err.iat[ib]), "redaction_in_key": "<R>" in str(nk)})
    rec["a"] = pd.DataFrame(rows)
    # ---------------------------------------------------------------- b, d, e on every paired result
    brow, drow, erow = [], [], []
    shell_calls_with_cmd = 0
    for i, (sid, cid, q, k, a, cmd, t, tr, jc) in enumerate(zip(
            P.session_id, P.call_id, P.seq, P.key, P.args.astype(object), P.command.astype(object),
            P.text_r.astype(object), P.trunc, P.join_clean)):
        sc = pc.shell_command(unit, k, pc.jl(a) if isinstance(a, str) else {}, cmd) if shellish(k) else None
        if sc:
            shell_calls_with_cmd += 1
            for name, fn in (("ls", pe.ls_order_violation), ("git_log", pe.gitlog_order_violation),
                             ("grep_n", pe.grepn_order_violation)):
                v = fn(sc, t)
                if v is None:
                    continue
                s2, ok = pe.atk_reorder_lines(pd.DataFrame({"text": [t]}, dtype=object), 0,
                                              pe.rng_for("N5bpc", sid, cid, name))
                pv = fn(sc, s2.at[0, "text"]) if ok else None
                brow.append({"session_id": sid, "call_id": cid, "seq": int(q), "checker": name, "via": "shell",
                             "key": k, "violation": bool(v), "pc_tamperable": bool(ok), "pc_eligible": pv is not None,
                             "pc_flag": bool(pv), "trunc": bool(tr), "join_clean": bool(jc),
                             "alt_colon_only": (grepn_colon_only(t) if name == "grep_n" else None)})
            wv = pe.ws_violations(sc, t)
            if wv:
                wn = pe.ws_violations(sc, pe.normalize_ws(t))
                for name, v in wv.items():
                    drow.append({"session_id": sid, "call_id": cid, "seq": int(q), "checker": name, "key": k,
                                 "violation": bool(v), "pc_eligible": name in wn, "pc_flag": bool(wn.get(name, False)),
                                 "trunc": bool(tr), "join_clean": bool(jc),
                                 "cmd_mentions_pytest": bool(re.search(r"\bpy\.?test\b", sc))})
            fam = family_of(sc)
            if fam is not None:
                b = len(t.encode("utf-8")) if isinstance(t, str) else 0
                erow.append({"session_id": sid, "call_id": cid, "seq": int(q), "family": fam, "bytes": b,
                             "log_b": math.log10(b + 1), "key": k, "trunc": bool(tr), "join_clean": bool(jc)})
        if k == "grep":
            v = pe.grepn_order_violation(a, t, is_grep_tool=True)
            if v is not None:
                s2, ok = pe.atk_reorder_lines(pd.DataFrame({"text": [t]}, dtype=object), 0,
                                              pe.rng_for("N5bpc", sid, cid, "grep_n"))
                pv = pe.grepn_order_violation(a, s2.at[0, "text"], is_grep_tool=True) if ok else None
                brow.append({"session_id": sid, "call_id": cid, "seq": int(q), "checker": "grep_n", "via": "grep_tool",
                             "key": k, "violation": bool(v), "pc_tamperable": bool(ok), "pc_eligible": pv is not None,
                             "pc_flag": bool(pv), "trunc": bool(tr), "join_clean": bool(jc),
                             "alt_colon_only": grepn_colon_only(t)})
    rec["b"] = pd.DataFrame(brow)
    rec["d"] = pd.DataFrame(drow)
    rec["e"] = pd.DataFrame(erow)
    # comparator: assistant text events + subagent final results
    crow = []
    asst = u[(u.kind == "assistant")]
    for sid, t in zip(asst.session_id, asst.text.astype(object)):
        if isinstance(t, str):
            b = len(t.encode("utf-8"))
            crow.append({"session_id": sid, "source": "assistant_text", "bytes": b, "log_b": math.log10(b + 1)})
    sub = P[P.key == "subagent"]
    for sid, t in zip(sub.session_id, sub.text_r.astype(object)):
        if isinstance(t, str):
            b = len(t.encode("utf-8"))
            crow.append({"session_id": sid, "source": "subagent_result", "bytes": b, "log_b": math.log10(b + 1)})
    rec["e_comp"] = pd.DataFrame(crow)
    # ---------------------------------------------------------------- f error fidelity
    frow = []
    hit = {s for s, e, t in zip(P.session_id, P.err, P.text_r.astype(object))
           if e and isinstance(t, str) and (PY_FRAME.search(t) or RUST_FRAME.search(t))}
    for sid in sorted(hit):
        Ps = P[P.session_id == sid]
        us = u[u.session_id == sid]
        frames = pe.error_fidelity_checks(unit, us, Ps)
        for (s_, q, pk, ln, faithful) in frames:
            j = Ps.index[Ps.seq == q][0]
            txt = Ps.at[j, "text_r"]
            new = _frame_shift(txt, pk, ln) if isinstance(txt, str) else None
            pcf, pce = False, False
            if new is not None:
                P2 = Ps.copy()
                P2.at[j, "text_r"] = new
                f2 = [x for x in pe.error_fidelity_checks(unit, us, P2) if x[1] == q and x[2] == pk and x[3] == ln + 7]
                pce = bool(f2)
                pcf = bool(f2 and not f2[0][4])
            frow.append({"session_id": sid, "seq": int(q), "call_id": Ps.at[j, "call_id"], "line": int(ln),
                         "faithful": bool(faithful), "unfaithful": not faithful, "pc_eligible": pce, "pc_flag": pcf,
                         "trunc": bool(Ps.at[j, "trunc"]), "join_clean": bool(Ps.at[j, "join_clean"]),
                         "key": Ps.at[j, "key"]})
    rec["f"] = pd.DataFrame(frow)
    # ---------------------------------------------------------------- per-session counts (coverage, strata, gates)
    ps = P.groupby("session_id").agg(pairs=("seq", "size"), err_results=("err", "sum"))
    ps = ps.reindex(sorted(u.session_id.unique()), fill_value=0).rename_axis("session_id").reset_index()
    reads = P[(P.key == "read")]
    nr = Counter(s for s, t in zip(reads.session_id, reads.text_r.astype(object))
                 if isinstance(t, str) and pe._R["read_numbered_line"].search(t))
    ps["numbered_reads"] = [nr.get(s, 0) for s in ps.session_id]
    gate = {"pairs": int(len(P)), "results_with_text": int(sum(isinstance(t, str) for t in P.text_r.astype(object))),
            "shell_calls_with_command": int(shell_calls_with_cmd), "read_results": int(len(reads)),
            "grep_tool_results": int((P.key == "grep").sum()), "numbered_read_results": int(sum(nr.values())),
            "error_results": int(P.err.sum()), "truncated_results": int(P.trunc.sum()),
            "join_unclean_pairs": int((~P.join_clean).sum())}
    return rec, ps, gate, model


# ================================================================================================== statistics
def zrate(flags, sids):
    """cluster_rate of a boolean decision-unit flag; zero numerators carry the Wilson upper bounds (global rule)."""
    if len(flags) == 0:
        return {"rate": None, "num": 0, "den": 0, "n_sessions": 0}
    return pe.rate_by_session(np.asarray(flags, dtype=bool), np.asarray(sids))


def hi_for_verdict(r):
    if r.get("rate") is None:
        return None
    if r.get("num", 0) == 0 and "wilson_hi_per_event" in r:
        return r["wilson_hi_per_event"]
    return r.get("hi")


def rate_verdict(item, r, path):
    n, ns = int(r.get("den", 0) or 0), int(r.get("n_sessions", 0) or 0)
    mn, ms = MIN[item]
    if n < mn or ns < ms:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {mn} decision units from >= {ms} sessions",
                "deciding_number": {"n": n, "sessions": ns}, "deciding_path": [f"{path}.den", f"{path}.n_sessions"]}
    th = TH[item]
    pt, hi = r["rate"], hi_for_verdict(r)
    hi_path = f"{path}.wilson_hi_per_event" if (r.get("num", 0) == 0 and "wilson_hi_per_event" in r) else f"{path}.hi"
    if pt <= th["alive_pt"] and hi is not None and hi <= th["alive_hi"]:
        return {"label": "ALIVE", "rule": f"rate <= {th['alive_pt']} with CI hi <= {th['alive_hi']}",
                "deciding_number": {"rate": pt, "ci_hi": hi}, "deciding_path": [f"{path}.rate", hi_path]}
    if pt <= th["weak_pt"]:
        why = "CI hi" if pt <= th["alive_pt"] else "rate"
        return {"label": "WEAK", "rule": f"rate <= {th['weak_pt']} (ALIVE fails on {why})",
                "deciding_number": {"rate": pt, "ci_hi": hi}, "deciding_path": [f"{path}.rate", hi_path]}
    return {"label": "DEAD", "rule": f"rate > {th['weak_pt']}", "deciding_number": pt, "deciding_path": f"{path}.rate"}


def stat_rate_item(item, df, path, flag="violation", w=None):
    """One rate item (a: drift, b/d per checker: violation, f: unfaithful) on one population."""
    if not len(df):
        r = {"rate": None, "num": 0, "den": 0, "n_sessions": 0}
    elif w is None:
        r = zrate(df[flag].to_numpy(), df.session_id.to_numpy())
    else:
        g = df.groupby("session_id")[flag].agg(["sum", "size"])
        r = pe.weighted_cluster_rate(g["sum"].to_numpy(), g["size"].to_numpy(), [w.get(s, 0.0) for s in g.index])
        r["num"], r["den"], r["n_sessions"] = float(g["sum"].sum()), float(g["size"].sum()), int(len(g))
        if r["num"] == 0:
            r["wilson_hi_per_event"] = stats.wilson(0, int(r["den"]))[2]
            r["wilson_hi_per_session"] = stats.wilson(0, int(r["n_sessions"]))[2]
    return r


def pc_block(df, flag):
    """Positive-control recall: over all eligible decision units, and over honest-non-flagged ones."""
    if not len(df):
        return {"n": 0}
    out = {"n": int(len(df)), "sessions": int(df.session_id.nunique()),
           "recall_all": zrate(df.pc_flag.to_numpy(), df.session_id.to_numpy())}
    if "pc_tamperable" in df:
        out["abstain_not_tamperable"] = int((~df.pc_tamperable).sum())
    if "pc_eligible" in df:
        out["abstain_not_eligible_after_edit"] = int((~df.pc_eligible).sum())
    h = df[~df[flag].astype(bool)]
    out["recall_on_honest_clean"] = zrate(h.pc_flag.to_numpy(), h.session_id.to_numpy()) if len(h) else {"n": 0}
    return out


def iqr(v):
    v = np.asarray(v, float)
    if len(v) == 0:
        return None
    return float(np.quantile(v, 0.75) - np.quantile(v, 0.25))


def wquantile(v, w, q):
    o = np.argsort(v, kind="mergesort")
    v, w = v[o], w[o]
    c = np.cumsum(w) - 0.5 * w
    c = c / w.sum()
    return float(np.interp(q, c, v))


def _expanded_quantile(v_sorted, cw, q):
    """np.quantile(..., 'linear') of the multiset in which sorted value v_sorted[i] occurs (cw[i] - cw[i-1]) times."""
    m = int(cw[-1])
    h = (m - 1) * q
    k0 = int(math.floor(h))
    k1 = min(k0 + 1, m - 1)
    i0 = int(np.searchsorted(cw, k0, side="right"))
    i1 = int(np.searchsorted(cw, k1, side="right"))
    return float(v_sorted[i0] + (h - k0) * (v_sorted[i1] - v_sorted[i0]))


def iqr_boot_fast(vals, sids):
    """Exactly prereg_e_common.boot_stat(groups, IQR of the concatenation): same groups (sessions in groupby order), same
    seeded draws (rng.integers(0, n, size=n) per draw, seed 20261003, 1,000 draws), same statistic (np.quantile linear
    on the concatenated draw), computed from per-session multiplicities instead of concatenating arrays."""
    df = pd.DataFrame({"v": np.asarray(vals, float), "s": np.asarray(sids)})
    codes, uniq = pd.factorize(df.s, sort=True)       # groupby('s') order = sorted session ids
    n = len(uniq)
    o = np.argsort(df.v.to_numpy(), kind="mergesort")
    v_sorted = df.v.to_numpy()[o]
    g_sorted = codes[o]
    val = iqr(df.v.to_numpy()) if len(df) else None
    out = {"value": val, "n_sessions": int(n), "valid_draws": 0, "ci_reported": False}
    if n >= 2:
        rng = np.random.default_rng(pe.SEED)
        draws = []
        for _ in range(stats.N_BOOT):
            pick = rng.integers(0, n, size=n)
            cnt = np.bincount(pick, minlength=n)
            cw = np.cumsum(cnt[g_sorted])
            if cw[-1] == 0:
                continue
            draws.append(_expanded_quantile(v_sorted, cw, 0.75) - _expanded_quantile(v_sorted, cw, 0.25))
        out["valid_draws"] = len(draws)
        out["ci_reported"] = len(draws) >= 900
        if out["ci_reported"]:
            out["lo"], out["hi"] = float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))
    return out


def iqr_boot(vals, sids, w=None):
    """IQR with a session-bootstrap CI (boot_stat; weighted quantiles when w is given)."""
    df = pd.DataFrame({"v": vals, "s": sids})
    if w is None and FAST_IQR:
        b = iqr_boot_fast(vals, sids)
        b["n"] = int(len(df))
        return b
    if w is None:
        groups = [g.v.to_numpy(float) for _, g in df.groupby("s")]

        def fn(gs):
            if not gs:
                return None
            x = np.concatenate(gs)
            return iqr(x) if len(x) else None
    else:
        groups = [(g.v.to_numpy(float), np.full(len(g), w.get(s, 0.0))) for s, g in df.groupby("s")]

        def fn(gs):
            if not gs:
                return None
            x = np.concatenate([a for a, _ in gs])
            ww = np.concatenate([b for _, b in gs])
            ok = ww > 0
            if ok.sum() < 2:
                return None
            return wquantile(x[ok], ww[ok], 0.75) - wquantile(x[ok], ww[ok], 0.25)
    b = pe.boot_stat(groups, fn)
    b["n"] = int(len(df))
    return b


def qt(v):
    v = np.asarray(v, float)
    out = {"n": int(len(v))}
    if len(v):
        for q in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0):
            out[f"q{q:g}"] = float(np.quantile(v, q))
    return out


def stat_size(E, C, path, w=None, families_only=None, anon=False):
    """Item e on one population. E: family results, C: comparator texts."""
    out = {}
    comp = {"n": int(len(C)), "sessions": int(C.session_id.nunique()) if len(C) else 0,
            "by_source": {k: int(v) for k, v in C.source.value_counts().items()} if len(C) else {},
            "zero_byte": int((C.bytes == 0).sum()) if len(C) else 0}
    if w is None:
        comp["log10_bytes_quantiles"] = qt(C.log_b if len(C) else [])
    comp["iqr"] = iqr_boot(C.log_b.to_numpy(float), C.session_id.to_numpy(), w) if len(C) else {"value": None}
    out["comparator"] = comp
    fams = {}
    if len(E):
        g = E.groupby("family").agg(n=("seq", "size"), s=("session_id", "nunique"))
        qual = sorted(g[(g.n >= E_FAM_MIN[0]) & (g.s >= E_FAM_MIN[1])].index)
    else:
        g, qual = None, []
    if families_only is not None:
        qual = [f for f in qual if f in families_only]
    chi = comp["iqr"].get("hi")
    above = 0
    alias = {f: f"family_{i}" for i, f in enumerate(sorted(qual, key=lambda x: (-int(g.loc[x, "n"]), x)))} if anon else {}
    for f in qual:
        sub = E[E.family == f]
        b = iqr_boot(sub.log_b.to_numpy(float), sub.session_id.to_numpy(), w)
        rec = {"n": int(len(sub)), "sessions": int(sub.session_id.nunique()), "iqr": b,
               "zero_byte": int((sub.bytes == 0).sum()),
               "above_comparator_ci_hi": (b.get("value") is not None and chi is not None and b["value"] > chi)}
        if w is None:
            rec["log10_bytes_quantiles"] = qt(sub.log_b)
        above += int(rec["above_comparator_ci_hi"])
        fams[alias.get(f, f)] = rec
    out["families_qualifying"] = len(qual)
    out["families_total"] = int(len(g)) if g is not None else 0
    out["families_above"] = above
    out["share_above"] = (above / len(qual)) if qual else None
    out["families"] = fams
    # verdict
    if not qual:
        v = {"label": "INSUFFICIENT_N", "rule": f"no family with >= {E_FAM_MIN[0]} results from >= {E_FAM_MIN[1]} sessions",
             "deciding_number": 0, "deciding_path": f"{path}.families_qualifying"}
    elif comp["n"] < E_COMP_MIN[0] or comp["sessions"] < E_COMP_MIN[1] or not comp["iqr"].get("ci_reported"):
        v = {"label": "INCONCLUSIVE", "rule": "comparator below 30 texts / 5 sessions or its IQR CI not reportable",
             "deciding_number": {"n": comp["n"], "sessions": comp["sessions"],
                                 "valid_draws": comp["iqr"].get("valid_draws")},
             "deciding_path": [f"{path}.comparator.n", f"{path}.comparator.sessions", f"{path}.comparator.iqr.valid_draws"]}
    elif out["share_above"] >= E_SHARE:
        v = {"label": "WEAK", "rule": ">= 0.5 of qualifying families have IQR above the comparator's CI hi (capped at "
                                      "WEAK: population-level, no per-call decision)",
             "deciding_number": {"share_above": out["share_above"], "families_above": above,
                                 "families_qualifying": len(qual), "comparator_ci_hi": chi},
             "deciding_path": [f"{path}.share_above", f"{path}.comparator.iqr.hi"]}
    else:
        v = {"label": "DEAD", "rule": "< 0.5 of qualifying families have IQR above the comparator's CI hi",
             "deciding_number": {"share_above": out["share_above"], "families_above": above,
                                 "families_qualifying": len(qual), "comparator_ci_hi": chi},
             "deciding_path": [f"{path}.share_above", f"{path}.comparator.iqr.hi"]}
    out["verdict"] = v
    return out


# ================================================================================================== per item blocks
def block(item, R, path, checker=None, w=None):
    """All numbers + verdict of one rate item (a, b/d checker, f) on one population."""
    df = R
    if checker is not None and len(df):
        df = df[df.checker == checker]
    flag = {"a": "drift", "b": "violation", "d": "violation", "f": "unfaithful"}[item]
    r = stat_rate_item(item, df, f"{path}.rate", flag=flag, w=w)
    out = {"rate": r}
    if w is None:
        out["n"] = int(len(df))
        out["sessions"] = int(df.session_id.nunique()) if len(df) else 0
        if item == "a" and len(df):
            out["identical_unmasked"] = zrate(df.identical.to_numpy(), df.session_id.to_numpy())
            out["drift_by_key"] = {k: {"pairs": int(len(g)), "drift": int(g.drift.sum())}
                                   for k, g in df.groupby("key")}
        if item == "b" and len(df):
            out["by_via"] = {k: {"outputs": int(len(g)), "violations": int(g.violation.sum()),
                                 "sessions": int(g.session_id.nunique())} for k, g in df.groupby("via")}
        out["positive_control"] = pc_block(df, flag)
        out["post_hoc_not_a_verdict"] = post_hoc(item, df, checker)
    out["verdict"] = rate_verdict(item, r, f"{path}.rate")
    return out


def post_hoc(item, df, checker):
    """Descriptive breakdowns of honest violations. POST HOC, NOT A VERDICT (PREREG_E 1.1 'no rescue')."""
    if not len(df):
        return {}
    out = {}
    if item == "a":
        for name, m in (("redaction_marker_in_key", df.redaction_in_key.astype(bool)),
                        ("either_result_primary_error", df.err_any.astype(bool))):
            out[name] = {"pairs_with": int(m.sum()), "drift_with": int(df.drift[m].sum()),
                         "pairs_without": int((~m).sum()), "drift_without": int(df.drift[~m].sum())}
        m = ~(df.redaction_in_key.astype(bool) | df.err_any.astype(bool))
        out["neither"] = {"pairs": int(m.sum()), "drift": int(df.drift[m].sum()),
                          "rate": zrate(df.drift[m].to_numpy(), df.session_id[m].to_numpy()) if m.sum() else None}
    if item == "b" and checker == "grep_n" and "alt_colon_only" in df:
        alt = df.alt_colon_only
        el = alt.notna().to_numpy()
        altv = np.array([bool(x) if x is not None and x == x else False for x in alt.astype(object)])
        viol = df.violation.astype(bool).to_numpy()
        out["colon_only_match_lines"] = {
            "rule": "match lines only, path delimited by ':' (hyphenated file names not split); context lines skipped",
            "outputs_eligible": int(el.sum()), "violations": int((altv & el).sum()),
            "frozen_violations_on_same_outputs": int((viol & el).sum()),
            "frozen_violations_not_violating_under_alt": int((viol & el & ~altv).sum()),
            "frozen_violations_ineligible_under_alt": int((viol & ~el).sum())}
    if item == "d" and checker == "pytest_banner" and "cmd_mentions_pytest" in df:
        m = df.cmd_mentions_pytest.astype(bool)
        out["command_mentions_pytest"] = {"outputs_with": int(m.sum()), "violations_with": int(df.violation[m].sum()),
                                          "outputs_without": int((~m).sum()),
                                          "violations_without": int(df.violation[~m].sum())}
    return out


def cell_of(lb, le, has_e):
    if has_e and le is not None and le != "INSUFFICIENT_N":
        return le, "E", ""
    return lb, "B", (" (B only, unreplicated)" if not has_e else " (B only; E INSUFFICIENT_N: NOT_REPLICABLE_AT_N)")


def lower(a, b):
    if a in LVL and b in LVL:
        return a if LVL[a] <= LVL[b] else b
    return a if a in LVL else b


# ================================================================================================== artifact checks
def _lab(x):
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return "nan"
    return str(x)


def recompute(item, R, checker, sess=None, w=None, extra=None):
    """Label of the item statistic on a sub-population (sessions in `sess`, or rows passing `extra`)."""
    df = R
    if sess is not None and len(df):
        df = df[df.session_id.isin(sess)]
    if extra is not None and len(df):
        df = df[extra(df)]
    if item == "e":
        E, C = df
        raise RuntimeError("use recompute_e")
    return block(item, df, "ac", checker=checker, w=w)


def recompute_e(E, C, sess=None, w=None, rowmask=None, families_only=None):
    if sess is not None:
        E = E[E.session_id.isin(sess)] if len(E) else E
        C = C[C.session_id.isin(sess)] if len(C) else C
    if rowmask is not None and len(E):
        E = E[rowmask(E)]
    return stat_size(E, C, "ac", w=w, families_only=families_only)


def summarize_block(item, b):
    if item == "e":
        return {"label": b["verdict"]["label"], "families_qualifying": b["families_qualifying"],
                "share_above": b["share_above"], "comparator_iqr": [b["comparator"]["iqr"].get(k) for k in
                                                                    ("value", "lo", "hi")]}
    r = b["rate"]
    return {"label": b["verdict"]["label"], "n": int(r.get("den", 0) or 0), "sessions": int(r.get("n_sessions", 0) or 0),
            "rate": r.get("rate"), "ci": [r.get("lo"), r.get("hi")], "num": r.get("num")}


def dominance_check(item, R, checker, base, smeta, unit, sess_all):
    """AC4 on B u E. Denominator events = the item's decision units per session."""
    if item == "e":
        E, C = R
        w = E.groupby("session_id").size().to_dict() if len(E) else {}
    else:
        df = R[R.checker == checker] if (checker is not None and len(R)) else R
        w = df.groupby("session_id").size().to_dict() if len(df) else {}
    kinds = ["repo", "user", "model"] if CORPUS_OF[unit] == "swechat" else ["repo", "model"]
    out = {"denominator": "decision units per session", "kinds": {}}
    leaveouts = []
    dom = False
    for kind in kinds:
        cmap = {s: smeta[s][kind] for s in w}
        d = pe.dominance(w, cmap)
        rec = {k: d.get(k) for k in ("top_share_events", "top_share_sessions", "n_clusters", "dominated")}
        top = d.get("top_clusters", [])
        rec["top5"] = [[(c if unit != "cc_local" else f"cluster_{i}"), a, b] for i, (c, a, b) in enumerate(top)]
        rec["top_cluster"] = (d.get("top_cluster") if unit != "cc_local" else "cluster_0")
        cd = max(d.get("top_share_events", 0) or 0, d.get("top_share_sessions", 0) or 0) > pe.DOM_SHARE
        rec["cluster_dominated"] = bool(cd)
        out["kinds"][kind] = rec
        if cd and unit == "aiv_cc" and d.get("n_clusters") == 1:
            rec["label_only"] = "aiv_cc is one agent (one model): always dominated, only labelled (PREREG_E 1.1)"
            continue
        if cd:
            dom = True
            for i, (c, _, _) in enumerate(top):
                keep = {s for s in sess_all if smeta[s][kind] != c}
                leaveouts.append((kind, c if unit != "cc_local" else f"cluster_{i}", keep))
    if w:
        ts = sorted(w.items(), key=lambda kv: -kv[1])
        share = ts[0][1] / max(sum(w.values()), 1)
        out["top_session_share_events"] = share
        if share > pe.DOM_SESSION:
            dom = True
            for rank, (s, _) in enumerate(ts[:5]):
                leaveouts.append(("session", f"largest_session_rank_{rank + 1}", set(sess_all) - {s}))
    out["dominated"] = dom
    res, effect = [], "pass"
    for kind, c, keep in leaveouts:
        if item == "e":
            b = recompute_e(R[0], R[1], sess=keep)
        else:
            b = recompute(item, R, checker, sess=keep)
        sm = summarize_block(item, b)
        sm.update({"kind": kind, "left_out": c})
        res.append(sm)
        lab = sm["label"]
        if lab == "INSUFFICIENT_N":
            if effect == "pass":
                effect = "cap_weak"
        elif lab in LVL and base in LVL and LVL[lab] < LVL[base]:
            effect = "downgrade"
    out["leaveouts"] = res
    out["effect"] = effect if dom else "pass"
    out["status"] = ("DOMINATED" if out["effect"] == "downgrade" else "UNTESTABLE_WITHOUT_DOMINANT"
                     if out["effect"] == "cap_weak" else "dominated, label stable" if dom else "not dominated")
    return out


def strata_check(item, R, checker, smeta, unit, sess_all):
    out = {}
    for axis in ("tool_key", "model", "repo", "length_tercile"):
        groups = {}
        if axis == "tool_key":
            if item == "e":
                out[axis] = {"strata": {}, "confinement": "UNTESTABLE",
                             "note": "single tool class (shell-command families)"}
                continue
            df = R[R.checker == checker] if (checker is not None and len(R)) else R
            col = "key"
            if item == "b":
                vals = sorted(set(zip(df.key, df.via)))
                groups = {f"{k}|{v}": ("rows", (lambda d, k=k, v=v: (d.key == k) & (d.via == v))) for k, v in vals}
            else:
                groups = {k: ("rows", (lambda d, k=k: d[col] == k)) for k in sorted(df[col].unique())} if len(df) else {}
        else:
            vals = Counter(smeta[s][axis] for s in sess_all)
            groups = {v: ("sess", {s for s in sess_all if smeta[s][axis] == v}) for v in vals}
        labels, rec = {}, {}
        for i, (k, (mode, sel)) in enumerate(sorted(groups.items(), key=lambda kv: str(kv[0]))):
            if item == "e":
                b = recompute_e(R[0], R[1], sess=sel)
            elif mode == "rows":
                b = recompute(item, R, checker, extra=sel)
            else:
                b = recompute(item, R, checker, sess=sel)
            sm = summarize_block(item, b)
            name = k if (unit != "cc_local" or axis in ("tool_key", "length_tercile")) else f"{axis}_{i}"
            rec[name] = sm
            labels[name] = sm["label"] if sm["label"] in LVL else None
        out[axis] = {"strata": rec, "confinement": pe.confinement(labels)}
    out["CONFINED_any_axis"] = any(v.get("confinement") == "CONFINED" for v in out.values() if isinstance(v, dict))
    return out


# ---------------------------------------------------------------- AC1 (raw source audit; Claude Code formats only)
def _raw_decision(item, checker, via, cmd, args_obj, texts):
    """The item's decision recomputed from raw-source fields (texts: [text] or [text_a, text_b] for a)."""
    if item == "a":
        return pe.mask_volatile(texts[0]) != pe.mask_volatile(texts[1])
    t = texts[0]
    if item == "b":
        if via == "grep_tool":
            return pe.grepn_order_violation(json.dumps(args_obj), t, is_grep_tool=True)
        fn = {"ls": pe.ls_order_violation, "git_log": pe.gitlog_order_violation, "grep_n": pe.grepn_order_violation}[checker]
        return fn(cmd, t) if cmd else None
    if item == "d":
        return pe.ws_violations(cmd, t).get(checker) if cmd else None
    return None


def ac1_audit(item, unit, R, checker, kind):
    """AC1: audit_sample() of 30 numerator events (or a 30-event denominator diagnostic), each looked up in the raw
    source by (session_id, call_id) with the committed N1 reader. An event DIFFERS when its decision recomputed from the
    raw fields differs from the IR decision (a: drift of the two raw texts; b/d: the checker on the raw command and text;
    f: raw result text or raw error flag differs), or when it is not found. Text / command differences that leave the
    decision unchanged are counted separately (no effect)."""
    from analysis.probes import phase_e_n1 as n1  # committed raw readers (read-only)
    from analysis.lib.ir import error_marker
    if unit not in ("swechat/claude_code", "aiv_cc"):
        return {"label": "NOT_RUN", "reason": f"no committed raw reader for {unit} (Claude Code formats only)"}
    df = R[R.checker == checker] if (checker is not None and len(R)) else R
    flag = {"a": "drift", "b": "violation", "d": "violation", "f": "unfaithful"}[item]
    if kind == "numerator":
        df = df[df[flag].astype(bool)]
    if item == "a":
        keys = sorted(set(zip(df.session_id, df.seq_a, df.seq_b)))
        pick = set(pe.audit_sample(keys, seed_parts=("N5", item, str(checker), "AC1", kind, unit)))
        sub = df[[k in pick for k in zip(df.session_id, df.seq_a, df.seq_b)]]
        evs = [(r.session_id, (r.call_id_a, r.call_id_b), bool(getattr(r, flag)), None) for r in sub.itertuples()]
    else:
        keys = sorted(set(zip(df.session_id, df.seq, df.call_id)))
        pick = set(pe.audit_sample(keys, seed_parts=("N5", item, str(checker), "AC1", kind, unit)))
        sub = df[[k in pick for k in zip(df.session_id, df.seq, df.call_id)]]
        evs = [(r.session_id, (r.call_id,), bool(getattr(r, flag)), getattr(r, "via", None)) for r in sub.itertuples()]
    if not evs:
        return {"label": "PASS" if kind == "numerator" else "diagnostic only (post hoc, not a verdict)", "audited": 0,
                "pool_size": int(len(keys)), "note": "empty: nothing to audit"}
    targets = [{"session_id": s, "call_id": c} for s, cs, _, _ in evs for c in cs]
    raw = n1.raw_lookup(unit, targets)
    OPENED.extend(n1.OPENED)
    sids = sorted({t["session_id"] for t in targets})
    ir = {}
    for split in (("B", "E") if CORPUS_OF[unit] in pe.CORPORA_WITH_E else ("B",)):
        d = pe.read_cache(CORPUS_OF[unit], split, ["session_id", "kind", "call_id", "text", "command", "args",
                                                   "native_error"],
                          filters=[("session_id", "in", sids), ("kind", "in", ["call", "result"])])
        for s_, k, c, t, cm, a, ne in zip(d.session_id, d.kind, d.call_id.astype(object), d.text.astype(object),
                                          d.command.astype(object), d.args.astype(object), d.native_error.astype(object)):
            if c is None:
                continue
            e = ir.setdefault((s_, str(c)), {})
            if k == "call" and "cmd" not in e:
                o = pc.jl(a) if isinstance(a, str) else {}
                e["cmd"] = cm if isinstance(cm, str) else (o.get("command") if isinstance(o.get("command"), str) else None)
            elif k == "result" and "text" not in e:
                e["text"] = t if isinstance(t, str) else ""
                e["native_error"] = ne
    recs = []
    for sid, cids, ir_dec, via in evs:
        why, info = [], []
        texts, found = [], True
        cmd, args_obj, raw_err = None, {}, None
        for c in cids:
            cl, rs = raw.get(c, ([], []))
            e = ir.get((sid, c), {})
            if not cl or not rs:
                found = False
                continue
            rt = rs[0]["text"]
            texts.append(rt)
            if rt != e.get("text"):
                info.append("result text")
            inp = cl[0]["input"]
            args_obj = inp
            cmd = inp.get("command") if isinstance(inp.get("command"), str) else None
            if (pe.normalize_command(cmd) if cmd else None) != (pe.normalize_command(e.get("cmd")) if e.get("cmd") else None):
                info.append("command")
            if item == "f":
                raw_err = bool(rs[0]["is_error"] is True and error_marker(rt) not in ("cc_permission_denied",
                                                                                      "cc_interrupt_reject"))
                ir_err = bool(e.get("native_error") is True) and error_marker(e.get("text") or "") not in (
                    "cc_permission_denied", "cc_interrupt_reject")
                if raw_err != ir_err:
                    why.append("error flag")
                if rt != e.get("text"):
                    why.append("result text (frame source)")
            if len(cl) > 1 or len(rs) > 1:
                info.append("multiple raw occurrences")
        if not found:
            why.append("not found in raw")
        elif item != "f":
            rd = _raw_decision(item, checker, via, cmd, args_obj, texts)
            if rd is None or bool(rd) != ir_dec:
                why.append("decision" if rd is not None else "not eligible on raw fields")
        recs.append({"found": found, "differs": bool(why), "why": sorted(set(why)), "info": sorted(set(info))})
    nd = sum(1 for x in recs if x["differs"])
    out = {"population": "B u E" if CORPUS_OF[unit] in pe.CORPORA_WITH_E else "B", "pool_size": int(len(keys)),
           "audited": int(len(recs)), "differing": int(nd),
           "differing_reasons": dict(Counter(w for x in recs for w in x["why"])),
           "field_differences_without_decision_change": dict(Counter(w for x in recs if not x["differs"]
                                                                     for w in x["info"])),
           "not_found": int(sum(1 for x in recs if not x["found"])),
           "seed_parts": ["N5", item, str(checker), "AC1", kind, unit]}
    if kind == "numerator":
        out["label"] = "FAIL" if nd >= pe.AUDIT_FAIL else ("PARSER_NOTE" if nd == 1 else "PASS")
        out["rule"] = "FAIL if >= 2 of 30 differ in a way that changes their contribution; 1 = PARSER_NOTE"
    else:
        out["label"] = "diagnostic only (post hoc, not a verdict)"
    return out


def run_checks(item, unit, R_be, checker, base, smeta, sess_all, results_by_split):
    """AC1-AC5 + strata on B u E for one item (checker). Returns (checks dict, list of effects, final label)."""
    ac = {"population": "B u E" if CORPUS_OF[unit] in pe.CORPORA_WITH_E else "B", "base_label": base}
    eff = []
    lab_of = (lambda b: b["verdict"]["label"])
    # AC2 truncation
    if item == "e":
        b = recompute_e(R_be[0], R_be[1], rowmask=lambda d: ~d.trunc)
    elif item == "a":
        b = recompute(item, R_be, checker, extra=lambda d: ~d.trunc)
    else:
        b = recompute(item, R_be, checker, extra=lambda d: ~d.trunc)
    ac["AC2_no_truncated"] = {**summarize_block(item, b), "fail": lab_of(b) != base}
    if item == "a":
        ac["AC2_no_truncated"]["note"] = "determinism_pairs() already excludes truncated results (by construction)"
    if lab_of(b) != base:
        eff.append(("AC2", lab_of(b)))
    # AC3 join
    if item == "e":
        b = recompute_e(R_be[0], R_be[1], rowmask=lambda d: d.join_clean)
    else:
        b = recompute(item, R_be, checker, extra=lambda d: d.join_clean)
    ac["AC3_join_clean"] = {**summarize_block(item, b), "fail": lab_of(b) != base}
    if lab_of(b) != base:
        eff.append(("AC3", lab_of(b)))
    # AC4
    ac["AC4_dominance"] = dominance_check(item, R_be, checker, base, smeta, unit, sess_all)
    # AC5
    if CORPUS_OF[unit] in ("swechat", "aiv_cu"):
        if item == "e":
            ss = sorted(set(R_be[0].session_id) | set(R_be[1].session_id))
            wts = pe.post_strat_weights(CORPUS_OF[unit], ss)
            b = recompute_e(R_be[0], R_be[1], w=wts)
        else:
            df = R_be[R_be.checker == checker] if checker is not None else R_be
            wts = pe.post_strat_weights(CORPUS_OF[unit], sorted(set(df.session_id)))
            b = block(item, R_be, "ac5", checker=checker, w=wts)
        ac["AC5_post_stratified"] = {**summarize_block(item, b), "fail": lab_of(b) != base,
                                     "weights": "population cell size / analysed sessions in the cell (post_strat_weights)"}
        if lab_of(b) != base:
            eff.append(("AC5", lab_of(b)))
        if "B" in results_by_split and "E" in results_by_split and item != "e":
            bp = results_by_split["B"]["rate"].get("rate")
            e = results_by_split["E"]["rate"]
            ac["AC5_shift"] = {"B_point": bp, "E_ci": [e.get("lo"), e.get("hi")],
                               "SHIFT": (bp is not None and e.get("lo") is not None and not (e["lo"] <= bp <= e["hi"])),
                               "note": "reported, no verdict effect"}
    else:
        ac["AC5_post_stratified"] = {"label": "NOT_RUN", "reason": "no population table for this corpus"}
    # AC1
    if item == "e":
        ac["AC1_parser"] = {"label": "NOT_RUN", "reason": "item e is a population statistic with no numerator events; "
                                                          "result bytes are audited by the a/b/d/f samples where they run"}
    else:
        ac["AC1_parser"] = ac1_audit(item, unit, R_be, checker, "numerator")
        if ac["AC1_parser"].get("label") != "NOT_RUN":
            ac["AC1_parser_diagnostic_denominator"] = ac1_audit(item, unit, R_be, checker, "denominator")
    st = strata_check(item, R_be, checker, smeta, unit, sess_all)
    return ac, st, eff


# ================================================================================================== main
def main():
    store = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # unit -> split -> rec -> [frames]
    sess_tab = defaultdict(lambda: defaultdict(list))
    gates = defaultdict(lambda: defaultdict(Counter))
    models = defaultdict(dict)
    nsplit = defaultdict(dict)
    copied = {}
    for corpus, unit, split, df, nss, ci in unit_chunks():
        nsplit[unit][split] = nss
        if df is None:
            continue
        if corpus not in copied:
            copied[corpus] = copied_call_ids(corpus)
        print(f"[{time.time() - T0:7.1f}s] {unit} {split} chunk {ci}: {len(df)} rows ({nss} sessions in split)", flush=True)
        rec, ps, gate, model = extract(unit, split, df, copied[corpus])
        for k, v in rec.items():
            store[unit][split][k].append(v)
        sess_tab[unit][split].append(ps)
        gates[unit][split].update(gate)
        models[unit].update(model)
        del df, rec
        gc.collect()
    print(f"[{time.time() - T0:7.1f}s] statistics", flush=True)

    def cat(unit, split, k):
        lst = [x for x in store[unit][split].get(k, []) if len(x)]
        df = pd.concat(lst, ignore_index=True) if lst else pd.DataFrame(columns=EMPTY_COLS[k])
        for c in BOOL_COLS:
            if c in df.columns:
                df[c] = df[c].astype(bool)
        return df

    out = {"item": "n5_battery", "items_covered": list(ITEMS), "items_not_covered": {
               "c_truncation_boundary": "not part of this item (separate assignment)",
               "g_cold_start": "not part of this item (separate assignment)"},
           "script": "analysis/probes/phase_e_n5_battery.py", "prereg_section": "prereg_e.json n5_battery",
           "prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
           "spec_module_sha256": PJ["provenance"]["spec_module_sha256"],
           "spec_module_sha256_lf": pe.sha256_lf(pe.ROOT / "analysis" / "probes" / "prereg_e_common.py"),
           "check_frozen": "passed", "spec": {k: SPEC[ITEM_NAME[k]] for k in ITEMS},
           "thresholds_used": {"min_n": {k: {"events": v[0], "sessions": v[1]} for k, v in MIN.items()},
                               "rate_rules": TH, "e_family_min": {"results": E_FAM_MIN[0], "sessions": E_FAM_MIN[1]},
                               "e_share_for_weak": E_SHARE,
                               "e_comparator_min": {"texts": E_COMP_MIN[0], "sessions": E_COMP_MIN[1]}},
           "seeds": {"bootstrap": pe.SEED, "positive_control_b": "rng_for('N5bpc', session_id, call_id, checker), "
                                                                 f"SEED_E={pe.SEED_E}",
                     "AC1": "audit_sample seed_parts ('N5', item, checker, 'AC1', kind, unit)"},
           "A_split_eligibility_context": {u: CAL_A["units"].get(u, {}).get("n5") for u in UNITS
                                           if CAL_A["units"].get(u, {}).get("n5") is not None},
           "self_tests": {"iqr_boot_fast_equals_boot_stat": selftest()},
           "cells_computed": 0, "units": {}}
    n_cells = 0
    for unit in UNITS:
        has_e = CORPUS_OF[unit] in pe.CORPORA_WITH_E
        splits = [s for s in ("B", "E") if s in store[unit]]
        U = {"labels": LABELS.get(unit, []), "sessions_in_split": dict(nsplit.get(unit, {})), "has_E": has_e,
             "field_gate": {s: dict(gates[unit][s]) for s in splits}}
        if not splits:
            U["cells"] = {N6_ROW[k]: {"label": "NOT_TESTABLE(no sessions in B or E)"} for k in ITEMS}
            out["units"][unit] = U
            continue
        # session meta (strata, dominance)
        st_all = pd.concat([x for s in splits for x in sess_tab[unit][s]], ignore_index=True)
        sids_all = sorted(set(st_all.session_id))
        corpus = CORPUS_OF[unit]
        dummy = pd.DataFrame({"session_id": sids_all, "stratum": [None] * len(sids_all)})
        if corpus in ("cc_local", "whowhen"):
            # stratum per session from the IR (project alias / stratum); read only that column
            strat = {}
            for s in splits:
                d = pe.read_cache(corpus, s, ["session_id", "stratum"])
                strat.update(d.groupby("session_id").stratum.first().astype(str).to_dict())
            dummy["stratum"] = [strat.get(s, "unknown") for s in sids_all]
        repo = pe.session_cluster_map(corpus, dummy, kind="repo") if corpus != "aiv_cc" else {s: "aiv_cc" for s in sids_all}
        user = pe.session_cluster_map(corpus, dummy, kind="user") if corpus == "swechat" else {}
        npairs = dict(zip(st_all.session_id, st_all.pairs))
        terc = pe.length_tercile_map(npairs, TERC[unit]["cuts"]) if TERC.get(unit, {}).get("cuts") else {}
        smeta = {s: {"model": _lab(models[unit].get(s, "unknown")), "repo": _lab(repo.get(s, "unknown")),
                     "user": _lab(user.get(s, "n/a")), "length_tercile": terc.get(s, "short")} for s in sids_all}
        U["coverage"] = {}
        for s in splits:
            t = pd.concat(sess_tab[unit][s], ignore_index=True)
            U["coverage"][s] = {"sessions": int(len(t)), "paired_calls": int(t.pairs.sum()),
                                "error_results": int(t.err_results.sum()),
                                "numbered_read_results": int(t.numbered_reads.sum())}
        pops = {s: {k: cat(unit, s, k) for k in ("a", "b", "d", "e", "e_comp", "f")} for s in splits}
        if len(splits) == 2:
            pops["BE"] = {k: pd.concat([pops["B"][k], pops["E"][k]], ignore_index=True) for k in pops["B"]}
        acpop = "BE" if "BE" in pops else splits[0]
        g_all = Counter()
        for s in splits:
            g_all.update(gates[unit][s])
        no_results = g_all["pairs"] == 0
        no_cmd = g_all["shell_calls_with_command"] == 0
        no_reads = g_all["numbered_read_results"] == 0
        U["results"] = {}
        U["cells"] = {}
        for item in ITEMS:
            row = N6_ROW[item]
            gate_missing = None
            if no_results:
                gate_missing = "no tool results"
            elif item == "a" and no_cmd and g_all["read_results"] == 0:
                gate_missing = "no shell commands and no Read results"
            elif item == "b" and no_cmd and g_all["grep_tool_results"] == 0:
                gate_missing = "no shell commands and no Grep-tool results"
            elif item in ("d", "e") and no_cmd:
                gate_missing = "no shell commands"
            elif item == "f" and no_reads:
                gate_missing = "no numbered Read results"
            res = {}
            if item in ("a", "f"):
                for s in pops:
                    res[s] = block(item, pops[s][item], f"units.{unit}.results.{item}.{s}")
                    n_cells += 1
                if item == "f":
                    for s in pops:
                        cov_den = (sum(U["coverage"][x]["error_results"] for x in splits) if s == "BE"
                                   else U["coverage"][s]["error_results"])
                        res[s]["coverage"] = {"checkable_frames": res[s]["n"], "error_results": cov_den,
                                              "share": (res[s]["n"] / cov_den) if cov_den else None}
                lb = res.get("B", {}).get("verdict", {}).get("label")
                le = res.get("E", {}).get("verdict", {}).get("label")
                cell, src, suf = cell_of(lb, le, has_e)
                cells = {None: {"B": lb, "E": le, "cell": cell, "source": src, "suffix": suf,
                                "BE_pooled_not_the_cell": res.get("BE", {}).get("verdict", {}).get("label")}}
            elif item in ("b", "d"):
                cells = {}
                for ch in CHECKERS[item]:
                    res.setdefault("per_checker", {})[ch] = {}
                    for s in pops:
                        res["per_checker"][ch][s] = block(item, pops[s][item], f"units.{unit}.results.{item}.per_checker.{ch}.{s}",
                                                          checker=ch)
                        n_cells += 1
                    lb = res["per_checker"][ch].get("B", {}).get("verdict", {}).get("label")
                    le = res["per_checker"][ch].get("E", {}).get("verdict", {}).get("label")
                    cell, src, suf = cell_of(lb, le, has_e)
                    cells[ch] = {"B": lb, "E": le, "cell": cell, "source": src, "suffix": suf,
                                 "BE_pooled_not_the_cell": res["per_checker"][ch].get("BE", {}).get("verdict", {})
                                 .get("label")}
            else:  # e
                for s in pops:
                    res[s] = stat_size(pops[s]["e"], pops[s]["e_comp"], f"units.{unit}.results.e.{s}",
                                       anon=(unit == "cc_local"))
                    n_cells += 1
                lb = res.get("B", {}).get("verdict", {}).get("label")
                le = res.get("E", {}).get("verdict", {}).get("label")
                cell, src, suf = cell_of(lb, le, has_e)
                cells = {None: {"B": lb, "E": le, "cell": cell, "source": src, "suffix": suf,
                                "BE_pooled_not_the_cell": res.get("BE", {}).get("verdict", {}).get("label")}}
            U["results"][item] = res
            # ---- artifact checks per checker (or item) that reached WEAK or better on B or E
            per = {}
            for ch, c in cells.items():
                final = c["cell"]
                applied = []
                reach = any(x in ("ALIVE", "WEAK") for x in (c["B"], c["E"]))
                if gate_missing:
                    final = f"NOT_TESTABLE({gate_missing})"
                    c["checks"] = {"status": "not run: field gate"}
                elif reach:
                    if item == "e":
                        Rbe = (pops[acpop]["e"], pops[acpop]["e_comp"])
                        base = res[acpop]["verdict"]["label"]
                        rbs = {}
                        sess_all = sorted(set(Rbe[0].session_id) | set(Rbe[1].session_id))
                    else:
                        Rbe = pops[acpop][item]
                        rb = res["per_checker"][ch] if ch is not None else res
                        base = rb[acpop]["verdict"]["label"]
                        rbs = {s: rb[s] for s in ("B", "E") if s in rb}
                        dfc = Rbe[Rbe.checker == ch] if ch is not None else Rbe
                        sess_all = sorted(set(dfc.session_id))
                    print(f"[{time.time() - T0:7.1f}s] checks {unit} {item} {ch}", flush=True)
                    ac, st, eff = run_checks(item, unit, Rbe, ch, base, smeta, sess_all, rbs)
                    for name, lab in eff:
                        if lab in LVL and final in LVL and LVL[lab] < LVL[final]:
                            final = lab
                            applied.append({"name": name, "effect": f"lower label to {lab}"})
                        elif lab not in LVL:
                            applied.append({"name": name, "effect": f"label {lab} on the recompute (not a level; "
                                                                    "no change)"})
                    a4 = ac["AC4_dominance"]["effect"]
                    if a4 == "downgrade":
                        final = pe.downgrade(final)
                        applied.append({"name": "AC4 DOMINATED", "effect": "downgrade"})
                    elif a4 == "cap_weak" and final == "ALIVE":
                        final = "WEAK"
                        applied.append({"name": "AC4 UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
                    if ac.get("AC1_parser", {}).get("label") == "FAIL":
                        final = pe.downgrade(final)
                        applied.append({"name": "AC1 FAIL", "effect": "downgrade"})
                    if st["CONFINED_any_axis"]:
                        final = pe.downgrade(final)
                        applied.append({"name": "CONFINED", "effect": "downgrade"})
                    c["checks"] = {"artifact_checks": ac, "stratification": st}
                else:
                    c["checks"] = {"status": "not required: neither B nor E reached WEAK or better"}
                c["final"] = final
                c["checks_applied"] = applied
                per[ch if ch is not None else "_"] = c
            if item in ("b", "d"):
                labs = [v["final"] for v in per.values()]
                lv = [x for x in labs if x in LVL]
                if gate_missing:
                    item_cell = f"NOT_TESTABLE({gate_missing})"
                elif lv:
                    item_cell = min(lv, key=lambda x: LVL[x])
                else:
                    item_cell = "INSUFFICIENT_N" if all(x == "INSUFFICIENT_N" for x in labs) else labs[0]
                U["cells"][row] = {"label": item_cell, "rule": "lowest final label among checkers with an "
                                                                "ALIVE/WEAK/DEAD cell (deviation 'item cell for "
                                                                "multi-checker items')",
                                   "per_checker": per,
                                   "suffix": "".join(f" [{x}]" for x in U["labels"])}
            else:
                c = per["_"]
                U["cells"][row] = {"label": c["final"], "before_checks": c["cell"], "B": c["B"], "E": c["E"],
                                   "BE_pooled_not_the_cell": c.get("BE_pooled_not_the_cell"),
                                   "source": c["source"], "suffix": c["suffix"] + "".join(f" [{x}]" for x in U["labels"]),
                                   "checks_applied": c["checks_applied"], "checks": c["checks"]}
        out["units"][unit] = U
    out["cells_computed"] = n_cells
    out["deviations"] = DEVIATIONS
    # compact summary (raw labels and deciding numbers, with paths)
    summ = {}
    for unit, U in out["units"].items():
        row = {}
        for item in ITEMS:
            c = U["cells"].get(N6_ROW[item], {})
            row[N6_ROW[item]] = {"cell": c.get("label")}
            res = U.get("results", {}).get(item, {})
            if item in ("a", "f", "e"):
                for s, b in res.items():
                    v = b.get("verdict", {})
                    row[N6_ROW[item]][s] = {"label": v.get("label"), "deciding_number": v.get("deciding_number"),
                                            "deciding_path": v.get("deciding_path")}
            else:
                for ch, bs in res.get("per_checker", {}).items():
                    for s, b in bs.items():
                        v = b.get("verdict", {})
                        row[N6_ROW[item]][f"{ch}.{s}"] = {"label": v.get("label"),
                                                          "deciding_number": v.get("deciding_number"),
                                                          "deciding_path": v.get("deciding_path")}
        summ[unit] = row
    out["summary_raw"] = summ
    # N6 cells with the deciding number and its JSON path (mechanical; no interpretation)
    n6 = {}
    for unit, U in out["units"].items():
        n6[unit] = {}
        for item in ITEMS:
            row = N6_ROW[item]
            c = U["cells"].get(row, {})
            rec = {"label": c.get("label"), "suffix": c.get("suffix", "")}
            res = U.get("results", {}).get(item, {})
            if item in ("b", "d") and "per_checker" in c:
                lv = {ch: x["final"] for ch, x in c["per_checker"].items()}
                rec["per_checker_final"] = lv
                pick = [ch for ch, l in lv.items() if l == c.get("label")]
                if pick and c.get("label") in LVL:
                    ch = pick[0]
                    x = c["per_checker"][ch]
                    v = res["per_checker"][ch][x["source"]]["verdict"]
                    rec.update({"deciding_checker": ch, "deciding_number": v.get("deciding_number"),
                                "deciding_path": v.get("deciding_path"), "checks_applied": x.get("checks_applied"),
                                "checks_path": f"units.{unit}.cells.{row}.per_checker.{ch}.checks"})
            if item in ("b", "d") and "per_checker" in c and c.get("label") not in LVL:
                # no ALIVE/WEAK/DEAD checker: the deciding numbers are each checker's n / sessions on its cell split
                dn, dp = {}, []
                for ch, x in c["per_checker"].items():
                    b = res.get("per_checker", {}).get(ch, {}).get(x.get("source", "B"))
                    if b is None:
                        continue
                    dn[ch] = {"n": int(b["rate"].get("den", 0) or 0), "sessions": int(b["rate"].get("n_sessions", 0) or 0)}
                    dp += [f"units.{unit}.results.{item}.per_checker.{ch}.{x.get('source', 'B')}.rate.den",
                           f"units.{unit}.results.{item}.per_checker.{ch}.{x.get('source', 'B')}.rate.n_sessions"]
                rec.update({"deciding_number": dn or None, "deciding_path": dp or None})
            if str(c.get("label", "")).startswith("NOT_TESTABLE") and "field_gate" in U:
                rec["field_gate"] = {s_: U["field_gate"][s_] for s_ in U["field_gate"]}
                rec["field_gate_path"] = f"units.{unit}.field_gate"
            if item not in ("b", "d") and res and c.get("source") in res:
                v = res[c["source"]]["verdict"]
                rec.update({"source_split": c["source"], "deciding_number": v.get("deciding_number"),
                            "deciding_path": v.get("deciding_path"), "checks_applied": c.get("checks_applied"),
                            "checks_path": f"units.{unit}.cells.{row}.checks"})
            n6[unit][row] = rec
    out["n6_cells"] = n6
    out["opened_files"] = sorted(set(OPENED)) + [
        "analysis/out/phase_e/prereg_e_calibration.json (A eligibility counts, context only)",
        "C:/Swarms/data/swe-chat-pinned/sessions.parquet (metadata: repo_id, user_id)",
        "analysis/cache/aiv_cu_sessions.parquet (metadata: agent_id, population cells)"]
    out["runtime_s"] = round(time.time() - T0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                   encoding="utf-8")
    print(f"[{time.time() - T0:7.1f}s] wrote {OUT}", flush=True)


def selftest():
    """iqr_boot_fast must reproduce boot_stat on the same groups exactly (synthetic values, no data)."""
    global FAST_IQR
    rng = np.random.default_rng(1)
    for n_s in (3, 25, 140):
        sids = np.repeat([f"s{i:03d}" for i in range(n_s)], rng.integers(1, 9, size=n_s))
        vals = rng.normal(2.0, 0.7, size=len(sids)).round(3)
        FAST_IQR = False
        a = iqr_boot(vals, sids)
        FAST_IQR = True
        b = iqr_boot(vals, sids)
        for k in ("value", "lo", "hi", "valid_draws"):
            assert (a.get(k) is None and b.get(k) is None) or abs(a[k] - b[k]) < 1e-12, (n_s, k, a.get(k), b.get(k))
    return True


if __name__ == "__main__":
    main()
