"""Phase E (WA1) independent verification of the E-split IR caches (analysis/cache/{swechat,aiv_cu}_E.parquet).

Counts only; no interpretation is written to the JSON. Independent of the loaders: nothing is imported from
analysis/loaders; raw transcripts are re-parsed here with deliberately minimal code.

Checks
  1. Split membership. Session ids present in each E cache (session_id column only) vs the "E" list of
     analysis/cache/samples/<corpus>_EH.json: equal / missing / extra. The "H" list is read as a set of id strings only
     (no H transcript, row or cache is opened): sha256 of "\n".join(H) must equal HELDOUT_MANIFEST.json, and the cache ids,
     the E list, A and B must be disjoint from it. n_E in the manifest == len(E). No *_H*.parquet in analysis/cache.
     Each E session missing from the swechat cache: raw bytes, lines, lines that parse as JSON, whole file parses.
     Locator for the E claude_code bad line(s) the loader reports (strict json.loads and non-strict multi-object decode
     both fail), and whether any cache result with no matching call (orphan) has its id inside such a line.
  2. Hashes. sha256 of the A/B caches vs (a) the pre-edit snapshot analysis/out/phase_e/e_cache_hashes_pre.json and
     (b) the earlier, independently committed records (A: analysis/prereg.json, B: analysis/out/probe_2.json and
     probe_3.json); the sample/manifest files vs their git HEAD blobs; the E caches vs analysis/out/phase_e/e_cache_build.json.
  3. Raw re-parse, 3 E sessions per corpus, chosen by a seeded draw (SEED) from the population tables (never from the cache
     under test): swechat one claude_code, one opencode, one codex session with population length in [LEN_LO, LEN_HI];
     aiv_cu one anthropic-sonnet, one openai-responses, one gemini-pro session with n_turns in [TURN_LO, TURN_HI].
     Supplementary (labelled): aiv_cu one compat-chat and one anthropic-claude-code (Agent-SDK) session drawn the same way;
     swechat the first (sorted) E session whose cache holds a result with no matching call (targeted at that anomaly).
     Minimal parsers:
       claude_code  JSONL; `assistant` lines: message.content blocks type tool_use -> call id; `user` lines: blocks type
                    tool_result -> tool_use_id. Blocks of isSidechain lines and blocks nested in `progress`
                    data.message.message.content are the subagent set, compared with the cache's is_subagent events.
       codex        JSONL; response_item payload types function_call / custom_tool_call / local_shell_call -> call_id
                    (calls); function_call_output / custom_tool_call_output -> call_id (results).
       opencode     one JSON document; messages[].parts[] type tool -> callID (call); a result when state.status is
                    completed or error.
       aiv_cu       computer_use_turns.jsonl.gz (one row = one turn; rows of the chosen sessions only, session_id field
                    re-checked after parsing). Synthetic bootstrap turn: Anthropic msg id all zeros, chat tool-call id all
                    zeros, Responses empty item list, or a Gemini message with no responseId and no usageMetadata.
                    Expected: one call + one result per non-synthetic row with agent_action not null, uuid = row id.
                    Expected call_id: the row's single provider call id when the row has exactly one, it is not all
                    zeros and no other row of the session carries it ("unambiguous"); 'turn:'+row id when the row has no
                    provider call id; otherwise one of the row's provider ids or 'turn:'+row id (membership only).
                    Result text == raw output, stderr == raw error, ts == created_at (parsed, UTC).
     Compared with the cache: call and result counts, call_id multisets, per-call tool_raw (swechat).

Writes analysis/out/phase_e/e_cache_verify.json.
Run:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_cache_verify
"""
import collections
import hashlib
import json
import os
import random
import re
import subprocess
import time
import zlib

