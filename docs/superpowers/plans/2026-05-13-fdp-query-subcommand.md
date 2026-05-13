# `fdp query` Subcommand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `fdp query "<prompt>"` subcommand that runs `query_toksearch` from the Claude agent module against a natural-language prompt with the FDP environment configured, and prints the result.

**Architecture:** A new `do_query` handler in `toksearch_d3d/fdp/cli.py` plus a subparser in `main()`. The handler runs the agent in a **fresh Python subprocess** that inherits `os.environ` from the parent (which `setup_environment()` has populated). The subprocess approach is load-bearing: libfdpio/XRootD/MDSplus C libraries read env vars at process-startup time, and `MdsSignal` tree opens via the Pelican-backed `default_tree_path` only work when those vars are in the child's initial env block. The agent's kwargs are passed as a JSON payload over stdin. Tests mock `subprocess.run` to avoid spawning a real child or hitting the LLM.

**Tech Stack:** Python 3.11, `argparse`, `subprocess`, `unittest`, `unittest.mock`, pixi-managed env.

**Reference spec:** `docs/superpowers/specs/2026-05-13-fdp-query-subcommand-design.md`

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `toksearch_d3d/fdp/cli.py` | Modify | Add `do_query`, `QUERY_RUNNER_SCRIPT`, and subparser wiring in `main()`. |
| `tests/test_fdp_query.py` | Create | Unit tests that mock `subprocess.run` and assert the CLI builds the right command, env, and JSON stdin payload. |

No new modules. No changes to `claude_toksearch_agent.py`.

---

## Task 1: Add tests for `fdp query` CLI wiring

**Files:**
- Create: `tests/test_fdp_query.py`

This task establishes the test surface before any implementation exists. All
tests will fail at the end of this task — that is the desired state. Task 2
makes them pass.

The tests mock `subprocess.run` on the `cli` module so the test never spawns a
real subprocess. Each test asserts something specific about how `do_query`
builds the command and payload from CLI arguments.

- [ ] **Step 1: Create `tests/test_fdp_query.py`**

Create the file with this exact content:

