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
Tests for ImasSignal.

Requires imas_composer to be installed and the FDP environment to be active
(default_tree_path, BEARER_TOKEN, PTDATA_LOC, etc. set by `fdp run`).
"""

import unittest
import numpy as np

SHOT = 202161


class TestImasSignalImport(unittest.TestCase):
    def test_import(self):
        """toksearch_d3d should import cleanly; ImasSignal present when imas_composer installed."""
        import toksearch_d3d  # must not raise regardless of imas_composer presence
        from toksearch_d3d import ImasSignal

    def test_imasbatchsignal_removed(self):
        """ImasBatchSignal should no longer be exported."""
        import toksearch_d3d
        self.assertFalse(hasattr(toksearch_d3d, 'ImasBatchSignal'))


class TestImasSignal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def _gather(self, ids_path):
        sig = self.ImasSignal(ids_path, composer=self.composer)
        return sig.gather(SHOT)

    # --- type checks ---

    def test_gather_returns_ndarray(self):
        """gather() 'data' must be a numpy ndarray."""
        result = self._gather('equilibrium.time_slice.global_quantities.ip')
        self.assertIsInstance(result['data'], np.ndarray)

    def test_equilibrium_times_ndarray(self):
        """gather() 'times' must be a numpy ndarray when present."""
        result = self._gather('equilibrium.time_slice.global_quantities.ip')
        self.assertIn('times', result)
        self.assertIsInstance(result['times'], np.ndarray)

    # --- shape checks ---

    def test_equilibrium_ip_1d(self):
        """Plasma current Ip must be a non-empty 1D time-series."""
        result = self._gather('equilibrium.time_slice.global_quantities.ip')
        self.assertEqual(result['data'].ndim, 1)
        self.assertGreater(len(result['data']), 0)

    def test_equilibrium_times_aligned_with_ip(self):
        """'times' length must match 'data' length for Ip."""
        result = self._gather('equilibrium.time_slice.global_quantities.ip')
        self.assertEqual(len(result['times']), len(result['data']))

    def test_equilibrium_q95_1d(self):
        """q95 must be a non-empty 1D array."""
        result = self._gather('equilibrium.time_slice.global_quantities.q_95')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 1)
        self.assertGreater(len(result['data']), 0)

    def test_equilibrium_profile_2d(self):
        """profiles_1d.psi must be 2D (n_time × n_rho)."""
        result = self._gather('equilibrium.time_slice.profiles_1d.psi')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 2)
        n_time, n_rho = result['data'].shape
        self.assertGreater(n_time, 0)
        self.assertGreater(n_rho, 0)

    def test_equilibrium_time_itself(self):
        """equilibrium.time must be a 1D ndarray."""
        result = self._gather('equilibrium.time')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 1)
        self.assertGreater(len(result['data']), 0)

    # --- pipeline integration ---

    def test_pipeline_two_signals(self):
        """Two ImasSignal objects sharing one ImasComposer succeed in a Pipeline."""
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
        self.assertIsInstance(records[0]['ip']['data'], np.ndarray)
        self.assertIsInstance(records[0]['q95']['data'], np.ndarray)
