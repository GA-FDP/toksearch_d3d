# `fdp query` Subcommand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `fdp query "<prompt>"` subcommand that runs `query_toksearch` from the Claude agent module against a natural-language prompt with the FDP environment configured, and prints the result.

**Architecture:** A new `do_query` handler in `toksearch_d3d/fdp/cli.py` plus a subparser in `main()`. The handler imports `query_toksearch` **lazily inside the function** so that `toksearch` (and its transitive libfdpio/XRootD load-time env-var consumers) are not imported until after `setup_environment()` has run. Tests monkeypatch `query_toksearch` to avoid hitting the real LLM.

**Tech Stack:** Python 3.11, `argparse`, `unittest`, `unittest.mock`, pixi-managed env.

**Reference spec:** `docs/superpowers/specs/2026-05-13-fdp-query-subcommand-design.md`

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `toksearch_d3d/fdp/cli.py` | Modify | Add `do_query` handler and subparser wiring in `main()`. |
| `tests/test_fdp_query.py` | Create | Unit tests that monkeypatch `query_toksearch` and assert the CLI forwards args correctly and prints the result. |

No new modules. No changes to `claude_toksearch_agent.py`.

---

## Task 1: Add tests for `fdp query` CLI wiring

**Files:**
- Create: `tests/test_fdp_query.py`

This task establishes the test surface before any implementation exists. All
tests will fail at the end of this task — that is the desired state. Task 2
makes them pass.

The tests monkeypatch
`toksearch_d3d.agents.claude_toksearch_agent.query_toksearch` rather than
importing it directly. This is critical: importing the agent module pulls in
`toksearch` (and libfdpio/XRootD), which is exactly the load-order hazard the
design avoids. The dotted-path patch goes in via `mock.patch` and the
production lazy import picks up the mocked attribute.

- [ ] **Step 1: Create `tests/test_fdp_query.py`**

Create the file with this exact content:

```python
# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for the `fdp query` CLI subcommand.

These tests monkeypatch `query_toksearch` on its source module so that the
production lazy import inside `do_query` picks up the mock. This avoids
importing the real agent module (which transitively imports toksearch +
libfdpio + XRootD) at test-collection time -- the same load-order rule the
production code follows.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


class TestFdpQuery(unittest.TestCase):
    def _run_cli(self, argv):
        """Invoke `toksearch_d3d.fdp.cli.main` with patched sys.argv and a
        no-op setup_environment (we don't want the test to touch os.environ).
        Returns captured stdout.
        """
        from toksearch_d3d.fdp import cli
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(cli, "setup_environment"), \
                redirect_stdout(buf):
            cli.main()
        return buf.getvalue()

    def test_defaults(self):
        """`fdp query "hello"` forwards defaults: max_iterations=10,
        verbose=True, debug=False, api_key_file=None."""
        recorder = mock.MagicMock(return_value="ANSWER")
        with mock.patch(
            "toksearch_d3d.agents.claude_toksearch_agent.query_toksearch",
            recorder,
        ):
            self._run_cli(["fdp", "query", "hello"])
        recorder.assert_called_once_with(
            "hello",
            max_iterations=10,
            verbose=True,
            debug=False,
            api_key_file=None,
        )

    def test_all_flags(self):
        """All flags wire through correctly: -n, --quiet, --api-key-file, and
        top-level --debug."""
        recorder = mock.MagicMock(return_value="ANSWER")
        with mock.patch(
            "toksearch_d3d.agents.claude_toksearch_agent.query_toksearch",
            recorder,
        ):
            self._run_cli([
                "fdp", "--debug",
                "query", "hi",
                "-n", "3",
                "--quiet",
                "--api-key-file", "/tmp/key",
            ])
        recorder.assert_called_once_with(
            "hi",
            max_iterations=3,
            verbose=False,
            debug=True,
            api_key_file=Path("/tmp/key"),
        )

    def test_result_is_printed(self):
        """Whatever `query_toksearch` returns is printed to stdout."""
        recorder = mock.MagicMock(return_value="THE ANSWER")
        with mock.patch(
            "toksearch_d3d.agents.claude_toksearch_agent.query_toksearch",
            recorder,
        ):
            out = self._run_cli(["fdp", "query", "anything"])
        self.assertIn("THE ANSWER", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run from the repo root:

```bash
pixi run bash -c 'cd tests && python -m unittest test_fdp_query -v'
```

Expected: all three tests fail. The exact failure mode depends on the current
state of `cli.py`, but it will be one of:
- `SystemExit: 2` from argparse rejecting the unknown `query` subcommand, or
- `AttributeError` if a name doesn't resolve.

If the tests fail for any other reason (import errors in unrelated modules,
etc.), fix that first before proceeding.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_fdp_query.py
git commit -m "Add failing tests for fdp query subcommand"
```

---

## Task 2: Implement `do_query` and wire the subparser

**Files:**
- Modify: `toksearch_d3d/fdp/cli.py`

This task adds the handler and subparser. No other files change.

- [ ] **Step 1: Add the `do_query` handler**

