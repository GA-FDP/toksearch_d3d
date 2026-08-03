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

from toksearch_d3d.interfaces import req_interface as ri


@dataclass
class FakeReq:
    mds_path: str
    shot: int
    treename: str = "ELECTRONS"

    def as_key(self):
        return (self.mds_path, self.shot, self.treename)


class TestAtlasReachable(unittest.TestCase):
    def setUp(self):
        ri._atlas_reachable_cache = None
        self._env_backup = os.environ.pop(ri._NO_ATLAS_ENV_VAR, None)

    def tearDown(self):
        ri._atlas_reachable_cache = None
        if self._env_backup is not None:
            os.environ[ri._NO_ATLAS_ENV_VAR] = self._env_backup

    def test_no_atlas_env_var_short_circuits(self):
        os.environ[ri._NO_ATLAS_ENV_VAR] = "1"
        with patch.object(ri.socket, "create_connection") as mock_connect:
            self.assertFalse(ri._atlas_reachable())
        mock_connect.assert_not_called()

    def test_reachable_when_socket_connects(self):
        with patch.object(ri.socket, "create_connection") as mock_connect:
            mock_connect.return_value.__enter__ = MagicMock()
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            self.assertTrue(ri._atlas_reachable())
        mock_connect.assert_called_once_with(
            (ri._FALLBACK_MDS_SERVER, ri._ATLAS_PORT), timeout=2.0
        )

    def test_unreachable_when_socket_raises(self):
        with patch.object(ri.socket, "create_connection", side_effect=OSError):
            self.assertFalse(ri._atlas_reachable())

    def test_result_is_cached(self):
        with patch.object(ri.socket, "create_connection") as mock_connect:
            mock_connect.return_value.__enter__ = MagicMock()
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            ri._atlas_reachable()
            ri._atlas_reachable()
        mock_connect.assert_called_once()


class TestFetchManyFromReq(unittest.TestCase):
    def setUp(self):
        ri._atlas_reachable_cache = None

    def tearDown(self):
        ri._atlas_reachable_cache = None

    def test_ptdata_reqs_bypass_batching(self):
        req = FakeReq("BT", 12345, "__ptdata__")
        with patch.object(ri, "fetch_from_req", return_value="ptdata-value") as mock_fetch, \
             patch.object(ri, "_atlas_reachable", return_value=True), \
             patch.object(ri, "_fetch_tree_group_via_atlas") as mock_batch:
            result = ri.fetch_many_from_req([req], None, False, None)

        mock_fetch.assert_called_once_with(req, None, False, None)
        mock_batch.assert_not_called()
        self.assertEqual(result[req.as_key()], "ptdata-value")

    def test_explicit_remote_bypasses_batching_entirely(self):
        reqs = [FakeReq("BT", 12345, "TREE_A"), FakeReq("IP", 12345, "TREE_A")]
        with patch.object(ri, "fetch_from_req", return_value="v") as mock_fetch, \
             patch.object(ri, "_atlas_reachable", return_value=True), \
             patch.object(ri, "_fetch_tree_group_via_atlas") as mock_batch:
            ri.fetch_many_from_req(reqs, "atlas.gat.com", True, "remote://atlas.gat.com")

        self.assertEqual(mock_fetch.call_count, 2)
        mock_batch.assert_not_called()

    def test_explicit_location_bypasses_batching_entirely(self):
        reqs = [FakeReq("BT", 12345, "TREE_A")]
        with patch.object(ri, "fetch_from_req", return_value="v") as mock_fetch, \
             patch.object(ri, "_atlas_reachable", return_value=True), \
             patch.object(ri, "_fetch_tree_group_via_atlas") as mock_batch:
            ri.fetch_many_from_req(reqs, None, False, "/fusion/projects/trees")

        mock_fetch.assert_called_once()
        mock_batch.assert_not_called()

    def test_tree_reqs_batched_by_treename_shot_when_atlas_reachable(self):
        reqs = [
            FakeReq("BT", 12345, "TREE_A"),
            FakeReq("IP", 12345, "TREE_A"),
            FakeReq("NE", 12345, "TREE_B"),
        ]
        with patch.object(ri, "_atlas_reachable", return_value=True), \
             patch.object(ri, "_fetch_tree_group_via_atlas") as mock_batch, \
             patch.object(ri, "fetch_from_req") as mock_fetch:
            mock_batch.side_effect = lambda treename, shot, group: {
                r.as_key(): f"{treename}-{shot}" for r in group
            }
            result = ri.fetch_many_from_req(reqs, None, False, None)

        self.assertEqual(mock_batch.call_count, 2)
        mock_fetch.assert_not_called()
        self.assertEqual(result[reqs[0].as_key()], "TREE_A-12345")
        self.assertEqual(result[reqs[2].as_key()], "TREE_B-12345")

    def test_falls_back_to_per_item_when_atlas_unreachable(self):
        reqs = [FakeReq("BT", 12345, "TREE_A")]
        with patch.object(ri, "_atlas_reachable", return_value=False), \
             patch.object(ri, "_fetch_tree_group_via_atlas") as mock_batch, \
             patch.object(ri, "fetch_from_req", return_value="v") as mock_fetch:
            result = ri.fetch_many_from_req(reqs, None, False, None)

        mock_batch.assert_not_called()
        mock_fetch.assert_called_once_with(reqs[0], None, False, None)
        self.assertEqual(result[reqs[0].as_key()], "v")

    def test_falls_back_to_per_item_when_batch_raises(self):
        reqs = [FakeReq("BT", 12345, "TREE_A"), FakeReq("IP", 12345, "TREE_A")]
        with patch.object(ri, "_atlas_reachable", return_value=True), \
             patch.object(ri, "_fetch_tree_group_via_atlas", side_effect=RuntimeError("down")), \
             patch.object(ri, "fetch_from_req", return_value="v") as mock_fetch:
            result = ri.fetch_many_from_req(reqs, None, False, None)

        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(result[reqs[0].as_key()], "v")

    def test_per_item_failure_is_stored_in_band(self):
        req = FakeReq("NOSUCHPOINT", 12345, "__ptdata__")
        with patch.object(ri, "fetch_from_req", side_effect=ValueError("%TREE-E-NODATA")):
            result = ri.fetch_many_from_req([req], None, False, None)

        self.assertIsInstance(result[req.as_key()], ValueError)


