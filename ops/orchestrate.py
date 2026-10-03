#!/usr/bin/env python
"""Overnight orchestrator. Deterministic code makes every keep/reject decision;
Claude sessions only propose changes.

  python ops/orchestrate.py setup             create division worktrees + state dirs (idempotent)
  python ops/orchestrate.py preflight <div>   check everything a night run needs, then exit
  python ops/orchestrate.py run <div>         preflight, then loop until done or stopped
  python ops/orchestrate.py plan <div>        one planner refill of the division queue, now
  python ops/orchestrate.py status            one-screen status for every division
  python ops/orchestrate.py paths <div>       print the state paths for a division

Kill switch: create ops/state/STOP.<div> (or STOP.all). The loop exits at its next check.

Two loop patterns, chosen per division in ops/config.toml:
  climb  one task per fresh session -> harness commits -> frozen eval -> keep or reset
  tend   a long-running pipeline runs on its own; Claude is called only when it crashes,
         hangs, or its output fails validation, and a fix is kept only if the smoke test passes
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

IS_WIN = os.name == "nt"


# ---------------------------------------------------------------- paths + config

def main_root() -> Path:
    """The main checkout, even when this file is run from inside a worktree."""
    here = Path(__file__).resolve().parent
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=here, capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit("not inside a git repo: run `git init` and make a first commit")
    return Path(out.stdout.strip()).parent


ROOT = main_root()
STATE = ROOT / "ops" / "state"
DATA = ROOT / "data"
PROMPTS = ROOT / "ops" / "prompts"


def load_config() -> dict:
    with open(ROOT / "ops" / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    defaults = cfg.get("defaults", {})
    for name, d in cfg.get("divisions", {}).items():
        merged = {**defaults, **d, "name": name}
        cfg["divisions"][name] = merged
    return cfg


def fmt(s: str) -> str:
    return s.format(root=ROOT, state=STATE, data=DATA)


def div_state(div: str) -> Path:
    p = STATE / div
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- small helpers

def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(div: str, msg: str) -> None:
    line = f"[{dt.datetime.now():%H:%M:%S}] [{div}] {msg}"
    print(line, flush=True)
    with open(div_state(div) / "loop.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def journal(div: str, **rec) -> None:
    rec = {"ts": now(), "div": div, **rec}
    with open(div_state(div) / "journal.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def alert(div: str, msg: str) -> None:
    log(div, "ALERT: " + msg)
    with open(STATE / "ALERTS.md", "a", encoding="utf-8") as f:
        f.write(f"- {now()} [{div}] {msg}\n")


def stop_requested(div: str) -> bool:
    return (STATE / f"STOP.{div}").exists() or (STATE / "STOP.all").exists()


def nap(div: str, seconds: float) -> bool:
    """Sleep in short slices so the kill file stays responsive. True = stop requested."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_requested(div):
            return True
        time.sleep(min(5.0, max(0.0, end - time.time())))
    return stop_requested(div)


