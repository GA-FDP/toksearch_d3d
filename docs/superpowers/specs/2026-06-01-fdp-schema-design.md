# `fdp-schema` Package — Design

**Date:** 2026-06-01
**Status:** Approved, ready for plan
**Context:** Phase 1 of the platform architecture handoff at
`/fusion/projects/dt/sammuli/fdp_dev/repos/2026-05-22-platform-architecture-handoff.md`.

## Problem

The FDP stack today encodes tokamak-specific access metadata (Pelican base URL,
XRootD origin, PTData JSON index location, MDS tree search path) as a Python
dataclass `fdp.Device` constructed in `toksearch_d3d/toksearch_d3d/fdp.py:43-64`
and discovered through the `fdp.devices` entry-point group.

Three problems with this:

1. It forces `toksearch_d3d → fdp` as an import-time dep (toksearch_d3d
   imports `fdp.Device` to construct its contribution). Combined with the
   runtime edge `fdp → toksearch` (the `fdp chat`/`query` CLI shims execvpe
   into `python -m toksearch.llm.cli`), this creates a triangle that complicates
   release ordering.

2. The Device dataclass mixes data-locator metadata (Pelican URLs, index paths)
   with framework-runtime hints (`default_llm_preset`, `extra_env`). There is no
   schema; new fields are added by editing the dataclass.

3. There is no package-neutral artifact describing how to find data for a
   tokamak. Non-Python consumers (a future Julia agent, a web tool, a
   `toksearch_kstar`) cannot validate or consume the metadata without importing
   `fdp`.

## Goals

Phase 1 delivers a single bundled change across three packages:

- **A new `fdp-schema` package** containing pydantic models for `Tokamak`,
  `Locator` (tagged union: `MdsTreeLocator`, `PtDataIndexedLocator`,
  `SqlLocator`), `AuthHint`. Pure data — no GA-FDP deps. Exposes JSON Schema
  for non-Python consumers.

- **A D3D tokamak YAML** shipped as package data in `toksearch_d3d`, declared
  via the new `fdp_schema.catalogs` entry-point group. No Python factory; the
  contribution is data only.

- **`fdp` integration**: a new `fdp.catalog` API that discovers tokamak YAMLs,
  parses them, and exposes typed resolver methods (`MdsTreeResolver`,
  `PtDataResolver`, `SqlResolver`). `fdp run` and `fdp env` keep emitting the
  same env vars they do today — the catalog is the new source of truth, the
  env vars are a derived projection.

- **Clean break**: delete `fdp.Device`, the `fdp.devices` entry-point group,
  and `toksearch_d3d.fdp.D3D_DEVICE`. No deprecation shim.

After Phase 1 the dep graph is:

```
fdp_schema   (pydantic, pyyaml — no GA-FDP deps)
    ▲
    │
   fdp ──→ toksearch
            ▲
            │
       toksearch_d3d ──→ ptdata, imas_composer
            │
            └─ ships d3d.yaml + fdp_schema.catalogs entry point
              (package data only — no Python import of fdp_schema)
```

`toksearch_d3d` no longer depends on `fdp`. The triangle from the handoff
dissolves.

## Non-Goals

- **MCP servers.** Zero MCP work in Phase 1; that is Phase 2+.
- **Additional locator types.** `ImasLocator` (IMAS today goes through
  `MdsSignal` over Pelican; `MdsTreeLocator` covers it), `HttpLocator`,
  `SqliteLocator` (a natural future home for `CAKE_DB_PATH`). Defer.
- **`default_llm_preset` on `Tokamak`.** The current D3D Device's `"amsc"`
  value is dropped in this release. LLM presets belong to a future
  `toksearch.llm.presets` owner per Framing 3 of the handoff.
- **Phasing out env-var-based access.** Phase 1 retains full env-var
  compatibility (catalog → env vars at `fdp run` time). Swapping C-library
  consumers (mdsplus-xrdcl, libfdpio) to read catalog config directly is a
  separate later phase.
- **Promoting `extra_env` keys to first-class fields.** `D3DATA`,
  `SYS_D3_DELIM`, `CAKE_DB_PATH` stay in `extra_env`. Revisit when there is
  more than one tokamak to compare.
