#!/usr/bin/env bash
# Launch Microsoft Edge with the Chrome DevTools Protocol debug port enabled,
# using a dedicated profile dir so the scraper can reuse your Yahoo session.
#
# Usage:
#   ./run-edge.sh              # launch + wait until the debugger is up
#
# Then: log into Yahoo Fantasy in the Edge window that opens, KEEP IT OPEN,
# and tell the assistant "ready" so it can run the scraper against port 9222.
#
# To stop: just quit Edge (Cmd+Q). The profile persists in ~/.phf-edge, so
# next time your Yahoo login is usually still there.
set -euo pipefail

EDGE="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
PORT=9222
PROFILE="$HOME/.phf-edge"

if [ ! -x "$EDGE" ]; then
  echo "ERROR: Microsoft Edge not found at $EDGE" >&2
  echo "Install it with: brew install --cask microsoft-edge" >&2
  exit 1
fi

# Don't launch a second instance if one is already debugging on this port.
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/json/version"; then
  echo "Edge is already debugging on port $PORT — use the running instance."
  echo "Open: https://football.fantasysports.yahoo.com/f1/447010"
  exit 0
fi

echo ">> Launching Edge (debug port $PORT, profile $PROFILE) ..."
# Launch in background; the window stays open for you to log in.
# --remote-allow-origins=* lets the CDP WebSocket from localhost connect
# (modern Edge/Chrome reject cross-origin WS without this flag).
"$EDGE" --remote-debugging-port=$PORT --user-data-dir="$PROFILE" --remote-allow-origins=* --no-first-run >/tmp/edge-debug.log 2>&1 &
EDGE_PID=$!
echo "   Edge pid: $EDGE_PID"

# Wait until the debugger answers (poll, don't assume).
for i in $(seq 1 30); do
  if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/json/version"; then
    echo ">> Debugger is up at http://127.0.0.1:$PORT"
    echo ">> NOW: log into Yahoo Fantasy in the Edge window, then keep it open."
    echo "   Standings: https://football.fantasysports.yahoo.com/f1/447010"
    exit 0
  fi
  sleep 1
done

echo "ERROR: Edge debugger did not come up within 30s. Check /tmp/edge-debug.log" >&2
exit 1
