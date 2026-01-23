#!/usr/bin/env python3
"""
Multi-Reasoner MCP Server

A pure reasoning assistant that uses multiple AI backends (GPT-5, Gemini).
This is NOT a coding agent - it provides qualitative reasoning only.

Usage:
    python server.py

Tools: chatgpt (GPT-5 via Codex), gemini (Gemini 2.5 Pro)
"""

import json
import os
import subprocess
import sys
from typing import Optional

from google import genai
from google.genai import types

# System instruction to force reasoning-only mode
REASONING_SYSTEM_PROMPT = """You are a reasoning-only assistant and second-thought partner.

CRITICAL CONSTRAINTS - YOU MUST OBEY THESE:
- You must NOT use any tools to inspect repositories or access the filesystem
- You must NOT propose code changes, diffs, or patches
- You must NOT run commands or assume any code context
- You must NOT reference the current working directory
- ONLY reason from the text and file contents provided in this prompt
- If file contents are attached below, analyze them as provided - do NOT try to access them yourself

Your ONLY job is to reason deeply about the text and any attached file contents provided."""

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
- Just list the questions, no other commentary"""
}

# Map depth parameter to Codex reasoning effort
DEPTH_MAP = {
    "low": "low",
    "medium": "medium",
    "high": "high"
}

def log(msg: str):
    """Log to stderr (won't interfere with MCP protocol on stdout)"""
    print(f"[multi-reasoner] {msg}", file=sys.stderr)

def read_files(file_paths: list) -> tuple[str, list]:
    """
    Read specified files and return their contents.

    Args:
        file_paths: List of file paths to read

    Returns:
        Tuple of (combined file contents as string, list of any errors)
    """
    contents = []
    errors = []

    for path in file_paths:
        try:
            # Expand ~ to home directory
            expanded_path = os.path.expanduser(path)

            with open(expanded_path, 'r', encoding='utf-8') as f:
                content = f.read()
                contents.append(f"=== FILE: {path} ===\n{content}\n=== END FILE ===")
                log(f"Read file: {path} ({len(content)} chars)")
        except FileNotFoundError:
            errors.append(f"File not found: {path}")
            log(f"File not found: {path}")
        except PermissionError:
            errors.append(f"Permission denied: {path}")
            log(f"Permission denied: {path}")
        except Exception as e:
            errors.append(f"Error reading {path}: {str(e)}")
            log(f"Error reading {path}: {e}")

    return '\n\n'.join(contents), errors


def call_codex(prompt: str, depth: str = "high", mode: str = "memo", files: list = None, timeout: int = 180) -> dict:
    """
    Call Codex CLI with the given prompt in reasoning-only mode.

    Args:
        prompt: The user's reasoning request
        depth: Reasoning effort (low, medium, high)
        mode: Output format (memo, bullets, questions)
        files: Optional list of file paths to include in analysis
        timeout: Max seconds to wait

    Returns:
        dict with 'success', 'output', and optionally 'error'
    """
    # Get output format instructions
    format_instructions = OUTPUT_FORMATS.get(mode, OUTPUT_FORMATS["memo"])

    # Read any specified files
    file_contents = ""
    file_errors = []
    if files:
        file_contents, file_errors = read_files(files)
        if file_contents:
            file_contents = f"\n\n--- ATTACHED FILES ---\n{file_contents}\n--- END ATTACHED FILES ---"

    # Construct the full prompt with system instruction
    full_prompt = f"""{REASONING_SYSTEM_PROMPT}
{format_instructions}

---

USER INPUT:
{prompt}{file_contents}"""

    # Add file reading errors as context if any
    if file_errors:
        full_prompt += f"\n\n(Note: Some files could not be read: {'; '.join(file_errors)})"

    # Map depth to reasoning effort
    reasoning_effort = DEPTH_MAP.get(depth, "high")

    # Build codex command
    # Run from /tmp to avoid any repo context
    # Use --skip-git-repo-check to prevent git errors
    # Use read-only sandbox as extra safeguard
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
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/tmp"  # Neutral directory - no repo context
        )

        if result.returncode != 0:
            error_msg = result.stderr or f"Codex exited with code {result.returncode}"
            log(f"Codex error: {error_msg}")
            return {
                "success": False,
                "output": None,
                "error": error_msg
            }

        # Extract the model's response from Codex output
        output = result.stdout
        lines = output.split('\n')
        response_lines = []
        skip_metadata = True

        for line in lines:
            # Skip Codex metadata header
            if skip_metadata:
                if line.startswith('OpenAI Codex') or line.startswith('--------') or \
                   line.startswith('workdir:') or line.startswith('model:') or \
                   line.startswith('provider:') or line.startswith('approval:') or \
                   line.startswith('sandbox:') or line.startswith('reasoning effort:') or \
                   line.startswith('reasoning summaries:') or line.startswith('session id:') or \
                   line.startswith('mcp startup:') or line == 'user':
                    continue
                # Check for start of actual content
                if line.startswith('thinking') or line.startswith('codex'):
                    skip_metadata = False
                    continue
                if line.strip() and not line.startswith(' '):
                    skip_metadata = False

            # Skip token count at the end
            if line.startswith('tokens used'):
                continue

            if not skip_metadata:
                response_lines.append(line)

        clean_output = '\n'.join(response_lines).strip()

        # Fallback: if parsing failed, return raw output minus obvious metadata
        if not clean_output:
            clean_output = output.strip()

        log(f"Codex returned {len(clean_output)} chars")
        return {
            "success": True,
            "output": clean_output,
            "error": None
        }

    except subprocess.TimeoutExpired:
        log(f"Codex timed out after {timeout}s")
        return {
            "success": False,
            "output": None,
            "error": f"Request timed out after {timeout} seconds. Try reducing depth or simplifying the input."
        }
    except FileNotFoundError:
        log("Codex CLI not found")
        return {
            "success": False,
            "output": None,
            "error": "Codex CLI not found. Install it with: brew install codex-cli"
        }
    except Exception as e:
        log(f"Unexpected error: {e}")
        return {
            "success": False,
            "output": None,
            "error": str(e)
        }


