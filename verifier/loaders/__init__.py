"""verifier.loaders: raw files and IR caches -> `Session`s (DESIGN.md §2.1, §2.5, §2.7).

  detect.py        sniff(path) -> Format                                   (input format of one file)
  files.py         load_file(path, fmt) -> list[Session]                   (one transcript; the CLI entry point)
  corpora.py       CORPUS_ADAPTERS[c].iter_sessions(split)                 (IR caches, splits A/B/E only)
  units.py         unit_of(corpus, session_id, stratum, fmt); DEFAULT_CALIBRATION_BY_FORMAT
  sidecar.py       read_cc_numlines, read_entire_tally, copied_request_ids (harness records the IR drops)
  capabilities.py  python -m verifier.loaders.capabilities -> capabilities.json (which IR fields each corpus fills)

Import rule (§2.2, §5.1): only `verify_file` and the CLI import this package, never `verify_session`, because it
pulls in `analysis.loaders.*`. May import: analysis.loaders.*, analysis.lib.cc_jsonl, verifier.ir, verifier.session,
pyarrow. Must not import: checks, eval, analysis.probes.
"""
from verifier.loaders.corpora import (CORPUS_ADAPTERS, PRIVATE_CORPORA, PUBLISHABLE, READABLE_SPLITS,  # noqa: F401
                                      CorpusAdapter, get_adapter, iter_sessions, public_corpora)
from verifier.loaders.detect import CLI_FORMATS, FILE_FORMATS, Format, sniff  # noqa: F401
from verifier.loaders.files import LoadedSession, LoadError, load_events, load_file  # noqa: F401
from verifier.loaders.units import (D1_PROXY_UNIT, DEFAULT_CALIBRATION_BY_FORMAT, PHASE_E_UNITS,  # noqa: F401
                                    reporting_stratum, unit_of)

__all__ = ["CORPUS_ADAPTERS", "PRIVATE_CORPORA", "PUBLISHABLE", "READABLE_SPLITS", "CorpusAdapter", "get_adapter",
           "iter_sessions", "public_corpora", "CLI_FORMATS", "FILE_FORMATS", "Format", "sniff", "LoadedSession",
           "LoadError", "load_events", "load_file", "D1_PROXY_UNIT", "DEFAULT_CALIBRATION_BY_FORMAT", "PHASE_E_UNITS",
           "reporting_stratum", "unit_of"]
