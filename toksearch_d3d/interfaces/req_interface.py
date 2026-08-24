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
import os
import socket

from toksearch.signal.mds import MdsConnectionRegistry
from toksearch_d3d.signal.ptdata import PtDataSignal

_log = logging.getLogger(__name__)

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


def _fetch_remote(req, server):
    if server == _FALLBACK_MDS_SERVER and os.environ.get(_NO_ATLAS_ENV_VAR):
        raise RuntimeError(
            f"Refusing to contact {_FALLBACK_MDS_SERVER}: {_NO_ATLAS_ENV_VAR} is "
            f"set, and this environment cannot reach atlas."
        )
    conn = MdsConnectionRegistry().connect(server)
    conn.openTree(req.treename, req.shot)
    return conn.get(req.mds_path).value


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


def _fetch_tree_group_via_server(server, treename, shot, reqs):
    """Fetch all reqs sharing (treename, shot) in one getMany() round trip against server."""
    conn = MdsConnectionRegistry().connect(server)
    conn.openTree(treename, shot)
    many = conn.getMany()
    for req in reqs:
        many.append(req.mds_path, req.mds_path)
    many.execute()
    results = {}
    for req in reqs:
        try:
            results[req.as_key()] = many.get(req.mds_path).data()
        except Exception as e:
            results[req.as_key()] = e
    return results


def fetch_many_from_req(reqs, server, is_remote):
    """Fetch many reqs at once, preferring a single batched round trip per
    (treename, shot) group -- first against the FDP thin client, then atlas
    -- over toksearch's per-requirement path.

    req objects must additionally implement as_key() (see fetch_from_req's
    docstring for the rest of the req contract).

    ptdata reqs, and everything when an explicit remote server was requested,
    fall through to fetch_from_req unchanged -- batching only applies to
    plain MDSplus tree reqs read via the default fallback chain.

    :return: dict mapping each req.as_key() to its fetched value, or to the
        Exception if fetching failed.
    """
    if is_remote:
        results = {}
        for req in reqs:
            try:
                results[req.as_key()] = fetch_from_req(req, server, is_remote)
            except Exception as e:
                results[req.as_key()] = e
        return results

    results = {}
    tree_groups = {}
    for req in reqs:
        if req.treename == _PTDATA_TREENAME:
            try:
                results[req.as_key()] = fetch_from_req(req, server, is_remote)
            except Exception as e:
                results[req.as_key()] = e
        else:
            tree_groups.setdefault((req.treename, req.shot), []).append(req)

    for (treename, shot), group in tree_groups.items():
        try:
            results.update(
                _fetch_tree_group_via_server(_FDP_THINCLIENT_SERVER, treename, shot, group)
            )
            continue
        except Exception as e:
            _log.warning(
                "Batched FDP thin-client fetch failed for tree=%s shot=%s (%s); "
                "trying atlas",
                treename, shot, e,
            )

        if _atlas_reachable():
            try:
                results.update(
                    _fetch_tree_group_via_server(_FALLBACK_MDS_SERVER, treename, shot, group)
                )
                continue
            except Exception as e:
                _log.warning(
                    "Batched atlas fetch failed for tree=%s shot=%s (%s); "
                    "falling back to per-requirement fetch",
                    treename, shot, e,
                )

        for req in group:
            try:
                results[req.as_key()] = fetch_from_req(req, server, is_remote)
            except Exception as e:
                results[req.as_key()] = e

    return results


def fetch_from_req(req, server, is_remote):
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
        # Explicit remote: use cached connection; connection.get() is a full
        # TDI evaluator so dim_of() and other expressions work fine.
        return _fetch_remote(req, server)
    else:
        # Default: try the FDP thin client, then atlas.
        last_exc = None
        for thin_server in (_FDP_THINCLIENT_SERVER, _FALLBACK_MDS_SERVER):
            try:
                return _fetch_remote(req, thin_server)
            except Exception as e:
                _log.warning(
                    "Thin-client fetch of %s (tree=%s, shot=%s) via %s failed (%s)",
                    req.mds_path, req.treename, req.shot, thin_server, e,
                )
                last_exc = e
        raise last_exc