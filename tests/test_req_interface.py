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

import os
import unittest
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

from toksearch.interfaces import req_interface as ri
from toksearch_d3d.interfaces import req_interface as d3d_ri


@dataclass
class FakeReq:
    mds_path: str
    shot: int
    treename: str = "__ptdata__"

    def as_key(self):
        return (self.mds_path, self.shot, self.treename)


class TestPatchesGenericReqInterface(unittest.TestCase):
    def test_servers_patched(self):
        self.assertIs(ri._servers, d3d_ri._servers)

    def test_ptdata_registered_as_treeless_group(self):
        self.assertIs(
            ri._TREELESS_GROUP_FETCHERS[d3d_ri._PTDATA_TREENAME],
            d3d_ri._fetch_ptdata_group_via_server,
        )


class TestAtlasReachable(unittest.TestCase):
    def setUp(self):
        # Snapshots os.environ and restores it wholesale on cleanup, so a test
        # that sets the no-atlas var cannot leak it into the rest of the run.
        self.enterContext(patch.dict(os.environ))
        os.environ.pop(d3d_ri._NO_ATLAS_ENV_VAR, None)
        d3d_ri._atlas_reachable_cache = None
        self.addCleanup(setattr, d3d_ri, "_atlas_reachable_cache", None)

    def test_no_atlas_env_var_short_circuits(self):
        os.environ[d3d_ri._NO_ATLAS_ENV_VAR] = "1"
        with patch.object(d3d_ri.socket, "create_connection") as mock_connect:
            self.assertFalse(d3d_ri._atlas_reachable())
        mock_connect.assert_not_called()

    def test_reachable_when_socket_connects(self):
        with patch.object(d3d_ri.socket, "create_connection") as mock_connect:
            self.assertTrue(d3d_ri._atlas_reachable())
        mock_connect.assert_called_once_with(
            (d3d_ri._FALLBACK_MDS_SERVER, d3d_ri._ATLAS_PORT), timeout=2.0
        )

    def test_unreachable_when_socket_raises(self):
        with patch.object(d3d_ri.socket, "create_connection", side_effect=OSError):
            self.assertFalse(d3d_ri._atlas_reachable())

    def test_result_is_cached(self):
        with patch.object(d3d_ri.socket, "create_connection") as mock_connect:
            d3d_ri._atlas_reachable()
            d3d_ri._atlas_reachable()
        mock_connect.assert_called_once()


class TestServers(unittest.TestCase):
    def test_fdp_then_atlas_when_reachable(self):
        with patch.object(d3d_ri, "_atlas_reachable", return_value=True):
            self.assertEqual(
                d3d_ri._servers(),
                [d3d_ri._FDP_THINCLIENT_SERVER, d3d_ri._FALLBACK_MDS_SERVER],
            )

    def test_fdp_only_when_atlas_unreachable(self):
        with patch.object(d3d_ri, "_atlas_reachable", return_value=False):
            self.assertEqual(d3d_ri._servers(), [d3d_ri._FDP_THINCLIENT_SERVER])


