"""Mechanical classification of every audited HF candidate. Rules fixed before reading the full audit:
- licence_class: permissive (mit, apache-2.0, cc-by-4.0, cc0-1.0, bsd-3-clause, cdla-permissive-2.0, odc-by),
  research_only (cc-by-nc-4.0, agpl-3.0 = permits research use, with NC / copyleft caveat), other (read by hand), none (do not download).
- ts_pass: best sampled file has >=3 records and >=50% of records carry a timestamp-valued field at depth <=2.
- join_pass: >=1 call id in the sample and >=80% of call ids have a matching result id (tool_use_id / call_id / toolCallId / tool_call_id).
- field_audit_pass = ts_pass and join_pass.
- size_ok: total repo bytes <= 5 GB.
"""
import json
from collections import Counter

PERMISSIVE = {"mit", "apache-2.0", "cc-by-4.0", "cc0-1.0", "bsd-3-clause", "cdla-permissive-2.0", "odc-by", "cc-by-sa-4.0"}
RESEARCH_ONLY = {"cc-by-nc-4.0", "agpl-3.0", "cc-by-nc-sa-4.0"}


def lic_of(meta):
    l = meta.get("license")
    if isinstance(l, list):
        l = ",".join(l)
    return (l or "NONE").lower()


def lic_class(l):
    if l == "none":
        return "none"
    if l in PERMISSIVE:
        return "permissive"
    if l in RESEARCH_ONLY:
        return "research_only"
    return "other"


def best_sample(a):
    best = None
    for s in a.get("samples", []) or []:
        au = s.get("audit")
        if not au or not au.get("n_records"):
            continue
        key = (au["ts_coverage"] >= 0.5 and au["n_records"] >= 3, (au.get("join_rate_calls") or 0) >= 0.8, au["n_call_ids"], au["n_records"])
        if best is None or key > best[0]:
            best = (key, s)
    return best[1] if best else None


def classify(meta, a):
    l = lic_of(meta)
    out = {"id": meta["id"], "sha": meta.get("sha"), "license": l, "licence_class": lic_class(l),
           "gated": meta.get("gated"), "total_bytes": meta.get("total_bytes"), "n_files": meta.get("n_files"),
           "n_jsonl": sum(1 for s in meta.get("siblings", []) if s["path"].endswith(".jsonl")),
           "lastModified": meta.get("lastModified"), "downloads": meta.get("downloads"),
           "agent_traces_tag": "format:agent-traces" in (meta.get("tags") or [])}
    s = best_sample(a) if a else None
    if not a or a.get("status") != "ok" or s is None:
        out.update(audit_status=(a or {}).get("status", "not_audited") if (a or {}).get("status") != "ok" else "no_parseable_sample",
                   ts_pass=None, join_pass=None, field_audit_pass=None)
        errs = [x.get("error") for x in (a or {}).get("samples", []) if x.get("error")]
        if errs:
            out["audit_errors"] = errs[:2]
        return out
    au = s["audit"]
    fmt = max(au["format_votes"].items(), key=lambda kv: kv[1])[0] if au["format_votes"] else "unknown"
    ts_pass = au["ts_coverage"] >= 0.5 and au["n_records"] >= 3
    join_pass = au["n_call_ids"] >= 1 and (au.get("join_rate_calls") or 0) >= 0.8
    out.update(audit_status="ok", sample_path=s["path"], sample_bytes_read=s.get("bytes_read"), format=fmt,
               n_records_sampled=au["n_records"], ts_coverage=au["ts_coverage"], ts_keys=au["ts_keys"], ts_resolution=au["ts_resolution"],
               n_call_ids=au["n_call_ids"], n_joined=au["n_joined"], join_rate=au.get("join_rate_calls"),
               request_id_values=au["n_request_id_values"], request_id_examples=au["request_id_examples"][:2],
               token_keys=sorted(au["token_keys"]), error_keys=sorted(au["error_keys"]), truncat_mentions=au["records_mentioning_truncat"],
               ts_pass=ts_pass, join_pass=join_pass, field_audit_pass=ts_pass and join_pass)
    return out


if __name__ == "__main__":
    metas = {m["id"]: m for m in json.load(open("meta.json"))}
    audits = {a["id"]: a for a in json.load(open("audit.json"))}
    rows = [classify(metas[i], audits.get(i)) for i in metas]
    json.dump(rows, open("classified.json", "w"), indent=1)
    c = Counter((r["licence_class"], r.get("field_audit_pass")) for r in rows)
    print(sorted(c.items(), key=str))
    print("audit_status", Counter(r["audit_status"] for r in rows))
