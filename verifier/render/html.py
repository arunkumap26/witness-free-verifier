"""Static HTML session page: a transcript whose per-call verdicts light up, with the deciding evidence inline
(DESIGN.md §6.2; demo rules §6.3, DA9).

    render_session_html(session, verdicts, *, title, compare=None, baseline_existence=True, max_chars=2000,
                        allow_unpublishable=False) -> str

`session` is a `verifier.session.Session` (DESIGN.md §4.2) and `verdicts` its `list[Verdict]` (§3.3). Both are read
by attribute *or* by key, so verdicts read back from `verdicts.jsonl` (plain dicts) render the same way. `compare`
is `(tampered_session, tampered_verdicts, tamper_dict)`; the tamper dict carries the eval's `Tamper` fields as plain
JSON (`verifier` never imports `eval`), plus any of the optional demo-input keys `class`, `cell_recall_loc`,
`honest_fpr`, `honest_session_cost`, `track_a_reference`, `why_this_session`, which are printed when present.
`allow_unpublishable` is an addition to the DESIGN.md §6.2 signature: it carries the CLI's `--allow-unpublishable`.

Rules this module enforces (DESIGN.md §6.2, §6.3):
- One self-contained file: inline CSS, inline JS (vanilla; it adds only the toggle, the scan animation and the
  evidence arcs), inline SVG. No network request, no dependency outside the standard library. The page is rendered
  server-side, so it reads with JS disabled.
- Every displayed string passes through `analysis.loaders.newcorp_common.redact` (credential patterns), then
  `html.escape`; excerpts longer than `max_chars` are cut with `… [N chars]`. If the redactor cannot be imported, the
  page is not rendered.
- `cc_local` is never rendered. Any session whose source split is H is never rendered. A corpus outside PUBLISHABLE
  (and outside the user-input kinds `file` / `turns`) renders only with `allow_unpublishable=True`, with a banner.
- Reference checks are shown but never decide (DESIGN.md §4.6, §4.8): their chips light up in the per-check row.

Demo (no eval needed yet; DESIGN.md §6.3 builds the tampered pages once `eval/heldout.py demo-input` exists):
    PYTHONIOENCODING=utf-8 python -m verifier.render.html demo            # -> analysis/out/phase_e/demo/index.html
It picks one session of split E of a redistributable corpus by a rule fixed in DEMO_SELECTION_RULE, runs the
reference check through the verifier pipeline when it is importable, and otherwise through a clearly labelled
stand-in of the DESIGN.md §4.8 rule (the page and demo_meta.json say which).

Location note: DESIGN.md §2.1 puts this file at verifier/render/html.py (here) and the demo builder in
verifier/render/demo.py; the reference-only demo builder lives here until demo.py and heldout.py demo-input exist.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import html as _html
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

PUBLISHABLE = frozenset({"swechat", "tbench2", "pub_trace_commons", "glm_tb21"})   # DESIGN.md §6.3 (licences)
NEVER_RENDER = frozenset({"cc_local"})                                              # private: aggregates only
USER_INPUT_CORPORA = frozenset({"file", "turns"})                                   # the user's own transcript
GATED_NOTE = {"swechat": "SWE-chat is gated on Hugging Face. This page is built locally and is not for publication "
                         "until a human confirms the gate terms allow a derivative (DESIGN.md §6.3; open item 8)."}
CHIP_CAPS = (("ts.ms", "ms clocks"), ("request_id.decodable", "request ids"), ("usage.io", "usage"),
             ("join.call_id", "call↔result join"), ("sidecar.cc_numlines", "dual render"),
             ("sidecar.entire_tally", "session tally"))
NO_NATURAL = "Synthetic tamper. This tool has not detected a natural fabrication in any corpus we hold."
CLASS_SENTENCE = {"edit": "Threat class: record editing (someone edited a finished log).",
                  "exec": "Threat class: execution path (the model wrote the tool result itself, or a shim did)."}
ID_LAYOUT_NOTE = "Provider clock inferred from an undocumented id layout."
EXCERPT = 240                         # characters shown on the card face; the full text (<= max_chars) expands
EXCERPT_LINES = 5                     # lines shown on the card face


class RenderRefused(ValueError):
    """The session may not be rendered (private corpus, held-out split, or not publishable without the flag)."""


# ------------------------------------------------------------------------------------------------- generic access
def _get(o, name, default=None):
    if o is None:
        return default
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)


def _isnull(v) -> bool:
    if v is None:
        return True
    if type(v).__name__ in ("NAType", "NaTType"):
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return False


def _clean(v):
    return None if _isnull(v) else v


def _event_rows(session) -> list[dict]:
    ev = _get(session, "events")
    if ev is None:
        return []
    rows = ev.to_dict("records") if hasattr(ev, "to_dict") else list(ev)
    out = [{k: _clean(v) for k, v in r.items()} for r in rows]
    out.sort(key=lambda r: int(r["seq"]))
    return out


_REDACT = None


def _redactor():
    global _REDACT
    if _REDACT is None:
        try:
            from analysis.loaders.newcorp_common import redact
        except ImportError as exc:            # never render unredacted text
            raise RenderRefused("credential redactor analysis.loaders.newcorp_common.redact is not importable "
                                "(DESIGN.md §2.4 fallback: vendor it to verifier/render/_redact.py)") from exc
        _REDACT = redact
    return _REDACT


def _txt(s, max_chars: int) -> str:
    """redact -> cut -> escape (the cut happens after redaction, so a cut never splits a credential pattern)."""
    if _isnull(s):
        return ""
    s = _redactor()(str(s))
    if len(s) > max_chars:
        s = s[:max_chars] + f"… [{len(s)} chars]"
    return _html.escape(s, quote=True)


def _attr(s) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def _clock(ts) -> str:
    if not ts:
        return "—"
    m = re.search(r"T(\d\d:\d\d:\d\d(?:\.\d+)?)", str(ts))
    return m.group(1) if m else str(ts)


def _family(reason: str) -> str:
    r = reason or ""
    if r == "abstain:below_threshold":
        return "screened"
    if r.startswith("missing:"):
        return "missing"
    if r.startswith("error:"):
        return "error"
    return "abstain"


# ------------------------------------------------------------------------------------------------- explanations
_EXPLAINERS: dict = {}


def _explain(cv) -> str:
    """Check.explain through the registry (DESIGN.md §2.2: render uses only Check.explain); a generic sentence built
    from reason/detail when the registry or the check is not importable."""
    name = _get(cv, "check")
    if name not in _EXPLAINERS:
        fn = None
        try:
            from verifier.registry import get_check      # imported lazily: render must not need the checks
            fn = get_check(name)().explain
        except Exception:                                # noqa: BLE001 - any failure falls back to the generic text
            fn = None
        _EXPLAINERS[name] = fn
    fn = _EXPLAINERS[name]
    if fn is not None:
        try:
            return str(fn(cv))
        except Exception:                                # noqa: BLE001
            pass
    v, reason = _get(cv, "verdict"), _get(cv, "reason") or ""
    if reason == "ok:result_joined":
        return "A result with this call's id follows the call (reference check: it proves the pipe, never decides)."
    if reason == "missing:result":
        return "No result with this call's id follows the call."
    return f"{name} says {v} ({reason})."


# ------------------------------------------------------------------------------------------------- render gate
def _check_renderable(session, allow_unpublishable: bool) -> list[str]:
    corpus = str(_get(session, "corpus") or "")
    src = _get(session, "source") or {}
    if corpus in NEVER_RENDER:
        raise RenderRefused(f"{corpus} is private and is never rendered (DESIGN.md §6.3)")
    split = str(_get(src, "split") or "")
    path = str(_get(src, "path") or "")
    if split.upper() == "H" or re.search(r"(_H\b|_H\.|heldout)", path, re.I):
        raise RenderRefused("held-out (H) sessions are never rendered (DESIGN.md §5.2, DA9)")
    banners = []
    if corpus in PUBLISHABLE or corpus in USER_INPUT_CORPORA:
        if corpus in GATED_NOTE:
            banners.append(GATED_NOTE[corpus])
        return banners
    if not allow_unpublishable:
        raise RenderRefused(f"corpus {corpus!r} is not in PUBLISHABLE {sorted(PUBLISHABLE)}; pass "
                            f"allow_unpublishable=True (CLI --allow-unpublishable) to render a LOCAL file")
    print(f"warning: rendering non-publishable corpus {corpus!r} to a local file; do not publish it", file=sys.stderr)
    banners.append(f"LOCAL ONLY: {corpus} is not a redistributable corpus. Do not publish or share this page.")
    return banners


# ------------------------------------------------------------------------------------------------- page pieces
def _verdict_chip(v, kind_of_check=None) -> str:
    """The composed verdict chip (or a per-check chip when kind_of_check is given)."""
    verdict = _get(v, "verdict") or "unconstrained"
    reason = _get(v, "reason") or ""
    disagree = bool(_get(v, "disagreement"))
    if verdict == "contradicted" and disagree:
        cls, text = "chip split", "contradicted | supported"
    elif verdict == "contradicted":
        cls, text = "chip contra", "CONTRADICTED"
    elif verdict == "supported":
        cls, text = "chip supp", "supported"
    else:
        cls, text = f"chip unc {_family(reason)}", "unconstrained"
    conf = _get(v, "confidence")
    tip = reason + (f" · conf {conf:.3f}" if isinstance(conf, (int, float)) else "")
    if kind_of_check:
        name = _get(v, "check")
        return (f'<span class="{cls} mini" title="{_attr(tip)}"><b>{_attr(name)}</b> {_attr(verdict)}'
                f'{" · " + _attr(reason) if verdict == "unconstrained" else ""}</span>')
    return f'<span class="{cls}" title="{_attr(tip)}">{text}</span>'


def _ref_links(evidence, frame: str, max_chars: int) -> str:
    out = []
    for r in evidence or ():
        seq = _get(r, "seq")
        field = _get(r, "field")
        role = _get(r, "role") or "witness"
        val = _get(r, "value")
        label = f"#{seq}" + (f" {field}" if field else "")
        val_html = f' = <code>{_txt(val, min(max_chars, 200))}</code>' if val not in (None, "") else ""
        out.append(f'<a class="ref r-{_attr(role)}" href="#{frame}-seq-{seq}" data-target="{frame}-seq-{seq}">'
                   f'<span class="role">{_attr(role)}</span> {_attr(label)}</a>{val_html}')
    return " ".join(out)


def _detail_html(detail, max_chars: int) -> str:
    if not detail:
        return ""
    if isinstance(detail, dict):
        items = []
        for k in sorted(detail):
            v = detail[k]
            sv = json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else str(v)
            items.append(f"<span class=kv><b>{_attr(k)}</b> {_txt(sv, 300)}</span>")
        return f'<div class="detail">{" ".join(items)}</div>'
    return f'<div class="detail">{_txt(detail, max_chars)}</div>'


def _evidence_strip(v, frame: str, max_chars: int, kinds: dict | None = None) -> str:
    """Under a decided card: the deciding check's explain() sentence, its detail numbers, its evidence refs."""
    verdict = _get(v, "verdict")
    if verdict not in ("supported", "contradicted"):
        return ""
    rule = _get(v, "rule")
    checks = list(_get(v, "checks") or ())
    deciding = [cv for cv in checks if _get(cv, "check") == rule and _get(cv, "verdict") == verdict]
    parts = []
    for cv in deciding[:1] + ([c for c in checks if _get(c, "verdict") == "contradicted" and c not in deciding]
                              if verdict == "contradicted" else []):
        conf = _get(cv, "confidence")
        parts.append(
            f'<div class="ev-item"><div class="explain"><b>{_attr(_get(cv, "check"))}</b> '
            f'<span class="reason">{_attr(_get(cv, "reason"))}</span>'
            f'{f" · conf {conf:.3f}" if isinstance(conf, (int, float)) else ""}'
            f' · {_attr(_get(cv, "strength"))}{"" if _get(cv, "localized", True) else " · not localized"}</div>'
            f'<p>{_txt(_explain(cv), max_chars)}</p>{_detail_html(_get(cv, "detail"), max_chars)}'
            f'<div class="refs">{_ref_links(_get(cv, "evidence"), frame, max_chars)}</div></div>')
    if verdict == "contradicted" and _get(v, "disagreement"):
        supp = [cv for cv in checks if _get(cv, "verdict") == "supported"
                and (kinds or {}).get(_get(cv, "check")) != "reference"]     # reference checks never decide
        parts.append('<div class="ev-item other"><b>Disagreement.</b> Also supported by: ' + ", ".join(
            f'{_attr(_get(c, "check"))} ({_attr(_get(c, "strength"))}'
            f'{", conf %.3f" % _get(c, "confidence") if isinstance(_get(c, "confidence"), (int, float)) else ""})'
            for c in supp) + ". A support elsewhere does not cancel an inconsistency (DESIGN.md §4.6).</div>")
    return f'<div class="evidence">{"".join(parts)}</div>'


