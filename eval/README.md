# eval/: the frozen judge for the witness-free verifier

The plan of record is `analysis/DESIGN.md` section 5. This directory holds the eval scaffold:

| File | What it does |
|---|---|
| `run_eval.py` | Entry point. Loads a pack, runs the honest pass and the seeded attack pass through `verifier.verify_session`, computes the metrics, writes a report, and prints **one JSON object** on the last stdout line |
| `attacks.py` | A frozen port of the pre-registered N7 attack battery (`prereg_e.json` `n7_attack_battery`) on IR DataFrames: verbatim copies of the injectors and the probes' target and donor rules, plus `plan()` / `apply()` / `to_labels()` |
| `metrics.py` | Per-session verdict summaries and every DESIGN.md 5.5 table: FPR, recall, ADR, localization, coverage, the transfer grid, disagreement, gates, labeled-corpus joins. Contains vendored copies of `wilson` and `cluster_rate` |
| `core.py` | The existing contract file. It is **not modified** here. Wiring it to `run_eval` is a daytime change on `main` (see "Orchestrator wiring") |
| `swarm.py` | Another division's validator. Not touched |

Real detection checks are not part of this scaffold: they are gated on the morning review (DESIGN.md 7.3, gate G0). The
eval runs today with the verifier's reference check, `ref_result_present`. A reference check never decides a composed
verdict, so every headline and coverage number is 0 until a deciding check is enabled. That is the correct reading.

## Running it

From the analysis worktree root (Windows, Git Bash):

```bash
PYTHONIOENCODING=utf-8 python eval/run_eval.py --checks ref_result_present            # quick E run, seeds 0,1,2
PYTHONIOENCODING=utf-8 python eval/run_eval.py --units glm_tb21,pub_codex --procs 1   # small development smoke run
PYTHONIOENCODING=utf-8 python eval/run_eval.py --mode full --checks id_bracket,...     # enable run (DESIGN 5.3; long)
python -m unittest tests.test_eval -v                                                  # the eval's tests
```

Flags (DESIGN.md 5.1, plus development options):

| Flag | Default | Meaning |
|---|---|---|
| `--repo PATH` | `.` | The checkout whose `verifier/` is scored |
| `--split E\|H` | `E` | `H` is the held-out read. It needs `--final --freeze SHA` |
| `--mode quick\|full` | `quick` | `full` runs the whole prereg grid on E: every ported attack and parameter, up to 500 sessions per cell in N7 order, seed 0 |
| `--seeds 0,1,2` (or `0 1 2`) | the config's seeds | The headline is the mean of the per-seed values; `stdev` is their population stdev |
| `--checks a,b` | the verifier's `ENABLED_CHECKS` | Passed through to `verify_session(checks=...)`. `ENABLED_CHECKS` is `()` until gate G0 |
| `--labeled DIR` | none | A labeled corpus (DESIGN.md 3.4). See "Labeled-corpus hook" |
| `--final --freeze SHA` | off | The only way to read H (see "Held-out split") |
| `--procs N` | `min(8, cpus)` | Worker processes (spawn) |
| `--pack DIR` | lookup | Read this pack: the official layout or the per-unit layout |
| `--limit N`, `--units a,b` | off | Development smoke runs: the first N pack sessions per unit, or a subset of units |
| `--report-dir DIR` | `<MAIN>/ops/state/eval/reports` | Where the report goes. Use `reports/eval` for a committed day run |
| `--cache DIR`, `--devpack-root DIR` | found | The IR caches a dev pack is built from, and where dev packs are cached |

## Output contract (what the orchestrator reads)

The last stdout line is one JSON object. Progress goes to stderr, and anything the verifier prints during a call is
redirected to stderr as well.

```json
{"ok": true, "headline": 0.0, "stdev": 0.0, "seeds": [0, 1, 2], "split": "E", "mode": "quick", "gate": null,
 "metrics": {"adr_loc_macro": 0.0, "adr_loc_macro_exec": 0.0, "adr_loc_macro_edit": 0.0, "edit_artifact_adr_exec": 0.0,
             "fpr_session_any": 0.0, "coverage_any": 0.0, "check_errors": 0, "headline_cells": 124, "runtime_s": 70.1},
 "per_check": {"<check>": {"kind": "reference|decides", "fpr_session": {...}, "decided_calls": 0, ...}},
 "per_corpus": {"<unit>": {"n_sessions": 150, "n_calls": 18224, "fpr_session_any": 0.0, "coverage_any": 0.0}},
 "timing": {"load_s": ..., "honest_s": ..., "attack_s": ..., "metrics_s": ..., "total_s": ...},
 "report": "<report_dir>/run_eval_E_quick_<checkset_sha12>.json", "content_sha256": "..."}
```

