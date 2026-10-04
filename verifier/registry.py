"""Check registry: registration, applicability, run order, output validation and gap filling (DESIGN.md §4.4).

Usage: decorate the check class with `@register` in its own module `verifier/checks/<name>.py`, add the module name to
`CHECK_MODULES`, and (only after its parity test and §5.7 enable run pass, DA15) add its name to `ENABLED_CHECKS`.
A registered check that is not enabled runs only through `checks=[name]` / `--checks name` or `--checks all`.

Deviation from DESIGN.md §4.4 (scaffold assignment): `ENABLED_CHECKS` and the check-module import list live here
rather than in `verifier/checks/__init__.py`, and the reference check lives in `verifier/checks/reference.py` while
keeping the name `ref_result_present`. The one-module-per-check rule (`cls.__module__ == verifier.checks.<name>`) is
enforced for identity and statistical checks; reference checks only need to live under `verifier.checks`.
`check_module_file(name)` gives the eval's verdict cache the module path either way (§5.3).
"""
from __future__ import annotations

import importlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence, Union

from verifier.checks.base import (ATTACK_NAMES_DECLARED, CHECK_KINDS, CHECK_STRENGTHS, READ_FIELDS, UNIT_KINDS, Check,
                                  CallVerdict, ContractError, check_version, load_calibration, unconstrained,
                                  validate_call_verdict)
from verifier.session import CAPABILITIES, Session, is_capability_name

REGISTRY: dict[str, type] = {}

# Check modules imported by load_checks(), as verifier.checks.<module>. Order does not matter: run order is by name.
CHECK_MODULES: tuple[str, ...] = ("reference",)

# Stays () through the scaffold and until gate G0 (§7.3). At the freeze: the checks that passed parity (DA15) and their
# §5.7 MUST rows on E. Reference checks are never listed.
ENABLED_CHECKS: tuple[str, ...] = ()

_NAME_RX = re.compile(r"^[a-z][a-z0-9_]*$")
_SEMVER_RX = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")
_loaded = False


def register(cls: type) -> type:
    """Class decorator. Raises ContractError on any violation of the §4.4 registration rules."""
    def bad(msg: str) -> ContractError:
        return ContractError(f"register({getattr(cls, 'name', cls.__name__)}): {msg}")

    for attr in ("name", "version", "kind", "strength", "requires", "reads", "targets", "unit_kind", "calibration"):
        if not hasattr(cls, attr):
            raise bad(f"missing class attribute {attr!r}")
    if not isinstance(cls.name, str) or not _NAME_RX.match(cls.name):
        raise bad("name must be snake_case")
    if cls.name in REGISTRY:
        raise bad("duplicate check name")
    if not isinstance(cls.version, str) or not _SEMVER_RX.match(cls.version):
        raise bad(f"version {cls.version!r} is not semver")
    if cls.kind not in CHECK_KINDS:
        raise bad(f"kind {cls.kind!r} not in {CHECK_KINDS}")
    if cls.strength not in CHECK_STRENGTHS:
        raise bad(f"strength {cls.strength!r} not in {CHECK_STRENGTHS}")
    if cls.unit_kind not in UNIT_KINDS:
        raise bad(f"unit_kind {cls.unit_kind!r} not in {UNIT_KINDS}")
    for a in ("requires", "reads", "targets"):
        if not isinstance(getattr(cls, a), frozenset):
            raise bad(f"{a} must be a frozenset")
    unknown_caps = sorted(c for c in cls.requires if not is_capability_name(c))
    if unknown_caps:
        raise bad(f"unknown capabilities {unknown_caps}")
    if not cls.reads <= READ_FIELDS:
        raise bad(f"reads {sorted(cls.reads - READ_FIELDS)} not in READ_FIELDS")
    if not cls.targets <= ATTACK_NAMES_DECLARED:
        raise bad(f"targets {sorted(cls.targets - ATTACK_NAMES_DECLARED)} not in ATTACK_NAMES_DECLARED")
    if (cls.calibration is None) != (cls.kind == "reference"):
        raise bad("calibration must be None exactly for reference checks")
    if cls.kind == "reference":
        if not cls.__module__.startswith("verifier.checks."):
            raise bad(f"module {cls.__module__!r} is not under verifier.checks")
    elif cls.__module__ != f"verifier.checks.{cls.name}":
        raise bad(f"module {cls.__module__!r} must be verifier.checks.{cls.name} (one module per check)")
    if not isinstance(cls(), Check):
        raise bad("does not satisfy the Check protocol")
    load_calibration(cls)  # §4.7: calibration is loaded (and its sha fixed) at registration
    REGISTRY[cls.name] = cls
    return cls


def load_checks() -> dict[str, type]:
    """Import every module in CHECK_MODULES once (each registers itself). Returns REGISTRY."""
    global _loaded
    if not _loaded:
        for m in CHECK_MODULES:
            importlib.import_module(f"verifier.checks.{m}")
        _loaded = True
    return REGISTRY


def get_check(name: str) -> type:
    load_checks()
    if name not in REGISTRY:
        raise KeyError(f"unknown check {name!r}; registered: {sorted(REGISTRY)}")
    return REGISTRY[name]


