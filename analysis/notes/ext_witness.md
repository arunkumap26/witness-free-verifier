# Lens: two external witnesses, no transcript (post-incident setting)

Script: `analysis/probes/phase_c_ext_witness.py`. Data: `analysis/out/phase_c/ext_witness.json` (raw counts only).
Run: `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_ext_witness` (single process).
Every number below appears in that JSON (rounded to 3 decimals here). Rates carry n and a 95% CI. "page-clustered" means
`stats.cluster_rate` / `cluster_quantile` with the wiki page as the resampling unit.

Pre-registered choices are in `JSON.prereg`. They were fixed before any outcome was computed: windows 1h/24h/7d, shift
nulls ±7/±14 d, a 60 s burst gap, claim keywords, delta bins, tolerances of 1/60/3600 s. Everything under a key containing
`posthoc` was added after run 1 had been inspected. `POSTHOC` in the script records what motivated each addition. Treat those
numbers as hypotheses that need a holdout.

---

## 1. Numbers

### S1. Multi-clock consistency inside collusion-wiki (NULL: no violations)
- Physically required orderings on revisions: request<=success, request<=write_date, request<=archived_at,
  success<=archived_at, write_date<=archived_at. Violations: **0/14482, 0/14482, 0/14482, 0/14585, 0/14591**. The Wilson
  upper bound is 0.0003 in every case. Zero events also means the beyond-uncertainty count is zero.
- `time` == `write_date` on 14591/14591 rows. `time` == `request_time` on 14482/14482 rows. `success_time` == `time` on
  12884/14585 rows. `success_time - request_time` takes only the values {0: 12792, 1: 1689, 2: 1} (n=14482).
- Deletes: `success - request` takes {0: 4746, 1: 470}. `clock_delta_seconds` disagrees with that difference on 0 rows.
- `archived_at - write_date`: median 390 s, 4856/14591 rows over 1 h, 3981 over 1 day. It is never negative.
- Quantization: second-of-minute chi-square p = 0.014 for `time` (n=14591), 0.358 for `success_time`, 0.161 for
  `archived_at`. Minute-of-hour p = 2.1e-66, because saves are bursty. That chi-square treats saves as independent, so read
  it as a sign of burstiness, not of quantization.
- Per-page order by `seq`: 0/10012 time decreases, 0 for `write_date`, 4/10008 for `success_time` (all -1 s), and 70/10012
  for `archived_at` (49 beyond 1 s, on 4 pages).
- Derived tables `pages.jsonl` and `labels.jsonl` match the revisions exactly: 0 mismatches on first_write, last_write and
  counts.
- **Post-hoc, storage order vs time.** Sorting each page by its RCS commit number (`1.N`, the order revisions were written to
  the file) gives 72/10012 adjacent pairs whose `time` goes backwards (0.007, Wilson [0.0057, 0.0090]; page-clustered
  [0.000, 0.015], 1453 pages). 59 pairs go back by more than 1 s. All 72 are on 4 pages, with magnitudes
  {-1: 13, -2: 29, -3: 28, -4: 1, -5: 1}. In 70/72 inverted pairs the two revisions carry different labels, and in 71/72
  they carry different ip16. 414 revisions on 5 pages have an RCS minor number different from `seq`.

### S2. Cross-witness temporal precedence (HIT for source-matched co-timing; weak directionality)
- 7305/14591 revisions name at least one catalog source marker (0.501 [0.493, 0.509]). New-mention events, where a source
  appears on a page for the first time: 3125 on 2231 pages. Of these, 3116 belong to a source with at least one catalog report.
- **Wiki new mention preceded by a urlquery report for the same source within 1 h:** 0.566 [0.481, 0.655], n=3116, 2223 pages.
  - Shift null (±7/±14 d): 0.000 [0.000, 0.001]. Source-permutation null: 0.233 [0.182, 0.291]. Post-hoc local null
    (±2 h/±4 h/±1 d): 0.307 [0.264, 0.352].
  - Excess over the local null: **0.259 [0.217, 0.303]**. Excess over the permutation null: 0.332 [0.298, 0.365].
  - After-window, a report in the following hour: 0.523 [0.468, 0.582]. Before minus after: 0.042 [0.010, 0.078].
- 24 h window: before 0.746 [0.701, 0.792], local null 0.599 [0.556, 0.642], excess 0.147 [0.140, 0.153], before minus
  after 0.159 [0.115, 0.204]. 7 d window: before 0.960, local null 0.845, excess 0.115 [0.105, 0.126].
- By source at 1 h (before / after / excess over local null):
  - SEC county data: 0.994 / 0.925 / 0.423 [0.396, 0.445] (n=1432, 794 pages). All 455 catalog reports fall on 1 UTC day.
  - USAspending: 0.764 / 0.558 / 0.369 (n=165).
  - MAX budget documents: 0.833 / 0.859 / 0.393 (n=78).
  - Clark newsletter: 0.800 / 1.000 / 0.675 (n=60).
  - IHME: 0.909 / 0.932 / 0.595 (n=44).
  - **DataUSA: 0.038 / 0.026 / 0.032 [0.023, 0.043] (n=1259; the catalog holds only 91 DataUSA reports).**
  - **US Census API: 0 / 0 / 0 (n=58; 5 catalog reports, 0 overlapping days).**