def call_codex_review(prompt: str, working_dir: str = None, timeout: int = 180) -> dict:
    """
    Call Codex CLI review command for code review.

    Unlike the generic chatgpt tool, this runs `codex review` which is
    git-aware and designed specifically for code review workflows.

    Args:
        prompt: The review request (e.g., "Review uncommitted changes")
        working_dir: Directory to run review from (must be a git repo)
        timeout: Max seconds to wait

    Returns:
        dict with 'success', 'output', and optionally 'error'
    """
    # Build codex review command
    cmd = [
        "codex", "review",
        prompt
    ]

    # Use provided working dir or current directory
    cwd = working_dir or os.getcwd()

    log(f"Calling Codex review: prompt={prompt[:50]}..., cwd={cwd}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd
        )

        if result.returncode != 0:
            error_msg = result.stderr or f"Codex review exited with code {result.returncode}"
            log(f"Codex review error: {error_msg}")
            return {
                "success": False,
                "output": None,
                "error": error_msg
            }

        # Extract the model's response from Codex output
        output = result.stdout
        lines = output.split('\n')
        response_lines = []
        skip_metadata = True

        for line in lines:
            # Skip Codex metadata header
            if skip_metadata:
                if line.startswith('OpenAI Codex') or line.startswith('--------') or \
                   line.startswith('workdir:') or line.startswith('model:') or \
                   line.startswith('provider:') or line.startswith('approval:') or \
                   line.startswith('sandbox:') or line.startswith('reasoning effort:') or \
                   line.startswith('reasoning summaries:') or line.startswith('session id:') or \
                   line.startswith('mcp startup:') or line == 'user':
                    continue
                if line.startswith('thinking') or line.startswith('codex'):
                    skip_metadata = False
                    continue
                if line.strip() and not line.startswith(' '):
                    skip_metadata = False

            # Skip token count at the end
            if line.startswith('tokens used'):
                continue

            if not skip_metadata:
                response_lines.append(line)

        clean_output = '\n'.join(response_lines).strip()

        # Fallback: if parsing failed, return raw output minus obvious metadata
        if not clean_output:
            clean_output = output.strip()

        log(f"Codex review returned {len(clean_output)} chars")
        return {
            "success": True,
            "output": clean_output,
            "error": None
        }

    except subprocess.TimeoutExpired:
        log(f"Codex review timed out after {timeout}s")
        return {
            "success": False,
            "output": None,
            "error": f"Review timed out after {timeout} seconds."
        }
    except FileNotFoundError:
        log("Codex CLI not found")
        return {
            "success": False,
            "output": None,
            "error": "Codex CLI not found. Install it with: brew install codex-cli"
        }
    except Exception as e:
        log(f"Unexpected error: {e}")
        return {
            "success": False,
            "output": None,
            "error": str(e)
        }


