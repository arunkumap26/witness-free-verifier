# Witness-free verification: how it works

A five-minute tour of the work in `analysis/` and `verifier/`, in six diagram sections. Every number is copied from a committed
file under `analysis/`, and the file is named next to it. **Every detection number in sections 1 to 6 is against synthetic
tampering of real honest sessions: none of the 21 corpora contains a known real fabricated tool result.** The same text and
diagrams exist in two forms: `analysis/FLOWCHARTS.md` (renders on GitHub) and `analysis/flowcharts.html`.

How to read the numbers: `k/n` is "flagged out of tried". "488/500 vs 3/500 honest" means the check flagged 488 of 500
tampered sessions and 3 of 500 untouched copies. sw/CC is the SWE-chat Claude Code unit, the largest one we hold.

---

## 1. The project in one picture

```mermaid
flowchart TD
    P["Problem<br/>Agents can fake what a tool returned.<br/>Graders, reviewers and other agents trust the log."]
    Q["Question<br/>How much can a log prove about itself,<br/>with no outside witness?"]
    D["Data: 21 corpora held<br/>7 before acquisition + 14 downloaded<br/>6 of the 14 loaded and measured"]
    PH["Phases A to E<br/>recon, pre-registered probes, discovery,<br/>report, second pass with an attack battery"]
    DS["Design<br/>analysis/DESIGN.md, commit 2baebcf"]
    V["Verifier scaffold, commit 5f837b6<br/>pipeline end to end, reference check only"]
    SW["Swarm labeled dataset test<br/>dev/test split by session, rules frozen before test"]
    P --> Q --> D --> PH --> DS --> V --> SW
    D -.- RID["Only 5 of the 21 carry provider request ids,<br/>all Claude Code talking to Anthropic"]
    PH -.- SYN["Every positive in the corpus work is synthetic"]
```

Agent harnesses record what each tool call returned, and those records are treated as evidence, but nothing checks
whether a recorded result could have come from the call it is attached to (`analysis/DESIGN.md` §1.1). We asked how
much of that a log can check about itself, using only fields the agent does not control: provider clocks, billing
counters, harness timers and second renderings. We held 21 corpora: 7 before acquisition, plus 14 downloaded, of which
6 were loaded and measured (tbench2, agentcap, pub_cc_hf, pub_trace_commons, pub_codex, glm_tb21) and 8 were not, for
time (`analysis/CORPUS_INVENTORY.md` §0, `analysis/MORNING_BRIEF.md` §1). Only 5 of the 21 carry provider request
ids, the strongest clock we found, and all 5 are one harness talking to one provider (`analysis/CORPUS_INVENTORY.md`
§0). The phases produced a design and a verifier scaffold. The last step tests that strategy against a labeled
dataset from the separate swarm workstream (section 5 and the results placeholder in section 6).

---

## 2. Phases A to E, with their gates

```mermaid
flowchart TD
    A["Phase A: schema recon, split A only<br/>Which fields exist, at what resolution?"]
    GA{{"Gate A<br/>pre-registered kill rules"}}
    KA["Killed early<br/>Latency in aiv_cu: call and result share one stamp,<br/>6,107/6,107 pairs. No stamps in whowhen and cursor."]
    PR1["Pre-registration, commit 3df8d28<br/>Phase B thresholds from split A only"]
    B["Phase B: 4 probes on split B<br/>latency, knowledge precedence, pushback, entropy"]
    SB["Skeptic re-derivation<br/>49 of 50 unit checks reproduced"]
    C["Phase C: 14 discovery lenses<br/>239 observations"]
    SC["Skeptic re-check<br/>200 of 239 reproduced"]
    D["Phase D: FINDINGS.md, commit c24eed6<br/>5 proposed witnesses R1 to R5, ranked"]
    PR2["Pre-registration E, commit 55fc556<br/>kill tests, attack battery, transfer grid"]
    E["Phase E, three tracks"]
    TA["Track A: measure<br/>second pass, N1 to N5,<br/>N7 attack battery, N6 transfer grid"]
    TB["Track B: prior art and corpora<br/>14 downloaded, 6 loaded"]
    TC["Track C: DESIGN.md and the scaffold"]
    GE{{"Survival rule<br/>a check can only lower a label"}}
    OUT["25 candidate x unit rows<br/>SURVIVES 9, DOWNGRADED 7,<br/>KILLED 3, NOT_RUN 6"]
    A --> GA
    GA -->|"dead"| KA
    GA -->|"alive"| PR1 --> B --> SB --> D
    GA -->|"alive"| C --> SC --> D
    D --> PR2 --> E
    E --> TA --> GE --> OUT
    E --> TB
    TA --> TC
    TB --> TC
```