def _checks_panel(v, frame: str, max_chars: int) -> str:
    checks = list(_get(v, "checks") or ())
    if not checks:
        return '<div class="checks none">No check ran on this call.</div>'
    lines = []
    for cv in checks:
        conf = _get(cv, "confidence")
        lines.append(
            f'<li>{_verdict_chip(cv, kind_of_check=True)} <span class="reason">{_attr(_get(cv, "reason"))}</span>'
            f'{f" · conf {conf:.3f}" if isinstance(conf, (int, float)) else ""}'
            f' <span class="ver">v{_attr(_get(cv, "check_version"))}</span>'
            f'<div class="sub">{_txt(_explain(cv), max_chars)}</div>'
            f'{_detail_html(_get(cv, "detail"), max_chars)}'
            f'{("<div class=refs>" + _ref_links(_get(cv, "evidence"), frame, max_chars) + "</div>") if _get(cv, "evidence") else ""}'
            f'</li>')
    summary = " ".join(_verdict_chip(cv, kind_of_check=True) for cv in checks)
    return (f'<details class="checks"><summary><span class="lbl">every check</span> {summary}</summary>'
            f'<ul>{"".join(lines)}</ul></details>')


def _call_line(ev: dict, max_chars: int) -> str:
    cmd = ev.get("command")
    if cmd:
        return _txt(cmd, EXCERPT)
    args = ev.get("args")
    if args:
        try:
            a = json.loads(args)
            if isinstance(a, dict):
                for key in ("file_path", "path", "pattern", "url", "query", "description", "prompt"):
                    if a.get(key):
                        return _txt(f"{key}: {a[key]}", EXCERPT)
        except (TypeError, ValueError):
            pass
        return _txt(args, EXCERPT)
    return ""


