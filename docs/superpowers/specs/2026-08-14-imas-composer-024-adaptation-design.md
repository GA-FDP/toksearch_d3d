# Adapting `ImasSignal` to imas_composer 0.2.4 — Design

**Date:** 2026-08-14
**Status:** Approved, ready for planning
**Repo:** `toksearch_d3d`

## Problem

conda-forge published `imas_composer` 0.2.4, skipping 0.2.1–0.2.3. That is a
267-commit jump, and it changed the public contract in two ways. Because
`recipe/recipe.yaml` pinned `imas_composer >=0.2` with no ceiling, the conda
test environment resolved 0.2.4 while the local `pixi.lock` stayed at 0.2. The
result: `toksearch_d3d` `main` has been unbuildable since 2026-08-03, with
8 failures in `tests/test_imas_signal.py`, independent of any local change.

Neither change is an upstream bug. Both are deliberate redesigns.

### Change 1 — the electron density field was renamed

Upstream commit `fdf82a4` ("Remove the performative `_thermal` from
electrons.density", PR #50):

```
0.2      core_profiles.profiles_1d.electrons.density_thermal
0.2.4    core_profiles.profiles_1d.electrons.density
```

Verified as an exact mirror image — each version returns `[]` from
`get_supported_fields()` for the other version's name. Ion paths **kept**
`density_thermal`; only the electron field moved. Separately, the ion index
left the path (`ion.0.density_thermal` → `ion.density_thermal`).

`ImasSignal.__init__` (`toksearch_d3d/signal/imas.py:234`) treats an empty
`get_supported_fields()` result as "path does not exist" and raises
`ValueError: No supported fields found`.

### Change 2 — core_profiles moved to a jagged shared time base

0.2.4 places every `profiles_1d` quantity on one unified GTIME axis and leaves
an **empty array** where a given fit has no matching time. This is documented
in `core_profiles_zipfit.py`: "Slots in GTIME where ETEMPFIT has no matching
time are empty." The compose functions now return `ak.Array`.

Measured on shot 202161:

| field | outer | non-empty | empty |
|---|---|---|---|
| `electrons.density` | 237 | 228 | 9 |
| `electrons.temperature` | 237 | 228 | 9 |
| `ion.temperature` | 237 | **100** | 137 |
| `grid.rho_tor_norm` | 237 | 237 | 0 |

Electron density and temperature share an identical empty-slot mask; ion
temperature does not. Quantities genuinely have different time coverage, and
the shared axis is what makes them comparable.

`magnetics.ip` changed in a related but distinct way: 0.2.4 exposes **two**
ip measurements with different lengths (480256 and 44204 samples) plus a new
`ip.method_name` field, where 0.2 had one.

### The physics is unchanged

Stacking the 228 non-empty slices from 0.2.4 and comparing against 0.2's
`(228, 101)` array: identical shape, identical time base, values agreeing to
~1e-9 relative. The only numeric difference is a float32→float64 rounding of
the time axis (4.9e-4 ms). Only the container and the field name changed.

### Two kinds of raggedness

The current `_to_numpy` (`imas.py:39`) treats these identically, and they are
not the same thing:

- **Holes** — one common inner length plus empty slots (`core_profiles`:
  `{101}` and `{0}`). Recoverable to rectangular.
- **Genuinely ragged** — multiple distinct real lengths (`magnetics.ip`:
  480256 and 44204; ECE channels). Not recoverable.

## Goals

- Restore a green build on `main`.
- Support multiple models of consuming non-rectangular composed data, selected
  by the user rather than imposed.
- Never silently misattribute data to the wrong channel or time.
- Provide offline test coverage for the layout logic.

## Non-goals

- Supporting `imas_composer` 0.2 and 0.2.4 simultaneously. The floor moves to
  0.2.4; runtime version-switching of field names is explicitly rejected as it
  would make shapes depend on the installed version.
- A ragged xarray representation. `layout='filled'` plus the existing
  `split_by='channel'` + `join='outer'` path already cover the cases that
  motivated it.
- Changing `imas_composer` itself.

## Design

### The `layout=` kwarg

One new `ImasSignal` constructor kwarg:

```python
ImasSignal(ids_path, ..., layout='compact')   # leaf default
```

It replaces the existing `as_awkward` boolean, which becomes
`layout='awkward'`. `as_awkward` remains accepted for one release: passing it
emits a `DeprecationWarning`; passing **both** `as_awkward` and `layout`
raises `ValueError` rather than picking a winner.

### The axis rule

A composed value's outer axis is treated as **time**, and therefore eligible
for layout transformation, only when all four conditions hold:

1. `times` resolved to a **1-D non-object** array,
2. `len(times)` equals the composed value's outer length,
3. `split_by` is `None`,
4. no sibling entity-name array matches the outer length (`entity_hint` is
   False).

Otherwise the outer axis is an entity axis (channel, measurement) and the
value passes through untouched in every mode.

**Condition 4 was added after review** and is the one that makes this a
structural guarantee. Conditions 1 and 2 alone are not sufficient: the
original design claimed entity axes always fail condition 1 because their
`times` is per-entity, but `_resolve_dim_ids_path` falls back to the
IDS-level `<ids>.time` — a flat 1-D numeric array — whenever the sibling
`.time` does not resolve, and always for paths not ending in `.data` or
`.data_error_upper`. In that case only a length coincidence separated a
channel axis from a time axis. Demonstrated false positives: 48 per-channel
rows with `times = np.arange(48.)`, and 2 ip measurements with
`times = np.array([0., 1.])`, both returned True. "Came from the fallback"
cannot be used as the discriminator either, because `core_profiles`' genuine
time axis resolves through that same fallback.

Condition 4 asks a structural question instead: does a sibling
`name`/`identifier`/`method_name` array exist with one entry per outer entry?
If so the outer axis enumerates entities, not times. `ImasSignal` computes
this (it owns the I/O) and passes a bool, so `imas_layout` stays pure.

This is grounded in the data's own structure, measured:

| path | outer axis | `times` | eligible |
|---|---|---|---|
| `core_profiles.…electrons.density` | time | `(237,) float32` | yes |
| `magnetics.ip.data` | measurement | `(2,) object` | no |
| `ece.channel.t_e.data` | channel | `(48, 65536)` 2-D | no |

For the three shapes above, entity axes fail condition 1 because their `times`
is either an object array of per-entry time arrays or a 2-D per-channel array.
Condition 4 covers the remaining case, where `times` resolves to the flat
IDS-level array and condition 1 does not fire.

Together these make a channel axis un-compactable by construction rather than
by convention, so the positional `names[i]` mapping in `_split_by_channel`
stays correct. Dropping entries from a channel axis would shift every
channel's identity — the same class of silent corruption as the mdsip
tree-context bug.

### The four modes

Applied only when the axis rule says "time":

| mode | behavior |
|---|---|
| `compact` | drop slots whose inner array is empty; filter `data` and `times` in lockstep -- `times` is the only dim array known to be outer-parallel, so every other dim array (e.g. `rho`) passes through unfiltered even on a coincidental length match; convert naturally |
| `filled` | keep all slots; pad empty slots to the common inner length with NaN |
| `ragged` | no transformation — object array exactly as the composer produced it |
| `awkward` | raw `ak.Array`, no numpy conversion |

`compact` promises only "no empty slots" — **not** rectangularity.
Rectangularity is a consequence when one common inner length remains, via the
existing try-`np.asarray`-then-fall-back-to-object logic. This is why ECE and
Thomson need no special case: compaction is a no-op for them and they keep
returning object arrays exactly as today. `core_profiles` becomes rectangular
because one length remains, not because it was special-cased.

### Defaults

- **Leaf paths:** `compact`. Restores pre-0.2.4 shapes, so existing user
  scripts and the `CLAUDE.md` demo recipes keep working. `np.nanmax` and
  `fetch_as_xarray` work.
- **Prefix paths:** `filled`. A prefix fetch is a joint fetch, and jointness
  implies a shared axis.

Under `compact` each field lands on its own time base; fields are reconciled
with `align()` as with any other toksearch signal.

### Behavior matrix

| fetch kind | `compact` | `filled` | `ragged` | `awkward` |
|---|---|---|---|---|
| leaf, time axis | drop empties, filter `times` | NaN-pad to common length | untouched object array | raw `ak.Array` |
| leaf, entity axis | no-op | no-op | no-op | raw `ak.Array` |
| prefix | **raises** | shared axis, bare ndarrays | bare object arrays | raw `ak.Array`s |
| `split_by='channel'` | no-op | no-op | no-op | raw |

Prefix mode keeps its current bare-ndarray contract. Measured under 0.2, a
prefix gather of `core_profiles.profiles_1d` returns 15 leaves all at
`(228, 101)`, with `profiles_1d.time` present as a sibling leaf at `(228,)`.
Under `filled` that structure is preserved at 237. Under `compact` it would
break: `electrons.density` → 228, `ion.temperature` → 100, while the sibling
`time` leaf stays 237, matching none of them — hence the error.

### No `valid` key

Under `compact` the surviving `times` identifies which slices are real; under
`filled` NaN marks the gaps. A third channel carrying the same information is
one more thing to keep consistent, so it is not added.

### `fetch_as_xarray`

No new machinery. `compact` and `filled` yield rectangular arrays that flow
through the existing axis-matching code unchanged. `ragged` and `awkward`
continue to raise `NotImplementedError`, but the message gains the actionable
half it currently lacks — today it says "use `fetch()`" without mentioning
that `layout='filled'` makes the call work.

`fetch_as_xarray` continues to raise for prefix paths.

## Error handling

Three errors, all loud, none substituting a default -- plus one deliberate
no-op that resembles an error at first glance but isn't (superseded design;
see below).

