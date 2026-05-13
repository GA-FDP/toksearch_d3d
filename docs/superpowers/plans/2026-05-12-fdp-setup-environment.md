# FDP `setup_environment` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the FDP environment-setup logic from the `fdp` CLI into a public Python function `toksearch_d3d.setup_environment()` so scripts can configure FDP access without going through `fdp run`.

**Architecture:** Move `DEFAULT_CONFIG`, `apply_environment`, and related helpers from `toksearch_d3d/fdp/cli.py` into a new `toksearch_d3d/fdp/environment.py`. Add a `setup_environment(bearer_token=None, **overrides)` function that applies defaults, force-sets keyword overrides, and resolves the bearer token. Refactor the CLI to call it. Re-export at the package root.

**Tech Stack:** Python 3.11, `unittest`, `unittest.mock`, pixi-managed pixi env, vendored versioneer.

**Reference spec:** `docs/superpowers/specs/2026-05-12-fdp-setup-environment-design.md`

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `toksearch_d3d/fdp/environment.py` | Create | Owns `DEFAULT_CONFIG`, `apply_environment`, `setup_environment`, and FDP URL constants. No XRootD imports. |
| `toksearch_d3d/fdp/cli.py` | Modify | Drop moved definitions; import from `.environment`; replace inline env block in `main()` with a `setup_environment` call. |
| `toksearch_d3d/fdp/__init__.py` | Modify | Re-export `setup_environment`. |
| `toksearch_d3d/__init__.py` | Modify | Re-export `setup_environment` and add a short docstring section. |
| `tests/test_fdp_cli.py` | Delete | Replaced by `tests/test_fdp_environment.py`. |
| `tests/test_fdp_environment.py` | Create | Existing `apply_environment` tests (moved over with updated imports) plus new `setup_environment` tests. |

---

## Task 1: Move environment primitives into a new module

**Files:**
- Create: `toksearch_d3d/fdp/environment.py`
- Modify: `toksearch_d3d/fdp/cli.py`
- Create: `tests/test_fdp_environment.py`
- Delete: `tests/test_fdp_cli.py`

This is a structural lift-and-shift. No behavior changes. The existing
`apply_environment` tests get carried over with updated imports and serve as
the regression net.

- [ ] **Step 1: Create `toksearch_d3d/fdp/environment.py`**

Create the file with this exact content:

```python
# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""FDP environment configuration.

Owns the defaults applied by ``fdp run`` and exposes ``setup_environment`` so
Python scripts can configure FDP access without going through the CLI.
"""

from pathlib import Path
import os
import sys
import warnings


##############################################################################
# Pelican / OSDF endpoints
##############################################################################

OSDF_SERVER = "pelican://osg-htc.org:443"
ORIGIN_SERVER = "root://fdp-d3d-origin.nationalresearchplatform.org:8443"
FDP_ROOT = f"{OSDF_SERVER}/fdp-d3d"
ARCHIVES_DIR = f"{FDP_ROOT}/archives"


##############################################################################
# Default config
##############################################################################

def get_default_xrd_pluginconfdir():
    conda_prefix = os.getenv("CONDA_PREFIX", None)
    prefix = os.getenv("PREFIX", None)

    def _plugin_conf_path(base_dir):
        return os.path.join(base_dir, "etc", "xrootd", "client.plugins.d")

    if conda_prefix is not None:
        return _plugin_conf_path(conda_prefix)
    elif prefix is not None:
        return _plugin_conf_path(prefix)
    else:
        val = os.getenv("XRD_PLUGINCONFDIR", None)
        if val is None:
            warnings.warn(
                "XRD_PLUGINCONFDIR is not set. "
                "This may cause problems with FDP access."
            )
        return val


# Resolve the active Python environment's directories
python_executable_path = Path(sys.executable)
env_dir = python_executable_path.parent.parent
lib_dir = env_dir / "lib"
bin_dir = env_dir / "bin"

DEFAULT_CONFIG = {
    # XRootD / FDP
    "XRDCP_ALLOW_HTTP": "true",
    "XRD_PELICANUSEAUTHHEADERS": "true",
    "XRD_CURLDISABLEPREFETCH": "1",
    "XRD_PLUGINCONFDIR": get_default_xrd_pluginconfdir(),
    # Thread-affinity vars (keep NumPy / MKL single-threaded)
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    # pymssql TLS requirement
    "TDSVER": "7.0",
    # Cake metadata DB
    "CAKE_DB_PATH": f"{FDP_ROOT}/metadata/iri_logs.db",
    # Shared-library and certificate locations
    "X509_CERT_FILE": str(env_dir / "ssl" / "cacert.pem"),
    # Prepend the active env's bin directory to PATH
    "PATH": f"{bin_dir}:{os.getenv('PATH', '')}",
    # TDI search path for MDSplus
    "MDS_PATH": str(env_dir / "tdi"),
    "default_tree_path": ";".join(
        [
            "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c",
            "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t",
            "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t",
            "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c",
        ]
    ),
    # PTData Config
    "D3DATA": "yes",
    "PTDATA_LOC": os.getenv("PTDATA_LOC", "1"),  # Do NOT go out to athena by default
    "PTDATA_JSON_INDEX_DIR": f"{ARCHIVES_DIR}/index/json/json_indexes_2026-01-13_12:22:11",
    "PTDATA_LIBRARY": str(lib_dir / "libd3.so"),
    "PTDATA_PLUGIN_LIB": str(lib_dir / "libjson_index_plugin.so"),
    "SYS_D3_DELIM": ";",
}


def apply_environment(config, env):
    """Apply config to env, preserving existing values except PATH.

    PATH is overwritten unconditionally because DEFAULT_CONFIG["PATH"]
    is built by prepending the env's bin_dir to the existing PATH at
    import time, so we must always write it through.
    """
    env["PATH"] = config["PATH"]
    for k, v in config.items():
        if k == "PATH":
            continue
        env.setdefault(k, v)
```

