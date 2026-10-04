"""Phase C discovery lens: git as an EXISTING second witness for the agent's own tool log (SWE-chat pinned).

Run from the worktree root:
    PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_commit_witness
Env: CW_N (sample size, default 1200), CW_PROCS (worker processes, default 4), CW_OUT (output path override),
CW_DUMP (directory for scratch call-level parquet dumps; not part of the JSON).

Writes analysis/out/phase_c/commit_witness.json: raw counts, rates with session-clustered bootstrap CIs (lib/stats.py),
and the pre-registered rules (PREREG) the counts were produced under. No interpretation in the data file; that lives in
analysis/notes/commit_witness.md.

Inputs (read-only): data/swe-chat-pinned/{sessions,checkpoints,commits}.parquet and transcripts/<session_id>.jsonl.
The transcript side is Claude Code JSONL only (parsed with analysis.lib.cc_jsonl.parse_lines); other scaffolds enter the
linkage-coverage counts (Q1) but not the transcript comparisons (Q1 transcript time order, Q2, Q3, Q4).

Questions
  Q1 linkage coverage: share of sessions with >=1 linked commit; commits per session; commit_date vs session time span.
  Q2 corroboration: Edit/MultiEdit/Write calls vs the linked commits' patch '+' lines and committed file content.
  Q3 reverse: committed '+' lines in agent-attributed files with no transcript call that could have produced them;
     agent_changes entries traceable to a transcript call; transcript calls present in agent_changes.
  Q4 commit hashes printed in Bash results ('[branch sha] subject', git log / rev-parse) vs commits.commit_sha.
"""
import bisect
import collections
import hashlib
import json
import math
import os
import re
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from analysis.lib import cc_jsonl, ir, stats
from analysis.lib.sample import _alloc

DATA = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "swe-chat-pinned")
TRANS = os.path.join(DATA, "transcripts")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # analysis/
OUT_DIR = os.path.join(HERE, "out", "phase_c")
OUT = os.environ.get("CW_OUT") or os.path.join(OUT_DIR, "commit_witness.json")
N_SAMPLE = int(os.environ.get("CW_N", "1200"))
N_PROC = int(os.environ.get("CW_PROCS", "4"))

TOL_S = 2.0
MIN_CHARS = 8
DECOY_SIZE_FACTOR = 2.0
LABEL_ALIASES = {"opencode": "OpenCode", "claude-code": "Claude Code", "claude code": "Claude Code"}
FAIL_MARKERS = {"cc_tool_use_error", "cc_permission_denied", "cc_interrupt_reject"}
REDACT_RX = re.compile(r"REDACTED")
COMMIT_RX = re.compile(r"(?m)^\[(?P<branch>[^\]\n]{1,200}?) (?:\(root-commit\) )?(?P<sha>[0-9a-f]{7,40})\] ?(?P<subj>[^\n]*)$")
LOG_RX = re.compile(r"(?m)^(?:[*|/\\] *)*(?:commit )?(?P<sha>[0-9a-f]{7,40})\b")
REWRITE_KW = ("--amend", "rebase", "reset --", "reset HEAD", "squash", "cherry-pick", "filter-branch", "push --force", "push -f")
BASH_EXPLAIN_KW = ("git checkout", "git restore", "git stash", "git reset", "git apply", "git merge", "git pull", "git rebase",
                   "patch ", "sed -i", "perl -pi", "prettier", "black ", "ruff format", "ruff check --fix", "eslint --fix",
                   "gofmt", "cargo fmt", "rustfmt", "npm run format", "npm run lint", "biome", "dprint", "clang-format",
                   "isort", "autopep8", "> ", ">> ", "tee ", "mv ", "cp ")

PREREG = {
    "fixed_before_first_run": True,
    "unit": "session (cluster bootstrap, lib/stats.py, SEED=%d, N_BOOT=%d); headline Q2/Q3 rates also given clustered by repo_id"
            % (stats.SEED, stats.N_BOOT),
    "format_sniff": "first 64 KB of each transcript (1 MB if undecided and larger): '\"projectHash\"' -> gemini; starts with "
                    "'{\"info\"' -> opencode; '\"parentUuid\"' -> claude_code; codex/copilot markers; else other",
    "linkage": "session -> checkpoints = union of checkpoints.session_pks membership and sessions.checkpoint_ids; "
               "checkpoint -> commits via commits.checkpoint_pk. 'linked ok commit' = status=='ok' (has sha, patch). "
               "status=='commit_not_found' rows have no sha and no patch; counted separately.",
    "sample": "seeded (stats.SEED) sample of N_SAMPLE sessions among sessions whose transcript sniffs as claude_code and that have "
              ">=1 linked ok commit; strata = sessions.agent label (aliases merged); allocation lib.sample._alloc (proportional, "
              "floor 5); within a stratum the first k of a seeded permutation.",
    "line_normalization": "norm(line) = ' '.join(line.split()) (collapse all whitespace incl. indentation and CR). Lines split on '\\n'.",
    "informative_line": "len(norm(line)) >= %d. Reason (set before looking at outcomes): short lines such as '}', '});', 'end', "
                        "'else:' recur in almost any patch and would produce chance matches; 8 is a round a-priori cut, not tuned. "
                        "Chance matching at this cut is measured by the decoy baseline." % MIN_CHARS,
    "line_identity": "64-bit blake2b of the normalized line; set semantics everywhere (duplicates collapse).",
    "added_lines": "Edit: set(info lines of new_string) - set(info lines of old_string); MultiEdit: union over sub-edits; "
                   "Write: set(info lines of content). Calls with an empty added set are counted as 'no_informative_added_lines'.",
    "successful_call": "a call with a paired result whose native_error is not True and whose ir.error_marker is not one of "
                       "cc_tool_use_error / cc_permission_denied / cc_interrupt_reject. Calls without a paired result -> 'no_result'.",
    "path_match": "call file_path with '\\' -> '/'; matched commit path = the longest repo-relative path p among the session's "
                  "linked commits' patch paths such that file_path == p or file_path ends with '/' + p.",
    "tolerance_s": "%.1f s. Reason: commit_date has 1-s resolution, transcript timestamps ms; 2 s covers truncation plus rounding. "
                   "Set before looking." % TOL_S,
    "target_commit": "earliest linked ok commit whose patch touches the matched path and whose commit_date >= call ts - tolerance.",
    "superseded_line": "a line L of the added set is superseded if a later successful mutation call (file order) on the same "
                       "matched path with ts <= target commit_date + tolerance removed it: Edit/MultiEdit with L in its old lines "
                       "and not in its new lines, or Write whose content lacks L. Testable set A2 = added - superseded.",
    "q2_categories": "unconstrained_file_not_in_linked_commits | unconstrained_only_earlier_commits | unconstrained_overwritten_later "
                     "(A2 empty) | constrained -> corroborated_full (all of A2 found) / corroborated_partial (some) / "
                     "contradicted_looking (none found). no_ts if the call has no timestamp.",
    "q2_witnesses": "plus = the target commit's patch '+' lines for the matched file; state = the target commit's "
                    "file_attribution[path].committed_version lines (committed file content); plus_union = '+' lines of all "
                    "linked ok commits touching the path with commit_date >= call ts - tolerance. Primary witness: plus for "
                    "Edit/MultiEdit, state for Write (a Write over an existing file leaves unchanged lines out of the '+' set). "
                    "All witnesses reported for both tools.",
    "q2_bash_could_explain": "for contradicted_looking calls: flag if a Bash call after the mutation call (file order) and with "
                             "ts <= target commit_date + tolerance has a command containing the file's basename or any of "
                             + json.dumps(list(BASH_EXPLAIN_KW)),
    "decoy_baseline": "for each constrained call, a decoy file section drawn (seeded) from needed commits of a DIFFERENT repo with "
                      "the same file extension and an informative line count within [1/%g, %g]x of the target section; fallbacks "
                      "(recorded): drop the size window, then drop the extension. Same categories computed against the decoy. "
                      "Separate decoy pools for the plus and state witnesses." % (DECOY_SIZE_FACTOR, DECOY_SIZE_FACTOR),
    "q3_explaining_corpus": "for a commit row (checkpoint_pk, sha): union over ALL sessions in that checkpoint's session list "
                            "(parsed when claude_code) of the info lines of successful Edit/MultiEdit new_string and Write content "
                            "(all lines, not only added) and of every Bash command; path-agnostic (lenient: biases toward "
                            "'explained'). Time-respecting variant: producing call ts <= commit_date + tolerance. Rows whose "
                            "checkpoint has any session without a parsed claude_code transcript are 'explainers_incomplete' and "
                            "excluded from the primary Q3 rates (counted).",
    "q3_unexplained_file": "agent_only or mixed file with >= 1 informative '+' line and 0 explained lines (any time).",
    "q3_agent_changes_key": "Edit: hash(norm-block(old_string), norm-block(new_string), file_path); Write: hash(norm-block(content), "
                            "file_path); transcript keys from successful calls; MultiEdit contributes one key per sub-edit.",
    "q4_commit_claim_regex": COMMIT_RX.pattern + " applied to every Bash result text",
    "q4_log_claim_regex": LOG_RX.pattern + " applied to Bash results whose command contains 'git log' or 'git rev-parse'",
    "q4_match": "prefix match (claimed sha is a prefix of commit_sha), in order: linked to this session; any ok commit of the "
                "session's repo; any ok commit in the table; none. Window check for matched commit claims: call ts - tol <= "
                "commit_date <= result ts + tol.",
    "q4_history_rewrite_flag": "an unmatched commit claim is flagged if a later Bash command in the session contains any of "
                               + json.dumps(list(REWRITE_KW)),
}


