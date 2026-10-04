"""Command line (DESIGN.md §6.1).

    python -m verifier.cli [verify] PATH [PATH ...] [--format F] [--session ID] [--unit U] [--checks NAMES]
                           [--show constrained|contradicted|all] [--explain CALL_ID] [--min-confidence X]
                           [--json OUT.jsonl] [--html OUT.html] [--max-chars N] [--no-color] [--strict]
                           [--allow-unpublishable] [--sidecar FILE.json]
    python -m verifier.cli checks [--json]
    python -m verifier.cli inspect PATH [--format F] [--session ID] [--unit U] [--json]
    python -m verifier.cli render VERDICTS.jsonl [--source PATH] --html OUT.html [--max-chars N] [--allow-unpublishable]
    python -m verifier.cli census --corpus C --split {A,B,E} [--limit N] --out OUT.parquet   (needs verifier.loaders)
    python -m verifier.cli demo --input DIR [--out demo/index.html]                           (needs verifier.render)

`python -m verifier ...` needs a one-line verifier/__main__.py (`from verifier.cli import main; raise SystemExit(main())`),
which is outside this scaffold's owned paths.

verify exit codes: 0 no call contradicted; 1 >= 1 contradicted; 2 input/parse error (unknown format, empty session,
unknown check); 3 a check exception or contract violation under --strict. Without --strict, check exceptions become
'error:' verdicts, a warning line counts them, and the exit code follows the verdicts.

HTML: verifier.render.html.render_session_html is used when it exists; until then a basic built-in page is written
(same safety rules: cc_local never rendered, non-publishable corpora only with --allow-unpublishable, every displayed
string redacted, then escaped).
"""
from __future__ import annotations

import argparse
import html as _html
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

SUBCOMMANDS = ("verify", "checks", "inspect", "render", "census", "demo")
PUBLISHABLE = frozenset({"swechat", "tbench2", "pub_trace_commons", "glm_tb21"})     # §6.3
KNOWN_CORPORA = frozenset({"swechat", "tbench2", "glm_tb21", "pub_cc_hf", "pub_trace_commons", "pub_codex", "agentcap",
                           "aiv_cu", "aiv_cc", "cc_local", "whowhen"})
PRIVATE = frozenset({"cc_local"})                                                     # never rendered, never excerpted
ID_LAYOUT_NOTE = "provider clock inferred from an undocumented id layout"
SYNTHETIC_NOTE = "Synthetic tamper. This tool has not detected a natural fabrication in any corpus we hold."
COLORS = {"contradicted": "\x1b[31;1m", "supported": "\x1b[32m", "unconstrained": "\x1b[2m", "reset": "\x1b[0m"}


class CliError(Exception):
    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


# ------------------------------------------------------------------------------------------------------- helpers
def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _redactor() -> Callable[[Optional[str]], Optional[str]]:
    try:
        from analysis.loaders.newcorp_common import redact
        return redact
    except Exception:  # noqa: BLE001 - redaction source unavailable: fall back to identity, loudly
        print("warning: analysis.loaders.newcorp_common.redact unavailable; excerpts are NOT redacted", file=sys.stderr)
        return lambda s: s


def _excerpt(s: Any, n: int, redact: Callable) -> str:
    if s is None:
        return ""
    s = str(s)
    s = redact(s) or ""
    s = s.replace("\r", " ").replace("\n", " ↵ ")
    return s if len(s) <= n else s[: max(n - 1, 0)] + f"… [{len(s)} chars]"


def _explain(cv: Any) -> str:
    from verifier.registry import REGISTRY
    cls = REGISTRY.get(cv.check)
    if cls is None:
        return cv.reason
    try:
        return cls().explain(cv)
    except Exception as e:  # noqa: BLE001 - display only
        return f"{cv.reason} (explain() failed: {type(e).__name__})"


