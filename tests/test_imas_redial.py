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
Tests for connection recovery in ImasSignal's remote requirement fetch.

A failed call can leave the process's MDSplus.Connection unusable rather than
merely unlucky. Over fdp:// the relay retires its session whenever a call
fails -- above all a call that overran the relay's timeout -- and answers every
later call on that token with 502 "unknown or expired session".
MdsConnectionRegistry hands the same Connection object to every caller in the
process for its whole life, so without this the poisoning is permanent: one
slow fetch takes down every later fetch in the process.

`toksearch`'s MdsRemoteSignal.gather already recovers this way, but
`_fetch_requirement` calls conn.get() directly -- it needs a full TDI evaluator
-- so it does not inherit that.

These are pure unit tests: the registry is mocked, so no network access.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from MDSplus.connection import MdsIpException
from MDSplus.mdsExceptions import MDSplusERROR, TreeNODATA


SERVER = "atlas.gat.com"
LEAF = "equilibrium.time_slice.global_quantities.ip"


def _req(treename="efit01", shot=123, mds_path=r"\ipmhd"):
    return SimpleNamespace(treename=treename, shot=shot, mds_path=mds_path)


class RemoteRequirementFetchTestCase(unittest.TestCase):
    """Drives ImasSignal._fetch_requirement with the connection registry mocked."""

    @classmethod
    def setUpClass(cls):
        from imas_composer import ImasComposer

        from toksearch_d3d import ImasSignal

        cls.composer = ImasComposer()
        cls.ImasSignal = ImasSignal

    def setUp(self):
        self.sig = self.ImasSignal(
            LEAF, composer=self.composer, location=f"remote://{SERVER}"
        )
        self.assertTrue(self.sig._is_remote, "test needs the remote fetch path")

    def _registry(self, get_side_effect=None, open_tree_side_effect=None):
        """A mocked MdsConnectionRegistry whose connection can be made to fail."""
        conn = mock.MagicMock()
        conn.get.return_value = SimpleNamespace(value="DATA")
        if get_side_effect is not None:
            conn.get.side_effect = get_side_effect
        if open_tree_side_effect is not None:
            conn.openTree.side_effect = open_tree_side_effect
        registry = mock.MagicMock()
        registry.connect.return_value = conn
        factory = mock.MagicMock(return_value=registry)
        return factory, registry, conn

    def _patched(self, factory):
        return mock.patch(
            "toksearch_d3d.signal.imas.MdsConnectionRegistry", factory
        )


class TestSucceedsWithoutRedial(RemoteRequirementFetchTestCase):
    def test_returns_the_value(self):
        factory, registry, conn = self._registry()
        with self._patched(factory):
            self.assertEqual(self.sig._fetch_requirement(_req()), "DATA")

    def test_does_not_drop_a_healthy_connection(self):
        factory, registry, conn = self._registry()
        with self._patched(factory):
            self.sig._fetch_requirement(_req())
        registry.disconnect.assert_not_called()


class TestRedialsOnce(RemoteRequirementFetchTestCase):
    def test_recovers_and_returns_the_value(self):
        factory, registry, conn = self._registry(
            get_side_effect=[MDSplusERROR(), SimpleNamespace(value="DATA")]
        )
        with self._patched(factory):
            self.assertEqual(self.sig._fetch_requirement(_req()), "DATA")

    def test_drops_the_connection_before_retrying(self):
        factory, registry, conn = self._registry(
            get_side_effect=[MDSplusERROR(), SimpleNamespace(value="DATA")]
        )
        with self._patched(factory):
            self.sig._fetch_requirement(_req())
        registry.disconnect.assert_called_once_with(SERVER)

    def test_redials_rather_than_reusing_the_same_connection(self):
        factory, registry, conn = self._registry(
            get_side_effect=[MDSplusERROR(), SimpleNamespace(value="DATA")]
        )
        with self._patched(factory):
            self.sig._fetch_requirement(_req())
        self.assertEqual(registry.connect.call_count, 2)

    def test_a_failure_in_open_tree_also_redials(self):
        # openTree is as likely as get() to be the call that lost the session.
        factory, registry, conn = self._registry(
            open_tree_side_effect=[MdsIpException("dead session"), None]
        )
        with self._patched(factory):
            self.assertEqual(self.sig._fetch_requirement(_req()), "DATA")
        registry.disconnect.assert_called_once_with(SERVER)

    def test_recovers_from_mdsip_exceptions_too(self):
        # A dropped socket on the atlas path has the same shape as an expired
        # fdp:// relay session, and is a different exception class.
        factory, registry, conn = self._registry(
            get_side_effect=[MdsIpException("broken pipe"), SimpleNamespace(value="DATA")]
        )
        with self._patched(factory):
            self.assertEqual(self.sig._fetch_requirement(_req()), "DATA")


