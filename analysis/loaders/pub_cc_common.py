"""Shared loader machinery for the public Claude Code JSONL corpora that carry Anthropic request ids (Phase E new corpora).

  corpus             raw data (read-only)                                     loader module
  pub_cc_hf          C:/Swarms/data/acquired/cli-claude-code-hf (12 HF repos) analysis/loaders/load_pub_cc_hf.py
  pub_trace_commons  C:/Swarms/data/acquired/cli-trace-commons (trace-commons) analysis/loaders/load_pub_trace_commons.py

Corpus-specific decisions (which files, stratum) are in each loader's docstring and in CORPORA below. Everything else is
here. Format reference: analysis/CORPUS_INVENTORY.md sections 5.0, 5.10, 5.11; the closest existing loader is
analysis/loaders/load_cc_local.py (same Claude Code generation: attachment entries, subagents/ and workflows/ layout,
resume chains), whose session rule this module follows.

FILES
  Only *.jsonl files are read. Skipped: anything under .cache/ (Hugging Face download metadata), workflow journal files
  (journal.jsonl: no timestamps, no tool traffic; counted in the build report as excluded), every non-JSONL file
  (README, _b5e_manifest.json, manifest/redaction/briefing files, parquet tables, .js). Roles by path:
    agent-<id>.jsonl under .../subagents/workflows/<run>/  -> wf_agent  (workflow subagent)
    agent-<id>.jsonl anywhere else                          -> subagent  (Task/Agent subagent)
    any other .jsonl                                        -> main      (session transcript)
  Lines are decoded as UTF-8 (errors='replace'); unparseable lines are counted (bad_json_lines) and skipped.

POPULATION PASS (structure only; runs over every file of the corpus, all splits)
  To define sessions, dedupe copies and run the field audit, every file is opened once and each line's JSON
  STRUCTURE is read: type, uuid, sessionId, timestamp, tool_use ids, tool_result tool_use_ids, requestId presence,
  message.model (pub_trace_commons stratum) and a sha1 fingerprint of the whole entry (copy-equality check). No text,
  argument, command or result content is retained, measured or written for any session at this stage, and no IR is
  built for a session outside the split being built. (B, E and H files are therefore opened by this pass; nothing
  from their content fields is kept. Stated so the blindness claim is exact.)

SESSION (unit of sampling and resampling)
  Files are joined (union-find) when they
    (a) share any entry uuid: resume chains (a main file that starts with a copy of another main file's history, as in
        cc_local) and byte-level copies of a session uploaded to two repos (armand0e/claude-fable-5-claude-code and
        cfahlgren1/Fable-5-traces share 29 main files and 8 subagent files with identical uuid sets);
    (b) carry the same sessionId value (subagent files carry their parent session's sessionId; copies across repos keep
        it);
    (c) are a non-main file without any sessionId and its layout parent: <prefix>.jsonl or <prefix>/session.jsonl for
        a path <prefix>/subagents/... (victor/claude-worldcup-2026-wallchart-traces has no sessionId anywhere; its
        data/session.jsonl and 52 agent files are one session).
  A session = one group. Main files are ordered by (earliest timestamp in the file, relative path); the first is the
  ROOT (for the 29 cross-repo copies both copies start at the same stamp, so the lexicographically first path, the
  armand0e copy, is root). session_id = the root's sessionId; a root without sessionId gets 'path:<relative path>'.
  A group without a main file is an orphan (its earliest file is root); counted in the build report.
  length (for the length tercile of the split cells) = distinct entries of the session: distinct uuids plus distinct
  fingerprints of uuid-less lines (sessionId and cwd removed), journals excluded.

FIELD AUDIT (per session, before the split; splits.new_corpora 'N sessions after the loader's field audit')
  A session passes if at least one tool_use id is answered by a tool_result in the session's files with a timestamp
  on both carrying entries (per-event stamps + call/result join: the Track B corpus-level criterion applied per
  session). Failures are counted by reason (no_tool_use / no_joined_call_with_both_stamps) and by repo, and excluded
  from N, the splits and every cache.

SPLITS (analysis/prereg_e.json splits.new_corpora, seed prereg_e_common.SEED_NEW_CORPUS = 20261006)
  Population table: one row per passing session (session_id, stratum, length), sorted by session_id. Cells =
  lib/sample.py's rule: stratum x length tercile (rank 'first', pct, over the whole population). The table is
  permuted once with np.random.default_rng(SEED_NEW_CORPUS). A = min(200, floor(0.2 N)) drawn by cell from the
  permuted table; R = the rest; B = min(2000, floor(|R|/3)) drawn by cell from R; E = min(2000, floor(|R|/3)) drawn by
  cell from R minus B; H = everything left. Each draw takes the first k sessions of each cell in permuted order, with
  k from lib/sample._alloc (proportional, largest remainder) and a per-cell floor of min(5, cell size).
  FLOOR RULE (deviation from lib/sample, for the change_log): lib/sample floors every cell at min(5, cell size) and
  does not cap the floors, so with more cells than the draw can feed the floors alone would exceed the pre-registered
  A/B/E sizes (here: 21 cells vs A = 32). The floor per draw is min(5, floor(draw size / number of non-empty cells)),
  the same rule as the other Phase E new-corpus loaders (newcorp_common._take, load_tbench2.draw_splits). It is
  recorded per draw (floor_used). (An earlier run of this loader used the largest feasible floor instead; it gave the
  same A and different B/E/H for pub_cc_hf; it was replaced before any B/E/H session was parsed.)
  Files written: analysis/cache/samples/<corpus>.json (A, B + allocations), analysis/cache/samples/<corpus>_EH.json
  (E, H + allocations), analysis/out/phase_e/heldout_manifest_<corpus>.json (sha256 of '\\n'.join(sorted H ids), the
  method of analysis/HELDOUT_MANIFEST.json), analysis/cache/<corpus>_index.json (session -> split, stratum, files, for
  A/B/E only; H has no index entry).

ENTRY -> IR MAPPING (analysis/lib/ir.py; built only for the sessions of the split being built)
  Each file is parsed with its own analysis.lib.cc_jsonl.Parser(corpus, session_id, stratum, ts_kind='event') in line
  order:
    assistant blocks  -> assistant (text) / call (tool_use, server_tool_use); thinking -> extra.thinking_chars;
                         usage_* from message.usage; api_msg_id = message.id; model = message.model
    user entries      -> result (one per tool_result block; is_error -> native_error; toolUseResult timers, stderr ->
                         extra/stderr), user (human prompt) or system (isMeta / harness prefixes / nested prompt)
    system entries    -> meta (subtype, durationMs, ...)
    attachment        -> lib/cc_attach.attachment_event (via the Parser): system/user when the model saw it, else meta
                         (extra.visibility / text_source; hook_success attachments keep extra.toolUseID)
  request_id = the entry's top-level requestId, kept on every event of that entry (Claude Code writes the same id on
  every content block of one response). It is kept raw: entries whose model is '<synthetic>' (harness-written
  messages) can carry one; consumers should drop model == '<synthetic>' before treating an id as provider-minted, and
  decodability is prereg_e_common.decode_req_ms (2 cfahlgren1 entries carry a 28-char req_ value that does not decode).
  User entries delivered as <task-notification> text get extra.notification_statuses
  (load_cc_local._tag_task_notifications, imported).
  Other timestamped entry types the Parser skips (queue-operation, file-history-delta, turn_ended, pr-link ...)
  -> meta with extra = {entry_type, operation} (load_cc_local._meta_extra, imported: ids/enums only).
  Untimestamped entry types (ai-title, last-prompt, mode, permission-mode, file-history-snapshot, custom-title,
  agent-name, agent-color, bridge-session, atis-latch, cost-state, ...) are dropped and counted.
  Subagent / workflow-agent files: every entry gets _nested=True (is_subagent=True; the subagent's 'user' prompt maps to
  system with extra.nested_prompt), agent_id = <id> of agent-<id>.jsonl, parent_call_id =
    subagent: the tool_use_id of the earliest result (any file of the session) whose toolUseResult.agentId == <id>;
    wf_agent: the tool_use_id of the earliest result whose toolUseResult.runId == the workflow run directory name;
    else None (no .meta.json files exist in these corpora; fill counted in the build report).
  Workflow agents are launched asynchronously: their events are stamped after the parent Workflow call's result, so a
  probe must not read "subagent event after parent result" as an anomaly in these corpora.

ORDERING AND DEDUPLICATION (as load_cc_local)
  Events of all files are merged and sorted by (event time, file order, line number, block index); file order = main
  files in member order, then non-main files by (member, path). An event without a timestamp carries the previous
  event time of its file. After sorting, the first (file, line) at which an entry uuid occurs keeps its events and
  the same uuid at any other (file, line) is dropped (cross-repo copies and resume-chain copies collapse onto the
  root's copy; the build report counts copied entries with identical sha1 fingerprints, sessionId/cwd/version
  ignored). uuid-less lines
  are deduplicated on their fingerprint. In a group with more than one main file every main-file event carries
  extra.family_member (0 = root).

SECRETS (CORPUS_INVENTORY 'Credentials in upstream public data')
  These public uploads contain credential-like values: bearer tokens in curl commands, API-key and token env
  assignments, JSON secret fields; some are placeholders. At load time every event's text,
  command, stderr, args (JSON, walked string by string) and extra (JSON, walked) is passed through SECRET_RX: known
  token formats (Anthropic/OpenAI/GitHub/HF/AWS/Slack/Google/Stripe keys, JWTs, PEM private-key blocks) are replaced
  whole; contextual forms (Bearer <v>, x-api-key/api-key/authorization header values, NAME_API_KEY|SECRET|TOKEN|
  PASSWORD=<v>, JSON fields "password"/"api_key"/"secret"/"*_token": "<v>") keep their prefix and lose the value. Each
  replacement is the literal '<REDACTED:<pattern name>>'. Counts per pattern and field go to the build report; values
  are never printed or stored. Consequence: a redacted result's byte length differs from the raw one (rare: see the
  count). Claude Code JSONL has no env/kwargs/headers fields of its own; none is copied (extra keeps only the timer and
  id/enum keys selected by the Parser and cc_attach).

SPLIT BUILD
  main() rebuilds samples, manifests, the index and the A cache from scratch (idempotent: same data, same seed, same
  files). --split {B,E} builds analysis/cache/<corpus>_<split>.parquet through the same build_frame() used for A; it
  re-runs the population pass, asserts the draw reproduces the saved sample files, reads ids with
  prereg_e_common.split_ids (key 'E' only of the EH file) and refuses A (built by main) and H. In this step --split was
  only exercised on A ids (selftest: build_frame(A ids) == the A cache) and never run on B or E.
"""
import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import cc_jsonl, ir, sample
from analysis.loaders.cc_build_stats import build_stats
from analysis.loaders.load_cc_local import _meta_extra, _tag_task_notifications
from analysis.probes import prereg_e_common as pe

