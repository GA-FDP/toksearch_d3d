# Decouple `fdp` from `toksearch_d3d` and `toksearch`

**Status:** Draft for review
**Date:** 2026-05-19
**Owner:** sammuli

## Motivation

`fdp` is the Fusion Data Platform CLI — `fdp run`, `fdp env`, `fdp ls`, `fdp
skills`, `fdp chat`, `fdp query`. Conceptually it is a tokamak-pluggable,
data-platform-level tool: Pelican/XRootD environment setup, OSDF browsing,
skill installation into AI assistants, and a conversational LLM frontend.

Today it lives inside `toksearch_d3d/fdp/`. That has three coupling problems:

1. **Repo location.** `fdp` is a subpackage of a DIII-D-specific package. A
   user who wants only Pelican/XRootD env setup (for, say, MAST data via
   `ZarrSignal`, or a custom non-toksearch script) must install
   `toksearch_d3d` and pull in the entire DIII-D signal stack.
2. **Code coupling.** `fdp/skills.py` and `fdp/cli.py` have hardcoded
   `import toksearch` / `import toksearch_d3d` calls — for skill-directory
   discovery — even though skill discovery should be device-agnostic.
3. **Config coupling.** `fdp/environment.py` hardcodes D3D values
   (`fdp-d3d/`, `fdp-d3d-origin.nationalresearchplatform.org:8443`,
   `PTDATA_JSON_INDEX_DIR` pointing at the D3D index). A second tokamak
   (MAST, KSTAR) cannot plug in without editing `fdp` itself.

This spec covers carving `fdp` into its own package on its own repo, breaking
the toksearch coupling at the code level, and turning device-specific config
into a contributor mechanism.

## Goals

- New top-level repo `GA-FDP/fdp` shipping the `fdp` Python package +
  console script + conda recipe. Lives on the `ga-fdp` channel alongside
  `toksearch`, `toksearch_d3d`, `ptdata`, etc.
- `fdp` depends on **nothing toksearch-related**. Only `python`, the XRootD
  client / Pelican plumbing already used today, and stdlib.
- Tokamak-specific config (`d3d`, future `mast`, `kstar`, ...) is contributed
  by device packages via Python entry points (`fdp.devices` group).
- `toksearch_d3d` becomes a contributor: drops its `fdp/` subpackage, adds
  `fdp` as a run-dep, registers `d3d` as an `fdp.devices` entry point.
- The user-facing CLI is preserved (`fdp run`, `fdp env`, etc.) with no
  behavioral regressions for the default single-device case.
- Multi-device usage is supported when warranted: `Device.activate()` context
  manager swaps runtime-adjustable env vars; the LLM agent (in the
  forward-looking native `fdp chat` evolution) picks per-fetch by
  conversation context.

## Non-goals

- A native `fdp chat` Session that actually executes tools in-process (the
  "multi-tool orchestrator" vision the user described). PR-1 of `fdp` keeps
  the `os.execvpe`-shim into `toksearch chat` exactly as it works today.
  That evolution is a follow-up that builds on this work.
- A second device contributor. The mechanism is provisional for D3D-only
  reality; future tokamak packages will register themselves via the entry
  point.
- True peer-multi-device with no env-var-driven defaults (would require
  pushing config into libfdpio / mdsplus-xrdcl as call-time arguments —
  out of scope).
- Reworking how `toksearch.llm.skills` discovery works. `fdp` reads that
  entry-point group as-is for the `fdp skills` subcommand.

## High-level design

### Dependency graph (target state)

```
┌──────────────────────┐
│       fdp            │  GA-FDP/fdp; ships `fdp` console script
│  (env/run/ls/skills, │  conda package on ga-fdp channel
│   chat/query shims,  │  depends only on: python, xrootd-pelican, stdlib
│   devices plugin)    │
└──┬───────────────────┘
   │ contributors (entry points):
   │   - fdp.devices             ← toksearch_d3d registers D3D_DEVICE here
   │   - toksearch.llm.skills    ← read for `fdp skills install`
   │
┌──┴───────────────────┐
│   toksearch_d3d      │  Adds `fdp` as run-dep; loses its `fdp/` subpackage
│  (D3D signals + the  │  Registers `d3d` as an `fdp.devices` contributor
│   D3D fdp config)    │  via `toksearch_d3d.fdp:D3D_DEVICE`
└──┬───────────────────┘
   │ depends on:
   │   - fdp        (runtime, for Device + setup_environment)
   │   - toksearch  (for Pipeline, signal base classes, llm)
   │
┌──┴───────────────────┐
│      toksearch       │  Unchanged. Knows nothing about fdp.
└──────────────────────┘
```

