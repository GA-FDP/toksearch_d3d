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
Tests for Signal.spec() on the DIII-D signal classes.

These are pure unit tests: no shot data is fetched and no MDSplus, PTData or
Pelican access happens, so they must pass *without* `fdp run`. If one of them
starts requiring it, a constructor has begun reaching the network -- report
that rather than wrapping the test.

`spec()` feeds provenance identity, so the two properties under test are:

1. Every DIII-D signal *declares* its fields (no `spec_incomplete` marker),
   rather than falling back to reflection over `vars(self)`.
2. Signals that fetch different data produce different specs, and signals
   configured identically produce equal, canonically serializable ones.
"""

import unittest
from unittest import mock

from toksearch.provenance import canonical_json

from toksearch_d3d import PtDataSignal, RDataSignal


class TestPtDataSignalSpec(unittest.TestCase):
    def test_declares_its_fields(self):
        self.assertNotIn("spec_incomplete", PtDataSignal("ip").spec())

    def test_captures_the_pointname(self):
        self.assertEqual(PtDataSignal("ip").spec()["fields"]["pointname"], "ip")

    def test_captures_ical(self):
        self.assertEqual(PtDataSignal("ip", ical=2).spec()["fields"]["ical"], 2)

    def test_captures_remote(self):
        self.assertFalse(PtDataSignal("ip", remote=False).spec()["fields"]["remote"])

    def test_captures_keep_header(self):
        self.assertTrue(
            PtDataSignal("ip", keep_header=True).spec()["fields"]["keep_header"]
        )

    def test_captures_fetch_times(self):
        self.assertFalse(
            PtDataSignal("ip", fetch_times=False).spec()["fields"]["fetch_times"]
        )

    def test_different_pointnames_differ(self):
        self.assertNotEqual(PtDataSignal("ip").spec(), PtDataSignal("bt").spec())

    def test_different_ical_differs(self):
        self.assertNotEqual(
            PtDataSignal("ip", ical=1).spec(), PtDataSignal("ip", ical=2).spec()
        )

    def test_different_fetch_units_differs(self):
        # fetch_units is stored as the base class's `with_units`, which spec()
        # records at the top level rather than under "fields". Two signals
        # differing only in fetch_units must still not collide.
        self.assertNotEqual(
            PtDataSignal("ip", fetch_units=True).spec(),
            PtDataSignal("ip", fetch_units=False).spec(),
        )

    def test_identical_signals_have_equal_specs(self):
        self.assertEqual(PtDataSignal("ip").spec(), PtDataSignal("ip").spec())

    def test_spec_is_canonically_serializable(self):
        canonical_json(PtDataSignal("ip").spec())

    def test_rdata_reports_its_own_class(self):
        self.assertEqual(RDataSignal().spec()["class"], "RDataSignal")

    def test_rdata_inherits_declared_fields(self):
        self.assertNotIn("spec_incomplete", RDataSignal().spec())


class TestCakeSignalSpec(unittest.TestCase):
    """CakeSignal, with the cake-db download stubbed out.

    `ensure_local_cake_db` is patched exactly as tests/test_cake_cache.py does
    it, so construction touches no filesystem or network.
    """

    URL = "pelican://h:443/fdp-d3d/metadata/iri_logs.db"

    def _signal(self, expression=r"\ipmhd", treename="eq", db=None, **kwargs):
        from toksearch_d3d import CakeSignal

        with mock.patch(
            "toksearch_d3d.signal.cake.ensure_local_cake_db",
            return_value="/cache/iri_logs.db",
        ):
            return CakeSignal(
                expression, treename, cake_db_location=db or self.URL, **kwargs
            )

    def test_declares_its_fields(self):
        self.assertNotIn("spec_incomplete", self._signal().spec())

    def test_inherits_mds_fields(self):
        fields = self._signal().spec()["fields"]
        self.assertEqual(fields["expression"], r"\ipmhd")
        self.assertEqual(fields["treename"], "efit")

    def test_records_the_requested_db_not_the_resolved_cache_path(self):
        # The resolved path is a per-machine cache location, so recording it
        # would make identical pipelines look different on different hosts.
        fields = self._signal().spec()["fields"]
        self.assertEqual(fields["cake_db_location"], self.URL)
        self.assertNotIn("/cache/", canonical_json(fields))

    def test_different_trees_differ(self):
        self.assertNotEqual(
            self._signal(treename="eq").spec(),
            self._signal(treename="prof").spec(),
        )

    def test_different_dbs_differ(self):
        self.assertNotEqual(
            self._signal(db="/a/iri_logs.db").spec(),
            self._signal(db="/b/iri_logs.db").spec(),
        )

    def test_identical_signals_have_equal_specs(self):
        self.assertEqual(self._signal().spec(), self._signal().spec())

    def test_spec_is_canonically_serializable(self):
        canonical_json(self._signal().spec())


class TestImasSignalSpec(unittest.TestCase):
    LEAF = "equilibrium.time_slice.global_quantities.ip"

    @classmethod
    def setUpClass(cls):
        from imas_composer import ImasComposer

        from toksearch_d3d import ImasSignal

        cls.ImasSignal = ImasSignal
        cls.ImasComposer = ImasComposer
        cls.composer = ImasComposer()

    def test_declares_its_fields(self):
        sig = self.ImasSignal(self.LEAF, composer=self.composer)
        self.assertNotIn("spec_incomplete", sig.spec())

    def test_captures_the_ids_path(self):
        sig = self.ImasSignal(self.LEAF, composer=self.composer)
        self.assertEqual(sig.spec()["fields"]["ids_path"], self.LEAF)

    def test_captures_the_resolved_layout(self):
        # A leaf path defaults to 'compact'; the spec must record the layout
        # actually in force, not the (unset) request.
        sig = self.ImasSignal(self.LEAF, composer=self.composer)
        self.assertEqual(sig.spec()["fields"]["layout"], "compact")

    def test_different_layouts_differ(self):
        self.assertNotEqual(
            self.ImasSignal(self.LEAF, composer=self.composer).spec(),
            self.ImasSignal(
                self.LEAF, composer=self.composer, layout="ragged"
            ).spec(),
        )

    def test_captures_the_composer_configuration(self):
        # The composer decides which EFIT/profiles trees back the IDS, so two
        # signals on the same ids_path can return entirely different data.
        sig = self.ImasSignal(
            self.LEAF, composer=self.ImasComposer(efit_tree="EFIT02")
        )
        self.assertEqual(sig.spec()["fields"]["composer"]["efit_tree"], "EFIT02")

    def test_different_efit_trees_differ(self):
        self.assertNotEqual(
            self.ImasSignal(
                self.LEAF, composer=self.ImasComposer(efit_tree="EFIT01")
            ).spec(),
            self.ImasSignal(
                self.LEAF, composer=self.ImasComposer(efit_tree="EFIT02")
            ).spec(),
        )

    def test_captures_the_location(self):
        sig = self.ImasSignal(
            self.LEAF, composer=self.composer, location="remote://atlas.gat.com"
        )
        self.assertEqual(
            sig.spec()["fields"]["location"], "remote://atlas.gat.com"
        )

    def test_identical_signals_have_equal_specs(self):
        self.assertEqual(
            self.ImasSignal(self.LEAF, composer=self.composer).spec(),
            self.ImasSignal(self.LEAF, composer=self.composer).spec(),
        )

    def test_spec_is_canonically_serializable(self):
        sig = self.ImasSignal(self.LEAF, composer=self.composer)
        canonical_json(sig.spec())


if __name__ == "__main__":
    unittest.main()
