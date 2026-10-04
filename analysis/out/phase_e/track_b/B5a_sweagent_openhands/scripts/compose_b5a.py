"""Compose analysis/out/phase_e/track_b/B5a_sweagent_openhands.json from the saved census / audit / manifest / meta files
in this evidence directory. Numbers are read from those files; verdict text is marked as interpretation.
Run from anywhere: python compose_b5a.py"""
import json, os

E = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../track_b/B5a_sweagent_openhands
OUT = os.path.join(os.path.dirname(E), "B5a_sweagent_openhands.json")
J = lambda *p: json.load(open(os.path.join(E, *p), encoding="utf-8"))
REL = "analysis/out/phase_e/track_b/B5a_sweagent_openhands/"

meta = {f[:-5]: J("meta", f) for f in os.listdir(os.path.join(E, "meta")) if f.endswith(".json") and "__" in f}
M = lambda k: meta[k.replace("/", "__")]
oh = J("census", "census_oh_eval.json")
fb = J("census", "census_feedback.json")
mini = J("census", "census_mini.json")
c2 = J("census", "census_combo2.json")
sa = J("census", "sample_audits.json")
man = {k: J("census", f"manifest_{k}.json") for k in ("openhands-evaluation-outputs", "openhands-feedback",
                                                       "miniswe-v2-qwen3-30b-swebv-tarsur385", "sweagent-combo2-rl-rollouts")}


def hf(repo):
    m = M(repo)
    return {"url": f"https://huggingface.co/datasets/{repo}", "revision": m["sha"], "gated": m["gated"],
            "licence_tag": m["license_tags"], "total_bytes": m["total_bytes"], "n_files": m["n_files"],
            "last_modified": (m.get("lastModified") or "")[:10]}


def pct(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 5) if n else None}


# ---------- OpenHands eval outputs: aggregate per-run census into provider-clock groups ----------
runs = oh["per_run"]
created_groups = {}
for r, v in runs.items():
    d = v["action_ts_minus_created_s"]
    if not d["n"]:
        continue
    model = list(v["models"].keys())[0]
    created_groups[r.split("/")[-1]] = {"model": model, "model_response_id_shape": v["model_response_id_shapes"][0][0],
                                       **{k: d[k] for k in ("n", "p0", "p50", "p100", "n_negative")}}
T = oh["totals"]
v19 = [r for r, v in runs.items() if "pair" in v["history_format"] or "v1.9" in r]
v2x = [r for r in runs if r not in v19]
model_strings = sorted({m for v in runs.values() for m in v["models"] if m and m != "null"})
prov_created_runs = [k for k, g in created_groups.items() if g["model_response_id_shape"] == "<uuid>"]
neg_runs = {k: (g["n_negative"], g["p0"]) for k, g in created_groups.items() if g["n_negative"]}
join_rate = T["obs_cause_joined"] / T["observations"]

corpora = []

