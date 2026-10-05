# witness-free-verifier

**Can an agent's own log prove that its tool results are real?** Coding agents record what every tool call returned,
and graders, reviewers and other agents treat that record as evidence. Nothing checks it. This repository is a
verifier that reads **only the transcript** (no host execution log, no re-execution, no second witness, no model) and,
for every tool call, returns `contradicted`, `supported` or `unconstrained`. It ships with a labelled dataset of 31,987
real and fabricated tool results and claims from a sandboxed agent swarm, and the scripts to reproduce every number
below in a few minutes on a laptop.

**Thesis.** A forged tool result has to agree with everything else the session recorded: the call order, the call's
own inputs, the files the session already read and wrote, and the token counts the model server billed. Most
forgeries break one of those, so they can be refuted from the log alone, with zero false positives on honest work.
A forgery that is coherent with all of them cannot be, and the verifier says so (`unconstrained`) instead of guessing.

## Headline results

Swarm labelled dataset, **test split** (split by session; every rule frozen on the dev split before the test split was
scored). Source: `analysis/out/swarmds/test_scores.json`, reproduced by `python scripts/score_dataset.py`.

| | fabricated tool outputs caught | honest tool outputs flagged | fabricated claims caught | honest claims flagged |
|---|---:|---:|---:|---:|
| **ours** (T0 + T1 + T3 + TC + claim provenance) | **3,778 / 5,948 (63.5%)** | **0 / 9,757** | **144 / 164 (87.8%)** | **0 / 243** |
| rule-based baseline | 368 / 5,948 (6.2%) | 0 / 9,757 | 38 / 164 (23.2%) | 0 / 243 |
| ours OR baseline (shipped union) | 4,041 / 5,948 (67.9%) | 0 / 9,757 | 145 / 164 (88.4%) | 0 / 243 |
| ours with T3 v2 rules (**post-hoc**: frozen after the v1 numbers above were seen) | 3,779 / 5,948 (63.5%) | 0 / 9,757 | 144 / 164 (87.8%) | 0 / 243 |

T3 v2 (post-hoc, `analysis/out/swarmds/test_scores_v2.json`) adds the `ack_path_mismatch` rule and a scoped pytest
rule. Most of its new catches were already caught by T1, so it lifts T3 alone from 452 to 1,047 caught but the combined
total by only 1 row (3,778 to 3,779; with the baseline, 4,041 to 4,042), still with 0 false positives. v1 stays the
default, and every other number in this README is v1.

**Soundness: 0 false positives on 179,365 honest tool calls** (every call in all 6,232 honest transcripts, both
splits, every check). When ours does decide a fabricated tool output it is right 3,778 times out of 3,779; the other
2,169 get an honest abstention (`unconstrained`), not a wrong answer.

Recall by kind of fabrication (test split):

| spoof_class | n | ours | baseline | union | caught by |
|---|---:|---:|---:|---:|---|
| injected_I-struct (turn deleted / re-parented) | 780 | **1.000** | 0.000 | 1.000 | T0 structural |
| injected_I-recompute | 744 | **0.999** | 0.000 | 0.999 | T1 recompute |
| injected_I-state (listing / file state edited) | 411 | **0.900** | 0.000 | 0.900 | T3 shadow state, T1 |
| injected_I-launder | 339 | **0.785** | 0.000 | 0.785 | T1, TC, T3 |
| injected_I-forge | 279 | **0.659** | 0.000 | 0.659 | TC token conservation |
| injected_I-grammar | 780 | **0.613** | 0.195 | 0.776 | T1, TC |
| tiered_easy / medium / hard (model-written forgeries) | 507 / 484 / 474 | **0.442 / 0.442 / 0.430** | 0.075 / 0.105 / 0.082 | 0.491 / 0.496 / 0.466 | T1, TC |
| counterfactual (model wrote the output without running it) | 1,149 | **0.274** | 0.077 | 0.333 | TC, T1 |
| mode_claim_unperformed_step (claimed a step never run) | 58 | **1.000** | 0.103 | 1.000 | claim provenance |
| mode_claim_prompted | 44 | **1.000** | 0.000 | 1.000 | claim provenance |
| fabricated_line_count | 20 | **0.850** | 0.900 | 0.900 | claim provenance |
| fabricated_digest | 14 | **0.857** | 0.857 | 0.857 | claim provenance |
| chore_answer (published answer no command produced) | 7 | **0.857** | 0.000 | 0.857 | claim provenance |