- [ ] **Step 2: Update `toksearch_d3d/fdp/cli.py`**

Replace the file's environment-setup section with imports from
`.environment`. The full diff:

**Remove** lines 16–95 (the comment block titled "ENVIRONMENT", `get_default_xrd_pluginconfdir`, the URL constants, the `env_dir`/`lib_dir`/`bin_dir` block, and `DEFAULT_CONFIG`).

**Remove** lines 229–240 (the `apply_environment` definition with its docstring).

**Add** at the top of `cli.py`, after the existing imports (replace the existing `from .skills import _parse_skill_md` line with this block):

```python
from .skills import _parse_skill_md
from .environment import (
    DEFAULT_CONFIG,
    FDP_ROOT,
    ORIGIN_SERVER,
    apply_environment,
)
```

(`apply_environment` is still imported in this task because `main()` still uses it. It will be removed in Task 3 when we switch `main()` to `setup_environment`.)

After this step, `cli.py` will start at `from XRootD import client` and contain only: XRootD-using helpers (`FdpFileSystem`), skill backends, subcommands (`do_skills`, `do_run`, `do_env`, `do_ls`), and `main()`. Confirm by reading the file.

- [ ] **Step 3: Move the existing test file**

Delete `tests/test_fdp_cli.py` and create `tests/test_fdp_environment.py` with this content (same five tests, updated imports and docstring):