- **`ok: false` plus `error`, exit 1** covers crashes and contract failures. Errors are named by prefix:
  - `verifier_import` and `import_isolation`;
  - `check_errors` (any `error:` verdict);
  - `ir_schema_mismatch`;
  - `missing_pack`;
  - `labeled_join` (ok share below 0.99) and `labeled_corpus_unregistered`;
  - the `freeze_*` and `h_*` guards;
  - any exception, reported as `ExceptionClass: message`.
- **A gate breach is `ok: true`, `headline: -1.0`, `gate: "<reason>"`, exit 0** (DA10). The ungated value is reported
  in `metrics.headline_ungated`. The orchestrator then rejects the candidate cleanly, without counting it toward its
  three-failure halt. Gates are `fpr_cap:<check>:<unit>` and `clean_cap`. Both caps are empty until the freeze baseline
  run writes them into `config_eval.json` (DESIGN.md 5.5).
- **Headline (DA12, DA13).** For each seed, take the ADR of the composed verifier on every headline cell, meaning every
  (unit, quick cell) pair with at least 30 eligible pack sessions. Edit cells use `flag_loc`. Exec cells use
  `flag_loc` restricted to `EXEC_CREDIT`, which is `{inline_fabrication: [inline_output_accounting]}`. The per-seed
  value is the mean over exec cells times 0.5 plus the mean over edit cells times 0.5. Reported results are per cell and
  per class; this pooled number is a climb score only.
- **The report** holds every table with its `n` and CIs:
  - honest per unit and per check × unit;
  - attack cells per seed and per check, with the seed-0 `cell_label`;
  - the transfer grid and disagreement;
  - pack metadata and the eval's own deviations.

  Its `content_sha256` excludes `timing`, and two runs on the same inputs give the same hash (tested). A sibling file,
  `honest_contradictions_<sha12>.jsonl`, lists every honest-pack contradiction as refs only, for the daytime manual
  review. cc_local appears there as aggregate counts only.

## Data: packs (DESIGN.md 5.2-5.3)

The eval scores a **pack**. A pack is a fixed, seed-independent, stratified subsample of at most 150 sessions per unit,
plus an **attack plan** in which every random choice is already resolved: target, donor text and latency, spliced id,
inserted pair, line pair, added tokens. Lookup order:

1. `--pack DIR`.
2. For `--split H`: `<MAIN>/data/eval/verifier_v1/H_pack.parquet`, built by `eval/heldout.py` after the freeze. That
   script does not exist yet.
3. The official dev pack `<MAIN>/data/eval/verifier_v1/E_pack.parquet` + `E_attack_plan.parquet` (+ optional
   `E_sidecar.parquet`, `BUILD.json`), built by `eval/heldout.py build-pack`.
4. Otherwise a **dev pack is built here** from the IR caches and cached per unit under
   `<MAIN>/ops/state/eval/devpack/E_quick_<key>/<unit>/`. The key covers the source files' size and mtime, the
   builder functions' source, `attacks.py` and the config. Sources:
   - `analysis/cache/<corpus>_E.parquet`, or `_B` for cc_local, aiv_cc and whowhen, which have no E;
   - the split ids, from `analysis/cache/samples/<corpus>_EH.json` **key "E" only** and `<corpus>.json` key "B";
   - the agentcap sessions excluded by `prereg_e.json` change_log D5 stay excluded.

   The cache directory is the first one that exists among `--cache`, `<repo>/analysis/cache`,
   `<MAIN>/.claude/worktrees/analysis/analysis/cache` and `<MAIN>/analysis/cache`. A build takes about 5 minutes once
   (most of it cc_local and swechat/claude_code). Later runs load the cached pack.

**Privacy.** A dev pack copies IR rows, including the private cc_local B rows, into
`ops/state/eval/devpack/`. That directory is gitignored runtime state on the dev box: never commit it, and never copy it
anywhere public. Reports carry cc_local only as aggregates (`private_units`).

Units are the Phase E units: `swechat/<format>`, `tbench2`, `glm_tb21`, `pub_cc_hf`, `pub_trace_commons`,
`pub_codex`, `agentcap/opencode`, `agentcap/pi`, `aiv_cu`, `aiv_cc`, `cc_local` and `whowhen`. The calibration unit
passed to the verifier follows `EVAL_CALIBRATION_UNIT`, the pre-registered D1 proxy map.

