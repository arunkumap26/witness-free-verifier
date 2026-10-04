"""Decode example ids quoted in official vendor docs / SDK sources with the Phase C layouts.
Usage: python decode_examples.py ID [ID ...]   (prints JSON lines)"""
import base64, datetime as dt, json, sys

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58I = {c: i for i, c in enumerate(B58)}


def iso(ms):
    try:
        return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()
    except Exception:
        return None


def anth(s):
    body = s.rsplit("_", 1)[1]
    out = {"id": s, "family": "anthropic", "body_len": len(body), "starts_01": body[:2] == "01"}
    if body[:2] != "01" or any(c not in B58I for c in body[2:]):
        out["note"] = "not <prefix>_01 + base58"
        return out
    v = 0
    for c in body[2:]:
        v = v * 58 + B58I[c]
    out["bits"] = v.bit_length()
    out["fits_128"] = v < (1 << 128)
    top = v >> 80
    out["top48_ms"] = top
    out["top48_iso"] = iso(top)
    out["version_nibble(bits76-79)"] = (v >> 76) & 0xF
    out["variant(bits62-63)"] = (v >> 62) & 0x3
    out["looks_uuidv7"] = out["version_nibble(bits76-79)"] == 7 and out["variant(bits62-63)"] == 2
    out["looks_uuidv4"] = out["version_nibble(bits76-79)"] == 4 and out["variant(bits62-63)"] == 2
    return out


def openai_hex(s):
    b = s.split("_", 1)[1]
    out = {"id": s, "family": "openai_item_hex", "len": len(b)}
    try:
        if len(b) == 48:
            out["sec"] = int(b[:8], 16); out["iso"] = iso(out["sec"] * 1000); out["layout"] = "hex48_time_first"
        elif len(b) == 50 and b[16] == "0":
            out["sec"] = int(b[18:26], 16); out["iso"] = iso(out["sec"] * 1000); out["layout"] = "hex50_prefix16_00_time"
        else:
            out["layout"] = "other"
    except ValueError:
        out["layout"] = "not_hex"
    return out


def gemini_rid(s):
    out = {"id": s, "family": "gemini_response_id"}
    try:
        b = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except Exception as e:
        out["note"] = f"not base64url: {e}"
        return out
    out["nbytes"] = len(b)
    if len(b) >= 4:
        sec = int.from_bytes(b[:4], "little")
        out["le_sec"] = sec; out["iso"] = iso(sec * 1000)
    return out


for s in sys.argv[1:]:
    if s.split("_", 1)[0] in ("req", "msg", "toolu", "srvtoolu", "msgbatch", "file", "compl") and "_" in s:
        r = anth(s)
    elif s.split("_", 1)[0] in ("resp", "fc", "msg", "rs", "ws", "item") and "_" in s:
        r = openai_hex(s)
    else:
        r = gemini_rid(s)
    print(json.dumps(r))
