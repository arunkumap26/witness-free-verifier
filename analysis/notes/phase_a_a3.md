# Phase A3: truncation of tool-result text

Script `analysis/probes/phase_a_a3.py`, output `analysis/out/phase_a/a3.json` (raw counts only). This file holds the
interpretation, and every number below is a field in that JSON. Data: Phase A splits only (`<corpus>_A.parquet`). Unit: one
IR `result` event. Rates are `cluster_rate` (result-level ratio, session-clustered bootstrap 95% CI). Session shares use
Wilson intervals. For a 0 count the bootstrap CI is [0, 0], so the Wilson upper bound on sessions is the usable bound.
The marker catalogue, windows and the cap-candidate rule are in `rules` / `markers_catalogue` / `cap_rule`. They were fixed
before the final counts were computed. The marker list came from exploring Phase A text of the public corpora. The
cc_local text was never read: the same patterns were applied to it blind.

## Headline answers

1. **The SWE-chat 10,256-char dataset cap is absent from every corpus we use (null).** Exact cap (`'\n... [truncated]'`,
   len 10,256): 0 of 21,025 swechat results (0 of 178 sessions, Wilson upper bound 2.1% of sessions). The loose form
   (any length) also has 0. The other four corpora have 0 as well. The cap exists only in `conversations.parquet`: 1,552
   of 408,572 tool_result rows in the full table (`context_from_recon`, not a Phase A number). The IR is built from the
   raw transcripts, and those are uncapped: 1,395 Phase A swechat results are longer than 10,256 chars.
2. **The only real cap in the 10 KB window is Claude Code's error-result truncation.** It keeps the first 5,000 and last 5,000
   UTF-16 units and puts `... [N characters truncated] ...` between them, so results land at 9,230 to 10,040 chars (median 10,040)
   in swechat and 10,039 to 10,040 in aiv_cc. Counts: swechat claude_code 15 results in 10 sessions, aiv_cc 15 in 2
   sessions, cc_local 0. Every one has native_error = true and **keeps the `Exit code N` first line** (error_marker
   cc_exit_code 15/15 in swechat and 15/15 in aiv_cc).
   The window [9,728, 10,256] is otherwise not enriched:
   - swechat claude_code shell: 22/4,150 in the window vs 9 in the equal-width window just below. 14 of the 22 carry the marker.
   - CC "other": 56 in the window vs 105 below.
   - aiv_cc other: 112 vs 101.
   - cc_local other: 50 in the window vs 5 below. All 50 are one repeated text: lengths 9,839 (42 results, 42 sessions,
     1 distinct text) and 9,838 (8). That is repeated content, not truncation.
3. **How much is truncated depends on the scaffold** (any loss-type marker, all tools):

   | corpus / group | k / n | rate [95% CI] | sessions hit |
   |---|---|---|---|
   | swechat claude_code | 134 / 13,592 | 0.99% [0.76, 1.22] | 55 / 126 |
   | swechat codex | 11 / 1,120 | 0.98% [0.31, 2.02] | 7 / 15 |
   | swechat gemini | 844 / 2,313 | **36.5% [25.5, 43.3]** | 7 / 10 |
   | swechat opencode | 40 / 3,735 | 1.07% [0.68, 1.64] | 16 / 25 |
   | swechat copilot | 4 / 265 | 1.51% [0, 2.78] | 1 / 2 |
   | swechat pooled | 1,033 / 21,025 | 4.91% [1.90, 8.47] (Gemini dominates) | 86 / 178 |
   | cc_local (text markers) | 22 / 5,164 | 0.43% [0.19, 0.87] | 8 / 107 |
   | cc_local (markers + structured flag) | 208 / 5,164 | 4.03% [2.02, 9.98] | 58 / 107 |
   | aiv_cc | 35 / 33,475 | 0.10% [0.03, 0.26] | 10 / 77 |
   | **aiv_cu** | **0 / 6,107** | 0 (Wilson session upper bound 1.9%) | 0 / 199 |
   | **whowhen** | **0 / 353** | 0 (Wilson session upper bound 5.7%) | 0 / 63 |

   Read windows (pagination) and read refusals are not counted above. Counted separately, read windows are OpenCode 412 and
   Gemini 90, and read refusals are CC 27 (swechat) and Copilot 5.

## Truncation types and markers (results affected; sessions in parentheses)

Claude Code (swechat claude_code / cc_local / aiv_cc):
- `[N characters truncated]` (error results, middle elision at 10 K UTF-16 units): 15 (10) / 0 / 15 (2). All Bash.
- `[N lines truncated]` (tail cut; success output at the 30,000-char Bash cap, 20,000-char Grep cap): 3 (2) / 0 / 1 (1).
  Lengths are 30,031 (Bash) and 20,030 to 20,031 (Grep), and 30,029 in aiv_cc.
