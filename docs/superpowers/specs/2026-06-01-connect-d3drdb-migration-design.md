# `connect_d3drdb` Migration — Design

**Date:** 2026-06-01
**Status:** Approved, ready for plan
**Context:** Resolves the `connect_d3drdb` Non-Goal from the Phase 1
fdp-schema design at
`toksearch_d3d/docs/superpowers/specs/2026-06-01-fdp-schema-design.md`.

## Problem

`toksearch.sql.mssql.connect_d3drdb()` is a D3D-specific function that
lives in the generic `toksearch` package. It carries hardcoded defaults
for the D3D shot-metadata database (`host="d3drdb.gat.com"`, `port=8001`,
`db="d3drdb"`, password file at `~/D3DRDB.sybase_login`). Those defaults
duplicate the `SqlLocator` block in `toksearch_d3d/data/d3d.yaml`. Phase 1
of the fdp-schema migration could not unify the two sources of truth and
shipped a sync test in `toksearch_d3d/tests/test_sql_sync.py` as a
stopgap, with the duplication tracked as follow-up work.

Three problems with the current state:

1. **Two sources of truth.** Changing the D3D database host requires
   editing both `connect_d3drdb`'s defaults and `d3d.yaml`. The sync test
   catches drift but doesn't prevent it.
2. **D3D-specific code in a device-neutral package.** `toksearch` is the
   general signal-retrieval framework; `connect_d3drdb` is by name only
   useful when the D3D database is reachable. The function is in the
   wrong package.
3. **No path for other tokamaks.** A future KSTAR or JET catalog cannot
   reuse the SQL plumbing; each would need a parallel hardcoded helper.

## Goals

Three packages change. No new cycles. The catalog becomes the single
source of truth for D3D SQL connection metadata.

- **`toksearch.sql.mssql`** gains a generic, device-neutral helper
  `connect_tokamak_sql(tokamak, name="main", **overrides)` that reads
  the catalog via `fdp_schema` and connects via `pymssql`. The existing
  `connect_d3drdb` symbol stays as a deprecation shim that lazily
  delegates to `toksearch_d3d.sql.connect_d3drdb`.
- **`toksearch_d3d.sql`** is a new flat module exposing `connect_d3drdb`
  as a one-liner over the generic API, pinning `tokamak="d3d"` and
  `name="d3drdb"`.
- **`toksearch_d3d/tests/test_sql_sync.py`** is deleted — the catalog is
  now the only source of truth, so drift cannot happen.

After the change, the dep graph gains one edge:

```
fdp_schema   toksearch       (new edge: toksearch → fdp_schema)
    ▲          ▲    ▲
    └──┬───────┘    │
       │            │
      fdp     toksearch_d3d
       ▲            ▲
       └──────┬─────┘
              │
         fdp_installer
```

`toksearch → fdp_schema` is acyclic; `fdp_schema` has no GA-FDP deps.
Every toksearch install gains pydantic v2 + pyyaml as transitive deps
(~5–10 MB). Accepted as the cost of single-source-of-truth.

## Non-Goals

- **`fdp_schema.discover_catalogs()` extraction.** Both
  `fdp.catalog._discover` and the new `toksearch.sql.mssql._discover_catalogs`
  would naturally consume such a helper. The duplication is ~10 lines;
  the right end state is a single helper in `fdp_schema`, but folding
  that refactor in here unnecessarily widens scope. Future cleanup.
- **Non-mssql SQL drivers.** Postgres/sqlite stay raising
  `NotImplementedError` (matches the Phase 1 SqlResolver scope).
- **Migration of in-repo call sites away from
  `toksearch.sql.mssql.connect_d3drdb`.** The deprecation shim keeps the
  ~25 ecosystem call sites working unchanged. A separate follow-up can
  `sed`-rewrite the imports.
- **Removal of the deprecation shim from `toksearch.sql.mssql`.** Stays
  through one toksearch minor cycle (e.g., `2.7.x` through `2.8.x`),
  removed in `2.9.0`. The removal is its own small PR.