Sampling follows DESIGN.md: stratum × length tercile, `lib.sample._alloc` (vendored), and
`rng = default_rng([SEED_E, crc32("pack|<split>|<unit>")])`. One addition: the per-cell floor is
`min(5, 150 // n_cells)`, the rule `prereg_e.json` change_log D3 adopted for the same problem. Without it, tbench2's
many submission × tercile cells drew 367 sessions instead of 150.

Session draws per attack cell: `min(40, n_eligible)` sessions from a `rng_for_seed(s, attack, param, unit)` permutation.
The target is drawn with `rng_for_seed(s, attack, param, session_id)` and the donor with
`rng_for_seed(s, "donor", attack, param, session_id)`. At seed 0 these are exactly `prereg_e_common.rng_for`, so seed 0
reproduces the pre-registered target and donor draws for a session.

## The attack port (`attacks.py`)

- **Verbatim copies.** `FROZEN_COPIES` lists 61 functions and constants copied verbatim from:
  - `analysis/lib/ir.py`;
  - `analysis/probes/prereg_common.py` and `prereg_e_common.py` (every `atk_*` injector, `pick_donor`,
    `qualify_pairs`, `response_table`, `n1_key`, `error_classes`, `make_pairs`, ...);
  - the two N7 probes (`DonorIndex`, `enrich_pairs`, `thread_of`, ...).

  The copies call each other through `pc.` / `pe.` namespace shims, so their text is unchanged. `tests/test_eval.py`
  asserts that each one is source-identical to its original.
- **Why copies, not imports.** The task said to wrap the frozen injectors. DA6 requires the score path to import nothing
  from `analysis/`, because the orchestrator rejects candidates that edit `eval/` but not ones that edit `analysis/`.
  The source-identity test is how the copies are tied to the originals.
- **Target and donor rules.** These are ported from the probe half named in `ATTACKS[name].source`:
  - timing, for `time_*`, `id_*` and `insert_pair_*`;
  - content, for `sub_*`, `rewrite_consistent_k`, `reorder_*`, `delete_*`, `inline_fabrication` and `image_relabel_gui`.
- **Parity tests, run on real E sessions.** They compare against the probes' own code:
  - timing half: `UnitCtx.targets` and `inject` on swechat/claude_code;
  - content half: `run_job`'s `tamper` closure on swechat/codex and aiv_cu, captured through its `noop_only` hand-off.

  Every comparable tamper is identical.
- **Not ported:** `image_insert_screenshot`. It is listed in the report and is not a quick cell.
- **`EVAL_DEVIATIONS`.** Each one is needed to produce a valid IR frame, and none changes which event is tampered:
  - tampered frames are re-typed to the IR schema and renumbered after a deletion;
  - inserted donor rows get the session's `corpus`;
  - `inline_fabrication` writes `round(tau × chars)` into `usage_out`. The content probe passed the float to N2 as a side
    channel instead, so the N2 parity test must allow for half-token rounding.
