# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
import os
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
