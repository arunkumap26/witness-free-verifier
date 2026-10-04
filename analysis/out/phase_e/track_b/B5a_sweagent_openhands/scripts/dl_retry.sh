#!/usr/bin/env bash
# Retry pinned HF dataset downloads through HF rate limits. Each job: repo rev localdir [include patterns...]
# Checks the 25 GB shared cap before each attempt. Logs to dl_retry.log next to this script.
LOG="$(dirname "$0")/dl_retry.log"
ACQ=/c/Swarms/data/acquired
cap_ok() {
  local used_kb; used_kb=$(du -sk "$ACQ" | cut -f1)
  local need_kb=$1
  if [ $((used_kb + need_kb)) -gt $((25 * 1000 * 1000)) ]; then
    echo "$(date -Is) CAP: used ${used_kb}KB + need ${need_kb}KB > 25GB, skipping" >> "$LOG"; return 1; fi
  return 0
}
run_job() {
  local repo=$1 rev=$2 dir=$3 need_kb=$4; shift 4
  local inc=()
  for p in "$@"; do inc+=(--include "$p"); done
  for attempt in $(seq 1 30); do
    cap_ok "$need_kb" || return 1
    echo "$(date -Is) attempt $attempt $repo@$rev -> $dir ${inc[*]}" >> "$LOG"
    if hf download "$repo" --repo-type dataset --revision "$rev" --local-dir "$dir" "${inc[@]}" >> "$LOG" 2>&1; then
      echo "$(date -Is) DONE $repo" >> "$LOG"; return 0
    fi
    echo "$(date -Is) failed attempt $attempt; sleeping 75s" >> "$LOG"
    sleep 75
  done
  echo "$(date -Is) GAVE UP $repo" >> "$LOG"; return 1
}
run_job tarsur385/qwen3-30b-a3b-instruct-2507-swebench-verified-mini-swe-agent 58389eb5426db5a3ae6159faa37498072b4735ff \
  "$ACQ/miniswe-v2-qwen3-30b-swebv-tarsur385" 30000
run_job sweagent/combo2-rl-rollouts eaff5487b8983db9aaed9e93c16e670695389827 \
  "$ACQ/sweagent-combo2-rl-rollouts" 460000 "README.md" ".gitattributes" "group_info.tar.gz" "trajectories_00.tar.gz"
run_job OpenHands/openhands-evaluation-outputs aa8977805b4cefd317001d80ddf1ad52790e9d23 \
  "$ACQ/openhands-evaluation-outputs" 4700000
echo "$(date -Is) ALL JOBS FINISHED" >> "$LOG"
