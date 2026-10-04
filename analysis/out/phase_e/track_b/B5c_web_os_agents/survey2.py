"""Field-audit survey of OSWorld-Verified zips via HTTP range reads.
For each zip: read central directory, pick k task dirs (deterministic: sorted, evenly spaced),
fetch traj.jsonl + runtime.log + result.txt into audit2/<idx>/<j>/, and grep id/usage/timestamp patterns."""
import sys, os, json, re, collections
from httpzip import open_zip
BASE = "https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/resolve/5473c39e42a538a187a9b2c2b499db59d560fd8c/"
PATS = {
    'anthropic_msg': r'msg_[A-Za-z0-9_]{10,}',
    'anthropic_toolu': r'toolu_[A-Za-z0-9_]{10,}',
    'anthropic_req': r'req_[A-Za-z0-9_]{10,}',
    'openai_resp': r'resp_[0-9a-f]{20,}',
    'openai_chatcmpl': r'chatcmpl-[A-Za-z0-9]{10,}',
    'openai_call_id': r'call_[A-Za-z0-9]{10,}',
    'request_id_key': r'(?i)request[_-]?id',
    'gemini_response_id': r'(?i)response_?id',
    'usage_metadata': r'usage_metadata|usageMetadata',
    'modality_IMAGE': r'IMAGE',
    'prompt_tokens': r'prompt_tokens|input_tokens|prompt_token_count',
    'completion_tokens': r'completion_tokens|output_tokens|candidates_token_count',
    'created_epoch': r"created['\"]?\s*[=:]\s*\d{10}",
    'log_ts_iso': r'\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d[,.]\d+',
    'log_ts_bracket': r'\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d',
}
def short(s):
    return re.sub(r'[^A-Za-z0-9._-]', '_', s)[:60]

def main(names, k, outroot):
    report = {}
    for zi, name in enumerate(names):
        rec = {'zip': name}
        try:
            f, z = open_zip(BASE + name)
        except Exception as e:
            rec['error'] = repr(e); report[name] = rec; print(name, 'ERR', e); continue
        il = z.infolist()
        trajs = sorted([i.filename for i in il if i.filename.endswith('traj.jsonl')])
        rec.update(zipsize=f.size, members=len(il), n_traj=len(trajs),
                   traj_bytes=sum(i.file_size for i in il if i.filename.endswith('traj.jsonl')),
                   runtime_log_bytes=sum(i.file_size for i in il if i.filename.endswith('runtime.log')),
                   png=sum(1 for i in il if i.filename.endswith('.png')),
                   mp4=sum(1 for i in il if i.filename.endswith('.mp4')),
                   other_basenames=dict(collections.Counter(
                       i.filename.rsplit('/', 1)[-1] for i in il
                       if not i.filename.endswith(('.png', '.mp4', '/'))
                       and not i.filename.rsplit('/', 1)[-1].startswith('step_')).most_common(12)),
                   sample_dir_example=os.path.dirname(trajs[0]) if trajs else None)
        picks = [trajs[int(j * len(trajs) / k)] for j in range(min(k, len(trajs)))]
        samples = []
        for j, t in enumerate(picks):
            d = os.path.dirname(t)
            od = os.path.join(outroot, f'{zi:02d}_{short(name)}', str(j))
            os.makedirs(od, exist_ok=True)
            s = {'dir': d}
            for suf in ('traj.jsonl', 'runtime.log', 'result.txt'):
                try:
                    data = z.read(d + '/' + suf)
                except KeyError:
                    continue
                open(os.path.join(od, suf), 'wb').write(data)
                s[suf + '_bytes'] = len(data)
                txt = data.decode('utf-8', 'replace')
                if suf == 'traj.jsonl':
                    rows = []
                    for line in txt.splitlines():
                        try: rows.append(json.loads(line))
                        except Exception: pass
                    s['traj_rows'] = len(rows)
                    s['traj_keys'] = sorted(set(kk for r in rows for kk in r))
                    s['ts_examples'] = [r.get('action_timestamp') for r in rows[:3]]
                    s['action_type_example'] = str(rows[0].get('action'))[:200] if rows else None
                    s['info_example'] = str(rows[0].get('info'))[:200] if rows else None
                s[suf + '_pats'] = {pk: len(re.findall(pv, txt)) for pk, pv in PATS.items()}
                s[suf + '_pat_examples'] = {pk: re.findall(pv, txt)[:2] for pk, pv in PATS.items() if re.findall(pv, txt)}
            samples.append(s)
        rec['samples'] = samples
        rec['bytes_read'] = f.nbytes
        report[name] = rec
        print(json.dumps(rec, indent=None)[:3000])
        print()
    return report

if __name__ == '__main__':
    k = int(sys.argv[1]); out = sys.argv[2]; names = sys.argv[3:]
    rep = main(names, k, out)
    tag = short(names[0])
    json.dump(rep, open(os.path.join(out, f'report_{tag}.json'), 'w'), indent=1)
