---
name: toksearch-d3d-ptdata
description: PtDataSignal and RDataSignal for DIII-D PTDATA diagnostics — constructor args, calibration, times in milliseconds, Pipeline usage, and xarray conversion
user-invocable: false
license: Apache-2.0
compatibility: Claude Code
metadata:
  author: GA-FDP
  version: "1.0"
  url: https://ga-fdp.github.io/toksearch/
---

# TokSearch DIII-D PTData Skill

## Description

`PtDataSignal` retrieves DIII-D time-series diagnostic data from the PTDATA store and fits naturally into the standard TokSearch `Pipeline` workflow. It wraps the `ptdata.PtDataFetcher` library and exposes the standard `Signal` interface.

```python
from toksearch_d3d import PtDataSignal, RDataSignal
```

## When to Use

- Fetching DIII-D diagnostic time series (plasma current, density, power, etc.)
- Any signal available through the PTDATA point name system
- Accessing DIII-D operations metadata via the `RDATA` lookup array

## A Simple Fetch

The first argument is the PTDATA point name (case-insensitive):

```python
sig = PtDataSignal('ip')
result = sig.fetch(202161)

print(result['data'].shape)   # (n_time,)
print(result['times'][:5])    # ms: [0.  0.5  1.  1.5  2. ]
print(result['units'])        # {'data': 'A', 'times': 'ms'}
```

`fetch` returns a plain dict with:
- `'data'`: numpy array of signal values
- `'times'`: numpy array of time points in **milliseconds**
- `'units'`: dict with unit strings (unless `fetch_units=False`)

Times are always in **milliseconds**, matching the MDSplus convention used elsewhere in TokSearch.

## Constructor

```python
PtDataSignal(
    pointname,            # PTDATA point name (case-insensitive, required)
    remote=True,          # True = Pelican/OSDF; False = local athena
    ical=1,               # 1 = calibrated (default); 0 = raw counts
    keep_header=False,    # include raw PTDATA header dict in result
    fetch_times=True,     # include 'times' array
    fetch_units=True,     # include 'units' dict
)
```

## Using `PtDataSignal` in a `Pipeline`

`PtDataSignal` is a `Signal` subclass and slots directly into a `Pipeline`:

```python
import numpy as np
from toksearch import Pipeline
from toksearch_d3d import PtDataSignal

ip_sig   = PtDataSignal('ip')
dens_sig = PtDataSignal('dssdenest')

shots = [202159, 202160, 202161]
pipeline = Pipeline(shots)
pipeline.fetch('ip',   ip_sig)
pipeline.fetch('dens', dens_sig)

@pipeline.map
def calc_max_ip(rec):
    rec['max_ip'] = float(np.max(np.abs(rec['ip']['data'])))

pipeline.keep(['shot', 'max_ip', 'dens'])
records = pipeline.compute_serial()

for rec in records:
    print(rec['shot'], rec['max_ip'])
```

```
202159 1423187.5
202160 1418203.2
202161 1401922.8
```

## Calibration (`ical`)

By default data are returned calibrated (`ical=1`). Pass `ical=0` for raw counts:

```python
raw_sig = PtDataSignal('ip', ical=0)
result  = raw_sig.fetch(202161)
```

## Omitting the Time Array (`fetch_times=False`)

When you need data values without the time base — for example, a scalar:

```python
sig = PtDataSignal('btor', fetch_times=False)
result = sig.fetch(202161)
print(result.keys())   # dict_keys(['data', 'units'])
```

## Converting to xarray (`fetch_as_xarray`)

Returns an `xr.DataArray` with a `'times'` coordinate:

```python
da = PtDataSignal('ip').fetch_as_xarray(202161)
# <xarray.DataArray (times: 3001)>
# Coordinates:
#   * times  (times) float64 0.0 0.5 1.0 ... 1500.0
# Attributes:
#     units: A
```

## Inspecting the Raw Header (`keep_header`)

```python
sig = PtDataSignal('ip', keep_header=True)
result = sig.fetch(202161)
print(result['header'])   # raw PTDATA header dict (metadata, calibration coefficients)
```

## Remote vs. Local (`remote`)

```python
# Remote (default) — uses Pelican/OSDF, sets PTDATA_LOC=1
sig = PtDataSignal('ip', remote=True)

# Local — uses athena ptserver, sets PTDATA_LOC=0
sig = PtDataSignal('ip', remote=False)
```

The `fdp run` command sets `PTDATA_LOC=1` automatically. In FDP workflows, always use `remote=True` (the default) or rely on `fdp run` to configure the environment.

## `RDataSignal`

`RDataSignal` fetches the `RDATA` point — a DIII-D operations lookup array. It has no time array and no units:

```python
from toksearch_d3d import RDataSignal

rdata_sig = RDataSignal()
result = rdata_sig.fetch(202161)

print(result['data'].shape)   # (n_radii,)
print(result.keys())          # dict_keys(['data'])
```

`RDataSignal` takes the same optional `remote` and `keep_header` arguments as `PtDataSignal`.

```python
# In a Pipeline
pipeline.fetch('rdata', RDataSignal())
```

## Common PTDATA Point Names

| Point name | Description |
|-----------|-------------|
| `ip` | Plasma current (A) |
| `dssdenest` | Line-averaged electron density estimate |
| `btor` | Toroidal magnetic field |
| `pinj` | Neutral beam injection power |
| `echpwr` | ECH power |
| `prad` | Radiated power |
| `wmhd` | MHD stored energy |

Point names are case-insensitive.

## Best Practices

- Use `remote=True` (default) for all FDP/Pelican workflows
- Times are in milliseconds — consistent with `MdsSignal` and `ImasSignal`
- For scalars or slowly-varying quantities, consider `fetch_times=False` to avoid an unnecessary array
- Use `keep_header=True` only when you need calibration metadata for debugging
