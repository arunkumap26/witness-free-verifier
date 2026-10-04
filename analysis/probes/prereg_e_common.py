"""Phase E pre-registration: the frozen definitions (SPEC_E) and the helper code that implements them.

analysis/prereg_e.json is generated from SPEC_E by analysis/probes/prereg_e_calibration.py, which adds the thresholds it
derives from split A (section `resolved`), the reference numbers it copies from committed Phase B/C/D outputs (section
`references`) and the sha256 provenance. Phase E measurement scripts import this module so that the extraction rules,
detectors, artifact checks and attack injectors they run are the code that was pre-registered. Before running, a
measurement script must call `check_frozen()`: the LF-normalised sha256 of this file must equal prereg_e.json
provenance.spec_module_sha256_lf (core.autocrlf is true in this repo, so raw bytes can differ across checkouts).
Any change after the orchestrator commits it goes to prereg_e.json `change_log` (before / after / reason).

Builds on the Phase B pre-registration (analysis/prereg.json, analysis/probes/prereg_common.py, commit 3df8d28), which
is imported, never edited: pairing, tool keys, error classes, path extraction and the change-point test come from it.

Split rule (asserted in code): calibration reads split A only. Measurement reads B and E. Nothing reads H:
`read_cache` refuses any split outside ("A", "B", "E"), and the E id list is read from <corpus>_EH.json key "E" only by
`split_ids`. The calibration script never opens *_B, *_E or *_EH files.
"""
import hashlib
import json
import math
import re
import zlib
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import error_marker, parse_ts
from analysis.probes import prereg_common as pc

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "analysis" / "cache"
SAMPLES = CACHE / "samples"
OUT_E = ROOT / "analysis" / "out" / "phase_e"
PREREG_E_JSON = ROOT / "analysis" / "prereg_e.json"
SWE_TRANSCRIPTS = Path("C:/Swarms/data/swe-chat-pinned/transcripts")
SWE_SESSIONS = Path("C:/Swarms/data/swe-chat-pinned/sessions.parquet")
SWE_COMMITS = Path("C:/Swarms/data/swe-chat-pinned/commits.parquet")

SEED = stats.SEED            # 20261003: every bootstrap (lib/stats)
SEED_E = stats.SEED + 2      # 20261005: Phase E tamper draws, donor picks, N7 session subsamples (SEED + 1 drew E/H)
SEED_NEW_CORPUS = stats.SEED + 3  # 20261006: A/B/E/H split of any corpus Track B loads later
ALLOWED_SPLITS = ("A", "B", "E")
CORPORA_WITH_E = ("swechat", "aiv_cu")
NO_E_REASON = {
    "cc_local": "all 309 sessions used by A+B (HELDOUT_MANIFEST no_heldout). A post-commit cc_local split is NOT built: "
                "recent local Claude Code sessions include sessions that operate the local Qwen swarm (scope boundary).",
    "aiv_cc": "all 314 runs used by A+B; effectively one agent in one SDK session",
    "whowhen": "all 184 tasks used by A+B",
}

LEVEL = {"ALIVE": 2, "WEAK": 1, "DEAD": 0}

# ============================================================================================================ regexes
# Every Phase E regex is written here once, as a raw string, and copied verbatim into prereg_e.json.
RX_E = {
    # ---- request ids (Anthropic request-id family and 48-bit ms clock layout from phase_c_ids_and_clocks_in_ids.py,
    #      inferred from data, UNVERIFIED against documentation)
    "anthropic_req": r"^req_(?:vrtx_|bdrk_)?01[1-9A-HJ-NP-Za-km-z]{22}$",
    # ---- truncation / loss markers (A3 catalogue, analysis/notes/phase_a_a3.md; used by the truncation artifact check)
    "trunc_chars_mid": r"\.\.\. \[(\d+) characters truncated\] \.\.\.",
    "trunc_lines_tail": r"\[(\d+) lines truncated\]",
    "trunc_persisted": r"^<persisted-output>",
    "trunc_glob": r"\(Results are truncated\. Consider using",
    "trunc_omitted_line": r"\[Omitted long matching line\]",
    "trunc_read_refusal": r"exceeds maximum allowed tokens",
    "trunc_gemini_masked": r"^<tool_output_masked>",
    "trunc_read_window": r"IMPORTANT: The file content has been truncated",
    # ---- background / async results (excluded from every duration statistic)
    "background_result": r"(?i)^(?:Command running in background|Command was manually backgrounded|Process running with session ID)",
    # ---- volatile tokens masked before the determinism comparison (N5a)
    "vol_iso": r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
    "vol_clock": r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b",
    "vol_duration": r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|secs|seconds|m|min|minutes|µs|us|ns)\b",
    "vol_hexaddr": r"\b0x[0-9a-fA-F]{6,}\b",
    "vol_uuid": r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
    "vol_tmp": r"(?:/tmp|/var/folders|/private/var/folders)/[^\s'\"]+",
    "vol_pid": r"(?i)\b(?:pid|process id|PID)[:= ]+\d+",
    "vol_ago": r"\b\d+\s+(?:seconds?|minutes?|hours?|days?)\s+ago\b",
    # ---- ls / git log / grep -n parsing (N5b)
    "ls_long_line": r"^[-dlcbpsD][rwxsStT\-]{9}[@+.]?\s+\d+\s+\S+\s+\S+\s+(\d[\d,.]*[KMGTPB]?)\s+",
    "gitlog_date": r"(?m)^Date:\s+(.+?)\s*$",
    "grep_n_line": r"^(?:(?P<path>[^\n:]+?)[:-])?(?P<line>\d+)[:-]",
    # ---- whitespace fingerprints (N5d)
    "git_status_entry": r"^(\s*)(modified|new file|deleted|renamed|typechange|both modified):\s",
    "wc_line": r"^(\s*)(\d+)(?:\s+\d+){0,2}\s+(\S.*)$",
    "pytest_banner": r"^=+ .+ =+$",
    # ---- error-message fidelity (N5f)
    "py_frame": r"(?m)^\s*File \"(?P<path>[^\"]+)\", line (?P<line>\d+)(?:, in [^\n]+)?\n(?P<src>[^\n]*)$",
    "rust_frame": r"(?m)^\s*--> (?P<path>[^\s:]+):(?P<line>\d+):\d+\s*\n(?:\s*\|\s*\n)?\s*(?P=line)\s*\|\s?(?P<src>[^\n]*)$",
    "read_numbered_line": r"(?m)^\s*(\d+)(?:\u2192|\t)(.*)$",
    # ---- git execution window (R3; COMMIT_RX of phase_c_commit_witness.py)
    "commit_claim": r"(?m)^\[(?P<branch>[^\]\n]{1,200}?) (?:\(root-commit\) )?(?P<sha>[0-9a-f]{7,40})\] ?(?P<subj>[^\n]*)$",
    "git_generator_cmd": r"\bgit\b(?:\s+(?:-C\s+\S+|-c\s+\S+|--no-pager))*\s+(?:commit|merge|cherry-pick|revert|rebase|am|pull)\b",
    "git_explicit_date": r"GIT_COMMITTER_DATE|GIT_AUTHOR_DATE|--date[= ]",
    "reread_program": r"^(?:cat|tail|head|grep|egrep|fgrep|rg|less|more|sed|awk|bat|nl|tac|cut|sort|jq)$",
    # ---- R4 dual-rendering whitelist (frozen now; the five swechat format classes + cc_local empty-file warning)
    "dual_persisted": r"^<persisted-output>",
    "dual_shorter_than_offset": r"shorter than the provided offset",
    "dual_identical_ref": r"(?i)(?:File unchanged since last read|\bidentical to\b)",
    "dual_redaction": r"REDACTED",
    "dual_negative_line": r"(?m)^\s*-\d+(?:\u2192|\t)",
    "dual_empty_file": r"(?i)exists but (?:has )?(?:the contents are |is )?empty",
}
_R = {k: re.compile(v) for k, v in RX_E.items()}

# ---- model-chosen parameter contexts (follow-up 3). An integer occurrence inside an argument string is a PARAMETER if
#      the text immediately before it (<= 48 chars, same line) matches one of these, or it is a JSON-number argument.
PARAM_CONTEXT = {
    "cli_option": r"(?:^|[\s(|;&])--?[A-Za-z][\w\-]*(?:\s*=\s*|\s+)[\"']?$",
    "numeric_positional_cmd": r"(?:^|[\s(|;&])(?:sleep|timeout|gtimeout|head|tail|seq|wait|usleep|ulimit\s+-\w|nice|kill|"
                              r"watch|yes|shuf|split|fold|xargs\s+-n|parallel\s+-j)\s+(?:-\w+\s+)*[\"']?$",
    "param_key_assign": r"(?i)\b[\w.\-]*(?:timeout|sleep|wait|delay|limit|max|min|count|lines|depth|port|size|len|"
                        r"length|width|height|retries|retry|interval|batch|epochs?|steps?|iters?|iterations|workers|"
                        r"threads|jobs|seed|ttl|offset|page|per_page|chunk|buffer|num|number|top|budget|tokens|"
                        r"bytes|ms|secs?|seconds|duration|period|capacity|quota|rate)[\w.\-]*\s*[:=]\s*[\"']?$",
    "call_arg": r"(?:\b(?:range|sleep|setTimeout|setInterval|time\.sleep|asyncio\.sleep|wait_for|waitFor|"
                r"islice|repeat|take|limit|head|tail|nlargest|nsmallest|randint|randrange|zfill)\s*\(\s*"
                r"(?:[^()\n]*,\s*)?)$",
    "host_port": r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]|host\.docker\.internal):$",
    "brace_range": r"\{\d*\.\.$",
    "sql_limit": r"(?i)\b(?:limit|offset|top|fetch first)\s+$",
}
_PARAM = {k: re.compile(v) for k, v in PARAM_CONTEXT.items()}

# ---- read-only shell programs for the determinism pairs (N5a) and their time-dependent exclusions
READONLY_PROGRAMS = {"ls", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "find", "fd", "wc", "stat", "file",
                     "tree", "pwd", "echo", "printf", "which", "type", "realpath", "readlink", "basename", "dirname",
                     "sort", "uniq", "cut", "awk", "diff", "cmp", "md5sum", "sha256sum", "sha1sum", "shasum", "jq",
                     "less", "more", "nl", "od", "xxd", "hexdump", "column", "tr", "comm", "test", "true", "sed", "git"}
GIT_READONLY_SUB = {"status", "log", "diff", "show", "rev-parse", "ls-files", "ls-tree", "blame", "cat-file",
                    "describe", "shortlog", "grep", "merge-base", "rev-list", "branch", "remote", "config", "tag"}
TIME_DEPENDENT_RX = re.compile(r"\$\(date|\$RANDOM|\bdate\b|\buptime\b|\bps\b|\btop\b|\bfree\b|\bdf\b|\bdu\b|"
                               r"\bcurl\b|\bwget\b|\bgit\s+(?:fetch|pull)\b|\btime\b")

# ---- N1 command normalisation
_CD_PREFIX = re.compile(r"^\s*cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*(?:&&|;)\s*")
_TRAIL_REDIR = re.compile(r"\s*2>&1\s*$")
N1_VOLATILE_ARG_KEYS = ("description", "timeout", "timeout_ms", "yield_time_ms", "max_output_tokens", "justification",
                        "sandbox_permissions", "with_escalated_permissions")

# ---- attack grid (N7)
GRID_D = [0.5, 1, 2, 5, 10, 30, 60, 300]
GRID_D_LATE_CHECK = [5, 30, 300]
REWRITE_K = [2, 5]
MATCHED_BYTES_TOL = 0.05
N7_CAP_SESSIONS = 500
N7_MIN_SESSIONS = 30

DOM_SHARE = 0.25
DOM_SESSION = 0.10
AUDIT_K = 30
AUDIT_FAIL = 2

# ============================================================================================================ SPEC_E
SPEC_E = {
    "version": "1.0",
    "title": "Phase E pre-registration: A1 second pass, N1-N5 new candidates, N6 transfer grid, N7 attack battery",
    "status": "Written before any Phase E measurement. Frozen when the orchestrator commits it. Later changes go to "
              "change_log with before/after/reason (README rule 3). Where PREREG_E.md and this JSON differ, the JSON "
              "wins and the difference is a bug to log.",
    "builds_on": {
        "phase_b_prereg": "analysis/prereg.json + analysis/probes/prereg_common.py (commit 3df8d28): every Phase B "
                          "definition (pairing, no-human-wait filter, error classes, Probe 1-4 statistics and verdict "
                          "rules, resolved thresholds from split A) is reused unchanged unless this file says otherwise.",
        "phase_d_ranking": "analysis/out/phase_d/ranking.json final_ranking (five proposals R1-R5); its test_measurement "
                           "and kill rules are adopted where this file names them.",
    },
}

SPEC_E["splits"] = {
    "A": "calibration only (thresholds below come from A; analysis/cache/<corpus>_A.parquet)",
    "B": "Phase B split; Phase C lenses also read it, so B is NOT blind for any Phase C observation",
    "E": "Phase E fresh split from analysis/cache/samples/<corpus>_EH.json key 'E' (swechat 1,825, aiv_cu 2,000; "
         "analysis/HELDOUT_MANIFEST.json). Reported separately from B as the replication.",
    "H": "held-out for the Track C eval. NEVER built, opened or read in Phase E. read_cache() refuses it; split_ids() "
         "reads only key 'E' of the EH file.",
    "re_measurement_population": "B ∪ E pooled (larger n) for every second-pass statistic and every artifact check; E "
                                 "alone for the replication verdict. Units without E (cc_local, aiv_cc, whowhen) are "
                                 "re-measured on B only and labelled UNREPLICATED.",
    "no_E": NO_E_REASON,
    "E_freshness": {
        "rule": "E is fresh for a candidate only if every Phase C number the candidate rests on came from a committed lens "
                "restricted to A/B caches. Committed lenses that read event data beyond B: phase_c_commit_witness.py "
                "(seeded sample of the whole swechat population, plus population metadata), phase_c_swechat_tables.py "
                "(whole swechat population tables and transcripts). Skeptic re-runs described in the Phase C index as "
                "'full population' (raw_census A6-O1/O2, commit_witness O9/O11, swechat_tables T1/T3) also read E and H "
                "sessions. Population METADATA tables (sessions.parquet, swechat_population.parquet, "
                "aiv_cu_sessions.parquet) were read by several lenses; they carry no event data.",
        "E_SEEN_candidates": ["R3_git", "R4_dual", "R5_ledger"],
        "label": "a candidate in E_SEEN_candidates gets the label 'E not blind' on its E result; it can at best reach "
                 "SURVIVES (not blind).",
        "H_caveat": "the same population-level reads touched swechat H sessions for R3/R4/R5 observations. H is still "
                    "untouched by Phase E; Track C must state that R3/R4/R5 H numbers are not fully blind.",
    },
    "new_corpora": {
        "rule": "any corpus Track B downloads gets splits at load time, before any analysis: N sessions after the "
                "loader's field audit; A = min(200, floor(0.2 N)); of the rest R: B = min(2000, floor(R/3)), "
                "E = min(2000, floor(R/3)), H = the remainder. Stratified by lib/sample cells (stratum x length tercile, "
                "floor 5) with seed SEED_NEW_CORPUS = 20261006. A/B/E ids go to cache/samples/<corpus>.json and "
                "<corpus>_EH.json; H ids are hashed into HELDOUT_MANIFEST.json like the existing corpora.",
        "calibration": "unit-specific thresholds (Probe 1 floors and G90, Probe 3 L75, Probe 2 D_unit, N1 residual "
                       "bounds, N2 tau, N5 truncation constants, length terciles) are computed on the new corpus's A by "
                       "prereg_e_calibration.calibrate_unit() and written to "
                       "analysis/out/phase_e/prereg_e_calibration_<corpus>.json BEFORE its B or E is read. The file's "
                       "sha256 is appended to prereg_e.json change_log as a pre-registered extension.",
    },
}

SPEC_E["global"] = {
    "resampling_unit": "session (aiv_cc: run; whowhen: task file), as Phase B",
    "bootstrap": {"n_boot": stats.N_BOOT, "seed": SEED, "impl": "analysis/lib/stats.py + boot_stat() here"},
    "ci_methods": "as prereg.json global.ci_methods: cluster_rate for event rates, cluster_quantile for quantiles, "
                  "wilson for session shares, session-resampled bootstrap (boot_stat) for Spearman/AUC/differences; a "
                  "CI needs >= 900 of 1000 valid draws. Zero numerators report the per-event and per-session Wilson "
                  "upper bounds; verdicts use the per-event Wilson upper bound.",
    "min_n": "as prereg.json global.min_n (rate >= 30 from >= 5 sessions; p50 30, p5/p95 100, p1 500, each from >= 5 "
             "sessions). Item-specific minima below are additional, never weaker.",
    "seeds": {"bootstrap": SEED, "tamper_and_donors": SEED_E, "new_corpus_split": SEED_NEW_CORPUS,
              "per_draw": "rng_for(*parts) = np.random.default_rng(SEED_E + crc32('|'.join(parts)))"},
    "verdict_vocabulary": {
        "mechanism": ["ALIVE", "WEAK", "DEAD", "INSUFFICIENT_N", "INCONCLUSIVE", "NOT_TESTABLE", "NOT_RUN"],
        "second_pass_status": ["SURVIVES", "DOWNGRADED", "KILLED", "UNREPLICATED (suffix)", "NOT_REPLICABLE_AT_N"],
        "n7_cell": ["DETECTS", "PARTIAL", "BLIND", "NA_BLIND_BY_CONSTRUCTION", "INSUFFICIENT_N", "NOT_RUN"],
        "NOT_RUN": "the cell was not computed (blocked or out of time); the reason is stated; never read as a null",
    },
    "multiplicity": "verdicts are descriptive per mechanism x unit x split; no family-wise correction. Every output JSON "
                    "reports the number of verdict cells it computed.",
    "output_contract": "each Phase E script writes raw counts only to analysis/out/phase_e/<name>.json with "
                       "prereg_e.json's sha256 and the spec-module sha256 it ran under; verdicts are computed "
                       "mechanically from the rules here and stored under `verdicts`; interpretation goes to "
                       "analysis/SECOND_PASS.md / DECISION_TABLE.md, never into the JSON.",
    "privacy": "cc_local: aggregates only (no text, commands, paths, ids, session ids). aiv_cc: label 'single-agent "
               "case study' on every number.",
    "scope": "nothing under swarm/, data/swarm/, .claude/worktrees/swarm, ops/state/swarm is read; no agent "
             "transcripts are generated; every positive control uses existing data or synthetic tampering only.",
}

