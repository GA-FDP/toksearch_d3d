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
