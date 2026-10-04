"""Flatten a remote parquet schema (footer only, via HfFileSystem range reads) to field paths; flag time/id-like fields.
Usage: pqpaths.py <repo_id> <revision> <path_in_repo>"""
import sys, re
import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem

repo, rev, path = sys.argv[1], sys.argv[2], sys.argv[3]
fs = HfFileSystem()
with fs.open(f"datasets/{repo}@{rev}/{path}", "rb", block_size=1024 * 1024) as f:
    pf = pq.ParquetFile(f)
    md = pf.metadata
    print("rows:", md.num_rows, "row_groups:", md.num_row_groups)
    paths = []

    def walk(t, p):
        if pa.types.is_struct(t):
            for fld in t:
                walk(fld.type, p + "." + fld.name)
        elif pa.types.is_list(t) or pa.types.is_large_list(t):
            walk(t.value_type, p + "[]")
        else:
            paths.append((p, str(t)))

    for fld in pf.schema_arrow:
        walk(fld.type, fld.name)
    skip = re.compile(r"^tools\[\]")
    top = [fld.name for fld in pf.schema_arrow]
    print("TOP-LEVEL:", top)
    for p, t in paths:
        if skip.match(p):
            continue
        flag = " <== time/id-like" if re.search(r"time|created|date|_id$|\.id$|latenc|usage|token|request", p, re.I) else ""
        print(f"  {p}: {t}{flag}")
