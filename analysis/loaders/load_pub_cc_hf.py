"""Loader: C:/Swarms/data/acquired/cli-claude-code-hf (12 pinned HF repos of raw Claude Code JSONL) -> corpus `pub_cc_hf`.

Run from the worktree root:
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_pub_cc_hf            # population, splits, A cache, selftest
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_pub_cc_hf --split B  # NEXT step only (B or E cache)

Every mapping rule shared with pub_trace_commons (files, session unit, field audit, split rule, ENTRY -> IR mapping,
ordering, dedupe, secret redaction, --split) is in analysis/loaders/pub_cc_common.py's docstring; this docstring adds
what is specific to this corpus.

SOURCE  CORPUS_INVENTORY.md 2.1 and 5.11 (Track B task B5e). Folders <owner>__<repo>@<sha8>, each a pinned HF repo:
  AlinCiocan/fable-5-claude-code-traces, INONONO/tarkov-customs-trajectory, armand0e/claude-fable-5-claude-code (MIT),
  build-small-hackathon/kirana-detective-build-traces, cfahlgren1/Fable-5-traces (AGPL-3.0), crispwisp/wisp-claude-code-
  sessions, naazimsnh02/tutordesk-agent-traces, thomwolf/am-session-claude-code-1-a66490, thomwolf/am-session-claude-
  code-1-c3cc0a, thomwolf/am-session-sharing-design, victor/claude-worldcup-2026-wallchart-traces, yellowbeeblackbee/
  claude-traces. Licences per repo (MIT, Apache-2.0, CC BY 4.0, CC0, AGPL-3.0).
FILES   every *.jsonl except .cache/ and the 2 crispwisp workflow journal.jsonl files. Not read: naazimsnh02
  runtime_traces/*.parquet (application LLM traces with columns agent/system/user/output/ts, not Claude Code), victor's
  .js file, thomwolf meta/*.json|md, READMEs and manifests.
REQUEST IDS  absent in INONONO and victor, partial in AlinCiocan (CORPUS_INVENTORY 1.1); those sessions stay in the
  corpus (the field audit is timestamps + call/result join, not request ids), so request-id fill is < 1 by repo.
STRATUM  source repo of the session's root file, label '<owner>__<repo>' (pin dropped); top 8 repos by passing-session
  count kept, the rest 'other' (the task's rule). A session copied into two repos takes the root's repo: the 29
  armand0e/cfahlgren1 copies start at the same timestamp, so the tie goes to the lexicographically first path
  (armand0e).
DEDUPE  armand0e and cfahlgren1 overlap (29 sessions, 2,576 request ids; CORPUS_INVENTORY 5.0): merged into one session
  per sessionId/uuid and collapsed onto the root copy (pub_cc_common SESSION / ORDERING AND DEDUPLICATION). Resume
  chains inside armand0e and crispwisp are merged the same way.
  The two uploads are NOT byte-identical (out/phase_e/newcorp_build_pub_cc_hf.json population.copies): 3,406 copied
  entries differ between the kept armand0e copy and the dropped cfahlgren1 copy, in message (1,914), message and
  toolUseResult (1,154), toolUseResult (192) or attachment (145); where the message differs, the kept armand0e message
  is the longer one in 3,036 of 3,068. Only key names and lengths were compared, never values. Read: the cfahlgren1
  upload rewrote (shortened) tokens. The root rule keeps the armand0e bytes, the longer and presumably original
  version. Resume-chain copies differ only in slug (crispwisp, 149) or gitBranch (armand0e, 138), plus 4 crispwisp
  entries.
SUBAGENT TIMING  workflow agents (crispwisp, victor) run after their parent Workflow call has returned (async launch):
  every A subagent event with a parent_call_id is stamped after the parent call's result (build_stats_full.subagent).
  victor's 50 workflow agents and 2 subagents have no parent call in the data (its main file has no toolUseResult).
SECRETS  credential-like values occur in these uploads (bearer tokens in curl commands, API-key and token env
  assignments, some of them placeholders); every match of pub_cc_common.SECRET_RX is replaced by
  '<REDACTED:<pattern>>' at load time. Per-split counts by field and pattern, and a re-scan of the built frame that
  must find no unredacted match, are in out/phase_e/newcorp_build_pub_cc_hf.json (A_redactions). The two files that
  mention CLAUDE_CODE_OAUTH_TOKEN name the variable only (CORPUS_INVENTORY 2.4).
MODELS  model strings include non-Claude names (qwen-fable5, Mini-Fable-5) and '<synthetic>'; kept raw in `model`.
"""
import sys

from analysis.loaders import pub_cc_common

CORPUS = "pub_cc_hf"


def main(argv=None):
    pub_cc_common.main(CORPUS, argv)


if __name__ == "__main__":
    main(sys.argv[1:])
