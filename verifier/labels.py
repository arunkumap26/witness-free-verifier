"""Labeled-corpus join (DESIGN.md §3.4): the pipe for a future labeled input. Contents are not assumed.

Whether any labeled data may be used is a human decision (PHASE_E_PROMPT.md "Scope boundary"). This module only
reads, validates and joins; it works with an absent or empty label file (every call then joins as `unknown`, which is
never read as `neg`).

Directory format of a labeled corpus:
    <dir>/manifest.json   {"name", "version", "schema": "labeled_call/1", "sessions_format": "ir"|"turns", "license",
                           "files": {path: sha256}, "classes": [...], "source": "..."}
    <dir>/labels.jsonl    one LabeledCall per line ("class" is the JSON key of `cls`)
    <dir>/sessions/       IR parquet with exactly COLUMNS, or turns/*.jsonl in the SCOPE §3 turn schema

Join rules (join_labels):
  1. call_id not null: join on (session_id, call_id). One matching call -> ok; more than one -> ambiguous (excluded,
     counted).
  2. call_id null: join on (session_id, seq) only if the label's ir_sha == session_ir_sha(session events); else
     seq_mismatch (excluded, counted).
  3. session absent -> orphan_label (counted). A call with no label -> unknown, never neg.
  Added here (DESIGN names no status for it): session present but no call matches -> no_match (excluded, counted).
  The eval rule "ok share of labels < 0.99 -> ok: false" (SCOPE §7.14) uses join_stats()['ok_share'].

Placement: DESIGN.md puts LabeledCall/session_ir_sha/join in eval/labeled.py; the scaffold assignment puts the
verifier-side copy here. Under DA6 the eval may import only verifier.verify_session, so eval/labeled.py must carry
its own frozen copy of these rules; tests should assert the two agree.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Optional, Union

import pandas as pd

from verifier.checks.base import Verdict
from verifier.ir import COLUMNS

LABEL_SCHEMA = "labeled_call/1"
LABEL_VALUES = ("pos", "neg", "unknown")
JOIN_STATUSES = ("ok", "ambiguous", "seq_mismatch", "orphan_label", "no_match", "unknown")
JOIN_OK_MIN = 0.99
LABEL_COLUMNS = ["set", "corpus", "session_id", "call_id", "seq", "label", "cls", "provenance", "label_version",
                 "ir_sha", "tampered_seqs"]


@dataclass(frozen=True)
class LabeledCall:                          # superset of SCOPE.md §3 `labeled_call`
    set: str                                # '<corpus name>' or 'attack:<attack>:<param>:seed<k>'
    corpus: str
    session_id: str
    call_id: Optional[str]                  # preferred join key (raw IR call_id)
    seq: Optional[int]                      # fallback join key (requires ir_sha)
    label: Literal["pos", "neg", "unknown"]
    cls: Optional[str]                      # serialized as "class"
    provenance: str
    label_version: str
    ir_sha: Optional[str] = None
    tampered_seqs: tuple[int, ...] = ()

    def to_json(self) -> dict:
        return {"set": self.set, "corpus": self.corpus, "session_id": self.session_id, "call_id": self.call_id,
                "seq": self.seq, "label": self.label, "class": self.cls, "provenance": self.provenance,
                "label_version": self.label_version, "ir_sha": self.ir_sha, "tampered_seqs": list(self.tampered_seqs)}

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> "LabeledCall":
        for k in ("set", "corpus", "session_id", "label", "provenance", "label_version"):
            if d.get(k) is None:
                raise ValueError(f"labeled_call: missing {k!r}")
        if d["label"] not in LABEL_VALUES:
            raise ValueError(f"labeled_call: label {d['label']!r} not in {LABEL_VALUES}")
        seq = d.get("seq")
        if d.get("call_id") is None and seq is None:
            raise ValueError("labeled_call: needs call_id or seq")
        return cls(set=str(d["set"]), corpus=str(d["corpus"]), session_id=str(d["session_id"]),
                   call_id=None if d.get("call_id") is None else str(d["call_id"]),
                   seq=None if seq is None else int(seq), label=d["label"], cls=d.get("class"),
                   provenance=str(d["provenance"]), label_version=str(d["label_version"]), ir_sha=d.get("ir_sha"),
                   tampered_seqs=tuple(int(s) for s in d.get("tampered_seqs") or ()))


def session_ir_sha(events: pd.DataFrame) -> str:
    """sha256 over the canonical bytes of the session's IR rows: columns in COLUMNS order, rows in seq order, NA as
    empty, fields joined with \\x1f and rows with \\x1e."""
    df = events.sort_values("seq", kind="mergesort")
    h = hashlib.sha256()
    cols = [df[c].tolist() for c in COLUMNS]
    for i in range(len(df)):
        vals = []
        for col in cols:
            v = col[i]
            vals.append("" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v))
        h.update("\x1f".join(vals).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def empty_labels() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=object) for c in LABEL_COLUMNS})


def read_labels(path: Union[None, str, Path]) -> pd.DataFrame:
    """labels.jsonl (or a directory holding one) -> one row per LabeledCall with LABEL_COLUMNS. None, a missing path or
    an empty file -> an empty frame. A malformed line raises ValueError naming the line."""
    if path is None:
        return empty_labels()
    p = Path(path)
    if p.is_dir():
        p = p / "labels.jsonl"
    if not p.is_file():
        return empty_labels()
    rows = []
    with p.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                lc = LabeledCall.from_json(json.loads(line))
            except ValueError as e:
                raise ValueError(f"{p.name}:{n}: {e}") from None
            rows.append({"set": lc.set, "corpus": lc.corpus, "session_id": lc.session_id, "call_id": lc.call_id,
                         "seq": lc.seq, "label": lc.label, "cls": lc.cls, "provenance": lc.provenance,
                         "label_version": lc.label_version, "ir_sha": lc.ir_sha, "tampered_seqs": lc.tampered_seqs})
    return pd.DataFrame(rows, columns=LABEL_COLUMNS) if rows else empty_labels()


def read_manifest(directory: Union[str, Path]) -> Optional[dict]:
    """<dir>/manifest.json, or None when absent. Raises ValueError on a wrong schema tag."""
    p = Path(directory) / "manifest.json"
    if not p.is_file():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("schema") != LABEL_SCHEMA:
        raise ValueError(f"manifest schema {m.get('schema')!r} != {LABEL_SCHEMA!r}")
    return m


def verdicts_frame(verdicts: Iterable[Verdict], ir_shas: Optional[Mapping[str, str]] = None) -> pd.DataFrame:
    """Verdicts -> one row per call: session_id, call_id, call_key, seq, tool, verdict, strength, confidence, rule,
    reason, localized, disagreement, ir_sha (from ir_shas when given)."""
    rows = [{"session_id": v.session_id, "call_id": v.call_id, "call_key": v.call_key, "seq": v.seq, "tool": v.tool,
             "verdict": v.verdict, "strength": v.strength, "confidence": v.confidence, "rule": v.rule,
             "reason": v.reason, "localized": v.localized, "disagreement": v.disagreement,
             "ir_sha": (ir_shas or {}).get(v.session_id)} for v in verdicts]
    cols = ["session_id", "call_id", "call_key", "seq", "tool", "verdict", "strength", "confidence", "rule", "reason",
            "localized", "disagreement", "ir_sha"]
    return pd.DataFrame(rows, columns=cols)


def _na(v: Any) -> bool:
    return v is None or (not isinstance(v, (str, tuple, list)) and pd.isna(v))


def join_labels(verdicts: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """One row per label (join_status ok | ambiguous | seq_mismatch | orphan_label | no_match) plus one row per
    unlabeled call (join_status unknown, label 'unknown'). Verdict columns are filled only for `ok` rows and unlabeled
    calls. `verdicts` is verdicts_frame() output; its `ir_sha` column gates seq joins (rule 2)."""
    vcols = [c for c in verdicts.columns if c not in ("session_id",)]
    by_cid: dict[tuple[str, str], list[int]] = {}
    by_seq: dict[tuple[str, int], int] = {}
    sha_of: dict[str, Any] = {}
    for i, r in enumerate(verdicts.itertuples(index=False)):
        by_cid.setdefault((r.session_id, r.call_id), []).append(i)
        by_seq[(r.session_id, int(r.seq))] = i
        sha_of.setdefault(r.session_id, getattr(r, "ir_sha", None))
    vrec = verdicts.to_dict("records")
    used: set[int] = set()
    rows = []
    for lab in labels.to_dict("records"):
        sid = str(lab["session_id"])
        status, hit = None, None
        if sid not in sha_of:
            status = "orphan_label"
        elif not _na(lab.get("call_id")):
            m = by_cid.get((sid, str(lab["call_id"])), [])
            status, hit = ("ok", m[0]) if len(m) == 1 else (("ambiguous", None) if m else ("no_match", None))
        else:
            vsha = sha_of.get(sid)
            if _na(lab.get("ir_sha")) or _na(vsha) or lab["ir_sha"] != vsha:
                status = "seq_mismatch"
            else:
                i = by_seq.get((sid, int(lab["seq"])))
                status, hit = ("ok", i) if i is not None else ("no_match", None)
        row = dict(lab)
        row["session_id"] = sid
        row["join_status"] = status
        for c in vcols:
            row[f"v_{c}"] = vrec[hit][c] if hit is not None else None
        if hit is not None:
            used.add(hit)
        rows.append(row)
    for i, v in enumerate(vrec):
        if i in used:
            continue
        row = {c: None for c in LABEL_COLUMNS}
        row.update(session_id=v["session_id"], call_id=v["call_id"], seq=v["seq"], label="unknown",
                   join_status="unknown")
        for c in vcols:
            row[f"v_{c}"] = v[c]
        rows.append(row)
    cols = LABEL_COLUMNS + ["join_status"] + [f"v_{c}" for c in vcols]
    return pd.DataFrame(rows, columns=cols)


def join_stats(joined: pd.DataFrame) -> dict:
    """Counts per join_status, n_labels, and ok_share = ok / labels (None when there are no labels)."""
    counts = {s: 0 for s in JOIN_STATUSES}
    for s, n in joined["join_status"].value_counts().items():
        counts[str(s)] = int(n)
    n_labels = sum(v for k, v in counts.items() if k != "unknown")
    return {"counts": counts, "n_labels": n_labels,
            "ok_share": (counts["ok"] / n_labels) if n_labels else None, "ok_min": JOIN_OK_MIN,
            "join_ok": (counts["ok"] / n_labels >= JOIN_OK_MIN) if n_labels else None}
