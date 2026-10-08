---
name: d3d-efit
description: Use when reading, interpreting, or judging a DIII-D EFIT equilibrium reconstruction — choosing among efit01/efit02/efit02er/efitrt/user/scratch trees, finding which measurements were used or excluded, locating residuals and constraints, deciding whether a reconstruction is trustworthy, or resolving what an EFIT node name and its units actually mean.
---

# Reading and assessing DIII-D EFIT

EFIT trees are MDSplus trees, read with `MdsSignal` or `MDSplus.Tree`. Three
things trip up every newcomer: `efit01` is magnetics-only, `\chisq` is not the
only quality gate (there are two), and some nodes do not contain valid data.

Verified on shots 165920 (2016), 170589 (2017), 180000 (2019), 198873 and
200000 (2024), trees `efit01`/`efit02`/`efit02er` and their unfiltered `efits*`
twins, plus the scratch `efit` tree. Numbers are from 165920 unless stated.

## 1. Pick the right tree

Read `:RUN_TYPE`, `:USERID`, `:COMMENTS`, `:NAMELIST` before trusting any tree.
Numbering above `efit02` carries **no fixed meaning** — `efit03` is a different
person's rerun on every shot.

| tree | what it is | use for |
|------|-----------|---------|
| `efit01` | ops automatic, **magnetics only** (`RUN_TYPE` `JT`, later `jta_f`) | geometry, boundary, shape, `WMHD`, `BETAN` |
| `efit02` | ops automatic, **MSE-constrained** (`RUN_TYPE` is the snap name — `MSE`, `mse15`, `mse23`, ...) | anything current-profile: `QPSI`, `Q0`, `QMIN`, `LI`, shear |
| `efit02er` | MSE-constrained with the MSE **corrected for the radial electric field** using CER | current profile where Er matters; compare against `efit02` |
| `efits1`/`efits2`/`efits2er` | **unfiltered** efit01/efit02/efit02er | quality labels — see §4 |
| `efitrt1`/`efitrt2` | real-time, computed by the PCS during the shot | what the controller saw; never physics |
| `efit03`+ | user reruns; owner in `:USERID` | only after reading `:COMMENTS` |
| `efit` | scratch tree: many runs per shot, each its own shot number | see §5 |

**`RUN_TYPE` is the snap name, so match on its prefix, not its exact value.**
Many MSE snaps have been used over the years — @torrinba lists `mse06`,
`mse07a/b`, `mse08`, `mse09`, `mse10`, `mse11`, `mse15`, `mse20`, `mse23` and
`mse23_no41`, with Er counterparts such as `mse09Er`, `mse10er`, `mse12Er`,
`mse16er`, `mse20er`, `mse23er` and `mse23er_no41`. Casing is inconsistent
(`Er` and `er` both occur). Confirmed here: `MSE` (165920), `mse15` (170589),
`mse23` (200000), `mse16er` (170589), `mse23er_no41` (200000).

`efit01` is under-determined for the current profile. Using its `q0`, `qmin` or
`li` without cross-checking `efit02` is the most common misuse.

`efit02` covers only the MSE-valid window and self-limits to it — on 165920 its
`MTIME` spans 205-4865 ms with a constant 14 active MSE channels, versus
`efit01`'s 100-6380 ms. Expect fewer slices, not a beam-window mask you must
apply yourself.

**`efit02er` exists only for some shots** — absent on 165920 and 198873,
present on 170589 and 200000. The d3drdb run log (§2) lists runs for shots
133103-208191. The Er correction is visible in `:NAMELIST` (`mse_usecer=1`,
`mse_use_cer330=1`, `mse_certree`). It is run by `USERID='efit'` on request.

**Do not read the `efit02er`-vs-`efit02` namelist diff as the Er correction.**
On 200000 the pair is `mse23er_no41` against `mse23`, so the diff also carries
the channel-41 exclusion (`fwtgam(41)=0.0`) and a different spline basis
(`kppknt` 3 vs 2, `pptens`/`fftens` 0.01 vs 5, plus `kcalpa`/`kcgama`
constraints). Isolating Er would need the matching non-Er snap
(`mse23_no41`), which is not present on that shot — no tree on 200000 carries
it. Two details worth knowing before you diff: `fwtfc` is `18*1.` in **both**
trees, so it is not a difference at all; and `iecurr=2 fwtec=6*1.` appears only
in the Er namelist, though @torrinba notes E-coil currents are not fit, which
would make those weights inert.

