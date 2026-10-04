# DESIGN (architecture draft): the mechanism-agnostic half of DESIGN.md

Status: **draft**, written 2026-10-04 for Track C (`analysis/PHASE_E_PROMPT.md`, C1). Not committed.
This file holds every part of `DESIGN.md` that does not depend on which mechanisms survive Track A. Per-check content
is marked **`TODO-TRACK-A`** (grep for it). Nothing here selects a mechanism. Mechanism names appear only as examples
of what the interfaces must carry. They are taken from `analysis/DECISION_TABLE.md` and `analysis/prereg_e.json`.

Inputs read: `analysis/PHASE_E_PROMPT.md` (Track C), `SCOPE.md` §2, §3, §5 and §8 (plan of record and contracts),
`PROJECT_BRIEF.md` §5–9, `analysis/README.md`, `analysis/lib/ir.py`, `analysis/loaders/*.py`,
`analysis/HELDOUT_MANIFEST.json`, `analysis/FINDINGS.md` §1, `analysis/DECISION_TABLE.md`, the `analysis/PRIOR_ART.md`
verdict table, `analysis/CORPUS_INVENTORY.md` §0–1, `analysis/PREREG_E.md` §0, and `analysis/prereg_e.json`
(`n7_attack_battery`, `n6_transfer_grid`). The critic pass also read `eval/core.py`, `ops/orchestrate.py`
(`snapshot_eval`, `run_eval`, the climb keep/reject logic), `prereg_e.json` `change_log` (D1, D5, D6), the
`prereg_e_calibration_*.json` unit keys, `analysis/loaders/load_agentcap.py` `split_incident`,
`analysis/probes/phase_e_n7_timing.py` `inject` / `target_units`, `analysis/lib/stats.py` and
`analysis/out/recon/swechat_scan_pinned.json`. Every number below is copied from one of these files, which is cited
where the number appears. Hour estimates, budgets and judgment constants are labelled as such.

**Decisions this draft makes.** A reviewer may overrule any of them. Each is argued where it is made.

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
| DA11 | `contradicted` may come only from a rule that compares a field the agent controls with one it does not, with a physical bound, or with another record no honest execution could have produced beside it (§4.1 types 1–3). A distributional anomaly (a base-rate statistic over a session) is never a per-call `contradicted`; it can be a census statistic | 4.1 |
| DA12 | The climb headline weights the two threat classes **equally** and is the **mean of per-seed values** (as `eval/core.py` computes it). It is a climb score; reported results are per cell and per class | 5.5 |

