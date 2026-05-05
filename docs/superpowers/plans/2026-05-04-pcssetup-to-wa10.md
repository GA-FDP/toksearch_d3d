# pcssetup-to-wa10 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `pcssetup-to-wa10` console script to `toksearch_d3d` that fetches the `PCSSETUP` pointname for a given shot and writes its raw bytes to a `.wa10` file on disk.

**Architecture:** New `toksearch_d3d.tools` subpackage with one module (`pcssetup_to_wa10.py`) split into a thin importable library function (`pcssetup_bytes(shot) -> bytes`) and an argparse-based `main(argv) -> int`. Wired up via `[project.scripts]` in `pyproject.toml`.

**Tech Stack:** Python 3.9+, `toksearch_d3d.PtDataSignal` (which now flows through `ptdata 2.0.3`), argparse, unittest. Tests run under the existing `fdp run python testit.py` flow.

**Spec:** `docs/superpowers/specs/2026-05-04-pcssetup-to-wa10-design.md`

---

## File Structure

- **Create** `toksearch_d3d/tools/__init__.py` — empty marker for the new subpackage.
- **Create** `toksearch_d3d/tools/pcssetup_to_wa10.py` — `pcssetup_bytes(shot)` + `main(argv)`.
- **Create** `tests/test_pcssetup_to_wa10.py` — unittest cases that exercise both functions against a real shot under `fdp run`.
- **Modify** `pyproject.toml` — add `pcssetup-to-wa10` script entry and `toksearch_d3d.tools` to the packages list.

---

## Task 1: Library function `pcssetup_bytes(shot)` (TDD)

**Files:**
- Create: `toksearch_d3d/tools/__init__.py`
- Create: `toksearch_d3d/tools/pcssetup_to_wa10.py`
- Create: `tests/test_pcssetup_to_wa10.py`

- [ ] **Step 1.1: Write the failing test for `pcssetup_bytes`**

Create `tests/test_pcssetup_to_wa10.py` with:

```python
# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Tests for the pcssetup-to-wa10 console script.

Requires a configured FDP environment (run via `fdp run python testit.py`).
Targets shot 165920, the same shot the existing PtDataSignal tests use.
"""

import unittest
from pathlib import Path

SHOT = 165920
# PCSSETUP wa10 files are typically a few megabytes. 500 KB is well below
# the typical payload but well above any plausible header-only / parse-
# failure false positive.
MIN_REASONABLE_SIZE = 500_000


class TestPcssetupBytes(unittest.TestCase):
    def test_returns_realistic_size(self):
        """pcssetup_bytes returns the wa10 payload as bytes (a few MB)."""
        from toksearch_d3d.tools.pcssetup_to_wa10 import pcssetup_bytes

        b = pcssetup_bytes(SHOT)

        self.assertIsInstance(b, bytes)
        self.assertGreater(len(b), MIN_REASONABLE_SIZE)
```

- [ ] **Step 1.2: Run the test to verify it fails**

Run:
```bash
cd tests && pixi run fdp run python -m unittest test_pcssetup_to_wa10 -v
```

Expected: ImportError / ModuleNotFoundError for `toksearch_d3d.tools.pcssetup_to_wa10`.

- [ ] **Step 1.3: Create the empty subpackage marker**

Create `toksearch_d3d/tools/__init__.py` as an empty file (no content needed; it just marks the directory as a Python package).

- [ ] **Step 1.4: Implement `pcssetup_bytes`**

Create `toksearch_d3d/tools/pcssetup_to_wa10.py` with:

```python
# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
pcssetup-to-wa10: extract the PCSSETUP pointname for a shot and write
the raw bytes to a .wa10 file -- the inverse of the PCS-side write that
stores the wa10 file in PTDATA at shot start.

Working assumption: PCSSETUP's data payload is byte-for-byte identical
to the original wa10 file. See
docs/superpowers/specs/2026-05-04-pcssetup-to-wa10-design.md.
"""

from toksearch_d3d import PtDataSignal


def pcssetup_bytes(shot: int) -> bytes:
    """Return the raw PCSSETUP bytes for ``shot`` as a single ``bytes`` blob.

    The returned bytes are assumed to be the original wa10 file contents
    written into PTDATA by PCS at shot start.
    """
    result = PtDataSignal("PCSSETUP").fetch(int(shot))
    return result["data"].tobytes()
```

