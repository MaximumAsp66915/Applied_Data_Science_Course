#!/usr/bin/env bash
# SUT Music recommendation engine launcher (R&D build).
#
# Same shape as engine_v1/engine_v2's start.sh -- ExecStart of the
# sutengine.service systemd *user* unit, foreground supervisor, exits
# non-zero on child death so Restart=always brings it back -- with three
# deliberate differences, all of them about not depending on the network at
# boot:
#
#   1. No `pip install` on every restart. engine_v2 ran
#      `pip install -r requirements.txt --upgrade` inside its start script, so
#      a PyPI outage, a DNS hiccup or a proxy failure turned a routine restart
#      into an outage -- for pinned dependencies that were already installed.
#      Dependency installation belongs in setup_venv.sh and in the deploy
#      workflow, which run once and can fail loudly.
#   2. A startup health check. The unit is not considered up until /health
#      answers, so a bundle that fails to load surfaces at deploy time rather
#      than on the first user request.
#   3. Log rotation by truncation is gone; the log is appended to and left for
#      logrotate/journald, so a restart no longer destroys the evidence of why
#      the previous process died.
set -uo pipefail

ENGINE_DIR="${ENGINE_DIR:-/srv/bots/telegram/SUTMusic_app/engine}"
cd "$ENGINE_DIR"

ENGINE_LOG="$ENGINE_DIR/engine.log"
touch "$ENGINE_LOG"

# Optional local overrides for ENGINE_HOST / ENGINE_PORT / ENGINE_PARAMS_DIR
# and any ENGINE_<CONFIG_FIELD> serving knob (see config.py). Excluded from
# the deploy rsync so a hand-written one survives deploys.
if [ -f "$ENGINE_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ENGINE_DIR/.env"
    set +a
fi

# shellcheck disable=SC1091
source "$ENGINE_DIR/.venv/bin/activate"

HOST="${ENGINE_HOST:-127.0.0.1}"
PORT="${ENGINE_PORT:-8100}"

nohup uvicorn main:app --host "$HOST" --port "$PORT" >> "$ENGINE_LOG" 2>&1 &
PID=$!

cleanup() {
    trap - TERM INT
    kill "$PID" >/dev/null 2>&1 || true
    wait >/dev/null 2>&1 || true
}
trap cleanup TERM INT

# --- Startup gate: refuse to look healthy if the model never loaded ---
for _ in $(seq 1 30); do
    if ! kill -0 "$PID" >/dev/null 2>&1; then
        echo "$(date -Is) engine died during startup" >> "$ENGINE_LOG"
        exit 1
    fi
    if curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1; then
        echo "$(date -Is) engine healthy on $HOST:$PORT" >> "$ENGINE_LOG"
        break
    fi
    sleep 1
done

# --- Supervise ---
while true; do
    if ! kill -0 "$PID" >/dev/null 2>&1; then
        echo "$(date -Is) engine process exited, restarting" >> "$ENGINE_LOG"
        cleanup
        exit 1
    fi
    sleep 5
done