def sh(cmd: list[str], cwd: Path, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def git(cwd: Path, *args: str) -> str:
    out = sh(["git", *args], cwd)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout.strip()


def kill_tree(pid: int) -> None:
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(pid, 9)
        except OSError:
            pass


def pid_alive(pid: int) -> bool:
    if IS_WIN:
        # never os.kill(pid, 0) on Windows: it terminates the process
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def last_json_line(text: str) -> dict | None:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def tail(p: Path, n: int = 60) -> str:
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return "(no log)"


# ---------------------------------------------------------------- lock

class Lock:
    def __init__(self, div: str):
        self.path = div_state(div) / "lock"

    def __enter__(self):
        info = read_json(self.path)
        if info and pid_alive(info.get("pid", -1)):
            sys.exit(f"{self.path} is held by pid {info['pid']} (started {info.get('started')}). "
                     "Another loop is running on this division.")
        self.path.write_text(json.dumps({"pid": os.getpid(), "started": now()}))
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


# ---------------------------------------------------------------- claude sessions

def claude_bin(cfg: dict) -> list[str]:
    b = cfg["defaults"].get("claude_bin", "auto")
    if isinstance(b, list):
        return [fmt(x) for x in b]
    if b != "auto":
        return [b]
    found = shutil.which("claude")
    if not found:
        sys.exit("claude CLI not found on PATH")
    # npm on Windows installs a .cmd shim around a native exe. Call the exe directly so a
    # timeout kill reaches the real process instead of orphaning it behind cmd.exe.
    if found.lower().endswith(".cmd"):
        m = re.search(r'"%dp0%\\([^"]+\.exe)"', Path(found).read_text(errors="replace"))
        if m:
            exe = Path(found).parent / m.group(1)
            if exe.exists():
                return [str(exe)]
    return [found]


LIMIT_RE = re.compile(r"usage limit|rate limit|limit reached|overloaded|too many requests", re.I)


def claude(cfg: dict, cwd: Path, *, prompt: str, model: str, agent: str | None = None,
           fallback: str | None = None, system_file: Path | None = None,
           budget: float | None = None, wall_min: float | None = None,
           overnight: bool = True, max_turns: int | None = None) -> dict:
    """Run one fresh `claude -p` session. Prompt goes over stdin so Windows never has to
    quote it. Returns the result JSON plus `_kind`, one of:
      ok | budget | turns   -> the session ran; evaluate whatever it changed
      limit                 -> usage/rate limit; wait and retry, not a failure
      auth                  -> login expired; nothing will work until a human fixes it
      error | crash | timeout
    """
    d = cfg["defaults"]
    cmd = claude_bin(cfg) + [
        "-p", "--output-format", "json", "--model", model,
        "--permission-mode", d.get("permission_mode", "acceptEdits"),
        "--max-turns", str(max_turns or d.get("max_turns", 60)),
        "--max-budget-usd", f"{budget or d.get('budget_usd', 5.0):.2f}",
    ]
    if agent:
        cmd += ["--agent", agent]
    if fallback:
        cmd += ["--fallback-model", fallback]
    if system_file:
        cmd += ["--append-system-prompt-file", str(system_file)]
    if overnight:
        cmd += ["--settings", str(ROOT / "ops" / "overnight.settings.json")]

    started = time.time()
    p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                         start_new_session=not IS_WIN)
    try:
        out, err = p.communicate(prompt, timeout=(wall_min or d.get("session_wall_min", 45)) * 60)
    except subprocess.TimeoutExpired:
        kill_tree(p.pid)
        out, err = p.communicate()
        return {"_kind": "timeout", "_secs": round(time.time() - started), "result": err[-400:]}

    res = last_json_line(out) or {}
    res["_secs"] = round(time.time() - started)
    res["_rc"] = p.returncode
    text = str(res.get("result", "")) + " " + err[-400:]
    status = res.get("api_error_status")
    subtype = str(res.get("subtype", ""))
    if not res.get("type"):
        res["_kind"] = "crash"
        res["result"] = (err or out)[-600:]
    elif res.get("is_error") and status in (401, 403):
        res["_kind"] = "auth"
    elif res.get("is_error") and (status in (429, 529) or LIMIT_RE.search(text)):
        res["_kind"] = "limit"
    elif "budget" in subtype or "Budget limit" in text:
        res["_kind"] = "budget"
    elif "max_turns" in subtype:
        res["_kind"] = "turns"
    elif res.get("is_error"):
        res["_kind"] = "error"
    else:
        res["_kind"] = "ok"
    return res


def limit_wait(cfg: dict, res: dict, streak: int) -> float:
    """Seconds to wait after a usage/rate limit. Uses the reset time if the CLI gave one."""
    d = cfg["defaults"]
    m = re.search(r"\|(\d{10})\b", str(res.get("result", "")))
    if m:
        return max(0.0, int(m.group(1)) - time.time()) + d.get("ratelimit_reset_margin_sec", 60)
    sched = d.get("ratelimit_backoff_min", [10, 20, 40, 60])
    return sched[min(streak, len(sched) - 1)] * 60


def cost(res: dict) -> float:
    return round(float(res.get("total_cost_usd") or 0.0), 4)


# ---------------------------------------------------------------- queue

TASK_RE = re.compile(r"^- \[ \] ")


def queue_path(div: str) -> Path:
    return div_state(div) / "queue.md"


def next_task(div: str) -> tuple[int, str] | None:
    try:
        lines = queue_path(div).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for i, line in enumerate(lines):
        if TASK_RE.match(line):
            body = [line[6:]]
            for cont in lines[i + 1:]:
                if cont.strip() and cont[:1].isspace():
                    body.append(cont.strip())
                else:
                    break
            return i, " ".join(body)
    return None


