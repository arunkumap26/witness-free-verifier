"""Phase E, Track A, task A0: consolidate Phases A-D into one MECHANISM x CORPUS decision table.

Reads committed outputs only. It opens no event data, no cache and no split E or H file:
  analysis/out/probe_{1,2,3,4}.json          Phase B verdicts per unit (split B)
  analysis/out/phase_a.json                  Phase A gate verdicts (A1 latency kill rule, A5 conservation gate; split A)
  analysis/out/phase_a/a5.json               split-A image-ledger replication, A5 infeasible units
  analysis/out/phase_a/a6_raw_census.json    committed dual-rendering sample (Read numLines)
  analysis/prereg.json                       verdict vocabulary and thresholds
  analysis/out/phase_b_verification.json     one re-derivation number (Probe 2 opencode subagent, strict root rule)
  analysis/out/phase_c/_index.json           skeptic-checked observations; [S] numbers are copied verbatim from its text
  analysis/out/phase_c/{ids_and_clocks_in_ids,token_conservation,commit_witness,swechat_tables}.json  lens numbers
  analysis/out/phase_d/ranking.json          the five ranked proposals, their plans and their computed numbers
Writes:
  analysis/out/phase_e/decision_table.json   one row per mechanism x corpus: status, deciding number, n, source path per
                                             cell, raw values. No interpretation (README rule 4).
  analysis/DECISION_TABLE.md                 the table, a compact grid, counts and a three-sentence statement. The
                                             'What would change this' column and the statement are interpretation and
                                             live only in the .md.
Before writing, the script checks that every number token in the .md also occurs in the .json text.

Run from the worktree root:  python -m analysis.probes.phase_e_a0
"""
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

F = {
    "p1": "analysis/out/probe_1.json",
    "p2": "analysis/out/probe_2.json",
    "p3": "analysis/out/probe_3.json",
    "p4": "analysis/out/probe_4.json",
    "pa": "analysis/out/phase_a.json",
    "a5": "analysis/out/phase_a/a5.json",
    "a6": "analysis/out/phase_a/a6_raw_census.json",
    "pr": "analysis/prereg.json",
    "pv": "analysis/out/phase_b_verification.json",
    "ix": "analysis/out/phase_c/_index.json",
    "ids": "analysis/out/phase_c/ids_and_clocks_in_ids.json",
    "tc": "analysis/out/phase_c/token_conservation.json",
    "cw": "analysis/out/phase_c/commit_witness.json",
    "st": "analysis/out/phase_c/swechat_tables.json",
    "rk": "analysis/out/phase_d/ranking.json",
}
OUT_JSON = "analysis/out/phase_e/decision_table.json"
OUT_MD = "analysis/DECISION_TABLE.md"
SCRIPT = "analysis/probes/phase_e_a0.py"

D, SHA = {}, {}


def ap(p):
    return os.path.join(ROOT, *p.split("/"))


def load_all():
    for k, p in F.items():
        b = open(ap(p), "rb").read()
        SHA[p] = hashlib.sha256(b).hexdigest()
        D[k] = json.loads(b.decode("utf-8"))


def get(fk, *keys):
    x = D[fk]
    for k in keys:
        x = x[k]
    return x


_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def path(fk, *keys):
    s = ""
    for k in keys:
        if isinstance(k, int):
            s += f"[{k}]"
        elif _ID.match(k):
            s += ("." if s else "") + k
        else:
            s += f"['{k}']"
    return f"{F[fk]}: {s}"


# ---------------------------------------------------------------- number formatting (the .md shows these strings only)
def fi(n):
    return f"{int(round(float(n))):,}"


def fr(x):
    if x is None:
        return "NA"
    x = float(x)
    a = abs(x)
    if a < 1e-9:
        return "0"
    if a >= 10:
        return f"{x:,.1f}"
    if a >= 0.1:
        return f"{x:.3f}"
    d = -math.floor(math.log10(a)) + 1
    return f"{x:.{d}f}"


def ci(lo, hi):
    return f"[{fr(lo)}, {fr(hi)}]"


def kn(k, n):
    return f"{fi(k)}/{fi(n)}"


def rate_s(d, k="num", n="den", r="rate"):
    return f"{kn(d[k], d[n])} = {fr(d[r])} {ci(d['lo'], d['hi'])}"


# ---------------------------------------------------------------- [S] extraction: verbatim substrings of committed skeptic text
def obs(lens, oid):
    for o in get("ix", "observations"):
        if o["lens"] == lens and o["id"] == oid:
            return o
    raise KeyError((lens, oid))


def obs_path(lens, oid):
    for i, o in enumerate(get("ix", "observations")):
        if o["lens"] == lens and o["id"] == oid:
            return path("ix", "observations", i, "skeptic_numbers")
    raise KeyError((lens, oid))


def sx(lens, oid, pattern):
    """Return the verbatim substring of an observation's skeptic_numbers that matches pattern (must match)."""
    t = obs(lens, oid)["skeptic_numbers"]
    m = re.search(pattern, t)
    if not m:
        raise ValueError(f"pattern not found in {lens}/{oid}: {pattern}")
    return m.group(0)


# ---------------------------------------------------------------- corpora and mechanisms
BASE = ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "swechat/cursor",
        "swechat/copilot", "swechat/simple_text", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
P3_UNITS = BASE[:-1] + ["whowhen/Algorithm-Generated", "whowhen/Hand-Crafted"]
P4_UNITS = BASE + ["swechat/*", "public/*"]
CLABEL = {"aiv_cc": "aiv_cc (one agent: case study)", "cc_local": "cc_local (private: aggregates only)",
          "swechat/*": "swechat/* (pooled)", "public/*": "public/* (pooled; contains aiv_cc)",
          "whowhen/Algorithm-Generated": "whowhen (Algorithm-Generated)", "whowhen/Hand-Crafted": "whowhen (Hand-Crafted)"}
SHORT = {"swechat/claude_code": "sw/claude_code", "swechat/codex": "sw/codex", "swechat/opencode": "sw/opencode",
         "swechat/gemini": "sw/gemini", "swechat/cursor": "sw/cursor", "swechat/copilot": "sw/copilot",
         "swechat/simple_text": "sw/simple_text", "cc_local": "cc_local", "aiv_cc": "aiv_cc", "aiv_cu": "aiv_cu",
         "whowhen": "whowhen", "collusion-wiki": "collusion-wiki", "urlquery": "urlquery"}

MECH = {}       # key -> display name
GROUP_OF = {}   # key -> group
ROWS, INTERP = [], {}

PRE, GATE, XD, XW = "preregistered_phase_b", "phase_a_gate", "exploratory_phase_d", "exploratory_external_witness"
EXPL, NOTM = "EXPLORATORY", "EXPLORATORY (not measured)"


def mech(key, name, group):
    MECH[key] = name
    GROUP_OF[key] = group


def add(mk, corpus, status, deciding, n, sources, values=None, labels=None, provenance=None, interp="", flags=None):
    r = {"id": len(ROWS) + 1, "group": GROUP_OF[mk], "mechanism_key": mk, "mechanism": MECH[mk], "corpus": corpus,
         "corpus_label": CLABEL.get(corpus, corpus), "status": status, "deciding_number": deciding, "n": n,
         "labels": list(labels or []), "provenance": list(provenance or ["committed"]), "sources": sources,
         "values": values or {}}
    if corpus == "aiv_cc":
        r["labels"].append("single-agent case study")
    r["labels"] = list(dict.fromkeys(x for x in r["labels"] if isinstance(x, str)))
    if r["status"] == NOTM and "deciding_number" not in r["sources"]:
        r["sources"]["deciding_number"] = "no measurement of this check on this corpus in any Phase A-D output"
    if flags:
        r.update(flags)
    ROWS.append(r)
    INTERP[r["id"]] = interp
    return r


def thr():
    """Pre-registered rule texts copied verbatim (data, not interpretation); the interpretation column cites them."""
    pr = D["pr"]
    return {
        "verdict_vocabulary_prereg": pr["global"]["verdict_vocabulary"],
        "added_labels": {
            "KILLED-in-A1": "Probe 1 only: the unit failed gate_rules.A1_latency_kill_rule in Phase A (split A) and was not "
                            "run in Phase B; prereg.json calls it NOT_TESTABLE ('killed in Phase A').",
            "GATE: TIGHT / LOOSE / NOT_TIGHT / INSUFFICIENT": "Phase A gate label of gate_rules.A5_conservation_rule "
                                                               "(token conservation). Not a Phase B verdict.",
            "EXPLORATORY": "not pre-registered; the measured honest-baseline number is shown and no verdict is assigned.",
            "EXPLORATORY (not measured)": "not pre-registered and not measured on this corpus.",
            "DEAD (by prereg)": "Probe 3 cells prereg.json set to DEAD before Phase B ran (no results, no failure signal "
                                "or no calls); not computed.",
        },
        "global_min_n": pr["global"]["min_n"],
        "probe1": {"labels": pr["probe1"]["separability"]["labels"], "min_n": pr["probe1"]["separability"]["min_n"],
                   "verdict": pr["probe1"]["verdict"], "floor_label": pr["probe1"]["floor_step_change"]["label"]},
        "probe2": {"verdict": pr["probe2"]["verdict"]["per_unit_main_thread"], "caps": pr["probe2"]["verdict"]["caps"],
                   "min_n": pr["probe2"]["statistics"]["min_n"]},
        "probe3": {"verdict": pr["probe3"]["verdict"], "min_n": pr["probe3"]["min_n"]},
        "probe4": {"verdict": pr["probe4"]["verdict"], "N_min": get("p4", "thresholds_used", "N_min")},
        "a5_gate": get("pa", "gate_rules", "A5_conservation_rule", "rule"),
        "phase_d_plans_not_measured": {r["key"]: r["test_measurement"] for r in get("rk", "final_ranking")},
        "sources": {"verdict_vocabulary_prereg": path("pr", "global", "verdict_vocabulary"),
                    "global_min_n": path("pr", "global", "min_n"),
                    "probe1": path("pr", "probe1"), "probe2": path("pr", "probe2"), "probe3": path("pr", "probe3"),
                    "probe4": path("pr", "probe4") + "; " + path("p4", "thresholds_used", "N_min"),
                    "a5_gate": path("pa", "gate_rules", "A5_conservation_rule", "rule"),
                    "phase_d_plans_not_measured": path("rk", "final_ranking") + "[*].test_measurement"},
    }


# ================================================================ Probe 1: latency physics
def a1_key(u):
    return "A1.verdict." + u.replace("/", "_")


