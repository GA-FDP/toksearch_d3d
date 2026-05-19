# `toksearch_d3d` PR 4 — Plug `toksearch_d3d` into `toksearch.llm`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Wire `toksearch_d3d` into the new `toksearch.llm` library so `fdp query` and `fdp chat` actually drive the new code (instead of the legacy `toksearch_d3d/agents/claude_toksearch_agent.py`). Declare the three entry-point contributions (namespace, skills, `amsc` preset) so a Session in any environment with `toksearch_d3d` installed auto-discovers it.

**Architecture:** New `toksearch_d3d/llm/` subpackage exposes a `skills_path` `Path` constant and an `AMSC_PRESET` `Preset` instance, both registered via Python entry points. `toksearch_d3d` itself becomes a namespace contributor with `__llm_description__` for the system-prompt catalog. The `fdp.cli` agent module (`do_query`, `QUERY_RUNNER_SCRIPT`) is replaced by thin shims that `setup_environment()` and then `os.execvpe` into `python -m toksearch.llm.cli {chat,query} ...` — preserving the env-block ordering libfdpio/XRootD requires, without the JSON-stdin pipe that was needed for the legacy agent. The legacy `toksearch_d3d/agents/` package is deleted.

**Tech Stack:** Python 3.11, `unittest`, `unittest.mock`, pixi-managed env, conda-forge.

**Reference spec:** `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch/docs/superpowers/specs/2026-05-18-toksearch-llm-design.md` (the migration plan section).

**Branch:** `feat/llm-pr4` off `main` in `toksearch_d3d` (already created).

**Precondition:** `toksearch` must be at a version that includes PR 30 (entry-point discovery). The plan pins `toksearch>=2.7`; adjust to whatever the next stable tag turns out to be. If no `release-2.7.0` tag exists yet when this PR ships, the pin can stay at `>=2.6.0` for the in-tree pixi dev env and be tightened in a follow-up.

## Scope notes — what's deferred

- The default `--backend` for `fdp` shims is **`amsc`** to preserve existing user behavior (`~/amsc_api_key` continues to "just work").
- Legacy `fdp query` flags `--quiet` / `--api-key-file` / `--debug` are DROPPED in PR 4. The corresponding work-alikes:
  - `--quiet` had no equivalent; the new CLI's output is the only mode.
  - `--api-key-file` is replaced by the `amsc` preset's `api_key_file = "~/amsc_api_key"` (set automatically).
  - `--debug` had no equivalent in PR 1; deferred to a follow-up if anyone needs it.