def call_gemini(prompt: str, depth: str = "high", mode: str = "memo", files: list = None, timeout: int = 180) -> dict:
    """
    Call Gemini API with the given prompt in reasoning-only mode.

    Args:
        prompt: The user's reasoning request
        depth: Reasoning effort (low, medium, high)
        mode: Output format (memo, bullets, questions)
        files: Optional list of file paths to include in analysis
        timeout: Max seconds to wait (not directly used by Gemini SDK)

    Returns:
        dict with 'success', 'output', and optionally 'error'
    """
    # Check for API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "success": False,
            "output": None,
            "error": "GEMINI_API_KEY environment variable not set"
        }

    # Get output format instructions
    format_instructions = OUTPUT_FORMATS.get(mode, OUTPUT_FORMATS["memo"])

    # Read any specified files
    file_contents = ""
    file_errors = []
    if files:
        file_contents, file_errors = read_files(files)
        if file_contents:
            file_contents = f"\n\n--- ATTACHED FILES ---\n{file_contents}\n--- END ATTACHED FILES ---"

    # Construct the full prompt with system instruction
    full_prompt = f"""{REASONING_SYSTEM_PROMPT}
{format_instructions}

---

USER INPUT:
{prompt}{file_contents}"""

    # Add file reading errors as context if any
    if file_errors:
        full_prompt += f"\n\n(Note: Some files could not be read: {'; '.join(file_errors)})"

    # Map depth to thinking budget (Gemini 2.5 uses thinking tokens)
    thinking_budget_map = {
        "low": 1024,
        "medium": 8192,
        "high": 24576
    }
    thinking_budget = thinking_budget_map.get(depth, 24576)

    log(f"Calling Gemini: depth={depth}, mode={mode}, thinking_budget={thinking_budget}")

    try:
        # Use the new google-genai SDK with thinking support
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=1.0,
                max_output_tokens=16384,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=thinking_budget
                )
            )
        )

        if response.text:
            log(f"Gemini returned {len(response.text)} chars")
            return {
                "success": True,
                "output": response.text,
                "error": None
            }
        else:
            log("Gemini returned empty response")
            return {
                "success": False,
                "output": None,
                "error": "Gemini returned an empty response"
            }

    except Exception as e:
        log(f"Gemini error: {e}")
        return {
            "success": False,
            "output": None,
            "error": str(e)
        }


def handle_initialize(request_id):
    """Handle MCP initialize request"""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "multi-reasoner",
                "version": "1.0.0"
            }
        }
    }