```python
# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for toksearch_d3d.fdp.environment."""

import unittest

from toksearch_d3d.fdp.environment import DEFAULT_CONFIG, apply_environment


class TestApplyEnvironment(unittest.TestCase):
    def test_path_always_overwritten(self):
        """PATH is overwritten because config["PATH"] already incorporates the existing PATH."""
        env = {"PATH": "/existing/bin"}
        config = {"PATH": "/new/bin:/existing/bin"}
        apply_environment(config, env)
        self.assertEqual(env["PATH"], "/new/bin:/existing/bin")

    def test_existing_value_not_clobbered(self):
        """User-set values for non-PATH keys are preserved."""
        env = {"PATH": "/p", "TDSVER": "8.0"}
        config = {"PATH": "/p", "TDSVER": "7.0"}
        apply_environment(config, env)
        self.assertEqual(env["TDSVER"], "8.0")

    def test_missing_value_filled_from_config(self):
        """Keys not present in env get the default from config."""
        env = {"PATH": "/p"}
        config = {"PATH": "/p", "MKL_NUM_THREADS": "1"}
        apply_environment(config, env)
        self.assertEqual(env["MKL_NUM_THREADS"], "1")

    def test_mutates_in_place(self):
        """env is mutated in place (no rebind), preserving os._Environ semantics."""
        env = {"PATH": "/p"}
        original_id = id(env)
        result = apply_environment({"PATH": "/p", "FOO": "bar"}, env)
        self.assertIsNone(result)
        self.assertEqual(id(env), original_id)
        self.assertEqual(env["FOO"], "bar")

    def test_real_default_config_against_synthetic_env(self):
        """End-to-end with the real DEFAULT_CONFIG: PATH applied, existing kept, missing filled."""
        env = {"PATH": "/system/bin", "OMP_NUM_THREADS": "4"}
        apply_environment(DEFAULT_CONFIG, env)
        # PATH always replaced with config's value (which prepends the env's bin_dir).
        self.assertEqual(env["PATH"], DEFAULT_CONFIG["PATH"])
        # User-set OMP_NUM_THREADS survives.
        self.assertEqual(env["OMP_NUM_THREADS"], "4")
        # TDSVER wasn't in env, gets the default.
        self.assertEqual(env["TDSVER"], "7.0")


if __name__ == "__main__":
    unittest.main()
```

Delete the old file:

```bash
rm tests/test_fdp_cli.py
```

- [ ] **Step 4: Run the tests**

Run: `pixi run bash -c 'cd tests && python -m unittest test_fdp_environment -v'`

Expected: 5 tests pass.

If anything fails with `ImportError: cannot import name X from toksearch_d3d.fdp.cli`, the cli.py import block from Step 2 was incomplete — re-check that `DEFAULT_CONFIG`, `FDP_ROOT`, `ORIGIN_SERVER`, `apply_environment` are all imported.

- [ ] **Step 5: Verify CLI still works**

Run: `pixi run fdp env | head -5`

Expected: prints `export XRDCP_ALLOW_HTTP='true'` and other export lines, no traceback.

Run: `pixi run fdp ls /`

Expected: prints `fdp-d3d`.

- [ ] **Step 6: Commit**

```bash
git add toksearch_d3d/fdp/environment.py toksearch_d3d/fdp/cli.py tests/test_fdp_environment.py tests/test_fdp_cli.py
git commit -m "Move FDP environment config into its own module"
```

(`git add tests/test_fdp_cli.py` stages the deletion.)

---

## Task 2: Add `setup_environment` (TDD)

**Files:**
- Modify: `tests/test_fdp_environment.py`
- Modify: `toksearch_d3d/fdp/environment.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fdp_environment.py` (before the `if __name__ == "__main__":` line). Add the additional imports at the top of the file first:

```python
import os
import tempfile
import warnings
from pathlib import Path
from unittest import mock
```

Then append this test class:

