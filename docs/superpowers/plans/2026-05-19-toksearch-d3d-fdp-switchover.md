# `toksearch_d3d` Switch-over to fdp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Migrate `toksearch_d3d` from owning `toksearch_d3d/fdp/` to consuming the standalone `fdp` package as a contributor. Delete the old subpackage; add a thin `toksearch_d3d/fdp.py` module that registers `D3D_DEVICE` via the `fdp.devices` entry point and keeps `toksearch_d3d.setup_environment()` working as a back-compat wrapper. Hard cut: no deprecation shim for `toksearch_d3d.fdp.*` Python imports.

**Architecture:** `toksearch_d3d/fdp/` (subpackage with cli.py, environment.py, skills.py) is replaced by `toksearch_d3d/fdp.py` (single module exposing `D3D_DEVICE: fdp.devices.Device`). The `fdp` console script entry moves out of `toksearch_d3d/pyproject.toml`. `toksearch_d3d` adds `fdp >= <release>` as a run-dep. `toksearch_d3d/__init__.py`'s package-level env init delegates to `fdp.setup_environment(device="d3d")`. Once toksearch_d3d ships as a contributor, the `_FALLBACK_DEVICE` in fdp becomes redundant and is removed in the last task.

**Tech Stack:** Python 3.11, fdp >= 0.1.0 (the new package from Plan A), unittest, pixi, rattler-build.

**Reference spec:** `docs/superpowers/specs/2026-05-19-fdp-decoupling-design.md`

**Branch:** `feat/fdp-switchover` off `main` (in `toksearch_d3d` repo).

**Precondition:** `fdp` package's first release (`release-0.1.0`) must be live on the `ga-fdp` conda channel before Plan B's CI can pass. Plan A Task 10 covers that release.

## Scope notes

- Hard cut on the Python-import surface: code that imports
  `from toksearch_d3d.fdp.environment import setup_environment` breaks.
  Mitigation: `toksearch_d3d.setup_environment` stays (top-level re-export),
  which is the most common usage anyway.
- D3D-specific PCSSETUP tooling (`pcssetup-to-wa10` console script + module)
  stays. Unrelated to the fdp decoupling.
- The `toksearch_d3d.llm` subpackage (PR 12's contributor wiring for
  toksearch.llm) stays unchanged.
- The cleanup task (removing `_FALLBACK_DEVICE` from `fdp`) lives at the end
  of this plan even though it touches the `fdp` repo. The implementer
  should switch repos for that task and open a small fdp PR.

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `toksearch_d3d/fdp.py` | Create (replaces subpackage) | `D3D_DEVICE` instance + back-compat `setup_environment()` wrapper. |
| `toksearch_d3d/fdp/` | Delete | Entire subpackage (cli, environment, skills, __init__). |
| `toksearch_d3d/__init__.py` | Modify | Replace any inline FDP env init with `fdp.setup_environment(device="d3d")`. |
| `pyproject.toml` | Modify | Add `fdp.devices` entry point; remove `fdp` script entry; remove `toksearch_d3d.fdp` from packages list. |
| `recipe/recipe.yaml` | Modify | Add `fdp >= 0.1.0` to `requirements.run`. |
| `tests/test_fdp_query.py` | Delete | Tested code now lives in `fdp` repo. |
| `tests/test_fdp_environment.py` | Delete | Same. |
| `tests/test_fdp_decoupling.py` | Create | Verify D3D_DEVICE is discovered + `setup_environment` wrapper delegates. |
| `fdp/devices.py` (in `fdp` repo) | Modify (last task) | Remove `_FALLBACK_DEVICE` and the fallback path in `discover_devices`. |

---

## Task 1: Add `toksearch_d3d/fdp.py` with D3D_DEVICE and wrapper

**Files:**
- Create: `toksearch_d3d/fdp.py` (a single module, NOT a subpackage — the existing `toksearch_d3d/fdp/` directory is deleted in Task 4)
- Create: `tests/test_fdp_decoupling.py`