import pandas as pd
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AN = os.path.join(ROOT, "analysis")
CACHE = os.path.join(AN, "cache")
SAMP = os.path.join(CACHE, "samples")
OUTD = os.path.join(AN, "out", "phase_e")
OUT = os.path.join(OUTD, "e_cache_verify.json")
SWE_TRANS = "C:/Swarms/data/swe-chat-pinned/transcripts"
AIV_TURNS = "C:/Swarms/data/ai-village/computer_use_turns.jsonl.gz"
SEED = 20261004
LEN_LO, LEN_HI = 50, 1500
TURN_LO, TURN_HI = 15, 200
SWE_FORMATS = ["claude_code", "opencode", "codex"]
AIV_PRIMARY = ["anthropic-sonnet", "openai-responses", "gemini-pro"]
AIV_SUPP = ["compat-chat", "anthropic-claude-code"]
ZERO_MSG = re.compile(r"^msg_0+$")
ZERO_CALL = re.compile(r"^(?:call_|toolu_)?0+$")
BAD_LINES = {}  # swechat E claude_code session -> its undecodable lines (kept in memory only, never written)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def git_unchanged_vs_head(rel):
    """git blob id of the working file (hash-object applies the same clean/autocrlf filter as `git add`) == HEAD's blob."""
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, check=True, text=True).stdout.strip()
    return git("hash-object", rel) == git("rev-parse", f"HEAD:{rel}")


def cache_session_ids(path):
    pf = pq.ParquetFile(path)
    ids = set()
    for g in range(pf.num_row_groups):
        ids |= set(pf.read_row_group(g, columns=["session_id"]).column("session_id").to_pylist())
    return ids


def cache_session(path, sid, cols):
    return pd.read_parquet(path, columns=cols, filters=[("session_id", "==", sid)])


def multiset_cmp(raw, cache):
    r, c = collections.Counter(raw), collections.Counter(cache)
    only_r, only_c = r - c, c - r
    return {"n_raw": sum(r.values()), "n_cache": sum(c.values()), "equal": r == c,
            "only_in_raw": sum(only_r.values()), "only_in_cache": sum(only_c.values()),
            "only_in_raw_ids_first5": sorted(only_r)[:5], "only_in_cache_ids_first5": sorted(only_c)[:5],
            "raw_duplicate_ids": sum(v - 1 for v in r.values() if v > 1)}


# ------------------------------------------------------------------------------------------------ 1+2: ids and hashes

def split_checks():
    man = json.load(open(os.path.join(AN, "HELDOUT_MANIFEST.json"), encoding="utf-8"))
    res = {}
    for c in ("swechat", "aiv_cu"):
        eh = json.load(open(os.path.join(SAMP, f"{c}_EH.json"), encoding="utf-8"))
        ab = json.load(open(os.path.join(SAMP, f"{c}.json"), encoding="utf-8"))
        E, H = list(eh["E"]), set(eh["H"])  # H: id strings only, never printed, never opened
        A, B = set(ab["A"]), set(ab["B"])
        h_sha = hashlib.sha256("\n".join(eh["H"]).encode()).hexdigest()
        ids = cache_session_ids(os.path.join(CACHE, f"{c}_E.parquet"))
        res[c] = {
            "E_list_len": len(E), "E_list_distinct": len(set(E)), "manifest_n_E": man["corpora"][c]["n_E"],
            "manifest_n_E_equals_E_list": man["corpora"][c]["n_E"] == len(E),
            "H_ids_sha256_equals_manifest": h_sha == man["corpora"][c]["sha256_sorted_H_ids"],
            "H_list_len": len(H), "manifest_n_H": man["corpora"][c]["n_H"],
            "cache_sessions": len(ids),
            "cache_ids_equal_E_list": ids == set(E),
            "E_list_missing_from_cache": sorted(set(E) - ids),
            "cache_ids_not_in_E_list": len(ids - set(E)),
            "cache_ids_in_H": len(ids & H), "cache_ids_in_A": len(ids & A), "cache_ids_in_B": len(ids & B),
            "E_list_in_H": len(set(E) & H), "E_list_in_A": len(set(E) & A), "E_list_in_B": len(set(E) & B),
        }
    res["h_cache_files_present"] = sorted(f for f in os.listdir(CACHE) if re.search(r"_H[._]", f))
    # E sessions missing from the swechat cache: is the raw transcript really event-free? (E data only)
    res["swechat_missing_E_raw"] = {}
    for sid in res["swechat"]["E_list_missing_from_cache"]:
        path = os.path.join(SWE_TRANS, sid + ".jsonl")
        raw = open(path, "rb").read()
        text = raw.decode("utf-8", errors="replace")
        lines = [l for l in text.splitlines() if l.strip()]

        def ok(s):
            try:
                json.loads(s)
                return True
            except ValueError:
                return False
        types = collections.Counter(json.loads(l).get("type") if ok(l) and isinstance(json.loads(l), dict) else None
                                    for l in lines)
        res["swechat_missing_E_raw"][sid] = {"bytes": len(raw), "nonblank_lines": len(lines),
                                             "lines_parsing_as_json": sum(ok(l) for l in lines),
                                             "whole_file_parses_as_json": ok(text),
                                             "line_types": {str(k): v for k, v in types.items()}}
    # where is the E claude_code "bad line" (swechat_E_build.json per_format_E.claude_code.parse.bad_lines)?
    # A line is bad here when json.loads fails and a non-strict raw_decode of consecutive objects also fails.
    e_ids = json.load(open(os.path.join(SAMP, "swechat_EH.json"), encoding="utf-8"))["E"]
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"],
                          filters=[("session_id", "in", e_ids)])
    dec = json.JSONDecoder(strict=False)
    bad = collections.Counter()
    t = time.time()
    for sid in sorted(pop.session_id[pop.format == "claude_code"]):
        text = open(os.path.join(SWE_TRANS, sid + ".jsonl"), "rb").read().decode("utf-8", errors="replace")
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
                continue
            except ValueError:
                pass
            pos, n, good = 0, len(line), True
            try:
                while pos < n:
                    _, pos = dec.raw_decode(line, pos)
                    while pos < n and line[pos] in " \t\r":
                        pos += 1
            except ValueError:
                good = False
            if not good:
                bad[sid] += 1
                BAD_LINES.setdefault(sid, []).append(line)
    res["swechat_E_claude_code_bad_lines"] = {"files_scanned": int((pop.format == "claude_code").sum()),
                                              "bad_lines": sum(bad.values()), "sessions": dict(bad),
                                              "wall_s": round(time.time() - t, 1)}
    return res


