"""Phase A4: error-signal survival. Which failure signals survive in each corpus, in what form, and how well does
text agree with the harness's own failure flag?

Reads ONLY the Phase A IR caches (analysis/cache/<corpus>_A.parquet) plus analysis/cache/swechat_population.parquet
(session -> SWE-chat transcript format). Writes RAW COUNTS ONLY to analysis/out/phase_a/a4.json; interpretation lives
in analysis/notes/phase_a_a4.md.

Unit: one IR `result` event (one tool result). Resampling unit for every CI: the session (lib/stats.cluster_rate).
Every rate is given with a Wilson interval on pooled counts (as the task asks) AND a session-clustered bootstrap
interval (README rule 5); n results and n sessions are attached to each.

cc_local is private: for it only counts, family/marker names and enum values written by the harness are output.
No text, command, path, tool_raw or template derived from content leaves the cache for cc_local.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_a4
"""
import json
import os
import re
import time
from collections import Counter

import numpy as np
import pandas as pd

from analysis.lib import ir, stats

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.normpath(os.path.join(HERE, ".."))
CACHE = os.path.join(ANALYSIS, "cache")
OUT_DIR = os.path.join(ANALYSIS, "out", "phase_a")
OUT_JSON = os.path.join(OUT_DIR, "a4.json")

