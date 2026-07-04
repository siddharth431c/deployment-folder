#!/bin/bash
# Update dependencies and (re)start Cursor Remote Agent.
# Usage:
#   ./update_and_start.sh [project_path] [password] [port] [app_url]
#   ./update_and_start.sh          # uses last-run settings from .run.conf
#
# Safe to run from Terminal or from the mobile "Update & Restart" button.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Load last-run settings if present
if [ -f "$DIR/.run.conf" ]; then
  # shellcheck disable=SC1091
  source "$DIR/.run.conf"
fi

PROJECT_PATH="${1:-${PROJECT_PATH:-$HOME}}"
PASSWORD="${2:-${PASSWORD:-cursor123}}"
PORT="${3:-${PORT:-8765}}"
APP_URL="${4:-${APP_URL:-}}"
HOST="${HOST:-0.0.0.0}"
CURSOR_API_KEY="${CURSOR_API_KEY:-}"

# Give the HTTP response a moment to finish when triggered from the app
if [ "${DELAY_RESTART:-0}" = "1" ]; then
  sleep 1
fi

echo "================================================"
echo "  Updating Cursor Remote Agent"
echo "================================================"
echo "  Project : $PROJECT_PATH"
echo "  Port    : $PORT"
echo "  Host    : $HOST"
echo ""

echo "→ Installing / updating dependencies..."
python3 -m pip install -r requirements.txt

echo "→ Stopping any server already on port $PORT..."
PIDS="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  sleep 1
  STILL="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
  if [ -n "$STILL" ]; then
    # shellcheck disable=SC2086
    kill -9 $STILL 2>/dev/null || true
  fi
fi

# Persist settings for the next update/restart
cat > "$DIR/.run.conf" <<EOF
PROJECT_PATH=$(printf '%q' "$PROJECT_PATH")
PASSWORD=$(printf '%q' "$PASSWORD")
PORT=$(printf '%q' "$PORT")
APP_URL=$(printf '%q' "$APP_URL")
HOST=$(printf '%q' "$HOST")
CURSOR_API_KEY=$(printf '%q' "$CURSOR_API_KEY")
EOF

ARGS=(python3 server.py --project "$PROJECT_PATH" --password "$PASSWORD" --port "$PORT" --host "$HOST")
if [ -n "$APP_URL" ]; then
  ARGS+=(--app-url "$APP_URL")
fi
if [ -n "$CURSOR_API_KEY" ]; then
  ARGS+=(--cursor-api-key "$CURSOR_API_KEY")
  export CURSOR_API_KEY
fi

echo "→ Starting server..."
nohup "${ARGS[@]}" > "$DIR/agent.log" 2>&1 &
NEW_PID=$!

# Brief wait so we can report whether it stayed up
sleep 1
if kill -0 "$NEW_PID" 2>/dev/null; then
  LOCAL_IP="$(ifconfig | grep "inet " | grep -v 127.0.0.1 | head -1 | awk '{print $2}')"
  echo ""
  echo "================================================"
  echo "  Server restarted (PID $NEW_PID)"
  echo "  Log: $DIR/agent.log"
  echo "  Open: http://${LOCAL_IP:-YOUR_MAC_IP}:$PORT"
  echo "================================================"
else
  echo "Server failed to start. Check $DIR/agent.log" >&2
  exit 1
fi
