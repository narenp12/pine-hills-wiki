#!/usr/bin/env bash
# One-shot: extract from Yahoo -> raw/, then generate Markdown -> content/.
set -euo pipefail
cd "$(dirname "$0")/.."
echo ">> extracting from Yahoo..."
python scripts/extract.py
echo ">> generating markdown..."
python scripts/generate.py
echo ">> done. Preview with: npx quartz build --serve"
