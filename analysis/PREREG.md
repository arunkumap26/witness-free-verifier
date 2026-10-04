# Phase B pre-registration

This file fixes, before any Phase B number exists, how the four Phase B probes are run, which units they run on, and
how results map to ALIVE / WEAK / DEAD. The machine-readable twin is `analysis/prereg.json`; Phase B scripts read it.
Where this file and the JSON differ, the JSON wins, and the difference is a bug to log in `change_log`.

**Files.**
- `analysis/probes/prereg_common.py` holds the frozen definitions (`SPEC`, every regex in `RX`) and the helper code
  that implements them: extraction, normalisation, error classes, the digit test and the change-point test. Phase B
  scripts import it. Before running, they must check that its sha256 equals `prereg.json provenance.spec_module_sha256`.
- `analysis/probes/prereg_calibration.py` (`PYTHONIOENCODING=utf-8 python -m analysis.probes.prereg_calibration`, about
  80 s) reads the split-A caches. It writes raw counts to `analysis/out/phase_a/prereg_calibration.json`, then writes
  `prereg.json` as SPEC plus `resolved` (the thresholds derived from A by the rules below) plus input hashes.

**What I read, and what I did not.** I used split A only (`*_A.parquet`), `analysis/out/phase_a*.json`, `PHASE_A.md`,
and the build reports. The build reports supplied B session counts only. No `*_B.parquet` was opened. No Phase C note or
output was read, because several Phase C lenses read split B (PHASE_A.md, consequence 6).

**What the calibration computed on A, and what it did not.** It computed only the inputs to thresholds and feasibility
counts:
- Probe 1: floors, IQRs, generation rates, and eligible-pair counts.
- Probe 2: extraction yields and access-path depths.
- Probe 3: call counts per session.
- Probe 4: token counts, plus the digit test on the machine control classes.

It did **not** compute any Phase B outcome on A. That excludes:
- the separability ratios r, fp_share and AUC;
- any sourced-versus-unsourced share;
- zero-error shares, retry rates and early/late differences;
- any digit test or round-number share of a model-typed class.

The verdict thresholds that are judgment calls are marked as such below. None of them was set by looking at an outcome.

Notation: `R:` = `prereg.json resolved.<path>`, `C:` = `prereg_calibration.json units.<unit>.<path>`,
`PA:` = `analysis/out/phase_a.json` or `PHASE_A.md`. Rates are k/n [95% CI]; s = sessions.

---

## 0. Global rules (`prereg.json global`, `data_rules`)

**B population** (`population_B`, session counts from the build reports):

| unit | B sessions | A sessions | notes |
|---|---|---|---|
| swechat/claude_code | 1,679 | 128 | |
| swechat/opencode | 214 | 25 | |
| swechat/codex | 77 | 19 | |
| swechat/gemini | 22 | 15 | label "small n" (< 30 B sessions) |
| swechat/cursor | 8 | 7 | no tool results in the source |
| swechat/copilot, swechat/simple_text | **0** | 2, 4 | NOT_TESTABLE in every probe |
| cc_local | 186 | 123 | aggregates only |
| aiv_cc | 189 runs | 125 runs | single-agent case study |
| aiv_cu | 2,000 | 200 | 10 model strata (`population_B.aiv_cu_by_stratum`) |
| whowhen | 111 (AG 78, HC 33) | 73 (AG 48, HC 25) | |

- **CIs.** Event rates use `stats.cluster_rate`, quantiles `stats.cluster_quantile`, and session shares `stats.wilson`.
  Statistics that lib/stats lacks (Spearman, AUC, w_adj, rate differences) use the same session resampling: 1,000 draws,
  seed 20261003. Undefined draws are skipped, and the CI is reported only if at least 900 draws are valid.
- **Zero counts.** When a rate's numerator is 0, the per-event and per-session Wilson upper bounds are reported as well,
  and a verdict uses the per-event Wilson upper bound in place of the degenerate [0, 0] bootstrap (resolution A2-3).
- **Minimum n.** A rate needs a denominator of at least 30 from at least 5 sessions. Five clusters is the smallest count
  with more than 100 distinct bootstrap resamples (126); A2-2 showed that a 2-cluster bootstrap is degenerate. A p50
  needs n ≥ 30, p5/p95 need n ≥ 100, and p1 needs n ≥ 500, each from ≥ 5 sessions (≥ 5 observations beyond the
  quantile). Below these, only raw k/n is reported, with the label INSUFFICIENT_N.
