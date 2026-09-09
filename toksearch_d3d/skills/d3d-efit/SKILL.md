---
name: d3d-efit
description: Use when reading, interpreting, or judging a DIII-D EFIT equilibrium reconstruction — choosing among efit01/efit02/efitrt/user trees, finding which measurements were used or excluded, locating residuals and constraints, deciding whether a reconstruction is trustworthy, or resolving what an EFIT node name and its units actually mean.
---

# Reading and assessing DIII-D EFIT

EFIT trees are MDSplus trees, read with `MdsSignal` or `MDSplus.Tree`. Three
things trip up every newcomer: `efit01` is magnetics-only, `\chisq` is not the
quality gate, and node names do not mean what they look like.

Everything below is verified on shot 165920, trees `efit01`/`efit02`/`efits1`/`efits2`.

## 1. Pick the right tree

Read `:RUN_TYPE`, `:USERID`, `:COMMENTS`, `:NAMELIST` before trusting any tree.
Numbering above `efit02` carries **no fixed meaning** — `efit03` is a different
person's rerun on every shot.

| tree | what it is | use for |
|------|-----------|---------|
| `efit01` | ops automatic, **magnetics only** (`RUN_TYPE='JT'`) | geometry, boundary, shape, `WMHD`, `BETAN` |
| `efit02` | ops automatic, **MSE-constrained** (`RUN_TYPE='MSE'`) | anything current-profile: `QPSI`, `Q0`, `QMIN`, `LI`, shear |
| `efits1`/`efits2` | **unfiltered** efit01/efit02 | quality labels — see §4 |
| `efitrt1`/`efitrt2` | real-time, computed by the PCS during the shot | what the controller saw; never physics |
| `efit03`+ | user reruns; owner in `:USERID` | only after reading `:COMMENTS` |

`efit01` is under-determined for the current profile. Using its `q0`, `qmin` or
`li` without cross-checking `efit02` is the most common misuse.

`efit02` covers only the MSE-valid window and self-limits to it — on 165920 its
`MTIME` spans 205-4865 ms with a constant 14 active MSE channels, versus
`efit01`'s 100-6380 ms. Expect fewer slices, not a beam-window mask you must
apply yourself.

## 2. Tree layout

```
\EFIT01::TOP:RUN_TYPE :USERID :COMMENTS :D3D_SHOT :NAMELIST
            .NAMELISTS.{SNAPFILE,KEQDSKS}
            .MEASUREMENTS    inputs, weights, residuals   (timebase MTIME)
            .RESULTS.AEQDSK  ~230 a-file scalars vs time  (timebase ATIME)
            .RESULTS.GEQDSK  g-file 1-D/2-D               (timebase GTIME)
            .RESULTS.CONFINEMENT
```

**MTIME differs in length from ATIME**; `ATIME` and `GTIME` are `ms` and are
equal on both ops trees, so AEQDSK scalars and GEQDSK profiles share one clock.
`MTIME` is longer and carries no `:UNITS`.

| tree | MTIME | ATIME | GTIME |
|------|-------|-------|-------|
| efit01/165920 | 315 | 303 | 303 (== ATIME) |
| efit02/165920 | 234 | 138 | 138 (== ATIME) |

Never index MEASUREMENTS against RESULTS positionally; match on time value or
use `Pipeline.align`. Verify `GTIME == ATIME` rather than assuming it on user
reruns.

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
loops), `FWTGAM` (101 MSE), `FWTFC`, `FWTEC`, `FWTPRE`, `FWTDIA`. These are
**1/sigma weights, not 0/1 flags**. **Zero means excluded from that slice's
fit.** On efit01/165920, 10 of 76 probes and 5 of 44 loops are zeroed.

**Residuals** — `SAIMPI`, `SAISIL`, `SAIPRE` hold per-channel chi-square
contributions; use them to attribute a bad `CHISQ` to a specific probe. Compare
measured against computed directly: `EXPMPI`/`CMPR2`, `SILOPT`/`CSILOP`,
`PLASMA`/`CPASMA`, `FCCURT`/`CCBRSP`, `TANGAM`/`CMGAM`.

**Uncertainty** — weak. `SIGMPI`/`SIGSIL`/`SIGPASMA` nodes exist but are
routinely empty; sigma survives only implicitly in `FWT*`. There is **no
posterior covariance**. `CONDNO` (fit condition number) is the only
ill-conditioning indicator.

**Configuration** — `:NAMELIST` holds the full EFIT namelist as free text plus a
glossary of its parameters; `:COMMENTS` names the snap file. There is **no EFIT
source-version string anywhere in the tree**. Record provenance as
`(tree, shot, RUN_TYPE, USERID, COMMENTS, hash(NAMELIST))`.

**These do NOT exist in DIII-D EFIT trees** — plausible names commonly
hallucinated from other EFIT deployments: `AEQDSK:JFLAG`, `AEQDSK:LFLAG`,
`TOP.INPUTS`, `MEASUREMENTS:MPNAM2`, `MEASUREMENTS:FWTCUR`. There are no
a-file error flags here. Convergence is judged from `ERROR` (§4).

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