**Deviations from `SCOPE.md` this draft makes** (each needs the human's sign-off at the morning merge):

| SCOPE says | This draft | Why |
|---|---|---|
| §4: SWE-chat split **by repo**, 80/20 dev/held-out; §8.2: `eval/core.py` uses held-out only | H is the Phase E session-level split (`HELDOUT_MANIFEST.json`); the climb loop is scored on E; H is read once after the freeze | H already exists and is pre-registered; scoring every climb iteration on H would tune against it (`PHASE_E_PROMPT.md` C2: "never touched during tuning"). Cost: H shares repos and operators with E (§7.5) |
| §3: "The eval imports only" `verify_session(turns)` | `verify_session` also accepts one session's IR `DataFrame` (§2.6); the eval still imports only that function | Packs are IR; turning IR into `turn` dicts would drop request ids, usage and error flags (open item 3) |
| §8.2: headline = pooled detection rate over all positives | ADR macro over fixed cells, threat classes weighted equally (DA12) | ADR charges a check for flagging the honest copy; macro stops one attack family dominating |
| §8.2: `ok: false` when the clean rate exceeds `CLEAN_CAP` | DA10 | `ops/orchestrate.py` counts `ok: false` toward its 3-consecutive-failure halt; a too-noisy candidate is a reject, not a broken harness |
| §8.1: effective coverage on the CF M2 set is the headline | Not computed here; the CF set can arrive as a labeled corpus (§3.4) | The CF set comes from the swarm, which is outside this division's scope |
| §5.7: census over the full pinned corpus | Same, but as `eval/heldout.py census --final --freeze` after the H eval run (§5.2 rule 3) | The full corpus contains H, and `verifier/` has no notion of H |
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
| harness structured copy (e.g. Claude Code `toolUseResult.numLines`, in `extra`) | harness, derived from the same tool output | It agrees with the fake text by construction. It catches post-hoc edits of the visible text only (`DECISION_TABLE.md`, rank 4: "One harness writes both renderings") |
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
  harness itself flags as substituted (`CORPUS_INVENTORY.md` §0 item 4). Whether harness-written substitutes count as
  fabrication ground truth is UNVERIFIED (`PRIOR_ART.md` §3.12), and no loader reads that corpus yet.
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
    idclock.py                     # provider id decoding (vendored from load_tbench2.id_family/id_embedded_ms + parity test)
    threads.py                     # thread/stream keys from (is_subagent, agent_id)
  loaders/
    __init__.py
    detect.py                      # sniff(path) -> Format
    files.py                       # load_file(path, fmt) -> list[Session]   (one transcript; reuses analysis/loaders parsers)
    corpora.py                     # CORPUS_ADAPTERS: IR caches by split (A/B/E only; refuses H)
    units.py                       # unit_of(corpus, session_id, stratum, fmt) -> Phase E unit (2.5); DEFAULT_CALIBRATION_BY_FORMAT
  checks/
    __init__.py                    # imports every check module; ENABLED_CHECKS tuple
    base.py                        # Check Protocol, constructors supported()/contradicted()/unconstrained(), Status
    ref_result_present.py          # reference check: proves the pipe end to end; never decides a verdict (4.8)
    calib/                         # frozen per-check calibration JSON (thresholds + provenance); TODO-TRACK-A
      build.py                     # day-time only, never imported by verifier: copies thresholds/fpr_hi/recall_lo from the
                                   #   analysis/out files named in source_files into <name>.json (4.7)
    <one module per Track A check> # TODO-TRACK-A
  registry.py                      # REGISTRY dict, @register, run_checks(session, names) -> {check: {call_key: CallVerdict}}
  compose.py                       # compose(session, by_check, kinds) -> list[Verdict]
  render/
    text.py                        # terminal table, ANSI colour, --explain
    jsonl.py                       # Verdict / session summary serialization
    html.py                        # render_session_html(): single static file, inline CSS/JS/SVG
    figures.py                     # transfer-matrix and recall-per-attack SVG/HTML from an eval report JSON
    demo.py                        # build_demo(input_dir) -> demo/index.html (input written by eval/heldout.py demo-input; 6.3)
    demo_spec.json                 # pinned demo unit + attack + seed + selection rule (6.3; TODO-TRACK-A fills the session)
  cli.py                           # argparse subcommands (6.1)

eval/                              # frozen judge (CLAUDE.md rule 3); merged to main by day (PHASE_E_PLAN.md "Track C location")
  core.py                          # existing contract file; main() delegates to run_eval.main (5.1)
  run_eval.py                      # entry point; last stdout line = ONE JSON object (eval/core.py contract); run_seed(repo, seed)
  heldout.py                       # H ids from samples/<c>_EH.json#H + manifest digest check; H cache build; pack build; access log
  attacks.py                       # frozen port of prereg_e.json n7_attack_battery on IR DataFrames (same names, same rng parts)
  metrics.py                       # FPR, recall, ADR, localization, coverage, transfer grid, disagreement
  _stats.py                        # vendored copies of analysis.lib.stats wilson/cluster_rate + Clopper-Pearson (parity test)
  labeled.py                       # labeled-corpus reader, split registration, join
  config_eval.json                 # frozen: seeds, pack dir, pack sizes, quick attack cells, unit maps, H exposure, caps (caps TODO-TRACK-A)

requirements.txt                   # repo root: numpy==2.3.5 scipy==1.17.1 pandas==3.0.5 pyarrow==25.0.1 (as analysis/requirements.txt)

tests/
  test_ir_parity.py  test_idclock_parity.py  test_turns_adapter.py  test_registry.py  test_compose.py
  test_check_purity.py  test_determinism.py  test_no_heldout_access.py  test_cli_smoke.py  test_attacks_parity.py
  test_eval_budget.py  test_eval_imports.py  test_stats_parity.py
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
| `verifier.loaders` | Raw file or IR cache → `list[Session]`. Reuses the `analysis/loaders` parsers. Knows splits A/B/E, never H | `analysis.loaders.*`, `analysis.lib.cc_jsonl`, `verifier.session` | checks, eval |
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
unit not listed calibrates as itself.

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
osworld, webarena-infinity, tracelab-uw and cli-pi-hf. They are COULD items, at 2–4 h each by B7's per-loader estimate
(`CORPUS_INVENTORY.md` §0 item 6). combo2 is the one that would bring harness-labelled substitutes (§1.4).

### 2.6 Public API (exact signatures)

```python
# verifier/api.py  (re-exported by verifier/__init__.py)
def verify_session(turns_or_events: list[dict] | pd.DataFrame, *, unit: str | None = None,
                   calibration_unit: str | None = None, checks: Sequence[str] | None = None,
                   source: dict | None = None, strict: bool = False) -> list[Verdict]:
    """SCOPE §3 contract. list[dict] = SCOPE `turn` dicts of ONE session (turns_to_events); DataFrame = IR events of ONE
    session (exactly COLUMNS; ValueError if it holds >1 session_id). unit defaults to 'turns' for turns and to
    'unknown' for frames. calibration_unit defaults to None, so statistical checks abstain (DA4) unless the caller
    names one. checks=None runs ENABLED_CHECKS. Returns one Verdict per call in call seq order ([] if no calls)."""

def verify_sessions(events: pd.DataFrame, *, unit_of: Callable[[str], str], calibration_unit_of: Callable[[str], str | None],
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
  seqs and count. Reason: on some exports they are loader artifacts. The SWE-chat conversations table orphans 18.8% of
  results, while the raw transcripts do not (`SCOPE.md` §1; `FINDINGS.md` caveat 4).
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
  in the calibration file. It is a Wilson bound, or Clopper–Pearson when the observed count
  is zero (`SCOPE.md` §8.4).
- `supported` (identity checks only): `recall_lo[unit]`, the lower 95% bound of the check's recall on its declared
  target attacks in that unit, copied from the Track A N7 output on B (§5.4). It answers: *had this call been tampered
  that way, how surely would we have said contradicted?*
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
              confidence: float | None, unit_kind="call", unit_id=None, localized=True, detail=None) -> CallVerdict
def contradicted(s: Session, call_key: str, check: Check, reason: str, evidence: Sequence[EventRef], *,
                 confidence: float | None, unit_kind="call", unit_id=None, localized=True, detail=None) -> CallVerdict
def unconstrained(s: Session, call_key: str, check: Check, reason: str, detail=None) -> CallVerdict
def all_unconstrained(s: Session, check: Check, reason: str, detail=None) -> list[CallVerdict]
def calib_for(check: Check, unit: str) -> dict | None      # frozen calib JSON slice for this unit, or None
```

Each one asserts: the reason prefix matches the verdict; `evidence` is non-empty for decided verdicts and contains at
least one `role="subject"` ref; `confidence` is in [0, 1] or None as §3.3 requires; every `seq` exists in the session;
a `localized=True` verdict cites at most `MAX_CORE` distinct seqs (§3.2); `supported()` is refused for a
`kind="statistical"` check (§4.6).

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
survives Track A, it is reported in the census and the N6 grid, not registered as a check. Each §7.1 block names which
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
                  turn_ids: dict[int, str] | None = None) -> Session          # validates, sorts, detects capabilities
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
| `usage.cache` | `usage_cache_read` not null |
| `subagent` | `is_subagent` true |
| `causal.uuid` | `uuid` and `parent_uuid` not null |
| `extra:<dotted.key>` | the parsed `extra` of ≥ 1 event has that key path (evaluated lazily; e.g. `extra:toolUseResult.numLines`) |

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
from . import ref_result_present  # noqa: F401   (+ one import line per Track A check: TODO-TRACK-A)
ENABLED_CHECKS: tuple[str, ...] = ()               # TODO-TRACK-A: the MUST/SHOULD checks; reference checks are never listed

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
  swechat Bedrock-backed calls carry none, 0 of 3,575, `CORPUS_INVENTORY.md` §1.1) → the check emits `missing:<IR
  column>` for that call.