def hash_checks():
    pre = json.load(open(os.path.join(OUTD, "e_cache_hashes_pre.json"), encoding="utf-8"))["snapshot"]
    prereg = json.load(open(os.path.join(AN, "prereg.json"), encoding="utf-8"))
    flat = {}

    def walk(o):  # collect every "analysis/cache/..parquet": sha pair recorded anywhere in prereg.json
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and k.startswith("analysis/cache/") and isinstance(v, str) and len(v) == 64:
                    flat[k] = v
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(prereg)
    b_rec = {}
    for p in ("analysis/out/probe_2.json", "analysis/out/probe_3.json"):
        b_rec[p] = json.load(open(os.path.join(ROOT, p), encoding="utf-8")).get("inputs_sha256", {})
    out = {"A_B_caches": {}, "committed_files_vs_git_HEAD": {}, "E_caches_vs_build_report": {}}
    for rel in ("analysis/cache/swechat_A.parquet", "analysis/cache/swechat_B.parquet",
                "analysis/cache/aiv_cu_A.parquet", "analysis/cache/aiv_cu_B.parquet"):
        now = sha256_file(os.path.join(ROOT, rel))
        rec = {"sha256_now": now, "equals_pre_edit_snapshot": now == pre[rel]["sha256"]}
        if rel.endswith("_A.parquet"):
            rec["equals_prereg_json_record"] = (now == flat[rel]) if rel in flat else None
        else:
            rec["equals_committed_probe_records"] = {p: (now == r[rel]) if rel in r else None for p, r in b_rec.items()}
        out["A_B_caches"][rel] = rec
    for rel in ("analysis/cache/samples/swechat.json", "analysis/cache/samples/aiv_cu.json",
                "analysis/cache/samples/swechat_EH.json", "analysis/cache/samples/aiv_cu_EH.json",
                "analysis/HELDOUT_MANIFEST.json", "analysis/prereg.json", "analysis/out/probe_2.json",
                "analysis/out/probe_3.json"):
        out["committed_files_vs_git_HEAD"][rel] = git_unchanged_vs_head(rel)
    build = json.load(open(os.path.join(OUTD, "e_cache_build.json"), encoding="utf-8"))
    for c in ("swechat", "aiv_cu"):
        now = sha256_file(os.path.join(CACHE, f"{c}_E.parquet"))
        out["E_caches_vs_build_report"][c] = {"sha256_now": now, "equals_build_report": now == build["corpora"][c]["sha256"]}
    return out


# ----------------------------------------------------------------------------------------------- 3a: swechat re-parse

