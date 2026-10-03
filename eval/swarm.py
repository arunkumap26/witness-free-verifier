"""Swarm dataset validator. The tend loop runs a FROZEN COPY of this against the output dir.

  python eval/swarm.py --data <dir>
  Reads <dir>/rows/*.jsonl and <dir>/skipped.jsonl, prints one JSON line:
    {"ok": bool, "rows": n, "valid_pct": float, "dupes": n, "skipped": n, "errors": {...}}

Tighten REQUIRED once the row schema is settled in MISSION.md. This file is the dataset's
definition of "correct", so changes to it are a daytime decision, never an overnight one.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# field -> required type (None = any non-null value)
REQUIRED: dict[str, type | None] = {
    "id": str,
    "input": None,
    "output": None,
}
MAX_SKIP_PCT = 5.0


def check(row: dict) -> str | None:
    for field, typ in REQUIRED.items():
        if row.get(field) is None:
            return f"missing:{field}"
        if typ is not None and not isinstance(row[field], typ):
            return f"type:{field}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    data = Path(ap.parse_args().data)
    rows = valid = 0
    errors: Counter = Counter()
    ids: Counter = Counter()
    for f in sorted((data / "rows").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows += 1
            try:
                row = json.loads(line)
            except ValueError:
                errors["bad_json"] += 1
                continue
            err = check(row)
            if err:
                errors[err] += 1
            else:
                valid += 1
                ids[row["id"]] += 1
    skip_file = data / "skipped.jsonl"
    skipped = sum(1 for l in skip_file.read_text(encoding="utf-8").splitlines() if l.strip()) \
        if skip_file.exists() else 0
    dupes = sum(c - 1 for c in ids.values() if c > 1)
    valid_pct = round(100.0 * valid / rows, 2) if rows else 100.0
    skip_pct = 100.0 * skipped / (rows + skipped) if rows + skipped else 0.0
    ok = dupes == 0 and skip_pct <= MAX_SKIP_PCT
    print(json.dumps({"ok": ok, "rows": rows, "valid_pct": valid_pct, "dupes": dupes,
                      "skipped": skipped, "skip_pct": round(skip_pct, 2),
                      "errors": dict(errors.most_common(10))}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