- **Statistical check, uncalibrated unit.** `calib_for(check, session.calibration_unit)` returns None → every call is
  `abstain:uncalibrated_unit`. Thresholds are never borrowed silently across units. The cross-harness spread is itself a
  finding: "no mechanism is ALIVE in more than 2 corpora" (`DECISION_TABLE.md`, strongest finding, sentence 2).
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
   "units": {"<unit>": {"thresholds": {...}, "fpr_hi": ..., "recall_lo": ..., "n": ..., "n_sessions": ...}}}
  ```

  `thresholds` come from split A only (`PHASE_E_PLAN.md`: "Calibration uses split A only"), never from E (the climb
  loop's dev split) and never from H. `verifier/checks/calib/build.py <check>` writes the file by copying values from
  the listed Track A outputs; it asserts that no source path names H and records each source's sha256.
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
 "metrics": {"adr_loc_macro": 0.0, "adr_loc_macro_exec": 0.0, "adr_loc_macro_edit": 0.0, "fpr_session_any": 0.0,
             "coverage_any": 0.0, "check_errors": 0, "runtime_s": 0.0},
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
   - Otherwise agentcap H is kept and labelled `exposed: 14/216 (parse-level, no per-session values inspected)`.
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

Reading the full IR for E or H every run is too slow: `swechat_E.parquet` alone is 192 MB of zstd. So the eval reads a
**pack**: a fixed, seed-independent, stratified subsample per unit, built once.

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

**Quick cells** (`config_eval.json`). They are fixed in this draft, whose inputs (header) do not include the N7
recall outputs (`n7_timing.json`, `n7_content_shards/`), although those files are on disk while it is written. If the
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

That is 16 cells: 5 exec, 11 edit. A cell with no unit meeting the eligibility floor is skipped and listed.

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
| `transfer[c][u]` | `prereg_e.json` `n6_transfer_grid` cell vocabulary: ALIVE / WEAK / DEAD by the per-check rule (**TODO-TRACK-A**, from SECOND_PASS.md rules); `INSUFFICIENT_N`; `NOT_TESTABLE(<cap>)` when the capability is absent from every pack session of the unit (`n6_transfer_grid.fill_rule` 1: "a required field is absent from the unit"); `NOT_RUN(uncalibrated_unit)` | check × unit (the N6 grid, now on the frozen verifier) |
| `disagreement[x][y]` | honest calls where x says contradicted and y says supported | check pair |
| `check_errors` | count of `error:` verdicts | run |
| `labeled.*` (when `--labeled`) | per `cls`: recall on `pos`, FPR on `neg`, precision, with session-clustered CIs; `unknown` excluded but counted; `join_status` counts | class |

**Headline (DA12; a climb score, not a reported result).** For seed s, `ADR_s(cell)` is the ADR of the **composed
verifier** on that (unit, quick cell) headline cell (§5.3), with "flagged" = `flag_loc`. Then
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

`fpr_cap` and `CLEAN_CAP` are **TODO-TRACK-A**. Each is set from that check's honest upper bound on E plus a margin
fixed by day, as `SCOPE.md` §8.2 does for `CLEAN_CAP` ("baseline + 0.2 points"). Note the unit: SCOPE's clean rate is a
contradiction rate; here it is the session-level any-contradiction rate (prereg `session_flag`), which grows with session
length for per-call checks, as the prereg accepts.

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

### 5.7 Per-check success criteria (template; values TODO-TRACK-A)

Two uses of one template, never mixed:
- **Enable decision (dev, on E; B for units without E).** At the freeze, a check is enabled iff its MUST rows pass on
  E. This is the only place the criteria change what ships.
- **Confirmation (on H, once, after the freeze).** The same rows are evaluated on H and reported as PASS / FAIL beside
  the E values. A FAIL is reported, not acted on (§5.2 rule 4): the check stays in the H numbers.

```
check: <name> v<version>     kind: identity|statistical     rule type (DA11): 1|2|3     units claimed: <list>     blind_on_H: per unit
MUST   honest fpr_session, every claimed unit with >= 30 sessions: k/n, Wilson hi <= fpr_cap[c]                 [TODO-TRACK-A]
MUST   >= 1 target attack with cell_label DETECTS in >= 1 claimed unit (seed 0; recall >= 0.5, CI lo > FPR CI hi) [TODO-TRACK-A]
SHOULD coverage[c][u] >= <x> on the claimed units (from the N6 grid on E)                                      [TODO-TRACK-A]
SHOULD localization >= <y> on DETECTS cells                                                                       [TODO-TRACK-A]
FLAG   (H only) H fpr_session CI lo > E fpr_session CI hi: reported as "H disagrees with E", no change to the check
REPORT every target attack with no DETECTS cell, in the walk-through table (prereg N7 'outputs')
```

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
`pub_cc_common`) is a COULD.

**Terminal output** (shape only; check names and numbers are placeholders):

```
session 3f2a…  file:claude_code  84 calls  calibration: swechat/claude_code (borrowed by format)
capabilities: ts.ms ts.pair_distinct join.call_id request_id.decodable usage.io error.marker extra:toolUseResult.numLines
checks: <check_a> 1.0.0 (ran)   <check_b> 1.0.0 (missing:usage.cache)   <check_c> 1.0.0 (abstain:uncalibrated_unit)
 seq  time          tool   call                                   verdict         by          reason
  12  12:00:01.204  shell  pytest -q tests/test_api.py            supported       <check_a>   ok:<rule>  (conf 0.91)
  31  12:03:44.010  shell  pytest -q                              CONTRADICTED !  <check_a>   violation:<rule> (conf 0.997)  core #30 #31 #33
        <check_a.explain(cv)>  e.g. "result stamped 410 ms before the provider clock allows; tolerance 2,000 ms"
        also supported by <check_b> (conf 0.62)   <- disagreement