DATA = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
ANALYSIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(ANALYSIS)
CACHE = os.path.join(ANALYSIS, "cache")
SAMPLES = os.path.join(CACHE, "samples")
OUT_E = os.path.join(ANALYSIS, "out", "phase_e")
PARSER_TYPES = {"assistant", "user", "system", "progress", "result", "attachment"}
FAR_FUTURE = pd.Timestamp("2262-01-01", tz="UTC").to_pydatetime()
TOP_STRATA = 8
A_MAX, A_FRAC, BE_MAX, FLOOR = 200, 0.2, 2000, 5
SEED = pe.SEED_NEW_CORPUS

CORPORA = {
    "pub_cc_hf": {
        "dir": "acquired/cli-claude-code-hf",
        "loader": "analysis/loaders/load_pub_cc_hf.py",
        "include": lambda rel: True,
        "stratum": "repo",
        "stratum_rule": "source repo folder (<owner>__<repo>, pin dropped) of the session's root file; top 8 by passing-"
                        "session count (ties by name) kept, the rest 'other'",
    },
    "pub_trace_commons": {
        "dir": "acquired/cli-trace-commons",
        "loader": "analysis/loaders/load_pub_trace_commons.py",
        "include": lambda rel: "/sessions/claude_code/" in "/" + rel,
        "stratum": "model",
        "stratum_rule": "modal message.model of the session's assistant entries ('<synthetic>' and missing excluded, ties "
                        "by name; 'unknown' if none); top 8 kept, the rest 'other'",
    },
}

