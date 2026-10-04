"""Who&When loader: raw JSON -> common event IR (analysis/lib/ir.py).

Source: C:/Swarms/data/who-and-when/Who&When/{Algorithm-Generated,Hand-Crafted}/<n>.json (184 tasks, read-only).
Outputs (all rebuilt end to end by main(); idempotent, deterministic):
  analysis/cache/samples/whowhen.json      population + disjoint A/B session lists (lib/sample.py)
  analysis/cache/whowhen_A.parquet         IR rows for split A sessions
  analysis/cache/whowhen_B.parquet         IR rows for split B sessions
  analysis/cache/whowhen_labels.json       session_id -> ground-truth failure attribution
  analysis/out/build/whowhen_build.json    raw counts (no interpretation)

Session, stratum, ordering
  session_id = '<split>/<file stem>' (e.g. 'Hand-Crafted/12'). stratum = split. sampling length = len(history).
  Files are processed in numeric stem order. Events follow history order; seq = 0..n-1 per session.
  When one history message yields two events (AG expert message with code), the assistant event comes first,
  then the call. Every event carries extra.step = its history index (the index mistake_step refers to) and
  extra.agent = the speaker. There are no timestamps anywhere: ts = None, ts_kind = 'none'.
  is_subagent = False for every event (Who&When agents are peers; there is no sidechain).
  agent_id / uuid / parent_uuid / usage / model / api_msg_id / request_id / stderr are None (no source field).
  model is None even though Hand-Crafted log lines mention gpt-4o: that is log text, not a per-event field.

Algorithm-Generated (AG2 CaptainAgent group chat; message = {content, name, role})
  `role` is from the logging agent's point of view and is ignored ('user'/'assistant' both occur for experts).
  Expert message (name != 'Computer_terminal')
    -> assistant event, text = full content.
    -> plus one call event when the content holds >= 1 fenced block matched by AG2's own extractor pattern
       CODE_BLOCK_PATTERN = ```[ \\t]*(\\w+)?[ \\t]*\\r?\\n(.*?)\\r?\\n[ \\t]*```  (any language, including none/plaintext,
       because that is what the harness extracts and tries to run; unknown languages come back as
       'exitcode: 1 ... unknown language'). tool = tool_raw = 'code_exec', call_id = 'step:<index>',
       args = JSON list of {"lang": <fence language or null>, "code": <block body>} in source order (one call per
       message, all blocks together, because the terminal answers the whole message with one reply).
       command = None (blocks may mix python and sh; the code is in args).
       extra.executed = whether the very next message is a Computer_terminal 'exitcode:' reply.
       extra.unexecuted = 'next_speaker_not_terminal' | 'history_end' when not executed. Such calls stay unpaired:
       the code was proposed but the harness never ran it.
    Step 0 is the CaptainAgent-composed task prompt ('You are given: (1) a task and advises from your manager...'),
    attributed by the source to the first expert. It is mapped like any expert message (the annotators attribute
    step-0 mistakes to that expert) and flagged extra.task_prompt = true so probes can exclude or reclassify it.
  Computer_terminal message
    'exitcode: N (execution succeeded|failed)\\nCode output: ...' -> result, call_id = 'step:<index-1>' when the
       previous message carried a call (always true in this data), tool = 'code_exec', text = full content,
       exit_code = N from that harness-written header, native_error = (N != 0), extra.marker = ir.error_marker(text).
    'There is no code from the last 1 message for me to execute...' -> system (harness text the agents see; there
       is no call to pair it with). extra.harness_note = 'terminal_no_code'.
    anything else from Computer_terminal -> system with extra.harness_note = 'terminal_other' (counted; 0 expected).

Hand-Crafted (Magentic-One; message = {content, role}; no name)
  'human'                               -> user (always step 0).
  'Orchestrator (thought)'              -> assistant. extra.thought_kind = plan | ledger | next_speaker | replan_notice |
                                           new_plan | request_satisfied | replan_exceeded | other (first-line template).
  'Orchestrator (-> X)'                 -> call. call_id = 'step:<index>', tool_raw = X, tool = websurfer | filesurfer |
                                           computerterminal for those agents, 'subagent' for Assistant, else X lowercased.
                                           args = {"target": X, "instruction": content}; text = None.
  'Orchestrator (termination condition)'-> system (harness-written stop reason + run-log tail). harness_note = 'termination_condition'.
  any other 'Orchestrator (...)' role   -> assistant with thought_kind = 'other_orchestrator_role' (counted; 0 expected).
  agent message (role = X, e.g. WebSurfer) -> result paired to the open call iff the most recent call is to X and has
       not been answered. A new call closes any still-open call as unanswered ('superseded'); a call open at the end
       of history is unanswered ('history_end'). An agent message with no matching open call is a result with
       call_id None (counted). Results to the orchestrator's call are 1 or 2 messages after it (a 'Next speaker X'
       thought may sit between).
       ComputerTerminal: exit_code parsed from the harness template 'The script ran, then exited with Unix exit code: N'
       or 'The script ran but produced no output to console. The Unix exit code was: N'; native_error = (N != 0).
       'No code block detected in the messages...' -> harness_note 'terminal_no_code' (exit_code None).
       FileSurfer 'File surfer encountered an error ...' -> harness_note 'filesurfer_error' (native_error stays None:
       no harness flag, only text).
  Log leakage: the dataset's Hand-Crafted messages sometimes contain process stderr/stdout of the run script
       (autogen 'UserWarning: Resolved model mismatch' lines, 'Error processing publish message' + traceback,
       'FINAL ANSWER: ...', 'SCENARIO.PY COMPLETE !#!#'). Text is kept verbatim; on non-ComputerTerminal messages
       extra.log_leak = sorted leak types found and extra.log_leak_at = char offset of the first leaked line
       (text[:log_leak_at] drops the leaked tail; it is approximate when a leak sits mid-message).

Not emitted: the top-level `question` (it is repeated inside history[0]) and AG `system_prompt` (a dict of
  per-expert role prompts; it is per-agent configuration, not a history step, so emitting it would make the IR
  disagree with mistake_step indexing). Both stay available in the raw files.

Ground truth (analysis/cache/whowhen_labels.json): session_id -> {split, mistake_agent, mistake_step (int, history
  index), mistake_reason, is_correct (AG 'is_correct' / HC 'is_corrected'), is_correct_src_key, question_ID, level,
  ground_truth, speaker_at_step, agent_vs_speaker ('match'|'case_insensitive_match'|'mismatch'), mistake_type/labels
  when present}. Labels are never written into the IR rows.
"""
import collections
import glob
import json
import os
import re

