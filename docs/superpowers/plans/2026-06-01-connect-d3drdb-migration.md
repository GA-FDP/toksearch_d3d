# `connect_d3drdb` Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move D3D-specific `connect_d3drdb` out of `toksearch.sql.mssql` and into `toksearch_d3d.sql`, replacing it in `toksearch` with a generic `connect_tokamak_sql(tokamak, name, **overrides)` that reads the catalog. Keep a lazily-delegating deprecation shim at `toksearch.sql.mssql.connect_d3drdb` so the ~25 in-tree callers keep working. Eliminate the Phase 1 sync test — the catalog is the single source of truth.

**Architecture:** `toksearch.sql.mssql` gains `connect_tokamak_sql` plus a `_discover_catalogs()` helper that reads `fdp_schema.catalogs` entry points (cached with `functools.cache`). The legacy `connect_d3drdb` symbol stays but lazily imports `toksearch_d3d.sql.connect_d3drdb` and emits `DeprecationWarning`. `toksearch_d3d.sql` is a new flat module — `connect_d3drdb` becomes a one-liner over the generic API pinning `tokamak="d3d"`, `name="d3drdb"`.

**Tech Stack:** Python 3.11, `pymssql`, `pydantic >=2`, `pyyaml`, `fdp_schema`, `pytest`, `unittest.mock`, versioneer, rattler-build, pixi.

**Reference spec:** `toksearch_d3d/docs/superpowers/specs/2026-06-01-connect-d3drdb-migration-design.md`

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `toksearch/toksearch/sql/mssql.py` | **Rewrite** | New `connect_tokamak_sql`, `_discover_catalogs`, `_resolve_credential`. Existing `connect_d3drdb` becomes a deprecation shim. Delete `USERNAME`, `DEFAULT_PASSWORD_FILE`, `_read_sybase_login_file`. |
| `toksearch/tests/test_sql.py` | **Augment** | Add `TestConnectTokamakSql` and `TestResolveCredential` classes. Existing dead `if False:` block stays. |
| `toksearch/tests/test_sql_deprecation.py` | **Create** | `TestConnectD3DRDBShim` — DeprecationWarning emission, kwarg forwarding, ImportError on missing `toksearch_d3d`. |
| `toksearch/recipe/recipe.yaml` | **Modify** | Add `fdp-schema >=0.1.1` to `run:` deps. |
| `toksearch/pixi.toml` | **Modify** | Add `fdp-schema >=0.1.1` to `[dependencies]`. |
| `toksearch_d3d/toksearch_d3d/sql.py` | **Create** | Flat module exposing `connect_d3drdb` as a one-liner. |
| `toksearch_d3d/tests/test_sql.py` | **Create** | Smoke tests delegating-to-generic + skip-gated real-DB integration. |
| `toksearch_d3d/tests/test_sql_sync.py` | **Delete** | Phase 1 stopgap — obsolete. |

---

## Implementation phases

- **Phase A (Tasks 1–2):** Pre-flight, dev-env setup, branches.
- **Phase B (Tasks 3–6):** Build `connect_tokamak_sql` and the deprecation shim in `toksearch`.
- **Phase C (Tasks 7–8):** Recipe + dev-env dep declaration.
- **Phase D (Tasks 9–11):** `toksearch_d3d.sql` module, tests, sync-test deletion.
- **Phase E (Tasks 12–13):** End-to-end demo, release tags, push, monitor CI.

Frequent commits — one per task at minimum.

---

# Phase A: Pre-flight

## Task 1: Create feature branches and verify clean state

**Files:** none (git operations only)

- [ ] **Step 1: Inspect each repo's working tree and current branch.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
git branch --show-current
git status -s
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git branch --show-current
git status -s
```

Expected: both on `main`, clean working trees (untracked scratch files in toksearch_d3d are fine).

If `toksearch_d3d` has `pixi.lock` or `pixi.toml` modified from previous work, decide whether to commit those changes separately or stash them. They will follow the feature branch otherwise.

- [ ] **Step 2: Create feature branches in both repos.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
git checkout -b connect-d3drdb-migration

cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git checkout -b connect-d3drdb-migration
```

Verify with `git branch --show-current` in each.

- [ ] **Step 3: Confirm current tags (used for version bump decisions in Task 13).**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch && git tag --list "release-*" | tail -3
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && git tag --list "release-*" | tail -3
```

Record the latest tag in each. The plan assumes `toksearch 2.7.4 → 2.8.0` and `toksearch_d3d 0.9.2 → 0.9.3`. If the actual current tags differ, adjust target versions in Task 13.

No commit for this task.

---

## Task 2: Add `fdp_schema` as an editable dev-dep in `toksearch/pixi.toml`

**Files:**
- Modify: `toksearch/pixi.toml`

This lets `toksearch`'s dev env iterate against the local `fdp_schema` checkout during this work. The production conda dep (Task 7/8) lands separately.

- [ ] **Step 1: Read `toksearch/pixi.toml` and locate `[pypi-dependencies]`.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
grep -n "pypi-dependencies\|^\[" pixi.toml | head -10
```

- [ ] **Step 2: Add the editable path-dep.**

In `toksearch/pixi.toml`, add to `[pypi-dependencies]` (create the section if absent):