- **Tau.** The values are frozen in `TAU` with source keys (DA19: a unit's own split-A calibration comes first) and
  are tested against those keys.

## Held-out split (DESIGN.md 5.2)

- `run_eval.py` never reads an H id list. It reads only H **packs**, which do not exist yet.
- `--split H` without `--final --freeze SHA` is refused. With them, before any H read, it checks that:
  - HEAD equals SHA;
  - `verifier/ eval/ analysis/lib analysis/loaders` have no uncommitted change;
  - every eval file it loaded equals `eval/<file>` at SHA.

  Only then does it append `{utc, sha, argv, purpose}` to `<MAIN>/reports/eval/h_access_log.jsonl` and read
  `H_pack.parquet`.
- `blind_on_H` is printed per check × unit from `config_eval.json` `h_exposure` (rule 7).
- **This path was not run.** The tests only check that it refuses: without the flags, and on a SHA mismatch, nothing
  is logged or read.

## Labeled-corpus hook (DESIGN.md 3.4, 5.8)

`--labeled DIR` takes `manifest.json` (`schema: "labeled_call/1"`), `labels.jsonl` (LabeledCall rows),
`sessions/*.parquet` (IR) or `sessions/turns/*.jsonl`, and `splits.json`.

- **`splits.json` is the split registration.** `eval/labeled.py register` is to write it; that script is not built yet.
  The hook reads only its `B`/`E` keys, and without the file it fails closed (`labeled_corpus_unregistered`).
- **What it does.** It verifies the development sessions with the same verifier and joins labels by `call_id`, or by
  `seq` when `ir_sha` matches (`metrics.join_labels`). It then reports per class: recall on `pos`, FPR on `neg`, and
  precision.
- **Gating.** The run is `ok: false` when the share of labels that join is below 0.99. The `headline` does not change;
  `metrics.labeled_recall_macro` is added beside it.
- **`--labeled` with `--split H` is refused** until the H-side tooling exists.

No labeled corpus exists today. The hook is tested on a synthetic labeled directory built from `attacks.to_labels`.

## Orchestrator wiring (a daytime change on `main`; not done here)

`ops/orchestrate.py` freezes a copy of `main:eval/` into `ops/state/<div>/eval_snapshot/` and runs
`python <snapshot>/core.py --repo <worktree>` with `cwd` set to the worktree. It parses the last JSON line and keeps a
candidate when `headline >= best - tol`, where `tol` is the reported `stdev` when `tolerance = 0`. To make this eval the
judge (DESIGN.md 5.1, open item 2):

1. **Merge.** Merge `eval/run_eval.py`, `attacks.py`, `metrics.py` (and later `heldout.py`, `_stats.py`, `labeled.py`,
   `config_eval.json`) to `main`. They import each other as top-level modules, so they work from the snapshot
   directory. They find `<MAIN>` through `git rev-parse --git-common-dir`.
2. **Wire `core.py`.** Replace `main()` with `return run_eval.main(sys.argv[1:])`, and make `run_once(repo, seed)`
   return `run_eval.run_seed(repo, seed)`. `run_seed` memoizes the honest pass in-process.
3. **Build a pack by day.** Either `eval/heldout.py build-pack` writes the official pack to `data/eval/verifier_v1/`,
   or the first `run_eval.py` run builds the dev pack under `ops/state/eval/devpack/` (about 5 minutes, inside the
   15-minute `eval_timeout_min`). The core worktree has no `analysis/cache`, so the dev-pack builder falls back to the
   analysis worktree's cache.
4. **Merge `analysis/`.** The `verifier` under test imports `analysis.lib.ir` (DA1). The worktree being scored therefore
   needs `analysis/lib` on `main`, or the vendored fallback (DESIGN.md 2.4).
5. **Set the caps by day.** After the freeze baseline run, write `fpr_cap` / `CLEAN_CAP` into `config_eval.json`. Until
   then the gates are inert.

## Measured here (2026-10-04, dev box, `--checks ref_result_present`, 8 processes)

These are timings, not findings, and they are machine-dependent.

| Step | Time |
|---|---|
| Dev pack build, one time, 16 units | 268 s; cc_local 106 s and swechat/claude_code 60 s of it |
| Quick E run on the cached pack: load | 0.7 s |
| Quick E run on the cached pack: honest pass | 5.4 s |
| Quick E run on the cached pack: attack pass | 51 s |
| Quick E run on the cached pack: total | 49–57 s |

- **Pack size.** 1,381 sessions over 16 units, 124 headline cells, and 117 cells below the 30-session floor (listed in
  the report).
- **Reproducible.** Two cached runs gave the same `content_sha256`, and stdout held exactly one line.
- **Per-copy cost.** `apply()` takes about 10 ms per tampered copy (median) and the reference-check verification about
  15 ms.
- **If real checks push a run past 120 s.** Real checks will add verification time. DESIGN.md 5.3 then says to halve
  `attack_per_cell`, then `pack_per_unit`, in `config_eval.json`, as a committed daytime change and never at run time.
- **Tests.** `python -m unittest tests.test_eval` runs 35 tests in about 100 s. The parity classes need `analysis/`
  and its E caches, and are skipped elsewhere.

## Known gaps (scaffold)

- **Files owned by other lanes.** `eval/heldout.py`, `_stats.py`, `labeled.py` and `config_eval.json` are not part of
  this lane. So `wilson` and `cluster_rate` live in `metrics.py` for now; moving them is a one-line import change. The
  labeled join lives in `metrics.py`. `LabeledCall` has an identical fallback in `attacks.py` until `labeled.py` exists.
- **No sidecars in dev packs.** Checks that need `cc_numlines`, `entire_tally` or `copied_request_ids` emit
  `missing:sidecar.*` until `heldout.py` packs carry the sidecar table.
- **`NA_BLIND_BY_CONSTRUCTION` cell labels need `check_reads`.** The eval sees only `verify_session`, so it cannot read
  a check's `reads`. The labels require a frozen `check_reads` table in `config_eval.json`.
- **Stream keys must match.** Stream-level localization compares a check's `unit_id` with the prereg stream key:
  `"main"`, or the subagent's `agent_id`. A check whose stream key differs gets no stream-level localization credit.
  Check this at integration.
- **The verifier per-check cache (vcache) is not built.** It is a SHOULD item on the cut list.
