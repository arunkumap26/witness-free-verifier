# Task: Signal Feasibility Probe (original brief, verbatim)

Read `CLAUDE.md` and `PROJECT_BRIEF.md` first. Do not re-research anything in their Settled Facts or Dead Ends sections.
You are not building the detector. You are running a measurement pass to find out which detection mechanisms the data can actually support, and to surface structure we have not thought of. The output is numbers and observations, not a tool.

## Operating rules — read these twice

1. Every number you report must come from a script you committed, writing to a file you saved. No number stated from memory, inference, or "approximately." If a number is not in a saved output file, it does not go in the report. We are building a fabrication detector; fabricating our own findings would be fatal and absurd.
2. Report nulls with the same prominence as hits. "This signal is absent" is a result that saves us hours. A probe that finds nothing is a successful probe. Do not soften a null, do not bury it, do not look for a reading that rescues it.
3. Do not tune thresholds until something fires. Set each threshold from the honest baseline before you look at the outcome, write it down, and leave it. If you change a threshold, log the before/after and the reason in the report.
4. Separate measurement from interpretation. Each probe writes raw counts to `analysis/out/<probe>.json`. Interpretation goes in the report only, clearly marked, and never gets written back into the data files.
5. Sample, don't boil the ocean. Use stratified samples and say what your `n` is everywhere. State a confidence interval or don't state the number.
6. When a phase's kill criterion is met, stop that line of work and say so. Do not push on with a dead mechanism because it was on the list.

## Phase A — Schema reconnaissance (GATE — nothing else starts until this is done)

Target: ~200 sessions. This phase decides whether the rest is possible. Budget 45 min.
Answer exactly these, each with a saved artifact:

* A1 Timestamp granularity. Histogram the distinct values of `result_ts - call_ts`. Report the resolution actually present (ms? whole seconds? identical stamps?). KILL: if the stamps are whole-second or shared between a call and its result, latency analysis is dead. Say so plainly and skip Probe 1 entirely.
* A2 Join completeness. Count `tool_result` with no matching `tool_call_id`, and `tool_use` with no result. Report rates.
* A3 Truncation. % of results at or near the 10 KB boundary.
* A4 Error-signal survival. Does any failure marker survive into result content? Search for tracebacks, `command not found`, `Permission denied`, `No such file`, nonzero-exit text. Report what survives and in what form. If nothing survives, Probe 3 needs a regex proxy or it is dead.
* A5 Token accounting. Does the schema record per-turn token counts, and are tool-result tokens accounted separately from model-generated tokens? If yes, note it loudly — that is a potential direct signal we have not explored.

Write `analysis/out/phase_a.json` and a short `analysis/PHASE_A.md`. Stop and report Phase A before starting Phase B. I want to see it before you spend more time.

## Phase B — Mechanism probes

Four mechanisms. For each: measure the honest baseline distribution first, then ask whether a deviation would be detectable above that baseline's noise. You are measuring separability, not hunting for culprits.

### Probe 1 — Latency physics
Hypothesis: honest tool latency is work-bound; fabricated latency is generation-bound, so it cannot go below time-to-first-token.
* Per `tool_name`, report the full latency distribution: min, p1, p5, median, p95, max.
* The p1/min per tool class is the key statistic — the honest floor. Trivial I/O commands should sit in single-digit milliseconds.
* Report `corr(output_bytes, latency)` per tool class.
* Report any session showing a step change in its latency floor mid-session.
* KILL: if within-tool latency variance is near zero (harness batching), or A1 failed.

### Probe 2 — Knowledge precedence
Hypothesis: every world-specific token an agent emits should have an antecedent in a prior tool result.
* Extract from call arguments: file paths, symbol names, config keys.
* For each, does it appear in any earlier result in the same session?
* Report the unsourced rate on honest data — that baseline is the whole point. If honest sessions are already 40% unsourced, the signal is buried and we need to know.
* Also report the inverse: first-try deep-path access with no prior enumeration.

### Probe 3 — Environment pushback / surprise rate
Hypothesis: real environments generate friction; fabricated ones are too agreeable.
* % of results that are errors (per A4's definition).
* % of calls that are a retry of an immediately-prior failed call.
* Distribution of per-session error rate. Specifically: how many long sessions have a zero error rate? That tail is the interesting population.
* Report whether error rate changes within sessions (early vs late).

### Probe 4 — Entropy / incidental detail
Hypothesis: models reproduce high-entropy incidental fields badly.
* Census: what % of results contain a hex string (len 7/8/32/40/64), a large integer (PID, byte count, inode), or an embedded timestamp?
* For hex fields: test digit uniformity across the corpus. Report the test statistic and n. Do not claim a result at small n.
* Round-number artifacts: byte counts ending 00, durations ending .0, mtimes at :00.
* This is a surface measurement. If few results carry such fields, the mechanism has nothing to work on — say so.

Each probe writes `analysis/out/probe_N.json`.

## Phase C — Open-ended discovery (do not skip this; it may be the most valuable phase)

Now stop testing our hypotheses and go look at the data without one.
Spend real effort here. Profile broadly and tell me what is actually in this corpus that we did not ask about. Things worth looking at, as starting points rather than a checklist:
* Distributions that are bimodal, long-tailed, or spiky where you'd expect smooth.
* Fields that correlate when there is no mechanical reason they should.
* Step changes or regime shifts within sessions, on any field.
* Sessions that are outliers on several axes at once.
* Structural regularities: ordering patterns, command bigrams, retry shapes, things agents always or never do.
* Anything that surprised you while writing the parsers. Parser surprises are data.
* Any field in the schema we have not used and probably should.

Then propose up to five new detection mechanisms grounded in something you actually observed, not in general reasoning about LLMs. For each: the observation that suggests it, the measurement that would test it, the expected false-positive source, and your honest guess at whether it is novel. Flag clearly that novelty is unverified — do not assert any of them are new. We check prior art separately and we have been burned on this before.
Rank them against each other and say which one you would build first and why.

## Phase D — Report

Write `analysis/FINDINGS.md`:
1. Verdict table — one row per mechanism: ALIVE / WEAK / DEAD, the number that decides it, and n.
2. Phase A results and anything they killed.
3. Per-probe findings with distributions, not just summary stats.
4. Phase C discoveries and the five proposed mechanisms, ranked.
5. What you could not measure and why — be exhaustive here.
6. Confidence log — for each headline number, how much you'd bet on it and what would change your mind.

Commit the scripts. Every number traceable to a script and a saved output file.

## If you get stuck

Do not guess and proceed. Write down the blocker, say what you tried, and move to the next probe. An honest partial pass beats a complete-looking one with soft numbers in it.
