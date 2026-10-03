# Swarms hackathon workspace

Day: you orchestrate in the Claude desktop app, one session per division worktree.
Night: `ops/orchestrate.py` orchestrates. It's deterministic Python that makes every
keep/reject decision; Claude sessions only propose changes.

## One-time setup
1. In a terminal: `claude`, then `/login`. The terminal CLI logs in separately from the desktop app,
   and every overnight session uses the terminal CLI.
2. Fill in `MISSION.md`. Preflight refuses to start until you do.
3. Make `eval/core.py` real (`run_once`). Nothing runs overnight until it prints a headline.
4. Make `swarm/run.py` real (`load_items`, `process`). `python -m swarm.run --smoke --out ops/state/swarm/smoke` must pass.
5. Commit both on `main`, then `python ops/orchestrate.py setup` to create the worktrees.

## Daily rhythm
| When | What |
|---|---|
| Morning | `/morning`: overnight summary, critic review of each division's commits, merge recommendations |
| Day | One desktop session per division, opened on `.claude/worktrees/<div>`. `/plan <div>` to fill a queue with you reviewing it, `/next <div>` to run one task interactively, `/status` any time |
| Evening | Merge `main` changes you want the loops to see. Run `/fewer-permission-prompts` so the overnight allow-list covers what the day actually used |
| Bed | `python ops/orchestrate.py preflight core` and `... preflight swarm`, then one Windows Terminal tab each: `python ops/orchestrate.py run core` / `run swarm` |
| Stop | `touch ops/state/STOP.core` (or `STOP.all`). The loop exits at its next check |

## What the night loops do
- **core (climb):** take the next task, run a fresh `claude -p --agent implementer` in the worktree, commit,
  run the **frozen** eval snapshot, keep if the headline is no worse than best (within the eval's stdev),
  otherwise `git reset`. Two failed attempts mark a task `[!]` blocked. When the queue empties, a fresh
  Opus planner session refills it (max 3 times a night).
- **swarm (tend):** run the pipeline as its own process. Every 20 min check its progress file. On crash,
  hang, or failed validation: stop it, run a fresh `--agent mechanic` session, keep the fix only if
  `--smoke` passes, restart with `--resume`. The same failure 4 times in a row halts the loop.
- **Both:** usage limits mean sleep and retry, not a failure. A 401 means log in again, and the loop halts with an
  alert. Three real failures in a row halt the loop. Halts land in `ops/state/ALERTS.md`.

## Layout
- `ops/orchestrate.py`: the orchestrator (`setup | preflight | run | plan | status | paths`)
- `ops/config.toml`: divisions, models, budgets, timings
- `ops/prompts/`: what each overnight session is told
- `ops/overnight.settings.json`: extra deny rules applied only to overnight sessions
- `ops/state/<div>/`: queue, journal, inbox, logs (gitignored)
- `.claude/agents/`: planner (opus), implementer and mechanic (sonnet), evaluator, critic (opus), scout (haiku)
- `eval/core.py`, `eval/swarm.py`: the judges. Changed by day, on main, deliberately