- **Site/user catalog overrides.** `/etc/fdp/tokamaks.d/*.yaml` and
  `~/.fdp/tokamaks.d/*.yaml` are deferred. Phase 1 only supports entry-point
  discovery.
- **Reloadable catalog.** Loaded once per process; restart to pick up changes.
- **Multi-driver `SqlLocator`.** The schema declares `mssql`, `postgres`,
  `sqlite` for forward-compat, but the v1 resolver implements only `mssql`.
- **Migrating `toksearch.sql.mssql.connect_d3drdb()` to use the catalog.**
  Would create a `toksearch → fdp` dep, completing a cycle with `fdp →
  toksearch`. The existing API keeps its hardcoded defaults in Phase 1; a
  follow-up resolves where `connect_d3drdb` should live. A sync test (see
  "Python API & Resolvers" section) catches drift between the two sources
  of truth in the meantime.
- **Multi-tokamak v1.** Only D3D ships a YAML.
- **Standalone `fdp-schema validate <path>` CLI.** `fdp catalog show <name>`
  is the only validation UX in v1.
- **`FDP_GUI_LOGO_PATH` → `TOKSEARCH_GUI_HEADER_LOGO` rename.** Unrelated
  toksearch internal cleanup; separate PR.

The `fdp → toksearch` run-dep honesty fix and the `toksearch_d3d → fdp` dep
removal — both from the handoff's "tighten seams" Framing 1 set — are
**folded into Phase 1** (Section 6), not deferred.

## Architecture

### Package boundaries

**New: `fdp-schema`** — new repo, conda package on `ga-fdp`.

- Deps: `pydantic >=2`, `pyyaml`. No GA-FDP deps, no network, no XRootD.
- Modules:
  - `fdp_schema/models.py` — pydantic models (Section "Schema Models").
  - `fdp_schema/loader.py` — `load_tokamak(source) -> Tokamak`.
  - `fdp_schema/__init__.py` — re-exports + `tokamak_json_schema()`.
- Released independently of `fdp` / `toksearch_d3d`.

**Changed: `fdp`** — `0.1.4 → 0.2.0` (breaking).

- New module `fdp/catalog.py` — discovery + `TokamakHandle` wrapper +
  `catalog` singleton.
- New package `fdp/resolvers/` — `MdsTreeResolver`, `PtDataResolver`,
  `SqlResolver`.
- Rewritten `fdp/environment.py` — drops `Device.to_env()` call sites; adds
  `_tokamak_env(handle)`.
- Rewritten `fdp/cli.py` — `fdp devices` removed; `fdp catalog list` /
  `fdp catalog show <name>` added. Other subcommands unchanged.
- Deleted: `fdp/devices.py`.
- New run-deps: `fdp-schema`, **and** `toksearch` (the handoff's seam #1
  honesty fix — `fdp chat`/`query` execvpe into `python -m toksearch.llm.cli`
  but the dep was never declared).

**Changed: `toksearch_d3d`** — `0.4.x → 0.5.0`.

- New file `toksearch_d3d/data/__init__.py` — 2 lines, declares a Traversable
  for the YAML.
- New file `toksearch_d3d/data/d3d.yaml` — the catalog content.
- Deleted: `toksearch_d3d/fdp.py` (the `D3D_DEVICE` module).
- `pyproject.toml`: remove `[project.entry-points."fdp.devices"]`; add
  `[project.entry-points."fdp_schema.catalogs"]`; drop `fdp` from
  `[project.dependencies]`; add `[tool.setuptools.package-data] "toksearch_d3d.data" = ["*.yaml"]`.
- `recipe/recipe.yaml` mirrors the dep changes.

## Schema Models

`fdp_schema/models.py` (pydantic v2; discriminated unions on `kind`):

