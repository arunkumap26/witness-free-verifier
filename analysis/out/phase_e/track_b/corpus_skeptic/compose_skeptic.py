"""Corpus skeptic: compose the evidence file analysis/out/phase_e/track_b/corpus_skeptic.json.

Inputs (all written by the scripts in this directory, read-only over C:/Swarms/data/acquired):
  field_audit.json, full_counts.json, request_id_scan.json, combo2_synthetic.json, openhands_shapes.json,
  context_probe.json
plus a fresh disk census and the on-disk dataset cards (README front matter) of every acquired repo.
Doc claims compared against are transcribed from analysis/CORPUS_INVENTORY.md (pre-skeptic version, sha256 recorded).
Upstream licence spot checks were made with WebFetch in this session; they are recorded as sources, not computed.

Run:  PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/corpus_skeptic/compose_skeptic.py
"""
import datetime as dt
import glob
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
WT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
A = "C:/Swarms/data/acquired"
OUT = os.path.join(HERE, "..", "corpus_skeptic.json")
GB, GIB = 1e9, 2 ** 30
CAP_CORPUS_GB, CAP_TOTAL_GB = 5, 25


def load(name):
    return json.load(open(os.path.join(HERE, name), encoding="utf-8"))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def du(path, skip=()):
    tot = 0
    for dp, dn, fn in os.walk(path):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return tot


