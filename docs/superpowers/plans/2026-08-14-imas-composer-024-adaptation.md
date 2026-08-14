# imas_composer 0.2.4 Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt `toksearch_d3d`'s `ImasSignal` to `imas_composer` 0.2.4 by adding a `layout=` kwarg that lets callers choose how non-rectangular composed data is presented.

**Architecture:** All layout logic lives in a new `toksearch_d3d/signal/imas_layout.py` as pure functions over `(value, dims)` — no `ImasSignal` state, no I/O — so the interesting cases are testable without shot data. `ImasSignal` gains a `layout=` kwarg (`compact`/`filled`/`ragged`/`awkward`), defaulting to `compact` for leaf paths and `filled` for prefix paths. Layout is applied only when the outer axis is provably a time axis; channel and measurement axes pass through untouched.

**Tech Stack:** Python 3.12, numpy, awkward, xarray, unittest, pixi, rattler-build.

**Spec:** `docs/superpowers/specs/2026-08-14-imas-composer-024-adaptation-design.md`

---

## AMENDMENT (post-review of Task 2) — READ BEFORE TASKS 3, 8, 9

Review of Task 2 found that the three-condition axis rule does **not**
structurally exclude entity axes, contrary to what Task 2's docstring claimed.
`_resolve_dim_ids_path` (`imas.py:277-314`) falls back to the IDS-level
`<ids>.time` — a flat 1-D numeric array — whenever the sibling `.time` does
not resolve, and always for paths not ending in `.data`/`.data_error_upper`.
When that happens, only a length coincidence separates a channel axis from a
time axis. Verified false positives: 48 per-channel rows with
`times = np.arange(48.)`, and 2 ip measurements with `times = np.array([0.,
1.])`, both returned True. "Came from the fallback" is not a usable
discriminator, because `core_profiles`' genuine time axis resolves through the
same fallback.

**A fourth condition is therefore added: `entity_hint`.** Task 2b (below)
implements it. Tasks 3, 8, and 9 must thread it through.

### Amended signatures

```python
# imas_layout.py
def is_time_axis(value, times, split_by, entity_hint=False): ...
def apply_layout(value, dims, layout, split_by=None, entity_hint=False): ...
def apply_layout_prefix(composed, layout, entity_hints=None): ...
```

`entity_hints` in `apply_layout_prefix` is an optional
`{leaf_path: bool}` mapping; a missing key means False.

`is_time_axis` returns False when `entity_hint` is True. Everything else
about the rule is unchanged.

### Where the hint comes from

`ImasSignal` owns the I/O, so it computes the bool and `imas_layout` stays
pure. Add to `toksearch_d3d/signal/imas.py`:

```python
# Leaf names that enumerate entities rather than times.  If one of these
# exists as a sibling with exactly one entry per outer entry, the outer axis
# indexes entities (channels, measurements) and must never be compacted --
# entries are matched positionally against these very arrays, so dropping one
# silently misattributes every entry after it.
_ENTITY_NAME_LEAVES = ('name', 'identifier', 'method_name', 'label')


def _entity_hint(self, ids_path, shot, raw_data, outer_len):
    """True when a sibling entity-name array has one entry per outer entry."""
    if not outer_len:
        return False
    parts = ids_path.split('.')
    # Walk from the most specific container up toward the IDS root.
    for cut in range(len(parts) - 1, 0, -1):
        prefix = '.'.join(parts[:cut])
        for leaf in _ENTITY_NAME_LEAVES:
            candidate = f'{prefix}.{leaf}'
            try:
                if not self._composer.get_supported_fields(candidate):
                    continue
            except ValueError:
                # Unknown IDS name -- nothing to look up under this prefix.
                continue
            val = self._fetch_dim(candidate, shot, raw_data)
            if val is None:
                continue
            arr = _to_numpy(val)
            if arr.ndim >= 1 and len(arr) == outer_len:
                return True
    return False
```

Expected behaviour: `core_profiles.profiles_1d.electrons.density` finds no
such sibling and yields False (time axis, compactable);
`ece.channel.t_e.data` finds `ece.channel.name` with 48 entries and yields
True; `magnetics.ip.data` finds `magnetics.ip.method_name` with 2 entries and
yields True.

Cost is a few in-memory `get_supported_fields` lookups plus at most one
compose of a name array, which `raw_data` caches and `_split_by_channel`
already fetches anyway.

---

## Background the engineer needs

`imas_composer` 0.2.4 changed two things relative to 0.2:

1. `core_profiles.profiles_1d.electrons.density_thermal` was renamed to
   `...electrons.density`. **Ion paths kept `density_thermal`** — only the
   electron field moved.
2. `core_profiles` moved to a unified GTIME axis. Every `profiles_1d` quantity
   is indexed by the same time array, with an **empty array** in slots where
   that quantity has no data. Composed values arrive as jagged `ak.Array`.

Measured on shot 202161: `electrons.density` and `.temperature` are 237 slots
with 228 non-empty; `ion.temperature` is 237 with only 100 non-empty;
`grid.rho_tor_norm` is 237 with 0 empty. Different quantities genuinely have
different time coverage.

The critical distinction driving this design:

- **Holes** — one common inner length plus empty slots. Recoverable to
  rectangular. Example: `core_profiles` (`{101}` and `{0}`).
- **Genuinely ragged** — several distinct real lengths. Not recoverable.
  Example: `magnetics.ip` (480256 and 44204), ECE channels.

**Running tests.** All commands run from the repo root
`/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d`.