def mark_task(div: str, idx: int, mark: str, note: str) -> None:
    p = queue_path(div)
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[idx] = f"- [{mark}] " + lines[idx][6:] + f"  _({note})_"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def bump_attempts(div: str, task: str) -> int:
    p = div_state(div) / "attempts.json"
    data = read_json(p) or {}
    key = hashlib.sha1(task.encode()).hexdigest()[:12]
    data[key] = data.get(key, 0) + 1
    p.write_text(json.dumps(data), encoding="utf-8")
    return data[key]


def collect_followups(div: str, wt: Path) -> None:
    f = wt / "FOLLOWUPS.md"
    if f.exists():
        with open(div_state(div) / "inbox.md", "a", encoding="utf-8") as inbox:
            inbox.write(f"\n<!-- {now()} -->\n" + f.read_text(encoding="utf-8").strip() + "\n")
        f.unlink()


# ---------------------------------------------------------------- frozen eval

def snapshot_eval(div: str) -> tuple[Path, str]:
    """Freeze eval/ for the night. Agents never see this copy, and editing eval/ on main
    mid-run can't shift the goalposts under a running loop."""
    snap = div_state(div) / "eval_snapshot"
    if snap.exists():
        shutil.rmtree(snap)
    shutil.copytree(ROOT / "eval", snap, ignore=shutil.ignore_patterns("__pycache__"))
    return snap, tree_hash(snap)


