"""Phase E Track B: consolidated corpus inventory (feeds analysis/CORPUS_INVENTORY.md).

Run from the worktree root:
    PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/corpus_inventory/compose_inventory.py

Writes analysis/out/phase_e/track_b/corpus_inventory.json. Every number in CORPUS_INVENTORY.md is either copied from a
Track B evidence file (the JSON records the key path it was read from) or computed here:

  1. disk census of C:/Swarms/data/acquired (bytes and file counts per corpus dir; .git dirs; *.part files; cap check)
  2. Anthropic request-id census over the PUBLIC raw Claude Code JSONL we downloaded (cli-trace-commons,
     cli-claude-code-hf, terminal-bench-2-leaderboard WozCode__Claude-Opus-4.6): entries carrying `requestId`, distinct
     ids, distinct sessionIds, and cross-repo / cross-corpus overlap of both. Counts only; no id value is written out.
     swechat is NOT re-scanned (its H split must not be read); its distinct count is copied from b4.json (non-H).
  3. agentcap capture -> trace join check: capture rows whose run_id equals a trace-repo folder name (B5e's census
     field capture_rows_run_in_traces looked only inside each capture repo, so it could not see the trace folders).
  4. the corpus registry (21 corpora held) and the request-id carrier count derived from it.
  5. loader-format list for the acquired corpora and the extrapolated loader hours (B7's per-loader 2-4 h judgement
     times the number of new formats).

Read-only on data/. Nothing under swarm/, data/swarm/ or .claude/worktrees/swarm is read. Downloaded code is never run.
"""
import glob
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TB = os.path.dirname(HERE)                                   # analysis/out/phase_e/track_b
PHASE_E = os.path.dirname(TB)                                # analysis/out/phase_e
DATA = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
ACQ = os.path.join(DATA, "acquired")
OUT = os.path.join(TB, "corpus_inventory.json")

