#!/usr/bin/env bash
# Extracts the current public *.trycloudflare.com URL out of cloudflare.log
# and upserts it into .env as PUBLIC_DOMAIN -- see webapp/config.py's
# get_public_domain() for how the webapp consumes it (the song-page link in
# download captions, see webapp/routers/tracks.py's build_share_caption()).
#
# Why this exists: we're on a `cloudflared tunnel --url ...` *quick* tunnel
# for now, not a named/static one, so the public domain changes on every
# restart (start.sh already tails cloudflare.log for this same reason to
# write app/url.txt -- see start.sh). Re-run this any time after a fresh
# tunnel comes up; it's idempotent and safe to call repeatedly.
#
# Usage: deploy/update_domain.sh
# (called automatically from start.sh right after cloudflared's URL shows
# up in cloudflare.log; can also be run by hand for a one-off refresh.)

set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUDFLARE_LOG="$APP_DIR/cloudflare.log"
ENV_FILE="$APP_DIR/.env"

if [ ! -f "$CLOUDFLARE_LOG" ]; then
    echo "$(date -Is) update_domain.sh: $CLOUDFLARE_LOG not found yet" >&2
    exit 1
fi

url=""
for _ in $(seq 1 60); do
    url=$(grep -Eo 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$CLOUDFLARE_LOG" | head -n1 || true)
    [ -n "$url" ] && break
    sleep 2
done

if [ -z "$url" ]; then
    echo "$(date -Is) update_domain.sh: no trycloudflare URL found in $CLOUDFLARE_LOG after waiting" >&2
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "$(date -Is) update_domain.sh: $ENV_FILE not found" >&2
    exit 1
fi

if grep -q '^PUBLIC_DOMAIN=' "$ENV_FILE"; then
    sed -i "s#^PUBLIC_DOMAIN=.*#PUBLIC_DOMAIN=$url#" "$ENV_FILE"
else
    printf '\nPUBLIC_DOMAIN=%s\n' "$url" >> "$ENV_FILE"
fi

echo "$(date -Is) update_domain.sh: PUBLIC_DOMAIN set to $url"