def _result_block(res: dict | None, max_chars: int) -> str:
    if res is None:
        return '<div class="result none">no result event</div>'
    text = res.get("text") or ""
    flags = []
    if res.get("native_error") is True:
        flags.append("native error")
    if res.get("exit_code") is not None:
        flags.append(f"exit {res['exit_code']}")
    flag_html = f'<span class="flag">{_attr(", ".join(flags))}</span>' if flags else ""
    lines = text.splitlines()
    face = "\n".join(lines[:EXCERPT_LINES]) + (f"\n… [{len(lines)} lines]" if len(lines) > EXCERPT_LINES else "")
    short = _txt(face, EXCERPT) if text else "<i>(empty)</i>"
    if len(text) > EXCERPT or len(lines) > EXCERPT_LINES:
        full = _txt(text, max_chars)
        body = (f'<details class="full"><summary><code class="excerpt">{short}</code></summary>'
                f'<pre>{full}</pre></details>')
    else:
        body = f'<code class="excerpt">{short}</code>'
    return (f'<div class="result" id="__RID__"><span class="rlabel">result #{res["seq"]} · '
            f'{_attr(_clock(res.get("ts")))}</span>{flag_html}{body}</div>')


def _diff_block(t_ev: dict, h_ev: dict | None, max_chars: int) -> str:
    if h_ev is None:
        return '<div class="diff"><b>inserted</b>: no counterpart in the honest record.</div>'
    rows = []
    for f in ("ts", "request_id", "api_msg_id", "usage_in", "usage_out", "tool_raw", "command", "native_error",
              "exit_code"):
        a, b = h_ev.get(f), t_ev.get(f)
        if a != b:
            rows.append(f'<tr><th>{_attr(f)}</th><td class="old">{_txt(a, 300)}</td>'
                        f'<td class="new">{_txt(b, 300)}</td></tr>')
    for f in ("text", "args"):
        a, b = h_ev.get(f) or "", t_ev.get(f) or ""
        if a != b:
            red = _redactor()
            lines = list(difflib.unified_diff(red(a).splitlines(), red(b).splitlines(), "honest", "tampered",
                                              lineterm="", n=1))[2:]
            shown, used = [], 0
            for ln in lines:
                if used > max_chars:
                    shown.append(f"… [{len(lines) - len(shown)} more diff lines]")
                    break
                used += len(ln)
                shown.append(ln)
            body = "\n".join(
                f'<span class="{"add" if ln.startswith("+") else "del" if ln.startswith("-") else "ctx"}">'
                f'{_html.escape(ln[:400])}</span>' for ln in shown)
            rows.append(f'<tr><th>{_attr(f)}</th><td colspan="2"><pre class="ldiff">{body}</pre></td></tr>')
    if not rows:
        return '<div class="diff">tampered event; no field differs from its honest counterpart.</div>'
    return ('<div class="diff"><table><thead><tr><th>field</th><th>honest</th><th>tampered</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _match_honest(t_ev: dict, honest_rows: list[dict]) -> dict | None:
    for key in ("uuid",):
        if t_ev.get(key):
            for h in honest_rows:
                if h.get(key) == t_ev[key] and h.get("kind") == t_ev.get("kind"):
                    return h
    if t_ev.get("call_id"):
        for h in honest_rows:
            if h.get("call_id") == t_ev["call_id"] and h.get("kind") == t_ev.get("kind"):
                return h
    for h in honest_rows:
        if h["seq"] == t_ev["seq"] and h.get("kind") == t_ev.get("kind"):
            return h
    return None


def _coverage(verdicts, checks_kind: dict) -> str:
    n = len(verdicts)
    if n == 0:
        return '<section class="coverage"><p>No tool calls in this session.</p></section>'
    fam = Counter()
    contra_loc = contra_unit = 0
    for v in verdicts:
        vd = _get(v, "verdict")
        if vd == "contradicted":
            if _get(v, "localized", True):
                contra_loc += 1
            else:
                contra_unit += 1
            fam["contradicted"] += 1
        elif vd == "supported":
            fam["supported"] += 1
        else:
            fam["unc:" + _family(_get(v, "reason"))] += 1
    segs = [("contradicted", "seg contra", "contradicted"), ("supported", "seg supp", "supported"),
            ("unc:screened", "seg screened", "screened, nothing found"),
            ("unc:missing", "seg missing", "record lacks the data"),
            ("unc:abstain", "seg abstain", "no rule covers it"), ("unc:error", "seg error", "check error")]
    bar = "".join(f'<span class="{c}" style="width:{100 * fam[k] / n:.3f}%" title="{_attr(t)}: {fam[k]}"></span>'
                  for k, c, t in segs if fam[k])
    legend = " ".join(f'<span class="lg"><span class="sw {c}"></span>{_attr(t)} {fam[k]}</span>'
                      for k, c, t in segs if fam[k])
    reasons = Counter(_get(v, "reason") for v in verdicts if _get(v, "verdict") == "unconstrained")
    reason_txt = ", ".join(f"{_attr(r)} {k}" for r, k in reasons.most_common(6))
    constrained = fam["supported"] + fam["contradicted"]
    # per-check coverage, reference checks included (they never decide, but they show the pipe ran)
    per = {}
    for v in verdicts:
        for cv in _get(v, "checks") or ():
            per.setdefault(_get(cv, "check"), Counter())[_get(cv, "verdict")] += 1
    per_rows = "".join(
        f'<tr><td>{_attr(c)}{" <span class=ref-tag>reference: never decides</span>" if checks_kind.get(c) == "reference" else ""}'
        f'</td><td class=num>{cnt["supported"]}</td><td class=num>{cnt["contradicted"]}</td>'
        f'<td class=num>{cnt["unconstrained"]}</td></tr>' for c, cnt in sorted(per.items()))
    per_tbl = (f'<table class="per"><thead><tr><th>check</th><th>supported</th><th>contradicted</th>'
               f'<th>unconstrained</th></tr></thead><tbody>{per_rows}</tbody></table>') if per_rows else ""
    return (f'<section class="coverage"><div class="cov-head"><b>{constrained} of {n}</b> calls constrained · '
            f'<b>{fam["contradicted"]}</b> contradicted (localized {contra_loc}, unit-level {contra_unit})</div>'
            f'<div class="bar" role="img" aria-label="coverage bar">{bar}</div><div class="legend">{legend}</div>'
            f'<div class="reasons">unconstrained by reason: {reason_txt or "—"}</div>{per_tbl}</section>')


def _frame_html(session, verdicts, frame: str, *, max_chars: int, baseline_existence: bool, kinds: dict | None = None,
                tamper: dict | None = None, honest_rows: list[dict] | None = None) -> tuple[str, dict]:
    rows = _event_rows(session)
    by_seq = {r["seq"]: r for r in rows}
    v_by_seq = {int(_get(v, "seq")): v for v in verdicts}
    result_owner = {}                                  # result seq -> call seq (from Verdict.result_seq)
    for v in verdicts:
        rs = _get(v, "result_seq")
        if rs is not None:
            result_owner[int(rs)] = int(_get(v, "seq"))
    referenced = set()
    for v in verdicts:
        referenced.update(int(s) for s in (_get(v, "core") or ()))
        for cv in _get(v, "checks") or ():
            referenced.update(int(_get(r, "seq")) for r in (_get(cv, "evidence") or ()))
    tampered = set(int(s) for s in ((tamper or {}).get("tampered_seqs") or ()))
    target_ids = set((tamper or {}).get("target_call_ids") or ())

    out = []
    for r in rows:
        seq, kind = int(r["seq"]), r.get("kind")
        diff = _diff_block(r, _match_honest(r, honest_rows or []), max_chars) if seq in tampered else ""
        if kind == "call":
            v = v_by_seq.get(seq)
            rs = _get(v, "result_seq") if v is not None else None
            res = by_seq.get(int(rs)) if rs is not None else None
            seqs = [seq] + ([int(rs)] if rs is not None else [])
            if res is not None and int(rs) in tampered:
                diff += _diff_block(res, _match_honest(res, honest_rows or []), max_chars)
            verdict = _get(v, "verdict") or "unconstrained"
            core = list(_get(v, "core") or ()) if v is not None else []
            blame = _get(v, "blame_seq")
            unit_key = ""
            if v is not None and verdict == "contradicted" and not _get(v, "localized", True):
                dec = [cv for cv in (_get(v, "checks") or ()) if _get(cv, "check") == _get(v, "rule")]
                unit_key = f'{_get(v, "rule")}:{_get(dec[0], "unit_id") if dec else ""}'
            is_target = (r.get("call_id") in target_ids) or (tamper is not None and
                                                             any(f"inserted:{r.get('call_id')}" == t for t in target_ids))
            res_html = _result_block(res, max_chars).replace("__RID__", f"{frame}-seq-{rs}") if res is not None \
                else _result_block(None, max_chars)
            exist = ('<span class="exist" title="What an existence check (OverclaimBench / Kraishan style) reports: '
                     'the call is present in the log">exists ✓</span>') if baseline_existence else ""
            chip = _verdict_chip(v) if v is not None else '<span class="chip unc abstain">no verdict</span>'
            out.append(
                f'<article class="card v-{_attr(verdict)}{" target" if is_target else ""}{" tampered" if diff else ""}" '
                f'id="{frame}-seq-{seq}" data-seqs="{" ".join(map(str, seqs))}" data-verdict="{_attr(verdict)}" '
                f'data-core="{" ".join(map(str, core))}" data-blame="{"" if blame is None else blame}" '
                f'data-unitkey="{_attr(unit_key)}">'
                f'<div class="c-head"><span class="seq">#{seq}</span><span class="time">{_attr(_clock(r.get("ts")))}'
                f'</span><span class="tool">{_attr(r.get("tool_raw") or r.get("tool") or "?")}</span>'
                f'<span class="cmd">{_call_line(r, max_chars)}</span>{exist}{chip}</div>'
                f'{res_html}{diff}{_evidence_strip(v, frame, max_chars, kinds) if v is not None else ""}'
                f'{_checks_panel(v, frame, max_chars) if v is not None else ""}</article>')
        elif kind == "result":
            if seq in result_owner:
                continue                                # shown inside its call's card
            out.append(f'<div class="ev orphan" id="{frame}-seq-{seq}" data-seqs="{seq}"><span class="seq">#{seq}</span>'
                       f'<span class="time">{_attr(_clock(r.get("ts")))}</span> orphan result (no call precedes it; '
                       f'no verdict, DESIGN.md DA7) <code>{_txt(r.get("text"), EXCERPT)}</code>{diff}</div>')
        elif kind in ("user", "assistant", "system"):
            text = r.get("text") or ""
            meta = []
            if kind == "assistant":
                if r.get("model"):
                    meta.append(str(r["model"]))
                if r.get("usage_out") is not None:
                    meta.append(f"out {r['usage_out']} tok")
                if r.get("request_id"):
                    meta.append(f"req {str(r['request_id'])[:18]}…")
            out.append(
                f'<details class="msg m-{kind}{" tampered" if diff else ""}" id="{frame}-seq-{seq}" data-seqs="{seq}"'
                f'{" open" if diff else ""}><summary><span class="seq">#{seq}</span>'
                f'<span class="time">{_attr(_clock(r.get("ts")))}</span><span class="who">{kind}</span>'
                f'<span class="mmeta">{_attr(" · ".join(meta))}</span>'
                f'<span class="first">{_txt(text, 110) if text else "<i>(no text)</i>"}</span></summary>'
                f'<pre>{_txt(text, max_chars)}</pre>{diff}</details>')
        elif seq in referenced or seq in tampered:      # meta rows appear only when evidence points at them
            bits = [f"{k}={r[k]}" for k in ("request_id", "api_msg_id", "usage_in", "usage_out") if r.get(k) is not None]
            out.append(f'<div class="ev meta" id="{frame}-seq-{seq}" data-seqs="{seq}"><span class="seq">#{seq}</span>'
                       f'<span class="time">{_attr(_clock(r.get("ts")))}</span> meta {_txt(" ".join(bits), 300)}'
                       f'{diff}</div>')
    info = {"rows": rows, "n_events": len(rows), "n_calls": sum(1 for r in rows if r.get("kind") == "call")}
    return "\n".join(out), info


def _checks_kind(verdicts) -> dict:
    kinds = {}
    try:
        from verifier.registry import load_checks
        for name, cls in load_checks().items():
            kinds[name] = getattr(cls, "kind", None)
    except Exception:                                    # noqa: BLE001 - registry absent: fall back to the name rule
        pass
    for v in verdicts:
        for cv in _get(v, "checks") or ():
            n = _get(cv, "check")
            if n not in kinds and str(n).startswith("ref_"):
                kinds[n] = "reference"
    return kinds


# ------------------------------------------------------------------------------------------------- the page
def render_session_html(session, verdicts, *, title: str, compare=None, baseline_existence: bool = True,
                        max_chars: int = 2000, allow_unpublishable: bool = False) -> str:
    banners = _check_renderable(session, allow_unpublishable)
    if compare is not None:
        banners += [b for b in _check_renderable(compare[0], allow_unpublishable) if b not in banners]
    verdicts = list(verdicts or [])
    kinds = _checks_kind(verdicts + (list(compare[1]) if compare else []))
    rows_h = _event_rows(session)

    # header facts
    corpus, unit = _get(session, "corpus"), _get(session, "unit")
    src = _get(session, "source") or {}
    caps = set(_get(session, "capabilities") or ())
    unknown = set(_get(session, "capabilities_unknown") or ())
    models = Counter(r.get("model") for r in rows_h if r.get("model"))
    model = models.most_common(1)[0][0] if models else "—"
    chips = "".join(
        f'<span class="cap {"yes" if c in caps else "unk" if c in unknown else "no"}" title="{_attr(c)}">'
        f'{_attr(label)} {"✓" if c in caps else "?" if c in unknown else "✗"}</span>' for c, label in CHIP_CAPS)
    date = next((str(r["ts"])[:10] for r in rows_h if r.get("ts")), "")
    cal = _get(session, "calibration_unit")
    cal_txt = ("none (statistical checks abstain, DESIGN.md DA4)" if not cal else
               f"{cal}{' (borrowed)' if cal != unit else ''}")
    version = next((_get(v, "version") for v in verdicts if _get(v, "version")), None) or "—"
    m = re.search(r"checks/([0-9a-f]+)", version)
    checkset = m.group(1) if m else "—"
    all_checks = sorted({_get(cv, "check") for v in verdicts for cv in (_get(v, "checks") or ())})
    ref_only = bool(all_checks) and all(kinds.get(c) == "reference" for c in all_checks)

    honest_html, info = _frame_html(session, verdicts, "h", max_chars=max_chars, kinds=kinds,
                                    baseline_existence=baseline_existence)
    frames = [("h", "Honest record", honest_html, _coverage(verdicts, kinds))]
    tamper_panel, toggle = "", ""
    tamper = None
    if compare is not None:
        t_sess, t_verdicts, tamper = compare[0], list(compare[1] or []), dict(compare[2] or {})
        t_html, t_info = _frame_html(t_sess, t_verdicts, "t", max_chars=max_chars, kinds=kinds,
                                     baseline_existence=baseline_existence, tamper=tamper, honest_rows=rows_h)
        t_rows = t_info["rows"]
        tgt_seqs = sorted(int(r["seq"]) for r in t_rows if r.get("kind") == "call" and (
            r.get("call_id") in set(tamper.get("target_call_ids") or ())))
        param = tamper.get("param")
        where = f" on call #{tgt_seqs[0]}" if tgt_seqs else ""
        t_label = (f'Tampered: {tamper.get("attack", "?")}{"" if param in (None, "", "-") else " " + str(param)}'
                   f'{where} (seed {tamper.get("seed", "?")})')
        frames.append(("t", t_label, t_html, _coverage(t_verdicts, kinds)))
        removed = len(rows_h) - len(t_rows)
        facts = []
        for k, lab in (("class", "threat class"), ("cell_recall_loc", "this cell's seed-0 hit rate"),
                       ("honest_fpr", "honest false-positive rate"), ("honest_session_cost", "honest session cost"),
                       ("track_a_reference", "Track A reference"), ("why_this_session", "why this session"),
                       ("donor_session_id", "donor session"), ("byte_delta", "byte delta"), ("clamped", "clamped")):
            if tamper.get(k) not in (None, ""):
                facts.append(f"<li><b>{_attr(lab)}</b>: {_txt(tamper[k], 600)}</li>")
        if removed > 0:
            facts.append(f"<li><b>events removed</b>: {removed} relative to the honest record</li>")
        tamper_panel = f'<section class="tamper" data-for="t"><h2>{_attr(t_label)}</h2><ul>{"".join(facts)}</ul></section>'
        toggle = ('<div class="toggle" role="group" aria-label="record shown">'
                  '<button type="button" data-show="h" aria-pressed="true">Honest record</button>'
                  f'<button type="button" data-show="t" aria-pressed="false">{_attr(t_label)}</button></div>')

    frames_html = "".join(
        f'<section class="frame" data-frame="{fid}" aria-label="{_attr(lab)}"><h2 class="ftitle">{_attr(lab)}</h2>'
        f'{cov}{tamper_panel if fid == "t" else ""}<div class="transcript"><svg class="arcs" aria-hidden="true"></svg>'
        f'<div class="scanline" aria-hidden="true"></div>{body}</div></section>'
        for fid, lab, body, cov in frames)

    foot = [f"verifier version: {version}", f"checkset sha: {checkset}", f"calibration unit: {cal_txt}",
            f"checks run: {', '.join(all_checks) or 'none'}",
            "Every displayed string passed through analysis/loaders/newcorp_common.redact, then html.escape; "
            f"excerpts over {max_chars} characters are cut."]
    if ref_only:
        foot.insert(0, "Only reference checks ran. A reference check proves the pipeline end to end and never decides a "
                       "verdict, so every composed verdict is unconstrained (DESIGN.md §4.6, §4.8). No detection check is "
                       "enabled before the morning gate (DESIGN.md §7.3, G0).")
    if any(c == "id_bracket" for c in all_checks) or (compare and any(
            _get(cv, "check") == "id_bracket" for v in compare[1] for cv in (_get(v, "checks") or ()))):
        foot.append(ID_LAYOUT_NOTE)
    if compare is not None:
        foot.append(NO_NATURAL)
        cls = (tamper or {}).get("class")
        if cls in CLASS_SENTENCE:
            foot.append(CLASS_SENTENCE[cls])
    if src:
        foot.append("source: " + ", ".join(f"{k}={src[k]}" for k in sorted(src) if src[k] not in (None, "")))
    banner_html = "".join(f'<div class="banner">{_attr(b)}</div>' for b in banners)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_attr(title)}</title><style>{PAGE_CSS}</style></head>