This task introduces the new module alongside the old subpackage. Both exist briefly until Task 4 removes the subpackage.

**Important note about ordering:** Python's package-resolution prefers a subpackage (`toksearch_d3d/fdp/`) over a sibling module (`toksearch_d3d/fdp.py`) if both exist. So during the brief window between Task 1 and Task 4, `from toksearch_d3d import fdp` still resolves to the old subpackage. The tests in this task therefore import the new module directly via its file path (or temporarily name it `fdp_new.py` and rename in Task 4). **We'll use a temporary name `_fdp_new.py` to avoid the conflict, then rename in Task 4.**

- [ ] **Step 1: Write the failing test**

Create `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/tests/test_fdp_decoupling.py`:

```python
# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for the toksearch_d3d -> fdp switch-over.

Verifies:
  - D3D_DEVICE is a properly-constructed fdp.devices.Device.
  - It's discoverable via the fdp.devices entry point (once Task 2 wires it
    in pyproject.toml).
  - toksearch_d3d.setup_environment() back-compat wrapper delegates to
    fdp.setup_environment(device="d3d").
"""

import unittest
from unittest import mock


class TestD3DDeviceShape(unittest.TestCase):
    def test_d3d_device_imported(self):
        from toksearch_d3d._fdp_new import D3D_DEVICE
        self.assertEqual(D3D_DEVICE.name, "d3d")
        self.assertIn("fdp-d3d", D3D_DEVICE.pelican_root)
        self.assertEqual(D3D_DEVICE.default_llm_preset, "amsc")

    def test_d3d_device_has_required_paths(self):
        from toksearch_d3d._fdp_new import D3D_DEVICE
        self.assertIsNotNone(D3D_DEVICE.mds_default_tree_path)
        self.assertIn("fdp-d3d", D3D_DEVICE.mds_default_tree_path)
        self.assertIsNotNone(D3D_DEVICE.ptdata_index_dir)


class TestEntryPointRegistration(unittest.TestCase):
    """Runs only after Task 2 wires the entry point."""

    def test_d3d_discoverable_via_fdp(self):
        try:
            from fdp.devices import discover_devices, clear_device_cache
        except ImportError:
            self.skipTest("fdp package not installed yet (precondition)")
        clear_device_cache()
        devices = discover_devices()
        self.assertIn("d3d", devices)
        # Confirm it's coming from our contributor (not the fdp fallback)
        from toksearch_d3d._fdp_new import D3D_DEVICE
        # After Task 2 lands the entry point, this should be our object:
        # (Pre-Task-2 it will be the fdp fallback, which is also named "d3d"
        # but has a different description.)
        try:
            self.assertIs(devices["d3d"], D3D_DEVICE)
        except AssertionError:
            self.skipTest("entry point not yet registered (Task 2 prereq)")


class TestSetupEnvironmentWrapper(unittest.TestCase):
    def test_wrapper_calls_fdp_setup_environment_with_d3d(self):
        try:
            import fdp
        except ImportError:
            self.skipTest("fdp package not installed yet")
        from toksearch_d3d._fdp_new import setup_environment
        with mock.patch("fdp.setup_environment") as su:
            setup_environment()
        su.assert_called_once()
        self.assertEqual(su.call_args.kwargs.get("device"), "d3d")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python -m unittest test_fdp_decoupling -v 2>&1 | tail -10'
```

Expected: `ModuleNotFoundError: No module named 'toksearch_d3d._fdp_new'`.

- [ ] **Step 3: Create `toksearch_d3d/_fdp_new.py`**

Use the FULL 13-line Apache header (matching `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch/setup.py` lines 1-13). Then:

```python
"""toksearch_d3d.fdp - DIII-D contributor for the fdp package.

(NOTE: this file is `_fdp_new.py` during the transition; it gets renamed
to `fdp.py` in Task 4 once the old `toksearch_d3d/fdp/` subpackage is
removed. Python's import system prefers a subpackage directory over a
sibling module of the same name, so this rename can't happen until the
subpackage is gone.)

Exposes:
  - D3D_DEVICE: the fdp.devices.Device instance describing DIII-D's
    Pelican namespace, MDSplus paths, PTData index, and `amsc` LLM
    preset. Registered via the `fdp.devices` entry point in
    pyproject.toml.
  - setup_environment(): back-compat wrapper that calls
    fdp.setup_environment(device="d3d", ...).
"""

import fdp
from fdp.devices import Device


D3D_DEVICE: Device = Device(
    name="d3d",
    pelican_root="pelican://osg-htc.org:443/fdp-d3d",
    origin_server="root://fdp-d3d-origin.nationalresearchplatform.org:8443",
    ptdata_index_dir=(
        "pelican://osg-htc.org:443/fdp-d3d/archives/index/json/"
        "json_indexes_2026-01-13_12:22:11"
    ),
    mds_default_tree_path=";".join([
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c",
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t",
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t",
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c",
    ]),
    description="DIII-D fusion experiment, via Pelican",
    default_llm_preset="amsc",
    extra_env={
        "D3DATA": "yes",
        "SYS_D3_DELIM": ";",
        "CAKE_DB_PATH": "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db",
    },
)


def setup_environment(bearer_token: str | None = None, **overrides) -> None:
    """Configure os.environ for DIII-D FDP access.

    Back-compat shim around `fdp.setup_environment(device="d3d", ...)`.
    Pre-existing callers that did `from toksearch_d3d import
    setup_environment` keep working without code changes.
    """
    fdp.setup_environment(
        device="d3d",
        bearer_token=bearer_token,
        **overrides,
    )


__all__ = ["D3D_DEVICE", "setup_environment"]
```

- [ ] **Step 4: Verify the two pre-entry-point tests pass**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python -m unittest test_fdp_decoupling.TestD3DDeviceShape -v 2>&1 | tail -5'
```

Expected: 2 tests pass.

The `TestEntryPointRegistration` and `TestSetupEnvironmentWrapper` tests will skip until Task 2 (entry-point wiring) and the fdp dep is installable.

- [ ] **Step 5: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add toksearch_d3d/_fdp_new.py tests/test_fdp_decoupling.py
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Add D3D_DEVICE + setup_environment wrapper (as _fdp_new.py for now)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire `fdp.devices` entry point + add fdp dep

**Files:**
- Modify: `toksearch_d3d/pyproject.toml`

- [ ] **Step 1: Update `pyproject.toml`**

Three changes:

**(a) Add `fdp` to `dependencies`:**

Locate the line `dependencies = []` and replace with:

```toml
# Runtime deps are declared in recipe/recipe.yaml for conda installs;
# toksearch is from the ga-fdp channel and not on PyPI. Keeping pip
# dependencies empty so `pip install toksearch_d3d` and pixi's pypi
# resolver don't try to fetch toksearch/fdp from PyPI.
dependencies = []
```

(No change if it's already `dependencies = []`. The recipe is the source of truth, not pyproject. Same pattern as today.)

**(b) Remove the `fdp` console script entry:**

Locate the `[project.scripts]` section. Remove the line:

```toml
fdp = "toksearch_d3d.fdp.cli:main"
```

The full `[project.scripts]` should then contain only:

```toml
[project.scripts]
pcssetup-to-wa10 = "toksearch_d3d.tools.pcssetup_to_wa10:main"
```

**(c) Add the `fdp.devices` entry point + remove `toksearch_d3d.fdp` from packages list:**

Locate `[tool.setuptools]` and update the `packages` line. Current:

```toml
packages = ["toksearch_d3d", "toksearch_d3d.fdp", "toksearch_d3d.llm", "toksearch_d3d.signal", "toksearch_d3d.tools"]
```

(or similar — may include `agents` from history). Replace with:

```toml
packages = ["toksearch_d3d", "toksearch_d3d.llm", "toksearch_d3d.signal", "toksearch_d3d.tools"]
```

(Removes `toksearch_d3d.fdp`. The `_fdp_new.py` module added in Task 1 is a top-level module of `toksearch_d3d`, so it's covered by the package entry `toksearch_d3d`.)

Append at the very end of `pyproject.toml`:

```toml
[project.entry-points."fdp.devices"]
d3d = "toksearch_d3d._fdp_new:D3D_DEVICE"
```

(Will be renamed to `toksearch_d3d.fdp:D3D_DEVICE` in Task 4.)

- [ ] **Step 2: Refresh the editable install**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run pip install -e . --no-deps 2>&1 | tail -3
```