# ================= DOWNLOADED =================
corpora.append({
    "name": "openhands-evaluation-outputs",
    "family": "OpenHands (CodeActAgent) SWE-bench Lite eval outputs, 19 runs x ~300 instances, 13 models",
    "source": hf("OpenHands/openhands-evaluation-outputs"),
    "licence": "MIT (dataset card YAML `license: mit`; README body is only that front matter)",
    "research_use_ok": True,
    "decision": "DOWNLOADED (whole repo at pinned revision)",
    "downloaded_to": "C:\\Swarms\\data\\acquired\\openhands-evaluation-outputs\\",
    "sha256": {"manifest": REL + "census/manifest_openhands-evaluation-outputs.json", "n_files": man["openhands-evaluation-outputs"]["n_files"],
               "total_bytes": man["openhands-evaluation-outputs"]["total_bytes"],
               "all_match_hub_lfs_sha256": man["openhands-evaluation-outputs"]["all_sha256_ok"]},
    "field_audit": {
        "sample_first": "byte-range heads of 4 output.jsonl files (sonnet v2.2, gpt-4o v1.9, deepseek v2.2, llama-3.3 v0.15) before download: "
                        "census/sample_audit_oh_legacy_heads.txt",
        "population_census": REL + "census/census_oh_eval.json (scripts/census_oh_eval.py over every outputs/**/output.jsonl)",
        "per_event_timestamps": {"present": True, "format": "ISO-8601 naive, microsecond (e.g. 2024-10-31T20:07:06.471072); UTC by inference "
                                 "(action ts minus provider `created` is 2-216 s for DeepSeek, never hours)",
                                 "events_with_parseable_ts": pct(T["ts_ok"], T["events"])},
        "call_result_join": {"present": True, "how": "observation.cause == action.id (both formats); v2.x also carries tool_call_metadata.tool_call_id on both sides",
                             "observations_joined": pct(T["obs_cause_joined"], T["observations"])},
        "provider_request_ids": {"present": "PARTIAL - no provider *request* ids; per-action model_response.id + created in v2.x runs only",
                                 "detail": "Anthropic runs (direct and via litellm proxy): model_response.id = 'chatcmpl-<uuid4>' minted by litellm; `created` is set "
                                           "locally after the response (action ts - created between 0 and ~2 s, p50 ~0.5 s). DeepSeek and Fireworks runs: id is a bare UUID "
                                           "(DeepSeek documents a UUID example, see sources) and `created` is set on a non-local clock: it normally precedes the action event "
                                           "by seconds, and in two Fireworks runs a few values fall after it, which a local request-start stamp could not do. "
                                           "Gemini via litellm_proxy: chatcmpl-<uuid>, created seconds earlier (setter UNVERIFIED). Per-run quantiles in "
                                           "created_vs_action_ts_by_run. v1.9 runs carry no model_response at all. "
                                           "tool_call_id: Anthropic first-party `toolu_01...` and Bedrock `tooluse_...` (provider-minted, no decodable time per B2a); "
                                           "non-function-calling runs use harness-minted sequential `toolu_01`, `toolu_02`.",
                                 "created_vs_action_ts_by_run": created_groups},
        "token_counts": {"present": "per action in v2.x (model_response.usage: prompt/completion, cache fields for Anthropic); none in v1.9",
                         "actions_with_usage": T["actions_with_usage"]},
        "error_markers": {"exit_code_in_observation_extras": T["obs_exit_code"], "error_observations": T["obs_error"],
                          "note": "exit_code only on CmdRunObservation; IPython/file-editor observations carry none"},
        "truncation_markers": {"observations_with_marker_v2x": T["obs_trunc_marker"],
                               "note": "regex in census_oh_eval.py; v1.9 runs use other wording (0 hits), so truncation in v1.9 is UNMEASURED"},
        "pass": True,
    },
    "schema_note": {
        "unit": "one JSON line per SWE-bench Lite instance: instance_id, instruction, metadata (agent_class, llm_config with api_key masked '******', "
                "max_iterations), history, metrics (accumulated_cost, costs[]), test_result.git_patch, report (resolved, ...), error",
        "history_v2x": "flat list of events {id, timestamp, source, message, action|observation, args|content+extras, cause, tool_call_metadata"
                       "{function_name, tool_call_id, model_response{id, created, model, usage, choices}, total_calls_in_response}}",
        "history_v1.9": "list of [action, observation] pairs, same event fields minus tool_call_metadata",
        "event_types": "actions: run (bash), run_ipython, browse_interactive, message, finish, ...; observations: run, run_ipython, error, browse, ...",
        "counts": {"runs": oh["n_runs"], "runs_v2x_with_model_response": len(created_groups), "runs_v1.9_pairs": len(v19),
                   "instances": T["instances"], "events": T["events"], "agent_tool_actions": T["agent_tool_actions"],
                   "observations": T["observations"]},
        "event_ts_range": [min(v["event_ts_range"][0] for v in runs.values() if v["event_ts_range"][0]),
                           max(v["event_ts_range"][1] for v in runs.values() if v["event_ts_range"][1])],
        "caveats": ["Benchmark runs, not production: one harness (OpenHands 0.9-0.15 era), SWE-bench Lite only, Sep-Dec 2024.",
                    "pages/0_*_OpenHands_Benchmark.py and analyze_outputs.py are code shipped with the data; never executed.",
                    "A byte-identical duplicate of claude-3-5-sonnet-20241022_maxiter_100_N_v2.1-no-hint/output.jsonl exists as output.jsonl.part "
                    "(153,841,006 B, same sha256 4c54a4ab...) from a download race between two of this task's own downloaders; not deleted "
                    "(data/ is append-only) - flagged for human cleanup; loaders must glob output.jsonl exactly."],
    },
})

corpora.append({
    "name": "openhands-feedback",
    "family": "OpenHands real-user sessions shared publicly via the thumbs-up/down button (not benchmark runs)",
    "source": hf("OpenHands/openhands-feedback"),
    "licence": "MIT (card YAML `license: mit`); every row has permissions='public'",
    "research_use_ok": True,
    "decision": "DOWNLOADED",
    "downloaded_to": "C:\\Swarms\\data\\acquired\\openhands-feedback\\",
    "sha256": {"manifest": REL + "census/manifest_openhands-feedback.json", "all_match_hub_lfs_sha256": man["openhands-feedback"]["all_sha256_ok"]},
    "field_audit": {
        "sample_first": "2 rows via datasets-server /rows before download; then whole-file census census/census_feedback.json",
        "per_event_timestamps": {"present": True, "format": "parquet timestamp[us] per trajectory event (microsecond)",
                                 "agent_tool_actions_with_ts": pct(fb["counts"]["agent_tool_actions_ts"], fb["counts"]["agent_tool_actions"]),
                                 "observations_with_ts": pct(fb["counts"]["observations_ts"], fb["counts"]["observations"])},
        "call_result_join": {"present": "strict pairing only (no `cause` column in this export)",
                             "rule": "observation id == preceding action id + 1 and, where both carry command/code, observation extras echo it",
                             "observations_paired": pct(fb["counts"]["obs_paired_strict"], fb["counts"]["observations"]),
                             "command_echo_matches": pct(fb["counts"]["obs_cmd_echo_match"], fb["counts"]["obs_with_both_cmds"])},
        "provider_request_ids": {"present": False},
        "token_counts": {"present": False},
        "error_markers": {"exit_code_in_extras": fb["counts"]["obs_exit_code"], "error_observations": fb["counts"]["obs_error"]},
        "truncation_markers": {"observations_with_marker": fb["counts"]["obs_trunc_marker"]},
        "pass": True,
    },
    "schema_note": {"columns": "version, feedback (positive/negative), permissions, timestamp[us], trajectory[] {action, content, extras (JSON string), id, message, "
                               "observation, source, timestamp[us]}",
                    "counts": {"sessions": fb["counts"]["sessions"], "events": fb["counts"]["events"], "feedback": fb["feedback"],
                               "distinct_llm_configs": fb["n_models"], "submitted_range": [fb["submitted_ts_min"], fb["submitted_ts_max"]]},
                    "models_top5": fb["models_top"][:5],
                    "caveats": ["Real users' prompts and repos: report aggregates only; do not republish raw content in the B7 release without review.",
                                "Strict-pairing join, not an id join: weaker than cause/tool_call_id.",
                                "53 LLM configs incl. local ollama models: provider clocks absent."]},
})