## 2. Tree layout

```
\EFIT01::TOP:RUN_TYPE :USERID :COMMENTS :D3D_SHOT :NAMELIST
            .NAMELISTS.{SNAPFILE,KEQDSKS}
            .MEASUREMENTS    inputs, weights, residuals   (timebase MTIME)
            .RESULTS.AEQDSK  ~230 a-file scalars vs time  (timebase ATIME)
            .RESULTS.GEQDSK  g-file 1-D/2-D               (timebase GTIME)
            .RESULTS.CONFINEMENT
```

**On the filtered trees, `MTIME` is longer than `ATIME`.** This is a
long-standing bug: the ops filter (§4) drops rejected slices from `RESULTS` but
not from `MEASUREMENTS`, so `MTIME` on `efit01`/`efit02`/`efit02er` is the
*unfiltered* timebase and equals the `efits*` twin's `ATIME`. On the `efits*`
trees all three timebases agree. `ATIME` and `GTIME` are `ms` and equal, so
AEQDSK scalars and GEQDSK profiles share one clock. `MTIME` carries no
`:UNITS`.

| tree | MTIME | ATIME | GTIME |
|------|-------|-------|-------|
| efit01/165920 | 315 | 303 | 303 (== ATIME) |
| efits1/165920 | 315 | 315 | 315 |
| efit02/165920 | 234 | 138 | 138 (== ATIME) |
| efits2/165920 | 234 | 234 | 234 |

Never index MEASUREMENTS against RESULTS positionally on a filtered tree; match
on time value or use `Pipeline.align`. Verify `GTIME == ATIME` rather than
assuming it on user reruns. Don't treat `MTIME` minus `ATIME` as the reject
list either: it only works because of the bug, and a fix would silently empty
it.

**Profiles live in GEQDSK**, shaped `(ntime, 65)` on a uniform flux grid:

| node | units | meaning |
|------|-------|---------|
| `QPSI` | — | q values on uniform flux grid from axis to boundary |
| `PSIN` | normalized psi | the 65-point radial grid, `(65,)`, 0=axis 1=boundary |
| `RHOVN` | — | normalized rho, `(ntime, 65)` |
| `PRES` | `N / m^2` | plasma pressure |
| `PPRIME` | `(N / m^2) / (V s / rad)` | P'(psi) |
| `FFPRIM` | `(T m)^2 / (V s / rad)` | FF'(psi) |
| `FPOL` | `T m` | poloidal current function F = R*Bt |
| `PSIRZ` | `V s / rad` | poloidal flux on the R,Z grid |

GEQDSK nodes carry the same `:LABEL`/`:UNITS`/`:MULTIPLIER` members as AEQDSK
(§3) — the units above were read from the tree, not assumed. `PSIN` has no
`:MULTIPLIER`; treat a missing multiplier as 1.0.

**Which channels were used or excluded** — the `FWT*` arrays in `MEASUREMENTS`,
shaped `(ntime, nchannel)`: `FWTMP2` (76 magnetic probes), `FWTSI` (44 flux
loops), `FWTGAM` (MSE; 101 channels on 165920, 69 on later shots), `FWTFC`,
`FWTEC`, `FWTPRE`, `FWTDIA`. These are **1/sigma weights, not 0/1 flags**.
**Zero means excluded from that slice's fit.** On efit01/165920, 10 of 76
probes and 5 of 44 loops are zeroed. `RRGAM`/`ZZGAM` give each MSE channel's
position in metres, same shape (1.53-2.33 m on efit02/200000; zero on `efit01`).

**Residuals** — per-channel chi-square contributions, all in `MEASUREMENTS`:

| node | channels | populated |
|------|----------|-----------|
| `SAIMPI`, `SAISIL`, `SAIPRE` | probes, loops, pressure | all runs |
| `CHIGAM` | MSE (label `chisq vs. polarimetries`) | MSE-constrained trees |
| `CHIFCC`, `CHIPASMA` | F-coils, Rogowski | empty on 165920 but filled for later shots |
| `CHIECC`, `CHIDFLUX` | E-coils, diamagnetic loop | exist, but zero on every run sampled |

