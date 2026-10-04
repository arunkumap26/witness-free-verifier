"""Loader: data/claude-code-local -> IR caches for corpus `cc_local` (PRIVATE corpus: outputs are aggregates only).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_cc_local
Writes (idempotent, rebuilt from scratch every run):
  analysis/cache/samples/cc_local.json   sample.draw() output (A/B session lists, population by cell)
  analysis/cache/cc_local_A.parquet, analysis/cache/cc_local_B.parquet   IR rows (ir.to_frame + ir.validate)
  analysis/out/build/cc_local_build.json aggregate-only build report

Raw layout (read-only):
  <project_dir>/<session_uuid>.jsonl                                   main session transcript
  <project_dir>/<session_uuid>/subagents/agent-<id>.jsonl (+ .meta.json) Task/Agent subagent transcript
  <project_dir>/<session_uuid>/subagents/workflows/<wf_run>/agent-<id>.jsonl (+ .meta.json)  workflow subagents
  <project_dir>/<session_uuid>/subagents/workflows/<wf_run>/journal.jsonl  workflow journal (no timestamps)
  <project_dir>/<session_uuid>/workflows/<wf_run>.json                 workflow run summary (not JSONL; not loaded)
  <project_dir>/<session_uuid>/tool-results/*.txt                      spilled large tool outputs (not loaded; the
                                                                       transcript keeps the preview the model saw)

SESSION
  Unit file-set = one main file plus every *.jsonl under the directory of the same name (recursively). A
  <session_uuid>/ directory holding JSONL but no main file would form its own file-set (orphan_subagent_dirs in the
  build report; 0 in the current data).
  Resume chains: some main files start with a copy of another main file's history (same entry uuids and timestamps,
  sessionId usually rewritten, cwd/version sometimes rewritten). These are continuations of one conversation in a
  new session file; the members of a chain are mostly sequential in time (the build report counts how often the
  merged main-file stream switches member: fork_families.member_switches). Main files that share any entry uuid are joined
  (union-find) into a FAMILY, and a session = one family (one file-set when nothing is shared). Keeping members
  apart would put the same events, or the same conversation, in two sessions and possibly in both splits A and B,
  and leaves subagent events whose parent Workflow call sits in another member's copy (counted for the rejected
  'keep earliest copy' rule in out/build/cc_local_fork_policy_owner_check.json).
  session_id = uuid of the family root = the member with the earliest timestamp in its main file (ties: uuid).
  stratum = project directory of the root, top 5 by session count + 'other'. Labels are aliases, not directory
  names: 'proj01' = the project dir with the most sessions, ... 'proj05' (ties broken by directory name), so no
  local path leaves the cache. The alias is recomputed deterministically by this loader.
  length (for length terciles) = total raw lines in all JSONL files of the session (copies included).

ENTRY -> IR MAPPING
  Main file entries are fed to analysis.lib.cc_jsonl.Parser (corpus 'cc_local', ts_kind 'event'):
    assistant blocks -> assistant (text) / call (tool_use, server_tool_use); thinking -> extra.thinking_chars
    user entries     -> result (one per tool_result block; toolUseResult timers/stderr into extra/stderr),
                        user (human prompt) or system (isMeta / isSynthetic / harness prefixes)
    system entries   -> meta (subtype, durationMs, compactMetadata in extra)
  User entries whose text starts with <task-notification> (how older Claude Code versions deliver background-task
  notifications; in subagent streams the text starts with a '[SYSTEM NOTIFICATION' header line and contains the
  tag) are system events from the Parser; the loader adds extra.notification_statuses = every
  <status>...</status> value in the text (enum tokens; [] when there is no tag).
  ATTACHMENT entries (type 'attachment', skipped by the Parser) are emitted by this loader, one event each:
    Claude Code >= 2.1.266 (RENDER_MIN_VERSION, lowest version in the data that writes it; the highest version
    without it is 2.1.260) records on the entry a `rendered` list whose items' `content` is the exact text put into
    the model's context (every one starts with <system-reminder>). In those versions every attachment of a
    model-visible type carries `rendered`, and the only attachments without it are the types prompt_snapshot,
    structured_output, deferred_tools_record, credential_org (+1 queued_command). Older versions never write
    `rendered`, so visibility there is decided by type. Rule, per entry (extra.visibility):
      'rendered'                          entry has `rendered`                          -> visible
      'not_rendered_in_rendering_version' version >= 2.1.266 and no `rendered`          -> meta
      'type_rendered_in_newer_versions'   older version, type in ATT_RENDERED_TYPES     -> visible
      'old_only_type_assumed_visible'     older version, type in ATT_OLD_ONLY_VISIBLE   -> visible (types absent
                                          from >= 2.1.266, so unverifiable; judged from their payload: a
                                          model-directed reminder text, a todo reminder, a date-change or budget
                                          notice, the exit counterpart of the rendered ultra_effort_enter)
      'type_never_rendered'               type in ATT_HIDDEN                            -> meta (the four types
                                          above, plus the old-only command_permissions: an allowedTools
                                          permission-state record with no text)
      'unknown_type'                      anything else                                 -> meta (0 in the data)
    Visible attachments -> kind 'system' (harness-injected text the model saw), except queued_command with
    commandMode 'prompt' in a main file (a prompt the human typed while the agent was busy) -> kind 'user'.
    text (extra.text_source):
      'rendered'         the `rendered` items' content joined with newlines (wrapper included).
      'payload:<field>'  no `rendered`: the attachment field that carries the body of the rendering (ATT_PAYLOAD;
                         e.g. total_tokens_reminder.text, queued_command.prompt, edited_text_file.snippet,
                         hook_additional_context.content, file.content.file.content). The build report checks each
                         field against `rendered` where both exist (attachments.payload_field_vs_rendered:
                         contained / all_lines_contained (every non-blank payload line is in the rendering,
                         e.g. list items or line-numbered file text) / not_contained / payload_empty). The
                         payload lacks the <system-reminder> wrapper and header lines, so it is a subset of what
                         the model saw.
      'unavailable'      visible but no text recorded (e.g. task_reminder with an empty item list, auto_mode,
                         ultra_effort_*): text None.
      kind 'user' (queued prompt) always uses payload:prompt, the human-authored text (it is contained in
      `rendered` wherever both exist).
    Meta attachments keep text None. extra always = {entry_type:'attachment', attachment_type, visibility} plus
    toolUseID / hookEvent / rendered_role (renderedRole) when present and, for queued_command, command_mode,
    rendered_in_human_turn_variant (the entry also has `renderedInHumanTurn`, an alternative wrapper used when the
    notification shares a turn with a human message; we cannot tell which was sent and use `rendered`) and, for
    task-notifications, notification_statuses as above. The build report section `attachments` gives counts by
    type x kind x visibility x text_source and how often a visible attachment's payload also appears in a
    Parser-derived user/system text of the same session (double-delivery check).
    Consequence for probes: most cc_local 'system' events are attachment reminders (total_tokens_reminder alone is
    the largest type); filter on extra.entry_type == 'attachment' / extra.attachment_type when only message-level
    harness text is wanted, and on extra.visibility to drop the version-inferred or assumed cases.
  Other entry types the Parser skips but that carry a `timestamp` (queue-operation, frame-link,
  file-history-delta, any other timestamped type) -> meta, emitted by this loader with
  extra = {entry_type, operation} (ids/enums only, never content): harness bookkeeping, kept for their timestamps.
  Entry types without a timestamp (custom-title, ai-title, last-prompt, mode, atis-latch, bridge-session,
  agent-name, cost-state, file-history-snapshot, artifact-* ...) are dropped and counted in the build report.
  Subagent / workflow-agent files: every entry gets _nested=True (is_subagent=True; a subagent's 'user' text turn is
  the parent's prompt, so the Parser maps it to system with extra.nested_prompt, as for SWE-chat nested traffic),
  agent_id = the <id> of agent-<id>.jsonl (equals the entries' own agentId), and parent_call_id =
    plain subagents:   .meta.json toolUseId (the parent's Agent/Task call id)
    workflow agents:   call_id of the main file's Workflow tool call whose result toolUseResult.runId == <wf_run>
                       (earliest such result by timestamp when the run was resumed/polled several times).
  Workflow journal.jsonl lines (started / result / failed / launched; no timestamps) -> meta with ts=None,
  ts_kind='none', is_subagent=True, agent_id = the line's agentId, parent_call_id as for workflow agents,
  extra = {entry_type:'workflow_journal', journal_type, result_type, sort_ts, sort_ts_source}. Labels, keys and
  result payloads are not copied.

ORDERING (seq)
  Each file is parsed with its own Parser in line order (so call->tool-name lookup and thinking-char carry stay
  within one stream). The session's events are then merged and sorted by
      (event time, source file order, line number, block index within the line)
  event time = parsed `timestamp` (ms precision). source file order = the members' main files (root first, then
  members by earliest timestamp, uuid), then every member's directory JSONL files (member order, relative path).
  Ties on time therefore keep file order, then line order, then block order.
  Journal lines have no time: they sort at an inferred time (stored in extra.sort_ts, ts stays None):
    started -> first event time of agent-<agentId>.jsonl in the same workflow dir; result/failed -> its last event
    time; launched (no agentId) -> first event time in the workflow dir; fallback -> last event time of the session.
  The time sort matters: main files write some lines out of time order (queue-operation lines are written before
  the stop_hook_summary of the previous turn; continuation files start with queue-operation lines stamped at the
  resume time followed by the copied history). Sorting puts every event at its stamped time.
  loader_counters.ts_inversions_adjacent_<role> / ts_lines_over_1h_below_running_max_<role> /
  files_with_ts_inversion_<role> count these raw write-order inversions per file role.

DEDUPLICATION (copies inside a family)
  After sorting, the first (file, line) at which an entry uuid occurs keeps its events; the same uuid at any other
  (file, line) is dropped. Because copies share the timestamp and mains come in member order, the root's copy wins.
  In a merged family every main-file event carries extra.family_member (0 = root, then member order), so a probe
  that walks seq can tell when consecutive events come from different member files.
  Lines without uuid (queue-operation, frame-link, file-history-delta) are deduplicated on a hash of the entry with
  sessionId and cwd removed. Raw block counts (recon) include the copies; IR counts do not.
"""
import glob
import hashlib
import json
import os
import re
from collections import Counter, defaultdict

