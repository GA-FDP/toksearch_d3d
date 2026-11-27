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
Tests for the names that moved to toksearch_imas.

Offline: a stand-in toksearch_imas module is put in sys.modules, so these
need neither the real package nor `fdp run`.
"""

import sys
import types
import unittest
import warnings
from unittest import mock

import toksearch_d3d

MOVED = ("ImasSignal", "D3dImasSignal", "list_imas_fields")


def _fake_toksearch_imas():
    module = types.ModuleType("toksearch_imas")
    for name in MOVED:
        setattr(module, name, object())
    return module


class TestForwarding(unittest.TestCase):
    def test_moved_names_forward_with_a_deprecation_warning(self):
        fake = _fake_toksearch_imas()
        with mock.patch.dict(sys.modules, {"toksearch_imas": fake}):
            for name in MOVED:
                with self.subTest(name=name):
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        value = getattr(toksearch_d3d, name)
                    self.assertIs(value, getattr(fake, name))
                    self.assertEqual(len(caught), 1)
                    self.assertIs(caught[0].category, DeprecationWarning)
                    self.assertIn(f"from toksearch_imas import {name}", str(caught[0].message))

    def test_from_import_forwards(self):
        fake = _fake_toksearch_imas()
        with mock.patch.dict(sys.modules, {"toksearch_imas": fake}):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from toksearch_d3d import ImasSignal
        self.assertIs(ImasSignal, fake.ImasSignal)

    def test_without_toksearch_imas_the_error_names_the_package(self):
        # A None entry in sys.modules makes `import toksearch_imas` raise ImportError.
        with mock.patch.dict(sys.modules, {"toksearch_imas": None}):
            with self.assertRaises(ImportError) as ctx:
                toksearch_d3d.ImasSignal
        self.assertIn("toksearch_imas", str(ctx.exception))

    def test_other_missing_names_are_attribute_errors(self):
        self.assertFalse(hasattr(toksearch_d3d, "NoSuchSignal"))

    def test_moved_names_are_not_attributes_of_the_module(self):
        for name in MOVED:
            self.assertNotIn(name, vars(toksearch_d3d))


if __name__ == "__main__":
    unittest.main()