- Lag from a mention back to the most recent prior report of the same source: median 971 s, page-clustered CI
  [491, 5388], n=3104. Lag to the next report: median 491.5 s [366, 728], n=2474. Same-second coincidence: 0.006
  [0.004, 0.009].
- Reverse direction, a urlquery burst of source S followed by a wiki new mention of S within 1 h: 0.085 [0.019, 0.159],
  n=4935 bursts, 131 source-days. Shift null 0.002. Post-hoc local null 0.045. Excess over the local null 0.040
  [0.007, 0.079]. At 24 h the excess over the local null is 0.031 [-0.015, 0.085].
- Exact report citations in wiki bodies: 1 first appearance (2 revisions on the same page). The revision is 8270 s **after**
  the cited report, so the order is consistent (n=1).
- httpbin.org/base64 new mentions: n=8. 7/8 have an indirection-class report in the hour before (Wilson [0.529, 0.978]);
  the shift-null mean is 0.5 of 8. 7/8 also have one in the hour after.
- Witness independence: 8 of the 52 catalog method entries cite the wiki in their `reason`
  (`urlquery_methods_with_wiki_in_reason`). Wiki content influenced which sources were queried. The report timestamps
  themselves are a census of each query (search-coverage.json), so timing is not selected on the wiki.

### S3. urlquery burst structure (structure present; any-source alignment with wiki NULL against local nulls)
- Same-second groups by size: {1: 28350, 2: 3051, 3: 744, 4: 231, 5: 73, 6: 30, 7: 1}. 9810 reports sit in a group of
  2 or more, which reproduces recon. Of the 4130 multi-report groups, 3998 have one data source and 132 mix sources.
- Gaps: 5680 zero gaps out of 38159; median 10 s globally and also within a source. Second-of-minute chi-square p = 1.3e-4
  (n=38160).
- Bursts (60 s gap rule): 8078 bursts, 3828 singletons, maximum size 1006. Of the multi-report bursts, 3410 have one source
  and 840 mix sources.
- The largest wiki save burst under the same rule has 4621 saves, 2026-06-18 17:42:33 to 20:52:40Z. 414 urlquery reports
  fall inside it.
- Alignment, any source, 5 min window:
  - A urlquery burst has a wiki save nearby: 0.424 [0.231, 0.582] (n=4060, 31 days). Shift null 0.112, excess 0.312.
    **Post-hoc local null 0.389, excess 0.035 [-0.008, 0.077].**
  - A wiki burst has a urlquery report nearby: 0.678 (n=2267, 28 days). Local null 0.618, **excess 0.060 [-0.014, 0.124].**
- At 1 h both excesses over the local null are 0.015 and 0.024, and both CIs include 0.

### S4. Narrated timing claims vs the revision's own save time
Parsing rules are in `prereg`. A claim counts only on the revision where it first appears on the page. Its delta is claim
minus save. Time-of-day claims are folded into ±12 h.
- Occurrences across all revisions: tod_task 55002, tod_unqualified 33472, tod_real 8341, epoch_prose 1765,
  epoch_url 657, iso_real 440. New claims: 6105, 4238, 854, 747, 370, and 31 iso_real.
- **Real-clock time-of-day claims** ("UTC", "terminal", "container"...): n=854 on 263 pages. Median delta -84 s
  [-107.5, -64]. 601 claims fall in [-1h, 0) against 95 in (0, +1h].
  - The task-clock control (n=6105) gives 344 vs 335, and the unqualified class gives 227 vs 201.
  - 180/854 real-clock claims are later than their own save by more than 1 s: 0.211 [0.178, 0.245].
- **Post-hoc, by tense.**
  - Forward-looking claims (due, projected, estimated, next...): 70/164 are after the save. These are predictions, not
    impossibilities.
  - Past or present tense, not approximate: n=125. 22/125 are after the save, but 15 of the 22 lie 1 h to 1 d out, where a
    folded event more than 12 h old lands.
  - The near-future band (1 s, 1 h] for that group: **7/125 = 0.056 [0.017, 0.100]**. Task-clock control: 37/550 = 0.067
    [0.042, 0.095]. A uniform unrelated clock would give 0.042 (`uniform_clock_expectation_near_future_1s_to_1h`).
- **Epoch stamps in prose:** n=747 on 297 pages, median delta -1 s [-1, -1]. 10/747 are later than the save by more than
  1 s (0.013 [0.005, 0.025]).
  - Post-hoc: with a fractional part (time.time() form), **0/459** are after the save (Wilson upper bound 0.008). Without a
    fraction, 10/288.
  - "Round" epochs (sec % 100 in {0, 1, 99}): 6/37 after the save. Non-round epochs: 4/710.
