"""Traceability audit of analysis/MORNING_BRIEF.md: phase_e_trace.py, re-pointed at one document.

phase_e_trace.py runs at import and hard-codes its documents and output, so this wrapper reads its source, substitutes
five definitions (each must occur exactly once, or the run stops), and executes it. Every extraction, matching, chance,
co-location, citation and mechanical-check rule is the unchanged phase_e_trace.py code.

Substitutions (the reasons are logged in analysis/out/phase_e/audit_log.json, entry MB1)
  DOCS            analysis/MORNING_BRIEF.md, whole file; no default cited file (the brief names its sources per section).
  OUT_REL         analysis/out/phase_e/trace_brief.json.
  EXCLUDE_FILES   adds trace_brief.json (this output) and phase_e/scaffold_check.json (Track C, still being written).
  EXCLUDE_DIR     phase_e/figures/ and phase_e/demo/ (Track C, still being written; they may copy brief numbers).
                  phase_e/track_b/ is NOT excluded here: it is committed (93532fb) and the brief cites it in sections
                  4 and 5, so it is primary evidence for this document.
  secondary set   as phase_e_trace.py (prereg files, PREREG_E.md, notes/phase_e_*.md) plus the committed write-ups the
                  brief copies from (PRIOR_ART.md, CORPUS_INVENTORY.md, DESIGN.md, SECOND_PASS.md, DECISION_TABLE.md,
                  TRANSFER_MATRIX.md, FINDINGS.md). A number found only there is traced to a write-up, not to an
                  analysis/out file; the audit log says which.

Run:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_trace_brief
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(HERE, "phase_e_trace.py")

SUBS = [
    ('OUT_REL = "analysis/out/phase_e/trace.json"',
     'OUT_REL = "analysis/out/phase_e/trace_brief.json"'),
    ('''DOCS = [
    {"name": "SECOND_PASS", "path": "analysis/SECOND_PASS.md", "start": None,
     "default_files": ["analysis/out/phase_e/second_pass.json"]},
    {"name": "TRANSFER_MATRIX", "path": "analysis/TRANSFER_MATRIX.md", "start": None,
     "default_files": ["analysis/out/phase_e/n6_grid.json"]},
    {"name": "DECISION_TABLE_phase_e", "path": "analysis/DECISION_TABLE.md", "start": "## Phase E update",
     "default_files": ["analysis/out/phase_e/n6_grid.json"]},
]''',
     '''DOCS = [
    {"name": "MORNING_BRIEF", "path": "analysis/MORNING_BRIEF.md", "start": None, "default_files": []},
]'''),
    ('''EXCLUDE_FILES = {"analysis/out/phase_d/trace.json", "analysis/out/phase_d/audit_log.json",
                 "analysis/out/phase_e/trace.json", "analysis/out/phase_e/audit_log.json"}
EXCLUDE_DIR_PREFIX = ("analysis/out/phase_e/track_b/",)''',
     '''EXCLUDE_FILES = {"analysis/out/phase_d/trace.json", "analysis/out/phase_d/audit_log.json",
                 "analysis/out/phase_e/trace.json", "analysis/out/phase_e/audit_log.json",
                 "analysis/out/phase_e/trace_brief.json", "analysis/out/phase_e/scaffold_check.json"}
EXCLUDE_DIR_PREFIX = ("analysis/out/phase_e/figures/", "analysis/out/phase_e/demo/")'''),
    ('''                 + [p for p in all_out_json if p.startswith(EXCLUDE_DIR_PREFIX)])''',
     '''                 + ["analysis/PRIOR_ART.md", "analysis/CORPUS_INVENTORY.md", "analysis/DESIGN.md",
                    "analysis/SECOND_PASS.md", "analysis/DECISION_TABLE.md", "analysis/TRANSFER_MATRIX.md",
                    "analysis/FINDINGS.md"])'''),
    ('''    "script": "analysis/probes/phase_e_trace.py",''',
     '''    "script": "analysis/probes/phase_e_trace_brief.py (runs analysis/probes/phase_e_trace.py with 5 substitutions)",'''),
    ('''    "primary_set": {"description": "analysis/out/**/*.json on disk, minus audit outputs and phase_e/track_b",''',
     '''    "primary_set": {"description": "analysis/out/**/*.json on disk, minus audit outputs and the in-flight Track C outputs (phase_e/figures, phase_e/demo, phase_e/scaffold_check.json); phase_e/track_b included",'''),
]

with open(SRC_PATH, "r", encoding="utf-8") as f:
    src = f.read()
for old, new in SUBS:
    n = src.count(old)
    if n != 1:
        raise SystemExit(f"substitution target found {n} times (expected 1): {old[:80]!r}")
    src = src.replace(old, new)

g = {"__name__": "__main__", "__file__": SRC_PATH}
exec(compile(src, SRC_PATH, "exec"), g)
