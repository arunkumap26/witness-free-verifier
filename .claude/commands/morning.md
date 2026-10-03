---
description: Morning review of the overnight run. Summarize each division, critic-review its commits, recommend what to merge
---
!`python ops/orchestrate.py status`

!`git log --oneline main..div/core`

!`git log --oneline main..div/swarm`

For each division that ran overnight (core, swarm):
1. Summarize the night from its journal (`python ops/orchestrate.py paths <div>` gives the path): iterations, keeps vs rejects vs limits, headline at start and end, total cost, any alerts, and anything still blocked.
2. Have the `critic` agent review the diff `main...div/<div>` for result-invalidating problems.
3. Recommend merge, partial merge, or hold, with one line of reasoning.

Then list the inbox follow-ups worth queueing today. Do not merge anything until I say so.