CORPORA = ["swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
PRIVATE = {"cc_local"}
COLS = ["session_id", "stratum", "seq", "kind", "tool", "tool_raw", "text", "stderr", "native_error", "exit_code", "extra"]

# ---------------------------------------------------------------------------------------------------------------------
# PRE-REGISTRATION. Written after a schema-only recon (which columns/extra keys are filled, per corpus/format, and the
# first-line SHAPE of a handful of results per native flag in public corpora) and BEFORE any precision/recall, census
# count or aiv_cu co-occurrence was computed. Nothing below was changed after outcomes were seen.
# ---------------------------------------------------------------------------------------------------------------------
TASK_FAMILIES = {  # the census families named in the task, as exact regexes (case-sensitive unless (?i))
    "py_traceback": r"Traceback \(most recent call last\)",
    "command_not_found": r"command not found",
    "permission_denied": r"Permission denied",
    "no_such_file": r"No such file or directory",
    "exit_status_N": r"\bexit status (?!0\b)-?\d+",
    "exited_with_code_N": r"\bexited with code (?!0\b)-?\d+",
    "returned_nonzero_exit_status": r"returned non-zero exit status",
    "error_line": r"(?m)^(?:Error|error):",
    "git_fatal": r"(?m)^fatal:",
    "npm_err": r"npm ERR!",
    "http_4xx_5xx": r"(?m)^(?:< )?HTTP/\d(?:\.\d)? [45]\d\d\b|curl: \(\d+\) The requested URL returned error:? [45]\d\d\b",
}
SUPP_FAMILIES = {  # harness exit/timeout templates seen in the schema recon; used only in predictor C and the census
    "exit_code_header_N": r"(?im)^exit code:? (?!0\b)-?\d+",
    "bash_exited_returncode_N": r"bash has exited with returncode (?!0\b)-?\d+",
    "harness_timeout": r"(?m)^(?:timed out: |sandbox error: command timed out)",
}
FAMILIES = {**TASK_FAMILIES, **SUPP_FAMILIES}
RX = {k: re.compile(v) for k, v in FAMILIES.items()}

PREREG = {
    "written_before_outcomes": True,
    "unit": "IR result event (kind == 'result'); session = resampling unit",
    "tool_class": "shell = (ir tool == 'shell'); other = every other result. aiv_cu section also splits gui.",
    "census_families_task": TASK_FAMILIES,
    "census_families_supplementary": SUPP_FAMILIES,
    "census_family_notes": {
        "exit_N_families": "'exit status N' / 'exited with code N' require N != 0 (N == 0 is a success report, e.g. Codex "
                           "'Process exited with code 0').",
        "case": "case-sensitive as the canonical tool/OS string is written; exit_code_header_N is case-insensitive so it "
                "covers CC 'Exit code N', Codex 'Exit code: N' and Gemini 'Exit Code: N' alike.",
        "supplementary_provenance": "exit_code_header_N: Codex legacy shell output header seen in schema recon (not covered "
                                    "by ir.ERROR_MARKERS); bash_exited_returncode_N and harness_timeout: aiv_cu stderr "
                                    "harness strings and the Codex sandbox timeout, seen in schema recon of 10 rows.",
    },
    "location": "per family and result: text_start = first match begins on the first non-blank line of the result text; "
                "text_middle = first match is later in the text; stderr = match in the stderr column; stderr_only = "
                "match in stderr and not in text.",
    "predictors": {
        "A": "ir.error_marker(text) is not None",
        "B": "A OR any task census family matches text OR stderr",
        "C": "B OR any supplementary family matches text OR stderr (exploratory, declared up front)",
    },
    "references": {
        "native_strict": "results with native_error not null; positive = native_error True",
        "native_null_neg": "all results; positive = native_error True, null counted as negative. Reason: schema recon shows "
                           "Claude Code writes is_error only on Bash results (false) and on failures (true); every CC "
                           "non-Bash result is True or absent, so absent = not flagged by the harness.",
        "exit_nonzero": "results with exit_code not null; positive = exit_code != 0",
    },
    "primary_reference": {
        "claude_code_family (swechat/claude_code, cc_local, aiv_cc)": "native_null_neg",
        "swechat/codex": "native_strict",
        "swechat/opencode, swechat/gemini, swechat/copilot": "native_strict (fill is 100%, so equal to native_null_neg)",
        "whowhen": "native_strict (== exit_nonzero; both are parsed by the loader from the same harness header the marker "
                   "reads, so agreement there is by construction)",
        "aiv_cu": "none (no native failure field)",
    },
    "verdict_rule_for_a_text_proxy": {
        "usable": "point precision >= 0.80 AND point recall >= 0.50 AND cluster-CI lower bounds >= 0.70 / >= 0.40, with "
                  ">= 10 results in each denominator from >= 3 sessions",
        "partial": "not usable, but point precision >= 0.50 AND point recall >= 0.20 with the same minimum n",
        "absent": "otherwise, or no reference flag",
        "reason": "Probe 3 needs the error class to be mostly real (precision) and to capture most of it (recall); "
                  "lower-bound conditions stop small-n flukes from passing; thresholds are judgment calls fixed here.",
    },
    "min_n_for_rate_verdict": {"results": 10, "sessions": 3},
    "aiv_cu_output_looks_successful": "output (text) not null, non-blank after strip, ir.error_marker(text) is None, and no "
                                      "task or supplementary census family matches the text",
    "aiv_cu_stderr_category_order": ["bash_exited_returncode_N", "harness_timeout", "any task census family", "other"],
    "aiv_cu_failure_template_in_stderr": "stderr matches bash_exited_returncode_N or harness_timeout or any task family",
    "templates": "public corpora only: first non-blank line, digits -> '#', path-like tokens -> '<path>', first 32 chars; "
                 "top 10 for B false negatives / false positives against the primary reference",
    "bootstrap": {"n_boot": stats.N_BOOT, "seed": stats.SEED},
    "post_first_run_additions_descriptive_only": {
        "note": "Added after the first run had been inspected. They are descriptive tables only; no predictor, reference, "
                "family regex or threshold above was changed.",
        "exit_header_any_value": "per unit: results whose text carries a harness exit-code header with ANY value (incl. 0), "
                                 "by native flag; shows whether the exit code reaches the model on every result or only on "
                                 "failures. Regexes in EXIT_HEADER_RX.",
        "aiv_cc_village_bash_json": "aiv_cc results of mcp__village__bash whose text parses as a JSON object: key inventory, "
                                    "error/system/output fill, error categories (same order as aiv_cu stderr), by native flag.",
        "aiv_cu_stderr_other_templates": "top 10 first-line templates of aiv_cu stderr in category 'other' (public corpus).",
        "aiv_cu_stderr_fail_template_rate": "aiv_cu by_class[*].stderr_fail_template: rate of the pre-registered failure "
                                            "template in stderr over all results of the class (was only implicit before).",
    },
}
EXIT_HEADER_RX = {  # descriptive only: harness-written exit-code headers, any value
    "cc_exit_code": re.compile(r"^Exit code (-?\d+)"),
    "codex_exit_code_colon": re.compile(r"(?m)^Exit code: (-?\d+)"),
    "gemini_exit_code": re.compile(r"(?m)^Exit Code: (-?\d+)"),
    "codex_process_exited": re.compile(r"Process exited with code (-?\d+)"),
    "whowhen_exitcode": re.compile(r"^exitcode: (-?\d+)"),
    "magentic_unix_exit": re.compile(r"(?:exited with Unix exit code: |The Unix exit code was: )(-?\d+)"),
    "aiv_bash_returncode": re.compile(r"bash has exited with returncode (-?\d+)"),
}
PRIMARY_REF = {"swechat/claude_code": "native_null_neg", "cc_local": "native_null_neg", "aiv_cc": "native_null_neg",
               "swechat/codex": "native_strict", "swechat/opencode": "native_strict", "swechat/gemini": "native_strict",
               "swechat/copilot": "native_strict", "whowhen": "native_strict"}

PATH_RX = re.compile(r"(?:[A-Za-z]:\\|~?/)[^\s'\"<>]+")


# ---------------------------------------------------------------------------------------------------------------------
def load(corpus):
    df = pd.read_parquet(os.path.join(CACHE, f"{corpus}_A.parquet"), columns=COLS, filters=[("kind", "==", "result")])
    df = df.astype(object).where(df.notna(), None)
    if corpus == "swechat":
        pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
        df["unit"] = "swechat/" + df.session_id.map(dict(zip(pop.session_id, pop.format))).astype(str)
    else:
        df["unit"] = corpus
    return df.reset_index(drop=True)


def first_line_end(t):
    off = len(t) - len(t.lstrip())
    e = t.find("\n", off)
    return len(t) if e < 0 else e


def features(df):
    """Per-result failure features. Adds marker, per-family text location (0 none / 1 start / 2 middle) and stderr hit,
    predictors A/B/C, native and exit as plain values."""
    marker, pa, pb, pc = [], [], [], []
    loc = {k: [] for k in FAMILIES}
    se = {k: [] for k in FAMILIES}
    for t, s in zip(df.text.values, df.stderr.values):
        t = t if isinstance(t, str) else ""
        s = s if isinstance(s, str) else ""
        m = ir.error_marker(t) if t else None
        marker.append(m)
        fle = first_line_end(t) if t else 0
        task_hit = supp_hit = False
        for k, rx in RX.items():
            mt = rx.search(t) if t else None
            ms = rx.search(s) if s else None
            loc[k].append(0 if mt is None else (1 if mt.start() <= fle else 2))
            se[k].append(ms is not None)
            if mt is not None or ms is not None:
                if k in TASK_FAMILIES:
                    task_hit = True
                else:
                    supp_hit = True
        a = m is not None
        pa.append(a)
        pb.append(a or task_hit)
        pc.append(a or task_hit or supp_hit)
    df["marker"] = marker
    for k in FAMILIES:
        df[f"loc_{k}"] = loc[k]
        df[f"se_{k}"] = se[k]
    df["pred_A"], df["pred_B"], df["pred_C"] = pa, pb, pc
    df["nat"] = df.native_error.map(lambda x: "null" if x is None else ("true" if bool(x) else "false"))
    exv = [None if (x is None or (isinstance(x, float) and np.isnan(x))) else int(x) for x in df.exit_code.values]
    df["ex_nonnull"] = np.array([x is not None for x in exv], dtype=bool)
    df["ex_zero"] = np.array([x == 0 for x in exv], dtype=bool)
    df["ex_nonzero"] = np.array([x is not None and x != 0 for x in exv], dtype=bool)
    df["tclass"] = np.where(df.tool.values == "shell", "shell", "other")
    df["stderr_nonempty"] = df.stderr.map(lambda s: isinstance(s, str) and len(s) > 0)
    df["stderr_nonnull"] = df.stderr.map(lambda s: s is not None)
    return df


def rate(df, num, den):
    """num/den boolean arrays over df rows. Pooled Wilson + session-clustered bootstrap."""
    num = np.asarray(num, dtype=bool)
    den = np.asarray(den, dtype=bool)
    k, n = int((num & den).sum()), int(den.sum())
    p, lo, hi = stats.wilson(k, n)
    g = pd.DataFrame({"s": df.session_id.values, "num": (num & den).astype(int), "den": den.astype(int)}).groupby("s").sum()
    c = stats.cluster_rate(g.num.values, g.den.values)
    return {"k": k, "n": n, "n_sessions": c["n_sessions"], "rate": p, "wilson_lo": lo, "wilson_hi": hi,
            "cluster_lo": c["lo"], "cluster_hi": c["hi"]}


def verdict_flags(prec, rec):
    mn = PREREG["min_n_for_rate_verdict"]
    enough = all(x["n"] >= mn["results"] and x["n_sessions"] >= mn["sessions"] for x in (prec, rec))
    if not enough or prec["rate"] is None or rec["rate"] is None:
        return {"min_n_met": enough, "meets_usable": False, "meets_partial": False}
    usable = prec["rate"] >= 0.80 and rec["rate"] >= 0.50 and prec["cluster_lo"] >= 0.70 and rec["cluster_lo"] >= 0.40
    partial = prec["rate"] >= 0.50 and rec["rate"] >= 0.20
    return {"min_n_met": True, "meets_usable": bool(usable), "meets_partial": bool(partial and not usable)}


def refs(df):
    nat_true = (df.nat == "true").values
    out = {}
    m = (df.nat != "null").values
    out["native_strict"] = (m, nat_true)
    out["native_null_neg"] = (np.ones(len(df), dtype=bool), nat_true)
    out["exit_nonzero"] = (df.ex_nonnull.values, df.ex_nonzero.values)
    return out


def pr_block(df):
    out = {}
    for rname, (mask, pos) in refs(df).items():
        if mask.sum() == 0:
            out[rname] = {"n_results": 0, "n_sessions": 0}
            continue
        sub_s = df.session_id.values[mask]
        blk = {"n_results": int(mask.sum()), "n_sessions": int(len(set(sub_s))), "positives": int((pos & mask).sum()),
               "prevalence": rate(df, pos, mask), "predictors": {}}
        for p in ("A", "B", "C"):
            pr = df[f"pred_{p}"].values.astype(bool)
            tp = int((pr & pos & mask).sum()); fp = int((pr & ~pos & mask).sum())
            fn = int((~pr & pos & mask).sum()); tn = int((~pr & ~pos & mask).sum())
            prec = rate(df, pos, pr & mask)
            rec = rate(df, pr, pos & mask)
            blk["predictors"][p] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": prec, "recall": rec,
                                    "prereg_rule": verdict_flags(prec, rec)}
        out[rname] = blk
    return out


