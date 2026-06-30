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


class TestEnsureLocalPassthrough(unittest.TestCase):
    def test_local_path_returned_unchanged(self):
        self.assertEqual(cc.ensure_local_cake_db("/data/iri_logs.db"),
                         "/data/iri_logs.db")


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
