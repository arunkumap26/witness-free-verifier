"""B5c field audit + schema census of the corpora downloaded by Track B5c (descriptive only; no verdicts).

Reads (never writes) C:/Swarms/data/acquired/osworld_verified_trajs/* and C:/Swarms/data/acquired/webarena_infinity_trajs.
Writes analysis/out/phase_e/track_b/B5c_web_os_agents/b5c_field_audit.json.

Per corpus/submission it counts: task dirs, step rows, step keys, timestamp format + resolution, per-step call ids,
token-usage records, provider message/response/request ids and whether they decode to a time near the step clock,
log-line timestamps, error/truncation markers. Every number in the B5c evidence JSON that describes these corpora
comes from this script's output.
"""
import json, os, re, sys, glob, statistics, datetime as dt, collections

ROOT_OSW = 'C:/Swarms/data/acquired/osworld_verified_trajs'
ROOT_WAI = 'C:/Swarms/data/acquired/webarena_infinity_trajs'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'b5c_field_audit.json')

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58I = {c: i for i, c in enumerate(B58)}

PAT = {
    'anthropic_msg_bdrk': re.compile(r"msg_bdrk_[A-Za-z0-9]{10,}"),
    'anthropic_msg_1p': re.compile(r"msg_01[A-Za-z0-9]{10,}"),
    'anthropic_toolu': re.compile(r"toolu_(?:bdrk_)?[A-Za-z0-9]{10,}"),
    'anthropic_req': re.compile(r"req_(?:vrtx_)?[A-Za-z0-9]{10,}"),
    'openai_resp': re.compile(r"resp_[0-9a-f]{20,}"),
    'openai_chatcmpl': re.compile(r"chatcmpl-[A-Za-z0-9]{10,}"),
    'openai_call_id': re.compile(r"call_[A-Za-z0-9]{10,}"),
    'request_id_word': re.compile(r"(?i)request[_-]?id"),
    'usage_input_tokens': re.compile(r"input_tokens['\"]?\s*[=:]\s*\d+"),
    'usage_prompt_tokens': re.compile(r"prompt_tokens['\"]?\s*[=:]\s*\d+"),
    'log_ts_ms': re.compile(r"^\[?\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d[,.]\d{3}", re.M),
    'traceback': re.compile(r"Traceback \(most recent call last\)"),
    'llm_usage_logline_ms': re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} INFO engines/[^\]]*\] \[LMMEngine\w*\] usage:", re.M),
    'aws_x_amzn_requestid': re.compile(r"x-amzn-RequestId"),
}


def b58_top48_ms(body):
    if body[:2] != '01' or any(c not in B58I for c in body[2:]):
        return None
    v = 0
    for c in body[2:]:
        v = v * 58 + B58I[c]
    return v >> 80


def parse_osw_ts(s):
    if not isinstance(s, str) or '@' not in s:
        return None, None
    d, t = s.split('@', 1)
    try:
        if len(t) == 6:
            return dt.datetime.strptime(d + t, '%Y%m%d%H%M%S'), 's'
        if len(t) == 12:
            return dt.datetime.strptime(d + t, '%Y%m%d%H%M%S%f'), 'us'
    except ValueError:
        return None, 'unparsed'
    return None, f'len{len(t)}'


def q(xs):
    if not xs:
        return None
    xs = sorted(xs)
    return {'n': len(xs), 'p5': xs[int(0.05 * (len(xs) - 1))], 'p50': xs[int(0.5 * (len(xs) - 1))],
            'p95': xs[int(0.95 * (len(xs) - 1))], 'min': xs[0], 'max': xs[-1]}