CHANGES = [
    {"what": "N_SAMPLE default 600 -> 1200", "when": "after a 20-session code-check pilot (output not kept)",
     "reason": "pilot parse took 0.6 s for 48 transcripts; a larger n tightens CIs within the ~6 GB RAM budget. Not outcome-driven; "
               "no matching rule or threshold changed."},
    {"what": "added diagnostics: (a) sessions.created_at minus first transcript event (sample); (b) agent_changes entries untraced "
             "by the full key, re-checked with a looser key (tool, file_path, new_string/content only); (c) Q4 unmatched commit claims: "
             "claimed subject equal to the first line of a linked / same-repo commit message; (d) peak RSS",
     "when": "after the pilot", "reason": "pilot showed metadata 'before_start' pairs and untraced agent_changes entries that the "
                                          "primary measures cannot attribute; the diagnostics only add breakdowns, primary rules unchanged"},
    {"what": "bug fix: mcp__acp__Edit / mcp__acp__Write / mcp__acp__MultiEdit (Zed ACP bridge; same input schema) now count as "
             "Edit / Write / MultiEdit in transcripts, and agent_changes entries named mcp__acp__Write are keyed as Write",
     "when": "after the first full run",
     "reason": "agent_changes contained mcp__acp__Write entries; a grep found ACP mutation tools in 7 transcripts. Omission, not a rule change."},
    {"what": "added diagnostics: (a) global trace of agent_changes entries against keys from ALL released claude_code transcripts; "
             "(b) for contradicted_looking Edits: another session of the target commit's checkpoint made a successful mutation on "
             "the same path between the call and the target commit; (c) bash_could_explain broken down by keyword family; "
             "(d) residual by target attribution; (e) Q4 matched claims outside the call window: dt values",
     "when": "after the first full run", "reason": "first run left 8,906 agent_changes entries and 223 residual contradicted-looking "
                                                   "Edits unattributed; breakdowns only, primary rules and thresholds unchanged"},
]
CHANGES.append(
    {"what": "added Q3 variant B: explaining corpus = listed sessions plus every released claude_code session that owns (by the "
             "full or loose key) an agent_changes entry of the same commit row; added owner-repo breakdown for agent_changes "
             "entries traced to another repo's session (same GitHub owner or not); optional scratch dump of call-level records "
             "(CW_DUMP, not part of the JSON)",
     "when": "after the second full run",
     "reason": "second run showed 8,310 agent_changes entries owned by sessions not listed in the commit's checkpoint, so the "
               "primary Q3 corpus under-counts what the dataset's own agent record can explain. Primary Q3 unchanged."})
CHANGES.append(
    {"what": "added mutation_stream_census: successful Edit/MultiEdit/Write calls with informative added lines across all claude_code "
             "transcripts, linked vs unlinked sessions, and the product with the sample constrained rate",
     "when": "before the final run", "reason": "the brief asks how much of the mutation stream git can constrain at all"})
CHANGES.append(
    {"what": "added Q2 breakdown by sample stratum (sessions.agent label) and, for Q4 matched claims outside the call window, "
             "the count whose command contains 'git commit'", "when": "before the final run",
     "reason": "the brief asks for scaffold stratification where possible; breakdowns only"})
CHANGES.append(
    {"what": "POST-HOC sensitivity (not a rule change): for Edit calls that are contradicted_looking under the plus witness, the "
             "first and last split-line of each new_string (which may begin or end mid-line) are re-checked as substrings of the "
             "target section's normalized '+' lines; plus post-hoc breakdowns of the Edit contradicted_looking rate by file "
             "extension (12 most frequent) and by worktree-like path (regex '/worktrees?/|/\\.worktrees/')",
     "when": "after the third full run, from inspecting 8 residual examples",
     "reason": "examples showed new_string fragments that are partial lines (exact whole-line matching cannot find them) and a higher "
               "rate on worktree paths and on formatter-heavy languages. The primary rule stays as pre-registered; the sensitivity "
               "variant is reported next to it and is labelled post-hoc."})
WT_RX = re.compile(r"/worktrees?/|/\.worktrees/")
ACP = {"mcp__acp__Edit": "Edit", "mcp__acp__Write": "Write", "mcp__acp__MultiEdit": "MultiEdit"}
BASH_KW_FAMILIES = {
    "git_history": ("git checkout", "git restore", "git stash", "git reset", "git apply", "git merge", "git pull", "git rebase"),
    "formatter": ("prettier", "black ", "ruff format", "ruff check --fix", "eslint --fix", "gofmt", "cargo fmt", "rustfmt",
                  "npm run format", "npm run lint", "biome", "dprint", "clang-format", "isort", "autopep8"),
    "inplace_edit": ("patch ", "sed -i", "perl -pi"),
    "redirect_copy_move": ("> ", ">> ", "tee ", "mv ", "cp "),
}


# ------------------------------------------------------------------------------------------------------------- helpers
def H(s):
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8", "surrogatepass"), digest_size=8).digest(), "little")


def norm(line):
    return " ".join(line.split())


def info_set(text):
    out = set()
    if not text:
        return out
    for line in text.split("\n"):
        n = norm(line)
        if len(n) >= MIN_CHARS:
            out.add(H(n))
    return out


def block_key(*parts):
    return H("\x1f".join("\n".join(norm(x) for x in (p or "").split("\n")) for p in parts))


def ep(ts):
    if not ts:
        return None
    d = ir.parse_ts(ts)
    return d.timestamp() if d is not None else None


def to_arr(s):
    return np.unique(np.fromiter(s, dtype=np.uint64, count=len(s))) if s else np.zeros(0, dtype=np.uint64)


def n_in(a_set, arr):
    """How many hashes of a Python set are in a sorted uint64 array."""
    if not a_set or arr is None or len(arr) == 0:
        return 0
    q = to_arr(a_set)
    idx = np.searchsorted(arr, q)
    idx[idx >= len(arr)] = 0
    return int((arr[idx] == q).sum())


def label(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "unknown"
    return LABEL_ALIASES.get(str(x).strip().lower(), str(x))


def sniff(path):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(1 << 16)
            h = head.decode("utf-8", "replace")
            if "\"parentUuid\"" not in h and size > len(head):
                h += fh.read(1 << 20).decode("utf-8", "replace")
    except OSError:
        return "missing"
    if not h.strip():
        return "empty"
    s = h.lstrip()
    if "\"projectHash\"" in h[:4096]:
        return "gemini"
    if s.startswith("{\"info\"") or re.match(r"\{\s*\"info\"", s):
        return "opencode"
    if "\"parentUuid\"" in h:
        return "claude_code"
    if "\"payload\"" in h and ("\"session_meta\"" in h or "\"response_item\"" in h or "\"turn_context\"" in h):
        return "codex"
    if "\"session.start\"" in h or "\"user.message\"" in h:
        return "copilot"
    return "other"


_Q = re.compile(r"\\([0-7]{3}|.)")


def unquote_git(p):
    """git C-style quoted path -> str."""
    if not (len(p) >= 2 and p[0] == '"' and p[-1] == '"'):
        return p
    body, out = p[1:-1], bytearray()
    i = 0
    esc = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r", "v": b"\v"}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            m = re.match(r"[0-7]{3}", body[i + 1:i + 4])
            if m:
                out.append(int(m.group(0), 8))
                i += 4
                continue
            out += esc.get(body[i + 1], body[i + 1].encode())
            i += 2
            continue
        out += c.encode("utf-8", "surrogatepass")
        i += 1
    return out.decode("utf-8", "replace")


def _strip_ab(p, pre):
    p = unquote_git(p.strip())
    return p[len(pre):] if p.startswith(pre) else p


def parse_patch(patch):
    """Unified diff (git show output) -> ({path: dict(plus=arr, minus=arr, n_plus_raw)}, n_combined_sections)."""
    secs, cur, in_hunk, combined = [], None, False, 0
    for line in (patch or "").split("\n"):
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):]
            path = None
            m = re.match(r'^("(?:[^"\\]|\\.)*"|a/.*?) ("(?:[^"\\]|\\.)*"|b/.*)$', rest)
            if m:
                a, b = _strip_ab(m.group(1), "a/"), _strip_ab(m.group(2), "b/")
                path = b
            # unquoted paths with spaces: prefer the split where a == b
            if not rest.startswith('"') and " b/" in rest:
                for k in [i for i in range(len(rest)) if rest.startswith(" b/", i)]:
                    if rest[2:k] == rest[k + 3:]:
                        path = rest[k + 3:]
                        break
            cur = {"path": path, "plus": set(), "minus": set(), "n_plus_raw": 0}
            secs.append(cur)
            in_hunk = False
            continue
        if line.startswith("diff --cc ") or line.startswith("diff --combined "):
            cur, in_hunk = None, False
            combined += 1
            continue
        if cur is None:
            continue
        if not in_hunk:
            if line.startswith("+++ "):
                p = line[4:].split("\t")[0]
                if p.strip() != "/dev/null":
                    cur["path"] = _strip_ab(p, "b/")
            elif line.startswith("@@"):
                in_hunk = True
            continue
        if line.startswith("@@"):
            continue
        c = line[:1]
        if c == "+":
            cur["n_plus_raw"] += 1
            n = norm(line[1:])
            if len(n) >= MIN_CHARS:
                cur["plus"].add(H(n))
        elif c == "-":
            n = norm(line[1:])
            if len(n) >= MIN_CHARS:
                cur["minus"].add(H(n))
        elif c in (" ", "\\") or line == "":
            pass
        else:
            in_hunk = False
    out = {}
    for s in secs:
        if s["path"] is None:
            continue
        o = out.setdefault(s["path"], {"plus": set(), "minus": set(), "n_plus_raw": 0})
        o["plus"] |= s["plus"]
        o["minus"] |= s["minus"]
        o["n_plus_raw"] += s["n_plus_raw"]
    return {p: {"plus": to_arr(v["plus"]), "minus": to_arr(v["minus"]), "n_plus_raw": v["n_plus_raw"]} for p, v in out.items()}, combined


