"""Hypothesis (formed from 2 cookbook ids, then tested on further official examples):
created == base62(id[9:14], alphabet 0-9A-Za-z) + 1_576_800_000.  Usage: python chatcmpl_epoch.py ID:CREATED ..."""
import sys, datetime as dt, json
A = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
OFF = 1_576_800_000
for arg in sys.argv[1:]:
    s, c = arg.rsplit(":", 1)
    body = s[len("chatcmpl-"):]
    v = 0
    for ch in body[:5]:
        v = v * 62 + A.index(ch)
    pred = v + OFF
    print(json.dumps({"id": s, "body_len": len(body), "created": int(c) if c else None, "pred": pred,
                      "pred_iso": dt.datetime.fromtimestamp(pred, dt.timezone.utc).isoformat(),
                      "match": (int(c) == pred) if c else None, "diff": (int(c) - pred) if c else None}))
print("offset_iso", dt.datetime.fromtimestamp(OFF, dt.timezone.utc).isoformat())
