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


class TestImasSignalThomson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def _gather(self, ids_path, **kwargs):
        sig = self.ImasSignal(ids_path, composer=self.composer, **kwargs)
        return sig.gather(SHOT)

    # --- scalar / position fields (regular numpy) ---

    def test_position_r(self):
        """channel.position.r must be a non-empty 1D float array."""
        result = self._gather('thomson_scattering.channel.position.r')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 1)
        self.assertGreater(len(result['data']), 0)

    def test_position_z(self):
        """channel.position.z must have the same length as position.r."""
        r = self._gather('thomson_scattering.channel.position.r')['data']
        z = self._gather('thomson_scattering.channel.position.z')['data']
        self.assertIsInstance(z, np.ndarray)
        self.assertEqual(len(z), len(r))

    # --- ragged measurement fields (default: object array) ---

    def test_ne_data_object_array(self):
        """channel.n_e.data must be a numpy object array; each element is a 1-D float array."""
        result = self._gather('thomson_scattering.channel.n_e.data')
        data = result['data']
        self.assertIsInstance(data, np.ndarray)
        self.assertEqual(data.dtype, object)
        self.assertGreater(len(data), 0)
        for ch in data:
            self.assertIsInstance(ch, np.ndarray)
            self.assertEqual(ch.ndim, 1)

    def test_te_data_object_array(self):
        """channel.t_e.data must be a numpy object array; each element is a 1-D float array."""
        result = self._gather('thomson_scattering.channel.t_e.data')
        data = result['data']
        self.assertIsInstance(data, np.ndarray)
        self.assertEqual(data.dtype, object)
        self.assertGreater(len(data), 0)
        for ch in data:
            self.assertIsInstance(ch, np.ndarray)
            self.assertEqual(ch.ndim, 1)

    # --- split_by='channel' ---

    def test_ne_data_split_by_channel(self):
        """split_by='channel' returns full per-channel dicts with data/times/units."""
        result = self._gather(
            'thomson_scattering.channel.n_e.data',
            split_by='channel',
            dims={'times': 'auto'},
            units={'data': 'm^-3', 'times': 's'},
        )
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)
        for name, entry in result.items():
            self.assertIsInstance(name, str)
            # data
            self.assertIsInstance(entry['data'], np.ndarray)
            self.assertEqual(entry['data'].ndim, 1)
            # times
            self.assertIn('times', entry)
            self.assertIsInstance(entry['times'], np.ndarray)
            self.assertEqual(entry['times'].ndim, 1)
            self.assertEqual(len(entry['times']), len(entry['data']))
            # units
            self.assertEqual(entry['units'], {'data': 'm^-3', 'times': 's'})


class TestImasSignalRaggedEquilibrium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def _gather(self, ids_path):
        sig = self.ImasSignal(ids_path, composer=self.composer)
        return sig.gather(SHOT)

    def test_boundary_outline_r(self):
        """boundary.outline.r must be a numpy object array; each element is a 1-D float array."""
        result = self._gather('equilibrium.time_slice.boundary.outline.r')
        data = result['data']
        self.assertIsInstance(data, np.ndarray)
        self.assertEqual(data.dtype, object)
        self.assertGreater(len(data), 0)
        for ts in data:
            self.assertIsInstance(ts, np.ndarray)
            self.assertEqual(ts.ndim, 1)

    def test_boundary_outline_z(self):
        """boundary.outline.z must have the same number of time slices as r."""
        r = self._gather('equilibrium.time_slice.boundary.outline.r')['data']
        z = self._gather('equilibrium.time_slice.boundary.outline.z')['data']
        self.assertIsInstance(z, np.ndarray)
        self.assertEqual(len(z), len(r))


SHOTS = [202161, 202159, 202160]


class TestImasSignalMultiprocessing(unittest.TestCase):
    """ImasSignal fetched in a Pipeline using multiprocessing (num_workers=2)."""

    def test_multiprocessing_pipeline(self):
        """Two workers each fetch ip and q95 for multiple shots; all results are valid ndarrays."""
        from toksearch import Pipeline
        from toksearch_d3d import ImasSignal

        # Each ImasSignal creates its own ImasComposer so pickling to worker
        # processes is straightforward — no shared state across workers.
        pipeline = Pipeline(SHOTS)
        pipeline.fetch('ip', ImasSignal('equilibrium.time_slice.global_quantities.ip'))
        pipeline.fetch('q95', ImasSignal('equilibrium.time_slice.global_quantities.q_95'))
        records = pipeline.compute_multiprocessing(num_workers=2)

        self.assertEqual(len(records), len(SHOTS))
        for rec in records:
            for key in ('ip', 'q95'):
                self.assertIn(key, rec)
                self.assertIn('errors', rec)
                data = rec[key]['data']
                times = rec[key]['times']
                self.assertIsInstance(data, np.ndarray)
                self.assertIsInstance(times, np.ndarray)
                self.assertEqual(data.ndim, 1)
                self.assertGreater(len(data), 0)
                self.assertEqual(len(times), len(data))
