"""Phase E figures: the N6 transfer matrix and the N7 recall-per-attack grid.

Run from the worktree root (after phase_e_n6):  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_figures

Reads only committed Phase E outputs: analysis/out/phase_e/n6_grid.json, n7_timing.json, n7_content.json.
Always writes the plotting data to analysis/out/phase_e/fig_data.json (labels and numbers copied from those files,
nothing new is computed except the 'best cell' selection rule stated below). If matplotlib is importable it also
writes fig_transfer_matrix.png and fig_n7_recall.png; otherwise it writes the data only and says so.

N7 grid selection rule (stated, mechanical): for each detector x attack, the cells considered are the replication
split of each unit (E where the unit has E, B for cc_local / aiv_cc / whowhen), every parameter value. The shown cell
is the best by label (DETECTS > PARTIAL > BLIND > INSUFFICIENT_N > NA_BLIND_BY_CONSTRUCTION > NOT_RUN), ties broken by
recall point estimate. Its recall point and unit are printed in the cell; every considered cell is in fig_data.json.
Colors: the dataviz reference status palette (good / warning / critical) plus neutral grays; every cell also carries
a text label, so color never carries the verdict alone.
"""
import json
from pathlib import Path

from analysis.probes import prereg_e_common as pe

OUT_E = pe.OUT_E
NO_E = ("cc_local", "aiv_cc", "whowhen")
SURFACE, INK, INK2 = "#fcfcfb", "#0b0b0b", "#52514e"
GRID_COLOR = {"ALIVE": "#0ca30c", "WEAK": "#fab219", "DEAD": "#d03b3b", "INSUFFICIENT_N": "#e2e1dc",
              "INCONCLUSIVE": "#e2e1dc", "NOT_TESTABLE": "#9b9a95", "NOT_RUN": SURFACE, "PER_STRATUM": "#4a3aa7"}
GRID_TEXT = {"ALIVE": "#ffffff", "WEAK": INK, "DEAD": "#ffffff", "INSUFFICIENT_N": INK2, "INCONCLUSIVE": INK2,
             "NOT_TESTABLE": "#ffffff", "NOT_RUN": INK2, "PER_STRATUM": "#ffffff"}
CODE = {"ALIVE": "ALIVE", "WEAK": "WEAK", "DEAD": "DEAD", "INSUFFICIENT_N": "ins-n", "INCONCLUSIVE": "inconc",
        "NOT_TESTABLE": "n/t", "NOT_RUN": "n/r", "PER_STRATUM": "strata"}
N7_RANK = {"DETECTS": 5, "PARTIAL": 4, "BLIND": 3, "INSUFFICIENT_N": 2, "NA_BLIND_BY_CONSTRUCTION": 1, "NOT_RUN": 0}
N7_COLOR = {"DETECTS": "#0ca30c", "PARTIAL": "#fab219", "BLIND": "#d03b3b", "INSUFFICIENT_N": "#e2e1dc",
            "NA_BLIND_BY_CONSTRUCTION": SURFACE, "NOT_RUN": SURFACE, None: SURFACE}
N7_TEXT = {"DETECTS": "#ffffff", "PARTIAL": INK, "BLIND": "#ffffff", "INSUFFICIENT_N": INK2,
           "NA_BLIND_BY_CONSTRUCTION": INK2, "NOT_RUN": INK2, None: INK2}
N7_CODE = {"DETECTS": "D", "PARTIAL": "P", "BLIND": "B", "INSUFFICIENT_N": "n<30", "NA_BLIND_BY_CONSTRUCTION": "na",
           "NOT_RUN": "n/r", None: ""}
UNIT_ABBR = {"swechat/claude_code": "CC", "swechat/codex": "cdx", "swechat/opencode": "oc", "swechat/gemini": "gem",
             "swechat/cursor": "cur", "cc_local": "ccl", "aiv_cc": "avc", "aiv_cu": "avu", "whowhen": "ww"}


def load(name):
    return json.loads((OUT_E / name).read_text(encoding="utf-8"))


def recall_p(c):
    r = c.get("recall")
    if isinstance(r, dict):
        return r.get("p")
    if isinstance(r, (list, tuple)) and r:
        return r[0]
    return None


def n7_cells():
    out = []
    for src in ("n7_timing.json", "n7_content.json"):
        d = load(src)
        for key, c in d["cells"].items():
            u, s = c["unit"], c["split"]
            repl = "B" if u in NO_E else "E"
            if s != repl:
                continue
            out.append({"key": key, "source": src, "unit": u, "split": s, "detector": c["detector"],
                        "attack": c["attack"], "param": c["param"], "label": c["label"], "recall_p": recall_p(c)})
    return out


def best_n7(cells):
    best = {}
    for c in cells:
        k = (c["detector"], c["attack"])
        sc = (N7_RANK.get(c["label"], -1), c["recall_p"] if c["recall_p"] is not None else -1)
        if k not in best or sc > best[k][0]:
            best[k] = (sc, c)
    return {k: v[1] for k, v in best.items()}


