#!/usr/bin/env bash
cd "$(dirname "$0")"
CAP=25000000000
A=C:/Swarms/data/acquired
python pinned_dl.py OpenHands/openhands-feedback $A/openhands-feedback $CAP
python pinned_dl.py tarsur385/qwen3-30b-a3b-instruct-2507-swebench-verified-mini-swe-agent $A/miniswe-v2-qwen3-30b-swebv-tarsur385 $CAP
python pinned_dl.py sweagent/combo2-rl-rollouts $A/sweagent-combo2-rl-rollouts $CAP README.md .gitattributes group_info.tar.gz trajectories_00.tar.gz
python pinned_dl.py OpenHands/openhands-evaluation-outputs $A/openhands-evaluation-outputs $CAP
echo ALL_DONE
