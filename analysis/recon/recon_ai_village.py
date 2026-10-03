"""Recon: AI Village tables that may hold tool calls.
- claude_code_messages: full scan (Claude Agent SDK stream).
- computer_use_turns: first N rows. The file is ordered by random UUID `id`, so the head is a time-uniform sample.
- events: full scan of actionType counts + whether raw outputs contain tool-call structures.
Writes analysis/out/recon/ai_village.txt."""
import collections, gzip, itertools, json, os, re, sys
from datetime import datetime

D = os.environ.get("SWARMS_DATA", "C:/Swarms/data") + "/ai-village/"
OUT = os.path.join(os.path.dirname(__file__), "..", "out", "recon", "ai_village.txt")
N_CU = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000
o = open(OUT, "w", encoding="utf-8")
w = lambda *a: (print(*a, file=o), o.flush())


def rows(name, n=None):
    with gzip.open(D + name, "rt", encoding="utf-8") as fh:
        for line in itertools.islice(fh, n):
            yield json.loads(line)


def frac_digits(s):
    m = re.search(r"\.(\d+)$", s or "")
    return len(m.group(1)) if m else 0


# ---------- claude_code_messages ----------
w("## claude_code_messages (full scan)")
mt = collections.Counter(); ckeys = collections.Counter(); tools = collections.Counter()
calls, results, has_ts, tur = {}, {}, collections.Counter(), collections.Counter()
lat = []
for r in rows("claude_code_messages.jsonl.gz"):
    mt[(r["message_type"], r.get("message_subtype"))] += 1
    c = r["content"] if isinstance(r["content"], dict) else {}
    for k in c:
        ckeys[(r["message_type"], k)] += 1
    has_ts["content.timestamp" if "timestamp" in c else "no content.timestamp"] += 1
    if "toolUseResult" in c or "tool_use_result" in c:
        tur["has toolUseResult"] += 1
    msg = c.get("message") or {}
    for b in (msg.get("content") if isinstance(msg.get("content"), list) else []):
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_use":
            calls[b["id"]] = (r["created_at"], b.get("name"))
            tools[b.get("name")] += 1
        elif b.get("type") == "tool_result":
            results[b.get("tool_use_id")] = r["created_at"]
w("message types", dict(mt.most_common()))
w("content keys", dict(ckeys.most_common(60)))
w("timestamp presence", dict(has_ts), dict(tur))
w(f"tool_use {len(calls)}  tool_result {len(results)}  results w/o call {len(set(results)-set(calls))}  calls w/o result {len(set(calls)-set(results))}")
w("tools", dict(tools.most_common(40)))
P = lambda s: datetime.fromisoformat(s)
for cid, (ct, name) in calls.items():
    if cid in results:
        lat.append((P(results[cid]) - P(ct)).total_seconds())
lat.sort()
if lat:
    q = lambda f: lat[min(len(lat) - 1, int(f * len(lat)))]
    w(f"created_at(result)-created_at(call) n={len(lat)} min {lat[0]} p1 {q(.01)} p5 {q(.05)} p50 {q(.5)} p95 {q(.95)} max {lat[-1]} zero {sum(x==0 for x in lat)} neg {sum(x<0 for x in lat)}")

# ---------- computer_use_turns ----------
w(f"\n## computer_use_turns (first {N_CU} rows of {2510487}; id-ordered => time-uniform sample)")
shape = collections.Counter(); act = collections.Counter(); outerr = collections.Counter()
models = collections.Counter(); timing = collections.Counter(); tsd = collections.Counter()
usage_seen = collections.Counter(); months = collections.Counter(); bash_examples = []
for r in rows("computer_use_turns.jsonl.gz", N_CU):
    am = r.get("agent_messages")
    a = r.get("agent_action")
    tsd[frac_digits(r["created_at"])] += 1
    months[r["created_at"][:7]] += 1
    s = json.dumps(am)[:20000] if am is not None else ""
    if isinstance(am, dict) and "candidates" in am:
        shp = "gemini"; models[am.get("modelVersion")] += 1
        if "server-timing" in s: timing["gemini server-timing header"] += 1
        if "usageMetadata" in am: usage_seen["gemini usageMetadata"] += 1
    elif isinstance(am, list):
        shp = "openai-responses"
        if '"usage"' in s: usage_seen["openai usage"] += 1
    elif isinstance(am, dict) and am.get("type") == "message":
        shp = "anthropic"; models[am.get("model")] += 1
        if "usage" in am: usage_seen["anthropic usage"] += 1
    elif isinstance(am, dict) and "tool_calls" in am:
        shp = "openai-chat"
    else:
        shp = type(am).__name__
    shape[shp] += 1
    if a is None:
        kind = "none"
    elif "command" in a:
        kind = "bash"
    else:
        kind = a.get("action") or "other:" + ",".join(sorted(a))[:40]
    act[kind] += 1
    outerr[(kind if kind in ("bash", "none") else "gui", r.get("output") is not None, r.get("error") is not None)] += 1
    if kind == "bash" and len(bash_examples) < 6:
        bash_examples.append({"cmd": a["command"][:160], "out": (r.get("output") or "")[:160], "err": (r.get("error") or "")[:160], "sys": r.get("system")})
w("created_at fractional digits", dict(tsd))
w("month histogram", dict(sorted(months.items())))
w("agent_messages shape", dict(shape.most_common()))
w("models (anthropic/gemini only)", dict(models.most_common(30)))
w("timing metadata", dict(timing), "usage", dict(usage_seen))
w("agent_action kind", dict(act.most_common(40)))
w("(kind, has_output, has_error)", {str(k): v for k, v in sorted(outerr.items(), key=lambda kv: -kv[1])})
for e in bash_examples:
    w("  bash example", json.dumps(e, ensure_ascii=False))

# ---------- events ----------
w("\n## events (full scan)")
at = collections.Counter(); out_tools = collections.Counter(); talk_tc = collections.Counter()
for r in rows("events.jsonl.gz"):
    d = r.get("data") or {}
    t = d.get("actionType"); at[t] += 1
    out = d.get("output")
    if out is not None:
        s = json.dumps(out)[:50000]
        for pat in ('"tool_use"', '"function_call"', '"functionCall"', '"tool_calls"'):
            if pat in s:
                out_tools[(t, pat)] += 1
w("actionType", dict(at.most_common()))
w("raw output containing tool-call structures (actionType, marker)", {str(k): v for k, v in out_tools.most_common(30)})
print(open(OUT, encoding="utf-8").read())