```python
class TestSetupEnvironment(unittest.TestCase):
    """setup_environment applies defaults, force-sets overrides, resolves bearer token."""

    def _isolated_env(self, **initial):
        """Return a mock.patch.dict context that fully replaces os.environ."""
        return mock.patch.dict(os.environ, initial, clear=True)

    def _isolated_home(self, tmpdir):
        """Patch Path.home() inside environment.py to point at tmpdir."""
        return mock.patch(
            "toksearch_d3d.fdp.environment.Path.home",
            return_value=Path(tmpdir),
        )

    def test_default_applied_when_env_empty(self):
        """DEFAULT_CONFIG values populate when env var is absent."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(), tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake")
            self.assertEqual(os.environ["TDSVER"], "7.0")

    def test_existing_env_preserved_against_default(self):
        """User-set env values win over DEFAULT_CONFIG (no override passed)."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(TDSVER="8.0"), \
                tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake")
            self.assertEqual(os.environ["TDSVER"], "8.0")

    def test_override_wins_over_existing_env(self):
        """A keyword override beats an already-set env var."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(PTDATA_LOC="9"), \
                tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake", PTDATA_LOC="1")
            self.assertEqual(os.environ["PTDATA_LOC"], "1")

    def test_override_stringifies_non_string_value(self):
        """Non-string override values are converted via str()."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(), tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake", PTDATA_LOC=2)
            self.assertEqual(os.environ["PTDATA_LOC"], "2")

    def test_bearer_token_arg_wins(self):
        """Explicit bearer_token arg beats existing BEARER_TOKEN env var."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(BEARER_TOKEN="from_env"), \
                tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="from_arg")
            self.assertEqual(os.environ["BEARER_TOKEN"], "from_arg")

    def test_bearer_token_falls_back_to_env(self):
        """When no arg given, existing BEARER_TOKEN env var is kept."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(BEARER_TOKEN="from_env"), \
                tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment()
            self.assertEqual(os.environ["BEARER_TOKEN"], "from_env")

    def test_bearer_token_falls_back_to_file(self):
        """When no arg and no env var, ~/.fdp/token is read."""
        from toksearch_d3d.fdp.environment import setup_environment
        with tempfile.TemporaryDirectory() as tmp:
            fdp_dir = Path(tmp) / ".fdp"
            fdp_dir.mkdir()
            (fdp_dir / "token").write_text("from_file\n")
            with self._isolated_env(), self._isolated_home(tmp):
                setup_environment()
                self.assertEqual(os.environ["BEARER_TOKEN"], "from_file")

    def test_bearer_token_warns_when_none_found(self):
        """Warns when no token can be resolved."""
        from toksearch_d3d.fdp.environment import setup_environment
        with tempfile.TemporaryDirectory() as tmp, \
                self._isolated_env(), self._isolated_home(tmp):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                setup_environment()
                messages = [str(w.message) for w in caught]
                self.assertTrue(
                    any("BEARER_TOKEN" in m for m in messages),
                    f"expected a BEARER_TOKEN warning, got: {messages}",
                )

    def test_safe_to_call_twice(self):
        """Calling setup_environment twice is idempotent."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(), tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake")
            first_path = os.environ["PATH"]
            setup_environment(bearer_token="fake")
            self.assertEqual(os.environ["PATH"], first_path)
            self.assertEqual(os.environ["TDSVER"], "7.0")
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `pixi run bash -c 'cd tests && python -m unittest test_fdp_environment.TestSetupEnvironment -v'`

Expected: each test fails with `ImportError: cannot import name 'setup_environment' from 'toksearch_d3d.fdp.environment'`.

- [ ] **Step 3: Implement `setup_environment`**

Append to `toksearch_d3d/fdp/environment.py`:

```python
def setup_environment(bearer_token=None, **overrides):
    """Populate os.environ with FDP variables and resolve BEARER_TOKEN.

    Defaults from DEFAULT_CONFIG are applied with setdefault semantics —
    existing env vars are preserved, except PATH which is overwritten to
    prepend the active env's bin/ directory.

    Keyword overrides force-set the corresponding env vars, winning over both
    DEFAULT_CONFIG and any existing os.environ value. Values are stringified
    via str().

    Bearer token resolution (first non-empty wins): bearer_token arg, then
    BEARER_TOKEN in os.environ (after defaults+overrides applied), then the
    contents of ~/.fdp/token. Warns if no token resolves.

    Returns None. Mutates os.environ in place. Safe to call multiple times.
    """
    apply_environment(DEFAULT_CONFIG, os.environ)
    for key, value in overrides.items():
        os.environ[key] = str(value)

    if not bearer_token:
        bearer_token = os.environ.get("BEARER_TOKEN", "")
    if not bearer_token:
        token_file = Path.home() / ".fdp" / "token"
        try:
            bearer_token = token_file.read_text().strip()
        except OSError:
            warnings.warn(
                "No BEARER_TOKEN specified. "
                "This will cause problems with FDP access."
            )
    os.environ["BEARER_TOKEN"] = bearer_token
```

- [ ] **Step 4: Run all environment tests**

Run: `pixi run bash -c 'cd tests && python -m unittest test_fdp_environment -v'`

Expected: 14 tests pass (5 from Task 1 + 9 new).

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/fdp/environment.py tests/test_fdp_environment.py
git commit -m "Add setup_environment for Python-side FDP configuration"
```

---

## Task 3: Wire the CLI to use `setup_environment`

**Files:**
- Modify: `toksearch_d3d/fdp/cli.py`

- [ ] **Step 1: Update the import block**

In `cli.py`, change the import block added in Task 1:

```python
from .environment import (
    DEFAULT_CONFIG,
    FDP_ROOT,
    ORIGIN_SERVER,
    apply_environment,
)
```

