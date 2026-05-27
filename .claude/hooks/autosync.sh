#!/usr/bin/env bash
# PostToolUse hook — mirror edited project files into /tmp/dims_project so the
# preview server (port 5001) sees changes. Triggered after Edit / Write.
#
# Reads the hook JSON payload from stdin:
#   { "tool_name": "...", "tool_input": { "file_path": "..." }, "cwd": "..." }

set -u

# Always exit 0 — a hook failure must not block Claude's tool call.
trap 'exit 0' ERR

payload=$(cat)
file=$(printf '%s' "$payload" | /usr/bin/jq -r '.tool_input.file_path // empty' 2>/dev/null)

[[ -z "$file" ]] && exit 0
[[ ! -f "$file" ]] && exit 0

SRC="${CLAUDE_PROJECT_DIR:-/Users/odin/Desktop/Стилометрія}"
DST="/tmp/dims_project"

# Only mirror files that live inside the project root.
case "$file" in
  "$SRC"/*) ;;
  *) exit 0 ;;
esac

rel="${file#$SRC/}"

# Only mirror files that the preview server actually consumes.
case "$rel" in
  app.py | templates/*.html | static/* | core/*.py) ;;
  *) exit 0 ;;
esac

mkdir -p "$DST" "$(dirname "$DST/$rel")"
cp "$file" "$DST/$rel" && echo "✓ autosync: $rel → $DST/" >&2
exit 0
