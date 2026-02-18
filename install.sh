#!/bin/bash
# Install Multi-Reasoner MCP for Claude Code

set -e

INSTALL_DIR="$HOME/.claude/mcp/multi-reasoner"

echo "Installing Multi-Reasoner MCP..."

# Create directory
mkdir -p "$INSTALL_DIR"

# Copy files (if running from repo)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/server.py" ]; then
    cp "$SCRIPT_DIR/server.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/README.md" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/test.sh" "$INSTALL_DIR/"
fi

chmod +x "$INSTALL_DIR/server.py"
chmod +x "$INSTALL_DIR/test.sh"

# Register with Claude Code
echo "Registering MCP with Claude Code..."
claude mcp remove multi-reasoner 2>/dev/null || true
claude mcp add multi-reasoner -- python3 "$INSTALL_DIR/server.py"

echo ""
echo "Done! Verify with: claude mcp list"
echo ""
echo "Prerequisites:"
echo "  1. Install Codex CLI: brew install codex-cli"
echo "  2. Login to Codex: codex login"
echo "  3. Set GEMINI_API_KEY for Gemini support"
echo "  4. pip install google-genai"
echo ""
echo "Usage: Start a new Claude Code session and ask:"
echo "  'Use chatgpt to analyze [topic]'"
echo "  'Use gemini to reason about [topic]'"
echo "  'Use consensus to get both perspectives on [topic]'"
