#!/bin/bash
# Smoke test for GPT Reasoner MCP server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$SCRIPT_DIR/server.py"

echo "=== GPT Reasoner MCP Smoke Test ==="
echo ""

# Check prerequisites
echo "1. Checking prerequisites..."

if ! command -v codex &> /dev/null; then
    echo "   ERROR: Codex CLI not found. Install with: brew install codex-cli"
    exit 1
fi
echo "   Codex CLI: OK"

if ! command -v python3 &> /dev/null; then
    echo "   ERROR: Python 3 not found"
    exit 1
fi
echo "   Python 3: OK"

if [ ! -f "$SERVER" ]; then
    echo "   ERROR: server.py not found at $SERVER"
    exit 1
fi
echo "   Server script: OK"

echo ""
echo "2. Testing MCP protocol (initialize)..."

INIT_RESPONSE=$(echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | python3 "$SERVER" 2>/dev/null | head -1)

if echo "$INIT_RESPONSE" | grep -q '"protocolVersion"'; then
    echo "   Initialize: OK"
else
    echo "   ERROR: Initialize failed"
    echo "   Response: $INIT_RESPONSE"
    exit 1
fi

echo ""
echo "3. Testing tools/list..."

TOOLS_RESPONSE=$(echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | python3 "$SERVER" 2>/dev/null | head -1)

if echo "$TOOLS_RESPONSE" | grep -q '"second_thought"'; then
    echo "   Tools list: OK (second_thought tool found)"
else
    echo "   ERROR: Tools list failed"
    echo "   Response: $TOOLS_RESPONSE"
    exit 1
fi

echo ""
echo "=== Protocol tests passed ==="
echo ""
echo "To test actual reasoning (takes 30-90 seconds), run:"
echo ""
echo "  echo '{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"second_thought\",\"arguments\":{\"reasoning_input\":\"What is the best approach to learn a new skill?\",\"depth\":\"low\",\"mode\":\"bullets\"}}}' | python3 $SERVER"
echo ""
