---
name: toksearch-d3d-d3drdb
description: DIII-D shot metadata (d3drdb) through connect_d3drdb — the published snapshot you get by default and live=True for SQL Server, the shot ceiling, pinning, what T-SQL works, what is excluded, and a guide to the tables (SHOTS, SHOTS_TYPE, SUMMARIES, DISRUPTIONS, disruption_warning, SIGNAL_NAMES, RUNS, ENTRIES)
user-invocable: false
license: Apache-2.0
compatibility: Claude Code
metadata:
  author: GA-FDP
  version: "1.0"
  url: https://ga-fdp.github.io/toksearch/
---

# DIII-D shot metadata: d3drdb

`d3drdb` is DIII-D's operations and physics-summary database. Every plasma
pulse has an integer **shot** number, and almost every table is keyed on
`shot`. Use it to *select* shots and attach labels; the waveforms themselves
live in PTDATA, MDSplus and IMAS, and you fetch them with TokSearch afterwards.

Three things catch people out: the default connection is a **published
snapshot**, not the live server; a snapshot stops at a **shot ceiling**; and
some `SUMMARIES` scalars hold unphysical sentinel values.

## 1. What you get

`connect_d3drdb()` returns the newest **published snapshot** of d3drdb:
Parquet files on the FDP origin, read remotely through DuckDB. You get the same
answer on-site and off. `connect_d3drdb(live=True)` dials the live SQL Server
instead, which works only on-site. **Neither falls back to the other.** If the
snapshot cannot be found or read, you get a `toksearch.sql.snapshot.SnapshotError`
and no live connection. If `live=True` cannot connect, you get that error and no
snapshot.

Both return a DB-API-shaped connection: `with`, `cursor()` and
`pd.read_sql(sql, conn)` all work. Your T-SQL runs unchanged on either (§4).

```python
import pandas as pd
from toksearch_d3d.sql import connect_d3drdb

with connect_d3drdb() as conn:              # the published snapshot
    df = pd.read_sql("SELECT TOP 10 shot, entered FROM shots ORDER BY shot", conn)
    print(conn.snapshot)                    # d3drdb_20261006T135944Z
```

Run it under `fdp run python script.py`, which supplies the token (§2).

```python
with connect_d3drdb(live=True) as conn:     # the live SQL Server, on-site only
    df = pd.read_sql("SELECT TOP 5 shot, entered FROM shots ORDER BY shot DESC", conn)
```

`live=True` needs the GA network and `~/D3DRDB.sybase_login`. Keyword overrides
(`db=`, `host=`, `port=`, `username=`, `password=`, `password_file=`) apply only
with `live=True`; passing one without it raises `TypeError`. Passing
`live=True` together with `snapshot=` raises `ValueError`.

**`TDSVER` matters only on the live path, and only for the deprecated
import.** `toksearch_d3d.sql.connect_d3drdb(live=True)` sets it for you. The
deprecated `toksearch.sql.mssql.connect_d3drdb` does not, so code still on
that import must `export TDSVER=7.0` or the connection fails. A snapshot has no
use for `TDSVER`.

The first published snapshot is `d3drdb_20261006T135944Z`: cut 2026-10-06,
shot ceiling 209,027, 67 tables (64 base tables and 3 materialized views),
8.0 million rows. Every snapshot id ends in the UTC time of its cut,
`YYYYMMDDTHHMMSSZ`. `conn.snapshot` is the id you read; `conn.manifest` is its
manifest (tables, row counts, the ceiling, what was excluded and why).

## 2. Three things you will hit first

**The shot ceiling.** A snapshot holds every shot up to the largest shot
number at the time of its cut, and none after. The newest shots are only in
`live=True`.

```python
with connect_d3drdb() as conn:
    print(conn.manifest["source"]["shot_ceiling"])   # 209027
```

Rows whose `shot` is NULL are kept. They are run-level rows, not shots (22,778
of them in `ENTRIES`), and the ceiling does not bound them.

**The token.** The snapshot is read from the FDP origin, which needs
`BEARER_TOKEN`. Run your script under `fdp run python script.py` (or
`fdp run jupyter lab`). A missing token raises before any request, naming
`fdp run` and `fdp login`. A token that expires mid-session is re-read from the
environment once; after that the error names `fdp login`.