to:

```python
from .environment import (
    DEFAULT_CONFIG,
    FDP_ROOT,
    ORIGIN_SERVER,
    setup_environment,
)
```

(`apply_environment` is no longer needed in `cli.py` — `main()` will call `setup_environment` instead. `DEFAULT_CONFIG` is still needed by `do_env`. `FDP_ROOT` and `ORIGIN_SERVER` are still needed by `do_ls`.)

- [ ] **Step 2: Replace the inline env-setup block in `main()`**

Locate this block in `cli.py::main()` (the section bracketed by `# Environment setup` comments):

```python
    ################# Environment setup ####################
    apply_environment(DEFAULT_CONFIG, os.environ)

    bearer_token = args.bearer_token or os.getenv("BEARER_TOKEN", "")
    if not bearer_token:
        home_dir = Path.home()
        token_file = home_dir / ".fdp" / "token"
        try:
            with open(token_file, "r") as f:
                bearer_token = f.read().strip()
        except:
            warnings.warn("No BEARER_TOKEN specified. This will cause problems with FDP access.")

    os.environ["BEARER_TOKEN"] = bearer_token
    #######################################################
```

Replace with:

```python
    setup_environment(bearer_token=args.bearer_token or None)
```

- [ ] **Step 3: Clean up now-unused imports in `cli.py`**

If `warnings` is no longer referenced anywhere else in `cli.py`, remove its import. Confirm with `grep -n 'warnings' toksearch_d3d/fdp/cli.py` after the edit — the only result should be the import line itself; if so, delete it.

Same check for `Path` (still used in skills backends — keep) and any other leftover symbols.

- [ ] **Step 4: Run the environment tests**

Run: `pixi run bash -c 'cd tests && python -m unittest test_fdp_environment -v'`

Expected: all 14 tests still pass (no regressions).

- [ ] **Step 5: Verify CLI behavior is unchanged**

Run: `pixi run fdp env > /tmp/fdp_env_after.txt && git stash && pixi run fdp env > /tmp/fdp_env_before.txt && git stash pop && diff /tmp/fdp_env_before.txt /tmp/fdp_env_after.txt`

Expected: empty diff (output is byte-identical to pre-refactor `fdp env`).

If the diff isn't empty, inspect it — the only acceptable difference would be ordering of keys (unlikely since both code paths iterate the same dict). Investigate any other difference.

Run: `pixi run fdp ls /`

Expected: prints `fdp-d3d`.

- [ ] **Step 6: Commit**

```bash
git add toksearch_d3d/fdp/cli.py
git commit -m "Use setup_environment in fdp CLI"
```

---

## Task 4: Re-export at the package level + docstring

**Files:**
- Modify: `toksearch_d3d/fdp/__init__.py`
- Modify: `toksearch_d3d/__init__.py`

- [ ] **Step 1: Re-export from the fdp subpackage**

`toksearch_d3d/fdp/__init__.py` is currently empty. Write to it:

```python
from .environment import setup_environment

__all__ = ["setup_environment"]
```

- [ ] **Step 2: Re-export from the package root**

In `toksearch_d3d/__init__.py`, locate the existing imports near the bottom:

```python
from .signal.ptdata import PtDataSignal
from .signal.ptdata import RDataSignal
from .signal.cake import CakeSignal

try:
    from .signal.imas import ImasSignal, list_imas_fields
except ImportError:
    pass

from . import _version
__version__ = _version.get_versions()['version']
```

Add a new line above the `from . import _version` line:

```python
from .fdp import setup_environment
```

So the block becomes:

```python
from .signal.ptdata import PtDataSignal
from .signal.ptdata import RDataSignal
from .signal.cake import CakeSignal

try:
    from .signal.imas import ImasSignal, list_imas_fields
except ImportError:
    pass

from .fdp import setup_environment

from . import _version
__version__ = _version.get_versions()['version']
```

- [ ] **Step 3: Update the package docstring**

In `toksearch_d3d/__init__.py`, locate the `Invocation` section (which currently shows only the `fdp run` form). Replace it with this:

Find the existing section that starts with `Invocation\n==========` and ends just before `Imports\n=======`. Replace its body with:

