"""Phase D: reconcile three independent rankings of the Phase C mechanism proposals into one ranked list.

Reads
  analysis/out/phase_d/inputs/ranker_{1,2,3}.json   the three ranker outputs, copied byte-for-byte from the Phase D
                                                    workflow scratchpad (rank_{1,2,3}.json); sha256 recorded below
  analysis/out/phase_c/_index.json                  Phase C observations with skeptic verdicts (citation check)
  analysis/out/phase_c/{ids_and_clocks_in_ids,token_conservation,commit_witness}.json   committed lens outputs
  analysis/out/phase_a/a5.json                      split-A Gemini modality rows (committed Phase A script)
  analysis/out/probe_{1,2,3,4}.json, analysis/out/phase_b_verification.json             Phase B reference numbers
Writes
  analysis/out/phase_d/ranking.json

What the script computes (data): the rank position of each merged mechanism in each input, the pairwise disagreements,
the decisive counts read from committed files by JSON path, Wilson intervals (lib/stats.wilson) for counts that have no
interval in their source, the Phase B reference numbers, a citation check (every lens/ID cited in the final text must be
in _index.json with reproduced == true) and a number trace (numeric tokens of the final text not found in any source).
What it does not compute: the rank order, the why_this_rank texts and the disagreement resolutions. Those are
INTERPRETATION, written in this file as literal text and labelled as such in the output (rule 4).

Run:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_d_ranking
"""
import hashlib
import json
import os
import re

