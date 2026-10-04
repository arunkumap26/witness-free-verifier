# commit_witness: git as an existing second witness (Phase C lens)

- Script: `analysis/probes/phase_c_commit_witness.py` (run: `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_commit_witness`)
- Data: `analysis/out/phase_c/commit_witness.json` (raw counts, CIs, the pre-registered rules in `prereg`, and every
  post-run change in `changes_after_first_run`)
- Corpus: `data/swe-chat-pinned` only. `claude-code-local` and the superseded mirror were not used.

Part A holds numbers copied from the JSON, with the JSON path. Part B is interpretation. Rates are given as
`rate [95% CI] num/den`. CIs are session-clustered bootstrap (`lib/stats.py`) unless the line says Wilson or
repo-clustered.

---------------------------------------------------------------------------------------------------------------------

## Part A: Numbers

### Setup (`sample`, `q1`)
- Population: 5,850 sessions with a transcript file. By sniffed content format: claude_code 4,922, opencode 624,
  codex 213, gemini 58, other 31, copilot 2 (`q1.format_counts`).
- Commit table: 14,459 rows. 9,254 are `ok` (7,447 unique SHAs). 5,205 are `commit_not_found`, which have no SHA and no
  patch (`q1.commit_rows`).
- The two foreign-key lists disagree for 57 sessions (`sessions.checkpoint_ids` vs `checkpoints.session_pks`). I used their union.
- Sample: 1,200 sessions, seeded, drawn from 3,412 eligible sessions (claude_code format with ≥1 linked `ok` commit).
  - Strata: Claude Code 1,166, unknown 20, Agent 11, Gemini CLI 3.
  - 140 distinct repos. The largest repo contributes 192 sessions.
  - 2,102 transcripts were parsed for Q2–Q4. The global key pass parsed all 4,922 claude_code transcripts.
- Transcript-side comparisons (Q2–Q4) cover Claude Code JSONL only.

### Q1. Linkage coverage and time order
- Sessions with ≥1 linked `ok` commit: 0.698 [0.686, 0.710] 4,085/5,850 (Wilson) (`q1.coverage_all`).
  - By format (`q1.coverage_by_format`):
    - claude_code 0.693 [0.680, 0.706] 3,412/4,922
    - opencode 0.809 [0.777, 0.838] 505/624
    - codex 0.479 [0.413, 0.546] 102/213
    - gemini 0.707 [0.580, 0.808] 41/58
  - Every session has ≥1 checkpoint. The remaining 0.302 [0.290, 0.314] 1,765/5,850 link only to `commit_not_found` checkpoints.
- `ok` commits per linked session: median 1, p75 3, p95 10, max 234 (n = 4,085; quantiles only, no CI).
- Time order from the transcripts (`q1.time_order_transcript_sample`). 4,580 (session, commit) pairs in 1,200 sessions:
  - 2,105 fall within the transcript's event span, 2,442 after the last event, 33 before the first event.
  - Lag after the last event: median 5.415 h [3.292, 10.978], p90 120.064 h [54.264, 292.574] (2,442 pairs, 814 sessions).
  - commit_date ≠ author_date in 366 of 4,580 pairs.
- `sessions.created_at` is later than the transcript's first event in 1,200/1,200 sampled sessions.
  - Median gap 0.797 h [0.655, 0.910]; p95 56.074 h.
  - Because of this, the metadata-based population time order (`q1.time_order_metadata_population`: 6,998 of 13,424 pairs "before_start") is not a valid time order.

### Q2. Corroboration of Edit/Write calls by linked commits (`q2`)
- Denominator: 22,282 successful Edit/MultiEdit/Write calls that have ≥1 informative added line, in 1,057 sampled sessions.
- Constrained (a linked commit touches the file at or after the call and the lines are not superseded):
  - 0.785 [0.757, 0.811] 17,486/22,282
  - repo-clustered [0.749, 0.818], 135 repos
  - Edit 0.803 [0.775, 0.828]; Write 0.684 [0.629, 0.729]
- Unconstrained, as a share of the same 22,282:
  - file never in a linked commit: 0.154 [0.128, 0.182] 3,433
  - only earlier commits touch the file: 0.011 [0.005, 0.017] 238
  - overwritten later: 0.050 [0.043, 0.059] 1,125
