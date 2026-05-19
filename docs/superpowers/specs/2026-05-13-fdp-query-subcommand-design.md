# `fdp query` Subcommand — Design

**Date:** 2026-05-13
**Status:** Approved, ready for plan

## Problem

`toksearch_d3d.agents.claude_toksearch_agent.query_toksearch` lets a user pose a
natural-language question and have an LLM iteratively generate and execute
TokSearch pipeline code to answer it. Today the only way to invoke it is to run
its module directly (`python -m ... claude_toksearch_agent`) and type the
prompt at an `input()` prompt, or to import and call the function manually.

Users in an FDP-enabled shell already reach for `fdp <subcommand>` for
environment-aware tasks. The query agent belongs in that surface — it needs the
exact same FDP environment (Pelican, MDSplus paths, PTData config, bearer
token) that `fdp run` provides, and it would be natural to invoke as:

```
fdp query "what was the maximum Ip on shot 165920?"
```

## Goal

Add an `fdp query` subcommand that takes a quoted natural-language prompt as a
single positional argument, runs `query_toksearch` against it with the FDP
environment configured, and prints the result.

## Non-Goals

- No interactive REPL mode. The existing `__main__` block in
  `claude_toksearch_agent.py` already covers that use case and stays.
- No stdin support for the prompt (stdin is reserved for the JSON payload
  passed to the agent subprocess — see "Architecture" below). Single quoted
  positional arg only.
- No output-format switches (JSON, plain). `query_toksearch` returns
  heterogeneous values (str or namespace objects); structured output is a
  separate feature if needed later.
- No changes to `query_toksearch` itself. The CLI is a pure wrapper.

## Architecture

A small addition to the existing `fdp` CLI dispatch in
`toksearch_d3d/fdp/cli.py`. No new module.

```
toksearch_d3d/fdp/
    cli.py           # add do_query + runner script + subparser wiring
    environment.py   # unchanged
    skills.py        # unchanged
    __init__.py      # unchanged
```

### CLI surface

```
fdp query "<prompt>" [--max-iterations N] [--quiet] [--api-key-file PATH]
```

| Flag | Effect | Default |
|---|---|---|
| (positional) `query` | natural-language prompt | required |
| `--max-iterations N` / `-n N` | agent tool-call rounds cap | 10 |
| `--quiet` / `-q` | set `verbose=False` in the agent | `verbose=True` |
| `--api-key-file PATH` | AmSC API key path | `None` → agent falls back to `~/amsc_api_key` |
| top-level `fdp --debug` | passes `debug=True` to the agent | `False` |

The existing top-level `--debug` flag is reused rather than adding a
query-specific one. This matches how `do_run` already uses it.

## Critical: Subprocess Execution Model

`do_query` MUST run the agent in a fresh Python subprocess that inherits
`os.environ` from the parent. **In-process execution does not work.**

Why: `query_toksearch` (and the rest of the agent module) imports `toksearch`,
which transitively loads `libfdpio2` and `libXrdCl` C libraries plus
`MDSplus`. Several env vars these libraries consume — most importantly
`XRD_PLUGINCONFDIR` (for the Pelican plugin), `default_tree_path` (for
MDSplus tree resolution), `BEARER_TOKEN`, and the `PTDATA_*` vars — are
honored only when present in the **initial process env block**. Setting them
via Python's `os.environ` after process startup is not sufficient for some
code paths (specifically, MDSplus tree opens via the Pelican-backed
`default_tree_path` fail with `TreeFOPENR` even though `os.environ` shows the
var is set).

`fdp run` works because it spawns the user command via `subprocess.run` with
`env=os.environ`, so the child Python starts with the FDP vars already in
its env block. `do_query` adopts the same pattern: invoke `python -c <runner
script>` via `subprocess.run(env=os.environ)` and pipe the agent kwargs in
as a JSON payload over stdin.

The current `main()` in `cli.py`:

```python
args = parser.parse_args()
setup_environment(bearer_token=args.bearer_token or None)
args.func(args)
```

guarantees `setup_environment()` runs before `do_query`, so `os.environ` is
populated by the time the subprocess is spawned.

## `do_query` Specification

