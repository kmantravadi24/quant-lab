#!/usr/bin/env bash
# Reproduce Quant Lab from nothing: fresh virtual environment, dependencies installed
# strictly from the hash-locked file, then lint, the full test suite and (when the private
# dataset is present) the frozen-study verification.
#
#   tools/verify_clean_env.sh python3.12 [work-dir]
#
# Exit code 0 only if every step passes. Nothing outside work-dir is modified.
set -euo pipefail
PY="${1:-python3}"
cd "$(dirname "$0")/.."
WORK="${2:-$(mktemp -d)}"
echo "== interpreter: $($PY --version) ; work dir: $WORK"
"$PY" -m venv "$WORK/venv"
VPY="$WORK/venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet --require-hashes -r requirements/lock.txt
"$VPY" -m pip install --quiet --no-deps -e .
"$VPY" -m pip check
"$VPY" -m ruff check .
"$VPY" -m pytest -q -p no:cacheprovider
if [ -d experiments/data ]; then
  "$VPY" experiments/trend_vs_buyhold.py --verify
else
  echo "experiments/data not present: frozen-study verification skipped (private dataset)"
fi
echo "== clean environment OK on $($PY --version)"
