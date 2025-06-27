from pathlib import Path
import argparse
import sys
import os
import subprocess
import sh

from XRootD import client
from XRootD.client.flags import DirListFlags, StatInfoFlags


##############################################################################
# 
# ENVIRONMENT
#
# Configure environment variables needed for access to
# FDP resources
##############################################################################



XRD_SERVER = "fdp-d3d-origin.nationalresearchplatform.org:8443"

FDP_ROOT = Path("/fdp-d3d")
ARCHIVES_DIR = FDP_ROOT / "archives"

# Resolve the active Python environment’s directories
python_executable_path = Path(sys.executable)
env_dir = python_executable_path.parent.parent
lib_dir = env_dir / "lib"
bin_dir = env_dir / "bin"

DEFAULT_CONFIG = {
    # XRootD / FDP
    "XROOTD_VMP": f"{XRD_SERVER}:{FDP_ROOT}",
    "TOKSEARCH_INDEX_DIR": str(ARCHIVES_DIR / "index" / "dbs" / "current"),

    # Thread-affinity vars (keep NumPy / MKL single-threaded)
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",

    # pymssql TLS requirement
    "TDSVER": "7.0",

    # PTData local-file override
    "D3DATA": "yes",

    # Cake metadata DB
    "CAKE_DB_PATH": str(FDP_ROOT / "metadata" / "iri_logs.db"),

    # Shared-library and certificate locations
    "LD_PRELOAD": str(lib_dir / "libXrdPosixPreload.so"),
    "X509_CERT_FILE": str(env_dir / "ssl" / "cacert.pem"),
    "PTDATA_LIBRARY": str(lib_dir / "libd3.so"),

    # Prepend the active env’s bin directory to PATH
    "PATH": f"{bin_dir}:{os.getenv('PATH', '')}",

    # TDI search path for MDSplus
    "MDS_PATH": str(env_dir / "tdi"),
}






class FdpFileSystem:
    def __init__(self, server: str, bearer_token: str):
        self.server = server

        os.environ["BEARER_TOKEN"] = bearer_token

        self.xrd_fs = client.FileSystem(server)

    def ls(self, path: str | Path, dirs_only: bool = False) -> list[Path]:
        
        _, listings = self.xrd_fs.dirlist(str(path), DirListFlags.STAT)


        if not listings:
            return []

        if dirs_only:
            paths = [Path(listing.name) for listing in listings if listing.statinfo.flags & StatInfoFlags.IS_DIR]
        else:
            paths = [Path(listing.name) for listing in listings]

        return paths


def get_mds_path_vars(bearer_token: str) -> dict[str, str]:

    archive_dir = ARCHIVES_DIR
    mds_archive_dir = ARCHIVES_DIR / "mdsplus"

    codes_mds_path = "codes/~t/~j~i/~h~g/~f~e/~d~c"
    usershots_path = "usershots/~t"
    models_path = "models/~t"


    fs = FdpFileSystem(XRD_SERVER, bearer_token)


    path_vars = {}

    def _set_paths(dirs: list[Path], tree_path: str):
        for d in dirs:
            tree_name = str(d.name)
            path_vars[f"{tree_name}_path"] = tree_path


    # efit and other between-shot directories
    mds_codes_dirs = fs.ls(Path(mds_archive_dir, "codes"), dirs_only=True)
    mds_codes_tree_path = f"{mds_archive_dir}/{usershots_path};{mds_archive_dir}/{codes_mds_path};{mds_archive_dir}/{models_path}"
    _set_paths(mds_codes_dirs, mds_codes_tree_path)


    # D3D tree and subtrees
    mds_shots_dirs = fs.ls(Path(mds_archive_dir, "shots"), dirs_only=True)
    shots_mds_path = "shots/~t/~f~e/~d~c"
    mds_shots_tree_path = f"{mds_archive_dir}/{usershots_path};{mds_archive_dir}/{shots_mds_path};{mds_archive_dir}/{models_path}"
    _set_paths(mds_shots_dirs, mds_shots_tree_path)

    # User shots
    mds_usershots_dirs = fs.ls(Path(mds_archive_dir, "usershots"), dirs_only=True)
    mds_usershots_tree_path = f"{mds_archive_dir}/{usershots_path}"
    _set_paths(mds_usershots_dirs, mds_usershots_tree_path)

    return path_vars 


def create_environment(bearer_token: str) -> dict[str, str]:
    
    env = os.environ.copy()

    env |= DEFAULT_CONFIG

    if not bearer_token:
        home_dir = Path.home()
        token_file = home_dir / ".fdp" / "token"
   
        with open(token_file, "r") as f:
            bearer_token = f.read().strip()

    env["BEARER_TOKEN"] = bearer_token


    mds_path_vars = get_mds_path_vars(bearer_token)
    env |= mds_path_vars

    return env

##############################################################################
# 
# CLI SUB COMMMANDS
#
##############################################################################

def do_run(args):
    passthrough_args = args.command_args
    env = create_environment(args.bearer_token)

    if args.debug:
        command_str = " ".join(passthrough_args)
        print(f"Running command: {command_str}")
        print("With environment vars:")
        for k, v in env.items():
            print(f"{k}: {v}")


    comm = passthrough_args
    result = subprocess.run(comm, env=env)
    sys.exit(result.returncode)



def do_ls(args):
    env = create_environment(args.bearer_token)

    fs = FdpFileSystem(XRD_SERVER, args.bearer_token)


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

    run_parser = subparsers.add_parser("run", help="Run a command with access to FDP data")
    run_parser.add_argument("command_args", nargs=argparse.REMAINDER, help="Command and args to pass through")
    run_parser.set_defaults(func=do_run)

    ls_parser = subparsers.add_parser("ls", help="List files on the FDP")
    ls_parser.add_argument("--dirs-only", "-d", action="store_true", help="Only show subdirectories")
    ls_parser.add_argument("path", type=str, help="The path whose contents will be listed")
    ls_parser.set_defaults(func=do_ls)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
