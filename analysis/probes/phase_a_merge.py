"""Phase A merge: one file with every Phase A number, each question's verification status, the synthesizer's
resolutions of verifier discrepancies, and the mechanical application of each pre-registered gate rule.

Run from the worktree root (after analysis.probes.phase_a_resolve):
    PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_merge
Reads   analysis/out/phase_a/{a1..a6, a6_raw_census, resolve}.json and analysis/out/phase_a/verification/*.json
Writes  analysis/out/phase_a.json

Layout of the output:
  meta          inputs (with sha256), conventions
  verification  per question: verifier status per corpus (reproduced flag + discrepancy text), kill-logic flag, overclaims
  gate_rules    pre-registered rules applied mechanically to the stored numbers (A1 kill rule, A2 join rule, A4 text-proxy
                rule, A5 conservation rule); categorical outputs of rules, no new judgement
  headline      the numbers PHASE_A.md cites, each with its source file and JSON path (resolved here, so a wrong path fails)
  resolutions   one entry per verifier discrepancy: the measurer's and the verifier's claim, the synthesizer's check
                (values resolved from resolve.json / the measurer's JSON) and which number stands
  sources       the measurer JSON files and resolve.json, verbatim
Interpretation lives in analysis/PHASE_A.md. The 'decision' strings in resolutions state which number is right and why,
with numbers; they are the only prose in this file besides the verifier texts.
"""
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PA = os.path.join(ROOT, "analysis", "out", "phase_a")
OUT = os.path.join(ROOT, "analysis", "out", "phase_a.json")
SRC_FILES = {k: os.path.join(PA, f"{k}.json") for k in ("a1", "a2", "a3", "a4", "a5", "a6", "a6_raw_census", "resolve")}
VER_FILES = {k: os.path.join(PA, "verification", f"verify_{k}.json") for k in ("a1", "a2", "a3", "a4", "a5", "a6",
                                                                                "a6_raw_census")}


class Ref:
    def __init__(self, src, *path):
        self.src, self.path = src, path


def R(src, *path):
    return Ref(src, *path)


def get(S, ref):
    o = S[ref.src]
    for k in ref.path:
        try:
            o = o[k]
        except (KeyError, IndexError, TypeError) as e:
            raise KeyError(f"path {ref.src}:{'/'.join(map(str, ref.path))} fails at {k!r}") from e
    return o


def resolve_refs(S, o):
    if isinstance(o, Ref):
        return {"source": o.src, "path": list(o.path), "value": get(S, o)}
    if isinstance(o, dict):
        return {k: resolve_refs(S, v) for k, v in o.items()}
    if isinstance(o, list):
        return [resolve_refs(S, v) for v in o]
    return o


SW = "swechat/format="
HW = ("claude_code_human_wait",)

