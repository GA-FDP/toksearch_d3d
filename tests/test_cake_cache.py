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