def build_p1():
    mech("p1_latency", "Probe 1: latency physics", PRE)
    gm = get("pr", "global", "min_n", "rate_reportable")
    for u in BASE:
        v = get("p1", "verdicts", u)
        hk = a1_key(u)
        a1 = get("pa", "headline", hk, "value")
        src_v = path("p1", "verdicts", u)
        if v["verdict"] == "NOT_TESTABLE":
            nt = get("p1", "not_testable", u)
            src = {"status": [src_v, path("pa", "headline", hk)], "deciding_number": [path("pa", "headline", hk), path("p1", "not_testable", u)],
                   "n": [path("pa", "headline", hk), path("p1", "not_testable", u)]}
            b = nt.get("a1_recheck_B_descriptive")
            if a1["verdict"] == "KILLED":
                parts = []
                rs = a1["reason"]
                if "shared_call_result_stamp" in rs:
                    s = a1["identical_stamp_share"]
                    parts.append(f"A1 (split A): call and result share one stamp in {kn(s['num'], s['den'])} pairs ({fi(s['n_sessions'])} s)")
                if "no_timestamps" in rs:
                    parts.append(f"A1 (split A): no timestamps; {fi(a1['n_pairs_both_ts'])} of {fi(a1['n_pairs'])} pairs carry both stamps")
                if "no_call_result_pairs_with_both_stamps" in rs:
                    s = a1["all_event_whole_second_stamp_share"]
                    parts.append(f"A1 (split A): no call/result pairs; {kn(s['num'], s['den'])} event stamps are whole-second ({fi(s['n_sessions'])} s)")
                if b:
                    if "shared_call_result_stamp" in b["reason"]:
                        s = b["identical_stamp_share"]
                        parts.append(f"B re-check: {kn(s['num'], s['den'])} pairs share one stamp ({fi(s['n_sessions'])} s)")
                    else:
                        parts.append(f"B re-check: {fi(b['n_pairs_both_ts'])} of {fi(b['n_pairs'])} pairs stamped ({fi(nt['B_sessions'])} B s)")
                else:
                    parts.append(f"{fi(nt['B_sessions'])} B sessions")
                a_pairs = a1.get("n_pairs", a1.get("n_pairs_both_ts"))
                n = f"A {fi(a_pairs)} pairs; B {fi(b['n_pairs']) if b else '0'} pairs from {fi(nt['B_sessions'])} s"
                why = {"aiv_cu": "per-action latency is gone: only the inter-turn gap is left",
                       "whowhen": "the record has no clock at all"}.get(u, "the record has no usable call/result stamps")
                add("p1_latency", u, "KILLED-in-A1", "; ".join(parts), n, src,
                    values={"a1": a1, "b_recheck": b, "B_sessions": nt["B_sessions"]},
                    interp=f"Killed in Phase A because {why}. Only a re-export carrying separate call and result stamps "
                           f"at sub-second resolution would reopen it; no analysis of the current record can.")
            else:
                s = a1["identical_stamp_share"]
                add("p1_latency", u, "NOT_TESTABLE",
                    f"A1 ALIVE on {fi(a1['n_sessions'])} A sessions only ({fi(a1['n_pairs_both_ts'])} pairs, identical stamps {kn(s['num'], s['den'])}); {fi(nt['B_sessions'])} B sessions",
                    f"{fi(nt['B_sessions'])} B sessions", src, values={"a1": a1, "B_sessions": nt["B_sessions"]},
                    interp=f"Needs B sessions; the A1 pass rests on {fi(a1['n_sessions'])} A sessions.")
            continue
        d = v["deciding"]
        fp, auc = d["fp_share"], d["auc"]
        fp_s = f"fp {rate_s(fp)}"
        if fp["num"] == 0:
            fp_s = f"fp {kn(fp['num'], fp['den'])}; per-event Wilson hi {fr(fp['wilson_hi_per_event'])} (used by the verdict)"
        if "auc" in auc:
            auc_s = f"AUC {fr(auc['auc'])} {ci(auc['lo'], auc['hi'])}"
        else:
            auc_s = f"AUC {auc['label']} (G {fi(auc['n_G'])} pairs from {fi(d['G_eligible_sessions'])} s)"
        fs = get("p1", "units", u, "floor_step_change")
        below = fs["eligible_series"] < gm["den_min"] or fs["eligible_sessions"] < gm["sessions_min"]
        if below:
            floor_s = (f"floor-step {kn(fs['steps'], fs['eligible_series'])} series from {fi(fs['eligible_sessions'])} s, below min n "
                       f"(JSON label {fs['label']}; read as INSUFFICIENT_N)")
        else:
            w = fs["step_share_wilson"]
            floor_s = f"floor-step {kn(fs['steps'], fs['eligible_series'])} = {fr(w['p'])} W{ci(w['lo'], w['hi'])} series from {fi(fs['eligible_sessions'])} s: {fs['label']}"
        deciding = f"{fp_s}; {auc_s}; {floor_s}. Rule: {v['rule_applied']}"
        n = (f"W {fi(d['W_eligible'])} pairs ({', '.join(d['W_reportable'])}) from {fi(d['W_eligible_sessions'])} s; "
             f"G {fi(d['G_eligible'])} from {fi(d['G_eligible_sessions'])} s")
        src = {"status": src_v + ".verdict", "deciding_number": [src_v + ".deciding", path("p1", "units", u, "floor_step_change")],
               "n": src_v + ".deciding"}
        st = v["verdict"]
        if st == "ALIVE":
            it = (f"Floor stability is untested here ({kn(fs['steps'], fs['eligible_series'])} series from {fi(fs['eligible_sessions'])} s, "
                  f"below the minimum of {gm['den_min']} from {gm['sessions_min']} sessions); an UNSTABLE floor on enough series would "
                  f"downgrade it to WEAK. The positive control G comes from {fi(d['G_eligible_sessions'])} sessions, so a broader G could move "
                  f"the AUC. Read-type tools only. Replication on split E is pending.")
        elif v.get("downgrade"):
            it = (f"fp and AUC both pass; only the mid-session floor shifts ({kn(fs['steps'], fs['eligible_series'])} series) hold it at WEAK. "
                  f"If the Phase E follow-up finds a shared benign cause, it returns to ALIVE; if the shifts are regime changes, they are "
                  f"a signal to study, not noise.")
        elif v["fp_label"] == "ALIVE":
            it = (f"fp passes but there is no usable positive control: G needs {get('pr', 'probe1', 'separability', 'min_n', 'G')} "
                  f"(has {fi(d['G_eligible'])} from {fi(d['G_eligible_sessions'])} s). Small n.")
        else:
            it = f"fp_share {fr(fp['rate'])} misses the ALIVE bar (fp_share <= 0.05 with CI hi <= 0.10)"
            if d["G_eligible"] == 0:
                it += "; this harness also has no generation-bound control tool, so the AUC cannot be computed"
            if u == "aiv_cc":
                it += "; one agent, so a change here says little about other agents"
            it += "."
        add("p1_latency", u, st, deciding, n, src, values={"deciding": d, "floor_step_change": {k: fs[k] for k in fs if k != "series"},
                                                           "rule_applied": v["rule_applied"]}, labels=v.get("labels"), interp=it)


# ================================================================ Probe 2: knowledge precedence
def build_p2():
    mech("p2_main", "Probe 2: knowledge precedence (main thread)", PRE)
    mech("p2_sub", "Probe 2: knowledge precedence (subagent stratum)", PRE)
    pv_txt = get("pv", "probes", 1, "rederive", "checks", 2, "my_numbers")
    for u in BASE:
        for st, mk in (("main", "p2_main"), ("sub", "p2_sub")):
            v = get("p2", "verdicts", u, st)
            sv = path("p2", "verdicts", u, st)
            status = v["verdict"]
            if status == "NOT_TESTABLE":
                add(mk, u, status, f"not testable: {v['reason']}", "0", {"status": sv, "deciding_number": sv, "n": sv},
                    values=v, interp="Needs B sessions with tool calls.")
                continue
            if status == "INSUFFICIENT_N":
                uv = get("p2", "units", u, "strata", st, "verdict")
                su = path("p2", "units", u, "strata", st, "verdict")
                dec = (f"below min n: S_deep {fi(uv['S_deep_n'])} deep first-try accesses from {fi(uv['S_deep_sessions'])} s; "
                       f"S_path_any {fi(uv['S_path_any_n'])} first mentions from {fi(uv['S_path_any_sessions'])} s"
                       + (f" ({uv['note']})" if uv.get("note") else ""))
                mn = uv["min_n"]
                add(mk, u, status, dec, f"{fi(uv['S_deep_n'])} / {fi(uv['S_path_any_n'])}", {"status": sv, "deciding_number": su, "n": su},
                    values=uv, labels=v.get("labels"),
                    interp=f"Needs {mn['S_deep'][0]} deep first-try accesses from {mn['S_deep'][1]} sessions (S_deep) or "
                           f"{mn['S_path_any'][0]} first-mention paths from {mn['S_path_any'][1]} sessions (S_path_any).")
                continue
            stat = v["deciding_statistic"]
            dec = f"{stat} {kn(v['k'], v['n'])} = {fr(v['value'])} {ci(*v['ci'])}"
            if v.get("caps_applied"):
                dec += f"; caps: {'; '.join(v['caps_applied'])}"
            src = {"status": sv + ".verdict", "deciding_number": sv, "n": sv}
            prov = ["committed"]
            vals = dict(v)
            if u == "swechat/opencode" and st == "sub":
                m = re.search(r"The fallback is S_path_any [\d.]+ \[[\d.]+, [\d.]+\], [\d,]+/[\d,]+, \d+ sessions, which gives WEAK", pv_txt)
                if not m:
                    raise ValueError("opencode sub PV text not found")
                dec += f"; depends on logged deviation 5 (child-session root); under the strict root rule S_deep has n = 0 and: {m.group(0)}"
                src["deciding_number"] = [sv, path("p2", "deviations", 5), path("pv", "probes", 1, "rederive", "checks", 2, "my_numbers")]
                vals["pv_strict_root"] = m.group(0)
                prov.append("verification_text")
            what = "deep first-try accesses" if stat == "S_deep" else "first-mention paths"
            n = f"{fi(v['n'])} {what} from {fi(v['n_sessions'])} s"
            fallback = any("S_path_any" in c for c in v.get("caps_applied", []))
            if status == "WEAK":
                it = f"ALIVE needs S_deep <= 0.05 with CI hi <= 0.10 (here {stat} = {fr(v['value'])}). "
                if fallback:
                    it += ("S_deep is below min n, and the S_path_any fallback is capped at WEAK, so this cell cannot become ALIVE "
                           "without enough deep first-try accesses. ")
                it += ("Context the record lacks (system prompts, the user's own knowledge) makes every unsourced rate an upper "
                       "bound; fuller antecedent capture could only lower it.")
            elif status == "DEAD":
                it = (f"The honest baseline defeats it: {fr(v['value'])} of {what} are unsourced (DEAD above 0.20). Only a fuller "
                      f"antecedent record (system prompt, repo listing) could revive it; on this record it is dead.")
            else:  # INCONCLUSIVE
                it = ("Would be DEAD, but the antecedent record is known to be incomplete (first-try success is a proxy here); "
                      "only a full context record could decide it.")
            add(mk, u, status, dec, n, src, values=vals, labels=v.get("labels"), provenance=prov, interp=it)