```toml
[pypi-dependencies]
toksearch = { path = ".", editable = true }
# For connect-d3drdb-migration: read the catalog via fdp_schema.
# Switches to a conda dep before release (see Task 7).
fdp_schema = { path = "../fdp_schema", editable = true }
```

If `toksearch = { path = ".", editable = true }` already exists, just append the `fdp_schema` line.

- [ ] **Step 3: Reinstall the pixi env.**

```bash
pixi install
```

Expected: successful install. The lockfile updates.

- [ ] **Step 4: Verify the import works.**

```bash
pixi run python -c "from fdp_schema import load_tokamak, Tokamak; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 5: Commit.**

```bash
git add pixi.toml pixi.lock
git commit -m "Add fdp_schema editable dev-dep for connect_tokamak_sql work"
```

---

# Phase B: Generic API in `toksearch`

## Task 3: Implement `_resolve_credential` helper with TDD

**Files:**
- Modify: `toksearch/tests/test_sql.py`
- Modify: `toksearch/toksearch/sql/mssql.py`

We start with the credential resolver because it's pure and isolatable. `connect_tokamak_sql` (Task 5) consumes it.

- [ ] **Step 1: Append failing tests to `toksearch/tests/test_sql.py`.**

After the existing imports, add:

```python
from unittest import mock


class TestResolveCredential(unittest.TestCase):
    """_resolve_credential: pure function reading a two-line password file.

    Phase 1 connect_d3drdb resolved credentials by reading a file with
    username on line 1 and password on line 2. This carries the behavior
    forward into the catalog-aware path.
    """

    def _locator(self, *, auth_kind="password_file", auth_path="~/.test.login"):
        from fdp_schema import SqlLocator, AuthHint
        return SqlLocator(
            name="testdb",
            driver="mssql",
            host="h",
            port=8001,
            database="testdb",
            auth=AuthHint(kind=auth_kind, path=auth_path) if auth_kind else None,
        )

    def test_reads_password_file_from_locator_auth_path(self):
        from toksearch.sql.mssql import _resolve_credential
        loc = self._locator(auth_path="/tmp/test.login")
        with mock.patch(
            "pathlib.Path.read_text",
            return_value="theuser\nthepass\n",
        ):
            user, password = _resolve_credential(None, loc, None)
        self.assertEqual((user, password), ("theuser", "thepass"))

    def test_password_file_override_wins_over_locator_auth_path(self):
        from toksearch.sql.mssql import _resolve_credential
        loc = self._locator(auth_path="/never/read.login")
        with mock.patch(
            "pathlib.Path.read_text",
            return_value="overuser\noverpass\n",
        ) as read_text:
            user, password = _resolve_credential(None, loc, "/tmp/o.login")
        # Verify the override path was opened, not the locator's.
        called_path = str(read_text.call_args.args[0]) if read_text.call_args.args else ""
        self.assertEqual((user, password), ("overuser", "overpass"))

    def test_explicit_username_wins_over_file_user(self):
        from toksearch.sql.mssql import _resolve_credential
        loc = self._locator()
        with mock.patch(
            "pathlib.Path.read_text",
            return_value="fromfile\nfilepass\n",
        ):
            user, password = _resolve_credential("kwarg_user", loc, None)
        self.assertEqual(user, "kwarg_user")
        self.assertEqual(password, "filepass")

    def test_tolerates_blank_lines_in_password_file(self):
        from toksearch.sql.mssql import _resolve_credential
        loc = self._locator()
        with mock.patch(
            "pathlib.Path.read_text",
            return_value="\nuser1\n\npass2\n",
        ):
            user, password = _resolve_credential(None, loc, None)
        self.assertEqual((user, password), ("user1", "pass2"))

    def test_expands_user_tilde_in_path(self):
        from toksearch.sql.mssql import _resolve_credential
        import os
        loc = self._locator(auth_path="~/.d3d.login")
        captured = {}
        def fake_read_text(self):
            captured["path"] = str(self)
            return "u\np\n"
        with mock.patch("pathlib.Path.read_text", new=fake_read_text):
            _resolve_credential(None, loc, None)
        self.assertNotIn("~", captured["path"])
        self.assertIn(os.path.expanduser("~"), captured["path"])

    def test_raises_runtimeerror_when_no_credential_source(self):
        from toksearch.sql.mssql import _resolve_credential
        loc = self._locator(auth_kind=None)
        with self.assertRaisesRegex(RuntimeError, "credential source"):
            _resolve_credential(None, loc, None)
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
pixi run python -m pytest tests/test_sql.py::TestResolveCredential -v
```

Expected: `ImportError: cannot import name '_resolve_credential' from 'toksearch.sql.mssql'`.

- [ ] **Step 3: Add `_resolve_credential` to `toksearch/toksearch/sql/mssql.py`.**

First, read the existing file:

```bash
cat toksearch/sql/mssql.py
```

You should see ~70 lines: license header, imports (`os`, `getpass`, `pathlib.Path`, `pymssql`), module-level constants (`USERNAME`, `DEFAULT_PASSWORD_FILE`), `_read_sybase_login_file`, and `connect_d3drdb`. Task 6 deletes the obsolete bits; Task 5 replaces `connect_d3drdb`. **This task only adds new code** — it does not touch the existing `connect_d3drdb` yet.

Append to `toksearch/toksearch/sql/mssql.py` (after the existing function, before EOF):

```python


