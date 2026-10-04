"""Central-directory census of every zip in xlangai/ubuntu_osworld_verified_trajs @ pinned sha (range reads only)."""
import json, sys, collections
from concurrent.futures import ThreadPoolExecutor
from httpzip import open_zip
SHA = "5473c39e42a538a187a9b2c2b499db59d560fd8c"
BASE = f"https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/resolve/{SHA}/"

def census(name):
    try:
        f, z = open_zip(BASE + name)
    except Exception as e:
        return name, {'error': repr(e)}
    il = z.infolist()
    rec = collections.Counter(); byt = collections.Counter()
    trajdirs = set()
    for i in il:
        fn = i.filename
        if fn.startswith('__MACOSX/') or fn.rsplit('/', 1)[-1].startswith('._'):
            rec['macosx_junk'] += 1; continue
        b = fn.rsplit('/', 1)[-1]
        if fn.endswith('/'): continue
        if b.endswith('.png'): k = 'png'
        elif b.endswith('.mp4'): k = 'mp4'
        elif b in ('traj.jsonl', 'runtime.log', 'result.txt'): k = b
        elif b.endswith('.json'): k = 'json:' + b
        else: k = 'other:' + (b.rsplit('.', 1)[-1] if '.' in b else b)
        rec[k] += 1; byt[k] += i.file_size
        if b == 'traj.jsonl': trajdirs.add(fn.rsplit('/', 1)[0])
    text_bytes = sum(v for k, v in byt.items() if k not in ('png', 'mp4'))
    return name, {'zip_bytes': f.size, 'members': len(il), 'counts': dict(rec), 'bytes': dict(byt),
                  'n_traj': len(trajdirs), 'text_bytes': text_bytes, 'cd_bytes_read': f.nbytes}

if __name__ == '__main__':
    names = [l.split()[0] for l in open(sys.argv[1]) if l.strip().endswith(tuple('0123456789')) and '.zip' in l]
    with ThreadPoolExecutor(8) as ex:
        res = dict(ex.map(census, names))
    json.dump({'repo': 'xlangai/ubuntu_osworld_verified_trajs', 'sha': SHA, 'zips': res}, open(sys.argv[2], 'w'), indent=1)
    tot = sum(r.get('text_bytes', 0) for r in res.values())
    print('zips', len(res), 'errors', sum('error' in r for r in res.values()), 'total_traj', sum(r.get('n_traj', 0) for r in res.values()), 'text_bytes', tot)