# ================================================================ Probe 3: environment pushback
def build_p3():
    mech("p3_tail", "Probe 3a: zero-error tail (primary)", PRE)
    mech("p3_retry", "Probe 3b: retry reaction to failure (secondary)", PRE)
    mn = get("pr", "probe3", "min_n")
    for u in P3_UNITS:
        vv = get("p3", "verdicts", u)
        sv = path("p3", "verdicts", u)
        if u not in get("p3", "units"):
            nr = get("p3", "not_run", u)
            sn = path("p3", "not_run", u)
            for mk, key in (("p3_tail", "zero_error_tail"), ("p3_retry", "reaction")):
                st = vv[key]
                if st == "NOT_TESTABLE":
                    add(mk, u, st, f"not testable: {nr['prereg_reason']}", "0 B sessions", {"status": sv, "deciding_number": sn, "n": sn},
                        values=nr, labels=vv["labels"], interp="Needs B sessions.")
                else:
                    add(mk, u, "DEAD", f"DEAD by prereg, not computed ({nr['prereg_reason']}); B: {fi(nr['calls'])} calls, "
                                       f"{fi(nr['results'])} results, {fi(nr['paired_calls'])} paired",
                        f"{fi(nr['B_sessions_in_cache_all_rows'])} B s", {"status": sv, "deciding_number": sn, "n": sn},
                        values=nr, labels=vv["labels"], flags={"dead_by_prereg": True},
                        interp=f"Dead by construction ({nr['prereg_reason']}); only a record carrying results and failure markers would reopen it.")
            continue
        U = get("p3", "units", u)
        su = path("p3", "units", u)
        vb = U["verdict"]
        # zero-error tail
        t = vb["zero_error_tail"]
        Z = t["deciding_number"]["Z"]
        L = U["zero_error_tail"]["L75"]
        st = t["verdict"]
        if st == "INSUFFICIENT_N":
            dec = f"Z {kn(Z['k'], Z['n'])} long sessions error-free (insufficient n). Rule: {t['rule_applied']}"
        else:
            dec = (f"Z {kn(Z['k'], Z['n'])} = {fr(Z['share'])} W{ci(Z['lo'], Z['hi'])} of long sessions (>= {fi(L['L'])} calls) have no "
                   f"primary error; Z/E0 = {fr(L['Z_over_E0'])}. Rule: {t['rule_applied']}")
        n = f"{fi(Z['n'])} long sessions (L75 = {fi(L['L'])} calls); {fi(U['paired_calls'])} paired calls in {fi(U['sessions_with_paired_calls'])} s"
        if st == "ALIVE":
            it = (f"Z/E0 = {fr(L['Z_over_E0'])}: errors clump by session, so Z mostly measures clumping, and the cell describes the "
                  f"honest baseline only. A split E replication with Z above 0.10 (or Wilson hi above 0.20) would demote it; no "
                  f"fabricated session exists to show the tail separates anything.")
        elif st == "DEAD":
            it = (f"The honest baseline defeats it: {fr(Z['share'])} of long sessions are error-free (DEAD above 0.30), close to what "
                  f"independent errors predict (Z/E0 = {fr(L['Z_over_E0'])}). Only a different, validated error definition could change it.")
        elif st == "WEAK":
            it = (f"WEAK only by the 0.30 bar: Z/E0 = {fr(L['Z_over_E0'])} shows no excess over independent errors, and "
                  f"{fi(Z['n'])} long sessions is below the 30 that ALIVE needs.")
        else:
            it = f"Needs {mn['zero_error_verdict']}; has {fi(Z['n'])}."
        add("p3_tail", u, st, dec, n, {"status": sv + ".zero_error_tail", "deciding_number": [su + ".verdict.zero_error_tail", su + ".zero_error_tail.L75"],
                                       "n": [su + ".zero_error_tail.L75", su + ".paired_calls"]},
            values={"verdict_block": t, "L75": L}, labels=vv["labels"], interp=it)
        # retry reaction
        r = vb["reaction"]
        e = r["deciding_number"]["effect"]
        R = U["retry"]
        st = r["verdict"]
        dec = (f"effect R_fail - R_ok = {fr(e['value'])} {ci(e['lo'], e['hi'])}; R_fail {kn(R['R_fail']['num'], R['R_fail']['den'])}, "
               f"R_ok {kn(R['R_ok']['num'], R['R_ok']['den'])}. Rule: {r['rule_applied']}")
        n = (f"{fi(r['deciding_number']['n_fail_with_successor'])} failed predecessors from {fi(r['deciding_number']['sessions_fail_with_successor'])} s; "
             f"{fi(r['deciding_number']['n_ok_with_successor'])} ok predecessors")
        if st == "WEAK":
            it = f"ALIVE needs effect CI lo >= 0.10; here CI lo = {fr(e['lo'])}."
            if u == "aiv_cu":
                it += " The error definition is an unvalidated stderr proxy, capped at WEAK."
        else:
            it = f"Effect CI lo {fr(e['lo'])} <= 0: agents here do not retry more after a failure than after a success."
            if e["hi"] < 0:
                it += " The effect is negative (retries are rarer after failures)."
        add("p3_retry", u, st, dec, n, {"status": sv + ".reaction", "deciding_number": [su + ".verdict.reaction", su + ".retry"],
                                        "n": su + ".verdict.reaction.deciding_number"},
            values={"verdict_block": r, "R_fail": R["R_fail"], "R_ok": R["R_ok"]}, labels=vv["labels"], interp=it)


# ================================================================ Probe 4: entropy / incidental detail
def build_p4():
    mech("p4_hex", "Probe 4a: hex digit uniformity (primary)", PRE)
    mech("p4_round", "Probe 4b: round numbers (secondary)", PRE)
    Nmin = get("p4", "thresholds_used", "N_min")
    for u in P4_UNITS:
        pooled = u.endswith("/*")
        blk = "pooled" if pooled else "units"
        V = get("p4", blk, u, "verdicts")
        sv = path("p4", blk, u, "verdicts")
        flags = {"pooled": True} if pooled else None
        ulabels = [] if pooled else [x for x in (get("p4", "units", u).get("labels") or []) if isinstance(x, str)]
        # hex
        h = V["hex_primary"]
        st = h["verdict"]
        dd = h.get("deciding")
        if st == "NOT_TESTABLE":
            add("p4_hex", u, st, f"not testable: {h['reason']}", "0 B sessions", {"status": sv + ".hex_primary", "deciding_number": sv + ".hex_primary", "n": sv + ".hex_primary"},
                values=h, flags=flags, interp="Needs B sessions.")
        else:
            n = (f"T_orig {fi(dd['T_orig_symbols'])} symbols / {fi(dd['T_orig_tokens'])} tokens / {fi(dd['T_orig_sessions'])} s; "
                 f"control {dd['control']} {fi(dd['control_symbols'])} symbols / {fi(dd['control_sessions'])} s")
            if st == "INSUFFICIENT_N":
                dec = h["reason"] + ("; control missing (0 symbols)" if dd["control_symbols"] == 0 else "")
                it = f"Needs {Nmin} model-originated hex symbols (N_min); this unit has {fi(dd['T_orig_symbols'])}."
                if dd["control_symbols"] == 0:
                    it += " The machine-hex control is also missing."
            else:
                dec = (f"T_orig w_adj {fr(dd['T_orig_w_adj'])} {ci(dd['T_orig_w_adj_lo'], dd['T_orig_w_adj_hi'])} against control "
                       f"{dd['control']} CI hi {fr(dd['control_w_adj_hi'])}. Rule: {h['reason']}")
                it = (f"Model-originated hex is less uniform than machine hex, but w_adj {fr(dd['T_orig_w_adj'])} is below the 0.15 "
                      f"ALIVE bar. More T_orig symbols would narrow the CI; the effect may still be too small to flag single tokens.")
            add("p4_hex", u, st, dec, n, {"status": sv + ".hex_primary.verdict", "deciding_number": sv + ".hex_primary.deciding", "n": sv + ".hex_primary.deciding"},
                values=h, labels=ulabels + list(h.get("labels") or []), flags=flags, interp=it)
        # round numbers
        rr = V["round_numbers_secondary"]
        st = rr["verdict"]
        dd = rr.get("deciding")
        if st == "NOT_TESTABLE":
            add("p4_round", u, st, f"not testable: {rr['reason']}", "0 B sessions", {"status": sv + ".round_numbers_secondary", "deciding_number": sv + ".round_numbers_secondary", "n": sv + ".round_numbers_secondary"},
                values=rr, flags=flags, interp="Needs B sessions.")
            continue
        tk, tn = dd["T_orig_last0_k_n"]
        n = f"T_orig {fi(dd['T_orig_distinct'])} distinct values from {fi(dd['T_orig_sessions'])} s; M_all {fi(dd['M_all_distinct'])} from {fi(dd['M_all_sessions'])} s"
        src = {"status": sv + ".round_numbers_secondary.verdict", "deciding_number": sv + ".round_numbers_secondary.deciding",
               "n": sv + ".round_numbers_secondary.deciding"}
        if st == "INSUFFICIENT_N":
            dec = f"T_orig last digit 0: {kn(tk, tn)} (insufficient n). Rule: {rr['reason']}"
            it = (f"Needs {dd['min_values']} distinct values from {dd['min_sessions']} sessions in each class; T_orig has "
                  f"{fi(dd['T_orig_distinct'])} from {fi(dd['T_orig_sessions'])}.")
        else:
            mk_, mn_ = dd["M_all_last0_k_n"]
            dec = (f"T_orig last digit 0: {kn(tk, tn)} = {fr(dd['T_orig_last0'])} {ci(dd['T_orig_last0_lo'], dd['T_orig_last0_hi'])} "
                   f"against machine M_all {kn(mk_, mn_)} = {fr(dd['M_all_last0'])} {ci(dd['M_all_last0_lo'], dd['M_all_last0_hi'])}. Rule: {rr['reason']}")
            ph = None
            if not pooled:
                ph = get("p4", "units", u).get("post_hoc_descriptive", {}).get("ints_T_by_origin", {}).get("T_orig")
            if ph:
                jn, sa = ph["json_number"]["last_0"], ph["args_string"]["last_0"]
                dec += (f"; post hoc, feeds no verdict: JSON-number parameters {kn(jn['k'], jn['n'])}, string-embedded subset "
                        f"{kn(sa['k'], sa['n'])} = {fr(sa['rate'])} {ci(sa['lo'], sa['hi'])}")
                src["deciding_number"] = [src["deciding_number"], path("p4", "units", u, "post_hoc_descriptive", "ints_T_by_origin", "T_orig")]
            if st == "ALIVE":
                it = ("Partly confounded with numbers the model chooses (timeouts, head -n, sleep): the Phase E A1 follow-up re-runs it "
                      "without model-chosen timeouts, and if the gap to machine numbers collapses it is DEAD.")
                if ph:
                    it += f" Post hoc, the string-embedded subset alone ({fr(sa['rate'])}) still sits above the bar."
                if u == "cc_local":
                    it += f" T_orig comes from {fi(dd['T_orig_sessions'])} sessions of one private corpus."
            else:
                it = (f"ALIVE needs the T_orig CI lo above the M_all CI hi + 0.05; here CI lo {fr(dd['T_orig_last0_lo'])} against "
                      f"M_all hi {fr(dd['M_all_last0_hi'])}.")
        add("p4_round", u, st, dec, n, src, values=rr, labels=ulabels + list(rr.get("labels") or []), flags=flags, interp=it)