corpora.append({
    "name": "miniswe-v2-qwen3-30b-swebv-tarsur385",
    "family": "mini-swe-agent 2.2.8 (SWE-agent org's minimal harness), SWE-bench Verified, Qwen3-30B-A3B-Instruct-2507 on self-hosted vLLM, T=0",
    "source": hf("tarsur385/qwen3-30b-a3b-instruct-2507-swebench-verified-mini-swe-agent"),
    "licence": "MIT (card YAML)",
    "research_use_ok": True,
    "decision": "DOWNLOADED",
    "downloaded_to": "C:\\Swarms\\data\\acquired\\miniswe-v2-qwen3-30b-swebv-tarsur385\\",
    "sha256": {"manifest": REL + "census/manifest_miniswe-v2-qwen3-30b-swebv-tarsur385.json",
               "all_match_hub_lfs_sha256": man["miniswe-v2-qwen3-30b-swebv-tarsur385"]["all_sha256_ok"]},
    "field_audit": {
        "sample_first": "one median-size .traj.json (scratchpad) before download; population census census/census_mini.json",
        "per_event_timestamps": {"present": True, "format": "float unix seconds (time.time(), microsecond digits) in extra.timestamp on every assistant and tool message",
                                 "semantics": "assistant ts = after the model response returns; tool ts = when the observation is formatted after the action batch "
                                              "executes (sources/msa_litellm_model.py L104, msa_actions_toolcall.py L100): parallel calls in one step share near-identical stamps",
                                 "assistant": pct(mini["counts"]["assistant_ts"], mini["counts"]["assistant"]),
                                 "tool": pct(mini["counts"]["tool_ts"], mini["counts"]["tool_results"])},
        "call_result_join": {"present": True, "how": "tool.tool_call_id == assistant.tool_calls[].id",
                             "tool_results_joined": pct(mini["counts"]["tool_joined"], mini["counts"]["tool_results"]),
                             "calls_without_result": mini["counts"]["tool_calls"] - mini["counts"]["tool_results"],
                             "note": f"unmatched calls = {mini['counts']['tool_calls'] - mini['counts']['tool_results']}; trajectories with exit_status Submitted = {mini['exit_status'].get('Submitted')} (final submit call ends the run without a tool result; descriptive)"},
        "provider_request_ids": {"present": False, "detail": "response.id 'chatcmpl-<16hex>' and created are minted by the local vLLM server: a second clock "
                                 "in a separate process, not a provider clock", "assistant_ts_minus_created_s": mini["assistant_ts_minus_created_s"]},
        "token_counts": {"present": True, "assistant_with_usage": mini["counts"]["assistant_with_usage"]},
        "error_markers": {"returncode_in_extra": mini["counts"]["tool_returncode"], "nonzero_returncode": mini["counts"]["tool_nonzero_rc"],
                          "harness_not_executed_padding": mini["counts"].get("tool_not_executed_padding", 0)},
        "truncation_markers": "not audited (mini-swe-agent truncates long output via its observation template; marker wording UNVERIFIED)",
        "pass": True,
    },
    "schema_note": {"files": "trajectories/<instance_id>.traj.json (499), preds.json/.jsonl, grading_report.json",
                    "traj": "{info{model_stats, config, mini_version, exit_status, submission}, messages[], trajectory_format 'mini-swe-agent-1.1', instance_id}",
                    "message": "assistant {content, tool_calls[{id,function{name,arguments}}], extra{actions, response{id, created, usage,...}, cost, timestamp}}; "
                               "tool {content, tool_call_id, extra{raw_output, returncode, timestamp, exception_info}}",
                    "counts": {"trajectories": mini["counts"]["trajectories"], "tool_calls": mini["counts"]["tool_calls"],
                               "tool_results": mini["counts"]["tool_results"], "exit_status": mini["exit_status"]},
                    "caveats": ["Single model, self-hosted: no provider ids, no cross-provider variety.",
                                "Same harness format as the SWE-bench bash-only leaderboard trajectories (listed below, no licence), so loaders transfer."]},
})