1. **Renamed field.** `core_profiles.profiles_1d.electrons.density_thermal`
   reports the rename and notes that ion paths kept `density_thermal`, instead
   of the generic "No supported fields found" — which is indistinguishable
   from a typo. No aliasing: the old path does not silently resolve to the new
   one, because upstream dropped `_thermal` as a deliberate semantic decision.

2. **`compact` on a prefix path.** Raises, naming the divergent lengths it
   would produce and pointing at `filled`:

   ```
   ValueError: layout='compact' is not supported for prefix path
   'core_profiles.profiles_1d': leaves would land on divergent time
   bases (electrons.density -> 228, ion.temperature -> 100) while the
   sibling 'profiles_1d.time' leaf stays 237. Use layout='filled'
   (the prefix default), or fetch leaves individually.
   ```

3. **Unrecognized `layout=` value.** Raises. A typo'd mode must not fall back
   to a working default and silently return a different shape than requested —
   this is the `_ICAL_MAP.get(ical, Full)` failure mode.

### `filled` cannot fabricate: no-op, not a raise (superseded)

The original design had `filled` raise in the two cases where it cannot pad
— reproduced below, then corrected by review:

1. *Non-float time axis.* The axis rule passes but the inner arrays are
   integer or string typed, so NaN has no value to fill gaps with.