- **Multi-`SqlLocator` selection logic.** v1 picks by exact `name=`; if
  a tokamak ships multiple SQL locators they're disambiguated via the
  `name` kwarg. No fuzzy matching, no "default" mechanism beyond `name="main"`.
- **Cache invalidation.** `functools.cache` is process-lifetime; restart
  to pick up new entry points. Matches `fdp.catalog` behavior.

## Architecture

### Package boundaries

**Changed: `toksearch`**
- `toksearch/toksearch/sql/mssql.py` rewritten:
  - New: `connect_tokamak_sql(tokamak, name="main", **overrides)`.
  - New: module-private `_discover_catalogs()` with `functools.cache`.
  - Kept: `connect_d3drdb` as a deprecation shim that lazily delegates
    to `toksearch_d3d.sql.connect_d3drdb`.
  - Deleted: `USERNAME`/`DEFAULT_PASSWORD_FILE` module-level constants
    and the `_read_sybase_login_file` helper (folded into
    `connect_tokamak_sql`).
- `toksearch/recipe/recipe.yaml`: add `fdp-schema >=0.1.1` to `run:`.
- `toksearch/pyproject.toml`: optional pip dep (only if toksearch ships
  via PyPI; current GA-FDP convention is conda-only — confirm during plan).
- `toksearch/tests/test_sql.py`: extend with `connect_tokamak_sql` cases.
- `toksearch/tests/test_sql_deprecation.py`: new file testing the shim.

**Changed: `toksearch_d3d`**
- New file `toksearch_d3d/toksearch_d3d/sql.py` exposing `connect_d3drdb`.
- New file `toksearch_d3d/tests/test_sql.py` smoke-testing the wrapper.
- Deleted: `toksearch_d3d/tests/test_sql_sync.py` (the Phase 1 stopgap).

**Unchanged: `fdp_schema`, `fdp`, `fdp_installer`.**

### Versioning

- `toksearch` minor bump (gains new public API + new run-dep). Per the
  current release cadence: `2.7.4 → 2.8.0`.
- `toksearch_d3d` patch bump (new module, no breaking changes):
  `0.9.2 → 0.9.3`.

## Generic API: `connect_tokamak_sql`

In `toksearch/toksearch/sql/mssql.py`:

