# CakeSignal CAKE DB auto-download — design

**Date:** 2026-06-30
**Status:** Approved (pending spec review)

## Problem

`CakeSignal` needs a local SQLite "CAKE catalogue" (`iri_logs.db`, ~8 MB, table
`BLESSED_CAKES`) to map a shot to its EFIT/OMFIT MDSplus upload IDs. Today the
class requires the caller to hand it a **local** path via the `cake_db_location`
argument or the `CAKE_DB_PATH` environment variable, and raises if neither is
set:

```python
self.cake_db_location = cake_db_location or os.getenv("CAKE_DB_PATH", None)
if not self.cake_db_location:
    raise Exception("cake_db_location not set")
...
_conn_cache = sqlite3.connect(self.cake_db_location)
```

The catalog (`d3d.yaml` `extra_env`) already publishes `CAKE_DB_PATH`, but it
holds the **Pelican URL**, not a local path:

```yaml
extra_env:
  CAKE_DB_PATH: "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db"
```

So under `fdp run` / `setup_environment()`, `CakeSignal` receives that URL and
calls `sqlite3.connect("pelican://…")`, which cannot work — sqlite treats it as
a literal filename. Users currently have to download the DB by hand (as the
`fetch_cake_equilibria.py` example script does with `xrdcp` into a
`tempfile.mkdtemp()`).

**Goal:** `CakeSignal` should transparently download the CAKE DB from Pelican to
a persistent local cache on first instantiation, and connect to the local copy —
so it "just works" under the standard FDP environment with no manual step.

## Decisions (from brainstorming)

1. **Cache location:** persistent home dir — `~/.cache/fdp/cake/iri_logs.db`
   (XDG-aware: honor `$XDG_CACHE_HOME`). Downloaded once, reused across
   sessions.
2. **Refresh policy:** re-validate against the remote and re-download if it
   changed. The DB grows as new shots are blessed; a stale cache must not go
   silently out of date.
3. **URL source:** already solved by the catalog — `CAKE_DB_PATH` in `d3d.yaml`
   `extra_env` carries the Pelican URL. No new locator. The job is to detect
   that the resolved value is a *remote URL* and download it. A plain local path
   is still accepted unchanged (back-compat).
4. **Validation granularity:** once per process, memoized. The first
   `CakeSignal` in a process stats the remote and conditionally re-downloads; all
   later instances in that process reuse the validated copy. A fresh run (or a
   spawned worker) re-validates.
5. **Fetch mechanism:** XRootD CLI tools (`xrdfs stat` + `xrdcp`) — the same
   toolchain `fetch_cake_equilibria.py` and the FDP env already provide. No new
   async/HTTP dependency.

### Why not pelicanfs / fsspec

fsspec's `filecache::`/`simplecache::` would give caching + sharing nearly for
free, but:

- The project already evaluated **pelicanfs** for ptdata's core path and
  abandoned it (see `ptdata/debug_pelicanfs.py`, `debug_async.py` — event-loop
  forensics); ptdata moved to **libfdpio** (C/XRootD). pelicanfs is in no
  `pixi.toml`/recipe in the stack and is not installed.
- pelicanfs is async (aiohttp). `CakeSignal` runs inside `compute_multiprocessing`
  (fork on Linux) and `compute_ray` — fork + a live asyncio event loop is exactly
  the failure mode those debug scripts chronicle.
- Auth would need wiring to the FDP `BEARER_TOKEN`; the CLI tools inherit it from
  the already-configured environment.

For a one-time 8 MB metadata fetch off the hot data path, the CLI-subprocess
approach is smaller, auth-free, and event-loop-free.

## Architecture

### New isolated unit: `toksearch_d3d/signal/_cake_cache.py`

One public function, independently testable:

```python
def ensure_local_cake_db(source: str, *, force: bool = False) -> str:
    """Return a local path to the CAKE DB.

    If `source` is a local file path, return it unchanged. If it is a remote URL
    (pelican://, root://, http://, https://), ensure a current cached copy exists
    at ~/.cache/fdp/cake/<basename> and return that local path.
    """
```

Behavior:

- **Scheme detection.** Parse `source`. If it has a recognized remote scheme
  (`pelican`, `root`, `http`, `https`), treat as remote. Otherwise return it
  unchanged (existing local-path callers and tests are untouched).
- **Cache path.** `cache_dir = $XDG_CACHE_HOME/fdp/cake` or
  `~/.cache/fdp/cake`; `local = cache_dir / basename(source)`; sidecar
  `meta = local + ".meta.json"` records the last-seen remote `{size, mtime, url}`.
