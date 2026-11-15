# Offline PCS setup reader (`toksearch_d3d.pcssetup`) — design

Date: 2026-11-15. Branch `pcssetup-reader`.

## Goal

Read a DIII-D shot's PCS setup values (categories, phases, the algorithm
of each phase, entry behaviour, anchor times, waveform vertices,
parameter values) as an ordinary offline fetch, addressed by the setup
paths pcssetup uses, `'Category|Phase|Subset|Data item'`, so setups can
be compared across thousands of shots without a waveserver.

Until now every reader (pcssetup, pcsgui) handed the file to a live
waveserver; even `Util::setUp(shot)` returns only structure, and values
need `restoreSetUp` plus item-by-item reads.

## Format note

All file:line references are to the d3d_pcs source tree unless noted.

**Container.** A `.wa10` is the on-disk form of `struct pfi42`
(`core/infra/pfi.h` lines 80-124): a 192-byte fixed header, then five
variable-header sections — ascii, int16, int32, real32, real64 — then a
data section; the header's word counts (`nwascii` … `nwreal64`,
`nwdata`) are in 16-bit words. `store_shotsetup` writes it and
`read_shotsetup_setupfile` reads it (`core/infra/setup_routines.c`
lines 115-377, 386-548). Files are big-endian: `setup_file_processor_type
= ALIGN8ON8` (`core/infra/restore_paramdata.c` line 91), and both
routines byte-swap on a little-endian host. `nbdata` is 32, or 16 in old
setups (widened to 32 bits on read, `setup_routines.c` lines 536-543).
The fixed header is constant apart from the counts (`setup_routines.c`
lines 125-163: pfi 42, `"PCS "`, `"PASY"`, ptname `PCSSETUP`, dfi 2205);
files written by the PCS carry shot 0 and a zero time.

**PTDATA.** At shot start the PCS writes the same `pfi42` as pointname
`PCSSETUP` (`pcsshotfile_ptdata.c` `pfi42_write`; read back in
`read_from_shotnum`). The five sections become the point's variable
header and the data section its data. So **the point's data words alone
are not the file**: they are only the index records (718 kB of the 4 MB
file for 204019). The 2026-05-04 `pcssetup-to-wa10` tool assumed
otherwise; it now rebuilds the file from the variable header (via
`ptdata.PtDataReader.read_header`) plus the raw data words, and the body
is byte-identical to what the PCS's own `pcssetup_to_wa10` writes
(checked for 204019 and 207123; only shot and time differ in the header).

**Records.** `setup_driver.h` (lines 37-189) and `setup_driver.c`
(lines 87-386) define the archive as tables of `struct field_def`
`{field_type, parameter}`; `parcel_setup_data.c` writes by walking them
and `unparcel_setup_data.c` (lines 103-903) reads by walking the same
tables. Scalars go to their typed section: CHAR (NUL-terminated string)
to ascii, SHORT to int16, INT to int32, FLOAT to real32, FLOATD (a float
stored as a double) and DOUBLE to real64. Before each child structure a
`struct indices` record — seven uint32: data type and the six section
positions — goes to the data section; the reader checks each against its
own positions (`check_indices`, lines 911-939), which makes the decode
self-verifying. Every table starts with a VERSION entry: the archive
stores the table's version as one int16 and the reader picks the
matching table (`unparcel_setup_data.c` lines 255-274), so old setups
decode with the tables of their time. Versions in the restore tables:
install 1-4, phase 1-2, algorithm 1-2, all others 1.

**Hierarchy.** install (archive version, `hold_onetick`, counts of
categories, cat/algs and waveforms, release identifier, change history)
→ global (`baseline_count`, `timetostop`, `maggain`) → for each category:
name, identifier, version; its phase sequences (name, a waveform
definition, vertices); its algorithms (identifier, version, name up to
the first comma, subset names, waveform list: name, description, 1-based
subset number); its phases (number, name, entry behaviour, anchor time,
access control, the algorithm by identifier+version — resolved to the
last archived cat/alg with that pair, `r_get_cat_alg` lines 951-979 —
one vertex list per waveform of that algorithm, and the parameter
data). Vertices are (FLOATD x, FLOAT y). Entry behaviour 1-4 maps to
pcsapi's `beginOfPhs`, `timeOfLastExit`, `timePhsReach`,
`anchorTimePhsReach` (`core/infra/pcsapi/util.hpp` lines 113-118).

**Paths.** As the waveserver builds them (`pcsapi/util.cpp` lines
203-262): Category | Phase | the phase algorithm's subset name for the
waveform's subset number | waveform name. Static (parameter) data items
are entries of the same waveform list whose description starts with
`StaticData` (`util.cpp` lines 195-200).

