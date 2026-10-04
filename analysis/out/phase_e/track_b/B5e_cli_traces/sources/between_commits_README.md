# Extractor code development dataset

Reproducibility archive for "Between the Commits: Process, Error, and Claim Reliability in a Wholly AI-Authored Codebase"  (D.J. Leith, Trinity College Dublin).  

## Summary

AI coding agents write code quickly, but make mistakes often enough that their output cannot be trusted at face value.  Judging how reliable AI-driven software development actually is requires visibility into the development process itself.  To gain that visibility we need full session transcripts and code development artefacts (e.g. AI generated to-do lists) not just commit history, and also the tools to analyse that data. The main contributions of this paper are: (i) the Extractor dataset; (ii) reusable tools that trace AI-authored Python code back to its provenance; (iii) taxonomies for instruction intent, commit provenance, and response reliability; and (iv) application of these to Extractor, to gain insight into the AI code development process.

This archive contains:

1. The Extractor dataset with full AI session transcripts, the complete commit history and AI-authored process artefacts (a running to-do list, a heuristics registry, its own limitations note) generated during the development of Extractor. Extractor is 21,000 lines of production code with a comparably sized test suite, built over 210 commits and 25 sessions from 678 user instructions. It was entirely built using Claude AI models over a period of several weeks. No code, test, or commit in its history has human authorship.

2. Two new tools that trace AI-authored code back to its provenance: (i) a control-flow-graph block decomposition traces individual code changes back to a specific user instruction, discovery, or self-correction event, (ii) a session-transcript mining tool recovers self-corrected code-generation errors from tool-use logs.  

3. The codebooks for applying three taxonomies: (i) the behavioural intent behind each user instruction, (ii) an extension of the standard Perfective/Corrective/Adaptive maintenance taxonomy to separate why a change was made from how it was worked out, (iii) the reliability of the AI's own claims to the user.  The raw categorisations/verdicts for these taxonomies when applied to the Extractor dataset.

4. Scripts and data to regenerate the plots and tables in the paper.


## Dataset

| What | Where | |
|---|---|---|
| Commits (full git history) | `reproducibility_archive/extractor_git_history/extractor_history.bundle` | 255 commits as a standalone `git clone`-able bundle |
| Commits (metadata) | `data/dataset/output/commits/commits.json` | 240 pinned commits (minus 15 excluded sibling-subproject commits) — hash/message/diff-stat records extracted as JSON, not a git repository |
| Session transcripts | `data/dataset/output/sessions/*.jsonl` | 19 sessions |
| Commit↔session linkage | `data/dataset/output/manifests/commit_session_linkage.json` | maps each commit to the session that produced it |
| Documented gaps | `data/dataset/output/manifests/lost_sessions.json` | 16 sessions known to exist but not recoverable |
| Pre-dataset-window context | `data/dataset/output/prehistory/*.md` | 4 claude.ai web-chat exports from 2026-05-31–06-06, predating the pinned dataset window and the first commit (2026-06-12) — the extraction tool's actual origin material (its directory/module layout and GPB-vs-PBCodable base-class detection strategy were designed there). Included for provenance/context. |
| Project artefacts | `data/dataset/output/source_snapshot/` | `TODO.md`, `LIMITATIONS.md`, `heuristic_registry.py`, taken at the paper's pin commit |

**Commit-hash caveat.** `commits.json` is extracted from the original git repo and commits are identified by hashes from
that repo.  The git bundle is extracted from the original repo and so its commits have different hashes.  That is, the commit hashes 
in `commits.json` and `extractor_history.bundle` do not match.  The file `commit_hash_mapping.csv` (columns original_commit_hash, bundle_commit_hash) is the lookup table to convert one to the other.


## Regenerating tables and plots

Run from the extraction root. Each script reads an already-archived `data/`
checkpoint directly, so nothing needs to run first except where noted.

| Paper item | Script |
|---|---|
| fig:components-per-instruction | `python3 scripts/plots/plot_components_per_instruction.py` |
| fig:codex-taxonomy-distribution | `python3 scripts/plots/plot_tang_vs_extractor_distribution.py` |
| tab:commit-type (Commits columns) | `python3 scripts/tables/build_commit_type_table.py` |
| tab:commit-type (Code blocks columns) | `python3 scripts/tables/build_commit_type_cfg_block_table.py` |
| fig:cfg-block-size-by-category | `python3 scripts/plots/plot_block_reactive_share_by_rater.py` |
| fig:cfg-block-origin-example | `python3 scripts/cfg_analysis/cfg/plot_annotated_source_by_block.py proto/writeto.py _extract_writeto_field_numbers` |
| fig:bug-hotspot-map | `python3 scripts/plots/plot_bug_hotspot_map.py` |
| fig:churn-composition-histogram | `python3 scripts/plots/plot_churn_composition_histogram.py` |
| tab:selfcorrect | `python3 scripts/precommit_defect_census/build_results_csv.py` then `python3 scripts/tables/build_selfcorrect_table.py` |
| tab:response-reliability | `python3 scripts/tables/build_response_reliability_table.py` |
| fig:category-distribution | `python3 scripts/plots/plot_category_distribution.py` |
| fig:error-count-per-response | `python3 scripts/plots/plot_error_count_per_response_678.py` |

Two of the rows above read a pre-computed snapshot that can optionally be
re-derived from scratch instead of used as-is:

- `plot_bug_hotspot_map.py`/`plot_churn_composition_histogram.py` read
  `data/bug_fix_churn_per_block.csv` directly. To re-derive it, run
  `python3 scripts/cfg_analysis/cfg/bug_fix_churn_analysis.py` and copy its
  output over that path.
