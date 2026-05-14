import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import toksearch
import toksearch_d3d

from toksearch_d3d.fdp.skills import get_system_prompt

# --- Config ---
AMSC_BASE_URL = "https://api.i2-core.american-science-cloud.org"
AMSC_MODEL_ID = "anthropic/claude-sonnet-4-6"

# Imports the agent is allowed to use — everything else is blocked at the AST level.
AUTHORIZED_IMPORTS = [
    "toksearch",
    "toksearch_d3d",
    "matplotlib",
    "matplotlib.pyplot",
    "numpy",
    "pandas",
    "xarray",
]

_RULES = """\
You are an expert in the TokSearch Python library for DIII-D fusion data retrieval.
Write and execute toksearch pipeline code iteratively until you have a result.
When done, call final_answer(result).

Rules:
- Do not write import statements. toksearch, toksearch_d3d, plt (matplotlib.pyplot), \
pd (pandas), and np (numpy) are already bound in the namespace.
- If code raises an error, read the traceback, fix the issue, and try again.
- Do not write files or save plots to disk. Return data objects (DataArrays, DataFrames, dicts) only.
- Do not attempt to import os, sys, subprocess, socket, requests, or any module not in \
the authorized list — those calls will fail.
- Add a brief comment at the top of each code block explaining what it does.
- Store your final result in a variable named `result`, then call final_answer(result).
"""


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------

def create_model(backend: str = "amsc", **kwargs):
    """Return the appropriate smolagents model object for the given backend.

    Parameters
    ----------
    backend:
        One of ``"amsc"`` (default), ``"openai"``, ``"anthropic"``, ``"transformers"``.
    **kwargs:
        Backend-specific options forwarded to the smolagents model constructor.
        For ``"amsc"``: optional ``api_key_file`` (Path, default ``~/amsc_api_key``),
        ``model_id``, ``api_base``.
        For ``"openai"``: ``model_id``, ``api_base``, ``api_key``.
        For ``"anthropic"``: optional ``model_id``.
        For ``"transformers"``: ``model_id``.
    """
    if backend == "amsc":
        from smolagents import LiteLLMModel
        api_key_file = kwargs.pop("api_key_file", Path.home() / "amsc_api_key")
        api_key = Path(api_key_file).read_text().strip()
        return LiteLLMModel(
            model_id=kwargs.pop("model_id", AMSC_MODEL_ID),
            api_base=kwargs.pop("api_base", AMSC_BASE_URL),
            api_key=api_key,
            **kwargs,
        )
    elif backend == "openai":
        from smolagents import OpenAIServerModel
        return OpenAIServerModel(**kwargs)
    elif backend == "anthropic":
        from smolagents import LiteLLMModel
        model_id = kwargs.pop("model_id", "anthropic/claude-sonnet-4-6")
        return LiteLLMModel(model_id=model_id, **kwargs)
    elif backend == "transformers":
        from smolagents import TransformersModel
        return TransformersModel(**kwargs)
    else:
        raise ValueError(
            f"Unknown backend {backend!r}. "
            "Choose from: 'amsc', 'openai', 'anthropic', 'transformers'."
        )


# ---------------------------------------------------------------------------
# Connectivity check
# ---------------------------------------------------------------------------

