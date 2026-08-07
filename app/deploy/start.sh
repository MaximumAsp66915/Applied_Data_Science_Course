#!/usr/bin/env bash
# SUTMusic app stack launcher.
#
# Runs as the ExecStart of the sutmusic.service systemd *user* unit (see
# sutmusic.service in this same folder) -- deliberately a single foreground
# script rather than four separate services, because the product ask was
# "one systemctl file" the GitHub Action can restart in one shot after a
# deploy.
#
# Starts, in $APP_DIR:
#   1. the Telegram bot        -> app.log
#   2. the FastAPI webapp      -> webapp.log
#   3. the frontend build+preview -> frontend.log
#   4. the cloudflared tunnel  -> cloudflare.log
# then tails cloudflare.log for the public *.trycloudflare.com URL and
# writes it to url.txt. All five files live directly under $APP_DIR, as
# requested.
#
# NOTE: the recommendation engine (../engine) is deliberately NOT part of
# this stack/unit -- it has its own systemd unit (engine/deploy/
# sutengine.service) and its own GitHub Action (.github/workflows/
# deploy-engine.yml, triggered only by changes under engine/), so a
# model/engine-only deploy never restarts the bot/webapp/frontend here, and
# vice versa. See engine/README.md.
#
# The script itself stays in the foreground and waits on all four child
# processes: if any one of them dies, it tears the rest down and exits
# non-zero so systemd's Restart=always brings the whole stack back up
# together, instead of leaving the others running against a dead sibling.

set -uo pipefail

APP_DIR="/srv/bots/telegram/SUTMusic_app/app"
cd "$APP_DIR"

APP_LOG="$APP_DIR/app.log"
WEBAPP_LOG="$APP_DIR/webapp.log"
FRONTEND_LOG="$APP_DIR/frontend.log"
CLOUDFLARE_LOG="$APP_DIR/cloudflare.log"
URL_FILE="$APP_DIR/url.txt"

: > "$APP_LOG"
: > "$WEBAPP_LOG"
: > "$FRONTEND_LOG"
: > "$CLOUDFLARE_LOG"
: > "$URL_FILE"

# --- venv: already provisioned on the server, just activate + sync deps ---
source "$APP_DIR/.venv/bin/activate"
pip install -r "$APP_DIR/requirements.txt" --upgrade-strategy only-if-needed --upgrade >> "$APP_LOG" 2>&1

