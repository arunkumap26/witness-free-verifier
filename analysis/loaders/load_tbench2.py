"""Loader: Terminal-Bench 2.0 leaderboard submissions -> IR caches for corpus `tbench2` (Phase E new corpus).

Run from the worktree root:
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_tbench2             # audit + splits + A cache + calibration
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_tbench2 --split B   # NEXT step only: build cache/tbench2_B.parquet
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_tbench2 --selftest  # A-only test of the split builder
`main()` is idempotent: it recomputes the population audit, the splits (seeded), the A cache and the calibration and
overwrites its own outputs. `--split {B,E}` exists for the next step (after the orchestrator commits the calibration);
it reads the id list from the sample files and never touches H. `--split H` is refused.

SOURCE (read-only): C:/Swarms/data/acquired/terminal-bench-2-leaderboard/hf_repo/submissions/terminal-bench/2.0/
  <submission = agent__model>/<job>/<task>__<trial>/  (HF harborframework/terminal-bench-2-leaderboard @572b2614,
  Apache-2.0 card; analysis/CORPUS_INVENTORY.md section 5.1). The byte-identical early copies under
  terminal-bench-2-leaderboard/submissions/ and everything under hf_repo/.git are never read; no `.cache` directory
  exists under the root (checked by `discover`, which skips any name starting with '.').
  A trial directory holds result.json and, for 25 of the 75 submissions, structured agent logs:
    agent/trajectory.json                                   ATIF (Harbor's Agent Trajectory Interchange Format)
    agent/sessions/projects/<proj>/<uuid>.jsonl             native Claude Code JSONL (main session file)
    agent/sessions/projects/<proj>/<uuid>/subagents/agent-<id>.jsonl   Claude Code subagent transcript
    agent/gemini-cli.trajectory.json                        native Gemini CLI session
    agent/.hookele/traj.jsonl                               native hookele log

SESSION UNIT AND FORMAT CHOICE
  session = one trial directory. session_id = "<submission>/<job>/<trial dir>" (unique; '/' as in aiv_cc).
  stratum = the submission directory name (submitting agent__model), as the task specifies.
  Exactly one log per trial is loaded, by priority: native Claude Code JSONL > native Gemini CLI > hookele > ATIF.
  Two submissions ship both a native log and Harbor's ATIF conversion of the same run (WozCode__Claude-Opus-4.6:
  CC JSONL + ATIF; Gemini_CLI__Gemini-3.1-Pro-Preview: Gemini CLI + ATIF). The native log is loaded and the ATIF copy
  is NOT (it is derived from the native log; loading both would put one run in the corpus twice). Reason for the
  priority: the native Claude Code log is the only place WozCode's Anthropic `requestId` survives, and the native
  Gemini log keeps per-tool-call timestamps that ATIF drops. population.parquet records `also_has_atif`.
  If the chosen native log does not parse, the ATIF copy is used instead (counted: `native_parse_fallback_to_atif`).

FIELD AUDIT (population) and N
  `audit_trial` opens each candidate log once and keeps STRUCTURAL COUNTS ONLY: records (ATIF steps / JSONL lines /
  Gemini messages), tool calls, calls with an id, results, records with a timestamp, parse errors. No text, no
  timestamp value and no statistic of any session is retained (the same kind of population metadata as
  swechat_population.parquet). Apart from it, B/E/H files were touched only by format discovery BEFORE the split was
  drawn: 3 seeded-random files per submission read for key names, value types, enum values (step.source, tool names,
  entry types) and timestamp digit patterns, plus one trial whose content was viewed (VIEWED_BEFORE_SPLIT; it landed
  in H and is listed in the held-out manifest). Every content-level check after the split read A only.
  A trial PASSES when its log parses, it has >= 1 tool call with an id, >= 1 tool result and >= 1 timestamped record.
  N = passing trials. Trials without any structured log (the 50 result.json-only submissions, and hookele trials
  whose job left no traj.jsonl) fail with reason `no_structured_log`. Failures by reason and submission are in the
  build report. population table: analysis/cache/tbench2_population.parquet (all candidate trials, with audit_pass).
  length (for the length terciles) = number of tool calls in the log (structural count). Tool calls rather than
  records, because records are not comparable across the four formats (a CC JSONL line is one content block, an ATIF
  step can hold many keystroke calls).

SPLITS (prereg_e.json splits.new_corpora; seed prereg_e_common.SEED_NEW_CORPUS = 20261006)
  A = min(200, floor(0.2 N)); R = N - A; B = min(2000, floor(R/3)); E = min(2000, floor(R/3)); H = remainder.
  Cells = lib/sample cells (stratum x length tercile; terciles from rank(method='first', pct=True) over the whole
  population table sorted by session_id). One permutation (default_rng(SEED_NEW_CORPUS)); A, then B, then E are taken
  in permutation order per cell with lib/sample._alloc (proportional, largest remainder); H = everything left.
  FLOOR DEVIATION: lib/sample floors each cell at 5. tbench2 has 25 strata x 3 terciles = 75 cells, and 75 x 5 = 375
  exceeds A = 200; lib/sample._alloc would then return 375 sessions (the floors are not capped). The size rule is kept
  exact and the floor for a draw is min(5, floor(n_draw / n_cells)): 2 for A, 5 for B and E. Recorded in the sample
  file (`floor_used`) and in the build report as a deviation for the change_log.
  Writes analysis/cache/samples/tbench2.json (A, B, allocation, population by cell), tbench2_EH.json (E, H),
  analysis/cache/tbench2_split_index.parquet (A/B/E ids -> stratum, format, relative log paths; H is not indexed),
  analysis/out/phase_e/heldout_manifest_tbench2.json (n_H and sha256 of the newline-joined sorted H ids).

ENTRY -> IR MAPPING (corpus 'tbench2'; every mapping below is applied to A only in this step)
  ATIF (analysis.loaders.load_tbench2.parse_atif, shared with load_glm_tb21):
    step.source user -> user, system -> system, agent -> assistant (step.message, when non-empty)
    step.reasoning_content -> not emitted; its length goes to extra.thinking_chars of the step's first assistant/call event
    step.tool_calls[] -> call: call_id = tool_call_id, tool_raw = function_name, tool = normalize_tool + TOOL_FOLD,
      args = arguments (JSON), command = arguments.command|cmd (shell tools) or arguments.keystrokes (Terminus
      `bash_command`: tmux keystrokes; tool name kept as `bash_command`, not folded into shell, because keystrokes can
      be control keys or input to a running program, and the model chooses the wait `duration`).
    step.observation.results[] -> result: text = content (a list content is joined like lib/cc_jsonl._text_of).
      An observation in a step WITHOUT tool calls is harness feedback, not a tool result (on A: Terminus 'Previous
      response had parsing errors', idle 'New Terminal Output', Wecode subagent-evidence notes) -> kind 'system' with
      extra.atif_observation = True and extra.join = 'no_call_in_step'.
      call_id join, extra.join:
        'source_call_id'  result carries source_call_id (Harbor validates it is a call of the same step)
        'step_single'     no source_call_id, and the step has exactly one call and one result -> that call
        'step_multi'      no source_call_id and the step has >1 calls (Terminus keystroke batches) -> call_id None,
                          extra.step_call_ids = the step's call ids (no per-call join, CORPUS_INVENTORY 5.1)
        'no_call_in_step' emitted as system (above)
      subagent_trajectory_ref -> extra.subagent_refs = [session_id] (trajectory paths dropped).
      result extra.exit_code (NexAU) -> exit_code; extra.duration_ms -> extra; step.extra.tool_result_is_error
      (Claude-Code-derived ATIF: JJAgent) -> native_error of the step's results. Otherwise native_error is None.
    step.metrics -> usage on every assistant/call event of the step: prompt_tokens -> usage_in, completion_tokens ->
      usage_out, cached_tokens -> usage_cache_read, metrics.extra.cache_creation_input_tokens -> usage_cache_create.
      api_msg_id = step.extra.response_id when present (Judy, one id per step; kept as written: on A the Judy-Gemini
      values have the Gemini responseId shape and decode to plausible times, the Judy-Claude values are litellm
      'chatcmpl-<uuid>' ids, i.e. operator-minted; see the report's provider_ids_by_stratum), else
      'synthetic:atif:<session_id>:s<step_id>' with extra.synthetic_api_msg_id (one ATIF step = one model response;
      prereg_e_common.response_table groups on api_msg_id). Steps with metrics but no assistant/call event get a meta
      event carrying the usage. metrics.cost_usd and metrics.extra.elapsed_ms (vix) -> extra.
    step.model_name -> model; step.extra.is_sidechain -> is_subagent.
    step.extra: only these keys are copied (ids/enums/timers): cost_time, phase, status, stop_reason, payload_type,
      wecode_thread_id, wecode_lane, wecode_agent_name. `hidden_params` (litellm; may hold api_base or headers),
      `raw_arguments`, `metadata`, `tool_result_metadata`, `cwd` and everything else are DROPPED.
    TIMESTAMPS: one stamp per step. Events of a step that has both calls and results get ts_kind 'shared_turn' (the
      call and its result share the stamp; the Terminus family mints it on the host after the commands ran,
      CORPUS_INVENTORY 5.0 'host_after_exec'); all other step events get 'event'. extra.ts_semantics =
      'host_after_exec' for the Terminus family (submissions Terminus2__*, Terminus-KIRA__*, Meta-Harness__*,
      terminus-2__*, and agent.name terminus-2 / terminus-kira elsewhere) else 'atif_step' (semantics UNVERIFIED).
      Offsets are converted to UTC keeping the source's fractional digits (load_swechat.to_iso). Naive stamps (Judy)
      are ASSUMED UTC (ir.iso appends Z); extra.ts_naive = True on those events. Check on A (build report
      A_checks.naive_ts_inside_agent_execution_pm5s): 1,581/1,581 naive-stamped events fall inside result.json
      agent_execution (UTC 'Z') +- 5 s, consistent with UTC.
      COLLAPSED STAMPS: when a trajectory has >= 3 stamped steps and all its step stamps lie within 1 s
      (COLLAPSED_SPAN_S), the stamps are write-time stamps of the ATIF conversion, not event times: every event of
      that session gets ts None / ts_kind 'none', the raw stamp goes to extra.atif_write_stamp and extra.ts_semantics =
      'write_time_collapsed'. Found on A (A_checks.collapsed_atif_stamps): all 7 Deep-Agents__GPT-5.2-Codex sessions
      (span 0.2-1.3 ms), whose stamps sit 17,999.99 s (5 h) after result.json agent_execution.finished_at (a
      local-time-as-UTC write stamp). The rule is generic (any ATIF document), so B/E get the same treatment without
      being read now.
    ORDER: steps in file order; within a step: message, then calls, then results.
  Native Claude Code JSONL (WozCode, ClaudeCode__GLM-4.7, cchuter): lib/cc_jsonl.Parser (attachments via
    lib/cc_attach). Main file in line order. Subagent files (subagents/agent-<id>.jsonl): every entry gets _nested=True
    (is_subagent, a subagent 'user' text turn -> system with nested_prompt), agent_id = <id>, parent_call_id = the
    main-file call whose tool_result's toolUseResult.agentId == <id> (unresolved counted). One seen-uuid set is shared
    by all files of the session, so a subagent entry already emitted from a main-file agent_progress (CC 2.1.34) is
    not emitted twice. Entry types the Parser skips but that carry a timestamp (queue-operation, agent-setting, ...)
    -> meta with extra {entry_type, operation} (enums only; queued prompt content is not copied).
    MERGE: each file's events keep their order; files are interleaved by a monotone key (running max of the stamps
    within the file), ties broken by file rank (main first) and position, so the main stream is never reordered
    (unlike load_cc_local, which sorts by time). Main files write some stamps out of order (A: 466 entries below the
    running max, almost all `progress` / queue-operation lines in cchuter); they stay in file order and are counted
    (loader counter cc_raw_ts_inversions_main; report adjacent_ts_inversions_in_seq_order).
    requestId -> request_id (Anthropic `req_`; decodable by prereg_e_common.decode_req_ms). toolUseResult.stderr ->
    stderr, is_error -> native_error. Spilled `tool-results/*.txt` files were not downloaded (CORPUS_INVENTORY 5.1):
    the result text is the preview the model saw.
  Native Gemini CLI (both Gemini_CLI submissions): load_swechat.parse_gemini (imported, unchanged; corpus relabelled):
    user -> user, gemini -> assistant + call per toolCalls[] (+ result per toolCalls[] with a `result`, stamped with
    toolCalls[].timestamp); tokens -> usage; message id -> api_msg_id; status error/cancelled -> native_error.
    toolCalls[].timestamp is read as the completion time of the call (as swechat's parse_gemini does): on A
    (A_checks.gemini_cli_*) it is 0.01-350 s after its message stamp (median 0.13 s, n = 491) and the next model event
    follows it by a median 4.4 s (5th pct 1.8 s; one of 488 is -0.13 s), which fits 'tool finished' rather than
    'tool requested'. The call event carries the message stamp.
    Exit codes exist only as 'Exit Code: N' text (ir.error_marker 'gemini_exit_code_nonzero').
  hookele traj.jsonl (`parse_hookele`): start -> user (instruction); llm_call -> meta (request start);
    stream_summary -> meta (extra.response_id, tool_call_count); raw_response -> assistant (content) + call per
    tool_calls[] (call_id, name, arguments JSON string parsed into args), usage from raw_response.usage, api_msg_id =
    the iteration's stream_summary response_id (OpenAI `resp_`; 1 s clock in the id per CORPUS_INVENTORY 1.2; it is a
    response id, NOT a request id, so request_id stays None); tool_execution -> result (call_id, output). The
    run_command output is a JSON string {"output", "metadata": {exit_code, duration_seconds, truncated}}: text keeps
    the whole string (what the harness returned), exit_code = metadata.exit_code, native_error = exit_code != 0,
    extra.duration_seconds / extra.truncated (harness timer). plan_update / plan_only / early_exit /
    chat_only_nudge / skills_classified / anything else -> meta (enums only). ts = `ts` (1 s resolution), 'event'.
  Tool folds (TOOL_FOLD): `execute` (Deep-Agents), `exec` (Simple-Codex) and `run_command` (hookele), all with a
    `command`/`cmd` argument, -> 'shell'. `write_stdin`, `run_shell_command`, `Bash`, `bash`, `exec_command` fold via
    ir.normalize_tool. Everything else keeps ir.normalize_tool's name.
  result.json (every session): one trailing meta event, ts None, extra {entry_type:'trial_result', task_name,
    agent_name, agent_version, model_name, model_provider, started_at, finished_at, phase windows (environment_setup,
    agent_setup, agent_execution, verifier), n_input_tokens, n_cache_tokens, n_output_tokens, cost_usd, n_episodes,
    summarization_count, api_request_times_msec (Terminus harness wall time per LLM request), reward,
    exception_type}. `config` (agent kwargs/env: CLAUDE_CODE_OAUTH_TOKEN values exist in this repo, CORPUS_INVENTORY
    2.4), `trial_uri`, exception messages and every other field are NOT read into the IR.

SECRETS
  Agent env/kwargs/headers are never copied (above). In addition every string that reaches text/args/command/stderr/
  extra passes `redact`: credential-like values (Anthropic sk-ant-, OpenAI sk-/sk-proj-, OpenRouter sk-or-v1-,
  GitHub gh?_, Hugging Face hf_, AWS AKIA, Google AIza, Slack xox?-, 'Bearer <token>') are replaced by
  '[REDACTED:credential]' (the swechat typed-redaction form, so prereg_common.mask_redaction handles it). Byte counts
  of affected fields change; the number of replacements per event is in extra.credential_redactions and per pattern in
  the build report. Values are never printed. Context on A (pattern, field, task; no values): the TB2 task
  `sanitize-git-repo` plants AWS/GitHub/Hugging Face-shaped secrets for the agent to remove, so most hits are task
  fixtures; they are redacted as well, since a fixture cannot be told from a live key. 2 Gemini_CLI results carry a
  Google-API-key-shaped value right after an environment-variable assignment (an env dump; possibly a live key). A
  looser OpenAI rule matched words such as '...task-...' and was tightened before the cache was built (no
  letter/digit before 'sk-', body >= 32 characters).

Outputs of main(): cache/samples/tbench2.json, cache/samples/tbench2_EH.json, cache/tbench2_population.parquet,
  cache/tbench2_split_index.parquet, cache/tbench2_A.parquet, out/phase_e/heldout_manifest_tbench2.json,
  out/phase_e/prereg_e_calibration_tbench2.json, out/phase_e/prereg_e_extensions/tbench2.json,
  out/phase_e/newcorp_build_tbench2.json.
"""
import argparse
import collections
import glob
import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from multiprocessing import Pool