2. *No single common inner length.* The axis rule passes but non-empty slots
   have two or more distinct lengths, so there is nothing to pad to.

In practice this left the flagship `core_profiles.profiles_1d` prefix fetch
with no working default: once `entity_hint` correctly stops excusing every
`ion.*` leaf (a related review fix), `ion.rotation_frequency_tor`'s non-empty
rows are themselves ragged, landing on case 2, and the prefix `filled`
default raised for the field the whole feature was built to serve.

**Corrected rule:** in both cases, `filled` is a no-op instead of raising —
the value is returned as `_stack_or_object` would render it (an object array
when the slots don't share one shape), untouched rather than fabricated. This
is deliberately the *same* treatment entity axes already get: no-op does not
invent data, and the leaf keeps its outer length, so it stays index-aligned
with siblings that padding *does* fill, and the prefix contract holds.

`magnetics.ip` was never an instance of either case: its `times` is an object
array, so it fails the axis rule and is a no-op in every mode regardless of
this rule. Padding 44204 up to 480256 was never reachable — the axis rule
excludes it before layout is applied.

In **prefix** mode, where `filled` is the default, this means a leaf that
cannot be filled no-ops on its own rather than failing the whole gather:
every other fillable leaf in the batch still gets padded normally, and the
no-op leaf's untouched outer length keeps it aligned with them. The original
design's per-leaf `ValueError` naming that leaf (and `apply_layout_prefix`'s
try/except wrapper that produced it) no longer applies.

