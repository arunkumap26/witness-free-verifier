# Probe 1 (Phase B): latency physics

**Data:** `analysis/out/probe_1.json`, written by `analysis/probes/probe_1.py` (B split only). A byte-identical copy
is at `analysis/out/phase_b/probe_1.json`.

**Pre-registration:** sha256 of `prereg_common.py` on disk equals `prereg.json provenance.spec_module_sha256`
(`prereg.spec_module_sha_ok`). The no-human-wait filter and the G-latency rule come from `prereg_calibration.py`,
imported unchanged. That is the code that produced the A-split floors, and its sha256 matches as well. Thresholds come
only from `prereg.json`, and each one is asserted against the prereg text at start-up (`thresholds_used`,
`threshold_sources`).

**Conventions:** k/n = rate [95% session-clustered CI]; W[...] = Wilson; s = sessions (aiv_cc: runs); r = latency /
T_gen. Sections 1–7 report data. Section 8 is **interpretation**. Every number cited is in the JSON, and its path is
given where it is not obvious.

**Labels:**
- aiv_cc is a **single-agent case study**. 156 of its 189 B runs share an SDK session with an A run, and one SDK
  session holds 155 B runs (`aiv_cc_split_overlap`), so B is not held out in content for aiv_cc.
- swechat/gemini has 22 B sessions, so it carries the label **small n**.
- cc_local is private: only aggregates are reported, and its session ids are replaced by indices.

## 1. Verdicts (mechanical, `verdicts`)

| unit | verdict | fp_share (W eligible, r ≥ 1) | AUC (G vs W) | floor step | rule applied |
|---|---|---|---|---|---|
| swechat/claude_code | **WEAK** | 72/20,937 = 0.0034 [0.0025, 0.0044], 1,042 s → ALIVE | 0.987 [0.980, 0.993] → ALIVE | **UNSTABLE** 21/156 | ALIVE, then downgraded because the floor is UNSTABLE |
| swechat/opencode | **ALIVE** | 7/4,419 = 0.0016 [0, 0.0033], 208 s | 0.999 [0.998, 1.000] | STABLE 0/15 | fp and auc both ALIVE |
| cc_local | **ALIVE** | 1/1,019 = 0.0010 [0, 0.0033], 112 s | 0.919 [0.881, 0.971] | STABLE 0/5 | fp and auc both ALIVE |
| aiv_cc (single agent) | **WEAK** | 241/3,217 = 0.075 [0.040, 0.119], 43 runs → WEAK | 0.865 [0.762, 0.922] → ALIVE | STABLE 8/134 | fp WEAK |
| swechat/codex | **WEAK** | 270/4,329 = 0.062 [0.026, 0.118], 57 s → WEAK | INSUFFICIENT_N (no G tool) | STABLE 0/33 | fp WEAK, no positive control |
| swechat/gemini (small n) | **WEAK** | 0/295, 16 s; per-event Wilson hi 0.0129 → ALIVE | INSUFFICIENT_N (G 13 pairs from 5 s, below 30) | STABLE 0/4 | fp ALIVE without a positive control |
| aiv_cu, whowhen, swechat/cursor | NOT_TESTABLE | killed in A1; the A1 rule fails on B too (section 2) | | | |
| swechat/copilot, swechat/simple_text | NOT_TESTABLE | 0 B sessions | | | |

The JSON counts its verdict cells under `verdict_cells`: 11 unit verdicts (6 testable, 5 not testable), 6 fp labels and
4 AUC labels.

**Kill criteria.** No kill fired in any testable unit.
- **A1 kill rule:** all six testable units pass on B.
- **FLAT (near-zero variance):** no reportable W tool_key is FLAT in any unit.

For the not-testable units, re-applying the A1 rule to B kills them again:
- **aiv_cu:** 59,956 of 59,956 pairs share one stamp, in 1,979 sessions.
- **whowhen:** 0 of 535 pairs carry stamps; 111 B sessions.
- **cursor:** 0 pairs; 8 B sessions.