- **Per-process memo.** A module-level `set` of source URLs already validated in
  this process. If `source` is in it and `force` is False, return `local`
  immediately (no network).
- **Coordinated validate/download**, under a cross-process `filelock`
  (`local + ".lock"`):
  1. `xrdfs <host> stat <path>` → `(size, mtime)`.
  2. If the DB is missing, or the stat differs from the sidecar, or `force`:
     `xrdcp -f <source> <tmp>` where `tmp = local + ".tmp.<pid>"`, then
     `os.replace(tmp, local)` (atomic publish), then write the sidecar.
  3. Add `source` to the memo; return `local`.
- **Resilience.** If the remote stat fails but a cached DB exists → log a warning
  and use the cache (offline tolerance). If it fails with no cache → raise an
  informative error naming the URL and required FDP env. `force=True` bypasses
  the memo and the staleness comparison.
- **Feasibility fallback.** If `xrdfs stat` cannot resolve `pelican://` URLs in
  practice, degrade to "download once per process" (memoized, no staleness skip).
  Still correct; just re-fetches each run instead of skipping on unchanged
  remote. This is decided during implementation by a real `xrdfs stat` check.

### Host/path parsing

`pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db` →
host `osg-htc.org:443`, path `/fdp-d3d/metadata/iri_logs.db`. `xrdfs` takes the
host as its first argument and the path as the stat target. `xrdcp` takes the
full URL. Both inherit Pelican plugin config and `BEARER_TOKEN` from the env.

### `CakeSignal.__init__` change (minimal)

After the existing resolution of `cake_db_location` (arg → `CAKE_DB_PATH` env,
unchanged) and the existing "not set" guard, pass the value through the cache:

```python
self.cake_db_location = ensure_local_cake_db(self.cake_db_location)
```

Everything downstream — `get_db_conn`, `get_upload_ids`, `gather`, `cleanup` —
already operates on a local path and is unchanged.

### Concurrency: one shared file for all processes

- **Shared path:** every process on the user/host resolves to the same
  `~/.cache/fdp/cake/iri_logs.db`.
- **Cross-process lock** (`filelock`) serializes validate/download: exactly one
  process downloads; others block, then find the file current and skip.
- **Atomic publish** (`os.replace`) guarantees no process reads a half-written
  DB — correctness holds even if locking is imperfect (e.g. NFS home).
- **Eager + memoized:** the parent builds all `CakeSignal`s before fork and
  downloads once; forked workers inherit the file and the per-process memo and
  never re-check. Spawn/Ray workers do at most one `xrdfs stat`, find the file
  current, and download nothing.
- **Graceful degradation:** on multi-node Ray over NFS, locking may be
  best-effort, but atomic replace keeps correctness — worst case a few nodes
  redundantly fetch 8 MB. No torn reads.

## Error handling summary

| Situation | Behavior |
|-----------|----------|
| `source` is a local path | Returned unchanged |
| Remote, cache absent, download OK | Download, publish, return local |
| Remote, cache current | Return local (skip download) |
| Remote stat fails, cache present | Warn, use stale cache |
| Remote stat fails, no cache | Raise (name URL + required FDP env) |
| Download fails mid-transfer | Temp file discarded; raise (or use existing cache if present) |
| `force=True` | Bypass memo + staleness; re-stat and re-download |

## Testing

- **Unit (no network).** Monkeypatch the `xrdfs`/`xrdcp` calls to operate on a
  local fixture DB:
  - local path returned as-is;
  - remote path copies into the cache and returns the local path;
  - per-process memoization (second call performs no stat);
  - re-download when the sidecar signature differs;
  - atomic publish (no partial file observable);
  - lock serializes two concurrent threads to a single download.
- **Integration (opt-in, FDP-env gated like the ptdata tests).** Real download
  of `iri_logs.db`, open it, `SELECT … FROM BLESSED_CAKES`. **Re-enables** the
  currently-disabled `tests/test_cake_signal.py` in a network-gated form.

## Dependencies

- Add `filelock` to `pyproject.toml` and the rattler-build recipe run-deps
  (already present in the dev env; make it an explicit dependency).
- No new async/HTTP dependency. `xrdfs`/`xrdcp` come from the XRootD client
  already required by the FDP environment.

## Out of scope

- Changing the CAKE DB URL or moving it into a dedicated locator kind — the
  existing `extra_env: CAKE_DB_PATH` is sufficient.
- Any change to the MDSplus data path or the upload-ID lookup logic.
- A general-purpose Pelican download utility for other signal classes (this
  cache helper is CAKE-specific for now; can be generalized later if needed).
