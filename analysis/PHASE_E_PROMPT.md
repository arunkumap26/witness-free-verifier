# Phase E — Analysis, validation, acquisition, design (brief, verbatim)

Received 2026-10-04, to start after Phase D completes. Operating rules are carried from `analysis/PROBE_PROMPT.md`.

Phase D is finishing. Do NOT start new probe phases.
Track A (analysis) and Track B (prior art + corpora) are independent — run them in parallel. Track C (design) depends on both. Everything is wall-clock bound, so fan out across subagents wherever tasks don't depend on each other; cap concurrency around 8 and set a fallback model so an overload degrades instead of halting.

## Scope boundary — read first

A separate Claude Code session owns the local Qwen swarm entirely — sandbox, generation, analysis. Do not read, modify, run, or analyze anything related to it. Do not generate agent transcripts of your own. Your scope is the publicly available corpora.
Swarm-derived labeled data may arrive in the morning. The record schema and eval harness should accept a labeled corpus as a future input; do not block on it or assume its contents.

## Operating rules (carried from `PROBE_PROMPT.md`)

Every number traceable to a committed script and a saved output file. Nulls reported as prominently as hits. Thresholds pre-registered before looking at outcomes. State `n` everywhere. We are building a fabrication detector; fabricating our own findings would be fatal.

## TRACK A — Analysis

### A0 — Consolidate (~20 min, do first)
Read Phase A–D outputs. Write `analysis/DECISION_TABLE.md`:

| Mechanism | Corpus | ALIVE / WEAK / DEAD | Deciding number | n | What would change this |

One row per mechanism per corpus — the cross-corpus spread is itself a finding.
State in three sentences what the strongest finding is. If nothing fired, say so plainly; the coverage result stands on its own.

### A1 — Second pass on existing findings
Phase C and the mechanism proposals were exploratory, so their numbers are provisional. For each surviving candidate: re-measure at larger n with a confidence interval, then actively try to kill it. Parser bug, truncation artifact, join error, one repo or model dominating the sample, sampling selection effect. Run the check that distinguishes artifact from signal. Stratify by tool type, model, repo, session length — a signal present in one stratum only is usually an artifact of that stratum.
Three specific follow-ups, all high value:
* The 10 honest request-ID failures in 3,674 streams. Explain them. A shared benign cause drops the effective FP rate toward zero.
* The 13.5% of SWE-chat sessions where the latency floor shifts mid-session. Currently treated as noise. A mid-session regime change is also what compromise looks like from outside. Investigate before dismissing.
* Entropy round numbers. The skeptic noted these are mostly model-chosen timeouts, not invented measurements. Re-run excluding model-chosen timeout values; if the 42%-vs-12% gap collapses, mark DEAD.

Write `analysis/SECOND_PASS.md`: per candidate — what you re-measured, what you tried to kill it with, whether it survived, the number.

### A2 — New mechanism candidates
Pre-register a threshold for each before looking at results. Report nulls.

**N1 — Conditional duration model (repairs the shell-command gap).** The floor test asks "slow enough to have been generated?" and fails on shell, because a slow `pytest` and a generated `pytest` look alike. Instead ask: is this call's duration explained by the work it claims to have done?
* Baseline from within-session repeats of the same command, not a global model — that holds machine load, cache state and repo size constant. Report the repeat-command rate first; it bounds coverage.
* Then test what explains the residual: for honest calls the residual should be uncorrelated with output size; for generated ones the residual is generation time and scales with output length. Report `corr(residual, output_bytes)`.
* Highest-value new candidate — shell is where most of the corpus lives.

**N2 — Token accounting as a direct discriminator.** Text the model produces bills as output tokens; text the environment returns arrives as input tokens on the next call. A result invented inline was generated, so it lands in the output column — an accounting identity, not a statistic.
* First establish whether the corpora expose per-turn input/output token counts at the needed granularity. If not, mark DEAD.
* State the limit: catches inline fabrication, not execution-layer compromise (fake output still returns through the harness as input tokens). Separating those two threat classes is itself useful.

**N3 — Reaction time to a result.** The gap between a result arriving and the next call is reading time and should scale with result size. If the agent authored the result, no reading is needed. Test `corr(next_call_gap, result_bytes)` per session.

**N4 — Concurrency physics.** Parallel real calls contend for CPU, disk and network and inflate together under load; generated calls contend for the inference engine, a different scaling signature. Measure duration vs. concurrent-call count. Also relevant to the #67730 class, which clustered at peak concurrency.