def handle_tools_list(request_id):
    """Handle tools/list request"""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "tools": [
                {
                    "name": "chatgpt",
                    "description": "Consult ChatGPT for qualitative reasoning. This is a pure reasoning tool - it will NOT read files, inspect code, or run commands. Use it for brainstorming, analysis, critique, strategic thinking, decision-making, or any non-code reasoning task.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "reasoning_input": {
                                "type": "string",
                                "description": "The topic, question, or content you want GPT to reason about. Provide full context - the tool cannot see any files or code."
                            },
                            "depth": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "default": "high",
                                "description": "Reasoning depth. 'high' recommended for complex topics. 'low' for quick takes."
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["memo", "bullets", "questions"],
                                "default": "memo",
                                "description": "Output format. 'memo' for structured analysis, 'bullets' for concise points, 'questions' for probing questions only."
                            },
                            "files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of file paths to include in the analysis. Files are read and their contents are provided to ChatGPT for reasoning. Use for documents, notes, or any text files you want analyzed."
                            }
                        },
                        "required": ["reasoning_input"]
                    }
                },
                {
                    "name": "gemini",
                    "description": "Consult Google Gemini 2.5 Flash for qualitative reasoning. This is a pure reasoning tool - it will NOT read files, inspect code, or run commands. Use it for brainstorming, analysis, critique, strategic thinking, decision-making, or any non-code reasoning task. Gemini has a 1M+ token context window.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "reasoning_input": {
                                "type": "string",
                                "description": "The topic, question, or content you want Gemini to reason about. Provide full context - the tool cannot see any files or code."
                            },
                            "depth": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "default": "high",
                                "description": "Reasoning depth. 'high' recommended for complex topics. 'low' for quick takes."
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["memo", "bullets", "questions"],
                                "default": "memo",
                                "description": "Output format. 'memo' for structured analysis, 'bullets' for concise points, 'questions' for probing questions only."
                            },
                            "files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of file paths to include in the analysis. Files are read and their contents are provided to Gemini for reasoning. Use for documents, notes, or any text files you want analyzed."
                            }
                        },
                        "required": ["reasoning_input"]
                    }
                },
                {
                    "name": "codex_review",
                    "description": "Use OpenAI Codex CLI to perform code review. Unlike chatgpt/gemini (pure reasoning), this tool is git-aware and designed for maker-checker workflows. It reviews uncommitted changes, specific commits, or diffs between branches. Requires being in a git repository.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "review_request": {
                                "type": "string",
                                "description": "What to review. Examples: 'Review uncommitted changes', 'Review the changes in commit abc123', 'Review the diff between main and this branch', 'Review the implementation in src/auth.ts'"
                            },
                            "working_dir": {
                                "type": "string",
                                "description": "Optional: Directory to run review from (must be a git repo). Defaults to current working directory."
                            }
                        },
                        "required": ["review_request"]
                    }
                }
            ]
        }
    }

def handle_tools_call(request_id, params):
    """Handle tools/call request"""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if tool_name not in ("chatgpt", "gemini", "codex_review"):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": f"Unknown tool: {tool_name}"
            }
        }

    # Handle codex_review separately (different parameters)
    if tool_name == "codex_review":
        review_request = arguments.get("review_request", "")
        working_dir = arguments.get("working_dir")

        if not review_request:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "review_request is required"
                }
            }

        result = call_codex_review(review_request, working_dir)

        if result["success"]:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": result["output"]
                        }
                    ]
                }
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {result['error']}"
                        }
                    ],
                    "isError": True
                }
            }

    # Handle chatgpt/gemini (reasoning tools)
    reasoning_input = arguments.get("reasoning_input", "")
    depth = arguments.get("depth", "high")
    mode = arguments.get("mode", "memo")
    files = arguments.get("files", [])

    if not reasoning_input:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": "reasoning_input is required"
            }
        }

    # Validate parameters
    if depth not in DEPTH_MAP:
        depth = "high"
    if mode not in OUTPUT_FORMATS:
        mode = "memo"
    if not isinstance(files, list):
        files = []

    # Call the appropriate backend
    if tool_name == "chatgpt":
        result = call_codex(reasoning_input, depth, mode, files)
    else:  # gemini
        result = call_gemini(reasoning_input, depth, mode, files)

    if result["success"]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": result["output"]
                    }
                ]
            }
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: {result['error']}"
                    }
                ],
                "isError": True
            }
        }

def handle_request(request: dict) -> Optional[dict]:
    """Route request to appropriate handler"""
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params", {})

    # Notifications (no id) don't need responses
    if request_id is None:
        if method == "notifications/initialized":
            log("Client initialized")
        return None

    if method == "initialize":
        return handle_initialize(request_id)
    elif method == "tools/list":
        return handle_tools_list(request_id)
    elif method == "tools/call":
        return handle_tools_call(request_id, params)
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }

def main():
    """Main MCP server loop"""
    log("Starting GPT Reasoner MCP server...")

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                log("EOF received, shutting down")
                break

            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            response = handle_request(request)

            if response:
                print(json.dumps(response), flush=True)

        except json.JSONDecodeError as e:
            log(f"JSON decode error: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                }
            }
            print(json.dumps(error_response), flush=True)
        except Exception as e:
            log(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
