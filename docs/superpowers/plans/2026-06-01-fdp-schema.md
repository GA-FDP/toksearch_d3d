# `fdp-schema` Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `fdp-schema` (a new pydantic-based schema package for tokamak data locators), migrate D3D's tokamak metadata from a Python dataclass entry point to a YAML data ship, and rewire `fdp.catalog` / `fdp run` / `fdp env` to consume the new schema while keeping byte-identical env-var output for existing scripts.

**Architecture:** Three packages change. A new `fdp-schema` repo provides pure pydantic models + a YAML loader + JSON Schema export (deps: pydantic v2, pyyaml). The `fdp` package gains `fdp.catalog` (entry-point discovery + `TokamakHandle`) and `fdp.resolvers` (typed per-backend helpers; `pymssql` for SQL); it loses `fdp.devices` and `fdp.Device`. The `toksearch_d3d` package ships `data/d3d.yaml` declared via the `fdp_schema.catalogs` entry-point group, drops its `fdp` run-dep, and deletes `D3D_DEVICE`. The work is staged so the new code is verified locally before old code is deleted. The parity guard is a fixture-pinned test that captures the current `D3D_DEVICE.to_env()` output and asserts the new derivation matches it byte-for-byte.

**Tech Stack:** Python 3.11, pydantic v2, pyyaml, pymssql, versioneer, rattler-build, pixi, pytest.

**Reference spec:** `toksearch_d3d/docs/superpowers/specs/2026-06-01-fdp-schema-design.md`

---

## File Structure

### New repo: `fdp_schema/`

| File | Purpose |
|---|---|
| `fdp_schema/fdp_schema/__init__.py` | Re-exports (`Tokamak`, `Locator`, locator subtypes, `load_tokamak`, `tokamak_json_schema`) + versioneer hook. |
| `fdp_schema/fdp_schema/models.py` | Pydantic models: `AuthHint`, `MdsTreeLocator`, `PtDataIndexedLocator`, `SqlLocator`, `Locator` union, `Tokamak`. |
| `fdp_schema/fdp_schema/loader.py` | `load_tokamak(source)` reads YAML and returns a validated `Tokamak`. |
| `fdp_schema/fdp_schema/_version.py` | Versioneer-generated. |
| `fdp_schema/versioneer.py` | Vendored v0.29 copy. |
| `fdp_schema/pyproject.toml` | Package metadata, build-system, versioneer config. |
| `fdp_schema/pixi.toml` | Dev workspace. |
| `fdp_schema/setup.cfg` | Versioneer prefix (`release-`). |
| `fdp_schema/recipe/recipe.yaml` | rattler-build recipe. |
| `fdp_schema/recipe/run_build.sh` | Versioneer wrapper. |
| `fdp_schema/recipe/print_version.py` | Versioneer print helper. |
| `fdp_schema/.github/workflows/conda_build.yaml` | CI / conda build / upload-on-release-tag. |
| `fdp_schema/tests/test_models.py` | Model validation + discriminated-union dispatch tests. |
| `fdp_schema/tests/test_loader.py` | YAML round-trip tests. |
| `fdp_schema/tests/test_json_schema.py` | JSON Schema export shape tests. |
| `fdp_schema/tests/fixtures/d3d.yaml` | Production-equivalent D3D fixture. |

### Modified: `fdp/`

| File | Action | Purpose |
|---|---|---|
| `fdp/fdp/devices.py` | **Delete** | Replaced by `fdp.catalog`. |
| `fdp/fdp/catalog.py` | Create | `_discover()`, `TokamakHandle`, `_Catalog`, `catalog` singleton. |
| `fdp/fdp/resolvers/__init__.py` | Create | Re-exports the three resolver classes. |
| `fdp/fdp/resolvers/mds_tree.py` | Create | `MdsTreeResolver` + `_expand_mds_template`. |
| `fdp/fdp/resolvers/ptdata.py` | Create | `PtDataResolver` (Pelican-backed JSON index reader). |
| `fdp/fdp/resolvers/sql.py` | Create | `SqlResolver` (pymssql, password-file auth). |
| `fdp/fdp/environment.py` | Modify | Replace `Device.to_env()` call sites with `_tokamak_env(catalog[name])`. |
| `fdp/fdp/cli.py` | Modify | Remove `devices` subcommand; add `catalog list` / `catalog show`. |
| `fdp/fdp/__init__.py` | Modify | Drop `Device` re-export; add `catalog`. |
| `fdp/pyproject.toml` | Modify | Add `fdp-schema`, `toksearch` to run-deps. Bump version to 0.2.0. |
| `fdp/recipe/recipe.yaml` | Modify | Mirror run-dep additions. |
| `fdp/tests/test_env_parity.py` | Create | Pinned fixture asserting `_tokamak_env(catalog["d3d"])` == expected dict. |
| `fdp/tests/test_catalog.py` | Create | Discovery (mocked entry points), `TokamakHandle.locator()` semantics, CLI snapshot. |
| `fdp/tests/test_resolvers.py` | Create | `MdsTreeResolver.urls_for`, mocked `PtDataResolver` and `SqlResolver`. |
| `fdp/tests/test_devices.py` | Delete (if exists) | Superseded by catalog tests. |

### Modified: `toksearch_d3d/`

| File | Action | Purpose |
|---|---|---|
| `toksearch_d3d/toksearch_d3d/fdp.py` | **Delete** | `D3D_DEVICE` module. |
| `toksearch_d3d/toksearch_d3d/data/__init__.py` | Create | 2 lines: `Traversable` declaration. |
| `toksearch_d3d/toksearch_d3d/data/d3d.yaml` | Create | The D3D catalog content. |
| `toksearch_d3d/pyproject.toml` | Modify | Swap entry-point group; drop `fdp` dep; add package-data; bump to 0.5.0. |
| `toksearch_d3d/recipe/recipe.yaml` | Modify | Drop `fdp` run-dep; bump version. |
| `toksearch_d3d/tests/test_catalog.py` | Create | YAML validates; entry-point discovery works. |
| `toksearch_d3d/tests/test_sql_sync.py` | Create | Catalog `SqlLocator` matches `connect_d3drdb` defaults. |

### Modified: top-level docs

| File | Action |
|---|---|
| `repos/CLAUDE.md` | Update `fdp.Device` references to `fdp.catalog`. |
| `toksearch_d3d/CLAUDE.md` | Update stale `toksearch_d3d.fdp.cli` reference; mention catalog. |

---

## Implementation phases

The plan is staged so each phase delivers something testable before moving on:

- **Phase A (Tasks 1–7):** Build `fdp-schema` package locally as a pip-installable. No conda, no release.
- **Phase B (Tasks 8–11):** Capture the D3D env-var fixture (must happen before `D3D_DEVICE` is deleted), author `d3d.yaml`, and verify it validates via `fdp-schema` — without touching `fdp.devices` yet.
- **Phase C (Tasks 12–17):** Build `fdp.catalog` and resolvers in `fdp`. Side-by-side with the existing `Device` code; nothing deleted yet.
- **Phase D (Tasks 18–19):** Rewire `fdp run` / `fdp env` to consume the catalog. Parity test pinned.
- **Phase E (Tasks 20–23):** Delete the old code. Swap entry-point groups. Drop deps.
- **Phase F (Tasks 24–26):** Sync test + docs.
- **Phase G (Tasks 27–28):** Conda packaging + version bumps + release tags.

Commit at every task boundary. Frequent small commits are the rule.

---

# Phase A: Bootstrap `fdp_schema` package

## Task 1: Create the `fdp_schema` repo skeleton

**Files:**
- Create: `fdp_schema/` (new directory under `/fusion/projects/dt/sammuli/fdp_dev/repos/`)
- Create: `fdp_schema/pyproject.toml`
- Create: `fdp_schema/setup.cfg`
- Create: `fdp_schema/pixi.toml`
- Create: `fdp_schema/fdp_schema/__init__.py`
- Create: `fdp_schema/versioneer.py`
- Create: `fdp_schema/.gitignore`
- Create: `fdp_schema/README.md`

The structure mirrors existing GA-FDP packages (compare `repos/fdp/` and `repos/toksearch_d3d/`). Vendor versioneer v0.29 verbatim from one of those repos.

- [ ] **Step 1: Create the directory and copy versioneer.**

```bash
mkdir -p /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema/fdp_schema
mkdir -p /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema/tests/fixtures
mkdir -p /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema/recipe
cp /fusion/projects/dt/sammuli/fdp_dev/repos/fdp/versioneer.py /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema/versioneer.py
```

- [ ] **Step 2: Write `fdp_schema/pyproject.toml`.**

```toml
[build-system]
requires = ["setuptools>=61", "wheel", "versioneer[toml]==0.29"]
build-backend = "setuptools.build_meta"

[project]
name = "fdp-schema"
description = "Package-neutral schema for tokamak data locator catalogs"
authors = [{name = "General Atomics"}]
license = {text = "Apache-2.0"}
readme = "README.md"
requires-python = ">=3.11"
dynamic = ["version"]
dependencies = [
    "pydantic>=2",
    "pyyaml",
]

[project.optional-dependencies]
test = ["pytest"]

[tool.setuptools.packages.find]
include = ["fdp_schema*"]

[tool.setuptools.package-data]
"fdp_schema" = ["py.typed"]

[tool.versioneer]
VCS = "git"
style = "pep440"
versionfile_source = "fdp_schema/_version.py"
versionfile_build = "fdp_schema/_version.py"
tag_prefix = "release-"
parentdir_prefix = "fdp_schema-"
```

- [ ] **Step 3: Write `fdp_schema/setup.cfg`.**

```ini
[versioneer]
VCS = git
style = pep440
versionfile_source = fdp_schema/_version.py
versionfile_build = fdp_schema/_version.py
tag_prefix = release-
parentdir_prefix = fdp_schema-
```

- [ ] **Step 4: Write `fdp_schema/pixi.toml`.**

```toml
[workspace]
name = "fdp_schema"
channels = ["conda-forge"]
platforms = ["linux-64"]

[dependencies]
python = "3.11.*"
pydantic = ">=2"
pyyaml = "*"
pytest = "*"
versioneer = "*"

[pypi-dependencies]
fdp_schema = { path = ".", editable = true }

[tasks]
test = "pytest -v"
```

- [ ] **Step 5: Write `fdp_schema/fdp_schema/__init__.py`.**

```python
# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Package-neutral schema for tokamak data locator catalogs.

Defines pydantic models that describe how a tokamak's data lives across
backends (MDSplus trees, PTData indexes, SQL databases). Pure data: no
network, no XRootD, no GA-FDP dependencies beyond pydantic and pyyaml.

Consumers (fdp, MCP servers, future Julia tools) import the models and
load YAMLs that contributing packages ship via the `fdp_schema.catalogs`
entry-point group.
"""
from . import _version

__version__ = _version.get_versions()["version"]

__all__ = [
    "__version__",
]
# Other re-exports added by subsequent tasks.
```

- [ ] **Step 6: Write `fdp_schema/.gitignore`.**

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.pixi/
build/
dist/
```

- [ ] **Step 7: Write `fdp_schema/README.md`.**

```markdown
# fdp-schema

Package-neutral pydantic schema for tokamak data locator catalogs.

The schema describes where a tokamak's data lives across backends (MDSplus
trees, PTData indexes, SQL databases). Other packages (e.g., `fdp`,
`toksearch_d3d`) consume the schema; tokamak packages contribute a YAML via
the `fdp_schema.catalogs` entry-point group.

See `docs/` and the design spec in
`toksearch_d3d/docs/superpowers/specs/2026-06-01-fdp-schema-design.md`.
```

- [ ] **Step 8: Initialize git and install versioneer.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema
git init
pixi install
pixi run python -m versioneer install --no-vendor
```

Expected: `fdp_schema/_version.py` is generated.

- [ ] **Step 9: First commit.**

```bash
git add -A
git commit -m "Bootstrap fdp_schema package skeleton"
```

---

## Task 2: Implement `AuthHint` model with TDD

**Files:**
- Create: `fdp_schema/tests/test_models.py`
- Modify: `fdp_schema/fdp_schema/models.py` (create file)
- Modify: `fdp_schema/fdp_schema/__init__.py`

- [ ] **Step 1: Write the failing test in `fdp_schema/tests/test_models.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for fdp_schema.models — pure pydantic validation, no I/O."""

import pytest
from pydantic import ValidationError


class TestAuthHint:
    def test_bearer_token_with_env(self):
        from fdp_schema.models import AuthHint
        a = AuthHint(kind="bearer_token", env="BEARER_TOKEN")
        assert a.kind == "bearer_token"
        assert a.env == "BEARER_TOKEN"
        assert a.path is None

    def test_password_file_with_path(self):
        from fdp_schema.models import AuthHint
        a = AuthHint(kind="password_file", path="~/.fdp/token")
        assert a.kind == "password_file"
        assert a.path == "~/.fdp/token"

    def test_kind_none(self):
        from fdp_schema.models import AuthHint
        a = AuthHint(kind="none")
        assert a.kind == "none"

    def test_unknown_kind_rejected(self):
        from fdp_schema.models import AuthHint
        with pytest.raises(ValidationError):
            AuthHint(kind="oauth2")
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema
pixi run pytest tests/test_models.py::TestAuthHint -v
```

