"""Recon: URLQuery agent-activity catalog v5 (data/urlquery-agent-activity) and its overlap with our other corpora.
Writes analysis/out/recon/urlquery.txt. Read-only."""
import collections, glob, gzip, json, os, re
import pandas as pd

ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
U = f"{ROOT}/urlquery-agent-activity/urlquery-agent-activity-2026-09-22-v5"
OUT = os.path.join(os.path.dirname(__file__), "..", "out", "recon", "urlquery.txt")
o = open(OUT, "w", encoding="utf-8")
w = lambda *a: print(*a, file=o)

a = pd.read_csv(f"{U}/all-reports.csv")
s = pd.read_csv(f"{U}/report-sources.csv")
m = json.load(open(f"{U}/methods.json", encoding="utf-8"))
w("## catalog")
w("rows", len(a), "distinct report_id", a.report_id.nunique(), "columns", list(a.columns))
w("timestamp_precision", a.timestamp_precision.value_counts().to_dict())
w("disposition", a.disposition.value_counts().to_dict())
w("broad_class x confidence\n", pd.crosstab(a.broad_class, a.confidence.fillna("none")).to_string())
d = pd.to_datetime(a.report_date_utc, utc=True)
w("date range", d.min().isoformat(), d.max().isoformat())
w("reports by month", d.dt.strftime("%Y-%m").value_counts().sort_index().to_dict())
w("source assignments", len(s), "top sources", s.data_source.value_counts().head(15).to_dict())
w("methods", len(m), "by broad_class", dict(collections.Counter(x.get("broad_class") for x in m)))
w("content fields present: none (no report JSON, request URLs, bodies or screenshots; README says links + metadata only)")
dup_ts = a.report_date_utc.value_counts()
w("reports sharing an exact second-precision timestamp with >=1 other report:", int(dup_ts[dup_ts > 1].sum()))

w("\n## overlap with collusion-wiki revisions")
ids = set(a.report_id)
markers = {mk: x.get("label") for x in m for mk in (x.get("markers") or [])}
rv = [json.loads(l) for l in open(f"{ROOT}/collusion-wiki/full-wiki-logs/revisions.jsonl", encoding="utf-8")]
cited = [(r["rev_id"], r["time"], re.findall(r"urlquery\.net/report/([0-9a-f-]{36})", r.get("body") or "")) for r in rv
         if "urlquery.net" in (r.get("body") or "")]
w("revisions mentioning urlquery.net", len(cited), "report ids cited", sum(len(c[2]) for c in cited),
  "of which in catalog", sum(i in ids for c in cited for i in c[2]))
hb = [r for r in rv if "httpbin.org/base64" in (r.get("body") or "")]
w("revisions mentioning httpbin.org/base64", len(hb), "pages", len({r["page_key"] for r in hb}),
  "time range", min(r["time"] for r in hb) if hb else None, max(r["time"] for r in hb) if hb else None)
any_marker = sum(1 for r in rv if any(mk in (r.get("body") or "") for mk in markers))
w(f"revisions mentioning >=1 catalog source marker: {any_marker} of {len(rv)} (markers from {len(markers)} method entries)")
by_label = collections.Counter(lab for r in rv for mk, lab in markers.items() if mk in (r.get("body") or ""))
w("  by method label (a revision can count under several):", dict(by_label.most_common(12)))

w("\n## footprint in tool-call corpora (substring counts)")
pats = {"urlquery.net": re.compile(r"urlquery\.net"), "httpbin.org/base64": re.compile(r"httpbin\.org/base64")}
for name, files in (("swe-chat-pinned transcripts", glob.glob(f"{ROOT}/swe-chat-pinned/transcripts/*.jsonl")),
                    ("claude-code-local jsonl", glob.glob(f"{ROOT}/claude-code-local/**/*.jsonl", recursive=True))):
    hits = collections.Counter()
    for f in files:
        txt = open(f, encoding="utf-8", errors="replace").read()
        for k, rx in pats.items():
            hits[k] += bool(rx.search(txt))
    w(f"{name}: files {len(files)}; files containing", dict(hits))
for t in ("claude_code_messages", "events", "chat_messages", "computer_use_turns"):
    hits = collections.Counter()
    with gzip.open(f"{ROOT}/ai-village/{t}.jsonl.gz", "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            for k, rx in pats.items():
                if rx.search(line):
                    hits[k] += 1
    w(f"ai-village {t}: rows containing", dict(hits))
o.close()
print(open(OUT, encoding="utf-8").read())