import numpy as np
import pandas as pd

from analysis.lib import cc_jsonl, ir, sample
from analysis.loaders import load_swechat as lsw

CORPUS = "tbench2"
LOADER = "analysis/loaders/load_tbench2.py"
DATA_ROOT = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "acquired", "terminal-bench-2-leaderboard",
                         "hf_repo", "submissions", "terminal-bench", "2.0")
AN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # analysis/
CACHE = os.path.join(AN, "cache")
SAMPLES = os.path.join(CACHE, "samples")
OUT_E = os.path.join(AN, "out", "phase_e")
N_PROC = int(os.environ.get("TBENCH_PROCS", "6"))

A_MAX, A_FRAC, BE_MAX, FLOOR = 200, 0.2, 2000, 5
# Content seen before the split existed (format discovery). Every other pre-split read was structure-only (key names,
# types, enum values such as step.source and tool names, timestamp digit patterns); listed in the held-out manifest.
VIEWED_BEFORE_SPLIT = [{
    "session_id": "Terminus2__Claude-Opus-4.6/2026-02-05__16-08-28/adaptive-rejection-sampler__gmpg6m3",
    "what": "result.json fields (config.agent.kwargs/env not shown) and agent/trajectory.json steps 1-3 with every "
            "string truncated to 160 characters", "when": "format discovery, before draw_splits ran"}]
FORMAT_PRIORITY = ("cc_jsonl", "gemini_cli", "hookele", "atif")
TERMINUS_SUBMISSION = re.compile(r"^(?:Terminus2__|Terminus-KIRA__|Meta-Harness__|terminus-2__)")
TERMINUS_AGENT = {"terminus-2", "terminus_2", "terminus-kira", "terminus"}

# ---------------------------------------------------------------------------------------------- tool name folds
# Command-execution tools with a `command` argument that ir.normalize_tool does not already fold into 'shell'.
TOOL_FOLD = {"execute": "shell", "exec": "shell", "shell_command": "shell", "run_command": "shell"}
COLLAPSED_SPAN_S, COLLAPSED_MIN_STEPS = 1.0, 3  # ATIF stamps written at conversion time (see docstring)

# ---------------------------------------------------------------------------------------------- credentials
CRED_PATTERNS = {
    "anthropic": r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{16,}",
    "openrouter": r"(?<![A-Za-z0-9])sk-or-v1-[A-Za-z0-9]{16,}",
    # body >= 32 and no letter/digit before 'sk-': A showed 'task-...'/'...,sk-xx-...' words matching a looser rule
    "openai": r"(?<![A-Za-z0-9])sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,}",
    "github": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "huggingface": r"\bhf_[A-Za-z0-9]{30,}",
    "aws_akid": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "google_api": r"\bAIza[0-9A-Za-z_\-]{35}",
    "slack": r"\bxox[abprs]-[A-Za-z0-9\-]{10,}",
    "bearer": r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{20,}=*",
}
_CRED = [(k, re.compile(v)) for k, v in CRED_PATTERNS.items()]
RED_MARK = "[REDACTED:credential]"