corpora.append({
    "name": "sweagent-combo2-rl-rollouts (subset: trajectories_00 of 6)",
    "family": "GRPO RL rollouts of Qwen3.5-35B-A3B in a mini-swe-agent-derived 'combo' harness; SWE-rebench V1/V2 + Scale-SWE tasks",
    "source": {**hf("sweagent/combo2-rl-rollouts"),
               "publisher_note": "HF org 'sweagent' (fullname 'SWE-Agent', 1 member, unverified): affiliation with the SWE-agent project is UNVERIFIED"},
    "licence": "MIT (card YAML)",
    "research_use_ok": True,
    "decision": "DOWNLOADED SUBSET: README, .gitattributes, group_info.tar.gz, trajectories_00.tar.gz (445 MB of 2.93 GB). Shards 01-05 and rewards.tar.gz "
                "deliberately left on the Hub as fresh, unseen data (see seen_data_warning) and to stay within the shared 25 GB budget.",
    "downloaded_to": "C:\\Swarms\\data\\acquired\\sweagent-combo2-rl-rollouts\\",
    "sha256": {"manifest": REL + "census/manifest_sweagent-combo2-rl-rollouts.json", "all_match_hub_lfs_sha256": man["sweagent-combo2-rl-rollouts"]["all_sha256_ok"]},
    "field_audit": {
        "sample_first": "first 3 members of trajectories_00.tar.gz from a 3 MB range read, then full streamed census of shard 00 (census/census_combo2.json); never extracted to disk",
        "per_event_timestamps": {"present": True, "format": "float unix seconds on every message", "messages": pct(c2["counts"]["messages_ts"], c2["counts"]["messages"])},
        "call_result_join": {"present": True, "how": "tool.tool_call_id == assistant extra.actions[].tool_call_id (harness-minted 'call_<step>_<k>')",
                             "tool_results_joined": pct(c2["counts"]["tool_joined"], c2["counts"]["tool_results"])},
        "provider_request_ids": {"present": False},
        "token_counts": {"present": "prompt/response token_ids and loss_mask per trajectory (RL training record), no per-call usage"},
        "error_markers": {"returncode_in_content": c2["counts"]["tool_rc_in_content"]},
        "harness_labelled_synthetic_results": {
            "what": "the harness writes some tool results itself instead of returning the executed command's output, and flags them extra.synthetic",
            "counts_shard00": c2["synthetic_flags"],
            "descriptive_latency_tool_ts_minus_assistant_ts_s": c2["tool_ts_minus_assistant_ts_s"],
            "interpretation": "A natural, harness-labelled set of results whose content did not come from the tool. NOT a clean 'zero-time' positive: "
                              f"synthetic results still arrive >= {c2['tool_ts_minus_assistant_ts_s']['synthetic']['p0']} s after the call (the submit command appears to run before its output is replaced), "
                              "and the two latency distributions overlap. Descriptive only; no threshold was set or tested."},
        "pass": True,
    },
    "schema_note": {"unit": "<instance_id>_<sample_index>.json inside tar.gz shards",
                    "fields": "instance_id, instance, messages[{role, content, timestamp, tool_call_id?, extra{actions|returncode|synthetic}}], model_patch, n_steps, "
                              "exit_status, all_tokens_length, prompt_token_ids, response_token_ids, loss_mask, env_creation_time",
                    "counts_shard00": {"trajectories": c2["counts"]["trajectories"], "messages": c2["counts"]["messages"],
                                       "tool_results": c2["counts"]["tool_results"], "exit_status": c2["exit_status"]},
                    "caveats": ["RL training rollouts of one policy, not production; ~34.8 GiB uncompressed for all 6 shards (README) - stream, do not extract.",
                                "Content is model output on third-party repos; token-id arrays dominate the bytes."]},
    "seen_data_warning": "This census looked at result latency split by the synthetic flag on shard 00. Any later pre-registered test that uses the synthetic "
                         "flag as a label should be confirmed on shards 01-05 (not downloaded, unseen).",
})

