"""Phase E, Track A: N4 concurrency physics (prereg_e.json S:n4_concurrency) and N5 battery items c (truncation
boundary) and g (cold start) (prereg_e.json S:n5_battery.c_truncation_boundary, S:n5_battery.g_cold_start).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n4_n5cg

What it measures (definitions are the frozen prereg_e_common.py functions; this script only applies them):
  N4   W = Phase B qualified work-bound pairs (prereg_calibration.p1_qualified, W_KEYS / auto_read class, delta > 0);
       G = Phase B generation-bound pairs with g_latency() (probe_1.py G-set logic: G_TOOLS keys, reject markers and
       the CC nested human-marker exclusion removed, latency > 0). k = inflight_counts() over ALL pairs of the session
       (S:n4_concurrency.in_flight "other calls of the session (any thread)"). Delta = median log10 delta at k >= 2 minus
       at k = 1 within tool_key, pair-count-weighted mean over tool_keys with >= 30 pairs in each arm, session-bootstrap
       CI; Delta_W vs Delta_G; verdict per S:n4_concurrency.verdict. Also: in-flight distributions and share at k >= 4.
  N5c  truncation_info() on every paired result; exactness = marked results whose raw prefix / suffix (UTF-16) equal the
       A constants 5002 / 5002 (cc_chars_mid) or whose listed lines equal 100 (cc_glob_cap). cc_lines_tail: A constant
       INSUFFICIENT_N (n_A 4) -> NOT_RUN, counts reported. Positive control: a long real result re-truncated at uniform
       random lengths with the marker inserted.
  N5g  cold_start_values() on qualify_pairs() qualified pairs; pooled median c (cluster_quantile) and share(c_s <= 0)
       (Wilson); positive control: the first call's delta replaced by a later call's delta.
Per unit x split (B; E where the corpus has one; B u E pooled = the artifact-check population). The N6 cell is the E
verdict where E exists and is not INSUFFICIENT_N, else the B verdict ("B only"). For every cell at WEAK or better on B
or E: AC1-AC5 and the four stratification axes on B u E (S:artifact_checks, S:stratification).

Reads: analysis/cache/<corpus>_{B,E}.parquet through prereg_e_common.read_cache (never A, never H); population metadata
(swechat_population.parquet format/cells, swe-chat-pinned sessions.parquet repo_id/user_id, aiv_cu_sessions.parquet)
through prereg_e_common helpers; raw sources for AC1 only (swe-chat-pinned transcripts, ai-village
claude_code_messages.jsonl.gz), read-only, through analysis/probes/phase_e_n1.py raw_lookup.
Writes: analysis/out/phase_e/n4_n5cg.json (raw numbers only). Interpretation: analysis/notes/phase_e_n4_n5cg.md.
Corrections C1 (N4 W-only null -> DEAD) and C2 (AC4 below-min-n test on counts) are listed with before/after values in
the output's "corrections" block (CORRECTION_RULES / CORRECTION_VALUES below).
cc_local: aggregates only (no session id, command, path, text or cluster name is written). aiv_cc: single-agent case
study.
"""
import gc
import json
import math
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import error_marker, iso, parse_ts
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe
from analysis.probes import prereg_calibration as pcal       # p1_qualified, W_KEYS, G_TOOLS, g_latency (Phase B, frozen)
from analysis.probes import prereg_e_calibration as pecal    # COLS: the column set the calibration read

T0 = time.time()
PJ = pe.check_frozen()
SPEC4 = PJ["n4_concurrency"]
SPEC5 = PJ["n5_battery"]
TC_POOLED = PJ["resolved"]["n5"]["truncation_constants_pooled"]
TERC = PJ["resolved"]["length_terciles_A"]
CAL_A = json.loads((pe.OUT_E / "prereg_e_calibration.json").read_text(encoding="utf-8"))
OUT = pe.OUT_E / "n4_n5cg.json"

UNITS = ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "swechat/cursor",
         "swechat/copilot", "swechat/simple_text", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
LAT_UNITS = list(SPEC4["units"])          # N4 and N5g units (per-call stamps)
CORPUS_OF = {u: ("swechat" if u.startswith("swechat/") else u) for u in UNITS}
LABELS = {"cc_local": ["private: aggregates only", "B only, unreplicated (no E split)"],
          "aiv_cc": ["single-agent case study", "B only, unreplicated (no E split)"],
          "whowhen": ["B only, unreplicated (no E split)"]}
N5G_SHELL_LABEL = {"swechat/claude_code": "shell: human-wait contaminated (permissionMode not in the IR)",
                   "cc_local": "shell: human-wait contaminated (permissionMode not in the IR)",
                   "swechat/opencode": "shell: permission timing unknown",
                   "swechat/gemini": "shell: permission timing unknown"}
N6_ROW = {"n4": "N4", "n5c": "N5c_truncation", "n5g": "N5g_cold_start"}
NOT_TESTABLE_STAMPS = {"aiv_cu": "per-call intervals (aiv_cu stamps are shared or row-insert stamps: 0 distinct "
                                 "call/result stamps on A)",
                       "whowhen": "per-call intervals (whowhen has no event stamps)"}
CHUNK = 250
OPENED = []
LVL = {"ALIVE": 2, "WEAK": 1, "DEAD": 0}

# ---- thresholds: S:n4_concurrency / S:n5_battery (judgment calls fixed at pre-registration, PREREG_E section 9)
N4_MIN = (100, 10)          # pairs at k >= 2, sessions, in each population
N4_ARM = 30                 # tool_key enters Delta with >= 30 pairs in each arm
N4_DIFF = 0.10              # decades
N5C_MIN = (50, 10)          # marked results, sessions, per item
N5C_ALIVE_PT, N5C_ALIVE_LO, N5C_WEAK_PT = 0.99, 0.95, 0.90
N5C_CONST = {"cc_chars_mid": (TC_POOLED["cc_chars_mid"]["prefix_u16"], TC_POOLED["cc_chars_mid"]["suffix_u16"]),
             "cc_glob_cap": TC_POOLED["cc_glob_cap"]["lines"]}
N5C_ITEMS = ("cc_chars_mid", "cc_glob_cap", "cc_lines_tail")
N5C_RUN = tuple(i for i in N5C_ITEMS if TC_POOLED[i]["status"] == "OK")
N5G_MIN = 30
N5G_ALIVE_LO = math.log10(1.5)
N5G_ALIVE_SHARE = 0.05
PC_LONG_U16 = 10_004        # N5c positive control: real results long enough to hold both A constants' kept text
GLOB_MARKER_LINE = "(Results are truncated. Consider using a more specific path or pattern.)"