<body><main>
<header>
<h1>{_attr(title)}</h1>
<p class="facts"><b>{_attr(corpus)}</b> · {_attr(unit)} · format {_attr(_get(src, "format") or "—")} · model {_txt(model, 80)}
 · {info["n_calls"]} tool calls · {info["n_events"]} events · {_attr(date)} · session <code>{_attr(_get(session, "session_id"))}</code></p>
<div class="caps">{chips}</div>{banner_html}
<p class="how">Each card is one tool call. The large chip is the composed verdict; <i>every check</i> lists each
check's own verdict. Verdicts: <span class="chip supp">supported</span> a check constrained the result and it is
consistent; <span class="chip contra">CONTRADICTED</span> a check constrained it and it is not;
<span class="chip unc missing">unconstrained</span> nothing in this record tests it (hatched: the record lacks the
data; outlined: screened by a statistical check, nothing found; plain: no rule covers it).</p>
{toggle}
</header>
{frames_html}
<footer>{"".join(f"<p>{_attr(x)}</p>" for x in foot)}</footer>
</main><script>{PAGE_JS}</script></body></html>
"""


PAGE_CSS = """
:root { color-scheme: light; --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,0.10); --good:#0ca30c; --good-ink:#006300; --warn:#fab219;
  --crit:#d03b3b; --unc:#e2e1dc; --hatch:#c3c2b7; --accent:#2a78d6; --codebg:#f0efec; --add:#e3f4e3; --del:#fbe4e4; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark; --plane:#0d0d0d;
  --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --axis:#383835;
  --ring:rgba(255,255,255,0.10); --good-ink:#0ca30c; --unc:#383835; --hatch:#4a4a46; --accent:#3987e5;
  --codebg:#232321; --add:#173a17; --del:#3d1b1b; } }