- **aiv_cc.** Every aiv_cc verdict carries the label "single-agent case study": 33,473/33,475 A results come from one
  SDK session (R:A4-3). Phase B also reports how many B runs share an sdk_session_id with an A run. Runs of one SDK
  session form one conversation, so for aiv_cc split B is not held out in content.
- **Verdict vocabulary.** ALIVE, WEAK, DEAD, INSUFFICIENT_N, NOT_TESTABLE, and (Probe 2 only) INCONCLUSIVE. No
  family-wise correction is applied: verdicts are descriptive per probe × unit, and each Phase B JSON reports how many
  verdict cells it computed.
- **Tool key.** The IR `tool` column, except:
  - `mcp__*` names keep their raw name, so aiv_cc Bash and `mcp__village__bash` stay apart;
  - Codex shell-family names and apply_patch keep their raw name, so `write_stdin` polls stay apart;
  - cc_local names are passed through `private_key()`.

  The tool classes are A1's, unchanged.
- **Output contract.** Phase B writes raw counts to `analysis/out/phase_b/<probe>.json` and copies the prereg.json
  sha256 into it. The verdict is computed mechanically from the rules here.

### Shared error definitions (`error_definitions`; used by Probe 3, and by Probe 2 for "first-try success")

| unit | primary error | A evidence (A4 and resolutions) | label |
|---|---|---|---|
| swechat/claude_code | native_error True, excluding permission-denied / interrupt-reject markers (reported as their own classes); null = not flagged | text proxy P 488/488, R 488/614 = 0.795 [0.720, 0.855], 90 s | usable |
| cc_local | same; permission denials kept apart from command failures | P 331/331, R 331/349 = 0.948 [0.900, 0.977], 74 s | usable |
| aiv_cc | same; the village-bash JSON `error` regex is a separate, unvalidated class | B: P 534/637, R 534/538 = 0.993 [0.977, 0.999], 38 runs | usable (native) |
| swechat/codex | native True; for shell results with null native, a nonzero `Exit code: N` / `Process exited with code N` in the first 600 chars | header: P 47/47, R 47/49 = 0.959 [0.823, 1.0]; positives from 6 s | usable, small n |
| swechat/opencode | native True (status=error or exit ≠ 0) | native fill 3,735/3,735 | usable (native only) |
| swechat/gemini | two classes never pooled into one rate: tool_failure = native True; command_failure = `Exit Code: N≠0`. Their union is used only as a session indicator | the classes never co-occur (0/280, 0/143) | native usable |
| aiv_cu | PROXY: stderr matches a nonzero bash returncode, a harness timeout or a census family | fires on 118/6,107 = 0.019 [0.013, 0.026]; no reference | proxy, caps verdicts at WEAK |
| whowhen | AG code_exec exit_code ≠ 0; HC has no signal | 36 nonzero of 87 exit codes; agreement tautological | AG only |
| cursor / simple_text | none | no results / no calls | DEAD |

---

## 1. Probe 1: latency physics (`prereg.json probe1`)

**Question.** Do work-bound tool latencies separate from generation time well enough that a tool result produced by
generation would stand out?

**Units.** Testable: swechat/claude_code, cc_local, aiv_cc, swechat/codex, swechat/opencode, swechat/gemini (the A1
gate). Not testable: aiv_cu (call and result share one stamp in 6,107/6,107 pairs), whowhen (no stamps), cursor (no
stamps, no results), simple_text, and copilot (0 B sessions). Phase B first re-applies the A1 kill rule to each unit's
B pairs; a unit that fails it in B is DEAD.

**No-human-wait filter** (the A1 proposed rule, now pre-registered). A pair qualifies only if all of these hold:
1. Both stamps exist.
2. The tool class is allowed for the unit:
   - CC formats, opencode and gemini: auto_read and internal_noperm;
   - aiv_cc: every class except human_interactive and subagent (bypassPermissions in 125/125 A runs);
   - codex: every tool except the subagent tools and `write_stdin`.
