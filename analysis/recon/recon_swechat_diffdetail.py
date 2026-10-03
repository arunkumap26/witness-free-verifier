"""Recon follow-up: (1) what differs in rows whose content differs between mirror and pinned;
(2) how conversation session_ids line up with sessions.parquet and transcript files.
Writes analysis/out/recon/swechat_diffdetail.txt."""
import collections, glob, os
import pandas as pd, pyarrow.parquet as pq

D = os.path.join(os.path.dirname(__file__), "..", "out", "recon")
ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
o = open(f"{D}/swechat_diffdetail.txt", "w", encoding="utf-8")
w = lambda *a: print(*a, file=o)

hm = pq.read_table(f"{D}/swechat_rowhash_mirror.parquet").to_pandas().drop_duplicates("turn_id")
hp = pq.read_table(f"{D}/swechat_rowhash_pinned.parquet").to_pandas().drop_duplicates("turn_id")
j = hm.merge(hp, on="turn_id", suffixes=("_m", "_p"))
diff_ids = set(j.loc[j.h_content_m != j.h_content_p, "turn_id"])
w(f"turn_ids with differing content: {len(diff_ids)}")

cols = ["turn_id", "session_id", "role", "turn_type", "tool_name", "content"]
def grab(path):
    pf = pq.ParquetFile(path); parts = []
    for g in range(pf.num_row_groups):
        t = pf.read_row_group(g, columns=cols).to_pandas()
        parts.append(t[t.turn_id.isin(diff_ids)])
    return pd.concat(parts).drop_duplicates("turn_id").set_index("turn_id")
a = grab(f"{ROOT}/swe-chat-mirror-cfahlgren1/conversations.parquet")
b = grab(f"{ROOT}/swe-chat-pinned/conversations.parquet")
x = a.join(b[["content"]], rsuffix="_p")
x["len_m"] = x.content.fillna("").str.len(); x["len_p"] = x.content_p.fillna("").str.len()
w("by role/turn_type", x.groupby(["role", "turn_type"]).size().sort_values(ascending=False).head(15).to_dict())
w("by tool_name", x.tool_name.value_counts().head(10).to_dict())
w(f"sessions affected: {x.session_id.nunique()}")
d = x.len_p - x.len_m
w(f"length change pinned-mirror: longer {int((d>0).sum())}, shorter {int((d<0).sum())}, same length {int((d==0).sum())}")
w(f"mirror ends with truncation marker: {int(x.content.fillna('').str.endswith('... [truncated]').sum())}; pinned: {int(x.content_p.fillna('').str.endswith('... [truncated]').sum())}")
w(f"one is null/empty, other not: {int(((x.len_m==0)!=(x.len_p==0)).sum())}")
# Characterize the first point of divergence on a few rows (positions and a short window; aggregate only)
kinds = collections.Counter()
for m_, p_ in zip(x.content.fillna(""), x.content_p.fillna("")):
    i = next((k for k in range(min(len(m_), len(p_))) if m_[k] != p_[k]), min(len(m_), len(p_)))
    if m_.strip() == p_.strip(): kinds["whitespace only"] += 1
    elif m_.replace("\r\n", "\n") == p_.replace("\r\n", "\n"): kinds["CRLF vs LF"] += 1
    elif m_.startswith(p_) or p_.startswith(m_): kinds["one is a prefix of the other"] += 1
    elif i > 0.9 * min(len(m_), len(p_)): kinds["diverge in last 10%"] += 1
    else: kinds["diverge earlier"] += 1
w("divergence kind", dict(kinds.most_common()))

sess = pq.read_table(f"{ROOT}/swe-chat-pinned/sessions.parquet", columns=["session_id"]).to_pandas().session_id
conv_s = set(pq.read_table(f"{ROOT}/swe-chat-pinned/conversations.parquet", columns=["session_id"]).column(0).to_pylist())
stems = {os.path.basename(f)[:-6] for f in glob.glob(f"{ROOT}/swe-chat-pinned/transcripts/*.jsonl")}
w(f"\nsessions.parquet {len(sess)}; distinct session_id in conversations {len(conv_s)}; transcript files {len(stems)}")
w(f"conversation session_ids not in sessions.parquet: {len(conv_s - set(sess))}; without a transcript file: {len(conv_s - stems)}")
w(f"sessions.parquet ids with no conversation rows: {len(set(sess) - conv_s)}")
o.close()
print(open(f"{D}/swechat_diffdetail.txt", encoding="utf-8").read())