def census_block(df):
    out = {}
    for k in FAMILIES:
        loc = df[f"loc_{k}"].values
        se = df[f"se_{k}"].values.astype(bool)
        intext = loc > 0
        anyhit = intext | se
        out[k] = {"hit_any": int(anyhit.sum()),
                  "sessions_hit": int(df.session_id[anyhit].nunique()),
                  "text_start": int((loc == 1).sum()), "text_middle": int((loc == 2).sum()),
                  "stderr_any": int(se.sum()), "stderr_only": int((se & ~intext).sum()),
                  "text_and_stderr": int((se & intext).sum()),
                  "hit_by_native": {v: int((anyhit & (df.nat.values == v)).sum()) for v in ("true", "false", "null")},
                  "hit_by_exit": {"nonzero": int((anyhit & df.ex_nonzero.values).sum()),
                                  "zero": int((anyhit & df.ex_zero.values).sum()),
                                  "null": int((anyhit & ~df.ex_nonnull.values).sum())}}
    return out


def template(t):
    t = (t or "").lstrip()
    line = t.split("\n", 1)[0]
    line = PATH_RX.sub("<path>", line)
    line = re.sub(r"\d+", "#", line)
    return line[:32]


AUX_KEYS = ["interrupted", "returnCodeInterpretation", "timedOutAfterMs", "exec_status", "status", "patch_success",
            "error_code", "output_metadata_exit_code", "native_error_from_exit", "harness_note", "exec_end_deferred",
            "unified_exec_running", "output_null", "error_null", "screenshot_is_redacted", "has_redaction_been_overruled",
            "system"]
