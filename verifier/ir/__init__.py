"""verifier.ir: the one import site of the IR schema (DESIGN.md §2.4, decision DA1).

The verifier imports the shared event IR from `analysis/lib/ir.py` instead of vendoring a copy, and pins the module's
bytes. `IR_SCHEMA_SHA` covers the whole file (COLUMNS, normalize_tool's local table, ERROR_MARKERS), with CRLF
normalised to LF so a git autocrlf checkout hashes the same. It enters every Verdict's `version`
(`ir/<IR_SCHEMA_SHA[:12]>`). `tests/test_verifier_core.py` fails if it drifts from `EXPECTED_IR_SCHEMA_SHA`.

Fallback (DA1 point 3): if `analysis/lib` is not merged to `main`, copy `ir.py` to `verifier/ir/_ir.py`, keep the pin,
and change the two import lines below. Nothing else in `verifier` imports `analysis.lib.ir`.

Only `analysis.lib.ir` is imported here (it imports json, re and datetime only), so importing `verifier` never loads
`analysis.lib.stats`, `analysis.lib.sample` or `analysis.loaders.*` (DESIGN §5.1 import isolation).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

try:
    from analysis.lib import ir as _ir
except ModuleNotFoundError:  # running from outside the repo root: the repo root is the parent of verifier/
    sys.path.insert(1, str(Path(__file__).resolve().parents[2]))
    from analysis.lib import ir as _ir

from analysis.lib.ir import (COLUMNS, SHELL_TOOLS, error_marker, frac_digits, iso, normalize_tool, parse_ts,  # noqa: F401
                             to_frame, validate)


def _module_sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


IR_SCHEMA_SHA: str = _module_sha(_ir.__file__)
# Pinned at scaffold time (2026-10-04) from analysis/lib/ir.py as committed in b75e511/82ce894. Bump deliberately, by
# day, together with every pack and cache built under the old schema.
EXPECTED_IR_SCHEMA_SHA: str = "ac603f32cbaf034b2193fb53a3d9d3bba86ebfed82544a5400e921f9199cae25"
IR_SCHEMA_SHA12: str = IR_SCHEMA_SHA[:12]
IR_MODULE_PATH: str = str(Path(_ir.__file__).resolve())

KINDS = ("user", "system", "assistant", "call", "result", "meta")
TS_KINDS = ("event", "row_insert", "shared_turn", "none")

__all__ = ["COLUMNS", "SHELL_TOOLS", "normalize_tool", "iso", "parse_ts", "frac_digits", "error_marker", "to_frame",
           "validate", "IR_SCHEMA_SHA", "EXPECTED_IR_SCHEMA_SHA", "IR_SCHEMA_SHA12", "IR_MODULE_PATH", "KINDS",
           "TS_KINDS"]