def card_licence(readme):
    lic = None
    with open(readme, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    if lines and lines[0].strip() == "---":
        for i, ln in enumerate(lines[1:], start=2):
            if ln.strip() == "---":
                break
            m = re.match(r"^licen[cs]e:\s*(.+)$", ln.strip())
            if m:
                lic = (m.group(1).strip(), i)
    return lic


def r(k, n):
    return round(k / n, 4) if n else None


FA = load("field_audit.json")["results"]
FC = load("full_counts.json")
RS = load("request_id_scan.json")
C2 = load("combo2_synthetic.json")
OH = load("openhands_shapes.json")
CP = load("context_probe.json")

RESEARCH_OK = {"mit", "apache-2.0", "cc-by-4.0", "cc0-1.0", "bsd-3-clause", "agpl-3.0"}
corpora = sorted(d for d in os.listdir(A) if os.path.isdir(os.path.join(A, d)))
disk = {}
total = 0
for c in corpora:
    p = os.path.join(A, c)
    b = du(p)
    b_nogit = du(p, skip=(".git",))
    b_core = du(p, skip=(".git", ".cache"))
    total += b
    disk[c] = {"bytes": b, "GB": round(b / GB, 3), "GiB": round(b / GIB, 3), "bytes_excluding_.git": b_nogit,
               "bytes_excluding_.git_and_.cache": b_core, "over_5GB_cap_on_disk": b / GB > CAP_CORPUS_GB,
               "over_5GB_cap_excluding_.git": b_nogit / GB > CAP_CORPUS_GB}

licences = {}
for c in corpora:
    rows = []
    for readme in sorted(glob.glob(os.path.join(A, c, "**", "README.md"), recursive=True)):
        rel = os.path.relpath(readme, A).replace("\\", "/")
        if "/.git/" in rel or "/tasks/" in rel or "/submissions/terminal-bench/2.0/" in rel or rel.startswith(c + "/submissions/"):
            continue
        lic = card_licence(readme)
        rows.append({"card": rel, "licence": lic[0] if lic else None, "line": lic[1] if lic else None})
    for prov in glob.glob(os.path.join(A, c, "**", "SOURCE.json"), recursive=True)[:1] + glob.glob(os.path.join(A, c, "**", "_b5e_provenance.json"), recursive=True):
        d = json.load(open(prov, encoding="utf-8"))
        rows.append({"card": os.path.relpath(prov, A).replace("\\", "/"), "licence": d.get("licence"), "line": None,
                     "kind": "acquisition record (B5c/B5e), not a dataset card"})
    licences[c] = rows

# ---- per-corpus verdicts -----------------------------------------------------------------
fa, fc = FA, FC
per = {}


def lic_summary(c):
    vals = sorted({(x["licence"] or "").lower() for x in licences[c] if x.get("licence") and not x.get("kind")})
    root_cards = [x for x in licences[c] if not x.get("kind") and "/_upload_staging/" not in x["card"]
                  and not re.search(r"/outputs/", x["card"])]
    return vals, root_cards


def entry(c, field_audit, request_ids, doc_claims_checked, notes, field_audit_pass, research_ok, licence_text):
    per[c] = {"exists": os.path.isdir(os.path.join(A, c)), "disk": disk[c], "licence_cards_on_disk": licences[c],
              "licence": licence_text, "research_use_ok": research_ok,
              "field_audit_resample": field_audit, "field_audit_pass": field_audit_pass,
              "request_ids_full_scan": request_ids, "doc_claims_checked": doc_claims_checked, "notes": notes}


def rid(c):
    v = RS["per_corpus"][c]
    return {k: v[k] for k in ("files", "bytes_scanned", "anth_matches", "anth_distinct", "files_with_anth", "keys",
                              "anth_by_prefix", "files_with_sk_ant", "files_with_oauth_env")}


t = fa["openhands-evaluation-outputs"]["tally"]
entry("openhands-evaluation-outputs",
      {"sample": "6 instances per run x 19 runs (seeded reservoir)", "events_with_ts": [t["events_with_ts"], t["events_n"]],
       "events_ts_subsecond": [t["events_ts_subsecond"], t["events_n"]],
       "observations_cause_resolves_flat_runs": [t["observations_cause_resolves"], t["observations"]],
       "tally": t, "history_shape_full_pass": OH["summary"]},
      rid("openhands-evaluation-outputs"),
      [{"claim": "312,115/318,298 events with ts", "doc_rate": r(312115, 318298), "skeptic_sample_rate": r(t["events_with_ts"], t["events_n"]), "status": "CONSISTENT"},
       {"claim": "history: v2.x (8 runs) flat; v1.9 (11 runs) [action, observation] pairs", "status": "WRONG",
        "skeptic": "full pass over all 5,695 instances: 9 runs flat, 10 runs pairs. claude-3-5-sonnet-20241022_maxiter_30_N_v1.9-no-hint is flat (joined by cause) but has no tool_call_metadata. B5a's own census_oh_eval.json per_run.history_format already shows 9 flat / 10 pair; the doc text (and B5a's prose) miscounted.",
        "evidence": "corpus_skeptic/openhands_shapes.json"},
       {"claim": "duplicate .part file, byte-identical, 153,841,006 B", "status": "CONFIRMED", "evidence": "request_id_scan.json#duplicates/openhands_part_files"},
       {"claim": "provider request ids: NO", "status": "CONFIRMED", "skeptic": "0 Anthropic-layout ids in 4.61 GB scanned"}],
      ["outputs/webarena/ holds only a 118-byte pointer README (726 B with folder); not a corpus.",
       "join is by cause in the 9 flat runs and positional in the 10 pair runs; the doc's 'by cause' label for the 145,631/145,966 total mixes both."],
      True, True, "MIT (card, on disk and upstream API @aa897780)")

t = fa["openhands-feedback"]["tally"]
entry("openhands-feedback",
      {"sample": "40 of 275 sessions (seeded)", "tool_actions_with_ts": [t["tool_actions_with_ts"], t["tool_actions_n"]],
       "tool_observations_with_ts": [t["tool_observations_with_ts"], t["tool_observations_n"]],
       "tool_observations_paired_to_id_minus_1_action": [t["tool_observations_paired_id_minus_1_to_tool_action"], t["tool_observations_n"]], "tally": t},
      rid("openhands-feedback"),
      [{"claim": "actions with ts 5,898/5,968", "doc_rate": r(5898, 5968), "skeptic_sample_rate": r(t["tool_actions_with_ts"], t["tool_actions_n"]), "status": "CONSISTENT"},
       {"claim": "strict pairing 5,552/5,974 (id-1 and echo match)", "doc_rate": r(5552, 5974), "skeptic_sample_rate_id_minus_1_only": r(t["tool_observations_paired_id_minus_1_to_tool_action"], t["tool_observations_n"]), "status": "CONSISTENT (looser rule, so higher)"}],
      ["real users' prompts: aggregates only (unchanged)."], True, True, "MIT (card on disk; B5a manifest license_tags)")

t = fa["miniswe-v2-qwen3-30b-swebv-tarsur385"]["tally"]
entry("miniswe-v2-qwen3-30b-swebv-tarsur385",
      {"sample": "40 of 499 trajectories", "assistant_with_ts": [t["assistant_with_ts"], t["assistant_n"]],
       "tool_with_ts": [t["tool_with_ts"], t["tool_n"]], "calls_joined": [t["calls_joined"], t["calls"]], "tally": t},
      rid("miniswe-v2-qwen3-30b-swebv-tarsur385"),
      [{"claim": "13,664/13,664 results join; 223 unjoined calls = final submit of 223 Submitted runs", "status": "CONSISTENT",
        "skeptic": "sample: %d unjoined calls, %d Submitted runs" % (t["calls"] - t["calls_joined"], t.get("exit_Submitted", 0))}],
      [], True, True, "MIT (card on disk; upstream API @58389eb5)")

t = fa["sweagent-combo2-rl-rollouts"]["tally"]
entry("sweagent-combo2-rl-rollouts",
      {"sample": "40 of 4,571 trajectories (seeded reservoir over the tar stream)", "assistant_with_ts": [t["assistant_with_ts"], t["assistant_n"]],
       "tool_with_ts": [t["tool_with_ts"], t["tool_n"]], "calls_joined": [t["calls_joined"], t["calls"]], "tally": t,
       "synthetic_flag_full_pass": C2["messages_extra_synthetic_by_role_value"]},
      rid("sweagent-combo2-rl-rollouts"),
      [{"claim": "4,525 tool results harness-flagged (combo_ground 4,361 + combo_empty_guard 164) + 101 user combo_valve", "status": "CONFIRMED with clarification",
        "skeptic": "every flagged tool message is accompanied by a user-role message carrying the same flag (4,361 + 164 more), so 9,151 messages carry extra.synthetic in shard 00; a raw-byte count gives 2x the tool figure. Count tool-role messages only when using these as labelled positives.",
        "evidence": "corpus_skeptic/combo2_synthetic.json"}],
      [], True, True, "MIT (card on disk; upstream API @eaff5487)")

t = fa["terminal-bench-2-leaderboard"]["tally"]
tcc = fa["terminal-bench-2-leaderboard"]["cc_tally"]
cen = fa["terminal-bench-2-leaderboard"]["census"]
agw = RS["claude_code_request_id_agreement"]["terminal-bench-2-leaderboard/WozCode__Claude-Opus-4.6"]
entry("terminal-bench-2-leaderboard",
      {"sample": fa["terminal-bench-2-leaderboard"]["sample"], "census": cen,
       "atif_steps_with_ts": [t["atif_steps_with_ts"], t["atif_steps_n"]], "atif_steps_ts_subsecond": [t["atif_steps_ts_subsecond"], t["atif_steps_n"]],
       "atif_results_with_source_call_id": [t["atif_obs_results_with_source_call_id"], t["atif_obs_results"]],
       "atif_results_step_paired": [t["atif_obs_results_step_paired"], t["atif_obs_results"]],
       "atif_steps_with_metrics": [t["atif_steps_with_metrics"], t["atif_steps_n"]], "atif_steps_with_nonzero_tokens": [t["atif_steps_with_nonzero_tokens"], t["atif_steps_n"]],
       "cc_entries_with_ts": [tcc["ua_entries_with_ts"], tcc["ua_entries_n"]], "cc_calls_joined": [tcc["calls_joined"], tcc["calls"]],
       "gemini_calls_joined": [t["gem_calls_joined"], t["gem_calls"]], "hookele_calls_joined": [t["hk_calls_joined"], t["hk_calls"]],
       "hookele_ts_subsecond": [t.get("hk_lines_ts_subsecond", 0), t["hk_lines_n"]]},
      {**rid("terminal-bench-2-leaderboard"), "wozcode_agreement": agw},
      [{"claim": "53 submissions without ATIF or native structured logs (so '1 of 75' has 53 unchecked)", "status": "WRONG",
        "skeptic": "%d of %d submissions hold structured logs (%d ATIF; native-only: %s); %d hold none" % (cen["submissions_with_any_structured_log"], cen["submissions"], cen["submissions_with"]["atif"], ", ".join(cen["native_only_submissions"]), cen["submissions_without_structured_log"])},
       {"claim": "request ids in 1 of 75 submissions (WozCode), 12,327 entries, 7,272 distinct, 12,279 agree", "status": "CONFIRMED",
        "skeptic": "entries %d, distinct %d, agree %d; correct denominator is 1 of %d submissions with logs" % (agw["entries_with_req"], agw["distinct_req_ids"], agw["entries_agree_-2s_+600s"], cen["submissions_with_any_structured_log"])},
       {"claim": "ATIF scan: 5 matches, all in mteb-leaderboard trials of 5 harnesses (probably task content)", "status": "PARTLY WRONG (regex artefact)",
        "skeptic": "compose_inventory.py's regex needs an unescaped closing quote, so it misses ids inside escaped JSON. The strict Anthropic-layout scan finds 6 ids in 6 non-WozCode files (Meta-Harness 3, Terminus-KIRA 2, JJAgent 1), all inside observation content or step message text (API error bodies), none in a harness field. The conclusion (no ATIF harness field carries request ids) stands.",
        "evidence": "corpus_skeptic/context_probe.json#tb2_non_wozcode_anthropic_req_ids"},
       {"claim": "1,766 early copies under submissions/ are byte-identical", "status": "CONFIRMED", "evidence": "request_id_scan.json#duplicates/tb2_early_copies"},
       {"claim": "446 files carry CLAUDE_CODE_OAUTH_TOKEN with sk-ant- value (pilot-real__claude-opus-4-6)", "status": "CONFIRMED",
        "skeptic": "446 files with an sk-ant- value, all under pilot-real__claude-opus-4-6; 449 files mention the variable name"},
       {"claim": "over the 5 GB cap only because of .git (4.814 GB without)", "status": "CONFIRMED"},
       {"claim": "ATIF metrics on 253,556 steps", "status": "CAVEAT", "skeptic": "metrics present does not mean token counts present: in the sample %d of %d steps with metrics have nonzero prompt or completion tokens" % (t["atif_steps_with_nonzero_tokens"], t["atif_steps_with_metrics"])}],
      ["hookele stamps are 1 s; its trajectory start line names model gpt-5.1-codex-max while the submission folder says gpt5.1-codex-mini (seen in one file; not counted)."],
      True, True, "Apache-2.0 (card on disk; upstream README @572b2614 opened)")

t = fa["glm52-nf3-tb21-traces"]["tally"]
entry("glm52-nf3-tb21-traces",
      {"sample": "20 of 86 ATIF files", "steps_with_ts": [t["atif_steps_with_ts"], t["atif_steps_n"]],
       "results_with_source_call_id": [t["atif_obs_results_with_source_call_id"], t["atif_obs_results"]], "tally": t},
      rid("glm52-nf3-tb21-traces"),
      [{"claim": "2,106/3,237 results by id, rest step-paired", "doc_rate": r(2106, 3237), "skeptic_sample_rate": r(t["atif_obs_results_with_source_call_id"], t["atif_obs_results"]), "status": "CONSISTENT"}],
      ["hf_repo/.git holds 14,145,658 B (not mentioned in the doc; negligible)."], True, True, "MIT (card on disk; upstream API @6020a41c)")

t = fa["osworld_verified_trajs"]["tally"]
entry("osworld_verified_trajs",
      {"sample": "4 traj.jsonl per submission x 20", "rows_with_ts": [t["rows_with_ts"], t["rows_n"]], "rows_ts_subsecond": [t["rows_ts_subsecond"], t["rows_n"]],
       "rows_with_call_id": [t["rows_with_call_id"], t["rows_n"]], "rows_with_screenshot_ref": [t["rows_with_screenshot_ref"], t["rows_n"]]},
      rid("osworld_verified_trajs"),
      [{"claim": "us 49,907 / s 95,890 / missing 20 of 145,817 steps", "doc_subsecond_rate": r(49907, 145817), "skeptic_sample_rate": r(t["rows_ts_subsecond"], t["rows_n"]), "status": "CONSISTENT"},
       {"claim": "Claude runs via Bedrock, 0 req_", "status": "CONFIRMED", "skeptic": "0 Anthropic-layout ids in all 23,213 files"}],
      ["PASS is weak: one pre-action stamp per step, no result-arrival time, positional join to a screenshot that was not downloaded. Two thirds of stamps are whole seconds."],
      "weak", True, "MIT (SOURCE.json records the card; upstream API @5473c39e)")

t = fa["webarena_infinity_trajs"]["tally"]
entry("webarena_infinity_trajs",
      {"sample": "40 of 844 history files", "steps_with_start_end": [t["step_start_with_ts"], t["steps"]],
       "steps_action_result_count_match": [t["steps_action_result_count_match"], t["steps"]]},
      rid("webarena_infinity_trajs"),
      [{"claim": "counts match in 9,078/9,241 steps", "doc_rate": r(9078, 9241), "skeptic_sample_rate": r(t["steps_action_result_count_match"], t["steps"]), "status": "CONSISTENT"},
       {"claim": "4 .incomplete files", "status": "BENIGN", "skeptic": "0-byte HF cache markers under .cache/; the 4 target history/result files exist"}],
      ["PASS is weak: one start/end window per step, positional action-result join, successful trajectories only."],
      "weak", True, "MIT (card on disk; upstream API @73cf7f57)")

ftl = FC["tracelab-uw"]
t = fa["tracelab-uw"]["tally"]
entry("tracelab-uw",
      {"sample": "3,000 of 665,453 rows", "tools_with_id_and_both_stamps_claude": [t["tools_with_id_and_both_stamps_claude"], t["tools_claude"]],
       "tools_with_id_and_both_stamps_codex": [t["tools_with_id_and_both_stamps_codex"], t["tools_codex"]], "full_pass": ftl},
      rid("tracelab-uw"),
      [{"claim": "8,058 sessions (5,319 + 2,739); 743,819 tools; both stamps 304,290 + 438,760", "status": "CONFIRMED (full pass)"}],
      ["no content, no provider ids (unchanged)."], True, True, "CC BY 4.0 data (LICENSE-DATASET.md @11b8b14c opened upstream; asks users not to re-identify contributors), Apache-2.0 code")

t = fa["cli-trace-commons"]["tally"]
ag = RS["claude_code_request_id_agreement"]["cli-trace-commons"]
entry("cli-trace-commons",
      {"sample": "all 29 session JSONL files", "entries_with_ts": [t["ua_entries_with_ts"], t["ua_entries_n"]], "calls_joined": [t["calls_joined"], t["calls"]]},
      {**rid("cli-trace-commons"), "agreement": ag},
      [{"claim": "7,496/7,499 assistant entries with requestId; 4,349 distinct; 7,496 agree", "status": "CONFIRMED"},
       {"claim": "data/ holds a parquet index", "status": "WRONG",
        "skeptic": "data/train-00000-of-00001.parquet has 30 rows with a `trace` column holding full session copies (the raw scan finds the same 7,503 request-id occurrences in data/ as in sessions/). Read one or the other, never both."}],
      ["5 request-id entries carry model `<synthetic>` (harness-written messages)."], True, True,
      "CC BY 4.0 for the compilation (card on disk; upstream API @112ebd4d); trace contents keep contributors' own licences")

fcc = FC["cli-claude-code-hf"]["tally"]
agu = RS["claude_code_request_id_agreement"]["cli-claude-code-hf (union)"]
entry("cli-claude-code-hf",
      {"sample": "full pass, 379 JSONL files", "entries_with_ts": [fcc["ua_entries_with_ts"], fcc["ua_entries_n"]], "calls_joined": [fcc["calls_joined"], fcc["calls"]],
       "distinct_sessionIds": FC["cli-claude-code-hf"]["distinct_sessionIds"]},
      {**rid("cli-claude-code-hf"), "agreement_union": agu},
      [{"claim": "377 files; 210 distinct sessionIds", "status": "PARTLY WRONG", "skeptic": "379 JSONL files (compose_inventory.json per_corpus also says 379); 210 sessionIds confirmed"},
       {"claim": "21,577/24,425 assistant entries with requestId; 7,660 distinct; 21,567 agree", "status": "CONFIRMED",
        "skeptic": "21,567 = assistant entries agreeing; all-type entries: 21,575 of 21,585 agree (8 system entries carry requestId; 2 entries in cfahlgren1 carry a non-Anthropic-layout req_ value of length 28)"},
       {"claim": "model strings include non-Claude names, so check the model before trusting a requestId", "status": "CLARIFIED",
        "skeptic": "on entries that carry requestId the models are only Claude names, `<synthetic>` (146) and None (8); non-Claude model strings never carry a requestId here"}],
      ["`<synthetic>` entries are harness-written; flag them before using their requestId as a provider clock."], True, True,
      "per repo on disk: MIT x5, Apache-2.0 x3, CC BY 4.0 x2, CC0 x1, AGPL-3.0 x1 (cfahlgren1, upstream API @0ba6f538 confirms agpl-3.0)")

entry("cli-codex-hf",
      {"sample": "all 46 rollouts", "lines_with_ts": [fa["cli-codex-hf"]["tally"]["lines_with_ts"], fa["cli-codex-hf"]["tally"]["lines_n"]],
       "calls_joined": [fa["cli-codex-hf"]["tally"]["calls_joined"], fa["cli-codex-hf"]["tally"]["calls"]]},
      rid("cli-codex-hf"),
      [{"claim": "46 rollouts, 3,381/3,381 by call_id, 17,617/17,617 lines", "status": "CONFIRMED (full pass)"}], [], True, True,
      "per repo on disk: CC BY 4.0 x3, MIT x3")

fpi = FC["cli-pi-hf"]
entry("cli-pi-hf",
      {"sample": "full pass, 544 JSONL files", "session_files": fpi["files_with_session_header_first"], "distinct_session_ids": fpi["distinct_session_ids"],
       "calls_joined": [fpi["tally"]["calls_joined"], fpi["tally"]["calls"]], "messages_epoch_ms": [fpi["tally"]["messages_epoch_with_ts"], fpi["tally"]["messages_epoch_n"]]},
      {**rid("cli-pi-hf"), "anthropic_ids_context": "all 31 in message text / error bodies; none in a harness field",
       "credential_like": [{k: v for k, v in x.items() if k != "context_masked"} for x in CP["cli-pi-hf_sk_ant"]]},
      [{"claim": "530 sessions, 23,974 calls, 23,928 joined", "status": "CONSISTENT with dedupe caveat",
        "skeptic": "530 session files but 522 distinct session ids: 7 files in julien-c__pi-sessions are copies under huggingface.js/ (6 byte-identical) and 1 session is shared by two thomasmustier repos; the 8 duplicate files hold 248 tool calls. 14 further JSONL files are pi-share-hf redaction manifests (427 rows, no timestamp). Joined calls: 23,927 here vs 23,928."},
       {"claim": "provider request ids: NO", "status": "CONFIRMED",
        "skeptic": "31 Anthropic-layout ids (14 distinct) occur only inside message text and API error bodies"},
       {"claim": "one file in lucacorbucci fails JSON decoding", "status": "CLARIFIED",
        "skeptic": "the failing file is the 0-byte .agents/skills/hf-cli/.hf-skill-manifest.json, not a session; the session JSONL parses 184/184 lines"},
       {"claim": "hygiene list in 2.4 is complete", "status": "INCOMPLETE",
        "skeptic": "one file in thomasmustier__pine-of-glass-sessions@b9a6b263 contains an `sk-ant-api03-` value (79 chars) in an x-api-key header of a curl command, twice. Not printed. Add to 2.4."}],
      ["4 repos (OmarRabhI, championswimmer, moikapy, woxQAQ) keep their data under _upload_staging/, whose generated README says `license: other`; the root card (the Hub card) says MIT or Apache-2.0."],
      True, True, "per repo root card: MIT x17, Apache-2.0 x4, CC BY 4.0 x1, BSD-3-Clause x1 (xhochy, upstream API @046e1aff confirms)")

fag = FC["agentcap-dacorvo"]["tally"]
entry("agentcap-dacorvo",
      {"sample": "full pass", "oc_parts_with_callID_and_output": [fag["oc_tool_parts_with_callID_and_output"], fag["oc_tool_parts"]],
       "oc_tool_start_end": [fag["oc_tool_end_with_ts"], fag["oc_tool_parts"]], "pi_calls_joined": [fag["pi_calls_joined"], fag["pi_calls"]],
       "captures": FA["agentcap-dacorvo"]["captures_tally"]},
      rid("agentcap-dacorvo"),
      [{"claim": "OpenCode 3,934/4,694 parts with callID+output; time on 4,685/4,694; Pi 6,804/6,805; 18,885 capture rows all matching a trace folder", "status": "CONFIRMED (full pass)"},
       {"claim": "capture request_id minted by the proxy", "status": "CONSISTENT", "skeptic": "18,885/18,885 are 32-hex values; 0 Anthropic-layout ids; captured_at is whole epoch seconds"}],
      ["the 760 OpenCode parts without output are status error (751), running (8), pending (1): calls with an error result or none, not a join failure."],
      True, True, "Apache-2.0 on all 9 cards on disk")

# ---- summary --------------------------------------------------------------------------
summary = {
    "corpora_marked_downloaded": 14, "dirs_present": sum(1 for c in corpora if per.get(c, {}).get("exists")),
    "disk_total_bytes": total, "disk_total_GB": round(total / GB, 3), "disk_total_GiB": round(total / GIB, 3),
    "over_per_corpus_cap_on_disk": [c for c in corpora if disk[c]["over_5GB_cap_on_disk"]],
    "over_per_corpus_cap_excluding_.git": [c for c in corpora if disk[c]["over_5GB_cap_excluding_.git"]],
    "licence_permits_research_use": sum(1 for c in per if per[c]["research_use_ok"]),
    "field_audit_pass": sum(1 for c in per if per[c]["field_audit_pass"] is True),
    "field_audit_pass_weak": [c for c in per if per[c]["field_audit_pass"] == "weak"],
    "request_id_carriers_confirmed": ["terminal-bench-2-leaderboard (WozCode only)", "cli-trace-commons", "cli-claude-code-hf (10 of 12 repos)"],
    "request_id_NO_rows_confirmed_by_full_scan": [c for c in corpora if RS["per_corpus"][c]["anth_matches"] == 0],
    "git_status_note": "no file under analysis/out/phase_e/track_b/ (incl. b4.json, B5*.json, corpus_inventory.json) is committed (git ls-files shows none); the B5 rows of the request-id column rest on uncommitted evidence. The B4 rows were checked against committed files instead (see committed_evidence_check).",
}
committed = {
    "swechat": {"committed_file": "analysis/out/phase_c/ids_and_clocks_in_ids.json#census.swechat.request_id.claude_code.anthropic_req",
                "committed_value": "split B: 287,574 rows, 154,765 distinct ids, 1,639 sessions; all time-format (clocks: 155,326 ids incl. copies)",
                "doc_value": "A u B u E: 305,727 distinct ids, 3,270 sessions with >=1 id",
                "check": "ratio 305,727/154,765 = 1.975 vs sessions 3,270/1,639 = 1.995: consistent; B split alone cannot confirm the A u E part", "status": "CONSISTENT"},
    "swechat_population": {"committed_file": "analysis/out/build/swechat_build.json#full_population_pass.by_format.claude_code", "committed_value": "584,802 calls, 583,958 results", "doc_value": "pop. 584,802 calls", "status": "MATCH"},
    "cc_local": {"committed_file": "analysis/out/build/cc_local_build.json#full_corpus_ir.usage_fill.call", "committed_value": "n 41,707, request_id fill 1.0", "doc_value": "41,707/41,707", "status": "MATCH"},
    "aiv_cc": {"committed_file": "analysis/out/build/aiv_cc_build.json#full_corpus_ir.usage_fill.call", "committed_value": "n 72,225, request_id fill 0.0", "doc_value": "0/72,225", "status": "MATCH"},
}
doc_path = os.path.join(WT, "analysis", "CORPUS_INVENTORY.md")
inputs = {n: sha(os.path.join(HERE, n)) for n in ("field_audit.json", "full_counts.json", "request_id_scan.json", "combo2_synthetic.json", "openhands_shapes.json", "context_probe.json")}
sources = [
    {"url": "https://huggingface.co/api/datasets/sweagent/combo2-rl-rollouts", "opened": True, "saw": "sha eaff5487b8983db9aaed9e93c16e670695389827; cardData.license mit; tag license:mit; gated false"},
    {"url": "https://huggingface.co/api/datasets/OpenHands/openhands-evaluation-outputs", "opened": True, "saw": "sha aa8977805b4cefd317001d80ddf1ad52790e9d23; license mit; gated false"},
    {"url": "https://huggingface.co/api/datasets/xlangai/ubuntu_osworld_verified_trajs", "opened": True, "saw": "sha 5473c39e42a538a187a9b2c2b499db59d560fd8c; license mit; gated false"},
    {"url": "https://huggingface.co/api/datasets/cfahlgren1/Fable-5-traces", "opened": True, "saw": "sha 0ba6f53852f296f8389290b112054b47cec2dc1f; license agpl-3.0; gated false"},
    {"url": "https://huggingface.co/api/datasets/0xSero/glm-5.2-nf3-hybrid-terminal-bench-2.1-traces", "opened": True, "saw": "sha 6020a41cb40ca06761d96250d80afef96d086e2a; license MIT; gated false"},
    {"url": "https://huggingface.co/api/datasets/trace-commons/agent-traces", "opened": True, "saw": "sha 112ebd4d03ce852b00e935d523107c3d0c9a65bf; license cc-by-4.0; gated false"},
    {"url": "https://huggingface.co/api/datasets/webarena-x/webarena-infinity-trajectories", "opened": True, "saw": "sha 73cf7f57a6ff61c95722a23bffdd9c1de4069bfe; license mit; gated false"},
    {"url": "https://huggingface.co/api/datasets/tarsur385/qwen3-30b-a3b-instruct-2507-swebench-verified-mini-swe-agent", "opened": True, "saw": "sha 58389eb5426db5a3ae6159faa37498072b4735ff; license MIT; gated false"},
    {"url": "https://huggingface.co/api/datasets/xhochy/conda-forge-agent-traces", "opened": True, "saw": "sha 046e1aff399803cc767fc76d91860ffd65b24add; license bsd-3-clause; gated false"},
    {"url": "https://huggingface.co/api/datasets/harborframework/terminal-bench-2-leaderboard", "opened": False, "saw": "fetch failed: response over the 10 MB tool limit (file listing); replaced by the README at the pinned revision"},
    {"url": "https://huggingface.co/datasets/harborframework/terminal-bench-2-leaderboard/raw/572b2614be2c0cb2527e14f5b1e4026f1072e6c1/README.md", "opened": True, "saw": "License: Apache 2.0 (front matter `license: apache-2.0`); 'SUBMISSIONS CLOSED' notice; same bytes' content as the on-disk card"},
    {"url": "https://raw.githubusercontent.com/uw-syfi/TraceLab/11b8b14c6005808ab272b3431487066832582414/LICENSE-DATASET.md", "opened": True, "saw": "'Creative Commons Attribution 4.0 International License (CC BY 4.0)'; asks users not to re-identify contributors"},
]
doc = {"key": "corpus_skeptic", "task": "Phase E Track B corpus skeptic: re-check every corpus marked downloaded in CORPUS_INVENTORY.md (files on disk, licence, size caps, field audit re-run on a sample, request-id column vs committed evidence); correct the doc.",
       "produced_by": "analysis/out/phase_e/track_b/corpus_skeptic/compose_skeptic.py",
       "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "method": {"independence": "all parsers and scanners written fresh in corpus_skeptic/; none imports B5 scripts, compose_inventory.py or analysis/lib",
                  "seen_data": "structural counts only (presence, resolution, joins, ids); no latency, gap or duration statistic computed",
                  "secrets": "credential-like values counted and classed, never printed or stored",
                  "scope": "C:/Swarms/data/acquired only; swechat H split, cc_local raw and anything swarm-related not opened"},
       "inputs_sha256": inputs, "doc_checked": {"path": "analysis/CORPUS_INVENTORY.md", "sha256_before_edit": "0e2a20afd93dc04bf5d36256d60176a7b5f38e0aa554aa2f69ac8c1147f410c1",
                       "sha256_after_edit": sha(doc_path),
                       "edits": "corrections in place (sections 0, 1.1, 1.3, 2.4, 5.3, 5.6, 5.10, 5.11, 5.13, 6) plus an appended 'Skeptic changes' section"},
       "summary": summary, "per_corpus": per, "committed_evidence_check": committed, "sources": sources,
       "doc_corrections": [
           {"section": "0, 1.1", "was": "1 of 75 submissions; 53 submissions without ATIF or native structured logs", "now": "1 of 25 submissions with structured logs (75 in repo); 50 without", "evidence": "corpus_skeptic/field_audit.json#results/terminal-bench-2-leaderboard/census"},
           {"section": "1.1", "was": "ATIF scan: 5 matches, all in mteb-leaderboard trials", "now": "strict scan: 6 Anthropic-layout ids in Meta-Harness/Terminus-KIRA/JJAgent files, all in content or message text; CI regex misses escaped JSON; conclusion unchanged", "evidence": "corpus_skeptic/context_probe.json#tb2_non_wozcode_anthropic_req_ids"},
           {"section": "1.1", "was": "(silent)", "now": "evidence status: track_b files uncommitted; B4 rows match committed files; B5 rows re-derived from data", "evidence": "committed_evidence_check"},
           {"section": "1.3, 5.11", "was": "377 files", "now": "379 JSONL files; requestId-bearing entries carry only Claude, <synthetic> (146) or no model (8); 2 non-layout req_ values", "evidence": "corpus_skeptic/full_counts.json, request_id_scan.json#claude_code_request_id_agreement"},
           {"section": "1.3, 5.13", "was": "530 sessions; lucacorbucci file fails JSON decoding", "now": "530 session files / 522 distinct ids, 8 duplicates hold 248 calls; 14 manifest JSONL; failing file is an empty skill manifest; _upload_staging cards say other", "evidence": "corpus_skeptic/full_counts.json"},
           {"section": "5.3", "was": "v2.x (8 runs) flat; v1.9 (11 runs) pairs", "now": "9 flat (one v1.9-named, no tool_call_metadata) / 10 pairs; detect per line", "evidence": "corpus_skeptic/openhands_shapes.json"},
           {"section": "5.10", "was": "data/ holds a parquet index", "now": "data/ parquet holds full session copies (trace column)", "evidence": "request_id_scan.json#per_corpus/cli-trace-commons/anth_by_prefix"},
           {"section": "5.6", "was": "4,525 tool results flagged", "now": "confirmed for tool role; each also has a user-role message with the same flag (9,151 flagged messages)", "evidence": "corpus_skeptic/combo2_synthetic.json"},
           {"section": "2.4, 6", "was": "credential list: TB2 OAuth tokens, sammshen bearer", "now": "adds one sk-ant-api03- value in cli-pi-hf thomasmustier/pine-of-glass-sessions (not printed); .incomplete markers benign", "evidence": "corpus_skeptic/context_probe.json#cli-pi-hf_sk_ant"},
           {"section": "0", "was": "All 14 passed the field audit before download", "now": "adds skeptic re-run: 14/14 pass, OSWorld and WebArena-Infinity weakly", "evidence": "per_corpus/*/field_audit_pass"},
       ],
       "VERDICT_REASONING": {
           "label": "Reasoning, not measurement.",
           "overall": "All 14 directories exist and match the doc's byte counts. Every licence permits research use. Only TB2 is over the 5 GB cap, and only through its .git folder. The field audit re-run agrees with the doc on all 14 corpora within sampling noise; OSWorld and WebArena-Infinity pass only weakly (one stamp or window per step, positional join). The request-id column holds: the three new carriers reproduce exactly, and a full-content scan finds no Anthropic-layout id in any harness field of the 11 NO corpora. Corrections are counts and descriptions (TB2 submissions without logs, OpenHands run shapes, trace-commons parquet, cli-claude-code-hf file count, ATIF scan matches), one missed credential-like value (cli-pi-hf), and dedupe caveats (cli-pi-hf, combo2 flag doubling).",
       }}
json.dump(doc, open(OUT, "w", encoding="utf-8"), indent=1)
print(json.dumps(summary, indent=1))