import pandas as pd

from analysis.lib import ir, sample

CORPUS = "whowhen"
DATA_ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
RAW = os.path.join(DATA_ROOT, "who-and-when", "Who&When")
RAW_PARQUET = os.path.join(DATA_ROOT, "who-and-when")
SPLITS = ("Algorithm-Generated", "Hand-Crafted")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # analysis/
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "out", "build")

# AG2 autogen.code_utils.CODE_BLOCK_PATTERN
FENCE = re.compile(r"```[ \t]*(\w+)?[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.S)
AG_EXIT = re.compile(r"^exitcode: (-?\d+) \((execution succeeded|execution failed)\)\nCode output:")
AG_NO_CODE = "There is no code from the last"
HC_CALL = re.compile(r"^Orchestrator \(-> (.+)\)$")
HC_TOOL = {"WebSurfer": "websurfer", "FileSurfer": "filesurfer", "ComputerTerminal": "computerterminal", "Assistant": "subagent"}
HC_CT_EXIT = [re.compile(r"^The script ran, then exited with (?:Unix |POSIX )?exit code: (-?\d+)"),
              re.compile(r"^The script ran but produced no output to console\. The (?:Unix |POSIX )?exit code was: (-?\d+)")]
HC_LEAK = [("warning", re.compile(r"^\S+\.py:\d+: \w*Warning: ", re.M)),
           ("publish_error", re.compile(r"^Error processing publish message$", re.M)),
           ("traceback", re.compile(r"^Traceback \(most recent call last\):$", re.M)),
           ("final_answer", re.compile(r"^FINAL ANSWER:", re.M)),
           ("run_trailer", re.compile(r"^(?:SCENARIO\.PY|RUN\.SH) (?:COMPLETE|EXITED)", re.M))]


def _stem_key(path):
    s = os.path.splitext(os.path.basename(path))[0]
    return (0, int(s), s) if s.isdigit() else (1, 0, s)


def iter_raw():
    """Yield (split, stem, path, record) in deterministic order."""
    for split in SPLITS:
        for path in sorted(glob.glob(os.path.join(RAW, split, "*.json")), key=_stem_key):
            with open(path, encoding="utf-8") as f:
                yield split, os.path.splitext(os.path.basename(path))[0], path, json.load(f)


class _Session:
    def __init__(self, sid, stratum):
        self.sid, self.stratum, self.events = sid, stratum, []

    def emit(self, kind, step, agent, extra=None, **kw):
        ex = {"step": step, "agent": agent}
        if extra:
            ex.update(extra)
        ev = {c: None for c in ir.COLUMNS}
        ev.update({"corpus": CORPUS, "session_id": self.sid, "stratum": self.stratum, "seq": len(self.events),
                   "kind": kind, "ts": None, "ts_kind": "none", "is_subagent": False, "extra": ir.j(ex)})
        ev.update(kw)
        self.events.append(ev)
        return ev


def _thought_kind(text):
    t = text.lstrip()
    for prefix, k in (("Initial plan", "plan"), ("Updated Ledger", "ledger"), ("Next speaker", "next_speaker"),
                      ("Stalled", "replan_notice"), ("New plan", "new_plan"), ("Request satisfied", "request_satisfied"),
                      ("Replan counter exceeded", "replan_exceeded")):
        if t.startswith(prefix):
            return k
    return "other"


def _leaks(text):
    found, first = [], None
    for name, rx in HC_LEAK:
        m = rx.search(text)
        if m:
            found.append(name)
            first = m.start() if first is None else min(first, m.start())
    return sorted(found), first


def parse_ag(sid, rec, st):
    """Algorithm-Generated record -> events. st: Counter of exceptions/observations (mutated)."""
    s = _Session(sid, "Algorithm-Generated")
    h = rec["history"]
    open_call = None  # step index of the call made by the previous message, if any
    for i, m in enumerate(h):
        name, content = m.get("name"), m.get("content") or ""
        st[f"role:{'terminal' if name == 'Computer_terminal' else 'expert'}:{m.get('role')}"] += 1
        if name == "Computer_terminal":
            mm = AG_EXIT.match(content)
            if mm:
                code = int(mm.group(1))
                if (code == 0) != (mm.group(2) == "execution succeeded"):
                    st["ag_exit_code_word_mismatch"] += 1
                if open_call == i - 1:
                    cid = f"step:{i - 1}"
                else:
                    cid = None
                    st["ag_result_without_call"] += 1
                s.emit("result", i, name, {"marker": ir.error_marker(content), "exec_status": mm.group(2)},
                       tool="code_exec", tool_raw="code_exec", call_id=cid, text=content,
                       native_error=code != 0, exit_code=code)
            elif content.startswith(AG_NO_CODE):
                st["ag_terminal_no_code"] += 1
                s.emit("system", i, name, {"harness_note": "terminal_no_code"}, text=content)
            else:
                st["ag_terminal_other"] += 1
                s.emit("system", i, name, {"harness_note": "terminal_other"}, text=content)
            open_call = None
            continue
        # expert message
        if name is None or not str(name).endswith("Expert"):
            st["ag_speaker_name_not_expert"] += 1
        if content.strip() == "":
            st["ag_empty_expert_message"] += 1
        if "exitcode:" in content:
            st["ag_expert_text_contains_exitcode"] += 1
            if i == 0:
                st["ag_task_prompt_contains_exitcode"] += 1
        if content.count("```") and not FENCE.search(content):
            st["ag_backticks_without_extractable_block"] += 1
        task_prompt = {"task_prompt": True} if i == 0 else None
        s.emit("assistant", i, name, task_prompt, text=content)
        blocks = FENCE.findall(content)
        open_call = None
        if blocks:
            nxt = h[i + 1] if i + 1 < len(h) else None
            executed = bool(nxt and nxt.get("name") == "Computer_terminal" and AG_EXIT.match(nxt.get("content") or ""))
            langs = [lang or None for lang, _ in blocks]
            ex = {"langs": langs, "n_blocks": len(blocks), "executed": executed}
            if not executed:
                ex["unexecuted"] = "history_end" if nxt is None else "next_speaker_not_terminal"
                st[f"ag_call_unexecuted:{ex['unexecuted']}"] += 1
            if task_prompt:
                ex.update(task_prompt)
                st["ag_task_prompt_with_call"] += 1
            st[f"ag_call_n_blocks:{len(blocks)}"] += 1
            for lang in langs:
                st[f"ag_block_lang:{lang}"] += 1
            if len(set(langs)) > 1:
                st["ag_call_mixed_langs"] += 1
            s.emit("call", i, name, ex, tool="code_exec", tool_raw="code_exec", call_id=f"step:{i}",
                   args=ir.j([{"lang": lang or None, "code": code} for lang, code in blocks]))
            open_call = i
    if len(h) == 10:
        st["ag_history_len_eq_10"] += 1
    return s.events


def parse_hc(sid, rec, st):
    """Hand-Crafted record -> events."""
    s = _Session(sid, "Hand-Crafted")
    h = rec["history"]
    open_call = None  # (step, target)
    for i, m in enumerate(h):
        role, content = m.get("role") or "", m.get("content") or ""
        st[f"role:{role}"] += 1
        leak, leak_at = (_leaks(content) if role != "ComputerTerminal" else ([], None))
        lx = {"log_leak": leak, "log_leak_at": leak_at} if leak else {}
        for k in leak:
            st[f"hc_log_leak:{'Orchestrator (->)' if role.startswith('Orchestrator (->') else role}:{k}"] += 1
        if leak:
            st["hc_messages_with_log_leak"] += 1
        cm = HC_CALL.match(role)
        if role == "human":
            if i != 0:
                st["hc_human_not_first"] += 1
            s.emit("user", i, "human", lx, text=content)
        elif cm:
            target = cm.group(1)
            if open_call is not None:
                st["hc_call_unanswered:superseded"] += 1
            s.emit("call", i, "Orchestrator", {"target": target, **lx}, tool=HC_TOOL.get(target, target.lower()),
                   tool_raw=target, call_id=f"step:{i}", args=ir.j({"target": target, "instruction": content}))
            open_call = (i, target)
        elif role == "Orchestrator (thought)":
            tk = _thought_kind(content)
            st[f"hc_thought_kind:{tk}"] += 1
            s.emit("assistant", i, "Orchestrator", {"thought_kind": tk, **lx}, text=content)
        elif role == "Orchestrator (termination condition)":
            s.emit("system", i, "Orchestrator", {"harness_note": "termination_condition", **lx}, text=content)
        elif role.startswith("Orchestrator"):
            st["hc_other_orchestrator_role"] += 1
            s.emit("assistant", i, "Orchestrator", {"thought_kind": "other_orchestrator_role", "role_raw": role, **lx}, text=content)
        else:
            if open_call is not None and open_call[1] == role:
                cid = f"step:{open_call[0]}"
                st[f"hc_call_result_gap:{i - open_call[0]}"] += 1
                open_call = None
            else:
                cid = None
                st["hc_result_without_call"] += 1
            ex = {"marker": ir.error_marker(content), **lx}
            exit_code, native = None, None
            if role == "ComputerTerminal":
                for rx in HC_CT_EXIT:
                    mm = rx.match(content)
                    if mm:
                        exit_code = int(mm.group(1))
                        native = exit_code != 0
                        break
                if exit_code is None:
                    if content.startswith("No code block detected"):
                        ex["harness_note"] = "terminal_no_code"
                        st["hc_terminal_no_code"] += 1
                    else:
                        st["hc_terminal_unparsed"] += 1
            elif role == "FileSurfer" and content.startswith("File surfer encountered an error"):
                ex["harness_note"] = "filesurfer_error"
                st["hc_filesurfer_error"] += 1
            if role not in HC_TOOL:
                st[f"hc_unknown_agent_role:{role}"] += 1
            s.emit("result", i, role, ex, tool=HC_TOOL.get(role, role.lower()), tool_raw=role, call_id=cid,
                   text=content, native_error=native, exit_code=exit_code)
    if open_call is not None:
        st["hc_call_unanswered:history_end"] += 1
    return s.events


def _label(split, sid, rec):
    h = rec["history"]
    step = int(rec["mistake_step"])
    spk = None
    if 0 <= step < len(h):
        spk = h[step].get("name") if split == "Algorithm-Generated" else h[step].get("role")
    agent = spk
    if split == "Hand-Crafted" and spk and spk.startswith("Orchestrator"):
        agent = "Orchestrator"
    ma = rec.get("mistake_agent")
    vs = "match" if agent == ma else ("case_insensitive_match" if agent and ma and agent.lower() == ma.lower() else "mismatch")
    key = "is_correct" if "is_correct" in rec else "is_corrected"
    lab = {"split": split, "mistake_agent": ma, "mistake_step": step, "mistake_reason": rec.get("mistake_reason"),
           "is_correct": rec.get(key), "is_correct_src_key": key, "question_ID": rec.get("question_ID"),
           "level": rec.get("level"), "ground_truth": rec.get("ground_truth", rec.get("groundtruth")),
           "history_len": len(h), "speaker_at_step": spk, "agent_vs_speaker": vs}
    for k in ("mistake_type", "labels"):
        if k in rec:
            lab[k] = rec[k]
    return lab


def _landing(events, step):
    """Classify the history step a mistake points at by the IR kinds emitted for it."""
    kinds = sorted({e["kind"] for e in events if json.loads(e["extra"])["step"] == step})
    if not kinds:
        return "out_of_range", kinds
    if "call" in kinds:
        return "call", kinds
    if "result" in kinds:
        return "result", kinds
    if kinds == ["assistant"]:
        return "narration", kinds
    return "+".join(kinds), kinds


def _parquet_crosscheck(raw_by_split):
    """Compare the JSON files with the HF parquet copies of the same dataset (by question_ID + history)."""
    out = {}
    for split in SPLITS:
        p = os.path.join(RAW_PARQUET, f"{split}.parquet")
        if not os.path.exists(p):
            out[split] = {"parquet_present": False}
            continue
        df = pd.read_parquet(p)
        pq = {}
        for _, r in df.iterrows():
            pq.setdefault(r["question_ID"], []).append([{k: v for k, v in dict(m).items() if v is not None} for m in r["history"]])
        js = collections.defaultdict(list)
        for rec in raw_by_split[split]:
            js[rec["question_ID"]].append([{k: v for k, v in m.items() if v is not None} for m in rec["history"]])
        ident = 0
        for q, hs in js.items():
            for hist in hs:
                if hist in pq.get(q, []):
                    ident += 1
        out[split] = {"parquet_present": True, "parquet_rows": int(len(df)), "json_files": sum(len(v) for v in js.values()),
                      "json_question_ids_distinct": len(js), "parquet_question_ids_distinct": len(pq),
                      "question_ids_in_both": len(set(js) & set(pq)), "json_records_with_identical_parquet_history": ident}
    return out


def main():
    os.makedirs(os.path.join(CACHE, "samples"), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    st = {s: collections.Counter() for s in SPLITS}
    # exception counters reported even when zero, so a 0 in the report is a measured 0
    for k in ("ag_result_without_call", "ag_terminal_other", "ag_exit_code_word_mismatch", "ag_call_unexecuted:history_end",
              "ag_call_unexecuted:next_speaker_not_terminal", "ag_task_prompt_with_call"):
        st["Algorithm-Generated"][k] += 0
    for k in ("hc_result_without_call", "hc_human_not_first", "hc_other_orchestrator_role", "hc_terminal_unparsed",
              "hc_call_unanswered:superseded", "hc_call_unanswered:history_end"):
        st["Hand-Crafted"][k] += 0
    events_by_sid, labels, pop_rows, raw_by_split = {}, {}, [], collections.defaultdict(list)
    for split, stem, path, rec in iter_raw():
        sid = f"{split}/{stem}"
        raw_by_split[split].append(rec)
        evs = (parse_ag if split == "Algorithm-Generated" else parse_hc)(sid, rec, st[split])
        events_by_sid[sid] = evs
        labels[sid] = _label(split, sid, rec)
        pop_rows.append({"session_id": sid, "stratum": split, "length": len(rec["history"])})
        st[split]["messages"] += len(rec["history"])
        st[split]["sessions"] += 1

    # ---- sample ----
    pop = pd.DataFrame(pop_rows)
    smp = sample.draw(pop, CORPUS)
    sample.save(smp, os.path.join(CACHE, "samples", f"{CORPUS}.json"))
    frames = {}
    for part in ("A", "B"):
        evs = [e for sid in smp[part] for e in events_by_sid[sid]]
        df = ir.to_frame(evs)
        frames[part] = (df, ir.validate(df))
        df.to_parquet(os.path.join(CACHE, f"{CORPUS}_{part}.parquet"), index=False)
    with open(os.path.join(CACHE, f"{CORPUS}_labels.json"), "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=1, ensure_ascii=False)

    # ---- validate the full population frame too (all 184 sessions) ----
    full = ir.to_frame([e for evs in events_by_sid.values() for e in evs])
    full_counts = ir.validate(full)
    assert set(smp["A"]).isdisjoint(smp["B"])

    # ---- report ----
    rep = {"corpus": CORPUS, "source": RAW, "population_sessions": int(len(pop)), "full_population_validate": full_counts,
           "sample": {"seed": smp["seed"], "rule": smp["rule"], "A_n": len(smp["A"]), "B_n": len(smp["B"]),
                      "A_by_split": dict(collections.Counter(s.split("/")[0] for s in smp["A"])),
                      "B_by_split": dict(collections.Counter(s.split("/")[0] for s in smp["B"])),
                      "not_in_A_or_B": int(len(pop) - len(smp["A"]) - len(smp["B"]))},
           "cache": {p: {"rows": int(len(frames[p][0])), "validate": frames[p][1]} for p in frames},
           "per_split": {}}
    for split in SPLITS:
        sids = [s for s in events_by_sid if s.startswith(split + "/")]
        evs = [e for s in sids for e in events_by_sid[s]]
        calls = [e for e in evs if e["kind"] == "call"]
        results = [e for e in evs if e["kind"] == "result"]
        paired_ids = {(e["session_id"], e["call_id"]) for e in results if e["call_id"] is not None}
        call_ids = {(e["session_id"], e["call_id"]) for e in calls}
        unpaired_calls = [e for e in calls if (e["session_id"], e["call_id"]) not in paired_ids]
        unpaired_results = [e for e in results if e["call_id"] is None or (e["session_id"], e["call_id"]) not in call_ids]
        exit_hist = collections.Counter("none" if e["exit_code"] is None else str(e["exit_code"]) for e in results)
        landing, landing_detail, landing_by_agent_vs = collections.Counter(), collections.Counter(), collections.Counter()
        for sid in sids:
            cat, kinds = _landing(events_by_sid[sid], labels[sid]["mistake_step"])
            landing[cat] += 1
            landing_detail["+".join(kinds) or "none"] += 1
            landing_by_agent_vs[f"{cat}|{labels[sid]['agent_vs_speaker']}"] += 1
        tool_counts = collections.Counter(e["tool"] for e in calls)
        res_tool = collections.Counter(e["tool"] for e in results)
        rep["per_split"][split] = {
            "sessions": len(sids), "messages": st[split]["messages"], "events": len(evs),
            "events_by_kind": dict(collections.Counter(e["kind"] for e in evs)),
            "calls": len(calls), "results": len(results), "calls_paired": len(calls) - len(unpaired_calls),
            "unpaired_calls": len(unpaired_calls), "unpaired_results": len(unpaired_results),
            "duplicate_call_ids": len(calls) - len(call_ids),
            "results_sharing_a_call_id": sum(1 for e in results if e["call_id"] is not None) - len(paired_ids),
            "calls_by_tool": dict(tool_counts), "results_by_tool": dict(res_tool),
            "native_error_true": sum(1 for e in results if e["native_error"] is True),
            "exit_code_histogram": dict(sorted(exit_hist.items())),
            "mistake_step_landing": dict(landing), "mistake_step_landing_kinds": dict(landing_detail),
            "mistake_step_landing_by_agent_vs_speaker": dict(landing_by_agent_vs),
            "agent_vs_speaker": dict(collections.Counter(labels[s]["agent_vs_speaker"] for s in sids)),
            "is_correct": {str(k): v for k, v in collections.Counter(labels[s]["is_correct"] for s in sids).items()},
            "is_correct_src_key": dict(collections.Counter(labels[s]["is_correct_src_key"] for s in sids)),
            "mistake_step_eq_0": sum(1 for s in sids if labels[s]["mistake_step"] == 0),
            "mistake_step_eq_last": sum(1 for s in sids if labels[s]["mistake_step"] == labels[s]["history_len"] - 1),
            "label_optional_keys_present": dict(collections.Counter(k for s in sids for k in ("mistake_type", "labels", "level")
                                                                    if labels[s].get(k) is not None)),
            "history_len": {"min": min(labels[s]["history_len"] for s in sids), "max": max(labels[s]["history_len"] for s in sids)},
            "observations": dict(sorted(st[split].items())),
        }
    # lengths whose sessions are split across tercile cells by sample.draw (it ranks with method='first', i.e. ties
    # are broken by population row order); replicated here so the effect on cells is on record.
    q = pop["length"].rank(method="first", pct=True)
    terc = pd.Series(["short" if x <= 1 / 3 else ("mid" if x <= 2 / 3 else "long") for x in q], index=pop.index)
    ties = {}
    for (stratum, length), g in pop.assign(t=terc).groupby(["stratum", "length"]):
        if g["t"].nunique() > 1:
            ties[f"{stratum}|len={length}"] = dict(collections.Counter(g["t"]))
    rep["sample"]["length_ties_split_across_terciles"] = ties
    rep["parquet_crosscheck"] = _parquet_crosscheck(raw_by_split)
    with open(os.path.join(OUT, f"{CORPUS}_build.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False, default=lambda o: int(o) if hasattr(o, "__int__") else str(o))
    print(json.dumps({"population": len(pop), "A": len(smp["A"]), "B": len(smp["B"]),
                      "rows_A": len(frames["A"][0]), "rows_B": len(frames["B"][0])}))
    return rep


if __name__ == "__main__":
    main()
