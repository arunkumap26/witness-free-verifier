"""Phase C lens: two EXTERNAL witnesses of the same agent campaigns, no transcript (post-incident setting).

Witness 1: collusion-wiki full-wiki-logs (revisions.jsonl, events.jsonl, pages.jsonl, labels.jsonl).
Witness 2: urlquery agent-activity catalog v5 (all-reports.csv, report-sources.csv, methods.json).

Sections
  S1 multi-clock consistency inside collusion-wiki
  S2 cross-witness temporal precedence (wiki mention of a catalog source vs urlquery reports for that source)
  S3 urlquery burst structure and alignment with wiki save bursts
  S4 narrated timing claims in wiki bodies (and epoch stamps in page names) vs the revision's own server clock

Writes RAW COUNTS ONLY to analysis/out/phase_c/ext_witness.json. Interpretation lives in analysis/notes/ext_witness.md.
Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_ext_witness
"""
import collections
import csv
import datetime as dt
import json
import os
import re
import urllib.parse

import numpy as np

from analysis.lib import stats

ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
WIKI = f"{ROOT}/collusion-wiki/full-wiki-logs"
UQ = f"{ROOT}/urlquery-agent-activity/urlquery-agent-activity-2026-09-22-v5"
OUT = os.path.join(os.path.dirname(__file__), "..", "out", "phase_c", "ext_witness.json")

DAY = 86400
# ---------------------------------------------------------------------------------------------------------------
# Pre-registered choices. Fixed before any outcome below was computed; each carries its reason.
# ---------------------------------------------------------------------------------------------------------------
PREREG = {
    "clock_violation_rule": {
        "value": "violation_any: later_clock - earlier_clock < 0; violation_beyond_uncertainty: < -uncertainty_seconds (row field)",
        "reason": "clocks are second-precision strings; the export states uncertainty_seconds per row, so a 1-step negative can be rounding"},
    "precedence_windows_s": {"value": [3600, 86400, 604800], "reason": "1h/24h/7d named in the lens brief"},
    "null_shifts_days": {"value": [-14, -7, 7, 14],
                         "reason": "multiples of 7 days keep time-of-day and weekday; brief suggested +-7d; two magnitudes to see sensitivity"},
    "n_source_permutations": {"value": 20, "reason": "enough for a stable mean of a permutation null; seed = stats.SEED"},
    "burst_gap_s": {"value": 60,
                    "reason": "smallest round gap above 1 s timestamp precision; chosen before looking at any gap distribution"},
    "alignment_windows_s": {"value": [300, 3600], "reason": "5 min ~ one agent step, 1 h ~ one task episode; chosen a priori"},
    "per_bucket_min_events": {"value": 30, "reason": "below this a per-source rate CI is too wide to read"},
    "same_second_rule": {"value": "a report at the same second as the save is in neither the before nor the after window; counted separately",
                         "reason": "second precision cannot order them"},
    "marker_matching": {"value": "case-insensitive substring of catalog markers in body, unquote(body), unquote(unquote(body))",
                        "reason": "wiki bodies carry proxy URLs with percent-encoded targets"},
    "new_mention_rule": {"value": "a (page, source) mention event is a revision whose source set contains the source and the previous held revision of the same page does not",
                         "reason": "bodies accumulate; carry-forward copies are not new evidence"},
    "claim_context_chars_before": {"value": 32, "reason": "about five words; enough for 'shared container UTC ' style qualifiers"},
    "claim_suffix_chars": {"value": 6, "reason": "catches ' UTC', 'Z', ' GMT' immediately after a time"},
    "claim_keywords_real": {"value": ["utc", "gmt", "terminal", "container", "wall", "real", "server", "host", "created_at", "updated_at"],
                            "reason": "words that name a wall/server clock in the lens examples ('shared UTC', 'terminal UTC')"},
    "claim_keywords_task": {"value": ["task", "platform", "timer", "countdown", "due", "projected", "expected", "eta", "deadline",
                                      "remaining", "elapsed"],
                            "reason": "words that name the simulated task clock or a future projection in the lens examples"},
    "claim_class_rule": {"value": "suffix UTC/GMT/Z -> real; else the keyword closest before the time decides real vs task; none -> unqualified",
                         "reason": "a priori rule; no tuning"},
    "claims_inside_urls": {"value": "times/ISO stamps inside an http(s) URL token are not claims; epochs inside URLs are kept as a separate class epoch_url",
                           "reason": "URL parameters can be server-generated (expiry tokens) rather than narrated"},
    "epoch_forms": {"value": "10 digits (optional .fraction), 13, 16 or 19 digits, leading digits 17 or 18 (1.7e9..1.9e9 s)",
                    "reason": "python time.time(), JS Date.now(), us and ns stamps"},
    "naive_iso_timezone": {"value": "UTC", "reason": "no offset given; UTC is the server clock's zone"},
    "tod_fold": {"value": "time-of-day claims compared modulo 24h, delta folded into [-12h, +12h)",
                 "reason": "date not stated; assume the claim refers to the instant nearest the save"},
    "claim_delta_bins_s": {"value": [-1e18, -DAY, -3600, -60, 0, 1, 60, 3600, DAY, 1e18],
                           "reason": "edges at 1 s (server uncertainty), 1 min (HH:MM truncation), 1 h, 1 day"},
    "impossible_claim_tolerances_s": {"value": [1, 60, 3600],
                                      "reason": "claim later than its own save by more than this is counted as physically impossible at that tolerance"},
    "save_clock_for_claims": {"value": "revision field 'time' (winning clock)", "reason": "the export's own adjudicated save time"},
    "cluster_units": {"value": {"wiki": "page_key (also label for page-name epochs)", "urlquery_burst": "(source, UTC date) or UTC date"},
                      "reason": "brief: session or page as unit"},
}

# ---------------------------------------------------------------------------------------------------------------
# POST-HOC additions. Added after run 1 had been inspected; each says what in run 1 motivated it.
# Numbers produced under these keys are exploratory and need a holdout before being read as a result.
# ---------------------------------------------------------------------------------------------------------------
POSTHOC = {
    "local_shift_nulls_s": {"value": [-86400, -14400, -7200, 7200, 14400, 86400],
                            "motivated_by": "run 1 +-7/14 d shift null was ~0 because each source's catalog activity sits in a few days; "
                                            "stricter local nulls test whether alignment is tighter than the day/hour scale"},
    "rcs_order_inversions": {"value": "per page, sort held revisions by RCS minor number (storage commit order); count adjacent pairs whose 'time' decreases",
                             "motivated_by": "run 1 found 414 revisions on 5 pages where rcs minor != seq"},
    "claim_tense_window_chars": {"value": 48, "motivated_by": "run 1 examples of real-clock times after their own save read as projections"},
    "claim_tense_keywords": {"value": {
        "forward": ["due", "project", "projects", "projected", "expect", "expected", "estimate", "estimated", "predict", "predicted", "next",
                    "will", "eta", "arrival", "until", "scheduled", "deadline", "when"],
        "past": ["appeared", "arrived", "confirmed", "posted", "observed", "saw", "seen", "received", "got", "was", "were", "happened",
                 "decoded", "returned", "fired", "landed", "came"],
        "present": ["current", "currently", "now"]},
        "rule": "closest tense keyword before the time within the window decides; none -> untensed; '~' or 'approx' within 3 chars before -> approx flag",
        "motivated_by": "run 1 examples"},
    "epoch_roundness": {"value": "integer-second epoch with sec % 100 in {0, 1, 99}; 3% expected under uniform last two digits",
                        "motivated_by": "run 1 examples of epochs later than their own save looked hand-typed (…000, …999, …001)"},
    "epoch_has_fraction": {"value": "10-digit epoch followed by .digits (python time.time() print form)", "motivated_by": "run 1 examples"},
    "task_utc_mapping": {"value": "pairs 'task[ -clock] HH:MM:SS <=|~|is|was|at> ... UTC ~HH:MM(:SS)' within 60 chars; offset = (utc - task) mod 24h; "
                                  "per (page,label) with >=2 distinct pairs: spread = circular range of offsets",
                         "thresholds_s": [60, 600], "motivated_by": "run 1 examples show agents narrating task-clock to UTC mappings"},
}

