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

    def test_equilibrium_times_default_ms(self):
        """Default dim_scales converts IMAS seconds to milliseconds."""
        result = self._gather('equilibrium.time_slice.global_quantities.ip')
        # DIII-D shots run ~0–6000 ms; raw IMAS times are in seconds (<10).
        self.assertGreater(result['times'].max(), 100.0)

    def test_equilibrium_times_seconds_override(self):
        """dim_scales={'times': 1.0} returns raw IMAS seconds."""
        sig = self.ImasSignal(
            'equilibrium.time_slice.global_quantities.ip',
            composer=self.composer,
            dim_scales={'times': 1.0},
        )
        result = sig.gather(SHOT)
        self.assertIn('times', result)
        self.assertLess(result['times'].max(), 10.0)

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

    def test_equilibrium_beta_normal_1d(self):
        """beta_normal must be a non-empty 1D array."""
        result = self._gather('equilibrium.time_slice.global_quantities.beta_normal')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 1)
        self.assertGreater(len(result['data']), 0)

    def test_equilibrium_li_3_1d(self):
        """li_3 must be a non-empty 1D array."""
        result = self._gather('equilibrium.time_slice.global_quantities.li_3')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 1)
        self.assertGreater(len(result['data']), 0)

    def test_equilibrium_magnetic_axis_r_1d(self):
        """magnetic_axis.r must be a non-empty 1D array."""
        result = self._gather('equilibrium.time_slice.global_quantities.magnetic_axis.r')
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

    def test_equilibrium_q_profile_2d(self):
        """profiles_1d.q must be 2D (n_time × n_rho)."""
        result = self._gather('equilibrium.time_slice.profiles_1d.q')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 2)
        self.assertGreater(result['data'].shape[0], 0)
        self.assertGreater(result['data'].shape[1], 0)

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
            units={'data': 'm^-3', 'times': 'ms'},
        )
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)
        for name, entry in result.items():
            self.assertIsInstance(name, str)
            # data
            self.assertIsInstance(entry['data'], np.ndarray)
            self.assertEqual(entry['data'].ndim, 1)
            # times — default dim_scales converts to ms
            self.assertIn('times', entry)
            self.assertIsInstance(entry['times'], np.ndarray)
            self.assertEqual(entry['times'].ndim, 1)
            self.assertEqual(len(entry['times']), len(entry['data']))
            self.assertGreater(entry['times'].max(), 100.0)
            # units
            self.assertEqual(entry['units'], {'data': 'm^-3', 'times': 'ms'})


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


# Magnetics and TF ptdata is indexed for shots ~200000 but not for 202161.
SHOT_MAGNETICS = 200000


class TestImasSignalMagnetics(unittest.TestCase):
    """Magnetics IDS — fetched via ptdata (requires shot in ptdata JSON index)."""

    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def _gather(self, ids_path):
        sig = self.ImasSignal(ids_path, composer=self.composer)
        return sig.gather(SHOT_MAGNETICS)

    def test_ip_data_shape(self):
        """magnetics.ip.data is (n_measurements, n_time); DIII-D has 1 measurement."""
        result = self._gather('magnetics.ip.data')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 2)
        self.assertEqual(result['data'].shape[0], 1)
        self.assertGreater(result['data'].shape[1], 0)

    def test_ip_times_in_ms(self):
        """magnetics.ip.data times must be (n_measurements, n_time) and in ms."""
        result = self._gather('magnetics.ip.data')
        self.assertIn('times', result)
        self.assertEqual(result['times'].ndim, 2)
        self.assertGreater(result['times'].max(), 100.0)

    def test_diamagnetic_flux_shape(self):
        """magnetics.diamagnetic_flux.data is (n_measurements, n_time); DIII-D has 1."""
        result = self._gather('magnetics.diamagnetic_flux.data')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 2)
        self.assertEqual(result['data'].shape[0], 1)
        self.assertGreater(result['data'].shape[1], 0)
        self.assertIn('times', result)
        self.assertEqual(result['times'].shape, result['data'].shape)