```python
from typing import Literal, Union, Annotated
from pydantic import BaseModel, Field

class AuthHint(BaseModel):
    kind: Literal["bearer_token", "password_file", "none"]
    env: str | None = None    # bearer_token: env var holding the credential
    path: str | None = None   # password_file: path to file (~ expanded by consumer)

class MdsTreeLocator(BaseModel):
    kind: Literal["mds_tree"] = "mds_tree"
    name: str
    transport: Literal["pelican", "xrootd", "local"]
    search_path: list[str]    # ordered base-URL templates with MDS tokens (~t, ~f~e~d~c, ...)
    auth: AuthHint | None = None

class PtDataIndexedLocator(BaseModel):
    kind: Literal["ptdata_indexed"] = "ptdata_indexed"
    name: str
    transport: Literal["pelican", "xrootd", "local"]
    index_dir: str            # URL to JSON index directory
    auth: AuthHint | None = None

class SqlLocator(BaseModel):
    kind: Literal["sql"] = "sql"
    name: str
    driver: Literal["mssql", "postgres", "sqlite"]
    host: str
    port: int | None = None
    database: str
    tdsver: str | None = None    # mssql via FreeTDS; load-bearing
    auth: AuthHint | None = None

Locator = Annotated[
    Union[MdsTreeLocator, PtDataIndexedLocator, SqlLocator],
    Field(discriminator="kind"),
]

class Tokamak(BaseModel):
    schema_version: Literal[1] = 1
    name: str
    description: str = ""
    pelican_root: str | None = None    # for `fdp ls`
    origin_server: str | None = None   # for `fdp ls`
    locators: list[Locator] = []
    extra_env: dict[str, str] = {}
```

Notes:

- Each locator has a `name` so a tokamak can carry multiple of the same kind
  (primary/backup, prod/staging). D3D ships one per kind in v1.
- `schema_version: 1` is a contract version (bumped only on breaking changes).
  Additive fields don't bump it. v2 models, when they exist, will live
  alongside v1, and the loader will dispatch on the declared version.
- `extra_env` is `dict[str, str]` — strict shape, no nesting. Escape hatch for
  known env vars that don't yet justify first-class fields.

### D3D YAML

`toksearch_d3d/data/d3d.yaml`:

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

### JSON Schema export

```python
# fdp_schema/__init__.py
from .models import Tokamak

def tokamak_json_schema() -> dict:
    return Tokamak.model_json_schema()
```

Non-Python consumers can validate against this output.

## Catalog Discovery & Loading

### Contributor side

`toksearch_d3d/toksearch_d3d/data/__init__.py`:

```python
from importlib.resources import files
d3d_yaml = files(__package__) / "d3d.yaml"
```

`toksearch_d3d/pyproject.toml`:

```toml
[project.entry-points."fdp_schema.catalogs"]
d3d = "toksearch_d3d.data:d3d_yaml"

[tool.setuptools.package-data]
"toksearch_d3d.data" = ["*.yaml"]
```

The entry-point value is a stdlib `Traversable`. `toksearch_d3d` does not
import `fdp_schema` or `pydantic`. Zero new run-deps on the contributor side.

### Loader

`fdp_schema/loader.py`:

```python
from pathlib import Path
import yaml
from .models import Tokamak

def load_tokamak(source) -> Tokamak:
    """source may be Traversable, Path, or str path."""
    text = source.read_text() if hasattr(source, "read_text") else Path(source).read_text()
    return Tokamak.model_validate(yaml.safe_load(text))
```

### Discovery

`fdp/catalog.py`:

```python
from importlib.metadata import entry_points
from fdp_schema import Tokamak, load_tokamak

def _discover() -> dict[str, Tokamak]:
    out: dict[str, Tokamak] = {}
    for ep in entry_points(group="fdp_schema.catalogs"):
        source = ep.load()
        tk = load_tokamak(source)
        if tk.name in out:
            raise RuntimeError(
                f"Duplicate tokamak name {tk.name!r} contributed by {ep.value}"
            )
        out[tk.name] = tk
    return out
```

**Lazy loading**: `_discover()` runs on first access, not at import. A
malformed YAML therefore fails at first-use, not at `import fdp`. Validation
errors surface as pydantic's `ValidationError` with file path in the message
(the loader wraps the call to include path context).

**Name collisions** are a hard error in v1. When site/user overlays land
later, that's the moment to introduce a documented precedence rule.

### CLI

Rename `fdp devices` → `fdp catalog`:

- `fdp catalog list` — print tokamak names + descriptions.
- `fdp catalog show <name>` — dump the parsed Tokamak as YAML/JSON.

