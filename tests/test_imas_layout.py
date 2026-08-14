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
    apply_layout,
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

    def test_string_times_is_not_time_axis(self):
        # A channel-name array passed where 'times' was expected: matches in
        # length but is not numeric, so must not be treated as a time axis.
        value = holey(n_slots=3, n_rho=2, empty_at=())
        names = np.array(['tecef01', 'tecef02', 'tecef03'])
        self.assertFalse(is_time_axis(value, names, None))

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

    def test_as_object_array_preserves_order(self):
        # Every other fixture here is palindromic under reversal, so a
        # mutant that reverses insertion order would go undetected. This is
        # the same order entity values are later matched positionally
        # against channel-name arrays, so it must be pinned explicitly.
        rows = [np.array([1.0]), np.array([2.0, 3.0]), np.array([4.0, 5.0, 6.0])]
        result = _as_object_array(rows)
        for i, row in enumerate(rows):
            np.testing.assert_array_equal(result[i], row)

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


class TestCompact(unittest.TestCase):
    def test_holes_become_rectangular(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'compact')
        self.assertEqual(data.shape, (3, 3))
        self.assertNotEqual(data.dtype, object)

    def test_times_filtered_in_lockstep(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'compact')
        np.testing.assert_array_equal(out_dims['times'], [0.0, 2.0, 4.0])
        self.assertEqual(len(out_dims['times']), data.shape[0])

    def test_surviving_rows_keep_their_values(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, _ = apply_layout(value, dims, 'compact')
        # rows 0, 2, 4 were arange(3) + i
        np.testing.assert_array_equal(data[0], [0.0, 1.0, 2.0])
        np.testing.assert_array_equal(data[1], [2.0, 3.0, 4.0])
        np.testing.assert_array_equal(data[2], [4.0, 5.0, 6.0])

    def test_truly_ragged_stays_object_after_compaction(self):
        value = truly_ragged()
        dims = {'times': np.arange(2, dtype=np.float64)}
        data, _ = apply_layout(value, dims, 'compact')
        self.assertEqual(data.dtype, object)
        self.assertEqual(len(data), 2)

    def test_all_slots_empty_yields_length_zero(self):
        value = holey(n_slots=3, empty_at=(0, 1, 2))
        dims = {'times': np.arange(3, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'compact')
        self.assertEqual(len(data), 0)
        self.assertEqual(len(out_dims['times']), 0)

    def test_no_empty_slots_is_a_no_op(self):
        value = holey(n_slots=4, n_rho=2, empty_at=())
        dims = {'times': np.arange(4, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'compact')
        self.assertEqual(data.shape, (4, 2))
        np.testing.assert_array_equal(out_dims['times'], np.arange(4.0))

    def test_entity_axis_untouched(self):
        # object times => measurement axis => no compaction even with a hole.
        # value is an ak.Array (as real composed data would be) so that a
        # mutant skipping the to_numpy() conversion is actually caught: with
        # a plain ndarray fixture, "return value, dims" and "return
        # to_numpy(value), dims" are indistinguishable.
        value = ak.Array([[], [1.0, 2.0, 3.0, 4.0]])
        times = np.empty(2, dtype=object)
        times[0] = np.array([], dtype=np.float64)
        times[1] = np.arange(4, dtype=np.float64)
        data, out_dims = apply_layout(value, {'times': times}, 'compact')
        self.assertEqual(len(data), 2)
        self.assertEqual(len(out_dims['times']), 2)
        # A raw ak.Array lacks .dtype, which fetch_as_xarray relies on.
        self.assertIsInstance(data, np.ndarray)

    def test_apply_layout_forwards_entity_hint(self):
        # An otherwise time-like axis (flat numeric times, matching length)
        # must still be left untouched when entity_hint=True is passed
        # through apply_layout, not just through is_time_axis directly.
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'compact', entity_hint=True)
        self.assertEqual(len(data), 5)
        self.assertEqual(len(out_dims['times']), 5)

    def test_apply_layout_forwards_split_by(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'compact', split_by='channel')
        self.assertEqual(len(data), 5)
        self.assertEqual(len(out_dims['times']), 5)

    def test_non_parallel_dims_are_not_filtered(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64),
                'rho': np.arange(3, dtype=np.float64)}
        _, out_dims = apply_layout(value, dims, 'compact')
        self.assertEqual(len(out_dims['times']), 3)
        self.assertEqual(len(out_dims['rho']), 3)  # length 3 != outer 5
        np.testing.assert_array_equal(out_dims['rho'], [0.0, 1.0, 2.0])

    def test_inner_dim_coincidentally_matching_outer_length_is_not_filtered(self):
        # n_rho happens to equal n_slots (e.g. DIII-D's n_rho=101 EFIT grid
        # coinciding with a 101-slice GTIME axis). A dim must never be
        # filtered just because len(dim) == outer -- only 'times' is known
        # to be outer-parallel.
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64),
                'rho': np.arange(5, dtype=np.float64)}
        _, out_dims = apply_layout(value, dims, 'compact')
        self.assertEqual(len(out_dims['times']), 3)
        self.assertEqual(len(out_dims['rho']), 5)
        np.testing.assert_array_equal(out_dims['rho'], np.arange(5.0))

    def test_three_level_jagged_compacts(self):
        # time x species x rho: _rows must recurse via to_numpy rather than
        # calling np.asarray directly, or this raises inside awkward.
        jag = ak.Array([[[1.0, 2.0], [3.0]], [], [[5.0, 6.0], [7.0, 8.0]]])
        dims = {'times': np.arange(3.0)}
        data, out_dims = apply_layout(jag, dims, 'compact')
        self.assertEqual(len(data), 2)
        np.testing.assert_array_equal(out_dims['times'], [0.0, 2.0])
        np.testing.assert_array_equal(data[1], [[5.0, 6.0], [7.0, 8.0]])


