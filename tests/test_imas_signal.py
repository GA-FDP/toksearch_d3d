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
        """magnetics.ip.data holds one entry per ip measurement.

        imas_composer 0.2.4 exposes two DIII-D ip measurements recorded on
        different time bases (a new `ip.method_name` field names them), so
        the value is a genuinely ragged object array rather than a
        rectangular (n_measurements, n_time) block.  Because the per-entry
        time arrays differ in length, `times` is itself an object array,
        which is what makes this an entity axis: no layout mode transforms
        it.
        """
        result = self._gather('magnetics.ip.data')
        data = result['data']
        self.assertIsInstance(data, np.ndarray)
        self.assertEqual(data.dtype, object)
        self.assertEqual(len(data), 2)
        for entry in data:
            self.assertGreater(np.asarray(entry).size, 0)

    def test_ip_measurements_have_distinct_lengths(self):
        """The two ip measurements are on different time bases."""
        result = self._gather('magnetics.ip.data')
        lengths = {np.asarray(e).size for e in result['data']}
        self.assertEqual(len(lengths), 2)

    def test_ip_times_in_ms(self):
        """Each ip measurement's time array is in milliseconds."""
        result = self._gather('magnetics.ip.data')
        times = result['times']
        self.assertEqual(len(times), 2)
        for entry in times:
            arr = np.asarray(entry)
            self.assertGreater(arr.size, 0)
            # DIII-D shots run for seconds; in ms the span exceeds 100.
            self.assertGreater(arr.max() - arr.min(), 100.0)

    def test_ip_data_fetch_as_xarray_times_coord(self):
        """Ragged ip data has no rectangular xarray form."""
        from toksearch_d3d import ImasSignal
        sig = ImasSignal('magnetics.ip.data', composer=self.composer)
        with self.assertRaises(NotImplementedError):
            sig.fetch_as_xarray(SHOT_MAGNETICS)

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
        """profiles_1d.electrons.density must be 2D (n_time × n_rho)."""
        result = self._gather('core_profiles.profiles_1d.electrons.density')
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
        ne = self._gather('core_profiles.profiles_1d.electrons.density')['data']
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

    def test_channel_te(self):
        """ece.channel.t_e.data must be a non-empty ndarray with ms times."""
        # ECE fetch is the slowest signal in this suite (~2.5 min each).
        # Combining the two original tests halves the CI cost.
        result = self._gather('ece.channel.t_e.data')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertGreater(result['data'].size, 0)
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
            'core_profiles.profiles_1d.electrons.density',
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
            'core_profiles.profiles_1d.electrons.density',
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


class _FakeLeafComposer:
    """Stand-in composer for unit tests of xarray conversion (no network)."""

    def __init__(self, ids_path):
        self._ids_path = ids_path

    def get_supported_fields(self, ids_path):
        return [self._ids_path]


class TestImasSignalFetchAsXarrayChannelDims(unittest.TestCase):
    """fetch_as_xarray must attach a times coordinate to channel-indexed data.

    Channel-indexed leaves (e.g. magnetics.ip.data) gather as data (n_chan, N)
    with times also (n_chan, N). When the per-channel timebases are identical,
    the DataArray must get a real 'times' coordinate; a singleton channel axis
    must be squeezed so the result behaves like a plain 1-D signal.
    """

    def _signal_with_gather(self, result):
        from toksearch_d3d import ImasSignal
        sig = ImasSignal('fake.path', composer=_FakeLeafComposer('fake.path'))
        sig.gather = lambda shot: result
        return sig

    def test_single_channel_2d_squeezed_with_times_coord(self):
        """(1, N) data + (1, N) times -> 1-D DataArray with times coordinate."""
        times = np.arange(5, dtype=float)
        data = np.arange(5, dtype=float)[np.newaxis, :] * 2.0
        sig = self._signal_with_gather({'data': data, 'times': times[np.newaxis, :]})
        da = sig.fetch_as_xarray(0)
        self.assertEqual(da.dims, ('times',))
        np.testing.assert_array_equal(da['times'].values, times)
        np.testing.assert_array_equal(da.values, data[0])

    def test_multichannel_identical_times_get_times_coord(self):
        """(3, N) data with identical per-channel times keeps the channel axis
        but labels the time axis with a times coordinate."""
        times = np.arange(4, dtype=float)
        data = np.arange(12, dtype=float).reshape(3, 4)
        times_2d = np.tile(times, (3, 1))
        sig = self._signal_with_gather({'data': data, 'times': times_2d})
        da = sig.fetch_as_xarray(0)
        self.assertEqual(da.shape, (3, 4))
        self.assertIn('times', da.dims)
        np.testing.assert_array_equal(da['times'].values, times)

    def test_multichannel_ragged_times_left_unlabeled(self):
        """Differing per-channel timebases cannot be a shared coordinate;
        generic dim labels and no times coordinate (existing behavior)."""
        data = np.arange(8, dtype=float).reshape(2, 4)
        times_2d = np.stack([np.arange(4.0), np.arange(4.0) + 0.5])
        sig = self._signal_with_gather({'data': data, 'times': times_2d})
        da = sig.fetch_as_xarray(0)
        self.assertEqual(da.shape, (2, 4))
        self.assertNotIn('times', da.coords)

    def test_plain_1d_signal_unchanged(self):
        """(N,) data + (N,) times keeps existing behavior (regression guard)."""
        times = np.arange(6, dtype=float)
        sig = self._signal_with_gather({'data': times * 3.0, 'times': times})
        da = sig.fetch_as_xarray(0)
        self.assertEqual(da.dims, ('times',))
        np.testing.assert_array_equal(da['times'].values, times)


