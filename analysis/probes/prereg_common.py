"""Phase B pre-registration: the frozen definitions (SPEC) and the helper code that implements them.

analysis/prereg.json is generated from SPEC by analysis/probes/prereg_calibration.py, which also adds the thresholds it
derives from the Phase A split (section `resolved`). Phase B probe scripts import this module so that extraction,
normalisation, error classes and test statistics are the same code that was pre-registered; prereg.json records this
file's sha256. Any change after the orchestrator commits it goes into prereg.json `change_log` (before/after/reason).

Split rule: every loader here takes split 'A' or 'B'. The calibration script asserts 'A'. Nothing here reads Phase C
outputs.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import error_marker, normalize_tool, parse_ts

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "analysis" / "cache"

# ======================================================================================================== regexes
# Every regex the probes use is written here once, as a raw string, and copied verbatim into prereg.json.
RX = {
    # ---- redaction (SWE-chat release markers; applied to every corpus, harmless where absent)
    "redaction_typed": r"\[REDACTED:[A-Za-z0-9_]+\]|\[REDACTED_[A-Za-z0-9_]+\]|\[REDACTED\]|<REDACTED>|<TRUFFLEHOG_REDACTED_[A-Za-z0-9_]*>",
    "redaction_any": r"REDACTED",
    "redaction_run": r"\S*REDACTED\S*",
    # ---- URLs are masked before free-text path extraction
    "url": r"\b[A-Za-z][A-Za-z0-9+.\-]*://\S+",
    # ---- paths in free text (shell commands, code, instructions)
    "path_abs_posix": r"(?<![\w.~$@%+:/\\-])(?:~|\.{1,2})?(?:/[\w.@%+~\-]+)+",
    "path_windows": r"(?<![\w])[A-Za-z]:[\\/]+(?:[\w.@%+~\-]+[\\/]+)*[\w.@%+~\-]+",
    "path_relative": r"(?<![\w.~$@%+:/\\-])(?:[\w@%+~\-][\w.@%+~\-]*/)+[\w.@%+~\-]+",
    "path_ext": r"\.[A-Za-z0-9]{1,8}$",
    "path_line_suffix": r"(?::\d+(?::\d+)?|#L\d+(?:-L?\d+)?)$",
    # ---- apply_patch file headers (Codex, OpenCode)
    "patch_file": r"(?m)^\*\*\* (Update|Add|Delete) File: (.+?)\s*$",
    "patch_move": r"(?m)^\*\*\* Move to: (.+?)\s*$",
    # ---- symbols (code-shaped identifiers)
    "sym_snake": r"(?<![\w])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w])",
    "sym_camel": r"(?<![\w])[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*(?![\w])",
    "sym_pascal": r"(?<![\w])[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+(?![\w])",
    # ---- config keys
    "env_var": r"(?<![\w])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![\w])",
    "cfg_key_line": r"(?m)^\s*[\"']?([A-Za-z_][\w.\-]*)[\"']?\s*[:=]",
    "git_config_key": r"\bgit\s+config\s+(?:--(?:global|local|system|worktree)\s+)?(?:--get(?:-all)?\s+)?([a-z][\w\-]*(?:\.[\w\-]+)+)",
    # ---- enumeration commands (first program word of a shell command segment)
    "enum_shell": r"(?:^|[;&|]\s*|\bxargs\s+)(?:sudo\s+)?(ls|find|tree|fd|dir|rg\s+--files|git\s+ls-files|git\s+ls-tree)\b",
    # ---- read-like shell commands (secondary access class)
    "read_shell": r"(?:^|[;&|]\s*)(?:sudo\s+)?(cat|head|tail|less|more|wc|stat|sed\s+-n|nl|bat)\b",
    # ---- hex / entropy
    "uuid": r"(?<![0-9A-Za-z_])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9A-Za-z_])",
    "hex_token": r"(?<![0-9A-Za-z_#])([0-9a-f]{7,64}|[0-9A-F]{7,64})(?![0-9A-Za-z_])",
    "git_cmd": r"\bgit\s+(?:-C\s+\S+\s+|--no-pager\s+|-c\s+\S+\s+)*(log|show|rev-parse|commit|status|branch|reflog|describe|cherry|blame|stash|merge-base|ls-tree|cat-file|rev-list|reset|checkout|switch|merge|rebase|cherry-pick|push|pull|fetch|tag|diff)\b",
    "git_hash_lines": [
        r"(?m)^commit ([0-9a-f]{7,40})\b",
        r"(?m)^[*|\\/_ ]*([0-9a-f]{7,40})\b",
        r"(?m)^\[[^\]\n]*? ([0-9a-f]{7,12})\]",
        r"(?m)^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})\b",
        r"HEAD is now at ([0-9a-f]{7,40})\b",
        r"(?m)^Merge: ([0-9a-f]{7,40}) ([0-9a-f]{7,40})\b",
        r"(?m)^\s*\+?\s*([0-9a-f]{7,40})\.\.\.?([0-9a-f]{7,40})\s",
    ],
    "large_int": r"(?<![\w.,])[1-9]\d{4,18}(?![\w]|[.,]\d)",
    "epoch_s": r"(?<![\w.,])1[5-9]\d{8}(?![\w]|[.,]\d)",
    "epoch_ms": r"(?<![\w.,])1[5-9]\d{11}(?![\w]|[.,]\d)",
    "iso_ts": r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,9}))?",
    # ---- error proxies (copied from A4 prereg; analysis/out/phase_a/a4.json prereg)
    "codex_exit_header": r"(?m)^Exit code: (-?\d+)",
    "codex_process_exited": r"Process exited with code (-?\d+)",
    "aiv_bash_returncode_nonzero": r"bash has exited with returncode (?!0\b)-?\d+",
    "harness_timeout": r"(?m)^(?:timed out: |sandbox error: command timed out)",
    "census_task_families": {
        "py_traceback": r"Traceback \(most recent call last\)",
        "command_not_found": r"command not found",
        "permission_denied": r"Permission denied",
        "no_such_file": r"No such file or directory",
        "exit_status_N": r"\bexit status (?!0\b)-?\d+",
        "exited_with_code_N": r"\bexited with code (?!0\b)-?\d+",
        "returned_nonzero_exit_status": r"returned non-zero exit status",
        "error_line": r"(?m)^(?:Error|error):",
        "git_fatal": r"(?m)^fatal:",
        "npm_err": r"npm ERR!",
        "http_4xx_5xx": r"(?m)^(?:< )?HTTP/\d(?:\.\d)? [45]\d\d\b|curl: \(\d+\) The requested URL returned error:? [45]\d\d\b",
    },
    # ---- retry similarity tokens
    "sim_token": r"[A-Za-z0-9_./\-]+",
}

_C = {k: re.compile(v) for k, v in RX.items() if isinstance(v, str)}
_GIT_LINES = [re.compile(r) for r in RX["git_hash_lines"]]
_CENSUS = {k: re.compile(v) for k, v in RX["census_task_families"].items()}

# ========================================================================================================== SPEC
UNITS = {
    "swechat/claude_code": {"corpus": "swechat", "format": "claude_code"},
    "swechat/codex": {"corpus": "swechat", "format": "codex"},
    "swechat/opencode": {"corpus": "swechat", "format": "opencode"},
    "swechat/gemini": {"corpus": "swechat", "format": "gemini"},
    "swechat/copilot": {"corpus": "swechat", "format": "copilot"},
    "swechat/cursor": {"corpus": "swechat", "format": "cursor"},
    "swechat/simple_text": {"corpus": "swechat", "format": "simple_text"},
    "cc_local": {"corpus": "cc_local"},
    "aiv_cc": {"corpus": "aiv_cc"},
    "aiv_cu": {"corpus": "aiv_cu"},
    "whowhen": {"corpus": "whowhen"},
}
CC_FORMAT_UNITS = ("swechat/claude_code", "cc_local", "aiv_cc")

# A1 tool classes (analysis/out/phase_a/a1.json rules.human_wait.tool_classes), unchanged.
TOOL_CLASSES = {
    "auto_read": ["read", "glob", "grep", "ls"],
    "shell": ["shell"],
    "file_write": ["edit", "write", "notebookedit"],
    "human_interactive": ["askuserquestion", "exitplanmode", "enterplanmode", "ask_user", "enter_plan_mode",
                          "exit_plan_mode"],
    "internal_noperm": ["todo", "taskcreate", "taskupdate", "tasklist", "taskget", "toolsearch", "update_plan"],
    "subagent": ["subagent"],
}
CLASS_OF = {t: c for c, ts in TOOL_CLASSES.items() for t in ts}

CODEX_SHELL_RAW = {"shell", "shell_command", "exec_command", "write_stdin", "local_shell", "container.exec"}

PUBLIC_CC_TOOLS = {"shell", "read", "write", "edit", "glob", "grep", "ls", "todo", "subagent", "webfetch", "websearch",
                   "taskcreate", "taskupdate", "tasklist", "taskget", "taskoutput", "taskstop", "toolsearch",
                   "askuserquestion", "exitplanmode", "enterplanmode", "skill", "sendmessage", "notebookedit", "workflow",
                   "killshell", "bashoutput", "killbash", "monitor", "structuredoutput"}

CONSTANT_HEX = {  # well-known constants: never random, excluded from every digit test
    "4b825dc642cb6eb9a060e54bf8d69288fbee4904",  # git empty tree
    "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",  # git empty blob
    "d41d8cd98f00b204e9800998ecf8427e",  # md5("")
    "da39a3ee5e6b4b0d3255bfef95601890afd80709",  # sha1("")
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # sha256("")
}
HEX_LENGTHS = (7, 8, 32, 40, 64)
CONFIG_EXT = {"json", "yaml", "yml", "toml", "ini", "cfg", "conf", "env", "properties"}
PATH_KEYS = ("file_path", "filePath", "path", "absolute_path", "notebook_path", "dir_path", "relative_path",
             "target_directory", "paths", "file")
REF_CONTENT_KEYS = ("old_string", "oldString")

SPEC = {
    "version": "1.0",
    "title": "Phase B pre-registration: four fabrication-signal feasibility probes",
    "status": "Written before any Phase B number exists. Frozen when the orchestrator commits it. Later changes go to "
              "change_log with before/after/reason (README rule 3).",
    "data_rules": {
        "phase_b_input": "analysis/cache/<corpus>_B.parquet only (plus swechat_population.parquet for format, "
                         "whowhen_labels.json not used by these probes). Load only needed columns.",
        "thresholds_source": "Phase A split only: analysis/cache/<corpus>_A.parquet and analysis/out/phase_a/*.json. "
                             "No *_B.parquet was opened to write this file.",
        "phase_c_not_read": "The pre-registration author did not read any Phase C note or output (several Phase C lenses "
                            "read *_B.parquet, PHASE_A.md consequence 6). No threshold here depends on them.",
        "ir_source": "raw-transcript IR only, never conversations.parquet (PHASE_A.md consequence 5).",
        "join": "calls and results join on (session_id, call_id); first call and first result by seq per key (A1/A2).",
        "privacy": "cc_local outputs are aggregates only: no text, commands, paths, tokens or hex values. cc_local tool "
                   "names outside PUBLIC_CC_TOOLS are reported as 'mcp__*' or 'other_tool'.",
        "output_contract": "each Phase B script writes raw counts only to analysis/out/phase_b/<probe>.json and copies "
                           "the prereg.json sha256 it ran under into that JSON. Verdicts are computed mechanically "
                           "from the rules below and written under `verdicts`; interpretation goes to notes.",
    },
    "global": {
        "resampling_unit": "session (aiv_cc: run = <sdk_session_id>/rNNN; whowhen: task file).",
        "bootstrap": {"n_boot": stats.N_BOOT, "seed": stats.SEED, "impl": "analysis/lib/stats.py"},
        "ci_methods": {
            "event_rate": "stats.cluster_rate(num_by_session, den_by_session): ratio estimator with session-clustered "
                          "bootstrap 95% CI",
            "quantile": "stats.cluster_quantile(values, session_ids, q)",
            "session_share": "stats.wilson(k_sessions, n_sessions)",
            "zero_count": "when num == 0 the bootstrap CI is [0, 0]; report also the per-event Wilson upper bound and "
                          "the per-session Wilson upper bound (resolution A2-3). Verdicts use the per-event Wilson "
                          "upper bound in place of the bootstrap hi when num == 0.",
            "statistic_ci": "for statistics lib/stats.py lacks (Spearman, AUC, w_adj, rate differences): resample "
                            "sessions with replacement, n_boot draws from np.random.default_rng(seed), recompute the "
                            "statistic on the concatenated draw, take the 2.5/97.5 percentiles. Draws where the "
                            "statistic is undefined are skipped and counted; the CI is reported only if >= 900 of 1000 "
                            "draws are valid.",
        },
        "min_n": {
            "rate_reportable": {"den_min": 30, "sessions_min": 5,
                                "reason": "A2-2: a 2-session bootstrap is degenerate; A4 used >=10 results from >=3 "
                                          "sessions for proxy labels; 5 sessions is the smallest cluster count whose "
                                          "bootstrap has more than 100 distinct resamples (126)."},
            "quantile_reportable": {"p50": [30, 5], "p5_p95": [100, 5], "p1_p99": [500, 5],
                                    "reason": "at least 5 observations beyond the quantile"},
            "below_min": "report raw k/n (or n) and the label 'insufficient n'; no rate, no CI, no verdict.",
            "small_n_label": "a unit with < 30 B sessions in the verdict population gets the extra label 'small n' "
                             "(A1 gate: codex 15, opencode 25, gemini 10 sessions in A).",
        },
        "aiv_cc_rule": "Every aiv_cc verdict carries the label 'single-agent case study' (resolutions A4-3, A5-3: "
                       "33,473/33,475 A results and all A conservation pairs come from one SDK session of one agent). "
                       "Phase B reports the number of distinct sdk_session_id values in B and how many B runs share "
                       "an sdk_session_id with an A run (runs of one SDK session are one conversation, so B is not "
                       "held out in content for aiv_cc).",
        "multiplicity": "Verdicts are per probe x unit and descriptive; no family-wise correction. Each Phase B JSON "
                        "reports the number of verdict cells it computed.",
        "verdict_vocabulary": {
            "ALIVE": "the data support the mechanism for this unit at the pre-registered thresholds",
            "WEAK": "partly supported, or supported without its control",
            "DEAD": "the mechanism fails here (a kill criterion holds, or the honest baseline defeats it)",
            "INSUFFICIENT_N": "below the minimum n; reported, not interpreted",
            "INCONCLUSIVE": "Probe 2 only: a DEAD result in a unit whose antecedent record is known to be incomplete",
            "NOT_TESTABLE": "unit has no B sessions or was killed in Phase A",
        },
    },
    "units": UNITS,
    "tool_key": {
        "rule": "tool_key = lower(tool_raw) when tool_raw starts with 'mcp__'; for swechat/codex, lower(tool_raw) when "
                "it is a shell-family name or apply_patch; otherwise the IR `tool` column (ir.normalize_tool). "
                "Keeps aiv_cc Bash ('shell') apart from mcp__village__bash and Codex polls (write_stdin) apart from "
                "exec_command (A1 1.8, gate note on codex). cc_local: tool_key is passed through private_key() "
                "(PUBLIC_CC_TOOLS kept, else 'mcp__*' / 'other_tool') before any grouping, in A and in B.",
        "tool_class": TOOL_CLASSES,
        "tool_class_reason": "A1 classes (a1.json rules.human_wait.tool_classes) plus the Gemini/Codex names of the same "
                             "tools; everything else is 'other'.",
        "thread": "(session_id, is_subagent, agent_id or ''); main thread = is_subagent False. OpenCode child sessions "
                  "and Codex sub-agent rollouts are separate session_ids with is_subagent True (loader).",
    },
    "error_definitions": {
        "note": "Used by Probe 3 (the error class) and by Probe 2 (first-try success = primary error False). Native "
                "flags are the definition wherever filled; text proxies only where the native flag is absent. P/R are "
                "the A4 numbers (analysis/out/phase_a/a4.json, gate decisions, resolutions A4-1..A4-5).",
        "swechat/claude_code": {
            "primary": "native_error is True AND ir.error_marker(text) not in {cc_permission_denied, cc_interrupt_reject}",
            "classes": "by ir.error_marker(text): cc_exit_code, cc_tool_use_error, cc_permission_denied, "
                       "cc_interrupt_reject, unmarked (native True, no marker)",
            "null_means": "not flagged (CC writes is_error only on Bash results and on failures)",
            "A_evidence": "native fill 4,464/13,592 = 0.328 [0.285, 0.370]; text proxy A: P 488/488 (Wilson lo 0.992), "
                          "R 488/614 = 0.795 [0.720, 0.855], 90 sessions; census regexes add 0 TP and 112 FP.",
            "label": "usable",
        },
        "cc_local": {
            "primary": "native_error is True AND ir.error_marker(text) not in {cc_permission_denied, cc_interrupt_reject}",
            "classes": "as swechat/claude_code; permission denials (157 of the 311 native-true shell results in A) are "
                       "reported apart from command failures",
            "null_means": "not flagged (9 non-shell Workflow results are False, resolution A4-4)",
            "A_evidence": "text proxy A: P 331/331, R 331/349 = 0.948 [0.900, 0.977], 74 sessions.",
            "label": "usable",
        },
        "aiv_cc": {
            "primary": "native_error is True AND ir.error_marker(text) not in {cc_permission_denied, cc_interrupt_reject}",
            "secondary_unvalidated": "village_bash_proxy: tool_raw mcp__village__bash, text parses as a JSON object, "
                                     "and its 'error' field matches aiv_bash_returncode_nonzero OR harness_timeout OR "
                                     "any census_task_family. Reported as its own class, never pooled.",
            "A_evidence": "text proxy A: R 296/538 = 0.550 [0.342, 0.791]; B: P 534/637 = 0.838 [0.736, 0.897], "
                          "R 534/538 = 0.993 [0.977, 0.999], 38 runs; the 1,746 village-bash JSON turns carry no "
                          "native flag.",
            "label": "usable (native); village-bash class unvalidated",
        },
        "swechat/codex": {
            "primary": "native_error is True; OR (native_error is null AND tool_key is a shell-family name AND the "
                       "first 600 chars of text match codex_exit_header or codex_process_exited with N != 0)",
            "A_evidence": "exit header alone: P 47/47, R 47/49 = 0.959 [0.823, 1.0]; positives from 6 sessions "
                          "(resolution A4-2). The timeout string (predictor C) is NOT part of the definition.",
            "label": "usable (small n)",
        },
        "swechat/opencode": {
            "primary": "native_error is True (status=error OR metadata.exit != 0)",
            "A_evidence": "native fill 3,735/3,735; no text proxy for shell (R 26/157 = 0.166 [0.096, 0.253]).",
            "label": "usable (native only)",
        },
        "swechat/gemini": {
            "primary": "two classes, never pooled into one rate: tool_failure = native_error is True (status error or "
                       "cancelled); command_failure = ir.error_marker(text) == 'gemini_exit_code_nonzero'. "
                       "'any_error' (either class) is used only as a session indicator (zero-error tail) and for "
                       "first-try success, and is labelled 'union'.",
            "A_evidence": "A: P 0/280, R 0/143: the classes never co-occur (loader construction); 10 sessions.",
            "label": "native usable; text class unvalidated",
        },
        "swechat/copilot": {"primary": "native_error is True", "label": "NOT_TESTABLE in B (0 B sessions)"},
        "swechat/cursor": {"primary": None, "label": "DEAD (no tool results in the source)"},
        "swechat/simple_text": {"primary": None, "label": "DEAD (no tool calls)"},
        "aiv_cu": {
            "primary": "PROXY: stderr matches aiv_bash_returncode_nonzero OR harness_timeout OR any census_task_family "
                       "(stderr is not a failure flag; no native flag exists)",
            "A_evidence": "fires on 118/6,107 = 0.019 [0.013, 0.026]; precision/recall not measurable (no reference); "
                          "stderr rate varies by model family.",
            "label": "PROXY (unvalidated): every aiv_cu Probe 2/3 verdict is capped at WEAK and labelled proxy-based",
        },
        "whowhen": {
            "primary": "Algorithm-Generated code_exec results: exit_code is not null AND exit_code != 0. "
                       "Hand-Crafted: no failure signal (Probe 3 DEAD for that stratum).",
            "A_evidence": "exit code on 87/353 results (36 nonzero); A agreement 36/36 is tautological.",
            "label": "usable for AG code_exec only",
        },
    },
}

# ------------------------------------------------------------------------------------------------------- PROBE 1
SPEC["probe1"] = {
    "name": "latency physics",
    "question": "Do work-bound tool latencies in honest logs separate from generation time well enough that a tool "
                "result produced by generation (fabricated) would stand out?",
    "units_alive_after_A1": ["swechat/claude_code", "cc_local", "aiv_cc", "swechat/codex", "swechat/opencode",
                             "swechat/gemini"],
    "units_not_testable": {
        "swechat/copilot": "ALIVE by the A1 rule only (2 A sessions); 0 B sessions",
        "aiv_cu": "KILLED in A1: call and result share one stamp in 6,107/6,107 pairs",
        "whowhen": "KILLED in A1: no timestamps (0 of 353 pairs stamped)",
        "swechat/cursor": "KILLED in A1: no timestamps, no results",
        "swechat/simple_text": "KILLED in A1: no tool pairs; 0 B sessions",
    },
    "b_recheck_of_A1_kill_rule": "Phase B first re-applies the A1 kill rule (gate_rules.A1_latency_kill_rule) to each "
                                 "unit's B pairs; a unit that fails it in B is DEAD for Probe 1.",
    "pair": "joined call/result with both stamps; delta_s = parse_ts(result.ts) - parse_ts(call.ts) in exact "
            "microseconds / 1e6 (A1 rules.delta). Negative deltas are kept in counts and excluded from log-scale "
            "statistics (A: 6 negatives, all Gemini).",
    "no_human_wait_filter": {
        "source": "A1 proposed rule (notes/phase_a_a1.md 'Proposed rule for Probe 1') with resolutions A1-1..A1-3.",
        "rule_all_units": [
            "1. unit alive and both stamps present",
            "2. tool class allowed for the unit (below)",
            "3. CC formats and Gemini: the call is the last (CC) / only (Gemini) call of its API message "
            "(same session_id, api_msg_id); a null api_msg_id counts as its own message",
            "4. result marker not cc_permission_denied / cc_interrupt_reject; Codex extra.exec_status != 'declined'; "
            "Gemini extra.status != 'cancelled'",
            "5. no linked hook: swechat CC meta events with extra.type == 'hook_progress' and parent_call_id == call_id; "
            "cc_local attachment events whose extra.attachment_type starts with 'hook' and extra.toolUseID == call_id",
            "6. Codex: the most recent turn_context meta (extra.approval_policy) before the call says 'never', and the "
            "result is not extra.unified_exec_running",
        ],
        "allowed_classes": {
            "swechat/claude_code": ["auto_read", "internal_noperm"],
            "cc_local": ["auto_read", "internal_noperm"],
            "aiv_cc": "every class except human_interactive and subagent (permissionMode bypassPermissions in 125/125 A "
                      "runs)",
            "swechat/codex": "every class except subagent tools (spawn_agent, wait_agent, close_agent, list_agents) and "
                             "write_stdin polls",
            "swechat/opencode": ["auto_read", "internal_noperm"],
            "swechat/gemini": ["auto_read", "internal_noperm"],
        },
        "excluded_reason": "shell/edit/write/web latencies in swechat CC carry human waits (edit/write > 2 s in "
                           "296/2,235 = 13.2% [6.8, 21.7]; rejections p50 23.0 s in 19/126 sessions; shell pre-exec "
                           "offset > 2 s in 50/367 = 13.6% [5.8, 25.9]); permissionMode is not in the IR, so they "
                           "stay out (rule 7 of the A1 proposal). OpenCode and Gemini permission timing is unknown "
                           "(A1 1.8), so only their auto-approved read tools qualify.",
        "aiv_cc_floor": "aiv_cc deltas below 0.1 s are floor-bound (A min 0.046 s on every tool, resolution A1-6); "
                        "they stay in the floor statistics and are reported as a separate 'below_0.1s' count.",
    },
    "per_tool_statistics": {
        "grouping": "unit x tool_key, qualified pairs; also 'all pairs' (unfiltered) for reference, labelled "
                    "human-wait-contaminated where the filter excludes the class",
        "quantiles": "min, p1, p5, p10, p50, p95, max of delta_s; p1/p5/p10/p50/p95 with cluster_quantile CIs subject to "
                     "global.min_n.quantile_reportable",
        "corr_bytes_latency": "Spearman rho between UTF-8 byte length of result text and delta_s, per tool_key with "
                              ">= 30 pairs from >= 5 sessions; CI per global.ci_methods.statistic_ci",
        "honest_floor": "per unit x tool_key: p1 and p5 of qualified delta_s (cluster CI). The A-split values are in "
                        "resolved.probe1.floors and are the transfer thresholds below.",
        "floor_transfer": "share of B qualified pairs with delta_s < the A-split p5 of the same unit x tool_key "
                          "(cluster_rate). Nominal 0.05. The floor TRANSFERS if the CI overlaps [0.025, 0.10]; else "
                          "the label is FLOOR_SHIFT (direction reported). Only for unit x tool_key with an A p5 "
                          "(A n >= 100 from >= 5 sessions) and B n >= 100.",
    },
    "near_zero_variance_kill": {
        "definition": "for a unit x tool_key with >= 30 qualified pairs from >= 5 sessions: FLAT if "
                      "(p75 - p25 of delta_s) <= 2 x stamp resolution OR (p75 - p25 of log10 delta_s, positive deltas) "
                      "< 0.05 (i.e. p75/p25 < 1.122).",
        "stamp_resolution_s": {"ms_units": 0.001, "aiv_cc": 0.000001,
                               "source": "A1 gcd_abs_nonzero_delta_us: 1,000 us in every ms-stamped format, 1 us aiv_cc"},
        "kill": "the unit is DEAD for Probe 1 if every reportable work-bound tool_key (W set) is FLAT.",
        "reason": "if latency within a tool is constant up to stamp quantisation, it carries no information about the "
                  "work done; the A split values (resolved.probe1.iqr_log10) are 1-2 orders of magnitude above 0.05.",
    },
    "floor_step_change": {
        "series": "per session x tool_key: qualified pairs in seq order, x = log10(delta_s) (positive deltas)",
        "eligible": "series with n >= 2m, m = 20 (minimum segment size 20 pairs on each side)",
        "statistic": "D_k = |Q10(x[:k]) - Q10(x[k:])| for k in {m, m+s, m+2s, ...} <= n-m with s = max(1, n // 100) "
                     "(Q10 = numpy quantile 0.10, linear); D* = max_k D_k; k* = smallest argmax "
                     "(prereg_common.change_point)",
        "test": "permutation: 199 shuffles of x with np.random.default_rng(SEED + i), i = 0-based index of the series "
                "in sorted (session_id, tool_key) order; p = (1 + #{D*_perm >= D*}) / 200",
        "step": "p <= 0.01 AND D* >= log10(2) (a factor-2 shift of the floor)",
        "report": "eligible series, steps, step share (Wilson over series; cluster_rate over sessions), direction and "
                  "size of each step, k*/n",
        "label": "floor STABLE if step share point <= 0.10, else UNSTABLE",
        "reason": "single change point, fixed method, no tuning. A factor of 2 is the smallest shift that clearly "
                  "exceeds the between-corpus floor differences in A1 (event-time p1 1-31 ms vs the aiv_cc ~50 ms "
                  "pipeline floor is a factor >= 1.6).",
    },
    "separability": {
        "work_bound_set_W": {
            "swechat/claude_code": "qualified pairs of class auto_read",
            "cc_local": "qualified pairs of class auto_read",
            "swechat/opencode": "qualified pairs of class auto_read",
            "swechat/gemini": "qualified pairs of class auto_read",
            "aiv_cc": "qualified pairs of tool_key read, glob, grep, ls, shell (Bash), edit, write",
            "swechat/codex": "qualified pairs of tool_key shell_command, exec_command, apply_patch, "
                             "mcp__filesystem__read_text_file, mcp__filesystem__read_multiple_files",
            "latency": "delta_s",
        },
        "generation_bound_set_G": {
            "tools": "subagent (Task/Agent/OpenCode task), webfetch, websearch, aiv_cc mcp__village__search_history",
            "latency": "CC formats: extra.durationMs/1000 (WebFetch), extra.durationSeconds (WebSearch), "
                       "extra.totalDurationMs/1000 (Task/Agent) when present, else delta_s. In swechat CC and cc_local "
                       "a webfetch/websearch pair without the tool-reported duration is excluded (its delta carries "
                       "permission waits: A1 1.8, WebFetch p50 1.68 s past its own duration in swechat).",
            "exclusions": "result marker cc_interrupt_reject / cc_permission_denied; subagent pairs whose nested events "
                          "(parent_call_id == call_id) contain such a marker or a human_interactive call",
            "per_unit": {
                "swechat/claude_code": "subagent, webfetch, websearch",
                "cc_local": "subagent, webfetch, websearch, workflow",
                "aiv_cc": "websearch, webfetch, mcp__village__search_history",
                "swechat/opencode": "subagent, websearch (webfetch excluded: permission timing unknown)",
                "swechat/gemini": "websearch (google_web_search)",
                "swechat/codex": "none (web search is server-side with no result; wait_agent has fixed timeouts)",
            },
        },
        "generation_time_model": {
            "tokens_per_char": 0.25,
            "tokens_per_char_reason": "below the smallest A5 Theil-Sen tokens/char slope (OpenCode 0.263; CC formats "
                                      "0.342-0.514), so result token counts are under- not over-estimated and the "
                                      "implied generation time is conservative (short).",
            "result_tokens": "len(result text) x tokens_per_char",
            "G_rate": "per unit, A split: rate of one API response = output tokens / gen_gap. gen_gap = (latest stamp "
                      "among the response's call events) - (stamp of the latest result or user event of the same "
                      "thread before the response's first call). Output tokens = max usage_out over the response's "
                      "rows (USAGE DEDUPE on (session_id, api_msg_id)); Codex: usage_out of the token_count row that "
                      "closes the calls. Responses kept if output tokens >= 50 and 0 < gen_gap <= 600 s. If the A "
                      "median of per-response output tokens is < 20 (streaming partials, A5: aiv_cc per-response max "
                      "median 1), the unit uses char-based tokens instead: (assistant text + call args chars + "
                      "extra.thinking_chars) x tokens_per_char.",
            "G90": "the A-split 90th percentile of per-response rates (resolved.probe1.generation_rate.<unit>.G90). "
                   "The fast end is used so implied generation times are short and the work-bound false-positive "
                   "share below is conservative.",
            "T_gen": "T_gen = result_tokens / G90 (seconds)",
            "r": "r = latency / T_gen",
            "eligibility": "pairs with T_gen >= 1.0 s only (outputs long enough that generating them would take at "
                           "least 1 s). 1.0 s sits just above the A1 auto_read p95 (0.938 s swechat CC, 0.977 s "
                           "aiv_cc, 0.537 s cc_local), so smaller outputs cannot separate by construction.",
        },
        "statistics": {
            "fp_share": "share of eligible W pairs with r >= 1 (a work-bound result that took at least as long as "
                        "generating it would have): cluster_rate",
            "auc": "AUC = P(log10 r_G > log10 r_W) + 0.5 P(tie) over eligible pairs; CI per statistic_ci (both groups "
                   "drawn from the same resampled sessions)",
            "also_reported": "medians of log10 r per group with cluster_quantile CIs; Spearman(bytes, latency) per group",
        },
        "min_n": {"W": "eligible W >= 100 pairs from >= 10 sessions", "G": "eligible G >= 30 pairs from >= 5 sessions"},
        "labels": {
            "fp": "ALIVE if fp_share <= 0.05 and its CI hi <= 0.10; WEAK if fp_share <= 0.20; DEAD otherwise",
            "auc": "ALIVE if AUC >= 0.85 and CI lo >= 0.75; WEAK if AUC >= 0.70; DEAD otherwise; INSUFFICIENT_N if G "
                   "is below min n",
        },
        "threshold_reason": "judgment calls fixed here, not derived from an A outcome (no r, fp_share or AUC was "
                            "computed on A). 0.05 is the false-positive budget at which a per-result flag stays usable "
                            "on sessions of hundreds of calls; 0.85/0.75 is conventional 'good' discrimination.",
    },
    "verdict": {
        "DEAD": "B fails the A1 kill rule; or every reportable W tool_key is FLAT; or fp label DEAD; or auc label DEAD",
        "INSUFFICIENT_N": "W below min n",
        "ALIVE": "fp ALIVE and auc ALIVE",
        "WEAK": "anything else that is not DEAD (including fp ALIVE with auc INSUFFICIENT_N: no positive control)",
        "downgrade": "ALIVE becomes WEAK if the floor label is UNSTABLE or FLOOR_SHIFT holds for a majority of the "
                     "unit's transfer-tested tool_keys",
        "labels_added": "aiv_cc: single-agent case study; units with < 30 B sessions: small n",
    },
}

# ------------------------------------------------------------------------------------------------------- PROBE 2
SPEC["probe2"] = {
    "name": "knowledge precedence",
    "question": "In honest logs, how often does an agent use a path, symbol or config key before anything in its "
                "visible record could have told it? If rarely, an unsourced reference (or a correct first-try deep "
                "access) is a usable anomaly signal.",
    "units": {
        "full": ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "cc_local", "whowhen"],
        "antecedents_incomplete": {
            "aiv_cc": "the SDK prompt and memory are not in the IR (0 user events in 125 A runs) and earlier runs of the "
                      "same SDK session are other IR sessions, possibly in split A",
            "aiv_cu": "no system prompt, memory or user text in the IR; GUI results carry no text (A2: 3,393/6,107 "
                      "results have no text)",
            "swechat/cursor": "the source records no tool results; 8 B sessions",
        },
        "antecedents_incomplete_rule": "missing antecedents can only inflate 'unsourced'. So a low unsourced rate is "
                                       "still valid (ALIVE/WEAK allowed), but a DEAD result becomes INCONCLUSIVE.",
        "not_testable": {"swechat/copilot": "0 B sessions", "swechat/simple_text": "no tool calls"},
    },
    "stream": "references are evaluated per thread. Main thread: antecedents are events of the main thread "
              "(is_subagent False), which include the results that subagents return to it. Subagent thread: only "
              "events of that thread (same session_id, is_subagent True, agent_id); its nested prompt (system event "
              "with extra.nested_prompt, CC; the child session's first user/system text, OpenCode) is the source "
              "'parent_prompt'. Subagents are a separate stratum, never pooled with main threads.",
    "extraction": {
        "fields": {
            "structured_path": "string (or list-of-string) values of args keys " + ", ".join(PATH_KEYS) +
                               " in any call; apply_patch headers (patch_file, patch_move) in Codex 'input' and OpenCode "
                               "'patchText'",
            "free_path": "regex paths in: shell `command` (CC Bash, OpenCode bash, Gemini run_shell_command, aiv_cc Bash "
                         "and mcp__village__bash, aiv_cu bash), Codex `cmd`/`command`, whowhen AG code_exec code "
                         "strings, whowhen HC instruction strings",
            "symbol_ref": "old_string / oldString values (CC Edit, MultiEdit edits[].old_string, Gemini replace, "
                          "OpenCode edit, aiv_cc Edit) and the '-' and ' ' lines of Update File hunks in apply_patch",
            "symbol_shell": "shell command strings (as free_path)",
            "symbol_search": "Grep/grep/search_file_content/grep_search `pattern` values (reported, not in any verdict: "
                             "a search for an unseen name is legitimate exploration)",
            "env_var": "env_var regex over shell commands and symbol_ref text",
            "cfg_key": "cfg_key_line over symbol_ref text of edits whose target path extension is in "
                       + ",".join(sorted(CONFIG_EXT)) + " (or basename .env); git_config_key over shell commands",
            "creation_fields_excluded": "new_string, content, '+' lines of patches, Write content: new code is not a "
                                        "reference",
        },
        "free_path_filter": "mask url matches first; keep a path_abs_posix / path_windows / path_relative match if "
                            "(a) its last component matches path_ext (or is a dotfile of >= 2 chars), or (b) it is "
                            "absolute (starts with '/', '~' or a drive) with >= 2 components; drop it if every "
                            "component is digits only or it contains no letter",
        "path_normalisation": "strip quotes/backticks and trailing .,;:)]}>'\"; strip path_line_suffix; '\\' -> '/'; "
                              "collapse '//' ; drop leading './' and trailing '/'; replace any redaction marker "
                              "(redaction_typed, then bare REDACTED) by '<R>'; lowercase if it has a drive letter. "
                              "components = split on '/' without '' and '.'",
        "path_key": "last two components joined by '/' (basename alone if one component). Paths whose components "
                    "include '<R>' are counted as 'redacted_path' and excluded from the rates.",
        "symbol_filter": "matches of sym_snake, sym_camel, sym_pascal with length >= 5",
        "env_filter": "env_var matches with length >= 5",
        "first_mention": "a reference is evaluated once per thread, at the first call (by seq) whose extracted "
                         "references include its key",
    },
    "sourcing": {
        "sources": {
            "result": "text (and stderr) of result events of the thread with seq < call seq",
            "user": "user events of the thread with seq < call seq; whowhen: also events with extra.task_prompt true",
            "system": "system events of the thread with seq < call seq, excluding the subagent nested prompt",
            "parent_prompt": "subagent threads only: the nested prompt (see stream)",
            "peer": "whowhen only: assistant text of a different speaker (extra.agent) with seq < call seq",
        },
        "never_a_source": "the agent's own assistant text, thinking, and earlier call args",
        "text_normalisation": "antecedent text gets the same '\\' -> '/' and redaction -> '<R>' replacement",
        "path_match": "path_key occurs in the antecedent text with a non-path character (or text edge) on both sides: "
                      "left boundary = start, '/', or a char not in [A-Za-z0-9_.-]; right boundary = end or a char not "
                      "in [A-Za-z0-9_.-]",
        "path_enumeration": "also sourced (source 'enumeration') if an earlier call of the thread is an enumeration "
                            "(tool_key glob, ls, grep, or a shell command matching enum_shell) whose extracted directory "
                            "argument's last component equals the path's parent component (or the enumeration has no "
                            "directory argument and the path has one component), and whose result text contains the "
                            "path's basename with the same boundaries",
        "symbol_match": "whole-word, case-sensitive occurrence ((?<![A-Za-z0-9_])sym(?![A-Za-z0-9_])) in antecedent text",
        "unsourced": "a first-mention reference with no match in any source",
        "report": "per unit x stratum (main / subagent) x reference class: n first mentions, sessions, share sourced "
                  "by each source separately (cluster_rate), unsourced share (cluster_rate)",
    },
    "deep_first_try": {
        "access_call": "first access in the thread to a path_key by an access tool: tool_key read (incl. read_file, "
                       "view, mcp__filesystem__read_text_file/read_multiple_files) or edit (CC Edit/MultiEdit, Gemini "
                       "replace, OpenCode edit, apply_patch 'Update File' paths). Write/Add File (creation) excluded.",
        "depth": "for a relative path: number of components. For an absolute path: components after the session's "
                 "workspace root = longest common component prefix of all absolute structured access paths of the "
                 "session's main thread (>= 2 such paths and a prefix of >= 2 components); otherwise the session's "
                 "most frequent 3-component prefix; with neither, the path is 'depth_unknown' and excluded.",
        "deep": "depth >= D_unit from resolved.probe2.depth_threshold.<unit>. Rule: D_unit = max(3, ceil(A-split p75 "
                "of the depth of the unit's first-mention access paths, main thread)) when the unit has >= 50 such A "
                "depths from >= 5 sessions; otherwise D_unit = the pooled value (same rule over the full units' main "
                "threads pooled).",
        "first_try_success": "the access call's result is not an error under error_definitions.<unit>.primary "
                             "(Gemini: union; aiv_cu: proxy) and the pair exists",
        "knowledge_from_nowhere": "deep AND first_try_success AND unsourced (no source, no enumeration)",
        "secondary": "the same for read-like shell commands (read_shell regex; first free_path of the command)",
    },
    "statistics": {
        "S_deep": "primary: share of deep first-try successful accesses (main thread) that are knowledge_from_nowhere; "
                  "cluster_rate; also the session share with >= 1 (Wilson)",
        "S_path_any": "unsourced share of first-mention paths (any field)",
        "S_symbol_ref": "unsourced share of first-mention symbols in symbol_ref fields",
        "S_env_cfg": "unsourced share of first-mention env_var and cfg_key",
        "instrument_check": "swechat/claude_code main-thread S_symbol_ref must be <= 0.10. Claude Code refuses an Edit "
                            "on a file not Read in the session, so its old_string symbols should almost always be in "
                            "an earlier result. If the check fails, every Probe 2 verdict is capped at WEAK and "
                            "labelled 'matching instrument suspect'.",
        "min_n": "S_deep verdict needs >= 100 deep first-try accesses from >= 20 sessions; S_path_any >= 200 first "
                 "mentions from >= 20 sessions",
    },
    "verdict": {
        "per_unit_main_thread": "ALIVE if S_deep <= 0.05 and its CI hi <= 0.10; WEAK if S_deep <= 0.20; DEAD if "
                                "S_deep > 0.20; INSUFFICIENT_N below min n. If S_deep is INSUFFICIENT_N, the same rule "
                                "is applied to S_path_any and the verdict is capped at WEAK.",
        "subagent_stratum": "same rule, reported as a separate verdict",
        "caps": "antecedents_incomplete units: DEAD -> INCONCLUSIVE; aiv_cu: proxy success -> cap WEAK; aiv_cc: "
                "single-agent case study; instrument_check failure -> cap WEAK",
        "threshold_reason": "judgment: a reference-level flag needs a <= 5% false-positive base rate to be usable on "
                            "sessions with many accesses; > 20% means unsourced references are normal. No unsourced "
                            "share was computed on A (calibration counted extraction yields and depths only).",
    },
}

# ------------------------------------------------------------------------------------------------------- PROBE 3
SPEC["probe3"] = {
    "name": "pushback",
    "question": "Does honest work meet friction (tool errors) often enough that a long session with no errors is "
                "anomalous, and do honest agents react to a failure (retry) more than to a success?",
    "units": {
        "testable": ["swechat/claude_code", "cc_local", "aiv_cc", "swechat/codex", "swechat/opencode",
                     "swechat/gemini", "aiv_cu", "whowhen/Algorithm-Generated"],
        "dead": {"swechat/cursor": "no results", "swechat/simple_text": "no calls",
                 "whowhen/Hand-Crafted": "no failure signal"},
        "not_testable": {"swechat/copilot": "0 B sessions"},
    },
    "error_definition": "error_definitions.<unit>.primary; class breakdown reported (CC marker classes; Gemini two "
                        "classes; aiv_cc village-bash proxy as its own class)",
    "session_call_count": "n_calls(session) = number of paired calls in the session, all threads",
    "long_session": "n_calls >= L75(unit), the A-split 75th percentile of n_calls over the unit's A sessions with >= 1 "
                    "paired call (resolved.probe3.long_session.<unit>.L75); secondary L90 (90th percentile). "
                    "whowhen/AG: n_calls = paired code_exec calls; aiv_cu: per stratum is reported, the verdict uses "
                    "the pooled unit.",
    "zero_error_tail": {
        "Z": "share of long sessions with zero primary errors (Wilson over sessions)",
        "expected_under_independence": "E0 = mean over long sessions s of (1 - p)^n_s, p = the unit's pooled B "
                                       "per-call primary error rate; report Z / E0",
        "also": "Z at L90; Z per error class; Gemini: Z for 'union' and per class",
    },
    "retry": {
        "pair": "consecutive calls (c_i, c_{i+1}) of the same thread by seq, where c_i has a paired result",
        "similarity": "Jaccard of the token sets (sim_token, lowercased) of c_i and c_{i+1}: the shell command for shell "
                      "tools, otherwise all string/number values of the parsed args",
        "retry": "c_{i+1} has the same tool_key AND (identical args OR Jaccard >= 0.5); 'exact' if identical args",
        "R_fail": "P(retry | c_i primary error)",
        "R_ok": "P(retry | c_i not an error)",
        "effect": "R_fail - R_ok with statistic_ci (session resampling)",
        "classes_apart": "c_i with cc_permission_denied / cc_interrupt_reject results are reported as their own rows",
        "similarity_reason": "0.5 = at least half of the distinct tokens shared; a judgment call fixed here. "
                             "No A retry rate was computed.",
    },
    "early_late": {
        "eligible": "sessions with n_calls >= 20 (>= 10 calls per half)",
        "split": "calls ordered by seq (all threads); early = first floor(n/2), late = the rest",
        "statistic": "late rate - early rate (sum errors / sum calls per half over sessions), statistic_ci with "
                     "paired session resampling; also the share of sessions with errors early but none late (Wilson)",
        "label": "descriptive only (no verdict); 'stable' if the difference CI contains 0",
    },
    "min_n": {"zero_error_verdict": "n_long >= 20 sessions (ALIVE needs n_long >= 30)",
              "retry_verdict": ">= 30 failed c_i with a successor from >= 10 sessions, and >= 30 non-failed c_i"},
    "verdict": {
        "zero_error_tail (primary)": "ALIVE if Z <= 0.10 and Wilson hi <= 0.20 and n_long >= 30; WEAK if Z <= 0.30; "
                                     "DEAD if Z > 0.30",
        "reaction (secondary)": "ALIVE if effect CI lo >= 0.10; WEAK if effect CI lo > 0; DEAD otherwise",
        "caps": "aiv_cu: proxy -> both capped at WEAK; aiv_cc: single-agent case study; Gemini: verdict from the union "
                "indicator, labelled 'union of two unvalidated-together classes'",
        "threshold_reason": "judgment calls fixed here. Context from A (not an outcome of this probe): per-call native "
                            "error rates were 614/13,592 (swechat CC), 349/5,164 (cc_local), 538/33,475 (aiv_cc); at "
                            "the L75 call counts in resolved.probe3 an independent-error model predicts almost no "
                            "zero-error long sessions, so Z mostly measures how clumped errors are across sessions.",
    },
}

# ------------------------------------------------------------------------------------------------------- PROBE 4
SPEC["probe4"] = {
    "name": "entropy",
    "question": "Is hex (and are numbers/timestamps) typed by the model distinguishable from machine-produced values "
                "in honest logs? If yes, a fabricated tool result written by the model would carry the signature.",
    "units": {"testable": ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "cc_local",
                           "aiv_cc", "aiv_cu", "whowhen"],
              "pooled_cells": {"swechat/*": "all swechat formats pooled (tokens deduped across formats, sessions kept)",
                               "public/*": "every unit except cc_local pooled"},
              "pooled_reason": "the feasibility projection (resolved.feasibility_projection) puts T_orig below N_min in "
                               "most single units; pooled cells are pre-registered so the test is not abandoned or "
                               "re-cut after seeing B. Pooled verdicts carry the label 'pooled' and never replace a "
                               "unit verdict.",
              "control_missing": {"swechat/cursor": "no results, so no machine class; 8 B sessions"},
              "not_testable": {"swechat/copilot": "0 B sessions", "swechat/simple_text": "0 B sessions"}},
    "hex": {
        "pre_mask": "1) replace uuid matches by a space (UUIDs have fixed version/variant nibbles; counted apart); "
                    "2) drop any hex token inside a maximal non-whitespace run that contains 'REDACTED' (redaction_run; "
                    "dropped tokens counted)",
        "token": "hex_token matches (all-lowercase or all-uppercase; mixed case never matches; not after '#', "
                 "not inside 0x prefixes) with length in {7, 8, 32, 40, 64}, containing >= 1 digit AND >= 1 letter, "
                 "not in CONSTANT_HEX; lowercased",
        "classes": {
            "M_git": "machine control: hashes captured by git_hash_lines (capture groups only) in result text of shell "
                     "calls whose command matches git_cmd",
            "M_all": "every hex token in result text and stderr",
            "T_copy": "call-args tokens (string values of the parsed args JSON; raw string if unparseable) that are "
                      "sourced: equal to, or a prefix of, a token seen earlier in the session in result / user / "
                      "system text (session-wide, all threads)",
            "T_orig": "call-args tokens not sourced (model-originated in this record)",
            "A_copy, A_orig": "the same split for assistant text",
        },
        "dedupe": "a token value counts once per unit x class (first occurrence in (session_id, seq) order, which also "
                  "assigns its session for the cluster bootstrap)",
        "digit_test": {
            "counts": "16-symbol counts over all characters of the class's distinct tokens",
            "expected": "per token of length L: each digit p_d(L) = E[#digits | 1 <= #digits <= L-1] / (10 L), each "
                        "letter p_l(L) = (1 - 10 p_d(L)) / 6, #digits ~ Binomial(L, 10/16) truncated by the token "
                        "filter; expected counts = sum over tokens of L p(L)",
            "chi2": "Pearson chi-square, df = 15 (scipy.stats.chisquare with f_exp)",
            "effect": "w_adj = sqrt(max(0, (chi2 - 15) / N)), N = symbols (bias-corrected Cohen's w)",
            "ci": "statistic_ci over sessions",
        },
        "N_min": "minimum symbols for a verdict: smallest N with power >= 0.80 to detect w = 0.15 at alpha 0.01, "
                 "df 15 (noncentral chi-square); value in resolved.probe4.N_min",
        "instrument_check": "control = M_git if N(M_git) >= N_min else M_all. Instrument OK if control w_adj CI hi <= "
                            "0.15 (the detection effect size behind N_min: the control must exclude a deviation as large "
                            "as the one the test is built to find). A-split control values: resolved.probe4.control_A.",
        "redaction_sensitivity": "swechat units: repeat the T_orig and control tests on events whose text has no "
                                 "'REDACTED' at all; report both",
    },
    "numbers": {
        "large_int": "large_int matches (5-19 digits, no leading zero, not part of a decimal or identifier), "
                     "excluding epoch_s / epoch_ms matches and integers that are part of a hex token",
        "round_metrics": "share with last digit 0, last two 00, last three 000, last digit in {0,5}",
        "expected_uniform_last_digits": {"last_0": 0.1, "last_00": 0.01, "last_000": 0.001, "last_0_or_5": 0.2},
        "classes": "M_all (results/stderr), T_copy/T_orig (args; JSON numbers included as their decimal string), "
                   "A_copy/A_orig (assistant text); sourcing as for hex (exact string)",
        "dedupe": "distinct values per unit x class",
    },
    "timestamps": {
        "patterns": "iso_ts, epoch_s, epoch_ms",
        "round_metrics": "iso: seconds == '00' (expected 1/60), fraction present and all zeros (expected 10^-digits); "
                         "epoch_s: last digit 0 (0.1); epoch_ms: last three 000 (0.001)",
        "classes": "as numbers",
    },
    "statistics": "per unit x class: n tokens, n symbols, chi2, p, w_adj with CI; round shares with cluster_rate "
                  "(session assigned by first occurrence) and their excess over the uniform expectation",
    "verdict": {
        "hex (primary)": "INSUFFICIENT_N if N(T_orig) < N_min (also report N), or if the control (M_git, else "
                         "M_all) has < N_min symbols. DEAD (instrument) if the control fails the instrument check. Else, with h = control w_adj CI hi: ALIVE if T_orig w_adj point >= 0.15 "
                         "AND T_orig w_adj CI lo > h; WEAK if T_orig w_adj point > h but ALIVE fails; DEAD if T_orig "
                         "w_adj point <= h (model-originated hex is as uniform as machine hex)",
        "round_numbers (secondary)": "ALIVE if T_orig last_0 share CI lo > M_all last_0 share CI hi + 0.05; WEAK if "
                                     "T_orig point > M_all CI hi; DEAD otherwise; needs >= 100 distinct values from >= "
                                     "10 sessions in each class",
        "caps": "aiv_cc single-agent case study; swechat: verdict stands only if the redaction sensitivity run gives the "
                "same label, else WEAK",
        "threshold_reason": "w = 0.15 lies between Cohen's small (0.1) and medium (0.3); invented placeholder hex "
                            "(abc1234, deadbeef) would be far above it. The instrument ceiling equals that effect size. "
                            "The A-split control values set no threshold; they show whether the ceiling is attainable "
                            "(it is, for controls of a few thousand symbols).",
    },
}

SPEC["drafting_notes"] = [
    {"what": "Probe 2 depth threshold: pooled D -> per-unit D_unit with pooled fallback",
     "when": "after the A calibration's depth histograms, before any B data or any Probe 2 outcome existed",
     "why": "A access-path depths differ by scaffold (prereg_calibration.json units.<unit>.probe2.access_depth_hist); a "
            "pooled D = 6 would leave 'deep' nearly empty for Gemini (5 of 204 A paths) and cc_local (6 of 97)."},
    {"what": "Probe 4 instrument ceiling 0.10 -> 0.15 and the ALIVE rule tied to the control's CI hi",
     "when": "after the A calibration's machine-control digit tests, before any model-typed class was tested",
     "why": "for a perfectly uniform control of N_min symbols the bootstrap hi of w_adj is about "
            "sqrt((chi2_0.975,15 - 15)/N_min) = 0.105, so a 0.10 ceiling would fail sound controls by chance; A control "
            "hi values were 0.040-0.171 (resolved.probe4.control_A)."},
]
SPEC["change_log"] = []


# ====================================================================================================== loading
def load_split(corpus, split, columns, filters=None):
    assert split in ("A", "B")
    df = pd.read_parquet(CACHE / f"{corpus}_{split}.parquet", columns=columns, filters=filters)
    if "session_id" in df.columns:
        df["session_id"] = df["session_id"].astype(str)
    return df


def swechat_formats():
    pop = pd.read_parquet(CACHE / "swechat_population.parquet", columns=["session_id", "format"])
    return dict(zip(pop.session_id.astype(str), pop.format.astype(str)))


def unit_frames(corpus, df):
    """Split a corpus frame into {unit: frame}."""
    if corpus == "swechat":
        fm = swechat_formats()
        df = df.assign(fmt=df.session_id.map(fm))
        return {f"swechat/{f}": g.drop(columns="fmt") for f, g in df.groupby("fmt")}
    return {corpus: df}


def sobj(series):
    return [x if isinstance(x, str) else None for x in series.astype(object)]


def jl(e):
    if isinstance(e, str):
        try:
            x = json.loads(e)
            return x if isinstance(x, dict) else {}
        except ValueError:
            return {}
    return {}


# ====================================================================================================== tools
def tool_key(unit, tool, tool_raw):
    tr = (tool_raw or "").lower()
    if tr.startswith("mcp__"):
        return tr
    if unit == "swechat/codex" and (tr in CODEX_SHELL_RAW or tr == "apply_patch"):
        return tr
    return tool if isinstance(tool, str) else (normalize_tool(tool_raw) or "unknown")


def tool_class(key):
    return CLASS_OF.get(key, "other")


def private_key(key):
    if key in PUBLIC_CC_TOOLS:
        return key
    return "mcp__*" if str(key).startswith("mcp__") else "other_tool"


# ====================================================================================================== pairing
def make_pairs(df):
    """Calls joined to results on (session_id, call_id), first by seq each. Adds delta_s (float, NaN if a stamp is
    missing). Columns of the result side get suffix _r."""
    calls = df[df.kind == "call"].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
    res = df[(df.kind == "result") & df.call_id.notna()].sort_values(["session_id", "seq"]).drop_duplicates(
        ["session_id", "call_id"])
    keep_r = [c for c in res.columns if c not in ("kind",)]
    p = calls.merge(res[keep_r], on=["session_id", "call_id"], suffixes=("", "_r"))
    d = []
    for a, b in zip(sobj(p.ts) if "ts" in p else [], sobj(p.ts_r) if "ts_r" in p else []):
        if a and b:
            pa, pb = parse_ts(a), parse_ts(b)
            if pa is not None and pb is not None:
                td = pb - pa
                d.append((td.days * 86_400_000_000 + td.seconds * 1_000_000 + td.microseconds) / 1e6)
                continue
        d.append(np.nan)
    if "ts" in p:
        p["delta_s"] = np.array(d, dtype=float)
    return p


# ====================================================================================================== errors
def _census_any(s):
    return bool(s) and any(rx.search(s) for rx in _CENSUS.values())


def error_classes(unit, tool_key_, tool_raw, text, stderr, native, exit_code, stratum=None):
    """Returns (primary: bool|None, cls: str). primary None = unit has no error definition for this result."""
    text = text if isinstance(text, str) else ""
    stderr = stderr if isinstance(stderr, str) else ""
    nat = None if native is None or (isinstance(native, float) and math.isnan(native)) or native is pd.NA else bool(native)
    if unit in CC_FORMAT_UNITS:
        m = error_marker(text)
        if nat is True:
            if m in ("cc_permission_denied", "cc_interrupt_reject"):
                return False, m
            return True, m or "unmarked"
        if unit == "aiv_cc" and (tool_raw or "").lower() == "mcp__village__bash":
            try:
                x = json.loads(text)
            except ValueError:
                x = None
            if isinstance(x, dict):
                err = x.get("error") or ""
                if isinstance(err, str) and (_C["aiv_bash_returncode_nonzero"].search(err) or _C["harness_timeout"].search(err)
                                             or _census_any(err)):
                    return False, "village_bash_proxy"
        return False, "ok"
    if unit == "swechat/codex":
        if nat is True:
            return True, "native"
        if nat is None and (tool_key_ in CODEX_SHELL_RAW):
            head = text[:600]
            for rx in (_C["codex_exit_header"], _C["codex_process_exited"]):
                m = rx.search(head)
                if m and int(m.group(1)) != 0:
                    return True, "exit_header"
        return False, "ok"
    if unit == "swechat/opencode":
        return (nat is True), ("native" if nat is True else "ok")
    if unit == "swechat/gemini":
        tf = nat is True
        cf = error_marker(text) == "gemini_exit_code_nonzero"
        cls = "tool_failure+command_failure" if (tf and cf) else "tool_failure" if tf else "command_failure" if cf else "ok"
        return (tf or cf), cls
    if unit == "swechat/copilot":
        return (nat is True), ("native" if nat is True else "ok")
    if unit == "aiv_cu":
        hit = bool(_C["aiv_bash_returncode_nonzero"].search(stderr) or _C["harness_timeout"].search(stderr)
                   or _census_any(stderr))
        return hit, ("proxy" if hit else "ok")
    if unit == "whowhen":
        if stratum == "Algorithm-Generated" and tool_key_ == "code_exec":
            if exit_code is not None and not (isinstance(exit_code, float) and math.isnan(exit_code)) and exit_code is not pd.NA:
                return int(exit_code) != 0, ("exit_nonzero" if int(exit_code) != 0 else "ok")
            return False, "no_exit_code"
        return None, "no_signal"
    return None, "no_definition"


# ====================================================================================================== text utils
def mask_redaction(s):
    if not s or "REDACTED" not in s:
        return s
    s = _C["redaction_typed"].sub("<R>", s)
    return s.replace("REDACTED", "<R>")


def norm_text(s):
    """Antecedent normalisation for Probe 2 matching."""
    if not s:
        return ""
    return mask_redaction(s).replace("\\", "/")


def args_strings(args):
    """All string values (and integer/float values as strings) of a parsed args JSON, depth-first; raw if unparseable."""
    if not isinstance(args, str):
        return [], []
    try:
        x = json.loads(args)
    except ValueError:
        return [args], []
    strs, nums = [], []

    def walk(o):
        if isinstance(o, str):
            strs.append(o)
        elif isinstance(o, bool) or o is None:
            return
        elif isinstance(o, (int, float)):
            nums.append(str(o) if isinstance(o, int) else repr(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(x)
    return strs, nums


# ====================================================================================================== paths (Probe 2)
_TRAIL = ".,;:)]}>'\"`"


def normalize_path(p):
    if not p:
        return None
    p = p.strip().strip("'\"`")
    while p and p[-1] in _TRAIL:
        p = p[:-1]
    p = _C["path_line_suffix"].sub("", p)
    p = mask_redaction(p).replace("\\", "/")
    p = re.sub(r"/{2,}", "/", p)
    while p.startswith("./"):
        p = p[2:]
    p = p.rstrip("/")
    if re.match(r"^[A-Za-z]:/", p):
        p = p.lower()
    return p or None


def path_components(p):
    return [c for c in p.split("/") if c not in ("", ".")]


def is_absolute(p):
    return p.startswith("/") or p.startswith("~") or bool(re.match(r"^[a-z]:/", p))


def path_key(p):
    comps = path_components(p)
    if not comps:
        return None
    if re.match(r"^[a-z]:$", comps[0]) and len(comps) == 1:
        return None
    return "/".join(comps[-2:]) if len(comps) >= 2 else comps[-1]


def free_paths(text):
    """Regex paths from free text, after URL masking, with the pre-registered filter."""
    if not text:
        return []
    t = _C["url"].sub(" ", text)
    out = []
    spans = []
    for name in ("path_windows", "path_abs_posix", "path_relative"):
        for m in _C[name].finditer(t):
            if any(a <= m.start() < b for a, b in spans):
                continue
            spans.append((m.start(), m.end()))
            raw = m.group(0)
            p = normalize_path(raw)
            if not p:
                continue
            comps = path_components(p)
            if not comps or not re.search(r"[A-Za-z]", p) or all(c.isdigit() for c in comps):
                continue
            last = comps[-1]
            has_ext = bool(_C["path_ext"].search(last)) and (last.rsplit(".", 1)[0] != "" or len(last) >= 2)
            absolute = name != "path_relative" and (p.startswith("/") or p.startswith("~") or re.match(r"^[a-z]:/", p))
            if has_ext or (absolute and len([c for c in comps if c not in ("~", "..")]) >= 2):
                out.append(p)
    return out


def structured_paths(args_obj, tool_raw):
    """(paths, access_kind) from structured keys and apply_patch headers. access_kind per path: 'read', 'edit',
    'create' or None."""
    out = []
    if not isinstance(args_obj, dict):
        return out
    for k in PATH_KEYS:
        v = args_obj.get(k)
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if isinstance(x, str) and x.strip():
                p = normalize_path(x)
                if p:
                    out.append((p, k))
    for key in ("input", "patchText"):
        v = args_obj.get(key)
        if isinstance(v, str) and "*** " in v:
            for m in _C["patch_file"].finditer(v):
                p = normalize_path(m.group(2))
                if p:
                    out.append((p, "patch_" + m.group(1).lower()))
            for m in _C["patch_move"].finditer(v):
                p = normalize_path(m.group(1))
                if p:
                    out.append((p, "patch_add"))
    return out


def shell_command(unit, tool_key_, args_obj, command):
    if isinstance(command, str) and command:
        return command
    if isinstance(args_obj, dict):
        for k in ("command", "cmd"):
            v = args_obj.get(k)
            if isinstance(v, str):
                return v
            if isinstance(v, list):
                return " ".join(str(x) for x in v)
    return None


def patch_ref_lines(patch):
    """'-' and ' ' lines inside Update File sections of an apply_patch text."""
    out, upd = [], False
    for line in patch.splitlines():
        if line.startswith("*** "):
            upd = line.startswith("*** Update File:")
            continue
        if upd and line and line[0] in "- " and not line.startswith("---"):
            out.append(line[1:])
    return "\n".join(out)


def symbol_ref_text(args_obj):
    if not isinstance(args_obj, dict):
        return ""
    parts = []
    for k in REF_CONTENT_KEYS:
        v = args_obj.get(k)
        if isinstance(v, str):
            parts.append(v)
    ed = args_obj.get("edits")
    if isinstance(ed, list):
        for e in ed:
            if isinstance(e, dict) and isinstance(e.get("old_string"), str):
                parts.append(e["old_string"])
    for key in ("input", "patchText"):
        v = args_obj.get(key)
        if isinstance(v, str) and "*** Update File:" in v:
            parts.append(patch_ref_lines(v))
    return "\n".join(parts)


def symbols(text):
    if not text:
        return []
    out = []
    for name in ("sym_snake", "sym_camel", "sym_pascal"):
        out += [m.group(0) for m in _C[name].finditer(text) if len(m.group(0)) >= 5]
    return out


def env_vars(text):
    return [m.group(0) for m in _C["env_var"].finditer(text or "") if len(m.group(0)) >= 5]


def cfg_keys(ref_text, target_paths, command):
    out = []
    if ref_text and any(p.rsplit(".", 1)[-1].lower() in CONFIG_EXT or p.rsplit("/", 1)[-1] == ".env"
                        for p in target_paths):
        out += [m.group(1) for m in _C["cfg_key_line"].finditer(ref_text)]
    if command:
        out += [m.group(1) for m in _C["git_config_key"].finditer(command)]
    return out


def workspace_root(abs_paths):
    """Pre-registered root rule. abs_paths: normalized absolute structured access paths of a session's main thread."""
    comps = [path_components(p) for p in abs_paths]
    comps = [c for c in comps if c]
    if len(comps) >= 2:
        pref = []
        for parts in zip(*comps):
            if all(x == parts[0] for x in parts):
                pref.append(parts[0])
            else:
                break
        if len(pref) >= 2:
            if any(len(c) == len(pref) for c in comps):  # the prefix is itself a full path: drop its last component
                pref = pref[:-1]
            if len(pref) >= 2:
                return tuple(pref)
    if comps:
        c3 = Counter(tuple(c[:3]) for c in comps if len(c) > 3)
        if c3:
            return max(c3.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return None


def path_depth(p, root):
    comps = path_components(p)
    if not is_absolute(p):
        return len([c for c in comps if c != ".."])
    if root is None:
        return None
    if tuple(comps[:len(root)]) == tuple(root):
        return len(comps) - len(root)
    return None


# ====================================================================================================== hex (Probe 4)
def hex_tokens(text, drop_redacted=True):
    """Returns (tokens, n_uuid, n_dropped_redaction). tokens lowercased, filtered per SPEC.probe4.hex.token."""
    if not text:
        return [], 0, 0
    n_uuid = len(_C["uuid"].findall(text))
    t = _C["uuid"].sub(" ", text) if n_uuid else text
    dropped = 0
    if drop_redacted and "REDACTED" in t:
        before = len(_valid_hex(_C["hex_token"].findall(t)))
        t = _C["redaction_run"].sub(" ", t)
        after_tokens = _valid_hex(_C["hex_token"].findall(t))
        dropped = max(0, before - len(after_tokens))
        return after_tokens, n_uuid, dropped
    return _valid_hex(_C["hex_token"].findall(t)), n_uuid, dropped


def _valid_hex(raw):
    out = []
    for tok in raw:
        if len(tok) not in HEX_LENGTHS:
            continue
        low = tok.lower()
        if not re.search(r"[0-9]", low) or not re.search(r"[a-f]", low) or low in CONSTANT_HEX:
            continue
        out.append(low)
    return out


def git_hashes(text):
    out = []
    if not text:
        return out
    for rx in _GIT_LINES:
        for m in rx.finditer(text):
            for g in m.groups():
                if g:
                    out.append(g)
    return _valid_hex(out)


HEX_SYMBOLS = "0123456789abcdef"


def p_digit(L):
    """Per-digit-symbol probability for a length-L token under uniform hex conditioned on 1 <= #digits <= L-1."""
    q = 10 / 16
    num, den = 0.0, 0.0
    for k in range(1, L):
        w = math.comb(L, k) * q ** k * (1 - q) ** (L - k)
        num += k * w
        den += w
    return (num / den) / (10 * L)


_PD = {L: p_digit(L) for L in HEX_LENGTHS}


def hex_counts(tokens):
    """(observed 16-vector, expected 16-vector) for a list of distinct tokens."""
    obs = np.zeros(16)
    exp = np.zeros(16)
    for t in tokens:
        for ch in t:
            obs[HEX_SYMBOLS.index(ch)] += 1
        L = len(t)
        pd_ = _PD[L]
        pl = (1 - 10 * pd_) / 6
        exp[:10] += L * pd_
        exp[10:] += L * pl
    return obs, exp


def w_adj_from_counts(obs, exp):
    n = obs.sum()
    if n == 0:
        return None, None, None, 0
    from scipy.stats import chisquare
    r = chisquare(obs, f_exp=exp * (n / exp.sum()))
    stat = float(r.statistic)
    return math.sqrt(max(0.0, (stat - 15) / n)), stat, float(r.pvalue), int(n)


def n_min_power(w=0.15, alpha=0.01, power=0.80, df=15):
    from scipy.stats import chi2, ncx2
    crit = chi2.ppf(1 - alpha, df)
    n = 16
    while ncx2.sf(crit, df, n * w * w) < power:
        n += 1
    return n


def large_ints(text):
    if not text:
        return []
    ep = {m.span() for m in _C["epoch_s"].finditer(text)} | {m.span() for m in _C["epoch_ms"].finditer(text)}
    return [m.group(0) for m in _C["large_int"].finditer(text) if m.span() not in ep]


# ====================================================================================================== retry (Probe 3)
def sim_tokens(s):
    return set(t.lower() for t in _C["sim_token"].findall(s or ""))


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


# ====================================================================================================== change point
def change_point(x, m=20, n_perm=199, seed=stats.SEED):
    """Single change point in the 10th percentile of x (log10 deltas). Returns dict or None if ineligible."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2 * m:
        return None

    step = max(1, n // 100)  # candidate grid: every step-th split point (<= ~100 candidates)
    ks = list(range(m, n - m + 1, step))

    def dstar(v):
        best, bk = -1.0, None
        for k in ks:
            d = abs(np.quantile(v[:k], 0.10) - np.quantile(v[k:], 0.10))
            if d > best + 1e-15:
                best, bk = d, k
        return best, bk

    d0, k0 = dstar(x)
    rng = np.random.default_rng(seed)
    ge = sum(1 for _ in range(n_perm) if dstar(rng.permutation(x))[0] >= d0 - 1e-15)
    p = (1 + ge) / (n_perm + 1)
    left, right = np.quantile(x[:k0], 0.10), np.quantile(x[k0:], 0.10)
    return {"n": n, "k": int(k0), "D": float(d0), "p": float(p), "step": bool(p <= 0.01 and d0 >= math.log10(2)),
            "direction": "up" if right > left else "down"}
