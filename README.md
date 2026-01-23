# Multi-Reasoner MCP Server

A reasoning assistant that runs inside Claude Code. Provides access to multiple AI backends for qualitative reasoning and code review.

## Tools

| Tool | Backend | Purpose |
|------|---------|---------|
| `chatgpt` | Codex CLI (GPT-5) | Pure reasoning via ChatGPT subscription |
| `gemini` | Gemini 2.5 Flash | Pure reasoning with 1M+ token context |
| `codex_review` | Codex CLI | Git-aware code review |

## What It Does

**chatgpt / gemini** - Pure reasoning tools for:
- Brainstorming and ideation
- Strategic analysis
- Decision-making support
- Critique and devil's advocate
- Synthesis and summarization

**codex_review** - Git-aware code review:
- Review uncommitted changes
- Review specific commits
- Compare branches
- Maker-checker workflow support

**What chatgpt/gemini do NOT do:**
- Read files automatically (but you can pass files explicitly)
- Inspect repositories
- Run commands
- Propose code changes

## Prerequisites

### For ChatGPT / Codex Review

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
pip install google-genai
```

## Installation

```bash
# Clone the repo
git clone https://github.com/adampaulwalker/chatgpt-mcp.git ~/.claude/mcp/multi-reasoner

# Register with Claude Code
claude mcp add multi-reasoner -- python ~/.claude/mcp/multi-reasoner/server.py

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

### Codex Review (Code Review)

```
Use codex_review to review uncommitted changes
```

```
Use codex_review to review the diff between main and this branch
```

### Tool Parameters

#### chatgpt / gemini

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reasoning_input` | string | (required) | Topic or content to reason about |
| `depth` | `low` \| `medium` \| `high` | `high` | Reasoning effort level |
| `mode` | `memo` \| `bullets` \| `questions` | `memo` | Output format |
| `files` | array of strings | `[]` | File paths to include in analysis |

#### codex_review

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `review_request` | string | (required) | What to review |
| `working_dir` | string | cwd | Git repo directory |

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

**questions**: Probing questions only—useful for exploring a topic.

## Testing

```bash
~/.claude/mcp/multi-reasoner/test.sh
```

Or test manually:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | python ~/.claude/mcp/multi-reasoner/server.py
```

## How It Works

```
Claude Code
    ↓ MCP tool call
Multi-Reasoner (server.py)
    ↓
    ├── chatgpt → Codex CLI → GPT-5.2-Codex
    ├── gemini  → Google API → Gemini 2.5 Flash
    └── codex_review → Codex CLI review
    ↓
Structured response
```

## Troubleshooting

### "Codex CLI not found"

Install: `brew install codex-cli`

### "GEMINI_API_KEY not set"

Export your API key: `export GEMINI_API_KEY="..."`

### Timeout errors

High reasoning can take 30-90+ seconds. Default timeout is 180s. Use `depth: "low"` for faster responses.

## Uninstalling

```bash
claude mcp remove multi-reasoner
rm -rf ~/.claude/mcp/multi-reasoner
```

## License

MIT
