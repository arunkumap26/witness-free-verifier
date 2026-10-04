"""Provider-id clock checks on the acquired TB2 leaderboard subset (read-only; no corpus code executed).
(1) Anthropic requestId in native Claude Code JSONL (per submission): distinct ids, sessions, models, UUIDv7 decode,
    agreement with the carrying entry's timestamp in [-2 s, +600 s] (same window as b4.json).
(2) OpenAI Responses resp_ ids in hookele .hookele/traj.jsonl: hex50 layout (16-hex prefix, '00', 8-hex unix seconds,
    per B2a_provider_id_facts), checked against the harness llm_call ts (start) and stream_summary ts (end), 1 s resolution.
Usage: python id_clock_checks.py TB2_SUBMISSIONS_DIR OUT_JSON"""
import os, sys, json, glob, collections, datetime as dt

root, outp = sys.argv[1], sys.argv[2]
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58I = {c: i for i, c in enumerate(B58)}


def v7_ms(s):
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


def ts(t):
    return dt.datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()


def q(a, p):
    return a[int(p * (len(a) - 1))] if a else None


out = {'anthropic_requestId': {}, 'openai_resp_id_hookele': {}}
for sub in sorted(os.listdir(root)):
    files = glob.glob(os.path.join(root, sub, '**', 'sessions', 'projects', '**', '*.jsonl'), recursive=True)
    if not files:
        continue
    ids, sess, models, trials = set(), set(), collections.Counter(), set()
    n_ent = n_dec = n_agree = 0
    gaps = []
    per_session_ids = collections.Counter()
    for f in files:
        trials.add(os.path.normpath(os.path.relpath(f, os.path.join(root, sub))).split(os.sep)[1])
        for line in open(f, encoding='utf-8'):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get('sessionId'):
                sess.add(e['sessionId'])
            m = e.get('message')
            if isinstance(m, dict) and e.get('type') == 'assistant':
                models[m.get('model')] += 1
            rid = e.get('requestId')
            if not rid:
                continue
            n_ent += 1
            if rid not in ids:
                per_session_ids[e.get('sessionId')] += 1
            ids.add(rid)
            ms = v7_ms(rid)
            if ms is None:
                continue
            n_dec += 1
            if e.get('timestamp'):
                g = ts(e['timestamp']) * 1000 - ms
                gaps.append(g)
                if -2000 <= g <= 600000:
                    n_agree += 1
    gaps.sort()
    out['anthropic_requestId'][sub] = {
        'jsonl_files': len(files), 'trials_with_jsonl': len(trials), 'sessions': len(sess),
        'sessions_with_ge1_requestId': sum(1 for k, v in per_session_ids.items() if v > 0),
        'models_assistant_entries': dict(models.most_common(5)),
        'entries_with_requestId': n_ent, 'distinct_requestIds': len(ids), 'v7_decodable_entries': n_dec,
        'agree_event_minus_id_in_[-2s,+600s]': n_agree,
        'event_minus_id_ms_quantiles': {str(p): q(gaps, p) for p in (0, 0.01, 0.05, 0.5, 0.95, 0.99, 1)}}

rows = []
layouts = collections.Counter()
for f in glob.glob(os.path.join(root, 'hookele__gpt5.1-codex-mini', '**', '.hookele', 'traj.jsonl'), recursive=True):
    last = None
    for line in open(f, encoding='utf-8'):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get('type') == 'llm_call':
            last = e.get('ts')
        rid = e.get('response_id')
        if rid and e.get('type') == 'stream_summary':
            b = rid.split('_', 1)[1]
            if len(b) == 50 and b[16:18] == '00':
                layouts['hex50_prefix16_00_sec'] += 1
                sec = int(b[18:26], 16)
                end = ts(e['ts'])
                start = ts(last) if last else None
                rows.append((sec - start if start is not None else None, end - sec))
            else:
                layouts['other_len%d' % len(b)] += 1
a = sorted(x for x, _ in rows if x is not None)
b_ = sorted(y for _, y in rows)
out['openai_resp_id_hookele'] = {
    'stream_summary_rows_with_response_id': sum(layouts.values()), 'layouts': dict(layouts),
    'id_sec_minus_llm_call_ts_s_quantiles': {str(p): q(a, p) for p in (0, 0.01, 0.05, 0.5, 0.95, 0.99, 1)},
    'summary_ts_minus_id_sec_s_quantiles': {str(p): q(b_, p) for p in (0, 0.01, 0.05, 0.5, 0.95, 0.99, 1)},
    'bracketed_within_1s': sum(1 for x, y in rows if x is not None and x >= -1 and y >= -1),
    'n_with_start': sum(1 for x, _ in rows if x is not None), 'n': len(rows),
    'resolution': '1 s on both sides (hookele ts has no fractional seconds; id carries unix seconds)'}
json.dump(out, open(outp, 'w'), indent=1)
print(json.dumps(out, indent=1))
