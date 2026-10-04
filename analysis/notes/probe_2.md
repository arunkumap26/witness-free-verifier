# Probe 2 (Phase B): knowledge precedence

Script `analysis/probes/probe_2.py` (`PYTHONIOENCODING=utf-8 python -m analysis.probes.probe_2`; `runtime_s` in the JSON).
Numbers: `analysis/out/probe_2.json` (byte-identical copy at `analysis/out/phase_b/probe_2.json`, the prereg's output
path). Pre-registration check: sha256 of `prereg_common.py` equals `prereg.json provenance.spec_module_sha256`
(`spec_module_sha256_ok: true`). The prereg.json sha256 it ran under is in `prereg_json_sha256`. Every threshold is
parsed from `prereg.json` text (`thresholds_from_prereg`). Split B only. No Phase C file and no other note was read.

Notation: k/n = rate [95% CI], s = sessions. CIs are `stats.cluster_rate` session-clustered bootstraps. A JSON path
such as `U.swechat/claude_code.main.deep_first_try.S_deep` means `units.<unit>.strata.<stratum>.<...>`.
Sections marked **Interpretation** are not data.

## 1. Verdicts (mechanical, `verdicts`; 22 cells, `n_verdict_cells`)

The rule: S_deep decides when it has at least 100 deep first-try successful accesses from at least 20 sessions.
ALIVE needs S_deep ≤ 0.05 with CI hi ≤ 0.10; WEAK needs ≤ 0.20; above that is DEAD. Below S_deep's minimum n, the same
rule runs on S_path_any (at least 200 from 20 sessions), capped at WEAK.

| unit | stratum | verdict | deciding statistic | value [CI], k/n, s | caps / labels |
|---|---|---|---|---|---|
| swechat/claude_code | main | **WEAK** | S_deep | 0.144 [0.125, 0.163], 671/4,655, 586 s | |
| swechat/claude_code | subagent | **WEAK** | S_deep | 0.077 [0.062, 0.091], 525/6,850, 296 s | |
| swechat/opencode | subagent | **WEAK** | S_deep | 0.073 [0.020, 0.150], 16/219, 53 s | |
| swechat/opencode | main | **DEAD** | S_path_any (S_deep has 11 s) | 0.309 [0.229, 0.394], 237/767, 36 s | fallback |
| swechat/codex | main | **DEAD** | S_path_any (S_deep has 11 s) | 0.311 [0.213, 0.429], 343/1,103, 24 s | fallback; small n |
| swechat/codex | subagent | **WEAK** | S_path_any (0 deep accesses) | 0.131 [0.099, 0.163], 104/795, 36 s | fallback (cap not binding) |
| cc_local | main | **DEAD** | S_path_any (S_deep has 17 s) | 0.592 [0.445, 0.653], 1,669/2,820, 173 s | fallback; aggregates only |
| aiv_cc | main | **WEAK** | S_path_any (S_deep has 13 s) | 0.192 [0.081, 0.351], 710/3,689, 53 s | fallback; **single-agent case study** |
| aiv_cu | main | **INCONCLUSIVE** | S_path_any (no structured reads) | 0.807 [0.788, 0.824], 9,597/11,889, 1,130 s | DEAD → INCONCLUSIVE (antecedents incomplete); proxy |
| swechat/gemini | main | INSUFFICIENT_N | S_deep 127 from 13 s; S_path_any 302 from 19 s | | |
| swechat/cursor | main | INSUFFICIENT_N | no results, so no first-try success; 38 paths from 3 s | | |
| whowhen | main | INSUFFICIENT_N | 0 access calls; 27 first-mention paths from 15 s | | |
| cc_local | subagent | INSUFFICIENT_N | S_deep 12 from 2 s; S_path_any 14,975 from **6** s | | |
| aiv_cc, aiv_cu, gemini, cursor, whowhen | subagent | INSUFFICIENT_N | no subagent threads with calls | | |
| swechat/copilot, swechat/simple_text | both | NOT_TESTABLE | 0 B sessions / no tool calls | | |

No unit is ALIVE. Instrument check passed, so no cap came from it (section 2). Every pre-registered sensitivity run
gives the same label in every cell (`U.<unit>.<s>.verdict.sensitivity`). Those runs are: the calibration's population
(first-mention accesses only), dropping permission/interrupt results, and literal case-sensitive matching.

## 2. Instrument check (`instrument_check`)