from analysis.lib import stats

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
A = lambda *p: os.path.join(ROOT, "analysis", *p)  # noqa: E731
OUT = A("out", "phase_d", "ranking.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def r(x):
    """Format a proportion: 4 decimals at or above 0.01, else 3 significant digits."""
    if x is None:
        return "NA"
    if x == 0:
        return "0"
    if x == 1:
        return "1.0"
    return f"{x:.4f}" if x >= 0.01 else f"{x:.3g}"


def n(x):
    return f"{int(x):,}"


def wil(k, m):
    p, lo, hi = stats.wilson(k, m)
    return {"k": int(k), "n": int(m), "rate": p, "lo": lo, "hi": hi, "method": "Wilson 95%, items treated as independent"}


def fw(w):
    return f"{n(w['k'])}/{n(w['n'])}, Wilson [{r(w['lo'])}, {r(w['hi'])}]"


def fcr(d, k="num", m="den"):
    """Format a stored rate dict with a CI (session-clustered in the source unless noted)."""
    return f"{n(d[k])}/{n(d[m])} = {r(d['rate'])} [{r(d['lo'])}, {r(d['hi'])}]"


# ---------------------------------------------------------------- inputs
INPUTS = {i: A("out", "phase_d", "inputs", f"ranker_{i}.json") for i in (1, 2, 3)}
rankers = {i: load(p) for i, p in INPUTS.items()}
IX_PATH = A("out", "phase_c", "_index.json")
ix = load(IX_PATH)
OBS = {(o["lens"], o["id"]): o for o in ix["observations"]}

# ---------------------------------------------------------------- mechanism keys and positions
CANON = {
    "bracket": {"power#1", "robustness#1", "coverage#1", "coverage#4"},
    "image": {"power#4", "coverage#5", "robustness#5"},
    "git": {"power#3", "robustness#3"},
    "dual": {"power#2", "coverage#3"},
    "ledger": {"power#5", "robustness#2", "coverage#2", "robustness#4"},
}
PID = re.compile(r"\b(power|robustness|coverage)#(\d)")


def mech_of(entry):
    ids = {f"{a}#{b}" for s in entry["merged_from"] for a, b in PID.findall(s)}
    best = max(CANON, key=lambda k: len(CANON[k] & ids))
    return best, sorted(ids)


positions, merged_ids = {}, {}
for i, d in rankers.items():
    for e in d["ranking"]:
        m, ids = mech_of(e)
        assert m not in positions.get(i, {}), (i, m)
        positions.setdefault(i, {})[m] = e["rank"]
        merged_ids.setdefault(i, {})[m] = ids
order = ["bracket", "image", "git", "dual", "ledger"]
pairwise = []
for a_i, a in enumerate(order):
    for b in order[a_i + 1:]:
        above = sum(positions[i][a] < positions[i][b] for i in rankers)
        pairwise.append({"pair": [a, b], "rankers_placing_first_above_second": above, "of": len(rankers),
                         "unanimous": above in (0, len(rankers))})

# ---------------------------------------------------------------- decisive numbers from committed files
idc = load(A("out", "phase_c", "ids_and_clocks_in_ids.json"))
br = idc["bracket"]["swechat"]["anthropic_req"]["claude_code"]
brl = idc["bracket"]["cc_local"]["anthropic_req"]["cc_local"]
brx = idc["bracket_x_copies"]["swechat"]["anthropic_req|claude_code"]
o5 = OBS[("ids_and_clocks_in_ids", "O5")]["skeptic_numbers"]
m_pl = re.search(r"Placebo \(swechat, ([\d,]+) streams\).*?5 s earlier flags ([\d,]+); 30 s earlier flags ([\d,]+)\. "
                 r"Moving it 5 s, 30 s or 300 s later flags (\d+)", o5)
assert m_pl, "placebo text not found in ids_and_clocks_in_ids/O5 skeptic_numbers"
pl_n, pl5, pl30, pl_late = (int(x.replace(",", "")) for x in m_pl.groups())
assert "Scripts: o5.py, o5b.py, o5c.py" in o5
m_hon = re.search(r"swechat: ([\d,]+) streams, (\d+) inconsistent .*?rate 0\.00272 \[0\.00112, 0\.00466\]", o5)
assert m_hon
hon_n, hon_k = int(m_hon.group(1).replace(",", "")), int(m_hon.group(2))
lens_script_has_placebo = "placebo" in open(A("probes", "phase_c_ids_and_clocks_in_ids.py"), encoding="utf-8").read().lower()
ver_ir_mentions = [s for s in ("o5.py", "o5b.py", "o5c.py") if s in json.dumps(load(A("out", "phase_c", "_verification_ir.json")))]

tc = load(A("out", "phase_c", "token_conservation.json"))
tci = tc["aiv_cu_gemini_text_image"]
by_tool = tci["dIMAGE_positive_by_top_tool"]
gui = by_tool["gui"]
nongui_n = sum(v["n"] for k, v in by_tool.items() if k != "gui")
nongui_pos = sum(v["dI_positive"] for k, v in by_tool.items() if k != "gui")
named = {"shell", "get_pixel_coords_of_element", "pause", "send_message_back_to_chat"}
other_n = sum(v["n"] for k, v in by_tool.items() if k != "gui" and k not in named)
other_tools = sorted(k for k in by_tool if k != "gui" and k not in named)

a5 = load(A("out", "phase_a", "a5.json"))
a5m = {"script": a5["meta"]["script"], "split": a5["meta"]["split"]}
spA = {}
for mdl in ("gemini-pro", "gemini-flash"):
    g = a5["part2"][f"aiv_cu/{mdl}"]["gemini_modality"]
    spA[mdl] = {"gui": g["gap_has_gui_result"]["share_d_image_gt0"], "nogui": g["gap_has_no_gui_result"]["share_d_image_gt0"]}

cw = load(A("out", "phase_c", "commit_witness.json"))
cwm = cw["q4"]["commit_claims"]["matched_checks"]
o11 = OBS[("commit_witness", "O11")]["skeptic_numbers"]
m_git = re.search(r"Population: (\d+) of (\d+) resolved claims", o11)
assert m_git
git_out, git_n = int(m_git.group(1)), int(m_git.group(2))

W = {
    "bracket_swechat_lens": {"k": br["streams_inconsistent"], "n": br["streams_ge2_responses"],
                             "session_clustered": br["inconsistent_rate_by_session"],
                             "U_minus_L_ms_p5_p50_p95": [br["U_minus_L_consistent_describe_ms"][q] for q in ("p5", "p50", "p95")],
                             "source": "ids_and_clocks_in_ids.json bracket.swechat.anthropic_req.claude_code"},
    "bracket_swechat_skeptic": {"k": hon_k, "n": hon_n, "source": "_index.json ids_and_clocks_in_ids/O5 skeptic_numbers"},
    "bracket_restamped_sessions": {"inconsistent_sessions": brx["sessions_with_inconsistent_stream"],
                                   "holding_restamped_copies": brx["of_which_hold_restamped_copies"],
                                   "source": "ids_and_clocks_in_ids.json bracket_x_copies.swechat"},
    "bracket_cc_local": wil(brl["streams_inconsistent"], brl["streams_ge2_responses"]),
    "placebo_back5": wil(pl5, pl_n),
    "placebo_back30": wil(pl30, pl_n),
    "placebo_later_flagged": pl_late,
    "placebo_provenance": {"skeptic_text_names_scripts": ver_ir_mentions,
                           "committed_lens_script_mentions_placebo": lens_script_has_placebo,
                           "note": "placebo counts exist only as skeptic text in committed JSON; produced by uncommitted scratch scripts"},
    "image_gui_hits": {"k": gui["dI_positive"], "n": gui["n"]},
    "image_gui_miss": wil(gui["n"] - gui["dI_positive"], gui["n"]),
    "image_nongui": wil(nongui_pos, nongui_n),
    "image_nongui_by_tool": by_tool,
    "image_lattice": tci["dIMAGE_in_0_or_unit"],
    "image_splitA": {m: {"gui_cluster": v["gui"], "gui_wilson": wil(v["gui"]["num"], v["gui"]["den"]),
                         "nogui_wilson": wil(v["nogui"]["num"], v["nogui"]["den"]),
                         "nogui_sessions": v["nogui"]["n_sessions"], "gui_sessions": v["gui"]["n_sessions"]}
                     for m, v in spA.items()},
    "image_splitA_source": {"file": "analysis/out/phase_a/a5.json part2.aiv_cu/gemini-*.gemini_modality", **a5m},
    "git_lens": {**cwm["commit_date_in_call_window"], "out_of_window": len(cwm["out_of_window_dt_s"]),
                 "source": "commit_witness.json q4.commit_claims.matched_checks"},
    "git_lens_out": wil(len(cwm["out_of_window_dt_s"]), cwm["n"]),
    "git_skeptic_out": wil(git_out, git_n),
}
W["insertion_direction_overlap"] = {
    "image_gui_miss": [W["image_gui_miss"]["lo"], W["image_gui_miss"]["hi"]],
    "git_out_of_window": [W["git_skeptic_out"]["lo"], W["git_skeptic_out"]["hi"]],
    "intervals_overlap": not (W["image_gui_miss"]["hi"] < W["git_skeptic_out"]["lo"] or W["git_skeptic_out"]["hi"] < W["image_gui_miss"]["lo"]),
}

# ---------------------------------------------------------------- Phase B reference numbers
p1 = load(A("out", "probe_1.json"))["verdicts"]
p2 = load(A("out", "probe_2.json"))["verdicts"]
p3 = load(A("out", "probe_3.json"))
p4 = load(A("out", "probe_4.json"))
pbv = load(A("out", "phase_b_verification.json"))
checks = [c for p in pbv["probes"] for c in p["rederive"]["checks"]]


def p1u(u):
    d = p1[u]["deciding"]
    fp = d["fp_share"]
    out = {"verdict": p1[u]["verdict"], "fp": fcr(fp)}
    if "auc" in d.get("auc", {}):
        a = d["auc"]
        out["auc"] = f"{a['auc']:.3f} [{a['lo']:.3f}, {a['hi']:.3f}]"
    out["floor_step"] = d.get("step_share")
    return out


def p2u(u, t):
    x = p2[u][t]
    return {"verdict": x["verdict"], "stat": x.get("deciding_statistic"),
            "value": f"{n(x['k'])}/{n(x['n'])} = {x['value']:.3f} [{x['ci'][0]:.3f}, {x['ci'][1]:.3f}]" if x.get("k") is not None else None}


def p3z(u):
    z = p3["units"][u]["zero_error_tail"]["L75"]["Z"]
    return f"{z['k']}/{z['n']} = {z['share']:.3f} [{z['lo']:.3f}, {z['hi']:.3f}]"


def p4d(u, kind):
    d = p4["units"][u]["verdicts"][kind]["deciding"]
    if kind == "hex_primary":
        return f"{d['T_orig_w_adj']:.3f} [{d['T_orig_w_adj_lo']:.3f}, {d['T_orig_w_adj_hi']:.3f}]"
    k, m = d["T_orig_last0_k_n"]
    k2, m2 = d["M_all_last0_k_n"]
    return (f"{n(k)}/{n(m)} = {d['T_orig_last0']:.3f} [{d['T_orig_last0_lo']:.3f}, {d['T_orig_last0_hi']:.3f}] vs machine "
            f"{n(k2)}/{n(m2)} = {d['M_all_last0']:.3f} [{d['M_all_last0_lo']:.3f}, {d['M_all_last0_hi']:.3f}]")


react = p3["units"]["swechat/claude_code"]["verdict"]["reaction"]["deciding_number"]["effect"]
PB = {
    "p1": {u: p1u(u) for u in ("swechat/opencode", "cc_local", "swechat/claude_code", "aiv_cc", "swechat/codex")},
    "p1_not_testable": sorted(u for u, v in p1.items() if v["verdict"] == "NOT_TESTABLE"),
    "p2": {"cc_main": p2u("swechat/claude_code", "main"), "cc_sub": p2u("swechat/claude_code", "sub"),
           "opencode_main": p2u("swechat/opencode", "main"), "codex_main": p2u("swechat/codex", "main"),
           "cc_local_main": p2u("cc_local", "main"), "aiv_cu_main": p2u("aiv_cu", "main")},
    "p2_alive_cells": sum(v[t].get("verdict") == "ALIVE" for v in p2.values() for t in ("main", "sub")),
    "p3_Z": {u: p3z(u) for u in ("swechat/claude_code", "cc_local", "aiv_cu")},
    "p3_verdicts": {u: p3["verdicts"][u] for u in ("swechat/claude_code", "cc_local", "aiv_cu")},
    "p3_reaction_cc": f"{react['value']:.3f} [{react['lo']:.3f}, {react['hi']:.3f}]",
    "p4_hex": {u: p4d(u, "hex_primary") for u in ("swechat/claude_code", "aiv_cu")},
    "p4_hex_insufficient_n_units": sorted(u for u, v in p4["verdict_table"].items()
                                          if v["hex_primary"] == "INSUFFICIENT_N"),
    "p4_round": {u: p4d(u, "round_numbers_secondary") for u in ("swechat/claude_code", "cc_local")},
    "p4_verdict_table": p4["verdict_table"],
    "rederive_checks": {"reproduced": sum(bool(c["reproduced"]) for c in checks), "of": len(checks)},
}

# ---------------------------------------------------------------- placeholder values for the final text
pro, fla = W["image_splitA"]["gemini-pro"], W["image_splitA"]["gemini-flash"]
V = {
    "hon_k": str(hon_k), "hon_n": n(hon_n),
    "lens_br": f"{br['streams_inconsistent']}/{n(br['streams_ge2_responses'])}, session-clustered "
               f"{r(br['inconsistent_rate_by_session']['rate'])} [{r(br['inconsistent_rate_by_session']['lo'])}, "
               f"{r(br['inconsistent_rate_by_session']['hi'])}] over {n(br['inconsistent_rate_by_session']['n_sessions'])} sessions",
    "restamp": f"{brx['of_which_hold_restamped_copies']} of the {brx['sessions_with_inconsistent_stream']}",
    "unexpl": str(brx["sessions_with_inconsistent_stream"] - brx["of_which_hold_restamped_copies"]),
    "ccl_w": fw(W["bracket_cc_local"]),
    "pl_n": n(pl_n), "p5": fw(W["placebo_back5"]), "p30": fw(W["placebo_back30"]), "pl_late": str(pl_late),
    "guimiss": fw(W["image_gui_miss"]),
    "nongui": fw(W["image_nongui"]), "nongui_n": n(nongui_n), "nongui_hi": r(W["image_nongui"]["hi"]),
    "other_n": n(other_n), "other_tools": ", ".join(other_tools),
    "proA": f"{n(pro['gui_cluster']['num'])}/{n(pro['gui_cluster']['den'])} = {r(pro['gui_cluster']['rate'])} "
            f"[{r(pro['gui_cluster']['lo'])}, {r(pro['gui_cluster']['hi'])}] ({pro['gui_sessions']} sessions)",
    "proA_no": f"{fw(pro['nogui_wilson'])} ({pro['nogui_sessions']} sessions)",
    "flaA": f"{fw(fla['gui_wilson'])} ({fla['gui_sessions']} sessions)",
    "flaA_no": f"{fw(fla['nogui_wilson'])} ({fla['nogui_sessions']} sessions)",
    "git_lens": f"{n(cwm['commit_date_in_call_window']['num'])}/{n(cwm['commit_date_in_call_window']['den'])} = "
                f"{r(cwm['commit_date_in_call_window']['rate'])} [{r(cwm['commit_date_in_call_window']['lo'])}, "
                f"{r(cwm['commit_date_in_call_window']['hi'])}], {cwm['commit_date_in_call_window']['n_sessions']} sessions",
    "gitout": fw(W["git_skeptic_out"]),
    "overlap": "overlap" if W["insertion_direction_overlap"]["intervals_overlap"] else "do not overlap",
    "pb_ok": str(PB["rederive_checks"]["reproduced"]), "pb_tot": str(PB["rederive_checks"]["of"]),
    "p1_oc": f"{PB['p1']['swechat/opencode']['fp']}, AUC {PB['p1']['swechat/opencode']['auc']}",
    "p1_ccl": f"{PB['p1']['cc_local']['fp']}, AUC {PB['p1']['cc_local']['auc']}",
    "p1_cc": f"{PB['p1']['swechat/claude_code']['fp']}, AUC {PB['p1']['swechat/claude_code']['auc']}, floor step in "
             f"{PB['p1']['swechat/claude_code']['floor_step'][0]}/{PB['p1']['swechat/claude_code']['floor_step'][1]} series",
    "p1_aivcc": PB["p1"]["aiv_cc"]["fp"], "p1_codex": PB["p1"]["swechat/codex"]["fp"],
    "p1_nt": ", ".join(PB["p1_not_testable"]),
    "p2_cc": PB["p2"]["cc_main"]["value"], "p2_sub": PB["p2"]["cc_sub"]["value"],
    "p2_oc": PB["p2"]["opencode_main"]["value"], "p2_cx": PB["p2"]["codex_main"]["value"],
    "p2_ccl": PB["p2"]["cc_local_main"]["value"], "p2_cu": PB["p2"]["aiv_cu_main"]["value"],
    "p2_alive": str(PB["p2_alive_cells"]),
    "p3_cc": PB["p3_Z"]["swechat/claude_code"], "p3_ccl": PB["p3_Z"]["cc_local"], "p3_cu": PB["p3_Z"]["aiv_cu"],
    "p3_react": PB["p3_reaction_cc"],
    "p4_hcc": PB["p4_hex"]["swechat/claude_code"], "p4_hcu": PB["p4_hex"]["aiv_cu"],
    "p4_ins": str(len(PB["p4_hex_insufficient_n_units"])),
    "p4_rcc": PB["p4_round"]["swechat/claude_code"], "p4_rccl": PB["p4_round"]["cc_local"],
    "p4_ralive": ", ".join(sorted(u for u, v in p4["verdict_table"].items() if v["round_numbers_secondary"] == "ALIVE")),
    "ccl_hi": r(W["bracket_cc_local"]["hi"]),
}

# ---------------------------------------------------------------- final ranking (literal text; INTERPRETATION where marked)
IXF = "analysis/out/phase_c/_index.json"
PG = "analysis/out/phase_c/_proposals_grounded.json"
FINAL = [
 {
  "rank": 1,
  "key": "bracket",
  "name": "Provider-minted request-id clock bracket: per-stream skew bracket and single-response binding test on decoded Anthropic request ids (inter-request ceiling and the aiv_cu Gemini HTTP-header window kept as unmeasured extensions)",
  "merged_from": [
   "power#1 Server-minted id bracket and binding test",
   "robustness#1 Provider-clock ceiling on each tool round (ceiling comparison never run; kept as an extension)",
   "coverage#1 Server-minted request-id bracket as a stretch guard for latency checks (stretch-guard power unmeasured)",
   "coverage#4 Provider-clock action windows for logs without per-call stamps (aiv_cu Gemini HTTP Date / server-timing; kept as an extension)"],
  "observation": (
   "Honest rate (ids_and_clocks_in_ids/O5 skeptic, " + IXF + "): one constant client-server skew per stream places every decoded request-id time "
   "between the stream's last input event and its first output block in all but <<hon_k>> of <<hon_n>> swechat Claude Code streams, session-clustered rate "
   "0.00272 [0.00112, 0.00466] at 2 s tolerance (0 s gives 18, 5 s gives 7); consistent-stream slack U-L p5 1,102 / p50 2,268 / p95 3,807 ms. "
   "cc_local: <<ccl_w>>. Committed-script copy (analysis/out/phase_c/ids_and_clocks_in_ids.json bracket.swechat.anthropic_req.claude_code): <<lens_br>>; "
   "<<restamp>> inconsistent sessions hold re-stamped resume/fork copies, <<unexpl>> are unexplained (bracket_x_copies.swechat). "
   "Tamper response (O5 skeptic placebo on <<pl_n>> swechat streams): moving one response's first event 5 s earlier flags <<p5>>; 30 s earlier flags <<p30>>; "
   "moving it 5, 30 or 300 s later flags <<pl_late>>, equal to the honest baseline, so the test is one-sided. Wilson intervals here are computed by "
   "analysis/probes/phase_d_ranking.py and treat streams as independent; no session-clustered interval exists for the placebo. "
   "Rolling every response's id by one flags 3,667, but that misbinds all responses at once and is not a single-response test (" + PG + " lenses[0].ground.checks[0]). "
   "PROVENANCE: the placebo counts were produced by the skeptic's uncommitted scratch scripts (o5.py, o5b.py, o5c.py) and survive only as text in committed "
   "_verification_ir.json and _index.json; the committed lens script analysis/probes/phase_c_ids_and_clocks_in_ids.py writes no placebo. "
   "Clock decode: 154,815/154,815 swechat ids v7|var2 against 2,418.98 expected by chance (n includes 50 Vertex ids the loader stored as message ids), "
   "cc_local 31,085/31,085; layout inferred from data, UNVERIFIED against documentation (ids_and_clocks_in_ids/O1). Clock agreement counting every copy "
   "155,067/155,267 = 0.99871 [0.99676, 0.99992] in 1,638 sessions; holdout A 11,047 ids, 0 violations (ids_and_clocks_in_ids/O2). aiv_cc stores 0 request ids "
   "(ids_and_clocks_in_ids/O13). aiv_cu: Anthropic id brackets 0 inconsistent of 105/80/27/32 streams, Gemini 0 of 255/92, OpenAI 3/463, but weak by construction "
   "because the row insert lags the id by a median 5.7-12 s and OpenAI/Gemini ids have 1 s resolution (ids_and_clocks_in_ids/O3, O5); Gemini server-timing fits "
   "inside the row gap in 0/12,292 rows, Wilson hi 3.12e-4, 347 of 2,000 B sessions, min slack 563.8 ms (two_clocks/O7)."),
  "test_measurement": (
   "Pre-register before running: tolerance 2 s; honest rates fixed at <<hon_k>>/<<hon_n>> (swechat CC) and 1/847 (cc_local); session-clustered CIs; one row per "
   "tamper type, never pooled. Step 0: commit the placebo as an analysis/probes script and re-run it on the same streams; FINDINGS may cite the 5 s and 30 s "
   "counts only after that re-run. Step 1, single-response tampers (none measured yet) on swechat CC B, holdout A and cc_local: splice one response with its "
   "request id from another session or from later in the same session; swap two adjacent responses' ids; delete one response; insert one fabricated "
   "call+result round; delay one tool_result by D in {1, 2, 5, 30, 300} s with every id untouched, and the consistent variant that shifts that result and "
   "all later client events by D. Step 2: back-date grid 1-30 s; report D at power 0.5 and 0.9 next to U-L p50 2,268 ms. Kill rule, fixed now: a tamper "
   "type whose flagged-stream rate has a session-clustered lower bound at or below the honest upper bound (0.00466 swechat CC, session-clustered; <<ccl_hi>> "
   "cc_local, Wilson) is reported as a null for that type; if no single-response type clears that bar, the line is reduced to 'back-dating only' and stopped. Each type is also reported next to the 5 s "
   "back-date point as a reference, not as a threshold. Extensions, only after Step 1: (a) ceiling S = t_req(k+1) - t_req(k) against client duration claims "
   "(call->result gap, bash_progress elapsed, durationMs), reporting the honest slack (S-D)/S per timer type before any power claim; (b) aiv_cu Gemini "
   "w = created_at - HTTP Date per row with positive controls (pause, explicit sleep must satisfy w >= requested duration - 1 s) before any separability "
   "claim. Split hygiene: the lenses already read B and holdout A, so the cleanest test set is cc_local sessions recorded after the Phase C commits."),
  "false_positive_source": (
   "Measured: <<hon_k>>/<<hon_n>> inconsistent swechat CC streams at 2 s (18 at 0 s, 7 at 5 s), <<restamp>> sessions explained by re-stamped resume/fork "
   "copies and <<unexpl>> unexplained (bracket_x_copies); cc_local 1/847. Re-stamped copies collapse history onto 1-2 timestamps (2 session pairs, 178 request "
   "ids; ids_and_clocks_in_ids/O7) and must be deduped; counting every copy leaves 190 offsets over 10 min, 12 after the lens dedupe (ids_and_clocks_in_ids/O2). "
   "Client clock steps are not absorbed by a constant skew: drift above 2 s in 15 swechat sessions and in 2 of 18 cc_local sessions (ids_and_clocks_in_ids/O6). "
   "329 v2.1 same-millisecond call/result pairs have no established cause (two_clocks/O12). OpenAI and Gemini ids and HTTP Date have 1 s resolution (OpenAI "
   "3/463 streams inconsistent; HTTP Date orders unambiguously in only 2,831/3,246 flash and 7,276/8,990 pro call rows, distributions/D19). Ceiling leg: async "
   "launches return before their work ends (cc_local 63/63 parent results before the last nested event, two_clocks/O15). Unmeasured: provider-side skew between "
   "consecutive ids, retries, concurrent subagent streams. Blind spots by construction, not false positives: late-stamping (later shifts flag only the "
   "baseline), compression of a call->result gap inside one round (reasoning, not measured), in-band fabrication (the harness stamps it consistently), content "
   "substitution, and any editor who re-mints ids (unsigned; the layout was inferred from data, so a forger can infer it too)."),
  "novelty_guess_unverified": (
   "UNVERIFIED - prior art not checked; do not claim novel. Reading time out of UUIDv1/v7, ULID or Snowflake ids is known forensics, and bounding an event "
   "between causally ordered stamped events with a clock-offset allowance matches the Gladyshev & Patel event-time-bounding line (the grounding skeptic's own "
   "unverified recollection, " + PG + " lenses[0].ground.checks[0]). HTTP Date as a forensic artefact is known. If anything is new it is narrow: LLM-provider "
   "request ids as the external bound on agent tool-log stamps and as a response-binding test."),
  "why_this_rank": (
   "INTERPRETATION. Unanimous rank 1 (3 of 3 rankers). (a) The only merged proposal with a measured tamper response for its own witness against a measured "
   "honest rate: honest <<hon_k>>/<<hon_n>> streams vs 5 s back-date <<p5>> and 30 s back-date <<p30>>, at a resolution on the order of the U-L p50 of 2,268 ms. "
   "(b) Minted by the provider on request receipt; that the model never sees it is reasoning, not observation. It is unsigned and re-mintable by an informed "
   "editor, so it binds post-hoc retiming and misbinding only, one-sided (back-dating), per turn. (c) Anthropic-backed Claude Code only: swechat 155,267 "
   "(session, request) pairs in 1,638 sessions and cc_local 847 streams; aiv_cc stores no request ids, Codex, OpenCode and Gemini CLI have none, aiv_cu is weak "
   "by construction; the share of tool calls covered is unmeasured. (d) Cheapest measurable next step: the lens code is committed and the placebo code exists. "
   "Condition on the rank: the decisive tamper counts come from uncommitted code (disagreement D6). If the committed re-run does not reproduce the 5 s "
   "back-date point, rank 1 loses its criterion-(a) lead and rank 2, whose separation replicates on split A in committed Phase A output, moves to first. "
   "Penalties carried from the grounding checks: 'only measured tamper curve' is false (token_conservation/TC2 has one); 3,667 is an all-response roll, not a "
   "splice; the ceiling and stretch-guard legs were never run; ids_and_clocks_in_ids/O7 is not independent evidence."),
 },
 {
  "rank": 2,
  "key": "image",
  "name": "Provider image-token ledger: per-window screenshot count from Gemini prompt IMAGE units (aiv_cc stripped-image residual as a one-agent case study)",
  "merged_from": [
   "power#4 Quantized server-usage ledger of result modality - image part only (its 128-token cache rule is listed under rank 5 with no weight)",
   "coverage#5 Image-token quanta as a screenshot-count witness for GUI agents",
   "robustness#5 Provider quantization lattices - image-unit part only (D7 usage_in mode and D1 reasoning lattice dropped: not lattices per the grounding check)"],
  "observation": (
   "Split B (token_conservation/TC9 skeptic, " + IXF + "): in aiv_cu Gemini the per-window change in prompt IMAGE tokens is 0 or exactly one per-model unit in "
   "11,668/11,668 pairs (258 for gemini-2.5-pro, n 4,925; 1,064 for 3-pro 682, 3.1-pro 3,166, 3.5-flash 2,895), never negative. It is positive in 5,059/5,092 "
   "GUI windows (misses <<guimiss>>) and in 0 of <<nongui_n>> non-GUI windows in the committed lens table (<<nongui>>; shell 0/4,134, get_pixel_coords 0/2,033, "
   "pause 0/202, send_message_back_to_chat 0/324, other tools 0/<<other_n>>; analysis/out/phase_c/token_conservation.json "
   "aiv_cu_gemini_text_image.dIMAGE_positive_by_top_tool). These Wilson intervals are computed by analysis/probes/phase_d_ranking.py and treat windows as "
   "independent; the committed file stores no per-session counts. Prompt IMAGE counts sit on {258, 1064, 2160} in 10,569/10,569 pro rows and on 1,064 in "
   "3,219/3,219 flash rows; 0/309 sessions mix lattices (distributions/D3 skeptic). Split A, committed Phase A output written before any Phase C lens read B "
   "(analysis/out/phase_a/a5.json part2.aiv_cu/gemini-*.gemini_modality, analysis/probes/phase_a_a5.py): IMAGE rises in gaps holding a GUI result in "
   "pro <<proA>> and flash <<flaA>>, and in gaps without one in pro <<proA_no>> and flash <<flaA_no>>. aiv_cc one-agent case study (aiv_accounting/O11 skeptic): residual per stripped "
   "image median 890.1 [887.9, 890.9], p25 879.1, p75 892.7, n 4,543 single-image pairs in 64 runs, but 227 fall in the 316-562 bin, below the honest "
   "per-turn |residual| p99 of 690.2 (651-735 across splits; aiv_accounting/O10), so single-image power there is below 1 and unmeasured. Context: aiv_cu GUI "
   "results carry text in 0.0002 of rows (aiv_narration/N5)."),
  "test_measurement": (
   "Fix the rule on split A (already measured there) and test on B and the population: per window require dIMAGE = (screenshot-returning actions in the "
   "window) x unit(model generation). Tamper honest B windows four ways: delete one GUI result; relabel a GUI action as shell; insert a fabricated "
   "screenshot-returning call and result with usage untouched; splice in a window from another session. Report detection per tamper type with "
   "session-clustered CIs against the honest 33/5,092 GUI misses and 0/<<nongui_n>> non-GUI increments, and state a session-level honest flag rate, which no "
   "file states yet. Run the regime above 40 images (442 population Gemini sessions exceed 40 GUI turns; no B session does) before any claim past 40. aiv_cc: "
   "add or remove one [IMAGE_REMOVED] marker and report power at FPR 1%, run-clustered, labelled single-agent. Optional: fit an image term for aiv_cu "
   "Anthropic (token_conservation/TC1 skeptic: GUI-window residual median +206.5 vs shell -602.8) to see whether coverage extends past Gemini. Kill rule "
   "(ranker 3's, adopted and fixed now): if the session-level honest flag rate exceeds 0.05, stop the line."),
  "false_positive_source": (
   "Measured: 33/5,092 GUI windows with no increment, unexplained and not cap effects (images before: median 4, max 31; token_conservation/TC9); the unit "
   "depends on model generation (258, 1,064, and 2,160 in 70 rows from 3 sessions; distributions/D3); gemini-3.8-flash (277 pairs) never shows an image (TC9); "
   "cached IMAGE counts are off-lattice (11/3,022 and 40/9,318; D3), so only prompt-side counts are usable; the regime above 40 images is untested; aiv_cc has "
   "30 unlogged non-compaction context resets, 27 of them image pairs (aiv_accounting/O12); user-pasted images vary in size (swechat CC single-image residual "
   "535.0, p5-p95 121-1,618; token_conservation/TC17), so a per-image constant holds only for fixed-size screenshots; per-window misses compound at session "
   "level, unmeasured."),
  "novelty_guess_unverified": (
   "UNVERIFIED - prior art not checked; do not claim novel. Token-count plausibility checks are generic billing practice and value-distribution checks "
   "(Benford-style) are old. The power and robustness grounding checks found no overlap with the listed items; the coverage grounding check found the "
   "narration cross-check close to OverclaimBench and 'Plans They Abandon' (listed) and the ledger itself an extension of our own Phase A conservation plan "
   "(" + PG + "). Using a provider's per-modality token breakdown as an exact count of screenshot-returning results in an agent log may be undescribed; that is a guess."),
  "why_this_rank": (
   "INTERPRETATION. Rankers 2 and 3 placed it 2nd, ranker 1 3rd; resolved on criterion (a) (disagreement D1). (a) The cleanest honest separation of the five "
   "and the only one replicated on held-out data by a committed script that predates Phase C: exact lattice 11,668/11,668; 0 of <<nongui_n>> non-GUI windows "
   "with an increment (Wilson hi <<nongui_hi>>); split A, gaps with a GUI result: pro <<proA>>, flash <<flaA>>; gaps without: pro <<proA_no>>, flash <<flaA_no>>. One-image resolution. No tamper "
   "simulation exists, so detection power is arithmetic, not measured. (b) Provider-computed usage; that it never reaches the model's context is reasoning. "
   "An informed editor can recompute it but must shift IMAGE and promptTokenCount by exact units in every later response while screenshots stay in context; a "
   "live forger who returns a real or fake screenshot gets a real increment, so it counts images and never speaks to their content. (c) Narrowest coverage: "
   "aiv_cu Gemini (11,945 pairs; Gemini rows in 347 of 2,000 B sessions, two_clocks/O7) plus one aiv_cc agent; but that is the corpus where Probe 1 is "
   "NOT_TESTABLE, Probe 2 INCONCLUSIVE and the Probe 3 tail DEAD. (d) Cheapest: TC9 already computes it. Penalties: aiv_cc single-image detectability is below "
   "1 and unmeasured; the bundled 128-token rule was post hoc and trivially satisfiable (moved to rank 5); no session-level false-positive rate exists."),
 },
 {
  "rank": 3,
  "key": "git",
  "name": "Git execution window: a commit SHA printed in a tool result must resolve, and its commit_date must fall inside the printing call's call->result window (fresh generator-printed readings and printed durations as unmeasured extensions; harness-timer legs demoted to internal consistency)",
  "merged_from": [
   "power#3 Execution-window consistency: time evidence in or around a result must fit the window in which it was supposedly produced",
   "robustness#3 Nested timer chain: printed durations <= model-invisible harness timers <= provider interval (printed-duration leg kept as an unmeasured extension; harness-timer legs demoted per the grounding check)"],
  "observation": (
   "commit_witness/O9 skeptic (" + IXF + "), all 3,411 linked Claude Code sessions: 3,936 resolved commit claims in 1,491 sessions; commit_date in "
   "[call ts - 2 s, result ts + 2 s] for 3,917 = 0.995 [0.992, 0.998]; median offset -0.103 s [-0.137, -0.062]. Committed-script copy on the lens sample "
   "(analysis/out/phase_c/commit_witness.json q4.commit_claims.matched_checks.commit_date_in_call_window): <<git_lens>>. Out of window: <<gitout>>; classified "
   "after the fact (commit_witness/O11 skeptic) as 15 cat/tail/head/grep re-reads of earlier output files, 1 amend with an explicit GIT_COMMITTER_DATE and 3 "
   "unexplained. Non-resolution: 2,198/6,141 = 0.358 [0.321, 0.394] of honest commit claims do not resolve, 39% of those with no explaining flag "
   "(commit_witness/O10), so a missing SHA cannot fire on its own. 4,085/5,850 = 0.698 [0.686, 0.710] of swechat sessions link at least one ok commit "
   "(commit_witness/O1). No held-out replication exists: the lens used a seeded sample and the skeptic the population. Fresh readings: fraction-form epochs "
   "in collusion-wiki prose never postdate the external save, 0/459, Wilson hi 0.0083, a post-hoc split, external-witness corpus only (ext_witness/O10). Timer "
   "legs, which the grounding check calls same-clock redundancy (" + PG + " lenses[0].ground.checks[2]): bash_progress floor rule 0/112,677, Wilson hi 3.41e-5 "
   "(two_clocks/O9); Codex model-visible Wall time never exceeds the call->output gap on exec_command, 0 of 4,408, while 0.1 s-display shell_command headers "
   "exceed it in 646/1,817 by at most 49 ms (two_clocks/O6); bash_progress exists in 1,981/4,925 swechat CC files and in 0 of 332 cc_local main files "
   "(raw_census/A6-O10). The printed-duration leg (test-runner 'in X s', shell 'real') was never extracted."),
  "test_measurement": (
   "Split hygiene first: fix the generator vs re-reader command classes on one half of the commit-linked sessions and test on the other, because the 15/19 "
   "classification was made on the full population. (1) Measure the share of all tool results carrying a resolvable SHA or a fresh generator-printed "
   "reading; stop rule: if that share is too small to matter, report it and stop. (2) Honest out-of-window rate per command class, session-clustered CIs, "
   "2 s tolerance. (3) Tamper: replay a real commit-bearing output into a later call of the same session and into another session of the same repo; "
   "fabricate a SHA (compare with the honest 0.358 non-resolution); shift a commit call's stamps on a delta grid; report detection per tamper and power vs "
   "delta at the honest rate. (4) Printed-duration leg only after (1): pre-register regexes on split A, exclude re-readers, and run a lying-backend "
   "simulation (printed 'N passed in 45 s' with an instant-return timing profile drawn from honest calls) plus a padded backend that sleeps for the printed "
   "duration, which should pass and measures the forger's wall-clock cost. Harness-timer legs are reported only as consistency checks."),
  "false_positive_source": (
   "Measured: re-reads of saved output (15 of 19 out-of-window), an explicit committer date (1), 3 unexplained of 3,936 (commit_witness/O11); "
   "auto-backgrounded commands whose result window is not the execution window (111 of 188 swechat 120 s shell results, outliers/O9); 329 unexplained v2.1 "
   "gap-0 pairs where any zero-width window check would fire (two_clocks/O12); display rounding (Codex shell_command 646/1,817 by at most 49 ms) and write_stdin "
   "poll stamps (14/1,600, min -36.1 ms) (two_clocks/O6); one machine-suspend progress overrun among 83,521 events (two_clocks/O10); stored ids and dates "
   "echoed by tools are not fresh (440 of 561 v7 mentions more than 10 min older, ids_and_clocks_in_ids/O14). Non-resolving SHAs (0.358 of honest claims) "
   "must abstain, not fire."),
  "novelty_guess_unverified": (
   "UNVERIFIED - prior art not checked; do not claim novel. The grounding checks call it partly prior art: the git leg is a claim-vs-record existence check "
   "overlapping our own git shadow-state core plan; the window logic is event-time bounding (Gladyshev & Patel line, listed); extracting printed durations is "
   "output-grammar parsing (jc, listed). The possibly new part is bounding non-recomputable outputs by the log's own call window, as opposed to METR-style "
   "recomputation of deterministic outputs."),
  "why_this_rank": (
   "INTERPRETATION. Ranker 1 placed it 2nd, rankers 2 and 3 3rd; resolved on criterion (a) (disagreement D1). (a) Honest in-window 0.995 [0.992, 0.998] "
   "(out of window <<gitout>>) at about 2 s resolution, but the exceptions that cut 19 to 3 were classified after seeing them, there is no held-out "
   "replication, and no tamper response is measured. (b) The strongest witness of the five: commit_date is hashed into a SHA held in an external repo, so a "
   "fabricated or replayed resolving commit claim needs a real commit with a chosen committer date in that repo (committer dates can be set: 1 amend "
   "observed). It is the only proposal whose core leg can bear on live fabrication of a result rather than post-hoc log edits, and its printed-duration "
   "extension is the only leg aimed at a lying tool backend behind an honest harness; both points are reasoning, not measurement. (c) Narrow: Entire-linked "
   "swechat CC only (3,936 resolved claims, 1,491 sessions); cc_local, aiv_cc and aiv_cu have no commit table; the share of results carrying such evidence is "
   "unmeasured. (d) Moderate: command classification, regexes and git lookups. Penalties: bundling same-clock harness timers as evidence, the overstated "
   "forging cost, and the post-hoc ext_witness split. If criterion (b) were placed first, i.e. binding result content to an external record, this would move "
   "to rank 2, which is ranker 1's position."),
 },
 {
  "rank": 4,
  "key": "dual",
  "name": "Harness dual-rendering recount: Claude Code toolUseResult structured counters (Read numLines, subagent totalToolUseCount, Edit/Grep counters) vs the model-visible result text",
  "merged_from": [
   "power#2 Visible-text vs harness structured-copy recount at 1-unit resolution",
   "coverage#3 Dual-rendering check: harness-only structured result fields vs the model-visible result text"],
  "observation": (
   "raw_census/A6-O1 skeptic, full swechat population (" + IXF + "): Read toolUseResult.file.numLines equals the numbered lines of the visible result in "
   "87,827/88,229 = 0.9954, Wilson [0.9950, 0.9959], cluster [0.9947, 0.9960] over 4,603 files; all 402 mismatches (275 files) are named formats: 282 "
   "persisted-output previews, 105 'file shorter than offset' warnings, 7 identical-to references, 7 redactions, 1 negative line numbers. cc_local main "
   "570/578 = 0.986 [0.973, 0.993], all 8 mismatches empty-file warnings; cc_local subagent files carry numLines in 0 of 12 Read results. Committed-script "
   "sample (analysis/out/phase_a/a6_raw_census.json): 2,510/2,514. raw_census/A6-O2: subagent totalToolUseCount equals the distinct nested tool_use ids in "
   "6,623/6,623, Wilson [0.9994, 1.0], 1,934 files; 2,150/8,773 = 0.245 [0.236, 0.254] of Agent/Task results have no nested traffic and cannot be checked. "
   "Field fill (raw_census/A6-O4): Read 88,229/90,763 = 0.972, Edit structuredPatch 70,553/73,460 = 0.960, Grep numLines 29,535/34,208 = 0.863 (agreement not "
   "measured); Glob totalMatches 0/6,422 in swechat; cc_local main Read 578/650 = 0.889 [0.863, 0.911]. Current Claude Code has no progress/agent_progress "
   "entries: 0 of 332 cc_local main and 840 subagent files (raw_census/A6-O10)."),
  "test_measurement": (
   "Freeze the whitelist now (the five swechat formats plus the cc_local empty-file warning) and measure the honest unexplained rate only on data it was not "
   "derived from (split-A swechat files; cc_local sessions recorded after the Phase C commits); the existing 0 is in-sample. Tamper clean Read results: add or "
   "delete 1, 2 or 5 lines; splice a same-path Read from another session; count-preserving substitution (expected invisible); rewrite a result into a "
   "whitelisted format, to measure the whitelist as an evasion route. Do the same for A6-O2 by deleting or inserting one nested tool_use. Then measure "
   "agreement, not fill, for Grep numLines and for Edit structuredPatch oldLines/newLines against old_string/new_string line counts. Needs a loader change "
   "(no loader reads numLines or structuredPatch), to be decided by day."),
  "false_positive_source": (
   "Measured: the 402 swechat format mismatches and 8 cc_local empty-file warnings (a detector without the whitelist fires on all of them); the whitelist "
   "exempts any result an editor rewrites into those formats; version drift (cc_local subagent files 0/12 numLines; Glob totalMatches 0/6,422 in swechat vs "
   "1,231/1,234 in cc_local); 2,150/8,773 Agent/Task results uncheckable, to be counted as abstentions, not passes; dataset redaction (7 of the 402)."),
  "novelty_guess_unverified": (
   "UNVERIFIED - prior art not checked; probably not novel as a technique. Consistency between redundant fields is a generic integrity idea. The two grounding "
   "checks disagree: power#2's found no overlap with the listed items; coverage#3's found substantial overlap with output-grammar parsing (jc), recomputation "
   "(METR) and our own filesystem shadow-state plan for the cross-call part (" + PG + ")."),
  "why_this_rank": (
   "INTERPRETATION. Unanimous rank 4 (3 of 3). (a) Largest-n exact agreement of any proposal (87,827/88,229 over 4,603 files; 6,623/6,623) at 1-line "
   "resolution, but '0 unexplained' is in-sample because the whitelist was built from the same 402 mismatches, and no tamper response is measured. (b) The "
   "weakest witness: one harness writes both renderings from the same read, so a schema-aware editor rewrites both, count-preserving substitution is "
   "invisible, and a lying execution layer yields two consistent renderings; it catches naive post-hoc text edits and export faults only. (c) Claude Code "
   "formats only; the subagent leg has no coverage in current Claude Code. (d) Low to medium (a loader change). Below rank 3 because the two are near-tied "
   "on (a), both resting on exception lists drawn up after seeing the exceptions, while rank 3's witness is external and this one is same-writer; above rank 5 "
   "because it touches result content at 1-line resolution."),
 },
 {
  "rank": 5,
  "key": "ledger",
  "name": "Usage-ledger reconciliation: commit-time Entire usage tally frozen in git, plus parameter-free provider usage identities (cache-append chain; Codex 128-token cache granularity as a post-hoc note)",
  "merged_from": [
   "power#5 Frozen usage-ledger reconciliation at tolerance 0",
   "robustness#2 Commit-time freeze points (git-held usage tally and agent_changes; cache-chain amplification adds nothing at tolerance 0 per the grounding check)",
   "coverage#2 Usage-ledger propagation check",
   "robustness#4 Prompt-cache state - cache-append chain identity only; the 'stopwatch' claim is dropped (8/32 long-gap breaks)",
   "power#4 / robustness#5 Codex/OpenCode 128-token cache granularity - post hoc, carries no ranking weight"],
  "observation": (
   "swechat_tables/T1 skeptic (" + IXF + "): the Entire CLI's 5-integer usage tally equals a tolerance-0 recount of the stored transcript in 4,794/4,836 = "
   "0.9913 [0.9883, 0.9936] Claude-format sessions (repo-clustered [0.9874, 0.9942], 183 repos): full 2,772, prefix 1,664, window 358, none 42; prefix "
   "snapshots precede the last transcript stamp in 1,664/1,664, median 3 messages before the end. The skeptic: the tally is a deterministic recount of the "
   "transcript's own usage fields; its only independent content is the commit-time snapshot. After the dataset join fix, unmatched 33/5,701 = 0.0058 "
   "[0.0041, 0.0081] across 4 scaffolds (swechat_tables/T3); by CLI version 0.4.x 11/3,691 = 0.0030 [0.0017, 0.0053], 0.5.x 15/1,048 = 0.0143 [0.0087, 0.0235] "
   "(swechat_tables/T4). Cache-append chain exact in 0.975 / 0.982 / 0.999 of clean swechat CC / cc_local / aiv_cc pairs (token_conservation/TC1); aiv_cc "
   "59,747/59,804, run-clustered 0.99905 [0.99858, 0.99943]; breaks 49/59,772 at gaps under 300 s and 8/32 at 300 s or more; compaction 0/933 "
   "(aiv_accounting/O9). Codex cached_input_tokens is a multiple of 128 in 16,106/16,106 calls, found post hoc (swechat_tables/T11). Content binding comes only "
   "through token conservation: inserted-text power 0.5/0.9 at 8,913/10,000 chars in swechat CC at realized FPR 0.0101 [0.0092, 0.0112], power 0.0099 at "
   "+3,000 chars (token_conservation/TC2); deleting a [100, 1,000)-char result has power 0.003, n 61,269 (token_conservation/TC16)."),
  "test_measurement": (
   "On the 5,701 swechat sessions with a tally: delete one assistant message.id inside the snapshot; insert a copied message.id; append after the snapshot "
   "(expected invisible); insert a tool_use block into an existing message.id (expected invisible); edit result content (invisible to the tally). Report "
   "detection per tamper against the honest 33/5,701, overall and per CLI version. Measure the share of tool results inside a frozen span. Before any "
   "session-level use of the cache-chain identity, characterize the honest swechat CC and cc_local breaks (per-pair exactness 0.975 and 0.982; per-session "
   "break rate unmeasured). aiv_cc (one agent): delete or insert a response with null stop_reason."),
  "false_positive_source": (
   "Measured: 33/5,701 unmatched after the join correction, 6 of them in one repo, higher in CLI 0.5.x (15/1,048); the dataset join artifact must be fixed "
   "first (it resolves 31 of 64 raw mismatches; swechat_tables/T3); checkpoint rows duplicated across repos (3,650/13,406 rows; swechat_tables/T9); aiv_cc "
   "cache-chain breaks at compaction (0/933 hold), image pairs (4,367/4,570 hold) and long gaps (8/32) (aiv_accounting/O9); 30 unlogged non-compaction context "
   "resets with 0/30 context_management objects (aiv_accounting/O12), the exact signature an 'unchanged-prefix certificate' would flag; uncharacterized "
   "swechat CC and cc_local chain breaks; non-null stop_reason responses omitted from result.usage depending on SDK version and date (15 of 211 runs; "
   "aiv_accounting/O7); hidden-content tools in conservation (ToolSearch residual median +897.4 with 0 logged chars; token_conservation/TC4)."),
  "novelty_guess_unverified": (
   "UNVERIFIED, and mostly listed prior art per the grounding checks (" + PG + "): a commit-time tally acting as a seal is hash-chain sealing (Agent Flight "
   "Recorder, NovaFabric, listed); the Entire CLI is installed capture-side tooling (Hearsay/ACE/Tracekit category); ledger reconciliation is standard audit "
   "practice; content binding is our own Phase A token-conservation plan; prompt-cache auditing has external prior art (Gu et al. 2025, 'Auditing Prompt "
   "Caching in Language Model APIs'; relevance UNVERIFIED). Do not claim novel."),
  "why_this_rank": (
   "INTERPRETATION. Unanimous rank 5 (3 of 3). (a) Honest unmatched 0.0058 [0.0041, 0.0081] at tolerance 0 with one-message resolution by arithmetic, but no "
   "tamper response is measured and it is blind to tool-result content: a content edit faces only token conservation (8,913 chars at power 0.5 in swechat CC). "
   "(b) The model never sees usage (reasoning), but the tally is a recount an editor can redo; the anchor is a local git branch rewritable until pushed, and "
   "push time is not in the data; a live forger gets a real count of the fake output; every identity is arithmetic a forger can propagate. (c) The frozen "
   "anchor exists only in Entire-linked swechat sessions; the identities span more scaffolds but constrain turn structure, not results. (d) Cheap to medium "
   "(the T1 matcher exists). Last because it constrains which turns exist rather than what the results said, and it carries the heaviest prior-art overlap."),
 },
]

BUILD_FIRST = (
 "INTERPRETATION. Build rank 1 first (unanimous across the three rankers), scoped as a post-hoc retiming and response-binding check, not a fabrication "
 "detector. Order of work: (0) commit the skeptic's placebo (scratch o5.py, o5b.py, o5c.py) as an analysis/probes script and re-run it; the 5 s and 30 s "
 "back-date counts that decide criterion (a) come from uncommitted code today, so FINDINGS may cite them only after that re-run, and if the re-run does not "
 "reproduce the 5 s point, rank 1 loses its (a) lead and rank 2 is built first instead. (1) Single-response tamper suite: splice one response with a foreign "
 "request id, swap two adjacent ids, delete one response, insert one fabricated round, and delay one result by D in {1, 2, 5, 30, 300} s with ids untouched "
 "and with a consistent re-stamp; plus a 1-30 s back-date grid; on swechat CC B, holdout A and cc_local, session-clustered CIs, one row per tamper type. "
 "(2) Kill rule, fixed now: a tamper type whose flagged-stream rate has a lower bound at or below the honest upper bound (0.00466 swechat CC, session-clustered; "
 "<<ccl_hi>> cc_local, Wilson) is a null for that type; if no single-response type clears it, report the bracket as back-dating-only and stop the line. Why rank 1: (i) it is the only proposal whose own "
 "witness has both a measured honest rate (<<hon_k>>/<<hon_n>> = 0.00272 [0.00112, 0.00466]; cc_local <<ccl_w>>) and a measured tamper response (5 s "
 "back-date <<p5>>; 30 s <<p30>>), so the next run can fail cleanly against a stated rule; (ii) the lens code is committed and the placebo code exists, so it "
 "is the cheapest measurable next step; (iii) it runs on the corpora where Probe 1 is ALIVE (cc_local) or WEAK (swechat CC), whose timing verdicts depend on "
 "the stamps it checks. Limits stated up front: blind to in-band fabrication, to late-stamping and, by reasoning, to compression of a call->result gap; binds "
 "only editors who do not re-mint ids; whether ids can be checked against provider records is untestable with our data. Second, in parallel if capacity "
 "allows: rank 2's tamper suite on aiv_cu Gemini (cheap; its separation already replicates on split A). If the priority is instead binding result content to "
 "an external record, rank 3 goes first, gated on its coverage-share stop rule."
)

RELATION = (
 "INTERPRETATION over committed numbers. Phase B values are read by analysis/probes/phase_d_ranking.py from analysis/out/probe_{1,2,3,4}.json "
 "(ranking.json phase_b_reference). Threat model: Probes 1-4 test behavioural signs that the producer fabricated a result (inline generation, knowledge from "
 "nowhere, missing pushback, invented values). The five proposals are mostly log-integrity witnesses against post-hoc edits (retiming, inserted, deleted or "
 "misbound turns). Among them only rank 3's git leg tests a result's content against an external record. Validation: Probes 1-4 were pre-registered "
 "(thresholds from split A, commit 3df8d28), produced mechanical verdicts on B, and were independently re-derived in <<pb_ok>> of <<pb_tot>> unit checks "
 "(analysis/out/phase_b_verification.json). The proposals come from lenses that read B before Phase B ran; they are not pre-registered and their honest rates "
 "are in-sample. Only rank 1 has a measured tamper response for its own witness, and that response comes from uncommitted code; rank 5's content leg reuses "
 "token_conservation/TC2. Only rank 2's core separation also appears on split A, in committed Phase A output. Neither side has a fabricated positive control. "
 "Tested results: Probe 1 is ALIVE in swechat/opencode (fp <<p1_oc>>) and cc_local (fp <<p1_ccl>>); WEAK in swechat CC (fp <<p1_cc>>, downgraded because the "
 "floor is UNSTABLE), aiv_cc (fp <<p1_aivcc>>, one agent) and codex (fp <<p1_codex>>); NOT_TESTABLE in <<p1_nt>>. Probe 2 has <<p2_alive>> ALIVE cells: the "
 "best is S_deep <<p2_cc>> in swechat CC main (WEAK; subagents <<p2_sub>>); it is DEAD in opencode main (<<p2_oc>>), codex main (<<p2_cx>>) and cc_local main "
 "(<<p2_ccl>>), and INCONCLUSIVE in aiv_cu (<<p2_cu>>). Probe 3: the zero-error tail is ALIVE only in swechat CC (Z <<p3_cc>>) and DEAD in cc_local "
 "(<<p3_ccl>>) and aiv_cu (<<p3_cu>>); reaction is at best WEAK (swechat CC effect <<p3_react>>). Probe 4: hex is never ALIVE (swechat CC w_adj <<p4_hcc>>; "
 "aiv_cu <<p4_hcu>>; INSUFFICIENT_N in <<p4_ins>> units); round numbers are ALIVE in <<p4_ralive>>: swechat CC <<p4_rcc>>; cc_local <<p4_rccl>>; but the post-hoc "
 "tables attribute the effect mostly to models choosing round parameters such as timeouts (analysis/notes/probe_4.md, post-hoc descriptive section). Comparison: rank 1's honest per-stream rate 0.00272 [0.00112, 0.00466] is of the same order as "
 "Probe 1's best fp shares, on a different unit. The other proposals' honest violation counts are 0 of <<nongui_n>> non-GUI windows and 33/5,092 GUI windows "
 "(rank 2), 19/3,936 out-of-window commit claims (rank 3), 402/88,229 raw Read mismatches, all whitelisted after the fact (rank 4), and 33/5,701 sessions "
 "(rank 5), all below Probe 2's best 0.144 and Probe 3's session-level tail 0.022. That comparison is not like for like: the proposals' low rates belong "
 "to structural identities a schema-aware editor can satisfy, the probes' rates to behavioural signals a fabricator has to work to avoid, and an honest rate "
 "is not a detection rate. Complementarity: rank 1 binds the stamps Probe 1 relies on but, by reasoning, does not see a compressed call->result gap inside "
 "one round, which is how an editor would hide an inline-generated result from Probe 1. Rank 2 is the only candidate for aiv_cu, where Probe 1 is "
 "NOT_TESTABLE, Probe 2 INCONCLUSIVE, the Probe 3 tail DEAD and Probe 4 WEAK. Rank 3 is the only one that tests result content against an external record; "
 "no Phase B probe does. No proposal revives a DEAD probe cell, and no probe verdict is confirmed by Phase C, because the Phase C lenses read the same B "
 "split. Outside this ranking (ranker 2's note): commit_witness/O3 and O6 (Edit '+'-line full match 0.829 [0.812, 0.844] vs cross-repo decoy 0.0014 "
 "[0.0009, 0.0020]; Write committed-content full 0.843 [0.825, 0.861] vs decoy 0.0011 [0.0003, 0.0022]) are the strongest external-witness separations in "
 "the data, but they were not among the 15 proposals and overlap the core git shadow-state plan."
)

SUMMARY = (
 "RECONCILIATION NOTE (full notes with numbers: analysis/out/phase_d/ranking.json disagreements D1-D8). The three rankers agreed on ranks 1, 4 and 5 "
 "and on the build-first choice. The one contested pair was ranks 2 and 3 (ranker 1: git 2, image 3; rankers 2 and 3: image 2, git 3). Resolved on "
 "criterion (a), the first of the (a)-(d) criteria all three rankers use: neither has a tamper response, but the image ledger has 0 of <<nongui_n>> non-GUI windows with an "
 "increment (<<nongui>>) and a split-A replication from committed pre-Phase-C code (pro <<proA>> with a GUI result and <<proA_no>> without; flash <<flaA>> "
 "and <<flaA_no>>), while git's out-of-window claims (<<gitout>>) shrink to 3 only through a post-hoc classification and have no held-out replication; so "
 "(b), where git is stronger, was not reached. Ranker 1's sources do not include analysis/out/phase_a/a5.json. Other differences were scope and procedure, "
 "with no rank effect: the 128-token rule listed under rank 5 with no weight (D2); harness-timer legs demoted to consistency checks per the grounding check "
 "(D3); the Gemini header leg and the ceiling kept as extensions (D4); the rank-1 kill rule set against the honest baseline (rankers 2 and 3), with ranker "
 "1's 5 s point as a reference (D5); the placebo provenance flag (rankers 2 and 3) made a gating step 0 (D6). The task text arrived truncated and without "
 "ranking 3; all three rankings were read in full from the ranker files (D8)."
)

DISAGREEMENTS = [
 {"id": "D1", "topic": "Order of the image-token ledger and the git execution window (final ranks 2 and 3)",
  "positions": {"ranker_1": "git 2, image 3", "ranker_2": "image 2, git 3", "ranker_3": "image 2, git 3"},
  "rankers_reasons": {
   "ranker_1": "(a) treated as comparable (in-window 0.995 vs exact lattice, neither with a tamper response); (b) decides: commit_date is hashed into an external, content-addressed record.",
   "ranker_2": "(a) favours image: exact lattice and zero non-GUI increments with no post-hoc exclusion list; git's exceptions were classified post hoc.",
   "ranker_3": "(a) favours image: exact lattice, zero non-GUI increments, and the only core separation that also appears on split A in committed Phase A output."},
  "numbers": (
   "Neither has a tamper response. Image: 0 of <<nongui_n>> non-GUI windows with an increment (<<nongui>>); GUI misses <<guimiss>>; split A, gaps with a GUI "
   "result: pro <<proA>>, flash <<flaA>>; gaps without: pro <<proA_no>>, flash <<flaA_no>>; from a committed Phase A script that predates Phase C. Git: out of window <<gitout>> "
   "(lens sample <<git_lens>>); the reduction from 19 to 3 rests on a post-hoc command classification; no held-out replication. In the insertion direction "
   "the two Wilson intervals (GUI misses vs out-of-window claims) <<overlap>>."),
  "resolution": (
   "INTERPRETATION. Criteria order (a) measured separability or tamper power on honest data, (b) witness independence or recompute cost, (c) coverage, "
   "(d) build cost (ranker 3's criteria_order; rankers 1 and 2 use the same (a)-(d) labels). On (a) the two are not tied: the image ledger has a zero-violation "
   "direction at n <<nongui_n>> and a held-out replication from committed pre-Phase-C code, while git's honest exceptions are reduced only by a post-hoc "
   "classification and are not replicated. So (a) decides and (b), where git is clearly stronger, is not reached; (d) also favours the image ledger, and (c) is "
   "narrow for both. Final: image 2, git 3 (2 of 3 rankers). Ranker 1's sources_read does not list analysis/out/phase_a/a5.json, the file holding the split-A "
   "replication, which accounts for its reading of (a) as a tie. Condition that would flip the order: placing criterion (b) first, i.e. prioritizing a "
   "witness that binds result content to an external record.")},
 {"id": "D2", "topic": "Placement of the Codex/OpenCode 128-token cache granularity rule",
  "positions": {"ranker_1": "note under the image ledger, plausibility check only", "ranker_2": "note under the image ledger, no weight",
                "ranker_3": "moved to rank 5 (usage identities)"},
  "numbers": "Codex cached_input_tokens multiple of 128 in 16,106/16,106 calls, found post hoc (swechat_tables/T11).",
  "resolution": (
   "INTERPRETATION. All three agree it carries no weight: it was found post hoc and an informed forger satisfies it trivially, so it adds nothing to (a) or "
   "(b). It is a cache-token identity, not an image count, so it is listed under rank 5's usage identities and the rank-2 merge stays about images. No effect "
   "on any rank.")},
 {"id": "D3", "topic": "Scope of the git execution-window mechanism (timer legs and printed durations)",
  "positions": {"ranker_1": "harness-timer legs dropped as same-clock redundancy; printed durations as step 4 after a coverage stop rule",
                "ranker_2": "timer legs kept in the observation with the skeptic's caveat; printed-duration leg called the only proposal aimed at a lying tool backend",
                "ranker_3": "timer chain demoted to internal consistency; fresh readings as an extension"},
  "numbers": "bash_progress floor 0/112,677 (two_clocks/O9); Codex exec_command Wall time 0/4,408, shell_command 646/1,817 (two_clocks/O6); progress stream in 0 of 332 cc_local main files (raw_census/A6-O10).",
  "resolution": (
   "INTERPRETATION. Follow the grounding check (" + PG + " lenses[0].ground.checks[2]): one process clock writes the timer legs and the stamps, so 'inside "
   "the window' is near-tautological and the timer legs are reported as consistency checks only. The printed-duration leg is kept as an unmeasured "
   "extension, gated on the coverage share; ranker 2's 'lying backend' point is kept in why_this_rank as reasoning. No effect on any rank.")},
 {"id": "D4", "topic": "Scope of the request-id bracket (aiv_cu Gemini header leg and inter-request ceiling)",
  "positions": {"ranker_1": "unmeasured extensions", "ranker_2": "Gemini HTTP Date / server-timing named as the aiv_cu leg of the mechanism",
                "ranker_3": "unmeasured extensions"},
  "numbers": "Gemini server-timing inside the row gap 0/12,292, Wilson hi 3.12e-4 (two_clocks/O7) is an honest-consistency count with no tamper and no positive control; aiv_cu id bracket weak by construction (row insert lags the id by a median 5.7-12 s; ids_and_clocks_in_ids/O3).",
  "resolution": "INTERPRETATION. Criterion (a) is unmeasured for both legs, so they stay as extensions run only after the single-response suite. No effect on any rank."},
 {"id": "D5", "topic": "Kill rule for the rank-1 tamper suite",
  "positions": {"ranker_1": "stop if single-response splice/delay power does not exceed the measured 5 s back-date point (1,441/3,673)",
                "ranker_2": "per tamper type, stop if the flagged rate's CI overlaps the honest 10/3,674 and report the bracket as back-dating-only",
                "ranker_3": "stop and report a null if single-response power at <= 5 s is not above the upper CI of the honest stream rate"},
  "numbers": "Honest upper bound 0.00466 (ids_and_clocks_in_ids/O5); 5 s back-date reference <<p5>>.",
  "resolution": (
   "INTERPRETATION. Rules 3 and 6 call for a threshold fixed in advance against the honest baseline, not against another tamper's result. Adopted: rankers "
   "2 and 3's honest-baseline bar per tamper type (lower bound of the flagged rate at or below 0.00466 means a null for that type; no type clearing it ends "
   "the line). Ranker 1's 5 s point is reported alongside as a reference comparison.")},
 {"id": "D6", "topic": "Provenance of the rank-1 placebo counts",
  "positions": {"ranker_1": "cited 1,441/3,673 and 3,581/3,673 without a provenance flag",
                "ranker_2": "flagged: uncommitted scratch script, not citable in FINDINGS until re-run from a committed script",
                "ranker_3": "flagged the same, with o5.py, o5b.py, o5c.py named"},
  "numbers": "Script names found in committed _verification_ir.json: <<pl_scripts>>. Committed lens script mentions a placebo: <<pl_lens>>.",
  "resolution": (
   "INTERPRETATION. Verified: the placebo exists only as skeptic text, from uncommitted code. The same holds for many skeptic-only numbers the brief tells us "
   "to use (for example the token_conservation/TC1 pipeline, scratchpad/tc/, and the ids_and_clocks_in_ids/O1 decode, scratchpad/rd/o1.py), so the "
   "placebo is not excluded; but because it alone decides rank 1's criterion-(a) lead, committing and re-running it is step 0 of build-first, and a failed "
   "re-run moves rank 2 to first.")},
 {"id": "D7", "topic": "Second build choice",
  "positions": {"ranker_1": "git window first if the goal is binding result content to an external record",
                "ranker_2": "printed-duration leg if the threat is a lying tool backend; image ledger for GUI logs",
                "ranker_3": "image ledger in parallel (split-A replication, only the tamper simulation missing)"},
  "resolution": "INTERPRETATION. Follows from the final order and criterion (d): the image ledger in parallel; the git window first only if criterion (b) is given priority."},
 {"id": "D8", "topic": "Input completeness",
  "positions": {"note": "The orchestrator's task text was truncated inside ranking 2's relation_to_phase_b and did not include ranking 3."},
  "resolution": (
   "All three inputs were read in full from the ranker files analysis/out/phase_d/inputs/ranker_{1,2,3}.json (byte-identical copies of the scratchpad "
   "rank_{1,2,3}.json; sha256 in inputs_sha256). Rankings 1 and 2 match the task text in substance; the task-text versions add a pointer line (ranking 1) and "
   "an empty rank_note field (ranking 2).")},
]

# ---------------------------------------------------------------- fill placeholders
V["pl_scripts"] = ", ".join(ver_ir_mentions)
V["pl_lens"] = "yes" if lens_script_has_placebo else "no"
TOK = re.compile(r"<<(\w+)>>")


def fill(s):
    out = TOK.sub(lambda m: V[m.group(1)], s)
    assert "<<" not in out, out
    return out


def fill_obj(o):
    if isinstance(o, str):
        return fill(o)
    if isinstance(o, list):
        return [fill_obj(x) for x in o]
    if isinstance(o, dict):
        return {k: fill_obj(v) for k, v in o.items()}
    return o


final = fill_obj(FINAL)
build_first = fill(BUILD_FIRST)
relation = fill(RELATION)
disagreements = fill_obj(DISAGREEMENTS)
summary = fill(SUMMARY)

# ---------------------------------------------------------------- checks
CIT = re.compile(r"\b(ids_and_clocks_in_ids|two_clocks|token_conservation|commit_witness|raw_census|swechat_tables|aiv_accounting|"
                 r"aiv_narration|distributions|correlations|ext_witness|outliers|changepoints|sequences|ids)/((?:A6-)?[A-Z]{1,2}\d+)")


def citations(text):
    out = set()
    for lens, oid in CIT.findall(text):
        out.add(("ids_and_clocks_in_ids" if lens == "ids" else lens, oid))
    return out


def cite_report(text):
    rep = []
    for key in sorted(citations(text)):
        o = OBS.get(key)
        rep.append({"cite": f"{key[0]}/{key[1]}", "in_index": o is not None, "reproduced": None if o is None else o["reproduced"]})
    return rep


final_text = json.dumps([final, build_first, relation, disagreements, summary], ensure_ascii=False)
final_cites = cite_report(final_text)
bad = [c for c in final_cites if not c["in_index"] or c["reproduced"] is not True]
assert not bad, bad
input_cites = {f"ranker_{i}": cite_report(json.dumps(d, ensure_ascii=False)) for i, d in rankers.items()}

# number trace: numeric tokens in the final text that appear in no committed source and no computed value
# Narrow corpus on purpose: observation texts of _index.json, the grounding file, and the values this script read or computed.
src_files = [IX_PATH, A("out", "phase_c", "_proposals_grounded.json")]
corpus = " ".join(o["numbers"] + " " + o["skeptic_numbers"] + " " + o["skeptic_problem"] + " " + o["statement"]
                  for o in ix["observations"])
corpus += " " + open(src_files[1], encoding="utf-8").read() + " " + json.dumps(V) + " " + json.dumps(W) + " " + json.dumps(PB)
corpus_nc = corpus.replace(",", "")
NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?:e-?\d+)?")
unmatched = sorted({t for t in NUM.findall(final_text) if len(t.replace(",", "").lstrip("-")) >= 3
                    and t.replace(",", "") not in corpus_nc})

