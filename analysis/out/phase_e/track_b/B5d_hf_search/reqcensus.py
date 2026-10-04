"""Request-id census on the sampled file of every HF candidate whose sample carried request ids.
Decoder copied from analysis/out/phase_e/track_b/B2a_provider_id_facts/decode_examples.py::anth (unchanged logic):
body after the last '_' must be '01' + base58; value's top 48 bits = ms epoch when the layout is UUIDv7-like.
Agreement rule identical to B4 (analysis/probes/phase_e_b4_inventory.py L31, L236): off = FIRST carrying event ts - embedded ms, agrees iff -2 s <= off <= +600 s."""
import json, re, datetime as dt
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from audit import fetch_range, decode, parse_records

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58I = {c: i for i, c in enumerate(B58)}


def anth_ms(s):
    body = s.rsplit("_", 1)[1]
    if body[:2] != "01" or any(c not in B58I for c in body[2:]):
        return None, False
    v = 0
    for c in body[2:]:
        v = v * 58 + B58I[c]
    uuidv7 = ((v >> 76) & 0xF) == 7 and ((v >> 62) & 0x3) == 2
    return v >> 80, uuidv7


def family(s):
    if re.fullmatch(r"req_vrtx_[A-Za-z0-9]+", s):
        return "anthropic_vertex"
    if re.fullmatch(r"req_01[1-9A-HJ-NP-Za-km-z]{20,30}", s):
        return "anthropic_first_party_shape"
    if re.fullmatch(r"req_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", s):
        return "req_uuid"
    if re.fullmatch(r"req_[0-9a-f]{24,40}", s):
        return "req_hex"
    if s.startswith("req_"):
        return "req_other"
    return "non_req:" + (s.split("_")[0][:8] if "_" in s else ("uuid" if re.fullmatch(r"[0-9a-f-]{36}", s) else "other"))


def ts_ms(v):
    try:
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000
    except Exception:
        return None


def census(item):
    rid, sha, path = item
    out = {"id": rid, "path": path, "families": Counter(), "n_records_with_rid": 0, "decodable": 0, "uuidv7": 0,
           "agree": 0, "deltas_s": [], "unit": "decodable/uuidv7/agree count DISTINCT request ids; off_s = first carrying event ts - embedded time", "models": Counter(), "msg_id_families": Counter()}
    try:
        raw = fetch_range(rid, sha, path)
        recs, _ = parse_records(decode(raw, path), path)
    except Exception as e:
        out["error"] = repr(e)[:150]
        return out
    first = {}
    for r in recs:
        if not isinstance(r, dict):
            continue
        q = r.get("requestId") or r.get("request_id")
        if not isinstance(q, str) or not q:
            continue
        out["n_records_with_rid"] += 1
        out["families"][family(q)] += 1
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        if msg.get("model"):
            out["models"][msg["model"]] += 1
        if isinstance(msg.get("id"), str):
            out["msg_id_families"][msg["id"][:6]] += 1
        ms, v7 = anth_ms(q) if q.startswith("req_") else (None, False)
        if ms is not None:
            em = ts_ms(r.get("timestamp", "")) if isinstance(r.get("timestamp"), str) else None
            prev = first.get(q)
            if prev is None:
                first[q] = [ms, v7, em]
            elif em is not None and (prev[2] is None or em < prev[2]):
                prev[2] = em
    for q, (ms, v7, em) in first.items():
        out["decodable"] += 1
        out["uuidv7"] += int(v7)
        if em is not None and v7:
            off = (em - ms) / 1000
            out["deltas_s"].append(round(off, 3))
            if -2 <= off <= 600:
                out["agree"] += 1
    out["families"] = dict(out["families"]); out["models"] = dict(out["models"].most_common(4)); out["msg_id_families"] = dict(out["msg_id_families"])
    ds = sorted(out["deltas_s"])
    out["delta_s_quantiles"] = [ds[0], ds[len(ds) // 2], ds[-1]] if ds else None
    del out["deltas_s"]
    return out


if __name__ == "__main__":
    rows = {r["id"]: r for r in json.load(open("classified.json"))}
    ids = json.load(open("req_ids_list.json"))
    items = [(i, rows[i]["sha"], rows[i]["sample_path"]) for i in ids]
    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(census, items))
    json.dump(res, open("reqcensus.json", "w"), indent=1)
    tot = Counter()
    for r in res:
        for k, v in r["families"].items():
            tot[k] += v
    print("record families", tot)
    print("datasets by dominant family", Counter(max(r["families"], key=r["families"].get) if r["families"] else "none" for r in res))
    print("decodable", sum(r["decodable"] for r in res), "uuidv7", sum(r["uuidv7"] for r in res), "agree", sum(r["agree"] for r in res))