class TestGivesUpAfterTheRetry(RemoteRequirementFetchTestCase):
    def test_raises_the_underlying_error(self):
        boom = MDSplusERROR()
        factory, registry, conn = self._registry(get_side_effect=boom)
        with self._patched(factory):
            with self.assertRaises(MDSplusERROR) as caught:
                self.sig._fetch_requirement(_req())
        self.assertIs(caught.exception, boom)

    def test_tries_exactly_twice(self):
        factory, registry, conn = self._registry(get_side_effect=MDSplusERROR())
        with self._patched(factory):
            with self.assertRaises(MDSplusERROR):
                self.sig._fetch_requirement(_req())
        self.assertEqual(conn.get.call_count, 2)

    def test_drops_the_connection_after_the_last_attempt_too(self):
        # Leaving a connection that may be dead in the registry carries the
        # failure into every later fetch, which is the cascade this fixes.
        factory, registry, conn = self._registry(get_side_effect=MDSplusERROR())
        with self._patched(factory):
            with self.assertRaises(MDSplusERROR):
                self.sig._fetch_requirement(_req())
        self.assertEqual(registry.disconnect.call_count, 2)


class TestPropagatesTreeErrorsUntouched(RemoteRequirementFetchTestCase):
    """Tree-class errors say the data isn't there, not that the link is bad."""

    def test_raises_immediately(self):
        factory, registry, conn = self._registry(get_side_effect=TreeNODATA())
        with self._patched(factory):
            with self.assertRaises(TreeNODATA):
                self.sig._fetch_requirement(_req())

    def test_does_not_retry(self):
        factory, registry, conn = self._registry(get_side_effect=TreeNODATA())
        with self._patched(factory):
            with self.assertRaises(TreeNODATA):
                self.sig._fetch_requirement(_req())
        self.assertEqual(conn.get.call_count, 1)

    def test_does_not_drop_the_connection(self):
        # A node with no data is routine. Redialling on it would churn the
        # session for a benign condition and double the cost of every miss.
        factory, registry, conn = self._registry(get_side_effect=TreeNODATA())
        with self._patched(factory):
            with self.assertRaises(TreeNODATA):
                self.sig._fetch_requirement(_req())
        registry.disconnect.assert_not_called()


class TestDroppingIsBestEffort(RemoteRequirementFetchTestCase):
    def test_a_failing_disconnect_does_not_mask_the_fetch_error(self):
        # disconnect() talks to the network too. Letting it raise would replace
        # the error that says why the data is missing with a cleanup error.
        boom = MDSplusERROR()
        factory, registry, conn = self._registry(get_side_effect=boom)
        registry.disconnect.side_effect = RuntimeError("socket already gone")
        with self._patched(factory):
            with self.assertRaises(MDSplusERROR) as caught:
                self.sig._fetch_requirement(_req())
        self.assertIs(caught.exception, boom)

    def test_a_failing_disconnect_does_not_prevent_the_retry(self):
        factory, registry, conn = self._registry(
            get_side_effect=[MDSplusERROR(), SimpleNamespace(value="DATA")]
        )
        registry.disconnect.side_effect = RuntimeError("socket already gone")
        with self._patched(factory):
            self.assertEqual(self.sig._fetch_requirement(_req()), "DATA")


if __name__ == "__main__":
    unittest.main()