SHIFTS = [d * DAY for d in PREREG["null_shifts_days"]["value"]]
LOCAL_SHIFTS = POSTHOC["local_shift_nulls_s"]["value"]
WINDOWS = PREREG["precedence_windows_s"]["value"]
GAP = PREREG["burst_gap_s"]["value"]
ALIGN_W = PREREG["alignment_windows_s"]["value"]
BINS = PREREG["claim_delta_bins_s"]["value"]
TOLS = PREREG["impossible_claim_tolerances_s"]["value"]
BIN_NAMES = ["le_-1d", "-1d_-1h", "-1h_-60s", "-60s_0", "eq0_to_1s", "1s_60s", "60s_1h", "1h_1d", "gt_1d"]

# methods.json label -> report-sources.csv data_source display bucket (hand map, every marker-bearing method must appear)
BUCKET = {
    "Thrill Data": "Thrill Data", "Thrill proxy references": "Thrill Data",
    "Thai NSO": "Thai NSO", "Thai NSO proxy references": "Thai NSO", "Thai ONCB": "Thai ONCB",
    "UNCTAD": "UNCTAD", "UNCTAD proxy references": "UNCTAD",
    "AIHW": "AIHW", "AIHW proxy references": "AIHW",
    "MAX budget documents": "MAX budget documents", "MAX exact PDF Q2": "MAX budget documents", "MAX exact PDF Q3": "MAX budget documents",
    "DataUSA": "DataUSA", "DataUSA proxy references": "DataUSA", "USAspending": "USAspending",
    "IHME health data": "IHME", "IHME proxy references": "IHME", "US Census API": "US Census API",
    "Mapillary API": "Mapillary", "Mapillary API proxy references": "Mapillary",
    "Drivelah research": "Drivelah", "Drivelah proxy references": "Drivelah", "GBBC Canada 2024": "GBBC",
    "SND Airtable view": "SND Airtable", "SND Airtable share": "SND Airtable", "SND Airtable base": "SND Airtable",
    "NZ vegetation API": "NZ vegetation API", "Iowa thyroid statistics": "Iowa thyroid statistics",
    "SEC county statistics": "SEC county data",
    "UNM Valmora archive": "UNM digital library", "UNM proxy references": "UNM digital library",
    "Maryland school report cards": "Maryland school report cards",
    "Maryland school-query proxy references": "Maryland school report cards",
    "IEA charts": "IEA", "IEA statistical pages and tools": "IEA",
    "School history": "Woodlands House School", "Woodlands House School history": "Woodlands House School",
    "Clark economics newsletter": "Clark economics newsletter",
    "NYSED enrollment institution": "NYSED enrollment institution",
    "Yahoo CYBR archived history": "Yahoo CYBR archived history", "Data for India chart assets": "Data for India",
}


def P(s):
    """ISO-8601 string -> integer epoch seconds (UTC)."""
    if s is None or s == "":
        return None
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def cr(num_by, den_by):
    """cluster_rate over dicts keyed by cluster id."""
    keys = sorted(den_by)
    return stats.cluster_rate([num_by.get(k, 0) for k in keys], [den_by[k] for k in keys])


def wil(k, n):
    p, lo, hi = stats.wilson(k, n)
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


def bin_counts(deltas):
    c, _ = np.histogram(np.asarray(deltas, dtype=float), bins=BINS)
    return dict(zip(BIN_NAMES, [int(x) for x in c]))


def bursts(times, gap):
    """Sorted int array -> list of (start_idx, end_idx_inclusive) runs with consecutive gaps <= gap."""
    out = []
    if len(times) == 0:
        return out
    s = 0
    for i in range(1, len(times)):
        if times[i] - times[i - 1] > gap:
            out.append((s, i - 1))
            s = i
    out.append((s, len(times) - 1))
    return out


def count_in(sorted_arr, lo, hi, lo_closed=True, hi_closed=False):
    a = np.searchsorted(sorted_arr, lo, "left" if lo_closed else "right")
    b = np.searchsorted(sorted_arr, hi, "right" if hi_closed else "left")
    return b - a


J = {"prereg": PREREG, "inputs": {"wiki_dir": WIKI, "urlquery_dir": UQ}}

# ===============================================================================================================
# Load wiki
# ===============================================================================================================
REV_CLOCKS = ["time", "request_time", "success_time", "write_date", "archived_at", "recent_changes_time"]
revs = []
with open(f"{WIKI}/revisions.jsonl", encoding="utf-8") as fh:
    for line in fh:
        r = json.loads(line)
        d = {k: r.get(k) for k in ("rev_id", "page_key", "wiki", "name", "seq", "rcs_rev", "label", "time_grade", "winning_clock",
                                    "uncertainty_seconds", "body", "request_action", "ip16")}
        d["t"] = {c: P(r.get(c)) for c in REV_CLOCKS}
        revs.append(d)
by_page = collections.defaultdict(list)
for r in revs:
    by_page[r["page_key"]].append(r)
for k in by_page:
    by_page[k].sort(key=lambda r: r["seq"])
wiki_times = np.sort(np.array([r["t"]["time"] for r in revs], dtype=np.int64))
WMIN, WMAX = int(wiki_times[0]), int(wiki_times[-1])
J["inputs"]["wiki_revisions"] = len(revs)
J["inputs"]["wiki_pages_in_revisions"] = len(by_page)
J["inputs"]["wiki_save_time_range"] = [dt.datetime.fromtimestamp(WMIN, dt.timezone.utc).replace(tzinfo=None).isoformat() + "Z", dt.datetime.fromtimestamp(WMAX, dt.timezone.utc).replace(tzinfo=None).isoformat() + "Z"]

events = [json.loads(l) for l in open(f"{WIKI}/events.jsonl", encoding="utf-8")]
pages = [json.loads(l) for l in open(f"{WIKI}/pages.jsonl", encoding="utf-8")]
labels = [json.loads(l) for l in open(f"{WIKI}/labels.jsonl", encoding="utf-8")]
J["inputs"]["wiki_events"] = len(events)
J["inputs"]["wiki_events_by_type"] = dict(collections.Counter(e["event_type"] for e in events))

# ===============================================================================================================
# S1 multi-clock consistency
# ===============================================================================================================
S1 = {}
avail = collections.Counter(tuple(c for c in REV_CLOCKS if r["t"][c] is not None) for r in revs)
S1["revision_clock_availability"] = [{"clocks_present": list(k), "n": v} for k, v in avail.most_common()]
S1["revision_uncertainty_seconds"] = dict(collections.Counter(str(r["uncertainty_seconds"]) for r in revs))
S1["revision_winning_clock"] = dict(collections.Counter(r["winning_clock"] for r in revs))

pair = {}
present = [c for c in REV_CLOCKS if any(r["t"][c] is not None for r in revs)]
for i, a in enumerate(present):
    for b in present[i + 1:]:
        d = np.array([r["t"][b] - r["t"][a] for r in revs if r["t"][a] is not None and r["t"][b] is not None], dtype=float)
        if len(d) == 0:
            continue
        vc = collections.Counter(int(x) for x in d if -5 <= x <= 5)
        pair[f"{b}_minus_{a}"] = {
            "n": int(len(d)), "eq0": int((d == 0).sum()), "gt0": int((d > 0).sum()), "lt0": int((d < 0).sum()),
            "abs_eq1": int((np.abs(d) == 1).sum()), "abs_gt1": int((np.abs(d) > 1).sum()), "abs_gt60": int((np.abs(d) > 60).sum()),
            "abs_gt3600": int((np.abs(d) > 3600).sum()), "abs_gt86400": int((np.abs(d) > 86400).sum()),
            "values_in_-5_5": {str(k): vc[k] for k in sorted(vc)}, "describe": stats.describe(d),
            "abs_log_histogram": stats.log_histogram(np.abs(d))}
S1["revision_pairwise_differences_s"] = pair

