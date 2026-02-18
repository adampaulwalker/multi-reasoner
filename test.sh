#!/bin/bash
# Smoke test for Multi-Reasoner MCP server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$SCRIPT_DIR/server.py"

echo "=== Multi-Reasoner MCP Smoke Test ==="
echo ""

# Check prerequisites
echo "1. Checking prerequisites..."

if ! command -v codex &> /dev/null; then
    echo "   WARNING: Codex CLI not found. chatgpt tool will not work."
    echo "   Install with: brew install codex-cli"
else
    echo "   Codex CLI: OK"
fi

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

# FastMCP uses stdio transport - send initialize and read response
INIT_RESPONSE=$(echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | python3 "$SERVER" 2>/dev/null | head -1)

if echo "$INIT_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'result' in d" 2>/dev/null; then
    echo "   Initialize: OK"
else
    echo "   ERROR: Initialize failed"
    echo "   Response: $INIT_RESPONSE"
    exit 1
fi

echo ""
echo "3. Testing tools/list..."

# Send initialize + initialized notification + tools/list
TOOLS_RESPONSE=$(printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n' | python3 "$SERVER" 2>/dev/null | tail -1)

# Check for expected tools
FOUND_TOOLS=0
for tool in chatgpt gemini consensus codex_review; do
    if echo "$TOOLS_RESPONSE" | grep -q "\"$tool\""; then
        FOUND_TOOLS=$((FOUND_TOOLS + 1))
    else
        echo "   WARNING: Tool '$tool' not found in response"
    fi
done

if [ "$FOUND_TOOLS" -ge 3 ]; then
    echo "   Tools list: OK ($FOUND_TOOLS/4 tools found)"
else
    echo "   ERROR: Only $FOUND_TOOLS/4 tools found"
    echo "   Response: $TOOLS_RESPONSE"
    exit 1
fi

echo ""
echo "=== Protocol tests passed ==="
echo ""
echo "To test actual reasoning (takes 30-90 seconds), run:"
echo ""
echo "  Use chatgpt/gemini/consensus tools via Claude Code"
echo ""
