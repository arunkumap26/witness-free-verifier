"""Peek at all non-image members of the first (or n-th) task dir of an OSWorld zip. Usage: peek.py <zip> <outdir> [nth] [maxchars]"""
import sys, os, re, json
from httpzip import open_zip
SHA = "5473c39e42a538a187a9b2c2b499db59d560fd8c"
BASE = f"https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/resolve/{SHA}/"
name, out = sys.argv[1], sys.argv[2]
nth = int(sys.argv[3]) if len(sys.argv) > 3 else 0
maxc = int(sys.argv[4]) if len(sys.argv) > 4 else 1500
f, z = open_zip(BASE + name)
il = [i for i in z.infolist() if not i.filename.startswith('__MACOSX') and not i.filename.endswith('/')]
dirs = sorted(set(i.filename.rsplit('/', 1)[0] for i in il if not i.filename.endswith(('.png', '.mp4'))))
# choose dirs that look like task dirs (contain result.txt or traj.jsonl or events.json)
cand = [d for d in dirs if any(i.filename.startswith(d + '/') and i.filename.rsplit('/', 1)[-1] in ('result.txt', 'traj.jsonl', 'events.json') for i in il)]
d = cand[min(nth, len(cand) - 1)] if cand else dirs[0]
print('DIR', d)
os.makedirs(out, exist_ok=True)
for i in il:
    if i.filename.rsplit('/', 1)[0] != d or i.filename.endswith(('.png', '.mp4', '.gz', '.zip')):
        continue
    if i.file_size > 30_000_000:
        print('SKIP big', i.filename, i.file_size); continue
    data = z.read(i.filename)
    b = i.filename.rsplit('/', 1)[-1]
    open(os.path.join(out, re.sub(r'[^A-Za-z0-9._-]', '_', b)), 'wb').write(data)
    print('-----', b, i.file_size)
    print(data[:maxc].decode('utf-8', 'replace'))
print('bytes_read', f.nbytes)
