#!/usr/bin/env bash
# Start the dashboard on a private port on synthetic data (no provider is contacted), run the browser checks, stop it.
#   tests/browser/run.sh [screenshot-folder]
# Needs: the app's Python dependencies, Node, and the `playwright` package with Chromium.
set -euo pipefail
cd "$(dirname "$0")/../.."
PORT="${QL_BROWSER_PORT:-8765}"
WORK="$(mktemp -d)"
QUANTLAB_DEFAULT_SOURCE=synthetic QUANTLAB_FORECAST_DIR="$WORK/forecasts" python -m streamlit run app/main.py \
  --server.port "$PORT" --server.headless true --server.address 127.0.0.1 \
  --browser.gatherUsageStats false >"$WORK/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
  if curl -fs "http://127.0.0.1:$PORT/_stcore/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
node tests/browser/smoke.js "http://127.0.0.1:$PORT" "${1:-}"
