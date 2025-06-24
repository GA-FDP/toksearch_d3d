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

from toksearch_d3d import CakeSignal


class TestCakeSignal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eq_ptname = r"\ipmhd"
        cls.prof_ptname = r"\OMFIT_PROFS::TOP:ZEFF"
        cls.shot =165920


    def test_fetch_eq(self):
        results = CakeSignal(self.eq_ptname, "eq").fetch(self.shot)
        self.assertGreater(len(results["data"]), 1)
        self.assertGreater(len(results["times"]), 1)


    def test_fetch_profile(self):
        results = CakeSignal(self.prof_ptname, "prof").fetch(self.shot)
        self.assertGreater(len(results["data"]), 1)
        self.assertGreater(len(results["times"]), 1)
