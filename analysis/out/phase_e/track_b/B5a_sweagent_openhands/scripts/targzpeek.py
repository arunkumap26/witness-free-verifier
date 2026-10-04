"""Peek the first members of a remote .tar.gz using only the first N bytes (HTTP Range); nothing is extracted to disk
except a small text dump of the first member(s). Usage: targzpeek.py <url> <out_prefix> [nbytes]"""
import sys, zlib, tarfile, io, urllib.request

url, outp = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 6_000_000
h = urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": "b5a-audit"}), timeout=60)
print("HEAD", h.status, "len", h.headers.get("Content-Length"), "type", h.headers.get("Content-Type"),
      "last-mod", h.headers.get("Last-Modified"))
r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "b5a-audit", "Range": f"bytes=0-{n-1}"}), timeout=300)
raw = r.read()
d = zlib.decompressobj(16 + zlib.MAX_WBITS)
data = d.decompress(raw)
print("compressed", len(raw), "decompressed", len(data))
bio = io.BytesIO(data)
names = []
try:
    tf = tarfile.open(fileobj=bio, mode="r|")
    for m in tf:
        names.append((m.name, m.size))
        if m.isfile() and len([x for x in names if x[1] > 0]) <= 3:
            f = tf.extractfile(m)
            b = f.read() if f else b""
            open(f"{outp}.{len(names)}.member", "wb").write(b)
except Exception as e:
    print("stopped:", type(e).__name__, e)
for nm, sz in names[:40]:
    print(f"  {sz:>10d} {nm}")
print("members seen:", len(names))
