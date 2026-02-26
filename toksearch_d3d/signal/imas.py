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
Signal classes that expose imas_composer output through the toksearch Pipeline API.

Requires imas_composer to be installed (optional dependency).
"""

import numpy as np
from urllib.parse import urlparse

from toksearch import Signal
from toksearch.signal.mds import MdsSignal, MdsTreeRegistry, MdsConnectionRegistry, MdsTreePath
from toksearch_d3d.signal.ptdata import PtDataSignal
from imas_composer import ImasComposer

try:
    import awkward as ak
    _AWKWARD_AVAILABLE = True
except ImportError:
    _AWKWARD_AVAILABLE = False
    ak = None

_PTDATA_TREENAME = "__ptdata__"


def _to_numpy(val):
    """Convert a compose() value to a numpy array.

    For regular arrays or uniformly-shaped ak.Array: returns np.ndarray.
    For ragged ak.Array: returns a numpy object array whose elements are
    1-D numpy arrays, one per outer entry (e.g. one per channel or time slice).
    """
    if _AWKWARD_AVAILABLE and isinstance(val, ak.Array):
        try:
            return np.asarray(val)
        except (ValueError, TypeError):
            return np.array([np.asarray(row) for row in val], dtype=object)
    return np.asarray(val)


class ImasSignal(Signal):
    """Fetch a single IMAS IDS field as a toksearch Signal.

    Wraps imas_composer's three-stage resolve/fetch/compose cycle and exposes
    the result through the standard Signal interface (gather returns
    ``{'data': array, 'times': array}`` as numpy arrays).

    For IDS fields that return ragged data (e.g. Thomson channel time series,
    equilibrium boundary outlines), ``data`` will be a numpy object array whose
    elements are 1-D numpy arrays.  Pass ``split_by='channel'`` to instead
    receive a dict keyed by channel name (or integer index).

    Parameters
    ----------
    ids_path:
        Full IMAS path, e.g. ``'equilibrium.time_slice.global_quantities.ip'``.
    composer:
        Optional shared ``ImasComposer`` instance.  If not supplied a default
        instance is created from the remaining keyword arguments.  Sharing one
        composer across many ``ImasSignal`` objects avoids repeated mapper
        initialisation.
    efit_tree, efit_run_id:
        Passed to ``ImasComposer`` when ``composer=None``.
    profiles_tree, profiles_run_id:
        Passed to ``ImasComposer`` when ``composer=None``.
    fast_ece:
        Passed to ``ImasComposer`` when ``composer=None``.
    location:
        MDSplus tree location.

        - ``None`` — use environment variables (``{TREENAME}_path`` or
          ``default_tree_path``).
        - A path string, e.g. ``'/path/to/trees'`` — local trees at that path.
        - ``'remote://atlas.gat.com'`` — remote MDSplus server.
        - An ``MdsTreePath`` object — passed directly to ``MdsSignal``.
    max_resolve_iterations:
        Maximum number of resolve/fetch iterations before giving up.
    split_by:
        How to handle channel-indexed data.

        - ``None`` (default) — return ``{'data': ndarray}`` as usual; ragged
          fields become numpy object arrays.
        - ``'channel'`` — split the composed array along the channel axis and
          return a dict keyed by channel name (or integer index when names are
          unavailable).  Each value is
          ``{'data': ndarray, 'units': dict}`` plus ``'times': ndarray`` when
          ``times_ids_path`` is set.
    times_ids_path:
        IDS path whose composed value supplies per-channel times when
        ``split_by='channel'``.

        - ``None`` (default) — no ``'times'`` key in per-channel dicts.
        - ``'auto'`` — derive from ``ids_path`` by replacing the terminal
          ``.data`` or ``.data_error_upper`` component with ``.time``.
        - any other string — use that path verbatim.
    units:
        Dict included verbatim as the ``'units'`` key in every per-channel
        entry when ``split_by='channel'``.  Keys are dimension names, e.g.
        ``{'data': 'm^-3', 'times': 's'}``.  Defaults to ``{}``.

    Examples
    --------
    Scalar signal::

        sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')
        result = sig.gather(202161)
        # result = {'data': array(shape=(n_time,)), 'times': array(shape=(n_time,))}

    Ragged field (default)::

        sig = ImasSignal('thomson_scattering.channel.n_e.data')
        result = sig.gather(202161)
        # result = {'data': array(shape=(n_channels,), dtype=object)}
        # result['data'][0]  →  1-D float64 array for channel 0

    Channel-split field with times and units::

        sig = ImasSignal(
            'thomson_scattering.channel.n_e.data',
            split_by='channel',
            times_ids_path='auto',
            units={'data': 'm^-3', 'times': 's'},
        )
        result = sig.gather(202161)
        # result = {
        #   'TS_core_r+0_0': {'data': array(...), 'times': array(...),
        #                      'units': {'data': 'm^-3', 'times': 's'}},
        #   ...
        # }
    """

    def __init__(
        self,
        ids_path,
        composer=None,
        efit_tree='EFIT01',
        efit_run_id='',
        profiles_tree='ZIPFIT01',
        profiles_run_id='',
        fast_ece=False,
        location=None,
        max_resolve_iterations=10,
        split_by=None,
    times_ids_path=None,
    units=None,
    ):
        super().__init__()
        self.set_dims(['times'])
        self.ids_path = ids_path
        self._composer = composer or ImasComposer(
            efit_tree=efit_tree,
            efit_run_id=efit_run_id,
            profiles_tree=profiles_tree,
            profiles_run_id=profiles_run_id,
            fast_ece=fast_ece,
        )
        self._max_iter = max_resolve_iterations
        self._split_by = split_by
        self._times_ids_path = times_ids_path
        self._units = units if units is not None else {}
        self._parse_location(location)

    def _parse_location(self, location):
        """Store location and determine cleanup mode."""
        self._location = location
        if isinstance(location, str):
            parsed = urlparse(location)
            self._is_remote = parsed.scheme == 'remote'
            self._server = parsed.netloc if self._is_remote else None
        else:
            self._is_remote = False
            self._server = None

    def _fetch_requirement(self, req):
        """Fetch a single imas_composer Requirement using MdsSignal or PtDataSignal."""
        if req.treename == _PTDATA_TREENAME:
            sig = PtDataSignal(req.mds_path, keep_header=True, fetch_units=False)
            result = sig.gather(req.shot)
            return {
                'data': result['data'],
                'times': result['times'],
                'rarray': result['header'].rarray.copy(),
            }
        else:
            sig = MdsSignal(req.mds_path, req.treename, location=self._location)
            return sig.gather(req.shot)['data']

    def _resolve_times_ids_path(self):
        """Return the concrete times IDS path to use, or None."""
        if self._times_ids_path is None:
            return None
        if self._times_ids_path != 'auto':
            return self._times_ids_path
        path = self.ids_path
        if path.endswith('.data_error_upper'):
            return path[:-len('.data_error_upper')] + '.time'
        if path.endswith('.data'):
            return path[:-len('.data')] + '.time'
        return None

    def _split_by_channel(self, shot, composed_val, raw_data):
        """Split a channel-indexed composed value into a dict keyed by channel name."""
        ids_name = self.ids_path.split('.')[0]

        # --- channel names ---
        names = None
        name_path = f'{ids_name}.channel.name'
        try:
            ts, tr = {}, []
            for _ in range(3):
                ts, tr = self._composer.resolve([name_path], shot, raw_data)
                if ts.get(name_path):
                    break
                for req in tr:
                    raw_data[req.as_key()] = self._fetch_requirement(req)
            if ts.get(name_path):
                names = np.asarray(
                    self._composer.compose([name_path], shot, raw_data)[name_path]
                )
        except Exception:
            pass

        # --- per-channel times (optional) ---
        times_val = None
        times_path = self._resolve_times_ids_path()
        if times_path:
            try:
                ts, tr = {}, []
                for _ in range(self._max_iter):
                    ts, tr = self._composer.resolve([times_path], shot, raw_data)
                    if ts.get(times_path):
                        break
                    for req in tr:
                        raw_data[req.as_key()] = self._fetch_requirement(req)
                if ts.get(times_path):
                    times_val = self._composer.compose(
                        [times_path], shot, raw_data
                    )[times_path]
            except Exception:
                pass

        # --- build result ---
        result = {}
        for i, row in enumerate(composed_val):
            key = str(names[i]) if (names is not None and i < len(names)) else str(i)
            entry = {
                'data':  np.asarray(row),
                'units': dict(self._units),
            }
            if times_val is not None:
                try:
                    entry['times'] = np.asarray(times_val[i])
                except Exception:
                    pass
            result[key] = entry
        return result

    def gather(self, shot):
        """Fetch and compose the IDS field for the given shot.

        Returns
        -------
        dict
            ``{'data': ndarray}`` always present (unless ``split_by='channel'``).
            ``'times': ndarray`` added when an IDS-level time array is available.
            When ``split_by='channel'``: a plain dict keyed by channel name,
            each value ``{'data': ndarray}``.
        """
        raw_data = {}

        # Phase 1: iteratively resolve and fetch requirements for the primary path
        for _ in range(self._max_iter):
            status, requirements = self._composer.resolve(
                [self.ids_path], shot, raw_data
            )
            if status[self.ids_path]:
                break
            for req in requirements:
                raw_data[req.as_key()] = self._fetch_requirement(req)

        # Phase 2: compose the primary path
        results = self._composer.compose([self.ids_path], shot, raw_data)
        composed = results[self.ids_path]

        if self._split_by == 'channel':
            return self._split_by_channel(shot, composed, raw_data)

        out = {'data': _to_numpy(composed)}

        # Phase 3: best-effort time array (reuses already-fetched raw_data to
        # avoid redundant MDSplus opens when the time is a direct requirement)
        ids_name = self.ids_path.split('.')[0]
        time_path = f'{ids_name}.time'
        if time_path != self.ids_path:
            try:
                ts, tr = {}, []
                for _ in range(3):
                    ts, tr = self._composer.resolve([time_path], shot, raw_data)
                    if ts[time_path]:
                        break
                    for req in tr:
                        raw_data[req.as_key()] = self._fetch_requirement(req)
                if ts.get(time_path, False):
                    out['times'] = _to_numpy(
                        self._composer.compose([time_path], shot, raw_data)[time_path]
                    )
            except Exception:
                pass  # static field or unavailable — omit times key

        return out

    def cleanup_shot(self, shot):
        if self._is_remote:
            try:
                MdsConnectionRegistry().connect(self._server).closeAllTrees()
            except Exception:
                pass
        else:
            MdsTreeRegistry().close_all_trees()

    def cleanup(self):
        if self._is_remote:
            try:
                MdsConnectionRegistry().disconnect(self._server)
            except Exception:
                pass
        else:
            MdsTreeRegistry().close_all_trees()