# ------------------------------------------------------------------------------------------------ artifact checks
SPEC_E["artifact_checks"] = {
    "applies_to": "every A1 candidate, and every N1-N5 cell that reaches ALIVE or WEAK on B or E",
    "population": "B ∪ E pooled (B only for units without E)",
    "AC1_parser": {
        "procedure": "audit_sample(): seeded (SEED_E) sample of AUDIT_K = 30 decision events from the statistic's "
                     "numerator (or from its flagged set; if the numerator has < 30 events, all of them). Each is looked "
                     "up in the raw source by (session_id, uuid or call_id) and the fields the statistic uses (stamps, "
                     "call/result join, text length, error flag, request id) are compared with the IR.",
        "fail": f"FAIL if >= {AUDIT_FAIL} of the audited events differ on a field the statistic uses in a way that "
                "changes the event's contribution; 1 = PARSER_NOTE (logged, no effect). cc_local: the comparison is "
                "done in-process and only the match counts are written.",
    },
    "AC2_truncation": {
        "procedure": "recompute the statistic after dropping every event whose result text matches truncated_result() "
                     "(the A3 catalogue: characters-truncated elision, lines-truncated tail cut, persisted-output "
                     "spill, Glob cap, omitted long line, read refusal, Gemini masked output, read window notice, or "
                     "extra.truncated true)",
        "fail": "FAIL if the verdict label changes; the candidate then takes the lower label",
    },
    "AC3_join": {
        "procedure": "recompute on pairs passing join_clean_mask(): (session_id, call_id) unique among calls and among "
                     "results, result seq > call seq, both stamps parse, and the call_id does not occur in another "
                     "session (re-stamped resume/fork copies)",
        "fail": "FAIL if the verdict label changes; the candidate then takes the lower label",
    },
    "AC4_dominance": {
        "clusters": "repo (swechat: sessions.parquet repo_id; aiv_cu: aiv_cu_sessions.parquet agent_id; cc_local: IR "
                    "stratum = project alias; aiv_cc: one agent, always dominated, label only), user (swechat "
                    "sessions.parquet user_id), model (modal non-synthetic model of the session), single session",
        "threshold": f"dominated if one repo, user or model holds > {DOM_SHARE} of the statistic's denominator events "
                     f"(or of its contributing sessions, whichever share is larger), or one session holds > "
                     f"{DOM_SESSION} of the denominator events",
        "procedure": "if dominated: recompute without the dominant cluster (leave-one-cluster-out), and also drop each "
                     "of the 5 largest clusters of the dominating kind one at a time",
        "fail": "DOMINATED if any leave-out drops the label by >= 1 level -> one-level downgrade; if the leave-out falls "
                "below min n -> label UNTESTABLE_WITHOUT_DOMINANT and the candidate is capped at WEAK",
        "threshold_reason": "judgment: 0.25 is the share above which one cluster alone can move a session-clustered "
                            "rate across a verdict boundary; the A-split context (largest repo/model share per unit) is "
                            "in resolved.dominance_context_A. Phase C already reported swechat/opencode 175/214 B "
                            "sessions from one repo (references.opencode_one_repo).",
    },
    "AC5_sampling": {
        "procedure": "post-stratified recompute (post_strat_weights): each session weighted by its population cell size "
                     "/ the number of analysed sessions in that cell, cells = lib/sample cells (stratum x length "
                     "tercile) recomputed from population metadata by population_cells(); ratio estimator "
                     "sum(w num)/sum(w den) with the same session bootstrap (weighted_cluster_rate). The H allocation "
                     "is never read. Corpora without a population table (cc_local, aiv_cc, whowhen): AC5 NOT_RUN.",
        "fail": "FAIL if the weighted label differs from the unweighted one; the candidate then takes the lower label. "
                "Also reported: SHIFT if the B point estimate lies outside the E CI (no verdict effect).",
    },
}

SPEC_E["stratification"] = {
    "axes": {
        "tool": "tool_key (pc.tool_key; cc_local through private_key)",
        "model": "modal non-'<synthetic>' model string of the session",
        "repo": "the AC4 repo cluster",
        "length": "tercile of paired calls per session, cut points = the unit's A-split terciles "
                  "(resolved.length_terciles_A)",
    },
    "reportable_stratum": "meets the candidate's own min n",
    "confinement_rule": "on an axis with >= 2 reportable strata, the signal-bearing strata are those whose label under "
                        "the candidate's rule is >= WEAK. If exactly one stratum is signal-bearing the signal is "
                        "CONFINED on that axis: one-level downgrade (ALIVE -> WEAK, WEAK -> DEAD). With >= 2 "
                        "signal-bearing strata, no effect. With < 2 reportable strata the axis is UNTESTABLE (reported).",
}

SPEC_E["survival_rule"] = {
    "levels": LEVEL,
    "KILLED": "the E verdict is DEAD; or an artifact check FAILs to DEAD; or a candidate-specific kill test fires",
    "DOWNGRADED": "the E verdict is one level below the Phase B verdict; or AC1-AC5 / confinement / a candidate kill "
                  "test lowers it one level (not to DEAD)",
    "SURVIVES": "E verdict >= Phase B verdict, every artifact check passes, not CONFINED or DOMINATED",
    "UNREPLICATED": "units without E: the same checks on B only; status suffix '(B only, unreplicated)'",
    "NOT_REPLICABLE_AT_N": "E is INSUFFICIENT_N for the candidate: status from B ∪ E with the suffix",
    "E_SEEN": "candidates listed in splits.E_freshness.E_SEEN_candidates get the suffix '(E not blind)'",
    "no_rescue": "a check can only lower a label. No post-hoc subset, correction or alternative definition raises a "
                 "verdict; any such number is reported as 'post hoc, not a verdict'.",
    "function": "survival_status()",
}

# ------------------------------------------------------------------------------------------------ A1 candidates
_P1_KILLS = {
    "K1_control_composition": "recompute AUC with G restricted to subagent, webfetch and websearch pairs (Phase B "
                              "latency definition; 'workflow' and 'mcp__village__search_history' excluded) and after "
                              "dropping the single session with most G pairs. AUC label DEAD -> KILLED; G below min n "
                              "(30 pairs from 5 sessions) -> cap WEAK ('control too concentrated').",
    "K2_floor_stability": "Phase B change-point rule (pc.change_point, prereg.json probe1.floor_step_change) on B ∪ E "
                          "and on E. UNSTABLE -> one-level downgrade (Phase B rule). INSUFFICIENT_N (< 30 series or "
                          "< 5 sessions) -> label 'floor untested' (no downgrade).",
    "K3_stamp_quality": "recompute fp_share and AUC excluding pairs with a whole-second call or result stamp; label "
                        "change -> take the lower label",
    "statistic": "fp_share and AUC exactly as prereg.json probe1.separability (W set, G set, tokens_per_char 0.25, "
                 "T_gen >= 1 s, G90 from resolved.probe1.generation_rate) and the Probe 1 verdict rule unchanged",
}
SPEC_E["a1"] = {
    "candidates": {
        "P1/swechat/opencode": {"phase_b": "ALIVE", "has_E": True, "kills": _P1_KILLS,
                                "specific": "AC4 is mandatory: Phase C found 175/214 B sessions from one repo."},
        "P1/cc_local": {"phase_b": "ALIVE", "has_E": False, "kills": _P1_KILLS,
                        "specific": "K1 matters most: the cc_local G control is bimodal (references.cc_local_G_bimodal)."},
        "P1/swechat/claude_code": {
            "phase_b": "WEAK (floor UNSTABLE)", "has_E": True, "kills": _P1_KILLS,
            "specific": "the floor-shift follow-up (followups.F2) decides how to read the UNSTABLE label; it cannot "
                        "raise the verdict (no_rescue): a covariate-corrected floor label is reported as post hoc."},
        "P3zero/swechat/claude_code": {
            "phase_b": "ALIVE", "has_E": True,
            "statistic": "Z = share of long sessions (>= L75 = resolved prereg.json probe3.long_session L75) with zero "
                         "primary errors, Wilson; verdict rule prereg.json probe3.verdict unchanged",
            "kills": {
                "K1_error_capable": "Z over long sessions that have >= 10 shell calls (error-capable). Z > 0.10 -> "
                                    "DOWNGRADED; Z > 0.30 -> KILLED",
                "K2_harness_validation": "Z with cc_tool_use_error removed from the error class (only cc_exit_code and "
                                         "unmarked count). Z > 0.10 -> DOWNGRADED with label 'friction is "
                                         "harness-validation-driven'",
                "K3_strata": "Z per model and per repo stratum (min 20 long sessions). A reportable stratum holding "
                             ">= 0.20 of long sessions with Z > 0.30 -> DOWNGRADED",
                "K4_length": "Z at L90 reported (Phase B 0/224); no verdict effect",
            },
        },
        "P4round/swechat/claude_code": {"phase_b": "ALIVE", "has_E": True, "kills": "followups.F3 (parameter exclusion)",
                                         "statistic": "prereg.json probe4.verdict round_numbers, distinct values"},
        "P4round/cc_local": {"phase_b": "ALIVE", "has_E": False, "kills": "followups.F3 (parameter exclusion)",
                             "statistic": "prereg.json probe4.verdict round_numbers, distinct values"},
        "P4round/swechat/* (pooled)": {
            "phase_b": "ALIVE (pooled Phase B row over all swechat formats; analysis/out/phase_e/decision_table.json)",
            "has_E": True, "kills": "followups.F3 (parameter exclusion), same rule and thresholds",
            "statistic": "prereg.json probe4.verdict round_numbers on the pooled swechat units, distinct values",
            "specific": "added by the pre-registration audit so that no Phase B ALIVE cell escapes the second pass; "
                        "labelled 'pooled'; swechat/claude_code supplies most of its sessions (references.population_B: "
                        "1,679 of 2,000 swechat B sessions), so it is not independent evidence"},
        "P2/swechat/claude_code/main": {"phase_b": "WEAK", "has_E": True},
        "P2/swechat/claude_code/subagent": {"phase_b": "WEAK", "has_E": True},
        "P2/swechat/opencode/subagent": {"phase_b": "WEAK (depends on a logged root-rule deviation)", "has_E": True},
        "P2/swechat/codex/subagent": {"phase_b": "WEAK (S_path_any fallback)", "has_E": True},
        "P2/aiv_cc/main": {"phase_b": "WEAK (S_path_any fallback; one agent)", "has_E": False},
        "R1_bracket": {"phase_b": "UNTESTED (Phase D rank 1)", "has_E": True, "units": ["swechat/claude_code",
                                                                                        "cc_local (B only)"],
                       "followup": "F1"},
        "R2_image": {"phase_b": "UNTESTED (Phase D rank 2)", "has_E": True, "units": ["aiv_cu Gemini strata"]},
        "R3_git": {"phase_b": "UNTESTED (Phase D rank 3)", "has_E": True, "units": ["swechat (all formats with shell)"],
                   "E_label": "E not blind"},
        "R4_dual": {"phase_b": "UNTESTED (Phase D rank 4)", "has_E": True, "units": ["swechat/claude_code (raw)",
                                                                                     "cc_local (raw, B only)"],
                    "E_label": "E not blind"},
        "R5_ledger": {"phase_b": "UNTESTED (Phase D rank 5)", "has_E": True, "units": ["swechat sessions with an "
                                                                                       "Entire tally"],
                      "E_label": "E not blind"},
    },
    "not_carried_into_A1": {
        "cells": ["P1 swechat/codex (WEAK)", "P1 swechat/gemini (WEAK)", "P1 aiv_cc (WEAK)",
                  "P3a whowhen/Algorithm-Generated (WEAK)",
                  "P3b swechat/claude_code, swechat/opencode, cc_local, aiv_cu (WEAK)",
                  "P4a swechat/claude_code, aiv_cu, swechat/* pooled, public/* pooled (WEAK)",
                  "P4b aiv_cu, public/* pooled (WEAK)"],
        "rule": "every Phase B ALIVE or WEAK cell (analysis/out/phase_e/decision_table.json) is either an A1 candidate "
                "above or listed here. Listed cells keep their Phase B verdict, get no A1 kill battery, and are re-run "
                "on E in the N6 grid where the unit has E (pooled rows: no N6 column, Phase B verdict only).",
    },
    "P2_common": {
        "statistic": "S_deep (fallback S_path_any capped at WEAK) exactly as prereg.json probe2; D_unit from "
                     "resolved.probe2.depth_threshold; instrument check rerun on B ∪ E",
        "kills": {
            "K1_root_rule": "recompute with the strict pre-registered workspace-root rule (no Phase B deviation). Label "
                            "DEAD -> KILLED ('rule-sensitive')",
            "K2_context_loss": "S_deep on sessions without compaction, resume or /clear events (record complete). "
                               "Reported only (it can only lower 'unsourced'; no_rescue).",
        },
    },
    "proposal_rules": {
        "verdict_from": "honest false-positive rate on B ∪ E (E separately) and the N7 recall cells for the proposal's "
                        "detector",
        "ALIVE": "session-level (stream-level for R1) honest flag rate <= 0.05 with CI hi <= 0.10, AND >= 1 "
                 "single-call or single-response attack type DETECTS in N7 on E (B for units without E)",
        "WEAK": "honest flag rate <= 0.20 and >= 1 attack type is DETECTS or PARTIAL",
        "DEAD": "honest flag rate > 0.20, or no attack type clears its honest rate",
        "R1_specific": "Step 0 of F1 runs before any R1 claim. If Step 0 is NOT_REPRODUCED, R1 is still measured with "
                       "the Phase E code on B and E, but no Phase C bracket or placebo number is cited as evidence for "
                       "it, and the R1 verdict carries the suffix '(Step 0 NOT_REPRODUCED)'. Phase D kill rule adopted: a tamper type whose "
                       "flagged-stream rate has a session-clustered CI lo <= the honest CI hi is a null for that type; "
                       "if no single-response type other than back-dating clears it, R1 is WEAK ('back-dating only'); "
                       "if 30 s back-dating does not clear it either, DEAD.",
        "R2_specific": "Phase D kill rule adopted: session-level honest flag rate > 0.05 -> DEAD (stop the line). "
                       "Window rule: image_window_violation(). Unit per model string = its A-split modal positive "
                       "increment if it has >= 20 positive A windows, else the A modal unit of its generation family "
                       "('gemini-2.5' or 'gemini-3'); a model with >= 10 GUI windows and zero positive increments on A "
                       "has no image accounting and is NOT_TESTABLE for R2 (reported apart); a model absent from A or "
                       "with < 10 GUI windows on A uses its family unit (resolved.image_units_A.rule). Strata: model "
                       "generation, sessions with <= 40 vs > 40 GUI windows.",
        "R3_specific": "generator-class claims only (git_cmd_class == 'generator'); window [call ts - 2 s, result ts + "
                       "2 s]; non-resolving SHAs abstain (honest non-resolution 0.358, references.git_nonresolution). "
                       "Coverage stop rule: if claims cover < 0.005 of tool results in the unit, the verdict is capped "
                       "at WEAK ('coverage too small').",
        "R4_specific": "needs raw toolUseResult.file.numLines (not in the IR): read from data/swe-chat-pinned "
                       "transcripts for B ∪ E Claude Code sessions, joined on tool_use_id. cc_local raw fields are read "
                       "only from the frozen snapshot data/claude-code-local (the loader's ROOT) for cc_local split B "
                       "session ids, in-process, aggregates only; never from ~/.claude/projects or any other live "
                       "session store (live stores hold sessions that operate the local Qwen swarm: scope boundary). "
                       "A mismatch inside the frozen "
                       "whitelist (dual_whitelisted()) is excused; any other mismatch is unexplained. Adding a whitelist "
                       "class after seeing B or E is a logged change that cannot raise the verdict. If the raw join is "
                       "not implemented: NOT_RUN.",
        "R5_specific": "Entire 5-integer tally (sessions.parquet input/output/cache tokens and api_call_count) against "
                       "a tolerance-0 recount of the session's deduplicated per-response usage; unmatched share is the "
                       "honest rate (Phase C 33/5,701 after the join fix, references.ledger_unmatched). If not "
                       "implemented: NOT_RUN.",
    },
}

