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

"""Offline unit tests for toksearch_d3d.signal.imas_layout.

These tests use synthetic ragged inputs and require no shot data, no
Pelican access, and no `fdp run` wrapper.
"""

import unittest
import numpy as np
import awkward as ak

from toksearch_d3d.signal.imas_layout import (
    LAYOUTS,
    _as_object_array,
    is_time_axis,
    to_numpy,
    validate_layout,
)


def holey(n_slots=5, n_rho=3, empty_at=(1, 3)):
    """Object array of n_slots rows; rows in empty_at are length-0."""
    out = np.empty(n_slots, dtype=object)
    for i in range(n_slots):
        out[i] = (np.array([], dtype=np.float64) if i in empty_at
                  else np.arange(n_rho, dtype=np.float64) + i)
    return out


def truly_ragged():
    """Object array whose non-empty rows have different lengths."""
    out = np.empty(2, dtype=object)
    out[0] = np.arange(4, dtype=np.float64)
    out[1] = np.arange(7, dtype=np.float64)
    return out


class TestValidateLayout(unittest.TestCase):
    def test_all_documented_layouts_accepted(self):
        for name in LAYOUTS:
            validate_layout(name)  # must not raise

    def test_unknown_layout_raises(self):
        with self.assertRaises(ValueError) as cm:
            validate_layout('compacted')
        self.assertIn('compacted', str(cm.exception))

    def test_error_lists_valid_layouts(self):
        with self.assertRaises(ValueError) as cm:
            validate_layout('nonsense')
        for name in LAYOUTS:
            self.assertIn(name, str(cm.exception))


class TestToNumpy(unittest.TestCase):
    def test_rectangular_list_becomes_ndarray(self):
        result = to_numpy(np.zeros((4, 3)))
        self.assertEqual(result.shape, (4, 3))
        self.assertNotEqual(result.dtype, object)


class TestIsTimeAxis(unittest.TestCase):
    def test_flat_numeric_times_matching_outer_is_time_axis(self):
        value = holey(n_slots=5)
        times = np.arange(5, dtype=np.float64)
        self.assertTrue(is_time_axis(value, times, None))

    def test_object_times_is_not_time_axis(self):
        # magnetics.ip: per-measurement time arrays
        times = np.empty(2, dtype=object)
        times[0] = np.arange(10, dtype=np.float64)
        times[1] = np.arange(4, dtype=np.float64)
        self.assertFalse(is_time_axis(truly_ragged(), times, None))

    def test_two_dimensional_times_is_not_time_axis(self):
        # ECE: one time row per channel
        value = np.zeros((3, 8))
        times = np.zeros((3, 8))
        self.assertFalse(is_time_axis(value, times, None))

    def test_length_mismatch_is_not_time_axis(self):
        self.assertFalse(is_time_axis(holey(n_slots=5), np.arange(4.0), None))

    def test_split_by_channel_is_never_time_axis(self):
        value = holey(n_slots=5)
        times = np.arange(5, dtype=np.float64)
        self.assertFalse(is_time_axis(value, times, 'channel'))

    def test_missing_times_is_not_time_axis(self):
        self.assertFalse(is_time_axis(holey(n_slots=5), None, None))

    def test_zero_dim_scalar_is_not_time_axis(self):
        self.assertFalse(is_time_axis(np.array(3.0), np.arange(5.0), None))


class TestLayoutsContents(unittest.TestCase):
    def test_layouts_is_exactly_the_four_documented_modes(self):
        # Pinned explicitly: iterating LAYOUTS to test LAYOUTS asserts nothing
        # about its contents, so a dropped or typo'd mode would go unnoticed.
        self.assertEqual(set(LAYOUTS),
                         {'compact', 'filled', 'ragged', 'awkward'})


class TestToNumpyAwkward(unittest.TestCase):
    def test_jagged_becomes_one_dimensional_object_array(self):
        result = to_numpy(ak.Array([[1.0, 2.0, 3.0], [], [4.0, 5.0, 6.0]]))
        self.assertEqual(result.dtype, object)
        self.assertEqual(result.ndim, 1)
        self.assertEqual([len(r) for r in result], [3, 0, 3])

    def test_equal_length_rows_do_not_collapse_to_two_dimensions(self):
        rows = [np.arange(3.0), np.arange(3.0) + 10]
        result = _as_object_array(rows)
        self.assertEqual(result.ndim, 1)
        self.assertEqual(len(result), 2)

    def test_rectangular_awkward_becomes_two_dimensional_numeric(self):
        result = to_numpy(ak.Array([[1.0, 2.0], [3.0, 4.0]]))
        self.assertEqual(result.shape, (2, 2))
        self.assertNotEqual(result.dtype, object)

    def test_three_level_jagged_does_not_raise(self):
        # time x species x rho quantities are 3-level; the fallback's per-row
        # conversion must recurse rather than escape with a ValueError.
        value = ak.Array([[[1.0, 2.0], [3.0]], [[4.0]]])
        result = to_numpy(value)
        self.assertEqual(result.dtype, object)
        self.assertEqual(len(result), 2)


class TestIsTimeAxisEntityHint(unittest.TestCase):
    def test_entity_hint_blocks_an_otherwise_time_like_axis(self):
        # 48 per-channel rows whose times resolved to the flat IDS-level
        # array and coincidentally match in length.
        value = holey(n_slots=48, n_rho=3, empty_at=(7,))
        times = np.arange(48, dtype=np.float64)
        self.assertTrue(is_time_axis(value, times, None))
        self.assertFalse(is_time_axis(value, times, None, entity_hint=True))

    def test_entity_hint_defaults_to_false(self):
        value = holey(n_slots=5, n_rho=3)
        times = np.arange(5, dtype=np.float64)
        self.assertTrue(is_time_axis(value, times, None))

    def test_ragged_times_do_not_raise(self):
        value = truly_ragged()
        times = [np.zeros(4), np.zeros(7)]
        self.assertFalse(is_time_axis(value, times, None))