summary: 84 calls | contradicted 1 (localized 1, unit-level 0) | supported 23 | unconstrained 60 (screened 20, missing:request_id 3, abstain:tool_out_of_scope 37)
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

The spec:

```json
{"corpus": "swechat", "unit": "swechat/claude_code", "split": "E", "session_id": "TODO-TRACK-A",
 "attack": "TODO-TRACK-A", "param": null, "seed": 0, "checks": "enabled",
 "why_this_session": "first session by sorted session_id among the unit's E-pack sessions in the attack's seed-0 plan whose tampered copy is flag_loc by the composed verifier and whose honest copy is not flagged",
 "cell_recall_loc": "TODO-TRACK-A: k/n of that cell at seed 0, printed on the page"}
```

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
   hold.

**COULD: gallery.** `demo/gallery.html` is a grid of quick attack cells × units. Each cell shows the composed cell
label and links to a rendered example page. This makes the recall-per-attack table clickable, and it must show BLIND
cells as prominently as DETECTS cells.

### 6.4 Figures (`verifier/render/figures.py`)

`transfer_matrix_svg(report: dict) -> str` and `recall_table_html(report: dict) -> str` read the eval report JSON and
write `reports/figures/transfer_matrix.svg` and `reports/figures/recall_per_attack.html`.
- Cells carry the vocabulary label and `n` as text, and colour encodes only the label. `NOT_TESTABLE` and `NOT_RUN`
  cells are shown, never dropped (`PHASE_E_PROMPT.md` N6: "failing cells included").