**The notice.** The first snapshot connection in a process issues one
`SnapshotNotice` warning naming the snapshot and `live=True`. Once you have
read it, silence it:

```python
import warnings
from toksearch.sql.snapshot import SnapshotNotice
warnings.filterwarnings("ignore", category=SnapshotNotice)
```

pandas also warns that it "only supports SQLAlchemy connectable" objects. It
says the same of the live `pymssql` connection, and both work.

## 3. Pinning a run

A new snapshot is published by hand from time to time, and the default moves to
it. To keep a result reproducible, name the snapshot and record what you read:

```python
with connect_d3drdb(snapshot="d3drdb_20261006T135944Z") as conn:
    df = pd.read_sql(sql, conn)
    used = conn.snapshot          # store this beside your results
```

`FDP_SQL_SNAPSHOT_D3DRDB=d3drdb_20261006T135944Z` pins a whole process and its
workers. The first connection exports the id it resolved into that variable,
so forked, spawned, Ray and Spark workers read the same snapshot as the parent.
One snapshot per process: code naming one snapshot while the environment names
another raises `toksearch.sql.snapshot.SnapshotConflict`, not a choice of
one. An id that has no manifest is an error, never "the newest instead".

## 4. What T-SQL works

The snapshot rewrites T-SQL for DuckDB (via sqlglot), so existing queries run
unchanged:

- `SELECT TOP n` (becomes `LIMIT n`), `ISNULL`, `GETDATE()`, `DATEDIFF`
- `[bracketed]` identifiers and `dbo.` prefixes
- case-insensitive comparisons: `=` and `LIKE` ignore case, as on SQL Server;
  trailing blanks are trimmed from `char`/`varchar` values, so they compare as
  SQL Server would
- date strings against timestamps: `entered BETWEEN '2024-06-01' AND '2024-08-01'`
- parameters: `%s` with a sequence, `%(name)s` with a mapping

```python
pd.read_sql("SELECT shot, entered FROM shots WHERE shot = %s", conn, params=(194528,))
```

**Refused, with an error rather than wrong rows:** a `LIKE` pattern containing
`[`, which is a T-SQL character class. `WHERE name LIKE 'ECE[0-9]%'` raises a
`ValueError` that names `regexp_matches()`, the DuckDB equivalent:

```sql
SELECT Name FROM signal_names WHERE regexp_matches(Name, '^ECE[0-9]')
```

A query written this way runs only on the snapshot, not on `live=True`.

**Passed through:** anything sqlglot cannot parse goes to DuckDB unchanged. If
DuckDB rejects it too, the error carries sqlglot's message as a second line.

**Column names.** Result column names follow the query's spelling
(`SELECT shot` → `shot`), as on SQL Server; `SELECT *` returns the stored names
(`SHOT`), also as on SQL Server. Requires toksearch >= 2.18.2; earlier versions
return the stored names for every column, so `df["shot"]` raises `KeyError`
there. Which case each table stores is shown in §6.

## 5. What is not in a snapshot, and why

Excluded on purpose, by reason:

| reason | tables |
|---|---|
| people | `PERSONNEL`, `OPERATORS`, view `PEOPLE` |
| per-user application state | `PREFERENCES`, `ENTRY_DISPLAY_PREFS`, `ENTRY_DISPLAY_TEMPLATES`, `AOT_PRESETS`, `SAVES`, `SAVEDATA` |
| retired | `OLD___DB_DOC`, `OLD___IRTV_LabViewMDSPlusLog`, `OLD___legacy`, `OLD___TEST_ITPA_H` |
| size | `DAM`, `eqp`, `USAGE_LOG` |
| scratch copy | `disruption_warning_test` (a copy of `disruption_warning`) |

Skipped because they are broken at the source: the four views
`BIGNODE_ATLAS_EXPORT_STATS`, `BIGNODE_HIGHLOAD_STATS`, `BIGNODE_ONESIG_STATS`
and `BIGNODE_STATS` (`Invalid object name` on the live server too).

