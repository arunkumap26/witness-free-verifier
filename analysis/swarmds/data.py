"""Read-only access to the swarm spoof dataset (spoof_v1.db) and the per-row session views the checks see.

    from analysis.swarmds import data as D
    db = D.connect()                      # sqlite, mode=ro
    rows = D.blind_rows(db)               # v_blind + items.call_id (provenance, not an answer column)
    obs = D.observed(db)                  # {row_id: {kind: parsed}} for the ALLOWED kinds only (never host_stdout)
    idx = D.SessionIndex()
    view = D.row_view(row, idx)           # RowView(kind, path, call_id, claimed) -> .turns()
    D.split_of(session_id)                # 'dev' | 'test'

Protocol (reports/TESTER_HANDOFF.md, task brief):
  * split by session: dev iff int(sha256(session_id).hexdigest(), 16) % 2 == 0, else test.
  * a detector sees v_blind columns, the ALLOWED observed kinds and transcripts. It never sees items.real_output,
    v_answers or observed.host_stdout (witness). `labels()` is the only function that reads v_answers; it is called by
    the scorer after every verdict exists.
  * session view per row:
      injected        <INJ>/<session_id>/<class>-seed<k>.jsonl (the whole tampered transcript)
      tiered / cf     the honest transcript with that call's tool_result content replaced by v_blind.claimed_output
      execlog / other the honest transcript as is
      claim units     tdir(<block>)/<session_id>.jsonl (as dev_claims.py used it)
  * paths: see set_root() below (--data / WFV_DATA / ./dataset; packaged and original layouts).
    Session ids are reused across re-run blocks, so for tool-output rows the block's own copy is used when it contains
    the call, else the copy that does.
Nothing here writes anywhere.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

# ----------------------------------------------------------------------------------------------- data root
# Where the dataset lives: set_root(path) (scripts pass --data) > env WFV_DATA > env SWARMS_DATA (legacy) >
# <repo>/dataset. Two layouts are recognised, nothing else changes between them:
#   packaged (the release asset, spoof_dataset_v1.zip):     original (the swarm repo's data/ tree):
#     <root>/spoof_v1.db                                      <root>/eval/spoof_v1.db
#     <root>/injected_v1/<sid>/<class>-seed<k>.jsonl          <root>/eval/injected_v1/...
#     <root>/transcripts/<block>/<sid>.jsonl                  <root>/swarm/<block>/transcripts/<sid>.jsonl
#     <root>/rows.jsonl                                       <root>/eval/spoof_dataset_v1/rows.jsonl
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "dataset"


def _layout(root: Path) -> dict:
    root = Path(root)
    if not (root / "spoof_v1.db").is_file() and (root / "eval" / "spoof_v1.db").is_file():
        return {"layout": "original", "DATA": root, "DB": root / "eval" / "spoof_v1.db",
                "INJ": root / "eval" / "injected_v1", "SWARM": root / "swarm", "TSUB": "transcripts",
                "ROWS_JSONL": root / "eval" / "spoof_dataset_v1" / "rows.jsonl"}
    return {"layout": "packaged", "DATA": root, "DB": root / "spoof_v1.db", "INJ": root / "injected_v1",
            "SWARM": root / "transcripts", "TSUB": "", "ROWS_JSONL": root / "rows.jsonl"}


def set_root(root=None) -> Path:
    """Point every path in this module at `root` (None: env WFV_DATA, SWARMS_DATA, else <repo>/dataset)."""
    global LAYOUT, DATA, DB, INJ, SWARM, TSUB, ROWS_JSONL
    if root is None:
        root = os.environ.get("WFV_DATA") or os.environ.get("SWARMS_DATA") or DEFAULT_ROOT
    L = _layout(Path(root).expanduser().resolve())
    LAYOUT, DATA, DB, INJ, SWARM, TSUB, ROWS_JSONL = (L["layout"], L["DATA"], L["DB"], L["INJ"], L["SWARM"],
                                                       L["TSUB"], L["ROWS_JSONL"])
    return DATA


def tdir(block: Optional[str]) -> Path:
    """Directory holding the honest transcripts of `block` ('*' works for globbing)."""
    d = SWARM / (block or "")
    return d / TSUB if TSUB else d


def require() -> None:
    """Fail with a readable message when the dataset is not where the paths point."""
    if not DB.is_file():
        raise SystemExit(f"dataset not found: {DB} does not exist.\n"
                         f"  download it:  python scripts/download_dataset.py   (extracts to ./dataset)\n"
                         f"  or point at it: --data <dir>  /  set WFV_DATA=<dir>")


LAYOUT = DATA = DB = INJ = SWARM = ROWS_JSONL = None   # set below
TSUB = ""
set_root()

ALLOWED_OBSERVED = ("supported_digests", "own_digests_by_file", "claimed_digests", "board_reads")
WITNESS_OBSERVED = ("host_stdout",)
HONEST_TRAPS = ("attributed_quotation", "challenged_planted_claim", "interstitial_false_pass",
                "unverified_true_claim", "unsupported_shared_value")


def split_of(session_id: Optional[str]) -> str:
    return "dev" if int(hashlib.sha256((session_id or "").encode()).hexdigest(), 16) % 2 == 0 else "test"


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def load_turns(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def splice(turns: list[dict], call_id: str, claimed: Optional[str]) -> tuple[list[dict], bool]:
    """Replace the content of `call_id`'s (first) tool_result with `claimed`; returns (new turns, hit)."""
    out, hit = [], False
    for t in turns:
        if not hit and t.get("role") == "tool_result" and t.get("tool_call_id") == call_id:
            t = dict(t, content=claimed)
            hit = True
        out.append(t)
    return out, hit