```
Invocation
==========

Two ways to configure the FDP environment:

**1. Python-side setup** (preferred for scripts and notebooks)::

    from toksearch_d3d import setup_environment
    setup_environment()           # then import signal classes and run pipelines

    # Override individual variables as needed:
    setup_environment(PTDATA_LOC="2", BEARER_TOKEN="...")

**2. CLI wrapper** (preferred when launching a subprocess)::

    TDSVER="7.0" pixi run fdp run python <script.py>

``setup_environment`` and ``fdp run`` apply the same defaults: XRootD plugin
paths, MDSplus tree paths, PTData configuration. The bearer token is
resolved from the ``bearer_token`` argument, then ``$BEARER_TOKEN``, then
``~/.fdp/token``.

``TDSVER="7.0"`` is required whenever the script connects to d3drdb (the
default config sets it, so this only matters if you've overridden it).
```

- [ ] **Step 4: Smoke-test the imports**

Run: `pixi run python -c "from toksearch_d3d import setup_environment; print(setup_environment)"`

Expected: prints `<function setup_environment at 0x...>` — no `ImportError`.

Run: `pixi run python -c "from toksearch_d3d.fdp import setup_environment; print(setup_environment)"`

Expected: same.

- [ ] **Step 5: Run the full test suite**

Run: `pixi run bash -c 'cd tests && python testit.py --mock --noptdata --nod3drdb'`

Expected: all tests pass. (Use `--mock --noptdata --nod3drdb` to skip integration tests that need live FDP access; flip those off only if you have a `BEARER_TOKEN` available and want the full run.)

- [ ] **Step 6: Commit**

```bash
git add toksearch_d3d/fdp/__init__.py toksearch_d3d/__init__.py
git commit -m "Re-export setup_environment at package level"
```

---

## Task 5: Manual end-to-end smoke test

**Files:** None (verification only)

These checks aren't automated because they need a live FDP token. Run them
once with a valid `~/.fdp/token` in place.

- [ ] **Step 1: Python-side data fetch (the new path)**

Run:

```bash
pixi run python -c "
from toksearch_d3d import setup_environment, PtDataSignal
setup_environment()
result = PtDataSignal('ip').fetch(202161)
print('data shape:', result['data'].shape)
print('times shape:', result['times'].shape)
"
```

Expected: prints non-zero `data shape` and `times shape`, no traceback.

- [ ] **Step 2: Override path**

Run:

```bash
pixi run python -c "
import os
os.environ['PTDATA_LOC'] = '9'
from toksearch_d3d import setup_environment
setup_environment(PTDATA_LOC='1')
assert os.environ['PTDATA_LOC'] == '1', os.environ['PTDATA_LOC']
print('ok')
"
```

Expected: prints `ok`.

- [ ] **Step 3: CLI regression**

Run: `pixi run fdp run python -c "import os; print(os.environ['XRD_PLUGINCONFDIR'])"`

Expected: prints the path under the pixi env, no warning, no traceback.

- [ ] **Step 4: `fdp env` byte-equality**

Already verified in Task 3 Step 5. Skip if green there.

---

## Done When

- All 14 unit tests in `tests/test_fdp_environment.py` pass.
- `from toksearch_d3d import setup_environment` works.
- `fdp env`, `fdp run`, `fdp ls` behave identically to before.
- A Python script that calls `setup_environment()` can fetch PTData without
  going through `fdp run`.
- The design spec (`docs/superpowers/specs/2026-05-12-fdp-setup-environment-design.md`) requirements are all covered:
  - [x] New `toksearch_d3d/fdp/environment.py` module owns `DEFAULT_CONFIG`, `apply_environment`, `setup_environment`, FDP URL constants (Task 1)
  - [x] `setup_environment(bearer_token=None, **overrides)` signature (Task 2)
  - [x] Overrides force-set with `str()` stringification (Task 2)
  - [x] Bearer token resolution: arg → env → file → warn (Task 2)
  - [x] Idempotent / safe to call multiple times (Task 2)
  - [x] CLI calls `setup_environment` (Task 3)
  - [x] `do_env` unchanged behavior (Task 3 Step 5)
  - [x] Re-exports at `toksearch_d3d.fdp` and `toksearch_d3d` (Task 4)
  - [x] Module docstring updated with Python-side usage (Task 4)
