"""Corpus skeptic: full-content scan of every acquired corpus for provider request ids, plus hygiene counts.

Independent of the B4/B5/compose_inventory code. Every file of every corpus under C:/Swarms/data/acquired is read
(text files as bytes; *.gz and *.tar.gz streamed; *.parquet via pyarrow string columns). Skipped: `.git/` and
`.cache/` folders (VCS / HF download bookkeeping) and terminal-bench-2-leaderboard/submissions/ (the early
duplicate copies; their byte identity with hf_repo/ is checked separately below).

Counts, per corpus:
  - ANTH: values matching the Anthropic request-id layout used by Phase C/B4 (req_[vrtx_|bdrk_]01 + 22 base58)
  - LOOSE: any `req_` followed by >= 20 alphanumerics (catches other layouts)
  - KEYS: JSON keys named like a request id (requestId, request_id, request-id, x-request-id), with value shape
  - where the ANTH values sit (top path prefixes)
  - credential hygiene: number of files containing `sk-ant-` followed by >= 20 key characters and files containing
    the string CLAUDE_CODE_OAUTH_TOKEN. Values are never stored or printed.
Then a decode/agreement check for the three corpora whose Claude Code JSONL carries requestId: each entry's id time
(top 48 bits of the base58 integer, the inferred UUIDv7 layout) against the entry's own timestamp, window
[-2 s, +600 s] as in B4.

Run:  PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/corpus_skeptic/request_id_scan.py
Out:  analysis/out/phase_e/track_b/corpus_skeptic/request_id_scan.json
"""
import collections
import datetime as dt
import glob
import gzip
import hashlib
import json
import os
import re
import sys
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

A = "C:/Swarms/data/acquired"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "request_id_scan.json")
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58C = "1-9A-HJ-NP-Za-km-z"
ANTH = re.compile(rb"req_(?:vrtx_|bdrk_)?01[" + B58C.encode() + rb"]{22}(?![" + B58C.encode() + rb"])")
LOOSE = re.compile(rb"req_[0-9A-Za-z]{20,}")
KEYS = re.compile(rb'"(requestId|request_id|request-id|x-request-id|requestID|RequestId)"\s*:\s*("([^"]{0,80})"|null|[0-9]+)')
SKANT = re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}")
OAUTH = b"CLAUDE_CODE_OAUTH_TOKEN"
TEXT_EXT = {".json", ".jsonl", ".txt", ".log", ".cast", ".pane", ".yaml", ".yml", ".md", ".csv", ".py", ".js", ".toml"}


def value_shape(v):
    if v is None:
        return "null"
    s = v.decode("utf-8", "replace")
    if ANTH.fullmatch(v):
        return "anthropic_req"
    if re.fullmatch(r"[0-9a-f]{32}", s):
        return "hex32"
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", s):
        return "uuid"
    if s.startswith("req_"):
        return "req_other"
    if s == "":
        return "empty"
    return "other_len%d" % len(s)


def scan_bytes(b, acc):
    for m in ANTH.finditer(b):
        acc["anth"].append(m.group(0).decode())
    acc["loose"] += len(LOOSE.findall(b))
    for m in KEYS.finditer(b):
        acc["keys"]["%s|%s" % (m.group(1).decode(), value_shape(m.group(3)) if m.group(3) is not None else m.group(2).decode()[:8])] += 1
    if SKANT.search(b):
        acc["skant_hit"] = True
    if OAUTH in b:
        acc["oauth_hit"] = True


def new_acc():
    return {"anth": [], "loose": 0, "keys": collections.Counter(), "skant_hit": False, "oauth_hit": False, "bytes": 0,
            "members": 0, "error": None}


