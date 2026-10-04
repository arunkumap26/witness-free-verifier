"""Phase E units for sessions (DESIGN.md §2.5) and the CLI's calibration borrowing by format (§4.5).

A unit is the grain at which calibrations and N6 cells were measured. The units are exactly the `prereg_e.json`
`n6_transfer_grid.columns` plus one per new corpus, named as the `prereg_e_calibration_<corpus>.json` files name them
(`units` keys, or `unit` for the pub_cc_* files). A finer split (tbench2 by log format, aiv_cu by provider family,
agentcap by route) has no calibration of its own and is reported only as a stratum (`reporting_stratum`).

Units for inputs that are not a corpus:
  file/<format>   one raw transcript given to the CLI (`verifier.loaders.files`), e.g. 'file/claude_code'
  turns           SCOPE.md §3 turn dicts (`verifier.ir.turns`)

Calibration borrowing (DA4, DA19). Nothing here decides a verdict. The CLI borrows by format
(`DEFAULT_CALIBRATION_BY_FORMAT`, §4.5) and prints 'borrowed'. `D1_PROXY_UNIT` is the pre-registered proxy map
(`prereg_e.json` change_log D1_calibration_unit_proxy); the eval keeps its own frozen copy in `eval/config_eval.json`
(`EVAL_CALIBRATION_UNIT`), and this copy is used only for IR-parquet input to the CLI (`files.py`).
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "analysis" / "cache"

SWECHAT_FORMATS = ("claude_code", "codex", "opencode", "gemini", "cursor", "copilot", "simple_text")

# prereg_e.json n6_transfer_grid.columns (the eleven original units) + the Track B corpora as their calibration files
# name them (prereg_e_calibration_<corpus>.json).
PHASE_E_UNITS: tuple[str, ...] = (
    tuple(f"swechat/{f}" for f in SWECHAT_FORMATS)
    + ("cc_local", "aiv_cc", "aiv_cu", "whowhen")
    + ("tbench2", "glm_tb21", "pub_cc_hf", "pub_trace_commons", "pub_codex", "agentcap/opencode", "agentcap/pi")
)

# Corpora whose unit is the corpus name itself (no sub-unit).
SINGLE_UNIT_CORPORA = frozenset({"cc_local", "aiv_cc", "aiv_cu", "whowhen", "tbench2", "glm_tb21", "pub_cc_hf",
                                 "pub_trace_commons", "pub_codex"})

# DESIGN.md §4.5: CLI borrowing for user files. `--unit` overrides it.
DEFAULT_CALIBRATION_BY_FORMAT: dict[str, str] = {
    "claude_code": "swechat/claude_code",
    "codex": "swechat/codex",
    "opencode": "swechat/opencode",
    "gemini": "swechat/gemini",
    "atif": "tbench2",
}

# prereg_e.json change_log D1_calibration_unit_proxy. tbench2, glm_tb21 and agentcap/pi calibrate as themselves.
D1_PROXY_UNIT: dict[str, str] = {
    "pub_cc_hf": "cc_local",
    "pub_trace_commons": "cc_local",
    "pub_codex": "swechat/codex",
    "agentcap/opencode": "swechat/opencode",
}

AGENTCAP_AGENTS = ("opencode", "pi")


@functools.lru_cache(maxsize=4096)
def _swechat_format_one(session_id: str) -> str | None:
    fm = swechat_formats([session_id])
    return fm.get(session_id)


def swechat_formats(session_ids: Iterable[str]) -> dict[str, str]:
    """{session_id: format} from analysis/cache/swechat_population.parquet, read only for the ids asked for.

    The population table is session metadata (no event data; prereg_e.json splits.E_freshness). The format is the
    content-sniffed one (load_swechat.sniff_text), not the dataset's agent label. Ids not in the table are absent."""
    import pyarrow.parquet as pq

    ids = sorted({str(s) for s in session_ids})
    if not ids:
        return {}
    path = CACHE_DIR / "swechat_population.parquet"
    if not path.exists():
        return {}
    t = pq.read_table(path, columns=["session_id", "format"], filters=[("session_id", "in", ids)])
    return {str(s): str(f) for s, f in zip(t.column("session_id").to_pylist(), t.column("format").to_pylist())}


def unit_of(corpus: str, session_id: str, stratum: str | None, fmt: str | None = None) -> str:
    """Phase E unit of one session (DESIGN.md §2.5).

    swechat     'swechat/<format>'; fmt is the swechat content format (claude_code, codex, ...). When fmt is None it is
                looked up in swechat_population.parquet for this one id; an id not in the table gives 'swechat/unknown'.
    agentcap    'agentcap/<agent>' from the stratum '<agent>/<route>' (opencode/local, pi/hf-router, ...); fmt may name
                the agent directly ('opencode' | 'pi').
    file        'file/<fmt>' (CLI raw-file input).
    turns       'turns'.
    every other corpus: the corpus name (tbench2 log format, aiv_cu provider family etc. are strata, not units).
    """
    if corpus == "swechat":
        f = fmt or _swechat_format_one(str(session_id)) or "unknown"
        return f"swechat/{f}"
    if corpus == "agentcap":
        agent = fmt if fmt in AGENTCAP_AGENTS else (str(stratum).split("/", 1)[0] if stratum else None)
        return f"agentcap/{agent}" if agent in AGENTCAP_AGENTS else "agentcap/unknown"
    if corpus == "file":
        return f"file/{fmt or 'unknown'}"
    if corpus == "turns":
        return "turns"
    return corpus


def reporting_stratum(corpus: str, stratum: str | None, fmt: str | None = None) -> str | None:
    """The finer grain DESIGN.md §2.5 keeps as a reporting stratum only (never a calibration unit).

    tbench2 / glm_tb21: the log format (atif, cc_jsonl, gemini_cli, hookele) when known, else the IR stratum
    (submitting agent); aiv_cu: provider family (the IR stratum); agentcap: route ('local' | 'hf-router');
    everything else: the IR stratum unchanged."""
    if corpus in ("tbench2", "glm_tb21"):
        return fmt or stratum
    if corpus == "agentcap" and stratum and "/" in stratum:
        return stratum.split("/", 1)[1]
    return stratum


def calibration_unit_for_file(fmt: str) -> str | None:
    """CLI default calibration for a raw transcript of this format (borrowed by format, §4.5); None when the format has
    no calibrated analogue (cursor, copilot, simple_text, turns)."""
    return DEFAULT_CALIBRATION_BY_FORMAT.get(fmt)


def calibration_unit_for_corpus_unit(unit: str) -> str | None:
    """Calibration unit for a session of a known corpus read from IR (CLI `--format ir`): the unit itself, or its D1
    proxy. None for a unit that is not a Phase E unit (e.g. 'swechat/unknown')."""
    if unit in D1_PROXY_UNIT:
        return D1_PROXY_UNIT[unit]
    return unit if unit in PHASE_E_UNITS else None
