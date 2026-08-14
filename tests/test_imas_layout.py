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

from toksearch_d3d.signal.imas_layout import (
    LAYOUTS,
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