def tree_hash(p: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            h.update(str(f.relative_to(p)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def run_eval(d: dict, script: Path, args: list[str], cwd: Path) -> dict:
    try:
        out = sh([sys.executable, str(script), *args], cwd,
                 timeout=d.get("eval_timeout_min", 15) * 60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "eval timed out"}
    res = last_json_line(out.stdout)
    if res is None:
        return {"ok": False, "error": (out.stderr or out.stdout)[-600:]}
    if out.returncode != 0:
        res["ok"] = False
    return res


def score(d: dict, ev: dict) -> float:
    h = float(ev["headline"])
    return h if d.get("direction", "max") == "max" else -h


def changed_paths(wt: Path, base: str) -> list[str]:
    tracked = git(wt, "diff", "--name-only", base).splitlines()
    untracked = git(wt, "ls-files", "--others", "--exclude-standard").splitlines()
    return [p for p in tracked + untracked if p]


def reset_to(wt: Path, sha: str) -> None:
    git(wt, "reset", "--hard", sha)
    git(wt, "clean", "-fd")


# ---------------------------------------------------------------- planner

def plan(cfg: dict, div: str) -> str:
    """One fresh planner session rewrites the queue. Returns 'ok', 'limit', 'auth' or 'fail'."""
    d = cfg["divisions"][div]
    p = cfg.get("planner", {})
    wt = ROOT / d["worktree"]
    if git(wt, "status", "--porcelain"):
        log(div, f"planner refused: {wt} has uncommitted changes it would discard")
        return "fail"
    base = git(wt, "rev-parse", "HEAD")
    qp = queue_path(div)
    queue = qp.read_text(encoding="utf-8") if qp.exists() else "(empty)"
    inbox_p = div_state(div) / "inbox.md"
    inbox = inbox_p.read_text(encoding="utf-8") if inbox_p.exists() else "(empty)"
    jp = div_state(div) / "journal.jsonl"
    jtail = "\n".join(jp.read_text(encoding="utf-8").splitlines()[-30:]) if jp.exists() else "(empty)"
    prompt = (
        f"Division: {div}\n\n# MISSION.md\n{(ROOT / 'MISSION.md').read_text(encoding='utf-8')}\n\n"
        f"# Current queue\n{queue}\n\n# Follow-ups proposed by workers\n{inbox}\n\n"
        f"# Last 30 journal lines\n{jtail}\n\n"
        "Write the new queue for this division now."
    )
    res = claude(cfg, wt, prompt=prompt, model=p.get("model", "opus"), agent="planner",
                 fallback=p.get("fallback_model"), system_file=PROMPTS / "plan.md",
                 budget=p.get("budget_usd", 3.0), max_turns=p.get("max_turns", 30))
    reset_to(wt, base)  # the planner's only output is text; discard any file edits
    kind = res["_kind"]
    m = re.search(r"<queue>\s*(.*?)\s*</queue>", str(res.get("result", "")), re.S)
    new_tasks = [l for l in (m.group(1).splitlines() if m else []) if l.strip()]
    n_tasks = sum(1 for l in new_tasks if TASK_RE.match(l))
    outcome = kind if kind in ("limit", "auth") else ("ok" if n_tasks else "fail")
    journal(div, kind="plan", verdict=outcome, tasks=n_tasks, cost=cost(res), secs=res.get("_secs"))
    if outcome != "ok":
        log(div, f"planner produced no tasks ({kind}): {str(res.get('result', ''))[:200]}")
        return outcome
    done = [l for l in queue.splitlines() if re.match(r"^- \[[x!]\] ", l)]
    qp.write_text(f"# Queue: {div}\n\n## Done\n" + "\n".join(done) +
                  "\n\n## Todo\n" + "\n".join(new_tasks) + "\n", encoding="utf-8")
    inbox_p.unlink(missing_ok=True)
    log(div, f"planner wrote {sum(1 for l in new_tasks if TASK_RE.match(l))} tasks")
    return "ok"


# ---------------------------------------------------------------- climb pattern

IMPLEMENT_PROMPT = """Task (from the {div} queue):
{task}
{previous}
Current best headline: {best}. The harness keeps your change only if the frozen eval
scores it no worse than that (tolerance {tol}). Do the one task, then stop."""


def previous_attempt(div: str, task: str) -> str:
    jp = div_state(div) / "journal.jsonl"
    if not jp.exists():
        return ""
    for line in reversed(jp.read_text(encoding="utf-8").splitlines()[-200:]):
        r = read_json_str(line)
        if r and r.get("task") == task[:300] and r.get("verdict") in ("reject", "noop"):
            why = r.get("reason") or "the session made no change"
            return f"\nA previous attempt at this task was rejected: {why}\nTry a different approach.\n"
    return ""


def read_json_str(s: str) -> dict | None:
    try:
        return json.loads(s)
    except ValueError:
        return None


def climb(cfg: dict, div: str, base_eval: dict, snap: Path, snap_hash: str) -> None:
    d = cfg["divisions"][div]
    wt = ROOT / d["worktree"]
    script = snap / Path(d["eval"]).name
    best = score(d, base_eval)
    tol = d.get("tolerance") or float(base_eval.get("stdev") or 0.0)
    fails = limit_streak = refills = it = 0
    log(div, f"climb start: best={best:.4f} tol={tol:.4f}")

    while not stop_requested(div):
        it += 1
        if tree_hash(snap) != snap_hash:
            alert(div, "frozen eval snapshot was modified during the run; halting")
            return

        picked = next_task(div)
        if picked is None:
            if refills >= cfg["defaults"].get("max_planner_refills", 3):
                log(div, "queue empty and refill cap reached; done for the night")
                return
            refills += 1
            r = plan(cfg, div)
            if r == "auth":
                alert(div, "claude login expired: run `claude` then /login in a terminal")
                return
            if r == "limit":
                limit_streak += 1
                if nap(div, limit_wait(cfg, {}, limit_streak - 1)):
                    return
            elif r == "fail":
                fails += 1
                if fails >= cfg["defaults"].get("max_consecutive_failures", 3):
                    alert(div, "planner failed repeatedly; halting")
                    return
            continue

        idx, task = picked
        base = git(wt, "rev-parse", "HEAD")
        log(div, f"iter {it}: {task[:100]}")
        prompt = IMPLEMENT_PROMPT.format(div=div, task=task, best=best, tol=tol,
                                         previous=previous_attempt(div, task))
        res = claude(cfg, wt, prompt=prompt,
                     model=d["model"], agent="implementer", fallback=d.get("fallback_model"),
                     system_file=PROMPTS / "implement.md", budget=d.get("budget_usd"))
        kind = res["_kind"]
        rec = dict(kind="iter", iter=it, task=task[:300], session=res.get("session_id"),
                   cost=cost(res), secs=res.get("_secs"), turns=res.get("num_turns"))

        if kind == "limit":
            reset_to(wt, base)
            wait = limit_wait(cfg, res, limit_streak)
            limit_streak += 1
            journal(div, **rec, verdict="limit", wait_min=round(wait / 60))
            log(div, f"usage limit; sleeping {wait / 60:.0f} min (not counted as a failure)")
            if nap(div, wait):
                return
            continue
        limit_streak = 0
        if kind == "auth":
            reset_to(wt, base)
            alert(div, "claude login expired: run `claude` then /login in a terminal")
            return
        if kind in ("crash", "error", "timeout"):
            reset_to(wt, base)
            fails += 1
            journal(div, **rec, verdict=kind, note=str(res.get("result", ""))[:300])
            log(div, f"  session {kind} ({fails} in a row): {str(res.get('result', ''))[:120]}")
            if fails >= cfg["defaults"].get("max_consecutive_failures", 3):
                alert(div, f"{fails} consecutive session failures (last: {kind}); halting")
                return
            if nap(div, cfg["defaults"].get("failure_pause_sec", 30)):
                return
            continue

        collect_followups(div, wt)
        paths = changed_paths(wt, base)
        if not paths:
            n = bump_attempts(div, task)
            if n >= d.get("max_attempts_per_task", 2):
                mark_task(div, idx, "!", f"blocked: no change after {n} attempts")
            journal(div, **rec, verdict="noop")
            log(div, f"  no change (attempt {n})")
            continue
        if any(p.replace("\\", "/").startswith("eval/") for p in paths):
            reset_to(wt, base)
            n = bump_attempts(div, task)
            if n >= d.get("max_attempts_per_task", 2):
                mark_task(div, idx, "!", "blocked: kept trying to edit eval/")
            journal(div, **rec, verdict="reject", reason="touched eval/")
            log(div, f"  reject  touched eval/ (attempt {n})")
            continue

        git(wt, "add", "-A")
        git(wt, "commit", "-q", "--no-verify", "-m", f"{div}: {task[:60]} (candidate)")
        ev = run_eval(d, script, ["--repo", str(wt)], wt)
        new = score(d, ev) if ev.get("ok") and "headline" in ev else None
        keep = new is not None and new >= best - tol
        rec.update(headline=ev.get("headline"), best=best, files=len(paths))

        if keep:
            msg = f"{div}: {task[:60]} (headline {best:.4f} -> {new:.4f})"
            git(wt, "commit", "-q", "--amend", "--no-verify", "-m", msg)
            best = max(best, new)
            mark_task(div, idx, "x", f"kept, headline {ev['headline']}")
            fails = 0
            journal(div, **rec, verdict="keep", sha=git(wt, "rev-parse", "--short", "HEAD"))
            log(div, f"  keep  headline={ev['headline']}  best={best:.4f}")
        else:
            reset_to(wt, base)
            n = bump_attempts(div, task)
            reason = ev.get("error", "")[:300] if new is None else f"headline {ev['headline']} < best {best:.4f} - tol"
            if n >= d.get("max_attempts_per_task", 2):
                mark_task(div, idx, "!", f"rejected {n}x: {reason[:80]}")
            # a clean "worse" verdict proves the harness works; the eval itself failing
            # on several candidates in a row is a structural problem
            fails = fails + 1 if new is None else 0
            journal(div, **rec, verdict="reject", reason=reason)
            log(div, f"  reject  {reason[:120]}")
            if fails >= cfg["defaults"].get("max_consecutive_failures", 3):
                alert(div, f"eval failed on {fails} consecutive candidates; halting")
                return
    log(div, "stop file seen; exiting")


# ---------------------------------------------------------------- tend pattern

MECHANIC_PROMPT = """The {div} pipeline needs repair: {reason}

Progress file:
{progress}

Last log lines:
{log}

Latest validator output:
{validation}

Fix it so the pipeline can resume, then stop."""


def tend(cfg: dict, div: str, snap: Path, snap_hash: str) -> None:
    d = cfg["divisions"][div]
    wt = ROOT / d["worktree"]
    validator = snap / Path(d["validate"]).name
    progress = Path(fmt(d["progress"]))
    log_path = Path(fmt(d["log"]))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    every = d.get("check_every_min", 20) * 60
    stale = d.get("stale_after_min", 15) * 60
    max_fail = cfg["defaults"].get("max_consecutive_failures", 3)
    proc: subprocess.Popen | None = None
    logf = None
    last_sig, same_sig, checks, limit_streak = None, 0, 0, 0
    started_at = 0.0
    validation: dict = {}

    def start() -> subprocess.Popen:
        nonlocal logf, started_at
        started_at = time.time()
        if logf:
            logf.close()
        logf = open(log_path, "a", encoding="utf-8")
        logf.write(f"\n===== start {now()} =====\n")
        logf.flush()
        log(div, "pipeline start: " + " ".join(fmt(x) for x in d["run"]))
        return subprocess.Popen([fmt(x) for x in d["run"]], cwd=wt, stdout=logf,
                                stderr=subprocess.STDOUT, start_new_session=not IS_WIN)

    def validate() -> dict:
        v = run_eval(d, validator, ["--data", str(progress.parent)], wt)
        journal(div, kind="validate", **{k: v.get(k) for k in ("ok", "rows", "valid_pct", "dupes", "skipped", "error")})
        return v

    def repair(reason: str) -> str:
        """One mechanic session. 'fixed' | 'nochange' | 'reverted' | 'auth' | 'stop'."""
        nonlocal limit_streak
        while True:
            base = git(wt, "rev-parse", "HEAD")
            prompt = MECHANIC_PROMPT.format(
                div=div, reason=reason, progress=json.dumps(read_json(progress) or {}, indent=1),
                log=tail(log_path, 80), validation=json.dumps(validation, indent=1)[:1500])
            res = claude(cfg, wt, prompt=prompt, model=d["model"], agent="mechanic",
                         fallback=d.get("fallback_model"), system_file=PROMPTS / "mechanic.md",
                         budget=d.get("budget_usd"))
            kind = res["_kind"]
            rec = dict(kind="repair", reason=reason[:200], session=res.get("session_id"),
                       cost=cost(res), secs=res.get("_secs"))
            if kind == "limit":
                reset_to(wt, base)
                wait = limit_wait(cfg, res, limit_streak)
                limit_streak += 1
                journal(div, **rec, verdict="limit", wait_min=round(wait / 60))
                log(div, f"usage limit; sleeping {wait / 60:.0f} min")
                if nap(div, wait):
                    return "stop"
                continue
            limit_streak = 0
            if kind == "auth":
                reset_to(wt, base)
                return "auth"
            collect_followups(div, wt)
            paths = changed_paths(wt, base)
            if any(p.replace("\\", "/").startswith("eval/") for p in paths):
                reset_to(wt, base)
                journal(div, **rec, verdict="reverted", note="touched eval/")
                return "reverted"
            if not paths:
                journal(div, **rec, verdict="nochange", note=str(res.get("result", ""))[:300])
                return "nochange"
            smoke = sh([fmt(x) for x in d["smoke"]], wt, timeout=d.get("smoke_timeout_min", 5) * 60)
            if smoke.returncode != 0:
                reset_to(wt, base)
                journal(div, **rec, verdict="reverted", note="smoke failed: " + smoke.stdout[-200:] + smoke.stderr[-200:])
                return "reverted"
            git(wt, "add", "-A")
            git(wt, "commit", "-q", "--no-verify", "-m", f"{div} mechanic: {reason[:70]}")
            journal(div, **rec, verdict="fixed", sha=git(wt, "rev-parse", "--short", "HEAD"))
            return "fixed"

    try:
        while not stop_requested(div):
            if tree_hash(snap) != snap_hash:
                alert(div, "frozen validator snapshot was modified during the run; halting")
                return
            prog = read_json(progress) or {}
            alive = proc is not None and proc.poll() is None

            if not alive and prog.get("status") == "done":
                v = validate()
                log(div, f"pipeline finished: rows={v.get('rows')} valid_pct={v.get('valid_pct')}")
                return
            if proc is None:
                proc = start()
            else:
                reason = None
                if not alive:
                    sig = (tail(log_path, 1) or "").strip()[:200]
                    reason = f"pipeline exited rc={proc.returncode}: {sig}"
                else:
                    touched = progress.stat().st_mtime if progress.exists() else 0.0
                    age = time.time() - max(touched, started_at)
                    if age > stale:
                        kill_tree(proc.pid)
                        proc.wait()
                        sig = f"hung: no progress for {age / 60:.1f} min"
                        reason = f"pipeline {sig}"
                    else:
                        checks += 1
                        if checks % d.get("validate_every_checks", 3) == 0:
                            validation = validate()
                            pct = validation.get("valid_pct")
                            if validation.get("ok") is False or (pct is not None and pct < d.get("min_valid_pct", 95)):
                                kill_tree(proc.pid)
                                proc.wait()
                                sig = f"quality: valid_pct={pct}"
                                reason = f"output failing validation ({sig})"
                        journal(div, kind="heartbeat", done=prog.get("done"), total=prog.get("total"))
                if reason:
                    same_sig = same_sig + 1 if sig == last_sig else 1
                    last_sig = sig
                    log(div, reason)
                    if same_sig > max_fail:
                        alert(div, f"same failure {same_sig}x after repairs: {sig}; halting")
                        return
                    r = repair(reason)
                    log(div, f"repair: {r}")
                    if r == "auth":
                        alert(div, "claude login expired: run `claude` then /login in a terminal")
                        return
                    if r == "stop":
                        return
                    proc = start()
            if nap(div, every):
                break
        log(div, "stop file seen; stopping pipeline")
    finally:
        if proc is not None and proc.poll() is None:
            kill_tree(proc.pid)
        if logf:
            logf.close()


# ---------------------------------------------------------------- preflight / setup / status

def preflight(cfg: dict, div: str) -> tuple[bool, dict, Path | None, str]:
    d = cfg["divisions"].get(div)
    ok = True
    base_eval: dict = {}
    snap, snap_hash = None, ""

    def check(name: str, passed: bool, detail: str = "", show: bool = False) -> bool:
        nonlocal ok
        ok &= passed
        print(f"  [{'ok' if passed else 'FAIL'}] {name}" + (f": {detail}" if detail and (show or not passed) else ""))
        return passed

    print(f"preflight: {div}")
    if not check("division in config", d is not None and d.get("pattern") in ("climb", "tend"),
                 "pattern must be climb or tend"):
        return False, {}, None, ""
    wt = ROOT / d["worktree"]
    if not check("worktree exists", wt.exists(), str(wt) + " (run: python ops/orchestrate.py setup)"):
        return False, {}, None, ""
    check("worktree clean", not sh(["git", "status", "--porcelain"], wt).stdout.strip(),
          "commit or stash first")
    m = sh(["git", "merge", "--no-edit", "main"], wt)
    if m.returncode != 0:
        sh(["git", "merge", "--abort"], wt)
    check("merged latest main", m.returncode == 0, m.stdout.strip()[-200:])
    check("MISSION.md filled in", "<one paragraph" not in (ROOT / "MISSION.md").read_text(encoding="utf-8"))

    auth = claude(cfg, ROOT, prompt="Reply with exactly: ok", model="haiku", budget=0.05,
                  max_turns=1, wall_min=2, overnight=False)
    check("claude CLI login", auth["_kind"] == "ok",
          "run `claude` then /login in a terminal" if auth["_kind"] == "auth" else str(auth.get("result", ""))[:160])

    snap, snap_hash = snapshot_eval(div)
    if d["pattern"] == "climb":
        base_eval = run_eval(d, snap / Path(d["eval"]).name, ["--repo", str(wt)], wt)
        check("eval runs on current branch", bool(base_eval.get("ok")) and "headline" in base_eval,
              json.dumps(base_eval)[:200], show=True)
        if next_task(div) is None:
            print("  [note] queue empty; the planner will fill it on the first iteration")
    else:
        smoke = sh([fmt(x) for x in d["smoke"]], wt, timeout=d.get("smoke_timeout_min", 5) * 60)
        check("smoke run passes", smoke.returncode == 0, (smoke.stdout + smoke.stderr).strip()[-200:])
    return ok, base_eval, snap, snap_hash


def setup(cfg: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        git(ROOT, "rev-parse", "HEAD")
    except RuntimeError:
        sys.exit("make a first commit on main before setup")
    for name, d in cfg["divisions"].items():
        div_state(name)
        qp = queue_path(name)
        if not qp.exists():
            qp.write_text(f"# Queue: {name}\n\n## Done\n\n## Todo\n", encoding="utf-8")
        wt = ROOT / d["worktree"]
        if wt.exists():
            print(f"  {name}: worktree exists at {wt}")
            continue
        exists = sh(["git", "rev-parse", "--verify", d["branch"]], ROOT).returncode == 0
        args = ["worktree", "add", str(wt), d["branch"]] if exists else \
               ["worktree", "add", "-b", d["branch"], str(wt), "main"]
        git(ROOT, *args)
        print(f"  {name}: created {wt} on {d['branch']}")


def status(cfg: dict) -> None:
    for name, d in cfg["divisions"].items():
        s = STATE / name
        lock = read_json(s / "lock")
        running = bool(lock and pid_alive(lock.get("pid", -1)))
        q = (s / "queue.md").read_text(encoding="utf-8").splitlines() if (s / "queue.md").exists() else []
        todo = sum(1 for l in q if l.startswith("- [ ]"))
        done = sum(1 for l in q if l.startswith("- [x]"))
        blocked = sum(1 for l in q if l.startswith("- [!]"))
        recs = []
        if (s / "journal.jsonl").exists():
            for l in (s / "journal.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    recs.append(json.loads(l))
                except ValueError:
                    pass
        day_ago = (dt.datetime.now().astimezone() - dt.timedelta(hours=24)).isoformat()
        spent = sum(r.get("cost") or 0 for r in recs if r.get("ts", "") >= day_ago)
        verdicts: dict[str, int] = {}
        for r in recs:
            if r.get("ts", "") >= day_ago and r.get("kind") in ("iter", "repair") and r.get("verdict"):
                verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        recs = [r for r in recs if r.get("kind") not in ("start", "end", "heartbeat")]
        print(f"{name:<9} {d.get('pattern', 'day'):<6} {'RUNNING' if running else 'idle':<8} "
              f"queue {done} done / {todo} todo / {blocked} blocked   24h cost ${spent:.2f}  {verdicts}")
        nt = next_task(name)
        if nt:
            print(f"          next: {nt[1][:100]}")
        if recs:
            r = recs[-1]
            print(f"          last: {r.get('ts', '')[11:19]} {r.get('kind')} {r.get('verdict', '')} "
                  f"headline={r.get('headline', '-')} best={r.get('best', '-')}")
    alerts = STATE / "ALERTS.md"
    if alerts.exists() and alerts.read_text(encoding="utf-8").strip():
        print("\nALERTS (delete ops/state/ALERTS.md once handled):")
        print("\n".join(alerts.read_text(encoding="utf-8").splitlines()[-8:]))
    stops = sorted(p.name for p in STATE.glob("STOP.*"))
    if stops:
        print("\nkill files present: " + ", ".join(stops))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "preflight", "run", "plan", "status", "paths"])
    ap.add_argument("div", nargs="?")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # task text can hold chars cp1252 can't print
    cfg = load_config()
    if a.cmd == "setup":
        setup(cfg)
        return 0
    if a.cmd == "status":
        status(cfg)
        return 0
    if not a.div or a.div not in cfg["divisions"]:
        sys.exit(f"division required, one of: {', '.join(cfg['divisions'])}")
    if a.cmd == "paths":
        s = div_state(a.div)
        print(json.dumps({"queue": str(s / "queue.md"), "journal": str(s / "journal.jsonl"),
                          "inbox": str(s / "inbox.md"), "loop_log": str(s / "loop.log"),
                          "worktree": str(ROOT / cfg["divisions"][a.div]["worktree"]),
                          "stop_file": str(STATE / f"STOP.{a.div}")}, indent=1))
        return 0
    if a.cmd == "plan":
        with Lock(a.div):
            return 0 if plan(cfg, a.div) == "ok" else 1
    if a.cmd == "preflight":
        return 0 if preflight(cfg, a.div)[0] else 1

    with Lock(a.div):
        (STATE / f"STOP.{a.div}").unlink(missing_ok=True)
        ok, base_eval, snap, snap_hash = preflight(cfg, a.div)
        if not ok:
            print("preflight failed; not starting")
            return 1
        d = cfg["divisions"][a.div]
        journal(a.div, kind="start", pattern=d["pattern"], headline=base_eval.get("headline"))
        try:
            if d["pattern"] == "climb":
                climb(cfg, a.div, base_eval, snap, snap_hash)
            else:
                tend(cfg, a.div, snap, snap_hash)
        except Exception as e:  # anything unexpected: record it, never die silently
            alert(a.div, f"orchestrator crashed: {type(e).__name__}: {e}")
            raise
        finally:
            journal(a.div, kind="end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