Since `fdp.Device` is deleted in the same release, the old command name has
no compatibility cost.

## Python API & Resolvers

`fdp.catalog[name]` returns a `TokamakHandle` that wraps a
`fdp_schema.Tokamak` and adds resolver methods.

```python
# fdp/catalog.py
from fdp_schema import MdsTreeLocator, PtDataIndexedLocator, SqlLocator
from fdp.resolvers import MdsTreeResolver, PtDataResolver, SqlResolver

class TokamakHandle:
    def __init__(self, model): self._model = model

    @property
    def name(self):        return self._model.name
    @property
    def description(self): return self._model.description
    @property
    def extra_env(self):   return self._model.extra_env
    @property
    def schema(self):      return self._model   # raw pydantic, escape hatch

    def locator(self, kind: str, name: str = "main"):
        matches = [l for l in self._model.locators
                   if l.kind == kind and l.name == name]
        if not matches:
            raise KeyError(f"No locator with kind={kind!r} name={name!r} on {self.name!r}")
        if len(matches) > 1:
            raise KeyError(f"Multiple locators with kind={kind!r} name={name!r}")
        return _wrap(matches[0])

def _wrap(loc):
    return {
        MdsTreeLocator:        MdsTreeResolver,
        PtDataIndexedLocator:  PtDataResolver,
        SqlLocator:            SqlResolver,
    }[type(loc)](loc)

class _Catalog:
    def __init__(self): self._cache = None
    def _load(self):
        if self._cache is None: self._cache = _discover()
        return self._cache
    def __getitem__(self, name):  return TokamakHandle(self._load()[name])
    def __contains__(self, name): return name in self._load()
    def __iter__(self):           return iter(self._load())
    def names(self):              return sorted(self._load())

catalog = _Catalog()
```

### Resolver methods are typed per backend

No fake common interface; the operations are genuinely different.

`fdp/resolvers/mds_tree.py`:

```python
class MdsTreeResolver:
    def __init__(self, model): self.model = model

    def urls_for(self, shot: int) -> list[str]:
        """Expand search-path templates. Pure, no I/O."""
        return [_expand_mds_template(t, shot) for t in self.model.search_path]

    def joined_path(self, shot: int, delim: str = ";") -> str:
        return delim.join(self.urls_for(shot))
```

`fdp/resolvers/ptdata.py`:

```python
class PtDataResolver:
    def __init__(self, model):
        self.model = model
        self._index_cache: dict[int, dict] = {}

    def resolve(self, shot: int, pointname: str, ext: str = ".PWR") -> str | None:
        """Read JSON index over Pelican, return shotfile URL. Network I/O."""
        self._check_auth()
        if shot not in self._index_cache:
            self._index_cache[shot] = self._fetch_index(shot)
        idx = self._index_cache[shot]
        return idx.get(pointname.upper(), {}).get("ext_location", {}).get(ext)

    def _fetch_index(self, shot: int) -> dict:
        # JSON layout follows libfdpio C-plugin convention.
        # Exact path scheme ({index_dir}/{shard}/{shot}.json) pinned in plan
        # by reading the C plugin's source.
        ...

    def _check_auth(self):
        if self.model.auth and self.model.auth.env and not os.environ.get(self.model.auth.env):
            raise RuntimeError(f"Auth required: env var {self.model.auth.env} not set")
```

`fdp/resolvers/sql.py` — uses **pymssql** (matching the existing
`toksearch.sql.mssql:connect_d3drdb`):

```python
class SqlResolver:
    def __init__(self, model): self.model = model

    def connect(self, username=None, password=None):
        if self.model.driver != "mssql":
            raise NotImplementedError(f"driver={self.model.driver!r} not in v1")
        if self.model.tdsver:
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
            path = Path(os.path.expanduser(auth.path))
            user, pw = [line.strip() for line in path.read_text().splitlines()[:2]]
            return user, pw
        raise RuntimeError(f"No credential source configured for {self.model.name!r}")
```

### Usage

