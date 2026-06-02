# `default_llm_preset` Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the `--backend amsc` auto-injection that `fdp chat`/`fdp query` had pre-Phase-1, by re-adding an optional `default_llm_preset: str | None` field to the `Tokamak` schema, populating it in `d3d.yaml`, and restoring the consumer logic in `fdp.llm_shims._build_llm_cmd`.

**Architecture:** Three packages change additively. `fdp_schema` gains one optional field on `Tokamak` (no `schema_version` bump — additive only). `toksearch_d3d/data/d3d.yaml` gains one line: `default_llm_preset: amsc`. `fdp/fdp/llm_shims.py:_build_llm_cmd` reads `handle.schema.default_llm_preset` and injects `--backend <preset>` when set and the user didn't pass `--backend` explicitly. Release is staged: `fdp_schema 0.1.2` first, then `fdp 0.2.3` + `toksearch_d3d 0.9.5` in parallel.

**Tech Stack:** Python 3.11, pydantic v2, pyyaml, pytest, unittest.mock, versioneer, rattler-build, pixi.

**Reference spec:** `toksearch_d3d/docs/superpowers/specs/2026-06-02-default-llm-preset-design.md`

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `fdp_schema/fdp_schema/models.py` | Modify | Add `default_llm_preset: str \| None = None` to `Tokamak`. |
| `fdp_schema/tests/test_models.py` | Augment | Add `test_default_llm_preset_field` to `TestTokamak`. |
| `fdp_schema/tests/fixtures/d3d.yaml` | Modify | Add `default_llm_preset: amsc` (matches the prod yaml). |
| `fdp/fdp/llm_shims.py` | Modify | Restore `--backend` auto-injection in `_build_llm_cmd`. |
| `fdp/tests/test_llm_shims.py` | Augment | New `TestBuildLlmCmdAutoInjection` class. |
| `fdp/fdp/cli.py` | Modify | Reword `--backend` help text. |
| `fdp/recipe/recipe.yaml` | Modify | Bump `fdp-schema` floor to `>=0.1.2`. |
| `fdp/pixi.toml` | Modify | Bump `fdp-schema` floor to `>=0.1.2`. |
| `toksearch_d3d/toksearch_d3d/data/d3d.yaml` | Modify | Add `default_llm_preset: amsc`. |
| `toksearch_d3d/pixi.toml` | Modify | Bump `fdp-schema` floor to `>=0.1.2`. |

---

## Implementation phases

- **Phase A (Tasks 1–2):** Pre-flight + `fdp_schema` change.
- **Phase B (Tasks 3–6):** `fdp` consumer logic + CLI help text + dep bumps.
- **Phase C (Tasks 7):** `toksearch_d3d` catalog data + dep bump.
- **Phase D (Tasks 8–9):** Two-wave release.

The new behavior only activates once both fdp 0.2.3 and toksearch_d3d 0.9.5 are installed alongside fdp_schema 0.1.2. Intermediate states (after fdp_schema 0.1.2 but before the other two) are functionally identical to today's broken state — no risk window.

---

# Phase A: Pre-flight + `fdp_schema`

## Task 1: Create feature branches in all three repos

**Files:** none (git operations).

- [ ] **Step 1: Inspect each repo's branch and clean state.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema && git branch --show-current && git status -s | head -3
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && git branch --show-current && git status -s | head -3
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && git branch --show-current && git status -s | head -3
```

Expected: all on `main`, no modified tracked files (untracked scratch files are fine).

- [ ] **Step 2: Create the feature branch in each repo.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema && git checkout -b default-llm-preset-restore
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && git checkout -b default-llm-preset-restore
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && git checkout -b default-llm-preset-restore
```

Verify each by running `git branch --show-current` in the corresponding directory.

- [ ] **Step 3: Confirm latest release tags (for the version bump decisions in Phase D).**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema && git tag --list "release-*" | tail -2
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && git tag --list "release-*" | tail -2
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && git tag --list "release-*" | tail -2
```

Expected baseline (per spec):
- `fdp_schema`: latest `release-0.1.1`, bump target `release-0.1.2`.
- `fdp`: latest `release-0.2.2`, bump target `release-0.2.3`.
- `toksearch_d3d`: latest `release-0.9.4`, bump target `release-0.9.5`.

If actual values differ, adjust targets in Phase D accordingly.

No commit for this task.

---

## Task 2: Add `default_llm_preset` to `Tokamak` (TDD)

**Files:**
- Modify: `fdp_schema/tests/test_models.py`
- Modify: `fdp_schema/fdp_schema/models.py`
- Modify: `fdp_schema/tests/fixtures/d3d.yaml`

- [ ] **Step 1: Append failing test to `fdp_schema/tests/test_models.py` inside the `TestTokamak` class.**

Add this method at the end of `TestTokamak`:

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

- [ ] **Step 2: Run the test to verify it fails.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema
pixi run pytest tests/test_models.py::TestTokamak::test_default_llm_preset_field -v
```