class TestImasSignalTf(unittest.TestCase):
    """Toroidal field IDS — fetched via ptdata (requires shot in ptdata JSON index)."""

    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def _gather(self, ids_path):
        sig = self.ImasSignal(ids_path, composer=self.composer)
        return sig.gather(SHOT_MAGNETICS)

    def test_b_field_tor_vacuum_r_1d(self):
        """tf.b_field_tor_vacuum_r.data must be a non-empty 1D array with times."""
        result = self._gather('tf.b_field_tor_vacuum_r.data')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 1)
        self.assertGreater(len(result['data']), 0)
        self.assertIn('times', result)
        self.assertEqual(len(result['times']), len(result['data']))


class TestImasSignalCoreProfiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def _gather(self, ids_path):
        sig = self.ImasSignal(ids_path, composer=self.composer)
        return sig.gather(SHOT_MAGNETICS)

    def test_time_1d(self):
        """core_profiles.time must be a non-empty 1D array."""
        result = self._gather('core_profiles.time')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 1)
        self.assertGreater(len(result['data']), 0)

    def test_electron_density_2d(self):
        """profiles_1d.electrons.density_thermal must be 2D (n_time × n_rho)."""
        result = self._gather('core_profiles.profiles_1d.electrons.density_thermal')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 2)
        self.assertGreater(result['data'].shape[0], 0)
        self.assertGreater(result['data'].shape[1], 0)

    def test_electron_temperature_2d(self):
        """profiles_1d.electrons.temperature must be 2D (n_time × n_rho)."""
        result = self._gather('core_profiles.profiles_1d.electrons.temperature')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 2)
        self.assertGreater(result['data'].shape[0], 0)
        self.assertGreater(result['data'].shape[1], 0)

    def test_density_temperature_same_shape(self):
        """Electron density and temperature profiles must have the same shape."""
        ne = self._gather('core_profiles.profiles_1d.electrons.density_thermal')['data']
        te = self._gather('core_profiles.profiles_1d.electrons.temperature')['data']
        self.assertEqual(ne.shape, te.shape)


class TestImasSignalEce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def _gather(self, ids_path):
        sig = self.ImasSignal(ids_path, composer=self.composer)
        return sig.gather(SHOT_MAGNETICS)

    def test_channel_te_data(self):
        """ece.channel.t_e.data must be a non-empty ndarray."""
        result = self._gather('ece.channel.t_e.data')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertGreater(result['data'].size, 0)

    def test_channel_te_has_times(self):
        """ece.channel.t_e.data times must be present and in milliseconds."""
        result = self._gather('ece.channel.t_e.data')
        self.assertIn('times', result)
        self.assertIsInstance(result['times'], np.ndarray)
        self.assertGreater(result['times'].max(), 100.0)


