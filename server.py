#!/usr/bin/env python3
"""
Multi-Reasoner MCP Server

A pure reasoning assistant that uses multiple AI backends (GPT-5, Gemini).
This is NOT a coding agent - it provides qualitative reasoning only.

Usage:
    python server.py

Tools: chatgpt (GPT-5 via Codex), gemini (Gemini 2.5 Flash), consensus (both)
"""

import concurrent.futures
import json
import os
import stat as stat_mod
import subprocess
import sys
import threading
from typing import Optional

from mcp.server.fastmcp import FastMCP

# Lazy import google.genai - deferred to first Gemini call so the MCP server
# can start even if the package or API key isn't available
genai = None
types = None
_genai_lock = threading.Lock()

def _ensure_genai():
    global genai, types
    if genai is not None and types is not None:
        return
    with _genai_lock:
        if genai is not None and types is not None:
            return
        from google import genai as _genai
        from google.genai import types as _types
        types = _types
        genai = _genai

# System instruction for reasoning mode
REASONING_SYSTEM_PROMPT = """You are a reasoning assistant providing a second opinion.

Analyze the input provided and give your perspective. If file contents are attached, analyze them as given.

Be direct and helpful. Skip meta-commentary about what you can or can't do - just answer the question."""

# Output format instructions based on mode
OUTPUT_FORMATS = {
    "memo": """
OUTPUT FORMAT - Structure your response as a memo:

## Summary
[2-3 sentence overview of the core insight]

## Key Assumptions
[Bullet list of assumptions you're making]

## Analysis
[Deep reasoning about the topic - this is the main section]

## Options
[If applicable: different approaches or perspectives]

## Risks
[Potential downsides, blind spots, or concerns]

## Recommendation
[Your synthesized recommendation or conclusion]

## Next Questions
[Questions that would help refine the thinking further]

Keep it concise but deep. Prioritize insight over length.""",

    "bullets": """
OUTPUT FORMAT - Bullet points only:
- Provide your analysis as clear, concise bullet points
- Each bullet should be a distinct insight or observation
- Group related points together
- No headers or sections, just bullets
- Aim for 5-15 bullets depending on complexity""",

    "questions": """
OUTPUT FORMAT - Questions only:
- Generate probing questions that would help think through this topic
- Include questions that challenge assumptions
- Include questions that explore implications
- Include questions that identify unknowns
- Aim for 5-10 high-quality questions
- Just list the questions, no other commentary""",

    "quick": """
OUTPUT FORMAT - Quick response:
- Give a direct, concise answer
- No sections or formatting
- 2-5 sentences max"""
}

# Map depth parameter to Codex reasoning effort
DEPTH_MAP = {
    "low": "low",
    "medium": "medium",
    "high": "high"
}

def log(msg: str):
    """Log to stderr (won't interfere with MCP protocol on stdout)"""
    print(f"[multi-reasoner] {msg}", file=sys.stderr, flush=True)

# Sensitive path patterns that should never be read
_BLOCKED_PATTERNS = (
    '.ssh', '.gnupg', '.aws', '.env', '.netrc',
    'credentials', 'secrets', '.git/config',
    'id_rsa', 'id_ed25519', 'id_ecdsa',
    '.claude/settings.json',
)

# Allowed file extensions for safety
_ALLOWED_EXTENSIONS = (
    '.md', '.txt', '.py', '.js', '.ts', '.jsx', '.tsx',
    '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini',
    '.html', '.css', '.csv', '.xml', '.rst', '.org',
    '.sh', '.bash', '.zsh', '.fish',
    '.go', '.rs', '.rb', '.php', '.java', '.kt', '.swift',
    '.c', '.h', '.cpp', '.hpp',
    '.sql', '.graphql', '.proto',
    '.tf', '.hcl',
)

# Known extensionless filenames that are safe to read
_ALLOWED_BASENAMES = (
    'README', 'LICENSE', 'LICENCE', 'Makefile', 'Dockerfile',
    'Vagrantfile', 'Gemfile', 'Rakefile', 'Procfile',
    'CHANGELOG', 'CONTRIBUTING', 'AUTHORS',
)


def _is_safe_path(path: str) -> tuple:
    """Check if a file path is safe to read. Returns (safe: bool, reason: str, resolved_path: str)."""
    resolved = os.path.realpath(os.path.expanduser(path))

    # Block sensitive path patterns
    lower_path = resolved.lower()
    for pattern in _BLOCKED_PATTERNS:
        if pattern in lower_path:
            return False, f"Blocked: path matches sensitive pattern '{pattern}'", resolved

    # Check extension or known basename
    basename = os.path.basename(resolved)
    _, ext = os.path.splitext(resolved)
    if ext.lower() not in _ALLOWED_EXTENSIONS and basename not in _ALLOWED_BASENAMES:
        return False, f"Blocked: '{basename}' not in allowed extensions or filenames", resolved

    return True, "", resolved