- Hand-written SVG, no plotting dependency (DA8).

---

## 7. Placeholders for Track A content

Everything in this section waits for `analysis/SECOND_PASS.md`, the updated `DECISION_TABLE.md`, the N6 grid
(`analysis/out/phase_e/n6_grid.json`) and the N7 recall tables (`n7_timing.json`, `n7_content_shards/`). Where the
mechanism-agnostic part is already known, it is filled in and marked as such.

### 7.1 Per-check designs: **TODO-TRACK-A**

One block per check that survived Track A **and** cleared Track B. "Cleared" means a `PRIOR_ART.md` verdict of NOVEL or
PARTIAL for the claim the check makes. UNVERIFIED does not clear: `PRIOR_ART.md` §3.13 says "DESIGN.md must not describe
them as having cleared prior art" (rank 2 image-token ledger, rank 3 git window, N5 sort order, truncation boundary,
whitespace, output-size distribution, cold start). Such a mechanism can appear only as a COULD labelled "prior art
UNVERIFIED". A TAKEN sub-claim (for example B3.10 7a) is cited as prior art, never claimed. Required fields;
"implement the check" is not an acceptable entry:

```
### <check name>  (module verifier/checks/<name>.py, class <Name>Check)
- Justifying finding: DECISION_TABLE row <mechanism × unit> = <ALIVE/WEAK>, deciding number <k/n [CI]>, n;
  SECOND_PASS row <…> (kill attempts survived); PRIOR_ART verdict <PARTIAL/NOVEL> (<citation>)
- Protocol attributes: kind, strength, requires, reads, targets, unit_kind, calibration path; lineage (prereg id)
- Rule type (DA11): 1 field-vs-field, 2 physical bound, or 3 record-vs-record; a distributional statistic is not a check
- Soundness under the threat model (1.2 table): which agent-controlled field is compared with which field the agent
  does not control; which direction is sound (e.g. "too fast" only); which threat class (5.4) it can address
- Inputs: the Session members read (pairs columns, responses columns, clocks, extra keys)
- Algorithm: named functions with signatures, step by step; the decision rule as an inequality
- Thresholds: value, unit, provenance (file + key + split A), fixed before which outcome
- Calibration per unit: which units are calibrated (own or D1 proxy); fpr_hi (B) and recall_lo (B) source; others ->
  abstain:uncalibrated_unit (statistical) or confidence None (identity)
- H exposure: the h_exposure entry it needs in config_eval.json (5.2 rule 7)
- Complexity: O(...) and the measured ms per 100 events
- Missing-data behaviour: every reason code it can emit (missing:…, abstain:…)
- Known false-positive sources: from the Track A kill attempts (e.g. resumed/forked sessions, clock skew, truncation,
  Bedrock calls without ids), and how each is excluded or accepted
- Target attacks and expected cell labels (from N7 on B/E); attacks it is BLIND to, by construction or measured
- Success criteria: the 5.7 template, filled
- explain() wording, with one real example rendered
```