class TestFilled(unittest.TestCase):
    def test_holes_become_rectangular_at_full_length(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'filled')
        self.assertEqual(data.shape, (5, 3))
        self.assertEqual(len(out_dims['times']), 5)

    def test_gaps_are_nan(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, _ = apply_layout(value, dims, 'filled')
        self.assertTrue(np.all(np.isnan(data[1])))
        self.assertTrue(np.all(np.isnan(data[3])))

    def test_real_rows_are_not_nan(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, _ = apply_layout(value, dims, 'filled')
        for i in (0, 2, 4):
            self.assertFalse(np.any(np.isnan(data[i])))
        np.testing.assert_array_equal(data[0], [0.0, 1.0, 2.0])

    def test_times_not_filtered(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        _, out_dims = apply_layout(value, dims, 'filled')
        np.testing.assert_array_equal(out_dims['times'], np.arange(5.0))

    def test_no_empty_slots_agrees_with_compact(self):
        value = holey(n_slots=4, n_rho=2, empty_at=())
        dims = {'times': np.arange(4, dtype=np.float64)}
        filled, filled_dims = apply_layout(value, dict(dims), 'filled')
        compact, compact_dims = apply_layout(value, dict(dims), 'compact')
        np.testing.assert_array_equal(filled, compact)
        np.testing.assert_array_equal(filled_dims['times'],
                                      compact_dims['times'])

    def test_multiple_real_lengths_raises(self):
        # A hole is required here: with no empty slots at all, 'filled' takes
        # the no-op path (see test_no_empty_slots_agrees_with_compact) and
        # this same shape mismatch would *not* raise.
        value = np.empty(3, dtype=object)
        value[0] = np.arange(4, dtype=np.float64)
        value[1] = np.array([], dtype=np.float64)
        value[2] = np.arange(7, dtype=np.float64)
        dims = {'times': np.arange(3, dtype=np.float64)}
        with self.assertRaises(ValueError) as cm:
            apply_layout(value, dims, 'filled')
        message = str(cm.exception)
        self.assertIn('filled', message)
        self.assertIn('4', message)
        self.assertIn('7', message)

    def test_non_float_raises(self):
        value = np.empty(3, dtype=object)
        value[0] = np.array([1, 2], dtype=np.int64)
        value[1] = np.array([], dtype=np.int64)
        value[2] = np.array([3, 4], dtype=np.int64)
        dims = {'times': np.arange(3, dtype=np.float64)}
        with self.assertRaises(ValueError) as cm:
            apply_layout(value, dims, 'filled')
        # Not just "int" -- numpy's own errors would also satisfy that.
        self.assertIn("layout='filled'", str(cm.exception))

    def test_all_slots_empty_yields_length_zero_rows(self):
        value = holey(n_slots=3, empty_at=(0, 1, 2))
        dims = {'times': np.arange(3, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'filled')
        self.assertEqual(data.shape, (3, 0))
        self.assertEqual(len(out_dims['times']), 3)

    def test_no_empty_slots_int_is_a_no_op_matching_compact(self):
        # Hole-free non-float data must succeed under 'filled' since nothing
        # would ever need to be fabricated -- only *holey* non-float data is
        # a real error (see test_non_float_raises).
        value = np.empty(3, dtype=object)
        value[0] = np.array([1, 2], dtype=np.int64)
        value[1] = np.array([3, 4], dtype=np.int64)
        value[2] = np.array([5, 6], dtype=np.int64)
        dims = {'times': np.arange(3, dtype=np.float64)}
        filled, _ = apply_layout(value, dict(dims), 'filled')
        compact, _ = apply_layout(value, dict(dims), 'compact')
        np.testing.assert_array_equal(filled, compact)
        self.assertEqual(filled.dtype, np.int64)

    def test_no_empty_slots_string_is_a_no_op_matching_compact(self):
        # Real case: core_profiles.profiles_1d.ion.label -- prefix mode
        # defaults to 'filled' and applies it to every leaf, including this
        # string field.
        value = np.empty(3, dtype=object)
        value[0] = np.array(['H', 'D'])
        value[1] = np.array(['H', 'D'])
        value[2] = np.array(['H', 'D'])
        dims = {'times': np.arange(3, dtype=np.float64)}
        filled, _ = apply_layout(value, dict(dims), 'filled')
        compact, _ = apply_layout(value, dict(dims), 'compact')
        np.testing.assert_array_equal(filled, compact)

    def test_filled_preserves_float32_dtype(self):
        # Real composed data is float32; silently upcasting to float64 would
        # be a 2x memory regression.
        value = np.empty(3, dtype=object)
        value[0] = np.array([1.0, 2.0], dtype=np.float32)
        value[1] = np.array([], dtype=np.float32)
        value[2] = np.array([3.0, 4.0], dtype=np.float32)
        dims = {'times': np.arange(3, dtype=np.float64)}
        data, _ = apply_layout(value, dims, 'filled')
        self.assertEqual(data.dtype, np.float32)

    def test_shape_mismatch_message_shows_full_shapes(self):
        # Shapes (3, 4) and (3, 5) share axis-0 length 3; printing only
        # shape[0] (the pre-fix behavior) would misleadingly show "3, 3".
        value = np.empty(3, dtype=object)
        value[0] = np.zeros((3, 4))
        value[1] = np.array([], dtype=np.float64)
        value[2] = np.zeros((3, 5))
        dims = {'times': np.arange(3, dtype=np.float64)}
        with self.assertRaises(ValueError) as cm:
            apply_layout(value, dims, 'filled')
        message = str(cm.exception)
        self.assertIn('(3, 4)', message)
        self.assertIn('(3, 5)', message)

    def test_zero_dim_row_does_not_raise_indexerror(self):
        # A 0-d row has an empty shape tuple; indexing shape[0] (the pre-fix
        # behavior) raised IndexError instead of the intended ValueError.
        value = np.empty(3, dtype=object)
        value[0] = np.array(5.0)
        value[1] = np.array([], dtype=np.float64)
        value[2] = np.array([1.0, 2.0])
        dims = {'times': np.arange(3, dtype=np.float64)}
        with self.assertRaises(ValueError) as cm:
            apply_layout(value, dims, 'filled')
        self.assertIn('()', str(cm.exception))

    def test_three_level_jagged_raises_informative_error(self):
        # time x species x rho with a hole: the non-empty slots have
        # different inner (species, rho) shapes, so there is no common shape
        # to pad to. Must raise the intended ValueError, not an opaque
        # awkward internals error (which is what a non-recursing _rows gives).
        jag = ak.Array([[[1.0, 2.0], [3.0]], [], [[5.0, 6.0], [7.0, 8.0]]])
        dims = {'times': np.arange(3.0)}
        with self.assertRaises(ValueError) as cm:
            apply_layout(jag, dims, 'filled')
        self.assertIn("layout='filled'", str(cm.exception))


class TestRaggedAndAwkward(unittest.TestCase):
    def test_ragged_preserves_empty_slots(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'ragged')
        self.assertEqual(len(data), 5)
        self.assertEqual(data[1].size, 0)
        self.assertEqual(data[3].size, 0)
        self.assertEqual(len(out_dims['times']), 5)

    def test_awkward_returns_value_untouched(self):
        # value must be an ak.Array: the previous ndarray fixture made
        # assertIs pass unconditionally, since to_numpy(ndarray) can also
        # return the same object, so the check couldn't distinguish "value
        # was passed straight through" from "value was converted".
        value = ak.Array([[1.0, 2.0, 3.0], [], [4.0, 5.0, 6.0]])
        dims = {'times': np.arange(3, dtype=np.float64)}
        data, _ = apply_layout(value, dims, 'awkward')
        self.assertIs(data, value)
        self.assertIsInstance(data, ak.Array)

    def test_awkward_skips_the_axis_rule(self):
        # No times at all: awkward must still pass the value straight through.
        value = holey(n_slots=5)
        data, _ = apply_layout(value, {}, 'awkward')
        self.assertIs(data, value)

    def test_unknown_layout_raises_before_any_work(self):
        with self.assertRaises(ValueError):
            apply_layout(holey(), {'times': np.arange(5.0)}, 'compacted')
