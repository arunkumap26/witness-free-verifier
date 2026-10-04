"""Field audit for parquet on the HF Hub without downloading the file: read the footer (schema, row counts, row groups)
through HfFileSystem range reads. Optionally read one small row group and summarise one row.
Usage: pqschema.py <repo_id> <revision> <path_in_repo> [read_rows:0/1]"""
import json, sys
import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem

repo, rev, path = sys.argv[1], sys.argv[2], sys.argv[3]
read_rows = len(sys.argv) > 4 and sys.argv[4] == "1"
fs = HfFileSystem()
uri = f"datasets/{repo}@{rev}/{path}"
with fs.open(uri, "rb", block_size=2 * 1024 * 1024) as f:
    pf = pq.ParquetFile(f)
    md = pf.metadata
    print("rows:", md.num_rows, "row_groups:", md.num_row_groups,
          "rg0 bytes:", md.row_group(0).total_byte_size if md.num_row_groups else None)
    print("SCHEMA:\n", pf.schema_arrow)
    if read_rows:
        t = pf.read_row_group(0)
        print("rg0 rows:", t.num_rows)
        rows = t.slice(0, 1).to_pylist()
        json.dump(rows, open(f"samples/{repo.replace('/', '__')}.row0.json", "w"), default=str, indent=1)
        print("wrote sample row")