`EXPERIMENTS` is in neither list: the database login cannot see it, so it
cannot be dumped. It is not readable on `live=True` with the same login either.

Querying an excluded table says so. The error is a `SnapshotError` with a line
reading, for example, `PERSONNEL is excluded from snapshots of this database
(reason recorded in the manifest: 'people')`. The lists are also in
`conn.manifest["excluded"]` and `conn.manifest["skipped"]`.

Usernames stay in `SHOTS`, `RUNS` and `ENTRIES` (`USERNAME`, `CHIEF_OPERATOR`)
as opaque login strings; the tables that map them to people are the excluded
ones.

## 6. The tables

`conn.manifest["tables"]` lists all 67, with their kind and row count.
`TABLE_DOC` holds a one-line description of most tables
(`SELECT * FROM table_doc`). This section covers the ones you will actually use.

### `SHOTS` — the master shot list

One row per shot, and the starting point for "which shots exist and when".
Columns are upper case.

- `SHOT` — the shot number (primary key)
- `ENTERED` — when the shot was taken; use it for date ranges
- `RUN` — the run-day label (joins to `RUNS`)
- `BRIEF` — one-line description
- `SHOT_TYPE`, `PLASMA_SHOT` — a rough classification; prefer `SHOTS_TYPE`
- `CHIEF_OPERATOR`, `USERNAME`

### `SHOTS_TYPE` — clean shot classification

The reliable way to separate real plasma discharges from test pulses. Columns
are lower case: `shot`, `shot_type`, `source`. The values you want are
`'plasma'`, `'power supply test'`, `'calibration'`, `'data acquisition'`,
`'unknown test'` and `'undefined'`. The column also holds about 500 stray
values (times of day, NULL), so filter with `= 'plasma'` and never with
`<> 'undefined'`. Example 1 below is the standard plasma-shot query.

### `SUMMARIES` — per-shot physics scalars

The most useful physics table: one row per shot with about 80 derived 0-D
quantities, so you can filter and scatter shots without reading any
time-series data. Columns include `pulse_length` (s), `topology`, minor and
major radius (`a`, `r`), elongation `kappa`, triangularity (`delta_u`,
`delta_l`), `betanmax`, `btor`, beam power `pbeam`, ECH power `pech`, radiated
power `prad`, stored energy `wtotmax`, line density `nemax_co2` and
`nemax_thomson`, `temax_ece`, and the times at which peaks occur (`t_*`).
**Powers are in watts** (`pbeam > 5e6` is 5 MW). Columns are lower case.
Some scalar columns hold unphysical sentinel values (`betanmax` reaches
2,204,480 on shot 104268), so range-filter any column you sort or scatter on;
`betanmax < 10` is the usual cut.

### `DISRUPTIONS` — one row per disrupted shot

A curated disruption catalog: `shot`, disruption time `t_disrupt`, current `ip`,
`bt`, `wmhd`, halo currents (`i_halo_l`, `i_halo_u`), `cause`, a `vde` flag,
`flattop`, and more. Use it to find and label disruptions at the shot level. It
is not maintained every campaign: it covers shots 100,000 to 196,645 (through
June 2023). Columns are lower case. (`DISRUPTION`, singular, is an older,
different table of per-shot maxima.)

### `disruption_warning` — time-resolved disruption ML dataset

The disruption-warning database: **many rows per shot**, one per time slice,
with `time`, `time_until_disrupt` and a wide set of ML features (`beta_n`,
`li`, `q95`, `n_equal_1_mode_IRLM`, `radiated_fraction`, `ip_error`, `v_loop`,
…). Disruption-prediction work trains on it. It covers shots 156,199 to 177,061
(2014 to 2018), about 3.0 million rows. Columns are mostly lower case.

### `SIGNAL_NAMES` and `SIGNAL_INFO` — the data dictionary

A catalog of stored signals, the metadata behind MDSplus and PTDATA, so you can
find out what a pointname *is* without asking a DIII-D expert.

- `SIGNAL_NAMES`: `Name`, `Tree`, `Full_Path`, `Experiment`, `Group_Id`
- `SIGNAL_INFO`: per `Group_Id`, `Diagnostic`, `Description`, `Units`,
  `Contact`, `Example_Shot`

