"""Phase A3: truncation of tool-result text.

Question: per corpus and per tool class (shell vs other), how long are result texts (chars, UTF-8 bytes; UTF-16 code
units as a third unit because the Node/TS harnesses count in them), how many sit at the 10 KB boundary, how many carry
a harness truncation marker (per marker, per truncation type), whether truncated results keep their failure marker /
exit line, and which exact lengths spike (caps we do not know about).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_a3
Reads ONLY analysis/cache/<corpus>_A.parquet (+ swechat_population.parquet for the per-session format). Never *_B.
Writes RAW COUNTS ONLY to analysis/out/phase_a/a3.json. Interpretation: analysis/notes/phase_a_a3.md.
cc_local is private: only counts, lengths and rates leave this script for it (no text, no tool names outside BUILTIN).

All rules, windows and the marker catalogue are fixed in RULES / MARKERS below and copied into the output.
"""
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import error_marker

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "analysis" / "cache"
OUT = ROOT / "analysis" / "out" / "phase_a" / "a3.json"
CORPORA = ["swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
PRIVATE = {"cc_local"}

WIN = (9728, 10256)            # task: "at or near the 10 KB boundary"
WIN_CMP = (9199, 9727)         # same width (529 values), immediately below WIN; context only, not a test
SWE_CAP_LEN, SWE_CAP_SUFFIX = 10256, "\n... [truncated]"
SPIKE_MIN_LEN, SPIKE_TOP = 1000, 10
CAP_RULE = {"min_n": 5, "min_sessions": 2, "min_prefix_diversity": 0.5, "min_excess_over_neighbourhood": 5.0,
            "neighbourhood_halfwidth": 50, "prefix_chars": 64}

# Marker catalogue. type: what the harness did to the output.
#   middle_elision  head and tail kept, middle replaced by a count marker
#   tail_cut        head kept, tail dropped, count marker at the end
#   spill           output moved to a file; the model sees a pointer + preview
#   list_cap        result list cut at N entries (glob/grep)
#   line_cap        single over-long lines replaced (ripgrep --max-columns)
#   read_window     file reader returned a window of the file with a continue-at hint (pagination, not loss)
#   read_refusal    reader refused an over-limit file (no content returned)
#   history_mask    harness replaced an older tool output in the history with a masked preview
#   dataset_cap     cap applied by the dataset publisher, not the harness
MARKERS = [
    # Claude Code (swechat claude_code, cc_local, aiv_cc)
    ("cc_chars_truncated", "middle_elision", r"\.\.\. \[\d+ characters truncated\] \.\.\."),
    ("cc_lines_truncated", "tail_cut", r"\.\.\. \[\d+ lines truncated\] \.\.\."),
    ("cc_persisted_output", "spill", r"^<persisted-output>"),
    ("cc_output_too_large", "spill", r"Output too large \([\d.]+\s?[KMG]?B\)\. Full output saved to:"),
    ("cc_results_truncated", "list_cap", r"\(Results are truncated\. Consider using a more specific path or pattern\.\)"),
    ("cc_rg_omitted_long_line", "line_cap", r"\[Omitted long (?:matching )?line"),
    ("cc_read_token_limit", "read_refusal", r"File content \(\d+ tokens\) exceeds maximum allowed tokens"),
    # Codex
    ("codex_tokens_truncated", "middle_elision", r"…\d+ tokens truncated…"),
    ("codex_chars_truncated", "middle_elision", r"…\d+ chars truncated…"),
    ("codex_total_output_lines", "middle_elision", r"(?m)^Total output lines: \d+"),
    ("codex_omitted_lines", "middle_elision", r"\[\.\.\. omitted \d+ of \d+ lines \.\.\.\]"),
    # Gemini CLI
    ("gem_tool_output_masked", "history_mask", r"^<tool_output_masked>"),
    ("gem_output_too_large_saved", "spill", r"Output too large\. Full output available at:"),
    ("gem_output_too_large_showing", "middle_elision", r"Output too large\. Showing first [\d,]+ and last [\d,]+ characters"),
    ("gem_truncated_tag", "middle_elision", r"\.\.\. \[TRUNCATED\] \.\.\."),
    ("gem_lines_omitted", "middle_elision", r"\.\.\. \[[\d,]+ lines omitted\] \.\.\."),
    ("gem_chars_omitted", "middle_elision", r"\.\.\. \[[\d,]+ characters omitted\] \.\.\."),
    ("gem_read_truncated", "read_window", r"IMPORTANT: The file content has been truncated\."),
    # OpenCode
    ("oc_bytes_truncated", "spill", r"\.\.\.\d+ bytes truncated\.\.\."),
    ("oc_output_saved", "spill", r"The tool call succeeded but the output was truncated\. Full output saved to:"),
    ("oc_bash_metadata_truncated", "tail_cut", r"<bash_metadata>[^<]*truncat"),
    ("oc_grep_results_truncated", "list_cap", r"\(Results truncated: showing \d+ of \d+ matches"),
    ("oc_glob_results_truncated", "list_cap", r"\(Results are truncated: showing first \d+ results"),
    ("oc_read_capped", "read_window", r"\(Output capped at \d+ KB\."),
    ("oc_read_showing_lines", "read_window", r"\(Showing lines \d+-\d+ of \d+\. Use offset=\d+ to continue\.\)"),
    # Copilot CLI
    ("cop_output_too_large_saved", "spill", r"Output too large to read at once \([\d.]+ ?KB\)\. Saved to:"),
    ("cop_output_truncated_view", "read_window", r"\[Output truncated\. Use view_range="),
    ("cop_file_too_large", "read_refusal", r"File too large to read at once"),
    # generic forms named in the task (any scaffold)
    ("generic_dots_output_truncated", "tail_cut", r"\.\.\.\[output truncated\]"),
]
MARKER_TYPE = {m: t for m, t, _ in MARKERS}
LOSS_TYPES = ["middle_elision", "tail_cut", "spill", "list_cap", "line_cap", "history_mask", "dataset_cap"]
ALL_TYPES = LOSS_TYPES + ["read_window", "read_refusal"]

# Scaffold-specific "exit line" in result text (None = the scaffold writes no exit line into the text).
EXIT_LINE = {
    "claude_code": (r"^Exit code \d+", "match"),
    "codex": (r"(?m)^(?:Exit code: \d+|Process exited with code \d+)", "head600"),
    "gemini": (r"(?m)^Exit Code: \d+", "search"),
    "whowhen": (r"^exitcode: \d+|exited with Unix exit code: \d+|The Unix exit code was: \d+", "search"),
}
SCAFFOLD_EXIT = {"claude_code": "claude_code", "cc_local": "claude_code", "aiv_cc": "claude_code", "codex": "codex",
                 "gemini": "gemini", "whowhen": "whowhen"}
FLAG_SOURCE = {"claude_code": "toolUseResult.truncated (Claude Code Glob/Grep)", "cc_local": "toolUseResult.truncated",
               "aiv_cc": "tool_use_result.truncated", "opencode": "state.metadata.truncated"}
BUILTIN = {"shell", "read", "write", "edit", "glob", "grep", "ls", "subagent", "webfetch", "websearch", "todo", "gui",
           "notebookedit", "taskoutput", "toolsearch", "skill", "exitplanmode", "askuserquestion", "killshell", "bashoutput",
           "taskcreate", "taskupdate", "tasklist", "taskget", "taskstop", "workflow", "enterplanmode"}

RULES = {
    "data": "Phase A split only: analysis/cache/<corpus>_A.parquet; *_B.parquet never opened. Unit = one IR event with "
            "kind == 'result'. text None counts as ''.",
    "lengths": "chars = Python len(text) (Unicode code points); bytes = len(text.encode('utf-8', 'surrogatepass')); "
               "utf16 = UTF-16 code units (len(text.encode('utf-16-le', 'surrogatepass')) // 2), the unit JavaScript "
               "String.length counts (Claude Code, OpenCode, Gemini CLI are Node/TS harnesses).",
    "tool_class": "shell if IR tool == 'shell' (ir.normalize_tool), else other. Who&When code_exec and computerterminal "
                  "are 'other' under this rule (reported per tool for whowhen).",
    "group": "swechat: per-session format from swechat_population.parquet; other corpora: one group named after the corpus. "
             "'_all' pools the groups of a corpus.",
    "window_10kb": f"length in [{WIN[0]}, {WIN[1]}] inclusive (task). Comparison window [{WIN_CMP[0]}, {WIN_CMP[1]}] "
                   "has the same width and sits immediately below; it is context, not a test. Computed in chars, bytes, utf16.",
    "swechat_dataset_cap": f"exact: text ends with {SWE_CAP_SUFFIX!r} and len(text) == {SWE_CAP_LEN}; loose: text ends "
                           "with '... [truncated]' at any length. Applied to every corpus.",
    "markers": "regex catalogue MARKERS (name, type, pattern), re.search on result text. Built before computing this "
               "file's counts from: the task's list, and exploration of Phase A result text of swechat / aiv_cc / aiv_cu "
               "/ whowhen (contexts of 'truncat', 'too large', 'omitted', 'exceeds'). cc_local text was never read; the "
               "same patterns were applied to it blind. A result can carry several markers; type counts are unions.",
    "loss_types": LOSS_TYPES,
    "any_truncation": "result carries >= 1 marker whose type is in loss_types (read_window and read_refusal excluded: "
                      "pagination / refusal, nothing silently cut).",
    "residual_truncat_word": "results whose text matches (?i)truncat but no catalogue marker: content that mentions "
                             "truncation (code, prose) plus any harness marker the catalogue misses.",
    "retention": "for results carrying a marker / type: counts of native_error (true/false/null), exit_code non-null, "
                 "ir.error_marker(text) by name, and the scaffold exit line (EXIT_LINE) present. Baseline = results of "
                 "the same cell with no loss-type marker. Key ratios with session-clustered CI: error_marker non-null | "
                 "native_error true; exit line present | shell.",
    "exit_line": {k: v[0] + " (" + v[1] + ")" for k, v in EXIT_LINE.items()},
    "exit_line_none": "OpenCode, Copilot, aiv_cu: no exit line is written into the result text (OpenCode's exit status is "
                      "structured: extra.exit -> exit_code column); exit_line is reported null for them.",
    "rates": "stats.cluster_rate (num/den per session, session-clustered bootstrap, 1000 draws, seed stats.SEED) and, for "
             "the share of sessions with >= 1 hit, stats.wilson(k_sessions, n_sessions). The bootstrap CI of a 0 count "
             "is [0, 0]; use the session Wilson upper bound for zeros.",
    "spikes": f"per corpus (and per swechat format): the {SPIKE_TOP} most frequent exact lengths with length > "
              f"{SPIKE_MIN_LEN}, in chars and in bytes, ties broken by smaller length. Per spike: n, sessions, distinct "
              f"texts, distinct {CAP_RULE['prefix_chars']}-char prefixes and suffixes (md5, never written out), mean count "
              f"per exact length in [L-{CAP_RULE['neighbourhood_halfwidth']}, L+{CAP_RULE['neighbourhood_halfwidth']}] "
              "excluding L, results with any catalogue marker, tool-class counts.",
    "cap_candidate_rule": "a spike is flagged cap_candidate when n >= 5 AND sessions >= 2 AND distinct_prefix64 / n >= 0.5 "
                          "AND n >= 5 x neighbourhood mean count (or the neighbourhood is empty). Reason: a cap truncates "
                          "unrelated outputs to one length, so it shows prefix diversity across sessions and an excess "
                          "over adjacent lengths; repeated identical content (distinct texts ~ 1) and fixed-format "
                          "outputs (shared prefix) fail it. Fixed after seeing an exploratory top-12 table of (n, sessions, "
                          "distinct texts) per corpus, before prefix diversity or neighbourhood excess were computed.",
}


def h(s):
    return hashlib.md5(s.encode("utf-8", "surrogatepass")).hexdigest()


def load(corpus):
    cols = ["session_id", "stratum", "kind", "tool", "tool_raw", "text", "native_error", "exit_code", "extra"]
    df = pd.read_parquet(CACHE / f"{corpus}_A.parquet", columns=cols)
    extra_sys = None
    if corpus == "cc_local":  # read_truncation_notice attachments (system/meta events), counts only
        s = df[df.kind.isin(["system", "meta"]) & df.extra.notna()]
        at = pd.Series([json.loads(e).get("attachment_type") if isinstance(e, str) else None for e in s.extra.tolist()], index=s.index)
        sub = s[at == "read_truncation_notice"]
        extra_sys = {"read_truncation_notice_attachments": {"n_events": int(len(sub)), "n_sessions": int(sub.session_id.nunique()),
                                                            "by_kind": {str(k): int(v) for k, v in sub.kind.value_counts().items()},
                                                            "n_sessions_corpus_A": int(df.session_id.nunique())}}
    r = df[df.kind == "result"].copy()
    n_sessions_all = int(df.session_id.nunique())
    del df
    if corpus == "swechat":
        pop = pd.read_parquet(CACHE / "swechat_population.parquet", columns=["session_id", "format"])
        r = r.merge(pop, on="session_id", how="left")
        r["group"] = r["format"].astype(str)
    else:
        r["group"] = corpus
    r["t"] = r["text"].fillna("").astype(str)
    return r, n_sessions_all, extra_sys


def annotate(r, corpus):
    t = r["t"]
    r["L"] = t.str.len().astype(int)
    r["B"] = t.map(lambda s: len(s.encode("utf-8", "surrogatepass")))
    r["U"] = t.map(lambda s: len(s.encode("utf-16-le", "surrogatepass")) // 2)
    r["cls"] = np.where(r["tool"].fillna("").astype(str) == "shell", "shell", "other")
    for name, _, pat in MARKERS:
        r["m_" + name] = t.str.contains(pat, regex=True)
    r["m_swe_cap_exact"] = t.str.endswith(SWE_CAP_SUFFIX) & (r["L"] == SWE_CAP_LEN)
    r["m_swe_cap_loose"] = t.str.endswith("... [truncated]")
    for ty in ALL_TYPES:
        names = [m for m, tt, _ in MARKERS if tt == ty]
        col = np.zeros(len(r), dtype=bool)
        for m in names:
            col |= r["m_" + m].to_numpy()
        if ty == "dataset_cap":
            col |= r["m_swe_cap_exact"].to_numpy()
        r["ty_" + ty] = col
    r["any_trunc"] = np.any(np.stack([r["ty_" + ty].to_numpy() for ty in LOSS_TYPES]), axis=0)
    r["any_marker"] = np.any(np.stack([r["ty_" + ty].to_numpy() for ty in ALL_TYPES]), axis=0)
    r["truncat_word"] = t.str.contains(r"(?i)truncat", regex=True)
    r["em"] = t.map(lambda s: error_marker(s) or "none")
    ne = r["native_error"]
    r["ne"] = np.where(ne.isna(), "null", np.where(ne.fillna(False).astype(bool), "true", "false"))
    r["ec"] = r["exit_code"].notna()
    # exit line per scaffold
    el = pd.Series([None] * len(r), index=r.index, dtype=object)
    for g in r["group"].unique():
        scaf = SCAFFOLD_EXIT.get(g)
        if scaf is None:
            continue
        pat, mode = EXIT_LINE[scaf]
        idx = r.index[r["group"] == g]
        sub = t.loc[idx]
        if mode == "match":
            v = sub.str.match(pat)
        elif mode == "head600":
            v = sub.str.slice(0, 600).str.contains(pat, regex=True)
        else:
            v = sub.str.contains(pat, regex=True)
        el.loc[idx] = v.astype(bool).astype(object)
    r["el"] = el
    r["h_text"] = t.map(h)
    r["h_pre"] = t.str.slice(0, CAP_RULE["prefix_chars"]).map(h)
    r["h_suf"] = t.map(lambda s: h(s[-CAP_RULE["prefix_chars"]:]))
    ex = [(json.loads(e) if isinstance(e, str) and e else {}) for e in r["extra"].tolist()]
    r["is_flag_truncated"] = pd.Series([d.get("truncated") if isinstance(d, dict) else None for d in ex], index=r.index, dtype=object)
    r["has_persisted_size"] = [isinstance(d, dict) and "persistedOutputSize" in d for d in ex]
    r["flag_true"] = (r["is_flag_truncated"] == True).astype(bool)  # noqa: E712
    last = t.map(lambda s: s.rstrip("\n").split("\n")[-1])
    r["nlines"] = t.map(lambda s: (s.rstrip("\n").count("\n") + 1) if s else 0)
    r["last_paren"] = last.str.startswith("(")
    r["last_len"] = last.str.len()
    r["h_last"] = last.map(h)
    return r.drop(columns=["text", "t", "extra"])


def rate(df, mask):
    """mask: boolean Series on df. Result-level ratio clustered by session + share of sessions with >= 1."""
    g = pd.DataFrame({"s": df["session_id"].to_numpy(), "k": mask.to_numpy().astype(int)}).groupby("s")["k"]
    num, den = g.sum(), g.size()
    cr = stats.cluster_rate(num.to_numpy(), den.to_numpy())
    ks, ns = int((num > 0).sum()), int(len(num))
    p, lo, hi = stats.wilson(ks, ns)
    return {"k": int(mask.sum()), "n": int(len(df)), "rate": cr["rate"], "lo": cr["lo"], "hi": cr["hi"],
            "n_sessions": ns, "k_sessions": ks, "session_share": p, "session_share_lo": lo, "session_share_hi": hi}


def retention(df):
    out = {"n": int(len(df)), "n_sessions": int(df.session_id.nunique()),
           "native_error": {k: int(v) for k, v in df["ne"].value_counts().items()},
           "exit_code_nonnull": int(df["ec"].sum()),
           "error_marker": {k: int(v) for k, v in df["em"].value_counts().items()}}
    el = df["el"].dropna()
    out["exit_line_present"] = None if len(el) == 0 else int(el.astype(bool).sum())
    out["exit_line_detector"] = "none" if len(el) == 0 else "yes"
    err = df[df["ne"] == "true"]
    out["native_error_true_with_error_marker"] = int((err["em"] != "none").sum())
    out["native_error_true_with_exit_line"] = None if len(el) == 0 else int(err["el"].dropna().astype(bool).sum())
    out["native_error_true_with_exit_code"] = int(err["ec"].sum())
    return out


def retention_ratios(df):
    res = {}
    err = df[df["ne"] == "true"]
    if len(err):
        res["error_marker_given_native_error_true"] = rate(err, err["em"] != "none")
    sh = df[(df["cls"] == "shell") & df["el"].notna()]
    if len(sh):
        res["exit_line_given_shell"] = rate(sh, sh["el"].astype(bool))
    return res


def length_block(df):
    out = {"n": int(len(df)), "n_sessions": int(df.session_id.nunique())}
    for u, c in (("chars", "L"), ("bytes", "B"), ("utf16", "U")):
        d = stats.describe(df[c].to_numpy())
        out[u] = d
        if len(df):
            mx = int(df[c].max())
            out[u]["n_at_max"] = int((df[c] == mx).sum())
    out["n_empty"] = int((df["L"] == 0).sum())
    out["n_chars_over_10256"] = int((df["L"] > SWE_CAP_LEN).sum())
    out["n_bytes_ne_chars"] = int((df["B"] != df["L"]).sum())
    out["n_utf16_ne_chars"] = int((df["U"] != df["L"]).sum())
    return out


def window_block(df):
    out = {}
    for u, c in (("chars", "L"), ("bytes", "B"), ("utf16", "U")):
        inw = (df[c] >= WIN[0]) & (df[c] <= WIN[1])
        cmpw = (df[c] >= WIN_CMP[0]) & (df[c] <= WIN_CMP[1])
        w = df[inw]
        out[u] = {"in_window": rate(df, inw), "comparison_window": rate(df, cmpw),
                  "in_window_by_native_error": {k: int(v) for k, v in w["ne"].value_counts().items()},
                  "in_window_with_any_truncation_marker": int(w["any_trunc"].sum()),
                  "in_window_by_marker": {m: int(w["m_" + m].sum()) for m, _, _ in MARKERS if w["m_" + m].any()},
                  "in_window_exact_lengths_top5": [[int(k), int(v)] for k, v in
                                                   w[c].value_counts().sort_index().sort_values(ascending=False, kind="stable").head(5).items()]}
    out["swechat_dataset_cap_exact"] = rate(df, df["m_swe_cap_exact"])
    out["swechat_dataset_cap_loose"] = rate(df, df["m_swe_cap_loose"])
    return out


def tool_counts(sub, private, top=5):
    if private:
        c = Counter((str(k) if str(k) in BUILTIN else "other_tool") for k in sub["tool"].astype(str))
        return dict(c.most_common(top))
    return {str(k): int(v) for k, v in sub["tool_raw"].astype(str).value_counts().head(top).items()}


def marker_block(df, baseline, private):
    out = {"any_truncation": {**rate(df, df["any_trunc"]), "retention": retention(df[df["any_trunc"]]),
                              "retention_ratios": retention_ratios(df[df["any_trunc"]])},
           "any_marker_incl_read_window": rate(df, df["any_marker"]),
           "baseline_no_truncation": {"retention": retention(baseline), "retention_ratios": retention_ratios(baseline)},
           "types": {}, "markers": {},
           "truncat_word_any": rate(df, df["truncat_word"]),
           "residual_truncat_word_no_marker": rate(df, df["truncat_word"] & ~df["any_marker"] & ~df["m_swe_cap_loose"]),
           "structured_flag_true": rate(df, df["flag_true"])}
    fl = df["any_trunc"] | (df["flag_true"] & ~df["ty_read_window"])
    out["any_truncation_or_flag_excl_read_window"] = {**rate(df, fl), "flag_only": int((fl & ~df["any_trunc"]).sum()),
                                                      "retention": retention(df[fl])}
    for ty in ALL_TYPES:
        m = df["ty_" + ty]
        if m.any():
            sub = df[m]
            out["types"][ty] = {**rate(df, m), "chars": stats.describe(sub["L"].to_numpy(), qs=(0.0, 0.5, 1.0)),
                                "retention": retention(sub), "retention_ratios": retention_ratios(sub)}
    for name, ty, _ in MARKERS:
        m = df["m_" + name]
        if m.any():
            sub = df[m]
            out["markers"][name] = {"type": ty, **rate(df, m), "chars": stats.describe(sub["L"].to_numpy(), qs=(0.0, 0.5, 1.0)),
                                    "utf16": stats.describe(sub["U"].to_numpy(), qs=(0.0, 0.5, 1.0)),
                                    "retention": retention(sub), "by_tool": tool_counts(sub, private)}
    return out


def spikes(df, col, private):
    big = df[df[col] > SPIKE_MIN_LEN]
    if not len(big):
        return {"n_over_min": 0, "top": []}
    counts = big[col].value_counts()
    top = counts.sort_index().sort_values(ascending=False, kind="stable").head(SPIKE_TOP)
    hw = CAP_RULE["neighbourhood_halfwidth"]
    res = []
    for L, n in top.items():
        sub = big[big[col] == L]
        nb = counts[(counts.index >= L - hw) & (counts.index <= L + hw) & (counts.index != L)]
        nb_mean = float(nb.sum()) / (2 * hw)  # mean count per exact length over the 100 neighbouring lengths
        ns, npre = int(sub.session_id.nunique()), int(sub["h_pre"].nunique())
        cap = (n >= CAP_RULE["min_n"] and ns >= CAP_RULE["min_sessions"] and npre / n >= CAP_RULE["min_prefix_diversity"]
               and (nb_mean == 0 or n >= CAP_RULE["min_excess_over_neighbourhood"] * nb_mean))
        row = {"length": int(L), "n": int(n), "n_sessions": ns, "distinct_texts": int(sub["h_text"].nunique()),
               "distinct_prefix64": npre, "distinct_suffix64": int(sub["h_suf"].nunique()),
               "neighbourhood_mean_count": round(nb_mean, 4), "with_any_marker": int(sub["any_marker"].sum()),
               "markers": {m: int(sub["m_" + m].sum()) for m, _, _ in MARKERS if sub["m_" + m].any()},
               "tool_class": {k: int(v) for k, v in sub["cls"].value_counts().items()},
               "native_error": {k: int(v) for k, v in sub["ne"].value_counts().items()},
               "cap_candidate": bool(cap)}
        if not private:
            row["tool_raw_top3"] = {str(k): int(v) for k, v in sub["tool_raw"].astype(str).value_counts().head(3).items()}
        else:
            row["tool_top3"] = {(str(k) if str(k) in BUILTIN else "other_tool"): int(v)
                                for k, v in sub["tool"].astype(str).value_counts().head(3).items()}
        res.append(row)
    return {"n_over_min": int(len(big)), "n_distinct_lengths_over_min": int(len(counts)), "top": res}


def flags_block(df, corpus, private):
    out = {}
    f = df["is_flag_truncated"]
    if f.notna().any():
        sub = df[f.notna()]
        by = []
        for grp, g in sub.groupby("group"):
            tab = {"group": grp, "source_key": FLAG_SOURCE.get(grp, "extra.truncated"), "flag_true": int((g["is_flag_truncated"] == True).sum()),  # noqa: E712
                   "flag_false": int((g["is_flag_truncated"] == False).sum()),  # noqa: E712
                   "flag_true_with_any_marker_incl_read_window": int(((g["is_flag_truncated"] == True) & g["any_marker"]).sum()),  # noqa: E712
                   "flag_false_with_any_marker_incl_read_window": int(((g["is_flag_truncated"] == False) & g["any_marker"]).sum()),  # noqa: E712
                   "flag_true_by_marker": {m: int(((g["is_flag_truncated"] == True) & g["m_" + m]).sum()) for m, _, _ in MARKERS  # noqa: E712
                                           if ((g["is_flag_truncated"] == True) & g["m_" + m]).any()}}  # noqa: E712
            tt = g[g["is_flag_truncated"] == True]  # noqa: E712
            tab["flag_true_structure"] = {
                "n": int(len(tt)), "n_sessions": int(tt.session_id.nunique()),
                "line_count_top3": [[int(k), int(v)] for k, v in tt["nlines"].value_counts().head(3).items()],
                "last_line_starts_with_paren": int(tt["last_paren"].sum()),
                "last_line_chars_min": int(tt["last_len"].min()) if len(tt) else None,
                "last_line_chars_max": int(tt["last_len"].max()) if len(tt) else None,
                "distinct_last_lines": int(tt["h_last"].nunique()),
                "contains_truncat_word": int(tt["truncat_word"].sum())}
            ff = g[g["is_flag_truncated"] == False]  # noqa: E712
            tab["flag_false_structure"] = {"n": int(len(ff)), "max_line_count": int(ff["nlines"].max()) if len(ff) else None,
                                           "last_line_starts_with_paren": int(ff["last_paren"].sum())}
            if private:
                tab["flag_true_by_tool"] = {(str(k) if str(k) in BUILTIN else "other_tool"): int(v)
                                            for k, v in tt["tool"].astype(str).value_counts().items()}
            else:
                tab["flag_true_by_tool_raw"] = {str(k): int(v) for k, v in tt["tool_raw"].astype(str).value_counts().items()}
                tab["flag_present_by_tool_raw"] = {str(k): int(v) for k, v in g["tool_raw"].astype(str).value_counts().items()}
            by.append(tab)
        out["extra_truncated_flag"] = {"groups": by}
    p = df["has_persisted_size"]
    if p.any() or df["m_cc_persisted_output"].any():
        out["persistedOutputSize_vs_marker"] = {
            "persistedOutputSize_present": int(p.sum()),
            "persisted_marker": int(df["m_cc_persisted_output"].sum()),
            "both": int((p & df["m_cc_persisted_output"]).sum()),
            "size_only": int((p & ~df["m_cc_persisted_output"]).sum()),
            "marker_only": int((~p & df["m_cc_persisted_output"]).sum())}
    return out


def recon_context():
    """Full-table SWE-chat count of the dataset cap, from the recon output (conversations.parquet, NOT the raw transcripts
    the IR is built from). Copied so the notes can cite it; not a Phase A measurement."""
    f = ROOT / "analysis" / "out" / "recon" / "swechat_scan_pinned.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return {"file": "analysis/out/recon/swechat_scan_pinned.json", "source_table": d.get("path"),
                "result_truncated_10256": d.get("result_truncated_10256"), "tool_result_rows": d.get("roles", {}).get("tool_result"),
                "sessions": d.get("sessions"),
                "definition": "conversations.parquet tool_result content with len == 10256 ending '\\n... [truncated]' "
                              "(analysis/recon/recon_swechat_scan.py)"}
    except (OSError, ValueError):
        return None


def cells(r):
    """Yield (group_label, cls_label, frame) for group x class, plus pooled groups."""
    groups = sorted(r["group"].unique())
    labels = groups + (["_all"] if len(groups) > 1 else [])
    for g in labels:
        gdf = r if g == "_all" else r[r["group"] == g]
        for c in ("shell", "other", "all"):
            cdf = gdf if c == "all" else gdf[gdf["cls"] == c]
            yield g, c, cdf


def main():
    t0 = time.time()
    out = {"question": "A3 truncation", "rules": RULES, "cap_rule": CAP_RULE,
           "markers_catalogue": [{"name": m, "type": t, "pattern": p} for m, t, p in MARKERS], "summary": [], "corpora": {},
           "context_from_recon": recon_context()}
    for corpus in CORPORA:
        private = corpus in PRIVATE
        r, n_sess_all, extra_sys = load(corpus)
        r = annotate(r, corpus)
        c = {"n_results": int(len(r)), "n_sessions_with_results": int(r.session_id.nunique()),
             "n_sessions_split_A": n_sess_all, "groups": {}}
        if extra_sys:
            c.update(extra_sys)
        for g, cl, df in cells(r):
            if not len(df):
                continue
            base = df[~df["any_trunc"]]
            c["groups"].setdefault(g, {})[cl] = {"lengths": length_block(df), "window_10kb": window_block(df),
                                                 "truncation": marker_block(df, base, private)}
        # spikes: per corpus pooled, and per group when several groups
        c["spikes"] = {"_all": {"chars": spikes(r, "L", private), "bytes": spikes(r, "B", private)}}
        if r["group"].nunique() > 1:
            for g, gdf in r.groupby("group"):
                c["spikes"][g] = {"chars": spikes(gdf, "L", private), "bytes": spikes(gdf, "B", private)}
        if corpus == "aiv_cu":
            per = {}
            for s, sdf in r.groupby("stratum"):
                per[str(s)] = {"n": int(len(sdf)), "n_sessions": int(sdf.session_id.nunique()),
                               "shell_n": int((sdf["cls"] == "shell").sum()),
                               "chars_max": int(sdf["L"].max()), "chars_p99": float(np.quantile(sdf["L"], 0.99)),
                               "bytes_max": int(sdf["B"].max()),
                               "top3_lengths_over_1000": [[int(k), int(v)] for k, v in sdf.loc[sdf["L"] > SPIKE_MIN_LEN, "L"]
                                                          .value_counts().sort_index().sort_values(ascending=False, kind="stable").head(3).items()]}
            c["aiv_cu_per_stratum"] = per
            df_full = pd.read_parquet(CACHE / "aiv_cu_A.parquet", columns=["kind", "stderr", "session_id"])
            se = df_full[df_full.kind == "result"]["stderr"].fillna("").astype(str).str.len()
            c["aiv_cu_stderr_chars"] = {**stats.describe(se.to_numpy()), "n_nonempty": int((se > 0).sum())}
            del df_full
        if corpus == "whowhen":
            c["per_tool"] = {}
            for tl, tdf in r.groupby(r["tool"].astype(str)):
                c["per_tool"][tl] = {"lengths": length_block(tdf), "any_truncation": rate(tdf, tdf["any_trunc"]),
                                     "in_window_chars": rate(tdf, (tdf["L"] >= WIN[0]) & (tdf["L"] <= WIN[1]))}
        c["structured_flags"] = flags_block(r, corpus, private)
        out["corpora"][corpus] = c
        # compact summary: corpus-level pooled cell (group '_all' when several groups), per tool class
        top = "_all" if "_all" in c["groups"] else next(iter(c["groups"]))
        for cl, cell in c["groups"][top].items():
            tr = cell["truncation"]
            out["summary"].append({
                "corpus": corpus, "group": top, "tool_class": cl, "n": tr["any_truncation"]["n"],
                "n_sessions": tr["any_truncation"]["n_sessions"],
                "any_truncation_k": tr["any_truncation"]["k"], "any_truncation_rate": tr["any_truncation"]["rate"],
                "any_truncation_lo": tr["any_truncation"]["lo"], "any_truncation_hi": tr["any_truncation"]["hi"],
                "any_truncation_k_sessions": tr["any_truncation"]["k_sessions"],
                "any_truncation_or_flag_k": tr["any_truncation_or_flag_excl_read_window"]["k"],
                "types_k": {ty: v["k"] for ty, v in tr["types"].items()},
                "types_k_sessions": {ty: v["k_sessions"] for ty, v in tr["types"].items()},
                "window_chars_k": cell["window_10kb"]["chars"]["in_window"]["k"],
                "window_chars_rate": cell["window_10kb"]["chars"]["in_window"]["rate"],
                "window_chars_lo": cell["window_10kb"]["chars"]["in_window"]["lo"],
                "window_chars_hi": cell["window_10kb"]["chars"]["in_window"]["hi"],
                "window_chars_cmp_k": cell["window_10kb"]["chars"]["comparison_window"]["k"],
                "window_bytes_k": cell["window_10kb"]["bytes"]["in_window"]["k"],
                "swechat_cap_exact_k": cell["window_10kb"]["swechat_dataset_cap_exact"]["k"],
                "swechat_cap_exact_session_share_hi": cell["window_10kb"]["swechat_dataset_cap_exact"]["session_share_hi"]})
        del r
    out["wall_seconds"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT, out["wall_seconds"], "s")


if __name__ == "__main__":
    main()
