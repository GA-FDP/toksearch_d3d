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
import sys
import os
import tempfile
import numpy as np
import timeit

from toksearch_d3d import PtDataSignal, RDataSignal


class TestPtDataSignal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ptname = "ip"
        cls.segmented_ptname = "ice01"
        cls.shot = 165920
        cls.segmented_shot = 170000
        cls.long_ptname = "hx16current"

    def test_ptdatasource_with_times(self):
        results = PtDataSignal(self.ptname).fetch(self.shot)
        self.assertGreater(len(results["data"]), 1)
        self.assertGreater(len(results["times"]), 1)
        self.assertEquals(results["units"]["data"], "amps")
        self.assertEquals(results["units"]["times"], "ms")

    def test_ptdatasource_without_times(self):
        results = PtDataSignal(self.ptname, fetch_times=False).fetch(self.shot)
        self.assertGreater(len(results["data"]), 1)
        self.assertEquals(results["units"]["data"], "amps")
        self.assertNotIn("times", results)
        self.assertNotIn("times", results["units"])

    def test_ptdatasource_without_units(self):
        results = PtDataSignal(self.ptname, fetch_units=False).fetch(self.shot)
        self.assertNotIn("units", results)

    def test_ptdatasource_with_numpy_int64(self):
        results = PtDataSignal(self.ptname).fetch(self.shot)
        results_64 = PtDataSignal(self.ptname).fetch(np.int64(self.shot))

        np.testing.assert_allclose(results["data"], results_64["data"])
        np.testing.assert_allclose(results["times"], results_64["times"])

    def test_with_long_ptname(self):
        results = PtDataSignal(self.long_ptname).fetch(self.shot)
        results_truncated = PtDataSignal(self.long_ptname[:10]).fetch(self.shot)
        np.testing.assert_allclose(results["data"], results_truncated["data"])
        np.testing.assert_allclose(results["times"], results_truncated["times"])

    def test_keep_header(self):
        res = PtDataSignal(self.ptname, keep_header=True).fetch(self.shot)
        self.assertIn("header", res)

    # Not supported yet
    # def test_pdatasource_with_segmented_ptname(self):
    #    results = self.ds.fetch(self.segmented_shot, self.segmented_ptname)

class TestRDataSignal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ptname = "ip"
        cls.shot = 165920

    def test_rdatasignal(self):
        results = RDataSignal(self.ptname).fetch(self.shot)

        self.assertIn("data", results)
        self.assertGreater(len(results["data"]), 500)

class TestPtDataSignalTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ptname = "ip"
        cls.shot = 165920

    def test_timing(self):
        elapsed_times = []
        for i in range(5):
            sig = PtDataSignal(self.ptname)
            start_time = timeit.default_timer()
            results = sig.fetch(self.shot)
            elapsed = timeit.default_timer() - start_time
            elapsed_times.append(elapsed)

        print(elapsed_times)