Expected: FAIL — pydantic raises `AttributeError` or `ValidationError` because the field doesn't exist.

- [ ] **Step 3: Add the field to `Tokamak` in `fdp_schema/fdp_schema/models.py`.**

Locate the `Tokamak` class. The current shape ends with `extra_env: dict[str, str] = {}`. Add the new field on the next line, before the closing of the class:

```python
class Tokamak(BaseModel):
    schema_version: Literal[1] = 1
    name: str
    description: str = ""
    pelican_root: str | None = None
    origin_server: str | None = None
    locators: list[Locator] = []
    extra_env: dict[str, str] = {}
    default_llm_preset: str | None = None
```

- [ ] **Step 4: Run the test to verify it passes.**

```bash
pixi run pytest tests/test_models.py::TestTokamak::test_default_llm_preset_field -v
```

Expected: PASS.

- [ ] **Step 5: Update the test fixture `fdp_schema/tests/fixtures/d3d.yaml` to add the field.**

Read the file first to see the current shape, then add `default_llm_preset: amsc` between `origin_server` and `locators`:

```yaml
schema_version: 1
name: d3d
description: DIII-D fusion experiment, via Pelican
pelican_root: pelican://osg-htc.org:443/fdp-d3d
origin_server: root://fdp-d3d-origin.nationalresearchplatform.org:8443
default_llm_preset: amsc

locators:
  - kind: mds_tree
    name: main
    transport: pelican
    search_path:
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/codes/~t/~j~i/~h~g/~f~e/~d~c
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/usershots/~t
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/models/~t
      - pelican://osg-htc.org:443/fdp-d3d/archives/mdsplus/shots/~t/~f~e/~d~c
    auth: { kind: bearer_token, env: BEARER_TOKEN }

  - kind: ptdata_indexed
    name: main
    transport: pelican
    index_dir: pelican://osg-htc.org:443/fdp-d3d/archives/index/json/json_indexes_2026-01-13_12:22:11
    auth: { kind: bearer_token, env: BEARER_TOKEN }

  - kind: sql
    name: d3drdb
    driver: mssql
    host: d3drdb.gat.com
    port: 8001
    database: d3drdb
    tdsver: "7.0"
    auth: { kind: password_file, path: ~/D3DRDB.sybase_login }

extra_env:
  D3DATA: "yes"
  SYS_D3_DELIM: ";"
  CAKE_DB_PATH: "pelican://osg-htc.org:443/fdp-d3d/metadata/iri_logs.db"
```

(Add only the `default_llm_preset: amsc` line; keep the rest as-is. The block above is for reference.)

- [ ] **Step 6: Run the full fdp_schema test suite to confirm the fixture test still passes.**

```bash
pixi run pytest -q
```

Expected: all PASS (the fixture-loads test should consume the new field cleanly).

- [ ] **Step 7: Commit.**

```bash
git add fdp_schema/models.py tests/test_models.py tests/fixtures/d3d.yaml
git commit -m "Add Tokamak.default_llm_preset optional field"
```

---

# Phase B: `fdp` consumer

## Task 3: Restore auto-injection in `_build_llm_cmd` (TDD)

**Files:**
- Modify: `fdp/tests/test_llm_shims.py`
- Modify: `fdp/fdp/llm_shims.py`

