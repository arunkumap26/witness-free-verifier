"""B5e: scan downloaded native sessions for error / exit-code / harness-duration / truncation markers inside tool results.
Read-only over C:/Swarms/data/acquired (from the download manifest). Writes census/marker_scan.json.

claude_code : toolUseResult key histogram (structured copy), is_error, content text markers.
codex       : function_call_output text wrapper fields ('Wall time: X seconds', 'Process exited with code N',
              'Original token count', 'Total output lines', 'Chunk ID') and JSON-wrapper metadata.exit_code/duration_seconds.
pi          : toolResult isError, details key histogram (e.g. truncation), text markers.
opencode    : tool state.metadata key histogram, status=error, output truncation text.
"""
import json, os, re, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from sample_audit import sniff  # noqa: E402

TXT = {
    "wall_time": re.compile(r"Wall time: [0-9.]+ seconds"),
    "process_exited": re.compile(r"Process exited with code -?\d+"),
    "original_token_count": re.compile(r"Original token count: \d+"),
    "total_output_lines": re.compile(r"Total output lines: \d+"),
    "chunk_id": re.compile(r"Chunk ID: [0-9a-f]+"),
    "truncated_word": re.compile(r"(?i)\btruncated\b"),
    "omitted_lines": re.compile(r"(?i)\[\.\.\. ?omitted|lines? omitted|\.\.\.\s*\(\d+ (more )?lines"),
    "exit_code_word": re.compile(r"(?i)exit code[: ]+-?\d+"),
}


def textof(x):
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "\n".join(textof(i) for i in x)
    if isinstance(x, dict):
        return textof(x.get("text") or x.get("content") or x.get("output") or "")
    return ""


def scan_text(t, ctr, prefix):
    for k, rx in TXT.items():
        if rx.search(t):
            ctr[f"{prefix}:{k}"] += 1


def main():
    G = json.load(open(sys.argv[1], encoding="utf-8"))
    out = {}
    for rec in G["repos"]:
        if rec.get("status") != "DOWNLOADED" or "captures" in rec["repo"]:
            continue
        ctr = Counter(); keys = defaultdict(Counter)
        for dp, dn, fn in os.walk(rec["dest"]):
            for f in fn:
                p = os.path.join(dp, f)
                try:
                    if f.endswith(".jsonl"):
                        rows = []
                        for ln in open(p, encoding="utf-8", errors="replace"):
                            try:
                                rows.append(json.loads(ln))
                            except Exception:
                                pass
                        k = sniff(rows)
                        for r in rows:
                            if not isinstance(r, dict):
                                continue
                            if k == "claude_code" and r.get("type") == "user":
                                tur = r.get("toolUseResult")
                                if isinstance(tur, dict):
                                    for kk in tur:
                                        keys["cc_toolUseResult_keys"][kk] += 1
                                msg = r.get("message") if isinstance(r.get("message"), dict) else {}
                                for c in msg.get("content") if isinstance(msg.get("content"), list) else []:
                                    if isinstance(c, dict) and c.get("type") == "tool_result":
                                        ctr["cc:tool_results"] += 1
                                        ctr["cc:is_error_true"] += int(bool(c.get("is_error")))
                                        scan_text(textof(c.get("content")), ctr, "cc")
                            elif k == "codex":
                                pl = r.get("payload") if isinstance(r.get("payload"), dict) else {}
                                if pl.get("type") in ("function_call_output", "custom_tool_call_output"):
                                    ctr["codex:outputs"] += 1
                                    o = pl.get("output")
                                    t = textof(o)
                                    try:
                                        j = json.loads(t) if isinstance(t, str) and t.startswith("{") else None
                                    except Exception:
                                        j = None
                                    if isinstance(j, dict):
                                        md = j.get("metadata") or {}
                                        for kk in md:
                                            keys["codex_output_json_metadata_keys"][kk] += 1
                                        t = textof(j.get("output", ""))
                                    scan_text(t, ctr, "codex")
                            elif k == "pi" and r.get("type") == "message":
                                m = r.get("message") or {}
                                if m.get("role") == "toolResult":
                                    ctr["pi:tool_results"] += 1
                                    ctr["pi:isError_true"] += int(bool(m.get("isError")))
                                    d = m.get("details")
                                    if isinstance(d, dict):
                                        for kk in d:
                                            keys["pi_details_keys"][kk] += 1
                                    scan_text(textof(m.get("content")), ctr, "pi")
                    elif f.endswith(".json") and not f.startswith("_b5e"):
                        obj = json.load(open(p, encoding="utf-8", errors="replace"))
                        if isinstance(obj, dict) and "messages" in obj and "info" in obj:
                            for mm in obj["messages"]:
                                for part in mm.get("parts") or []:
                                    if part.get("type") != "tool":
                                        continue
                                    st = part.get("state") or {}
                                    ctr["oc:tool_parts"] += 1
                                    ctr["oc:status_error"] += int(st.get("status") == "error")
                                    for kk in (st.get("metadata") or {}):
                                        keys["oc_state_metadata_keys"][kk] += 1
                                    scan_text(textof(st.get("output") or st.get("error") or ""), ctr, "oc")
                except Exception as ex:
                    ctr["error:" + type(ex).__name__] += 1
        out[f"{rec['corpus']}::{rec['repo']}"] = {"counts": dict(ctr), **{k: dict(v.most_common(30)) for k, v in keys.items()}}
        print(rec["repo"], dict(ctr))
    json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