## 2. A1 kill rule, re-applied to B pairs (`units.<u>.a1_recheck_B`)

| unit | pairs with both stamps (s) | identical stamps | whole-second stamps (call+result pooled) | gcd of nonzero \|Δ\| |
|---|---|---|---|---|
| swechat/claude_code | 194,366 (1,648) | 897 = 0.0046 [0.0033, 0.0064] | 389/388,732 = 0.0010 | 1,000 µs |
| swechat/opencode | 8,194 (212) | 37 = 0.0045 [0.0013, 0.0099] | 11/16,388 | 1,000 µs |
| swechat/codex | 9,727 (63) | 1 | 20/19,454 | 1,000 µs |
| swechat/gemini | 1,776 (21) | 9 = 0.0051 [0.0012, 0.0171] | 8/3,552 | 1,000 µs |
| cc_local | 36,542 (174) | 1 | 86/73,084 | 1,000 µs |
| aiv_cc | 38,738 (119) | 0 | 0/77,476 | 1 µs |

Every share is far below the 0.5 kill line. No unit gets a `mixed_flag`, so no share falls in (0.01, 0.5]. The stamp
resolution matches A: 1 ms in every ms-stamped format and 1 µs in aiv_cc.

## 3. The honest floor (qualified pairs, Δ > 0; `units.<u>.qualified_by_tool`, `qualified_by_class_dist`)

Seconds. CIs are session-clustered. "IN" means the value is withheld under the min-n rule (p1 needs n ≥ 500).

| unit | tool | n (s) | min | p1 | p5 | p50 | p95 |
|---|---|---|---|---|---|---|---|
| swechat CC | read | 17,543 (1,071) | 0.001 | 0.002 [0.001, 0.002] | 0.003 [0.003, 0.003] | 0.022 | 0.449 |
| swechat CC | grep | 7,267 (753) | 0.001 | 0.005 [0.004, 0.007] | 0.010 [0.009, 0.013] | 0.101 | 0.787 |
| swechat CC | glob | 1,829 (612) | 0.001 | 0.002 [0.001, 0.0056] | 0.013 [0.010, 0.020] | 0.330 | 2.269 |
| opencode | read | 3,740 (208) | 0.001 | 0.001 [0.001, 0.001] | 0.002 [0.002, 0.002] | 0.005 | 0.017 |
| opencode | grep | 867 (151) | 0.001 | 0.001 [0.001, 0.004] | 0.0053 [0.004, 0.006] | 0.017 | 0.036 |
| cc_local | read | 1,302 (96) | 0.003 | 0.004 [0.003, 0.005] | 0.005 [0.004, 0.006] | 0.008 | 0.149 |
| cc_local | glob | 459 (100) | 0.029 | IN | 0.032 [0.031, 0.033] | 0.042 | 1.131 |
| gemini | read | 303 (16) | 0.002 | IN | 0.054 [0.013, 0.061] | 0.096 | 0.188 |
| codex | mcp read_text_file | 120 (14) | 0.003 | IN | 0.018 [0.010, 0.024] | 0.1595 | 0.973 |
| codex | shell_command | 1,631 (22) | 0.037 | 0.050 [0.040, 0.149] | 0.156 [0.056, 0.161] | 0.447 | 15.96 |
| codex | exec_command | 3,502 (34) | 0.004 | 0.267 [0.254, 0.316] | 0.329 [0.292, 0.438] | 0.829 | 2.034 |
| aiv_cc | read | 2,840 (47) | 0.0497 | 0.058 [0.055, 0.062] | 0.068 [0.063, 0.078] | 0.1405 | 0.741 |
| aiv_cc | shell (Bash) | 3,913 (47) | 0.0486 | 0.065 [0.063, 0.073] | 0.084 [0.074, 0.101] | 0.614 | 4.829 |
| aiv_cc | mcp__village__get_events | 17,304 (113) | 0.0527 | 0.236 [0.231, 0.240] | 0.2566 [0.2536, 0.2625] | 0.379 | 0.847 |

