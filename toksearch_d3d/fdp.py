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

(NOTE: this file is `_fdp_new.py` during the transition; it gets renamed
to `fdp.py` in Task 4 once the old `toksearch_d3d/fdp/` subpackage is
removed. Python's import system prefers a subpackage directory over a
sibling module of the same name, so this rename can't happen until the
subpackage is gone.)

Exposes:
  - D3D_DEVICE: the fdp.devices.Device instance describing DIII-D's
    Pelican namespace, MDSplus paths, PTData index, and `amsc` LLM
    preset. Registered via the `fdp.devices` entry point in
    pyproject.toml.
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
from fdp.devices import Device
from fdp.environment import setup_environment as _fdp_setup_environment


D3D_DEVICE: Device = Device(
    name="d3d",
    pelican_root="pelican://osg-htc.org:443/fdp-d3d",
    origin_server="root://fdp-d3d-origin.nationalresearchplatform.org:8443",
    ptdata_index_dir=(
        "pelican://osg-htc.org:443/fdp-d3d/archives/index/json/"
        "json_indexes_2026-01-13_12:22:11"
    ),
    mds_default_tree_path=";".join([
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c",
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t",
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t",
        "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c",
    ]),
    description="DIII-D fusion experiment, via Pelican",
    default_llm_preset="amsc",
    extra_env={
        "D3DATA": "yes",
        "SYS_D3_DELIM": ";",
        "CAKE_DB_PATH": "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db",
    },
)


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


__all__ = ["D3D_DEVICE", "setup_environment"]
