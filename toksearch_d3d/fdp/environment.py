# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""FDP environment configuration.

Owns the defaults applied by ``fdp run`` and exposes ``setup_environment`` so
Python scripts can configure FDP access without going through the CLI.
"""

from pathlib import Path
import os
import sys
import warnings


##############################################################################
# Pelican / OSDF endpoints
##############################################################################

OSDF_SERVER = "pelican://osg-htc.org:443"
ORIGIN_SERVER = "root://fdp-d3d-origin.nationalresearchplatform.org:8443"
FDP_ROOT = f"{OSDF_SERVER}/fdp-d3d"
ARCHIVES_DIR = f"{FDP_ROOT}/archives"


##############################################################################
# Default config
##############################################################################

def get_default_xrd_pluginconfdir():
    conda_prefix = os.getenv("CONDA_PREFIX", None)
    prefix = os.getenv("PREFIX", None)

    def _plugin_conf_path(base_dir):
        return os.path.join(base_dir, "etc", "xrootd", "client.plugins.d")

    if conda_prefix is not None:
        return _plugin_conf_path(conda_prefix)
    elif prefix is not None:
        return _plugin_conf_path(prefix)
    else:
        val = os.getenv("XRD_PLUGINCONFDIR", None)
        if val is None:
            warnings.warn(
                "XRD_PLUGINCONFDIR is not set. "
                "This may cause problems with FDP access."
            )
        return val


# Resolve the active Python environment's directories
python_executable_path = Path(sys.executable)
env_dir = python_executable_path.parent.parent
lib_dir = env_dir / "lib"
bin_dir = env_dir / "bin"

DEFAULT_CONFIG = {
    # XRootD / FDP
    "XRDCP_ALLOW_HTTP": "true",
    "XRD_PELICANUSEAUTHHEADERS": "true",
    "XRD_CURLDISABLEPREFETCH": "1",
    "XRD_PLUGINCONFDIR": get_default_xrd_pluginconfdir(),
    # Thread-affinity vars (keep NumPy / MKL single-threaded)
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    # pymssql TLS requirement
    "TDSVER": "7.0",
    # Cake metadata DB
    "CAKE_DB_PATH": f"{FDP_ROOT}/metadata/iri_logs.db",
    # Shared-library and certificate locations
    "X509_CERT_FILE": str(env_dir / "ssl" / "cacert.pem"),
    # Prepend the active env's bin directory to PATH
    "PATH": f"{bin_dir}:{os.getenv('PATH', '')}",
    # TDI search path for MDSplus
    "MDS_PATH": str(env_dir / "tdi"),
    "default_tree_path": ";".join(
        [
            "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c",
            "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t",
            "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t",
            "pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c",
        ]
    ),
    # PTData Config
    "D3DATA": "yes",
    "PTDATA_LOC": os.getenv("PTDATA_LOC", "1"),  # Do NOT go out to athena by default
    "PTDATA_JSON_INDEX_DIR": f"{ARCHIVES_DIR}/index/json/json_indexes_2026-01-13_12:22:11",
    "PTDATA_LIBRARY": str(lib_dir / "libd3.so"),
    "PTDATA_PLUGIN_LIB": str(lib_dir / "libjson_index_plugin.so"),
    "SYS_D3_DELIM": ";",
}


def apply_environment(config, env):
    """Apply config to env, preserving existing values except PATH.

    PATH is overwritten unconditionally because DEFAULT_CONFIG["PATH"]
    is built by prepending the env's bin_dir to the existing PATH at
    import time, so we must always write it through.
    """
    env["PATH"] = config["PATH"]
    for k, v in config.items():
        if k == "PATH":
            continue
        env.setdefault(k, v)
