# GPT Reasoner MCP Server

A pure reasoning assistant that runs inside Claude Code. Uses Codex CLI as the backend to access GPT models via your existing ChatGPT subscription—**no API billing required**.

## What It Does

Provides a `chatgpt` tool for qualitative reasoning:
- Brainstorming and ideation
- Strategic analysis
- Decision-making support
- Critique and devil's advocate
- Synthesis and summarization

**What it does NOT do:**
- Read files or code
- Inspect repositories
- Run commands
- Propose code changes

This is intentionally a reasoning-only tool.

## Prerequisites

### 1. Codex CLI

Install and authenticate Codex CLI:

```bash
brew install codex-cli
codex login
```

### 2. Codex Configuration

Ensure your `~/.codex/config.toml` has high reasoning effort:

```toml
model = "gpt-5.2-codex"
model_reasoning_effort = "high"
```

### 3. Python 3

The server requires Python 3.7+. No external dependencies needed.

## Installation

### Register with Claude Code

```bash
claude mcp add gpt-reasoner -- python ~/.claude/mcp/gpt-reasoner/server.py
```

Verify it's connected:

```bash
claude mcp list
```

## Usage

Once registered, ask Claude to use the `chatgpt` tool:

> "Use chatgpt to analyze the pros and cons of microservices vs monolith for our startup"

> "Get a second opinion on this product strategy: [paste strategy]"

> "Use chatgpt in questions mode to help me think through this decision"

### Tool Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reasoning_input` | string | (required) | The topic or content to reason about |
| `depth` | `low` \| `medium` \| `high` | `high` | Reasoning effort level |
| `mode` | `memo` \| `bullets` \| `questions` | `memo` | Output format |
| `files` | array of strings | `[]` | Optional file paths to include in analysis |

### Analyzing Files

You can include files for ChatGPT to analyze:

```
Use chatgpt to analyze ~/Desktop/strategy.md and identify risks
```

```
Use chatgpt with files ["/path/to/doc1.md", "/path/to/doc2.txt"] to compare these approaches
```

The MCP server reads the files and includes their contents in the prompt. ChatGPT reasons about the content but cannot access files itself—this keeps the "no auto-scanning" behavior intact.

### Output Modes

**memo** (default): Structured analysis with Summary, Assumptions, Analysis, Options, Risks, Recommendation, and Next Questions.

**bullets**: Concise bullet-point analysis.

**questions**: Probing questions only—useful for exploring a topic.

## Testing

Run the smoke test:

```bash
~/.claude/mcp/gpt-reasoner/test.sh
```

Or test manually:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | python ~/.claude/mcp/gpt-reasoner/server.py
```

## Troubleshooting

### "Codex CLI not found"

Install Codex: `brew install codex-cli`

### "Not inside a trusted directory"

The server runs from `/tmp` and uses `--skip-git-repo-check` to avoid this. If you still see it, ensure you're using the latest Codex version.

### Timeout errors

High reasoning can take 30-90+ seconds. The default timeout is 180 seconds. For faster responses, use `depth: "low"`.

### Codex tries to read files anyway

The system prompt explicitly forbids file access. If Codex still tries, update your `~/.codex/config.toml` to ensure no default behaviors are overriding.

## How It Works

```
Claude Code
    ↓ MCP tool call
GPT Reasoner (server.py)
    ↓ subprocess
Codex CLI (codex exec)
    ↓ authenticated via ChatGPT subscription
GPT-5.2-Codex model
    ↓
Structured reasoning response
```

The MCP server:
1. Receives tool calls from Claude Code
2. Wraps the input with a strict "reasoning-only" system prompt
3. Shells out to `codex exec` with safeguards (no repo, read-only sandbox)
4. Parses and returns the response

## Uninstalling

```bash
claude mcp remove gpt-reasoner
rm -rf ~/.claude/mcp/gpt-reasoner
```

## License

MIT
