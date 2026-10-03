"""Recon: one light pass over a SWE-chat conversations.parquet (mirror or pinned).
Usage: python recon_swechat_scan.py <conversations.parquet> <label>
Writes analysis/out/recon/swechat_scan_<label>.json (counts) and swechat_rowhash_<label>.parquet
(per-row blake2b hashes of content and of the other fields, for a row-level diff between copies)."""
import collections, hashlib, json, os, re, sys
import pyarrow as pa, pyarrow.parquet as pq

path, label = sys.argv[1], sys.argv[2]
OUTD = os.path.join(os.path.dirname(__file__), "..", "out", "recon")
pf = pq.ParquetFile(path)
cols = ["turn_id", "session_id", "turn_number", "role", "turn_type", "content", "timestamp", "tool_name",
        "tool_call_id", "input_tokens", "output_tokens", "agent"]
H = lambda s: hashlib.blake2b(s.encode("utf-8", "surrogatepass"), digest_size=8).hexdigest()
id_re = re.compile(r'"type":\s*"tool_use",\s*"id":\s*"(toolu_[A-Za-z0-9]+)"|"id":\s*"(toolu_[A-Za-z0-9]+)"[^{}]{0,200}?"type":\s*"tool_use"')
res_re = re.compile(r'"tool_use_id":\s*"(toolu_[A-Za-z0-9]+)"')
exit_re = re.compile(r"^Exit code (\d+)")

c = collections.Counter()
roles, agents, turn_types, exitcodes = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
sessions = set(); use, res, hid_use, hid_res = set(), set(), set(), set()
hashes = {"turn_id": [], "h_content": [], "h_meta": []}
for g in range(pf.num_row_groups):
    t = pf.read_row_group(g, columns=cols).to_pandas()
    ts = t.timestamp
    c["rows"] += len(t); c["ts_null"] += int(ts.isna().sum())
    c["ts_ms_multiple"] += int(((ts.dropna().dt.microsecond % 1000) == 0).sum())
    for r in t.itertuples(index=False):
        sessions.add(r.session_id); roles[r.role] += 1; turn_types[(r.role, r.turn_type)] += 1
        content = r.content if isinstance(r.content, str) else ""
        if r.role == "tool_use" and r.tool_call_id:
            use.add((r.session_id, r.tool_call_id)); agents[r.agent] += 1
        elif r.role == "tool_result" and r.tool_call_id:
            res.add((r.session_id, r.tool_call_id))
            if len(content) == 10256 and content.endswith("\n... [truncated]"):
                c["result_truncated_10256"] += 1
            m = exit_re.match(content)
            if m:
                exitcodes[m.group(1)] += 1
        elif r.role == "assistant" and (r.input_tokens or 0) > 0:
            c["assistant_rows_with_input_tokens"] += 1
        elif r.role == "metadata" and content:
            if '"tool_use_id"' in content:
                hid_res.update((r.session_id, i) for i in res_re.findall(content))
            if "tool_use" in content:
                hid_use.update((r.session_id, a or b) for a, b in id_re.findall(content))
        hashes["turn_id"].append(r.turn_id)
        hashes["h_content"].append(H(content))
        hashes["h_meta"].append(H("|".join(str(x) for x in (r.session_id, r.turn_number, r.role, r.turn_type, r.timestamp,
                                                             r.tool_name, r.tool_call_id, r.input_tokens, r.output_tokens, r.agent))))

orph = res - use
out = {
    "label": label, "path": path, "row_groups": pf.num_row_groups, **c,
    "sessions": len(sessions),
    "roles": dict(roles.most_common()),
    "tool_use_by_agent": dict(agents.most_common()),
    "tool_use_distinct": len(use), "tool_result_distinct": len(res),
    "calls_with_result": len(use & res), "orphaned_results": len(orph),
    "hidden_subagent_tool_use": len(hid_use), "hidden_subagent_tool_result": len(hid_res),
    "hidden_paired": len(hid_use & hid_res), "hidden_ids_also_in_tool_use_table": len(hid_use & use),
    "orphans_matching_hidden_use": len(orph & hid_use),
    "exit_code_prefix_on_results": dict(exitcodes.most_common(12)),
    "turn_types": {f"{a}/{b}": v for (a, b), v in turn_types.most_common()},
}
json.dump(out, open(f"{OUTD}/swechat_scan_{label}.json", "w"), indent=1)
pq.write_table(pa.table(hashes), f"{OUTD}/swechat_rowhash_{label}.parquet")
print(json.dumps(out, indent=1)[:3000])
