import json, sys
from audit import fetch_range, decode, parse_records, audit_records, raw_scan
m={o["id"]:o for o in json.load(open("meta.json"))}
targets=json.loads(open(sys.argv[1]).read())
out=[]
for repo, paths in targets.items():
    sha=m[repo]["sha"]
    for p in paths:
        r={"id":repo,"path":p}
        try:
            raw=fetch_range(repo, sha, p, 600_000)
            text=decode(raw,p); recs,how=parse_records(text,p)
            r["bytes_read"]=len(raw); r["parse"]=how; r["audit"]=audit_records(recs); r["raw_scan"]=raw_scan(text)
            r["first_record_keys"]=list(recs[0].keys())[:20] if recs and isinstance(recs[0],dict) else None
            r["first_record_excerpt"]=json.dumps(recs[0])[:700] if recs else text[:700]
        except Exception as e:
            r["error"]=repr(e)[:200]
        out.append(r)
        print(json.dumps(r)[:1800]); print()
json.dump(out, open(sys.argv[2],"w"), indent=1)
