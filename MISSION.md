# MISSION: fill this in before the first loop run (preflight checks it)

## What we are submitting
<one paragraph. The judges read this. Write it first, build toward it.>

## How it is scored
<the organizers' criteria, verbatim where possible>

## Headline metrics
- core: `python eval/core.py` prints `headline` = <metric name>. Baseline <n>, target <n>.
- swarm: `python eval/swarm.py` gates the dataset. Target <n> valid rows, 0 dupes, skip rate < 5%.

## Division contracts (committed on main; divisions depend on these, not on each other)
- swarm row schema: <fields, types; mirror in eval/swarm.py REQUIRED>
- core <-> swarm interface: <what core consumes from the dataset, if anything>

## Hard constraints
- Submission deadline: <datetime, timezone>
- Compute: local RTX 5070 Ti 16 GB (swarm owns it overnight). API budget: <$>
- Inputs / datasets: <paths / HF ids>

## Out of scope (do not build these)
- <...>