Expected: All four FAIL with `ImportError: cannot import name 'AuthHint' from 'fdp_schema.models'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Create `fdp_schema/fdp_schema/models.py` with `AuthHint`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Pydantic models for the fdp_schema catalog format."""

from typing import Literal
from pydantic import BaseModel


class AuthHint(BaseModel):
    """Tells consumers what credential to expect. Mechanism is out-of-band:
    the credential itself lives in an env var (`env=...`) or a file
    (`path=...`); this object never holds secrets."""

    kind: Literal["bearer_token", "password_file", "none"]
    env: str | None = None
    path: str | None = None
```

- [ ] **Step 4: Run the tests to verify they pass.**

```bash
pixi run pytest tests/test_models.py::TestAuthHint -v
```

Expected: All four PASS.

- [ ] **Step 5: Commit.**

```bash
git add fdp_schema/models.py tests/test_models.py
git commit -m "Add AuthHint model"
```

---

## Task 3: Implement the three Locator models with discriminated-union dispatch

**Files:**
- Modify: `fdp_schema/tests/test_models.py`
- Modify: `fdp_schema/fdp_schema/models.py`

- [ ] **Step 1: Append failing tests to `fdp_schema/tests/test_models.py`.**

```python
class TestMdsTreeLocator:
    def test_minimal(self):
        from fdp_schema.models import MdsTreeLocator
        m = MdsTreeLocator(
            name="main",
            transport="pelican",
            search_path=["pelican://host/tree1", "pelican://host/tree2"],
        )
        assert m.kind == "mds_tree"
        assert m.search_path == ["pelican://host/tree1", "pelican://host/tree2"]
        assert m.auth is None

    def test_with_auth(self):
        from fdp_schema.models import MdsTreeLocator, AuthHint
        m = MdsTreeLocator(
            name="main",
            transport="pelican",
            search_path=["pelican://host/tree"],
            auth=AuthHint(kind="bearer_token", env="BEARER_TOKEN"),
        )
        assert m.auth.kind == "bearer_token"

    def test_kind_immutable_via_init(self):
        # Pydantic accepts the literal default; explicit kind=mds_tree also ok.
        from fdp_schema.models import MdsTreeLocator
        m = MdsTreeLocator(
            kind="mds_tree", name="main", transport="pelican", search_path=[]
        )
        assert m.kind == "mds_tree"

    def test_unknown_transport_rejected(self):
        from fdp_schema.models import MdsTreeLocator
        with pytest.raises(ValidationError):
            MdsTreeLocator(name="main", transport="smb", search_path=[])


class TestPtDataIndexedLocator:
    def test_minimal(self):
        from fdp_schema.models import PtDataIndexedLocator
        p = PtDataIndexedLocator(
            name="main",
            transport="pelican",
            index_dir="pelican://host/index",
        )
        assert p.kind == "ptdata_indexed"
        assert p.index_dir == "pelican://host/index"


class TestSqlLocator:
    def test_mssql_full(self):
        from fdp_schema.models import SqlLocator
        s = SqlLocator(
            name="d3drdb",
            driver="mssql",
            host="d3drdb.gat.com",
            port=8001,
            database="d3drdb",
            tdsver="7.0",
        )
        assert s.kind == "sql"
        assert s.host == "d3drdb.gat.com"
        assert s.port == 8001
        assert s.tdsver == "7.0"

    def test_unknown_driver_rejected(self):
        from fdp_schema.models import SqlLocator
        with pytest.raises(ValidationError):
            SqlLocator(name="x", driver="oracle", host="h", database="d")


class TestLocatorDispatch:
    """The Locator union must dispatch on `kind` to the right subtype."""

    def test_dispatch_mds_tree(self):
        from pydantic import TypeAdapter
        from fdp_schema.models import Locator, MdsTreeLocator
        adapter = TypeAdapter(Locator)
        loc = adapter.validate_python(
            {"kind": "mds_tree", "name": "main", "transport": "pelican",
             "search_path": ["url1"]}
        )
        assert isinstance(loc, MdsTreeLocator)

    def test_dispatch_ptdata(self):
        from pydantic import TypeAdapter
        from fdp_schema.models import Locator, PtDataIndexedLocator
        adapter = TypeAdapter(Locator)
        loc = adapter.validate_python(
            {"kind": "ptdata_indexed", "name": "main",
             "transport": "pelican", "index_dir": "u"}
        )
        assert isinstance(loc, PtDataIndexedLocator)

    def test_dispatch_sql(self):
        from pydantic import TypeAdapter
        from fdp_schema.models import Locator, SqlLocator
        adapter = TypeAdapter(Locator)
        loc = adapter.validate_python(
            {"kind": "sql", "name": "d", "driver": "mssql",
             "host": "h", "database": "d"}
        )
        assert isinstance(loc, SqlLocator)

    def test_unknown_kind_rejected(self):
        from pydantic import TypeAdapter, ValidationError
        from fdp_schema.models import Locator
        adapter = TypeAdapter(Locator)
        with pytest.raises(ValidationError):
            adapter.validate_python({"kind": "kafka", "name": "x"})
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
pixi run pytest tests/test_models.py -v -k "MdsTree or PtData or Sql or Dispatch"
```

Expected: ImportErrors for `MdsTreeLocator`, `PtDataIndexedLocator`, `SqlLocator`, `Locator`.

- [ ] **Step 3: Append the locator models to `fdp_schema/fdp_schema/models.py`.**

```python
from typing import Annotated, Union
from pydantic import Field


class MdsTreeLocator(BaseModel):
    """A search path of base URLs (with MDSplus tree-path tokens like ~t)
    consulted in order when opening an MDSplus tree."""

    kind: Literal["mds_tree"] = "mds_tree"
    name: str
    transport: Literal["pelican", "xrootd", "local"]
    search_path: list[str]
    auth: AuthHint | None = None


class PtDataIndexedLocator(BaseModel):
    """A PTData (shot, pointname) → shotfile resolution via a JSON index."""

    kind: Literal["ptdata_indexed"] = "ptdata_indexed"
    name: str
    transport: Literal["pelican", "xrootd", "local"]
    index_dir: str
    auth: AuthHint | None = None


class SqlLocator(BaseModel):
    """A SQL database holding shot metadata. v1 implements mssql only."""

    kind: Literal["sql"] = "sql"
    name: str
    driver: Literal["mssql", "postgres", "sqlite"]
    host: str
    port: int | None = None
    database: str
    tdsver: str | None = None
    auth: AuthHint | None = None


Locator = Annotated[
    Union[MdsTreeLocator, PtDataIndexedLocator, SqlLocator],
    Field(discriminator="kind"),
]
```

- [ ] **Step 4: Run the tests to verify they pass.**

```bash
pixi run pytest tests/test_models.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit.**

```bash
git add fdp_schema/models.py tests/test_models.py
git commit -m "Add Locator models and discriminated-union dispatch"
```

---

## Task 4: Implement the `Tokamak` model

**Files:**
- Modify: `fdp_schema/tests/test_models.py`
- Modify: `fdp_schema/fdp_schema/models.py`
- Modify: `fdp_schema/fdp_schema/__init__.py`

- [ ] **Step 1: Append failing tests to `fdp_schema/tests/test_models.py`.**

```python
class TestTokamak:
    def test_minimal(self):
        from fdp_schema.models import Tokamak
        t = Tokamak(name="x")
        assert t.schema_version == 1
        assert t.name == "x"
        assert t.description == ""
        assert t.locators == []
        assert t.extra_env == {}

    def test_full(self):
        from fdp_schema.models import (
            Tokamak, MdsTreeLocator, PtDataIndexedLocator
        )
        t = Tokamak(
            name="d3d",
            description="DIII-D",
            pelican_root="pelican://host/d3d",
            origin_server="root://host:8443",
            locators=[
                MdsTreeLocator(name="main", transport="pelican",
                               search_path=["u"]),
                PtDataIndexedLocator(name="main", transport="pelican",
                                     index_dir="u"),
            ],
            extra_env={"D3DATA": "yes"},
        )
        assert t.name == "d3d"
        assert len(t.locators) == 2
        assert t.locators[0].kind == "mds_tree"
        assert t.locators[1].kind == "ptdata_indexed"
        assert t.extra_env == {"D3DATA": "yes"}

    def test_locator_dispatch_from_dict(self):
        from fdp_schema.models import Tokamak, MdsTreeLocator
        t = Tokamak.model_validate({
            "name": "x",
            "locators": [
                {"kind": "mds_tree", "name": "main", "transport": "pelican",
                 "search_path": ["u"]},
            ],
        })
        assert isinstance(t.locators[0], MdsTreeLocator)

    def test_schema_version_must_be_1(self):
        from fdp_schema.models import Tokamak
        with pytest.raises(ValidationError):
            Tokamak(schema_version=2, name="x")

    def test_extra_env_rejects_non_string_values(self):
        from fdp_schema.models import Tokamak
        with pytest.raises(ValidationError):
            Tokamak(name="x", extra_env={"K": 42})
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
pixi run pytest tests/test_models.py::TestTokamak -v
```

Expected: ImportError for `Tokamak`.

- [ ] **Step 3: Append the `Tokamak` model to `fdp_schema/fdp_schema/models.py`.**

```python
class Tokamak(BaseModel):
    """One tokamak's data-locator catalog. Schema-versioned for forward
    compatibility — v2 (when it exists) will live as a separate class and
    the loader will dispatch on the declared version."""

    schema_version: Literal[1] = 1
    name: str
    description: str = ""
    pelican_root: str | None = None
    origin_server: str | None = None
    locators: list[Locator] = []
    extra_env: dict[str, str] = {}
```

- [ ] **Step 4: Update `fdp_schema/fdp_schema/__init__.py` to re-export.**

Replace the existing `__all__` block with:

```python
from .models import (
    AuthHint,
    MdsTreeLocator,
    PtDataIndexedLocator,
    SqlLocator,
    Locator,
    Tokamak,
)

__all__ = [
    "__version__",
    "AuthHint",
    "MdsTreeLocator",
    "PtDataIndexedLocator",
    "SqlLocator",
    "Locator",
    "Tokamak",
]
```

- [ ] **Step 5: Run all tests in the file to verify they pass.**

```bash
pixi run pytest tests/test_models.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit.**

```bash
git add fdp_schema/models.py fdp_schema/__init__.py tests/test_models.py
git commit -m "Add Tokamak model and package re-exports"
```

---

## Task 5: Implement the YAML loader

**Files:**
- Create: `fdp_schema/tests/test_loader.py`
- Create: `fdp_schema/fdp_schema/loader.py`
- Modify: `fdp_schema/fdp_schema/__init__.py`

- [ ] **Step 1: Write the failing tests in `fdp_schema/tests/test_loader.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for fdp_schema.loader — YAML parsing and round-trip."""

from pathlib import Path
import textwrap
import pytest


class TestLoadTokamak:
    def test_load_from_path(self, tmp_path):
        from fdp_schema import load_tokamak, Tokamak
        p = tmp_path / "x.yaml"
        p.write_text(textwrap.dedent("""
            schema_version: 1
            name: x
            description: test
            locators:
              - kind: mds_tree
                name: main
                transport: pelican
                search_path: ["u1", "u2"]
        """))
        t = load_tokamak(p)
        assert isinstance(t, Tokamak)
        assert t.name == "x"
        assert len(t.locators) == 1
        assert t.locators[0].search_path == ["u1", "u2"]

    def test_load_from_str_path(self, tmp_path):
        from fdp_schema import load_tokamak
        p = tmp_path / "x.yaml"
        p.write_text("schema_version: 1\nname: x\n")
        t = load_tokamak(str(p))
        assert t.name == "x"

    def test_load_from_traversable(self, tmp_path):
        from fdp_schema import load_tokamak
        # Traversable is duck-typed: needs .read_text(). Use a Path (which qualifies).
        p = tmp_path / "x.yaml"
        p.write_text("schema_version: 1\nname: x\n")

        class FakeTraversable:
            def read_text(self):
                return p.read_text()

        t = load_tokamak(FakeTraversable())
        assert t.name == "x"

    def test_invalid_yaml_raises(self, tmp_path):
        from fdp_schema import load_tokamak
        p = tmp_path / "x.yaml"
        p.write_text("name: x\nlocators:\n  - kind: kafka\n")
        with pytest.raises(Exception):  # pydantic ValidationError
            load_tokamak(p)

    def test_round_trip(self, tmp_path):
        """model_dump() → yaml → load_tokamak() is identity."""
        import yaml
        from fdp_schema import (
            load_tokamak, Tokamak, MdsTreeLocator, AuthHint,
        )
        original = Tokamak(
            name="d3d",
            description="DIII-D",
            locators=[
                MdsTreeLocator(
                    name="main", transport="pelican",
                    search_path=["u1", "u2"],
                    auth=AuthHint(kind="bearer_token", env="BEARER_TOKEN"),
                ),
            ],
            extra_env={"K": "V"},
        )
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(original.model_dump()))
        loaded = load_tokamak(p)
        assert loaded == original
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
pixi run pytest tests/test_loader.py -v
```