class TestFetchPtdataGroupViaServer(unittest.TestCase):
    def test_batches_ptdata_without_opening_a_tree(self):
        # Differing shots still share a single getMany, since ptdata2() needs no
        # open tree.
        reqs = [FakeReq("BT", 12345), FakeReq("IP", 200000)]

        mock_conn = MagicMock()
        mock_many = MagicMock()
        mock_conn.getMany.return_value = mock_many

        values = {
            "d0": 1.0, "t0": 10.0, "r0": [1, 2, 3, 4, 5],
            "d1": 2.0, "t1": 20.0, "r1": [6, 7, 8, 9, 10],
        }

        def _get(name):
            node = MagicMock()
            node.data.return_value = values[name]
            return node

        mock_many.get.side_effect = _get

        with patch.object(d3d_ri, "MdsConnectionRegistry") as mock_registry_cls:
            mock_registry_cls.return_value.connect.return_value = mock_conn
            result = d3d_ri._fetch_ptdata_group_via_server(
                d3d_ri._FDP_THINCLIENT_SERVER, reqs
            )

        mock_registry_cls.return_value.connect.assert_called_once_with(
            d3d_ri._FDP_THINCLIENT_SERVER
        )
        mock_conn.openTree.assert_not_called()
        mock_conn.getMany.assert_called_once()
        # Three TDI forms per req, all in one getMany.
        self.assertEqual(mock_many.append.call_count, 6)
        mock_many.append.assert_any_call("d0", "ptdata2($, $)", "BT", 12345)
        mock_many.append.assert_any_call("t0", "dim_of(ptdata2($, $), 0)", "BT", 12345)
        mock_many.append.assert_any_call("r0", "pthead2($, $), __rarray", "BT", 12345)
        mock_many.append.assert_any_call("d1", "ptdata2($, $)", "IP", 200000)
        mock_many.execute.assert_called_once()
        self.assertEqual(
            result[reqs[0].as_key()],
            {"data": 1.0, "times": 10.0, "rarray": [1, 2, 3, 4, 5]},
        )
        self.assertEqual(
            result[reqs[1].as_key()],
            {"data": 2.0, "times": 20.0, "rarray": [6, 7, 8, 9, 10]},
        )

    def test_per_req_failure_is_stored_in_band(self):
        reqs = [FakeReq("NOSUCHPOINT", 12345)]

        mock_conn = MagicMock()
        mock_many = MagicMock()
        mock_conn.getMany.return_value = mock_many
        mock_many.get.side_effect = ValueError("%TREE-E-NODATA")

        with patch.object(d3d_ri, "MdsConnectionRegistry") as mock_registry_cls:
            mock_registry_cls.return_value.connect.return_value = mock_conn
            result = d3d_ri._fetch_ptdata_group_via_server(
                d3d_ri._FALLBACK_MDS_SERVER, reqs
            )

        self.assertIsInstance(result[reqs[0].as_key()], ValueError)

    def test_pointname_and_shot_go_as_arguments_not_tdi_text(self):
        import numpy as np

        reqs = [FakeReq('BAD"NAME', np.int64(12345))]
        mock_conn = MagicMock()
        mock_many = MagicMock()
        mock_conn.getMany.return_value = mock_many

        with patch.object(d3d_ri, "MdsConnectionRegistry") as mock_registry_cls:
            mock_registry_cls.return_value.connect.return_value = mock_conn
            d3d_ri._fetch_ptdata_group_via_server(d3d_ri._FDP_THINCLIENT_SERVER, reqs)

        name, exp, pointname, shot = mock_many.append.call_args_list[0].args
        self.assertEqual(exp, "ptdata2($, $)")
        self.assertEqual(pointname, 'BAD"NAME')
        self.assertIs(type(shot), int)


class TestFetchManyFromReqPtdata(unittest.TestCase):
    def test_ptdata_reqs_routed_through_generic_fetch(self):
        reqs = [FakeReq("BT", 12345), FakeReq("IP", 200000)]

        with patch.object(d3d_ri, "_atlas_reachable", return_value=False), \
                patch.object(d3d_ri, "_fetch_ptdata_group_via_server") as mock_ptdata, \
                patch.dict(
                    ri._TREELESS_GROUP_FETCHERS,
                    {d3d_ri._PTDATA_TREENAME: mock_ptdata},
                ):
            mock_ptdata.side_effect = lambda server, group: {
                r.as_key(): f"{server}-ptdata" for r in group
            }
            result = ri.fetch_many_from_req(reqs)

        mock_ptdata.assert_called_once_with(d3d_ri._FDP_THINCLIENT_SERVER, reqs)
        self.assertEqual(
            result[reqs[1].as_key()], f"{d3d_ri._FDP_THINCLIENT_SERVER}-ptdata"
        )


if __name__ == "__main__":
    unittest.main()