```python
# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for the `fdp query` CLI subcommand.

`do_query` runs the agent in a fresh Python subprocess so the child inherits
the FDP-prepared os.environ at startup (required for libXrdCl + MDSplus tree
opens via the Pelican-backed default_tree_path). These tests mock
`subprocess.run` to assert that the right command, environment, and stdin
payload are built from the CLI arguments -- they do not actually spawn a
subprocess or invoke the LLM.

`setup_environment` is patched on `cli` (not on `.environment`) because
`cli.py` does `from .environment import setup_environment`, binding the name
into the `cli` module namespace; that is the binding `main()` calls.
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock


class TestFdpQuery(unittest.TestCase):
    def _run_cli(self, argv, subprocess_returncode=0):
        """Invoke `toksearch_d3d.fdp.cli.main` with patched sys.argv, a
        no-op setup_environment, and a mocked subprocess.run.

        Returns (subprocess_run_mock, captured_stdout, sys_exit_code).
        """
        from toksearch_d3d.fdp import cli
        buf = io.StringIO()
        fake_proc = mock.MagicMock()
        fake_proc.returncode = subprocess_returncode
        exit_code = None
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(cli, "setup_environment"), \
                mock.patch.object(cli.subprocess, "run", return_value=fake_proc) as run_mock, \
                redirect_stdout(buf):
            try:
                cli.main()
            except SystemExit as e:
                exit_code = e.code
        return run_mock, buf.getvalue(), exit_code

    def _payload_from_call(self, run_mock):
        """Pull the JSON stdin payload out of the mocked subprocess.run call."""
        self.assertEqual(run_mock.call_count, 1)
        _args, kwargs = run_mock.call_args
        self.assertIn("input", kwargs)
        return json.loads(kwargs["input"])

    def test_defaults(self):
        """`fdp query "hello"` builds a payload with default kwargs."""
        run_mock, _, _ = self._run_cli(["fdp", "query", "hello"])
        payload = self._payload_from_call(run_mock)
        self.assertEqual(payload, {
            "prompt": "hello",
            "max_iterations": 10,
            "verbose": True,
            "debug": False,
            "api_key_file": None,
        })

    def test_all_flags(self):
        """All flags wire through: -n, --quiet, --api-key-file, top-level --debug."""
        run_mock, _, _ = self._run_cli([
            "fdp", "--debug",
            "query", "hi",
            "-n", "3",
            "--quiet",
            "--api-key-file", "/tmp/key",
        ])
        payload = self._payload_from_call(run_mock)
        self.assertEqual(payload, {
            "prompt": "hi",
            "max_iterations": 3,
            "verbose": False,
            "debug": True,
            "api_key_file": "/tmp/key",
        })

    def test_subprocess_command_shape(self):
        """The subprocess command is [sys.executable, '-c', runner_script]."""
        from toksearch_d3d.fdp import cli
        run_mock, _, _ = self._run_cli(["fdp", "query", "anything"])
        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1], "-c")
        self.assertEqual(cmd[2], cli.QUERY_RUNNER_SCRIPT)

    def test_subprocess_env_is_os_environ(self):
        """The subprocess inherits os.environ (populated by setup_environment)."""
        import os
        run_mock, _, _ = self._run_cli(["fdp", "query", "anything"])
        self.assertIs(run_mock.call_args.kwargs["env"], os.environ)

    def test_exit_code_propagates(self):
        """sys.exit is called with the subprocess's returncode."""
        _, _, exit_code = self._run_cli(["fdp", "query", "anything"],
                                        subprocess_returncode=7)
        self.assertEqual(exit_code, 7)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests and verify they fail**

```bash
pixi run bash -c 'cd tests && python -m unittest test_fdp_query -v'
```

Expected: all five tests fail. `cli.QUERY_RUNNER_SCRIPT` doesn't exist yet and
the `query` subparser isn't registered, so the most likely failure is
`SystemExit: 2` from argparse rejecting the unknown subcommand, or
`AttributeError: module 'toksearch_d3d.fdp.cli' has no attribute 'QUERY_RUNNER_SCRIPT'`.

If the tests fail for unrelated reasons (import errors elsewhere), fix that
first before proceeding.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_fdp_query.py
git commit -m "Add failing tests for fdp query subcommand"
```

---

## Task 2: Implement `do_query` and wire the subparser

**Files:**
- Modify: `toksearch_d3d/fdp/cli.py`

This task adds the runner script, handler, and subparser. No other files change.

- [ ] **Step 1: Add the runner script + `do_query` handler**

Open `toksearch_d3d/fdp/cli.py`. After the existing `do_ls` function (around
line 245) and before the `# MAIN` banner block, add:

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
    # Run the agent in a fresh Python subprocess that inherits the FDP
    # environment from os.environ. The subprocess approach is load-bearing:
    # several C libraries pulled in by `import toksearch` (libfdpio2 +
    # libXrdCl) read env vars (XRD_PLUGINCONFDIR, default_tree_path,
    # PTDATA_*, BEARER_TOKEN) at library load time, and reliable access
    # via libXrdCl's Pelican plugin requires those vars to be in the
    # initial process env block -- mutating os.environ from inside a
    # running process is not sufficient for some code paths (notably
    # MdsSignal tree opens via the default Pelican-backed tree path).
    # `setup_environment()` has populated os.environ in main() before
    # dispatch, so spawning a fresh Python here makes the child inherit
    # those vars at startup.
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

- [ ] **Step 2: Add the subparser wiring in `main()`**

In `toksearch_d3d/fdp/cli.py`, find the `main()` function and locate the
`skills_parser.set_defaults(func=do_skills)` line. Add the following block
immediately after it, before `args = parser.parse_args()`:

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