INPUTS = {
    "b4": os.path.join(TB, "b4.json"),
    "b4_probe": os.path.join(PHASE_E, "b4_inventory.json"),
    "B5a": os.path.join(TB, "B5a_sweagent_openhands.json"),
    "B5b": os.path.join(TB, "B5b_aider_tbench_metr.json"),
    "B5b_idclock": os.path.join(TB, "B5b_aider_tbench_metr", "id_clock_checks.json"),
    "B5c": os.path.join(TB, "B5c_web_os_agents.json"),
    "B5d": os.path.join(TB, "B5d_hf_search.json"),
    "B5e": os.path.join(TB, "B5e_cli_traces.json"),
    "B5e_census": os.path.join(TB, "B5e_cli_traces", "census", "census_downloaded.json"),
    "B6": os.path.join(TB, "B6.json"),
    "B7": os.path.join(TB, "B7.json"),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(key):
    with open(INPUTS[key], encoding="utf-8") as f:
        return json.load(f)


def get(obj, path):
    """Follow a '/'-separated key path; list indices are ints. Keys that themselves contain '/' (b4.json uses
    'swechat/claude_code') are matched greedily: segments are joined until the dict has the key."""
    cur = obj
    parts = path.split("/")
    i = 0
    while i < len(parts):
        if isinstance(cur, list):
            cur = cur[int(parts[i])]
            i += 1
            continue
        j = i
        key = parts[i]
        while key not in cur and j + 1 < len(parts):
            j += 1
            key = key + "/" + parts[j]
        cur = cur[key]
        i = j + 1
    return cur


def src(key, path, obj):
    return {"value": get(obj, path), "from": os.path.relpath(INPUTS[key], os.path.dirname(PHASE_E)).replace("\\", "/") + "#" + path}


# ---------------------------------------------------------------- 1. disk census
def disk_census():
    rows = {}
    for d in sorted(os.listdir(ACQ)):
        p = os.path.join(ACQ, d)
        if not os.path.isdir(p):
            continue
        b = n = git_b = 0
        parts = []
        for dp, dn, fn in os.walk(p):
            in_git = (os.sep + ".git") in dp or dp.endswith(".git") or "/.git" in dp.replace("\\", "/")
            for f in fn:
                fp = os.path.join(dp, f)
                try:
                    s = os.path.getsize(fp)
                except OSError:
                    continue
                b += s
                n += 1
                if in_git:
                    git_b += s
                if f.endswith(".part"):
                    parts.append({"path": os.path.relpath(fp, ACQ).replace("\\", "/"), "bytes": s})
        rows[d] = {"bytes": b, "GB": round(b / 1e9, 3), "files": n, "git_bytes": git_b, "git_GB": round(git_b / 1e9, 3),
                   "bytes_excluding_git": b - git_b, "GB_excluding_git": round((b - git_b) / 1e9, 3), "part_files": parts,
                   "part_GB": round(sum(x["bytes"] for x in parts) / 1e9, 3)}
    total = sum(r["bytes"] for r in rows.values())
    cap = 5 * 10**9
    return {
        "root": ACQ.replace("\\", "/"),
        "measured_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "per_dir": rows,
        "n_dirs": len(rows),
        "total_bytes": total,
        "total_GB": round(total / 1e9, 3),
        "cap_total_GB": 25,
        "cap_per_corpus_GB": 5,
        "headroom_to_total_cap_GB": round(25 - total / 1e9, 3),
        "dirs_over_per_corpus_cap_on_disk": [k for k, r in rows.items() if r["bytes"] > cap],
        "dirs_over_per_corpus_cap_excluding_git": [k for k, r in rows.items() if r["bytes_excluding_git"] > cap],
        "note": "GB = 1e9 bytes. git_bytes counts files under any .git directory (git partial clones used by B5b).",
    }


# ---------------------------------------------------------------- 2. request-id census (public raw CC JSONL)
def cc_reqid_scan():
    groups = {}
    for repo_dir in sorted(glob.glob(os.path.join(ACQ, "cli-trace-commons", "*@*"))):
        groups["cli-trace-commons::" + os.path.basename(repo_dir)] = repo_dir
    for repo_dir in sorted(glob.glob(os.path.join(ACQ, "cli-claude-code-hf", "*@*"))):
        groups["cli-claude-code-hf::" + os.path.basename(repo_dir)] = repo_dir
    groups["terminal-bench-2-leaderboard::WozCode__Claude-Opus-4.6"] = os.path.join(
        ACQ, "terminal-bench-2-leaderboard", "hf_repo", "submissions", "terminal-bench", "2.0", "WozCode__Claude-Opus-4.6")

    per = {}
    ids_by = {}
    sess_by = {}
    for g, root in groups.items():
        c = Counter()
        ids = set()
        sess = set()
        for dp, dn, fn in os.walk(root):
            for f in fn:
                if not f.endswith(".jsonl"):
                    continue
                c["jsonl_files"] += 1
                with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                    for ln in fh:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            o = json.loads(ln)
                        except Exception:
                            c["bad_lines"] += 1
                            continue
                        if not isinstance(o, dict):
                            continue
                        c["entries"] += 1
                        sid = o.get("sessionId")
                        if isinstance(sid, str):
                            sess.add(sid)
                        if o.get("type") == "assistant":
                            c["assistant_entries"] += 1
                        rid = o.get("requestId")
                        if isinstance(rid, str) and rid.startswith("req_"):
                            c["entries_with_req_id"] += 1
                            ids.add(rid)
        corpus = g.split("::")[0]
        per[g] = dict(c, distinct_req_ids=len(ids), distinct_session_ids=len(sess), corpus=corpus)
        ids_by[g] = ids
        sess_by[g] = sess

    # overlap across repos and across corpora
    keys = list(groups)
    pair_overlap = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            oi = len(ids_by[a] & ids_by[b])
            os_ = len(sess_by[a] & sess_by[b])
            if oi or os_:
                pair_overlap.append({"a": a, "b": b, "shared_req_ids": oi, "shared_session_ids": os_})
    by_corpus_ids = defaultdict(set)
    by_corpus_sess = defaultdict(set)
    by_corpus = defaultdict(Counter)
    for g in keys:
        cp = per[g]["corpus"]
        by_corpus_ids[cp] |= ids_by[g]
        by_corpus_sess[cp] |= sess_by[g]
        for k in ("jsonl_files", "entries", "assistant_entries", "entries_with_req_id", "bad_lines"):
            by_corpus[cp][k] += per[g].get(k, 0)
    corp = {}
    for cp in by_corpus:
        corp[cp] = dict(by_corpus[cp], distinct_req_ids=len(by_corpus_ids[cp]), distinct_session_ids=len(by_corpus_sess[cp]))
    cnames = sorted(corp)
    cross = []
    for i in range(len(cnames)):
        for j in range(i + 1, len(cnames)):
            a, b = cnames[i], cnames[j]
            cross.append({"a": a, "b": b, "shared_req_ids": len(by_corpus_ids[a] & by_corpus_ids[b]),
                          "shared_session_ids": len(by_corpus_sess[a] & by_corpus_sess[b])})
    union_ids = set().union(*by_corpus_ids.values())
    return {
        "definition": "entry = one JSON object line in a .jsonl file; entries_with_req_id = entries whose top-level "
                      "`requestId` is a string starting 'req_'; distinct ids/sessions are set sizes. Within-corpus "
                      "union, so ids repeated across repos of one corpus count once at corpus level.",
        "scope": "public raw Claude Code JSONL downloaded in Phase E B5 (TB2: hf_repo copy only, not the early "
                 "duplicate copies under terminal-bench-2-leaderboard/submissions). swechat and cc_local not rescanned.",
        "per_repo": per,
        "per_corpus": corp,
        "repo_pairs_with_any_overlap": pair_overlap,
        "corpus_pairs_overlap": cross,
        "union_distinct_req_ids_new_public": len(union_ids),
    }


def atif_reqid_scan():
    """B5b scanned only native Claude Code JSONL for requestId. This checks the ATIF trajectory.json files of the TB2
    subset and the GLM set for request-id-like keys or Anthropic-shaped req_ values (raw text regex, counts only)."""
    import re
    rx = re.compile(r'"req_[0-9A-Za-z]{20,}"|"request[-_]?[iI]d"|x-request-id')
    res = {}
    roots = {"terminal-bench-2-leaderboard": os.path.join(ACQ, "terminal-bench-2-leaderboard", "hf_repo", "submissions"),
             "glm52-nf3-tb21-traces": os.path.join(ACQ, "glm52-nf3-tb21-traces", "hf_repo", "traces")}
    for name, root in roots.items():
        files = hits_files = hits = 0
        by_sub = Counter()
        by_task = Counter()
        for dp, dn, fn in os.walk(root):
            if "trajectory.json" not in fn:
                continue
            files += 1
            with open(os.path.join(dp, "trajectory.json"), encoding="utf-8", errors="replace") as fh:
                n = len(rx.findall(fh.read()))
            if n:
                hits_files += 1
                hits += n
                rel = os.path.relpath(dp, root).replace("\\", "/").split("/")
                by_sub[rel[2] if name.startswith("terminal") and len(rel) > 2 else rel[0]] += 1
                task = [p for p in rel if "__" in p and not p.startswith(("terminal-bench",))]
                by_task[task[-1].split("__")[0] if task else "?"] += 1
        res[name] = {"atif_files": files, "files_with_match": hits_files, "matches": hits,
                     "files_with_match_by_submission": dict(by_sub), "files_with_match_by_task": dict(by_task)}
    res["note"] = ("Regex on raw text, so a match can sit inside task content or tool output rather than in a harness "
                   "field; files_with_match_by_task shows where they are.")
    return res


# ---------------------------------------------------------------- 3. agentcap capture -> trace join
def agentcap_join(census):
    trace_dirs = set()
    for repo_dir in glob.glob(os.path.join(ACQ, "agentcap-dacorvo", "*-traces@*")):
        for p in glob.glob(os.path.join(repo_dir, "data", "*")):
            if os.path.isdir(p):
                trace_dirs.add(os.path.basename(p))
    rows = matched = 0
    runs = matched_runs = 0
    per_repo = {}
    for k, v in census.items():
        if not k.startswith("agentcap-dacorvo::") or "captures" not in v:
            continue
        cr = v["captures"]["capture_run_ids"]
        r_rows = sum(cr.values())
        r_match = sum(n for r, n in cr.items() if r in trace_dirs)
        per_repo[k] = {"capture_rows": v["captures"]["capture_rows"], "rows_in_run_id_counter": r_rows,
                       "rows_whose_run_id_is_a_trace_folder": r_match,
                       "run_ids": len(cr), "run_ids_matching_a_trace_folder": sum(1 for r in cr if r in trace_dirs)}
        rows += r_rows
        matched += r_match
        runs += len(cr)
        matched_runs += per_repo[k]["run_ids_matching_a_trace_folder"]
    return {
        "method": "run_id counts from B5e census_downloaded.json captures.capture_run_ids (complete per repo: its row "
                  "sum is checked against capture_rows); trace folder names = directories under "
                  "agentcap-dacorvo/*-traces@*/data/. Folder-level match only: per-call alignment (turn/time) is NOT tested.",
        "trace_folders": len(trace_dirs),
        "per_capture_repo": per_repo,
        "capture_rows": rows,
        "capture_rows_matching_trace_folder": matched,
        "capture_run_ids": runs,
        "capture_run_ids_matching_trace_folder": matched_runs,
        "why_B5e_reported_0": "census_downloaded.py L270-275 builds trace_runs from the capture repo's own data/ "
                              "directory, which holds parquet files, not run folders; so capture_rows_run_in_traces is 0 "
                              "by construction and says nothing about the join.",
    }


# ---------------------------------------------------------------- 4. registry
def registry(I):
    b4 = I["b4"]
    pc = "REQUEST_ID_COLUMN_FIRST/per_corpus/"
    cen = I["B5e_census"]

    def cen_sum(prefix, fmt, key):
        return sum(v.get(fmt, {}).get(key, 0) for k, v in cen.items() if k.startswith(prefix))

    R = [
        # name, origin, public, harness/provider of ids, request-id evidence
        {"name": "swechat", "origin": "B4", "public": True, "carries_provider_request_ids": True,
         "id_family": "Anthropic req_ (first-party + Vertex req_vrtx_), Claude Code format only",
         "evidence": {"calls_with_request_id_claude_code": src("b4", pc + "swechat/claude_code/calls_with_request_id", b4),
                      "distinct_request_ids_nonH": src("b4", pc + "swechat/claude_code/distinct_request_ids", b4),
                      "calls_with_request_id_all_formats": src("b4", pc + "swechat/all_formats/calls_with_request_id", b4)}},
        {"name": "cc_local", "origin": "B4", "public": False, "carries_provider_request_ids": True,
         "id_family": "Anthropic req_ (first-party)",
         "evidence": {"calls_with_request_id": src("b4", pc + "cc_local/calls_with_request_id", b4),
                      "distinct_request_ids": src("b4", pc + "cc_local/distinct_request_ids", b4)}},
        {"name": "aiv_cc", "origin": "B4", "public": True, "carries_provider_request_ids": False,
         "evidence": {"calls_with_request_id": src("b4", pc + "aiv_cc/calls_with_request_id", b4)}},
        {"name": "aiv_cu", "origin": "B4", "public": True, "carries_provider_request_ids": False,
         "evidence": {"request_id_keys_in_raw_scan": src("b4", pc + "aiv_cu/request_id_keys_in_raw_scan", b4),
                      "raw_scan_rows": src("b4", pc + "aiv_cu/raw_scan_rows", b4)},
         "other_provider_ids_with_time": "Gemini responseId (1 s), OpenAI item ids (1 s), Anthropic msg_ (ms, post 2026-07-06) per b4.json"},
        {"name": "whowhen", "origin": "B4", "public": True, "carries_provider_request_ids": False,
         "evidence": {"calls_with_request_id": src("b4", pc + "whowhen/calls_with_request_id", b4)}},
        {"name": "collusion-wiki", "origin": "B4", "public": True, "carries_provider_request_ids": False,
         "note": "external witness, no LLM calls", "evidence": {"note": src("b4", pc + "collusion_wiki/note", b4)}},
        {"name": "urlquery-agent-activity", "origin": "B4", "public": True, "carries_provider_request_ids": False,
         "note": "external witness, no LLM calls", "evidence": {"note": src("b4", pc + "urlquery/note", b4)}},
        {"name": "terminal-bench-2-leaderboard", "origin": "B5b", "public": True, "carries_provider_request_ids": True,
         "id_family": "Anthropic req_ in 1 of 75 submissions (WozCode__Claude-Opus-4.6, Claude Code)",
         "evidence": {"entries_with_requestId": src("B5b_idclock", "anthropic_requestId/WozCode__Claude-Opus-4.6/entries_with_requestId", I["B5b_idclock"]),
                      "distinct_requestIds": src("B5b_idclock", "anthropic_requestId/WozCode__Claude-Opus-4.6/distinct_requestIds", I["B5b_idclock"]),
                      "sessions_with_ge1_requestId": src("B5b_idclock", "anthropic_requestId/WozCode__Claude-Opus-4.6/sessions_with_ge1_requestId", I["B5b_idclock"]),
                      "agree": src("B5b_idclock", "anthropic_requestId/WozCode__Claude-Opus-4.6/agree_event_minus_id_in_[-2s,+600s]", I["B5b_idclock"]),
                      "glm_entries_with_requestId": src("B5b_idclock", "anthropic_requestId/ClaudeCode__GLM-4.7/entries_with_requestId", I["B5b_idclock"]),
                      "cchuter_entries_with_requestId": src("B5b_idclock", "anthropic_requestId/cchuter__minimax-m2.5/entries_with_requestId", I["B5b_idclock"])},
         "other_provider_ids_with_time": "hookele OpenAI resp_ (1 s) 12,804 per B5b id_clock_checks.json"},
        {"name": "cli-trace-commons", "origin": "B5e", "public": True, "carries_provider_request_ids": True,
         "id_family": "Anthropic req_ (Claude Code)",
         "evidence": {"assistant_entries_with_req_B5e": {"value": cen_sum("cli-trace-commons::", "claude_code", "req_ids"),
                                                          "from": "analysis/out/phase_e/track_b/B5e_cli_traces/census/census_downloaded.json#cli-trace-commons::*/claude_code/req_ids (sum)"},
                      "assistant_entries_B5e": {"value": cen_sum("cli-trace-commons::", "claude_code", "assistant_entries"),
                                                "from": "analysis/out/phase_e/track_b/B5e_cli_traces/census/census_downloaded.json#cli-trace-commons::*/claude_code/assistant_entries (sum)"}}},
        {"name": "cli-claude-code-hf", "origin": "B5e", "public": True, "carries_provider_request_ids": True,
         "id_family": "Anthropic req_ (Claude Code), 10 of 12 repos",
         "evidence": {"assistant_entries_with_req_B5e": {"value": cen_sum("cli-claude-code-hf::", "claude_code", "req_ids"),
                                                          "from": "analysis/out/phase_e/track_b/B5e_cli_traces/census/census_downloaded.json#cli-claude-code-hf::*/claude_code/req_ids (sum)"},
                      "assistant_entries_B5e": {"value": cen_sum("cli-claude-code-hf::", "claude_code", "assistant_entries"),
                                                "from": "analysis/out/phase_e/track_b/B5e_cli_traces/census/census_downloaded.json#cli-claude-code-hf::*/claude_code/assistant_entries (sum)"}}},
        {"name": "cli-codex-hf", "origin": "B5e", "public": True, "carries_provider_request_ids": False,
         "evidence": {"headline": src("B5e", "headline/request_id_column/codex_and_opencode_native", I["B5e"])}},
        {"name": "cli-pi-hf", "origin": "B5e", "public": True, "carries_provider_request_ids": False,
         "other_provider_ids_with_time": "OpenAI resp_ hex50 responseId (1 s) and OpenRouter gen-<s>, per B5e headline",
         "evidence": {"pi_openai_responses": src("B5e", "headline/request_id_column/pi_openai_responses", I["B5e"])}},
        {"name": "agentcap-dacorvo", "origin": "B5e", "public": True, "carries_provider_request_ids": False,
         "note": "capture request_id is minted by the capture proxy; local models + HF-Router",
         "evidence": {"agentcap_wire_captures": src("B5e", "headline/request_id_column/agentcap_wire_captures", I["B5e"])}},
        {"name": "tracelab-uw", "origin": "B5e", "public": True, "carries_provider_request_ids": False,
         "evidence": {"field_audit": src("B5e", "corpora_downloaded/0/field_audit/provider_request_ids", I["B5e"])}},
        {"name": "openhands-evaluation-outputs", "origin": "B5a", "public": True, "carries_provider_request_ids": False,
         "note": "model_response.id + created per action in v2.x runs; no request id",
         "evidence": {"provider_request_ids": src("B5a", "corpora_downloaded/0/field_audit/provider_request_ids/present", I["B5a"])}},
        {"name": "openhands-feedback", "origin": "B5a", "public": True, "carries_provider_request_ids": False,
         "evidence": {"provider_request_ids": src("B5a", "corpora_downloaded/1/field_audit/provider_request_ids/present", I["B5a"])}},
        {"name": "miniswe-v2-qwen3-30b-swebv-tarsur385", "origin": "B5a", "public": True, "carries_provider_request_ids": False,
         "evidence": {"provider_request_ids": src("B5a", "corpora_downloaded/2/field_audit/provider_request_ids/present", I["B5a"])}},
        {"name": "sweagent-combo2-rl-rollouts", "origin": "B5a", "public": True, "carries_provider_request_ids": False,
         "evidence": {"provider_request_ids": src("B5a", "corpora_downloaded/3/field_audit/provider_request_ids/present", I["B5a"])}},
        {"name": "glm52-nf3-tb21-traces", "origin": "B5b", "public": True, "carries_provider_request_ids": False,
         "evidence": {"provider_request_ids": src("B5b", "corpora/1/provider_request_ids", I["B5b"])}},
        {"name": "osworld_verified_trajs", "origin": "B5c", "public": True, "carries_provider_request_ids": False,
         "other_provider_ids_with_time": "Meta Muse Spark resp_ ids (8 hex Unix seconds), 1 of 20 downloaded submissions",
         "evidence": {"what_is_missing": src("B5c", "downloaded/osworld_verified_trajs/schema_note/what_is_missing", I["B5c"])}},
        {"name": "webarena_infinity_trajs", "origin": "B5c", "public": True, "carries_provider_request_ids": False,
         "evidence": {"note": "B5c corpora row provider_request_ids = none (see B5c_web_os_agents.json and the evidence summary)"}},
    ]
    carriers = [r["name"] for r in R if r["carries_provider_request_ids"]]
    carriers_public = [r["name"] for r in R if r["carries_provider_request_ids"] and r["public"]]
    b4_count = get(b4, "REQUEST_ID_COLUMN_FIRST/corpora_carrying_provider_request_ids/count_strict")
    b4_of = get(b4, "REQUEST_ID_COLUMN_FIRST/corpora_carrying_provider_request_ids/of_corpora_audited")
    b4_pub = get(b4, "REQUEST_ID_COLUMN_FIRST/corpora_carrying_provider_request_ids/public_count")
    return {
        "definition": "provider request id = per-HTTP-request id minted by the LLM provider and stored by the harness "
                      "(b4.json REQUEST_ID_COLUMN_FIRST/definition). Response/message/item ids are NOT counted here even "
                      "when they embed time; they are listed under other_provider_ids_with_time.",
        "unit": "corpus = one B4 corpus or one top-level directory under data/acquired (swechat mirror excluded: superseded, unaudited)",
        "corpora": R,
        "n_corpora_held": len(R),
        "n_B4": sum(1 for r in R if r["origin"] == "B4"),
        "n_acquired": sum(1 for r in R if r["origin"] != "B4"),
        "carriers": carriers,
        "n_carriers": len(carriers),
        "carriers_public": carriers_public,
        "n_carriers_public": len(carriers_public),
        "harness_provider_pairs_among_carriers": ["Claude Code -> Anthropic"],
        "B4_baseline": {"count_strict": b4_count, "of": b4_of, "public_count": b4_pub,
                        "from": "analysis/out/phase_e/track_b/b4.json#REQUEST_ID_COLUMN_FIRST/corpora_carrying_provider_request_ids"},
    }


# ---------------------------------------------------------------- 5. loader formats + hours
def loaders():
    reuse = [
        {"format": "Claude Code JSONL", "corpora": ["cli-trace-commons", "cli-claude-code-hf", "terminal-bench-2-leaderboard (WozCode, ClaudeCode__GLM-4.7, cchuter)"],
         "existing_code": "analysis/lib/cc_jsonl.py (used by load_cc_local.py and load_swechat.parse_claude_code)"},
        {"format": "Codex rollout JSONL", "corpora": ["cli-codex-hf"], "existing_code": "analysis/loaders/load_swechat.py parse_codex (same session_meta/turn_context/response_item/event_msg envelope; CLI versions differ, untested)"},
        {"format": "OpenCode export JSON {info, messages}", "corpora": ["agentcap-dacorvo (opencode traces)", "cli-trace-commons (1 file)"], "existing_code": "analysis/loaders/load_swechat.py parse_opencode (same envelope per B5e schema note; untested)"},
        {"format": "Gemini-CLI chat JSON", "corpora": ["terminal-bench-2-leaderboard (Gemini_CLI submissions)"], "existing_code": "analysis/loaders/load_swechat.py parse_gemini (B5b field list matches; untested)"},
    ]
    new = [
        {"format": "OpenHands eval output.jsonl (v1.9 pair list and v2.x flat event list)", "corpora": ["openhands-evaluation-outputs"]},
        {"format": "OpenHands feedback parquet (trajectory[] per row, no cause column)", "corpora": ["openhands-feedback"]},
        {"format": "mini-swe-agent v2 .traj.json", "corpora": ["miniswe-v2-qwen3-30b-swebv-tarsur385"]},
        {"format": "combo2 RL rollout JSON inside tar.gz (stream, do not extract)", "corpora": ["sweagent-combo2-rl-rollouts"]},
        {"format": "Harbor ATIF trajectory.json + trial result.json (api_request_times_msec)", "corpora": ["terminal-bench-2-leaderboard", "glm52-nf3-tb21-traces"]},
        {"format": "hookele .hookele/traj.jsonl", "corpora": ["terminal-bench-2-leaderboard (hookele)"]},
        {"format": "OSWorld traj.jsonl (+ runtime.log for Claude/Muse Spark/klick ids and usage)", "corpora": ["osworld_verified_trajs"]},
        {"format": "browser-use history.json", "corpora": ["webarena_infinity_trajs"]},
        {"format": "TraceLab round rows (content-free)", "corpora": ["tracelab-uw"]},
        {"format": "Pi session JSONL v3", "corpora": ["cli-pi-hf", "agentcap-dacorvo (pi traces)"]},
        {"format": "agentcap capture parquet (join-only side table)", "corpora": ["agentcap-dacorvo (captures)"]},
    ]
    optional = [{"format": "asciinema v2 recording.cast (second terminal clock)", "corpora": ["terminal-bench-2-leaderboard (3 submissions)", "glm52-nf3-tb21-traces"]}]
    per_lo, per_hi = 2.0, 4.0
    return {
        "reuse_with_adapter": reuse,
        "new_loaders": new,
        "optional_witness_loaders": optional,
        "n_new_loaders": len(new),
        "n_reuse": len(reuse),
        "per_loader_hours_B7": [per_lo, per_hi],
        "per_loader_hours_from": "analysis/out/phase_e/track_b/B7.json#hours_estimate/not_counted (\"~2-4 h each\", engineering judgement)",
        "new_loader_hours_extrapolated": [per_lo * len(new), per_hi * len(new)],
        "label": "EXTRAPOLATION of B7's engineering judgement (not measured): n_new_loaders x 2-4 h. Reuse adapters and the "
                 "optional cast loader are not included; the IR enum for corpus/ts_kind also needs extending.",
    }


SOURCES = [
    # Local files this task opened (opened=true). External works are relayed from sibling evidence files with the
    # passage those tasks recorded; this task did not re-open them (opened=false, opened_by names the task).
    {"url": "analysis/out/phase_e/track_b/b4.json", "opened": True, "used_for": "B4 inventory rows, request-id column, CIs"},
    {"url": "analysis/out/phase_e/b4_inventory.json", "opened": True, "used_for": "B4 probe output (numbers behind b4.json)"},
    {"url": "analysis/out/phase_e/track_b/B5a_sweagent_openhands.json", "opened": True, "used_for": "OpenHands/SWE-agent family acquisitions"},
    {"url": "analysis/out/phase_e/track_b/B5b_aider_tbench_metr.json (+ id_clock_checks.json, tb2_stats_v2.json, glm_stats_v2.json)", "opened": True, "used_for": "TB2/GLM acquisitions, WozCode request ids, hookele resp_ clock"},
    {"url": "analysis/out/phase_e/track_b/B5c_web_os_agents.json", "opened": True, "used_for": "OSWorld/WebArena acquisitions"},
    {"url": "analysis/out/phase_e/track_b/B5d_hf_search.json", "opened": True, "used_for": "HF search funnel, pending-approval list"},
    {"url": "analysis/out/phase_e/track_b/B5e_cli_traces.json (+ census/census_downloaded.json, scripts/census_downloaded.py)", "opened": True, "used_for": "CLI trace acquisitions; census bug in capture join counter (L270-275)"},
    {"url": "analysis/out/phase_e/track_b/B6.json", "opened": True, "used_for": "B6 assessment"},
    {"url": "analysis/out/phase_e/track_b/B7.json", "opened": True, "used_for": "B7 assessment"},
    {"url": "analysis/PHASE_E_PROMPT.md, analysis/PHASE_E_PLAN.md, C:/Swarms/CLAUDE_context_swarms.md s5-7", "opened": True, "used_for": "brief, caps, dead ends"},
    {"url": "analysis/loaders/load_swechat.py (docstring), analysis/lib/ir.py", "opened": True, "used_for": "which native formats existing loaders already parse; IR enums"},
    {"url": "C:/Swarms/data/acquired/** (directory metadata; Claude Code JSONL requestId/sessionId/type fields)", "opened": True, "used_for": "disk census, distinct request-id census, agentcap folder names"},
    {"url": "https://huggingface.co/datasets/sammshen/wildclaw-opus-traces (README)", "opened": False, "opened_by": "B6", "passage_recorded_by_sibling": "'Full agentic traces from running WildClawBench tasks through Claude Opus 4.6 via an instrumented reverse proxy.'", "used_for": "B6 method TAKEN"},
    {"url": "https://raw.githubusercontent.com/harbor-framework/harbor/main/src/harbor/models/trajectories/step.py", "opened": False, "opened_by": "B7 (and B5b for the ATIF validator)", "used_for": "schema TAKEN / join validation PARTIAL"},
    {"url": "arXiv 2510.24702 (Agent Data Protocol)", "opened": False, "opened_by": "B7 via alphaXiv", "used_for": "pooled dataset PARTIAL; coverage table NOVEL as far as searched"},
    {"url": "https://github.com/uw-syfi/TraceLab (release v0.0.2, LICENSE-DATASET.md @11b8b14c)", "opened": False, "opened_by": "B5e (asset sha256 matched GitHub digest)", "used_for": "TraceLab licence and provenance"},
]

INTERPRETATION = {
    "label": "INTERPRETATION (reasoning, not measurement). Numbers it relies on are in the sections above or in the cited sibling files.",
    "request_id_headline": "The request-id mechanism still runs on one harness/provider pair (Claude Code -> Anthropic). B5 added "
                           "public corpora and independent operators (TB2 WozCode, Trace Commons donors, 10 HF uploaders) but "
                           "no second harness or provider with request ids. Cross-harness transfer of the bracket cannot be shown "
                           "with held data; the nearest substitutes are 1 s response-id clocks (OpenAI resp_, Muse Spark, Gemini).",
    "B6_after_B5e": "B6 made P1/P2 wait on B5e's audit of public raw Claude Code JSONL. That audit is in: public files do keep "
                    "requestId (registry: cli-trace-commons, cli-claude-code-hf). So generating a corpus for request-id COVERAGE "
                    "is unnecessary. What generation would still add is a documented server clock (HTTP Date) and a wire clock "
                    "outside the agent process (B6 P0), and possibly a non-Anthropic first-party request id. B6's blocking "
                    "decisions H1-H3 are unchanged.",
    "B7_after_B5": "B7's licence matrix covered only the B4 corpora and concluded that only SWE-chat data is cleanly "
                   "redistributable. The 14 acquired corpora declare permissive or attribution licences on their cards "
                   "(MIT, Apache-2.0, CC BY 4.0, CC0, BSD-3-Clause; one AGPL-3.0 repo), so a data release is no longer "
                   "SWE-chat-only in principle, but none has had B7's per-corpus pass (contents licences, secrets, personal "
                   "data). Known hazards: TB2 upstream OAuth tokens (B5b), openhands-feedback real-user content (B5a), "
                   "usernames in Pi folder names, AGPL member in cli-claude-code-hf.",
}


def main():
    I = {k: load(k) for k in INPUTS}
    out = {
        "key": "corpus_inventory",
        "task": "Phase E Track B: consolidate B4-B7 into analysis/CORPUS_INVENTORY.md and data/README.md acquired rows",
        "produced_by": "analysis/out/phase_e/track_b/corpus_inventory/compose_inventory.py",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {k: {"path": os.path.relpath(p, os.path.dirname(PHASE_E)).replace("\\", "/"), "sha256": sha256(p)} for k, p in INPUTS.items()},
        "scope_note": "Reads Track B evidence JSONs and, read-only, data/acquired (directory metadata; Claude Code JSONL "
                      "request-id/session-id fields only). No swarm data. swechat H split not read (swechat not rescanned).",
    }
    out["disk"] = disk_census()
    out["request_id_scan_new_public_cc"] = cc_reqid_scan()
    out["atif_request_id_scan"] = atif_reqid_scan()
    out["agentcap_join"] = agentcap_join(I["B5e_census"])
    out["registry"] = registry(I)
    out["loaders"] = loaders()
    # consistency: my entry counts vs B5e's census (B5e counted assistant entries carrying req_)
    rs = out["request_id_scan_new_public_cc"]["per_corpus"]
    reg = {r["name"]: r for r in out["registry"]["corpora"]}
    out["consistency_checks"] = {
        "cli-trace-commons_entries_with_req": {"this_scan": rs.get("cli-trace-commons", {}).get("entries_with_req_id"),
                                               "B5e": reg["cli-trace-commons"]["evidence"]["assistant_entries_with_req_B5e"]["value"]},
        "cli-claude-code-hf_entries_with_req": {"this_scan": rs.get("cli-claude-code-hf", {}).get("entries_with_req_id"),
                                                "B5e": reg["cli-claude-code-hf"]["evidence"]["assistant_entries_with_req_B5e"]["value"]},
        "tb2_wozcode_entries_with_req": {"this_scan": rs.get("terminal-bench-2-leaderboard", {}).get("entries_with_req_id"),
                                         "B5b": reg["terminal-bench-2-leaderboard"]["evidence"]["entries_with_requestId"]["value"]},
        "tb2_wozcode_distinct": {"this_scan": rs.get("terminal-bench-2-leaderboard", {}).get("distinct_req_ids"),
                                 "B5b": reg["terminal-bench-2-leaderboard"]["evidence"]["distinct_requestIds"]["value"]},
    }
    out["consistency_checks"]["note"] = (
        "This scan counts entries of ANY type carrying requestId; B5e counted assistant entries only. B5e's own "
        "top_keys.requestId for cli-claude-code-hf is 21,585 (B5e_cli_traces.json corpora_downloaded/2/"
        "aggregate_by_format/claude_code/top_keys/requestId), equal to this scan, so the 8-entry gap is non-assistant "
        "entries carrying a requestId, not a parse difference.")
    sw_distinct = get(I["b4"], "REQUEST_ID_COLUMN_FIRST/per_corpus/swechat/claude_code/distinct_request_ids")
    pcs = out["request_id_scan_new_public_cc"]["per_corpus"]
    b5e_distinct = pcs["cli-trace-commons"]["distinct_req_ids"] + pcs["cli-claude-code-hf"]["distinct_req_ids"]
    b5e_entries = pcs["cli-trace-commons"]["entries_with_req_id"] + pcs["cli-claude-code-hf"]["entries_with_req_id"]
    union_new = out["request_id_scan_new_public_cc"]["union_distinct_req_ids_new_public"]
    out["request_id_totals"] = {
        "swechat_claude_code_distinct_nonH": sw_distinct,
        "swechat_from": "analysis/out/phase_e/track_b/b4.json#REQUEST_ID_COLUMN_FIRST/per_corpus/swechat/claude_code/distinct_request_ids",
        "B5e_corpora_entries_with_req_id": b5e_entries,
        "B5e_corpora_distinct_req_ids": b5e_distinct,
        "new_public_distinct_req_ids_union_incl_tb2": union_new,
        "new_public_vs_swechat_distinct_ratio": round(union_new / sw_distinct, 4),
        "correction_to_B5e_headline": "B5e's headline 'gains 29073 new public Anthropic request ids' counts assistant "
                                      "ENTRIES (Claude Code repeats one requestId on every content block of a response). "
                                      "Distinct ids in the two B5e corpora are B5e_corpora_distinct_req_ids; 2,576 of "
                                      "them are shared by armand0e/claude-fable-5-claude-code and cfahlgren1/Fable-5-traces "
                                      "(repo_pairs_with_any_overlap) and are counted once.",
        "not_checked": "overlap of these ids with swechat (would require opening swechat transcripts incl. the H split) "
                       "or with cc_local (private).",
    }
    # small derived sums used in the inventory table (inputs read by key path)
    tl = "corpora_downloaded/0/schema_note/counts_by_provider/"
    ac = "corpora_downloaded/5/aggregate_by_format/"
    e = I["B5e"]
    out["derived_sums"] = {
        "tracelab_sessions": get(e, tl + "claude/sessions") + get(e, tl + "codex/sessions"),
        "tracelab_tools": get(e, tl + "claude/tools") + get(e, tl + "codex/tools"),
        "agentcap_sessions_opencode_plus_pi": get(e, ac + "opencode/sessions") + get(e, ac + "pi/sessions"),
        "agentcap_tool_calls_opencode_parts_plus_pi_calls": get(e, ac + "opencode/tool_parts") + get(e, ac + "pi/tool_calls"),
        "from": "analysis/out/phase_e/track_b/B5e_cli_traces.json#" + tl + "{claude,codex}/{sessions,tools} and #" + ac + "{opencode,pi}",
        "B5d_priority_A_not_downloaded_MB": {
            "Exgentic": get(I["B5d"], "corpora_recommended_pending_approval/0/MB"),
            "AgentBRANE_v14": get(I["B5d"], "corpora_recommended_pending_approval/1/MB"),
            "MCPHunt": get(I["B5d"], "corpora_recommended_pending_approval/2/MB"),
            "sum_MB": round(sum(get(I["B5d"], f"corpora_recommended_pending_approval/{i}/MB") for i in (0, 1, 2)), 1),
            "from": "analysis/out/phase_e/track_b/B5d_hf_search.json#corpora_recommended_pending_approval/{0,1,2}/MB "
                    "(entries 3, 4, 7, 8 were downloaded, fully or in part, by B5e)",
        },
        "acquired_corpora_bytes_reported_by_B5_tasks": {
            "B5a_downloaded_bytes": get(I["B5a"], "headline/downloaded_bytes"),
            "B5e_downloaded_bytes_total": get(e, "headline/downloaded_bytes_total"),
            "note": "B5b and B5c report sizes per corpus (see their JSONs); on-disk truth is disk.per_dir above.",
        },
    }
    out["sources"] = SOURCES
    out["INTERPRETATION"] = INTERPRETATION
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("wrote", OUT)
    print(json.dumps({"disk_total_GB": out["disk"]["total_GB"], "n_held": out["registry"]["n_corpora_held"],
                      "carriers": out["registry"]["carriers"], "consistency": out["consistency_checks"],
                      "union_ids": out["request_id_scan_new_public_cc"]["union_distinct_req_ids_new_public"],
                      "agentcap": {k: out["agentcap_join"][k] for k in ("capture_rows", "capture_rows_matching_trace_folder")}}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