# ================= PASSED AUDIT, LISTED (not downloaded) =================
listed = []
listed.append({
    "name": "SWE-bench leaderboard trajectories (S3 bucket swe-bench-submissions + self-hosted submitter repos)",
    "source": {"url": "https://github.com/SWE-bench/experiments", "commit": "40f164d5b8f1d249bf95a6df8b74b577fd8e519d",
               "bucket": "s3://swe-bench-submissions (anonymous HTTPS listing works per prefix; root listing 403)",
               "entries_at_commit": {"verified": 182, "lite": 84, "test": 24, "multimodal": 22, "multilingual": 14}},
    "licence": "NONE. GitHub API license=null; root has no LICENSE file (README, checklist.md, analysis/, evaluation/, validation/ only). "
               "README says the logs are 'publicly accessible' but grants no licence; per-submitter repos may carry their own.",
    "research_use_ok": False,
    "decision": "LISTED - no licence file (rule: do not download). Human decision: ask SWE-bench maintainers for a data licence, or pick submitter repos that carry one.",
    "field_audit_by_format (one file each, scratchpad)": {
        "mini-swe-agent v2.x bash-only (e.g. 20260217_mini-v2.0.0_claude-4-5-sonnet-high, 503 objects, 0.30 GB)": {**sa["s3_bashonly_mini_v2.1_claude-sonnet-4-5"], "pass": True},
        "SWE-agent 0.x .traj (20240620_sweagent_claude3.5sonnet)": {**sa["s3_sweagent_0x_claude3.5sonnet"], "pass": False, "why": "no timestamps, no ids"},
        "SWE-agent 1.1 .traj (20250522_sweagent_claude-4-sonnet-20250514)": {**sa["s3_sweagent_1.1_claude-4-sonnet"], "pass": False,
            "why": "per-step execution_time (perf_counter duration) and tool_call_ids, but no wall-clock timestamps"},
        "OpenHands submissions (20241029 CodeAct 2.1, 20250415, 20251127 Opus 4.5)": {"20241029": sa["s3_openhands_20241029_codeact2.1"], "20250415": sa["s3_openhands_20250415"],
            "20251127": sa["s3_openhands_20251127_opus-4-5"], "pass": False, "why": "LLM-message export only (role/content/tool_calls/tool_call_id); no timestamps"}},
    "notes": "The 48 mini-swe-agent entries in evaluation/verified at this commit (14 of them v2.x) are the largest pool of this harness with frontier models (Claude, GPT-5.x, Gemini 3, GLM, Kimi, DeepSeek). "
             "Of the two versions sampled, only v2.1 carries per-message timestamps (v1.14 does not); Anthropic response ids are litellm 'chatcmpl-<uuid>', not provider ids.",
})
listed.append({
    "name": "OpenHands Index full_archive tarballs (results.eval.all-hands.dev)",
    "source": {"url": "https://github.com/OpenHands/openhands-index-results", "commit": "3015ac612e7196f428e6e8a3948965d32d9a3331",
               "examples_opened": ["https://results.eval.all-hands.dev/eval-21386741317-deepseek-v_litellm_proxy-deepseek-deepseek-reasoner_26-01-27-17-23.tar.gz (423,683,435 B)",
                                   "https://results.eval.all-hands.dev/swebench/litellm_proxy-anthropic-claude-opus-4-8/26737081181/results.tar.gz (515,328,661 B)"],
               "entries": "35 model directories, each with swe-bench / swt-bench / gaia / commit0 / multimodal archives"},
    "licence": "NONE on the results repo (GitHub API license=null) or the archive host. The HF snapshot OpenHands/openhands-index is Apache-2.0 but holds only "
               "leaderboard scores and per-instance resolved/cost, not trajectories.",
    "research_use_ok": False,
    "decision": "LISTED - no licence. HIGH VALUE for a human request to All Hands: richest timing schema seen in this family.",
    "field_audit": {"v1.8.3 deepseek-reasoner (first output.jsonl line from an 8 MB range read)": sa["openhands_index_v1.8.3_deepseek-reasoner_swebench"],
                    "v1.24.0 claude-opus-4-8 (one per-conversation event tarball)": sa["openhands_index_v1.24.0_claude-opus-4-8_swebench_one_conversation"],
                    "pass": True,
                    "why_valuable": "ActionEvent/ObservationEvent with microsecond timestamps, tool_call_id + action_id joins, exit_code/is_error/timeout on "
                                    "observations, and metrics.response_latencies[] + token_usages[] keyed by llm_response_id (a per-LLM-call latency and "
                                    "token ledger). Provider ids: DeepSeek UUIDs; Anthropic via litellm proxy = chatcmpl-<uuid> (not provider)."},
})
listed.append({
    "name": "CooperBench qwen9b mini-swe-agent v2 (solo 0.78 GB; coop 12.05 GB)",
    "source": {"solo": hf("CooperBench/qwen9b-solo-mini-swe-agent"), "coop": hf("CooperBench/qwen9b-coop-mini-swe-agent")},
    "licence": "MIT (both cards)",
    "research_use_ok": True,
    "decision": "LISTED. solo: passes the audit (one trajectory sampled) but is the same harness and model class as the downloaded tarsur385 corpus, on a non-SWE "
                "benchmark: redundant here. coop: over the 5 GB cap. Swarm-relevant: two agents per task coordinating via Redis messages and a shared git "
                "remote (conversation.json per pair). Human decision: a sub-5 GB subset of coop.",
    "field_audit": {"solo_sample": sa["cooperbench_solo_qwen9b_mini_v2"], "coop": "not sampled; README lists agent{1,2}_full_traj.json in the same mini v2 format - UNVERIFIED"},
})
listed.append({
    "name": "sweagent/iter2-rl-rollouts and combo2 shards 01-05",
    "source": {"iter2": hf("sweagent/iter2-rl-rollouts"), "combo2": hf("sweagent/combo2-rl-rollouts")},
    "licence": "MIT", "research_use_ok": True,
    "decision": "LISTED: same family as the downloaded combo2 shard; kept on the Hub as unseen confirmation data and for the shared budget. iter2 not sampled (format UNVERIFIED).",
})

