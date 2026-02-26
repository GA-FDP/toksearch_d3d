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

_PTDATA_TREENAME = "__ptdata__"


class ImasSignal(Signal):
    """Fetch a single IMAS IDS field as a toksearch Signal.

    Wraps imas_composer's three-stage resolve/fetch/compose cycle and exposes
    the result through the standard Signal interface (gather returns
    ``{'data': array, 'times': array}`` as numpy arrays).

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

    Examples
    --------
    Single signal::

        sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')
        result = sig.gather(202161)
        # result = {'data': array(shape=(n_time,)), 'times': array(shape=(n_time,))}

    Shared composer in a Pipeline::

        composer = ImasComposer()
        pipeline = Pipeline([202161, 203321])
        pipeline.fetch('ip', ImasSignal('equilibrium.time_slice.global_quantities.ip',
                                        composer=composer))
        pipeline.fetch('q95', ImasSignal('equilibrium.time_slice.global_quantities.q_95',
                                         composer=composer))
        records = pipeline.compute_serial()
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

    def gather(self, shot):
        """Fetch and compose the IDS field for the given shot.

        Returns
        -------
        dict
            ``{'data': ndarray}`` always present.
            ``'times': ndarray`` added when an IDS-level time array is available.
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
        out = {'data': np.asarray(results[self.ids_path])}

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
                    out['times'] = np.asarray(
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
