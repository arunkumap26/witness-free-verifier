"""HF datasets-server /rows (a few rows only, read-only) for a field audit. Usage: dsrows.py <repo> <config> <split> <offset> <length> <out>"""
import json, sys, urllib.request, urllib.parse

repo, config, split, off, ln, out = sys.argv[1:7]
url = ("https://datasets-server.huggingface.co/rows?" +
       urllib.parse.urlencode({"dataset": repo, "config": config, "split": split, "offset": off, "length": ln}))
req = urllib.request.Request(url, headers={"User-Agent": "b5a-audit"})
d = json.loads(urllib.request.urlopen(req, timeout=180).read())
json.dump(d, open(out, "w"), indent=1)
print("rows:", len(d.get("rows", [])), "truncated:", [r.get("truncated_cells") for r in d.get("rows", [])],
      "num_rows_total:", d.get("num_rows_total"))
