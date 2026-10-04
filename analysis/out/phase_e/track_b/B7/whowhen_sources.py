"""B7: which upstream benchmark each Who&When task comes from, inferred from question_ID shape.

GAIA task ids are UUIDs (36 chars); AssistantBench ids are 64-hex. This is an inference from id shape only, not a
lookup against either benchmark's id list. Reads only the question_ID and ground-truth key presence (no text).

Output: analysis/out/phase_e/track_b/B7/whowhen_sources.json
Run:    python analysis/out/phase_e/track_b/B7/whowhen_sources.py
"""
import glob, json, os, re, collections

ROOT = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "who-and-when", "Who&When")
OUT = os.path.join(os.path.dirname(__file__), "whowhen_sources.json")
res = {}
for sub in ("Algorithm-Generated", "Hand-Crafted"):
    shape, gt_key = collections.Counter(), collections.Counter()
    for f in glob.glob(os.path.join(ROOT, sub, "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        q = str(d.get("question_ID", ""))
        shape["uuid36_gaia_shaped" if re.fullmatch(r"[0-9a-f-]{36}", q) else
              "hex64_assistantbench_shaped" if re.fullmatch(r"[0-9a-f]{64}", q) else f"other_len{len(q)}"] += 1
        gt_key["has_question"] += "question" in d
        gt_key["has_ground_truth_or_groundtruth"] += ("ground_truth" in d) or ("groundtruth" in d)
    res[sub] = {"question_id_shape": dict(shape), "keys": dict(gt_key)}
json.dump({"script": "analysis/out/phase_e/track_b/B7/whowhen_sources.py", "source": ROOT,
           "inference": "id shape only; UNVERIFIED against GAIA/AssistantBench id lists", "subsets": res},
          open(OUT, "w", encoding="utf-8"), indent=1)
print(open(OUT, encoding="utf-8").read())