def _resolve_credential(
    username: str | None, loc, password_file_override: str | None,
) -> tuple[str, str]:
    """Resolve (username, password) for an mssql SqlLocator.

    Reads a two-line password file (username on line 1, password on
    line 2) from `password_file_override` if given, else from
    `loc.auth.path`. Returns `(file_user, file_pass)` unless `username`
    is explicitly provided, in which case the explicit value wins.

    Raises:
      RuntimeError: no credential source resolvable.
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
    text = Path(os.path.expanduser(pf)).read_text()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    file_user, file_pass = lines[0], lines[1]
    return (username if username is not None else file_user), file_pass
```

- [ ] **Step 4: Run the tests to verify they pass.**

```bash
pixi run python -m pytest tests/test_sql.py::TestResolveCredential -v
```

Expected: all 6 PASS.

- [ ] **Step 5: Commit.**

```bash
git add toksearch/sql/mssql.py tests/test_sql.py
git commit -m "Add _resolve_credential helper in toksearch.sql.mssql"
```

---

## Task 4: Implement `_discover_catalogs` helper with TDD

**Files:**
- Modify: `toksearch/tests/test_sql.py`
- Modify: `toksearch/toksearch/sql/mssql.py`

- [ ] **Step 1: Append failing tests to `toksearch/tests/test_sql.py`.**

```python
class TestDiscoverCatalogs(unittest.TestCase):
    """_discover_catalogs reads the fdp_schema.catalogs entry-point group
    and parses each contributed YAML. Cached for process lifetime."""

    def setUp(self):
        from toksearch.sql.mssql import _discover_catalogs
        _discover_catalogs.cache_clear()

    def _ep(self, name: str, yaml: str):
        ep = mock.MagicMock()
        ep.name = name
        ep.value = f"mock:{name}"
        src = mock.MagicMock()
        src.read_text.return_value = yaml
        ep.load.return_value = src
        return ep

    def test_returns_dict_keyed_by_tokamak_name(self):
        from toksearch.sql.mssql import _discover_catalogs
        eps = [self._ep("d3d", "schema_version: 1\nname: d3d\n")]
        with mock.patch("toksearch.sql.mssql.entry_points", return_value=eps):
            result = _discover_catalogs()
        self.assertEqual(set(result.keys()), {"d3d"})
        self.assertEqual(result["d3d"].name, "d3d")

    def test_loads_full_locator_data(self):
        from toksearch.sql.mssql import _discover_catalogs
        eps = [self._ep("d3d", """
schema_version: 1
name: d3d
locators:
  - kind: sql
    name: d3drdb
    driver: mssql
    host: d3drdb.gat.com
    port: 8001
    database: d3drdb
""")]
        with mock.patch("toksearch.sql.mssql.entry_points", return_value=eps):
            result = _discover_catalogs()
        loc = result["d3d"].locators[0]
        self.assertEqual(loc.kind, "sql")
        self.assertEqual(loc.host, "d3drdb.gat.com")

    def test_duplicate_tokamak_name_raises(self):
        from toksearch.sql.mssql import _discover_catalogs
        eps = [
            self._ep("a", "schema_version: 1\nname: x\n"),
            self._ep("b", "schema_version: 1\nname: x\n"),
        ]
        with mock.patch("toksearch.sql.mssql.entry_points", return_value=eps):
            with self.assertRaisesRegex(RuntimeError, "Duplicate tokamak name"):
                _discover_catalogs()

    def test_result_is_cached(self):
        from toksearch.sql.mssql import _discover_catalogs
        eps = [self._ep("d3d", "schema_version: 1\nname: d3d\n")]
        with mock.patch(
            "toksearch.sql.mssql.entry_points", return_value=eps
        ) as ep_mock:
            _discover_catalogs()
            _discover_catalogs()
            _discover_catalogs()
        self.assertEqual(ep_mock.call_count, 1)
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
pixi run python -m pytest tests/test_sql.py::TestDiscoverCatalogs -v
```

Expected: `ImportError: cannot import name '_discover_catalogs' from 'toksearch.sql.mssql'`.

- [ ] **Step 3: Add imports and `_discover_catalogs` to `toksearch/toksearch/sql/mssql.py`.**

At the top of the file, ensure these imports exist (add any that are missing — keep existing imports in place):

```python
import functools
import os
import pathlib
from importlib.metadata import entry_points
from pathlib import Path

import pymssql
from fdp_schema import load_tokamak, Tokamak
```

Append the function:

```python


@functools.cache
def _discover_catalogs() -> dict[str, Tokamak]:
    """Read and validate every YAML contributed via the
    `fdp_schema.catalogs` entry-point group. Cached for process lifetime;
    tests that patch `entry_points` must call `cache_clear()` in setUp."""
    out: dict[str, Tokamak] = {}
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

- [ ] **Step 4: Run the tests to verify they pass.**

```bash
pixi run python -m pytest tests/test_sql.py::TestDiscoverCatalogs tests/test_sql.py::TestResolveCredential -v
```

Expected: all 10 PASS (6 from Task 3 + 4 new).

- [ ] **Step 5: Commit.**

```bash
git add toksearch/sql/mssql.py tests/test_sql.py
git commit -m "Add _discover_catalogs helper reading fdp_schema.catalogs entry points"
```

---

## Task 5: Implement `connect_tokamak_sql` with TDD

**Files:**
- Modify: `toksearch/tests/test_sql.py`
- Modify: `toksearch/toksearch/sql/mssql.py`

The main event. Reads from catalog, applies overrides, resolves credentials, calls pymssql.

- [ ] **Step 1: Append failing tests to `toksearch/tests/test_sql.py`.**

```python
class TestConnectTokamakSql(unittest.TestCase):
    """connect_tokamak_sql: catalog-aware mssql connect helper."""

    YAML = """
