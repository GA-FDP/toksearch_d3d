# Fetching IMAS Data with `ImasSignal`

`ImasSignal` exposes DIII-D diagnostic and equilibrium data through the
[IMAS](https://imas.iter.org/) IDS schema via the `imas_composer` backend,
while fitting naturally into the standard TokSearch `Pipeline` workflow.

```python
from toksearch_d3d import ImasSignal
```

---

## A simple scalar signal

The first argument to `ImasSignal` is a dot-separated IMAS path.  The
following example fetches the plasma current stored in the `equilibrium` IDS:

```python
ip_sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')
result = ip_sig.fetch(202161)
```

`fetch` returns a plain dict.  By default it always includes `'data'` and,
when the IMAS time array can be found, `'times'`:

```python
print(result['data'].shape)   # (n_time,)
print(result['times'][:5])    # times in milliseconds
```

```
(303,)
[ 100.  140.  160.  180.  200.]
```

Times are returned in **milliseconds** by default, matching the PTDATA and
MDSplus convention used elsewhere in TokSearch.  See [Changing time
units](#changing-time-units) below if you prefer raw IMAS seconds.

---

## Using `ImasSignal` in a `Pipeline`

`ImasSignal` is a `Signal` subclass, so it slots directly into a `Pipeline`
with no special handling:

```python
import numpy as np
from toksearch import Pipeline
from toksearch_d3d import ImasSignal

ip_sig  = ImasSignal('equilibrium.time_slice.global_quantities.ip')
q95_sig = ImasSignal('equilibrium.time_slice.global_quantities.q_95')

shots = [202159, 202160, 202161]
pipeline = Pipeline(shots)
pipeline.fetch('ip',  ip_sig)
pipeline.fetch('q95', q95_sig)

@pipeline.map
def calc_max_ip(rec):
    rec['max_ip'] = float(np.max(np.abs(rec['ip']['data'])))

pipeline.keep(['max_ip', 'q95'])

records = pipeline.compute_serial()
for rec in records:
    print(rec['shot'], rec['max_ip'])
```

```
202159 1423187.5
202160 1418203.2
202161 1401922.8
```

---

## Profile data

Many IDS fields are profiles — one value per spatial grid point at each time
step.  `ImasSignal` returns them as 2-D numpy arrays:

```python
q_sig = ImasSignal('equilibrium.time_slice.profiles_1d.q')
result = q_sig.fetch(202161)

print(result['data'].shape)   # (n_time, n_rho)
print(result['times'].shape)  # (n_time,)
```

```
(303, 129)
(303,)
```

The `'times'` dim is resolved automatically using the same IMAS path with the
`time` component substituted in.  For `profiles_1d.q` there is no sibling
`profiles_1d.time`, so the fallback `equilibrium.time` is used instead.

---

## Ragged data

Some IDS fields are ragged — the inner array length varies across the outer
axis.  The most common case is Thomson scattering channel data, where each
channel may have a different number of time points.  `ImasSignal` returns these
as a **numpy object array** whose elements are 1-D numpy arrays:

```python
ne_sig = ImasSignal('thomson_scattering.channel.n_e.data')
result  = ne_sig.fetch(202161)

print(result['data'].dtype)        # object
print(result['data'].shape)        # (n_channels,)
print(result['data'][0].shape)     # (n_time_for_channel_0,)
```

```
object
(68,)
(340,)
```

---

## Discovering which fields are available

`list_imas_fields()` returns the IDS paths `imas_composer` can compose, so you
can check a path before building a pipeline around it:

```python
from toksearch_d3d import list_imas_fields

fields = list_imas_fields()          # every IDS
fields = list_imas_fields('ece')     # one IDS
```

Pass an existing `ImasComposer` as `composer=` to reuse it rather than
constructing a new one.

---

## Fetching all fields under a prefix

Instead of a full leaf path, you can pass a **dotted prefix** such as an IDS
name or a partial path.  `ImasSignal` discovers all supported leaf fields under
that prefix and fetches them in a single batched compose call:

```python
sig = ImasSignal('equilibrium.time_slice.global_quantities')
result = sig.fetch(202161)
```

`result` is a plain dict keyed by full leaf path, each value a numpy array:

```python
print(list(result.keys())[:3])
# ['equilibrium.time_slice.global_quantities.ip',
#  'equilibrium.time_slice.global_quantities.q_95',
#  'equilibrium.time_slice.global_quantities.li_3']

print(result['equilibrium.time_slice.global_quantities.ip'].shape)  # (n_time,)
```

Any prefix depth works:

```python
ece_all = ImasSignal('ece').fetch(202161)         # every ECE field
ece_ch  = ImasSignal('ece.channel').fetch(202161) # only channel subtree
```

**Restrictions for prefix paths**: supplementary dimension arrays (`dims`),
`split_by`, and `fetch_as_xarray()` are not supported — prefix mode returns
plain arrays only.

---

## Controlling supplementary dimension arrays with `dims`

The `dims` keyword controls which supplementary arrays are returned alongside
`'data'`.  Each key becomes a field in the result dict; each value is either
`'auto'` or an explicit IMAS path.

**`'auto'` resolution** (the default):

1. If `ids_path` ends in `.data` or `.data_error_upper`, `ImasSignal` strips
   that suffix and appends the dimension name, then traverses upward toward the
   IDS top level until a resolvable path is found.  For example, for
   `ids_path='ece.channel.t_e.data'` and `dim='times'`, the candidates tried
   in order are `ece.channel.t_e.time` → `ece.channel.time` → `ece.time`.
2. Otherwise the fallback `{ids_name}.{dim_name}` is used (e.g.
   `equilibrium.time`).

The default is `dims={"times": "auto"}`.  To fetch additional dimensions, pass
extra entries:

```python
sig = ImasSignal(
    'thomson_scattering.channel.position.r',
    dims={
        'times': 'auto',
        'z':     'thomson_scattering.channel.position.z',
    },
)
result = sig.fetch(202161)
print(result.keys())   # dict_keys(['data', 'times', 'z'])
```

To suppress the `'times'` array entirely, pass an empty dict:

```python
sig = ImasSignal(
    'equilibrium.time_slice.global_quantities.ip',
    dims={},
)
result = sig.fetch(202161)
print(result.keys())   # dict_keys(['data'])
```

---

## Changing time units

Times are scaled by the values in `dim_scales`.  The default is
`{'times': 1000.0}`, which converts IMAS seconds to milliseconds.  To keep
raw IMAS seconds:

```python
sig = ImasSignal(
    'equilibrium.time_slice.global_quantities.ip',
    dim_scales={'times': 1.0},
)
result = sig.fetch(202161)
print(result['times'][:3])   # seconds
```

```
[0.1  0.14 0.16]
```

`dim_scales` applies to any dimension, not just `'times'`.

---

## Controlling shape with `layout=`

Ragged fields (e.g. equilibrium boundary outlines where the number of points
varies per time slice, or `core_profiles` quantities that imas_composer
places on a single unified time axis with empty slots where a quantity has
no data) can be shaped four ways via the `layout=` kwarg:

- `'compact'` (default for **leaf** paths) — drop empty slots, filtering
  `times` in lockstep.  Becomes a rectangular `ndarray` when one common inner
  length remains; otherwise a numpy object array, same as the historical
  default.
- `'filled'` (default for **prefix** paths) — keep every slot, padding empty
  ones with NaN so every leaf of a joint prefix fetch stays index-aligned to
  one shared time axis.
- `'ragged'` — no transformation; the object array exactly as imas_composer
  produced it, empty slots included.
- `'awkward'` — the raw `ak.Array`, with no numpy conversion:

  ```python
  import awkward as ak
  from toksearch_d3d import ImasSignal

  sig = ImasSignal(
      'equilibrium.time_slice.boundary.outline.r',
      layout='awkward',
  )
  result = sig.fetch(202161)

  print(type(result['data']))   # <class 'awkward.highlevel.Array'>
  print(result['data'].type)    # var * float64  (ragged)
  ```

`layout` applies **only** when the outer axis is provably a time axis (see
the `ImasSignal` docstring for the exact rule); channel and measurement axes
(`ece.channel.t_e.data`, `magnetics.ip.data`) pass through untouched in every
mode.

**`as_awkward` is deprecated** in favor of `layout='awkward'`.
`as_awkward=True` still works and is exactly equivalent to
`layout='awkward'`, but emits a `DeprecationWarning`; passing both
`as_awkward` and `layout` raises `ValueError`. `as_awkward=False` is
equivalent to leaving `layout` unset (the leaf/prefix default applies).

`layout='awkward'` (and the deprecated `as_awkward=True`) also work with
prefix paths:

```python
sig = ImasSignal('equilibrium.time_slice.global_quantities', layout='awkward')
result = sig.fetch(202161)
# Each value is an ak.Array or np.ndarray depending on the field.
```

---

## Channel-split data with `split_by='channel'`

For IDS paths indexed over a `channel` axis, `split_by='channel'` splits the
composed array along that axis and returns a plain dict keyed by channel name
(or integer index when names are unavailable).  Each entry contains `'data'`,
`'units'`, and a slice of every resolved `dims` array:

```python
ne_sig = ImasSignal(
    'thomson_scattering.channel.n_e.data',
    split_by='channel',
    dims={
        'times': 'auto',
        'r':     'thomson_scattering.channel.position.r',
        'z':     'thomson_scattering.channel.position.z',
    },
    units={'data': 'm^-3', 'times': 'ms', 'r': 'm', 'z': 'm'},
)

result = ne_sig.fetch(202161)
```

`result` is now a dict of per-channel entries:

```python
print(list(result.keys())[:3])
# ['TS_core_r+0_0', 'TS_core_r+0_1', 'TS_core_r+0_2']

ch = result['TS_core_r+0_0']
print(ch['data'].shape)    # (n_time,)
print(ch['times'][:3])     # ms
print(ch['r'])             # scalar R position in metres
print(ch['z'])             # scalar Z position in metres
print(ch['units'])
```

```
(340,)
[100. 105. 110.]
1.272
0.0
{'data': 'm^-3', 'times': 'ms', 'r': 'm', 'z': 'm'}
```

This format is convenient for converting to a `pandas.DataFrame` or an
`xarray.Dataset` keyed by channel.

---

## Converting to xarray with `fetch_as_xarray`

`ImasSignal` overrides `fetch_as_xarray` to return sensible xarray objects for
all supported data shapes.

**Scalar and profile signals** return an `xr.DataArray`.  Dimension names are
taken from resolved `dims` entries; any data axis without a matching dim array
gets a generic `'dim_N'` label:

```python
ip_sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')
da = ip_sig.fetch_as_xarray(202161)
# <xarray.DataArray (times: 303)>
# Coordinates:
#   * times  (times) float64 100.0 140.0 ... 6380.0

ne_sig = ImasSignal('core_profiles.profiles_1d.electrons.density')
da = ne_sig.fetch_as_xarray(200000)
# <xarray.DataArray (times: 121, dim_1: 332)>
```

For the 2-D case, you can name the second axis by adding an explicit entry to
`dims`:

```python
ne_sig = ImasSignal(
    'core_profiles.profiles_1d.electrons.density',
    dims={
        'times': 'auto',
        'rho':   'core_profiles.profiles_1d.grid.rho_tor_norm',
    },
)
da = ne_sig.fetch_as_xarray(200000)
# <xarray.DataArray (times: 121, rho: 332)>
```

**Channel-split signals** (`split_by='channel'`) return an `xr.Dataset` with
one variable per channel.  Channels are merged with `join="outer"`, so the
dataset has the **union** of all channels' time coordinates — consistent with
how `Pipeline.fetch_dataset` combines signals with different time bases.
Channels that have no data at a given time are `NaN` there:

```python
ne_sig = ImasSignal(
    'thomson_scattering.channel.n_e.data',
    split_by='channel',
    dims={'times': 'auto'},
    units={'data': 'm^-3', 'times': 'ms'},
)
ds = ne_sig.fetch_as_xarray(202161)
# <xarray.Dataset>
# Dimensions:  (times: N)
# Coordinates:
#   * times    (times) float64 ...
# Data variables:
#     TS_core_r+0_0  (times) float64 ...
#     TS_core_r+0_1  (times) float64 ...
#     ...
```

If a uniform, gap-free time base is needed, call `Pipeline.align()` on the
dataset after building it.

### Known limitations

- **Ragged data** (`split_by=None`, e.g. `thomson_scattering.channel.n_e.data`
  without `split_by`): raises `NotImplementedError`.  Use `fetch()` to retrieve
  the raw dict with the object array.

- **Ambiguous axis assignment for N-D data**: each 1-D dim array is matched to
  the first unused data axis of equal length.  If two axes have the same size
  the pairing may be wrong — add explicit paths to `dims`, or use `fetch()` and
  build the `DataArray` yourself.

- **Heterogeneous time bases with `split_by='channel'`**: channels that record
  at different times (e.g. Thomson scattering) will have `NaN` at times where
  they have no measurement.  Use `Pipeline.align()` to interpolate to a common
  grid if needed.

- **Prefix paths**: raises `NotImplementedError`.  Use `fetch()` to retrieve
  the dict of arrays.

---

## Sharing an `ImasComposer` across signals

Each `ImasSignal` constructs an `ImasComposer` internally by default.  When
fetching several IDS paths from the same IDS, it is more efficient to create
one `ImasComposer` and pass it to each signal — the mapper tables are only
initialised once:

```python
from imas_composer import ImasComposer
from toksearch_d3d import ImasSignal

composer = ImasComposer(efit_tree='EFIT01', profiles_tree='ZIPFIT01')

ip_sig = ImasSignal(
    'equilibrium.time_slice.global_quantities.ip',
    composer=composer,
)
q95_sig = ImasSignal(
    'equilibrium.time_slice.global_quantities.q_95',
    composer=composer,
)
li_sig = ImasSignal(
    'equilibrium.time_slice.global_quantities.li_3',
    composer=composer,
)
```

All three signals now share a single `ImasComposer` instance.  This is the
recommended pattern when building a `Pipeline` with many equilibrium quantities.

---

## Specifying a data location

By default, `ImasSignal` resolves MDSplus trees from environment variables (the
same way `MdsSignal` does).  The `location` keyword accepts the same formats
as `MdsSignal`:

```python
# Local trees at a specific path
sig = ImasSignal('equilibrium.time_slice.global_quantities.ip',
                 location='/path/to/trees')

# Remote MDSplus server
sig = ImasSignal('equilibrium.time_slice.global_quantities.ip',
                 location='remote://atlas.gat.com')
```

When using the FDP/Pelican stack the environment variables are set up
automatically by the `fdp run` command, so `location` can be left as the
default `None`.

---

## Non-equilibrium IDS sources

`ImasSignal` is not limited to equilibrium quantities.  Any IDS supported by
`imas_composer` can be accessed in the same way.  A few examples:

```python
# ECE electron temperature (channel-indexed)
ece_te = ImasSignal('ece.channel.t_e.data')

# TF vacuum toroidal field
tf_sig = ImasSignal('tf.b_field_tor_vacuum_r')

# Magnetics — plasma current
mag_ip = ImasSignal('magnetics.ip.data')

# Core profiles — electron density radial profile
ne_prof = ImasSignal('core_profiles.profiles_1d.electrons.density')
```

All of these are fetched and composed the same way as the equilibrium examples
above.