def scan_file(path):
    acc = new_acc()
    try:
        low = path.lower()
        if low.endswith(".tar.gz"):
            with tarfile.open(path, "r|gz") as tf:
                for ti in tf:
                    if ti.isfile():
                        b = tf.extractfile(ti).read()
                        acc["bytes"] += len(b)
                        acc["members"] += 1
                        scan_bytes(b, acc)
                        acc_flush = None
        elif low.endswith(".gz"):
            with gzip.open(path, "rb") as fh:  # jsonl.gz: line by line, so no match is split
                for b in fh:
                    acc["bytes"] += len(b)
                    scan_bytes(b, acc)
        elif low.endswith(".parquet"):
            import pyarrow.parquet as pq
            import pyarrow as pa
            t = pq.read_table(path)
            for name in t.column_names:
                col = t.column(name)
                if pa.types.is_string(col.type) or pa.types.is_large_string(col.type):
                    for v in col.to_pylist():
                        if v:
                            b = v.encode("utf-8", "replace")
                            acc["bytes"] += len(b)
                            scan_bytes(b, acc)
                elif pa.types.is_list(col.type) or pa.types.is_struct(col.type):
                    for v in col.to_pylist():
                        if v:
                            b = json.dumps(v, default=str).encode("utf-8", "replace")
                            acc["bytes"] += len(b)
                            scan_bytes(b, acc)
        else:
            ext = os.path.splitext(low)[1]
            if ext not in TEXT_EXT and ext != "":
                acc["skipped_ext"] = ext
                return path, acc
            if os.path.getsize(path) > (256 << 20):  # big JSONL: line by line (JSON strings never span lines)
                with open(path, "rb") as fh:
                    for b in fh:
                        acc["bytes"] += len(b)
                        scan_bytes(b, acc)
            else:
                with open(path, "rb") as fh:
                    b = fh.read()
                acc["bytes"] += len(b)
                scan_bytes(b, acc)
    except Exception as e:
        acc["error"] = repr(e)[:200]
    return path, acc


def corpus_files(corpus):
    root = os.path.join(A, corpus)
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in (".git", ".cache")]
        rel = os.path.relpath(dp, root).replace("\\", "/")
        if corpus == "terminal-bench-2-leaderboard" and (rel == "submissions" or rel.startswith("submissions/")):
            dn[:] = []
            continue
        for f in fn:
            yield os.path.join(dp, f)


def b58_int(s):
    v = 0
    for ch in s:
        v = v * 58 + B58.index(ch)
    return v


def id_ms(rid):
    body = rid.rsplit("_", 1)[1]
    return b58_int(body[2:]) >> 80