class TestImasSignalLayoutKwarg(unittest.TestCase):
    """Constructor-level layout handling. No data access required."""

    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    LEAF = 'core_profiles.profiles_1d.electrons.density'
    PREFIX = 'core_profiles.profiles_1d'

    def test_leaf_defaults_to_compact(self):
        sig = self.ImasSignal(self.LEAF, composer=self.composer)
        self.assertEqual(sig.layout, 'compact')

    def test_prefix_defaults_to_filled(self):
        sig = self.ImasSignal(self.PREFIX, composer=self.composer)
        self.assertEqual(sig.layout, 'filled')

    def test_explicit_layout_is_honored(self):
        sig = self.ImasSignal(self.LEAF, composer=self.composer,
                              layout='ragged')
        self.assertEqual(sig.layout, 'ragged')

    def test_unknown_layout_raises(self):
        with self.assertRaises(ValueError):
            self.ImasSignal(self.LEAF, composer=self.composer,
                            layout='compacted')

    def test_compact_on_prefix_raises(self):
        with self.assertRaises(ValueError) as cm:
            self.ImasSignal(self.PREFIX, composer=self.composer,
                            layout='compact')
        message = str(cm.exception)
        self.assertIn('compact', message)
        self.assertIn('filled', message)
        self.assertIn(self.PREFIX, message)

    def test_filled_on_prefix_is_allowed(self):
        sig = self.ImasSignal(self.PREFIX, composer=self.composer,
                              layout='filled')
        self.assertEqual(sig.layout, 'filled')

    def test_as_awkward_true_warns_and_maps(self):
        with self.assertWarns(DeprecationWarning):
            sig = self.ImasSignal(self.LEAF, composer=self.composer,
                                  as_awkward=True)
        self.assertEqual(sig.layout, 'awkward')

    def test_as_awkward_false_warns_and_uses_default(self):
        with self.assertWarns(DeprecationWarning):
            sig = self.ImasSignal(self.LEAF, composer=self.composer,
                                  as_awkward=False)
        self.assertEqual(sig.layout, 'compact')

    def test_passing_both_raises(self):
        with self.assertRaises(ValueError):
            self.ImasSignal(self.LEAF, composer=self.composer,
                            as_awkward=True, layout='ragged')


class TestImasSignalRenamedField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def test_old_electron_path_reports_the_rename(self):
        old = 'core_profiles.profiles_1d.electrons.density_thermal'
        with self.assertRaises(ValueError) as cm:
            self.ImasSignal(old, composer=self.composer)
        message = str(cm.exception)
        self.assertIn('core_profiles.profiles_1d.electrons.density', message)
        self.assertIn('0.2.4', message)
        self.assertIn('ion', message.lower())

    def test_unrelated_bad_path_keeps_the_generic_error(self):
        with self.assertRaises(ValueError) as cm:
            self.ImasSignal('core_profiles.not_a_real_field',
                            composer=self.composer)
        self.assertIn('No supported fields found', str(cm.exception))

    def test_ion_density_thermal_still_resolves(self):
        # 0.2.4 kept density_thermal for ions; only electrons were renamed.
        sig = self.ImasSignal('core_profiles.profiles_1d.ion.density_thermal',
                              composer=self.composer)
        self.assertIsNotNone(sig)


