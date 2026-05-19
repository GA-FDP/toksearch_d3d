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

"""toksearch_d3d.llm -- contributor module for toksearch.llm.

Exposes:
- ``skills_path``: directory of DIII-D-specific SKILL.md files, registered
  via the ``toksearch.llm.skills`` entry point.
- ``AMSC_PRESET``: a backend preset that points the Anthropic backend at
  GA's American Science Cloud endpoint with ``~/amsc_api_key`` as the key
  source, registered via the ``toksearch.llm.presets`` entry point.

The ``toksearch.llm.namespace`` entry point points at ``toksearch_d3d``
itself (whose ``__init__.py`` defines ``__llm_description__``).
"""

from pathlib import Path

from toksearch.llm.presets import Preset


skills_path: Path = Path(__file__).parent.parent / "skills"


AMSC_PRESET: Preset = Preset(
    backend="anthropic",
    model="claude-sonnet-4-6",
    base_url="https://api.i2-core.american-science-cloud.org",
    api_key_file="~/amsc_api_key",
)


__all__ = ["skills_path", "AMSC_PRESET"]
