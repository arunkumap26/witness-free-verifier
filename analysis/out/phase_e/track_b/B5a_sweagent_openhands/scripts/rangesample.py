"""Fetch only the first N bytes of a remote file (HTTP Range) for a field audit. Usage: rangesample.py <url> <out> [nbytes]"""
import sys, urllib.request

url, out = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 4_000_000
req = urllib.request.Request(url, headers={"User-Agent": "b5a-audit", "Range": f"bytes=0-{n-1}"})
r = urllib.request.urlopen(req, timeout=300)
b = r.read()
open(out, "wb").write(b)
print(r.status, len(b), r.headers.get("Content-Range"))