- Path-agnostic "any trace in any linked commit": 0.762 [0.735, 0.786] 16,975/22,282.
- **Edit, `+`-line witness** (15,164 calls, 925 sessions):
  - full 0.830 [0.808, 0.853] 12,586
  - partial 0.032 [0.026, 0.038] 482
  - **contradicted-looking 0.138 [0.116, 0.161] 2,096** (repo-clustered [0.100, 0.172])
  - Line level: 74,737/84,754 added lines found.
- Edit, committed-content witness (15,123 calls):
  - full 0.879 [0.858, 0.899]
  - contradicted-looking 0.089 [0.071, 0.107] 1,340
- **Decoy baseline** (different repo, same extension, similar size). Edit `+` lines:
  - full 0.003 [0.001, 0.005] 42
  - partial 0.014 [0.011, 0.017] 205
  - contradicted-looking 0.984 [0.979, 0.988]
  - Line level: 707/84,754
  - Decoy for the committed-content witness: full 0.009 [0.006, 0.011], contradicted-looking 0.956 [0.949, 0.963].
- **Write, committed-content witness** (2,320 calls, 418 sessions):
  - full 0.836 [0.803, 0.866]
  - partial 0.164 [0.134, 0.197]
  - contradicted-looking 1/2,320 (0.0004 [0, 0.0014])
  - Decoy: full 0.002 [0.000, 0.004] (4), **partial 0.350 [0.311, 0.393]** (812)
- Write, `+`-line witness: full 0.656 [0.604, 0.705], partial 0.314 [0.268, 0.368], contradicted-looking 0.029 [0.019, 0.041] 68/2,322.
- Contradicted-looking Edits, `+` witness: 2,096 calls in 303 sessions (`q2.edit_contradicted_looking_plus_detail`).
  - By the dataset's attribution of the target file (`q2.edit_constrained_by_target_attribution`):
    - agent_only 0.063 [0.047, 0.081] 459/7,323
    - human_only 0.165 [0.121, 0.215] 752/4,551
    - mixed 0.269 [0.221, 0.319] 885/3,290
  - Subagent 0.195 [0.109, 0.292] 434/2,227 vs main 0.128 [0.107, 0.152] 1,662/12,937. The CIs overlap.
  - Lines present in the committed content but not in the `+` set: 716. Present in a later linked commit: 261. Present in the target's `-` lines: 93. Redacted: 15.
  - A later Bash command could explain the change (pre-registered keyword list): 1,710. The flag is broad; family breakdown is in the JSON. For 676 calls the only trigger was the file's basename appearing in a later command.
  - Residual after the pre-registered flags: 223 calls / 74 sessions.
    - Also excluding a same-path edit by another session of the same checkpoint: 182 / 52.
- POST-HOC sensitivity: the first and last lines of `new_string` can start or end mid-line, so I re-checked them as substrings (`q2.edit_contradicted_looking_edge_substring_sensitivity_POSTHOC`).
  - 680 of the 1,512 contradicted calls that have edge lines are then found.
  - Edit contradicted-looking falls to 0.093 [0.074, 0.114] 1,416/15,164.
  - Residual falls to 53 calls / 31 sessions (mixed 32, human_only 11, agent_only 10; the top session has 9).
- POST-HOC breakdowns of the Edit contradicted-looking rate. Each is shown as rate → rate after the edge-substring rule.
  - Worktree-like paths: 0.321 [0.207, 0.405] 326/1,015 (69 sessions) → 0.275
  - Other paths: 0.125 [0.103, 0.149] 1,770/14,149 → 0.080
  - By extension:
    - css 0.397 [0.033, 0.680] 104/262 → 0.038
    - tex 0.278 50/180 (5 sessions) → 0.028
    - json 0.244 [0.162, 0.341] 72/295 → 0.081
    - go 0.211 [0.150, 0.267] 614/2,910 → 0.161 [0.105, 0.214]
    - rs 0.198 [0.099, 0.246] 163/824 → 0.181
    - md 0.136 → 0.081
    - py 0.128 → 0.113
    - ts 0.088 → 0.055
    - tsx 0.068 → 0.036
    - kt 0/397
- Strata (`q2.by_sample_stratum_label`, `q2.by_strategy`):
  - Edit contradicted-looking for the Claude Code label: 0.141 [0.118, 0.164] 2,077/14,757. Agent 10/88, unknown 8/238, Gemini CLI label 1/81.
  - auto-commit strategy: 75 of 300 constrained Edits (12 sessions). manual-commit: 2,021 of 14,864.