CONSTRAINTS = [
    ("request_time", "success_time", "the request must arrive before the server logs its success"),
    ("request_time", "write_date", "the page-file write cannot precede the request that caused it"),
    ("request_time", "archived_at", "the archive copy cannot precede the request"),
    ("success_time", "archived_at", "the archive copy cannot precede the logged success"),
    ("write_date", "archived_at", "the archive copy cannot precede the write it archives"),
]
cons = {}
for a, b, why in CONSTRAINTS:
    num_any, num_unc, den = collections.Counter(), collections.Counter(), collections.Counter()
    ex = []
    for r in revs:
        ta, tb = r["t"][a], r["t"][b]
        if ta is None or tb is None:
            continue
        d = tb - ta
        den[r["page_key"]] += 1
        if d < 0:
            num_any[r["page_key"]] += 1
            if len(ex) < 15:
                ex.append({"rev_id": r["rev_id"], "delta_s": d})
        if d < -(r["uncertainty_seconds"] or 0):
            num_unc[r["page_key"]] += 1
    n = sum(den.values())
    cons[f"{a}<={b}"] = {"reason": why, "n_rows": n, "n_pages": len(den),
                         "violation_any": wil(sum(num_any.values()), n), "violation_any_page_clustered": cr(num_any, den),
                         "violation_beyond_uncertainty": wil(sum(num_unc.values()), n),
                         "violation_beyond_uncertainty_page_clustered": cr(num_unc, den), "examples": ex}
S1["revision_ordering_constraints"] = cons

# which clock does 'time' equal
eqs = {}
for c in present:
    if c == "time":
        continue
    n = sum(1 for r in revs if r["t"][c] is not None)
    k = sum(1 for r in revs if r["t"][c] is not None and r["t"][c] == r["t"]["time"])
    eqs[f"time_eq_{c}"] = {"k": k, "n": n}
eqs["by_time_grade"] = {}
for g in sorted({r["time_grade"] for r in revs}):
    sub = [r for r in revs if r["time_grade"] == g]
    eqs["by_time_grade"][g] = {c: sum(1 for r in sub if r["t"][c] is not None and r["t"][c] == r["t"]["time"]) for c in present if c != "time"}
    eqs["by_time_grade"][g]["n"] = len(sub)
S1["time_field_equalities"] = eqs

