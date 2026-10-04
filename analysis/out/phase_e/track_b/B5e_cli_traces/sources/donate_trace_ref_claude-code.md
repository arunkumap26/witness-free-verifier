# Claude Code sessions

## Location
`~/.claude/projects/<project-slug>/<session-uuid>.jsonl`

One JSONL file per session. The `<project-slug>` is derived from the working directory. Pick the most recently modified file unless the user names one.

## Format
One JSON object per line. Top-level `type` is one of: `user`, `assistant`, `queue-operation`, `last-prompt`.

Identity / sensitive fields:
- top-level `cwd` — absolute working directory (contains the username)
- top-level `gitBranch` — branch name (may encode a feature/client name)
- top-level `sessionId`, and `message.id`, `message.content[].id` (`msg_*`, `toolu_*`)

Free-text carriers (where prompts, commands, and outputs live):
- `message.content[].text` — assistant/user prose
- `message.content[].input` — tool inputs; for the Bash tool this is `.input.command`, the single richest source of leaked secrets
- tool_result content blocks — command output, which can contain anything

## Donating
The native file is already in the right shape. After scrubbing, place the cleaned file at `sessions/claude_code/<filename>` in the dataset. The `traces` rows are just the parsed lines.
