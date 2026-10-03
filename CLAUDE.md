# Operating rules: AI Swarm Dynamics hackathon

Read `MISSION.md` for what we're building and how it's scored.

## Layout
- Divisions live in git worktrees under `.claude/worktrees/<div>` on branches `div/<div>`:
  `core` (score-gated overnight loop), `swarm` (VLM pipeline, run-and-repair overnight loop),
  `analysis` (daytime only). Divisions share only what is committed on `main`: schemas, interfaces, `eval/`.
- Runtime state (queues, journals, logs, alerts) lives in `ops/state/` in the main checkout and is
  gitignored. `python ops/orchestrate.py paths <div>` prints the paths from any worktree.
- Datasets live in `data/` in the main checkout, gitignored.

## Non-negotiables
1. The eval is the judge. Core changes are justified by their effect on `python eval/core.py`;
   swarm output by `python eval/swarm.py`. If you can't measure it, don't do it.
2. One task per session. Finish it, then stop. Put follow-up work in `FOLLOWUPS.md`, don't do it.
3. Overnight, `eval/`, `ops/`, and `MISSION.md` are off-limits, and the harness commits, not you.
   By day we change them together, on `main`, deliberately.
4. The GPU (RTX 5070 Ti, 16 GB) belongs to the swarm pipeline overnight. The core eval must not use it.
5. Never delete or rewrite rows under `data/`. Datasets are append-only.
6. No new dependencies without adding them to requirements and re-running the eval.

## Environment (Windows)
- Shell is Git Bash. Use `python`, never `python3` (that's the Microsoft Store stub). No `make`, no `tmux`.
- Windows tools that take `/flags` (powercfg, taskkill) get mangled by Git Bash; prefix with `MSYS_NO_PATHCONV=1`.

## Working style
- Smallest change that moves the metric. There is no credit for architecture.
- Write results to files, not chat. The next session won't remember this one.
- When blocked, write the blocker to `FOLLOWUPS.md` and stop. Don't improvise around it at 3am.