# ------------------------------------------------------------------------------------------------ follow-ups
SPEC_E["followups"] = {
    "F1_bracket_failures": {
        "step0_placebo": {
            "requirement": "before ANY bracket claim, a committed analysis/probes script re-implements the bracket and "
                           "the placebo with bracket_responses(), bracket_streams(), placebo_shift(), roll_ids() and runs "
                           "them on the same streams (swechat/claude_code split B, streams with >= 2 decoded responses)",
            "bracket": "per response k (request id decoded to ms, |event - id| <= 1 day): lo_k = ts(last result/user "
                       "event of the same stream before the response's first event) - id_ms; hi_k = ts(response's first "
                       "event) - id_ms. Stream = (session, agent_id if is_subagent else 'main'). L = max lo, U = min hi; "
                       "inconsistent if L - U > 2,000 ms.",
            "placebo": "for each stream, one response chosen uniformly (rng_for('F1', D, session, stream)) has its first "
                       "event moved D earlier (hi_k -= D) for D in {5, 30} s, and D later for D in {5, 30, 300} s; "
                       "roll_ids: every response takes the next response's id (cyclic) - reference only.",
            "reproduction_rule": "REPRODUCED if (a) the honest inconsistent count is within 10 +/- 3 on the same stream "
                                 "set, (b) the 5 s back-date flagged share is within 0.03 of 1,441/3,673 and the 30 s "
                                 "share within 0.01 of 3,581/3,673, and (c) every later shift flags within the honest "
                                 "count +/- 3. Otherwise NOT_REPRODUCED: the Phase C placebo numbers are withdrawn and "
                                 "rank 1 loses its criterion-(a) lead (Phase D condition).",
            "stream_count": "the re-implementation's stream count is reported next to the committed lens's 3,676 "
                            "(references.bracket_B_committed_lens) and the skeptic text's 3,673/3,674 "
                            "(references.placebo_skeptic_text); a different count is reported as such and is not "
                            "reconciled post hoc. The shares in (b) use the re-implementation's own stream count.",
        },
        "benign_categories": {
            "restamped_copy": "the stream holds a request id that also occurs in another session of the corpus "
                              "(resume/fork copy)",
            "clock_step": "piecewise_consistent(): one split point makes both segments consistent (a client clock step "
                          "absorbed by two constant skews)",
            "concurrent_streams": "the L- or U-binding response's previous input event has a different agent_id, or "
                                  "is_subagent is null on a binding event",
            "api_retry": "an api_error event (meta/system subtype api_error or text 'API Error') between the binding "
                         "response's previous input and its first event",
            "compaction": "a compaction event (system text starting 'This session is being continued' or meta subtype "
                          "compact_boundary/microcompact_boundary) between the binding input and response",
            "user_input_binding": "the L-binding input event is a user event (queued prompts are stamped at enqueue)",
            "long_gap": "more than 600 s between the binding input and the binding response",
            "whole_second": "a binding event stamp has no fractional seconds",
            "vertex_or_bedrock": "a binding request id has the vrtx_ or bdrk_ prefix",
        },
        "control": "each category is also measured on a seeded sample of consistent streams (5 per inconsistent stream, "
                   "same unit and split, drawn with rng_for('F1ctl', unit, split)); enrichment = share among "
                   "inconsistent - share among controls",
        "shared_benign_cause": "a category present in >= 0.5 of inconsistent streams with enrichment >= 0.3 and "
                               "detectable from the log itself",
        "corrections": {
            "restamped_copy": "dedupe ids across sessions (keep the copy in the lexicographically smallest session_id)",
            "clock_step": "allow one skew change point per stream (piecewise_consistent)",
            "concurrent_streams": "abstain on the stream",
            "api_retry|compaction|user_input_binding|long_gap": "drop the affected response from L/U (abstain on it)",
            "whole_second|vertex_or_bedrock": "tolerance 3,000 ms",
        },
        "adoption_rule": "a correction is ADOPTED only if, on B, it lowers the honest inconsistent count AND keeps the "
                         "30 s back-date power >= 0.90 AND keeps the 5 s power within 0.05 of the uncorrected detector. "
                         "Adopted corrections are then frozen and applied unchanged on E.",
        "effective_fp": "FP_eff = inconsistent streams under the adopted corrections / streams, session-clustered "
                        "cluster_rate, on E (fresh) and B; reported with the corrected detector's placebo power at "
                        "5 s and 30 s on E. Unexplained streams are listed by category vector (no session ids for "
                        "cc_local).",
    },
    "F2_floor_shift": {
        "population": "Phase B floor_step_change series (qualified pairs, per session x tool_key, n >= 40) on swechat/"
                      "claude_code B ∪ E; the 13.5% is 21/156 eligible SERIES in 18 of 114 eligible sessions "
                      "(references.floor_steps_B), not a session share",
        "replication": "the Phase B step rule (pc.change_point, p <= 0.01 and D* >= log10 2) on E alone; label "
                       "STABLE/UNSTABLE by the Phase B 0.10 rule",
        "covariates": {
            "harness_events": "events of phase_c_changepoints.HARNESS_TYPES (definitions copied in "
                              "covariate_definitions) in the window of W = 5 calls on each side of k*",
            "version_change": "raw Claude Code entry `version` differs between the pre- and post-step segments "
                              "(raw_cc_entries())",
            "cwd_or_branch_change": "raw entry cwd or gitBranch differs between segments",
            "permission_mode_change": "raw entry permissionMode differs between segments",
            "idle_gap": "a wall-clock gap >= 300 s between consecutive events within the window",
            "hook_rate_change": "share of calls with a linked hook_progress event differs by >= 0.5 between segments",
            "tool_mix_shift": "Jensen-Shannon distance (base 2) >= 0.3 between tool_key distributions of the 20 calls "
                              "before and after k*",
            "parallelism_change": "share of calls that are not the last call of their API message differs by >= 0.3",
            "result_size_shift": "|log10(median result bytes after / before)| >= log10 2",
            "subagent_in_flight": "a subagent call is in flight at the step call's stamp",
            "workspace_change": "workspace root (pc.workspace_root) of pre- and post-step read paths differs",
        },
        "control": "for every non-step eligible series, one split point k drawn uniformly in [20, n-20] "
                   "(rng_for('F2', session, tool_key)); covariate rates at k* (step series) vs k (controls)",
        "credited_covariate": "rate at k* minus control rate >= 0.25, and present in >= 3 step series",
        "compromise_signature": "post-step Spearman(result bytes, latency) >= 0.5 with n_post >= 20 while the pre-step "
                                "value is <= 0.2, OR post-step median r = latency / T_gen >= 0.1 (T_gen from the unit's "
                                "G90); computed by compromise_signature()",
        "classes": {"BENIGN": ">= 1 credited covariate present in the window",
                    "COMPROMISE_LIKE": "signature met and no credited covariate",
                    "UNEXPLAINED": "neither"},
        "outcome_rule": "DISMISSIBLE_AS_BENIGN if BENIGN share >= 0.8 of step series and COMPROMISE_LIKE = 0; "
                        "otherwise OPEN. COMPROMISE_LIKE series are listed individually (series index, factor, "
                        "direction, covariate vector) for human review. No verdict changes either way (no_rescue).",
    },
    "F3_round_numbers": {
        "exclusion_set": {
            "json_number": "every JSON-number argument value (a parameter by construction)",
            "string_parameter": "an integer occurrence inside an argument string whose preceding context (<= 48 chars, "
                                "same line) matches PARAM_CONTEXT (CLI option argument, numeric positional of sleep/"
                                "timeout/head/tail/seq/wait/ulimit/nice/kill/watch/xargs -n/parallel -j, key=value or "
                                "key: value with a parameter-like key, call arguments of range/sleep/setTimeout/islice/"
                                "..., host:port, brace range, SQL LIMIT/OFFSET)",
            "value_level_rule_primary": "a distinct T_orig value is EXCLUDED if ANY of its occurrences in call args in "
                                        "the unit is a parameter occurrence (strict)",
            "value_level_rule_secondary": "excluded if its FIRST occurrence (the one that assigned it to T_orig) is a "
                                          "parameter occurrence (reported)",
        },
        "statistic": "last-0 share of the remaining distinct T_orig values (T_orig_noparam) against M_all, B ∪ E and "
                     "E; gap g = p(T_orig_noparam) - p(M_all) and g_full = p(T_orig) - p(M_all) on the same data",
        "verdict": "Phase B round-number rule applied to T_orig_noparam (ALIVE if its CI lo > M_all CI hi + 0.05; WEAK "
                   "if its point > M_all CI hi; DEAD otherwise; >= 100 distinct values from >= 10 sessions). COLLAPSE "
                   "= DEAD: the rule gives DEAD, OR g <= 0.25 x g_full. ALIVE is kept only if the rule gives ALIVE AND "
                   "g >= 0.5 x g_full; otherwise WEAK. Below min n after exclusion: INSUFFICIENT_N and the candidate "
                   "is capped at WEAK ('parameter-confounded, residual untestable').",
        "functions": "int_occurrences(), is_param_occurrence(), classify_args_ints()",
    },
}

# ------------------------------------------------------------------------------------------------ N1-N5
_LAT_UNITS = ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "cc_local", "aiv_cc"]
SPEC_E["n1_conditional_duration"] = {
    "units": _LAT_UNITS,
    "not_testable": {"aiv_cu": "call and result share one stamp", "whowhen": "no stamps", "swechat/cursor": "no results"},
    "scope": "shell family (primary: tool_key 'shell', Codex shell_command/exec_command/local_shell, "
             "mcp__village__bash; write_stdin excluded) and auto_read (secondary)",
    "qualification": "qualify_pairs(unit, u, P, classes=('shell','auto_read')): Phase B no-human-wait rules 1, 3, 4, 5 "
                     "and 6 (rule 2's class list replaced by the scope), positive delta, not backgrounded "
                     "(args run_in_background true, result extra backgroundTaskId, or background_result regex). Labels: "
                     "swechat/claude_code and cc_local shell 'human-wait contaminated (permissionMode not in the IR)'; "
                     "opencode and gemini shell 'permission timing unknown'.",
    "key": "n1_key(): shell -> normalize_command (drop leading 'cd X &&' / 'cd X;' chains, strip a trailing 2>&1, "
           "collapse whitespace) + Codex workdir; read -> path + offset + limit; other tools -> canonical JSON of args "
           "without N1_VOLATILE_ARG_KEYS",
    "repeat_group": "(session, tool_key, key) with >= 2 qualified instances",
    "coverage_first": "RR = qualified calls in a repeat group / qualified calls (cluster_rate). Reported before any other "
                      "N1 number; it bounds coverage.",
    "residual": "n1_residuals(): for instance i, r_i = log10(delta_i) - median log10(delta_j) over the group's other "
                "instances j with the same primary-error status (no reference -> no residual)",
    "honest_statistic": "rho_hon = Spearman(r_i, log10(result bytes_i + 1)) over all residuals, session-bootstrap CI; "
                        "secondary Spearman(r_i, delta log bytes vs the reference median)",
    "positive_control": "synthetic, existing data only: in each group one instance (rng_for('N1pc', session, key)) gets "
                        "delta' = T_gen = result chars x 0.25 / G90(unit) (resolved Phase B); residuals recomputed; "
                        "rho_pc = Spearman(r_i', log10(result bytes_i + 1)) over the TAMPERED instances only (one per "
                        "repeat group; their residuals against the group's untouched instances), session-bootstrap CI. "
                        "The untouched instances' recomputed residuals are not part of rho_pc (in a 2-instance group "
                        "they are the negated tampered residual). Natural control (reported): Spearman(log latency, "
                        "log bytes) of the unit's Phase B G set.",
    "min_n": ">= 200 residuals from >= 20 sessions",
    "detector": "call flagged if r_i < N1_lo or r_i > N1_hi, the A-split 0.5th and 99.5th percentiles of honest "
                "residuals (resolved.n1.<unit>.bounds; pooled over the unit's scope; needs >= 500 A residuals from >= 5 "
                "sessions, else the pooled-all-units bounds with label 'pooled bounds')",
    "verdict": {
        "ALIVE": "rho_hon CI within [-0.15, 0.15], rho_pc CI lo >= 0.30, RR >= 0.10, and the call-level honest flag "
                 "rate at the A bounds <= 0.02 with CI hi <= 0.05",
        "WEAK": "rho_hon point within [-0.15, 0.15] and rho_pc CI lo > rho_hon CI hi, but an ALIVE condition fails "
                "(label names which, e.g. 'coverage' when RR < 0.10)",
        "DEAD": "rho_hon point > 0.15 (honest residual already scales with output size) or rho_pc CI lo <= rho_hon CI hi",
        "threshold_reason": "judgment calls fixed now: |rho| <= 0.15 is 'uncorrelated' at the n expected; 0.30 is the "
                            "smallest positive-control dependence worth a detector; 0.10 coverage is the share below "
                            "which a shell check covers too little of the corpus to matter.",
    },
}
SPEC_E["n2_token_accounting"] = {
    "granularity_check": {
        "definition": "per unit: G1 = share of API responses with >= 1 call that carry both usage_in and usage_out; G2 "
                      "= median per-response max usage_out >= 20 (not a streaming partial); G3 = responses are "
                      "identifiable (api_msg_id, or Codex token_count rows). GRANULAR iff G1 >= 0.9 and G2 and G3.",
        "split": "computed on A in calibration (resolved.n2.<unit>) and re-checked on B and E",
        "aiv_cu": "checked per model stratum (resolved.n2.aiv_cu.by_stratum); N2 runs only on GRANULAR strata, each "
                  "with its own A-split tau; the N6 cell names the strata. The pooled aiv_cu check is reported too.",
        "DEAD": "a unit that is not GRANULAR is DEAD for N2 ('per-turn input/output counts absent')",
    },
    "statistic": "unexplained output U_k = usage_out_k - tau_unit x (chars of assistant text + call args + "
                 "extra.thinking_chars of response k); tau_unit = A-split median of usage_out / chars over responses "
                 "with usage_out >= 50 and chars >= 200 (resolved.n2.<unit>.tau)",
    "detector": "response k flagged if the result of its last call has >= 800 chars and U_k >= 0.5 x tau_unit x "
                "chars(that result)",
    "positive_control": "synthetic inline fabrication: usage_out_k += tau' x chars(result), tau' in {tau, 0.8 tau}; "
                        "recall = flagged share",
    "min_n": ">= 100 eligible responses from >= 10 sessions",
    "verdict": {"ALIVE": "honest flag rate <= 0.05 with CI hi <= 0.10 and recall >= 0.90 at tau' = 0.8 tau",
                "WEAK": "honest flag rate <= 0.20 and recall >= 0.50",
                "DEAD": "otherwise, or not GRANULAR"},
    "limit": "an accounting identity for INLINE fabrication only: text the model's decoder produces is billed as output. "
             "Execution-layer compromise (a fake result returned through the harness) is billed as input on the next "
             "call exactly like a real one, so N2 is blind to it by construction. N2 separates the two threat classes; "
             "it does not detect the second.",
}
SPEC_E["n3_reaction_time"] = {
    "units": _LAT_UNITS,
    "not_testable": {"aiv_cu": "row-insert / shared-turn stamps", "whowhen": "no stamps"},
    "gap": "n3_gaps(): for each batch of results of one thread followed by the thread's next model event (assistant or "
           "call) with no user/system event in between: gap = ts(next model event) - ts(last result of the batch); "
           "bytes = total UTF-8 bytes of the batch's results; gaps <= 0 or > 600 s excluded",
    "per_session": "rho_s = Spearman(gap, bytes) for sessions with >= 20 gaps",
    "statistics": "pooled Spearman with session-bootstrap CI; share of sessions with rho_s <= 0 (Wilson); secondary: "
                  "gap minus usage_out(next response) / G50 where usage exists",
    "detector": "session flagged if rho_s <= 0 (judgment threshold: no positive reaction to size)",
    "positive_control": "within-session permutation of gaps (an author who does not read): recall = flagged share",
    "min_n": ">= 20 sessions with >= 20 gaps",
    "verdict": {"ALIVE": "pooled rho CI lo >= 0.30 and share(rho_s <= 0) <= 0.10 with Wilson hi <= 0.20",
                "WEAK": "pooled rho CI lo > 0", "DEAD": "otherwise"},
    "note": "the gap includes prefill and the next response's generation; prefill also scales with result size, so a "
            "positive rho is not by itself reading time (stated limit).",
}
SPEC_E["n4_concurrency"] = {
    "units": _LAT_UNITS,
    "in_flight": "inflight_counts(): k_i = 1 + #{other calls j of the session (any thread) with call_ts_j <= mid_i <= "
                 "result_ts_j}, mid_i = midpoint of pair i",
    "populations": "W = Phase B qualified work-bound pairs; G = Phase B generation-bound pairs with tool-reported "
                   "durations",
    "statistic": "Delta = median log10(delta | k >= 2) - median log10(delta | k = 1), within tool_key, combined as the "
                 "pair-count-weighted mean over tool_keys with >= 30 pairs in each arm; session-bootstrap CI; Delta_W "
                 "and Delta_G",
    "min_n": ">= 100 pairs at k >= 2 from >= 10 sessions in each population",
    "verdict": {"ALIVE": "Delta_W and Delta_G CIs disjoint and |Delta_W - Delta_G| >= 0.10 decades",
                "WEAK": "CIs disjoint but the difference < 0.10, or Delta_W CI excludes 0 with G below min n",
                "DEAD": "CIs overlap", "INSUFFICIENT_N": "below min n"},
    "also_reported": "in-flight distribution per unit; share of pairs at k >= 4 (peak concurrency, the #67730 class)",
    "n7": "population-level signature, no per-session decision rule: every N7 cell NA_BLIND_BY_CONSTRUCTION",
}
SPEC_E["n5_battery"] = {
    "a_determinism": {
        "pairs": "determinism_pairs(): two calls i < j of one session with the same n1_key, both results present, the "
                 "command read-only (readonly_command(): every pipeline segment's program in READONLY_PROGRAMS, git "
                 "subcommand in GIT_READONLY_SUB, sed without -i, find without -delete/-exec/-execdir/-ok/-okdir/"
                 "-fprint/-fprintf/-fls, sort without -o/--output, no output redirection, no TIME_DEPENDENT_RX "
                 "match) or a read tool with the "
                 "same path/offset/limit; no intervening write between them in the session (any thread): no "
                 "file_write call, no non-read-only shell call, no subagent call, no user event; neither result is "
                 "truncated or a reference stub",
        "statistic": "drift = share of pairs whose results differ after mask_volatile(); also the unmasked "
                     "byte-identical share",
        "min_n": ">= 100 pairs from >= 20 sessions",
        "verdict": {"ALIVE": "drift <= 0.05 with CI hi <= 0.10", "WEAK": "drift <= 0.20", "DEAD": "drift > 0.20"},
        "positive_control": "the second result's last digit edited (sub_single_digit) -> recall",
    },
    "b_sort_order": {
        "checkers": {"ls": "ls_order_violation(): ls with -1 or -l (or piped), without t/S/r/U/f/c/u/v/X/R; violation "
                           "if the names are sorted under none of: byte order, casefold, casefold alnum-only, natural",
                     "git_log": "gitlog_order_violation(): git log without --reverse/--topo-order/--graph; violation if "
                                "a Date: line is later than the previous one. Known honest false-positive source, "
                                "stated now: Date: shows the AUTHOR date, while git log orders by commit date and "
                                "parentage, so rebased, cherry-picked or amended history can violate honestly; it is "
                                "measured, not corrected",
                     "grep_n": "grepn_order_violation(): grep/rg/egrep with -n, or the Grep tool with -n and "
                               "output_mode content; violation if line numbers are not strictly increasing within a "
                               "contiguous file block"},
        "statistic": "per checker: violation share of eligible outputs",
        "min_n": ">= 100 outputs from >= 20 sessions per checker",
        "verdict": {"ALIVE": "violation <= 0.01 with CI hi <= 0.03", "WEAK": "violation <= 0.05", "DEAD": "otherwise"},
        "positive_control": "reorder_lines (adjacent line swap) -> recall",
    },
    "c_truncation_boundary": {
        "items": {"cc_chars_mid": "Claude Code error elision '... [N characters truncated] ...': prefix and suffix "
                                  "lengths in UTF-16 units must equal the A-split modal constants "
                                  "(resolved.n5.truncation_constants). Lengths are RAW: all text before / after the "
                                  "marker, separator newlines included (truncation_info prefix_u16 / suffix_u16; the "
                                  "newline-stripped lengths are kept only as a diagnostic, drafting_notes)",
                  "cc_lines_tail": "'[N lines truncated]': text length before the marker must equal the A modal cap "
                                   "for the tool",
                  "cc_glob_cap": "Glob '(Results are truncated...)': listed path lines must equal the A modal count"},
        "statistic": "exactness share among results carrying the marker",
        "min_n": ">= 50 marked results from >= 10 sessions per item",
        "verdict": {"ALIVE": "exactness >= 0.99 with CI lo >= 0.95", "WEAK": "exactness >= 0.90", "DEAD": "otherwise"},
        "positive_control": "a long real result re-truncated at a uniform random length with the marker appended",
        "constants_rule": "if A has < 5 instances of an item, the constant is INSUFFICIENT_N and the item is NOT_RUN",
    },
    "d_whitespace": {
        "checks": {"ls_long_alignment": "ls -l: the size column's right edge is the same on every entry line",
                   "git_status_tab": "git status long format: change lines start with a tab",
                   "wc_alignment": "wc on >= 2 files: count columns right-aligned to one edge",
                   "pytest_banner": "pytest '=== ... ===' banner lines of one output have equal length"},
        "statistic": "violation share per check",
        "min_n": ">= 100 outputs from >= 20 sessions per check",
        "verdict": {"ALIVE": "violation <= 0.01 with CI hi <= 0.03", "WEAK": "violation <= 0.05", "DEAD": "otherwise"},
        "positive_control": "normalize_ws() (runs of spaces -> one space, tab -> 4 spaces) -> recall",
    },
    "e_size_distribution": {
        "families": "command family = first program + git subcommand (e.g. 'git status', 'ls', 'pytest'); families with "
                    ">= 100 results from >= 10 sessions",
        "statistic": "IQR of log10(result bytes) per family; comparator = IQR of log10 bytes of model-generated text in "
                     "the unit (assistant text events and subagent final results)",
        "verdict": {"WEAK": ">= 0.5 of families have IQR above the comparator's CI hi",
                    "DEAD": "otherwise", "cap": "WEAK at most: population-level, no per-call decision"},
    },
    "f_error_fidelity": {
        "checkable": "error_fidelity_checks(): a Python traceback frame (py_frame) or rustc frame (rust_frame) in a "
                     "primary-error result whose (path key, line N) was displayed earlier in the session by a Read "
                     "result (numbered lines) with no edit/write to that path in between",
        "statistic": "infidelity = share of checkable frames whose quoted source line (stripped) differs from the "
                     "displayed line N (stripped); coverage = checkable frames / error results",
        "min_n": ">= 100 checkable frames from >= 20 sessions",
        "verdict": {"ALIVE": "infidelity <= 0.02 with CI hi <= 0.05", "WEAK": "infidelity <= 0.10", "DEAD": "otherwise"},
        "positive_control": "line number shifted by +7 in the error text -> recall",
    },
    "g_cold_start": {
        "statistic": "cold_start_values(): c_s = log10(delta of the session's first qualified call of tool t) - median "
                     "log10(delta of its later qualified calls of t), t = the session's most frequent qualified tool, "
                     "sessions with >= 5 later calls; pooled median c (cluster_quantile) and share(c_s <= 0)",
        "detector": "session flagged if c_s <= 0",
        "positive_control": "first call's delta replaced by a later call's delta (no cold start) -> recall",
        "min_n": ">= 30 sessions",
        "verdict": {"ALIVE": "median c CI lo >= log10(1.5) and share(c_s <= 0) <= 0.05",
                    "WEAK": "median c CI lo > 0", "DEAD": "otherwise"},
    },
}