The p1 per tool class is the key statistic of the brief:
- swechat CC auto_read: p1 0.002 [0.002, 0.002] (n 26,639, 1,103 s).
- opencode auto_read: 0.001 [0.001, 0.001].
- cc_local auto_read: 0.004 [0.003, 0.005].
- aiv_cc auto_read: 0.056 [0.053, 0.060]; aiv_cc shell 0.065 [0.063, 0.073].

The full log histograms (4 bins per decade) sit under `log_histogram_s` for every tool and class. The unfiltered "all
pairs" distributions are under `all_pairs_by_tool` and `all_pairs_by_class`, marked `human_wait_contaminated` where
the filter excludes the class.

**Variance (FLAT test, `flat_test`).** The smallest IQR(log10 Δ) among reportable W tool_keys is cc_local grep
(0.078, n 56). Next come aiv_cc glob (0.139) and grep (0.145). The threshold is 0.05. Two tools are FLAT, both outside
W: opencode todo and cc_local toolsearch, each with an IQR of 0.002 s, at most 2 ms.

## 4. Result size against latency (Spearman ρ, bytes vs Δ, `spearman_bytes_latency`)

| group | ρ [CI] |
|---|---|
| swechat CC auto_read (qualified) | −0.139 [−0.173, −0.105] |
| opencode auto_read | −0.304 [−0.336, −0.265] |
| cc_local auto_read | 0.365 [−0.002, 0.614] |
| aiv_cc auto_read | −0.528 [−0.638, −0.387] |
| aiv_cc shell | −0.024 [−0.093, 0.076] |
| gemini auto_read | −0.034 [−0.282, 0.365] |
| W eligible, swechat CC (`separability.W_spearman_bytes_latency`) | −0.013 [−0.051, 0.023] |
| G eligible, swechat CC (`G_spearman_bytes_latency`) | 0.496 [0.421, 0.570] |
| G eligible, cc_local | 0.695 [0.533, 0.805] |
| G eligible, aiv_cc | 0.751 [0.644, 0.940] |
| G eligible, opencode | −0.048 [−0.263, 0.311] |

## 5. Floor transfer, A p5 → B (`floor_transfer`)

Every tested tool_key transfers in opencode (3/3), cc_local (2/2), gemini (1/1), codex (1/1) and aiv_cc (14/14).

swechat CC has 2 FLOOR_SHIFT keys of 4 tested, which is not a majority, so it does not trigger the downgrade:
- **read:** 2,153/17,543 = 0.123 [0.105, 0.144] of B pairs fall below the A p5 of 0.006 s, so the B floor is lower.
- **taskupdate:** 0/2,570 fall below the A p5 of 0.001 s. This is a **quantisation artifact**: the A p5 equals the
  1 ms stamp resolution, and no positive ms-stamped delta can be below it. Excluding it, the shift is 1 of 3
  (`sensitivity_excluding_A_p5_at_stamp_resolution`).

## 6. Mid-session floor step changes (`floor_step_change`)

| unit | eligible series (s) | steps | sessions with a step | label |
|---|---|---|---|---|
| swechat/claude_code | 156 (114) | **21** = 0.135 W[0.090, 0.197] | 18 | **UNSTABLE** (> 0.10) |
| aiv_cc | 134 (46) | 8 = 0.060 W[0.031, 0.113] | 7 | STABLE |
| swechat/codex | 33 (30) | 0 | 0 | STABLE |
| swechat/opencode | 15 (10) | 0 | 0 | STABLE |
| cc_local | 5 (4) | 0 | 0 | STABLE |
| swechat/gemini | 4 (4) | 0 | 0 | STABLE |

**swechat CC steps:**
- By tool: read 16 of 110 series, grep 3 of 38, glob 1 of 2, todo 1 of 4.
- Direction: 18 steps go up and 3 go down. The step factor has a median of 3.39 and a maximum of 35.4; 6 steps are at
  least 10×.