def swe_raw(sid, fmt):
    path = os.path.join(SWE_TRANS, sid + ".jsonl")
    text = open(path, encoding="utf-8", errors="replace").read()
    calls, results, names, other = [], [], {}, collections.Counter()
    sub_calls, sub_results = [], []  # claude_code: blocks of isSidechain lines and blocks nested in progress messages
    if fmt == "opencode":
        doc = json.loads(text)
        for m in doc.get("messages") or []:
            for p in m.get("parts") or []:
                if p.get("type") != "tool":
                    continue
                calls.append(p["callID"])
                names[p["callID"]] = p.get("tool")
                if (p.get("state") or {}).get("status") in ("completed", "error"):
                    results.append(p["callID"])
                else:
                    other["tool_part_status_" + str((p.get("state") or {}).get("status"))] += 1
        return calls, results, names, other, sub_calls, sub_results
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            other["unparseable_line"] += 1
            continue
        if fmt == "claude_code":
            t = d.get("type")
            if t in ("assistant", "user"):
                content = (d.get("message") or {}).get("content")
                side = bool(d.get("isSidechain"))
                for b in content if isinstance(content, list) else []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        (sub_calls if side else calls).append(b["id"])
                        names[b["id"]] = b.get("name")
                    elif b.get("type") == "tool_result":
                        (sub_results if side else results).append(b["tool_use_id"])
                    elif b.get("type") not in ("text", "thinking", "redacted_thinking", "image"):
                        other["block_" + str(b.get("type"))] += 1
            elif t == "progress":
                m = ((d.get("data") or {}).get("message") or {})
                mm = m.get("message") if isinstance(m, dict) else None
                content = mm.get("content") if isinstance(mm, dict) else None
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        sub_calls.append(b["id"])
                        names[b["id"]] = b.get("name")
                    elif isinstance(b, dict) and b.get("type") == "tool_result":
                        sub_results.append(b["tool_use_id"])
        elif fmt == "codex":
            if d.get("type") != "response_item":
                continue
            p = d.get("payload") or {}
            pt = p.get("type")
            if pt in ("function_call", "custom_tool_call", "local_shell_call"):
                calls.append(p.get("call_id"))
                names[p.get("call_id")] = p.get("name")
            elif pt in ("function_call_output", "custom_tool_call_output"):
                results.append(p.get("call_id"))
            elif "call_id" in p:
                other["response_item_with_call_id_" + str(pt)] += 1
    return calls, results, names, other, sub_calls, sub_results


def swe_verify(sid, fmt, role):
    calls, results, names, other, sub_calls, sub_results = swe_raw(sid, fmt)
    df = cache_session(os.path.join(CACHE, "swechat_E.parquet"), sid, ["kind", "call_id", "tool_raw", "is_subagent"])
    df["sub"] = df.is_subagent.fillna(False).astype(bool)
    cc = df[df.kind == "call"]
    cr = df[df.kind == "result"]
    cache_names = dict(zip(cc.call_id, cc.tool_raw))
    common = set(names) & set(cache_names)
    return {"session_id": sid, "format": fmt, "role": role,
            "calls_all": multiset_cmp(calls + sub_calls, cc.call_id.tolist()),
            "results_all": multiset_cmp(results + sub_results, cr.call_id.tolist()),
            "calls_main_vs_cache_not_subagent": multiset_cmp(calls, cc[~cc["sub"]].call_id.tolist()),
            "results_main_vs_cache_not_subagent": multiset_cmp(results, cr[~cr["sub"]].call_id.tolist()),
            "calls_subagent_vs_cache_subagent": multiset_cmp(sub_calls, cc[cc["sub"]].call_id.tolist()),
            "results_subagent_vs_cache_subagent": multiset_cmp(sub_results, cr[cr["sub"]].call_id.tolist()),
            "tool_raw_equal_on_common_call_ids": sum(names[i] == cache_names[i] for i in common), "common_call_ids": len(common),

            "raw_other_counts": dict(other)}


# ------------------------------------------------------------------------------------------------ 3b: aiv_cu re-parse

def aiv_extract(sids):
    pats = {s: ('"session_id":"%s"' % s).encode() for s in sids}
    out = {s: [] for s in sids}
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    rest, nbytes, nlines, t = b"", 0, 0, time.time()
    with open(AIV_TURNS, "rb") as f:
        while True:
            raw = f.read(16 << 20)
            final = not raw
            buf = rest + (d.flush() if final else d.decompress(raw))
            cut = len(buf) if final else buf.rfind(b"\n") + 1
            blk, rest = buf[:cut], buf[cut:]
            nbytes += len(blk)
            nlines += blk.count(b"\n")
            for s, p in pats.items():
                i = blk.find(p)
                while i != -1:
                    a = blk.rfind(b"\n", 0, i) + 1
                    b = blk.find(b"\n", i)
                    b = len(blk) if b == -1 else b
                    row = json.loads(blk[a:b].decode("utf-8"))
                    if row.get("session_id") == s:
                        out[s].append(row)
                    i = blk.find(p, b)
            if final:
                break
    return out, {"decompressed_bytes": nbytes, "newlines": nlines, "wall_s": round(time.time() - t, 1)}