**Constraints already fixed for whatever lands here.**
- An identity check needs no thresholds; its `calib/<name>.json` holds only `fpr_hi` / `recall_lo`. A statistical check's
  thresholds come from split A only, never E (the climb loop's dev split, so FPR on E stays out of sample) and never H.
- H blindness is set in `config_eval.json` `h_exposure` (§5.2 rule 7): R3, R4 and R5 on every unit (`PREREG_E.md` §0);
  the bracket, latency and reaction-time lineages on every new-corpus unit (`prereg_e.json` change_log D6).
- `contradicted` only from rule types 1–3 (DA11). Zero-error tail (Probe 3a), round numbers and hex uniformity (Probe 4)
  are distributional: if they survive Track A they go to the census and the N6 grid, not to `ENABLED_CHECKS`.
  (`PRIOR_ART.md` §3.10 also notes the zero-error tail "can be evaded by error fabrication".)
- External-witness mechanisms are not core checks: the linked-commit patch, Write content in the committed file, and
  the wiki and urlquery clocks (`DECISION_TABLE.md` "External witness" rows). If kept at all, they are a separate
  `witness` plugin family that is excluded from witness-free metrics (COULD).
- A check built on provider request ids carries the layout limitation in its block. Coverage: the 5 of 21 corpora
  with request ids are all Claude Code to Anthropic (`CORPUS_INVENTORY.md` §0 item 1), and the id layout is
  undocumented (`PRIOR_ART.md` B2 fact row).

### 7.2 MUST / SHOULD / COULD

The agnostic rows are filled in now. Each is justified by a contract or an eval rule, not by a finding. Check rows are
**TODO-TRACK-A**, each tagged with its justifying finding. Anything without one is demoted or cut (`PHASE_E_PROMPT.md`
C1).

| Tier | Item | Justification |
|---|---|---|
| MUST | `verifier.ir` re-export + `turns` adapter + `test_ir_parity` | `SCOPE.md` §3: `verify_session(turns)` contract |
| MUST | `session/` (build_session, pairs, responses, clocks, capabilities, idclock + parity) | every check depends on it |
| MUST | `checks/base.py`, `registry.py`, `compose.py`, `ref_result_present` | `PHASE_E_PROMPT.md` C2: registry + one trivial reference check end to end |
| MUST | `loaders/` (detect, files for claude_code/codex/opencode/gemini/atif/ir/turns; corpora adapters A/B/E) | C2: loader normalizing every public corpus |
| MUST | CLI `verify` / `checks` / `inspect`, text + JSONL output, exit codes | `SCOPE.md` §2 deliverable 2 |
| MUST | `eval/run_eval.py` quick on E, `heldout.py` manifest verify + pack + attack plan, `attacks.py` port with parity test, `metrics.py`, `_stats.py` + parity, import isolation + `test_eval_imports`, `core.py` wiring, single-JSON output, ≥ 3 seeds, ≤ ~2 min | C2: `eval/run_eval.py` deterministic per seed, ≥ 3 seeds, under ~2 minutes, one JSON object; `eval/core.py` docstring: "Reads nothing an agent is allowed to edit except the code under test" |
| MUST | root `requirements.txt` | CLAUDE.md rule 6 |
| MUST | **TODO-TRACK-A**: checks whose per-check success criteria (5.7) are met on E | finding per check |
| SHOULD | `render/html.py` + `demo.py` + `demo_spec.json` | `SCOPE.md` §9 Demo 1 "must have"; `PHASE_E_PROMPT.md` C1 demo surface |
| SHOULD | `render/figures.py` (transfer matrix, recall per attack) | C2: figure generation for both |
| SHOULD | H build + `--final` run + access log | the held-out headline |
| SHOULD | `eval/labeled.py` validate/register/join | `PHASE_E_PROMPT.md` scope boundary: accept a labeled corpus later |
| SHOULD | per-check verdict cache in eval | keeps the climb loop at ~100 iterations a night (`eval/core.py` docstring) |
| SHOULD | `census` subcommand (A/B/E) + `heldout.py census` (full corpus, after `--final`) | `SCOPE.md` §5.7 |
| SHOULD | **TODO-TRACK-A** | finding per check |
| COULD | directory input (Claude Code project with subagent files) | — |
| COULD | demo gallery | — |
| COULD | loaders for openhands, miniswe, combo2 (harness-labelled substitutes, §1.4), tracelab, osworld, webarena, cli-pi-hf | `CORPUS_INVENTORY.md` §0 |
| COULD | `witness` plugin family (external-witness mechanisms) | out of the witness-free core |
| COULD | **TODO-TRACK-A** | |

### 7.3 Build order against the 15:00 CDT code freeze

The agnostic part, with **estimated** hours, is known now. Hours on check rows are **TODO-TRACK-A**.

| # | Item | Depends on | Est. h | Parallel lane |
|---|---|---|---|---|
| 1 | `verifier/ir` + `turns.py` (TURN_TO_IR, §2.6) + parity test + root `requirements.txt` | — | 0.5 | A |
| 2 | `session/` (+ idclock parity) | 1 | 1.5 | A |
| 3 | `checks/base.py` + `registry.py` + `ref_result_present` + `calib/build.py` | 2 | 0.75 | A |
| 4 | `compose.py` + `api.py` (§2.6) + `test_compose.py` | 3 | 0.5 | A |
| 5 | `loaders/` (detect, files, corpora, units) | 1 | 1.0 | B |
| 6 | CLI `verify/checks/inspect` + text + JSONL | 4, 5 | 0.75 | A |
| 7 | `eval/heldout.py` (manifest verify, E pack, attack plans, agentcap exposed-id recompute) | 8 | 1.0 | C |
| 8 | `eval/attacks.py` port on IR frames (`targets`/`plan`/`apply`) + parity test | — | 1.5 | C |
| 9 | `eval/metrics.py` + `_stats.py` + `run_eval.py` (quick, E; import isolation; gates) + `core.py` wiring + determinism, budget and import tests | 4, 7 | 1.5 | C |
| 10 | `render/html.py` + `demo.py` + `heldout.py demo-input` | 4, 7 | 1.5 | B |
| 11 | `render/figures.py` | 9 | 0.75 | B |
| 12 | `labeled.py` | 9 | 0.5 | C |
| 13 | H build-cache + build-pack + `--final` run + full-corpus census | 9, **freeze** | 0.5 (+ one-time parse time, unmeasured) | after 15:00 |
| T1… | **TODO-TRACK-A**: one row per check (design → code → calib JSON → E eval → criteria) | 3, 9 | TODO | D… |

Critical path, agnostic: 1 → 2 → 3 → 4 → 9 ≈ 4.75 h (0.5 + 1.5 + 0.75 + 0.5 + 1.5) of the 12.25 h total. The eval lane
8 → 7 (2.5 h) needs no verifier code, because the attack port works on IR frames, so it finishes before 4 does. All
hours are estimates. **Freeze rule:** at 15:00 whatever passes its 5.7 MUST criteria on E is enabled. Everything else
stays registered but out of `ENABLED_CHECKS`. Then the H `--final` run executes once, and nothing that changes verdicts
changes after it (§5.2 rule 4).

### 7.4 Cut list (in this order when behind)

Agnostic, known now:
1. demo gallery;
2. directory input;
3. per-check verdict cache (accept fewer climb iterations);
4. `census` subcommand (run census from a script instead);
5. `labeled.py` register/join (keep only `validate`; the pipe stays specified here);
6. figures as SVG (fall back to the HTML tables in the report);
7. honest/tampered toggle animation (keep two static pages).

Never cut:
- `run_eval.py` single-JSON contract;
- H manifest verification;
- the reference check;
- `unconstrained` reasons;
- the "synthetic only" footer.

**TODO-TRACK-A**: where each check sits in this order.

### 7.5 Risks

Agnostic risks, known now. Each is mitigated or accepted and documented.

| Risk | Sev. | Mitigation or acceptance |
|---|---|---|
| H leaks into tuning (the climb loop is scored on H, or a script reads it) | High | DA5: climb on E; H events only via `--final --freeze`, logged; no change after the first H read (5.2 rule 4); `test_no_heldout_access.py`; verifier has no H notion; the H pack does not exist until the freeze |
| H results fed back (a check disabled or recalibrated because it failed on H) | High | 5.2 rule 4 and 5.7: H criteria are reported, never acted on; the write-up reports the first H run |
| R3/R4/R5-type evidence already read H in Phase C; B5e read timing and request-id statistics over the full new corpora | Med | **Accepted and documented**: `blind_on_H: false` beside every affected H number, from `config_eval.json` `h_exposure` (`PREREG_E.md` §0; `prereg_e.json` change_log D6) |
| H shares repos, operators and submitting agents with E (session-level split, not `SCOPE.md` §4's repo split) | Med | **Accepted and documented** as a limitation of the H numbers; deviations table |
| The climb loop edits what judges it: `analysis/` stats or loaders imported from `--repo`, or `verifier.session` deciding attack targets | High | DA6: score path imports only `verify_session`; stats vendored in `eval/`; attacks on IR frames; plans pre-built; `test_eval_imports.py`; `run_eval` asserts module origins |
| Gate breaches halt the overnight loop (3 consecutive `ok: false`) | Med | DA10: a gate breach is `ok: true`, headline -1.0, a clean reject |
| 14 agentcap H sessions parse-exposed and not identifiable by id | Low | Recompute exactly as `load_agentcap.split_incident` does and drop if the sha matches; else keep and label (5.2 rule 5) |
| `seq` changes when a loader changes → stale labels and cached verdicts | Med | `ir_sha` on labels; loader shas in BUILD.json and pack metadata; vcache keyed by `ir_sha` and file-byte `code_sha` |
| Same `ts_kind` with different timestamp semantics across harnesses (e.g. ATIF Terminus stamps are host-after-exec; `load_tbench2.parse_atif` `sem`) | Med | DA4: statistical checks calibrate per unit and abstain elsewhere; identity checks must state their stamp assumption in 7.1 |
| Quick eval exceeds 2 min on the dev box | Med | Fixed pack sizes; halve by day; budget test; 8 processes; vcache |
| Attack port diverges from the pre-registered battery | Med | `test_attacks_parity.py` against the probe implementations at seed 0 |
| A check crashes on one odd session and blocks the climb loop | Low | **Accepted**: `check_errors > 0` → `ok=false` is intended (a crash is a bug); `--strict` for development; the error is localized in the report |
| Private or gated content leaks through html/census | High | `cc_local` render refusal; `PUBLISHABLE` set; aggregates-only census for `cc_local`; redaction before escape |
| Secrets in public corpora displayed in the demo | Med | `newcorp_common.redact` on every displayed string; loaders already redact (`CORPUS_INVENTORY.md` §2.4) |
| `verifier` depends on `analysis/` being on `main` | Med | Morning merge decision; DA1 fallback: vendor `ir.py` and `redact` behind the same re-exports (two import lines) |
| Recall on `rewrite_consistent_k` overstates execution-path detection (ids and usage are not re-minted after the shift) | Med | Reported under record editing when the deciding check reads `request_id` or `usage` (5.4) |
| Contradictions on presumed-honest public data get reported as FPs (or as fabrications) without review | Med | `honest_contradictions_*.jsonl` + manual review sample (`SCOPE.md` §5.7); neither label is asserted without review |
| Reviewers read synthetic recall as real-world detection | High | The 1.4 statement, the demo footer, per-threat-class reporting (5.4), labeled-set metrics kept separate |

**TODO-TRACK-A**: risks specific to the chosen checks. Expected kinds, to be confirmed or dropped:
- undocumented id layouts changing (`PRIOR_ART.md` B2);
- mid-session latency floor shifts (`DECISION_TABLE.md`, Probe 1 swechat/claude_code: 21/156 series);
- one repo, model or agent dominating a calibration unit (`aiv_cc` is one agent);
- truncation markers interacting with content checks.

---

### Open items for the morning (human decisions this design surfaces)

1. Merge `analysis/lib` + `analysis/loaders` to `main` with `verifier/` (DA1), or accept the vendored fallback.
2. Merge `eval/run_eval.py`, `attacks.py`, `heldout.py`, `metrics.py`, `_stats.py`, `labeled.py` and
   `config_eval.json` to `main`, and replace `eval/core.py`'s `main()` / `run_once` as in §5.1 (`PHASE_E_PLAN.md`: a
   morning decision).
3. Extend the `SCOPE.md` §3 `turn` contract with optional `request_id`, `api_msg_id`, `native_error` and `exit_code`.
   Without them, checks that need these fields will read `missing:` on any input in turn format.
4. Set `fpr_cap[check]` and `CLEAN_CAP` from the E honest bounds once Track A lands (§5.5).
5. Sign off the deviations from `SCOPE.md` listed after the decisions table (split, eval import, headline, gate
   semantics, effective coverage, census timing, `core` ids).
6. `schemas/` does not exist on `main` yet (`SCOPE.md` §3 says contracts are committed there). Commit
   `schemas/verdict.json` (JSON Schema of `Verdict.to_scope_dict`) and `schemas/labeled_call.json` with the merge.
7. Add the root `requirements.txt` (DA8) with the merge.
8. Confirm the SWE-chat HF gate terms allow publishing a tampered session before the demo page is published
   (`SCOPE.md` §2 item 6, §11).
9. Decide whether `run_eval` also scores the `SCOPE.md` §6 classes from the untracked `eval/inject.py` (§5.4).

---

### Critic changes

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