# ------------------------------------------------------------------------------------------------------------ headline
HEADLINE = {
    # A1
    "A1.verdict.swechat_claude_code": R("a1", "verdicts", SW + "claude_code"),
    "A1.verdict.swechat_codex": R("a1", "verdicts", SW + "codex"),
    "A1.verdict.swechat_opencode": R("a1", "verdicts", SW + "opencode"),
    "A1.verdict.swechat_gemini": R("a1", "verdicts", SW + "gemini"),
    "A1.verdict.swechat_copilot": R("a1", "verdicts", SW + "copilot"),
    "A1.verdict.swechat_cursor": R("a1", "verdicts", SW + "cursor"),
    "A1.verdict.swechat_simple_text": R("a1", "verdicts", SW + "simple_text"),
    "A1.verdict.cc_local": R("a1", "verdicts", "cc_local"),
    "A1.verdict.aiv_cc": R("a1", "verdicts", "aiv_cc"),
    "A1.verdict.aiv_cu": R("a1", "verdicts", "aiv_cu"),
    "A1.verdict.whowhen": R("a1", "verdicts", "whowhen"),
    "A1.delta_p50.swechat_claude_code": R("a1", "groups", SW + "claude_code", "format", "delta_s", "p50"),
    "A1.delta_p50.cc_local": R("a1", "groups", "cc_local", "corpus", "delta_s", "p50"),
    "A1.delta.aiv_cc": R("a1", "groups", "aiv_cc", "corpus", "delta_s"),
    "A1.gemini_negative_deltas": R("a1", "groups", SW + "gemini", "format", "delta_negative"),
    "A1.aiv_cc_min_inter_row_gap_s": R("a1", "aiv_cc_insert_time", "consecutive_rows", "gap_s", "min"),
    "A1.aiv_cc_permission_mode": R("a1", "aiv_cc_insert_time", "init_permissionMode_counts"),
    "A1.swechat_cc_edit_write_gt_2s": R("a1", *HW, "swechat_claude_code", "latency_by_class/all", "file_write", "share_gt_2s"),
    "A1.cc_local_edit_write_gt_2s": R("a1", *HW, "cc_local", "latency_by_class/all", "file_write", "share_gt_2s"),
    "A1.aiv_cu_inter_turn_gap_s": R("a1", "aiv_cu_shared_turn", "inter_turn_gap_s"),
    "A1r.swechat_cc_rejections": R("resolve", "A1", "swechat_cc_interrupt_reject"),
    "A1r.marker_latency_by_corpus": R("resolve", "A1", "marker_latency_by_corpus"),
    "A1r.bash_progress_offset": R("resolve", "A1", "swechat_cc_bash_progress_offset"),
    "A1r.aiv_cc_not_last_block_write": R("resolve", "A1", "aiv_cc_not_last_block", "by_tool", "write"),
    # A2
    "A2.calls_without_result.swechat_claude_code": R("a2", "swechat_by_format", "claude_code", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.swechat_codex": R("a2", "swechat_by_format", "codex", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.swechat_opencode": R("a2", "swechat_by_format", "opencode", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.swechat_gemini": R("a2", "swechat_by_format", "gemini", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.swechat_copilot": R("a2", "swechat_by_format", "copilot", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.swechat_cursor": R("a2", "swechat_by_format", "cursor", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.swechat_excl_structural": R("a2", "by_corpus", "swechat", "all", "rates", "calls_without_result_excl_structural"),
    "A2.calls_without_result.cc_local": R("a2", "by_corpus", "cc_local", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.aiv_cc": R("a2", "by_corpus", "aiv_cc", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.aiv_cu": R("a2", "by_corpus", "aiv_cu", "all", "rates", "calls_without_result"),
    "A2.calls_without_result.whowhen": R("a2", "by_corpus", "whowhen", "all", "rates", "calls_without_result"),
    "A2.whowhen_AG": R("a2", "by_stratum", "whowhen", "Algorithm-Generated", "rates", "calls_without_result"),
    "A2.orphans.swechat_claude_code": R("a2", "swechat_by_format", "claude_code", "all", "rates", "orphan_results"),
    "A2.aiv_cu_results_text_null_or_empty": R("a2", "by_corpus", "aiv_cu", "results_text_null_or_empty"),
    "A2.table_orphan_share": R("a2", "derived_from_cited", "table_orphan_share_of_distinct_results"),
    "A2.raw_results_without_call_share": R("a2", "derived_from_cited", "raw_full_pass_results_without_call_share"),
    "A2r.salvaged_opencode_session": R("resolve", "A2", "salvaged_opencode_session"),
    "A2r.verdict_per_call_wilson": R("resolve", "A2", "verdict_rule_with_per_call_wilson"),
    # A3
    "A3.swechat_cap_exact": R("a3", "corpora", "swechat", "groups", "_all", "all", "window_10kb", "swechat_dataset_cap_exact"),
    "A3.table_cap_rows_recon": R("a3", "context_from_recon", "result_truncated_10256"),
    "A3.raw_results_over_10256_chars": R("a3", "corpora", "swechat", "groups", "_all", "all", "lengths", "n_chars_over_10256"),
    "A3.any_truncation.swechat_claude_code": R("a3", "corpora", "swechat", "groups", "claude_code", "all", "truncation", "any_truncation"),
    "A3.any_truncation.swechat_codex": R("a3", "corpora", "swechat", "groups", "codex", "all", "truncation", "any_truncation"),
    "A3.any_truncation.swechat_gemini": R("a3", "corpora", "swechat", "groups", "gemini", "all", "truncation", "any_truncation"),
    "A3.any_truncation.swechat_opencode": R("a3", "corpora", "swechat", "groups", "opencode", "all", "truncation", "any_truncation"),
    "A3.any_truncation.cc_local": R("a3", "corpora", "cc_local", "groups", "cc_local", "all", "truncation", "any_truncation"),
    "A3.any_truncation.aiv_cc": R("a3", "corpora", "aiv_cc", "groups", "aiv_cc", "all", "truncation", "any_truncation"),
    "A3.any_truncation.aiv_cu": R("a3", "corpora", "aiv_cu", "groups", "aiv_cu", "all", "truncation", "any_truncation"),
    "A3.any_truncation.whowhen": R("a3", "corpora", "whowhen", "groups", "whowhen", "all", "truncation", "any_truncation"),
    "A3.cc_chars_truncated.swechat": R("a3", "corpora", "swechat", "groups", "claude_code", "all", "truncation", "markers", "cc_chars_truncated"),
    "A3.cc_persisted_output.swechat": R("a3", "corpora", "swechat", "groups", "claude_code", "all", "truncation", "markers", "cc_persisted_output"),
    "A3.cc_local_glob_flag": R("a3", "corpora", "cc_local", "structured_flags", "extra_truncated_flag", "groups", 0),
    "A3r.gemini_masking": R("resolve", "A3", "swechat_gemini_masking"),
    "A3r.swechat_cc_exit_line_baseline": R("resolve", "A3", "swechat_cc_exit_line_baseline"),
    "A3r.aiv_cc_exit_line_baseline": R("resolve", "A3", "aiv_cc_cc_exit_line_baseline"),
    "A3r.swechat_glob_flag_vs_text": R("resolve", "A3", "swechat_cc_glob_flag_vs_text"),
    "A3r.old_spill_aiv_cc": R("resolve", "A3", "old_spill_by_corpus", "aiv_cc"),
    "A3r.old_spill_cc_local": R("resolve", "A3", "old_spill_by_corpus", "cc_local"),
    "A3r.cc_local_truncation_union": R("resolve", "A3", "cc_local_truncation_union"),
    "A3r.cc_local_glob_shape": R("resolve", "A3", "cc_local_glob_shape_vs_flag"),
    # A4
    "A4.native_fill.swechat_claude_code": R("a4", "units", "swechat/claude_code", "all", "native_fill"),
    "A4.native_fill.cc_local": R("a4", "units", "cc_local", "all", "native_fill"),
    "A4.native_fill.aiv_cc": R("a4", "units", "aiv_cc", "all", "native_fill"),
    "A4.native_fill.swechat_opencode": R("a4", "units", "swechat/opencode", "all", "native_fill"),
    "A4.native_fill.swechat_gemini": R("a4", "units", "swechat/gemini", "all", "native_fill"),
    "A4.native_fill.swechat_codex": R("a4", "units", "swechat/codex", "all", "native_fill"),
    "A4.A.swechat_claude_code": R("a4", "units", "swechat/claude_code", "all", "pr", "native_null_neg", "predictors", "A"),
    "A4.A.cc_local": R("a4", "units", "cc_local", "all", "pr", "native_null_neg", "predictors", "A"),
    "A4.A.aiv_cc": R("a4", "units", "aiv_cc", "all", "pr", "native_null_neg", "predictors", "A"),
    "A4.B.aiv_cc": R("a4", "units", "aiv_cc", "all", "pr", "native_null_neg", "predictors", "B"),
    "A4.C.swechat_codex": R("a4", "units", "swechat/codex", "all", "pr", "native_strict", "predictors", "C"),
    "A4.B.swechat_opencode_shell": R("a4", "units", "swechat/opencode", "shell", "pr", "native_strict", "predictors", "B"),
    "A4.A.swechat_gemini": R("a4", "units", "swechat/gemini", "all", "pr", "native_strict", "predictors", "A"),
    "A4.A.whowhen": R("a4", "units", "whowhen", "all", "pr", "native_strict", "predictors", "A"),
    "A4.cc_local_shell_native_true_markers": R("a4", "units", "cc_local", "shell", "error_marker_by_native", "true"),
    "A4.aiv_cc_village_bash_json_by_native": R("a4", "aiv_cc_village_bash_json", "json_by_native"),
    "A4.aiv_cu_stderr_proxy": R("a4", "aiv_cu", "by_class", "all", "stderr_fail_template"),
    "A4r.codex_shell": R("resolve", "A4", "codex_shell"),
    "A4r.aiv_cc_sdk_sessions": R("resolve", "A4", "aiv_cc_results_by_sdk_session"),
    # A5
    "A5.gemini_cli_tokens_tool": R("a5", "part1", "raw_A_checks", "swechat_gemini_tokens_A", "counts"),
    "A5.gemini_pro_image_rise_gui": R("a5", "part2", "aiv_cu/gemini-pro", "gemini_modality", "gap_has_gui_result", "share_d_image_gt0"),
    "A5.gemini_pro_image_rise_no_gui": R("a5", "part2", "aiv_cu/gemini-pro", "gemini_modality", "gap_has_no_gui_result", "share_d_image_gt0"),
    "A5.gemini_flash_image_rise_gui": R("a5", "part2", "aiv_cu/gemini-flash", "gemini_modality", "gap_has_gui_result", "share_d_image_gt0"),
    "A5.aiv_cc_tokens_per_image": R("a5", "part2", "aiv_cc", "image", "resid_per_image_tokens", "median"),
    "A5r.random_splits": R("resolve", "A5"),
    # A6
    "A6.census_crossref_by_status": R("a6", "part1_census_crossref", "summary_with_pass1_extra", "by_status"),
    "A6.census_crossref_n_entries": R("a6", "part1_census_crossref", "summary_with_pass1_extra", "n_entries"),
    "A6.census_uncaptured_now_captured": R("a6", "part1_census_crossref", "summary", "census_uncaptured_now_captured_total"),
    "A6.candidates_totals": R("a6", "part1_candidates", "totals"),
    "A6.parser_surprises": R("a6", "part2_summary", "by_status"),
    "A6r.value_fill": R("resolve", "A6", "harness_measured_fill_ge_0.3_value_fill", "by_value_fill"),
    "A6r.stop_fields": R("resolve", "A6", "stop_fields_census_types"),
    "A6r.read_rows": R("resolve", "A6", "swechat_cc_read_results"),
    "A6r.marker_value": R("resolve", "A6", "swechat_result_extra_marker"),
    "A6r.parent_uuid_link": R("resolve", "A6", "swechat_cc_result_parent_uuid_link"),
}

for g in ("aiv_cc", "swechat/claude_code", "swechat/opencode", "swechat/gemini", "swechat/codex", "cc_local",
          "aiv_cu/anthropic_all", "aiv_cu/gemini-pro", "aiv_cu/gemini-flash", "aiv_cu/anthropic-haiku"):
    HEADLINE[f"A5.{g}.fit_set"] = R("a5", "part2", g, "fit_set")
    HEADLINE[f"A5.{g}.spearman"] = R("a5", "part2", g, "non_image_growth", "corr", "spearman")
    HEADLINE[f"A5.{g}.cross_fit_median_abs_resid"] = R("a5", "part2", g, "non_image_growth", "cross_fit", "resid", "median_abs")
    HEADLINE[f"A5.{g}.typical_result_tokens"] = R("a5", "part2", g, "typical_result", "median_result_tokens")
    HEADLINE[f"A5.{g}.ratio"] = R("a5", "part2", g, "typical_result", "cross_fit_median_abs_resid_over_median_result_tokens")
for g in ("swechat/opencode", "swechat/gemini", "swechat/codex"):
    HEADLINE[f"A5.{g}.result_only.spearman"] = R("a5", "part2", g, "result_only_variant", "corr", "spearman")
    HEADLINE[f"A5.{g}.result_only.resid"] = R("a5", "part2", g, "result_only_variant", "cross_fit", "resid", "median_abs")
    HEADLINE[f"A5.{g}.result_only.ratio"] = R("a5", "part2", g, "result_only_variant",
                                               "cross_fit_median_abs_resid_over_median_result_tokens")

# --------------------------------------------------------------------------------------------------------- resolutions
RESOLUTIONS = [
    # ---------------------------------------------------------------- A1
    {"id": "A1-1", "question": "A1", "unit": "swechat/claude_code", "affects_gate": False,
     "dispute": "share of sessions with a human answering a permission prompt",
     "measurer": "34/126 sessions (27.0% [20.0, 35.3]) contain a 'user doesn't want to proceed' rejection; 'a direct "
                 "measure of a human answering a permission prompt'",
     "verifier": "41 results in 20/126 sessions = 15.9% [10.5, 23.2] on permission-gated tools",
     "check": R("resolve", "A1", "swechat_cc_interrupt_reject"),
     "decision": "34/126 is the right count of sessions with any cc_interrupt_reject result (59 results), but 15 of the 59 "
                 "are ExitPlanMode and 3 AskUserQuestion (tools that wait for the human by design) and 1 is a "
                 "'[Request interrupted' interrupt. Permission-prompt rejections are 40 results in 19/126 sessions = "
                 "15.1% [9.9, 22.4], p50 latency 23.0 s (synthesizer definition, DEFS A1.permission_gated_rejection). The "
                 "verifier's 41/20 counts the interrupt as well. Use 19/126 for 'human answered a permission prompt'."},
    {"id": "A1-2", "question": "A1", "unit": "swechat/claude_code, cc_local", "affects_gate": False,
     "dispute": "whether the same marker means machine denial in cc_local and human interaction in swechat",
     "measurer": "'The same marker means machine denial in cc_local and human interaction in swechat'; notes: human-wait "
                 "evidence absent in cc_local",
     "verifier": "the two markers differ; cc_permission_denied is fast in both corpora, cc_interrupt_reject human-paced in both",
     "check": R("resolve", "A1", "marker_latency_by_corpus"),
     "decision": "Verifier is right. cc_permission_denied: swechat 3 results, p50 0.022 s (max 0.037); cc_local 173 results "
                 "in 67/107 sessions, p50 0.007 s (max 0.037). cc_interrupt_reject: swechat 59 results, p50 23.4 s; "
                 "cc_local 9 results in 6/107 sessions = 5.6% [2.6, 11.7], p50 4.9 s (min 0.458), 6 on shell. Corpora "
                 "differ in frequency, not in marker meaning; cc_local has some human-paced waits. Only 'no slow edits in "
                 "cc_local' (0/358 Edit/Write > 2 s) holds."},
    {"id": "A1-3", "question": "A1", "unit": "swechat/claude_code", "affects_gate": False,
     "dispute": "share of long shell commands that start > 2 s after the call (bash_progress offset)",
     "measurer": "56/373 = 15.0% [7.2, 26.9]", "verifier": "6 of the 373 are Task calls; shell only 50/367 = 13.6% [5.8, 25.9]",
     "check": R("resolve", "A1", "swechat_cc_bash_progress_offset"),
     "decision": "Verifier is right: 367 shell + 6 subagent calls; all 6 subagent offsets exceed 2 s (p50 68.9 s, which is "
                 "subagent run time). Shell only: 50/367 = 13.6% [5.8, 25.9] over 51 sessions."},
    {"id": "A1-4", "question": "A1", "unit": "swechat/claude_code", "affects_gate": False,
     "dispute": "nature of the maximum delta", "measurer": "max 78,675.7 s is 'a subagent call'; heavy tails are 'real waits'",
     "verifier": "main-thread Task call (is_subagent False)", "check": R("resolve", "A1", "swechat_cc_max_delta"),
     "decision": "Verifier is right: delta 78,675.683 s, tool 'subagent' (Task), is_subagent False. 'Real waits' is not "
                 "measured."},
    {"id": "A1-5", "question": "A1", "unit": "aiv_cc", "affects_gate": False,
     "dispute": "do non-last tool_use blocks absorb later-block generation time (SDK does not stream)?",
     "measurer": "Write p50 15.5 s for non-last blocks vs 0.089 s; tool execution does not stream in this SDK version",
     "verifier": "one-session Write effect; most tools' non-last results arrive before the last block",
     "check": R("resolve", "A1", "aiv_cc_not_last_block"),
     "decision": "Verifier is right. Non-last Write: 160 calls, all in 1 session (160/160), p50 15.65 s, 0/160 results "
                 "before the last block's stamp. Other tools: grep 41/41, read 45/68, get_events 502/993, chat_message "
                 "187/294, shell 549/1,570 non-last results stamped before the last block; non-last Read p50 0.111 s vs "
                 "last-block 0.314 s. Keep the 'last or only block' filter as a cheap precaution, not as an SDK property."},
    {"id": "A1-6", "question": "A1", "unit": "aiv_cc", "affects_gate": False,
     "dispute": "the ~50 ms floor", "measurer": "'ingestion floor'; insert time tracks event time",
     "verifier": "inserts can be 18.2 ms apart while call-to-result is never under 46 ms; cause unidentified; event "
                 "tracking shown only at run level",
     "check": {"min_inter_row_gap_s": R("a1", "aiv_cc_insert_time", "consecutive_rows", "gap_s", "min"),
               "call_to_result_min_s": R("a1", "aiv_cc_insert_time", "consecutive_rows", "by_kind_transition", "call->result", "gap_s", "min"),
               "sdk_duration_vs_run_span": R("a1", "aiv_cc_insert_time", "sdk_result_duration_vs_run_span", "span_minus_duration_s")},
     "decision": "Both numbers stand (min row gap 0.018192 s; min call->result 0.046118 s). The ~46-50 ms floor is "
                 "measured; its attribution to ingestion is not. Per-event insert lag is unmeasured."},
    {"id": "A1-7", "question": "A1", "unit": "swechat/opencode", "affects_gate": False,
     "dispute": "last-digit uniformity", "measurer": "notes call the last digit uniform (swechat pooled p 0.20)",
     "verifier": "OpenCode alone p 0.039", "check": R("resolve", "A1", "opencode_last_digit_distinct_stamps"),
     "decision": "Verifier is right: chi2 p 0.039 on 8,298 distinct OpenCode stamps (digit 5: 919 vs mean 829.8). The kill "
                 "rule does not use digit uniformity; verdict unchanged."},
    # ---------------------------------------------------------------- A2
    {"id": "A2-1", "question": "A2", "unit": "swechat", "affects_gate": False, "dispute": "structural unpaired calls",
     "measurer": "summary text: 694 structural", "verifier": "695", "check": R("resolve", "A2", "swechat_structural_unpaired"),
     "decision": "695 (206 + 488 + 1) is right; the JSON was right, the summary text slipped. 727 - 695 = 32."},
    {"id": "A2-2", "question": "A2", "unit": "swechat/copilot", "affects_gate": True,
     "dispute": "copilot 'usable'", "measurer": "usable (cluster-bootstrap hi 0.0082 <= 0.01)",
     "verifier": "2-cluster bootstrap is degenerate; per-call Wilson hi 0.021",
     "check": R("resolve", "A2", "verdict_rule_with_per_call_wilson", "swechat/copilot"),
     "decision": "Verifier is right: per-call Wilson upper bound for 1/266 is 0.0210 > 0.01, so the rule gives 'partial'; "
                 "with 2 sessions the honest label is 'insufficient n'."},
    {"id": "A2-3", "question": "A2", "unit": "zero-count units", "affects_gate": False,
     "dispute": "zero-count 'usable' verdicts rest on a [0, 0] bootstrap",
     "measurer": "usable (bootstrap hi 0)", "verifier": "the rule's hi does not bound zero rates; session Wilson up to 0.133",
     "check": R("resolve", "A2", "verdict_rule_with_per_call_wilson"),
     "decision": "Re-applying the rule with per-call Wilson upper bounds changes only copilot (A2-2). OpenCode 0/3,735 "
                 "(Wilson hi 0.0010), aiv_cu 0/6,107 (0.0006), cc_local 1/5,165 (0.0011), aiv_cc 4/33,479 (0.0003), "
                 "codex 2/1,122 (0.0065), swechat CC 31/13,620 (0.0032) stay usable. The session Wilson bound (0.133 for "
                 "0/25) bounds the share of sessions affected, which the rule does not use."},
    {"id": "A2-4", "question": "A2", "unit": "swechat/opencode", "affects_gate": False,
     "dispute": "origin of the 162 conversations.parquet ids missing from the raw IR",
     "measurer": "all OpenCode REDACTED-id handling", "verifier": "one salvaged, truncated OpenCode session in split A",
     "check": R("resolve", "A2", "salvaged_opencode_session"),
     "decision": "Verifier is right. ses_3353a8139ffeLXvY9MIuOitgt6 (split A, the only document_parse_not_ok file, "
                 "salvaged) has 185 IR calls (126 raw ids + 59 synthetic) against 417 table tool_use rows (288 distinct "
                 "non-REDACTED ids + 129 REDACTED); 162 table ids are not in the raw IR and 0 raw ids are not in the "
                 "table, i.e. all 162. The crosscheck skips REDACTED ids by construction. Consequence: the raw IR can "
                 "lose calls in a truncated document, and A2's join metrics cannot see that loss."},
    {"id": "A2-5", "question": "A2", "unit": "aiv_cu", "affects_gate": False,
     "dispute": "aiv_cu 'usable'", "measurer": "usable (pairing built by the loader)",
     "verifier": "not testable: the loader emits call and result from the same row",
     "check": R("a2", "pairing_mechanism", "aiv_cu"),
     "decision": "Verifier is right about the label: 0/6,107 is true by construction, so join completeness is untestable "
                 "for aiv_cu, not 'usable'."},
    {"id": "A2-6", "question": "A2", "unit": "swechat (cited)", "affects_gate": False,
     "dispute": "sessions behind the 1,367 orphan-id check", "measurer": "50 sessions", "verifier": "48",
     "check": R("a2", "cited", "swechat_table_orphans_in_raw_check"),
     "decision": "48: 50 sampled, 2 without a transcript file."},
    # ---------------------------------------------------------------- A3
    {"id": "A3-1", "question": "A3", "unit": "swechat/gemini", "affects_gate": False,
     "dispute": "Gemini masked share", "measurer": "844/2,313 = 36.5% 'all <tool_output_masked>'; masked shell keeps Exit "
                                                  "Code 97/270",
     "verifier": "masked 840; 4 more are unmasked head/tail cuts; masked shell 97/266",
     "check": R("resolve", "A3", "swechat_gemini_masking"),
     "decision": "Verifier is right: <tool_output_masked> on 840/2,313 = 36.3% [25.2, 43.2] (7/10 sessions); 844 is the "
                 "union with the 10 'Showing first/last' cuts (6 of them also masked). Masked shell 266, of which 97 carry "
                 "an Exit Code line."},
    {"id": "A3-2", "question": "A3", "unit": "swechat/claude_code, aiv_cc", "affects_gate": False,
     "dispute": "exit-line retention baseline", "measurer": "15/15 vs baseline 282/285 (swechat) and 229/267 (aiv_cc)",
     "verifier": "baselines measure 'any error marker'; like-for-like 'Exit code N' is 233/285 and 200/267",
     "check": {"swechat": R("resolve", "A3", "swechat_cc_exit_line_baseline"), "aiv_cc": R("resolve", "A3", "aiv_cc_cc_exit_line_baseline")},
     "decision": "Verifier is right about the metric. Like-for-like 'Exit code N' at text start on untruncated native-true "
                 "shell results: swechat 233/285 = 0.818 [0.730, 0.884] (58 sessions); aiv_cc 200/267 = 0.749 [0.573, "
                 "0.858] (22 sessions). Truncated (char-elided) results keep it 15/15 (10 sessions) and 15/15 (2 "
                 "sessions). Retention holds and is guaranteed by the format (head kept); aiv_cc rests on 2 sessions."},
    {"id": "A3-3", "question": "A3", "unit": "swechat/gemini", "affects_gate": False,
     "dispute": "does masking remove the Exit Code line?", "measurer": "masked 97/270 vs unmasked 183/546: 'retained at "
                                                                     "baseline rate'",
     "verifier": "Gemini writes 'Exit Code:' only for nonzero exits; the comparison is of failure rates",
     "check": R("resolve", "A3", "swechat_gemini_masking"),
     "decision": "Verifier is right: 0 'Exit Code: 0' lines in 816 shell results. 97/266 masked vs 183/550 unmasked compares "
                 "failure-text rates; retention under masking is not measurable."},
    {"id": "A3-4", "question": "A3", "unit": "swechat/claude_code", "affects_gate": False,
     "dispute": "Glob structured flag vs text marker", "measurer": "flag agrees exactly with text (10/10, 0/158)",
     "verifier": "flag absent on 34 of 44 text-marked Glob truncations",
     "check": R("resolve", "A3", "swechat_cc_glob_flag_vs_text"),
     "decision": "Verifier is right: of 44 text-marked Glob truncations, flag True 10, flag absent 34. A flag-only gate "
                 "misses 34/44 in swechat."},
    {"id": "A3-5", "question": "A3", "unit": "aiv_cc, cc_local", "affects_gate": False,
     "dispute": "completeness of the marker catalogue", "measurer": "aiv_cc any truncation 35/33,475 (10/77); cc_local 22",
     "verifier": "older CC spill format missed: aiv_cc 5, cc_local 1",
     "check": {"aiv_cc": R("resolve", "A3", "old_spill_by_corpus", "aiv_cc"), "cc_local": R("resolve", "A3", "old_spill_by_corpus", "cc_local"),
               "cc_local_union": R("resolve", "A3", "cc_local_truncation_union")},
     "decision": "Verifier is right. Older-format spill ('Error: result (...) exceeds maximum allowed tokens. Output has been "
                 "saved to'): aiv_cc 5 results in 4 sessions (shell 4, search_history 1), cc_local 1 (MCP), swechat 0. "
                 "aiv_cc any truncation becomes 40/33,475 = 0.12% [0.04, 0.28], 11/77 sessions; cc_local text markers 23/5,164 "
                 "= 0.45% [0.19, 0.95]; cc_local markers + flag 209/5,164 = 4.05% [2.02, 10.03], 58/107."},
    {"id": "A3-6", "question": "A3", "unit": "cc_local", "affects_gate": False,
     "dispute": "is cc_local Glob truncation invisible in text?", "measurer": "text-only detection misses all 186",
     "verifier": "a text shape separates them perfectly", "check": R("resolve", "A3", "cc_local_glob_shape_vs_flag"),
     "decision": "Verifier is right: '101 lines, last line starts with (' holds on 186/186 flag-true and 0/241 flag-false "
                 "Glob results. The A3 catalogue misses them; text does not. (Shape rule is post hoc; A3's own JSON already "
                 "recorded flag_false last_line_starts_with_paren = 0.)"},
    {"id": "A3-7", "question": "A3", "unit": "aiv_cu, whowhen", "affects_gate": False,
     "dispute": "'results can be treated as complete'", "measurer": "no harness truncation, results complete",
     "verifier": "absence of markers does not establish completeness",
     "check": {"aiv_cu": R("a3", "corpora", "aiv_cu", "groups", "aiv_cu", "all", "truncation", "any_truncation"),
               "whowhen": R("a3", "corpora", "whowhen", "groups", "whowhen", "all", "truncation", "any_truncation")},
     "decision": "Verifier is right: 0/6,107 and 0/353 marked truncations; unmarked caps are not excluded (aiv_cu max "
                 "135,168 chars, n = 1, ends mid-line)."},
    # ---------------------------------------------------------------- A4
    {"id": "A4-1", "question": "A4", "unit": "all", "affects_gate": True,
     "dispute": "unit labels vs the pre-registered text-proxy rule",
     "measurer": "opencode usable, gemini partial, copilot partial, whowhen partial, codex usable",
     "verifier": "labels do not follow the rule; they grade native-flag availability",
     "check": R("resolve", "A4", "prereg_rule_labels"),
     "decision": "Rule labels for text proxies (best predictor, primary reference): swechat CC usable (A), cc_local usable "
                 "(A), aiv_cc usable (B; A partial), codex usable (C; B partial), opencode partial (B/C; shell absent), "
                 "gemini absent, copilot absent (min n not met), whowhen usable but tautological. The measurer's labels "
                 "answer a different question (is any Probe 3 error definition available, native or text). Both are "
                 "reported; the text-proxy label is the pre-registered one."},
    {"id": "A4-2", "question": "A4", "unit": "swechat/codex", "affects_gate": False,
     "dispute": "Codex recall 49/49", "measurer": "C: P 49/52, R 49/49",
     "verifier": "header alone gives R 47/49; 49/49 needs the 'sandbox error: command timed out' string",
     "check": R("resolve", "A4", "codex_shell"),
     "decision": "Verifier is right: nonzero exit header alone P 47/47, R 47/49 = 0.959 [0.823, 1.0] over 6 sessions; the 2 "
                 "missed positives are timeout texts. Header present on 822/842 shell results under A3's head-600 rule "
                 "(the verifier's 826 uses a wider search). The header alone still meets the 'usable' thresholds; "
                 "positives come from 6 sessions only."},
    {"id": "A4-3", "question": "A4", "unit": "aiv_cc", "affects_gate": False,
     "dispute": "independence of aiv_cc runs", "measurer": "CIs over 77 runs (38 with positives)",
     "verifier": "33,473/33,475 results share one sdk_session_id", "check": R("resolve", "A4", "aiv_cc_results_by_sdk_session"),
     "decision": "Verifier is right: 33,473 of 33,475 results (76 of 77 runs) belong to one SDK session of one agent. Every "
                 "aiv_cc CI treats resumed runs of one conversation as independent; effective n is one agent."},
    {"id": "A4-4", "question": "A4", "unit": "cc_local", "affects_gate": False,
     "dispute": "'every non-shell CC result is true or absent'", "measurer": "holds in all three CC corpora",
     "verifier": "9 non-shell cc_local results are False", "check": R("resolve", "A4", "cc_local_nonshell_native"),
     "decision": "Verifier is right: cc_local non-shell native_error True 38 / False 9 / null 1,805; all 9 False are "
                 "Workflow, in 2 sessions. The null-as-negative reading stays right for swechat CC and aiv_cc."},
    {"id": "A4-5", "question": "A4", "unit": "aiv_cc, cc_local", "affects_gate": False,
     "dispute": "'census regexes add no recall in any CC corpus'", "measurer": "no recall added, only false positives",
     "verifier": "false for aiv_cc", "check": {"aiv_cc_A": R("a4", "units", "aiv_cc", "all", "pr", "native_null_neg", "predictors", "A", "tp"),
                                                "aiv_cc_B": R("a4", "units", "aiv_cc", "all", "pr", "native_null_neg", "predictors", "B", "tp"),
                                                "cc_local_A": R("a4", "units", "cc_local", "all", "pr", "native_null_neg", "predictors", "A", "tp"),
                                                "cc_local_B": R("a4", "units", "cc_local", "all", "pr", "native_null_neg", "predictors", "B", "tp")},
     "decision": "Verifier is right: aiv_cc TP 296 -> 534 with B; cc_local 331 -> 332. The claim holds for swechat CC only."},
    # ---------------------------------------------------------------- A5
    {"id": "A5-1", "question": "A5", "unit": "all fitted groups", "affects_gate": False,
     "dispute": "single sha1 fold split vs fold variance",
     "measurer": "cross-fit residuals from one sha1 session split, CIs with the fit fixed",
     "verifier": "Gemini CLI 117.8 is below p5 of random splits; Codex 315.3 above p95",
     "check": R("resolve", "A5"),
     "decision": "Partly confirmed. Median |residual| over 50 random splits, p50 (p5-p95): aiv_cc 63.8 (55.3-69.1), swechat "
                 "CC 124.8 (113.9-133.7), OpenCode 96.2 (84.5-108.4), Gemini CLI 147.2 (114.0-218.9; 45 of 49 splits give more "
                 "than the sha1 value 117.8), Codex 251.5 (218.1-292.6; sha1 315.3 above all 50), cc_local 609.3 "
                 "(568.0-690.9). Applying the pre-registered rule at the random-split median changes no verdict: TIGHT "
                 "aiv_cc (ratio 0.044), LOOSE swechat CC (0.740), OpenCode (0.506), Gemini CLI (0.646; p95 0.961), "
                 "NOT_TIGHT Codex (1.84), cc_local (1.70). Report Gemini CLI at 147.2, not 117.8."},
    {"id": "A5-2", "question": "A5", "unit": "swechat/codex", "affects_gate": False,
     "dispute": "Codex conservation with reasoning tokens subtracted",
     "measurer": "NOT_TIGHT (residual 2.3x a typical result); full usage_out form not pre-registered",
     "verifier": "subtracting full usage_out gives a 45-token residual (~0.33 of a result, Spearman 0.974), 'close to TIGHT'",
     "check": R("resolve", "A5", "swechat/codex", "full_usage_out_variant_POST_HOC"),
     "decision": "Post hoc, reproduced: Spearman 0.974 [0.936, 0.994], residual 45.1 (random splits 49.7, 34.3-85.8), ratio "
                 "0.334 [0.139, 0.658] of a typical result. Under the rule's thresholds that is LOOSE, not TIGHT (0.334 > "
                 "0.25). The Phase A verdict stays NOT_TIGHT (pre-registered form); Phase B must pre-register the "
                 "full-usage_out form before using Codex."},
    {"id": "A5-3", "question": "A5", "unit": "aiv_cc", "affects_gate": False,
     "dispute": "scope of the aiv_cc TIGHT result", "measurer": "TIGHT over 73 sessions",
     "verifier": "all fit pairs come from one sdk_session_id", "check": R("resolve", "A5", "aiv_cc", "fit_pairs_by_sdk_session"),
     "decision": "Verifier is right: 27,491/27,491 fit pairs come from 1 SDK session (one Opus 4.5 agent). TIGHT stands "
                 "for that agent and harness; the 73-run CIs overstate generality."},
    {"id": "A5-4", "question": "A5", "unit": "swechat/claude_code", "affects_gate": False,
     "dispute": "LOOSE margin", "measurer": "ratio 0.742 [0.591, 1.0]", "verifier": "CI upper bound is 0.9996, at the boundary",
     "check": R("a5", "part2", "swechat/claude_code", "typical_result", "cross_fit_median_abs_resid_over_median_result_tokens"),
     "decision": "Both agree on the number: upper bound 0.9996 < 1.0; LOOSE is borderline at the CI edge."},
    {"id": "A5-5", "question": "A5", "unit": "swechat/gemini, swechat/claude_code", "affects_gate": False,
     "dispute": "notes section 7 lists Gemini CLI and SWE-chat CC among tight-capable forms",
     "measurer": "'only where the fit is tight' includes Gemini CLI result-only and SWE-chat CC with thinking",
     "verifier": "neither meets TIGHT under the rule",
     "check": {"gemini_result_only_spearman": R("a5", "part2", "swechat/gemini", "result_only_variant", "corr", "spearman"),
               "swechat_cc_with_thinking_resid": R("a5", "part2", "swechat/claude_code", "non_image_growth_with_thinking", "cross_fit", "resid", "median_abs")},
     "decision": "Verifier is right: Gemini CLI result-only Spearman CI low 0.857 < 0.90 (LOOSE); SWE-chat CC with thinking "
                 "90.1 tokens / 168.7 = 0.53 (LOOSE); SWE-chat CC has no exact per-response output count, so the result-only "
                 "form does not apply. Only aiv_cc (pre-registered form) and OpenCode (result-only form; random-split p50 "
                 "15.5 tokens, about 0.08 of a result) meet the TIGHT thresholds."},
    # ---------------------------------------------------------------- A6
    {"id": "A6-1", "question": "A6", "unit": "all", "affects_gate": False,
     "dispute": "fills are key presence, not value fill", "measurer": "e.g. aiv_cc stop_reason 13,792/13,792 uncaptured",
     "verifier": "stop_reason / stop_sequence are mostly null; >= 12 of 435 candidates majority-null",
     "check": R("resolve", "A6", "harness_measured_fill_ge_0.3_value_fill"),
     "decision": "Verifier is right. Of the 435 harness-measured candidates with key-presence fill >= 0.3, census value "
                 "counts show 7 majority-null (stop_reason / stop_sequence in swechat CC, cc_local, aiv_cc; aiv_cc "
                 "stop_reason non-null 14/13,792), 421 majority non-null, and 7 aiv_cu pass-1 entries without value counts "
                 "(verifier: null on every A row it checked). The 'uncaptured' list needs a non-null condition before Phase "
                 "B uses it; aiv_cc stop_reason is not a candidate."},
    {"id": "A6-2", "question": "A6", "unit": "swechat/claude_code", "affects_gate": False,
     "dispute": "Read numLines availability per A row", "measurer": "raw fill 0.982 next to 4,043 A Read rows",
     "verifier": "1,794 of the rows are subagent rows that almost never carry the field; per-row 0.539",
     "check": R("resolve", "A6", "swechat_cc_read_results"),
     "decision": "Row split confirmed: 2,249 top-level + 1,794 subagent Read results (120 sessions). The census 0.982 is a "
                 "top-level fill. The verifier's per-row 2,180/4,042 = 0.539 needs raw files and was not re-derived."},
    {"id": "A6-3", "question": "A6", "unit": "swechat", "affects_gate": False,
     "dispute": "extra.marker fill", "measurer": "present on 0.646 of swechat results",
     "verifier": "key presence; value non-null on 488/21,025", "check": R("resolve", "A6", "swechat_result_extra_marker"),
     "decision": "Verifier is right: key present 13,592/21,025 (the CC share), value non-null 488/21,025."},
    {"id": "A6-4", "question": "A6", "unit": "swechat/claude_code", "affects_gate": False,
     "dispute": "sourceToolAssistantUUID listed as uncaptured linkage", "measurer": "uncaptured",
     "verifier": "equals IR parent_uuid on 9,338/9,340", "check": R("resolve", "A6", "swechat_cc_result_parent_uuid_link"),
     "decision": "For top-level results the link is already in the IR: result.parent_uuid equals the call row's uuid on "
                 "9,557/9,679 pairs. Nested subagent results have parent_uuid null (3,910/3,910), so the field's value for "
                 "them is unknown from the IR. Remove it from the top-level 'uncaptured linkage' list."},
    {"id": "A6-5", "question": "A6", "unit": "whowhen", "affects_gate": False,
     "dispute": "'no hash field'", "measurer": "0 timer/clock/token/hash fields", "verifier": "question_ID is HASH_ID",
     "check": R("resolve", "A6", "whowhen_census_classes"),
     "decision": "Verifier is right on wording: question_ID is census class HASH_ID in 4 entries (label store). Transcript-"
                 "side: no timer, clock, token or hash field; verdict 'absent' unchanged."},
    {"id": "A6-6", "question": "A6", "unit": "swechat/codex", "affects_gate": False,
     "dispute": "Codex ids missing from conversations.parquet", "measurer": "all 10,923 Codex calls",
     "verifier": "10,899 (24 synthetic skipped)", "check": R("resolve", "A6", "build_crosscheck_codex"),
     "decision": "10,899 ids of 10,923 raw calls (24 synthetic ids skipped). The table has 0 Codex tool_use rows."},
    # ---------------------------------------------------------------- A6 raw census (earlier workflow)
    {"id": "A6c-1", "question": "A6 census", "unit": "swechat/claude_code", "affects_gate": False,
     "dispute": "I5 uncheckable Agent results stored as a pass", "measurer": "match 94 / n 94 / rate 1.0 with a Wilson CI",
     "verifier": "a non-check encoded as a 100% pass", "check": R("resolve", "A6", "census_I5_no_nested_traffic_entry"),
     "decision": "Verifier is right: the entry stores match 94, n 94, rate 1.0. Read it as 94 uncheckable results, not 94 "
                 "passes."},
    {"id": "A6c-2", "question": "A6 census", "unit": "several", "affects_gate": False,
     "dispute": "'the IR drops' second clocks (OpenCode state.time.end, Codex exec duration, aiv_cu updated_at)",
     "measurer": "census O3: dropped", "verifier": "3 of 5 are in the IR",
     "check": R("a6", "part1_census_crossref", "summary", "census_uncaptured_now_captured_total"),
     "decision": "Superseded by A6, which found 302 census-'uncaptured' entries in the IR, including these three. Use A6."},
    {"id": "A6c-3", "question": "A6 census", "unit": "full raw populations", "affects_gate": False,
     "dispute": "O1 sample vs population rate, O7 Codex counter direction, O8 OpenCode formula, O12 diff range, O17 "
                "events data.cost",
     "measurer": "census statements", "verifier": "corrections from full-population re-derivations",
     "check": None,
     "decision": "Not re-derived here: each needs the full raw population outside the Phase A IR. No Phase A gate depends "
                 "on them. The verifier's corrections stand as verifier-reported (verification/verify_a6_raw_census.json) "
                 "and should be re-derived before Phase C uses these identities."},
]


# ---------------------------------------------------------------------------------------------------------- gate rules
def gate_rules(S):
    out = {}
    a1 = S["a1"]
    out["A1_latency_kill_rule"] = {
        "rule": a1["rules"]["kill_rule"]["operationalisation"],
        "units": {u: {k: v.get(k) for k in ("verdict", "reason", "n_pairs_both_ts", "n_sessions", "identical_stamp_share",
                                             "whole_second_stamp_share", "mixed_flag")}
                  for u, v in a1["verdicts"].items()}}
    a2 = S["a2"]
    rr = S["resolve"]["A2"]["verdict_rule_with_per_call_wilson"]
    units = {f"swechat/{f}": a2["swechat_by_format"][f]["verdict"] for f in a2["swechat_by_format"]}
    units.update({c: a2["by_corpus"][c]["verdict"] for c in a2["by_corpus"]})
    out["A2_join_rule"] = {"rule": a2["prereg"]["verdict_rule"]["value"],
                           "units": {u: {**v, "verdict_per_call_wilson_hi": (rr.get(u) or {}).get("verdict_wilson_hi")}
                                     for u, v in units.items()}}
    out["A4_text_proxy_rule"] = {"rule": S["a4"]["prereg"]["verdict_rule_for_a_text_proxy"],
                                 "labels": S["resolve"]["A4"]["prereg_rule_labels"]}
    # A5 conservation rule applied to the stored numbers
    a5 = S["a5"]
    rule = a5["PREREG"]["verdict_rule"]["value"]
    rs = S["resolve"]["A5"]

    def label(n_pairs, n_sess, sp_r, sp_lo, ratio):
        if n_sess < 10 or n_pairs < 200:
            return "INSUFFICIENT"
        if ratio is None:
            return None
        if sp_lo is not None and sp_lo >= 0.90 and ratio <= 0.25:
            return "TIGHT"
        if sp_r is not None and sp_r >= 0.70 and ratio <= 1.0:
            return "LOOSE"
        return "NOT_TIGHT"

    groups = {}
    for g, v in a5["part2"].items():
        fs = v.get("fit_set") or {}
        sp = ((v.get("non_image_growth") or {}).get("corr") or {}).get("spearman") or {}
        tr = (v.get("typical_result") or {}).get("cross_fit_median_abs_resid_over_median_result_tokens") or {}
        row = {"fit_pairs": fs.get("n"), "fit_sessions": fs.get("n_sessions"), "spearman": sp.get("r"),
               "spearman_lo": sp.get("lo"), "ratio_sha1": tr.get("value"),
               "label_sha1": label(fs.get("n", 0), fs.get("n_sessions", 0), sp.get("r"), sp.get("lo"), tr.get("value"))}
        if g in rs and rs[g].get("ratio_random_p50") is not None:
            row["ratio_random_split_p50"] = rs[g]["ratio_random_p50"]
            row["label_random_split_p50"] = label(fs["n"], fs["n_sessions"], sp.get("r"), sp.get("lo"), rs[g]["ratio_random_p50"])
        ro = v.get("result_only_variant")
        if ro and ro.get("cross_fit_median_abs_resid_over_median_result_tokens"):
            rsp = (ro.get("corr") or {}).get("spearman") or {}
            rt = ro["cross_fit_median_abs_resid_over_median_result_tokens"].get("value")
            row["result_only"] = {"spearman": rsp.get("r"), "spearman_lo": rsp.get("lo"), "ratio_sha1": rt,
                                  "label_sha1": label(ro.get("n", 0), ro.get("n_sessions", 0), rsp.get("r"), rsp.get("lo"), rt),
                                  "note": "ratio for this variant was added post hoc in A5 (POST_HOC.result_only_typical_ratio)"}
            rro = (rs.get(g) or {}).get("result_only_preregistered")
            if rro and rro["random_splits"].get("n_splits") and rro.get("typical_result_tokens_a5"):
                r50 = rro["random_splits"]["p50"] / rro["typical_result_tokens_a5"]
                row["result_only"]["ratio_random_split_p50"] = r50
                row["result_only"]["label_random_split_p50"] = label(ro.get("n", 0), ro.get("n_sessions", 0), rsp.get("r"), rsp.get("lo"), r50)
        groups[g] = row
    cx = (rs.get("swechat/codex") or {}).get("full_usage_out_variant_POST_HOC")
    if cx:
        groups["swechat/codex"]["full_usage_out_POST_HOC"] = {
            "spearman": cx["spearman"]["r"], "spearman_lo": cx["spearman"]["lo"],
            "ratio_sha1": cx["ratio_cross_fit_resid_over_typical_result"]["value"],
            "label_sha1": label(cx["n"], cx["n_sessions"], cx["spearman"]["r"], cx["spearman"]["lo"],
                                cx["ratio_cross_fit_resid_over_typical_result"]["value"]),
            "note": "post hoc; not a Phase A verdict"}
    out["A5_conservation_rule"] = {"rule": rule, "groups": groups,
                                   "not_feasible": {g: v.get("reason") for g, v in a5["part2_not_feasible"].items()}}
    return out


def verification(V):
    out = {}
    for k, rec in V.items():
        v = rec["verifier"]
        checks = v.get("checks") or []
        rows = []
        for c in checks:
            rows.append({"unit": c.get("corpus") or c.get("id"), "reproduced": c.get("reproduced"),
                         "discrepancy": c.get("problem") or ""})
        n_rep = sum(1 for c in rows if c["reproduced"])
        status = ("reproduced" if n_rep == len(rows) and not any(c["discrepancy"] and c["discrepancy"].lower() not in
                                                                    ("none.", "none", "") for c in rows)
                  else ("reproduced_with_discrepancies" if n_rep == len(rows) else "partly_not_reproduced"))
        out[k] = {"status": status, "checks_reproduced": n_rep, "checks": len(rows),
                  "kill_logic_ok": v.get("kill_logic_ok"), "per_unit": rows, "overclaims": v.get("overclaims", []),
                  "file": os.path.relpath(VER_FILES[k], ROOT).replace("\\", "/"), "provenance": rec.get("provenance")}
    return out


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    t0 = time.time()
    S = {k: json.load(open(p, encoding="utf-8")) for k, p in SRC_FILES.items()}
    V = {k: json.load(open(p, encoding="utf-8")) for k, p in VER_FILES.items()}
    res = {
        "meta": {"script": "analysis/probes/phase_a_merge.py", "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "inputs": {k: {"path": os.path.relpath(p, ROOT).replace("\\", "/"), "sha256": sha(p)}
                            for k, p in {**SRC_FILES, **{f"verify_{k}": p for k, p in VER_FILES.items()}}.items()},
                 "conventions": "rates are k/n with session-clustered bootstrap 95% CI (lib/stats.cluster_rate) unless "
                                "marked wilson; 'sessions' = resampling units (aiv_cc: runs). Split A only. Interpretation "
                                "in analysis/PHASE_A.md."},
        "verification": verification(V),
        "gate_rules": gate_rules(S),
        "headline": {k: resolve_refs(S, v) for k, v in HEADLINE.items()},
        "resolutions": [resolve_refs(S, r) for r in RESOLUTIONS],
        "sources": S,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False, allow_nan=False)
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