```python
def connect_tokamak_sql(
    tokamak: str,
    name: str = "main",
    *,
    host: str | None = None,
    port: int | None = None,
    db: str | None = None,
    username: str | None = None,
    password: str | None = None,
    password_file: str | None = None,
):
    """Connect to a tokamak's SQL database, reading defaults from the
    catalog contributed via the `fdp_schema.catalogs` entry-point group.

    `tokamak` selects the tokamak by its registered name (e.g., "d3d").
    `name` selects the SqlLocator within that tokamak (D3D's is
    "d3drdb"). All kwargs override the catalog's value for the matching
    field.

    Credential resolution:
      1. Explicit `password` kwarg wins.
      2. Otherwise `password_file` (kwarg, else locator's auth.path).
      3. If neither resolves, raise RuntimeError.

    Driver scope: only `driver == "mssql"` is supported in v1. Anything
    else raises NotImplementedError.

    Raises:
      KeyError: unknown tokamak, or no SqlLocator with the given name.
      NotImplementedError: locator's driver is not "mssql".
      RuntimeError: no credential source resolvable.
    """
    catalogs = _discover_catalogs()
    if tokamak not in catalogs:
        raise KeyError(
            f"No tokamak named {tokamak!r}. Available: {sorted(catalogs)}"
        )
    tk = catalogs[tokamak]
    sqls = [l for l in tk.locators if l.kind == "sql" and l.name == name]
    if not sqls:
        avail = sorted(l.name for l in tk.locators if l.kind == "sql")
        raise KeyError(
            f"No sql locator named {name!r} on tokamak {tokamak!r}. "
            f"Available: {avail}"
        )
    loc = sqls[0]

    if loc.driver != "mssql":
        raise NotImplementedError(
            f"connect_tokamak_sql: driver={loc.driver!r} on locator "
            f"{name!r} is not supported in v1; only 'mssql' is implemented."
        )

    # tdsver is set via env var (FreeTDS reads it); setdefault preserves
    # any pre-existing value.
    if loc.tdsver:
        os.environ.setdefault("TDSVER", loc.tdsver)

    eff_host = host if host is not None else loc.host
    eff_port = port if port is not None else loc.port
    eff_db   = db   if db   is not None else loc.database

    if password is None:
        username, password = _resolve_credential(
            username, loc, password_file
        )
    elif username is None:
        # Explicit password but no username: preserve Phase 1's
        # `username=USERNAME` (current OS user) default. The original
        # `connect_d3drdb` signature defaulted username to
        # `getpass.getuser()` so explicit-password callers without an
        # explicit username don't pass `None` to pymssql.
        import getpass
        username = getpass.getuser()

    return pymssql.connect(
        eff_host, username, password, eff_db,
        port=str(eff_port) if eff_port else None,
    )


def _resolve_credential(
    username: str | None, loc, password_file_override: str | None,
) -> tuple[str, str]:
    """Resolve (username, password) for an mssql SqlLocator.

    Reads a two-line password file (username on line 1, password on
    line 2) from `password_file_override` if given, else from
    `loc.auth.path`. Returns the file's username if `username` arg is
    None.
    """
    pf = password_file_override
    if pf is None and loc.auth and loc.auth.kind == "password_file":
        pf = loc.auth.path
    if not pf:
        raise RuntimeError(
            f"No credential source for locator {loc.name!r}. "
            f"Pass `password=` explicitly, or provide a password_file "
            f"(catalog auth.path or `password_file=` kwarg)."
        )
    text = pathlib.Path(os.path.expanduser(pf)).read_text()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    file_user, file_pass = lines[0], lines[1]
    return (username or file_user), file_pass
```

**Argument naming note:** `db=` (not `database=`) matches the legacy
`connect_d3drdb` kwarg name; the function translates `db` to the
catalog's `database` field internally. The one in-tree caller of
`connect_d3drdb(db="code_rundb")` keeps working unchanged.

## D3D Wrapper and Deprecation Shim