Use them to attribute a bad `CHISQ` to a specific channel. Compare measured
against computed directly: `EXPMPI`/`CMPR2`, `SILOPT`/`CSILOP`,
`PLASMA`/`CPASMA`, `FCCURT`/`CCBRSP`, `TANGAM`/`CMGAM`, `ECCURT`/`CECURR`,
`DIAMAG`/`CDFLUX`. **Always take these from `MEASUREMENTS`, not `AEQDSK`** —
`AEQDSK` carries nodes of the same name that are sometimes different
quantities. `DIAMAG`/`CDFLUX` are the confirmed case: in `AEQDSK` they hold a
scaled loop signal and an unlabeled value near 1.7. `PRESSR`/`CPRESS` exist but
are zero outside kinetic EFITs (per its label).

**Uncertainty depends on when the run was made.** Per-channel sigmas live in
`MEASUREMENTS`:

| node | measures | 165920 (2016), 180000 (2019) | 198873, 200000 (2024) |
|------|----------|------------------------------|-----------------------|
| `SIGMPI`, `SIGSIL`, `SIGPASMA`, `SIGFCC` | probes, loops, Ip, F-coils | empty | populated |
| `SIGGAM` | MSE `TANGAM` | populated on MSE trees | populated on MSE trees |
| `SIGDIA` | diamagnetic flux | populated | populated |
| `SIGECC`, `SIGPRE` | E-coils, pressure | empty or zero | zero |

The MSE sigma is `SIGGAM`; there is no `SIGAM`. On older runs sigma survives
only implicitly in `FWT*`, and rerunning EFIT is the way to get explicit
values. At any date there is **no posterior covariance**, and `CONDNO` (fit
condition number) is the only ill-conditioning indicator.

**Configuration** — `:NAMELIST` holds the full EFIT namelist as free text plus a
glossary of its parameters; `:COMMENTS` names the snap file. There is **no EFIT
source-version string anywhere in the tree**. When a run was made, by whom, and
whether it was later retracted live in the d3drdb run log, not the tree:

```python
import pandas as pd
from toksearch_d3d.sql import connect_d3drdb
with connect_d3drdb() as conn:
    runs = pd.read_sql(
        "SELECT tree, run_id, runtag, date_run, run_by, deleted, run_comment "
        f"FROM code_rundb.dbo.plasmas WHERE code_name = 'EFIT' AND shot = {int(shot)} "
        "ORDER BY date_run", conn)
```

Filter on `code_name`, not `tree`: tree names come back in mixed case
(`EFIT02er`). `deleted=1` marks a run someone retracted. Some user runs store
only the date in `date_run` (midnight) and put the real time in `run_comment`.
Record provenance as `(tree, shot, run_id, RUN_TYPE, USERID, date_run,
COMMENTS, hash(NAMELIST))`.

**These do NOT exist in DIII-D EFIT trees** — plausible names commonly
hallucinated from other EFIT deployments: `AEQDSK:JFLAG`, `AEQDSK:LFLAG`,
`TOP.INPUTS`, `MEASUREMENTS:MPNAM2`, `MEASUREMENTS:FWTCUR`,
`MEASUREMENTS:SIGAM`. There are no a-file error flags here. Quality is judged
from `ERROR` and `CHISQ` (§4).

## 3. The tree is its own data dictionary

Each documented signal carries **member nodes**, not XNCI attributes.
`node.help` throws `%TDI-E-INVDTYDSC` — do not use it.

```
\EFIT01::TOP.RESULTS.AEQDSK:WMHD:LABEL       'total plasma energy'
                                :UNITS       'J'
                                :MULTIPLIER  1.0
                                :EFIT_NAME   'WPLASM'
                                :READA_NAME  'WMHD'
                                :REVIEW_NAME 'WMHD'
```

Harvest per tree rather than hardcoding a map (296 documented nodes on
efit01/165920):

```python
import MDSplus
FIELDS = ('LABEL', 'UNITS', 'MULTIPLIER', 'EFIT_NAME', 'READA_NAME',
          'REVIEW_NAME', 'INFO')
t = MDSplus.Tree('efit01', shot)
dd = {}
for n in t.getNodeWild('***'):
    p = n.getFullPath()
    base, _, suf = p.rpartition(':')
    if suf in FIELDS and base.count(':') >= 1:
        try:
            dd.setdefault(base, {})[suf] = t.getNode(p).getData().data()
        except Exception:
            pass    # member exists but is empty — common in CONFINEMENT
```

- `:EFIT_NAME` maps the tree name back to EFIT's internal/a-file variable name.
- `:INFO` decodes enums, e.g. `LIMLOC` spells out `IN`/`OUT`/`TOP`/`BOT`/`SNB`/`SNT`/`DND`.
- Apply `:MULTIPLIER`; do not assume 1.0.
- `:UNITS` of `?` or `???` means unknown, not a unit. A single space means dimensionless.

