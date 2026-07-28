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

from toksearch.signal.mds import MdsTreeRegistry, MdsConnectionRegistry
from toksearch_d3d.signal.ptdata import PtDataSignal

_PTDATA_TREENAME = "__ptdata__"

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
        conn = MdsConnectionRegistry().connect(server)
        conn.openTree(req.treename, req.shot)
        return conn.get(req.mds_path).value
    else:
        # Local/Pelican: use cached tree from MdsTreeRegistry then evaluate
        # via tdiExecute(), which handles arbitrary TDI expressions
        # (dim_of(), scalars, node paths) unlike tree.getNode().
        tree = MdsTreeRegistry().open_tree(
            req.treename, req.shot, treepath=location
        )
        return tree.tdiExecute(req.mds_path).data()