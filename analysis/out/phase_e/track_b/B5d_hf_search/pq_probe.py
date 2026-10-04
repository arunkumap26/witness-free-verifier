import json, sys, re, datetime as dt
import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem
from collections import Counter
repo, sha, path = sys.argv[1], sys.argv[2], sys.argv[3]
fs = HfFileSystem()
f = fs.open(f"datasets/{repo}@{sha}/{path}", "rb", block_size=4_000_000)
pf = pq.ParquetFile(f)
md = pf.metadata
print("rows", md.num_rows, "row_groups", md.num_row_groups, "rg0 bytes", md.row_group(0).total_byte_size)
batch = next(pf.iter_batches(batch_size=int(sys.argv[4]) if len(sys.argv) > 4 else 5))
rows = batch.to_pylist()
json.dump(rows, open("pq_sample_" + repo.replace("/", "__") + ".json", "w"), default=str)
print("sampled", len(rows))
