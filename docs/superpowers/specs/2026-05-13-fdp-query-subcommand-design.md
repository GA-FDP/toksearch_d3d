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
- No stdin support. Single quoted positional arg only.
- No output-format switches (JSON, plain). `query_toksearch` returns
  heterogeneous values (str or namespace objects); structured output is a
  separate feature if needed later.
- No changes to `query_toksearch` itself. The CLI is a pure wrapper.

## Architecture

A small addition to the existing `fdp` CLI dispatch in
`toksearch_d3d/fdp/cli.py`. No new module.

```
toksearch_d3d/fdp/
    cli.py           # add do_query + subparser wiring
    environment.py   # unchanged
    skills.py        # unchanged
    __init__.py      # unchanged
```

### CLI surface

```
fdp query "<prompt>" [--max-iterations N] [--quiet] [--api-key-file PATH]
```

| Flag | Maps to | Default |
|---|---|---|
| (positional) `query` | `query_toksearch(prompt=...)` | required |
| `--max-iterations N` / `-n N` | `max_iterations=` | 10 |
| `--quiet` / `-q` | `verbose=not quiet` | `verbose=True` |
| `--api-key-file PATH` | `api_key_file=Path(PATH)` | `None` (function falls back to `~/amsc_api_key`) |
| top-level `fdp --debug` | `debug=` | `False` |

The existing top-level `--debug` flag is reused rather than adding a
query-specific one. This matches how `do_run` already uses it.

## Critical: Import Ordering

`query_toksearch` lives in `toksearch_d3d.agents.claude_toksearch_agent`, which
imports `toksearch` and `toksearch_d3d` at module top. `toksearch` transitively
pulls in `libfdpio` and XRootD, and those C libraries **consume env vars at
library load time** (`XRD_PLUGINCONFDIR`, `PTDATA_LIBRARY`,
`PTDATA_PLUGIN_LIB`, `default_tree_path`, etc.). If they load before
`setup_environment()` writes those vars into `os.environ`, FDP access from the
agent will silently misbehave.

The current `main()` in `cli.py` already calls `setup_environment()` between
argparse parsing and subcommand dispatch:

```python
args = parser.parse_args()
setup_environment(bearer_token=args.bearer_token or None)
args.func(args)
```

So the rule for `do_query` is: **the import of `query_toksearch` must happen
inside the handler function, never at the top of `cli.py`.** A comment at the
import site will state this explicitly so a future refactor does not innocently
hoist it.

## `do_query` Specification

```python
def do_query(args):
    # Lazy import: this transitively imports toksearch, which pulls in
    # libfdpio + xrootd. Those C libraries read env vars
    # (XRD_PLUGINCONFDIR, PTDATA_*, default_tree_path) at library load
    # time, so the import MUST happen after setup_environment() — never
    # at the top of this module.
    from toksearch_d3d.agents.claude_toksearch_agent import query_toksearch

    api_key_file = Path(args.api_key_file) if args.api_key_file else None
    result = query_toksearch(
        args.query,
        max_iterations=args.max_iterations,
        verbose=not args.quiet,
        debug=args.debug,
        api_key_file=api_key_file,
    )
    print(result)
```

## Subparser Wiring

Inside `main()`, after the existing `skills_parser` block and before
`args = parser.parse_args()`:

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

A new `tests/test_fdp_query.py` exercises the CLI wiring without hitting the
real LLM. The test monkeypatches
`toksearch_d3d.agents.claude_toksearch_agent.query_toksearch` to a recorder,
invokes `toksearch_d3d.fdp.cli.main()` with `sys.argv` patched, and asserts
that the recorded call captured the expected positional and keyword args.

Cases covered:

1. **Defaults.** `fdp query "hello"` → `query_toksearch("hello",
   max_iterations=10, verbose=True, debug=False, api_key_file=None)`.
2. **All flags.** `fdp query "hi" -n 3 --quiet --api-key-file /tmp/key` plus
   top-level `--debug` → `verbose=False, debug=True, max_iterations=3,
   api_key_file=Path('/tmp/key')`.
3. **Result printing.** Capture stdout; confirm the recorder's return value is
   printed (e.g. set the recorder to return `"ANSWER"` and grep stdout).

The test does **not** import `claude_toksearch_agent` at module top — the
monkeypatch is installed against the dotted path so the lazy import inside
`do_query` picks it up. This preserves the same ordering safety the production
code relies on.

Manual smoke (run from `toksearch_d3d/` inside the pixi env, BEARER_TOKEN and
AmSC key in place):

```
pixi run fdp query "fetch ip for shot 165920 and report its peak value in MA"
```

Expected: per-iteration progress lines, then a final printed result.

## Risks & Rollback

- **Forgotten lazy-import discipline.** The most likely regression is a future
  edit hoisting the agent import to the top of `cli.py`. Mitigation: explicit
  comment at the import site, plus this design doc.
- **Agent module import cost.** `claude_toksearch_agent` runs
  `pydoc.Helper(...)` over `toksearch` and `toksearch_d3d` at module-import
  time to build its system prompt. That's already slow today; the lazy import
  keeps that cost off the critical path for `fdp env` / `fdp ls`. The cost
  hits only on `fdp query`, which is acceptable.
- **AmSC API key missing.** `query_toksearch` reads the key file unconditionally
  and raises if missing. The user sees a Python traceback rather than a clean
  error. Out of scope for this change — owned by `query_toksearch` itself.
- **Rollback:** purely additive; revert is a single git revert.
