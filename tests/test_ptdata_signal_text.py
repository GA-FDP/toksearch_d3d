# Copyright 2026 General Atomics
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

"""ASCII-type PTDATA points (PCS phase logs PHASESTKn/SEQSTKn) come back as text.

The offline tests use a stub reader. The live test needs the FDP environment
(`fdp run`) or on-site ptserver access, and skips otherwise.
"""

import unittest

import ptdata
from ptdata import _core

from toksearch_d3d.signal.ptdata import PtDataSignal, PtDataReaderRegistry

PHASE_TEXT = (
    "catid     phasename   algid              absolute time  relative time  \n"
    "shape     ShotStart   isosnull               -9.000000       0.000000  \n"
)


class _TextResult:
    data = []
    raw_integer = []
    times = []
    text = PHASE_TEXT
    units = "none"
    n_over = 0
    n_under = 0


class _TextReader:
    def fetch(self, pointname, shot, params, source='', version=None, snapshot=None):
        return _TextResult()


class TestTextPassthrough(unittest.TestCase):
    def setUp(self):
        PtDataReaderRegistry()._reader = _TextReader()

    def tearDown(self):
        PtDataReaderRegistry().close()

    def test_text_is_the_data(self):
        res = PtDataSignal("PHASESTK1").fetch(204019)
        self.assertIsInstance(res["data"], str)
        self.assertEqual(res["data"], PHASE_TEXT)
        self.assertNotIn("times", res)
        self.assertEqual(res["units"], {"data": "none"})

    def test_text_regardless_of_ical_and_times(self):
        for kwargs in ({"ical": 0}, {"fetch_times": False}, {"fetch_units": False}):
            res = PtDataSignal("PHASESTK1", **kwargs).fetch(204019)
            self.assertEqual(res["data"], PHASE_TEXT)
            self.assertNotIn("times", res)


class TestPhaseStkLive(unittest.TestCase):
    SHOT = 204019

    def setUp(self):
        PtDataReaderRegistry().close()

    def _fetch(self, pointname):
        try:
            return PtDataSignal(pointname).fetch(self.SHOT)
        except (ptdata.PtDataError, _core.PtDataError) as e:
            if e.code == 53:  # InvalidDataType: the decoder refused it
                raise
            self.skipTest(f"PTDATA for {self.SHOT} unreachable here: {e}")

    def test_phasestk1(self):
        res = self._fetch("PHASESTK1")
        self.assertIsInstance(res["data"], str)
        self.assertTrue(res["data"].startswith("catid     phasename"))
        self.assertIn("ShotStart", res["data"])
        self.assertNotIn("times", res)

    def test_seqstk1(self):
        res = self._fetch("SEQSTK1")
        self.assertIsInstance(res["data"], str)
        self.assertTrue(res["data"])


if __name__ == "__main__":
    unittest.main()