Verify the `fdp` dev env has the new `fdp_schema` field available before starting:

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
pixi run python -c "
from fdp_schema import Tokamak
print('field' if 'default_llm_preset' in Tokamak.model_fields else 'no field')
"
```

If this prints `no field`, the `fdp_schema` editable install hasn't picked up Task 2's change. Run `pixi run pip install -e ../fdp_schema --force-reinstall --no-deps` to refresh, then re-check. If `fdp/pixi.toml` already uses a conda dep instead of editable, fall back to `cd ../fdp_schema && pixi run pip install . --target /tmp/check` and import from there to verify, then proceed knowing the dev env will pick up the field only after the new fdp_schema is published in Phase D Wave 1. Tests can still run because they construct `Tokamak` objects from the local source via the import path that the test mocks use.

- [ ] **Step 1: Append a failing test class to `fdp/tests/test_llm_shims.py`.**

```python
class TestBuildLlmCmdAutoInjection(unittest.TestCase):
    """Auto-injects --backend from the active tokamak's
    default_llm_preset, unless the user passed --backend explicitly."""

    def _handle(self, preset):
        from unittest import mock
        h = mock.MagicMock()
        h.schema.default_llm_preset = preset
        return h

    def test_injects_when_handle_has_preset_and_user_did_not(self):
        from fdp.llm_shims import _build_llm_cmd
        cmd = _build_llm_cmd("chat", ["--prompt", "hi"], self._handle("amsc"))
        self.assertIn("--backend", cmd)
        self.assertEqual(cmd[cmd.index("--backend") + 1], "amsc")

    def test_skips_when_user_passed_backend_explicitly(self):
        from fdp.llm_shims import _build_llm_cmd
        cmd = _build_llm_cmd(
            "chat",
            ["--backend", "openai", "--prompt", "hi"],
            self._handle("amsc"),
        )
        # Exactly one --backend in cmd, and it's the user's value.
        self.assertEqual(cmd.count("--backend"), 1)
        self.assertEqual(cmd[cmd.index("--backend") + 1], "openai")

    def test_skips_when_handle_is_none(self):
        from fdp.llm_shims import _build_llm_cmd
        cmd = _build_llm_cmd("chat", ["--prompt", "hi"], None)
        self.assertNotIn("--backend", cmd)

    def test_skips_when_preset_is_none(self):
        from fdp.llm_shims import _build_llm_cmd
        cmd = _build_llm_cmd("chat", ["--prompt", "hi"], self._handle(None))
        self.assertNotIn("--backend", cmd)

    def test_skips_when_preset_is_empty_string(self):
        from fdp.llm_shims import _build_llm_cmd
        cmd = _build_llm_cmd("chat", ["--prompt", "hi"], self._handle(""))
        self.assertNotIn("--backend", cmd)
```

If `import unittest` isn't already at the top of the file, add it; if `from unittest import mock` isn't at the top, the inline import inside `_handle` covers it.

- [ ] **Step 2: Run the tests to verify the first one fails.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
pixi run python -m pytest tests/test_llm_shims.py::TestBuildLlmCmdAutoInjection -v
```

Expected: `test_injects_when_handle_has_preset_and_user_did_not` FAILS (the current `_build_llm_cmd` body doesn't inject). The four "skips" tests may pass coincidentally (no injection happens because the function never injects).

- [ ] **Step 3: Restore the auto-injection in `fdp/fdp/llm_shims.py`.**

Locate `_build_llm_cmd`. The current body (post-Phase-1) looks like:

```python
def _build_llm_cmd(
    subcommand: str,
    passthrough_args: list[str],
    handle: "TokamakHandle | None",
) -> list[str]:
    """Construct argv for the `toksearch.llm.cli` delegate.

    ``handle`` is ``None`` when no tokamak contributor is installed
    ...
    """
    cmd = [sys.executable, "-m", "toksearch.llm.cli", subcommand]
    cmd.extend(passthrough_args)
    return cmd
```

Replace it with the restored version. Keep the existing imports (`sys`, the typing) untouched:

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

- [ ] **Step 4: Run the tests to verify all pass.**

```bash
pixi run python -m pytest tests/test_llm_shims.py::TestBuildLlmCmdAutoInjection -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Run the full test_llm_shims.py to confirm no pre-existing tests regressed.**

```bash
pixi run python -m pytest tests/test_llm_shims.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit.**

```bash
git add fdp/llm_shims.py tests/test_llm_shims.py
git commit -m "Restore --backend auto-injection from Tokamak.default_llm_preset"
```

---

## Task 4: Update `--backend` argparse help text

**Files:**
- Modify: `fdp/fdp/cli.py`

- [ ] **Step 1: Locate the current help text.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
grep -n "default_llm_preset\|active device" fdp/cli.py
```

Expected: one hit in `_add_llm_args` (or whatever the `--backend` flag is added in), with help text like:

```python
help="Backend / preset name (defaults to active device's default_llm_preset).")
```

- [ ] **Step 2: Update the help text to use post-Phase-1 vocabulary.**

In `fdp/fdp/cli.py`, change the matching line to:

```python
help="Backend / preset name (defaults to the active tokamak's default_llm_preset).")
```

(`device's` → `the active tokamak's`.)

- [ ] **Step 3: Confirm the CLI help renders the new text.**

```bash
pixi run fdp chat --help 2>&1 | grep -A1 backend
```

Expected: shows the new wording. If `fdp chat --help` errors for unrelated reasons (e.g., missing env), just confirm the file edit is correct by re-reading it.

- [ ] **Step 4: Commit.**

```bash
git add fdp/cli.py
git commit -m "Reword --backend help text for post-Phase-1 tokamak vocabulary"
```

---

## Task 5: Bump `fdp-schema` pin to `>=0.1.2` in `fdp`

**Files:**
- Modify: `fdp/recipe/recipe.yaml`
- Modify: `fdp/pixi.toml`

The new `Tokamak.default_llm_preset` field requires `fdp-schema 0.1.2`. The conda recipe and dev-env both need the floor pin bumped so the published `fdp 0.2.3` can't co-install with an older fdp-schema.

- [ ] **Step 1: Bump `fdp/recipe/recipe.yaml`.**

```bash
grep -n "fdp-schema" recipe/recipe.yaml
```

Expected: line like `- fdp-schema >=0.1.1`. Edit it to:

```yaml
    - fdp-schema >=0.1.2
