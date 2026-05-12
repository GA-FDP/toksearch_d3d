import io
import json
import sys
import pydoc
import traceback
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from pathlib import Path

import anthropic
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import toksearch
import toksearch_d3d

# --- Config ---
BASE_URL = "https://api.i2-core.american-science-cloud.org"
MODEL = "claude-sonnet-4-6"
#TODO: This code should be modified to support both using the AmSC LLM API and user's claude interchangeably
#TODO: There should also be a connectivity test to confirm it the LLM is playing nicely before running

# --- Load toksearch docs once at import time (replicates the SKILL.md instructions) ---
def _capture_help(obj):
    buf = io.StringIO()
    pydoc.Helper(output=buf)(obj)
    return buf.getvalue()

DOCS = _capture_help(toksearch) + "\n\n" + _capture_help(toksearch_d3d)

# --- Tool definitions for the Anthropic API ---
TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Execute a Python code string. The execution namespace persists across calls "
            "within a single query, so variables set in earlier calls are available later. "
            "The namespace is pre-populated with: toksearch, toksearch_d3d, plt (matplotlib.pyplot), "
            "pd (pandas), np (numpy). Returns captured stdout, stderr, and any exception. "
            "Always populate the 'thought' field with a one-sentence description of what this code does and why."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute.",
                },
                "thought": {
                    "type": "string",
                    "description": "One-sentence description of what this code does and why.",
                },
            },
            "required": ["code", "thought"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Signal that you have finished. Use this when you have a final answer. "
            "Provide either result_var (name of a variable in the namespace to return to the caller) "
            "or message (a plain-text answer)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "result_var": {
                    "type": "string",
                    "description": "Name of the variable in the execution namespace to return.",
                },
                "message": {
                    "type": "string",
                    "description": "Plain-text final answer if there is no variable to return.",
                },
            },
        },
    },
]

#This prompt should be seriously modified to include a few major guardrails
#TODO: This should be fully ephemeral (read: stop writing graph images to files)
SYSTEM_PROMPT = f"""You are an expert in the TokSearch Python library for fusion data retrieval.
You have access to a run_python tool to write and execute toksearch pipeline code iteratively.
When you have a working result, call finish with either the variable name holding the result or a message.

Rules:
- Do not include import statements; toksearch, toksearch_d3d, plt, pd, and np are already available.
- If code raises an error, read the traceback, fix the issue, and try again.
- Store your final pipeline or result in a variable named `result` before calling finish.

--- TokSearch Documentation ---
{DOCS}
"""


def _serialize_messages(messages: list) -> list:
    """Convert the messages list to a JSON-serializable structure.

    Assistant turns contain Anthropic SDK pydantic objects; user turns are plain dicts.
    """
    result = []
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list):
                content = [
                    b.model_dump() if hasattr(b, "model_dump") else b for b in content
                ]
            result.append({**msg, "content": content})
        else:
            result.append(msg)
    return result


def _run_code(code: str, namespace: dict) -> str:
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(code, namespace)  # noqa: S102
    except Exception:
        stderr_buf.write(traceback.format_exc())
    output = stdout_buf.getvalue()
    errors = stderr_buf.getvalue()
    parts = []
    if output:
        parts.append(f"stdout:\n{output}")
    if errors:
        parts.append(f"stderr:\n{errors}")
    return "\n".join(parts) if parts else "(no output)"


def query_toksearch(prompt: str, max_iterations: int = 10, verbose: bool = True, debug: bool = False, api_key_file: str | None = None):
    """
    Take a natural language prompt, use Claude to generate and iteratively
    execute toksearch code, and return the result.

    Args:
        prompt: Natural language description of the data you want.
        max_iterations: Maximum number of tool-call rounds before giving up.
        verbose: Print a one-line summary of each tool call (default True).
        debug: Print full code and output for each tool call (implies verbose).
    """
    if debug:
        verbose = True
        debug_dir = Path(f"toksearch_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        debug_dir.mkdir(parents=True, exist_ok=True)
        print(f"[debug] writing iteration files to {debug_dir}/")

    if api_key_file is None:
        api_key_file = Path(Path.home() / "amsc_api_key")

    API_KEY = api_key_file.read_text().strip()

    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

    namespace = {
        "toksearch": toksearch,
        "toksearch_d3d": toksearch_d3d,
        "plt": plt,
        "pd": pd,
        "np": np,
    }

    messages = [{"role": "user", "content": prompt}]

    for i in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Append assistant turn to history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text = next((b.text for b in response.content if hasattr(b, "text")), "")
            if verbose:
                print(f"[iter {i+1}] end_turn (no finish call) → returning text response")
            if debug:
                (debug_dir / "messages.json").write_text(
                    json.dumps(_serialize_messages(messages), indent=2)
                )
            return namespace.get("result", text)

        if response.stop_reason == "tool_use":
            tool_results = []
            done = False
            run_python_count = 0

            for block in response.content:
                if block.type != "tool_use":
                    continue

                if block.name == "run_python":
                    code = block.input["code"]
                    thought = block.input.get("thought", "")
                    output = _run_code(code, namespace)
                    failed = "stderr:" in output or "Traceback" in output
                    if verbose:
                        status = "✗" if failed else "✓"
                        print(f"[iter {i+1}] run_python: {thought} → {status}")
                    if debug:
                        run_python_count += 1
                        suffix = f"_{run_python_count}" if run_python_count > 1 else ""
                        debug_file = debug_dir / f"iter_{i+1:02d}{suffix}.py"
                        output_block = "\n".join(f"# {line}" for line in output.splitlines())
                        debug_file.write_text(
                            f"# thought: {thought}\n\n{code}\n\n# --- output ---\n{output_block}\n"
                        )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })

                elif block.name == "finish":
                    result_var = block.input.get("result_var")
                    message = block.input.get("message")
                    if verbose:
                        label = f"result_var='{result_var}'" if result_var else f"message='{str(message)[:60]}'"
                        print(f"[iter {i+1}] finish → {label}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Done.",
                    })
                    done = True
                    final = namespace.get(result_var) if result_var else message

            messages.append({"role": "user", "content": tool_results})

            if done:
                if debug:
                    (debug_dir / "messages.json").write_text(
                        json.dumps(_serialize_messages(messages), indent=2)
                    )
                return final

    if verbose:
        print(f"[warning] reached max iterations ({max_iterations}) without a finish call")
    if debug:
        (debug_dir / "messages.json").write_text(
            json.dumps(_serialize_messages(messages), indent=2)
        )
    return namespace.get("result", "Reached max iterations without a final answer.")


if __name__ == "__main__":
    debug = "--debug" in sys.argv
    prompt = input("Query: ").strip()
    result = query_toksearch(prompt, debug=debug)
    print(result)

