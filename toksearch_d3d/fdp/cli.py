from pathlib import Path
import argparse
import shlex
import shutil
import sys
import os
import subprocess
import warnings

from XRootD import client
from XRootD.client.flags import DirListFlags, StatInfoFlags


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

    if conda_prefix is not None:
        return _plugin_conf_path(conda_prefix)
    elif prefix is not None:
        return _plugin_conf_path(prefix)
    else:

        val = os.getenv("XRD_PLUGINCONFDIR", None)
        if val is None:
            warnings.warn(
                "XRD_PLUGINCONFDIR is not set. This may cause problems with FDP access."
            )
        return val



OSDF_SERVER = "pelican://osg-htc.org:443"
ORIGIN_SERVER = "root://fdp-d3d-origin.nationalresearchplatform.org:8443"

FDP_ROOT = f"{OSDF_SERVER}/fdp-d3d"
ARCHIVES_DIR = f"{FDP_ROOT}/archives"

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
    "CAKE_DB_PATH": f"{FDP_ROOT}/metadata/iri_logs.db",
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
    "PTDATA_LOC": os.getenv("PTDATA_LOC", "1"),  # Do NOT go out to athena by default
    "PTDATA_JSON_INDEX_DIR": f"{ARCHIVES_DIR}/index/json/json_indexes_2026-01-13_12:22:11",
    "PTDATA_LIBRARY": str(lib_dir / "libd3.so"),
    "PTDATA_PLUGIN_LIB": str(lib_dir / "libjson_index_plugin.so"),
    "SYS_D3_DELIM": ";",
}


class FdpFileSystem:
    def __init__(self, server: str):
        self.server = server
        self.xrd_fs = client.FileSystem(server)

    def ls(self, path: str | Path, dirs_only: bool = False) -> list[Path]:
        _, listings = self.xrd_fs.dirlist(str(path), DirListFlags.STAT)

        if not listings:
            return []

        if dirs_only:
            listings = [l for l in listings if l.statinfo.flags & StatInfoFlags.IS_DIR]

        return [Path(l.name) for l in listings]


##############################################################################
#
# SKILLS BACKENDS
#
##############################################################################


