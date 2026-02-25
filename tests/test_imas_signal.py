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

"""
Tests for ImasSignal and ImasBatchSignal.

Unit tests (TestImasSignalImport) run without MDSplus access.
Integration tests require TOKSEARCH_INTEGRATION=yes, a valid BEARER_TOKEN,
and MDSplus access to atlas.gat.com (or equivalent).
"""

import os
import unittest


SHOT = 200000
_INTEGRATION = True


class TestImasSignalImport(unittest.TestCase):
    def test_import(self):
        """toksearch_d3d should import cleanly; ImasSignal present when imas_composer installed."""
        import toksearch_d3d  # must not raise regardless of imas_composer presence
        from toksearch_d3d import ImasSignal, ImasBatchSignal


@unittest.skipUnless(_INTEGRATION, 'Set TOKSEARCH_INTEGRATION=yes to run integration tests')
class TestImasSignal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def test_gather_returns_data(self):
        """ImasSignal.gather() returns a dict with 'data' key."""
        sig = self.ImasSignal('equilibrium.time_slice.global_quantities.ip',
                              composer=self.composer)
        result = sig.gather(SHOT)
        self.assertIn('data', result)

    def test_equilibrium_ip_shape(self):
        """Plasma current Ip should be a 1D time-series."""
        sig = self.ImasSignal('equilibrium.time_slice.global_quantities.ip',
                              composer=self.composer)
        result = sig.gather(SHOT)
        self.assertEqual(result['data'].ndim, 1)

    def test_equilibrium_profile_2d(self):
        """profiles_1d.psi should be a 2D array (n_time, n_rho)."""
        sig = self.ImasSignal('equilibrium.time_slice.profiles_1d.psi',
                              composer=self.composer)
        result = sig.gather(SHOT)
        self.assertEqual(result['data'].ndim, 2)

    def test_times_present_for_time_varying_field(self):
        """gather() should include 'times' aligned with 'data' for a time-varying field."""
        sig = self.ImasSignal('equilibrium.time_slice.global_quantities.ip',
                              composer=self.composer)
        result = sig.gather(SHOT)
        self.assertIn('times', result)
        self.assertEqual(result['times'].ndim, 1)
        self.assertEqual(len(result['times']), len(result['data']))

    def test_shared_composer_in_pipeline(self):
        """Two ImasSignal objects sharing one ImasComposer should both succeed in a Pipeline."""
        from toksearch import Pipeline
        pipeline = Pipeline([SHOT])
        pipeline.fetch('ip', self.ImasSignal(
            'equilibrium.time_slice.global_quantities.ip', composer=self.composer
        ))
        pipeline.fetch('q95', self.ImasSignal(
            'equilibrium.time_slice.global_quantities.q_95', composer=self.composer
        ))
        records = pipeline.compute_serial()
        self.assertIn('ip', records[0])
        self.assertIn('q95', records[0])


@unittest.skipUnless(_INTEGRATION, 'Set TOKSEARCH_INTEGRATION=yes to run integration tests')
class TestImasBatchSignal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasBatchSignal
        cls.ImasBatchSignal = ImasBatchSignal
        cls.paths = [
            'equilibrium.time',
            'equilibrium.time_slice.global_quantities.ip',
        ]

    def test_gather_returns_all_paths(self):
        """ImasBatchSignal.gather() returns a dict keyed by IDS path."""
        sig = self.ImasBatchSignal(self.paths)
        result = sig.gather(SHOT)
        for p in self.paths:
            self.assertIn(p, result, msg=f"Missing key: {p}")