Integration tests need FDP data access and **must** be launched through
`fdp run`, or ~40 IMAS tests fail spuriously with `TreeFOPENR`:

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q
```

Pure unit tests need no data access and run directly:

```bash
pixi run python -m pytest tests/test_imas_layout.py -q
```

The full suite (what CI runs) is `cd tests && ./testit`, a unittest
discovery harness.

**Shell note.** The environment shell is **zsh**, not bash. Quote glob
patterns passed to commands (`grep -rn "x" --include="*.py" .`), or zsh
expands them and the command fails with `no matches found`.

---

## File Structure

| File | Responsibility |
|---|---|
| `toksearch_d3d/signal/imas_layout.py` | **Create.** Pure layout functions: `to_numpy`, `validate_layout`, `is_time_axis`, `apply_layout`, `apply_layout_prefix`. No I/O, no `ImasSignal` state. |
| `toksearch_d3d/signal/imas.py` | **Modify.** `__init__` gains `layout=`; `gather` and `_gather_prefix` delegate to `imas_layout`; `_to_numpy` moves out; `fetch_as_xarray` error message improved. |
| `toksearch_d3d/__init__.py:138` | **Modify.** Stale `density_thermal` in the documented example. |
| `tests/test_imas_layout.py` | **Create.** Offline unit tests for every layout mode and error. |
| `tests/test_imas_signal.py` | **Modify.** Field rename, `magnetics.ip` shape fix, layout coverage. |
| `pixi.toml:25`, `recipe/recipe.yaml:39` | **Modify.** `imas_composer >=0.2.4,<0.3`. |

---

## Task 1: Move to imas_composer 0.2.4 and confirm the red state

This task deliberately **leaves the suite failing**. It establishes the
starting point every later task is measured against.

**Files:**
- Modify: `pixi.toml:25`
- Modify: `recipe/recipe.yaml:39`

- [ ] **Step 1: Bump the pixi dependency**

In `pixi.toml`, line 25, change:

```toml
imas_composer = ">=0.2"
```

to:

```toml
imas_composer = ">=0.2.4,<0.3"
```

- [ ] **Step 2: Bump the recipe dependency**

In `recipe/recipe.yaml`, line 39, change:

```yaml
    - imas_composer >=0.2
```

to:

```yaml
    - imas_composer >=0.2.4,<0.3
```

- [ ] **Step 3: Re-lock the environment**

```bash
pixi install
```

If this fails with "Disk quota exceeded", set a cache dir outside the quota
and retry:

```bash
RATTLER_CACHE_DIR=/tmp/rattler-$USER pixi install
```

- [ ] **Step 4: Verify 0.2.4 is installed**

```bash
pixi list | grep imas_composer
```

Expected: a line showing version `0.2.4`.

- [ ] **Step 5: Record the red state**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q 2>&1 | tail -12
```

Expected: `8 failed, 42 passed`. The 8 are three `TestImasSignalMagnetics`
(`test_ip_data_shape`, `test_ip_times_in_ms`,
`test_ip_data_fetch_as_xarray_times_coord`), three
`TestImasSignalCoreProfiles` (`test_electron_density_2d`,
`test_electron_temperature_2d`, `test_density_temperature_same_shape`), and
two `TestImasSignalXarray` (`test_profile_2d_dataarray`,
`test_profile_2d_times_coord`).

If you see a different count, stop and report it — the rest of the plan
assumes this baseline.

- [ ] **Step 6: Commit**

```bash
git add pixi.toml pixi.lock recipe/recipe.yaml
git commit -m "build: require imas_composer >=0.2.4,<0.3"
```

---

## Task 2: Create imas_layout with to_numpy, validation, and the axis rule

**Files:**
- Create: `toksearch_d3d/signal/imas_layout.py`
- Create: `tests/test_imas_layout.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_imas_layout.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named
'toksearch_d3d.signal.imas_layout'`.

- [ ] **Step 3: Write the implementation**

Create `toksearch_d3d/signal/imas_layout.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q
```

Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/signal/imas_layout.py tests/test_imas_layout.py
git commit -m "feat(imas_layout): add layout validation and the time-axis rule"
```

---

## Task 2b: Close the review findings on imas_layout

Applies the amendment above plus three defects review found in Task 2. Pure
`imas_layout` work only — `ImasSignal` wiring is Tasks 6-9.

**Files:**
- Modify: `toksearch_d3d/signal/imas_layout.py`
- Modify: `tests/test_imas_layout.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_imas_layout.py`:

```python
import awkward as ak


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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k "LayoutsContents or ToNumpyAwkward or EntityHint"
```

Expected: FAIL. `test_three_level_jagged_does_not_raise` raises `ValueError:
cannot convert to RegularArray`; the `entity_hint` tests raise `TypeError:
is_time_axis() got an unexpected keyword argument`.

- [ ] **Step 3: Fix to_numpy to recurse**

In `toksearch_d3d/signal/imas_layout.py`, in `to_numpy`, replace:

```python
            return _as_object_array([np.asarray(row) for row in val])
```

with:

```python
            # Recurse: a row of a 3-level jagged array is itself jagged, and
            # np.asarray would raise on it outside any handler.
            return _as_object_array([to_numpy(row) for row in val])
```

- [ ] **Step 4: Add entity_hint, a public outer_length, and safe times conversion**

First, in `toksearch_d3d/signal/imas_layout.py`, add a public wrapper directly
below `_outer_len` (Tasks 8 and 9 need the outer length from `imas.py`, and
reaching across modules for a private name is worse than exporting one):

```python
def outer_length(value):
    """Length of ``value``'s outer axis, or None when it has none.

    Public wrapper over ``_outer_len`` for callers outside this module.
    """
    return _outer_len(value)
```

Then replace the whole `is_time_axis` function with:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q
```

Expected: `19 passed` (11 from Task 2, 8 added here).

- [ ] **Step 6: Verify the new tests bite**