# quantization: second-of-minute and minute-of-hour
quant = {}
for c in present:
    v = np.array([r["t"][c] for r in revs if r["t"][c] is not None], dtype=np.int64)
    som = np.bincount(v % 60, minlength=60)
    moh = np.bincount((v // 60) % 60, minlength=60)
    quant[c] = {"n": int(len(v)), "second_of_minute_chi2_uniform": stats.chi2_uniform(som),
                "at_second_00": int(som[0]), "second_of_minute_counts": [int(x) for x in som],
                "minute_of_hour_chi2_uniform": stats.chi2_uniform(moh), "even_seconds": int((v % 2 == 0).sum())}
S1["revision_clock_quantization"] = quant

# per-page monotonicity in seq order, rcs_rev vs seq
mono = {c: {"pairs": 0, "violations": 0, "violations_beyond_1s": 0, "pages_with_violation": 0, "examples": []} for c in present}
seq_gaps = collections.Counter()
rcs_mismatch = 0
rcs_n = 0
for pk, rs in by_page.items():
    flagged = set()
    for r in rs:
        try:
            minor = int(str(r["rcs_rev"]).split(".")[-1])
            rcs_n += 1
            rcs_mismatch += int(minor != r["seq"])
        except ValueError:
            pass
    for x, y in zip(rs, rs[1:]):
        seq_gaps[y["seq"] - x["seq"]] += 1
        if y["seq"] - x["seq"] != 1:
            continue
        for c in present:
            if x["t"][c] is None or y["t"][c] is None:
                continue
            mono[c]["pairs"] += 1
            d = y["t"][c] - x["t"][c]
            if d < 0:
                mono[c]["violations"] += 1
                flagged.add(c)
                if len(mono[c]["examples"]) < 10:
                    mono[c]["examples"].append({"page_key": pk, "seq": y["seq"], "delta_s": d})
            if d < -1:
                mono[c]["violations_beyond_1s"] += 1
    for c in flagged:
        mono[c]["pages_with_violation"] += 1
for c in mono:
    mono[c]["violation_rate"] = wil(mono[c]["violations"], mono[c]["pairs"])
S1["per_page_seq_monotonicity"] = mono
S1["seq_step_counts"] = {str(k): v for k, v in sorted(seq_gaps.items())}
S1["rcs_rev_minor_ne_seq"] = {"k": rcs_mismatch, "n": rcs_n,
                              "pages": sum(1 for rs in by_page.values() if any(int(str(r["rcs_rev"]).split(".")[-1]) != r["seq"] for r in rs))}

# POST-HOC: storage commit order (RCS minor number) vs timestamp order
inv = {"posthoc": True, "pairs": 0, "inversions": 0, "inversions_beyond_1s": 0, "pages_with_inversion": 0, "inversion_magnitudes_s": [],
       "rcs_minor_steps": collections.Counter(), "examples": []}
inv_num, inv_den = collections.Counter(), collections.Counter()
for pk, rs in by_page.items():
    rr = sorted(rs, key=lambda r: int(str(r["rcs_rev"]).split(".")[-1]))
    hit = False
    for x, y in zip(rr, rr[1:]):
        step = int(str(y["rcs_rev"]).split(".")[-1]) - int(str(x["rcs_rev"]).split(".")[-1])
        inv["rcs_minor_steps"][str(step) if step <= 3 else ">3"] += 1
        if step != 1:
            continue
        inv["pairs"] += 1
        inv_den[pk] += 1
        d = y["t"]["time"] - x["t"]["time"]
        if d < 0:
            inv["inversions"] += 1
            inv_num[pk] += 1
            inv["inversion_magnitudes_s"].append(d)
            inv["labels_differ"] = inv.get("labels_differ", 0) + int(x["label"] != y["label"])
            inv["ip16_differ"] = inv.get("ip16_differ", 0) + int(x["ip16"] != y["ip16"])
            hit = True
            if len(inv["examples"]) < 10:
                inv["examples"].append({"page_key": pk, "rcs_rev": y["rcs_rev"], "delta_s": d,
                                        "labels_differ": x["label"] != y["label"], "ip16_differ": x["ip16"] != y["ip16"]})
        if d < -1:
            inv["inversions_beyond_1s"] += 1
    inv["pages_with_inversion"] += int(hit)
inv["inversion_rate_pooled"] = wil(inv["inversions"], inv["pairs"])
inv["inversion_rate_page_clustered"] = cr(inv_num, inv_den)
inv["inversion_magnitude_counts"] = dict(collections.Counter(str(x) for x in inv.pop("inversion_magnitudes_s")))
inv["rcs_minor_steps"] = dict(inv["rcs_minor_steps"])
S1["posthoc_rcs_commit_order_vs_time"] = inv

# events: delete / revert clocks
ev_out = {}
for et in ("delete", "revert"):
    rows = [e for e in events if e["event_type"] == et]
    both = [e for e in rows if e.get("request_time") and e.get("success_time")]
    d = np.array([P(e["success_time"]) - P(e["request_time"]) for e in both], dtype=float)
    cds = [e.get("clock_delta_seconds") for e in both]
    mism = sum(1 for e, x in zip(both, d) if e.get("clock_delta_seconds") is not None and e["clock_delta_seconds"] != x)
    mism_abs = sum(1 for e, x in zip(both, d) if e.get("clock_delta_seconds") is not None and e["clock_delta_seconds"] != abs(x))
    ev_out[et] = {"n": len(rows), "n_with_request_and_success": len(both),
                  "success_minus_request": {"eq0": int((d == 0).sum()), "lt0": int((d < 0).sum()), "gt0": int((d > 0).sum()),
                                            "describe": stats.describe(d) if len(d) else {"n": 0},
                                            "values": dict(collections.Counter(str(int(x)) for x in d))},
                  "clock_delta_seconds_values": dict(collections.Counter(str(x) for x in cds)),
                  "clock_delta_ne_success_minus_request": mism, "clock_delta_ne_abs_success_minus_request": mism_abs,
                  "time_grade": dict(collections.Counter(e["time_grade"] for e in rows)),
                  "clock_note": dict(collections.Counter(str(e.get("clock_note")) for e in rows))}
# deletes of pages that have held revisions: held revision written after the delete (recreation) vs relation records
del_rows = [e for e in events if e["event_type"] == "delete" and e.get("page_key") in by_page]
later = 0
for e in del_rows:
    td = P(e["time"])
    if any(r["t"]["time"] > td for r in by_page[e["page_key"]]):
        later += 1
ev_out["delete_of_held_page_followed_by_held_save"] = {"k": later, "n": len(del_rows),
                                                      "revert_events_recorded": sum(1 for e in events if e["event_type"] == "revert")}
S1["event_clocks"] = ev_out

# derived tables vs revisions
pg_first = {pk: min(r["t"]["time"] for r in rs) for pk, rs in by_page.items()}
pg_last = {pk: max(r["t"]["time"] for r in rs) for pk, rs in by_page.items()}
pm = {"n_pages": len(pages), "first_write_ne_min_rev_time": 0, "last_write_ne_max_rev_time": 0, "n_revs_ne_held_count": 0,
      "page_missing_in_revisions": 0}
for p in pages:
    pk = p["page_key"]
    if pk not in by_page:
        pm["page_missing_in_revisions"] += 1
        continue
    pm["first_write_ne_min_rev_time"] += int(P(p["first_write"]) != pg_first[pk])
    pm["last_write_ne_max_rev_time"] += int(P(p["last_write"]) != pg_last[pk])
    pm["n_revs_ne_held_count"] += int(p["n_revs"] != len(by_page[pk]))
lab_rev = collections.defaultdict(list)
for r in revs:
    lab_rev[r["label"]].append(r["t"]["time"])
lm = {"n_labels": len(labels), "stored_revisions_ne_count": 0, "first_write_ne_min": 0, "last_write_ne_max": 0, "label_missing": 0}
for L in labels:
    ts = lab_rev.get(L["label"])
    if not ts:
        lm["label_missing"] += 1
        continue
    lm["stored_revisions_ne_count"] += int(L["stored_revisions"] != len(ts))
    lm["first_write_ne_min"] += int(P(L["first_write"]) != min(ts))
    lm["last_write_ne_max"] += int(P(L["last_write"]) != max(ts))
S1["derived_table_consistency"] = {"pages_jsonl": pm, "labels_jsonl": lm}
J["S1_multiclock"] = S1
print("S1 done", flush=True)

# ===============================================================================================================
# Load urlquery
# ===============================================================================================================
allrep = list(csv.DictReader(open(f"{UQ}/all-reports.csv", encoding="utf-8")))
srcrows = list(csv.DictReader(open(f"{UQ}/report-sources.csv", encoding="utf-8")))
methods = json.load(open(f"{UQ}/methods.json", encoding="utf-8"))
rep_time = {a["report_id"]: P(a["report_date_utc"]) for a in allrep}
rep_meta = {a["report_id"]: a for a in allrep}
rep_src = {s["report_id"]: s["data_source"] for s in srcrows}
J["inputs"]["urlquery_reports"] = len(allrep)
J["inputs"]["urlquery_source_rows"] = len(srcrows)
J["inputs"]["urlquery_methods"] = len(methods)
J["inputs"]["urlquery_methods_with_wiki_in_reason"] = sorted(m["id"] for m in methods if "wiki" in (m.get("reason") or "").lower())
src_time_mismatch = sum(1 for s in srcrows if P(s["report_date_utc"]) != rep_time.get(s["report_id"]))
J["inputs"]["urlquery_source_rows_time_ne_catalog_time"] = src_time_mismatch

marker_to_bucket = collections.defaultdict(set)
unmapped = []
for m in methods:
    for mk in m.get("markers") or []:
        if m["label"] not in BUCKET:
            unmapped.append(m["label"])
            continue
        marker_to_bucket[mk.lower()].add(BUCKET[m["label"]])
assert not unmapped, unmapped
J["inputs"]["marker_to_bucket"] = {k: sorted(v) for k, v in sorted(marker_to_bucket.items())}

bucket_times = collections.defaultdict(list)
for s in srcrows:
    bucket_times[s["data_source"]].append(P(s["report_date_utc"]))
bucket_times = {k: np.sort(np.array(v, dtype=np.int64)) for k, v in bucket_times.items()}
all_times = np.sort(np.array([rep_time[a["report_id"]] for a in allrep], dtype=np.int64))

# ===============================================================================================================
# S2 cross-witness temporal precedence
# ===============================================================================================================
S2 = {}
match_mode = collections.Counter()
rev_sources = {}
for r in revs:
    low = (r["body"] or "").lower()
    u1 = urllib.parse.unquote(low)
    u2 = urllib.parse.unquote(u1)
    found = set()
    for mk, bs in marker_to_bucket.items():
        raw = mk in low
        dec = (mk in u1) or (mk in u2)
        if raw or dec:
            found |= bs
            for b in bs:
                match_mode[(b, "raw" if raw else "decoded_only")] += 1
    rev_sources[r["rev_id"]] = found
S2["revisions_with_any_source"] = wil(sum(1 for v in rev_sources.values() if v), len(revs))
S2["revision_mentions_by_bucket_and_mode"] = {f"{b}|{m}": v for (b, m), v in sorted(match_mode.items())}

mention_events = []  # (page_key, bucket, t, rev_id)
for pk, rs in by_page.items():
    prev = set()
    for r in rs:
        cur = rev_sources[r["rev_id"]]
        for b in sorted(cur - prev):
            mention_events.append((pk, b, r["t"]["time"], r["rev_id"]))
        prev = cur
S2["new_mention_events"] = {"n": len(mention_events), "n_pages": len({e[0] for e in mention_events}),
                            "by_bucket": dict(collections.Counter(e[1] for e in mention_events).most_common())}
S2["catalog_reports_by_bucket"] = {k: int(len(v)) for k, v in sorted(bucket_times.items(), key=lambda x: -len(x[1]))}
ctx = {}
for b, n in collections.Counter(e[1] for e in mention_events).most_common():
    md = {dt.datetime.fromtimestamp(e[2], dt.timezone.utc).date() for e in mention_events if e[1] == b}
    arr = bucket_times.get(b, np.array([], dtype=np.int64))
    rd = {dt.datetime.fromtimestamp(int(t), dt.timezone.utc).date() for t in arr}
    ctx[b] = {"mention_events": n, "mention_days": len(md), "catalog_report_days_all_time": len(rd), "overlap_days": len(md & rd),
              "catalog_reports_inside_wiki_window": int(count_in(arr, WMIN, WMAX, True, True)),
              "catalog_reports_total": int(len(arr))}
S2["bucket_day_overlap_context"] = ctx
no_cat = [e for e in mention_events if e[1] not in bucket_times]
S2["new_mention_events_whose_bucket_has_zero_catalog_reports"] = {"n": len(no_cat), "buckets": dict(collections.Counter(e[1] for e in no_cat))}
ME = [e for e in mention_events if e[1] in bucket_times]
ev_page = [e[0] for e in ME]
ev_b = [e[1] for e in ME]
ev_t = np.array([e[2] for e in ME], dtype=np.int64)
rng = np.random.default_rng(stats.SEED)


def hits_for(buckets, times, lo_off, hi_off, lo_closed=True, hi_closed=False):
    """For each event, whether >=1 report of its bucket lies in [t+lo_off, t+hi_off) (closure per flags)."""
    out = np.zeros(len(times), dtype=np.int64)
    bk = np.array(buckets)
    for b in set(buckets):
        idx = np.where(bk == b)[0]
        arr = bucket_times[b]
        out[idx] = count_in(arr, times[idx] + lo_off, times[idx] + hi_off, lo_closed, hi_closed) > 0
    return out


def page_rates(flags_list, pages_list, label):
    num, den = collections.Counter(), collections.Counter()
    for f, p in zip(flags_list, pages_list):
        num[p] += float(f)
        den[p] += 1
    r = cr(num, den)
    r["what"] = label
    return r


forward = {}
same_sec = hits_for(ev_b, ev_t, 0, 0, True, True)
forward["same_second_report"] = page_rates(same_sec, ev_page, "events with a report of the same source at the same second")
for W in WINDOWS:
    before = hits_for(ev_b, ev_t, -W, 0, True, False)
    after = hits_for(ev_b, ev_t, 0, W, False, True)
    nulls = np.mean([hits_for(ev_b, ev_t + s, -W, 0, True, False) for s in SHIFTS], axis=0)
    perm = []
    for _ in range(PREREG["n_source_permutations"]["value"]):
        pb = list(rng.permutation(ev_b))
        perm.append(hits_for(pb, ev_t, -W, 0, True, False))
    permm = np.mean(perm, axis=0)
    forward[f"W{W}"] = {
        "before_obs": page_rates(before, ev_page, "report of same source in [t-W, t)"),
        "after_obs": page_rates(after, ev_page, "report of same source in (t, t+W]"),
        "before_shift_null": page_rates(nulls, ev_page, "mean over shifts of before-window hit at t+shift"),
        "before_perm_null": page_rates(permm, ev_page, "mean over source permutations of before-window hit"),
        "excess_before_minus_shift_null": page_rates(before - nulls, ev_page, "page-clustered mean of (obs - shift null)"),
        "excess_before_minus_perm_null": page_rates(before - permm, ev_page, "page-clustered mean of (obs - perm null)"),
        "before_minus_after": page_rates(before - after, ev_page, "page-clustered mean of (before - after)"),
        "per_shift_before_rate": {str(int(s / DAY)): float(hits_for(ev_b, ev_t + s, -W, 0).mean()) for s in SHIFTS},
    }
    # per bucket
    pb_out = {}
    for b, n in collections.Counter(ev_b).most_common():
        if n < PREREG["per_bucket_min_events"]["value"]:
            continue
        idx = [i for i, x in enumerate(ev_b) if x == b]
        pg = [ev_page[i] for i in idx]
        pb_out[b] = {"n_events": n, "n_pages": len(set(pg)),
                     "before_obs": page_rates(before[idx], pg, "before"), "after_obs": page_rates(after[idx], pg, "after"),
                     "before_shift_null": page_rates(nulls[idx], pg, "shift null"),
                     "excess_before_minus_shift_null": page_rates(before[idx] - nulls[idx], pg, "excess")}
    forward[f"W{W}"]["per_bucket"] = pb_out
    # POST-HOC local shift nulls
    lnull = np.mean([hits_for(ev_b, ev_t + s, -W, 0, True, False) for s in LOCAL_SHIFTS], axis=0)
    forward[f"W{W}"]["posthoc_local_shift_null"] = {
        "posthoc": True, "before_local_null": page_rates(lnull, ev_page, "mean over local shifts of before-window hit"),
        "excess_before_minus_local_null": page_rates(before - lnull, ev_page, "page-clustered mean of (obs - local null)"),
        "per_shift_before_rate": {str(s): float(hits_for(ev_b, ev_t + s, -W, 0).mean()) for s in LOCAL_SHIFTS}}
    for b in pb_out:
        idx = [i for i, x in enumerate(ev_b) if x == b]
        pg = [ev_page[i] for i in idx]
        pb_out[b]["posthoc_excess_before_minus_local_null"] = page_rates(before[idx] - lnull[idx], pg, "excess vs local null")
        pb_out[b]["posthoc_before_local_null"] = page_rates(lnull[idx], pg, "local null")
# lag from most recent prior report / to next report
lag_prev, lag_next, lag_pages = [], [], []
for i, (b, t) in enumerate(zip(ev_b, ev_t)):
    arr = bucket_times[b]
    j = np.searchsorted(arr, t, "left") - 1
    k = np.searchsorted(arr, t, "right")
    lag_prev.append(float(t - arr[j]) if j >= 0 else np.nan)
    lag_next.append(float(arr[k] - t) if k < len(arr) else np.nan)
    lag_pages.append(ev_page[i])
lp = np.array(lag_prev)
ln = np.array(lag_next)
okp = ~np.isnan(lp)
okn = ~np.isnan(ln)
forward["lag_since_prior_report_s"] = {"describe": stats.describe(lp), "log_histogram": stats.log_histogram(lp[okp]),
                                      "median_page_clustered": stats.cluster_quantile(lp[okp], np.array(lag_pages)[okp], 0.5),
                                      "n_without_prior": int((~okp).sum())}
forward["lag_to_next_report_s"] = {"describe": stats.describe(ln), "log_histogram": stats.log_histogram(ln[okn]),
                                  "median_page_clustered": stats.cluster_quantile(ln[okn], np.array(lag_pages)[okn], 0.5),
                                  "n_without_next": int((~okn).sum())}
S2["forward_wiki_mention_preceded_by_report"] = forward

# reverse: urlquery bursts of a source followed by wiki new-mentions of that source
ev_by_bucket = collections.defaultdict(list)
for e in ME:
    ev_by_bucket[e[1]].append(e[2])
ev_by_bucket = {k: np.sort(np.array(v, dtype=np.int64)) for k, v in ev_by_bucket.items()}
reverse = {}
for W in WINDOWS:
    num_a, num_b, num_n, den = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    num_l, num_lo, den_l = collections.Counter(), collections.Counter(), collections.Counter()
    nb = 0
    for b, arr in bucket_times.items():
        E = ev_by_bucket.get(b, np.array([], dtype=np.int64))
        for s_i, e_i in bursts(arr, GAP):
            st, en = int(arr[s_i]), int(arr[e_i])
            if st - W < WMIN or en + W > WMAX:
                continue
            valid = [s for s in SHIFTS if en - s >= WMIN and en - s + W <= WMAX]
            if not valid:
                continue
            nb += 1
            key = f"{b}|{dt.datetime.fromtimestamp(en, dt.timezone.utc).replace(tzinfo=None).date()}"
            den[key] += 1
            num_a[key] += float(count_in(E, en, en + W, False, True) > 0)
            num_b[key] += float(count_in(E, st - W, st, True, False) > 0)
            num_n[key] += float(np.mean([count_in(E, en - s, en - s + W, False, True) > 0 for s in valid]))
            lv = [s for s in LOCAL_SHIFTS if en - s >= WMIN and en - s + W <= WMAX]
            if lv:
                den_l[key] += 1
                num_lo[key] += float(count_in(E, en, en + W, False, True) > 0)
                num_l[key] += float(np.mean([count_in(E, en - s, en - s + W, False, True) > 0 for s in lv]))
    diff = {k: num_a[k] - num_n[k] for k in den}
    asym = {k: num_a[k] - num_b[k] for k in den}
    reverse[f"W{W}"] = {"n_bursts": nb, "n_clusters_source_day": len(den),
                        "after_obs": cr(num_a, den), "before_obs": cr(num_b, den), "after_shift_null": cr(num_n, den),
                        "excess_after_minus_shift_null": cr(diff, den), "after_minus_before": cr(asym, den),
                        "posthoc_local_shift_null": {"posthoc": True, "n_bursts": int(sum(den_l.values())), "after_obs": cr(num_lo, den_l),
                                                     "after_local_null": cr(num_l, den_l),
                                                     "excess_after_minus_local_null": cr({k: num_lo[k] - num_l[k] for k in den_l}, den_l)}}
S2["reverse_report_burst_followed_by_wiki_mention"] = reverse

# exact report citations in wiki bodies
cites = []
seen = set()
for pk, rs in by_page.items():
    for r in rs:
        for rid in re.findall(r"urlquery\.net/report/([0-9a-f-]{36})", (r["body"] or "").lower()):
            if (pk, rid) in seen:
                continue
            seen.add((pk, rid))
            rt = rep_time.get(rid)
            cites.append({"rev_id": r["rev_id"], "report_id": rid, "in_catalog": rt is not None,
                          "rev_time_minus_report_time_s": (r["t"]["time"] - rt) if rt is not None else None,
                          "report_broad_class": rep_meta[rid]["broad_class"] if rid in rep_meta else None,
                          "report_source": rep_src.get(rid)})
S2["exact_report_citations_first_appearance_per_page"] = cites

# httpbin.org/base64 revisions vs indirection-class reports
ind_times = np.sort(np.array([rep_time[a["report_id"]] for a in allrep if a["broad_class"] == "indirection"], dtype=np.int64))
hb = []
for pk, rs in by_page.items():
    prev = False
    for r in rs:
        low = (r["body"] or "").lower()
        cur = "httpbin.org/base64" in low or "httpbin.org/base64" in urllib.parse.unquote(low)
        if cur and not prev:
            hb.append((pk, r["t"]["time"]))
        prev = cur
hbo = {"n_new_mention_events": len(hb), "n_pages": len({h[0] for h in hb}), "n_indirection_reports_total": int(len(ind_times))}
for W in WINDOWS:
    obs = [int(count_in(ind_times, t - W, t) > 0) for _, t in hb]
    aft = [int(count_in(ind_times, t, t + W, False, True) > 0) for _, t in hb]
    nul = [float(np.mean([count_in(ind_times, t + s - W, t + s) > 0 for s in SHIFTS])) for _, t in hb]
    hbo[f"W{W}"] = {"before_obs_k": int(sum(obs)), "after_obs_k": int(sum(aft)), "before_shift_null_mean_k": float(sum(nul)), "n": len(hb),
                    "before_obs_wilson": wil(int(sum(obs)), len(hb)), "after_obs_wilson": wil(int(sum(aft)), len(hb))}
S2["httpbin_base64_vs_indirection_reports"] = hbo
J["S2_precedence"] = S2
print("S2 done", flush=True)

# ===============================================================================================================
# S3 urlquery burst structure, alignment with wiki save bursts
# ===============================================================================================================
S3 = {}
sec_counts = collections.Counter(int(t) for t in all_times)
size_hist = collections.Counter(sec_counts.values())
S3["same_second_group_size_histogram"] = {str(k): v for k, v in sorted(size_hist.items())}
S3["reports_in_same_second_groups"] = int(sum(v for v in sec_counts.values() if v > 1))
S3["n_reports"] = int(len(all_times))
groups = collections.defaultdict(list)
for a in allrep:
    groups[rep_time[a["report_id"]]].append(a)
multi = [g for g in groups.values() if len(g) > 1]
hom = collections.Counter()
for g in multi:
    srcs = {rep_src.get(a["report_id"], "<no source row>") for a in g}
    hom["distinct_sources_" + ("1" if len(srcs) == 1 else ">=2")] += 1
    hom["distinct_broad_class_" + ("1" if len({a['broad_class'] for a in g}) == 1 else ">=2")] += 1
    hom["distinct_disposition_" + ("1" if len({a['disposition'] for a in g}) == 1 else ">=2")] += 1
    hom["distinct_confidence_" + ("1" if len({a['confidence'] for a in g}) == 1 else ">=2")] += 1
S3["same_second_groups_homogeneity"] = {"n_groups": len(multi), **dict(hom)}
gaps = np.diff(all_times).astype(float)
S3["global_gaps_s"] = {"n": int(len(gaps)), "eq0": int((gaps == 0).sum()), "describe": stats.describe(gaps),
                       "log_histogram": stats.log_histogram(gaps)}
wg = np.concatenate([np.diff(v) for v in bucket_times.values() if len(v) > 1]).astype(float)
S3["within_source_gaps_s"] = {"n": int(len(wg)), "eq0": int((wg == 0).sum()), "describe": stats.describe(wg),
                              "log_histogram": stats.log_histogram(wg)}
som = np.bincount(all_times % 60, minlength=60)
S3["second_of_minute"] = {"chi2_uniform": stats.chi2_uniform(som), "counts": [int(x) for x in som]}
S3["minute_of_hour"] = {"chi2_uniform": stats.chi2_uniform(np.bincount((all_times // 60) % 60, minlength=60))}
hod = np.bincount((all_times // 3600) % 24, minlength=24)
S3["hour_of_day_counts_utc"] = [int(x) for x in hod]
wh = np.bincount((wiki_times // 3600) % 24, minlength=24)
S3["wiki_save_hour_of_day_counts_utc"] = [int(x) for x in wh]
ub = bursts(all_times, GAP)
sizes = np.array([e - s + 1 for s, e in ub], dtype=float)
durs = np.array([all_times[e] - all_times[s] for s, e in ub], dtype=float)
S3["global_bursts"] = {"gap_rule_s": GAP, "n_bursts": len(ub), "singletons": int((sizes == 1).sum()),
                       "size_describe": stats.describe(sizes), "duration_describe_s": stats.describe(durs),
                       "size_ge_10": int((sizes >= 10).sum()), "size_ge_100": int((sizes >= 100).sum())}
# source homogeneity of multi-report bursts (all-reports order: map sorted times back to report ids)
order = sorted(allrep, key=lambda a: rep_time[a["report_id"]])
src_seq = [rep_src.get(a["report_id"], "<no source row>") for a in order]
hb_src = collections.Counter()
for s, e in ub:
    if e > s:
        hb_src["1" if len(set(src_seq[s:e + 1])) == 1 else ">=2"] += 1
S3["global_bursts_multi_report_distinct_sources"] = dict(hb_src)
# urlquery report counts inside wiki window
S3["reports_inside_wiki_save_window"] = int(count_in(all_times, WMIN, WMAX, True, True))

wb = bursts(wiki_times, GAP)
S3["wiki_save_bursts"] = {"n_bursts": len(wb), "singletons": sum(1 for s, e in wb if s == e),
                          "size_describe": stats.describe([e - s + 1 for s, e in wb])}
align = {}
for W in ALIGN_W:
    # urlquery burst -> any wiki save within [a-W, b+W]; validity: window inside wiki coverage
    num, numn, den = collections.Counter(), collections.Counter(), collections.Counter()
    numl, denl, numlo = collections.Counter(), collections.Counter(), collections.Counter()
    for s, e in ub:
        a, b = int(all_times[s]), int(all_times[e])
        if a - W < WMIN or b + W > WMAX:
            continue
        valid = [sh for sh in SHIFTS if a - W + sh >= WMIN and b + W + sh <= WMAX]
        if not valid:
            continue
        key = str(dt.datetime.fromtimestamp(a, dt.timezone.utc).replace(tzinfo=None).date())
        den[key] += 1
        num[key] += float(count_in(wiki_times, a - W, b + W, True, True) > 0)
        numn[key] += float(np.mean([count_in(wiki_times, a - W + sh, b + W + sh, True, True) > 0 for sh in valid]))
        lv = [sh for sh in LOCAL_SHIFTS if a - W + sh >= WMIN and b + W + sh <= WMAX]
        numl[key] += float(np.mean([count_in(wiki_times, a - W + sh, b + W + sh, True, True) > 0 for sh in lv])) if lv else 0.0
        denl[key] += 1 if lv else 0
        numlo[key] += float(count_in(wiki_times, a - W, b + W, True, True) > 0) if lv else 0.0
    exc = {k: num[k] - numn[k] for k in den}
    # wiki burst -> any urlquery report within [a-W, b+W]
    num2, numn2, den2, numl2 = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    for s, e in wb:
        a, b = int(wiki_times[s]), int(wiki_times[e])
        key = str(dt.datetime.fromtimestamp(a, dt.timezone.utc).replace(tzinfo=None).date())
        den2[key] += 1
        num2[key] += float(count_in(all_times, a - W, b + W, True, True) > 0)
        numn2[key] += float(np.mean([count_in(all_times, a - W + sh, b + W + sh, True, True) > 0 for sh in SHIFTS]))
        numl2[key] += float(np.mean([count_in(all_times, a - W + sh, b + W + sh, True, True) > 0 for sh in LOCAL_SHIFTS]))
    exc2 = {k: num2[k] - numn2[k] for k in den2}
    align[f"W{W}"] = {
        "urlquery_burst_has_wiki_save": {"n_bursts": int(sum(den.values())), "obs": cr(num, den), "shift_null": cr(numn, den),
                                         "excess": cr(exc, den), "cluster": "UTC date of burst start"},
        "wiki_burst_has_urlquery_report": {"n_bursts": int(sum(den2.values())), "obs": cr(num2, den2), "shift_null": cr(numn2, den2),
                                           "excess": cr(exc2, den2), "cluster": "UTC date of burst start"},
        "posthoc_local_shift_null": {
            "posthoc": True,
            "urlquery_burst_has_wiki_save": {"n_bursts": int(sum(denl.values())), "obs": cr(numlo, denl), "local_null": cr(numl, denl),
                                             "excess": cr({k: numlo[k] - numl[k] for k in denl}, denl)},
            "wiki_burst_has_urlquery_report": {"n_bursts": int(sum(den2.values())), "obs": cr(num2, den2), "local_null": cr(numl2, den2),
                                               "excess": cr({k: num2[k] - numl2[k] for k in den2}, den2)}}}
S3["burst_alignment_any_source"] = align
# largest wiki save burst (gap rule) location and size
big = max(wb, key=lambda x: x[1] - x[0])
S3["largest_wiki_save_burst"] = {"size": int(big[1] - big[0] + 1),
                                 "start": dt.datetime.fromtimestamp(int(wiki_times[big[0]]), dt.timezone.utc).isoformat(),
                                 "end": dt.datetime.fromtimestamp(int(wiki_times[big[1]]), dt.timezone.utc).isoformat(),
                                 "urlquery_reports_inside": int(count_in(all_times, int(wiki_times[big[0]]), int(wiki_times[big[1]]), True, True))}
J["S3_bursts"] = S3
print("S3 done", flush=True)

# ===============================================================================================================
# S4 narrated timing claims
# ===============================================================================================================
URL_RX = re.compile(r"https?://[^\s\]\[|<>\"']+", re.I)
ISO_RX = re.compile(r"(20\d\d)-([01]\d)-([0-3]\d)[T ]([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?:\.\d+)?(Z|[+-]\d\d:?\d\d|\s?UTC)?")
TOD_RX = re.compile(r"(?<![\d:.])([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?![\d:])")
EPOCH_RX = re.compile(r"(?<![\d.])(1[78]\d{8})(?:(\.\d+)|(\d{9})|(\d{6})|(\d{3}))?(?!\d)")
REAL_KW = PREREG["claim_keywords_real"]["value"]
TASK_KW = set(PREREG["claim_keywords_task"]["value"])
KW_RX = re.compile(r"\b(" + "|".join(REAL_KW + sorted(TASK_KW)) + r")\b")
SUFFIX_REAL = re.compile(r"^\s?(utc|gmt|z\b)")
CB = PREREG["claim_context_chars_before"]["value"]
CA = PREREG["claim_suffix_chars"]["value"]


def qualify(body, st, en, own_suffix=None):
    if own_suffix:
        return "real"
    suf = body[en:en + CA].lower()
    if SUFFIX_REAL.match(suf):
        return "real"
    pre = body[max(0, st - CB):st].lower()
    best = None
    for m in KW_RX.finditer(pre):
        best = m.group(1)
    if best is None:
        return "unqualified"
    return "task" if best in TASK_KW else "real"


def in_spans(pos, spans):
    for a, b in spans:
        if a <= pos < b:
            return True
    return False


def extract_claims(body):
    """-> list of (class, key, claim_value, kind) ; kind in tod/iso/epoch; value is seconds-of-day (tod) or epoch seconds."""
    out = []
    if not body:
        return out
    urls = [(m.start(), m.end()) for m in URL_RX.finditer(body)]
    iso_spans = []
    for m in ISO_RX.finditer(body):
        iso_spans.append((m.start(), m.end()))
        if in_spans(m.start(), urls):
            continue
        y, mo, d, hh, mi, ss, tz = m.groups()
        try:
            base = dt.datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        off = 0
        if tz and tz.strip().upper() not in ("Z", "UTC"):
            sign = 1 if tz[0] == "+" else -1
            tzd = tz[1:].replace(":", "")
            off = sign * (int(tzd[:2]) * 3600 + int(tzd[2:]) * 60)
        val = int(base.timestamp()) - off
        cls = qualify(body, m.start(), m.end(), own_suffix=bool(tz) and tz.strip().upper() in ("Z", "UTC") or (bool(tz) and off == 0))
        out.append(("iso_" + cls, ("iso", m.group(0), body[max(0, m.start() - 24):m.start()]), val, "iso", m.start(), m.end()))
    for m in TOD_RX.finditer(body):
        if in_spans(m.start(), urls) or in_spans(m.start(), iso_spans):
            continue
        hh, mi, ss = m.groups()
        val = int(hh) * 3600 + int(mi) * 60 + int(ss or 0)
        cls = qualify(body, m.start(), m.end())
        out.append(("tod_" + cls, ("tod", m.group(0), body[max(0, m.start() - 24):m.start()]), val, "tod", m.start(), m.end()))
    for m in EPOCH_RX.finditer(body):
        sec = int(m.group(1))
        cls = "epoch_url" if in_spans(m.start(), urls) else "epoch_prose"
        out.append((cls, ("epoch", m.group(0), body[max(0, m.start() - 24):m.start()]), sec, "epoch", m.start(), m.end()))
    return out


TENSE = POSTHOC["claim_tense_keywords"]["value"]
TENSE_RX = re.compile(r"\b(" + "|".join(sorted({w for v in TENSE.values() for w in v})) + r")\b")
TENSE_OF = {w: k for k, v in TENSE.items() for w in v}
TW = POSTHOC["claim_tense_window_chars"]["value"]


def features(body, cls, text, val, st, en):
    """POST-HOC per-claim features: tense of the closest tense keyword before the time, approx flag, epoch roundness/fraction."""
    f = {}
    if cls.startswith(("tod_", "iso_")):
        pre = body[max(0, st - TW):st].lower()
        best = None
        for m in TENSE_RX.finditer(pre):
            best = m.group(1)
        f["tense"] = TENSE_OF[best] if best else "untensed"
        near = body[max(0, st - 8):st].lower()
        f["approx"] = ("~" in near[-3:]) or ("approx" in near)
    if cls.startswith("epoch_") or cls == "name":
        f["round"] = (val % 100) in (0, 1, 99)
        f["fraction"] = "." in text
    return f


CLASSES = ["epoch_prose", "epoch_url", "tod_real", "tod_task", "tod_unqualified", "iso_real", "iso_task", "iso_unqualified"]
occ_all = collections.Counter()
revs_with = collections.Counter()
new_claims = collections.defaultdict(list)  # cls -> list of (page, label, delta, rev_id, text, features)
mapping_pairs = []  # POST-HOC: (page, label, task_tod, utc_tod, rev_id)
for pk, rs in by_page.items():
    prev_keys = set()
    for r in rs:
        cl = extract_claims(r["body"])
        keys = set()
        seen_cls = set()
        save = r["t"]["time"]
        body = r["body"] or ""
        tods = sorted([x for x in cl if x[3] == "tod" and x[0] in ("tod_real", "tod_task")], key=lambda x: x[4])
        for cls, key, val, kind, st, en in cl:
            occ_all[cls] += 1
            seen_cls.add(cls)
            keys.add(key)
            if key in prev_keys:
                continue
            if kind == "tod":
                delta = ((val - (save % DAY) + DAY // 2) % DAY) - DAY // 2
            else:
                delta = val - save
            new_claims[cls].append((pk, r["label"], int(delta), r["rev_id"], key[1], features(body, cls, key[1], val, st, en)))
            if cls == "tod_real":
                # POST-HOC mapping pair: nearest task-clock time within 80 chars, no other time in between
                i = next(j for j, x in enumerate(tods) if x[4] == st)
                for j in (i - 1, i + 1):
                    if 0 <= j < len(tods) and tods[j][0] == "tod_task":
                        gap = (st - tods[j][5]) if j < i else (tods[j][4] - en)
                        if 0 <= gap <= 80:
                            mapping_pairs.append((pk, r["label"], tods[j][2], val, r["rev_id"]))
                            break
        for c in seen_cls:
            revs_with[c] += 1
        prev_keys = keys

S4 = {"occurrences_all_revisions": {c: occ_all[c] for c in CLASSES},
      "revisions_containing": {c: revs_with[c] for c in CLASSES}, "n_revisions": len(revs), "classes": {}}
for c in CLASSES:
    rows = new_claims[c]
    d = np.array([x[2] for x in rows], dtype=float)
    den = collections.Counter(x[0] for x in rows)
    o = {"n_new_claims": len(rows), "n_pages": len(den), "n_labels": len({x[1] for x in rows}),
         "delta_bins": bin_counts(d) if len(d) else {}, "delta_describe_s": stats.describe(d) if len(d) else {"n": 0}}
    if len(d):
        o["delta_median_page_clustered"] = stats.cluster_quantile(d, np.array([x[0] for x in rows]), 0.5)
    imp = {}
    for tol in TOLS:
        num = collections.Counter(x[0] for x in rows if x[2] > tol)
        imp[f"gt_{tol}s"] = {"pooled": wil(sum(num.values()), len(rows)), "page_clustered": cr(num, den) if den else None}
    o["claim_after_own_save"] = imp
    if c.startswith("tod_"):
        o["fold_symmetry"] = {"in_minus1h_0": int(((d >= -3600) & (d < 0)).sum()), "in_0_plus1h": int(((d > 0) & (d <= 3600)).sum()),
                              "eq0": int((d == 0).sum())}
    ex = sorted([x for x in rows if x[2] > 60], key=lambda x: x[2])[:20]
    o["examples_after_save_gt60s"] = [{"rev_id": x[3], "claim": x[4], "delta_s": x[2]} for x in ex]
    S4["classes"][c] = o

# page-name epochs vs the page's first held save (only pages whose held history starts at seq 1)
pn = []
for pk, rs in by_page.items():
    if rs[0]["seq"] != 1:
        continue
    for m in EPOCH_RX.finditer(rs[0]["name"]):
        pn.append((pk, rs[0]["label"], int(m.group(1)) - rs[0]["t"]["time"], rs[0]["rev_id"], m.group(0),
                   features("", "name", m.group(0), int(m.group(1)), 0, 0)))
d = np.array([x[2] for x in pn], dtype=float)
pno = {"n_names_with_epoch": len(pn), "n_pages": len({x[0] for x in pn}), "n_labels": len({x[1] for x in pn}),
       "pages_starting_at_seq1": sum(1 for rs in by_page.values() if rs[0]["seq"] == 1),
       "delta_bins": bin_counts(d) if len(d) else {}, "delta_describe_s": stats.describe(d) if len(d) else {"n": 0}}
if len(d):
    pno["delta_median_label_clustered"] = stats.cluster_quantile(d, np.array([x[1] for x in pn]), 0.5)
imp = {}
for tol in TOLS:
    num_p = collections.Counter(x[0] for x in pn if x[2] > tol)
    den_p = collections.Counter(x[0] for x in pn)
    num_l = collections.Counter(x[1] for x in pn if x[2] > tol)
    den_l = collections.Counter(x[1] for x in pn)
    imp[f"gt_{tol}s"] = {"pooled": wil(sum(num_p.values()), len(pn)), "page_clustered": cr(num_p, den_p),
                         "label_clustered": cr(num_l, den_l)}
pno["name_epoch_after_first_save"] = imp
pno["examples_after_save_gt60s"] = [{"rev_id": x[3], "epoch_text": x[4], "delta_s": x[2]} for x in sorted([x for x in pn if x[2] > 60], key=lambda x: x[2])[:20]]
S4["page_name_epochs"] = pno

# ---------------- POST-HOC breakdowns (see POSTHOC) ----------------


def imp_rates(rows, cl_idx=0):
    den = collections.Counter(x[cl_idx] for x in rows)
    out = {"n": len(rows), "n_clusters": len(den), "delta_bins": bin_counts([x[2] for x in rows]) if rows else {}}
    for tol in TOLS:
        num = collections.Counter(x[cl_idx] for x in rows if x[2] > tol)
        out[f"gt_{tol}s"] = {"pooled": wil(sum(num.values()), len(rows)), "clustered": cr(num, den) if den else None}
    # near-future band (1 s, 1 h]: after the save but too close to be a >12 h-old event folded forward
    nf = collections.Counter(x[cl_idx] for x in rows if 1 < x[2] <= 3600)
    out["near_future_1s_to_1h"] = {"pooled": wil(sum(nf.values()), len(rows)), "clustered": cr(nf, den) if den else None}
    if rows:
        out["delta_median_clustered"] = stats.cluster_quantile([x[2] for x in rows], np.array([x[cl_idx] for x in rows]), 0.5)
    return out


ph = {"posthoc": True, "cluster_unit": "page unless stated",
      "uniform_clock_expectation_near_future_1s_to_1h": (3600 - 1) / DAY}
for c in ("tod_real", "iso_real", "tod_task", "tod_unqualified"):
    rows = new_claims[c]
    ph[c] = {"by_tense": {t: imp_rates([x for x in rows if x[5]["tense"] == t]) for t in ("past", "present", "forward", "untensed")},
             "by_approx": {str(v): imp_rates([x for x in rows if x[5]["approx"] == v]) for v in (True, False)},
             "past_or_present_and_not_approx": imp_rates([x for x in rows if x[5]["tense"] in ("past", "present") and not x[5]["approx"]]),
             "past_only_not_approx": imp_rates([x for x in rows if x[5]["tense"] == "past" and not x[5]["approx"]])}
for c in ("epoch_prose", "epoch_url"):
    rows = new_claims[c]
    ph[c] = {"by_round": {str(v): imp_rates([x for x in rows if x[5]["round"] == v]) for v in (True, False)},
             "by_fraction": {str(v): imp_rates([x for x in rows if x[5]["fraction"] == v]) for v in (True, False)}}
ph["page_name_epochs"] = {"by_round_page": {str(v): imp_rates([x for x in pn if x[5]["round"] == v]) for v in (True, False)},
                          "by_round_label_clustered": {str(v): imp_rates([x for x in pn if x[5]["round"] == v], cl_idx=1) for v in (True, False)}}
# task-clock <-> UTC mapping pairs: self-consistency of the narrated offset
def circ_range(vals):
    o = np.sort(np.asarray(vals, dtype=float) % DAY)
    if len(o) < 2:
        return 0.0
    gaps = np.diff(np.concatenate([o, [o[0] + DAY]]))
    return float(DAY - gaps.max())


mp = {"n_pairs_new": len(mapping_pairs), "n_pages": len({x[0] for x in mapping_pairs}), "n_labels": len({x[1] for x in mapping_pairs})}
for unit, idx in (("label", 1), ("page", 0), ("page_label", None)):
    groups = collections.defaultdict(set)
    for x in mapping_pairs:
        k = (x[0], x[1]) if idx is None else x[idx]
        groups[k].add((x[2], x[3]))
    spreads, uspan = [], []
    for k, prs in groups.items():
        if len(prs) < 2:
            continue
        spreads.append(circ_range([(u - t) % DAY for t, u in prs]))
        uspan.append(circ_range([u for t, u in prs]))
    sp = np.array(spreads)
    th = POSTHOC["task_utc_mapping"]["thresholds_s"]
    mp[f"by_{unit}"] = {"groups_with_ge2_distinct_pairs": len(sp), "offset_spread_describe_s": stats.describe(sp) if len(sp) else {"n": 0},
                        **{f"spread_le_{t}s": wil(int((sp <= t).sum()), len(sp)) for t in th},
                        "utc_span_describe_s": stats.describe(uspan) if uspan else {"n": 0}}
ph["task_utc_mapping"] = mp
S4["posthoc"] = ph
J["S4_timing_claims"] = S4
print("S4 done", flush=True)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(J, fh, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
print("wrote", os.path.abspath(OUT))
