#!/bin/bash

# Cursor Remote Agent - Multi-Microservice Edition
# Quick Start Script
# Usage: ./start.sh [workspace_path] [password] [port]

WORKSPACE="${1:-$HOME}"
PASSWORD="${2:-cursor123}"
PORT="${3:-8765}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║     Cursor Remote Agent - Multi-Microservice Edition                   ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if Flask is installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip3 install -r requirements.txt
fi

# Get local IP addresses
echo -e "${GREEN}Finding network addresses...${NC}"
LOCAL_IPS=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}')

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "  Server Configuration:"
echo -e "  • Workspace: ${BLUE}$WORKSPACE${NC}"
echo -e "  • Password:  ${BLUE}$PASSWORD${NC}"
echo -e "  • Port:      ${BLUE}$PORT${NC}"
echo ""
echo -e "  ${YELLOW}Connect from your iPhone:${NC}"
echo ""
for ip in $LOCAL_IPS; do
    echo -e "    ${GREEN}http://$ip:$PORT${NC}"
done
echo ""
echo -e "${GREEN}================================================${NC}"
echo ""

# Start the server
python3 server.py --workspace "$WORKSPACE" --password "$PASSWORD" --port "$PORT"
