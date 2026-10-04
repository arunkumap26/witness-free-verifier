# DESIGN: witness-free verification of agent tool-log results (plan of record for the build)

> **Status update (orchestrator, after the critic pass):** the Track A item JSONs, `second_pass.json` and `n6_grid.json` this file cites are now committed (ed2c1d4, f829639), so the G0 precondition on uncommitted sources is met. This file is committed (2baebcf). The scaffold built to it is committed (5f837b6); its layout deviations from §2.1 (API in `verifier/__init__.py`, a single `verifier/session.py` module, figures in `verifier/figures.py`) are listed in `analysis/out/phase_e/scaffold_check.json`.

Status: **plan of record for the 2026-10-04 build**, written 06:40–07:15 CDT for Track C (`analysis/PHASE_E_PROMPT.md`,
C1). Not committed. It starts from `analysis/DESIGN_ARCH_DRAFT.md` (critic-reviewed), keeps its architecture, decisions
DA1–DA12, interfaces, schema, eval design, CLI and demo surface, and fills every `TODO-TRACK-A` placeholder from the
Track A item outputs and the Track B verdicts. Sections 1–6 are the draft with Track A content folded in; section 7 is
new (per-check designs, feature tiers, build order, cut list, risks). Real detection checks are **not** implemented by
this document or before the morning gate (§7.3, gate G0).

**Nothing described here exists yet.** At the critic pass (07:20 CDT) there is no `verifier/` directory, and `eval/`
holds only the pre-existing `core.py` (plus a file owned by another division). Every recall, false-positive and ADR
number in this file was measured by a **Track A probe** (`analysis/probes/phase_e_*.py`), not by the verifier. The
verifier inherits a number only after a parity test reproduces it (DA15). A critic pass edited this file in place;
its changes are listed in Appendix C.

## Summary (ten lines)

1. We build `verifier/`: from a transcript alone, every tool call gets `supported` / `contradicted` / `unconstrained`
   plus the deciding evidence. No narration, no LLM, no external witness. Architecture as in the draft (DA1–DA12).
2. **MUST check 1, `id_bracket`** (request-id clock bracket, R1): ALIVE in swechat/claude_code [resolved here,
   §7.1.1; the Track A assembly now agrees, SP `r1_rows`]. Honest inconsistent streams on E are 11/3,325
   [F1 `f1_effective_fp."swechat/claude_code".E.honest`]. Track A's R1 probe flagged a 30 s back-dated response in
   488/500 sessions against 3/500 honest [N7T `cells."swechat/claude_code|E|R1_BRACKET|time_response_early|30"`].
3. **MUST check 2, `inline_output_accounting`** (N2 token accounting): among the mechanisms that survived Track A, the
   only one whose power on the in-scope execution-path class is not an edit artifact (§1.5, DA13). That power is
   against inline fabrication only, and it is only PARTIAL in swechat/claude_code: 224/500 against 83/500 honest
   [N7C `cells."swechat/claude_code|E|N2|inline_fabrication|tau"`].
4. **SHOULD:** `ledger_tally` (R5; ALIVE, swechat only, session-level; delete_response 396/500 vs 4/500
   [N7C `cells."swechat/claude_code|E|R5_LEDGER|delete_response|-"`]) and `dual_render_recount` (R4; WEAK; 0/2,998 honest
   sessions [R45 `R4.units."swechat/claude_code".verdict_blocks.BuE`]). **COULD:** `latency_floor` (P1, cc_local only).
   Nothing else becomes a check or a feature (§7.1.6): N1, N3, N4, N5, P2–P4, R2 (killed) and R3 (external witness,
   prior art UNVERIFIED). P3 survived Track A but has no Track B verdict, so it is cut, census statistic included.
5. **What this cannot do.** R1, R4 and R5 see only naive record editing. In the in-scope class, only N2 among the
   shipped checks has power that is not an edit artifact, and only against inline fabrication. A shim that returns plausible output passes. A coherent forgery passes. Every
   positive so far is SYNTHETIC: no corpus we hold has a known fabricated tool result.
6. **Material limitation.** The Anthropic request-id clock is reverse-engineered: the layout is undocumented and has no
   stability promise (`PRIOR_ART.md` B2 fact row). R1 therefore runs only where Claude Code talks to Anthropic, in 5
   of the 21 corpora we hold [CI `registry.n_carriers`, `registry.n_corpora_held`]. Every decode is gated, and a
   failed decode is lost coverage, never a detection (DA20).
7. **Gate (DA15).** A check is enabled only if it reproduces the Track A numbers on E exactly (parity tests) and passes
   the §5.7 criteria in one full-mode E run at about 13:30. H is read once, after the 15:00 freeze.
8. **Timeline (America/Chicago).** Scaffold from 08:00, once this critic pass ends (§7.3 re-sequences lane A so the
   check lanes still start at G0). Gate G0 at 09:30 (assumed). Checks in parallel lanes 09:30–13:15. Enable run and
   decision 13:30–14:45. Freeze 15:00. H run after the freeze. Cut order in §7.4.
9. **New decisions DA13–DA21.** The main ones are DA13 (execution-class credit per (check, attack)), DA14 (sidecar
   records for harness fields the IR drops), DA15 (parity gate) and DA16 (per-unit enable rule for statistical checks).
10. **Human decisions (open items).**
    - Enable N2 on Claude Code formats at a session-level honest cost of 237/1,492 = 0.159
      [N2 `units."swechat/claude_code".groups."swechat/claude_code".results.E.session_level_honest_flag_share`]?
    - **Blocking:** commit the Track A item JSONs before G0. 15 of the 34 cited files are uncommitted (Appendix A),
      so until then this design does not meet the rule that every number cites a committed file.
    - The merges, and the deviations from `SCOPE.md`.

**Number provenance.** Every measured number carries a bracketed source: `[TAG key.path]`. TAG names a file in the
Appendix A table, which gives its path, its raw-byte sha256 prefix and whether it was committed when this was written.
Keys are JSON paths; a quoted segment is one key that contains `/` or `|`. Hour estimates, budgets and judgment
constants carry no source; they are labelled *(estimate)* or *(judgment)*. Numbers that only describe the draft's
interfaces (MAX_CORE, pack sizes, seeds) are constants, not findings.

**Track A synthesis.** `SECOND_PASS.md` and `TRANSFER_MATRIX.md` did not exist when this was written. Survival labels
are read directly from the item JSONs. Where an item JSON left a label pending (R1: `PENDING_N7`), this document
applies the rule that item stated. Each such resolution is marked **[resolved here]**, so the morning reviewer can
check it.

*Critic cross-check (07:20).* Both files now exist, uncommitted, and `SECOND_PASS.md` was still being edited. Their
assemblies agree with every survival label this design uses for the kept checks:
- R1: swechat/claude_code SURVIVES → ALIVE, and cc_local DOWNGRADED → WEAK [SP `r1_rows`];
- R4 and R5: SURVIVES → WEAK and ALIVE [SP `r2_r5_rows`];
- P1: WEAK in all three units [SP `a1_rows`].

There is one disagreement. The N6 grid labels R1 on tbench2 **ALIVE** [N6 `cells.R1_bracket.tbench2.label`]. This
design keeps the committed resolution's **WEAK** [RES `resolutions[0].label_after`]: the whole tbench2 R1 population
is one submission, so the AC4 cap applies (§7.1.1, open item 17).