- `build_commit_type_cfg_block_table.py`/`plot_block_reactive_share_by_
  rater.py` read `data/cfg_block_categories_by_rater.csv` directly. To
  re-derive it, run `python3 scripts/cfg_analysis/cfg/categorize_blocks.py`
  and copy its output (`categorize_blocks.csv`) over that path.

## Regenerating results

### Types of instruction given

The instruction components are categorised using an LLM with codebook in
`scripts/instruction_taxonomy/instruction_codebook.md`.  

The full instructions and their associated context are in master_pool.csv (scripts/instruction_taxonomy/master_pool.csv, 
columns are: idx, session, text, prev_instruction, next_instruction, prev_response, source_file, 
source_line).  The instruction components are in decomposed_components_full.csv, decomposed_excluded_a/b.csv and decomposed_excluded_missing4.csv (columns are: idx, component_num, component_text, no labels).  The components in decomposed_excluded_a/b.csv and decomposed_excluded_missing4.csv are the ones used when constructing the codebook, decomposed_components_full.csv is the held out set.

The instruction component categorisation used in the paper is in `data/instruction_taxonomy_components.csv`. 

### Triggers for code development: Commit analysis

The commits are categorised using an LLM with the codebook in
`scripts/commit_type_taxonomy/commit_taxonomy_codebook.md`.

The commits, with their message/diff, are in extractor_git_history/extractor_history.bundle.

The commit classifications used in the paper are in commit_type_classification_by_rater_full.csv.

### Triggers for code development: Code block analysis

To regenerate the code blocks (data/cfg_report.json) use:

```
mkdir -p scripts/cfg_analysis/scratch
git clone reproducibility_archive/extractor_git_history/extractor_history.bundle \
    scripts/cfg_analysis/scratch/gt_worktree_dfff6a3
cd scripts/cfg_analysis/scratch/gt_worktree_dfff6a3
git checkout paper-pin-dfff6a3
cd ../../cfg
python3 build_cfg_report.py all
cp cfg_report.json ../../../data/cfg_report.json
```

This clones git bundle extractor_git_history/extractor_history.bundle, then runs build_cfg_report.py (which partitions each function's AST into CFG basic blocks (cfg_builder.py) and traces each block's origin commit + churn history via git log -L (git_tracer.py).).  The script outputs cfg_report.json which contains each code block and its churn_commits list: every later commit that touched that block, oldest-first.

To categorise the code blocks then use:

```
python3 categorize_blocks.py
cp categorize_blocks.csv ../../../data/cfg_block_categories_by_rater.csv
cd ../../..
```

### Code churn

To regenerate fig:bug-hotspot-map and fig:churn-composition-histogram's
data use:

```
cd scripts/cfg_analysis/cfg
python3 bug_fix_churn_analysis.py
cp bug_fix_churn_per_block.csv ../../../data/bug_fix_churn_per_block.csv
cd ../../..
```

This reads data/cfg_report.json (the code blocks and their churn history) and
scripts/commit_type_taxonomy/commit_type_classification_by_rater_full.csv (for Codex's 
current commit categories).  The script outputs bug_fix_churn_per_block.csv.

### Reliability of Claude code generation

To regenerate the self-correction episodes (a pytest FAIL, followed by edits, then a later PASS on the same target within the same session) run:

```
python3 scripts/precommit_defect_census/scan_selfcorrect.py 
```

(the session transcripts are read from data/dataset/output/sessions/).  It outputs a JSON file (e.g. raw_scan_june_window.json) listing, per session, its pytest-run/commit/edit counts plus a list of candidate episodes — each a FAIL→PASS pair with the two event indices, edits/commits between them, test targets, and pytest output snippets.

The episodes are categorised using an LLM with the codebook in `scripts/precommit_defect_census/selfcorrect_verdict_codebook.md`

### Reliability of Claude user interactions

The response components are decomposed and categorised using an LLM with instructions in scripts/response_reliability/response_population_678/decompose_instructions.md and categorize_instructions.md.  The raw responses are in data/full_response_dataset_678.csv. The component classifications used in the paper are in data/response_reliability_components_678.csv.

Each component is then scored against gathered evidence for a verdict using score_instructions.md (Claude) / codex_score_instructions.md (Codex). This step is not reproducible from this archive — the per-response evidence bundles it scores against (grep/git-log results pinned to specific commits, plus session-transcript references) aren't included.

## Archive contents

- **`apple_protobuf_extractor_dataset.zip`** — the archive itself. Every
  entry is zipped at its real path relative to the extraction root, so extracting over 
  an empty directory reproduces a
  working layout: the scripts above run unmodified against the data
  sitting next to them, no path changes needed. 
- **`manifest.json`** — one entry per archived file (`path`, `size_bytes`,
  `sha256`), plus archive-level metadata (`archive_sha256`,
  `archive_size_bytes`, `file_count`, `total_uncompressed_bytes`) for
  integrity verification.

## Verifying integrity

```python
import hashlib, json, zipfile

manifest = json.load(open("manifest.json"))
assert hashlib.sha256(open("apple_protobuf_extractor_dataset.zip", "rb").read()).hexdigest() \
    == manifest["archive_sha256"]

with zipfile.ZipFile("apple_protobuf_extractor_dataset.zip") as zf:
    for entry in manifest["files"]:
        assert hashlib.sha256(zf.read(entry["path"])).hexdigest() == entry["sha256"]
```