```

- [ ] **Step 2: Bump `fdp/pixi.toml`.**

```bash
grep -n "fdp-schema" pixi.toml
```

Expected: line like `fdp-schema = ">=0.1.1"`. Edit it to:

```toml
fdp-schema = ">=0.1.2"
```

- [ ] **Step 3: Refresh the pixi env.**

```bash
pixi install
```

Note: until `fdp_schema 0.1.2` is actually published (Phase D Wave 1), pixi may complain that it can't resolve `fdp-schema >=0.1.2`. If so, leave the edits in place and skip pixi install; the changes will be committed and validated later during the Phase D release sequence.

If `pixi install` succeeds, run the test suite as a sanity check:

```bash
pixi run python -m pytest tests/test_llm_shims.py -v
```

Expected: all PASS.

- [ ] **Step 4: Commit.**

```bash
git add recipe/recipe.yaml pixi.toml pixi.lock 2>/dev/null || git add recipe/recipe.yaml pixi.toml
git commit -m "Bump fdp-schema pin to >=0.1.2 (Tokamak.default_llm_preset)"
```

(`pixi.lock` is added only if `pixi install` succeeded and updated it.)

---

## Task 6: Remove stale `--backend amsc` mentions from CLAUDE.md files

**Files:**
- Possibly modify: `/fusion/projects/dt/sammuli/fdp_dev/repos/CLAUDE.md`
- Possibly modify: `/fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/CLAUDE.md`

Spec Open Item #4: any guidance that tells users to type `--backend amsc`
manually is stale once auto-injection is restored. Find and remove.

- [ ] **Step 1: Grep both CLAUDE.md files for `--backend` mentions.**

```bash
grep -n "\-\-backend" /fusion/projects/dt/sammuli/fdp_dev/repos/CLAUDE.md /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d/CLAUDE.md 2>/dev/null
```

If grep finds nothing, no edits needed — skip to Step 3.

If grep finds hits, each one falls in one of two buckets:
- **Workaround instructions like "pass `--backend amsc` because the default is missing"** — DELETE. These existed during the Phase 1 regression window.
- **General reference like "fdp chat accepts `--backend`"** — KEEP. The flag is still documented; the auto-injection just makes it usually-not-needed.

- [ ] **Step 2: Edit each stale mention.**

For each hit identified in Step 1, decide which bucket and edit accordingly. If a sentence reads "you must pass `--backend amsc`", drop the sentence. If it reads "you can override with `--backend`", keep it.

- [ ] **Step 3: Commit any changes (each repo separately).**

If `repos/CLAUDE.md` changed:

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos
git add CLAUDE.md
git commit -m "Drop stale --backend amsc workaround from top-level CLAUDE.md"
```