**Parameters.** Per phase, `pcs_forarchive` (`core/infra/waveparams.c`
lines 176-489) stores the archive-flagged parameter blocks in a
self-describing form: int32 `[19971, nblocks]`, then per block
`[namesize, datasize, flags, insert_order, mem_align, ndesc]` and
`ndesc` × `(type, count, offset)` descriptors followed by the block's
int values; the block name and char values go to ascii, the other types
to their sections. Descriptor types: char 1, short 2, int 3, uint32 4,
float 5, double 6, long 7 (`core/infra/descriptors.h` lines 40-58).
Install versions < 3 store the five per-phase counts as int16 (with a
65536 correction for float counts, `unparcel_setup_data.c` lines
750-784). Setups from before pcs_forarchive (shots up to ~100000, 1997-99)
use older per-algorithm archive layouts (format word 3 or 4); the reader
keeps those arrays undecoded.

**Items.** pcsapi's editors read a static data item `D` from blocks
named after it (`pcsapi/editorInfo.cpp`): Generic from `D :data` and
`D :labels` (lines 243-410; item titles come from the labels, parsed
with `|` and `:` keywords — `title:` keeps the text verbatim, a
`,old name` suffix is dropped), File from `D :file name` (672-695),
Matrix from `D dimensions/row names/col names/names/data` (455-520),
OpSetUp from `D :infra` and `D :infra cpu` (743-793). The reader infers
the kind from which blocks exist, because the item's editor name is
compiled into the PCS and not archived. Char data are NUL-separated
strings with empty ones dropped (pcsapi `interpretStrings`).

**Dependence on compiled PCS tables: none for decoding.** The record
tables are fixed, versioned infrastructure (ported into
`toksearch_d3d/pcssetup/decode.py`); everything algorithm-specific
(names, subsets, waveform lists, parameter block layouts, labels) is in
the file. What is compiled and not archived: the editor name of each
static item (inferred from blocks, matches pcsapi on all items it
decodes); default values; and, for a few items, the labels or the data
block when the algorithm did not flag them for archiving (4 generic
items per modern setup have values but no labels → kind `values`; 1 has
labels but no values → kind `labels`).

**Archive vs restored values.** The reader returns what the setup held
when archived. A waveserver restoring that shot into a newer PCS shows
some different values: algorithms forced by `algs_config.json`, items
added since (filled with defaults), categories added since, renamed
labels.

## API

```python
from toksearch_d3d.pcssetup import read_wa10, pcssetup, PcsSetupSignal
s = read_wa10(path_or_bytes, strict=True)  # Setup
s = pcssetup(shot)                         # fetch PCSSETUP (under `fdp run`)
s.read("C|P")        # {'alg', 'entry_behavior', 'anchor_time'}
s.read("C|P|S|D")    # vertices | {title: value} | values tuple | file name |
                     # MatrixValue | OpSetupValue | parameter blocks
s.paths(scope=None)  # phase and data paths
s.snapshot(scope=None)  # {path: (kind, value)}, pcssetup Session._snapshot shape
s.item("C|P|S|D")    # DataItem (.read() -> (kind, value), .phase.param_blocks)
s.categories, s.category(n), s.phase(c, p), s.subsets(c, p), s.data_items(c, p, s)
s.shot, s.release, s.install, s.change_history, s.header
pcssetup_wa10_bytes(shot)                  # the rebuilt .wa10
PcsSetupSignal(paths=[...]) / PcsSetupSignal(scope="Gas")   # toksearch Signal
```

Kinds: phase, waveform, generic, values, labels, file, matrix, opsetup,
opaque (other editors; blocks stay readable), unreadable (inconsistent
blocks, e.g. label/data count mismatch — pcsapi fails on the same items).

Decode is about 0.4 s per modern setup; fetch plus decode 0.5-0.7 s.

## Validation (offline)

Reference: pcssetup `Session._snapshot()` dumps of simulated-PCS
waveservers (sessions sourced from shots 204019 and 207123).

- **Waveserver-written setups** (`setups/<id>.wa10`, the waveserver's
  own NextShot file copied right after the snapshot): 24 files, 132,764
  items matched, 0 mismatched, 0 missing, 0 extra; plus 74 `values`
  (values match; titles not archived) and 22 `labels` (titles match;
  values not archived); 3,984 items pcssetup itself could not read
  (opaque/unreadable) are not compared. No real setup is checked in;
  `tests/test_pcssetup_live.py` repeats this comparison when
  `PCSSETUP_REFERENCE_DIR` points at such pairs.
- **Original shot setups vs restored waveserver** (`start.wa10` from
  PTDATA vs `start.json` after restore): 19 pairs, 107,888 matched, 448
  differ, 2,271 only on the waveserver, 9,604 only in the file — every
  inspected difference is restore semantics (above), not decoding.
- PTDATA decode sweep: 19 sampled shots from 90000 to 207787 (every
  ~5000-10000 shots, plus 165920, 198873, 204019, 206863, 207388,
  207787) all decode with every index record checked; shots ≤ 100000
  without parameter decoding. 80000, 85000 and 120000 have no PTDATA
  shot file.

## Not done / limits

- Editors pcssetup leaves opaque (segment, beam control, patch, …)
  return their raw blocks, not structured values.
- Default values are not in the file.
- `PcsSetupSignal` fetches the whole point per shot; a cache of decoded
  setups for repeated studies would be a follow-on.