def _hhmmss(ts: Any) -> str:
    if not isinstance(ts, str) or "T" not in ts:
        return "-"
    t = ts.split("T", 1)[1].rstrip("Z")
    return t[:12]


def _cal_label(session: Any, borrowed: bool) -> str:
    if session.calibration_unit is None:
        return "calibration: none (statistical checks abstain)"
    how = "borrowed by format" if (session.source or {}).get("format") not in ("ir", "turns") else "borrowed: D1 proxy"
    return f"calibration: {session.calibration_unit}" + (f" ({how})" if borrowed else "")


def _load_sidecar(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CliError(f"--sidecar {path}: {e}") from None


def _load(paths: Sequence[str], args: argparse.Namespace, sidecar: Optional[dict] = None) -> list[tuple[Any, bool]]:
    from verifier import load_sessions
    out = []
    for p in paths:
        if not Path(p).exists():
            raise CliError(f"{p}: no such file")
        try:
            out.extend(load_sessions(p, fmt=args.format, unit=args.unit, session_id=getattr(args, "session", None),
                                     sidecar=sidecar))
        except (ValueError, PermissionError, OSError, KeyError) as e:
            raise CliError(f"{p}: {e}") from None
    if not out:
        raise CliError("no sessions in input")
    return out


def _session_json(session: Any, verdicts: list, stats: Any, borrowed: bool) -> dict:
    from verifier.checks.base import checkset_sha, verdict_version
    from verifier.compose import summarize
    return {"session_id": session.session_id, "corpus": session.corpus, "unit": session.unit,
            "source": session.source, "n_calls": len(session.call_keys), "n_events": len(session.events),
            "capabilities": sorted(session.capabilities), "checks_run": stats.checks_run(),
            "counts": summarize(verdicts), "orphans": {"n": len(session.orphans), "seqs": list(session.orphans)},
            "calibration_unit": session.calibration_unit, "calibration_borrowed": borrowed,
            "id_layout_unrecognized": session.id_layout["id_layout_unrecognized"],
            "version": verdicts[0].version if verdicts else verdict_version(checkset_sha(stats.version))}


def _write_jsonl(out: str, results: list) -> None:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for _, verdicts, _, _ in results:
            for v in verdicts:
                f.write(json.dumps(v.to_dict(), ensure_ascii=False) + "\n")
    sj = [_session_json(s, v, st, b) for s, v, st, b in results]
    sp = p.with_name(p.name[: -len(".jsonl")] + ".session.json") if p.name.endswith(".jsonl") else \
        p.with_name(p.name + ".session.json")
    sp.write_text(json.dumps(sj[0] if len(sj) == 1 else sj, ensure_ascii=False, indent=1, sort_keys=True),
                  encoding="utf-8", newline="\n")
    print(f"wrote {p} and {sp}")


# ------------------------------------------------------------------------------------------------ terminal output
def _print_session(session: Any, verdicts: list, stats: Any, borrowed: bool, args: argparse.Namespace,
                   redact: Callable) -> None:
    from verifier.compose import apply_min_confidence, summarize
    color = (not args.no_color) and sys.stdout.isatty()

    def c(status: str, s: str) -> str:
        return f"{COLORS[status]}{s}{COLORS['reset']}" if color else s

    n = args.max_chars or 100
    private = session.corpus in PRIVATE
    fmt = session.source.get("format") or "?"
    print(f"session {session.session_id}  {session.corpus}:{fmt}  unit {session.unit}  {len(session.call_keys)} calls  "
          f"{_cal_label(session, borrowed)}")
    print("capabilities: " + (" ".join(sorted(session.capabilities)) or "(none)"))
    if stats.status:
        print("checks: " + "  ".join(f"{k} {stats.version[k]} ({stats.status[k]}"
                                     f"{':' + stats.reason[k] if stats.reason.get(k) else ''})" for k in sorted(stats.status)))
    else:
        print("checks: none enabled (ENABLED_CHECKS is empty until the morning gate; --checks all runs the reference check)")
    if session.id_layout["id_layout_unrecognized"]:
        print("note: every req_-shaped request id failed the layout gate (id_layout_unrecognized); lost coverage, not a detection")
    pairs = session.pairs.set_index("call_key")
    ts = session.events["ts"].tolist()
    print(f"{'seq':>5}  {'time':<12}  {'tool':<8}  {'call':<30}  {'verdict':<16}  {'by':<22}  reason")
    hidden_rest: Counter = Counter()
    for v, hidden in apply_min_confidence(verdicts, args.min_confidence):
        shown = "unconstrained" if hidden else v.verdict
        if (args.show == "contradicted" and shown != "contradicted") or \
                (args.show == "constrained" and shown == "unconstrained"):
            hidden_rest["below_display_threshold" if hidden else v.reason] += 1
            continue
        row = pairs.loc[v.call_key]
        call = "[private corpus]" if private else _excerpt(row["command"] or row["args"], 30, redact)
        label = ("unconstrained (below display threshold)" if hidden else
                 (v.verdict.upper() if v.verdict == "contradicted" else v.verdict) + (" !" if v.disagreement else ""))
        conf = f" (conf {v.confidence:.3f})" if v.confidence is not None else ""
        core = ("  core " + " ".join(f"#{s}" for s in v.core)) if v.core and v.verdict == "contradicted" else ""
        print(f"{v.seq:>5}  {_hhmmss(ts[v.seq]):<12}  {str(v.tool or '-')[:8]:<8}  {call[:30]:<30}  "
              f"{c(v.verdict if not hidden else 'unconstrained', f'{label:<16}')}  {str(v.rule or '-'):<22}  "
              f"{v.reason} ({v.strength}){conf}{core}")
        if v.rule and not hidden:
            d = next(cv for cv in v.checks if cv.check == v.rule)
            print(f"        \"{_excerpt(_explain(d), n * 3, redact)}\"")
        if v.disagreement:
            others = [f"{cv.check} ({cv.verdict})" for cv in v.checks if cv.verdict == "supported"]
            print("        also supported by " + ", ".join(others) + "   <- disagreement")
    cnt = summarize(verdicts)
    unc = Counter(v.reason for v in verdicts if v.verdict == "unconstrained")
    print(f"summary: {len(verdicts)} calls | contradicted {cnt['contradicted_localized'] + cnt['contradicted_unit']} "
          f"(localized {cnt['contradicted_localized']}, unit-level {cnt['contradicted_unit']}) | supported "
          f"{cnt['supported']} | unconstrained {cnt['unconstrained']}"
          + (" (" + ", ".join(f"{r} {k}" for r, k in sorted(unc.items(), key=lambda x: (-x[1], x[0]))) + ")" if unc else ""))
    if hidden_rest and args.show != "all":
        print(f"not shown (--show {args.show}): " + ", ".join(f"{r} {k}" for r, k in sorted(hidden_rest.items())))
    print(f"orphan results: {len(session.orphans)}")
    if any(v.rule == "id_bracket" for v in verdicts):
        print(f"note: {ID_LAYOUT_NOTE}")


def _print_explain(session: Any, verdicts: list, call_id: str, redact: Callable) -> bool:
    hits = [v for v in verdicts if call_id in (v.call_id, v.call_key)]
    for v in hits:
        print(f"\ncall {v.call_key} (call_id {v.call_id}) seq {v.seq} result_seq {v.result_seq} tool {v.tool}")
        print(f"  composed: {v.verdict} strength={v.strength} rule={v.rule} reason={v.reason} conf={v.confidence} "
              f"core={list(v.core)} blame_seq={v.blame_seq} localized={v.localized} disagreement={v.disagreement}")
        for cv in v.checks:
            print(f"  - {cv.check} {cv.check_version}: {cv.verdict} {cv.reason} conf={cv.confidence} "
                  f"strength={cv.strength} unit={cv.unit_kind}:{cv.unit_id} localized={cv.localized}")
            if cv.detail:
                print(f"      detail: {json.dumps(cv.detail, ensure_ascii=False, sort_keys=True)[:400]}")
            for r in cv.evidence:
                val = "[private corpus]" if session.corpus in PRIVATE else _excerpt(r.value, 120, redact)
                print(f"      evidence #{r.seq} {r.role} {r.field}: {val}")
            print(f"      {_excerpt(_explain(cv), 300, redact)}")
    return bool(hits)


# --------------------------------------------------------------------------------------------------------- HTML
def _check_renderable(session: Any, allow_unpublishable: bool) -> None:
    corpus = getattr(session, "corpus", None)
    if corpus in PRIVATE:
        raise CliError(f"{corpus} is private: it is never rendered (DESIGN §6.3)")
    if corpus in KNOWN_CORPORA and corpus not in PUBLISHABLE:
        if not allow_unpublishable:
            raise CliError(f"{corpus} is not publishable; pass --allow-unpublishable to render it to a LOCAL file")
        print(f"warning: rendering non-publishable corpus {corpus} to a local file; do not publish it", file=sys.stderr)


_CSS = """:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--line:#e2e1dc;--sup:#1f7a4d;--con:#b3261e;--unc:#8a8a84;--chip:#f0efea}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#1b1b1a;--fg:#ecebe6;--muted:#a3a29c;--line:#34332f;--sup:#5cc191;--con:#ff7b72;--unc:#8f8e88;--chip:#2a2926}}
:root[data-theme="dark"]{--bg:#1b1b1a;--fg:#ecebe6;--muted:#a3a29c;--line:#34332f;--sup:#5cc191;--con:#ff7b72;--unc:#8f8e88;--chip:#2a2926}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:16px;max-width:1200px}
h1{font-size:18px;margin:0 0 4px}.muted{color:var(--muted)}.chip{display:inline-block;background:var(--chip);border-radius:10px;padding:1px 8px;margin:2px;font-size:12px}
.bar{display:flex;height:10px;border-radius:5px;overflow:hidden;margin:10px 0;background:var(--line)}.bar span{display:block}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
.v{font-weight:600;white-space:nowrap}.supported{color:var(--sup)}.contradicted{color:var(--con)}.unconstrained{color:var(--unc)}
.ev{font-size:12px;color:var(--muted)}code{font-size:12px;word-break:break-all}footer{margin-top:16px;font-size:12px;color:var(--muted)}
.wrap{overflow-x:auto}"""


def _basic_html(session: Any, verdicts: list, title: str, max_chars: int, redact: Callable) -> str:
    """Built-in fallback page (until verifier.render.html exists): no JS, no network, every string redacted+escaped."""
    from verifier.compose import summarize
    e = lambda s: _html.escape(str(s) if s is not None else "")  # noqa: E731
    cnt = summarize(verdicts)
    n = max(len(verdicts), 1)
    shares = [("supported", cnt["supported"]), ("contradicted", cnt["contradicted_localized"] + cnt["contradicted_unit"]),
              ("unconstrained", cnt["unconstrained"])]
    bar = "".join(f'<span style="width:{100.0 * k / n:.2f}%;background:var(--{s[:3]})" title="{s} {k}"></span>'
                  for s, k in shares if k)
    pairs = session.pairs.set_index("call_key") if session is not None else None
    ts = session.events["ts"].tolist() if session is not None else None
    rows = []
    for v in verdicts:
        if pairs is not None and v.call_key in pairs.index:
            r = pairs.loc[v.call_key]
            call, res = _excerpt(r["command"] or r["args"], max_chars, redact), _excerpt(r["text"], max_chars, redact)
            t = _hhmmss(ts[v.seq])
        else:
            call, res, t = "", "", "-"
        ev = ""
        if v.rule:
            d = next(cv for cv in v.checks if cv.check == v.rule)
            # without the source session the corpus is unknown, so evidence values (record content) are omitted
            refs = " ".join(f"#{x.seq} {x.role} {x.field or ''}"
                            + (f"={_excerpt(x.value, 80, redact)}" if session is not None else "") for x in d.evidence)
            ev = f'<div class="ev">{e(_excerpt(_explain(d), 400, redact))}<br><code>{e(refs)}</code></div>'
        rows.append(f'<tr><td>{v.seq}</td><td>{e(t)}</td><td>{e(v.tool or "-")}</td><td><code>{e(call)}</code></td>'
                    f'<td><code>{e(res)}</code></td><td class="v {v.verdict}">{e(v.verdict)}{" !" if v.disagreement else ""}'
                    f'</td><td>{e(v.rule or "-")}</td><td>{e(v.reason)}{ev}</td></tr>')
    caps = "".join(f'<span class="chip">{e(c)}</span>' for c in sorted(session.capabilities)) if session else ""
    sid = verdicts[0].session_id if verdicts else (session.session_id if session else "?")
    head = (f"{e(session.corpus)} · unit {e(session.unit)} · calibration {e(session.calibration_unit or 'none')}"
            if session is not None else "events not loaded (render without --source)")
    notes = []
    if any(v.rule == "id_bracket" for v in verdicts):
        notes.append(ID_LAYOUT_NOTE.capitalize() + ".")
    if verdicts and all(v.reason in ("abstain:reference_only", "abstain:no_enabled_checks") for v in verdicts):
        notes.append("No detection check decided any call (reference check only, or no check enabled).")
    version = verdicts[0].version if verdicts else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{e(title)}</title><style>{_CSS}</style></head><body>'
            f'<h1>{e(title)}</h1><div class="muted">session {e(sid)} · {head} · {len(verdicts)} calls</div>'
            f'<div>{caps}</div><div class="bar">{bar}</div><div class="muted">supported {shares[0][1]} · contradicted '
            f'{shares[1][1]} · unconstrained {shares[2][1]}</div><div class="wrap"><table><thead><tr><th>seq</th>'
            f'<th>time</th><th>tool</th><th>call</th><th>result</th><th>verdict</th><th>by</th><th>reason / evidence'
            f'</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div><footer>{e(version)}<br>'
            f'{"<br>".join(e(x) for x in notes)}<br>"supported" means consistent with the fields the deciding check reads, '
            f'nothing more. Basic page written by verifier.cli (verifier.render.html not available).</footer>'
            f'</body></html>')