Arrows point downward only. `fdp` does not import `toksearch` or
`toksearch_d3d`. `toksearch` does not import `fdp`. `toksearch_d3d` imports
both. The user's vision of an `fdp chat` Session that orchestrates toksearch
+ other tools is enabled by `fdp` depending on `toksearch.llm` (the library)
in a later PR; not part of this work.

### New repo layout

```
GA-FDP/fdp/                            ← new top-level repo
├── fdp/
│   ├── __init__.py                    public surface: setup_environment, FdpFileSystem,
│                                       list_devices, get_device, current_device, Device
│   ├── cli.py                         argparse entrypoint; subcommands env/run/ls/skills/
│                                       chat/query/devices; --default-device global flag
│   ├── environment.py                 apply_environment, setup_environment(device=None);
│                                       reads from active Device
│   ├── devices.py                     Device dataclass; discover_devices() via importlib.metadata;
│                                       resolve_default_device() with the precedence order below
│   ├── filesystem.py                  FdpFileSystem (XRootD wrapper used by `fdp ls`)
│   ├── skills.py                      `fdp skills install/list`; reads `toksearch.llm.skills`
│                                       entry-point group without importing toksearch
│   └── llm_shims.py                   do_chat / do_query: os.execvpe into `toksearch chat`
│                                       / `toksearch query` with the active device's
│                                       default_llm_preset as --backend
├── tests/
│   ├── test_devices.py                entry-point discovery + Device.activate()
│   ├── test_environment.py            ported from toksearch_d3d/tests/test_fdp_environment.py
│   ├── test_cli.py                    ported from toksearch_d3d/tests/test_fdp_query.py and
│                                       test_fdp_environment.py for the CLI parts
│   └── testit.py                      unittest discovery, same shape as toksearch's
├── recipe/
│   ├── recipe.yaml                    fdp conda package; depends on python, xrdcl-pelican,
│                                       and minimum versioneer for the build
│   └── run_build.sh                   PKG_VERSION + rattler-build pattern (same as siblings)
├── pyproject.toml                     name="fdp", versioneer-driven, [project.scripts] fdp=...
├── pixi.toml                          dev env
├── docs/                              mkdocs site (env.md / run.md / ls.md / skills.md /
│                                       devices.md / chat.md)
└── .github/workflows/conda_build.yaml CI: build on push-to-main and on release-* tag
```

`pyproject.toml` console script: `fdp = "fdp.cli:main"`. Replaces the existing
entry shipping from `toksearch_d3d`.

### `Device` dataclass

```python
@dataclass(frozen=True)
class Device:
    name: str
    pelican_root: str
    origin_server: str
    ptdata_index_dir: str | None = None         # D3D-only by nature
    mds_default_tree_path: str | None = None
    description: str = ""
    default_llm_preset: str | None = None       # e.g. "amsc" for d3d
    extra_env: dict[str, str] = field(default_factory=dict)

    def apply(self) -> None:
        """Set this device's env vars in the current process. No restore.
        Used by `fdp.setup_environment(device=...)` and `fdp run`.
        """

    def activate(self) -> ContextManager[None]:
        """Context manager: set runtime-adjustable env vars on enter,
        restore prior values on exit. Concretely:

        Swapped on activate / restored on exit:
          - default_tree_path (MDSplus reads at Tree.open time)
          - any keys in self.extra_env that are tagged "runtime"

        NOT swapped (these are load-time-locked or shared in practice):
          - XRD_PLUGINCONFDIR  (libXrdCl reads at library load time)
          - PTDATA_JSON_INDEX_DIR  (libfdpio reads at first PTData call;
            also D3D-only, so no other device contributes one)
          - BEARER_TOKEN  (single OAuth identity across the FDP stack)
          - XRDCP_ALLOW_HTTP, XRD_PELICANUSEAUTHHEADERS  (process-wide)
        """
```