# ================= FAILED AUDIT or EXCLUDED =================
failed = [
    {"name": "nebius/SWE-agent-trajectories", "source": hf("nebius/SWE-agent-trajectories"), "licence": "CC-BY-4.0 (+ Llama 3.1 licence notice for outputs)",
     "audit": "parquet footer + 1 row: trajectory[] = {cutoff_date, mask, role, system_prompt, text}; cutoff_date is the model knowledge cutoff ('01.01.2023') on the system turn only. "
              "No timestamps, no ids; alternating ai/user pairing only.", "pass": False, "rows": 80036},
    {"name": "nebius/SWE-rebench-openhands-trajectories", "source": hf("nebius/SWE-rebench-openhands-trajectories"), "licence": "CC-BY-4.0",
     "audit": "parquet footer: trajectory[] = {content, name, role, tool_call_id, tool_calls[]}; tool_call_id join yes, no timestamp anywhere (OpenHands 0.54 export to chat format).",
     "pass": False, "rows": 67074},
    {"name": "SWE-Gym/OpenHands-Sampled-Trajectories", "source": hf("SWE-Gym/OpenHands-Sampled-Trajectories"), "licence": "none tagged",
     "audit": "messages[] {content, role, tool_call_id, tool_calls}; no timestamps", "pass": False},
    {"name": "SWE-Gym/OpenHands-SFT-Trajectories", "source": hf("SWE-Gym/OpenHands-SFT-Trajectories"), "licence": "MIT",
     "audit": "messages[] {content, role} only", "pass": False},
    {"name": "SWE-Gym/OpenHands-Verifier-Trajectories", "source": hf("SWE-Gym/OpenHands-Verifier-Trajectories"), "licence": "none tagged",
     "audit": "messages[] {content, role}, resolved", "pass": False},
    {"name": "SWE-bench/SWE-smith-trajectories", "source": hf("SWE-bench/SWE-smith-trajectories"), "licence": "MIT",
     "audit": "messages is a JSON string of SWE-agent history items {role, content, agent, message_type, thought, action, tool_calls, tool_call_ids}; no timestamps", "pass": False},
    {"name": "nvidia/SWE-Zero-openhands-trajectories", "source": hf("nvidia/SWE-Zero-openhands-trajectories"), "licence": "CC-BY-4.0",
     "audit": "trajectory[] {content, role, tool_calls[]}; no timestamps; also 12.2 GB > cap", "pass": False},
    {"name": "nvidia/SWE-Hero-openhands-trajectories", "source": hf("nvidia/SWE-Hero-openhands-trajectories"), "licence": "CC-BY-4.0",
     "audit": "trajectory[] {content, role, tool_calls[]}; no timestamps", "pass": False},
    {"name": "Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k", "source": hf("Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k"), "licence": "MIT",
     "audit": "messages[] {content, role} only", "pass": False},
    {"name": "livesweagent/*_swebench_verified_traj (gpt-5, claude-sonnet-4-5, gemini-3-pro, ...)", "source": {"gpt-5": hf("livesweagent/gpt-5_swebench_verified_traj"),
     "claude-sonnet-4-5": hf("livesweagent/claude-sonnet-4-5_swebench_verified_traj"), "gemini-3-pro": hf("livesweagent/gemini_3_pro_swebench_verified_traj")},
     "licence": "MIT",
     "audit": {"gpt-5": sa["livesweagent_gpt-5_mini_v1.14"], "claude-sonnet-4-5": sa["livesweagent_claude-sonnet-4-5_mini_v1.14"],
               "why_fail": "mini-swe-agent 1.14: no harness timestamps; observations are plain user messages with no id (pairing only). Only the LLM response carries `created`."},
     "pass": False,
     "note_for_B2_B4": "The gpt-5 trajectories (via the tensorblock proxy) carry OpenAI-minted chatcmpl ids: in the sampled trajectory 14/14 ids decode to their `created` "
                       "second with B2a's rule (base62(id[9:14]) + 1,576,800,000). A provider clock without a harness clock: usable only for inter-request ordering, "
                       "not for the rank-1 bracket."},
    {"name": "OpenHands/CodeScout_Eval_Rollouts", "source": hf("OpenHands/CodeScout_Eval_Rollouts"), "licence": "none tagged",
     "audit": "chat_messages (role/content/tool_calls/tool_call_id) + accumulated token metrics; no timestamps", "pass": False},
    {"name": "sailplane/swe-agent-trajs", "source": hf("sailplane/swe-agent-trajs"), "licence": "none tagged",
     "audit": "SWE-agent 0.x leaderboard trajs re-packed: trajectory string + model_stats; no timestamps", "pass": False},
    {"name": "antontuzovAI/swe-agent-successful-raw-1000, ElenaFu/SWE-agent-trajectories", "source": {"a": hf("antontuzovAI/swe-agent-successful-raw-1000"),
     "b": hf("ElenaFu/SWE-agent-trajectories")}, "licence": "CC-BY-4.0",
     "audit": "subset/mirror of nebius/SWE-agent-trajectories (same schema; ElenaFu total_bytes identical to nebius); no timestamps", "pass": False},
    {"name": "WhitzardAgent/ClaudeCode-OpenHands", "source": hf("WhitzardAgent/ClaudeCode-OpenHands"), "licence": "Apache-2.0",
     "audit": "README: Claude Code traces converted by AgentIR into OpenHands chat format {role, content, tool_calls, tool_call_id}; conversion target has no timestamps (from README; data not sampled)",
     "pass": False, "lead": "Its source nlile/misc-merged-claude-code-traces-v1 (1.16 GB) declares `timestamp`, `request_id` and `claude_log` columns in its card, "
                            "but carries NO licence tag: list for the B4/B2 owners; do not download."},
]
excluded = [
    {"name": "OpenHandsCommunity/eval-output-webarena", "source": hf("OpenHandsCommunity/eval-output-webarena"), "why": "no licence; 31.8 GB > cap; not sampled"},
    {"name": "OpenHandsCommunity/evaluation (HF Space, formerly OpenHands/evaluation)", "source": {"url": "https://huggingface.co/spaces/OpenHandsCommunity/evaluation",
     "revision": "f86335188c3ad61d2e2285751968ffbeff94f856", "n_files": 10733}, "why": "no licence declared; legacy viewer of eval outputs (the MIT dataset above appears to be its curated successor - UNVERIFIED)"},
    {"name": "OnepointfiveHz/sonnet-openhands-0815", "source": hf("OnepointfiveHz/sonnet-openhands-0815"), "why": "no licence; 28.4 GB .zst > cap"},
    {"name": "sweagent/pi-harness-swev-trajs", "source": hf("sweagent/pi-harness-swev-trajs"), "why": "no licence (pi coding-agent harness, not SWE-agent)"},
    {"name": "SWE-agent repo trajectories/demonstrations", "source": {"url": "https://github.com/SWE-agent/SWE-agent/tree/3ea751c087f32b16e039a2233dd6eefecef325d5/trajectories",
     "licence": "MIT"}, "why": "22 few-shot demonstration .traj files, not a corpus; not opened"},
]