PRESENCE_ONLY = {"returnCodeInterpretation", "timedOutAfterMs", "system"}  # free-ish text or private: presence only


def aux_block(df, private):
    """Structured fields other than native_error that might carry failure, cross-tabbed with the native flag."""
    out = {}
    exs = [json.loads(e) if isinstance(e, str) else {} for e in df.extra.values]
    for key in AUX_KEYS:
        vals = []
        for e in exs:
            if key not in e:
                vals.append("<absent>")
            elif key in PRESENCE_ONLY or private and key not in ("interrupted",):
                vals.append("<present_null>" if e[key] is None else "<present>")
            else:
                v = e[key]
                if key == "output_metadata_exit_code":
                    v = "nonzero" if v not in (0, None) else str(v)
                vals.append(str(v)[:40])
        c = Counter(vals)
        if set(c) == {"<absent>"}:
            continue
        tab = {}
        for v in c:
            sel = np.array([x == v for x in vals])
            tab[v] = {"n": int(sel.sum()), **{f"native_{nv}": int((sel & (df.nat.values == nv)).sum()) for nv in ("true", "false", "null")},
                      "pred_B": int((sel & df.pred_B.values.astype(bool)).sum()),
                      "stderr_nonempty": int((sel & df.stderr_nonempty.values.astype(bool)).sum())}
        out[key] = tab
    return out


