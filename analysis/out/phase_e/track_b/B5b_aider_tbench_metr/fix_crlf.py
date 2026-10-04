"""Restore byte-exact upstream content for files that git's core.autocrlf=true converted LF->CRLF at checkout.
For every non-LFS file present in the work tree, read the committed blob with `git cat-file --batch` and, if the
work-tree bytes differ, overwrite them with the blob bytes. LFS-fetched files (already sha256-verified against their
oid) are skipped. Logs every rewrite to LOG (jsonl). Usage: python fix_crlf.py REPO_DIR LFS_LOG LOG"""
import os, sys, json, subprocess, hashlib

repo, lfs_log, logp = sys.argv[1:4]
lfs = set()
for l in open(lfs_log, encoding='utf-8'):
    r = json.loads(l)
    if r.get('ok'):
        lfs.add(r['path'])
ls = subprocess.run(['git', '-C', repo, 'ls-tree', '-r', '-z', 'HEAD'], capture_output=True, check=True).stdout
items = []
for ent in ls.split(b'\0'):
    if not ent:
        continue
    meta, path = ent.split(b'\t', 1)
    mode, typ, sha = meta.split()
    p = path.decode('utf-8')
    if typ != b'blob' or p in lfs:
        continue
    fp = os.path.join(repo, *p.split('/'))
    if os.path.exists(fp):
        items.append((p, sha.decode(), fp))
print('candidates', len(items), flush=True)
proc = subprocess.Popen(['git', '-C', repo, 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
fixed = same = 0
with open(logp, 'a', encoding='utf-8') as log:
    for p, sha, fp in items:
        proc.stdin.write((sha + '\n').encode()); proc.stdin.flush()
        hdr = proc.stdout.readline().split()
        size = int(hdr[2])
        blob = proc.stdout.read(size); proc.stdout.read(1)
        cur = open(fp, 'rb').read()
        if cur == blob:
            same += 1
            continue
        with open(fp, 'wb') as f:
            f.write(blob)
        fixed += 1
        log.write(json.dumps({'path': p, 'blob': sha, 'before_bytes': len(cur), 'after_bytes': len(blob),
                              'after_sha256': hashlib.sha256(blob).hexdigest(), 'reason': 'undo core.autocrlf LF->CRLF checkout conversion'}) + '\n')
proc.stdin.close(); proc.wait()
print(json.dumps({'checked': len(items), 'already_exact': same, 'restored': fixed}))
