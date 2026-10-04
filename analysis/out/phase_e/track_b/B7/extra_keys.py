"""B7: inventory of top-level keys inside the IR `extra` JSON column, per corpus (key names and fill counts only).

Sizes the schema-documentation work: every key listed here would need a sentence in a public SCHEMA.md.
Reads only analysis/cache/{swechat,whowhen,aiv_cc,aiv_cu}_{A,B,E}.parquet that exist (never H; cc_local skipped because
it is private and not releasable). No values are written.

Output: analysis/out/phase_e/track_b/B7/extra_keys.json
Run:    python analysis/out/phase_e/track_b/B7/extra_keys.py
"""
import json, os, collections, time
import pyarrow.parquet as pq

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.path.join(os.path.dirname(__file__), "extra_keys.json")
t0 = time.time()
res = {}
for corpus in ("swechat", "whowhen", "aiv_cc", "aiv_cu"):
    keys, rows, nonnull, bad = collections.Counter(), 0, 0, 0
    used = []
    for split in ("A", "B", "E"):
        p = os.path.join(CACHE, f"{corpus}_{split}.parquet")
        if not os.path.exists(p):
            continue
        used.append(os.path.basename(p))
        for b in pq.ParquetFile(p).iter_batches(batch_size=50000, columns=["extra"]):
            for s in b.column(0).to_pylist():
                rows += 1
                if not s:
                    continue
                nonnull += 1
                try:
                    o = json.loads(s)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(o, dict):
                    keys.update(o.keys())
    res[corpus] = {"files": used, "rows": rows, "rows_with_extra": nonnull, "unparseable": bad,
                   "distinct_top_level_keys": len(keys), "keys_by_rows": dict(keys.most_common())}
json.dump({"script": "analysis/out/phase_e/track_b/B7/extra_keys.py", "wall_seconds": round(time.time() - t0, 1),
           "corpora": res}, open(OUT, "w", encoding="utf-8"), indent=1)
print({c: (v["rows"], v["rows_with_extra"], v["distinct_top_level_keys"]) for c, v in res.items()})
