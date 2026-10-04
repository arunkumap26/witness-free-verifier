import json, urllib.request, urllib.parse, time
queries = ["agent trajectories","agent trajectory","trajectories","tool calls","tool call","tool-use","tool use logs","claude code","codex","opencode","trajectory","function calling logs","function calling","swe-agent","openhands","agent traces","agent logs","coding agent","terminal-bench","swe-bench trajectories","agentic traces","agent sessions","cline","aider","nemotron agentic","mcp traces","agent-trace","coding sessions","claude-code","gemini-cli","cursor","otel","telemetry agent","agent rollouts","swe-gym","swe-smith","sweb trajectories","tau-bench","toolbench","bfcl"]
out = {}
for q in queries:
    url = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode({"search": q, "limit": 200, "full": "true"})
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = json.load(r)
    except Exception as e:
        data = {"error": str(e)}
    out[q] = data
    print(q, len(data) if isinstance(data, list) else data)
    time.sleep(0.5)
json.dump(out, open("search_raw.json","w"))