def exit_header_block(df):
    """Descriptive: harness exit-code headers of any value in text (or stderr), by native flag and exit_code."""
    out = {}
    for name, rx in EXIT_HEADER_RX.items():
        vals = []
        for t, s_ in zip(df.text.values, df.stderr.values):
            m = rx.search(t) if isinstance(t, str) and t else None
            if m is None and isinstance(s_, str) and s_:
                m = rx.search(s_)
            vals.append(None if m is None else int(m.group(1)))
        has = np.array([v is not None for v in vals], dtype=bool)
        if not has.any():
            continue
        nz = np.array([v is not None and v != 0 for v in vals], dtype=bool)
        z = has & ~nz
        out[name] = {"n_with_header": int(has.sum()), "sessions": int(df.session_id[has].nunique()),
                     "header_rate": rate(df, has, np.ones(len(df), dtype=bool)),
                     **{f"header_{lab}|native_{nv}": int((arr & (df.nat.values == nv)).sum())
                        for lab, arr in (("zero", z), ("nonzero", nz)) for nv in ("true", "false", "null")},
                     **{f"header_{lab}|exit_{el}": int((arr & ea).sum())
                        for lab, arr in (("zero", z), ("nonzero", nz))
                        for el, ea in (("zero", df.ex_zero.values), ("nonzero", df.ex_nonzero.values), ("null", ~df.ex_nonnull.values))}}
    return out


def aiv_cc_village_bash(df):
    """aiv_cc mcp__village__bash results whose text is a JSON object (the AI Village turn record shown to the agent)."""
    g = df[df.tool_raw == "mcp__village__bash"]
    keys, rows = Counter(), []
    for t, nat, sid in zip(g.text.values, g.nat.values, g.session_id.values):
        try:
            o = json.loads(t) if isinstance(t, str) else None
        except ValueError:
            o = None
        if not isinstance(o, dict):
            rows.append({"json": False, "nat": nat, "sid": sid})
            continue
        keys[tuple(sorted(o.keys()))] += 1
        err = o.get("error")
        err = err if isinstance(err, str) else ("" if err is None else json.dumps(err))
        out_ = o.get("output")
        cat = "empty"
        if err:
            if RX["bash_exited_returncode_N"].search(err):
                cat = "bash_exited_returncode_N"
            elif RX["harness_timeout"].search(err):
                cat = "harness_timeout"
            elif any(RX[k].search(err) for k in TASK_FAMILIES):
                cat = "task_census_family"
            else:
                cat = "other"
        out_txt = out_ if isinstance(out_, str) else ("" if out_ is None else json.dumps(out_))
        out_hit = bool(out_txt) and (ir.error_marker(out_txt) is not None or any(RX[k].search(out_txt) for k in FAMILIES))
        sysv = o.get("system")
        rows.append({"json": True, "nat": nat, "sid": sid, "error_nonempty": bool(err), "error_cat": cat,
                     "system_nonnull": sysv is not None, "output_null": out_ is None,
                     "output_blank": not out_txt.strip(), "output_census_hit": out_hit,
                     "system_tpl": template(sysv) if isinstance(sysv, str) else (None if sysv is None else "<non-string>")})
    r = pd.DataFrame(rows)
    if len(r) == 0:
        return {"n_results": 0}
    jr = r[r.json]
    res = {"n_results": int(len(g)), "n_sessions": int(g.session_id.nunique()), "json_object": int(r.json.sum()),
           "non_json_by_native": dict(Counter(r[~r.json].nat)), "json_by_native": dict(Counter(jr.nat)),
           "json_key_sets": {"|".join(k): int(v) for k, v in keys.most_common(10)}}
    if len(jr):
        jd = jr.rename(columns={"sid": "session_id"}).reset_index(drop=True)
        for c in ("error_nonempty", "system_nonnull", "output_null", "output_blank", "output_census_hit"):
            jd[c] = jd[c].astype(bool)
        one = np.ones(len(jd), dtype=bool)
        res.update({
            "error_nonempty": rate(jd, jd.error_nonempty.values, one),
            "system_nonnull": rate(jd, jd.system_nonnull.values, one),
            "output_null": int(jd.output_null.sum()), "output_blank": int(jd.output_blank.sum()),
            "error_category": dict(Counter(jd.error_cat)),
            "error_category_given_output_blank": dict(Counter(jd.error_cat[jd.output_blank])),
            "error_nonempty_given_output_blank": rate(jd, jd.error_nonempty.values, jd.output_blank.values),
            "error_nonempty_given_output_not_blank": rate(jd, jd.error_nonempty.values, ~jd.output_blank.values),
            "output_census_hit": int(jd.output_census_hit.sum()),
            "system_nonnull_x_error_nonempty": {f"system_{a}|error_{b}": int(((jd.system_nonnull.values == a) & (jd.error_nonempty.values == b)).sum())
                                                for a in (True, False) for b in (True, False)},
            "system_templates_top10": Counter(t for t in jd.system_tpl if isinstance(t, str)).most_common(10),
        })
    return res