# Pull API_ID/API_HASH out of .env for the local Bot API server step below
# (bash never sources .env for its own use elsewhere -- config/ reads it in
# Python only -- so extract just these two values, tolerating either being
# absent/blank without failing the whole script under `set -u`).
API_ID=$(grep -E '^API_ID=' "$APP_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)
API_HASH=$(grep -E '^API_HASH=' "$APP_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)


PIDS=()

cleanup() {
    trap - TERM INT
    for pid in "${PIDS[@]:-}"; do
        kill "$pid" >/dev/null 2>&1 || true
    done
    wait >/dev/null 2>&1 || true
}
trap cleanup TERM INT

# 1) Telegram bot
nohup python main.py >> "$APP_LOG" 2>&1 &
PIDS+=("$!")

# 1b) Local Bot API Server (optional) -- fallback for tracks >20MB, see
# webapp/media.py's TelegramFileTooBigError / TELEGRAM_LOCAL_API_BASE.
# Only started if the `telegram-bot-api` binary is on PATH and API_ID/
# API_HASH are set (same app credentials the Telethon userbot already
# uses, from my.telegram.org) -- otherwise skipped entirely so a server
# that never opted into this doesn't fail to start. Deliberately NOT added
# to PIDS/supervision: it's a fallback path, not a core process, so if it
# dies or was never running, oversized tracks just go back to failing
# clean (413) instead of taking the whole stack down. Must happen BEFORE
# step 2's uvicorn launch: webapp/config.py's Settings reads .env once at
# process import time, so TELEGRAM_LOCAL_API_BASE has to already be in
# .env by then, not patched in afterward.
LOCAL_BOT_API_LOG="$APP_DIR/local_bot_api.log"
: > "$LOCAL_BOT_API_LOG"
if command -v telegram-bot-api >/dev/null 2>&1 && [ -n "${API_ID:-}" ] && [ -n "${API_HASH:-}" ]; then
    mkdir -p "$APP_DIR/.local_bot_api_data"
    nohup telegram-bot-api \
        --api-id="$API_ID" \
        --api-hash="$API_HASH" \
        --local \
        --http-port=8081 \
        --dir="$APP_DIR/.local_bot_api_data" \
        >> "$LOCAL_BOT_API_LOG" 2>&1 &
    echo "$(date -Is) started local Bot API server on :8081 (pid $!)" >> "$LOCAL_BOT_API_LOG"
    if grep -q '^TELEGRAM_LOCAL_API_BASE=' "$APP_DIR/.env" 2>/dev/null; then
        sed -i 's|^TELEGRAM_LOCAL_API_BASE=.*|TELEGRAM_LOCAL_API_BASE=http://127.0.0.1:8081|' "$APP_DIR/.env"
    else
        echo "TELEGRAM_LOCAL_API_BASE=http://127.0.0.1:8081" >> "$APP_DIR/.env"
    fi
    # Give it a moment to finish binding its HTTP port before uvicorn (and
    # therefore the webapp's first getFile calls) comes up.
    sleep 2
else
    echo "$(date -Is) telegram-bot-api not found or API_ID/API_HASH unset -- skipping local Bot API server, large tracks (>20MB) will fail to stream" >> "$LOCAL_BOT_API_LOG"
fi

# 2) FastAPI webapp
nohup uvicorn webapp.main:app --host 0.0.0.0 --port 8000 --reload >> "$WEBAPP_LOG" 2>&1 &
PIDS+=("$!")


# 3) Frontend: install + build run synchronously (their output still goes to
#    frontend.log) since `preview` is the long-lived process; only preview
#    itself is what actually needs to be backgrounded/supervised.
(
    cd "$APP_DIR/frontend"
    export NODE_OPTIONS="--dns-result-order=ipv4first"
    npm install >> "$FRONTEND_LOG" 2>&1 && \
    npm run build >> "$FRONTEND_LOG" 2>&1 && \
    exec npm run preview >> "$FRONTEND_LOG" 2>&1
) &
PIDS+=("$!")

# 4) Cloudflare quick tunnel, pointed at the frontend preview server
nohup cloudflared tunnel --protocol quic --url http://localhost:4173 >> "$CLOUDFLARE_LOG" 2>&1 &
PIDS+=("$!")

# --- Wait for cloudflared to print the public URL, then record it (both
#     url.txt, for humans/CI, and .env's PUBLIC_DOMAIN, for the webapp --
#     see deploy/update_domain.sh; webapp/config.py's get_public_domain()
#     re-reads .env on every call so this lands without a webapp restart) ---
(
    for _ in $(seq 1 60); do
        url=$(grep -Eo 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$CLOUDFLARE_LOG" | head -n1 || true)
        if [ -n "$url" ]; then
            echo "$url" > "$URL_FILE"
            "$APP_DIR/deploy/update_domain.sh" >> "$APP_LOG" 2>&1
            break
        fi
        sleep 2
    done
) &
# PIDS+=("$!") ## Better to comment it due to rate limit and else 

# --- Supervise: if any of the four main processes dies, tear everything
#     down and exit non-zero so systemd restarts the whole stack together ---
while true; do
    for pid in "${PIDS[@]}"; do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
            echo "$(date -Is) child pid $pid exited, restarting the stack" >> "$APP_LOG"
            cleanup
            exit 1
        fi
    done
    sleep 5
done
