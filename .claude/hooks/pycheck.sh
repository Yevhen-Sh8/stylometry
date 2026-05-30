#!/usr/bin/env bash
# PostToolUse hook — instant syntax check after editing Python sources.
# Catches syntax errors / leftover conflict markers the moment a file is saved,
# instead of at import time later. Non-blocking: only warns on stderr, always
# exits 0 so it can never abort the tool call.
#
# Reads the hook JSON payload from stdin:
#   { "tool_input": { "file_path": "..." }, ... }

set -u

payload=$(cat)
file=$(printf '%s' "$payload" | /usr/bin/jq -r '.tool_input.file_path // empty' 2>/dev/null || true)

# Guard: only check existing .py files. (Combined into one `if` so a false
# condition can never trip an ERR trap / early-exit.)
if [[ -z "$file" || "$file" != *.py || ! -f "$file" ]]; then
    exit 0
fi

# Leftover git conflict markers are a common, easy-to-miss failure.
# Match real markers precisely (exactly 7 chars) so comment dividers like
# "# =========" or "=================" are NOT flagged as false positives:
#   <<<<<<< <label>  |  ======= (exactly 7, alone)  |  >>>>>>> <label>
if grep -nE '^(<<<<<<<( |$)|=======$|>>>>>>>( |$))' "$file" >/dev/null 2>&1; then
    echo "⚠️  $file: знайдено маркери конфлікту git (<<<<<<< / ======= / >>>>>>>)" >&2
fi

# Syntax check — `if` tests the exit status directly, no ERR trap needed.
if err=$(python3 -m py_compile "$file" 2>&1); then
    echo "✓ py_compile OK: ${file##*/}" >&2
else
    echo "⚠️  SYNTAX ERROR у $file:" >&2
    printf '%s\n' "$err" >&2
fi
exit 0