def unit_block(df, unit, private):
    b = {"n_results": int(len(df)), "n_sessions": int(df.session_id.nunique())}
    if len(df) == 0:
        return b
    b["native_error"] = {v: int((df.nat == v).sum()) for v in ("true", "false", "null")}
    b["native_fill"] = rate(df, df.nat.values != "null", np.ones(len(df), dtype=bool))
    b["native_true_rate"] = rate(df, df.nat.values == "true", np.ones(len(df), dtype=bool))
    exn = df.ex_nonnull.values
    b["exit_code"] = {"nonnull": int(exn.sum()), "zero": int(df.ex_zero.sum()), "nonzero": int(df.ex_nonzero.sum())}
    b["exit_code_fill"] = rate(df, exn, np.ones(len(df), dtype=bool))
    exs = {"zero": df.ex_zero.values, "nonzero": df.ex_nonzero.values, "null": ~exn}
    b["exit_vs_native"] = {f"exit_{e}|native_{n}": int((exs[e] & (df.nat.values == n)).sum())
                           for e in ("zero", "nonzero", "null") for n in ("true", "false", "null")}
    b["stderr"] = {"nonnull": int(df.stderr_nonnull.sum()), "nonempty": int(df.stderr_nonempty.sum()),
                   "nonempty_by_native": {v: int((df.stderr_nonempty.values & (df.nat.values == v)).sum()) for v in ("true", "false", "null")}}
    mk = df.marker.fillna("none")
    b["error_marker"] = dict(Counter(mk))
    b["error_marker_by_native"] = {v: dict(Counter(mk[df.nat == v])) for v in ("true", "false", "null")}
    b["text_null_or_blank"] = {v: int(((df.nat.values == v) & df.text.map(lambda t: not isinstance(t, str) or not t.strip()).values).sum())
                               for v in ("true", "false", "null")}
    b["census"] = census_block(df)
    b["exit_header_any_value"] = exit_header_block(df)
    b["pr"] = pr_block(df)
    b["aux_fields"] = aux_block(df, private)
    ref = PRIMARY_REF.get(unit)
    if not private and ref and ref in b["pr"] and b["pr"][ref].get("n_results"):
        mask, pos = refs(df)[ref]
        pr = df.pred_B.values.astype(bool)
        b["templates_B_vs_" + ref] = {
            "false_negatives_top10": Counter(template(t) for t in df.text.values[pos & ~pr & mask]).most_common(10),
            "false_positives_top10": Counter(template(t) for t in df.text.values[pr & ~pos & mask]).most_common(10),
            "fp_family_hits": {k: int(((df[f"loc_{k}"].values > 0) | df[f"se_{k}"].values.astype(bool))[pr & ~pos & mask].sum()) for k in FAMILIES},
            "fp_marker": dict(Counter(df.marker.fillna("none").values[pr & ~pos & mask])),
        }
    return b


