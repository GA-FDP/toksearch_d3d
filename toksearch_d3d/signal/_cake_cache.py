"""Maintain a process-shared local cache of the CAKE catalogue DB.

`ensure_local_cake_db(source)` turns a (possibly remote) CAKE DB location into a
current local file path. Local paths pass through unchanged; remote URLs are
downloaded once to ~/.cache/fdp/cake/ and re-validated against the remote on the
first call in each process.

Remote access uses the ``pelican`` object CLI (``pelican object stat`` /
``pelican object get``) rather than ``xrdfs``/``xrdcp``: pelican performs its own
token discovery/refresh, which is far more robust than relying on a valid
``BEARER_TOKEN`` being present in the environment, and it reports actionable
errors (e.g. authorization failures) that we surface to the caller.
"""
import json
import logging
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from filelock import FileLock

logger = logging.getLogger(__name__)

_REMOTE_SCHEMES = ("pelican", "osdf", "root", "http", "https")

# Bounded timeouts so a stalled pelican transfer cannot wedge the process
# forever; without these the resilience fallback (stat fails -> serve cache /
# raise) can never fire.
_STAT_TIMEOUT_S = 30
_DOWNLOAD_TIMEOUT_S = 600

_validated: set = set()  # per-process memo of validated source URLs

# Best-effort detail (stderr / exception) from the most recent stat failure,
# surfaced in the "cannot stat" error so users see the real cause (e.g. an
# expired token) instead of a generic checklist. Set inside _remote_signature.
_last_remote_error: "str | None" = None


def _is_remote(source: str) -> bool:
    return urlparse(source).scheme in _REMOTE_SCHEMES


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "fdp" / "cake"


def _local_path(source: str) -> Path:
    return _cache_dir() / os.path.basename(urlparse(source).path)


def _describe_proc_error(exc) -> str:
    """Human-readable one-liner for a subprocess failure, preferring stderr."""
    if isinstance(exc, FileNotFoundError):
        return "pelican not found on PATH"
    stderr = getattr(exc, "stderr", None)
    if stderr:
        lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
        if lines:
            return lines[-1]
    return str(exc)


def _parse_pelican_stat(output: str) -> dict:
    """Extract {'size': int, 'mtime': str} from `pelican object stat` output.

    Sample::

        Name: /fdp-d3d/metadata/iri_logs.db
        Size: 11038720
        ModTime: 2026-06-30 15:34:49 +0000 GMT
        IsCollection: false
    """
    sig: dict = {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Size:"):
            try:
                sig["size"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("ModTime:"):
            sig["mtime"] = line.split(":", 1)[1].strip()
    return sig


def _remote_signature(source: str):
    """Return {'size','mtime'} via `pelican object stat <url>`, or None on failure.

    On failure the detail (last stderr line / exception) is stashed in
    ``_last_remote_error`` so ``ensure_local_cake_db`` can surface it.
    """
    global _last_remote_error
    try:
        proc = subprocess.run(
            ["pelican", "object", "stat", source],
            capture_output=True, text=True, check=True,
            timeout=_STAT_TIMEOUT_S,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ) as exc:
        _last_remote_error = _describe_proc_error(exc)
        logger.warning(
            "pelican object stat failed for %s: %s", source, _last_remote_error
        )
        return None
    _last_remote_error = None
    return _parse_pelican_stat(proc.stdout)


def _download(source: str, dest: str) -> None:
    """Copy the remote DB to `dest` with `pelican object get`."""
    try:
        subprocess.run(
            ["pelican", "object", "get", source, str(dest)],
            capture_output=True, text=True, check=True,
            timeout=_DOWNLOAD_TIMEOUT_S,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ) as exc:
        raise RuntimeError(
            f"`pelican object get` failed: {_describe_proc_error(exc)}"
        ) from exc


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


def _staleness_key(meta) -> tuple:
    """The stable fields used to decide staleness. Endpoint MTime is volatile
    (Pelican returns a near-now MTime on every stat), so mtime is excluded —
    only size and source url are compared. CAKE is append-mostly, so size
    reliably grows when new shots are blessed."""
    if not meta:
        return (None, None)
    return (meta.get("size"), meta.get("url"))


def ensure_local_cake_db(source: str, *, force: bool = False) -> str:
    """Return a local path to the CAKE DB.

    Local `source` paths are returned unchanged. Remote URLs (pelican://,
    osdf://, root://, http(s)://) are cached locally and re-validated; see
    module docs.
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
            detail = f" ({_last_remote_error})" if _last_remote_error else ""
            raise RuntimeError(
                f"Cannot stat remote CAKE DB {source!r} and no local cache "
                f"exists{detail}. This usually means an expired or missing "
                f"token. Verify access with `pelican object get {source} "
                f"<local>` (refresh your FDP token if it fails), or set "
                f"CAKE_DB_PATH to a local copy of the DB."
            )
        meta = {**sig, "url": source}
        if (force or not local.exists()
                or _staleness_key(_read_meta(local)) != _staleness_key(meta)):
            tmp = local.with_name(f"{local.name}.tmp.{os.getpid()}")
            try:
                _download(source, str(tmp))
                os.replace(tmp, local)
            except Exception as exc:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                if local.exists():
                    logger.warning(
                        "Using cached CAKE DB (remote download failed): %s (%s)",
                        local, exc,
                    )
                    _validated.add(source)
                    return str(local)
                raise RuntimeError(
                    f"Failed to download remote CAKE DB {source!r} and no local "
                    f"cache exists: {exc}. Verify access with `pelican object "
                    f"get {source} <local>`, or set CAKE_DB_PATH to a local copy."
                ) from exc
            _write_meta(local, meta)

    _validated.add(source)
    return str(local)