```python
QUERY_RUNNER_SCRIPT = """
import json
import sys
from pathlib import Path
from toksearch_d3d.agents.claude_toksearch_agent import query_toksearch

kw = json.loads(sys.stdin.read())
api_key_file = Path(kw["api_key_file"]) if kw["api_key_file"] else None
result = query_toksearch(
    kw["prompt"],
    max_iterations=kw["max_iterations"],
    verbose=kw["verbose"],
    debug=kw["debug"],
    api_key_file=api_key_file,
)
print(result)
"""


def do_query(args):
    import json
    payload = json.dumps({
        "prompt": args.query,
        "max_iterations": args.max_iterations,
        "verbose": not args.quiet,
        "debug": args.debug,
        "api_key_file": args.api_key_file,
    })
    result = subprocess.run(
        [sys.executable, "-c", QUERY_RUNNER_SCRIPT],
        env=os.environ,
        input=payload,
        text=True,
    )
    sys.exit(result.returncode)
```

`subprocess`, `sys`, and `os` are already imported at the top of `cli.py`.

## Subparser Wiring

Inside `main()`, after the existing `skills_parser.set_defaults(func=do_skills)`
line and before `args = parser.parse_args()`:

```python
query_parser = subparsers.add_parser(
    "query",
    help="Run a natural-language query against TokSearch via the agent",
)
query_parser.add_argument(
    "query",
    type=str,
    help="Natural-language query (quote it on the shell)",
)
query_parser.add_argument(
    "--max-iterations", "-n", type=int, default=10,
    help="Maximum agent tool-call rounds (default: 10)",
)
query_parser.add_argument(
    "--quiet", "-q", action="store_true",
    help="Suppress per-iteration progress output",
)
query_parser.add_argument(
    "--api-key-file", type=str, default=None,
    help="Path to AmSC API key file (default: ~/amsc_api_key)",
)
query_parser.set_defaults(func=do_query)
```

## Testing Plan

A new `tests/test_fdp_query.py` exercises the CLI wiring without spawning a
real subprocess or hitting the LLM. The tests mock `subprocess.run` on the
`cli` module, invoke `cli.main()` with patched `sys.argv` (and a no-op
`setup_environment`), and assert that the mock was called with the expected
command, environment, and JSON stdin payload.

Cases covered:

1. **Defaults.** `fdp query "hello"` → stdin payload has
   `max_iterations=10, verbose=True, debug=False, api_key_file=None`.
2. **All flags.** `fdp query "hi" -n 3 --quiet --api-key-file /tmp/key` plus
   top-level `--debug` → `max_iterations=3, verbose=False, debug=True,
   api_key_file="/tmp/key"`.
3. **Command shape.** The first arg to `subprocess.run` is
   `[sys.executable, "-c", QUERY_RUNNER_SCRIPT]`.
4. **Env passthrough.** The subprocess `env` kwarg is `os.environ` itself.
5. **Exit code propagation.** `sys.exit(<returncode>)` is called with the
   subprocess's returncode.

Manual smoke (run from `toksearch_d3d/` inside the pixi env, BEARER_TOKEN and
AmSC key in place):

```
pixi run fdp query "fetch ip for shot 165920 and report its peak value in MA"
```

Plus a MdsSignal-via-Pelican smoke (the case that motivated the subprocess
architecture):

```
pixi run fdp query "Use MdsSignal to fetch \ipmhd from efit01 for shot 165920 with NO location argument."
```

Both should succeed end-to-end. The MdsSignal smoke is the key regression
test for the subprocess design — if it ever fails, suspect that `do_query`
was rewritten to run in-process.

## Risks & Rollback

- **AmSC API key missing.** The runner script will raise inside the
  subprocess; the user sees a traceback and `do_query` exits non-zero. Out
  of scope for this change — owned by `query_toksearch` itself.
- **Process startup cost.** Each `fdp query` invocation spawns a fresh
  Python that re-imports `toksearch`, `toksearch_d3d`, `anthropic`,
  `matplotlib`, etc. That's slow (several seconds) but acceptable for an
  interactive query CLI. Not a regression — `fdp run python script.py` pays
  the same cost.
- **Rollback:** purely additive; revert is a single git revert.
