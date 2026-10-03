"""Recon: are SWE-chat's 'orphaned' tool_results' tool_use blocks hidden inside metadata rows (raw JSON)?
Scans all rows of the mirror conversations table (column subset). Writes analysis/out/recon/swechat_hidden.txt."""
import collections, json, os, re
import pyarrow.parquet as pq

ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
OUT = os.path.join(os.path.dirname(__file__), "..", "out", "recon", "swechat_hidden.txt")
pf = pq.ParquetFile(f"{ROOT}/swe-chat-mirror-cfahlgren1/conversations.parquet")
cols = ["session_id", "role", "turn_type", "tool_call_id", "content", "agent"]

use_ids, res_ids = set(), set()
meta_types = collections.Counter()
hidden_ids = set()           # toolu_ ids that appear as tool_use blocks inside metadata rows' raw JSON
hidden_res = set()           # tool_use_ids referenced by tool_result blocks inside metadata rows
res_re = re.compile(r'"tool_use_id":\s*"(toolu_[A-Za-z0-9]+)"')
meta_with_tooluse = collections.Counter()
id_re = re.compile(r'"type":\s*"tool_use",\s*"id":\s*"(toolu_[A-Za-z0-9]+)"|"id":\s*"(toolu_[A-Za-z0-9]+)"[^{}]{0,200}?"type":\s*"tool_use"')
for g in range(pf.num_row_groups):
    t = pf.read_row_group(g, columns=cols).to_pandas()
    sid = t.session_id.values
    for s, role, tt, cid, content in zip(sid, t.role.values, t.turn_type.values, t.tool_call_id.values, t.content.values):
        if role == "tool_use" and cid:
            use_ids.add((s, cid))
        elif role == "tool_result" and cid:
            res_ids.add((s, cid))
        elif role == "metadata":
            meta_types[tt] += 1
            if content and '"tool_use_id"' in content:
                hidden_res.update((s, i) for i in res_re.findall(content))
            if content and "tool_use" in content:
                ids = {a or b for a, b in id_re.findall(content)}
                if ids:
                    meta_with_tooluse[tt] += 1
                    hidden_ids.update((s, i) for i in ids)

orph = res_ids - use_ids
found = orph & hidden_ids
with open(OUT, "w", encoding="utf-8") as o:
    w = lambda *a: print(*a, file=o)
    w(f"tool_use (session,id) {len(use_ids)}  tool_result (session,id) {len(res_ids)}  orphaned results {len(orph)}")
    w("metadata turn_type counts", dict(meta_types.most_common()))
    w("metadata rows whose raw JSON contains tool_use blocks, by turn_type", dict(meta_with_tooluse.most_common()))
    w(f"distinct tool_use ids found inside metadata rows: {len(hidden_ids)}")
    w(f"orphaned results whose tool_use is found inside a metadata row of the same session: {len(found)} / {len(orph)}")
    w(f"hidden ids that are NOT in the tool_use table: {len(hidden_ids - use_ids)}")
    w(f"tool_result blocks inside metadata rows (distinct session,id): {len(hidden_res)}; of these paired with a hidden tool_use: {len(hidden_res & hidden_ids)}")
    hid_any = {i for _, i in hidden_ids}
    w(f"orphaned results whose id matches a hidden tool_use in ANY session: {sum(1 for _, i in orph if i in hid_any)}")
    w(f"orphaned results whose id also appears as a tool_result inside metadata rows: {len(orph & hidden_res)}")
print(open(OUT, encoding="utf-8").read())