Expected: `ImportError: cannot import name 'load_tokamak'`.

- [ ] **Step 3: Create `fdp_schema/fdp_schema/loader.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""YAML loading and validation for tokamak catalog files."""

from pathlib import Path
import yaml
from pydantic import ValidationError

from .models import Tokamak


def load_tokamak(source) -> Tokamak:
    """Load a Tokamak from a YAML file.

    `source` may be:
    - a stdlib `importlib.abc.Traversable` (anything with `.read_text()`)
    - a `pathlib.Path`
    - a `str` filesystem path

    Raises:
      pydantic.ValidationError: with the source path prepended to the
        error message, so failures point at the offending YAML.
    """
    label = str(source) if not hasattr(source, "read_text") else repr(source)
    if hasattr(source, "read_text"):
        text = source.read_text()
    else:
        text = Path(source).read_text()
    try:
        return Tokamak.model_validate(yaml.safe_load(text))
    except ValidationError as e:
        raise ValidationError.from_exception_data(
            f"Tokamak (from {label})", e.errors(),
        ) from None
```

Also add a test case for this behavior — append to the existing `TestLoadTokamak` class in `fdp_schema/tests/test_loader.py`:

```python
    def test_invalid_yaml_error_mentions_source(self, tmp_path):
        from fdp_schema import load_tokamak
        from pydantic import ValidationError
        p = tmp_path / "bad.yaml"
        p.write_text("name: x\nlocators:\n  - kind: kafka\n")
        with pytest.raises(ValidationError) as exc:
            load_tokamak(p)
        # The error message should make it possible to identify the source file.
        assert "bad.yaml" in str(exc.value) or "bad.yaml" in repr(exc.value)
```

- [ ] **Step 4: Update `fdp_schema/fdp_schema/__init__.py` to re-export the loader.**

Add `load_tokamak` to imports and `__all__`:

```python
from .models import (
    AuthHint,
    MdsTreeLocator,
    PtDataIndexedLocator,
    SqlLocator,
    Locator,
    Tokamak,
)
from .loader import load_tokamak

__all__ = [
    "__version__",
    "AuthHint",
    "MdsTreeLocator",
    "PtDataIndexedLocator",
    "SqlLocator",
    "Locator",
    "Tokamak",
    "load_tokamak",
]
```

- [ ] **Step 5: Run the tests to verify they pass.**

```bash
pixi run pytest tests/test_loader.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit.**

```bash
git add fdp_schema/loader.py fdp_schema/__init__.py tests/test_loader.py
git commit -m "Add load_tokamak YAML loader"
```

---

## Task 6: Implement JSON Schema export

**Files:**
- Create: `fdp_schema/tests/test_json_schema.py`
- Modify: `fdp_schema/fdp_schema/__init__.py`

- [ ] **Step 1: Write the failing test in `fdp_schema/tests/test_json_schema.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for fdp_schema's JSON Schema export."""


class TestJsonSchema:
    def test_export_returns_dict(self):
        from fdp_schema import tokamak_json_schema
        schema = tokamak_json_schema()
        assert isinstance(schema, dict)

    def test_exports_top_level_tokamak_properties(self):
        from fdp_schema import tokamak_json_schema
        schema = tokamak_json_schema()
        props = schema["properties"]
        assert "name" in props
        assert "schema_version" in props
        assert "locators" in props
        assert "extra_env" in props

    def test_defs_include_all_locator_types(self):
        from fdp_schema import tokamak_json_schema
        schema = tokamak_json_schema()
        defs = schema.get("$defs", schema.get("definitions", {}))
        names = set(defs.keys())
        assert "MdsTreeLocator" in names
        assert "PtDataIndexedLocator" in names
        assert "SqlLocator" in names
        assert "AuthHint" in names
```

- [ ] **Step 2: Run the test to verify it fails.**

```bash
pixi run pytest tests/test_json_schema.py -v
```

Expected: `ImportError: cannot import name 'tokamak_json_schema'`.

- [ ] **Step 3: Add `tokamak_json_schema` to `fdp_schema/fdp_schema/__init__.py`.**

After the loader import, before `__all__`:

```python

def tokamak_json_schema() -> dict:
    """Return the JSON Schema (Draft 2020-12) for a Tokamak document.

    Useful for non-Python consumers (Julia, JS, etc.) to validate catalog
    files without importing pydantic.
    """
    return Tokamak.model_json_schema()
```

Update `__all__` to include `"tokamak_json_schema"`.

- [ ] **Step 4: Run the test to verify it passes.**

```bash
pixi run pytest tests/test_json_schema.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit.**

```bash
git add fdp_schema/__init__.py tests/test_json_schema.py
git commit -m "Add tokamak_json_schema export"
```

---

## Task 7: Add D3D fixture and full-fixture validation test

**Files:**
- Create: `fdp_schema/tests/fixtures/d3d.yaml`
- Modify: `fdp_schema/tests/test_loader.py`

This fixture is the canonical sample used to validate the schema is rich
enough for real data. It is a near-copy of the production YAML that
`toksearch_d3d` will ship in Task 10. Keeping it inside `fdp_schema/tests/`
lets the schema package detect breaks before they hit downstream consumers.

- [ ] **Step 1: Write `fdp_schema/tests/fixtures/d3d.yaml`.**

```yaml
schema_version: 1
name: d3d
description: DIII-D fusion experiment, via Pelican
pelican_root: pelican://osg-htc.org:443/fdp-d3d
origin_server: root://fdp-d3d-origin.nationalresearchplatform.org:8443

locators:
  - kind: mds_tree
    name: main
    transport: pelican
    search_path:
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c
    auth: { kind: bearer_token, env: BEARER_TOKEN }

  - kind: ptdata_indexed
    name: main
    transport: pelican
    index_dir: pelican://osg-htc.org:443/fdp-d3d/archives/index/json/json_indexes_2026-01-13_12:22:11
    auth: { kind: bearer_token, env: BEARER_TOKEN }

  - kind: sql
    name: d3drdb
    driver: mssql
    host: d3drdb.gat.com
    port: 8001
    database: d3drdb
    tdsver: "7.0"
    auth: { kind: password_file, path: ~/D3DRDB.sybase_login }

extra_env:
  D3DATA: "yes"
  SYS_D3_DELIM: ";"
  CAKE_DB_PATH: "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db"
```

- [ ] **Step 2: Append the fixture test to `fdp_schema/tests/test_loader.py`.**

```python
class TestD3DFixture:
    def test_d3d_fixture_loads(self):
        from pathlib import Path
        from fdp_schema import load_tokamak
        fixture = Path(__file__).parent / "fixtures" / "d3d.yaml"
        t = load_tokamak(fixture)
        assert t.name == "d3d"
        assert len(t.locators) == 3
        kinds = {l.kind for l in t.locators}
        assert kinds == {"mds_tree", "ptdata_indexed", "sql"}
        assert t.extra_env["D3DATA"] == "yes"
        assert t.extra_env["SYS_D3_DELIM"] == ";"
```

- [ ] **Step 3: Run all tests to verify everything passes.**

```bash
pixi run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit.**

```bash
git add tests/fixtures/d3d.yaml tests/test_loader.py
git commit -m "Add D3D fixture and full-fixture validation test"
```

End of Phase A. `fdp_schema` is now a functional pip-installable package with full test coverage. The conda recipe and release tagging come in Phase G.

---

# Phase B: D3D YAML migration (capture fixture, author YAML)

## Task 8: Install `fdp_schema` in `toksearch_d3d`'s and `fdp`'s dev envs

**Files:**
- Modify: `toksearch_d3d/pixi.toml`
- Modify: `fdp/pixi.toml`

The goal is to make `fdp_schema` importable from both repos in development without requiring a conda release. We use a path-based pypi-dependency (editable install).

- [ ] **Step 1: Add `fdp_schema` to `toksearch_d3d/pixi.toml`.**

Read the existing `[pypi-dependencies]` (if any) in `toksearch_d3d/pixi.toml`. Add or extend:

```toml
[pypi-dependencies]
fdp_schema = { path = "../fdp_schema", editable = true }
```

If `[pypi-dependencies]` already exists, append the line; otherwise add the whole section. Also add `pydantic = ">=2"` and `pyyaml = "*"` under `[dependencies]` if they're not already pulled in transitively (verify with `pixi tree`).

- [ ] **Step 2: Add `fdp_schema` to `fdp/pixi.toml`.**

Same pattern: add `fdp_schema = { path = "../fdp_schema", editable = true }` to `[pypi-dependencies]`.

- [ ] **Step 3: Verify both envs install cleanly.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi install
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && pixi install
```

Expected: both succeed.

- [ ] **Step 4: Sanity-check from each env that `fdp_schema` imports.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -c "import fdp_schema; print(fdp_schema.__version__)"
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && pixi run python -c "import fdp_schema; print(fdp_schema.__version__)"
```

Expected: prints a version string from each env.

- [ ] **Step 5: Commit (in each repo separately).**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git add pixi.toml pixi.lock
git commit -m "Add fdp_schema dev dep for upcoming catalog migration"

cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
git add pixi.toml pixi.lock
git commit -m "Add fdp_schema dev dep for upcoming catalog migration"
```

---

## Task 9: Capture the D3D env-var fixture

**Files:**
- Create: `fdp/tests/test_env_parity_fixture.txt` (temporary file holding the captured output)

This is the **critical** step that must happen before `D3D_DEVICE` is deleted. The captured output is the ground truth that the parity test (Task 18) will assert against forever.

- [ ] **Step 1: Run the existing D3D Device to capture its full env-var output.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
pixi run python -c "
from toksearch_d3d.fdp import D3D_DEVICE
import json
print(json.dumps(D3D_DEVICE.to_env(), indent=2, sort_keys=True))
" > /tmp/d3d_to_env_capture.json
cat /tmp/d3d_to_env_capture.json
```

Expected output contains keys: `default_tree_path`, `PTDATA_JSON_INDEX_DIR`, `D3DATA`, `SYS_D3_DELIM`, `CAKE_DB_PATH`. Verify by eye.

- [ ] **Step 2: Save the capture into the repo for reference.**

```bash
cp /tmp/d3d_to_env_capture.json /fusion/projects/dt/sammuli/fdp_dev/repos/fdp/tests/_d3d_to_env_capture.json
```

This file is a one-time captured artifact. It will become the `EXPECTED_D3D_ENV` dict in `test_env_parity.py` (Task 18). It is **not** consumed at test time — the test will inline the expected dict. The file is committed so the capture is reviewable.

- [ ] **Step 3: Commit.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
git add tests/_d3d_to_env_capture.json
git commit -m "Capture D3D_DEVICE.to_env() output for parity-test ground truth"
```

---

## Task 10: Create `d3d.yaml` in `toksearch_d3d`

**Files:**
- Create: `toksearch_d3d/toksearch_d3d/data/__init__.py`
- Create: `toksearch_d3d/toksearch_d3d/data/d3d.yaml`

- [ ] **Step 1: Create `toksearch_d3d/toksearch_d3d/data/__init__.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Catalog data shipped by toksearch_d3d.

This module exposes Traversable references for each YAML so the
fdp_schema.catalogs entry-point group can find them without importing
fdp_schema or pydantic.
"""

from importlib.resources import files

d3d_yaml = files(__package__) / "d3d.yaml"
```

- [ ] **Step 2: Create `toksearch_d3d/toksearch_d3d/data/d3d.yaml`.**

Use the exact content from `fdp_schema/tests/fixtures/d3d.yaml` (Task 7) — they should be byte-identical at this point. The plan ships this as the canonical D3D YAML:

```yaml
schema_version: 1
name: d3d
description: DIII-D fusion experiment, via Pelican
pelican_root: pelican://osg-htc.org:443/fdp-d3d
origin_server: root://fdp-d3d-origin.nationalresearchplatform.org:8443

locators:
  - kind: mds_tree
    name: main
    transport: pelican
    search_path:
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c
    auth: { kind: bearer_token, env: BEARER_TOKEN }

  - kind: ptdata_indexed
    name: main
    transport: pelican
    index_dir: pelican://osg-htc.org:443/fdp-d3d/archives/index/json/json_indexes_2026-01-13_12:22:11
    auth: { kind: bearer_token, env: BEARER_TOKEN }

  - kind: sql
    name: d3drdb
    driver: mssql
    host: d3drdb.gat.com
    port: 8001
    database: d3drdb
    tdsver: "7.0"
    auth: { kind: password_file, path: ~/D3DRDB.sybase_login }

extra_env:
  D3DATA: "yes"
  SYS_D3_DELIM: ";"
  CAKE_DB_PATH: "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db"
```

**Verify** the URLs match the current `D3D_DEVICE`. Cross-reference with the capture from Task 9 — the `default_tree_path` value is the four URLs joined with `;`, and `PTDATA_JSON_INDEX_DIR` is the `index_dir` value verbatim. If anything mismatches, fix the YAML.