# ------------------------------------------------------------------------------------------------ N6
SPEC_E["n6_transfer_grid"] = {
    "rows": ["P1_latency", "P2_knowledge", "P3a_zero_error", "P3b_reaction", "P4a_hex", "P4b_round",
             "R1_bracket", "R2_image", "R3_git", "R4_dual", "R5_ledger", "N1", "N2", "N3", "N4",
             "N5a_determinism", "N5b_sort", "N5c_truncation", "N5d_whitespace", "N5e_size", "N5f_error_fidelity",
             "N5g_cold_start"],
    "columns": ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "swechat/cursor",
                "swechat/copilot", "swechat/simple_text", "cc_local", "aiv_cc", "aiv_cu", "whowhen",
                "+ one column per Track B corpus (split at load time per splits.new_corpora)"],
    "cell_vocabulary": ["ALIVE", "WEAK", "DEAD", "INSUFFICIENT_N", "INCONCLUSIVE", "NOT_TESTABLE(<missing field>)",
                        "NOT_RUN(<reason>)"],
    "required_fields": {
        "P1_latency": "per-call event stamps (distinct call and result), call/result join",
        "P2_knowledge": "call args with paths, result text", "P3a_zero_error": "error signal (native or validated proxy)",
        "P3b_reaction": "error signal", "P4a_hex": "result text and call args", "P4b_round": "result text and call args",
        "R1_bracket": "provider request ids decodable to ms + event stamps",
        "R2_image": "per-response prompt IMAGE token counts + GUI actions",
        "R3_git": "shell results with commit lines + an external commit table linked by repo",
        "R4_dual": "harness structured counters (toolUseResult numLines) in the raw source",
        "R5_ledger": "external usage tally + per-response usage",
        "N1": "per-call stamps + repeated normalized commands", "N2": "per-response usage_in and usage_out (GRANULAR)",
        "N3": "event stamps for results and the next model event", "N4": "per-call intervals",
        "N5a_determinism": "result text + commands", "N5b_sort": "result text + commands",
        "N5c_truncation": "result text with harness truncation markers", "N5d_whitespace": "result text + commands",
        "N5e_size": "result text", "N5f_error_fidelity": "error results + earlier Read results with line numbers",
        "N5g_cold_start": "per-call stamps",
    },
    "fill_rule": "1) field gate: NOT_TESTABLE(<field>) iff a required field is absent from the unit (checked on A in "
                 "calibration, resolved.n6_field_gate_A, and re-checked on B). 2) otherwise run the mechanism's own "
                 "verdict rule on B and on E. The cell shows 'E verdict' where the unit has E and E is not "
                 "INSUFFICIENT_N, else the B verdict with suffix 'B only'; both are stored. For Probes 1-4 on units "
                 "without E (cc_local, aiv_cc, whowhen) the Phase B verdict IS the B run (same data, same frozen code) "
                 "and fills the cell with the suffix 'B only (Phase B run)'. Where a unit has E, Probes 1-4 are re-run "
                 "on E with the Phase B code and thresholds; a cell not re-run is NOT_RUN(reason) with the Phase B "
                 "verdict shown beside it, never copied into it. 3) aiv_cc cells carry 'single-agent'; cc_local cells "
                 "carry 'private'.",
    "transfer_statement": "a mechanism TRANSFERS between two testable units if both cells are >= WEAK; it FAILS TO "
                          "TRANSFER if one is ALIVE and the other DEAD. The grid reports, per mechanism, the counts of "
                          "testable / ALIVE / WEAK / DEAD cells and of failing transfer pairs.",
}

# ------------------------------------------------------------------------------------------------ N7
SPEC_E["n7_attack_battery"] = {
    "sessions": f"per unit and split (B and E; B only for cc_local and aiv_cc): every session with >= 1 eligible target "
                f"for the attack, capped at N7_CAP_SESSIONS = {N7_CAP_SESSIONS} by a seeded draw (rng_for('N7', unit, "
                f"split)); each session is tampered once per cell, from its untampered copy",
    "honest_fpr": "flag rate of the same sessions untampered (session-level; stream-level for R1 as well)",
    "attacks": {
        "time_result_early": f"one qualified pair's result stamp moved D earlier, D in {GRID_D} s (clamped at call ts + "
                             f"1 ms; clamped draws labelled)",
        "time_result_late": f"one result stamp moved D later, D in {GRID_D} s; nothing else moves",
        "time_tail_late": f"one result and every later event of the session moved D later (consistent), D in {GRID_D}",
        "time_tail_early": f"one result and every later event moved D earlier (consistent compression), D in {GRID_D}",
        "time_response_early": f"the first event of one request-id response moved D earlier, D in {GRID_D} (R1 placebo)",
        "time_response_late": f"the same, D later, D in {GRID_D_LATE_CHECK} (one-sidedness check)",
        "id_swap_adjacent": "request ids of two adjacent responses of one stream swapped",
        "id_splice_foreign": "one response's request id replaced by an id from another session of the same unit and "
                             "split; variants 'random' and 'nearest' (decoded time nearest to the target's)",
        "sub_single_flip_error": "one primary-error result replaced by a successful result of the same tool_key from "
                                 "another session (matched bytes within 5%), native_error set False",
        "sub_single_digit": "the last digit of the last integer in one result changed d -> (d+1) mod 10",
        "sub_matched_bytes": "one result text replaced by another REAL result of the same unit and tool_key from "
                             "another session of the same split, byte length within 5% (nearest); variant 'samecmd': "
                             "donor with the same n1_key",
        "rewrite_consistent_k": f"k in {REWRITE_K} consecutive results of one thread replaced by matched-bytes donors, "
                                f"each pair's latency set to its donor's own latency, later events shifted to keep "
                                f"order; ids and usage untouched",
        "reorder_adjacent_pairs": "two adjacent call/result pairs of one thread exchange contents (tool, args, command, "
                                  "result text, error fields); stamps, ids and seq stay",
        "reorder_lines": "two adjacent lines of one result with >= 3 lines swapped",
        "delete_pair": "one call, its result and its nested events removed",
        "delete_response": "every event of one request id removed",
        "insert_pair_consistent": "a donor call+result pair (another session, same unit) inserted after a result event, "
                                  "with the donor's own call gap and latency; later events shifted",
        "insert_pair_squeezed": "the same, squeezed into the existing gap (call at 25%, result at 75% of the gap); "
                                "skipped if the gap < 2 ms",
        "inline_fabrication": "usage_out of one response += tau x chars of its last call's result (the accounting "
                              "footprint of a result the model wrote itself)",
        "image_relabel_gui": "aiv_cu: one GUI call relabelled as shell",
        "image_insert_screenshot": "aiv_cu: a donor GUI call+result inserted with usage untouched",
    },
    "single_call_types": ["time_result_early", "time_result_late", "time_response_early", "id_swap_adjacent",
                          "id_splice_foreign", "sub_single_flip_error", "sub_single_digit", "sub_matched_bytes",
                          "reorder_adjacent_pairs", "reorder_lines", "delete_pair", "delete_response",
                          "insert_pair_consistent", "insert_pair_squeezed", "inline_fabrication",
                          "image_relabel_gui", "image_insert_screenshot"],
    "donors": "drawn only from OTHER REAL results of the same unit and split (never generated text, never H, never "
              "another split); pick_donor() records the byte difference",
    "detectors": {
        "R1_BRACKET": "stream inconsistent: L - U > 2,000 ms (swechat/claude_code, cc_local)",
        "P1_FLOOR": "call: delta <= 0, or delta < the Phase B A-split p1 floor of unit x tool_key (p5 / 2 where p1 is "
                    "not reportable; resolved.n7.floor_thresholds)",
        "P1_GEN": "call: qualified W pair with r = latency / T_gen >= 1 (Phase B FP definition)",
        "N1": "call: residual outside the A bounds",
        "N2": "response: U_k rule", "N3": "session: rho_s <= 0",
        "N5a": "pair: masked mismatch", "N5b": "output: order violation", "N5c": "output: inexact boundary",
        "N5d": "output: whitespace violation", "N5f": "frame: infidelity", "N5g": "session: c_s <= 0",
        "P2_KFN": "call: knowledge_from_nowhere (Phase B definition, D_unit)",
        "P3_ZERO": "session: long (>= L75) with zero primary errors",
        "R2_IMAGE": "window: image_window_violation()", "R3_GIT": "claim: generator-class commit date out of window",
        "R4_DUAL": "Read result: unexplained numLines mismatch (raw; NOT_RUN if not loaded)",
        "R5_LEDGER": "session: tally mismatch (raw; NOT_RUN if not loaded)",
        "N4": "none (NA_BLIND_BY_CONSTRUCTION)",
    },
    "applicability": "a cell whose attack modifies no field its detector reads is NA_BLIND_BY_CONSTRUCTION (counted "
                     "as BLIND in the walk-through table, with the reason); ATTACK_FIELDS and DETECTOR_FIELDS below "
                     "decide it mechanically (applicable())",
    "session_flag": "a session counts as flagged by a detector iff at least one of its decision units (call, response, "
                    "stream, pair, output, frame, window, claim or the session itself, per `detectors`) is flagged; a "
                    "session in which the detector decides no unit abstains. The same aggregation is used on the "
                    "untampered (FPR) and tampered (recall) copies.",
    "statistics": "session-level: FPR (untampered), recall (tampered; abstention counts as not flagged), attributable "
                  "detection ADR = P(flag tampered and not flag honest), localization = share of flagged tampered "
                  "sessions where a flagged unit is the tampered one; Wilson CIs over sessions (one tampered copy "
                  "per session) and the session bootstrap for ADR",
    "cell_label": "n7_cell_label(): DETECTS if recall >= 0.5 and recall CI lo > FPR CI hi; PARTIAL if recall CI lo > "
                  "FPR CI hi; BLIND otherwise; INSUFFICIENT_N below 30 tampered sessions",
    "outputs": "one row per unit x split x mechanism x attack x parameter; never pooled across attack types; the "
               "walk-through table lists every attack type with no DETECTS cell",
    "thresholds_frozen": "no detector threshold is changed after any recall is seen",
}

