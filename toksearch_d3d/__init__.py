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

"""
toksearch_d3d — DIII-D signal classes and FDP CLI for the TokSearch framework.

Extends ``toksearch`` with DIII-D-specific signal types (PtDataSignal,
ImasSignal, CakeSignal) and the ``fdp`` CLI for Pelican/OSDF data access.
For core Pipeline documentation, see ``help(toksearch)``.

Invocation
==========

Two ways to configure the FDP environment:

**1. Python-side setup** (preferred for scripts and notebooks)::

    from toksearch_d3d import setup_environment
    setup_environment()           # then import signal classes and run pipelines

    # Override individual variables as needed:
    setup_environment(PTDATA_LOC="2", BEARER_TOKEN="...")

**2. CLI wrapper** (preferred when launching a subprocess)::

    pixi run fdp run python <script.py>

``setup_environment`` and ``fdp run`` apply the same defaults: XRootD plugin
paths, MDSplus tree paths, PTData configuration. The bearer token is
resolved from the ``bearer_token`` argument, then ``$BEARER_TOKEN``, then
``~/.fdp/token``.

Connecting to d3drdb needs no manual ``TDSVER`` — ``connect_d3drdb`` reads
``tdsver`` from the ``d3d.yaml`` d3drdb locator and sets it for you.

Imports
=======

::

    from toksearch import Pipeline
    from toksearch_d3d import PtDataSignal     # DIII-D PTDATA diagnostics
    from toksearch_d3d import ImasSignal       # IMAS IDS paths (requires imas_composer)
    from toksearch_d3d import CakeSignal       # Equilibrium/profile via MDSplus+SQLite
    from toksearch.sql.mssql import connect_d3drdb  # Shot metadata DB

Import ``PtDataSignal`` and ``ImasSignal`` from ``toksearch_d3d``, **not**
``toksearch``.

PtDataSignal
============

Fetches DIII-D PTDATA time-series diagnostics.  Times in **milliseconds**::

    sig = PtDataSignal('ip')
    result = sig.fetch(202161)   # {'data': ndarray, 'times': ndarray, 'units': dict}

Constructor::

    PtDataSignal(pointname, remote=True, ical=1, keep_header=False,
                 fetch_times=True, fetch_units=True)

Common point names:

==========  ============================
Point       Description
==========  ============================
ip          Plasma current (A)
dssdenest   Line-averaged electron density
btor        Toroidal magnetic field
pinj        NBI power (unreliable for recent shots — prefer ImasSignal)
echpwr      ECH power
prad        Radiated power
wmhd        MHD stored energy
==========  ============================

ImasSignal (Experimental)
=========================

Fetches DIII-D data via the IMAS IDS schema using ``imas_composer``.
Only available when ``imas_composer`` is installed. Also exported as
``D3dImasSignal`` (an exact alias) for device-prefixed symmetry with other
device packages, e.g. ``toksearch_mast.MastImasSignal``.

**Leaf path** — fetches one field::

    ImasSignal('equilibrium.time_slice.global_quantities.ip')

**Prefix path** — fetches all fields under a subtree::

    ImasSignal('equilibrium.time_slice.global_quantities')

**Ragged arrays**: channel-indexed data returns a numpy object array.
Use ``split_by='channel'`` for a dict keyed by channel name::

    ImasSignal('thomson_scattering.channel.n_e.data', split_by='channel')

**Controlling shape with** ``layout=``: imas_composer 0.2.4 puts every
``core_profiles.profiles_1d`` quantity on one shared time axis, leaving an
*empty* slot where that quantity has no data.  ``layout=`` chooses how that
is presented:

- ``'compact'`` — drop the empty slots, filtering ``times`` in lockstep.
  Rectangular when one common inner length remains.  **Default for leaf
  paths.**
- ``'filled'`` — keep every slot, NaN-padding the gaps so all leaves stay
  index-aligned to one time axis.  **Default for prefix paths.**
- ``'ragged'`` — no transformation; the object array as composed.
- ``'awkward'`` — the raw ``ak.Array``.

::

    # rectangular (n_time, n_rho), the default
    ImasSignal('core_profiles.profiles_1d.electrons.density')

    # every slot kept, gaps NaN
    ImasSignal('core_profiles.profiles_1d.electrons.density', layout='filled')

Layout applies **only** when the outer axis is provably a time axis, so
channel- and measurement-indexed data (ECE channels, ``magnetics.ip``) is
never reshaped — entries there are matched positionally against sibling
name arrays.  ``as_awkward`` is deprecated in favour of ``layout='awkward'``.

**NBI power recipe** — 8 per-unit time series.  Object array under
imas_composer 0.2; rectangular ``(8, n_time)`` under 0.2.4.  ``np.stack``
handles both::

    import numpy as np
    nbi_data = rec.get('nbi', None)
    if nbi_data is not None and nbi_data.get('data') is not None:
        units = np.stack(list(nbi_data['data']), axis=0).astype(float)
        total_mw = np.nanmax(np.nansum(units, axis=0)) / 1e6

**Sharing a composer** avoids repeated mapper init::

    from imas_composer import ImasComposer
    composer = ImasComposer(efit_tree='EFIT01')
    ImasSignal('equilibrium.time_slice.global_quantities.ip', composer=composer)

**Discovering fields**::

    from toksearch_d3d import list_imas_fields
    fields = list_imas_fields()          # all IDS
    fields = list_imas_fields('ece')     # one IDS

Common IDS paths::

    equilibrium.time_slice.global_quantities.ip
    equilibrium.time_slice.global_quantities.q_95
    equilibrium.time_slice.global_quantities.beta_normal
    equilibrium.time_slice.profiles_1d.q
    nbi.unit.power_launched.data
    ece.channel.t_e.data
    magnetics.ip.data
    core_profiles.profiles_1d.electrons.density
    thomson_scattering.channel.n_e.data

Shot List from d3drdb
=====================

::

    import pandas as pd
    from toksearch.sql.mssql import connect_d3drdb

    with connect_d3drdb() as conn:
        df = pd.read_sql(
            \"\"\"SELECT s.shot, s.entered
            FROM shots s JOIN shots_type st ON s.shot = st.shot
            WHERE st.shot_type = 'plasma'
              AND s.entered >= '2024-06-01'\"\"\",
            conn,
        )
    shots = df['shot'].tolist()

Key tables: ``shots`` (shot number, ``entered`` timestamp),
``shots_type`` (``shot_type``: 'plasma', 'calibration', etc.).
Join on ``shots.shot = shots_type.shot``.

fdp CLI
=======

``fdp run <cmd>``
    Execute a command with all FDP environment variables configured.

``fdp env``
    Print ``export VAR=value`` lines for shell eval: ``eval $(fdp env)``.

``fdp ls <path>``
    List files/directories on the FDP origin server via XRootD.

Authentication: ``~/.fdp/token`` file (preferred), ``BEARER_TOKEN`` env var,
or ``-t TOKEN`` flag.

DIII-D Gotchas
==============

- ``connect_d3drdb`` sets ``TDSVER`` automatically (from the ``d3d.yaml``
  d3drdb locator); the deprecated ``toksearch.sql.mssql.connect_d3drdb``
  still needs ``TDSVER="7.0"`` set manually
- ``PtDataSignal('pinj')`` returns "Invalid shot number" for recent shots —
  use ``ImasSignal('nbi.unit.power_launched.data')`` instead
- ``PTDATA2`` TDI expressions hang inside ``fdp run`` due to XRootD
  fork-after-threading — fetch via ``PtDataSignal`` directly
- Only the ``efit01`` MDSplus tree is available via FDP Pelican
- PTData JSON index has a coverage cap (~shot 201,299) — use ImasSignal
  for newer shots
- ``pathlib.Path()`` mangles ``pelican://`` URLs — use f-strings
"""

