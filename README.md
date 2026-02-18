# Multi-Reasoner MCP Server

A reasoning assistant that runs inside Claude Code. Provides access to multiple AI backends for qualitative reasoning.

## Tools

| Tool | Backend | Purpose |
|------|---------|---------|
| `chatgpt` | Codex CLI (GPT-5) | Pure reasoning via ChatGPT subscription |
| `gemini` | Gemini 2.5 Flash | Pure reasoning with 1M+ token context |
| `consensus` | Both GPT + Gemini | Query both models in parallel, compare responses |
| `codex_review` | *(deprecated)* | Returns instructions to use the `/codex` skill instead |

## What It Does

**chatgpt / gemini** - Pure reasoning tools for:
- Brainstorming and ideation
- Strategic analysis
- Decision-making support
- Critique and devil's advocate
- Synthesis and summarization

**What chatgpt/gemini do NOT do:**
- Run commands or modify files
- Automatically read your codebase (you must explicitly pass file paths)

You can optionally pass file paths via the `files` parameter to include their contents in the analysis. Safety restrictions apply:
- Only text-based extensions allowed (`.md`, `.py`, `.js`, `.json`, `.toml`, etc.)
- Known extensionless filenames allowed (`README`, `Makefile`, `Dockerfile`, etc.)
- Sensitive paths blocked (`.ssh`, `.env`, `.codex`, `.config`, credentials, etc.)
- Max 10 files per request, 512KB per file

## Prerequisites

### For ChatGPT

```bash
brew install codex-cli
codex login
```

Ensure your `~/.codex/config.toml` has:

```toml
model = "gpt-5.2-codex"
model_reasoning_effort = "high"
```

### For Gemini

Set your API key:

```bash
export GEMINI_API_KEY="your-api-key"
```

Add to your shell profile for persistence.

### Python Dependencies

```bash
pip install mcp google-genai
```

## Installation

```bash
# Clone the repo
git clone https://github.com/adampaulwalker/multi-reasoner.git ~/.claude/mcp/multi-reasoner

# Register with Claude Code
claude mcp add multi-reasoner -- python3 ~/.claude/mcp/multi-reasoner/server.py

# Verify
claude mcp list
```

## Usage

### ChatGPT (Pure Reasoning)

```
Use chatgpt to analyze the pros and cons of microservices vs monolith
```

```
Get a second opinion from chatgpt on this strategy: [paste strategy]
```

### Gemini (Pure Reasoning)

```
Use gemini to analyze this architecture decision
```

```
Ask gemini to critique this proposal with depth high
```

### Consensus (Multi-Model)

```
Use consensus to get perspectives from both GPT and Gemini on this decision
```

```
Ask consensus to analyze this architecture with depth high
```

### Tool Parameters

#### chatgpt / gemini / consensus

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reasoning_input` | string | (required) | Topic or content to reason about |
| `depth` | `low` \| `medium` \| `high` | `high` | Reasoning effort level |
| `mode` | `memo` \| `bullets` \| `questions` \| `quick` | `memo` | Output format |
| `files` | array of strings | `[]` | File paths to include in analysis (safe extensions only) |

### Analyzing Files

Pass files explicitly to include their contents:

```
Use gemini to analyze ~/Desktop/strategy.md and identify risks
```

```
Use chatgpt with files ["/path/to/doc1.md", "/path/to/doc2.txt"] to compare approaches
```

### Output Modes

**memo** (default): Structured analysis with Summary, Assumptions, Analysis, Options, Risks, Recommendation, and Next Questions.

**bullets**: Concise bullet-point analysis.

**questions**: Probing questions only - useful for exploring a topic.

**quick**: Direct 2-5 sentence answer with no formatting.

## Testing

```bash
~/.claude/mcp/multi-reasoner/test.sh
```

## How It Works

```
Claude Code
    ↓ MCP tool call
Multi-Reasoner (server.py)
    ↓
    ├── chatgpt   → Codex CLI → GPT-5.2-Codex
    ├── gemini    → Google API → Gemini 2.5 Flash
    └── consensus → Both (parallel) → Combined response
    ↓
Structured response
```

## Troubleshooting

### "Codex CLI not found"

Install: `brew install codex-cli`

### "GEMINI_API_KEY not set"

Export your API key: `export GEMINI_API_KEY="..."`

### "google-genai not available"

Install: `pip install google-genai`

### Timeout errors

High reasoning can take 30-90+ seconds. Default timeout is 180s. Use `depth: "low"` for faster responses.

## Uninstalling

```bash
claude mcp remove multi-reasoner
rm -rf ~/.claude/mcp/multi-reasoner
```

## License

MIT
