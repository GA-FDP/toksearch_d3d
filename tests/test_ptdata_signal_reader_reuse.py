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

"""PtDataSignal now fetches via the modern PtDataReader and reuses one reader
per process (a PtDataReaderRegistry singleton), so a pipeline of many shots
issues a single fetch per shot on one shared, pooled ptserver connection —
instead of the legacy PtDataFetcher's per-shot reader + separate header read.

These tests pin the reuse/lifecycle contract. Data-correctness/units parity is
covered by test_ptdata_signal.py.
"""

import os
import pickle
import unittest

from toksearch_d3d.signal.ptdata import PtDataSignal, PtDataReaderRegistry

TEST_SHOTS = os.environ.get(
    "PTDATA_TEST_SHOTS_DIR", "/cscratch/sammuli/ptdata_test_files")


def _shots_available():
    return os.path.isfile(os.path.join(TEST_SHOTS, "165920.MAG"))


@unittest.skipUnless(_shots_available(),
                     f"local test shots not found at {TEST_SHOTS}")
class TestPtDataReaderReuse(unittest.TestCase):
    SHOT = 165920
    PTNAME = "ip"

    def setUp(self):
        self._env_backup = {k: os.environ.get(k)
                            for k in ("SYS_D3", "SYS_D3_DELIM")}
        os.environ["SYS_D3"] = TEST_SHOTS
        os.environ["SYS_D3_DELIM"] = ";"
        PtDataReaderRegistry().close()  # test isolation

    def tearDown(self):
        PtDataReaderRegistry().close()
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_registry_is_singleton(self):
        self.assertIs(PtDataReaderRegistry(), PtDataReaderRegistry())

    def test_reader_created_lazily(self):
        # No reader until the first gather.
        self.assertIsNone(PtDataReaderRegistry()._reader)
        PtDataSignal(self.PTNAME).fetch(self.SHOT)
        self.assertIsNotNone(PtDataReaderRegistry()._reader)

    def test_reader_reused_across_fetches(self):
        sig = PtDataSignal(self.PTNAME)
        sig.fetch(self.SHOT)
        r1 = PtDataReaderRegistry().reader()
        sig.fetch(self.SHOT)
        r2 = PtDataReaderRegistry().reader()
        self.assertIs(r1, r2)

    def test_distinct_signals_share_one_reader(self):
        # Two independent Signal instances must share the one process reader.
        PtDataSignal(self.PTNAME).fetch(self.SHOT)
        r1 = PtDataReaderRegistry().reader()
        PtDataSignal(self.PTNAME).fetch(self.SHOT)
        r2 = PtDataReaderRegistry().reader()
        self.assertIs(r1, r2)

    def test_cleanup_releases_reader(self):
        sig = PtDataSignal(self.PTNAME)
        sig.fetch(self.SHOT)
        self.assertIsNotNone(PtDataReaderRegistry()._reader)
        sig.cleanup()
        self.assertIsNone(PtDataReaderRegistry()._reader)


class TestPtDataSignalPicklable(unittest.TestCase):
    """The design keeps the (unpicklable) reader off the Signal so Signals can
    be shipped to multiprocessing/Ray workers. This runs without shot files."""

    def test_signal_is_picklable_and_holds_no_reader(self):
        sig = PtDataSignal("ip", ical=4, fetch_times=False)
        self.assertFalse(hasattr(sig, "_reader"))
        restored = pickle.loads(pickle.dumps(sig))
        self.assertEqual(restored.pointname, "ip")
        self.assertEqual(restored.ical, 4)
        self.assertFalse(restored.fetch_times)
