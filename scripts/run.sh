#!/usr/bin/env bash
# Pipeline: Fantasy Helper export -> canonical raw JSON -> Quartz Markdown.
#
# 1. Go to https://fantasyhelper.net/ , log in with Yahoo (read-only, no key).
# 2. Open your league, download Teams / Matchups / Transactions / Rosters as
#    CSV (or JSON). Put them all in one folder, e.g. exports/.
# 3. Run this script.
set -euo pipefail
cd "$(dirname "$0")/.."

EXPORTS="${1:-exports}"
echo ">> adapting Fantasy Helper exports from $EXPORTS ..."
python scripts/import_export.py "$EXPORTS"

echo ">> generating markdown..."
python scripts/generate.py

echo ">> done. Preview with: npx quartz build --serve"