def _render_html(session: Any, verdicts: list, out: Path, *, title: str, max_chars: int, allow_unpublishable: bool,
                 redact: Callable) -> None:
    if session is not None:
        _check_renderable(session, allow_unpublishable)
    page = None
    if session is not None:
        try:
            from verifier.render.html import render_session_html  # type: ignore
        except ImportError:
            render_session_html = None
        if render_session_html is not None:
            import inspect
            kw = {"title": title, "max_chars": max_chars}
            if "allow_unpublishable" in inspect.signature(render_session_html).parameters:
                kw["allow_unpublishable"] = allow_unpublishable
            page = render_session_html(session, verdicts, **kw)
    if page is None:
        page = _basic_html(session, verdicts, title, max_chars, redact)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {out}")


def _html_targets(out: str, sids: list[str]) -> list[Path]:
    p = Path(out)
    if len(sids) == 1:
        return [p]
    safe = lambda s: "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in s)[:80]  # noqa: E731
    return [p.with_name(f"{p.stem}__{safe(s)}{p.suffix or '.html'}") for s in sids]


# --------------------------------------------------------------------------------------------------------- commands
def cmd_verify(args: argparse.Namespace) -> int:
    from verifier import run_session
    from verifier.registry import resolve_names
    try:
        names = resolve_names(args.checks)
    except KeyError as e:
        raise CliError(str(e).strip('"')) from None
    loaded = _load(args.paths, args, _load_sidecar(args.sidecar))
    redact = _redactor()
    results = []
    for s, borrowed in loaded:
        try:
            verdicts, stats = run_session(s, names, strict=args.strict)
        except Exception as e:  # noqa: BLE001 - only reachable under --strict
            print(f"error: {s.session_id}: check raised {type(e).__name__}: {e}", file=sys.stderr)
            return 3
        results.append((s, verdicts, stats, borrowed))
    n_err = sum(sum(st.errors.values()) for _, _, st, _ in results)
    for i, (s, verdicts, stats, borrowed) in enumerate(results):
        if i:
            print()
        _print_session(s, verdicts, stats, borrowed, args, redact)
        if args.explain:
            _print_explain(s, verdicts, args.explain, redact)
    if args.explain and not any(args.explain in (v.call_id, v.call_key) for _, vs, _, _ in results for v in vs):
        print(f"--explain {args.explain}: no such call_id or call_key", file=sys.stderr)
    if n_err:
        print(f"warning: {n_err} check exception(s) became error: verdicts (rerun with --strict to raise)",
              file=sys.stderr)
    if args.json:
        _write_jsonl(args.json, results)
    if args.html:
        targets = _html_targets(args.html, [s.session_id for s, _, _, _ in results])
        for (s, verdicts, _, _), out in zip(results, targets):
            _render_html(s, verdicts, out, title=f"verifier: {s.session_id}", max_chars=args.max_chars or 2000,
                         allow_unpublishable=args.allow_unpublishable, redact=redact)
    any_contra = any(v.verdict == "contradicted" for _, vs, _, _ in results for v in vs)
    return 1 if any_contra else 0