- The deprecation shim that re-exports `query_toksearch` for any external script using the old module path is INTENTIONALLY OMITTED. The legacy `toksearch_d3d.agents` package is just deleted. A 1-release-cycle shim is the PR 5 of the migration; we collapse it here on the assumption that no external code uses it. If anyone hits an ImportError, point them at `toksearch.llm`.

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `toksearch_d3d/llm/__init__.py` | Create | Public exports: `skills_path` (`Path`), `AMSC_PRESET` (`Preset`). |
| `toksearch_d3d/__init__.py` | Modify | Add module-level `__llm_description__` for the system-prompt catalog. |
| `toksearch_d3d/pyproject.toml` | Modify | Add `toksearch>=2.7` dependency, three entry-point declarations, add `toksearch_d3d.llm` to packages, drop `toksearch_d3d.agents`. |
| `toksearch_d3d/fdp/cli.py` | Modify | Replace `do_query` body with an `os.execvpe` shim into `toksearch query`; add `do_chat` shim; drop `QUERY_RUNNER_SCRIPT`. |
| `recipe/recipe.yaml` | Modify | Bump `toksearch >=2.7`, drop `anthropic` run dep (now optional inside core toksearch's `[llm]` extra). |
| `toksearch_d3d/agents/__init__.py` | Delete | Legacy package removed. |
| `toksearch_d3d/agents/claude_toksearch_agent.py` | Delete | Legacy code removed. |
| `tests/test_fdp_query.py` | Modify | Update test expectations for the new exec/argv shape; drop JSON-stdin assertions. |
| `tests/test_llm_pr4_contributor.py` | Create | Verify `toksearch_d3d` is discovered as a namespace + skills + preset contributor end-to-end. |

---

## Task 1: Add `toksearch_d3d.llm` subpackage and `__llm_description__`

**Files:**
- Create: `toksearch_d3d/llm/__init__.py`
- Modify: `toksearch_d3d/__init__.py`

Use the FULL 13-line Apache header (matching `setup.py` lines 1-13 of `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch/setup.py`) in any new file.

- [ ] **Step 1: Create `toksearch_d3d/llm/__init__.py`**

```python
# [FULL 13-line Apache header]
"""toksearch_d3d.llm -- contributor module for toksearch.llm.

Exposes:
- ``skills_path``: directory of DIII-D-specific SKILL.md files, registered
  via the ``toksearch.llm.skills`` entry point.
- ``AMSC_PRESET``: a backend preset that points the Anthropic backend at
  GA's American Science Cloud endpoint with ``~/amsc_api_key`` as the key
  source, registered via the ``toksearch.llm.presets`` entry point.

The ``toksearch.llm.namespace`` entry point points at ``toksearch_d3d``
itself (whose ``__init__.py`` defines ``__llm_description__``).
"""

from pathlib import Path

from toksearch.llm.presets import Preset


skills_path: Path = Path(__file__).parent.parent / "skills"


AMSC_PRESET: Preset = Preset(
    backend="anthropic",
    model="claude-sonnet-4-6",
    base_url="https://api.i2-core.american-science-cloud.org",
    api_key_file="~/amsc_api_key",
)


__all__ = ["skills_path", "AMSC_PRESET"]
```

- [ ] **Step 2: Add `__llm_description__` to `toksearch_d3d/__init__.py`**

Open `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/toksearch_d3d/__init__.py`. Find the LAST line of the file (the `__version__ = ...` line is near the bottom). Append AFTER it:

```python

__llm_description__ = (
    "toksearch_d3d - DIII-D signal classes (PtDataSignal, ImasSignal, "
    "CakeSignal) + FDP/Pelican data access via the `fdp` CLI"
)
```

(Adjust as needed if `__version__` isn't the last meaningful line; the important thing is that `__llm_description__` is a module-level top-level binding.)

- [ ] **Step 3: Verify both imports work**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -c "
import toksearch_d3d
print('description:', toksearch_d3d.__llm_description__)
from toksearch_d3d.llm import skills_path, AMSC_PRESET
print('skills_path exists:', skills_path.exists())
print('AMSC preset base_url:', AMSC_PRESET.base_url)
print('AMSC preset api_key_file:', AMSC_PRESET.api_key_file)
"
```

Expected output:

```
description: toksearch_d3d - DIII-D signal classes ...
skills_path exists: True
AMSC preset base_url: https://api.i2-core.american-science-cloud.org
AMSC preset api_key_file: ~/amsc_api_key
```

- [ ] **Step 4: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add toksearch_d3d/llm/__init__.py toksearch_d3d/__init__.py
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Add toksearch_d3d.llm subpackage with AMSC preset and skills path

Two contributions to toksearch.llm: a `skills_path` Path pointing at the
existing toksearch_d3d/skills/ directory, and an AMSC_PRESET that maps
backend="anthropic" + base_url=AmSC endpoint + api_key_file=~/amsc_api_key.
The toksearch_d3d module itself becomes a namespace contributor via the
new __llm_description__ attribute.

The actual entry-point registration lives in pyproject.toml (Task 2).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Declare entry points and update packages list

**Files:**
- Modify: `toksearch_d3d/pyproject.toml`

- [ ] **Step 1: Read the current `pyproject.toml`**

```bash
cat /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/pyproject.toml
```

You'll need to make three edits below; the rest of the file stays intact.

- [ ] **Step 2: Add `toksearch>=2.7` to `dependencies`**

The current line reads `dependencies = []`. Replace with:

```toml
dependencies = ["toksearch>=2.7"]
```

If `release-2.7.0` of toksearch hasn't been tagged yet at PR-merge time, soften to `toksearch>=2.6.0` and add a note in the commit body; the in-tree pixi dev env tracks the unreleased main.

- [ ] **Step 3: Update `[tool.setuptools]` packages list**

Replace the existing line:

```toml
packages = ["toksearch_d3d", "toksearch_d3d.fdp", "toksearch_d3d.signal", "toksearch_d3d.tools", "toksearch_d3d.agents"]
```

with:

```toml
packages = ["toksearch_d3d", "toksearch_d3d.fdp", "toksearch_d3d.llm", "toksearch_d3d.signal", "toksearch_d3d.tools"]
```

(Removes `toksearch_d3d.agents`, adds `toksearch_d3d.llm`. The legacy agents package is deleted in Task 4.)

- [ ] **Step 4: Add three `[project.entry-points...]` tables**

Append at the very end of `pyproject.toml`:

```toml

[project.entry-points."toksearch.llm.namespace"]
toksearch_d3d = "toksearch_d3d"

[project.entry-points."toksearch.llm.skills"]
toksearch_d3d = "toksearch_d3d.llm:skills_path"

[project.entry-points."toksearch.llm.presets"]
amsc = "toksearch_d3d.llm:AMSC_PRESET"
```

- [ ] **Step 5: Refresh the editable install so entry points take effect**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run pip install -e . --no-deps 2>&1 | tail -3
```

- [ ] **Step 6: Verify the entry points are visible**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -c "
from importlib.metadata import entry_points
for group in ('toksearch.llm.namespace', 'toksearch.llm.skills', 'toksearch.llm.presets'):
    print(f'--- {group} ---')
    for ep in entry_points(group=group):
        print(f'  {ep.name} -> {ep.value}')
"
```

Expected output includes:

```
--- toksearch.llm.namespace ---
  toksearch -> toksearch
  toksearch_d3d -> toksearch_d3d
--- toksearch.llm.skills ---
  toksearch -> toksearch.llm:CORE_SKILLS_DIR
  toksearch_d3d -> toksearch_d3d.llm:skills_path
--- toksearch.llm.presets ---
  amsc -> toksearch_d3d.llm:AMSC_PRESET
```

The `toksearch` entries are registered by core toksearch from PR 2; their presence confirms the install picked up the new pyproject metadata.

- [ ] **Step 7: Smoke-test that a Session sees toksearch_d3d as a contributor**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -c "
from toksearch.llm.discovery import discover_namespace_contributors, discover_skill_dirs, discover_presets, clear_discovery_cache
clear_discovery_cache()
ns = [(n, d) for n, _v, d in discover_namespace_contributors()]
print('namespace:', ns)
skills = [n for n, _p in discover_skill_dirs()]
print('skills:', skills)
presets = sorted(discover_presets())
print('presets:', presets)
"
```

Expected:

```
namespace: [('toksearch', 'core toksearch ...'), ('toksearch_d3d', 'toksearch_d3d - DIII-D ...')]
skills: ['toksearch', 'toksearch_d3d']
presets: ['amsc']
```

- [ ] **Step 8: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add pyproject.toml
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Register toksearch_d3d as a toksearch.llm contributor

Three entry points: toksearch.llm.namespace (toksearch_d3d module),
toksearch.llm.skills (toksearch_d3d/skills/), toksearch.llm.presets
(amsc -> AMSC_PRESET). Adds toksearch>=2.7 dependency for the discovery
machinery and drops the legacy toksearch_d3d.agents package from the
packages list in preparation for its removal in Task 4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Replace `fdp.cli` agent shims with delegates to `toksearch.llm`

**Files:**
- Modify: `toksearch_d3d/fdp/cli.py`
- Modify: `tests/test_fdp_query.py`

The current `do_query` builds a JSON payload, spawns a Python subprocess that runs `query_toksearch` from the legacy agent module, and pipes the payload over stdin. After PR 4 the agent module is gone; `do_query` becomes a thin shim that `setup_environment()` (already called by `main()` before dispatch) and then `os.execvpe`s into `python -m toksearch.llm.cli query <prompt> --backend amsc ...`. Same env-block ordering guarantee, simpler payload.

- [ ] **Step 1: Update `tests/test_fdp_query.py` with the new expected shape**

Read the existing `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/tests/test_fdp_query.py` first to understand its structure. The existing helper mocks `subprocess.run` and asserts the command/env shape; with `os.execvpe` we mock `os.execvpe` instead.

REPLACE the entire file content with:

```python
# [FULL 13-line Apache header]

"""Tests for the `fdp query` and `fdp chat` CLI shims.

After PR 4 of the toksearch.llm migration, both subcommands are thin
re-exec shims that call `setup_environment()` (already invoked by
`main()` before dispatch) and then `os.execvpe` into
`python -m toksearch.llm.cli {query,chat} ...`.  These tests mock
`os.execvpe` to verify the argv and env are constructed correctly
without actually exec'ing.

`setup_environment` is patched on `cli` (not on `.environment`) because
`cli.py` does `from .environment import setup_environment`, binding the
name into the `cli` module namespace; that is the binding `main()` calls.
"""

import os
import sys
import unittest
from unittest import mock


class _ShimTestBase(unittest.TestCase):
    def _run_cli(self, argv):
        from toksearch_d3d.fdp import cli
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(cli, "setup_environment"), \
                mock.patch.object(cli.os, "execvpe") as execvpe_mock:
            # os.execvpe normally never returns; we don't want main() to
            # continue, so mock it to no-op.  In production it never returns
            # to Python because the process image is replaced.
            try:
                cli.main()
            except SystemExit:
                pass
        return execvpe_mock


class TestFdpQuery(_ShimTestBase):
    def test_query_dispatches_to_toksearch_llm_cli(self):
        m = self._run_cli(["fdp", "query", "hello"])
        m.assert_called_once()
        _, args, env = m.call_args.args
        self.assertEqual(args[0], sys.executable)
        self.assertEqual(args[1:4], ["-m", "toksearch.llm.cli", "query"])
        self.assertIn("hello", args)
        # Default --backend is amsc
        self.assertEqual(args[args.index("--backend") + 1], "amsc")
        # Env passes os.environ
        self.assertIs(env, os.environ)

    def test_query_backend_flag_forwarded(self):
        m = self._run_cli(
            ["fdp", "query", "--backend", "anthropic", "hi"])
        args = m.call_args.args[1]
        self.assertEqual(args[args.index("--backend") + 1], "anthropic")

    def test_query_max_iterations_flag_forwarded(self):
        m = self._run_cli(["fdp", "query", "-n", "3", "hi"])
        args = m.call_args.args[1]
        self.assertIn("-n", args)
        self.assertEqual(args[args.index("-n") + 1], "3")


class TestFdpChat(_ShimTestBase):
    def test_chat_dispatches_to_toksearch_llm_cli(self):
        m = self._run_cli(["fdp", "chat"])
        m.assert_called_once()
        _, args, env = m.call_args.args
        self.assertEqual(args[1:4], ["-m", "toksearch.llm.cli", "chat"])
        # Default --backend is amsc
        self.assertEqual(args[args.index("--backend") + 1], "amsc")
        self.assertIs(env, os.environ)

    def test_chat_backend_flag_forwarded(self):
        m = self._run_cli(["fdp", "chat", "--backend", "claude-max"])
        args = m.call_args.args[1]
        self.assertEqual(args[args.index("--backend") + 1], "claude-max")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify tests fail (against the existing cli.py)**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python -m unittest test_fdp_query -v'
```

Expected: most tests fail with `AttributeError: <module 'os'> does not have the attribute 'execvpe'` (because the existing `cli` doesn't import `os.execvpe`), or with assertions about the legacy subprocess+JSON shape not matching.

- [ ] **Step 3: Rewrite `do_query`, add `do_chat`, drop `QUERY_RUNNER_SCRIPT`**

Open `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/toksearch_d3d/fdp/cli.py`.

Find the `QUERY_RUNNER_SCRIPT = """..."""` block (currently around line 248) and the `do_query` function below it. DELETE both. Replace with:

```python
def _build_llm_cmd(subcommand: str, passthrough_args: list[str]) -> list[str]:
    """Construct argv for the toksearch.llm CLI delegate."""
    cmd = [sys.executable, "-m", "toksearch.llm.cli", subcommand]
    # Default backend: amsc, preserves existing `fdp query` behavior so
    # users with ~/amsc_api_key see no change.  The user can override with
    # --backend on the fdp side.
    if "--backend" not in passthrough_args:
        cmd.extend(["--backend", "amsc"])
    cmd.extend(passthrough_args)
    return cmd


def do_query(args):
    # Re-exec into python -m toksearch.llm.cli query.  The exec replaces
    # this Python process so libfdpio/XRootD env vars set by
    # setup_environment() are honored at the new process's C-library load
    # time (subprocess vs re-exec is equivalent here for env block; re-exec
    # is simpler and avoids subprocess wait/return-code plumbing).
    passthrough = [args.query]
    if args.backend:
        passthrough.extend(["--backend", args.backend])
    if args.model:
        passthrough.extend(["--model", args.model])
    if args.max_iterations is not None:
        passthrough.extend(["-n", str(args.max_iterations)])
    cmd = _build_llm_cmd("query", passthrough)
    os.execvpe(cmd[0], cmd, os.environ)


def do_chat(args):
    passthrough = []
    if args.backend:
        passthrough.extend(["--backend", args.backend])
    if args.model:
        passthrough.extend(["--model", args.model])
    if args.max_iterations is not None:
        passthrough.extend(["-n", str(args.max_iterations)])
    cmd = _build_llm_cmd("chat", passthrough)
    os.execvpe(cmd[0], cmd, os.environ)
```

- [ ] **Step 4: Update the argparse wiring in `main()` to add `chat` and adjust `query`**

In the same file (`cli.py`), find the existing `query_parser = subparsers.add_parser("query", ...)` block in `main()`. Replace it (and the four `query_parser.add_argument` calls below it) with:

```python
    def _add_llm_args(parser):
        parser.add_argument(
            "--backend", default=None,
            help="Backend / preset name (default: amsc). Options: amsc, "
                 "anthropic, openai, claude-max, or any user preset.")
        parser.add_argument(
            "--model", default=None,
            help="Override the preset's default model.")
        parser.add_argument(
            "-n", "--max-iterations", type=int, default=None,
            help="Cap on tool-call rounds per turn.")

    query_parser = subparsers.add_parser(
        "query",
        help="Run a one-shot natural-language query against TokSearch",
    )
    query_parser.add_argument(
        "query",
        type=str,
        help="Natural-language query (quote it on the shell)",
    )
    _add_llm_args(query_parser)
    query_parser.set_defaults(func=do_query)

    chat_parser = subparsers.add_parser(
        "chat",
        help="Interactive conversational query against TokSearch",
    )
    _add_llm_args(chat_parser)
    chat_parser.set_defaults(func=do_chat)
```

(`query` no longer accepts `--quiet` / `--api-key-file` / top-level `--debug` flags; those were scoped to the legacy agent. The new CLI inherits any debug behavior from `toksearch.llm.cli`.)

- [ ] **Step 5: Verify all `test_fdp_query.py` tests pass**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python -m unittest test_fdp_query -v 2>&1 | tail -15'
```

Expected: 5 tests pass.

- [ ] **Step 6: Verify `fdp --help` shows both subcommands**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run fdp --help
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run fdp query --help
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run fdp chat --help
```

Expected: `query` and `chat` both listed; their `--help` shows `--backend`, `--model`, `-n`.

- [ ] **Step 7: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add toksearch_d3d/fdp/cli.py tests/test_fdp_query.py
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Replace fdp agent shim with delegates into toksearch.llm.cli

`fdp query` and the new `fdp chat` both call setup_environment() (still
in main() before dispatch) and then os.execvpe into
`python -m toksearch.llm.cli {query,chat}`.  The default --backend is
"amsc" so existing users with ~/amsc_api_key see no change in behavior;
override with --backend to use anthropic, openai, claude-max, or a user
preset.  The legacy JSON-stdin payload is gone (no longer needed because
the new CLI takes plain argv).

Drops legacy `--quiet`, `--api-key-file`, `--debug` flags from `fdp
query`; their effects are subsumed by the new CLI's behavior.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Delete `toksearch_d3d/agents/` and update the conda recipe

**Files:**
- Delete: `toksearch_d3d/agents/__init__.py`
- Delete: `toksearch_d3d/agents/claude_toksearch_agent.py`
- Modify: `recipe/recipe.yaml`

- [ ] **Step 1: Delete the legacy agents package**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d rm -r toksearch_d3d/agents
```

Confirm:

```bash
ls /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/toksearch_d3d/
```

Should NOT show an `agents/` directory anymore.

- [ ] **Step 2: Update `recipe/recipe.yaml`**

Open `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/recipe/recipe.yaml`. Find the `run:` section under `requirements:`. It currently looks like:

```yaml
  run:
    - python
    - toksearch >=2.6.0
    - ptdata >=2.0.2,<3
    - imas_composer >=0.2
    - anthropic >=0.101.0,<1
```

Replace with:

```yaml
  run:
    - python
    - toksearch >=2.7
    - ptdata >=2.0.2,<3
    - imas_composer >=0.2
```

(Bumps the toksearch pin to `>=2.7` for the discovery machinery; drops `anthropic` because it now lives in core toksearch's `[llm]` extra and isn't a hard runtime dep of toksearch_d3d.)

- [ ] **Step 3: Run the existing project test suite**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python testit.py --mock --noptdata --nod3drdb 2>&1 | tail -10'
```

Expected: all tests pass. The previously-failing tests (if any referenced `toksearch_d3d.agents`) should already have been updated in Task 3.

If any test fails due to `ModuleNotFoundError: No module named 'toksearch_d3d.agents'`, find and delete the offending test or import — it's an orphan from the old code path. There should not be any such test after Task 3.

- [ ] **Step 4: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add recipe/recipe.yaml
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Delete legacy toksearch_d3d.agents and bump conda recipe pins

The agent module has been replaced by the toksearch.llm library + the
fdp.cli shims that delegate to it. The conda recipe loses its anthropic
run-dep (now part of core toksearch's [llm] optional extra) and bumps
its toksearch pin to >=2.7 for the entry-point discovery machinery.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: End-to-end contributor smoke + manual smoke (operator-run)

**Files:**
- Create: `tests/test_llm_pr4_contributor.py`

This task adds an automated test that exercises the full contributor pipeline (entry-point discovery → namespace + skills + preset registered → `resolve_preset("amsc")` returns the AmSC config), then documents manual smoke steps.

- [ ] **Step 1: Create the contributor test**

Create `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/tests/test_llm_pr4_contributor.py` with the FULL 13-line Apache header followed by:

```python
"""End-to-end test that toksearch_d3d shows up as a toksearch.llm contributor.

Requires the editable install picked up the pyproject.toml entry-point
declarations (Task 2).  Runs only when the toksearch.llm machinery is
importable (i.e. core toksearch is at PR 30 or later); otherwise skips.
"""

import unittest


try:
    from toksearch.llm.discovery import (
        discover_namespace_contributors,
        discover_skill_dirs,
        discover_presets,
        clear_discovery_cache,
    )
    from toksearch.llm.presets import resolve_preset
    from toksearch.llm.config import Config
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False


@unittest.skipUnless(_LLM_AVAILABLE,
                     "toksearch.llm not available (requires toksearch>=2.7)")
class TestToksearchD3dContributor(unittest.TestCase):
    def setUp(self):
        clear_discovery_cache()

    def tearDown(self):
        clear_discovery_cache()

    def test_namespace_entry_registered(self):
        names = [n for n, _v, _d in discover_namespace_contributors()]
        self.assertIn("toksearch_d3d", names)

    def test_namespace_description_populated(self):
        for name, _value, desc in discover_namespace_contributors():
            if name == "toksearch_d3d":
                self.assertIn("DIII-D", desc)
                return
        self.fail("toksearch_d3d not in namespace contributors")

    def test_skills_dir_registered(self):
        names = [n for n, _p in discover_skill_dirs()]
        self.assertIn("toksearch_d3d", names)

    def test_amsc_preset_registered(self):
        self.assertIn("amsc", discover_presets())

    def test_amsc_preset_resolves(self):
        preset = resolve_preset("amsc", Config())
        self.assertEqual(preset.backend, "anthropic")
        self.assertEqual(
            preset.base_url,
            "https://api.i2-core.american-science-cloud.org")
        self.assertEqual(preset.api_key_file, "~/amsc_api_key")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python -m unittest test_llm_pr4_contributor -v'
```

Expected: 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add tests/test_llm_pr4_contributor.py
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Add end-to-end test for toksearch_d3d contributor registration

Runs discovery for real (not mocked) and asserts toksearch_d3d shows
up in all three entry-point groups: namespace, skills, presets.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Manual smoke (operator-run, not automated)**

These require a populated `~/amsc_api_key` and an active `BEARER_TOKEN` / `~/.fdp/token`. Skip if either is missing.

- [ ] **Step 5: One-shot query via AmSC**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run fdp query "Fetch the ip signal for shot 165920 and print its peak value in MA."
```

Expected: per-iteration `[run_python] ...` lines and a final text containing a peak around 1.15 MA. Confirms the AmSC preset works through the new shim.

- [ ] **Step 6: REPL via AmSC**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run fdp chat
```

Try a multi-turn sequence that requires DIII-D-specific knowledge:
```
you> Fetch beta_normal for shot 200000 from IMAS and report the peak.
you> Now fetch ip for the same shot via PtData and report peak in MA.
you> /quit
```

Expected: agent uses ImasSignal and PtDataSignal correctly (`lookup_docs(skill_name="toksearch-d3d-imas")` etc. may appear); the namespace persists across turns.

- [ ] **Step 7: Verify backend override works**

```bash
ANTHROPIC_API_KEY=sk-ant-... pixi run fdp query --backend anthropic "What is 2+2 in Python?"
```

Expected: works against the direct Anthropic API instead of AmSC; final text mentions `4`.

If any step fails, the failure is either in the fdp shim (Task 3) or the contributor registration (Tasks 1-2). Both are covered by unit tests; a new smoke failure is worth a follow-up unit test case.

---

## Self-Review Notes

Coverage against the PR 4 scope:
- ✓ `toksearch_d3d.llm` subpackage with `skills_path` and `AMSC_PRESET` — Task 1.
- ✓ `__llm_description__` on `toksearch_d3d` module — Task 1.
- ✓ Three entry-point declarations in `pyproject.toml` — Task 2.
- ✓ `fdp query` shim and new `fdp chat` shim — Task 3.
- ✓ Legacy `toksearch_d3d.agents` package deleted — Task 4.
- ✓ Conda recipe pin bumped + anthropic dep dropped — Task 4.
- ✓ End-to-end contributor test — Task 5.
- ✓ Manual smoke documented — Task 5.

Explicit decisions (called out in scope notes):
- Default `fdp` backend is `amsc` to preserve existing user behavior.
- Legacy `--quiet` / `--api-key-file` / `--debug` flags dropped from `fdp query`.
- No deprecation shim for `query_toksearch`; PR 5 of the migration is collapsed into PR 4 (no removal-after-release-cycle).