# ------------------------------------------------------------------------------------------------------------ secrets
_BS = "\\"
SECRET_RX = [  # (name, regex, value group: 0 = whole match replaced, n = only group n replaced)
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), 0),
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}"), 0),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"), 0),
    ("hf_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}"), 0),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), 0),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}"), 0),
    ("stripe_key", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{20,}"), 0),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), 0),
    ("bearer", re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._~+/\-]{20,}=*)"), 2),
    ("api_key_header", re.compile(r"(?i)(\b(?:x-api-key|api-key|x-auth-token|authorization)[\"']?\s*[:=]\s*[\"']?)"
                                  r"([A-Za-z0-9._\-]{16,})"), 2),
    ("env_secret", re.compile(r"(\b[A-Z][A-Z0-9_]*(?:API_KEY|APIKEY|SECRET|TOKEN|PASSWORD|PASSWD)\s*=\s*[\"']?)"
                              r"([A-Za-z0-9._/+\-]{16,})"), 2),
    ("json_secret_field", re.compile(r"(?i)(" + _BS + _BS + r"*\"(?:password|passwd|api[_-]?key|apikey|secret|client_secret|"
                                     r"access_token|refresh_token|auth_token|token|bearer_token)" + _BS + _BS
                                     + r"*\"\s*:\s*" + _BS + _BS + r"*\")([^\"" + _BS + _BS + r"]{8,})"), 2),
]


def redact_str(s, C, field):
    """Replace credential-like values in one string. C counts f'{field}|{pattern}'. Returns the (possibly) new string."""
    if not isinstance(s, str) or not s:
        return s
    for name, rx, grp in SECRET_RX:
        if grp == 0:
            s, n = rx.subn(f"<REDACTED:{name}>", s)
        else:
            s, n = rx.subn(lambda m: m.group(1) + f"<REDACTED:{name}>", s)
        if n:
            C[f"{field}|{name}"] += n
    return s


def _redact_obj(o, C, field):
    if isinstance(o, str):
        return redact_str(o, C, field)
    if isinstance(o, list):
        return [_redact_obj(x, C, field) for x in o]
    if isinstance(o, dict):
        return {k: _redact_obj(v, C, field) for k, v in o.items()}
    return o


def redact_event(ev, C):
    """In-place redaction of text, command, stderr (strings) and args, extra (JSON walked). Returns True if changed."""
    changed = False
    for f in ("text", "command", "stderr"):
        v = ev.get(f)
        if isinstance(v, str):
            nv = redact_str(v, C, f)
            if nv != v:
                ev[f] = nv
                changed = True
    for f in ("args", "extra"):
        v = ev.get(f)
        if isinstance(v, str) and v:
            try:
                o = json.loads(v)
            except ValueError:
                nv = redact_str(v, C, f + "_unparsed")
            else:
                no = _redact_obj(o, C, f)
                nv = ir.j(no) if no != o else v
            if nv != v:
                ev[f] = nv
                changed = True
    return changed


def residual_secret_matches(df):
    """Re-scan of a built frame with SECRET_RX: matches whose value is not a '<REDACTED:' token (expected: none)."""
    C = Counter()
    for col in ("text", "args", "command", "stderr", "extra"):
        for v in df[col].dropna().astype(str):
            for name, rx, g in SECRET_RX:
                for m in rx.finditer(v):
                    if not (m.group(0) if g == 0 else m.group(g)).startswith("<REDACTED"):
                        C[f"{col}|{name}"] += 1
    return dict(sorted(C.items()))


# ------------------------------------------------------------------------------------------------------------ discovery
def corpus_root(corpus):
    return os.path.join(DATA, CORPORA[corpus]["dir"]).replace("\\", "/")


def file_role(rel):
    base = rel.rsplit("/", 1)[-1]
    if base == "journal.jsonl":
        return "journal"
    if base.startswith("agent-"):
        return "wf_agent" if "/subagents/workflows/" in "/" + rel else "subagent"
    return "main"


def discover(corpus):
    """[{rel, abs, role, repo}] for every *.jsonl of the corpus (journals included here, excluded later)."""
    root = corpus_root(corpus)
    inc = CORPORA[corpus]["include"]
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".cache")
        for fn in sorted(filenames):
            if not fn.endswith(".jsonl"):
                continue
            ab = os.path.join(dirpath, fn).replace("\\", "/")
            rel = os.path.relpath(ab, root).replace("\\", "/")
            if not inc(rel):
                continue
            out.append({"rel": rel, "abs": ab, "role": file_role(rel), "repo": rel.split("/", 1)[0].split("@", 1)[0]})
    return sorted(out, key=lambda f: f["rel"])


def read_jsonl(path):
    """[(line_no, entry or None)], n_lines, n_bad."""
    rows, n, bad = [], 0, 0
    with open(path, encoding="utf-8", errors="replace") as fh:
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


def _dt(ts):
    return ir.parse_ts(ir.iso(ts)) if ts else None


COPY_IGNORED_KEYS = ("sessionId", "cwd", "version")


