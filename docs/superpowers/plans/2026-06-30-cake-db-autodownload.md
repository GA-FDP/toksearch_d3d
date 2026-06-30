# CakeSignal CAKE DB Auto-Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `CakeSignal` transparently downloads the CAKE DB (`iri_logs.db`) from the Pelican URL already published in `d3d.yaml` to a persistent, process-shared local cache on first instantiation, validating against the remote each run.

**Architecture:** A new isolated helper `toksearch_d3d/signal/_cake_cache.py` exposes one public function `ensure_local_cake_db(source)`. It passes local paths through unchanged and, for remote URLs, maintains a current cached copy under `~/.cache/fdp/cake/` — coordinated across processes with a `filelock` and published atomically with `os.replace`. `CakeSignal.__init__` routes its resolved `cake_db_location` through this helper. Remote stat/download go through two small seams (`_remote_signature`, `_download`) using the XRootD CLI (`xrdfs`/`xrdcp`), which unit tests monkeypatch.

**Tech Stack:** Python 3.11, `unittest`, `filelock`, `sqlite3`, XRootD CLI tools (`xrdfs`, `xrdcp`), `toksearch.MdsSignal`.

---

## Spec

See `docs/superpowers/specs/2026-06-30-cake-db-autodownload-design.md`.

## File Structure

- **Create** `toksearch_d3d/signal/_cake_cache.py` — the cache helper. Pure-ish functions plus the `ensure_local_cake_db` orchestrator. Sole responsibility: turn a (possibly remote) CAKE DB source into a current local path.
- **Modify** `toksearch_d3d/signal/cake.py` — import and call `ensure_local_cake_db` in `__init__` (one line + one import). Nothing else changes.
- **Create** `tests/test_cake_cache.py` — unit tests for the helper, no network (seams monkeypatched).
- **Modify** `tests/test_cake_signal.py` — re-enable a network-gated integration test.
- **Modify** `pixi.toml` and `recipe/recipe.yaml` — declare `filelock` as a runtime dependency.

---

### Task 1: Scheme detection and cache paths

**Files:**
- Create: `toksearch_d3d/signal/_cake_cache.py`
- Test: `tests/test_cake_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cake_cache.py
import os
import unittest
from pathlib import Path

from toksearch_d3d.signal import _cake_cache as cc


class TestCachePaths(unittest.TestCase):
    def test_is_remote_true_for_known_schemes(self):
        self.assertTrue(cc._is_remote("pelican://h:443/a/iri_logs.db"))
        self.assertTrue(cc._is_remote("root://h:8443/a/iri_logs.db"))
        self.assertTrue(cc._is_remote("https://h/a/iri_logs.db"))

    def test_is_remote_false_for_local_path(self):
        self.assertFalse(cc._is_remote("/tmp/iri_logs.db"))
        self.assertFalse(cc._is_remote("iri_logs.db"))

    def test_cache_dir_honors_xdg(self):
        os.environ["XDG_CACHE_HOME"] = "/tmp/xdgcache"
        try:
            self.assertEqual(cc._cache_dir(), Path("/tmp/xdgcache/fdp/cake"))
        finally:
            del os.environ["XDG_CACHE_HOME"]

    def test_local_path_uses_url_basename(self):
        os.environ["XDG_CACHE_HOME"] = "/tmp/xdgcache"
        try:
            self.assertEqual(
                cc._local_path("pelican://h:443/fdp-d3d/metadata/iri_logs.db"),
                Path("/tmp/xdgcache/fdp/cake/iri_logs.db"),
            )
        finally:
            del os.environ["XDG_CACHE_HOME"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && python -m pytest test_cake_cache.py -v`
Expected: FAIL — `ModuleNotFoundError` / `module 'toksearch_d3d.signal._cake_cache' has no attribute '_is_remote'`.

- [ ] **Step 3: Write minimal implementation**