Inputs read (beyond the draft's): the Track A item outputs `analysis/out/phase_e/{f1_bracket, f2_floor_shift, f3_round,
a1_p1_p3, a1_p2_p4_f3, n1, n2, n3, n4_n5cg, n5_battery, n7_timing, n7_content, r2_r3, r4_r5}.json` and their notes
`analysis/notes/phase_e_*.md`, the new-corpus results `analysis/out/phase_e/newcorp_measure_*.json` and
`newcorp_resolutions.json`, the new-corpus calibration files `prereg_e_calibration_<corpus>.json`, `PRIOR_ART.md` in
full, `analysis/probes/prereg_e_common.py` (bracket, N2, injector code), `analysis/probes/phase_e_f1_bracket.py`
(corrections), `analysis/probes/phase_e_n7_content.py` (R4/R5 detectors), `analysis/lib/cc_jsonl.py` (which harness
fields the IR keeps).

Inputs the draft read: `analysis/PHASE_E_PROMPT.md` (Track C), `SCOPE.md` §2, §3, §5 and §8 (plan of record and contracts),
`PROJECT_BRIEF.md` §5–9, `analysis/README.md`, `analysis/lib/ir.py`, `analysis/loaders/*.py`,
`analysis/HELDOUT_MANIFEST.json`, `analysis/FINDINGS.md` §1, `analysis/DECISION_TABLE.md`, the `analysis/PRIOR_ART.md`
verdict table, `analysis/CORPUS_INVENTORY.md` §0–1, `analysis/PREREG_E.md` §0, and `analysis/prereg_e.json`
(`n7_attack_battery`, `n6_transfer_grid`). The critic pass also read `eval/core.py`, `ops/orchestrate.py`
(`snapshot_eval`, `run_eval`, the climb keep/reject logic), `prereg_e.json` `change_log` (D1, D5, D6), the
`prereg_e_calibration_*.json` unit keys, `analysis/loaders/load_agentcap.py` `split_incident`,
`analysis/probes/phase_e_n7_timing.py` `inject` / `target_units`, `analysis/lib/stats.py` and
`analysis/out/recon/swechat_scan_pinned.json`.

**Decisions this design makes.** A reviewer may overrule any of them. Each is argued where it is made. DA1–DA12 come
from the critic-reviewed draft. DA13–DA21 are new here and were made after reading the Track A outputs.

| # | Decision | Section |
|---|---|---|
| DA1 | `verifier/` **imports** the IR from `analysis/lib/ir.py` through one re-export module and pins its schema hash. It does not vendor a copy | 2.4 |
| DA2 | Composition is a lattice: **contradicted > supported > unconstrained**. There is no confidence-weighted vote, and every per-check verdict is reported | 4.6 |
| DA3 | `confidence` is a **frozen per (check, unit) constant** taken from split-A calibration and Track A outputs, never a per-call posterior and never fit on H. Identity checks carry the same file (no thresholds) and get `None` where it has no entry | 3.3 |
| DA4 | A statistical check on a unit it was not calibrated on **abstains** (`abstain:uncalibrated_unit`). The eval borrows only by the pre-registered proxy map (`prereg_e.json` change_log D1); the CLI borrows by format and says so | 4.5 |
| DA5 | The climb loop and day-to-day eval run on **E**. **H** is read only by an explicit `--final` run, and every H read is logged. This deviates from `SCOPE.md` §4/§8.2 (see the deviations table) | 5.2 |
| DA6 | The attack battery, metrics and H access live in the repo-level `eval/` (the frozen judge), not inside `verifier/`. The eval imports **only** `verifier.verify_session` from the code under test, and nothing from `analysis/` at score time | 2.1, 5.1 |
| DA7 | One verdict per **call**. Orphan results are counted and listed but never judged | 3.2 |
| DA8 | **No new packages.** HTML and figures are written with the standard library plus inline SVG: no jinja2 and no matplotlib. A root `requirements.txt` pins the four packages `analysis/requirements.txt` already pins (CLAUDE.md rule 6) | 6 |
| DA9 | The demo uses a session from **split E** of a corpus whose licence permits redistribution, never from H, and never `cc_local` or `aiv_*` content | 6.3 |
| DA10 | An FPR-gate breach is a **clean reject**, not an eval failure: `ok: true`, `headline: -1.0`, `gate: "<reason>"`, exit 0. `ok: false` is kept for crashes and check exceptions | 5.1, 5.5 |
| DA11 | `contradicted` may come only from a rule that compares a field the agent controls with one it does not, with a physical bound, or with another record no honest execution could have produced beside it (§4.1 types 1–3). A distributional anomaly (a base-rate statistic over a session) is never a per-call `contradicted`; it can be a census statistic, but only if it also cleared Track B (§7.0) | 4.1 |
| DA12 | The climb headline weights the two threat classes **equally** and is the **mean of per-seed values** (as `eval/core.py` computes it). It is a climb score; reported results are per cell and per class | 5.5 |
| DA13 | **Execution-class credit is per (check, attack).** A hit in an execution-path cell counts toward the execution headline only if the pair is in `EXEC_CREDIT` = {(`inline_output_accounting`, `inline_fabrication`)}. Every other hit in an execution cell happened because the battery left a dependent field unrepaired that a real shim would have kept consistent: request ids, the session tally, or the harness line counter. Those hits are reported per cell as `edit_artifact` and excluded from `adr_loc_macro_exec` | 5.4 |
| DA14 | **Sidecar records.** Harness-written fields the IR drops (Claude Code `toolUseResult.numLines`, the SWE-chat Entire session tally, the corpus-level copied-request-id index) travel beside the IR in `Session.sidecar`. They do not travel inside `extra`, and `analysis/lib` is not edited. Loaders and `eval/heldout.py build-pack` fill them; attacks never touch them | 2.7, 4.2 |
| DA15 | **Parity gate.** A check is enabled only after a parity test shows its implementation reproduces the Track A item's numbers on the same split, exactly. If parity fails, the check ships registered but disabled, and the failure is reported. Track A verdicts transfer to the verifier only through parity | 5.7, 7.1 |
| DA16 | **Per-unit enable rule for statistical checks.** A statistical check decides only on calibration units whose honest leg passed the **pre-registered** ALIVE false-positive condition on E (B for units without E): rate ≤ 0.05 and CI hi ≤ 0.10 in the check's own decision unit. Other calibrated units carry `enabled: false` in the calibration file, and the check abstains there (`abstain:unit_not_enabled`) | 4.5, 7.1 |
| DA17 | **`id_bracket` v1.0.0 is exactly F1's adopted rule set:** the 2,000 ms tolerance plus the two corrections adopted on B (restamped-copy dedupe, user-input-binding drop). The post-hoc "ordered inputs" correction is pre-registered here, before any H read, as a reported variant (v1.1.0-candidate). It does not ship enabled | 7.1.1 |
| DA18 | A check may **lower** the strength of a single verdict below its class strength, never raise it. `ledger_tally` support is session-level and constrains existence, not content, so it is `format`. `dual_render_recount` is `format` throughout, because one writer produces both renderings | 4.1 |
| DA19 | **Calibration lookup.** A new corpus uses values from its own split-A calibration file first (`prereg_e_calibration_<corpus>.json`), as the new-corpus measurements did. It falls back to its `change_log` D1 proxy unit only for quantities that file does not produce. This refines DA4's "borrow by the proxy map" | 4.5 |
| DA20 | **The id decoder gates on layout.** `idclock` accepts an Anthropic `req_` id only if the decoded 128-bit value has UUIDv7 version and variant bits, on top of `prereg_e_common.decode_req_ms`'s regex and date window. A format failure is `missing:request_id.decodable`, never a contradiction. A session whose ids all fail is flagged `id_layout_unrecognized` in `session.json` | 2.4, 7.1.1 |
| DA21 | **Tests use stdlib `unittest`.** pytest is installed on the dev box, but it is not in any requirements file (CLAUDE.md rule 6). pytest can still discover the tests | 2.1 |

**Deviations from `SCOPE.md` this design makes** (each needs the human's sign-off at the morning merge):

| SCOPE says | This draft | Why |
|---|---|---|
| §4: SWE-chat split **by repo**, 80/20 dev/held-out; §8.2: `eval/core.py` uses held-out only | H is the Phase E session-level split (`HELDOUT_MANIFEST.json`); the climb loop is scored on E; H is read once after the freeze | H already exists and is pre-registered; scoring every climb iteration on H would tune against it (`PHASE_E_PROMPT.md` C2: "never touched during tuning"). Cost: H shares repos and operators with E (§7.5) |
| §3: "The eval imports only" `verify_session(turns)` | `verify_session` also accepts one session's IR `DataFrame` (§2.6); the eval still imports only that function | Packs are IR; turning IR into `turn` dicts would drop request ids, usage and error flags (open item 3) |
| §8.2: headline = pooled detection rate over all positives | ADR macro over fixed cells, threat classes weighted equally (DA12) | ADR charges a check for flagging the honest copy; macro stops one attack family dominating |
| §8.2: `ok: false` when the clean rate exceeds `CLEAN_CAP` | DA10 | `ops/orchestrate.py` counts `ok: false` toward its 3-consecutive-failure halt; a too-noisy candidate is a reject, not a broken harness |
| §8.1: effective coverage on the CF M2 set is the headline | Not computed here; the CF set can arrive as a labeled corpus (§3.4) | The CF set comes from the swarm, which is outside this division's scope |
| §5.7: census over the full pinned corpus | Same, but as `eval/heldout.py census --final --freeze` after the H eval run (§5.2 rule 3) | The full corpus contains H, and `verifier/` has no notion of H |
| §2 deliverable 3: the demo shows "the same fabricated `tool_result`" contradicted | The primary demo tamper is a 30 s back-dated response (record editing, caught by `id_bracket`). A second page shows the in-scope `inline_fabrication` tamper caught by `inline_output_accounting`, with its honest false-positive rate on the page (§6.3) | No check reaches DETECTS on a fabricated result *content* at an acceptable honest rate (§7.1); showing one as if it did would overclaim |
| §3 `verdict.core: [turn_id...]` | `turn_id`s when the session came from turns, else `"seq:<n>"` strings (§3.3) | Raw-file inputs have no turn ids |

---

## 1. Problem, threat model, user view, non-goals

### 1.1 Problem statement (three sentences)

Agent harnesses record what each tool call returned, and graders, other agents and human reviewers now treat those
records as evidence, yet nothing checks whether a recorded result could actually have come from the call it is
attached to. When the agent controls the execution path (a shimmed binary, a wrapper script, a tool server it
launched, or a parser that lets the model write its own observation), the harness faithfully records a lie, and every
check that only asks whether a call happened passes it. We build a retrospective, witness-free verifier that reads only
the log and asks whether each recorded result is consistent with the fields of the same record that the agent does not
control and with the physics of how such a result is produced.

### 1.2 Threat model (stated explicitly)

**In scope: execution-path compromise.** "In scope" means this is the class we model and measure against, not a class
we detect in general (§1.4). The agent controls what a tool returns: its stdout, stderr and, through a
shim, its exit status. The harness is honest. It records the call the agent made, stamps its own clock when the call
and the result happen, and stores the provider metadata (request ids, message ids, usage counters) exactly as the
provider returned them. This covers PATH shims and aliases (the METR mechanism, `SCOPE.md` §7.8 N-planted), wrapper
scripts, agent-launched tool servers, and the leaky ReAct parser in which the model writes its own `Observation:` and
no tool runs (`SCOPE.md` §7.12, condition L; `prereg_e.json` attack `inline_fabrication`).

**Who controls each field under the in-scope threat.** A check is sound against this threat only where it compares a
field the agent controls against a field it does not, or against a physical bound (§4.1 types 1–2). A check that finds
two agent-controlled records disagreeing (type 3) catches only an attacker who does not keep its fabrications
consistent. This table is the basis for every per-check soundness argument in §7.1.

| IR field(s) (`analysis/lib/ir.py` COLUMNS) | Written by | Can the agent alter it under execution-path compromise? |
|---|---|---|
| `text`, `stderr` of a `result` | tool → harness | **Yes.** This is the primary attack surface |
| `native_error`, `exit_code` | harness, from the tool's exit status | **Yes**, when a shim sets the exit status |
| `ts` of a `result` | harness clock on receipt | **Only later than the call.** A shim can return at any moment after it is called and can sleep to look slow. So a result too *fast* for the work its call claims is evidence against it, and a result too *slow* is not. A canned-output shim is fast; only text generated at call time (inline fabrication, a model-backed shim) needs generation time, so a generation-time floor says nothing about a canned shim |
| harness timers in `extra` (e.g. `durationMs`, elapsed) | harness clock around the tool's execution | Same as the result `ts`: only longer |
| `ts` of a `call`, `user`, `assistant`; event order (`seq`) | harness clock; harness write order | No |
| `request_id`, `api_msg_id` | provider | No |
| `usage_in`, `usage_cache_*` | provider | Indirectly. Fake result text is billed as input on the next request, exactly like real text, so these fields constrain how much text was appended, not where it came from |
| `usage_out` | provider | No. Text the model writes inline is billed here. That is what catches `inline_fabrication` and nothing else (`PRIOR_ART.md` B3.4) |
| harness structured copy (e.g. Claude Code `toolUseResult.numLines`; not kept by the IR, so it travels in `Session.sidecar`, DA14) | harness, derived from the same tool output | It agrees with the fake text by construction. It catches post-hoc edits of the visible text only (`DECISION_TABLE.md`, rank 4: "One harness writes both renderings") |
| harness session tally (SWE-chat Entire `sessions.parquet` token totals and `api_call_count`; `Session.sidecar`) | harness capture tool, from provider usage | No. It sums provider-billed usage, so a real inline fabrication is in it too. It disagrees with the log only when someone edits the log afterwards (DA13) |
| `args`, `command`, `tool` | model, recorded by the harness | Chosen by the agent, but recorded honestly |
| narration (`assistant` text) | model | Yes. **The verifier never reads narration** |

**Secondary and measured, but not the headline: naive post-hoc record editing.** An editor changes some fields of a
finished log, such as a stamp, an id, or a deleted or inserted call pair, without repairing every dependent field. Most
of the pre-registered synthetic battery models this class (§5.4). It is a partial harness compromise. We report it
separately so that a detection on it is never presented as a detection of execution-path compromise.

**Out of scope, by definition, for any log-based method: full harness compromise.** If the attacker controls the writer
of the log, it can emit a record in which every field is mutually consistent: clocks, ids, usage and renderings. No
function of the log alone can tell that record from an honest one. The I-forge class (`SCOPE.md` §6) is the same thing
reached by editing, and it is reported as the ceiling, not as a target.

### 1.3 What the tool does, from a user's view

You give it a transcript: a Claude Code JSONL, a Codex rollout, an OpenCode or Gemini CLI export, an ATIF trajectory,
an IR parquet, or a list of `turn` dicts through the Python API. It parses the transcript into the shared event IR and
works out which fields this record actually carries (millisecond clocks, provider request ids, usage counters,
structured renderings, error flags). It runs every check whose required fields are present. For **every tool call** it
returns one of three verdicts:
- `supported`: a check constrained this result and it is consistent;
- `contradicted`: a check constrained it and it is not, with the events and numbers that disagree;
- `unconstrained`: nothing in this record can test it, with the reason, for example `missing:request_id`.

It prints a per-call table and writes JSONL plus a single static HTML page. On that page, the calls light up in
verdict colours and the deciding evidence sits inline under each call. Most calls in most corpora will be
`unconstrained`. The tool reports that share as **coverage** instead of hiding it, because "this cannot be checked from
the log" is the honest answer for those calls (`PROJECT_BRIEF.md` §7.2: "The third class is not a cop-out; it is the
contribution").

### 1.4 What it explicitly does not do

- **It does not establish truth.** `supported` means *consistent with the fields this check reads*, nothing more.
  Internal consistency is **necessary, not sufficient**. The write-up says this once and means it (`SCOPE.md` §5.6).
- **A coherent forgery passes.** Examples: a shim that returns plausible output after a plausible delay, for a command
  whose output no other record constrains; an I-forge rewrite; a fully compromised harness. All of them come out
  `supported` or `unconstrained`. Replacing the execution layer outright "produces a perfectly self-consistent log"
  (`PROJECT_BRIEF.md` §9); within the in-scope class, this tool can only catch the residue a shim leaves: content that
  contradicts another record, or timing and accounting the shim did not match.
- **Every positive detected so far is synthetic.** "No corpus contains a known fabricated tool result. Every cell
  describes the honest baseline. No cell is a detection rate" (`DECISION_TABLE.md`). Every recall number this tool
  reports comes from the pre-registered synthetic battery (§5.4), or later from a labeled corpus that does not exist
  yet (§3.4). The nearest thing to natural labeled positives we hold is the 4,525 tool results that sweagent combo2's
  harness itself flags as substituted [B5a `corpora_downloaded[3].field_audit.harness_labelled_synthetic_results.descriptive_latency_tool_ts_minus_assistant_ts_s.synthetic.n`].
  That count covers only the one shard Track B downloaded and audited (`trajectories_00 of 6`, [B5a `corpora_downloaded[3].name`]).
  Whether harness-written substitutes count as fabrication ground truth is UNVERIFIED (`PRIOR_ART.md` §3.12), and no
  loader reads that corpus yet.
- **It barely sees the in-scope class.** Of the checks that ship, only `inline_output_accounting` has power against an
  execution-path attack, and only against inline fabrication (§1.5). A canned-output shim, a substituted result of the
  right size, a flipped error, a changed digit, or reordered output lines gets no contradiction from any shipped
  check, except as an `edit_artifact` (DA13). The N7 walk-through lists these attacks as walking through every timing
  detector [N7T `verdicts.walk_through_timing_only`] and every content and accounting detector at DETECTS level
  [N7C `walkthrough`].
- **Orphan results are not judged** (DA7). A result whose call is missing (SCOPE §6 I-struct "orphan a result") is
  counted in the session summary, never given a per-call verdict, and is not in the eval battery.
- **Statistical anomalies are not contradictions** (DA11). A session that is merely unusual for its corpus (for example,
  long with zero errors) gets no `contradicted` verdict.
- **"Honest" means presumed honest.** False-positive rates are measured on public records nobody labeled. A
  `contradicted` verdict on such a record is either a false positive or a real incoherence. The census answers which
  only by manual review (`SCOPE.md` §5.7).
- It reads no narration, uses no LLM, needs no instrumentation, and consults no external witness such as git remotes,
  provider logs or wiki clocks. External-witness checks from Phase C are excluded from the core (§7.2).
- It does not repair, rank or attribute blame to agents. `blame_seq` names the probable *event*, not an actor.

### 1.5 What the shipped checks can address, per threat class (Track A consequence)

The checks are designed in §7.1. This table says, before any of them is built, which class each one can address and
why. "Credited" means the hit counts toward that class's headline (DA13).

| Check | Execution path (in scope) | Record editing (secondary) | Why |
|---|---|---|---|
| `id_bracket` (R1) | **No credit.** A shim cannot move the provider's clock; delaying a result only delays the next request, which keeps the bracket consistent | Credited: back-dated responses (≥ 10 s), late-moved results (≥ 5 s), swapped or spliced ids, some inserted pairs | Rule type 1: harness stamps vs the provider's id clock, which the agent does not control |
| `inline_output_accounting` (N2) | **Credited for `inline_fabrication` only.** Text the model generated and that was recorded as a tool result is billed as output tokens | Credited (an editor who moves model text into a result without repairing usage) | Rule type 2: an accounting bound on provider-billed `usage_out`. Blind by construction to a fake result returned through the harness, because that text is billed as input (`prereg_e.json` `n2_token_accounting.limit`) |
| `ledger_tally` (R5) | **No credit.** A real fabrication is billed and therefore sits in the tally too | Credited: deleted responses and deleted pairs; also inline fabrication, but only because the battery leaves the tally unrepaired (DA13) | Rule type 1: the log's usage vs the capture tool's tally |
| `dual_render_recount` (R4) | **No credit.** One writer produces both renderings from the same fake output | Credited: post-hoc edits that change a Read result's line count | Rule type 1 for record editing only (§4.1) |
| `latency_floor` (P1, COULD) | In principle, a canned shim that returns faster than the tool's honest floor | Credited: results moved earlier | Rule type 2: a physical floor. Shipped only on one private unit, so it is not a public claim |

**Plainly:** the shipped verifier is mostly a detector of naive post-hoc record editing. Its only in-scope power is
against inline fabrication, where it is PARTIAL in the largest unit (224/500 against 83/500 honest
[N7C `cells."swechat/claude_code|E|N2|inline_fabrication|tau"`]). A fabricated result *content* that returns through
the harness gets no contradiction from any shipped check. That is the measured state, and the write-up says so.

**Execution-class power outside the shipped set.** Track A found it in three other places. None of them qualifies as a
check:
- **P3 zero-error tail** on `sub_single_flip_error`: 8/500 against 0/500, PARTIAL
  [N7C `cells."swechat/claude_code|E|P3_ZERO|sub_single_flip_error|-"`]. It is distributional (DA11) and has no Track B
  verdict (§7.0).
- **N5d whitespace** on `rewrite_consistent_k` k = 5 in aiv_cu: 221/500 against 169/500, PARTIAL
  [N7C `cells."aiv_cu|E|N5d|rewrite_consistent_k|5"`]. N5d is DEAD and UNVERIFIED (§7.1.6).
- **R3 git window** on `rewrite_consistent_k` k = 2: 45/500 against 0/500
  [N7T `cells."swechat/claude_code|E|R3_GIT|rewrite_consistent_k|2"`]. This is an edit artifact for the same reason as
  `id_bracket`'s hit: later commit times are not shifted.

**One observation the class table does not encode.** `time_tail_early` (a result and every later event shifted
earlier) is also the timing footprint of a canned shim that answers fast. The only thing that differs is that the
battery does not re-mint later request ids. The class assignment of every attack was fixed in the draft before the
N7 recall files were read, and it is kept, so the headline is not fitted to the mechanisms. Whether to move
`time_tail_early` into the execution class (crediting `latency_floor` but not `id_bracket`) is open item 10.

### 1.6 The request-id dependency (Track B, B2)

`id_bracket`, the strongest check, rests on a clock the vendor does not document.

- **What is documented.** Nothing about the layout. The Anthropic errors page documents the `request-id` header and
  gives example values, with no format statement. The SDK says of message ids: "The format and length of IDs may change
  over time" (`PRIOR_ART.md` §1.2, B2 fact row: "Undocumented for every provider, with no stability promise. This is a
  MATERIAL LIMITATION").
- **What we infer.** `req_` + `01` + 22 base58 characters is a 128-bit RFC 9562 UUIDv7 holding 48 bits of Unix
  milliseconds. All 305,727 distinct swechat Claude Code request ids outside H carry v7 version and variant bits
  [B4 `REQUEST_ID_COLUMN_FIRST.per_corpus."swechat/claude_code".decodable_time.rfc9562_v7_version_and_variant_bits`].
  305,584 of them fall within [−2 s, +600 s] of their carrying event [B4 same path `.agrees_with_carrying_event_minus2s_plus600s`].
- **Observed instability.** Anthropic `msg_` ids switched from random to UUIDv7 on 2026-07-06 with no release-note
  entry [B2a `providers.anthropic.message_id_msg_.timestamp_embedded`]. OpenAI item ids changed layout three times
  [B2a `verdict_reasoning.VERDICT_REASONING_stability`].
- **It is unsigned.** The id is not a signature. A forger who learns the layout can re-mint consistent ids, and a relay
  that rewrites tool_use fields leaves the id, and so the bracket, intact (`PRIOR_ART.md` §1.4, design consequence 4).
  Re-minting is a coherent forgery: out of scope (§1.2) and stated.
- **Coverage.** Request ids exist only where Claude Code talks to Anthropic: 5 of the 21 corpora we hold
  [CI `registry.n_carriers`, `registry.n_corpora_held`]. Within swechat Claude Code, 380,855/388,605 = 0.980 of calls carry one
  [B4 `REQUEST_ID_COLUMN_FIRST.per_corpus."swechat/claude_code".calls_with_request_id`]. Bedrock-backed calls carry
  none: 3,575 calls [B4 same path `.calls_by_backend.anthropic_bedrock`].

**Design consequences (each implemented, §2.4 and §7.1.1).**
1. Every decode is gated on the per-family layout (DA20). A failed gate means `missing:request_id.decodable`.
2. A layout change is lost coverage, never a detection. `session.json` carries `id_layout_unrecognized: true` when
   every `req_`-shaped id of a session fails the gate. The census reports the decodable share per corpus per month, so
   a vendor change shows up as a coverage cliff, not as a wave of contradictions.
3. The 2,000 ms tolerance is a pre-registered design parameter (`prereg_e.json` `constants.BRACKET_TOL_MS`). It is not
   an accuracy the vendor promises.
4. Every user-facing `id_bracket` verdict prints "provider clock inferred from undocumented id layout" in `explain()`
   and in the HTML footer.
5. Prior art is cited, not claimed. The method is a time-anchor / clock-hypothesis consistency test (Willassen 2008;
   Vanini et al., primary UNVERIFIED), near-TAKEN as a method. NOVEL is only the application to LLM-provider request
   ids in agent tool logs, plus the single-response binding test (`PRIOR_ART.md` §1.4).

---

## 2. Module decomposition

### 2.1 Layout

```
verifier/                          # SCOPE.md §3: core division owns it; Python API verify_session(turns) -> list[Verdict]
  __init__.py                      # exports: verify_session, verify_sessions, verify_file, Verdict, CallVerdict, EventRef, __version__
  __main__.py                      # `python -m verifier ...` -> verifier.cli.main(sys.argv[1:])
  api.py                           # verify_session / verify_sessions / verify_file (input dispatch, no logic)
  ir/
    __init__.py                    # re-export of analysis.lib.ir + IR_SCHEMA_SHA pin (DA1)
    turns.py                       # SCOPE `turn` dicts <-> IR events: turns_to_events(), TURN_TO_IR
  session/
    __init__.py                    # Session dataclass, build_session(), split_sessions()
    capabilities.py                # CAPABILITIES: name -> predicate; detect_capabilities(events) -> frozenset[str]
    pairs.py                       # pair_calls(events) -> pairs frame; orphan_results(events)
    responses.py                   # group_responses(events) -> one row per provider response, usage deduped
    clocks.py                      # ClockView: ts_ms, resolution_ms, provider_ms
    idclock.py                     # provider id decoding (vendored from load_tbench2.id_family/id_embedded_ms + parity test;
                                   #   + UUIDv7 version/variant gate, DA20)
    threads.py                     # thread/stream keys from (is_subagent, agent_id)
    sidecar.py                     # SIDECAR_KEYS, Sidecar TypedDict, validate_sidecar() (DA14, 2.7)
  loaders/
    __init__.py
    detect.py                      # sniff(path) -> Format
    files.py                       # load_file(path, fmt) -> list[Session]   (one transcript; reuses analysis/loaders parsers)
    corpora.py                     # CORPUS_ADAPTERS: IR caches by split (A/B/E only; refuses H)
    units.py                       # unit_of(corpus, session_id, stratum, fmt) -> Phase E unit (2.5); DEFAULT_CALIBRATION_BY_FORMAT
    sidecar.py                     # read_cc_numlines(raw_path), read_entire_tally(session_ids), copied_request_ids(frames) (2.7)
  checks/
    __init__.py                    # imports every check module; ENABLED_CHECKS tuple (7.2)
    base.py                        # Check Protocol, constructors supported()/contradicted()/unconstrained(), Status
    ref_result_present.py          # reference check: proves the pipe end to end; never decides a verdict (4.8)
    id_bracket.py                  # MUST  R1 request-id clock bracket (7.1.1)
    inline_output_accounting.py    # MUST  N2 token accounting (7.1.2)
    ledger_tally.py                # SHOULD R5 usage ledger vs Entire tally (7.1.3)
    dual_render_recount.py         # SHOULD R4 numLines vs visible lines (7.1.4)
    latency_floor.py               # COULD P1 floor, cc_local only (7.1.5)
    _whitelist.py                  # frozen copies of prereg_e.json regexes dual_* and read_numbered_line (R4); parity-tested
    calib/                         # frozen per-check calibration JSON (thresholds + provenance), written by build.py
      build.py                     # day-time only, never imported by verifier: copies thresholds/fpr_hi/recall_lo from the
                                   #   analysis/out files named in source_files into <name>.json (4.7; sources in 7.1)
      id_bracket.json  inline_output_accounting.json  ledger_tally.json  dual_render_recount.json  latency_floor.json
  registry.py                      # REGISTRY dict, @register, run_checks(session, names) -> {check: {call_key: CallVerdict}}
  compose.py                       # compose(session, by_check, kinds) -> list[Verdict]
  render/
    text.py                        # terminal table, ANSI colour, --explain
    jsonl.py                       # Verdict / session summary serialization
    html.py                        # render_session_html(): single static file, inline CSS/JS/SVG
    figures.py                     # transfer-matrix and recall-per-attack SVG/HTML from an eval report JSON
    demo.py                        # build_demo(input_dir) -> demo/index.html (input written by eval/heldout.py demo-input; 6.3)
    demo_spec.json                 # primary demo: swechat/claude_code E, time_response_early D=30, seed 0 (6.3)
    demo_spec_exec.json            # second page: swechat/claude_code E, inline_fabrication, seed 0 (6.3)
  cli.py                           # argparse subcommands (6.1)

eval/                              # frozen judge (CLAUDE.md rule 3); merged to main by day (PHASE_E_PLAN.md "Track C location")
  core.py                          # existing contract file; main() delegates to run_eval.main (5.1)
  run_eval.py                      # entry point; last stdout line = ONE JSON object (eval/core.py contract); run_seed(repo, seed)
  heldout.py                       # H ids from samples/<c>_EH.json#H + manifest digest check; H cache build; pack build; access log
  attacks.py                       # frozen port of prereg_e.json n7_attack_battery on IR DataFrames (same names, same rng parts)
  metrics.py                       # FPR, recall, ADR, localization, coverage, transfer grid, disagreement
  _stats.py                        # vendored copies of analysis.lib.stats wilson/cluster_rate + Clopper-Pearson (parity test)
  labeled.py                       # labeled-corpus reader, split registration, join
  config_eval.json                 # frozen: seeds, pack dir, pack sizes, quick attack cells, unit maps, H exposure,
                                   #   EXEC_CREDIT (DA13), fpr_cap / CLEAN_CAP (5.5, written at the freeze baseline run)

requirements.txt                   # repo root: numpy==2.3.5 scipy==1.17.1 pandas==3.0.5 pyarrow==25.0.1 (as analysis/requirements.txt)

tests/                             # stdlib unittest (DA21); `python -m unittest discover tests`
  test_ir_parity.py  test_idclock_parity.py  test_turns_adapter.py  test_registry.py  test_compose.py
  test_check_purity.py  test_determinism.py  test_no_heldout_access.py  test_cli_smoke.py  test_attacks_parity.py
  test_eval_budget.py  test_eval_imports.py  test_stats_parity.py  test_sidecar.py  test_whitelist_parity.py
  parity/                          # DA15: one file per check; needs analysis/cache (E/B caches) + data/swe-chat-pinned,
                                   #   so it runs by day in the analysis worktree and is skipped (not failed) elsewhere
    test_id_bracket_parity.py  test_inline_output_accounting_parity.py  test_ledger_tally_parity.py
    test_dual_render_recount_parity.py  test_latency_floor_parity.py
```

**Module style inside `eval/`.** The orchestrator runs a copy of `eval/` at `ops/state/<div>/eval_snapshot/core.py`
(`ops/orchestrate.py` `snapshot_eval`), so `sys.path[0]` is that directory and it is not a package named `eval`. Eval
modules therefore import each other as top-level modules (`import attacks`, `from _stats import wilson`), never as
`eval.attacks`, and read `config_eval.json` from `Path(__file__).parent`.

**Why the eval sits outside `verifier/` (DA6).** The overnight climb loop edits `verifier/` and is scored by the eval.
If the attack battery or the metric code lived in `verifier/`, the loop could tune the attack it is scored against.
That is the Goodhart risk `SCOPE.md` §11 rates High, and it is why `SCOPE.md` §6 puts the injector in `eval/`. `eval/`
imports from the code under test **only** `verifier.verify_session` (and `verifier.__version__`). Attack eligibility,
targets and injection run on IR DataFrames inside `eval/`, so the climb loop cannot change which calls get tampered by
editing `verifier.session`. `verifier` never imports `eval`.

**Why the eval imports nothing from `analysis/` at score time.** The orchestrator rejects a candidate that touches
`eval/`, but not one that touches `analysis/` (`ops/orchestrate.py`, the `startswith("eval/")` check). If the scoring
path imported `analysis.lib.stats` from `--repo`, a climb agent could edit the statistics it is judged by. So the
score path uses `eval/_stats.py` (vendored, parity-tested), reads pre-built packs, and imports `analysis` only
indirectly, through `verifier`'s own IR re-export, which is code under test. `eval/heldout.py`'s build commands and
`eval/labeled.py register` import `analysis.loaders` and `analysis.lib.sample` inside those functions; they run by day,
by hand, never inside the climb loop. `tests/test_eval_imports.py` asserts that `core.py`, `run_eval.py`, `metrics.py`,
`attacks.py` and `_stats.py` contain no `analysis` import, and that `heldout.py` and `labeled.py` import it only inside
those day-time functions.

### 2.2 Responsibilities and dependencies

| Module | Responsibility | May import | Must not import |
|---|---|---|---|
| `verifier.ir` | The one import site of the IR schema. Its turn adapter normalizes `SCOPE.md` §3 `turn` dicts | `analysis.lib.ir` | anything else in `analysis` |
| `verifier.session` | Turns one session's IR frame into a `Session`: joins, responses, clocks, capabilities. Pure; no I/O | `verifier.ir`, numpy, pandas | loaders, checks, eval |
| `verifier.loaders` | Raw file or IR cache → `list[Session]`. Reuses the `analysis/loaders` parsers. Knows splits A/B/E, never H. `loaders.sidecar` re-reads the raw file for harness fields the IR drops (2.7) | `analysis.loaders.*`, `analysis.lib.cc_jsonl`, `verifier.session`, pyarrow | checks, eval |
| `verifier.session.sidecar` | The sidecar schema (`SIDECAR_KEYS`) and its validation. Pure | stdlib | everything else |
| `verifier.checks.*` | One plugin per mechanism. A pure function of one `Session` plus frozen calibration | `verifier.checks.base`, `verifier.session`, numpy, pandas, stdlib `json` (calibration only) | loaders, eval, file I/O at run time, `analysis.probes` |
| `verifier.registry` | Registration, applicability, run order, filling and validating per-call output, catching check exceptions | `verifier.checks.base`, `verifier.session` | loaders, eval |
| `verifier.compose` | Per-call precedence, disagreement, blame, final verdict | `verifier.checks.base` | everything else |
| `verifier.render` | Text, JSONL, HTML, figures and demo from `Session` + `Verdict` lists. Redacts and refuses private corpora | `verifier.compose` outputs, `analysis.loaders.newcorp_common.redact` | checks (it uses only `Check.explain` through the registry) |
| `verifier.api` / `cli` | Input dispatch, orchestration, exit codes | all verifier modules; `loaders` and `render` only inside `verify_file` and the CLI, never at module level (§5.1 import isolation) | eval |
| `eval` score path (`core`, `run_eval`, `metrics`, `attacks` apply, `_stats`, `labeled` join) | Attacks, metrics, the single-JSON judge output | `verifier.verify_session`, `verifier.__version__`, numpy, pandas, pyarrow, scipy | anything else in `verifier`; anything in `analysis` |
| `eval/heldout.py` build commands, `eval/labeled.py register` (by day) | Manifest check, E/H caches, packs, attack plans, demo input, labeled-set splits | `analysis.loaders.*`, `analysis.lib.sample`, `attacks` (imports inside the functions) | `verifier`, except `verify_session` for `heldout.py census` |

### 2.3 Data flow, raw transcript to rendered verdict

```
 raw transcript file            IR parquet cache (A/B/E)        list[turn dict] (SCOPE §3)      eval pack (E or H)
 (CC JSONL, Codex, OpenCode,    analysis/cache/<c>_<s>.parquet   swarm / other callers           run_eval reads the pack and
  Gemini, ATIF trajectory.json)         |                                |                       applies attack plans itself,
        | loaders.detect.sniff()        | loaders.corpora                | ir.turns.turns_to_events  then calls
        | loaders.files.load_file()     |   CORPUS_ADAPTERS[c]           |                       verifier.verify_session(df,
        |   -> analysis/loaders parsers |   .iter_sessions(split)        |                         unit=, calibration_unit=)
        v                               v                                v                               v
   list[dict] IR events  --- analysis.lib.ir.to_frame() + validate() --> pd.DataFrame (IR COLUMNS, seq 0..n-1)
                                                   |
                                                   v
                        session.build_session(df, unit=, source=)  -> Session
                          .pairs  .responses  .clocks  .capabilities  .call_keys
                                                   |
                                                   v
                        registry.run_checks(session, ENABLED_CHECKS)   (sorted by check name)
                          for each check:  requires ⊆ capabilities ?  no -> unconstrained 'missing:<cap>' for every call
                                           applicable(session) ?      no -> unconstrained 'abstain:not_applicable'
                                           run(session) -> list[CallVerdict]  -> validate, fill gaps, catch exceptions
                                                   |
                                                   v
                        compose.compose(session, by_check, kinds) -> list[Verdict]   (one per call, in seq order;
                                                                      kinds = {name: REGISTRY[name].kind}, passed by api)
                                                   |
         +-----------------------+-----------------+------------------+----------------------------------+
         v                       v                                    v                                  v
  render.text (terminal)   render.jsonl (verdicts.jsonl     render.html (static page,         eval/run_eval.py (joins to
                           + <out>.session.json)            evidence inline, demo)            tamper labels / LabeledCall)
```

### 2.4 IR: import, do not vendor (DA1)

`verifier/ir/__init__.py` is the only place that imports `analysis.lib.ir`:

```python
from analysis.lib import ir as _ir
from analysis.lib.ir import COLUMNS, SHELL_TOOLS, normalize_tool, iso, parse_ts, frac_digits, error_marker, to_frame, validate
import hashlib
from pathlib import Path
# The pin covers the whole module, because normalize_tool's table is a local variable and cannot be hashed on its own.
IR_SCHEMA_SHA = hashlib.sha256(Path(_ir.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
EXPECTED_IR_SCHEMA_SHA = "<sha computed at scaffold time>"   # test_ir_parity.py asserts equality
```

Reasons:
1. The parsers we reuse (`analysis/loaders/*`, `analysis/lib/cc_jsonl.py`) already emit `analysis.lib.ir` rows, and
   every cache on disk was validated with `analysis.lib.ir.validate`. A vendored copy would be a second schema that has
   to agree with the first and buys no isolation, because the loaders are imported anyway.
2. Drift is caught mechanically. `IR_SCHEMA_SHA` goes into every verdict's `version`, and `tests/test_ir_parity.py`
   fails if any byte of `ir.py` (so `COLUMNS`, `normalize_tool`'s table and `ERROR_MARKERS` too) changes without the pin
   being bumped. The pack records the `IR_SCHEMA_SHA` it was built under; `run_eval` returns `ok: false` with
   `error: "ir_schema_mismatch"` when the `ir/<sha12>` part of the returned `Verdict.version` differs.
3. **Cost and fallback.** `verifier/` then needs `analysis/lib` and `analysis/loaders` on `main` (a morning merge
   decision; divisions share only what is committed on `main`). If the human declines that merge, the re-export module
   is the single switch point: copy `ir.py` to `verifier/ir/_ir.py` and `newcorp_common.redact` with its `SECRET_RX` to
   `verifier/render/_redact.py`, keep the pin, and change two import lines. File input for formats whose parser lives
   in `analysis/loaders` is then unavailable until those parsers are merged.

`verifier/session/idclock.py` is the exception: it is **vendored**. It holds 25 lines of id decoding, copied from
`analysis/loaders/load_tbench2.py` `id_family` / `id_embedded_ms` together with `_B58I` and `_WIN` from
`analysis/probes/prereg_e_common.py`. The point is that `verifier` never imports `analysis.probes`.
`tests/test_idclock_parity.py` checks that the copy decodes every distinct `request_id` and `api_msg_id` in split A
exactly as `load_tbench2.id_embedded_ms(id_family(v), v)` does, and that for the `anthropic_req` family it also equals
`prereg_e_common.decode_req_ms(v)`, the decoder Track A's bracket used. The decoder keeps `_WIN` = [2024-01-01,
2027-01-01): an id outside it is undecodable (`missing:request_id.decodable`). Layout caveat: every provider id layout
is undocumented and comes with no stability promise (`PRIOR_ART.md` B2, fact row: "MATERIAL LIMITATION").

**Layout gate (DA20).** `idclock.decode(v) -> tuple[str, float] | None` returns `(family, ms)`. For the
`anthropic_req` and `anthropic_msg` families it first rebuilds the 128-bit value from the base58 body. It then requires
version nibble `== 7` (bits 76–79) and variant `== 0b10` (bits 62–63), as `PRIOR_ART.md` §1.4 design consequence 1
asks. Only then does it return the top 48 bits as ms. On swechat this gate loses nothing: 305,727 of 305,727 distinct
ids pass it [B4 `REQUEST_ID_COLUMN_FIRST.per_corpus."swechat/claude_code".decodable_time.rfc9562_v7_version_and_variant_bits`].
`test_idclock_parity.py` therefore also asserts that the gate rejects 0 ids that `decode_req_ms` accepts on split A. A
non-zero count stops the build: it means the layout differs from what Track A measured. `idclock.layout_report(ids) ->
{"n_shaped": int, "n_decoded": int}` feeds `session.json` `id_layout_unrecognized`
(`n_shaped > 0 and n_decoded == 0`).

### 2.5 Loader reuse (adapters over `analysis/loaders`)

`verifier/loaders/corpora.py` defines one `CorpusAdapter` per corpus:
`iter_sessions(split: Literal["A","B","E"], session_ids: Sequence[str] | None = None) -> Iterator[Session]`. It reads
`analysis/cache/<corpus>_<split>.parquet` with pyarrow (row-group streaming, `filters=[("session_id","in",ids)]`),
groups by `session_id`, and calls `build_session`. It refuses `split == "H"` with an assertion, and it refuses any path
whose name contains `_H` or `heldout` (the same guard as `prereg_e_common.read_cache`). `verifier/loaders/files.py`
parses one file through the per-session parser named below.

**Units are the Phase E units**, exactly the `prereg_e.json` `n6_transfer_grid` columns plus one per new corpus as the
`prereg_e_calibration_<corpus>.json` files name them. That is what lets calibrations and N6 cells carry over unchanged.
A finer split (for example tbench2 by log format) has no calibration and is reported only as a stratum.
`EVAL_CALIBRATION_UNIT` in `config_eval.json` is the pre-registered proxy map (`prereg_e.json` change_log D1); every
unit not listed calibrates as itself. Under DA19, a calibration file keys its entries by the unit's **own** name
whenever that corpus's split-A calibration produced the value (for example N2's τ for pub_cc_hf,
[CAL-pub_cc_hf `calibration.n2.tau`] = 0.668). The D1 proxy is consulted only for a quantity the corpus's own file
lacks. The "H in manifest" column is `n_H` from `analysis/HELDOUT_MANIFEST.json` `corpora.<corpus>.n_H` [MAN]
(the committed manifest; it lives in `analysis/`, not `analysis/out`).

| Corpus | IR caches today (`analysis/cache/`) | Per-session parser reused | Unit (`units.py`) | Eval calibration unit (D1) | H in manifest |
|---|---|---|---|---|---|
| swechat | A, B, E | `load_swechat.PARSERS[fmt](sid, stratum, text, stat, ctx)`, with `ctx={"opencode_task": {}, "codex_spawn": {}}` for single files; `parse_session(sid, fmt, stratum, ctx, path)` for cached ids | `swechat/<format>`, with format from `swechat_population.parquet` (claude_code, codex, opencode, gemini, cursor, copilot, simple_text) | itself | 1,825 |
| tbench2 | A, B, E | `load_tbench2.parse_session(row)`; `parse_atif(doc, corpus, sid, stratum, submission, cnt)` for one `trajectory.json` | `tbench2` (log format kept as a reporting stratum: atif, cc_jsonl, gemini_cli, hookele) | itself | 7,129 |
| glm_tb21 | A, B, E | through `load_tbench2.build_frame` | `glm_tb21` | itself | 23 |
| pub_cc_hf | A, B, E | `pub_cc_common.parse_session(s, corpus, C, R)` | `pub_cc_hf` | `cc_local` | 45 |
| pub_trace_commons | A, B, E | `pub_cc_common.parse_session` | `pub_trace_commons` | `cc_local` | 8 |
| pub_codex | A, B, E | `load_pub_codex.parse_one(row, red)` | `pub_codex` | `swechat/codex` | 13 |
| agentcap | A, B, E | `load_agentcap.parse_pi` / `join_session` | `agentcap/opencode`, `agentcap/pi` | `swechat/opencode`; `agentcap/pi` | 216 (14 parse-exposed, §5.2) |
| aiv_cu | A, B, E | `load_aiv_cu.build_session(sid, stratum, model_string, raw_lines, counters)` | `aiv_cu` (provider family kept as a stratum) | itself | 2,000 |
| aiv_cc | A, B | `cc_jsonl.Parser` | `aiv_cc` (one agent: case study) | itself | none |
| cc_local | A, B (**private**) | `load_cc_local.process_session` | `cc_local` (never rendered) | itself | none |
| whowhen | A, B | `load_whowhen.parse_ag` / `parse_hc` | `whowhen` (no clock) | itself | none |

Acquired corpora with **no loader yet**: openhands-evaluation-outputs, openhands-feedback, miniswe, sweagent combo2,
osworld, webarena-infinity, tracelab-uw and cli-pi-hf. They are COULD items, at 2–4 h each *(estimate: B7's per-loader
figure, [CI `loaders`])*. combo2 is the one that would bring harness-labelled substitutes (§1.4).

### 2.6 Public API (exact signatures)

```python
# verifier/api.py  (re-exported by verifier/__init__.py)
def verify_session(turns_or_events: list[dict] | pd.DataFrame, *, unit: str | None = None,
                   calibration_unit: str | None = None, checks: Sequence[str] | None = None,
                   source: dict | None = None, sidecar: Mapping[str, object] | None = None,
                   strict: bool = False) -> list[Verdict]:
    """SCOPE §3 contract. list[dict] = SCOPE `turn` dicts of ONE session (turns_to_events); DataFrame = IR events of ONE
    session (exactly COLUMNS; ValueError if it holds >1 session_id). unit defaults to 'turns' for turns and to
    'unknown' for frames. calibration_unit defaults to None, so statistical checks abstain (DA4) unless the caller
    names one. sidecar: harness records the IR drops (2.7), validated by session.sidecar.validate_sidecar; None = {}.
    checks=None runs ENABLED_CHECKS. Returns one Verdict per call in call seq order ([] if no calls)."""

def verify_sessions(events: pd.DataFrame, *, unit_of: Callable[[str], str], calibration_unit_of: Callable[[str], str | None],
                    sidecar_of: Callable[[str], Mapping[str, object] | None] = lambda sid: None,
                    checks: Sequence[str] | None = None, strict: bool = False) -> Iterator[tuple[Session, list[Verdict]]]
def verify_file(path: str | Path, *, fmt: str = "auto", unit: str | None = None, checks: Sequence[str] | None = None,
                strict: bool = False) -> list[tuple[Session, list[Verdict]]]   # CLI path; borrows calibration by format (4.5)
```

**`turns_to_events` mapping (`verifier/ir/turns.py` `TURN_TO_IR`).** Input rows are sorted by `turn_number`, then input
order; `seq` is that order. SWE-chat `(role, turn_type)` values are those in `analysis/out/recon/swechat_scan_pinned.json`.

| `role` / `turn_type` | IR `kind` | Columns filled |
|---|---|---|
| `tool_use` / `tool_use` | `call` | `tool_raw=tool_name`, `tool=normalize_tool(tool_name)`, `call_id=tool_call_id` (if null: `"turn:<turn_id>"`), `args=tool_input_json`, `command=command` |
| `tool_result` / `tool_result` | `result` | `call_id=tool_call_id`, `text=content`, `tool`/`tool_raw` copied from the matching call when there is one |
| `user` / `user_prompt` | `user` | `text=content` |
| `user` / `system_injected` | `system` | `text=content` |
| `assistant` / `assistant_response` | `assistant` | `text=content`, `usage_in=input_tokens`, `usage_out=output_tokens`, `model` |
| `assistant` / `assistant_thinking` | `meta` | `text=None`, `extra={"turn_type": "assistant_thinking", "thinking_chars": len(content)}` (the IR keeps thinking as a count only) |
| `metadata` / any | `meta` | `text=None`, `extra={"turn_type": <turn_type>}` |
| any other pair | `meta` | `extra={"role": .., "turn_type": ..}`; counted in `source["unmapped"]` |

Every row: `corpus="turns"`, `session_id`, `stratum=source` (the turn's `source` column, or None), `ts=iso(timestamp)`,
`ts_kind="event"` if `timestamp` else `"none"`, `uuid`, `parent_uuid`, and `extra.turn_id`. `request_id`, `api_msg_id`,
`native_error` and `exit_code` stay null (open item 3). Cache-token columns map to `usage_cache_*` when present under
the names `cache_read_input_tokens` / `cache_creation_input_tokens`.

### 2.7 Sidecar records (DA14)

Three Track A mechanisms read harness-written records that the IR does not carry. `analysis/lib/cc_jsonl.py` copies a
fixed list of `toolUseResult` keys into a result's `extra`, and `numLines` is not on that list. The Entire tally lives
in the SWE-chat `sessions.parquet` / `session_logs.parquet` tables, not in any transcript. The restamped-copy
correction of the bracket needs to know which request ids occur in another session of the corpus. Editing
`analysis/lib` is out of bounds, and putting these fields into `extra` would make the IR cache disagree with its own
loader. So they travel beside the IR.

```python
# verifier/session/sidecar.py
SIDECAR_KEYS = {
  "cc_numlines":        "dict[str call_id, int]   toolUseResult.file.numLines of Read results (raw Claude Code JSONL)",
  "entire_tally":       "dict {api, in, cc, cr, out} (ints) | None   SWE-chat sessions.parquet, gated on session_logs token_usage",
  "copied_request_ids": "dict[str request_id, str smallest_holder_session_id]   corpus-level index (F1 dedupe rule)",
}
def validate_sidecar(sc: Mapping[str, object]) -> dict      # unknown keys -> ValueError; types checked; returns a frozen copy
```

| Key | Filled by | Source (read-only) | Matches Track A's |
|---|---|---|---|
| `cc_numlines` | `loaders.sidecar.read_cc_numlines(raw_path) -> dict` (CLI file input); `eval/heldout.py build-pack` for packs | the raw `.jsonl`: every user entry whose `toolUseResult.file.numLines` is an int, keyed by `tool_use_id` | `phase_e_n7_content.raw_swechat_cc` / `_numlines_from_entry` (R4 detector input) |
| `entire_tally` | `loaders.sidecar.read_entire_tally(session_ids) -> dict[sid, dict \| None]` | `data/swe-chat-pinned/sessions.parquet` columns `input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, api_call_count`, and `session_logs.parquet` `session_metadata_raw.token_usage` (gate) | `phase_e_n7_content.swechat_tallies` |
| `copied_request_ids` | `loaders.sidecar.copied_request_ids(frames) -> dict` at pack build, over the dev splits the pack is built from (B ∪ E for swechat, B for cc_local) | IR `request_id` across sessions | `phase_e_f1_bracket.copied_ids` (deviation 1: "another session of the readable corpus") |

- **Attacks never touch the sidecar.** This reproduces N7's semantics. A tampered IR text is compared with the honest
  `numLines`. A tampered usage row is compared with the honest tally. An inserted pair has no counter and abstains.
- **CLI single-file input** fills `cc_numlines` only. `entire_tally` exists only for SWE-chat sessions, and
  `copied_request_ids` only for a corpus. Checks that need a missing key emit `missing:sidecar.<key>` (§4.3).
- **Pack storage.** `<pack_dir>/<split>_sidecar.parquet` holds one row per session, with columns `session_id, key,
  json`. Its sha256 goes in `BUILD.json`. The score path reads it with pyarrow and passes `sidecar=` to
  `verify_session`, and imports nothing new.
- **H.** `heldout.py build-cache --final` builds the H sidecar with the same functions. The H `copied_request_ids`
  index is computed over B ∪ E ∪ H, at H-build time only (§5.2 rule 3).

---

## 3. Record schema

### 3.1 The IR event row (input, unchanged)

One row is one event. The columns are exactly `analysis/lib/ir.py` `COLUMNS`:
- identity: `corpus, session_id, stratum, seq`;
- event type: `kind ∈ {user, system, assistant, call, result, meta}`;
- time: `ts`, plus `ts_kind ∈ {event, row_insert, shared_turn, none}`;
- tool: `tool, tool_raw, call_id, args, command`;
- content: `text, stderr`;
- errors: `native_error, exit_code`;
- usage: `usage_in, usage_out, usage_cache_read, usage_cache_create`;
- provider and model: `api_msg_id, request_id, model`;
- threading: `is_subagent, parent_call_id, agent_id, uuid, parent_uuid`;
- `extra` (a JSON string).

`ir.validate` enforces that `seq` runs 0..n-1 per session and that every call has a `call_id`. **`seq` depends on the
loader**: it is file/stream order as one loader version emits it. Anything that refers to an event by `seq` across
processes must therefore carry the session fingerprint `ir_sha` (§3.4).

The verifier adds nothing to the row. Derived structures live on `Session` (§4.2):
- `pairs`: one row per call:
  - `call_key, call_id, call_seq, result_seq, n_results`;
  - `tool, tool_raw, command, args, text, native_error, exit_code`;
  - `t_call_ms, t_result_ms, latency_ms`;
  - `thread, is_subagent`.
  - **Pairing rule.** A call pairs with the first `result` after it in seq order that has the same `call_id` and comes
    before the next call with that `call_id`. `n_results` counts results in that window. A result is an **orphan** iff
    no call with its `call_id` precedes it.
- `responses`: one row per provider response:
  - `resp_key` = `request_id`, else `api_msg_id`; rows carrying neither are in no response (formats without provider
    ids have an empty `responses` frame, and checks that need per-step usage there group it themselves);
  - `request_id, api_msg_id, first_seq, last_seq, t_first_ms, t_last_ms`;
  - usage deduped as the IR docstring prescribes: rows with `usage_in` not null, deduped on
    `(session_id, api_msg_id)`, `max(usage_out)`;
  - `provider_ms` (idclock), `stream`, `call_keys`.

### 3.2 Unit of verdict: the call (DA7)

- **One `Verdict` per call event.** The key is `call_key` = `call_id` when that `call_id` occurs on exactly one call of
  the session, else `f"{call_id}@{call_seq}"` for **every** call that carries it (no occurrence is privileged).
  `ir.validate` does not enforce uniqueness, and resumed or forked sessions copy history. `Verdict.call_id` keeps the raw
  IR `call_id` for joins and the SCOPE projection; `Verdict.call_key` is the unique key.
- **Orphan results** (a result whose `call_id` matches no call) get no verdict. `SessionReport.orphans` lists their
  seqs and count. Reason: on some exports they are loader artifacts. The SWE-chat conversations table orphans a large
  share of results that the raw transcripts keep (`SCOPE.md` §1 and `FINDINGS.md` caveat 4 give the share; it is a
  pre-Phase-A probe number that is not in `analysis/out`, so it is not repeated here).
- Checks whose decision unit is larger than a call (a response, a stream, an output or a whole session) still emit one
  `CallVerdict` per call. They set `unit_kind`/`unit_id`, and set `localized=False` when the evidence does not single
  out the call (§4.6). A `localized=True` verdict's evidence may span at most `MAX_CORE = 6` distinct seqs (a judgment
  fixed now; `SCOPE.md` §5.5 expects cores of 2–3 events; the registry rejects more); a check that cannot name ≤ 6 events sets `localized=False`, so a large core cannot buy
  localization in §5.5.

### 3.3 Verdict records

```python
# verifier/checks/base.py
from dataclasses import dataclass, field
from typing import Literal, Optional

Status = Literal["supported", "contradicted", "unconstrained"]
Strength = Literal["strong", "format", "none"]

@dataclass(frozen=True)
class EventRef:
    seq: int                                  # IR seq in this session
    field: Optional[str] = None               # IR column or 'extra.<dotted.key>' the evidence reads, e.g. 'ts', 'request_id', 'usage_out'
    role: Literal["subject", "witness", "conflict"] = "witness"
                                              # subject: the call/result judged; witness: where a fact came from; conflict: the fact that disagrees
    value: Optional[str] = None               # short rendered value (<= 200 chars, redacted) shown inline

@dataclass(frozen=True)
class CallVerdict:                            # one check's verdict on one call
    session_id: str
    call_key: str                             # Session call_key (3.2)
    check: str                                # Check.name
    check_version: str                        # Check.version + '+' + calib sha[:12] (or 'nocalib')
    verdict: Status
    reason: str                               # vocabulary below
    confidence: Optional[float]               # always None when unconstrained; may be None when decided (semantics below)
    evidence: tuple[EventRef, ...] = ()       # empty iff unconstrained
    unit_kind: str = "call"                   # call | pair | response | stream | output | session
    unit_id: Optional[str] = None             # e.g. resp_key, stream key; None for 'call'
    localized: bool = True                    # False when the evidence does not single out this call
    strength: Strength = "none"               # Check.strength when decided, 'none' when unconstrained
    detail: Optional[dict] = None             # numbers behind the decision, JSON-safe: {'U_ms': .., 'L_ms': .., 'tol_ms': 2000}

@dataclass(frozen=True)
class Verdict:                                # composed per call (compose.py); the SCOPE §3 'verdict' contract is a projection of this
    session_id: str
    call_id: str                              # raw IR call_id (join key; SCOPE 'call_id')
    call_key: str                             # unique within the session (3.2)
    seq: int                                  # call event seq
    result_seq: Optional[int]
    tool: Optional[str]
    verdict: Status
    strength: Strength
    confidence: Optional[float]
    rule: Optional[str]                       # deciding check name (SCOPE 'rule'); None if unconstrained
    reason: str                               # deciding check's reason, or the summary unconstrained reason
    core: tuple[int, ...]                     # seqs of the deciding evidence (SCOPE 'core', as seqs)
    blame_seq: Optional[int]                  # probable fabricated event (4.6)
    localized: bool
    disagreement: bool                        # >= 1 contradicted and >= 1 supported among checks
    detail: Optional[dict]                    # deciding CallVerdict.detail; for unconstrained {'unconstrained_reasons': {reason: n_checks}}
    checks: tuple[CallVerdict, ...]           # every check's verdict on this call, sorted by check name ("report all")
    version: str                              # 'verifier/<__version__> ir/<IR_SCHEMA_SHA[:12]> checks/<checkset_sha[:12]>'
                                              # checkset_sha = sha256('\n'.join(sorted(f'{cv.check}@{cv.check_version}' for the checks run)))

    def to_scope_dict(self, turn_ids: dict[int, str] | None = None) -> dict:
        """SCOPE.md §3 verdict: {session_id, call_id, tool, verdict, strength, tiers, core, rule, detail}.
        call_id = raw call_id; tiers = [cv.check for cv in checks if cv.verdict != 'unconstrained'];
        core = [turn_ids[s] for s in core] when the session came from turns, else [f'seq:{s}' for s in core]."""
```

**Reason vocabulary.** The format is `<prefix>:<detail>`, and the prefix is machine-checked by the registry:

| Prefix | Verdict | Meaning | Examples |
|---|---|---|---|
| `ok:` | supported | The rule constrained the call and it held | `ok:within_bracket`, `ok:recount_match` |
| `violation:` | contradicted | The rule constrained the call and it failed | `violation:bracket_infeasible`, `violation:faster_than_floor` |
| `missing:` | unconstrained | Data the rule needs is absent: a session capability (§4.3) or this call's field | `missing:request_id.decodable`, `missing:result`, `missing:ts` |
| `abstain:` | unconstrained | Data present, but the rule does not decide here | `abstain:tool_out_of_scope`, `abstain:uncalibrated_unit`, `abstain:below_min_n`, `abstain:truncated`, `abstain:not_applicable`, `abstain:not_decided`, `abstain:no_enabled_checks` (composed only) |
| `abstain:below_threshold` | unconstrained | A **statistical** check screened this call and its score did not cross the threshold. Statistical checks never emit `supported` (§4.6); this reason is how they show they applied | — |
| `error:` | unconstrained | The check raised, or returned output that broke the contract (`error:ContractError`). The registry records `error:<ExceptionClass>` and counts it (eval fails on any; §5.6) | `error:KeyError` |

**`confidence` semantics (DA3).** It is never a per-call posterior, and it is never estimated on H. Every check except
reference checks ships `verifier/checks/calib/<check>.json`; for identity checks it holds only these two constants.
- `contradicted`: `1 − fpr_hi[unit]`. `fpr_hi` is the upper 95% bound of the check's honest flag rate per decision unit
  on split B as Track A measured it (every unit has a B split, and B is out of sample for thresholds fit on A), frozen
  in the calibration file. It is copied exactly as Track A computed it: a Wilson bound, including at zero counts (§7.1
  names each source key). Clopper–Pearson (`SCOPE.md` §8.4) is used only where `calib/build.py` has to compute a bound
  itself.
- `supported` (identity checks only): `recall_lo[unit]`, the lower 95% bound of the check's recall on its declared
  **primary** target attack in that unit, copied from the Track A N7 output on B (§5.4; §7.1 names the cell). It
  answers: *had this call been tampered that way, how surely would we have said contradicted?*
- Either is `None` when the file has no entry for the call's calibration unit. An identity check still decides then; a
  statistical check abstains (`abstain:uncalibrated_unit`, §4.5).
- `unconstrained`: `None`.
- A check may refine either constant per `tool_key` when its calibration file carries one. It may not compute
  confidence from the call itself. Confidence never changes a verdict; it is display and tie-break only (§4.6).

**Serialization.**
- `verdicts.jsonl`: one `Verdict` per line, from `dataclasses.asdict`. Key order is fixed. Floats are rounded to 6
  places.
- `<out>.session.json`: `{session_id, corpus, unit, source, n_calls, n_events, capabilities, checks_run: [{name,
  version, status: ran|missing|not_applicable|error, reason}], counts: {supported, contradicted_localized,
  contradicted_unit, unconstrained, screened},
  orphans: {n, seqs}, calibration_unit, calibration_borrowed: bool, version}`.
- Census: `reports/census/<corpus>_<split>_verdicts.parquet`, with columns `session_id, call_id, call_key, seq, tool,
  verdict, strength, confidence, rule, reason, localized, disagreement, version, checks_json`. The full-corpus census
  `SCOPE.md` §5.7 asks for (`<corpus>_all_verdicts.parquet`) includes H, so it is `eval/heldout.py census --final
  --freeze SHA`, run after the H eval run (§5.2 rule 3), not a `verifier` subcommand.

### 3.4 Labeled-corpus extension (a future input; contents not assumed)

A labeled corpus may arrive later, for example swarm-derived ground truth produced by another session. This design
guarantees only the pipe. Whether such data may be used at all is a human decision, outside this division's scope
(`PHASE_E_PROMPT.md` "Scope boundary").

```python
# eval/labeled.py
@dataclass(frozen=True)
class LabeledCall:                          # superset of SCOPE.md §3 `labeled_call`
    set: str                                # labeled-set name: '<corpus name>' or 'attack:<attack>:<param>:seed<k>'
    corpus: str
    session_id: str
    call_id: str | None                     # preferred join key (raw IR call_id; always set by eval/attacks.py)
    seq: int | None                         # fallback join key (requires ir_sha)
    label: Literal["pos", "neg", "unknown"] # SCOPE has pos|neg; 'unknown' is read but never written by this repo
    cls: str | None                         # serialized as "class"; free string, the source's own vocabulary
    provenance: str                         # e.g. 'eval/attacks.py@<git sha>:sub_matched_bytes:base:seed0' or '<manifest id>:<row>'
    label_version: str
    ir_sha: str | None = None               # session_ir_sha(events) of the frame the seq refers to
    tampered_seqs: tuple[int, ...] = ()     # events actually changed (localization scoring)

def session_ir_sha(events: pd.DataFrame) -> str:
    """sha256 over the canonical bytes of the session's IR rows: columns in COLUMNS order, rows in seq order,
    NA as empty, joined with \\x1f / \\x1e."""
```

**Directory format of a labeled corpus.**
- `<dir>/manifest.json`:
  - `{"name", "version", "schema": "labeled_call/1", "sessions_format": "ir" | "turns", "license", "files": {path:
    sha256}, "classes": [...], "source": "..."}`.
- `<dir>/labels.jsonl`: one `LabeledCall` per line.
- `<dir>/sessions/`, one of:
  - IR parquet with exactly `COLUMNS`;
  - `turns/*.jsonl` in the `SCOPE.md` §3 `turn` schema, read through `verifier.ir.turns.turns_to_events`.

**Join rules (`join_labels(verdicts: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame`, adds `join_status`).**
1. When `call_id` is not null, join on `(session_id, call_id)`.
   - Exactly one matching call: `join_status = ok`.
   - More than one: `ambiguous`. The label is excluded and counted.
2. When `call_id` is null, join on `(session_id, seq)`, but only if `ir_sha == session_ir_sha(session.events)`.
   Otherwise `seq_mismatch`: excluded and counted.
3. A label whose session is absent is `orphan_label`: counted. A call with no label is `unknown`: it is never read as
   `neg`.
4. `run_eval.py --labeled DIR` sets `ok=false` when the `ok` share of labels is below 0.99. This mirrors the
   `join_rate >= 0.99` validity rule in `SCOPE.md` §7.14.

**Split registration before the first read.** `eval/labeled.py register DIR` applies the pre-registered new-corpus
split rule (`analysis/loaders/newcorp_common.py` `split_population`, seed 20261006) to the corpus's sessions, with
`stratum` = the IR `stratum` of the session's first event (`""` when null) and `length` = its number of call events.
A = calibration, B and E = development (`--labeled DIR --split E`), H = the confirmatory read. It writes
`analysis/out/phase_e/heldout_manifest_<name>.json` with `sha256_sorted_H_ids`, using the same digest rule as
`HELDOUT_MANIFEST.json`, and the entry is merged into `HELDOUT_MANIFEST.json` as the six Track B corpora were (commit
`669124a`). Only after that may calibration read A. Labeled-set metrics (§5.5) are reported from H, under the same
`--final --freeze` rule as every other H read (§5.2).

**Synthetic positives use the same record.** `eval/attacks.py` `to_labels` emits, per tampered copy, one `LabeledCall`
per entry of `Tamper.target_call_ids` (§5.4):
- `label="pos"`, `cls=<attack>`, with `tampered_seqs` filled;
- for the untampered copy of each sampled session, `label="neg"` on every call, `cls="presumed_honest"`.

That last label is a convention, not ground truth (§1.4).

---

## 4. Check plugin interface

### 4.1 The Protocol (exact signature)

```python
# verifier/checks/base.py
from typing import ClassVar, Literal, Protocol, runtime_checkable
from verifier.session import Session

@runtime_checkable
class Check(Protocol):
    name: ClassVar[str]                          # unique snake_case, stable across versions; e.g. 'ref_result_present'
    version: ClassVar[str]                       # semver; bump on ANY logic or threshold change
    kind: ClassVar[Literal["identity", "statistical", "reference"]]
                                                 # identity: an exact accounting/recount identity, thresholds not fit on data
                                                 # statistical: thresholds calibrated per unit; reference: plumbing only, never decides
    strength: ClassVar[Literal["strong", "format"]]   # SCOPE §5.6 strength when this check decides
    requires: ClassVar[frozenset[str]]           # capability names (4.3), e.g. frozenset({'ts.ms', 'join.call_id'})
    reads: ClassVar[frozenset[str]]              # fields read, in prereg_e.json DETECTOR_FIELDS vocabulary:
                                                 #   {'ts','order','request_id','text','args','error','usage','events','tool'}
    targets: ClassVar[frozenset[str]]            # eval/attacks.py attack names this check claims to see (5.4)
    unit_kind: ClassVar[str]                     # its decision unit: call | pair | response | stream | output | session
    calibration: ClassVar[str | None]            # 'verifier/checks/calib/<name>.json'; None only for reference checks (3.3)

    def applicable(self, session: Session) -> bool:
        """Cheap. Called only when requires ⊆ session.capabilities. False -> every call 'abstain:not_applicable'."""

    def run(self, session: Session) -> list[CallVerdict]:
        """Pure: no I/O, no randomness, no wall clock, no global mutable state, no branching on corpus/session_id
        strings (calibration lookup by session.calibration_unit is the only allowed use). Returns at most one CallVerdict per
        call_key; omitted calls are filled 'abstain:not_decided' by the registry."""

    def explain(self, cv: CallVerdict) -> str:
        """One plain-English sentence for render, built only from cv.reason / cv.detail / cv.evidence."""
```

Constructors in the same module keep checks short and enforce the invariants. They are the only sanctioned way to
build a `CallVerdict`:

```python
def supported(s: Session, call_key: str, check: Check, reason: str, evidence: Sequence[EventRef], *,
              confidence: float | None, unit_kind="call", unit_id=None, localized=True, detail=None,
              strength: Strength | None = None) -> CallVerdict
def contradicted(s: Session, call_key: str, check: Check, reason: str, evidence: Sequence[EventRef], *,
                 confidence: float | None, unit_kind="call", unit_id=None, localized=True, detail=None,
                 strength: Strength | None = None) -> CallVerdict
def unconstrained(s: Session, call_key: str, check: Check, reason: str, detail=None) -> CallVerdict
def all_unconstrained(s: Session, check: Check, reason: str, detail=None) -> list[CallVerdict]
def calib_for(check: Check, unit: str, stratum: str | None = None) -> dict | None
    # frozen calib JSON slice: units["<unit>/<stratum>"] if present (aiv_cu N2 strata), else units[unit], else the D1
    # proxy's entry for quantities flagged proxy_ok (DA19), else None
```

Each one asserts: the reason prefix matches the verdict; `evidence` is non-empty for decided verdicts and contains at
least one `role="subject"` ref; `confidence` is in [0, 1] or None as §3.3 requires; every `seq` exists in the session;
a `localized=True` verdict cites at most `MAX_CORE` distinct seqs (§3.2); `supported()` is refused for a
`kind="statistical"` check (§4.6). A `strength` argument may only lower the check's class strength, never raise it
(`strong > format`; DA18). Evidence about a sidecar value is attached to the event it describes: for example the
result seq with `field="sidecar.cc_numlines"` and `value="numLines=120"`. A sidecar holds no events, so it never
supplies a `seq`.

**What may emit `contradicted` (DA11).** A check's `violation:` rule must be one of:
1. an inconsistency between a field the agent controls and a field it does not (§1.2 table), for example a result
   stamp against a provider id clock. Result text against a harness structured count (`toolUseResult.numLines`) is
   type 1 only for the record-editing class: under execution-path compromise both renderings come from the same fake
   output (§1.2), so such a check must declare only record-editing targets;
2. a physical bound, for example a result faster than any honest execution of that tool in that unit, or output tokens
   too few to have produced inline text;
3. an inconsistency between two agent-controlled results that no honest execution can produce, for example two
   outputs of a deterministic command with no intervening write that differ.

A distributional statistic (a session's error share, digit or round-number distribution, or size distribution
against a corpus base rate) is evidence about a population, not a contradiction of this record. If such a mechanism
survives Track A **and clears Track B** (§7.0), it is reported in the census and the N6 grid, not registered as a
check. No mechanism in this build meets both conditions: P3 survived Track A but has no Track B verdict. Each §7.1 block names which
of 1–3 its rule is.

### 4.2 The `Session` object

```python
# verifier/session/__init__.py
@dataclass(frozen=True, eq=False)
class Session:
    corpus: str                         # 'swechat', ..., 'file' for CLI inputs, 'turns' for turn dicts
    session_id: str
    unit: str                           # 'swechat/claude_code', 'tbench2', 'agentcap/pi', 'file/claude_code', 'turns', ...
    calibration_unit: str | None        # unit whose calibration checks may use: == unit, the D1 proxy (eval), borrowed by
                                        # format (CLI), or None (API default); 4.5
    stratum: str | None
    events: pd.DataFrame                # IR COLUMNS, sorted by seq, RangeIndex == seq, validated
    capabilities: frozenset[str]        # 4.3
    source: dict                        # {'path', 'format', 'loader', 'loader_sha256', 'split'}
    turn_ids: dict[int, str] | None     # seq -> SCOPE turn_id when built from turns
    sidecar: Mapping[str, object]       # 2.7 (DA14); validated, frozen; {} when none. Never mutated by attacks

    # The members below are @functools.cached_property methods, NOT annotated dataclass fields (an annotation here would
    # make them required __init__ arguments). cached_property writes to __dict__, so it works on a frozen dataclass
    # without __slots__. Computed once; callers must not mutate the frames.
    #   calls -> pd.DataFrame          events[kind == 'call']
    #   results -> pd.DataFrame        events[kind == 'result']
    #   pairs -> pd.DataFrame          3.1 (pairing rule there)
    #   orphans -> tuple[int, ...]     result seqs with no preceding call of that call_id
    #   responses -> pd.DataFrame      3.1
    #   call_keys -> tuple[str, ...]   in call seq order (3.2)
    #   clocks -> ClockView
    #   threads -> pd.Series           seq -> (is_subagent, agent_id or '')

    def extra(self, seq: int) -> dict:  # parsed `extra` JSON, LRU-cached; {} when null or invalid
    def ref(self, seq: int, field: str | None = None, role: str = "witness", value: str | None = None) -> EventRef
    def call_seq(self, call_key: str) -> int
    def result_seq(self, call_key: str) -> int | None

@dataclass(frozen=True)
class ClockView:
    ts_ms: np.ndarray                   # float64 epoch ms per seq (analysis.lib.ir.parse_ts), NaN when missing
    ts_kind: np.ndarray                 # per seq
    resolution_ms: float                # 10 ** (3 - MIN frac digits over call/result stamps present): the coarsest stamp
                                        # sets the tolerance (conservative); 1000.0 when any is whole seconds
    provider_ms: np.ndarray             # per seq: idclock.decode(request_id or api_msg_id), NaN when undecodable
    provider_family: np.ndarray         # per seq: idclock family name or ''

def build_session(events: pd.DataFrame, *, unit: str, source: dict, calibration_unit: str | None = None,
                  turn_ids: dict[int, str] | None = None,
                  sidecar: Mapping[str, object] | None = None) -> Session    # validates, sorts, detects capabilities
def split_sessions(df: pd.DataFrame) -> Iterator[pd.DataFrame]                # groupby session_id, sort=True
```

### 4.3 Capabilities (what `requires` names)

`detect_capabilities(events)` returns the set of names whose predicate holds for **at least one** event of the
session. Session presence gates a check; per-call absence becomes `missing:<field>` inside the check. One rule, no
thresholds.

| Capability | Predicate (on IR rows of the session) |
|---|---|
| `ts.any` | `ts` not null |
| `ts.event` | `kind ∈ {call,result}` and `ts_kind == 'event'` |
| `ts.ms` | `kind ∈ {call,result}` and `frac_digits(ts) >= 3` |
| `ts.pair_distinct` | ≥ 1 joined pair with both stamps and `ts_kind != 'shared_turn'` |
| `join.call_id` | ≥ 1 result whose `call_id` matches a call |
| `join.unique` | every `call_id` is unique in the session |
| `result.text` | `kind == 'result'` and `text` not null |
| `error.native` | result with `native_error` not null |
| `error.exit_code` | `exit_code` not null |
| `error.marker` | `ir.error_marker(text)` not None on ≥ 1 result |
| `shell.command` | `command` not null |
| `request_id` | `request_id` not null on `assistant`, `call` or `meta` |
| `request_id.decodable` | `idclock.decode(request_id)` not None |
| `api_msg_id` | `api_msg_id` not null |
| `api_msg_id.decodable` | `idclock.decode(api_msg_id)` not None (e.g. aiv_cu Gemini `responseId`, OpenAI `resp_`; 1 s resolution, `CORPUS_INVENTORY.md` §1.2) |
| `usage.io` | `usage_in` and `usage_out` not null |
| `usage.out` | `usage_out` not null on ≥ 1 row (Codex `token_count` meta rows included) |
| `usage.cache` | `usage_cache_read` not null |
| `subagent` | `is_subagent` true |
| `causal.uuid` | `uuid` and `parent_uuid` not null |
| `extra:<dotted.key>` | the parsed `extra` of ≥ 1 event has that key path (evaluated lazily; e.g. `extra:durationMs`) |
| `sidecar.cc_numlines` | `Session.sidecar["cc_numlines"]` has ≥ 1 entry whose `call_id` is a call of the session (DA14) |
| `sidecar.entire_tally` | `Session.sidecar["entire_tally"]` is a dict (the token_usage gate passed) |
| `sidecar.copied_request_ids` | key present (may be empty). Its absence is not fatal for any check: `id_bracket` then skips the dedupe correction and records `corrections_applied` without it |

`register()` rejects a `requires` entry that is neither a table name nor an `extra:` pattern. Corpus names are **not**
capabilities. A check that needs "swechat" really needs a field, and has to name it. This is what makes the transfer
grid (§5.5) data-driven: `NOT_TESTABLE(<cap>)` cells fall out of `requires − capabilities`.

### 4.4 Registration and running

```python
# verifier/registry.py
REGISTRY: dict[str, type[Check]] = {}

def register(cls: type[Check]) -> type[Check]:
    assert cls.name not in REGISTRY, f"duplicate check name {cls.name}"
    bad = {c for c in cls.requires if c not in CAPABILITIES and not c.startswith("extra:")}
    assert not bad, f"{cls.name}: unknown capabilities {bad}"
    assert cls.reads <= READ_FIELDS and cls.targets <= ATTACK_NAMES_DECLARED
    assert (cls.calibration is None) == (cls.kind == "reference")     # identity: confidence constants; statistical: + thresholds
    assert cls.__module__ == f"verifier.checks.{cls.name}"            # one module per check; the eval's vcache key needs the path (5.3)
    assert isinstance(cls(), Check)
    REGISTRY[cls.name] = cls
    return cls

# verifier/checks/__init__.py
from . import ref_result_present, id_bracket, inline_output_accounting, ledger_tally, dual_render_recount, latency_floor  # noqa: F401
ENABLED_CHECKS: tuple[str, ...] = ()   # stays () through the scaffold and until gate G0 (7.3). At the freeze it is set to
                                       # the checks that passed parity (DA15) and their 5.7 MUST rows on E. The expected
                                       # value, if everything passes: ("dual_render_recount", "id_bracket",
                                       # "inline_output_accounting", "ledger_tally"). Reference checks are never listed;
                                       # latency_floor is listed only if built and passing (COULD)

def run_checks(session: Session, names: Sequence[str] | None = None, *, strict: bool = False
               ) -> dict[str, dict[str, CallVerdict]]:
    """For name in sorted(names or ENABLED_CHECKS):
         missing = cls.requires - session.capabilities (extra: keys checked lazily)
         if missing:  every call -> unconstrained('missing:' + sorted(missing)[0], detail={'missing': sorted(missing)})
         elif not inst.applicable(session): every call -> unconstrained('abstain:not_applicable')
         else: out = inst.run(session)
               reject: duplicate call_key, unknown call_key, check/version mismatch, invariant violations -> ContractError
               fill: absent call_keys -> unconstrained('abstain:not_decided')
         any exception in applicable/run, ContractError included -> every call unconstrained('error:<ExcClass>');
         counted in RunStats; re-raised when strict=True.
       If the session has no calls, returns {name: {} for each name}."""
```

`READ_FIELDS` and `ATTACK_NAMES_DECLARED` are constants in `verifier/checks/base.py`:
- `READ_FIELDS` is the `prereg_e.json` `DETECTOR_FIELDS` vocabulary;
- `ATTACK_NAMES_DECLARED` is the 21 keys of `prereg_e.json` `n7_attack_battery.attacks`.

They are copied, not imported, because `verifier` never imports `eval`. `tests/test_registry.py` asserts that both
still equal the prereg file.

Usage: `@register` on the check class (the decorator), plus the module import and the `ENABLED_CHECKS` entry (the entry
in the registry dict). A registered check that is not enabled runs only through `--checks name` or `--checks all`. Run
order is sorted by name, so output does not depend on import order.

### 4.5 Missing data, calibration units and borrowing (DA4)

- **Session lacks a required capability** → every call is `unconstrained`, reason `missing:<first missing capability
  in sorted order>`, with `detail.missing` listing all of them.
- **Session has the capability but this call lacks the field** (for example, this response has no `request_id`;
  swechat Bedrock-backed calls carry none, 3,575 calls [B4 `REQUEST_ID_COLUMN_FIRST.per_corpus."swechat/claude_code".calls_by_backend.anthropic_bedrock`])
  → the check emits `missing:<IR column>` for that call.
- **Statistical check, uncalibrated unit.** `calib_for(check, session.calibration_unit, session.stratum)` returns None
  → every call is `abstain:uncalibrated_unit`. Thresholds are never borrowed silently across units. The cross-harness
  spread is itself a finding: "no mechanism is ALIVE in more than 2 corpora" (`DECISION_TABLE.md`, strongest finding,
  sentence 2; [DT `rows`]).
- **Statistical check, calibrated but not enabled (DA16).** The calibration entry exists with `"enabled": false`,
  because the unit's honest leg failed the pre-registered ALIVE false-positive condition. Every call is then
  `abstain:unit_not_enabled`, and `detail` carries the failing rate and its source key. The unit stays visible in the
  transfer grid as `NOT_RUN(unit_not_enabled)`, with the Track A label beside it.
- **Calibration lookup order (DA19).** The entry for `<unit>/<stratum>` comes first (aiv_cu N2 strata), then `<unit>`
  (own split-A values, including new corpora), then the D1 proxy unit for quantities marked `proxy_ok`, then None.
- **CLI borrowing.** For user files, `verifier.loaders.units.DEFAULT_CALIBRATION_BY_FORMAT = {"claude_code":
  "swechat/claude_code", "codex": "swechat/codex", "opencode": "swechat/opencode", "gemini": "swechat/gemini", "atif":
  "tbench2"}` sets `calibration_unit`. The header prints `calibration: swechat/claude_code (borrowed by format)`,
  and `--unit` overrides it.
- **Eval borrowing.** `run_eval.py` passes `calibration_unit = EVAL_CALIBRATION_UNIT.get(unit, unit)`, the
  pre-registered proxy map of §2.5 (`prereg_e.json` change_log D1: pub_cc_hf and pub_trace_commons → cc_local, pub_codex
  → swechat/codex, agentcap/opencode → swechat/opencode). It borrows nothing else. The report prints the map beside
  every proxied unit.
- **API default.** `verify_session` without `calibration_unit` borrows nothing (§2.6).
- Identity checks need no thresholds. They decide on every unit that has the capabilities, with `confidence=None` where
  their file has no entry for the calibration unit.

### 4.6 Composition and disagreement (DA2)

```python
# verifier/compose.py
STRENGTH_RANK = {"strong": 2, "format": 1, "none": 0}

def _conf(c: CallVerdict) -> float:
    return -1.0 if c.confidence is None else c.confidence

def compose(session: Session, by_check: dict[str, dict[str, CallVerdict]], kinds: dict[str, str]) -> list[Verdict]:
    out = []
    for key in session.call_keys:
        cvs = [by_check[n][key] for n in sorted(by_check)]
        deciding = [cv for cv in cvs if kinds[cv.check] != "reference"]          # reference checks are listed, never decide
        contra = [cv for cv in deciding if cv.verdict == "contradicted"]
        supp   = [cv for cv in deciding if cv.verdict == "supported"]
        if contra:
            d = max(contra, key=lambda c: (STRENGTH_RANK[c.strength], c.localized, _conf(c), c.check))
            final, core = "contradicted", sorted({r.seq for c in contra for r in c.evidence})
            blame = blame_seq(contra)
        elif supp:
            d = max(supp, key=lambda c: (STRENGTH_RANK[c.strength], _conf(c), c.check))
            final, core, blame = "supported", sorted({r.seq for r in d.evidence}), None
        else:
            d, final, core, blame = None, "unconstrained", [], None
        if d:
            reason, detail = d.reason, d.detail
        elif deciding:   # all unconstrained: most frequent reason; ties -> lexicographically first
            counts = Counter(cv.reason for cv in deciding)
            reason = min(counts, key=lambda r: (-counts[r], r))
            detail = {"unconstrained_reasons": dict(sorted(counts.items()))}
        else:            # nothing but reference checks ran, or nothing ran
            reason = "abstain:reference_only" if cvs else "abstain:no_enabled_checks"
            detail = None
        out.append(Verdict(..., call_id=raw_call_id(session, key), call_key=key, verdict=final,
                           strength=d.strength if d else "none", confidence=d.confidence if d else None,
                           rule=d.check if d else None, reason=reason, detail=detail, core=tuple(core),
                           blame_seq=blame, localized=any(c.localized for c in contra) if contra else True,
                           disagreement=bool(contra and supp), checks=tuple(cvs)))
    return out

def blame_seq(contra: list[CallVerdict]) -> int:
    """Most-cited seq among role in {'subject','conflict'} refs across contradicting checks; ties -> the later seq
    (SCOPE §5.5: 'the later one is marked probable')."""
```

**Why contradicted dominates, and why there is no vote.** A `supported` from check X says only that the fields X reads
are mutually consistent. It says nothing about the fields that check Y reads. An inconsistency anywhere in the record is
an inconsistency of the record, so a support elsewhere cannot cancel it. That is `SCOPE.md` §5.6 ("`contradicted` if any
tier contradicts"). Confidence-weighted voting is rejected because checks are not independent votes on one question:
they test different fields. Statistical checks deal with their false-positive rates where they decide, not at
composition. A statistical check emits `contradicted` only past its own pre-registered threshold, and below it emits
`abstain:below_threshold`; it **never emits `supported`** (the constructor refuses it). Not crossing a threshold is not
evidence that a result is consistent, so `supported` is reserved for identity checks. The CLI flag `--min-confidence x`
is **display-only**. It shows contradictions below `x` as `unconstrained (below display threshold)`. The eval always
composes at the default.

**How disagreement is shown.**
- `Verdict.disagreement = True`, and `checks` keeps every side.
- Terminal: a `!` after the verdict, and `--explain` lists "contradicted by X (conf), supported by Y (conf)".
- HTML: a split red/green chip whose evidence panel shows both sides.
- Eval: a `disagreement[x][y]` count matrix on honest sessions (§5.5). A high honest disagreement between an identity
  check and a statistical check points at the statistical one.

**Localization disagreement.** Two checks can both contradict while blaming different events. In that case `core` is
the union of their evidence, `blame_seq` is chosen by the rule above, and `localized` is true if any contradicting
check is localized. A stream- or session-level contradiction (`localized=False`) marks every call in that unit
`contradicted`. Render draws it as one bracket over those calls instead of per-call arcs. Every count of contradicted
calls (terminal summary, `session.json` `counts`, census) is split into `contradicted_localized` and
`contradicted_unit`, so one stream-level flag is never read as N separate detections.

### 4.7 Determinism, purity and performance rules for checks

- Pure function of (`Session`, frozen calibration). Calibration JSON is loaded at import time, and its sha256 becomes
  part of `check_version`.
- No reliance on Python `hash()` or set iteration order. Iterate sorted. Pandas sorts use `kind="mergesort"`.
- Complexity at most O(n log n) in session events. Budget: median ≤ 5 ms per 100 events per check on the dev box
  (`tests/test_eval_budget.py` measures it).
- `tests/test_check_purity.py`: running each enabled check twice, and once on a re-ordered list of sessions, gives
  identical `CallVerdict`s.
- Each calibration file records its provenance:

  ```json
  {"check": "<name>", "version": "<semver>", "lineage": "<prereg_e.json mechanism id, e.g. R1_BRACKET>",
   "source_files": {"analysis/out/phase_e/<x>.json": "<sha256>"},
   "thresholds_split": "A", "fpr_split": "B", "recall_split": "B",
   "units": {"<unit>[/<stratum>]": {"thresholds": {...}, "fpr_hi": ..., "recall_lo": ..., "n": ..., "n_sessions": ...,
                                    "enabled": true, "enable_basis": "<source key + value, DA16>", "session_cost": ...,
                                    "source_keys": {"<field>": "<file>#<json path>"}, "proxy_ok": [...]}},
   "corrections": [...]}            # id_bracket only (DA17)
  ```

  `thresholds` come from split A only (`PHASE_E_PLAN.md`: "Calibration uses split A only"), never from E (the climb
  loop's dev split) and never from H. `verifier/checks/calib/build.py <check>` writes the file by copying values from
  the listed Track A outputs, at the JSON keys §7.1 names (`source_keys`). It asserts that no source path names H, and
  it records each source's LF-normalised sha256. It refuses to run if a source's sha differs from the value pinned in
  `build.py` (Appendix A gives the prefixes when this was written). `enabled` and `enable_basis` implement DA16 for
  statistical checks; identity checks carry `enabled: true`.
- **H blindness is not declared by the check.** It lives in the frozen `config_eval.json` `h_exposure` table, keyed by
  check name and recording that check's lineage (§5.2 rule 7), written by day when the check is enabled. The code under
  test cannot mark itself blind; `lineage` in the calibration file is informational.

### 4.8 The reference check (pipeline proof only)

`verifier/checks/ref_result_present.py`, with `name="ref_result_present"`, `kind="reference"`, `strength="format"`,
`requires=frozenset({"join.call_id"})`, `reads={"events"}`, `targets=frozenset()`, `unit_kind="call"` and
`calibration=None`.
- A call with a joined result gets `supported`, reason `ok:result_joined`, evidence = [call (subject), result
  (witness)], confidence `None`.
- A call without one gets `unconstrained`, reason `missing:result`.
- **It never contradicts and never decides a composed verdict**, because reference checks are filtered out in
  `compose`. It is not in `ENABLED_CHECKS`, so it cannot inflate coverage. It exists so that `--checks
  ref_result_present` exercises loader → session → registry → compose → render → eval end to end. It makes **no
  detection claim**.

---

## 5. Eval design

### 5.1 Files and contract

`python eval/run_eval.py [--repo PATH] [--split E|H] [--mode quick|full] [--seeds 0,1,2] [--checks a,b]
[--labeled DIR] [--final --freeze SHA] [--procs 8] [--pack DIR] [--limit N] [--report-dir DIR]`. Defaults: `--repo .`, `--split E`,
`--mode quick`, `--seeds 0,1,2`, `--checks` = the `ENABLED_CHECKS` of `--repo`. It satisfies the `eval/core.py`
contract: deterministic per seed, at least 3 seeds, no GPU, and the **last stdout line is one JSON object**:

```json
{"ok": true, "headline": 0.0, "stdev": 0.0, "seeds": [0, 1, 2], "split": "E", "mode": "quick", "gate": null,
 "metrics": {"adr_loc_macro": 0.0, "adr_loc_macro_exec": 0.0, "adr_loc_macro_edit": 0.0, "edit_artifact_adr_exec": 0.0,
             "fpr_session_any": 0.0, "coverage_any": 0.0, "check_errors": 0, "runtime_s": 0.0},
 "report": "<report_dir>/run_eval_E_quick_<checkset_sha12>.json"}
```

- **Crash or contract failure** (an exception in the eval, `check_errors > 0`, `ir_schema_mismatch`, a missing pack,
  labeled join share < 0.99): prints `{"ok": false, "error": "<reason>"}`, exit 1.
- **Gate breach (DA10):** prints the full object with `"ok": true`, `"headline": -1.0`, `"stdev": 0.0`,
  `"gate": "<reason>"` (for example `"fpr_cap:<check>:<unit>"`), the ungated value in `metrics.headline_ungated`, exit
  0. Every real headline is in [0, 1], so -1.0 is below any `best` and is rejected even when `best` is still 0 (a 0.0
  would tie and be kept by `keep = new >= best - tol`). With `ok: true` the orchestrator scores the candidate, rejects
  it and resets its consecutive-failure counter (`fails = 0` when `new` is not None); `ok: false` would count toward the
  3-failure halt.

**Wiring into `eval/core.py`** (a daytime change on `main`). The orchestrator runs `core.py`, not `run_eval.py`.
`core.py`'s `main()` is replaced by `return run_eval.main(sys.argv[1:])`, which keeps the output contract and runs the
seed-independent honest pass once. `run_once(repo, seed)` stays for API compatibility and returns
`run_eval.run_seed(repo, seed)`, which memoizes the honest pass per `(repo, checkset_sha)` in-process.

**Import isolation (DA6).** `run_eval` keeps `sys.path[0]` (its own directory: `eval/` or the orchestrator's
`eval_snapshot/`) first and inserts `--repo` second, then imports `verifier`. Before scoring it asserts that
`verifier.__file__` lies under `--repo` and that no module named `analysis.lib.stats`, `analysis.lib.sample` or
`analysis.loaders.*` is loaded. For that to hold, `verifier/__init__.py` and `verifier/api.py` import
`verifier.loaders` and `verifier.render` (which pull in `analysis.loaders.newcorp_common` and through it
`analysis.lib.sample`) only inside `verify_file` and the CLI, never at module level; `verify_session` loads only
`verifier.ir`, `session`, `checks`, `registry` and `compose`. `ProcessPoolExecutor` workers (spawn on Windows) re-apply
the same `sys.path` in their initializer.

**Pack location.** `config_eval.json` `"pack_dir": "data/eval/verifier_v1"`, resolved against the main checkout:
`MAIN = Path(git -C <--repo> rev-parse --path-format=absolute --git-common-dir).parent`. That works from any worktree
and from the orchestrator's snapshot, needs no environment variable, and puts the pack where `SCOPE.md` §8.2 puts eval
inputs (`data/eval/`). `data/` is append-only (CLAUDE.md rule 5): a rebuilt pack goes to `verifier_v2/` and
`config_eval.json` is bumped by day; nothing under `verifier_v1/` is rewritten. `--pack DIR` overrides it for tests.

### 5.2 Splits and held-out strategy (DA5)

**What exists.** `analysis/HELDOUT_MANIFEST.json` lists H per corpus. The ids are in
`analysis/cache/samples/<corpus>_EH.json` under key `"H"`, and the manifest stores only
`sha256('\n'.join(sorted(H ids)).encode())` under `sha256_sorted_H_ids`. (The three sub-manifests call that rule
`digest_rule`, `hash_rule` or `hash_method`; it is the same rule.)

Counts are `corpora.<corpus>.n_H` / `.n_E` [MAN]; the agentcap exposure is `corpora.agentcap.exposed_H_sessions` [MAN].

| Corpus | n_H | n_E | Notes |
|---|---|---|---|
| swechat | 1,825 | 1,825 | |
| aiv_cu | 2,000 | 2,000 | gated licence: metrics only, never rendered |
| tbench2 | 7,129 | 2,000 | |
| agentcap | 216 | 214 | 14 H sessions parse-exposed in an abandoned A build (`exposed_H_sessions`, ids known only by sha `36df3363…`) |
| pub_cc_hf | 45 | 43 | |
| glm_tb21 | 23 | 23 | |
| pub_codex | 13 | 12 | |
| pub_trace_commons | 8 | 7 | |
| cc_local, aiv_cc, whowhen | none | none | "all … used by A+B" (`no_heldout`); excluded from H metrics, reported as "no held-out" |

**Rules.**
1. **`verifier/` never reads H, and has no notion of H.** `tests/test_no_heldout_access.py` fails if any file under
   `verifier/` contains `_EH.json`, `HELDOUT`, `_H.parquet` or `H_pack`, and if any file under `eval/` other than
   `heldout.py` reads key `"H"` of an `_EH.json` file. `CorpusAdapter.iter_sessions` asserts `split != "H"`.
2. **The climb loop and daily development run `--split E`.** E was read by Track A. It is a dev set here, not a blind
   one. For units without E (cc_local, aiv_cc, whowhen), the dev pack uses B. Calibration reads A only.
3. **H events are read only under `--final --freeze <sha>`**: `run_eval --split H` (including `--labeled DIR --split
   H`), `heldout.py build-cache`, `build-pack --split H` and `heldout.py census` (the full-corpus census, which lives in
   `eval/` because `verifier/` has no notion of H). Each of them:
   - requires `git -C <--repo> rev-parse HEAD == sha`;
   - requires `git -C <--repo> status --porcelain verifier/ eval/ analysis/lib analysis/loaders` to be empty, and the
     sha256 of every file the running eval loads to equal that file at `sha:eval/`;
   - appends `{utc, sha, argv, purpose}` to `<MAIN>/reports/eval/h_access_log.jsonl`, committed by day. The write-up
     reports the **first** `run_eval --split H` result as the held-out result and the number of H runs. Any later H run
     is reported beside it with what changed and why.

   Reading the H **id list** to recompute its digest (`heldout.py verify-manifest`) reads no event data and is allowed
   at any time.
4. **No feedback from H.** After the first H run, nothing that changes verdicts (`ENABLED_CHECKS`, thresholds,
   calibration files, `config_eval.json`) may change and still be called held-out. A check that fails on H stays in the
   H numbers and is reported as failing (§5.7).
5. **H ids** come from `eval/heldout.py`:

   ```python
   h_ids(corpus: str) -> list[str]
   ```

   It reads `#H`, recomputes the digest, and raises if the digest differs from the manifest. For agentcap it drops the
   14 exposed ids, recomputed exactly as `load_agentcap.split_incident` computes them (its docstring: "recomputed here
   exactly (same function, same seed)"): `nc.split_population` over the `agentcap_population.parquet` rows
   `[session_id, stratum, length]` plus the 2 empty OpenCode files (`load_agentcap.census()` →
   `empty_opencode_file_ids`, stratum by `hf-router` in the path, length 0); `seen = (A_806 − empty) − A_final`;
   exposed = `seen ∩ H`. The incident file holds counts and the hash, not the 806 ids, so it cannot be read for them.
   - If `sha_ids(exposed)` equals `36df3363…`, those 14 ids are dropped (the manifest's rule: "Track C drops these").
   - Otherwise agentcap H is kept and labelled `exposed: 14/216 (parse-level, no per-session values inspected)` [MAN `corpora.agentcap`].
6. **H caches.** The loaders refuse H. `nc.split_ids`, `load_tbench2.ids_for_split` and `build_split_cache` all assert
   `split in ("A","B","E")`. So `eval/heldout.py build-cache --final --freeze SHA` writes
   `<MAIN>/data/eval/verifier_v1/H/<corpus>_H.parquet` through explicit-id copies of each loader's per-session path:
   - `_build_swechat_h`: `load_swechat.build_split_e` with `ids = h_ids("swechat")`, the same format re-sniff, and
     `write_split_cache("H", ids, fmt_of, strat, ctx, path=...)`;
   - `_build_aiv_cu_h`: mirrors `load_aiv_cu.build_split_e`;
   - `_build_tbench2_h(corpus)`: rows from `<corpus>_population.parquet` filtered to H ids (H is not in the split
     index), then `load_tbench2.build_frame(rows, ...)`;
   - `_build_pub_cc_h(corpus)`: `pub_cc_common.population(corpus)["passing"]`, then `build_frame(corpus, ids, by_sid)`;
   - `_build_pub_codex_h`: `parse_one(row, red)` over population rows;
   - `_build_agentcap_h`: mirrors `load_agentcap`'s split builder.

   The build commands run from a checkout that holds the IR caches (the analysis worktree by day: `analysis/cache/` is
   gitignored and exists only there). `BUILD.json` beside the pack records the sha256 of every loader file and the
   `IR_SCHEMA_SHA`. The score path runs no loader, so a loader drift is not a failure: `run_eval` writes
   `pack_loader_drift: true` into the report when the recorded shas differ from `--repo`'s loader files, and the
   labeled join then refuses `seq`-only labels (§3.4 rule 2). An `IR_SCHEMA_SHA` mismatch is a failure (§2.4).
7. **Not fully blind.** `blind_on_H[c][u]` is printed next to every H number. It is false when, in
   `config_eval.json` `h_exposure`, check c's lineage is:
   - R3 git, R4 dual or R5 ledger, on any unit ("Their H numbers are not fully blind either. Track C must say so",
     `PREREG_E.md` §0);
   - the request-id bracket (R1/F1), latency (Probe 1 / P1) or reaction time (N3), on any new-corpus unit (tbench2,
     glm_tb21, pub_cc_hf, pub_trace_commons, pub_codex, agentcap/*): B5e "computed request-id decode deltas and
     call->result gap quantiles over the full acquired corpora" (`prereg_e.json` change_log D6).

   agentcap H additionally carries the rule-5 label when the 14 ids could not be dropped.

### 5.3 Packs and the sampling plan (≤ ~2 minutes)

Reading the full IR for E or H on every run is too slow: `swechat_E.parquet` alone is a few hundred MB of zstd. So the
eval reads a **pack**: a fixed, seed-independent, stratified subsample per unit, built once. Each pack has a sidecar
table beside it (§2.7).

- `eval/heldout.py build-pack --split {E,H}` (H only under `--final --freeze`) writes
  `<pack_dir>/<split>_pack.parquet`, with IR COLUMNS plus `unit`. It is sorted by `(unit, session_id, seq)`, has about
  50 sessions per row group, and stores the pack metadata (ids per unit, cells, attack eligibility counts, source shas,
  `IR_SCHEMA_SHA`) in the parquet schema metadata. Units without E (cc_local, aiv_cc, whowhen) are packed from B into
  the E pack and labelled `dev_split: "B"`.
- Per unit it takes `min(|split_unit|, PACK_PER_UNIT)` sessions. `PACK_PER_UNIT = 150` in `config_eval.json`. The
  sample is stratified on stratum × length tercile with `analysis.lib.sample._alloc`, using
  `rng = default_rng([SEED_E, crc32("pack|<split>|<unit>")])`, where `SEED_E = 20261005` (`PREREG_E.md` §0). Units
  smaller than 150 are taken whole. The agentcap B/E sessions excluded by `prereg_e.json` change_log D5 stay excluded.
- **Attack plans are built with the pack, not at score time.** For every seed, quick cell and unit, `build-pack` runs
  `attacks.plan(...)` and writes `<pack_dir>/<split>_attack_plan.parquet`: one row per (seed, attack, param, unit,
  session_id) holding every resolved random choice (target, donor text and latency, line pair, spliced id, inserted
  pair) and the `tampered_seqs` / `target_call_ids` / `target_streams` of the result. Donors are drawn from the **full** split of the unit
  (the prereg donor rule and the probes' pools), so pack size does not change donor matching. At score time
  `attacks.apply(plan_row, honest_frame) -> (tampered_frame, Tamper)` needs no rng and no donor pool.
- **Honest pass (seed-independent).** Every pack session is verified once. Because the verifier is deterministic, the
  honest verdicts do not depend on the seed, so FPR has no seed variance and gets a bootstrap CI instead.
- **Attack pass (seed-dependent).** For seed s ∈ {0, 1, 2}, each quick attack cell and each unit:
  - draw `min(ATTACK_PER_CELL = 40, n_eligible)` sessions from the attack's eligible pack sessions with
    `rng_for_seed(s, attack, param, unit)` (build time; a permutation, first k taken);
  - plan one tamper per session with `rng_for_seed(s, attack, param, session_id)` and donor rng
    `rng_for_seed(s, "donor", attack, param, session_id)` (build time, stored in the attack plan);
  - apply the plan row and verify the tampered copy (score time).

  `rng_for_seed(s, *parts) = np.random.default_rng(SEED_E + s + zlib.crc32("|".join(map(str, parts)).encode()))`.
  At s = 0 this equals `prereg_e_common.rng_for(*parts)`, so for a given session seed 0 reproduces the pre-registered
  tamper-target draw `rng_for(attack, param, session_id)` and donor draw `rng_for("donor", attack, param, session_id)`.
  The session subsample is different by design: it comes from the pack, not `rng_for("N7", unit, split)`.
  `tests/test_attacks_parity.py` checks this on 50 split-B sessions against `phase_e_n7_timing.inject` and the tamper
  path of `phase_e_n7_content.run_job`. 40 per seed is at least the prereg minimum of 30 tampered sessions per cell.
- **Seeds and labels.** Seeds 0–2 feed the headline (mean of per-seed values, DA12). Per-check `cell_label`s (§5.5) use
  **seed 0 only**: the three seeds reuse the same sessions with different targets, so pooling them would break the
  prereg's Wilson-over-sessions statistics. A cell whose seed-0 copies number < 30 after `inject` failures is
  `INSUFFICIENT_N`.
- **Fixed denominator.** The headline cells are every (unit, quick cell) pair with at least 30 eligible pack sessions.
  Eligibility is decided by the attack, not by any check, and is stored in the pack metadata. A check that covers
  nothing scores 0 there, so the climb loop cannot raise the headline by shrinking applicability.
- **Budget (estimates, to be confirmed by `tests/test_eval_budget.py` on the dev box).**

  | Step | Work | Target |
  |---|---|---|
  | load pack | 18 units (§2.5 table) × ≤ 150 sessions; ≈ 1,600 sessions is an estimate from the per-unit session counts of the E (or B) caches, not a saved output | ≤ 10 s |
  | honest pass | ≈ 1,600 sessions × all enabled checks, 8 processes | ≤ 25 s |
  | attack pass | 16 cells × ≤ 40 sessions × 3 seeds × eligible units (~6 average) ≈ 11.5k verifications, 8 processes | ≤ 60 s |
  | metrics | Wilson, cluster bootstraps (`N_BOOT` 1,000, seed 20261003), grid | ≤ 10 s |
  | total | | **≤ 110 s** |

  If the quick run exceeds 120 s, halve `ATTACK_PER_CELL`, then `PACK_PER_UNIT`, in `config_eval.json`. That is a
  committed daytime change. **Sizes are never adapted at run time**, because that would break determinism across
  machines.
- **Should: a per-check verdict cache.** Key: (session `ir_sha`, check name, `code_sha`), where `code_sha` = sha256
  over the bytes of `--repo/verifier/checks/<name>.py`, `verifier/checks/calib/<name>.json` and every file under
  `verifier/session/`, `verifier/ir/`, `verifier/checks/base.py` and `verifier/registry.py`. The key is computed by the
  eval from file bytes, not from the `version` the code under test reports, so a logic change without a version bump
  cannot read stale verdicts. `register()` asserts `cls.__module__ == f"verifier.checks.{cls.name}"` so the module path
  is known. Stored under `<pack_dir>/vcache/` as new files only (append-only `data/`). A climb iteration that changes
  one check module recomputes only that check; a change to shared modules recomputes everything.
- `--mode full` runs the whole prereg grid on E (B for units without E): every attack, every parameter, up to
  `N7_CAP_SESSIONS = 500` sessions per cell, seed 0, no time cap. It runs once for report tables. `--mode full --split
  H` is an H read (§5.2 rule 3).
- **The enable run is a full-mode run.** The §5.7 enable decision uses `run_eval --mode full --split E --checks
  <candidates> --report-dir reports/eval`, run once at about 13:30 (§7.3). It draws sessions from the full E caches by
  `rng_for("N7", unit, split)`, exactly as N7 did, so its cells are the same size as Track A's (≤ 500). Quick-mode
  cells (≤ 40 sessions) are a climb signal and are too coarse to enable a check. Time *(estimate)*: 20–45 min with 8
  processes for the ≤ 5 kept checks and the ≤ 61 attack-params they apply to. For scale, N7 timing took 2,561 s for 8
  detectors with 4 workers [N7T `runtime_s`].

### 5.4 The synthetic attack battery (`eval/attacks.py`)

The module is a frozen port of `prereg_e.json` `n7_attack_battery`: the same attack names, parameter grids,
eligibility rules, donor rule ("other real results of the same unit and split") and rng parts. The source
implementations are `analysis/probes/phase_e_n7_timing.py` `inject(ctx, attack, param, sid, s, target, rng, drng)` and
the tamper path of `analysis/probes/phase_e_n7_content.py` `run_job`. The port carries its own copies of the probe
helpers it needs (the `prereg_e_common` `atk_*` functions, `pick_donor`, target enumeration, the stream key), works on
**IR DataFrames only**, and imports neither `verifier` (DA6) nor `analysis`. API:

```python
@dataclass(frozen=True)
class Tamper:
    attack: str; param: str | float | None; seed: int; session_id: str
    tampered_seqs: tuple[int, ...]        # in the tampered frame (table below)
    target_call_ids: tuple[str, ...]      # raw IR call_ids in the tampered frame (table below)
    target_streams: tuple[str, ...]       # stream keys, for stream-level verdicts
    donor_session_id: str | None; byte_delta: int | None; clamped: bool

ATTACKS: dict[str, AttackSpec]            # name -> (params grid, targets(frame) -> list, fields touched)
def targets(attack: str, param, frame: pd.DataFrame) -> list                     # eligible iff non-empty
def plan(attack: str, param, seed: int, unit: str, frame: pd.DataFrame, split_frames: DonorSource
         ) -> PlanRow | None                                                    # build time: all random choices resolved
def apply(row: PlanRow, frame: pd.DataFrame) -> tuple[pd.DataFrame, Tamper]     # score time: deterministic, no rng
def to_labels(t: Tamper, tampered_frame: pd.DataFrame) -> list[LabeledCall]
```

**Targets and localization per attack.** These follow `phase_e_n7_timing.target_units` (the probe's localization
rule), except for deletions, where the probe has no target and the eval needs one.

| Attack | `target_call_ids` | `tampered_seqs` |
|---|---|---|
| `time_result_*`, `sub_*`, `reorder_lines`, `inline_fabrication` | the target pair's call (for `inline_fabrication`: the response's last call) | the target result; for `inline_fabrication` the response's rows whose `usage_out` changed |
| `time_tail_*` | the target pair's call | the target result only (later events move consistently, so they are not the discontinuity) |
| `time_response_*`, `id_swap_adjacent`, `id_splice_foreign` | every call of the touched response(s) | the touched response's first event (both responses for a swap) |
| `rewrite_consistent_k`, `reorder_adjacent_pairs` | the k (or 2) target calls | their results (and, for reorder, their calls) |
| `insert_pair_*`, `image_insert_screenshot` | the inserted call (`"inserted:<call_id>"`) | the inserted call and result |
| `image_relabel_gui` | the relabelled call | the relabelled call |
| `delete_pair`, `delete_response` | the nearest surviving call before and after the removed span in the same thread (≤ 2) | those calls' seqs. The probe treats these as undefined (`k_undefined_deleted_target`); the eval reports both |

**Threat class of each attack.** Reported results never pool across these classes; the climb headline weights them
equally (DA12).

| Class | Attacks (prereg names) | Models |
|---|---|---|
| **Execution path (in scope, primary)** | `sub_single_flip_error`, `sub_single_digit`, `sub_matched_bytes` (+ `samecmd`), `rewrite_consistent_k` (k = 2, 5; donor latency applied), `reorder_lines`, `inline_fabrication` | the agent controls the result content (and can only delay it); `inline_fabrication` = the model wrote the result itself. **Caveat for `rewrite_consistent_k`:** it shifts later harness stamps but leaves request ids and usage untouched ("ids and usage untouched", prereg). A real shim would not desynchronise later provider ids from later stamps, so a detection of this attack that relies on `request_id` or `usage` is an artifact of the edit and is reported under record editing |
| **Record editing (secondary, naive partial harness compromise)** | `time_result_early`, `time_result_late`, `time_tail_late`, `time_tail_early`, `time_response_early`, `time_response_late`, `id_swap_adjacent`, `id_splice_foreign` (random, nearest), `delete_pair`, `delete_response`, `insert_pair_consistent`, `insert_pair_squeezed`, `reorder_adjacent_pairs`, `image_relabel_gui`, `image_insert_screenshot` | someone edited a finished log without repairing every dependent field |
| **Out of scope (ceiling)** | I-forge (`SCOPE.md` §6) | coherent rewrite of every field |

**Quick cells** (`config_eval.json`). They were fixed in the architecture draft, before the N7 recall outputs
(`n7_timing.json`, `n7_content_shards/`) were read, although those files were already on disk. If the
list changes after N7 recall has been read, the change is logged in `config_eval.json` `change_log` with its reason, so
a reader can see whether the headline was fit to the mechanisms. Class: exec = execution path, edit = record editing.
- edit: `time_result_early` with D = 5 s and D = 30 s (30 s is the original back-date positive, `PHASE_E_PROMPT.md` N7);
- edit: `time_result_late` D = 30;
- edit: `time_tail_late` D = 30;
- edit: `time_response_early` D = 5;
- edit: `id_swap_adjacent`;
- edit: `id_splice_foreign:nearest`;
- exec: `sub_single_flip_error`;
- exec: `sub_single_digit`;
- exec: `sub_matched_bytes`;
- exec: `rewrite_consistent_k:2`;
- edit: `reorder_adjacent_pairs`;
- edit: `delete_pair`;
- edit: `insert_pair_consistent`;
- exec: `inline_fabrication`;
- edit: `image_relabel_gui` (aiv_cu only).

That is 16 cells: 5 exec, 11 edit. A cell with no unit meeting the eligibility floor is skipped and listed. The list
was **not changed** after the N7 recall files were read for this design, so `config_eval.json` `change_log` starts
empty.

**Execution-class credit (DA13).** `config_eval.json` holds
`"EXEC_CREDIT": {"inline_fabrication": ["inline_output_accounting"]}`. Every other exec attack maps to `[]`.
`metrics.flag_loc_credited(t, verdicts, attack)` is `flag_loc` (§5.5) evaluated on each call's `Verdict.checks`
restricted to `EXEC_CREDIT[attack]`. Only that value enters `adr_loc_macro_exec`. The unrestricted `flag_loc` of the
same exec cell is reported beside it as `edit_artifact_adr`. The reason, pair by pair:
- **`id_bracket` × `rewrite_consistent_k`.** It catches the shifted later stamps against un-shifted later ids. A shim
  delays the next request too, so its ids would not be out of step (prereg: "ids and usage untouched").
- **`ledger_tally` × `inline_fabrication`.** It catches injected `usage_out` against an unchanged session tally. A real
  inline fabrication is billed, so it is in the tally.
- **`dual_render_recount` × `sub_*` / `rewrite_consistent_k` / `reorder_lines`.** It catches edited text against an
  unchanged `numLines`. A real shim's output feeds both renderings.

Edit-class cells credit every check: a naive editor really does leave those fields unrepaired.

**Forecast for the quick cells, from Track A (not a measurement of the verifier).** This is a reading aid for the
climb. Rows show the kept check that Track A measured on that attack in swechat/claude_code E, where 500 tampered
sessions sit against the same 500 untampered. "credited" follows DA13.

| Quick cell | Kept check with power (Track A cell, E) | Label | Credited to |
|---|---|---|---|
| time_result_early 5 / 30 | `id_bracket` 3/500 = honest [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|time_result_early\|5"`]; `latency_floor` only in cc_local B 97/173 and 95/173 vs 0/173 [N7T `cells."cc_local\|B\|P1_FLOOR\|time_result_early\|5"`, `…\|30"`] | BLIND (public units) | edit |
| time_result_late 30 | `id_bracket` 335/500 [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|time_result_late\|30"`] | DETECTS | edit |
| time_tail_late 30 | `id_bracket` 485/500 [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|time_tail_late\|30"`] | DETECTS | edit |
| time_response_early 5 | `id_bracket` 163/500 [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|time_response_early\|5"`] | PARTIAL | edit |
| id_swap_adjacent | `id_bracket` 486/500 [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|id_swap_adjacent\|-"`] | DETECTS | edit |
| id_splice_foreign nearest | `id_bracket` 395/500 [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|id_splice_foreign\|nearest"`] | DETECTS | edit |
| reorder_adjacent_pairs | `dual_render_recount` 147/500 vs 0/500 [N7C `cells."swechat/claude_code\|E\|R4_DUAL\|reorder_adjacent_pairs\|-"`] | PARTIAL | edit |
| delete_pair | `ledger_tally` 219/500 [N7C `cells."swechat/claude_code\|E\|R5_LEDGER\|delete_pair\|-"`], session-level so not localized (0 toward ADR); `id_bracket` BLIND | PARTIAL | edit (recall only) |
| insert_pair_consistent | `id_bracket` 187/500 [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|insert_pair_consistent\|-"`] | PARTIAL | edit |
| image_relabel_gui (aiv_cu) | none (R2 killed, §7.2) | — | edit |
| sub_single_flip_error, sub_single_digit | none: `dual_render_recount` 0/500 each [R45 `R4.units."swechat/claude_code".n7_meta.E.cells_detail`] | BLIND | — |
| sub_matched_bytes | `dual_render_recount` 76/500 [N7C `cells."swechat/claude_code\|E\|R4_DUAL\|sub_matched_bytes\|any"`] | PARTIAL | `edit_artifact` only |
| rewrite_consistent_k 2 | `id_bracket` 151/500 [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|rewrite_consistent_k\|2"`], `dual_render_recount` 154/500 [N7C `cells."swechat/claude_code\|E\|R4_DUAL\|rewrite_consistent_k\|2"`] | PARTIAL | `edit_artifact` only |
| inline_fabrication | `inline_output_accounting` 224/500 vs 83/500, ADR 0.282 [N7C `cells."swechat/claude_code\|E\|N2\|inline_fabrication\|tau"`]; `ledger_tally` 374/500 | PARTIAL | **exec** (N2 only) |

Read plainly: in the largest unit, the execution-class headline can come only from `inline_output_accounting` on one
of five exec cells. Its expected exec macro is roughly a fifth of 0.28 *(arithmetic on the Track A ADR, not a
measurement)*. The record-editing class carries the headline. Reported results never hide this.

**Relation to `eval/inject.py`.** `SCOPE.md` §6 names `eval/inject.py` as the injector for its I-* classes. A file of
that name exists untracked in the main checkout; this design did not read it and does not import or replace it.
Whether `run_eval` also scores its classes is a morning decision (open items).

### 5.5 Metrics (definitions)

All CIs are 95%. Session shares get Wilson intervals (`eval/_stats.wilson`, a copy of `analysis.lib.stats.wilson`).
Call-level rates get the session-clustered bootstrap (`eval/_stats.cluster_rate`, a copy of
`analysis.lib.stats.cluster_rate`, `N_BOOT = 1000`, seed 20261003); `tests/test_stats_parity.py` asserts both copies
match the originals. A zero count gets the Clopper–Pearson upper bound `scipy.stats.beta.ppf(0.975, k+1, n-k)`
(`SCOPE.md` §8.4). Min-n follows `prereg.json` `global`: a rate needs at least 30 events from at least 5 sessions,
otherwise the cell is `INSUFFICIENT_N`. Every number carries its `n`.

**Flag definitions used below.** For a tampered copy t with `Tamper` T and a check c (or the composed verifier):
- `flag(t)`: at least one call of t has verdict `contradicted` (prereg `session_flag`; no localization);
- `flag_loc(t)`: at least one call v of t is `contradicted` and either `v.call_id ∈ T.target_call_ids`, or
  `v.blame_seq ∈ T.tampered_seqs`, or `v.localized` is False and its unit is a stream in `T.target_streams`. This is
  `SCOPE.md` §8.1's "the flagged call or its core includes the spoofed call", with the core bounded by `MAX_CORE`
  (§3.2).

| Metric | Definition | Per |
|---|---|---|
| `fpr_session[c][u]` | honest pack sessions with ≥ 1 `contradicted` from check c ÷ sessions where c decided or screened ≥ 1 call (reason `ok:`, `violation:` or `abstain:below_threshold`). Other sessions are excluded from the denominator and reported as `abstain_sessions`. Feeds the per-check gate | check × unit |
| `fpr_call[c][u]` | contradicted calls ÷ calls c decided or screened, honest pack, cluster bootstrap | check × unit |
| `fpr_session_any[u]` | honest sessions with ≥ 1 composed `contradicted` ÷ all honest pack sessions of u | unit (feeds the pooled gate) |
| `recall[c][a][p][u]` | tampered copies with `flag(t)` ÷ tampered copies; abstention counts as not flagged. This is the prereg recall, used for `cell_label` | check × attack × param × unit, seed 0 |
| `recall_loc[c][a][p][u]` | tampered copies with `flag_loc(t)` ÷ tampered copies (`SCOPE.md` §8.1: localization required) | same, per seed |
| `adr[c][a][p][u]` | P(`flag_loc(t)` **and** the same session's honest copy not flagged by c) (prereg N7 ADR, with localization added) | same, per seed; session bootstrap |
| `cell_label` | `prereg_e.json` `n7_cell_label` on seed 0: DETECTS if `recall` ≥ 0.5 and recall CI lo > FPR CI hi; PARTIAL if recall CI lo > FPR CI hi; BLIND otherwise; INSUFFICIENT_N below 30 tampered sessions; `NA_BLIND_BY_CONSTRUCTION` when `c.reads ∩ ATTACK_FIELDS[a] = ∅`. **FPR here is the prereg one**: the flag rate of the same drawn sessions untampered, abstention counted as not flagged, Wilson over sessions | same |
| `localization[c][a]` | tampered copies with `flag_loc(t)` ÷ tampered copies with `flag(t)` (prereg "localization"); deletions also reported the probe's way (undefined target excluded) | check × attack |
| `coverage[c][u]` | calls c decided or screened ÷ all calls, honest pack; split by `kind` (identity / statistical) and by `strength`. For a statistical check this is "calls it could have flagged" | check × unit |
| `coverage_any[u]` | calls with ≥ 1 enabled check deciding or screening ÷ all calls (`SCOPE.md` §8.1 "nominal coverage", ≥ 1 applicable oracle); `supported_share[u]` and `contradicted_share[u]` beside it | unit |
| `transfer[c][u]` | `prereg_e.json` `n6_transfer_grid` cell vocabulary. ALIVE / WEAK / DEAD follow **one rule for every kept check**: `prereg_e.json` `a1.proposal_rules`, applied to the frozen verifier's own outputs. That is the session-level honest flag rate (stream-level for `id_bracket`) plus the seed-0 `cell_label`s: ALIVE = honest ≤ 0.05 with CI hi ≤ 0.10 and ≥ 1 single-call/single-response attack DETECTS; WEAK = honest ≤ 0.20 and ≥ 1 attack DETECTS or PARTIAL; DEAD otherwise. Also `INSUFFICIENT_N`; `NOT_TESTABLE(<cap>)` when the capability is absent from every pack session of the unit (`n6_transfer_grid.fill_rule` 1); `NOT_RUN(uncalibrated_unit)` and `NOT_RUN(unit_not_enabled)` (DA16). Beside each cell, the report prints the Track A label of the same mechanism × unit from §7.1, with its source key, so drift between Track A and the verifier is visible | check × unit (the N6 grid, now on the frozen verifier) |
| `edit_artifact_adr[a][p][u]` | for exec cells only: ADR of unrestricted `flag_loc` minus ADR of `flag_loc_credited` (DA13), with the checks responsible | exec cell |
| `disagreement[x][y]` | honest calls where x says contradicted and y says supported | check pair |
| `check_errors` | count of `error:` verdicts | run |
| `labeled.*` (when `--labeled`) | per `cls`: recall on `pos`, FPR on `neg`, precision, with session-clustered CIs; `unknown` excluded but counted; `join_status` counts | class |

**Headline (DA12; a climb score, not a reported result).** For seed s, `ADR_s(cell)` is the ADR of the **composed
verifier** on that (unit, quick cell) headline cell (§5.3), with "flagged" = `flag_loc` on edit cells and
`flag_loc_credited` on exec cells (DA13). Then
`adr_loc_macro_exec_s` = mean of `ADR_s` over exec cells, `adr_loc_macro_edit_s` = mean over edit cells, and
`headline_s = 0.5 × adr_loc_macro_exec_s + 0.5 × adr_loc_macro_edit_s` (if a class has no headline cell, the other
class alone). `headline = mean_s(headline_s)` and `stdev = pstdev_s(headline_s)`, exactly what `eval/core.py`'s
`main()` computes from per-seed `run_once` values. Each cell weighs the same within its class, so a many-parameter attack
cannot dominate, and the record-editing class (11 of 16 cells) cannot pull the climb away from the in-scope class.
Reported results (write-up, figures) are per cell and per class, never this pooled number. Deviation from `SCOPE.md`
§8.2: see the deviations table.

**Gates.** In this order; the first that holds decides:
1. `ok: false` (exit 1): `check_errors > 0`, `ir_schema_mismatch`, a missing pack, or `--labeled` with join
   `ok` share < 0.99 (`SCOPE.md` §7.14's 0.99).
2. `gate: "fpr_cap:<check>:<unit>"` (DA10: `ok: true`, `headline: -1.0`): an enabled check's honest `fpr_session[c][u]`
   Wilson upper bound exceeds `fpr_cap[c]`, checked only on units with ≥ 30 decided-or-screened sessions (prereg min-n);
   smaller units are reported `INSUFFICIENT_N` and covered by gate 3.
3. `gate: "clean_cap"` (DA10): the Wilson upper bound of `fpr_session_any` pooled over **all** honest pack sessions
   exceeds `CLEAN_CAP`.

`fpr_cap` and `CLEAN_CAP` are **regression guards for the climb**. They are not acceptance thresholds: acceptance is
§5.7 on the full-mode E run. Both are written into `config_eval.json` by day, from the **freeze baseline run**. That
run is the first quick E run with the frozen `ENABLED_CHECKS`, and it records `k_base[c][u]` and `n[c][u]` on the
pack.
- `fpr_cap[c][u] = wilson_hi(k_base[c][u] + 1, n[c][u])`. One additional honest contradicted session in a unit is
  tolerated; two are a reject. A Wilson bound on a pack of about 150 sessions cannot fall below about 0.025, even at
  k = 0 *(arithmetic)*, so a cap copied from Track A's 500-session or full-E bound would reject the baseline itself.
  The cap must therefore be expressed on the pack.
- `CLEAN_CAP = wilson_hi(K_base + ceil(0.002 × N), N)` over all honest pack sessions. This is `SCOPE.md` §8.2's
  "baseline + 0.2 points", expressed in sessions.
- The baseline values themselves are reported beside the Track A expectations in §7.1. A baseline that is far above
  Track A's rate for the same check and unit is a parity bug, not a cap to accept: it blocks the freeze (§7.3 step F2).

Note the unit: SCOPE's clean rate is a contradiction rate; here it is the session-level any-contradiction rate (prereg
`session_flag`), which grows with session length for per-call checks, as the prereg accepts.

**Report file.** `<report_dir>/run_eval_<split>_<mode>_<checkset_sha12>.json` holds every table above with `n`, CIs,
`blind_on_H`, pack metadata, config sha and verifier version. `<report_dir>` defaults to `<MAIN>/ops/state/eval/reports/`
(runtime state, gitignored, outside every worktree), because the orchestrator runs the eval with `cwd` = the worktree
under test and a later `git add -A` there would commit a report written into it. A day run passes `--report-dir
reports/eval` to write the committed copy. `<report_dir>/honest_contradictions_<sha12>.jsonl` lists
`(corpus, unit, session_id, call_id, check, reason)` for every honest-pack contradiction, refs only and no content, for
the daytime manual review (`SCOPE.md` §5.7). cc_local rows are replaced by per-(check, reason) counts (private:
aggregates only, `analysis/README.md` rule 7).

### 5.6 Determinism

- Jobs are `(seed, cell, unit)` tuples, run in a `ProcessPoolExecutor(max_workers=--procs)` and merged sorted by job
  key.
- No wall-clock values enter any metric. `runtime_s` is excluded from the report's content hash.
- JSON is written with `sort_keys=True` and floats rounded to 6 places.
- `tests/test_determinism.py` builds a 20-sessions-per-unit **A** pack and attack plan into a temp dir
  (`heldout.py build-pack --split A --per-unit 20 --out <tmp>`), runs `run_eval --pack <tmp>` twice, and asserts
  identical report hashes. Tests never need the E pack to exist.
- `PYTHONHASHSEED` is irrelevant by construction (no `hash()`), and the test runs with two different values to prove
  it.

### 5.7 Per-check success criteria (template; filled per check in §7.1)

Two uses of one template, never mixed:
- **Enable decision (dev, on E; B for units without E).** At the freeze, a check is enabled iff its PARITY and MUST
  rows pass on E, on the full-mode run of §5.3. This is the only place the criteria change what ships.
- **Confirmation (on H, once, after the freeze).** The same rows are evaluated on H and reported as PASS / FAIL beside
  the E values. A FAIL is reported, not acted on (§5.2 rule 4): the check stays in the H numbers.

```
check: <name> v<version>     kind: identity|statistical     rule type (DA11): 1|2|3     units claimed: <list>     blind_on_H: per unit
PARITY the check, run on the full E (or B) cache of each claimed unit, reproduces the named Track A count exactly (DA15)
MUST   honest session flag rate on the claimed unit, full-mode E run: k/n with Wilson hi <= the value in 7.1
       (set from Track A's measured bound on the same unit and population; it is a parity tolerance, not a new target)
MUST   >= 1 declared target attack whose cell_label on E is at least the level in 7.1 (DETECTS for identity checks that
       have one in Track A; PARTIAL where Track A's best is PARTIAL, stated as such)
SHOULD localization >= the value in 7.1 on its DETECTS/PARTIAL cells (Track A's localization share minus 0.05)
SHOULD coverage[c][u] reported (no threshold: Track A did not measure per-call coverage for any kept check)
FLAG   (H only) H fpr_session CI lo > E fpr_session CI hi: reported as "H disagrees with E", no change to the check
REPORT every target attack with no DETECTS cell, in the walk-through table (prereg N7 'outputs')
```

The MUST thresholds are copied from Track A, not invented, so that the check reproduces the measurement Track A made.
A check that fails PARITY never reaches the MUST rows: its numbers would describe a different mechanism from the one
Track A measured.

### 5.8 The labeled-corpus path (later)

1. Receive the directory (§3.4). Run `eval/labeled.py validate DIR` (schema, file shas, join dry run) and then
   `register DIR` (split, manifest digest).
2. During development, `run_eval.py --labeled DIR --split E` verifies the labeled set's B/E sessions. Once, after the
   freeze, `run_eval.py --labeled DIR --split H --final --freeze SHA` verifies its H sessions with the same frozen
   verifier (an H read, logged; §5.2 rule 3). Both add the `labeled.*` metrics and the join stats to the report and
   `labeled_recall_macro` to `metrics`, without changing `headline`. A human decides whether the headline moves to
   labeled data. If the set arrives after the freeze, it cannot change the frozen verifier: its E numbers are reported
   as development numbers and its H is read once.
3. If labels carry a ground-truth negative class (for example, delivered output equal to formatted execution), the
   report shows FPR on those negatives beside the presumed-honest FPR on public corpora. It never pools the two.

---

## 6. CLI and demo surfaces

### 6.1 CLI

```
python -m verifier [verify] PATH [PATH ...]              # 'verify' is the default subcommand (SCOPE §2: python -m verifier <transcript>)
    --format {auto,claude_code,codex,opencode,gemini,atif,ir,turns}   default auto (loaders.detect.sniff)
    --session ID          only this session (IR parquet or multi-session input)
    --unit UNIT           calibration unit (default by format, printed as 'borrowed'; 4.5)
    --checks NAMES        comma list | 'enabled' (default) | 'all' (adds reference checks)
    --show {constrained,contradicted,all}       default constrained, plus a one-line summary of the rest
    --explain CALL_ID     full evidence for one call: every check's verdict, reason, detail, evidence refs and values
    --min-confidence X    display-only threshold (4.6)
    --json OUT.jsonl      every call's Verdict + OUT.session.json
    --html OUT.html       static page (6.2)
    --max-chars N         excerpt length (default 100 in the terminal, 2,000 in html)
    --no-color            no ANSI codes (default: colour when stdout is a tty)
    --strict              re-raise check exceptions
    --allow-unpublishable render content of non-publishable corpora to a LOCAL file (6.3); prints a warning
    --sidecar FILE.json   extra harness records for this session (2.7), e.g. {"entire_tally": {...}}; validated by
                          validate_sidecar; cc_numlines is read from a Claude Code JSONL automatically
  exit codes: 0 no call contradicted; 1 >= 1 contradicted; 2 input/parse error (unknown format, empty session);
              3 a check exception or contract violation under --strict. Without --strict these become 'error:'
              verdicts, a warning line counts them, and the exit code follows the verdicts.

python -m verifier checks [--json]           # registry: name, version, kind, strength, requires, reads, targets, calibrated units
python -m verifier inspect PATH              # capabilities of each session and, per check, applicable / missing:<cap> / uncalibrated
python -m verifier census --corpus C --split {A,B,E} [--limit N] [--procs 8] --out reports/census/<C>_<split>_verdicts.parquet
                                             # refuses H; cc_local output is aggregates only (counts per reason), never rows
python -m verifier render VERDICTS.jsonl --source PATH --html OUT.html
python -m verifier demo --input demo/input [--out demo/index.html]       # renders files written by heldout.py demo-input
python eval/run_eval.py ...                  # 5.1
python eval/heldout.py {verify-manifest | build-cache | build-pack | census | demo-input} [--split A|E|H] [--final --freeze SHA]
                                             # build-cache, build-pack --split H and census need --final (5.2 rule 3)
python eval/labeled.py {validate | register} DIR
```

The CLI calls `sys.stdout.reconfigure(encoding="utf-8")`, because the corpora contain non-ASCII text and the Windows
console default is not UTF-8. Input format detection (`verifier/loaders/detect.py`):
- `.parquet` with exactly the IR COLUMNS → `ir`;
- `.json` whose top-level object has a `steps` list → `atif` (`load_tbench2.parse_atif`);
- `.jsonl` whose first object has `role` and `turn_number` → `turns`;
- otherwise `load_swechat.sniff_text(load_swechat.read_head(path))` → claude_code, codex, opencode, gemini, cursor,
  copilot or simple_text.

`cursor` and `simple_text` load, but they carry no results or no clock (`CORPUS_INVENTORY.md` §1.3: cursor fails the
field audit). They come out `unconstrained` everywhere, with a header line saying why. One file is one session, with
`session_id` = file stem, as swechat does. Directory input (a Claude Code project with subagent files, via
`pub_cc_common`) is **cut from this build**: no finding justifies it (§7.2).

**Terminal output** (shape only; every number in this block is illustrative, not a measurement):

```
session 3f2a…  file:claude_code  84 calls  calibration: swechat/claude_code (borrowed by format)
capabilities: ts.ms ts.pair_distinct join.call_id request_id.decodable usage.io error.marker sidecar.cc_numlines
checks: dual_render_recount 1.0.0 (ran)  id_bracket 1.0.0 (ran)  inline_output_accounting 1.0.0 (ran)
        ledger_tally 1.0.0 (missing:sidecar.entire_tally)
 seq  time          tool   call                          verdict          by                    reason
  12  12:00:01.204  read   src/api.py                    supported        dual_render_recount   ok:recount_match (format)
  31  12:03:44.010  shell  pytest -q                     CONTRADICTED !   id_bracket            violation:bracket_infeasible (conf 0.997)  core #29 #30 #33
        "response #30 is stamped 27.8 s before the earliest time its request id allows, given the stream's other
         responses; tolerance 2,000 ms. Provider clock inferred from an undocumented id layout."
        also supported by dual_render_recount (format)   <- disagreement
  47  12:09:10.551  shell  cat build.log                 unconstrained    —                     abstain:result_below_800_chars
summary: 84 calls | contradicted 2 (localized 2, unit-level 0) | supported 31 | unconstrained 51 (screened 9, missing:request_id 3, abstain:not_last_call 39)
orphan results: 0      exit 1
```

### 6.2 The static HTML page (`verifier/render/html.py`)

```python
def render_session_html(session: Session, verdicts: list[Verdict], *, title: str,
                        compare: tuple[Session, list[Verdict], dict] | None = None,     # honest/tampered toggle; dict = tamper.json
                                                                                        # (Tamper fields; verifier never imports eval)
                        baseline_existence: bool = True,                                  # 'call present in log' column
                        max_chars: int = 2000) -> str
```

- **One self-contained file.** CSS, JS (≤ 200 lines, vanilla) and SVG are inline. There are no network requests and
  no new dependency. Everything is built with `html.escape` and f-strings. The page renders server-side, so it reads
  with JS disabled; JS adds only the toggle, the expansion and the scan animation.
- **Layout, top to bottom.**
  - **Header**: corpus, harness/format, model, call count, and capability chips (`ms clocks ✓`, `request ids ✓`,
    `usage ✓`, `dual render ✗`).
  - **Coverage bar**: supported / contradicted / unconstrained shares of calls, with the unconstrained part split by
    reason family (`abstain:below_threshold` light outline: screened by a statistical check, nothing found;
    `missing:*` hatched grey: the record lacks the data; other `abstain:*` plain grey: the data exists, but no rule
    covers it).
  - **Transcript**: the user prompt and assistant text, collapsed. Then one card per call:
    `seq · time · tool · command/args excerpt · result excerpt · verdict chip`.
- **Verdicts lighting up.** On load, a scan line walks down the cards, about 40 ms per card, the chips are revealed in
  sequence, and contradicted cards pulse red once. `prefers-reduced-motion` turns the animation off.
- **Deciding evidence inline.** Under a contradicted or supported card, an evidence strip shows `explain()` and the
  `detail` numbers. A left gutter holds SVG arcs from the card to every `core` event's card, with the `blame_seq` arc
  solid and the others dashed. A non-localized (stream/session) contradiction is drawn as one bracket spanning its
  calls. Hovering an evidence ref highlights its card.
- **"Existence check" column** (`baseline_existence`): a ✓ on every call that has a tool_use. This is what an
  OverclaimBench/Kraishan-style check reports (`SCOPE.md` §2 deliverable 3; `PROJECT_BRIEF.md` §8 "The demo").
- **Honest/tampered toggle** (`compare`): one switch re-renders in place. The tampered card shows a before/after diff
  of the changed fields (text diff by line, timestamps side by side).
- **Disagreement**: a split chip. The panel lists both sides with their confidences.
- **Footer**, always present: verifier version, checkset sha, calibration unit (and "borrowed" when it is), and the
  sentence "Synthetic tamper. This tool has not detected a natural fabrication in any corpus we hold." whenever
  `compare` is set. (Not "no corpus contains one": combo2's harness-flagged substitutes are unread, §1.4.)
- **Safety**: every displayed string passes through `analysis.loaders.newcorp_common.redact` (credential patterns),
  then `html.escape`. Excerpts longer than `max_chars` are cut with `… [N chars]`.

### 6.3 The demo (`verifier/render/demo.py`, DA9)

Two steps, so that `verifier` never imports `eval`:
1. `python eval/heldout.py demo-input --spec verifier/render/demo_spec.json --out demo/input/` reads the session from
   the E pack, applies the spec's attack plan row with `attacks.apply` and writes `honest.parquet`,
   `tampered.parquet` (IR COLUMNS) and `tamper.json` (the `Tamper` fields).
2. `build_demo(input_dir="demo/input", out="demo/index.html")` (`python -m verifier demo`) verifies both frames with
   `verify_session`, and calls `render_session_html(..., compare=(tampered_session, tampered_verdicts, tamper_dict))`.

The specs (two pages; the second is SHOULD; shown with `//` labels, each file is plain JSON):

```jsonc
// verifier/render/demo_spec.json  (primary page; record-editing class)
{"corpus": "swechat", "unit": "swechat/claude_code", "split": "E",
 "session_id": "<resolved by heldout.py demo-input under why_this_session, written to demo/input/tamper.json>",
 "attack": "time_response_early", "param": 30, "seed": 0, "checks": "enabled", "class": "edit",
 "why_this_session": "first session by sorted session_id among the unit's E-pack sessions in the attack's seed-0 plan whose tampered copy is flag_loc by the composed verifier and whose honest copy is not flagged",
 "cell_recall_loc": "<computed by demo-input from the seed-0 plan: k/n of flag_loc tampered copies in this cell; printed on the page>",
 "track_a_reference": "N7T cells.\"swechat/claude_code|E|R1_BRACKET|time_response_early|30\": 488/500 vs 3/500 honest"}
// verifier/render/demo_spec_exec.json  (second page; in-scope class)
{"corpus": "swechat", "unit": "swechat/claude_code", "split": "E", "session_id": "<resolved as above>",
 "attack": "inline_fabrication", "param": "tau", "seed": 0, "checks": "enabled", "class": "exec",
 "why_this_session": "same rule as the primary page",
 "cell_recall_loc": "<computed by demo-input>",
 "honest_session_cost": "N2 units.\"swechat/claude_code\".groups.\"swechat/claude_code\".results.E.session_level_honest_flag_share: 237/1,492 — printed on the page beside the hit",
 "track_a_reference": "N7C cells.\"swechat/claude_code|E|N2|inline_fabrication|tau\": 224/500 vs 83/500 honest (PARTIAL)"}
```

Why these attacks. The primary page uses the strongest measured cell with the plainest story. The log says this
response started streaming at time t. The provider's own clock, embedded in its request id, says the request
could not have been minted before t + 28 s *(illustrative)*. It is a record-editing tamper, and the page says so.
The second page is there because the in-scope class must be shown honestly too. It shows inline fabrication caught by
the token-accounting identity, and it prints that check's honest session cost on the same page. If
`inline_output_accounting` is not enabled at the freeze, the second page is not built.

The selection rule is fixed now, before any session is looked at: it picks a hit, and the page prints the cell's hit
rate (`cell_recall_loc`) beside it so the reader sees how often that hit happens.

**Corpus rules.**
- `PUBLISHABLE = {"swechat", "tbench2", "pub_trace_commons", "glm_tb21"}` (ODC-BY, Apache-2.0, CC BY 4.0, MIT;
  `CORPUS_INVENTORY.md` §1.3). `pub_cc_hf` is per-repo and needs a per-repo check first. swechat is gated on HF:
  `SCOPE.md` §2 item 6 and §11 require checking the gate terms before publishing a derivative, and a tampered session is
  one. Until a human confirms the terms (open items), the demo page is built locally and not published.
- `aiv_cc` and `aiv_cu` are gated, with custom research terms. `cc_local` is private: it is never rendered, and
  `render_session_html` raises on it even with `--allow-unpublishable`.
- The demo never uses H (§5.2). It uses E, which is public and already read.

**What one demo session looks like (storyboard).**
1. Open `demo/index.html`. Header: a public Claude Code session from SWE-chat, N tool calls, with capability chips
   showing that this record carries ms clocks, provider request ids and usage. Ids and usage are fields the agent
   cannot set; the result clocks it can only delay (§1.2).
2. The scan runs. Most cards turn plain or hatched grey, some green. The coverage bar settles at "k of N calls
   constrained, 0 contradicted". The honest record is consistent everywhere it can be tested.
3. Flip the toggle to "Tampered: `<attack>` on call #j (seed 0)". The existence-check column still shows ✓ on every
   call. Card #j turns red, arcs reach to its evidence cards, and the strip states the numbers that disagree and the
   rule they break (DA11 type 1–3).
4. Click #j. The panel shows the honest result, the tampered result, the deciding check's explanation, the cell's
   seed-0 hit rate, and its honest FPR with n: from the `--final` H report if it exists, otherwise the E value labelled
   "E (development)".
5. The footer states that this tamper is synthetic and that no natural fabrication has been detected in any corpus we
   hold. It names the tamper's threat class ("record editing: someone edited a finished log"; or "execution path:
   the model wrote the tool result itself") and, on an `id_bracket` page, adds "provider clock inferred from an
   undocumented id layout" (§1.6).

**Cut from this build: gallery.** `demo/gallery.html` would be a grid of quick attack cells × units, each cell
linking to a rendered example page, with BLIND cells shown as prominently as DETECTS cells. No finding justifies it
(§7.2), and the recall-per-attack figure (§6.4) carries the same table.

### 6.4 Figures (`verifier/render/figures.py`)

`transfer_matrix_svg(report: dict) -> str` and `recall_table_html(report: dict) -> str` read the eval report JSON and
write `reports/figures/transfer_matrix.svg` and `reports/figures/recall_per_attack.html`.
- Cells carry the vocabulary label and `n` as text, and colour encodes only the label. `NOT_TESTABLE` and `NOT_RUN`
  cells are shown, never dropped (`PHASE_E_PROMPT.md` N6: "failing cells included").
- Hand-written SVG, no plotting dependency (DA8).

---

## 7. The checks, the feature tiers, the build

### 7.0 Selection: what survived Track A and cleared Track B

The rule (`PHASE_E_PROMPT.md` C1, applied as written):
- **Survived** means a final Track A label of WEAK or better: SURVIVES, or DOWNGRADED-but-WEAK-or-better.
- **Cleared** means the `PRIOR_ART.md` verdict for the claimed contribution is not TAKEN. PARTIAL is allowed when the
  difference is stated. UNVERIFIED does not clear, and neither does having no verdict at all (P2, P3, P4: Track B never
  assessed them).
- The rule applies to **every feature**, not only to checks. A census statistic, a second clock source or a witness
  plugin built on an uncleared mechanism is cut as well (§7.2).
- On top of that, a candidate becomes a per-call check only if its rule is of DA11 type 1–3. A distributional
  statistic can only be a census number.

| Mechanism | Track A final label (largest unit) | Track B | DA11 | Decision |
|---|---|---|---|---|
| R1 request-id bracket | **ALIVE** swechat/claude_code **[resolved here]**: F1 ceiling ALIVE, pending only N7 [F1 `r1."swechat/claude_code".verdict`]; N7 E lists 4 single-call types as DETECTS [N7T `verdicts.per_unit_split_detector."swechat/claude_code\|E\|R1_BRACKET".single_call_types_detecting`]. The Track A assembly agrees: SURVIVES → ALIVE [SP `r1_rows`]. WEAK in cc_local, tbench2 (N6 says ALIVE; §7.1.1), pub_cc_hf | PARTIAL (method near-TAKEN; application NOVEL); MATERIAL LIMITATION | type 1 | **MUST** `id_bracket` |
| N2 token accounting | WEAK swechat/claude_code [N2 `units."swechat/claude_code".cell_final`]; ALIVE in 3 aiv_cu strata and agentcap/opencode | PARTIAL (B3.4) | type 2 | **MUST** `inline_output_accounting`: the only surviving mechanism whose in-scope power is not an edit artifact (§1.5) |
| R5 usage ledger | **ALIVE** (E not blind) [R45 `R5.units."swechat/claude_code".survival`] | PARTIAL via B3.1/B3.2 (tally leg not separately searched; open item 14) | type 1 | **SHOULD** `ledger_tally` |
| R4 dual rendering | **WEAK** (SURVIVES, E not blind) [R45 `R4.units."swechat/claude_code".survival`] | PARTIAL (B3.5) | type 1, record editing only | **SHOULD** `dual_render_recount` |
| P1 latency floor | **WEAK** after DOWNGRADED in all three units [P13 `verdicts."P1/swechat/opencode"`, `."P1/cc_local"`, `."P1/swechat/claude_code"`] | PARTIAL (B1(a)); premise TAKEN as context | type 2 | **COULD** `latency_floor` (one private unit qualifies) |
| N1 conditional duration | ALIVE as a population statistic in swechat/claude_code [N1 `units."swechat/claude_code".cell_final`] | PARTIAL (B1(a), B1(b)) | the per-call rule is weak (§7.1.6) | not a check: transfer grid only |
| P3 zero-error tail | ALIVE (SURVIVES) [P13 `verdicts."P3zero/swechat/claude_code"`] | no verdict: not in the `PRIOR_ART.md` table, so it does not clear (§3.10 adds that error fabrication evades it) | distributional | **cut**, census statistic included |
| P2, P4, N3, N4, N5a–g, R2, R3 | WEAK at best, DEAD or KILLED (§7.1.6) | not assessed / UNVERIFIED / PARTIAL | — | cut |

### 7.1 Per-check designs

Every block follows the per-check template of `DESIGN_ARCH_DRAFT.md` §7.1. Check modules live in
`verifier/checks/<name>.py`. Each check's
logic sits in **module-level pure functions** that take an IR `DataFrame` (one session) plus a sidecar dict. The
`Check` class is a thin wrapper around them. This split lets a check's parity test run on the IR caches from 09:30,
before `verifier.session` and the registry exist (§7.3).

#### 7.1.1 `id_bracket` (module `verifier/checks/id_bracket.py`, class `IdBracketCheck`) — MUST

**Justifying findings.**
- **swechat/claude_code: ALIVE [resolved here].** F1 left R1 at `PENDING_N7`, with ceiling ALIVE after checks
  [F1 `r1."swechat/claude_code".verdict`]. Its stated remaining condition is that at least one single-call or
  single-response type DETECTS on E in N7. N7 lists `id_splice_foreign`, `id_swap_adjacent`, `time_response_early` and
  `time_result_late` [N7T `verdicts.per_unit_split_detector."swechat/claude_code|E|R1_BRACKET".single_call_types_detecting`].
  - Honest leg, with the adopted corrections: 11/3,325 streams = 0.00331 [0.00145, 0.00551], 1,484 sessions
    [F1 `f1_effective_fp."swechat/claude_code".E.honest.rate_by_session`].
  - Session-level on N7's E draw: 5/687, Wilson hi 0.0169
    [N7T `verdicts.per_unit_split_detector."swechat/claude_code|E|R1_BRACKET".honest_union_of_selected_sessions`].
  - Kill attempts it survived: AC1–AC5, and no confined stratum [F1 `r1."swechat/claude_code".artifact_checks`, `.strata`].
- **cc_local: WEAK, B only [resolved here].** The ceiling after checks is WEAK, from AC4: one project
  [F1 `r1.cc_local.verdict.ceiling_after_checks`]. N7 B has DETECTS cells
  [N7T `verdicts.per_unit_split_detector."cc_local|B|R1_BRACKET".single_call_types_detecting`].
- **Transfer (new data, frozen thresholds, NOT_BLIND per D6).**
  - tbench2 (WozCode stratum only): 0/168 honest streams [TB `detail.R1.BuE.honest`]. Label WEAK after the
    orchestrator's AC4 resolution [RES `resolutions[0].label_after`]. The N6 grid, assembled later and still
    uncommitted, labels the same cell ALIVE [N6 `cells.R1_bracket.tbench2.label`]. It took the raw E verdict without
    applying RES. RES itself names that reading as the only way the cell stays ALIVE. This design keeps WEAK (open
    item 17).
  - pub_cc_hf: 0/82 streams [PCH `r1.pooled_BuE.honest`]. WEAK (DOMINATED by one model) [PCH `cells.R1_bracket.label`].
  - pub_trace_commons: 0/14 streams, INSUFFICIENT_N [PTC `cells.R1_bracket`].
  - Every other unit is NOT_TESTABLE, because it has no decodable request id.
- **Track B.** PARTIAL: the method is old, the application is new. The fact row is a MATERIAL LIMITATION (§1.6).

**Protocol attributes.**
`name="id_bracket"`, `version="1.0.0"`, `kind="identity"`, `strength="strong"`,
`requires=frozenset({"request_id.decodable", "ts.event"})`, `reads={"ts", "order", "request_id"}`,
`targets={time_response_early, time_result_late, time_tail_late, time_tail_early, id_swap_adjacent, id_splice_foreign,
insert_pair_consistent, insert_pair_squeezed, rewrite_consistent_k}`, `unit_kind="stream"`,
`calibration="verifier/checks/calib/id_bracket.json"`. Lineage: `R1_BRACKET` / `F1`.

**Rule type (DA11): 1.** Harness stamps are compared with the provider clock embedded in the request id.

**Soundness.** The provider mints response k's id after its request arrives. The request contains the last input
event before it: a result or a user turn. The id is minted before the response's first output. With one constant
client–server offset θ per stream, `prev_ms_k ≤ emb_k + θ ≤ first_ms_k` must hold for every k. So the stream is
feasible iff `max_k(prev_ms_k − emb_k) − min_k(first_ms_k − emb_k) ≤ tol`.
- **Under execution-path compromise it is never violated, and therefore has no power.** A shim that delays a result
  also delays the next request.
- **It catches** edits that move a harness stamp relative to the provider clock, and edits that move an id between
  responses.
- **It is one-sided.** Forward-dating, results moved earlier and deletions loosen the bracket.
- **It is sound against no forger who re-mints ids** (§1.6). Execution-class credit is therefore none (DA13).

**Inputs.**
- `Session.events`: `seq, kind, ts, request_id, is_subagent, agent_id, call_id`.
- `Session.clocks.ts_ms`, `Session.clocks.provider_ms` (`idclock.decode` with the DA20 gate).
- `Session.threads` (stream key: `"main"`, or the subagent id).
- `Session.sidecar["copied_request_ids"]` (optional).

**Algorithm.** It ports `prereg_e_common.bracket_responses` and `bracket_streams` unchanged, plus F1's
`stream_status` restricted to the adopted set.

```python
def responses_with_bounds(ev: pd.DataFrame, provider_ms: np.ndarray) -> tuple[pd.DataFrame, list[int]]:
    """One row per (stream, request_id): first_seq, first_ms (first event carrying the id), emb (decoded ms), and
    prev_seq / prev_ms / prev_kind: the last event of the same stream with kind in {result, user}, seq < first_seq,
    finite ms (merge_asof backward, allow_exact_matches=False). lo = prev_ms - emb; hi = first_ms - emb.
    Ids with |first_ms - emb| > 86_400_000 ms are removed and returned in the second element (implausible)."""
def dedupe_copied(R: pd.DataFrame, copied: Mapping[str, str], session_id: str) -> pd.DataFrame
    """F1 restamped_copy: drop rows whose request_id is in `copied` and whose session is not the smallest holder."""
def stream_brackets(R: pd.DataFrame) -> list[StreamBracket]
    """Per stream with >= 2 responses: L = nanmax(lo), U = nanmin(hi), gap = L - U, k_L = nanargmax(lo),
    k_U = nanargmin(hi) (first index on ties, as numpy does)."""
def drop_user_bindings(Rs: pd.DataFrame, sb: StreamBracket, tol_ms: float) -> StreamBracket | Literal["abstain"]
    """F1 user_input_binding drop: while gap > tol and the L-binding response's prev_kind == 'user', drop it and
    recompute; fewer than 2 responses left -> 'abstain'."""
def bracket_verdicts(ev, provider_ms, sidecar, *, tol_ms=2000.0,
                     corrections=("restamped_copy", "user_input_binding")) -> dict[str, BracketOutcome]
    """call_key -> outcome. Called by IdBracketCheck.run with the calibration file's `corrections`, and by the parity
    test with corrections=() so that it can compare against N7, whose R1 detector is the uncorrected rule."""
```

Decision: a stream is **inconsistent** iff `gap > BRACKET_TOL_MS` after the adopted corrections. A call belongs to the
response whose `request_id` it carries; Claude Code writes `requestId` on every content block of a response.

| Situation | Per-call verdict | Evidence (≤ `MAX_CORE` = 6 seqs) |
|---|---|---|
| consistent stream | `supported`, `ok:within_bracket`, confidence `recall_lo[unit]` | subject: the call; witness: response first event (`request_id`); witness: its prev input (`ts`) |
| inconsistent stream: calls of responses k_L and k_U | `contradicted`, `violation:bracket_infeasible`, localized, confidence `1 − fpr_hi[unit]` | subject: the call; conflict: k_L's prev input (`ts`) and k_U's first event (`ts`); witness: both first events (`request_id`) |
| inconsistent stream: any other call | `unconstrained`, `abstain:stream_inconsistent_elsewhere` | — |
| stream abstained by a correction | `abstain:correction_abstain` | — |
| stream with one decodable response | `abstain:single_response_stream` | — |
| id more than 1 day from its event | `abstain:id_time_implausible` (counted in `session.json`) | — |
| no id / undecodable id / no stamp | `missing:request_id` / `missing:request_id.decodable` / `missing:ts` | — |

`detail` = `{L_ms, U_ms, gap_ms, tol_ms, slack_ms, n_responses, k_L_request_id, k_U_request_id, corrections_applied}`.

**Thresholds and provenance.**
- `BRACKET_TOL_MS = 2000.0` [PRE `constants.BRACKET_TOL_MS`], pre-registered before Phase E.
- The 1-day plausibility filter and `_WIN` are in the frozen code (`prereg_e_common.bracket_responses`).
- The correction set is the one adopted on B [F1 `f1_effective_fp."swechat/claude_code".adopted_on_B`].
- Nothing is fitted (`kind="identity"`).
- **Variant pre-registered here for H, reported, not shipped (DA17).** "Ordered inputs": a result whose own call
  appears later in the file is not used as an input. On E, post hoc, honest goes from 11 to 8 streams
  [F1 `units."swechat/claude_code|E".posthoc_ordered_inputs.honest`]. `run_eval` reports v1.1.0-candidate beside v1.0.0
  on every split, and H decides nothing about it within this build.

**Calibration (`calib/id_bracket.json`, written by `calib/build.py`).**
- `fpr_hi` is the Wilson hi per stream on B:
  - swechat/claude_code 0.00393, adopted set [F1 `f1_effective_fp."swechat/claude_code".B.honest.wilson_per_stream.hi`];
  - cc_local 0.00666 [F1 `units."cc_local|B".honest.wilson_per_stream.hi`];
  - tbench2 0.0428 [TB `detail.R1.B.honest.wilson_per_stream.hi`];
  - pub_cc_hf 0.0787 [PCH `r1.splits.B.honest.wilson_per_stream.hi`].
- `recall_lo` is the Wilson lo of `time_response_early|30` on B: swechat/claude_code 0.941
  [N7T `cells."swechat/claude_code|B|R1_BRACKET|time_response_early|30".recall.lo`] and cc_local 0.859
  [N7T `cells."cc_local|B|R1_BRACKET|time_response_early|30".recall.lo`]. For tbench2 and pub_cc_hf, `build.py`
  copies it from [TB `detail.R1.B.n7_session_cells`] and [PCH `r1.n7_legs`].
- pub_trace_commons has no entry, so its confidence is None and the check still decides.

**H exposure.** `blind_on_H` is false on tbench2, pub_cc_hf and pub_trace_commons (`change_log` D6) and true on
swechat. cc_local has no H.

**Complexity.** One sort and one `merge_asof` per session, O(n log n). The correction loop is bounded by the
responses per inconsistent stream.

**Known false-positive sources (measured).** E has 11 honest failures, classified post hoc
[F1 `units."swechat/claude_code|E".posthoc_mechanisms.counts`]:
- client clock behind the server: 6. Accepted. The clock-step correction would remove them but costs power: 30 s
  power falls to 0.8909 on B [F1 `units."swechat/claude_code|B".corrections_single.per_category.clock_step.back_30s_power`];
- out-of-order result writes by Claude Code 2.1.x: 3. Targeted by the ordered-inputs variant;
- other: 2.

On B, restamped resume copies were 3 [F1 `units."swechat/claude_code|B".posthoc_mechanisms.counts.restamped_copy`].
The adopted dedupe removes 2 of them: honest goes from 10 to 8 streams
[F1 `units."swechat/claude_code|B".corrections_single.uncorrected.honest`,
`units."swechat/claude_code|B".corrections_single.per_category.restamped_copy.honest_flagged`]. Tolerance sensitivity on E: 17 streams
exceed 0 ms, 11 exceed 2 s and 7 exceed 5 s
[F1 `units."swechat/claude_code|E".honest.tolerance_sensitivity_streams_over`].

**Targets and expected labels** (N7, swechat/claude_code E; 500 tampered sessions against the same 500 untampered).
- **DETECTS:**
  - `time_response_early` at D = 10 s: 429/500; at D = 30 s: 488/500;
  - `time_result_late` at D = 5 s: 272/500;
  - `time_tail_late` and `time_tail_early` from D = 5 s;
  - `id_swap_adjacent` 486/500;
  - `id_splice_foreign` nearest 395/500.
- **PARTIAL:**
  - `time_response_early` at D = 5 s: 163/500;
  - `insert_pair_consistent` 187/500;
  - `insert_pair_squeezed` 91/500;
  - `rewrite_consistent_k` 151/500 (k = 2) and 241/500 (k = 5), `edit_artifact` under DA13;
  - `id_splice_foreign` random 17/500.
- **BLIND:** `time_response_early` at D ≤ 2 s, every `time_response_late`, every `time_result_early`, `delete_pair`
  and `delete_response`.
- Each count is `cells."swechat/claude_code|E|R1_BRACKET|<attack>|<param>".recall` in [N7T].
- The random-splice blind spot comes from the 1-day filter. It drops an implausible id silently, so the session
  abstains instead of being flagged (F1 note §4c). `abstain:id_time_implausible` makes those abstentions visible, and
  R1b (§7.1.6) is the follow-up.

**Success criteria (§5.7, filled).**

```
check: id_bracket v1.0.0   kind identity   rule type 1   units claimed: swechat/claude_code (ALIVE), cc_local (WEAK, B only),
       tbench2 (WEAK), pub_cc_hf (WEAK)   blind_on_H: swechat yes; tbench2/pub_cc_hf/pub_trace_commons no (D6); cc_local no H
PARITY full swechat/claude_code E cache, corrections as adopted: 11 inconsistent of 3,325 streams
       [F1 f1_effective_fp."swechat/claude_code".E.honest]; corrections=(): 11 of 3,332 [F1 units."swechat/claude_code|E".honest];
       cc_local B, corrections=(): 1 of 847 [F1 units."cc_local|B".honest]; tbench2 B∪E: 0 of 168 [TB detail.R1.BuE.honest]
PARITY full-mode N7 cell (corrections=()): time_response_early|30 on swechat/claude_code E = 488/500 tampered, 3/500 honest
       [N7T cells."swechat/claude_code|E|R1_BRACKET|time_response_early|30"]  (also proves the attack port, §5.3)
MUST   session-level honest flag rate, swechat/claude_code, full-mode E draw: Wilson hi <= 0.02 (Track A 5/687, hi 0.0169)
MUST   time_response_early D=30 on swechat/claude_code E: DETECTS
SHOULD localization >= 0.95 on DETECTS cells (Track A: 486 of 486 flagged id_swap copies localized
       [N7T cells."swechat/claude_code|E|R1_BRACKET|id_swap_adjacent|-".localization])
REPORT time_response_late, time_result_early, delete_pair, delete_response, every shift <= 2 s: walk through
```

**`explain()`.**
- Contradicted: "Response #{k_U} is stamped {gap_s:.1f} s earlier than its request id allows, given response #{k_L}
  of the same stream (tolerance {tol_s:.0f} s). The provider clock is inferred from an undocumented request-id
  layout."
- Supported: "All {n} responses of this stream fit one constant client–server clock offset within {tol_s:.0f} s
  (slack {slack_ms} ms)."
- Rendered example, from the demo spec: the primary demo page (§6.3).

#### 7.1.2 `inline_output_accounting` (module `verifier/checks/inline_output_accounting.py`, class `InlineOutputAccountingCheck`) — MUST

**Justifying findings.**
- **N6 cells** [N2 `units.<unit>.cell_final`; aiv_cu per stratum]:
  - WEAK: swechat/claude_code, codex and opencode; cc_local (B only); aiv_cu opus, fable and haiku.
  - ALIVE: aiv_cu anthropic-sonnet, gemini-pro and gemini-flash.
  - DEAD (not granular): swechat/gemini, cursor, copilot and simple_text; aiv_cc; whowhen.
- **New corpora.**
  - agentcap/opencode ALIVE [AC `cells.N2."agentcap/opencode"`].
  - agentcap/pi WEAK, AC4 cap [AC `cells.N2."agentcap/pi"`].
  - pub_codex WEAK [PCX `cells.N2.pub_codex`].
  - tbench2 WEAK [TB `cells.N2`]; glm_tb21 WEAK [GLM `cells.N2`]; pub_cc_hf WEAK [PCH `cells.N2`].
- **Kill attempts.** No artifact check lowered any N2 cell
  [N2 `units."swechat/claude_code".groups."swechat/claude_code".artifact_checks`].
- **N7.** `inline_fabrication` is PARTIAL in swechat/claude_code E: 224/500 = 0.448 [0.405, 0.492] against 83/500 =
  0.166 [0.136, 0.201]. ADR 0.282; localization 171/224
  [N7C `cells."swechat/claude_code|E|N2|inline_fabrication|tau"`]. It reaches DETECTS only at high honest rates:
  - swechat/opencode E 136/190 against 67/190;
  - swechat/codex E 45/52 against 30/52;
  - cc_local B 120/174 against 18/174.

  Each is [N7C `cells."<unit>|<split>|N2|inline_fabrication|tau"`].
- **Track B.** B3.4 is PARTIAL. ReAct's stop sequence and crewAI PR #4077 *prevent* inline fabrication at parse
  time. No opened source uses the output-vs-visible identity after the fact on recorded logs. That difference is the
  claim.

**Protocol attributes.**
`kind="statistical"`, `strength="strong"`, `requires=frozenset({"usage.out", "join.call_id", "result.text"})`,
`reads={"usage", "text", "args"}`, `targets={"inline_fabrication"}`, `unit_kind="response"`,
`calibration="verifier/checks/calib/inline_output_accounting.json"`. Lineage: `N2`.

**Rule type (DA11): 2.** This is an accounting bound on a provider-billed counter.

**Soundness.**
- `usage_out` is written by the provider. If the model's decoder produced a recorded result (a leaky parser, or a
  model writing its own `Observation:`), those characters are billed as output. Then
  `U_k = usage_out_k − τ·chars_out_k ≈ τ·chars(result) ≥ 0.5·τ·chars(result)`, whatever visible padding the model adds.
- A fake result returned **through the harness** is billed as input and passes by construction
  (`prereg_e.json` `n2_token_accounting.limit`).
- In structured tool-call harnesses (Claude Code, Codex, OpenCode, Pi), the harness writes `tool_result` itself. There
  the leaky-parser path is closed by construction (`PRIOR_ART.md` §3.4 interpretation). A positive in those formats is
  either an edit that moved model text into a result, or honest hidden output: a false positive (open item 11).

**Inputs.**
- `Session.events`: `api_msg_id`, `kind`, `usage_out`, `usage_in`, assistant `text`, call `args`,
  `extra.thinking_chars`, `call_id`.
- Codex `token_count` meta rows, which close a response in that format.
- `Session.pairs.text`: chars of each call's result.

**Algorithm.** It ports `prereg_e_common.response_table` and `n2_flags` unchanged. That includes the Claude Code
double count of thinking characters (N2 deviation 6), because τ was computed with it.

```python
def response_table(ev: pd.DataFrame, fmt: Literal["codex", "default"]) -> pd.DataFrame
    """One row per response with >= 1 call: resp, usage_out (max over its rows; Codex: the closing token_count row),
    chars_out = assistant text + call args + extra.thinking_chars, last_call_key, n_calls."""
def result_chars(pairs: pd.DataFrame) -> dict[str, int]                 # call_key -> len(result text)
def n2_decide(row, rc: int | None, tau: float) -> Literal["flag", "below", "short", "no_result", "no_usage"]
    """rc None -> no_result; usage_out NaN -> no_usage; rc < 800 -> short;
       U = usage_out - tau * chars_out; flag iff U >= 0.5 * tau * rc."""
```

| Situation | Per-call verdict | Evidence |
|---|---|---|
| last call of a response, flagged | `contradicted`, `violation:output_exceeds_visible`, localized, confidence `1 − fpr_hi[unit]` | subject: the last call; conflict: its result (`text`, value `"{rc} chars"`); witness: the response's usage row (`usage_out`, value `"usage_out={uo}; tau*chars_out={x:.0f}"`) |
| last call, not flagged | `abstain:below_threshold` (screened; never `supported`, §4.6) | — |
| last call, result < 800 chars / no result / no usage | `abstain:result_below_800_chars` / `missing:result` / `missing:usage_out` | — |
| any other call of the response | `abstain:not_last_call` | — |
| call in no response (no `api_msg_id`, not Codex) | `missing:api_msg_id` | — |
| unit uncalibrated / not enabled (DA16) | `abstain:uncalibrated_unit` / `abstain:unit_not_enabled` | — |

**Thresholds and provenance.** Every τ was fixed on split A, before any B or E read.

| Unit | τ | Source |
|---|---|---|
| swechat/claude_code | 0.4088 | [PRE `resolved.n2."swechat/claude_code".tau`] |
| swechat/codex | 0.4923 | [PRE `resolved.n2."swechat/codex".tau`] |
| swechat/opencode | 0.3676 | [PRE `resolved.n2."swechat/opencode".tau`] |
| cc_local | 0.7718 | [PRE `resolved.n2.cc_local.tau`] |
| aiv_cu strata | sonnet 0.6727, gemini-pro 0.2714, gemini-flash 0.2977, haiku 0.8655, opus 0.7781, fable 0.7088 | [PRE `resolved.n2.aiv_cu.by_stratum.<stratum>.tau`] |
| tbench2 | 0.3444 | [CAL-tbench2 `units.tbench2.n2.tau`] |
| pub_cc_hf | 0.6676 | [CAL-pub_cc_hf `calibration.n2.tau`] |
| agentcap/opencode | 0.2604 | [CAL-agentcap `units."agentcap/opencode".resolved.n2.tau`] |
| agentcap/pi | 0.2601 | [CAL-agentcap `units."agentcap/pi".unit_result.n2.tau`] |
| pub_codex | 0.3623 | [CAL-pub_codex `units.pub_codex.resolved.n2.tau`] |
| glm_tb21 | 0.2895 | [CAL-glm_tb21 `units.glm_tb21.n2.tau`] |

The 800-character and 0.5 constants are [PRE `n2_token_accounting.detector`].

**Enable rule per unit (DA16).** The rule is the pre-registered ALIVE false-positive leg
[PRE `n2_token_accounting.verdict.ALIVE`]: a per-response honest flag rate ≤ 0.05 with CI hi ≤ 0.10, on E (B where no
E exists). Rates below come from `results.E.honest_flag_rate` in [N2] unless another source is named.

| Enabled | Not enabled |
|---|---|
| swechat/claude_code 779/46,138 = 0.0169 [0.0133, 0.0209] | swechat/codex 106/2,011 = 0.0527 |
| aiv_cu/anthropic-sonnet 21/781 = 0.0269 [0.0154, 0.0381] | swechat/opencode 99/1,667 = 0.0594 |
| aiv_cu/gemini-pro 1/494 = 0.0020 [0, 0.0066] | cc_local (B) 1,095/14,451 = 0.0758, hi 0.1026 |
| aiv_cu/gemini-flash 0/430 [0, 0] as the file reports it (Wilson hi 0.0089 *(arithmetic)*) | aiv_cu/anthropic-opus 79/1,147 = 0.0689 |
| aiv_cu/anthropic-haiku 2/271 = 0.0074 [0, 0.0187] | aiv_cu/anthropic-fable 12/137 = 0.0876 |
| agentcap/opencode 0/417 [0, 0.0091] [AC `cells.N2."agentcap/opencode"`] | tbench2 2,078/13,018 = 0.160 [TB `detail.N2.E.honest_flag_rate`] |
| agentcap/pi 2/722 = 0.0028 [0, 0.0089] [AC `cells.N2."agentcap/pi"`] | glm_tb21 21/224 = 0.094, hi 0.248 [GLM `cells.N2`] |
| pub_codex 5/134 = 0.037 [0, 0.0645] [PCX `cells.N2.pub_codex`] | pub_cc_hf 45/361 = 0.125 [PCH `cells.N2`]; pub_trace_commons INSUFFICIENT_N |

**Read this plainly.** The rule excludes exactly the units where N7 shows DETECTS (opencode, codex, cc_local), because
their honest rates are high. It enables swechat/claude_code, where N7 is only PARTIAL. N2 enters the build as the only
measured instrument for the in-scope class. It does not enter as a strong detector.

**Calibration (`calib/inline_output_accounting.json`).** Per unit (aiv_cu per stratum): `tau`, `enabled`, `fpr_hi`
(the B per-response CI hi; swechat/claude_code 0.0192
[N2 `units."swechat/claude_code".groups."swechat/claude_code".results.B.honest_flag_rate.hi`]), and
`session_cost` (E session-level share, printed by `explain()`; swechat/claude_code 237/1,492 = 0.159 [0.141, 0.178]
[N2 `units."swechat/claude_code".groups."swechat/claude_code".results.E.session_level_honest_flag_share`]).

**H exposure.** N2 is in no E_SEEN or D6 lineage, so `blind_on_H` is true everywhere.

**Complexity.** One groupby on `api_msg_id`: O(n log n).

**Known false-positive sources (measured, swechat/claude_code).**
- **Output the transcript does not show** (thinking, hidden tokens). The model stratum claude-opus-4-7 flags at
  134/638 [N2 `units."swechat/claude_code".groups."swechat/claude_code".stratification.model.strata."claude-opus-4-7"`].
- **Which tools trip it.** The E flags by last-call tool are read 365, shell 260 and grep 108 of 779
  [N2 `…results.E.flagged_by_last_call_key`].
- **Session-level cost.** 0.159 on E (above). It grows with session length.

None of these is corrected. They are printed beside each verdict.

**Targets and expected labels.** `inline_fabrication`: PARTIAL in swechat/claude_code (above). The enabled units have no
other N7 cell. The aiv_cu N7 cell pools enabled and non-enabled strata, so it is not a claim for any one stratum:
PARTIAL, 115/500 against 38/500 [N7C `cells."aiv_cu|E|N2|inline_fabrication|tau"`]. N2 is BLIND by construction to
every attack that does not touch `usage_out`.

**Success criteria (§5.7, filled).**

```
check: inline_output_accounting v1.0.0   kind statistical   rule type 2   units claimed: the 8 enabled units above
       blind_on_H: yes (all)
PARITY swechat/claude_code full E: 779 flagged of 46,138 eligible responses, 1,492 sessions
       [N2 units."swechat/claude_code".groups."swechat/claude_code".results.E.honest_flag_rate]; positive control at
       tau' = 0.8 tau: 41,112 of 46,138 [... .results.E."recall_tau_prime_0.8"]; B: 793 of 49,998 [... .results.B.honest_flag_rate]
MUST   inline_fabrication on swechat/claude_code, full-mode E: at least PARTIAL (Track A: recall CI lo 0.405 > FPR CI hi 0.201)
MUST   session-level honest flag rate on that draw: Wilson hi <= 0.21 (Track A 83/500, hi 0.201) — a regression bound
SHOULD localization >= 0.70 on that cell (Track A 171/224 = 0.763)
REPORT no enabled unit has a DETECTS cell; DETECTS exists only where the unit is not enabled (opencode, codex, cc_local)
```

**`explain()`.** "This response billed {uo} output tokens; its visible text and arguments account for about
{tau_chars:.0f}. The unexplained {U:.0f} tokens are at least half the size of the {rc}-character result of call
#{seq}, so that result may have been written by the model instead of returned by the tool. Honest responses in this
unit trip this rule {rate:.1%} of the time ({k}/{n}); {session_cost:.0%} of honest sessions have at least one."

#### 7.1.3 `ledger_tally` (module `verifier/checks/ledger_tally.py`, class `LedgerTallyCheck`) — SHOULD

**Justifying findings.**
- **Track A.** R5 swechat/claude_code SURVIVES at ALIVE, with E not blind [R45 `R5.units."swechat/claude_code".survival`].
  - Honest: E 10/1,520 = 0.0066 [0.0036, 0.0121]; B 13/1,645 = 0.0079 [0.0046, 0.0135]
    [R45 `R5.units."swechat/claude_code".verdict_blocks.E`, `.B`].
  - N7 E: `delete_response` DETECTS 396/500 against 4/500, ADR 0.784
    [N7C `cells."swechat/claude_code|E|R5_LEDGER|delete_response|-"`]; `delete_pair` PARTIAL 219/500; both
    `insert_pair_*` BLIND (4/500, equal to honest) [N7C `cells."swechat/claude_code|E|R5_LEDGER|<attack>|<param>"`].
  - `inline_fabrication` reaches 374/500 [N7C `cells."swechat/claude_code|E|R5_LEDGER|inline_fabrication|tau"`], but
    it is an `edit_artifact` (DA13).
  - Kill attempts: AC1 re-read all 23 flagged sessions with 0 changes; AC3 8/3,111 ALIVE; AC4 PASS
    [R45 `R5.units."swechat/claude_code".artifact_checks`].
- **Other swechat formats.** Honest leg only; N7 NOT_RUN [R45 `R5.units."swechat/codex".survival`, `."swechat/opencode".survival`].
  Not enabled there.
- **Track B.** PARTIAL through B3.1/B3.2. Billing audits (Velasco et al.) recount output against a reported count, and
  trust the content. Our difference is auditing the log's own usage records against the capture tool's tally, after
  the fact. The tally-vs-recount leg itself was not separately searched by Track B, and FINDINGS §4.3 calls rank 5
  "mostly listed prior art" (open item 14). Claim only the measured agreement and the tamper response.

**Protocol attributes.**
`kind="identity"`, `strength="strong"` (support is lowered to `format`, DA18),
`requires=frozenset({"sidecar.entire_tally", "api_msg_id", "usage.io"})`, `reads={"usage", "events"}`,
`targets={"delete_response", "delete_pair", "inline_fabrication"}`, `unit_kind="session"`. Lineage: `R5_LEDGER`.

**Rule type (DA11): 1.** The log's usage records are compared with the capture tool's tally.

**Soundness.**
- The tally is computed from provider usage. Any real fabrication is billed and so sits inside it: no execution-class
  power.
- A naive deletion of a response, or an edit of usage, breaks the match.
- An editor who holds the transcript can recompute the tally. That is a coherent forgery: out of scope.

**Algorithm.**

```python
def recount(ev: pd.DataFrame) -> np.ndarray
    """(n, 4) int64 (usage_in, usage_cache_create, usage_cache_read, usage_out) per response in first-appearance order
    of api_msg_id, taking each response's LAST IR row in seq order (the 'last record per message id' of R5_specific)."""
def match_tally(seq: np.ndarray, tally: dict) -> dict
    """Exact port of phase_c_swechat_tables._match (4-field branch): cls in {full, prefix, window, none} plus start."""
```

- tally None → `missing:sidecar.entire_tally`.
- `tally["api"] == 0` → `abstain:empty_tally`.
- `cls == "none"` → every call `contradicted`, `violation:tally_mismatch`, `localized=False`, `unit_kind="session"`.
  Evidence: the call as subject; the session's last usage row as witness (`usage_out`, value
  `"recount={tx}; tally={tally}"`).
- full / prefix / window → every call `supported`, `ok:tally_<cls>`, `strength="format"`.
- Parity fallback. If the IR-row recount misses parity, `loaders.sidecar` adds the raw records the IR does not keep
  (`cc_usage_unparsed`), exactly as N7's recount did. *(estimate: +0.5 h)*

**Thresholds.** None. The tolerance is 0 [PRE `a1.proposal_rules.R5_specific`].

**Calibration.**
- `fpr_hi` = 0.0135: B session Wilson hi [R45 `R5.units."swechat/claude_code".verdict_blocks.B`].
- `recall_lo` = 0.719: B `delete_response` [N7C `cells."swechat/claude_code|B|R5_LEDGER|delete_response|-".recall`, element 1].

**H exposure.** R5 lineage, so `blind_on_H` is false (`PREREG_E.md` §0).

**Complexity.** O(n) recount, plus an O(n) window scan.

**Known false-positive sources (measured).**
- The sessions table and session_logs disagree on the tally in 18 sessions, and 14 of those are flagged
  [R45 `R5.units."swechat/claude_code".descriptive.BuE.flag_among_tab_ne_raw`]. Under a join-fix tally the honest rate
  is 9/3,165 [R45 `R5.units."swechat/claude_code".join_fix_variant.BuE`]. That variant is reported, not adopted.
- Flags concentrate in long sessions and in CLI 0.5.x [R45 `R5.units."swechat/claude_code".descriptive`].

**Coverage and contribution.**
- It runs only on swechat Claude Code. Only that dataset carries an Entire tally; the CLI on other inputs emits
  `missing:sidecar.entire_tally`.
- It is session-level and never localized, so it adds **0** to the ADR headline (`flag_loc`). It contributes to
  `recall`, to `cell_label`s and to the session-level report. That is why it is SHOULD and not MUST.

**Success criteria (§5.7, filled).**

```
check: ledger_tally v1.0.0   kind identity   rule type 1   units claimed: swechat/claude_code   blind_on_H: no
PARITY full E: 10 flagged of 1,520 decided [R45 R5.units."swechat/claude_code".verdict_blocks.E]; gate counts equal
       [R45 R5.gate_counts]
MUST   delete_response on E: DETECTS (Track A 396/500 vs 4/500)
MUST   session-level honest rate on the full-mode E draw: Wilson hi <= 0.021 (Track A 4/500, hi 0.0204)
SHOULD localization: not applicable (session-level); reported as such
```

**`explain()`.** "The capture tool's tally for this session ({api} API calls, {out} output tokens) matches no
prefix or window of the {n} responses recorded here. A response was removed, or its usage edited, after capture.
This is a session-level finding; it does not say which call."

#### 7.1.4 `dual_render_recount` (module `verifier/checks/dual_render_recount.py`, class `DualRenderRecountCheck`) — SHOULD

**Justifying findings.**
- **Track A.** R4 swechat/claude_code SURVIVES at WEAK, with E not blind [R45 `R4.units."swechat/claude_code".survival`].
  - Honest: 0/1,444 E sessions (hi 0.0027) and 0/2,998 on B ∪ E (hi 0.0013) [R45 `R4.units."swechat/claude_code".verdict_blocks`].
  - 287/58,209 mismatches, all excused by the frozen whitelist [R45 `R4.units."swechat/claude_code".whitelist_coverage_ir_BuE`].
  - N7 E best cells are PARTIAL with 0/500 honest [N7C `cells."swechat/claude_code|E|R4_DUAL|<attack>|<param>"`]:
    `rewrite_consistent_k` 205/500 (k = 5) and 154/500 (k = 2); `reorder_adjacent_pairs` 147/500, localization
    147/147; `sub_matched_bytes` 76/500 (any) and 26/500 (samecmd).
  - BLIND at 0/500: `sub_single_flip_error`, `sub_single_digit`, `reorder_lines`, `delete_*`, `insert_pair_*`
    [R45 `R4.units."swechat/claude_code".n7_meta.E.cells_detail`].
- **Transfer.**
  - cc_local WEAK: 0/110 B [R45 `R4.units.cc_local.verdict_blocks.B`].
  - tbench2 WEAK: 0/117 sessions on two non-Anthropic-model Claude Code strata
    [TB `cells.R4_dual`, `detail.R4.E.honest.session_rate`].
  - pub_cc_hf INSUFFICIENT_N: 0 of 27 decided sessions [PCH `cells.R4_dual`].
- **Track B.** B3.5 is PARTIAL (GhostBuster cross-view diff; NTFS $SI/$FN). Claim the measured agreement rate and the
  tamper response, never a new technique.

**Protocol attributes.**
`kind="identity"`, `strength="format"` (DA18), `requires=frozenset({"sidecar.cc_numlines", "result.text", "join.call_id"})`,
`reads={"text"}`, `targets={"reorder_adjacent_pairs", "rewrite_consistent_k", "sub_matched_bytes"}`, `unit_kind="call"`.
Lineage: `R4_DUAL`.

**Rule type (DA11): 1, record editing only.** Under execution-path compromise both renderings come from the same fake
output. Execution-class credit is none (DA13).

**Algorithm.** It ports `phase_e_n7_content.det_R4` and `prereg_e_common.dual_whitelisted`. The regexes are frozen
copies in `checks/_whitelist.py`, and `test_whitelist_parity.py` asserts they equal [PRE `regexes`].

```python
def visible_lines(text: str) -> int      # count of lines matching regexes.read_numbered_line
def whitelist_class(text: str, corpus: str) -> str | None   # dual_persisted | dual_shorter_than_offset | dual_identical_ref
                                                            # | dual_redaction | dual_negative_line | (cc_local) dual_empty_file
```

For each Read result with a sidecar `numLines` (results de-duplicated on `call_id`, as N7 did):
- `L == numLines` → `supported`, `ok:recount_match`.
- Mismatch inside the whitelist → `abstain:whitelisted_<class>`.
- Mismatch outside it → `contradicted`, `violation:numlines_mismatch`, localized. Evidence: subject call; conflict:
  result (`text`, value `"visible={L}"`); witness: same result (`sidecar.cc_numlines`, value `"numLines={n}"`).
- Non-Read calls → `abstain:tool_out_of_scope`.
- Read without a counter → `missing:sidecar.cc_numlines`.

**Thresholds.** None. The whitelist is frozen, and adding a class after seeing B or E cannot raise the verdict
[PRE `a1.proposal_rules.R4_specific`].

**Calibration.**
- `fpr_hi` = 0.0025: B 0/1,554 [R45 `R4.units."swechat/claude_code".verdict_blocks.B`].
- `recall_lo` = 0.241: B `reorder_adjacent_pairs` 139/500
  [N7C `cells."swechat/claude_code|B|R4_DUAL|reorder_adjacent_pairs|-".recall`, element 1].
- The low `recall_lo` is deliberate. A `supported` from this check is weak evidence, and its confidence says so.

**H exposure.** R4 lineage, so `blind_on_H` is false.

**Complexity.** O(n), one regex pass per Read result.

**Known false-positive sources and evasion (measured).**
- 2,011 of 58,209 Read results match some whitelist class, 1,506 of them redactions
  [R45 `R4.units."swechat/claude_code".whitelist_coverage_ir_BuE.all_units_matching_a_whitelist_class`]. Any mismatch
  there is excused, so an editor who adds a whitelist marker evades the check. Stated.
- Coverage is Read results only.

**Success criteria (§5.7, filled).**

```
check: dual_render_recount v1.0.0   kind identity   rule type 1 (record editing)   units: swechat/claude_code, cc_local (B), tbench2
PARITY full E: 0 flagged of 1,444 sessions, 28,198 counters joined [R45 R4.units."swechat/claude_code".raw_join_coverage];
       B∪E mismatch classes 203/75/5/3/1 (persisted/shorter/identical/redaction/negative) [R45 ...whitelist_coverage_ir_BuE.by_class]
MUST   honest flagged sessions on full E: Wilson hi <= 0.005 (Track A 0/1,444, hi 0.0027)
MUST   reorder_adjacent_pairs on E: at least PARTIAL (Track A 147/500 vs 0/500)
SHOULD localization >= 0.95 (Track A 147/147)
```

**`explain()`.** "The harness recorded numLines={n} for this Read, but the visible result shows {L} numbered lines.
One process writes both, so this catches an edit made after the log was written, not a tool that lied."

#### 7.1.5 `latency_floor` (module `verifier/checks/latency_floor.py`) — COULD

**Findings.**
- **Track A.**
  - P1 is WEAK everywhere after the second pass [P13 `verdicts."P1/swechat/opencode"`, `."P1/cc_local"`,
    `."P1/swechat/claude_code"`].
  - The claude_code floor is UNSTABLE, and F2 could not explain the shifts: BENIGN 0/31, COMPROMISE_LIKE 3/31,
    UNEXPLAINED 28/31, outcome OPEN [F2 `populations.BuE.classes`, `.outcome`].
- **N7.**
  - cc_local B: DETECTS `time_result_early` from D = 1 s (D = 30 s: 95/173 against 0/173)
    [N7T `cells."cc_local|B|P1_FLOOR|time_result_early|30"`]. Honest 0/186 sessions
    [N7T `verdicts.per_unit_split_detector."cc_local|B|P1_FLOOR".honest_union_of_selected_sessions`].
  - swechat/opencode E: DETECTS `time_tail_early` at an honest rate of 12/190 (hi 0.107)
    [N7T `verdicts.per_unit_split_detector."swechat/opencode|E|P1_FLOOR"`].
  - swechat/claude_code E: honest 154/687 = 0.224 [N7T `verdicts.per_unit_split_detector."swechat/claude_code|E|P1_FLOOR"`].
- **Track B.** B1(a) is PARTIAL: crewAI PR #3388's fixed 10 ms floor (live, instrumented, unmerged), MLPerf TEST04,
  BOINC CreditNew. Do not claim "first to use timing".

**Design (if built).**
- Statistical, rule type 2, per-call.
- `delta_ms = t_result − t_call` on Phase B qualified pairs. The qualification is ported from
  `prereg_calibration.p1_qualified`, the largest part of the 1.5 h estimate.
- `violation:faster_than_floor` iff `delta ≤ 0` or `delta < floor[unit][tool_key]`.
- Floors come from [N7T `thresholds_used.floors_s`] (source [PRE `resolved.n7`]); cc_local: glob 0.016 s, read 0.0025 s.
- Enabled by DA16, adapted to the session-level N7 honest leg (Wilson hi ≤ 0.10). Only cc_local passes, and cc_local
  is private, has no E and has no H.
- So it can make no public claim. That, and F2's open floor shifts, is why it is COULD and first on the cut list.

#### 7.1.6 Mechanisms not built, and why

| Mechanism | Track A (number, source) | Track B | Why no check | Where it still appears |
|---|---|---|---|---|
| N1 conditional duration | ALIVE as a population statistic in swechat/claude_code: ρ_hon E [0.016, 0.046], ρ_pc CI lo 0.425 [N1 `units."swechat/claude_code".results.E.shell.verdict`]. The per-call detector catches 219/3,842 = 0.057 of synthetic tampered shell calls [N1 `units."swechat/claude_code".results.BE.shell.positive_control.detector_flag_on_tampered_diagnostic`]. N7 best is PARTIAL, 43/500 [N7T `cells."swechat/claude_code\|B\|N1\|time_result_early\|60"`] | PARTIAL B1(a)/(b) | No per-call rule with power; a population correlation is not a contradiction (DA11) | transfer grid row, copied from Track A |
| P3 zero-error tail | ALIVE: E 8/380 [P13 `verdicts."P3zero/swechat/claude_code"`]. Its only N7 power is `sub_single_flip_error` 8/500 vs 0/500 (PARTIAL) [N7C `cells."swechat/claude_code\|E\|P3_ZERO\|sub_single_flip_error\|-"`] | no verdict (not assessed); evadable by error fabrication (`PRIOR_ART.md` §3.10) | Distributional (DA11); not cleared by Track B (§7.0) | cut, census statistic included; follow-up: a Track B search |
| P2 knowledge precedence | WEAK: S_deep E 608/4,466 = 0.136 [P24 `verdicts."P2/swechat/claude_code/main"`] | no verdict (not assessed) | Honest base rate of 8–14% per reference: S_deep E 0.077 on subagent threads [P24 `verdicts."P2/swechat/claude_code/subagent".deciding.E_or_B.value`] to 0.136 on the main thread | cut |
| P4 round numbers | DOWNGRADED to WEAK; pooled KILLED [P24 `verdicts."P4round/swechat/claude_code"`, `."P4round/swechat/* (pooled)"`] | not assessed | Distributional, and lives in call args | cut |
| N3 reaction time | DEAD in swechat/claude_code: pooled ρ E −0.039 [−0.054, −0.024] [N3 `units."swechat/claude_code".results.E.rho_pooled`] | PARTIAL (B3.7; Track B predicted a null) | Dead | cut |
| N4 concurrency | WEAK, but no per-session rule (every N7 cell NA) [N45 `n6_cells."swechat/claude_code"`] | PARTIAL (B3.8) | No decision rule | cut |
| N5 a, b, d, e, f, c, g | No N5 item cell ALIVE in any unit [N5 `n6_cells`; N45 `n6_cells`]. Determinism drift E 491/1,745 = 0.281 [N5 `units."swechat/claude_code".results.a.E.rate`] | a: PARTIAL near-TAKEN; b, c, d, e, g: UNVERIFIED (§3.13) | Dead or uncleared | cut |
| R2 image ledger | KILLED: 44/807 = 0.0545 > 0.05 [R23 `R2.verdict_blocks.BuE`] | UNVERIFIED | Killed | cut |
| R3 git window | WEAK: 2/976 [R23 `R3.units."swechat/claude_code".verdict_blocks.BuE`] | UNVERIFIED (does not clear, §7.0) | External witness (commit table), outside the witness-free core (§1.4) | cut; follow-up: a Track B search, then a `witness` plugin family |
| Two-clock (`created`) | EXPLORATORY, NOT_BLIND: 0/295 streams [AC `exploratory_two_clock.by_population.BuE.stream_inconsistent`] | design consequence 3 (prefer documented clocks) | Not pre-registered, so it has no Track A label | cut from this build; follow-up: pre-register, then measure as a second clock source for `id_bracket` |
| R1b implausible-id flag | Not measured. At most 143 of 305,727 swechat ids fall outside [−2 s, +600 s] of their event [B4 `REQUEST_ID_COLUMN_FIRST.per_corpus."swechat/claude_code".decodable_time.agrees_with_carrying_event_minus2s_plus600s`] | (with R1) | No measured honest rate at the 1-day bar, so no finding | cut from this build; follow-up: measure on E, then decide |

### 7.2 MUST / SHOULD / COULD

Each row names its justification. A check row cites its finding. An agnostic row cites the contract or eval rule that
requires it.

| Tier | Item | Justification |
|---|---|---|
| MUST | `verifier.ir` re-export + `turns` adapter + `test_ir_parity` | `SCOPE.md` §3: `verify_session(turns)` contract |
| MUST | `session/` (build_session, pairs, responses, clocks, capabilities, idclock + DA20 gate + parity, sidecar schema) | every check depends on it |
| MUST | `checks/base.py`, `registry.py`, `compose.py`, `ref_result_present` | `PHASE_E_PROMPT.md` C2: registry + one trivial reference check end to end |
| MUST | `loaders/` (detect, files for claude_code/codex/opencode/gemini/atif/ir/turns; corpora adapters A/B/E) + `loaders/sidecar.py` | C2: loader normalizing every public corpus; DA14 (three of the four kept checks read a sidecar or need its index) |
| MUST | CLI `verify` / `checks` / `inspect`, text + JSONL output, exit codes | `SCOPE.md` §2 deliverable 2 |
| MUST | `eval/run_eval.py` quick on E + `--mode full`; `heldout.py` manifest verify + pack + attack plan + sidecar table; `attacks.py` port with parity test; `metrics.py` with `flag_loc_credited` (DA13); `_stats.py` + parity; import isolation; `core.py` wiring; single-JSON output; ≥ 3 seeds; ≤ ~2 min | C2 contract; `eval/core.py` docstring |
| MUST | root `requirements.txt` | CLAUDE.md rule 6 |
| MUST | **`id_bracket`** + calib + parity test | ALIVE swechat/claude_code [resolved here]: honest 11/3,325 on E [F1 `f1_effective_fp."swechat/claude_code".E.honest`]; DETECTS `time_response_early\|30` 488/500 vs 3/500 [N7T `cells."swechat/claude_code\|E\|R1_BRACKET\|time_response_early\|30"`]; transfer 0/168 (tbench2) and 0/82 (pub_cc_hf) honest streams |
| MUST | **`inline_output_accounting`** + calib + parity test (ships disabled if parity fails) | the only surviving mechanism whose in-scope power is not an edit artifact (§1.5): PARTIAL 224/500 vs 83/500 [N7C `cells."swechat/claude_code\|E\|N2\|inline_fabrication\|tau"`]; per-response honest 0.0169 on E [N2 `units."swechat/claude_code".groups."swechat/claude_code".results.E.honest_flag_rate`] |
| MUST | per-threat-class reporting (DA13) and the "synthetic only" footer | §1.4–1.5: every positive is synthetic; R1/R4/R5 carry no execution-class power |
| SHOULD | **`ledger_tally`** + `entire_tally` sidecar + parity | ALIVE: `delete_response` 396/500 vs 4/500 [N7C `cells."swechat/claude_code\|E\|R5_LEDGER\|delete_response\|-"`]; honest 10/1,520 [R45 `R5.units."swechat/claude_code".verdict_blocks.E`]. Session-level, so 0 ADR contribution |
| SHOULD | **`dual_render_recount`** + `cc_numlines` sidecar + parity | WEAK; honest 0/2,998 [R45 `R4.units."swechat/claude_code".verdict_blocks.BuE`]; `reorder_adjacent_pairs` 147/500 vs 0/500 [N7C `cells."swechat/claude_code\|E\|R4_DUAL\|reorder_adjacent_pairs\|-"`] |
| SHOULD | `render/html.py` + `demo.py` + primary `demo_spec.json` | `SCOPE.md` §9 Demo 1 "must have"; C1 demo surface; strongest cell above |
| SHOULD | second demo page (`demo_spec_exec.json`) | the in-scope class shown with its cost (§6.3) |
| SHOULD | `render/figures.py` (transfer matrix, recall per attack) | C2: figure generation for both |
| SHOULD | H build + `--final` run + access log | the held-out headline |
| SHOULD | `eval/labeled.py` validate/register/join | scope boundary: accept a labeled corpus later |
| SHOULD | per-check verdict cache in eval | keeps the climb loop near 100 iterations a night (`eval/core.py` docstring) |
| SHOULD | `census` subcommand (A/B/E) + `heldout.py census` (full corpus, after `--final`) | `SCOPE.md` §5.7 |
| COULD | `latency_floor` | WEAK; only cc_local qualifies (0/186 honest, DETECTS 95/173 [N7T `cells."cc_local\|B\|P1_FLOOR\|time_result_early\|30"`]); private, no H |
| COULD | loaders for openhands, miniswe, combo2, tracelab, osworld, webarena, cli-pi-hf | `CORPUS_INVENTORY.md` §0 (acquired corpora with a planned loader, [CI `loaders.new_loaders`]); combo2 brings harness-labelled substitutes (§1.4) |
| CUT | N1, N3, N4, N5a–g, P2, P4, R2 as checks | §7.1.6 |
| CUT | P3 zero-error tail, census statistic included | survived Track A, but has no Track B verdict (§7.0) |
| CUT | `witness` plugin family (R3 git window) | prior art UNVERIFIED, so it does not clear (§7.0) |
| CUT | R1b implausible-id flag; two-clock source for `id_bracket` | no measured or pre-registered finding yet (§7.1.6); follow-ups |
| CUT | directory input; demo gallery | no finding justifies them (C1: "anything without one demoted or cut"); the figure in §6.4 carries the gallery's table |

### 7.3 Build order against the 15:00 CDT code freeze

All hours are *estimates*. Times are America/Chicago, 2026-10-04.
- **Assumptions.** The scaffold (C2) starts once this file and its critic pass land, about **08:00** (the draft
  assumed 07:30). The morning review clears **gate G0** at 09:30. Five lanes run in parallel: three for the scaffold,
  two for checks.
- **Total work.** 21.75 lane-hours:
  - agnostic items 1–12: 11.75;
  - S0: 1.0;
  - checks T1–T4: 7.25;
  - enable and freeze steps F0–F3: 1.75.

  T5 adds 1.5 if built. H runs after the freeze and is not counted. Capacity is 5 lanes × 7.0 h (08:00–15:00) = 35
  lane-hours, but dependencies bind first: lane A is idle from 12:00 and lane B from 13:00.
- **Why lane A is re-sequenced.** With an 08:00 start, item 2 cannot finish by 09:30. At G0, T1 and T2 need only the
  id decoder and the pairing rule, so item 2 is split:
  - item 2a (`session/idclock.py` with the DA20 gate and its parity test, plus `session/pairs.py`) lands by 09:30;
  - item 2b, the rest of `session/`, follows.
- **Gate G0 (human):** confirm the Track A item JSONs are committed (open item 0, blocking); approve the check list
  (§7.0), DA13–DA21, the N2-on-Claude-Code question (open item 11) and the merges (open items 1–2). **No detection
  logic is written before G0.** Before G0, check lanes may only port the *frozen measurement functions* into the
  parity harness (`tests/parity/`), which reproduce Track A and decide nothing.

| # | Item | Depends on | Est. h | Lane | Window (est.) |
|---|---|---|---|---|---|
| 1 | `verifier/ir` + `turns.py` + parity + root `requirements.txt` | — | 0.5 | A | 08:00–08:30 |
| 2a | `session/idclock.py` (DA20 gate + `test_idclock_parity`) + `session/pairs.py` | 1 | 1.0 | A | 08:30–09:30 |
| 2b | rest of `session/`: responses, clocks, capabilities, threads, sidecar schema, `build_session` | 2a | 0.5 | A | 09:30–10:00 |
| 3 | `checks/base.py` + `registry.py` + `ref_result_present` + `calib/build.py` | 2b | 0.75 | A | 10:00–10:45 |
| 4 | `compose.py` + `api.py` (with `sidecar=`) + `test_compose.py` | 3 | 0.5 | A | 10:45–11:15 |
| 6 | CLI `verify/checks/inspect` + text + JSONL | 4, 5 | 0.75 | A | 11:15–12:00 |
| 5 | `loaders/` (detect, files, corpora, units) | 1 | 1.0 | B | 08:00–09:00 (written against the `ir` import surface until item 1 lands) |
| S0 | `loaders/sidecar.py`: `read_cc_numlines`, `read_entire_tally`, `copied_request_ids` + `test_sidecar.py` | 5 | 1.0 | B | 09:00–10:00 |
| 10 | `render/html.py` + `demo.py` + `heldout.py demo-input`, developed on fixture verdicts written to the §3.3 types. It is hooked to `api` (item 4) and the pack (item 7) at the end; the real pages are built in step F2 | 3 (types); 4 and 7 to integrate | 1.5 | B | 10:45–12:15 |
| 11 | `render/figures.py` | 9 | 0.75 | B | 12:15–13:00 |
| 8 | `eval/attacks.py` port + `test_attacks_parity` | — | 1.5 | C | 08:00–09:30 |
| 7 | `eval/heldout.py`: manifest verify, E pack, attack plans, **pack sidecar table**, agentcap exposed-id recompute | 8, S0 | 1.0 | C | 09:30–10:30 (sidecar table once S0 lands at 10:00) |
| 9 | `metrics.py` (+ `flag_loc_credited`) + `_stats.py` + `run_eval.py` (quick + full) + `core.py` wiring + determinism, budget and import tests. Metrics and `_stats` start at 10:30; the `run_eval` integration waits for item 4 (11:15) | 4, 7 | 1.5 | C | 10:30–12:15 |
| 12 | `labeled.py` | 9 | 0.5 | C | 12:30–13:00 |
| T1 | `id_bracket`: pure functions + parity on E/B caches (1.5; the `corrections=()` parity first, the adopted set once S0 lands), wrapper + `calib/id_bracket.json` (0.5) | G0, 2a; S0 for the dedupe; 3 for the wrapper | 2.0 | D | 09:30–11:30 |
| T2 | `inline_output_accounting`: pure functions + parity (1.25), wrapper + calib (0.5) | G0, 2a; 3 for the wrapper | 1.75 | E | 09:30–11:15 |
| T4 | `dual_render_recount` + `_whitelist.py` + parity | 3, S0 | 1.5 | D | 11:30–13:00 |
| T3 | `ledger_tally` + parity (+0.5 h fallback, §7.1.3) | 3, S0 | 2.0 | E | 11:15–13:15 |
| T5 | `latency_floor` (COULD) | 3 | 1.5 | lane A after 12:00, only if T3 and T4 are on time; else cut | — |
| F0 | first end-to-end quick E run with T1 + T2: smoke, budget test (≤ 120 s) | 9, T1, T2 | 0.25 | C | 12:15–12:30 |
| F1 | **enable run:** `run_eval --mode full --split E --checks id_bracket,inline_output_accounting,ledger_tally,dual_render_recount`, MUST checks first | T1–T4, 9 | 0.75 | C | 13:30–14:15 |
| F2 | enable decision per §5.7: set `ENABLED_CHECKS`; freeze-baseline quick run → `fpr_cap`, `CLEAN_CAP` in `config_eval.json`; build the demo pages from the frozen checks | F1 | 0.5 | C + B | 14:15–14:45 |
| F3 | freeze: a human commits and records the SHA. Nothing that changes verdicts changes after this | F2 | 0.25 | human | 14:45–15:00 |
| H | `heldout.py build-cache/build-pack --final --freeze SHA`, then `run_eval --split H --final` once, then census | F3 | 0.5 + parse time (unmeasured) | after 15:00 | — |

**Dependency graph.**

```
08:00                       09:30 (G0)                    12:00                13:30        14:45 15:00
lane A  1 ─► 2a ──────────► 2b ─► 3 ─► 4 ─► 6 ─► (idle: takes T3/T4 overflow, else T5)
             │                    │    │
lane B  5 ─► S0 ──┬───────────────┼────┼─► 10 ─────────────► 11
             │    │               │    │
lane C  8 ───┼──► 7 (+sidecar table) ──┴─► 9 ─► F0 ─► 12          F1 (full E) ─► F2 ─► F3 ─► H
             │    │               │         ▲                       ▲
lane D       └────┼─ G0 ─► T1 core ─► T1 wrap ─► T4 ────────────────┤
lane E            └─ G0 ─► T2 core ─► T2 wrap ─► T3 ────────────────┘
```

**Critical path.** 1 → 2a → 2b → 3 → 4 → 9 → F0 is about 5 h of dependent work. It ends near 12:30, before the check
lanes finish. The binding chain is G0 → T2 wrap → T3 (SHOULD) → F1, with about 15 minutes of slack. For the MUST
checks it is G0 → T1 (2.0 h) → F1, which leaves about 2 h of slack before 13:30.

**Slip rules.** These replace the draft's single rule, "cut the next §7.4 item for each 30 minutes of G0 slip". That
rule cut items on lanes A–C, which frees no time on the check lanes, where a G0 slip lands.
- **G0 slips.** T1–T4 move by the same amount.
  - Lane A is idle from 12:00 and lane B from 13:00. Whichever of T3 or T4 has not started by then moves there,
    because both depend only on items 3 and S0.
  - The 13:15 parity deadline holds: a SHOULD check that is not parity-green by 13:15 stays registered and disabled
    (§7.4).
  - The MUST checks absorb a G0 up to about 11:30. Past that, F1 starts when T1 or T2 is parity-green. A MUST check
    that is not green by 13:45 ships registered and disabled, and the miss is reported.
- **Item 9 is late.** No check can be enabled without a full-mode E run (§5.7), so item 9 outranks every item that is
  not a MUST check. Lanes A and B drop their remaining items (12, then 11, then 10) and help finish it.
- **F1 overruns** (estimate 20–45 min, §5.3). F1 runs `id_bracket` and `inline_output_accounting` first, then the
  SHOULD checks. At 14:20, every check whose full-mode cells have finished is decided. Any other check ships
  registered and disabled, and the report says why.
- **Late scaffold start.** Each 30 minutes past 08:00 shifts lanes A–C. The check lanes are unaffected as long as
  item 2a lands by G0.

### 7.4 Cut list (in this order when behind)

Directory input and the demo gallery are already cut (§7.2), so they are not on this list.
1. `latency_floor` (COULD). It is not started unless lane A is idle at 12:00 and T3 and T4 are on time.
2. per-check verdict cache (accept fewer climb iterations).
3. `census` subcommand (run the census from a script instead).
4. second demo page (`demo_spec_exec.json`).
5. `ledger_tally`. If parity is not green by 13:15, it stays registered and disabled.
6. `labeled.py` register/join (keep `validate`; the pipe stays specified).
7. `dual_render_recount`. Same 13:15 parity deadline.
8. figures as SVG (fall back to the HTML tables in the report).
9. honest/tampered toggle animation (keep two static pages).

**Never cut:**
- `id_bracket`;
- the `inline_output_accounting` implementation and its parity test (the check may *ship disabled*, but it is
  measured);
- every parity test;
- `run_eval.py`'s single-JSON contract;
- H manifest verification;
- the reference check;
- `unconstrained` reasons;
- per-threat-class reporting (DA13);
- the "synthetic only" footer and the §1.4 statement.

### 7.5 Risks

**Agnostic risks (from the draft), each mitigated or accepted.**

| Risk | Sev. | Mitigation or acceptance |
|---|---|---|
| H leaks into tuning (the climb loop is scored on H, or a script reads it) | High | DA5: climb on E; H events only via `--final --freeze`, logged; no change after the first H read (5.2 rule 4); `test_no_heldout_access.py`; verifier has no H notion; the H pack does not exist until the freeze |
| H results fed back (a check disabled or recalibrated because it failed on H) | High | 5.2 rule 4 and 5.7: H criteria are reported, never acted on; the write-up reports the first H run |
| R3/R4/R5-type evidence already read H in Phase C; B5e read timing and request-id statistics over the full new corpora | Med | **Accepted and documented**: `blind_on_H: false` beside every affected H number, from `config_eval.json` `h_exposure` (`PREREG_E.md` §0; `prereg_e.json` change_log D6). Affects `ledger_tally` and `dual_render_recount` everywhere, and `id_bracket` on new corpora |
| H shares repos, operators and submitting agents with E (session-level split) | Med | **Accepted and documented** as a limitation of the H numbers; deviations table |
| The climb loop edits what judges it | High | DA6: score path imports only `verify_session`; stats vendored in `eval/`; attacks on IR frames; plans pre-built; `test_eval_imports.py`; `run_eval` asserts module origins |
| Gate breaches halt the overnight loop (3 consecutive `ok: false`) | Med | DA10: a gate breach is `ok: true`, headline -1.0, a clean reject |
| 14 agentcap H sessions parse-exposed and not identifiable by id | Low | Recompute exactly as `load_agentcap.split_incident` does and drop if the sha matches; else keep and label (5.2 rule 5) |
| `seq` changes when a loader changes → stale labels and cached verdicts | Med | `ir_sha` on labels; loader shas in BUILD.json and pack metadata; vcache keyed by `ir_sha` and file-byte `code_sha` |
| Same `ts_kind` with different timestamp semantics across harnesses | Med | DA4/DA16: statistical checks calibrate and enable per unit; `id_bracket` requires `ts.event` and states its stamp assumption (7.1.1) |
| Quick eval exceeds 2 min on the dev box | Med | Fixed pack sizes; halve by day; budget test; 8 processes; vcache |
| Attack port diverges from the pre-registered battery | Med | `test_attacks_parity.py`; the F1 parity row reproduces an N7 cell count exactly (7.1.1) |
| A check crashes on one odd session and blocks the climb loop | Low | **Accepted**: `check_errors > 0` → `ok=false` is intended; `--strict` for development |
| Private or gated content leaks through html/census | High | `cc_local` render refusal; `PUBLISHABLE` set; aggregates-only census for `cc_local`; redaction before escape |
| Secrets in public corpora displayed in the demo | Med | `newcorp_common.redact` on every displayed string; loaders already redact |
| `verifier` depends on `analysis/` being on `main` | Med | Morning merge decision; DA1 fallback: vendor `ir.py` and `redact` behind the same re-exports |
| Contradictions on presumed-honest public data get reported as FPs (or as fabrications) without review | Med | `honest_contradictions_*.jsonl` + manual review sample (`SCOPE.md` §5.7) |
| Reviewers read synthetic recall as real-world detection | High | §1.4–1.5 statements, demo footer, per-threat-class reporting with DA13, labeled-set metrics kept separate |

**Risks specific to the chosen checks.**

| Risk | Sev. | Mitigation or acceptance |
|---|---|---|
| **Anthropic changes the request-id layout** (undocumented, no stability promise; `msg_` already changed on 2026-07-06) | High | DA20 gate; a format change becomes lost coverage plus `id_layout_unrecognized`, never contradictions; the census reports the decodable share per month. **Accepted and documented** as a material limitation (§1.6) |
| A forger re-mints consistent ids, or a relay rewrites tool_use fields and keeps the id | High | **Accepted**: coherent forgery, out of scope by definition (§1.2); stated in `explain()` and the write-up |
| `id_bracket` honest failures: client clock jumps (6 of 11 on E), out-of-order result writes (3), restamped copies (§7.1.1, [F1 `units."swechat/claude_code\|E".posthoc_mechanisms.counts`]) | Med | Adopted corrections (DA17); ordered-inputs variant reported and pre-registered for H; residual E rate 11/3,325 **accepted and printed**. The clock-step correction is rejected because it costs power (30 s power 0.8909 on B) |
| `id_bracket` blind spots: forward-dating, early results, deletions, shifts ≤ 2 s, random foreign splices dropped by the 1-day filter | Med | **Documented**: walk-through table; `abstain:id_time_implausible` counted; R1b is a follow-up, cut from this build (§7.1.6) |
| `id_bracket` transfer rests on one submission (tbench2 WozCode [RES `resolutions[0]`]) and one corpus dominated by one model (pub_cc_hf [PCH `r1.pooled_BuE.artifact_checks.AC4_dominance`]) | Med | **Accepted**: transfer is labelled WEAK in both, as Track A labelled it; the write-up says "one more harness configuration", not "transfers" |
| `inline_output_accounting` costs 237/1,492 = 0.159 of honest Claude Code sessions on E (§7.1.2) | High | DA16 enable rule; confidence and session cost printed with every verdict; demo selection excludes flagged honest copies and prints the cost; **human decision** (open item 11) whether to enable it on Claude Code formats at all |
| `inline_output_accounting` in structured tool-call formats tests an attack the harness already prevents | Med | **Documented** (§7.1.2 soundness); its positives there are labelled "model-generated text in a result (or hidden output)" |
| Thinking characters double-counted in Claude Code `chars_out` | Low | **Accepted**: τ was computed the same way (N2 deviation 6); the parity test locks it; changing it needs a new τ and a new pre-registration |
| `ledger_tally` exists only for swechat and is non-localized | Med | **Accepted**: SHOULD tier; reported as session-level; 0 ADR contribution by design |
| `ledger_tally` honest flags come mostly from a dataset join artifact (14 of the 23 B∪E flags sit in the 18 sessions whose two tables disagree; §7.1.3) | Low | Join-fix variant reported (9/3,165); not adopted (it would be post hoc) |
| `dual_render_recount` evaded by any whitelist marker (2,011 of 58,209 results match a class; §7.1.4) | Med | **Documented** as an evasion route; record-editing only |
| A check's implementation differs from Track A's (port bug, IR-vs-raw difference) | High | DA15 parity tests are a precondition to enabling. If parity fails, the check ships disabled and the miss is reported |
| Track A item JSONs are uncommitted, so DESIGN.md cites files that could change (15 of 34 cited files, among them the sources of every MUST-check number) | High | **Blocking at G0** (open item 0): a human commits them before any build reads them. Appendix A records each file's sha256 prefix; `calib/build.py` refuses a source whose sha differs from the one recorded. `second_pass.json` was still being rewritten during the critic pass, so its sha must be re-recorded at commit |
| R1's ALIVE and cc_local's WEAK are resolved here, not in a Track A synthesis | Low | Marked **[resolved here]**. The Track A assembly, written later, reaches the same labels [SP `r1_rows`]; open item 12 |
| Track A sources disagree on tbench2 R1 (RES: WEAK; N6 grid: ALIVE) | Low | The design uses the committed RES label (WEAK) and calls tbench2 transfer "one more harness configuration", never "transfers". Open item 17 |
| One model dominates every calibration unit (swechat/claude_code: claude-opus-4-6 holds most events for R1, N2, R4 and R5; AC4 blocks in [F1 `r1."swechat/claude_code".artifact_checks.AC4_dominance`], [N2 `units."swechat/claude_code".groups."swechat/claude_code".artifact_checks`], [R45 `R4.units."swechat/claude_code".artifact_checks`, `R5.units."swechat/claude_code".artifact_checks`]) | Med | **Accepted**: every Track A AC4 leave-out of that model kept the label; reported as a stratum in the eval report |
| G0 slips, or a lane overruns | Med | Slip rules and cut list (§7.3–7.4): check-lane overflow moves to idle lanes A and B; 13:15 parity deadline for SHOULD checks; MUST checks have about 2 h of slack before F1 |
| The scaffold starts at 08:00, not 07:30, because the critic pass ran first | Low | Lane A builds item 2a (idclock + pairs) first, so T1 and T2 still start at G0 (§7.3) |
| The full-mode enable run (F1) takes longer than its 45-minute window | Med | MUST checks run first; at 14:20 unfinished checks ship disabled (§7.3 slip rules) |

---

### Open items for the morning (human decisions this design surfaces)

0. **Blocking, before G0: commit the Track A item JSONs.** Appendix A marks 15 cited files UNCOMMITTED, with the
   sha256 prefix each had when this was written. The 13 item outputs include F1, N2, N7T, N7C and R45, which hold most
   of the Track A numbers behind the kept checks. The other two are `second_pass.json` and `n6_grid.json`, cited only
   for cross-checks. Until they are committed, this
   design does not meet the rule that every number cites a committed file. Every number this design takes from them
   must stay reproducible. `calib/build.py` refuses a source whose sha differs from the one recorded. If any of them
   changed after Appendix A, re-run the citation check before G0.
1. Merge `analysis/lib` + `analysis/loaders` to `main` with `verifier/` (DA1), or accept the vendored fallback.
2. Merge `eval/run_eval.py`, `attacks.py`, `heldout.py`, `metrics.py`, `_stats.py`, `labeled.py` and
   `config_eval.json` to `main`, and replace `eval/core.py`'s `main()` / `run_once` as in §5.1 (`PHASE_E_PLAN.md`: a
   morning decision).
3. Extend the `SCOPE.md` §3 `turn` contract with optional `request_id`, `api_msg_id`, `native_error` and `exit_code`.
   Without them, `id_bracket` and `ledger_tally` read `missing:` on any input in turn format.
4. Confirm the `fpr_cap` / `CLEAN_CAP` rule of §5.5: baseline + 1 honest session per unit, and baseline + 0.2 points
   pooled, both on the pack. The values are written at step F2.
5. Sign off the deviations from `SCOPE.md` (split, eval import, headline, gate semantics, effective coverage, census
   timing, `core` ids, and the demo tamper class).
6. `schemas/` does not exist on `main` yet (`SCOPE.md` §3 says contracts are committed there). Commit
   `schemas/verdict.json` (JSON Schema of `Verdict.to_scope_dict`) and `schemas/labeled_call.json` with the merge.
7. Add the root `requirements.txt` (DA8) with the merge.
8. Confirm the SWE-chat HF gate terms allow publishing a tampered session before the demo page is published
   (`SCOPE.md` §2 item 6, §11).
9. Decide whether `run_eval` also scores the `SCOPE.md` §6 classes from the untracked `eval/inject.py` (§5.4).
10. **`time_tail_early` class.** It is also the timing footprint of a fast canned shim (§1.5). Default: keep it in the
    record-editing class, as fixed before N7 was read. If it moves to the execution class, only `latency_floor` would
    be credited for it (DA13), not `id_bracket`.
11. **Enable `inline_output_accounting` on Claude Code formats?** The default is yes, under DA16: per-response honest
    0.0169 on E. It costs 237/1,492 = 0.159 of honest sessions (§7.1.2), and in structured tool-call formats it tests
    an attack the harness's role labels already prevent. Choosing no drops the execution-class headline in
    swechat/claude_code to 0, and the write-up must then say the shipped verifier has no in-scope power in that unit.
12. **Confirm the two [resolved here] labels:** `id_bracket` ALIVE in swechat/claude_code, and WEAK in cc_local. They
    apply F1's stated `PENDING_N7` rule to the N7 timing output (§7.1.1). The Track A assembly, written later, reaches
    the same two labels [SP `r1_rows`], so this is now a formality.
13. **DA17.** The ordered-inputs correction is pre-registered here as a reported variant for H, and it does not ship.
    Confirm before any H build.
14. **`ledger_tally` prior art.** The tally-vs-recount leg was not searched separately by Track B. Accept PARTIAL via
    B3.1/B3.2, or demote `ledger_tally` to COULD.
15. **Gate G0 time.** It is assumed to be 09:30, with five parallel lanes (§7.3). A slip moves the check lanes. The
    §7.3 slip rules then move SHOULD checks onto idle lanes or disable them at the 13:15 parity deadline. The MUST checks
    absorb a G0 up to about 11:30.
16. **Split hygiene note** (`PRIOR_ART.md` §4): B2a's id-format scans touched aiv_cu H rows. No shipped check reads
    aiv_cu ids (`inline_output_accounting` reads usage only), so this changes no shipped `blind_on_H`. It is recorded
    for the write-up.
17. **tbench2 R1 label.** The committed resolution says WEAK, because the whole population is one submission and the
    AC4 cap applies [RES `resolutions[0]`]. The uncommitted N6 grid says ALIVE [N6 `cells.R1_bracket.tbench2.label`].
    This design uses WEAK. Track A should reconcile the two before `TRANSFER_MATRIX.md` is committed, or the write-up
    must state both.
18. **Cut features that a Track B search could revive.** P3 (zero-error tail; no Track B verdict) and R3 (git window;
    UNVERIFIED) survived Track A but are cut because prior art was never checked (§7.0). A Track B pass on either
    would make it eligible again, for a later build. Neither fits today.

---

## Appendix A: sources cited by tag

Raw-byte sha256 (first 16 hex digits), taken when this file was written. "UNCOMMITTED" means the file was on disk in
this worktree but not yet committed (open item 0). Line endings may differ across checkouts, because `core.autocrlf`
is true. `calib/build.py` therefore records LF-normalised sha256 values, and these prefixes are for human
cross-checking only.

| Tag | Path | sha256[:16] | Committed |
|---|---|---|---|
| F1 | `analysis/out/phase_e/f1_bracket.json` | e0bbbd598d369505 | UNCOMMITTED |
| F2 | `analysis/out/phase_e/f2_floor_shift.json` | ce313640eaac73de | UNCOMMITTED |
| P13 | `analysis/out/phase_e/a1_p1_p3.json` | 05b63d8451e96a65 | UNCOMMITTED |
| P24 | `analysis/out/phase_e/a1_p2_p4_f3.json` | 9ebd5e5e89e49920 | UNCOMMITTED |
| N1 | `analysis/out/phase_e/n1.json` | 398b4723e90440a8 | UNCOMMITTED |
| N2 | `analysis/out/phase_e/n2.json` | e924a2978e873be0 | UNCOMMITTED |
| N3 | `analysis/out/phase_e/n3.json` | 64865fdeb491ff48 | UNCOMMITTED |
| N45 | `analysis/out/phase_e/n4_n5cg.json` | 995bca333eddef93 | UNCOMMITTED |
| N5 | `analysis/out/phase_e/n5_battery.json` | fe2d9a7b156c9d59 | UNCOMMITTED |
| N7T | `analysis/out/phase_e/n7_timing.json` | e7899b2ec5e1b130 | UNCOMMITTED |
| N7C | `analysis/out/phase_e/n7_content.json` | 5c677a8138f24097 | UNCOMMITTED |
| R23 | `analysis/out/phase_e/r2_r3.json` | 5b5c3305bd3d9338 | UNCOMMITTED |
| R45 | `analysis/out/phase_e/r4_r5.json` | d3e02c6902407fdf | UNCOMMITTED |
| TB | `analysis/out/phase_e/newcorp_measure_tbench2.json` | b2c6237101df0d1f | committed |
| GLM | `analysis/out/phase_e/newcorp_measure_glm_tb21.json` | bad548187187d371 | committed |
| PCH | `analysis/out/phase_e/newcorp_measure_pub_cc_hf.json` | 3679fade25339216 | committed |
| PTC | `analysis/out/phase_e/newcorp_measure_pub_trace_commons.json` | 6115363ff575cc87 | committed |
| AC | `analysis/out/phase_e/newcorp_measure_agentcap.json` | 40816aef748decb0 | committed |
| PCX | `analysis/out/phase_e/newcorp_measure_pub_codex.json` | 0ef8ff1980d0f49e | committed |
| RES | `analysis/out/phase_e/newcorp_resolutions.json` | 5008f509dec292e2 | committed |
| CAL-tbench2 | `analysis/out/phase_e/prereg_e_calibration_tbench2.json` | 7d95d098b3724861 | committed |
| CAL-pub_cc_hf | `analysis/out/phase_e/prereg_e_calibration_pub_cc_hf.json` | 06e63db1d8906fdf | committed |
| CAL-agentcap | `analysis/out/phase_e/prereg_e_calibration_agentcap.json` | f0ae0eeadfd56960 | committed |
| CAL-pub_codex | `analysis/out/phase_e/prereg_e_calibration_pub_codex.json` | c95f37397963116d | committed |
| CAL-glm_tb21 | `analysis/out/phase_e/prereg_e_calibration_glm_tb21.json` | f340bebb29b666a6 | committed |
| DT | `analysis/out/phase_e/decision_table.json` | e3747254f75a509a | committed |
| B4 | `analysis/out/phase_e/track_b/b4.json` | 1d26d0a2dc1d8d99 | committed |
| CI | `analysis/out/phase_e/track_b/corpus_inventory.json` | 23a49aa80c7dfabd | committed |
| B2a | `analysis/out/phase_e/track_b/B2a_provider_id_facts.json` | 988e9c6df9ea4712 | committed |
| B5a | `analysis/out/phase_e/track_b/B5a_sweagent_openhands.json` | 8c482fba5ffeccc7 | committed |
| PRE | `analysis/prereg_e.json` (the frozen pre-registration; in `analysis/`, not `analysis/out`) | 568d423f0e061f9a | committed |
| MAN | `analysis/HELDOUT_MANIFEST.json` (the committed H manifest; in `analysis/`) | ef45a9edba2fce5d | committed |
| SP | `analysis/out/phase_e/second_pass.json` (Track A assembly; added by the critic pass; the file was rewritten at 07:16, so this sha may change again before commit) | 74e5c62a87a7cbee | UNCOMMITTED |
| N6 | `analysis/out/phase_e/n6_grid.json` (N6 transfer grid behind `TRANSFER_MATRIX.md`; added by the critic pass) | 63b1a0256f2cff05 | UNCOMMITTED |

Track B verdicts are cited by section of `analysis/PRIOR_ART.md`. That file synthesises the committed
`analysis/out/phase_e/track_b/*.json` evidence; the verdicts are labels, not numbers.

---

## Appendix B: critic changes to the draft (kept for provenance)

Made in place by the critic pass (2026-10-04). Each item names the problem it fixes.

**Inconsistencies with `SCOPE.md` contracts, `eval/core.py` or `ir.py`**
1. Added the "Deviations from `SCOPE.md`" table (split, eval import, headline, gate, effective coverage, census, `core`
   ids); DA5 now says it deviates from SCOPE §4/§8.2 instead of reading as SCOPE-compliant.
2. `Verdict` carried only `call_key` as `call_id` and had no `detail`, so `to_scope_dict` and the `(session_id, call_id)`
   label join could not work on duplicated ids. Now `call_id` (raw) + `call_key`, `detail`, and a `core` rule for
   non-turn inputs (§3.2, §3.3). `CallVerdict.call_id` renamed `call_key`.
3. The eval imported `verifier.session.build_session` (SCOPE: the eval imports only `verify_session`). Added exact
   `verify_session` / `verify_sessions` / `verify_file` signatures with an IR-frame overload (§2.6); attacks now run on
   IR frames inside `eval/`.
4. No `turn` → IR mapping existed; added `TURN_TO_IR` from the SWE-chat `(role, turn_type)` values (§2.6).
5. `IR_SCHEMA_SHA` hashed only `COLUMNS` while the test claimed to cover `normalize_tool` and `ERROR_MARKERS` (a local
   variable cannot be hashed); now hashes `ir.py` bytes (§2.4).
6. `compose` was called without its required `kinds`, was a generator declared as returning a list, compared `None`
   confidences, and could emit an `ok:` reason on an unconstrained verdict; fixed (§4.6).
7. Identity checks had no calibration file, yet `contradicted()` required a confidence taken from one; identity checks
   now ship `fpr_hi`/`recall_lo`-only files and may have `None` (§3.3, §4.4).
8. `core.py` averages per-seed `run_once` values; the headline was "pooled over seeds". Now the mean of per-seed values,
   and `core.py` delegates to `run_eval.main` so the honest pass runs once (§5.1, §5.5).
9. The `ok: false` gate would trip `ops/orchestrate.py`'s 3-consecutive-failure halt, and a 0.0 headline would tie a 0
   baseline and be kept; gate breaches now return `ok: true`, headline -1.0 (DA10).
10. Units `tbench2/<format>`, `glm_tb21/atif`, `pub_*/<fmt>`, `aiv_cu/<stratum>` did not match the Phase E units or
    calibration files, and "the eval never borrows" contradicted the pre-registered proxy map (change_log D1). Units
    and `EVAL_CALIBRATION_UNIT` now follow prereg (§2.5, §4.5). Stale "IR caches today" column fixed (B/E exist).
11. Statistical checks' below-threshold behaviour was half-specified (`abstain:below_threshold` used but not in the
    vocabulary; `supported` confidence defined for them). Now: they never emit `supported`; coverage counts
    "screened" calls (§3.3, §4.6, §5.5).
12. `MUST`/`KILL` criteria were evaluated on H while the freeze rule enables on E; split into an E enable decision and
    an H confirmation that is never acted on (§5.7).
13. Recall required localization yet fed the prereg `n7_cell_label`, whose recall does not; split into `recall`
    (prereg, seed 0) and `recall_loc`/ADR (headline). Cell-label FPR is now the prereg same-sessions FPR (§5.5).
14. The headline pooled threat classes while §5.4 said they are never pooled; classes now weigh 0.5 each and the
    pooled number is labelled a climb score only (DA12).
15. `NOT_TESTABLE` used an unsourced 95% threshold; now the prereg fill rule (§5.5).

**Decisions an implementer would still have had to make (now made)**
16. Where the eval finds packs from the orchestrator's `eval_snapshot/` copy (`data/eval/verifier_v1` under the main
    checkout via `git --git-common-dir`), flat imports inside `eval/`, where reports go (`ops/state/eval/reports`, so
    the climb loop's `git add -A` cannot commit them) (§2.1, §5.1, §5.5).
17. Pairing and orphan rules for repeated `call_id`s; `call_key` for every duplicate; id-less responses (§3.1, §3.2).
18. Per-attack `target_call_ids` / `tampered_seqs`, including deletions, where the probe has no target (§5.4).
19. Donor pools and rng choices resolved at pack-build time into an attack plan (§5.3).
20. Seeds vs labels (labels on seed 0), `min(40, n_eligible)`, per-unit gate min-n, pooled gate population (§5.3, §5.5).
21. `resolution_ms` uses the coarsest stamp; `checkset_sha` defined; composed unconstrained reason rule;
    `ContractError` handling and CLI exit codes without `--strict` (§3.3, §4.2, §4.4, §6.1).
22. agentcap exposed-H recompute: the incident file holds no 806-id list; the procedure is now
    `load_agentcap.split_incident`'s exact recomputation (§5.2 rule 5).
23. Calibration build script, splits for thresholds (A), `fpr_hi`/`recall_lo` (B) (§4.7).
24. vcache keyed on file bytes, not on the version string the code under test reports (§5.3).
25. Demo session selection rule fixed before looking; demo built via a file handoff so `verifier` never imports `eval`
    (`render_session_html` no longer takes `eval`'s `Tamper` type) (§6.3).
26. Root `requirements.txt`, `schemas/`, SWE-chat gate terms and `eval/inject.py` added as open items.

**Claims beyond what the threat model allows**
27. The `ts` row said "generating text takes time"; a canned-output shim returns fast. Reworded: too-fast-for-the-work
    is sound, a generation-time floor says nothing about canned shims (§1.2).
28. "In scope" now says modelled, not detected; §1.4 cites the brief's "perfectly self-consistent log" for execution-
    layer replacement (§1.2, §1.4).
29. DA11: `contradicted` only from field-vs-uncontrolled-field, physical-bound or record-vs-record rules; distributional
    anomalies (zero-error tail, round numbers, hex uniformity) go to the census. A dual-rendering recount is a
    record-editing check only (§4.1, §7.1).
30. `rewrite_consistent_k` leaves ids and usage unshifted, so id- or usage-based detections of it are reported as
    record editing (§5.4). Non-localized contradictions are counted separately from localized ones (§4.6).
31. combo2's harness flags are no longer called "natural labeled positives" without the `PRIOR_ART.md` §3.12 UNVERIFIED
    caveat; the demo footer no longer says no corpus contains a natural fabrication (§1.4, §6.2).
32. "Cleared Track B" now means NOVEL or PARTIAL; UNVERIFIED (`PRIOR_ART.md` §3.13) does not clear (§7.1).
33. Problem statement cut to three sentences, as C1 requires (§1.1).

**Eval designs that could touch H during tuning (closed)**
34. `KILL ... disable` after an H result fed H back into the shipped config; now report-only, no change after the first
    H read, and the write-up reports the first H run (§5.2 rule 4, §5.7).
35. `--labeled DIR --split H` was runnable during development; now `--final --freeze` only, with B/E as the labeled
    set's dev splits (§3.4, §5.8).
36. The full-corpus census (SCOPE §5.7) includes H; it is now `eval/heldout.py census --final` after the H run, not a
    `verifier` subcommand (§3.3, §5.2 rule 3).
37. `build-pack --split H` and `--mode full --split H` were not gated; both are H reads now (§5.2 rule 3, §5.3).
38. Calibration "from A (or A+E)" would have made E FPR in-sample for the climb split; thresholds now from A only.
39. H blindness was self-declared in the check's calibration file (editable by the climb loop) and missed
    change_log D6 (B5e read timing and request-id statistics on the full new corpora); now a frozen
    `config_eval.json` `h_exposure` table covering both (§4.7, §5.2 rule 7).
40. The score path imported `analysis.lib.stats` from `--repo`, which the climb loop may edit (the orchestrator only
    rejects `eval/` edits); stats are vendored into `eval/_stats.py` and module origins are asserted (DA6, §5.1).

---

## Appendix C: Critic changes (Track C critic pass on DESIGN.md, 2026-10-04, about 07:15–07:45 CDT)

The critic pass edited the file in place. It ran no build, read no H data, committed nothing and touched nothing
swarm-related.

**What the critic verified, with no change needed**
- **Citations resolve.** Every single-line `[TAG key]` citation resolves in its file: 194 of 200. The other 6 are
  `<unit>` / `<attack>` templates whose concrete keys are given beside them.
- **Values match.** About 60 numbers were checked against the values at their keys, and none differed:
  - every R1 N7 count in §7.1.1;
  - the N2 enable table and every τ;
  - the R4 and R5 counts, including the 203/75/5/3/1 classes;
  - the F1 corrections and post-hoc counts;
  - the P1, N1, N3, N5, R2 and R3 deciding numbers;
  - the B4 id counts and the manifest n_H/n_E.
- **Kept checks survived Track A in their item JSONs.** R1: `PENDING_N7`, and the stated rule is met (4 single-call
  types DETECTS on E). N2: WEAK. R5: ALIVE. R4: WEAK. P1: WEAK in all three units.
- **Kept checks cleared Track B.** Each has a non-TAKEN verdict with the difference stated: B2 PARTIAL/NOVEL
  application, B3.4, B3.5, B3.1 and B1(a). R5's tally leg stays open item 14.
- **MUST checks carry finding tags.** Both have them.
- **Threat model and non-goals are explicit** (§1.2, §1.4).

**Changes**
1. **No detection check implied to exist.** A status paragraph now says no `verifier/` code exists yet, and that
   every recall and FPR number is a Track A probe measurement, not a verifier measurement. Summary items 2–3 now
   attribute the numbers to Track A probes.
2. **Overclaim corrected.** "N2 is the only mechanism with any power on the in-scope class" was false as worded.
   Track A also has exec-class PARTIAL cells:
   - P3 on `sub_single_flip_error`, 8/500 vs 0/500;
   - N5d on `rewrite_consistent_k` k = 5 in aiv_cu, 221/500 vs 169/500;
   - R3 on `rewrite_consistent_k` k = 2, 45/500 (an edit artifact).

   The claim now reads: the only *surviving* mechanism whose in-scope power is not an edit artifact. §1.5 lists the
   other three (summary, §1.5, §7.0, §7.2).
3. **Uncommitted sources made blocking.** 15 of the 34 cited files are uncommitted: the 13 Track A item JSONs, plus
   `second_pass.json` and `n6_grid.json`, which the critic added. The task rule (every number cites a committed
   file) therefore is not met until a human commits them. The critic may not commit. Open item 0 is now a G0
   precondition, and the risk is raised to High.
4. **Track A synthesis cross-checked.** `SECOND_PASS.md` and `TRANSFER_MATRIX.md` appeared after drafting. Their JSONs
   agree with every label used for the kept checks [SP `r1_rows`, `r2_r5_rows`, `a1_rows`]. One conflict is recorded:
   tbench2 R1 is WEAK in the committed RES and ALIVE in the N6 grid (§7.1.1, risks, open item 17). The design keeps
   WEAK. Appendix A gains SP and N6.
5. **Track B clearance enforced for every feature, using the draft's own §7.0 rule.**
   - "No verdict" now also fails to clear.
   - Cut: the P3 census statistic (no Track B verdict); the R3 `witness` family (UNVERIFIED, which §7.0 already said
     does not clear, yet it was kept as COULD); R1b and the two-clock source (no measured or pre-registered finding).
   - Cut: directory input and the demo gallery (no finding; C1: "anything without one demoted or cut").
   - DA11 and §4.1 now require Track B clearance for any census statistic. Open item 18 added.
6. **Build arithmetic.** Items 1–12 sum to 11.75 h, not 12.25. The total is 21.75 lane-hours, not 22.25, with H
   excluded because it runs after the freeze.
7. **Schedule made feasible from now.**
   - The scaffold cannot start at 07:30, because the critic pass runs until about 07:45. The schedule now starts at
     08:00.
   - Item 2 is split. 2a (idclock + pairs) lands by G0, so T1 and T2 still start at 09:30.
   - Item 10 started at 09:30, before its dependencies (item 4 at 10:45, item 7 at 10:00). It now runs 10:45–12:15
     on fixtures.
   - Every window was recomputed. The binding chain (T3 ends 13:15) and the MUST slack (about 2 h) are unchanged.
8. **Slip rule replaced.** "Cut the next §7.4 item per 30 min of G0 slip" cut items on lanes A–C, which frees no time
   on the check lanes, where a G0 slip lands. The new rules are:
   - T3 and T4 overflow onto idle lanes A and B;
   - the 13:15 parity deadline for SHOULD checks;
   - MUST slack up to a G0 of about 11:30;
   - an item-9-late rule;
   - an F1-overrun rule: MUST checks run first, and the cutoff is 14:20.

   The cut list was renumbered, without the two features already cut.
9. **Uncited or imprecise numbers fixed.**
   - B restamped copies (3, of which the dedupe removes 2) now cite F1 keys.
   - P2's "8–14%" cites both P24 strata.
   - The gemini-flash Wilson hi is marked arithmetic; the file reports [0, 0].
   - The combo2 count of 4,525 is limited to the one audited shard (1 of 6).
   - The two-clock and corpus-registry keys are made precise.
10. **Risks added:** the F1 overrun, the late scaffold start, and the tbench2 label conflict. The uncommitted-sources
    risk is raised to High.

**Not changed, flagged for the reviewer**
- **§1.3 is longer than C1's "one paragraph".** It is one paragraph, three bullets and a coverage paragraph.
- **F1 is tight.** The full-mode enable run's 20–45 min estimate fills its 45-minute window. The new F1-overrun rule
  bounds the damage but does not create time.
- **Some numbers in success-criteria blocks repeat earlier figures without a tag.** For example, 171/224 = 0.763 and
  147/147 restate numbers cited a few lines above in the same check block.
- **matplotlib is mentioned only as a comment.** The uncommitted `analysis/requirements.txt` now carries matplotlib
  3.11.2 as an optional, commented line for Track A's figure script. DA8 still holds: the verifier and the eval write
  SVG by hand, and the root `requirements.txt` pins only the four packages.