If `toksearch_d3d/CLAUDE.md` changed:

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git add CLAUDE.md
git commit -m "Drop stale --backend amsc workaround from toksearch_d3d CLAUDE.md"
```

If grep in Step 1 found nothing, no commit for this task.

End of Phase B.

---

# Phase C: `toksearch_d3d` catalog data

## Task 7: Add `default_llm_preset: amsc` to `d3d.yaml` + bump pin

**Files:**
- Modify: `toksearch_d3d/toksearch_d3d/data/d3d.yaml`
- Modify: `toksearch_d3d/pixi.toml`

- [ ] **Step 1: Read the current `d3d.yaml`.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
cat toksearch_d3d/data/d3d.yaml
```

Should match (up to whitespace) the test fixture at `fdp_schema/tests/fixtures/d3d.yaml`.

- [ ] **Step 2: Add `default_llm_preset: amsc` between `origin_server` and `locators`.**

After the edit, the top of the file should read:

```yaml
schema_version: 1
name: d3d
description: DIII-D fusion experiment, via Pelican
pelican_root: pelican://osg-htc.org:443/fdp-d3d
origin_server: root://fdp-d3d-origin.nationalresearchplatform.org:8443
default_llm_preset: amsc

locators:
  ...
```

(Add only the `default_llm_preset: amsc` line; keep everything else.)

- [ ] **Step 3: Bump `toksearch_d3d/pixi.toml`'s fdp-schema pin.**

```bash
grep -n "fdp-schema" pixi.toml
```

Expected: line like `fdp-schema = ">=0.1.1"`. Edit it to:

```toml
fdp-schema = ">=0.1.2"
```

- [ ] **Step 4: Refresh the pixi env.**

```bash
pixi install
```

Same caveat as fdp's Task 5: until `fdp_schema 0.1.2` is published, pixi may fail to resolve. If so, skip the install; revisit during Phase D.

If `pixi install` succeeds, verify the new field is reachable:

```bash
pixi run python -c "
from fdp_schema import load_tokamak
from toksearch_d3d.data import d3d_yaml
t = load_tokamak(d3d_yaml)
print(t.default_llm_preset)
"
```

Expected: prints `amsc`.

- [ ] **Step 5: Verify the catalog test still passes.**

```bash
pixi run python -m pytest tests/test_catalog.py -v
```

Expected: all PASS. The existing `test_d3d_yaml_validates` doesn't assert anything about `default_llm_preset`; the new field validates because `fdp_schema 0.1.2`'s `Tokamak` model accepts it.

- [ ] **Step 6: Commit.**

```bash
git add toksearch_d3d/data/d3d.yaml pixi.toml pixi.lock 2>/dev/null || git add toksearch_d3d/data/d3d.yaml pixi.toml
git commit -m "Add default_llm_preset: amsc to d3d.yaml; bump fdp-schema pin"
```

---

# Phase D: Release

## Task 8: Wave 1 — release `fdp_schema 0.1.2`

**Files:** none (git tag operations).

- [ ] **Step 1: Verify clean state on the `default-llm-preset-restore` branch.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp_schema
git status -s
git branch --show-current
git log --oneline main..default-llm-preset-restore
```

Expected: 1 commit ahead of main (the Task 2 commit). Clean working tree.

- [ ] **Step 2: Fast-forward merge to main and push.**

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
git merge --ff-only default-llm-preset-restore
git push origin main
```

If `pull --ff-only` fails because main moved ahead remotely, rebase the feature branch onto the updated main first, then re-merge.

- [ ] **Step 3: Tag and push.**

```bash
git tag release-0.1.2
git push origin release-0.1.2
```

- [ ] **Step 4: Monitor the CI run.**

```bash
gh run list --repo GA-FDP/fdp_schema --branch release-0.1.2 --limit 1
```

Wait for the run to complete (historically ~30s for fdp_schema). Use `gh run view --repo GA-FDP/fdp_schema <run-id>` to inspect if needed.

- [ ] **Step 5: Verify the package landed on the channel.**

```bash
pixi search fdp-schema -c ga-fdp 2>&1 | grep -E "Name|Version" | head -3
```

Expected: prints `fdp-schema 0.1.2`. Anaconda channel indexing can take 1-2 minutes after the upload step finishes; if `0.1.2` isn't there yet, wait briefly and retry.

- [ ] **Step 6: Delete the local feature branch.**

```bash
git branch -d default-llm-preset-restore
```