schema_version: 1
name: testtok
locators:
  - kind: sql
    name: testdb
    driver: mssql
    host: testdb.example.com
    port: 8001
    database: testdb
    tdsver: "7.0"
    auth: { kind: password_file, path: ~/.testdb.login }
"""

    def setUp(self):
        from toksearch.sql.mssql import _discover_catalogs
        _discover_catalogs.cache_clear()

    def _patch_entry_points(self):
        ep = mock.MagicMock()
        ep.name = "testtok"
        ep.value = "mock:testtok"
        src = mock.MagicMock()
        src.read_text.return_value = self.YAML
        ep.load.return_value = src
        return mock.patch(
            "toksearch.sql.mssql.entry_points", return_value=[ep]
        )

    def test_calls_pymssql_with_catalog_values(self):
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with mock.patch(
                "toksearch.sql.mssql._resolve_credential",
                return_value=("u", "p"),
            ):
                with mock.patch("pymssql.connect") as connect:
                    connect_tokamak_sql("testtok", "testdb")
        connect.assert_called_once_with(
            "testdb.example.com", "u", "p", "testdb", port="8001"
        )

    def test_kwarg_overrides_catalog_host(self):
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with mock.patch(
                "toksearch.sql.mssql._resolve_credential",
                return_value=("u", "p"),
            ):
                with mock.patch("pymssql.connect") as connect:
                    connect_tokamak_sql("testtok", "testdb", host="other.example.com")
        connect.assert_called_once_with(
            "other.example.com", "u", "p", "testdb", port="8001"
        )

    def test_kwarg_db_overrides_catalog_database(self):
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with mock.patch(
                "toksearch.sql.mssql._resolve_credential",
                return_value=("u", "p"),
            ):
                with mock.patch("pymssql.connect") as connect:
                    connect_tokamak_sql("testtok", "testdb", db="code_rundb")
        # db kwarg → 4th positional arg (database)
        connect.assert_called_once_with(
            "testdb.example.com", "u", "p", "code_rundb", port="8001"
        )

    def test_kwarg_port_overrides_catalog_port(self):
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with mock.patch(
                "toksearch.sql.mssql._resolve_credential",
                return_value=("u", "p"),
            ):
                with mock.patch("pymssql.connect") as connect:
                    connect_tokamak_sql("testtok", "testdb", port=9999)
        connect.assert_called_once_with(
            "testdb.example.com", "u", "p", "testdb", port="9999"
        )

    def test_tdsver_setdefault_does_not_override(self):
        import os
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with mock.patch.dict(os.environ, {"TDSVER": "8.0"}, clear=True):
                with mock.patch(
                    "toksearch.sql.mssql._resolve_credential",
                    return_value=("u", "p"),
                ):
                    with mock.patch("pymssql.connect"):
                        connect_tokamak_sql("testtok", "testdb")
                # Pre-existing TDSVER kept.
                self.assertEqual(os.environ["TDSVER"], "8.0")

    def test_tdsver_set_when_not_in_env(self):
        import os
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch(
                    "toksearch.sql.mssql._resolve_credential",
                    return_value=("u", "p"),
                ):
                    with mock.patch("pymssql.connect"):
                        connect_tokamak_sql("testtok", "testdb")
                self.assertEqual(os.environ.get("TDSVER"), "7.0")

    def test_explicit_password_skips_credential_file_read(self):
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with mock.patch(
                "toksearch.sql.mssql._resolve_credential"
            ) as resolve:
                with mock.patch("pymssql.connect") as connect:
                    connect_tokamak_sql(
                        "testtok", "testdb",
                        username="bob", password="explicit",
                    )
        resolve.assert_not_called()
        connect.assert_called_once_with(
            "testdb.example.com", "bob", "explicit", "testdb", port="8001"
        )

    def test_explicit_password_without_username_defaults_to_os_user(self):
        """Phase 1 connect_d3drdb signature was `username=USERNAME, password=None`.
        When a caller now passes only `password=`, preserve the OS-current-user
        default so pymssql doesn't receive None."""
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with mock.patch("getpass.getuser", return_value="osuser"):
                with mock.patch("pymssql.connect") as connect:
                    connect_tokamak_sql("testtok", "testdb", password="x")
        connect.assert_called_once_with(
            "testdb.example.com", "osuser", "x", "testdb", port="8001"
        )

    def test_unknown_tokamak_raises_keyerror_with_available_list(self):
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with self.assertRaises(KeyError) as ctx:
                connect_tokamak_sql("nonexistent", "testdb")
        self.assertIn("Available", str(ctx.exception))
        self.assertIn("testtok", str(ctx.exception))

    def test_unknown_locator_name_raises_keyerror_with_available_list(self):
        from toksearch.sql.mssql import connect_tokamak_sql
        with self._patch_entry_points():
            with self.assertRaises(KeyError) as ctx:
                connect_tokamak_sql("testtok", "nonexistent")
        self.assertIn("Available", str(ctx.exception))
        self.assertIn("testdb", str(ctx.exception))

    def test_unsupported_driver_raises_notimplementederror(self):
        yaml = """
schema_version: 1
name: testtok
locators:
  - kind: sql
    name: pgdb
    driver: postgres
    host: pg.example.com
    database: pgdb
"""
        from toksearch.sql.mssql import connect_tokamak_sql
        ep = mock.MagicMock()
        ep.name = "testtok"
        ep.value = "mock:testtok"
        src = mock.MagicMock()
        src.read_text.return_value = yaml
        ep.load.return_value = src
        with mock.patch(
            "toksearch.sql.mssql.entry_points", return_value=[ep]
        ):
            with self.assertRaisesRegex(NotImplementedError, "postgres"):
                connect_tokamak_sql("testtok", "pgdb")
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
pixi run python -m pytest tests/test_sql.py::TestConnectTokamakSql -v
```

Expected: `ImportError: cannot import name 'connect_tokamak_sql' from 'toksearch.sql.mssql'`.

- [ ] **Step 3: Add `connect_tokamak_sql` to `toksearch/toksearch/sql/mssql.py`.**

Add `import getpass` to the existing imports if not already present. Then append:

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

    Args:
      tokamak: tokamak name registered via fdp_schema.catalogs (e.g. "d3d").
      name: which SqlLocator within that tokamak. D3D ships "d3drdb".
      host, port, db: catalog overrides. `db` maps to SqlLocator.database.
      username, password, password_file: credential overrides.

    Credential resolution:
      1. Explicit `password` kwarg wins.
      2. Otherwise `password_file` (kwarg if given, else locator.auth.path).
      3. If neither resolves, raise RuntimeError.

    Driver scope: only driver=="mssql" is supported in v1.

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

    if loc.tdsver:
        os.environ.setdefault("TDSVER", loc.tdsver)

    eff_host = host if host is not None else loc.host
    eff_port = port if port is not None else loc.port
    eff_db   = db   if db   is not None else loc.database

    if password is None:
        username, password = _resolve_credential(username, loc, password_file)
    elif username is None:
        # Explicit password without username: preserve Phase 1's OS
        # current-user default so pymssql doesn't receive None.
        username = getpass.getuser()

    return pymssql.connect(
        eff_host, username, password, eff_db,
        port=str(eff_port) if eff_port else None,
    )
```