# ================================================================ Phase A gate: token conservation
def build_a5():
    mech("a5_gate", "Token conservation (Phase A A5 gate label; no Phase B probe)", GATE)
    G = get("pa", "gate_rules", "A5_conservation_rule", "groups")
    nf = get("a5", "part2_not_feasible")
    one = {"swechat/claude_code": "swechat/claude_code", "swechat/codex": "swechat/codex", "swechat/opencode": "swechat/opencode",
           "swechat/gemini": "swechat/gemini", "cc_local": "cc_local", "aiv_cc": "aiv_cc"}
    for u in BASE:
        if u in one:
            g = G[one[u]]
            rk_, sk_ = f"A5.{one[u]}.ratio", f"A5.{one[u]}.spearman"
            ra, sp = get("pa", "headline", rk_, "value"), get("pa", "headline", sk_, "value")
            lab = g["label_sha1"]
            dec = (f"ratio {fr(ra['value'])} {ci(ra['lo'], ra['hi'])} (cross-fit median |residual| / typical result tokens); "
                   f"Spearman {fr(sp['r'])} {ci(sp['lo'], sp['hi'])}")
            n = f"{fi(g['fit_pairs'])} fit pairs from {fi(g['fit_sessions'])} s (split A)"
            src = {"status": path("pa", "gate_rules", "A5_conservation_rule", "groups", one[u], "label_sha1"),
                   "deciding_number": [path("pa", "headline", rk_), path("pa", "headline", sk_)],
                   "n": path("pa", "gate_rules", "A5_conservation_rule", "groups", one[u])}
            if lab == "TIGHT":
                it = ("TIGHT, but in one agent only. A second TIGHT corpus, and a tamper curve showing single-result edits are "
                      "detectable at a usable size, would be needed before this carries a mechanism.")
            elif lab == "LOOSE":
                it = ("Passes the gate but cannot carry a mechanism: in Phase C only multi-thousand-character edits to one result "
                      "were detectable at a 1% false-positive rate (TC2).")
            else:
                it = ("The residual exceeds the typical result size, so inserted results hide in the noise; Phase C found the tails "
                      "do not shrink with model-aware fits (TC14, TC10).")
            add("a5_gate", u, f"GATE: {lab}", dec, n, src, values={"group": g, "ratio": ra, "spearman": sp}, interp=it)
        elif u == "aiv_cu":
            ra = get("pa", "headline", "A5.aiv_cu/anthropic_all.ratio", "value")
            strata = {k.split("/", 1)[1]: v["label_sha1"] for k, v in G.items() if k.startswith("aiv_cu/") and k != "aiv_cu/anthropic_all"}
            nfs = sorted(k.split("/", 1)[1] for k in nf if k.startswith("aiv_cu/"))
            g = G["aiv_cu/anthropic_all"]
            dec = (f"anthropic_all ratio {fr(ra['value'])} {ci(ra['lo'], ra['hi'])}; strata: "
                   + ", ".join(f"{k} {v}" for k, v in strata.items()) + f"; no usage data: {', '.join(nfs)}")
            add("a5_gate", u, f"GATE: {g['label_sha1']}", dec, f"{fi(g['fit_pairs'])} fit pairs from {fi(g['fit_sessions'])} s (anthropic_all, split A)",
                {"status": path("pa", "gate_rules", "A5_conservation_rule", "groups", "aiv_cu/anthropic_all", "label_sha1"),
                 "deciding_number": [path("pa", "headline", "A5.aiv_cu/anthropic_all.ratio"), path("pa", "gate_rules", "A5_conservation_rule", "groups")],
                 "n": path("pa", "gate_rules", "A5_conservation_rule", "groups", "aiv_cu/anthropic_all"),
                 "no_usage": path("a5", "part2_not_feasible")},
                values={"anthropic_all": g, "ratio": ra, "strata": strata, "not_feasible": nfs},
                interp="Every stratum is NOT_TIGHT or INSUFFICIENT; the GUI windows carry image tokens that the text fit cannot "
                       "explain. Phase D rank 2 uses those image tokens directly instead.")
        else:
            x = nf[u]
            add("a5_gate", u, "NOT_TESTABLE", f"no conservation fit: {x['reason']} ({fi(x['rows_usage_in'])} rows with usage_in of {fi(x['rows'])}, split A)",
                f"{fi(x['sessions'])} A sessions", {"status": path("a5", "part2_not_feasible", u), "deciding_number": path("a5", "part2_not_feasible", u),
                                                    "n": path("a5", "part2_not_feasible", u)},
                values=x, interp="Needs per-call input/context token counts, which this record does not carry.")


# ================================================================ EXPLORATORY: Phase D ranked proposals
def rank_name(key):
    for r in get("rk", "final_ranking"):
        if r["key"] == key:
            return f"Phase D rank {r['rank']}: " + r["name"].split(":")[0]
    raise KeyError(key)