def parse_iso_ms(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000.0
    except Exception:
        return None


def cc_agreement(files):
    c = collections.Counter()
    distinct, distinct_agree = set(), set()
    models = collections.Counter()
    for f in files:
        with open(f, "rb") as fh:
            for raw in fh:
                try:
                    o = json.loads(raw)
                except Exception:
                    c["bad_lines"] += 1
                    continue
                rid = o.get("requestId")
                if not isinstance(rid, str) or not rid.startswith("req_"):
                    continue
                c["entries_with_req"] += 1
                c["entries_with_req_type_" + str(o.get("type"))] += 1
                m = (o.get("message") or {}).get("model") if isinstance(o.get("message"), dict) else None
                models[str(m)] += 1
                distinct.add(rid)
                if not ANTH.fullmatch(rid.encode()):
                    c["entries_req_not_anthropic_layout"] += 1
                    continue
                ts = parse_iso_ms(o.get("timestamp") or "")
                if ts is None:
                    c["entries_without_ts"] += 1
                    continue
                d = ts - id_ms(rid)
                if -2000 <= d <= 600000:
                    c["entries_agree_-2s_+600s"] += 1
                    distinct_agree.add(rid)
                elif d < -2000:
                    c["entries_id_after_event_by_gt_2s"] += 1
                else:
                    c["entries_event_after_id_by_gt_600s"] += 1
    c["distinct_req_ids"] = len(distinct)
    c["distinct_req_ids_with_ge1_agreeing_entry"] = len(distinct_agree)
    return dict(c), dict(models.most_common(15))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    t0 = time.time()
    corpora = sorted(d for d in os.listdir(A) if os.path.isdir(os.path.join(A, d)))
    jobs = [(c, p) for c in corpora for p in corpus_files(c)]
    per = {c: {"files": 0, "bytes_scanned": 0, "anth_matches": 0, "anth_distinct": set(), "loose_matches": 0,
               "keys": collections.Counter(), "files_with_anth": 0, "anth_by_prefix": collections.Counter(),
               "files_with_sk_ant": 0, "files_with_oauth_env": 0, "sk_ant_by_prefix": collections.Counter(),
               "errors": [], "skipped_ext": collections.Counter()} for c in corpora}
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(scan_file, p): c for c, p in jobs}
        for fu in as_completed(futs):
            c = futs[fu]
            path, acc = fu.result()
            r = per[c]
            r["files"] += 1
            if acc.get("skipped_ext"):
                r["skipped_ext"][acc["skipped_ext"]] += 1
                continue
            r["bytes_scanned"] += acc["bytes"]
            rel = os.path.relpath(path, os.path.join(A, c)).replace("\\", "/")
            prefix = "/".join(rel.split("/")[:2]) if c != "terminal-bench-2-leaderboard" else "/".join(rel.split("/")[:5])
            if acc["anth"]:
                r["files_with_anth"] += 1
                r["anth_matches"] += len(acc["anth"])
                r["anth_distinct"].update(acc["anth"])
                r["anth_by_prefix"][prefix] += len(acc["anth"])
            r["loose_matches"] += acc["loose"]
            r["keys"].update(acc["keys"])
            if acc["skant_hit"]:
                r["files_with_sk_ant"] += 1
                r["sk_ant_by_prefix"][prefix] += 1
            if acc["oauth_hit"]:
                r["files_with_oauth_env"] += 1
            if acc["error"]:
                r["errors"].append([rel, acc["error"]])
    out = {}
    for c, r in per.items():
        out[c] = {k: (len(v) if k == "anth_distinct" else dict(v.most_common(12)) if isinstance(v, collections.Counter) else v)
                  for k, v in r.items()}
    # decode / agreement on the Claude Code JSONL that carry requestId
    tb2 = A + "/terminal-bench-2-leaderboard/hf_repo/submissions/terminal-bench/2.0"
    cc_sets = {
        "terminal-bench-2-leaderboard/WozCode__Claude-Opus-4.6": glob.glob(tb2 + "/WozCode__Claude-Opus-4.6/**/agent/sessions/**/*.jsonl", recursive=True),
        "terminal-bench-2-leaderboard/ClaudeCode__GLM-4.7": glob.glob(tb2 + "/ClaudeCode__GLM-4.7/**/agent/sessions/**/*.jsonl", recursive=True),
        "terminal-bench-2-leaderboard/cchuter__minimax-m2.5": glob.glob(tb2 + "/cchuter__minimax-m2.5/**/agent/sessions/**/*.jsonl", recursive=True),
        "cli-trace-commons": glob.glob(A + "/cli-trace-commons/*/sessions/**/*.jsonl", recursive=True),
    }
    for d in sorted(glob.glob(A + "/cli-claude-code-hf/*/")):
        cc_sets["cli-claude-code-hf/" + os.path.basename(os.path.normpath(d))] = glob.glob(d + "**/*.jsonl", recursive=True)
    agree = {}
    for k, files in cc_sets.items():
        stats, models = cc_agreement(files)
        agree[k] = {"jsonl_files": len(files), **stats, "models_on_req_entries": models}
    # corpus-level union for cli-claude-code-hf (distinct ids across repos)
    allcc = []
    for k, files in cc_sets.items():
        if k.startswith("cli-claude-code-hf/"):
            allcc += files
    s, m = cc_agreement(allcc)
    agree["cli-claude-code-hf (union)"] = {"jsonl_files": len(allcc), **s, "models_on_req_entries": m}
    # duplicate-copy checks
    dup = {}
    early = A + "/terminal-bench-2-leaderboard/submissions"
    n = same = missing = 0
    diff = []
    for dp, dn, fn in os.walk(early):
        for f in fn:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, A + "/terminal-bench-2-leaderboard").replace("\\", "/")
            q = A + "/terminal-bench-2-leaderboard/hf_repo/" + rel
            n += 1
            if not os.path.exists(q):
                missing += 1
            elif os.path.getsize(p) == os.path.getsize(q) and sha256(p) == sha256(q):
                same += 1
            else:
                diff.append(rel)
    dup["tb2_early_copies"] = {"files": n, "byte_identical_to_hf_repo": same, "missing_in_hf_repo": missing,
                               "differ": len(diff), "differ_examples": diff[:5],
                               "bytes": sum(os.path.getsize(os.path.join(dp, f)) for dp, dn, fn in os.walk(early) for f in fn)}
    part = glob.glob(A + "/openhands-evaluation-outputs/outputs/**/*.part", recursive=True)
    dup["openhands_part_files"] = []
    for p in part:
        q = p[:-5]
        dup["openhands_part_files"].append({"part": os.path.relpath(p, A).replace("\\", "/"), "bytes": os.path.getsize(p),
                                            "identical_to": os.path.relpath(q, A).replace("\\", "/") if os.path.exists(q) and sha256(p) == sha256(q) else None})
    doc = {"produced_by": "analysis/out/phase_e/track_b/corpus_skeptic/request_id_scan.py",
           "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "patterns": {"ANTH": ANTH.pattern.decode(), "LOOSE": LOOSE.pattern.decode(), "KEYS": KEYS.pattern.decode(),
                        "SK_ANT": "sk-ant- + >=20 key chars (count of files only; values never stored)"},
           "skips": [".git/", ".cache/", "terminal-bench-2-leaderboard/submissions/ (duplicates, checked in duplicates)"],
           "per_corpus": out, "claude_code_request_id_agreement": agree, "duplicates": dup,
           "seconds": round(time.time() - t0, 1)}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), indent=1)
    print("done", round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
