#!/bin/bash

# Cursor Remote Agent - Quick Start Script
# Usage: ./start.sh [project_path] [password] [port]
#
# Environment variables:
#   CURSOR_API_KEY - Cursor API key for CLI authentication (required for Cursor agent commands)
#   PROJECT_PATH   - Default project path (overridden by first argument)
#   AGENT_PASSWORD - Server password (overridden by second argument)
#   AGENT_PORT     - Server port (overridden by third argument)

PROJECT_PATH="${1:-${PROJECT_PATH:-$HOME}}"
PASSWORD="${2:-${AGENT_PASSWORD:-cursor123}}"
PORT="${3:-${AGENT_PORT:-8765}}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════════╗"
echo "║           Cursor Remote Agent - Starting...                        ║"
echo "╚═══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if Flask is installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
fi

# Get local IP
LOCAL_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | head -1 | awk '{print $2}')

# Check Cursor API key
if [ -z "$CURSOR_API_KEY" ]; then
    echo -e "${YELLOW}"
    echo "Warning: CURSOR_API_KEY is not set."
    echo "Cursor agent commands will fail with authentication errors."
    echo ""
    echo "To fix this, either:"
    echo "  1. Run 'agent login' on your Mac first, OR"
    echo "  2. Set CURSOR_API_KEY environment variable:"
    echo "     export CURSOR_API_KEY=your_api_key_here"
    echo "     ./start.sh"
    echo -e "${NC}"
fi

echo -e "${GREEN}"
echo "================================================"
echo "  Server starting on port $PORT"
echo "  Project: $PROJECT_PATH"
echo "  Password: $PASSWORD"
if [ -n "$CURSOR_API_KEY" ]; then
    echo "  Cursor API Key: Configured"
else
    echo "  Cursor API Key: Not set"
fi
echo ""
echo "  Connect from your iPhone:"
echo "  http://$LOCAL_IP:$PORT"
echo "================================================"
echo -e "${NC}"

# Start the server
python3 server.py --project "$PROJECT_PATH" --password "$PASSWORD" --port "$PORT"
