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

"""DIII-D servers and PTDATA support for toksearch.interfaces.req_interface.

Importing this module patches the generic req_interface: groups are fetched
from the FDP thin client first, then atlas, and reqs with treename
"__ptdata__" are batched as tree-less ptdata2() TDI.
"""

import os
import socket

from toksearch.interfaces import req_interface as _ri
from toksearch.signal.mds import MdsConnectionRegistry

_PTDATA_TREENAME = "__ptdata__"
_FDP_THINCLIENT_SERVER = "fdp://fdp-d3d-origin.nationalresearchplatform.org:8443/mdsip"
_FALLBACK_MDS_SERVER = "atlas.gat.com"
_ATLAS_PORT = 8000

# Set in environments (e.g. GitHub CI) that cannot reach atlas, so a failed
# FDP thin-client fetch falls through to an atlas attempt that raises
# immediately instead of hanging on an unreachable connection.
_NO_ATLAS_ENV_VAR = "TOKSEARCH_D3D_NO_ATLAS"

# Tri-state cache (None = unchecked) for whether atlas is directly reachable
# from this process. Populated on first use by _atlas_reachable().
_atlas_reachable_cache = None


def _atlas_reachable(timeout=2.0):
    """Whether atlas is directly reachable from this process, cached process-wide.

    A raw TCP precheck is used instead of just trying MDSplus.Connection and
    catching failure, because MDSplus.Connection connects via a native call
    with no timeout -- on an unreachable host that can hang far longer than
    the toksearch round trip this check exists to avoid.
    """
    global _atlas_reachable_cache
    if os.environ.get(_NO_ATLAS_ENV_VAR):
        return False
    if _atlas_reachable_cache is None:
        try:
            with socket.create_connection((_FALLBACK_MDS_SERVER, _ATLAS_PORT), timeout=timeout):
                _atlas_reachable_cache = True
        except OSError:
            _atlas_reachable_cache = False
    return _atlas_reachable_cache


def _servers():
    """FDP thin client first, then atlas when it is directly reachable."""
    servers = [_FDP_THINCLIENT_SERVER]
    if _atlas_reachable():
        servers.append(_FALLBACK_MDS_SERVER)
    return servers


def _fetch_ptdata_group_via_server(server, reqs):
    """Fetch all ptdata reqs in one getMany() round trip against server.

    ptdata2() needs no open tree, so every ptdata req -- regardless of shot --
    batches into a single getMany. Each req expands to the three TDI forms the
    omas machine mappings emit (data, times, rarray) and is reassembled into the
    {data, times, rarray} dict the compose functions expect. Despite its name
    req.mds_path is the PTDATA point name.
    """
    conn = MdsConnectionRegistry().connect(server)
    many = conn.getMany()
    for i, req in enumerate(reqs):
        many.append(f"d{i}", f'ptdata2("{req.mds_path}", {req.shot})')
        many.append(f"t{i}", f'dim_of(ptdata2("{req.mds_path}", {req.shot}), 0)')
        many.append(f"r{i}", f'pthead2("{req.mds_path}", {req.shot}), __rarray')
    many.execute()
    results = {}
    for i, req in enumerate(reqs):
        try:
            results[_ri._req_key(req)] = {
                "data": many.get(f"d{i}").data(),
                "times": many.get(f"t{i}").data(),
                "rarray": many.get(f"r{i}").data(),
            }
        except Exception as e:
            results[_ri._req_key(req)] = e
    return results


_ri._servers = _servers
_ri._TREELESS_GROUP_FETCHERS[_PTDATA_TREENAME] = _fetch_ptdata_group_via_server