def audit_osworld_submission(zdir):
    rec = collections.Counter()
    keys = collections.Counter()
    ts_res = collections.Counter()
    step_gaps = []
    pat_traj = collections.Counter(); pat_log = collections.Counter()
    tasks_with_id_in_action = 0
    steps_with_call_id = 0
    msg_decode = collections.Counter(); msg_offsets_h = []
    resp_decode = collections.Counter(); resp_offsets_s = []
    model_time = []
    step_id_vs_ts_s = []
    step_rows_messages_without_hexid = [0]
    tasks = sorted(glob.glob(os.path.join(zdir, 'tasks', '*', '*')))
    for td in tasks:
        tp = os.path.join(td, 'traj.jsonl')
        if not os.path.exists(tp):
            rec['task_dirs_without_traj'] += 1
            continue
        rec['task_dirs'] += 1
        txt = open(tp, encoding='utf-8', errors='replace').read()
        rows = []
        for line in txt.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rec['traj_lines_unparsed'] += 1
        rec['step_rows'] += len(rows)
        tss = []
        any_id = False
        for r in rows:
            for k in r:
                keys[k] += 1
            t, res = parse_osw_ts(r.get('action_timestamp'))
            ts_res[res or 'missing'] += 1
            if t:
                tss.append(t)
            a = r.get('action')
            a_s = json.dumps(a) if not isinstance(a, str) else a
            if re.search(r"toolu_|call_[A-Za-z0-9]{8,}", a_s or '') or (isinstance(a, dict) and (a.get('id') or a.get('call_id'))):
                steps_with_call_id += 1; any_id = True
            mu = r.get('model_usage')
            if isinstance(mu, dict) and isinstance(mu.get('model_time'), (int, float)):
                model_time.append(round(mu['model_time'], 3))
            # per-step join of a time-prefixed response-item id (Responses-API style: <prefix>_<8 hex epoch s><16 hex>)
            # found inside this step's own 'messages' to this step's action_timestamp (both read as UTC).
            if 'messages' in r and t is not None:
                m = re.search(r"\b(?:rs|msg|fc|resp)_([0-9a-f]{24})\b", json.dumps(r.get('messages')))
                if m:
                    sec = int(m.group(1)[:8], 16)
                    step_id_vs_ts_s.append(round(sec - (t - dt.datetime(1970, 1, 1)).total_seconds(), 3))
                else:
                    step_rows_messages_without_hexid[0] += 1
        tasks_with_id_in_action += any_id
        for a, b in zip(tss, tss[1:]):
            step_gaps.append(round((b - a).total_seconds(), 3))
        rec['tasks_ts_monotonic'] += all(b >= a for a, b in zip(tss, tss[1:])) if len(tss) > 1 else 0
        for k, p in PAT.items():
            pat_traj[k] += len(p.findall(txt))
        lp = os.path.join(td, 'runtime.log')
        if os.path.exists(lp):
            rec['runtime_logs'] += 1
            ltxt = open(lp, encoding='utf-8', errors='replace').read()
            if ltxt:
                rec['runtime_logs_nonempty'] += 1
            for k, p in PAT.items():
                pat_log[k] += len(p.findall(ltxt))
            both = txt + ltxt
            if tss:
                lo, hi = min(tss), max(tss)
                for mid in set(PAT['anthropic_msg_1p'].findall(both)):
                    ms = b58_top48_ms(mid.split('_', 1)[1])
                    if ms is None:
                        msg_decode['undecodable'] += 1; continue
                    t = dt.datetime.utcfromtimestamp(ms / 1000)
                    off = (t - lo).total_seconds() / 3600
                    msg_offsets_h.append(round(off, 3))
                    msg_decode['within_24h_of_task_clock' if -24 <= off <= 24 + (hi - lo).total_seconds() / 3600 else 'outside_24h'] += 1
                for mid in set(PAT['anthropic_msg_bdrk'].findall(both)):
                    ms = b58_top48_ms(mid.split('_', 2)[2])
                    if ms is None:
                        msg_decode['bdrk_undecodable'] += 1; continue
                    t = dt.datetime.utcfromtimestamp(ms / 1000) if 0 < ms < 4e12 else None
                    if t is None:
                        msg_decode['bdrk_out_of_range'] += 1; continue
                    off = (t - lo).total_seconds() / 3600
                    msg_decode['bdrk_within_24h' if -24 <= off <= 24 + (hi - lo).total_seconds() / 3600 else 'bdrk_outside_24h'] += 1
                rids = list(dict.fromkeys(PAT['openai_resp'].findall(both)))
                for rid in rids:
                    try:
                        sec = int(rid[5:13], 16)
                    except ValueError:
                        resp_decode['undecodable'] += 1; continue
                    t = dt.datetime.utcfromtimestamp(sec)
                    off = (t - lo).total_seconds()
                    resp_offsets_s.append(round(off, 1))
                    resp_decode['within_24h_of_task_clock' if -86400 <= off <= 86400 + (hi - lo).total_seconds() else 'outside_24h'] += 1
    return {
        'counts': dict(rec), 'step_keys': dict(keys.most_common()), 'timestamp_resolution': dict(ts_res),
        'steps_with_call_id_in_action': steps_with_call_id, 'tasks_with_call_id_in_action': tasks_with_id_in_action,
        'step_gap_seconds': q(step_gaps), 'pattern_counts_traj': dict(pat_traj), 'pattern_counts_runtime_log': dict(pat_log),
        'anthropic_msg_id_decode': dict(msg_decode), 'anthropic_msg_offset_hours_from_first_step': q(msg_offsets_h),
        'openai_resp_id_decode': dict(resp_decode), 'openai_resp_offset_seconds_from_first_step': q(resp_offsets_s),
        'model_time_seconds': q(model_time),
        'step_hexid_time_minus_action_timestamp_s': q(step_id_vs_ts_s),
        'step_hexid_abs_le_1s': sum(1 for x in step_id_vs_ts_s if abs(x) <= 1),
        'step_hexid_abs_le_60s': sum(1 for x in step_id_vs_ts_s if abs(x) <= 60),
        'step_rows_with_messages_but_no_hexid': step_rows_messages_without_hexid[0],
    }