- [ ] **Step 3: Commit.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git add toksearch_d3d/data/__init__.py toksearch_d3d/data/d3d.yaml
git commit -m "Add d3d.yaml catalog data and Traversable declaration"
```

---

## Task 11: Wire the `fdp_schema.catalogs` entry point in `toksearch_d3d` (do NOT remove `fdp.devices` yet)

**Files:**
- Modify: `toksearch_d3d/pyproject.toml`
- Create: `toksearch_d3d/tests/test_catalog.py`

This task adds the new entry point **alongside** the existing `fdp.devices` one. Removing the old entry point is Task 22 — keeping both during the transition lets us verify the new path independently without breaking the old one.

- [ ] **Step 1: Add the entry-point and package-data declarations to `toksearch_d3d/pyproject.toml`.**

Locate the existing `[project.entry-points."fdp.devices"]` block (around line 63 per the spec; verify). Below it, add:

```toml
[project.entry-points."fdp_schema.catalogs"]
d3d = "toksearch_d3d.data:d3d_yaml"
```

Also add package-data declaration (likely in `[tool.setuptools.package-data]` if present, or add the section):

```toml
[tool.setuptools.package-data]
"toksearch_d3d.data" = ["*.yaml"]
```

Do **not** modify `[project.dependencies]` yet. `fdp` stays as a dep for now.

- [ ] **Step 2: Reinstall editable to pick up the new entry point.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
pixi install
```

- [ ] **Step 3: Write the failing test `toksearch_d3d/tests/test_catalog.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests that the toksearch_d3d catalog data ships and validates."""

import unittest


class TestD3DCatalog(unittest.TestCase):
    def test_d3d_yaml_validates(self):
        from fdp_schema import load_tokamak
        from toksearch_d3d.data import d3d_yaml
        t = load_tokamak(d3d_yaml)
        self.assertEqual(t.name, "d3d")
        self.assertEqual(len(t.locators), 3)
        kinds = {l.kind for l in t.locators}
        self.assertEqual(kinds, {"mds_tree", "ptdata_indexed", "sql"})

    def test_entry_point_registered(self):
        from importlib.metadata import entry_points
        eps = list(entry_points(group="fdp_schema.catalogs"))
        names = [ep.name for ep in eps]
        self.assertIn("d3d", names)

    def test_entry_point_load_returns_readable_traversable(self):
        from importlib.metadata import entry_points
        from fdp_schema import load_tokamak
        eps = entry_points(group="fdp_schema.catalogs")
        d3d_ep = next(ep for ep in eps if ep.name == "d3d")
        source = d3d_ep.load()
        # Should be readable via load_tokamak directly.
        t = load_tokamak(source)
        self.assertEqual(t.name, "d3d")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the test to verify it passes.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
pixi run python -m pytest tests/test_catalog.py -v
```

Expected: all three tests PASS.

- [ ] **Step 5: Verify the SQL locator data matches `connect_d3drdb` defaults manually.**

This sanity check anticipates the sync test in Task 24:

```bash
pixi run python -c "
from inspect import signature
from toksearch.sql.mssql import connect_d3drdb
from fdp_schema import load_tokamak
from toksearch_d3d.data import d3d_yaml
t = load_tokamak(d3d_yaml)
sql = next(l for l in t.locators if l.kind == 'sql')
sig = signature(connect_d3drdb)
assert sql.host == sig.parameters['host'].default, (sql.host, sig.parameters['host'].default)
assert sql.port == sig.parameters['port'].default, (sql.port, sig.parameters['port'].default)
assert sql.database == sig.parameters['db'].default, (sql.database, sig.parameters['db'].default)
print('SQL locator data matches connect_d3drdb defaults.')
"
```

Expected: prints the success message. If it fails, edit `d3d.yaml` so the host/port/database match `toksearch.sql.mssql.connect_d3drdb`'s defaults.

- [ ] **Step 6: Commit.**

```bash
git add pyproject.toml tests/test_catalog.py
git commit -m "Wire fdp_schema.catalogs entry point (old fdp.devices still active)"
```

End of Phase B. The D3D YAML ships and validates; the new entry-point group is populated; the old code is untouched. Nothing breaks.

---

# Phase C: `fdp` catalog + resolvers

## Task 12: Implement `fdp.catalog._discover` and `_Catalog` (no `TokamakHandle` yet)

**Files:**
- Create: `fdp/fdp/catalog.py`
- Create: `fdp/tests/test_catalog.py`

Build the bottom layer first: entry-point discovery and the lazy-load singleton. `TokamakHandle` (which wraps Tokamak with resolver methods) comes in Task 13.

- [ ] **Step 1: Write the failing tests in `fdp/tests/test_catalog.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for fdp.catalog — discovery + lazy load."""

import unittest
from unittest import mock


def _make_mock_ep(name: str, tokamak_yaml: str):
    """Build a mock entry-point object whose .load() returns a Traversable
    whose .read_text() returns `tokamak_yaml`."""
    ep = mock.MagicMock()
    ep.name = name
    ep.value = f"mock:{name}"
    src = mock.MagicMock()
    src.read_text.return_value = tokamak_yaml
    ep.load.return_value = src
    return ep


class TestDiscover(unittest.TestCase):
    def test_discover_single(self):
        from fdp.catalog import _discover
        ep = _make_mock_ep("d3d", "schema_version: 1\nname: d3d\n")
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            result = _discover()
        self.assertEqual(set(result.keys()), {"d3d"})
        self.assertEqual(result["d3d"].name, "d3d")

    def test_duplicate_name_raises(self):
        from fdp.catalog import _discover
        ep1 = _make_mock_ep("d3d_a", "schema_version: 1\nname: d3d\n")
        ep2 = _make_mock_ep("d3d_b", "schema_version: 1\nname: d3d\n")
        with mock.patch("fdp.catalog.entry_points", return_value=[ep1, ep2]):
            with self.assertRaisesRegex(RuntimeError, "Duplicate tokamak name"):
                _discover()


class TestCatalogSingleton(unittest.TestCase):
    def test_lazy_load_then_cached(self):
        from fdp.catalog import _Catalog
        c = _Catalog()
        ep = _make_mock_ep("x", "schema_version: 1\nname: x\n")
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            tk = c._load()
            self.assertIn("x", tk)
        # Second access should not re-call entry_points
        with mock.patch("fdp.catalog.entry_points") as ep_patch:
            tk2 = c._load()
            ep_patch.assert_not_called()
        self.assertIs(tk, tk2)

    def test_contains(self):
        from fdp.catalog import _Catalog
        c = _Catalog()
        ep = _make_mock_ep("d3d", "schema_version: 1\nname: d3d\n")
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            self.assertIn("d3d", c)
            self.assertNotIn("xyz", c)

    def test_names(self):
        from fdp.catalog import _Catalog
        c = _Catalog()
        eps = [
            _make_mock_ep("d3d", "schema_version: 1\nname: d3d\n"),
            _make_mock_ep("kstar", "schema_version: 1\nname: kstar\n"),
        ]
        with mock.patch("fdp.catalog.entry_points", return_value=eps):
            self.assertEqual(c.names(), ["d3d", "kstar"])
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
pixi run python -m pytest tests/test_catalog.py -v
```

Expected: `ModuleNotFoundError: No module named 'fdp.catalog'`.

- [ ] **Step 3: Create `fdp/fdp/catalog.py` with `_discover` and `_Catalog`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tokamak catalog discovery for fdp.

Reads tokamak YAMLs contributed via the `fdp_schema.catalogs` entry-point
group, validates them against fdp_schema, and exposes them through a
lazy-loaded singleton `catalog`.
"""

from importlib.metadata import entry_points
from fdp_schema import Tokamak, load_tokamak


def _discover() -> dict[str, Tokamak]:
    """Load all contributed tokamak YAMLs from the entry-point group."""
    out: dict[str, Tokamak] = {}
    for ep in entry_points(group="fdp_schema.catalogs"):
        source = ep.load()
        tk = load_tokamak(source)
        if tk.name in out:
            raise RuntimeError(
                f"Duplicate tokamak name {tk.name!r}: a previous entry point "
                f"already contributed it; {ep.value} conflicts."
            )
        out[tk.name] = tk
    return out


class _Catalog:
    """Lazy-loaded registry of tokamaks. Discovery runs on first access."""

    def __init__(self):
        self._cache: dict[str, Tokamak] | None = None

    def _load(self) -> dict[str, Tokamak]:
        if self._cache is None:
            self._cache = _discover()
        return self._cache

    def __contains__(self, name: str) -> bool:
        return name in self._load()

    def __iter__(self):
        return iter(self._load())

    def names(self) -> list[str]:
        return sorted(self._load())


catalog = _Catalog()
```

Note: `__getitem__` is intentionally omitted in this task. It's added in Task 13 once `TokamakHandle` exists.

- [ ] **Step 4: Run the tests to verify they pass.**

```bash
pixi run python -m pytest tests/test_catalog.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit.**

```bash
git add fdp/catalog.py tests/test_catalog.py
git commit -m "Add fdp.catalog discovery and _Catalog singleton"
```

---

## Task 13: Implement `TokamakHandle` and wire into `_Catalog.__getitem__`

**Files:**
- Modify: `fdp/fdp/catalog.py`
- Modify: `fdp/tests/test_catalog.py`

- [ ] **Step 1: Append failing tests to `fdp/tests/test_catalog.py`.**

```python
class TestTokamakHandle(unittest.TestCase):
    YAML = """
schema_version: 1
name: d3d
description: DIII-D
locators:
  - kind: mds_tree
    name: main
    transport: pelican
    search_path: [u1, u2]
  - kind: mds_tree
    name: backup
    transport: pelican
    search_path: [b1]
  - kind: ptdata_indexed
    name: main
    transport: pelican
    index_dir: idx
extra_env: { D3DATA: "yes" }
"""

    def _catalog(self):
        from fdp.catalog import _Catalog
        c = _Catalog()
        ep = _make_mock_ep("d3d", self.YAML)
        return c, ep

    def test_getitem_returns_handle(self):
        from fdp.catalog import TokamakHandle
        c, ep = self._catalog()
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            handle = c["d3d"]
        self.assertIsInstance(handle, TokamakHandle)
        self.assertEqual(handle.name, "d3d")
        self.assertEqual(handle.description, "DIII-D")
        self.assertEqual(handle.extra_env, {"D3DATA": "yes"})

    def test_handle_schema_is_raw_model(self):
        from fdp_schema import Tokamak
        c, ep = self._catalog()
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            handle = c["d3d"]
        self.assertIsInstance(handle.schema, Tokamak)

    def test_locator_default_name_main(self):
        c, ep = self._catalog()
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            handle = c["d3d"]
            loc = handle.locator("mds_tree")  # default name="main"
        self.assertEqual(loc.model.name, "main")

    def test_locator_explicit_name(self):
        c, ep = self._catalog()
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            handle = c["d3d"]
            loc = handle.locator("mds_tree", name="backup")
        self.assertEqual(loc.model.name, "backup")
        self.assertEqual(loc.model.search_path, ["b1"])

    def test_locator_not_found_raises(self):
        c, ep = self._catalog()
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            handle = c["d3d"]
            with self.assertRaises(KeyError):
                handle.locator("sql")  # no sql locator in this fixture

    def test_unknown_tokamak_raises(self):
        c, ep = self._catalog()
        with mock.patch("fdp.catalog.entry_points", return_value=[ep]):
            with self.assertRaises(KeyError):
                c["nonexistent"]
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
pixi run python -m pytest tests/test_catalog.py::TestTokamakHandle -v
```

Expected: ImportError for `TokamakHandle`.

- [ ] **Step 3: Add `TokamakHandle`, `_wrap`, and `__getitem__` to `fdp/fdp/catalog.py`.**

Append:

```python
from fdp_schema import MdsTreeLocator, PtDataIndexedLocator, SqlLocator
from fdp.resolvers import MdsTreeResolver, PtDataResolver, SqlResolver


def _wrap(loc):
    """Dispatch a Locator subtype to its Resolver."""
    return {
        MdsTreeLocator:        MdsTreeResolver,
        PtDataIndexedLocator:  PtDataResolver,
        SqlLocator:            SqlResolver,
    }[type(loc)](loc)


class TokamakHandle:
    """fdp-side wrapper around a fdp_schema.Tokamak. Adds typed resolver
    methods; the underlying schema model is exposed via `.schema` as an
    escape hatch."""

    def __init__(self, model):
        self._model = model

    @property
    def name(self) -> str:        return self._model.name

    @property
    def description(self) -> str: return self._model.description

    @property
    def extra_env(self) -> dict:  return self._model.extra_env

    @property
    def schema(self):             return self._model

    def locator(self, kind: str, name: str = "main"):
        matches = [l for l in self._model.locators
                   if l.kind == kind and l.name == name]
        if not matches:
            raise KeyError(
                f"No locator with kind={kind!r} name={name!r} on {self.name!r}"
            )
        if len(matches) > 1:
            raise KeyError(
                f"Multiple locators with kind={kind!r} name={name!r} on {self.name!r}"
            )
        return _wrap(matches[0])
```

And add the `__getitem__` method to `_Catalog`:

```python
    def __getitem__(self, name: str) -> "TokamakHandle":
        return TokamakHandle(self._load()[name])
```

Note: this task creates an `ImportError` until Task 14 ships the resolver classes. Step 4 below proceeds despite the import failure to make sure tests fail for the right reason (missing resolver imports, not missing TokamakHandle).

- [ ] **Step 4: Run the tests; expect them to fail because resolvers don't exist yet.**

```bash
pixi run python -m pytest tests/test_catalog.py::TestTokamakHandle -v
```

Expected: ImportError on `from fdp.resolvers import ...`. This is fine — Task 14 fixes it.

- [ ] **Step 5: Commit (broken state — fixed in Task 14).**

```bash
git add fdp/catalog.py tests/test_catalog.py
git commit -m "Add TokamakHandle and _Catalog.__getitem__ (depends on resolvers, next task)"
```

---

## Task 14: Implement `MdsTreeResolver` with template expansion

**Files:**
- Create: `fdp/fdp/resolvers/__init__.py`
- Create: `fdp/fdp/resolvers/mds_tree.py`
- Create: `fdp/tests/test_resolvers.py`

- [ ] **Step 1: Create `fdp/fdp/resolvers/__init__.py` with placeholder imports.**

This will be expanded as Tasks 15 and 16 add the other resolvers.

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Resolvers for fdp.catalog locator subtypes. Each resolver wraps a
schema Locator and exposes typed methods appropriate to its backend."""