prior_art = [
    {"claim": "A SWE-bench-family harness or leaderboard already verifies tool results, or time-checks tool calls, from the recorded log",
     "closest_work": "SWE-bench `swebench submit verify` + SWE-bench/experiments analysis scripts",
     "does": "Re-grades every instance from the recorded test output and flags disagreement with results.json, with no re-execution "
             "(sources/sb_submit_verify.py docstring: 'No Docker and no re-execution: the recorded test output is the evidence'). "
             "detect_similarity.py compares predicted patches with the gold patch ('Cheating detection for SWE-bench'). "
             "git_peek_suspicious_commits.py regex-scans mini-swe-agent trajectory commands for git-history peeking. "
             "validate_entries.py checks entry structure only ('not that the artifacts are correct').",
     "does_not": "No script reads timestamps, durations, request/response ids, or checks tool results against each other. The recorded test output and "
                 "trajectories are trusted as given. The README requirement that traces be 'Generated with the inference process, not post-hoc' is stated "
                 "but not machine-checked in any script opened.",
     "verdict": "NOT TAKEN for our mechanisms (rank-1 id bracket, N1 conditional duration, repeat determinism). PARTIAL precedent only for the general "
                "pattern 'verify claims from the record without re-execution' (claim-vs-recorded-artifact), which, like OverclaimBench, trusts the record.",
     "deciding_citation": "sources/sb_submit_verify.py lines 1-10 and sources/sbexp_validate_entries.py docstring (SWE-bench @02e7a74f, experiments @40f164d5)"},
    {"claim": "Agent harnesses in this family already record the clocks N1/N3 need",
     "closest_work": "SWE-agent StepOutput.execution_time; mini-swe-agent extra.timestamp; OpenHands event timestamps and V1 metrics.response_latencies",
     "does": "SWE-agent times each action with time.perf_counter() (B1d evidence swa_agents.py L960-L991) for a total-execution budget. mini-swe-agent "
             "stamps time.time() on every response and observation (sources/msa_litellm_model.py L104; msa_actions_toolcall.py L100). OpenHands stamps "
             "every event (microseconds) and, in the V1 SDK, logs latency and token usage per llm_response_id.",
     "does_not": "None of them uses these clocks to check whether a result is consistent with the work claimed. They are budget and accounting fields.",
     "verdict": "NOT TAKEN (consistent with B1d). These harnesses supply the inputs for N1/N3 across three more harness formats.",
     "deciding_citation": "sources/msa_*.py (mini-swe-agent @04d809ce); B1d_agent_eval/swa_agents.py (SWE-agent @3ea751c0)"},
    {"claim": "Harness-written tool results are labelled as such in the record",
     "closest_work": "mini-swe-agent not_executed padding; 'combo' harness extra.synthetic",
     "does": "mini-swe-agent pads unexecuted actions with {output:'', returncode:-1, exception_info:'action was not executed'} "
             "(sources/msa_actions_toolcall.py L88). The combo harness substitutes some submit outputs and flags them extra.synthetic "
             "(combo_ground / combo_empty_guard), counted in census_combo2.json.",
     "does_not": "These are provenance labels the harness writes about its own substitutions, not detectors. No paper using them as fabrication ground truth was searched for or found.",
     "verdict": "NOT ASSESSED as a method claim (data property). Use: a small, honest, labelled positive set for 'result content not produced by the "
                "command'. Novelty of using it as ground truth: UNVERIFIED.",
     "deciding_citation": "sources/msa_actions_toolcall.py L88; census/census_combo2.json synthetic_flags"},
]