**Presence of `:LABEL` is the test for whether a node is real.** The tree renames
things relative to EFIT *and* keeps stray nodes carrying the EFIT-side names.
Identical on efit01 and efit02:

| use | ignore | why the stray is dangerous |
|-----|--------|----------------------------|
| `CHISQ` (`magnetic chi^2`) | `TSAISQ` | empty |
| `ERROR` (`convergence error`) | `TERROR` | 303 plausible values, 1.45-1.75; gating on it accepts or rejects everything |
| `CHIMSE` (`MSE chi^2`) | `CHIGAMT` | holds a 65-point axis, -1.6 to 1.6 |
| — | `FIT_TYPE` | undocumented |

Renames to load up front: `IPMEAS`<-`PASMAT`, `IPMHD`<-`CPASMA`, `Q95`<-`QPSIB`,
`Q0`<-`QQMAGX`, `LI`<-`ALI`, `WMHD`<-`WPLASM`, `WDIA`<-`WPLASMD`,
`VOLUME`<-`VOUT`, `DRSEP`<-`SSEP`, `QMIN`<-`QQMIN`, `RHOQMIN`<-`RQQMIN`. Every
efit-side name also exists as an empty node in `AEQDSK`.

## 4. Judging a reconstruction

**Ops keep a slice when `ERROR < 1e-2` and `CHISQ < 80`.** That filter turns
`efits1` into `efit01`, `efits2` into `efit02` and `efits2er` into `efit02er`.
The thresholds are fixed and do not depend on the snap file.

- `ERROR` (`convergence error`) is where the fit actually ended up. The
  namelist's `error`/`errmin` is only the tolerance at which EFIT *stops
  iterating*. A slice that hits the iteration limit first is still written out,
  so never gate on the namelist value. The namelist tolerance differs by snap
  (`1e-4` on efit01, `1e-3` on efit02), which is irrelevant to the gate.
- `CHISQ` (`magnetic chi^2`) is goodness of fit, not convergence. It is the
  rarer half of the gate: a slice filtered on `CHISQ` usually means a
  diagnostic failure, not a bad reconstruction. Across the six filtered pairs
  sampled, the highest `CHISQ` in any *kept* set was 47.4 — well under the 80
  cut — so in practice `ERROR` does nearly all the rejecting. Do not gate on
  `CHISQ` alone: on 165920/efit01 the discarded slices had *lower* `CHISQ`
  (median 11.9) than the kept ones (22.7), but that inversion is a coincidence
  of that shot, not a rule — the other five pairs run the expected way.

```python
import numpy as np, MDSplus
def ops_gate(tree, shot):
    t = MDSplus.Tree(tree, shot)
    get = lambda n: np.asarray(t.getNode(rf'\{tree.upper()}::TOP.RESULTS.AEQDSK:{n}').getData().data())
    return get('ATIME'), (get('ERROR') < 1e-2) & (get('CHISQ') < 80)
```

This rule reproduces ops' kept set on all seven filtered/unfiltered pairs
checked (efit01 on all four shots, efit02 on 165920 and 200000, efit02er on
200000), with one exception: **the first slice of a run is kept even when it
fails**. Examples: t=100 ms on efit01 at 165920 and 180000 (`ERROR` 0.09 and
0.40), and t=520 ms on efit02er at 200000 (`ERROR` 0.30). Apply the gate
to an ops tree as well, to catch that leaked slice. Every rejection in this
sample failed on `ERROR`; none failed on `CHISQ` alone. So the 80 cut comes
from the EFIT maintainers, not from these measurements.

| pair | kept | rejected |
|------|------|----------|
| efit01 / efits1, 165920 | 303 | 12 |
| efit02 / efits2, 165920 | 138 | 96 |
| efit01 / efits1, 198873 | 304 | 20 |
| efit02 / efits2, 200000 | 300 | 0 |
| efit02er / efits2er, 200000 | 290 | 19 |

**The gate is `ERROR` and `CHISQ`; everything below is diagnostic — use it to
explain a bad slice, not to reject a good one.**

1. `|IPMHD - IPMEAS| / IPMEAS` within a few percent.
2. `CHISQ` normalized by the count of nonzero `FWT*` entries, then the
   per-channel residuals (§2) to find the offending channel.