from .mds_tree import MdsTreeResolver
# from .ptdata import PtDataResolver   # Task 15
# from .sql import SqlResolver         # Task 16


# Temporary placeholders so `from fdp.resolvers import ...` works during
# the staged build. These are replaced in Tasks 15 and 16.
class PtDataResolver:
    def __init__(self, model): raise NotImplementedError("Task 15")


class SqlResolver:
    def __init__(self, model): raise NotImplementedError("Task 16")
```

- [ ] **Step 2: Write failing tests in `fdp/tests/test_resolvers.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for fdp.resolvers — typed per-backend helpers."""

import unittest


class TestMdsTemplateExpansion(unittest.TestCase):
    """The MDSplus path-token convention used by the search_path templates.

    Tokens are single chars after `~`:
      ~t — full shot as decimal
      ~c, ~d, ~e, ~f, ~g, ~h, ~i, ~j — individual digits of the shot
        zero-padded to 8 digits, where ~c is the units digit (rightmost),
        ~d is tens, ..., ~j is 10^7.

    Examples for shot 165920 (zero-padded: "00165920"):
      ~t   → "165920"
      ~c   → "0"   (units)
      ~d   → "2"   (tens)
      ~e   → "9"   (hundreds)
      ~f   → "5"   (thousands)
      ~g   → "6"   (ten-thousands)
      ~h   → "1"   (hundred-thousands)
      ~i   → "0"   (millions)
      ~j   → "0"   (ten-millions)
    """

    def test_full_shot_token(self):
        from fdp.resolvers.mds_tree import _expand_mds_template
        self.assertEqual(_expand_mds_template("x/~t/y", 165920), "x/165920/y")

    def test_individual_digit_tokens(self):
        from fdp.resolvers.mds_tree import _expand_mds_template
        # Shot 165920 → padded "00165920"; c..j = 0,2,9,5,6,1,0,0
        result = _expand_mds_template("~j~i/~h~g/~f~e/~d~c", 165920)
        self.assertEqual(result, "00/16/59/20")

    def test_low_shot(self):
        from fdp.resolvers.mds_tree import _expand_mds_template
        # Shot 5 → padded "00000005"; only ~c is nonzero
        self.assertEqual(_expand_mds_template("d/~t", 5), "d/5")
        self.assertEqual(_expand_mds_template("d/~c", 5), "d/5")
        self.assertEqual(_expand_mds_template("d/~d", 5), "d/0")

    def test_shot_too_large_raises(self):
        from fdp.resolvers.mds_tree import _expand_mds_template
        with self.assertRaises(ValueError):
            _expand_mds_template("~t", 100_000_000)  # 9-digit shot


class TestMdsTreeResolver(unittest.TestCase):
    def _model(self):
        from fdp_schema import MdsTreeLocator
        return MdsTreeLocator(
            name="main",
            transport="pelican",
            search_path=[
                "pelican://h/codes/~t/~j~i/~h~g/~f~e/~d~c",
                "pelican://h/shots/~t",
            ],
        )

    def test_urls_for_expands_all(self):
        from fdp.resolvers.mds_tree import MdsTreeResolver
        r = MdsTreeResolver(self._model())
        urls = r.urls_for(165920)
        self.assertEqual(urls, [
            "pelican://h/codes/165920/00/16/59/20",
            "pelican://h/shots/165920",
        ])

    def test_joined_path_default_delim(self):
        from fdp.resolvers.mds_tree import MdsTreeResolver
        r = MdsTreeResolver(self._model())
        joined = r.joined_path(165920)
        self.assertIn(";", joined)
        self.assertEqual(joined.count(";"), 1)  # 2 URLs, 1 separator

    def test_joined_path_custom_delim(self):
        from fdp.resolvers.mds_tree import MdsTreeResolver
        r = MdsTreeResolver(self._model())
        joined = r.joined_path(165920, delim="|")
        self.assertIn("|", joined)
```

- [ ] **Step 3: Run the tests to verify they fail.**

```bash
pixi run python -m pytest tests/test_resolvers.py::TestMdsTemplateExpansion tests/test_resolvers.py::TestMdsTreeResolver -v
```

Expected: ImportError for `fdp.resolvers.mds_tree`.

- [ ] **Step 4: Create `fdp/fdp/resolvers/mds_tree.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""MdsTreeResolver — typed wrapper for MdsTreeLocator.

Expands MDSplus tree-path tokens (`~t`, `~c`..`~j`) for a given shot. The
expansion is purely lexical — MDSplus's own libraries do the same expansion
at file-open time when consuming `default_tree_path`, but this Python
implementation lets callers compute concrete URLs without going through the
C stack.
"""


def _expand_mds_template(template: str, shot: int) -> str:
    """Expand MDSplus tree-path tokens in `template` for `shot`.

    Tokens (single char after `~`):
      ~t — full shot as decimal string
      ~c..~j — individual digits, zero-padded to 8; ~c=units, ~j=10^7.

    Raises:
      ValueError: if shot exceeds 8 decimal digits (overflows ~j).
    """
    s = str(shot)
    if len(s) > 8:
        raise ValueError(
            f"shot {shot} has more than 8 digits; ~c..~j tokens overflow"
        )
    digits = s.zfill(8)
    # Order doesn't matter (no token is a prefix of another); replace ~t
    # first because it's the most likely to appear and lexically distinct.
    return (
        template
        .replace("~t", s)
        .replace("~c", digits[-1])
        .replace("~d", digits[-2])
        .replace("~e", digits[-3])
        .replace("~f", digits[-4])
        .replace("~g", digits[-5])
        .replace("~h", digits[-6])
        .replace("~i", digits[-7])
        .replace("~j", digits[-8])
    )


class MdsTreeResolver:
    """Resolver for MdsTreeLocator. All methods are pure: no network."""

    def __init__(self, model):
        self.model = model

    def urls_for(self, shot: int) -> list[str]:
        """Return concrete URLs for `shot` (templates expanded in order)."""
        return [_expand_mds_template(t, shot) for t in self.model.search_path]

    def joined_path(self, shot: int, delim: str = ";") -> str:
        """Return the URLs joined by `delim` — the form MDSplus's
        `default_tree_path` env var expects."""
        return delim.join(self.urls_for(shot))
```

- [ ] **Step 5: Run the tests to verify they pass.**

```bash
pixi run python -m pytest tests/test_resolvers.py::TestMdsTemplateExpansion tests/test_resolvers.py::TestMdsTreeResolver -v
```

Expected: all PASS.

- [ ] **Step 6: Re-run the catalog tests to confirm `TokamakHandle` now imports cleanly.**

```bash
pixi run python -m pytest tests/test_catalog.py -v
```

Expected: all `TestTokamakHandle` tests PASS now (the resolver placeholders in `__init__.py` cover `PtDataResolver` and `SqlResolver`; the actual `MdsTreeResolver` works).

- [ ] **Step 7: Commit.**

```bash
git add fdp/resolvers/__init__.py fdp/resolvers/mds_tree.py tests/test_resolvers.py tests/test_catalog.py
git commit -m "Add MdsTreeResolver with MDSplus tree-path token expansion"
```

---

## Task 15: Implement `PtDataResolver`

**Files:**
- Create: `fdp/fdp/resolvers/ptdata.py`
- Modify: `fdp/fdp/resolvers/__init__.py`
- Modify: `fdp/tests/test_resolvers.py`

The PtData JSON index is read over Pelican. Before implementing, **discover the exact index path scheme** by reading the libfdpio C plugin source. The plugin lives in `repos/libfdpio/`; look for code that builds an index file URL from `(PTDATA_JSON_INDEX_DIR, shot)`.

- [ ] **Step 1: Discover the PTData index URL scheme AND the Pelican fetch mechanism.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/libfdpio
grep -rn "JSON_INDEX\|json_index\|PTDATA_JSON\|index_dir" --include="*.c" --include="*.h" --include="*.cpp"
```

Two things to determine:

**(a) Index URL layout.** Find where the C plugin constructs the per-shot
index URL from `PTDATA_JSON_INDEX_DIR` and the shot number. Common shapes:
- `{index_dir}/{shot}.json`
- `{index_dir}/{shot_first_2_digits}/{shot}.json`
- `{index_dir}/{shard_dir}/{shot}.json` with some other shard function

Record the exact layout. The plan below assumes `{index_dir}/{shot}.json`;
**if the layout differs, adjust `_index_url()` accordingly before running
the tests**.

**(b) Fetch mechanism.** The C plugin reads these JSON files via XRootD
(`libXrdCl` with the Pelican plugin). Python doesn't have a stdlib XRootD
client. Three options for fetching from Python:

1. **HTTPS translation** — Pelican origins expose HTTPS in addition to
   XRootD (because `XRDCP_ALLOW_HTTP=true` is set in `_generic_config`).
   Translate `pelican://host:port/path` to `https://<director-or-origin>/path`
   and use `urllib.request.urlopen`. **The exact translation depends on
   Pelican director resolution** and may not be a simple scheme swap.

2. **`pelicanplatform` Python package** — there is a `pelican` Python
   client. Heavier dep, but does Pelican-native resolution.

3. **Subprocess `pelican object get`** — shell out to the Pelican CLI
   that's already installed via `fdp_installer`. Simple and well-tested
   but adds process-spawn overhead.