def honest_transcripts() -> list[Path]:
    """Every honest swarm transcript (all blocks, both splits; a reused session id appears once per block)."""
    return [Path(p) for p in sorted(glob.glob(str(tdir("*") / "*.jsonl")))]


class SessionIndex:
    def __init__(self) -> None:
        self.by_sid: dict[str, list[Path]] = defaultdict(list)
        for p in honest_transcripts():
            self.by_sid[p.stem].append(p)

    def honest_path(self, block: Optional[str], sid: str, call_id: Optional[str]) -> Optional[Path]:
        own = tdir(block) / f"{sid}.jsonl"
        cands = ([own] if own.is_file() else []) + [c for c in self.by_sid.get(sid, []) if c != own]
        if not cands:
            return None
        if not call_id or len(cands) == 1:
            return cands[0]                 # a call absent from it comes back from the check as missing
        for c in cands:
            if call_id in self._text(c):
                return c
        return None

    _texts: dict = {}

    def _text(self, p: Path) -> str:
        if p not in self._texts:
            self._texts[p] = p.read_text(encoding="utf-8")
        return self._texts[p]


@dataclass(frozen=True)
class RowView:
    kind: str                     # 'tampered' | 'spliced' | 'honest' | 'claim' | 'none'
    path: Optional[Path]
    call_id: Optional[str]
    claimed: Optional[str] = None
    note: str = ""

    def turns(self) -> list[dict]:
        if self.path is None:
            return []
        t = load_turns(self.path)
        if self.kind == "spliced":
            t, _ = splice(t, self.call_id, self.claimed)
        return t


def row_view(r, idx: SessionIndex) -> RowView:
    """What the verifier sees for one v_blind row (r needs row_id, source, unit, block, session_id, call_id,
    claimed_output)."""
    rid, src, sid, cid = r["row_id"], r["source"], r["session_id"], r["call_id"]
    if r["unit"] == "claim":
        p = tdir(r["block"]) / f"{sid}.jsonl"
        return RowView("claim", p if p.is_file() else None, cid, note="" if p.is_file() else "missing:no_transcript")
    if src == "injected":
        _, call, cls, seed = rid.split(":")                      # inj:<call_id>:<class>:seed<k>
        p = INJ / sid / f"{cls}-{seed}.jsonl"
        return RowView("tampered", p if p.is_file() else None, call, note="" if p.is_file() else "missing:no_view")
    p = idx.honest_path(r["block"], sid, cid)
    if p is None:
        return RowView("none", None, cid, note="missing:no_session_view")
    if src in ("tiered", "counterfactual"):
        return RowView("spliced", p, cid, r["claimed_output"])
    return RowView("honest", p, cid)


def blind_rows(db: sqlite3.Connection) -> list[dict]:
    """All v_blind rows plus items.call_id (provenance: locates the call in its session; not an answer column)."""
    return [dict(r) for r in db.execute(
        "SELECT b.*, i.call_id FROM v_blind b JOIN items i ON i.row_id = b.row_id ORDER BY b.row_id")]


def observed(db: sqlite3.Connection, kinds: tuple[str, ...] = ALLOWED_OBSERVED) -> dict[str, dict]:
    bad = set(kinds) & set(WITNESS_OBSERVED)
    if bad:
        raise ValueError(f"observed kinds {sorted(bad)} are witness data; not available to a detector")
    q = "SELECT row_id, kind, content FROM observed WHERE kind IN (%s)" % ",".join("?" * len(kinds))
    out: dict[str, dict] = defaultdict(dict)
    for r in db.execute(q, kinds):
        try:
            out[r["row_id"]][r["kind"]] = json.loads(r["content"])
        except (TypeError, ValueError):
            out[r["row_id"]][r["kind"]] = r["content"]
    return out


def observed_raw(db: sqlite3.Connection, kinds: tuple[str, ...] = ALLOWED_OBSERVED) -> dict[str, dict]:
    """Same as observed() but contents left as stored strings (what dev_claims.py passed to verify_claim)."""
    if set(kinds) & set(WITNESS_OBSERVED):
        raise ValueError("witness kinds are not available to a detector")
    q = "SELECT row_id, kind, content FROM observed WHERE kind IN (%s)" % ",".join("?" * len(kinds))
    out: dict[str, dict] = defaultdict(dict)
    for r in db.execute(q, kinds):
        out[r["row_id"]][r["kind"]] = r["content"]
    return out


def labels(db: sqlite3.Connection) -> dict[str, dict]:
    """SCORING ONLY: v_answers (label, spoof_class, difficulty, verdict_class, consistency, detectable_witness_free).
    real_output is deliberately not selected."""
    return {r["row_id"]: dict(r) for r in db.execute(
        "SELECT row_id, label, spoof_class, difficulty, verdict_class, consistency, detectable_witness_free "
        "FROM v_answers")}


def iter_rows_jsonl() -> Iterator[dict]:
    """The baseline's own input file (reports/detector_score.txt was computed from it). Used only to replay the
    baseline detector, which reads non-witness fields of it."""
    if not ROWS_JSONL.is_file():
        return
    with open(ROWS_JSONL, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
