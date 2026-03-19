---
name: toksearch-d3d-imas
description: ImasSignal for DIII-D IMAS IDS data — leaf/prefix paths, ragged arrays, channel splitting, dimension control, and shared ImasComposer
user-invocable: false
license: Apache-2.0
compatibility: Claude Code
metadata:
  author: GA-FDP
  version: "1.0"
  url: https://ga-fdp.github.io/toksearch/
---

# TokSearch DIII-D ImasSignal Skill

## Description

`ImasSignal` exposes DIII-D diagnostic and equilibrium data through the [IMAS](https://imas.iter.org/) IDS schema via the `imas_composer` backend, while fitting into the standard TokSearch `Pipeline` workflow.

> **Experimental**: `ImasSignal` and the `imas_composer` backend are under active development. The API (constructor arguments, return formats, and supported IDS paths) is likely to change in future releases.

```python
from toksearch_d3d import ImasSignal
```

## When to Use

- Fetching DIII-D equilibrium, profile, and diagnostic data via the IMAS schema
- When you need ITER-standard data representations (IDS paths)
- When accessing Thomson scattering, ECE, magnetics, or core profiles data

## A Simple Scalar Signal

The first argument is a dot-separated IMAS path. The following fetches plasma current from the `equilibrium` IDS:

```python
ip_sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')
result = ip_sig.fetch(202161)

print(result['data'].shape)   # (n_time,)
print(result['times'][:5])    # ms: [100. 140. 160. 180. 200.]
```

`fetch` returns a plain dict with `'data'` and, by default, `'times'` in **milliseconds**.

## Using `ImasSignal` in a `Pipeline`

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

pipeline.keep(['shot', 'max_ip', 'q95'])
records = pipeline.compute_serial()
```

## Profile Data

Many IDS fields are profiles — one value per spatial grid point at each time step. `ImasSignal` returns them as 2-D numpy arrays:

```python
q_sig = ImasSignal('equilibrium.time_slice.profiles_1d.q')
result = q_sig.fetch(202161)

print(result['data'].shape)   # (n_time, n_rho)
print(result['times'].shape)  # (n_time,)
```

The `'times'` dimension is resolved automatically. For `profiles_1d.q` there is no sibling `profiles_1d.time`, so `equilibrium.time` is used as the fallback.

## Ragged Data

Some IDS fields are ragged — the inner array length varies across the outer axis (e.g. Thomson scattering channels each with a different number of time points). `ImasSignal` returns these as a **numpy object array**:

```python
ne_sig = ImasSignal('thomson_scattering.channel.n_e.data')
result  = ne_sig.fetch(202161)

print(result['data'].dtype)        # object
print(result['data'].shape)        # (n_channels,)
print(result['data'][0].shape)     # (n_time_for_channel_0,)
```

## Fetching All Fields Under a Prefix

Pass a **dotted prefix** instead of a full leaf path. `ImasSignal` discovers all supported leaf fields and fetches them in a single batched compose call:

```python
sig = ImasSignal('equilibrium.time_slice.global_quantities')
result = sig.fetch(202161)

print(list(result.keys())[:3])
# ['equilibrium.time_slice.global_quantities.ip',
#  'equilibrium.time_slice.global_quantities.q_95',
#  'equilibrium.time_slice.global_quantities.li_3']
```

Any prefix depth works:

```python
ece_all = ImasSignal('ece').fetch(202161)          # every ECE field
ece_ch  = ImasSignal('ece.channel').fetch(202161)  # only channel subtree
```

**Restrictions for prefix paths**: `dims`, `split_by`, and `fetch_as_xarray()` are not supported — prefix mode returns plain arrays only.

## Controlling Dimension Arrays (`dims`)

The `dims` kwarg controls which supplementary arrays accompany `'data'`:

```python
# Default: resolve 'times' automatically
sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')
# result has 'data' and 'times'

# Add an extra spatial dimension
sig = ImasSignal(
    'thomson_scattering.channel.position.r',
    dims={
        'times': 'auto',
        'z':     'thomson_scattering.channel.position.z',
    },
)
result = sig.fetch(202161)
print(result.keys())   # dict_keys(['data', 'times', 'z'])

# Suppress times entirely
sig = ImasSignal(
    'equilibrium.time_slice.global_quantities.ip',
    dims={},
)
result = sig.fetch(202161)
print(result.keys())   # dict_keys(['data'])
```

**`'auto'` resolution**: strips `.data` suffix and traverses upward until a resolvable time path is found. For `ece.channel.t_e.data`, the candidates tried are `ece.channel.t_e.time` → `ece.channel.time` → `ece.time`.

## Changing Time Units

Default `dim_scales={'times': 1000.0}` converts IMAS seconds to milliseconds. For raw IMAS seconds:

```python
sig = ImasSignal(
    'equilibrium.time_slice.global_quantities.ip',
    dim_scales={'times': 1.0},
)
result = sig.fetch(202161)
print(result['times'][:3])   # seconds: [0.1  0.14 0.16]
```

## Channel-Split Data (`split_by='channel'`)

For IDS paths indexed over a `channel` axis, `split_by='channel'` splits along that axis and returns a dict keyed by channel name:

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
print(list(result.keys())[:3])
# ['TS_core_r+0_0', 'TS_core_r+0_1', 'TS_core_r+0_2']

ch = result['TS_core_r+0_0']
print(ch['data'].shape)   # (n_time,)
print(ch['times'][:3])    # ms
print(ch['r'])            # scalar R position in metres
print(ch['units'])        # {'data': 'm^-3', 'times': 'ms', 'r': 'm', 'z': 'm'}
```

## Converting to xarray (`fetch_as_xarray`)

**Scalar and profile signals** return an `xr.DataArray`:

```python
ip_sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')
da = ip_sig.fetch_as_xarray(202161)
# <xarray.DataArray (times: 303)>
```

```python
# Name the spatial axis explicitly
ne_sig = ImasSignal(
    'core_profiles.profiles_1d.electrons.density_thermal',
    dims={
        'times': 'auto',
        'rho':   'core_profiles.profiles_1d.grid.rho_tor_norm',
    },
)
da = ne_sig.fetch_as_xarray(200000)
# <xarray.DataArray (times: 121, rho: 332)>
```

**Channel-split signals** return an `xr.Dataset` with one variable per channel:

```python
ne_sig = ImasSignal(
    'thomson_scattering.channel.n_e.data',
    split_by='channel',
    dims={'times': 'auto'},
    units={'data': 'm^-3', 'times': 'ms'},
)
ds = ne_sig.fetch_as_xarray(202161)
# <xarray.Dataset> with variables TS_core_r+0_0, TS_core_r+0_1, ...
```

**Known limitations**:
- Ragged data (`split_by=None`) and prefix paths raise `NotImplementedError` in `fetch_as_xarray`; use `fetch()` instead

## Returning Awkward Arrays (`as_awkward`)

For ragged fields, pass `as_awkward=True` to get a native `ak.Array`:

```python
import awkward as ak
from toksearch_d3d import ImasSignal

sig = ImasSignal(
    'equilibrium.time_slice.boundary.outline.r',
    as_awkward=True,
)
result = sig.fetch(202161)
print(type(result['data']))   # <class 'awkward.highlevel.Array'>
print(result['data'].type)    # var * float64
```

## Sharing an `ImasComposer`

Each `ImasSignal` constructs an `ImasComposer` internally by default. When fetching several fields from the same IDS, sharing one composer avoids repeated initialisation of the mapper tables:

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

This is the recommended pattern when building a `Pipeline` with many equilibrium quantities.

## Specifying a Data Location

Leave `location=None` (default) when using `fdp run` — the environment is already configured:

```python
sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')  # location=None
```

To override:

```python
# Local trees
sig = ImasSignal('...', location='/path/to/trees')

# Remote MDSplus server
sig = ImasSignal('...', location='remote://atlas.gat.com')
```

## Example IDS Paths

```python
# Equilibrium
ImasSignal('equilibrium.time_slice.global_quantities.ip')
ImasSignal('equilibrium.time_slice.global_quantities.q_95')
ImasSignal('equilibrium.time_slice.profiles_1d.q')

# ECE electron temperature (channel-indexed)
ImasSignal('ece.channel.t_e.data')

# TF vacuum toroidal field
ImasSignal('tf.b_field_tor_vacuum_r')

# Magnetics plasma current
ImasSignal('magnetics.ip.data')

# Core profiles electron density radial profile
ImasSignal('core_profiles.profiles_1d.electrons.density_thermal')

# Thomson scattering (ragged / channel-indexed)
ImasSignal('thomson_scattering.channel.n_e.data')
```

## Discovering Available IMAS Fields

`list_imas_fields()` enumerates all IDS paths that `imas_composer` supports without
requiring knowledge of its internals.

```python
from toksearch_d3d import list_imas_fields

# All supported IDS names → fields
fields = list_imas_fields()
print(list(fields.keys()))
# ['core_profiles', 'ec_launchers', 'ece', 'equilibrium', 'gas_injection',
#  'magnetics', 'nbi', 'reflectometer_profile', 'tf', 'thomson_scattering', 'wall']

# Fields for a single IDS
for f in list_imas_fields('ece'):
    print(f)
# ece.channel.frequency.data
# ece.channel.identifier
# ece.channel.t_e.data
# ...
```

Pass a shared `ImasComposer` to avoid re-initialising mapper tables:

```python
from imas_composer import ImasComposer
from toksearch_d3d import list_imas_fields

composer = ImasComposer(efit_tree='EFIT02')
fields = list_imas_fields(composer=composer)
```

`list_imas_fields` raises `ValueError` for an unrecognised IDS name and is
unavailable if `imas_composer` is not installed (same optional-dependency guard
as `ImasSignal`).

## Best Practices

- Mark all code using `ImasSignal` as experimental — the API is under active development
- Share one `ImasComposer` across signals from the same IDS to reduce overhead
- Use prefix paths for broad exploration; use leaf paths for production pipelines
- For ragged channel data, prefer `split_by='channel'` for per-channel analysis
- Leave `location=None` in FDP workflows — `fdp run` sets up the MDSplus tree paths