:root[data-theme="dark"] { color-scheme: dark; --plane:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
  --muted:#898781; --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,0.10); --good-ink:#0ca30c; --unc:#383835;
  --hatch:#4a4a46; --accent:#3987e5; --codebg:#232321; --add:#173a17; --del:#3d1b1b; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--plane); color: var(--ink); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 20px 16px 40px; }
h1 { font-size: 21px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 18px 0 8px; }
code, pre { font: 12px/1.4 ui-monospace, "Cascadia Mono", Consolas, monospace; }
pre { white-space: pre-wrap; word-break: break-word; background: var(--codebg); padding: 8px; border-radius: 4px; margin: 6px 0; max-height: 420px; overflow: auto; }
.facts { color: var(--ink2); margin: 2px 0 8px; word-break: break-word; }
.how { color: var(--ink2); font-size: 13px; }
.caps { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.cap { font-size: 12px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--axis); }
.cap.yes { border-color: var(--good); color: var(--good-ink); } .cap.no { color: var(--muted); } .cap.unk { color: var(--ink2); border-style: dashed; }
.banner { margin: 8px 0; padding: 8px 10px; border-left: 4px solid var(--warn); background: var(--surface); font-size: 13px; }
.chip { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 4px; white-space: nowrap; }
.chip.supp { background: var(--good); color: #fff; } .chip.contra { background: var(--crit); color: #fff; }
.chip.split { background: linear-gradient(90deg, var(--crit) 50%, var(--good) 50%); color: #fff; }
.chip.unc { background: var(--unc); color: var(--ink2); }
.chip.unc.missing { background: repeating-linear-gradient(45deg, var(--unc) 0 4px, var(--surface) 4px 8px); }
.chip.unc.screened { background: transparent; border: 1px solid var(--axis); }
.chip.unc.error { background: transparent; border: 1px dashed var(--crit); color: var(--crit); }
.chip.mini { font-weight: 400; font-size: 11px; padding: 1px 6px; }
.toggle { display: inline-flex; border: 1px solid var(--axis); border-radius: 6px; overflow: hidden; margin: 8px 0; flex-wrap: wrap; }
.toggle button { font: inherit; font-size: 13px; padding: 6px 12px; border: 0; background: var(--surface); color: var(--ink); cursor: pointer; }
.toggle button[aria-pressed="true"] { background: var(--ink); color: var(--plane); }
.coverage { background: var(--surface); border: 1px solid var(--ring); border-radius: 6px; padding: 10px 12px; margin: 6px 0 12px; }
.bar { display: flex; height: 14px; border-radius: 3px; overflow: hidden; gap: 2px; margin: 6px 0; background: var(--surface); }
.seg, .sw { display: inline-block; height: 100%; }
.seg.contra, .sw.contra { background: var(--crit); } .seg.supp, .sw.supp { background: var(--good); }
.seg.screened, .sw.screened { background: var(--surface); box-shadow: inset 0 0 0 1px var(--axis); }
.seg.missing, .sw.missing { background: repeating-linear-gradient(45deg, var(--unc) 0 4px, var(--hatch) 4px 6px); }
.seg.abstain, .sw.abstain { background: var(--unc); } .seg.error, .sw.error { background: transparent; box-shadow: inset 0 0 0 1px var(--crit); }
.legend { font-size: 12px; color: var(--ink2); display: flex; flex-wrap: wrap; gap: 12px; }
.lg { display: inline-flex; align-items: center; gap: 4px; } .sw { width: 12px; height: 12px; border-radius: 2px; }
.reasons { font-size: 12px; color: var(--muted); margin-top: 4px; word-break: break-word; }
table.per { border-collapse: collapse; font-size: 12px; margin-top: 8px; font-variant-numeric: tabular-nums; }
table.per th, table.per td { padding: 2px 10px 2px 0; text-align: left; border-bottom: 1px solid var(--grid); }
table.per td.num { text-align: right; } .ref-tag { color: var(--muted); font-size: 11px; }
.transcript { position: relative; padding-left: 56px; }
svg.arcs { position: absolute; left: 0; top: 0; width: 56px; height: 100%; overflow: visible; pointer-events: none; }
svg.arcs path { fill: none; stroke: var(--crit); stroke-width: 1.6; } svg.arcs path.dash { stroke-dasharray: 4 3; }
svg.arcs path.bracket { stroke: var(--crit); stroke-width: 3; }
.card { background: var(--surface); border: 1px solid var(--ring); border-radius: 6px; padding: 8px 10px; margin: 6px 0; transition: box-shadow .3s; }
.card.v-contradicted { border-left: 4px solid var(--crit); } .card.v-supported { border-left: 4px solid var(--good); }
.card.target { box-shadow: 0 0 0 2px var(--warn); }
.card.hl, .msg.hl, .ev.hl { outline: 2px solid var(--accent); outline-offset: 1px; }
.c-head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; }
.seq { font-weight: 600; font-variant-numeric: tabular-nums; min-width: 36px; }
.time { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 12px; }
.tool { font-weight: 600; } .cmd { flex: 1 1 260px; min-width: 0; font: 12px/1.4 ui-monospace, Consolas, monospace; color: var(--ink2); word-break: break-word; }
.exist { font-size: 11px; color: var(--ink2); border: 1px solid var(--axis); border-radius: 10px; padding: 1px 6px; }
.result { margin: 6px 0 0 46px; font-size: 12px; } .result.none { color: var(--muted); font-style: italic; }
.rlabel { color: var(--muted); margin-right: 6px; } .flag { color: var(--crit); margin-right: 6px; font-weight: 600; }
code.excerpt { white-space: pre-wrap; word-break: break-word; color: var(--ink2); }
details.full > summary { cursor: pointer; list-style: none; } details.full > summary::-webkit-details-marker { display: none; }
.evidence { margin: 8px 0 0 46px; border-top: 1px dashed var(--axis); padding-top: 6px; font-size: 13px; }
.ev-item p { margin: 4px 0; } .explain .reason, .reason { font-family: ui-monospace, Consolas, monospace; font-size: 12px; color: var(--ink2); }
.detail { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--ink2); }
.kv b { color: var(--ink); font-weight: 600; }
.refs { margin-top: 4px; font-size: 12px; display: flex; flex-wrap: wrap; gap: 4px 10px; }
a.ref { color: var(--accent); text-decoration: none; } a.ref:hover { text-decoration: underline; }
.role { font-size: 10px; text-transform: uppercase; color: var(--muted); } a.r-conflict .role { color: var(--crit); }
details.checks { margin: 6px 0 0 46px; font-size: 12px; } details.checks summary { cursor: pointer; color: var(--ink2); }
details.checks .lbl { margin-right: 4px; } details.checks ul { margin: 6px 0; padding-left: 18px; }
details.checks li { margin: 4px 0; } .sub { color: var(--ink2); } .ver { color: var(--muted); font-size: 11px; }
.msg { margin: 4px 0; border-left: 3px solid var(--grid); padding: 2px 8px; font-size: 12.5px; }
.msg summary { cursor: pointer; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; color: var(--ink2); }
.msg .who { font-weight: 600; color: var(--ink); } .msg .mmeta { color: var(--muted); font-size: 11px; }
.msg .first { flex: 1 1 300px; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.m-user { border-left-color: var(--accent); }
.ev { font-size: 12px; color: var(--ink2); margin: 4px 0; padding: 2px 8px; border-left: 3px dotted var(--axis); word-break: break-word; }
.diff { margin: 8px 0 0 46px; font-size: 12px; } .diff table { border-collapse: collapse; width: 100%; }
.diff th { width: 92px; white-space: nowrap; }
.diff th, .diff td { text-align: left; padding: 2px 6px; border-bottom: 1px solid var(--grid); vertical-align: top; word-break: break-word; }
.diff td.old { background: var(--del); } .diff td.new { background: var(--add); }
pre.ldiff span { display: block; } pre.ldiff .add { background: var(--add); } pre.ldiff .del { background: var(--del); }
.tamper { background: var(--surface); border: 1px solid var(--warn); border-radius: 6px; padding: 6px 12px; margin: 6px 0 12px; font-size: 13px; }
.tamper h2 { margin: 4px 0; font-size: 14px; }
.scanline { position: absolute; left: 0; right: 0; height: 2px; background: var(--accent); opacity: 0; top: 0; pointer-events: none; transition: top 40ms linear; }
.js .frame.scanning .scanline { opacity: .6; }
.js .frame.scanning .card:not(.lit) .chip { opacity: 0; }
.chip { transition: opacity .25s; }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(208,59,59,.6); } 100% { box-shadow: 0 0 0 12px rgba(208,59,59,0); } }
.card.pulse { animation: pulse 0.9s ease-out 1; }
@media (prefers-reduced-motion: reduce) { .card.pulse { animation: none; } .scanline { display: none; } .chip { transition: none; } }
footer { margin-top: 24px; border-top: 1px solid var(--grid); padding-top: 8px; font-size: 12px; color: var(--ink2); }
footer p { margin: 3px 0; word-break: break-word; }
@media (max-width: 640px) { .transcript { padding-left: 24px; } svg.arcs { width: 24px; }
  .result, .evidence, details.checks, .diff { margin-left: 0; } }