result = {
    "key": "B5a_sweagent_openhands",
    "task": "Phase E Track B5 (sources group a): SWE-agent / SWE-bench trajectory releases and OpenHands (OpenDevin) public logs. Find, audit fields, download what passes.",
    "produced_by": {"composer": REL + "scripts/compose_b5a.py (reads the census/meta/manifest files; no number typed by hand)",
                    "scripts": REL + "scripts/", "census_outputs": REL + "census/", "hub_metadata": REL + "meta/",
                    "source_code_evidence": REL + "sources/ (MANIFEST.json has URL + sha256 of each file)",
                    "samples": "third-party sample bytes kept in the session scratchpad only (not committed)"},
    "scope_and_rules_followed": ["Public, ungated, licence-tagged data only; no click-through accepted; nothing under swarm/ read.",
                                 "Field audit on a sample (byte range, parquet footer, datasets-server rows, or one file) before every download.",
                                 "Downloaded code never executed (pages/*.py and analyze_outputs.py in openhands-evaluation-outputs).",
                                 "Shared 25 GB cap checked before each download (pinned_dl.py); this task added "
                                 f"{sum(m['total_bytes'] for m in man.values())} bytes plus one 153,841,006-byte duplicate .part file."],
    "headline": {
        "downloaded": [c["name"] for c in corpora],
        "downloaded_bytes": sum(m["total_bytes"] for m in man.values()),
        "new_harness_formats_with_ts_and_join": ["OpenHands legacy event stream (v1.9 pairs, v2.x flat)", "OpenHands feedback export (real users)",
                                                 "mini-swe-agent v2 (tool_call_id + per-message time.time())", "combo RL harness (mini-swe-agent-derived)"],
        "provider_request_ids": "NONE of the downloaded corpora carries a provider request id with embedded time. The rank-1 request-id bracket does not "
                                "transfer to this family. A weaker substitute exists in the " + str(len(prov_created_runs)) + " DeepSeek/Fireworks OpenHands runs "
                                "(" + ", ".join(prov_created_runs) + "): a provider-set `created` second (DeepSeek documents it as 'The Unix timestamp (in "
                                "seconds) of when the chat completion was created') that normally precedes the harness action timestamp; but " +
                                "; ".join(f"{k}: {n} actions with created after the action stamp (min {p} s)" for k, (n, p) in neg_runs.items()) +
                                " - so a created <= action-timestamp ordering check needs a tolerance of at least " + str(max(-p for n, p in neg_runs.values())) + " s (provider rounding or clock skew; descriptive, not a calibrated threshold), on top of the 1 s resolution of created. The Gemini-via-proxy run also shows created 1-265 s "
                                "earlier, but whether the proxy or Google set it is UNVERIFIED. Anthropic runs carry only proxy-minted chatcmpl-<uuid> ids.",
        "biggest_gap": "The two richest timing sources in this family (SWE-bench S3 mini-swe-agent v2 trajectories with frontier models; OpenHands Index V1 "
                       "archives with per-response latency ledgers) carry no licence: human request needed.",
        "most_useful_find": f"OpenHands eval outputs: {T['observations']:,} observations, {join_rate:.4f} joined by cause, microsecond timestamps, "
                            f"{T['obs_exit_code']:,} exit codes, {len(model_strings)} distinct llm_config.model strings ({', '.join(model_strings)}), one harness - "
                            "a direct second corpus for N1, N3, N5 and the N6 transfer grid.",
    },
    "seen_data_warning": "The OpenHands census computed action.timestamp minus model_response.created for every v2.x run (a bracket-like quantity), and the "
                         "combo2 census split latency by the synthetic flag. Any pre-registered test of those quantities on these corpora is not blind: "
                         "pre-register on held-out instances or the unseen combo2 shards.",
    "corpora_downloaded": corpora,
    "corpora_passed_audit_but_listed": listed,
    "corpora_failed_audit": failed,
    "corpora_excluded_unaudited": excluded,
    "prior_art": prior_art,
    "hf_search_sweep": {"queries": ["search=swe-agent", "search=sweagent", "search=openhands", "search=opendevin", "author=nebius", "author=SWE-Gym",
                                    "author=SWE-bench", "author=OpenHands", "author=all-hands", "author=princeton-nlp", "search=swe-smith", "search=swe-rebench",
                                    "search=swe-bench", "search=trajector", "search=mini-swe", "search=R2E-Gym", "author=R2E-Gym"],
                        "relevant_hits_after_name_filter": 212, "saved": REL + "meta/hfsearch_all.json",
                        "not_audited": "roughly 180 remaining small third-party SFT/RL re-exports (DCAgent*, OnepointfiveHz/*, asaverren/*, ...). Spot-checked re-exports were chat-format "
                                       "without timestamps; the remainder are UNVERIFIED and mostly lack licence tags."},
    "sources": [
        {"url": "https://huggingface.co/datasets/OpenHands/openhands-evaluation-outputs", "opened": True, "saw": "card `license: mit`; 91 files; output.jsonl event streams (sampled then downloaded)"},
        {"url": "https://huggingface.co/datasets/OpenHands/openhands-feedback", "opened": True, "saw": "card license mit; 275 public feedback sessions; schema in census"},
        {"url": "https://huggingface.co/datasets/tarsur385/qwen3-30b-a3b-instruct-2507-swebench-verified-mini-swe-agent", "opened": True, "saw": "card license mit; 499 mini-swe-agent 2.2.8 trajectories"},
        {"url": "https://huggingface.co/datasets/sweagent/combo2-rl-rollouts", "opened": True, "saw": "card license mit; README: 27,787 trajectories in 6 shards, '34.8 GiB raw'"},
        {"url": "https://github.com/SWE-bench/experiments", "opened": True, "saw": "license null via API at 40f164d5; README: entries not artifacts; S3 bucket swe-bench-submissions"},
        {"url": "https://swe-bench-submissions.s3.amazonaws.com/ (prefix listings)", "opened": True, "saw": "listing per prefix allowed, root listing 403; trajectory files fetched one each"},
        {"url": "https://github.com/SWE-bench/SWE-bench/blob/02e7a74ffd0b707aab73d203fe87bdc7c76afc8e/swebench/submit/verify.py", "opened": True, "saw": "re-grade from recorded test output, no re-execution"},
        {"url": "https://github.com/SWE-agent/SWE-agent/blob/3ea751c087f32b16e039a2233dd6eefecef325d5/sweagent/types.py", "opened": True, "saw": "TrajectoryStep has execution_time; no wall-clock field"},
        {"url": "https://github.com/SWE-agent/mini-swe-agent (commit 04d809ce)", "opened": True, "saw": "licence MIT; time.time() stamps in litellm_model.py and actions_toolcall.py"},
        {"url": "https://github.com/OpenHands/openhands-index-results (commit 3015ac61)", "opened": True, "saw": "license null; scores.json full_archive URLs"},
        {"url": "https://results.eval.all-hands.dev/ (two archives, range reads only)", "opened": True, "saw": "OpenHands V1 SDK events, response_latencies keyed by llm_response_id"},
        {"url": "https://huggingface.co/datasets/OpenHands/openhands-index", "opened": True, "saw": "Apache-2.0 leaderboard snapshot; no trajectories"},
        {"url": "https://api-docs.deepseek.com/api/create-chat-completion", "opened": True, "saw": "created: 'The Unix timestamp (in seconds) of when the chat completion was created'; example id is a UUID"},
        {"url": "https://huggingface.co/api/organizations/sweagent/overview", "opened": True, "saw": "fullname 'SWE-Agent', numUsers 1, isVerified false"},
        {"url": "https://huggingface.co/spaces/OpenHandsCommunity/evaluation", "opened": True, "saw": "API metadata only: 10,733 files, no licence"},
        {"url": "https://huggingface.co/datasets/nlile/misc-merged-claude-code-traces-v1", "opened": True, "saw": "card features include timestamp and request_id; no licence tag"},
        {"url": "(all other HF datasets in the failed/excluded lists)", "opened": True, "saw": "Hub API info + tree + README at the pinned revision in meta/; parquet footers via HfFileSystem range reads"},
    ],
    "process_incidents": ["HF resolver rate limit (5000 req / 5 min) hit while other Track B agents were downloading; switched to a downloader that fetches only missing files.",
                          "A stopped background retry script kept running and its `hf download` raced pinned_dl.py on openhands-evaluation-outputs; final state verified: "
                          "91/91 files match Hub LFS sha256; one duplicate .part file left in place (see caveats)."],
}
json.dump(result, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("wrote", OUT, os.path.getsize(OUT))
