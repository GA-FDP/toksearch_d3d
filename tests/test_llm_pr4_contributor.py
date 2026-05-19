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
"""End-to-end test that toksearch_d3d shows up as a toksearch.llm contributor.

Requires the editable install picked up the pyproject.toml entry-point
declarations (Task 2).  Runs only when the toksearch.llm machinery is
importable (i.e. core toksearch is at PR 30 or later); otherwise skips.
"""

import unittest


try:
    from toksearch.llm.discovery import (
        discover_namespace_contributors,
        discover_skill_dirs,
        discover_presets,
        clear_discovery_cache,
    )
    from toksearch.llm.presets import resolve_preset
    from toksearch.llm.config import Config
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False


@unittest.skipUnless(_LLM_AVAILABLE,
                     "toksearch.llm not available (requires toksearch>=2.7)")
class TestToksearchD3dContributor(unittest.TestCase):
    def setUp(self):
        clear_discovery_cache()

    def tearDown(self):
        clear_discovery_cache()

    def test_namespace_entry_registered(self):
        names = [n for n, _v, _d in discover_namespace_contributors()]
        self.assertIn("toksearch_d3d", names)

    def test_namespace_description_populated(self):
        for name, _value, desc in discover_namespace_contributors():
            if name == "toksearch_d3d":
                self.assertIn("DIII-D", desc)
                return
        self.fail("toksearch_d3d not in namespace contributors")

    def test_skills_dir_registered(self):
        names = [n for n, _p in discover_skill_dirs()]
        self.assertIn("toksearch_d3d", names)

    def test_amsc_preset_registered(self):
        self.assertIn("amsc", discover_presets())

    def test_amsc_preset_resolves(self):
        preset = resolve_preset("amsc", Config())
        self.assertEqual(preset.backend, "anthropic")
        self.assertEqual(
            preset.base_url,
            "https://api.i2-core.american-science-cloud.org")
        self.assertEqual(preset.api_key_file, "~/amsc_api_key")


if __name__ == "__main__":
    unittest.main()