def redact(s, counter=None):
    """Replace credential-like substrings. Returns (new_string, n_replaced). Never logs the value."""
    if not isinstance(s, str) or not s:
        return s, 0
    n = 0
    for name, rx in _CRED:
        s, k = rx.subn(RED_MARK, s)
        if k:
            n += k
            if counter is not None:
                counter[name] += k
    return s, n


def redact_events(events, counter):
    for e in events:
        tot = 0
        for c in ("text", "args", "command", "stderr", "extra"):
            v = e.get(c)
            if isinstance(v, str):
                v2, k = redact(v, counter)
                if k:
                    e[c] = v2
                    tot += k
        if tot:
            ex = json.loads(e["extra"]) if e.get("extra") else {}
            if not isinstance(ex, dict):
                ex = {"extra_raw": ex}
            ex["credential_redactions"] = tot
            e["extra"] = ir.j(ex)
    return events


# ================================================================================================ discovery + audit
def _is_dir(p):
    return os.path.isdir(p)


def discover(root=DATA_ROOT):
    """Candidate trials: every <submission>/<job>/<trial>/ directory. Names starting with '.' are skipped."""
    out = []
    for sub in sorted(os.listdir(root)):
        ps = os.path.join(root, sub)
        if sub.startswith(".") or not _is_dir(ps):
            continue
        for job in sorted(os.listdir(ps)):
            pj = os.path.join(ps, job)
            if job.startswith(".") or not _is_dir(pj):
                continue
            for trial in sorted(os.listdir(pj)):
                pt = os.path.join(pj, trial)
                if trial.startswith(".") or not _is_dir(pt):
                    continue
                out.append({"session_id": f"{sub}/{job}/{trial}", "submission": sub, "job": job, "trial": trial,
                            "dir": pt})
    return out


def log_files(tdir):
    """{format: [relative paths]} of structured logs in one trial directory (relative to the trial dir)."""
    f = {}
    a = os.path.join(tdir, "agent")
    if not os.path.isdir(a):
        return f
    mains = sorted(glob.glob(os.path.join(a, "sessions", "projects", "*", "*.jsonl")))
    if mains:
        subs = []
        for m in mains:
            subs += sorted(glob.glob(os.path.join(m[:-len(".jsonl")], "subagents", "*.jsonl")))
        f["cc_jsonl"] = [os.path.relpath(p, tdir).replace("\\", "/") for p in mains + subs]
    if os.path.isfile(os.path.join(a, "gemini-cli.trajectory.json")):
        f["gemini_cli"] = ["agent/gemini-cli.trajectory.json"]
    if os.path.isfile(os.path.join(a, ".hookele", "traj.jsonl")):
        f["hookele"] = ["agent/.hookele/traj.jsonl"]
    if os.path.isfile(os.path.join(a, "trajectory.json")):
        f["atif"] = ["agent/trajectory.json"]
    return f


def _read(path):
    with open(path, "rb") as fh:
        b = fh.read()
    try:
        return b.decode("utf-8"), False
    except UnicodeDecodeError:
        return b.decode("utf-8", errors="replace"), True


def _jsonl(text, cnt):
    for line in text.split("\n"):
        if not line.strip():
            continue
        cnt["lines"] += 1
        try:
            yield json.loads(line)
        except ValueError:
            cnt["bad_lines"] += 1


def audit_counts(fmt, tdir, files):
    """Structural counts only (see module docstring). Raises on an unparseable document."""
    c = collections.Counter()
    if fmt == "atif":
        d = json.loads(_read(os.path.join(tdir, files[0]))[0])
        steps = d.get("steps") if isinstance(d, dict) else None
        steps = steps if isinstance(steps, list) else []
        c["records"] = len(steps)
        for s in steps:
            if not isinstance(s, dict):
                continue
            c["ts"] += bool(s.get("timestamp"))
            for tc in s.get("tool_calls") or []:
                c["calls"] += 1
                c["calls_with_id"] += bool(isinstance(tc, dict) and tc.get("tool_call_id"))
            c["results"] += len((s.get("observation") or {}).get("results") or [])
        ag = d.get("agent") if isinstance(d.get("agent"), dict) else {}
        return c, {"agent_name": ag.get("name"), "agent_model": ag.get("model_name"), "schema": d.get("schema_version")}
    if fmt == "cc_jsonl":
        for rel in files:
            for e in _jsonl(_read(os.path.join(tdir, rel))[0], c):
                if not isinstance(e, dict):
                    continue
                c["records"] += 1
                c["ts"] += bool(e.get("timestamp"))
                m = e.get("message")
                if isinstance(m, dict) and isinstance(m.get("content"), list):
                    for b in m["content"]:
                        if isinstance(b, dict) and b.get("type") in ("tool_use", "server_tool_use"):
                            c["calls"] += 1
                            c["calls_with_id"] += bool(b.get("id"))
                        elif isinstance(b, dict) and b.get("type") == "tool_result":
                            c["results"] += 1
        if c["lines"] and c["bad_lines"] == c["lines"]:
            raise ValueError("no decodable line")
        return c, {}
    if fmt == "gemini_cli":
        d = json.loads(_read(os.path.join(tdir, files[0]))[0])
        msgs = d.get("messages") if isinstance(d, dict) and isinstance(d.get("messages"), list) else []
        c["records"] = len(msgs)
        for m in msgs:
            if not isinstance(m, dict):
                continue
            c["ts"] += bool(m.get("timestamp"))
            for tc in m.get("toolCalls") or []:
                c["calls"] += 1
                c["calls_with_id"] += bool(isinstance(tc, dict) and tc.get("id"))
                c["results"] += bool(isinstance(tc, dict) and "result" in tc)
        return c, {}
    if fmt == "hookele":
        for o in _jsonl(_read(os.path.join(tdir, files[0]))[0], c):
            if not isinstance(o, dict):
                continue
            c["records"] += 1
            c["ts"] += bool(o.get("ts"))
            if o.get("type") == "raw_response":
                for tc in o.get("tool_calls") or []:
                    c["calls"] += 1
                    c["calls_with_id"] += bool(isinstance(tc, dict) and tc.get("call_id"))
            elif o.get("type") == "tool_execution":
                c["results"] += 1
        if c["lines"] and c["bad_lines"] == c["lines"]:
            raise ValueError("no decodable line")
        return c, {}
    raise ValueError(fmt)


def audit_trial(t):
    """One population row (structural metadata only)."""
    lf = log_files(t["dir"])
    row = {"session_id": t["session_id"], "stratum": t["submission"], "submission": t["submission"], "job": t["job"],
           "trial": t["trial"], "formats_present": ",".join(k for k in FORMAT_PRIORITY if k in lf),
           "also_has_atif": "atif" in lf and any(k in lf for k in FORMAT_PRIORITY[:3]), "format": None, "files": None,
           "has_result_json": os.path.isfile(os.path.join(t["dir"], "result.json")), "parse_ok": False,
           "native_parse_fallback_to_atif": False, "records": 0, "calls": 0, "calls_with_id": 0, "results": 0,
           "ts_records": 0, "bad_lines": 0, "agent_name": None, "agent_model": None, "schema": None,
           "audit_pass": False, "fail_reason": None}
    if not lf:
        row["fail_reason"] = "no_structured_log"
        return row
    order = [k for k in FORMAT_PRIORITY if k in lf]
    for i, fmt in enumerate(order):
        try:
            c, meta = audit_counts(fmt, t["dir"], lf[fmt])
        except Exception as ex:  # noqa: BLE001  structural parse failure is an audit outcome
            row["fail_reason"] = f"parse_error:{fmt}:{type(ex).__name__}"
            continue
        row.update({"format": fmt, "files": json.dumps(lf[fmt]), "parse_ok": True, "records": int(c["records"]),
                    "calls": int(c["calls"]), "calls_with_id": int(c["calls_with_id"]), "results": int(c["results"]),
                    "ts_records": int(c["ts"]), "bad_lines": int(c["bad_lines"]), "fail_reason": None,
                    "native_parse_fallback_to_atif": i > 0 and fmt == "atif", **meta})
        break
    if row["parse_ok"]:
        if row["calls_with_id"] < 1:
            row["fail_reason"] = "no_tool_call"
        elif row["results"] < 1:
            row["fail_reason"] = "no_tool_result"
        elif row["ts_records"] < 1:
            row["fail_reason"] = "no_timestamp"
        else:
            row["audit_pass"] = True
    return row


def population(candidates, procs=N_PROC):
    if procs > 1:
        with Pool(procs) as pool:
            rows = pool.map(audit_trial, candidates, chunksize=32)
    else:
        rows = [audit_trial(t) for t in candidates]
    pop = pd.DataFrame(rows).sort_values("session_id").reset_index(drop=True)
    pop["length"] = pop["calls_with_id"].astype(int)
    return pop