```python
# toksearch_d3d/signal/_cake_cache.py
"""Maintain a process-shared local cache of the CAKE catalogue DB.

`ensure_local_cake_db(source)` turns a (possibly remote) CAKE DB location into a
current local file path. Local paths pass through unchanged; remote URLs are
downloaded once to ~/.cache/fdp/cake/ and re-validated against the remote on the
first call in each process.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

_REMOTE_SCHEMES = ("pelican", "root", "http", "https")


def _is_remote(source: str) -> bool:
    return urlparse(source).scheme in _REMOTE_SCHEMES


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "fdp" / "cake"


def _local_path(source: str) -> Path:
    return _cache_dir() / os.path.basename(urlparse(source).path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tests && python -m pytest test_cake_cache.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/signal/_cake_cache.py tests/test_cake_cache.py
git commit -m "feat(cake): add cache path + scheme detection helpers"
```

---

### Task 2: Parse `xrdfs stat` output into a signature

**Files:**
- Modify: `toksearch_d3d/signal/_cake_cache.py`
- Test: `tests/test_cake_cache.py`

> `xrdfs <host> stat <path>` prints lines like `Size:   8388608` and
> `MTime:   2025-05-01 12:00:00`. We extract `Size` (int) and `MTime` (string)
> as the change-detection signature. (Verify the exact field labels against a
> live `xrdfs` run during integration; the parser tolerates extra/missing
> lines.)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cake_cache.py
class TestStatParse(unittest.TestCase):
    SAMPLE = (
        "Path:   /fdp-d3d/metadata/iri_logs.db\n"
        "Id:     0001\n"
        "Size:   8388608\n"
        "MTime:  2025-05-01 12:00:00\n"
        "Flags:  16 (IsReadable)\n"
    )

    def test_parse_extracts_size_and_mtime(self):
        sig = cc._parse_xrdfs_stat(self.SAMPLE)
        self.assertEqual(sig["size"], 8388608)
        self.assertEqual(sig["mtime"], "2025-05-01 12:00:00")

    def test_parse_missing_fields_returns_partial(self):
        sig = cc._parse_xrdfs_stat("Path: /x\n")
        self.assertNotIn("size", sig)
        self.assertNotIn("mtime", sig)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && python -m pytest test_cake_cache.py::TestStatParse -v`
Expected: FAIL — `module 'toksearch_d3d.signal._cake_cache' has no attribute '_parse_xrdfs_stat'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to toksearch_d3d/signal/_cake_cache.py
def _parse_xrdfs_stat(output: str) -> dict:
    """Extract {'size': int, 'mtime': str} from `xrdfs stat` text output."""
    sig: dict = {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Size:"):
            try:
                sig["size"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("MTime:"):
            sig["mtime"] = line.split(":", 1)[1].strip()
    return sig
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tests && python -m pytest test_cake_cache.py::TestStatParse -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/signal/_cake_cache.py tests/test_cake_cache.py
git commit -m "feat(cake): parse xrdfs stat output into change signature"
```

---

### Task 3: `ensure_local_cake_db` — local path passthrough

**Files:**
- Modify: `toksearch_d3d/signal/_cake_cache.py`
- Test: `tests/test_cake_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cake_cache.py
class TestEnsureLocalPassthrough(unittest.TestCase):
    def test_local_path_returned_unchanged(self):
        self.assertEqual(cc.ensure_local_cake_db("/data/iri_logs.db"),
                         "/data/iri_logs.db")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && python -m pytest test_cake_cache.py::TestEnsureLocalPassthrough -v`
Expected: FAIL — `has no attribute 'ensure_local_cake_db'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to toksearch_d3d/signal/_cake_cache.py
def ensure_local_cake_db(source: str, *, force: bool = False) -> str:
    """Return a local path to the CAKE DB.

    Local `source` paths are returned unchanged. Remote URLs (pelican://,
    root://, http(s)://) are cached locally and re-validated; see module docs.
    """
    if not _is_remote(source):
        return source
    raise NotImplementedError  # remote handling added in Task 4
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tests && python -m pytest test_cake_cache.py::TestEnsureLocalPassthrough -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/signal/_cake_cache.py tests/test_cake_cache.py
git commit -m "feat(cake): ensure_local_cake_db passes local paths through"
```

---

### Task 4: `ensure_local_cake_db` — remote download to cache

**Files:**
- Modify: `toksearch_d3d/signal/_cake_cache.py`
- Test: `tests/test_cake_cache.py`

> Introduces the two seams (`_remote_signature`, `_download`), the sidecar
> meta, the `filelock`, and atomic publish. Tests monkeypatch the seams and
> redirect `XDG_CACHE_HOME` to a temp dir, so no network is touched.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cake_cache.py
import tempfile
import shutil


class _RemoteFixture:
    """Helper: a fake remote DB file plus a monkeypatched seam set."""
    def __init__(self, testcase, contents=b"DBDATA", sig=None):
        self.dl_calls = 0
        self.stat_calls = 0
        self._contents = contents
        self._sig = sig or {"size": len(contents), "mtime": "2025-05-01 12:00:00"}
        testcase.tmp = tempfile.mkdtemp()
        os.environ["XDG_CACHE_HOME"] = testcase.tmp
        cc._validated.clear()
        testcase.addCleanup(lambda: shutil.rmtree(testcase.tmp, ignore_errors=True))
        testcase.addCleanup(lambda: os.environ.pop("XDG_CACHE_HOME", None))
        testcase.addCleanup(cc._validated.clear)

        def fake_stat(source):
            self.stat_calls += 1
            return dict(self._sig)

        def fake_download(source, dest):
            self.dl_calls += 1
            Path(dest).write_bytes(self._contents)

        testcase._orig = (cc._remote_signature, cc._download)
        cc._remote_signature = fake_stat
        cc._download = fake_download
        testcase.addCleanup(self._restore, testcase)

    def _restore(self, testcase):
        cc._remote_signature, cc._download = testcase._orig

    def set_signature(self, sig):
        self._sig = sig


class TestEnsureLocalDownload(unittest.TestCase):
    URL = "pelican://h:443/fdp-d3d/metadata/iri_logs.db"

    def test_downloads_and_returns_local_path(self):
        fx = _RemoteFixture(self)
        path = cc.ensure_local_cake_db(self.URL)
        self.assertEqual(path, os.path.join(self.tmp, "fdp/cake/iri_logs.db"))
        self.assertEqual(Path(path).read_bytes(), b"DBDATA")
        self.assertEqual(fx.dl_calls, 1)

    def test_writes_sidecar_meta(self):
        _RemoteFixture(self)
        path = cc.ensure_local_cake_db(self.URL)
        meta = Path(path + ".meta.json")
        self.assertTrue(meta.exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && python -m pytest test_cake_cache.py::TestEnsureLocalDownload -v`
Expected: FAIL — `NotImplementedError` (and `_remote_signature`/`_download` not defined).

- [ ] **Step 3: Write minimal implementation**

```python
# add imports at top of toksearch_d3d/signal/_cake_cache.py
import json
import logging
import subprocess
from filelock import FileLock

logger = logging.getLogger(__name__)

_validated: set = set()  # per-process memo of validated source URLs


def _split_host_path(url: str):
    p = urlparse(url)
    return p.netloc, p.path


def _remote_signature(source: str):
    """Return {'size','mtime'} via `xrdfs <host> stat <path>`, or None on failure."""
    host, path = _split_host_path(source)
    try:
        proc = subprocess.run(
            ["xrdfs", host, "stat", path],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("xrdfs stat failed for %s: %s", source, exc)
        return None
    return _parse_xrdfs_stat(proc.stdout)


def _download(source: str, dest: str) -> None:
    """Copy the remote DB to `dest` with `xrdcp -f`."""
    subprocess.run(["xrdcp", "-f", source, str(dest)], check=True)


def _meta_path(local: Path) -> Path:
    return local.with_name(local.name + ".meta.json")


def _read_meta(local: Path):
    mp = _meta_path(local)
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_meta(local: Path, sig: dict) -> None:
    _meta_path(local).write_text(json.dumps(sig))
```

```python
# replace the body of ensure_local_cake_db with:
def ensure_local_cake_db(source: str, *, force: bool = False) -> str:
    """Return a local path to the CAKE DB.

    Local `source` paths are returned unchanged. Remote URLs (pelican://,
    root://, http(s)://) are cached locally and re-validated; see module docs.
    """
    if not _is_remote(source):
        return source

    if source in _validated and not force:
        return str(_local_path(source))

    local = _local_path(source)
    local.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(str(local) + ".lock"):
        sig = _remote_signature(source)
        if sig is None:
            if local.exists():
                logger.warning("Using cached CAKE DB (remote stat failed): %s", local)
                _validated.add(source)
                return str(local)
            raise RuntimeError(
                f"Cannot stat remote CAKE DB {source!r} and no local cache "
                f"exists. Ensure the FDP environment is active (xrdfs/xrdcp on "
                f"PATH, BEARER_TOKEN set)."
            )
        if force or not local.exists() or _read_meta(local) != sig:
            tmp = local.with_name(f"{local.name}.tmp.{os.getpid()}")
            _download(source, str(tmp))
            os.replace(tmp, local)
            _write_meta(local, sig)

    _validated.add(source)
    return str(local)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tests && python -m pytest test_cake_cache.py::TestEnsureLocalDownload -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/signal/_cake_cache.py tests/test_cake_cache.py
git commit -m "feat(cake): download remote CAKE DB to shared cache (lock + atomic publish)"
```

---

### Task 5: Skip / re-download / force based on signature

**Files:**
- Modify: `tests/test_cake_cache.py` (no implementation change — Task 4 code already covers this; this task verifies it)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cake_cache.py
class TestEnsureLocalRefresh(unittest.TestCase):
    URL = "pelican://h:443/fdp-d3d/metadata/iri_logs.db"

    def test_unchanged_signature_skips_download_on_new_process(self):
        fx = _RemoteFixture(self)
        cc.ensure_local_cake_db(self.URL)
        self.assertEqual(fx.dl_calls, 1)
        cc._validated.clear()  # simulate a fresh process, same cache dir
        cc.ensure_local_cake_db(self.URL)
        self.assertEqual(fx.dl_calls, 1)  # signature matched -> no re-download

    def test_changed_signature_redownloads(self):
        fx = _RemoteFixture(self)
        cc.ensure_local_cake_db(self.URL)
        self.assertEqual(fx.dl_calls, 1)
        cc._validated.clear()
        fx.set_signature({"size": 999, "mtime": "2025-06-01 00:00:00"})
        cc.ensure_local_cake_db(self.URL)
        self.assertEqual(fx.dl_calls, 2)

    def test_force_redownloads_even_when_unchanged(self):
        fx = _RemoteFixture(self)
        cc.ensure_local_cake_db(self.URL)
        cc.ensure_local_cake_db(self.URL, force=True)
        self.assertEqual(fx.dl_calls, 2)
```

- [ ] **Step 2: Run test to verify it passes (behavior already implemented)**

Run: `cd tests && python -m pytest test_cake_cache.py::TestEnsureLocalRefresh -v`
Expected: PASS (3 tests). If any fail, fix `ensure_local_cake_db` in `_cake_cache.py` — do not edit the tests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cake_cache.py
git commit -m "test(cake): cover signature skip/refresh/force behavior"
```

---

### Task 6: Per-process memoization avoids redundant stats

**Files:**
- Modify: `tests/test_cake_cache.py` (verifies Task 4 behavior)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cake_cache.py
class TestEnsureLocalMemo(unittest.TestCase):
    URL = "pelican://h:443/fdp-d3d/metadata/iri_logs.db"

    def test_second_call_same_process_does_not_stat(self):
        fx = _RemoteFixture(self)
        cc.ensure_local_cake_db(self.URL)
        cc.ensure_local_cake_db(self.URL)
        cc.ensure_local_cake_db(self.URL)
        self.assertEqual(fx.stat_calls, 1)  # memoized after first
        self.assertEqual(fx.dl_calls, 1)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd tests && python -m pytest test_cake_cache.py::TestEnsureLocalMemo -v`
Expected: PASS. If it fails, fix the memo check in `ensure_local_cake_db` — do not edit the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cake_cache.py
git commit -m "test(cake): per-process memoization skips redundant stats"
```

---

### Task 7: Resilience when remote stat fails

**Files:**
- Modify: `tests/test_cake_cache.py` (verifies Task 4 behavior)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cake_cache.py
class TestEnsureLocalResilience(unittest.TestCase):
    URL = "pelican://h:443/fdp-d3d/metadata/iri_logs.db"

    def test_stat_fail_with_cache_uses_cache(self):
        fx = _RemoteFixture(self)
        cc.ensure_local_cake_db(self.URL)   # populate cache
        cc._validated.clear()
        cc._remote_signature = lambda source: None  # remote now unreachable
        path = cc.ensure_local_cake_db(self.URL)
        self.assertEqual(Path(path).read_bytes(), b"DBDATA")

    def test_stat_fail_without_cache_raises(self):
        _RemoteFixture(self)
        cc._remote_signature = lambda source: None
        with self.assertRaises(RuntimeError):
            cc.ensure_local_cake_db(self.URL)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd tests && python -m pytest test_cake_cache.py::TestEnsureLocalResilience -v`
Expected: PASS (2 tests). If it fails, fix the `sig is None` branch in `ensure_local_cake_db` — do not edit the tests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cake_cache.py
git commit -m "test(cake): resilience when remote stat fails (use cache / raise)"
```

---

### Task 8: Wire `ensure_local_cake_db` into `CakeSignal`

**Files:**
- Modify: `toksearch_d3d/signal/cake.py:1-5` (import) and `toksearch_d3d/signal/cake.py:70-74` (resolution)
- Test: `tests/test_cake_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cake_cache.py
from unittest import mock


class TestCakeSignalUsesCache(unittest.TestCase):
    def test_init_routes_db_location_through_cache(self):
        # A remote URL should be converted to the local cache path during init,
        # with no MDSplus/network access.
        with mock.patch(
            "toksearch_d3d.signal.cake.ensure_local_cake_db",
            return_value="/cache/iri_logs.db",
        ) as ensure:
            from toksearch_d3d import CakeSignal
            sig = CakeSignal(
                r"\ipmhd", "eq",
                cake_db_location="pelican://h:443/fdp-d3d/metadata/iri_logs.db",
            )
        ensure.assert_called_once_with(
            "pelican://h:443/fdp-d3d/metadata/iri_logs.db"
        )
        self.assertEqual(sig.cake_db_location, "/cache/iri_logs.db")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tests && python -m pytest test_cake_cache.py::TestCakeSignalUsesCache -v`
Expected: FAIL — `AttributeError: <module 'toksearch_d3d.signal.cake'> does not have the attribute 'ensure_local_cake_db'`.

- [ ] **Step 3: Write minimal implementation**

In `toksearch_d3d/signal/cake.py`, add the import near the top (after the existing imports on lines 1-5):

```python
from toksearch_d3d.signal._cake_cache import ensure_local_cake_db
```

Then change the resolution block (currently lines 70-74):

```python
        self.cake_db_location = cake_db_location or os.getenv("CAKE_DB_PATH", None)

        if not self.cake_db_location:
            msg = f"cake_db_location not set"
            raise Exception(msg)
```

to:

```python
        self.cake_db_location = cake_db_location or os.getenv("CAKE_DB_PATH", None)

        if not self.cake_db_location:
            msg = f"cake_db_location not set"
            raise Exception(msg)

        # If the location is a remote (e.g. pelican://) URL, download it to a
        # process-shared local cache and use that path. Local paths pass
        # through unchanged.
        self.cake_db_location = ensure_local_cake_db(self.cake_db_location)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tests && python -m pytest test_cake_cache.py::TestCakeSignalUsesCache -v`
Expected: PASS.

- [ ] **Step 5: Run the full helper test module**

Run: `cd tests && python -m pytest test_cake_cache.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add toksearch_d3d/signal/cake.py tests/test_cake_cache.py
git commit -m "feat(cake): CakeSignal auto-downloads remote CAKE DB on init"
```

---

### Task 9: Declare `filelock` as a runtime dependency

**Files:**
- Modify: `pixi.toml:20-29` (`[dependencies]`)
- Modify: `recipe/recipe.yaml:35-39` (`requirements.run`)

- [ ] **Step 1: Add to `pixi.toml`**

Under `[dependencies]` (after the `imas_composer` line, ~line 25), add:

```toml
filelock = ">=3"
```

- [ ] **Step 2: Add to `recipe/recipe.yaml`**

Under `requirements: run:` (after `- imas_composer >=0.2`, ~line 39), add:

```yaml
    - filelock >=3
```

- [ ] **Step 3: Verify the env still resolves**

Run: `pixi run python -c "import filelock; print(filelock.__version__)"`
Expected: prints a version `>= 3` (e.g. `3.29.0`).

- [ ] **Step 4: Commit**

```bash
git add pixi.toml recipe/recipe.yaml
git commit -m "build(cake): add filelock runtime dependency"
```

---

### Task 10: Re-enable the gated CakeSignal integration test

**Files:**
- Modify: `tests/test_cake_signal.py` (replace the commented-out body)

> This is the design's network-gated integration test. It runs only when the
> FDP environment is active (so `xrdfs`/`xrdcp` and `BEARER_TOKEN` are present),
> using the real Pelican URL from `d3d.yaml`. Mirrors the
> `skipTest("requires BEARER_TOKEN ...")` pattern in `test_fdp_decoupling.py`.

- [ ] **Step 1: Replace the file body**

Replace the commented-out block (lines 18-40) of `tests/test_cake_signal.py` with:

```python
import sqlite3

from toksearch_d3d.signal._cake_cache import ensure_local_cake_db

CAKE_DB_URL = "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db"


class TestCakeDbDownload(unittest.TestCase):
    """Network-gated: exercises the real Pelican download path."""

    def setUp(self):
        if os.environ.get("TOKSEARCH_INTEGRATION") != "yes":
            self.skipTest("integration test (set via testit.py without --mock)")
        if not (os.environ.get("BEARER_TOKEN") and os.environ.get("CONDA_PREFIX")):
            self.skipTest("requires BEARER_TOKEN and CONDA_PREFIX (FDP env)")

    def test_downloads_and_opens_blessed_cakes(self):
        path = ensure_local_cake_db(CAKE_DB_URL, force=True)
        self.assertTrue(os.path.exists(path))
        with sqlite3.connect(path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM blessed_cakes")
            self.assertGreater(cur.fetchone()[0], 0)
```

- [ ] **Step 2: Run it (skips without FDP env)**

Run: `cd tests && TOKSEARCH_INTEGRATION=no python -m pytest test_cake_signal.py -v`
Expected: the test is SKIPPED (no error).

- [ ] **Step 3: Run it for real if an FDP env is available**

Run: `pixi run fdp run bash -c 'cd tests && TOKSEARCH_INTEGRATION=yes python -m pytest test_cake_signal.py -v'`
Expected: PASS — downloads `iri_logs.db` and counts `blessed_cakes` rows. (If no token is available, it SKIPS — acceptable.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_cake_signal.py
git commit -m "test(cake): re-enable CakeSignal download integration test (gated)"
```

---

### Task 11: Full suite + manual smoke check

**Files:** none (verification only)

- [ ] **Step 1: Run the mocked suite**

Run: `pixi run bash -c 'cd tests && python testit.py --mock --fast-exit'`
Expected: OK — all unit tests pass, integration tests skipped.

- [ ] **Step 2: Manual smoke (only if an FDP env/token is available)**

Run:
```bash
pixi run fdp run python -c "
from toksearch_d3d import CakeSignal
s = CakeSignal(r'\\ipmhd', 'eq')   # no cake_db_location -> uses CAKE_DB_PATH from catalog
print('resolved local db:', s.cake_db_location)
"
```
Expected: prints a path under `~/.cache/fdp/cake/iri_logs.db` (a real local file), not a `pelican://` URL. (Skips/needs a token; acceptable to defer to CI.)

- [ ] **Step 3: Final commit (if any uncommitted verification artifacts)**

```bash
git status   # expect clean
```

---

## Self-Review notes

- **Spec coverage:** cache location (Task 1), refresh/validate-every-run (Tasks 4–5), URL-already-in-catalog passthrough + remote detection (Tasks 1, 3, 8), per-process memo (Task 6), xrdfs/xrdcp seams (Tasks 2, 4), shared-file concurrency via `filelock` + atomic `os.replace` (Task 4), resilience table (Task 7), `filelock` dependency (Task 9), gated integration test re-enabling `test_cake_signal.py` (Task 10). All covered.
- **Feasibility fallback** (xrdfs stat may not resolve `pelican://`): surfaced in Task 2's note and exercised by the Task 10 integration run; if `_remote_signature` returns `None` in practice, the Task 7 resilience path keeps things correct (download-once via the cache), and the parser/seam can be adjusted without touching the orchestrator's tests.
- **Type consistency:** `_remote_signature`/`_download`/`_local_path`/`_read_meta`/`_write_meta`/`_parse_xrdfs_stat`/`ensure_local_cake_db` names and signatures are identical across all tasks and the `CakeSignal` call site.