- In the largest steps, the read floor (Q10) rises from 0.002–0.007 s to 0.07–0.25 s partway through a session
  (series list, `Q10_left_s` / `Q10_right_s`).
- One step sits at p = 0.01, the boundary. Without it the share is 0.128, still UNSTABLE
  (`sensitivity_steps_at_p_boundary`).

**aiv_cc:** all 8 steps are in runs of one SDK session (ids beginning `0a15c7c2`). The factors run from 3.0 to 61.2.

## 7. Separability (`separability`)

| unit | G90 (G50) tok/s from A | result chars for T_gen = 1 s | W all → eligible (s) | median log10 r, W | G eligible (s) | G by tool: median r (r ≥ 1 / n) |
|---|---|---|---|---|---|---|
| swechat CC | 65.3 (37.1) | 261 | 26,639 → 20,937 (1,042) | −2.44 [−2.52, −2.36] | 3,812 (903) | subagent 2.62 (2,863/3,319); webfetch 0.976 (151/335); websearch 0.676 (33/158) |
| opencode | 62.5 (33.4) | 250 | 5,113 → 4,419 (208) | −3.53 [−3.61, −3.45] | 127 (12) | subagent 22.1 (116/116); websearch 0.046 (0/11) |
| cc_local | 91.4 (74.2) | 365 | 1,817 → 1,019 (112) | −2.76 [−2.94, −2.54] | 153 (12) | webfetch 1.39 (43/47); websearch 0.855 (6/53); workflow 0.0069 (0/47); subagent 0.0064 (0/6) |
| aiv_cc | 47.1 (26.0) | 189 | 7,423 → 3,217 (43) | −0.81 [−0.94, −0.63] | 178 (25) | search_history 0.720 (42/160); webfetch 0.658 (1/14); websearch 0.881 (0/4) |
| codex | 76.5 (46.3) | 306 | 5,949 → 4,329 (57) | −1.20 [−1.31, −1.11] | 0 | none |
| gemini | 94.3 (25.5) | 377 | 321 → 295 (16) | −1.38 [−1.87, −1.29] | 13 (5) | websearch 1.65 (10/13) |

**Where r ≥ 1 occurs among honest W** (`W_eligible_r_ge_1_by_tool`):
- swechat CC: glob 27/873, grep 25/3,799, read 20/16,265.
- aiv_cc: shell 241/2,785, and 0 for read (325), grep (87) and glob (17).
- codex: shell_command 183/1,227, exec_command 87/2,927, and 0 for the reads and apply_patch.
- opencode: read 6/3,658, glob 1/119.

**G exclusions:**
- swechat CC: 1,163 webfetch/websearch pairs lack a tool-reported duration and are excluded, along with 57 rejected
  pairs and 5 with a nested human marker.
- cc_local: 1,082 lack a duration.
- opencode: the cross-session check finds 0 rejection markers and 0 human-interactive calls among 8,352
  subagent-thread rows, so the CC-only nested exclusion removes nothing there (`G_nested_exclusion_crosscheck`).

## 8. Interpretation (not data)

**What survives: work-bound reads are far faster than generation.**
- Auto-approved reads, globs and greps return their results orders of magnitude faster than a model could generate
  the same text. The median log10 r is −2.44 in swechat CC, −3.53 in OpenCode and −2.76 in cc_local, against a bound
  of 0.
- The honest exceedance rate (fp_share) is 0.0034 (CC), 0.0016 (OpenCode) and 0.0010 (cc_local), well inside the
  0.05 budget.
- So a read-type result that the model wrote inline, taking at least T_gen, would sit in a tail that honest reads
  almost never reach. The floor itself is in single-digit milliseconds for CC, OpenCode and cc_local reads, as the
  brief expected.

**The floors are not universal.**
- **Harness floors:** Gemini read sits near 50 ms (p5 0.054), and aiv_cc tools do too. The aiv_cc minimum is 0.0497 s
  for read, 0.0486 s for shell and 0.0476 s for computer_use, so its lowest is 0.0476 s. That is a pipeline floor
  rather than work.
