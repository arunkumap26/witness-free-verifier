"""B7 release-readiness scan (aggregate counts only; no matched value is ever written or printed).

Purpose: size the privacy/secret-scrubbing work for a public release of the normalized IR. Counts candidate
secrets and PII-like strings that survive the upstream redaction in the releasable corpora's IR caches.

Reads ONLY: analysis/cache/swechat_{A,B,E}.parquet, analysis/cache/whowhen_{A,B}.parquet.
Never reads split H (no H cache exists; H session ids are not in these files), cc_local, aiv_* (not releasable),
or anything related to the swarm.

Output: analysis/out/phase_e/track_b/B7/release_scan.json
Run from the worktree root:  PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/B7/release_scan.py

Patterns are high-precision vendor token shapes plus email addresses. A match is a CANDIDATE, not a confirmed live
secret: documentation placeholders and test fixtures also match (e.g. AWS's documented example key id is counted
separately). Counts are upper bounds on what a scrubber must review, not a leak count.
"""
import json, os, re, sys, time, collections
import pyarrow.parquet as pq

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.path.join(os.path.dirname(__file__), "release_scan.json")
FILES = {"swechat": ["swechat_A", "swechat_B", "swechat_E"], "whowhen": ["whowhen_A", "whowhen_B"]}
FIELDS = ["text", "args", "command", "stderr"]

# (name, cheap substring prefilter, compiled regex)
PATTERNS = [
    ("aws_access_key_id", ("AKIA", "ASIA"), re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"),
     re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{60,}")),
    ("anthropic_key", ("sk-ant-",), re.compile(r"sk-ant-[A-Za-z0-9_\-]{30,}")),
    ("openai_key", ("sk-",), re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{40,}")),
    ("slack_token", ("xox",), re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("google_api_key", ("AIza",), re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe_live_key", ("sk_live_", "rk_live_"), re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}")),
    ("private_key_block", ("PRIVATE KEY-----",), re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("jwt", ("eyJ",), re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("email_address", ("@",), re.compile(r"\b[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63})*\.[A-Za-z]{2,24}\b")),
]
AWS_DOC_EXAMPLE = "AKIAIOSFODNN7EXAMPLE"
# emails that are structurally non-personal (bots, placeholders); counted apart, never printed
NONPERSONAL_EMAIL_RX = re.compile(r"(noreply|no-reply|users\.noreply\.github\.com|@example\.(com|org|net)|@localhost|"
                                  r"@test\.|@email\.com|@domain\.com|anthropic\.com$|^git@|"
                                  # file names such as icon@2x.png or pkg@scope.js: the 'TLD' is a file extension
                                  r"\.(png|jpe?g|gif|svg|webp|ico|js|mjs|cjs|ts|tsx|jsx|css|scss|json|md|py|txt|html?|map|"
                                  r"lock|ya?ml|toml|sh|go|rs|rb|java|kt|swift|vue|wasm|zip|gz|tar|pdf|mp4|woff2?)$)", re.I)
REDACTION_RX = re.compile(r"REDACTED")


def scan():
    t0 = time.time()
    res = {}
    for corpus, stems in FILES.items():
        c = {"rows": 0, "events_by_kind": collections.Counter(), "sessions": set(),
             "redaction_marker_events": 0, "patterns": {}}
        for name, _, _ in PATTERNS:
            c["patterns"][name] = {"matches": 0, "distinct_values": set(), "events": 0, "sessions": set(),
                                   "by_kind": collections.Counter(), "by_stratum": collections.Counter()}
        aws_doc = 0
        email_nonpersonal_distinct = set()
        for stem in stems:
            path = os.path.join(CACHE, stem + ".parquet")
            if not os.path.exists(path):
                continue
            pf = pq.ParquetFile(path)
            for batch in pf.iter_batches(batch_size=20000, columns=["session_id", "stratum", "kind"] + FIELDS):
                cols = batch.to_pydict()
                n = len(cols["session_id"])
                for i in range(n):
                    sid, strat, kind = cols["session_id"][i], cols["stratum"][i], cols["kind"][i]
                    c["rows"] += 1
                    c["events_by_kind"][kind] += 1
                    c["sessions"].add(sid)
                    blob = "\n".join(v for v in (cols[f][i] for f in FIELDS) if v)
                    if not blob:
                        continue
                    if "REDACTED" in blob:
                        c["redaction_marker_events"] += 1
                    for name, pre, rx in PATTERNS:
                        if not any(p in blob for p in pre):
                            continue
                        found = rx.findall(blob)
                        if not found:
                            continue
                        p = c["patterns"][name]
                        if name == "aws_access_key_id":
                            aws_doc += sum(1 for v in found if v == AWS_DOC_EXAMPLE)
                            found = [v for v in found if v != AWS_DOC_EXAMPLE]
                            if not found:
                                continue
                        if name == "email_address":
                            personal = [v for v in found if not NONPERSONAL_EMAIL_RX.search(v)]
                            email_nonpersonal_distinct.update(hash(v) for v in found if NONPERSONAL_EMAIL_RX.search(v))
                            found = personal
                            if not found:
                                continue
                        p["matches"] += len(found)
                        p["distinct_values"].update(hash(v) for v in found)  # in-memory hashes only, never written
                        p["events"] += 1
                        p["sessions"].add(sid)
                        p["by_kind"][kind] += 1
                        p["by_stratum"][strat] += 1
        out = {"files": stems, "rows": c["rows"], "sessions": len(c["sessions"]),
               "events_by_kind": dict(c["events_by_kind"]),
               "events_with_REDACTED_marker": c["redaction_marker_events"],
               "aws_documented_example_key_occurrences_excluded": aws_doc,
               "email_nonpersonal_distinct_excluded": len(email_nonpersonal_distinct),
               "patterns": {}}
        for name, p in c["patterns"].items():
            out["patterns"][name] = {"matches": p["matches"], "distinct_values": len(p["distinct_values"]),
                                     "events": p["events"], "sessions": len(p["sessions"]),
                                     "events_by_kind": dict(p["by_kind"]),
                                     "events_by_stratum": dict(p["by_stratum"])}
        out["sessions_with_any_secret_candidate"] = len(set().union(
            *[c["patterns"][n]["sessions"] for n, _, _ in PATTERNS if n != "email_address"]))
        res[corpus] = out
    return {"script": "analysis/out/phase_e/track_b/B7/release_scan.py",
            "splits_read": "A, B, E only (H never opened; cc_local and aiv_* not read)",
            "fields_scanned": FIELDS,
            "patterns": {n: rx.pattern for n, _, rx in PATTERNS},
            "caveat": "candidate matches, not confirmed live secrets; values never stored or printed",
            "wall_seconds": round(time.time() - t0, 1), "corpora": res}


if __name__ == "__main__":
    r = scan()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1)
    print(json.dumps({k: {"rows": v["rows"], "sessions": v["sessions"],
                          "pat": {n: (p["matches"], p["distinct_values"], p["sessions"]) for n, p in v["patterns"].items()}}
                      for k, v in r["corpora"].items()}, indent=1))
    print("wall_seconds", r["wall_seconds"])
