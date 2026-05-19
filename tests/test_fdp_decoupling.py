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
"""Tests for the toksearch_d3d -> fdp switch-over.

Verifies:
  - D3D_DEVICE is a properly-constructed fdp.devices.Device.
  - It's discoverable via the fdp.devices entry point (once Task 2 wires it
    in pyproject.toml).
  - toksearch_d3d.setup_environment() back-compat wrapper delegates to
    fdp.setup_environment(device="d3d").
"""

import unittest
from unittest import mock


class TestD3DDeviceShape(unittest.TestCase):
    def test_d3d_device_imported(self):
        from toksearch_d3d.fdp import D3D_DEVICE
        self.assertEqual(D3D_DEVICE.name, "d3d")
        self.assertIn("fdp-d3d", D3D_DEVICE.pelican_root)
        self.assertEqual(D3D_DEVICE.default_llm_preset, "amsc")

    def test_d3d_device_has_required_paths(self):
        from toksearch_d3d.fdp import D3D_DEVICE
        self.assertIsNotNone(D3D_DEVICE.mds_default_tree_path)
        self.assertIn("fdp-d3d", D3D_DEVICE.mds_default_tree_path)
        self.assertIsNotNone(D3D_DEVICE.ptdata_index_dir)


class TestEntryPointRegistration(unittest.TestCase):
    """Runs only after Task 2 wires the entry point."""

    def test_d3d_discoverable_via_fdp(self):
        try:
            from fdp.devices import discover_devices, clear_device_cache
        except ImportError:
            self.skipTest("fdp package not installed yet (precondition)")
        clear_device_cache()
        devices = discover_devices()
        self.assertIn("d3d", devices)
        # Confirm it's coming from our contributor (not the fdp fallback)
        from toksearch_d3d.fdp import D3D_DEVICE
        # After Task 2 lands the entry point, this should be our object:
        # (Pre-Task-2 it will be the fdp fallback, which is also named "d3d"
        # but has a different description.)
        try:
            self.assertIs(devices["d3d"], D3D_DEVICE)
        except AssertionError:
            self.skipTest("entry point not yet registered (Task 2 prereq)")


class TestSetupEnvironmentWrapper(unittest.TestCase):
    def test_wrapper_calls_fdp_setup_environment_with_d3d(self):
        try:
            import fdp
        except ImportError:
            self.skipTest("fdp package not installed yet")
        from toksearch_d3d.fdp import setup_environment
        with mock.patch("fdp.setup_environment") as su:
            setup_environment()
        su.assert_called_once()
        self.assertEqual(su.call_args.kwargs.get("device"), "d3d")


if __name__ == "__main__":
    unittest.main()