- [ ] **Step 1.5: Run the test to verify it passes**

Run:
```bash
cd tests && pixi run fdp run python -m unittest test_pcssetup_to_wa10 -v
```

Expected: `test_returns_realistic_size ... ok` (the fetch may take a few seconds).

- [ ] **Step 1.6: Commit**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git add toksearch_d3d/tools/__init__.py toksearch_d3d/tools/pcssetup_to_wa10.py tests/test_pcssetup_to_wa10.py
git commit -m "feat: add pcssetup_bytes library function for wa10 extraction"
```

---

## Task 2: CLI wrapper `main(argv)` (TDD)

**Files:**
- Modify: `tests/test_pcssetup_to_wa10.py`
- Modify: `toksearch_d3d/tools/pcssetup_to_wa10.py`

- [ ] **Step 2.1: Add the failing test for `main`**

Append to `tests/test_pcssetup_to_wa10.py`:

```python
import io
import tempfile
from contextlib import redirect_stderr, redirect_stdout


class TestMain(unittest.TestCase):
    def test_writes_file_with_default_name(self):
        """main(["<shot>"]) writes <shot>.wa10 in cwd, returns 0."""
        from toksearch_d3d.tools.pcssetup_to_wa10 import main, pcssetup_bytes

        expected = pcssetup_bytes(SHOT)

        with tempfile.TemporaryDirectory() as td:
            cwd = Path.cwd()
            try:
                import os
                os.chdir(td)
                with redirect_stdout(io.StringIO()):
                    rc = main([str(SHOT)])
            finally:
                os.chdir(cwd)

            out = Path(td) / f"{SHOT}.wa10"
            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())
            self.assertEqual(out.stat().st_size, len(expected))

    def test_writes_file_with_explicit_output(self):
        """main(["<shot>", "-o", path]) writes to that path, returns 0."""
        from toksearch_d3d.tools.pcssetup_to_wa10 import main, pcssetup_bytes

        expected = pcssetup_bytes(SHOT)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "custom.wa10"
            with redirect_stdout(io.StringIO()):
                rc = main([str(SHOT), "-o", str(out)])

            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())
            self.assertEqual(out.stat().st_size, len(expected))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2.2: Run the tests to verify they fail**

Run:
```bash
cd tests && pixi run fdp run python -m unittest test_pcssetup_to_wa10 -v
```

Expected: the two new `TestMain.*` cases fail with `ImportError` (`main` not yet defined). The `TestPcssetupBytes.test_returns_realistic_size` from Task 1 should still pass.

- [ ] **Step 2.3: Implement `main`**

Append to `toksearch_d3d/tools/pcssetup_to_wa10.py`:

```python
import argparse
import sys
from pathlib import Path

from ptdata import PtDataError


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``pcssetup-to-wa10``.

    Returns the int exit code so tests can drive it without ``sys.exit``.
    """
    parser = argparse.ArgumentParser(
        prog="pcssetup-to-wa10",
        description=(
            "Fetch the PCSSETUP pointname for a shot and write the raw "
            "bytes to a .wa10 file. Run under `fdp run`."
        ),
    )
    parser.add_argument("shot", type=int, help="shot number")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="output path (default: <shot>.wa10 in cwd)",
    )
    args = parser.parse_args(argv)

    out_path = args.output or Path(f"{args.shot}.wa10")

    try:
        data = pcssetup_bytes(args.shot)
    except PtDataError as e:
        print(f"error: PCSSETUP fetch failed for shot {args.shot}: {e}",
              file=sys.stderr)
        return 1

    try:
        out_path.write_bytes(data)
    except OSError as e:
        print(f"error: could not write {out_path}: {e}", file=sys.stderr)
        return 1

    print(f"wrote {len(data)} bytes to {out_path}")
    return 0
```

