"""B5e: on the sampled Pi sessions (scratchpad bytes), test whether assistant responseId values decode to a time that
agrees with the message's own epoch-ms timestamp. Layouts: OpenAI resp_ hex (B2a openai_hex: hex50 with '0' at [16] ->
seconds at [18:26]; hex48 -> seconds at [0:8]); OpenRouter gen-<digits>-... (leading unix seconds, hypothesis);
Anthropic msg_ (B2a anth: top-48 ms if UUIDv7 bits). All layouts UNVERIFIED against vendor docs.
Writes census/pi_respid_decode.json."""
import json, os, re, statistics, sys
from collections import defaultdict
A = json.load(open(sys.argv[1], encoding="utf-8")); sdir = sys.argv[2]
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"; B58I = {c: i for i, c in enumerate(B58)}
def dec(rid):
    if rid.startswith("resp_"):
        b = rid[5:]
        try:
            if len(b) == 50 and b[16] == "0": return "openai_resp_hex50", int(b[18:26], 16) * 1000
            if len(b) == 48: return "openai_resp_hex48", int(b[:8], 16) * 1000
        except ValueError: return "openai_resp_nothex", None
        return f"openai_resp_len{len(b)}", None
    m = re.match(r"^gen-(\d{9,11})-", rid)
    if m: return "openrouter_gen_secs", int(m.group(1)) * 1000
    if rid.startswith("gen-"): return "openrouter_gen_other", None
    if rid.startswith("msg_"):
        body = rid[4:]
        if body[:2] == "01" and all(c in B58I for c in body[2:]):
            v = 0
            for c in body[2:]: v = v * 58 + B58I[c]
            if ((v >> 76) & 0xF) == 7 and ((v >> 62) & 3) == 2: return "anthropic_msg_v7", v >> 80
            return "anthropic_msg_not_v7", None
    return "other", None
out = {}
for k, r in A.items():
    if (r.get("metrics") or {}).get("format") != "pi_session_jsonl": continue
    p = os.path.join(sdir, r["dataset"].replace("/", "__"), r["sample_path"].replace("/", "__"))
    if not os.path.exists(p): continue
    fam = defaultdict(list); ex = {}
    for ln in open(p, encoding="utf-8", errors="replace"):
        try: e = json.loads(ln)
        except Exception: continue
        m = e.get("message") if isinstance(e, dict) else None
        if not isinstance(m, dict) or m.get("role") != "assistant" or not m.get("responseId"): continue
        f, ms = dec(m["responseId"]); ex.setdefault(f, m["responseId"][:14] + "...")
        if ms is not None and isinstance(m.get("timestamp"), (int, float)):
            fam[f].append(m["timestamp"] - ms)
        else:
            fam[f].append(None)
    res = {}
    for f, ds in fam.items():
        dd = [d for d in ds if d is not None]
        res[f] = {"n": len(ds), "decoded": len(dd), "example_prefix": ex[f]}
        if dd:
            res[f].update(delta_ms_p50=round(statistics.median(dd)), delta_ms_min=round(min(dd)), delta_ms_max=round(max(dd)),
                          within_m2s_p600s=sum(1 for d in dd if -2000 <= d <= 600000))
    out[k] = res
    print(k, res)
json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), indent=1)
