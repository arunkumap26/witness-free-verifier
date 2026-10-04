"""Tiny fetch helper: python get.py URL [OUTFILE] [MAXBYTES]. Prints status, size, sha256. Read-only GET."""
import sys, urllib.request, hashlib, json, os
url = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != '-' else None
maxb = int(sys.argv[3]) if len(sys.argv) > 3 else 50_000_000
hdr = {'User-Agent': 'research-audit'}
tok = None
req = urllib.request.Request(url, headers=hdr)
try:
    r = urllib.request.urlopen(req, timeout=60)
    data = r.read(maxb)
    status = r.status
except urllib.error.HTTPError as e:
    status = e.code; data = e.read(4000)
h = hashlib.sha256(data).hexdigest()
if out:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, 'wb').write(data)
    print(json.dumps({'url': url, 'status': status, 'bytes': len(data), 'sha256': h, 'out': out}))
else:
    sys.stdout.buffer.write(data)
    sys.stderr.write(json.dumps({'url': url, 'status': status, 'bytes': len(data), 'sha256': h}) + '\n')