3. The call is the last (CC) or only (Gemini) call of its API message.
4. There is no rejection or permission marker, no Codex `declined`, no Gemini `cancelled`, and no Codex
   `unified_exec_running`.
5. There is no linked hook (a swechat CC `hook_progress` event, or a cc_local hook attachment).
6. For Codex, the most recent `approval_policy` is `never`.

What the filter keeps on A (C:probe1.filter_outcome):

| unit | kept | removed |
|---|---|---|
| swechat CC | 2,387 of 13,589 pairs | class 6,992; not the last call of its message 2,442; hook 1,767 |
| cc_local | 487 of 5,164 | |
| aiv_cc | 30,012 of 33,475 | 3,463 as not-last calls |
| codex | 1,070 of 1,120 | |
| opencode | 1,625 of 3,735 | |
| gemini | 360 of 2,313 | |

Shell, edit, write and web latencies in swechat CC and cc_local stay out, because they carry human waits:
- swechat CC edit/write calls over 2 s: 296/2,235 = 13.2% [6.8, 21.7];
- rejections in 19/126 s, p50 23.0 s;
- shell pre-exec offset over 2 s: 50/367.

**Per-tool statistics and the honest floor.** For each unit × tool_key, over qualified pairs:
- min, p1, p5, p10, p50, p95 and max, with cluster CIs;
- Spearman ρ of result bytes against latency, where there are ≥ 30 pairs from ≥ 5 sessions.

The honest floor is the p1/p5 of qualified deltas. The A values are in `R:probe1.floors`. Examples of A p5:

| unit | tool | A p5 (s) |
|---|---|---|
| swechat CC | read | 0.006 |
| swechat CC | grep | 0.015 |
| swechat CC | glob | 0.0231 |
| cc_local | read | 0.005 |
| cc_local | glob | 0.032 |
| opencode | read | 0.002 |
| gemini | read | 0.061 |
| codex | shell_command | 0.052 |
| aiv_cc | read | 0.0694 |
| aiv_cc | shell | 0.0849 |

**Floor transfer.** For each unit × tool_key with an A p5 and at least 100 B pairs, Phase B reports the share of B
qualified pairs below the A p5 (nominal 0.05). The floor TRANSFERS if that CI overlaps [0.025, 0.10], a factor of 2;
otherwise the label is FLOOR_SHIFT. aiv_cc deltas below 0.1 s are floor-bound, because every A tool starts near the
0.046 s pipeline minimum (R:A1-6). They stay in the floors and are counted separately; on A, 421 read and 337 shell
pairs fall below 0.1 s (C:aiv_cc.probe1.qualified_by_tool).

**Near-zero-variance kill.** A unit × tool_key with ≥ 30 qualified pairs from ≥ 5 sessions is FLAT if:
- its delta IQR is at most 2 × the stamp resolution (1 ms; 1 µs in aiv_cc; A1 gcd, R:probe1.stamp_resolution_check_A),
  **or**
- its IQR of log10 delta is below 0.05 (p75/p25 < 1.122).

The unit is DEAD if every reportable work-bound tool is FLAT. Reason: if latency is constant up to quantisation, it
carries no information about the work. The smallest A IQR(log10) among the work-bound tools is cc_local grep at 0.101
(n 35); the others range from 0.158 to 1.223 (R:probe1.iqr_log10).