def cmd_checks(args: argparse.Namespace) -> int:
    from verifier.registry import ENABLED_CHECKS, describe
    rows = describe()
    if args.json:
        print(json.dumps(rows, indent=1, sort_keys=True))
        return 0
    for r in rows:
        print(f"{r['name']:<26} {r['check_version']:<22} {r['kind']:<11} {r['strength']:<6} unit={r['unit_kind']:<8} "
              f"enabled={'yes' if r['enabled'] else 'no'}")
        print(f"    requires={','.join(r['requires']) or '-'} reads={','.join(r['reads']) or '-'} "
              f"targets={','.join(r['targets']) or '-'} calibrated_units={','.join(r['calibrated_units']) or '-'}")
    print(f"ENABLED_CHECKS = {tuple(ENABLED_CHECKS)!r}")
    return 0


def _inspect_status(session: Any, cls: type) -> str:
    from verifier.checks.base import calib_for
    missing = sorted(c for c in cls.requires if not session.has_capability(c))
    if missing:
        return f"missing:{missing[0]}"
    try:
        if not cls().applicable(session):
            return "not_applicable"
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}"
    if cls.kind == "statistical":
        cal = calib_for(cls, session.calibration_unit, session.stratum)
        if cal is None:
            return "uncalibrated"
        if cal.get("enabled") is False:
            return "unit_not_enabled"
    return "applicable"


