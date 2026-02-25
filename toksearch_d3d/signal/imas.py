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
from toksearch.signal.mds import MdsTreeRegistry, MdsConnectionRegistry, MdsTreePath
from imas_composer import ImasComposer

try:
    from ptdata import PtDataFetcher
    _PTDATA_AVAILABLE = True
except ImportError:
    _PTDATA_AVAILABLE = False
    PtDataFetcher = None

_PTDATA_TREENAME = "__ptdata__"


def _fetch_requirement(req, is_remote, server, treepath):
    """Fetch a single imas_composer Requirement and return the raw value.

    Requirements with ``treename == "__ptdata__"`` are fetched via
    ``PtDataFetcher`` and returned as a dict with keys ``'data'``,
    ``'times'``, and ``'rarray'`` — matching the format expected by the
    imas_composer mappers that consume ptdata.

    All other requirements are fetched from MDSplus using the appropriate
    registry (local or remote).
    """
    if req.treename == _PTDATA_TREENAME:
        if not _PTDATA_AVAILABLE:
            raise RuntimeError(
                "ptdata package is required for ptdata requirements but is not installed."
            )
        fetcher = PtDataFetcher(req.mds_path, req.shot)
        result = fetcher.fetch(fetch_times=True)
        return {
            'data': result['data'],
            'times': result['times'],
            'rarray': fetcher.header.rarray.copy(),
        }
    elif is_remote:
        conn = MdsConnectionRegistry().connect(server)
        conn.openTree(req.treename, req.shot)
        return conn.get(req.mds_path).value
    else:
        tree = MdsTreeRegistry().open_tree(req.treename, req.shot, treepath=treepath)
        return tree.getNode(req.mds_path).data()


class ImasSignal(Signal):
    """Fetch a single IMAS IDS field as a toksearch Signal.

    Wraps imas_composer's three-stage resolve/fetch/compose cycle and exposes
    the result through the standard Signal interface (gather returns
    ``{'data': array, 'times': array}``).

    Fields that return ``ak.Array`` (e.g. ragged boundary outlines) are passed
    through as-is; ``fetch_as_xarray()`` will not work for those fields.

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
        - An ``MdsTreePath`` object — passed directly to ``MdsTreeRegistry``.
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
        """Determine local vs remote fetch mode from the location argument."""
        if location is None or isinstance(location, MdsTreePath):
            self._is_remote = False
            self._treepath = location  # None → use env vars; MdsTreePath → use as-is
            self._server = None
        else:
            parsed = urlparse(location)
            if parsed.scheme == 'remote':
                self._is_remote = True
                self._server = parsed.netloc
                self._treepath = None
            else:
                self._is_remote = False
                self._server = None
                self._treepath = parsed.path or None  # string path or None

    def _fetch_requirement(self, req):
        return _fetch_requirement(req, self._is_remote, self._server, self._treepath)

    def gather(self, shot):
        """Fetch and compose the IDS field for the given shot.

        Returns
        -------
        dict
            ``{'data': array}`` always present.
            ``'times'`` added when an IDS-level time array is available.
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
        out = {'data': results[self.ids_path]}

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


class ImasBatchSignal:
    """Fetch multiple IMAS IDS fields sharing a single resolve/fetch loop.

    Unlike ``ImasSignal``, this class does **not** inherit from ``Signal`` — it
    returns a plain dict keyed by IDS path, not a ``{data, times}`` dict.  Use
    ``pipeline.map()`` to extract individual arrays.

    Parameters
    ----------
    ids_paths:
        List of full IMAS paths to fetch together.
    composer, efit_tree, efit_run_id, profiles_tree, profiles_run_id, fast_ece:
        Same as ``ImasSignal``.
    location:
        Same as ``ImasSignal``.
    max_resolve_iterations:
        Maximum number of resolve/fetch iterations.

    Examples
    --------
    ::

        sig = ImasBatchSignal([
            'equilibrium.time',
            'equilibrium.time_slice.global_quantities.ip',
            'equilibrium.time_slice.profiles_1d.psi',
        ])
        pipeline.fetch('eq', sig)
        pipeline.map(lambda rec: {
            'eq_time': rec['eq']['equilibrium.time'],
            'ip':      rec['eq']['equilibrium.time_slice.global_quantities.ip'],
        })
    """

    def __init__(
        self,
        ids_paths,
        composer=None,
        efit_tree='EFIT01',
        efit_run_id='',
        profiles_tree='ZIPFIT01',
        profiles_run_id='',
        fast_ece=False,
        location=None,
        max_resolve_iterations=10,
    ):
        self.ids_paths = list(ids_paths)
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
        if location is None or isinstance(location, MdsTreePath):
            self._is_remote = False
            self._treepath = location
            self._server = None
        else:
            parsed = urlparse(location)
            if parsed.scheme == 'remote':
                self._is_remote = True
                self._server = parsed.netloc
                self._treepath = None
            else:
                self._is_remote = False
                self._server = None
                self._treepath = parsed.path or None

    def _fetch_requirement(self, req):
        return _fetch_requirement(req, self._is_remote, self._server, self._treepath)

    def gather(self, shot):
        """Fetch and compose all IDS paths for the given shot.

        Returns
        -------
        dict
            Keyed by IDS path, values are numpy arrays (or ``ak.Array``).
        """
        raw_data = {}
        for _ in range(self._max_iter):
            status, requirements = self._composer.resolve(
                self.ids_paths, shot, raw_data
            )
            if all(status.values()):
                break
            for req in requirements:
                raw_data[req.as_key()] = self._fetch_requirement(req)
        return self._composer.compose(self.ids_paths, shot, raw_data)

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
