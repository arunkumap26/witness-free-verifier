"""Figures: the transfer matrix and the recall-per-attack table/figure (DESIGN.md §6.4, DA8).

Interfaces (DESIGN.md §6.4, exact):
    transfer_matrix_svg(report: dict) -> str
    recall_table_html(report: dict) -> str
plus, for this build:
    recall_per_attack_svg(report: dict) -> str     # the focused figure that recall_table_html embeds
    report_from_track_a(out_dir) -> dict           # assembles the report dict below from the Track A outputs
    load_report(path) -> dict                      # an eval report JSON (eval/run_eval.py), once it exists
    write_figures(report, out_dir) -> dict          # writes the files, returns {relative path: sha256}

Location note: DESIGN.md §2.1 / §6.4 place this module at `verifier/render/figures.py` and its output at
`reports/figures/`. The Track C scaffold task placed it at `verifier/figures.py` with output in
`analysis/out/phase_e/figures/`; the module is self-contained, so moving it is a one-line import change.

Run (from the worktree root):
    PYTHONIOENCODING=utf-8 python -m verifier.figures                      # Track A outputs -> analysis/out/phase_e/figures/
    python -m verifier.figures --report reports/eval/run_eval_E_full_<sha>.json --out reports/figures

Hand-written SVG and HTML from the standard library only (DA8: no matplotlib, no plotting dependency). Every number
in a figure is copied from the input files, never computed from data: the only arithmetic is counting cell labels
and choosing which split of a unit to show (rule below). Each figure carries its sources (path, LF-normalised
sha256 prefix, committed or not at generation time).

The report contract (what the three figure functions read; `report_from_track_a` builds it, and the eval report
should carry the same keys, DESIGN.md §5.5 `transfer[c][u]` and `recall[c][a][p][u]`):

    report = {
      "title": str,                                    # optional
      "provenance": {"kind": "track_a" | "eval", "files": [{"path", "sha256_lf", "committed"}], "notes": [str]},
      "transfer": {row: {col: cell}},                  # cell = label str, or {"label", "n", "detail", "source",
                                                       #   "suffix", "note", "label_E", "label_B"}
      "transfer_rows": [row, ...], "transfer_cols": [col, ...],          # optional: order (default: sorted)
      "transfer_row_names": {row: str},                                   # optional display names
      "transfer_col_groups": [[group name, [col, ...]], ...],             # optional column groups
      "row_check": {row: "verifier check (TIER)"},                        # optional: which shipped check a row became
      "recall": {check: {attack: {param: {unit: cell}}}},                 # cell = number (recall point) or {"label",
                                                       #   "k", "n", "p", "lo", "hi", "fpr_k", "fpr_n", "fpr_p",
                                                       #   "fpr_lo", "fpr_hi", "adr", "adr_lo", "adr_hi", "split", "source"}
      "cell_label": {check: {attack: {param: {unit: label}}}},            # optional, overrides cell["label"]
      "recall_focus": [[check, unit], ...],            # optional: columns of the focused recall figure
      "check_names": {check: str},                     # optional display names (e.g. Track A detector -> verifier check)
      "attack_class": {attack: "exec" | "edit"},       # optional (default: DESIGN.md §5.4 table)
      "exec_credit": {attack: [check, ...]},           # optional (default: DESIGN.md DA13)
    }
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # worktree root (verifier/ sits at the top level)
DEFAULT_TRACK_A = ROOT / "analysis" / "out" / "phase_e"
DEFAULT_OUT = DEFAULT_TRACK_A / "figures"

# --------------------------------------------------------------------------------------------- constants (copied)
# The 21 attack names in prereg_e.json n7_attack_battery.attacks key order (DESIGN.md §4.4 copies them the same way).
ATTACK_ORDER = (
    "time_result_early", "time_result_late", "time_tail_late", "time_tail_early", "time_response_early",
    "time_response_late", "id_swap_adjacent", "id_splice_foreign", "sub_single_flip_error", "sub_single_digit",
    "sub_matched_bytes", "rewrite_consistent_k", "reorder_adjacent_pairs", "reorder_lines", "delete_pair",
    "delete_response", "insert_pair_consistent", "insert_pair_squeezed", "inline_fabrication", "image_relabel_gui",
    "image_insert_screenshot",
)
# DESIGN.md §5.4 "Threat class of each attack": execution path (in scope, primary) vs record editing (secondary).
EXEC_ATTACKS = frozenset({"sub_single_flip_error", "sub_single_digit", "sub_matched_bytes", "rewrite_consistent_k",
                          "reorder_lines", "inline_fabrication"})
ATTACK_CLASS = {a: ("exec" if a in EXEC_ATTACKS else "edit") for a in ATTACK_ORDER}
CLASS_TITLE = {"exec": "Execution path (in scope): the agent controls the result content",
               "edit": "Record editing (secondary): someone edited a finished log"}
# DESIGN.md DA13: execution-class credit per (check, attack). Track A detector names and verifier check names both
# appear, because the Track A report keys recall by detector.
EXEC_CREDIT = {"inline_fabrication": ["inline_output_accounting", "N2"]}

# DESIGN.md §7.0 / §7.2: which Track A mechanism became which verifier check, and its tier.
N6_ROW_CHECK = {"R1_bracket": "id_bracket (MUST)", "N2": "inline_output_accounting (MUST)",
                "R5_ledger": "ledger_tally (SHOULD)", "R4_dual": "dual_render_recount (SHOULD)",
                "P1_latency": "latency_floor (COULD, cc_local)"}
N7_DETECTOR_CHECK = {"R1_BRACKET": "id_bracket", "N2": "inline_output_accounting", "R5_LEDGER": "ledger_tally",
                     "R4_DUAL": "dual_render_recount", "P1_FLOOR": "latency_floor"}
# The focused recall figure: each kept check in the unit DESIGN.md §7.1 claims for it (latency_floor: cc_local, B).
N7_FOCUS = (("R1_BRACKET", "swechat/claude_code"), ("N2", "swechat/claude_code"), ("R5_LEDGER", "swechat/claude_code"),
            ("R4_DUAL", "swechat/claude_code"), ("P1_FLOOR", "cc_local"))

LABEL_RANK = {"DETECTS": 5, "PARTIAL": 4, "BLIND": 3, "INSUFFICIENT_N": 2, "NA_BLIND_BY_CONSTRUCTION": 1, "NOT_RUN": 0}

# Colour encodes only the label (DESIGN.md §6.4); every cell also carries the label as text. Status palette from the
# dataviz reference instance (good / warning / critical are fixed across themes); grays and surfaces swap in dark.
CSS_TOKENS = """
  :root, svg { --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --axis:#c3c2b7; --insuff:#e2e1dc; --nt:#9b9a95; --hatch:#c3c2b7; --ring:rgba(11,11,11,0.10);
    --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; --strata:#4a3aa7; --accent:#2a78d6; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]), :root:not([data-theme="light"]) svg {
      --surface:#1a1a19; --plane:#0d0d0d; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --axis:#383835; --insuff:#383835; --nt:#6b6a66; --hatch:#4a4a46; --ring:rgba(255,255,255,0.10);
      --strata:#9085e9; --accent:#3987e5; }
  }
  :root[data-theme="dark"], :root[data-theme="dark"] svg {
      --surface:#1a1a19; --plane:#0d0d0d; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --axis:#383835; --insuff:#383835; --nt:#6b6a66; --hatch:#4a4a46; --ring:rgba(255,255,255,0.10);
      --strata:#9085e9; --accent:#3987e5; }
"""
SVG_CSS = CSS_TOKENS + """
  text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink); }
  .bg { fill: var(--surface); }
  .t-title { font-size: 17px; font-weight: 600; }
  .t-sub { font-size: 12px; fill: var(--ink2); }
  .t-row { font-size: 12px; }
  .t-rowsub { font-size: 10px; fill: var(--accent); font-weight: 600; }
  .t-col { font-size: 11px; fill: var(--ink2); }
  .t-grp { font-size: 11px; fill: var(--ink2); font-weight: 600; }
  .t-foot { font-size: 11px; fill: var(--ink2); }
  .t-cell { font-size: 11px; font-weight: 600; }
  .t-n { font-size: 9.5px; }
  .t-small { font-size: 10px; fill: var(--ink2); }
  .t-on-dark { fill: #ffffff; } .t-on-light { fill: #0b0b0b; } .t-on-surface { fill: var(--ink2); }
  .c-good { fill: var(--good); } .c-warn { fill: var(--warn); } .c-crit { fill: var(--crit); }
  .c-insuff { fill: var(--insuff); } .c-nt { fill: var(--nt); } .c-strata { fill: var(--strata); }
  .c-none { fill: url(#hatch); stroke: var(--ring); stroke-width: 1; }
  .c-empty { fill: var(--surface); stroke: var(--ring); stroke-width: 1; }
  .hair { stroke: var(--grid); stroke-width: 1; fill: none; }
  .axis { stroke: var(--axis); stroke-width: 1; fill: none; }
  .sep { stroke: var(--ink2); stroke-width: 1.5; }
  .fprband { fill: var(--muted); opacity: 0.45; }
  .whisk { stroke: var(--ink); stroke-width: 1.5; }
  .dot { fill: var(--ink); stroke: var(--surface); stroke-width: 2; }
  .cell:hover rect.k { stroke: var(--ink); stroke-width: 1.5; }
"""
HATCH_DEF = ('<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
             'patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--surface)"/>'
             '<line x1="0" y1="0" x2="0" y2="6" stroke="var(--hatch)" stroke-width="1.2"/></pattern></defs>')

# transfer-grid vocabulary (prereg_e.json n6_transfer_grid cell_vocabulary) -> (css class, text class, short code)
GRID_STYLE = {"ALIVE": ("c-good", "t-on-dark", "ALIVE"), "WEAK": ("c-warn", "t-on-light", "WEAK"),
              "DEAD": ("c-crit", "t-on-dark", "DEAD"), "INSUFFICIENT_N": ("c-insuff", "t-on-surface", "ins-n"),
              "INCONCLUSIVE": ("c-insuff", "t-on-surface", "inconc"), "NOT_TESTABLE": ("c-nt", "t-on-light", "n/t"),
              "NOT_RUN": ("c-none", "t-on-surface", "n/r"), "PER_STRATUM": ("c-strata", "t-on-dark", "strata")}
# N7 cell vocabulary (prereg_e.json n7_attack_battery cell_label)
N7_STYLE = {"DETECTS": ("c-good", "t-on-dark", "D"), "PARTIAL": ("c-warn", "t-on-light", "P"),
            "BLIND": ("c-crit", "t-on-dark", "B"), "INSUFFICIENT_N": ("c-insuff", "t-on-surface", "n<30"),
            "NA_BLIND_BY_CONSTRUCTION": ("c-empty", "t-on-surface", "na"), "NOT_RUN": ("c-none", "t-on-surface", "n/r")}
LABEL_MEANING_GRID = {
    "ALIVE": "honest flag rate <= 0.05 (CI hi <= 0.10) and >= 1 single-call attack DETECTS",
    "WEAK": "honest <= 0.20 and >= 1 attack DETECTS or PARTIAL", "DEAD": "otherwise",
    "INSUFFICIENT_N": "below min-n", "NOT_TESTABLE": "a required field is absent from the unit",
    "NOT_RUN": "not run (reason in the cell tooltip), including acquired corpora not loaded",
    "PER_STRATUM": "N2 aiv_cu: labelled per provider stratum"}
LABEL_MEANING_N7 = {
    "DETECTS": "recall >= 0.5 and recall CI lo > honest FPR CI hi", "PARTIAL": "recall CI lo > honest FPR CI hi",
    "BLIND": "otherwise", "INSUFFICIENT_N": "< 30 tampered sessions",
    "NA_BLIND_BY_CONSTRUCTION": "the detector reads no field the attack touches",
    "NOT_RUN": "not run"}


# --------------------------------------------------------------------------------------------------- small helpers
def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _git_committed(path: Path) -> bool | None:
    """True if tracked and unmodified in the git index/HEAD, False if untracked or modified, None if git fails."""
    try:
        rel = Path(path).resolve().relative_to(ROOT)
        r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", str(rel).replace("\\", "/")],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        if r.stdout.strip():
            return False
        t = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", str(rel).replace("\\", "/")],
                           capture_output=True, text=True, timeout=30)
        return t.returncode == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _file_record(path: Path, role: str | None = None) -> dict:
    """role: 'transfer' or 'recall' (which figure the file feeds); None = all."""
    p = Path(path)
    try:
        rel = str(p.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        rel = str(p)
    rec = {"path": rel, "sha256_lf": sha256_lf(p), "committed": _git_committed(p)}
    if role:
        rec["role"] = role
    return rec


def _fmt_int(v) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "" if v is None else str(v)


def _fmt_p(v, nd=3) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _param_key(p: str):
    try:
        return (0, float(p), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(p))


def _attack_key(a: str):
    return (ATTACK_ORDER.index(a) if a in ATTACK_ORDER else len(ATTACK_ORDER), a)


def _base_label(label: str) -> str:
    """'NOT_TESTABLE(provider ids...)' -> 'NOT_TESTABLE'; 'WEAK (DOMINATED ...)' -> 'WEAK'."""
    m = re.match(r"\s*([A-Z_]+)", label or "")
    return m.group(1) if m else (label or "")


def _compact_n(n) -> str:
    """Short n for a cell face; the full n string is in the tooltip."""
    if n is None or n == "":
        return ""
    if isinstance(n, (int, float)):
        return "n=" + _fmt_int(n)
    s = str(n)
    m = re.search(r"(\d[\d,]*)", s)
    if not m or s.lstrip().startswith("{"):
        return ""
    return "n=" + _fmt_int(m.group(1).replace(",", ""))


# --------------------------------------------------------------------------------------------------- normalisation
def _norm_transfer_cell(c) -> dict:
    if isinstance(c, str):
        return {"label": c}
    return dict(c or {"label": "NOT_RUN(no cell)"})


def _norm_recall_cell(c, label_override=None) -> dict:
    if c is None:
        return {}
    if isinstance(c, (int, float)):
        d = {"p": float(c)}
    else:
        d = dict(c)
    if label_override:
        d["label"] = label_override
    return d


def _cell_label_of(report, check, attack, param, unit):
    try:
        return report["cell_label"][check][attack][param][unit]
    except (KeyError, TypeError):
        return None


# ----------------------------------------------------------------------------------------- Track A -> report dict
def _n7_cell_to_report(key: str, c: dict, src_name: str) -> dict:
    """One N7 cell (n7_timing.json or n7_content.json shape) -> the report's recall cell. Copies, never computes."""
    out = {"label": c.get("label"), "split": c.get("split"), "source": f'{src_name} cells."{key}"'}
    r, f, a = c.get("recall"), c.get("fpr"), c.get("adr")
    if isinstance(r, dict):                                    # n7_timing shape
        out.update(k=r.get("k"), n=r.get("n"), p=r.get("p"), lo=r.get("lo"), hi=r.get("hi"))
    elif isinstance(r, (list, tuple)) and len(r) == 3:         # n7_content shape: [p, lo, hi] + k/n fields
        out.update(k=c.get("k_tampered_flagged"), n=c.get("n_tampered"), p=r[0], lo=r[1], hi=r[2])
    if isinstance(f, dict):
        out.update(fpr_k=f.get("k"), fpr_n=f.get("n"), fpr_p=f.get("p"), fpr_lo=f.get("lo"), fpr_hi=f.get("hi"))
    elif isinstance(f, (list, tuple)) and len(f) == 3:
        out.update(fpr_k=c.get("k_honest_flagged"), fpr_n=c.get("n_honest"), fpr_p=f[0], fpr_lo=f[1], fpr_hi=f[2])
    if isinstance(a, dict):
        out.update(adr=a.get("value", a.get("rate")), adr_lo=a.get("lo"), adr_hi=a.get("hi"))
    loc = c.get("localization")
    if isinstance(loc, dict):
        out["loc_share"] = loc.get("share")
    if c.get("label_note") or c.get("labels"):
        out["note"] = c.get("label_note") or "; ".join(c.get("labels") or [])
    return out


def _assemble_grid_fallback(out_dir: Path, files: list, notes: list) -> dict:
    """n6_grid.json absent: columns from the committed new-corpus measurements only. Nothing is guessed: every
    other cell is NOT_RUN(n6_grid.json absent) and the notes say so."""
    transfer, cols = {}, []
    for p in sorted(out_dir.glob("newcorp_measure_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        cells = d.get("cells") if isinstance(d, dict) else None     # newcorp_measure_workflow_result.json is a list
        if not isinstance(cells, dict):
            continue
        files.append(_file_record(p, "transfer"))
        corpus = d.get("corpus") or p.stem.replace("newcorp_measure_", "")
        for row, v in cells.items():
            if isinstance(v, dict) and "label" in v:
                per_unit = {corpus: v}
            elif isinstance(v, dict):
                per_unit = {u: vv for u, vv in v.items() if isinstance(vv, dict) and "label" in vv}
            else:
                continue
            for unit, cell in per_unit.items():
                if unit not in cols:
                    cols.append(unit)
                transfer.setdefault(row, {})[unit] = {
                    "label": cell.get("label"), "n": cell.get("n") if not isinstance(cell.get("n"), dict) else None,
                    "detail": json.dumps(cell.get("deciding_number"))[:600] if cell.get("deciding_number") else None,
                    "source": f"{p.name} cells.{row}" + ("" if unit == corpus else f'."{unit}"')}
    notes.append({"role": "transfer", "text": "analysis/out/phase_e/n6_grid.json was absent: the grid shows the "
                  "new-corpus columns from newcorp_measure_*.json only; the Phase B unit columns need n6_grid.json."})
    rows = sorted(transfer)
    for r in rows:
        for c in cols:
            transfer[r].setdefault(c, {"label": "NOT_RUN(no cell in source)"})
    return {"transfer": transfer, "transfer_rows": rows, "transfer_cols": cols,
            "transfer_col_groups": [["Track B corpora (newcorp_measure_*.json)", cols]]}


def report_from_track_a(out_dir: str | Path = DEFAULT_TRACK_A) -> dict:
    """Assemble the report dict from the Track A outputs: transfer from n6_grid.json (else the fallback above),
    with the committed newcorp_resolutions.json relabels applied and marked; recall from n7_timing.json and
    n7_content.json. Shown split per unit: E where the unit has any E cell, else B (Track A's replication split)."""
    out_dir = Path(out_dir)
    files, notes = [], []
    rep: dict = {"title": "Track A outputs (Phase E)", "check_names": dict(N7_DETECTOR_CHECK),
                 "row_check": dict(N6_ROW_CHECK), "attack_class": dict(ATTACK_CLASS),
                 "exec_credit": {k: list(v) for k, v in EXEC_CREDIT.items()}}

    n6p = out_dir / "n6_grid.json"
    if n6p.exists():
        files.append(_file_record(n6p, "transfer"))
        g = json.loads(n6p.read_text(encoding="utf-8"))
        transfer = {}
        for row in g["rows"]:
            transfer[row] = {}
            for col, c in g["cells"][row].items():
                transfer[row][col] = {"label": c.get("label"), "base": c.get("base"), "n": c.get("n"),
                                      "detail": c.get("deciding_number"), "source": c.get("source"),
                                      "suffix": c.get("suffix"), "label_E": c.get("label_E"),
                                      "label_B": c.get("label_B"),
                                      "key": f'n6_grid.json cells.{row}."{col}"'}
        rep.update(transfer=transfer, transfer_rows=list(g["rows"]),
                   transfer_cols=list(g["columns_loaded"]) + list(g["columns_not_loaded"]),
                   transfer_row_names=dict(g.get("row_names") or {}),
                   transfer_col_groups=[[f"Phase B units ({len(g['columns_phase_b'])})", list(g["columns_phase_b"])],
                                        [f"Track B corpora ({len(g['columns_track_b'])})", list(g["columns_track_b"])],
                                        [f"acquired, not loaded ({len(g['columns_not_loaded'])})",
                                         list(g["columns_not_loaded"])]])
    else:
        rep.update(_assemble_grid_fallback(out_dir, files, notes))

    resp = out_dir / "newcorp_resolutions.json"
    if resp.exists():
        files.append(_file_record(resp, "transfer"))
        for i, r in enumerate(json.loads(resp.read_text(encoding="utf-8")).get("resolutions", [])):
            row, col = r.get("cell"), r.get("corpus")
            cell = rep["transfer"].get(row, {}).get(col)
            if cell is None or _base_label(cell.get("label")) == _base_label(r.get("label_after")):
                continue
            cell["note"] = (f"relabelled {_base_label(cell['label'])} -> {r['label_after']} by "
                            f"newcorp_resolutions.json resolutions[{i}] ({r.get('rule', '')[:160]})")
            cell["label_source_grid"] = cell["label"]
            cell["label"] = r["label_after"]
            cell["base"] = _base_label(r["label_after"])
            cell["resolved"] = True
            grid_src = "n6_grid.json" if n6p.exists() else "the grid source"
            notes.append({"role": "transfer", "text": f"{row} x {col}: {grid_src} says "
                          f"{_base_label(cell['label_source_grid'])}; newcorp_resolutions.json "
                          f"resolutions[{i}] relabels it {r['label_after']} (shown, marked +)."})

    # recall: N7 timing + content
    raw: list[tuple[str, dict, str]] = []
    for name in ("n7_timing.json", "n7_content.json"):
        p = out_dir / name
        if not p.exists():
            notes.append({"role": "recall", "text": f"{name} absent: its detectors are missing from the recall figures."})
            continue
        files.append(_file_record(p, "recall"))
        for key, c in json.loads(p.read_text(encoding="utf-8"))["cells"].items():
            raw.append((key, c, name))
    units_with_e = {key.split("|")[0] for key, _, _ in raw if key.split("|")[1] == "E"}
    recall: dict = {}
    for key, c, name in raw:
        unit, split, det, attack, param = key.split("|")
        want = "E" if unit in units_with_e else "B"
        if split != want:
            continue
        recall.setdefault(det, {}).setdefault(attack, {}).setdefault(param, {})[unit] = _n7_cell_to_report(key, c, name)
    rep["recall"] = recall
    rep["recall_focus"] = [[d, u] for d, u in N7_FOCUS if d in recall]
    notes.append({"role": "recall", "text": "Recall cells: the replication split of each unit (E where the unit has "
                  "E, else B); every split is in the source files. All tampering is synthetic."})
    rep["provenance"] = {"kind": "track_a", "files": files, "notes": notes}
    return rep


def _recall_from_eval_cells(rep: dict, src_name: str) -> dict:
    """eval/run_eval.py reports carry recall as cells["<unit>|<attack>|<param>"].per_check[<check>][<seed>] (DESIGN.md
    5.5), not as the figure contract's recall[check][attack][param][unit]. Copy the first seed's values (the seed the
    cell labels use) into the contract shape. Reference checks (transfer row all NOT_APPLICABLE(reference)) are
    skipped: they never decide, so a recall row for them would read as BLIND."""
    seeds = rep.get("seeds") or [0]
    s0 = str(seeds[0])
    units_meta = ((rep.get("pack") or {}).get("units") or {})
    T = rep.get("transfer") or {}
    ref = {c for c, row in T.items() if row and all(str(_norm_transfer_cell(x).get("label", "")).startswith(
        "NOT_APPLICABLE(reference)") for x in row.values())}
    recall: dict = {}
    for key, cell in sorted((rep.get("cells") or {}).items()):
        unit, attack, param = key.split("|", 2)
        for chk, by_seed in sorted((cell.get("per_check") or {}).items()):
            c = (by_seed or {}).get(s0)
            if chk in ref or not isinstance(c, dict):
                continue
            r = c.get("recall") or {}
            f = (c.get("cell_label_basis") or {}).get("fpr_same_sessions") or {}
            loc = c.get("localization") or {}
            recall.setdefault(chk, {}).setdefault(attack, {}).setdefault(param, {})[unit] = {
                "label": c.get("cell_label"), "k": r.get("k"), "n": r.get("n"), "p": r.get("p"), "lo": r.get("lo"),
                "hi": r.get("hi"), "fpr_k": f.get("k"), "fpr_n": f.get("n"), "fpr_p": f.get("p"), "fpr_lo": f.get("lo"),
                "fpr_hi": f.get("hi"), "adr": c.get("adr"), "loc_share": loc.get("share"),
                "split": (units_meta.get(unit) or {}).get("dev_split") or rep.get("split"),
                "source": f'{src_name} cells."{key}".per_check.{chk}."{s0}"'}
    return recall


def load_report(path: str | Path) -> dict:
    """An eval report JSON. It must carry 'transfer' and/or 'recall' in the contract above; an eval/run_eval.py
    report's per-cell recall ('cells') is converted to 'recall' here."""
    rep = json.loads(Path(path).read_text(encoding="utf-8"))
    if "recall" not in rep and isinstance(rep.get("cells"), dict):
        rec = _recall_from_eval_cells(rep, Path(path).name)
        if rec:
            rep["recall"] = rec
            if rep.get("exec_credit") is None and isinstance((rep.get("eval") or {}).get("exec_credit"), dict):
                rep["exec_credit"] = rep["eval"]["exec_credit"]
    if "transfer" not in rep and "recall" not in rep:
        raise ValueError(f"{path}: no 'transfer' or 'recall' key (see verifier/figures.py report contract)")
    rep.setdefault("provenance", {"kind": "eval", "files": [_file_record(Path(path))], "notes": []})
    return rep


# ------------------------------------------------------------------------------------------------ transfer matrix
def _grid_counts(report) -> Counter:
    cnt = Counter()
    for row in report.get("transfer", {}).values():
        for c in row.values():
            cnt[_base_label(_norm_transfer_cell(c).get("label"))] += 1
    return cnt


def _notes(report, role: str) -> list[str]:
    out = []
    for n in (report.get("provenance") or {}).get("notes", []):
        if isinstance(n, dict):
            if n.get("role") in (None, role):
                out.append(n.get("text", ""))
        else:
            out.append(str(n))
    return out


def _sources_lines(report, role: str | None = None) -> list[str]:
    out = []
    for f in (report.get("provenance") or {}).get("files", []):
        if role and f.get("role") not in (None, role):
            continue
        st = {True: "committed", False: "UNCOMMITTED", None: "git status unknown"}[f.get("committed")]
        out.append(f"{f['path']} sha256_lf {f['sha256_lf'][:16]} ({st})")
    return out


def transfer_matrix_svg(report: dict) -> str:
    """Mechanism x unit grid. Every cell is drawn, failing and not-run cells included (PHASE_E_PROMPT.md N6)."""
    T = report.get("transfer") or {}
    rows = list(report.get("transfer_rows") or sorted(T))
    cols = list(report.get("transfer_cols") or sorted({c for r in T.values() for c in r}))
    groups = report.get("transfer_col_groups") or [["units", cols]]
    names = report.get("transfer_row_names") or {}
    row_check = report.get("row_check") or {}

    cw, ch, gap = 78, 38, 2
    left, top = 330, 132
    group_gap = 10
    xs, x = {}, left
    for gi, (_, gcols) in enumerate(groups):
        for c in gcols:
            if c in cols and c not in xs:
                xs[c] = x
                x += cw + gap
        x += group_gap
    for c in cols:                      # columns not named in any group go at the end
        if c not in xs:
            xs[c] = x
            x += cw + gap
    width = x + 20
    grid_bottom = top + len(rows) * (ch + gap)
    col_label_h = 120
    cnt = _grid_counts(report)
    decided = sum(cnt[k] for k in ("ALIVE", "WEAK", "DEAD"))
    notes = _notes(report, "transfer")
    src = _sources_lines(report, "transfer")
    legend_y = grid_bottom + col_label_h + 18
    foot_lines = 4 + len(notes) + len(src)
    height = legend_y + 34 + foot_lines * 16 + 16

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
         f'role="img" aria-labelledby="tm-title tm-desc">',
         f"<style>{SVG_CSS}</style>", HATCH_DEF,
         f'<rect class="bg" x="0" y="0" width="{width}" height="{height}"/>']
    title = (f"Transfer matrix: {len(rows)} mechanisms x {len(cols)} units, every cell shown "
             f"({report.get('title', '')})")
    sub = (f"Decided cells {decided} (ALIVE {cnt['ALIVE']}, WEAK {cnt['WEAK']}, DEAD {cnt['DEAD']}); "
           f"INSUFFICIENT_N {cnt['INSUFFICIENT_N'] + cnt['INCONCLUSIVE']}, NOT_TESTABLE {cnt['NOT_TESTABLE']}, "
           f"NOT_RUN {cnt['NOT_RUN']}, PER_STRATUM {cnt['PER_STRATUM']}. Colour encodes only the label; "
           f"hover a cell for its deciding number and source.")
    o.append(f'<title id="tm-title">{_e(title)}</title><desc id="tm-desc">{_e(sub)}</desc>')
    o.append(f'<text class="t-title" x="24" y="34">{_e(title)}</text>')
    o.append(f'<text class="t-sub" x="24" y="54">{_e(sub)}</text>')
    o.append('<text class="t-sub" x="24" y="72">Cell face: label, then n. Markers: B = B split only; '
             '* = not blind (E read before freeze, prereg D6); + = relabelled by a committed resolution. '
             'Rows in blue name the verifier check the mechanism became (DESIGN.md 7.0).</text>')

    # group headers
    for gname, gcols in groups:
        gx = [xs[c] for c in gcols if c in xs]
        if not gx:
            continue
        x0, x1 = min(gx), max(gx) + cw
        o.append(f'<line class="axis" x1="{x0}" y1="{top - 14}" x2="{x1}" y2="{top - 14}"/>')
        o.append(f'<text class="t-grp" x="{(x0 + x1) / 2:.1f}" y="{top - 20}" text-anchor="middle">{_e(gname)}</text>')

    for ri, row in enumerate(rows):
        y = top + ri * (ch + gap)
        nm = names.get(row, row)
        rc = row_check.get(row)
        if rc:
            o.append(f'<text class="t-row" x="{left - 10}" y="{y + 16}" text-anchor="end">{_e(nm)}</text>')
            o.append(f'<text class="t-rowsub" x="{left - 10}" y="{y + 30}" text-anchor="end">'
                     f'verifier: {_e(rc)}</text>')
        else:
            o.append(f'<text class="t-row" x="{left - 10}" y="{y + ch / 2 + 4}" text-anchor="end">{_e(nm)}</text>')
        for col in cols:
            c = _norm_transfer_cell((T.get(row) or {}).get(col))
            label = c.get("label") or "NOT_RUN(no cell)"
            base = c.get("base") or _base_label(label)
            cls, tcls, code = GRID_STYLE.get(base, ("c-none", "t-on-surface", base[:6].lower()))
            if base == "PER_STRATUM":
                m = re.findall(r"(ALIVE|WEAK|DEAD) (\d+)", label)
                code = " ".join(f"{k}{v[0]}" for v, k in m) if m else "strata"
            suffix = (c.get("suffix") or "")
            marks = ""
            if base in ("ALIVE", "WEAK", "DEAD", "INSUFFICIENT_N", "INCONCLUSIVE"):
                if ("B only" in suffix) or (c.get("label_E") is None and c.get("label_B") is not None):
                    marks += " B"
                if "not_blind" in suffix.lower().replace(" ", "_"):
                    marks += "*"
            if c.get("resolved"):
                marks += "+"
            x0 = xs[col]
            tip = [f"{names.get(row, row)} x {col}", f"label: {label}"]
            if c.get("label_source_grid"):
                tip.append(f"grid label before resolution: {c['label_source_grid']}")
            if suffix:
                tip.append(f"qualifiers: {suffix}")
            if c.get("detail"):
                tip.append(f"deciding number: {c['detail']}")
            if c.get("n") not in (None, ""):
                tip.append(f"n: {c['n']}")
            if c.get("note"):
                tip.append(f"note: {c['note']}")
            if c.get("key"):
                tip.append(f"cell: {c['key']}")
            if c.get("source"):
                tip.append(f"measured in: {c['source']}")
            nshort = "" if base in ("NOT_RUN", "NOT_TESTABLE") else _compact_n(c.get("n"))
            if base == "PER_STRATUM" and c.get("n"):
                nshort = str(c["n"]).replace("model ", "")
            o.append(f'<g class="cell"><title>{_e(chr(10).join(tip))}</title>'
                     f'<rect class="k {cls}" x="{x0}" y="{y}" width="{cw}" height="{ch}" rx="3"/>')
            ty = y + (15 if nshort else ch / 2 + 4)
            o.append(f'<text class="t-cell {tcls}" x="{x0 + cw / 2}" y="{ty}" text-anchor="middle">'
                     f'{_e(code + marks)}</text>')
            if nshort:
                o.append(f'<text class="t-n {tcls}" x="{x0 + cw / 2}" y="{y + 30}" text-anchor="middle">'
                         f'{_e(nshort)}</text>')
            o.append("</g>")

    # column labels, rotated
    for col in cols:
        cx = xs[col] + cw / 2
        o.append(f'<text class="t-col" x="{cx}" y="{grid_bottom + 10}" text-anchor="end" '
                 f'transform="rotate(-40 {cx} {grid_bottom + 10})">{_e(col)}</text>')

    # legend
    lx = 24
    for base in ("ALIVE", "WEAK", "DEAD", "INSUFFICIENT_N", "NOT_TESTABLE", "NOT_RUN", "PER_STRATUM"):
        cls, tcls, code = GRID_STYLE[base]
        o.append(f'<g><title>{_e(base + ": " + LABEL_MEANING_GRID[base])}</title>'
                 f'<rect class="{cls}" x="{lx}" y="{legend_y}" width="46" height="20" rx="3"/>'
                 f'<text class="t-n {tcls}" x="{lx + 23}" y="{legend_y + 14}" text-anchor="middle">{_e(code)}</text>'
                 f'<text class="t-small" x="{lx + 52}" y="{legend_y + 14}">{_e(base)}</text></g>')
        lx += 52 + 9 * len(base) + 22
    fy = legend_y + 44
    foot = ["Rule (prereg_e.json n6_transfer_grid / a1.proposal_rules): ALIVE = honest flag rate <= 0.05 with CI hi "
            "<= 0.10 and >= 1 single-call attack DETECTS; WEAK = honest <= 0.20 and >= 1 attack DETECTS or PARTIAL; "
            "DEAD otherwise.",
            "These are Track A probe labels, not verifier measurements: the verifier inherits a label only after a "
            "parity test reproduces it (DESIGN.md DA15). All tampering behind the labels is synthetic.",
            *notes, "Sources:", *src]
    for i, line in enumerate(foot):
        o.append(f'<text class="t-foot" x="24" y="{fy + i * 16}">{_e(line)}</text>')
    o.append("</svg>")
    return "\n".join(o)


# ------------------------------------------------------------------------------------------------ recall per attack
def _recall_rows(report, focus):
    """(class, attack, param) rows present for any focus column, exec class first, then prereg order."""
    R = report.get("recall") or {}
    cls_of = report.get("attack_class") or ATTACK_CLASS
    rows = set()
    for chk, unit in focus:
        for attack, by_p in (R.get(chk) or {}).items():
            for param, by_u in by_p.items():
                if unit in by_u:
                    rows.add((cls_of.get(attack, "edit"), attack, param))
    order = {"exec": 0, "edit": 1}
    return sorted(rows, key=lambda r: (order.get(r[0], 2), _attack_key(r[1]), _param_key(r[2])))


def _focus(report):
    f = report.get("recall_focus")
    if f:
        return [tuple(x) for x in f]
    R = report.get("recall") or {}
    out = []
    for chk in sorted(R):
        units = sorted({u for by_p in R[chk].values() for by_u in by_p.values() for u in by_u})
        out += [(chk, u) for u in units[:1]]
    return out


def _credited(report, check, attack) -> bool:
    ec = report.get("exec_credit") or EXEC_CREDIT
    return check in (ec.get(attack) or [])


def recall_per_attack_svg(report: dict) -> str:
    """Focused figure: each kept check in its claimed unit x every (attack, param) Track A ran there. Per cell: the
    label (colour + text), recall k/n with its 95% CI as a dot and whisker on a 0-1 track, and the same sessions'
    honest flag rate CI as a grey band. Missing cells are drawn, not dropped."""
    R = report.get("recall") or {}
    focus = _focus(report)
    rows = _recall_rows(report, focus)
    names = report.get("check_names") or {}
    cls_of = report.get("attack_class") or ATTACK_CLASS

    left, top, cw, rh, gap = 250, 150, 236, 24, 2
    track_x0, track_w = 92, 96
    n_groups = len({r[0] for r in rows})
    height = (top + len(rows) * (rh + gap) + n_groups * 30 + 200
              + 16 * (len(_sources_lines(report, "recall")) + len(_notes(report, "recall"))))
    width = left + len(focus) * (cw + 8) + 24
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
         f'role="img" aria-labelledby="rp-title rp-desc">', f"<style>{SVG_CSS}</style>", HATCH_DEF,
         f'<rect class="bg" x="0" y="0" width="{width}" height="{height}"/>']
    title = "Recall per attack: the kept checks in their claimed units (Track A N7 cells)"
    sub = ("Per cell: label; recall k/n; dot = recall, whisker = its 95% CI; grey band = honest flag-rate 95% CI of "
           "the same sessions untampered. Synthetic tampering only.")
    o.append(f'<title id="rp-title">{_e(title)}</title><desc id="rp-desc">{_e(sub)}</desc>')
    o.append(f'<text class="t-title" x="24" y="34">{_e(title)}</text>')
    o.append(f'<text class="t-sub" x="24" y="54">{_e(sub)}</text>')
    o.append('<text class="t-sub" x="24" y="72">^ = a hit in an execution-path cell by a check without execution '
             'credit: an edit artifact, not in-scope power (DESIGN.md DA13).</text>')

    for ci, (chk, unit) in enumerate(focus):
        x0 = left + ci * (cw + 8)
        any_cell = next((by_u[unit] for by_p in (R.get(chk) or {}).values() for by_u in by_p.values()
                         if unit in by_u), {})
        split = _norm_recall_cell(any_cell).get("split") or ""
        o.append(f'<text class="t-row" x="{x0}" y="{top - 46}" font-weight="600">{_e(names.get(chk, chk))}</text>')
        o.append(f'<text class="t-small" x="{x0}" y="{top - 31}">{_e(chk)} · {_e(unit)}'
                 f'{(" · split " + _e(split)) if split else ""}</text>')
        # 0-1 axis ticks
        o.append(f'<text class="t-small" x="{x0 + track_x0}" y="{top - 10}" text-anchor="middle">0</text>')
        o.append(f'<text class="t-small" x="{x0 + track_x0 + track_w}" y="{top - 10}" text-anchor="middle">1</text>')

    y = top
    current = None
    for cls, attack, param in rows:
        if cls != current:
            current = cls
            y += 8
            o.append(f'<text class="t-grp" x="24" y="{y + 12}">{_e(CLASS_TITLE.get(cls, cls))}</text>')
            o.append(f'<line class="axis" x1="24" y1="{y + 18}" x2="{width - 24}" y2="{y + 18}"/>')
            y += 22
        plabel = attack if param in ("-", "") else f"{attack}  {param}"
        o.append(f'<text class="t-row" x="{left - 12}" y="{y + rh / 2 + 4}" text-anchor="end">{_e(plabel)}</text>')
        for ci, (chk, unit) in enumerate(focus):
            x0 = left + ci * (cw + 8)
            raw = (((R.get(chk) or {}).get(attack) or {}).get(param) or {}).get(unit)
            c = _norm_recall_cell(raw, _cell_label_of(report, chk, attack, param, unit))
            if not c:
                o.append(f'<g class="cell"><title>{_e(f"{chk} x {attack} {param} in {unit}: no cell in the source")}'
                         f'</title><rect class="k c-empty" x="{x0}" y="{y}" width="{cw}" height="{rh}" rx="3" '
                         f'opacity="0.6"/><text class="t-small" x="{x0 + 10}" y="{y + rh / 2 + 4}">— no cell</text></g>')
                continue
            label = c.get("label") or ""
            scls, tcls, code = N7_STYLE.get(label, ("c-empty", "t-on-surface", label[:4]))
            artifact = (cls_of.get(attack) == "exec" and label in ("DETECTS", "PARTIAL")
                        and not _credited(report, chk, attack))
            tip = [f"{names.get(chk, chk)} ({chk}) x {attack} {param}, unit {unit}, split {c.get('split', '')}",
                   f"label: {label}" + ("  [edit artifact: no execution credit, DA13]" if artifact else ""),
                   f"recall {_fmt_int(c.get('k'))}/{_fmt_int(c.get('n'))} = {_fmt_p(c.get('p'))} "
                   f"[{_fmt_p(c.get('lo'))}, {_fmt_p(c.get('hi'))}]",
                   f"honest flag {_fmt_int(c.get('fpr_k'))}/{_fmt_int(c.get('fpr_n'))} = {_fmt_p(c.get('fpr_p'))} "
                   f"[{_fmt_p(c.get('fpr_lo'))}, {_fmt_p(c.get('fpr_hi'))}]",
                   f"ADR {_fmt_p(c.get('adr'))} [{_fmt_p(c.get('adr_lo'))}, {_fmt_p(c.get('adr_hi'))}]"]
            if c.get("note"):
                tip.append(f"note: {c['note']}")
            if c.get("source"):
                tip.append(f"source: {c['source']}")
            o.append(f'<g class="cell"><title>{_e(chr(10).join(tip))}</title>')
            o.append(f'<rect class="k c-empty" x="{x0}" y="{y}" width="{cw}" height="{rh}" rx="3"/>')
            o.append(f'<rect class="{scls}" x="{x0 + 2}" y="{y + 2}" width="40" height="{rh - 4}" rx="3"/>')
            o.append(f'<text class="t-n {tcls}" x="{x0 + 22}" y="{y + rh / 2 + 3.5}" text-anchor="middle" '
                     f'font-weight="600">{_e(code + ("^" if artifact else ""))}</text>')
            if label not in ("NA_BLIND_BY_CONSTRUCTION", "NOT_RUN") and c.get("p") is not None:
                tx0, ty = x0 + track_x0, y + rh / 2
                o.append(f'<line class="axis" x1="{tx0}" y1="{ty}" x2="{tx0 + track_w}" y2="{ty}"/>')
                if c.get("fpr_lo") is not None and c.get("fpr_hi") is not None:
                    a, b = float(c["fpr_lo"]), float(c["fpr_hi"])
                    o.append(f'<rect class="fprband" x="{tx0 + a * track_w:.1f}" y="{ty - 6}" '
                             f'width="{max(1.5, (b - a) * track_w):.1f}" height="12" rx="1"/>')
                if c.get("lo") is not None and c.get("hi") is not None:
                    o.append(f'<line class="whisk" x1="{tx0 + float(c["lo"]) * track_w:.1f}" y1="{ty}" '
                             f'x2="{tx0 + float(c["hi"]) * track_w:.1f}" y2="{ty}"/>')
                o.append(f'<circle class="dot" cx="{tx0 + float(c["p"]) * track_w:.1f}" cy="{ty}" r="4"/>')
                kn = (f"{_fmt_int(c.get('k'))}/{_fmt_int(c.get('n'))}" if c.get("k") is not None
                      else _fmt_p(c.get("p"), 2))
                o.append(f'<text class="t-small" x="{x0 + track_x0 + track_w + 8}" y="{y + rh / 2 + 4}">'
                         f'{_e(kn)}</text>')
            else:
                short = {"NA_BLIND_BY_CONSTRUCTION": "blind by construction", "NOT_RUN": "not run"}
                o.append(f'<text class="t-small" x="{x0 + 50}" y="{y + rh / 2 + 4}">'
                         f'{_e(short.get(label, "no recall in source"))}</text>')
            o.append("</g>")
        y += rh + gap

    # legend + sources
    y += 22
    lx = 24
    for lab in ("DETECTS", "PARTIAL", "BLIND", "INSUFFICIENT_N", "NA_BLIND_BY_CONSTRUCTION"):
        scls, tcls, code = N7_STYLE[lab]
        o.append(f'<g><title>{_e(lab + ": " + LABEL_MEANING_N7[lab])}</title>'
                 f'<rect class="{scls}" x="{lx}" y="{y}" width="40" height="18" rx="3"/>'
                 f'<text class="t-n {tcls}" x="{lx + 20}" y="{y + 13}" text-anchor="middle">{_e(code)}</text>'
                 f'<text class="t-small" x="{lx + 46}" y="{y + 13}">{_e(lab)}: {_e(LABEL_MEANING_N7[lab])}</text></g>')
        y += 22
    y += 8
    foot = ["Track A probe cells (prereg_e.json n7_attack_battery, seed-0 plan, Wilson CIs as the probes computed "
            "them); not verifier measurements until parity (DESIGN.md DA15). The full table is "
            "recall_per_attack.html.", *_notes(report, "recall"), "Sources:",
            *_sources_lines(report, "recall")]
    for i, line in enumerate(foot):
        o.append(f'<text class="t-foot" x="24" y="{y + i * 16}">{_e(line)}</text>')
    o.append("</svg>")
    final_h = int(y + len(foot) * 16 + 12)          # trim the estimate to the drawn content
    o[0] = o[0].replace(f"0 0 {width} {height}", f"0 0 {width} {final_h}").replace(
        f'height="{height}"', f'height="{final_h}"')
    o[3] = o[3].replace(f'height="{height}"', f'height="{final_h}"')
    return "\n".join(o)


HTML_CSS = CSS_TOKENS + """
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--plane); color: var(--ink);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 14px; line-height: 1.45; }
  main { max-width: 1500px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 22px; margin: 0 0 6px; } h2 { font-size: 17px; margin: 28px 0 8px; }
  p { margin: 6px 0; color: var(--ink2); max-width: 1100px; }
  .fig { overflow-x: auto; background: var(--surface); border: 1px solid var(--ring); border-radius: 6px; }
  .fig svg { display: block; }
  .filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 10px 0; }
  .filters label { font-size: 12px; color: var(--ink2); display: flex; gap: 6px; align-items: center; }
  select, input[type=search] { font: inherit; font-size: 13px; padding: 4px 6px; background: var(--surface);
         color: var(--ink); border: 1px solid var(--axis); border-radius: 4px; }
  .count { font-size: 12px; color: var(--ink2); }
  .tablewrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--ring); border-radius: 6px; }
  table { border-collapse: collapse; width: 100%; font-size: 12.5px; font-variant-numeric: tabular-nums; }
  th, td { padding: 4px 8px; border-bottom: 1px solid var(--grid); text-align: left; white-space: nowrap; }
  th { position: sticky; top: 0; background: var(--surface); cursor: pointer; color: var(--ink2); font-weight: 600; }
  th:hover { color: var(--ink); }
  td.num { text-align: right; }
  td.src { color: var(--muted); font-size: 11px; }
  .chip { display: inline-block; min-width: 40px; text-align: center; padding: 1px 6px; border-radius: 3px;
          font-weight: 600; font-size: 11px; }
  .l-DETECTS { background: var(--good); color: #fff; } .l-PARTIAL { background: var(--warn); color: #0b0b0b; }
  .l-BLIND { background: var(--crit); color: #fff; } .l-INSUFFICIENT_N { background: var(--insuff); color: var(--ink2); }
  .l-NA_BLIND_BY_CONSTRUCTION, .l-NOT_RUN { border: 1px solid var(--axis); color: var(--ink2); }
  .art { color: var(--crit); font-weight: 600; }
  tr.k td:first-child { box-shadow: inset 3px 0 0 var(--accent); }
"""

TABLE_JS = r"""
(function(){
  var tb = document.getElementById('rt'); if (!tb) return;
  var rows = Array.prototype.slice.call(tb.tBodies[0].rows);
  var f = {det: document.getElementById('f-det'), unit: document.getElementById('f-unit'),
           att: document.getElementById('f-att'), lab: document.getElementById('f-lab'),
           cls: document.getElementById('f-cls'), kept: document.getElementById('f-kept'),
           q: document.getElementById('f-q')};
  var cnt = document.getElementById('f-count');
  function t(r, i){ return r.cells[i].textContent; }
  function apply(){
    var n = 0, q = (f.q.value || '').toLowerCase();
    rows.forEach(function(r){
      var ok = (!f.det.value || t(r, 0) === f.det.value) && (!f.unit.value || t(r, 1) === f.unit.value) &&
        (!f.cls.value || t(r, 3) === f.cls.value) && (!f.att.value || t(r, 4) === f.att.value) &&
        (!f.lab.value || r.cells[6].dataset.f === f.lab.value) && (!f.kept.checked || r.classList.contains('k')) &&
        (!q || r.textContent.toLowerCase().indexOf(q) >= 0);
      r.hidden = !ok; if (ok) n++;
    });
    cnt.textContent = n + ' of ' + rows.length + ' cells shown';
  }
  Object.keys(f).forEach(function(k){ f[k].addEventListener(k === 'q' ? 'input' : 'change', apply); });
  var dir = {};
  Array.prototype.forEach.call(tb.tHead.rows[0].cells, function(th, i){
    th.addEventListener('click', function(){
      var num = th.dataset.num === '1';
      dir[i] = dir[i] === undefined ? !num : !dir[i];     // numbers sort descending first
      function v(r){ var c = r.cells[i]; var s = c.dataset.v !== undefined ? c.dataset.v : c.textContent;
                     if (!num) return s; s = parseFloat(s); return isNaN(s) ? -1 : s; }
      rows.sort(function(a, b){ var x = v(a), y = v(b); return (x < y ? -1 : x > y ? 1 : 0) * (dir[i] ? 1 : -1); });
      rows.forEach(function(r){ tb.tBodies[0].appendChild(r); });
    });
  });
  apply();
})();
"""


def _ci(lo, hi) -> str:
    return "" if lo is None or hi is None else f"{_fmt_p(lo)}–{_fmt_p(hi)}"


def recall_table_html(report: dict) -> str:
    """One self-contained HTML page: the focused figure, then every recall cell of the report in a filterable,
    sortable table. The table is rendered server-side, so it reads without JS; JS adds filters and sorting."""
    R = report.get("recall") or {}
    names = report.get("check_names") or {}
    cls_of = report.get("attack_class") or ATTACK_CLASS
    focus = set(_focus(report))
    recs = []
    for chk in R:
        for attack, by_p in R[chk].items():
            for param, by_u in by_p.items():
                for unit, raw in by_u.items():
                    c = _norm_recall_cell(raw, _cell_label_of(report, chk, attack, param, unit))
                    recs.append((chk, unit, attack, param, c))
    recs.sort(key=lambda r: ((r[0], r[1]) not in focus, r[0], r[1], cls_of.get(r[2], "edit") != "exec",
                             _attack_key(r[2]), _param_key(r[3])))
    lab_counts = Counter(r[4].get("label") for r in recs)

    def opts(vals):
        return "".join(f'<option value="{_e(v)}">{_e(v)}</option>' for v in vals)

    dets = sorted({r[0] for r in recs})
    units = sorted({r[1] for r in recs})
    atts = sorted({r[2] for r in recs}, key=_attack_key)
    labs = sorted({r[4].get("label") or "" for r in recs}, key=lambda s: -LABEL_RANK.get(s, -1))
    body = []
    for chk, unit, attack, param, c in recs:          # end tags omitted (valid HTML5) to keep the page small
        label = c.get("label") or ""
        cls = cls_of.get(attack, "edit")
        artifact = cls == "exec" and label in ("DETECTS", "PARTIAL") and not _credited(report, chk, attack)
        art = ' <span class="art" title="edit artifact (DA13)">^</span>' if artifact else ""
        rk = f"{_fmt_int(c.get('k'))}/{_fmt_int(c.get('n'))}" if c.get("k") is not None else ""
        fk = f"{_fmt_int(c.get('fpr_k'))}/{_fmt_int(c.get('fpr_n'))}" if c.get("fpr_k") is not None else ""
        src = str(c.get("source") or "").split(" cells.")[0]
        tip = f' title="{_e(names[chk])}"' if chk in names else ""
        kept = " class=k" if (chk, unit) in focus else ""
        body.append(
            f'<tr{kept}><td{tip}>{_e(chk)}<td>{_e(unit)}'
            f'<td>{_e(c.get("split", ""))}<td>{cls}<td>{_e(attack)}<td>{_e(param)}'
            f'<td data-v={LABEL_RANK.get(label, -1)} data-f="{_e(label)}"><b class="chip l-{_e(label)}">'
            f'{_e(label or "—")}</b>{art}'
            f'<td class=num>{_fmt_p(c.get("p"))}<td class=num>{rk}<td class=num>{_ci(c.get("lo"), c.get("hi"))}'
            f'<td class=num>{_fmt_p(c.get("fpr_p"))}<td class=num>{fk}'
            f'<td class=num>{_ci(c.get("fpr_lo"), c.get("fpr_hi"))}<td class=num>{_fmt_p(c.get("adr"))}'
            f'<td class=src>{_e(src)}')
    heads = [("detector", 0), ("unit", 0), ("split", 0), ("class", 0), ("attack", 0), ("param", 0),
             ("label", 1), ("recall", 1), ("k/n", 0), ("recall 95% CI", 0), ("honest", 1), ("k/n", 0),
             ("honest 95% CI", 0), ("ADR", 1), ("file", 0)]
    thead = "".join(f'<th data-num="{n}" scope="col">{_e(h)}</th>' for h, n in heads)
    summary = ", ".join(f"{k} {v}" for k, v in sorted(lab_counts.items(), key=lambda kv: -LABEL_RANK.get(kv[0], -1)))
    src = "".join(f"<li><code>{_e(s)}</code></li>" for s in _sources_lines(report, "recall"))
    notes = "".join(f"<li>{_e(n)}</li>" for n in _notes(report, "recall"))
    mapping = ", ".join(f"{k} → {v}" for k, v in sorted(names.items()))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recall per attack</title><style>{HTML_CSS}</style></head>
<body><main>
<h1>Recall per attack</h1>
<p>Every N7 attack cell of the report ({len(recs)} cells: {_e(summary)}). Recall is the share of tampered sessions
flagged; "honest" is the flag rate of the same sessions untampered; ADR is Track A's attributable detection rate.
Execution-path attacks model a compromised tool path; record-editing attacks model someone editing a finished log
(DESIGN.md §5.4). <strong>All tampering is synthetic.</strong> These are Track A probe numbers: the verifier inherits
one only after a parity test reproduces it (DESIGN.md DA15).</p>
<h2>The kept checks in their claimed units</h2>
<div class="fig">{recall_per_attack_svg(report)}</div>
<h2>Every cell</h2>
<p>Each row is the cell <code>cells."&lt;unit&gt;|&lt;split&gt;|&lt;detector&gt;|&lt;attack&gt;|&lt;param&gt;"</code> of the
file in the last column. Rows with a blue edge are a kept check in its claimed unit. Detector → verifier check:
{_e(mapping) or "n/a"}.</p>
<div class="filters">
 <label>detector <select id="f-det"><option value="">all</option>{opts(dets)}</select></label>
 <label>unit <select id="f-unit"><option value="">all</option>{opts(units)}</select></label>
 <label>attack <select id="f-att"><option value="">all</option>{opts(atts)}</select></label>
 <label>class <select id="f-cls"><option value="">all</option>{opts(["exec", "edit"])}</select></label>
 <label>label <select id="f-lab"><option value="">all</option>{opts(labs)}</select></label>
 <label><input type="checkbox" id="f-kept"> kept checks in claimed units only</label>
 <label>search <input type="search" id="f-q" placeholder="text"></label>
 <span class="count" id="f-count">{len(recs)} cells</span>
</div>
<div class="tablewrap"><table id="rt"><thead><tr>{thead}</tr></thead><tbody>
{chr(10).join(body)}
</tbody></table></div>
<h2>Notes and sources</h2>
<ul>{notes}</ul>
<p>Sources (LF-normalised sha256 prefix; committed status at generation time):</p><ul>{src}</ul>
<p>^ = a DETECTS/PARTIAL cell in an execution-path attack by a check without execution credit: the battery left a
dependent field unrepaired that a real shim would keep consistent, so it is an edit artifact (DESIGN.md DA13).
Generated by <code>verifier/figures.py</code>.</p>
</main><script>{TABLE_JS}</script></body></html>
"""


# --------------------------------------------------------------------------------------------------------- writing
def write_figures(report: dict, out_dir: str | Path = DEFAULT_OUT) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = {}
    outputs = {"transfer_matrix.svg": transfer_matrix_svg(report) if report.get("transfer") else None,
               "recall_per_attack.svg": recall_per_attack_svg(report) if report.get("recall") else None,
               "recall_per_attack.html": recall_table_html(report) if report.get("recall") else None}
    for name, text in outputs.items():
        if text is None:
            continue
        p = out_dir / name
        p.write_text(text, encoding="utf-8", newline="\n")
        produced[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {"generated_by": "verifier/figures.py", "generator_sha256_lf": sha256_lf(Path(__file__)),
                "inputs": (report.get("provenance") or {}).get("files", []),
                "kind": (report.get("provenance") or {}).get("kind"),
                "notes": (report.get("provenance") or {}).get("notes", []), "outputs_sha256": produced}
    (out_dir / "figures_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                                                    encoding="utf-8", newline="\n")
    return produced


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m verifier.figures", description=__doc__.split("\n")[0])
    ap.add_argument("--report", help="an eval report JSON (eval/run_eval.py); default: assemble from Track A outputs")
    ap.add_argument("--track-a", default=str(DEFAULT_TRACK_A), help="Track A output dir (default analysis/out/phase_e)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output dir (default analysis/out/phase_e/figures)")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    rep = load_report(a.report) if a.report else report_from_track_a(a.track_a)
    produced = write_figures(rep, a.out)
    for name, sha in produced.items():
        print(f"wrote {Path(a.out) / name}  sha256 {sha[:16]}")
    for f in (rep.get("provenance") or {}).get("files", []):
        if f.get("committed") is not True:
            print(f"warning: input {f['path']} is not committed (committed={f.get('committed')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