def _verify_model_connection(model, backend: str) -> None:
    """Raise RuntimeError with a clear message if the model endpoint is unreachable."""
    try:
        # smolagents models accept a list of message dicts or ChatMessage objects.
        # Use the dict form for broadest compatibility across versions.
        response = model([{"role": "user", "content": "ping"}])
        if response is None or not str(response.content if hasattr(response, "content") else response).strip():
            raise ValueError("empty response from model")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Model connectivity check failed (backend={backend!r}): {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _make_system_prompt() -> str:
    """Compose the full system prompt: CodeAgent base + rules + skills docs."""
    try:
        from smolagents.prompts import CODE_SYSTEM_PROMPT
        base = CODE_SYSTEM_PROMPT
    except ImportError:
        base = ""

    skills = get_system_prompt()
    sections = [s for s in [base, _RULES, "--- TokSearch Documentation ---\n\n" + skills] if s]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Namespace pre-population
# ---------------------------------------------------------------------------

def _setup_namespace(agent) -> None:
    """Inject pre-loaded variables into the agent's Python interpreter.

    smolagents' LocalPythonInterpreter maintains a ``state`` dict that persists
    across code blocks. Injecting here means the LLM can use toksearch, plt, etc.
    without writing import statements.

    Falls back silently if the interpreter API differs across smolagents versions.
    """
    ns = {
        "toksearch": toksearch,
        "toksearch_d3d": toksearch_d3d,
        "plt": plt,
        "pd": pd,
        "np": np,
    }
    try:
        agent.python_executor.state.update(ns)
    except AttributeError:
        # Interpreter API varies; LLM can still import from the whitelist.
        pass


# ---------------------------------------------------------------------------
# Debug callback
# ---------------------------------------------------------------------------

class _DebugCallback:
    """Write per-iteration debug files in the style of claude_toksearch_agent."""

    def __init__(self, debug_dir: Path) -> None:
        self.debug_dir = debug_dir
        self.step_count = 0

    def __call__(self, step, *args, **kwargs) -> None:
        self.step_count += 1
        try:
            code = getattr(step, "tool_calls", None) or getattr(step, "code", None) or ""
            output = getattr(step, "observations", None) or getattr(step, "output", None) or ""
            thought = getattr(step, "model_output", None) or ""
            if code:
                code_str = code if isinstance(code, str) else json.dumps(code, default=str)
                out_str = output if isinstance(output, str) else json.dumps(output, default=str)
                out_block = "\n".join(f"# {line}" for line in out_str.splitlines())
                debug_file = self.debug_dir / f"iter_{self.step_count:02d}.py"
                debug_file.write_text(
                    f"# thought: {str(thought)[:200]}\n\n{code_str}\n\n# --- output ---\n{out_block}\n"
                )
        except Exception:
            pass  # never let debug machinery break the agent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_toksearch(
    prompt: str,
    max_iterations: int = 10,
    verbose: bool = True,
    debug: bool = False,
    backend: str = "amsc",
    **model_kwargs,
):
    """Take a natural language prompt, use an LLM to generate and iteratively
    execute toksearch pipeline code, and return the result.

    Parameters
    ----------
    prompt:
        Natural language description of the data you want.
    max_iterations:
        Maximum number of code-execution rounds before giving up.
    verbose:
        Print a one-line summary per iteration (default True).
    debug:
        Print full detail per iteration and write ``iter_NN.py`` files to a
        timestamped directory in the current working directory (implies verbose).
    backend:
        Model backend — ``"amsc"`` (default), ``"openai"``, ``"anthropic"``,
        or ``"transformers"``.
    **model_kwargs:
        Forwarded to :func:`create_model` (e.g. ``api_base``, ``model_id``).
    """
    from smolagents import CodeAgent

    if debug:
        verbose = True
        debug_dir = Path(f"toksearch_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        debug_dir.mkdir(parents=True, exist_ok=True)
        print(f"[debug] writing iteration files to {debug_dir}/")

    verbosity_level = 2 if debug else (1 if verbose else 0)

    model = create_model(backend=backend, **model_kwargs)

    if verbose:
        print(f"[toksearch] verifying connection to backend={backend!r}...")
    _verify_model_connection(model, backend)
    if verbose:
        print("[toksearch] connection ok")

    step_callbacks = [_DebugCallback(debug_dir)] if debug else []

    agent = CodeAgent(
        tools=[],
        model=model,
        max_steps=max_iterations,
        verbosity_level=verbosity_level,
        additional_authorized_imports=AUTHORIZED_IMPORTS,
        system_prompt=_make_system_prompt(),
        step_callbacks=step_callbacks,
    )
    _setup_namespace(agent)

    return agent.run(prompt)


if __name__ == "__main__":
    _debug = "--debug" in sys.argv
    _prompt = input("Query: ").strip()
    _result = query_toksearch(_prompt, debug=_debug)
    print(_result)
