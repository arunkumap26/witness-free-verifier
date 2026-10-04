"""Write analysis/out/phase_e/track_b/B5c_web_os_agents.json.
Numbers come from _compose_inputs.json (written by compose_b5c.py from b5c_field_audit.json, the zip census and the
downloaders' SOURCE.json files). Fields named VERDICT_REASONING / INTERPRETATION are hand-written judgement."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'B5c_web_os_agents.json')
I = json.load(open(os.path.join(HERE, '_compose_inputs.json')))
osw, cen, wai_src, wai_aud = I['osw_sub'], I['cen_tot'], I['wai_src'], I['wai_aud']
OSW_SHA = '5473c39e42a538a187a9b2c2b499db59d560fd8c'
WAI_SHA = '73cf7f57a6ff61c95722a23bffdd9c1de4069bfe'


def agg(field):
    return sum((v['audit'].get('counts') or {}).get(field, 0) for v in osw.values())


def pat(where, name):
    return sum((v['audit'].get(f'pattern_counts_{where}') or {}).get(name, 0) for v in osw.values())


per_sub = {}
for k, v in osw.items():
    a = v['audit']
    per_sub[k] = {
        'zip': v['zip'], 'zip_bytes': v['zip_bytes'], 'local_text_bytes': v['local_bytes'],
        'text_members': v['text_members_planned'], 'download_errors': v['download_errors'],
        'manifest_sha256': v['manifest_sha256'],
        'task_dirs': (a.get('counts') or {}).get('task_dirs'), 'step_rows': (a.get('counts') or {}).get('step_rows'),
        'step_keys': sorted((a.get('step_keys') or {}).keys()),
        'timestamp_resolution_counts': a.get('timestamp_resolution'),
        'steps_with_call_id_in_action': a.get('steps_with_call_id_in_action'),
        'tasks_ts_monotonic': (a.get('counts') or {}).get('tasks_ts_monotonic'),
        'step_gap_seconds': a.get('step_gap_seconds'),
        'runtime_log_pattern_counts_nonzero': {kk: vv for kk, vv in (a.get('pattern_counts_runtime_log') or {}).items() if vv},
        'traj_pattern_counts_nonzero': {kk: vv for kk, vv in (a.get('pattern_counts_traj') or {}).items() if vv},
        'anthropic_msg_id_decode': a.get('anthropic_msg_id_decode'),
        'responses_style_id_per_step': {'time_minus_action_timestamp_s': a.get('step_hexid_time_minus_action_timestamp_s'),
                                        'abs_le_1s': a.get('step_hexid_abs_le_1s'), 'abs_le_60s': a.get('step_hexid_abs_le_60s'),
                                        'rows_with_messages_but_no_id': a.get('step_rows_with_messages_but_no_hexid')}
        if a.get('step_hexid_time_minus_action_timestamp_s') else None,
        'model_time_seconds': a.get('model_time_seconds'),
    }

muse = next((v for k, v in per_sub.items() if 'muse_spark' in k), None)
klick = next((v for k, v in per_sub.items() if 'klick' in k), None)
gem = (wai_aud or {}).get('gemini', {})
gc = gem.get('counts', {})

osw_total_steps = agg('step_rows'); osw_total_tasks = agg('task_dirs')
ts_res_tot = {}
for v in per_sub.values():
    for kk, vv in (v['timestamp_resolution_counts'] or {}).items():
        ts_res_tot[kk] = ts_res_tot.get(kk, 0) + vv

doc = {
    'key': 'B5c_web_os_agents',
    'task': 'Phase E Track B5 (group c): acquire public WebArena / VisualWebArena, AgentBench and OSWorld trajectory dumps '
            '(computer-use / web agents) that carry structured call/result records; field-audit, licence-check, download what passes.',
    'produced_by': {
        'scripts': {
            'hfq.py': 'HF Hub API metadata (licence, gated flag, sha, file sizes)',
            'httpzip.py': 'seekable HTTP-range file so Python zipfile can read a remote zip central directory without downloading it',
            'cd_all.py': 'central-directory census of all 99 OSWorld-Verified zips -> osworld_verified_zip_census.json',
            'survey2.py / peek.py': 'field-audit samples (1-2 task dirs per zip, text members only) into the scratchpad',
            'bulk_text.py': 'download of text members only (traj.jsonl, runtime.log, result.txt, json/log/txt) of 20 selected zips; one range request per member; CRC32 verified; manifest.jsonl with sha256 per file',
            'wai_fill.py': 'download of WebArena-Infinity Gemini history.json/result.json + manifest, git-blob-id verified, sha256 recorded (hf download hit HTTP 429 and was resumed by this script)',
            'b5c_field_audit.py': 'descriptive census of the downloaded files -> b5c_field_audit.json (every corpus number below)',
            'compose_b5c.py + compose_b5c_final.py': 'assemble this file',
        },
        'outputs': ['analysis/out/phase_e/track_b/B5c_web_os_agents/b5c_field_audit.json',
                    'analysis/out/phase_e/track_b/B5c_web_os_agents/osworld_verified_zip_census.json',
                    'analysis/out/phase_e/track_b/B5c_web_os_agents/_compose_inputs.json'],
        'note': 'Scripts were run from the scratchpad and copied here unchanged; the orchestrator commits. Downloaded content was never executed; no pickles were loaded.',
    },
    'scope_and_rules_applied': {
        'swarm': 'Nothing under swarm/, data/swarm/ or .claude/worktrees/swarm was read. No agent transcripts were generated.',
        'licence_rule': 'Downloaded only MIT-licensed sets (dataset card licence field). No-licence and custom-terms sets were listed, not downloaded. HF gated:auto sets were not accessed (no terms accepted).',
        'size_rule': 'du -sh C:/Swarms/data/acquired checked before each download (324M before the first, 8.9G before the WebArena-Infinity retry; other B5 agents were writing concurrently). B5c added about %.2f GB in total.' % ((I['osw_local_bytes'] + I['wai_local']) / 1e9),
        'field_audit_rule': 'Every download was preceded by a sample audit (one or two task dirs, or one file) for per-event timestamps AND a call/result join.',
        'subset_rule': 'Screenshots (.png), videos (.mp4) and nested archives were not downloaded: our mechanisms read text records, and the image bytes are >99% of both repos.',
    },

    'INTERPRETATION_summary': {
        'headline': 'Two web/OS-agent corpora passed the field audit and were downloaded (text only): OSWorld-Verified trajectories '
                    '(MIT; 20 of 99 submissions, %d task runs, %d steps) and WebArena-Infinity Gemini/browser-use trajectories '
                    '(MIT; %s trajectories, %s steps). Neither carries a provider request id. One OSWorld submission (Meta Muse Spark via '
                    'api.ai.meta.com) carries Responses-API-style ids whose first 8 hex digits decode to a Unix-second time; per step it '
                    'lands within 1 s of the harness action_timestamp in %s of %s steps, and never after it (max difference 0 s). '
                    'That is a provider clock from a provider (Meta) and a harness (OSWorld) that none of our other corpora carry, '
                    'but its layout is inferred and undocumented, and it covers 1 of 99 submissions.' % (
                        osw_total_tasks, osw_total_steps, gc.get('trajectories'), gc.get('steps'),
                        (muse or {}).get('responses_style_id_per_step', {}).get('abs_le_1s') if muse and muse.get('responses_style_id_per_step') else 'n/a',
                        ((muse or {}).get('responses_style_id_per_step') or {}).get('time_minus_action_timestamp_s', {}).get('n') if muse and muse.get('responses_style_id_per_step') else 'n/a'),
        'what_the_tool_results_are': 'In OSWorld the result of a GUI call is a screenshot (not downloaded). Text results exist only where the harness logs them: '
                                     'muse_spark function_output strings, klick action logs, and browser-use extracted_content in WebArena-Infinity. '
                                     'Text-output mechanisms (determinism, sort order, error-message fidelity) therefore have little to work on here. '
                                     'Timing, token-ledger and id-clock mechanisms do.',
        'request_id_coverage': 'Provider request ids (Anthropic req_...) present in 0 of 2 downloaded corpora and 0 of the audited listed ones. '
                               'The Claude OSWorld runs went through Bedrock (msg_bdrk_/toolu_bdrk_ ids), which carry no request id and whose msg ids do not decode to a time near the run. '
                               'This does not change B4\'s cap: the request-id mechanism still runs on one public harness/provider pair (SWE-chat Claude Code).',
        'timing_confounds': 'OSWorld inserts a fixed post-action sleep (args.json sleep_after_execution: 10.0 s in the mano run, 3.0 s in klick, 0.0 in muse_spark) and the '
                            'stock runner sleeps 60 s before the first step; step gaps are dominated by these constants plus model latency. Any duration/reaction-time '
                            'mechanism must subtract a per-submission constant read from args.json.',
        'nulls': 'AgentBench: no official trajectory release found, and its runs.jsonl format has one completion timestamp per sample and untimed role/content history (fails). '
                 'VisualWebArena: the released GPT-4V+SoM trajectories are render HTML (no timestamps; fails). WebArena official traces: render HTML fails; the Playwright trace zips '
                 'would pass at the browser-action level but sit on Google Drive with no data licence (listed). AgentRewardBench cleaned JSON has no per-step timestamps (fails) and custom terms.',
    },

    'downloaded': {
        'osworld_verified_trajs': {
            'source': f'https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs (revision {OSW_SHA})',
            'licence': 'MIT (dataset card front matter `license: mit`)',
            'local_dir': 'C:/Swarms/data/acquired/osworld_verified_trajs/<submission>/{tasks/<domain>/<task_uuid>[__runN]/,_meta/,manifest.jsonl,SOURCE.json}',
            'repo_census_all_zips': cen,
            'downloaded_submissions': len(per_sub), 'downloaded_task_runs': osw_total_tasks, 'downloaded_step_rows': osw_total_steps,
            'downloaded_text_bytes': I['osw_local_bytes'],
            'timestamp_resolution_counts_all_downloaded_steps': ts_res_tot,
            'selection_rationale': 'Chosen for field richness, not at random: all nine Claude computer-use runs (tool_use ids + per-response usage in runtime.log; 4.5 runs at microsecond step time), '
                                   'the Claude 4.6/Opus 4.7 run (first-party API toolu ids), Muse Spark (time-prefixed response ids, call_id join, model_time), klick (ms-stamped harness log with per-LLM-call usage), '
                                   'qwen3.7-plus (microsecond step time), Agent-S2 gemini/o3 (per-step token counts), and o3 / kimi-k26 / evocua / autoglm / uitars-1.5-7b as plain baselines. '
                                   'The other 79 zips (and the four zips with no traj.jsonl) were not downloaded; the census lists them.',
            'schema_note': {
                'unit': 'one task run = one directory <domain>/<task_uuid>; files traj.jsonl (one JSON object per executed action), runtime.log (free-form per-task logger output; content varies by agent), result.txt (final evaluator score 0..1).',
                'traj.jsonl_core_fields': {'step_num': 'int, 1-based, per action', 'action_timestamp': 'string %Y%m%d@%H%M%S (seconds) or %Y%m%d@%H%M%S%f (microseconds), captured BEFORE env.step(action) (lib_run_single.py)',
                                           'action': 'agent-specific: pyautogui code string, or dict (Claude: {name, input, id: toolu_..., action_type, command, raw_response}; Muse Spark: {action, call_id, function_name, raw_actions, function_output})',
                                           'response': 'model text (some agents)', 'reward': 'always 0 during the episode (desktop_env.step sets reward = 0)', 'done': 'bool', 'info': 'dict, {fail|done: true} on terminal actions',
                                           'screenshot_file': 'step_<n>_<action_timestamp>.png: the observation returned by the step (the call result); file not downloaded'},
                'agent_specific_extras': {'Agent-S2': 'num_input_tokens_executor/_evaluator, num_output_tokens_*, evaluator_cost, plan/reflection text',
                                          'Muse Spark': 'model_usage {model_time, prompt_tokens, completion_tokens}; messages (Responses items with rs_/fc_ ids); runtime.log holds request input items incl. function_call_output',
                                          'klick': 'llm_call_log.jsonl (per LLM call: session_name, model, prompt, response, usage); usage.json per task; action_steps.log; runtime.log at DEBUG with ms timestamps',
                                          'Claude computer-use': 'runtime.log holds repr(BetaMessage) per response: id msg_bdrk_..., tool_use ids toolu_bdrk_..., usage input/output/cache tokens'},
                'id_fields': 'call ids exist only for Claude (toolu_) and Muse Spark (call_); other agents are joined to results by strict position (one row = action + its resulting screenshot).',
                'what_is_missing': 'no result-arrival timestamp (one stamp per step, taken before the action); no exit codes; result content of GUI calls is an image; no provider request ids.',
            },
            'per_submission': per_sub,
            'field_audit_pass': True,
            'field_audit_basis': 'per-step timestamps present (seconds or microseconds) and strict pairing of action to resulting observation within each traj.jsonl row; explicit call ids for Claude and Muse Spark rows.',
        },
        'webarena_infinity_trajs': {
            'source': f'https://huggingface.co/datasets/webarena-x/webarena-infinity-trajectories (revision {WAI_SHA})',
            'licence': 'MIT (dataset card front matter `license: mit`)',
            'local_dir': 'C:/Swarms/data/acquired/webarena_infinity_trajs/{README.md, data/manifest.json, data/gemini/<env>/<task>/{history.json,result.json}, MANIFEST_b5c.jsonl, SOURCE.json}',
            'download_record': wai_src,
            'downloaded_text_bytes': I['wai_local'],
            'subset_downloaded': 'Gemini 2.5 Flash / browser-use trajectories only. Kimi K2.5 and Qwen 2.5 VL Plus (vision_agent format) have no per-step timestamps: field audit FAIL, not downloaded.',
            'manifest_vs_files': 'manifest.json lists 978 Gemini trajectories (2,329 total); 844 Gemini history.json files exist at the pinned revision (134 manifest entries have no history file).',
            'selection_bias': 'README: "Successful browser-agent trajectories" only; no failures, so failure-mode checks have no negatives here.',
            'schema_note': {
                'history.json': '{history: [step]}; step = {model_output: {evaluation_previous_goal, memory, next_goal, action: [ {<action_name>: {params}} ], thinking?}, '
                                'result: [ {is_done, extracted_content, error?, long_term_memory?, metadata?, attachments?, success?, judgement?} ], state: {url, title, tabs, interacted_element, screenshot_path}, '
                                'metadata: {step_start_time, step_end_time (Unix epoch float seconds, sub-ms precision), step_number, step_interval}, state_message}',
                'join': 'action[i] -> result[i] strict positional pairing within a step (browser-use executes the action list in order and appends one ActionResult per executed action; a step that stops early has fewer results)',
                'timestamps': 'one start/end pair per step (covers LLM call + action execution); no per-action timestamps',
                'tokens': 'none in the files (browser-use StepMetadata docstring mentions token information, but the class holds only times)',
                'counts_from_audit': gem,
            },
            'field_audit_pass': True,
        },
    },
}

listed = [
    {'name': 'xlangai/osworld2.0-trajectory', 'source_url': 'https://huggingface.co/datasets/xlangai/osworld2.0-trajectory',
     'licence': 'unknown: no licence field in the card; HF gated: auto (click-through)', 'research_use_ok': False,
     'size': '248.5 GB (100,000 files listed; mostly PNG); sha 01cb84fcd5fb8ee415e7e065d7aaf3ec8f95fe1f',
     'why_not_downloaded': 'gated (agree-to-access); a human must accept terms. File listing (public API) shows api_usage.json (108), call_0000.json.. (per-call records?), runtime.log, eval.log, traj.jsonl (325): the most promising listed set for raw per-call API records. UNAUDITED.',
     'field_audit_pass': None},
    {'name': 'mlfoundations-cua-dev/osworld-trajectories', 'source_url': 'https://huggingface.co/datasets/mlfoundations-cua-dev/osworld-trajectories',
     'licence': 'none declared', 'research_use_ok': False, 'size': '23.3 GB; 2,014 traj.jsonl, 500 runtime.log, 37,927 PNG; sha b97b4d2bab47db84f328fb0d3d7ba243bf375651',
     'why_not_downloaded': 'no licence. Same OSWorld traj.jsonl format, so it would likely pass the field audit.', 'field_audit_pass': None},
    {'name': 'McGill-NLP/agent-reward-bench', 'source_url': 'https://huggingface.co/datasets/McGill-NLP/agent-reward-bench',
     'licence': 'no licence; README "Terms of Use" (by downloading you agree; research use only if fair use)', 'research_use_ok': False,
     'size': '38.4 GB (cleaned/ 30.4 GB, screenshots 4.2 GB, judgments 3.8 GB); 1,302 trajectories over WebArena, VisualWebArena, AssistantBench, WorkArena(++); sha b6d17e646009d6cb63d5dd7be78807b680693f61',
     'why_not_downloaded': 'field audit FAIL on one 118 KB file (cleaned/webarena/GenericAgent-anthropic_claude-3.7-sonnet/.../webarena.400.json): per-step keys num, action, last_action_error, stats{input_tokens, output_tokens, cost}, axtree, chat_messages, no per-step time; '
                           'only episode totals stats.cum_step_elapsed / cum_agent_elapsed in summary_info. Also custom terms.', 'field_audit_pass': False},
    {'name': 'agentlabtraces/agentlabtraces', 'source_url': 'https://huggingface.co/datasets/agentlabtraces/agentlabtraces',
     'licence': 'none declared (README is 85 bytes: reassembly instructions only)', 'research_use_ok': False,
     'size': '207.0 GB as five split tar.gz parts; sha 6f65d9fa58b152c5860e2fde4eba55d6e0330c6a',
     'why_not_downloaded': 'no licence; over the 5 GB cap; AgentLab stores steps as pickled StepInfo (step_<n>.pkl.gz), and unpickling is code execution, which our rules forbid on downloaded data. '
                           'By AgentLab code the pickles would carry per-step StepTimestamps (env/agent/action_exec/page-load start-stop).', 'field_audit_pass': None},
    {'name': 'OpenHandsCommunity/eval-output-webarena', 'source_url': 'https://huggingface.co/datasets/OpenHandsCommunity/eval-output-webarena',
     'licence': 'none declared', 'research_use_ok': False, 'size': '31.8 GB: three output.jsonl of 9.5-11.8 GB (BrowsingAgent with claude-3.5-sonnet, gpt-3.5-turbo, gpt-4o); sha 35869ceb04d13d5db6ffb0128f11f479d9e5c437',
     'why_not_downloaded': 'no licence and every file is over the 5 GB per-corpus cap. A 400 KB range read of the gpt-4o file PASSES the field audit: OpenHands events with id, ISO microsecond timestamp, source, action/observation, and observation.cause = action id. '
                           'Overlap: the OpenHands B5 agent may list this too.', 'field_audit_pass': True},
    {'name': 'WebArena official execution traces v1/v2 (Google Drive)', 'source_url': 'https://github.com/web-arena-x/webarena/blob/main/resources/README.md',
     'licence': 'repository Apache-2.0; no licence attached to the Drive data', 'research_use_ok': False,
     'size': 'UNVERIFIED (Drive folders list 6 v2 zips and 3 v1 zips; sizes not exposed)',
     'why_not_downloaded': 'no data licence. Per resources/README.md each zip holds render_*.html (observation, raw prediction, parsed action; no timestamps: FAIL) and trace/*.zip Playwright traces '
                           '(Playwright trace events carry callId before/after pairs with times, so these would pass at the browser-action level, not at the LLM tool-call level; UNAUDITED).', 'field_audit_pass': None},
    {'name': 'VisualWebArena GPT-4V+SoM trajectories (Google Drive gpt4v_som.tar)', 'source_url': 'https://drive.google.com/file/d/1-tKz5ByWa1-jwtejiFgxli8fZcBPZgAE/view',
     'licence': 'repository MIT; no licence attached to the Drive file', 'research_use_ok': False, 'size': 'UNVERIFIED',
     'why_not_downloaded': 'README: ".html files that record the agent\'s observations and output at each step"; the render template has no timestamps: FAIL. Also no data licence.', 'field_audit_pass': False},
    {'name': 'WebArena / VisualWebArena human Playwright traces (Google Drive)', 'source_url': 'https://github.com/web-arena-x/webarena/blob/main/resources/README.md',
     'licence': 'no data licence', 'research_use_ok': False, 'size': 'WebArena 179 trace zips; VWA folder vwa_human_trajectories (3 entries)',
     'why_not_downloaded': 'human demonstrations, not agent tool calls: out of scope.', 'field_audit_pass': None},
    {'name': 'AgentBench (THUDM) run outputs', 'source_url': 'https://github.com/THUDM/AgentBench',
     'licence': 'code Apache-2.0', 'research_use_ok': True, 'size': 'no trajectory release found (repo tree has data/ task inputs only)',
     'why_not_downloaded': 'nothing released. Format by code (src/assigner.py, src/typings/output.py): runs.jsonl rows {index, output{status, result, history[{role, content}]}, time{timestamp (ms), str}}: one completion time per sample, untimed role/content turns, no call ids: FAIL.',
     'field_audit_pass': False},
    {'name': 'THUDM/AgentInstruct (AgentBench-derived SFT trajectories)', 'source_url': 'https://huggingface.co/datasets/THUDM/AgentInstruct',
     'licence': 'none in card', 'research_use_ok': False, 'size': '1.26 MB parquet (6 tasks)', 'why_not_downloaded': 'conversation SFT data, no timestamps: FAIL (by format; not opened beyond the file listing).', 'field_audit_pass': False},
    {'name': 'harry1332/agentbench-avalon-sampled-cpu-trace', 'source_url': 'https://huggingface.co/datasets/harry1332/agentbench-avalon-sampled-cpu-trace',
     'licence': 'none in card', 'research_use_ok': False, 'size': '37 MB; one Avalon episode (26 model calls) with DynamoRIO CPU traces',
     'why_not_downloaded': 'no licence; n = 1 episode.', 'field_audit_pass': None},
    {'name': 'anonymousmypcbench/cua-speedrun-trajectories', 'source_url': 'https://huggingface.co/datasets/anonymousmypcbench/cua-speedrun-trajectories',
     'licence': 'none in card', 'research_use_ok': False, 'size': '158.0 GB, 125 files (COST-*.json + archives)', 'why_not_downloaded': 'no licence; over cap. UNAUDITED.', 'field_audit_pass': None},
    {'name': 'mlfoundations-cua-dev/computer-agent-trajectories', 'source_url': 'https://huggingface.co/datasets/mlfoundations-cua-dev/computer-agent-trajectories',
     'licence': 'none in card', 'research_use_ok': False, 'size': '197.6 GB (406 arrow shards)', 'why_not_downloaded': 'no licence; over cap. UNAUDITED.', 'field_audit_pass': None},
]
doc['listed_not_downloaded'] = listed

doc['prior_art'] = {
    'scope': 'B5 is acquisition, so most claims here are data facts. The binding question for this group is whether any of these benchmark harnesses already, internally, '
             'verifies per-call results or time-checks tool calls from the log. Code was read for each.',
    'claims': [
        {'claim': 'A web/OS-agent benchmark harness already checks recorded tool results or call timing for internal consistency (witness-free).',
         'closest_existing_work': [
             {'system': 'OSWorld (xlang-ai/OSWorld @ b138d348)', 'does': 'Stamps action_timestamp before each env.step and saves the post-action screenshot. Scores the episode once at the end with task-specific getters that read the live VM state (desktop_env.evaluate -> result_getter / expected_getter -> metric).',
              'does_not': 'Score or check individual steps: desktop_env.step sets `reward = 0  # todo: Define reward calculation for each example`. It never compares the log with itself; its only verifier is a live-environment witness at the end.'},
             {'system': 'BrowserGym / AgentLab (ServiceNow/AgentLab @ cbc35a9b)', 'does': 'Records per-step StepTimestamps (env_start/stop, action_exec_start/stop, wait_for_page_loading, validation, get_observation, agent_start/stop) and stats step_elapsed / agent_elapsed. agent_xray.plot_profiling draws them as a timeline. ReproducibilityAgent replays the recorded LLM messages against a live environment and diffs the new chat messages against the old ones (difflib).',
              'does_not': 'Use the timestamps for any check. They feed a profiling plot and video alignment ("to extract begining of visual action from video"). Replay-and-diff needs the live environment, so it is a witness, and it diffs whole message streams rather than checking any single result.'},
             {'system': 'WebArena (web-arena-x/webarena @ dce04686)', 'does': 'Rule-based outcome evaluators (string/URL/program-HTML match) at episode end; saves render HTML and optional Playwright traces.',
              'does_not': 'Check per-step records. The Playwright trace is kept for human viewing (`playwright show-trace`).'},
             {'system': 'AgentBench (THUDM/AgentBench @ d1e4a10d)', 'does': 'Writes one runs.jsonl row per sample with a completion timestamp and the role/content history.',
              'does_not': 'Timestamp turns, carry call ids, or check results.'},
             {'system': 'browser-use (browser-use/browser-use @ 7be96ed8)', 'does': 'StepMetadata {step_start_time, step_end_time, step_number, step_interval} with a duration_seconds property; ActionResult per executed action.',
              'does_not': 'Check results against the record; timing is descriptive.'},
             {'system': 'AgentRewardBench (arXiv 2504.08942)', 'does': 'Benchmarks 12 LLM judges of web-agent trajectory success against expert labels. Best precision is about 70%. One named error class is judges accepting the agent\'s own "misleading reasoning". Also shows rule-based evaluators underreport success.',
              'does_not': 'Check tool results or timing; it is outcome judgement by LLMs, the category CLAUDE_context_swarms.md section 5 calls broken.'},
         ],
         'verdict': 'NOVEL (relative to these six systems)',
         'deciding_citation': 'OSWorld desktop_env/desktop_env.py step(): "reward = 0  # todo: Define reward calculation for each example"; AgentLab src/agentlab/experiments/loop.py StepTimestamps "action_exec_start: float = 0  # to extract begining of visual action from video", used only in src/agentlab/analyze/agent_xray.py plot_profiling.',
         'VERDICT_REASONING': 'Every harness records the raw material (step times, sometimes call ids and usage), and none reads it back for consistency. The nearest internal mechanism is AgentLab ReproducibilityAgent, which is replay against a live environment: a witness, not a log-only check. This covers only these six systems; B1d covers the coding-agent harnesses.'},
        {'claim': 'Provider-minted ids with an embedded clock exist in a public web/OS-agent corpus beyond aiv_cu (Meta Muse Spark resp_/rs_ ids in OSWorld-Verified).',
         'closest_existing_work': [{'system': 'B2a provider-id facts (this project, analysis/out/phase_e/track_b/B2a_provider_id_facts.json)', 'does': 'Infers OpenAI Responses item ids as hex with a leading 32-bit Unix-second field.', 'does_not': 'Cover Meta\'s api.ai.meta.com, which these ids come from.'}],
         'verdict': 'TAKEN as a data fact: the vendor mints the ids, so the time field is theirs, not ours. Its use as a bracketing clock is B2\'s claim and B2\'s verdict.',
         'deciding_citation': 'results_muse_spark_..._sanitized/_meta args.json "base_url": "https://api.ai.meta.com/v1"; runtime.log "Sending Muse Spark request with previous_response_id=resp_6a4feecba5d4eff5e9a74241"; int("6a4feecb",16) = 1783623371 = 2026-07-09 18:56:11 UTC; same step action_timestamp "20260709@185611".',
         'VERDICT_REASONING': 'The layout is inferred from agreement with the harness clock. No Meta documentation of the id layout was found or opened, so it is UNDOCUMENTED.'},
        {'claim': 'OSWorld-"Verified" verifies trajectories (a naming hazard a reviewer could raise).',
         'closest_existing_work': [{'system': 'OSWorld-Verified blog (xlang.ai)', 'does': 'Fixes tasks and evaluators (300+ feedback items; "we primarily modified only the evaluators"); moves to AWS.', 'does_not': 'Verify agent trajectories or tool results.'}],
         'verdict': 'n/a (not a competing claim); recorded so the name is not misread',
         'deciding_citation': 'https://xlang.ai/blog/osworld-verified: "For tasks we identified as genuinely problematic, we primarily modified only the evaluators to minimize changes to the tasks themselves"',
         'VERDICT_REASONING': 'Verified means the benchmark was fixed, not the trajectories.'},
    ],
}

doc['sources'] = [
    {'url': f'https://huggingface.co/api/datasets/xlangai/ubuntu_osworld_verified_trajs?blobs=true', 'opened': True, 'passage': f'sha {OSW_SHA}; gated False; tags license:mit; 104 files, 500.43 GB', 'used_for': 'licence, revision, sizes'},
    {'url': f'https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/resolve/{OSW_SHA}/README.md', 'opened': True, 'passage': '"license: mit" ... "Each zip file contains complete evaluation trajectories including: Screenshots and action sequences; Model reasoning traces; Task completion results"', 'used_for': 'licence + content'},
    {'url': f'https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/resolve/{OSW_SHA}/<99 zips> (HTTP range reads of central directories)', 'opened': True, 'passage': 'see osworld_verified_zip_census.json', 'used_for': 'per-zip member census without full download'},
    {'url': 'https://raw.githubusercontent.com/xlang-ai/OSWorld/b138d348256078fa634fc3b73567a7337c793e6b/lib_run_single.py', 'opened': True, 'passage': '"# Capture the timestamp before executing the action / action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S%f")" ... f.write(json.dumps({"step_num": ..., "action_timestamp": ..., "action": ..., "response": ..., "reward": ..., "done": ..., "info": ..., "screenshot_file": ...}))', 'used_for': 'traj.jsonl schema and timestamp semantics'},
    {'url': 'https://raw.githubusercontent.com/xlang-ai/OSWorld/b138d348256078fa634fc3b73567a7337c793e6b/desktop_env/desktop_env.py', 'opened': True, 'passage': '"reward = 0  # todo: Define reward calculation for each example"; evaluate(): result_state = self.result_getter(self, self.evaluator["result"]) ... metric(result_state, expected_state)', 'used_for': 'prior-art: OSWorld checks only the final live state'},
    {'url': 'https://xlang.ai/blog/osworld-verified', 'opened': True, 'passage': '"we primarily modified only the evaluators to minimize changes to the tasks themselves"', 'used_for': 'what Verified means'},
    {'url': 'https://huggingface.co/api/datasets/xlangai/osworld2.0-trajectory?blobs=true', 'opened': True, 'passage': 'gated "auto"; sha 01cb84fc...; 100,000 files incl. api_usage.json, call_0000.json, runtime.log, traj.jsonl', 'used_for': 'listed (gated)'},
    {'url': 'https://huggingface.co/api/datasets/mlfoundations-cua-dev/osworld-trajectories?blobs=true', 'opened': True, 'passage': 'no cardData licence; 42,867 files; 2,014 traj.jsonl', 'used_for': 'listed (no licence)'},
    {'url': f'https://huggingface.co/datasets/webarena-x/webarena-infinity-trajectories/resolve/{WAI_SHA}/README.md', 'opened': True, 'passage': '"license: mit" ... "Successful browser-agent trajectories" ... Gemini 978 / Kimi 643 / Qwen 708 ... metadata {"step_number", "step_start_time", "step_end_time"}', 'used_for': 'licence, schema, selection bias'},
    {'url': f'https://huggingface.co/datasets/webarena-x/webarena-infinity-trajectories/resolve/{WAI_SHA}/data/gemini/elation-clinical-records/task_e1/history.json', 'opened': True, 'passage': '"metadata": {"step_start_time": 1772990053.442137, "step_end_time": 1772990060.0055003, "step_number": 1, ...}; result [{"extracted_content": "Clicked strong \\"Johnson, Marcus\\""}]', 'used_for': 'field audit sample (PASS)'},
    {'url': 'https://raw.githubusercontent.com/browser-use/browser-use/7be96ed8bafa8dfe1eef228b59cf5c884b8b2431/browser_use/agent/views.py', 'opened': True, 'passage': 'class StepMetadata(BaseModel): """Metadata for a single step including timing and token information""" step_start_time: float; step_end_time: float; step_number: int; step_interval: float | None', 'used_for': 'timestamp semantics; no token fields despite the docstring'},
    {'url': 'https://huggingface.co/api/datasets/McGill-NLP/agent-reward-bench?blobs=true', 'opened': True, 'passage': 'sha b6d17e64...; no cardData licence; cleaned/ 1,302 json', 'used_for': 'listing'},
    {'url': 'https://huggingface.co/datasets/McGill-NLP/agent-reward-bench/resolve/b6d17e646009d6cb63d5dd7be78807b680693f61/README.md', 'opened': True, 'passage': '"By downloading this Dataset, you agree to comply with the following terms of use" ... "may be used for research if it constitutes fair use"', 'used_for': 'terms (not a licence)'},
    {'url': 'https://huggingface.co/datasets/McGill-NLP/agent-reward-bench/resolve/b6d17e646009d6cb63d5dd7be78807b680693f61/cleaned/webarena/GenericAgent-anthropic_claude-3.7-sonnet/GenericAgent-anthropic_claude-3.7-sonnet_on_webarena/webarena.400.json', 'opened': True, 'passage': 'step keys [num, reasoning, action, screenshot_path, url, open_pages_urls, focused_element, last_action_error, stats, axtree, axtree_obj, chat_messages, bounding_boxes, extra_element_properties, axtree_pruned]; summary_info "stats.cum_step_elapsed": 10.34', 'used_for': 'field audit sample (FAIL: no per-step time)'},
    {'url': 'https://raw.githubusercontent.com/McGill-NLP/agent-reward-bench/05899fcfe52c925978944a23920373b7a9c63740/agent_reward_bench/trajectories.py', 'opened': True, 'passage': "Step.to_dict: {'num', 'reasoning', 'action', 'screenshot_path', 'url', ..., 'stats': self.stats (agent_info.stats), ...}; Step.__init__ uses pickle.load on step_*.pkl.gz", 'used_for': 'confirms the cleaned JSON drops AgentLab profiling'},
    {'url': 'https://arxiv.org/abs/2504.08942 (via alphaXiv get_paper_content)', 'opened': True, 'passage': 'best LLM-judge precision about 70% (GPT-4o 69.8%); rule-based evaluation recall 55.9%; error class "Misleading Agent Reasoning"', 'used_for': 'prior art: LLM judges of web trajectories'},
    {'url': 'https://huggingface.co/datasets/agentlabtraces/agentlabtraces/resolve/main/README.md', 'opened': True, 'passage': 'to combine the data parts: cat tmlr_traces_part_* > reassembled_traces.tar.gz', 'used_for': 'listing (no licence, 207 GB)'},
    {'url': 'https://raw.githubusercontent.com/ServiceNow/AgentLab/cbc35a9bc0facaf731bc858c5825edbe757c719f/src/agentlab/experiments/loop.py', 'opened': True, 'passage': 'class StepTimestamps: env_start ... action_exec_start: float = 0  # to extract begining of visual action from video ... stats["step_elapsed"] = t.env_stop - t.env_start; stats["agent_elapsed"] = t.agent_stop - t.agent_start; pickle.dump(self, f) to step_{n}.pkl.gz', 'used_for': 'what AgentLab records; pickle storage'},
    {'url': 'https://raw.githubusercontent.com/ServiceNow/AgentLab/cbc35a9bc0facaf731bc858c5825edbe757c719f/src/agentlab/analyze/agent_xray.py', 'opened': True, 'passage': 'def plot_profiling(ax, step_info_list, summary_info, progress_fn): ... add_patch(ax, prof.agent_start, prof.agent_stop, ...)', 'used_for': 'timestamps used only for a plot'},
    {'url': 'https://raw.githubusercontent.com/ServiceNow/AgentLab/cbc35a9bc0facaf731bc858c5825edbe757c719f/src/agentlab/agents/generic_agent/reproducibility_agent.py', 'opened': True, 'passage': '"An agent that reproduces exactly the same traces as GenericAgent, to compare the results." ... _make_diff(old_str, new_str) via difflib.HtmlDiff', 'used_for': 'nearest internal mechanism (replay witness)'},
    {'url': 'https://huggingface.co/datasets/OpenHandsCommunity/eval-output-webarena/resolve/35869ceb04d13d5db6ffb0128f11f479d9e5c437/BrowsingAgent/gpt-4o-2024-05-13_maxiter_15_N_v1.0/output.jsonl (bytes 0-400000)', 'opened': True, 'passage': '{"id": 3, "timestamp": "2024-06-02T09:57:04.999643", "source": "agent", "action": "browse_interactive", ...}, {"id": 4, "timestamp": "2024-06-02T09:57:07.812340", "cause": 3, "observation": "browse", ...}', 'used_for': 'field audit (PASS) of a listed, unlicensed set'},
    {'url': 'https://raw.githubusercontent.com/web-arena-x/webarena/dce04686a56253aefba7b18a4fa0937cf1dc987b/resources/README.md', 'opened': True, 'passage': '"you will see a list of render_*.html, a log file merge_log.txt ... and a trace folder containing the playwright recording of the executions"', 'used_for': 'WebArena official trace contents'},
    {'url': 'https://raw.githubusercontent.com/web-arena-x/webarena/dce04686a56253aefba7b18a4fa0937cf1dc987b/browser_env/helper_functions.py', 'opened': True, 'passage': "RenderHelper.render writes <h3 class='url'>, <div class='state_obv'>, raw_parsed_prediction, action_object divs; no time field", 'used_for': 'render HTML has no timestamps'},
    {'url': 'https://drive.google.com/embeddedfolderview?id=1H4wkzDkY2ufiC63DISMXllri0j-ipWcs', 'opened': True, 'passage': "6 entries: v2_919_gpt35_16k_cot.zip ... v2_919_gpt4_8k_cot.zip, v2_919_text_bison_001_cot.zip", 'used_for': 'WebArena v2 traces exist (sizes not shown)'},
    {'url': 'https://drive.google.com/embeddedfolderview?id=18Oww0fAgwhuSjSzxUNgzBUlC6M9IZZB2', 'opened': True, 'passage': '3 entries: release_v1.0_gpt3.5direct.zip, release_v1.0_gpt3.5dreasoning.zip, release_v1.0_gpt4.zip', 'used_for': 'WebArena v1 traces exist'},
    {'url': 'https://raw.githubusercontent.com/web-arena-x/visualwebarena/89f5af29305c3d1e9f97ce4421462060a70c9a03/README.md', 'opened': True, 'passage': '"we have also released the trajectories of the GPT-4V + SoM agent on the full set of 910 VWA tasks ... It consists of .html files"', 'used_for': 'VWA release format'},
    {'url': 'https://drive.google.com/file/d/1-tKz5ByWa1-jwtejiFgxli8fZcBPZgAE/view', 'opened': True, 'passage': 'page title "gpt4v_som.tar - Google Drive"', 'used_for': 'VWA trajectory file exists (size not shown)'},
    {'url': 'https://raw.githubusercontent.com/THUDM/AgentBench/d1e4a10db08c87075c78972e48ecc182be03e2d5/src/assigner.py', 'opened': True, 'passage': 'timestamp: int = int(time.time() * 1000) ... "time": {"timestamp": timestamp, "str": time_str} ... runs.jsonl', 'used_for': 'AgentBench output format (one time per sample)'},
    {'url': 'https://raw.githubusercontent.com/THUDM/AgentBench/d1e4a10db08c87075c78972e48ecc182be03e2d5/src/typings/output.py', 'opened': True, 'passage': 'class TaskOutput: index, status, result, history: List[ChatHistoryItem]; ChatHistoryItem: role, content', 'used_for': 'no per-turn time or ids'},
    {'url': 'https://api.github.com/repos/THUDM/AgentBench/git/trees/d1e4a10db08c87075c78972e48ecc182be03e2d5?recursive=1', 'opened': True, 'passage': 'top-level dirs data/, src/, configs/, extra/, scripts/: no outputs/ or trajectory files', 'used_for': 'no trajectory release in repo'},
    {'url': 'https://huggingface.co/api/datasets/THUDM/AgentInstruct?blobs=true', 'opened': True, 'passage': 'no cardData licence; 6 parquet files, 1.26 MB', 'used_for': 'listing'},
    {'url': 'https://huggingface.co/datasets/harry1332/agentbench-avalon-sampled-cpu-trace/resolve/8d4e5207aef2253c75c048e4c56f40686ac0352f/README.md', 'opened': True, 'passage': '"One completed non-coding AgentBench episode, with one validated CPU trace sample."', 'used_for': 'listing'},
    {'url': 'https://huggingface.co/api/datasets/anonymousmypcbench/cua-speedrun-trajectories?blobs=true', 'opened': True, 'passage': 'no cardData licence; 125 files; 158.0 GB', 'used_for': 'listing'},
    {'url': 'https://huggingface.co/api/datasets/mlfoundations-cua-dev/computer-agent-trajectories?blobs=true', 'opened': True, 'passage': 'no cardData licence; 410 files; 197.6 GB', 'used_for': 'listing'},
    {'url': 'https://api.github.com/repos/{xlang-ai/OSWorld, web-arena-x/webarena, web-arena-x/visualwebarena, THUDM/AgentBench, ServiceNow/AgentLab, ServiceNow/BrowserGym, McGill-NLP/agent-reward-bench, browser-use/browser-use}', 'opened': True,
     'passage': 'licences: OSWorld Apache-2.0; webarena Apache-2.0; visualwebarena MIT; AgentBench Apache-2.0; AgentLab and BrowserGym NOASSERTION; agent-reward-bench none; browser-use MIT', 'used_for': 'code licences (not data licences)'},
]

doc['limitations'] = [
    'OSWorld submissions were picked for field richness, not sampled, so per-submission numbers do not describe the whole repo. The census covers all 99 zips, central directories only.',
    'action_timestamp is taken from the runner\'s local clock (datetime.now(), no zone). In the Muse Spark run it matches decoded UTC id times, which suggests UTC there; other runs are unverified.',
    'Muse Spark id layout: 8 hex Unix seconds then 16 hex, inferred from agreement with the harness clock. Undocumented by Meta (no documentation found or opened).',
    'Claude OSWorld runs went through AWS Bedrock (global.anthropic.* model ids; msg_bdrk_ ids), not the first-party API, so no Anthropic request-id or msg-id clock.',
    'Screenshots were not downloaded, so the observation content of GUI calls is absent from our copy (filenames and step times remain).',
    'WebArena-Infinity holds successful trajectories only, and 134 of 978 Gemini manifest entries have no history.json at the pinned revision.',
    'The HF resolver rate limit (5,000 requests per 5 min, shared with other agents on this machine) interrupted hf download; wai_fill.py resumed it and verified every file against the Hub git blob id (0 mismatches).',
]

doc['for_human'] = [
    'xlangai/osworld2.0-trajectory is gated (auto-approve click-through). Its file list shows call_000N.json and api_usage.json per task, the most likely place for raw per-call API records (request ids?) in this group. Accepting terms is a human decision.',
    'OpenHandsCommunity/eval-output-webarena passes the field audit (microsecond ISO times, id/cause join) but has no licence, and each file is 9.5-11.8 GB. A licence query to OpenHands would unlock it.',
    'The other 79 OSWorld-Verified submissions (MIT) can be fetched text-only with bulk_text.py if N6 needs more harness/model strata: about 4.2 GB of traj.jsonl + runtime.log across all 99 zips.',
]

json.dump(doc, open(OUT, 'w'), indent=1, default=str)
print('wrote', OUT)
