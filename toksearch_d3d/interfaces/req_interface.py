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

import logging

from MDSplus.mdsExceptions import MDSplusException
from toksearch.signal.mds import MdsTreeRegistry, MdsConnectionRegistry
from toksearch_d3d.signal.ptdata import PtDataSignal

_log = logging.getLogger(__name__)

_PTDATA_TREENAME = "__ptdata__"
_FALLBACK_MDS_SERVER = "atlas.gat.com"

# (treename, shot) pairs where opening the tree at the origin/local path is
# known to fail. Populated the first time MdsTreeRegistry().open_tree() raises
# for a given pair -- every other requirement on that same tree+shot would
# fail identically (same call, same args), so once seen, skip straight to the
# fallback server instead of re-paying a failing origin round trip per field.
_ORIGIN_OPEN_FAILURES = set()


def _fetch_remote(req, server):
    conn = MdsConnectionRegistry().connect(server)
    conn.openTree(req.treename, req.shot)
    return conn.get(req.mds_path).value


def fetch_from_req(req, server, is_remote, location):
    """Fetch a signal for a given req using MdsSignal or PtDataSignal.
    req is an instance of the Requirement class below. Despite its name 
    mds_path can also be a PTDATA path.

    class Requirement:
        mds_path: str
        shot: int
        treename: str = "ELECTRONS"

    """
    if req.treename == _PTDATA_TREENAME:
        sig = PtDataSignal(req.mds_path, keep_header=True, fetch_units=False)
        result = sig.gather(req.shot)
        return {
            'data': result['data'],
            'times': result['times'],
            'rarray': result['header'].rarray.copy(),
        }
    elif is_remote:
        # Remote: use cached connection; connection.get() is a full TDI
        # evaluator so dim_of() and other expressions work fine.
        return _fetch_remote(req, server)
    else:
        # Local/Pelican: use cached tree from MdsTreeRegistry then evaluate
        # via tdiExecute(), which handles arbitrary TDI expressions
        # (dim_of(), scalars, node paths) unlike tree.getNode().
        key = (req.treename, req.shot)
        if key in _ORIGIN_OPEN_FAILURES:
            return _fetch_remote(req, _FALLBACK_MDS_SERVER)

        try:
            tree = MdsTreeRegistry().open_tree(
                req.treename, req.shot, treepath=location
            )
        except MDSplusException as e:
            _log.warning(
                "MDSplus error opening tree=%s shot=%s at origin/local (%s); "
                "using remote://%s for the rest of this tree+shot",
                req.treename, req.shot, e, _FALLBACK_MDS_SERVER,
            )
            _ORIGIN_OPEN_FAILURES.add(key)
            return _fetch_remote(req, _FALLBACK_MDS_SERVER)

        try:
            return tree.tdiExecute(req.mds_path).data()
        except MDSplusException as e:
            _log.warning(
                "MDSplus error fetching %s (tree=%s, shot=%s) from origin "
                "(%s); falling back to remote://%s",
                req.mds_path, req.treename, req.shot, e, _FALLBACK_MDS_SERVER,
            )
            return _fetch_remote(req, _FALLBACK_MDS_SERVER)