```python
from fdp import catalog

tk = catalog["d3d"]
urls    = tk.locator("mds_tree").urls_for(shot=200000)
ptd_url = tk.locator("ptdata_indexed").resolve(shot=200000, pointname="ip")
with tk.locator("sql", name="d3drdb").connect() as conn:
    df = pd.read_sql("SELECT TOP 10 * FROM shots", conn)
```

**`toksearch.sql.mssql.connect_d3drdb()` is NOT migrated in Phase 1.** Doing
so would force `toksearch → fdp`, completing a cycle with the
`fdp → toksearch` dep added in Section 6 (and used at runtime by
`fdp chat`/`query` execvpe). For Phase 1, `connect_d3drdb()` keeps its
current hardcoded defaults (host, port, db) and pymssql import. The
catalog's `SqlLocator` is *available for new callers* but is not the source
of truth for the existing API path in this release.

This leaves two sources of truth for D3D's SQL connection info — the
hardcoded defaults in `toksearch/sql/mssql.py:32-38` and the d3d.yaml
`SqlLocator` block. To prevent them drifting, the plan adds a sync test in
`toksearch_d3d/tests/`:

```python
def test_sql_locator_matches_connect_d3drdb_defaults():
    from inspect import signature
    from toksearch.sql.mssql import connect_d3drdb
    sig = signature(connect_d3drdb)
    sql = catalog["d3d"].locator("sql", name="d3drdb").model
    assert sql.host     == sig.parameters["host"].default
    assert sql.port     == sig.parameters["port"].default
    assert sql.database == sig.parameters["db"].default
```

Resolving the duplication (likely by moving `connect_d3drdb` to a package
that can depend on both `toksearch` and `fdp` — perhaps a new module in
`fdp` itself, with a re-export shim in `toksearch.sql.mssql`) is deferred
to a follow-up that addresses the cycle separately. Acknowledged as tech
debt; tracked by the sync test as a regression guard.

### Design notes

- `TokamakHandle` and resolvers are constructed fresh per `catalog[name]`
  access — cheap. The `PtDataResolver` index cache lasts for the lifetime of
  the resolver instance. Long-running processes that want persistent caching
  should hold the resolver: `ptd = tk.locator("ptdata_indexed"); ptd.resolve(...); ptd.resolve(...)`.
- All network I/O lives in `fdp.resolvers`, not in `fdp_schema`. The schema
  package is pure data.
- The PtData JSON index reader is new Python code. The existing libfdpio C
  plugin keeps running for actual ptdata file access via env vars (next
  section); the Python resolver only covers catalog-driven lookups (e.g., an
  agent asking "where is this signal?").

## Env-var Derivation (`fdp run` / `fdp env`)

The generic vs tokamak-specific split is unchanged:

- `_generic_config()` in `fdp/environment.py:59-87` keeps its job: derive
  `XRD_*`, `PTDATA_LIBRARY`, `MDS_PATH`, `X509_CERT_FILE`, `TDSVER=7.0`
  (default), etc. from `$CONDA_PREFIX`. Untouched.
- Tokamak-specific env vars (`default_tree_path`, `PTDATA_JSON_INDEX_DIR`,
  `D3DATA`, `SYS_D3_DELIM`, `CAKE_DB_PATH`) get derived from the catalog.

```python
# fdp/environment.py
def _tokamak_env(handle: TokamakHandle) -> dict[str, str]:
    out: dict[str, str] = {}
    delim = handle.extra_env.get("SYS_D3_DELIM", ";")

    mds = [l for l in handle.schema.locators if l.kind == "mds_tree"]
    if mds:
        out["default_tree_path"] = delim.join(p for m in mds for p in m.search_path)

    ptd = [l for l in handle.schema.locators if l.kind == "ptdata_indexed"]
    if ptd:
        out["PTDATA_JSON_INDEX_DIR"] = ptd[-1].index_dir   # last-wins if multiple

    for s in handle.schema.locators:
        if s.kind == "sql" and s.driver == "mssql" and s.tdsver:
            out["TDSVER"] = s.tdsver

    out.update(handle.extra_env)
    return out

def apply_environment(tokamak_name: str | None = None) -> dict[str, str]:
    cfg = _generic_config()
    if tokamak_name:
        cfg.update(_tokamak_env(catalog[tokamak_name]))
    os.environ.update(cfg)
    return cfg
```