def check_module_file(name: str) -> str:
    """Source file of a registered check's module (the eval's vcache code_sha input, §5.3)."""
    return sys.modules[get_check(name).__module__].__file__ or ""


def resolve_names(names: Union[None, str, Sequence[str]]) -> tuple[str, ...]:
    """None or 'enabled' -> ENABLED_CHECKS; 'all' -> every registered check (reference checks included);
    a comma string or a sequence -> those names (KeyError on an unknown one). Sorted, deduplicated."""
    load_checks()
    if names is None or names == "enabled":
        out: Iterable[str] = ENABLED_CHECKS
    elif names == "all":
        out = REGISTRY
    elif isinstance(names, str):
        out = [n.strip() for n in names.split(",") if n.strip()]
    else:
        out = list(names)
    out = sorted(set(out))
    for n in out:
        get_check(n)
    return tuple(out)


@dataclass
class RunStats:
    """Per-session run record: status per check (ran | missing | not_applicable | error) and error counts."""
    status: dict[str, str] = field(default_factory=dict)
    reason: dict[str, Optional[str]] = field(default_factory=dict)
    version: dict[str, str] = field(default_factory=dict)
    errors: Counter = field(default_factory=Counter)

    def checks_run(self) -> list[dict]:
        """session.json `checks_run` rows (§3.3)."""
        return [{"name": n, "version": self.version[n], "status": self.status[n], "reason": self.reason.get(n)}
                for n in sorted(self.status)]


def run_checks(session: Session, names: Union[None, str, Sequence[str]] = None, *, strict: bool = False,
               stats: Optional[RunStats] = None) -> dict[str, dict[str, CallVerdict]]:
    """For each check in sorted(names or ENABLED_CHECKS):
      requires - capabilities non-empty  -> every call unconstrained('missing:<first>', detail={'missing': [...]})
      not applicable(session)            -> every call unconstrained('abstain:not_applicable')
      else run(session), validated: duplicate or unknown call_key, check/version mismatch, any §4.1 invariant ->
           ContractError; absent call_keys -> unconstrained('abstain:not_decided')
    Any exception in applicable/run (ContractError included) -> every call unconstrained('error:<ExcClass>'), counted
    in stats.errors; re-raised when strict=True. A session with no calls gives {name: {}}."""
    stats = stats if stats is not None else RunStats()
    out: dict[str, dict[str, CallVerdict]] = {}
    keys = session.call_keys
    keyset = session.call_key_set
    for name in resolve_names(names):
        cls = REGISTRY[name]
        inst = cls()
        stats.version[name] = check_version(cls)
        missing = sorted(c for c in cls.requires if not session.has_capability(c))
        if missing:
            stats.status[name], stats.reason[name] = "missing", f"missing:{missing[0]}"
            out[name] = {k: unconstrained(session, k, cls, f"missing:{missing[0]}", {"missing": missing}) for k in keys}
            continue
        try:
            if not inst.applicable(session):
                stats.status[name], stats.reason[name] = "not_applicable", "abstain:not_applicable"
                out[name] = {k: unconstrained(session, k, cls, "abstain:not_applicable") for k in keys}
                continue
            got: dict[str, CallVerdict] = {}
            for cv in inst.run(session) or ():
                validate_call_verdict(cv, session, cls, call_keys=keyset)
                if cv.call_key in got:
                    raise ContractError(f"{name}: duplicate call_key {cv.call_key!r}")
                got[cv.call_key] = cv
            out[name] = {k: got[k] if k in got else unconstrained(session, k, cls, "abstain:not_decided") for k in keys}
            stats.status[name], stats.reason[name] = "ran", None
        except Exception as e:  # noqa: BLE001 - the contract: a check exception becomes error:<ExcClass>
            if strict:
                raise
            ename = type(e).__name__
            stats.status[name], stats.reason[name] = "error", f"error:{ename}"
            stats.errors[name] += 1
            out[name] = {k: unconstrained(session, k, cls, f"error:{ename}", {"message": str(e)[:300]}) for k in keys}
    return out


def kinds_of(names: Iterable[str]) -> dict[str, str]:
    """{name: kind} for compose()."""
    return {n: get_check(n).kind for n in names}


def describe() -> list[dict]:
    """Registry listing for `checks` (name, version, kind, strength, requires, reads, targets, calibrated units)."""
    load_checks()
    rows = []
    for n in sorted(REGISTRY):
        c = REGISTRY[n]
        cal, sha = load_calibration(c)
        rows.append({"name": n, "version": c.version, "check_version": check_version(c), "kind": c.kind,
                     "strength": c.strength, "unit_kind": c.unit_kind, "requires": sorted(c.requires),
                     "reads": sorted(c.reads), "targets": sorted(c.targets), "calibration": c.calibration,
                     "calibrated_units": sorted((cal or {}).get("units", {})), "enabled": n in ENABLED_CHECKS,
                     "module": c.__module__})
    return rows


__all__ = ["REGISTRY", "CHECK_MODULES", "ENABLED_CHECKS", "CAPABILITIES", "register", "load_checks", "get_check",
           "check_module_file", "resolve_names", "RunStats", "run_checks", "kinds_of", "describe"]