SPEC_E["outputs"] = {
    "rule": "one committed script per item under analysis/probes/, one raw-count JSON per item under "
            "analysis/out/phase_e/; each JSON carries prereg_e.json's sha256 and provenance.spec_module_sha256",
    "F1": "phase_e_f1_bracket.py -> f1_bracket.json (Step 0 first; nothing else of R1 before it)",
    "F2": "phase_e_f2_floor_shift.py -> f2_floor_shift.json", "F3": "phase_e_f3_round.py -> f3_round.json",
    "A1": "phase_e_a1_<candidate>.py -> a1_<candidate>.json (P1, P2, P3zero, P4round, R1-R5)",
    "N1-N5": "phase_e_n<k>.py -> n<k>.json", "N6": "phase_e_n6_grid.py -> n6_grid.json",
    "N7": "phase_e_n7_attacks.py -> n7_attacks.json (per unit x split shards allowed: n7_attacks_<unit>_<split>.json)",
    "seeds": "N7 session subsample rng_for('N7', unit, split); tamper target rng_for(attack, param, session_id); donor "
             "rng_for('donor', attack, param, session_id); positive controls rng_for('<item>pc', session_id, key)",
}
SPEC_E["drafting_notes"] = [
    {"what": "AC5 sampling check: weights from population metadata (population_cells) instead of the E allocation",
     "when": "while drafting, before any Phase E number",
     "why": "the E allocation sits in <corpus>_EH.json next to the H allocation; population metadata gives the same "
            "cells without touching anything H-related (the cells reproduce samples/<corpus>.json population_by_cell, "
            "checked in prereg_e_calibration.json ac5_population_cells_check)"},
    {"what": "R2 image unit: per-model A unit -> model unit if >= 20 positive A windows, else generation-family unit; "
             "models with >= 10 GUI windows and no positive increment on A are NOT_TESTABLE",
     "when": "after the A calibration's per-model window counts (resolved.image_units_A), before any B or E R2 number",
     "why": "several Gemini model strings have too few A windows for their own lattice unit"},
    {"what": "N2 granularity for aiv_cu checked per model stratum instead of pooled",
     "when": "after the A granularity check (resolved.n2.aiv_cu), before any B or E N2 number",
     "why": "aiv_cu pools strata with and without usage; a pooled G1 below 0.9 would kill N2 in strata that carry "
            "complete per-response usage"},
    {"what": "P1 kill test K1: 'tool-reported durations only' -> 'exclude workflow and search_history pairs'",
     "when": "while drafting, before any Phase E number",
     "why": "the first wording would have removed opencode's subagent control by construction rather than testing it; "
            "the cc_local bimodality concern is the workflow pairs (references.cc_local_G_bimodal)"},
    {"what": "N1 residual bounds: per unit when >= 500 A residuals from >= 5 sessions, else bounds pooled over all "
             "latency units (labelled)",
     "when": "rule written before the calibration ran; the fallback applies where resolved.n1.<unit>.source says so",
     "why": "same min-n logic as the Phase B quantile rule (p1 needs >= 500 from >= 5 sessions)"},
    # ---- pre-registration audit (2026-10-04), before the orchestrator commit and before any B or E number
    {"what": "N5c cc_chars_mid lengths: newline-stripped prefix/suffix -> RAW prefix/suffix (truncation_info); the "
             "stripped lengths stay in the calibration output as a diagnostic",
     "when": "pre-registration audit, after the first A calibration, before any B or E number",
     "why": "rstrip/lstrip('\\n') also removed newlines belonging to the cut text, so honest elisions whose cut text "
            "began or ended with a newline came out 1-2 units short of the harness constant; compare "
            "c_truncation_A.cc_chars_mid prefix_u16_mode (raw) with prefix_u16_stripped_mode in "
            "prereg_e_calibration.json. Left as it was, N5c would have measured a parser artifact"},
    {"what": "N5a readonly_command(): find with -delete/-exec/-execdir/-ok/-okdir/-fprint/-fprintf/-fls and sort with "
             "-o/--output are no longer read-only",
     "when": "pre-registration audit, before any B or E number",
     "why": "they write files; as intervening commands they would hide a real write between a determinism pair"},
    {"what": "N1 rho_pc population fixed to the tampered instances only",
     "when": "pre-registration audit, before any B or E number",
     "why": "over all residuals the control is diluted, and in a 2-instance group the untouched instance's residual "
            "is the negated tampered one, which would push rho_pc towards 0 by construction"},
    {"what": "N7 session_flag aggregation stated (>= 1 flagged decision unit; no decided unit = abstain)",
     "when": "pre-registration audit, before any B or E number", "why": "every N7 cell depends on it; it was implicit"},
    {"what": "F1/R1: consequence of Step 0 NOT_REPRODUCED stated; stream-count reporting rule; F1 control seed",
     "when": "pre-registration audit, before any B or E number",
     "why": "'must reproduce before any R1 claim' left the R1 outcome undefined when Step 0 fails; the committed lens "
            "(3,676), the skeptic text (3,673) and the brief (3,674) give three stream counts"},
    {"what": "R4: cc_local raw source pinned to the data/claude-code-local snapshot, B ids only",
     "when": "pre-registration audit, before any B or E number",
     "why": "scope boundary: live Claude Code session stores hold sessions that operate the local Qwen swarm"},
    {"what": "A1: P4round/swechat/* (pooled, Phase B ALIVE) added as a candidate under F3; a1.not_carried_into_A1 lists "
             "every other Phase B ALIVE/WEAK cell left out of A1",
     "when": "pre-registration audit, before any B or E number",
     "why": "the pooled ALIVE row and the WEAK cells P3a whowhen/Algorithm-Generated, P4b aiv_cu and the public/* "
            "pooled rows were neither candidates nor listed as excluded"},
    {"what": "N5b git log: author-date false-positive source stated", "when": "pre-registration audit",
     "why": "stated before measurement so an honest DEAD is not read as a fabrication signal"},
]
SPEC_E["change_log"] = []

ATTACK_FIELDS = {
    "time_result_early": {"ts"}, "time_result_late": {"ts", "order"}, "time_tail_late": {"ts"},
    "time_tail_early": {"ts"}, "time_response_early": {"ts"}, "time_response_late": {"ts"},
    "id_swap_adjacent": {"request_id"}, "id_splice_foreign": {"request_id"},
    "sub_single_flip_error": {"text", "error"}, "sub_single_digit": {"text"}, "sub_matched_bytes": {"text", "error"},
    "rewrite_consistent_k": {"text", "error", "ts"}, "reorder_adjacent_pairs": {"text", "args", "error", "order"},
    "reorder_lines": {"text"}, "delete_pair": {"text", "args", "events", "ts"},
    "delete_response": {"text", "args", "events", "request_id", "ts"},
    "insert_pair_consistent": {"text", "args", "events", "ts"}, "insert_pair_squeezed": {"text", "args", "events", "ts"},
    "inline_fabrication": {"usage"}, "image_relabel_gui": {"tool"}, "image_insert_screenshot": {"tool", "events"},
}
DETECTOR_FIELDS = {
    "R1_BRACKET": {"ts", "request_id", "events"}, "P1_FLOOR": {"ts", "order"}, "P1_GEN": {"ts", "text"},
    "N1": {"ts", "text", "args"}, "N2": {"usage", "text"}, "N3": {"ts", "text", "order", "events"},
    "N5a": {"text", "args", "events"}, "N5b": {"text"}, "N5c": {"text"}, "N5d": {"text"},
    "N5f": {"text", "error", "events"}, "N5g": {"ts", "events"}, "P2_KFN": {"text", "args", "events", "error"},
    "P3_ZERO": {"error", "events"}, "R2_IMAGE": {"tool", "usage", "events"}, "R3_GIT": {"text", "ts", "args"},
    "R4_DUAL": {"text"}, "R5_LEDGER": {"usage", "events"}, "N4": set(),
}
SPEC_E["n7_attack_battery"]["attack_fields"] = {k: sorted(v) for k, v in ATTACK_FIELDS.items()}
SPEC_E["n7_attack_battery"]["detector_fields"] = {k: sorted(v) for k, v in DETECTOR_FIELDS.items()}

SPEC_E["covariate_definitions"] = {
    "source": "copied from analysis/probes/phase_c_changepoints.py HARNESS_DEFS (committed) so the F2 covariates are "
              "frozen here; the measurement script may call phase_c_changepoints.harness_events for the same types",
    "harness_types": ["compaction", "context_clear", "slash_command", "skill_injection", "model_switch",
                      "setting_change", "subagent_start", "user_turn", "resume", "version_change", "api_error",
                      "interrupt", "tool_timeout", "task_notification", "rollback"],
}

SPEC_E["functions"] = {
    "guards": ["read_cache", "split_ids", "check_frozen", "sha256_lf"],
    "stratifiers_and_checks": ["session_cluster_map", "session_model_map", "length_tercile_map", "dominance",
                               "truncated_result", "join_clean_mask", "audit_sample", "population_cells",
                               "post_strat_weights",
                               "weighted_cluster_rate", "boot_stat", "spearman", "survival_status", "confinement"],
    "F1": ["decode_req_ms", "bracket_responses", "bracket_streams", "placebo_shift", "roll_ids",
           "piecewise_consistent", "bracket_benign_categories"],
    "F2": ["raw_cc_entries", "js_distance", "compromise_signature"],
    "F3": ["int_occurrences", "is_param_occurrence", "classify_args_ints"],
    "pairs": ["qualify_pairs"],
    "N1": ["normalize_command", "n1_key", "n1_residuals"], "N2": ["response_table", "granularity", "n2_flags"],
    "N3": ["n3_gaps"], "N4": ["inflight_counts"],
    "N5": ["readonly_command", "mask_volatile", "determinism_pairs", "ls_order_violation", "gitlog_order_violation",
           "grepn_order_violation", "ws_violations", "normalize_ws", "truncation_info", "error_fidelity_checks",
           "cold_start_values"],
    "R2": ["image_windows", "image_window_violation"], "R3": ["git_cmd_class", "commit_claims", "git_window_ok"],
    "R4": ["dual_whitelisted"],
    "N7": ["rng_for", "pick_donor", "applicable", "n7_cell_label", "atk_time", "atk_id_swap", "atk_id_splice",
           "atk_substitute", "atk_digit", "atk_rewrite_consistent", "atk_reorder_pairs", "atk_reorder_lines",
           "atk_delete_pair", "atk_delete_response", "atk_insert_pair", "atk_inline_fabrication",
           "atk_image_relabel"],
}


# ============================================================================================================ guards
def _s(x):
    """str or '' (pd.NA / None / NaN safe)."""
    return x if isinstance(x, str) else ""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256_lf(path):
    """sha256 of the file with CRLF normalised to LF (core.autocrlf is true in this repo, so a checkout elsewhere can
    change line endings without changing content)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def check_frozen():
    """Measurement scripts call this first: the module must be the pre-registered one (line-ending insensitive)."""
    pj = json.loads(PREREG_E_JSON.read_text(encoding="utf-8"))
    want = pj["provenance"]["spec_module_sha256_lf"]
    got = sha256_lf(Path(__file__))
    assert got == want, f"prereg_e_common.py changed since pre-registration ({got} != {want}); log it in change_log"
    return pj


def read_cache(corpus, split, columns, allowed=("B", "E"), filters=None):
    """The only sanctioned reader of IR caches in Phase E. Refuses H and any split not in `allowed`."""
    assert split in ALLOWED_SPLITS, f"split {split!r} is not readable in Phase E"
    assert split in allowed, f"split {split!r} not allowed for this caller ({allowed})"
    if split == "E":
        assert corpus in CORPORA_WITH_E or (SAMPLES / f"{corpus}_EH.json").exists(), f"{corpus} has no E split"
    path = CACHE / f"{corpus}_{split}.parquet"
    assert "_H" not in path.name and "heldout" not in path.name.lower()
    df = pd.read_parquet(path, columns=columns, filters=filters)
    if "session_id" in df.columns:
        df["session_id"] = df["session_id"].astype(str)
    return df


def split_ids(corpus, split):
    """Session ids of split A, B (samples/<corpus>.json) or E (samples/<corpus>_EH.json key 'E' only). Never H."""
    assert split in ALLOWED_SPLITS
    if split in ("A", "B"):
        return list(json.loads((SAMPLES / f"{corpus}.json").read_text(encoding="utf-8"))[split])
    eh = json.loads((SAMPLES / f"{corpus}_EH.json").read_text(encoding="utf-8"))
    ids = list(eh["E"])
    del eh
    return ids


# ============================================================================================================ stats
def rng_for(*parts):
    return np.random.default_rng(SEED_E + zlib.crc32("|".join(str(p) for p in parts).encode("utf-8")))


def spearman(x, y):
    from scipy.stats import spearmanr
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3 or np.all(x[ok] == x[ok][0]) or np.all(y[ok] == y[ok][0]):
        return None
    return float(spearmanr(x[ok], y[ok]).statistic)


def boot_stat(groups, fn, n_boot=stats.N_BOOT, seed=SEED):
    """Session bootstrap of a statistic. groups: list of per-session payloads; fn(list_of_payloads) -> float|None.
    Returns dict(value, lo, hi, valid_draws, ci_reported) per SPEC_E global.ci_methods."""
    val = fn(groups)
    rng = np.random.default_rng(seed)
    n = len(groups)
    draws = []
    if n >= 2:
        for _ in range(n_boot):
            pick = rng.integers(0, n, size=n)
            v = fn([groups[i] for i in pick])
            if v is not None and np.isfinite(v):
                draws.append(v)
    out = {"value": val, "n_sessions": n, "valid_draws": len(draws), "ci_reported": len(draws) >= 900}
    if out["ci_reported"]:
        out["lo"], out["hi"] = float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))
    return out


def session_spearman(x, y, sids):
    """Pooled Spearman with a session-bootstrap CI."""
    df = pd.DataFrame({"x": x, "y": y, "s": sids})
    groups = [(g.x.to_numpy(), g.y.to_numpy()) for _, g in df.groupby("s")]

    def fn(gs):
        if not gs:
            return None
        return spearman(np.concatenate([a for a, _ in gs]), np.concatenate([b for _, b in gs]))
    return boot_stat(groups, fn)


def rate_by_session(flags, sids):
    num, den = Counter(), Counter()
    for f, s in zip(flags, sids):
        den[s] += 1
        num[s] += int(bool(f))
    keys = list(den)
    r = stats.cluster_rate([num[k] for k in keys], [den[k] for k in keys])
    if r["num"] == 0 and r["den"] > 0:
        r["wilson_hi_per_event"] = stats.wilson(0, int(r["den"]))[2]
        r["wilson_hi_per_session"] = stats.wilson(0, int(r["n_sessions"]))[2]
    return r


def weighted_cluster_rate(num, den, w, n_boot=stats.N_BOOT, seed=SEED):
    num, den, w = (np.asarray(a, dtype=float) for a in (num, den, w))
    keep = den > 0
    num, den, w = num[keep], den[keep], w[keep]
    n = len(den)
    if n == 0:
        return {"rate": None}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    b = (w[idx] * num[idx]).sum(1) / np.maximum((w[idx] * den[idx]).sum(1), 1e-12)
    return {"rate": float((w * num).sum() / (w * den).sum()), "lo": float(np.quantile(b, 0.025)),
            "hi": float(np.quantile(b, 0.975)), "n_sessions": int(n)}


# ============================================================================================================ strata
def swechat_session_meta(session_ids, columns=("session_id", "repo_id", "user_id")):
    """swechat sessions.parquet rows for the given ids only (pyarrow filter; no other row is materialised)."""
    import pyarrow.parquet as pq
    ids = sorted(set(str(s) for s in session_ids))
    if not ids:
        return pd.DataFrame(columns=list(columns))
    t = pq.read_table(SWE_SESSIONS, columns=list(columns), filters=[("session_id", "in", ids)])
    return t.to_pandas()


def session_cluster_map(corpus, u, kind="repo"):
    """{session_id: cluster label} for AC4. kind in ('repo', 'user')."""
    sids = sorted(u.session_id.unique())
    if corpus == "swechat":
        m = swechat_session_meta(sids)
        col = "repo_id" if kind == "repo" else "user_id"
        d = dict(zip(m.session_id.astype(str), m[col].astype(str)))
        return {s: d.get(s, "unknown") for s in sids}
    if corpus == "aiv_cu":
        import pyarrow.parquet as pq
        t = pq.read_table(CACHE / "aiv_cu_sessions.parquet", columns=["session_id", "agent_id"],
                          filters=[("session_id", "in", sids)]).to_pandas()
        d = dict(zip(t.session_id.astype(str), t.agent_id.astype(str)))
        return {s: d.get(s, "unknown") for s in sids}
    if corpus in ("cc_local", "whowhen"):
        st = u.groupby("session_id").stratum.first()
        return {s: str(st.get(s, "unknown")) for s in sids}
    return {s: corpus for s in sids}  # aiv_cc: one agent


def session_model_map(u):
    m = u[u.model.notna() & (u.model.astype(str) != "<synthetic>")]
    out = {}
    for s, g in m.groupby("session_id"):
        out[s] = str(g.model.astype(str).value_counts().index[0])
    return {s: out.get(s, "unknown") for s in u.session_id.unique()}


def length_tercile_map(n_calls_by_session, cuts):
    lo, hi = cuts
    return {s: ("short" if n <= lo else "mid" if n <= hi else "long") for s, n in n_calls_by_session.items()}


# ============================================================================================================ artifact checks
def dominance(weight_by_session, cluster_by_session):
    """Max share of the denominator held by one cluster (and by one session). weight = denominator events per session."""
    tot = float(sum(weight_by_session.values()))
    if tot <= 0:
        return {"dominated": False, "total": 0}
    cw = Counter()
    cs = Counter()
    for s, w in weight_by_session.items():
        c = cluster_by_session.get(s, "unknown")
        cw[c] += w
        cs[c] += 1
    n_s = len(weight_by_session)
    top = cw.most_common(5)
    share_ev = top[0][1] / tot
    share_s = cs[top[0][0]] / n_s
    top_sess = max(weight_by_session.items(), key=lambda kv: kv[1])
    return {"top_clusters": [(c, w / tot, cs[c] / n_s) for c, w in top],
            "top_cluster": top[0][0], "top_share_events": share_ev, "top_share_sessions": share_s,
            "top_session_share_events": top_sess[1] / tot,
            "dominated": max(share_ev, share_s) > DOM_SHARE or top_sess[1] / tot > DOM_SESSION,
            "n_clusters": len(cw), "total": tot}


def truncated_result(text, extra=None):
    t = text if isinstance(text, str) else ""
    for k in ("trunc_chars_mid", "trunc_lines_tail", "trunc_glob", "trunc_omitted_line", "trunc_read_refusal",
              "trunc_read_window"):
        if _R[k].search(t):
            return True
    if _R["trunc_persisted"].search(t) or _R["trunc_gemini_masked"].search(t):
        return True
    if isinstance(extra, str) and '"truncated"' in extra:
        x = pc.jl(extra)
        if x.get("truncated") is True:
            return True
    return False


def join_clean_mask(df, P, copied_call_ids=frozenset()):
    """Boolean mask over pairs P (from pc.make_pairs on df): unique keys, result after call, stamps parse, no copy."""
    c = df[df.kind == "call"].groupby(["session_id", "call_id"]).size()
    r = df[(df.kind == "result") & df.call_id.notna()].groupby(["session_id", "call_id"]).size()
    keys = list(zip(P.session_id, P.call_id.astype(str)))
    cu = {k for k, v in c.items() if v == 1}
    ru = {k for k, v in r.items() if v == 1}
    ok = np.array([(s, ci) in cu and (s, ci) in ru for s, ci in zip(P.session_id, P.call_id)])
    ok &= (P.seq_r.to_numpy() > P.seq.to_numpy())
    ok &= np.isfinite(P.delta_s.to_numpy()) if "delta_s" in P else True
    ok &= np.array([k[1] not in copied_call_ids for k in keys])
    return ok


def audit_sample(keys, k=AUDIT_K, seed_parts=("audit",)):
    keys = list(keys)
    if len(keys) <= k:
        return keys
    rng = rng_for(*seed_parts)
    return [keys[i] for i in sorted(rng.choice(len(keys), size=k, replace=False))]


def population_cells(corpus):
    """{session_id: lib/sample cell} over the whole population, replicating lib/sample.draw (stratum x length tercile,
    rank 'first' on the population table order before any permutation). Population METADATA only (no event data)."""
    if corpus == "swechat":
        p = pd.read_parquet(CACHE / "swechat_population.parquet", columns=["session_id", "stratum", "length"])
    elif corpus == "aiv_cu":
        p = pd.read_parquet(CACHE / "aiv_cu_sessions.parquet", columns=["session_id", "stratum", "n_turns"])
        p = p.rename(columns={"n_turns": "length"})
    else:
        raise ValueError(f"no population table registered for {corpus}")
    p = p.drop_duplicates("session_id").reset_index(drop=True)
    p["stratum"] = p["stratum"].fillna("unknown").astype(str)
    q = p["length"].rank(method="first", pct=True)
    terc = np.where(q <= 1 / 3, "short", np.where(q <= 2 / 3, "mid", "long"))
    return dict(zip(p.session_id.astype(str), p["stratum"] + "|" + terc))


def post_strat_weights(corpus, session_ids, cells=None):
    """AC5 weight per session: population cell size / number of the given sessions in that cell. Uses population
    metadata and the given ids only (never the H allocation)."""
    cells = cells or population_cells(corpus)
    popn = Counter(cells.values())
    mine = {s: cells.get(str(s), "unknown") for s in session_ids}
    n_in = Counter(mine.values())
    return {s: (popn.get(c, 0) / n_in[c]) if n_in[c] else 0.0 for s, c in mine.items()}


def confinement(stratum_labels):
    """stratum_labels: {stratum: label or None (not reportable)}. Returns 'CONFINED', 'OK' or 'UNTESTABLE'."""
    rep = {k: v for k, v in stratum_labels.items() if v in LEVEL}
    if len(rep) < 2:
        return "UNTESTABLE"
    sig = [k for k, v in rep.items() if LEVEL[v] >= 1]
    return "CONFINED" if len(sig) == 1 else "OK"


def downgrade(label, n=1):
    if label not in LEVEL:
        return label
    inv = {v: k for k, v in LEVEL.items()}
    return inv[max(0, LEVEL[label] - n)]


def survival_status(phase_b_label, e_label, checks, has_e=True, e_seen=False):
    """phase_b_label/e_label: ALIVE|WEAK|DEAD|INSUFFICIENT_N|...; checks: list of dicts {name, effect} with effect in
    ('pass', 'downgrade', 'kill', 'cap_weak'). Returns (status, final_label, reasons)."""
    reasons = []
    base = phase_b_label if phase_b_label in LEVEL else None
    label = e_label if (has_e and e_label in LEVEL) else base
    suffix = ""
    if not has_e:
        suffix = " (B only, unreplicated)"
    elif e_label not in LEVEL:
        suffix = " (NOT_REPLICABLE_AT_N)"
    if e_seen:
        suffix += " (E not blind)"
    if label is None:
        return "NOT_RUN" + suffix, None, ["no usable label"]
    status = "SURVIVES"
    if has_e and e_label in LEVEL and base is not None and LEVEL[e_label] < LEVEL[base]:
        status = "KILLED" if e_label == "DEAD" else "DOWNGRADED"
        reasons.append(f"E {e_label} below Phase B {base}")
    for c in checks:
        eff = c.get("effect", "pass")
        if eff == "kill":
            label, status = "DEAD", "KILLED"
            reasons.append(c["name"])
        elif eff == "downgrade":
            label = downgrade(label)
            reasons.append(c["name"])
            if label == "DEAD":
                status = "KILLED"
            elif status == "SURVIVES":
                status = "DOWNGRADED"
        elif eff == "cap_weak" and LEVEL.get(label, 0) > 1:
            label = "WEAK"
            reasons.append(c["name"])
            if status == "SURVIVES":
                status = "DOWNGRADED"
    if label == "DEAD":
        status = "KILLED"
    return status + suffix, label, reasons


# ============================================================================================================ F1 bracket
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58I = {c: i for i, c in enumerate(_B58)}
_WIN = (int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000), int(pd.Timestamp("2027-01-01", tz="UTC").value // 1_000_000))
BRACKET_TOL_MS = 2000.0


def decode_req_ms(s):
    """Anthropic request id -> embedded ms (top 48 bits of the base58 body after '01'), or None."""
    if not isinstance(s, str) or not _R["anthropic_req"].match(s):
        return None
    body = s.rsplit("_", 1)[1][2:]
    v = 0
    for ch in body:
        v = v * 58 + _B58I[ch]
    top = v >> 80
    return float(top) if _WIN[0] <= top < _WIN[1] else None


def _ms(ts_series):
    t = pd.to_datetime(ts_series, utc=True, format="ISO8601", errors="coerce")
    return ((t - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() * 1000.0).astype(float).to_numpy()


def _stream(is_sub, agent):
    return [(a if isinstance(a, str) and a else "?") if bool(b) else "main"
            for b, a in zip(pd.Series(is_sub).astype("boolean").fillna(False), pd.Series(agent).astype(object))]


def bracket_responses(u):
    """One row per (session, stream, request id): first event seq/ms, previous input (result|user) seq/ms/kind, id ms,
    lo, hi. u: IR rows of one unit (any number of sessions). Ids whose |first event - id| > 1 day are dropped."""
    u = u.assign(_ms=_ms(u.ts), _stream=_stream(u.is_subagent, u.agent_id))
    R = u[u.request_id.notna()].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "request_id"])
    R = R.assign(emb=[decode_req_ms(x) for x in R.request_id.astype(object)])
    R = R[R.emb.notna() & np.isfinite(R._ms)]
    R = R[(R._ms - R.emb).abs() <= 86_400_000]
    inp = u[u.kind.isin(["result", "user"]) & np.isfinite(u._ms)][["session_id", "_stream", "seq", "_ms", "kind",
                                                                    "agent_id"]]
    R = R.sort_values("seq")
    inp = inp.sort_values("seq").rename(columns={"seq": "prev_seq", "_ms": "prev_ms", "kind": "prev_kind",
                                                 "agent_id": "prev_agent"})
    M = pd.merge_asof(R[["session_id", "_stream", "seq", "_ms", "emb", "request_id", "agent_id", "is_subagent", "ts"]],
                      inp, left_on="seq", right_on="prev_seq", by=["session_id", "_stream"], direction="backward",
                      allow_exact_matches=False)
    M = M.rename(columns={"_stream": "stream", "_ms": "first_ms"})
    M["lo"] = M.prev_ms - M.emb
    M["hi"] = M.first_ms - M.emb
    return M.sort_values(["session_id", "stream", "seq"]).reset_index(drop=True)


def bracket_streams(R, tol_ms=BRACKET_TOL_MS):
    """Per stream with >= 2 responses: L, U, gap = L - U, inconsistent, binding response indices."""
    rows = []
    for (s, st), g in R.groupby(["session_id", "stream"], sort=False):
        if len(g) < 2:
            continue
        lo, hi = g.lo.to_numpy(), g.hi.to_numpy()
        L = np.nanmax(lo) if np.isfinite(lo).any() else np.nan
        U = np.nanmin(hi)
        gap = L - U
        rows.append({"session_id": s, "stream": st, "n": len(g), "L": L, "U": U, "gap": gap,
                     "inconsistent": bool(np.isfinite(gap) and gap > tol_ms),
                     "k_L": int(g.index[np.nanargmax(lo)]) if np.isfinite(lo).any() else None,
                     "k_U": int(g.index[np.nanargmin(hi)])})
    return pd.DataFrame(rows)


def placebo_shift(R, D_ms, tag="F1"):
    """Move the first event of one uniformly chosen response per stream by -D_ms (D > 0 = earlier). Returns a copy."""
    R = R.copy()
    for (s, st), g in R.groupby(["session_id", "stream"], sort=False):
        if len(g) < 2:
            continue
        rng = rng_for(tag, D_ms, s, st)
        i = g.index[int(rng.integers(0, len(g)))]
        R.at[i, "first_ms"] = R.at[i, "first_ms"] - D_ms
        R.at[i, "hi"] = R.at[i, "hi"] - D_ms
    return R


def roll_ids(R):
    """Every response takes the next response's id (cyclic within the stream). Reference only."""
    R = R.copy()
    for (s, st), g in R.groupby(["session_id", "stream"], sort=False):
        if len(g) < 2:
            continue
        emb = np.roll(g.emb.to_numpy(), -1)
        R.loc[g.index, "emb"] = emb
        R.loc[g.index, "lo"] = g.prev_ms.to_numpy() - emb
        R.loc[g.index, "hi"] = g.first_ms.to_numpy() - emb
    return R