### New: `toksearch_d3d/toksearch_d3d/sql.py`

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""D3D-specific SQL helpers. Thin wrappers over toksearch.sql.mssql
that pin the tokamak name; everything else is delegated to the
generic API."""

from toksearch.sql.mssql import connect_tokamak_sql


def connect_d3drdb(**overrides):
    """Connect to the D3D shot-metadata database.

    Reads host/port/database from the d3d.yaml SqlLocator(name='d3drdb').
    Keyword overrides match `connect_tokamak_sql`. Pre-existing callers
    like `connect_d3drdb(db='code_rundb')` keep working unchanged.
    """
    return connect_tokamak_sql("d3d", "d3drdb", **overrides)


__all__ = ["connect_d3drdb"]
```

### Changed: `toksearch/toksearch/sql/mssql.py` (the deprecation shim)

```python
import warnings


def connect_d3drdb(**overrides):
    """Deprecated. Use `toksearch_d3d.sql.connect_d3drdb` (or the generic
    `connect_tokamak_sql('d3d', 'd3drdb', **overrides)`) instead."""
    warnings.warn(
        "toksearch.sql.mssql.connect_d3drdb is deprecated. Use "
        "toksearch_d3d.sql.connect_d3drdb instead (or "
        "toksearch.sql.mssql.connect_tokamak_sql for non-D3D tokamaks).",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        from toksearch_d3d.sql import connect_d3drdb as _impl
    except ImportError as e:
        raise ImportError(
            "toksearch.sql.mssql.connect_d3drdb requires toksearch_d3d "
            "to be installed. Either `conda install toksearch_d3d` or "
            "migrate to toksearch.sql.mssql.connect_tokamak_sql."
        ) from e
    return _impl(**overrides)
```

Key properties:

- **Lazy import of `toksearch_d3d.sql`** — inside the function body, not
  at module top. `import toksearch.sql.mssql` does not pull in
  `toksearch_d3d`; the cycle direction stays clean. The import only fires
  when someone actually calls the deprecated symbol.
- **Helpful failure mode** when `toksearch_d3d` isn't installed —
  `ImportError` with concrete remediation pointing at either install or
  the generic API.
- **No `toksearch` run-dep on `toksearch_d3d`.** The lazy import is a
  soft runtime coupling, not a declared dependency.

## Catalog Discovery in `toksearch`

`connect_tokamak_sql` discovers tokamak catalogs without importing
`fdp.catalog` (importing that would route back through toksearch via the
LLM CLI shims and complete a cycle at module-load time). The discovery
uses `fdp_schema`'s public surface directly:

```python
# In toksearch/toksearch/sql/mssql.py
import functools
import os
import pathlib
from importlib.metadata import entry_points

import pymssql
from fdp_schema import load_tokamak


@functools.cache
def _discover_catalogs() -> dict[str, "fdp_schema.Tokamak"]:
    """Read and validate every YAML contributed via the
    `fdp_schema.catalogs` entry-point group. Cached for process lifetime.
    """
    out: dict[str, "fdp_schema.Tokamak"] = {}
    for ep in entry_points(group="fdp_schema.catalogs"):
        tk = load_tokamak(ep.load())
        if tk.name in out:
            raise RuntimeError(
                f"Duplicate tokamak name {tk.name!r}: "
                f"{ep.value} conflicts with a previous entry point"
            )
        out[tk.name] = tk
    return out
```

### Duplication acknowledgement

This loop is functionally identical to `fdp.catalog._discover`. The
correct end state is a single `fdp_schema.discover_catalogs()` helper
that both call. That refactor:

1. Moves the loop into `fdp_schema`.
2. Bumps `fdp_schema` to 0.2.0.
3. Updates `fdp.catalog._discover` to wrap it.
4. Updates `toksearch.sql.mssql._discover_catalogs` to wrap it.

Tracked as future work; not in this spec. The duplication is small
enough (~10 lines) to absorb in the meantime.

### Caching

`functools.cache` caches the result for process lifetime. New entry
points appearing mid-process (e.g., via `pip install` in a long-running
Python session) are NOT picked up. Restart to refresh. This matches
`fdp.catalog`'s singleton behavior.

Tests that patch `entry_points` MUST call
`_discover_catalogs.cache_clear()` in their `setUp` to avoid leakage
across cases. The plan adds a small fixture helper.

## Testing Strategy

### `toksearch/tests/test_sql.py` (existing file, augmented)

Unit tests for `connect_tokamak_sql`, all using mocked `entry_points` and
mocked `pymssql.connect` to avoid network:

- `test_calls_pymssql_with_catalog_values` — bare call uses catalog
  host/port/db verbatim.
- `test_kwarg_overrides_catalog_host` — `host="other"` wins over catalog.
- `test_kwarg_db_overrides_catalog_database` — `db="code_rundb"`
  (the in-tree override case) routes correctly.
- `test_kwarg_port_overrides_catalog_port` — same shape.
- `test_tdsver_setdefault_does_not_override` — pre-set `TDSVER` is
  preserved; only `os.environ.setdefault` is used.
- `test_password_file_kwarg_overrides_catalog_auth_path` —
  `password_file="/x"` is read instead of `loc.auth.path`.
- `test_explicit_password_skips_file_read` — `password="…"` short-circuits
  `_resolve_credential`.
- `test_explicit_password_without_username_defaults_to_os_user` —
  `password="x"` with no `username` falls back to `getpass.getuser()`
  (preserves Phase 1 `connect_d3drdb(username=USERNAME, …)` default).
- `test_password_file_two_line_format_parsed` — username on line 1,
  password on line 2, blanks tolerated.
- `test_unknown_tokamak_raises_keyerror_with_available_list` — message
  includes `Available: [...]`.
- `test_unknown_locator_name_raises_keyerror_with_available_list` — same
  shape for the within-tokamak lookup.
- `test_unsupported_driver_raises_notimplementederror` — non-mssql
  locator path.
- `test_missing_credential_raises_runtimeerror` — neither `password`,
  `password_file`, nor `auth.path` provided.

A shared `setUp` helper calls `_discover_catalogs.cache_clear()` and
returns a context manager that patches `entry_points` with a fake yielding
a canned tokamak YAML.

### `toksearch/tests/test_sql_deprecation.py` (new file)

The deprecation shim's behavior:

- `test_emits_deprecation_warning` — calling `connect_d3drdb` emits
  `DeprecationWarning` with the new path mentioned.
- `test_kwargs_forwarded_to_impl` —
  `connect_d3drdb(db="code_rundb", host="h")` reaches
  `toksearch_d3d.sql.connect_d3drdb` with the same kwargs.
- `test_helpful_error_if_toksearch_d3d_missing` — when
  `toksearch_d3d.sql` is unimportable (mocked via `sys.modules`), the
  shim raises `ImportError` with "conda install toksearch_d3d" in the
  message.

### `toksearch_d3d/tests/test_sql.py` (new file)

- `test_delegates_to_connect_tokamak_sql` — mocked
  `toksearch.sql.mssql.connect_tokamak_sql` is called with
  `("d3d", "d3drdb", **kwargs)`.
- `test_integration_connects_to_real_d3drdb` (skip-gated on
  `~/D3DRDB.sybase_login` existing) — opens a real connection and
  `SELECT 1`. Run locally and in pre-release; skipped in plain CI.

### Deleted: `toksearch_d3d/tests/test_sql_sync.py`

The Phase 1 stopgap. With the catalog now the only source of truth,
drift between hardcoded defaults and YAML cannot happen. Removed in the
same commit that adds the new `toksearch_d3d.sql` module.

### End-to-end demo re-verification

The `bn_vs_nbi_highcurrent.py` script (the Phase 1 acceptance case) uses
`from toksearch.sql.mssql import connect_d3drdb` and runs the full
pipeline. After this change:

- The deprecation shim is invoked, the warning fires.
- The lazy import pulls `toksearch_d3d.sql.connect_d3drdb`.
- That delegates to `toksearch.sql.mssql.connect_tokamak_sql("d3d", "d3drdb")`.
- Catalog discovery picks the D3D yaml and connects with its host/port/db.
- The full pipeline runs.

Expected result: 651 plasma shots, 275 high-current after filtering,
byte-comparable plot (same point positions, modulo PNG-encoding noise
from matplotlib). If the demo breaks, the migration broke the data path
— this is the definitive end-to-end gate before merging.

## Open Items for the Plan

1. **Confirm `toksearch`'s pyproject.toml / pixi.toml structure.** The
   spec adds `fdp-schema >=0.1.1` to the conda recipe; whether it also
   needs to land in `pyproject.toml` (pip) depends on whether `toksearch`
   ships via PyPI. Current GA-FDP convention is conda-only — verify
   before editing.
2. **Confirm the `toksearch.sql` module imports.** The new file pulls
   `from fdp_schema import load_tokamak`. Confirm no existing
   module-load-time side effects in `fdp_schema` (we audited Phase 1; it
   should be clean).
3. **Toksearch dev-env editable install.** `toksearch/pixi.toml` should
   add `fdp_schema = { path = "../fdp_schema", editable = true }` if
   the dev workflow expects in-tree iteration. Otherwise the pixi-env
   conda dep (`fdp-schema >=0.1.1`) is sufficient.
4. **Version bump confirmation.** Spec assumes `toksearch 2.7.x → 2.8.0`
   and `toksearch_d3d 0.9.2 → 0.9.3`. Verify against the current
   versioneer tag state before tagging.

## Suggested Next Step

Invoke the `superpowers:writing-plans` skill to decompose this design
into an ordered, TDD-staged implementation plan with review checkpoints.