result = {
 "probe": "phase_d_ranking",
 "script": "analysis/probes/phase_d_ranking.py",
 "field_kinds": {
  "final_ranking[].observation": "data with citations (skeptic-corrected numbers from analysis/out/phase_c/_index.json unless a committed file path is given)",
  "final_ranking[].false_positive_source": "data with citations",
  "final_ranking[].test_measurement": "plan, not measured",
  "final_ranking[].novelty_guess_unverified": "unverified guess; prior art not checked",
  "final_ranking[].why_this_rank": "INTERPRETATION",
  "build_first": "INTERPRETATION",
  "relation_to_phase_b": "INTERPRETATION over committed numbers",
  "disagreements[].resolution": "INTERPRETATION applying the stated criteria",
  "reconciliation_summary": "INTERPRETATION; short form of disagreements",
  "computed": "data: read from committed files by JSON path; Wilson intervals from analysis/lib/stats.wilson",
 },
 "criteria_order": rankers[3].get("criteria_order"),
 "standing_caveats": [
  "Novelty of every proposal is UNVERIFIED; prior art is checked separately. None is asserted to be new.",
  "Phase C discovery lenses read split B before Phase B ran. Phase B thresholds came only from Phase A, but Phase B is not a blind held-out test, and Phase C numbers are in-sample on B or the full population.",
  "aiv_cc is a single agent (effectively one SDK session): case study only. cc_local is private: aggregates only.",
  "SWE-chat source is the pinned f66cca95 raw transcripts, not conversations.parquet. Who&When has no timestamps and every task is a failure. collusion-wiki and urlquery have no agent-side tool calls (external witnesses only).",
  "Skeptic-corrected numbers are used wherever a skeptic disagreed; no not-reproduced or unchecked observation is cited (citation_check).",
  "Many skeptic-only numbers, including rank 1's decisive placebo counts, were produced by uncommitted scratch scripts and survive only as text in committed JSON; rule 1 is fully met for them only once those scripts are committed and re-run.",
 ],
 "final_ranking": final,
 "build_first": build_first,
 "relation_to_phase_b": relation,
 "reconciliation_summary": summary,
 "disagreements": disagreements,
 "computed": {
  "positions_by_ranker": {f"ranker_{i}": positions[i] for i in rankers},
  "proposal_ids_by_ranker": {f"ranker_{i}": merged_ids[i] for i in rankers},
  "pairwise": pairwise,
  "contested_pairs": [p["pair"] for p in pairwise if not p["unanimous"]],
  "decisive_numbers": W,
  "phase_b_reference": PB,
 },
 "citation_check": {"final": final_cites, "inputs": input_cites,
                    "rule": "every lens/ID cited in the final text is in _index.json with reproduced == true (asserted)"},
 "number_trace": {"tokens_not_found_in_sources": unmatched,
                  "sources": [os.path.relpath(p, ROOT).replace(os.sep, "/") for p in src_files],
                  "note": "numeric tokens (3+ characters) in the final text found neither in the _index.json observation texts, the grounding file, nor the values read or computed by this script; expected to be test-design parameters only"},
 "inputs_sha256": {f"ranker_{i}": sha(p) for i, p in INPUTS.items()},
 "ranker_inputs": {f"ranker_{i}": d for i, d in rankers.items()},
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=1, ensure_ascii=False)
print("wrote", os.path.relpath(OUT, ROOT))
print("positions", {i: positions[i] for i in rankers})
print("contested", result["computed"]["contested_pairs"])
print("final citations", len(final_cites), "all reproduced")
print("unmatched numeric tokens", unmatched)
print("nongui", W["image_nongui"], "guimiss", W["image_gui_miss"], "gitout", W["git_skeptic_out"])
print("overlap", W["insertion_direction_overlap"])