Full per-stratum tables (source, unit, instructed_to_lie, consistency, difficulty) and the dev split:
`analysis/SWARM_DATASET_RESULTS.md`, `analysis/out/swarmds/test_tables.md`.

### What "the baseline" is

The **rule-based baseline** is the witness-free oracle set that was built and validated together with the dataset:
`swarm/delta.py` (output-grammar rules such as "`head -n 5` cannot return 7 lines", self-consistency rules such as
"`Exit code 0` beside an uncaught traceback", and digest-provenance rules such as "a digest the agent never computed
for that file") run through `eval/score_detector.py:detect` on each row's claimed output. It reads the claimed output
plus the session's digest provenance and never the real output. It is vendored unmodified in
`analysis/swarmds/baseline/` (sha256 in `PROVENANCE.json`) and replayed row by row by the same scorer. Over all rows the
replay gives 820 true positives and 1 false positive, the same counts as the dataset's own `detector_score.json`.
The Claude-as-a-judge comparison is a second, model-based baseline (next section).

### How the fabrications are caught

Each check asks whether the recorded result is consistent with something else in the same log that the forger did
not change:

* **T0 structural** (`verifier/checks/structural.py`): the record is structurally possible for the harness. Every
  result has its call, ids are unique, the uuid chain is linear, turn numbers are contiguous, timestamps never go
  backwards. Catches deleted, re-parented or spliced turns.
* **T1 recompute** (`verifier/checks/recompute.py`): recompute the result from the call's own inputs and from content
  the session already saw (`echo`, arithmetic, `wc -l`/`head`/`cat`/`sha256sum` of a known file, Write/Submit
  acknowledgements, `Exit code N` headers, pytest summaries vs their own per-test lines, pytest re-runs with nothing
  changed).
* **T3 shadow state** (`verifier/checks/shadow_state.py`): replay the file system state the session itself built up.
  A listing that omits a file the session later reads (and never created), a read that disagrees with what it last
  wrote, `git status` flipping with no edit in between.
* **TC token conservation** (`verifier/checks/token_conservation.py`): the model server bills input tokens for
  everything it was shown. A tool result whose text is far smaller or larger than the tokens billed for it was not
  the text the model saw.
* **Claim provenance** (`verifier/checks/claims.py`): a published claim ("Mode: agent", "file has 8 lines",
  "sha256: ...", "the answer is X") must trace to an output the agent's own commands produced.

The combined verdict is `contradicted` if any check contradicts, `supported` if T1, T3 or claim provenance vouches for
the content, else `unconstrained`. Diagrams: [`analysis/FLOWCHARTS.md`](analysis/FLOWCHARTS.md) (renders on GitHub)
and `analysis/flowcharts.html` (open in a browser).

## Ours vs Claude as a judge

We gave Claude Opus 5.5 the same evidence for a stratified sample of 120 **test-split** rows: 60 honest and 60
spoofed, covering every injected class, every tiered difficulty, counterfactuals, fabricated claims and the honest
"trap" claims. Claude read blinded text renderings of the session views our checks read: no labels, no ids and no
real outputs. It ran as subagents that could only read their own batch file, 5 items per call, and returned
`contradicted` / `supported` / `unconstrained` with a one-sentence reason. Full method, every disagreement and
caveats: [`analysis/CLAUDE_JUDGE_COMPARISON.md`](analysis/CLAUDE_JUDGE_COMPARISON.md). Source:
`analysis/out/claude_judge/compare.json`, reproduced by
`python -m analysis.probes.claude_judge_compare --data dataset`.

| same 120 rows | honest flagged (FP) | spoofed caught | recall (Wilson 95%) | spoofed passed as genuine | right when it decides |
|---|---:|---:|---:|---:|---:|
| Claude Opus 5.5 as judge | 0 / 60 | 52 / 60 | 86.7% (75.8-93.1%) | 7 | 109 / 116 |
| **ours** (frozen v1; T3 v2 identical on these rows) | 0 / 60 | 39 / 60 | 65.0% (52.4-75.8%) | **0** | **48 / 48** |
| rule-based baseline | 0 / 60 | 10 / 60 | 16.7% (9.3-28.0%) | 49 | n/a (never abstains) |
| ours OR baseline (shipped union) | 0 / 60 | 43 / 60 | 71.7% (59.2-81.5%) | 17 | n/a |
| **ours OR Claude** (combination, not pre-registered) | **0 / 60** | **60 / 60** | **100% (94.0-100%)** | **0** | 117 / 117 |

What this shows:

* **On this subset, Claude alone catches more than our checks alone.** Claude does better on forgeries that are
  semantically wrong but structurally clean:

  | class | Claude | ours |
  |---|---:|---:|
  | counterfactual | 6/6 | 1/6 |
  | tiered | 12/12 | 7/12 |
  | injected I-grammar | 6/6 | 1/6 |
  | injected I-forge | 6/6 | 3/6 |

  It traces program logic, compares a result with earlier runs of the same command, and notices when a tool
  returns the wrong kind of output.
* **Our checks are never wrong when they decide, and they catch what Claude misses.** Claude passed 7 spoofed rows
  as genuine and abstained on 1. Ours caught all 8:
  * All six injected I-struct rows: the tool call's own turn was deleted from the log, which T0 flags as
    `orphan_result`.
    Claude judged the (real) content plausible.
  * Two I-launder rows: the `Exit code 1` header was stripped (T1 `exit_code`).
* **Together they caught everything:** 60 of 60 spoofed rows, 0 of 60 honest rows flagged. Running ours first and
  asking Claude only where ours abstains gives the same result. That needed Claude on 72 of these 120 rows. On the
  whole test split ours abstains on 66% of rows, so in practice ours replaces about a third of the judge calls.
* **Soundness evidence is not comparable.** Claude's 0 false positives on 60 honest rows bounds its false-positive
  rate only below 6% (95%). Ours has 0 false positives on all 179,365 honest tool calls in the dataset, with no
  model and no API cost.

Caveats: n = 120, and the subset is balanced 50/50 rather than at the natural base rate (precision here does not
transfer). The positives are synthetic or instructed. The judge used other items in its 5-item batch as context.
There was one judge run, with no repeats or confidences.

## Quickstart

Python 3.9 or newer (tested: 3.11 end to end; 3.12 and 3.14 for verify.py). No packages, no GPU, no API key.

```bash
git clone https://github.com/arunkumap26/witness-free-verifier.git
cd witness-free-verifier
python -m venv .venv
source .venv/bin/activate            # Windows cmd: .venv\Scripts\activate   Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt      # stdlib-only core: installs nothing
python scripts/verify.py examples/tampered.jsonl
python scripts/download_dataset.py
python scripts/score_dataset.py
```

What you should see (captured from a fresh copy on Windows 11, Python 3.11.9; timings from that run: venv 2.8 s,
pip 1.2 s, verify 0.1 s, download + extract 11.4 s from a local mirror, score 131.5 s).

`python scripts/verify.py examples/tampered.jsonl` (exit code 1). The tampered copy's `ls` hides `configs/web.ini`,
which the agent reads two turns later; T3 catches the listing:

```
examples/tampered.jsonl  (session b1_census-s04-045, 12 turns, 5 tool calls)

    # turn  tool     input                                  verdict       check  reason
    1    2  Read     /workspace/TASK.md                     UNCONSTRAINED -      no check could decide: T1 abstain:format_held_read_numbering, T3 abstain:no_constraint
    2    4  Bash     ls -la /workspace/configs/             CONTRADICTED  T3     T3 violation:presence_after_absence (conflicts with call #3): a path shown absent here is present later, and nothing in between created it
    3    6  Read     /workspace/configs/web.ini             UNCONSTRAINED -      no check could decide: T1 abstain:format_held_read_numbering, T3 abstain:no_constraint
    4    9  Write    /workspace/ANSWER.txt                  SUPPORTED     T1     T1 ok:ack_path
    5   11  Submit   {"problem_id": "chore-04"}             SUPPORTED     T1     T1 ok:ack_id

  1 contradicted, 2 supported, 2 unconstrained  ->  CONTRADICTED (exit 1)
```

`python scripts/verify.py examples/honest.jsonl` (the untouched session, exit code 0) ends with
`0 contradicted, 2 supported, 3 unconstrained  ->  no contradiction found (exit 0)`.

`python scripts/download_dataset.py`:

```
downloading https://github.com/arunkumap26/witness-free-verifier/releases/download/v1.0.0/spoof_dataset_v1.tar.xz
  25.6 MB in 0s
  sha256 c630aa7c37c1ea29778caad0cdcc9b13b47451cf5d20f487b9e60fc69a514d2b  (verified)
extracting spoof_dataset_v1.tar.xz -> dataset
  12680 files in 11s; spoof_v1.db present: True; honest transcripts: 6232
done. next: python scripts/score_dataset.py
```

`python scripts/score_dataset.py` (about 2 minutes; full tables in `results/test_scores.txt`):

```
dataset: dataset (packaged layout)
scoring every row with the frozen checks and the baseline; full log -> results/score_log.txt (takes a few minutes) ...
done in 131s

SOUNDNESS: 0 false positives on 179,365 honest tool calls (6,232 honest transcripts, every check)

TEST SPLIT (rules frozen on dev)        tool outputs                      claims
  method                              caught  recall  FP       caught  recall  FP
  ours (T0+T1+T3+TC+CLM)       3,778/5,948     0.635   0    144/164     0.878   0
  rule-based baseline            368/5,948     0.062   0     38/164     0.232   0
  ours OR baseline             4,041/5,948     0.679   0    145/164     0.884   0
  (honest rows in test: 9,757 tool outputs, 243 claims)

  recall by spoof_class          ours   base  union
  injected_I-struct             1.000  0.000  1.000
  injected_I-recompute          0.999  0.000  0.999
  injected_I-state              0.900  0.000  0.900
  injected_I-launder            0.785  0.000  0.785
  injected_I-forge              0.659  0.000  0.659
  injected_I-grammar            0.613  0.195  0.776
  tiered_easy                   0.442  0.075  0.491
  tiered_medium                 0.442  0.105  0.496
  tiered_hard                   0.430  0.082  0.466
  counterfactual                0.274  0.077  0.333
  mode_claim_unperformed_step   1.000  0.103  1.000
  mode_claim_prompted           1.000  0.000  1.000
  fabricated_line_count         0.850  0.900  0.900
  fabricated_digest             0.857  0.857  0.857
  chore_answer                  0.857  0.000  0.857
  scope_substitution            0.500  0.000  0.500

matches the recorded results (analysis/out/swarmds/test_scores.json): yes

full per-stratum tables: results/test_scores.txt
```

The download above was captured from a local mirror of the release assets (`WFV_DATASET_URL`), before the GitHub
release existed, so its first line here shows the GitHub URL the script uses by default. Everything else is verbatim.
`pip install -r requirements.txt` installs nothing (it only printed pip's own upgrade notice).

Verify your own transcript: `python scripts/verify.py path/to/session.jsonl` (`--json` for machine output,
`--flagged-only` to list only contradicted calls; exit code 1 if anything is contradicted, so it can gate CI). The
input is one session as turn JSONL in the swarm / SWE-chat format described in `dataset/DATASET_README.md`.

## The dataset

`spoof_dataset_v1`, CC BY 4.0, attached to the [v1.0.0 release](https://github.com/arunkumap26/witness-free-verifier/releases/tag/v1.0.0)
and fetched by `scripts/download_dataset.py` (it downloads the `.tar.xz` and checks its sha256).
Sizes, hashes, the compression comparison and per-table counts: `DATASET_MANIFEST.json`.

| asset | size | sha256 | notes |
|---|---:|---|---|
| `spoof_dataset_v1.tar.xz` | 25.6 MB | `c630aa7c37c1ea29778caad0cdcc9b13b47451cf5d20f487b9e60fc69a514d2b` | tar + xz -9e; smallest; `tar -xJf` or the script |
| `spoof_dataset_v1_db.zip` + `spoof_dataset_v1_transcripts.zip` | 10.6 + 80.8 MB | `194d2a83…c590` / `8ce3e99f…e7` | plain zips for unzip/Explorer; same db and transcripts, no `rows.jsonl` (only the rule-baseline column needs it); extract each with `python scripts/download_dataset.py --file <zip>` |

The `.tar.xz` unpacks to 12,680 files, 735.9 MB (checked byte for byte against the source). It is 73%
smaller than a zip of the same files because tampered transcripts sit next to their honest originals and xz's 64 MiB window deduplicates them; a
zip compresses each file alone (Python deflate-9: 97.5 MB in 12 s; 7-Zip ultra Deflate: 94.2 MB in 312 s; xz -9e: 25.6
MB in 240 s single-threaded, 25.8 MB in 122 s multi-threaded).

Contents: `spoof_v1.db` (SQLite; `v_blind` is what a verifier may see, `v_answers` is the key, joined only for
scoring), `rows.jsonl`, `injected_v1/` (the tampered transcripts), `transcripts/<block>/` (all 6,232 honest
transcripts) and `DATASET_README.md` (schema, protocol, pitfalls, known label defects). Manual install: `tar -xJf spoof_dataset_v1.tar.xz` in the
repository root, which creates `./dataset/`; or put it anywhere and pass `--data <dir>` or set
`WFV_DATA=<dir>`.

## Repository layout

```
scripts/            verify.py, download_dataset.py, score_dataset.py (the three entry points; stdlib only)
examples/           honest.jsonl and tampered.jsonl: the same session before and after an I-state edit
verifier/checks/    the checks: structural (T0), recompute (T1), shadow_state (T3), token_conservation (TC), claims
verifier/           the wider verifier package (IR, loaders, CLI, composition; needs requirements-analysis.txt)
analysis/swarmds/   dataset access (data.py), scorer (score.py), frozen rules (frozen_*.json), dev_*.py tuning
                    scripts (dev split only), baseline/ (vendored rule-based baseline)
analysis/out/       every recorded result (JSON / TXT / MD / figures); swarmds/ is the dataset evaluation
analysis/*.md       the research record: FINDINGS, DESIGN, FLOWCHARTS, SWARM_DATASET_RESULTS, MORNING_BRIEF, PREREG*
analysis/{lib,loaders,probes,notes}   the public-corpus analysis (phases A to E)
eval/               run_eval.py / attacks.py / metrics.py: the public-corpus eval harness (seeded attack battery;
                    needs requirements-analysis.txt and the corpora)
tests/              unit tests. Stdlib-only: python -m unittest tests.test_structural tests.test_swarm_profile
                    (the rest need requirements-analysis.txt)
```

## What it cannot do

* **A coherent forgery passes.** A fabricated result that is consistent with the call order, the inputs, the file
  state and the billed token counts is `unconstrained`. On the test split that is 2,169 of 5,948 fabricated tool
  outputs, mostly model-written forgeries of commands whose output nothing else in the log constrains. This is the
  limit of witness-free checking, not a tuning gap.
* **The positives are synthetic or instructed.** Injected rows were written by a regex; tiered and counterfactual
  rows by a model told to forge. They measure detection, not how often agents fabricate on their own. The rules were
  developed on dev rows of the same generators, so expect lower recall on other forgers.
* **The rules are harness-specific.** T0's invariants and T1's acknowledgement formats are those of the swarm
  harness; on other harnesses T0 abstains (`abstain:unvalidated_harness`) rather than guess. Each new harness needs its
  own honest-population soundness pass before its rules are trusted.
* **The strongest clock needs Anthropic request ids.** The public-corpus work's best signal (bracketing a tool call
  between provider request ids, `analysis/DESIGN.md`) needs `req_` ids that only Claude Code talking to Anthropic
  records (5 of 21 corpora), and the id layout is undocumented.
* **TC needs usage counts.** Token conservation abstains when the transcript has no per-response token usage.

## Reproducing the full public-corpus analysis

`analysis/` also holds the earlier measurement work on 21 public and private agent-trace corpora (phases A to E,
`analysis/FINDINGS.md`, `analysis/MORNING_BRIEF.md`). Re-running it needs `pip install -r requirements-analysis.txt`
(numpy, scipy, pandas, pyarrow) and the third-party corpora themselves, which are **not** shipped: fetch them from
their sources (`analysis/CORPUS_INVENTORY.md` lists each with its licence), point `SWARMS_DATA` at the directory that
holds them, then run the loaders (`analysis/loaders/load_<corpus>.py`) and probes (`analysis/probes/`). The recorded
outputs are in `analysis/out/`.

## Licences

* Code: MIT (`LICENSE`).
* `spoof_dataset_v1` and `examples/`: CC BY 4.0 (`DATA_LICENSE.md`).
* Third-party corpora used in the public-corpus analysis keep their own licences and are **not** redistributed;
  `analysis/out/` holds aggregate measurements only.

## Citation

```bibtex
@misc{witness_free_verifier_2026,
  title        = {Witness-free verification of agent tool-call results},
  author       = {Arunkumar, Prathik},
  year         = {2026},
  howpublished = {\url{https://github.com/arunkumap26/witness-free-verifier}},
  note         = {Code (MIT) and the spoof\_dataset\_v1 labelled dataset (CC BY 4.0)}
}
```