def piecewise_consistent(lo, hi, tol_ms=BRACKET_TOL_MS):
    """True if one split point (both segments >= 1 response) makes both segments consistent."""
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    n = len(hi)
    for k in range(1, n):
        ok = True
        for a, b in ((0, k), (k, n)):
            sl, sh = lo[a:b], hi[a:b]
            L = np.nanmax(sl) if np.isfinite(sl).any() else -np.inf
            if L - np.nanmin(sh) > tol_ms:
                ok = False
                break
        if ok:
            return True
    return False


def bracket_benign_categories(u, R, stream_row, copied_ids=frozenset()):
    """Category set (SPEC_E followups.F1_bracket_failures.benign_categories) for one stream row of bracket_streams."""
    g = R[(R.session_id == stream_row["session_id"]) & (R.stream == stream_row["stream"])]
    cats = set()
    if any(x in copied_ids for x in g.request_id.astype(str)):
        cats.add("restamped_copy")
    if piecewise_consistent(g.lo.to_numpy(), g.hi.to_numpy()):
        cats.add("clock_step")
    s_ev = u[u.session_id == stream_row["session_id"]]
    for kname in ("k_L", "k_U"):
        k = stream_row.get(kname)
        if k is None or k not in R.index:
            continue
        row = R.loc[k]
        if pd.isna(row.get("is_subagent")):
            cats.add("concurrent_streams")
        pa = row.get("prev_agent")
        if bool(row.get("is_subagent")) and isinstance(pa, str) and pa != row.get("agent_id"):
            cats.add("concurrent_streams")
        if kname == "k_L" and row.get("prev_kind") == "user":
            cats.add("user_input_binding")
        if np.isfinite(row.get("prev_ms", np.nan)) and row["first_ms"] - row["prev_ms"] > 600_000:
            cats.add("long_gap")
        if isinstance(row.get("request_id"), str) and re.match(r"^req_(?:vrtx|bdrk)_", row["request_id"]):
            cats.add("vertex_or_bedrock")
        ts0 = row.get("ts")
        if isinstance(ts0, str) and "." not in ts0:
            cats.add("whole_second")
        if np.isfinite(row.get("prev_seq", np.nan)):
            mid = s_ev[(s_ev.seq > row["prev_seq"]) & (s_ev.seq < row["seq"])]
            for kind, txt, ex in zip(mid.kind, mid.text.astype(object), mid.extra.astype(object)):
                x = pc.jl(ex) if isinstance(ex, str) else {}
                sub = x.get("subtype")
                t = txt if isinstance(txt, str) else ""
                if sub == "api_error" or "API Error" in t[:200]:
                    cats.add("api_retry")
                if sub in ("compact_boundary", "microcompact_boundary") or t.startswith("This session is being continued"):
                    cats.add("compaction")
    return sorted(cats)


# ============================================================================================================ F2 floor shift
def raw_cc_entries(session_id):
    """Raw swechat Claude Code transcript lines: [(timestamp, version, sessionId, cwd, gitBranch, permissionMode, type)].
    Read-only; swechat public data only (never cc_local text)."""
    p = SWE_TRANSCRIPTS / f"{session_id}.jsonl"
    out = []
    if not p.exists():
        return out
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                x = json.loads(line)
            except ValueError:
                continue
            if isinstance(x, dict):
                out.append((x.get("timestamp"), x.get("version"), x.get("sessionId"), x.get("cwd"), x.get("gitBranch"),
                            x.get("permissionMode"), x.get("type")))
    return out


def js_distance(a, b):
    """Jensen-Shannon distance (base 2) between two Counters."""
    keys = sorted(set(a) | set(b))
    if not keys:
        return 0.0
    p = np.array([a.get(k, 0) for k in keys], dtype=float)
    q = np.array([b.get(k, 0) for k in keys], dtype=float)
    if p.sum() == 0 or q.sum() == 0:
        return 1.0
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2

    def kl(x, y):
        nz = x > 0
        return float((x[nz] * np.log2(x[nz] / y[nz])).sum())
    return math.sqrt(max(0.0, (kl(p, m) + kl(q, m)) / 2))


def compromise_signature(latency, result_chars, k_star, G90, tokens_per_char=0.25):
    """F2 signature on one series (arrays in seq order). Returns dict with the two legs and `met`."""
    lat, ch = np.asarray(latency, dtype=float), np.asarray(result_chars, dtype=float)
    pre_rho = spearman(ch[:k_star], lat[:k_star]) if k_star >= 3 else None
    post_rho = spearman(ch[k_star:], lat[k_star:]) if len(lat) - k_star >= 3 else None
    tgen = ch[k_star:] * tokens_per_char / G90 if G90 else None
    post_r = float(np.median(lat[k_star:] / np.maximum(tgen, 1e-9))) if tgen is not None and len(tgen) else None
    leg1 = (post_rho is not None and post_rho >= 0.5 and len(lat) - k_star >= 20 and pre_rho is not None
            and pre_rho <= 0.2)
    leg2 = post_r is not None and post_r >= 0.1
    return {"pre_rho": pre_rho, "post_rho": post_rho, "post_median_r": post_r, "leg_rho": bool(leg1),
            "leg_r": bool(leg2), "met": bool(leg1 or leg2)}


# ============================================================================================================ F3 parameters
_LARGE_INT = re.compile(pc.RX["large_int"])
_EPOCH_S = re.compile(pc.RX["epoch_s"])
_EPOCH_MS = re.compile(pc.RX["epoch_ms"])


def int_occurrences(s):
    """[(value, start, end)] of pc large_int matches in s, epochs excluded (same as pc.large_ints, with spans)."""
    if not s:
        return []
    ep = {m.span() for m in _EPOCH_S.finditer(s)} | {m.span() for m in _EPOCH_MS.finditer(s)}
    return [(m.group(0), m.start(), m.end()) for m in _LARGE_INT.finditer(s) if m.span() not in ep]


def is_param_occurrence(s, start, end):
    """Which PARAM_CONTEXT pattern (name) the occurrence's preceding context matches, or None."""
    line_start = s.rfind("\n", 0, start) + 1
    ctx = s[max(line_start, start - 48):start]
    for name, rx in _PARAM.items():
        if rx.search(ctx):
            return name
    return None


def classify_args_ints(args_json):
    """[(value, origin, param_kind)] for every large integer of a call's args: origin 'json_number' (param_kind
    'json_number') or 'args_string' (param_kind = PARAM_CONTEXT name or None). Epochs excluded as in Probe 4."""
    strs, nums = pc.args_strings(args_json)
    out = []
    for t in strs:
        for v, a, b in int_occurrences(t):
            out.append((v, "args_string", is_param_occurrence(t, a, b)))
    for v0 in nums:
        for v in pc.large_ints(v0):
            out.append((v, "json_number", "json_number"))
    return out