class TestImasSignalXarray(unittest.TestCase):
    """fetch_as_xarray() must produce sensible xarray objects for all data shapes."""

    @classmethod
    def setUpClass(cls):
        import xarray as xr
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.xr = xr
        cls.ImasSignal = ImasSignal
        cls.composer_eq = ImasComposer()
        cls.composer_cp = ImasComposer()

    # --- scalar 1-D signals ---

    def test_scalar_1d_dataarray(self):
        """equilibrium ip must produce a 1-D DataArray with a 'times' dimension."""
        sig = self.ImasSignal(
            'equilibrium.time_slice.global_quantities.ip',
            composer=self.composer_eq,
        )
        da = sig.fetch_as_xarray(SHOT)
        self.assertIsInstance(da, self.xr.DataArray)
        self.assertEqual(da.ndim, 1)
        self.assertIn('times', da.dims)

    def test_scalar_1d_times_in_ms(self):
        """The 'times' coordinate must be in milliseconds (default dim_scales)."""
        sig = self.ImasSignal(
            'equilibrium.time_slice.global_quantities.ip',
            composer=self.composer_eq,
        )
        da = sig.fetch_as_xarray(SHOT)
        self.assertGreater(float(da.coords['times'].max()), 100.0)

    # --- 2-D profile data ---

    def test_profile_2d_dataarray(self):
        """core_profiles electron density must produce a 2-D DataArray."""
        sig = self.ImasSignal(
            'core_profiles.profiles_1d.electrons.density_thermal',
            composer=self.composer_cp,
        )
        da = sig.fetch_as_xarray(SHOT_MAGNETICS)
        self.assertIsInstance(da, self.xr.DataArray)
        self.assertEqual(da.ndim, 2)
        self.assertEqual(da.dims[0], 'times')
        self.assertEqual(da.dims[1], 'dim_1')

    def test_profile_2d_times_coord(self):
        """The 'times' coordinate of the 2-D DataArray must be present and in ms."""
        sig = self.ImasSignal(
            'core_profiles.profiles_1d.electrons.density_thermal',
            composer=self.composer_cp,
        )
        da = sig.fetch_as_xarray(SHOT_MAGNETICS)
        self.assertIn('times', da.coords)
        self.assertGreater(float(da.coords['times'].max()), 100.0)

    # --- ragged object arrays must raise ---

    def test_ragged_raises_not_implemented(self):
        """fetch_as_xarray() must raise NotImplementedError for ragged data."""
        sig = self.ImasSignal(
            'thomson_scattering.channel.n_e.data',
            composer=self.composer_eq,
        )
        with self.assertRaises(NotImplementedError):
            sig.fetch_as_xarray(SHOT)

    # --- channel-split → xr.Dataset ---

    def test_channel_split_returns_dataset(self):
        """split_by='channel' must return a non-empty xr.Dataset."""
        sig = self.ImasSignal(
            'thomson_scattering.channel.n_e.data',
            split_by='channel',
            dims={'times': 'auto'},
            composer=self.composer_eq,
        )
        ds = sig.fetch_as_xarray(SHOT)
        self.assertIsInstance(ds, self.xr.Dataset)
        self.assertGreater(len(ds.data_vars), 0)

    def test_channel_split_dataset_has_units_attrs(self):
        """Each DataArray in the Dataset must carry a 'units' attribute."""
        sig = self.ImasSignal(
            'thomson_scattering.channel.n_e.data',
            split_by='channel',
            dims={'times': 'auto'},
            units={'data': 'm^-3', 'times': 'ms'},
            composer=self.composer_eq,
        )
        ds = sig.fetch_as_xarray(SHOT)
        for var in ds.data_vars.values():
            self.assertEqual(var.attrs.get('units'), 'm^-3')

    def test_channel_split_scalar_dims_as_attrs(self):
        """Scalar dims (r, z) must appear as float attributes on each DataArray."""
        sig = self.ImasSignal(
            'thomson_scattering.channel.n_e.data',
            split_by='channel',
            dims={
                'times': 'auto',
                'r': 'thomson_scattering.channel.position.r',
                'z': 'thomson_scattering.channel.position.z',
            },
            composer=self.composer_eq,
        )
        ds = sig.fetch_as_xarray(SHOT)
        for var in ds.data_vars.values():
            self.assertIn('r', var.attrs)
            self.assertIn('z', var.attrs)
            self.assertIsInstance(var.attrs['r'], float)
            self.assertIsInstance(var.attrs['z'], float)


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


class TestImasSignalAsAwkward(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def test_default_returns_numpy(self):
        """Default (as_awkward=False) returns numpy object array for ragged field."""
        sig = self.ImasSignal(
            'equilibrium.time_slice.boundary.outline.r',
            composer=self.composer
        )
        result = sig.gather(SHOT)
        self.assertIsInstance(result['data'], np.ndarray)

    def test_as_awkward_returns_awkward(self):
        """as_awkward=True returns ak.Array for ragged field."""
        import awkward as ak
        sig = self.ImasSignal(
            'equilibrium.time_slice.boundary.outline.r',
            composer=self.composer,
            as_awkward=True
        )
        result = sig.gather(SHOT)
        self.assertIsInstance(result['data'], ak.Array)

    def test_prefix_default_returns_numpy(self):
        """Prefix fetch default returns numpy arrays."""
        sig = self.ImasSignal(
            'equilibrium.time_slice.global_quantities',
            composer=self.composer
        )
        result = sig.gather(SHOT)
        for val in result.values():
            self.assertIsInstance(val, np.ndarray)

    def test_prefix_as_awkward(self):
        """Prefix fetch with as_awkward=True returns ak.Array or np.ndarray values."""
        import awkward as ak
        sig = self.ImasSignal(
            'equilibrium.time_slice.global_quantities',
            composer=self.composer,
            as_awkward=True
        )
        result = sig.gather(SHOT)
        for val in result.values():
            self.assertIsInstance(val, (ak.Array, np.ndarray))
