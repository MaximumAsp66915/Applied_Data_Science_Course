#!/usr/bin/env bash
# SUT Music recommendation engine launcher.
#
# Runs as the ExecStart of the sutengine.service systemd *user* unit (see
# sutengine.service in this same folder) -- deliberately its OWN unit,
# separate from sutmusic.service (the app stack: bot/webapp/frontend/
# tunnel, see ../../app/deploy/start.sh). That split is what lets
# .github/workflows/deploy-engine.yml restart only this process on an
# engine-only push, without ever touching the running app stack, and vice
# versa for .github/workflows/deploy-app.yml.
#
# The server only ever has one "engine/" folder -- whichever engine_v*
# version was most recently pushed gets rsynced into it by
# deploy-engine.yml, and this script (shipped as part of that same folder)
# is what actually runs it. Same launcher shape regardless of which
# engine_v* is currently deployed: starts the FastAPI engine (main.py) in
# $ENGINE_DIR, bound to 127.0.0.1 only -> engine.log.
#
# Stays in the foreground and supervises that one process: if it dies, this
# script exits non-zero so systemd's Restart=always brings it back.

set -uo pipefail

ENGINE_DIR="/srv/bots/telegram/SUTMusic_app/engine"
cd "$ENGINE_DIR"

ENGINE_LOG="$ENGINE_DIR/engine.log"
: > "$ENGINE_LOG"

# Optional local overrides for ENGINE_HOST/ENGINE_PORT (see .env.example) --
# not required for anything to work, main.py already defaults to
# 127.0.0.1:8100 with no .env present at all. Deliberately excluded from
# deploy-engine.yml's rsync (--exclude ".env") so a manually-created one
# here survives every deploy instead of being wiped by --delete.
if [ -f "$ENGINE_DIR/.env" ]; then
    set -a
    source "$ENGINE_DIR/.env"
    set +a
fi

# --- venv: provisioned once via `bash setup_venv.sh`, just activate + sync deps ---
source "$ENGINE_DIR/.venv/bin/activate"
pip install -r "$ENGINE_DIR/requirements.txt" --upgrade-strategy only-if-needed --upgrade >> "$ENGINE_LOG" 2>&1

nohup uvicorn main:app --host "${ENGINE_HOST:-127.0.0.1}" --port "${ENGINE_PORT:-8100}" >> "$ENGINE_LOG" 2>&1 &
PID=$!

cleanup() {
    trap - TERM INT
    kill "$PID" >/dev/null 2>&1 || true
    wait >/dev/null 2>&1 || true
}
trap cleanup TERM INT

# --- Supervise: if the engine process dies, tear down and exit non-zero so
#     systemd restarts it (Restart=always in sutengine.service) ---
while true; do
    if ! kill -0 "$PID" >/dev/null 2>&1; then
        echo "$(date -Is) engine process exited, restarting" >> "$ENGINE_LOG"
        cleanup
        exit 1
    fi
    sleep 5
done