### Parity is load-bearing

The new code must produce byte-identical env vars to the current
`Device.to_env()` for D3D. The parity is pinned by a fixture test:

```python
# fdp/tests/test_env_parity.py
EXPECTED_D3D_ENV = {
    "default_tree_path": (
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c;"
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t;"
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t;"
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c"
    ),
    "PTDATA_JSON_INDEX_DIR": "pelican://osg-htc.org:443/fdp-d3d/archives/index/json/json_indexes_2026-01-13_12:22:11",
    "D3DATA": "yes",
    "SYS_D3_DELIM": ";",
    "CAKE_DB_PATH": "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db",
}

def test_d3d_env_parity():
    assert _tokamak_env(catalog["d3d"]) == EXPECTED_D3D_ENV
```

This fixture is captured from a dump of the current `D3D_DEVICE.to_env()`
before the deletion (the plan step that produces the fixture is its own
explicit step). The test then lives forever — if anyone edits `d3d.yaml` in
a way that changes the emitted env vars, the test catches it.

### CLI behavior unchanged

- `fdp env` — print exports (same output as today for D3D).
- `fdp env -d <name>` — same flag, now resolves through catalog.
- `fdp run <cmd>` — apply env, then `subprocess.run(passthrough, env=os.environ)`.

## Removal of `fdp.Device` / `fdp.devices`

### In `fdp/`

- Delete `fdp/fdp/devices.py` entirely.
- Update `fdp/fdp/cli.py`: remove `fdp devices` subcommand; add
  `fdp catalog list` and `fdp catalog show <name>`.
- Update `fdp/fdp/environment.py`: replace `Device.to_env()` call sites with
  `_tokamak_env(catalog[name])`.
- Update `fdp/fdp/__init__.py`: drop any `Device` re-export; add `catalog`.
- Update `fdp/pyproject.toml`: add `fdp-schema` and `toksearch` to run-deps.
- Update `fdp/recipe/recipe.yaml`: mirror the run-deps additions.
- Update `fdp/tests/`: delete `test_devices.py` if it exists; the new
  parity test is the replacement contract.

### In `toksearch_d3d/`

- Delete `toksearch_d3d/toksearch_d3d/fdp.py` (the `D3D_DEVICE` module).
- Create `toksearch_d3d/toksearch_d3d/data/__init__.py` (2 lines).
- Create `toksearch_d3d/toksearch_d3d/data/d3d.yaml`.
- Update `pyproject.toml`:
  - Remove `[project.entry-points."fdp.devices"]` block.
  - Add `[project.entry-points."fdp_schema.catalogs"] d3d = "toksearch_d3d.data:d3d_yaml"`.
  - Remove `fdp` from `[project.dependencies]`.
  - Add `[tool.setuptools.package-data] "toksearch_d3d.data" = ["*.yaml"]`.
- Update `recipe/recipe.yaml`: drop `fdp` from run requirements.
- Grep for internal imports of `toksearch_d3d.fdp` and update or delete each.
  Plan stage owns enumerating them.

### CLAUDE.md updates

- `repos/CLAUDE.md` (top-level) — mention the catalog API where Device is
  referenced today.
- `toksearch_d3d/CLAUDE.md` — same; also currently references
  `toksearch_d3d.fdp.cli`, which is already stale (the fdp CLI lives in the
  separate `fdp` package post-decoupling). Refresh while in the area.

### Versioning

- `fdp-schema` `0.1.0` — first release.
- `fdp` `0.1.4 → 0.2.0` — breaking API change.
- `toksearch_d3d` `0.4.x → 0.5.0` — loses `D3D_DEVICE` public attribute.

Out-of-tree blast radius: anyone who does `from fdp.devices import Device`
or `from fdp import Device` breaks at install time of the new fdp release.
This is the clean-break trade-off chosen during brainstorming.

## Testing Strategy

### `fdp-schema` — pure, no network, no GA-FDP deps

- Validation: each locator type accepts/rejects the right shapes.
- Discriminated-union dispatch: a YAML with `kind: mds_tree` parses to
  `MdsTreeLocator`; bad `kind` value raises.