def aiv_provider_ids(m):
    ids = []
    if isinstance(m, list):
        ids = [it.get("call_id") for it in m if isinstance(it, dict) and it.get("call_id")]
    elif isinstance(m, dict):
        if isinstance(m.get("content"), list):
            ids += [b.get("id") for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
        ids += [t.get("id") for t in m.get("tool_calls") or [] if isinstance(t, dict)]
        for cand in m.get("candidates") or []:
            for p in ((cand or {}).get("content") or {}).get("parts") or []:
                fc = p.get("functionCall") if isinstance(p, dict) else None
                if isinstance(fc, dict) and fc.get("id"):
                    ids.append(fc["id"])
    return [i for i in ids if i]


def aiv_synthetic(m):
    if isinstance(m, list):
        return len(m) == 0
    if not isinstance(m, dict):
        return False
    if ZERO_MSG.match(str(m.get("id") or "")):
        return True
    if any(ZERO_CALL.match(str((t or {}).get("id") or "")) for t in m.get("tool_calls") or []):
        return True
    if "candidates" in m and not m.get("responseId") and not m.get("usageMetadata"):
        return True
    return False


def aiv_verify(sid, rows, stratum, role):
    df = cache_session(os.path.join(CACHE, "aiv_cu_E.parquet"), sid, ["kind", "call_id", "uuid", "ts", "text", "stderr"])
    cc = df[df.kind == "call"].set_index("uuid")
    cr = df[df.kind == "result"]
    acting = [r for r in rows if r.get("agent_action") is not None and not aiv_synthetic(r.get("agent_messages"))]
    synth = [r for r in rows if aiv_synthetic(r.get("agent_messages"))]
    pid = {r["id"]: aiv_provider_ids(r.get("agent_messages")) for r in acting}
    rows_per_id = collections.Counter(i for r in acting for i in set(pid[r["id"]]))
    k = collections.Counter()
    cache_ids = []
    for r in acting:
        rid, ids = r["id"], pid[r["id"]]
        if rid not in cc.index:
            k["acting_row_without_cache_call"] += 1
            continue
        cid = cc.loc[rid, "call_id"]
        cache_ids.append(cid)
        if len(ids) == 0:
            k["no_provider_id_rows"] += 1
            k["no_provider_id_rows_call_id_is_turn_rowid"] += cid == "turn:" + rid
        elif len(ids) == 1 and not ZERO_CALL.match(ids[0]) and rows_per_id[ids[0]] == 1:
            k["unambiguous_rows"] += 1
            k["unambiguous_rows_call_id_equal"] += cid == ids[0]
        else:
            k["ambiguous_rows"] += 1
            k["ambiguous_rows_call_id_in_provider_ids_or_turn_rowid"] += cid in set(ids) | {"turn:" + rid}
        res = cr[cr.call_id == cid]
        k["calls_with_exactly_one_result"] += len(res) == 1
        if len(res) == 1:
            x = res.iloc[0]
            k["result_text_equal_raw_output"] += (pd.isna(x.text) and r.get("output") is None) or x.text == r.get("output")
            k["result_stderr_equal_raw_error"] += (pd.isna(x.stderr) and r.get("error") is None) or x.stderr == r.get("error")
            raw_ts = pd.Timestamp(r["created_at"])
            raw_ts = raw_ts.tz_localize("UTC") if raw_ts.tzinfo is None else raw_ts  # naive created_at read as UTC
            k["result_ts_equal_created_at"] += pd.Timestamp(x.ts) == raw_ts
    return {"session_id": sid, "stratum": stratum, "role": role, "raw_rows": len(rows), "raw_synthetic_rows": len(synth),
            "raw_talk_only_rows": sum(r.get("agent_action") is None for r in rows),
            "raw_expected_calls": len(acting), "cache_calls": int((df.kind == "call").sum()),
            "cache_results": int((df.kind == "result").sum()), "cache_system_events": int((df.kind == "system").sum()),
            "cache_call_uuids_equal_acting_row_ids": set(cc.index) == {r["id"] for r in acting},
            "cache_call_ids_distinct": len(set(cache_ids)) == len(cache_ids),
            "raw_determinable_call_ids_vs_cache": {
                "rows": k["unambiguous_rows"] + k["no_provider_id_rows"],
                "equal": k["unambiguous_rows_call_id_equal"] + k["no_provider_id_rows_call_id_is_turn_rowid"]},
            "result_ids_equal_call_ids": collections.Counter(cr.call_id) == collections.Counter(df[df.kind == "call"].call_id),
            "counts": dict(k)}


# --------------------------------------------------------------------------------------------------------- selection

def select():
    swe_e = json.load(open(os.path.join(SAMP, "swechat_EH.json"), encoding="utf-8"))["E"]
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), filters=[("session_id", "in", swe_e)])
    rng = random.Random(SEED)
    swe = []
    for fmt in SWE_FORMATS:
        pool = sorted(pop[(pop.format == fmt) & pop.length.between(LEN_LO, LEN_HI)].session_id)
        swe.append((rng.choice(pool), fmt, "primary"))
    aiv_e = json.load(open(os.path.join(SAMP, "aiv_cu_EH.json"), encoding="utf-8"))["E"]
    ses = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"), columns=["session_id", "n_turns", "stratum"],
                          filters=[("session_id", "in", aiv_e)])
    rng = random.Random(SEED)
    aiv = []
    for st, role in [(s, "primary") for s in AIV_PRIMARY] + [(s, "supplementary") for s in AIV_SUPP]:
        pool = sorted(ses[(ses.stratum == st) & ses.n_turns.between(TURN_LO, TURN_HI)].session_id)
        aiv.append((rng.choice(pool), st, role))
    # targeted supplementary: first E session (sorted) whose cache holds a result with no matching call
    pf = pq.ParquetFile(os.path.join(CACHE, "swechat_E.parquet"))
    orphan, orphan_ids = set(), []
    for g in range(pf.num_row_groups):
        t = pf.read_row_group(g, columns=["session_id", "kind", "call_id"]).to_pandas()
        c = set(zip(t.session_id[t.kind == "call"], t.call_id[t.kind == "call"]))
        r = t[t.kind == "result"]
        orphan_ids += [(s, i) for s, i in zip(r.session_id, r.call_id) if (s, i) not in c]
        orphan |= {s for s, _ in orphan_ids}
    fmt_of = dict(zip(pop.session_id, pop.format))
    first = sorted(orphan)[0]
    swe.append((first, fmt_of[first], "supplementary_orphan_result"))
    return swe, aiv, len(orphan), orphan_ids