- `<persisted-output>` + `Output too large (…KB). Full output saved to:` (spill; the model sees a preview of about 2 KB):
  65 (36) / 18 (5) / 10 (6). Preview lengths are 1,833 to 2,282 / 1,300 to 2,216 / 2,170 to 2,306 chars. Tools: swechat
  Bash 26, Read 22, Grep 17; cc_local shell 15, webfetch 3; aiv_cc Bash 7, Grep 3.
- `(Results are truncated. Consider using…)` (Glob list cap): 44 (25) / **0** / 8 (3).
- `[Omitted long matching line]` (ripgrep line cap): 7 (5) / 4 (4) / 1 (1).
- `File content (N tokens) exceeds maximum allowed tokens` (read refusal): 27 (13) / 1 (1) / 1 (1).

Codex: `…N tokens truncated…`, always together with a `Total output lines: N` header: 11 results in 7 sessions, 39,966 to
120,266 chars. The tools were exec_command 8, shell_command 2 and write_stdin 1. The task's other forms
(`...[output truncated]`, `[... omitted N of M lines ...]`, `…N chars truncated…`) and an `extra.truncated` flag: 0 / absent.

Gemini CLI: `<tool_output_masked>` wrapper with `Output too large. Full output available at:` appears on 840 of 2,313 results
in 7 of 10 sessions:
- shell: 266, with `... [N lines omitted] ...`, 722 to 33,655 chars.
- non-shell: 574 (read_file 226, write_file 187, replace 133, …), with `... [TRUNCATED] ...`, in a narrow 583 to 773 chars.

Other Gemini markers: `Output too large. Showing first 8,000 and last 32,000 characters` 10 (3 sessions),
`... [N characters omitted] ...` 5, and read_file `IMPORTANT: The file content has been truncated` 90 (read window).

OpenCode:
- `...N bytes truncated...` + `The tool call succeeded but the output was truncated. Full output saved to:` (bash spill):
  16 (14), up to 51,551 chars.
- grep `(Results truncated: showing N of M matches` 20 (8), glob `(Results are truncated: showing first N results` 4 (2).
- read `(Output capped at N KB` 14 (8) and `(Showing lines a-b of N. Use offset=…)` 398 (20).

Copilot (2 sessions): `Output too large to read at once (N KB). Saved to:` 4, `[Output truncated. Use view_range=` 1,
`File too large to read at once` 5.

aiv_cu, whowhen: no marker of any type. The residual "truncat" mentions (aiv_cu 7, whowhen 1) are content.

## Do truncated results keep their failure marker / exit line?

- **CC error truncation: yes (15/15 swechat, 15/15 aiv_cc).** The head is kept, so `^Exit code N` survives. Error-marker | native_error = true:
  15/15 (swechat, 10 sessions) vs 282/285 = 0.989 [0.972, 1.0] in untruncated shell results. aiv_cc: 15/15 (2 sessions)
  vs 229/267 = 0.858 [0.708, 0.942].
- **CC persisted-output: untestable (n = 0 failures).** None of the persisted results has native_error = true (swechat 65:
  false 26 / null 39; cc_local 18: false 15 / null 3; aiv_cc 10: false 7 / null 3). The text starts
  with `<persisted-output>`, so the anchored `^Exit code` marker could not fire on such a result anyway. This follows from
  the format; it was not observed.
- **Codex: header exit line kept in 10/11** (0.909 [0.571, 1.0], 7 sessions) vs 812/831 = 0.977 [0.930, 0.996] baseline.
  The one without it is a write_stdin poll whose header reports a still-running process, so there was no exit to show. None
  of the 11 is a failure (native_error false 5, null 6), so retention for failures is untestable.
- **Gemini masked shell: `Exit Code:` line present in 97/270 = 0.359 [0.21, 0.429]** vs 183/546 = 0.335 [0.224, 0.451] for
  unmasked shell. The preview keeps the tail, and masking does not remove the exit line at a detectable rate.
  native_error = true is 0 of 270 masked vs 16 of 546 unmasked.
- **OpenCode bash spill: no exit line in the text by design.** The structured exit code is present in 16/16 and none of them
  are failures.
- Copilot: no exit line in the text. aiv_cu has no exit field. Who&When has no truncation.

## Length spikes (top-10 exact lengths > 1,000 chars; `spikes`)