def build_d():
    for key, mk in (("bracket", "d1_bracket"), ("image", "d2_image"), ("git", "d3_git"), ("dual", "d4_dual"), ("ledger", "d5_ledger")):
        mech(mk, rank_name(key), XD)
    dn = get("rk", "computed", "decisive_numbers")
    dnp = path("rk", "computed", "decisive_numbers")

    # ---- rank 1: request-id clock bracket
    br = get("ids", "bracket")
    inp = get("ids", "inputs")
    cen = get("ids", "census")
    for u in BASE:
        if u == "swechat/claude_code" or u == "cc_local":
            corp, sub = ("swechat", "claude_code") if u.startswith("swechat") else ("cc_local", "cc_local")
            b = br[corp]["anthropic_req"][sub]
            r = b["inconsistent_rate_by_session"]
            c = cen[corp]["request_id"][sub]["anthropic_req"]
            p50 = b["U_minus_L_consistent_describe_ms"]["p50"]
            dec = (f"honest inconsistent streams {kn(b['streams_inconsistent'], b['streams_ge2_responses'])} = {fr(r['rate'])} "
                   f"{ci(r['lo'], r['hi'])} at {fi(b['tol_ms'])} ms tolerance; consistent-stream bracket width U-L p50 {fr(p50)} ms")
            src = {"status": "not pre-registered", "deciding_number": [path("ids", "bracket", corp, "anthropic_req", sub)],
                   "n": [path("ids", "bracket", corp, "anthropic_req", sub, "inconsistent_rate_by_session"),
                         path("ids", "census", corp, "request_id", sub, "anthropic_req")]}
            vals = {"bracket": {k: v for k, v in b.items() if not k.endswith("describe_ms")}, "U_minus_L_p50_ms": p50, "census": c}
            if u == "cc_local":
                w = dn["bracket_cc_local"]
                dec += f"; Phase D Wilson {ci(w['lo'], w['hi'])} [D]"
                src["deciding_number"].append(dnp + ".bracket_cc_local")
                vals["phase_d_wilson"] = w
            dec += "; tamper response: none from committed code (the Phase C placebo ran on uncommitted scripts and is withheld)"
            src["deciding_number"].append(dnp + ".placebo_provenance")
            n = (f"{fi(b['streams_ge2_responses'])} streams from {fi(r['n_sessions'])} s; {fi(c['distinct'])} distinct request ids in "
                 f"{fi(c['sessions'])} B s")
            bound = fr(dn["bracket_cc_local"]["hi"]) + " (Wilson)" if u == "cc_local" else fr(r["hi"])
            it = (f"An honest rate is not a detection rate. A committed single-response tamper suite (splice, swap, delete, insert, "
                  f"delay) whose flagged rate clears the honest upper bound {bound} decides it; if no single-response tamper "
                  f"clears it, the line shrinks to back-dating only (Phase D kill rule). The id layout is inferred from data, not documented.")
            add("d1_bracket", u, EXPL, dec, n, src, values=vals, interp=it)
        elif u == "aiv_cu":
            parts, tot = [], {}
            for fam, dd in br["aiv_cu"].items():
                for strat, b in dd.items():
                    parts.append(f"{strat} {kn(b['streams_inconsistent'], b['streams_ge2_responses'])}")
                    tot[f"{fam}/{strat}"] = {"inconsistent": b["streams_inconsistent"], "streams": b["streams_ge2_responses"],
                                             "rate_by_session": b["inconsistent_rate_by_session"]}
            dec = ("message/response ids, not request ids (no request-id field in the B census); inconsistent streams by family: "
                   + ", ".join(parts) + "; weak by construction (the row insert lags the id; OpenAI and Gemini ids have 1 s resolution; IX ids/O3)")
            add("d1_bracket", u, EXPL, dec, f"{fi(inp['aiv_cu']['sessions'])} B s", {"status": "not pre-registered", "deciding_number": path("ids", "bracket", "aiv_cu"),
                                                                                       "n": path("ids", "inputs", "aiv_cu", "sessions"), "context": obs_path("ids_and_clocks_in_ids", "O3")},
                values=tot, interp="A provider clock exists here but brackets only the turn, not the action; the Phase D extension "
                                   "(Gemini HTTP Date and server-timing window) is unmeasured.")
        elif u == "aiv_cc":
            t = sx("ids_and_clocks_in_ids", "O13", r"0 request ids stored")
            add("d1_bracket", u, NOTM, f"not measured: no request-id field in the B census ({fi(inp['aiv_cc']['rows'])} rows); [S] '{t}'",
                "0 request ids", {"status": "not pre-registered", "deciding_number": [path("ids", "census", "aiv_cc"), obs_path("ids_and_clocks_in_ids", "O13")],
                                  "n": path("ids", "inputs", "aiv_cc", "rows")},
                provenance=["committed", "skeptic_text"], values={"skeptic": t},
                interp="Cannot run: the SDK stream stores no provider request ids.")
        else:
            corp, sub = ("whowhen", "whowhen") if u == "whowhen" else ("swechat", u.split("/")[1])
            rows = inp[corp]["rows_by_sub"].get(sub, 0)
            dec = (f"not measured: no request-id field among {fi(rows)} B rows" if rows else "not measured: 0 B rows")
            add("d1_bracket", u, NOTM, dec, "0 request ids", {"status": "not pre-registered", "deciding_number": [path("ids", "census", corp), path("ids", "inputs", corp, "rows_by_sub")],
                                                              "n": path("ids", "inputs", corp, "rows_by_sub")},
                values={"rows": rows}, interp="Cannot run: the record carries no provider request ids." if rows else "No B sessions to check.")

    # ---- rank 2: image-token ledger
    ti = get("tc", "aiv_cu_gemini_text_image")
    tbl = ti["dIMAGE_positive_by_top_tool"]
    ng_n = sum(v["n"] for k, v in tbl.items() if k != "gui")
    ng_k = sum(v["dI_positive"] for k, v in tbl.items() if k != "gui")
    assert (ng_k, ng_n) == (dn["image_nongui"]["k"], dn["image_nongui"]["n"]), "non-GUI sum differs from ranking.json"
    gui = tbl["gui"]
    a5g = {m: get("a5", "part2", f"aiv_cu/gemini-{m}", "gemini_modality") for m in ("pro", "flash")}
    sa = "; ".join(
        f"{m} GUI gaps {kn(a5g[m]['gap_has_gui_result']['share_d_image_gt0']['num'], a5g[m]['gap_has_gui_result']['share_d_image_gt0']['den'])} "
        f"({fi(a5g[m]['gap_has_gui_result']['n_sessions'])} s), no-GUI gaps "
        f"{kn(a5g[m]['gap_has_no_gui_result']['share_d_image_gt0']['num'], a5g[m]['gap_has_no_gui_result']['share_d_image_gt0']['den'])} "
        f"({fi(a5g[m]['gap_has_no_gui_result']['n_sessions'])} s)" for m in ("pro", "flash"))
    for u in BASE:
        if u == "aiv_cu":
            dec = (f"non-GUI windows with an image increment {kn(ng_k, ng_n)}, W {ci(dn['image_nongui']['lo'], dn['image_nongui']['hi'])} [D]; "
                   f"GUI windows with one {kn(gui['dI_positive'], gui['n'])} (misses W {ci(dn['image_gui_miss']['lo'], dn['image_gui_miss']['hi'])} [D]); "
                   f"increment is 0 or one per-model unit in {kn(ti['dIMAGE_in_0_or_unit']['count'], ti['dIMAGE_in_0_or_unit']['n_pairs_model_with_unit'])} pairs; "
                   f"split A replication (committed Phase A): {sa}; no tamper simulation")
            add("d2_image", u, EXPL, dec, f"{fi(ti['pairs_with_text_image_detail'])} Gemini pairs in {fi(ti['sessions'])} B s",
                {"status": "not pre-registered", "deciding_number": [path("tc", "aiv_cu_gemini_text_image", "dIMAGE_positive_by_top_tool"),
                                                                     dnp + ".image_nongui", dnp + ".image_gui_miss",
                                                                     path("tc", "aiv_cu_gemini_text_image", "dIMAGE_in_0_or_unit"),
                                                                     path("a5", "part2", "aiv_cu/gemini-pro", "gemini_modality"),
                                                                     path("a5", "part2", "aiv_cu/gemini-flash", "gemini_modality")],
                 "n": path("tc", "aiv_cu_gemini_text_image", "sessions")},
                provenance=["committed", "phase_d_wilson"],
                values={"nongui": [ng_k, ng_n], "gui": gui, "wilson_nongui": dn["image_nongui"], "wilson_gui_miss": dn["image_gui_miss"],
                        "splitA": {m: {"gui": a5g[m]["gap_has_gui_result"]["share_d_image_gt0"], "nogui": a5g[m]["gap_has_no_gui_result"]["share_d_image_gt0"]} for m in a5g}},
                interp="Cleanest honest separation of the five, and the only one replicated on split A by committed code, but it "
                       "counts images, not their content, and has no tamper simulation yet. A session-level honest flag rate above "
                       "0.05 stops the line (Phase D kill rule).")
        elif u == "aiv_cc":
            a = sx("aiv_accounting", "O11", r"n=\d+ image pairs in \d+ runs")
            b = sx("aiv_accounting", "O11", r"Residual per image: median [\d.]+ \([\d.]+-[\d.]+\)")
            add("d2_image", u, EXPL, f"[S] {b} (token residual per stripped image); single-image detection power unmeasured", f"[S] {a}",
                {"status": "not pre-registered", "deciding_number": obs_path("aiv_accounting", "O11"), "n": obs_path("aiv_accounting", "O11")},
                provenance=["skeptic_text"], values={"skeptic": [a, b]},
                interp="One agent. The per-image residual is stable, but whether one removed image is detectable against the "
                       "honest per-turn residual is unmeasured.")
        else:
            add("d2_image", u, NOTM, "not measured", "—", {"status": "not pre-registered"},
                interp="Not run here; it needs per-modality prompt token counts.")

    # ---- rank 3: git execution window
    mc = get("cw", "q4", "commit_claims", "matched_checks", "commit_date_in_call_window")
    cov = get("cw", "q1", "coverage_by_format")
    for u in BASE:
        if u == "swechat/claude_code":
            o9 = sx("commit_witness", "O9", r"commit_date in \[call ts - 2 s, result ts \+ 2 s\]: \d+ = [\d.]+ \[[\d.,]+\]")
            o9n = sx("commit_witness", "O9", r"\d+ resolved claims \([^)]*\) in \d+ sessions")
            o11 = sx("commit_witness", "O11", r"Population: \d+ of \d+ resolved claims have commit_date earlier than call ts - 2 s, in \d+ sessions")
            o10 = sx("commit_witness", "O10", r"Unmatched \d+ = [\d.]+ \[[\d.,]+\]")
            w = dn["git_skeptic_out"]
            dec = (f"commit_date inside the printing call's window {rate_s(mc)} ({fi(mc['n_sessions'])} s, lens sample); "
                   f"[S] population: {o9}; [S] out of window: {o11}, W {ci(w['lo'], w['hi'])} [D]; [S] honest claims that do not "
                   f"resolve: {o10}; no tamper measurement")
            add("d3_git", u, EXPL, dec, f"{fi(mc['den'])} resolved claims from {fi(mc['n_sessions'])} s (lens); [S] {o9n}",
                {"status": "not pre-registered", "deciding_number": [path("cw", "q4", "commit_claims", "matched_checks", "commit_date_in_call_window"),
                                                                     obs_path("commit_witness", "O9"), obs_path("commit_witness", "O11"),
                                                                     dnp + ".git_skeptic_out", obs_path("commit_witness", "O10")],
                 "n": [path("cw", "q4", "commit_claims", "matched_checks"), obs_path("commit_witness", "O9")]},
                provenance=["committed", "skeptic_text", "phase_d_wilson"], values={"lens": mc, "skeptic": [o9, o9n, o11, o10], "wilson_out": w},
                interp="The out-of-window exceptions were classified after they were seen and there is no held-out replication "
                       "or tamper response. A replay or fabricated-SHA tamper that clears the honest out-of-window and "
                       "non-resolution rates, on a split the classes were not fit on, decides it.")
        elif u in ("swechat/codex", "swechat/opencode", "swechat/gemini", "swechat/copilot"):
            c = cov[u.split("/")[1]]["with_linked_ok_commit"]
            add("d3_git", u, NOTM, f"not measured (witness run on Claude Code transcripts); coverage only: {kn(c['k'], c['n'])} = {fr(c['rate'])} W{ci(c['lo'], c['hi'])} sessions link an ok commit",
                f"{fi(c['n'])} sessions (coverage)", {"status": "not pre-registered", "deciding_number": path("cw", "q1", "coverage_by_format", u.split("/")[1], "with_linked_ok_commit"),
                                                      "n": path("cw", "q1", "coverage_by_format", u.split("/")[1])},
                values=c, interp="Commits exist to test against; the claim parser has not been run on this harness's output format.")
        else:
            add("d3_git", u, NOTM, "not measured", "—", {"status": "not pre-registered"},
                interp="Not run here; it needs a commit history linked to the sessions.")
    a = sx("ext_witness", "O10", r"\d+/\d+ more than 1 s after the save \([^)]*\)")
    b = sx("ext_witness", "O10", r"With fraction: 0/\d+, Wilson upper bound [\d.]+")
    nn = sx("ext_witness", "O10", r"n=\d+, \d+ pages")
    add("d3_git", "collusion-wiki", EXPL, f"fresh-reading leg only: [S] prose epochs {a}; post-hoc fraction-form subset: {b}", f"[S] {nn}",
        {"status": "not pre-registered", "deciding_number": obs_path("ext_witness", "O10"), "n": obs_path("ext_witness", "O10")},
        provenance=["skeptic_text"], values={"skeptic": [a, b, nn]},
        interp="The fraction-form subset was chosen after the outcome; it needs a holdout before it can carry a threshold.")

    # ---- rank 4: harness dual-rendering recount
    for u in BASE:
        if u in ("swechat/claude_code", "cc_local"):
            key = "swechat_sample" if u.startswith("swechat") else "cc_local_sample"
            s = get("a6", "parts", "identities", key, "I4_cc_read_numlines_vs_text")
            c = s["cluster"]
            if u.startswith("swechat"):
                full = sx("raw_census", "A6-O1", r"Full swechat population: \d+/\d+ = [\d.]+, Wilson \[[\d.]+, [\d.]+\], cluster \[[\d.]+, [\d.]+\] over \d+ files")
                sub = sx("raw_census", "A6-O2", r"Full population: \d+/\d+, Wilson \[[\d.]+, [\d.]+\], \d+ files")
                extra = f"; [S] {full}; [S] subagent totalToolUseCount, {sub}"
                ex_src = [obs_path("raw_census", "A6-O1"), obs_path("raw_census", "A6-O2")]
            else:
                full = sx("raw_census", "A6-O1", r"cc_local main sessions, full: \d+/\d+ = [\d.]+, Wilson \[[\d.]+, [\d.]+\]")
                extra, ex_src = f"; [S] {full}", [obs_path("raw_census", "A6-O1")]
            dec = (f"Read numLines equals the visible numbered lines in {kn(s['match'], s['n'])} = {fr(s['rate'])}, cluster {ci(c['lo'], c['hi'])} "
                   f"over {fi(c['n_files'])} files (committed Phase A sample){extra}; no tamper measurement")
            add("d4_dual", u, EXPL, dec, f"{fi(s['n'])} Read results from {fi(c['n_files'])} files (sample)",
                {"status": "not pre-registered", "deciding_number": [path("a6", "parts", "identities", key, "I4_cc_read_numlines_vs_text")] + ex_src,
                 "n": path("a6", "parts", "identities", key, "I4_cc_read_numlines_vs_text")},
                provenance=["committed", "skeptic_text"], values={"sample": s, "skeptic": full},
                interp="One harness writes both renderings, so this catches naive text edits and export faults only. 'No "
                       "unexplained mismatch' is in-sample; a frozen whitelist tested on new data, plus line-add/delete "
                       "tampers, decides it.")
        else:
            add("d4_dual", u, NOTM, "not measured", "—", {"status": "not pre-registered"},
                interp="Not run here; the check reads Claude Code toolUseResult counters.")

    # ---- rank 5: usage-ledger reconciliation
    cls = get("st", "followup", "classes_using_session_logs_metadata")
    tcf = get("tc", "fmt")
    tal = {"swechat/claude_code": "claude", "swechat/codex": "codex", "swechat/opencode": "opencode", "swechat/gemini": "gemini"}
    chain = {"swechat/claude_code": ["swechat:claude_code"], "swechat/codex": ["swechat:codex"], "swechat/opencode": ["swechat:opencode"],
             "swechat/gemini": ["swechat:gemini"], "cc_local": ["cc_local:claude_code"], "aiv_cc": ["aiv_cc:claude_code"],
             "aiv_cu": ["aiv_cu:anthropic", "aiv_cu:gemini"]}
    nf = get("a5", "part2_not_feasible")
    for u in BASE:
        parts, src, vals, prov = [], [], {}, ["committed"]
        nstr = []
        if u in tal:
            x = cls[tal[u]]["none"]
            parts.append(f"Entire usage tally unmatched {kn(x['k'], x['n'])} = {fr(x['rate'])} W{ci(x['lo'], x['hi'])} sessions (full population)")
            src.append(path("st", "followup", "classes_using_session_logs_metadata", tal[u], "none"))
            vals["tally_unmatched"] = x
            nstr.append(f"{fi(x['n'])} tallied sessions")
        for ck in chain.get(u, []):
            cc = tcf[ck]["cache_chain_exact_clean"]
            src.append(path("tc", "fmt", ck, "cache_chain_exact_clean"))
            vals[f"cache_chain:{ck}"] = cc
            if cc is None:
                parts.append(f"cache-append chain not computed ({ck})")
            else:
                parts.append(f"cache-append chain exact in clean pairs {rate_s(cc)} ({ck})")
                nstr.append(f"{fi(cc['den'])} clean pairs from {fi(cc['n_sessions'])} s ({ck})")
        if u == "swechat/codex":
            t = sx("swechat_tables", "T11", r"Codex last_token_usage\.cached_input_tokens is a multiple of 128 in \d+/\d+ calls")
            parts.append(f"[S] post hoc: {t}")
            src.append(obs_path("swechat_tables", "T11"))
            prov.append("skeptic_text")
            vals["skeptic"] = t
        if not parts:
            reason = nf.get(u, {}).get("reason")
            add("d5_ledger", u, NOTM, "not measured" + (f": {reason} (Phase A A5)" if reason else ""), "—",
                {"status": "not pre-registered", **({"deciding_number": path("a5", "part2_not_feasible", u)} if reason else {})},
                interp="Needs a usage record (per-call token counts or a frozen usage tally).")
            continue
        dec = "; ".join(parts) + "; content binding only through token conservation (see the A5 gate rows)"
        if u == "swechat/opencode":
            it = ("The cache-append identity largely fails here, so only the tally leg is usable. It constrains which turns "
                  "exist, not what results said; an editor can redo the tally.")
        else:
            it = ("Constrains which turns exist, not what results said, and an editor can redo the tally; a per-tamper "
                  "detection table against the honest unmatched rate decides it. Heaviest prior-art overlap of the five.")
        if u == "aiv_cc":
            it = "One agent. " + it
        add("d5_ledger", u, EXPL, dec, "; ".join(nstr), {"status": "not pre-registered", "deciding_number": src, "n": src},
            provenance=prov, values=vals, interp=it)


