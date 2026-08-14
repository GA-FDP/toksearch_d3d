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
    For ragged input (an ak.Array, or a plain sequence such as a list of
    differently-shaped rows): returns a numpy object array whose elements
    are 1-D numpy arrays, one per outer entry.
    """
    if _AWKWARD_AVAILABLE and isinstance(val, ak.Array):
        try:
            return np.asarray(val)
        except (ValueError, TypeError):
            # Recurse: a row of a 3-level jagged array is itself jagged, and
            # np.asarray would raise on it outside any handler.
            return _as_object_array([to_numpy(row) for row in val])
    try:
        return np.asarray(val)
    except (ValueError, TypeError):
        # A plain ragged sequence (e.g. a list of differently-length arrays,
        # as callers may pass for ``times``) hits the same inhomogeneous-
        # shape error as a ragged ak.Array. Recurse the same way instead of
        # letting it escape.
        return _as_object_array([to_numpy(row) for row in val])


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


def outer_length(value):
    """Length of ``value``'s outer axis, or None when it has none.

    Public wrapper over ``_outer_len`` for callers outside this module.
    """
    return _outer_len(value)


def is_time_axis(value, times, split_by, entity_hint=False):
    """Return True when ``value``'s outer axis is a time axis.

    All four conditions must hold:

    1. ``times`` is a 1-D, non-object array,
    2. ``len(times)`` equals ``value``'s outer length,
    3. ``split_by`` is None,
    4. ``entity_hint`` is False.

    Conditions 1 and 2 are not sufficient on their own.  Entity axes usually
    fail condition 1 -- ``magnetics.ip`` carries an *object* array of
    per-measurement time arrays and ECE carries a *2-D* array with one time
    row per channel -- but ``_resolve_dim_ids_path`` falls back to the flat
    IDS-level ``<ids>.time`` whenever a sibling ``.time`` does not resolve, and
    in that case only a length coincidence would separate a channel axis from
    a time axis.  Condition 4 closes that gap structurally: the caller sets
    ``entity_hint`` when a sibling ``name``/``identifier``/``method_name``
    array has one entry per outer entry, which means the outer axis enumerates
    entities.

    This matters because entries on an entity axis are matched *positionally*
    against those same name arrays.  Dropping or padding one would misattribute
    every entry after it -- silent data corruption rather than a crash.
    """
    if split_by is not None:
        return False
    if entity_hint:
        return False
    if times is None:
        return False
    # to_numpy, not np.asarray: a ragged times sequence would otherwise raise
    # instead of simply failing the dtype check below.
    times_arr = to_numpy(times)
    if times_arr.dtype == object or times_arr.ndim != 1:
        return False
    outer = _outer_len(value)
    return outer is not None and outer == len(times_arr)


def _rows(value):
    """Return ``value``'s outer entries as a list of numpy arrays."""
    return [np.asarray(row) for row in value]


def _stack_or_object(rows):
    """Stack rows into a rectangular array, falling back to an object array."""
    if not rows:
        return np.array([], dtype=np.float64)
    try:
        return np.stack(rows)
    except ValueError:
        # Rows have differing shapes -- genuinely ragged, keep them separate.
        return _as_object_array(rows)


def _compact(value, dims):
    """Drop empty slots; filter parallel dim arrays in lockstep."""
    rows = _rows(value)
    keep = np.array([row.size > 0 for row in rows], dtype=bool)
    outer = len(rows)

    data = _stack_or_object([row for row, k in zip(rows, keep) if k])

    out_dims = {}
    for name, arr in dims.items():
        arr_np = np.asarray(arr)
        # Only arrays parallel to the outer axis are filtered.  A dim such as
        # 'rho' that indexes the *inner* axis must be left alone.
        if arr_np.ndim >= 1 and len(arr_np) == outer:
            out_dims[name] = arr_np[keep]
        else:
            out_dims[name] = arr
    return data, out_dims


def apply_layout(value, dims, layout, split_by=None, entity_hint=False):
    """Apply ``layout`` to a composed value and its dimension arrays.

    Args:
        value: Composed value from imas_composer (``ak.Array`` or ndarray).
        dims (dict): ``{dim_name: ndarray}``, already converted and scaled.
        layout (str): One of :data:`LAYOUTS`.
        split_by: ``ImasSignal``'s ``split_by`` setting; when not None the
            outer axis is a channel axis and layout is never applied.
        entity_hint (bool): True when a sibling entity-name array has one
            entry per outer entry, meaning the outer axis enumerates entities
            rather than times.  See :func:`is_time_axis`.

    Returns:
        tuple: ``(data, dims)`` after transformation.
    """
    validate_layout(layout)

    if layout == 'awkward':
        return value, dims

    if not is_time_axis(value, dims.get('times'), split_by,
                        entity_hint=entity_hint):
        return to_numpy(value), dims

    if layout == 'ragged':
        return to_numpy(value), dims

    if layout == 'compact':
        return _compact(value, dims)

    raise AssertionError(f"unreachable layout {layout!r}")  # pragma: no cover
