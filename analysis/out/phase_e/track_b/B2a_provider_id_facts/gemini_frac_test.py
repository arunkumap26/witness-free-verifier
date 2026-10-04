"""Does varint1 of the Gemini responseId carry real sub-second time? Test (pre-stated before running):
within a session, for consecutive rows (ordered by DB created_at), compare
  R_full = d(created_at) - d(sec + v1/1e6)   vs   R_sec = d(created_at) - d(sec)   vs   R_rand = d(created_at) - d(sec + U)
where U is a uniform random fraction. If v1 is a true microsecond fraction, var(R_full) < var(R_sec) < var(R_rand)
(quantization noise removed). If v1 is unrelated noise, var(R_full) ~= var(R_rand) > var(R_sec).
Also: among consecutive pairs with equal sec, share where v1 order agrees with created_at order. Aggregates only."""
import base64, collections, gzip, json, sys, datetime as dt
import numpy as np
PATH = r"C:\Swarms\data\ai-village\computer_use_turns.jsonl.gz"
MAX = int(sys.argv[1])
rng = np.random.default_rng(0)

def varint(b, i):
    r = n = 0
    while i < len(b):
        x = b[i]; r |= (x & 0x7F) << (7 * n); n += 1; i += 1
        if not x & 0x80:
            return r, i
    return None, i

rows = collections.defaultdict(list); n = 0
with gzip.open(PATH, "rt", encoding="utf-8") as f:
    for line in f:
        if "responseId" not in line:
            continue
        d = json.loads(line); am = d.get("agent_messages")
        if not isinstance(am, dict) or not am.get("responseId"):
            continue
        s = am["responseId"]
        b = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        sec = int.from_bytes(b[:4], "little"); v1, _ = varint(b, 4)
        ca = dt.datetime.fromisoformat(str(d["created_at"]).replace("Z", "+00:00")).timestamp()
        rows[d["session_id"]].append((ca, sec, v1 / 1e6))
        n += 1
        if n >= MAX:
            break
Rf, Rs, Rr = [], [], []; eq_agree = eq_n = 0
for sid, r in rows.items():
    r.sort()
    U = rng.random(len(r))
    for k in range(1, len(r)):
        dca = r[k][0] - r[k-1][0]
        Rf.append(dca - ((r[k][1] + r[k][2]) - (r[k-1][1] + r[k-1][2])))
        Rs.append(dca - (r[k][1] - r[k-1][1]))
        Rr.append(dca - ((r[k][1] + U[k]) - (r[k-1][1] + U[k-1])))
        if r[k][1] == r[k-1][1] and dca != 0:
            eq_n += 1; eq_agree += (r[k][2] > r[k-1][2]) == (dca > 0)
Rf, Rs, Rr = map(np.array, (Rf, Rs, Rr))
# robust: restrict to pairs with |Rs| < 30 s to drop session gaps / outliers, same mask for all three
m = np.abs(Rs) < 30
def boot_diff(a, b, B=500):
    idx = np.arange(len(a)); out = []
    for _ in range(B):
        j = rng.choice(idx, len(idx)); out.append(np.var(a[j]) - np.var(b[j]))
    return [float(np.quantile(out, .025)), float(np.quantile(out, .975))]
print(json.dumps({"rows": n, "sessions": len(rows), "pairs": int(len(Rs)), "pairs_used_abs_Rs_lt_30s": int(m.sum()),
  "var_R_full": float(np.var(Rf[m])), "var_R_sec": float(np.var(Rs[m])), "var_R_rand": float(np.var(Rr[m])),
  "var_full_minus_sec_CI": boot_diff(Rf[m], Rs[m]), "var_rand_minus_sec_CI": boot_diff(Rr[m], Rs[m]),
  "expected_if_true_fraction": "var_full - var_sec ~ -1/6 s^2 (-0.167); var_rand - var_sec ~ +1/6",
  "equal_sec_pairs": eq_n, "equal_sec_order_agree": eq_agree}, indent=1))