- [ ] **Step 4: Run the tests to verify they pass.**

```bash
pixi run python -m pytest tests/test_sql.py::TestConnectTokamakSql -v
```

Expected: all 11 PASS.

- [ ] **Step 5: Run all sql tests to confirm no regressions in earlier helpers.**

```bash
pixi run python -m pytest tests/test_sql.py -v
```

Expected: all 21 PASS (10 from Tasks 3+4, 11 new).

- [ ] **Step 6: Commit.**

```bash
git add toksearch/sql/mssql.py tests/test_sql.py
git commit -m "Add connect_tokamak_sql: catalog-aware mssql connect helper"
```

---

## Task 6: Replace `connect_d3drdb` with the deprecation shim

**Files:**
- Create: `toksearch/tests/test_sql_deprecation.py`
- Modify: `toksearch/toksearch/sql/mssql.py`

- [ ] **Step 1: Create `toksearch/tests/test_sql_deprecation.py` with failing tests.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for the deprecation shim at toksearch.sql.mssql.connect_d3drdb.

The function is preserved for back-compat after the migration to
toksearch_d3d.sql.connect_d3drdb. Calling it must:
  - emit a DeprecationWarning pointing at the new path
  - lazily delegate to toksearch_d3d.sql.connect_d3drdb
  - forward all kwargs unchanged
  - raise a helpful ImportError if toksearch_d3d isn't installed
