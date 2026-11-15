# Offline PCS setup reader — plan

Spec: `docs/superpowers/specs/2026-11-15-pcssetup-reader-design.md`.
Branch `pcssetup-reader` from `origin/main` (d8d8753).

## Phase A — parser and tests (offline) — done

1. Learn the format from d3d_pcs (read-only) and write the format note
   into the spec. — done
2. `toksearch_d3d/pcssetup/`:
   - `wa10.py` — split a file into header and typed sections; build a
     file from sections (`store_shotsetup` layout).
   - `decode.py` — port of `unparcel_setup_data.c` with the versioned
     `field_def` tables; `pcs_forarchive` parameter blocks.
   - `model.py` — `Setup`/`Category`/`Phase`/`Algorithm`/… and the path
     API (`read`, `paths`, `snapshot`, `item`).
   - `items.py` — generic/values/labels/file/matrix/opsetup decoding as
     pcsapi's editors do it.
   - `fetch.py` — rebuild the `.wa10` from PTDATA `PCSSETUP` (variable
     header + data words).
   - `signal.py` — `PcsSetupSignal` for Pipelines. — done
3. Tests: `tests/test_pcssetup_reader.py` (synthetic setups from
   `tests/pcssetup_synth.py`; no real setup data is checked in), `tests/test_pcssetup_live.py` (fetch + Signal, needs
   `fdp run`). Fix `pcssetup-to-wa10` to write the whole file. — done
4. Spec and plan. — done

## Phase B — validation against a waveserver (deferred)

Not run. The offline comparison (0 mismatches on 132,764 items) was judged
enough. If it is wanted later: restore a few archived setups into an
isolated simulated-PCS waveserver, take pcssetup's snapshot, and compare it
with `read_wa10` of the waveserver's re-archived setup file (decoder check)
and with `pcssetup(shot)` (archive vs restore). The live test
`TestWaveserverReference` takes such pairs via `PCSSETUP_REFERENCE_DIR`.
