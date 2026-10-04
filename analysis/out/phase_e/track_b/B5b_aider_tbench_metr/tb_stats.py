"""Schema/field census over a Harbor-format job tree (TB2 leaderboard subset or a single Harbor job dir).
Usage: python tb_stats.py ROOT OUT_JSON. Reads only; executes nothing from the corpus."""
import os, sys, json, re, collections, datetime as dt

root, outp = sys.argv[1], sys.argv[2]
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58I = {c: i for i, c in enumerate(B58)}


def dec_req(s):
    try:
        body = s.rsplit('_', 1)[1]
        if body[:2] != '01':
            return None
        v = 0
        for ch in body[2:]:
            v = v * 58 + B58I[ch]
        if (v >> 76) & 0xF != 7 or (v >> 62) & 3 != 2:
            return None
        return v >> 80
    except Exception:
        return None


def iso_ms(t):
    try:
        return dt.datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp() * 1000
    except Exception:
        return None


def sub_of(rel):
    parts = rel.split('/')
    if len(parts) > 3 and parts[0] == 'submissions':
        return parts[3]
    return parts[0]


S = collections.defaultdict(collections.Counter)
FR = collections.defaultdict(collections.Counter)
MODELS = collections.defaultdict(collections.Counter)
REQ_GAPS = []
for r, ds, fs in os.walk(root):
    ds[:] = [d for d in ds if d != '.git']
    for f in fs:
        p = os.path.join(r, f)
        rel = os.path.relpath(p, root).replace(os.sep, '/')
        sub = sub_of(rel)
        c = S[sub]
        try:
            if f == 'result.json' and '/agent/' not in rel:
                d = json.load(open(p, encoding='utf-8'))
                if 'trial_name' in d:
                    c['trials'] += 1
                    md = ((d.get('agent_result') or {}).get('metadata') or {})
                    if isinstance(md, dict) and md.get('api_request_times_msec'):
                        c['trials_with_api_request_times_msec'] += 1
                        c['api_request_times_n'] += len(md['api_request_times_msec'])
                    if (d.get('agent_execution') or {}).get('started_at'):
                        c['trials_with_agent_execution_window'] += 1
                    if d.get('exception_info'):
                        c['trials_with_exception'] += 1
                    mi = (d.get('agent_info') or {}).get('model_info') or {}
                    MODELS[sub]['%s/%s' % (mi.get('provider'), mi.get('name'))] += 1
                else:
                    c['job_results'] += 1
            elif f == 'trajectory.json' and rel.endswith('/agent/trajectory.json'):
                d = json.load(open(p, encoding='utf-8'))
                st = d.get('steps') or []
                c['atif_files'] += 1
                c['atif_steps'] += len(st)
                c['atif_schema:' + str(d.get('schema_version'))] += 1
                ids = set()
                prev = None
                mono = True
                for s in st:
                    t = s.get('timestamp')
                    if t:
                        c['atif_steps_with_ts'] += 1
                        m = re.search(r'T\d\d:\d\d:\d\d(?:\.(\d+))?', t)
                        FR[sub][len(m.group(1)) if m and m.group(1) else 0] += 1
                        ms = iso_ms(t)
                        if ms is not None and prev is not None and ms < prev:
                            mono = False
                        if ms is not None:
                            prev = ms
                    for tc in s.get('tool_calls') or []:
                        c['atif_tool_calls'] += 1
                        ids.add(tc.get('tool_call_id'))
                    ob = s.get('observation') or {}
                    for o in ((ob.get('results') or []) if isinstance(ob, dict) else []):
                        c['atif_obs_results'] += 1
                        sc = o.get('source_call_id')
                        if sc in ids:
                            c['atif_obs_joined_by_id'] += 1
                        elif sc is None:
                            c['atif_obs_no_id'] += 1
                        else:
                            c['atif_obs_dangling_id'] += 1
                    if s.get('metrics'):
                        c['atif_steps_with_metrics'] += 1
                if not mono:
                    c['atif_files_nonmonotonic_ts'] += 1
            elif f.endswith('.jsonl') and '/sessions/projects/' in rel:
                c['cc_jsonl_files'] += 1
                tu = set()
                tr = set()
                for line in open(p, encoding='utf-8'):
                    if not line.strip():
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        c['cc_bad_lines'] += 1
                        continue
                    c['cc_entries'] += 1
                    if e.get('timestamp'):
                        c['cc_entries_with_ts'] += 1
                    rid = e.get('requestId')
                    if rid:
                        c['cc_entries_with_requestId'] += 1
                        ms = dec_req(rid)
                        ev = iso_ms(e.get('timestamp') or '')
                        if ms is not None:
                            c['cc_requestId_v7_decodable'] += 1
                            if ev is not None:
                                REQ_GAPS.append(ev - ms)
                                if -2000 <= ev - ms <= 600000:
                                    c['cc_requestId_agrees_event_-2s_+600s'] += 1
                    m = e.get('message')
                    if isinstance(m, dict):
                        if e.get('type') == 'assistant' and m.get('model'):
                            MODELS[sub + ':cc'][m.get('model')] += 1
                        cont = m.get('content')
                        if isinstance(cont, list):
                            for b in cont:
                                if isinstance(b, dict):
                                    if b.get('type') == 'tool_use':
                                        tu.add(b.get('id'))
                                    elif b.get('type') == 'tool_result':
                                        tr.add(b.get('tool_use_id'))
                c['cc_tool_use'] += len(tu)
                c['cc_tool_result'] += len(tr)
                c['cc_joined'] += len(tu & tr)
            elif f == 'gemini-cli.trajectory.json':
                d = json.load(open(p, encoding='utf-8'))
                c['gemini_files'] += 1
                for m in d.get('messages') or []:
                    c['gemini_messages'] += 1
                    if m.get('timestamp'):
                        c['gemini_messages_with_ts'] += 1
                    for tc in m.get('toolCalls') or []:
                        c['gemini_tool_calls'] += 1
                        if tc.get('timestamp'):
                            c['gemini_tool_calls_with_ts'] += 1
                        res = tc.get('result') or []
                        if any(((x.get('functionResponse') or {}).get('id') == tc.get('id')) for x in res if isinstance(x, dict)):
                            c['gemini_tool_calls_result_joined'] += 1
            elif f == 'traj.jsonl' and '/.hookele/' in rel:
                c['hookele_files'] += 1
                for line in open(p, encoding='utf-8'):
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get('type') == 'tool_execution':
                        c['hookele_tool_exec'] += 1
                        c['hookele_tool_exec_with_call_id'] += bool(e.get('call_id'))
                    if e.get('response_id'):
                        c['hookele_response_ids'] += 1
            elif f == 'recording.cast':
                c['cast_files'] += 1
                with open(p, encoding='utf-8', errors='replace') as h:
                    hdr = json.loads(h.readline())
                    if 'timestamp' in hdr:
                        c['cast_with_header_epoch'] += 1
                    for _ in h:
                        c['cast_events'] += 1
        except Exception:
            c['parse_errors'] += 1

out = {'per_unit': {k: dict(v) for k, v in sorted(S.items())},
       'atif_ts_fraction_digits': {k: dict(v) for k, v in FR.items()},
       'models': {k: dict(v) for k, v in MODELS.items()}}
if REQ_GAPS:
    g = sorted(REQ_GAPS)
    out['requestId_event_minus_id_ms_quantiles'] = {q: g[int(q * (len(g) - 1))] for q in (0.0, 0.01, 0.05, 0.5, 0.95, 0.99, 1.0)}
    out['requestId_event_minus_id_n'] = len(g)
tot = collections.Counter()
for v in S.values():
    tot.update(v)
out['totals'] = dict(tot)
json.dump(out, open(outp, 'w'), indent=1)
print(json.dumps(out['totals'], indent=1))