# ============================================================================================================ pairs
def qualify_pairs(unit, u, P, classes=("shell", "auto_read")):
    """Phase B no-human-wait filter with rule 2 replaced by `classes`; adds key, cls, marker, qualified, background.
    P = pc.make_pairs(u[kind in (call, result)])."""
    P = P.copy()
    P["key"] = [pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    if unit == "cc_local":
        P["key"] = [pc.private_key(k) for k in P.key]
    P["cls"] = [("shell" if (k == "shell" or (k in pc.CODEX_SHELL_RAW and k != "write_stdin") or k.endswith("__bash"))
                 else pc.tool_class(k)) for k in P.key]
    txt = pc.sobj(P.text_r)
    P["marker"] = [error_marker(t) for t in txt]
    rx = [pc.jl(e) for e in P.extra_r.astype(object)]
    ok = np.isfinite(P.delta_s.to_numpy()) & (P.delta_s.to_numpy() > 0)
    cls_ok = P.cls.isin(list(classes)).to_numpy() & ~P.key.isin(["write_stdin"]).to_numpy()
    if unit in pc.CC_FORMAT_UNITS or unit == "swechat/gemini":
        calls = u[u.kind == "call"].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
        cm = [a if isinstance(a, str) else f"__solo__{c}" for a, c in zip(calls.api_msg_id.astype(object),
                                                                         calls.call_id.astype(str))]
        calls = calls.assign(_msg=cm)
        last = ~calls.duplicated(["session_id", "_msg"], keep="last")
        nin = calls.groupby(["session_id", "_msg"]).call_id.transform("size")
        lk = dict(zip(zip(calls.session_id, calls.call_id.astype(str)), last))
        nk = dict(zip(zip(calls.session_id, calls.call_id.astype(str)), nin))
        keys = list(zip(P.session_id, P.call_id.astype(str)))
        msg_ok = (np.array([nk.get(k, 1) == 1 for k in keys]) if unit == "swechat/gemini"
                  else np.array([bool(lk.get(k, True)) for k in keys]))
        P["last_in_msg"] = np.array([bool(lk.get(k, True)) for k in keys])
    else:
        msg_ok = np.ones(len(P), dtype=bool)
        P["last_in_msg"] = True
    mk_ok = ~P.marker.isin(["cc_permission_denied", "cc_interrupt_reject"]).to_numpy()
    if unit == "swechat/codex":
        mk_ok &= np.array([x.get("exec_status") != "declined" and not x.get("unified_exec_running") for x in rx])
    if unit == "swechat/gemini":
        mk_ok &= np.array([x.get("status") != "cancelled" for x in rx])
    hook_ok = np.ones(len(P), dtype=bool)
    if unit == "swechat/claude_code":
        m = u[(u.kind == "meta") & u.parent_call_id.notna()]
        hooked = {(s, str(p)) for s, p, e in zip(m.session_id, m.parent_call_id.astype(object), m.extra.astype(object))
                  if pc.jl(e).get("type") == "hook_progress"}
        hook_ok = np.array([k not in hooked for k in zip(P.session_id, P.call_id.astype(str))])
    elif unit == "cc_local":
        a = u[u.extra.notna() & u.kind.isin(["system", "meta", "user"])]
        hooked = set()
        for s, e in zip(a.session_id, a.extra.astype(object)):
            x = pc.jl(e)
            at = x.get("attachment_type")
            if at and str(at).startswith("hook") and x.get("toolUseID"):
                hooked.add((s, str(x["toolUseID"])))
        hook_ok = np.array([k not in hooked for k in zip(P.session_id, P.call_id.astype(str))])
    pol_ok = np.ones(len(P), dtype=bool)
    if unit == "swechat/codex":
        m = u[(u.kind == "meta") & u.extra.notna()]
        pol = defaultdict(list)
        for s, q, e in zip(m.session_id, m.seq, m.extra.astype(object)):
            x = pc.jl(e)
            if "approval_policy" in x:
                pol[s].append((int(q), x.get("approval_policy")))
        for s in pol:
            pol[s].sort()
        res = []
        for s, q in zip(P.session_id, P.seq):
            lst = pol.get(s, [])
            i = bisect_left([a for a, _ in lst], int(q)) - 1
            res.append(i >= 0 and lst[i][1] == "never")
        pol_ok = np.array(res)
    bg = []
    for a, t, x in zip(P.args.astype(object), txt, rx):
        o = pc.jl(a) if isinstance(a, str) else {}
        bg.append(bool(o.get("run_in_background")) or "backgroundTaskId" in x
                  or bool(t and _R["background_result"].search(t)))
    P["background"] = np.array(bg, dtype=bool)
    P["qualified"] = ok & cls_ok & msg_ok & mk_ok & hook_ok & pol_ok & ~P.background.to_numpy()
    P["result_bytes"] = [len(t.encode("utf-8")) if t else 0 for t in txt]
    P["result_chars"] = [len(t) if t else 0 for t in txt]
    return P


# ============================================================================================================ N1
def normalize_command(cmd):
    if not isinstance(cmd, str):
        return None
    c = cmd.strip()
    prev = None
    while prev != c:
        prev = c
        c = _CD_PREFIX.sub("", c)
    c = _TRAIL_REDIR.sub("", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c or None


def n1_key(unit, key, args_json, command):
    o = pc.jl(args_json) if isinstance(args_json, str) else {}
    shellish = key == "shell" or key in pc.CODEX_SHELL_RAW or str(key).endswith("__bash")
    if shellish:
        c = normalize_command(pc.shell_command(unit, key, o, command))
        if c is None:
            return None
        wd = o.get("workdir")
        return f"{key}|{c}|{wd}" if isinstance(wd, str) else f"{key}|{c}"
    if key == "read":
        p = None
        for k in pc.PATH_KEYS:
            if isinstance(o.get(k), str):
                p = pc.normalize_path(o[k])
                break
        return f"read|{p}|{o.get('offset')}|{o.get('limit')}" if p else None
    oo = {k: v for k, v in o.items() if k not in N1_VOLATILE_ARG_KEYS}
    return f"{key}|" + json.dumps(oo, sort_keys=True, ensure_ascii=False)


def n1_residuals(Q, unit, err_col="err"):
    """Q: qualified pairs with columns session_id, seq, key, delta_s, result_bytes, n1 (n1_key), err (bool).
    Returns a frame of residuals (one row per instance with >= 1 same-status reference)."""
    rows = []
    for (s, k, nk), g in Q[Q.n1.notna()].groupby(["session_id", "key", "n1"], sort=False):
        if len(g) < 2:
            continue
        lg = np.log10(g.delta_s.to_numpy())
        er = g[err_col].to_numpy() if err_col in g else np.zeros(len(g), dtype=bool)
        by = g.result_bytes.to_numpy()
        for i in range(len(g)):
            ref = [lg[j] for j in range(len(g)) if j != i and er[j] == er[i]]
            if not ref:
                continue
            rows.append({"session_id": s, "key": k, "n1": nk, "seq": int(g.seq.iloc[i]), "residual": lg[i] - np.median(ref),
                         "log_bytes": math.log10(by[i] + 1), "d_log_bytes": math.log10(by[i] + 1)
                         - np.median([math.log10(by[j] + 1) for j in range(len(g)) if j != i and er[j] == er[i]]),
                         "n_ref": len(ref), "err": bool(er[i])})
    return pd.DataFrame(rows)


# ============================================================================================================ N2
def response_table(unit, u):
    """One row per API response (CC formats, opencode, gemini, aiv_cu: api_msg_id; codex: token_count close).
    Columns: session_id, resp, usage_in, usage_out, chars_out (text + args + thinking), last_call_id, n_calls."""
    rows = []
    if unit == "swechat/codex":
        for sid, g in u.sort_values(["session_id", "seq"]).groupby("session_id", sort=False):
            pend, chars, last = 0, 0, None
            for kind, txt, a, uo, ui, cid, ex in zip(g.kind, g.text.astype(object), g.args.astype(object), g.usage_out,
                                                    g.usage_in, g.call_id.astype(object), g.extra.astype(object)):
                if kind == "call":
                    pend += 1
                    chars += len(a) if isinstance(a, str) else 0
                    last = cid
                elif kind == "assistant" and isinstance(txt, str):
                    chars += len(txt)
                elif kind == "meta" and not pd.isna(uo):
                    if pend:
                        rows.append({"session_id": sid, "resp": f"tc{len(rows)}", "usage_in": ui, "usage_out": uo,
                                     "chars_out": chars, "last_call_id": last, "n_calls": pend})
                    pend, chars, last = 0, 0, None
        return pd.DataFrame(rows)
    r = u[u.api_msg_id.notna()]
    for (sid, a), g in r.groupby(["session_id", "api_msg_id"], sort=False):
        calls = g[g.kind == "call"]
        if not len(calls):
            continue
        uo = g.usage_out.dropna()
        ui = g.usage_in.dropna()
        ch = sum(len(t) for t in g[g.kind == "assistant"].text.astype(object) if isinstance(t, str))
        ch += sum(len(t) for t in calls.args.astype(object) if isinstance(t, str))
        for e in g.extra.astype(object):
            if isinstance(e, str) and "thinking_chars" in e:
                v = pc.jl(e).get("thinking_chars")
                if isinstance(v, (int, float)):
                    ch += int(v)
        rows.append({"session_id": sid, "resp": str(a), "usage_in": float(ui.max()) if len(ui) else np.nan,
                     "usage_out": float(uo.max()) if len(uo) else np.nan, "chars_out": ch,
                     "last_call_id": calls.sort_values("seq").call_id.iloc[-1], "n_calls": int(len(calls))})
    return pd.DataFrame(rows)


def granularity(resp):
    if not len(resp):
        return {"responses": 0, "GRANULAR": False}
    both = (resp.usage_in.notna() & resp.usage_out.notna())
    g1 = float(both.mean())
    med = float(resp.usage_out.dropna().median()) if resp.usage_out.notna().any() else None
    return {"responses": int(len(resp)), "G1_share_both": g1, "G2_median_usage_out": med,
            "G2_not_partial": bool(med is not None and med >= 20), "G3_identifiable": True,
            "GRANULAR": bool(g1 >= 0.9 and med is not None and med >= 20)}


def n2_flags(resp, result_chars_by_call, tau, extra_out=None):
    """Flag per eligible response (last call's result >= 800 chars). extra_out: {resp: added output tokens} (attack)."""
    out = []
    for s, r, uo, ch, cid in zip(resp.session_id, resp.resp, resp.usage_out, resp.chars_out, resp.last_call_id):
        rc = result_chars_by_call.get((s, cid))
        if rc is None or rc < 800 or pd.isna(uo):
            continue
        add = (extra_out or {}).get((s, r), 0.0)
        U = uo + add - tau * ch
        out.append((s, r, bool(U >= 0.5 * tau * rc)))
    return out


# ============================================================================================================ N3 / N4
def n3_gaps(u):
    """[(session_id, gap_s, batch_bytes)] per SPEC_E n3_reaction_time.gap (main and subagent threads separately)."""
    out = []
    u = u.sort_values(["session_id", "seq"])
    thr = list(zip(u.session_id, u.is_subagent.astype("boolean").fillna(False), u.agent_id.astype(object).fillna("")))
    u = u.assign(_thr=thr)
    for _, g in u.groupby("_thr", sort=False):
        last_t, nbytes, blocked = None, 0, False
        for kind, ts, txt in zip(g.kind, g.ts.astype(object), g.text.astype(object)):
            if kind == "result":
                t = parse_ts(ts) if isinstance(ts, str) else None
                if t is not None:
                    last_t = t
                nbytes += len(txt.encode("utf-8")) if isinstance(txt, str) else 0
            elif kind in ("user", "system"):
                blocked = True
            elif kind in ("assistant", "call"):
                if last_t is not None and not blocked and isinstance(ts, str):
                    t = parse_ts(ts)
                    if t is not None:
                        gap = (t - last_t).total_seconds()
                        if 0 < gap <= 600:
                            out.append((g.session_id.iloc[0], gap, nbytes))
                last_t, nbytes, blocked = None, 0, False
    return out


def inflight_counts(P):
    """k_i per pair of P (pc.make_pairs output with delta_s): 1 + other pairs of the session in flight at the midpoint."""
    call_ms = _ms(P.ts)
    res_ms = _ms(P.ts_r)
    P = P.assign(_c=call_ms, _r=res_ms)
    k = np.ones(len(P), dtype=int)
    pos = {ix: i for i, ix in enumerate(P.index)}
    for _, g in P.groupby("session_id", sort=False):
        c, r = g._c.to_numpy(), g._r.to_numpy()
        mid = (c + r) / 2
        for j, ix in enumerate(g.index):
            if not (np.isfinite(c[j]) and np.isfinite(r[j])):
                continue
            inf = (c <= mid[j]) & (mid[j] <= r)
            k[pos[ix]] = 1 + int(inf.sum()) - int(inf[j])
    return k


# ============================================================================================================ N5
def command_programs(cmd):
    """[(program, segment)] for each pipeline/list segment of a shell command (best-effort split on | ; && ||)."""
    if not isinstance(cmd, str):
        return []
    segs = re.split(r"\|\||&&|\||;|\n", cmd)
    out = []
    for s in segs:
        toks = s.strip().split()
        while toks and (re.match(r"^\w+=\S*$", toks[0]) or toks[0] in ("sudo", "command", "env", "time", "nohup")):
            toks = toks[1:]
        if toks:
            out.append((os_basename(toks[0]), s.strip()))
    return out


def os_basename(p):
    return p.rsplit("/", 1)[-1]


def readonly_command(cmd):
    if not isinstance(cmd, str) or TIME_DEPENDENT_RX.search(cmd) or re.search(r"(?<![<>&0-9])>(?!&)|>>", cmd):
        return False
    progs = command_programs(cmd)
    if not progs:
        return False
    for p, seg in progs:
        if p not in READONLY_PROGRAMS:
            return False
        if p == "sed" and re.search(r"\s-i\b|--in-place", seg):
            return False
        if p == "find" and re.search(r"\s-(?:delete|exec|execdir|ok|okdir|fprint0?|fprintf|fls)\b", seg):
            return False
        if p == "sort" and re.search(r"\s(?:-o\s*\S|--output\b)", seg):
            return False
        if p == "git":
            m = re.search(r"\bgit\s+(?:-C\s+\S+\s+|-c\s+\S+\s+|--no-pager\s+)*([a-z\-]+)", seg)
            if not m or m.group(1) not in GIT_READONLY_SUB:
                return False
            if m.group(1) in ("branch", "tag", "config", "remote") and re.search(
                    r"\b(?:-d|-D|-m|-M|--delete|--set|add|remove|rm|rename|set-url)\b", seg):
                return False
    return True


_VOL = [_R[k] for k in ("vol_iso", "vol_uuid", "vol_tmp", "vol_hexaddr", "vol_pid", "vol_ago", "vol_clock",
                        "vol_duration")]


def mask_volatile(text):
    t = text if isinstance(text, str) else ""
    for rx in _VOL:
        t = rx.sub("<V>", t)
    return t


def determinism_pairs(unit, u, P):
    """[(session_id, seq_i, seq_j, n1key, text_i, text_j)] per SPEC_E n5_battery.a_determinism.pairs.
    P: pairs with key and n1 columns (qualify_pairs + n1)."""
    out = []
    u = u.sort_values(["session_id", "seq"])
    Pn = P[P.n1.notna()]
    rep = Pn.groupby(["session_id", "n1"]).seq.transform("size") >= 2   # only keys seen twice can form a pair
    Pn = Pn[rep.to_numpy()]
    want = set(Pn.session_id.unique())
    ev_by = {sid: g for sid, g in u[u.session_id.isin(want)].groupby("session_id", sort=False)}
    for sid, g in Pn.sort_values(["session_id", "seq"]).groupby("session_id", sort=False):
        ev = ev_by[sid]
        cand = []
        for _, r in g.iterrows():
            cmd = pc.shell_command(unit, r.key, pc.jl(r.args) if isinstance(r.args, str) else {}, r.command)
            ro = (r.key == "read") or (cmd is not None and readonly_command(cmd))
            if not ro or truncated_result(r.text_r, r.extra_r) or not isinstance(r.text_r, str):
                continue
            if r.key == "read" and re.search(_R["dual_identical_ref"].pattern, r.text_r[:300]):
                continue
            cand.append(r)
        byk = defaultdict(list)
        for r in cand:
            byk[r.n1].append(r)
        for nk, lst in byk.items():
            for a, b in zip(lst, lst[1:]):
                mid = ev[(ev.seq > a.seq_r) & (ev.seq < b.seq)]
                bad = False
                for kind, tl, tr, cmd, args in zip(mid.kind, mid.tool.astype(object), mid.tool_raw.astype(object),
                                                   mid.command.astype(object), mid.args.astype(object)):
                    if kind == "user":
                        bad = True
                        break
                    if kind != "call":
                        continue
                    k2 = pc.tool_key(unit, tl, tr)
                    c2 = pc.tool_class(k2)
                    if c2 in ("file_write", "subagent"):
                        bad = True
                        break
                    if k2 == "shell" or k2 in pc.CODEX_SHELL_RAW or str(k2).endswith("__bash"):
                        sc = pc.shell_command(unit, k2, pc.jl(args) if isinstance(args, str) else {}, cmd)
                        if not readonly_command(sc):
                            bad = True
                            break
                if not bad:
                    out.append((sid, int(a.seq), int(b.seq), nk, a.text_r, b.text_r))
    return out


_LS_BAD_FLAGS = set("tSrUfcuvXR")


def _ls_names(cmd, text):
    m = re.search(r"(?:^|[|;&]\s*)ls((?:\s+-[A-Za-z0-9]+)*)(\s+[^|;&]*)?$", cmd.strip().split("|")[0].strip()) \
        if isinstance(cmd, str) else None
    if not m:
        return None
    flags = set("".join(f.strip().lstrip("-") for f in (m.group(1) or "").split()))
    if flags & _LS_BAD_FLAGS:
        return None
    if not ({"1", "l"} & flags) and "|" not in cmd:
        return None
    names = []
    for line in _s(text).splitlines():
        if not line.strip() or line.startswith("total ") or line.endswith(":"):
            continue
        if "l" in flags:
            if not re.match(r"^[-dlcbpsD][rwxsStT\-]{9}", line):
                continue
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            nm = parts[8].split(" -> ")[0]
        else:
            nm = line.strip()
        names.append(nm)
    return names if len(names) >= 3 else None


def _natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s.casefold())]


def ls_order_violation(cmd, text):
    """None if not an eligible ls output, else True/False (violation)."""
    names = _ls_names(cmd, text)
    if names is None:
        return None
    keys = [lambda s: s, lambda s: s.casefold(), lambda s: re.sub(r"[^0-9a-z]", "", s.casefold()), _natkey]
    return not any(all(f(a) <= f(b) for a, b in zip(names, names[1:])) for f in keys)


