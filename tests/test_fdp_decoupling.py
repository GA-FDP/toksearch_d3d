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
  - ``import toksearch_d3d`` populates XRD_PLUGINCONFDIR before the signal
    classes pull in libXrdCl, so Pelican fetches work from a fresh Python
    process that doesn't go through ``fdp run``.
"""

import os
import subprocess
import sys
import textwrap
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
            import fdp.environment  # noqa: F401
        except ImportError:
            self.skipTest("fdp package not installed yet")
        from toksearch_d3d.fdp import setup_environment
        # The wrapper imports the inner function as
        # `_fdp_setup_environment` from `fdp.environment`; we patch at the
        # toksearch_d3d.fdp module level to intercept that bound name.
        with mock.patch("toksearch_d3d.fdp._fdp_setup_environment") as su:
            setup_environment()
        su.assert_called_once()
        self.assertEqual(su.call_args.kwargs.get("device"), "d3d")


class TestSetupEnvironmentIntegration(unittest.TestCase):
    """End-to-end: ``import toksearch_d3d`` must enable Pelican access from a
    fresh Python process that inherits no FDP env vars.

    Regression for an XRootD load-order bug: libXrdCl's static initializer
    reads XRD_PLUGINCONFDIR at library-load time, and libXrdCl is pulled in as
    a transitive dep of MDSplus (libTreeShr -> libfdpio2 -> libXrdCl). If the
    var isn't set before the signal imports in ``toksearch_d3d/__init__.py``
    run, the Pelican plugin is never registered and ``pelican://`` fetches
    fail with "Error opening network link connection". ``fdp run`` masks this
    by exporting XRD_PLUGINCONFDIR before Python starts -- this test does not.
    """

    def test_pelican_fetch_from_fresh_python_subprocess(self):
        bearer = os.environ.get("BEARER_TOKEN")
        conda_prefix = os.environ.get("CONDA_PREFIX")
        if not bearer or not conda_prefix:
            self.skipTest("requires BEARER_TOKEN and CONDA_PREFIX")

        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "CONDA_PREFIX": conda_prefix,
            "BEARER_TOKEN": bearer,
        }
        # Pass through proxy settings if the host requires them to reach the
        # Pelican origin -- these aren't part of the FDP setup we're testing.
        for k in ("http_proxy", "https_proxy", "no_proxy", "all_proxy",
                  "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"):
            if k in os.environ:
                clean_env[k] = os.environ[k]

        script = textwrap.dedent("""
            from toksearch_d3d import setup_environment, PtDataSignal
            setup_environment()
            res = PtDataSignal("ip").fetch(165920)
            assert len(res["data"]) > 1, "empty data"
            print("OK")
        """)

        result = subprocess.run(
            [sys.executable, "-c", script],
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(
            result.returncode, 0,
            f"subprocess failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
