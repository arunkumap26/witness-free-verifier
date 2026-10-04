"""Inspect complete lines of a partial JSONL sample: top-level keys, and a schema summary of nested event lists.
Usage: inspect_jsonl.py <file> [max_lines]"""
import json, sys, collections

path = sys.argv[1]
maxl = int(sys.argv[2]) if len(sys.argv) > 2 else 3
raw = open(path, "rb").read()
lines = raw.split(b"\n")
complete = lines[:-1] if not raw.endswith(b"\n") else lines
recs = []
for ln in complete[:maxl]:
    if ln.strip():
        recs.append(json.loads(ln))
print("complete lines parsed:", len(recs))


def shape(v, depth=0, maxdepth=3):
    if isinstance(v, dict):
        if depth >= maxdepth:
            return "{...%d keys}" % len(v)
        return {k: shape(x, depth + 1, maxdepth) for k, x in v.items()}
    if isinstance(v, list):
        if not v:
            return "[]"
        return ["list[%d]" % len(v), shape(v[0], depth + 1, maxdepth)]
    if isinstance(v, str):
        return "str(%d): %r" % (len(v), v[:60])
    return repr(v)[:60]


r = recs[0]
print("TOP KEYS:", list(r.keys()))
for k, v in r.items():
    if k not in ("history", "trajectory", "messages", "events"):
        print(" ", k, "=>", json.dumps(shape(v, 0, 2))[:400])
for hk in ("history", "trajectory", "messages", "events"):
    if hk in r:
        h = r[hk]
        print(f"\n{hk}: len={len(h)} type0={type(h[0]).__name__}")
        kc = collections.Counter()
        for e in h:
            if isinstance(e, dict):
                kc.update(e.keys())
            elif isinstance(e, list):
                for x in e:
                    if isinstance(x, dict):
                        kc.update("pair." + k for k in x.keys())
        print(" key counts:", dict(kc))
        for e in h[:4]:
            print("  EVENT:", json.dumps(shape(e, 0, 3))[:1500])