# ------------------------------------------------------------------------------------------------------------- worker
def parse_session(task):
    sid, mode = task
    detail = mode == "detail"
    path = os.path.join(TRANS, sid + ".jsonl")
    with open(path, encoding="utf-8", errors="replace") as fh:
        events, bad = cc_jsonl.parse_lines(fh, "swechat", sid, "cc")
    calls, results, order = {}, {}, []
    first = last = None
    dup_calls = 0
    for ev in events:
        t = ep(ev["ts"])
        if t is not None:
            first = t if first is None or t < first else first
            last = t if last is None or t > last else last
        cid = ev["call_id"]
        if ev["kind"] == "call":
            if cid in calls:
                dup_calls += 1
                continue
            calls[cid] = (ev, t)
            order.append(cid)
        elif ev["kind"] == "result" and cid is not None and cid not in results:
            results[cid] = (ev, ep(ev["ts"]))
    muts, bashes, explain, keys = [], [], {}, set()
    loose_all = set()
    mpaths = []
    n_succ_added = 0
    tool_counts = collections.Counter()
    n_notebook = 0
    INF = float("inf")
    for cid in order:
        ev, t = calls[cid]
        raw = ev["tool_raw"]
        tool_counts[raw] += 1
        raw = ACP.get(raw, raw)
        res = results.get(cid)
        if res is None:
            status = "no_result"
        else:
            rev = res[0]
            try:
                mk = (json.loads(rev["extra"]) if rev["extra"] else {}).get("marker")
            except json.JSONDecodeError:
                mk = None
            status = "error" if (rev["native_error"] is True or mk in FAIL_MARKERS) else "ok"
        try:
            args = json.loads(ev["args"]) if ev["args"] else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        tt = t if t is not None else INF
        if raw in ("Edit", "MultiEdit", "Write"):
            fp = args.get("file_path") if isinstance(args.get("file_path"), str) else ""
            loose = set()
            edge = {}
            if raw == "Write":
                content = args.get("content") if isinstance(args.get("content"), str) else ""
                new = info_set(content)
                old, added, key, rtext = set(), set(new), [block_key("W", fp, content)], content
                loose.add(block_key("w", fp, content))
            else:
                edits = args.get("edits") if raw == "MultiEdit" else [args]
                edits = edits if isinstance(edits, list) else []
                new, old, added, key, rtext = set(), set(), set(), [], ""
                for e in edits:
                    if not isinstance(e, dict):
                        continue
                    o = e.get("old_string") if isinstance(e.get("old_string"), str) else ""
                    n = e.get("new_string") if isinstance(e.get("new_string"), str) else ""
                    so, sn = info_set(o), info_set(n)
                    old |= so
                    new |= sn
                    added |= (sn - so)
                    if detail:
                        parts = n.split("\n")
                        for ii, line in enumerate(parts):
                            nl = norm(line)
                            if len(nl) >= MIN_CHARS and (ii == 0 or ii == len(parts) - 1):
                                hh = H(nl)
                                if hh in sn and hh not in so:
                                    edge[hh] = nl
                    key.append(block_key("E", fp, o, n))
                    loose.add(block_key("e", fp, n))
                    rtext += n
            if detail:
                muts.append({"seq": ev["seq"], "tool": raw, "path": fp, "ts": t, "sub": bool(ev["is_subagent"]), "status": status,
                             "new": new, "old": old, "added": added, "redacted": bool(REDACT_RX.search(rtext)), "keys": key,
                             "edge": edge})
            if status == "ok":
                for h in new:
                    if tt < explain.get(h, INF) or h not in explain:
                        explain[h] = tt
                keys.update(key)
                loose_all |= loose
                n_succ_added += bool(added)
                mpaths.append((fp.replace("\\", "/"), t))
        elif raw == "NotebookEdit":
            n_notebook += 1
        elif ev["tool"] == "shell":
            cmd = ev["command"] if isinstance(ev["command"], str) else (args.get("command") if isinstance(args.get("command"), str) else "")
            for h in info_set(cmd):
                if tt < explain.get(h, INF) or h not in explain:
                    explain[h] = tt
            if detail:
                rtext = (res[0]["text"] if res else "") or ""
                claims = [(m.group("branch"), m.group("sha"), m.group("subj")) for m in COMMIT_RX.finditer(rtext)]
                logs = [m.group("sha") for m in LOG_RX.finditer(rtext)] if ("git log" in cmd or "git rev-parse" in cmd) else []
                bashes.append({"seq": ev["seq"], "ts": t, "rts": res[1] if res else None, "cmd": cmd[:20000], "claims": claims,
                               "logs": logs, "sub": bool(ev["is_subagent"]), "status": status})
    if mode == "keys":
        return {"sid": sid, "keys": to_arr(keys), "loose": to_arr(loose_all), "n_calls": len(order), "n_succ_added": n_succ_added,
                "mut_tools": {k: v for k, v in tool_counts.items() if "Edit" in k or "Write" in k}}
    hs = np.fromiter(explain.keys(), dtype=np.uint64, count=len(explain))
    ts = np.fromiter(explain.values(), dtype=np.float64, count=len(explain))
    o = np.argsort(hs)
    return {"mpaths": mpaths, "n_succ_added": n_succ_added, "sid": sid, "n_events": len(events), "bad_lines": bad, "first": first, "last": last, "dup_calls": dup_calls,
            "n_calls": len(order), "tool_counts": dict(tool_counts), "n_notebook": n_notebook,
            "muts": muts, "bashes": bashes, "ex_h": hs[o], "ex_t": ts[o], "keys": to_arr(keys), "loose": to_arr(loose_all)}


# ------------------------------------------------------------------------------------------------------------- stats helpers
def crate(df, num, den, unit="sid"):
    if len(df) == 0:
        return stats.cluster_rate([], [])
    g = pd.DataFrame({"u": df[unit].values, "n": np.asarray(num, dtype=float), "d": np.asarray(den, dtype=float)}).groupby("u")[["n", "d"]].sum()
    return stats.cluster_rate(g["n"].values, g["d"].values)


def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "rate": p, "lo": lo, "hi": hi}


def cq(values, units, qs=(0.5, 0.9)):
    return {f"q{q}": stats.cluster_quantile(values, units, q) for q in qs}


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    return o


def has_key(arr, k):
    if not len(arr):
        return False
    ix = np.searchsorted(arr, np.uint64(k))
    return bool(ix < len(arr) and arr[ix] == np.uint64(k))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