# ================================================================================================== deviations / choices
# Written before any N4 / N5c / N5g number was computed (the script was written, then run once). Exception: the
# entries "N4 minimum n and missing rule branches" and "AC4 'leave-out falls below min n'" were corrected after an
# independent re-derivation (corrections C1, C2; earlier text and values kept in the output's "corrections" block).
DEVIATIONS = [
    {"item": "output file names",
     "prereg_said": "prereg_e.json outputs 'N1-N5': phase_e_n<k>.py -> n<k>.json",
     "what_you_did": "analysis/probes/phase_e_n4_n5cg.py -> analysis/out/phase_e/n4_n5cg.json (the orchestrator's item "
                     "key n4_n5cg); N5 items a, b, d, e, f are in n5_battery.json (separate agent)",
     "why": "the N5 battery was split across agents; a distinct name avoids two agents writing n4.json / n5.json",
     "effect_on_verdict": "none"},
    {"item": "N4 in-flight population",
     "prereg_said": "S:n4_concurrency.in_flight: k_i = 1 + #{other calls j of the session (any thread) with call_ts_j <= "
                    "mid_i <= result_ts_j}. The A eligibility counts quoted in PREREG_E (C:latency_counts.n4, e.g. "
                    "swechat CC 9 W pairs at k >= 2) were computed by prereg_e_calibration.cal_latency_counts with "
                    "inflight_counts() called on the W (or G) subset only",
     "what_you_did": "verdict k = inflight_counts() on ALL pairs of the session (pc.make_pairs output, any thread, "
                     "qualified or not), as the JSON definition says; the calibration's within-set k is also computed "
                     "and reported (k_within_set) so the announced counts can be compared",
     "why": "the JSON wins over the markdown; the calibration call counted eligibility only",
     "effect_on_verdict": "the k >= 2 populations are larger than the announced A counts (see n4.<split>.W.k_hist vs "
                          "k_within_set_hist)"},
    {"item": "N4 nesting (decided before any N4 number was computed)",
     "prereg_said": "'any thread' in the in-flight definition",
     "what_you_did": "applied literally for the verdict: a call inside a subagent thread counts its parent subagent "
                     "pair as in flight, and a subagent pair counts its own nested calls. POST HOC, NOT A VERDICT: the "
                     "same statistic with k recomputed excluding ancestor/descendant pairs (parent_call_id chain), "
                     "reported as n4.<split>.post_hoc_not_a_verdict.k_excluding_nesting",
     "why": "a waiting parent pair does not contend for CPU, disk or network; reporting both lets the reader see "
            "whether k >= 2 measures concurrency or thread membership",
     "effect_on_verdict": "none (the verdict uses the literal k)"},
    {"item": "N4 Delta combination and bootstrap",
     "prereg_said": "pair-count-weighted mean over tool_keys with >= 30 pairs in each arm; session-bootstrap CI",
     "what_you_did": "weight of a tool_key = its pair count (k = 1 plus k >= 2); the qualifying tool_key set is fixed "
                     "on the point estimate; in a bootstrap draw a key with an empty arm is skipped and weights are the "
                     "draw's pair counts; boot_stat (seed 20261003, 1,000 draws, CI needs >= 900 valid draws)",
     "why": "the prereg does not say which count weights or how the key set behaves under resampling",
     "effect_on_verdict": "none expected"},
    {"item": "N4 minimum n and missing rule branches",
     "prereg_said": ">= 100 pairs at k >= 2 from >= 10 sessions in each population; ALIVE / WEAK / DEAD / "
                    "INSUFFICIENT_N rules",
     "what_you_did": "min n counted over the whole population (all W or all G pairs at k >= 2); additionally Delta is "
                     "undefined (-> INSUFFICIENT_N for that population) if no tool_key has >= 30 pairs in each arm. "
                     "Order: W below min n -> INSUFFICIENT_N; G below min n (W at min n) -> the W-only test: WEAK if "
                     "the Delta_W CI excludes 0, else DEAD; a needed CI with < 900 valid draws -> INCONCLUSIVE; CIs "
                     "disjoint and |Delta_W - Delta_G| >= 0.10 -> ALIVE; disjoint -> WEAK; overlap -> DEAD. The "
                     "contributing k >= 2 counts (pairs in qualifying keys) are reported next to the population counts. "
                     "CORRECTED (C1, see 'corrections'): the first version of this entry assigned INSUFFICIENT_N to "
                     "'G below min n and Delta_W CI covers 0'",
     "why": "the rule list leaves 'G below min n and Delta_W CI covers 0' unassigned. The WEAK branch ('Delta_W CI "
            "excludes 0 with G below min n'; PREREG_E: 'Delta_W != 0 without a G control') makes W alone a testable "
            "population, and PREREG_E section 5 calls codex testable although it has no G control. INSUFFICIENT_N is "
            "'below min n', and W is not below it; the W-only analogue of 'CIs overlap' is a Delta_W CI that covers "
            "the comparator 0, so the null outcome is DEAD. This is also the reading that can only lower a label",
     "effect_on_verdict": "DEAD rather than INSUFFICIENT_N where W meets min n, G is below it and Delta_W covers 0 "
                          "(base cells, artifact-check recomputes, AC4 leave-outs and strata); see 'corrections'"},
    {"item": "AC4 'leave-out falls below min n' (correction C2)",
     "prereg_said": "AC4: DOMINATED if any leave-out drops the label (one-level downgrade); if a leave-out falls below "
                    "min n: capped at WEAK (UNTESTABLE_WITHOUT_DOMINANT)",
     "what_you_did": "a leave-out falls below min n when its own counts fail the item's min n (N4: W k >= 2 pairs or "
                     "sessions below 100 / 10 or Delta_W undefined; or G below min n where the base cell's G met it; "
                     "N5c / N5g: the INSUFFICIENT_N label, which only min n produces). Such a leave-out caps at WEAK. "
                     "Every other leave-out is compared on levels: lower than the base label -> DOMINATED. Both can "
                     "hold; the downgrade is applied, then the cap. CORRECTED: the first version treated every "
                     "INSUFFICIENT_N leave-out label as 'below min n', including N4 leave-outs whose W met min n",
     "why": "the prereg reserves UNTESTABLE_WITHOUT_DOMINANT for a leave-out below min n; in swechat/codex N4 G was 0 "
            "in the base cell too, so dropping a cluster did not remove a population the base cell had",
     "effect_on_verdict": "see 'corrections' (swechat/codex N4 AC4: UNTESTABLE_WITHOUT_DOMINANT -> DOMINATED)"},
    {"item": "N4 G latency",
     "prereg_said": "G = Phase B generation-bound pairs with tool-reported durations",
     "what_you_did": "Phase B G set and latency exactly (prereg_calibration.g_latency, probe_1.py exclusions): CC "
                     "formats use durationMs / durationSeconds / totalDurationMs (subagent falls back to the stamp "
                     "delta; aiv_cc webfetch/websearch too); outside CC formats g_latency is the stamp delta. The "
                     "latency source is counted per population (G.latency_source)",
     "why": "the prereg names Phase B's G set", "effect_on_verdict": "none"},
    {"item": "N5c exactness CI and zero-numerator rule",
     "prereg_said": "exactness >= 0.99 with CI lo >= 0.95 (ALIVE); global: zero numerators use the per-event Wilson "
                    "upper bound for verdicts",
     "what_you_did": "exactness = 1 - inexact rate; inexact rate by cluster_rate (rate_by_session); CI lo of exactness "
                     "= 1 - CI hi of the inexact rate, and when 0 marked results are inexact, 1 - the per-event Wilson "
                     "upper bound",
     "why": "the global zero-numerator rule applied to the complement", "effect_on_verdict": "applied where every "
                                                                                              "marked result is exact"},
    {"item": "N5c item cell",
     "prereg_said": "three sub-items (cc_chars_mid, cc_lines_tail, cc_glob_cap) with their own min n and verdict; one "
                    "N6 row N5c_truncation; no combination rule",
     "what_you_did": "each runnable sub-item gets its own verdict, cell and checks; the N6 cell is the LOWEST final "
                     "label among sub-items with an ALIVE/WEAK/DEAD cell (INSUFFICIENT_N if none); cc_lines_tail is "
                     "NOT_RUN (A constant INSUFFICIENT_N) and does not enter the combination; its B/E counts are "
                     "reported",
     "why": "same rule as n5_battery.json (multi-checker items): cannot raise a label",
     "effect_on_verdict": "the cell can only be lower than its best sub-item"},
    {"item": "N5c positive control",
     "prereg_said": "a long real result re-truncated at a uniform random length with the marker appended",
     "what_you_did": "cc_chars_mid: every paired result that is not truncated_result() and has >= 10,004 UTF-16 units "
                     "(enough for both A constants' kept text); with rng_for('N5cpc', session_id, call_id, item) a kept "
                     "prefix a ~ U{0..L} and suffix b ~ U{0..L-a} chars, rebuilt as text[:a] + '\\n\\n... [L-a-b "
                     "characters truncated] ...\\n\\n' + text[L-b:] (the separator layout behind the raw 5,002 = 5,000 "
                     "+ 2); cc_glob_cap: every non-truncated glob result with >= 2 non-blank lines, first n ~ U{1..N-1} "
                     "lines kept and the Glob marker line appended. Flagged = truncation_info() of the rebuilt text "
                     "is not exact",
     "why": "'long' and the cut layout are not fixed by the prereg; the mid-text marker needs two lengths",
     "effect_on_verdict": "none: positive-control recall is reported, it is not a verdict input"},
    {"item": "N5c AC2 (truncation)",
     "prereg_said": "AC2: recompute without results matching truncated_result()",
     "what_you_did": "NOT_RUN for N5c: every marked result matches truncated_result() by definition, so the AC2 "
                     "population is empty",
     "why": "the check is undefined for a statistic computed on truncated results only",
     "effect_on_verdict": "none"},
    {"item": "N5g statistic details",
     "prereg_said": "pooled median c (cluster_quantile) and share(c_s <= 0); ALIVE: median c CI lo >= log10 1.5 and "
                    "share(c_s <= 0) <= 0.05; WEAK: median c CI lo > 0; min n >= 30 sessions",
     "what_you_did": "one c_s per eligible session (cold_start_values on qualify_pairs(...)[qualified]); median and CI "
                     "by stats.cluster_quantile(q = 0.5) over sessions; share(c_s <= 0) by Wilson (global: Wilson for "
                     "session shares), the ALIVE rule uses its point estimate",
     "why": "as written", "effect_on_verdict": "none"},
    {"item": "N5g positive control",
     "prereg_said": "first call's delta replaced by a later call's delta (no cold start) -> recall; seeds "
                    "rng_for('<item>pc', session_id, key)",
     "what_you_did": "the later call is drawn uniformly from the session's later calls of its top tool with "
                     "rng_for('N5gpc', session_id, tool_key); c'_s = log10 delta(drawn) - median log10 delta(later "
                     "calls, unchanged); recall = share of sessions with c'_s <= 0 (the detector's flag rule), Wilson",
     "why": "the later-call set is left as it was so only the first call changes",
     "effect_on_verdict": "none: recall is reported, not a verdict input"},
    {"item": "field gate",
     "prereg_said": "N6 fill rule: NOT_TESTABLE iff a required field is absent (N4: per-call intervals; N5c: result "
                    "text with harness truncation markers; N5g: per-call stamps); PREREG_E section 2: aiv_cu and whowhen "
                    "are NOT_TESTABLE for N4 and N5g",
     "what_you_did": "N4 / N5g run on the six S:n4_concurrency units; aiv_cu, whowhen NOT_TESTABLE as stated (the B/E "
                     "count of pairs with distinct stamps is reported); units with 0 sessions in B and E (copilot, "
                     "simple_text) NOT_TESTABLE(no sessions in B or E), as n5_battery.json; cursor (no call/result "
                     "pairs) NOT_TESTABLE(no call/result pairs). N5c: a unit with 0 results carrying any of the three "
                     "Claude Code markers on B and E is NOT_TESTABLE(no harness truncation markers)",
     "why": "re-check on B as the fill rule requires", "effect_on_verdict": "NOT_TESTABLE instead of INSUFFICIENT_N "
                                                                            "where the field is absent"},
    {"item": "artifact-check recompute with a non-level label",
     "prereg_said": "AC2 / AC3 / AC5: FAIL if the label changes; the candidate takes the lower label",
     "what_you_did": "a recompute that lands on INSUFFICIENT_N or INCONCLUSIVE is stored with fail = true but does not "
                     "change the cell (it is not on the ALIVE > WEAK > DEAD scale), as in phase_e_n5_battery.py; the "
                     "notes state per cell what the stricter reading (cell -> the non-level label) would give. After "
                     "correction C1 an N4 recompute is INSUFFICIENT_N only when its W population is below min n",
     "why": "'lower label' is defined on levels only; same convention as the sibling N5 battery output",
     "effect_on_verdict": "see cells.*.checks_applied entries 'label ... on the recompute (not a level; no change)'"},
    {"item": "artifact checks (applied only to cells at WEAK or better on B or E)",
     "prereg_said": "S:artifact_checks AC1-AC5, S:stratification",
     "what_you_did": "population B u E. AC1: audit_sample() of 30 numerator events (N4: W pairs at k >= 2; N5c: "
                     "inexact marked results; N5g: flagged sessions c_s <= 0), looked up in the raw source with "
                     "phase_e_n1.raw_lookup (Claude Code formats only; else NOT_RUN; for aiv_cc the gz lines are "
                     "pre-filtered by 'toolu_' id extraction instead of n1's per-target substring scan, same rows and "
                     "parser, see raw_lookup()); an event differs if not found or "
                     "its contribution changes (N4: |delta| change > 1 ms or the k >= 2 arm changes when k is "
                     "recomputed from the raw stamps of every pair of the session; N5c: exactness of the raw text; N5g: "
                     "the flag recomputed from raw stamps of the session's top-tool calls); FAIL = one-level "
                     "downgrade. AC2: recompute without truncated results (N4: W/G pairs; N5g: cold_start_values on "
                     "qualified pairs without truncated results). AC3: join_clean_mask() pairs only (copied ids over "
                     "the corpus's B and E caches). AC4: dominance over the item's denominator per session (N4: W "
                     "pairs; N5c: marked results; N5g: sessions), leave-outs recompute the full verdict; aiv_cc "
                     "single-cluster kinds labelled only. AC5: post_strat_weights over contributing sessions (N4: "
                     "weighted medians; N5c: weighted_cluster_rate; N5g: weighted median and share, session "
                     "bootstrap). Strata: tool_key (N4: per W key against the full G; N5c: key of the marked result; "
                     "N5g: the session's top tool), modal model, repo, length tercile of paired calls (A cuts)",
     "why": "smallest faithful reading, matching phase_e_n1.py and phase_e_n5_battery.py",
     "effect_on_verdict": "listed per cell under checks_applied"},
]


# ================================================================================================== loading
def unit_chunks():
    """(corpus, unit, split, frame | None, n_sessions_in_split, chunk_index); <= CHUNK sessions per frame."""
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
def nested_bad_set(unit, u):
    """Subagent pairs excluded from G (probe_1.py nested_bad_set / prereg_calibration.probe1_unit, verbatim logic)."""
    nested_bad = set()
    if unit in ("swechat/claude_code", "cc_local"):
        nn = u[u.parent_call_id.notna() & u.kind.isin(["result", "call"])]
        for s, pcid, kind, txt, tl in zip(nn.session_id, nn.parent_call_id.astype(str), nn.kind, nn.text.astype(object),
                                          nn.tool.astype(object)):
            if kind == "result" and error_marker(txt if isinstance(txt, str) else "") in ("cc_permission_denied",
                                                                                          "cc_interrupt_reject"):
                nested_bad.add((s, pcid))
            if kind == "call" and pc.tool_class(tl if isinstance(tl, str) else "") == "human_interactive":
                nested_bad.add((s, pcid))
    return nested_bad


def inflight_nonest(P):
    """POST HOC (not a verdict): k as inflight_counts() but not counting ancestor or descendant pairs (parent_call_id
    chain within the session). Also returns whether an ancestor pair is in flight at the midpoint."""
    c_all, r_all = pe._ms(P.ts), pe._ms(P.ts_r)
    k = np.ones(len(P), dtype=int)
    anc_in = np.zeros(len(P), dtype=bool)
    cid_all = P.call_id.astype(str).to_numpy()
    par_all = P.parent_call_id.astype(object).to_numpy() if "parent_call_id" in P else np.array([None] * len(P))
    for _, idx in P.groupby("session_id", sort=False).indices.items():
        c, r = c_all[idx], r_all[idx]
        cids = cid_all[idx]
        pmap = {a: str(b) for a, b in zip(cids, par_all[idx]) if isinstance(b, str) and b}
        anc = []
        for x in cids:
            s, cur = set(), x
            for _ in range(50):
                p = pmap.get(cur)
                if p is None or p in s:
                    break
                s.add(p)
                cur = p
            anc.append(s)
        mid = (c + r) / 2
        for j in range(len(idx)):
            if not (np.isfinite(c[j]) and np.isfinite(r[j])):
                continue
            inf = (c <= mid[j]) & (mid[j] <= r)
            inf[j] = False
            js = np.nonzero(inf)[0]
            if not pmap:
                k[idx[j]] = 1 + len(js)
                continue
            cnt = 0
            for q in js:
                if cids[q] in anc[j]:
                    anc_in[idx[j]] = True
                    continue
                if cids[j] in anc[q]:
                    continue
                cnt += 1
            k[idx[j]] = 1 + cnt
    return k, anc_in


def _u16(t):
    return pe.utf16_len(t) if isinstance(t, str) else 0