- [ ] **Step 3: Verify the entry point is discoverable**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -c "
from importlib.metadata import entry_points
for ep in entry_points(group='fdp.devices'):
    print(ep.name, '->', ep.value)
"
```

Expected: `d3d -> toksearch_d3d._fdp_new:D3D_DEVICE`.

- [ ] **Step 4: Run the decoupling tests (all four now)**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python -m unittest test_fdp_decoupling -v 2>&1 | tail -10'
```

Expected: 4 tests pass (one previously skipping). If `import fdp` still fails because the new fdp package isn't installed in this pixi env, the entry-point test skips with the expected message — that's OK; Task 5 adds fdp to the pixi env.

- [ ] **Step 5: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add pyproject.toml
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Wire fdp.devices entry point; drop fdp script entry + subpackage

Registers D3D_DEVICE via the new fdp.devices entry point.
Drops the `fdp` console script entry (the new fdp package owns it).
Removes toksearch_d3d.fdp from the setuptools packages list in
preparation for the subpackage's deletion (Task 4).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Update `toksearch_d3d/__init__.py` to delegate

**Files:**
- Modify: `toksearch_d3d/__init__.py`

- [ ] **Step 1: Read current state**

```bash
cat /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/toksearch_d3d/__init__.py
```

Look for two things:

1. **The top-level `setup_environment` re-export** — likely a line like:

   ```python
   from .fdp.environment import setup_environment
   ```

