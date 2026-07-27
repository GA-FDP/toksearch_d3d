---
name: toksearch-signal-routing
description: Read this FIRST when unsure which Signal class or data path a DIII-D quantity needs. Maps physics quantities (Ip, Wmhd, beta_N, q95, NBI power, density, Te, boundary, ...) to the correct Signal class and path, how to discover IMAS paths, and which skill to use for time-alignment/correlation. Avoids the common mistake of using PtDataSignal for a quantity that lives in MDSplus or IMAS.
---

# Choosing the right signal class for a DIII-D quantity

Picking the wrong backend is the most common failure. PtData only serves raw
PTDATA **pointnames**; asking it for an analysis quantity (e.g. `wmhd`, `betan`)
fails with `PtDataError: Shot.extension not found`. Use this table.

| Quantity | Class & path | Notes |
|----------|--------------|-------|
| Plasma current Ip | `PtDataSignal('ip')` | amps -> /1e6 for MA; times in **ms** |
| Ip from EFIT | `MdsSignal(r'\ipmhd', 'efit01')` | `MdsSignal` is imported from `toksearch` |
| Stored energy Wmhd | `MdsSignal(r'\wmhd', 'efit01')` | **not** a PTDATA pointname; Joules -> /1e6 for MJ |
| Normalized beta (beta_N) | `ImasSignal('equilibrium.time_slice.global_quantities.beta_normal')` | EFIT01-backed |
| q95 | `ImasSignal('equilibrium.time_slice.global_quantities.q_95')` | |
| Total NBI power | `ImasSignal('nbi.unit.power_launched.data')` | object array of per-unit W series (see recipe) |
| Core electron density | `ImasSignal('core_profiles.profiles_1d.electrons.density_thermal')` | 2-D (time, rho) |
| Thomson Te (per channel) | `ImasSignal('thomson_scattering.channel.t_e.data', split_by='channel')` | dict keyed by channel |
| Plasma boundary outline | `ImasSignal('equilibrium.time_slice.boundary.outline.r')` | ragged object array |

`PtDataSignal` comes from `toksearch_d3d`; `MdsSignal` from `toksearch`;
`ImasSignal` from the separate **`toksearch_imas`** package
(`conda install -c ga-fdp -c conda-forge toksearch_imas`).

## Discovering IMAS paths (don't guess)

```python
from toksearch_imas import list_imas_fields
list_imas_fields()          # all supported IDS names -> fields
list_imas_fields('nbi')     # fields under one IDS
```
`list_imas_fields()` reads the installed `imas_composer`'s mapper registry, so
it is always accurate for the version in use. The supported IDS set grows
between releases — always enumerate, never rely on a written-down list.

## Recipe: total injected NBI power (object array)

`nbi.unit.power_launched.data` returns a numpy **object array** of per-unit
power series (watts). Sum over units, then convert:

```python
import numpy as np
def peak_nbi_mw(rec):
    units = rec['pnbi']['data']                       # object array, ~8 units
    total = np.nansum(np.stack([np.asarray(u, float) for u in units]), axis=0)
    rec['peak_pnbi_MW'] = float(np.nanmax(total) / 1e6)   # 0.0 if no NBI
```

## Aligning / correlating two signals

Do **not** hand-roll resampling. Use `Pipeline.fetch_dataset` + `Pipeline.align`
(see the **toksearch-datasets** skill) so both signals share one grid:

```python
pipe.fetch_dataset('ds', {'ip': PtDataSignal('ip'),
                          'wmhd': MdsSignal(r'\wmhd', 'efit01')})
pipe.align('ds', align_with=10.0, method='pad')   # uniform 10 ms grid, zero-order hold
@pipeline.map
def corr(rec):
    ds = rec['ds']; a = ds['ip'].values; b = ds['wmhd'].values
    m = np.isfinite(a) & np.isfinite(b)
    rec['corr'] = float(np.corrcoef(a[m], b[m])[0, 1])
```

## SQL shot metadata

```python
from toksearch_d3d.sql import connect_d3drdb        # sets TDSVER for you
```
Canonical shot-type classification is the **`shots_type` table**
(`shot_type='plasma'`), joined on `shots.shot = shots_type.shot` — not the
`shot_type` column on `shots`.

## API reminders

- Times are **milliseconds**.
- Set record fields by item assignment in a `def` map: `rec['k'] = v`
  (`Record` has no `.update()`; lambdas can't assign).
- `rec.get('k', default)` requires the default argument.

## See also

- **toksearch-imas** — full ImasSignal API (ragged data, `split_by`, dims);
  ships with the separate `toksearch_imas` package.
- **toksearch-datasets** — `fetch_dataset`/`align` for multi-signal grids.
- **toksearch-d3d-ptdata** / **toksearch-mds** — per-backend details.