- **Epoch stamps in page names**, compared with the page's first save: n=396 names, 183 labels, median -2 s [-3, -2].
  31/396 are after the save by more than 1 s (0.078; label-clustered [0.023, 0.100]).
  - Post-hoc: round names 26/55 = 0.473 (label-clustered [0.118, 0.660]). Non-round names 5/341 = 0.015 (label-clustered
    [0.000, 0.022]).
  - Near-future band (1 s, 1 h]: round 0.236 [0.088, 0.316], non-round 0.006 [0.000, 0.016].
- Epoch stamps inside URLs: 39/370 after the save, 30 of them by more than 1 day. These include server-generated expiry
  tokens and incrementing `uniq=` sequences.
- ISO real-clock claims: n=31. 2 are after the save by more than 1 s, and none by more than 60 s.
- **Post-hoc, task-clock to UTC mappings:** 482 new pairs. Among the 84 labels with at least 2 distinct pairs, the median
  offset spread is 6268 s. Only 3/84 labels have a spread of 60 s or less, and 18/84 have 600 s or less.

---

## 2. Interpretation (separate from the numbers)

1. **The wiki's internal clocks cannot catch anything.** Every required ordering holds, but that is largely by construction.
   `request_time` was joined to the save by equality, so `time`, `write_date` and `request_time` are one clock written three
   times. Only `success_time` (0-2 s later) and `archived_at` vary independently. This is a clean export, not evidence about
   agents. The one real inconsistency is the post-hoc one: RCS commit order against timestamp order. The inversions are
   1-5 s and sit on 4 shared, heavily edited pages, written by different labels from different ip16. That fits concurrent
   saves where the timestamp is taken before the commit lock (a mechanical race), not fabrication.

2. **Cross-witness co-timing is real but is campaign-level, not claim-level.** A wiki page that starts naming a catalog source
   is far more likely to have a urlquery report for the same source in the preceding hour than at ±2-4 h or ±1 d (excess
   0.259). The any-source burst alignment, by contrast, disappears against the same local nulls. So the two witnesses agree
   on which source was being worked on when, beyond what the general activity of either witness predicts.
   - Directionality is weak. The before rate exceeds the after rate by 0.042 at 1 h, and for MAX, IHME and Clark the after
     rate is equal or higher. The data cannot say "fetch, then write". It says "same source, same hour".
   - Coverage is source-dependent. DataUSA and US Census mentions are almost never preceded by a report. **A missing
     urlquery report is therefore not evidence that a claimed fetch was fabricated.** That would be the false-positive
     trap of using this witness as an oracle.
   - SEC county data drives the pooled number: 1432 of 3116 events, with all 455 reports on one day.

3. **Agent-emitted epochs are the sharpest witness-free check here.**
   - Epochs printed from a real clock (fractional time.time() form) never postdate the save that carries them: 0/459.
     Overall the agent sandbox clocks agree with the wiki server clock to a median of 1-2 s.
   - The epochs that do postdate their own save are concentrated among hand-looking round numbers (…000, …999, …001), in
     both page names (26/55 vs 5/341) and prose (6/37 vs 4/710).
   - Reading: some agents wrote "timestamps" they had not read from any clock. They guessed or extrapolated "now", and the
     guess ran ahead of the server. That is a narrated value with no tool behind it, caught purely by an external clock.
   - Caveat: the roundness definition was chosen after seeing 20 examples, most of them round. The 26/55 contains those
     examples. It needs a holdout corpus.

4. **Narrated wall-clock claims track the server clock, but the impossibility test does not separate cleanly.**
   - "UTC/terminal/container" times are pinned just before the save (median -84 s; 601 vs 95 asymmetry, against 344 vs 335
     for task-clock times). The keyword classifier therefore finds real clock readings.
   - But most after-save real-clock claims are projections. After restricting to past or present tense, the near-future rate
     (0.056) is no higher than the unrelated-clock control (0.067).
   - Folding without a date, and keyword tense tagging, are too blunt to call any single time-of-day claim impossible.
     **Null for the lens's headline question at this resolution.**

5. **Narrated task-clock to UTC mappings are not self-consistent at the minute level** (3/84 labels within 60 s).
   Explanations other than fabrication, none tested: the task clock may not run at wall-clock rate, a label may span several
   cohorts or episodes, or the pairing heuristic may be wrong. Exploratory only.

## 3. Could not measure
- urlquery carries no URLs, bodies or submitters. A wiki claim cannot be linked to a specific fetch or value, only to
  source-level co-timing.
- No transcripts or tool logs exist for these campaigns, so no claim can be graded against ground truth. "Impossible" here
  means physically inconsistent with the server clock, not "known fabricated".
- `recent_changes_time` is null on all revisions, so the rclog clock cannot be checked on saves.
- Time-of-day claims carry no date. Events more than 12 h old fold forward and cannot be separated from future-dated claims.
- The tense, roundness and mapping heuristics have no hand labels or holdout.