`apply()` is the "set-and-leave" form for process-startup configuration
(e.g. `fdp run`). `activate()` is the context manager for the multi-device
case where the agent (or user code) wraps fetches.

### Entry-point discovery

```toml
# In toksearch_d3d/pyproject.toml (PR 3):
[project.entry-points."fdp.devices"]
d3d = "toksearch_d3d.fdp:D3D_DEVICE"
```

`toksearch_d3d/fdp.py` defines:

```python
from fdp.devices import Device

D3D_DEVICE = Device(
    name="d3d",
    pelican_root="fdp-d3d/",
    origin_server="root://fdp-d3d-origin.nationalresearchplatform.org:8443",
    ptdata_index_dir="pelican://osg-htc.org:443/fdp-d3d/ptdata/json_index",
    mds_default_tree_path="...",   # carry over from current environment.py
    description="DIII-D fusion experiment, via Pelican",
    default_llm_preset="amsc",
)
```

`fdp.devices.discover_devices()` reads the `fdp.devices` entry-point group at
`Session`/CLI startup (`importlib.metadata.entry_points(group="fdp.devices")`)
and returns a `dict[str, Device]`. Cached per-process; tests monkeypatch.

### Default-device resolution

Resolution precedence (highest first):

1. CLI flag: `fdp --default-device d3d run ...`
2. Env var: `FDP_DEFAULT_DEVICE=d3d`
3. Config file: `~/.fdp/config.toml`:

   ```toml
   default_device = "d3d"
   ```

4. Auto-detect: if exactly one device discovered, use it.
5. Error: `error: no default device selected and multiple devices installed
   (d3d, mast). Pass --default-device or set FDP_DEFAULT_DEVICE.`

`--default-device` (rather than `--device`) makes the intent honest: for
single-shot CLI invocations (`fdp env`, `fdp run`, `fdp ls`) the default IS
the operative device. For `fdp chat`/`query` (today: execvpe-shims into
`toksearch chat`; tomorrow: native fdp Sessions), it's the starting device;
the agent picks per-fetch from conversation context.

### CLI subcommand surface

```
fdp [--default-device NAME] [--debug] <subcommand>
```

| Subcommand | Behavior |
|---|---|
| `fdp env` | Print `export KEY=value` for the resolved default device. |
| `fdp run <cmd>` | Apply default device's env, then `subprocess.run(cmd, env=os.environ)`. |
| `fdp ls <path>` | `FdpFileSystem(origin_server).dirlist(path)` on the resolved default device. |
| `fdp skills list` | List discovered SKILL.md files from the `toksearch.llm.skills` entry-point group. |
| `fdp skills install [--backend NAME]` | Copy SKILL.md files into the named AI assistant's config dir (claude / cursor / codex / all). Same backends as today. |
| `fdp chat` | `os.execvpe([sys.executable, "-m", "toksearch.llm.cli", "chat", "--backend", <device.default_llm_preset>, ...], env=os.environ)`. If toksearch CLI is missing, print actionable error and exit non-zero. |
| `fdp query "..."` | Same shim pattern. |
| `fdp devices` | List discovered devices with name + description; mark which is the current default. |

### Skills entry-point group

The `toksearch.llm.skills` entry-point group is the canonical place for
SKILL.md directory contributions. `fdp` reads it for `fdp skills install`
without importing `toksearch`: `importlib.metadata.entry_points(group=...)`
returns descriptors whose `.load()` resolves the contributor's `Path` (or
callable returning one) without requiring `fdp` to declare `toksearch` as a
dependency. The group name is in `toksearch`'s namespace by history; that's
acceptable cross-package convention.

### `toksearch_d3d` changes (hard cut)

**Removed:**

- `toksearch_d3d/fdp/` (subpackage, four files: cli, environment, skills, __init__)
- `[project.scripts] fdp = "toksearch_d3d.fdp.cli:main"`