class TestFetchTreeGroupViaAtlas(unittest.TestCase):
    def test_batches_group_via_get_many(self):
        reqs = [FakeReq("BT", 12345, "TREE_A"), FakeReq("IP", 12345, "TREE_A")]

        mock_conn = MagicMock()
        mock_many = MagicMock()
        mock_conn.getMany.return_value = mock_many

        def _get(name):
            data = {"BT": MagicMock(), "IP": MagicMock()}
            data["BT"].data.return_value = 1.0
            data["IP"].data.return_value = 2.0
            return data[name]

        mock_many.get.side_effect = _get

        with patch.object(ri, "MdsConnectionRegistry") as mock_registry_cls:
            mock_registry_cls.return_value.connect.return_value = mock_conn
            result = ri._fetch_tree_group_via_atlas("TREE_A", 12345, reqs)

        mock_conn.openTree.assert_called_once_with("TREE_A", 12345)
        self.assertEqual(mock_many.append.call_count, 2)
        mock_many.execute.assert_called_once()
        self.assertEqual(result[reqs[0].as_key()], 1.0)
        self.assertEqual(result[reqs[1].as_key()], 2.0)

    def test_per_key_failure_is_stored_in_band(self):
        reqs = [FakeReq("BT", 12345, "TREE_A")]

        mock_conn = MagicMock()
        mock_many = MagicMock()
        mock_conn.getMany.return_value = mock_many
        mock_many.get.side_effect = ValueError("%TREE-E-NODATA")

        with patch.object(ri, "MdsConnectionRegistry") as mock_registry_cls:
            mock_registry_cls.return_value.connect.return_value = mock_conn
            result = ri._fetch_tree_group_via_atlas("TREE_A", 12345, reqs)

        self.assertIsInstance(result[reqs[0].as_key()], ValueError)


if __name__ == "__main__":
    unittest.main()