- [ ] **Step 2.4: Run the tests to verify they pass**

Run:
```bash
cd tests && pixi run fdp run python -m unittest test_pcssetup_to_wa10 -v
```

Expected: all three test cases pass.

- [ ] **Step 2.5: Commit**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git add toksearch_d3d/tools/pcssetup_to_wa10.py tests/test_pcssetup_to_wa10.py
git commit -m "feat: add pcssetup-to-wa10 CLI main()"
```

---

## Task 3: Wire up the console script

**Files:**
- Modify: `pyproject.toml` (currently `pyproject.toml:31-35`)

- [ ] **Step 3.1: Add the script entry and subpackage**

In `pyproject.toml`, update the `[project.scripts]` block and the `[tool.setuptools]` `packages` list:

```toml
[project.scripts]
fdp = "toksearch_d3d.fdp.cli:main"
pcssetup-to-wa10 = "toksearch_d3d.tools.pcssetup_to_wa10:main"

[tool.setuptools]
packages = ["toksearch_d3d", "toksearch_d3d.fdp", "toksearch_d3d.signal", "toksearch_d3d.tools"]
zip-safe = false
```

- [ ] **Step 3.2: Reinstall in editable mode and verify the entry point**

Run:
```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
pixi run pip install --no-deps --no-build-isolation -e .
pixi run which pcssetup-to-wa10
pixi run pcssetup-to-wa10 --help
```

Expected: `which` prints the env's bin path; `--help` prints the argparse usage with `shot` and `-o/--output`.

- [ ] **Step 3.3: Smoke-test end-to-end against the test shot**

Run:
```bash
cd /tmp && pixi --manifest-path /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/pixi.toml run fdp run pcssetup-to-wa10 165920 -o /tmp/165920.wa10
ls -la /tmp/165920.wa10
```

Expected: prints `wrote N bytes to /tmp/165920.wa10` where N is in the multi-megabyte range; the file exists with that size.

Clean up: `rm /tmp/165920.wa10`.

- [ ] **Step 3.4: Run the full toksearch_d3d test suite**

Run:
```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/tests && pixi run fdp run python testit.py
```

Expected: all tests pass (existing 54 + the 3 new pcssetup tests = 57). No regressions.

- [ ] **Step 3.5: Commit**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git add pyproject.toml
git commit -m "build: register pcssetup-to-wa10 console script"
```

---

## Self-review checklist (for the plan author)

Before handing off:

- [ ] **Spec coverage:**
  - "CLI surface: `pcssetup-to-wa10 <shot> [-o <path>]`" → Task 2 (argparse) + Task 3 (entry point).
  - "Default output `<shot>.wa10` in cwd" → Task 2.3 (`out_path = args.output or Path(f"{args.shot}.wa10")`) + Task 2.1 test.
  - "Module layout: `toksearch_d3d/tools/{__init__.py, pcssetup_to_wa10.py}`" → Tasks 1.3, 1.4.
  - "`pcssetup_bytes(shot) -> bytes` importable" → Task 1.4.
  - "`main(argv=None) -> int`" → Task 2.3.
  - "Catches PtDataError and OSError, prints one-line stderr, exit 1" → Task 2.3.
  - "Prints `wrote N bytes to <path>` on success" → Task 2.3.
  - "Tests under fdp run, shot 165920, size > 500 KB" → Task 1.1 + Task 2.1.
  - "`pyproject.toml` script entry + packages list" → Task 3.1.
  - "No CHANGELOG section" → not in plan; correct.

- [ ] **No placeholders.** All code blocks contain runnable code; all commands have explicit expected output.

- [ ] **Type consistency.** Function name `pcssetup_bytes` matches across all tasks. CLI arg `--output` and attribute `args.output` consistent. Exit codes (`0`, `1`) used consistently.
