"""B5e composer: builds analysis/out/phase_e/track_b/B5e_cli_traces.json from the saved census/meta/source files.
Every count below is read from a file written by a script in scripts/; text fields (verdicts, notes) are marked as
interpretation. Usage: python compose_b5e.py <B5e dir> <out.json>
"""
import glob, json, os, sys
from collections import Counter, defaultdict

D = sys.argv[1]
J = lambda p: json.load(open(os.path.join(D, p), encoding="utf-8"))
summ = J("census/hf_census_summary.json"); dedupe = J("census/dedupe_clusters.json"); sample = J("census/sample_audit.json")
pidec = J("census/pi_respid_decode.json"); dl = J("census/download_manifest.json"); dlg = J("census/download_manifest_github.json")
cen = J("census/census_downloaded.json"); mk = J("census/marker_scan.json"); tl = J("census/census_tracelab.json")
fmt = J("meta/hf_format_agent_traces.json")


def agg_corpus(corpus):
    out = defaultdict(Counter); repos = []; lists = defaultdict(list); ctrs = defaultdict(lambda: defaultdict(Counter))
    for key, r in cen.items():
        c, repo = key.split("::", 1)
        if c != corpus:
            continue
        repos.append({"repo": repo, "sha": r["sha"], "licence": r["licence"], "bytes": r.get("bytes"),
                      "formats": {k: (v.get("sessions") or v.get("capture_rows")) for k, v in r.items() if isinstance(v, dict) and k not in ("unparsed_files", "_bad")},
                      "unparsed_files": r.get("unparsed_files")})
        for fmtk, v in r.items():
            if not isinstance(v, dict) or fmtk in ("unparsed_files", "_bad"):
                continue
            for kk, vv in v.items():
                if isinstance(vv, (int, float)) and not isinstance(vv, bool):
                    out[fmtk][kk] += vv
                elif isinstance(vv, dict) and "p50" in vv:
                    lists[f"{fmtk}::{kk}"].append(vv)
                elif isinstance(vv, dict):
                    for a, b in vv.items():
                        if isinstance(b, (int, float)):
                            ctrs[fmtk][kk][a] += b
    res = {}
    for fmtk, c in out.items():
        d = dict(c)
        for kk, ct in ctrs[fmtk].items():
            d[kk] = dict(Counter(ct).most_common(15))
        d["per_repo_quantiles_note"] = "quantiles are per repo (see census/census_downloaded.json); not pooled here"
        res[fmtk] = d
    return res, repos


def rate(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 5) if n else None}


corpora = {}
for corpus in ["cli-trace-commons", "cli-claude-code-hf", "cli-codex-hf", "cli-pi-hf", "agentcap-dacorvo"]:
    a, repos = agg_corpus(corpus)
    corpora[corpus] = {"aggregate_by_format": a, "repos": repos,
                       "bytes_on_disk": sum(r["bytes"] or 0 for r in repos),
                       "download_records": [x for x in dl["repos"] if x["corpus"] == corpus]}

# request-id / provider-clock coverage (interpretation-free counts)
rid = {}
for corpus, v in corpora.items():
    cc = v["aggregate_by_format"].get("claude_code")
    if cc:
        rid[corpus + "/claude_code"] = {
            "assistant_entries_with_anthropic_req_id": rate(cc.get("req_ids", 0), cc.get("assistant_entries", 0)),
            "tool_calls_whose_response_has_requestId": rate(cc.get("calls_with_requestId", 0), cc.get("tool_calls", 0)),
            "req_ids_decoding_as_uuidv7": rate(cc.get("req_v7", 0), cc.get("req_ids", 0)),
            "decoded_ids_within_minus2s_plus600s_of_entry_ts": rate(cc.get("req_agree", 0), cc.get("req_v7", 0)),
            "requestId_shapes": cc.get("requestId_shape")}
    pi = v["aggregate_by_format"].get("pi")
    if pi:
        fam = pi.get("responseId_family", {})
        rid[corpus + "/pi"] = {"assistant_messages": pi.get("assistant_messages"), "responseId_family_counts": fam,
                               "openai_resp_hex50_within_5s_of_message_ts": rate(pi.get("respid_within_5s::openai_resp_hex50", 0), fam.get("openai_resp_hex50", 0)),
                               "openrouter_gen_secs_within_5s": rate(pi.get("respid_within_5s::openrouter_gen_secs", 0), fam.get("openrouter_gen_secs", 0))}
    cx = v["aggregate_by_format"].get("codex")
    if cx:
        rid[corpus + "/codex"] = {"provider_request_or_response_ids": "none found: rollout response_item entries carry no id; no requestId-like key (sample audit id_like_keys empty)"}
    oc = v["aggregate_by_format"].get("opencode")
    if oc:
        rid[corpus + "/opencode"] = {"provider_request_or_response_ids": "none in the native export (sample audit id_like_keys empty)"}
    cap = v["aggregate_by_format"].get("captures")
    if cap:
        rid[corpus + "/captures"] = {"rows": cap.get("capture_rows"), "sse_first_chunk_id_shapes": cap.get("sse_id_shape"),
                                     "rows_with_sse_created": cap.get("sse_with_created"), "rows_with_sla_metrics_ts_us": cap.get("sse_with_sla_ts_us"),
                                     "capture_provider": cap.get("capture_provider"),
                                     "note": "request_id column is minted by the capture proxy (README), not the provider; provider ids live in the SSE body"}

