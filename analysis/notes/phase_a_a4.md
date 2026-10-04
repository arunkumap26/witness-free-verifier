# Phase A4: error-signal survival

Script: `analysis/probes/phase_a_a4.py`. Data: `analysis/out/phase_a/a4.json` (raw counts only). Phase A split only
(`analysis/cache/<corpus>_A.parquet`). Unit = one IR `result` event. Every rate below is `k/n`, with a session-clustered
bootstrap 95% CI `[lo, hi]` and the number of sessions `s`. Wilson intervals are also in the JSON. Note that the
clustered bootstrap collapses to `[1.00, 1.00]` or `[0.00, 0.00]` when a rate is exactly 1 or 0. For those cases use the
Wilson interval in the JSON.

Pre-registration (in the JSON under `prereg`) was fixed after a schema-only recon and before any outcome was computed.
It covers the census regexes, the predictors A/B/C, the three references, the primary reference per unit and the
usable/partial/absent rule. Three descriptive tables were added after the first run: the any-value exit header, the aiv_cc
village-bash JSON section and the aiv_cu stderr templates. They are logged in
`prereg.post_first_run_additions_descriptive_only`. Predictor outputs were re-run and diffed against the first run and
are identical.

Predictors:
- **A** = `ir.error_marker(text)`.
- **B** = A OR any task census family in text or stderr.
- **C** = B OR the supplementary harness exit/timeout templates (Codex `Exit code: N`, aiv `bash has exited with
  returncode N`, harness timeouts).

References:
- **native_strict**: non-null `native_error` only.
- **native_null_neg**: null counted as "not flagged".
- **exit_nonzero**: rows with a non-null `exit_code`.

## Headline

| corpus / format | native flag survives? | best text proxy vs native (primary ref) | proposed Probe 3 error definition | verdict |
|---|---|---|---|---|
| swechat/claude_code | `is_error`: 4464/13592 filled. All 4150 shell results; non-shell only when true (314). | A: P 488/488, R 488/614 = 0.795 [0.72,0.85] s90 | `native_error is True` (null = not error) | usable |
| cc_local | 3359/5164 filled. All 3312 shell; non-shell 47/1852. | A: P 331/331, R 331/349 = 0.948 [0.90,0.98] s74 | `native_error is True` | usable |
| aiv_cc | 5957/33475 filled. Bash 5652/5652. `mcp__village__bash` only on MCP-level errors (49 true, 1750 null). | B: P 534/637 = 0.838 [0.74,0.90], R 534/538 = 0.993 [0.98,1.00] s38 | `native_error is True`, plus a regex on the JSON `error` field of village-bash turns (unvalidated) | usable, with a structural hole |
| swechat/codex | 860/1120 filled; shell 679/842 (= exit_code fill) | C: P 49/52 = 0.942 [0.81,1.00], R 49/49 (Wilson [0.93,1.00]) s6 | `native_error is True`; where shell native is null, a text exit header with N != 0 | usable (15 sessions) |
| swechat/opencode | 3735/3735; exit_code on 1135/1140 shell | B: P 62/85 = 0.729 [0.56,0.85], R 62/197 = 0.315 [0.22,0.40] s13. Shell R 26/157 = 0.166 [0.10,0.25] | `native_error is True` (status=error OR exit != 0). No text proxy for shell. | usable (native only) |
| swechat/gemini | 2313/2313 (`status` error/cancelled) | A: P 0/280, R 0/143. Disjoint. | union: `native_error is True` OR `gemini_exit_code_nonzero` marker, kept as two separate classes | partial |
| swechat/copilot | 265/265, 8 true, 2 sessions | below min n | `native_error is True` | partial (n too small) |
| swechat/cursor, simple_text | no tool results (0 results; 7 and 4 sessions in A) | n/a | none | absent |
| aiv_cu | none (0/6107) | no reference | regex proxy on stderr only (below), unvalidated | absent (native); proxy only |
| whowhen | exit_code on 87/353 (AG `code_exec`), 36 nonzero | A: 36/36 and 36/36, but **by construction**: loader and marker read the same header | `exit_code != 0` for AG code_exec; nothing for other agents | partial |

## 1. Fill rates (native_error, exit_code, stderr)

The key structural fact for the three Claude Code formats is when `is_error` is written: only on Bash results (`false`)
and on failures (`true`). Every non-shell result is `true` or absent:
- swechat/claude_code other: 314 true / 0 false / 9128 null
- cc_local other: 38 / 9 / 1805
- aiv_cc other: 256 / 0 / 25768

