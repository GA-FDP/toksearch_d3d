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
"""toksearch_d3d.fdp - DIII-D contributor for the fdp package.

Exposes:
  - setup_environment(): back-compat wrapper that calls
    fdp.setup_environment(device="d3d", ...).
"""

# Import from submodules rather than top-level `fdp` so that simply
# importing toksearch_d3d does NOT trigger fdp/__init__.py's eager
# `from .filesystem import FdpFileSystem`, which in turn loads
# `XRootD.client` → libXrdCl. libXrdCl is already loaded via the
# `from .signal.ptdata import PtDataSignal` chain in toksearch_d3d/__init__.py;
# a second load through the fdp chain leaves non-daemon C-extension threads
# alive at Python shutdown, blocking interpreter exit (observed: 30+ min
# hang in CI conda recipe tests after tests pass).
from fdp.environment import setup_environment as _fdp_setup_environment


def setup_environment(bearer_token: str | None = None, **overrides) -> None:
    """Configure os.environ for DIII-D FDP access.

    Back-compat shim around `fdp.setup_environment(device="d3d", ...)`.
    Pre-existing callers that did `from toksearch_d3d import
    setup_environment` keep working without code changes.
    """
    _fdp_setup_environment(
        device="d3d",
        bearer_token=bearer_token,
        **overrides,
    )


__all__ = ["setup_environment"]
