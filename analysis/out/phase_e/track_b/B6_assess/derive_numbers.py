# B6: derive every number the B6 memo quotes from existing outputs. No new measurement of any corpus.
# Inputs (read-only):
#   analysis/out/phase_e/track_b/b4.json                (B4 inventory evidence, Phase E; probe analysis/probes/phase_e_b4_inventory.py)
#   analysis/out/phase_c/ids_and_clocks_in_ids.json      (committed in 15324cc)
#   analysis/out/phase_e/track_b/B5e_cli_traces/census/hf_census_summary.json   (B5e, in progress at 2026-10-04 02:43 CDT)
#   analysis/out/phase_e/track_b/B6_assess/codex_keycensus.json                (this task)
# Output: analysis/out/phase_e/track_b/B6_assess/derived.json
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))  # worktree root


def load(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return json.load(f)


b4 = load('analysis/out/phase_e/track_b/b4.json')
pc = load('analysis/out/phase_c/ids_and_clocks_in_ids.json')
hf = load('analysis/out/phase_e/track_b/B5e_cli_traces/census/hf_census_summary.json')
cx = load('analysis/out/phase_e/track_b/B6_assess/codex_keycensus.json')

rid = b4['REQUEST_ID_COLUMN_FIRST']
pcs = rid['per_corpus']
sw = pcs['swechat/claude_code']
cc = pcs['cc_local']

out = {}
out['request_ids_in_claude_code_jsonl'] = {
    'swechat_claude_code_calls_with_request_id': sw['calls_with_request_id'],
    'swechat_claude_code_responses_with_request_id': sw['responses_with_request_id'],
    'swechat_claude_code_distinct_request_ids': sw['distinct_request_ids'],
    'swechat_claude_code_v7_decodable': sw['decodable_time']['rfc9562_v7_version_and_variant_bits'],
    'swechat_bedrock_calls_without_request_id': sw['calls_by_backend']['anthropic_bedrock'],
    'cc_local_calls_with_request_id': cc['calls_with_request_id'],
    'cc_local_responses_with_request_id': cc['responses_with_request_id'],
    'cc_local_distinct_request_ids': cc['distinct_request_ids'],
    'corpora_with_request_ids_strict': rid['corpora_carrying_provider_request_ids'],
    'source': 'analysis/out/phase_e/track_b/b4.json#REQUEST_ID_COLUMN_FIRST',
}
# mean API responses per session = proxy for API requests a session costs (human-driven sessions, not benchmark tasks)
out['mean_responses_per_session'] = {
    'swechat_claude_code': round(sw['responses_with_request_id']['n'] / sw['responses_with_request_id']['n_sessions'], 1),
    'swechat_n_responses': sw['responses_with_request_id']['n'],
    'swechat_n_sessions': sw['responses_with_request_id']['n_sessions'],
    'cc_local': round(cc['responses_with_request_id']['n'] / cc['responses_with_request_id']['n_sessions'], 1),
    'cc_local_n_responses': cc['responses_with_request_id']['n'],
    'cc_local_n_sessions': cc['responses_with_request_id']['n_sessions'],
    'note': 'Means over sessions as B4 counted them (cc_local counts subagent files as sessions). Descriptive only; a benchmark task is not a human session.',
}
bits = pc['bits']
out['committed_phase_c_decode'] = {
    'swechat_req_v7': bits['swechat']['anthropic_req']['time_format']['uuid_fields']['n_version7_variant2'],
    'swechat_req_n': bits['swechat']['anthropic_req']['time_format']['n'],
    'cc_local_req_v7': bits['cc_local']['anthropic_req']['time_format']['uuid_fields']['n_version7_variant2'],
    'cc_local_req_n': bits['cc_local']['anthropic_req']['time_format']['n'],
    'source': 'analysis/out/phase_c/ids_and_clocks_in_ids.json#bits.<corpus>.anthropic_req.time_format (commit 15324cc)',
}
cc_hf = hf['by_harness_class']['claude_code']
out['public_hf_raw_claude_code_files_B5e'] = {
    'permissive_licence_datasets': cc_hf.get('open|permissive_or_copyleft|datasets'),
    'permissive_licence_files': cc_hf.get('open|permissive_or_copyleft|files'),
    'permissive_licence_bytes': cc_hf.get('open|permissive_or_copyleft|bytes'),
    'no_licence_datasets': cc_hf.get('open|none|datasets'),
    'no_licence_files': cc_hf.get('open|none|files'),
    'request_id_presence_audited': False,
    'source': 'analysis/out/phase_e/track_b/B5e_cli_traces/census/hf_census_summary.json#by_harness_class.claude_code (B5e in progress; file-format census only, requestId presence not yet audited)',
}
out['local_codex_rollouts_key_census'] = {
    'files': cx['files'], 'lines': cx['lines'], 'unparsable': cx['unparsable'],
    'files_with_any_request_or_trace_or_header_key': sum(v for k, v in cx['matching_key_paths_files'].items()
                                                         if any(t in k.lower() for t in ('request', 'trace', 'ray', 'header', 'server_timing'))),
    'files_with_rate_limits': cx['matching_key_paths_files'].get('.payload.rate_limits', 0),
    'source': 'analysis/out/phase_e/track_b/B6_assess/codex_keycensus.json (script codex_keycensus.py; key names only)',
}
with open(os.path.join(HERE, 'derived.json'), 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=1)
print(json.dumps(out, indent=1))