**Added:**

- `toksearch_d3d/fdp.py` (single module, replaces the subpackage):

  ```python
  from fdp.devices import Device

  D3D_DEVICE = Device(...)            # see above

  def setup_environment(*, bearer_token=None):
      """Back-compat wrapper: configures the process for D3D access."""
      import fdp
      return fdp.setup_environment(device="d3d", bearer_token=bearer_token)
  ```

- `pyproject.toml` `[project.entry-points."fdp.devices"]` for D3D
- `recipe/recipe.yaml` `requirements.run`: add `fdp >=<release>` (pin set
  when fdp's first release lands)
- `toksearch_d3d/__init__.py` package-level env setup (currently
  `apply(_defaults, _os.environ)`) becomes
  `fdp.setup_environment(device="d3d")` — same behavior, different source.

**Unchanged:**

- `toksearch_d3d/llm/` — its `toksearch.llm.namespace`, `.skills`, `.presets`
  entry-point contributions, including the `amsc` preset.
- `toksearch_d3d/signal/` — PtData / Imas / Cake.
- `toksearch_d3d/tools/pcssetup_to_wa10.py` and its console script.
- All `toksearch_d3d/skills/*/SKILL.md` files.

**Back-compat surface:**

The user-facing `fdp ...` CLI works identically. The Python-import surface
breaks for callers that imported `toksearch_d3d.fdp.environment.*` directly.
The `toksearch_d3d.setup_environment` top-level re-export stays; most
callers use that. A one-line note in the PR description points users at
`fdp.setup_environment(device="d3d")` as the new canonical path.

## Multi-device support

D3D is the only device today. The Device mechanism is provisional for that
reality. When a second device package arrives (`toksearch_mast`,
`toksearch_kstar`, ...), it registers via the same `fdp.devices` entry point.

What works peer-multi-device:

- **`ZarrSignal`** for any device's data: doesn't touch FDP env vars at all.
- **Explicit `location=` on `MdsSignal`**: bypasses `default_tree_path`.
- **`with Device.activate(): ...`**: swaps the runtime-adjustable env vars
  (notably `default_tree_path`) within the block. PTData (D3D-only),
  Pelican plugin config (shared via one config file), and BEARER_TOKEN
  (shared OAuth identity) don't need swapping.

What doesn't work (out of scope):

- Two `PTDATA_JSON_INDEX_DIR` values active at once. Acceptable because
  PTData is D3D-only.
- Truly load-time-locked env vars across multiple Pelican origins. The
  shared XRootD plugin config can list multiple namespaces, so this rarely
  matters in practice.

## CLI behavior preservation

Today's `fdp` CLI invocations keep working byte-for-byte once `fdp` is
installed:

| Invocation | After decoupling |
|---|---|
| `fdp run python script.py` | Same (default device auto-resolves to d3d when only toksearch_d3d is installed) |
| `fdp env` | Same |
| `fdp ls /fdp-d3d/some/path` | Same |
| `fdp skills install --backend claude` | Same |
| `fdp query "..."` | Same (shim into `toksearch query --backend amsc ...`) |
| `fdp chat` | Same (shim into `toksearch chat --backend amsc`) |

New invocations (no-op for single-device users):

- `fdp devices` — list installed devices.
- `fdp --default-device d3d run ...` — explicit device pick for one
  invocation (redundant when only D3D is installed).

## Configuration

`~/.fdp/config.toml` gains one new key:

```toml
default_device = "d3d"             # optional; auto-detected if only one installed

# Existing keys (from the toksearch.llm work) stay where they are:
[llm]
backend = "amsc"
```

Env vars: `FDP_DEFAULT_DEVICE`, `BEARER_TOKEN` (unchanged), plus everything
the active device's `apply()` sets (XRD_PLUGINCONFDIR, PTDATA_*,
default_tree_path, etc., as today).

## Testing

`fdp` ships with its own `tests/` directory using `unittest` discovery,
same shape as `toksearch`. Mocking conventions:

- `FdpFileSystem` tests mock `XRootD.client.FileSystem.dirlist`.
- Device-discovery tests monkeypatch `importlib.metadata.entry_points`.
- `setup_environment` tests temporarily set/restore `os.environ` (the
  existing `tests/test_fdp_environment.py` in `toksearch_d3d` ports
  near-verbatim).
- CLI subcommand tests mock `os.execvpe` (for chat/query) and
  `subprocess.run` (for run) — same pattern as the existing
  `toksearch_d3d/tests/test_fdp_query.py`.

`toksearch_d3d` adds one new test (`tests/test_fdp_decoupling.py`):

- Confirm `D3D_DEVICE` is discovered via `fdp.devices` entry point.
- Confirm `toksearch_d3d.setup_environment()` delegates to
  `fdp.setup_environment(device="d3d")`.

## Migration plan

Four sequential PRs across two repos:

1. **`GA-FDP/fdp` PR 1 — new repo bootstrap.** Carve `toksearch_d3d/fdp/`
   into the new repo. Adapt `environment.py` to read from a `Device`
   resolved at runtime. Add `devices.py` with the `Device` dataclass +
   entry-point discovery + default-device resolution + `Device.activate()`.
   Tests carry over. Conda recipe + GitHub Actions workflow modeled on
   `toksearch`. No device registered yet (the fallback in `environment.py`
   contains D3D's values for the case where no contributor is installed —
   this is a back-compat hack so the first PR is reviewable on its own).

2. **`GA-FDP/fdp` PR 2 — tag and release.** `release-<version>` tag → CI
   uploads to `ga-fdp` channel. Precondition for PR 3.

3. **`GA-FDP/toksearch_d3d` PR 3 — switch to fdp.** Delete
   `toksearch_d3d/fdp/`. Add `toksearch_d3d/fdp.py` with `D3D_DEVICE` and
   the back-compat `setup_environment` wrapper. Add the `fdp.devices` entry
   point. Add `fdp` to recipe run-deps. Update `toksearch_d3d/__init__.py`
   to use `fdp.setup_environment(device="d3d")`. CI depends on the new
   `fdp` conda release being available on the channel.

4. **`GA-FDP/toksearch_d3d` PR 4 — cleanup / docs.** Drop the D3D-fallback
   in `fdp`'s `environment.py` (no longer needed once toksearch_d3d
   contributes). Update toksearch_d3d docs to reference `fdp.*` instead of
   `toksearch_d3d.fdp.*`. Possibly folded into PR 3 if small.

## Risks

- **Release coordination.** Same pattern as the `toksearch >=2.7` exercise:
  `toksearch_d3d` PR 3 cannot land until `fdp` has been released. Standard
  discipline.
- **In-the-wild scripts importing `toksearch_d3d.fdp.*`.** Mitigated by
  keeping `toksearch_d3d.setup_environment` working. Documented in PR 3's
  description; users adapt with a one-line import change.
- **Versioneer + new-repo bootstrap.** Tag-based versioning needs a first
  `release-*` tag to produce a usable conda package. Either use a
  pre-release tag (`release-0.1.0a0`) for PR 1's first iteration, or do
  the manual `PKG_VERSION` override the way the other ga-fdp packages do
  in their first-release CI runs.
- **`xrootd` / `xrdcl-pelican` deps in the new `fdp` recipe.** These are
  already on the `ga-fdp` channel; pinning matches what `toksearch_d3d`
  uses today. No new dep surface.

## Out of scope (explicit non-features)

- A native `fdp chat` Session that runs tools in-process (no execvpe). This
  is the "simulations + historical data" multi-tool orchestrator vision.
  PR-1 of this decoupling sets up the contributor seams; the native Session
  is a follow-up.
- Per-device LLM presets beyond `default_llm_preset`. A device's preferred
  backend is single; users wanting other backends pass `--backend` to
  `fdp chat`/`query`, which the shim forwards.
- A new entry-point group for skills (`fdp.skills`). The existing
  `toksearch.llm.skills` group is read as-is. Renaming would be churn for
  no benefit.
- Migrating `toksearch.llm.cli` itself to live in `fdp`. The library
  stays in `toksearch`; `fdp` is the CLI/infrastructure layer that
  consumes it.