def read_files(file_paths: list) -> tuple:
    """Read specified files and return their contents. Applies safety checks."""
    contents = []
    errors = []

    for path in file_paths:
        safe, reason, resolved_path = _is_safe_path(path)
        if not safe:
            errors.append(f"{path}: {reason}")
            log(f"Blocked file read: {path} - {reason}")
            continue
        try:
            fd = os.open(resolved_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                stat = os.fstat(fd)
                if not stat_mod.S_ISREG(stat.st_mode):
                    os.close(fd)
                    errors.append(f"{path}: Not a regular file")
                    continue
                with os.fdopen(fd, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                os.close(fd)
                raise
            contents.append(f"=== FILE: {path} ===\n{content}\n=== END FILE ===")
            log(f"Read file: {path} ({len(content)} chars)")
        except FileNotFoundError:
            errors.append(f"File not found: {path}")
        except PermissionError:
            errors.append(f"Permission denied: {path}")
        except Exception as e:
            errors.append(f"Error reading {path}: {str(e)}")

    return '\n\n'.join(contents), errors


def _build_prompt(prompt: str, mode: str, files: list = None) -> str:
    """Build the full prompt with system instruction, format, and file contents."""
    format_instructions = OUTPUT_FORMATS.get(mode, OUTPUT_FORMATS["memo"])

    file_contents = ""
    file_errors = []
    if files:
        file_contents, file_errors = read_files(files)
        if file_contents:
            file_contents = f"\n\n--- ATTACHED FILES ---\n{file_contents}\n--- END ATTACHED FILES ---"

    full_prompt = f"""{REASONING_SYSTEM_PROMPT}
{format_instructions}

---

USER INPUT:
{prompt}{file_contents}"""

    if file_errors:
        full_prompt += f"\n\n(Note: Some files could not be read: {'; '.join(file_errors)})"

    return full_prompt


def _call_codex(prompt: str, depth: str = "high", mode: str = "memo", files: list = None, timeout: int = 180) -> dict:
    """Call Codex CLI with the given prompt in reasoning-only mode."""
    full_prompt = _build_prompt(prompt, mode, files)
    reasoning_effort = DEPTH_MAP.get(depth, "high")

    cmd = [
        "codex", "exec",
        "--skip-git-repo-check",
        "-c", f'model_reasoning_effort="{reasoning_effort}"',
        "-s", "read-only",
        "--color", "never",
        full_prompt
    ]

    log(f"Calling Codex: depth={depth}, mode={mode}, effort={reasoning_effort}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd="/tmp"
        )

        if result.returncode != 0:
            error_msg = result.stderr or f"Codex exited with code {result.returncode}"
            return {"success": False, "output": None, "error": error_msg}

        output = result.stdout
        lines = output.split('\n')

        response_start = -1
        response_end = len(lines)

        for i, line in enumerate(lines):
            if line.strip() in ('codex', 'thinking'):
                response_start = i + 1
            elif line.startswith('tokens used') and response_start >= 0:
                response_end = i
                break

        if response_start >= 0:
            clean_output = '\n'.join(lines[response_start:response_end]).strip()
        else:
            clean_output = output.strip()

        log(f"Codex returned {len(clean_output)} chars")
        return {"success": True, "output": clean_output, "error": None}

    except subprocess.TimeoutExpired:
        return {"success": False, "output": None, "error": f"Timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "output": None, "error": "Codex CLI not found. Install: brew install codex-cli"}
    except Exception as e:
        return {"success": False, "output": None, "error": str(e)}


def _call_gemini(prompt: str, depth: str = "high", mode: str = "memo", files: list = None, timeout: int = 180) -> dict:
    """Call Gemini API with the given prompt in reasoning-only mode."""
    try:
        _ensure_genai()
    except ImportError as e:
        return {"success": False, "output": None, "error": f"google-genai not available: {e}"}
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"success": False, "output": None, "error": "GEMINI_API_KEY not set"}

    full_prompt = _build_prompt(prompt, mode, files)

    thinking_budget_map = {"low": 1024, "medium": 8192, "high": 24576}
    thinking_budget = thinking_budget_map.get(depth, 24576)

    log(f"Calling Gemini: depth={depth}, mode={mode}, thinking_budget={thinking_budget}")

    def _gemini_request():
        client = genai.Client(api_key=api_key)
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=1.0,
                max_output_tokens=16384,
                thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget)
            )
        )

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_gemini_request)
        response = future.result(timeout=timeout)

        if response.text:
            log(f"Gemini returned {len(response.text)} chars")
            return {"success": True, "output": response.text, "error": None}
        else:
            return {"success": False, "output": None, "error": "Gemini returned empty response"}

    except concurrent.futures.TimeoutError:
        log(f"Gemini timed out after {timeout}s")
        future.cancel()
        executor.shutdown(wait=False)
        return {"success": False, "output": None, "error": f"Timed out after {timeout}s"}
    except Exception as e:
        log(f"Gemini error: {e}")
        return {"success": False, "output": None, "error": str(e)}
    finally:
        executor.shutdown(wait=False)