Temporarily change `if entity_hint:` to `if False:` and re-run:

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k EntityHint
```

Expected: FAIL on `test_entity_hint_blocks_an_otherwise_time_like_axis`. Then
revert with `git checkout toksearch_d3d/signal/imas_layout.py` **only if you
have already committed**; otherwise undo the edit by hand.

- [ ] **Step 7: Commit**

```bash
git add toksearch_d3d/signal/imas_layout.py tests/test_imas_layout.py
git commit -m "fix(imas_layout): add the entity-axis guard and close review gaps"
```

---

## Task 3: Implement compact mode

`compact` drops empty slots and filters every parallel dim array in lockstep.
It promises **only** "no empty slots" — not rectangularity. Rectangularity is
what you get when one common inner length remains.

**Files:**
- Modify: `toksearch_d3d/signal/imas_layout.py`
- Modify: `tests/test_imas_layout.py`

- [ ] **Step 1: Import apply_layout in the test module**

`apply_layout` is introduced in this task, so add it to the existing import
block at the top of `tests/test_imas_layout.py`:

```python
from toksearch_d3d.signal.imas_layout import (
    LAYOUTS,
    apply_layout,
    is_time_axis,
    to_numpy,
    validate_layout,
)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_imas_layout.py`:

```python
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
        # object times => measurement axis => no compaction even with a hole
        value = np.empty(2, dtype=object)
        value[0] = np.array([], dtype=np.float64)
        value[1] = np.arange(4, dtype=np.float64)
        times = np.empty(2, dtype=object)
        times[0] = np.array([], dtype=np.float64)
        times[1] = np.arange(4, dtype=np.float64)
        data, out_dims = apply_layout(value, {'times': times}, 'compact')
        self.assertEqual(len(data), 2)
        self.assertEqual(len(out_dims['times']), 2)

    def test_non_parallel_dims_are_not_filtered(self):
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64),
                'rho': np.arange(3, dtype=np.float64)}
        _, out_dims = apply_layout(value, dims, 'compact')
        self.assertEqual(len(out_dims['times']), 3)
        self.assertEqual(len(out_dims['rho']), 3)  # length 3 != outer 5
        np.testing.assert_array_equal(out_dims['rho'], [0.0, 1.0, 2.0])
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k Compact
```

Expected: collection error, `ImportError: cannot import name 'apply_layout'`.

- [ ] **Step 4: Write the implementation**

Append to `toksearch_d3d/signal/imas_layout.py`:

```python
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
```

- [ ] **Step 5: Add the dispatcher stub so tests can call it**

Append to `toksearch_d3d/signal/imas_layout.py`:

```python
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
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k Compact
```

Expected: `8 passed`.

- [ ] **Step 7: Commit**

```bash
git add toksearch_d3d/signal/imas_layout.py tests/test_imas_layout.py
git commit -m "feat(imas_layout): implement compact mode"
```

---

## Task 4: Implement filled mode

`filled` keeps every slot and pads the empty ones with NaN. It raises rather
than inventing data when padding is not well defined.

**Files:**
- Modify: `toksearch_d3d/signal/imas_layout.py`
- Modify: `tests/test_imas_layout.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_imas_layout.py`:

```python
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
        value = truly_ragged()
        dims = {'times': np.arange(2, dtype=np.float64)}
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
        self.assertIn('int', str(cm.exception).lower())

    def test_all_slots_empty_yields_length_zero_rows(self):
        value = holey(n_slots=3, empty_at=(0, 1, 2))
        dims = {'times': np.arange(3, dtype=np.float64)}
        data, out_dims = apply_layout(value, dims, 'filled')
        self.assertEqual(data.shape, (3, 0))
        self.assertEqual(len(out_dims['times']), 3)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k Filled
```

Expected: FAIL — `apply_layout` hits the `AssertionError: unreachable layout
'filled'` line.

- [ ] **Step 3: Write the implementation**

Append to `toksearch_d3d/signal/imas_layout.py`, above `apply_layout`:

```python
def _filled(value, dims):
    """Keep every slot; pad empty slots with NaN to the common inner shape."""
    rows = _rows(value)
    non_empty = [row for row in rows if row.size > 0]

    if not non_empty:
        # Every slot empty: the common inner shape is (0,), so the result is
        # an (n_slots, 0) array.  Nothing to fill, and no dtype to infer.
        return np.zeros((len(rows), 0), dtype=np.float64), dims

    shapes = {row.shape for row in non_empty}
    if len(shapes) > 1:
        listed = ', '.join(str(s[0]) for s in sorted(shapes))
        raise ValueError(
            f"layout='filled' needs one common inner length to pad to, but "
            f"the non-empty slots have {len(shapes)} distinct lengths: "
            f"{listed}. This data is genuinely ragged rather than holey, so "
            f"padding would fabricate values. Use layout='ragged' or "
            f"layout='compact'."
        )

    dtype = np.result_type(*[row.dtype for row in non_empty])
    if not np.issubdtype(dtype, np.floating):
        raise ValueError(
            f"layout='filled' requires floating-point data, but this field "
            f"has dtype {dtype}. NaN has no meaning in a {dtype} array, so "
            f"gaps cannot be marked. Use layout='ragged' or layout='compact'."
        )

    inner_shape = shapes.pop()
    out = np.full((len(rows),) + inner_shape, np.nan, dtype=dtype)
    for i, row in enumerate(rows):
        if row.size > 0:
            out[i] = row
    return out, dims
```

- [ ] **Step 4: Wire `filled` into the dispatcher**

In `toksearch_d3d/signal/imas_layout.py`, in `apply_layout`, replace:

```python
    if layout == 'compact':
        return _compact(value, dims)
```

with:

```python
    if layout == 'compact':
        return _compact(value, dims)

    if layout == 'filled':
        return _filled(value, dims)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q
```

Expected: `27 passed` (11 from Task 2, 8 from Task 3, 8 here).

- [ ] **Step 6: Commit**

```bash
git add toksearch_d3d/signal/imas_layout.py tests/test_imas_layout.py
git commit -m "feat(imas_layout): implement filled mode"
```

---

## Task 5: Cover ragged and awkward pass-through

**Files:**
- Modify: `tests/test_imas_layout.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_imas_layout.py`:

```python
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
        value = holey(n_slots=5, n_rho=3, empty_at=(1, 3))
        dims = {'times': np.arange(5, dtype=np.float64)}
        data, _ = apply_layout(value, dims, 'awkward')
        self.assertIs(data, value)

    def test_awkward_skips_the_axis_rule(self):
        # No times at all: awkward must still pass the value straight through.
        value = holey(n_slots=5)
        data, _ = apply_layout(value, {}, 'awkward')
        self.assertIs(data, value)

    def test_unknown_layout_raises_before_any_work(self):
        with self.assertRaises(ValueError):
            apply_layout(holey(), {'times': np.arange(5.0)}, 'compacted')
```

- [ ] **Step 2: Run the tests to verify they pass**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k RaggedAndAwkward
```

