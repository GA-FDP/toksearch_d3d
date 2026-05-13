# FDP `setup_environment` — Design

**Date:** 2026-05-12
**Status:** Approved, ready for plan

## Problem

The FDP environment (XRootD plugin paths, MDSplus tree paths, PTData
configuration, bearer token) is currently configured only as a side effect of
running `fdp run <cmd>`. A user who wants to write a Python script that uses
`PtDataSignal`, `MdsSignal`, etc. without going through the CLI wrapper has no
clean way to apply the same environment — the setup logic lives inline in
`toksearch_d3d.fdp.cli.main()`.

## Goal

Expose a Python-callable function that mirrors what `fdp run` does to the
environment, so a script can be self-contained:

```python
from toksearch_d3d import setup_environment
setup_environment()

from toksearch_d3d import PtDataSignal
PtDataSignal('ip').fetch(202161)
```

## Non-Goals

- No support for "delete this env var" semantics. `None`-valued kwargs are not
  treated specially in this pass.
- No alternative "return a dict instead of mutating `os.environ`" mode. A
  single, side-effect form is enough for the use case.
- No new CLI behavior. The `fdp` CLI keeps working exactly as it does today.

## Architecture

Split the FDP module so environment concerns live separately from CLI concerns.
The CLI imports from the environment module; no duplication.

```
toksearch_d3d/fdp/
    environment.py   # NEW — DEFAULT_CONFIG, setup_environment, helpers
    cli.py           # argparse + subcommand dispatch + FdpFileSystem
    skills.py        # unchanged
    __init__.py      # re-exports setup_environment
```

### `toksearch_d3d/fdp/environment.py` (new)

Owns:

- `OSDF_SERVER`, `ORIGIN_SERVER`, `FDP_ROOT`, `ARCHIVES_DIR` constants
- `get_default_xrd_pluginconfdir()` helper
- `DEFAULT_CONFIG` dict
- `apply_environment(config, env)` helper (unchanged behavior)
- `setup_environment(bearer_token=None, **overrides)` — new public function

This module must not import `XRootD` or `subprocess` — importing it should be
cheap.

### `toksearch_d3d/fdp/cli.py` (edit)

- Drop the moved definitions; import them from `.environment`.
- Replace the inline env-setup block in `main()` (current lines 400-413) with a
  single call to `setup_environment(bearer_token=args.bearer_token or None)`.
- `FdpFileSystem` stays here — it's CLI-adjacent and uses `XRootD` directly.

### `toksearch_d3d/fdp/__init__.py` (edit)

```python
from .environment import setup_environment
```

### `toksearch_d3d/__init__.py` (edit)

Add at the bottom:

```python
from .fdp import setup_environment
```

Update the module docstring with a short "Python-side environment setup"
section that shows the one-liner.

## `setup_environment` Specification

```python
def setup_environment(bearer_token: str | None = None, **overrides) -> None:
    """Populate os.environ with FDP variables and resolve BEARER_TOKEN.

    Defaults from DEFAULT_CONFIG are applied with setdefault semantics —
    existing env vars are preserved, except PATH which is overwritten to
    prepend the active env's bin/ directory.

    Keyword overrides force-set the corresponding env vars, winning over both
    DEFAULT_CONFIG and any existing os.environ value. Values are stringified
    via str().

    Bearer token resolution (first match wins):
      1. bearer_token argument (if truthy)
      2. os.environ['BEARER_TOKEN'] after defaults+overrides applied
      3. contents of ~/.fdp/token (whitespace-stripped)
    Warns via warnings.warn(...) if none resolves to a non-empty value.

    Returns None. Mutates os.environ in place. Safe to call multiple times.

    Example:
        from toksearch_d3d import setup_environment
        setup_environment(PTDATA_LOC="2")
    """
```

### Precedence summary (highest first)

| Source | Applies to |
|---|---|
| `bearer_token=` arg | `BEARER_TOKEN` only |
| `**overrides` kwargs | Any env var passed as a kwarg |
| Existing `os.environ` | All non-overridden, non-PATH vars |
| `DEFAULT_CONFIG` PATH | `PATH` (unconditional unless overridden) |
| `DEFAULT_CONFIG` defaults | All other vars not already set |

### Implementation sketch

```python
import os
import warnings
from pathlib import Path

# ... DEFAULT_CONFIG, apply_environment, etc. ...

def setup_environment(bearer_token=None, **overrides):
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

## CLI Refactor

`toksearch_d3d/fdp/cli.py::main()` — replace this block:

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
        warnings.warn("No BEARER_TOKEN specified. ...")

os.environ["BEARER_TOKEN"] = bearer_token
#######################################################
```

with:

```python
setup_environment(bearer_token=args.bearer_token or None)
```

`do_env` continues to print from `DEFAULT_CONFIG` (now imported from
`.environment`); no behavior change.

`do_run` still calls `subprocess.run(..., env=os.environ)` after
`setup_environment` has populated it.

## Testing Plan

Manual smoke tests run from the `toksearch_d3d/` directory inside the pixi env:

1. **Python-side path (the new entry point).** Open `pixi run python`:
   ```python
   from toksearch_d3d import setup_environment, PtDataSignal
   setup_environment()
   PtDataSignal('ip').fetch(202161)  # returns dict with 'data'/'times'
   ```
2. **Override path.** Verify a kwarg wins over an existing env var:
   ```python
   import os
   os.environ["PTDATA_LOC"] = "9"
   from toksearch_d3d import setup_environment
   setup_environment(PTDATA_LOC="1")
   assert os.environ["PTDATA_LOC"] == "1"
   ```
3. **Bearer token fallback.** With `BEARER_TOKEN` unset and `~/.fdp/token`
   present, confirm `os.environ["BEARER_TOKEN"]` is populated after calling.
4. **CLI regression.** `pixi run fdp run python -c "import os; print(os.environ['XRD_PLUGINCONFDIR'])"` still prints the expected path.
5. **`fdp env` regression.** `pixi run fdp env` output is unchanged (compare
   against git HEAD before the refactor).

The existing test runner (`tests/testit.py`) should continue to pass — no
public CLI semantics change.

## Risks & Rollback

- **Import cycle risk:** `fdp/__init__.py` will import from `.environment`;
  `cli.py` will also import from `.environment`. No cycle since `environment`
  imports nothing from `cli` or the package root.
- **Forgotten constant:** if a CLI subcommand still references a symbol that
  moved (e.g. `ORIGIN_SERVER` used by `do_ls`), tests will catch it. Verify
  with a quick grep after the move.
- **Rollback:** the refactor is purely structural; reverting is a single git
  revert.
