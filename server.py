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
        # Codex output format:
        #   [metadata headers]
        #   user
        #   [user input]
        #   codex (or thinking)
        #   [model response]
        #   tokens used
        #   [token count]
        output = result.stdout
        lines = output.split('\n')

        # Find where model response starts (after 'codex' or 'thinking' line)
        response_start = -1
        response_end = len(lines)

        for i, line in enumerate(lines):
            if line.strip() in ('codex', 'thinking'):
                response_start = i + 1
            elif line.startswith('tokens used') and response_start >= 0:
                response_end = i
                break

        if response_start >= 0:
            response_lines = lines[response_start:response_end]
            clean_output = '\n'.join(response_lines).strip()
        else:
            # Fallback: return everything after removing obvious metadata
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


def get_codex_review_hint() -> dict:
    """
    Return a hint recommending the /codex skill for code review.

    The MCP's subprocess approach has timeout limitations for large repos.
    Running Codex via Bash (through the skill) allows background execution
    and no timeout constraints.
    """
    hint_text = """## Use the /codex skill instead

For code reviews, especially on large codebases, use the `/codex` skill which runs Codex via Bash.

**Why?** This MCP tool has timeout limitations. The /codex skill:
- Runs via Bash with no timeout constraints
- Can run in background for large reviews
- Supports all Codex review features

**To use:** Just invoke `/codex` or run `codex review` directly via Bash.

**Examples:**
```bash
# Review uncommitted changes
codex review "Review my uncommitted changes"

# Review specific commits
codex review "Review the last 3 commits"

# Review branch diff
codex review "Review changes between main and this branch"
```"""

    return {
        "success": True,
        "output": hint_text,
        "error": None
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


def call_consensus(prompt: str, depth: str = "high", mode: str = "memo", files: list = None) -> dict:
    """
    Call both ChatGPT and Gemini and return combined results.

    Args:
        prompt: The user's reasoning request
        depth: Reasoning effort (low, medium, high)
        mode: Output format (memo, bullets, questions)
        files: Optional list of file paths to include in analysis

    Returns:
        dict with 'success', 'output', and optionally 'error'
    """
    import concurrent.futures

    log(f"Calling consensus: depth={depth}, mode={mode}")

    results = {}
    errors = []

    # Run both models in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(call_codex, prompt, depth, mode, files): "chatgpt",
            executor.submit(call_gemini, prompt, depth, mode, files): "gemini"
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
        return {
            "success": False,
            "output": None,
            "error": "; ".join(errors)
        }

    # Format combined output
    output_parts = []
    for model in ["chatgpt", "gemini"]:
        if model in results:
            output_parts.append(f"## {model.upper()}\n\n{results[model]}")

    if errors:
        output_parts.append(f"\n---\n*Note: {'; '.join(errors)}*")

    combined = "\n\n---\n\n".join(output_parts)
    log(f"Consensus returned {len(combined)} chars from {len(results)} models")

    return {
        "success": True,
        "output": combined,
        "error": None
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
                    "description": "DEPRECATED: Returns instructions to use the /codex skill instead. For code reviews, the /codex skill runs via Bash without timeout limitations. Call this to get usage instructions.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "consensus",
                    "description": "Query BOTH ChatGPT and Gemini in parallel and return both responses for comparison. Use this when you want multiple perspectives on a reasoning task. Returns responses from both models side-by-side.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "reasoning_input": {
                                "type": "string",
                                "description": "The topic, question, or content you want both models to reason about."
                            },
                            "depth": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "default": "high",
                                "description": "Reasoning depth for both models."
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["memo", "bullets", "questions"],
                                "default": "memo",
                                "description": "Output format for both models."
                            },
                            "files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional file paths to include in analysis for both models."
                            }
                        },
                        "required": ["reasoning_input"]
                    }
                }
            ]
        }
    }

def handle_tools_call(request_id, params):
    """Handle tools/call request"""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if tool_name not in ("chatgpt", "gemini", "codex_review", "consensus"):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": f"Unknown tool: {tool_name}"
            }
        }

    # Handle codex_review - now just returns hint to use /codex skill
    if tool_name == "codex_review":
        result = get_codex_review_hint()
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
    elif tool_name == "gemini":
        result = call_gemini(reasoning_input, depth, mode, files)
    else:  # consensus
        result = call_consensus(reasoning_input, depth, mode, files)

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
