# analysis/: Signal Feasibility Probe

Measurement pass: which fabrication-detection mechanisms can the data support? Output is numbers and
observations, not a tool. Task brief: Phases A (schema recon, gate), B (four mechanism probes),
C (open-ended discovery), D (report: `FINDINGS.md`).

## Rules (apply to every script and every agent)
1. Every reported number comes from a committed script writing to a saved file under `analysis/out/`.
   No number from memory, inference, or "approximately".
2. Nulls are reported with the same prominence as hits.
3. Thresholds are set from the honest baseline **before** looking at outcomes, written to `PREREG.md`,
   and committed. Any later change is logged with before/after/reason.
4. Measurement and interpretation are separate. `analysis/out/*.json` holds raw counts only.
   Interpretation lives in `.md` files and is never written back into data files.
5. Sample, state n everywhere, give a CI or don't give the number. The resampling unit is the session
   (`lib/stats.py`).
6. When a kill criterion is met, stop that line of work and say so.
7. `data/claude-code-local` is private: outputs carry aggregates only, never content.
8. The SWE-chat mirror (`cfahlgren1`) is superseded (unredacted secrets). Use `data/swe-chat-pinned` only.

## Layout
- `lib/ir.py`: common event IR (one row per event) + failure-marker classifier. `lib/cc_jsonl.py`: Claude Code JSONL parser.
  `lib/sample.py`: disjoint stratified samples (A = Phase A, B = Phase B). `lib/stats.py`: session-clustered CIs.
- `loaders/load_<corpus>.py`: raw data -> `cache/<corpus>_{A,B}.parquet` (gitignored, regenerable) and `cache/samples/<corpus>.json`.
- `probes/`: one script per measurement; each writes `out/<name>.json`.
- `recon/`: the pre-plan dataset recon (outputs in `out/recon/`).

Corpora: `swechat` (pinned raw transcripts, all scaffolds), `cc_local`, `aiv_cc` (AI Village Claude Agent SDK stream),
`aiv_cu` (AI Village computer_use_turns), `whowhen` (Who&When, no timestamps). collusion-wiki has no agent-side tool calls.
