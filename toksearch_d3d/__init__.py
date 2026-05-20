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

    TDSVER="7.0" pixi run fdp run python <script.py>

``setup_environment`` and ``fdp run`` apply the same defaults: XRootD plugin
paths, MDSplus tree paths, PTData configuration. The bearer token is
resolved from the ``bearer_token`` argument, then ``$BEARER_TOKEN``, then
``~/.fdp/token``.

``TDSVER="7.0"`` is required whenever the script connects to d3drdb (the
default config sets it, so this only matters if you've overridden it).

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
Only available when ``imas_composer`` is installed.

**Leaf path** — fetches one field::

    ImasSignal('equilibrium.time_slice.global_quantities.ip')

**Prefix path** — fetches all fields under a subtree::

    ImasSignal('equilibrium.time_slice.global_quantities')

**Ragged arrays**: channel-indexed data returns a numpy object array.
Use ``split_by='channel'`` for a dict keyed by channel name::

    ImasSignal('thomson_scattering.channel.n_e.data', split_by='channel')

**NBI power recipe** (object array of 8 per-unit time series)::

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
    core_profiles.profiles_1d.electrons.density_thermal
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

- ``TDSVER="7.0"`` must be set before connecting to d3drdb
- ``PtDataSignal('pinj')`` returns "Invalid shot number" for recent shots —
  use ``ImasSignal('nbi.unit.power_launched.data')`` instead
- ``PTDATA2`` TDI expressions hang inside ``fdp run`` due to XRootD
  fork-after-threading — fetch via ``PtDataSignal`` directly
- Only the ``efit01`` MDSplus tree is available via FDP Pelican
- PTData JSON index has a coverage cap (~shot 201,299) — use ImasSignal
  for newer shots
- ``pathlib.Path()`` mangles ``pelican://`` URLs — use f-strings
"""

# libXrdCl reads XRD_PLUGINCONFDIR in its static initializer, and the signal
# imports below pull libXrdCl in transitively (MDSplus → libTreeShr →
# libfdpio2 → libXrdCl). Populate FDP generic env vars NOW, before that chain
# loads, so the Pelican plugin registers correctly even when callers use a
# bare ``import toksearch_d3d`` instead of going through ``fdp run``.
import os as _os
from fdp.environment import _generic_config as _fdp_generic_config
from fdp.environment import apply_environment as _fdp_apply_environment
_fdp_apply_environment(_fdp_generic_config(), _os.environ)
del _os, _fdp_generic_config, _fdp_apply_environment

from .signal.ptdata import PtDataSignal
from .signal.ptdata import RDataSignal
from .signal.cake import CakeSignal

try:
    from .signal.imas import ImasSignal, list_imas_fields
except ImportError:
    pass

from .fdp import setup_environment

from . import _version
__version__ = _version.get_versions()['version']

__llm_description__ = (
    "toksearch_d3d - DIII-D signal classes (PtDataSignal, ImasSignal, "
    "CakeSignal) + FDP/Pelican data access via the `fdp` CLI"
)
