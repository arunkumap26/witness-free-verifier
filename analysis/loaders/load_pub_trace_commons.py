"""Loader: C:/Swarms/data/acquired/cli-trace-commons (HF trace-commons/agent-traces @112ebd4d, CC BY 4.0) -> corpus
`pub_trace_commons`.

Run from the worktree root:
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_pub_trace_commons            # population, splits, A cache
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_pub_trace_commons --split B  # NEXT step only (B or E cache)

Every mapping rule shared with pub_cc_hf (files, session unit, field audit, split rule, ENTRY -> IR mapping, ordering,
dedupe, secret redaction, --split) is in analysis/loaders/pub_cc_common.py's docstring; this docstring adds what is
specific to this corpus.

SOURCE  CORPUS_INVENTORY.md 2.1 and 5.10 (Track B task B5e). Sessions were donated with the donate-trace skill and
  scrubbed by the contributor before upload (README); contents keep their contributors' own licences.
FILES   only trace-commons__agent-traces@112ebd4d/sessions/claude_code/*.jsonl (28 raw Claude Code session files).
  Not read:
    data/train-00000-of-00001.parquet  its `trace` column holds full copies of the same sessions (CORPUS_INVENTORY
                                       5.10: read sessions/ or the parquet, never both); sessions/ is the source of truth
    sessions/cursor/*.jsonl            Cursor export (role/message lines, no tool results): not Claude Code format
    sessions/opencode/*.json           1 OpenCode session with 3 websearch calls: another harness; out of scope for a
                                       Claude Code corpus (load_swechat.parse_opencode could read it, deliberately not
                                       used so the corpus stays one harness)
STRATUM  modal message.model of the session's assistant entries ('<synthetic>' excluded), top 8 + 'other'. The task
  fixed the stratum only for pub_cc_hf; this corpus is one source repo, so the IR's other stratum meaning
  (provider-model family) is used.
SPLIT SIZE  N is small (28 files before the audit), so A = floor(0.2 N) is about 5 and the per-cell floor of 5 cannot
  hold; pub_cc_common's FLOOR RULE lowers it (floor_used in the sample files). Every B/E statistic on this corpus will
  be small-n.
SECRETS  the upstream scrubber already replaced many values (README: scrub.py + TruffleHog), but JSON "secret"-style
  fields remain in some files; every match of pub_cc_common.SECRET_RX is redacted at load. Per-split counts and the
  post-redaction re-scan are in out/phase_e/newcorp_build_pub_trace_commons.json (A_redactions).
"""
import sys

from analysis.loaders import pub_cc_common

CORPUS = "pub_trace_commons"


def main(argv=None):
    pub_cc_common.main(CORPUS, argv)


if __name__ == "__main__":
    main(sys.argv[1:])