# ================================================================ EXPLORATORY: external-witness checks
def build_x():
    mech("x_git_edit", "External witness: linked commit's patch contains the Edit '+' lines", XW)
    mech("x_git_write", "External witness: Write content present in the committed file", XW)
    mech("x_wiki_epoch", "External witness: prose epochs against the wiki save clock", XW)
    mech("x_urlquery", "External witness: urlquery reports against wiki source mentions", XW)
    mech("x_narr_support", "External witness: narration supported by the session's own log", XW)
    mech("x_narr_contra", "External witness: narration claims an action the log shows failed", XW)
    cwo = get("cw", "q2", "constrained_witness_outcomes")
    sp = path("cw", "q2", "constrained_witness_outcomes")

    def rest(mk, done, interp):
        for u in BASE:
            if u not in done:
                add(mk, u, NOTM, "not measured", "—", {"status": "not pre-registered"}, interp=interp)

    # Edit '+' lines
    e, dcy = cwo["Edit"]["plus"], cwo["Edit"]["decoy_plus"]
    cl = e["contradicted_looking"]
    s1 = sx("commit_witness", "O3", r"Edit, '\+'-line witness \([^)]*\): full \d+ = [\d.]+ \[[\d.,]+\]")
    s2 = sx("commit_witness", "O3", r"none \d+ = [\d.]+ \[[\d.,]+\] \(repo-clustered \[[\d.,]+\]\)")
    s3 = sx("commit_witness", "O3", r"cross-repo decoy: '\+' full \d+/\d+ = [\d.]+ \[[\d.,]+\]")
    add("x_git_edit", "swechat/claude_code", EXPL,
        f"full match {rate_s(e['full'])} against cross-repo decoy {rate_s(dcy['full'])}; honest no-match {rate_s(cl)} (lens); "
        f"[S] population: {s1}; honest no-match {s2}; {s3}",
        f"{fi(e['n_calls'])} Edit calls from {fi(e['n_sessions'])} s (lens sample)",
        {"status": "not pre-registered", "deciding_number": [sp + ".Edit.plus", sp + ".Edit.decoy_plus", obs_path("commit_witness", "O3")],
         "n": sp + ".Edit.plus"},
        provenance=["committed", "skeptic_text"], values={"plus": e, "decoy": dcy, "skeptic": [s1, s2, s3]},
        interp="Strong separation from decoys, but the honest no-match rate is the false-positive base for a per-call flag "
               "and it is high; no tamper response exists. Entire-linked Claude Code sessions only.")
    rest("x_git_edit", {"swechat/claude_code"}, "Not run here; it needs commit-linked sessions and an edit parser for this harness.")
    # Write content
    e, dcy = cwo["Write"]["state"], cwo["Write"]["decoy_state"]
    s1 = sx("commit_witness", "O6", r"Write, committed-content witness \([^)]*\): full \d+ = [\d.]+ \[[\d.,]+\]")
    s2 = sx("commit_witness", "O6", r"Decoy: full \d+/\d+ = [\d.]+ \[[\d.,]+\]")
    add("x_git_write", "swechat/claude_code", EXPL,
        f"full match {rate_s(e['full'])} against decoy {rate_s(dcy['full'])} (lens); [S] population: {s1}; {s2}",
        f"{fi(e['n_calls'])} Write calls from {fi(e['n_sessions'])} s (lens sample)",
        {"status": "not pre-registered", "deciding_number": [sp + ".Write.state", sp + ".Write.decoy_state", obs_path("commit_witness", "O6")],
         "n": sp + ".Write.state"},
        provenance=["committed", "skeptic_text"], values={"state": e, "decoy": dcy, "skeptic": [s1, s2]},
        interp="Only full matches discriminate (decoy partial matches are common); no tamper response exists.")
    rest("x_git_write", {"swechat/claude_code"}, "Not run here; it needs commit-linked sessions and a write parser for this harness.")
    # wiki epochs
    a = sx("ext_witness", "O10", r"\d+/\d+ more than 1 s after the save \([^)]*\)")
    b = sx("ext_witness", "O10", r"With fraction: 0/\d+, Wilson upper bound [\d.]+")
    c = sx("ext_witness", "O10", r"Without fraction: \d+/\d+")
    nn = sx("ext_witness", "O10", r"n=\d+, \d+ pages")
    add("x_wiki_epoch", "collusion-wiki", EXPL, f"[S] prose epochs {a}; post hoc: {b}; {c}", f"[S] {nn}",
        {"status": "not pre-registered", "deciding_number": obs_path("ext_witness", "O10"), "n": obs_path("ext_witness", "O10")},
        provenance=["skeptic_text"], values={"skeptic": [a, b, c, nn]},
        interp="Mostly not later than the save, with exceptions; the clean fraction-form subset was found post hoc and needs a holdout.")
    rest("x_wiki_epoch", set(), "Not run here; it needs an external save clock for the text the agent wrote.")
    # urlquery
    a = sx("ext_witness", "O3", r"With a \+-2h/4h-only null, my excess is [\d.]+ \[[\d.]+, [\d.]+\] page-clustered and \[[\d.]+, [\d.]+\] with \d+ source-day clusters")
    b = sx("ext_witness", "O4", r"Forward before-minus-after 1h: [\d.]+ \[[\d.]+, [\d.]+\]")
    c = sx("ext_witness", "O6", r"local excess [-\d.]+ \[[-\d.]+, [-\d.]+\]")
    nn = sx("ext_witness", "O3", r"\d+ new-mention events on \d+ pages")
    add("x_urlquery", "urlquery", EXPL, f"[S] source-specific co-activity, {a}; null: directionality {b}; null: burst alignment {c}", f"[S] {nn} (against collusion-wiki)",
        {"status": "not pre-registered", "deciding_number": [obs_path("ext_witness", "O3"), obs_path("ext_witness", "O4"), obs_path("ext_witness", "O6")],
         "n": obs_path("ext_witness", "O3")},
        provenance=["skeptic_text"], values={"skeptic": [a, b, c, nn]},
        interp="Day-level agreement on which source was worked, not hour-level precedence; directionality and burst alignment "
               "are nulls, so a missing report is not evidence of a fabricated fetch.")
    rest("x_urlquery", set(), "Not run here; it needs an independent request log for the same agents.")
    # narration support
    a = sx("aiv_narration", "N4", r"path [\d.]+ vs [\d.]+, \+[\d.]+ \(\+[\d.]+ to \+[\d.]+, \d+\)")
    b = sx("aiv_narration", "N4", r"CONS own vs c1: url [-+\d.]+ \([-+\d.]+ to [-+\d.]+\)")
    ns = re.search(r", (\d+)\)$", a).group(1)
    add("x_narr_support", "aiv_cu", EXPL, f"[S] STOP summaries, own log against another agent's same-time narration: {a}; against the same agent's previous narration (c1): {b}, a null",
        f"[S] {ns} sessions (STOP paths)",
        {"status": "not pre-registered", "deciding_number": obs_path("aiv_narration", "N4"), "n": obs_path("aiv_narration", "N4")},
        provenance=["skeptic_text"], values={"skeptic": [a, b]},
        interp="Narration is grounded in its own log far more than in another agent's, but the stricter same-agent control "
               "is null for CONS urls; it supports narration, it does not test results.")
    rest("x_narr_support", {"aiv_cu"}, "Not run here; the check used aiv_cu's end-of-session summaries.")
    # narration contradicted
    a = sx("aiv_narration", "N6", r"contradicted_failed \d+/\d+ \(STOP\)")
    b = sx("aiv_narration", "N6", r"\d+/\d+ claimed, Wilson upper [\d.]+")
    c = sx("aiv_narration", "N6", r"That is \d+ session-actions")
    nc = re.search(r"\d+", c).group(0)
    add("x_narr_contra", "aiv_cu", EXPL, f"[S] null: assertive claims {a}; no power: {c}, {b}", f"[S] {nc} session-actions with all-failed evidence",
        {"status": "not pre-registered", "deciding_number": obs_path("aiv_narration", "N6"), "n": obs_path("aiv_narration", "N6")},
        provenance=["skeptic_text"], values={"skeptic": [a, b, c]},
        interp="A null without power: too few all-failed actions exist to tell whether agents would narrate them as successes.")
    rest("x_narr_contra", {"aiv_cu"}, "Not run here; the check used aiv_cu's end-of-session summaries.")


