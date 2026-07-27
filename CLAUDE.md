# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TokSearch DIII-D (`toksearch_d3d`) is a Python package providing signal retrieval classes for DIII-D fusion experiment data. It builds on the general `toksearch` framework with DIII-D-specific implementations for parallel data retrieval and processing.

## Build & Development

**Environment setup:**
```bash
pixi install
```

**Run tests:**
```bash
pixi run bash -c 'cd tests && python testit.py'
```

Test flags: `--mock` (skip integration tests), `--noptdata` (skip ptdata tests).

**Build conda package (rattler-build):**
```bash
cd recipe && bash run_build.sh
```

`run_build.sh` extracts the version via versioneer before invoking `rattler-build`, because `source: path: ..` copies files without `.git` so versioneer can't resolve the version at build time.

**Versioning:** Uses versioneer with git tags (prefix `release-`). The `versioneer[toml]` pip package must stay in `pyproject.toml` build-system requires so that pixi/uv can resolve the editable install. The vendored `versioneer.py` (v0.29) only reads `setup.cfg`; `versioneer[toml]` patches it to read `pyproject.toml`.

## Architecture

Three main modules exported from `toksearch_d3d/__init__.py`:

- **`toksearch_d3d.signal.ptdata`** — `PtDataSignal` and `RDataSignal` classes wrapping `ptdata.PtDataFetcher` for time-series diagnostic data. Inherits from `toksearch.Signal`.
- **`toksearch_d3d.signal.cake`** — `CakeSignal` for equilibrium/profile data from MDSplus with SQLite database lookup. Inherits from `toksearch.MdsSignal`. Currently disabled in tests (needs rework away from sqlite).
- **`toksearch_d3d.data`** — Ships `d3d.yaml`, the D3D tokamak catalog,
  declared via the `fdp_schema.catalogs` entry-point group. Consumed by
  `fdp.catalog` at runtime; replaces the old `fdp.devices` entry-point
  contribution.
- **IMAS** — `ImasSignal` was split out into the separate `toksearch_imas`
  package (`ga-fdp` channel) as of 0.11.0. There is **no back-compat shim**
  here. The dependency arrow points `toksearch_imas → toksearch_d3d` (it needs
  `PtDataSignal` and the FDP env bootstrap), not the other way round — do not
  add an `imas_composer` dependency back to this package.
- **`toksearch_d3d.fdp`** — Thin back-compat shim exposing `setup_environment()`,
  which delegates to `fdp.setup_environment(device="d3d", ...)`. The `fdp` CLI
  itself now lives in the separate `fdp` package.

## Key Dependencies

- `toksearch >=2.4` — Base Signal classes and parallel framework
- `ptdata >=1.4` — PTData diagnostic data fetcher (with libfdpio/Pelican support)
- `fdp_schema` — Pydantic schema for tokamak catalog entries; `toksearch_d3d` contributes `d3d.yaml` via the `fdp_schema.catalogs` entry-point group
- Conda channels: `ga-fdp`, `conda-forge`

## Pelican/OSDF Configuration

The `fdp` CLI (from the `fdp` package, configured via `fdp.catalog["d3d"]`) sets environment variables for Pelican object store access at `pelican://osg-htc.org:443/fdp-d3d/`. Key variables: `XRD_PLUGINCONFDIR`, `XRDCP_ALLOW_HTTP`, `XRD_PELICANUSEAUTHHEADERS`, `BEARER_TOKEN`, `PTDATA_LOC=1`, `PTDATA_JSON_INDEX_DIR`. The D3D catalog entry (`d3d.yaml`) is contributed by `toksearch_d3d.data` via the `fdp_schema.catalogs` entry-point group.

## Build Files

- `pixi.toml` — Workspace config (uses `[workspace]` not `[project]`)
- `pyproject.toml` — Package metadata, entry points, versioneer config
- `recipe/recipe.yaml` — rattler-build recipe (replaces old meta.yaml)
- `recipe/variants.yaml` — Python 3.11 and 3.12 variants
- `recipe/run_build.sh` — Wrapper that sets PKG_VERSION before rattler-build
