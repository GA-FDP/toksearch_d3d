# `default_llm_preset` Restoration — Design

**Date:** 2026-06-02
**Status:** Approved, ready for plan
**Context:** Restores a Phase 1 regression. The original fdp-schema spec
documented it as a Non-Goal, intentionally deferred:
> **`default_llm_preset` on `Tokamak`.** Removed from the schema; the
> current D3D Device's `"amsc"` value gets dropped in this release. Per
> Framing 3 of the handoff, LLM presets belong to `toksearch.llm.presets`
> ownership, not the catalog.

In practice, the regression matters in daily use: `fdp chat` and
`fdp query` lost the `amsc`-by-default behavior D3D users had relied on.
The Phase 1 framing conflated *preset definitions* (the `Preset`
dataclass with backend/model/url/api_key, correctly owned by
`toksearch.llm.presets`) with *per-tokamak default preset names* (a
single string, naturally tokamak-scoped metadata). Putting that string
back in the catalog is the smallest correct fix.

## Problem

Three concrete issues created by Phase 1's removal of
`default_llm_preset` from the `Tokamak` schema:

1. **`fdp chat` and `fdp query` no longer auto-inject `--backend amsc`
   for D3D.** Pre-Phase-1, `fdp/fdp/llm_shims.py:_build_llm_cmd` checked
   `device.default_llm_preset` and injected `--backend <preset>` into
   the argv passed to `toksearch.llm.cli`. The Phase 1 cleanup commit
   (`6cfbf9d` — "Delete fdp.devices module and tests; simplify
   environment.py") deleted that block. Users must now type
   `--backend amsc` on every invocation.
2. **Dangling promise in CLI help text.** `fdp/fdp/cli.py:_add_llm_args`
   still advertises that `--backend` "defaults to active device's
   `default_llm_preset`" — accurate before Phase 1, false after it.
3. **Existing preset registry has no per-tokamak default.**
   `toksearch.llm.presets` entry-point group already discovers `amsc`
   from `toksearch_d3d/pyproject.toml`, and `toksearch.llm.cli`'s
   `--backend amsc` flag resolves it correctly. The only thing missing
   is the *mapping* from tokamak (`"d3d"`) to default preset name
   (`"amsc"`).

## Goals

Three packages change, each with a small additive edit. The single
source of truth for the mapping is the catalog YAML.

- **`fdp_schema`** adds one optional field on `Tokamak`:
  `default_llm_preset: str | None = None`. No `schema_version` bump
  (additive only).
- **`toksearch_d3d/toksearch_d3d/data/d3d.yaml`** adds one line:
  `default_llm_preset: amsc`.
- **`fdp/fdp/llm_shims.py:_build_llm_cmd`** restores the auto-injection
  block, parameterized on `handle.schema.default_llm_preset` instead of
  the deleted `device.default_llm_preset`.
- **`fdp/fdp/cli.py:_add_llm_args`** rewords the `--backend` help text to
  match the post-Phase-1 vocabulary ("tokamak's `default_llm_preset`").

## Non-Goals

- **Validating preset names at catalog-load time.** That would couple
  `fdp_schema` to `toksearch.llm.presets`/discovery, defeating the layer
  separation Phase 1 established. The CLI invocation naturally fails
  with a clear error from `toksearch.llm.presets.resolve_preset` if the
  name doesn't resolve at runtime.
- **Multiple default presets per tokamak** (e.g., per-subcommand defaults
  like one for chat and another for query). Today D3D has one. If a
  legitimate need ever appears, the schema can extend to
  `default_llm_presets: dict[str, str]` without breaking the single
  string. YAGNI.
- **Persistent user overrides** beyond `--backend` on the command line.
  `~/.fdp/config.toml`-driven overrides are useful but not required to
  restore the regression. Separate feature if/when wanted.
- **A new entry-point group like `toksearch.llm.tokamak_defaults`**. One
  brainstorming option was to keep the catalog purely
  data-locator-shaped and put the tokamak→preset mapping in a separate
  entry-point group. Rejected: the catalog already carries non-locator
  metadata (`description`, `extra_env`), one more optional string is
  consistent, and adding a new entry-point machinery for a single string
  per tokamak is disproportionate.

## Architecture

Single new edge in the data flow:

```
toksearch_d3d/data/d3d.yaml
     │ (default_llm_preset: amsc)
     ▼
fdp_schema.Tokamak.default_llm_preset
     │
     ▼
fdp.catalog["d3d"].schema.default_llm_preset
     │
     ▼
fdp.llm_shims._build_llm_cmd → ["--backend", "amsc", ...]
     │
     ▼
toksearch.llm.cli --backend amsc
     │ (toksearch.llm.presets.resolve_preset("amsc"))
     ▼
toksearch_d3d.llm.AMSC_PRESET (Preset dataclass)
```

`fdp_schema` stays a leaf; `toksearch.llm.presets` discovery is
unaffected; the catalog is the single source of truth for the
tokamak→preset-name mapping.

### Schema field

`fdp_schema/fdp_schema/models.py`:

```python
class Tokamak(BaseModel):
    schema_version: Literal[1] = 1
    name: str
    description: str = ""
    pelican_root: str | None = None
    origin_server: str | None = None
    locators: list[Locator] = []
    extra_env: dict[str, str] = {}
    default_llm_preset: str | None = None    # ← new
```

The value is the name of a preset registered via the
`toksearch.llm.presets` entry-point group. `None` means "no default;
let `toksearch.llm.cli` use its own built-in default of `anthropic`."

### Catalog data

`toksearch_d3d/toksearch_d3d/data/d3d.yaml`:

```yaml
schema_version: 1
name: d3d
description: DIII-D fusion experiment, via Pelican
pelican_root: pelican://osg-htc.org:443/fdp-d3d
origin_server: root://fdp-d3d-origin.nationalresearchplatform.org:8443
default_llm_preset: amsc      # ← new
locators:
  - kind: mds_tree
    ...
```

### Consumer logic

`fdp/fdp/llm_shims.py`:

```python
def _build_llm_cmd(
    subcommand: str,
    passthrough_args: list[str],
    handle: "TokamakHandle | None",
) -> list[str]:
    """Construct argv for the `toksearch.llm.cli` delegate.

    If the active tokamak has `default_llm_preset` set in its catalog
    entry and the user did NOT pass `--backend` explicitly, inject
    `--backend <preset>` so D3D users get the expected default
    (e.g. `amsc`) without typing it every time.
    """
    cmd = [sys.executable, "-m", "toksearch.llm.cli", subcommand]
    if (
        handle is not None
        and handle.schema.default_llm_preset
        and "--backend" not in passthrough_args
    ):
        cmd.extend(["--backend", handle.schema.default_llm_preset])
    cmd.extend(passthrough_args)
    return cmd
```

Three guards, all standard:
1. `handle is not None` — no tokamak resolved (e.g., fdp's dev env with
   no contributor installed); skip.
2. `handle.schema.default_llm_preset` — non-empty string check; both
   `None` and `""` skip.
3. `"--backend" not in passthrough_args` — user's explicit flag always
   wins.

### CLI help text fix

`fdp/fdp/cli.py:_add_llm_args`:

```python
p.add_argument(
    "--backend", default=None,
    help="Backend / preset name (defaults to the active tokamak's "
         "default_llm_preset).")
```

Removes the dangling "active device's" wording and matches post-Phase-1
vocabulary.

## Testing Strategy

### `fdp_schema/tests/test_models.py` — augment `TestTokamak`

```python
def test_default_llm_preset_field(self):
    from fdp_schema.models import Tokamak
    # Default is None.
    t = Tokamak(name="x")
    self.assertIsNone(t.default_llm_preset)
    # Accepts a string.
    t = Tokamak(name="x", default_llm_preset="amsc")
    self.assertEqual(t.default_llm_preset, "amsc")
    # YAML-style round-trip.
    t2 = Tokamak.model_validate(
        {"name": "x", "default_llm_preset": "amsc"}
    )
    self.assertEqual(t2.default_llm_preset, "amsc")
```

### `fdp_schema/tests/fixtures/d3d.yaml` — add the field

Update the test fixture so the existing `test_d3d_fixture_loads` keeps
catching real-world breaks. The fixture should byte-match
`toksearch_d3d/data/d3d.yaml`.

### `fdp/tests/test_llm_shims.py` — new test class

```python
class TestBuildLlmCmdAutoInjection(unittest.TestCase):
    def _handle(self, preset):
        h = mock.MagicMock()
        h.schema.default_llm_preset = preset
        return h

    def test_injects_when_handle_has_preset_and_user_did_not(self):
        cmd = _build_llm_cmd("chat", ["--prompt", "hi"], self._handle("amsc"))
        self.assertIn("--backend", cmd)
        self.assertEqual(cmd[cmd.index("--backend") + 1], "amsc")

    def test_skips_when_user_passed_backend_explicitly(self):
        cmd = _build_llm_cmd(
            "chat",
            ["--backend", "openai", "--prompt", "hi"],
            self._handle("amsc"),
        )
        # exactly one --backend in cmd, and it's the user's value
        self.assertEqual(cmd.count("--backend"), 1)
        self.assertEqual(cmd[cmd.index("--backend") + 1], "openai")

    def test_skips_when_handle_is_none(self):
        cmd = _build_llm_cmd("chat", ["--prompt", "hi"], None)
        self.assertNotIn("--backend", cmd)

    def test_skips_when_preset_is_none(self):
        cmd = _build_llm_cmd("chat", ["--prompt", "hi"], self._handle(None))
        self.assertNotIn("--backend", cmd)

    def test_skips_when_preset_is_empty_string(self):
        cmd = _build_llm_cmd("chat", ["--prompt", "hi"], self._handle(""))
        self.assertNotIn("--backend", cmd)
```

### End-to-end manual check

Not a test — a one-time confirmation before tagging:

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
pixi run fdp chat --help | grep -A1 backend    # expect new help text
pixi run fdp run python -c "
from fdp.llm_shims import _build_llm_cmd
from fdp import catalog
print(_build_llm_cmd('chat', ['--prompt', 'hi'], catalog['d3d']))
"
# Expect: ['..../python', '-m', 'toksearch.llm.cli', 'chat',
#          '--backend', 'amsc', '--prompt', 'hi']
```

## Release Plan

Three packages, in two waves to respect the dep order:

1. **Wave 1**: `fdp_schema 0.1.2`. Patch bump (additive optional field).
   Recipe + pyproject unchanged besides versioneer tag. Wait for the
   conda upload before Wave 2 — `fdp 0.2.3` and `toksearch_d3d 0.9.5`
   both want `fdp-schema >=0.1.2`.
2. **Wave 2** (parallel): `fdp 0.2.3` and `toksearch_d3d 0.9.5`. Each
   bumps the `fdp-schema` floor pin in `recipe.yaml` and `pixi.toml` to
   `>=0.1.2`. The recipe-level changes are tiny; the meaningful
   behavioral change is `fdp 0.2.3`'s `_build_llm_cmd` restoration plus
   `toksearch_d3d 0.9.5`'s `d3d.yaml` adding the field.

**Intermediate state safety:** if Wave 1 ships but Wave 2 hasn't yet,
behavior is unchanged from today (no auto-injection — same regression
state). No risk of a broken intermediate.

## Open Items for the Plan

1. **Branch naming convention.** Phase 1 used `fdp-schema-phase1` across
   repos; connect-d3drdb used `connect-d3drdb-migration`. Suggest
   `default-llm-preset-restore` for consistency, but verify by
   convention.
2. **Confirm `_add_llm_args`'s actual location.** The exploration noted
   it lives in `fdp/fdp/cli.py`; if the function name or location
   differs, adjust during the plan.
3. **Confirm `_build_llm_cmd`'s passthrough convention.** The current
   code passes `passthrough_args` after `cmd.extend([..., subcommand])`.
   The auto-injection block in this design inserts `--backend` BEFORE
   the passthrough args (so it stays adjacent to the subcommand name).
   That's a cosmetic choice and matches the pre-Phase-1 order; the plan
   should preserve it.
4. **Update CLAUDE.md mention of `--backend`.** The top-level
   `repos/CLAUDE.md` has a Pelican/OSDF section that lists env vars; no
   mention of LLM preset defaults. Check both CLAUDE.md files for stale
   `--backend amsc` instructions that can be deleted now that the
   default is back.

## Suggested Next Step

Invoke the `superpowers:writing-plans` skill to decompose this design
into a TDD-staged implementation plan with review checkpoints.
