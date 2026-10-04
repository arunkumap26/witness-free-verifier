"""Index every Phase C observation with its skeptic verdict, from the two verification files.
Writes analysis/out/phase_c/_index.json: one row per observation (lens, id, kind, reproduced, problem, statement, json_path)
plus per-lens candidate mechanisms and overclaim lists. Data only; no interpretation."""
import json, os

D = os.path.join(os.path.dirname(__file__), "..", "out", "phase_c")
rows, mechs, overclaims = [], [], []
for src in ("_verification_early.json", "_verification_ir.json"):
    for r in json.load(open(os.path.join(D, src), encoding="utf-8"))["lenses"]:
        lens, obs, v = r["lens"], r["obs"], r["verdict"]
        ck = {c["id"]: c for c in v["checks"]}
        for o in obs["observations"]:
            c = ck.get(o["id"])
            rows.append({"source": src, "lens": lens, "id": o["id"], "kind": o["kind"],
                         "reproduced": None if c is None else bool(c["reproduced"]),
                         "skeptic_problem": (c or {}).get("problem") or "", "skeptic_numbers": (c or {}).get("my_numbers") or "",
                         "statement": o["statement"], "numbers": o["numbers"], "json_path": o["json_path"],
                         "mechanical_explanation": o["mechanical_explanation"]})
        for m in obs["candidate_mechanisms"]:
            mechs.append({"source": src, "lens": lens, **m})
        overclaims += [{"source": src, "lens": lens, "text": t} for t in v["overclaims"]]
summary = {}
for x in rows:
    k = (x["kind"], "reproduced" if x["reproduced"] else ("not_reproduced" if x["reproduced"] is False else "unchecked"))
    summary["|".join(k)] = summary.get("|".join(k), 0) + 1
json.dump({"n_observations": len(rows), "by_kind_and_status": summary, "observations": rows,
           "candidate_mechanisms": mechs, "skeptic_overclaims": overclaims},
          open(os.path.join(D, "_index.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(len(rows), "observations;", summary, ";", len(mechs), "candidate mechanisms;", len(overclaims), "overclaims")
