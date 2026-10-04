"""Replace git-lfs pointer files (listed in PTRLIST, paths relative to REPO_DIR) with their content,
via the git-lfs batch API of a HF dataset repo. Verifies sha256 == oid before writing. Logs to LOG (jsonl).
Usage: python lfs_fetch.py HF_REPO_ID REPO_DIR PTRLIST LOG [WORKERS]"""
import sys, os, json, hashlib, time, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
rid, repo_dir, ptrlist, logp = sys.argv[1:5]
workers = int(sys.argv[5]) if len(sys.argv) > 5 else 8
paths = [l.strip() for l in open(ptrlist, encoding='utf-8') if l.strip()]
done = set()
if os.path.exists(logp):
    for l in open(logp, encoding='utf-8'):
        r = json.loads(l)
        if r.get('ok'): done.add(r['path'])
objs = []
for p in paths:
    if p in done: continue
    fp = os.path.join(repo_dir, *p.split('/'))
    txt = open(fp, 'rb').read(400)
    if not txt.startswith(b'version https://git-lfs'): continue
    d = dict(l.split(' ', 1) for l in txt.decode().strip().splitlines())
    objs.append((p, d['oid'].split(':', 1)[1], int(d['size'])))
print('to fetch', len(objs), 'GB', sum(o[2] for o in objs) / 1e9, flush=True)
lock = threading.Lock(); logf = open(logp, 'a', encoding='utf-8')
batch_url = f'https://huggingface.co/datasets/{rid}.git/info/lfs/objects/batch'
H = {'Accept': 'application/vnd.git-lfs+json', 'Content-Type': 'application/vnd.git-lfs+json', 'User-Agent': 'git-lfs/3.7.1'}
def get_hrefs(chunk):
    body = json.dumps({'operation': 'download', 'transfers': ['basic'], 'objects': [{'oid': o, 'size': s} for _, o, s in chunk]}).encode()
    for a in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request(batch_url, data=body, headers=H, method='POST'), timeout=120)
            res = json.load(r)
            return {o['oid']: o for o in res['objects']}
        except urllib.error.HTTPError as e:
            time.sleep(30 * (a + 1) if e.code == 429 else 5 * (a + 1))
        except Exception:
            time.sleep(5 * (a + 1))
    return {}
stats = {'ok': 0, 'bad': 0, 'bytes': 0}
def fetch(item, info):
    p, oid, size = item
    act = (info or {}).get('actions', {}).get('download')
    if not act:
        with lock: logf.write(json.dumps({'path': p, 'oid': oid, 'ok': False, 'err': str(info.get('error') if info else 'no info')}) + '\n'); stats['bad'] += 1
        return
    for a in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(act['href'], headers={**act.get('header', {}), 'User-Agent': 'git-lfs/3.7.1'}), timeout=300)
            data = r.read()
            h = hashlib.sha256(data).hexdigest()
            if h != oid or len(data) != size:
                raise ValueError('hash/size mismatch')
            fp = os.path.join(repo_dir, *p.split('/'))
            with open(fp, 'wb') as f: f.write(data)
            with lock:
                logf.write(json.dumps({'path': p, 'oid': oid, 'bytes': size, 'ok': True}) + '\n'); stats['ok'] += 1; stats['bytes'] += size
            return
        except Exception as e:
            err = str(e); time.sleep(5 * (a + 1))
    with lock: logf.write(json.dumps({'path': p, 'oid': oid, 'ok': False, 'err': err}) + '\n'); stats['bad'] += 1
t0 = time.time()
with ThreadPoolExecutor(workers) as ex:
    for i in range(0, len(objs), 100):
        chunk = objs[i:i + 100]
        infos = get_hrefs(chunk)
        list(ex.map(lambda it: fetch(it, infos.get(it[1])), chunk))
        with lock:
            logf.flush(); print(f"t={time.time()-t0:.0f}s ok={stats['ok']} bad={stats['bad']} GB={stats['bytes']/1e9:.3f}", flush=True)
print('DONE', stats, flush=True)
