"""Reference check `ref_result_present`: pipeline proof only (DESIGN.md §4.8). Makes NO detection claim.

A call with a joined result (§3.1 pairing rule) is `supported` / `ok:result_joined` with evidence [call (subject),
result (witness)]; a call without one is `unconstrained` / `missing:result`. It never contradicts, and `compose`
filters reference checks out, so it never decides a composed verdict. It is not in ENABLED_CHECKS, so it cannot
inflate coverage. `--checks ref_result_present` (or `--checks all`) exercises loader -> session -> registry ->
compose -> render end to end.

DESIGN.md names the module `ref_result_present.py`; the scaffold assignment puts it in `reference.py` (see the
registry docstring for how the one-module-per-check rule treats reference checks).
"""
from __future__ import annotations

from typing import ClassVar

import pandas as pd

from verifier.checks.base import CallVerdict, supported, unconstrained
from verifier.registry import register


@register
class RefResultPresent:
    name: ClassVar[str] = "ref_result_present"
    version: ClassVar[str] = "1.0.0"
    kind: ClassVar[str] = "reference"
    strength: ClassVar[str] = "format"
    requires: ClassVar[frozenset] = frozenset({"join.call_id"})
    reads: ClassVar[frozenset] = frozenset({"events"})
    targets: ClassVar[frozenset] = frozenset()
    unit_kind: ClassVar[str] = "call"
    calibration: ClassVar[None] = None

    def applicable(self, session) -> bool:
        return True

    def run(self, session) -> list[CallVerdict]:
        out = []
        p = session.pairs
        for key, cid, cs, rs, n in zip(p["call_key"].tolist(), p["call_id"].tolist(), p["call_seq"].tolist(),
                                       p["result_seq"].tolist(), p["n_results"].tolist()):
            if rs is None or pd.isna(rs):
                out.append(unconstrained(session, key, self, "missing:result"))
                continue
            ev = [session.ref(int(cs), "call_id", "subject", cid), session.ref(int(rs), "call_id", "witness", cid)]
            out.append(supported(session, key, self, "ok:result_joined", ev, confidence=None,
                                 detail={"result_seq": int(rs), "n_results": int(n)}))
        return out

    def explain(self, cv: CallVerdict) -> str:
        if cv.verdict == "supported":
            d = cv.detail or {}
            extra = f" ({d['n_results']} results in its window)" if d.get("n_results", 1) > 1 else ""
            return (f"A result with the same call_id follows this call at seq {d.get('result_seq')}{extra}. "
                    f"Reference check: this proves the pipeline, not the result.")
        return "No result with this call_id follows the call before the next call with the same id."