"""

import sys
import unittest
import warnings
from unittest import mock


class TestConnectD3DRDBShim(unittest.TestCase):
    def test_emits_deprecation_warning(self):
        from toksearch.sql.mssql import connect_d3drdb
        with mock.patch.dict(
            sys.modules,
            {"toksearch_d3d.sql": mock.MagicMock(
                connect_d3drdb=mock.MagicMock(return_value=mock.sentinel.conn)
            )},
        ):
            with self.assertWarns(DeprecationWarning) as ctx:
                result = connect_d3drdb()
        self.assertIs(result, mock.sentinel.conn)
        self.assertIn(
            "toksearch_d3d.sql.connect_d3drdb", str(ctx.warning),
        )

    def test_kwargs_forwarded_to_impl(self):
        from toksearch.sql.mssql import connect_d3drdb
        impl = mock.MagicMock(return_value=mock.sentinel.conn)
        with mock.patch.dict(
            sys.modules,
            {"toksearch_d3d.sql": mock.MagicMock(connect_d3drdb=impl)},
        ):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                connect_d3drdb(db="code_rundb", host="h", port=9999)
        impl.assert_called_once_with(db="code_rundb", host="h", port=9999)

    def test_helpful_error_if_toksearch_d3d_missing(self):
        from toksearch.sql.mssql import connect_d3drdb
        # Force the import inside the shim to fail.
        # Insert a None entry so `import toksearch_d3d.sql` hits ImportError.
        with mock.patch.dict(sys.modules, {"toksearch_d3d.sql": None}):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                with self.assertRaisesRegex(
                    ImportError, "toksearch_d3d.*conda install"
                ):
                    connect_d3drdb()
```

- [ ] **Step 2: Run the tests to verify they fail.**

```bash
pixi run python -m pytest tests/test_sql_deprecation.py -v
```

Expected: the tests fail. The exact failure mode depends on the
developer machine state because the current `connect_d3drdb` (pre-shim)
has real side effects:

- `test_emits_deprecation_warning` fails with `AssertionError: DeprecationWarning not raised` if the password file exists and pymssql throws a connection error; or it fails with `FileNotFoundError` if no password file exists. Either failure is acceptable proof the test is exercising the un-shimmed code.
- `test_kwargs_forwarded_to_impl` and `test_helpful_error_if_toksearch_d3d_missing` fail similarly (the current function doesn't call `toksearch_d3d.sql.connect_d3drdb` at all, so kwargs aren't forwarded and the missing-module ImportError never triggers).

Don't try to make these tests pass against the old implementation. Move
to Step 3 immediately; the shim is the real implementation under test.

- [ ] **Step 3: Replace the existing `connect_d3drdb` in `toksearch/toksearch/sql/mssql.py` with the shim.**

The current `connect_d3drdb` function body looks like (from the source file):

```python
def connect_d3drdb(
    username=USERNAME,
    password=None,
    host="d3drdb.gat.com",
    db="d3drdb",
    port=8001,
    password_file=DEFAULT_PASSWORD_FILE,
):
    """..."""
    if password is None:
        username, password = _read_sybase_login_file(password_file)
    conn = pymssql.connect(host, username, password, db, port=str(port))
    return conn
```

Replace this entire function with the shim. Also add `import warnings` to the existing imports at the top of the file if not already present.

```python
def connect_d3drdb(**overrides):
    """Deprecated. Use `toksearch_d3d.sql.connect_d3drdb` (or the
    generic `toksearch.sql.mssql.connect_tokamak_sql('d3d', 'd3drdb',
    **overrides)`) instead."""
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

- [ ] **Step 4: Run the deprecation tests to verify they pass.**

```bash
pixi run python -m pytest tests/test_sql_deprecation.py -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Re-run the full sql test suite to confirm no regression.**

```bash
pixi run python -m pytest tests/test_sql.py tests/test_sql_deprecation.py -v
```

Expected: all 24 PASS (21 from earlier + 3 new).

- [ ] **Step 6: Commit.**

```bash
git add toksearch/sql/mssql.py tests/test_sql_deprecation.py
git commit -m "Replace connect_d3drdb with deprecation shim delegating to toksearch_d3d.sql"
```

---

## Task 7: Delete dead helpers in `toksearch.sql.mssql`

**Files:**
- Modify: `toksearch/toksearch/sql/mssql.py`

The shim no longer uses `USERNAME`, `DEFAULT_PASSWORD_FILE`, or `_read_sybase_login_file`. Delete them.

- [ ] **Step 1: Confirm no other module uses these symbols.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
grep -rn "USERNAME\|DEFAULT_PASSWORD_FILE\|_read_sybase_login_file" --include="*.py" toksearch/
grep -rn "USERNAME\|DEFAULT_PASSWORD_FILE\|_read_sybase_login_file" --include="*.py" tests/
```

Expected: only references in `toksearch/sql/mssql.py` itself.

- [ ] **Step 2: Delete the module-level constants and helper.**

In `toksearch/toksearch/sql/mssql.py`, remove these lines (which currently sit above the shim):

```python
USER_HOME_DIR = str(Path.home())
USERNAME = getpass.getuser()
DEFAULT_PASSWORD_FILE = os.path.join(USER_HOME_DIR, "D3DRDB.sybase_login")


def _read_sybase_login_file(filename):
    with open(filename, "r") as f:
        username, password = [line.strip() for line in f.readlines()]
    return username, password
```

Also remove any now-unused imports (`USER_HOME_DIR` is gone; check if `getpass` is still imported elsewhere — Task 5 added it for `getpass.getuser()` so it stays).

- [ ] **Step 3: Run the full sql test suite.**

```bash
pixi run python -m pytest tests/test_sql.py tests/test_sql_deprecation.py -v
```

Expected: all 24 still PASS.

- [ ] **Step 4: Commit.**

```bash
git add toksearch/sql/mssql.py
git commit -m "Delete dead helpers from toksearch.sql.mssql"
```

---

# Phase C: Dependency declarations

## Task 8: Add `fdp_schema` to toksearch's conda recipe

**Files:**
- Modify: `toksearch/recipe/recipe.yaml`

- [ ] **Step 1: Read the recipe to locate the `run:` block.**

```bash
cat toksearch/recipe/recipe.yaml | head -40
```

- [ ] **Step 2: Add the dep.**

In `toksearch/recipe/recipe.yaml`, find the `run:` block (it currently lists `mdsplus-xrdcl`, `numpy`, `pymssql`, etc.). Add `fdp-schema >=0.1.1` to the list. Order: put it with other GA-FDP-channel deps if any (`mdsplus-xrdcl`), otherwise just append.

Example final block:

```yaml
  run:
    - python
    - mdsplus-xrdcl >=1,<2
    - fdp-schema >=0.1.1
    - numpy >=1.20, <2
    - pymssql
    # ... rest unchanged ...
```

- [ ] **Step 3: Commit.**

```bash
git add recipe/recipe.yaml
git commit -m "Add fdp-schema run-dep to toksearch recipe"
```

---

## Task 9: Switch toksearch's dev-env to a conda fdp-schema dep

**Files:**
- Modify: `toksearch/pixi.toml`

The editable path-dep added in Task 2 worked for local iteration. For consistency with the conda release env and to avoid CI lockfile issues (Phase 1 lesson), switch to a conda dep.

- [ ] **Step 1: Replace the editable path-dep with a conda dep.**

In `toksearch/pixi.toml`:

- In `[pypi-dependencies]`, remove `fdp_schema = { path = "../fdp_schema", editable = true }`.
- In `[dependencies]`, add `fdp-schema = ">=0.1.1"`.

- [ ] **Step 2: Refresh the pixi env.**

```bash
pixi install
```

Expected: succeeds. Lockfile now references `fdp-schema-0.1.1` from the ga-fdp channel.

- [ ] **Step 3: Verify the import still works.**

```bash
pixi run python -c "from fdp_schema import load_tokamak; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Run all sql tests.**

```bash
pixi run python -m pytest tests/test_sql.py tests/test_sql_deprecation.py -v
```

Expected: all 24 PASS.

- [ ] **Step 5: Commit.**

```bash
git add pixi.toml pixi.lock
git commit -m "Switch toksearch dev-env fdp-schema dep from editable to conda"
```

---

# Phase D: `toksearch_d3d.sql` and cleanup

## Task 10: Create `toksearch_d3d/toksearch_d3d/sql.py` and its tests

**Files:**
- Create: `toksearch_d3d/toksearch_d3d/sql.py`
- Create: `toksearch_d3d/tests/test_sql.py`

- [ ] **Step 1: Write the failing test at `toksearch_d3d/tests/test_sql.py`.**

```python
# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for toksearch_d3d.sql.connect_d3drdb."""