- **Codex exec_command:** its p1 is 0.267 s, against 0.050 s for shell_command. This looks like a harness wait (a
  yield window), not work. That is an inference; the cause was not measured.
- **Consequence:** a floor must be calibrated per harness × tool. A floor carried across harnesses would mislabel one
  of them.

**Generation-bound tools rise with output size; work-bound tools do not.** In G, latency grows with output bytes
(ρ 0.50 to 0.75 in swechat CC, cc_local and aiv_cc). In W it is flat or negative. That is the physical signature the
hypothesis predicts: generation time scales with the text produced, and a file read does not.

**Where it fails: compute-bound tools.**
- Shell commands that run long and print little exceed their own generation time honestly: aiv_cc shell 241/2,785,
  codex shell_command 183/1,227. That pushes aiv_cc and codex to WEAK.
- Latency cannot tell a fabricated `pytest` result from a real slow one.
- For the CC formats, shell, edit and write were **not tested** at all, because the filter excludes human waits. The
  ALIVE verdicts for CC formats cover only read-type tools.

**The positive control is weaker than the AUCs suggest.**
- The AUCs (0.865 to 0.999) are high mainly because W is so low. The G tools themselves often have r below 1:
  - CC webfetch median 0.976 and websearch 0.676;
  - cc_local workflow and subagent about 0.007;
  - aiv_cc search_history 0.720.
- Under this model, several "generation-bound" tools produce text faster than G90 implies. Server-side summarisers run
  on other models, and tool output is not all generated.
- G90 is the fast end by design, the A-split 90th percentile of response rates, so faster responses exist. A
  fabricator generating faster than G90, using a smaller model or emitting short text, can land below r = 1.
- The bound is therefore a one-sided check. r ≪ 1 certifies that a result was not generated inline. r ≥ 1 says
  nothing. The miss rate against real fabrication is not measured here, because there are no fabricated pairs.
- Coverage is partial. Only results long enough for T_gen ≥ 1 s are testable: 20,937 of 26,639 W pairs in swechat CC
  and 3,217 of 7,423 in aiv_cc. Short results cannot be separated by construction.

**Floor instability in swechat CC is real and large.**
- In 18 of 114 eligible sessions, the read/grep/glob floor shifts at least 2× mid-session. It mostly rises, by up to
  35.4×.
- A detector that learns a session's floor early, and treats later sub-floor latencies as suspicious, would misfire in
  the opposite direction after a downward step (3 of 21).
- The cause is not identified. Candidates are an unlogged hook, a filesystem change, or a client update during the
  session.
- B reads are also faster than the A floor (FLOOR_SHIFT, read). The prereg's downgrade (ALIVE → WEAK) is applied as
  written.

**Threat model caveat.** This mechanism can only catch a model that fabricates a tool result inline: it writes the
result text itself, so the result's latency includes its own generation time. Several attacks defeat it:
- A replaced or compromised execution layer emits fabricated results at program speed, with r ≪ 1, exactly like honest
  reads.
- A harness can pad latency.
- A fabricated result shorter than 189–377 characters, the T_gen = 1 s threshold by unit, is not testable.

Latency physics therefore constrains *who* produced a result (the model's decoder or something else). It cannot tell
whether the producer was honest.

**Nulls, with the same prominence:**
- **swechat/codex:** no generation-bound control exists (G = 0), so the AUC cannot be tested.
- **gemini:** G has only 13 pairs, below the minimum of 30.
- **aiv_cu:** dead again on B; every one of its 59,956 pairs shares a stamp.
- **whowhen:** dead again on B; 0 of its 535 pairs are stamped.
- **cursor:** no pairs.
- **copilot and simple_text:** absent from B.

**Deviations from the prereg text** are listed in `deviations` (6 items). None changes a verdict. The items are: the
output path; zero deltas excluded as on A; the change-point seed index over eligible series; the transfer test also
requiring 5 sessions; no vacuous FLAT kill; and the nested-G exclusion applied in CC formats only.
