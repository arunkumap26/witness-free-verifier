# B6 feasibility: key-NAME census of the user's local Codex rollouts (~/.codex/sessions).
# Aggregates only: no values are read out, and any key that is not an identifier (e.g. a file path used as a dict key)
# is masked as <non-identifier-key>, so no private path or content reaches the output.
# Question answered: does the standard (non-trace) Codex rollout record any provider request id / trace id / header?
import json, os, glob, re, collections, sys
root = os.path.expanduser('~/.codex/sessions')
files = sorted(glob.glob(os.path.join(root, '**', '*.jsonl'), recursive=True))
rx = re.compile(r'(request|req_id|trace|cf.?ray|rate.?limit|resets|header|server.?timing|date)', re.I)
keys = collections.Counter(); files_with = collections.Counter(); types = collections.Counter()
lines = 0; bad = 0; months = collections.Counter()
def walk(o, path, seen):
    if isinstance(o, dict):
        for k, v in o.items():
            kk = k if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_\-]{0,63}', k) else '<non-identifier-key>'
            p = path + '.' + kk
            if rx.search(kk): seen.add(p)
            walk(v, p, seen)
    elif isinstance(o, list):
        for v in o[:50]: walk(v, path + '[]', seen)
for f in files:
    m = re.search(r'(\d{4})[\/](\d{2})[\/]', f)
    if m: months[m.group(1) + '-' + m.group(2)] += 1
    seen = set()
    try:
        with open(f, encoding='utf-8', errors='replace') as fh:
            for ln in fh:
                lines += 1
                try: o = json.loads(ln)
                except Exception: bad += 1; continue
                t = (o.get('type'), (o.get('payload') or {}).get('type') if isinstance(o.get('payload'), dict) else None)
                types[t] += 1
                s = set(); walk(o, '', s)
                for p in s: keys[p] += 1
                seen |= s
    except Exception as e:
        bad += 1
    for p in seen: files_with[p] += 1
out = {'files': len(files), 'lines': lines, 'unparsable': bad,
       'matching_key_paths_lines': dict(keys.most_common(60)),
       'matching_key_paths_files': dict(files_with.most_common(60)),
       'top_record_types': {str(k): v for k, v in types.most_common(25)}}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'codex_keycensus.json'), 'w'), indent=1)
print(json.dumps(out, indent=1)[:4000])
