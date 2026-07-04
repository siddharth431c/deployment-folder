#!/bin/bash

# Cursor Remote Agent - Quick Start Script
# Usage: ./start.sh [project_path] [password]

PROJECT_PATH="${1:-$HOME}"
PASSWORD="${2:-cursor123}"
PORT="${3:-8765}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
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

echo -e "${GREEN}"
echo "================================================"
echo "  Server starting on port $PORT"
echo "  Project: $PROJECT_PATH"
echo "  Password: $PASSWORD"
echo ""
echo "  Connect from your iPhone:"
echo "  http://$LOCAL_IP:$PORT"
echo "================================================"
echo -e "${NC}"

# Start the server
python3 server.py --project "$PROJECT_PATH" --password "$PASSWORD" --port "$PORT"