def _call_consensus(prompt: str, depth: str = "high", mode: str = "memo", files: list = None) -> dict:
    """Call both ChatGPT and Gemini in parallel and return combined results."""
    log(f"Calling consensus: depth={depth}, mode={mode}")

    results = {}
    errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_call_codex, prompt, depth, mode, files): "chatgpt",
            executor.submit(_call_gemini, prompt, depth, mode, files): "gemini"
        }

        for future in concurrent.futures.as_completed(futures):
            model = futures[future]
            try:
                result = future.result()
                if result["success"]:
                    results[model] = result["output"]
                else:
                    errors.append(f"{model}: {result['error']}")
            except Exception as e:
                errors.append(f"{model}: {str(e)}")

    if not results:
        return {"success": False, "output": None, "error": "; ".join(errors)}

    output_parts = []
    for model in ["chatgpt", "gemini"]:
        if model in results:
            output_parts.append(f"## {model.upper()}\n\n{results[model]}")

    if errors:
        output_parts.append(f"\n---\n*Note: {'; '.join(errors)}*")

    combined = "\n\n---\n\n".join(output_parts)
    log(f"Consensus returned {len(combined)} chars from {len(results)} models")

    return {"success": True, "output": combined, "error": None}


# ---- MCP Server using official SDK ----

mcp = FastMCP("multi-reasoner")


@mcp.tool(structured_output=False)
def chatgpt(
    reasoning_input: str,
    depth: str = "high",
    mode: str = "memo",
    files: Optional[list] = None
) -> str:
    """Consult ChatGPT (GPT-5 via Codex) for qualitative reasoning. Optionally pass file paths to include their contents (restricted to safe text-based extensions). Use for brainstorming, analysis, critique, strategic thinking, decision-making, or any non-code reasoning task."""
    result = _call_codex(reasoning_input, depth, mode, files or [])
    if result["success"]:
        return result["output"]
    else:
        return f"Error: {result['error']}"


@mcp.tool(structured_output=False)
def gemini(
    reasoning_input: str,
    depth: str = "high",
    mode: str = "memo",
    files: Optional[list] = None
) -> str:
    """Consult Google Gemini 2.5 Flash for qualitative reasoning. Optionally pass file paths to include their contents (restricted to safe text-based extensions). Use for brainstorming, analysis, critique, strategic thinking, decision-making. Has 1M+ token context window."""
    result = _call_gemini(reasoning_input, depth, mode, files or [])
    if result["success"]:
        return result["output"]
    else:
        return f"Error: {result['error']}"


@mcp.tool(structured_output=False)
def consensus(
    reasoning_input: str,
    depth: str = "high",
    mode: str = "memo",
    files: Optional[list] = None
) -> str:
    """Query BOTH ChatGPT and Gemini in parallel and return both responses for comparison. Use when you want multiple perspectives on a reasoning task. Returns responses from both models side-by-side."""
    result = _call_consensus(reasoning_input, depth, mode, files or [])
    if result["success"]:
        return result["output"]
    else:
        return f"Error: {result['error']}"


@mcp.tool(structured_output=False)
def codex_review() -> str:
    """DEPRECATED: Use the /codex skill instead for code reviews. Returns usage instructions."""
    return """## Use the /codex skill instead

For code reviews, use the `/codex` skill which runs Codex via Bash.

**Why?** This MCP tool has timeout limitations. The /codex skill:
- Runs via Bash with no timeout constraints
- Can run in background for large reviews
- Supports all Codex review features

**Examples:**
```bash
codex review "Review my uncommitted changes"
codex review "Review the last 3 commits"
```"""


if __name__ == "__main__":
    log("Starting multi-reasoner MCP server (FastMCP SDK)...")
    mcp.run(transport="stdio")
