"""Maintain a process-shared local cache of the CAKE catalogue DB.

`ensure_local_cake_db(source)` turns a (possibly remote) CAKE DB location into a
current local file path. Local paths pass through unchanged; remote URLs are
downloaded once to ~/.cache/fdp/cake/ and re-validated against the remote on the
first call in each process.
"""
import json
import logging
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from filelock import FileLock

logger = logging.getLogger(__name__)

_REMOTE_SCHEMES = ("pelican", "root", "http", "https")

_validated: set = set()  # per-process memo of validated source URLs


def _is_remote(source: str) -> bool:
    return urlparse(source).scheme in _REMOTE_SCHEMES


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "fdp" / "cake"


def _local_path(source: str) -> Path:
    return _cache_dir() / os.path.basename(urlparse(source).path)


def _split_host_path(url: str):
    p = urlparse(url)
    return p.netloc, p.path


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
        meta = {**sig, "url": source}
        if force or not local.exists() or _read_meta(local) != meta:
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
                    f"cache exists. Ensure the FDP environment is active "
                    f"(xrdfs/xrdcp on PATH, BEARER_TOKEN set)."
                ) from exc
            _write_meta(local, meta)

    _validated.add(source)
    return str(local)
