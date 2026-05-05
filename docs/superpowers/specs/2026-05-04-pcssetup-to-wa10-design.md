# pcssetup-to-wa10 — design

Date: 2026-05-04
Status: Draft

## Goal

Add a console script to `toksearch_d3d` that fetches the `PCSSETUP`
pointname for a given shot and writes its raw bytes to a `.wa10`
file on disk — the inverse of the PCS-side process that writes a
`wa10` binary into PTDATA at shot start.

## Background

When a DIII-D shot starts, PCS records its setup as a binary `wa10`
file and writes that file's contents into PTDATA under the
`PCSSETUP` pointname. PCS users occasionally need to recover the
original `wa10` for an old shot — currently there is no toksearch_d3d
tool that does this.

PCSSETUP `wa10` files are typically a few megabytes.

## Working assumption

The `data` payload returned by `PtDataSignal('PCSSETUP').fetch(shot)`
is byte-for-byte identical to the original `wa10` file contents. We
estimate ~90% confidence in this and have no canonical reference
`wa10` to diff against today; the script is built on this assumption
and a `--verify` flag can be added later when a reference becomes
available.

## CLI surface

A new top-level console script registered in `pyproject.toml`:

```
pcssetup-to-wa10 <shot> [-o <output_path>]
```

- `<shot>`: required, integer shot number.
- `-o/--output`: optional output path. Default: `<shot>.wa10` in cwd.

Single shot per invocation; batch is left to the shell. Exit 0 on
success; exit 1 with a one-line stderr message if the fetch fails
(e.g. `error: PCSSETUP not found for shot 165920`).

The script must be invoked under a configured FDP environment
(typically `fdp run pcssetup-to-wa10 ...`), the same as the rest of
toksearch_d3d's data-access tooling.

## Module layout

- `toksearch_d3d/tools/__init__.py` — new, empty.
- `toksearch_d3d/tools/pcssetup_to_wa10.py` — new module.
  - `pcssetup_bytes(shot: int) -> bytes` — importable library
    function. Calls
    `toksearch_d3d.PtDataSignal('PCSSETUP').fetch(shot)` and
    returns `result['data'].tobytes()`.
  - `main(argv: list[str] | None = None) -> int` — argparse-based
    CLI entry point. Wraps `pcssetup_bytes`, handles I/O, prints
    `wrote N bytes to <path>` on success, returns the int exit
    code. Catches `PtDataError` (and `OSError` on write) to emit a
    one-line stderr message instead of a traceback.

`pyproject.toml` changes:

- `[project.scripts]` adds:
  ```
  pcssetup-to-wa10 = "toksearch_d3d.tools.pcssetup_to_wa10:main"
  ```
- `[tool.setuptools] packages` list adds `toksearch_d3d.tools`.

## Tests

`tests/test_pcssetup_to_wa10.py`, runnable under the existing
`fdp run python testit.py` flow:

- `test_pcssetup_bytes_returns_realistic_size`: assert
  `pcssetup_bytes(SHOT)` returns `bytes` with `len(b) > 500_000`.
  500 KB is well below the typical "few MB" payload but well above
  any plausible header-only / parse-failure false positive.
- `test_main_writes_file`: invoke `main([str(SHOT), "-o",
  str(tmp_path)])`, assert exit code 0 and that the file exists
  with size equal to `len(pcssetup_bytes(SHOT))`.

Pick a shot that is known-old enough to have stable PCSSETUP data
across the test horizon (the existing PtDataSignal tests use shot
`165920`, which works here too).

No fixtures committed to the repo; data is fetched from FDP at
runtime, same as the existing `test_ptdata_signal.py` suite.

## Out of scope

- `--verify <ref.wa10>` — easy to add later when a reference `wa10`
  is available; defer to keep the initial surface minimal.
- Multi-shot batch mode — shell loops are sufficient.
- Round-trip verification (write a `wa10`, push it back into PTDATA,
  read it back, compare) — purely a read-side tool.

## Open risks

- **Working assumption may be wrong.** If the PCSSETUP payload has
  any header/transform around the wa10 bytes, the produced file
  will not be byte-identical to the original. Mitigation: the
  `--verify` flag (deferred) is one line of comparison; users with
  a reference can validate immediately. Until then, a >500 KB size
  check at least catches the empty/header-only failure mode.
