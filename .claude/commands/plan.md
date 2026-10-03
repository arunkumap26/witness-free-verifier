---
description: Draft a division's task queue with the planner, review it with me, then write it
argument-hint: "<division>"
---
Division: $1

State paths for this division:
!`python ops/orchestrate.py paths $1`

1. Have the `planner` agent draft the queue for division $1. Give it MISSION.md, the current queue, the inbox, and the last 30 journal lines (paths above).
2. Show me the draft and point out any task whose acceptance check the eval can't actually measure.
3. Wait for my edits or approval. Only then write the approved queue to the `queue` path above, keeping existing `- [x]` and `- [!]` lines under `## Done`.