**N5 — Lightweight battery** (all cheap; one pass over the corpora).
* Repeat-command determinism — same command twice with no intervening write should return byte-identical output; sampling makes fabricated repeats drift. Likely the strongest item here and nearly free.
* Sort-order violations — `ls` sorted, `git log` chronological, `grep -n` ascending; models get ordering subtly wrong on long outputs.
* Truncation-boundary behavior — real output truncates at exact byte boundaries; check whether fabricated output claiming to be large truncates identically.
* Whitespace/formatting fingerprints — real output has tool-specific column padding, tab alignment, trailing-newline conventions; models normalize.
* Output-size distribution per command — real sizes are world-determined and often multimodal; generated sizes cluster near model-preferred lengths.
* Error-message fidelity — real errors carry exact library paths, version strings and line numbers matching files the log already showed. Nobody studies fabricated failures; everyone assumes a lying agent only lies about success.
* Cold-start signature — the first call of a session runs against cold caches and is honestly slower; generated calls don't care.

**N6 — Cross-corpus transfer matrix.** Run every mechanism against every corpus and produce the full grid, failing cells included. "Fabrication-detection signals do not transfer across harnesses" is a real secondary contribution and the grid is the evidence. Embarrassingly parallel — fan out wide. This is one of the two biggest overnight jobs.

**N7 — Expand the synthetic attack battery.** Current positives are ID-swap and 30s back-date only. Add larger and smaller time offsets, selective single-call tampering, consistent multi-call rewrites, reordering, output substitution with matched byte counts. Report recall per attack type per mechanism. That table is what the writeup needs and it exposes which attacks currently walk through untouched. The other big overnight job.

## TRACK B — Prior art and corpora (parallel with Track A)

For every item: name the closest existing work, state precisely what it does and does not do, verdict NOVEL / PARTIAL / TAKEN, with the citation that decides it.
The standing rule, which already cost us a day this week: do not stop at title and abstract. Ask whether an existing system already internally embodies the idea even if that is not its headline. A benchmark harness, APM product or eval framework may do it without advertising it. Mark unverifiable citations UNVERIFIED; never assert a paper exists without opening it; if a repo 404s, say so.

### B1 — Conditional duration model (N1) ⚠️ validate carefully
Two sub-claims, verified separately:
* (a) duration-vs-expected-workload residuals as a fabrication signal in agent logs
* (b) `corr(residual, output_size)` as the discriminator between work-bound and generation-bound latency

Search these angles explicitly — the adjacent literature is large and won't be phrased in agent terms:
* covert/timing side channels; timing-based tamper detection
* performance-regression and latency-anomaly detection in APM / observability
* runtime prediction: CI build duration, database query cost estimation, job scheduling
* log anomaly detection (DeepLog, LogAnomaly, LogBERT and successors) — do any model duration rather than event sequence?
* LLM inference latency modeling: TTFT, tokens/sec, output-length-proportional latency
* machine-generated text detection using generation-time signals
* fraud-detection velocity checks and transaction-timing anomalies
* agent-trajectory evaluation and benchmark-cheating detection — does any harness already time-check tool calls internally?

Be specific about which sub-claim is taken, if either. Timing anomaly detection in general is almost certainly old; the question is whether anyone has applied a workload-conditioned residual to agent tool-call fabrication.

### B2 — Server-minted request IDs ⚠️ highest priority
The build order hinges on this and novelty is UNVERIFIED. Claim: the timestamp embedded in a provider-minted request ID must sit between the stream's last input and the response's first output, giving a clock the agent does not control.
Search: provider request-ID structure and embedded timestamps; trusted timestamping and RFC 3161; multi-clock and clock-skew consistency in distributed logs; secure log timestamping and forensic clock analysis; agent-log verification using provider-side metadata.
Also report factually: what is actually known about request-ID internal structure from major providers — timestamp embedded? layout documented? stable? If this rests on an undocumented format, that is a material limitation and must appear in the design.

### B3 — Everything else (parallel, lower priority)
Token/prompt-cache accounting (chase the prompt-cache timing side-channel paper already surfaced); harness structured-copy vs visible-text mismatch; nested timer chain; reaction-time scaling; concurrency-contention scaling; repeat-command determinism; fabricated error-message fidelity; cross-harness non-transfer of detection signals.
Write `analysis/PRIOR_ART.md`, one section per item, verdict table at the top.

### B4 — Audit the corpora we have
Inventory table: name, source, licence, session count, tool-call count, and which fields are present — ms timestamps, `tool_call_id` join, token counts, truncation markers, error markers, and critically whether provider request IDs are present.
The request-ID mechanism only runs on corpora carrying request IDs, so its coverage is bounded by that column. Establish it before anything else. If only one corpus has them, say so plainly — it caps the headline.