"""

PAGE_JS = r"""
(function(){
  var doc = document; doc.body.classList.add('js');
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var frames = Array.prototype.slice.call(doc.querySelectorAll('.frame'));
  var NS = 'http://www.w3.org/2000/svg';
  function seqMap(frame){
    var m = {};
    frame.querySelectorAll('[data-seqs]').forEach(function(el){
      el.getAttribute('data-seqs').split(' ').forEach(function(s){ if (s && !(s in m)) m[s] = el; });
    });
    return m;
  }
  function draw(frame){
    var svg = frame.querySelector('svg.arcs'); if (!svg || frame.hidden) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var box = frame.querySelector('.transcript').getBoundingClientRect();
    var W = svg.getBoundingClientRect().width || 56, m = seqMap(frame), units = {};
    function mid(el){ var r = el.getBoundingClientRect(); return r.top - box.top + Math.min(r.height / 2, 18); }
    frame.querySelectorAll('.card[data-verdict="contradicted"], .card[data-verdict="supported"]').forEach(function(card){
      var uk = card.getAttribute('data-unitkey');
      if (uk) { (units[uk] = units[uk] || []).push(card); return; }
      var y1 = mid(card), blame = card.getAttribute('data-blame');
      var core = (card.getAttribute('data-core') || '').split(' ').filter(Boolean);
      var own = (card.getAttribute('data-seqs') || '').split(' ');
      core.forEach(function(s){
        var t = m[s]; if (!t || t === card || own.indexOf(s) >= 0) return;
        var y2 = mid(t), d = Math.min(W - 6, 14 + Math.abs(y2 - y1) / 18);
        var p = doc.createElementNS(NS, 'path');
        p.setAttribute('d', 'M' + W + ' ' + y1 + ' C' + (W - d) + ' ' + y1 + ' ' + (W - d) + ' ' + y2 + ' ' + W + ' ' + y2);
        if (s !== blame) p.setAttribute('class', 'dash');
        if (card.getAttribute('data-verdict') === 'supported') p.style.stroke = 'var(--good)';
        svg.appendChild(p);
      });
    });
    Object.keys(units).forEach(function(k){            // a non-localized contradiction: one bracket over its calls
      var cs = units[k], top = cs[0].getBoundingClientRect().top - box.top;
      var last = cs[cs.length - 1].getBoundingClientRect(), bot = last.bottom - box.top, x = W - 10;
      var p = doc.createElementNS(NS, 'path');
      p.setAttribute('d', 'M' + (x + 6) + ' ' + top + ' H' + x + ' V' + bot + ' H' + (x + 6));
      p.setAttribute('class', 'bracket'); svg.appendChild(p);
    });
  }
  function drawAll(){ frames.forEach(draw); }
  function scan(frame){
    var cards = Array.prototype.slice.call(frame.querySelectorAll('.card'));
    if (reduce || !cards.length) { cards.forEach(function(c){ c.classList.add('lit'); }); return; }
    var line = frame.querySelector('.scanline'), box = frame.querySelector('.transcript');
    cards.forEach(function(c){ c.classList.remove('lit'); });
    frame.classList.add('scanning');
    cards.forEach(function(c, i){
      setTimeout(function(){
        c.classList.add('lit');
        if (line) line.style.top = (c.offsetTop + c.offsetHeight) + 'px';
        if (c.getAttribute('data-verdict') === 'contradicted') c.classList.add('pulse');
        if (i === cards.length - 1) setTimeout(function(){ frame.classList.remove('scanning'); }, 120);
      }, 40 * i);
    });
  }
  var buttons = Array.prototype.slice.call(doc.querySelectorAll('.toggle button'));
  function show(which){
    frames.forEach(function(f){ f.hidden = buttons.length ? f.getAttribute('data-frame') !== which : false; });
    buttons.forEach(function(b){ b.setAttribute('aria-pressed', String(b.getAttribute('data-show') === which)); });
    drawAll();
    frames.forEach(function(f){ if (!f.hidden) scan(f); });
  }
  buttons.forEach(function(b){ b.addEventListener('click', function(){ show(b.getAttribute('data-show')); }); });
  doc.addEventListener('mouseover', function(e){
    var a = e.target.closest && e.target.closest('a.ref'); if (!a) return;
    var t = doc.getElementById(a.getAttribute('data-target')); if (t) t.classList.add('hl');
  });
  doc.addEventListener('mouseout', function(e){
    var a = e.target.closest && e.target.closest('a.ref'); if (!a) return;
    var t = doc.getElementById(a.getAttribute('data-target')); if (t) t.classList.remove('hl');
  });
  doc.addEventListener('toggle', function(){ drawAll(); }, true);
  window.addEventListener('resize', drawAll);
  show('h');
})();
"""


# ================================================================================================= demo (no eval yet)
ROOT = Path(__file__).resolve().parents[2]
DEMO_OUT = ROOT / "analysis" / "out" / "phase_e" / "demo" / "index.html"
DEMO_SELECTION_RULE = (
    "Fixed before any session was looked at: the first session by sorted session_id among the unit's sessions in "
    "the split's IR cache that has 12 to 30 call events, a request_id on at least one assistant/call/meta row, and "
    "millisecond-resolution timestamps (>= 3 fractional digits) on every call and result.")


def _assert_not_h(path: Path, split: str) -> None:
    if split.upper() == "H" or re.search(r"(_H\b|_H\.|heldout)", path.name, re.I):
        raise RenderRefused(f"refusing to read held-out data: {path}")


def _frac_ok(ts) -> bool:
    m = re.search(r"\.(\d+)", str(ts or ""))
    return bool(m) and len(m.group(1)) >= 3


def _select_demo_session(cache: Path, unit: str, corpus: str) -> str:
    import pyarrow.parquet as pq
    cols = ["session_id", "kind", "ts", "request_id"]
    df = pq.read_table(cache, columns=cols).to_pandas()
    if corpus == "swechat":
        pop = pq.read_table(ROOT / "analysis" / "cache" / "swechat_population.parquet",
                            columns=["session_id", "format"]).to_pandas()
        fmt = unit.split("/", 1)[1]
        keep = set(pop.loc[pop["format"] == fmt, "session_id"].astype(str))
        df = df[df["session_id"].astype(str).isin(keep)]
    for sid in sorted(df["session_id"].astype(str).unique()):
        g = df[df["session_id"].astype(str) == sid]
        n_calls = int((g["kind"] == "call").sum())
        if not 12 <= n_calls <= 30:
            continue
        rid = g[g["kind"].isin(["assistant", "call", "meta"]) & g["request_id"].notna()]
        if rid.empty:
            continue
        cr = g[g["kind"].isin(["call", "result"])]
        if not cr["ts"].map(_frac_ok).all():
            continue
        return sid
    raise SystemExit(f"no session in {cache} meets the demo selection rule")


def session_ir_sha(events) -> str:
    """DESIGN.md §3.4 rule: sha256 over the IR rows, columns in COLUMNS order, rows in seq order, NA as empty,
    fields joined with \\x1f and rows with \\x1e."""
    from analysis.lib.ir import COLUMNS
    rows = []
    for r in sorted(events.to_dict("records"), key=lambda r: int(r["seq"])):
        rows.append("\x1f".join("" if _isnull(r.get(c)) else str(r.get(c)) for c in COLUMNS))
    return hashlib.sha256("\x1e".join(rows).encode("utf-8")).hexdigest()


class _StandInSession:
    """Only what render_session_html reads, for the demo while verifier.session does not exist yet. Capabilities
    are computed with the DESIGN.md §4.3 predicates that need no decoder or sidecar; the rest are marked unknown."""

    def __init__(self, events, *, corpus, unit, source):
        from analysis.lib import ir
        self.events, self.corpus, self.unit, self.source = events, corpus, unit, source
        self.session_id = str(events["session_id"].iloc[0])
        self.calibration_unit, self.stratum, self.turn_ids, self.sidecar = None, None, None, {}
        rows = _event_rows(self)
        calls = {r["call_id"] for r in rows if r.get("kind") == "call"}
        cr = [r for r in rows if r.get("kind") in ("call", "result")]
        caps = set()
        if any(r.get("ts") for r in rows):
            caps.add("ts.any")
        if any(r.get("ts_kind") == "event" for r in cr):
            caps.add("ts.event")
        if any(ir.frac_digits(r.get("ts")) >= 3 for r in cr if r.get("ts")):
            caps.add("ts.ms")
        if any(r.get("kind") == "result" and r.get("call_id") in calls for r in rows):
            caps.add("join.call_id")
        if any(r.get("kind") == "result" and r.get("text") is not None for r in rows):
            caps.add("result.text")
        if any(r.get("request_id") for r in rows if r.get("kind") in ("assistant", "call", "meta")):
            caps.add("request_id")
        if any(r.get("usage_in") is not None and r.get("usage_out") is not None for r in rows):
            caps.add("usage.io")
        if any(r.get("api_msg_id") for r in rows):
            caps.add("api_msg_id")
        self.capabilities = frozenset(caps)
        self.capabilities_unknown = frozenset({"request_id.decodable", "api_msg_id.decodable"})


def _standin_reference_verdicts(session) -> list[dict]:
    """DESIGN.md §4.8 reference rule and the §4.6 composition for a reference-only run, as plain dicts (the JSONL
    shape). Pairing per §3.1; call keys per §3.2. Used only when verifier.api is not importable."""
    from analysis.lib import ir as _ir
    rows = _event_rows(session)
    calls = [r for r in rows if r.get("kind") == "call"]
    id_count = Counter(r["call_id"] for r in calls)
    ir_sha12 = hashlib.sha256(Path(_ir.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]
    check_version = "0.0.0-standin+nocalib"
    checkset = hashlib.sha256(f"ref_result_present@{check_version}".encode()).hexdigest()[:12]
    version = f"verifier/standin-html-demo ir/{ir_sha12} checks/{checkset}"
    out = []
    for c in calls:
        seq, cid = int(c["seq"]), c["call_id"]
        key = cid if id_count[cid] == 1 else f"{cid}@{seq}"
        nxt = min((int(r["seq"]) for r in calls if r["call_id"] == cid and int(r["seq"]) > seq), default=None)
        window = [r for r in rows if r.get("kind") == "result" and r.get("call_id") == cid and int(r["seq"]) > seq
                  and (nxt is None or int(r["seq"]) < nxt)]
        res = window[0] if window else None
        base = {"session_id": session.session_id, "call_key": key, "check": "ref_result_present",
                "check_version": check_version, "confidence": None, "unit_kind": "call", "unit_id": None,
                "localized": True, "detail": None}
        if res is not None:
            cv = dict(base, verdict="supported", reason="ok:result_joined", strength="format",
                      evidence=[{"seq": seq, "field": "call_id", "role": "subject", "value": None},
                                {"seq": int(res["seq"]), "field": "call_id", "role": "witness", "value": None}])
        else:
            cv = dict(base, verdict="unconstrained", reason="missing:result", strength="none", evidence=[])
        out.append({"session_id": session.session_id, "call_id": cid, "call_key": key, "seq": seq,
                    "result_seq": int(res["seq"]) if res is not None else None, "tool": c.get("tool"),
                    "verdict": "unconstrained", "strength": "none", "confidence": None, "rule": None,
                    "reason": "abstain:reference_only", "core": [], "blame_seq": None, "localized": True,
                    "disagreement": False, "detail": None, "checks": [cv], "version": version,
                    "n_results": len(window)})
    return out


def build_reference_demo(*, corpus: str = "swechat", unit: str = "swechat/claude_code", split: str = "E",
                         session_id: str | None = None, out: Path = DEMO_OUT, pipeline: str = "auto") -> dict:
    """DA9: split E (never H) of a redistributable corpus (never cc_local or aiv_*). Writes index.html and
    demo_meta.json next to it and returns the meta dict."""
    if corpus not in PUBLISHABLE:
        raise RenderRefused(f"demo corpus must be redistributable (one of {sorted(PUBLISHABLE)}), got {corpus!r}")
    if split != "E":
        raise RenderRefused("the demo uses split E only (DESIGN.md §6.3, DA9)")
    import pyarrow.parquet as pq
    cache = ROOT / "analysis" / "cache" / f"{corpus}_{split}.parquet"
    _assert_not_h(cache, split)
    rule = DEMO_SELECTION_RULE if session_id is None else "session id given on the command line"
    sid = session_id or _select_demo_session(cache, unit, corpus)
    events = pq.read_table(cache, filters=[("session_id", "==", sid)]).to_pandas()
    events = events.sort_values("seq", kind="mergesort").reset_index(drop=True)
    fmt = unit.split("/", 1)[1] if "/" in unit else corpus
    source = {"path": f"analysis/cache/{cache.name}", "format": fmt, "loader": "ir_cache", "split": split}

    used, reason = pipeline, ""
    if pipeline in ("auto", "verifier"):
        try:                                   # the scaffold exports these from verifier/__init__.py (DESIGN: api.py)
            from verifier import run_session
            from verifier.session import build_session
        except ImportError as exc:
            if pipeline == "verifier":
                raise
            used, reason = "standin", f"verifier pipeline not importable ({exc.__class__.__name__}: {exc})"
        else:
            used = "verifier"
            # One Session object feeds both the checks and the page, so seqs and call keys cannot drift apart.
            session = build_session(events, unit=unit, source=source, calibration_unit=unit)
            verdicts, _stats = run_session(session, ["ref_result_present"], strict=True)
    if used == "standin":
        session = _StandInSession(events, corpus=corpus, unit=unit, source=source)
        verdicts = _standin_reference_verdicts(session)
        reason = reason or "stand-in requested"

    title = f"{unit} · session {sid[:8]} · reference check only"
    page = render_session_html(session, verdicts, title=title)
    demo_note = (f"<p>Demo session (DESIGN.md §6.3, DA9: split {split} of a redistributable corpus, never H, never "
                 f"cc_local or aiv_*). Selection: {_html.escape(rule)}</p>")
    if used == "standin":
        demo_note += ("<p><b>Verdicts produced by the html.py demo stand-in</b> of the DESIGN.md §4.8 reference rule, "
                      f"because {_html.escape(reason)}. Re-run <code>python -m verifier.render.html demo</code> once "
                      "verifier.api exists.</p>")
    page = page.replace("<footer>", "<footer>" + demo_note, 1)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8", newline="\n")
    vc = Counter(_get(v, "verdict") for v in verdicts)
    cc = Counter((_get(cv, "check"), _get(cv, "reason")) for v in verdicts for cv in (_get(v, "checks") or ()))
    meta = {"generated_by": "verifier/render/html.py demo", "selection_rule": rule, "corpus": corpus, "unit": unit,
            "split": split, "session_id": sid, "n_events": int(len(events)),
            "n_calls": int((events["kind"] == "call").sum()), "session_ir_sha": session_ir_sha(events),
            "cache": source["path"], "pipeline": used, "pipeline_note": reason,
            "checks": ["ref_result_present"], "composed_verdicts": dict(vc),
            "per_check_reasons": {f"{c}|{r}": n for (c, r), n in sorted(cc.items())},
            "html_sha256": hashlib.sha256(page.encode("utf-8")).hexdigest(),
            "html_path": str(out.relative_to(ROOT)).replace("\\", "/") if out.is_relative_to(ROOT) else str(out),
            "publish": "local only: swechat is HF-gated; do not publish until the gate terms are confirmed "
                       "(DESIGN.md §6.3, open item 8)" if corpus == "swechat" else "see DESIGN.md §6.3"}
    (out.parent / "demo_meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                               newline="\n")
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m verifier.render.html")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="render the reference-check demo page from one E-split session (DA9)")
    d.add_argument("--corpus", default="swechat", choices=sorted(PUBLISHABLE))
    d.add_argument("--unit", default="swechat/claude_code")
    d.add_argument("--split", default="E", choices=["E"])
    d.add_argument("--session", default=None, help="session id (default: DEMO_SELECTION_RULE picks one)")
    d.add_argument("--out", default=str(DEMO_OUT))
    d.add_argument("--pipeline", default="auto", choices=["auto", "verifier", "standin"])
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if a.cmd == "demo":
        meta = build_reference_demo(corpus=a.corpus, unit=a.unit, split=a.split, session_id=a.session,
                                    out=Path(a.out), pipeline=a.pipeline)
        print(json.dumps({k: meta[k] for k in ("session_id", "n_calls", "pipeline", "composed_verdicts",
                                                "per_check_reasons", "html_path")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
