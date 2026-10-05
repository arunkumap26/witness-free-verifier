# Data licence

## spoof_dataset_v1 (the release asset `spoof_dataset_v1.zip` / `spoof_dataset_v1.tar.xz`)

Licensed under the **Creative Commons Attribution 4.0 International** licence (CC BY 4.0),
https://creativecommons.org/licenses/by/4.0/ .

You may share and adapt it for any purpose, including commercially, provided you give appropriate credit (cite the
repository, see the citation block in `README.md`), link to the licence, and indicate if changes were made.

It covers everything inside the asset: `spoof_v1.db`, `rows.jsonl`, `summary.json`, `detector_score.json`,
`injected_v1/`, `transcripts/` and `DATASET_README.md`. The transcripts were produced by this project's own agent
harness on synthetic tasks in a sandbox; they contain no third-party data. The two example transcripts in `examples/`
are copies of dataset files and carry the same licence.

## Third-party corpora (NOT redistributed)

The public-corpus analysis under `analysis/` (loaders, probes, notes, `analysis/out/`) measured third-party agent-trace
corpora (SWE-chat, AI Village, Who&When, Terminal-Bench 2 submissions, public Claude Code / Codex trace sets on
Hugging Face, and others listed in `analysis/CORPUS_INVENTORY.md`). Those corpora are **not** included here and keep
their own licences; fetch them from their sources under their terms. `analysis/out/` contains only aggregate
measurements derived from them.

## Code

The code is MIT licensed (`LICENSE`). `analysis/swarmds/baseline/` holds unmodified copies of the project's own
rule-based baseline (`swarm/delta.py`, `eval/score_detector.py`), under the same MIT licence.