# The signal imports below pull in libd3 (PTData) and libXrdCl
# transitively. Both libraries read env vars in their static
# initializers — libXrdCl needs XRD_PLUGINCONFDIR to register the
# Pelican plugin, and libd3 needs PTDATA_LOC=1 plus PTDATA_JSON_INDEX_DIR
# to route through Pelican instead of falling back to the legacy
# PTATHENA RPC. Populate the full FDP env (generic + d3d-specific) NOW,
# before those imports, so a bare ``import toksearch_d3d`` works without
# ``fdp run``.
#
# XRD_PLUGINCONFDIR is set FIRST with stdlib only, because just
# *importing* anything from fdp triggers fdp/__init__.py →
# fdp.filesystem → XRootD.client, which loads libXrdCl and reads
# XRD_PLUGINCONFDIR in its static initializer. We have to beat that
# load — even a "from fdp.environment import ..." is too late.
import os as _os
import sys as _sys
_conda_prefix = (_os.environ.get("CONDA_PREFIX")
                 or _os.path.dirname(_os.path.dirname(_sys.executable)))
_os.environ.setdefault(
    "XRD_PLUGINCONFDIR",
    _os.path.join(_conda_prefix, "etc", "xrootd", "client.plugins.d"),
)
from fdp.environment import build_device_config as _fdp_build_device_config
from fdp.environment import _resolve_device_handle as _fdp_resolve_device_handle
from fdp.environment import apply_environment as _fdp_apply_environment
_fdp_cfg = _fdp_build_device_config(_fdp_resolve_device_handle("d3d"))
_fdp_apply_environment(_fdp_cfg, _os.environ)
del _os, _sys, _conda_prefix
del _fdp_build_device_config, _fdp_resolve_device_handle, _fdp_apply_environment, _fdp_cfg

from .signal.ptdata import PtDataSignal
from .signal.ptdata import RDataSignal
from .signal.cake import CakeSignal

try:
    from .signal.imas import ImasSignal, D3dImasSignal, list_imas_fields
except ImportError:
    pass

from .fdp import setup_environment

from . import _version
__version__ = _version.get_versions()['version']

__llm_description__ = (
    "toksearch_d3d - DIII-D signal classes (PtDataSignal, ImasSignal, "
    "CakeSignal) + FDP/Pelican data access via the `fdp` CLI"
)