## Edge cases

- **Every slot empty**, `compact`: length-0 `data` and `times`. A legitimate
  "no data this shot" outcome, not an error.
- **No empty slots**: `compact` and `filled` are both no-ops and must agree
  exactly.
- **0-d scalars** (`ion.label`, `element.a`): fail the axis rule, pass through
  untouched in every mode.
- **Genuinely ragged or non-floating holey data**, `filled`: a no-op, same
  treatment as entity axes (see Error handling's `filled` no-op rule).

## File structure

**Create `toksearch_d3d/signal/imas_layout.py`.** The layout logic lives here
as pure functions over `(composed_value, times)` — no `ImasSignal` state, no
I/O. `imas.py` is already 615 lines and this is a separable concern. Purity is
what makes the interesting cases testable without shot data.

**Modify `toksearch_d3d/signal/imas.py`:**
- `__init__`: accept `layout=`, validate it, handle `as_awkward` deprecation,
  reject `compact` on prefix paths, detect the renamed field.
- `gather` / `_gather_prefix`: apply the selected layout via `imas_layout`.
- `fetch_as_xarray`: improve the ragged error message.

**Modify `toksearch_d3d/__init__.py`:** line 138 uses the old
`density_thermal` path in its documented example.

**Modify `tests/test_imas_signal.py`** and add
`tests/test_imas_layout.py`.

## Testing

**Unit tests (`tests/test_imas_layout.py`), no shot data required:**

- holes → `compact` → rectangular, with `times` filtered in lockstep
- holes → `filled` → NaN in exactly the empty slots
- genuinely ragged → `compact` is a no-op
- all slots empty → length-0 result
- no empty slots → `compact` and `filled` agree exactly
- object `times` (entity axis) → untouched in every mode
- 2-D `times` (channel axis) → untouched in every mode
- genuinely ragged / non-floating holey data → `filled` is a no-op
- each of the three errors

The existing `test_imas_signal.py` is entirely shot-data dependent. Adding
this offline layer avoids widening the same coverage gap already open on
ptdata's `ical=2` path.

**Integration tests (`tests/test_imas_signal.py`):**

- update the five `electrons.density_thermal` references to
  `electrons.density` — four call sites (lines 373, 389, 458, 470) plus a
  docstring (line 372)
- **fix `magnetics.ip`**: it currently asserts `(1, N)` 2-D, but 0.2.4 gives
  two measurements of 480256 and 44204 samples. The correct assertion is a
  2-element object array. This test currently passes for the wrong reason and
  would keep passing if fields were merely renamed.
- add coverage for each layout mode against real data

**Verification step:** confirm each new test fails when compaction is
disabled. Every bug found in this repo group over the past week was a check
that could not fail — the concurrency test that opened one shot,
`doctest::Approx` on a bit-exactness claim, a leak counter matching a dead
process name. These tests must be shown to bite.

## Documentation

- `ImasSignal` docstring: document all four layout modes with the shapes each
  produces, the leaf-vs-prefix default split, and the axis rule.
- `toksearch_d3d/__init__.py:138`: update the stale example path.
- Check `.claude/skills/toksearch-d3d-imas/` for stale field names.
- Verify the `CLAUDE.md` βN/NBI demo recipe still holds.
  `nbi.unit.power_launched.data` is an entity axis, so `compact` is a no-op
  there and the recipe should be unaffected — to be confirmed, not assumed.

## Pinning

`imas_composer >=0.2.4,<0.3` in both `recipe/recipe.yaml` and `pixi.toml`.

**Caveat, stated plainly:** this ceiling would **not** have caught the present
break, because 0.2.4 < 0.3. Upstream shipped two contract changes in a patch
release, so a semver-shaped ceiling is weak protection. It is a cheap backstop
against a genuine 0.3 and nothing more.

The real gap is not the ceiling at all. `.github/workflows/conda_build.yaml`
triggers only on `push` to `main`, `release-*` tags, and pull requests — there
is no `schedule:`. This break involved no commit: a third party published a
release and the conda test environment, which resolves fresh from the channels
regardless of `pixi.lock`, picked it up. The build that was green on
2026-08-03 fails today on unmodified source. That class of failure is
invisible to a commit-triggered CI by construction.

Adding a scheduled run is deliberately **out of scope here**. It is orthogonal
to 0.2.4 — it would be wanted even if 0.2.4 had never happened — and it is not
a `toksearch_d3d` question: every repo in the stack declares unpinned recipe
floors, so `ptdata`, `toksearch`, and `fdp` share the same blind spot. Fixing
it in one repo addresses a fraction of the exposure. Tracked as a separate
cross-repo follow-up.

## Release coordination

`fdp-core` pins `imas_composer ==0.2` exactly. A `toksearch_d3d 0.11.0` with a
`>=0.2.4` floor therefore **cannot be blessed** until `fdp-core` moves
`imas_composer` in the same bless — shipping `toksearch_d3d` alone would make
the metapackage unsolvable.

Ordering:

1. This work lands on `main` (turns CI green).
2. PR #33 (the ptdata `ical` single-sourcing fix) rebases onto it and merges.
3. One `release-0.11.0` tag carries both.
4. The `fdp-core` bless moves `imas_composer` and `toksearch_d3d` together.

## Rejected alternatives

- **Pin `<0.2.4` and stay on 0.2.** Freezes `toksearch_d3d` off 267 commits
  and four new IDSs (`charge_exchange`, `interferometer`, `pf_active`,
  `summary`) to preserve a field name upstream intentionally removed. No
  upstream fix is coming, because nothing upstream is broken.
- **Compact as a blanket rule across all axes.** Would shift channel identity
  on entity axes.
- **A `valid` boolean key alongside `data`.** Redundant with `times` under
  `compact` and with NaN under `filled`.
- **Masked arrays as the primary representation.** Dtype-preserving, but
  masks are silently dropped by `np.stack`, xarray, and most HDF5 writers.
- **Aliasing `density_thermal` → `density`.** Cannot be a blind rewrite, since
  ion paths legitimately keep `density_thermal`; and it would paper over a
  deliberate upstream semantic change.

## Upstream issue to file (separate from this work)

`imas_composer` 0.2.4 imports `scipy` at module top level in
`core_profiles_zipfit.py`, `equilibrium.py`, and `interferometer.py`, and
`IDSFactory.__init__` eagerly imports every module in `ids/`. But `scipy`
appears only in the `[plots]` optional-dependency extra, not in core
`dependencies`. A bare `pip install imas_composer` followed by
`ImasComposer()` therefore raises `ModuleNotFoundError`. This is latent for
FDP because `toksearch` pulls `scipy` in transitively. It is unrelated to the
failures addressed here.