# ================================================================ summary, md, checks
ORDER = ["p1_latency", "p2_main", "p2_sub", "p3_tail", "p3_retry", "p4_hex", "p4_round", "a5_gate",
         "d1_bracket", "d2_image", "d3_git", "d4_dual", "d5_ledger",
         "x_git_edit", "x_git_write", "x_wiki_epoch", "x_urlquery", "x_narr_support", "x_narr_contra"]
UNTESTABLE = {"KILLED-in-A1", "NOT_TESTABLE", "INSUFFICIENT_N"}


def base_corpus(c):
    return "whowhen" if c.startswith("whowhen/") else c


def summarize():
    pre = [r for r in ROWS if r["group"] == PRE and not r.get("pooled")]
    by_status = {}
    for r in pre:
        k = "DEAD (by prereg)" if r.get("dead_by_prereg") else r["status"]
        by_status[k] = by_status.get(k, 0) + 1
    by_mech = {}
    for r in ROWS:
        m = by_mech.setdefault(r["mechanism_key"], {})
        k = "DEAD (by prereg)" if r.get("dead_by_prereg") else r["status"]
        m[k] = m.get(k, 0) + 1
    alive = [(r["mechanism"], r["corpus"]) for r in pre if r["status"] == "ALIVE"]
    alive_units = sorted({c for _, c in alive})
    no_alive = [c for c in BASE if c not in {base_corpus(c2) for c2 in alive_units}]
    untest = [r for r in pre if r["status"] in UNTESTABLE or r.get("dead_by_prereg")]
    computed = [r for r in pre if not (r["status"] in UNTESTABLE or r.get("dead_by_prereg"))]
    per_corpus = {}
    for c in BASE:
        rs = [r for r in pre if base_corpus(r["corpus"]) == c]
        per_corpus[c] = {"cells": len(rs), "computed": sum(1 for r in rs if r in computed),
                         "ALIVE": sum(1 for r in rs if r["status"] == "ALIVE"), "WEAK": sum(1 for r in rs if r["status"] == "WEAK")}
    no_computed = [c for c, v in per_corpus.items() if v["computed"] == 0]
    expl = [r for r in ROWS if r["group"] in (XD, XW)]
    expl_measured = {m: sorted(r["corpus"] for r in expl if r["mechanism_key"] == m and r["status"] == EXPL)
                     for m in ORDER if GROUP_OF.get(m) in (XD, XW)}
    # corpora whose B rows carry a provider request-id field (ids lens census)
    req_all = []
    for corp, v in get("ids", "census").items():
        for sub in (v.get("request_id") or {}):
            req_all.append(f"{corp}/{sub}" if corp == "swechat" else corp)
    alive_per_mech = {}
    for m, c in alive:
        alive_per_mech.setdefault(m, set()).add(base_corpus(c))
    max_alive = max((len(v) for v in alive_per_mech.values()), default=0)
    # Probe 1 ALIVE units: was floor stability testable? (series below global.min_n.rate_reportable)
    gm = get("pr", "global", "min_n", "rate_reportable")
    p1_alive_floor = {}
    for r in ROWS:
        if r["mechanism_key"] == "p1_latency" and r["status"] == "ALIVE":
            fs = r["values"]["floor_step_change"]
            p1_alive_floor[r["corpus"]] = {"eligible_series": fs["eligible_series"], "eligible_sessions": fs["eligible_sessions"],
                                           "below_min_n": fs["eligible_series"] < gm["den_min"] or fs["eligible_sessions"] < gm["sessions_min"]}
    return {"preregistered_cells": len(pre), "preregistered_cells_by_status": by_status,
            "preregistered_cells_computed": len(computed), "preregistered_cells_not_computable": len(untest),
            "rows_by_mechanism_and_status": by_mech, "alive_cells": [{"mechanism": m, "corpus": c} for m, c in alive],
            "alive_units": alive_units, "max_corpora_alive_for_one_mechanism": max_alive,
            "base_corpora_without_any_alive_cell": no_alive,
            "base_corpora_without_any_computed_cell": no_computed, "per_corpus": per_corpus,
            "probe1_alive_floor_testability": p1_alive_floor,
            "exploratory_measured_corpora": expl_measured, "corpora_with_request_id_field_in_census": req_all,
            "counting_rules": {"preregistered_cells": "rows of group preregistered_phase_b, pooled Probe 4 rows excluded; whowhen "
                                                      "counts once per Probe 1/2/4 mechanism and twice for Probe 3 (AG, HC)",
                               "not_computable": "KILLED-in-A1, NOT_TESTABLE, INSUFFICIENT_N, or DEAD by prereg (not computed)",
                               "request_id": path("ids", "census") + "[*].request_id"}}


ABBR = {"ALIVE": "ALIVE", "WEAK": "WEAK", "DEAD": "DEAD", "INSUFFICIENT_N": "ins-n", "NOT_TESTABLE": "n/t",
        "KILLED-in-A1": "KILLED-A1", "INCONCLUSIVE": "INCONC", EXPL: "EXPL", NOTM: "·",
        "GATE: TIGHT": "TIGHT", "GATE: LOOSE": "LOOSE", "GATE: NOT_TIGHT": "NOT_TIGHT", "GATE: INSUFFICIENT": "INSUFF"}