import pandas as pd

from analysis.lib import cc_jsonl, ir, sample
from analysis.loaders.cc_build_stats import build_stats

CORPUS = "cc_local"
ROOT = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "claude-code-local")
ANALYSIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ANALYSIS, "cache")
OUT = os.path.join(ANALYSIS, "out", "build")
PARSER_TYPES = {"assistant", "user", "system", "progress", "result"}
TOP_STRATA = 5
FAR_FUTURE = pd.Timestamp("2262-01-01", tz="UTC").to_pydatetime()

# ---- attachments: moved to analysis/lib/cc_attach.py (same code) ----
from analysis.lib.cc_attach import (RENDER_MIN_VERSION, ATT_RENDERED_TYPES, ATT_OLD_ONLY_VISIBLE, ATT_HIDDEN, ATT_PAYLOAD,
                                    STATUS_RX, TASK_NOTE, NOTE_HEADER, OVERLAP_MIN_CHARS, _join, _sub, _norm, _version, _statuses)
from analysis.lib.cc_attach import attachment_event as _attachment_event


def _tag_task_notifications(evs, C):
    """Parser user entries delivered as <task-notification> text (system events): add their <status> values.
    A notification text starts with the tag, or (subagent streams) with a '[SYSTEM NOTIFICATION' header line."""
    for ev in evs:
        txt = ev.get("text")
        if ev["kind"] in ("system", "user") and isinstance(txt, str) and TASK_NOTE in txt \
                and txt.lstrip().startswith((TASK_NOTE, NOTE_HEADER)):
            ex = json.loads(ev["extra"]) if ev.get("extra") else {}
            ex["notification_statuses"] = _statuses(txt)
            ev["extra"] = ir.j(ex)
            C[f"user_entry_task_notification_events_copies_included:{ev['kind']}"] += 1