- Time from an edit to its target commit: median 0.253 h [0.195, 0.335], p90 16.482 h.

### Mutation stream that git can constrain at all (`mutation_stream_census`)
- Across all 4,922 claude_code transcripts there are 88,745 successful mutation calls with informative added lines.
- 60,183 of them are in sessions with a linked `ok` commit: 0.678 [0.647, 0.708] (session-clustered).
- Multiplied by the sample's constrained rate: 0.532 [0.513, 0.550] of all CC mutation calls. The census share is held fixed, so this CI reflects only the sample's uncertainty.

### Q3. Reverse direction (`q3`)
- Scope: 4,371 commit rows linked to the sample. 322 rows have a checkpoint session without a parsed claude_code transcript; these are excluded.
- Primary check: is each committed `+` line explained by any Edit/Write/Bash text from the checkpoint's listed sessions?
  - agent_only files: 0.167 [0.098, 0.232] of 252,927 lines unexplained (repo-clustered [0.074, 0.240]). 684/8,129 files have zero explained lines.
  - mixed files: 0.290 [0.187, 0.387] of 165,001 unexplained.
  - human_only files: 0.890 [0.718, 0.950] of 1,778,657 unexplained.
  - Lines explained only by calls made after the commit: agent_only 182/252,927.
- Variant B: also allow the sessions that own the row's agent_changes entries (47 extra transcripts parsed).
  - agent_only: 0.050 [0.024, 0.089] 12,687/252,927 unexplained. 95 files have zero explained lines.
  - mixed: 0.109 [0.067, 0.193].
  - human_only: 0.888.
- agent_changes traceability (60,995 entries in complete rows):
  - Traced to a listed session's call by the exact key (path, old_string, new_string / content): 0.856 [0.772, 0.945] 52,220.
  - Untraced entries, located by a global search of all released CC transcripts:
    - 4,572 belong to another session of the same repo that is not in the checkpoint's list
    - 3,738 belong to a session of a repo with the same name but a different GitHub owner (3,738/3,738 same name, 0 same owner)
    - 452 appear in no released transcript (60 sessions)
    - 13 match a listed session only by the looser key
- Forward check: successful Edit/Write calls on committed paths whose key appears in a linked row's agent_changes: 0.716 [0.662, 0.775] 13,488/18,849.

### Q4. Commit hashes printed in Bash results (`q4`)
- 2,178 `[branch sha] subject` claims in 634 sessions. 2,033 come from commands containing `git commit`; 253 come from subagents.
  - Match a linked commit: 0.606 [0.543, 0.671] 1,320.
  - Match any commit of the same repo: 0.624 [0.561, 0.690] 1,360.
  - Match only another repo: 5.
  - Unmatched: 0.373 [0.307, 0.437] 813.
- Checks on the 1,360 matched claims:
  - commit_date within [call ts − 2 s, result ts + 2 s]: **0.993 [0.986, 0.999] 1,351**
  - author_date in the same window: 0.975 [0.964, 0.985]
  - branch equal: 0.967 [0.912, 0.997]
  - subject equal: 0.996 [0.992, 0.999]
  - commit_date − call ts: p5 −0.825 s, median −0.151 s [−0.208, −0.081], p95 37.55 s
- The 9 matched claims outside the window are in 6 sessions. In all 9 the commit predates the call (dt = −27.7 to −2,713 s). 3 of them come from commands containing `git commit`.
- The 813 unmatched claims:
  - a later history-rewrite command in the session: 356
  - the session has a `commit_not_found` checkpoint: 303
  - the claimed subject equals the subject of a same-repo commit: 191
  - none of the three: 266
- SHAs from `git log` / `git rev-parse` output: 15,449 claims in 641 sessions. Matched in the same repo: 0.349 [0.298, 0.407].
- Linked (session, commit) pairs whose commit was created by the agent's own Bash call: 0.288 [0.242, 0.339] 1,320/4,580.

### Nulls and limits, given equal weight
- agent_changes is not an independent witness (Q3 traceability above). It carries the transcript's own Edit/Write inputs.
- Log-listing SHAs match only 0.349. Unmatched commit claims are 0.373.
- 0.302 of sessions link only to `commit_not_found` checkpoints, which have no SHA or patch.
- Write `partial` corroboration is at chance level: decoy partial is 0.350.
- The metadata timestamps (`created_at`) cannot place commits relative to sessions.

