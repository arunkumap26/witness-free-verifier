"""Count, over the first N lines of aiv_cu computer_use_turns, how many raw lines mention request-id-like keys
or ids, by key. Aggregates only."""
import gzip, re, sys, json, collections
PATH = r"C:\Swarms\data\ai-village\computer_use_turns.jsonl.gz"
N = int(sys.argv[1])
pats = {k: re.compile(v) for k, v in {
    "x-request-id": r'"x-request-id"', "request-id": r'"request-id"', "request_id_key": r'"request_?[iI]d"',
    "req_011C": r"req_011C", "x-goog": r'"x-goog-[a-z-]+"', "openai-processing-ms": r"openai-processing-ms",
    "resp_hex": r'"resp_[0-9a-f]{8}', "chatcmpl-": r"chatcmpl-", "createTime": r'"createTime"',
    "created_at_key_in_agent_messages": r'"created_at"'}.items()}
c = collections.Counter(); goog = collections.Counter(); n = 0
with gzip.open(PATH, "rt", encoding="utf-8") as f:
    for line in f:
        n += 1
        for k, p in pats.items():
            if p.search(line):
                c[k] += 1
        for m in re.findall(r'"(x-goog-[a-z-]+)"', line):
            goog[m] += 1
        if n >= N:
            break
print(json.dumps({"lines": n, "lines_matching": dict(c), "x_goog_keys": dict(goog)}, indent=1))
