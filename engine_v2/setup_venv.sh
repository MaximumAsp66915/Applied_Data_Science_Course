#!/usr/bin/env bash
# One-time setup on the server: creates engine/.venv and installs
# engine/requirements.txt into it. Run once from anywhere:
#   bash engine/setup_venv.sh
# After this, deploy/start.sh activates and reuses this same venv on every
# restart -- it never recreates it, just like engine_v1's did.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "engine/.venv ready. Start the service with:"
echo "  source engine/.venv/bin/activate && uvicorn main:app --host 127.0.0.1 --port 8100"
echo "In production this runs under its own systemd unit -- see deploy/sutengine.service."