**`CHISQ` is not the gate and alone it inverts the answer.** Its label is
"magnetic chi^2" — goodness of fit, not convergence. On 165920 the 12 slices ops
discarded had *lower* `CHISQ` (10.9-22.0) than the median kept slice (22.7).

**`ERROR` (`convergence error`) is the gate, but its scale is per-snap.** Read
the tolerance from `:NAMELIST`; never hardcode one:

```python
import re
def tolerances(tree, shot):
    t = MDSplus.Tree(tree, shot)
    nl = str(t.getNode(rf'\{tree.upper()}::TOP:NAMELIST').getData().data())
    # namelists differ in case between snaps -- efit01 writes ERROR=,
    # efit02 writes error=. Fold the keys or this KeyErrors.
    return {k.lower(): float(v)
            for k, v in re.findall(r'(?i)\b(errmin|error)\s*=\s*([0-9.eE+-]+)', nl)}
```

efit01/efits1 declare `error=1.E-4, errmin=1.0E-4`; **efit02 declares `1.0e-3`**.
A hardcoded `1e-4` rejects 100% of efit02 slices. And efit02's median `ERROR`
(1.5e-3) already exceeds its own declared tolerance, so an absolute cut is
unreliable even when read correctly.

**Use the ops labels instead of inventing a threshold.** `efit01`'s `ATIME` is a
strict subset of `efits1`'s; the set difference is exactly what ops rejected.

```python
import numpy as np
A = lambda tr: np.asarray(MDSplus.Tree(tr, shot).getNode(
        rf'\{tr.upper()}::TOP.RESULTS.AEQDSK:ATIME').getData().data())
rejected = sorted(set(np.round(A('efits1'), 3)) - set(np.round(A('efit01'), 3)))
```

`ERROR` separates those populations by roughly an order of magnitude **relative
to the tree's own kept-slice median**, which is the portable rule:

| pair | kept | rejected | rejected `ERROR` median | kept `ERROR` median |
|------|------|----------|------------------------|---------------------|
| efit01 / efits1 | 303 | 12 | 2.5e-2 | 4.2e-5 |
| efit02 / efits2 | 138 | 96 | 1.8e-2 | 1.5e-3 |

If the `efits*` twin is missing, fall back to `ERROR` above ~10x the tree's own
median — but know its limits. On efit01 the two populations separate by ~600x,
so the cut is safe. **On efit02 they separate by only ~12x**, so a 10x cut sits
just under the rejected median and will misclassify both tails. Treat a
twin-less efit02-class tree as having no reliable automatic gate, and say so,
rather than shipping a filter that only looks like one. The median is also of
whatever population the tree holds — on an already-filtered tree it is a median
of survivors, which is not the same quantity.

**`ERROR` (or the set difference) is the gate; everything below is diagnostic —
use it to explain a bad slice, not to reject a good one.**

1. `|IPMHD - IPMEAS| / IPMEAS` within a few percent.
2. `CHISQ` normalized by the count of nonzero `FWT*` entries, then
   `SAIMPI`/`SAISIL` to find the offending channel.
3. `CHIMSE` per slice for MSE-constrained trees (0.72-13.3 on efit02/165920).
4. `CONDNO` spikes mean an ill-conditioned fit.
5. `WMHD` vs `WDIA` — large disagreement means bad pressure or `li`.
6. Plausibility: `Q95`, `LI`, `BETAN` in range; `RMAXIS` inside the vessel;
   `RBBBS`/`ZBBBS` closed and inside `LIM`.
7. `efit01` vs `efit02` divergence in `q0`/`li` — the honest signal that
   magnetics-only is under-determined at that time.

**Not covered here — do not invent values for these.** `CONDNO` has no reference
scale; `CHIMSE` has an observed range (0.72-13.3 on efit02/165920) but no
acceptance cut; there is no rule for how few active MSE channels make `QPSI`
untrustworthy, and no mapping from active channel indices to a trustworthy
radius — so outside MSE coverage `efit02`'s `QPSI` is effectively magnetics-only
even though the tree is MSE-constrained. There is no per-slice uncertainty on
`q`, so a trust verdict is binary. Measure these per study; do not guess.

## 5. Access

All DIII-D MDSplus trees are on the FDP origin; the catalog search path is
generic, so any tree name resolves. Nothing restricts you to `efit01`.

```python
MdsSignal(r'\efit02::top.results.aeqdsk:q95', 'efit02')
ImasSignal('equilibrium.time_slice.global_quantities.q_95', efit_tree='EFIT02')
```

`fdp ls /fdp-d3d/archives/mdsplus/codes/` lists the 54 code trees available.
Run under `fdp run python`; in-process `setup_environment()` is too late for
MDSplus-over-Pelican. Scaling past one shot: fork workers **before** any XrdCl
use, or use the `spawn` start method — see the FDP notes on fork-after-XrdCl.

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