The check is swechat/claude_code main-thread S_symbol_ref ≤ 0.10. Measured: **0.027 [0.022, 0.031]**, 1,242/46,836
first-mention old_string symbols, 1,274 s. **Passed.** Only 0.027 of Edit `old_string` identifiers lack an earlier
visible antecedent, as Claude Code's read-before-edit rule predicts. Excluded redacted references
change nothing here (`including_redacted_refs`: the same 1,242/46,836).

## 3. The honest baseline: how often is an honest reference unsourced?

Main thread, first mentions per thread (`U.<unit>.main.classes.<class>.unsourced`). Cells below the global minimum
(30 from 5 s) show k/n only.

| class | swechat CC | codex (small n) | opencode | gemini | cc_local | aiv_cc (single agent) | aiv_cu |
|---|---|---|---|---|---|---|---|
| path (S_path_any) | 0.289 [0.276, 0.300] | 0.311 [0.213, 0.429] | 0.309 [0.229, 0.394] | 0.523 [0.410, 0.635] | 0.592 [0.445, 0.653] | 0.192 [0.081, 0.351] | 0.807 [0.788, 0.824] |
| symbol_ref (edit old_string) | **0.027** [0.022, 0.031] | **0.050** [0.011, 0.069] | 0.100 [0.043, 0.164] | 0.397 [0.201, 0.520] | 0.421 [0.320, 0.569] (12 s) | **0.028** [0.004, 0.073] | none |
| symbol_shell | 0.296 [0.263, 0.332] | 0.353 [0.278, 0.483] | 0.227 [0.144, 0.418] | 0.214 [0.143, 0.338] | 0.751 [0.675, 0.867] | 0.701 [0.467, 0.843] | 0.786 [0.761, 0.809] |
| env_var + cfg_key (S_env_cfg) | 0.125 [0.103, 0.148] | 0.356 [0.208, 0.498] | 0.156 [0.050, 0.320] | 0.077 [0.000, 0.241] | 0.680 [0.530, 0.850] | 0.534 [0.217, 0.778] | 0.832 [0.796, 0.868] |
| symbol_search (reported only) | 0.262 [0.244, 0.282] | none | 0.180 [0.121, 0.254] | 4/18 | 0.500 [0.325, 0.676] | 0.278 [0.154, 0.462] | none |

Paths by field, main thread (`classes.path.by_field`). In swechat CC, structured (tool-argument) paths are 0.252
[0.241, 0.265] (19,211) and free (shell) paths are 0.364 [0.341, 0.386] (9,272). In aiv_cc the split is 0.131 [0.024,
0.323] structured and 0.482 [0.390, 0.580] free.

Where sources come from (swechat CC main paths, `classes.path.sourced_by`). A path can match more than one source:
- result: 0.594 [0.579, 0.608];
- user: 0.103 [0.093, 0.113];
- system: 0.067 [0.058, 0.076];
- enumeration: 0.104 [0.096, 0.113], of which 0.025 [0.022, 0.029] are sourced only by enumeration.

The most recent matching result is a median of 3 result events back (p90 29 [26, 33], p95 57 [50, 63];
`result_source_lag_events`). Only 0.174 [0.166, 0.182] of first mentions are sourced by the immediately preceding
result. In aiv_cc that share is 0.724 [0.556, 0.856].

Per-session spread (swechat CC main, sessions with ≥ 10 first-mention paths, 897 s,
`per_session_unsourced_share`): p10 0.069 [0.063, 0.077], median 0.243 [0.231, 0.261], p90 0.522 [0.492, 0.538].
Histogram by tenths: 160, 190, 207, 120, 112, 65, 18, 15, 5, 5.

Position in the thread (`by_call_ordinal`, swechat CC main paths):
- the first call: 0.352 [0.313, 0.392];
- calls 5–19: 0.252 [0.235, 0.267];
- calls 100–499: 0.320 [0.294, 0.347];
- calls 500+: 0.403 [0.328, 0.453] (23 s).

## 4. S_deep: deep, first-try successful, unsourced and unenumerated accesses

**swechat/claude_code main (D = 6).**
- First accesses by a read or edit tool: 15,745, with depth unknown for 521.
- First-try success: 0.961 [0.958, 0.966]. Deep: 4,818; deep and successful: 4,655 (586 s).
- **S_deep = 0.144 [0.125, 0.163]**. Sessions with at least one such access: 231/586 = 0.394 [0.355, 0.434] (Wilson).
- Every depth, successful accesses: 0.162 [0.151, 0.173].
- By tool: read 0.147 [0.127, 0.166] (4,549); edit 0.019 [0.000, 0.051] (106). A secondary class, read-like shell
  commands, gives 0.175 [0.129, 0.225] (308, 138 s).