def _h8(v):
    return hashlib.blake2b(json.dumps(v, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8"),
                           digest_size=8).hexdigest()


def _fp(e, drop=("sessionId", "cwd")):
    k = {a: b for a, b in e.items() if a not in drop}
    return hashlib.sha1(json.dumps(k, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def scan_file(f):
    """Structure-only scan of one file (see POPULATION PASS). No content field is retained."""
    rows, n, bad = read_jsonl(f["abs"])
    sc = {"lines": n, "bad": bad, "nonobj": 0, "sids": Counter(), "uuid_fp": {}, "nouuid_fp": set(), "first": None,
          "last": None, "tu": {}, "tr": {}, "models": Counter(), "types": Counter(), "req_entries": 0, "entries": 0}
    for _, e in rows:
        if not isinstance(e, dict):
            sc["nonobj"] += 1
            continue
        sc["entries"] += 1
        t = e.get("type")
        sc["types"][str(t)] += 1
        if isinstance(e.get("sessionId"), str) and e["sessionId"]:
            sc["sids"][e["sessionId"]] += 1
        d = _dt(e.get("timestamp"))
        if d is not None:
            sc["first"] = d if sc["first"] is None else min(sc["first"], d)
            sc["last"] = d if sc["last"] is None else max(sc["last"], d)
        if e.get("uuid") and e["uuid"] not in sc["uuid_fp"]:
            keep = {k: v for k, v in e.items() if k not in COPY_IGNORED_KEYS}
            sc["uuid_fp"][e["uuid"]] = (_fp(keep, drop=()), {k: _h8(v) for k, v in keep.items()},
                                        len(json.dumps(e.get("message"), ensure_ascii=False, default=str)))
        elif not e.get("uuid"):
            sc["nouuid_fp"].add(_fp(e))
        if e.get("requestId"):
            sc["req_entries"] += 1
        m = e.get("message")
        if isinstance(m, dict):
            if t == "assistant" and isinstance(m.get("model"), str):
                sc["models"][m["model"]] += 1
            if isinstance(m.get("content"), list):
                for b in m["content"]:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") in ("tool_use", "server_tool_use") and b.get("id"):
                        sc["tu"][b["id"]] = sc["tu"].get(b["id"], False) or d is not None
                    elif b.get("type") == "tool_result" and b.get("tool_use_id"):
                        sc["tr"][b["tool_use_id"]] = sc["tr"].get(b["tool_use_id"], False) or d is not None
    return sc


def group_sessions(files, scans):
    """Union-find over files (see SESSION). Returns (sessions, stats). files/scans exclude journals."""
    n = len(files)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    by_uuid, by_sid = defaultdict(list), defaultdict(list)
    for i, sc in enumerate(scans):
        for u in sc["uuid_fp"]:
            by_uuid[u].append(i)
        for s in sc["sids"]:
            by_sid[s].append(i)
    shared_uuid = 0
    for u, ii in by_uuid.items():
        if len(ii) > 1:
            shared_uuid += 1
            for j in ii[1:]:
                union(ii[0], j)
    for s, ii in by_sid.items():
        for j in ii[1:]:
            union(ii[0], j)
    rel_idx = {f["rel"]: i for i, f in enumerate(files)}
    layout_links = layout_missing = 0
    for i, f in enumerate(files):
        if f["role"] == "main" or scans[i]["sids"]:
            continue
        k = f["rel"].find("/subagents/")
        cands = [f["rel"][:k] + ".jsonl", f["rel"][:k] + "/session.jsonl"] if k >= 0 else []
        hit = [rel_idx[c] for c in cands if c in rel_idx]
        if hit:
            union(i, hit[0])
            layout_links += 1
        else:
            layout_missing += 1
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    def order(i):
        return (scans[i]["first"] or FAR_FUTURE, files[i]["rel"])
    sessions = []
    for g in groups.values():
        mains = sorted([i for i in g if files[i]["role"] == "main"], key=order)
        others = [i for i in g if files[i]["role"] != "main"]
        orphan = not mains
        root = mains[0] if mains else min(g, key=order)
        member_of_sid = {}
        for m_i, i in enumerate(mains):
            for s in scans[i]["sids"]:
                member_of_sid.setdefault(s, m_i)
        def member(i):
            for s in scans[i]["sids"]:
                if s in member_of_sid:
                    return member_of_sid[s]
            return 0
        others = sorted(others, key=lambda i: (member(i), files[i]["rel"]))
        flist = [(files[i]["role"], files[i]["rel"], m_i) for m_i, i in enumerate(mains)]
        flist += [(files[i]["role"], files[i]["rel"], member(i)) for i in others]
        sids_root = scans[root]["sids"]
        sid = sids_root.most_common(1)[0][0] if sids_root else f"path:{files[root]['rel']}"
        main_sids = {s for i in mains for s in scans[i]["sids"]}
        sessions.append({"session_id": sid, "root_rel": files[root]["rel"], "root_repo": files[root]["repo"],
                         "files": flist, "idx": mains + others,
                         "n_members": len(mains), "orphan": orphan,
                         "repos": sorted({files[i]["repo"] for i in g}),
                         "main_repos": sorted({files[i]["repo"] for i in mains}),
                         "resume_chain": len(main_sids) > 1})
    sessions.sort(key=lambda s: s["session_id"])
    ids = [s["session_id"] for s in sessions]
    assert len(ids) == len(set(ids)), "session id collision after grouping"
    multi = [s for s in sessions if s["n_members"] > 1]
    stats = {"file_groups": len(sessions), "uuids_in_more_than_one_file": shared_uuid,
             "groups_with_more_than_one_main_file": len(multi),
             "groups_with_mains_in_more_than_one_repo": sum(1 for s in sessions if len(s["main_repos"]) > 1),
             "groups_with_resume_chain_distinct_session_ids": sum(1 for s in sessions if s["resume_chain"]),
             "main_files_per_group_histogram": dict(sorted(Counter(s["n_members"] for s in sessions).items())),
             "orphan_groups_without_main_file": sum(1 for s in sessions if s["orphan"]),
             "files_attached_by_layout_without_sessionId": layout_links,
             "non_main_files_without_sessionId_or_layout_parent": layout_missing,
             "cross_repo_pairs": dict(Counter("+".join(s["main_repos"]) for s in sessions if len(s["main_repos"]) > 1))}
    return sessions, stats


def session_structure(s, scans, files):
    """Per-session structural aggregates for the field audit, length and stratum (no content)."""
    uu, nofp, tu, tr, models = {}, set(), {}, {}, Counter()
    copies_identical = copies_differ = 0
    differ_pairs, differ_keys, differ_len = Counter(), Counter(), Counter()
    first = None
    for i in s["idx"]:
        sc = scans[i]
        for u, (fp, kh, mlen) in sc["uuid_fp"].items():
            if u in uu:
                fp0, i0, kh0, mlen0 = uu[u]
                if fp0 == fp:
                    copies_identical += 1
                else:
                    copies_differ += 1
                    pair = f"{files[i0]['repo']} -> {files[i]['repo']}"
                    differ_pairs[pair] += 1
                    differ_keys[(pair, ",".join(sorted(k for k in set(kh0) | set(kh) if kh0.get(k) != kh.get(k))))] += 1
                    if kh0.get("message") != kh.get("message"):
                        differ_len[(pair, "kept_message_longer" if mlen0 > mlen else
                                    "dropped_message_longer" if mlen > mlen0 else "same_length")] += 1
            else:
                uu[u] = (fp, i, kh, mlen)
        nofp |= sc["nouuid_fp"]
        for k, v in sc["tu"].items():
            tu[k] = tu.get(k, False) or v
        for k, v in sc["tr"].items():
            tr[k] = tr.get(k, False) or v
        models.update(sc["models"])
        if sc["first"] is not None:
            first = sc["first"] if first is None else min(first, sc["first"])
    joined = sum(1 for k in tu if k in tr)
    joined_ts = sum(1 for k, v in tu.items() if v and tr.get(k))
    reason = None if joined_ts else ("no_tool_use" if not tu else "no_joined_call_with_both_stamps")
    real = Counter({m: c for m, c in models.items() if m and m != "<synthetic>"})
    modal = sorted(real.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if real else "unknown"
    return {"length": len(uu) + len(nofp), "tool_use_ids": len(tu), "joined": joined, "joined_both_ts": joined_ts,
            "audit_pass": reason is None, "audit_fail_reason": reason, "modal_model": modal,
            "copy_entries_identical": copies_identical, "copy_entries_differ": copies_differ,
            "copy_differ_pairs": differ_pairs, "copy_differ_keys": differ_keys, "copy_differ_len": differ_len,
            "first": first}


def collapse(labels, top=TOP_STRATA):
    n = Counter(labels)
    ranked = sorted(n, key=lambda k: (-n[k], k))
    keep = set(ranked[:top])
    return {k: (k if k in keep else "other") for k in n}


def population(corpus):
    """Population pass. Returns dict with files, scans, sessions (with structure, stratum) and report counters."""
    allf = discover(corpus)
    journals = [f for f in allf if f["role"] == "journal"]
    files = [f for f in allf if f["role"] != "journal"]
    scans = [scan_file(f) for f in files]
    j_lines = sum(read_jsonl(f["abs"])[1] for f in journals)
    sessions, gstats = group_sessions(files, scans)
    for s in sessions:
        s.update(session_structure(s, scans, files))
        s["stratum_raw"] = s["root_repo"] if CORPORA[corpus]["stratum"] == "repo" else s["modal_model"]
    passing = [s for s in sessions if s["audit_pass"]]
    cmap = collapse([s["stratum_raw"] for s in passing])
    for s in sessions:
        s["stratum"] = cmap.get(s["stratum_raw"], "other") if s["audit_pass"] else None
    rep = {
        "files": {"jsonl_total": len(allf), "by_role": dict(Counter(f["role"] for f in allf)),
                  "by_repo": dict(sorted(Counter(f["repo"] for f in allf).items())),
                  "journal_files_excluded": len(journals), "journal_lines_excluded": j_lines,
                  "lines": sum(sc["lines"] for sc in scans), "bad_json_lines": sum(sc["bad"] for sc in scans),
                  "non_object_lines": sum(sc["nonobj"] for sc in scans),
                  "entries": sum(sc["entries"] for sc in scans),
                  "entries_with_requestId_raw_copies_included": sum(sc["req_entries"] for sc in scans),
                  "entry_types_raw_copies_included": dict(sum((sc["types"] for sc in scans), Counter()).most_common())},
        "grouping": gstats,
        "copies": {"copied_uuid_entries_identical_fingerprint": sum(s["copy_entries_identical"] for s in sessions),
                   "copied_uuid_entries_differing_fingerprint": sum(s["copy_entries_differ"] for s in sessions),
                   "differing_by_kept_repo_to_dropped_repo": dict(sum((s["copy_differ_pairs"] for s in sessions),
                                                                      Counter()).most_common()),
                   "differing_top_level_keys": {f"{p} | {k}": int(n) for (p, k), n in sorted(
                       sum((s["copy_differ_keys"] for s in sessions), Counter()).items(), key=lambda kv: -kv[1])},
                   "differing_message_serialized_length": {f"{p} | {k}": int(n) for (p, k), n in sorted(
                       sum((s["copy_differ_len"] for s in sessions), Counter()).items())},
                   "fingerprint": "sha1 of the whole entry with sessionId, cwd and version removed; per-key blake2b-64 "
                                  "for the differing-key census; message length = len(json.dumps(message))",
                   "kept": "the root copy (first in file order); every other copy of a uuid is dropped"},
        "field_audit": {"sessions_before_audit": len(sessions), "pass": len(passing),
                        "fail_by_reason": dict(Counter(s["audit_fail_reason"] for s in sessions if not s["audit_pass"])),
                        "fail_by_root_repo": dict(Counter(s["root_repo"] for s in sessions if not s["audit_pass"])),
                        "rule": "pass = >= 1 tool_use id answered by a tool_result with timestamps on both entries"},
        "stratum": {"rule": CORPORA[corpus]["stratum_rule"],
                    "raw_label_counts_passing": dict(sorted(Counter(s["stratum_raw"] for s in passing).items())),
                    "collapse_map": dict(sorted(cmap.items())),
                    "stratum_counts_passing": dict(sorted(Counter(s["stratum"] for s in passing).items()))},
        "length": {"definition": "distinct entries (uuid + uuid-less fingerprints), journals excluded",
                   **{k: float(v) for k, v in pd.Series([s["length"] for s in passing], dtype=float).describe().items()}},
    }
    return {"files": files, "scans": scans, "sessions": sessions, "passing": passing, "report": rep}


# ------------------------------------------------------------------------------------------------------------ splits
def _fit_alloc(sizes, total):
    """lib/sample._alloc with floor = min(5, total // n_cells): the floor rule shared by the other Phase E new-corpus
    loaders (newcorp_common._take, load_tbench2.draw_splits), so every new corpus carries one deviation."""
    sizes = {k: v for k, v in sizes.items() if v > 0}
    f = min(FLOOR, total // max(1, len(sizes)))
    a = sample._alloc(sizes, total, floor=f)
    assert sum(a.values()) == total, (sum(a.values()), total)
    return a, f


def _take(df, alloc):
    ids = []
    for cell, k in alloc.items():
        ids += df.loc[df.cell == cell, "session_id"].head(k).tolist()
    return ids


def draw_splits(pop, corpus):
    """pop: session_id, stratum, length. Returns the A/B/E/H draw per splits.new_corpora (see module docstring)."""
    pop = pop.drop_duplicates("session_id").sort_values("session_id").reset_index(drop=True).copy()
    pop["stratum"] = pop["stratum"].fillna("unknown").astype(str)
    q = pop["length"].rank(method="first", pct=True)
    pop["tercile"] = np.where(q <= 1 / 3, "short", np.where(q <= 2 / 3, "mid", "long"))
    pop["cell"] = pop["stratum"] + "|" + pop["tercile"]
    cells = dict(zip(pop.session_id, pop.cell))
    rng = np.random.default_rng(SEED)
    pop = pop.iloc[rng.permutation(len(pop))].reset_index(drop=True)
    N = len(pop)
    n_a = min(A_MAX, int(np.floor(A_FRAC * N)))
    alloc_a, f_a = _fit_alloc(pop.groupby("cell").size().to_dict(), n_a)
    a_ids = _take(pop, alloc_a)
    R = pop[~pop.session_id.isin(set(a_ids))]
    n_b = min(BE_MAX, len(R) // 3)
    n_e = min(BE_MAX, len(R) // 3)
    alloc_b, f_b = _fit_alloc(R.groupby("cell").size().to_dict(), n_b)
    b_ids = _take(R, alloc_b)
    R2 = R[~R.session_id.isin(set(b_ids))]
    alloc_e, f_e = _fit_alloc(R2.groupby("cell").size().to_dict(), n_e)
    e_ids = _take(R2, alloc_e)
    h_ids = R2[~R2.session_id.isin(set(e_ids))].session_id.tolist()
    sets = [set(a_ids), set(b_ids), set(e_ids), set(h_ids)]
    assert sum(len(x) for x in sets) == N and len(set().union(*sets)) == N
    assert (len(a_ids), len(b_ids), len(e_ids)) == (n_a, n_b, n_e)
    alloc_h = dict(Counter(cells[s] for s in h_ids))
    return {"corpus": corpus, "seed": SEED, "population_sessions": int(N),
            "population_by_cell": {k: int(v) for k, v in sorted(Counter(cells.values()).items())},
            "A": sorted(a_ids), "B": sorted(b_ids), "E": sorted(e_ids), "H": sorted(h_ids),
            "alloc_A": alloc_a, "alloc_B": alloc_b, "alloc_E": alloc_e, "alloc_H": alloc_h,
            "floor_used": {"A": f_a, "B": f_b, "E": f_e}, "remainder_after_A": int(len(R)),
            "cells": cells}


def write_samples(d, corpus, session_unit):
    rule = ("analysis/prereg_e.json splits.new_corpora: N after field audit; A = min(200, floor(0.2 N)); of the rest R: "
            "B = min(2000, floor(R/3)), E = min(2000, floor(R/3)), H = remainder; lib/sample cells (stratum x length "
            "tercile over the population) via lib/sample._alloc with floor per draw = min(5, floor(n_draw / n_cells)) "
            "(floor_used); seed SEED_NEW_CORPUS = 20261006; one permutation, A then B then E take cell heads, H = rest")
    ab = {"corpus": corpus, "seed": d["seed"], "population_sessions": d["population_sessions"],
          "population_by_cell": d["population_by_cell"], "A": d["A"], "B": d["B"], "alloc_A": d["alloc_A"],
          "alloc_B": d["alloc_B"], "floor_used": {"A": d["floor_used"]["A"], "B": d["floor_used"]["B"]},
          "rule": rule, "session_unit": session_unit}
    eh = {"corpus": corpus, "seed": d["seed"], "population_sessions": d["population_sessions"],
          "remainder_after_A": d["remainder_after_A"], "E": d["E"], "H": d["H"], "alloc_E": d["alloc_E"],
          "alloc_H": d["alloc_H"], "floor_used": {"E": d["floor_used"]["E"]}, "rule": rule, "session_unit": session_unit}
    os.makedirs(SAMPLES, exist_ok=True)
    p1, p2 = os.path.join(SAMPLES, f"{corpus}.json"), os.path.join(SAMPLES, f"{corpus}_EH.json")
    with open(p1, "w", encoding="utf-8") as f:
        json.dump(ab, f, indent=1)
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(eh, f, indent=1)
    h_sha = hashlib.sha256("\n".join(d["H"]).encode()).hexdigest()
    man = {"corpus": corpus, "purpose": "Held-out split H for the Track C eval harness. Never read during tuning or "
                                        "analysis. Separate from analysis/HELDOUT_MANIFEST.json (not edited).",
           "n_H": len(d["H"]), "n_E": len(d["E"]), "n_B": len(d["B"]), "n_A": len(d["A"]),
           "sha256_sorted_H_ids": h_sha, "hash_method": "sha256 of '\\n'.join(sorted H ids).encode() (as HELDOUT_MANIFEST)",
           "ids_file": f"analysis/cache/samples/{corpus}_EH.json#H", "seed": d["seed"], "rule": rule}
    os.makedirs(OUT_E, exist_ok=True)
    with open(os.path.join(OUT_E, f"heldout_manifest_{corpus}.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    return {"samples_json": rel_root(p1), "samples_json_sha256": pe.sha256_file(p1),
            "samples_EH_json": rel_root(p2), "samples_EH_json_sha256": pe.sha256_file(p2),
            "sha256_sorted_ids": {k: hashlib.sha256("\n".join(d[k]).encode()).hexdigest() for k in ("A", "B", "E", "H")}}


def rel_root(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


# ------------------------------------------------------------------------------------------------------------ parsing
def _parent_links(rows, agent_parent, run_parent):
    for _, e in rows:
        if not isinstance(e, dict) or e.get("type") != "user":
            continue
        tur = e.get("toolUseResult")
        if not isinstance(tur, dict):
            continue
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        ids = [b.get("tool_use_id") for b in (msg.get("content") if isinstance(msg.get("content"), list) else [])
               if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id")]
        d = _dt(e.get("timestamp")) or FAR_FUTURE
        for cid in ids:
            if isinstance(tur.get("agentId"), str):
                agent_parent[tur["agentId"]].append((d, cid))
            if isinstance(tur.get("runId"), str):
                run_parent[tur["runId"]].append((d, cid))


def parse_session(s, corpus, C, R):
    """One session (see SESSION) -> IR event dicts with seq. C: loader counters, R: redaction counters."""
    sid, stratum = s["session_id"], s["stratum"]
    root = corpus_root(corpus)
    loaded = []
    agent_parent, run_parent = defaultdict(list), defaultdict(list)
    for role, rel, member in s["files"]:
        rows, n, bad = read_jsonl(os.path.join(root, rel))
        C[f"files_{role}"] += 1
        C[f"lines_{role}"] += n
        C["bad_json_lines"] += bad
        loaded.append(rows)
        _parent_links(rows, agent_parent, run_parent)
    tagged = []
    for fidx, ((role, rel, member), rows) in enumerate(zip(s["files"], loaded)):
        p = cc_jsonl.Parser(corpus, sid, stratum, ts_kind="event")
        agent_id = parent = None
        if role in ("subagent", "wf_agent"):
            base = rel.rsplit("/", 1)[-1]
            agent_id = base[len("agent-"):-len(".jsonl")]
            if role == "wf_agent":
                cands = sorted(run_parent.get(rel.split("/")[-2], []))
            else:
                cands = sorted(agent_parent.get(agent_id, []))
            parent = cands[0][1] if cands else None
            C[f"{role}_files_parent_call_found"] += parent is not None
            C[f"{role}_files_parent_call_missing"] += parent is None
        for line_no, e0 in rows:
            if not isinstance(e0, dict):
                C["non_object_lines"] += 1
                continue
            e = e0 if role == "main" else dict(e0, _nested=True, _agent_id=agent_id, _parent_call_id=parent)
            t = e.get("type")
            u = e.get("uuid")
            dupkey = ("u", u) if u else None
            before = len(p.events)
            if t in PARSER_TYPES and not (t == "attachment" and not e.get("timestamp")):
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
                        dupkey = ("h", _fp(e0))
                    p._emit(e, e["timestamp"], kind="meta", extra=ir.j(_meta_extra(e)))
                    C[f"loader_emitted_meta:{t}"] += 1
            else:
                C[f"dropped_untimestamped:{t}"] += 1
            for k, ev in enumerate(p.events[before:]):
                tagged.append([_dt(ev["ts"]), fidx, line_no, k, dupkey, ev])
    last = {}
    for row in sorted(tagged, key=lambda r: (r[1], r[2], r[3])):
        if row[0] is None:
            row[0] = last.get(row[1], FAR_FUTURE)
            C["events_without_ts_carried"] += 1
        last[row[1]] = row[0]
    tagged.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    events, first_pos = [], {}
    for d, fidx, line_no, k, dupkey, ev in tagged:
        if dupkey is not None:
            pos = first_pos.setdefault(dupkey, (fidx, line_no))
            if pos != (fidx, line_no):
                C["copy_events_dropped_uuid" if dupkey[0] == "u" else "copy_events_dropped_fingerprint"] += 1
                continue
        role, _, member = s["files"][fidx]
        if role == "main" and s["n_members"] > 1:
            ex = json.loads(ev["extra"]) if ev.get("extra") else {}
            ex["family_member"] = member
            ev["extra"] = ir.j(ex)
        if redact_event(ev, R):
            C["events_redacted"] += 1
        ev["seq"] = len(events)
        events.append(ev)
    return events


def build_frame(corpus, ids, by_sid):
    """IR frame for the given session ids (sorted), validated. Returns (df, counters, redaction counters)."""
    C, R = Counter(), Counter()
    evs = []
    for sid in sorted(ids):
        evs += parse_session(by_sid[sid], corpus, C, R)
    df = ir.to_frame(evs)
    basic = ir.validate(df) if len(df) else {"rows": 0}
    return df, C, R, basic


# ------------------------------------------------------------------------------------------------------------ reports
def request_id_stats(df):
    rid = df[df.request_id.notna()]
    out = {"events_with_request_id": int(len(rid)), "by_kind": {k: int(v) for k, v in rid.kind.value_counts().items()}}
    for kind in ("assistant", "call"):
        sub = df[df.kind == kind]
        out[f"{kind}_fill"] = {"n": int(len(sub)), "with_request_id": int(sub.request_id.notna().sum()),
                               "fill_rate": float(sub.request_id.notna().mean()) if len(sub) else None}
    resp = df[df.api_msg_id.notna()].drop_duplicates(["session_id", "api_msg_id"])
    out["api_responses"] = {"n": int(len(resp)), "with_request_id": int(resp.request_id.notna().sum())}
    ids = sorted(set(rid.request_id.astype(str)))
    dec = [x for x in ids if pe.decode_req_ms(x) is not None]
    synth = df[(df.model.astype(str) == "<synthetic>") & df.request_id.notna()]
    shapes = Counter("req_vrtx_" if x.startswith("req_vrtx_") else ("req_" + str(len(x) - 4)) if x.startswith("req_")
                     else "other" for x in ids)
    per = rid.groupby("request_id").session_id.nunique()
    out.update({"distinct_request_ids": len(ids), "distinct_decodable_ms": len(dec),
                "decodable_rate": len(dec) / len(ids) if ids else None,
                "decoder": "analysis.probes.prereg_e_common.decode_req_ms (inferred UUIDv7-like ms layout; undocumented)",
                "distinct_shapes": dict(shapes.most_common()),
                "events_with_request_id_and_model_synthetic": int(len(synth)),
                "distinct_request_ids_in_more_than_one_session": int((per > 1).sum()),
                "sessions_with_any_request_id": int(rid.session_id.nunique()), "sessions": int(df.session_id.nunique())})
    return out


def split_stratum_table(d, by_sid):
    tab = defaultdict(lambda: Counter())
    for k in ("A", "B", "E", "H"):
        for s in d[k]:
            tab[by_sid[s]["stratum"]][k] += 1
    return {st: {k: int(c.get(k, 0)) for k in ("A", "B", "E", "H")} for st, c in sorted(tab.items())}


def write_index(corpus, d, by_sid):
    idx = {"corpus": corpus, "note": "A/B/E sessions only (H has no entry). files = [role, path relative to the corpus "
                                     "root, member]; built by the population pass (structure only).",
           "corpus_root": corpus_root(corpus), "sessions": {}}
    for k in ("A", "B", "E"):
        for s in d[k]:
            x = by_sid[s]
            idx["sessions"][s] = {"split": k, "stratum": x["stratum"], "stratum_raw": x["stratum_raw"],
                                  "length": x["length"], "repos": x["repos"], "n_members": x["n_members"],
                                  "files": [list(f) for f in x["files"]]}
    p = os.path.join(CACHE, f"{corpus}_index.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=1)
    return rel_root(p)


# ------------------------------------------------------------------------------------------------------------ split build
def build_split(corpus, split, ids=None, out_path=None, P=None):
    """Build a B or E cache through build_frame. ids/out_path overrides exist only for the selftest (A ids, scratch path)."""
    if ids is None:
        assert split in ("B", "E"), "only B or E can be built with --split (A is built by main(); H never)"
        ids = pe.split_ids(corpus, split)
    P = P or population(corpus)
    by_sid = {s["session_id"]: s for s in P["passing"]}
    pop = pd.DataFrame([{"session_id": s["session_id"], "stratum": s["stratum"], "length": s["length"]}
                        for s in P["passing"]])
    d = draw_splits(pop, corpus)
    saved = json.load(open(os.path.join(SAMPLES, f"{corpus}.json"), encoding="utf-8"))
    assert d["A"] == saved["A"] and d["B"] == saved["B"], "population draw no longer reproduces the saved samples"
    if split in ("B", "E"):
        assert sorted(ids) == d[split], f"{split} ids differ from the reproduced draw"
    df, C, R, basic = build_frame(corpus, ids, by_sid)
    path = out_path or os.path.join(CACHE, f"{corpus}_{split}.parquet")
    df.to_parquet(path, index=False)
    return df, C, R, basic, path


def selftest(corpus, P, a_df):
    """Exercises the --split code path on A ids only, the split guard and the redaction patterns (synthetic strings)."""
    import tempfile
    out = {}
    scratch = tempfile.mkdtemp(prefix=f"selftest_{corpus}_", dir=os.environ.get("NEWCORP_SCRATCH") or None)
    path = os.path.join(scratch, f"{corpus}_A_via_split_path.parquet")
    df, _, _, _, _ = build_split(corpus, "A", ids=json.load(open(os.path.join(SAMPLES, f"{corpus}.json"),
                                                                 encoding="utf-8"))["A"], out_path=path, P=P)
    back = pd.read_parquet(path)
    a_back = pd.read_parquet(os.path.join(CACHE, f"{corpus}_A.parquet"))
    out["split_path_on_A_equals_A_cache"] = bool(back.equals(a_back)) and bool(df.reset_index(drop=True).equals(
        a_df.reset_index(drop=True)))
    out["split_path_rows"] = int(len(back))
    for bad in ("A", "H"):
        try:
            build_split(corpus, bad, P=P)
            out[f"refuses_{bad}"] = False
        except AssertionError:
            out[f"refuses_{bad}"] = True
    os.remove(path)
    try:
        os.rmdir(scratch)
    except OSError:
        pass
    # redaction on synthetic, obviously fake values (built at runtime)
    fake = "Z" * 40
    cases = {"anthropic_key": "key sk-ant-" + fake, "bearer": "Authorization: Bearer " + fake,
             "env_secret": "export MY_API_KEY=" + fake, "json_secret_field": '{"password": "' + "z" * 12 + '"}',
             "github_token": "ghp_" + fake, "private_key_block": "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"}
    res = {}
    for name, s in cases.items():
        C = Counter()
        r = redact_str(s, C, "t")
        res[name] = bool(f"<REDACTED:{name}>" in r and fake not in r and "z" * 12 not in r and "abc" not in r)
    ev = {"args": json.dumps({"command": "curl -H 'x-api-key: " + fake + "' x"}), "text": None, "extra": None}
    C = Counter()
    redact_event(ev, C)
    res["args_json_walk"] = bool(fake not in ev["args"] and json.loads(ev["args"]))
    benign = "def token_count(x): return x  # TOKEN_LIMIT = 4096; Bearer auth explained"
    C = Counter()
    res["benign_unchanged"] = redact_str(benign, C, "t") == benign
    out["redaction_unit_tests"] = res
    out["all_pass"] = all(v for k, v in out.items() if isinstance(v, bool)) and all(res.values())
    return out


# ------------------------------------------------------------------------------------------------------------ main
def main(corpus, argv=None):
    ap = argparse.ArgumentParser(description=f"Loader for {corpus}")
    ap.add_argument("--split", choices=["B", "E"], help="build the B or E cache (NEXT step only)")
    args = ap.parse_args(argv)
    t0 = time.time()
    os.makedirs(SAMPLES, exist_ok=True)
    os.makedirs(OUT_E, exist_ok=True)
    if args.split:
        df, C, R, basic, path = build_split(corpus, args.split)
        rep = {"corpus": corpus, "split": args.split, "cache": rel_root(path), "validate": basic,
               "stats": build_stats(df), "request_id": request_id_stats(df), "loader_counters": dict(sorted(C.items())),
               "redactions": dict(sorted(R.items())), "residual_secret_matches": residual_secret_matches(df),
               "runtime_s": round(time.time() - t0, 1)}
        with open(os.path.join(OUT_E, f"newcorp_build_{corpus}_{args.split}.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
        print(json.dumps({"split": args.split, "rows": int(len(df)), "sessions": int(df.session_id.nunique())}))
        return
    P = population(corpus)
    t_pop = time.time() - t0
    passing = P["passing"]
    by_sid = {s["session_id"]: s for s in passing}
    pop = pd.DataFrame([{"session_id": s["session_id"], "stratum": s["stratum"], "length": s["length"]} for s in passing])
    d = draw_splits(pop, corpus)
    unit = "union-find group of Claude Code JSONL files sharing a uuid or a sessionId (copies and resume chains merged)"
    hashes = write_samples(d, corpus, unit)
    index_path = write_index(corpus, d, by_sid)
    t1 = time.time()
    df, C, R, basic = build_frame(corpus, d["A"], by_sid)
    a_path = os.path.join(CACHE, f"{corpus}_A.parquet")
    df.to_parquet(a_path, index=False)
    t_a = time.time() - t1
    st = selftest(corpus, P, df)
    a_stats = build_stats(df)
    report = {
        "corpus": corpus, "loader": CORPORA[corpus]["loader"], "common_module": "analysis/loaders/pub_cc_common.py",
        "raw_root": corpus_root(corpus),
        "generated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "population": {**P["report"], "N_after_field_audit": len(passing)},
        "splits": {"rule": "analysis/prereg_e.json splits.new_corpora (see pub_cc_common docstring SPLITS)",
                   "seed": d["seed"], "N": d["population_sessions"],
                   "sizes": {k: len(d[k]) for k in ("A", "B", "E", "H")}, "floor_used": d["floor_used"],
                   "by_stratum": split_stratum_table(d, by_sid), "cells": d["population_by_cell"],
                   "files": hashes, "index": index_path,
                   "heldout_manifest": f"analysis/out/phase_e/heldout_manifest_{corpus}.json"},
        "A_cache": {"path": rel_root(a_path), "sha256": pe.sha256_file(a_path), "validate": basic,
                    "events_by_kind": a_stats.get("events_by_kind"), "ts_kind": a_stats.get("ts_kind"),
                    "ts_fill": a_stats.get("ts_fill"), "ts_fractional_digits": a_stats.get("ts_fractional_digits"),
                    "pairing": a_stats.get("pairing"), "native_error": a_stats.get("native_error"),
                    "usage_fill": a_stats.get("usage_fill"), "request_id": request_id_stats(df),
                    "build_stats_full": a_stats},
        "A_loader_counters": dict(sorted(C.items())),
        "A_redactions": {"events_changed": int(C.get("events_redacted", 0)),
                         "by_field_and_pattern": dict(sorted(R.items())),
                         "residual_matches_after_redaction": residual_secret_matches(df),
                         "note": "counts only; values never printed or stored"},
        "selftest": st,
        "runtime_s": {"population_pass": round(t_pop, 1), "A_build": round(t_a, 1), "total": round(time.time() - t0, 1)},
    }
    with open(os.path.join(OUT_E, f"newcorp_build_{corpus}.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    print(json.dumps({"corpus": corpus, "N": d["population_sessions"], "sizes": report["splits"]["sizes"],
                      "floor_used": d["floor_used"], "A_rows": int(len(df)), "selftest_all_pass": st["all_pass"],
                      "runtime_s": report["runtime_s"]}, indent=1))
