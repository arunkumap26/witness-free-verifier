"""Check `token_conservation`: server-side token accounting vs the logged transcript (swarm turn format).

THE WITNESS. The swarm harness (swarm/agent_loop.py, read-only reference) calls a vLLM OpenAI endpoint once per step
and records the server's `usage.prompt_tokens` / `usage.completion_tokens` on the assistant text turn of that step
(`input_tokens` / `output_tokens`). A step that produced only a tool call and no text logs NO usage. `prompt_tokens`
is the FULL rendered prompt (no prompt-cache split): the system prompt, the tool schemas and every earlier message,
including every earlier tool result, verbatim. The server produced the count at request time, so editing a
tool_result's text in the log afterwards does not change it.

THE IDENTITY. For two consecutive usage-bearing assistant turns i < j (an "anchor window"):

    input_tokens_j - input_tokens_i  =  output_tokens_i            (anchor i's reply + its tool call, re-rendered)
                                      + tokens(tool calls of steps between i and j that logged no usage)
                                      + tokens(every tool_result between i and j)
                                      + per-message template overhead

Text token counts are not known without the model's tokenizer (not on the verifier host), so each text is reduced to
pre-tokenizer counts (letter runs, digits, punctuation runs, whitespace runs, ...) and a linear model fitted on HONEST
dev windows maps them to tokens (frozen in analysis/swarmds/frozen_token_conservation.json). A window whose logged
content predicts a prompt growth that differs from the server's by more than the frozen tolerance is `contradicted`:
the logged text between i and j is not the text the server was sent. Otherwise every call in the window is
`unconstrained` / `abstain:below_threshold` (statistical check: it never emits `supported`).

BREAKS (abstain, decided from the log's own fields, never from the server growth):
  * a user turn inside the window (the harness NUDGE after a malformed reply): the chat template re-renders history
    and drops earlier reasoning, so the prompt can shrink;
  * output_tokens_i far above the estimate of anchor i's logged text + call: the harness keeps only the FIRST tool
    call of a reply, so extra generated calls are billed but never re-sent.

LOCALIZATION. A window holding exactly one tool call localizes the mismatch to it (localized=True). A window with
several says only that one of them (or a no-usage tool-call turn) was altered; each call in it is reported
`contradicted` with localized=False and the window's call ids in `detail`.

WHAT IT CANNOT SEE. A substitution that keeps the token count (a digit flip, a same-length word swap), a size change
below the tolerance, any call after the session's last usage-bearing turn or before its first, and claim/board text
that never re-enters the prompt.

ENTRYPOINT (integrator):

    from verifier.checks.token_conservation import check_session
    check_session(turns: list[dict], frozen: dict | None = None) -> dict[str, dict]

`turns` = one session's turns in the swarm/SWE-chat turn format (dicts with at least role, content, turn_number,
tool_call_id, tool_name, tool_input_json, input_tokens, output_tokens). Returns, for every tool_call_id on a tool_use
or tool_result turn:
    {"verdict": "contradicted"|"unconstrained", "reason": str, "confidence": float|None, "localized": bool,
     "detail": dict}
`frozen` defaults to analysis/swarmds/frozen_token_conservation.json. Stdlib only, so the module can be loaded by
file path when the `verifier` package's own imports (pandas) are unavailable.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

NAME = "token_conservation"
VERSION = "1.0.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_PATH = REPO_ROOT / "analysis" / "swarmds" / "frozen_token_conservation.json"

# ------------------------------------------------------------------------------------------- text -> counts
# A pre-tokenizer shaped like the Qwen2/3 BPE pre-tokenizer (letters, single digits, punctuation runs, whitespace),
# expressed with stdlib `re` (no \p{L}: letters are [^\W\d_]).
_PRE = re.compile(
    r"'(?:s|t|re|ve|m|ll|d)"            # contractions
    r"|[^\r\n\w]?[^\W\d_]+"             # optional leading space/punct + a letter run
    r"|\d"                              # one digit per token
    r"| ?[^\s\w]+[\r\n]*"               # punctuation run
    r"|_+"                              # underscores (\w but not a letter)
    r"|\s*[\r\n]+"                      # newline run
    r"|\s+(?!\S)|\s+",                  # whitespace run
    re.IGNORECASE)

TEXT_FEATURES = ("chars", "words", "word_excess", "long_chars", "digits", "punct_runs", "punct_chars", "nl_runs",
                 "ws_runs", "nonascii", "hexlike")
_HEX = re.compile(r"\b[0-9a-f]{12,}\b")


def text_counts(text: Optional[str]) -> list[float]:
    """Pre-tokenizer counts of one text, in TEXT_FEATURES order."""
    if not text:
        return [0.0] * len(TEXT_FEATURES)
    words = word_excess = long_chars = digits = punct_runs = punct_chars = nl_runs = ws_runs = 0
    for m in _PRE.finditer(text):
        t = m.group(0)
        c0 = t[-1]
        if len(t) == 1 and t.isdigit():
            digits += 1
        elif "\n" in t or "\r" in t:
            if t.strip():                  # punctuation run carrying trailing newlines
                punct_runs += 1
                punct_chars += len(t.strip())
            nl_runs += 1
        elif not t.strip():
            ws_runs += 1
        elif c0.isalpha() or t.startswith("'"):
            words += 1
            L = sum(1 for ch in t if ch.isalpha())
            word_excess += max(0, L - 6)
            if L > 16:                     # long / repetitive runs (e.g. 'IIIIIIII...') split into many tokens
                long_chars += L
        else:
            punct_runs += 1
            punct_chars += len(t.strip())
    nonascii = sum(1 for ch in text if ord(ch) > 127)
    hexlike = sum(len(h) for h in _HEX.findall(text))
    return [float(len(text)), float(words), float(word_excess), float(long_chars), float(digits), float(punct_runs),
            float(punct_chars), float(nl_runs), float(ws_runs), float(nonascii), float(hexlike)]


def _add(a: list[float], b: list[float]) -> None:
    for i, v in enumerate(b):
        a[i] += v


def _split_think(text: str) -> tuple[str, str]:
    """(reasoning, visible) of an assistant text the harness recorded as '<think>...</think>rest'."""
    if text.startswith("<think>") and "</think>" in text:
        a, b = text[len("<think>"):].split("</think>", 1)
        return a, b
    return "", text


def _render_call(t: dict) -> str:
    """Text of a logged tool call as it re-enters the prompt (name + JSON arguments)."""
    args = t.get("tool_input_json")
    if args is None:
        args = t.get("content") or ""
    return f"{t.get('tool_name') or ''} {args}"


# window feature vector: names fixed here, coefficients fitted and frozen elsewhere
GROUPS = ("r", "c", "k")                           # r: tool_result texts; c: tool calls of no-usage steps (their output
                                                   # tokens were never logged); k: anchor i's reasoning text
FEATURE_NAMES: tuple[str, ...] = (
    ("intercept", "out_i", "n_results", "n_calls_nousage")
    + tuple(f"{g}_{f}" for g in GROUPS for f in TEXT_FEATURES))


def _turns_sorted(turns: Iterable[dict]) -> list[dict]:
    ts = list(turns)
    if all(isinstance(t.get("turn_number"), int) for t in ts):
        ts.sort(key=lambda t: t["turn_number"])
    return ts


def build_windows(turns: Iterable[dict]) -> tuple[list[dict], list[str]]:
    """Anchor windows of one session: (windows, call_ids).

    windows = [{i, j, dC, x (feature dict), anchor_counts, n_user, call_ids, n_results}] (i, j = indices into the
    turn list sorted by turn_number); call_ids = every tool_call_id on a tool_use / tool_result turn, in order.
    A tool_use immediately after a usage-bearing assistant turn is that step's own call (its tokens are in out_i);
    any other tool_use is a step that logged no text and therefore no usage (its tokens must be estimated)."""
    ts = _turns_sorted(turns)
    call_ids: list[str] = []
    seen: set[str] = set()
    for t in ts:
        cid = t.get("tool_call_id")
        if cid and t.get("role") in ("tool_use", "tool_result") and cid not in seen:
            seen.add(cid)
            call_ids.append(cid)
    anchors = [k for k, t in enumerate(ts) if t.get("role") == "assistant" and t.get("input_tokens") is not None
               and t.get("output_tokens") is not None]
    windows: list[dict] = []
    nf = len(TEXT_FEATURES)
    for a, b in zip(anchors, anchors[1:]):
        ti, tj = ts[a], ts[b]
        acc = {g: [0.0] * nf for g in GROUPS}
        n_res = n_calls = n_user = 0
        cids: list[str] = []
        think, _visible = _split_think(ti.get("content") or "")
        acc["k"] = text_counts(think)
        anchor_counts = text_counts(ti.get("content") or "")
        for m in range(a + 1, b):
            t = ts[m]
            role = t.get("role")
            if role == "tool_use":
                if m == a + 1:
                    _add(anchor_counts, text_counts(_render_call(t)))   # anchor i's own call: inside out_i
                else:
                    n_calls += 1
                    _add(acc["c"], text_counts(_render_call(t)))
            elif role == "tool_result":
                n_res += 1
                _add(acc["r"], text_counts(t.get("content") or ""))
            else:                                   # user turn (harness NUDGE) or an assistant turn with no usage
                n_user += 1
            cid = t.get("tool_call_id")
            if cid and role in ("tool_use", "tool_result") and cid not in cids:
                cids.append(cid)
        x = {"intercept": 1.0, "out_i": float(ti["output_tokens"]), "n_results": float(n_res),
             "n_calls_nousage": float(n_calls)}
        for g in GROUPS:
            for name, v in zip(TEXT_FEATURES, acc[g]):
                x[f"{g}_{name}"] = v
        dC = float(tj["input_tokens"]) - float(ti["input_tokens"])
        windows.append({"i": a, "j": b, "dC": dC, "x": x, "anchor_counts": anchor_counts, "n_user": n_user,
                        "call_ids": cids, "n_results": n_res})
    return windows, call_ids


# ------------------------------------------------------------------------------------------- frozen rules
@lru_cache(maxsize=4)
def _load_frozen_file(path: str) -> Optional[dict]:
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def load_frozen(path: Optional[str] = None) -> Optional[dict]:
    return _load_frozen_file(str(path or FROZEN_PATH))


def predict(x: dict, coef: dict) -> float:
    return sum(coef.get(n, 0.0) * x.get(n, 0.0) for n in FEATURE_NAMES)


def scale_of(x: dict, coef: dict) -> float:
    """Estimated (not server-counted) tokens in the window: |sum| of each estimated group (results, no-usage calls,
    reasoning). The tolerance grows with it; the server-counted out_i adds no estimation error."""
    return sum(abs(sum(coef.get(f"{g}_{f}", 0.0) * x.get(f"{g}_{f}", 0.0) for f in TEXT_FEATURES)) for g in GROUPS)


def text_tokens(counts: list[float], text_coef: dict) -> float:
    """Token estimate of one text from its counts (frozen per-text estimator)."""
    return sum(text_coef.get(f, 0.0) * v for f, v in zip(TEXT_FEATURES, counts))


def break_reason(w: dict, frozen: dict) -> Optional[str]:
    """Why a window's identity does not hold, from the log's own fields (never from the server growth), else None."""
    if w["n_user"]:
        # a user turn (the harness NUDGE after a malformed reply) moves the chat template's last-query index, which
        # drops earlier reasoning from the re-rendered history: the prompt can SHRINK across this window.
        return "abstain:history_rerendered_at_user_turn"
    gap = w["x"]["out_i"] - text_tokens(w["anchor_counts"], frozen["text_coef"])
    if gap > frozen["anchor_gap_max"]:
        # the server generated more than the log kept: the harness keeps only the FIRST tool call of a reply, so
        # extra generated calls are billed in out_i but never re-sent.
        return "abstain:anchor_output_not_resent"
    if w["x"].get("r_long_chars", 0.0) > frozen.get("long_chars_max", float("inf")) or             w["x"].get("r_nonascii", 0.0) > frozen.get("nonascii_max", float("inf")):
        # long letter runs ('IIIIIIII...') and non-ASCII text tokenize far from the count model: the estimate,
        # not the log, would be wrong
        return "abstain:tokenization_uncertain_content"
    return None


def window_residual(w: dict, frozen: dict) -> tuple[float, float, float]:
    """(residual = logged-content prediction - server growth, tolerance, scale)."""
    coef = frozen["coef"]
    pred = predict(w["x"], coef)
    sc = scale_of(w["x"], coef)
    th = frozen["threshold"]
    tol = th["abs_tokens"] + th["rel"] * sc
    return pred - w["dC"], tol, sc


def check_session(turns: list[dict], frozen: Optional[dict] = None) -> dict[str, dict]:
    """{tool_call_id: {verdict, reason, confidence, localized, detail}} for one session (see module docstring)."""
    frozen = frozen or load_frozen()
    windows, call_ids = build_windows(turns)
    out: dict[str, dict] = {}
    if frozen is None:
        for cid in call_ids:
            out[cid] = {"verdict": "unconstrained", "reason": "missing:frozen_calibration", "confidence": None,
                        "localized": False, "detail": {}}
        return out
    for cid in call_ids:
        out[cid] = {"verdict": "unconstrained", "reason": "missing:no_usage_window", "confidence": None,
                    "localized": False, "detail": {}}
    for w in windows:
        br = break_reason(w, frozen)
        if br:
            for cid in w["call_ids"]:
                if out[cid]["verdict"] != "contradicted":
                    out[cid] = {"verdict": "unconstrained", "reason": br, "confidence": None, "localized": False,
                                "detail": {"window_turns": [w["i"], w["j"]]}}
            continue
        res, tol, _sc = window_residual(w, frozen)
        detail = {"window_turns": [w["i"], w["j"]], "server_growth": w["dC"],
                  "logged_prediction": round(w["dC"] + res, 1), "residual_tokens": round(res, 1),
                  "tolerance_tokens": round(tol, 1), "n_results": w["n_results"],
                  "window_call_ids": list(w["call_ids"])}
        if abs(res) > tol:
            direction = "logged_text_larger" if res > 0 else "logged_text_smaller"
            excess = abs(res) / max(tol, 1.0) - 1.0
            conf = round(min(0.999, 0.5 + 0.5 * (1.0 - math.exp(-3.0 * excess))), 3)
            loc = w["n_results"] == 1 and len(w["call_ids"]) == 1
            for cid in w["call_ids"]:
                out[cid] = {"verdict": "contradicted", "reason": f"violation:token_growth_{direction}",
                            "confidence": conf, "localized": loc, "detail": detail}
        else:
            for cid in w["call_ids"]:
                if out[cid]["verdict"] != "contradicted":
                    out[cid] = {"verdict": "unconstrained", "reason": "abstain:below_threshold", "confidence": None,
                                "localized": False, "detail": detail}
    return out