- Sources of the deep accesses (`deep_sourced_by`): result 0.731 [0.706, 0.757], user 0.099 [0.083, 0.118], system
  0.077 [0.059, 0.097], enumeration 0.119 [0.101, 0.138].
- Unsourced share by depth (`unsourced_by_depth`):
  - depth 1: 0.368 [0.327, 0.410];
  - depth 2: 0.126 [0.104, 0.151];
  - depth 3: 0.167 [0.147, 0.190];
  - depth 6: 0.147 [0.119, 0.178];
  - depth 7: 0.103 [0.073, 0.138];
  - depth 9: 0.156 [0.120, 0.196];
  - depth 10: 0.175 [0.095, 0.257].

  Past depth 1 the rate is flat, between 0.103 and 0.175 for depths 2–10.

**swechat/claude_code subagent stratum (D = 6).**
- **S_deep = 0.077 [0.062, 0.091]**, 525/6,850, 296 s. Sessions with at least one: 115/296 = 0.389 [0.335, 0.445].
- The nested prompt (`parent_prompt`) sources 0.263 [0.218, 0.309] of the deep accesses and 0.255 [0.237, 0.273] of
  all first-mention paths.
- S_path_any is 0.179 [0.164, 0.197] and S_symbol_ref is 0.011 [0.007, 0.016].

**swechat/opencode subagent (child sessions).** S_deep 0.073 [0.020, 0.150], 16/219, 53 s. S_path_any is 0.098
[0.084, 0.112] (176 s), the lowest path baseline of any cell with enough n.

**Cells where S_deep was below its minimum, reported but not interpreted:**
- codex main: 27/156, 11 s;
- opencode main: 18/201, 11 s;
- gemini main: 55/127, 13 s;
- cc_local main: 31/90, 17 s.

## 5. Nulls, with the same prominence

- **aiv_cc (single-agent case study): S_deep = 0/1,235.** The per-event Wilson upper bound is 0.0031, and no session
  has one (0/13, Wilson hi 0.228). Across all depths the unsourced share is 0.002 [0.000, 0.004] (2,636 accesses,
  47 s). Of the deep reads, 0.998 [0.990, 1.000] are sourced by an earlier result. But the 1,235 deep accesses come
  from **13 sessions**, below the 20 the verdict needs, so the cell falls back to S_path_any (0.192, WEAK). Of 189 B
  runs, 156 share an SDK session with an A run, and there are 35 distinct SDK sessions (`aiv_cc_rule`). The case is not
  held out in content.
- **No subagent signal outside three scaffolds.** The subagent stratum reaches a verdict only for swechat CC, opencode
  and codex. cc_local has 675 subagent threads, but they sit in 6 sessions.
- **Gemini, cursor and whowhen are INSUFFICIENT_N.** whowhen yields 27 first-mention paths over 111 sessions and no
  access calls. cursor records no tool results.
- **No cell reached ALIVE**, including the instrument-validated swechat CC.

## 6. Deviations (`deviations` in the JSON) and their effect

1. **Output path.** The JSON is written to `analysis/out/probe_2.json` and also to `analysis/out/phase_b/probe_2.json`.
   No effect.
2. **Drive-letter path keys are matched case-insensitively.** The prereg lowercases drive paths but not the antecedent
   text, so a Windows path containing an uppercase letter could never be sourced. The literal variant is reported, and
   **no verdict changes**. It matters materially only in cc_local (swechat CC main S_deep is 0.144 vs 0.145 literal):
   - S_path_any: 0.592 vs 0.694 literal;
   - S_deep: 0.344 vs 0.567 literal.
3. **Identifiers containing REDACTED are excluded**, as redacted paths already are. 3 distinct env_var references in
   swechat CC main; 0 symbol_ref. No effect.
4. **Enumeration directory argument.** The prereg does not say how to extract it from shell commands; the extraction
   used is written out in the JSON. Enumeration-only sourcing is 0.025 of swechat CC main paths.
5. **Codex sub-agent envelopes count as `parent_prompt`.** These are inter-agent JSON messages stored as
   assistant-kind rows. This affects the codex subagent cell only, which has 0 deep accesses.
6. **Workspace root for child sessions with no main thread** (opencode/codex subagents) is taken from the thread's own
   access paths.
7. **Access population.** The prereg text says "first access by an access tool"; the calibration counted "first
   mention that is an access". The verdict follows the text. The calibration population gives the same labels (swechat
   CC main 0.157 [0.137, 0.178], subagent 0.076 [0.061, 0.091]).
8. **First-try success is applied literally** (a CC permission-denied or interrupted read is "not an error"). Dropping
   those changes nothing (swechat CC main 671/4,655 either way).