def extract(unit, split, u, copied):
    """One chunk of one unit x split -> compact record frames (no text kept)."""
    u = u.reset_index(drop=True)
    rec = {}
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])]).reset_index(drop=True)
    model = pe.session_model_map(u)
    ps = pd.DataFrame({"session_id": sorted(u.session_id.unique())})
    gate = Counter()
    if not len(P):
        ps["pairs"] = 0
        return rec, ps, gate, model
    P["key"] = [pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    if unit == "cc_local":
        P["key"] = [pc.private_key(k) for k in P.key]
    P["join_clean"] = pe.join_clean_mask(u, P, copied)
    P["call_id"] = P.call_id.astype(str)
    txt = P.text_r.astype(object).tolist()
    P["trunc"] = [pe.truncated_result(t, x) for t, x in zip(txt, P.extra_r.astype(object))]
    ps = P.groupby("session_id").size().rename("pairs").reindex(ps.session_id, fill_value=0).rename_axis(
        "session_id").reset_index()
    d = P.delta_s.to_numpy(dtype=float)
    gate["pairs"] += int(len(P))
    gate["pairs_stamped"] += int(np.isfinite(d).sum())
    gate["pairs_positive_delta"] += int((np.isfinite(d) & (d > 0)).sum())
    gate["truncated_results"] += int(P.trunc.sum())
    gate["join_unclean_pairs"] += int((~P.join_clean).sum())
    gate["results_with_text"] += int(sum(isinstance(t, str) for t in txt))

    # ------------------------------------------------------------------------------------------ N5c (every unit)
    trows, pcrows = [], []
    for i, (sid, cid, q, k, t, jc, tr) in enumerate(zip(P.session_id, P.call_id, P.seq, P.key, txt, P.join_clean,
                                                         P.trunc)):
        if not isinstance(t, str):
            continue
        ti = pe.truncation_info(t)
        if ti:
            row = {"session_id": sid, "call_id": cid, "seq": int(q), "item": ti["item"], "key": k,
                   "join_clean": bool(jc), "stated": ti.get("stated")}
            if ti["item"] == "cc_chars_mid":
                pre, suf = N5C_CONST["cc_chars_mid"]
                row.update({"prefix_u16": ti["prefix_u16"], "suffix_u16": ti["suffix_u16"],
                            "prefix_u16_stripped": ti["prefix_u16_stripped"],
                            "suffix_u16_stripped": ti["suffix_u16_stripped"],
                            "exact": bool(ti["prefix_u16"] == pre and ti["suffix_u16"] == suf)})
            elif ti["item"] == "cc_glob_cap":
                row.update({"lines": ti["lines"], "exact": bool(ti["lines"] == N5C_CONST["cc_glob_cap"])})
            else:
                row.update({"prefix_raw": ti["prefix_raw"], "prefix_chars": ti["prefix_chars"], "exact": None})
            trows.append(row)
            continue
        if tr:
            continue
        # positive-control candidates (not truncated)
        if len(t) >= PC_LONG_U16 // 2 and _u16(t) >= PC_LONG_U16:
            L = len(t)
            g = pe.rng_for("N5cpc", sid, cid, "cc_chars_mid")
            a = int(g.integers(0, L + 1))
            b = int(g.integers(0, L - a + 1))
            t2 = t[:a] + f"\n\n... [{L - a - b} characters truncated] ...\n\n" + t[L - b:]
            ti2 = pe.truncation_info(t2)
            ok = bool(ti2 and ti2["item"] == "cc_chars_mid")
            ex = bool(ok and (ti2["prefix_u16"], ti2["suffix_u16"]) == N5C_CONST["cc_chars_mid"])
            pcrows.append({"session_id": sid, "call_id": cid, "item": "cc_chars_mid", "key": k,
                           "pc_eligible": ok, "pc_flag": bool(ok and not ex)})
        if k == "glob":
            lines = [ln for ln in t.splitlines() if ln.strip()]
            if len(lines) >= 2:
                g = pe.rng_for("N5cpc", sid, cid, "cc_glob_cap")
                n = int(g.integers(1, len(lines)))
                t2 = "\n".join(lines[:n]) + "\n" + GLOB_MARKER_LINE
                ti2 = pe.truncation_info(t2)
                ok = bool(ti2 and ti2["item"] == "cc_glob_cap")
                pcrows.append({"session_id": sid, "call_id": cid, "item": "cc_glob_cap", "key": k,
                               "pc_eligible": ok, "pc_flag": bool(ok and ti2["lines"] != N5C_CONST["cc_glob_cap"])})
    rec["tr"] = pd.DataFrame(trows)
    rec["pc5c"] = pd.DataFrame(pcrows)
    gate["marked_results"] += len(trows)
    for r in trows:
        gate[f"marked_{r['item']}"] += 1
    gate["glob_results"] += int((P.key == "glob").sum())

    if unit not in LAT_UNITS:
        return rec, ps, gate, model

    # ------------------------------------------------------------------------------------------ N4
    k_all = pe.inflight_counts(P)
    k_nn, anc_in = inflight_nonest(P)
    PB = pcal.p1_qualified(unit, u, P)
    assert (PB.index == P.index).all()
    if unit in pcal.W_KEYS:
        wm = PB.qualified.to_numpy() & (PB.delta_s.to_numpy() > 0) & PB.key.isin(pcal.W_KEYS[unit]).to_numpy()
    else:
        wm = PB.qualified.to_numpy() & (PB.delta_s.to_numpy() > 0) & (PB.cls == "auto_read").to_numpy()
    subthr = P.is_subagent.astype("boolean").fillna(False).astype(bool).to_numpy()
    W = P[wm]
    kw_within = pe.inflight_counts(W) if len(W) else np.array([], dtype=int)
    rec["W"] = pd.DataFrame({"session_id": W.session_id.to_numpy(), "call_id": W.call_id.to_numpy(),
                             "seq": W.seq.to_numpy(), "key": W.key.to_numpy(),
                             "delta_s": W.delta_s.to_numpy(float), "lg": np.log10(W.delta_s.to_numpy(float)),
                             "k": k_all[wm], "k_nonest": k_nn[wm], "k_within": kw_within, "anc_inflight": anc_in[wm],
                             "sub_thread": subthr[wm], "trunc": P.trunc.to_numpy()[wm],
                             "join_clean": P.join_clean.to_numpy()[wm]})
    nb = nested_bad_set(unit, u)
    gidx, glat, gsrc = [], [], []
    gex = Counter()
    G_T = pcal.G_TOOLS.get(unit, set())
    for i, (k, dd, x, s, cid, mk) in enumerate(zip(PB.key, PB.delta_s, PB._rx, PB.session_id, PB.call_id.astype(str),
                                                   PB.marker)):
        if k not in G_T:
            continue
        if mk in ("cc_permission_denied", "cc_interrupt_reject"):
            gex["reject_marker"] += 1
            continue
        if (s, cid) in nb:
            gex["nested_human_marker_or_interactive"] += 1
            continue
        lat = pcal.g_latency(unit, k, dd, x)
        if lat is None:
            gex["no_tool_reported_duration"] += 1
            continue
        if not np.isfinite(lat) or lat <= 0:
            gex["nonpositive_or_missing_latency"] += 1
            continue
        tool_rep = unit in pc.CC_FORMAT_UNITS and any(isinstance(x.get(f), (int, float)) for f in
                                                      ("durationMs", "durationSeconds", "totalDurationMs"))
        gidx.append(i), glat.append(float(lat)), gsrc.append("tool_reported" if tool_rep else "stamp_delta")
    gm = np.zeros(len(P), dtype=bool)
    gm[gidx] = True
    G = P.iloc[gidx]
    kg_within = pe.inflight_counts(G) if len(G) else np.array([], dtype=int)
    rec["G"] = pd.DataFrame({"session_id": G.session_id.to_numpy(), "call_id": G.call_id.to_numpy(),
                             "seq": G.seq.to_numpy(), "key": G.key.to_numpy(), "lat_s": np.array(glat, float),
                             "lg": np.log10(np.array(glat, float)), "delta_s": G.delta_s.to_numpy(float),
                             "lat_source": np.array(gsrc, dtype=object),
                             "k": k_all[gidx] if len(gidx) else np.array([], int),
                             "k_nonest": k_nn[gidx] if len(gidx) else np.array([], int), "k_within": kg_within,
                             "anc_inflight": anc_in[gidx] if len(gidx) else np.array([], bool),
                             "sub_thread": subthr[gidx] if len(gidx) else np.array([], bool),
                             "trunc": P.trunc.to_numpy()[gidx] if len(gidx) else np.array([], bool),
                             "join_clean": P.join_clean.to_numpy()[gidx] if len(gidx) else np.array([], bool)})
    rec["G_excl"] = gex
    fin = np.isfinite(pe._ms(P.ts)) & np.isfinite(pe._ms(P.ts_r))
    rec["k_all_hist"] = Counter(int(x) for x in k_all[fin])
    rec["k_all_nonest_hist"] = Counter(int(x) for x in k_nn[fin])

    # ------------------------------------------------------------------------------------------ N5g
    Q = pe.qualify_pairs(unit, u, P)
    Qq = Q[Q.qualified]
    cs = pe.cold_start_values(Qq)
    cs_nt = pe.cold_start_values(Qq[~Qq.trunc.astype(bool)])
    cs_jc = pe.cold_start_values(Qq[Qq.join_clean.astype(bool)])
    byc = {s: (t, c) for s, t, c in cs}
    rows = []
    for sid, g in Qq.sort_values(["session_id", "seq"]).groupby("session_id", sort=False):
        if not len(g):
            continue
        t = g.key.value_counts().index[0]
        h = g[g.key == t]
        if len(h) < 6:
            continue
        lg = np.log10(h.delta_s.to_numpy(float))
        c = float(lg[0] - np.median(lg[1:]))
        assert byc[sid][0] == t and abs(byc[sid][1] - c) < 1e-12
        j = int(pe.rng_for("N5gpc", sid, t).integers(1, len(h)))
        cpc = float(lg[j] - np.median(lg[1:]))
        rows.append({"session_id": sid, "tool": t, "cls": str(h.cls.iloc[0]), "c": c, "flag": bool(c <= 0),
                     "c_pc": cpc, "pc_flag": bool(cpc <= 0), "n_t": int(len(h)),
                     "first_delta_s": float(h.delta_s.iloc[0]), "later_median_delta_s": float(10 ** np.median(lg[1:])),
                     "first_is_session_first_qualified": bool(h.seq.iloc[0] == g.seq.iloc[0]),
                     "first_sub_thread": bool(pd.Series([h.is_subagent.iloc[0]]).astype("boolean").fillna(False)
                                              .astype(bool).iloc[0]),
                     "first_trunc": bool(h.trunc.iloc[0]), "first_join_clean": bool(h.join_clean.iloc[0]),
                     "t_call_ids": "\x1f".join(h.call_id.astype(str).tolist())})
    rec["cs"] = pd.DataFrame(rows)
    rec["cs_nt"] = pd.DataFrame(cs_nt, columns=["session_id", "tool", "c"])
    rec["cs_jc"] = pd.DataFrame(cs_jc, columns=["session_id", "tool", "c"])
    gate["qualified_pairs_n5g"] += int(len(Qq))
    return rec, ps, gate, model


# ================================================================================================== statistics: N4
def _wmedian(v, w):
    o = np.argsort(v, kind="mergesort")
    v, w = v[o], w[o]
    c = np.cumsum(w) - 0.5 * w
    c = c / w.sum()
    return float(np.interp(0.5, c, v))


def n4_keys(df, kcol="k"):
    if not len(df):
        return []
    g = df.assign(_hi=df[kcol] >= 2).groupby(["key", "_hi"]).size().unstack(fill_value=0)
    if True not in g.columns or False not in g.columns:
        return []
    return sorted(g[(g[True] >= N4_ARM) & (g[False] >= N4_ARM)].index)


def n4_delta_value(key, hi, lg, w, keys):
    """Pair-count-weighted mean over `keys` of median(lg | k >= 2) - median(lg | k = 1); w = per-row weights or None."""
    num, den = 0.0, 0.0
    for kk in keys:
        m = key == kk
        a, b = m & ~hi, m & hi
        if not a.any() or not b.any():
            continue
        if w is None:
            d = float(np.median(lg[b]) - np.median(lg[a]))
            wt = float(m.sum())
        else:
            d = _wmedian(lg[b], w[b]) - _wmedian(lg[a], w[a])
            wt = float(w[m].sum())
        num += wt * d
        den += wt
    return num / den if den > 0 else None


def n4_delta(df, kcol="k", sw=None):
    """Delta with session-bootstrap CI (boot_stat). sw: {session: weight} for AC5."""
    keys = n4_keys(df, kcol)
    out = {"keys": keys, "value": None, "valid_draws": 0, "ci_reported": False, "n_sessions": 0}
    if not keys:
        return out
    groups = []
    for s, g in df.groupby("session_id", sort=True):
        ww = None if sw is None else np.full(len(g), float(sw.get(s, 0.0)))
        groups.append((g.key.to_numpy(object), (g[kcol] >= 2).to_numpy(), g.lg.to_numpy(float), ww))

    def fn(gs):
        if not gs:
            return None
        key = np.concatenate([x[0] for x in gs])
        hi = np.concatenate([x[1] for x in gs])
        lg = np.concatenate([x[2] for x in gs])
        w = None if sw is None else np.concatenate([x[3] for x in gs])
        if w is not None and w.sum() <= 0:
            return None
        return n4_delta_value(key, hi, lg, w, keys)
    b = pe.boot_stat(groups, fn)
    b["keys"] = keys
    return b


def n4_pop(df, kcol="k", sw=None, detail=True, boot=True):
    """One population (W or G): counts, k distribution, per-key arms, Delta."""
    out = {"pairs": int(len(df)), "sessions": int(df.session_id.nunique()) if len(df) else 0}
    if not len(df):
        out.update({"k_ge_2": 0, "k_ge_2_sessions": 0, "delta": {"value": None, "keys": []}})
        return out
    hi = df[kcol] >= 2
    out["k_ge_2"] = int(hi.sum())
    out["k_ge_2_sessions"] = int(df[hi].session_id.nunique())
    if boot:
        d = n4_delta(df, kcol, sw)
    else:  # sub-population already below the W minimum n: the label is INSUFFICIENT_N whatever the CI (no bootstrap)
        keys = n4_keys(df, kcol)
        d = {"keys": keys, "valid_draws": 0, "ci_reported": False, "skipped": "W below min n (label fixed)",
             "value": (n4_delta_value(df.key.to_numpy(object), (df[kcol] >= 2).to_numpy(), df.lg.to_numpy(float),
                                      None, keys) if (keys and sw is None) else None)}
    out["delta"] = d
    keys = d.get("keys", [])
    con = df[df.key.isin(keys)]
    out["contributing"] = {"pairs": int(len(con)), "k_ge_2": int((con[kcol] >= 2).sum()),
                           "k_ge_2_sessions": int(con[con[kcol] >= 2].session_id.nunique()),
                           "sessions": int(con.session_id.nunique())}
    if detail and sw is None:
        out["k_hist"] = {str(k): int(v) for k, v in sorted(Counter(df[kcol].astype(int)).items())}
        out["share_k_ge_4"] = pe.rate_by_session((df[kcol] >= 4).to_numpy(), df.session_id.to_numpy())
        pk = {}
        for kk, g in df.groupby("key"):
            h = g[kcol] >= 2
            rec = {"n_k1": int((~h).sum()), "n_k2plus": int(h.sum()), "sessions": int(g.session_id.nunique()),
                   "sessions_k2plus": int(g[h].session_id.nunique()), "in_delta": kk in keys}
            for nm, m in (("k1", ~h), ("k2plus", h)):
                if m.any():
                    v = g.delta_s.to_numpy(float)[m.to_numpy()] if "lat_s" not in g else g.lat_s.to_numpy(float)[m.to_numpy()]
                    rec[f"{nm}_seconds_q"] = {f"q{q:g}": float(np.quantile(v, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
            if (~h).any() and h.any():
                rec["median_log10_diff"] = float(np.median(g.lg[h]) - np.median(g.lg[~h]))
            pk[kk] = rec
        out["by_key"] = pk
    return out


def n4_verdict(Wb, Gb, path):
    wn, ws = Wb["k_ge_2"], Wb["k_ge_2_sessions"]
    gn, gs = Gb["k_ge_2"], Gb["k_ge_2_sessions"]
    dw, dg = Wb["delta"], Gb["delta"]
    w_ok = wn >= N4_MIN[0] and ws >= N4_MIN[1] and dw.get("value") is not None
    g_ok = gn >= N4_MIN[0] and gs >= N4_MIN[1] and dg.get("value") is not None
    mn = {"W_k_ge_2": wn, "W_k_ge_2_sessions": ws, "W_delta_defined": dw.get("value") is not None,
          "G_k_ge_2": gn, "G_k_ge_2_sessions": gs, "G_delta_defined": dg.get("value") is not None}
    mp = [f"{path}.W.k_ge_2", f"{path}.W.k_ge_2_sessions", f"{path}.G.k_ge_2", f"{path}.G.k_ge_2_sessions"]
    if not w_ok:
        return {"label": "INSUFFICIENT_N", "rule": f"W below min n (>= {N4_MIN[0]} pairs at k >= 2 from >= {N4_MIN[1]} "
                                                    f"sessions, and a tool_key with >= {N4_ARM} pairs in each arm)",
                "deciding_number": mn, "deciding_path": mp}
    if not dw.get("ci_reported"):
        return {"label": "INCONCLUSIVE", "rule": "Delta_W CI has < 900 valid bootstrap draws",
                "deciding_number": {"valid_draws": dw.get("valid_draws")}, "deciding_path": f"{path}.W.delta.valid_draws"}
    excl0 = dw["lo"] > 0 or dw["hi"] < 0
    if not g_ok:
        if excl0:
            return {"label": "WEAK", "rule": "Delta_W CI excludes 0 with G below min n",
                    "deciding_number": {"delta_W": dw["value"], "ci": [dw["lo"], dw["hi"]], **mn},
                    "deciding_path": [f"{path}.W.delta.value", f"{path}.W.delta.lo", f"{path}.W.delta.hi"] + mp}
        # correction C1: W meets min n, so this is the W-only test the WEAK branch defines ("Delta_W != 0 without a G
        # control"); its null outcome is DEAD (CI overlaps the comparator 0), not INSUFFICIENT_N (W is not below min n)
        return {"label": "DEAD", "rule": "G below min n (no G control) and Delta_W CI includes 0: W-only test, W at min "
                                         "n, Delta_W not distinguishable from 0 (correction C1; was INSUFFICIENT_N)",
                "deciding_number": {"delta_W": dw["value"], "ci": [dw["lo"], dw["hi"]], **mn},
                "deciding_path": [f"{path}.W.delta.value", f"{path}.W.delta.lo", f"{path}.W.delta.hi"] + mp}
    if not dg.get("ci_reported"):
        return {"label": "INCONCLUSIVE", "rule": "Delta_G CI has < 900 valid bootstrap draws",
                "deciding_number": {"valid_draws": dg.get("valid_draws")}, "deciding_path": f"{path}.G.delta.valid_draws"}
    disjoint = dw["hi"] < dg["lo"] or dg["hi"] < dw["lo"]
    diff = dw["value"] - dg["value"]
    dn = {"delta_W": dw["value"], "ci_W": [dw["lo"], dw["hi"]], "delta_G": dg["value"], "ci_G": [dg["lo"], dg["hi"]],
          "diff": diff}
    dp = [f"{path}.W.delta.value", f"{path}.W.delta.lo", f"{path}.W.delta.hi", f"{path}.G.delta.value",
          f"{path}.G.delta.lo", f"{path}.G.delta.hi"]
    if disjoint and abs(diff) >= N4_DIFF:
        return {"label": "ALIVE", "rule": f"CIs disjoint and |Delta_W - Delta_G| >= {N4_DIFF}", "deciding_number": dn,
                "deciding_path": dp}
    if disjoint:
        return {"label": "WEAK", "rule": f"CIs disjoint, |Delta_W - Delta_G| < {N4_DIFF}", "deciding_number": dn,
                "deciding_path": dp}
    return {"label": "DEAD", "rule": "Delta_W and Delta_G CIs overlap", "deciding_number": dn, "deciding_path": dp}


def n4_block(Wd, Gd, path, kcol="k", sw=None, detail=True):
    boot = True
    if not detail and len(Wd):
        h = Wd[kcol] >= 2
        boot = bool(h.sum() >= N4_MIN[0] and Wd[h].session_id.nunique() >= N4_MIN[1])
    elif not detail:
        boot = False
    out = {"W": n4_pop(Wd, kcol, sw, detail, boot), "G": n4_pop(Gd, kcol, sw, detail, boot)}
    if detail and sw is None and kcol == "k":
        out["W"]["k_within_set_hist"] = {str(k): int(v) for k, v in sorted(Counter(Wd.k_within.astype(int)).items())} \
            if len(Wd) else {}
        out["G"]["k_within_set_hist"] = {str(k): int(v) for k, v in sorted(Counter(Gd.k_within.astype(int)).items())} \
            if len(Gd) else {}
        if len(Gd):
            out["G"]["latency_source"] = dict(Counter(Gd.lat_source))
            out["G"]["by_key_latency_source"] = {k: dict(Counter(g.lat_source)) for k, g in Gd.groupby("key")}
        for nm, D in (("W", Wd), ("G", Gd)):
            if len(D):
                h = D.k >= 2
                out[nm]["k_ge_2_composition"] = {
                    "in_subagent_thread": int((h & D.sub_thread).sum()),
                    "ancestor_pair_in_flight": int((h & D.anc_inflight).sum()),
                    "k_ge_2_without_nesting (k_nonest >= 2)": int((D.k_nonest >= 2).sum())}
    out["verdict"] = n4_verdict(out["W"], out["G"], path)
    return out


# ================================================================================================== statistics: N5c
def n5c_block(T, PCd, item, path, w=None, detail=True):
    df = T[T.item == item] if len(T) else T
    out = {"marked": int(len(df)), "sessions": int(df.session_id.nunique()) if len(df) else 0}
    if item == "cc_lines_tail":
        if len(df) and detail:
            out["by_key"] = {k: {"n": int(len(g)), "prefix_raw_mode": [[int(a), int(b)] for a, b in
                                                                        Counter(g.prefix_raw).most_common(3)]}
                             for k, g in df.groupby("key")}
        out["verdict"] = {"label": "NOT_RUN", "rule": "A constant INSUFFICIENT_N (n_A 4 < 5): item NOT_RUN "
                                                      "(S:n5_battery.c_truncation_boundary.constants_rule)",
                          "deciding_number": TC_POOLED["cc_lines_tail"]["n_A"],
                          "deciding_path": "prereg_e.json resolved.n5.truncation_constants_pooled.cc_lines_tail.n_A"}
        return out
    if not len(df):
        r = {"rate": None, "num": 0, "den": 0, "n_sessions": 0}
    elif w is None:
        r = pe.rate_by_session((~df.exact.astype(bool)).to_numpy(), df.session_id.to_numpy())
    else:
        g = df.assign(_x=~df.exact.astype(bool)).groupby("session_id")._x.agg(["sum", "size"])
        r = pe.weighted_cluster_rate(g["sum"].to_numpy(), g["size"].to_numpy(), [w.get(s, 0.0) for s in g.index])
        r["num"], r["den"], r["n_sessions"] = float(g["sum"].sum()), float(g["size"].sum()), int(len(g))
        if r["num"] == 0:
            r["wilson_hi_per_event"] = stats.wilson(0, int(r["den"]))[2]
            r["wilson_hi_per_session"] = stats.wilson(0, int(r["n_sessions"]))[2]
    out["inexact_rate"] = r
    if r.get("rate") is not None:
        zero = r.get("num", 0) == 0 and "wilson_hi_per_event" in r
        out["exactness"] = 1 - r["rate"]
        out["exactness_ci_lo"] = 1 - (r["wilson_hi_per_event"] if zero else r["hi"])
        out["exactness_ci_lo_source"] = ("1 - inexact_rate.wilson_hi_per_event (zero numerator)" if zero
                                         else "1 - inexact_rate.hi")
        out["exactness_ci_hi"] = 1 - r["lo"] if r.get("lo") is not None else None
    if detail and w is None and len(df):
        if item == "cc_chars_mid":
            out["prefix_suffix_u16_top"] = [[int(a), int(b), int(c)] for (a, b), c in
                                            Counter(zip(df.prefix_u16, df.suffix_u16)).most_common(10)]
            out["prefix_suffix_u16_stripped_top (diagnostic)"] = [
                [int(a), int(b), int(c)] for (a, b), c in
                Counter(zip(df.prefix_u16_stripped, df.suffix_u16_stripped)).most_common(5)]
            st = df.stated.dropna().to_numpy(float)
            if len(st):
                out["stated_truncated_chars_q"] = {f"q{q:g}": float(np.quantile(st, q)) for q in
                                                   (0, 0.05, 0.25, 0.5, 0.75, 0.95, 1)}
            ix = df[~df.exact.astype(bool)]
            out["inexact_detail"] = {"n": int(len(ix)), "sessions": int(ix.session_id.nunique()),
                                     "prefix_exact_suffix_not": int(((ix.prefix_u16 == N5C_CONST[item][0])
                                                                     & (ix.suffix_u16 != N5C_CONST[item][1])).sum()),
                                     "suffix_exact_prefix_not": int(((ix.prefix_u16 != N5C_CONST[item][0])
                                                                     & (ix.suffix_u16 == N5C_CONST[item][1])).sum()),
                                     "both_below_constant": int(((ix.prefix_u16 < N5C_CONST[item][0])
                                                                 & (ix.suffix_u16 < N5C_CONST[item][1])).sum()),
                                     "any_above_constant": int(((ix.prefix_u16 > N5C_CONST[item][0])
                                                                | (ix.suffix_u16 > N5C_CONST[item][1])).sum())}
        else:
            out["lines_top"] = [[int(a), int(b)] for a, b in Counter(df.lines).most_common(10)]
            ix = df[~df.exact.astype(bool)]
            out["inexact_detail"] = {"n": int(len(ix)), "sessions": int(ix.session_id.nunique()),
                                     "lines_below_cap": int((ix.lines < N5C_CONST[item]).sum()),
                                     "lines_above_cap": int((ix.lines > N5C_CONST[item]).sum())}
        out["by_key"] = {k: {"n": int(len(g)), "exact": int(g.exact.astype(bool).sum())} for k, g in df.groupby("key")}
    if detail and w is None:
        p = PCd[PCd.item == item] if len(PCd) else PCd
        if len(p):
            out["positive_control"] = {"n": int(len(p)), "sessions": int(p.session_id.nunique()),
                                       "abstain_not_eligible": int((~p.pc_eligible.astype(bool)).sum()),
                                       "recall": pe.rate_by_session(p.pc_flag.astype(bool).to_numpy(),
                                                                    p.session_id.to_numpy())}
        else:
            out["positive_control"] = {"n": 0}
    out["verdict"] = n5c_verdict(out, path)
    return out


def n5c_verdict(b, path):
    n, ns = b["marked"], b["sessions"]
    if n < N5C_MIN[0] or ns < N5C_MIN[1]:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {N5C_MIN[0]} marked results from >= {N5C_MIN[1]} sessions",
                "deciding_number": {"n": n, "sessions": ns}, "deciding_path": [f"{path}.marked", f"{path}.sessions"]}
    ex, lo = b["exactness"], b["exactness_ci_lo"]
    dn = {"exactness": ex, "ci_lo": lo, "n": n, "sessions": ns}
    dp = [f"{path}.exactness", f"{path}.exactness_ci_lo"]
    if ex >= N5C_ALIVE_PT and lo >= N5C_ALIVE_LO:
        return {"label": "ALIVE", "rule": f"exactness >= {N5C_ALIVE_PT} with CI lo >= {N5C_ALIVE_LO}",
                "deciding_number": dn, "deciding_path": dp}
    if ex >= N5C_WEAK_PT:
        return {"label": "WEAK", "rule": f"exactness >= {N5C_WEAK_PT} (ALIVE fails)", "deciding_number": dn,
                "deciding_path": dp}
    return {"label": "DEAD", "rule": f"exactness < {N5C_WEAK_PT}", "deciding_number": dn, "deciding_path": dp}


# ================================================================================================== statistics: N5g
def n5g_block(C, path, w=None, detail=True):
    out = {"sessions": int(len(C))}
    if not len(C):
        out["verdict"] = {"label": "INSUFFICIENT_N", "rule": f"min n: >= {N5G_MIN} eligible sessions",
                          "deciding_number": 0, "deciding_path": f"{path}.sessions"}
        return out
    c = C.c.to_numpy(float)
    fl = c <= 0
    if w is None:
        if detail or len(C) >= N5G_MIN:
            out["median_c"] = stats.cluster_quantile(c, C.session_id.to_numpy(), 0.5)
        else:  # below min n: label fixed (INSUFFICIENT_N), no bootstrap
            out["median_c"] = {"q": 0.5, "value": float(np.median(c)), "lo": None, "hi": None, "n": int(len(c)),
                               "n_sessions": int(len(c)), "skipped": "below min n (label fixed)"}
        p, lo, hi = stats.wilson(int(fl.sum()), int(len(fl)))
        out["share_c_le_0"] = {"k": int(fl.sum()), "n": int(len(fl)), "p": p, "lo": lo, "hi": hi}
    else:
        ww = np.array([w.get(s, 0.0) for s in C.session_id], float)
        groups = [(a, b) for a, b in zip(c, ww)]

        def fmed(gs):
            v = np.array([a for a, _ in gs])
            x = np.array([b for _, b in gs])
            return _wmedian(v, x) if x.sum() > 0 else None

        def fsh(gs):
            v = np.array([a for a, _ in gs])
            x = np.array([b for _, b in gs])
            return float((x * (v <= 0)).sum() / x.sum()) if x.sum() > 0 else None
        m = pe.boot_stat(groups, fmed)
        s = pe.boot_stat(groups, fsh)
        out["median_c"] = {"q": 0.5, "value": m["value"], "lo": m.get("lo"), "hi": m.get("hi"),
                           "valid_draws": m["valid_draws"], "n": int(len(c)), "n_sessions": int(len(c)),
                           "method": "weighted median, session bootstrap (boot_stat)"}
        out["share_c_le_0"] = {"p": s["value"], "lo": s.get("lo"), "hi": s.get("hi"), "valid_draws": s["valid_draws"],
                               "n": int(len(c)), "method": "weighted share, session bootstrap (boot_stat)"}
    if detail and w is None:
        out["c_quantiles"] = {f"q{q:g}": float(np.quantile(c, q)) for q in (0, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1)}
        out["c_histogram_0.25_decade_bins"] = {str(b): int(n) for b, n in sorted(
            Counter(np.floor(c / 0.25).astype(int) * 0.25).items())}
        out["first_vs_later_seconds"] = {"first_q": {f"q{q:g}": float(np.quantile(C.first_delta_s, q)) for q in
                                                     (0.25, 0.5, 0.75)},
                                         "later_median_q": {f"q{q:g}": float(np.quantile(C.later_median_delta_s, q))
                                                            for q in (0.25, 0.5, 0.75)}}
        out["by_top_tool"] = {t: {"sessions": int(len(g)), "median_c": float(np.median(g.c)),
                                  "flagged": int((g.c <= 0).sum())} for t, g in C.groupby("tool")}
        out["by_top_tool_class"] = {t: {"sessions": int(len(g)), "median_c": float(np.median(g.c)),
                                        "flagged": int((g.c <= 0).sum())} for t, g in C.groupby("cls")}
        out["first_call_of_top_tool_is_first_qualified_call"] = int(C.first_is_session_first_qualified.sum())
        out["first_call_in_subagent_thread"] = int(C.first_sub_thread.sum())
        pf = C.pc_flag.astype(bool).to_numpy()
        p, lo, hi = stats.wilson(int(pf.sum()), int(len(pf)))
        out["positive_control"] = {"sessions": int(len(pf)), "recall": {"k": int(pf.sum()), "n": int(len(pf)), "p": p,
                                                                        "lo": lo, "hi": hi},
                                   "median_c_pc": float(np.median(C.c_pc))}
    out["verdict"] = n5g_verdict(out, path)
    return out


def n5g_verdict(b, path):
    n = b["sessions"]
    if n < N5G_MIN:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {N5G_MIN} eligible sessions", "deciding_number": n,
                "deciding_path": f"{path}.sessions"}
    m, s = b["median_c"], b["share_c_le_0"]
    if m.get("lo") is None:
        return {"label": "INCONCLUSIVE", "rule": "median c CI not reportable", "deciding_number": None,
                "deciding_path": f"{path}.median_c"}
    dn = {"median_c": m["value"], "ci_lo": m["lo"], "ci_hi": m["hi"], "share_c_le_0": s["p"], "sessions": n}
    dp = [f"{path}.median_c.value", f"{path}.median_c.lo", f"{path}.share_c_le_0.p"]
    if m["lo"] >= N5G_ALIVE_LO and s["p"] <= N5G_ALIVE_SHARE:
        return {"label": "ALIVE", "rule": f"median c CI lo >= log10(1.5) = {N5G_ALIVE_LO:.4f} and share(c_s <= 0) <= "
                                          f"{N5G_ALIVE_SHARE}", "deciding_number": dn, "deciding_path": dp}
    if m["lo"] > 0:
        return {"label": "WEAK", "rule": "median c CI lo > 0 (ALIVE fails)", "deciding_number": dn, "deciding_path": dp}
    return {"label": "DEAD", "rule": "median c CI lo <= 0", "deciding_number": dn, "deciding_path": dp}


# ================================================================================================== artifact checks
def _lab(x):
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return "nan"
    return str(x)


def recompute(item, D, sess=None, rowmask=None, w=None, variant=None, sub=None):
    """Label + summary of an item on a sub-population. D: item data (N4: (W, G); N5c: (T, PC); N5g: dict of frames)."""
    if item == "n4":
        Wd, Gd = D
        if sess is not None:
            Wd, Gd = Wd[Wd.session_id.isin(sess)], Gd[Gd.session_id.isin(sess)]
        if rowmask is not None:
            Wd, Gd = Wd[rowmask(Wd)] if len(Wd) else Wd, Gd[rowmask(Gd)] if len(Gd) else Gd
        sw = w
        b = n4_block(Wd, Gd, "ac", sw=sw, detail=False)
        return b, {"label": b["verdict"]["label"], "delta_W": b["W"]["delta"].get("value"),
                   "ci_W": [b["W"]["delta"].get("lo"), b["W"]["delta"].get("hi")],
                   "delta_G": b["G"]["delta"].get("value"), "ci_G": [b["G"]["delta"].get("lo"), b["G"]["delta"].get("hi")],
                   "W_k_ge_2": b["W"]["k_ge_2"], "W_k_ge_2_sessions": b["W"]["k_ge_2_sessions"],
                   "G_k_ge_2": b["G"]["k_ge_2"], "G_k_ge_2_sessions": b["G"]["k_ge_2_sessions"]}
    if item == "n5c":
        T, PCd = D
        if sess is not None and len(T):
            T = T[T.session_id.isin(sess)]
        if rowmask is not None and len(T):
            T = T[rowmask(T)]
        b = n5c_block(T, PCd, sub, "ac", w=w, detail=False)
        return b, {"label": b["verdict"]["label"], "marked": b["marked"], "sessions": b["sessions"],
                   "exactness": b.get("exactness"), "ci_lo": b.get("exactness_ci_lo")}
    if item == "n5g":
        C = D[variant or "cs"]
        if sess is not None and len(C):
            C = C[C.session_id.isin(sess)]
        b = n5g_block(C, "ac", w=w, detail=False)
        m = b.get("median_c", {})
        return b, {"label": b["verdict"]["label"], "sessions": b["sessions"], "median_c": m.get("value"),
                   "ci": [m.get("lo"), m.get("hi")], "share_c_le_0": b.get("share_c_le_0", {}).get("p")}
    raise ValueError(item)


def denominators(item, D, sub=None):
    if item == "n4":
        Wd = D[0]
        return Wd.groupby("session_id").size().to_dict() if len(Wd) else {}
    if item == "n5c":
        T = D[0]
        T = T[T.item == sub] if len(T) else T
        return T.groupby("session_id").size().to_dict() if len(T) else {}
    C = D["cs"]
    return {s: 1 for s in C.session_id}


def dominance_check(item, D, base, smeta, unit, sub=None):
    w = denominators(item, D, sub)
    # sessions a leave-out recomputes on: every session of the item's data outside the dropped set
    if item == "n4":
        all_s = set(D[0].session_id) | set(D[1].session_id)
    else:
        all_s = set(w)
    kinds = ["repo", "user", "model"] if CORPUS_OF[unit] == "swechat" else ["repo", "model"]
    out = {"denominator": {"n4": "W pairs per session", "n5c": "marked results per session",
                           "n5g": "eligible sessions (1 each)"}[item], "kinds": {}}
    leaveouts, dom = [], False
    for kind in kinds:
        cmap = {s: smeta[s][kind] for s in w}
        d = pe.dominance(w, cmap)
        rec = {k: d.get(k) for k in ("top_share_events", "top_share_sessions", "n_clusters", "dominated")}
        top = d.get("top_clusters", [])
        rec["top5"] = [[(c if unit != "cc_local" else f"cluster_{i}"), a, b] for i, (c, a, b) in enumerate(top)]
        cd = max(d.get("top_share_events", 0) or 0, d.get("top_share_sessions", 0) or 0) > pe.DOM_SHARE
        rec["cluster_dominated"] = bool(cd)
        out["kinds"][kind] = rec
        if cd and unit == "aiv_cc" and d.get("n_clusters") == 1:
            rec["label_only"] = "aiv_cc is one agent (one model): always dominated, only labelled (PREREG_E 1.1)"
            continue
        if cd:
            dom = True
            for i, (c, _, _) in enumerate(top):
                leaveouts.append((kind, c if unit != "cc_local" else f"cluster_{i}",
                                  {s for s in all_s if smeta[s][kind] == c}))
    if w:
        ts = sorted(w.items(), key=lambda kv: -kv[1])
        share = ts[0][1] / max(sum(w.values()), 1)
        out["top_session_share_events"] = share
        if share > pe.DOM_SESSION:
            dom = True
            for rank, (s, _) in enumerate(ts[:5]):
                leaveouts.append(("session", f"largest_session_rank_{rank + 1}", {s}))
    out["dominated"] = dom
    # correction C2: "a leave-out falls below min n" is decided on the leave-out's counts against the min n the base
    # cell met (N4: W, and G where the base G met it), not on the label; every other leave-out label is compared on levels
    base_g_ok = None
    if item == "n4":
        Gb = D[1]
        hb = Gb.k >= 2 if len(Gb) else None
        base_g_ok = bool(len(Gb) and int(hb.sum()) >= N4_MIN[0] and Gb[hb].session_id.nunique() >= N4_MIN[1]
                         and len(n4_keys(Gb)) > 0)
        out["base_G_meets_min_n"] = base_g_ok
    res, down, cap = [], False, False
    for kind, c, drop in leaveouts:
        keep = all_s - drop
        _, sm = recompute(item, D, sess=keep, sub=sub)
        sm.update({"kind": kind, "left_out": c})
        lab = sm["label"]
        if item == "n4":
            w_ok = (sm["W_k_ge_2"] >= N4_MIN[0] and sm["W_k_ge_2_sessions"] >= N4_MIN[1]
                    and sm.get("delta_W") is not None)
            g_ok = (sm["G_k_ge_2"] >= N4_MIN[0] and sm["G_k_ge_2_sessions"] >= N4_MIN[1]
                    and sm.get("delta_G") is not None)
            below = (not w_ok) or (base_g_ok and not g_ok)
        else:
            below = lab == "INSUFFICIENT_N"
        sm["below_min_n"] = bool(below)
        if below:
            cap = True
            sm["effect"] = "below min n -> UNTESTABLE_WITHOUT_DOMINANT (cap WEAK)"
        elif lab in LVL and base in LVL and LVL[lab] < LVL[base]:
            down = True
            sm["effect"] = "label drops -> DOMINATED"
        else:
            sm["effect"] = "label held" if lab in LVL else f"{lab} (not a level; no effect)"
        res.append(sm)
    out["leaveouts"] = res
    effect = "downgrade" if down else "cap_weak" if cap else "pass"
    out["effect"] = effect if dom else "pass"
    out["also_cap_weak"] = bool(dom and down and cap)
    out["n_leaveouts_dropping_label"] = sum(1 for x in res if x["effect"].startswith("label drops"))
    out["n_leaveouts_below_min_n"] = sum(1 for x in res if x["below_min_n"])
    out["status"] = ("DOMINATED" + (" (+ UNTESTABLE_WITHOUT_DOMINANT leave-outs)" if out["also_cap_weak"] else "")
                     if out["effect"] == "downgrade" else "UNTESTABLE_WITHOUT_DOMINANT"
                     if out["effect"] == "cap_weak" else "dominated, label stable" if dom else "not dominated")
    return out


def strata_check(item, D, smeta, unit, sub=None):
    out = {}
    if item == "n4":
        sess_all = sorted(set(D[0].session_id) | set(D[1].session_id))
    elif item == "n5c":
        T = D[0][D[0].item == sub]
        sess_all = sorted(set(T.session_id))
    else:
        sess_all = sorted(set(D["cs"].session_id))
    for axis in ("tool_key", "model", "repo", "length_tercile"):
        labels, rec = {}, {}
        if axis == "tool_key":
            if item == "n4":
                groups = {k: ("w_key", k) for k in sorted(D[0].key.unique())}
            elif item == "n5c":
                groups = {k: ("rows", (lambda d, k=k: d.key == k)) for k in sorted(T.key.unique())}
            else:
                groups = {t: ("sess", set(D["cs"][D["cs"].tool == t].session_id)) for t in sorted(D["cs"].tool.unique())}
        else:
            vals = Counter(smeta[s][axis] for s in sess_all)
            groups = {v: ("sess", {s for s in sess_all if smeta[s][axis] == v}) for v in vals}
        for i, (k, (mode, sel)) in enumerate(sorted(groups.items(), key=lambda kv: str(kv[0]))):
            if mode == "w_key":
                Wd, Gd = D
                _, sm = recompute("n4", (Wd[Wd.key == sel], Gd))
            elif mode == "rows":
                _, sm = recompute(item, D, rowmask=sel, sub=sub)
            else:
                if item == "n4":
                    _, sm = recompute(item, D, sess=sel)
                else:
                    _, sm = recompute(item, D, sess=sel, sub=sub)
            name = k if (unit != "cc_local" or axis in ("tool_key", "length_tercile")) else f"{axis}_{i}"
            rec[name] = sm
            labels[name] = sm["label"] if sm["label"] in LVL else None
        out[axis] = {"strata": rec, "confinement": pe.confinement(labels)}
    out["CONFINED_any_axis"] = any(v.get("confinement") == "CONFINED" for v in out.values() if isinstance(v, dict))
    return out


def _raw_ms(ts):
    t = parse_ts(iso(ts)) if ts is not None else None
    return None if t is None else t.timestamp() * 1000.0


def raw_lookup(unit, events, n1):
    """phase_e_n1.raw_lookup, except that for aiv_cc the gz lines are pre-filtered by extracting 'toolu_' ids with a
    regex and intersecting with the target set (n1 tests every target as a substring of every line, which takes hours
    for the thousands of targets the N4 / N5g audits need). Same rows, same parser (_scan_entry), same order."""
    if unit != "aiv_cc":
        return n1.raw_lookup(unit, events)
    import gzip
    import re
    targets = {e["call_id"] for e in events}
    other = [t for t in targets if not t.startswith("toolu_")]
    rx = re.compile(r"toolu_[A-Za-z0-9]+")
    calls, results = defaultdict(list), defaultdict(list)
    src = "C:/Swarms/data/ai-village/claude_code_messages.jsonl.gz"
    OPENED.append(src)
    rows = []
    with gzip.open(src, "rt", encoding="utf-8") as f:
        for line in f:
            if ("toolu_" in line and not targets.isdisjoint(rx.findall(line))) or any(t in line for t in other):
                rows.append(json.loads(line))
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    seen = set()
    for r in rows:
        n1._scan_entry(r.get("content"), iso(r.get("created_at")), targets, calls, results, seen)
    return {t: (calls.get(t, []), results.get(t, [])) for t in targets}


def ac1_audit(item, unit, D, sub=None):
    """AC1 (Claude Code formats only): 30 numerator events looked up in the raw source (phase_e_n1.raw_lookup)."""
    if unit not in ("swechat/claude_code", "aiv_cc"):
        return {"label": "NOT_RUN", "reason": f"no committed raw reader for {unit} (Claude Code formats only)"}
    from analysis.probes import phase_e_n1 as n1
    recs = []
    if item == "n4":
        Wd = D[0]
        num = Wd[Wd.k >= 2].sort_values(["session_id", "seq"])
        keys = list(zip(num.session_id, num.seq))
        pick = set(pe.audit_sample(keys, seed_parts=("N4", "AC1", "numerator", unit)))
        ev = num[np.array([k in pick for k in keys], dtype=bool)] if keys else num.iloc[0:0]
        sids = sorted(set(ev.session_id))
        allp = []
        for split in (("B", "E") if CORPUS_OF[unit] in pe.CORPORA_WITH_E else ("B",)):
            d = pe.read_cache(CORPUS_OF[unit], split, ["session_id", "kind", "seq", "ts", "call_id"],
                              filters=[("session_id", "in", sids), ("kind", "in", ["call", "result"])])
            if len(d):
                allp.append(pc.make_pairs(d))
        AP = pd.concat(allp, ignore_index=True) if allp else pd.DataFrame()
        targets = [{"session_id": s, "call_id": str(c)} for s, c in zip(AP.session_id, AP.call_id)]
        raw = raw_lookup(unit, targets, n1)
        OPENED.extend(n1.OPENED)
        for r in ev.itertuples():
            cl, rs = raw.get(r.call_id, ([], []))
            why = []
            if not cl or not rs:
                why.append("not found in raw")
            else:
                ca, ra = _raw_ms(cl[0]["ts"]), _raw_ms(rs[0]["ts"])
                if ca is None or ra is None or abs((ra - ca) / 1000.0 - r.delta_s) > 0.001:
                    why.append("delta")
                else:
                    mid = (ca + ra) / 2
                    kr = 1
                    for c2 in AP[AP.session_id == r.session_id].call_id.astype(str):
                        if c2 == r.call_id:
                            continue
                        cl2, rs2 = raw.get(c2, ([], []))
                        if cl2 and rs2:
                            a2, b2 = _raw_ms(cl2[0]["ts"]), _raw_ms(rs2[0]["ts"])
                            if a2 is not None and b2 is not None and a2 <= mid <= b2:
                                kr += 1
                    if (kr >= 2) != (r.k >= 2):
                        why.append("k arm")
            recs.append({"differs": bool(why), "why": why})
        pool = len(keys)
        seed = ["N4", "AC1", "numerator", unit]
    elif item == "n5c":
        T = D[0]
        T = T[(T.item == sub) & ~T.exact.astype(bool)].sort_values(["session_id", "seq"])
        keys = list(zip(T.session_id, T.seq))
        pick = set(pe.audit_sample(keys, seed_parts=("N5c", sub, "AC1", "numerator", unit)))
        ev = T[np.array([k in pick for k in keys], dtype=bool)] if keys else T.iloc[0:0]
        raw = raw_lookup(unit, [{"session_id": s, "call_id": c} for s, c in zip(ev.session_id, ev.call_id)], n1)
        OPENED.extend(n1.OPENED)
        for r in ev.itertuples():
            cl, rs = raw.get(r.call_id, ([], []))
            why = []
            if not rs:
                why.append("not found in raw")
            else:
                ti = pe.truncation_info(rs[0]["text"])
                if not ti or ti["item"] != sub:
                    why.append("marker not found in raw text")
                else:
                    ex = ((ti["prefix_u16"], ti["suffix_u16"]) == N5C_CONST[sub]) if sub == "cc_chars_mid" else \
                        ti["lines"] == N5C_CONST[sub]
                    if bool(ex) != bool(r.exact):
                        why.append("exactness")
            recs.append({"differs": bool(why), "why": why})
        pool = len(keys)
        seed = ["N5c", sub, "AC1", "numerator", unit]
    else:
        C = D["cs"]
        num = C[C.flag.astype(bool)].sort_values("session_id")
        keys = list(num.session_id)
        pick = set(pe.audit_sample(keys, seed_parts=("N5g", "AC1", "numerator", unit)))
        ev = num[num.session_id.isin(pick)]
        targets = [{"session_id": s, "call_id": c} for s, ids in zip(ev.session_id, ev.t_call_ids)
                   for c in ids.split("\x1f")]
        raw = raw_lookup(unit, targets, n1)
        OPENED.extend(n1.OPENED)
        for r in ev.itertuples():
            why = []
            lg = []
            for c in r.t_call_ids.split("\x1f"):
                cl, rs = raw.get(c, ([], []))
                if not cl or not rs:
                    why.append("not found in raw")
                    break
                a, b = _raw_ms(cl[0]["ts"]), _raw_ms(rs[0]["ts"])
                if a is None or b is None or b <= a:
                    why.append("raw delta not positive")
                    break
                lg.append(math.log10((b - a) / 1000.0))
            if not why:
                craw = lg[0] - float(np.median(lg[1:]))
                if (craw <= 0) != bool(r.flag):
                    why.append("flag")
            recs.append({"differs": bool(why), "why": sorted(set(why))})
        pool = len(keys)
        seed = ["N5g", "AC1", "numerator", unit]
    nd = sum(1 for x in recs if x["differs"])
    out = {"population": "B u E" if CORPUS_OF[unit] in pe.CORPORA_WITH_E else "B", "pool_size": int(pool),
           "audited": len(recs), "differing": int(nd),
           "differing_reasons": dict(Counter(w for x in recs for w in x["why"])), "seed_parts": seed,
           "rule": "FAIL if >= 2 of 30 differ in a way that changes their contribution; 1 = PARSER_NOTE"}
    out["label"] = ("PASS" if not recs else "FAIL" if nd >= pe.AUDIT_FAIL else "PARSER_NOTE" if nd == 1 else "PASS")
    if not recs:
        out["note"] = "empty: nothing to audit"
    return out


def posthoc_chars_mid_raw(unit, T):
    """POST HOC, NOT A VERDICT: every inexact cc_chars_mid result of the pooled population (and 30 exact ones drawn
    with audit_sample as a control) looked up in the raw source; counts only (no text). Asks whether the inexactness is
    in the raw transcript or introduced by the IR, and whether carriage returns sit in the kept text."""
    if unit not in ("swechat/claude_code", "aiv_cc"):
        return {"status": "NOT_RUN", "reason": "no committed raw reader for this unit"}
    from analysis.probes import phase_e_n1 as n1
    t = T[T.item == "cc_chars_mid"].sort_values(["session_id", "seq"])
    if not len(t):
        return {"status": "no marked results"}
    ix = t[~t.exact.astype(bool)]
    ex = t[t.exact.astype(bool)]
    keys = list(zip(ex.session_id, ex.seq))
    pick = set(pe.audit_sample(keys, seed_parts=("N5c", "cc_chars_mid", "posthoc_raw", "exact_control", unit)))
    exs = ex[np.array([k in pick for k in keys], dtype=bool)] if keys else ex.iloc[0:0]
    ev = pd.concat([ix, exs], ignore_index=True)
    raw = raw_lookup(unit, [{"session_id": a, "call_id": b} for a, b in zip(ev.session_id, ev.call_id)], n1)
    ir = {}
    sids = sorted(set(ev.session_id))
    for split in (("B", "E") if CORPUS_OF[unit] in pe.CORPORA_WITH_E else ("B",)):
        d = pe.read_cache(CORPUS_OF[unit], split, ["session_id", "kind", "call_id", "text"],
                          filters=[("session_id", "in", sids), ("kind", "==", "result")])
        for a, c, x in zip(d.session_id, d.call_id.astype(object), d.text.astype(object)):
            if c is not None:
                ir.setdefault((a, str(c)), x if isinstance(x, str) else "")
    out = {}
    for name, grp in (("inexact_all", ev.iloc[:len(ix)]), ("exact_control_sample", ev.iloc[len(ix):])):
        c = Counter()
        dpre, dsuf = Counter(), Counter()
        for r in grp.itertuples():
            cl, rs = raw.get(r.call_id, ([], []))
            if not rs:
                c["not_found"] += 1
                continue
            rt = rs[0]["text"]
            c["found"] += 1
            c["ir_text_equals_raw"] += int(ir.get((r.session_id, r.call_id)) == rt)
            if len(rs) > 1:
                c["multiple_raw_occurrences"] += 1
            ti = pe.truncation_info(rt)
            if not ti or ti["item"] != "cc_chars_mid":
                c["raw_marker_not_cc_chars_mid"] += 1
                continue
            rex = (ti["prefix_u16"], ti["suffix_u16"]) == N5C_CONST["cc_chars_mid"]
            c["raw_exact"] += int(rex)
            m = pe._R["trunc_chars_mid"].search(rt)
            pre, post = rt[:m.start()], rt[m.end():]
            c["raw_kept_text_contains_CR"] += int(chr(13) in pre or chr(13) in post)
            c["raw_marker_count_gt_1"] += int(len(pe._R["trunc_chars_mid"].findall(rt)) > 1)
            dpre[int(N5C_CONST["cc_chars_mid"][0] - ti["prefix_u16"])] += 1
            dsuf[int(N5C_CONST["cc_chars_mid"][1] - ti["suffix_u16"])] += 1
        out[name] = {"n": int(len(grp)), **{k: int(v) for k, v in c.items()},
                     "raw_prefix_deficit_u16_top": [[a, b] for a, b in dpre.most_common(8)],
                     "raw_suffix_deficit_u16_top": [[a, b] for a, b in dsuf.most_common(8)]}
    out["note"] = ("POST HOC, NOT A VERDICT (the cc_chars_mid cell is DEAD and no check can raise it). Deficit = "
                   "constant - raw length (positive = shorter than 5,002).")
    return out


def run_checks(item, unit, D, base, smeta, sub=None):
    ac = {"population": "B u E" if CORPUS_OF[unit] in pe.CORPORA_WITH_E else "B", "base_label": base}
    eff = []
    # AC2
    if item == "n5c":
        ac["AC2_no_truncated"] = {"label": "NOT_RUN", "reason": "every marked result is truncated by definition "
                                                                "(deviation 'N5c AC2')"}
    else:
        if item == "n4":
            _, sm = recompute(item, D, rowmask=lambda d: ~d.trunc.astype(bool))
        else:
            _, sm = recompute(item, D, variant="cs_nt")
        ac["AC2_no_truncated"] = {**sm, "fail": sm["label"] != base}
        if sm["label"] != base:
            eff.append(("AC2", sm["label"]))
    # AC3
    if item == "n4":
        _, sm = recompute(item, D, rowmask=lambda d: d.join_clean.astype(bool))
    elif item == "n5c":
        _, sm = recompute(item, D, rowmask=lambda d: d.join_clean.astype(bool), sub=sub)
    else:
        _, sm = recompute(item, D, variant="cs_jc")
    ac["AC3_join_clean"] = {**sm, "fail": sm["label"] != base}
    if sm["label"] != base:
        eff.append(("AC3", sm["label"]))
    # AC4
    ac["AC4_dominance"] = dominance_check(item, D, base, smeta, unit, sub)
    # AC5
    if CORPUS_OF[unit] in ("swechat", "aiv_cu"):
        if item == "n4":
            ss = sorted(set(D[0].session_id) | set(D[1].session_id))
        elif item == "n5c":
            ss = sorted(set(D[0][D[0].item == sub].session_id))
        else:
            ss = sorted(set(D["cs"].session_id))
        wts = pe.post_strat_weights(CORPUS_OF[unit], ss)
        _, sm = recompute(item, D, w=wts, sub=sub)
        ac["AC5_post_stratified"] = {**sm, "fail": sm["label"] != base,
                                     "weights": "population cell size / analysed sessions in the cell (post_strat_weights)"}
        if sm["label"] != base:
            eff.append(("AC5", sm["label"]))
    else:
        ac["AC5_post_stratified"] = {"label": "NOT_RUN", "reason": "no population table for this corpus"}
    # AC1
    ac["AC1_parser"] = ac1_audit(item, unit, D, sub)
    st = strata_check(item, D, smeta, unit, sub)
    return ac, st, eff


def apply_checks(cell, ac, st, eff):
    final, applied = cell, []
    for name, lab in eff:
        if lab in LVL and final in LVL and LVL[lab] < LVL[final]:
            final = lab
            applied.append({"name": name, "effect": f"lower label to {lab}"})
        elif lab not in LVL:
            applied.append({"name": name, "effect": f"label {lab} on the recompute (not a level; no change)"})
    a4 = ac["AC4_dominance"]["effect"]
    if a4 == "downgrade":
        final = pe.downgrade(final)
        applied.append({"name": "AC4 DOMINATED", "effect": "downgrade"})
        if ac["AC4_dominance"].get("also_cap_weak") and final == "ALIVE":
            final = "WEAK"
            applied.append({"name": "AC4 UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
    elif a4 == "cap_weak" and final == "ALIVE":
        final = "WEAK"
        applied.append({"name": "AC4 UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
    if ac.get("AC1_parser", {}).get("label") == "FAIL":
        final = pe.downgrade(final)
        applied.append({"name": "AC1 FAIL", "effect": "downgrade"})
    if st["CONFINED_any_axis"]:
        final = pe.downgrade(final)
        applied.append({"name": "CONFINED", "effect": "downgrade"})
    return final, applied


def cell_of(lb, le, has_e):
    if has_e and le is not None and le != "INSUFFICIENT_N":
        return le, "E", ""
    return lb, "B", (" (B only, unreplicated)" if not has_e else " (B only; E INSUFFICIENT_N: NOT_REPLICABLE_AT_N)")


# ================================================================================================== corrections
# Fixes after an independent re-derivation (blocking issues on swechat/codex N4 and cc_local N4). "before" values are
# copied from the previous output (run 4); "after" is read from this run's output at the same path, so the block is
# mechanical. Every measured number (Delta, CI, n, sessions) is unchanged; only rule branches and labels move.
CORRECTION_RULES = [
    {"id": "C1", "what": "N4 verdict branch 'G below min n and Delta_W CI covers 0' (W at min n)",
     "before": "INSUFFICIENT_N ('no rule assigns a level')",
     "after": "DEAD (the W-only test's null outcome)",
     "reason": "re-deriver, blocking: W meets min n, so INSUFFICIENT_N ('below min n') turned a null into missing "
               "data. The WEAK branch ('Delta_W CI excludes 0 with G below min n'; PREREG_E 'Delta_W != 0 without a G "
               "control') defines a W-only test, PREREG_E section 5 calls codex testable without a G control, and the "
               "W-only analogue of 'CIs overlap' is a Delta_W CI covering 0. The first version's own deviation named "
               "DEAD as the alternative. Applies wherever the rule runs: base split verdicts, AC2/AC3/AC5 recomputes, "
               "AC4 leave-outs, strata, post-hoc variants",
     "deviation": "N4 minimum n and missing rule branches"},
    {"id": "C2", "what": "AC4: which leave-outs count as 'below min n' (UNTESTABLE_WITHOUT_DOMINANT)",
     "before": "any leave-out labelled INSUFFICIENT_N",
     "after": "a leave-out whose own counts fail min n (N4: W below 100 pairs at k >= 2 / 10 sessions or Delta_W "
              "undefined; or G below min n where the base cell's G met it); other leave-outs compared on levels",
     "reason": "re-deriver, blocking: PREREG_E 1.1 reserves UNTESTABLE_WITHOUT_DOMINANT for a leave-out below min n. "
               "In swechat/codex N4 every repo/user/session leave-out keeps 2,410 to 4,120 W pairs at k >= 2 in 47 to "
               "79 sessions, and G was 0 in the base cell as well",
     "deviation": "AC4 'leave-out falls below min n' (correction C2)"},
]
CORRECTION_VALUES = [   # (path as key list, before = run-4 value, rule); filled from the diff against run 4
    (["n6_cells", "cc_local", "N4", "checks_applied"], [{"name": "AC2", "effect": "label INSUFFICIENT_N on the recompute (not a level; no change)"}], "C1"),
    (["n6_cells", "cc_local", "N4", "label"], "WEAK", "C1"),
    (["n6_cells", "swechat/codex", "N4", "B"], "INSUFFICIENT_N", "C1"),
    (["n6_cells", "swechat/codex", "N4", "checks_applied"], [], "C1"),
    (["n6_cells", "swechat/codex", "N4", "label"], "WEAK", "C1"),
    (["units", "cc_local", "cells", "N4", "checks_applied"], [{"name": "AC2", "effect": "label INSUFFICIENT_N on the recompute (not a level; no change)"}], "C1"),
    (["units", "cc_local", "cells", "N4", "label"], "WEAK", "C1"),
    (["units", "swechat/codex", "cells", "N4", "B"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks_applied"], [], "C1"),
    (["units", "swechat/codex", "cells", "N4", "label"], "WEAK", "C1"),
    (["units", "cc_local", "cells", "N4", "checks", "artifact_checks", "AC2_no_truncated", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "cc_local", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "effect"], "cap_weak", "C1+C2"),
    (["units", "cc_local", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 5, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "cc_local", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 7, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "cc_local", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "status"], "UNTESTABLE_WITHOUT_DOMINANT", "C1+C2"),
    (["units", "cc_local", "cells", "N4", "checks", "stratification", "CONFINED_any_axis"], False, "C1"),
    (["units", "cc_local", "cells", "N4", "checks", "stratification", "length_tercile", "confinement"], "UNTESTABLE", "C1"),
    (["units", "cc_local", "cells", "N4", "checks", "stratification", "length_tercile", "strata", "long", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "cc_local", "cells", "N4", "checks", "stratification", "tool_key", "confinement"], "UNTESTABLE", "C1"),
    (["units", "cc_local", "cells", "N4", "checks", "stratification", "tool_key", "strata", "read", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/claude_code", "cells", "N4", "checks", "stratification", "model", "strata", "claude-sonnet-4-5-20250929", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/claude_code", "cells", "N4", "checks", "stratification", "repo", "strata", "ClusterCockpit/cc-backend", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/claude_code", "cells", "N4", "checks", "stratification", "repo", "strata", "anchoo2kewl/SprintSpark", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/claude_code", "cells", "N4", "checks", "stratification", "repo", "strata", "jdsingh122918/forge", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/claude_code", "cells", "N4", "checks", "stratification", "repo", "strata", "nosman/gossamer", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/claude_code", "cells", "N4", "checks", "stratification", "repo", "strata", "obsessiondb/rudel", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "effect"], "cap_weak", "C1+C2"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 0, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 1, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 3, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 4, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 5, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 6, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 7, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 11, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 12, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "leaveouts", 13, "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "artifact_checks", "AC4_dominance", "status"], "UNTESTABLE_WITHOUT_DOMINANT", "C1+C2"),
    (["units", "swechat/codex", "cells", "N4", "checks", "stratification", "CONFINED_any_axis"], False, "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "stratification", "length_tercile", "confinement"], "UNTESTABLE", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "stratification", "length_tercile", "strata", "long", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "stratification", "length_tercile", "strata", "mid", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "stratification", "tool_key", "confinement"], "UNTESTABLE", "C1"),
    (["units", "swechat/codex", "cells", "N4", "checks", "stratification", "tool_key", "strata", "exec_command", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "cells", "N5g_cold_start", "checks", "artifact_checks", "AC4_dominance", "status"], "DOMINATED", "C2"),
    (["units", "swechat/codex", "results", "n4", "B", "post_hoc_not_a_verdict", "k_excluding_nesting", "label_under_same_rule"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "results", "n4", "B", "post_hoc_not_a_verdict", "main_thread_W_only", "label_under_same_rule"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "results", "n4", "B", "verdict", "deciding_path"], ["units.swechat/codex.results.n4.B.W.delta.lo", "units.swechat/codex.results.n4.B.W.delta.hi", "units.swechat/codex.results.n4.B.W.k_ge_2", "units.swechat/codex.results.n4.B.W.k_ge_2_sessions", "units.swechat/codex.results.n4.B.G.k_ge_2", "units.swechat/codex.results.n4.B.G.k_ge_2_sessions"], "C1"),
    (["units", "swechat/codex", "results", "n4", "B", "verdict", "label"], "INSUFFICIENT_N", "C1"),
    (["units", "swechat/codex", "results", "n4", "B", "verdict", "rule"], "G below min n and Delta_W CI includes 0 (no rule assigns a level)", "C1"),
    (["units", "swechat/opencode", "cells", "N4", "checks", "stratification", "tool_key", "strata", "grep", "label"], "INSUFFICIENT_N", "C1"),
]


def _get(d, keys):
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        elif isinstance(d, list) and isinstance(k, int) and k < len(d):
            d = d[k]
        else:
            return "<absent>"
    return d


def corrections_block(out):
    vals = []
    for keys, before, rid in CORRECTION_VALUES:
        vals.append({"path": ".".join(str(k) for k in keys), "before": before, "after": _get(out, keys),
                     "rule": rid})
    return {"note": "earlier values kept here; the cells and checks elsewhere in this file carry the corrected values. "
                    "Measured numbers (Delta, CIs, counts) did not change; only labels and statuses did",
            "rules": CORRECTION_RULES, "values": vals,
            "n_values_changed": sum(1 for v in vals if v["before"] != v["after"])}


# ================================================================================================== main
def main():
    store = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    sess_tab = defaultdict(lambda: defaultdict(list))
    gates = defaultdict(lambda: defaultdict(Counter))
    gex = defaultdict(lambda: defaultdict(Counter))
    khist = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    models = defaultdict(dict)
    nsplit = defaultdict(dict)
    copied = {}
    for corpus, unit, split, df, nss, ci in unit_chunks():
        nsplit[unit][split] = nss
        if df is None:
            continue
        if corpus not in copied:
            copied[corpus] = copied_call_ids(corpus)
        print(f"[{time.time() - T0:7.1f}s] {unit} {split} chunk {ci}: {len(df)} rows ({nss} sessions)", flush=True)
        rec, ps, gate, model = extract(unit, split, df, copied[corpus])
        for k, v in rec.items():
            if k == "G_excl":
                gex[unit][split].update(v)
            elif k in ("k_all_hist", "k_all_nonest_hist"):
                khist[unit][split][k].update(v)
            else:
                store[unit][split][k].append(v)
        sess_tab[unit][split].append(ps)
        gates[unit][split].update(gate)
        models[unit].update(model)
        del df, rec
        gc.collect()
    print(f"[{time.time() - T0:7.1f}s] statistics", flush=True)

    EMPTY = {"W": ["session_id", "call_id", "seq", "key", "delta_s", "lg", "k", "k_nonest", "k_within", "anc_inflight",
                   "sub_thread", "trunc", "join_clean"],
             "G": ["session_id", "call_id", "seq", "key", "lat_s", "lg", "delta_s", "lat_source", "k", "k_nonest",
                   "k_within", "anc_inflight", "sub_thread", "trunc", "join_clean"],
             "tr": ["session_id", "call_id", "seq", "item", "key", "join_clean", "stated", "prefix_u16", "suffix_u16",
                    "prefix_u16_stripped", "suffix_u16_stripped", "lines", "prefix_raw", "prefix_chars", "exact"],
             "pc5c": ["session_id", "call_id", "item", "key", "pc_eligible", "pc_flag"],
             "cs": ["session_id", "tool", "cls", "c", "flag", "c_pc", "pc_flag", "n_t", "first_delta_s",
                    "later_median_delta_s", "first_is_session_first_qualified", "first_sub_thread", "first_trunc",
                    "first_join_clean", "t_call_ids"],
             "cs_nt": ["session_id", "tool", "c"], "cs_jc": ["session_id", "tool", "c"]}

    def cat(unit, split, k):
        lst = [x for x in store[unit][split].get(k, []) if len(x)]
        if lst:
            df = pd.concat(lst, ignore_index=True)
        else:
            df = pd.DataFrame({c: pd.Series(dtype=(float if c in ("lg", "c", "delta_s", "lat_s", "c_pc") else object))
                               for c in EMPTY[k]})
        for c in ("trunc", "join_clean", "sub_thread", "anc_inflight", "pc_flag", "pc_eligible", "flag"):
            if c in df.columns:
                df[c] = df[c].astype(bool)
        for c in ("k", "k_nonest", "k_within"):
            if c in df.columns:
                df[c] = df[c].astype(int)
        return df

    out = {"item": "n4_n5cg", "items_covered": ["N4 concurrency physics", "N5c truncation boundary", "N5g cold start"],
           "script": "analysis/probes/phase_e_n4_n5cg.py",
           "prereg_sections": ["prereg_e.json n4_concurrency", "prereg_e.json n5_battery.c_truncation_boundary",
                               "prereg_e.json n5_battery.g_cold_start"],
           "prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
           "spec_module_sha256": PJ["provenance"]["spec_module_sha256"],
           "spec_module_sha256_lf": pe.sha256_lf(pe.ROOT / "analysis" / "probes" / "prereg_e_common.py"),
           "check_frozen": "passed",
           "spec": {"n4_concurrency": SPEC4, "c_truncation_boundary": SPEC5["c_truncation_boundary"],
                    "g_cold_start": SPEC5["g_cold_start"]},
           "thresholds_used": {
               "n4": {"min_n_pairs_k_ge_2": N4_MIN[0], "min_n_sessions": N4_MIN[1], "arm_min_pairs": N4_ARM,
                      "alive_min_abs_diff_decades": N4_DIFF},
               "n5c": {"min_n_marked": N5C_MIN[0], "min_n_sessions": N5C_MIN[1], "alive_exactness": N5C_ALIVE_PT,
                       "alive_ci_lo": N5C_ALIVE_LO, "weak_exactness": N5C_WEAK_PT,
                       "constants (resolved.n5.truncation_constants_pooled)": TC_POOLED,
                       "items_run": list(N5C_RUN), "pc_long_u16": PC_LONG_U16},
               "n5g": {"min_sessions": N5G_MIN, "alive_median_ci_lo": N5G_ALIVE_LO,
                       "alive_share_c_le_0": N5G_ALIVE_SHARE}},
           "seeds": {"bootstrap": pe.SEED, "n5c_positive_control": "rng_for('N5cpc', session_id, call_id, item)",
                     "n5g_positive_control": "rng_for('N5gpc', session_id, tool_key)",
                     "AC1": "audit_sample seed_parts (item, ..., 'AC1', 'numerator', unit)", "SEED_E": pe.SEED_E},
           "A_split_eligibility_context": {
               u: {"n4": CAL_A["units"].get(u, {}).get("latency_counts", {}).get("n4"),
                   "cold_start": CAL_A["units"].get(u, {}).get("cold_start"),
                   "c_truncation_A": CAL_A["units"].get(u, {}).get("n5", {}).get("c_truncation_A")}
               for u in UNITS if u in CAL_A["units"]},
           "cells_computed": 0, "units": {}}
    n_cells = 0
    for unit in UNITS:
        print(f"[{time.time() - T0:7.1f}s] {unit}", flush=True)
        corpus = CORPUS_OF[unit]
        has_e = corpus in pe.CORPORA_WITH_E
        splits = [s for s in ("B", "E") if s in store[unit] or s in sess_tab[unit]]
        U = {"labels": LABELS.get(unit, []), "sessions_in_split": dict(nsplit.get(unit, {})), "has_E": has_e,
             "field_gate": {s: dict(gates[unit][s]) for s in splits}, "results": {}, "cells": {}}
        if not splits:
            for it in N6_ROW.values():
                U["cells"][it] = {"label": "NOT_TESTABLE(no sessions in B or E)"}
            out["units"][unit] = U
            continue
        st_all = pd.concat([x for s in splits for x in sess_tab[unit][s]], ignore_index=True)
        sids_all = sorted(set(st_all.session_id))
        dummy = pd.DataFrame({"session_id": sids_all, "stratum": [None] * len(sids_all)})
        if corpus in ("cc_local", "whowhen"):
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
        pops = {s: {k: cat(unit, s, k) for k in EMPTY} for s in splits}
        if len(splits) == 2:
            pops["BE"] = {k: pd.concat([pops["B"][k], pops["E"][k]], ignore_index=True) for k in EMPTY}
            for k in pops["BE"]:
                for c in ("trunc", "join_clean", "sub_thread", "anc_inflight", "pc_flag", "pc_eligible", "flag"):
                    if c in pops["BE"][k].columns:
                        pops["BE"][k][c] = pops["BE"][k][c].astype(bool)
        acpop = "BE" if "BE" in pops else splits[0]
        g_all = Counter()
        for s in splits:
            g_all.update(gates[unit][s])

        # ------------------------------------------------------------------ N4
        if unit in LAT_UNITS and g_all["pairs"] > 0:
            res = {}
            for s in pops:
                path = f"units.{unit}.results.n4.{s}"
                b = n4_block(pops[s]["W"], pops[s]["G"], path)
                n_cells += 1
                if s in ("B", "E"):
                    b["k_all_pairs_hist"] = {str(k): int(v) for k, v in sorted(khist[unit][s]["k_all_hist"].items())}
                    ka = khist[unit][s]["k_all_hist"]
                    b["all_pairs_counts"] = {"n_stamped_pairs": int(sum(ka.values())),
                                             "k_ge_2": int(sum(v for k, v in ka.items() if k >= 2)),
                                             "k_ge_4": int(sum(v for k, v in ka.items() if k >= 4)),
                                             "note": "all stamped pairs of the unit x split (any tool, qualified or "
                                                     "not), literal k; counts only, no CI"}
                    b["G"]["excluded"] = dict(gex[unit][s])
                    pn = n4_block(pops[s]["W"], pops[s]["G"], path + ".post_hoc_not_a_verdict.k_excluding_nesting",
                                  kcol="k_nonest", detail=False)
                    b["post_hoc_not_a_verdict"] = {
                        "k_excluding_nesting": {"W_delta": pn["W"]["delta"], "G_delta": pn["G"]["delta"],
                                                "W_k_ge_2": pn["W"]["k_ge_2"], "W_k_ge_2_sessions": pn["W"]["k_ge_2_sessions"],
                                                "G_k_ge_2": pn["G"]["k_ge_2"], "G_k_ge_2_sessions": pn["G"]["k_ge_2_sessions"],
                                                "label_under_same_rule": pn["verdict"]["label"],
                                                "k_all_pairs_hist": {str(k): int(v) for k, v in sorted(
                                                    khist[unit][s]["k_all_nonest_hist"].items())}},
                        "main_thread_W_only": {}}
                    Wm = pops[s]["W"][~pops[s]["W"].sub_thread]
                    pm = n4_block(Wm, pops[s]["G"], path + ".post_hoc_not_a_verdict.main_thread_W_only", detail=False)
                    b["post_hoc_not_a_verdict"]["main_thread_W_only"] = {
                        "W_delta": pm["W"]["delta"], "W_k_ge_2": pm["W"]["k_ge_2"],
                        "W_k_ge_2_sessions": pm["W"]["k_ge_2_sessions"], "label_under_same_rule": pm["verdict"]["label"]}
                res[s] = b
            U["results"]["n4"] = res
            lb = res.get("B", {}).get("verdict", {}).get("label")
            le = res.get("E", {}).get("verdict", {}).get("label")
            cell, src, suf = cell_of(lb, le, has_e)
            c = {"label": cell, "before_checks": cell, "B": lb, "E": le, "source": src,
                 "BE_pooled_not_the_cell": res.get("BE", {}).get("verdict", {}).get("label"),
                 "suffix": suf + "".join(f" [{x}]" for x in U["labels"])}
            if any(x in ("ALIVE", "WEAK") for x in (lb, le)):
                print(f"[{time.time() - T0:7.1f}s] checks {unit} n4", flush=True)
                D = (pops[acpop]["W"], pops[acpop]["G"])
                base = res[acpop]["verdict"]["label"]
                ac, st, eff = run_checks("n4", unit, D, base, smeta)
                c["label"], c["checks_applied"] = apply_checks(cell, ac, st, eff)
                c["checks"] = {"artifact_checks": ac, "stratification": st}
            else:
                c["checks"] = {"status": "not required: neither B nor E reached WEAK or better"}
                c["checks_applied"] = []
            U["cells"]["N4"] = c
        elif unit in NOT_TESTABLE_STAMPS:
            U["cells"]["N4"] = {"label": f"NOT_TESTABLE({NOT_TESTABLE_STAMPS[unit]})",
                                "B_E_check": {s: {"pairs": gates[unit][s]["pairs"],
                                                  "pairs_positive_delta": gates[unit][s]["pairs_positive_delta"]}
                                              for s in splits}}
        else:
            U["cells"]["N4"] = {"label": "NOT_TESTABLE(no call/result pairs)" if g_all["pairs"] == 0 else
                                "NOT_TESTABLE(not an S:n4_concurrency unit)"}

        # ------------------------------------------------------------------ N5c
        any_marker = g_all["marked_results"] > 0
        res = {}
        if g_all["pairs"] > 0:
            for item in N5C_ITEMS:
                res[item] = {}
                for s in pops:
                    res[item][s] = n5c_block(pops[s]["tr"], pops[s]["pc5c"], item,
                                             f"units.{unit}.results.n5c.{item}.{s}")
                    if item in N5C_RUN and any_marker:
                        n_cells += 1
            U["results"]["n5c"] = res
        if g_all["pairs"] == 0:
            U["cells"]["N5c_truncation"] = {"label": "NOT_TESTABLE(no tool results)"}
        elif not any_marker:
            U["cells"]["N5c_truncation"] = {"label": "NOT_TESTABLE(no harness truncation markers)",
                                            "field_gate": {s: {"results_with_text": gates[unit][s]["results_with_text"],
                                                               "marked_results": gates[unit][s]["marked_results"]}
                                                           for s in splits}}
        else:
            per = {}
            for item in N5C_RUN:
                lb = res[item].get("B", {}).get("verdict", {}).get("label")
                le = res[item].get("E", {}).get("verdict", {}).get("label")
                cell, src, suf = cell_of(lb, le, has_e)
                c = {"B": lb, "E": le, "cell": cell, "source": src, "suffix": suf,
                     "BE_pooled_not_the_cell": res[item].get("BE", {}).get("verdict", {}).get("label")}
                if any(x in ("ALIVE", "WEAK") for x in (lb, le)):
                    print(f"[{time.time() - T0:7.1f}s] checks {unit} n5c {item}", flush=True)
                    D = (pops[acpop]["tr"], pops[acpop]["pc5c"])
                    base = res[item][acpop]["verdict"]["label"]
                    ac, st, eff = run_checks("n5c", unit, D, base, smeta, sub=item)
                    c["final"], c["checks_applied"] = apply_checks(cell, ac, st, eff)
                    c["checks"] = {"artifact_checks": ac, "stratification": st}
                else:
                    c["final"], c["checks_applied"] = cell, []
                    c["checks"] = {"status": "not required: neither B nor E reached WEAK or better"}
                per[item] = c
            per["cc_lines_tail"] = {"final": "NOT_RUN(A constant INSUFFICIENT_N: n_A 4 < 5)",
                                    "B_marked": res["cc_lines_tail"].get("B", {}).get("marked"),
                                    "E_marked": res["cc_lines_tail"].get("E", {}).get("marked")}
            if "cc_chars_mid" in N5C_RUN and unit in ("swechat/claude_code", "aiv_cc") and                     res["cc_chars_mid"][acpop]["marked"] > 0:
                print(f"[{time.time() - T0:7.1f}s] post hoc raw audit {unit} n5c cc_chars_mid", flush=True)
                per["cc_chars_mid"]["post_hoc_not_a_verdict"] = {
                    "raw_audit_inexact": posthoc_chars_mid_raw(unit, pops[acpop]["tr"])}
            labs = [per[i]["final"] for i in N5C_RUN]
            lv = [x for x in labs if x in LVL]
            item_cell = min(lv, key=lambda x: LVL[x]) if lv else (
                "INSUFFICIENT_N" if all(x == "INSUFFICIENT_N" for x in labs) else labs[0])
            U["cells"]["N5c_truncation"] = {"label": item_cell, "rule": "lowest final label among runnable sub-items with "
                                                                        "an ALIVE/WEAK/DEAD cell (deviation 'N5c item cell')",
                                            "per_item": per, "suffix": "".join(f" [{x}]" for x in U["labels"])}

        # ------------------------------------------------------------------ N5g
        if unit in LAT_UNITS and g_all["pairs"] > 0:
            res = {}
            for s in pops:
                res[s] = n5g_block(pops[s]["cs"], f"units.{unit}.results.n5g.{s}")
                n_cells += 1
            U["results"]["n5g"] = res
            lb = res.get("B", {}).get("verdict", {}).get("label")
            le = res.get("E", {}).get("verdict", {}).get("label")
            cell, src, suf = cell_of(lb, le, has_e)
            labs = list(U["labels"]) + ([N5G_SHELL_LABEL[unit]] if unit in N5G_SHELL_LABEL else [])
            c = {"label": cell, "before_checks": cell, "B": lb, "E": le, "source": src,
                 "BE_pooled_not_the_cell": res.get("BE", {}).get("verdict", {}).get("label"),
                 "suffix": suf + "".join(f" [{x}]" for x in labs)}
            if any(x in ("ALIVE", "WEAK") for x in (lb, le)):
                print(f"[{time.time() - T0:7.1f}s] checks {unit} n5g", flush=True)
                D = {k: pops[acpop][k] for k in ("cs", "cs_nt", "cs_jc")}
                base = res[acpop]["verdict"]["label"]
                ac, st, eff = run_checks("n5g", unit, D, base, smeta)
                c["label"], c["checks_applied"] = apply_checks(cell, ac, st, eff)
                c["checks"] = {"artifact_checks": ac, "stratification": st}
            else:
                c["checks"] = {"status": "not required: neither B nor E reached WEAK or better"}
                c["checks_applied"] = []
            U["cells"]["N5g_cold_start"] = c
        elif unit in NOT_TESTABLE_STAMPS:
            U["cells"]["N5g_cold_start"] = {"label": f"NOT_TESTABLE({NOT_TESTABLE_STAMPS[unit].replace('intervals', 'stamps')})"}
        else:
            U["cells"]["N5g_cold_start"] = {"label": "NOT_TESTABLE(no call/result pairs)" if g_all["pairs"] == 0 else
                                            "NOT_TESTABLE(not an S:n4_concurrency unit)"}
        out["units"][unit] = U
        del pops
        gc.collect()

    out["cells_computed"] = n_cells
    out["deviations"] = DEVIATIONS
    # ------------------------------------------------------------------ N6 cells (mechanical)
    n6 = {}
    for unit, U in out["units"].items():
        n6[unit] = {}
        for nm, row in (("n4", "N4"), ("n5c", "N5c_truncation"), ("n5g", "N5g_cold_start")):
            c = U["cells"].get(row, {})
            rec = {"label": c.get("label"), "suffix": c.get("suffix", "")}
            res = U.get("results", {}).get(nm, {})
            if nm in ("n4", "n5g") and res and c.get("source") in res:
                v = res[c["source"]]["verdict"]
                rec.update({"source_split": c["source"], "B": c.get("B"), "E": c.get("E"),
                            "deciding_number": v.get("deciding_number"), "deciding_path": v.get("deciding_path"),
                            "checks_applied": c.get("checks_applied"), "checks_path": f"units.{unit}.cells.{row}.checks"})
            if nm == "n5c" and "per_item" in c:
                rec["per_item_final"] = {i: x.get("final") for i, x in c["per_item"].items()}
                pick = [i for i in N5C_RUN if c["per_item"][i]["final"] == c.get("label")]
                i = pick[0] if pick else N5C_RUN[0]
                x = c["per_item"][i]
                v = res[i][x["source"]]["verdict"]
                rec.update({"deciding_item": i, "source_split": x["source"], "deciding_number": v.get("deciding_number"),
                            "deciding_path": v.get("deciding_path"), "checks_applied": x.get("checks_applied"),
                            "checks_path": f"units.{unit}.cells.N5c_truncation.per_item.{i}.checks"})
            n6[unit][row] = rec
    out["n6_cells"] = n6
    # ------------------------------------------------------------------ Track B corpora (not run here)
    newc = {}
    for c in ("agentcap", "pub_codex", "tbench2"):
        be = [(pe.CACHE / f"{c}_{x}.parquet").exists() for x in ("B", "E")]
        why = ("B/E IR caches present at write time, but they were still being built while this item ran (none existed "
               "when it started) and the corpus's unit mapping (prereg_e_extensions/<corpus>.json) is not wired into "
               "this script; left to the N6 grid run" if any(be) else "no B/E IR cache under analysis/cache when this ran")
        newc[c] = {"B_cache_exists": be[0], "E_cache_exists": be[1],
                   "cells": {r: f"NOT_RUN(Track B corpus: {why})" for r in N6_ROW.values()}}
    out["track_b_corpora"] = newc
    out["opened_files"] = sorted(set(OPENED)) + [
        "analysis/out/phase_e/prereg_e_calibration.json (A eligibility counts, context only)",
        "C:/Swarms/data/swe-chat-pinned/sessions.parquet (metadata: repo_id, user_id)",
        "analysis/cache/aiv_cu_sessions.parquet (metadata: agent_id, population cells)"]
    out["corrections"] = corrections_block(out)
    out["runtime_s"] = round(time.time() - T0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    OUT.write_text(txt, encoding="utf-8")
    print(f"[{time.time() - T0:7.1f}s] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