Each corpus's sessions were drawn into disjoint splits: A and B by stratified sampling at the start
(`analysis/lib/sample.py`), E and H in commit 49f254b, before any Phase E measurement (`analysis/PHASE_E_PLAN.md`).

```mermaid
flowchart LR
    S_A["A<br/>calibrate thresholds"] --> S_B["B<br/>measure;<br/>Phase C also read it"] --> S_E["E<br/>fresh replication"] --> S_H["H<br/>held out; read once,<br/>after the freeze"]
```

Phase A only looked at which fields exist and at what resolution, on split A, and its gate killed lines whose data
could not carry them, for example latency in aiv_cu, where a call and its result share one stamp in 6,107/6,107 pairs
(`analysis/PHASE_A.md` A1). Thresholds for Phase B were then frozen in a pre-registration commit (3df8d28) from split A
alone, and an independent re-derivation reproduced 49 of 50 Phase B unit checks (`analysis/FINDINGS.md`, "Read this
first"). Phase C's 14 discovery lenses read split B before the Phase B probes ran, so B is not blind for anything
Phase C found; a skeptic reproduced 200 of its 239 observations (`analysis/FINDINGS.md` §4.1). Phase E re-ran every survivor and the
five Phase D proposals under a second pre-registration (55fc556), using a fresh split E as the replication; split E
holds 1,825 swechat and 2,000 aiv_cu sessions (`analysis/PREREG_E.md` §0). Of 25 candidate x unit rows, 9 survived, 7
were downgraded, 3 were killed and 6 could not be run (`analysis/SECOND_PASS.md` §1,
`analysis/out/phase_e/second_pass.json` `counts`). Split H is held out and is read once, after the code freeze
(`analysis/DESIGN.md` §5.2).

---

## 3. Hidden witnesses inside ordinary logs, and the attacks they catch

```mermaid
flowchart LR
    subgraph W["Witness already in the log"]
        W1["Request-id server clock<br/>R1, id_bracket"]
        W2["Usage ledger<br/>R5, ledger_tally"]
        W2b["Output-token accounting<br/>N2, inline_output_accounting"]
        W3["Harness timers<br/>P1 latency floor"]
        W4["Git commit times<br/>R3"]
        W5["Structure: the harness's second rendering<br/>R4, dual_render_recount"]
        W6["Recomputation<br/>N5 battery"]
        W7["Shadow state<br/>replayed file reads and writes"]
    end
    subgraph AT["Attack, synthetic, sw/CC split E"]
        A1["Back-dated response"]
        A2["Request-id swap or splice"]
        A3["Deleted response"]
        A4["Inline fabrication<br/>model writes its own tool output"]
        A5["Output substitution<br/>flipped error, changed digit, same-size swap"]
        A6["Consistent rewrite of k results"]
        A7["Execution-layer shim<br/>returns plausible output"]
        A8["Coherent forgery<br/>every field consistent"]
    end
    NONE["Nothing in the log can catch it"]
    W1 -->|"30 s: 488/500 vs 3/500"| A1
    W1 -->|"swap 486/500, splice 395/500, vs 3/500"| A2
    W2 -->|"396/500 vs 4/500"| A3
    W2b -->|"224/500 vs 83/500, partial"| A4
    W5 -->|"same-size swap 76/500 vs 0/500, partial"| A5
    W6 -.->|"no detecting cell"| A5
    W5 -->|"k=5: 205/500 vs 0/500, partial"| A6
    W4 -->|"k=2: 45/500 vs 0/500, partial"| A6
    W3 -.->|"in principle only, not shipped"| A7
    W7 -.->|"not measured in analysis/"| A5
    A8 --- NONE
```

Each witness is a field the agent does not write: the provider mints request ids with a clock inside them, bills
output tokens, and the harness stamps time and writes a second structured copy of some results. Against synthetic
attacks on sw/CC split E, the request-id clock flags a 30 s back-dated response in 488/500 sessions against 3/500
honest copies, an adjacent id swap in 486/500 and a nearest-time foreign id in 395/500 (`analysis/out/phase_e/n7_timing.json`
`cells`, keys `swechat/claude_code|E|R1_BRACKET|...`), with an honest stream rate of 11/3,325 = 0.00331 on E
(`analysis/SECOND_PASS.md` §4.1). The usage ledger catches deleted responses, 396/500 against 4/500, but its E split is
not blind, and output-token accounting is the only shipped check with power against an attack inside the threat
model, inline fabrication, where it is only partial: 224/500 against 83/500 (`analysis/out/phase_e/n7_content.json`
`cells`; `analysis/DESIGN.md` §1.5). Output substitution, consistent rewrites, reordering, deleted pairs and inserted
pairs walk through: 10 of 21 attack types have no detecting cell in any detector, unit or split
(`analysis/SECOND_PASS.md` §6). A shim that returns plausible output, and any coherent forgery, passes by construction
(`analysis/DESIGN.md` §1.2, §1.4).

| Witness | What we measured (honest baseline, then synthetic attack) | Source |
|---|---|---|
| Request-id server clock (R1) | honest streams on E 11/3,325 = 0.00331; back-date 30 s 488/500 vs 3/500 | `analysis/SECOND_PASS.md` §4.1; `analysis/out/phase_e/n7_timing.json` |
| Usage ledger (R5) | honest sessions 23/3,165 = 0.0073 (B ∪ E); delete_response 396/500 vs 4/500 (E not blind) | `analysis/SECOND_PASS.md` §1 row 22; `analysis/out/phase_e/n7_content.json` |
| Output-token accounting (N2) | inline_fabrication 224/500 vs 83/500 (PARTIAL); 237/1,492 = 0.159 of honest sessions flagged | `analysis/out/phase_e/n7_content.json`; `analysis/DESIGN.md` Summary, from `n2.json` |
| Harness timers (P1 floor, N1) | results moved 5 s earlier: 257/500 vs 121/500 honest; N1 flags only 219/3,842 = 0.057 of tampered shell calls per call | `analysis/out/phase_e/n7_timing.json`; `analysis/SECOND_PASS.md` §6 |
| Git commit times (R3) | honest 2/976; consistent rewrite k=2 45/500 vs 0/500 (edit artifact) | `analysis/SECOND_PASS.md` §1 row 16; `analysis/out/phase_e/n7_timing.json` |
| Structure: dual rendering (R4) | honest 0/2,998 sessions; rewrite k=5 205/500 vs 0/500; same-size swap 76/500 vs 0/500 | `analysis/SECOND_PASS.md` §1 row 20; `analysis/out/phase_e/n7_content.json` |
| Recomputation (N5 battery) | determinism, sort order, truncation, whitespace and cold start are DEAD in sw/CC (determinism drift 491/1,745 = 0.281); no content detector reaches DETECTS | `analysis/SECOND_PASS.md` §6 |
| Shadow state | not measured in `analysis/`. The nearest relative, P2 knowledge precedence, never reached ALIVE (honest E rate 608/4,466 = 0.136) | `analysis/SECOND_PASS.md` §1 row 5 |

---

## 4. Verifier data flow

```mermaid
flowchart TD
    IN1["Raw transcript<br/>Claude Code JSONL, Codex, OpenCode,<br/>Gemini CLI, ATIF trajectory"]
    IN2["IR parquet cache<br/>splits A, B, E"]
    IN3["Python list of turn dicts"]
    IN4["Eval pack<br/>attacks applied by eval/"]
    LD["verifier/loaders<br/>sniff the format, reuse the analysis/loaders parsers"]
    IR["IR events, one row per event<br/>analysis/lib/ir.py"]
    SE["Session<br/>call/result pairs, responses, clocks,<br/>capabilities, sidecar fields"]
    REG["registry: for each enabled check"]
    G1{{"Required fields present?"}}
    G2{{"Check applies to this session?"}}
    U1["unconstrained<br/>missing: field"]
    U2["unconstrained<br/>abstain: not applicable"]
    RUN["check.run<br/>one CallVerdict per call, with evidence"]
    CO["compose<br/>contradicted beats supported beats unconstrained<br/>reference checks never decide"]
    VE["Verdict per call<br/>verdict, rule, reason, evidence events, blame"]
    O1["CLI table"]
    O2["JSONL + session.json"]
    O3["Static HTML page<br/>evidence inline"]
    O4["eval/run_eval.py<br/>joins tamper labels, scores"]
    IN1 --> LD
    IN2 --> LD
    LD --> IR
    IN3 --> IR
    IN4 --> IR
    IR --> SE --> REG --> G1
    G1 -->|"no"| U1
    G1 -->|"yes"| G2
    G2 -->|"no"| U2
    G2 -->|"yes"| RUN
    U1 --> CO
    U2 --> CO
    RUN --> CO --> VE
    VE --> O1
    VE --> O2
    VE --> O3
    VE --> O4
```

Every input, whatever its format, becomes the same event table (the IR in `analysis/lib/ir.py`), and one session's
events become a `Session` that records which fields this log actually carries (`analysis/DESIGN.md` §2.3). Each check
is a plugin that declares the fields it needs; if they are missing, every call gets `unconstrained` with the reason,
so a gap in the data is reported as lost coverage, never as a detection. Composition is a fixed order, not a vote:
any `contradicted` wins, then `supported`, then `unconstrained`, and a statistical check may contradict but never
support (`analysis/DESIGN.md` §4.6, DA2). The scaffold runs end to end with the reference check only: 115 tests ran
and passed with 1 slow test skipped, and the demo session gives 17/17 calls `unconstrained` because no detection
check is enabled yet (`analysis/out/phase_e/scaffold_check.json` `tests`; `analysis/out/phase_e/demo/demo_meta.json`).
The planned checks, in build order, are `id_bracket` and `inline_output_accounting` (MUST), `ledger_tally` and
`dual_render_recount` (SHOULD) and `latency_floor` (COULD) (`analysis/DESIGN.md` §7.2).

---

## 5. Evaluation protocol

### 5a. How the corpus measurements were run

```mermaid
flowchart TD
    PRE["Pre-register the rule and its thresholds<br/>commit before any outcome exists"]
    CAL["Calibrate thresholds on split A only,<br/>measure on split B, replicate on fresh split E"]
    AC["Artifact checks AC1 to AC5<br/>parser, truncation, join, dominance, sampling<br/>can only lower a label"]
    HON{{"Honest leg passes?<br/>rate at most 0.05, CI high at most 0.10"}}
    ATK{{"Synthetic attack leg<br/>recall at least 0.5 and<br/>recall CI low above honest CI high?"}}
    DET["DETECTS"]
    PAR["PARTIAL<br/>separates, recall under 0.5"]
    BL["BLIND"]
    V3["The verifier reports three verdicts per call<br/>contradicted, supported, unconstrained<br/>unconstrained is shown as coverage, not hidden"]
    RPT["Report per unit and per threat class<br/>never pooled across corpora"]
    H["Split H: read once, after the freeze, every read logged"]
    PRE --> CAL --> AC --> HON
    HON -->|"no"| BL
    HON -->|"yes"| ATK
    ATK -->|"yes"| DET
    ATK -->|"separates only"| PAR
    ATK -->|"no"| BL
    DET --> V3
    PAR --> V3
    V3 --> RPT --> H
```

Every rule and threshold was written down and committed before the data that judges it was read: thresholds come from
split A, and the first measurement is on B, with E as the replication (`analysis/PREREG_E.md` §0). A check decides on
a unit only if its honest leg passes the pre-registered bar there, a rate of at most 0.05 with a CI high of at most
0.10 (`analysis/DESIGN.md` DA16). Against an attack, DETECTS needs recall of at least 0.5 and a recall CI low above
the honest CI high; separation with lower recall is PARTIAL (`analysis/out/phase_e/n7_content.json`, `deciding_number.rule`
in each cell). Results are reported per unit and per threat class, never as one pooled number (`analysis/DESIGN.md`
DA12). `unconstrained` is an answer, not a failure, and the share of calls that get it is reported as coverage
(`analysis/DESIGN.md` §1.3).

### 5b. How the swarm labeled dataset is tested

```mermaid
flowchart TD
    DB["Swarm labeled dataset, read-only<br/>v_blind: the claimed output and its context<br/>observed: provenance the session itself produced"]
    WIT["Witness and label data<br/>real output, host stdout, answer labels"]
    SPLIT{{"sha256 of session_id, mod 2"}}
    DEV["dev: build and tune rules,<br/>look at labels here only"]
    SOUND{{"Soundness gate<br/>fires on 0 honest real executed calls<br/>and 0 honest swarm tool results?"}}
    DROP["Rule dropped"]
    FREEZE["Freeze rules and thresholds into a JSON"]
    TEST["test: score once with the frozen rules"]
    SCORE["Join labels only at scoring<br/>contradicted, supported, or unconstrained as an abstention"]
    STRATA["Report per stratum, never pooled<br/>source, spoof class, unit, instructed to lie, consistency,<br/>and the honest trap classes"]
    DB --> SPLIT
    SPLIT -->|"0"| DEV
    SPLIT -->|"1"| TEST
    DEV --> SOUND
    SOUND -->|"no"| DROP
    SOUND -->|"yes"| FREEZE --> TEST --> SCORE --> STRATA
    WIT -.->|"scoring only, never inside a detector"| SCORE
```

The swarm dataset is an outside input with labels, so it gets its own split: a session goes to dev when the sha256 of
its id is even and to test when it is odd, and labels are looked at on dev only. A rule is kept only if it fires on
zero honest calls, checked against every honest real executed call and every honest swarm tool result, because one
false `contradicted` makes the tool useless. Rules and thresholds are frozen into a JSON before the test split is
scored. Detectors never read the real output, host stdout or the labels; those are joined only when scoring, and
`unconstrained` counts as an abstention, not a miss. Results are reported per stratum (source, spoof class, unit,
whether the agent was told to lie, consistency) and separately for the honest classes that look like positives, such
as an agent quoting a false value in order to refute it.

---

## 6. Results at a glance

```mermaid
flowchart TD
    ROWS["25 candidate x unit rows, second pass"]
    SV["SURVIVES 9"]
    DG["DOWNGRADED 7"]
    KL["KILLED 3"]
    NR["NOT_RUN 6"]
    AL["Final ALIVE 3, all in sw/CC<br/>R1 request-id bracket, replicated on blind E<br/>R5 usage ledger, E not blind<br/>P3a zero-error tail, baseline only"]
    WK["Final WEAK 13<br/>P1 latency, P2 knowledge precedence,<br/>P4 round numbers, R3 git, R4 dual render"]
    DD["Final DEAD 3<br/>R2 image ledger, P4 pooled, P2 aiv_cc"]
    ROWS --> SV
    ROWS --> DG
    ROWS --> KL
    ROWS --> NR
    SV --> AL
    SV --> WK
    DG --> WK
    KL --> DD
```

```mermaid
flowchart LR
    GRID["N6 transfer grid<br/>396 loaded mechanism x unit cells"]
    DEC["Decided: 87"]
    UND["Not decidable: 309"]
    G_AL["ALIVE 7<br/>19 before the artifact checks and kill tests"]
    G_WK["WEAK 41"]
    G_DD["DEAD 39"]
    G_IN["INSUFFICIENT_N 110<br/>too few sessions"]
    G_NT["NOT_TESTABLE 172<br/>a required field is absent"]
    G_NR["NOT_RUN 26, per stratum 1"]
    GRID --> DEC
    GRID --> UND
    DEC --> G_AL
    DEC --> G_WK
    DEC --> G_DD
    UND --> G_IN
    UND --> G_NT
    UND --> G_NR
```

Three candidates survived every attempt to kill them, all in sw/CC: the request-id bracket (R1, replicated on a blind
E), the usage ledger (R5, E not blind) and the zero-error tail (P3a, a baseline with no positive control)
(`analysis/SECOND_PASS.md` §1, §8). R2 died on its honest rate, 44/807 = 0.0545 against a 0.05 budget; the pooled
round-number row collapsed without one model; and in sw/CC the reaction-time test and five of the seven N5 items are
DEAD (`analysis/SECOND_PASS.md` §7). Across the transfer grid only 87 of 396 loaded cells could be decided, and 7 are
ALIVE, down from 19 before the artifact checks and kill tests: most cells are undecidable rather than failed
(`analysis/SECOND_PASS.md` §6, `analysis/MORNING_BRIEF.md` §2, `analysis/out/phase_e/n6_grid.json`). Read plainly, the verifier we can ship mostly detects naive record editing; its
only in-scope power is partial, against inline fabrication, and a coherent forgery passes (`analysis/DESIGN.md` §1.5).
We do not claim the request-id bracket method: prior art for it exists (`analysis/PRIOR_ART.md`, B2 rows).

| The 7 ALIVE grid cells | Held at WEAK | Died (KILLED or DEAD) |
|---|---|---|
| R1 request-id bracket, sw/CC: honest 21/7,008 streams = 0.00300 | P1 latency floor, all 3 second-pass units | R2 image-token ledger: honest 44/807 = 0.0545 |
| R5 usage ledger, sw/CC: honest 23/3,165 = 0.0073 (E not blind) | P2 knowledge precedence | P4 round numbers, swechat pooled |
| P3a zero-error tail, sw/CC: E 8/380 = 0.021 (baseline only) | P4 round numbers, sw/CC and cc_local (after F3) | P2 knowledge precedence, aiv_cc (one agent) |
| N1 conditional duration, sw/CC, and aiv_cc (one agent, B only) | R3 git window: honest 2/976 | N3 reaction time, N5a to d and N5g, in sw/CC |
| P4b round numbers, tbench2 (Phase B rule only); N2 token accounting, agentcap/opencode (one corpus) | R4 dual render: honest 0/2,998 sessions | 10 of 21 attack types: no detecting cell anywhere |

Sources: `analysis/SECOND_PASS.md` §1, §6, §7; `analysis/MORNING_BRIEF.md` §2, §3; `analysis/out/phase_e/second_pass.json`;
`analysis/out/phase_e/n6_grid.json`.

## Swarm dataset results

```mermaid
flowchart TD
    DB["spoof_v1.db, read-only<br/>31,987 rows; test split 16,112"]
    V["Session view per row<br/>tampered transcript, spliced honest transcript,<br/>or honest transcript"]
    T0["T0 structural<br/>call and turn chain"]
    T1["T1 recompute<br/>output vs the call's own inputs"]
    T3["T3 shadow state<br/>files and git state seen so far"]
    TC["TC token conservation<br/>server token counts vs logged text"]
    CL["Claim provenance<br/>published claim vs own record"]
    OURS{{"Combined: contradicted if any check contradicts"}}
    BASE["Baseline oracles, swarm/delta.py<br/>tool outputs 368 / 5,948 = 0.062"]
    R1["Ours, test: tool outputs 3,778 / 5,948 = 0.635<br/>claims 144 / 164 = 0.878"]
    R2["Union with the baseline, test<br/>tool outputs 4,041 / 5,948 = 0.679<br/>claims 145 / 164 = 0.884"]
    S["Soundness: 0 false positives on 179,365 honest calls<br/>and on 10,000 honest test rows"]
    DB --> V
    V --> T0
    V --> T1
    V --> T3
    V --> TC
    DB --> CL
    T0 --> OURS
    T1 --> OURS
    T3 --> OURS
    TC --> OURS
    CL --> OURS
    OURS --> R1 --> R2
    BASE --> R2
    S -.-> R1
```

We tested five frozen checks on the test split of the swarm team's labeled dataset, scoring it once. Each check fired on 0 of 179,365 honest tool calls and on 0 of 10,000 honest test rows. On fabricated tool outputs the combined verdict contradicts 3,778 of 5,948 (0.635), against 368 (0.062) for the baseline. On fabricated claims it contradicts 144 of 164 (0.878), against 38 (0.232) for the baseline. The union with the baseline reaches 4,041 (0.679) and 145 (0.884), still with no false positives. Two numbers are close to built in: injected_I-struct 780/780 (T0) and injected_I-recompute 743/744 (T1), because the injector creates those two classes from the very invariants these checks test.

What stays out of reach is the coherent forgery. On test, ours abstains on 2,169 of the 5,948 fabricated tool outputs, mostly counterfactual (834 of 1,149) and tiered (823 of 1,465) rows whose output cannot be recomputed from the transcript and whose token count is within tolerance. This dataset cannot test the request-id clock (vLLM ids carry no time) or the timing mechanisms (forged rows keep the original timing). Full tables: `analysis/SWARM_DATASET_RESULTS.md`; numbers: `analysis/out/swarmds/test_scores.json`.