9. **Post-hoc descriptive additions**, made after the first B output and feeding no verdict:
   - **S_path_any without creation targets:**
     - swechat CC main: 0.255 [0.243, 0.267];
     - codex main: 0.300 [0.199, 0.425];
     - opencode main: 0.219 [0.168, 0.274];
     - cc_local main: 0.514 [0.383, 0.586];
     - aiv_cc: 0.098 [0.054, 0.163];
     - aiv_cu: 0.807.

     The three DEAD fallback cells stay above 0.20 without creation targets.
   - **Trace of unsourced references** (below).

## 7. Interpretation

**Is the signal buried?** It depends on the reference class, and the answer is the probe's main result.

- **"Any world-specific path with no antecedent" is buried.** Honest main threads leave between 0.192 (aiv_cc) and
  0.807 (aiv_cu) of first-mention paths unsourced; swechat CC sits at 0.289. That is the buried-signal case the brief
  warned about: a path-mention flag would fire on a large fraction of honest references. Shell-text paths are noisier
  than tool-argument paths.
- **"Deep, first-try, successful read of a path never shown" is not buried, but it misses the budget.** The best
  measured cell, swechat CC main, sits at 0.144 against the pre-registered 0.05 false-positive budget. Its
  session-level form is useless as a binary flag: 0.394 of honest sessions with deep reads have at least one such read.
  Subagents are cleaner (0.077 in CC, 0.073 in OpenCode child sessions) because their nested prompt names the files.
  They still miss ALIVE on the point estimate. Depth does not concentrate the anomaly: past depth 1 the honest rate is
  flat, so "deep" adds little discrimination over "any read".
- **Edit `old_string` symbols are the one quiet channel.** In Claude Code formats, honest agents almost always quote
  code they have just seen: 0.027 in swechat CC, 0.011 in CC subagents, 0.050 in codex (small n), and 0.028 in aiv_cc
  (single agent). This was the instrument check, not a pre-registered verdict statistic, so it carries no verdict here.
  As a measured baseline, though, it is the lowest. Gemini (0.397) and cc_local (0.421, 12 s) break it:
  - Gemini masks some results (PHASE_A.md A3), and it can edit code it wrote itself in earlier `write_file`
    arguments, which the prereg rightly does not count as a source. This is seen in examples, not measured here;
  - cc_local's old_string references come from 12 sessions only.

**What honest "unsourced" looks like** (post-hoc trace, swechat CC main, 671 knowledge-from-nowhere deep reads,
`post_hoc_unsourced_deep_trace`):
- 0.523 [0.455, 0.589] have their basename visible earlier: a directory the user or a listing named, plus a file name
  seen elsewhere, which the last-two-components key cannot credit. This includes the tree-style listings the prereg
  flags as a known bias.
- 0.113 [0.080, 0.151] had already been written by the agent into its own earlier arguments (e.g. a Task prompt).
- 0.410 [0.347, 0.474] leave neither trace.

So under half of the honest residual is "knowledge from nowhere" in the strong sense. Even that residual is an
upper bound, because the IR lacks CLAUDE.md, the system prompt, the cwd and earlier sessions (PREREG §7).
Unsourced rates rise at both ends of a thread (first call 0.352, calls 500+ 0.403). That fits context the transcript
does not show at the start, and context lost to compaction late.

**Consequence for a detector** (interpretation only). A knowledge-precedence check cannot work as a per-reference
alarm on these data. It could work as a rate comparison: an agent fabricating tool results would have to reference
paths and code it never saw, pushing its own S_deep and S_symbol_ref above the honest 0.144 and 0.027. That needs many
deep reads or edits per agent, plus a matcher that credits path composition (basename and parent seen separately)
before the honest residual drops toward the 0.05 budget. The aiv_cc null (0 of 1,235) shows the honest floor can be zero
for a disciplined single agent. But that is one agent in 13 sessions, and it is not evidence for any other scaffold.

## 8. Limits

- "Unsourced" is an upper bound everywhere (PREREG §7). In aiv_cc, aiv_cu and cursor the antecedent record is known to
  be incomplete, so a DEAD there is INCONCLUSIVE.
- The aiv_cu path rate (0.807) comes from shell text alone, and first-try success there is a proxy.
- S_deep minimum n: codex, opencode main, gemini, cc_local and aiv_cc have 156, 201, 127, 90 and 1,235 deep
  successful accesses, but fewer than 20 sessions each. Their verdicts come from the fallback statistic, or are
  INSUFFICIENT_N, not from the mechanism the probe targets.
- cc_local is private: this note and the JSON carry aggregates only, with tool names mapped by `private_key`.