def _parse_skill_md(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) from a SKILL.md file."""
    text = path.read_text()
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        fm_dict = {}
        for line in fm.strip().splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm_dict[k.strip()] = v.strip()
        return fm_dict, body.lstrip("\n")
    return {}, text


class ClaudeBackend:
    """Claude Code — ~/.claude/skills/<name>/SKILL.md"""

    name = "claude"

    @property
    def dest_root(self):
        return Path.home() / ".claude" / "skills"

    def is_detected(self):
        return (Path.home() / ".claude").exists()

    def install_skill(self, skill_dir: Path, force: bool) -> str:
        dest = self.dest_root / skill_dir.name
        if dest.exists() and not force:
            return "skipped"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_dir, dest)
        return "installed"

    def is_skill_installed(self, skill_name: str) -> bool:
        return (self.dest_root / skill_name).exists()


class CursorBackend:
    """Cursor IDE — ~/.cursor/rules/fdp-<name>.mdc"""

    name = "cursor"

    @property
    def dest_root(self):
        return Path.home() / ".cursor" / "rules"

    def is_detected(self):
        return (Path.home() / ".cursor").exists()

    def install_skill(self, skill_dir: Path, force: bool) -> str:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return "skipped"
        fm, body = _parse_skill_md(skill_md)
        description = fm.get("description", skill_dir.name)
        dest_file = self.dest_root / f"fdp-{skill_dir.name}.mdc"
        if dest_file.exists() and not force:
            return "skipped"
        self.dest_root.mkdir(parents=True, exist_ok=True)
        content = f"---\ndescription: {description}\nglobs: \nalwaysApply: false\n---\n\n{body}"
        dest_file.write_text(content)
        return "installed"

    def is_skill_installed(self, skill_name: str) -> bool:
        return (self.dest_root / f"fdp-{skill_name}.mdc").exists()


class CodexBackend:
    """OpenAI Codex CLI — ~/.codex/instructions.md (section-per-skill)"""

    name = "codex"

    @property
    def dest_root(self):
        return Path.home() / ".codex"

    @property
    def _instructions_file(self):
        return self.dest_root / "instructions.md"

    def is_detected(self):
        return (Path.home() / ".codex").exists()

    def _markers(self, skill_name):
        return f"<!-- fdp-skill:{skill_name} -->", f"<!-- /fdp-skill:{skill_name} -->"

    def is_skill_installed(self, skill_name: str) -> bool:
        if not self._instructions_file.exists():
            return False
        start, _ = self._markers(skill_name)
        return start in self._instructions_file.read_text()

    def install_skill(self, skill_dir: Path, force: bool) -> str:
        import re
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return "skipped"
        _, body = _parse_skill_md(skill_md)
        start, end = self._markers(skill_dir.name)
        section = f"{start}\n{body.rstrip()}\n{end}"
        current = self._instructions_file.read_text() if self._instructions_file.exists() else ""
        if start in current:
            if not force:
                return "skipped"
            pattern = re.escape(start) + r".*?" + re.escape(end)
            current = re.sub(pattern, section, current, flags=re.DOTALL)
        else:
            current = current.rstrip("\n") + ("\n\n" if current else "") + section + "\n"
        self._instructions_file.write_text(current)
        return "installed"


BACKENDS = {
    "claude": ClaudeBackend(),
    "cursor": CursorBackend(),
    "codex":  CodexBackend(),
}


##############################################################################
#
# CLI SUB COMMMANDS
#
##############################################################################


def do_skills(args):
    import toksearch
    import toksearch_d3d

    skill_sources = [
        Path(toksearch.__file__).parent / "skills",
        Path(toksearch_d3d.__file__).parent / "skills",
    ]
    skill_dirs = [
        d
        for source in skill_sources if source.exists()
        for d in sorted(source.iterdir()) if d.is_dir()
    ]

    backend_arg = getattr(args, "backend", "claude")
    if backend_arg == "all":
        backends = [b for b in BACKENDS.values() if b.is_detected()]
        if not backends:
            print("No supported coding assistant tool detected.")
            return
    elif backend_arg in BACKENDS:
        backends = [BACKENDS[backend_arg]]
    else:
        print(f"Unknown backend '{backend_arg}'. Choose from: {', '.join(BACKENDS)}, all")
        sys.exit(1)

    if args.skills_command == "list":
        for backend in backends:
            print(f"[{backend.name}]")
            for d in skill_dirs:
                status = "installed" if backend.is_skill_installed(d.name) else "not installed"
                print(f"  {d.name}  [{status}]")
        return

    force = getattr(args, "force", False)
    for backend in backends:
        print(f"\n[{backend.name}] Installing to {backend.dest_root}")
        backend.dest_root.mkdir(parents=True, exist_ok=True)
        installed = skipped = 0
        for skill_dir in skill_dirs:
            result = backend.install_skill(skill_dir, force)
            if result == "installed":
                print(f"  install  {skill_dir.name}")
                installed += 1
            else:
                print(f"  skip     {skill_dir.name}  (use --force to overwrite)")
                skipped += 1
        print(f"  {installed} installed, {skipped} skipped")


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
    fs = FdpFileSystem(ORIGIN_SERVER)

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

    skills_parser = subparsers.add_parser("skills", help="Manage AI coding assistant skills for FDP")
    skills_sub = skills_parser.add_subparsers(dest="skills_command")

    list_p = skills_sub.add_parser("list", help="List FDP skills and their installation status")
    list_p.add_argument(
        "--backend", default="claude",
        help="Target tool: claude, cursor, codex, or all (default: claude)"
    )

    install_p = skills_sub.add_parser("install", help="Install FDP skills for a coding assistant")
    install_p.add_argument(
        "--backend", default="claude",
        help="Target tool: claude, cursor, codex, or all (default: claude)"
    )
    install_p.add_argument(
        "--force", "-f", action="store_true", help="Overwrite already-installed skills"
    )

    skills_parser.set_defaults(func=do_skills)

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