**Mid-session floor step change.** Fixed method (`prereg_common.change_point`):
- **Series:** per session × tool_key, x = log10 delta of qualified pairs in seq order.
- **Eligibility:** n ≥ 40, so the minimum segment is 20 pairs on each side.
- **Statistic:** D* = max over split points k of |Q10(x[:k]) − Q10(x[k:])|. The split points form a grid with step
  max(1, n // 100).
- **Test:** 199 seeded permutations. A step is p ≤ 0.01 **and** D* ≥ log10 2 (a factor-2 floor shift).
- **Label:** the unit's floor is STABLE if at most 0.10 of eligible series step; otherwise UNSTABLE.

On A, the eligible series are few outside aiv_cc: swechat CC read 9, opencode read 7, codex shell_command 5, gemini
read 5 (C:probe1.qualified_by_tool.*.series_n_ge_40).

**Separability test.**
- **Work-bound set W:**
  - CC formats, opencode and gemini: qualified auto_read pairs;
  - aiv_cc: read, glob, grep, ls, Bash, edit, write;
  - codex: shell_command, exec_command, apply_patch, and the MCP filesystem reads.
- **Generation-bound set G:** subagent (Task/Agent/task), webfetch, websearch, and aiv_cc
  `mcp__village__search_history`, per unit as listed in `probe1.separability.generation_bound_set_G.per_unit`.
  - Codex has no usable G tool.
  - G latency is the tool-reported duration where the harness writes one (durationMs, durationSeconds,
    totalDurationMs). In swechat CC and cc_local, a webfetch or websearch pair without one is excluded.
  - Subagent runs that contain a human marker are excluded.
- **Generation-time model:**
  - result tokens = chars × 0.25;
  - T_gen = tokens / G90;
  - r = latency / T_gen;
  - only pairs with T_gen ≥ 1.0 s count.
- **Why these values:**
  - **0.25 tokens/char** is below every A5 Theil-Sen slope (OpenCode 0.263 is the smallest), so implied generation
    times err short. That makes fp_share conservative.
  - **1.0 s** sits just above the A1 auto_read p95: 0.938 s in swechat CC, 0.977 s in aiv_cc, 0.537 s in cc_local.
  - **G90** is the A-split 90th percentile of per-response output rates. Rate = output tokens / gap, where gap is the
    time from the last result or user event in the thread to the response's last call stamp. Responses count if they
    have ≥ 50 tokens and the gap is between 0 and 600 s. The fast end keeps fp_share conservative. Where per-response
    usage is a streaming partial (A median < 20 tokens), a char-based count is used instead.

| unit | method | G50 | **G90** (tok/s) | A rates (sessions) | A eligible W / G pairs |
|---|---|---|---|---|---|
| swechat/claude_code | usage | 37.1 | **65.3** | 5,795 (110) | 1,641 / 318 |
| cc_local | usage | 74.2 | **91.4** | 3,800 (107) | 328 / 41 |
| aiv_cc | chars (usage median 1.0 token per response) | 26.0 | **47.1** | 22,908 (55) | 3,744 / 176 |
| swechat/codex | usage | 46.3 | **76.5** | 651 (15) | 600 / 0 |
| swechat/opencode | usage | 33.4 | **62.5** | 2,688 (25) | 1,362 / 131 |
| swechat/gemini | usage | 25.5 | **94.3** | 1,998 (10) | 334 / 10 |

(R:probe1.generation_rate; C:probe1.eligible_T_gen_ge_1s.)

**Statistics.**
- fp_share = the share of eligible W pairs with r ≥ 1: a work-bound result that took at least as long as generating it
  would have.
- AUC = P(log r_G > log r_W).
- Minimum n: eligible W ≥ 100 pairs from ≥ 10 sessions; eligible G ≥ 30 pairs from ≥ 5 sessions.

**Verdict.**

| label | rule |
|---|---|
| fp | ALIVE if fp_share ≤ 0.05 and its CI hi ≤ 0.10; WEAK if ≤ 0.20; DEAD otherwise |
| auc | ALIVE if AUC ≥ 0.85 and its CI lo ≥ 0.75; WEAK if ≥ 0.70; DEAD otherwise; INSUFFICIENT_N if G is below min n |

- **Unit DEAD** if B fails the A1 kill rule, every W tool is FLAT, or either label is DEAD.
- **Unit ALIVE** if both labels are ALIVE.
- **WEAK** otherwise, including fp ALIVE without a G control.
- **Downgrade:** ALIVE becomes WEAK if the floor is UNSTABLE, or if FLOOR_SHIFT holds for most transfer-tested tools.

The thresholds 0.05/0.10/0.20 and 0.85/0.75/0.70 are judgment calls: a per-result flag needs a false-positive base rate
of about 5% or less to stay usable over hundreds of calls, and 0.85 is conventional "good" discrimination.

---

## 2. Probe 2: knowledge precedence (`prereg.json probe2`)

**Question.** How often does an honest agent use a path, symbol or config key before anything visible in its own record
could have told it? A low rate makes an unsourced reference, or a correct first-try deep access, a usable anomaly.

**Units.**
- Full: swechat/claude_code, codex, opencode, gemini, cc_local and whowhen.
- Antecedents incomplete (missing antecedents can only inflate "unsourced"):
  - aiv_cc: no prompt or memory in the IR, and earlier runs are other IR sessions;
  - aiv_cu: no prompt, memory or user text; GUI results carry no text;
  - cursor: no results.

  In these three units a low rate stays valid, but a DEAD result becomes INCONCLUSIVE.
- Not testable: copilot and simple_text.

**Streams.** References are evaluated per thread.
- The main thread's sources are main-thread events, including the results that subagents return to it.
- A subagent thread sees only its own events. Its nested prompt is the source `parent_prompt`.
- Subagents form a separate stratum with their own verdict.

**Extraction** (regexes are in `prereg.json regexes`):
- **Structured paths:** the args keys `file_path, filePath, path, absolute_path, notebook_path, dir_path, relative_path,
  target_directory, paths, file`, plus apply_patch `*** Update/Add/Delete File:` headers.
- **Free paths:** `path_abs_posix | path_windows | path_relative`, applied after URL masking, in shell commands, Codex
  `cmd`, and whowhen code and instructions. A free path is kept only if its last component has an extension (or is a
  dotfile), or it is absolute with ≥ 2 components.
- **Path normalisation:**
  - strip quotes and trailing punctuation, and a `:line:col` or `#L` suffix;
  - convert `\` to `/` and drop `./`;
  - replace redaction markers with `<R>`, and exclude any path that contains `<R>` (swechat CC A: 59);
  - lowercase drive paths.

  The match key is the last two components.
- **Symbols** (`sym_snake | sym_camel | sym_pascal`, length ≥ 5) come only from reference fields: `old_string` /
  `oldString`, MultiEdit `edits[].old_string`, and the `-` and context lines of apply_patch Update hunks. Shell commands
  form their own class. Search patterns are reported but feed no verdict, since searching for an unseen name is
  legitimate exploration.
- **Config keys:** `env_var` (UPPER_SNAKE, length ≥ 5); `cfg_key_line` in edits of config files
  (json/yaml/yml/toml/ini/cfg/conf/env/properties); and `git config` keys.
- **Excluded:** creation fields (`new_string`, Write `content`, patch `+` lines).

**Sourcing.** A first-mention reference is sourced if an earlier event of the same thread contains it. Each source type
is reported separately: result text and stderr, user text (whowhen: plus the AG task prompt), system text,
parent_prompt, and (whowhen only) peer agents' text.
- The agent's own assistant text, its thinking and its earlier call args are never a source.
- Paths match by key with path-character boundaries. Symbols match as whole words, case-sensitive.
- A path is also sourced by an earlier enumeration (glob, ls, grep, or a shell `ls`/`find`/`tree`/`fd`/`rg --files`/
  `git ls-files`) whose directory argument ends in the path's parent and whose result contains the basename.
- Known bias toward "unsourced": recursive listings that print a directory header apart from the entries are not
  matched. That bias makes ALIVE conservative.

**Deep first-try access.** This is the first access to a path key in a thread by a read tool, or by an edit tool that
requires an existing file (creation is excluded).
- **Depth:** components after the session's workspace root. The root is the longest common prefix of its absolute
  access paths (≥ 2 paths, ≥ 2 components), else the most frequent 3-component prefix.
- **Deep** = depth ≥ D_unit. D_unit = max(3, ceil(A p75)) when the unit has ≥ 50 A depths from ≥ 5 sessions; otherwise
  it takes the pooled value (pooled A p75 = 6 over 1,684 paths in 187 sessions). See R:probe2.depth_threshold.

  | unit | D | basis |
  |---|---|---|
  | swechat CC | 6 | A p75 6, n 1,052, 116 s |
  | opencode | 6 | 313 depths, 11 s |
  | gemini | 3 | p75 3, 204 depths, 10 s |
  | cc_local | 3 | p75 2, raised to the floor 3; 97 depths, 48 s |
  | aiv_cc | 6 | 2,241 depths, 32 s |
  | codex, whowhen, aiv_cu, cursor | 6 | pooled fallback |
- **First-try success:** the result is not an error under the unit's primary definition.
- **knowledge_from_nowhere** = deep AND first-try success AND unsourced AND not enumerated.

**Statistics.**
- **S_deep (primary):** the share of deep first-try successful main-thread accesses that are knowledge_from_nowhere,
  plus the session share with at least one. It needs ≥ 100 accesses from ≥ 20 sessions.
- **S_path_any:** the unsourced share of first-mention paths. It needs ≥ 200 from ≥ 20 sessions.
- S_symbol_ref and S_env_cfg are reported alongside.
- **Instrument check.** swechat CC main-thread S_symbol_ref must be ≤ 0.10. Claude Code refuses an Edit on a file not
  Read in the session, so old_string symbols should be in an earlier result. If the check fails, every Probe 2 verdict
  is capped at WEAK ("matching instrument suspect").

**Verdict** (per unit, main thread; the subagent stratum gets the same rule separately):
- ALIVE if S_deep ≤ 0.05 and its CI hi ≤ 0.10;
- WEAK if S_deep ≤ 0.20;
- DEAD if S_deep > 0.20;
- if S_deep is INSUFFICIENT_N, the same rule is applied to S_path_any, capped at WEAK.

Caps:
- antecedents_incomplete units: DEAD becomes INCONCLUSIVE;
- aiv_cu: WEAK (proxy success);
- instrument failure: WEAK.

The thresholds are judgment calls, the same budget logic as Probe 1. No unsourced share was computed on A.

---

## 3. Probe 3: pushback (`prereg.json probe3`)

**Question.** Does honest work meet friction often enough that a long session with no errors is anomalous? And do agents
react to a failure (retry) more than to a success?

**Units.**
- Testable: swechat/claude_code, cc_local, aiv_cc, codex, opencode, gemini, aiv_cu (proxy) and whowhen AG.
- DEAD: cursor, simple_text, whowhen HC.
- Not testable: copilot.

**Long session.** A session is long if its paired calls (all threads) number at least L75, the A-split 75th percentile
for the unit. L90 is the secondary cut (R:probe3.long_session):

| unit | L75 | L90 | A sessions |
|---|---|---|---|
| swechat/claude_code | 134 | 220 | 126 |
| cc_local | 20 | 46 | 107 |
| aiv_cc | 666 | 1,559 | 77 |
| swechat/codex | 120 | 184 | 15 |
| swechat/opencode | 185 | 425 | 25 |
| swechat/gemini | 405 | 548 | 10 |
| aiv_cu | 40 | 41 | 199 (L75 ≈ L90: A sessions cluster at about 40 turns) |
| whowhen AG | 3 | 4 | 39 (code_exec calls only) |

**Zero-error tail (primary).** Z = the share of long sessions with no primary error (Wilson). Phase B also reports:
- the expected share under independence, E0 = mean over long sessions of (1 − p)^n_s, where p is the unit's pooled B
  per-call error rate;
- Z / E0;
- Z at L90, and Z per error class.

**Retry (secondary).** Take consecutive calls of the same thread. The next call is a retry if it has the same tool_key
and either identical args or a Jaccard ≥ 0.5 over lowercased `[A-Za-z0-9_./-]+` tokens (the shell command, or else all
arg values).
- R_fail = P(retry | previous call failed); R_ok = P(retry | previous call succeeded). The effect is R_fail − R_ok, with
  a session-resampled CI.
- Permission and interrupt rows are reported apart.

**Early versus late.** For sessions with ≥ 20 calls, calls are split at floor(n/2) by seq. Phase B reports the late
error rate minus the early error rate (paired session resampling), and the share of sessions with errors early but
none late. This part is descriptive, with no verdict.

**Verdict.**
- **Zero-error tail:** ALIVE if Z ≤ 0.10, its Wilson hi ≤ 0.20, and there are ≥ 30 long sessions; WEAK if Z ≤ 0.30;
  DEAD if Z > 0.30. Fewer than 20 long sessions gives INSUFFICIENT_N.
- **Reaction:** ALIVE if the effect's CI lo ≥ 0.10; WEAK if CI lo > 0; DEAD otherwise. It needs ≥ 30 failed calls with
  a successor from ≥ 10 sessions.
- **Caps:** aiv_cu is capped at WEAK (proxy). aiv_cc carries the single-agent label. Gemini uses the union indicator,
  labelled as such.

These thresholds are judgment calls. For context only, the A per-call native error counts were 614/13,592 (swechat CC),
349/5,164 (cc_local) and 538/33,475 (aiv_cc). At L75 call counts, an independent-error model predicts almost no
zero-error long sessions, so Z mainly measures how errors clump across sessions.

---

## 4. Probe 4: entropy (`prereg.json probe4`)

**Question.** Is model-typed hex, or a model-typed number or timestamp, distinguishable from machine-produced values in
honest logs? If so, a model-written fake tool result would carry that signature.

**Hex tokens.**
- Before matching, UUIDs are masked and counted apart.
- Any token inside a non-whitespace run containing `REDACTED` is dropped and counted (A: 9 in swechat CC, 1 in aiv_cu).
- A token matches `hex_token` if it is all lowercase or all uppercase hex, not preceded by `#`, and not inside `0x`.
- Its length must be in {7, 8, 32, 40, 64}, with ≥ 1 digit and ≥ 1 letter.
- Five well-known constants are excluded (the empty tree and empty blob hashes, and the md5, sha1 and sha256 of the empty
  string).

**Classes.**

| class | contents |
|---|---|
| M_git (machine control) | capture groups of `git_hash_lines` in results of shell calls matching `git_cmd`: commit headers, oneline/graph, `[branch sha]`, `index a..b`, `HEAD is now at`, push ranges |
| M_all | all result text and stderr |
| T_copy / T_orig | args tokens that are / are not equal to (or a prefix of) a token seen earlier in the session's result, user or system text |
| A_copy / A_orig | the same split for assistant text |

Tokens are deduplicated per unit × class; the first occurrence assigns the session.

**Digit test.**
- Expected counts follow uniform hex conditioned on the ≥ 1 digit / ≥ 1 letter filter, computed exactly per length.
- Pearson χ² with df = 15.
- Effect size: w_adj = √max(0, (χ² − 15)/N), with a session-bootstrap CI.
- **N_min = 1,131 symbols:** the power calculation for w = 0.15 at α = 0.01 with power 0.80 (R:probe4.N_min).

**Instrument check.** The control is M_git, or M_all when M_git has fewer than N_min symbols. It must have its w_adj CI
hi ≤ 0.15, the effect size behind N_min. A-split controls (R:probe4.control_A; symbols, w_adj, CI hi):

| unit | M_git | M_all |
|---|---|---|
| swechat CC | 11,501; 0.000; **0.055** | 24,814; 0.027; 0.099 |
| opencode | 2,924; 0.000; 0.107 | 10,008; 0.000; 0.068 |
| aiv_cc | 6,562; 0.009; 0.081 | 22,732; 0.000; 0.040 |
| aiv_cu | 3,617; 0.030; 0.121 | 12,996; 0.080; 0.171 |
| codex | 1,704; 0.000; 0.160 | 1,962; 0.000; 0.139 |
| cc_local | 56 (below N_min) | 10,817; 0.015; 0.111 |
| gemini | 784 (below N_min) | 1,049 (below N_min) |
| whowhen | 0 | 2,147; 0.065; 0.161 |

**Verdict (hex, primary).** Let h be the control's w_adj CI hi.
- INSUFFICIENT_N if T_orig or the control has fewer than N_min symbols.
- DEAD (instrument) if the control fails the instrument check.
- ALIVE if T_orig w_adj ≥ 0.15 and its CI lo > h.
- WEAK if T_orig w_adj > h but the ALIVE condition fails.
- DEAD if T_orig w_adj ≤ h: model-originated hex is as uniform as machine hex.
- For swechat, the verdict stands only if a rerun on events with no `REDACTED` at all gives the same label; otherwise
  WEAK.
- Pooled cells `swechat/*` and `public/*` (everything except cc_local) are pre-registered too. They carry the label
  "pooled" and never replace a unit verdict.

**Numbers and timestamps (secondary).**
- `large_int`: 5 to 19 digits, no leading zero, not part of a decimal or identifier, excluding epochs.
- The round-number metrics are the shares with last digit 0, last two digits 00, last three digits 000, and last digit
  0 or 5. Under uniform last digits they would be 0.1, 0.01, 0.001 and 0.2.
- Machine output is already rounder than uniform. The A M_all last-0 shares run from 0.111 [0.102, 0.122] (aiv_cc,
  2,942 values) to 0.316 [0.119, 0.409] (whowhen, 171 values); swechat CC is 0.140 [0.119, 0.161] (1,676 values).
  So the comparison is against M_all, not against 0.1.
- **Round-number verdict:** ALIVE if the T_orig last-0 share's CI lo exceeds M_all's CI hi + 0.05; WEAK if the T_orig
  point exceeds M_all's CI hi; DEAD otherwise. Each class needs ≥ 100 distinct values from ≥ 10 sessions.
- Timestamps (ISO, epoch_s, epoch_ms) are reported with their uniform expectations (1/60, 0.1, 0.001). They feed no
  verdict.

---

## 5. Nulls announced in advance: the feasibility projection

`R:feasibility_projection` scales each A count by the unit's B/A session ratio. It is a projection, not a measurement,
and sets no threshold. Where the projection falls below a minimum n, Phase B will most likely report INSUFFICIENT_N.
That would be a result of the data, not of the analysis.

- **Probe 4 hex is likely testable only in aiv_cu and opencode.**

  | unit | T_orig symbols, A | projected B |
  |---|---|---|
  | aiv_cu | 2,680 | 26,800 |
  | opencode | 160 | 1,370 |
  | swechat CC | 71 | 931 |
  | aiv_cc | 217 | 328 |
  | cc_local | 79 | 120 |
  | codex, gemini, whowhen | 0 | 0 |

  N_min is 1,131. Models type almost no unsourced hex in these logs, and that scarcity is itself a finding. The pooled
  `swechat/*` cell exists for this reason.
- **Probe 3 long sessions:** gemini 3 → 4.4 and codex 4 → 16.2 projected, both below the minimum of 20, so likely
  INSUFFICIENT_N. whowhen AG 15 → 24.4 is close to the minimum.
- **Probe 1 positive control (G):** gemini 10 → 14.7 and codex 0. Their separability can reach WEAK at most.
- **Probe 2 S_deep:** cc_local 11 → 16.6, codex 10 → 40.5, aiv_cu 0, whowhen 0. These units fall back to S_path_any
  (capped at WEAK) or are INSUFFICIENT_N.

## 6. Drafting notes (rule revisions made before any B data; `prereg.json drafting_notes`)

1. **Probe 2 depth: a pooled D became per-unit D with a pooled fallback.** The A depth histograms differ by scaffold. A
   pooled D = 6 would leave "deep" nearly empty for Gemini (5 of 204 A paths) and cc_local (6 of 97). No Probe 2 outcome
   had been computed.
2. **Probe 4 instrument ceiling: 0.10 became 0.15, tied to the control's CI hi.** For a perfectly uniform control of
   N_min symbols, the bootstrap hi of w_adj is about √((χ²₀.₉₇₅,₁₅ − 15)/N_min) = 0.105. A 0.10 ceiling would therefore
   fail sound controls by chance. No model-typed class had been tested.
3. Two clauses were added at the same stage: the pooled Probe 4 cells, and INSUFFICIENT_N when the control is smaller
   than N_min.

## 7. Known limitations (decided now, not discovered later)

- **aiv_cc is one agent.** Every aiv_cc result generalises to that agent and harness only.
- **swechat CC and cc_local shell/edit/web latencies stay out of Probe 1** until `permissionMode` is carried into the IR.
  That needs a loader change, decided by day.
- **The tool-result token counts in Probe 1 are inferred** (chars × 0.25). No corpus counts tool-result tokens apart
  (A5 headline).
- **Probe 2 antecedents exclude content outside the record:** the CC system prompt, the cwd, spilled outputs, and
  Gemini-masked results (840/2,313 masked in A). So "unsourced" is an upper bound everywhere.
- **Probe 4 redaction can bias the surviving hex.** The SWE-chat release redacted high-entropy strings, which can bias
  what survives toward lower entropy. The redaction-free rerun is the check.
- **Truncation.** Claims about content beyond a spilled preview cannot be checked (A3), and Probe 2 does not try.

## 8. Change log

Empty at commit. Any later change goes to `prereg.json change_log` with before, after and the reason (README rule 3).