def main():
    t0 = time.time()
    swe, aiv, n_orphan_sessions, orphan_ids = select()
    report = {"probe": "analysis/probes/phase_e_cache_verify.py", "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "seed": SEED, "selection": {"swechat_length_range": [LEN_LO, LEN_HI], "aiv_cu_n_turns_range": [TURN_LO, TURN_HI],
                                          "swechat_sessions_with_orphan_result_in_cache": n_orphan_sessions},
              "split_membership": split_checks(), "hashes": hash_checks(), "swechat_reparse": [], "aiv_cu_reparse": []}
    report["swechat_orphan_results_vs_bad_lines"] = [
        {"session_id": s, "call_id": i, "session_has_bad_line": s in BAD_LINES,
         "call_id_occurs_in_a_bad_line": any(i in l for l in BAD_LINES.get(s, [])),
         "call_id_as_tool_use_id_in_a_bad_line": any(('"id":"%s"' % i) in l.replace(" ", "") for l in BAD_LINES.get(s, []))}
        for s, i in orphan_ids]
    for sid, fmt, role in swe:
        report["swechat_reparse"].append(swe_verify(sid, fmt, role))
    rows, scan = aiv_extract([s for s, _, _ in aiv])
    report["aiv_cu_scan"] = scan
    for sid, st, role in aiv:
        report["aiv_cu_reparse"].append(aiv_verify(sid, rows[sid], st, role))
    report["wall_s"] = round(time.time() - t0, 1)
    os.makedirs(OUTD, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=lambda o: int(o) if hasattr(o, "__int__") else str(o))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