def main():
    G = load("n6_grid.json")
    rows, cols = G["rows"], G["columns_loaded"]
    grid_data = [[{"row": r, "col": c, "base": G["cells"][r][c]["base"], "label": G["cells"][r][c]["label"],
                   "suffix": G["cells"][r][c].get("suffix", "")} for c in cols] for r in rows]
    cells = n7_cells()
    best = best_n7(cells)
    attacks = sorted({c["attack"] for c in cells})
    det_order = ["R1_BRACKET", "P1_FLOOR", "P1_GEN", "N1", "N3", "N5g", "N4", "R3_GIT", "N2", "N5a", "N5b", "N5c",
                 "N5d", "N5f", "P2_KFN", "P3_ZERO", "R2_IMAGE", "R4_DUAL", "R5_LEDGER"]
    dets = [d for d in det_order if any(c["detector"] == d for c in cells)] + sorted(
        {c["detector"] for c in cells} - set(det_order))
    att_order = ["time_result_early", "time_result_late", "time_tail_early", "time_tail_late", "time_response_early",
                 "time_response_late", "id_swap_adjacent", "id_splice_foreign", "sub_single_flip_error",
                 "sub_single_digit", "sub_matched_bytes", "rewrite_consistent_k", "reorder_adjacent_pairs",
                 "reorder_lines", "delete_pair", "delete_response", "insert_pair_consistent", "insert_pair_squeezed",
                 "inline_fabrication", "image_relabel_gui", "image_insert_screenshot"]
    atts = [a for a in att_order if a in attacks] + sorted(set(attacks) - set(att_order))
    uncomputed = {"not_applicable": [[a, d] for a in atts for d in dets if (d, a) not in best
                                      and not pe.applicable(a, d)],
                  "applicable_no_cell": [[a, d] for a in atts for d in dets if (d, a) not in best
                                         and pe.applicable(a, d)]}
    n7_data = [[(lambda b: None if b is None else {k: b[k] for k in ("key", "source", "unit", "split", "label",
                                                                       "recall_p", "param")})(best.get((d, a)))
                for d in dets] for a in atts]
    data = {"script": "analysis/probes/phase_e_figures.py",
            "inputs": ["analysis/out/phase_e/n6_grid.json", "analysis/out/phase_e/n7_timing.json",
                       "analysis/out/phase_e/n7_content.json"],
            "transfer_matrix": {"rows": rows, "columns": cols, "cells": grid_data},
            "n7_recall": {"rule": "per detector x attack: best label over the replication split of each unit (E, or B "
                                  "for units without E) and every parameter; ties by recall point",
                          "attacks": atts, "detectors": dets, "best_cells": n7_data,
                          "cells_considered": len(cells), "pairs_without_a_cell": uncomputed,
                          "label_counts_considered": {lab: sum(1 for c in cells if c["label"] == lab)
                                                      for lab in sorted({c["label"] for c in cells})}},
            "matplotlib": None}
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        data["matplotlib"] = matplotlib.__version__
    except ImportError:
        plt = None
    if plt is not None:
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8})
        # ---- transfer matrix
        fig, ax = plt.subplots(figsize=(16, 9.2), dpi=150)
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)
        for i, r in enumerate(rows):
            for j, c in enumerate(cols):
                cl = G["cells"][r][c]
                b = cl["base"]
                ax.add_patch(Rectangle((j + 0.04, i + 0.04), 0.92, 0.92, facecolor=GRID_COLOR[b],
                                       edgecolor="#d6d5d0" if b == "NOT_RUN" else "none", linewidth=0.6,
                                       hatch="////" if b == "NOT_RUN" else None))
                txt = CODE[b]
                if b == "PER_STRATUM":
                    sc = cl.get("stratum_counts", {})
                    txt = f"{sc.get('ALIVE', 0)}A/{sc.get('WEAK', 0)}W/{sc.get('DEAD', 0)}D"
                sfx = cl.get("suffix") or ""
                marks = ("ᴮ" if "B only" in sfx else "") + ("*" if ("not blind" in sfx.lower() or "NOT_BLIND" in sfx)
                                                             else "")
                ax.text(j + 0.5, i + 0.5, txt + marks, ha="center", va="center", fontsize=6.6,
                        color=GRID_TEXT[b], fontweight="bold" if b in ("ALIVE", "WEAK", "DEAD") else "normal")
        ax.set_xlim(0, len(cols))
        ax.set_ylim(len(rows), 0)
        ax.set_xticks([j + 0.5 for j in range(len(cols))])
        ax.set_xticklabels(cols, rotation=40, ha="right", color=INK2)
        ax.set_yticks([i + 0.5 for i in range(len(rows))])
        ax.set_yticklabels([G["row_names"][r] for r in rows], color=INK)
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.axvline(len(G["columns_phase_b"]), color=INK2, linewidth=1.2)
        ax.text(len(G["columns_phase_b"]) / 2, -0.6, "11 Phase B units", ha="center", color=INK2, fontsize=8)
        ax.text(len(G["columns_phase_b"]) + len(G["columns_track_b"]) / 2, -0.6, "Track B corpora (own A/B/E splits)",
                ha="center", color=INK2, fontsize=8)
        t = G["transfer"]["primary"]["totals"]
        ax.set_title(f"N6 transfer grid: {t['rows']} mechanisms x {len(cols)} loaded columns. Decided {t['decided']} "
                     f"(ALIVE {t['n_ALIVE']}, WEAK {t['n_WEAK']}, DEAD {t['n_DEAD']}); decided pairs "
                     f"{t['pairs_decided']}: transfer {t['transfer_pairs']}, fail {t['failing_pairs']}",
                     loc="left", color=INK, fontsize=10, pad=26)
        fig.text(0.01, 0.01, "Cell = E verdict where the unit has E (after the pre-registered checks); ᴮ = B only; "
                             "* = not blind; n/t = NOT_TESTABLE (missing field); n/r = NOT_RUN (hatched); "
                             "ins-n = INSUFFICIENT_N. 8 acquired-but-not-loaded corpora omitted (all NOT_RUN). "
                             "Source: analysis/out/phase_e/n6_grid.json", color=INK2, fontsize=7)
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        fig.savefig(OUT_E / "fig_transfer_matrix.png", facecolor=SURFACE)
        plt.close(fig)
        # ---- n7 recall
        fig, ax = plt.subplots(figsize=(15, 9.5), dpi=150)
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)
        for i, a in enumerate(atts):
            for j, d in enumerate(dets):
                b = best.get((d, a))
                lab = b["label"] if b else None
                ax.add_patch(Rectangle((j + 0.04, i + 0.04), 0.92, 0.92, facecolor=N7_COLOR.get(lab, SURFACE),
                                       edgecolor="#d6d5d0" if lab in (None, "NA_BLIND_BY_CONSTRUCTION", "NOT_RUN")
                                       else "none", linewidth=0.5))
                if b is None:
                    na = not pe.applicable(a, d)
                    ax.text(j + 0.5, i + 0.5, "na" if na else "-", ha="center", va="center", fontsize=5.6,
                            color=INK2, style="italic")
                    continue
                txt = N7_CODE.get(lab, lab)
                if lab in ("DETECTS", "PARTIAL", "BLIND") and b["recall_p"] is not None:
                    txt = f"{N7_CODE[lab]} {b['recall_p']:.2f}\n{UNIT_ABBR.get(b['unit'], b['unit'])}"
                ax.text(j + 0.5, i + 0.5, txt, ha="center", va="center", fontsize=5.6, color=N7_TEXT.get(lab, INK2),
                        linespacing=0.95)
        ax.set_xlim(0, len(dets))
        ax.set_ylim(len(atts), 0)
        ax.set_xticks([j + 0.5 for j in range(len(dets))])
        ax.set_xticklabels(dets, rotation=40, ha="right", color=INK2)
        ax.set_yticks([i + 0.5 for i in range(len(atts))])
        ax.set_yticklabels(atts, color=INK)
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        lc = data["n7_recall"]["label_counts_considered"]
        ax.set_title("N7: best cell per detector x attack (replication split: E, or B where the unit has no E; best "
                     "over units and parameters)" + "\n" + ", ".join(f"{k} {v}" for k, v in lc.items()) +
                     f" of {len(cells)} cells considered", loc="left", color=INK, fontsize=9, pad=10)
        fig.text(0.01, 0.01, "D = DETECTS (recall >= 0.5 and recall CI lo > honest FPR CI hi); P = PARTIAL (CI lo > "
                             "FPR CI hi); B = BLIND; number = recall point of the shown cell; second line = unit "
                             "(CC swechat/claude_code, ccl cc_local, avc aiv_cc, avu aiv_cu, oc opencode, cdx codex, "
                             "gem gemini, cur cursor, ww whowhen). na = blind by construction (italic na: no cell computed, "
                             "prereg_e_common.applicable() is False); italic - = applicable but no cell computed. "
                             "All tampering is "
                             "synthetic. Sources: n7_timing.json, n7_content.json", color=INK2, fontsize=6.6, wrap=True)
        fig.tight_layout(rect=(0, 0.035, 1, 1))
        fig.savefig(OUT_E / "fig_n7_recall.png", facecolor=SURFACE)
        plt.close(fig)
    (OUT_E / "fig_data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print("matplotlib", data["matplotlib"], "- wrote fig_data.json" +
          (", fig_transfer_matrix.png, fig_n7_recall.png" if plt is not None else " only (no matplotlib)"))


if __name__ == "__main__":
    main()
