"""Test whether aiv_cu Gemini responseIds follow the Google 'ei' (EventId) layout used by Unfurl's parse_ei:
bytes 0-3 = LE unix seconds, then varint (thought to be fractional seconds / microseconds), then 2 more varints.
Aggregates only. Compares decoded time with the HTTP Date header (1 s resolution) on the same row.
Usage: python gemini_rid_ei_layout.py MAX_ROWS"""
import base64, collections, gzip, json, sys
from email.utils import parsedate_to_datetime
import numpy as np

PATH = r"C:\Swarms\data\ai-village\computer_use_turns.jsonl.gz"
MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 20000


def varint(b, i):
    r = n = 0
    while i < len(b):
        x = b[i]; r |= (x & 0x7F) << (7 * n); n += 1; i += 1
        if not x & 0x80:
            return r, i
    return None, i


n = 0
ok_parse = 0
v1_lt_1e6 = 0
v1_vals, consumed, nbytes = [], collections.Counter(), collections.Counter()
v2_c, v3_c = collections.Counter(), collections.Counter()
d_int, d_frac = [], []  # HTTP Date (s) minus decoded seconds; minus decoded seconds+frac
frac_order_ok = frac_order_n = 0
with gzip.open(PATH, "rt", encoding="utf-8") as f:
    for line in f:
        if "responseId" not in line:
            continue
        am = json.loads(line).get("agent_messages")
        if not isinstance(am, dict) or not am.get("responseId"):
            continue
        s = am["responseId"]
        try:
            b = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        except Exception:
            continue
        n += 1
        nbytes[len(b)] += 1
        if len(b) < 5:
            continue
        sec = int.from_bytes(b[:4], "little")
        v1, i = varint(b, 4)
        v2, i = varint(b, i) if v1 is not None else (None, i)
        v3, i = varint(b, i) if v2 is not None else (None, i)
        if v3 is None:
            continue
        ok_parse += 1
        consumed[len(b) - i] += 1  # trailing bytes left after 4 bytes + 3 varints
        v1_vals.append(v1)
        if v1 < 1_000_000:
            v1_lt_1e6 += 1
        v2_c[v2] += 1
        v3_c[v3] += 1
        hdr = ((am.get("sdkHttpResponse") or {}).get("headers") or {})
        if hdr.get("date"):
            try:
                hd = parsedate_to_datetime(hdr["date"]).timestamp()
                d_int.append(hd - sec)
                if v1 < 1_000_000:
                    d_frac.append(hd - (sec + v1 / 1e6))
            except Exception:
                pass
        if n >= MAX:
            break

v1a = np.array(v1_vals, dtype=float)
di, df = np.array(d_int), np.array(d_frac)
out = {
    "path": PATH, "rows_with_responseId": n, "decoded_nbytes": dict(nbytes),
    "parsed_4B_plus_3_varints": ok_parse,
    "trailing_bytes_after_3_varints": dict(consumed),
    "varint1_lt_1e6": v1_lt_1e6,
    "varint1_quantiles": {q: float(np.quantile(v1a, q)) for q in (0, 0.01, 0.25, 0.5, 0.75, 0.99, 1)} if len(v1a) else None,
    "varint1_uniform_check_mean_over_1e6": float(v1a.mean() / 1e6) if len(v1a) else None,
    "varint2_distinct": len(v2_c), "varint2_top": [[str(k)[:3] + "...", c] for k, c in v2_c.most_common(3)],
    "varint3_distinct": len(v3_c), "varint3_top_counts": [c for _, c in v3_c.most_common(5)],
    "http_date_minus_sec": {"n": len(di), "min": float(di.min()) if len(di) else None,
                            "p50": float(np.median(di)) if len(di) else None,
                            "lt0": int((di < 0).sum()) if len(di) else None},
    "http_date_minus_sec_plus_frac": {"n": len(df), "min": float(df.min()) if len(df) else None,
                                      "p50": float(np.median(df)) if len(df) else None,
                                      "lt_minus1": int((df < -1).sum()) if len(df) else None},
}
print(json.dumps(out, indent=1))