The view `signals` is the two joined (see Views, below).

### `RUNS` — run-day and experiment metadata

One row per run day: `RUN`, `BRIEF`, `MINIPROPOSAL` (for example
`'2024-12-06'`), `experiment_number`, `configuration`, `REFSHOT`. Join to
`SHOTS.RUN` to attach an experiment's purpose to its shots.

### `ENTRIES` — the electronic logbook

Free-text logbook entries keyed on `SHOT` and `RUN`, with a `TOPIC`, a `TEXT`
body, a `VOIDED` marker and attached `image*_id`. Useful for human context on a
shot. **Run-level entries have `SHOT IS NULL`**: 22,778 of them, most carrying
a `RUN` (2,869 have neither). Select a run day's with
`WHERE run = ... AND shot IS NULL`.

### Views

Three of d3drdb's views are materialized as tables in a snapshot:

- `signals` — `SIGNAL_NAMES` joined to `SIGNAL_INFO` on `Group_Id`: one row
  per signal with its tree, path, diagnostic, units and description. The
  quickest way to look up a pointname:

  ```sql
  SELECT Name, Tree, Diagnostic, Units, Description
  FROM signals
  WHERE Name = 'IP'
  ```
- `shotvalvegas` — `SHOT`, `valve`, `gas`: which gas each valve held on each
  shot.
- `preshot_summaries` — per shot, the pre-shot comment (`precomment`), `RUN`,
  `SHOT_TYPE` and miniproposal step (`mp_step`), beside a few scalars (`ip`,
  `pbeam`, `pech`, `btor`) and `a_*` columns. `a_ip` is mostly amps, but a few
  2013-era shots (152,775–153,042) store MA (values 0.8–1.25); check units
  before use.

### How they fit together

```
RUNS ──< SHOTS ──< ENTRIES            (run day → its shots → logbook notes;
          │                            run-level entries have SHOT IS NULL)
          │  └──── SHOTS_TYPE         (1:1 classification)
          │  └──── SUMMARIES          (1:1 physics scalars)
          │  └──< shotvalvegas        (one row per valve per shot)
          │  └──── DISRUPTIONS        (0..1 row per shot: disrupted shots)
          └──< disruption_warning     (many time slices per shot)

SIGNAL_INFO ──< SIGNAL_NAMES          (data dictionary, not shot-keyed;
                                       the view signals is the join)
```

### Example queries

Each runs inside the connection from §1:

```python
with connect_d3drdb() as conn:
    df = pd.read_sql(QUERY, conn)
```

**1. Plasma shots in a date window (the standard cohort).** A two-month window
is roughly 600–700 plasma shots.

```sql
SELECT s.shot, s.entered, s.brief
FROM shots s JOIN shots_type t ON s.shot = t.shot
WHERE t.shot_type = 'plasma'
  AND s.entered BETWEEN '2024-06-01' AND '2024-08-01'
ORDER BY s.shot
```

**2. The N most recent plasma shots** (in this snapshot; `live=True` for the
ones above the ceiling).

```sql
SELECT TOP 50 s.shot, s.entered
FROM shots s JOIN shots_type t ON s.shot = t.shot
WHERE t.shot_type = 'plasma'
ORDER BY s.shot DESC
```

**3. Physics-cohort selection without reading any waveforms.** Pull derived
scalars from `SUMMARIES` (here: high-βN, high-power, long shots):

```sql
SELECT su.shot, su.betanmax, su.pbeam, su.kappa, su.topology, su.pulse_length
FROM summaries su JOIN shots_type t ON su.shot = t.shot
WHERE t.shot_type = 'plasma'
  AND su.betanmax > 2.5
  AND su.betanmax < 10          -- drop sentinel values
  AND su.pbeam   > 5e6          -- watts: 5 MW
  AND su.pulse_length > 2.0     -- seconds
ORDER BY su.betanmax DESC
```

This is the right way to build a shot list for a TokSearch run: filter here,
then fetch time series only for the survivors.

**4. Attach physics scalars to a list of shots you already have.**

