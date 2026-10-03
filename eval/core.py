"""Core judge. The overnight loop runs a FROZEN COPY of this file against a division worktree.

Contract (the orchestrator depends on every line of this):
  python eval/core.py --repo <path-to-worktree>
  - The last line of stdout is ONE JSON object:
      {"ok": true, "headline": <float>, "stdev": <float>, "metrics": {...}, "seeds": [...]}
  - "ok": false plus "error" when the system under test crashes or its tests fail.
  - Deterministic per seed, run across >= 3 seeds so a gain can be told apart from noise.
  - Fast: a few minutes at most, or the loop gets ~20 iterations a night instead of ~100.
  - No GPU: the swarm pipeline owns the GPU overnight.
  - Reads nothing an agent is allowed to edit except the code under test in --repo.

Until run_once() is real, this exits with ok=false and preflight refuses to start the loop.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

SEEDS = [0, 1, 2]
HEADLINE = "task_completion_rate"  # rename to the metric MISSION.md names


def run_once(repo: Path, seed: int) -> dict:
    """Run the system in `repo` once with `seed` and return {metric_name: float}."""
    # TODO: import or subprocess the core system from `repo`, run it on the held-out
    # task set with this seed, and return the metrics. Keep the held-out set outside
    # the repo (or under eval/) so agents can't tune against it.
    raise NotImplementedError("wire up the real core run in eval/core.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    repo = Path(ap.parse_args().repo).resolve()
    try:
        runs = [run_once(repo, s) for s in SEEDS]
    except Exception as e:  # any failure of the system under test is a failed candidate
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}))
        return 1
    metrics = {k: statistics.mean(r[k] for r in runs) for k in runs[0]}
    print(json.dumps({
        "ok": True,
        "headline": metrics[HEADLINE],
        "stdev": statistics.pstdev([r[HEADLINE] for r in runs]),
        "metrics": metrics,
        "seeds": SEEDS,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