def _dt(ts):
    return ir.parse_ts(ir.iso(ts)) if ts else None


def discover():
    """List sessions: [{sid, project, files: [(role, relpath)], orphan}]. relpath is posix, relative to ROOT."""
    out = []
    for proj in sorted(os.listdir(ROOT)):
        pdir = os.path.join(ROOT, proj)
        if not os.path.isdir(pdir):
            continue
        mains = {f[:-6] for f in os.listdir(pdir) if f.endswith(".jsonl") and os.path.isfile(os.path.join(pdir, f))}
        subdirs = {d for d in os.listdir(pdir) if os.path.isdir(os.path.join(pdir, d))}
        with_jsonl = {d for d in subdirs if glob.glob(os.path.join(pdir, d, "**", "*.jsonl"), recursive=True)}
        for sid in sorted(mains | with_jsonl):
            files = [("main", f"{proj}/{sid}.jsonl")] if sid in mains else []
            if sid in with_jsonl:
                subs = sorted(os.path.relpath(f, ROOT).replace("\\", "/")
                              for f in glob.glob(os.path.join(pdir, sid, "**", "*.jsonl"), recursive=True))
                for rel in subs:
                    base = rel.rsplit("/", 1)[-1]
                    role = "journal" if base == "journal.jsonl" else ("wf_agent" if "/subagents/workflows/" in rel else "subagent")
                    files.append((role, rel))
            out.append({"sid": sid, "project": proj, "files": files, "orphan": sid not in mains})
    return out


