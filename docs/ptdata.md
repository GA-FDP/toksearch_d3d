# Fetching PTDATA Diagnostics with `PtDataSignal`

`PtDataSignal` retrieves DIII-D time-series diagnostic data from the PTDATA store,
fitting naturally into the standard TokSearch `Pipeline` workflow.

```python
from toksearch_d3d import PtDataSignal
```

---

## A simple fetch

The first argument is the PTDATA point name (case-insensitive).  `fetch` returns a
plain dict containing `'data'`, `'times'` (in milliseconds), and `'units'`:

```python
sig = PtDataSignal('ip')
result = sig.fetch(202161)

print(result['data'].shape)          # (n_time,)
print(result['times'][:5])           # ms
print(result['units'])
```

```
(3001,)
[   0.  0.5  1.   1.5  2. ]
{'data': 'A', 'times': 'ms'}
```

Times are returned in **milliseconds** by default, matching the MDSplus convention
used elsewhere in TokSearch.

---

## Using `PtDataSignal` in a `Pipeline`

`PtDataSignal` is a `Signal` subclass, so it slots directly into a `Pipeline`:

```python
import numpy as np
from toksearch import Pipeline
from toksearch_d3d import PtDataSignal

ip_sig  = PtDataSignal('ip')
dens_sig = PtDataSignal('dssdenest')

shots = [202159, 202160, 202161]
pipeline = Pipeline(shots)
pipeline.fetch('ip',   ip_sig)
pipeline.fetch('dens', dens_sig)

@pipeline.map
def calc_max_ip(rec):
    rec['max_ip'] = float(np.max(np.abs(rec['ip']['data'])))

pipeline.keep(['max_ip', 'dens'])

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

## Pinning a shot to a stored version

The DIII-D store keeps shots under explicit versions, and a pipeline can ask for
one. The version travels with the **shot**, not the signal: a single
`PtDataSignal` serves every shot in the pipeline, so putting the version on the
signal would mean "v2 of everything". Give the shot list dicts instead:

```python
pipeline = Pipeline([
    {'shot': 202159, 'version': 2},
    {'shot': 202160, 'version': 2},
    {'shot': 202161},                 # unpinned -- whatever the catalog says now
])
pipeline.fetch('ip', PtDataSignal('ip'))
```

`snapshot` names a catalog snapshot instead of a version number, and the two may
be given together or separately:

```python
Pipeline([{'shot': 202161, 'snapshot': 'catalog_20260901T000000'}])
```

**A pin is a guarantee, not a preference.** If the requested version cannot be
served you get an error in `record['errors']` -- never data from some other
version. This is deliberate: silently falling back would make a reproduction
run look successful while reading different bytes than the run it reproduces.

`version` and `snapshot` are reserved fields on the `Record`, alongside `shot`
and `errors`. They survive `keep()` and cannot be deleted, so a routine
`keep(['max_ip'])` in the middle of a pipeline cannot strip the provenance that
says which bytes produced `max_ip`:

```python
records = pipeline.compute_serial()
rec = records[0]
print(rec['shot'], rec['version'])     # still there after keep(['max_ip'])
```

Reading them back is how you record what a run actually used. Note that
`Record.get` requires an explicit default:

```python
version = rec.get('version', None)     # not rec.get('version')
```

Requires `toksearch >= 2.12.0` and `ptdata >= 2.6.0`; `toksearch_d3d 0.13.0`
floors both, so a correct environment cannot silently drop the pin.

---

## Calibration (`ical`)

By default data are returned in physics units (`ical=1`).  Pass `ical=0` to
retrieve raw digitizer counts:

```python
raw_sig = PtDataSignal('ip', ical=0)
result  = raw_sig.fetch(202161)
```

The full set of legacy PTDATA calibration flags:

| `ical` | Data returned                        |
| ------ | ------------------------------------ |
| `0`    | Raw digitizer counts                 |
| `1`    | Physics units (default)              |
| `2`    | Volts into the digitizer             |
| `4`    | Integrated signal (v-sec)            |

Any other value raises `ptdata.PtDataError` (code 110,
`InvalidConfiguration`) when the signal is constructed.  The flag is
translated by `ptdata.calibration_mode_for_ical`, which refuses to guess:
returning differently-calibrated data than you asked for is a units error
that looks like valid data.

---

## Omitting the time array (`fetch_times=False`)

When you need the data values but not the time base — for example, a single scalar
that does not vary in time — pass `fetch_times=False`:

```python
sig = PtDataSignal('btor', fetch_times=False)
result = sig.fetch(202161)
print(result.keys())   # dict_keys(['data', 'units'])
```

---

## Converting to xarray with `fetch_as_xarray`

`PtDataSignal` inherits the base `Signal.fetch_as_xarray` implementation, which
returns an `xr.DataArray` with a `'times'` coordinate:

```python
da = PtDataSignal('ip').fetch_as_xarray(202161)
# <xarray.DataArray (times: 3001)>
# Coordinates:
#   * times  (times) float64 0.0 0.5 1.0 ... 1500.0
# Attributes:
#     units: A
```

---

## Inspecting the raw header (`keep_header`)

Pass `keep_header=True` to include the PTDATA header dict in the result.  This is
useful for debugging or when you need metadata such as the point description or
calibration coefficients:

```python
sig = PtDataSignal('ip', keep_header=True)
result = sig.fetch(202161)
print(result['header'])
```

---

## `RDataSignal`

`RDataSignal` is a convenience subclass that always fetches the `RDATA` point,
a DIII-D operations lookup array.  It has no time array and no units:

```python
from toksearch_d3d import RDataSignal

rdata_sig = RDataSignal()
result = rdata_sig.fetch(202161)

print(result['data'].shape)    # (n_radii,)
```

`RDataSignal` takes the same optional `remote` and `keep_header` arguments as
`PtDataSignal`.

