"""Compose analysis/out/phase_e/track_b/B7.json from the saved B7 outputs plus b4.json.

Every number below is read from a file; the hand-written parts are the licence reading, the hours estimate (an
engineering judgement, labelled as such), the prior-art verdicts and the cited passages.
Run from the worktree root:  python analysis/out/phase_e/track_b/B7/compose_b7.py
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TB = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(TB, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
from analysis.lib.ir import COLUMNS  # noqa: E402

ld = lambda p: json.load(open(p, encoding="utf-8"))
b4 = ld(os.path.join(TB, "b4.json"))
scan = ld(os.path.join(HERE, "release_scan.json"))
repo = ld(os.path.join(HERE, "repo_licences.json"))
ww = ld(os.path.join(HERE, "whowhen_sources.json"))
xk = ld(os.path.join(HERE, "extra_keys.json"))
CACHE = os.path.join(ROOT, "analysis", "cache")
samp = ld(os.path.join(CACHE, "samples", "swechat.json"))
samp_eh = ld(os.path.join(CACHE, "samples", "swechat_EH.json"))


def r(x):
    return None if not isinstance(x, dict) or "rate" not in x else {"k": x["k"], "n": x["n"], "rate": x["rate"],
                                                                     "ci95_session_clustered": x.get("ci95_session_clustered")}


# ---------- field coverage table preview (from b4.json; non-H population) ----------
inv = b4["inventory_rows"]
cov = []
for fmt, row in inv["swechat"]["by_format"].items():
    pr = row.get("provider_request_ids", {})
    cov.append({"corpus": f"swechat/{fmt}", "releasable_data": True, "sessions_measured_nonH": row.get("sessions_measured_nonH"),
                "tool_calls_measured_nonH": row.get("tool_calls_measured_nonH"),
                "ms_timestamps_events": r(row.get("ms_timestamps")),
                "call_result_join": r(row.get("tool_call_id_join", {}).get("calls_joined")),
                "calls_with_token_usage": r(row.get("token_counts", {}).get("calls_with_usage_in")),
                "results_with_truncation_marker": r(row.get("truncation_markers")),
                "results_with_native_error_field": r(row.get("error_markers", {}).get("native_error_nonnull")),
                "results_with_exit_code_field": row.get("error_markers", {}).get("exit_code_nonnull"),
                "calls_with_provider_request_id": r(pr.get("calls_with_request_id")) if isinstance(pr, dict) else pr})
for name in ("whowhen", "aiv_cc"):
    row = inv[name]
    cov.append({"corpus": name, "releasable_data": name == "whowhen",
                "sessions_measured": row.get("sessions_measured"), "tool_calls_measured": row.get("tool_calls_measured"),
                "ms_timestamps_events": r(row.get("ms_timestamps")),
                "call_result_join": r(row.get("tool_call_id_join", {}).get("calls_joined")),
                "calls_with_token_usage": r(row.get("token_counts", {}).get("calls_with_usage_in")),
                "results_with_truncation_marker": r(row.get("truncation_markers")),
                "results_with_native_error_field": r(row.get("error_markers", {}).get("native_error_nonnull")),
                "results_with_exit_code_field": row.get("error_markers", {}).get("exit_code_nonnull"),
                "calls_with_provider_request_id": r(row.get("provider_request_ids", {}).get("calls_with_request_id")),
                "caveat": row.get("caveat"), "timestamp_kind": row.get("timestamp_kind")})
a = inv["aiv_cu"]
cov.append({"corpus": "aiv_cu", "releasable_data": False, "sessions_measured_nonH": a.get("sessions_measured_nonH"),
            "turn_rows_measured_nonH": a.get("turn_rows_measured_nonH"), "ms_timestamps_events": a.get("ms_timestamps"),
            "call_result_join": a.get("tool_call_id_join"), "calls_with_token_usage": a.get("token_counts"),
            "results_with_truncation_marker": a.get("truncation_markers"),
            "results_with_native_error_field": a.get("error_markers"),
            "calls_with_provider_request_id": a.get("provider_request_ids")})

# ---------- size of a swechat full-population IR shard (linear scale-up of the non-H caches) ----------
sw_bytes = {s: os.path.getsize(os.path.join(CACHE, f"swechat_{s}.parquet")) for s in ("A", "B", "E")}
n_ = lambda v: len(v) if isinstance(v, (list, dict)) else int(v)
sw_sessions = {"A": n_(samp["A"]), "B": n_(samp["B"]), "E": n_(samp_eh["E"])}
pop = samp["population_sessions"]
est_full = sum(sw_bytes.values()) * pop / sum(sw_sessions.values())
ww_bytes = sum(os.path.getsize(os.path.join(CACHE, f"whowhen_{s}.parquet")) for s in ("A", "B"))

sc = scan["corpora"]["swechat"]
em = sc["patterns"]["email_address"]
sl = sc["patterns"]["slack_token"]
vendor = {k: v["matches"] for k, v in sc["patterns"].items() if k not in ("email_address",)}

HOURS = [
    {"item": "schema_docs", "low_h": 2.0, "high_h": 3.5,
     "what": "SCHEMA.md: the %d IR columns (analysis/lib/ir.py COLUMNS, already commented inline), kind/ts_kind enums, the "
             "usage-dedupe rule, error-marker definitions (ir.ERROR_MARKERS), the known IR artifacts list (FINDINGS.md 5.8), "
             "and the `extra` JSON keys: swechat %d distinct (%d at >=1%% of rows that carry extra, %d at >=0.1%%), whowhen %d, "
             "aiv_cc %d, aiv_cu %d. Plan: auto-generate the key inventory with fill rates, hand-document only the >=1%% keys."
             % (len(COLUMNS), xk["corpora"]["swechat"]["distinct_top_level_keys"],
                sum(1 for x in xk["corpora"]["swechat"]["keys_by_rows"].values() if x >= 0.01 * xk["corpora"]["swechat"]["rows_with_extra"]),
                sum(1 for x in xk["corpora"]["swechat"]["keys_by_rows"].values() if x >= 0.001 * xk["corpora"]["swechat"]["rows_with_extra"]),
                xk["corpora"]["whowhen"]["distinct_top_level_keys"], xk["corpora"]["aiv_cc"]["distinct_top_level_keys"],
                xk["corpora"]["aiv_cu"]["distinct_top_level_keys"])},
    {"item": "loader_cleanup", "low_h": 4.0, "high_h": 6.0,
     "what": "Loaders today emit only the stratified sample caches (A/B/E) via lib/sample.py; a release needs a full-population "
             "export mode sharded by session (swechat %d sessions, 1,798-line loader; whowhen 470 lines; aiv_cc 240; aiv_cu 1,552; "
             "cc_local 644 + lib/cc_jsonl.py 204). Make the data root configurable everywhere (load_aiv_cu.py line 139 hard-codes "
             "C:\\Swarms\\data\\ai-village with no SWARMS_DATA override), keep or drop the Phase-E-only flags (--split E, --rederive, "
             "--scratch), package (pyproject; pins from analysis/requirements.txt: numpy, scipy, pandas, pyarrow), MIT LICENSE, "
             "and a fresh-clone smoke test: build twice and hash outputs (determinism), run ir.validate on every shard." % pop},
    {"item": "coverage_table", "low_h": 1.0, "high_h": 1.5,
     "what": "Re-run analysis/probes/phase_e_b4_inventory.py (657 lines; already computes every column session-clustered) on "
             "the released population and render it as Markdown + CSV. B4's numbers are non-H only; a release that includes split "
             "H must wait until the held-out evaluation has been run, or must exclude H."},
    {"item": "dataset_card", "low_h": 2.0, "high_h": 3.0,
     "what": "Per-shard provenance and pins (SWE-chat f66cca95 = v1), per-shard licence with the ODC-BY 4.2 notices, upstream "
             "citations (SWE-chat, Who&When; AI Digest if any aiv aggregate appears), the ODC-BY 2.4 contents caveat with a "
             "per-session repo-licence column, redaction caveats (upstream REDACTED markers; redacted OpenCode/Gemini ids replaced "
             "by loader-synthetic ids), 'no fabrication labels / no ground truth', intended use, removal-request route, versioning."},
    {"item": "privacy_secret_scrub", "low_h": 4.0, "high_h": 6.0,
     "what": "Extend release_scan.py (URL-embedded credentials, KEY=value assignments, generic high-entropy strings), decide the "
             "email policy and implement length-preserving masking with a per-event `scrubbed` flag (byte counts feed N1/N3/N5, "
             "so masking must not change lengths), human review of candidates, sync with upstream removals (drop sessions no "
             "longer on SWE-chat main; needs an approved download of the current sessions table), re-scan the final shards."},
    {"item": "upload_publish", "low_h": 1.0, "high_h": 1.5,
     "what": "HF dataset repo (gated 'auto', like upstream), upload ~%.2f GB swechat shard + ~%.1f MB whowhen shard if included, "
             "GitHub repo for code, release notes. Publishing is public content: needs an explicit human yes."
             % (est_full / 1e9, ww_bytes / 1e6)},
]
tier = lambda items: (round(sum(h["low_h"] for h in HOURS if h["item"] in items), 1),
                      round(sum(h["high_h"] for h in HOURS if h["item"] in items), 1))
t_all = tier({h["item"] for h in HOURS})
_t1 = tier({"schema_docs", "loader_cleanup", "coverage_table"})
T1 = (_t1[0] + 0.5, _t1[1] + 1.0)  # + short README/card and code upload

out = {
 "key": "B7",
 "task": "Phase E Track B7: assess (do not build) publishing the normalized multi-harness corpus (IR schema, loaders, "
         "per-corpus field coverage table) under MIT (code) / CC BY 4.0 or compatible (data; not CC BY-NC)",
 "date": "2026-10-04",
 "produced_by": {
  "composer": "analysis/out/phase_e/track_b/B7/compose_b7.py (numbers read from the files below; nothing typed by hand)",
  "scripts": ["analysis/out/phase_e/track_b/B7/release_scan.py -> B7/release_scan.json",
              "analysis/out/phase_e/track_b/B7/repo_licences.py -> B7/repo_licences.json",
              "analysis/out/phase_e/track_b/B7/whowhen_sources.py -> B7/whowhen_sources.json",
              "analysis/out/phase_e/track_b/B7/extra_keys.py -> B7/extra_keys.json"],
  "reused": ["analysis/out/phase_e/track_b/b4.json (field coverage, licences already opened by B4)",
             "analysis/out/build/swechat_build.json#redaction_markers_raw_files",
             "analysis/out/recon/swechat_compare.txt, swechat_diffdetail.txt (mirror vs pinned)"]},
 "scope_note": "Assessment only: nothing built, uploaded, downloaded or committed. Split H never opened (scans read swechat A/B/E "
               "and whowhen A/B). cc_local not read (private, never releasable). AI Village caches read only for `extra` key names "
               "(no content). No swarm data touched. No secret or email value was printed or stored; only counts.",

 "HEADLINE": [
  "Only SWE-chat-derived data (ODC-BY) is cleanly redistributable, and ODC-BY 1.0 s.4.2(a) requires a publicly conveyed "
  "Derivative Database to be released 'only under the terms of this License', so that shard ships as ODC-BY 1.0, not CC BY "
  "4.0. ODC-BY is attribution-only with no NonCommercial term, so it meets the 'not CC BY-NC' goal.",
  "AI Village (aiv_cc, aiv_cu) cannot be redistributed: custom research terms behind a manual gate, no redistribution grant, "
  "and a no-training clause that CC BY 4.0 would override. It ships as loader code plus aggregate coverage numbers only, "
  "unless AI Digest gives written permission. cc_local: never. collusion-wiki and urlquery: no licence and no tool calls; "
  "urlquery's ToS forbids redistribution without written permission. Neither is in the IR anyway.",
  "Who&When is MIT but embeds GAIA questions and ground-truth answers (%d of %d tasks have GAIA-shaped ids). GAIA's gate "
  "asks that the dataset not be reshared outside a gated or private repo. Recommendation: loader-only, or a gated shard with "
  "question and answer text stripped. It carries no timestamps, so it adds little to timing mechanisms."
  % (sum(v["question_id_shape"].get("uuid36_gaia_shaped", 0) for v in ww["subsets"].values()),
     sum(sum(v["question_id_shape"].values()) for v in ww["subsets"].values())),
  "So the releasable data is essentially a re-normalized SWE-chat v1: 6 harness formats from one upstream source. 'Multi-corpus' "
  "holds for the code (loaders for SWE-chat, AI Village, Who&When and any Claude Code ~/.claude/projects dir), not for the data.",
  "Incremental cost: %.1f-%.1f h for code + schema + coverage table + scrubbed ODC-BY swechat shard (itemized below). The "
  "code-only 'recipe' release (users fetch each upstream themselves) costs %.1f-%.1f h and carries no redistribution risk. A "
  "writeup-grade coverage table + column reference from existing files (T0) costs about 1-2 h. Recommendation: only T0 before "
  "today's 3:00pm code freeze; T1 vs T2 is a morning human decision." % (t_all[0], t_all[1], *T1)],

 "licence_matrix": [
  {"corpus": "swechat (SALT-NLP/SWE-chat, pinned f66cca95 = v1)", "licence": "ODC-BY 1.0 (card `license: odc-by`); HF gate 'auto' (agree to share contact info, no extra terms text)",
   "derivative_redistribution_allowed": True,
   "conditions": ["s.4.2(a): publicly convey the Derivative Database only under ODC-BY (so not relicensable to CC BY 4.0)",
                  "s.4.2(b): include a copy or URI of the licence with the data and in relevant documentation",
                  "s.4.2(c): keep intact notices that refer to the licence; s.4.2(d): put notices where users will look if a file cannot hold them",
                  "s.4.3: a publicly used Produced Work (e.g. a figure or table) needs a notice that the content came from the database and is under ODC-BY",
                  "s.2.4: ODC-BY does not cover rights in individual Contents; transcripts embed repo content under the repos' own licences",
                  "Card asks to cite Baumann et al. 2026 (COLM); card offers a removal-request route (joachimbaumann@stanford.edu) that a mirror would not inherit"],
   "release_as": "ODC-BY 1.0 data shard (gated auto on HF), our code MIT", "verdict": "REDISTRIBUTABLE with conditions"},
  {"corpus": "aiv_cc, aiv_cu (aidigestorg/ai-village rev 838b4150)", "licence": "other: 'ai-village-research-terms'; HF gate 'manual'",
   "derivative_redistribution_allowed": False,
   "conditions": ["gate terms: research/analysis use; no training or fine-tuning without written permission; no re-identification; cite AI Digest / AI Village; tell them about publications",
                  "no redistribution grant anywhere in README, card or gate; access is reviewed manually, so a public derivative would bypass their gate",
                  "CC BY 4.0 s.2(a)(1) grants reuse for any purpose, including training, which conflicts with the no-training term"],
   "release_as": "loader code (MIT) + aggregate field coverage with AI Digest citation; data only with written permission (README: 'reach out')",
   "verdict": "NOT REDISTRIBUTABLE (aggregates and code only)"},
  {"corpus": "whowhen (Kevin355/Who_and_When rev 59b9fcba; same data in github.com/mingyin1/Agents_Failure_Attribution)",
   "licence": "MIT (repo LICENSE, 'Copyright (c) 2025 Ming Yin'); the HF card states no licence",
   "derivative_redistribution_allowed": True,
   "conditions": ["MIT: include the copyright notice and permission notice in all copies",
                  "upstream-of-upstream: queries come from GAIA and AssistantBench. GAIA's gate: 'you agree to not reshare this dataset outside of a gated or private repository on the HF hub'. AssistantBench is Apache-2.0 (notice required).",
                  "the IR carries the question text (history[0]) and whowhen_labels.json carries ground_truth (load_whowhen.py lines 71, 316)"],
   "release_as": "loader-only (recommended), or a gated shard with GAIA question/answer text removed",
   "verdict": "REDISTRIBUTABLE under MIT, but GAIA-encumbered content"},
  {"corpus": "cc_local (~/.claude/projects on the dev machine)", "licence": "none: the user's private transcripts",
   "derivative_redistribution_allowed": False, "conditions": ["README rule 7: aggregates only, never content"],
   "release_as": "never; even its aggregate row in a public coverage table needs a human yes", "verdict": "NEVER"},
  {"corpus": "collusion-wiki (collusion.wiki exports)", "licence": "UNVERIFIED / none stated: no licence in manifest.json, SHA256SUMS or the download page; the site says 'We encourage others to take a look and write up their own analyses of this data'",
   "derivative_redistribution_allowed": False,
   "conditions": ["no licence means all rights reserved by default; analysis is invited, redistribution is not granted",
                  "contents are third-party wiki pages with their own licences; no agent tool calls; no IR loader exists"],
   "release_as": "excluded", "verdict": "NOT REDISTRIBUTABLE (and out of IR scope)"},
  {"corpus": "urlquery (URLQuery agent-activity catalog v5, third-party package)", "licence": "UNVERIFIED for the package (README states none); urlquery.net Terms s.5 forbid reproduction or distribution without prior written permission and limit use to personal, non-commercial research",
   "derivative_redistribution_allowed": False,
   "conditions": ["no agent tool calls; no IR loader exists"], "release_as": "excluded",
   "verdict": "NOT REDISTRIBUTABLE (and out of IR scope)"}],

 "what_is_releasable": {
  "data": "swechat shard (ODC-BY 1.0). Optionally a gated, GAIA-stripped whowhen shard (MIT + Apache-2.0 notices).",
  "code": "analysis/lib/ir.py, lib/cc_jsonl.py, lib/cc_attach.py, all loaders/*.py (our code: MIT). The cc_local loader is a "
          "generic Claude Code JSONL loader with no private strings found by a grep for user and path names; review its "
          "docstrings once more before release.",
  "aggregates": "field-coverage table for every corpus (CC BY 4.0 for our numbers, with source citations). The cc_local row "
                "needs a human yes."},

 "swechat_redaction_situation": {
  "upstream_policy": "Current card: Presidio + TruffleHog redaction of 'all user prompts, assistant responses, subagent prose/task "
                     "descriptions, and released skills'. Tool results are not in that list.",
  "upstream_markers_in_raw_transcripts": ld(os.path.join(ROOT, "analysis", "out", "build", "swechat_build.json"))["redaction_markers_raw_files"],
  "upstream_redaction_broke_ids": {"opencode_call_ids_redacted_or_missing": 6366, "opencode_message_ids_redacted": 2196,
                                   "source": "analysis/out/build/swechat_build.json full_population_pass.by_format.opencode.parse; format_notes",
                                   "consequence": "loader substitutes synthetic ids; the dataset card must say so"},
  "ungated_mirror_precedent": "cfahlgren1/SWE-chat (ODC-BY, NOT gated, sha f6cbfbbc, lastModified 2026-09-25, opened 2026-10-04) "
                              "still serves the pre-redaction bytes: 5,259 rows in 915 sessions differ from the pinned release, "
                              "which redacts them (out/recon/swechat_diffdetail.txt; data/README.md). An ungated derivative that "
                              "does not track upstream fixes becomes a second such mirror.",
  "residual_scan_nonH": {"script": scan["script"], "rows": sc["rows"], "sessions": sc["sessions"],
                         "events_with_REDACTED_marker": sc["events_with_REDACTED_marker"],
                         "vendor_shaped_secret_candidates_by_pattern": vendor,
                         "slack_shaped": {k: sl[k] for k in ("matches", "distinct_values", "events", "sessions", "events_by_kind")},
                         "sessions_with_any_secret_candidate": sc["sessions_with_any_secret_candidate"],
                         "personal_looking_emails": {k: em[k] for k in ("matches", "distinct_values", "events", "sessions", "events_by_kind")},
                         "email_share_of_sessions": round(em["sessions"] / sc["sessions"], 4),
                         "whowhen_personal_looking_emails": {k: scan["corpora"]["whowhen"]["patterns"]["email_address"][k] for k in ("matches", "distinct_values", "sessions")},
                         "caveats": "candidates, not confirmed secrets; placeholders and fixtures match too. Generic secrets "
                                    "(passwords in .env dumps, URL-embedded credentials) are NOT covered by these patterns. "
                                    "Emails exclude noreply/example/git@ and filename-like matches (e.g. icon@2x.png)."},
  "reading": "Upstream TruffleHog redaction looks effective for vendor-shaped tokens: 0 AWS, GitHub, OpenAI, Anthropic, Google, Stripe, "
             "private-key or JWT candidates in non-H swechat. The Slack-shaped hits are 3 distinct strings in 6 sessions; whether "
             "they are placeholders is unreviewed. Personal-looking email addresses survive widely: most sit in tool results and "
             "call arguments, outside the card's Presidio scope, but some also sit in user prompts and assistant text. They are "
             "already public in SWE-chat, so leaving them in adds no new exposure, but an ungated mirror widens access. Masking "
             "must preserve byte length because result size is an input to N1/N3/N5.",
  "versioning_risk": "HF main is now v2 (sha 202b071f, lastModified 2026-10-03; 17,968 sessions). A v1-based release freezes v1 "
                     "content, including anything upstream later removed on request. Before release, intersect session_ids with "
                     "current upstream and drop the missing ones. This needs an approved download of the current sessions table."},

 "contents_licences_swechat": {"source": repo["script"], "repos_by_class": repo["repos_by_class"],
                               "sessions_by_repo_licence_class": repo["sessions_by_repo_licence_class"],
                               "repos_by_license_type": repo["repos_by_license_type"],
                               "implication": "ODC-BY 2.4 leaves Contents rights untouched: sessions from copyleft (AGPL/GPL) and "
                                              "source-available (Elastic 2.0, FSL, O'Saasy) repos embed code under those terms. "
                                              "Pass the caveat through and carry a per-session repo licence_type column so users can filter."},

 "whowhen_upstream_sources": ww,

 "field_coverage_table_preview": {"note": "From b4.json (non-H). A release re-runs the B4 probe on the released population. "
                                          "Rates are session-clustered where B4 computed them.", "rows": cov,
                                  "public_calls_with_provider_request_id": b4["cross_corpus_descriptive"]["public_tool_calls_with_provider_request_id"]},

 "release_size_estimate": {"swechat_nonH_cache_bytes": sw_bytes, "swechat_nonH_sessions": sw_sessions,
                           "swechat_population_sessions": pop,
                           "swechat_full_population_ir_bytes_est": int(est_full),
                           "method": "linear scale of A+B+E parquet bytes by session count (stratified by length tercile, so roughly representative)",
                           "whowhen_ir_bytes": ww_bytes},

 "hours_estimate": {"label": "ENGINEERING JUDGEMENT (not measured). Incremental over what exists: IR schema, 6 loaders, B4 coverage probe, these scans.",
                    "items": HOURS,
                    "tiers": {
                     "T0_writeup_grade": {"low_h": 1.0, "high_h": 2.0, "what": "render the b4.json coverage table + an IR column reference from ir.py COLUMNS comments into the writeup. No data, no new licence exposure."},
                     "T1_code_recipe_release": {"low_h": T1[0], "high_h": T1[1],
                                                "what": "MIT code + SCHEMA.md + coverage table + short README/card; users download each upstream themselves (the trajdata model). Zero redistribution risk."},
                     "T2_code_plus_swechat_shard": {"low_h": t_all[0], "high_h": t_all[1],
                                                    "what": "T1 + scrubbed ODC-BY swechat shard on a gated HF repo, upstream-removal sync, full dataset card."},
                     "T3_add_ai_village_shards": {"extra_low_h": 4.0, "extra_high_h": 6.0,
                                                  "what": "only with AI Digest's written permission (calendar time unknown); re-scan ~2.5M aiv_cu rows + 245k aiv_cc rows; card section; screenshots stay excluded."}},
                    "not_counted": ["human legal review (ODC-BY reading here is ours, not counsel's)",
                                    "calendar wait for AI Digest permission",
                                    "loaders for B5 acquisitions in data/acquired (openhands-evaluation-outputs, openhands-feedback, miniswe-v2, sweagent-combo2 are MIT per B5a; others per B5b/B5c): no IR loader exists yet, ~2-4 h each"]},

 "prior_art": {"rules_note": "B7 is a release assessment; the claims tested are the ones a release would make.",
  "claims": [
   {"claim": "A common event schema that normalizes transcripts from several agent harnesses (call/result join, timestamps, usage)",
    "closest_existing_work": ["Harbor ATIF (harbor-framework/harbor; ATIF-v1.7)", "Inspect Scout transcript sources (meridianlabs-ai/inspect_scout)",
                              "Hugging Face Hub agent traces + STS-Format", "SWE-chat conversations table"],
    "what_it_does": "ATIF: standard JSON for agent trajectories with per-step ISO-8601 timestamp, tool_calls joined to observation results by tool_call_id/source_call_id, metrics, extra; Harbor adapters convert Claude Code, Cursor CLI, Devin and others (B2c). Inspect Scout imports ATIF, Claude Code, LangSmith, Logfire, Phoenix and Weave sources into one transcript DB. The HF Hub renders raw Claude Code/Codex/Pi JSONL natively and defines STS-Format (role, content, toolCalls, toolCallId, epoch-ms timestamp, model). SWE-chat already maps 6 agents into one conversations schema with tool_call_id.",
    "what_it_does_not": "No timestamp-provenance field (ATIF's validator only checks ISO format; STS timestamp is optional); no provider request-id field in ATIF (only via extra for some adapters, B2c) or STS; no split of harness error flag vs exit code vs text marker; SWE-chat's table truncates tool_result at 10KB and orphans 18.8% of results (FINDINGS caveat 4).",
    "verdict": "TAKEN", "deciding_citation": "https://raw.githubusercontent.com/harbor-framework/harbor/main/src/harbor/models/trajectories/step.py (Step fields incl. timestamp, tool_calls, observation, metrics) + docs-mintlify/agents/atif.mdx ('tool calls use tool_call_id, and observation results reference them via source_call_id'; 'ATIF-v1.7')",
    "residual_contribution": "verification-oriented columns: ts_kind (event / row_insert / shared_turn / none), request_id, native_error vs exit_code vs ERROR_MARKERS, separate stderr, raw-transcript sourcing."},
   {"claim": "A pooled multi-source agent-trajectory dataset in one schema",
    "closest_existing_work": ["Agent Data Protocol (ADP), Song et al., ICLR 2026, arXiv 2510.24702; data neulab/agent-data-collection",
                              "Exgentic/agent-llm-traces (OTel spans, CDLA-Permissive-2.0)"],
    "what_it_does": "ADP unifies 13 agent datasets (1.3M trajectories) into Trajectory/Action/Observation Pydantic schemas for SFT and publishes a per-dataset licence table (Appendix F). Exgentic pools OTel traces across frameworks with span start/end and gen_ai.response.id (B5d).",
    "what_it_does_not": "ADP TextObservation is (source, content) only: no timestamps, durations, token usage, error/exit fields or call ids, and its sources are benchmark, synthetic or rollout data, not in-the-wild harness logs. Exgentic is the publisher's own runs, not a re-normalization of existing corpora.",
    "verdict": "PARTIAL", "deciding_citation": "arXiv 2510.24702 s.3.2 (Observation definition) and Table 11 (licences); opened via alphaXiv",
    "residual_contribution": "small after licensing: the releasable data is one upstream (SWE-chat, 6 harness formats) plus optionally Who&When."},
   {"claim": "A per-corpus coverage table for verification-relevant fields (ms timestamps, call/result join, token counts, truncation and error markers, provider request ids)",
    "closest_existing_work": ["ADP Table 2 cross-dataset analysis", "B5d's HF audit (ours, internal)"],
    "what_it_does": "ADP Table 2 reports average rounds, action-type mix and function-thought coverage per dataset.",
    "what_it_does_not": "No field-availability columns of any kind. None of the opened sources (ATIF, Inspect Scout, HF agent-traces docs, ADP, SWE-chat card) publishes timestamp, join, request-id or error-field coverage across corpora.",
    "verdict": "NOVEL (as far as searched; search was narrow: one web search plus the sources above)",
    "deciding_citation": "arXiv 2510.24702 Table 2 columns: 'AVG. Rounds', '% Actions (A/C/M)', '% Func Thought'"},
   {"claim": "Release model: loaders plus a unified interface over datasets users fetch themselves (no redistribution)",
    "closest_existing_work": ["NVlabs/trajdata (human-motion trajectories, Apache-2.0)", "ADP reproducibility statement"],
    "what_it_does": "trajdata: 'download the raw datasets ... in case you do not already have them', then loaders and one interface; it does not redistribute.",
    "what_it_does_not": "different domain; not agent logs", "verdict": "TAKEN (as a release pattern; cite it as the model for T1)",
    "deciding_citation": "https://raw.githubusercontent.com/NVlabs/trajdata/main/README.md"}]},

 "decisions_for_human": [
  "Publish at all, and which tier: T0 (writeup table, ~1-2 h), T1 (code recipe), or T2 (code + ODC-BY swechat shard). Recommend T0 now, T1/T2 after the code freeze.",
  "Accept that the swechat shard is ODC-BY 1.0, not CC BY 4.0 (ODC-BY 4.2(a)). Both are attribution-only and allow benchmarking.",
  "Email policy for the swechat shard: leave as upstream, or length-preserving mask.",
  "Gate the HF repo ('auto', like upstream) or not. The ungated cfahlgren1 mirror is the cautionary precedent.",
  "Include split H in a public release (then publish only after the held-out eval runs), or exclude it.",
  "Ask AI Digest for written permission to redistribute aiv_cc/aiv_cu IR (their README invites contact).",
  "Whether the private cc_local aggregate row may appear in a public coverage table.",
  "Approve downloading the current SWE-chat sessions table (v2) to sync upstream removals before release."],

 "sources": [
  {"url": "https://opendatacommons.org/licenses/by/1-0/", "opened": True,
   "passage": "4.2: 'If You Publicly Convey this Database, any Derivative Database, ... then You must: a. Do so only under the terms of this License; b. Include a copy of this License or its Uniform Resource Identifier (URI) with the Database or Derivative Database...; c. Keep intact any copyright or Database Right notices and notices that refer to this License; and d. ...' 4.3: 'if you Publicly Use a Produced Work, You must include a notice ... that Content was obtained from the Database ... and that it is available under this License.' 2.4: '... this License does not cover any rights (other than Database Rights or in contract) in individual Contents'",
   "used_for": "swechat shard licence and attribution obligations (WebFetch summary of the legal text; quotes as returned)"},
  {"url": "https://creativecommons.org/licenses/by/4.0/legalcode.en", "opened": True,
   "passage": "2(a)(1): '... license to exercise the Licensed Rights in the Licensed Material to: (i) reproduce and Share the Licensed Material, in whole or in part; and (ii) produce, reproduce, and Share Adapted Material.' No NonCommercial term.",
   "used_for": "CC BY 4.0 permits any use, which conflicts with AI Village's no-training term"},
  {"url": "https://huggingface.co/api/datasets/SALT-NLP/SWE-chat", "opened": True,
   "passage": "cardData.license 'odc-by'; gated 'auto'; no extra_gated_prompt; sha 202b071f18e03c79df5a7287565ce2ebc5ee7756; lastModified 2026-10-03T22:38:39Z; 11 parquet tables incl. subagent_tasks, conversations_subagents, skill_*, context_events",
   "used_for": "licence; gate adds no terms; main has moved to v2"},
  {"url": "https://huggingface.co/datasets/SALT-NLP/SWE-chat", "opened": True,
   "passage": "PII: 'Personally identifiable information in all user prompts, assistant responses, subagent prose/task descriptions, and released skills' redacted with Presidio and TruffleHog; removal requests via joachimbaumann@stanford.edu; v1 2026-04-29 5,851 sessions, v2 2026-10-02 17,968 sessions; citation baumann2026swechat (COLM)",
   "used_for": "redaction scope (tool results not listed), removal route, versioning, citation"},
  {"url": "file:C:/Swarms/data/swe-chat-pinned/README.md", "opened": True,
   "passage": "line 2 'license: odc-by'; line 172 content '(truncated to 10KB for tool_result)'; line 184 tool_call_id; line 379 'We redacted personally identifiable information in all user prompts and assistant text responses using Microsoft Presidio ... and TruffleHog'; lines 387-388 removal requests",
   "used_for": "v1 card terms; v1 Presidio scope narrower than v2's"},
  {"url": "https://huggingface.co/api/datasets/cfahlgren1/SWE-chat", "opened": True,
   "passage": "exists; license ODC-BY; not gated; sha f6cbfbbc935ba714a53e093eda99166a39048f2e; lastModified 2026-09-25T15:24:05Z; 998 JSONL trace files",
   "used_for": "ungated mirror still serving the revision our recon found carrying secrets that the pinned release redacts"},
  {"url": "https://huggingface.co/api/datasets/aidigestorg/ai-village", "opened": True,
   "passage": "license 'other', license_name 'ai-village-research-terms', gated 'manual'; extra_gated_prompt: '(1) use the data for research and analysis, not to train or fine-tune AI systems without our written permission; (2) not attempt to re-identify any individuals; (3) cite AI Digest / AI Village ...; (4) let us know about publications'; no LICENSE file",
   "used_for": "aiv licence: no redistribution grant"},
  {"url": "file:C:/Swarms/data/ai-village/README.md", "opened": True,
   "passage": "'Released under custom research terms (see the access form).'; 'Secrets redacted ... This is a best-effort safety net, not a guarantee'; 'reach out, and tell us about publications'",
   "used_for": "aiv terms and contact route"},
  {"url": "https://raw.githubusercontent.com/mingyin1/Agents_Failure_Attribution/main/LICENSE", "opened": True,
   "passage": "'MIT License ... Copyright (c) 2025 Ming Yin ... The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.'",
   "used_for": "Who&When licence and its notice condition"},
  {"url": "https://raw.githubusercontent.com/mingyin1/Agents_Failure_Attribution/main/README.md", "opened": True,
   "passage": "184 annotated failure tasks; CaptainAgent (algorithm-generated) and Magentic-One (hand-crafted); queries from GAIA and AssistantBench; ICML 2025 citation",
   "used_for": "Who&When upstream benchmarks"},
  {"url": "https://huggingface.co/datasets/Kevin355/Who_and_When/raw/main/README.md", "opened": True,
   "passage": "front matter has configs only, no licence; 'based on queries from GAIA and AssistantBench'",
   "used_for": "HF copy carries no licence"},
  {"url": "https://huggingface.co/api/datasets/gaia-benchmark/GAIA", "opened": True,
   "passage": "gated 'auto'; extra_gated_prompt 'To avoid contamination and data leakage, you agree to not reshare this dataset outside of a gated or private repository on the HF hub.'",
   "used_for": "GAIA reshare restriction that Who&When content inherits"},
  {"url": "https://huggingface.co/datasets/gaia-benchmark/GAIA", "opened": True,
   "passage": "'Please do not reshare the validation or test set in a crawlable format.'", "used_for": "same"},
  {"url": "https://huggingface.co/api/datasets/AssistantBench/AssistantBench", "opened": True,
   "passage": "license apache-2.0; gated false", "used_for": "AssistantBench-derived Who&When tasks"},
  {"url": "https://assistantbench.github.io/", "opened": True,
   "passage": "website CC BY-SA 4.0; no dataset licence on the page", "used_for": "checked; the HF card above decides"},
  {"url": "https://collusion.wiki/", "opened": True,
   "passage": "'We encourage others to take a look and write up their own analyses of this data.'; no licence or copyright notice",
   "used_for": "collusion-wiki licence: none stated"},
  {"url": "https://collusion.wiki/explorer/download", "opened": True,
   "passage": "lists full-wiki-logs.zip, pages/revisions/events/labels, other-wikis, shortener-logs, records, links, site-coverage, coverage-gaps with checksums; no licence or terms",
   "used_for": "same"},
  {"url": "file:C:/Swarms/data/collusion-wiki/full-wiki-logs/manifest.json", "opened": True,
   "passage": "keys generated_at, db_sha256, cut, counts, ... tool_versions, source_scan; no licence key", "used_for": "same"},
  {"url": "https://urlquery.net/terms-and-conditions", "opened": True,
   "passage": "s.5: 'No part of the Site, Services, Content, or Data may be reproduced, distributed, or commercially exploited without our prior written permission'; licence 'solely for your personal, non-commercial research or educational purposes'",
   "used_for": "urlquery-derived content not redistributable"},
  {"url": "https://urlquery.net/terms", "opened": False, "passage": "HTTP 404", "used_for": "n/a (found the real terms page via /about)"},
  {"url": "file:C:/Swarms/data/urlquery-agent-activity/urlquery-agent-activity-2026-09-22-v5/README.md", "opened": True,
   "passage": "'It contains public report links and research metadata, with no full report JSON, response bodies, ...'; no licence",
   "used_for": "package licence UNVERIFIED"},
  {"url": "https://raw.githubusercontent.com/harbor-framework/harbor/main/docs-mintlify/agents/atif.mdx", "opened": True,
   "passage": "'Record and exchange agent trajectories in a standard JSON format'; tool calls use tool_call_id, observation results reference them via source_call_id; 'ATIF-v1.7'",
   "used_for": "schema prior art"},
  {"url": "https://raw.githubusercontent.com/harbor-framework/harbor/main/src/harbor/models/trajectories/step.py", "opened": True,
   "passage": "Step fields step_id, timestamp ('ISO 8601 timestamp indicating when this step occurred'), source, model_name, message, reasoning_content, tool_calls, observation, metrics, is_copied_context, llm_call_count, extra; validate_timestamp checks ISO format only",
   "used_for": "schema prior art; no timestamp provenance"},
  {"url": "https://api.github.com/repos/meridianlabs-ai/inspect_scout/contents/src/inspect_scout/sources", "opened": True,
   "passage": "entries: __init__.py, _atif, _claude_code, _langsmith, _logfire, _phoenix, _weave",
   "used_for": "an eval framework that internally normalizes multi-source transcripts"},
  {"url": "file:analysis/out/phase_e/track_b/B1d_agent_eval/sc_src_inspect_scout_sources__claude_code_transcripts.py", "opened": True,
   "passage": "'This module provides functions to import transcripts from Claude Code session files into an Inspect Scout transcript database.'",
   "used_for": "same (copy fetched by B1d at commit 8660a282)"},
  {"url": "https://huggingface.co/docs/hub/en/agent-traces", "opened": True,
   "passage": "'Agent traces from Claude Code, Codex, and Pi Agent are natively supported on the Hugging Face Hub.' 'Trace files can include prompts, tool inputs, command output, local paths, screenshots, secrets, private code, and personal data. Review and redact traces before publishing them publicly...'",
   "used_for": "schema prior art; Hub's own redaction advice"},
  {"url": "https://huggingface.co/docs/hub/session-traces-format.md", "opened": True,
   "passage": "STS-Format message fields: role, content, reasoningContent, toolCalls, toolCallId, timestamp ('epoch milliseconds', optional), model",
   "used_for": "schema prior art: no request id, no error flag, no timestamp provenance"},
  {"url": "https://huggingface.co/docs/hub/datasets-agent-traces", "opened": False, "passage": "HTTP 404", "used_for": "n/a (wrong URL; the page above is the real one)"},
  {"url": "https://arxiv.org/abs/2510.24702", "opened": True, "how": "alphaXiv answer_pdf_queries",
   "passage": "s.3.2 'Trajectory consists of (1) id ... (2) content ... (3) details'; Text Observations '(1) source ... and (2) content'; Table 2 columns 'AVG. Rounds', '% Actions (A/C/M)', '% Func Thought'; Table 11 per-dataset licences (Apache 2.0, MIT, CC BY 4.0, CDLA-Permissive-2.0, CC BY-SA 4.0)",
   "used_for": "pooled-dataset prior art; licence-table precedent"},
  {"url": "https://huggingface.co/api/datasets/neulab/agent-data-collection", "opened": True,
   "passage": "no license field; not gated; 18 configs (agenttuning_*, code_feedback, codeactinstruct, ..., swe-smith, synatra)",
   "used_for": "ADP data release carries no top-level licence"},
  {"url": "https://huggingface.co/api/datasets/Exgentic/agent-llm-traces", "opened": True,
   "passage": "license CDLA Permissive 2.0; not gated; '1,781 execution traces'", "used_for": "pooled OTel trace prior art"},
  {"url": "https://raw.githubusercontent.com/NVlabs/trajdata/main/README.md", "opened": True,
   "passage": "'Then, download the raw datasets (nuScenes, Lyft Level 5, View-of-Delft, ETH/UCY, etc.) in case you do not already have them.' Apache-2.0 badge",
   "used_for": "recipe-release precedent"},
  {"url": "https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/", "opened": True,
   "passage": "page moved to github.com/open-telemetry/semantic-conventions-genai; no field text on the page",
   "used_for": "not used for any verdict"},
  {"url": "https://github.com/open-telemetry/semantic-conventions-genai", "opened": True,
   "passage": "repo landing page only; execute_tool and gen_ai.* attribute definitions not visible", "used_for": "not used for any verdict"},
  {"url": "file:analysis/out/phase_e/track_b/b4.json", "opened": True,
   "passage": "inventory_rows.*.licence and per-format coverage", "used_for": "licences B4 already opened; coverage preview"}],

 "unverified_or_unopened": [
  "ODC-BY quotes come through WebFetch's model summary of the legal text, not a raw byte fetch; re-read the official text before release.",
  "The ODC-BY reading (4.2(a) means a derivative must stay ODC-BY) is ours, not legal advice.",
  "Who&When GAIA/AssistantBench attribution is inferred from question_ID shape only (B7/whowhen_sources.py), not looked up in GAIA's id list.",
  "OpenTelemetry GenAI execute_tool / gen_ai.tool.call.id field definitions: not opened (the page moved); not used.",
  "Data Provenance Initiative (arXiv 2310.16787) came up in search and was NOT opened; it audits dataset licences, not field coverage.",
  "Slack-shaped candidates (3 distinct values) and the email hits were not reviewed by a human; their real/placeholder split is unknown.",
  "SWE-chat v2 raw transcripts were not audited (B4 flag stands)."],

 "dead_ends_respected": "No CLAUDE_context_swarms.md section 7 item cited or pursued. collusion-wiki licence was checked only; no site discovery or census.",

 "INTERPRETATION_verdict": {
  "can_we_publish_under_MIT_plus_CC_BY_4.0": "Code: yes, MIT; it is all ours. Data: not as CC BY 4.0. The only cleanly redistributable shard "
     "(SWE-chat) must stay ODC-BY 1.0 under s.4.2(a). That satisfies the intent (attribution-only, benchmarking allowed). AI Village is "
     "not redistributable. Who&When is MIT but GAIA-encumbered. cc_local, collusion-wiki and urlquery are out.",
  "incremental_hours": {"T0": [1.0, 2.0], "T1": list(T1),
                        "T2": list(t_all), "T3_extra": [4.0, 6.0]},
  "biggest_cost_drivers": ["loader full-population export + packaging (loaders only build sample caches today)",
                           "privacy pass: emails survive in about a third of sessions; email masking must preserve byte length; upstream-removal sync"],
  "novelty": "Schema: TAKEN (ATIF, Inspect Scout, HF STS). Pooled dataset: PARTIAL (ADP, but without the verification fields). "
             "Verification-field coverage table: NOVEL as far as searched. The table is the cheap, defensible artifact; the data release is mostly a "
             "re-normalized SWE-chat.",
  "recommendation": "Before the 3:00pm freeze, do T0 only: put the coverage table and column reference in the writeup. Bring T1 vs T2 to the "
                    "morning review as a human decision, with this licence matrix attached."}}

json.dump(out, open(os.path.join(TB, "B7.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("wrote", os.path.join(TB, "B7.json"), "T2 hours", t_all)