def cmd_inspect(args: argparse.Namespace) -> int:
    from verifier.registry import describe, get_check
    loaded = _load([args.path], args)
    out = []
    for s, borrowed in loaded:
        out.append({"session_id": s.session_id, "corpus": s.corpus, "unit": s.unit,
                    "calibration_unit": s.calibration_unit, "calibration_borrowed": borrowed,
                    "n_events": len(s.events), "n_calls": len(s.call_keys), "n_orphan_results": len(s.orphans),
                    "capabilities": sorted(s.capabilities), "id_layout": s.id_layout,
                    "checks": {r["name"]: _inspect_status(s, get_check(r["name"])) for r in describe()}})
    if args.json:
        print(json.dumps(out if len(out) > 1 else out[0], indent=1, sort_keys=True))
        return 0
    for o in out:
        print(f"session {o['session_id']}  {o['corpus']}  unit {o['unit']}  calibration {o['calibration_unit']}"
              f"{' (borrowed by format)' if o['calibration_borrowed'] else ''}")
        print(f"  events {o['n_events']}  calls {o['n_calls']}  orphan results {o['n_orphan_results']}  "
              f"id layout {o['id_layout']}")
        print("  capabilities: " + (" ".join(o["capabilities"]) or "(none)"))
        for k, st in sorted(o["checks"].items()):
            print(f"  {k:<26} {st}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    from verifier.checks.base import Verdict
    from verifier.registry import load_checks
    load_checks()
    p = Path(args.verdicts)
    if not p.is_file():
        raise CliError(f"{p}: no such file")
    try:
        verdicts = [Verdict.from_dict(json.loads(line)) for line in p.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
    except (ValueError, KeyError, TypeError) as e:
        raise CliError(f"{p}: not a verdicts JSONL ({e})") from None
    by_sid: dict[str, list] = {}
    for v in verdicts:
        by_sid.setdefault(v.session_id, []).append(v)
    if not by_sid:
        raise CliError(f"{p}: no verdicts")
    sessions: dict[str, Any] = {}
    if args.source:
        args.session = None
        for s, _ in _load([args.source], args):
            sessions[s.session_id] = s
        absent = sorted(set(by_sid) - set(sessions))
        if absent:
            print(f"warning: {len(absent)} session(s) not in --source; rendered without events: {absent[:3]}",
                  file=sys.stderr)
    redact = _redactor()
    sids = sorted(by_sid)
    for sid, out in zip(sids, _html_targets(args.html, sids)):
        s = sessions.get(sid)
        vs = sorted(by_sid[sid], key=lambda v: v.seq)
        _render_html(s, vs, out, title=f"verifier: {sid}", max_chars=args.max_chars or 2000,
                     allow_unpublishable=args.allow_unpublishable, redact=redact)
    return 0


def cmd_census(args: argparse.Namespace) -> int:
    """Per-call verdicts of one corpus split (A/B/E; H is refused by argparse and by the adapter) to parquet.
    cc_local writes aggregates only (counts per check and reason), never rows."""
    try:
        from verifier.loaders.corpora import CORPUS_ADAPTERS  # type: ignore
    except ImportError:
        raise CliError("census needs verifier.loaders.corpora (CORPUS_ADAPTERS), which is not built yet") from None
    import pandas as pd
    from verifier import run_session
    from verifier.registry import resolve_names
    if args.corpus not in CORPUS_ADAPTERS:
        raise CliError(f"unknown corpus {args.corpus!r}; known: {sorted(CORPUS_ADAPTERS)}")
    import inspect
    from verifier.checks.base import D1_PROXY_UNIT
    names = resolve_names(args.checks)
    adapter = CORPUS_ADAPTERS[args.corpus]
    params = inspect.signature(adapter.iter_sessions).parameters
    kw: dict = {}
    if "calibration_unit_of" in params:   # census calibrates every unit as itself or its pre-registered D1 proxy
        kw["calibration_unit_of"] = lambda u: D1_PROXY_UNIT.get(u, u)
    if "with_sidecar" in params:
        kw["with_sidecar"] = True
    rows, agg = [], Counter()
    for i, s in enumerate(adapter.iter_sessions(args.split, **kw)):
        if args.limit and i >= args.limit:
            break
        verdicts, _ = run_session(s, names)
        for v in verdicts:
            if args.corpus in PRIVATE:
                for cv in v.checks:
                    agg[(cv.check, cv.reason)] += 1
                agg[("composed", v.reason)] += 1
                continue
            rows.append({"session_id": v.session_id, "call_id": v.call_id, "call_key": v.call_key, "seq": v.seq,
                         "tool": v.tool, "verdict": v.verdict, "strength": v.strength, "confidence": v.confidence,
                         "rule": v.rule, "reason": v.reason, "localized": v.localized, "disagreement": v.disagreement,
                         "version": v.version, "checks_json": json.dumps([cv.to_dict() for cv in v.checks])})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.corpus in PRIVATE:
        df = pd.DataFrame([{"check": k[0], "reason": k[1], "n": n} for k, n in sorted(agg.items())])
    else:
        df = pd.DataFrame(rows)
    df.to_parquet(out, index=False)
    print(f"wrote {out} ({len(df)} rows)")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    try:
        from verifier.render.demo import build_demo  # type: ignore
    except ImportError:
        raise CliError("demo needs verifier.render.demo, which is not built yet") from None
    build_demo(input_dir=args.input, out=args.out)
    return 0


# ----------------------------------------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m verifier", description="Witness-free verification of tool-log results.")
    sub = ap.add_subparsers(dest="cmd")

    def common_input(p: argparse.ArgumentParser) -> None:
        p.add_argument("--format", default="auto",
                       choices=["auto", "claude_code", "codex", "opencode", "gemini", "atif", "ir", "turns"])
        p.add_argument("--session", default=None, help="only this session (IR parquet or multi-session input)")
        p.add_argument("--unit", default=None, help="calibration unit (default: borrowed by format)")

    v = sub.add_parser("verify", help="verify transcripts (default subcommand)")
    v.add_argument("paths", nargs="+")
    common_input(v)
    v.add_argument("--checks", default="enabled", help="comma list | 'enabled' (default) | 'all' (adds reference checks)")
    v.add_argument("--show", default="constrained", choices=["constrained", "contradicted", "all"])
    v.add_argument("--explain", default=None, metavar="CALL_ID")
    v.add_argument("--min-confidence", type=float, default=None, help="display-only threshold")
    v.add_argument("--json", default=None, metavar="OUT.jsonl")
    v.add_argument("--html", default=None, metavar="OUT.html")
    v.add_argument("--max-chars", type=int, default=None)
    v.add_argument("--no-color", action="store_true")
    v.add_argument("--strict", action="store_true")
    v.add_argument("--allow-unpublishable", action="store_true")
    v.add_argument("--sidecar", default=None, metavar="FILE.json")
    v.set_defaults(func=cmd_verify)

    c = sub.add_parser("checks", help="list registered checks")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_checks)

    i = sub.add_parser("inspect", help="capabilities and per-check applicability")
    i.add_argument("path")
    common_input(i)
    i.add_argument("--json", action="store_true")
    i.set_defaults(func=cmd_inspect)

    r = sub.add_parser("render", help="render a verdicts JSONL to a static HTML page")
    r.add_argument("verdicts")
    r.add_argument("--source", default=None, help="the transcript the verdicts came from (events for the page)")
    r.add_argument("--html", required=True, metavar="OUT.html")
    r.add_argument("--format", default="auto",
                   choices=["auto", "claude_code", "codex", "opencode", "gemini", "atif", "ir", "turns"])
    r.add_argument("--unit", default=None)
    r.add_argument("--max-chars", type=int, default=None)
    r.add_argument("--allow-unpublishable", action="store_true")
    r.set_defaults(func=cmd_render)

    k = sub.add_parser("census", help="per-call verdicts of one corpus split (A, B or E) to parquet")
    k.add_argument("--corpus", required=True)
    k.add_argument("--split", required=True, choices=["A", "B", "E"])
    k.add_argument("--limit", type=int, default=None)
    k.add_argument("--procs", type=int, default=1, help="accepted for interface compatibility; runs sequentially")
    k.add_argument("--checks", default="enabled")
    k.add_argument("--out", required=True)
    k.set_defaults(func=cmd_census)

    d = sub.add_parser("demo", help="render the demo pages from heldout.py demo-input files")
    d.add_argument("--input", default="demo/input")
    d.add_argument("--out", default="demo/index.html")
    d.set_defaults(func=cmd_demo)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    _utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help"):
        argv = ["verify"] + argv
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    try:
        return int(args.func(args))
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    raise SystemExit(main())