(No remote-delete: we didn't push the feature branch to origin; FF-merged main carries the commit.)

End of Wave 1.

---

## Task 9: Wave 2 — release `fdp 0.2.3` and `toksearch_d3d 0.9.5`

**Files:** none (git tag operations).

Wave 2 can release the two packages in parallel — neither depends on the other for this change. Both depend on `fdp_schema 0.1.2`, which Wave 1 just published.

- [ ] **Step 1: Refresh both repos' pixi envs now that `fdp_schema 0.1.2` is on the channel.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && pixi install
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi install
```

Expected: both succeed. If either complained about `fdp-schema >=0.1.2` not being resolvable during Tasks 5 / 7, this is where they get unstuck.

If either repo's `pixi.lock` updated, stage and amend the relevant Task-5 or Task-7 commit:

```bash
git add pixi.lock
git commit --amend --no-edit
```

(`--amend --no-edit` keeps the original message; preserves history clarity. Only do this BEFORE pushing to main.)

- [ ] **Step 2: Verify tests pass in both repos.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && pixi run python -m pytest tests/test_llm_shims.py -v 2>&1 | tail -5
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && pixi run python -m pytest tests/ 2>&1 | tail -5
```

Expected: all PASS. Some toksearch_d3d tests may skip if they require credentials; that's fine.

- [ ] **Step 3: FF-merge `fdp` to main and push.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp
git fetch origin
git checkout main
git pull --ff-only origin main
git merge --ff-only default-llm-preset-restore
git push origin main
git tag release-0.2.3
git push origin release-0.2.3
```

- [ ] **Step 4: FF-merge `toksearch_d3d` to main and push.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
git fetch origin
git checkout main
git pull --ff-only origin main
git merge --ff-only default-llm-preset-restore
git push origin main
git tag release-0.9.5
git push origin release-0.9.5
```

- [ ] **Step 5: Monitor both CI runs.**

```bash
gh run list --repo GA-FDP/fdp --branch release-0.2.3 --limit 1
gh run list --repo GA-FDP/toksearch_d3d --branch release-0.9.5 --limit 1
```

`fdp` CI is fast (~1 min). `toksearch_d3d` CI is slow (~15-19 min) because the recipe test runs `testit.py`.

If `toksearch_d3d`'s recipe test fails because the conda solver picked an old fdp-schema, the recipe's run-dep block already pins `fdp-schema >=0.1.1` (from Phase 1). Since 0.1.2 was published in Wave 1, the solver should pick it. If it doesn't, the spec's Open Items #1 calls out the lesson from connect-d3drdb-migration: bump the recipe pin (`toksearch_d3d/recipe/recipe.yaml`) to explicitly require `>=0.1.2` and re-tag.

- [ ] **Step 6: Confirm both packages on the channel.**

```bash
pixi search fdp -c ga-fdp 2>&1 | grep -E "Name|Version" | head -3
pixi search toksearch_d3d -c ga-fdp 2>&1 | grep -E "Name|Version" | head -3
```

Expected: `fdp 0.2.3` and `toksearch_d3d 0.9.5`.

- [ ] **Step 7: Delete the local feature branches.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/fdp && git branch -d default-llm-preset-restore
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d && git branch -d default-llm-preset-restore
```

- [ ] **Step 8: End-to-end verification.**

```bash
cd /fusion/projects/dt/sammuli/fdp_dev/repos/toksearch_d3d
# Help text mentions tokamak (not device).
pixi run fdp chat --help 2>&1 | grep -A1 backend
# Auto-injection actually fires.
pixi run fdp run python -c "
from fdp.llm_shims import _build_llm_cmd
from fdp import catalog
cmd = _build_llm_cmd('chat', ['--prompt', 'hi'], catalog['d3d'])
print(cmd)
assert '--backend' in cmd
assert cmd[cmd.index('--backend') + 1] == 'amsc'
print('OK: amsc auto-injected')
"
```

Expected: prints `OK: amsc auto-injected`.

End of plan.

---

## Notes for the executing engineer

- **TDD discipline**: each TDD task starts with a failing test, then minimal code to pass. The injection logic is the only place where TDD is meaningful; the catalog YAML edits and dep bumps are not test-driven (they're declarative changes).
- **Branch-pin chicken-and-egg**: Tasks 5 and 7 bump `fdp-schema >=0.1.2` BEFORE `fdp_schema 0.1.2` is on the channel. Pixi may refuse to resolve. The plan calls this out at each step — proceed without `pixi install` succeeding if needed; the Phase D Wave 2 refresh fixes it.
- **No new schema_version**: adding an optional field does not bump `schema_version` (which is `Literal[1]`). Documented in the spec; do not change it.
- **Don't push branches/tags before review unless explicitly authorized.** The plan documents what to do; the user decides when.
