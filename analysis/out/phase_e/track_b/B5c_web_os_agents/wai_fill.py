"""Fill in missing WebArena-Infinity Gemini text files (history.json, result.json) + data/manifest.json
at the pinned revision, with backoff on HTTP 429. Verifies each file's git blob id (sha1 of 'blob <len>\\0'+content)
against the Hub listing, then writes a manifest with sha256. Never overwrites existing files."""
import json, os, time, hashlib, urllib.request, urllib.error
SHA = '73cf7f57a6ff61c95722a23bffdd9c1de4069bfe'
REPO = 'webarena-x/webarena-infinity-trajectories'
DEST = 'C:/Swarms/data/acquired/webarena_infinity_trajs'
sib = json.load(open(os.path.join(os.path.dirname(__file__), 'wai', 'siblings.json')))
want = [s for s in sib if s['path'] in ('README.md', 'data/manifest.json')
        or (s['path'].startswith('data/gemini/') and s['path'].endswith(('/history.json', '/result.json')))]

def gitblob(b):
    return hashlib.sha1(b'blob %d\x00' % len(b) + b).hexdigest()

rows = []; fetched = 0; verified_existing = 0; bad = []
for s in want:
    p = os.path.join(DEST, s['path'])
    if os.path.exists(p):
        b = open(p, 'rb').read()
        ok = (gitblob(b) == s['blobId']) or (s.get('lfs_sha256') and hashlib.sha256(b).hexdigest() == s['lfs_sha256'])
        if not ok: bad.append(s['path'])
        verified_existing += 1
    else:
        url = f'https://huggingface.co/datasets/{REPO}/resolve/{SHA}/{s["path"]}'
        for attempt in range(30):
            try:
                b = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'research-audit'}), timeout=120).read()
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(30); continue
                raise
        ok = (gitblob(b) == s['blobId']) or (s.get('lfs_sha256') and hashlib.sha256(b).hexdigest() == s['lfs_sha256'])
        if not ok: bad.append(s['path']); continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(b); fetched += 1
        time.sleep(0.1)
    rows.append({'path': s['path'], 'size': len(b), 'git_blob_sha1': s['blobId'], 'sha256': hashlib.sha256(b).hexdigest(), 'verified': ok})
with open(os.path.join(DEST, 'MANIFEST_b5c.jsonl'), 'a', encoding='utf-8') as fh:
    for r in rows: fh.write(json.dumps(r) + '\n')
json.dump({'repo': REPO, 'revision': SHA, 'licence': 'MIT (dataset card license: mit)',
           'subset_rule': 'README.md + data/manifest.json + data/gemini/*/*/{history.json,result.json}; screenshots and kimi/qwen histories NOT downloaded (kimi/qwen lack per-step timestamps: field audit fail)',
           'n_wanted': len(want), 'fetched_now': fetched, 'verified_existing': verified_existing, 'bad': bad,
           'bytes': sum(r['size'] for r in rows)}, open(os.path.join(DEST, 'SOURCE.json'), 'w'), indent=1)
print('wanted', len(want), 'fetched', fetched, 'existing', verified_existing, 'bad', len(bad))