---------------------------------------------------------------------------------------------------------------------

## Part B: Interpretation (mine, not data)

1. **Git is a real second witness for file mutations, but only for about half of the CC mutation stream.**
   - For Edits it constrains, whole-call corroboration is 0.830 against a 0.003 decoy, so a match is very unlikely to be chance.
   - Git cannot see:
     - sessions with no linked commit
     - files outside the repo or never committed
     - edits overwritten before the commit
   - Together these leave about 0.532 of all CC mutation calls constrained.
2. **"Contradicted-looking" is mostly mechanical, not fabrication.** The honest-log rate of 0.138 (0.093 after the post-hoc fix) is far too high to use as a per-call alarm. Its sources:
   - Edit strings that begin or end mid-line. This explains most of the css/json/tex excess.
   - Worktree paths matched to the wrong branch's commit.
   - Formatter ecosystems. Go and Rust stay high after the substring fix, consistent with gofmt/rustfmt run by hooks or editors, which leave no Bash trace.
   - Human edits between turns. The rate rises from agent_only to human_only to mixed.
   - Other sessions in the same checkpoint editing the same file.
   - After all of these, 53 calls in 31 sessions remain unexplained. I did not inspect them individually beyond 8 examples. Those 8 showed later value changes (a constant changed, a checkbox flipped) and extended comments, which look like honest later edits, not fabrication.
   - A fabricated Edit (success reported, file untouched) would look exactly like this residual. A detector would therefore need session-level aggregation or extra conditions (agent_only target, no human turn, no formatter, no worktree) before it could exceed the honest base rate.
3. **The commit-claim timing check is the cleanest per-call witness found.** When an agent's Bash result prints `[branch sha] subject` and the SHA resolves in the repo:
   - commit_date falls inside the call/result window 0.993 of the time
   - the subject matches 0.996 of the time
   - The median offset of −0.151 s is consistent with git's 1-second truncation.
   - The limit is coverage. 0.373 of claims do not resolve, mainly through amend/rebase/squash, unpushed or not-found commits, and checkpoint gaps. 266 have none of my flags.
   - A fabricated claim would hide among those 266 unless the check were restricted to sessions with no history rewrite and no not-found checkpoint.
   - The 9 resolved claims whose commit predates the call by 27.7 s to 2,713 s are unexplained. They are rare but are exactly the shape a "replayed" output would have, so they are worth a look.
4. **The dataset's own agent record is a copy of the transcript, attached by a looser rule than the session list.**
   - agent_changes entries carry the CC Edit/Write inputs and 0.856 match a listed session's call exactly.
   - Most of the remainder match other released sessions: same repo but not listed, or a same-name repo under another owner (forks or mirrors).
   - Two consequences:
     - (a) agent_changes cannot serve as an independent check on the agent's claims.
     - (b) The checkpoint-to-session links under-cover the sessions whose edits reach a commit. Most "unexplained agent-attributed hunks" disappear when the owners of the agent_changes entries are added (0.167 → 0.050).
   - The 452 entries found in no released transcript are either unreleased sessions or log loss. As a log-integrity signal they are interesting but small.
5. **Attribution leakage.** 4,551 constrained agent Edits target files the dataset labels human_only, and most of those edits are present in the commit (contradicted-looking only 0.165). The `human_only` label is not evidence that the agent did not touch a file.
6. **Novelty (UNVERIFIED).** These ideas are close to existing work, so I make no claim of novelty:
   - Using pre-existing git history as an external witness for an agent's tool log.
   - Specifically, checking agent-printed commit SHAs and commit timestamps against the call window.
   - Related prior art: software provenance and attestation (in-toto/SLSA-style), and SWE-chat's own attribution. I did not search the literature.

## Could not measure
- Transcript-side checks for OpenCode, Codex, Gemini, Copilot and Cursor. These sessions appear only in coverage counts, and their mutation-tool schemas differ.
- NotebookEdit calls (`.ipynb` diffs are JSON-escaped).
- Anything inside `commit_not_found` checkpoints, which have no SHA or patch.
- Hook-run formatters and human keystrokes. Neither is visible in the transcript, so formatter effects can only be inferred from the language breakdown.
- Whether the 53 residual and 9 out-of-window cases are fabrications. No ground truth exists here.
- Concurrent sessions in other checkpoints. Only same-checkpoint sessions were checked.
