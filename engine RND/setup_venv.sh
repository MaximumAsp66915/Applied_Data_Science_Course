#!/usr/bin/env bash
# One-time setup: creates .venv next to this script and installs
# requirements.txt into it. Run once, from anywhere:
#
#   bash "engine RND/setup_venv.sh"
#
# After this, deploy/start.sh activates and reuses the same venv on every
# restart -- it never recreates it. Same contract as engine_v1/engine_v2.
#
# Note the quoting: this folder's name contains a space, so every path that
# touches it needs quotes. That is deliberate for an R&D folder -- it keeps
# .github/workflows/deploy-engine.yml, which globs `engine_v*`, from ever
# selecting it. Promoting this engine means copying it to `engine_v3/`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Build the serving bundle from the engine_v2 exports if one isn't there yet.
# The engine also runs straight off engine_v2/model_params/ without this, but
# then it needs scikit-learn and cannot use the artist bias -- see README.md.
if [ ! -f model_params/bundle.json ]; then
    echo "No model_params/bundle.json found -- building one from ../engine_v2/model_params"
    python tools/build_params.py --source ../engine_v2/model_params --out model_params || {
        echo "Bundle build failed; the engine will fall back to reading engine_v2 artifacts directly." >&2
        pip install "scikit-learn==1.5.2"
    }
fi

echo
echo ".venv ready. Start the service with:"
echo "  source .venv/bin/activate && uvicorn main:app --host 127.0.0.1 --port 8100"
echo "Run the tests with:"
echo "  source .venv/bin/activate && pip install pytest && python -m pytest tests/ -q"
