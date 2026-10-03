---
description: Run the next queued task for a division interactively (implementer, then an independent evaluator)
argument-hint: "<division>"
---
Division: $1

!`python ops/orchestrate.py paths $1`

1. Read MISSION.md and the queue file above. Take the FIRST `- [ ]` task only.
2. Delegate it to the `implementer` agent with the task text and its acceptance check.
3. When it returns, have the `evaluator` agent measure the result independently and compare it with the last `keep` line in the journal.
4. Show me the diff summary and the measurement. If it regressed, say so and propose reverting. Don't commit or check the task off until I agree.

Do not take a second task.