Expected: `4 passed`. These exercise dispatcher branches written in Task 3,
so they should pass without new implementation. If any fail, fix
`apply_layout` before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_imas_layout.py
git commit -m "test(imas_layout): cover ragged and awkward pass-through"
```

---

## Task 6: Add the layout kwarg to ImasSignal.__init__

**Files:**
- Modify: `toksearch_d3d/signal/imas.py:39-51` (delete `_to_numpy`)
- Modify: `toksearch_d3d/signal/imas.py:188-234` (`__init__`)
- Modify: `tests/test_imas_signal.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_imas_signal.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k LayoutKwarg
```

Expected: FAIL with `AttributeError: 'ImasSignal' object has no attribute
'layout'`.

- [ ] **Step 3: Replace the local `_to_numpy` with the shared one**

In `toksearch_d3d/signal/imas.py`, delete lines 39-51 (the `_to_numpy`
function and its docstring) entirely, and delete the now-unused awkward
import block at lines 29-34:

```python
try:
    import awkward as ak
    _AWKWARD_AVAILABLE = True
except ImportError:
    _AWKWARD_AVAILABLE = False
    ak = None
```

Then add to the import block near the top of the file, after the
`from toksearch_d3d.signal.ptdata import PtDataSignal` line:

```python
from toksearch_d3d.signal.imas_layout import (
    apply_layout,
    outer_length,
    to_numpy as _to_numpy,
    validate_layout,
)
```

Aliasing `to_numpy` to `_to_numpy` keeps the existing call sites in
`_fetch_all_dims` and `_split_by_channel` working unchanged.

Also add the `_ENTITY_NAME_LEAVES` constant and the `_entity_hint` method
given in the **AMENDMENT** section near the top of this plan. `_entity_hint`
is a method on `ImasSignal`; place it directly above `_fetch_dim`.

Also add `import warnings` to the standard-library imports at the top of the
file.

- [ ] **Step 4: Add the kwarg to the signature**

In `toksearch_d3d/signal/imas.py`, in `__init__`, change:

```python
        units=None,
        as_awkward=False,
    ):
```

to:

```python
        units=None,
        as_awkward=None,
        layout=None,
    ):
```

- [ ] **Step 5: Replace the `as_awkward` assignment**

In `__init__`, replace:

```python
        self._max_iter = max_resolve_iterations
        self._as_awkward = as_awkward