# per-repo decode-delta quantiles (descriptive; delta = carrying timestamp minus id time, ms)
per_repo = {}
for key, r in cen.items():
    cc = r.get("claude_code") or {}
    pi = r.get("pi") or {}
    e = {}
    if cc.get("req_ids"):
        e["claude_code_req"] = {"req_ids": cc.get("req_ids"), "assistant_entries": cc.get("assistant_entries"), "v7": cc.get("req_v7"),
                                "within_m2s_p600s": cc.get("req_agree"), "delta_ms": cc.get("req_delta_ms")}
    elif cc.get("assistant_entries"):
        e["claude_code_req"] = {"req_ids": 0, "assistant_entries": cc.get("assistant_entries")}
    for fam in ("openai_resp_hex50", "openrouter_gen_secs"):
        if pi.get(f"respid_delta_ms::{fam}"):
            e[f"pi_{fam}"] = {"n": (pi.get("responseId_family") or {}).get(fam), "within_5s": pi.get(f"respid_within_5s::{fam}"),
                              "delta_ms": pi.get(f"respid_delta_ms::{fam}")}
    if e:
        per_repo[key] = e
rid["per_repo_decode_deltas"] = per_repo

# agentcap join: capture run_ids vs trace run folders
trace_runs = set()
for r in dl["repos"]:
    if r.get("status") == "DOWNLOADED" and r["corpus"] == "agentcap-dacorvo" and "traces" in r["repo"]:
        for p in glob.glob(os.path.join(r["dest"], "data", "*")):
            if os.path.isdir(p):
                trace_runs.add(os.path.basename(p))
cap_runs = Counter()
for key, r in cen.items():
    if key.startswith("agentcap-dacorvo::") and "captures" in r:
        cap_runs.update(r["captures"].get("capture_run_ids", {}))
agentcap_join = {"trace_run_folders": len(trace_runs), "capture_run_ids": len(cap_runs),
                 "capture_run_ids_matching_a_trace_folder": sum(1 for k in cap_runs if k in trace_runs),
                 "capture_rows_in_matching_runs": sum(n for k, n in cap_runs.items() if k in trace_runs),
                 "capture_rows_total": sum(cap_runs.values()),
                 "unmatched_capture_run_ids": sorted(k for k in cap_runs if k not in trace_runs)[:20],
                 "trace_folders_without_capture": sorted(k for k in trace_runs if k not in cap_runs)[:40]}

out = {
    "counts_from": {"hf_format_agent_traces_listing": "meta/hf_format_agent_traces.json", "census_summary": "census/hf_census_summary.json",
                    "dedupe": "census/dedupe_clusters.json", "sample_audit": "census/sample_audit.json", "pi_respid_decode": "census/pi_respid_decode.json",
                    "download_manifest_hf": "census/download_manifest.json", "download_manifest_github": "census/download_manifest_github.json",
                    "population_census": "census/census_downloaded.json", "marker_scan": "census/marker_scan.json", "tracelab_census": "census/census_tracelab.json"},
    "hf_agent_traces_population": {"n_format_agent_traces": fmt["n"], "retrieved_utc": fmt["retrieved_utc"],
                                   "datasets_by_gate_and_licence": summ["datasets_by_gate_and_licence"],
                                   "by_harness_class": summ["by_harness_class"],
                                   "dedupe": {k: dedupe[k] for k in ("n_with_native", "n_canonical", "n_copies", "distinct_native_files_all_open")}},
    "corpora": corpora, "provider_clock_coverage": rid, "agentcap_run_join": agentcap_join,
    "tracelab": {"download": dlg["assets"], "census": tl}, "marker_scan": mk,
    "pi_respid_sample_decode": pidec,
}
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
print("wrote", sys.argv[2])
print(json.dumps(rid, indent=1)[:3500]); print(agentcap_join)