import os
import unittest
from pathlib import Path
from unittest import mock


class TestConnectD3DRDB(unittest.TestCase):
    def test_delegates_to_connect_tokamak_sql(self):
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch(
            "toksearch.sql.mssql.connect_tokamak_sql",
            return_value=mock.sentinel.conn,
        ) as fn:
            result = connect_d3drdb()
        fn.assert_called_once_with("d3d", "d3drdb")
        self.assertIs(result, mock.sentinel.conn)

    def test_forwards_kwargs(self):
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch(
            "toksearch.sql.mssql.connect_tokamak_sql"
        ) as fn:
            connect_d3drdb(db="code_rundb", port=9999)
        fn.assert_called_once_with(
            "d3d", "d3drdb", db="code_rundb", port=9999
        )

    @unittest.skipUnless(
        Path("~/.D3DRDB.sybase_login").expanduser().exists()
        or Path("~/D3DRDB.sybase_login").expanduser().exists(),
        "needs ~/.D3DRDB.sybase_login (or ~/D3DRDB.sybase_login)",
    )
    def test_integration_select_1(self):
        """Hits the real d3drdb. Skipped unless the password file exists."""
        from toksearch_d3d.sql import connect_d3drdb
        with connect_d3drdb() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            self.assertEqual(cur.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the test file imports fail (the module doesn't exist yet).**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
pixi run python -m pytest tests/test_sql.py -v
```

Expected: `ModuleNotFoundError: No module named 'toksearch_d3d.sql'`.

- [ ] **Step 3: Create the module.**

Write `toksearch_d3d/toksearch_d3d/sql.py`:

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

- [ ] **Step 4: Run the tests.**

```bash
pixi run python -m pytest tests/test_sql.py -v
```

Expected: 2 PASS (delegation + kwarg forwarding), 1 SKIP unless the password file exists locally. If you have `~/.D3DRDB.sybase_login` locally, the integration test runs and should PASS too.

- [ ] **Step 5: Commit.**

```bash
git add toksearch_d3d/sql.py tests/test_sql.py
git commit -m "Add toksearch_d3d.sql.connect_d3drdb as one-liner over connect_tokamak_sql"
```

---

## Task 11: Delete the Phase 1 sync test

**Files:**
- Delete: `toksearch_d3d/tests/test_sql_sync.py`

With the catalog as the single source of truth, drift between hardcoded defaults and YAML can't happen.

- [ ] **Step 1: Delete the file.**

```bash
git rm tests/test_sql_sync.py
```

- [ ] **Step 2: Run the full toksearch_d3d test suite to confirm no other test imported from it.**

```bash
pixi run python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: collection succeeds, all tests pass (or skip as appropriate).

- [ ] **Step 3: Commit.**

```bash
git commit -m "Delete Phase 1 sync test (catalog is now the single source of truth)"
```

---

# Phase E: End-to-end + release

## Task 12: End-to-end demo re-verification

**Files:** none (verification only)

- [ ] **Step 1: Back up the existing demo PNG.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
cp bn_vs_nbi_highcurrent.png bn_vs_nbi_highcurrent.before-migration.png
```

(If the PNG doesn't exist locally — e.g., on a fresh checkout — skip the backup and just run the script.)

- [ ] **Step 2: Run the demo headless and capture warnings.**

```bash
MPLBACKEND=Agg pixi run fdp run python bn_vs_nbi_highcurrent.py 2>&1 | tee /tmp/demo_output.log
```

Expected:
- `Querying shot list...` followed by `651 plasma shots found` (or whatever the current real number is — the value should match the pre-migration run).
- A `DeprecationWarning: toksearch.sql.mssql.connect_d3drdb is deprecated. Use toksearch_d3d.sql.connect_d3drdb instead ...` fires somewhere — confirms the shim is being exercised.
- `Running pipeline...` followed by `<N> records returned` and `<M> high-current shots after filtering`.
- `Saved bn_vs_nbi_highcurrent.png`.

- [ ] **Step 3: Compare the new PNG against the backup (if present).**

```bash
md5sum bn_vs_nbi_highcurrent.png bn_vs_nbi_highcurrent.before-migration.png 2>&1
```

The MD5s may differ (matplotlib PNG encoding isn't byte-stable), but visual inspection should show the same plot.

If you can view PNGs in your tooling, eyeball both. If anything's off — different shot count, different point density, different axis ranges — investigate before tagging.

- [ ] **Step 4: Clean up the backup.**

```bash
rm -f bn_vs_nbi_highcurrent.before-migration.png
```

No commit for this task — it's a verification gate.

---

## Task 13: Release tags + push + monitor CI

**Files:** none (git tag operations only)

The plan assumes `toksearch 2.7.4 → 2.8.0` and `toksearch_d3d 0.9.2 → 0.9.3`. **Verify the actual current tags first and adjust if different** (this was the lesson from Phase 1 where the plan assumed an older version than reality).

- [ ] **Step 1: Verify clean working trees, current branches, and current tags.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
git status -s
git branch --show-current   # expect: connect-d3drdb-migration
git tag --list "release-*" | tail -3

cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git status -s
git branch --show-current   # expect: connect-d3drdb-migration
git tag --list "release-*" | tail -3
```

- [ ] **Step 2: Fast-forward merge each feature branch into `main` and push.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
git checkout main
git pull --ff-only origin main
git merge --ff-only connect-d3drdb-migration
git push origin main

cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git checkout main
git pull --ff-only origin main
git merge --ff-only connect-d3drdb-migration
git push origin main
```

If either merge isn't fast-forward (main moved ahead remotely while you were working), rebase the feature branch onto the updated main first:

```bash
git checkout connect-d3drdb-migration
git rebase main
# resolve conflicts if any, re-run tests
git checkout main
git merge --ff-only connect-d3drdb-migration
git push origin main
```

- [ ] **Step 3: Verify the version that versioneer will report once the new tag exists.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
# Determine the bump:
git tag --list "release-*" | tail -1   # e.g., release-2.7.4 → bump to 2.8.0
```

Decide on target version (default per spec: minor bump for toksearch because of new public API; patch for toksearch_d3d because of new module without breaking changes).

- [ ] **Step 4: Tag and push toksearch.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
git tag release-2.8.0   # adjust to actual target
git push origin release-2.8.0
```

- [ ] **Step 5: Tag and push toksearch_d3d.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git tag release-0.9.3   # adjust to actual target
git push origin release-0.9.3
```

- [ ] **Step 6: Monitor the conda build CI for both tags.**

```bash
gh run list --repo GA-FDP/toksearch --limit 3
gh run list --repo GA-FDP/toksearch_d3d --limit 3
```

Wait for both `release-*` runs to succeed. toksearch's CI is fast (~1 min). toksearch_d3d's CI runs the recipe test (which calls `fdp run testit.py`) and takes ~15–19 min.

- [ ] **Step 7: Confirm packages on the channel.**

```bash
pixi search toksearch -c ga-fdp 2>&1 | grep -E "Name|Version" | head -3
pixi search toksearch_d3d -c ga-fdp 2>&1 | grep -E "Name|Version" | head -3
```

Expected: latest versions match the new tags.

- [ ] **Step 8: Delete the merged feature branches locally and on remote.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch
git branch -d connect-d3drdb-migration
git push origin --delete connect-d3drdb-migration

cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git branch -d connect-d3drdb-migration
git push origin --delete connect-d3drdb-migration
```

End of plan.

---

## Notes for the executing engineer

- **TDD discipline**: every code-bearing task starts with a failing test, then minimal code to pass. Don't write helpers "just in case."
- **Cache_clear() in setUp**: every test that patches `entry_points` must call `_discover_catalogs.cache_clear()` first or risk cross-test bleed.
- **`getpass.getuser()` shows up once** (in Task 5, for the explicit-password-without-username corner case). Don't accidentally import the deleted `USERNAME` constant.
- **If the demo (Task 12) breaks**: do NOT tag. The pipeline going through pymssql → catalog → `connect_tokamak_sql` is the load-bearing user-visible path. If it fails or produces a different plot, the migration broke something. Investigate before releasing.
- **If toksearch_d3d's recipe test fails in CI after tag push**: likely because the test env doesn't have a fresh-enough toksearch on the ga-fdp channel yet. toksearch 2.8.0 must upload before toksearch_d3d 0.9.3's CI runs (its recipe depends on it). If both tag pushes go out simultaneously, toksearch_d3d's might race. If it fails for this reason, wait for toksearch to upload, then re-trigger toksearch_d3d's CI by force-updating the tag (`git tag -f release-0.9.3 && git push --force-with-lease origin release-0.9.3`) or bumping to 0.9.4 and re-tagging.
- **Don't push branches/tags before user review unless explicitly authorized.** The plan documents what to do; the user decides when.