```

with:

```python
        self._max_iter = max_resolve_iterations

        # `as_awkward` is the deprecated spelling of `layout='awkward'`.
        if as_awkward is not None:
            if layout is not None:
                raise ValueError(
                    "Pass either layout= or as_awkward=, not both. "
                    "as_awkward=True is equivalent to layout='awkward'."
                )
            warnings.warn(
                "as_awkward is deprecated; use layout='awkward' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            # as_awkward=False asked for numpy output, which is what the
            # default layouts already produce -- leave layout unset so the
            # leaf/prefix default applies.
            layout = 'awkward' if as_awkward else None
        if layout is not None:
            validate_layout(layout)
        self._requested_layout = layout
```

- [ ] **Step 6: Resolve the default after leaf/prefix detection**

In `__init__`, replace the leaf/prefix detection block:

```python
        # Detect leaf vs prefix path.
        leaf_paths = self._composer.get_supported_fields(ids_path)
        if len(leaf_paths) == 1 and leaf_paths[0] == ids_path:
            self._leaf_paths = None  # leaf mode — existing single-field behaviour
        elif len(leaf_paths) > 1:
            if split_by is not None:
                raise ValueError(
                    "split_by is not supported for prefix IDS paths"
                )
            self._leaf_paths = leaf_paths  # prefix mode — multi-field batch
        else:
            raise ValueError(f"No supported fields found for '{ids_path}'")
```

with:

```python
        # Detect leaf vs prefix path.
        leaf_paths = self._composer.get_supported_fields(ids_path)
        if len(leaf_paths) == 1 and leaf_paths[0] == ids_path:
            self._leaf_paths = None  # leaf mode — existing single-field behaviour
        elif len(leaf_paths) > 1:
            if split_by is not None:
                raise ValueError(
                    "split_by is not supported for prefix IDS paths"
                )
            self._leaf_paths = leaf_paths  # prefix mode — multi-field batch
        else:
            raise ValueError(f"No supported fields found for '{ids_path}'")

        # Layout default depends on the fetch kind: a leaf fetch returns one
        # field on its own time base, while a prefix fetch is a *joint* fetch
        # whose value comes from every leaf sharing one axis.
        self._is_prefix = self._leaf_paths is not None
        if self._requested_layout is None:
            self.layout = 'filled' if self._is_prefix else 'compact'
        else:
            self.layout = self._requested_layout
            if self._is_prefix and self.layout == 'compact':
                raise ValueError(
                    f"layout='compact' is not supported for prefix path "
                    f"'{ids_path}': each leaf would compact onto its own "
                    f"time base while the sibling '.time' leaf keeps the "
                    f"full shared axis, leaving them mutually unaligned. "
                    f"Use layout='filled' (the prefix default), or fetch "
                    f"leaves individually."
                )
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k LayoutKwarg
```

Expected: `9 passed`.

- [ ] **Step 8: Commit**

```bash
git add toksearch_d3d/signal/imas.py tests/test_imas_signal.py
git commit -m "feat(ImasSignal): add layout= kwarg, deprecating as_awkward"
```

---

## Task 7: Report the renamed electron density field

**Files:**
- Modify: `toksearch_d3d/signal/imas.py`
- Modify: `tests/test_imas_signal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_imas_signal.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k RenamedField
```

Expected: `test_old_electron_path_reports_the_rename` FAILS (the generic "No
supported fields found" message lacks `0.2.4`). The other two should pass.

- [ ] **Step 3: Write the implementation**

In `toksearch_d3d/signal/imas.py`, add near the top after
`_PTDATA_TREENAME = "__ptdata__"`:

```python
# Paths renamed by imas_composer 0.2.4.  Reported as a targeted error rather
# than silently aliased: upstream dropped the `_thermal` suffix as a
# deliberate semantic decision (their PR #50), and ion paths legitimately
# kept `density_thermal`, so a blind rewrite would be wrong.
_RENAMED_PATHS = {
    'core_profiles.profiles_1d.electrons.density_thermal':
        'core_profiles.profiles_1d.electrons.density',
}
```

Then in `__init__`, replace:

```python
        else:
            raise ValueError(f"No supported fields found for '{ids_path}'")
```

with:

```python
        else:
            renamed_to = _RENAMED_PATHS.get(ids_path)
            if renamed_to is not None:
                raise ValueError(
                    f"'{ids_path}' was renamed to '{renamed_to}' in "
                    f"imas_composer 0.2.4. Note that ion paths kept "
                    f"'density_thermal' -- only the electron field changed."
                )
            raise ValueError(f"No supported fields found for '{ids_path}'")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k RenamedField
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/signal/imas.py tests/test_imas_signal.py
git commit -m "feat(ImasSignal): report the 0.2.4 electron density rename"
```

---

## Task 8: Apply layout in gather()

`gather` currently composes data, then fetches dims. Compaction needs `times`
*before* it transforms `data`, so the order flips.

**Files:**
- Modify: `toksearch_d3d/signal/imas.py` (`gather`, around lines 397-435)
- Modify: `tests/test_imas_signal.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_imas_signal.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k LayoutIntegration
```

Expected: several failures — `compact` currently returns a `(237,)` object
array, so `test_compact_is_rectangular` fails with `1 != 2`.

- [ ] **Step 3: Write the implementation**

In `toksearch_d3d/signal/imas.py`, in `gather`, replace:

```python
        if self._split_by == 'channel':
            return self._split_by_channel(shot, composed, raw_data)

        out = {'data': composed if self._as_awkward else _to_numpy(composed)}

        # Phase 3: supplementary dimension arrays
        out.update(self._fetch_all_dims(shot, raw_data))

        return out
```

with:

```python
        if self._split_by == 'channel':
            return self._split_by_channel(shot, composed, raw_data)

        # Phase 3: supplementary dimension arrays.  Fetched *before* the
        # layout is applied because 'compact' filters data and its parallel
        # dim arrays in lockstep, and because the time-axis rule needs
        # 'times' to decide whether the outer axis may be transformed at all.
        dims = self._fetch_all_dims(shot, raw_data)

        # Phase 4: shape the composed value the way the caller asked for.
        # The entity hint keeps a channel/measurement axis from ever being
        # compacted -- see imas_layout.is_time_axis.
        entity_hint = self._entity_hint(
            self.ids_path, shot, raw_data, outer_length(composed)
        )
        data, dims = apply_layout(
            composed, dims, self.layout,
            split_by=self._split_by, entity_hint=entity_hint,
        )

        out = {'data': data}
        out.update(dims)
        return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k LayoutIntegration
```

Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/signal/imas.py tests/test_imas_signal.py
git commit -m "feat(ImasSignal): apply the selected layout in gather()"
```

---

## Task 9: Apply layout in _gather_prefix()

Prefix mode never calls `_fetch_all_dims`, so there is no `times` to feed the
axis rule. The shared axis is instead available as a composed sibling leaf
whose path ends in `.time`; its length is the match target.

**Files:**
- Modify: `toksearch_d3d/signal/imas_layout.py`
- Modify: `toksearch_d3d/signal/imas.py` (`_gather_prefix`, lines 380-395)
- Modify: `tests/test_imas_layout.py`
- Modify: `tests/test_imas_signal.py`

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/test_imas_layout.py`:

```python
from toksearch_d3d.signal.imas_layout import apply_layout_prefix


class TestApplyLayoutPrefix(unittest.TestCase):
    def _composed(self):
        return {
            'core_profiles.profiles_1d.electrons.density':
                holey(n_slots=5, n_rho=3, empty_at=(1, 3)),
            'core_profiles.profiles_1d.ion.temperature':
                holey(n_slots=5, n_rho=3, empty_at=(0, 1, 2)),
            'core_profiles.profiles_1d.time':
                np.arange(5, dtype=np.float64),
            'core_profiles.profiles_1d.ion.label':
                np.array('D'),
        }

    def test_filled_pads_every_time_indexed_leaf(self):
        out = apply_layout_prefix(self._composed(), 'filled')
        ne = out['core_profiles.profiles_1d.electrons.density']
        ti = out['core_profiles.profiles_1d.ion.temperature']
        self.assertEqual(ne.shape, (5, 3))
        self.assertEqual(ti.shape, (5, 3))

    def test_leaves_stay_index_aligned(self):
        out = apply_layout_prefix(self._composed(), 'filled')
        lengths = {
            len(out['core_profiles.profiles_1d.electrons.density']),
            len(out['core_profiles.profiles_1d.ion.temperature']),
            len(out['core_profiles.profiles_1d.time']),
        }
        self.assertEqual(lengths, {5})

    def test_scalar_leaf_passes_through(self):
        out = apply_layout_prefix(self._composed(), 'filled')
        self.assertEqual(
            out['core_profiles.profiles_1d.ion.label'].ndim, 0)

    def test_time_leaf_itself_is_unchanged(self):
        out = apply_layout_prefix(self._composed(), 'filled')
        np.testing.assert_array_equal(
            out['core_profiles.profiles_1d.time'], np.arange(5.0))

    def test_ragged_leaves_object_arrays(self):
        out = apply_layout_prefix(self._composed(), 'ragged')
        ne = out['core_profiles.profiles_1d.electrons.density']
        self.assertEqual(ne.dtype, object)
        self.assertEqual(len(ne), 5)

    def test_unfillable_leaf_raises_naming_the_leaf(self):
        composed = self._composed()
        composed['core_profiles.profiles_1d.bad'] = truly_ragged()
        composed['core_profiles.profiles_1d.time'] = np.arange(
            2, dtype=np.float64)
        with self.assertRaises(ValueError) as cm:
            apply_layout_prefix(composed, 'filled')
        self.assertIn('core_profiles.profiles_1d.bad', str(cm.exception))

    def test_no_time_leaf_passes_everything_through(self):
        composed = {'some.ids.field': holey(n_slots=4)}
        out = apply_layout_prefix(composed, 'filled')
        self.assertEqual(len(out['some.ids.field']), 4)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k ApplyLayoutPrefix
```

Expected: `ImportError: cannot import name 'apply_layout_prefix'`.

- [ ] **Step 3: Write the implementation**

Append to `toksearch_d3d/signal/imas_layout.py`:

```python
def _prefix_shared_time(composed):
    """Return the batch's shared time axis, or None.

    In prefix mode no dim arrays are fetched, but the shared axis is present
    as a composed sibling leaf whose path ends in ``.time`` (for example
    ``core_profiles.profiles_1d.time``).
    """
    for path, value in composed.items():
        if not path.endswith('.time'):
            continue
        arr = to_numpy(value)
        if arr.ndim == 1 and arr.dtype != object:
            return arr
    return None


def apply_layout_prefix(composed, layout, entity_hints=None):
    """Apply ``layout`` to every leaf of a prefix batch.

    Leaves whose outer length matches the batch's shared time axis are
    transformed; every other leaf (0-d scalars, entity-indexed values) passes
    through untouched, so the batch stays index-aligned.

    Args:
        composed (dict): ``{leaf_path: composed_value}``.
        layout (str): One of :data:`LAYOUTS`. ``'compact'`` is rejected by
            ``ImasSignal.__init__`` before reaching here.
        entity_hints (dict): Optional ``{leaf_path: bool}``; a leaf marked
            True has an entity outer axis and is never transformed. A missing
            key means False.

    Returns:
        dict: ``{leaf_path: value}``.
    """
    validate_layout(layout)

    if layout == 'awkward':
        return dict(composed)

    shared_time = _prefix_shared_time(composed)
    hints = entity_hints or {}

    out = {}
    for path, value in composed.items():
        if layout == 'ragged' or not is_time_axis(
            value, shared_time, None, entity_hint=hints.get(path, False)
        ):
            out[path] = to_numpy(value)
            continue
        try:
            data, _ = apply_layout(value, {'times': shared_time}, layout)
        except ValueError as exc:
            raise ValueError(f"leaf '{path}': {exc}") from exc
        out[path] = data
    return out
```

- [ ] **Step 4: Run the unit tests to verify they pass**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k ApplyLayoutPrefix
```

Expected: `7 passed`.

- [ ] **Step 5: Wire it into `_gather_prefix`**

In `toksearch_d3d/signal/imas.py`, in `_gather_prefix`, replace:

```python
        composed = self._composer.compose(self._leaf_paths, shot, raw_data)
        convert = (lambda v: v) if self._as_awkward else _to_numpy
        return {path: convert(val) for path, val in composed.items()}
```

with:

```python
        composed = self._composer.compose(self._leaf_paths, shot, raw_data)
        entity_hints = {
            path: self._entity_hint(path, shot, raw_data, outer_length(value))
            for path, value in composed.items()
        }
        return apply_layout_prefix(composed, self.layout, entity_hints)
```

Add `apply_layout_prefix` to the `imas_layout` import block added in Task 6:

```python
from toksearch_d3d.signal.imas_layout import (
    apply_layout,
    apply_layout_prefix,
    outer_length,
    to_numpy as _to_numpy,
    validate_layout,
)
```

- [ ] **Step 6: Write the integration test**

Append to `tests/test_imas_signal.py`:

```python
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
```

- [ ] **Step 7: Run the integration tests to verify they pass**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k PrefixLayout
```

Expected: `2 passed`.

- [ ] **Step 8: Commit**

```bash
git add toksearch_d3d/signal/imas.py toksearch_d3d/signal/imas_layout.py tests/
git commit -m "feat(ImasSignal): apply layout across prefix batches"
```

---

## Task 10: Improve the ragged fetch_as_xarray error

The current message says "use `fetch()`" without mentioning that
`layout='filled'` makes the call work.

**Files:**
- Modify: `toksearch_d3d/signal/imas.py` (around lines 487-492)
- Modify: `tests/test_imas_signal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_imas_signal.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k XarrayRaggedMessage
```

Expected: FAIL — the message contains neither layout suggestion.

- [ ] **Step 3: Write the implementation**

In `toksearch_d3d/signal/imas.py`, in `fetch_as_xarray`, replace:

```python
        if data.dtype == object:
            raise NotImplementedError(
                f"fetch_as_xarray() does not support ragged (object-array) "
                f"data from '{self.ids_path}'. Use fetch() instead."
            )
```

with:

```python
        if data.dtype == object:
            raise NotImplementedError(
                f"fetch_as_xarray() does not support ragged (object-array) "
                f"data from '{self.ids_path}' (layout={self.layout!r}). "
                f"If this field is holey rather than genuinely ragged, "
                f"layout='filled' or layout='compact' produces a rectangular "
                f"array that this method accepts. Otherwise use fetch()."
            )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k XarrayRaggedMessage
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/signal/imas.py tests/test_imas_signal.py
git commit -m "feat(ImasSignal): point the ragged xarray error at layout="
```

---

## Task 11: Update the existing integration tests

Two distinct fixes: the renamed field, and `magnetics.ip`'s shape — which
changed because 0.2.4 exposes **two** ip measurements of different lengths
where 0.2 had one. The existing `magnetics` assertions describe 0.2's world
and would keep passing after a pure rename, so they must be rewritten
against the measured 0.2.4 behaviour.

**Files:**
- Modify: `tests/test_imas_signal.py:372-393` (core_profiles)
- Modify: `tests/test_imas_signal.py:294-310` (magnetics)
- Modify: `tests/test_imas_signal.py:455-475` (xarray)

- [ ] **Step 1: Rename the electron density path**

In `tests/test_imas_signal.py`, replace all five occurrences of
`core_profiles.profiles_1d.electrons.density_thermal` with
`core_profiles.profiles_1d.electrons.density` — four call sites (lines 373,
389, 458, 470) and one docstring (line 372).

```bash
sed -i 's/electrons\.density_thermal/electrons.density/g' tests/test_imas_signal.py
grep -c "electrons.density_thermal" tests/test_imas_signal.py
```

Expected: `0`.

- [ ] **Step 2: Run the core_profiles and xarray tests**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q \
    -k "CoreProfiles or Xarray"
```

Expected: all pass. `compact` is the default, so the profile fields are
rectangular `(n_time, n_rho)` again and the existing 2-D assertions hold.

- [ ] **Step 3: Rewrite the magnetics ip shape test**

In `tests/test_imas_signal.py`, replace the body of `test_ip_data_shape`:

```python
    def test_ip_data_shape(self):
        """magnetics.ip.data is (n_measurements, n_time); DIII-D has 1 measurement."""
        result = self._gather('magnetics.ip.data')
        self.assertIsInstance(result['data'], np.ndarray)
        self.assertEqual(result['data'].ndim, 2)
        self.assertEqual(result['data'].shape[0], 1)
        self.assertGreater(result['data'].shape[1], 0)
```

with:

```python
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
```

- [ ] **Step 4: Inspect the remaining magnetics failures**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k Magnetics 2>&1 | tail -40
```

`test_ip_times_in_ms` and `test_ip_data_fetch_as_xarray_times_coord` were
written against the single-measurement shape. Read the failure output and
update each assertion to match the measured two-measurement structure:
`times` is an object array of two 1-D arrays, and `fetch_as_xarray` raises
`NotImplementedError` for an object-dtype value.

For `test_ip_times_in_ms`, assert the millisecond scaling on each entry:

```python
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
```

For `test_ip_data_fetch_as_xarray_times_coord`, assert the documented
refusal, since an entity axis with per-entry time bases has no rectangular
xarray form:

```python
    def test_ip_data_fetch_as_xarray_times_coord(self):
        """Ragged ip data has no rectangular xarray form."""
        from toksearch_d3d import ImasSignal
        sig = ImasSignal('magnetics.ip.data', composer=self.composer)
        with self.assertRaises(NotImplementedError):
            sig.fetch_as_xarray(SHOT_MAGNETICS)
```

- [ ] **Step 5: Run the magnetics tests to verify they pass**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q -k Magnetics
```

Expected: all pass.

- [ ] **Step 6: Run the whole IMAS file**

```bash
pixi run fdp run python -m pytest tests/test_imas_signal.py -q 2>&1 | tail -5
```

Expected: `0 failed`.

- [ ] **Step 7: Commit**

```bash
git add tests/test_imas_signal.py
git commit -m "test(imas): update integration tests for imas_composer 0.2.4"
```

---

## Task 12: Prove the new tests actually fail when the code is wrong

Every bug found in this repo group over the past week was a check that could
not fail. This task verifies these checks bite. **No code is kept from this
task** — each mutation is reverted.

**Files:** none modified permanently.

- [ ] **Step 1: Mutate compact into a no-op**

In `toksearch_d3d/signal/imas_layout.py`, temporarily change `_compact`'s
first body line to keep every row:

```python
    keep = np.array([True for row in rows], dtype=bool)
```

- [ ] **Step 2: Confirm the tests catch it**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k Compact 2>&1 | tail -5
```

Expected: FAIL, including `test_holes_become_rectangular` and
`test_times_filtered_in_lockstep`. If everything passes, the tests are not
testing compaction — fix them before proceeding.

- [ ] **Step 3: Revert the mutation**

```bash
git checkout toksearch_d3d/signal/imas_layout.py
```

- [ ] **Step 4: Mutate the axis rule to ignore object times**

In `is_time_axis`, temporarily change:

```python
    if times_arr.dtype == object or times_arr.ndim != 1:
        return False
```

to:

```python
    if times_arr.ndim != 1:
        return False
```

- [ ] **Step 5: Confirm the entity-axis guard catches it**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k "IsTimeAxis or Compact" 2>&1 | tail -5
```

Expected: FAIL on `test_object_times_is_not_time_axis` and
`test_entity_axis_untouched`. This is the check that keeps channel identity
from shifting — if it does not fail here, that protection is not tested.

- [ ] **Step 6: Revert the mutation**

```bash
git checkout toksearch_d3d/signal/imas_layout.py
```

- [ ] **Step 7: Mutate filled to skip the dtype guard**

In `_filled`, temporarily delete the `if not np.issubdtype(dtype,
np.floating):` block (the raise and its message).

- [ ] **Step 8: Confirm the dtype guard is tested**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q -k Filled 2>&1 | tail -5
```

Expected: FAIL on `test_non_float_raises`.

- [ ] **Step 9: Revert and confirm a clean tree**

```bash
git checkout toksearch_d3d/signal/imas_layout.py
git status --short
```

Expected: no modifications to `toksearch_d3d/signal/imas_layout.py`.

---

## Task 13: Update the documentation

**Files:**
- Modify: `toksearch_d3d/__init__.py:138`
- Modify: `toksearch_d3d/signal/imas.py` (class docstring, around lines 174-178)

- [ ] **Step 1: Fix the stale example path**

In `toksearch_d3d/__init__.py`, line 138, change:

```
    core_profiles.profiles_1d.electrons.density_thermal
```

to:

```
    core_profiles.profiles_1d.electrons.density
```

- [ ] **Step 2: Replace the as_awkward docstring entry**

In `toksearch_d3d/signal/imas.py`, in the `ImasSignal` class docstring,
replace the `as_awkward:` entry:

```
        as_awkward: If `True`, return the raw composed value from imas_composer
            without converting to numpy.  The result may be an `ak.Array`
            (regular or ragged) or a plain `np.ndarray` depending on the field.
            Useful for preserving ragged structure instead of receiving a numpy
            object array.  Defaults to `False` (numpy output).
```

with:

```
        layout: How non-rectangular composed data is presented.  One of:

            - `'compact'` — drop slots that have no data, filtering `times`
              and any other parallel dim array in lockstep.  Promises only
              "no empty slots", not rectangularity: a field becomes a
              rectangular `ndarray` when one common inner length remains,
              and stays an object array otherwise.  Default for **leaf**
              paths.
            - `'filled'` — keep every slot, padding empty ones with NaN so
              all leaves stay index-aligned to one shared time axis.
              Requires floating-point data and one common inner length;
              raises otherwise rather than fabricating values.  Default for
              **prefix** paths, where a joint fetch implies a shared axis.
            - `'ragged'` — no transformation; the object array exactly as
              imas_composer produced it, empty slots included.
            - `'awkward'` — the raw `ak.Array`, with no numpy conversion.

            Layout applies **only** when the outer axis is provably a time
            axis: `times` must be a 1-D non-object array whose length matches
            the value's outer length, and `split_by` must be None.  Channel
            and measurement axes (`ece.channel.t_e.data`, `magnetics.ip.data`)
            fail that test on the structure of their own time data and pass
            through untouched in every mode — dropping or padding entries
            there would shift each entity's identity relative to the sibling
            `name` array matched to it positionally.

            `layout='compact'` is rejected for prefix paths: leaves would
            compact onto divergent time bases while the sibling `.time` leaf
            keeps the full shared axis.

        as_awkward: **Deprecated** — use `layout='awkward'`.  Passing both
            `as_awkward` and `layout` raises `ValueError`.
```

- [ ] **Step 3: Check the skill docs for stale field names**

```bash
grep -rn "density_thermal" /fusion/projects/dt/sammuli/fdp_dev/repos/.claude/skills/ 2>/dev/null || echo "no stale references"
```

If any electron `density_thermal` references appear, update them to
`density`. Leave **ion** `density_thermal` references alone — that spelling
is still correct for ions.

- [ ] **Step 4: Verify the CLAUDE.md demo recipe still holds**

The repository `CLAUDE.md` documents a βN vs NBI power recipe using
`ImasSignal`. Confirm both of its IDS paths still behave as documented:

```bash
pixi run fdp run python -c "
from toksearch_d3d import ImasSignal
from imas_composer import ImasComposer
import numpy as np
c = ImasComposer()
bn = ImasSignal('equilibrium.time_slice.global_quantities.beta_normal', composer=c).gather(202161)
nbi = ImasSignal('nbi.unit.power_launched.data', composer=c).gather(202161)
print('beta_normal:', bn['data'].shape, bn['data'].dtype)
print('nbi:', nbi['data'].shape, nbi['data'].dtype)
print('nbi stack ok:', np.stack([np.asarray(u) for u in nbi['data']]).shape
      if nbi['data'].dtype == object else 'rectangular')
"
```

Expected: `beta_normal` is a 1-D float array; `nbi` is an 8-element object
array (an entity axis — one entry per beam unit — so layout is a no-op) that
still stacks, exactly as the recipe describes. If either differs, update the
recipe in `CLAUDE.md`.

- [ ] **Step 5: Commit**

```bash
git add toksearch_d3d/__init__.py toksearch_d3d/signal/imas.py
git commit -m "docs(ImasSignal): document layout modes and fix the stale example"
```

---

## Task 14: Full-suite verification

**Files:** none modified.

- [ ] **Step 1: Run the complete test suite the way CI does**

```bash
cd tests && pixi run fdp run ./testit ; cd ..
```

Expected: `OK`. Compare the skip count against the pre-change baseline —
unexpected new skips mean tests silently stopped running rather than
passing.

- [ ] **Step 2: Confirm the offline tests need no data access**

```bash
pixi run python -m pytest tests/test_imas_layout.py -q
```

Expected: all pass **without** the `fdp run` wrapper. This is the point of
putting the layout logic in pure functions — if this fails, the module has
picked up a hidden dependency on I/O.

- [ ] **Step 3: Verify the conda recipe builds**

```bash
bash recipe/run_build.sh 2>&1 | tail -30
```

Expected: build succeeds and the packaged test suite passes. This is what CI
runs, and it resolves `imas_composer` fresh from the channels rather than
from `pixi.lock` — which is precisely the resolution path that broke.

- [ ] **Step 4: Push and open the pull request**

```bash
git push -u origin feat/imas-composer-024-layout
gh pr create --title "Adapt ImasSignal to imas_composer 0.2.4" --body "$(cat <<'EOF'
imas_composer 0.2.4 reached conda-forge skipping 0.2.1-0.2.3 -- a 267-commit
jump that changed the public contract twice, leaving `main` unbuildable since
2026-08-03. Neither change is an upstream bug; both are deliberate redesigns.

- `electrons.density_thermal` was renamed to `electrons.density` (ion paths
  kept `density_thermal`)
- `core_profiles` moved to a unified GTIME axis with empty slots where a
  quantity has no data, so composed values arrive jagged

Adds a `layout=` kwarg (`compact`/`filled`/`ragged`/`awkward`) so callers
choose their consumption model, defaulting to `compact` for leaf paths
(restoring pre-0.2.4 shapes) and `filled` for prefix paths. Layout applies
only when `times` is a 1-D non-object array matching the outer length, which
structurally excludes channel and measurement axes.

Design: `docs/superpowers/specs/2026-08-14-imas-composer-024-adaptation-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Monitor CI to green**

```bash
gh pr checks --watch
```

Expected: all checks pass. If the conda build fails while local tests passed,
the cause is almost certainly dependency resolution differing from
`pixi.lock` — read the resolved `imas_composer` version in the build log
first.

---

## After this plan

These follow-ups are **out of scope here** and tracked separately:

1. **Rebase PR #33** (ptdata `ical` single-sourcing) onto this branch once it
   lands, then merge it.
2. **Tag `release-0.11.0`** carrying both changes.
3. **Bless in `fdp-core`.** `fdp-core` pins `imas_composer ==0.2` exactly, so
   `toksearch_d3d 0.11.0` and the `imas_composer` move must ship **together**
   or the metapackage is unsolvable.
4. **Scheduled CI across the stack** — no FDP repo has a `schedule:` trigger,
   so an upstream release can break a build with zero commits. This one sat
   red for eleven days.
5. **File the upstream scipy bug.** `imas_composer` 0.2.4 imports `scipy` at
   module top level in three `ids/` modules that `IDSFactory.__init__`
   eagerly imports, but `scipy` is only in the `[plots]` extra — a bare
   `pip install imas_composer` plus `ImasComposer()` raises
   `ModuleNotFoundError`.
