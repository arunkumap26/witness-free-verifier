"""Download an explicit list of files from a HF dataset repo at a pinned revision.
Usage: python hf_fetch.py REPO_ID REVISION SELECTION_JSON DEST_DIR [WORKERS]
Writes DEST_DIR/<path>; appends {path,bytes,sha256,status} to DEST_DIR/_acquisition/MANIFEST.jsonl.
Skips files already present with a manifest entry (resume). Never deletes anything. Executes no downloaded content."""
import sys, os, json, time, hashlib, threading, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from huggingface_hub import get_token
rid, rev, selfile, dest = sys.argv[1:5]
workers = int(sys.argv[5]) if len(sys.argv) > 5 else 12
sel = json.load(open(selfile, encoding='utf-8'))
os.makedirs(os.path.join(dest, '_acquisition'), exist_ok=True)
manp = os.path.join(dest, '_acquisition', 'MANIFEST.jsonl')
done = set()
if os.path.exists(manp):
    for l in open(manp, encoding='utf-8'):
        try:
            r = json.loads(l)
            if r.get('status') == 200: done.add(r['path'])
        except Exception: pass
todo = [p for p in sel if p not in done]
print(f'selection {len(sel)}, already {len(done)}, todo {len(todo)}', flush=True)
tok = get_token()
lock = threading.Lock()
manf = open(manp, 'a', encoding='utf-8')
stats = {'ok': 0, 'err': 0, 'bytes': 0, '429': 0}
t0 = time.time()
def one(p):
    url = f'https://huggingface.co/datasets/{rid}/resolve/{rev}/' + urllib.parse.quote(p)
    hdr = {'User-Agent': 'research-corpus-audit'}
    if tok: hdr['Authorization'] = 'Bearer ' + tok
    for attempt in range(8):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=120)
            data = r.read()
            out = os.path.join(dest, *p.split('/'))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, 'wb') as f: f.write(data)
            rec = {'path': p, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'status': 200}
            with lock:
                manf.write(json.dumps(rec) + '\n'); stats['ok'] += 1; stats['bytes'] += len(data)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                ra = e.headers.get('Retry-After')
                with lock: stats['429'] += (e.code == 429)
                time.sleep(min(300, float(ra) if ra and ra.isdigit() else 20 * (attempt + 1)))
                continue
            with lock:
                manf.write(json.dumps({'path': p, 'status': e.code}) + '\n'); stats['err'] += 1
            return
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    with lock:
        manf.write(json.dumps({'path': p, 'status': 'failed'}) + '\n'); stats['err'] += 1
def progress():
    while True:
        time.sleep(60)
        with lock:
            print(f"t={time.time()-t0:.0f}s ok={stats['ok']} err={stats['err']} 429={stats['429']} GB={stats['bytes']/1e9:.3f}", flush=True)
            manf.flush()
threading.Thread(target=progress, daemon=True).start()
with ThreadPoolExecutor(workers) as ex:
    list(ex.map(one, todo))
manf.close()
print(f"DONE t={time.time()-t0:.0f}s ok={stats['ok']} err={stats['err']} 429={stats['429']} GB={stats['bytes']/1e9:.3f}", flush=True)