def stratum_table(df):
    out = {}
    for s, g in df.groupby("stratum"):
        out[str(s)] = {"n_results": int(len(g)), "n_sessions": int(g.session_id.nunique()),
                       "native": {v: int((g.nat == v).sum()) for v in ("true", "false", "null")},
                       "exit_nonnull": int(g.ex_nonnull.sum()), "pred_A": int(g.pred_A.sum()), "pred_B": int(g.pred_B.sum()),
                       "pred_C": int(g.pred_C.sum()), "stderr_nonempty": int(g.stderr_nonempty.sum())}
    return out


def aiv_cu_section(df):
    """No native failure field. Measure stderr non-empty on outputs that look successful; test candidate flags."""
    exs = [json.loads(e) if isinstance(e, str) else {} for e in df.extra.values]
    df = df.copy()
    df["cls3"] = np.where(df.tool.values == "shell", "shell", np.where(df.tool.values == "gui", "gui", "other"))
    df["output_null"] = [bool(e.get("output_null")) for e in exs]
    df["error_null"] = [bool(e.get("error_null")) for e in exs]
    df["redacted"] = [bool(e.get("screenshot_is_redacted")) for e in exs]
    df["overruled"] = [str(e.get("has_redaction_been_overruled")) for e in exs]
    df["system_present"] = ["system" in e for e in exs]
    text_task_or_supp = np.zeros(len(df), dtype=bool)
    for k in FAMILIES:
        text_task_or_supp |= df[f"loc_{k}"].values > 0
    blank = df.text.map(lambda t: not isinstance(t, str) or not t.strip()).values
    df["looks_ok"] = (~blank) & df.marker.isna().values & ~text_task_or_supp
    se_task = np.zeros(len(df), dtype=bool)
    for k in TASK_FAMILIES:
        se_task |= df[f"se_{k}"].values.astype(bool)
    cat = np.where(df["se_bash_exited_returncode_N"].values, "bash_exited_returncode_N",
                   np.where(df["se_harness_timeout"].values, "harness_timeout",
                            np.where(se_task, "task_census_family", np.where(df.stderr_nonempty.values, "other", "empty"))))
    df["stderr_cat"] = cat
    df["stderr_fail_tpl"] = np.isin(cat, ["bash_exited_returncode_N", "harness_timeout", "task_census_family"])
    out = {"n_results": int(len(df)), "n_sessions": int(df.session_id.nunique()),
           "system_key_present_on_results": int(df.system_present.sum()),
           "consistency_output_null_vs_text_null": int((df.output_null.values == df.text.isna().values).sum()),
           "consistency_error_null_vs_stderr_null": int((df.error_null.values == df.stderr.isna().values).sum()),
           "by_class": {}}
    for cls in ("all", "shell", "gui", "other"):
        g = df if cls == "all" else df[df.cls3 == cls]
        if len(g) == 0:
            continue
        one = np.ones(len(g), dtype=bool)
        blk = {"n_results": int(len(g)), "n_sessions": int(g.session_id.nunique()),
               "stderr_nonempty": rate(g, g.stderr_nonempty.values, one),
               "output_null": rate(g, g.output_null.values, one),
               "looks_ok": rate(g, g.looks_ok.values, one),
               "stderr_fail_template": rate(g, g.stderr_fail_tpl.values, one),
               "stderr_nonempty_given_looks_ok": rate(g, g.stderr_nonempty.values, g.looks_ok.values),
               "stderr_fail_template_given_looks_ok": rate(g, g.stderr_fail_tpl.values, g.looks_ok.values),
               "stderr_category": dict(Counter(g.stderr_cat)),
               "stderr_category_given_looks_ok": dict(Counter(g.stderr_cat[g.looks_ok])),
               "stderr_category_given_output_null": dict(Counter(g.stderr_cat[g.output_null])),
               "crosstab_output_null_x_stderr_nonempty": {f"output_null_{a}|stderr_nonempty_{b}": int(((g.output_null.values == a) & (g.stderr_nonempty.values == b)).sum())
                                                           for a in (True, False) for b in (True, False)},
               "candidate_flags": {}}
        for flag, vec in (("output_null", g.output_null.values), ("screenshot_is_redacted", g.redacted.values),
                          ("has_redaction_been_overruled_true", (g.overruled.values == "True")),
                          ("system_key_present", g.system_present.values), ("pred_B_text_or_stderr", g.pred_B.values.astype(bool)),
                          ("pred_C_text_or_stderr", g.pred_C.values.astype(bool))):
            vec = np.asarray(vec, dtype=bool)
            blk["candidate_flags"][flag] = {
                "n_flag_true": int(vec.sum()),
                "stderr_nonempty_given_flag": rate(g, g.stderr_nonempty.values, vec),
                "stderr_nonempty_given_not_flag": rate(g, g.stderr_nonempty.values, ~vec),
                "stderr_fail_template_given_flag": rate(g, g.stderr_fail_tpl.values, vec),
                "stderr_fail_template_given_not_flag": rate(g, g.stderr_fail_tpl.values, ~vec),
            }
        out["by_class"][cls] = blk
    st = {}
    for s, g in df[df.cls3 == "shell"].groupby("stratum"):
        one = np.ones(len(g), dtype=bool)
        st[str(s)] = {"n_results": int(len(g)), "n_sessions": int(g.session_id.nunique()),
                      "output_null": int(g.output_null.sum()), "stderr_nonempty": int(g.stderr_nonempty.sum()),
                      "looks_ok": int(g.looks_ok.sum()), "looks_ok_and_stderr_nonempty": int((g.looks_ok & g.stderr_nonempty).sum()),
                      "stderr_category": dict(Counter(g.stderr_cat)),
                      "stderr_nonempty_rate": rate(g, g.stderr_nonempty.values, one)}
    out["shell_by_stratum"] = st
    oth = df.stderr_cat.values == "other"
    out["stderr_other_templates_top10"] = Counter(template(x) for x in df.stderr.values[oth]).most_common(10)
    out["stderr_other_given_looks_ok_templates_top10"] = Counter(template(x) for x in df.stderr.values[oth & df.looks_ok.values]).most_common(10)
    return out