- Round-trip: `Tokamak.model_dump()` → YAML → `load_tokamak()` is identity.
- JSON Schema export: `tokamak_json_schema()` returns a dict whose
  `$defs` contains all three locator types.
- D3D fixture: `tests/fixtures/d3d.yaml` (a copy of the production D3D YAML)
  loads cleanly. Catches schema regressions before they hit `toksearch_d3d`.

### `fdp` — unit always, integration gated by env

**Unit (no network):**

- Catalog discovery with a mock entry-point group (pytest fixture
  monkeypatches `importlib.metadata.entry_points`).
- `TokamakHandle.locator(kind, name)` — found, not-found, ambiguous.
- **`test_d3d_env_parity`** (the load-bearing one) — pinned fixture.
- `MdsTreeResolver.urls_for(shot)` — template expansion, deterministic.
- `SqlResolver.connect()` — patched `pymssql.connect`, verify the TDSVER
  side-effect and the credential read.
- CLI: `fdp catalog list` / `fdp catalog show d3d` (snapshot test).

**Integration (`pytest -m integration`):**

- `PtDataResolver.resolve(shot, pointname)` against the real Pelican-hosted
  JSON index. Picks a stable shot/pointname (e.g., 200000 / `ip`). Asserts
  the returned URL is well-formed and dereferenceable. Gated by `BEARER_TOKEN`.
- `SqlResolver.connect()` against d3drdb — gated by the presence of
  `~/D3DRDB.sybase_login`.

### `toksearch_d3d`

- `tests/test_catalog.py`: `load_tokamak(d3d_yaml)` succeeds, returns a
  Tokamak with `name == "d3d"`, expected locator count, expected
  `extra_env` keys.
- Entry-point wiring: `entry_points(group="fdp_schema.catalogs")` includes
  `"d3d"` with a readable Traversable.

### End-to-end

`fdp_installer/tests/testit.py` — unchanged. Runs `fdp run python -c ...`,
`fdp ls`, a ptdata fetch. If env-var parity holds, this passes without
modification. **If it fails, parity broke.** It's the canary.

### CI matrix

- `fdp-schema` — Python 3.11, pure unit. Trivial CI.
- `fdp` — Python 3.11 + the conda env (XRootD libs, `pymssql`). Unit always;
  integration gated by a `BEARER_TOKEN` repository secret in GitHub Actions
  for nightly runs; otherwise skipped.
- `toksearch_d3d` — existing CI runs the new test alongside existing
  signal tests.

### Tests deliberately not added

- libfdpio C plugin behavior (env-var compatibility is the contract; C-side
  unchanged).
- mdsplus-xrdcl resolution behavior (same reason).
- `fdp.devices` / `fdp.Device` (deleted in this release).

## Open Items for the Plan

These were called out during brainstorming as decisions the plan stage needs
to pin concretely (not design questions — implementation details):

1. **Exact PTData JSON index path scheme** — the `_fetch_index(shot)` method
   needs the layout (likely `{index_dir}/{shard}/{shot}.json`). Reading
   libfdpio's C plugin source pins it.
2. **`mds_tree` template expansion** (`~t`, `~f~e~d~c`, `~j~i`, etc.) — the
   token semantics are MDSplus convention. The plan implements
   `_expand_mds_template` and tests against shots that exercise each token.
3. **Exact entry-point declaration form** — the `Traversable`-via-init-module
   pattern is what we're going with; verify it loads through
   `entry_points().load()` cleanly across Python 3.11 setuptools.
4. **Internal toksearch_d3d imports of `toksearch_d3d.fdp`** — enumerate and
   update or delete each during the plan.
5. **D3D environment fixture capture** — the parity test's expected dict is
   captured by running the current D3D_DEVICE.to_env() one last time before
   deletion. The plan has an explicit step for this so the fixture is real,
   not transcribed.
6. **Release order** — `fdp-schema` releases first; then `fdp` and
   `toksearch_d3d` together (they break each other otherwise). `fdp_installer`
   gets a `pixi.toml` bump after.

## Suggested next step

Invoke the `superpowers:writing-plans` skill to break this design into an
ordered implementation plan with review checkpoints, owned task by task.