```python
shots = [194528, 194529, 194530]
placeholders = ",".join(str(int(s)) for s in shots)
df = pd.read_sql(
    f"SELECT shot, betanmax, btor, wtotmax, nemax_thomson "
    f"FROM summaries WHERE shot IN ({placeholders})",
    conn,
)
```

**5. Disrupted shots in a campaign (shot-level labels).** `DISRUPTIONS` ends at
June 2023, so pick a window it covers:

```sql
SELECT d.shot, d.t_disrupt, d.ip, d.cause, d.vde, d.flattop
FROM disruptions d JOIN shots s ON d.shot = s.shot
WHERE s.entered BETWEEN '2022-01-01' AND '2023-01-01'
ORDER BY d.shot
```

**6. Disruption rate over a date window.**

```sql
SELECT COUNT(DISTINCT d.shot) AS disrupted,
       COUNT(DISTINCT s.shot) AS total_plasma,
       100.0 * COUNT(DISTINCT d.shot) / COUNT(DISTINCT s.shot) AS pct
FROM shots s
JOIN shots_type t ON s.shot = t.shot AND t.shot_type = 'plasma'
LEFT JOIN disruptions d ON s.shot = d.shot
WHERE s.entered BETWEEN '2022-01-01' AND '2023-01-01'
```

**7. Time-resolved disruption-warning ML features for a shot** (many rows per
shot, one per time slice; shots 156,199–177,061; not every feature is
filled on every shot):

```sql
SELECT time, time_until_disrupt, beta_n, li, q95, n_equal_1_mode_IRLM,
       radiated_fraction, ip_error, v_loop
FROM disruption_warning
WHERE shot = 165454
ORDER BY time
```

**8. Look up what a signal or pointname is (the data dictionary).**

```sql
SELECT n.Name, n.Tree, n.Full_Path, i.Diagnostic, i.Units, i.Description
FROM signal_names n JOIN signal_info i ON n.Group_Id = i.Group_Id
WHERE n.Name LIKE '%ip%'
```

Or browse everything from one diagnostic through `signal_info.Diagnostic`, or
use the `signals` view (Views, above).

**9. Shots belonging to a particular experiment or miniproposal.**

```sql
SELECT s.shot, s.entered, r.brief, r.miniproposal, r.experiment_number
FROM shots s JOIN runs r ON s.run = r.run
WHERE r.miniproposal = '2024-12-06'
ORDER BY s.shot
```

**10. Read the logbook for a shot.**

```sql
SELECT entered, username, topic, text
FROM entries
WHERE shot = 194528 AND voided IS NULL
ORDER BY entered
```

**11. Read the run-level logbook entries for a run day** (`SHOT IS NULL`):

```sql
SELECT e.entered, e.topic, e.text
FROM entries e
WHERE e.shot IS NULL AND e.voided IS NULL
  AND e.run = (SELECT run FROM shots WHERE shot = 194528)
ORDER BY e.entered
```

**12. Shot count per run day (operations overview).**

```sql
SELECT s.run, MIN(s.entered) AS day, COUNT(*) AS n_shots,
       SUM(CASE WHEN t.shot_type = 'plasma' THEN 1 ELSE 0 END) AS n_plasma
FROM shots s LEFT JOIN shots_type t ON s.shot = t.shot
GROUP BY s.run
ORDER BY day DESC
```

**13. Which gas each valve held on a shot.**

```sql
SELECT shot, valve, gas
FROM shotvalvegas
WHERE shot = 194528 AND gas IS NOT NULL
ORDER BY valve
```

### Practical tips

- **Filter on `SUMMARIES` and `SHOTS_TYPE` first**, then fetch time series for
  the surviving shots with TokSearch (`PtDataSignal`, `MdsSignal`,
  `ImasSignal`). The database is for selection and labels; bulk waveform data
  lives in MDSplus and PTDATA, not here.
- Use `SHOTS.ENTERED` for date filtering.
- Everything joins on `shot`. When in doubt, that is the key.
- The many other tables (`ZIPFIT_*`, `Gas*`, `RWM`, `SWIM`, the
  diagnostic-specific ones) are special-purpose or legacy. Look them up in
  `TABLE_DOC` before relying on one.
