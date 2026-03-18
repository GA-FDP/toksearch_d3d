---
name: toksearch-d3d-fdp
description: fdp CLI for FDP/Pelican data access — fdp run, fdp env, fdp ls, authentication, and available DIII-D data
user-invocable: false
license: Apache-2.0
compatibility: Claude Code
metadata:
  author: GA-FDP
  version: "1.0"
  url: https://ga-fdp.github.io/toksearch/
---

# FDP CLI Skill

## Description

The `fdp` command-line tool configures all environment variables required for accessing DIII-D fusion data via the Pelican/OSDF object store (XRootD transport, MDSplus tree paths, PTData settings, authentication). It is the standard entry point for running FDP-enabled scripts and for inspecting available data.

The `fdp` CLI is provided by the `toksearch_d3d` package (entry point: `toksearch_d3d.fdp.cli:main`).

## When to Use

- Running Python scripts that use `MdsSignal`, `PtDataSignal`, or `ImasSignal`
- Setting up a shell session for interactive FDP data access
- Listing available files/directories on the FDP data store

## Authentication

`fdp` looks for a bearer token in this priority order:

1. `--bearer-token TOKEN` / `-t TOKEN` command-line argument
2. `BEARER_TOKEN` environment variable
3. `~/.fdp/token` file (plain text, one token)

```bash
# Store token in file (recommended)
mkdir -p ~/.fdp
echo "your_token_here" > ~/.fdp/token
```

If no token is found, `fdp` prints a warning and continues (some operations may fail).

## `fdp run` — Execute a Command with FDP Environment

Runs any command with all FDP environment variables pre-configured:

```bash
fdp run python my_analysis.py
fdp run python -c "from toksearch_d3d import PtDataSignal; print(PtDataSignal('ip').fetch(202161))"
fdp run jupyter notebook
fdp run bash   # interactive shell with FDP env
```

The `fdp run` command sets:

| Variable | Purpose |
|----------|---------|
| `BEARER_TOKEN` | Pelican authentication |
| `XRD_PLUGINCONFDIR` | Path to XRootD client plugin configs |
| `XRDCP_ALLOW_HTTP` | Enable HTTP transport |
| `XRD_PELICANUSEAUTHHEADERS` | Send auth headers to Pelican |
| `default_tree_path` | MDSplus tree paths (semicolon-delimited Pelican URLs) |
| `MDS_PATH` | TDI search path for MDSplus |
| `PTDATA_LOC` | `1` = use Pelican (not local athena) |
| `PTDATA_JSON_INDEX_DIR` | Pelican URL to PTData JSON index |
| `PTDATA_LIBRARY` | Path to PTData shared library |
| `PTDATA_PLUGIN_LIB` | Path to JSON index plugin |

**Script workflow**: Write your analysis script using normal TokSearch/toksearch_d3d APIs with `location=None` (default), then run it via `fdp run`:

```python
# my_analysis.py — no special location args needed
from toksearch import Pipeline, MdsSignal
from toksearch_d3d import PtDataSignal

shots = [202159, 202160, 202161]
pipeline = Pipeline(shots)
pipeline.fetch('ip',   MdsSignal(r'\ipmhd', 'efit01'))   # location=None
pipeline.fetch('dens', PtDataSignal('dssdenest'))         # remote=True
records = pipeline.compute_serial()
```

```bash
fdp run python my_analysis.py
```

### Debug mode

Print the full environment configuration before running:

```bash
fdp --debug run python my_analysis.py
```

## `fdp env` — Print Environment Variables for Shell Eval

Outputs `export VAR=value` lines for all FDP environment variables. Use when you want to configure the current shell session directly:

```bash
# Configure the current shell
eval $(fdp env)
# or
source <(fdp env)

# Now run Python directly (env is already set)
python my_analysis.py
```

Useful for Jupyter kernels, interactive shells, or environments where subprocess wrapping is not practical.

## `fdp ls` — List Files on the FDP Data Store

Lists files and directories on the FDP origin server via XRootD:

```bash
# List top-level directories
fdp ls /

# List shot archive directories
fdp ls /archives/mdsplus/shots

# Show only subdirectories (no files)
fdp ls --dirs-only /archives/mdsplus/shots
fdp ls -d /archives/mdsplus/shots
```

The listing queries the XRootD origin server directly:
- Origin: `root://fdp-d3d-origin.nationalresearchplatform.org:8443`
- FDP root: `pelican://osg-htc.org:443/fdp-d3d/`

## Available Data via FDP

| Data type | Access method | Notes |
|-----------|--------------|-------|
| MDSplus `efit01` tree | `MdsSignal(r'\signal', 'efit01')` | Equilibrium, profiles |
| PTDATA diagnostics | `PtDataSignal('pointname')` | Time-series diagnostics |
| IMAS-composed data | `ImasSignal('ids.path')` | Via `imas_composer` (experimental) |

**Note**: Only the `efit01` MDSplus tree is confirmed available via FDP Pelican. Other trees (magnetics, pcs, ece, etc.) are not currently accessible through this path.

## Complete Workflow Example

```bash
# 1. Store your token
echo "Bearer eyJ..." > ~/.fdp/token

# 2. Explore available data
fdp ls /archives/mdsplus/shots

# 3. Write your analysis script (see above)

# 4. Run it
fdp run python my_analysis.py

# 5. Or set up a Jupyter session
eval $(fdp env)
jupyter notebook
```

## Best Practices

- Store the bearer token in `~/.fdp/token` rather than passing it on the command line (avoids token exposure in shell history)
- Use `fdp run` rather than `fdp env` + source when running scripts, to keep the environment isolated to the subprocess
- Always leave `location=None` in `MdsSignal` and `ImasSignal` constructors when using `fdp run` — the tree paths are already configured
- Use `fdp --debug run python script.py` when debugging environment issues — it prints all configured variables
