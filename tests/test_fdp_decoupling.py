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
  - The d3d tokamak is discoverable via the fdp_schema.catalogs entry point.
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


class TestCatalogContribution(unittest.TestCase):
    """Verify the fdp_schema.catalogs entry point is registered and works."""

    def test_d3d_in_catalog(self):
        from fdp.catalog import catalog
        self.assertIn("d3d", catalog)

    def test_d3d_catalog_has_origin_server(self):
        from fdp.catalog import catalog
        handle = catalog["d3d"]
        self.assertIn("fdp-d3d", handle.schema.origin_server)

    def test_d3d_catalog_has_mds_locator(self):
        from fdp.catalog import catalog
        handle = catalog["d3d"]
        mds = [l for l in handle.schema.locators if l.kind == "mds_tree"]
        self.assertTrue(len(mds) > 0)
        self.assertTrue(any("fdp-d3d" in p for m in mds for p in m.search_path))

    def test_d3d_catalog_has_ptdata_locator(self):
        from fdp.catalog import catalog
        handle = catalog["d3d"]
        ptd = [l for l in handle.schema.locators if l.kind == "ptdata_indexed"]
        self.assertTrue(len(ptd) > 0)
        self.assertIn("fdp-d3d", ptd[0].index_dir)


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
            # Generous timeout: CI Pelican fetch can be slower than
            # local. Locally this completes in ~90s.
            timeout=300,
        )
        self.assertEqual(
            result.returncode, 0,
            f"subprocess failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
