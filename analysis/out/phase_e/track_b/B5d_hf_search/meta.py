import json, time, sys
from concurrent.futures import ThreadPoolExecutor
from huggingface_hub import HfApi
api = HfApi()
tagged = json.load(open("agent_traces_tag.json"))
ids = [d["id"] for d in tagged]
extra = """ibm-research/codex_swebenchpro_traces_Otel
Inferact/codex_swebenchpro_traces
ibm-research/lmcache-agentic-traces_Otel
sammshen/lmcache-agentic-traces
agent-evals/hal_traces
Exgentic/agent-llm-traces-v2
Exgentic/agent-llm-traces
trace-commons/agent-traces
open-agent-leaderboard/traces
Jakumetsu/mcpmark-trajectory-log
risenlab/agentlogs
Lightcap/agent-runtime-telemetry-small
cline/incident-traces
thoughtworks/agentic-coding-trajectories
MaxDevv/real-pi-coding-agent-traces-sessions
nlile/misc-merged-claude-code-traces-v1
ratanon/claude-code
choucsan/mimo-claude-code-traces-1k
crispwisp/wisp-claude-code-sessions
netpreme/coding_agent_traces
AlinCiocan/fable-5-claude-code-traces
championswimmer/pi-coding-sessions
Mike0021/codex-sessions
cfahlgren1/codex-sessions
cfahlgren1/agent-sessions-list
mlfoundations-dev/terminal-bench-traces-local
melissapan/swe-bench-lite-agent-traces-v14
GXCafe/ai-agent-failure-logs
WhitzardAgent/ClaudeCode-Anthropic
RangaPrasath/coding-sessions
intelchen/claudecode-trace
rs545837/entity-native-agent-sessions
arsentev-ai/context-economy-agent-sessions
PotatoHD/agent-coding-traces-public
PotatoHD/github-pr-agent-trajectories
VonEquinox/efficient-agent-experiment-logs
DCI-Agent/eval-logs
harry1332/hpca2027-agentic-validated-traces-20260711
stindardlogic/mcp-tool-traces-v2
typesafe/evalsafe-agent-trace-observability
aisa-group/instrumental-choices-agent-traces
Wejh/ninja-agent-traces
kelikelibababian/mimir-agent-traces
beomi/agent-traces
juliensimon/open-agent-traces
xhochy/conda-forge-agent-traces
dacorvo/transformers-coding-session-opencode-traces
dacorvo/hf-hub-session-opencode-traces
lihaonan0716/mcphunt-agent-traces
pagarsky/agent-trace
basedlsg/codex-assistant-rollouts
sehyunlee217/Codex-Agent-Trace
build-small-hackathon/agent-trace-privacy-scrubber-codex-traces
cfahlgren1/verizon-codex-trace
TeichAI/Fable-5-Cursor-Traces
armand0e/cursor-traces-example
whitecircle/swe-rebench-v2-glm-5.1-pi-agent-successful-traces
open-athena/nemotron-gym-agent-calendar-qwen3.5-122b-131k-opencode-traces
zwright/hermes-flight-recorder-self-improving-agent-trajectories
lhoestq/agent-traces-example
merve/agent_traces
davanstrien/agent-race-traces
narcolepticchicken/agent-cost-traces
semioz/prime-agent-traces
Datoric/computer-use-agent-traces-250k
simonycl/trsi-calib-a-claudecode-opus-20260623-001050
misterkerns/my-personal-claude-code-data
thomwolf/am-session-claude-code-1-a66490
OnepointfiveHz/opus-4_8-claude_code-rollout-xhg_0805
sunnydubey1111/agent-trajectory-sentinel
TeichAI/DeepSeek-v4-Pro-Agent""".split()
for e in extra:
    if e not in ids: ids.append(e)
print(len(ids), file=sys.stderr)
def get(i):
    for attempt in range(3):
        try:
            info = api.dataset_info(i, files_metadata=True)
            sib = [{"path": s.rfilename, "size": s.size} for s in (info.siblings or [])]
            cd = info.card_data.to_dict() if info.card_data else {}
            return {"id": i, "sha": info.sha, "gated": info.gated, "private": info.private, "disabled": info.disabled,
                    "lastModified": str(info.last_modified), "createdAt": str(info.created_at), "downloads": info.downloads,
                    "license": cd.get("license"), "license_name": cd.get("license_name"), "license_link": cd.get("license_link"),
                    "tags": info.tags, "n_files": len(sib), "total_bytes": sum((s["size"] or 0) for s in sib), "siblings": sib,
                    "pretty_name": cd.get("pretty_name")}
        except Exception as ex:
            err = repr(ex)[:300]
            time.sleep(3)
    return {"id": i, "error": err}
with ThreadPoolExecutor(6) as ex:
    out = list(ex.map(get, ids))
json.dump(out, open("meta.json","w"))
print(sum(1 for o in out if "error" in o), "errors", file=sys.stderr)