So null means "not flagged", not "unknown". The `native_null_neg` reference is the right one for these formats. Under
`native_strict`, non-shell precision is trivially 1.0 because there are no negatives.

- **swechat/claude_code**: fill 0.328 [0.285,0.370] (4464/13592, s126). Shell fill 4150/4150; native true on shell
  300/4150 = 0.072 [0.054,0.094]. exit_code 0/13592 (Claude Code has no exit field). stderr non-empty 43, all on
  native-false shell results.
- **cc_local**: fill 0.650 [0.394,0.790] (3359/5164, s107). Native true 349/5164 = 0.068 [0.056,0.105]. stderr
  non-empty 27, all native false.
- **aiv_cc**: fill 0.178 [0.108,0.247] (5957/33475, s77), because 26024 of the results are non-shell. Shell fill 5701/7451 = 0.765 [0.634,0.855]. The 1750 null shell results are all
  `mcp__village__bash` (`shell_tool_raw_x_native`). stderr non-empty 2323, all on native-false Bash results.
- **swechat/codex**: native fill 860/1120. Shell: exit_code fill 679/842 = 0.806 [0.513,0.930]; exit nonzero 49, all
  native true; 163 shell results are null on both. `exec_status`: completed 630 (all native false), failed 47 and
  declined 2 (all native true).
- **swechat/opencode**: native fill 3735/3735. Shell exit_code 1135/1140, nonzero 157 (= native true). Non-shell native
  true 40, all `status=error`.