class TestImasSignalLayoutIntegration(unittest.TestCase):
    """Layout behaviour against real composed data."""

    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    NE = 'core_profiles.profiles_1d.electrons.density'

    def _gather(self, path, **kwargs):
        return self.ImasSignal(path, composer=self.composer,
                               **kwargs).gather(SHOT)

    def test_compact_is_rectangular(self):
        result = self._gather(self.NE, layout='compact')
        data = result['data']
        self.assertEqual(data.ndim, 2)
        self.assertNotEqual(data.dtype, object)

    def test_compact_times_match_data_rows(self):
        result = self._gather(self.NE, layout='compact')
        self.assertEqual(len(result['times']), result['data'].shape[0])

    def test_compact_has_no_nan_rows(self):
        result = self._gather(self.NE, layout='compact')
        self.assertFalse(np.all(np.isnan(result['data']), axis=1).any())

    def test_filled_keeps_every_slot(self):
        compact = self._gather(self.NE, layout='compact')
        filled = self._gather(self.NE, layout='filled')
        self.assertEqual(filled['data'].ndim, 2)
        self.assertGreater(filled['data'].shape[0], compact['data'].shape[0])
        self.assertEqual(len(filled['times']), filled['data'].shape[0])

    def test_filled_gaps_are_nan(self):
        filled = self._gather(self.NE, layout='filled')
        self.assertTrue(np.all(np.isnan(filled['data']), axis=1).any())

    def test_filled_real_rows_equal_compact_rows(self):
        compact = self._gather(self.NE, layout='compact')
        filled = self._gather(self.NE, layout='filled')
        real = ~np.all(np.isnan(filled['data']), axis=1)
        np.testing.assert_allclose(filled['data'][real], compact['data'])

    def test_ragged_is_an_object_array(self):
        result = self._gather(self.NE, layout='ragged')
        self.assertEqual(result['data'].dtype, object)

    def test_default_matches_compact(self):
        default = self._gather(self.NE)
        compact = self._gather(self.NE, layout='compact')
        np.testing.assert_array_equal(default['data'], compact['data'])

    def test_entity_axis_unaffected_by_layout(self):
        # magnetics.ip has object times, so every layout is a no-op.
        compact = self._gather('magnetics.ip.data', layout='compact')
        ragged = self._gather('magnetics.ip.data', layout='ragged')
        self.assertEqual(len(compact['data']), len(ragged['data']))


class TestImasSignalEntityHint(unittest.TestCase):
    """Direct coverage of `_entity_hint`'s judgment on real composed data.

    All other entity_hint tests (test_imas_layout.py) pass synthetic bools
    into is_time_axis/apply_layout; nothing exercises the method that
    actually computes the hint. `core_profiles...ion.label` composes to
    (n_time, 2) -- one row of species labels per *time slice*, not one name
    per entity -- and its length equals the outer length of every
    time-indexed `ion.*` sibling, which used to produce a false positive.
    """

    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def _entity_hint(self, ids_path, shot):
        """Reproduce gather()'s resolve/compose cycle, then call `_entity_hint`.

        `_entity_hint` needs the same populated `raw_data` that `gather()`
        builds internally as a local variable, so it cannot be called in
        isolation without first running the same resolve/fetch loop.
        """
        from toksearch_d3d.signal.imas_layout import outer_length
        sig = self.ImasSignal(ids_path, composer=self.composer)
        raw_data = {}
        for _ in range(sig._max_iter):
            status, requirements = sig._composer.resolve(
                [ids_path], shot, raw_data)
            if status[ids_path]:
                break
            for req in requirements:
                raw_data[req.as_key()] = sig._fetch_requirement(req)
        composed = sig._composer.compose([ids_path], shot, raw_data)[ids_path]
        return sig._entity_hint(ids_path, shot, raw_data, outer_length(composed))

    def test_ion_temperature_is_a_time_axis(self):
        # (n_time,) object array; the sibling ion.label array is (n_time, 2)
        # -- 2-D, not one name per entity -- so it must NOT set the hint.
        self.assertFalse(self._entity_hint(
            'core_profiles.profiles_1d.ion.temperature', SHOT_MAGNETICS))

    def test_ece_channel_te_is_an_entity_axis(self):
        # ece.channel.name is (48,), matching the 48-channel outer length.
        self.assertTrue(self._entity_hint('ece.channel.t_e.data', SHOT_MAGNETICS))

    def test_magnetics_ip_is_an_entity_axis(self):
        # magnetics.ip.method_name is (2,), matching the 2-measurement outer
        # length.
        self.assertTrue(self._entity_hint('magnetics.ip.data', SHOT_MAGNETICS))

    def test_nbi_unit_power_launched_is_an_entity_axis(self):
        # nbi.unit.name is (8,), matching the 8-unit outer length.
        self.assertTrue(self._entity_hint('nbi.unit.power_launched.data', SHOT))


class TestImasSignalPrefixLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    PREFIX = 'core_profiles.profiles_1d'

    def test_prefix_leaves_share_one_outer_length(self):
        result = self.ImasSignal(self.PREFIX,
                                 composer=self.composer).gather(SHOT)
        outer = {
            np.asarray(v).shape[0]
            for v in result.values()
            if np.asarray(v).ndim >= 1
        }
        self.assertEqual(len(outer), 1)

    def test_prefix_returns_bare_arrays(self):
        result = self.ImasSignal(self.PREFIX,
                                 composer=self.composer).gather(SHOT)
        for value in result.values():
            self.assertIsInstance(value, np.ndarray)


class TestImasSignalXarrayRaggedMessage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from toksearch_d3d import ImasSignal
        from imas_composer import ImasComposer
        cls.ImasSignal = ImasSignal
        cls.composer = ImasComposer()

    def test_ragged_layout_error_suggests_a_working_layout(self):
        sig = self.ImasSignal('core_profiles.profiles_1d.electrons.density',
                              composer=self.composer, layout='ragged')
        with self.assertRaises(NotImplementedError) as cm:
            sig.fetch_as_xarray(SHOT)
        message = str(cm.exception)
        self.assertIn("layout='filled'", message)
        self.assertIn("layout='compact'", message)
