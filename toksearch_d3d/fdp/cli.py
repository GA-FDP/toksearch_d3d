from pathlib import Path
import argparse
import shlex
import sys
import os
import subprocess
import warnings

from pelicanfs.core import PelicanFileSystem as PelicanFS


##############################################################################
#
# ENVIRONMENT
#
# Configure environment variables needed for access to
# FDP resources
##############################################################################


def get_default_xrd_pluginconfdir():

    conda_prefix = os.getenv("CONDA_PREFIX", None)
    prefix = os.getenv("PREFIX", None)

    def _plugin_conf_path(base_dir):
        return os.path.join(base_dir, "etc", "xrootd", "client.plugins.d")

    if prefix is not None:
        return _plugin_conf_path(prefix)
    elif conda_prefix is not None:
        return _plugin_conf_path(conda_prefix)
    else:

        val = os.getenv("XRD_PLUGINCONFDIR", None)
        if val is None:
            warnings.warn(
                "XRD_PLUGINCONFDIR is not set. This may cause problems with FDP access."
            )
        return val



OSDF_SERVER = "pelican://osg-htc.org:443"

FDP_ROOT = Path(OSDF_SERVER) / "fdp-d3d"
ARCHIVES_DIR = FDP_ROOT / "archives"

# Resolve the active Python environment’s directories
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
    "CAKE_DB_PATH": str(FDP_ROOT / "metadata" / "iri_logs.db"),
    # Shared-library and certificate locations
    "X509_CERT_FILE": str(env_dir / "ssl" / "cacert.pem"),
    # Prepend the active env’s bin directory to PATH
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
    "PTDATA_LOC": "${PTDATA_LOC:-1}",  # Do NOT go out to athena by default
    "PTDATA_JSON_INDEX_DIR": str(Path(OSDF_SERVER)
    / "fdp-d3d/archives/index/json/json_indexes_2026-01-13_12:22:11"),
    "PTDATA_LIBRARY": str(lib_dir / "libd3.so"),
    "PTDATA_PLUGIN_LIB": "libjson_index_plugin.so",
    "SYS_D3_DELIM": ";",
}


class FdpFileSystem:
    def __init__(self, server: str):
        self.server = server
        self.fs = PelicanFS(server)

    def ls(self, path: str | Path, dirs_only: bool = False) -> list[Path]:
        entries = self.fs.ls(str(path), detail=True)

        if not entries:
            return []

        if dirs_only:
            entries = [e for e in entries if e["type"] == "directory"]

        return [Path(e["name"]).name for e in entries]


##############################################################################
#
# CLI SUB COMMMANDS
#
##############################################################################


def do_run(args):
    passthrough_args = args.command_args

    if args.debug:
        command_str = " ".join(passthrough_args)
        print(f"Running command: {command_str}")
        print("With environment vars:")
        for k, v in env.items():
            print(f"{k}: {v}")

    comm = passthrough_args
    result = subprocess.run(comm, env=os.environ)
    sys.exit(result.returncode)


def do_env(args):
    for key, value in DEFAULT_CONFIG.items():
        print(f"export {key}={shlex.quote(value)}")
    bearer_token = os.environ.get("BEARER_TOKEN", "")
    if bearer_token:
        print(f"export BEARER_TOKEN={shlex.quote(bearer_token)}")


def do_ls(args):
    fs = FdpFileSystem(OSDF_SERVER)

    if args.path == "/":
        listing = [Path(FDP_ROOT).name]
    else:
        listing = fs.ls(args.path)

    if listing:
        for l in listing:
            print(l)
    else:
        print("No such file or directory")
        sys.exit(1)


##############################################################################
#
# MAIN
#
##############################################################################
def main():
    parser = argparse.ArgumentParser(
        description="CLI interface for the Fusion Data Platform"
    )
    # Define any wrapper-specific options here if needed
    parser.add_argument("--bearer-token", "-t", type=str, default="")
    parser.add_argument("--debug", action="store_true", help="Print debug info")

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run", help="Run a command with access to FDP data"
    )
    run_parser.add_argument(
        "command_args",
        nargs=argparse.REMAINDER,
        help="Command and args to pass through",
    )
    run_parser.set_defaults(func=do_run)

    env_parser = subparsers.add_parser(
        "env", help="Print environment variables for shell eval"
    )
    env_parser.set_defaults(func=do_env)

    ls_parser = subparsers.add_parser("ls", help="List files on the FDP")
    ls_parser.add_argument(
        "--dirs-only", "-d", action="store_true", help="Only show subdirectories"
    )
    ls_parser.add_argument(
        "path", type=str, help="The path whose contents will be listed"
    )
    ls_parser.set_defaults(func=do_ls)

    args = parser.parse_args()

    ################# Environment setup ####################
    os.environ |= DEFAULT_CONFIG

    bearer_token = args.bearer_token or os.getenv("BEARER_TOKEN", "")
    if not bearer_token:
        home_dir = Path.home()
        token_file = home_dir / ".fdp" / "token"
        try:
            with open(token_file, "r") as f:
                bearer_token = f.read().strip()
        except:
            warnings.warn("No BEARER_TOKEN specified. This will cause problems with FDP access.")

    os.environ["BEARER_TOKEN"] = bearer_token
    #######################################################

    # Now run it
    args.func(args)


if __name__ == "__main__":
    main()
