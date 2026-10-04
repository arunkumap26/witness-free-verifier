"""Read-only HF Hub dataset search (metadata only)."""
import json, urllib.request, os

D = os.path.dirname(os.path.abspath(__file__))
QS = ["search=swe-agent", "search=sweagent", "search=openhands", "search=opendevin", "author=nebius", "author=SWE-Gym",
      "author=SWE-bench", "author=OpenHands", "author=all-hands", "author=princeton-nlp", "search=swe-smith",
      "search=swe-rebench", "search=swe-bench", "search=trajector", "search=mini-swe", "search=R2E-Gym", "author=R2E-Gym"]
allrows = {}
for q in QS:
    url = f"https://huggingface.co/api/datasets?{q}&limit=500"
    req = urllib.request.Request(url, headers={"User-Agent": "b5a-audit"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception as e:
        print(q, "ERR", e); continue
    print(q, len(d))
    for r in d:
        allrows.setdefault(r["id"], {"id": r["id"], "gated": r.get("gated"), "downloads": r.get("downloads"),
                                     "lastModified": r.get("lastModified"), "tags": r.get("tags", []), "hits": []})["hits"].append(q)
json.dump(allrows, open(os.path.join(D, "hfsearch_all.json"), "w"), indent=1)
kw = ("traj", "openhands", "swe-agent", "sweagent", "opendevin", "swe-smith", "swe-gym", "rebench", "mini")
for k, r in sorted(allrows.items()):
    if any(x in k.lower() for x in kw):
        lic = [t for t in r["tags"] if t.startswith("license:")]
        print(f"{k:80s} gated={r['gated']!s:6s} dl={r['downloads']!s:7s} {r['lastModified'][:10] if r['lastModified'] else ''} {lic}")
