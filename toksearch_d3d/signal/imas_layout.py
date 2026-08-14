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

"""Layout transformations for imas_composer composed values.

imas_composer 0.2.4 places every ``core_profiles.profiles_1d`` quantity on a
single unified GTIME axis, leaving an *empty* array in slots where a given
quantity has no data.  Composed values therefore arrive jagged.  This module
turns a jagged value into whichever shape the caller asked for.

Two kinds of raggedness exist and must not be conflated:

* **Holes** -- one common inner length plus empty slots.  Recoverable to a
  rectangular array (``core_profiles``).
* **Genuinely ragged** -- several distinct real lengths.  Not recoverable
  (``magnetics.ip``'s two measurements, ECE channels).

Everything here is a pure function of its arguments so the interesting cases
can be tested with synthetic inputs, without shot data.
"""

import numpy as np

try:
    import awkward as ak
    _AWKWARD_AVAILABLE = True
except ImportError:
    _AWKWARD_AVAILABLE = False
    ak = None


#: Layout modes accepted by ``ImasSignal(layout=...)``.
LAYOUTS = ('compact', 'filled', 'ragged', 'awkward')


def validate_layout(layout):
    """Raise ``ValueError`` unless ``layout`` is a recognized mode.

    A typo must not silently fall back to a working default and return a
    different shape than the caller asked for.
    """
    if layout not in LAYOUTS:
        raise ValueError(
            f"Unknown layout {layout!r}. Valid layouts are: "
            f"{', '.join(LAYOUTS)}."
        )


def to_numpy(val):
    """Convert a compose() value to a numpy array.

    For regular arrays or uniformly-shaped ak.Array: returns np.ndarray.
    For ragged ak.Array: returns a numpy object array whose elements are
    1-D numpy arrays, one per outer entry.
    """
    if _AWKWARD_AVAILABLE and isinstance(val, ak.Array):
        try:
            return np.asarray(val)
        except (ValueError, TypeError):
            return _as_object_array([np.asarray(row) for row in val])
    return np.asarray(val)


def _as_object_array(rows):
    """Build a 1-D object array from a list of arrays.

    Built element-by-element rather than via ``np.array(rows, dtype=object)``,
    which collapses equal-length rows into a 2-D object array instead of
    keeping them as separate elements.
    """
    out = np.empty(len(rows), dtype=object)
    for i, row in enumerate(rows):
        out[i] = row
    return out


def _outer_len(value):
    """Length of ``value``'s outer axis, or None if it has no outer axis."""
    try:
        if isinstance(value, np.ndarray) and value.ndim == 0:
            return None
        return len(value)
    except TypeError:
        return None


def is_time_axis(value, times, split_by):
    """Return True when ``value``'s outer axis is a time axis.

    All three conditions must hold:

    1. ``times`` is a 1-D, non-object array,
    2. ``len(times)`` equals ``value``'s outer length,
    3. ``split_by`` is None.

    An entity axis (channel, measurement) fails condition 1 on the structure
    of its own time data: ``magnetics.ip`` carries an *object* array of
    per-measurement time arrays, and ECE carries a *2-D* array with one time
    row per channel.  Dropping or padding entries on such an axis would shift
    every entity's identity relative to the sibling ``name``/``identifier``
    arrays that are matched to it positionally, so this check is what makes
    that corruption unreachable rather than merely discouraged.
    """
    if split_by is not None:
        return False
    if times is None:
        return False
    times_arr = np.asarray(times)
    if times_arr.dtype == object or times_arr.ndim != 1:
        return False
    outer = _outer_len(value)
    return outer is not None and outer == len(times_arr)