def cell_code(r):
    if r.get("dead_by_prereg"):
        return "DEAD*"
    return ABBR.get(r["status"], r["status"])


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_md(S):
    L = []
    w = L.append
    w("# Decision table: mechanism × corpus (Phases A–D consolidated)")
    w("")
    w("Built by `python -m analysis.probes.phase_e_a0` (`analysis/probes/phase_e_a0.py`) from committed Phase A–D outputs only. "
      "Every row, with the source path of each cell and the raw values, is in `analysis/out/phase_e/decision_table.json` "
      "(`rows[].sources`, `rows[].values`). The script checks that every number in this file also occurs in that JSON.")
    w("")
    w("- **No corpus contains a known fabricated tool result.** Every cell describes the honest baseline. No cell is a detection rate.")
    w("- **Data.** Phase B verdicts are on split B. The A1 kills and the token-conservation gate are on split A. Phase C numbers "
      "(the EXPLORATORY rows) are in-sample on B, or on the full population, which overlaps the later E and H splits; none of "
      "them is held-out evidence. Phase B is not a blind test either, because the Phase C lenses read split B first.")
    w("- **Status vocabulary.** ALIVE, WEAK, DEAD, INSUFFICIENT_N, INCONCLUSIVE and NOT_TESTABLE are the pre-registered verdicts "
      "(`prereg.json` `global.verdict_vocabulary`, copied into the JSON). Added labels, defined in the JSON `thresholds.added_labels`: "
      "KILLED-in-A1 (Probe 1 units killed by the Phase A timestamp gate); GATE: TIGHT / LOOSE / NOT_TIGHT (Phase A "
      "token-conservation gate, not a Phase B verdict); DEAD (by prereg) (Probe 3 cells fixed as DEAD before Phase B ran); "
      "EXPLORATORY (not pre-registered, measured number shown, no verdict); EXPLORATORY (not measured).")
    w("- **Provenance tags.** [S]: a skeptic number copied verbatim from the committed `analysis/out/phase_c/_index.json`; it was "
      "produced by uncommitted scratch scripts, so rule 1 is fully met only once those are committed. [D]: a Wilson interval that "
      "Phase D's `phase_d_ranking.py` computed with items treated as independent. W: Wilson. Unmarked intervals are "
      "session-clustered bootstraps. The Probe 2 opencode subagent cell also quotes the independent Phase B re-derivation "
      "(`analysis/out/phase_b_verification.json`). The rank-1 back-dating placebo counts come from uncommitted code and are "
      "withheld here, as in FINDINGS.md.")
    w("- **aiv_cc** is one agent: every aiv_cc row is a case study. **cc_local** is private: aggregates only.")
    w("- **The column \"What would change this\" is INTERPRETATION.** It is written by this report, it is not data, and it is not "
      "in the JSON. The three-sentence statement below is interpretation too. Everything else is copied from a committed file.")
    w("")
    # ---------------- statement
    p1 = {r["corpus"]: r for r in ROWS if r["mechanism_key"] == "p1_latency"}
    op, cl, cc = p1["swechat/opencode"]["values"]["deciding"], p1["cc_local"]["values"]["deciding"], p1["swechat/claude_code"]["values"]
    fs_cc = cc["floor_step_change"]
    alive_list = "; ".join(f"{a['mechanism']} in {a['corpus']}" for a in S["alive_cells"])
    assert set(S["probe1_alive_floor_testability"]) == {"swechat/opencode", "cc_local"}, "statement 1 assumes these ALIVE units"
    assert all(v["below_min_n"] for v in S["probe1_alive_floor_testability"].values()), "statement 1 assumes floor untestable"
    assert p1["swechat/claude_code"]["status"] == "WEAK" and fs_cc["label"] == "UNSTABLE", "statement 1 assumes CC WEAK/UNSTABLE"
    w("## Strongest finding (INTERPRETATION, three sentences)")
    w("")
    w(f"1. The strongest pre-registered result is latency physics (Probe 1) on read-type tools: ALIVE in swechat/opencode "
      f"(fp {kn(op['fp_share']['num'], op['fp_share']['den'])}, AUC {fr(op['auc']['auc'])} {ci(op['auc']['lo'], op['auc']['hi'])}) "
      f"and cc_local (fp {kn(cl['fp_share']['num'], cl['fp_share']['den'])}, AUC {fr(cl['auc']['auc'])} {ci(cl['auc']['lo'], cl['auc']['hi'])}), "
      f"but only WEAK in the largest unit, swechat/claude_code, whose latency floor shifts mid-session in "
      f"{kn(fs_cc['steps'], fs_cc['eligible_series'])} series, and neither ALIVE unit had enough series to test floor stability at all.")
    w(f"2. Signals barely transfer across harnesses: {S['preregistered_cells_by_status'].get('ALIVE', 0)} of {S['preregistered_cells']} "
      f"pre-registered mechanism × corpus cells are ALIVE ({alive_list}), no mechanism is ALIVE in more than "
      f"{S['max_corpora_alive_for_one_mechanism']} corpora, and no pre-registered mechanism is ALIVE anywhere in "
      f"{', '.join(S['base_corpora_without_any_alive_cell'])}.")
    w(f"3. The coverage result stands on its own: {S['preregistered_cells_not_computable']} of the {S['preregistered_cells']} "
      f"pre-registered cells could not be computed at all (KILLED-in-A1, NOT_TESTABLE, INSUFFICIENT_N or DEAD by prereg), and the "
      f"top-ranked Phase D witness, the request-id clock bracket, can only run where the record carries provider request ids: "
      f"{' and '.join(S['corpora_with_request_id_field_in_census'])}.")
    w("")
    w("**Where nothing fired, plainly.** No pre-registered mechanism is ALIVE in "
      f"{', '.join(S['base_corpora_without_any_alive_cell'])}. "
      f"No pre-registered cell could even be computed in {', '.join(S['base_corpora_without_any_computed_cell']) or 'none'}. "
      "No EXPLORATORY row has a committed tamper measurement of its own witness (rank 5 only borrows token conservation's "
      "insertion curve), so none of them has shown it detects anything yet.")
    w("")
    # ---------------- compact grid
    w("## Compact grid")
    w("")
    w("Codes: ALIVE, WEAK, DEAD; DEAD* = DEAD by prereg (not computed); ins-n = INSUFFICIENT_N; n/t = NOT_TESTABLE; "
      "KILLED-A1 = killed by the Phase A timestamp gate; INCONC = INCONCLUSIVE; TIGHT / LOOSE / NOT_TIGHT = Phase A gate labels; "
      "EXPL = EXPLORATORY, measured; · = EXPLORATORY, not measured. Probe 3 whowhen cells read AG / HC. Pooled Probe 4 cells are in "
      "the full table only.")
    w("")
    cols = BASE + ["collusion-wiki", "urlquery"]
    w("| Mechanism | " + " | ".join(SHORT[c] for c in cols) + " |")
    w("|---|" + "---|" * len(cols))
    for m in ORDER:
        cells = []
        for c in cols:
            rs = [r for r in ROWS if r["mechanism_key"] == m and base_corpus(r["corpus"]) == c and not r.get("pooled")]
            cells.append(" / ".join(cell_code(r) for r in rs) if rs else "")
        w(f"| {esc(MECH[m])} | " + " | ".join(cells) + " |")
    w("")
    # ---------------- counts
    w("## Counts per mechanism (rows of the full table, pooled rows included)")
    w("")
    keys = ["ALIVE", "WEAK", "DEAD", "DEAD (by prereg)", "INCONCLUSIVE", "INSUFFICIENT_N", "NOT_TESTABLE", "KILLED-in-A1",
            "GATE: TIGHT", "GATE: LOOSE", "GATE: NOT_TIGHT", EXPL, NOTM]
    present = [k for k in keys if any(k in v for v in S["rows_by_mechanism_and_status"].values())]
    w("| Mechanism | " + " | ".join(present) + " |")
    w("|---|" + "---|" * len(present))
    for m in ORDER:
        v = S["rows_by_mechanism_and_status"][m]
        w(f"| {esc(MECH[m])} | " + " | ".join(str(v.get(k, "")) for k in present) + " |")
    w("")
    # ---------------- full tables
    head = "| Mechanism | Corpus | ALIVE / WEAK / DEAD | Deciding number | n | What would change this (INTERPRETATION) |"
    sections = [(PRE, "Pre-registered Phase B mechanisms (verdicts from `analysis/out/probe_1.json` to `probe_4.json`)"),
                (GATE, "Phase A gate, not a Phase B verdict: token conservation (`analysis/out/phase_a.json`)"),
                (XD, "EXPLORATORY: the five ranked Phase D proposals (not pre-registered; no verdict)"),
                (XW, "EXPLORATORY: external-witness checks (not pre-registered; no verdict)")]
    w("## Full table")
    for g, title in sections:
        w("")
        w(f"### {title}")
        w("")
        w(head)
        w("|---|---|---|---|---|---|")
        for m in ORDER:
            if GROUP_OF[m] != g:
                continue
            rs = [r for r in ROWS if r["mechanism_key"] == m]
            if g in (XD, XW):
                rs = sorted(rs, key=lambda r: (r["status"] != EXPL, r["id"]))
            for r in rs:
                st = "DEAD (by prereg)" if r.get("dead_by_prereg") else r["status"]
                shown = [x for x in r["labels"] if not (x == "single-agent case study" and r["corpus"] == "aiv_cc")
                         and not (x == "pooled" and r.get("pooled"))]
                lab = f" ({'; '.join(shown)})" if shown else ""
                w(f"| {esc(r['mechanism'])} | {esc(r['corpus_label'])}{esc(lab)} | **{esc(st)}** | {esc(r['deciding_number'])} | "
                  f"{esc(r['n'])} | {esc(INTERP[r['id']])} |")
    w("")
    w("## Sources")
    w("")
    for p in sorted(SHA):
        w(f"- `{p}` sha256 `{SHA[p][:16]}…`")
    w("")
    return "\n".join(L)


NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def check_numbers(md, js):
    missing = sorted({t for t in NUM.findall(md) if t not in js and t.rstrip(",") not in js})
    return missing


def main():
    load_all()
    build_p1()
    build_p2()
    build_p3()
    build_p4()
    build_a5()
    build_d()
    build_x()
    S = summarize()
    out = {
        "probe": "phase_e_a0_decision_table",
        "script": SCRIPT,
        "description": "One row per mechanism x corpus, consolidated from committed Phase A-D outputs. Measurement only: the "
                       "'What would change this' column and the strongest-finding statement are interpretation and live only "
                       "in analysis/DECISION_TABLE.md (README rule 4).",
        "inputs_sha256": SHA,
        "columns": ["Mechanism", "Corpus", "ALIVE / WEAK / DEAD", "Deciding number", "n", "What would change this"],
        "column_to_field": {"Mechanism": "mechanism", "Corpus": "corpus_label", "ALIVE / WEAK / DEAD": "status",
                            "Deciding number": "deciding_number", "n": "n", "What would change this": "md only (interpretation)"},
        "notes": ["No corpus contains a known fabricated tool result; every row describes the honest baseline, none is a detection rate.",
                  "Phase B verdicts are on split B; A1 kills and the A5 gate on split A; Phase C numbers are in-sample on B or the full "
                  "population (which overlaps the later E and H splits).",
                  "provenance: committed = number from a committed script's output; skeptic_text = verbatim substring of a skeptic "
                  "note in analysis/out/phase_c/_index.json (uncommitted scratch scripts); phase_d_wilson = Wilson interval computed by "
                  "analysis/probes/phase_d_ranking.py with items treated as independent; verification_text = verbatim substring of the "
                  "independent Phase B re-derivation in analysis/out/phase_b_verification.json.",
                  "The rank-1 back-dating placebo counts in ranking.json come from uncommitted code and are not copied into any row.",
                  "aiv_cc rows are a single-agent case study; cc_local is private (aggregates only)."],
        "mechanisms": [{"key": m, "name": MECH[m], "group": GROUP_OF[m]} for m in ORDER],
        "thresholds": thr(),
        "summary": S,
        "rows": ROWS,
    }
    js = json.dumps(out, ensure_ascii=False, indent=1, default=str)
    md = render_md(S)
    miss = check_numbers(md, js)
    if miss:
        print("numbers in the .md that do not occur in the .json:", miss, file=sys.stderr)
        sys.exit(1)
    os.makedirs(os.path.dirname(ap(OUT_JSON)), exist_ok=True)
    with open(ap(OUT_JSON), "w", encoding="utf-8") as f:
        f.write(js + "\n")
    with open(ap(OUT_MD), "w", encoding="utf-8") as f:
        f.write(md)
    print(f"rows {len(ROWS)}; preregistered cells {S['preregistered_cells']} {S['preregistered_cells_by_status']}")
    print(f"wrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