# ------------------------------------------------------------------------------------------------------------- main
def main():
    T0 = time.time()
    out = {"prereg": PREREG, "params": {"N_SAMPLE": N_SAMPLE, "TOL_S": TOL_S, "MIN_CHARS": MIN_CHARS, "SEED": stats.SEED,
                                        "N_BOOT": stats.N_BOOT, "DECOY_SIZE_FACTOR": DECOY_SIZE_FACTOR},
           "changes_after_first_run": CHANGES}

    # ---------------- metadata
    sess = pd.read_parquet(os.path.join(DATA, "sessions.parquet"),
                           columns=["session_id", "repo_id", "agent", "strategy", "checkpoint_ids", "created_at", "duration_seconds",
                                    "action_count"])
    sess["label"] = sess["agent"].map(label)
    cp = pd.read_parquet(os.path.join(DATA, "checkpoints.parquet"), columns=["checkpoint_pk", "session_pks", "strategy"])
    pf = pq.ParquetFile(os.path.join(DATA, "commits.parquet"))
    meta = pf.read(columns=["commit_sha", "checkpoint_pk", "repo_id", "commit_date", "author_date", "branch", "commit_message",
                            "status"]).to_pandas()
    meta["row"] = np.arange(len(meta))
    meta["cdate"] = meta["commit_date"].map(lambda x: x.timestamp() if pd.notna(x) else np.nan)
    meta["adate"] = meta["author_date"].map(lambda x: x.timestamp() if pd.notna(x) else np.nan)
    log("metadata", len(sess), len(cp), len(meta))

    cp_sessions = {pk: (json.loads(x) if isinstance(x, str) else []) for pk, x in zip(cp.checkpoint_pk, cp.session_pks)}
    sess_cps = collections.defaultdict(set)
    for pk, ss in cp_sessions.items():
        for s in ss:
            sess_cps[s].add(pk)
    n_disagree = 0
    for sid, x in zip(sess.session_id, sess.checkpoint_ids):
        lst = set(json.loads(x)) if isinstance(x, str) else set()
        if lst != sess_cps.get(sid, set()):
            n_disagree += 1
        sess_cps[sid] |= lst
    cp_ok_rows = collections.defaultdict(list)
    cp_nf = collections.Counter()
    for pk, st, row in zip(meta.checkpoint_pk, meta.status, meta.row):
        if st == "ok":
            cp_ok_rows[pk].append(row)
        else:
            cp_nf[pk] += 1
    sha_of = meta.commit_sha.values
    cdate = meta.cdate.values
    for pk in cp_ok_rows:  # (checkpoint, sha) rows in a fixed order
        cp_ok_rows[pk].sort()

    # ---------------- Q1 population coverage (metadata only, all scaffolds)
    log("sniffing formats")
    sess["has_file"] = sess.session_id.map(lambda s: os.path.exists(os.path.join(TRANS, s + ".jsonl")))
    sess["fmt"] = [sniff(os.path.join(TRANS, s + ".jsonl")) if hf else "missing" for s, hf in zip(sess.session_id, sess.has_file)]
    rows_of, n_ok, n_nf_cp = {}, {}, {}
    for sid in sess.session_id:
        rows = sorted({r for pk in sess_cps.get(sid, ()) for r in cp_ok_rows.get(pk, ())})
        rows_of[sid] = rows
        n_ok[sid] = len({sha_of[r] for r in rows})
        n_nf_cp[sid] = sum(1 for pk in sess_cps.get(sid, ()) if cp_nf.get(pk, 0) > 0)
    sess["n_ok_commits"] = sess.session_id.map(n_ok)
    sess["n_nf_cps"] = sess.session_id.map(n_nf_cp)
    sess["n_cps"] = sess.session_id.map(lambda s: len(sess_cps.get(s, ())))
    pop = sess[sess.has_file].copy()

    def cov_block(d):
        has = d.n_ok_commits > 0
        return {"n_sessions": int(len(d)), "with_linked_ok_commit": wil(has.sum(), len(d)),
                "with_only_commit_not_found": wil(((~has) & (d.n_nf_cps > 0)).sum(), len(d)),
                "with_no_checkpoint": int((d.n_cps == 0).sum()),
                "ok_commits_per_session_among_linked": stats.describe(d.loc[has, "n_ok_commits"].values),
                "action_count_total": float(d.action_count.fillna(0).sum()),
                "action_count_in_linked_sessions": float(d.loc[has, "action_count"].fillna(0).sum())}

    q1 = {"checkpoint_list_disagreements_sessions_vs_checkpoints": int(n_disagree),
          "sessions_table_rows": int(len(sess)), "sessions_without_transcript_file": int((~sess.has_file).sum()),
          "commit_rows": {"total": int(len(meta)), "ok": int((meta.status == "ok").sum()),
                          "commit_not_found": int((meta.status != "ok").sum()),
                          "ok_unique_sha": int(meta.loc[meta.status == "ok", "commit_sha"].nunique())},
          "checkpoints": {"total": int(len(cp)), "with_ok_commit": int(sum(1 for pk in cp.checkpoint_pk if cp_ok_rows.get(pk))),
                          "commit_not_found_only": int(sum(1 for pk in cp.checkpoint_pk if not cp_ok_rows.get(pk) and cp_nf.get(pk)))},
          "format_counts": pop.fmt.value_counts().to_dict(),
          "coverage_all": cov_block(pop),
          "coverage_by_label": {k: cov_block(d) for k, d in pop.groupby("label")},
          "coverage_by_format": {k: cov_block(d) for k, d in pop.groupby("fmt")},
          "coverage_by_strategy": {k: cov_block(d) for k, d in pop.groupby(pop.strategy.fillna("unknown"))}}

    # population time order from metadata: commit_date vs [created_at, created_at + duration_seconds]
    pos = collections.Counter()
    lag_after, lag_unit, lead_before, lead_unit = [], [], [], []
    linked_pop = pop[pop.n_ok_commits > 0]
    for sid, ca, du in zip(linked_pop.session_id, linked_pop.created_at, linked_pop.duration_seconds):
        if pd.isna(ca) or pd.isna(du):
            pos["no_span"] += len({sha_of[r] for r in rows_of[sid]})
            continue
        a = ca.timestamp()
        b = a + float(du)
        seen = set()
        for r in rows_of[sid]:
            if sha_of[r] in seen:
                continue
            seen.add(sha_of[r])
            c = cdate[r]
            if c < a - TOL_S:
                pos["before_start"] += 1
                lead_before.append((a - c) / 3600.0)
                lead_unit.append(sid)
            elif c <= b + TOL_S:
                pos["during"] += 1
            else:
                pos["after_end"] += 1
                lag_after.append((c - b) / 3600.0)
                lag_unit.append(sid)
    q1["time_order_metadata_population"] = {
        "basis": "sessions.created_at and created_at + duration_seconds vs commits.commit_date; (session, unique sha) pairs",
        "counts": dict(pos), "n_pairs": int(sum(pos.values())),
        "lag_after_end_hours": cq(lag_after, lag_unit), "lead_before_start_hours": cq(lead_before, lead_unit)}
    log("population coverage done", q1["coverage_all"]["with_linked_ok_commit"])

    # ---------------- sample
    elig = pop[(pop.fmt == "claude_code") & (pop.n_ok_commits > 0)].copy()
    rng = np.random.default_rng(stats.SEED)
    elig = elig.iloc[rng.permutation(len(elig))].reset_index(drop=True)
    sizes = elig.groupby("label").size().to_dict()
    alloc = _alloc(sizes, min(N_SAMPLE, len(elig)))
    sample_ids = []
    for lab, k in sorted(alloc.items()):
        sample_ids += elig.loc[elig.label == lab, "session_id"].head(k).tolist()
    sample_ids = sorted(sample_ids)
    S = set(sample_ids)
    srow = sess.set_index("session_id")
    out["sample"] = {"eligible_sessions": int(len(elig)), "eligible_by_label": {k: int(v) for k, v in sizes.items()},
                     "alloc": {k: int(v) for k, v in alloc.items()}, "n": len(sample_ids),
                     "by_strategy": collections.Counter(srow.loc[sample_ids, "strategy"].fillna("unknown")).most_common(),
                     "distinct_repos": int(srow.loc[sample_ids, "repo_id"].nunique()),
                     "max_sessions_one_repo": int(srow.loc[sample_ids, "repo_id"].value_counts().max())}
    # needed commit rows and explaining sessions
    need_rows = sorted({r for s in sample_ids for r in rows_of[s]})
    need_cps = sorted({meta.checkpoint_pk.values[r] for r in need_rows})
    explainers = sorted({s for pk in need_cps for s in cp_sessions.get(pk, [])})
    fmt_of = dict(zip(sess.session_id, sess.fmt))
    parse_ids = sorted(S | {s for s in explainers if fmt_of.get(s) == "claude_code"})
    out["sample"].update({"needed_commit_rows": len(need_rows), "needed_unique_sha": len({sha_of[r] for r in need_rows}),
                          "needed_checkpoints": len(need_cps), "explaining_sessions_listed": len(explainers),
                          "explaining_sessions_by_format": collections.Counter(fmt_of.get(s, "not_in_sessions_table") for s in explainers).most_common(),
                          "transcripts_parsed": len(parse_ids)})
    log("sample", len(sample_ids), "rows", len(need_rows), "parse", len(parse_ids))

    # ---------------- parse transcripts
    parsed = {}
    tasks = [(s, "detail" if s in S else "explain") for s in parse_ids]
    t1 = time.time()
    with Pool(N_PROC, maxtasksperchild=50) as pool:
        for i, r in enumerate(pool.imap_unordered(parse_session, tasks, chunksize=2)):
            parsed[r["sid"]] = r
            if (i + 1) % 100 == 0:
                log("parsed", i + 1, "/", len(tasks), round(time.time() - t1), "s")
    out["sample"]["parse_seconds"] = round(time.time() - t1, 1)
    rest = sorted(set(pop.loc[pop.fmt == "claude_code", "session_id"]) - set(parse_ids))
    gkeys, gloose, mut_tools = {}, {}, collections.Counter()
    census = {}
    for r in parsed.values():
        gkeys[r["sid"]], gloose[r["sid"]] = r["keys"], r["loose"]
        census[r["sid"]] = r["n_succ_added"]
    with Pool(N_PROC, maxtasksperchild=50) as pool:
        for r in pool.imap_unordered(parse_session, [(s, "keys") for s in rest], chunksize=4):
            gkeys[r["sid"]], gloose[r["sid"]] = r["keys"], r["loose"]
            census[r["sid"]] = r["n_succ_added"]
    cc_ids = sorted(set(pop.loc[pop.fmt == "claude_code", "session_id"]))
    linked_flag = {x: n_ok[x] > 0 for x in cc_ids}
    tot_all = sum(census.get(x, 0) for x in cc_ids)
    tot_linked = sum(census.get(x, 0) for x in cc_ids if linked_flag[x])
    out["mutation_stream_census"] = {
        "basis": "all sniffed claude_code transcripts; count of successful Edit/MultiEdit/Write calls (incl. ACP names) with a "
                 "non-empty informative added set (the Q2 denominator definition)",
        "sessions": len(cc_ids), "sessions_with_linked_ok_commit": int(sum(linked_flag.values())),
        "calls_all_sessions": int(tot_all), "calls_in_linked_sessions": int(tot_linked),
        "share_in_linked_sessions_session_cluster": stats.cluster_rate([census.get(x, 0) if linked_flag[x] else 0 for x in cc_ids],
                                                                       [census.get(x, 0) for x in cc_ids])}
    out["sample"]["global_key_pass_sessions"] = len(gkeys)
    for s in sample_ids:
        for k, v in parsed[s]["tool_counts"].items():
            if "Edit" in k or "Write" in k:
                mut_tools[k] += v
    out["sample"]["mutation_like_tool_counts_in_sample"] = dict(mut_tools.most_common())
    key_owner = collections.defaultdict(list)
    for s, arr in gkeys.items():
        for k in arr.tolist():
            key_owner[k].append(s)
    loose_owner = collections.defaultdict(list)
    for s, arr in gloose.items():
        for k in arr.tolist():
            loose_owner[k].append(s)
    del gkeys, gloose
    out["sample"]["bad_lines_total"] = int(sum(r["bad_lines"] for r in parsed.values()))
    out["sample"]["duplicate_call_ids_total"] = int(sum(r["dup_calls"] for r in parsed.values()))

    # ---------------- commits heavy columns for needed rows
    log("reading commit heavy columns")
    rg_off = np.cumsum([0] + [pf.metadata.row_group(i).num_rows for i in range(pf.metadata.num_row_groups)])
    need_set = set(need_rows)
    patch_files, combined_secs, attr, ac = {}, 0, {}, {}
    attr_counts = collections.Counter()
    for i in range(pf.metadata.num_row_groups):
        local = [r - rg_off[i] for r in need_rows if rg_off[i] <= r < rg_off[i + 1]]
        if not local:
            continue
        for col in ("patch", "file_attribution", "agent_changes"):
            vals = pf.read_row_group(i, columns=[col]).column(0).take(local).to_pylist()
            for lr, v in zip(local, vals):
                r = int(lr + rg_off[i])
                if col == "patch":
                    sha = sha_of[r]
                    if sha not in patch_files:
                        patch_files[sha], cmb = parse_patch(v)
                        combined_secs += cmb
                elif col == "file_attribution":
                    d = {}
                    try:
                        fa = json.loads(v) if v else {}
                    except json.JSONDecodeError:
                        fa = {}
                    for p, x in fa.items():
                        if not isinstance(x, dict) or x.get("attribution") is None:
                            continue
                        cv = x.get("committed_version")
                        d[p] = (x.get("attribution"), to_arr(info_set(cv)) if isinstance(cv, str) else None)
                        attr_counts[(x.get("attribution"), isinstance(cv, str))] += 1
                    attr[r] = d
                else:
                    try:
                        lst = json.loads(v) if v else []
                    except json.JSONDecodeError:
                        lst = []
                    ents = []
                    for e in lst if isinstance(lst, list) else []:
                        if not isinstance(e, dict):
                            continue
                        tn, fp = e.get("tool_name"), e.get("file_path") or ""
                        if "content" in e and "Write" in (tn or ""):
                            k = block_key("W", fp, e.get("content") or "")
                            kl = block_key("w", fp, e.get("content") or "")
                        else:
                            k = block_key("E", fp, e.get("old_string") or "", e.get("new_string") or "")
                            kl = block_key("e", fp, e.get("new_string") or "")
                        ents.append((tn, fp, k, kl))
                    ac[r] = ents
            del vals
        log("row group", i, "done")
    out["sample"]["combined_diff_sections_skipped"] = int(combined_secs)
    out["sample"]["file_attribution_entries_by_class_and_committed_version_present"] = {
        f"{a}|{b}": int(c) for (a, b), c in sorted(attr_counts.items(), key=lambda x: str(x[0]))}

    # decoy pools
    repo_of_row = meta.repo_id.values

    def ext(p):
        b = p.rsplit("/", 1)[-1]
        return b.rsplit(".", 1)[-1].lower() if "." in b else ""

    pool_plus, pool_state = collections.defaultdict(list), collections.defaultdict(list)
    seen_sha = set()
    for r in need_rows:
        sha = sha_of[r]
        if sha not in seen_sha:
            seen_sha.add(sha)
            for p, sec in patch_files.get(sha, {}).items():
                if len(sec["plus"]):
                    pool_plus[ext(p)].append((repo_of_row[r], len(sec["plus"]), sec["plus"]))
        for p, (a, cs) in attr.get(r, {}).items():
            if cs is not None and len(cs):
                pool_state[ext(p)].append((repo_of_row[r], len(cs), cs))
    pool_np = {}
    for name, pl in (("plus", pool_plus), ("state", pool_state)):
        allv = [x for v in pl.values() for x in v]
        pool_np[name] = {"by_ext": {e: (np.array([x[0] for x in v]), np.array([x[1] for x in v]), [x[2] for x in v]) for e, v in pl.items()},
                         "all": (np.array([x[0] for x in allv]), np.array([x[1] for x in allv]), [x[2] for x in allv])}
    drng = np.random.default_rng(stats.SEED + 1)
    decoy_fallback = collections.Counter()

    def decoy(name, repo, e, n):
        be = pool_np[name]["by_ext"].get(e)
        for lvl, tup in (("ext_size", be), ("ext", be), ("any", pool_np[name]["all"])):
            if tup is None or len(tup[0]) == 0:
                continue
            repos, ns, arrs = tup
            m = repos != repo
            if lvl == "ext_size":
                m &= (ns >= n / DECOY_SIZE_FACTOR) & (ns <= n * DECOY_SIZE_FACTOR)
            idx = np.flatnonzero(m)
            if len(idx):
                decoy_fallback[f"{name}:{lvl}"] += 1
                return arrs[int(drng.choice(idx))]
        decoy_fallback[f"{name}:none"] += 1
        return None

    # ---------------- Q2 per sampled session
    log("Q2")
    recs = []
    q1_sample_pos = collections.Counter()
    lagS, lagS_u = [], []
    commit_vs_author = collections.Counter()
    cat_none_detail = []
    cr_first, cr_u = [], []
    for sid in sample_ids:
        r = parsed[sid]
        repo = srow.at[sid, "repo_id"]
        ca = srow.at[sid, "created_at"]
        if r["first"] is not None and pd.notna(ca):
            cr_first.append((ca.timestamp() - r["first"]) / 3600.0)
            cr_u.append(sid)
        commits = {}
        for row in sorted(rows_of[sid], key=lambda x: (meta.checkpoint_pk.values[x], x)):
            sha = sha_of[row]
            if sha not in commits:
                commits[sha] = {"sha": sha, "row": row, "date": cdate[row], "files": patch_files.get(sha, {}), "attr": attr.get(row, {})}
        clist = sorted(commits.values(), key=lambda c: c["date"])
        # Q1 transcript-based time order
        for c in clist:
            commit_vs_author["equal" if meta.adate.values[c["row"]] == c["date"] else "differ"] += 1
            if r["first"] is None:
                q1_sample_pos["no_ts"] += 1
            elif c["date"] < r["first"] - TOL_S:
                q1_sample_pos["before_first_event"] += 1
            elif c["date"] <= r["last"] + TOL_S:
                q1_sample_pos["within_span"] += 1
            else:
                q1_sample_pos["after_last_event"] += 1
                lagS.append((c["date"] - r["last"]) / 3600.0)
                lagS_u.append(sid)
        pathset = set()
        for c in clist:
            pathset |= set(c["files"].keys())
        muts = r["muts"]
        for m in muts:
            m["f"] = None
            p = (m["path"] or "").replace("\\", "/")
            parts = p.split("/")
            for i in range(len(parts)):
                cand = "/".join(parts[i:])
                if cand and cand in pathset:
                    m["f"] = cand
                    break
        bashes = r["bashes"]
        allplus = [sec["plus"] for c in clist for sec in c["files"].values() if len(sec["plus"])]
        union_all = np.unique(np.concatenate(allplus)) if allplus else np.zeros(0, np.uint64)
        by_f = collections.defaultdict(list)
        for idx, m in enumerate(muts):
            if m["f"] is not None and m["status"] == "ok":
                by_f[m["f"]].append(idx)
        ac_keys = set(x[2] for row in rows_of[sid] for x in ac.get(row, []))
        for idx, m in enumerate(muts):
            base = {"sid": sid, "repo": repo, "tool": "Write" if m["tool"] == "Write" else "Edit", "sub": m["sub"], "path": m["path"],
                    "f": m["f"], "seq": m["seq"], "ts": m["ts"],
                    "status": m["status"], "redacted": m["redacted"], "n_added": len(m["added"]), "matched": m["f"] is not None}
            if m["status"] != "ok":
                recs.append({**base, "cat": "not_successful_" + m["status"]})
                continue
            if not m["added"]:
                recs.append({**base, "cat": "no_informative_added_lines"})
                continue
            # any trace anywhere in linked commits (path-agnostic)
            base["any_trace_any_file"] = n_in(m["added"], union_all) > 0
            if m["f"] is not None:
                base["in_agent_changes"] = any(k in ac_keys for k in m["keys"])
            if m["ts"] is None:
                recs.append({**base, "cat": "no_ts"})
                continue
            if m["f"] is None:
                recs.append({**base, "cat": "unconstrained_file_not_in_linked_commits"})
                continue
            K = [c for c in clist if m["f"] in c["files"] and c["date"] >= m["ts"] - TOL_S]
            if not K:
                recs.append({**base, "cat": "unconstrained_only_earlier_commits"})
                continue
            tgt = K[0]
            sup = set()
            for j in by_f[m["f"]]:
                m2 = muts[j]
                if j <= idx or m2["ts"] is None or m2["ts"] > tgt["date"] + TOL_S:
                    continue
                if m2["tool"] == "Write":
                    sup |= {h for h in m["added"] if h not in m2["new"]}
                else:
                    sup |= {h for h in m["added"] if h in m2["old"] and h not in m2["new"]}
            A2 = m["added"] - sup
            if not A2:
                recs.append({**base, "cat": "unconstrained_overwritten_later", "n_superseded": len(sup)})
                continue
            sec = tgt["files"][m["f"]]
            k_plus = n_in(A2, sec["plus"])
            union = np.unique(np.concatenate([c["files"][m["f"]]["plus"] for c in K]))
            k_union = n_in(A2, union)
            a_cls, cs = tgt["attr"].get(m["f"], ("missing", None))
            k_state = n_in(A2, cs) if cs is not None else None
            e = ext(m["f"])
            dp = decoy("plus", repo, e, len(sec["plus"]))
            ds = decoy("state", repo, e, len(cs)) if cs is not None else None
            rec = {**base, "cat": "constrained", "n_A2": len(A2), "n_superseded": len(sup), "k_plus": k_plus, "k_union": k_union,
                   "k_minus": n_in(A2, sec["minus"]), "tgt_sha": tgt["sha"], "tgt_date": tgt["date"],
                   "k_state": k_state, "attr": a_cls, "target_lag_h": (tgt["date"] - m["ts"]) / 3600.0,
                   "k_decoy_plus": n_in(A2, dp) if dp is not None else None,
                   "k_decoy_state": n_in(A2, ds) if ds is not None else None,
                   "n_later_commits_touching": len(K) - 1}
            if k_plus == 0:
                rec["edge_txt"] = [m["edge"][h] for h in A2 if h in m["edge"]]
                bn = m["f"].rsplit("/", 1)[-1]
                later_b = [b for b in bashes if b["seq"] > m["seq"] and b["ts"] is not None and b["ts"] <= tgt["date"] + TOL_S]
                rec["bash_could_explain"] = any(bn in b["cmd"] or any(kw in b["cmd"] for kw in BASH_EXPLAIN_KW) for b in later_b)
                fam = {"basename": any(bn in b["cmd"] for b in later_b)}
                for fname, kws in BASH_KW_FAMILIES.items():
                    fam[fname] = any(any(kw in b["cmd"] for kw in kws) for b in later_b)
                rec["bash_families"] = "|".join(k for k, v in fam.items() if v) or "none"
                others = [x for x in cp_sessions.get(meta.checkpoint_pk.values[tgt["row"]], []) if x != sid and x in parsed]
                rec["other_session_same_path"] = any(
                    (pth == m["f"] or pth.endswith("/" + m["f"])) and tt is not None and m["ts"] < tt <= tgt["date"] + TOL_S
                    for x in others for pth, tt in parsed[x]["mpaths"])
            recs.append(rec)
        # free detail
        r["muts"] = None
    R = pd.DataFrame(recs)
    for col, dflt in (("edge_txt", None), ("bash_could_explain", None), ("bash_families", None), ("other_session_same_path", None), ("k_state", None), ("k_decoy_plus", None), ("k_decoy_state", None),
                      ("any_trace_any_file", None), ("in_agent_changes", None), ("attr", None), ("n_A2", None), ("k_plus", None),
                      ("k_union", None), ("k_minus", None), ("target_lag_h", None)):
        if col not in R.columns:
            R[col] = dflt
    log("Q2 records", len(R))

    def cat3(k, n):
        return np.where(k >= n, "full", np.where(k > 0, "partial", "none"))

    q2 = {"mutation_calls_total": int(len(R)), "by_tool": R.tool.value_counts().to_dict(),
          "subagent_calls": int(R["sub"].sum()), "redacted_calls": int(R.redacted.sum()),
          "category_counts": {t: R[R.tool == t].cat.value_counts().to_dict() for t in ("Edit", "Write")}}
    succ = R[R.cat.isin(["no_ts", "unconstrained_file_not_in_linked_commits", "unconstrained_only_earlier_commits",
                         "unconstrained_overwritten_later", "constrained"])]
    q2["share_constrained_among_successful_with_added_lines"] = {
        t: {"session": crate(d, d.cat == "constrained", np.ones(len(d))), "repo": crate(d, d.cat == "constrained", np.ones(len(d)), "repo")}
        for t, d in (("all", succ), ("Edit", succ[succ.tool == "Edit"]), ("Write", succ[succ.tool == "Write"]))}
    q2["unconstrained_breakdown_rates"] = {
        c: crate(succ, succ.cat == c, np.ones(len(succ))) for c in ["unconstrained_file_not_in_linked_commits",
                                                                    "unconstrained_only_earlier_commits", "unconstrained_overwritten_later", "no_ts"]}
    q2["any_trace_any_file_among_successful_with_added_lines"] = {
        "session": crate(succ, succ.any_trace_any_file.fillna(False).astype(bool), np.ones(len(succ))),
        "repo": crate(succ, succ.any_trace_any_file.fillna(False).astype(bool), np.ones(len(succ)), "repo")}
    C = R[R.cat == "constrained"].copy()
    wit = {}
    for t in ("Edit", "Write"):
        d = C[C.tool == t]
        wt = {}
        for w, kcol in (("plus", "k_plus"), ("plus_union", "k_union"), ("state", "k_state"),
                        ("decoy_plus", "k_decoy_plus"), ("decoy_state", "k_decoy_state")):
            dd = d[d[kcol].notna()]
            if len(dd) == 0:
                wt[w] = {"n_calls": 0}
                continue
            c3 = cat3(dd[kcol].astype(float).values, dd.n_A2.values)
            wt[w] = {"n_calls": int(len(dd)), "n_sessions": int(dd.sid.nunique()),
                     "counts": collections.Counter(c3).most_common(),
                     "full": crate(dd, c3 == "full", np.ones(len(dd))),
                     "partial": crate(dd, c3 == "partial", np.ones(len(dd))),
                     "contradicted_looking": crate(dd, c3 == "none", np.ones(len(dd))),
                     "contradicted_looking_repo_cluster": crate(dd, c3 == "none", np.ones(len(dd)), "repo"),
                     "line_level_found": crate(dd, dd[kcol].astype(float).values, dd.n_A2.values)}
        wit[t] = wt
    q2["constrained_witness_outcomes"] = wit
    # contradicted-looking detail (primary witness: plus for Edit)
    E = C[C.tool == "Edit"]
    ne = E[E.k_plus == 0]
    q2["edit_contradicted_looking_plus_detail"] = {
        "n": int(len(ne)), "n_sessions": int(ne.sid.nunique()),
        "by_target_attribution": ne.attr.value_counts().to_dict(),
        "bash_could_explain": int(ne.bash_could_explain.fillna(False).astype(bool).sum()),
        "found_in_state_witness_any": int((ne.k_state.fillna(0) > 0).sum()),
        "state_witness_available": int(ne.k_state.notna().sum()),
        "found_in_later_commit_union": int((ne.k_union > 0).sum()),
        "found_in_target_minus_lines": int((ne.k_minus > 0).sum()),
        "redacted": int(ne.redacted.sum()), "subagent": int(ne["sub"].sum()),
        "n_A2_describe": stats.describe(ne.n_A2.values),
        "residual_after_flags": int(((ne.k_union == 0) & (ne.k_state.fillna(0) == 0) & ~ne.bash_could_explain.fillna(False).astype(bool)
                                     & ~ne.redacted.astype(bool)).sum()),
        "bash_family_combinations": ne.bash_families.value_counts().to_dict(),
        "other_session_same_path_before_commit": int(ne.other_session_same_path.fillna(False).astype(bool).sum()),
        "residual_by_target_attribution": ne[(ne.k_union == 0) & (ne.k_state.fillna(0) == 0)
                                             & ~ne.bash_could_explain.fillna(False).astype(bool)
                                             & ~ne.redacted.astype(bool)].attr.value_counts().to_dict(),
        "residual_also_without_other_session_same_path": int(((ne.k_union == 0) & (ne.k_state.fillna(0) == 0)
                                                              & ~ne.bash_could_explain.fillna(False).astype(bool) & ~ne.redacted.astype(bool)
                                                              & ~ne.other_session_same_path.fillna(False).astype(bool)).sum()),
        "residual_also_without_other_session_same_path_sessions": int(ne[(ne.k_union == 0) & (ne.k_state.fillna(0) == 0)
                                                                         & ~ne.bash_could_explain.fillna(False).astype(bool)
                                                                         & ~ne.redacted.astype(bool)
                                                                         & ~ne.other_session_same_path.fillna(False).astype(bool)].sid.nunique()),
        "redirect_copy_move_is_the_only_bash_family": int((ne.bash_families == "redirect_copy_move").sum()),
        "residual_after_flags_sessions": int(ne[(ne.k_union == 0) & (ne.k_state.fillna(0) == 0)
                                                & ~ne.bash_could_explain.fillna(False).astype(bool) & ~ne.redacted.astype(bool)].sid.nunique())}
    q2["edit_constrained_by_target_attribution"] = {
        a: {"n": int(len(d)), "contradicted_looking_plus": crate(d, d.k_plus == 0, np.ones(len(d)))} for a, d in E.groupby("attr")}
    q2["edit_constrained_subagent_vs_main"] = {
        ("subagent" if k else "main"): {"n": int(len(d)), "contradicted_looking_plus": crate(d, d.k_plus == 0, np.ones(len(d)))}
        for k, d in E.groupby("sub")}
    q2["target_lag_hours"] = cq(C.target_lag_h.values, C.sid.values)
    lab_of = srow["label"]
    q2["by_sample_stratum_label"] = {}
    for lab in sorted(set(lab_of.loc[sample_ids])):
        ids = set(x for x in sample_ids if lab_of.at[x] == lab)
        dsu, d = succ[succ.sid.isin(ids)], E[E.sid.isin(ids)]
        q2["by_sample_stratum_label"][lab] = {"sessions": len(ids), "successful_with_added": int(len(dsu)),
                                              "constrained": crate(dsu, dsu.cat == "constrained", np.ones(len(dsu))),
                                              "edit_contradicted_looking_plus": crate(d, d.k_plus == 0, np.ones(len(d)))}
    q2["decoy_fallback_levels"] = dict(decoy_fallback)
    q2["by_strategy"] = {}
    strat = srow["strategy"].fillna("unknown")
    for st in sorted(set(strat.loc[sample_ids])):
        ids = set(s for s in sample_ids if strat.at[s] == st)
        d = E[E.sid.isin(ids)]
        dsu = succ[succ.sid.isin(ids)]
        q2["by_strategy"][st] = {"sessions": len(ids), "successful_with_added": int(len(dsu)),
                                 "constrained": int((dsu.cat == "constrained").sum()),
                                 "edit_constrained": int(len(d)), "edit_contradicted_looking_plus": int((d.k_plus == 0).sum())}
    # ---- post-hoc sensitivity: edge lines as substrings of target '+' lines
    need_sec = collections.defaultdict(set)
    for sha, f, et in zip(ne.tgt_sha, ne.f, ne.edge_txt):
        if et is not None and len(et):
            need_sec[sha].add(f)
    plus_txt = {}
    if need_sec:
        import pyarrow as pa
        import pyarrow.compute as pcm
        for i in range(pf.metadata.num_row_groups):
            t = pf.read_row_group(i, columns=["commit_sha", "patch"])
            t = t.filter(pcm.is_in(t.column("commit_sha"), value_set=pa.array(sorted(need_sec))))
            for sha, ptxt in zip(t.column("commit_sha").to_pylist(), t.column("patch").to_pylist()):
                if sha in plus_txt:
                    continue
                cur, d = None, collections.defaultdict(list)
                for line in (ptxt or "").split("\n"):
                    if line.startswith("diff --git "):
                        cur = next((f for f in need_sec[sha] if line.endswith(" b/" + f) or line.endswith('/' + f + '"')), None)
                    elif cur is not None and line.startswith("+") and not line.startswith("+++ "):
                        d[cur].append(norm(line[1:]))
                plus_txt[sha] = d
            del t
    sub_found = []
    for sha, f, et in zip(ne.tgt_sha, ne.f, ne.edge_txt):
        lines = plus_txt.get(sha, {}).get(f, [])
        sub_found.append(bool(et is not None and len(et) and any(any(x in pl for pl in lines) for x in et)))
    ne = ne.assign(edge_sub_found=sub_found)
    resid_mask = ((ne.k_union == 0) & (ne.k_state.fillna(0) == 0) & ~ne.bash_could_explain.fillna(False).astype(bool)
                  & ~ne.redacted.astype(bool) & ~ne.other_session_same_path.fillna(False).astype(bool))
    Ee = E.assign(none_after=(E.k_plus == 0))
    Ee.loc[ne.index[ne.edge_sub_found.values], "none_after"] = False
    q2["edit_contradicted_looking_edge_substring_sensitivity_POSTHOC"] = {
        "n_contradicted_looking_plus": int(len(ne)),
        "with_edge_lines": int(sum(1 for x in ne.edge_txt if x is not None and len(x))),
        "edge_line_found_as_substring": int(ne.edge_sub_found.sum()),
        "contradicted_looking_after": crate(Ee, Ee.none_after, np.ones(len(Ee))),
        "residual_after_flags_and_other_session": int(resid_mask.sum()),
        "residual_after_flags_other_session_and_substring": int((resid_mask & ~ne.edge_sub_found).sum()),
        "residual_after_flags_other_session_and_substring_sessions": int(ne[resid_mask & ~ne.edge_sub_found].sid.nunique()),
        "residual_after_all_by_target_attribution": ne[resid_mask & ~ne.edge_sub_found].attr.value_counts().to_dict(),
        "residual_after_all_calls_per_session_top10": ne[resid_mask & ~ne.edge_sub_found].groupby("sid").size()
                                                      .sort_values(ascending=False).head(10).tolist()}
    Ee["ext"] = Ee.f.str.rsplit(".", n=1).str[-1].str.lower()
    top_ext = Ee.ext.value_counts().head(12).index.tolist()
    q2["edit_contradicted_looking_plus_by_extension_POSTHOC"] = {
        e: {"n": int((Ee.ext == e).sum()), "rate": crate(Ee[Ee.ext == e], Ee[Ee.ext == e].k_plus == 0, np.ones(int((Ee.ext == e).sum()))),
            "rate_after_edge_substring": crate(Ee[Ee.ext == e], Ee[Ee.ext == e].none_after, np.ones(int((Ee.ext == e).sum())))}
        for e in top_ext}
    wt = Ee.path.fillna("").str.contains(WT_RX)
    q2["edit_contradicted_looking_plus_by_worktree_path_POSTHOC"] = {
        lab: {"n": int(m.sum()), "rate": crate(Ee[m], Ee[m].k_plus == 0, np.ones(int(m.sum()))),
              "rate_after_edge_substring": crate(Ee[m], Ee[m].none_after, np.ones(int(m.sum())))}
        for lab, m in (("worktree_like", wt), ("other", ~wt))}
    sh = out["mutation_stream_census"]["calls_in_linked_sessions"] / max(out["mutation_stream_census"]["calls_all_sessions"], 1)
    cs = q2["share_constrained_among_successful_with_added_lines"]["all"]["session"]
    out["mutation_stream_census"]["constrained_share_of_all_cc_calls_point_and_scaled_ci"] = {
        "census_share_in_linked": sh, "sample_constrained_rate": cs["rate"],
        "product": (sh * cs["rate"]) if cs["rate"] is not None else None,
        "product_lo": (sh * cs["lo"]) if cs["lo"] is not None else None, "product_hi": (sh * cs["hi"]) if cs["hi"] is not None else None,
        "note": "census share treated as fixed (full census); CI is the sample cluster-bootstrap CI of the constrained rate scaled by it"}
    out["q2"] = q2

    q1["time_order_transcript_sample"] = {"basis": "first/last event ts of the parsed transcript vs commit_date; (session, unique sha)",
                                          "counts": dict(q1_sample_pos), "n_pairs": int(sum(q1_sample_pos.values())),
                                          "n_sessions": len(sample_ids),
                                          "lag_after_last_event_hours": cq(lagS, lagS_u),
                                          "commit_date_vs_author_date": dict(commit_vs_author),
                                          "created_at_minus_first_event_hours": {
                                              **cq(cr_first, cr_u, (0.05, 0.5, 0.95)),
                                              "n_negative_beyond_tol": int(sum(1 for x in cr_first if x < -TOL_S / 3600)),
                                              "n_positive_beyond_tol": int(sum(1 for x in cr_first if x > TOL_S / 3600)),
                                              "n": len(cr_first)}}
    out["q1"] = q1

    # ---------------- Q3 reverse
    log("Q3")
    unit_of_row = {}
    for s in sample_ids:
        for row in rows_of[s]:
            unit_of_row.setdefault(row, s)
    q3recs, acrecs = [], []
    repo_of_sess = dict(zip(sess.session_id, sess.repo_id))
    owners_of_row = {}
    for row in need_rows:
        own = set()
        for tn, fp, k, kl in ac.get(row, []):
            own.update(key_owner.get(k, []))
            own.update(loose_owner.get(kl, []))
        owners_of_row[row] = own
    extra_ids = sorted({o for v in owners_of_row.values() for o in v} - set(parsed))
    with Pool(N_PROC, maxtasksperchild=50) as pool:
        for r in pool.imap_unordered(parse_session, [(x, "explain") for x in extra_ids], chunksize=2):
            parsed[r["sid"]] = r
    q3_extra_parsed = len(extra_ids)
    incomplete_rows = 0
    for row in need_rows:
        pk = meta.checkpoint_pk.values[row]
        lst = cp_sessions.get(pk, [])
        ex = [parsed[s] for s in lst if s in parsed]
        complete = len(ex) == len(lst) and len(lst) > 0
        if not complete:
            incomplete_rows += 1
        sha = sha_of[row]
        cd = cdate[row]
        u = unit_of_row[row]
        rp = repo_of_row[row]
        for f, sec in patch_files.get(sha, {}).items():
            P = sec["plus"]
            if len(P) == 0:
                continue
            fa = np.zeros(len(P), bool)
            fb = np.zeros(len(P), bool)
            fB = np.zeros(len(P), bool)
            for x in [parsed[o] for o in owners_of_row[row] if o in parsed] + ex:
                hs = x["ex_h"]
                if len(hs) == 0:
                    continue
                ix = np.searchsorted(hs, P)
                ix[ix >= len(hs)] = 0
                fB |= hs[ix] == P
            for x in ex:
                hs, tt = x["ex_h"], x["ex_t"]
                if len(hs) == 0:
                    continue
                ix = np.searchsorted(hs, P)
                ix[ix >= len(hs)] = 0
                hit = hs[ix] == P
                fa |= hit
                fb |= hit & (tt[ix] <= cd + TOL_S)
            q3recs.append({"sid": u, "repo": rp, "row": row, "complete": complete, "attr": attr.get(row, {}).get(f, ("missing",))[0],
                           "n": len(P), "n_any": int(fa.sum()), "n_before": int(fb.sum()), "n_B": int(fB.sum())})
        keys = np.unique(np.concatenate([x["keys"] for x in ex])) if ex else np.zeros(0, np.uint64)
        lkeys = np.unique(np.concatenate([x["loose"] for x in ex])) if ex else np.zeros(0, np.uint64)
        lst_set = set(lst)
        for tn, fp, k, kl in ac.get(row, []):
            rec = {"sid": u, "repo": rp, "complete": complete, "tool": tn, "traced": has_key(keys, k),
                   "traced_loose": has_key(lkeys, kl)}
            if not rec["traced"]:
                own = key_owner.get(k, []) or loose_owner.get(kl, [])
                rec["global"] = ("listed" if any(o in lst_set for o in own) else
                                 "same_repo_other_session" if any(repo_of_sess.get(o) == rp for o in own) else
                                 "other_repo_session" if own else "nowhere")
                if rec["global"] == "other_repo_session":
                    rec["other_repo_same_owner"] = any(str(repo_of_sess.get(o) or "").split("/")[0] == str(rp).split("/")[0] for o in own)
                    rec["other_repo_same_name"] = any(str(repo_of_sess.get(o) or "").split("/")[-1] == str(rp).split("/")[-1] for o in own)
                    rec["other_repo_n_repos"] = len({repo_of_sess.get(o) for o in own})
                rec["path_in_listed_sessions"] = any(fp.replace("\\", "/") == pth for x in ex for pth, _ in x["mpaths"])
            acrecs.append(rec)
    Q3 = pd.DataFrame(q3recs)
    AC = pd.DataFrame(acrecs)
    q3 = {"commit_rows": len(need_rows), "rows_explainers_incomplete": int(incomplete_rows),
          "variantB_extra_sessions_parsed": q3_extra_parsed,
          "rows_with_agent_changes_owner_outside_listed": int(sum(1 for row in need_rows
                                                                 if owners_of_row[row] - set(cp_sessions.get(meta.checkpoint_pk.values[row], [])))),
          "file_sections": int(len(Q3)), "file_sections_complete": int(Q3.complete.sum()) if len(Q3) else 0}
    Qc = Q3[Q3.complete] if len(Q3) else Q3
    q3["plus_lines_by_attribution"] = {}
    for a, d in Qc.groupby("attr"):
        unexpl = d.n - d.n_any
        q3["plus_lines_by_attribution"][a] = {
            "file_sections": int(len(d)), "rows": int(d.row.nunique()), "plus_lines": int(d.n.sum()),
            "unexplained_any_time": crate(d, unexpl, d.n), "unexplained_any_time_repo_cluster": crate(d, unexpl, d.n, "repo"),
            "explained_only_by_calls_after_commit": crate(d, d.n_any - d.n_before, d.n),
            "files_with_zero_explained": crate(d, (d.n_any == 0), np.ones(len(d))),
            "files_with_zero_explained_count": int((d.n_any == 0).sum()),
            "variantB_unexplained_any_time": crate(d, d.n - d.n_B, d.n),
            "variantB_files_with_zero_explained_count": int((d.n_B == 0).sum())}
    if len(AC):
        ACc = AC[AC.complete]
        q3["agent_changes_traceability"] = {
            "entries": int(len(AC)), "entries_complete_rows": int(len(ACc)),
            "traced_rate": crate(ACc, ACc.traced, np.ones(len(ACc))),
            "untraced_full_key_but_traced_loose_key": int((~ACc.traced & ACc.traced_loose).sum()),
            "untraced_both_keys": int((~ACc.traced & ~ACc.traced_loose).sum()),
            "untraced_global_location": ACc.loc[~ACc.traced, "global"].value_counts().to_dict() if "global" in ACc else {},
            "untraced_other_repo_same_github_owner": int(ACc.get("other_repo_same_owner", pd.Series(dtype=object)).fillna(False).astype(bool).sum()),
            "untraced_other_repo_same_repo_name": int(ACc.get("other_repo_same_name", pd.Series(dtype=object)).fillna(False).astype(bool).sum()),
            "untraced_other_repo_owner_session_repos_describe": stats.describe(ACc.get("other_repo_n_repos", pd.Series(dtype=float)).dropna().values),
            "untraced_nowhere_sessions": int(ACc.loc[~ACc.traced & (ACc.get("global") == "nowhere"), "sid"].nunique()) if "global" in ACc else 0,
            "untraced_nowhere_path_seen_in_listed_sessions": int((~ACc.traced & (ACc.get("global") == "nowhere")
                                                                  & ACc.get("path_in_listed_sessions").fillna(False).astype(bool)).sum())
            if "global" in ACc else 0,
            "by_tool": {t: crate(d, d.traced, np.ones(len(d))) for t, d in ACc.groupby("tool")}}
    # forward: sampled sessions' successful Edit/Write calls on committed paths -> present in agent_changes of linked rows?
    fw = R[R.in_agent_changes.notna()]
    q3["forward_successful_calls_on_committed_paths_in_agent_changes"] = {
        t: crate(d, d.in_agent_changes.astype(bool), np.ones(len(d))) for t, d in (("all", fw), ("Edit", fw[fw.tool == "Edit"]),
                                                                                    ("Write", fw[fw.tool == "Write"]))}
    out["q3"] = q3

    # ---------------- Q4 hash claims
    log("Q4")
    ok = meta[meta.status == "ok"]
    all_shas = sorted(set(ok.commit_sha))
    repo_shas = {rp: sorted(set(d.commit_sha)) for rp, d in ok.groupby("repo_id")}
    first_row_of_sha = {}
    for sha, row in zip(ok.commit_sha, ok.row):
        first_row_of_sha.setdefault(sha, row)

    def pref(lst, s):
        i = bisect.bisect_left(lst, s)
        return lst[i] if i < len(lst) and lst[i].startswith(s) else None

    def subj_of(row):
        return norm((meta.commit_message.values[row] or "").split("\n", 1)[0])
    repo_subj = collections.defaultdict(set)
    for rp, row in zip(ok.repo_id, ok.row):
        repo_subj[rp].add(subj_of(row))
    crec, lrec = [], []
    agent_made = []
    for sid in sample_ids:
        r = parsed[sid]
        repo = srow.at[sid, "repo_id"]
        linked = sorted({sha_of[x] for x in rows_of[sid]})
        linked_subj = {subj_of(x) for x in rows_of[sid]}
        rs = repo_shas.get(repo, [])
        seen = set()
        matched_linked = set()
        bashes = r["bashes"]
        for bi, b in enumerate(bashes):
            for br, sh, subj in b["claims"]:
                if sh in seen:
                    continue
                seen.add(sh)
                hit = pref(linked, sh)
                lvl = "linked" if hit else None
                if hit is None:
                    hit = pref(rs, sh)
                    lvl = "same_repo" if hit else None
                if hit is None:
                    hit = pref(all_shas, sh)
                    lvl = "other_repo" if hit else "none"
                rec = {"sid": sid, "level": lvl, "sub": b["sub"], "has_git_commit_cmd": "git commit" in b["cmd"], "len": len(sh)}
                if hit is not None:
                    row = first_row_of_sha[hit]
                    c = cdate[row]
                    rec["in_window"] = (b["ts"] is not None and b["rts"] is not None and b["ts"] - TOL_S <= c <= b["rts"] + TOL_S)
                    rec["dt_call_s"] = (c - b["ts"]) if b["ts"] is not None else None
                    rec["author_in_window"] = (b["ts"] is not None and b["rts"] is not None
                                               and b["ts"] - TOL_S <= meta.adate.values[row] <= b["rts"] + TOL_S)
                    rec["branch_eq"] = (br.strip() == (meta.branch.values[row] or "").strip())
                    msg = meta.commit_message.values[row] or ""
                    rec["subject_eq"] = norm(subj) == norm(msg.split("\n", 1)[0])
                    if lvl == "linked":
                        matched_linked.add(hit)
                else:
                    rec["later_rewrite_cmd"] = any(any(kw in b2["cmd"] for kw in REWRITE_KW) for b2 in bashes[bi:])
                    ns = norm(subj)
                    rec["subject_in_linked"] = bool(ns) and ns in linked_subj
                    rec["subject_in_repo"] = bool(ns) and ns in repo_subj.get(repo, set())
                    rec["session_has_not_found_cp"] = bool(srow.at[sid, "n_nf_cps"] > 0)
                crec.append(rec)
            if b["logs"]:
                for sh in set(b["logs"]):
                    lvl = "linked" if pref(linked, sh) else ("same_repo" if pref(rs, sh) else ("other_repo" if pref(all_shas, sh) else "none"))
                    lrec.append({"sid": sid, "level": lvl, "len": len(sh)})
        agent_made.append({"sid": sid, "linked": len(linked), "agent_made": len(matched_linked)})
    CR, LR, AM = pd.DataFrame(crec), pd.DataFrame(lrec), pd.DataFrame(agent_made)
    q4 = {"sessions": len(sample_ids)}
    if len(CR):
        q4["commit_claims"] = {"n": int(len(CR)), "sessions_with_claims": int(CR.sid.nunique()),
                               "level_counts": CR.level.value_counts().to_dict(),
                               "matched_linked": crate(CR, CR.level == "linked", np.ones(len(CR))),
                               "matched_same_repo_any": crate(CR, CR.level.isin(["linked", "same_repo"]), np.ones(len(CR))),
                               "matched_other_repo": int((CR.level == "other_repo").sum()),
                               "unmatched": crate(CR, CR.level == "none", np.ones(len(CR))),
                               "claims_from_subagent": int(CR["sub"].sum()),
                               "claims_whose_command_contains_git_commit": int(CR.has_git_commit_cmd.sum()),
                               "sha_length_counts": CR["len"].value_counts().to_dict()}
        M = CR[CR.level.isin(["linked", "same_repo"])]
        if len(M):
            q4["commit_claims"]["matched_checks"] = {
                "n": int(len(M)),
                "commit_date_in_call_window": crate(M, M.in_window.astype(bool), np.ones(len(M))),
                "author_date_in_call_window": crate(M, M.author_in_window.astype(bool), np.ones(len(M))),
                "branch_equal": crate(M, M.branch_eq.astype(bool), np.ones(len(M))),
                "subject_equal": crate(M, M.subject_eq.astype(bool), np.ones(len(M))),
                "dt_commit_minus_call_s": cq(M.dt_call_s.dropna().values, M.loc[M.dt_call_s.notna(), "sid"].values, (0.05, 0.5, 0.95)),
                "out_of_window_dt_s": sorted(round(float(x), 1) for x in M.loc[~M.in_window.astype(bool), "dt_call_s"].dropna()),
                "out_of_window_sessions": int(M.loc[~M.in_window.astype(bool), "sid"].nunique()),
                "out_of_window_command_contains_git_commit": int(M.loc[~M.in_window.astype(bool), "has_git_commit_cmd"].astype(bool).sum())}
        U = CR[CR.level == "none"]
        q4["commit_claims"]["unmatched_flags"] = {"n": int(len(U)),
                                                  "later_rewrite_cmd": int(U.later_rewrite_cmd.fillna(False).astype(bool).sum()),
                                                  "session_has_not_found_checkpoint": int(U.session_has_not_found_cp.fillna(False).astype(bool).sum()),
                                                  "subject_equals_a_linked_commit_subject": int(U.subject_in_linked.fillna(False).astype(bool).sum()),
                                                  "subject_equals_a_same_repo_commit_subject": int(U.subject_in_repo.fillna(False).astype(bool).sum()),
                                                  "no_flag_and_no_subject_match": int((~U.later_rewrite_cmd.fillna(False).astype(bool)
                                                                                       & ~U.session_has_not_found_cp.fillna(False).astype(bool)
                                                                                       & ~U.subject_in_repo.fillna(False).astype(bool)).sum()),
                                                  "neither_flag": int((~U.later_rewrite_cmd.fillna(False).astype(bool)
                                                                       & ~U.session_has_not_found_cp.fillna(False).astype(bool)).sum())}
    else:
        q4["commit_claims"] = {"n": 0}
    if len(LR):
        q4["log_claims"] = {"n": int(len(LR)), "sessions": int(LR.sid.nunique()), "level_counts": LR.level.value_counts().to_dict(),
                            "matched_same_repo_any": crate(LR, LR.level.isin(["linked", "same_repo"]), np.ones(len(LR))),
                            "full_40_hex": int((LR["len"] == 40).sum())}
    q4["linked_commits_made_by_agent_bash"] = {"linked_commit_session_pairs": int(AM.linked.sum()), "matched_to_agent_claim": int(AM.agent_made.sum()),
                                               "rate": crate(AM, AM.agent_made.values, AM.linked.values)}
    out["q4"] = q4

    try:
        import psutil
        mi = psutil.Process().memory_info()
        rss = {"rss_gb_main_end": round(mi.rss / 1e9, 2), "peak_wset_gb_main": round(getattr(mi, "peak_wset", 0) / 1e9, 2)}
    except Exception:
        rss = {}
    if os.environ.get("CW_DUMP"):
        R.drop(columns=[c for c in ("keys",) if c in R.columns]).to_parquet(os.path.join(os.environ["CW_DUMP"], "cw_calls.parquet"))
        if len(CR):
            CR.to_parquet(os.path.join(os.environ["CW_DUMP"], "cw_claims.parquet"))
    out["run"] = {"seconds": round(time.time() - T0, 1), "python": sys.version.split()[0], "n_proc": N_PROC, **rss}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(clean(out), fh, indent=1, default=str)
    log("wrote", OUT, out["run"])


if __name__ == "__main__":
    main()