### B5 — Acquire more
Find and download public agent-trajectory corpora with structured call/result records. Check at least: SWE-agent / SWE-bench trajectory releases; OpenHands (OpenDevin) logs; Aider benchmark logs; Terminal-Bench traces; WebArena / AgentBench / OSWorld dumps; HuggingFace search for agent trajectory and tool-use datasets; METR public task-suite transcripts; any OpenCode / Codex / Cline / Roo public trace releases.
Record licence (must permit research use), size, schema, timestamp resolution, request-ID presence. Download only what passes the field audit — a corpus without timestamps or a call/result join is not worth the disk. Pure-narration sources stay out of scope.

### B6 — Assess generating a corpus we lack
If few corpora carry provider request IDs, that gap is worth filling: running a harness against real tasks while capturing raw API responses including request IDs and headers would produce a corpus nobody has. Assess feasibility and cost; do not start. Constraint: no paid API spend. If it needs budget, flag it as a morning human decision.

### B7 — Release artifact
Organizers listed aggregated datasets and meta-analysis frameworks as need areas, and we are already normalizing several corpora into one schema for N6. Assess the incremental hours to publish that normalized multi-harness corpus — schema, loaders, per-corpus field coverage table — under MIT or CC BY 4.0 (not CC BY-NC, which blocks benchmarking use). Report the cost. Do not build it yet.
Write `analysis/CORPUS_INVENTORY.md`.

## TRACK C — Design and scaffold (after A and B)

### C1 — `DESIGN.md`
Use only mechanisms that survived Track A and cleared Track B.
High level: problem statement in three sentences; threat model stated explicitly (execution-path compromise — agent controls what a tool returns, harness still honestly records the call and stamps the clock — not full harness compromise, which is out of scope for any log-based method by definition); what the tool does from a user's view in one paragraph; what it explicitly does not do (internal consistency is necessary, not sufficient; a coherent forgery passes; every positive detected so far is synthetic — say so); feature list split MUST / SHOULD / COULD, each tagged with the finding that justifies it, anything without one demoted or cut.
Architecture: module decomposition with responsibilities and dependencies; data flow from raw transcript to rendered verdict; record schema able to accept a labeled corpus later; check plugin interface with exact signature (a check takes a session, returns per-call verdicts of `supported` / `contradicted` / `unconstrained` plus a reason string and a confidence) including registration, composition and disagreement resolution; per-check detailed design — inputs, algorithm, thresholds and their provenance, complexity, known false-positive sources, behavior when required data is missing; eval design — metrics, held-out split strategy, per-check success criteria; CLI surface; demo surface — favor the visceral, a transcript with per-call verdicts lighting up and the deciding evidence inline; build order sequenced against a 3:00pm code freeze with hour estimates, dependency graph and an explicit cut list; risks, each mitigated or accepted-and-documented.
Be concrete. "Implement the check" is not a design — name the functions, the data they touch, and the decisions a reader would otherwise have to make.

### C2 — Scaffold (only after `DESIGN.md` exists)
Loader normalizing every public corpus into the record schema; check registry implementing the plugin interface; `eval/run_eval.py` deterministic per seed, ≥3 seeds, under ~2 minutes, one JSON object; held-out split created now, manifest on disk, never touched during tuning; one trivial reference check proving the pipeline runs end to end; figure generation for the transfer matrix and the recall-per-attack table.
Do not implement the real detection checks — gated on the morning review.

### C3 — `analysis/MORNING_BRIEF.md`
For a reader who has been asleep and has ~20 minutes before making build decisions:
1. What ran, what finished, what failed.
2. Updated decision table.
3. What survived the kill attempts; what died.
4. Prior-art verdicts, B1 and B2 called out first.
5. Corpus inventory, request-ID coverage column highlighted; anything downloaded and whether it passed the field audit.
6. The design in ten lines, plus the two or three checks to build first and the number justifying each.
7. Decisions needing a human: whether to generate a request-ID corpus, whether to publish the normalized dataset, plus anything else.

Decision-shaped and short. No narrative of the night.

## Stop conditions
* Blocked: log it, skip it, move on. An honest partial pass beats a complete-looking one with soft numbers.
* Do not implement detection checks before the morning gate.
* Do not begin generating any corpus — assess and report only.
* Do not touch the swarm.

This is after all the past tasks that were assigned and scheduled are complete.
