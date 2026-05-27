#!/usr/bin/env bash
# PreToolUse hook — refuse `git commit` / `git push` while HEAD is on main.
#
# Reads the hook JSON payload from stdin:
#   { "tool_name": "Bash", "tool_input": { "command": "..." }, "cwd": "..." }
#
# Exit 0 → allow; exit 1 → block with message on stderr.

set -u

payload=$(cat)
tool=$(printf '%s' "$payload" | /usr/bin/jq -r '.tool_name // empty')
cmd=$(printf '%s' "$payload"  | /usr/bin/jq -r '.tool_input.command // empty')

# We only police shell commands.
[[ "$tool" != "Bash" ]] && exit 0
[[ -z "$cmd" ]] && exit 0

repo="${CLAUDE_PROJECT_DIR:-$(pwd)}"
branch=$(git -C "$repo" branch --show-current 2>/dev/null || true)
[[ "$branch" != "main" ]] && exit 0

# Tokenise the command so we don't match arguments like commit messages
# (e.g. `git commit -m "fix checkout flow"` previously slipped through).
# Look for the *first* git subcommand on each line / chained statement.
#
# Splits on shell statement separators (; && || | newline) and inspects
# each fragment independently.
blocked=0
while IFS= read -r frag; do
    # Strip leading whitespace.
    frag="${frag#"${frag%%[![:space:]]*}"}"
    [[ -z "$frag" ]] && continue
    # Match `git <subcommand>` where subcommand ∈ {commit, push}.
    if [[ "$frag" =~ ^(sudo[[:space:]]+)?git[[:space:]]+(commit|push)([[:space:]]|$) ]]; then
        blocked=1
        break
    fi
done < <(printf '%s\n' "$cmd" | tr ';|&\n' '\n')

if (( blocked )); then
    cat >&2 <<EOF
⛔ BLOCKED: ви на гілці 'main'.
Створіть feature-гілку перед комітом/пушем:

    git checkout -b feature/<назва>

Або викликайте skill: /dims-new-feature <назва>
EOF
    exit 1
fi
exit 0