def shell_tool_raw(df, private):
    if private:
        return None
    g = df[df.tclass == "shell"]
    return {str(t): {v: int((h.nat == v).sum()) for v in ("true", "false", "null")} | {"n": int(len(h))}
            for t, h in g.groupby("tool_raw")}


def main():
    t0 = time.time()
    res = {"script": "analysis/probes/phase_a_a4.py", "question": "A4 error-signal survival",
           "inputs": [f"analysis/cache/{c}_A.parquet" for c in CORPORA] + ["analysis/cache/swechat_population.parquet"],
           "prereg": PREREG, "units": {}, "by_stratum": {}, "shell_tool_raw_x_native": {}}
    for c in CORPORA:
        df = features(load(c))
        priv = c in PRIVATE
        res["by_stratum"][c] = stratum_table(df) if not priv else {"n_strata": int(df.stratum.nunique()),
                                                                     **{str(s): v for s, v in stratum_table(df).items()}}
        for unit, g in df.groupby("unit"):
            res["units"][unit] = {cls: unit_block(g if cls == "all" else g[g.tclass == cls], unit, priv)
                                  for cls in ("all", "shell", "other")}
            res["shell_tool_raw_x_native"][unit] = shell_tool_raw(g, priv)
        if c == "aiv_cu":
            res["aiv_cu"] = aiv_cu_section(df)
        if c == "aiv_cc":
            res["aiv_cc_village_bash_json"] = aiv_cc_village_bash(df)
        del df
    if "swechat" in CORPORA:  # formats with no results in A (no tool results in the source) still get a row
        pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
        sa = pd.read_parquet(os.path.join(CACHE, "swechat_A.parquet"), columns=["session_id", "kind"])
        fm = dict(zip(pop.session_id, pop.format))
        sa["fmt"] = sa.session_id.map(fm)
        res["swechat_A_sessions_by_format"] = {str(k): int(v) for k, v in sa.groupby("fmt").session_id.nunique().items()}
        res["swechat_A_results_by_format"] = {str(k): int(v) for k, v in sa[sa.kind == "result"].groupby("fmt").size().items()}
    res["runtime_s"] = round(time.time() - t0, 1)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False, allow_nan=False,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", OUT_JSON, "in", res["runtime_s"], "s")


if __name__ == "__main__":
    main()