def read_jsonl(rel):
    """[(line_no, entry or None)], n_lines, n_bad. Blank lines count as lines (like the recon) but yield no entry."""
    rows, n, bad = [], 0, 0
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            n += 1
            s = line.strip()
            if not s:
                continue
            try:
                rows.append((i, json.loads(s)))
            except json.JSONDecodeError:
                bad += 1
    return rows, n, bad


def fork_families(units):
    """Join file-sets whose main files share any entry uuid. Returns (families as lists of unit indices, root first;
    stats). Members are ordered by (earliest timestamp in the main file, session uuid)."""
    first_ts, where = {}, defaultdict(set)
    for ui, s in enumerate(units):
        lo = None
        for role, rel in s["files"]:
            if role != "main":
                continue
            rows, _, _ = read_jsonl(rel)
            for _, e in rows:
                if not isinstance(e, dict):
                    continue
                d = _dt(e.get("timestamp"))
                if d is not None and (lo is None or d < lo):
                    lo = d
                if e.get("uuid"):
                    where[e["uuid"]].add(ui)
        first_ts[ui] = lo or FAR_FUTURE
    parent = list(range(len(units)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    shared = 0
    for u, uis in where.items():
        if len(uis) > 1:
            shared += 1
            uis = sorted(uis)
            for ui in uis[1:]:
                parent[find(ui)] = find(uis[0])
    groups = defaultdict(list)
    for ui in range(len(units)):
        groups[find(ui)].append(ui)

    def order(ui):
        return (first_ts[ui], units[ui]["sid"])
    fams = sorted((sorted(g, key=order) for g in groups.values()), key=lambda g: order(g[0]))
    multi = [f for f in fams if len(f) > 1]
    return fams, {"uuids_in_multiple_main_files": shared, "families_with_multiple_files": len(multi),
                  "files_in_multi_file_families": sum(len(f) for f in multi),
                  "family_size_histogram": dict(sorted(Counter(len(f) for f in fams).items())),
                  "multi_file_families_spanning_project_dirs": sum(1 for f in multi if len({units[i]["project"] for i in f}) > 1)}


def _meta_extra(e):
    """extra for timestamped non-attachment entry types the Parser skips (ids/enums only)."""
    t = e.get("type")
    ex = {"entry_type": t}
    if t == "queue-operation":
        ex["operation"] = e.get("operation")
    return ex


def _runid_calls(e, out):
    """Collect Workflow runId -> [(result time, call_id)] from a main-file user entry."""
    tur = e.get("toolUseResult")
    if not isinstance(tur, dict) or not isinstance(tur.get("runId"), str):
        return
    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
    for b in msg.get("content") if isinstance(msg.get("content"), list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
            out[tur["runId"]].append((_dt(e.get("timestamp")) or FAR_FUTURE, b["tool_use_id"]))


def process_session(s, stratum, C, raw):
    """Parse one session (a family of file-sets) into IR events with seq. C: loader stats, raw: recon-style scan."""
    sid = s["sid"]
    tagged = []          # [sortdt, fidx, line, k, dupkey, ev]
    run_calls = defaultdict(list)
    file_span = {}       # fidx -> (min dt, max dt) over its events with ts
    journals = []        # (fidx, rel, rows)
    total_lines = 0
    for fidx, (role, rel, member) in enumerate(s["files"]):
        rows, n, bad = read_jsonl(rel)
        total_lines += n
        C[f"files_{role}"] += 1
        C[f"lines_{role}"] += n
        C["bad_json_lines"] += bad
        raw["files"] += 1
        raw["lines"] += n
        for _, e in rows:
            raw_scan(e, raw)
        if role == "journal":
            journals.append((fidx, rel, rows))
            continue
        p = cc_jsonl.Parser(CORPUS, sid, stratum, ts_kind="event")
        agent_id = parent = None
        if role in ("subagent", "wf_agent"):
            base = rel.rsplit("/", 1)[-1]
            agent_id = base[len("agent-"):-len(".jsonl")] if base.startswith("agent-") else None
            if role == "subagent":
                mp = os.path.join(ROOT, rel[:-len(".jsonl")] + ".meta.json")
                try:
                    with open(mp, encoding="utf-8") as fh:
                        parent = json.load(fh).get("toolUseId")
                except (OSError, ValueError):
                    parent = None
            else:
                cands = sorted(run_calls.get(rel.split("/")[-2], []))
                parent = cands[0][1] if cands else None
            C[f"{role}_files_parent_call_found"] += parent is not None
            C[f"{role}_files_parent_call_missing"] += parent is None
        prev_dt = run_max = None
        had_inv = False
        for line_no, e in rows:
            if not isinstance(e, dict):
                C["non_object_lines"] += 1
                continue
            t = e.get("type")
            ld = _dt(e.get("timestamp"))
            if ld is not None:  # write order vs stamped time, raw lines of this file
                if prev_dt is not None and ld < prev_dt:
                    C[f"ts_inversions_adjacent_{role}"] += 1
                    had_inv = True
                if run_max is not None and (run_max - ld).total_seconds() > 3600:
                    C[f"ts_lines_over_1h_below_running_max_{role}"] += 1
                prev_dt, run_max = ld, ld if run_max is None else max(run_max, ld)
            if role == "main":
                _runid_calls(e, run_calls)
            else:
                e = dict(e, _nested=True, _agent_id=agent_id, _parent_call_id=parent)
            u = e.get("uuid")
            dupkey = ("u", u) if u else None
            before = len(p.events)
            if t in PARSER_TYPES:
                p.feed(e)
                if t == "user":
                    _tag_task_notifications(p.events[before:], C)
            elif e.get("timestamp"):
                if u and u in p.seen_uuid:
                    C["dup_uuid_lines_skipped_in_file"] += 1
                else:
                    if u:
                        p.seen_uuid.add(u)
                    else:
                        k = {a: b for a, b in e.items() if a not in ("sessionId", "cwd")}
                        dupkey = ("h", hashlib.sha1(json.dumps(k, sort_keys=True, default=str).encode("utf-8")).hexdigest())
                    if t == "attachment":
                        kind, text, ex, payload = _attachment_event(e, role != "main", raw["att"])
                        ev = p._emit(e, e["timestamp"], kind=kind, text=text, extra=ir.j(ex))
                        if payload is not None:
                            ev["_payload"] = payload  # for the double-delivery check; not an IR column
                    else:
                        kind = "meta"
                        p._emit(e, e["timestamp"], kind="meta", extra=ir.j(_meta_extra(e)))
                    C[f"loader_emitted:{t}:{kind}"] += 1
            else:
                C[f"dropped_untimestamped:{t}"] += 1
            for k, ev in enumerate(p.events[before:]):
                d = _dt(ev["ts"])
                tagged.append([d, fidx, line_no, k, dupkey, ev])
                if d is not None:
                    lo, hi = file_span.get(fidx, (d, d))
                    file_span[fidx] = (min(lo, d), max(hi, d))
        C[f"files_with_ts_inversion_{role}"] += had_inv
    # journal lines: meta, no ts, sorted at an inferred time
    agent_span, wf_span = {}, {}
    for fidx, (role, rel, member) in enumerate(s["files"]):
        if role == "wf_agent" and fidx in file_span:
            wf, aid = rel.split("/")[-2], rel.rsplit("/", 1)[-1][len("agent-"):-len(".jsonl")]
            lo, hi = file_span[fidx]
            agent_span[(member, wf, aid)] = (lo, hi)
            a, b = wf_span.get((member, wf), (lo, hi))
            wf_span[(member, wf)] = (min(a, lo), max(b, hi))
    sess_end = max((x[0] for x in tagged if x[0] is not None), default=FAR_FUTURE)
    for fidx, rel, rows in journals:
        member = s["files"][fidx][2]
        wf = rel.split("/")[-2]
        cands = sorted(run_calls.get(wf, []))
        parent = cands[0][1] if cands else None
        p = cc_jsonl.Parser(CORPUS, sid, stratum, ts_kind="event")
        for line_no, e in rows:
            if not isinstance(e, dict):
                C["non_object_lines"] += 1
                continue
            jt, aid = e.get("type"), e.get("agentId")
            span = agent_span.get((member, wf, aid)) if aid else None
            if span is not None and jt == "started":
                sd, src = span[0], "agent_first_event"
            elif span is not None and jt in ("result", "failed"):
                sd, src = span[1], "agent_last_event"
            elif (member, wf) in wf_span:
                sd, src = wf_span[(member, wf)][0], "workflow_first_event"
            else:
                sd, src = sess_end, "session_last_event"
            C[f"journal_sort_ts_source:{src}"] += 1
            C[f"journal_type:{jt}"] += 1
            ev = p._emit({"agentId": aid, "_nested": True, "_parent_call_id": parent}, None, kind="meta",
                         extra=ir.j({"entry_type": "workflow_journal", "journal_type": jt,
                                     "result_type": type(e.get("result")).__name__ if "result" in e else None,
                                     "sort_ts": None if sd is FAR_FUTURE else sd.isoformat(), "sort_ts_source": src}))
            tagged.append([sd, fidx, line_no, 0, None, ev])
    # events without ts outside journals (none expected): carry the previous event time of the same file
    last = {}
    for row in sorted(tagged, key=lambda r: (r[1], r[2], r[3])):
        if row[0] is None:
            row[0] = last.get(row[1], FAR_FUTURE)
            C["events_without_ts_carried"] += 1
        last[row[1]] = row[0]
    tagged.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    events, first_pos = [], {}
    prev_member = None
    for d, fidx, line_no, k, dupkey, ev in tagged:
        if dupkey is not None:
            pos = first_pos.setdefault(dupkey, (fidx, line_no))
            if pos != (fidx, line_no):
                C["copy_events_dropped_uuid" if dupkey[0] == "u" else "copy_events_dropped_hash"] += 1
                continue
        role, _, member = s["files"][fidx]
        if role == "main":
            if prev_member is not None and member != prev_member:
                C["family_member_switches"] += 1
            prev_member = member
            if s["n_members"] > 1:  # which member file of a merged resume chain this main-file event came from
                ex = json.loads(ev["extra"]) if ev.get("extra") else {}
                ex["family_member"] = member
                ev["extra"] = ir.j(ex)
        ev["seq"] = len(events)
        events.append(ev)
    # double-delivery check: is a visible attachment's payload also inside a Parser-derived user/system text of
    # this session (i.e. the same text reached the IR twice)? Whitespace-normalized substring test; payloads
    # shorter than OVERLAP_MIN_CHARS are not tested (short strings match by accident).
    msg = None
    for ev in events:
        pl = ev.pop("_payload", None)
        if pl is None or ev["kind"] == "meta":
            continue
        if msg is None:
            msg = _norm("\n\x00".join(x["text"] for x in events if x["kind"] in ("user", "system") and x.get("text")
                                      and '"entry_type":"attachment"' not in (x.get("extra") or "")))
        at = json.loads(ev["extra"])["attachment_type"]
        npl = _norm(pl)
        if len(npl) < OVERLAP_MIN_CHARS:
            C[f"overlap|{at}|too_short"] += 1
        else:
            C[f"overlap|{at}|{'found' if npl in msg else 'not_found'}"] += 1
    return events, total_lines


def _status_bucket(s):
    return s if re.fullmatch(r"[a-z_-]{1,20}", s or "") else "other"


def attachment_report(df, detail=True):
    """IR-level counts (after resume-chain dedupe) of attachment-derived events and of task notifications
    (attachment queued_command vs user-entry text). Enums and counts only."""
    tot, by_type = defaultdict(Counter), defaultdict(lambda: defaultdict(Counter))
    notes = defaultdict(lambda: defaultdict(Counter))
    vis_sessions = set()
    for sid, kind, ex, text in zip(df.session_id.tolist(), df.kind.tolist(), df.extra.tolist(), df.text.tolist()):
        if not isinstance(ex, str) or ('"entry_type":"attachment"' not in ex and '"notification_statuses"' not in ex):
            continue
        e = json.loads(ex)
        if e.get("entry_type") == "attachment":
            at = e.get("attachment_type")
            dims = (("kind", kind), ("visibility", e.get("visibility")), ("text_source", e.get("text_source", "(meta: none)")),
                    ("text", "present" if isinstance(text, str) else "null"))
            for dim, val in dims:
                tot[dim][str(val)] += 1
                by_type[str(at)][dim][str(val)] += 1
            if at == "queued_command":
                tot["queued_command_mode_x_kind"][f"{e.get('command_mode')}|{kind}"] += 1
            if kind != "meta":
                vis_sessions.add(sid)
            src = "attachment_queued_command"
        else:
            src = "user_entry_text"
        if "notification_statuses" in e:
            st = e["notification_statuses"] or []
            n = notes[src]
            n["kind"][kind] += 1
            n["first_status"][_status_bucket(st[0]) if st else "<no status tag>"] += 1
            n["text"]["present" if isinstance(text, str) else "null"] += 1
            if len(st) > 1:
                n["multi"]["events_with_more_than_one_status"] += 1
            if any(x in ("failed", "killed") for x in st):
                n["multi"]["events_with_failed_or_killed_status"] += 1
    out = {"attachment_events": int(sum(tot["kind"].values())),
           **{f"by_{dim}": dict(c.most_common()) for dim, c in tot.items()},
           "sessions_with_visible_attachment_events": len(vis_sessions),
           "task_notifications": {src: {k: dict(c.most_common()) for k, c in n.items()} for src, n in sorted(notes.items())}}
    if detail:
        out["by_attachment_type"] = {at: {dim: dict(c.most_common()) for dim, c in d.items()}
                                     for at, d in sorted(by_type.items(), key=lambda kv: -sum(kv[1]["kind"].values()))}
    return out


def attachment_raw_report(A, C):
    """Raw-line checks (copies included) from _attachment_event, and the IR-level double-delivery check."""
    by_type, pvr, ov = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for k, n in A.items():
        parts = k.split("|")
        if parts[0] == "by_type":
            by_type[parts[1]][f"{parts[2]}|{parts[3]}"] += n
        elif parts[0] == "payload_vs_rendered":
            pvr[f"{parts[1]}.{parts[2]}"][parts[3]] += n
    for k in [k for k in C if k.startswith("overlap|")]:
        _, at, res = k.split("|")
        ov[at][res] += C.pop(k)
    return {"rule": "see load_cc_local docstring, ENTRY -> IR MAPPING / ATTACHMENT entries",
            "render_min_version": ".".join(map(str, RENDER_MIN_VERSION)),
            "raw_entries_copies_included": {
                "by_type_visibility_rendered": {t: dict(c.most_common()) for t, c in sorted(by_type.items(), key=lambda kv: -sum(kv[1].values()))},
                "rendered_types_with_rendered_below_min_version": int(A.get("rendered_below_min_version", 0)),
                "hidden_types_with_rendered": int(A.get("hidden_type_with_rendered", 0)),
                "unknown_type_entries": int(sum(c[x] for c in by_type.values() for x in c if x.startswith("unknown_type|")))},
            "payload_field_vs_rendered": {k: dict(c) for k, c in sorted(pvr.items())},
            "double_delivery_check_ir": {"method": f"whitespace-normalized payload of a visible attachment event found as a substring "
                                                   f"of the session's Parser-derived user/system texts; payloads < {OVERLAP_MIN_CHARS} chars not tested",
                                         "by_type": {t: dict(c) for t, c in sorted(ov.items())},
                                         "found_total": int(sum(c["found"] for c in ov.values())),
                                         "tested_total": int(sum(c["found"] + c["not_found"] for c in ov.values()))}}


def raw_scan(e, raw):
    """Recon-equivalent raw counts over every line, copies included (method of recon/recon_cc_local.py)."""
    if not isinstance(e, dict):
        return
    ts = e.get("timestamp")
    msg = e.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
        return
    for b in msg["content"]:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_use":
            raw["tool_use_blocks"] += 1
            raw["call_ts"][b.get("id")] = ts
        elif b.get("type") == "tool_result":
            raw["tool_result_blocks"] += 1
            raw["res_ts"][b.get("tool_use_id")] = ts


def raw_summary(raw):
    call_ts, res_ts = raw["call_ts"], raw["res_ts"]
    lat = []
    for cid, ct in call_ts.items():
        rt = res_ts.get(cid)
        if ct and rt:
            lat.append((ir.parse_ts(ir.iso(rt)) - ir.parse_ts(ir.iso(ct))).total_seconds())
    return {"files": raw["files"], "lines": raw["lines"], "tool_use_blocks": raw["tool_use_blocks"],
            "tool_result_blocks": raw["tool_result_blocks"], "tool_use_ids_unique": len(call_ts),
            "tool_result_ids_unique": len(res_ts), "results_without_call": len(set(res_ts) - set(call_ts)),
            "calls_without_result": len(set(call_ts) - set(res_ts)), "paired_both_ts": len(lat),
            "paired_identical_ts": sum(1 for x in lat if x == 0),
            "paired_ms_multiples": sum(1 for x in lat if abs(x * 1000 - round(x * 1000)) < 1e-6),
            "paired_negative_delta": sum(1 for x in lat if x < 0)}


def main():
    os.makedirs(os.path.join(CACHE, "samples"), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    units = discover()
    fams, fork_info = fork_families(units)
    sessions = []
    for f in fams:
        members = [units[i] for i in f]
        files = [(r, rel, m) for m, u in enumerate(members) for r, rel in u["files"] if r == "main"]
        files += [(r, rel, m) for m, u in enumerate(members) for r, rel in u["files"] if r != "main"]
        sessions.append({"sid": members[0]["sid"], "project": members[0]["project"], "files": files,
                         "n_members": len(members), "orphan": all(u["orphan"] for u in members)})
    proj_n = Counter(s["project"] for s in sessions)
    ranked = sorted(proj_n, key=lambda p: (-proj_n[p], p))
    alias = {p: (f"proj{k + 1:02d}" if k < TOP_STRATA else "other") for k, p in enumerate(ranked)}
    C, raw = Counter(), {"files": 0, "lines": 0, "tool_use_blocks": 0, "tool_result_blocks": 0, "call_ts": {}, "res_ts": {},
                         "att": Counter()}
    by_sid, pop = {}, []
    for s in sessions:
        evs, n_lines = process_session(s, alias[s["project"]], C, raw)
        by_sid[s["sid"]] = evs
        pop.append({"session_id": s["sid"], "stratum": alias[s["project"]], "length": n_lines})
    pop = pd.DataFrame(pop)
    smp = sample.draw(pop, CORPUS)
    smp["session_unit"] = "family of resume-chained main files + their subagent/workflow JSONL"
    sample.save(smp, os.path.join(CACHE, "samples", f"{CORPUS}.json"))
    frames, report_splits = {}, {}
    for split in ("A", "B"):
        df = ir.to_frame([ev for sid in smp[split] for ev in by_sid[sid]])
        basic = ir.validate(df)
        df.to_parquet(os.path.join(CACHE, f"{CORPUS}_{split}.parquet"), index=False)
        frames[split] = df
        report_splits[split] = {"sessions_in_sample": len(smp[split]),
                                "sessions_with_zero_events": sum(1 for sid in smp[split] if not by_sid[sid]),
                                "validate": {k: int(v) for k, v in basic.items()}, **build_stats(df, private=True),
                                "attachments": attachment_report(df, detail=False)}
    in_sample = set(smp["A"]) | set(smp["B"])
    full = ir.to_frame([ev for s in sessions for ev in by_sid[s["sid"]]])
    u = full[full.uuid.notna()].groupby("uuid").session_id.nunique()
    fork_info.update({"sessions_after_merge": len(sessions), "file_sets_before_merge": len(units),
                      "copy_events_dropped_uuid": C.pop("copy_events_dropped_uuid", 0),
                      "copy_events_dropped_hash": C.pop("copy_events_dropped_hash", 0),
                      "member_switches": C.pop("family_member_switches", 0),
                      "uuids_in_more_than_one_session_after_merge": int((u > 1).sum())})
    att = attachment_raw_report(raw["att"], C)
    att["full_corpus_ir"] = attachment_report(full)
    report = {
        "corpus": CORPUS,
        "privacy": "aggregates only; strata are aliases (proj01..proj05 by session count, other); MCP tools collapsed to mcp__*",
        "session_unit": smp["session_unit"],
        "population": {"sessions": len(sessions), "orphan_subagent_dirs": sum(u["orphan"] for u in units),
                       "sessions_with_subagent_files": sum(any(r in ("subagent", "wf_agent") for r, _, _ in s["files"]) for s in sessions),
                       "sessions_with_workflow_journals": sum(any(r == "journal" for r, _, _ in s["files"]) for s in sessions),
                       "sessions_by_stratum": dict(Counter(pop.stratum).most_common()),
                       "project_dirs": len(proj_n), "sessions_in_A_or_B": len(in_sample),
                       "sessions_not_sampled": len(sessions) - len(in_sample),
                       "length_lines": {k: float(v) for k, v in pop.length.describe().items()}},
        "non_jsonl_files": {"tool_results_txt": len(glob.glob(os.path.join(ROOT, "*", "*", "tool-results", "*"))),
                            "workflow_run_json": len(glob.glob(os.path.join(ROOT, "*", "*", "workflows", "*.json"))),
                            "subagent_meta_json": len(glob.glob(os.path.join(ROOT, "*", "*", "subagents", "**", "*.meta.json"), recursive=True))},
        "recon_reproduction": {"recon_file": "analysis/out/recon/cc_local.txt",
                               "expected": {"files": 1172, "lines": 210465, "tool_use_blocks": 46333, "tool_result_blocks": 46332,
                                            "paired_both_ts": 41706, "paired_identical_ts": 1, "paired_ms_multiples": 41706,
                                            "paired_negative_delta": 0},
                               "raw_scan": raw_summary(raw)},
        "fork_families": fork_info,
        "attachments": att,
        "loader_counters": dict(sorted(C.items())),
        "full_corpus_ir": build_stats(full, private=True),
        "splits": report_splits,
        "cache_rows": {k: int(len(v)) for k, v in frames.items()},
    }
    with open(os.path.join(OUT, f"{CORPUS}_build.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    print(json.dumps({"sessions": len(sessions), "A": len(smp["A"]), "B": len(smp["B"]), "rows": report["cache_rows"],
                      "raw": report["recon_reproduction"]["raw_scan"], "fork": fork_info}, indent=1))


if __name__ == "__main__":
    main()
