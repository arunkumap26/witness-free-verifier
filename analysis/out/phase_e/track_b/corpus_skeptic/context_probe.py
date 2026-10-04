"""Corpus skeptic: where do the stray request-id / credential-like matches sit? Prints MASKED context only.

For each match it reports the file (relative), the JSON key path of the enclosing string where the file is JSONL/JSON,
and up to 60 characters of surrounding text with the matched value replaced by a mask. Credential-like values are
never printed: only their prefix class (e.g. `sk-ant-api03-`, `sk-ant-oat01-`) and length.

Run:  PYTHONIOENCODING=utf-8 python analysis/out/phase_e/track_b/corpus_skeptic/context_probe.py
Out:  analysis/out/phase_e/track_b/corpus_skeptic/context_probe.json
"""
import glob
import json
import os
import re

A = "C:/Swarms/data/acquired"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "context_probe.json")
B58C = "1-9A-HJ-NP-Za-km-z"
ANTH = re.compile(r"req_(?:vrtx_|bdrk_)?01[" + B58C + r"]{22}")
SKANT = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")


def walk(o, path, rx, hits):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, path + "/" + str(k), rx, hits)
    elif isinstance(o, list):
        for i, x in enumerate(o):
            walk(x, path + "[]", rx, hits)
    elif isinstance(o, str):
        for m in rx.finditer(o):
            hits.append((path, o, m))


def masked(s, m, label):
    a, b = m.start(), m.end()
    pre = s[max(0, a - 60):a].replace("\n", " ")
    post = s[b:b + 40].replace("\n", " ")
    return pre + "<" + label + ">" + post


def probe(files, rx, label, secret):
    out = []
    for f in files:
        lines = open(f, encoding="utf-8", errors="replace").read().splitlines() if f.endswith(".jsonl") else None
        objs = []
        if lines is not None:
            for ln in lines:
                try:
                    objs.append(json.loads(ln))
                except Exception:
                    pass
        else:
            try:
                objs = [json.load(open(f, encoding="utf-8"))]
            except Exception:
                objs = []
        for o in objs:
            hits = []
            walk(o, "", rx, hits)
            for path, s, m in hits:
                rec = {"file": os.path.relpath(f, A).replace("\\", "/"), "json_path": path,
                       "entry_type": o.get("type") if isinstance(o, dict) else None}
                if secret:
                    v = m.group(0)
                    pm = re.match(r"sk-ant-[a-z]+\d*-", v)
                    rec["value_class"] = (pm.group(0) if pm else "sk-ant-") + "...(len %d)" % len(v)
                    rec["context_masked"] = masked(s, m, "MASKED_CREDENTIAL")
                else:
                    rec["context_masked"] = masked(s, m, "REQ_ID")
                out.append(rec)
    return out


res = {}
pi = glob.glob(A + "/cli-pi-hf/**/*.jsonl", recursive=True)
res["cli-pi-hf_anthropic_req_ids"] = probe(pi, ANTH, "REQ_ID", False)
res["cli-pi-hf_sk_ant"] = probe(pi, SKANT, "", True)
tb2 = A + "/terminal-bench-2-leaderboard/hf_repo/submissions/terminal-bench/2.0"
others = []
for sub in ("Meta-Harness__Claude-Opus-4.6", "Terminus-KIRA__Claude-Opus-4.6", "JJAgent__Multiple"):
    for f in glob.glob(tb2 + "/" + sub + "/**/*", recursive=True):
        if os.path.isfile(f) and (f.endswith(".json") or f.endswith(".jsonl")):
            try:
                if ANTH.search(open(f, encoding="utf-8", errors="replace").read()):
                    others.append(f)
            except Exception:
                pass
res["tb2_non_wozcode_anthropic_req_ids"] = probe(others, ANTH, "REQ_ID", False)
cc = glob.glob(A + "/cli-claude-code-hf/**/*.jsonl", recursive=True)
odd = []
for f in cc:
    for ln in open(f, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        r = o.get("requestId")
        if isinstance(r, str) and r.startswith("req_") and not re.fullmatch(r"req_(?:vrtx_|bdrk_)?01[" + B58C + r"]{22}", r):
            odd.append({"file": os.path.relpath(f, A).replace("\\", "/"), "type": o.get("type"),
                        "shape": re.sub(r"[A-Za-z0-9]", "x", r), "len": len(r)})
res["cli-claude-code-hf_requestId_not_anthropic_layout"] = odd
cc_oauth = []
for f in cc:
    s = open(f, encoding="utf-8", errors="replace").read()
    if "CLAUDE_CODE_OAUTH_TOKEN" in s:
        i = s.index("CLAUDE_CODE_OAUTH_TOKEN")
        ctx = s[max(0, i - 80): i + 80]
        ctx = SKANT.sub("<MASKED_CREDENTIAL>", ctx).replace("\n", " ")
        cc_oauth.append({"file": os.path.relpath(f, A).replace("\\", "/"), "has_sk_ant_value_in_file": bool(SKANT.search(s)),
                         "context_masked": ctx})
res["cli-claude-code-hf_oauth_env_mentions"] = cc_oauth
json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1)
for k, v in res.items():
    print("==", k, len(v))
    for r in v[:40]:
        print("  ", json.dumps(r)[:330])
