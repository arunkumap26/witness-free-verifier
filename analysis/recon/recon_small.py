"""Recon: Who&When (embedded tool results in multi-agent chat) and collusion-wiki (server-side logs).
Writes analysis/out/recon/small.txt."""
import collections, glob, gzip, json, os, re

ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
OUT = os.path.join(os.path.dirname(__file__), "..", "out", "recon", "small.txt")
o = open(OUT, "w", encoding="utf-8")
w = lambda *a: print(*a, file=o)

# ---------- Who&When ----------
w("## Who&When")
for split in ("Algorithm-Generated", "Hand-Crafted"):
    fs = glob.glob(f"{ROOT}/who-and-when/Who&When/{split}/*.json")
    names = collections.Counter(); roles = collections.Counter(); exitc = collections.Counter()
    nmsg = 0; tool_like = collections.Counter(); has_ts = 0; mistake_names = collections.Counter()
    for f in fs:
        d = json.load(open(f, encoding="utf-8"))
        mistake_names[d.get("mistake_agent")] += 1
        for m in d["history"]:
            nmsg += 1
            names[m.get("name")] += 1
            roles[m.get("role")] += 1
            if any(k in m for k in ("timestamp", "time", "created_at")):
                has_ts += 1
            c = m.get("content") or ""
            mm = re.match(r"exitcode: (\d+)", c)
            if mm:
                exitc[mm.group(1)] += 1
            if re.search(r"```(python|sh|bash)", c):
                tool_like["code block in message"] += 1
            if c.startswith("I typed") or c.startswith("I clicked") or "Here is a screenshot" in c:
                tool_like["websurfer action report"] += 1
    w(f"### {split}: files {len(fs)}, messages {nmsg}, messages with any timestamp key {has_ts}")
    w("  name", dict(names.most_common(25)))
    w("  role", dict(roles.most_common(25)))
    w("  'exitcode: N' results", dict(exitc))
    w("  tool-like", dict(tool_like))
    w("  mistake_agent", dict(mistake_names.most_common(15)))

# ---------- collusion-wiki ----------
w("\n## collusion-wiki full-wiki-logs")
ev = [json.loads(l) for l in open(f"{ROOT}/collusion-wiki/full-wiki-logs/events.jsonl", encoding="utf-8")]
w("events", len(ev))
w("event_type", dict(collections.Counter(e.get("event_type") for e in ev).most_common()))
w("time_grade", dict(collections.Counter(e.get("time_grade") for e in ev).most_common()))
w("request_action", dict(collections.Counter(e.get("request_action") for e in ev).most_common(20)))
w("success_observed", dict(collections.Counter(str(e.get("success_observed")) for e in ev).most_common()))
w("event keys", dict(collections.Counter(k for e in ev for k in e).most_common()))
rv = [json.loads(l) for l in open(f"{ROOT}/collusion-wiki/full-wiki-logs/revisions.jsonl", encoding="utf-8")]
w("revisions", len(rv), "time_grade", dict(collections.Counter(r.get("time_grade") for r in rv).most_common()))
w("revision keys", sorted({k for r in rv for k in r}))
tool_words = collections.Counter()
for r in rv:
    b = r.get("body") or ""
    for pat, lab in ((r"\btool_use\b|\btool_result\b", "tool_use/tool_result"), (r"\bexit code\b|\bexitcode\b", "exit code"),
                     (r"\$ (curl|ls|cat|git|python)\b", "shell prompt"), (r"```", "code fence")):
        if re.search(pat, b, re.I):
            tool_words[lab] += 1
w("revision bodies mentioning tool-ish text", dict(tool_words))
print(open(OUT, encoding="utf-8").read())
