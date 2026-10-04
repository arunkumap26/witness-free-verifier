"""Per-call composition and disagreement (DESIGN.md §4.6, decision DA2).

A lattice, not a vote: contradicted > supported > unconstrained. Reference checks are listed in `Verdict.checks` but
never decide. Every per-check verdict is kept ("report all"). `confidence` is display and tie-break only.

Imports verifier.checks.base only (§2.2).
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Optional

from verifier.checks.base import (SCREENED_REASON, STRENGTH_RANK, CallVerdict, Verdict, checkset_sha,
                                  verdict_version)


def _conf(c: CallVerdict) -> float:
    return -1.0 if c.confidence is None else c.confidence


def blame_seq(contra: list[CallVerdict]) -> Optional[int]:
    """Most-cited seq among role in {'subject','conflict'} refs across contradicting checks; ties -> the later seq
    (SCOPE §5.5: 'the later one is marked probable')."""
    n: Counter = Counter(r.seq for c in contra for r in c.evidence if r.role in ("subject", "conflict"))
    if not n:
        return None
    return max(n, key=lambda s: (n[s], s))


def _versions(by_check: Mapping[str, Mapping[str, CallVerdict]]) -> dict[str, str]:
    out = {}
    for name, cvs in by_check.items():
        for cv in cvs.values():
            out[name] = cv.check_version
            break
    return out


def compose(session: Any, by_check: Mapping[str, Mapping[str, CallVerdict]], kinds: Mapping[str, str]) -> list[Verdict]:
    """One Verdict per call of `session`, in call seq order. `by_check` is registry.run_checks output; `kinds` maps
    check name -> kind (identity | statistical | reference)."""
    version = verdict_version(checkset_sha(_versions(by_check)))
    names = sorted(by_check)
    pairs = session.pairs
    tools = dict(zip(pairs["call_key"].tolist(), pairs["tool"].tolist()))
    out: list[Verdict] = []
    for key in session.call_keys:
        cvs = [by_check[n][key] for n in names]
        deciding = [cv for cv in cvs if kinds[cv.check] != "reference"]
        contra = [cv for cv in deciding if cv.verdict == "contradicted"]
        supp = [cv for cv in deciding if cv.verdict == "supported"]
        d: Optional[CallVerdict]
        if contra:
            d = max(contra, key=lambda c: (STRENGTH_RANK[c.strength], c.localized, _conf(c), c.check))
            final, core, blame = "contradicted", sorted({r.seq for c in contra for r in c.evidence}), blame_seq(contra)
        elif supp:
            d = max(supp, key=lambda c: (STRENGTH_RANK[c.strength], _conf(c), c.check))
            final, core, blame = "supported", sorted({r.seq for r in d.evidence}), None
        else:
            d, final, core, blame = None, "unconstrained", [], None
        if d is not None:
            reason, detail = d.reason, d.detail
        elif deciding:  # all unconstrained: most frequent reason; ties -> lexicographically first
            counts = Counter(cv.reason for cv in deciding)
            reason = min(counts, key=lambda r: (-counts[r], r))
            detail = {"unconstrained_reasons": dict(sorted(counts.items()))}
        else:           # nothing but reference checks ran, or nothing ran
            reason = "abstain:reference_only" if cvs else "abstain:no_enabled_checks"
            detail = None
        tool = tools.get(key)
        out.append(Verdict(
            session_id=session.session_id, call_id=session.call_id_of(key), call_key=key, seq=session.call_seq(key),
            result_seq=session.result_seq(key), tool=None if tool is None or tool != tool else str(tool),
            verdict=final, strength=d.strength if d else "none", confidence=d.confidence if d else None,
            rule=d.check if d else None, reason=reason, core=tuple(core), blame_seq=blame,
            localized=any(c.localized for c in contra) if contra else True, disagreement=bool(contra and supp),
            detail=detail, checks=tuple(cvs), version=version))
    return out


def summarize(verdicts: Iterable[Verdict]) -> dict[str, int]:
    """session.json `counts` (§3.3): contradicted split into localized and unit-level (§4.6); `screened` counts
    unconstrained calls that a statistical check screened (abstain:below_threshold)."""
    c = {"supported": 0, "contradicted_localized": 0, "contradicted_unit": 0, "unconstrained": 0, "screened": 0}
    for v in verdicts:
        if v.verdict == "contradicted":
            c["contradicted_localized" if v.localized else "contradicted_unit"] += 1
        elif v.verdict == "supported":
            c["supported"] += 1
        else:
            c["unconstrained"] += 1
            if any(cv.reason == SCREENED_REASON for cv in v.checks):
                c["screened"] += 1
    return c


def apply_min_confidence(verdicts: Iterable[Verdict], x: Optional[float]) -> list[tuple[Verdict, bool]]:
    """Display-only (§4.6, --min-confidence): pairs (verdict, hidden) where hidden marks a contradiction whose
    confidence is below x (shown as 'unconstrained (below display threshold)'). The eval never calls this."""
    out = []
    for v in verdicts:
        hidden = (x is not None and v.verdict == "contradicted" and v.confidence is not None and v.confidence < x)
        out.append((v, hidden))
    return out