# ================================================================================================ splits
def draw_splits(pop_pass, corpus, seed, a_max=A_MAX, a_frac=A_FRAC, be_max=BE_MAX, floor=FLOOR):
    """prereg_e.json splits.new_corpora on the audited population (rows with audit_pass). See module docstring."""
    pop = pop_pass[["session_id", "stratum", "length"]].drop_duplicates("session_id").sort_values("session_id")
    pop = pop.reset_index(drop=True).copy()
    pop["stratum"] = pop["stratum"].fillna("unknown").astype(str)
    q = pop["length"].rank(method="first", pct=True)
    pop["tercile"] = np.where(q <= 1 / 3, "short", np.where(q <= 2 / 3, "mid", "long"))
    pop["cell"] = pop["stratum"] + "|" + pop["tercile"]
    cells_pop = pop.groupby("cell").size().to_dict()
    rng = np.random.default_rng(seed)
    perm = pop.iloc[rng.permutation(len(pop))].reset_index(drop=True)
    N = len(perm)
    n_a = min(a_max, int(math.floor(a_frac * N)))
    R = N - n_a
    n_b = min(be_max, R // 3)
    n_e = min(be_max, R // 3)

    def take(frame, n):
        sizes = frame.groupby("cell").size().to_dict()
        fl = min(floor, n // len(sizes)) if sizes else 0
        alloc = sample._alloc(sizes, n, floor=fl)
        ids = []
        for cell, k in alloc.items():
            ids += frame.loc[frame.cell == cell, "session_id"].head(k).tolist()
        return ids, {k: int(v) for k, v in alloc.items()}, fl

    a_ids, alloc_a, fl_a = take(perm, n_a)
    rest = perm[~perm.session_id.isin(set(a_ids))]
    b_ids, alloc_b, fl_b = take(rest, n_b)
    rest2 = rest[~rest.session_id.isin(set(b_ids))]
    e_ids, alloc_e, fl_e = take(rest2, n_e)
    h_ids = rest2[~rest2.session_id.isin(set(e_ids))].session_id.tolist()
    sets = [set(a_ids), set(b_ids), set(e_ids), set(h_ids)]
    assert len(a_ids) == n_a and len(b_ids) == n_b and len(e_ids) == n_e, (len(a_ids), n_a, len(b_ids), n_b)
    assert sum(len(s) for s in sets) == N and len(set().union(*sets)) == N
    cell_of = dict(zip(pop.session_id, pop.cell))
    alloc_h = dict(collections.Counter(cell_of[s] for s in h_ids))
    base = {"corpus": corpus, "seed": int(seed), "population_sessions": int(N),
            "population_by_cell": {k: int(v) for k, v in cells_pop.items()},
            "rule": "prereg_e.json splits.new_corpora: A=min(200,floor(0.2N)); R=N-A; B=min(2000,floor(R/3)); "
                    "E=min(2000,floor(R/3)); H=remainder; lib/sample cells (stratum x length tercile over the "
                    "population sorted by session_id); one permutation default_rng(seed); A then B then E by "
                    "lib/sample._alloc; floor per draw = min(5, floor(n_draw/n_cells))",
            "floor_used": {"A": int(fl_a), "B": int(fl_b), "E": int(fl_e)}, "n_cells": len(cells_pop),
            "length_definition": "tool calls with an id in the loaded log (structural count from the field audit)"}
    ab = dict(base, A=sorted(a_ids), B=sorted(b_ids), alloc_A=alloc_a, alloc_B=alloc_b)
    eh = dict(base, E=sorted(e_ids), H=sorted(h_ids), alloc_E=alloc_e, alloc_H={k: int(v) for k, v in alloc_h.items()})
    return ab, eh, cell_of


def sha_ids(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


# ================================================================================================ parsing helpers
def _text_of(content):
    return cc_jsonl._text_of(content)


def _ts(s):
    return lsw.to_iso(s) if s not in (None, "") else None


def _is_naive(s):
    return isinstance(s, str) and "T" in s and not s.endswith("Z") and not re.search(r"[+-]\d\d:?\d\d$", s)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class Emitter:
    """Event sink with the IR defaults (mirrors lib/cc_jsonl.Parser._emit)."""

    def __init__(self, corpus, session_id, stratum):
        self.corpus, self.session_id, self.stratum, self.events = corpus, session_id, stratum, []

    def emit(self, kind, ts=None, ts_kind=None, extra=None, **kw):
        t = _ts(ts)
        ev = {"corpus": self.corpus, "session_id": self.session_id, "stratum": self.stratum, "seq": len(self.events),
              "kind": kind, "ts": t, "ts_kind": (ts_kind or "event") if t else "none", "tool": None, "tool_raw": None,
              "call_id": None, "args": None, "command": None, "text": None, "stderr": None, "native_error": None,
              "exit_code": None, "usage_in": None, "usage_out": None, "usage_cache_read": None,
              "usage_cache_create": None, "api_msg_id": None, "request_id": None, "model": None, "is_subagent": False,
              "parent_call_id": None, "agent_id": None, "uuid": None, "parent_uuid": None, "extra": None}
        ev.update(kw)
        if extra:
            extra = {k: v for k, v in extra.items() if v is not None}
            ev["extra"] = ir.j(extra) if extra else None
        self.events.append(ev)
        return ev


def norm_tool(name):
    if name is None:
        return None
    low = str(name).strip().lower()
    return TOOL_FOLD.get(low) or ir.normalize_tool(name)


def shell_cmd(tool, tool_raw, args):
    if not isinstance(args, dict):
        return None
    if tool == "shell":
        v = args.get("command", args.get("cmd"))
        if isinstance(v, list):
            v = [str(x) for x in v]
            return v[-1] if len(v) >= 3 and v[-2] in ("-lc", "-c", "/c") else " ".join(v)
        return v if isinstance(v, str) else None
    if (tool_raw or "").lower() == "bash_command" and isinstance(args.get("keystrokes"), str):
        return args["keystrokes"]
    return None


STEP_EXTRA_KEEP = ("cost_time", "phase", "status", "stop_reason", "payload_type", "wecode_thread_id", "wecode_lane",
                   "wecode_agent_name")


# ================================================================================================ ATIF
def parse_atif(doc, corpus, session_id, stratum, submission, cnt):
    """ATIF document -> IR events (module docstring, 'ATIF')."""
    E = Emitter(corpus, session_id, stratum)
    ag = doc.get("agent") if isinstance(doc.get("agent"), dict) else {}
    terminus = bool(TERMINUS_SUBMISSION.match(submission or "")) or str(ag.get("name") or "").lower() in TERMINUS_AGENT
    sem = "host_after_exec" if terminus else "atif_step"
    steps = doc.get("steps") if isinstance(doc.get("steps"), list) else []
    stamps = [ir.parse_ts(_ts(x.get("timestamp"))) for x in steps if isinstance(x, dict) and x.get("timestamp")]
    stamps = [x for x in stamps if x is not None]
    collapsed = len(stamps) >= COLLAPSED_MIN_STEPS and (max(stamps) - min(stamps)).total_seconds() < COLLAPSED_SPAN_S
    cnt["atif_collapsed_stamp_sessions"] += int(collapsed)
    for st in steps:
        if not isinstance(st, dict):
            cnt["atif_non_dict_step"] += 1
            continue
        sid_ = st.get("step_id")
        src = st.get("source")
        ts = st.get("timestamp")
        raw_stamp = None
        if collapsed:
            raw_stamp, ts = _ts(ts), None
        naive = _is_naive(ts)
        cnt["atif_ts_naive"] += bool(naive)
        calls = [c for c in (st.get("tool_calls") or []) if isinstance(c, dict)]
        obs = (st.get("observation") or {}) if isinstance(st.get("observation"), dict) else {}
        results = [r for r in (obs.get("results") or []) if isinstance(r, dict)]
        shared = bool(calls) and bool(results)
        tsk = "shared_turn" if shared else "event"
        sx = st.get("extra") if isinstance(st.get("extra"), dict) else {}
        is_sub = bool(sx.get("is_sidechain")) if "is_sidechain" in sx else False
        base_extra = {"atif_step_id": sid_, "atif_source": src, "ts_semantics": "write_time_collapsed" if collapsed else sem,
                      "ts_naive": True if naive else None, "atif_write_stamp": raw_stamp}
        for k in STEP_EXTRA_KEEP:
            if k in sx and (isinstance(sx[k], (str, int, float, bool)) or sx[k] is None):
                v = sx[k]
                base_extra[f"step_{k}"] = v if not isinstance(v, str) else v[:200]
        if sx:
            cnt["atif_step_extra_keys_dropped"] += sum(1 for k in sx if k not in STEP_EXTRA_KEEP and k != "is_sidechain")
        m = st.get("metrics") if isinstance(st.get("metrics"), dict) else {}
        mx = m.get("extra") if isinstance(m.get("extra"), dict) else {}
        usage = {}
        if m:
            usage = {"usage_in": _num(m.get("prompt_tokens")), "usage_out": _num(m.get("completion_tokens")),
                     "usage_cache_read": _num(m.get("cached_tokens")),
                     "usage_cache_create": _num(mx.get("cache_creation_input_tokens"))}
        resp_id = sx.get("response_id") if isinstance(sx.get("response_id"), str) and sx.get("response_id") else None
        model = st.get("model_name") or None
        api = None
        if usage and any(v is not None for v in usage.values()):
            api = resp_id or f"synthetic:atif:{session_id}:s{sid_}"
        elif resp_id:
            api = resp_id
        mextra = {"metrics_cost_usd": _num(m.get("cost_usd")), "elapsed_ms": _num(mx.get("elapsed_ms")),
                  "synthetic_api_msg_id": True if (api and api.startswith("synthetic:")) else None}
        think = st.get("reasoning_content")
        thinking = len(think) if isinstance(think, str) else 0
        msg = st.get("message")
        if isinstance(msg, list):
            msg = _text_of(msg)
        emitted_model_event = False
        if src == "agent":
            if isinstance(msg, str) and msg.strip():
                ex = dict(base_extra, **mextra, thinking_chars=thinking or None)
                thinking = 0
                E.emit("assistant", ts, tsk, extra=ex, text=msg, model=model, api_msg_id=api, is_subagent=is_sub,
                       **usage)
                emitted_model_event = True
        elif src in ("user", "system"):
            if isinstance(msg, str) and msg != "":
                E.emit(src, ts, tsk, extra=base_extra, text=msg, is_subagent=is_sub)
        else:
            cnt[f"atif_unknown_source:{src}"] += 1
            if isinstance(msg, str) and msg != "":
                E.emit("meta", ts, tsk, extra=dict(base_extra, unknown_source=str(src)[:40]), text=msg)
        step_call_ids = []
        for c in calls:
            name = c.get("function_name")
            a = c.get("arguments")
            if isinstance(a, str):
                try:
                    a = json.loads(a)
                except ValueError:
                    cnt["atif_args_string_not_json"] += 1
            tool = norm_tool(name)
            cid = c.get("tool_call_id")
            if not cid:
                cnt["atif_call_without_id"] += 1
                cid = f"synthetic:atif:{session_id}:s{sid_}:c{len(step_call_ids)}"
            step_call_ids.append(cid)
            ex = dict(base_extra, **mextra, thinking_chars=thinking or None)
            thinking = 0
            E.emit("call", ts, tsk, extra=ex, tool=tool, tool_raw=name, call_id=cid,
                   args=ir.j(a) if a is not None else None, command=shell_cmd(tool, name, a), model=model,
                   api_msg_id=api, is_subagent=is_sub, **usage)
            emitted_model_event = True
        if usage and not emitted_model_event and any(v is not None for v in usage.values()):
            E.emit("meta", ts, tsk, extra=dict(base_extra, **mextra, entry_type="atif_metrics_only"), model=model,
                   api_msg_id=api, is_subagent=is_sub, **usage)
            cnt["atif_metrics_only_steps"] += 1
        step_err = sx.get("tool_result_is_error") if isinstance(sx.get("tool_result_is_error"), bool) else None
        for r in results:
            scid = r.get("source_call_id")
            if scid:
                join, cid = "source_call_id", scid
                if scid not in step_call_ids:
                    cnt["atif_source_call_id_not_in_step"] += 1
            elif len(calls) == 1 and len(results) == 1:
                join, cid = "step_single", step_call_ids[0]
            elif calls:
                join, cid = "step_multi", None
            else:
                join, cid = "no_call_in_step", None
            cnt[f"atif_join:{join}"] += 1
            content = r.get("content")
            text = content if isinstance(content, str) else (_text_of(content) if content is not None else None)
            rx = r.get("extra") if isinstance(r.get("extra"), dict) else {}
            refs = r.get("subagent_trajectory_ref")
            ref_ids = [x.get("session_id") for x in refs if isinstance(x, dict)] if isinstance(refs, list) else None
            ex = dict(base_extra, join=join, step_call_ids=step_call_ids if join == "step_multi" else None,
                      n_calls_in_step=len(calls), duration_ms=_num(rx.get("duration_ms")), subagent_refs=ref_ids or None,
                      marker=ir.error_marker(text))
            ec = rx.get("exit_code")
            ec = int(ec) if isinstance(ec, (int, float)) and not isinstance(ec, bool) else None
            tool_raw = None
            if cid:
                for c in calls:
                    if c.get("tool_call_id") == cid:
                        tool_raw = c.get("function_name")
            if join == "no_call_in_step":  # harness feedback (parse errors, idle pane output): not a tool result
                E.emit("system", ts, tsk, extra=dict(ex, atif_observation=True), text=text, is_subagent=is_sub)
                continue
            E.emit("result", ts, tsk, extra=ex, tool=norm_tool(tool_raw), tool_raw=tool_raw, call_id=cid, text=text,
                   native_error=step_err, exit_code=ec, is_subagent=is_sub)
    return E.events


# ================================================================================================ Claude Code JSONL
CC_PARSER_TYPES = {"progress", "assistant", "user", "system", "attachment", "result"}


def _agent_of_subfile(rel):
    b = os.path.basename(rel)
    return b[len("agent-"):-len(".jsonl")] if b.startswith("agent-") and b.endswith(".jsonl") else None


def parse_cc(tdir, files, corpus, session_id, stratum, cnt):
    mains = [f for f in files if "/subagents/" not in f]
    subs = [f for f in files if "/subagents/" in f]
    seen = set()
    streams = []
    agent_parent = {}
    for rank, rel in enumerate(mains + subs):
        text, rep = _read(os.path.join(tdir, rel))
        cnt["cc_utf8_replaced_files"] += int(rep)
        p = cc_jsonl.Parser(corpus, session_id, stratum)
        p.seen_uuid = seen
        nested = rel in subs
        aid = _agent_of_subfile(rel) if nested else None
        for e in _jsonl(text, cnt):
            if not isinstance(e, dict):
                cnt["cc_non_object_lines"] += 1
                continue
            if not nested and e.get("type") == "user":
                tur = e.get("toolUseResult")
                msg = e.get("message") if isinstance(e.get("message"), dict) else {}
                if isinstance(tur, dict) and tur.get("agentId") and isinstance(msg.get("content"), list):
                    for b in msg["content"]:
                        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                            agent_parent.setdefault(str(tur["agentId"]), b["tool_use_id"])
            if nested:
                e = dict(e)
                e["_nested"] = True
                e["_agent_id"] = aid
            t = e.get("type")
            if t in CC_PARSER_TYPES:
                p.feed(e)
            elif e.get("timestamp"):
                uid = e.get("uuid")
                if uid and uid in seen:
                    continue
                if uid:
                    seen.add(uid)
                keep = {"entry_type": t}
                if isinstance(e.get("operation"), str):
                    keep["operation"] = e["operation"][:40]
                p._emit(e, e.get("timestamp"), kind="meta", extra=ir.j(keep))
                cnt[f"cc_meta_entry:{t}"] += 1
            else:
                cnt[f"cc_dropped_untimed:{t}"] += 1
        evs = p.events
        if nested:
            for ev in evs:
                ev["agent_id"] = ev["agent_id"] or aid
        streams.append((rank, rel, nested, aid, evs))
    # resolve subagent parent call ids
    for rank, rel, nested, aid, evs in streams:
        if nested:
            par = agent_parent.get(aid)
            cnt["cc_subagent_files"] += 1
            cnt["cc_subagent_files_parent_resolved"] += int(par is not None)
            for ev in evs:
                if ev["parent_call_id"] is None:
                    ev["parent_call_id"] = par
    # merge: monotone key per stream (running max of ts), then (key, rank, position)
    keyed = []
    for rank, rel, nested, aid, evs in streams:
        run = None
        inv = 0
        for i, ev in enumerate(evs):
            dt = ir.parse_ts(ev["ts"]) if ev["ts"] else None
            if dt is not None:
                if run is not None and dt < run:
                    inv += 1
                run = dt if run is None or dt > run else run
            key = run if run is not None else datetime(1970, 1, 1, tzinfo=timezone.utc)
            keyed.append((key, rank, i, ev))
        cnt["cc_raw_ts_inversions_" + ("subagent" if nested else "main")] += inv
    keyed.sort(key=lambda x: (x[0], x[1], x[2]))
    out = [k[3] for k in keyed]
    for ev in out:
        if ev.get("is_subagent") is None:
            ev["is_subagent"] = False
    return out


# ================================================================================================ Gemini CLI
def parse_gemini_cli(tdir, files, corpus, session_id, stratum, cnt):
    text, rep = _read(os.path.join(tdir, files[0]))
    stat = collections.defaultdict(int)
    evs = lsw.parse_gemini(session_id, stratum, text, stat, None)
    for k, v in stat.items():
        if isinstance(v, (int, float)):
            cnt[f"gemini_{k}"] += v
    for e in evs:
        e["corpus"] = corpus
    lsw.ensure_usage_ids(evs, "gemini", session_id, stat)
    return evs


# ================================================================================================ hookele
def parse_hookele(tdir, files, corpus, session_id, stratum, cnt):
    text, rep = _read(os.path.join(tdir, files[0]))
    E = Emitter(corpus, session_id, stratum)
    resp_of_iter = {}
    tool_of_call = {}
    for o in _jsonl(text, cnt):
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        ts = o.get("ts")
        it = o.get("iteration")
        cnt[f"hookele_type:{t}"] += 1
        if t == "start":
            E.emit("user", ts, text=o.get("instruction") if isinstance(o.get("instruction"), str) else None,
                   model=o.get("model"), extra={"entry_type": "start", "hookele_version": o.get("hookele_version"),
                                                "reasoning_effort": o.get("reasoning_effort")})
        elif t == "llm_call":
            E.emit("meta", ts, model=o.get("model"), extra={"entry_type": "llm_call", "iteration": it})
        elif t == "stream_summary":
            rid = o.get("response_id") if isinstance(o.get("response_id"), str) else None
            if rid:
                resp_of_iter[it] = rid
            u = o.get("usage") if isinstance(o.get("usage"), dict) else {}
            E.emit("meta", ts, api_msg_id=rid, extra={"entry_type": "stream_summary", "iteration": it,
                                                      "response_id": rid, "tool_call_count": o.get("tool_call_count"),
                                                      "reasoning_tokens": _num(u.get("reasoning_tokens"))})
        elif t == "raw_response":
            u = o.get("usage") if isinstance(o.get("usage"), dict) else {}
            usage = {"usage_in": _num(u.get("input_tokens")), "usage_out": _num(u.get("output_tokens")),
                     "usage_cache_read": _num(u.get("cached_tokens"))}
            api = resp_of_iter.get(it)
            if api is None:
                api = f"synthetic:hookele:{session_id}:i{it}"
                cnt["hookele_raw_response_without_summary_id"] += 1
            base = {"iteration": it, "reasoning_tokens": _num(u.get("reasoning_tokens")),
                    "synthetic_api_msg_id": True if api.startswith("synthetic:") else None}
            content = o.get("content")
            if isinstance(content, str) and content.strip():
                E.emit("assistant", ts, text=content, api_msg_id=api, extra=base, **usage)
            btc = o.get("builtin_tool_calls")
            if isinstance(btc, list) and btc:
                cnt["hookele_builtin_tool_calls"] += len(btc)
            for tc in o.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                a = tc.get("arguments")
                if isinstance(a, str):
                    try:
                        a = json.loads(a)
                    except ValueError:
                        cnt["hookele_args_not_json"] += 1
                name = tc.get("name")
                tool = norm_tool(name)
                cid = tc.get("call_id")
                tool_of_call[cid] = name
                E.emit("call", ts, tool=tool, tool_raw=name, call_id=cid, args=ir.j(a) if a is not None else None,
                       command=shell_cmd(tool, name, a if isinstance(a, dict) else None), api_msg_id=api, extra=base,
                       **usage)
        elif t == "tool_execution":
            name = o.get("name") or tool_of_call.get(o.get("call_id"))
            out = o.get("output")
            text_ = out if isinstance(out, str) else (ir.j(out) if out is not None else None)
            md = {}
            if isinstance(text_, str) and text_.startswith("{"):
                try:
                    oo = json.loads(text_)
                    md = oo.get("metadata") if isinstance(oo, dict) and isinstance(oo.get("metadata"), dict) else {}
                except ValueError:
                    md = {}
            ec = md.get("exit_code")
            ec = int(ec) if isinstance(ec, (int, float)) and not isinstance(ec, bool) else None
            cnt["hookele_result_metadata_exit_code"] += int(ec is not None)
            E.emit("result", ts, tool=norm_tool(name), tool_raw=name, call_id=o.get("call_id"), text=text_,
                   exit_code=ec, native_error=(ec != 0) if ec is not None else None,
                   extra={"entry_type": "tool_execution", "iteration": it, "marker": ir.error_marker(text_),
                          "duration_seconds": _num(md.get("duration_seconds")),
                          "truncated": md.get("truncated") if isinstance(md.get("truncated"), bool) else None})
        else:
            E.emit("meta", ts, extra={"entry_type": str(t)[:40], "iteration": it,
                                      "reason": o.get("reason")[:80] if isinstance(o.get("reason"), str) else None})
    return E.events


# ================================================================================================ result.json
WINDOWS = ("environment_setup", "agent_setup", "agent_execution", "verifier")


def trial_result_extra(path, cnt):
    """Whitelisted trial-level fields of result.json (module docstring). `config` is never read into the IR."""
    if not os.path.isfile(path):
        cnt["result_json_missing"] += 1
        return None
    try:
        d = json.loads(_read(path)[0])
    except ValueError:
        cnt["result_json_unparseable"] += 1
        return None
    ex = {"entry_type": "trial_result", "task_name": d.get("task_name"), "started_at": _ts(d.get("started_at")),
          "finished_at": _ts(d.get("finished_at"))}
    ai = d.get("agent_info") if isinstance(d.get("agent_info"), dict) else {}
    mi = ai.get("model_info") if isinstance(ai.get("model_info"), dict) else {}
    ex.update({"agent_name": ai.get("name"), "agent_version": ai.get("version"), "model_name": mi.get("name"),
               "model_provider": mi.get("provider")})
    for w in WINDOWS:
        x = d.get(w)
        if isinstance(x, dict):
            ex[f"{w}_started_at"] = _ts(x.get("started_at"))
            ex[f"{w}_finished_at"] = _ts(x.get("finished_at"))
    ar = d.get("agent_result") if isinstance(d.get("agent_result"), dict) else {}
    for k in ("n_input_tokens", "n_cache_tokens", "n_output_tokens", "cost_usd"):
        ex[k] = _num(ar.get(k))
    md = ar.get("metadata") if isinstance(ar.get("metadata"), dict) else {}
    ex["n_episodes"] = _num(md.get("n_episodes"))
    ex["summarization_count"] = _num(md.get("summarization_count"))
    rt = md.get("api_request_times_msec")
    if isinstance(rt, list):
        ex["api_request_times_msec"] = [float(x) for x in rt if _num(x) is not None]
    vr = d.get("verifier_result") if isinstance(d.get("verifier_result"), dict) else {}
    rw = vr.get("rewards") if isinstance(vr.get("rewards"), dict) else {}
    ex["reward"] = _num(rw.get("reward"))
    ei = d.get("exception_info")
    if isinstance(ei, dict):
        ex["exception_type"] = str(ei.get("exception_type"))[:80] if ei.get("exception_type") else "unknown"
    return {k: v for k, v in ex.items() if v is not None}


# ================================================================================================ one session
def parse_session(row, data_root=DATA_ROOT, corpus=CORPUS):
    """IR events for one population row (row: dict with session_id, stratum, submission, job, trial, format, files)."""
    cnt = collections.Counter()
    tdir = os.path.join(data_root, row["submission"], row["job"], row["trial"]) if row.get("submission") else \
        os.path.join(data_root, row["trial"])
    files = json.loads(row["files"])
    fmt = row["format"]
    sid, st = row["session_id"], row["stratum"]
    if fmt == "atif":
        doc = json.loads(_read(os.path.join(tdir, files[0]))[0])
        evs = parse_atif(doc, corpus, sid, st, row.get("submission"), cnt)
    elif fmt == "cc_jsonl":
        evs = parse_cc(tdir, files, corpus, sid, st, cnt)
    elif fmt == "gemini_cli":
        evs = parse_gemini_cli(tdir, files, corpus, sid, st, cnt)
    elif fmt == "hookele":
        evs = parse_hookele(tdir, files, corpus, sid, st, cnt)
    else:
        raise ValueError(fmt)
    tr = trial_result_extra(os.path.join(tdir, "result.json"), cnt)
    if tr is not None:
        evs.append({"corpus": corpus, "session_id": sid, "stratum": st, "seq": 0, "kind": "meta", "ts": None,
                    "ts_kind": "none", "tool": None, "tool_raw": None, "call_id": None, "args": None, "command": None,
                    "text": None, "stderr": None, "native_error": None, "exit_code": None, "usage_in": None,
                    "usage_out": None, "usage_cache_read": None, "usage_cache_create": None, "api_msg_id": None,
                    "request_id": None, "model": None, "is_subagent": False, "parent_call_id": None, "agent_id": None,
                    "uuid": None, "parent_uuid": None, "extra": ir.j(tr)})
    for i, e in enumerate(evs):
        e["seq"] = i
        e["corpus"] = corpus
        e["session_id"] = sid
        e["stratum"] = st
        if e.get("ts") is None:
            e["ts_kind"] = "none"
        if e.get("is_subagent") is None:
            e["is_subagent"] = False
    cred = collections.Counter()
    redact_events(evs, cred)
    for k, v in cred.items():
        cnt[f"credential_redactions:{k}"] += v
    cnt[f"format:{fmt}"] += 1
    return evs, cnt


def _parse_worker(args):
    row, data_root, corpus = args
    try:
        evs, cnt = parse_session(row, data_root, corpus)
        return row["session_id"], evs, dict(cnt), None
    except Exception as ex:  # noqa: BLE001  recorded per session
        return row["session_id"], [], {}, f"{type(ex).__name__}: {str(ex)[:200]}"


def build_frame(rows, data_root=DATA_ROOT, corpus=CORPUS, procs=N_PROC):
    """Parse the given population rows (dicts). Returns (IR frame, counters, errors)."""
    args = [(r, data_root, corpus) for r in rows]
    if procs > 1 and len(args) > 8:
        with Pool(procs) as pool:
            res = pool.map(_parse_worker, args, chunksize=4)
    else:
        res = [_parse_worker(a) for a in args]
    events, cnt, errs = [], collections.Counter(), {}
    for sid, evs, c, err in sorted(res, key=lambda x: x[0]):
        if err:
            errs[sid] = err
        events += evs
        cnt.update(c)
    df = ir.to_frame(events)
    if len(df):
        cnt["surrogate_fields_sanitized"] += lsw._sanitize_surrogates(df)  # in place (parquet needs valid UTF-8)
    return df, cnt, errs


# ================================================================================================ build steps
def split_paths(corpus):
    return {"ab": os.path.join(SAMPLES, f"{corpus}.json"), "eh": os.path.join(SAMPLES, f"{corpus}_EH.json"),
            "pop": os.path.join(CACHE, f"{corpus}_population.parquet"),
            "index": os.path.join(CACHE, f"{corpus}_split_index.parquet")}


def write_splits(pop, corpus, seed, out_e=OUT_E, loader=LOADER, viewed_before_split=None):
    passed = pop[pop.audit_pass].copy()
    ab, eh, cell_of = draw_splits(passed, corpus, seed)
    P = split_paths(corpus)
    sample.save(ab, P["ab"])
    sample.save(eh, P["eh"])
    pop.to_parquet(P["pop"], index=False)
    lab = {**{s: "A" for s in ab["A"]}, **{s: "B" for s in ab["B"]}, **{s: "E" for s in eh["E"]}}
    idx = passed[passed.session_id.isin(set(lab))][["session_id", "stratum", "submission", "job", "trial", "format",
                                                     "files", "length"]].copy()
    idx.insert(1, "split", idx.session_id.map(lab))
    idx = idx.sort_values(["split", "session_id"]).reset_index(drop=True)
    idx.to_parquet(P["index"], index=False)
    man = {"corpus": corpus, "purpose": "Held-out split H for the Track C eval harness. Never read during tuning or "
                                        "analysis. Separate from analysis/HELDOUT_MANIFEST.json (not edited).",
           "n_H": len(eh["H"]), "n_E": len(eh["E"]), "sha256_sorted_H_ids": sha_ids(eh["H"]),
           "hash_rule": "sha256 of '\\n'.join(sorted(H ids)).encode() (as analysis/probes/phase_e_split.py)",
           "ids_file": f"analysis/cache/samples/{corpus}_EH.json#H", "seed": int(seed), "loader": loader,
           "viewed_before_split": [dict(v, split=("H" if v["session_id"] in set(eh["H"]) else "not H"))
                                   for v in (viewed_before_split or [])]}
    os.makedirs(out_e, exist_ok=True)
    with open(os.path.join(out_e, f"heldout_manifest_{corpus}.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    return ab, eh, idx, man


def ids_for_split(corpus, split):
    """A/B from <corpus>.json, E from <corpus>_EH.json key 'E'. H is refused."""
    assert split in ("A", "B", "E"), f"split {split!r} may not be built"
    P = split_paths(corpus)
    if split in ("A", "B"):
        return json.load(open(P["ab"], encoding="utf-8"))[split]
    eh = json.load(open(P["eh"], encoding="utf-8"))
    ids = list(eh["E"])
    del eh
    return ids


def build_split_cache(corpus, split, ids, out_path, data_root=DATA_ROOT, procs=N_PROC):
    """Parse the sessions `ids` (looked up in the split index, never H) and write an IR cache to out_path."""
    assert split in ("A", "B", "E")
    idx = pd.read_parquet(split_paths(corpus)["index"])
    rows = idx[idx.session_id.isin(set(ids))]
    assert len(rows) == len(set(ids)), "ids missing from the split index"
    assert set(rows.split) == {split}, f"index split labels {set(rows.split)} != {split}"
    df, cnt, errs = build_frame(rows.to_dict("records"), data_root, corpus, procs)
    basic = ir.validate(df)
    df.to_parquet(out_path, index=False)
    return df, cnt, errs, basic


def selftest(corpus=CORPUS, data_root=DATA_ROOT, scratch=None):  # noqa: D401
    """A-only test of the --split code path: rebuild A through build_split_cache into a scratch file and compare."""
    scratch = scratch or os.path.join(os.environ.get("TEMP", "."), f"{corpus}_A_selftest.parquet")
    ids = ids_for_split(corpus, "A")
    df, cnt, errs, basic = build_split_cache(corpus, "A", ids, scratch, data_root, procs=1)
    ref = pd.read_parquet(os.path.join(CACHE, f"{corpus}_A.parquet"))
    same = df.reset_index(drop=True).equals(ref.reset_index(drop=True))
    try:
        ids_for_split(corpus, "H")
        refused = False
    except AssertionError:
        refused = True
    os.remove(scratch)
    return {"rebuilt_A_equals_cache": bool(same), "H_refused": refused, "rows": int(len(df)), "errors": len(errs)}


# ================================================================================================ report helpers
# id families for the provider-id fill report (layouts inferred from data in Phase C / B5b, UNVERIFIED by vendors)
_ID_FAMILIES = [
    ("anthropic_req", re.compile(r"^req_(?:vrtx_|bdrk_)?01[1-9A-HJ-NP-Za-km-z]{22}$"), True),
    ("anthropic_msg", re.compile(r"^msg_(?:vrtx_|bdrk_)?01[1-9A-HJ-NP-Za-km-z]{22}$"), True),
    ("openai_resp_hex50", re.compile(r"^resp_[0-9a-f]{50}$"), True),
    ("gemini_response_id_b64", re.compile(r"^[A-Za-z0-9_-]{16,24}$"), True),
    ("chatcmpl_operator", re.compile(r"^chatcmpl-"), False),
    ("uuid", re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"), False),
    ("synthetic", re.compile(r"^synthetic:"), False),
]


def id_family(v):
    for name, rx, _ in _ID_FAMILIES:
        if rx.match(v):
            return name
    return "other"


def id_embedded_ms(fam, v):
    """Embedded time (ms) when the id decodes to a time inside [2024-01-01, 2027-01-01), else None."""
    from analysis.probes import prereg_e_common as pe
    lo, hi = pe._WIN
    t = None
    if fam in ("anthropic_req", "anthropic_msg"):
        x = 0
        for ch in v.rsplit("_", 1)[1][2:]:
            x = x * 58 + pe._B58I[ch]
        t = float(x >> 80)
    elif fam == "openai_resp_hex50":
        b = v.split("_", 1)[1]
        t = float(int(b[18:26], 16)) * 1000.0 if b[16:18] == "00" else None
    elif fam == "gemini_response_id_b64":
        import base64
        try:
            b = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))
            t = float(int.from_bytes(b[:4], "little")) * 1000.0 if len(b) >= 4 else None
        except ValueError:
            t = None
    elif fam == "uuid" and v[14] == "7":
        t = float(int(v.replace("-", "")[:12], 16))
    return t if t is not None and lo <= t < hi else None


def provider_ids(df):
    """Per stratum: distinct request_id / api_msg_id values on call+assistant events by family, and how many decode to
    a plausible embedded time. Counts only (no agreement statistic)."""
    m = df[df.kind.isin(["call", "assistant"])]
    out = {}
    for col in ("request_id", "api_msg_id"):
        per = {}
        for st, g in m[m[col].notna()].groupby("stratum"):
            vals = g[col].astype(str).unique()
            fam = collections.Counter()
            dec = collections.Counter()
            for v in vals:
                f = id_family(v)
                fam[f] += 1
                dec[f] += int(id_embedded_ms(f, v) is not None)
            per[str(st)] = {f: {"distinct": int(n), "decodes_to_plausible_time": int(dec[f])} for f, n in fam.items()}
        out[col] = per
    out["provider_minted_families"] = [n for n, _, prov in _ID_FAMILIES if prov]
    out["note"] = ("family by shape only; gemini_response_id_b64 is the aiv_cu Gemini responseId shape (first 4 bytes LE "
                   "= unix s); chatcmpl- and uuid ids are operator/harness-minted; layouts inferred, not documented")
    return out


def frame_report(df):
    from analysis.loaders.cc_build_stats import build_stats
    from analysis.probes import prereg_e_common as pe
    rep = build_stats(df)
    calls = df[df.kind == "call"]
    res = df[df.kind == "result"]
    rep["events_by_kind_and_ts_kind"] = {f"{k}|{t}": int(v) for (k, t), v in
                                         df.groupby(["kind", "ts_kind"]).size().items()}
    rid = df.request_id.dropna().astype(str)
    uniq = rid.unique()
    dec = [x for x in uniq if pe.decode_req_ms(x) is not None]
    rep["request_id"] = {"events_with_request_id": int(len(rid)), "distinct": int(len(uniq)),
                         "distinct_decodable_anthropic_layout": int(len(dec)),
                         "calls_with_request_id": int(calls.request_id.notna().sum()), "calls": int(len(calls)),
                         "call_fill_rate": float(calls.request_id.notna().mean()) if len(calls) else None,
                         "sessions_with_request_id": int(df[df.request_id.notna()].session_id.nunique()),
                         "by_stratum_calls_with_request_id": {str(k): int(v) for k, v in
                                                              calls[calls.request_id.notna()].groupby("stratum").size().items()}}
    api = calls.api_msg_id.dropna().astype(str)
    rep["provider_response_ids_on_calls"] = {
        "anthropic_msg_": int(api.str.startswith("msg_").sum()), "openai_resp_": int(api.str.startswith("resp_").sum()),
        "chatcmpl_": int(api.str.startswith("chatcmpl").sum()), "synthetic": int(api.str.startswith("synthetic:").sum()),
        "other": int((~api.str.match(r"^(?:msg_|resp_|chatcmpl|synthetic:)")).sum())}
    rep["native_error_by_stratum"] = {str(k): {"results": int(len(g)), "filled": int(g.native_error.notna().sum()),
                                               "true": int((g.native_error == True).sum())}  # noqa: E712
                                      for k, g in res.groupby("stratum")}
    um = {}
    for k, g in calls.groupby("stratum"):
        um[str(k)] = {"calls": int(len(g)), "usage_in": float(g.usage_in.notna().mean()),
                      "usage_out": float(g.usage_out.notna().mean()), "api_msg_id": float(g.api_msg_id.notna().mean())}
    rep["usage_fill_calls_by_stratum"] = um
    tsn = df[df.ts.notna()]
    rep["ts_fractional_digits_by_stratum"] = {
        str(k): {str(d): int(n) for d, n in sorted(collections.Counter(ir.frac_digits(s) for s in g.ts).items())}
        for k, g in tsn.groupby("stratum")}
    ex = [json.loads(e) if isinstance(e, str) else {} for e in res.extra.astype(object)]
    rep["result_join"] = dict(collections.Counter(x.get("join", "native_id") for x in ex))
    rep["provider_ids_by_stratum"] = provider_ids(df)
    rep["note_duplicate_result_events"] = ("pairing.duplicate_result_events_same_session_id counts results with a null "
                                           "call_id (step_multi) as duplicates of each other; non-null duplicates = "
                                           f"{int(res[res.call_id.notna()].duplicated(['session_id', 'call_id']).sum())}")
    return rep


def _q(v, qs=(0.0, 0.05, 0.5, 0.95, 1.0)):
    v = np.asarray([x for x in v if x is not None and np.isfinite(x)], dtype=float)
    return {"n": int(len(v)), **({f"q{q:g}": float(np.quantile(v, q)) for q in qs} if len(v) else {})}


def a_checks(df):
    """Parser checks on the A cache that the docstring cites (counts and quantiles; A only)."""
    ex = [json.loads(e) if isinstance(e, str) else {} for e in df.extra.astype(object)]
    tr = {s: x for s, x in zip(df.session_id, ex) if x.get("entry_type") == "trial_result"}
    out = {}
    # 1. naive (Judy) stamps vs result.json agent_execution window (UTC 'Z') +- 5 s
    inside = total = 0
    for sid, ts, x in zip(df.session_id, df.ts.astype(object), ex):
        if not x.get("ts_naive") or not isinstance(ts, str):
            continue
        w = tr.get(sid, {})
        lo, hi = ir.parse_ts(w.get("agent_execution_started_at")), ir.parse_ts(w.get("agent_execution_finished_at"))
        if lo is None or hi is None:
            continue
        t = ir.parse_ts(ts)
        total += 1
        inside += int((lo - pd.Timedelta(seconds=5)) <= t <= (hi + pd.Timedelta(seconds=5)))
    out["naive_ts_inside_agent_execution_pm5s"] = {"inside": inside, "events": total}
    # 2. collapsed ATIF stamps: sessions by stratum, span, offset to agent_execution end
    col = collections.defaultdict(list)
    for sid, st, x in zip(df.session_id, df.stratum, ex):
        if x.get("ts_semantics") == "write_time_collapsed" and x.get("atif_write_stamp"):
            col[(sid, st)].append(ir.parse_ts(x["atif_write_stamp"]))
    spans, offs, by = [], [], collections.Counter()
    for (sid, st), v in col.items():
        by[st] += 1
        spans.append((max(v) - min(v)).total_seconds())
        fin = ir.parse_ts(tr.get(sid, {}).get("agent_execution_finished_at"))
        if fin is not None:
            offs.append((min(v) - fin).total_seconds())
    out["collapsed_atif_stamps"] = {"sessions_by_stratum": dict(by), "span_s": _q(spans),
                                    "first_stamp_minus_agent_execution_finished_s": _q(offs)}
    # 3. Gemini CLI: result stamp (toolCalls[].timestamp) vs its call (message stamp) and vs the next model event
    g = df[df.stratum.astype(str).str.startswith("Gemini_CLI")].sort_values(["session_id", "seq"])
    d1, d2 = [], []
    for sid, gg in g.groupby("session_id"):
        cc = gg[gg.kind == "call"]
        call_ts = {c: ir.parse_ts(t) for c, t in zip(cc.call_id.astype(object), cc.ts.astype(object))
                   if isinstance(t, str)}
        rows = list(zip(gg.kind, gg.ts.astype(object), gg.call_id.astype(object),
                        [a if isinstance(a, str) else None for a in gg.api_msg_id.astype(object)]))
        for i, (k, t, c, a) in enumerate(rows):
            if k != "result" or not isinstance(t, str) or c not in call_ts:
                continue
            rt = ir.parse_ts(t)
            d1.append((rt - call_ts[c]).total_seconds())
            nxt = next((ir.parse_ts(t2) for k2, t2, c2, a2 in rows[i + 1:] if k2 in ("assistant", "call")
                        and isinstance(t2, str) and a2 != a), None)
            if nxt is not None:
                d2.append((nxt - rt).total_seconds())
    out["gemini_cli_result_minus_call_s"] = _q(d1)
    out["gemini_cli_next_model_event_minus_result_s"] = _q(d2)
    return out


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def calibrate(corpus, df_A, out_e=OUT_E, loader=LOADER):
    """prereg_e_calibration.calibrate_unit on A (called, not re-implemented); writes the calibration + extension."""
    from analysis.probes import prereg_e_calibration as pcal_e
    from analysis.probes import prereg_e_common as pe
    from analysis.probes import prereg_common as pc
    frozen = None
    try:
        pe.check_frozen()
        frozen = True
    except AssertionError as ex:
        frozen = f"FAILED: {ex}"
    u_all = df_A[pcal_e.COLS].copy()
    u_all["session_id"] = u_all["session_id"].astype(str)
    units = {}
    for unit, u in pc.unit_frames(corpus, u_all).items():
        u = u.reset_index(drop=True)
        res, R = pcal_e.calibrate_unit(corpus, unit, u)
        units[unit] = res
    cal = {"corpus": corpus, "script": loader, "function": "analysis.probes.prereg_e_calibration.calibrate_unit",
           "split": "A only (cache/<corpus>_A.parquet built by the loader; B/E/H never parsed)",
           "check_frozen_prereg_e_common": frozen, "units": _jsonable(units),
           "prereg_rule": "prereg_e.json splits.new_corpora.calibration",
           "note": "calibrate_unit runs the unit-specific blocks only for units registered in prereg_e (N1/latency for "
                   "SPEC_E n1 units, N5 for the seven Phase E units, F3 for probe4 testable units, R2 for aiv_cu, R3 for "
                   "swechat/cc_local/aiv_cc). A new corpus unit gets length terciles, dominance context, the request-id "
                   "bracket baseline (when request ids exist), N2 granularity/tau and the N6 field gate."}
    path = os.path.join(out_e, f"prereg_e_calibration_{corpus}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=1, default=str)
    return cal, path


def write_extension(corpus, cal_path, loader=LOADER, out_e=OUT_E):
    from analysis.probes import prereg_e_common as pe
    P = split_paths(corpus)
    d = os.path.join(out_e, "prereg_e_extensions")
    os.makedirs(d, exist_ok=True)
    ext = {"corpus": corpus, "calibration_file": os.path.relpath(cal_path, os.path.dirname(AN)).replace("\\", "/"),
           "calibration_sha256": pe.sha256_file(cal_path), "splits_sha256": {
               f"analysis/cache/samples/{corpus}.json": pe.sha256_file(P["ab"]),
               f"analysis/cache/samples/{corpus}_EH.json": pe.sha256_file(P["eh"])},
           "heldout_manifest": f"analysis/out/phase_e/heldout_manifest_{corpus}.json",
           "loader": loader, "loader_sha256_lf": pe.sha256_lf(os.path.join(os.path.dirname(AN), loader)),
           "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "status": "calibration written BEFORE any B or E read; orchestrator appends the change_log entry"}
    p = os.path.join(d, f"{corpus}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(ext, f, indent=1)
    return ext


def audit_summary(pop):
    out = {"candidate_trials": int(len(pop)), "passing": int(pop.audit_pass.sum()),
           "fail_reasons": {str(k): int(v) for k, v in pop.fail_reason.dropna().value_counts().items()},
           "fail_by_submission": {}, "pass_by_stratum": {str(k): int(v) for k, v in
                                                         pop[pop.audit_pass].groupby("stratum").size().items()},
           "format_by_stratum": {}, "native_parse_fallback_to_atif": int(pop.native_parse_fallback_to_atif.sum()),
           "also_has_atif_not_loaded": int(pop[pop.audit_pass].also_has_atif.sum()),
           "structural_totals_passing": {k: int(pop[pop.audit_pass][k].sum()) for k in
                                         ("records", "calls", "calls_with_id", "results", "ts_records", "bad_lines")}}
    for (s, r), n in pop[pop.fail_reason.notna()].groupby(["submission", "fail_reason"]).size().items():
        out["fail_by_submission"].setdefault(str(s), {})[str(r)] = int(n)
    for (s, f), n in pop[pop.audit_pass].groupby(["stratum", "format"]).size().items():
        out["format_by_stratum"].setdefault(str(s), {})[str(f)] = int(n)
    out["length_calls_passing"] = {k: float(v) for k, v in pop[pop.audit_pass].length.describe().items()}
    return out


def split_sizes(ab, eh, pop):
    st = dict(zip(pop.session_id, pop.stratum))
    out = {"N": ab["population_sessions"], "A": len(ab["A"]), "B": len(ab["B"]), "E": len(eh["E"]), "H": len(eh["H"]),
           "floor_used": ab["floor_used"], "n_cells": ab["n_cells"], "by_stratum": {}}
    for name, ids in (("A", ab["A"]), ("B", ab["B"]), ("E", eh["E"]), ("H", eh["H"])):
        for s, n in collections.Counter(st[i] for i in ids).items():
            out["by_stratum"].setdefault(s, {})[name] = int(n)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["B", "E"], help="NEXT step only: build cache/<corpus>_<split>.parquet")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    from analysis.probes import prereg_e_common as pe
    if a.split:
        ids = ids_for_split(CORPUS, a.split)
        df, cnt, errs, basic = build_split_cache(CORPUS, a.split, ids, os.path.join(CACHE, f"{CORPUS}_{a.split}.parquet"))
        print(json.dumps({"split": a.split, "sessions": len(ids), "errors": len(errs), **basic}, indent=1))
        return
    if a.selftest:
        print(json.dumps(selftest(), indent=1))
        return
    t0 = time.time()
    cands = discover()
    pop = population(cands)
    ab, eh, idx, man = write_splits(pop, CORPUS, pe.SEED_NEW_CORPUS, viewed_before_split=VIEWED_BEFORE_SPLIT)
    t_audit = time.time() - t0
    print(f"[{t_audit:.0f}s] audit: {len(pop)} candidates, N={ab['population_sessions']} A={len(ab['A'])} "
          f"B={len(ab['B'])} E={len(eh['E'])} H={len(eh['H'])}", flush=True)
    dfA, cnt, errs, basic = build_split_cache(CORPUS, "A", ab["A"], os.path.join(CACHE, f"{CORPUS}_A.parquet"))
    t_a = time.time() - t0
    print(f"[{t_a:.0f}s] A cache: {basic}", flush=True)
    cal, cal_path = calibrate(CORPUS, dfA)
    ext = write_extension(CORPUS, cal_path)
    st = selftest()
    rep = {"corpus": CORPUS, "loader": LOADER, "source": "C:/Swarms/data/acquired/terminal-bench-2-leaderboard/hf_repo "
                                                          "(HF harborframework/terminal-bench-2-leaderboard @572b2614)",
           "population": audit_summary(pop), "splits": split_sizes(ab, eh, pop),
           "heldout_manifest": {"n_H": man["n_H"], "sha256_sorted_H_ids": man["sha256_sorted_H_ids"]},
           "A_cache": {"path": f"analysis/cache/{CORPUS}_A.parquet", "validate": {k: int(v) for k, v in basic.items()},
                       "parse_errors": errs, "loader_counters": dict(sorted(cnt.items())), **frame_report(dfA)},
           "calibration": {"path": os.path.relpath(cal_path, os.path.dirname(AN)).replace("\\", "/"),
                           "sha256": ext["calibration_sha256"]},
           "A_checks": a_checks(dfA), "extension": ext, "selftest_split_builder_on_A": st,
           "runtime_s": {"audit_and_splits": round(t_audit, 1), "A_cache": round(t_a - t_audit, 1),
                         "total": round(time.time() - t0, 1)}}
    with open(os.path.join(OUT_E, f"newcorp_build_{CORPUS}.json"), "w", encoding="utf-8") as f:
        json.dump(_jsonable(rep), f, indent=1, default=str)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
