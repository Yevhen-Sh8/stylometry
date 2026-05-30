#!/usr/bin/env bash
# PreToolUse hook — warn before editing the Cloudflare wrangler config.
# DIMS cannot run on Cloudflare Workers (heavy Python stack + SQLite on disk +
# Flask/WSGI). The wrangler.jsonc here is a misconfiguration that spams every
# PR with failing Workers builds. This hook reminds us not to develop it.
# Non-blocking: warns on stderr, always exits 0.
#
# Reads the hook JSON payload from stdin.

set -u

payload=$(cat)
file=$(printf '%s' "$payload" | /usr/bin/jq -r '.tool_input.file_path // empty' 2>/dev/null || true)

if [[ -z "$file" ]]; then
    exit 0
fi

case "$file" in
  *wrangler*|*cloudflare*)
    echo "ℹ️  $file — Cloudflare-конфіг. Нагадування: DIMS не працює на Workers" >&2
    echo "   (Flask + numpy/scipy + SQLite на диску). Розвивати це не варто —" >&2
    echo "   деплой іде на Render. Краще видалити wrangler.jsonc і вимкнути" >&2
    echo "   Git-інтеграцію в Cloudflare Dashboard." >&2
    ;;
esac
exit 0