Open `toksearch_d3d/fdp/cli.py`. After the existing `do_ls` function (around
line 245) and before the `# MAIN` banner block, add this function:

```python
def do_query(args):
    # Lazy import: this transitively imports toksearch, which pulls in
    # libfdpio + xrootd. Those C libraries read env vars
    # (XRD_PLUGINCONFDIR, PTDATA_*, default_tree_path) at library load
    # time, so the import MUST happen after setup_environment() has run --
    # never at the top of this module.
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

`Path` is already imported at the top of `cli.py` (line 1). No new imports.

- [ ] **Step 2: Add the subparser wiring in `main()`**

In `toksearch_d3d/fdp/cli.py`, find the `main()` function and locate the
`skills_parser.set_defaults(func=do_skills)` line (around line 305). Add the
following block immediately after it, before `args = parser.parse_args()`:

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

- [ ] **Step 3: Run the tests and verify they pass**

```bash
pixi run bash -c 'cd tests && python -m unittest test_fdp_query -v'
```

Expected: all three tests pass.

- [ ] **Step 4: Run the existing test suite to confirm no regressions**

```bash
pixi run bash -c 'cd tests && python testit.py --mock'
```

Expected: same pass/fail tally as before this change (i.e. the existing
`test_fdp_environment`, `test_imas_signal`, etc. tests still pass; the new
`test_fdp_query` tests pass). `--mock` skips heavy integration tests so this
is fast.

- [ ] **Step 5: Confirm `fdp --help` shows the new subcommand**

```bash
pixi run fdp --help
```

Expected: the subcommand list includes `query` alongside `run`, `env`, `ls`,
`skills`. Then:

```bash
pixi run fdp query --help
```

Expected: usage line shows `fdp query [-h] [--max-iterations MAX_ITERATIONS]
[--quiet] [--api-key-file API_KEY_FILE] query` and the four arg help strings
appear.

- [ ] **Step 6: Confirm `fdp env` / `fdp ls` startup is not slowed down**

The lazy import is what keeps these fast. Sanity-check with:

```bash
time pixi run fdp env > /dev/null
```

Expected: subsecond. If this regresses noticeably (multi-second), check that
`do_query`'s import of `query_toksearch` is inside the function body, not at
the top of `cli.py`.

- [ ] **Step 7: Commit the implementation**

```bash
git add toksearch_d3d/fdp/cli.py
git commit -m "Add fdp query subcommand wrapping query_toksearch

The handler lazy-imports query_toksearch from the Claude agent
module so that toksearch (and its transitive libfdpio/XRootD
load-time env-var consumers) are not imported until after
setup_environment() has run in main()."
```

---

## Task 3: Manual smoke test (operator-run, not automated)

**Files:** none modified.

This step is for the engineer running the plan — it cannot be CI-automated
because it requires a live BEARER_TOKEN and an AmSC API key. Skip it if
either is missing; the unit tests in Task 1+2 cover the CLI wiring.

- [ ] **Step 1: Verify the agent path end-to-end**

With `BEARER_TOKEN` set (or `~/.fdp/token` present) and `~/amsc_api_key`
populated, run from the repo root:

```bash
pixi run fdp query "Fetch the ip signal for shot 165920 and print its peak value in MA."
```

Expected: per-iteration progress lines like
`[iter 1] run_python: ... → ✓`, followed by either a printed numeric result
or a `result` variable repr. The exact answer is not asserted — we are
confirming that:

1. The CLI dispatches to `do_query`.
2. `setup_environment` runs before the agent module imports `toksearch`
   (no XRootD "Error opening network link" errors).
3. The agent can talk to the AmSC LLM and execute pipeline code against
   the FDP.

- [ ] **Step 2: Verify `--quiet` suppresses progress**

```bash
pixi run fdp query --quiet "What is 2+2 in Python?"
```

Expected: no `[iter N]` progress lines, just the final printed result.

- [ ] **Step 3: Verify `--max-iterations 1` short-circuits a long query**

```bash
pixi run fdp query -n 1 "Plot beta_normal vs nbi power for shots 200000-200010."
```

Expected: a `[warning] reached max iterations (1)` line and a fallback
result. This confirms the flag is being respected.

If any of these steps fail, do NOT mark Task 3 complete — investigate
whether the failure is in `do_query` (regression) or in `query_toksearch`
itself (out of scope for this plan; file a separate issue).

---

## Self-Review Notes

Coverage against spec:
- ✓ Positional `query` arg → tested in `test_defaults`, exercised in smoke.
- ✓ `--max-iterations` / `-n` → tested in `test_all_flags`, exercised in smoke step 3.
- ✓ `--quiet` / `-q` → tested in `test_all_flags`, exercised in smoke step 2.
- ✓ `--api-key-file` → tested in `test_all_flags` (Path wrapping verified).
- ✓ Top-level `--debug` reuse → tested in `test_all_flags`.
- ✓ Lazy-import discipline → enforced by inline comment + by the test strategy that monkeypatches the source module without importing it.
- ✓ Result printing → tested in `test_result_is_printed`.
- ✓ No changes to `claude_toksearch_agent.py` → no task touches it.