- **swechat/gemini**: native fill 2313/2313 from `status`: success 2170, error 126, cancelled 17. No exit field.
- **swechat/copilot**: native fill 265/265, 8 true (`error_code=failure` on all 8), 2 sessions.
- **aiv_cu**: native and exit_code 0/6107. stderr (the turn's `error`) non-empty 277/6107 = 0.045 [0.035,0.056];
  shell 253/2229 = 0.114 [0.089,0.141].
- **whowhen**: exit_code 87/353 = 0.246 [0.151,0.403] (s63), all AG `code_exec`; 36 nonzero = native true.

## 2. error_marker distribution on results

- swechat/claude_code: cc_exit_code 248, cc_tool_use_error 176, cc_interrupt_reject 61, cc_permission_denied 3, none 13104.
  All markers sit on native-true results.
- cc_local: cc_permission_denied 173, cc_exit_code 135, cc_tool_use_error 14, cc_interrupt_reject 9, none 4833.
  On shell native-true results the split is permission_denied 157, exit_code 135, tool_use_error 11, interrupt 6,
  none 2. **About half of cc_local's Bash "errors" are permission denials (a harness refusal, not a failed command).**
  In swechat/claude_code shell the split is exit_code 248 of 300.
- aiv_cc: cc_exit_code 215, cc_tool_use_error 81, none 33179.
- codex, opencode, copilot, aiv_cu: **0 markers**. `ir.ERROR_MARKERS` has no Codex, OpenCode, Copilot or AI Village
  computer-use template.
- gemini: gemini_exit_code_nonzero 280, all on native-**false** shell results.
- whowhen: whowhen_exitcode_nonzero 36 (= native true).

## 3. Census: what survives and in what form

Per family the JSON gives `text_start` / `text_middle` / `stderr_any` / `stderr_only` / `hit_by_native`.

- **Claude Code formats.** Failure text is in the result text, never stderr-only (`stderr_only` = 0 for every family).
  - The exit header is always at the start: `cc_exit_code` text_start 248/248 in swechat, 135/135 in cc_local,
    215/215 in aiv_cc, all native true.
  - Generic families sit mostly in the middle of shell output and fire on native-false results too. In swechat/CC
    shell: `error_line` 83 hits (74 middle), 51 native true and 32 native false; `py_traceback` 38 hits (31 middle),
    18 true and 20 false; `no_such_file` 29 hits, 12 true and 17 false.
  - The CC non-shell failures the marker misses (FN templates, swechat) are harness texts with no `<tool_use_error>`
    wrapper: "File content (N tokens) exceeds" 27, "File does not exist." 26 + 5, "EISDIR" 18, "Request failed with
    status code" 9, "Cannot resume agent" 9, "ENOENT" 7.
- **aiv_cc non-shell.** MCP tool errors start with `Error:`: `error_line` text_start 201, of which 200 are native true.
  That is why B lifts recall there from A 52/256 to 252/256.
- **Codex.**
  - Every legacy shell result opens with an exit header of any value: `Exit code: N` on 558/842 shell results
    (incl. 466 zeros with native false).
  - Unified exec prints `Process exited with code N` mid-text, on 268/842.
  - Text therefore carries the exit code on success too.
  - Where shell native is null, the header is still present: `Exit code:` 66 zero + 3 nonzero; `Process exited` 78 zero.
- **OpenCode.** The exit code does **not** survive in the IR text.
  - Shell native-true results with blank text: 24.
  - B catches 26/157 nonzero exits. FN templates are ordinary test/build output, e.g. `> @…/… test` 50 and "PASS
    state-machine" 10.
  - Non-shell `Error:` lines open the text (text_start 36, all native true).
- **Gemini.**
  - `Exit Code: N` (N != 0) sits mid-text in a `Command/Directory/Output/Exit Code` block: 280/816 shell results,
    **all native false**.
  - Native-true results have their own texts, none matched by any family: "Failed to edit, N occurrences" 102,
    "[Operation Cancelled]" 17, "File path … is ignored" 8.
- **aiv_cu.** Failure text lives in stderr only, in every shell family:
  - `py_traceback` 14/14
  - `command_not_found` 12/12
  - `no_such_file` 29/32
  - `harness_timeout` 27/27
  - `bash_exited_returncode_N` 17/17
- **whowhen.** `py_traceback` appears mid-text in 41 results: 29 are native-true code_exec, 12 are other agents
  (native null; the loader notes Hand-Crafted log leakage).

## 4. Precision / recall against the native flag

Point estimates with cluster CIs. TP/FP/FN, Wilson CIs and the `prereg_rule` flags are under
`units[<unit>][all|shell|other].pr`.

- **swechat/claude_code** (null_neg):
  - all: A P 488/488, R 0.795 [0.72,0.85]. B P 0.813 [0.74,0.89] (488/600), same recall.
  - shell: A P 297/297, R 297/300 = 0.990 [0.97,1.00]. B adds 81 FP and 0 TP.
  - other: A R 191/314 = 0.608 [0.52,0.69].
  - **The census adds no recall in Claude Code; it only adds false positives.**
- **cc_local** (null_neg):
  - all: A P 331/331, R 0.948 [0.90,0.98]. B P 0.900 [0.82,0.95] (332/369), R 332/349.
  - shell: A R 309/311 = 0.994 [0.98,1.00].
  - other: A R 22/38 = 0.579 [0.41,0.76].
- **aiv_cc** (null_neg):
  - all: A P 296/296, R 296/538 = 0.550 [0.34,0.79]. B P 0.838 [0.74,0.90], R 0.993 [0.98,1.00].
  - shell: B P 282/365 = 0.773 [0.67,0.86], R 282/282.
  - Many B "false positives" are village-bash JSON turns whose `error` field holds a real failure the harness never
    flags (FP top template `{` 46). So they are not necessarily wrong.
- **swechat/codex** (strict):
  - A R 0/49.
  - B P 33/36 = 0.917 [0.60,1.00], R 33/49 = 0.673 [0.19,0.92] (s6).
  - C P 49/52 = 0.942 [0.81,1.00], R 49/49.
  - Against exit_nonzero (n 679) the numbers are identical.
- **swechat/opencode** (strict):
  - all: B P 0.729 [0.56,0.85], R 0.315 [0.22,0.40].
  - shell: B P 26/36 = 0.722, R 0.166 [0.10,0.25], so absent by the rule.
  - other: B P 36/49 = 0.735 [0.47,0.87], R 36/40 = 0.900 [0.65,1.00].
  - A and C add nothing.
- **swechat/gemini** (strict):
  - A P 0/280, R 0/143. B and C P 0/281, R 0/143.
  - The text exit code and the native flag do not overlap at all in Phase A.
- **swechat/copilot**: B 1 TP, 1 FP, 7 FN. Below min n (2 sessions).
- **whowhen** (strict = exit): A, B and C P 36/36, R 36/36 (s26).
  - **Tautological**: native_error and exit_code are parsed from the same `exitcode:` header the marker reads.
  - Under null_neg, B adds 12 FP from non-code agents.

## 5. aiv_cu: no native failure field

- **Output that looks successful** (pre-registered: non-blank output, no marker, no family in the output) covers
  2698/6107 results; on shell 1888/2229.
- **stderr on those results.** stderr is non-empty on 135/2698 = 0.050 [0.037,0.066]; on shell 128/1888 = 0.068
  [0.047,0.090].
  - Only 33/1888 = 0.017 [0.010,0.026] of shell results carry a failure template in stderr.
  - The rest is mostly git/curl progress. The top "other" stderr templates on looks-ok outputs are "To https:…" 41,
    "From https:…" 28, "Already on 'main'" 4 and curl progress 3.
  - **stderr is not a failure flag.**
- **stderr categories, all results:** empty 5830, other 159, task census family 74, harness_timeout 27,
  bash_exited_returncode_N 17. All 27 timeouts and all 17 nonzero returncodes occur with null output.
- **`system`**: the key is present on 0/6107 A results. The same field inside aiv_cc village-bash JSON turns is non-null
  on 0/1746. It cannot serve as a flag in Phase A.
- **`output_null`**:
  - gui: null on 3065/3065, a structural property, not a failure.
  - shell: P(stderr non-empty | output null) 125/325 = 0.385 [0.308,0.473], against 128/1904 = 0.067 [0.047,0.089]
    when output is present. Failure template 83/325 = 0.255 [0.181,0.347] against 33/1904 = 0.017 [0.010,0.026].
  - But 200/325 output-null shell results have empty stderr.
  - So output_null is associated with failure but is not a failure flag.
- **Other flags.** `screenshot_is_redacted` (31, all gui, no stderr) and `has_redaction_been_overruled` (true on 0) carry
  nothing.
- **By model family (shell).** stderr non-empty ranges from 4/240 (anthropic-fable) to 58/203 = 0.286 [0.181,0.428]
  (openai-responses). A stderr-based proxy would therefore mix model behaviour into the error rate.
- **Note.** In `candidate_flags`, `pred_C` against the failure template is tautological: C contains those templates.
- **aiv_cc village-bash.** 1746/1799 `mcp__village__bash` results are JSON turn records with keys
  output/error/system/turnId/agentStatus(/advice/day), the same harness as aiv_cu. All 1746 are native null.
  - `error` is non-empty on 267/1746 = 0.153 [0.098,0.236].
  - Categories: other 217, task census family 42, harness_timeout 8.

## 6. Proposed Probe 3 error definitions (not applied)

- **Claude Code formats** (swechat/claude_code, cc_local, aiv_cc Bash):
  - Definition: `native_error is True`, with null = not error.
  - Measured agreement of the best text proxy: A P 1.0, R 0.795 / 0.948 / 0.550 in the three corpora.
  - Split the error class by marker (exit code / permission denial / tool_use_error / interrupt). In cc_local,
    permission denials are 157 of the 311 shell errors.
  - aiv_cc village-bash turns have no native failure. Use the aiv_cu stderr rule on the JSON `error` field and report
    it as a separate, unvalidated class.
- **Codex**:
  - Definition: `native_error is True`; for shell results with null native, nonzero `Exit code: N` / `Process exited
    with code N` in text.
  - C measures P 49/52, R 49/49 against native.
  - Only 15 sessions with results in A.
- **OpenCode**:
  - Definition: `native_error is True` (status=error OR exit != 0).
  - Text cannot replace it for shell (R 0.166).
- **Gemini**:
  - Report two classes: tool-call failure = `native_error is True`; command failure = `gemini_exit_code_nonzero`
    marker.
  - Their union cannot be validated against anything, because they never co-occur.
- **Copilot**: `native_error is True`. Too small to measure text (2 sessions).
- **Cursor, simple_text**: Probe 3 is dead (no tool results).
- **aiv_cu**: Probe 3 needs a regex proxy.
  - Proxy: stderr matches `bash has exited with returncode N≠0`, a harness timeout, or a task census family.
  - It fires on 118/6107 = 0.019 [0.013,0.026] of results; shell 116/2229 = 0.052 [0.038,0.072] (`aiv_cu.by_class.*.stderr_fail_template`).
  - Its precision/recall cannot be measured here: there is no reference.
- **whowhen**:
  - Definition: `exit_code != 0` on AG `code_exec` (36/87).
  - No failure signal exists for WebSurfer/FileSurfer/Assistant results.

## 7. Could not measure

- **aiv_cu**: precision/recall of any definition (no reference flag).
- **whowhen**: the 1.0/1.0 agreement is by construction.
- **Copilot** (2 sessions) and **cursor/simple_text** (no results).
- **OpenCode visibility**: whether the model saw anything beyond `state.output` for shell. The IR text has no exit code,
  but the harness prompt assembly is not in the data.
- **Codex null native**: the 163 null-native Codex shell results are not resolved here. They are unified-exec
  running/deferred cases or missing `exec_command_end`; see `swechat_build.json`.