The cap-candidate rule flagged three spikes in total:
- swechat claude_code 10,040 chars: 9 results in 7 sessions, all with `cc_chars_truncated`. **This is a true cap.**
- swechat claude_code 1,600: 8 results in 6 sessions in chars, and 10 in 4 sessions in bytes, with no marker. Inspected:
  unrelated content (ps listings, file reads, source). **A false positive of the rule.**

No other spike in any corpus qualifies:
- swechat: repeated reads of one file (for example 10,403 / 11,256 / 5,283: 15 results, 1 session, 1 distinct text each)
  and deterministic test output (opencode 9,955: 23 results, 1 session, 1 distinct prefix).
- cc_local: Glob listings repeated across sessions (7,324: 69 results / 47 sessions / 4 texts / 1 prefix; 7,510; 6,629;
  2,392) and one file read in many sessions (9,839).
- aiv_cc: fixed-format `mcp__village__get_events` JSON (3,529: 2,237 results in 5 sessions, 259 distinct texts but 2
  distinct prefixes).
- aiv_cu: no exact length repeats more than 3 times in chars or 4 in bytes.
- whowhen: no repeat above 2.
- **aiv_cu has no visible cap**, but its maximum is a single gemini-pro shell output of exactly 135,168 chars (a round binary size).
  Inspected, it ends mid-line. With n = 1, no cap can be claimed.

## Structured truncation flags

- CC `toolUseResult.truncated` (Glob only):
  - swechat: true 10 / false 158. aiv_cc: true 8 / false 82. Flag true agrees exactly with the text marker in both.
  - **cc_local: true 186 / false 241, and 0 of the 186 carry any catalogue marker.** All 186 have exactly 101 lines and a last
    line that starts with `(` (103 to 105 chars, 29 distinct variants). None contains "truncat". This local CC version words
    the Glob note differently, so a text-only detector misses all of them. They are in 52 sessions, and adding them moves
    cc_local from 22 to 208 truncated results.
- OpenCode `state.metadata.truncated`: true 452 / false 3,243. All 452 flagged results carry a text marker (read 412,
  grep 20, bash 16, glob 4), and 0 unflagged results do. Flag and text agree exactly.
- CC `persistedOutputSize` is on 16 of the 65 swechat persisted results, 8 of 18 in cc_local and 0 of 10 in aiv_cc, so the
  text marker is the more complete signal.
- cc_local `read_truncation_notice` attachments: 0 events in split A.

## Unit effects

Chars, UTF-8 bytes and UTF-16 units disagree enough to move results across a window:
- opencode shell has 23 results in the char window but 1 in the byte window, all from the 9,955-char run with
  box-drawing characters.
- CC's cap counts UTF-16 units, not Python chars.

Results whose UTF-16 length ≠ char length: swechat claude_code 140, aiv_cc 1,635, cc_local 5.

## Surprises
- Gemini CLI masks a third of its tool outputs (`<tool_output_masked>`), so the transcript holds a preview and not what the
  tool returned. The transcript cannot tell whether the model ever saw the unmasked output.
- The local CC version's Glob truncation is invisible to the text markers and only the structured flag catches it.
- The 10 KB question applies only to the HF table: the raw transcripts carry results up to 358,153 chars (codex).

## Implications for Phase B
- Use the raw-transcript IR and never the `conversations.parquet` content for any content or length check. The table caps
  1,552 results.
- Before any "claim vs tool output" comparison, gate on truncation per scaffold. Use the marker catalogue plus the
  structured flags (CC Glob `truncated`, OpenCode `metadata.truncated`). Exclude or separately label Gemini
  `<tool_output_masked>` results: 36.5% of Gemini results.
- Failure detection from text stays valid on truncated CC errors, because the exit line survives. Persisted (spilled)
  outputs show only about 2 KB. Claims about content beyond the preview cannot be checked against the transcript, which
  makes this a candidate fabrication surface: 65 results in 36 of 126 swechat CC sessions.
- Measure CC caps in UTF-16 units, not Python chars.
- aiv_cu and whowhen show no harness truncation, so their results can be treated as complete. The one aiv_cu output at
  exactly 135,168 chars stays unexplained (n = 1).

## Could not measure
- Whether Gemini models saw the full output before masking (no pre-mask copy in the data).
- The content of spilled files (`tool-results/*.txt`, OpenCode/Gemini/Copilot tool-output files are not in the IR).
- The cc_local Glob note wording (private; only its shape was counted).
- Failure-marker retention under spill / Codex / OpenCode truncation: no truncated failures in those types (n = 0).
- An aiv_cu output cap: one observation at the maximum.