def _parse_git_date(s):
    for fmt in ("%a %b %d %H:%M:%S %Y %z", "%Y-%m-%d %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return pd.Timestamp(pd.to_datetime(s.strip(), format=fmt, utc=True))
        except (ValueError, TypeError):
            continue
    return None


def gitlog_order_violation(cmd, text):
    if not isinstance(cmd, str) or not re.search(r"\bgit\s+(?:-C\s+\S+\s+|--no-pager\s+)*log\b", cmd):
        return None
    if re.search(r"--reverse|--topo-order|--graph", cmd):
        return None
    ds = [_parse_git_date(m.group(1)) for m in _R["gitlog_date"].finditer(_s(text))]
    ds = [d for d in ds if d is not None]
    if len(ds) < 3:
        return None
    return any(b > a for a, b in zip(ds, ds[1:]))


def grepn_order_violation(cmd_or_args, text, is_grep_tool=False):
    if is_grep_tool:
        o = pc.jl(cmd_or_args) if isinstance(cmd_or_args, str) else {}
        if not (o.get("-n") is True and o.get("output_mode") == "content"):
            return None
    else:
        if not isinstance(cmd_or_args, str) or not re.search(r"(?:^|[|;&]\s*)(?:grep|egrep|rg)\b[^|;&]*\s-[A-Za-z]*n",
                                                            cmd_or_args):
            return None
    prev_path, prev_line, n = None, None, 0
    for line in _s(text).splitlines():
        if line == "--":
            continue
        m = _R["grep_n_line"].match(line)
        if not m:
            continue
        n += 1
        p, ln = m.group("path"), int(m.group("line"))
        if p == prev_path and prev_line is not None and ln <= prev_line:
            return True
        prev_path, prev_line = p, ln
    return False if n >= 3 else None


def ws_violations(cmd, text):
    """{check: True/False} for the checks that apply to this output (absent key = not eligible)."""
    out = {}
    lines = _s(text).splitlines()
    if isinstance(cmd, str) and re.search(r"(?:^|[|;&]\s*)ls\s+-[A-Za-z]*l", cmd):
        ends = []
        for ln in lines:
            m = _R["ls_long_line"].match(ln)
            if m:
                ends.append(m.end(1))
        if len(ends) >= 3:
            out["ls_long_alignment"] = len(set(ends)) > 1
    if isinstance(cmd, str) and re.search(r"\bgit\s+status\b", cmd) and not re.search(r"--short|-s\b|--porcelain", cmd):
        ent = [ln for ln in lines if _R["git_status_entry"].match(ln)]
        if ent:
            out["git_status_tab"] = any(not ln.startswith("\t") for ln in ent)
    if isinstance(cmd, str) and re.search(r"(?:^|[|;&]\s*)wc\b", cmd):
        ends = []
        for ln in lines:
            m = _R["wc_line"].match(ln)
            if m:
                ends.append(m.end(2))
        if len(ends) >= 3:
            out["wc_alignment"] = len(set(ends)) > 1
    ban = [ln for ln in lines if _R["pytest_banner"].match(ln)]
    if len(ban) >= 2:
        out["pytest_banner"] = len(set(len(b) for b in ban)) > 1
    return out


def normalize_ws(text):
    return re.sub(r" {2,}", " ", _s(text).replace("\t", "    "))


def utf16_len(s):
    return len(s.encode("utf-16-le")) // 2


def truncation_info(text):
    """{item, ...} for a result carrying a Claude Code truncation marker, else None."""
    t = text if isinstance(text, str) else ""
    m = _R["trunc_chars_mid"].search(t)
    if m:
        # Raw lengths: everything before / after the marker, separators included. Stripping newlines (the pre-audit
        # definition, kept below as a diagnostic) also removed newlines that belong to the cut text itself.
        pre, post = t[:m.start()], t[m.end():]
        return {"item": "cc_chars_mid", "prefix_u16": utf16_len(pre), "suffix_u16": utf16_len(post),
                "prefix_u16_stripped": utf16_len(pre.rstrip("\n")), "suffix_u16_stripped": utf16_len(post.lstrip("\n")),
                "stated": int(m.group(1))}
    m = _R["trunc_lines_tail"].search(t)
    if m:
        return {"item": "cc_lines_tail", "prefix_chars": len(t[:m.start()].rstrip("\n").rstrip(".").rstrip()),
                "prefix_raw": m.start(), "stated": int(m.group(1))}
    if _R["trunc_glob"].search(t):
        n = sum(1 for ln in t.splitlines() if ln.strip() and not _R["trunc_glob"].search(ln))
        return {"item": "cc_glob_cap", "lines": n}
    return None


def error_fidelity_checks(unit, u, P):
    """[(session_id, seq, path_key, line, faithful)] per SPEC_E n5_battery.f_error_fidelity. P has key, err columns."""
    out = []
    u = u.sort_values(["session_id", "seq"])
    for sid, g in P.sort_values(["session_id", "seq"]).groupby("session_id", sort=False):
        shown = {}       # path_key -> {line: text}
        for _, r in g.iterrows():
            o = pc.jl(r.args) if isinstance(r.args, str) else {}
            tgt = None
            for k in pc.PATH_KEYS:
                if isinstance(o.get(k), str):
                    tgt = pc.path_key(pc.normalize_path(o[k]) or "")
                    break
            if pc.tool_class(r.key) == "file_write" and tgt:
                shown.pop(tgt, None)
            if r.key == "read" and tgt and isinstance(r.text_r, str):
                d = shown.setdefault(tgt, {})
                for m in _R["read_numbered_line"].finditer(r.text_r):
                    d[int(m.group(1))] = m.group(2)
            if bool(r.get("err")) and isinstance(r.text_r, str):
                for name in ("py_frame", "rust_frame"):
                    for m in _R[name].finditer(r.text_r):
                        pk = pc.path_key(pc.normalize_path(m.group("path")) or "")
                        ln = int(m.group("line"))
                        if pk in shown and ln in shown[pk]:
                            out.append((sid, int(r.seq), pk, ln, shown[pk][ln].strip() == m.group("src").strip()))
    return out


def cold_start_values(Q):
    """[(session_id, tool_key, c_s)] per SPEC_E n5_battery.g_cold_start. Q: qualified pairs (delta_s > 0)."""
    out = []
    for sid, g in Q.sort_values(["session_id", "seq"]).groupby("session_id", sort=False):
        if not len(g):
            continue
        t = g.key.value_counts().index[0]
        h = g[g.key == t]
        if len(h) < 6:
            continue
        lg = np.log10(h.delta_s.to_numpy())
        out.append((sid, t, float(lg[0] - np.median(lg[1:]))))
    return out


# ============================================================================================================ R2 / R3 / R4
def image_windows(u):
    """aiv_cu Gemini: one row per consecutive pair of usage-bearing calls of a session: d_image, n_gui, model."""
    rows = []
    c = u[(u.kind == "call")].sort_values(["session_id", "seq"])
    for sid, g in c.groupby("session_id", sort=False):
        prev = None
        n_gui = 0
        for tl, ex, model, seq in zip(g.tool.astype(object), g.extra.astype(object), g.model.astype(object), g.seq):
            img = None
            if isinstance(ex, str) and "promptTokensDetails" in ex:
                det = (pc.jl(ex).get("usage_detail") or {}).get("promptTokensDetails") or {}
                if isinstance(det, dict):
                    img = det.get("IMAGE", 0)
            if img is not None and prev is not None:
                rows.append({"session_id": sid, "seq": int(seq), "d_image": float(img - prev[0]), "n_gui": n_gui,
                             "model": model if isinstance(model, str) else None})
            if img is not None:
                prev = (img, seq)
                n_gui = 0
            n_gui += int(tl == "gui")
    return pd.DataFrame(rows)


def image_window_violation(d_image, n_gui, unit_tokens):
    """True if the window breaks the rule: positive iff a GUI result is in the window, and on the unit lattice."""
    if n_gui >= 1 and d_image <= 0:
        return True
    if n_gui == 0 and d_image != 0:
        return True
    if unit_tokens and d_image > 0 and abs(d_image / unit_tokens - round(d_image / unit_tokens)) > 1e-9:
        return True
    return False


_GEN = re.compile(RX_E["git_generator_cmd"])


def git_cmd_class(cmd):
    """'generator' | 'rereader' | 'other' for a shell command printing a commit line."""
    if not isinstance(cmd, str):
        return "other"
    if _GEN.search(cmd):
        return "generator_explicit_date" if _R["git_explicit_date"].search(cmd) else "generator"
    progs = command_programs(cmd)
    if progs and _R["reread_program"].match(progs[0][0]):
        return "rereader"
    return "other"


def commit_claims(text):
    return [(m.group("sha"), m.group("branch")) for m in _R["commit_claim"].finditer(_s(text))]


def git_window_ok(call_ts, result_ts, commit_date, tol_s=2.0):
    c, r, d = parse_ts(call_ts), parse_ts(result_ts), (pd.Timestamp(commit_date) if commit_date is not None else None)
    if c is None or r is None or d is None:
        return None
    d = d.tz_convert("UTC") if d.tzinfo else d.tz_localize("UTC")
    return bool((c - pd.Timedelta(seconds=tol_s)) <= d <= (r + pd.Timedelta(seconds=tol_s)))


def dual_whitelisted(text, corpus="swechat"):
    t = text if isinstance(text, str) else ""
    names = ["dual_persisted", "dual_shorter_than_offset", "dual_identical_ref", "dual_redaction", "dual_negative_line"]
    if corpus == "cc_local":
        names.append("dual_empty_file")
    for n in names:
        if _R[n].search(t):
            return n
    return None


# ============================================================================================================ N7
def applicable(attack, detector):
    return bool(ATTACK_FIELDS.get(attack, set()) & DETECTOR_FIELDS.get(detector, set()))


def n7_cell_label(n_tampered, k_tampered, n_honest, k_honest):
    if n_tampered < N7_MIN_SESSIONS:
        return "INSUFFICIENT_N", None
    rec = stats.wilson(k_tampered, n_tampered)
    fpr = stats.wilson(k_honest, n_honest)
    if rec[1] > fpr[2]:
        return ("DETECTS" if rec[0] >= 0.5 else "PARTIAL"), {"recall": rec, "fpr": fpr}
    return "BLIND", {"recall": rec, "fpr": fpr}


def pick_donor(pool, target_bytes, rng, exclude_session=None, tol=MATCHED_BYTES_TOL):
    """pool: DataFrame with session_id, text, bytes (same unit, split and tool_key). Nearest byte length from another
    session, ties broken by rng. Returns (row index, relative byte difference) or (None, None)."""
    cand = pool[pool.session_id != exclude_session]
    if not len(cand) or target_bytes <= 0:
        return None, None
    diff = (cand.bytes - target_bytes).abs()
    best = diff.min()
    idx = cand.index[diff == best].to_numpy()
    i = idx[int(rng.integers(0, len(idx)))]
    rel = float(best / target_bytes)
    return (i, rel) if rel <= tol else (None, rel)


def _shift_ts(ts, seconds):
    t = parse_ts(ts) if isinstance(ts, str) else None
    if t is None:
        return ts
    t2 = t + pd.Timedelta(seconds=seconds).to_pytimedelta()
    return t2.astimezone(t.tzinfo).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def atk_time(s, target_idx, D, mode):
    """s: one session's IR rows (copy is returned). target_idx: index label of the target event (a result, or a
    response's first event). mode in result_early|result_late|tail_late|tail_early|response_early|response_late."""
    s = s.copy()
    sign = -1 if mode.endswith("early") else 1
    if mode.startswith("tail"):
        q = s.at[target_idx, "seq"]
        idx = s.index[s.seq >= q]
        s.loc[idx, "ts"] = [_shift_ts(t, sign * D) for t in s.loc[idx, "ts"]]
        return s, {"clamped": False}
    clamped = False
    new = _shift_ts(s.at[target_idx, "ts"], sign * D)
    if mode == "result_early":
        cid = s.at[target_idx, "call_id"]
        c = s[(s.kind == "call") & (s.call_id == cid)]
        if len(c):
            ct = parse_ts(c.ts.iloc[0])
            nt = parse_ts(new)
            if ct is not None and nt is not None and nt <= ct:
                new = _shift_ts(c.ts.iloc[0], 0.001)
                clamped = True
    s.at[target_idx, "ts"] = new
    return s, {"clamped": clamped}


def atk_id_swap(s, idx_a, idx_b):
    """Swap the request ids of two responses (all events carrying each id)."""
    s = s.copy()
    a, b = s.at[idx_a, "request_id"], s.at[idx_b, "request_id"]
    ma, mb = s.request_id == a, s.request_id == b
    s.loc[ma, "request_id"] = b
    s.loc[mb, "request_id"] = a
    return s


def atk_id_splice(s, idx, donor_id):
    s = s.copy()
    a = s.at[idx, "request_id"]
    s.loc[s.request_id == a, "request_id"] = donor_id
    return s


def atk_substitute(s, result_idx, donor_text, donor_error=None):
    s = s.copy()
    s.at[result_idx, "text"] = donor_text
    if donor_error is not None:
        s.at[result_idx, "native_error"] = donor_error
    if "stderr" in s.columns:
        s.at[result_idx, "stderr"] = None
    return s


def atk_digit(s, result_idx):
    s = s.copy()
    t = s.at[result_idx, "text"]
    if not isinstance(t, str):
        return s, False
    ms = list(re.finditer(r"\d+", t))
    if not ms:
        return s, False
    m = ms[-1]
    d = int(t[m.end() - 1])
    s.at[result_idx, "text"] = t[:m.end() - 1] + str((d + 1) % 10) + t[m.end():]
    return s, True


def atk_rewrite_consistent(s, result_idxs, donor_texts, donor_latencies):
    """Replace k results; set each pair's latency to its donor latency; shift later events to keep order."""
    s = s.copy()
    for ri, txt, lat in zip(result_idxs, donor_texts, donor_latencies):
        cid = s.at[ri, "call_id"]
        c = s[(s.kind == "call") & (s.call_id == cid)]
        if not len(c):
            continue
        ct, rt = parse_ts(c.ts.iloc[0]), parse_ts(s.at[ri, "ts"])
        if ct is None or rt is None:
            continue
        shift = (ct + pd.Timedelta(seconds=lat).to_pytimedelta() - rt).total_seconds()
        q = s.at[ri, "seq"]
        idx = s.index[s.seq >= q]
        s.loc[idx, "ts"] = [_shift_ts(t, shift) for t in s.loc[idx, "ts"]]
        s.at[ri, "text"] = txt
    return s


def atk_reorder_pairs(s, call_a, call_b):
    """Exchange contents of two call/result pairs (by call index labels); stamps, ids, seq stay."""
    s = s.copy()
    cols_c = [c for c in ("tool", "tool_raw", "args", "command") if c in s.columns]
    cols_r = [c for c in ("text", "stderr", "native_error", "exit_code", "extra") if c in s.columns]
    ra = s.index[(s.kind == "result") & (s.call_id == s.at[call_a, "call_id"])]
    rb = s.index[(s.kind == "result") & (s.call_id == s.at[call_b, "call_id"])]
    va, vb = s.loc[call_a, cols_c].copy(), s.loc[call_b, cols_c].copy()
    s.loc[call_a, cols_c], s.loc[call_b, cols_c] = vb.values, va.values
    if len(ra) and len(rb):
        xa, xb = s.loc[ra[0], cols_r].copy(), s.loc[rb[0], cols_r].copy()
        s.loc[ra[0], cols_r], s.loc[rb[0], cols_r] = xb.values, xa.values
    return s


def atk_reorder_lines(s, result_idx, rng):
    s = s.copy()
    t = s.at[result_idx, "text"]
    lines = t.split("\n") if isinstance(t, str) else []
    cand = [i for i in range(len(lines) - 1) if lines[i] != lines[i + 1]]
    if len(lines) < 3 or not cand:
        return s, False
    i = cand[int(rng.integers(0, len(cand)))]
    lines[i], lines[i + 1] = lines[i + 1], lines[i]
    s.at[result_idx, "text"] = "\n".join(lines)
    return s, True


def atk_delete_pair(s, call_idx):
    cid = s.at[call_idx, "call_id"]
    drop = (s.call_id == cid) | (s.parent_call_id == cid)
    s = s[~drop.fillna(False).to_numpy()].copy()
    return s


def atk_delete_response(s, any_idx):
    rid = s.at[any_idx, "request_id"]
    s = s[~(s.request_id == rid).fillna(False).to_numpy()].copy()
    return s


def atk_insert_pair(s, after_idx, donor_call, donor_result, mode="consistent", donor_gap_s=None, donor_lat_s=None):
    """Insert donor call/result rows (pd.Series, from another session) after event after_idx. Seq is renumbered by
    +0.25/+0.5 then re-ranked. mode consistent: later events shifted by gap + latency; squeezed: placed inside the gap."""
    s = s.copy()
    q = s.at[after_idx, "seq"]
    t0 = parse_ts(s.at[after_idx, "ts"])
    nxt = s[s.seq > q].sort_values("seq")
    c, r = donor_call.copy(), donor_result.copy()
    new_cid = f"inserted:{c.get('call_id')}"
    c["call_id"], r["call_id"] = new_cid, new_cid
    c["session_id"] = r["session_id"] = s.session_id.iloc[0]
    if mode == "consistent":
        gap = donor_gap_s if donor_gap_s is not None else 1.0
        lat = donor_lat_s if donor_lat_s is not None else 0.1
        c["ts"] = _shift_ts(s.at[after_idx, "ts"], gap)
        r["ts"] = _shift_ts(s.at[after_idx, "ts"], gap + lat)
        idx = s.index[s.seq > q]
        s.loc[idx, "ts"] = [_shift_ts(t, gap + lat) for t in s.loc[idx, "ts"]]
    else:
        if not len(nxt) or t0 is None:
            return None
        t1 = parse_ts(nxt.ts.iloc[0])
        if t1 is None or (t1 - t0).total_seconds() < 0.002:
            return None
        g = (t1 - t0).total_seconds()
        c["ts"] = _shift_ts(s.at[after_idx, "ts"], 0.25 * g)
        r["ts"] = _shift_ts(s.at[after_idx, "ts"], 0.75 * g)
    c["seq"], r["seq"] = q + 0.25, q + 0.5
    for x in (c, r):
        for col in ("request_id", "api_msg_id", "uuid", "parent_uuid", "usage_in", "usage_out"):
            if col in x.index:
                x[col] = None
    s = pd.concat([s, pd.DataFrame([c, r])], ignore_index=False)
    s = s.sort_values("seq")
    s["seq"] = np.arange(len(s))
    return s.reset_index(drop=True)


def atk_inline_fabrication(resp_row, result_chars, tau):
    """Return the output-token addition for one response (N2 attack footprint)."""
    return float(tau * result_chars)


def atk_image_relabel(s, call_idx):
    s = s.copy()
    s.at[call_idx, "tool"] = "shell"
    s.at[call_idx, "tool_raw"] = "bash"
    return s