Probe interactively with a known JSON index URL to pick the simplest
option that works:

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
# Try HTTPS translation against a known shot's index:
pixi run fdp run python -c "
import os
from urllib.request import urlopen, Request
url = os.environ['PTDATA_JSON_INDEX_DIR'] + '/200000.json'
# Try the simplest swap first:
https = url.replace('pelican://', 'https://', 1)
req = Request(https, headers={'Authorization': f\"Bearer {os.environ['BEARER_TOKEN']}\"})
print(urlopen(req).read()[:200])
"
```

Record which approach works. If HTTPS translation works, use it (zero new
deps). If not, prefer subprocess `pelican object get` (already-installed
CLI) over adding `pelicanplatform` as a Python dep. **Update the
`_fetch_index` implementation in Step 4 below to match the chosen
approach.**

- [ ] **Step 2: Write failing tests in `fdp/tests/test_resolvers.py`.**

Append:

```python
class TestPtDataResolver(unittest.TestCase):
    """Tests use mocked network access via mock.patch."""

    def _model(self, with_auth=True):
        from fdp_schema import PtDataIndexedLocator, AuthHint
        kwargs = dict(
            name="main",
            transport="pelican",
            index_dir="pelican://h/idx",
        )
        if with_auth:
            kwargs["auth"] = AuthHint(kind="bearer_token", env="BEARER_TOKEN")
        return PtDataIndexedLocator(**kwargs)

    def test_resolve_returns_url_for_known_pointname(self):
        from fdp.resolvers.ptdata import PtDataResolver
        import os
        from unittest import mock
        r = PtDataResolver(self._model())
        fake_index = {
            "IP": {"ext_location": {".PWR": "pelican://h/data/200000/ip.pwr"}}
        }
        with mock.patch.dict(os.environ, {"BEARER_TOKEN": "x"}):
            with mock.patch.object(r, "_fetch_index", return_value=fake_index):
                url = r.resolve(200000, "ip")
        self.assertEqual(url, "pelican://h/data/200000/ip.pwr")

    def test_resolve_pointname_case_insensitive(self):
        from fdp.resolvers.ptdata import PtDataResolver
        import os
        from unittest import mock
        r = PtDataResolver(self._model())
        fake_index = {
            "IP": {"ext_location": {".PWR": "U1"}}
        }
        with mock.patch.dict(os.environ, {"BEARER_TOKEN": "x"}):
            with mock.patch.object(r, "_fetch_index", return_value=fake_index):
                self.assertEqual(r.resolve(200000, "ip"), "U1")
                self.assertEqual(r.resolve(200000, "Ip"), "U1")
                self.assertEqual(r.resolve(200000, "IP"), "U1")

    def test_resolve_unknown_pointname_returns_none(self):
        from fdp.resolvers.ptdata import PtDataResolver
        import os
        from unittest import mock
        r = PtDataResolver(self._model())
        with mock.patch.dict(os.environ, {"BEARER_TOKEN": "x"}):
            with mock.patch.object(r, "_fetch_index", return_value={}):
                self.assertIsNone(r.resolve(200000, "nonexistent"))

    def test_index_cached_after_first_fetch(self):
        from fdp.resolvers.ptdata import PtDataResolver
        import os
        from unittest import mock
        r = PtDataResolver(self._model())
        with mock.patch.dict(os.environ, {"BEARER_TOKEN": "x"}):
            with mock.patch.object(
                r, "_fetch_index", return_value={"IP": {"ext_location": {".PWR": "U"}}}
            ) as fetch:
                r.resolve(200000, "ip")
                r.resolve(200000, "ip")
                fetch.assert_called_once()

    def test_missing_auth_env_raises(self):
        from fdp.resolvers.ptdata import PtDataResolver
        import os
        from unittest import mock
        r = PtDataResolver(self._model(with_auth=True))
        # Ensure BEARER_TOKEN is unset
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "BEARER_TOKEN"):
                r.resolve(200000, "ip")

    def test_no_auth_allowed_when_locator_has_no_auth(self):
        from fdp.resolvers.ptdata import PtDataResolver
        import os
        from unittest import mock
        r = PtDataResolver(self._model(with_auth=False))
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(
                r, "_fetch_index", return_value={"IP": {"ext_location": {".PWR": "U"}}}
            ):
                # No raise; auth check is skipped when locator.auth is None.
                self.assertEqual(r.resolve(200000, "ip"), "U")

    def test_index_url_construction(self):
        """_index_url builds {index_dir}/{shot}.json (or whatever the
        discovered C-plugin convention is — adjust the assert)."""
        from fdp.resolvers.ptdata import PtDataResolver
        r = PtDataResolver(self._model())
        self.assertEqual(
            r._index_url(200000),
            "pelican://h/idx/200000.json",
        )
```

- [ ] **Step 3: Run the tests; verify they fail.**

```bash
pixi run python -m pytest tests/test_resolvers.py::TestPtDataResolver -v
```

Expected: ImportError or assertion failures (the placeholder `PtDataResolver` in `__init__.py` raises `NotImplementedError`).

- [ ] **Step 4: Create `fdp/fdp/resolvers/ptdata.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""PtDataResolver — reads the Pelican-hosted PTData JSON index.

The index files mirror the format consumed by libfdpio's C plugin. Each
shot has a JSON file shaped roughly:

    {
      "POINTNAME_UPPERCASE": {
        "ext_location": { ".PWR": "pelican://.../shot/pointname.pwr", ... }
      },
      ...
    }

This Python resolver lets explicit callers (e.g., MCP servers, agents)
query the index without going through the C plugin. The C plugin keeps
working in parallel for the env-var-based access path.
"""

import json
import os
from urllib.request import Request, urlopen


class PtDataResolver:
    """Resolver for PtDataIndexedLocator. Uses network I/O on first
    access; caches the per-shot index in process memory."""

    def __init__(self, model):
        self.model = model
        self._index_cache: dict[int, dict] = {}

    def resolve(
        self, shot: int, pointname: str, ext: str = ".PWR"
    ) -> str | None:
        """Return the shotfile URL for `(shot, pointname, ext)`, or None
        if no matching entry is found."""
        self._check_auth()
        if shot not in self._index_cache:
            self._index_cache[shot] = self._fetch_index(shot)
        idx = self._index_cache[shot]
        entry = idx.get(pointname.upper(), {})
        return entry.get("ext_location", {}).get(ext)

    def _index_url(self, shot: int) -> str:
        # NOTE: This convention was confirmed against libfdpio's C plugin
        # in Task 15 Step 1. If the C plugin uses sharding (e.g.,
        # {index_dir}/{shot[:3]}/{shot}.json), update here accordingly.
        return f"{self.model.index_dir}/{shot}.json"

    def _fetch_index(self, shot: int) -> dict:
        url = self._index_url(shot)
        headers = {}
        if self.model.auth and self.model.auth.kind == "bearer_token":
            token = os.environ.get(self.model.auth.env or "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        # urllib supports https; Pelican URLs need to be translated to
        # https for plain urllib access. Production deployments use
        # XRootD instead; for v1 the Python resolver uses HTTPS directly.
        # NOTE: confirm pelican://... URLs are accessible via https://...
        # by replacing the scheme; if not, adjust.
        https_url = url.replace("pelican://", "https://", 1)
        req = Request(https_url, headers=headers)
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _check_auth(self):
        auth = self.model.auth
        if auth and auth.env and not os.environ.get(auth.env):
            raise RuntimeError(
                f"PtData auth: env var {auth.env!r} must be set "
                f"(needed for locator {self.model.name!r})"
            )
```

- [ ] **Step 5: Update `fdp/fdp/resolvers/__init__.py` to import the real class.**

Replace the `PtDataResolver` placeholder with:

```python
from .ptdata import PtDataResolver
```

- [ ] **Step 6: Run the tests to verify they pass.**

```bash
pixi run python -m pytest tests/test_resolvers.py::TestPtDataResolver -v
```

Expected: all PASS.

- [ ] **Step 7: Commit.**

```bash
git add fdp/resolvers/__init__.py fdp/resolvers/ptdata.py tests/test_resolvers.py
git commit -m "Add PtDataResolver with Pelican-backed JSON index reader"
```

---

## Task 16: Implement `SqlResolver` (pymssql + password file)

**Files:**
- Create: `fdp/fdp/resolvers/sql.py`
- Modify: `fdp/fdp/resolvers/__init__.py`
- Modify: `fdp/tests/test_resolvers.py`

- [ ] **Step 1: Append failing tests to `fdp/tests/test_resolvers.py`.**

```python
class TestSqlResolver(unittest.TestCase):
    def _model(self, **overrides):
        from fdp_schema import SqlLocator, AuthHint
        kw = dict(
            name="d3drdb",
            driver="mssql",
            host="d3drdb.gat.com",
            port=8001,
            database="d3drdb",
            tdsver="7.0",
            auth=AuthHint(kind="password_file", path="~/.D3DRDB.login"),
        )
        kw.update(overrides)
        return SqlLocator(**kw)

    def test_connect_calls_pymssql(self):
        from unittest import mock
        from fdp.resolvers.sql import SqlResolver

        r = SqlResolver(self._model())
        with mock.patch.object(
            r, "_read_credential", return_value=("user", "pw")
        ):
            with mock.patch("pymssql.connect") as connect:
                r.connect()
        connect.assert_called_once_with(
            "d3drdb.gat.com", "user", "pw", "d3drdb", port="8001"
        )

    def test_connect_sets_tdsver(self):
        import os
        from unittest import mock
        from fdp.resolvers.sql import SqlResolver

        r = SqlResolver(self._model())
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(
                r, "_read_credential", return_value=("u", "p")
            ):
                with mock.patch("pymssql.connect"):
                    r.connect()
            self.assertEqual(os.environ.get("TDSVER"), "7.0")

    def test_connect_setdefault_does_not_override_tdsver(self):
        import os
        from unittest import mock
        from fdp.resolvers.sql import SqlResolver

        r = SqlResolver(self._model(tdsver="7.0"))
        with mock.patch.dict(os.environ, {"TDSVER": "8.0"}, clear=True):
            with mock.patch.object(
                r, "_read_credential", return_value=("u", "p")
            ):
                with mock.patch("pymssql.connect"):
                    r.connect()
            # setdefault: pre-existing 8.0 is kept.
            self.assertEqual(os.environ["TDSVER"], "8.0")

    def test_connect_explicit_credentials(self):
        from unittest import mock
        from fdp.resolvers.sql import SqlResolver

        r = SqlResolver(self._model())
        with mock.patch("pymssql.connect") as connect:
            r.connect(username="explicit_user", password="explicit_pw")
        connect.assert_called_once_with(
            "d3drdb.gat.com", "explicit_user", "explicit_pw", "d3drdb",
            port="8001",
        )

    def test_read_credential_from_password_file(self, ):
        from unittest import mock
        from fdp.resolvers.sql import SqlResolver
        r = SqlResolver(self._model())
        with mock.patch(
            "pathlib.Path.read_text", return_value="theuser\nthepass\n"
        ):
            u, p = r._read_credential()
        self.assertEqual((u, p), ("theuser", "thepass"))

    def test_unsupported_driver_raises(self):
        from unittest import mock
        from fdp.resolvers.sql import SqlResolver
        r = SqlResolver(self._model(driver="postgres"))
        with self.assertRaises(NotImplementedError):
            r.connect()
```

- [ ] **Step 2: Run the tests; verify they fail.**

```bash
pixi run python -m pytest tests/test_resolvers.py::TestSqlResolver -v
```

Expected: NotImplementedError (the placeholder in `__init__.py`).

- [ ] **Step 3: Create `fdp/fdp/resolvers/sql.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""SqlResolver — opens a SQL connection from a SqlLocator.

v1 implements driver="mssql" only, via pymssql. Other drivers raise
NotImplementedError. Credential resolution supports:
  - auth.kind="password_file": two-line file (username, password)
  - explicit username= / password= kwargs to connect()
"""

import os
from pathlib import Path


class SqlResolver:
    def __init__(self, model):
        self.model = model

    def connect(self, username: str | None = None, password: str | None = None):
        if self.model.driver != "mssql":
            raise NotImplementedError(
                f"SqlResolver.connect: driver={self.model.driver!r} "
                f"not supported in v1; only 'mssql' is implemented."
            )
        if self.model.tdsver:
            # setdefault preserves a user-provided TDSVER if already set
            # (e.g., by fdp's _generic_config).
            os.environ.setdefault("TDSVER", self.model.tdsver)
        if password is None:
            username, password = self._read_credential()
        import pymssql
        return pymssql.connect(
            self.model.host, username, password, self.model.database,
            port=str(self.model.port) if self.model.port else None,
        )

    def _read_credential(self) -> tuple[str, str]:
        auth = self.model.auth
        if auth and auth.kind == "password_file" and auth.path:
            text = Path(os.path.expanduser(auth.path)).read_text()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return lines[0], lines[1]
        raise RuntimeError(
            f"SqlResolver: no credential source for locator {self.model.name!r} "
            f"(auth must be kind=password_file with a path, or pass "
            f"username/password explicitly to connect())"
        )
```

- [ ] **Step 4: Update `fdp/fdp/resolvers/__init__.py` to import the real class.**

Replace the `SqlResolver` placeholder with:

```python
from .sql import SqlResolver
```

Also remove the now-unused placeholder block. Final `__init__.py` should be:

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Resolvers for fdp.catalog locator subtypes."""

from .mds_tree import MdsTreeResolver
from .ptdata import PtDataResolver
from .sql import SqlResolver

__all__ = ["MdsTreeResolver", "PtDataResolver", "SqlResolver"]
```

- [ ] **Step 5: Run all resolver tests to verify they pass.**

```bash
pixi run python -m pytest tests/test_resolvers.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run all catalog tests to make sure nothing regressed.**

```bash
pixi run python -m pytest tests/test_catalog.py tests/test_resolvers.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit.**

```bash
git add fdp/resolvers/__init__.py fdp/resolvers/sql.py tests/test_resolvers.py
git commit -m "Add SqlResolver (pymssql, password-file auth)"
```

---

## Task 17: Integration smoke — `fdp.catalog["d3d"]` returns a real handle

**Files:**
- Modify: `fdp/tests/test_catalog.py`

This is an integration test that exercises the full path: real
`fdp_schema.catalogs` entry points (contributed by the
`toksearch_d3d` editable install from Task 8) → `_discover()` → real
`Tokamak` → real `TokamakHandle` → real resolvers. No mocking.

- [ ] **Step 1: Append the integration test to `fdp/tests/test_catalog.py`.**

```python
class TestCatalogIntegration(unittest.TestCase):
    """End-to-end with the real toksearch_d3d entry point installed."""

    def test_d3d_handle_exposes_real_locators(self):
        from fdp.catalog import catalog
        tk = catalog["d3d"]
        self.assertEqual(tk.name, "d3d")
        self.assertIn("D3DATA", tk.extra_env)

    def test_d3d_mds_tree_resolver_works(self):
        from fdp.catalog import catalog
        from fdp.resolvers.mds_tree import MdsTreeResolver
        loc = catalog["d3d"].locator("mds_tree")
        self.assertIsInstance(loc, MdsTreeResolver)
        urls = loc.urls_for(165920)
        self.assertEqual(len(urls), 4)  # four D3D search-path entries
        # Tokens should be expanded — no ~ in concrete URLs
        for u in urls:
            self.assertNotIn("~", u)

    def test_d3d_sql_locator_metadata_present(self):
        from fdp.catalog import catalog
        from fdp.resolvers.sql import SqlResolver
        loc = catalog["d3d"].locator("sql", name="d3drdb")
        self.assertIsInstance(loc, SqlResolver)
        self.assertEqual(loc.model.host, "d3drdb.gat.com")
        self.assertEqual(loc.model.port, 8001)
        self.assertEqual(loc.model.database, "d3drdb")
        self.assertEqual(loc.model.tdsver, "7.0")
```

- [ ] **Step 2: Run the integration test.**

```bash
pixi run python -m pytest tests/test_catalog.py::TestCatalogIntegration -v
```

Expected: all PASS. (`toksearch_d3d` was installed editable in Task 8 with the new entry point added in Task 11.)

- [ ] **Step 3: Commit.**

```bash
git add tests/test_catalog.py
git commit -m "Add catalog integration test against real toksearch_d3d entry point"
```

End of Phase C. The new catalog API works against real data. Old code still in place.

---

# Phase D: Rewire `fdp run` / `fdp env` to use the catalog

## Task 18: Implement `_tokamak_env()` with parity test

**Files:**
- Modify: `fdp/fdp/environment.py`
- Create: `fdp/tests/test_env_parity.py`

This is the **most important task** in the plan. The parity fixture pins the env-var contract forever.

- [ ] **Step 1: Read `fdp/tests/_d3d_to_env_capture.json` from Task 9 to verify the captured ground truth.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
cat tests/_d3d_to_env_capture.json
```

Note the exact strings — copy them verbatim into the test fixture in Step 3 below. Do not re-derive or re-format them.

- [ ] **Step 2: Add `_tokamak_env` to `fdp/fdp/environment.py`.**

Locate `_generic_config()` in `fdp/fdp/environment.py:59-87`. Below it (and below any other existing functions), append:

```python


def _tokamak_env(handle) -> dict[str, str]:
    """Derive tokamak-specific env vars from a TokamakHandle's locators.

    Output mirrors the legacy Device.to_env() for D3D byte-for-byte —
    pinned by test_env_parity.py.
    """
    out: dict[str, str] = {}
    delim = handle.extra_env.get("SYS_D3_DELIM", ";")

    # default_tree_path = delim-joined search_path entries from all
    # mds_tree locators (v1: one per tokamak, but the schema permits more).
    mds = [l for l in handle.schema.locators if l.kind == "mds_tree"]
    if mds:
        out["default_tree_path"] = delim.join(
            p for m in mds for p in m.search_path
        )

    # PTDATA_JSON_INDEX_DIR — last ptdata_indexed wins if multiple.
    ptd = [l for l in handle.schema.locators if l.kind == "ptdata_indexed"]
    if ptd:
        out["PTDATA_JSON_INDEX_DIR"] = ptd[-1].index_dir

    # mssql TDSVER override (generic config defaults to "7.0"; locator
    # value, if set, takes precedence in the per-tokamak dict).
    for s in handle.schema.locators:
        if s.kind == "sql" and s.driver == "mssql" and s.tdsver:
            out["TDSVER"] = s.tdsver

    # extra_env passes through verbatim.
    out.update(handle.extra_env)
    return out
```

Note: `_tokamak_env` is added side-by-side with the existing `Device`-based code. Switching `apply_environment` to use it happens in Task 19.

- [ ] **Step 3: Write `fdp/tests/test_env_parity.py`.**

Use the captured fixture values from Step 1. Adjust the dict below to match the JSON capture exactly — typos here defeat the test's purpose.

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Pinned env-var parity test.

This test asserts that the new catalog-driven _tokamak_env() emits exactly
the same dict that the legacy D3D_DEVICE.to_env() produced. The fixture
was captured during planning (see tests/_d3d_to_env_capture.json) before
D3D_DEVICE was deleted.

If you edit toksearch_d3d/data/d3d.yaml and this test breaks, the test is
doing its job. Either:
  - the YAML edit was intentional (update the fixture)
  - the YAML edit broke env-var compatibility (revert the edit)
"""

import unittest


# Captured 2026-06-XX from `D3D_DEVICE.to_env()`. Do not edit casually.
EXPECTED_D3D_ENV = {
    "default_tree_path": (
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c;"
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t;"
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t;"
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c"
    ),
    "PTDATA_JSON_INDEX_DIR": (
        "pelican://osg-htc.org:443/fdp-d3d/archives/index/json/"
        "json_indexes_2026-01-13_12:22:11"
    ),
    "D3DATA": "yes",
    "SYS_D3_DELIM": ";",
    "CAKE_DB_PATH": (
        "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db"
    ),
    # TDSVER: 7.0 IS captured from the catalog's SqlLocator. _tokamak_env
    # emits it, then _generic_config sets it as a default. Both happen to
    # be "7.0" today; the catalog wins.
    "TDSVER": "7.0",
}


class TestEnvParity(unittest.TestCase):
    def test_d3d_env_matches_captured_fixture(self):
        from fdp.environment import _tokamak_env
        from fdp.catalog import catalog
        got = _tokamak_env(catalog["d3d"])
        self.assertEqual(got, EXPECTED_D3D_ENV)
```

**Important:** if Task 9's capture did NOT include TDSVER (because `D3D_DEVICE` didn't set it — it's only set by `_generic_config`), then remove `TDSVER` from `EXPECTED_D3D_ENV` AND remove the SqlLocator TDSVER-emission branch from `_tokamak_env`. The whole point of the fixture is that it's the ground truth — match it, don't argue with it.

- [ ] **Step 4: Run the parity test.**

```bash
pixi run python -m pytest tests/test_env_parity.py -v
```

Expected: PASS. If it fails, the YAML's URLs or extra_env differ from the captured fixture. Fix the YAML, not the fixture.

- [ ] **Step 5: Commit.**

```bash
git add fdp/environment.py tests/test_env_parity.py
git commit -m "Add _tokamak_env with pinned D3D parity fixture"
```

---

## Task 19: Switch `apply_environment` and the CLI to the catalog

**Files:**
- Modify: `fdp/fdp/environment.py`
- Modify: `fdp/fdp/cli.py`
- Modify: `fdp/fdp/__init__.py`
- Modify: `fdp/tests/test_catalog.py`

- [ ] **Step 1: Update `apply_environment` in `fdp/fdp/environment.py` to call `_tokamak_env(catalog[name])` instead of `Device.to_env()`.**

Find the current `apply_environment` (or whatever the wrapper function is named — confirm by reading the file). Replace the device-resolution + `to_env()` call with:

```python
from .catalog import catalog


def apply_environment(tokamak_name: str | None = None) -> dict[str, str]:
    """Merge generic config + tokamak-specific config into os.environ.

    Returns the merged dict for callers that want to print or inspect.
    """
    cfg = _generic_config()
    if tokamak_name:
        cfg.update(_tokamak_env(catalog[tokamak_name]))
    import os
    os.environ.update(cfg)
    return cfg
```

The exact function signature must match what existed before (likely `apply_environment` or `setup_environment` — preserve the name and signature). If the current signature is `apply_environment(device_name=None)`, rename the parameter to `tokamak_name` but accept a positional `device_name` argument as the same thing for back-compat within fdp's own code; the public CLI interface stays `-d` for now.

- [ ] **Step 2: Update `fdp/fdp/cli.py`:**

  - Remove the `fdp devices` subcommand handler.
  - Add `fdp catalog list` and `fdp catalog show <name>` subcommands.

Find the `do_devices` function (or similar) and the subparser entry for `devices`. Delete both. Add:

```python
def do_catalog(args):
    from .catalog import catalog
    if args.subcmd == "list":
        for name in catalog.names():
            tk = catalog[name]
            print(f"{name}\t{tk.description}")
    elif args.subcmd == "show":
        tk = catalog[args.name]
        import yaml
        print(yaml.safe_dump(tk.schema.model_dump(), sort_keys=False))
    else:
        raise ValueError(f"Unknown catalog subcommand: {args.subcmd!r}")
```

Wire it into the argparse:

```python
cat = subparsers.add_parser("catalog", help="Inspect the tokamak catalog")
cat_sub = cat.add_subparsers(dest="subcmd", required=True)
cat_sub.add_parser("list", help="List tokamak names and descriptions")
show = cat_sub.add_parser("show", help="Print a tokamak's full catalog YAML")
show.add_argument("name")
cat.set_defaults(func=do_catalog)
```

- [ ] **Step 3: Update `fdp/fdp/__init__.py`.**

  - Remove any `from .devices import Device` re-export.
  - Add `from .catalog import catalog`.

- [ ] **Step 4: Add a CLI snapshot test to `fdp/tests/test_catalog.py`.**

Append:

```python
class TestCatalogCli(unittest.TestCase):
    def test_catalog_list_prints_d3d(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from fdp.cli import main as cli_main
        with redirect_stdout(StringIO()) as buf:
            cli_main(["catalog", "list"])
        output = buf.getvalue()
        self.assertIn("d3d", output)
        self.assertIn("DIII-D", output)

    def test_catalog_show_d3d_includes_locators(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from fdp.cli import main as cli_main
        with redirect_stdout(StringIO()) as buf:
            cli_main(["catalog", "show", "d3d"])
        output = buf.getvalue()
        self.assertIn("mds_tree", output)
        self.assertIn("ptdata_indexed", output)
        self.assertIn("d3drdb", output)
```

If `fdp.cli.main` takes argv differently than this test assumes, adjust the call signature.

- [ ] **Step 5: Run all fdp tests to confirm the switchover.**

```bash
pixi run python -m pytest tests/ -v
```

Expected: all PASS, including the parity test from Task 18.

- [ ] **Step 6: Sanity-check `fdp env` and `fdp run` from the shell.**

```bash
pixi run fdp env -d d3d | head -30
```

Expected: prints export statements including `default_tree_path`,
`PTDATA_JSON_INDEX_DIR`, `D3DATA`, `SYS_D3_DELIM`, `CAKE_DB_PATH` — the same as before the rewrite.

```bash
pixi run fdp run python -c "import os; print(os.environ.get('default_tree_path', '<unset>'))"
```

Expected: prints the same semicolon-joined URL list as before.

- [ ] **Step 7: Commit.**

```bash
git add fdp/environment.py fdp/cli.py fdp/__init__.py tests/test_catalog.py
git commit -m "Switch fdp run/env to catalog; replace fdp devices with fdp catalog"
```

End of Phase D. `fdp` now uses the catalog as the source of truth, but `fdp.devices` and `toksearch_d3d.fdp.D3D_DEVICE` still exist alongside.

---

# Phase E: Old code removal + run-dep cleanup

## Task 20: Delete `fdp/fdp/devices.py` and `tests/test_devices.py`

**Files:**
- Delete: `fdp/fdp/devices.py`
- Delete: `fdp/tests/test_devices.py` (if exists)

- [ ] **Step 1: Confirm no remaining imports in `fdp/`.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
grep -rn "from .devices\|from fdp.devices\|import devices\b" --include="*.py"
```

Expected: no results (after Task 19's edits). If anything remains, fix it before deleting.

- [ ] **Step 2: Delete the files.**

```bash
git rm fdp/devices.py
git rm tests/test_devices.py 2>/dev/null || true
```

- [ ] **Step 3: Run the full fdp test suite.**

```bash
pixi run python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 4: Commit.**

```bash
git commit -m "Delete fdp.devices module and tests (superseded by fdp.catalog)"
```

---

## Task 21: Delete `toksearch_d3d/toksearch_d3d/fdp.py` and remove the old entry point

**Files:**
- Delete: `toksearch_d3d/toksearch_d3d/fdp.py`
- Modify: `toksearch_d3d/pyproject.toml`

- [ ] **Step 1: Grep for any remaining imports of `toksearch_d3d.fdp` inside `toksearch_d3d/`.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
grep -rn "from toksearch_d3d.fdp\|from toksearch_d3d\.fdp\|import toksearch_d3d.fdp" --include="*.py"
```

Note: `toksearch_d3d/CLAUDE.md` references `toksearch_d3d.fdp.cli` but that string is already stale (the fdp CLI moved to the `fdp` package); it's not a Python import. CLAUDE.md will be updated in Task 25.

If any real Python imports remain (likely zero — the `D3D_DEVICE` was only consumed by `fdp.devices` discovery), delete or update those files.

- [ ] **Step 2: Delete the file.**

```bash
git rm toksearch_d3d/fdp.py
```

- [ ] **Step 3: Remove the `[project.entry-points."fdp.devices"]` block from `toksearch_d3d/pyproject.toml`.**

Find and delete the lines:

```toml
[project.entry-points."fdp.devices"]
d3d = "toksearch_d3d.fdp:D3D_DEVICE"
```

Leave the new `[project.entry-points."fdp_schema.catalogs"]` block alone.

- [ ] **Step 4: Reinstall to refresh entry-point metadata.**

```bash
pixi install
```

- [ ] **Step 5: Run the toksearch_d3d catalog test to confirm the new entry point is still wired.**

```bash
pixi run python -m pytest tests/test_catalog.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add pyproject.toml
git commit -m "Delete toksearch_d3d.fdp module; remove fdp.devices entry point"
```

---

## Task 22: Drop `fdp` run-dep from `toksearch_d3d`

**Files:**
- Modify: `toksearch_d3d/pyproject.toml`
- Modify: `toksearch_d3d/recipe/recipe.yaml`

- [ ] **Step 1: Read `toksearch_d3d/pyproject.toml` to locate the `fdp` line in `[project.dependencies]` (or `[project]` `dependencies = [...]`).**

```bash
grep -n "fdp" pyproject.toml
```

- [ ] **Step 2: Remove the `fdp` (or `fdp>=...`) entry from the dependencies list.**

Use Edit to delete just that line. Do **not** remove `fdp_schema` — we don't add it here because toksearch_d3d's contribution is data-only (no fdp_schema import at runtime).

- [ ] **Step 3: Mirror the change in `toksearch_d3d/recipe/recipe.yaml`.**

Locate the `run:` requirements block. Remove the `- fdp` (or similar) entry.

- [ ] **Step 4: Verify no Python imports of `fdp` remain in toksearch_d3d.**

```bash
grep -rn "^import fdp\|^from fdp " --include="*.py" toksearch_d3d/
```

Expected: no results.

- [ ] **Step 5: Reinstall and run the test suite.**

```bash
pixi install
pixi run python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 6: Commit.**

```bash
git add pyproject.toml recipe/recipe.yaml
git commit -m "Drop fdp run-dep from toksearch_d3d"
```

---

## Task 23: Add `fdp-schema` + `toksearch` run-deps to `fdp`

**Files:**
- Modify: `fdp/pyproject.toml`
- Modify: `fdp/recipe/recipe.yaml`

This task makes the `fdp` package's dependency declarations honest. `fdp-schema` is new; `toksearch` was always needed at runtime by `fdp chat`/`fdp query` (which execvpe into `python -m toksearch.llm.cli`) but never declared.

- [ ] **Step 1: Add `fdp-schema` and `toksearch` to `fdp/pyproject.toml`.**

In the `[project.dependencies]` block (or equivalent), add:

```toml
dependencies = [
    # ... existing entries ...
    "fdp-schema",
    "toksearch",
]
```

- [ ] **Step 2: Add them to `fdp/recipe/recipe.yaml`.**

Locate the `run:` block and add:

```yaml
run:
  - python >=3.11
  # ... existing entries ...
  - fdp-schema
  - toksearch
```

- [ ] **Step 3: Reinstall and re-run all fdp tests.**

```bash
pixi install
pixi run python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 4: Commit.**

```bash
git add pyproject.toml recipe/recipe.yaml
git commit -m "Add fdp-schema and toksearch as honest run-deps for fdp"
```

End of Phase E. All old code is gone; deps are accurate.

---

# Phase F: Sync test + docs

## Task 24: Add the SQL locator sync test in `toksearch_d3d`

**Files:**
- Create: `toksearch_d3d/tests/test_sql_sync.py`

Phase 1 leaves `connect_d3drdb()` with its hardcoded host/port/db defaults to avoid the `toksearch → fdp` cycle (see spec Non-Goals). This test catches drift between the YAML's `SqlLocator` and those hardcoded defaults.

- [ ] **Step 1: Write the test.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Sync test: keep the d3d.yaml SqlLocator aligned with the hardcoded
defaults in toksearch.sql.mssql.connect_d3drdb.

This test exists because Phase 1 of the fdp-schema migration could not
migrate connect_d3drdb() to use the catalog (it would create a toksearch
→ fdp dependency cycle). The two sources of truth (hardcoded defaults vs
catalog) must stay aligned; this test fails loudly if either drifts.

Resolving the duplication permanently is tracked as follow-up work; see
the design spec's Non-Goals section.
"""

import unittest
from inspect import signature


class TestSqlLocatorSync(unittest.TestCase):
    def test_d3d_sql_locator_matches_connect_d3drdb_defaults(self):
        from fdp_schema import load_tokamak
        from toksearch_d3d.data import d3d_yaml
        from toksearch.sql.mssql import connect_d3drdb

        t = load_tokamak(d3d_yaml)
        sql = next(l for l in t.locators
                   if l.kind == "sql" and l.name == "d3drdb")

        sig = signature(connect_d3drdb)
        self.assertEqual(sql.host,     sig.parameters["host"].default,
                         "Catalog SqlLocator.host drifted from connect_d3drdb default")
        self.assertEqual(sql.port,     sig.parameters["port"].default,
                         "Catalog SqlLocator.port drifted from connect_d3drdb default")
        self.assertEqual(sql.database, sig.parameters["db"].default,
                         "Catalog SqlLocator.database drifted from connect_d3drdb default")
```

- [ ] **Step 2: Run the test.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
pixi run python -m pytest tests/test_sql_sync.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add tests/test_sql_sync.py
git commit -m "Add sync test for d3d.yaml SqlLocator vs connect_d3drdb defaults"
```

---

## Task 25: Update `toksearch_d3d/CLAUDE.md`

**Files:**
- Modify: `toksearch_d3d/CLAUDE.md`

- [ ] **Step 1: Read the current CLAUDE.md and locate stale or now-incorrect content.**

Read `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/CLAUDE.md`. Identify:

  - The mention of `toksearch_d3d.fdp.cli` (stale — the fdp CLI moved to the separate `fdp` package previously).
  - Any reference to `D3D_DEVICE` or `fdp.devices`.

- [ ] **Step 2: Replace stale sections.**

In the "Architecture" section, replace the `toksearch_d3d.fdp.cli` bullet with a sentence noting that catalog data is now shipped via `toksearch_d3d.data` and the `fdp_schema.catalogs` entry-point group. Example replacement bullet:

```markdown
- **`toksearch_d3d.data`** — Ships `d3d.yaml`, the D3D tokamak catalog,
  declared via the `fdp_schema.catalogs` entry-point group. Consumed by
  `fdp.catalog` at runtime.
```

In "Key Dependencies", drop the `fdp` line if present and add `fdp_schema`.

- [ ] **Step 3: Commit.**

```bash
git add CLAUDE.md
git commit -m "Update CLAUDE.md for catalog migration"
```

---

## Task 26: Update top-level `repos/CLAUDE.md`

**Files:**
- Modify: `repos/CLAUDE.md`

- [ ] **Step 1: Read the file and locate any references to `fdp.Device`, `fdp.devices`, or `D3D_DEVICE`.**

```bash
grep -n "Device\|devices" /fusion/projects/dt/sammuli/fdp_dev/repos/CLAUDE.md
```

- [ ] **Step 2: Replace references with catalog-API equivalents.**

For each occurrence:
  - Replace `fdp.Device` / `fdp.devices` with `fdp.catalog`.
  - Mention `fdp_schema` in the package list (between `xrdcl-pelican` and `fdp`).

If the file has a "Repository Map" section, add a row for `fdp_schema`:

```markdown
| `fdp_schema` | Package-neutral pydantic schema for tokamak data locator
  catalogs (Tokamak, Locator, AuthHint). Consumed by `fdp`; contributed to
  by tokamak-specific packages like `toksearch_d3d`. |
```

Update the Conda Channel section's package list to include `fdp-schema`.

- [ ] **Step 3: Commit.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos
git add CLAUDE.md
git commit -m "Update repo-level CLAUDE.md for fdp_schema and catalog migration"
```

End of Phase F. Documentation reflects the new world.

---

# Phase G: Conda packaging + release

## Task 27: Conda recipe and CI for `fdp_schema`

**Files:**
- Create: `fdp_schema/recipe/recipe.yaml`
- Create: `fdp_schema/recipe/run_build.sh`
- Create: `fdp_schema/recipe/print_version.py`
- Create: `fdp_schema/.github/workflows/conda_build.yaml`

Pattern source: copy from `repos/fdp/recipe/` and `repos/fdp/.github/workflows/conda_build.yaml`, then adapt.

- [ ] **Step 1: Copy templates from fdp.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema
mkdir -p .github/workflows
cp /fusion/projects/dt/sammuli/fdp_dev/repos/fdp/recipe/run_build.sh recipe/run_build.sh
cp /fusion/projects/dt/sammuli/fdp_dev/repos/fdp/recipe/print_version.py recipe/print_version.py
cp /fusion/projects/dt/sammuli/fdp_dev/repos/fdp/recipe/recipe.yaml recipe/recipe.yaml
cp /fusion/projects/dt/sammuli/fdp_dev/repos/fdp/.github/workflows/conda_build.yaml .github/workflows/conda_build.yaml
```

- [ ] **Step 2: Edit `recipe/recipe.yaml` for fdp_schema specifics.**

Set:
- `package.name: fdp-schema`
- `source.path: ..`
- `build.entry_points`: empty (no CLI)
- `requirements.host`: `python >=3.11`, `pip`, `setuptools`, `versioneer`
- `requirements.run`: `python >=3.11`, `pydantic >=2`, `pyyaml`
- `tests`: `import fdp_schema` and run `pytest` if feasible

Example (adjust based on fdp's actual recipe.yaml structure):

```yaml
context:
  name: fdp-schema
  version: ${{ env.get("PKG_VERSION") }}

package:
  name: ${{ name }}
  version: ${{ version }}

source:
  path: ..

build:
  number: 0
  noarch: python
  script:
    - pip install . --no-deps --no-build-isolation -vv

requirements:
  host:
    - python >=3.11
    - pip
    - setuptools
    - versioneer
  run:
    - python >=3.11
    - pydantic >=2
    - pyyaml

tests:
  - python:
      imports:
        - fdp_schema
```

- [ ] **Step 3: Edit `.github/workflows/conda_build.yaml` for fdp_schema.**

The fdp workflow uploads to `ga-fdp` channel on `release-*` tags. Keep that pattern. Update any package-name references from `fdp` to `fdp-schema`.

- [ ] **Step 4: Verify the build runs locally.**

```bash
cd recipe && bash run_build.sh
```

Expected: rattler-build produces a `.conda` artifact under `recipe/output/`.

- [ ] **Step 5: Commit.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema
git add recipe/ .github/
git commit -m "Add rattler-build recipe and conda_build CI for fdp_schema"
```

---

## Task 28: Release-tag and version bumps across three packages

**Files:**
- Modify: `fdp/pyproject.toml` (version bump, if hardcoded)
- Modify: `toksearch_d3d/pyproject.toml` (version bump, if hardcoded)

Versioneer reads git tags with prefix `release-`. So bumps are primarily a tagging operation. Verify each package uses versioneer first.

- [ ] **Step 1: Tag `fdp_schema 0.1.0`.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema
git tag release-0.1.0
```

Do NOT push yet — the user reviews tags before pushing.

- [ ] **Step 2: Tag `fdp 0.2.0`.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
git tag release-0.2.0
```

- [ ] **Step 3: Tag `toksearch_d3d 0.5.0`.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git tag release-0.5.0
```

- [ ] **Step 4: Verify versioneer picks up each new tag.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema
pixi run python -c "import fdp_schema; print(fdp_schema.__version__)"

cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
pixi run python -c "import fdp; print(fdp.__version__)"

cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
pixi run python -c "import toksearch_d3d; print(toksearch_d3d.__version__)"
```

Expected: each prints the new version.

- [ ] **Step 5: Run all three test suites one more time.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema && pixi run pytest -v
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && pixi run pytest -v
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run pytest -v
```

Expected: all PASS.

- [ ] **Step 6: Run the end-to-end installer test.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_installer
pixi run bash -c 'cd tests && python testit.py'
```

Expected: all integration tests PASS. **If this fails, env-var parity broke.** Investigate.

- [ ] **Step 7: Stop here. Hand back to user for review of tags before pushing.**

Do not push tags or commits to remote. The user reviews tag state, then pushes manually:

```bash
# (User runs these after review:)
cd fdp_schema && git push && git push --tags
cd ../fdp && git push && git push --tags
cd ../toksearch_d3d && git push && git push --tags
```

This triggers the conda_build CI in each repo, which uploads to the `ga-fdp` channel.

End of Phase G. Phase 1 is shipped.

---

## Notes for the executing engineer

- **TDD discipline:** every code-bearing task starts with a failing test, then minimal code to pass it. Don't write helpers "just in case." If a step doesn't have a test, it's a refactor or a config change — those don't need tests but should be verified by running existing tests after.

- **Commit cadence:** one commit per task at minimum, more often if the task has natural sub-units. The plan's commit boundaries are minima.

- **If parity test fails (Task 18, Task 28):** the YAML is wrong, not the test. The captured fixture is the contract. Adjust the YAML to match.

- **If you need to discover a thing the plan didn't pin** (e.g., the exact PTData JSON index path scheme in Task 15): read the relevant source code (libfdpio C plugin, MDSplus tree-path docs), pin it, and document the discovery in a code comment so future-you doesn't have to re-find it.

- **Don't push to remote until told.** Task 28 ends with tagged commits; the user reviews before pushing.
