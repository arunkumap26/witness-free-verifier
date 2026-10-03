"""VLM swarm pipeline, resumable. The overnight tend loop depends on this contract:

  python -m swarm.run --out DIR [--resume] [--smoke] [--limit N]

  - Appends one JSON row per item to DIR/rows/part-<start>.jsonl. Append-only, never rewritten.
  - Records unprocessable inputs in DIR/skipped.jsonl with a reason (counted by the validator).
  - Writes DIR/progress.json at least every HEARTBEAT_SEC:
      {"status": "running|done", "done": n, "total": n, "skipped": n, "updated": iso}
    The loop treats a progress file older than stale_after_min as a hang.
  - --resume skips ids already present in DIR/rows/.
  - --smoke wipes DIR, processes 2 items, exits 0 on success. Must finish in < 2 minutes.
  - Exit 0 = finished. Nonzero or a traceback = crashed; the loop reads the log and repairs.

Only load_items() and process() are project-specific. The rest is the contract.
"""
import argparse
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

HEARTBEAT_SEC = 30


def load_items() -> list[dict]:
    """Every input to process, each with a stable unique "id"."""
    # TODO: list the images/prompts for the swarm (from a manifest, a folder, or an HF dataset).
    raise NotImplementedError("list the swarm inputs in swarm/run.py:load_items")


def process(item: dict) -> dict:
    """Run the VLM swarm on one item. Return the output row (must include "id").
    Raise SkipItem(reason) for a bad input; any other exception crashes the run."""
    # TODO: call the local VLM(s) (Ollama / LM Studio / vLLM on the RTX 5070 Ti) and the
    # swarm logic. Keep batch size and resolution in config so the mechanic can tune them.
    raise NotImplementedError("run the swarm on one item in swarm/run.py:process")


class SkipItem(Exception):
    pass


def write_progress(out: Path, status: str, done: int, total: int, skipped: int) -> None:
    tmp = out / "progress.json.tmp"
    tmp.write_text(json.dumps({"status": status, "done": done, "total": total, "skipped": skipped,
                               "updated": dt.datetime.now().astimezone().isoformat(timespec="seconds")}))
    tmp.replace(out / "progress.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    out = Path(a.out)
    if a.smoke and out.exists():
        shutil.rmtree(out)
    (out / "rows").mkdir(parents=True, exist_ok=True)

    items = load_items()
    if a.smoke:
        items = items[:2]
    elif a.limit:
        items = items[:a.limit]

    seen: set[str] = set()
    if a.resume:
        for f in (out / "rows").glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    seen.add(json.loads(line)["id"])
        skip_file = out / "skipped.jsonl"
        if skip_file.exists():
            for line in skip_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    seen.add(json.loads(line)["id"])

    todo = [it for it in items if it["id"] not in seen]
    done, skipped, total = len(items) - len(todo), 0, len(items)
    part = out / "rows" / f"part-{int(time.time())}.jsonl"
    write_progress(out, "running", done, total, skipped)
    last_beat = time.time()
    print(f"start: {len(todo)} to do, {done} already done", flush=True)
    with open(part, "a", encoding="utf-8") as rows, open(out / "skipped.jsonl", "a", encoding="utf-8") as skips:
        for item in todo:
            try:
                row = process(item)
                rows.write(json.dumps(row) + "\n")
                rows.flush()
            except SkipItem as e:
                skips.write(json.dumps({"id": item["id"], "reason": str(e)}) + "\n")
                skips.flush()
                skipped += 1
            done += 1
            if time.time() - last_beat > HEARTBEAT_SEC:
                write_progress(out, "running", done, total, skipped)
                last_beat = time.time()
    write_progress(out, "done", done, total, skipped)
    print(f"done: {done}/{total}, skipped {skipped}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