def audit_wai():
    out = {}
    for model in sorted(os.listdir(os.path.join(ROOT_WAI, 'data'))) if os.path.isdir(os.path.join(ROOT_WAI, 'data')) else []:
        mdir = os.path.join(ROOT_WAI, 'data', model)
        if not os.path.isdir(mdir):
            continue
        rec = collections.Counter(); keys = collections.Counter(); meta_keys = collections.Counter(); res_keys = collections.Counter()
        durs = []; gaps = []
        for hp in sorted(glob.glob(os.path.join(mdir, '*', '*', 'history.json'))):
            rec['trajectories'] += 1
            try:
                h = json.load(open(hp, encoding='utf-8'))
            except Exception:
                rec['unparsed'] += 1; continue
            hist = h.get('history', []) if isinstance(h, dict) else h
            prev_end = None
            mono = True
            for st in hist:
                rec['steps'] += 1
                for k in st:
                    keys[k] += 1
                md = st.get('metadata') or {}
                for k in md:
                    meta_keys[k] += 1
                s0, s1 = md.get('step_start_time'), md.get('step_end_time')
                if isinstance(s0, (int, float)) and isinstance(s1, (int, float)):
                    rec['steps_with_start_end'] += 1
                    durs.append(round(s1 - s0, 3))
                    if prev_end is not None:
                        gaps.append(round(s0 - prev_end, 3))
                        if s0 < prev_end - 1e-6:
                            mono = False
                    prev_end = s1
                acts = ((st.get('model_output') or {}).get('action')) or []
                res = st.get('result') or []
                rec['actions'] += len(acts); rec['results'] += len(res)
                rec['steps_len_action_eq_len_result'] += (len(acts) == len(res))
                for r in res:
                    for k in r:
                        res_keys[k] += 1
                    if r.get('error'):
                        rec['results_with_error'] += 1
                    if r.get('extracted_content'):
                        rec['results_with_extracted_content'] += 1
            rec['trajectories_monotonic'] += mono
        out[model] = {'counts': dict(rec), 'step_keys': dict(keys.most_common()), 'metadata_keys': dict(meta_keys),
                      'result_keys': dict(res_keys.most_common()), 'step_duration_s': q(durs),
                      'inter_step_gap_s': q(gaps)}
    rp = glob.glob(os.path.join(ROOT_WAI, 'data', '*', '*', '*', 'result.json'))
    out['_result_json_files'] = len(rp)
    return out


def main():
    res = {'script': 'analysis/out/phase_e/track_b/B5c_web_os_agents/b5c_field_audit.py',
           'generated_utc': dt.datetime.utcnow().isoformat(timespec='seconds'), 'osworld_verified': {}, 'webarena_infinity': None}
    if os.path.isdir(ROOT_OSW):
        for zdir in sorted(glob.glob(os.path.join(ROOT_OSW, '*'))):
            if os.path.isdir(zdir) and os.path.exists(os.path.join(zdir, 'SOURCE.json')):
                res['osworld_verified'][os.path.basename(zdir)] = audit_osworld_submission(zdir)
    if os.path.isdir(ROOT_WAI):
        res['webarena_infinity'] = audit_wai()
    json.dump(res, open(OUT, 'w'), indent=1, default=str)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
