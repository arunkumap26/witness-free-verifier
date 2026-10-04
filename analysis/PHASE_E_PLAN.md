# Phase E execution plan

Brief: `analysis/PHASE_E_PROMPT.md` (verbatim). Rules: `analysis/PROBE_PROMPT.md` + `analysis/README.md`. Starts after Phase D (`wf_614e118e-d72`) completes.

## Fixed decisions
- **Scope.** Public corpora only: swechat (pinned raw), cc_local (private: aggregates only), aiv_cc, aiv_cu, whowhen, collusion-wiki and urlquery (external witnesses), plus anything B5 downloads that passes the field audit. Nothing that touches the Qwen swarm: `swarm/`, `data/swarm/`, `.claude/worktrees/swarm`, `ops/state/swarm`. No new agent transcripts are generated.
- **Splits** (`analysis/probes/phase_e_split.py`, committed before any Phase E measurement):
  - A: Phase A and calibration only. B: Phase B; Phase C also read it.
  - **E**: Phase E re-measurement and new candidates. Fresh: no earlier phase read it. swechat 1,825, aiv_cu 2,000.
  - **H**: held-out for the Track C eval. Manifest only, ids hashed in `analysis/HELDOUT_MANIFEST.json`. swechat 1,825, aiv_cu 2,000. Nothing reads H during tuning.
  - cc_local, aiv_cc and whowhen have no E or H; A and B used all of them.
- **Pre-registration.** `analysis/PREREG_E.md` + `analysis/prereg_e.json` fix thresholds, kill tests and verdict rules for A1 (second pass), N1–N5 and the N7 attack battery. Calibration uses split A only. The orchestrator commits it before any E or B measurement for these items. Verdicts are reported on B and E separately; E is the replication.
- **Concurrency and fallback.** At most 8 concurrent agents in total: Track A pool 4 + Track B pool 4. Track C gets pool 8 once A and B finish. Every `agent()` call goes through a wrapper: if it returns null or throws (overload or terminal API error), it retries once with `model: 'sonnet'` and logs the fallback.
- **Commits.** Agents never commit. The orchestrator commits between workflows.
- **Track C location.** The scaffold lives on `div/analysis`: package `verifier/`, which matches SCOPE.md's `verifier.verify_session` contract, plus `eval/run_eval.py`. CLAUDE.md reserves `eval/` changes on `main` for deliberate daytime work, so merging to `main` is a morning human decision. The morning brief flags it.
- **Downloads (B5).** Public, research-permitting licences only. No gated datasets: those need a human to accept terms, so they get listed instead. Cap 5 GB per corpus and 25 GB total; anything bigger is listed for a human decision. Destination is `data/<name>/` (append-only). Downloaded code is never executed.

## Workflows
| # | Workflow | Pool | Contents | Depends on |
|---|---|---|---|---|
| WA1 | Track A prep | 4 | A0 DECISION_TABLE.md; build swechat_E / aiv_cu_E caches; PREREG_E author | Phase D |
| WB | Track B | 4 | B4 inventory (request-id column first); B2 ×3 + synth/skeptic; B1 ×4 angles + synth; B3 ×3; B5 ×5 source groups; B6; B7; PRIOR_ART.md + CORPUS_INVENTORY.md writers + citation skeptic | Phase D (parallel with WA1/WA2) |
| — | orchestrator commits PREREG_E | — | — | WA1 |
| WA2 | Track A measure | 4 (8 once WB finishes) | A1 follow-ups ×3 + surviving-candidate re-measures; N1–N5; N7 attack library then per-mechanism recall; N6 grid assembly + gap fills; SECOND_PASS.md | PREREG_E commit |
| WC | Track C | 8 | DESIGN.md (+ critic); scaffold modules in parallel; MORNING_BRIEF.md | WA2 + WB |