3. `CHIMSE` per slice for MSE-constrained trees (0.72-13.3 on efit02/165920),
   and `CHIGAM` for the channel behind it.
4. `CONDNO` spikes mean an ill-conditioned fit.
5. `WMHD` vs `WDIA` — large disagreement means bad pressure or `li`.
6. Plausibility: `Q95`, `LI`, `BETAN` in range; `RMAXIS` inside the vessel;
   `RBBBS`/`ZBBBS` closed and inside `LIM`.
7. `efit01` vs `efit02` divergence in `q0`/`li` — the honest signal that
   magnetics-only is under-determined at that time.

**Not covered here — do not invent values for these.** `CONDNO` has no reference
scale. `CHIMSE` has an observed range (0.72-13.3 on efit02/165920) but no
acceptance cut. There is no rule for how few active MSE channels, or how narrow
a span of `RRGAM` radii, make `QPSI` untrustworthy. There is no per-slice
uncertainty on `q`, so a trust verdict is binary. Measure these per study; do
not guess.

## 5. Access

All named DIII-D MDSplus trees are on the FDP origin; the catalog search path
is generic, so any tree name resolves. Nothing restricts you to `efit01`.

```python
MdsSignal(r'\efit02::top.results.aeqdsk:q95', 'efit02')
ImasSignal('equilibrium.time_slice.global_quantities.q_95', efit_tree='EFIT02')
```

`fdp ls /fdp-d3d/archives/mdsplus/codes/` lists the 54 code trees available.
Run under `fdp run python`; in-process `setup_environment()` is too late for
MDSplus-over-Pelican. Scaling past one shot: fork workers **before** any XrdCl
use, or use the `spawn` start method — see the FDP notes on fork-after-XrdCl.

**Scratch runs live in the single `efit` tree.** Each run is its own MDSplus
shot number, `shot*100 + NN`, so run 01 of shot 170589 is `17058901`. The top
node is `\EFIT::TOP`, and the layout matches §2. Find a shot's runs with the
d3drdb query in §2: they appear as `tree='EFIT'` with the full number in
`run_id`. A filtered run and its unfiltered twin get separate numbers, told
apart by `(unfiltered)` in `run_comment`. Recent rows include FDP reruns
(`run_by='d3dsf'`) and CAKE kinetic EFITs.

**Don't assume a scratch "filtered" run is filtered.** `17058901` is logged
as the filtered twin of `17058902`, yet it holds all 329 of the unfiltered
slices, including 4 that fail the §4 gate. Run `ops_gate` on scratch runs
yourself.

```python
p = Pipeline([17058901])          # the run number, not the shot
p.fetch('q95', MdsSignal(r'\efit::top.results.aeqdsk:q95', 'efit'))

p = Pipeline([170589])            # the shot; the run goes in efit_run_id
p.fetch('q95', ImasSignal('equilibrium.time_slice.global_quantities.q_95',
                          efit_tree='EFIT', efit_run_id='01'))
```

Both return the same q95 magnitudes as the tree node. The IMAS value carries the
IMAS COCOS sign, so it is negative where the tree's `Q95` is positive, and the
default `efit01` behaves the same way. Compare magnitudes, or convert the sign
deliberately.

**Only some scratch runs are on the origin.** `17058901`/`02` and
`16695301`/`02` are; `20000003` (run 2026-07-30) is not, and opening a missing
run fails with `TreeFOPENR`. The path splits the run number into digit pairs,
so check a run first with
`fdp ls /fdp-d3d/archives/mdsplus/codes/efit/00/17/05/89/`.

## Authority order for definitions

1. In-tree `:LABEL`/`:UNITS`/`:INFO`/`:MULTIPLIER`/`:EFIT_NAME` (§3).
2. IMAS Data Dictionary via `ImasSignal` — formal, machine-readable definitions;
   `imas_composer` maps EFIT nodes to IDS paths, default `efit_tree='EFIT01'`.
3. EFIT literature for the undocumented remainder: Lao et al., *Nucl. Fusion*
   **25** (1985) 1611; Lao et al., *Fusion Sci. Technol.* **48** (2005) 968.

Never infer a node's meaning from its name alone. Check `:LABEL`, `dtype`,
`shape` and `:UNITS` first.

## See also

- **toksearch-mds** — `MdsSignal` constructor, TDI, `location=` formats.
- **toksearch-signal-routing** — which Signal class a quantity needs.
- **toksearch-datasets** — `fetch_dataset`/`align` for the differing timebases.