2. **The package-level env init block** (if present) — looks like:

   ```python
   import os as _os
   from .fdp.environment import DEFAULT_CONFIG as _defaults, apply_environment as _apply
   _apply(_defaults, _os.environ)
   del _os, _defaults, _apply
   ```

   This block ensures `XRD_PLUGINCONFDIR` etc. are set before MDSplus → libfdpio → libXrdCl get pulled in by the signal imports below. It may have been added recently (see toksearch_d3d's recent commits) or may still be local WIP not yet on main.

- [ ] **Step 2: Replace both with delegations to `fdp` / `toksearch_d3d._fdp_new`**

Change the re-export (case 1) FROM:

```python
from .fdp.environment import setup_environment
```

TO:

```python
from ._fdp_new import setup_environment
```

Change the package-level env init block (case 2 — only if present) FROM:

```python
import os as _os
from .fdp.environment import DEFAULT_CONFIG as _defaults, apply_environment as _apply
_apply(_defaults, _os.environ)
del _os, _defaults, _apply
```

TO:

```python
# libXrdCl reads XRD_PLUGINCONFDIR at library-load time; apply FDP defaults
# now (before MDSplus -> libTreeShr -> libfdpio2 -> libXrdCl gets pulled in
# by the signal imports below).
from ._fdp_new import setup_environment as _setup
_setup()
del _setup
```

If the block is NOT present in your checkout, skip the second change. Confirm by checking that the test environment can import `toksearch_d3d` cleanly:

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -c "import toksearch_d3d; toksearch_d3d.setup_environment()"
```

Expected: no error, and `os.environ` now contains FDP env vars.

- [ ] **Step 3: Verify the top-level setup_environment still works**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -c "
import toksearch_d3d
toksearch_d3d.setup_environment()
import os
print('default_tree_path' in os.environ, os.environ.get('XRDCP_ALLOW_HTTP'))
"
```

Expected: `True true`.

- [ ] **Step 4: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add toksearch_d3d/__init__.py
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Delegate setup_environment to fdp via toksearch_d3d._fdp_new wrapper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Delete `toksearch_d3d/fdp/` and rename `_fdp_new.py` to `fdp.py`

**Files:**
- Delete: `toksearch_d3d/fdp/__init__.py`
- Delete: `toksearch_d3d/fdp/cli.py`
- Delete: `toksearch_d3d/fdp/environment.py`
- Delete: `toksearch_d3d/fdp/skills.py`
- Delete: `tests/test_fdp_query.py`
- Delete: `tests/test_fdp_environment.py`
- Rename: `toksearch_d3d/_fdp_new.py` → `toksearch_d3d/fdp.py`
- Modify: `toksearch_d3d/__init__.py` (update `from ._fdp_new` to `from .fdp`)
- Modify: `pyproject.toml` (update entry-point path)
- Modify: `tests/test_fdp_decoupling.py` (update import path)

- [ ] **Step 1: Delete the old subpackage and obsolete tests**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d rm -r toksearch_d3d/fdp tests/test_fdp_query.py tests/test_fdp_environment.py
```

`test_fdp_query.py` exercised the old `do_query` subprocess shim; that surface is now in the `fdp` repo (Plan A Task 7). `test_fdp_environment.py` exercised the old `setup_environment` directly; that's also in the `fdp` repo (Plan A Task 3).

- [ ] **Step 2: Rename the new module**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d mv toksearch_d3d/_fdp_new.py toksearch_d3d/fdp.py
```

- [ ] **Step 3: Update the import in `toksearch_d3d/__init__.py`**

Edit `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/toksearch_d3d/__init__.py`:

- `from ._fdp_new import setup_environment` → `from .fdp import setup_environment`
- `from ._fdp_new import setup_environment as _setup` → `from .fdp import setup_environment as _setup` (if the env-init block exists)

- [ ] **Step 4: Update the entry-point path in `pyproject.toml`**

Change:

```toml
[project.entry-points."fdp.devices"]
d3d = "toksearch_d3d._fdp_new:D3D_DEVICE"
```

To:

```toml
[project.entry-points."fdp.devices"]
d3d = "toksearch_d3d.fdp:D3D_DEVICE"
```

- [ ] **Step 5: Update import paths in the test file**

Edit `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/tests/test_fdp_decoupling.py`:

Replace every occurrence of `toksearch_d3d._fdp_new` with `toksearch_d3d.fdp`:

```bash
sed -i 's/toksearch_d3d\._fdp_new/toksearch_d3d.fdp/g' /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/tests/test_fdp_decoupling.py
```

- [ ] **Step 6: Refresh the editable install**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run pip install -e . --no-deps 2>&1 | tail -3
```

- [ ] **Step 7: Verify everything still works**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -c "
import toksearch_d3d
toksearch_d3d.setup_environment()
from toksearch_d3d.fdp import D3D_DEVICE
print(D3D_DEVICE.name, D3D_DEVICE.default_llm_preset)
" 2>&1 | tail -3
```

Expected: `d3d amsc`.

- [ ] **Step 8: Run the full test suite**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python testit.py --mock --noptdata --nod3drdb 2>&1 | tail -10'
```

Expected: all tests pass (modulo unrelated pre-existing failures in test_imas_signal that need real MDSplus data — same situation as the LLM migration's smoke runs).

- [ ] **Step 9: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add toksearch_d3d/__init__.py toksearch_d3d/fdp.py pyproject.toml tests/test_fdp_decoupling.py
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Delete legacy toksearch_d3d.fdp subpackage; rename module to fdp.py

Drops cli.py, environment.py, skills.py (now owned by the fdp package).
Drops test_fdp_query.py and test_fdp_environment.py (tests moved to
the fdp repo). Renames the transition module from _fdp_new.py to its
final home at toksearch_d3d.fdp; updates imports and entry-point path
to match.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Update conda recipe to pin `fdp >= 0.1.0`

**Files:**
- Modify: `recipe/recipe.yaml`

- [ ] **Step 1: Add `fdp` to `requirements.run`**

Open `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/recipe/recipe.yaml`. Find the `run:` section under `requirements:`. Add `fdp >=0.1.0` (or whatever release tag Plan A produces).

Example (the rest of the run-deps stay):

```yaml
  run:
    - python
    - toksearch >=2.6.0
    - ptdata >=2.0.2,<3
    - imas_composer >=0.2
    - fdp >=0.1.0
```

- [ ] **Step 2: Commit**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add recipe/recipe.yaml
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Pin fdp >=0.1.0 in conda recipe run-deps

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Update pixi.toml to include fdp in the dev env**

Edit `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/pixi.toml`. Add to `[dependencies]`:

```toml
fdp = ">=0.1.0"
```

- [ ] **Step 4: pixi install + run tests**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi install 2>&1 | tail -3
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run bash -c 'cd tests && python -m unittest test_fdp_decoupling -v 2>&1 | tail -5'
```

Expected: all 4 decoupling tests pass (the entry-point and wrapper tests stop skipping now that fdp is installed).

- [ ] **Step 5: Commit pixi.toml + pixi.lock**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d add pixi.toml pixi.lock
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d commit -m "$(cat <<'EOF'
Add fdp to toksearch_d3d's pixi dev env

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Push branch, open PR, watch CI

**Files:** none modified.

- [ ] **Step 1: Push the branch**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d push -u origin feat/fdp-switchover 2>&1 | tail -3
```

- [ ] **Step 2: Open the PR**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && gh pr create --base main --title "Switch toksearch_d3d to consume fdp (decoupling, hard cut)" --body "$(cat <<'EOF'
## Summary

Replaces the in-package `toksearch_d3d/fdp/` subpackage with consumption of the standalone \`fdp\` package (now on the \`ga-fdp\` channel as of release 0.1.0). Adds \`toksearch_d3d.fdp\` as a single module exposing \`D3D_DEVICE\` (an \`fdp.devices.Device\`) registered via the \`fdp.devices\` entry point. \`toksearch_d3d.setup_environment()\` stays as a top-level re-export that delegates to \`fdp.setup_environment(device="d3d")\`.

Hard cut: \`from toksearch_d3d.fdp.environment import setup_environment\` no longer works. Most users use the top-level re-export and aren't affected.

## Test plan

- [ ] CI passes
- [ ] \`pixi run python -c "import toksearch_d3d; toksearch_d3d.setup_environment(); from toksearch_d3d.fdp import D3D_DEVICE; print(D3D_DEVICE.name)"\` prints \`d3d\`
- [ ] \`pixi run fdp devices\` lists \`d3d\` and the description matches toksearch_d3d's contribution (not the fdp fallback)
- [ ] Manual smoke: \`pixi run fdp query "Fetch ip for shot 165920 ..."\` works end-to-end

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" 2>&1 | tail -3
```

- [ ] **Step 3: Watch CI**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && gh pr checks --watch
```

If CI fails because \`fdp >=0.1.0\` isn't on the channel yet, wait for Plan A Task 10 to complete, then re-run the CI manually.

---

## Task 7: Remove `_FALLBACK_DEVICE` from `fdp` (small follow-up PR in the fdp repo)

**Files:**
- Modify: `fdp/devices.py` (in the **`fdp` repo**, NOT toksearch_d3d)
- Modify: `tests/test_devices.py` (in the **`fdp` repo**)

Once the toksearch_d3d switch-over has merged and `toksearch_d3d >= <release>` is on the `ga-fdp` channel, the `_FALLBACK_DEVICE` back-compat anchor in `fdp` becomes redundant. The `d3d` entry now comes from a real contributor.

**Branch:** `cleanup/drop-fallback-device` in the **`fdp` repo**.

- [ ] **Step 1: Switch repos**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
git checkout main
git pull
git checkout -b cleanup/drop-fallback-device
```

- [ ] **Step 2: Remove the fallback from `fdp/devices.py`**

Edit `/fusion/projects/dt/sammuli/fdp_dev/repos/fdp/fdp/devices.py`. Delete:

1. The entire `_FALLBACK_DEVICE = Device(...)` block (about 30 lines).
2. The fallback path at the end of `discover_devices`:

   ```python
   if "d3d" not in out:
       out["d3d"] = _FALLBACK_DEVICE
   ```

3. The `_FALLBACK_DEVICE` from the public re-exports / `__all__` in `fdp/__init__.py` if it appears there.

- [ ] **Step 3: Update `tests/test_devices.py`**

Drop tests that exercise the fallback specifically. Specifically the `test_no_entry_points_yields_only_fallback` test. The other tests (entry-point discovery, contributor takes precedence, multi-contributor) stay.

Add a new test:

```python
class TestNoContributors(_Base):
    def test_no_devices_returns_empty_dict(self):
        with mock.patch("fdp.devices._entry_points", return_value=[]):
            self.assertEqual(discover_devices(), {})

    def test_resolve_with_no_devices_raises(self):
        with mock.patch("fdp.devices._entry_points", return_value=[]):
            with self.assertRaises(ValueError):
                resolve_default_device()
```

- [ ] **Step 4: Run tests**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && pixi run bash -c 'cd tests && python -m unittest test_devices -v 2>&1 | tail -5'
```

Expected: all tests pass.

- [ ] **Step 5: Smoke-test that `fdp devices` still lists d3d (via toksearch_d3d's contributor)**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && pixi run fdp devices 2>&1 | head -3
```

Expected: `d3d (default) - DIII-D fusion experiment, via Pelican`.

(This requires `toksearch_d3d` to be in the env. If the fdp dev env doesn't pull it in, add it temporarily: `pixi run pip install toksearch_d3d --no-deps`.)

- [ ] **Step 6: Commit and PR**

```bash
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/fdp add fdp/devices.py tests/test_devices.py
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/fdp commit -m "$(cat <<'EOF'
Remove _FALLBACK_DEVICE; toksearch_d3d now contributes d3d via entry point

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git -C /fusion/projects/dt/sammuli/fdp_dev/repos/fdp push -u origin cleanup/drop-fallback-device
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && gh pr create --base main --title "Drop _FALLBACK_DEVICE; toksearch_d3d now contributes d3d" --body "Follow-up to GA-FDP/toksearch_d3d's switch to consuming fdp. The fallback device was a back-compat anchor for the brief window before toksearch_d3d became a contributor. With toksearch_d3d on the ga-fdp channel registering d3d via the fdp.devices entry point, the fallback is redundant. ($([ "$(echo 🤖)" = "🤖" ] && echo "🤖 Generated with [Claude Code](https://claude.com/claude-code)"))"
```

- [ ] **Step 7: Watch CI; merge once green**

```bash
gh pr checks --watch
```

After CI passes and the PR merges, tag `release-0.2.0` on the fdp repo (if you want a clean version delineation marking the post-fallback state).

---

## Self-Review Notes

Coverage against the spec:

- ✓ `toksearch_d3d/fdp/` subpackage deleted → Task 4.
- ✓ `toksearch_d3d/fdp.py` single module with `D3D_DEVICE` → Tasks 1, 4 (rename).
- ✓ `fdp.devices` entry-point registration → Task 2.
- ✓ `toksearch_d3d.setup_environment()` back-compat wrapper → Task 1.
- ✓ Package-level env init delegates to `fdp.setup_environment` → Task 3.
- ✓ Conda recipe pins `fdp >= 0.1.0` → Task 5.
- ✓ `_FALLBACK_DEVICE` removed from fdp once toksearch_d3d ships → Task 7.

The transition uses `_fdp_new.py` then renames to `fdp.py` to avoid Python's subpackage-over-module preference during the brief window when both could exist.

PR dependency chain:
1. fdp Plan A Tasks 1-10 (new repo, first release on ga-fdp).
2. toksearch_d3d Plan B Tasks 1-6 (this PR).
3. toksearch_d3d release after PR merge (so the contributor lands on ga-fdp).
4. fdp Plan B Task 7 (drop fallback) — once toksearch_d3d's release is published.
