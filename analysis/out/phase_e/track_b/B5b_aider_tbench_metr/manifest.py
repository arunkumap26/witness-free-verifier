"""Write <root>/_acquisition/FILES_SHA256.jsonl (path, bytes, sha256) for every file under <root>/<sub> (skips .git)."""
import os, sys, json, hashlib
root, sub = sys.argv[1], sys.argv[2]
outp = os.path.join(root, '_acquisition', sys.argv[3] if len(sys.argv) > 3 else 'FILES_SHA256.jsonl')
os.makedirs(os.path.dirname(outp), exist_ok=True)
n = 0; tot = 0; agg = hashlib.sha256()
rows = []
for r, ds, fs in os.walk(os.path.join(root, sub)):
    ds[:] = [d for d in ds if d != '.git']
    for f in fs:
        p = os.path.join(r, f)
        h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
        rel = os.path.relpath(p, root).replace(os.sep, '/')
        rows.append((rel, os.path.getsize(p), h))
rows.sort()
with open(outp, 'w', encoding='utf-8') as o:
    for rel, s, h in rows:
        o.write(json.dumps({'path': rel, 'bytes': s, 'sha256': h}) + '\n'); n += 1; tot += s; agg.update((rel + h).encode())
print(json.dumps({'files': n, 'bytes': tot, 'manifest': outp, 'aggregate_sha256': agg.hexdigest()}))
