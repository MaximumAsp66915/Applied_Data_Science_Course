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