Expected: all five tests pass.

- [ ] **Step 4: Confirm `fdp --help` shows the new subcommand**

```bash
pixi run fdp --help
pixi run fdp query --help
```

The first should list `query` alongside `run`, `env`, `ls`, `skills`. The
second should show the four flag definitions.

- [ ] **Step 5: Commit the implementation**

```bash
git add toksearch_d3d/fdp/cli.py
git commit -m "Add fdp query subcommand wrapping query_toksearch

do_query spawns a fresh Python subprocess that runs the agent
with os.environ inherited from the parent (where setup_environment
populated it). Subprocess execution is load-bearing: MDSplus tree
opens via the Pelican-backed default_tree_path only work when
XRD_PLUGINCONFDIR etc. are in the initial process env block."
```

---

## Task 3: Manual smoke tests (operator-run, not automated)

**Files:** none modified.

These steps require a live `BEARER_TOKEN` (or `~/.fdp/token`) and a populated
`~/amsc_api_key`. Skip if either is missing; the unit tests cover the wiring.

- [ ] **Step 1: Verify the PtData-via-Pelican agent path end-to-end**

```bash
pixi run fdp query "Fetch the ip signal for shot 165920 and print its peak value in MA."
```

Expected: per-iteration progress lines (`[iter N] run_python: ... → ✓`), then
a printed result containing a peak value around 1.15 MA. Confirms basic
agent + Pelican data access.

- [ ] **Step 2: Verify `--quiet` suppresses progress**

```bash
pixi run fdp query --quiet "What is 2+2 in Python?"
```

Expected: no `[iter N]` progress lines, just the answer.

- [ ] **Step 3: Verify `--max-iterations 1` short-circuits**

```bash
pixi run fdp query -n 1 "Plot beta_normal vs nbi power for shots 200000-200010."
```

Expected: a `[warning] reached max iterations (1)` line followed by a
fallback message. Confirms the flag is being respected.

- [ ] **Step 4: Verify MdsSignal-via-Pelican (no atlas) works**

This step is the regression test for the subprocess architecture. It must
succeed; if it ever starts failing, suspect a refactor that moved `do_query`
back to in-process execution.

```bash
pixi run fdp query "Use toksearch's MdsSignal (NOT PtDataSignal) to fetch \ipmhd from the efit01 tree for shot 165920. Do NOT pass a location argument and do NOT use atlas -- the FDP environment is configured for Pelican-backed MDSplus. Run: MdsSignal(r'\ipmhd', 'efit01').fetch(165920) and print the peak |ipmhd|."
```

Expected: the agent calls `MdsSignal(r'\ipmhd', 'efit01').fetch(165920)`
without specifying any `location` argument, succeeds (✓), and reports a peak
value around 1.13e6 A (~1.13 MA). The same call run in-process (without the
subprocess wrapper) fails with `TreeFOPENR`, so a success here is the
behavioral guarantee that the architecture is doing its job.

If any step fails, investigate whether the failure is in `do_query`
(regression) or in `query_toksearch` itself (out of scope; file a separate
issue).

---

## Self-Review Notes

Coverage against spec:
- ✓ Positional `query` arg → tested in `test_defaults`, exercised in smoke step 1.
- ✓ `--max-iterations` / `-n` → tested in `test_all_flags`, exercised in smoke step 3.
- ✓ `--quiet` / `-q` → tested in `test_all_flags`, exercised in smoke step 2.
- ✓ `--api-key-file` → tested in `test_all_flags` (string payload value).
- ✓ Top-level `--debug` reuse → tested in `test_all_flags`.
- ✓ Subprocess execution model → tested in `test_subprocess_command_shape`,
  `test_subprocess_env_is_os_environ`, `test_exit_code_propagates`; exercised
  end-to-end by smoke step 4 (which only works in a subprocess).
- ✓ No changes to `claude_toksearch_agent.py` → no task touches it.
