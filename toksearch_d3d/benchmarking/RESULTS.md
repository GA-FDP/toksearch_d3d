# FDP Origin Server Concurrency Benchmark Results

Date: 2026-02-19
Host: linux (4.18.0-553.70.1.el8_10.x86_64)

## Setup

- Signal access via Pelican/XRootD to `fdp-d3d-origin.nationalresearchplatform.org:8443`
- Backend: toksearch multiprocessing (joblib/loky)
- Environment configured via `fdp run`

## PtData: Single signal (`ip`), 200 shots (165920–166119)

| Workers | Wall(s) |   OK | Err | Shots/s | Avg(s) | Med(s) | p95(s) | Max(s) |
|--------:|--------:|-----:|----:|--------:|-------:|-------:|-------:|-------:|
|       1 |    32.9 |  200 |   0 |     6.1 |   0.16 |   0.17 |   0.22 |   0.38 |
|       2 |    14.0 |  200 |   0 |    14.3 |   0.11 |   0.10 |   0.13 |   0.72 |
|       4 |     9.4 |  200 |   0 |    21.2 |   0.11 |   0.10 |   0.12 |   1.16 |
|       8 |     7.3 |  200 |   0 |    27.5 |   0.11 |   0.09 |   0.30 |   0.74 |
|      16 |     6.2 |  200 |   0 |    32.4 |   0.14 |   0.10 |   0.55 |   0.58 |
|      32 |     4.9 |  200 |   0 |    41.1 |   0.19 |   0.15 |   0.52 |   0.57 |

## PtData: Single signal (`ip`), 500 shots (165920–166419)

| Workers | Wall(s) |   OK | Err | Shots/s | Avg(s) | Med(s) | p95(s) | Max(s) |
|--------:|--------:|-----:|----:|--------:|-------:|-------:|-------:|-------:|
|       1 |    70.2 |  500 |   0 |     7.1 |   0.14 |   0.14 |   0.20 |   0.45 |
|       8 |    10.9 |  500 |   0 |    46.0 |   0.10 |   0.09 |   0.11 |   1.54 |
|      16 |     8.1 |  500 |   0 |    61.7 |   0.11 |   0.10 |   0.14 |   0.75 |
|      32 |     5.5 |  500 |   0 |    91.1 |   0.20 |   0.17 |   0.37 |   0.87 |
|      64 |    15.9 |  500 |   0 |    31.4 |   0.36 |   0.25 |   1.12 |   2.34 |
|     128 |    14.8 |  500 |   0 |    33.8 |   0.53 |   0.54 |   1.00 |   1.53 |

## PtData: Single signal (`ip`), 10000 shots (165920–175919)

| Workers | Wall(s) |    OK | Err | Shots/s | Avg(s) | Med(s) | p95(s) | Max(s) |
|--------:|--------:|------:|----:|--------:|-------:|-------:|-------:|-------:|
|      16 |   110.8 | 9952  |  48 |    90.2 |   0.17 |   0.17 |   0.24 |   0.85 |
|      32 |    52.4 | 9952  |  48 |   190.7 |   0.16 |   0.15 |   0.26 |   1.79 |

48 errors are data gaps (shots without `ip` data), not concurrency failures.

## PtData: 18 signals (`pcf[1-9][a,b]`), 1000 shots (165920–166919)

| Workers | Wall(s) |  OK | Err | Shots/s | Avg(s) | Med(s) | p95(s) | Max(s) |
|--------:|--------:|----:|----:|--------:|-------:|-------:|-------:|-------:|
|      16 |    72.4 | 957 |  43 |    13.8 |   1.13 |   1.10 |   1.60 |   2.40 |
|      32 |    49.0 | 957 |  43 |    20.4 |   1.50 |   1.44 |   2.14 |   3.04 |

43 errors are data gaps. 18 signals × 32 workers = up to 576 concurrent fetches — no server errors.

## MDS: `\psirz` + `\ipmhd` (efit01), 200 shots (190000–190199)

| Workers | Wall(s) |  OK | Err | Shots/s | Avg(s) | Med(s) | p95(s) | Max(s) |
|--------:|--------:|----:|----:|--------:|-------:|-------:|-------:|-------:|
|       1 |    28.7 | 158 |  42 |     7.0 |   0.17 |   0.17 |   0.25 |   0.63 |
|       2 |    18.6 | 158 |  42 |    10.8 |   0.16 |   0.16 |   0.29 |   0.66 |
|       4 |    10.7 | 158 |  42 |    18.7 |   0.17 |   0.16 |   0.38 |   0.60 |
|       8 |     8.2 | 158 |  42 |    24.5 |   0.22 |   0.18 |   0.55 |   0.80 |
|      16 |     8.3 | 158 |  42 |    24.2 |   0.28 |   0.22 |   0.68 |   1.84 |
|      32 |     5.9 | 158 |  42 |    33.6 |   0.38 |   0.31 |   0.90 |   1.82 |

42 errors are TreeFOPENR (missing efit01 data for those shots), consistent across all worker counts.

## MDS: `\psirz` + `\ipmhd` (efit01), 1000 shots (190000–190999)

| Workers | Wall(s) |  OK | Err | Shots/s | Avg(s) | Med(s) | p95(s) | Max(s) |
|--------:|--------:|----:|----:|--------:|-------:|-------:|-------:|-------:|
|       8 |    26.4 | 863 | 137 |    37.8 |   0.20 |   0.18 |   0.42 |   1.28 |
|      16 |    20.0 | 863 | 137 |    49.9 |   0.27 |   0.21 |   0.61 |   1.53 |

Segfault in MDSplus `Tree.__del__` during GC at process exit (after results collected).

## Key Findings

### Server-side behavior
- **No concurrency-induced errors observed.** All errors are data gaps (missing shots/signals on the origin), consistent across serial and parallel runs.
- **Peak throughput ~190 shots/s** (single signal, 32 workers, 10000 shots).
- **Throughput scales well up to 32 workers**, then degrades at 64+ (500-shot test: 91 shots/s at 32 vs 31 shots/s at 64).
- **Per-shot latency increases with concurrency** (server-side queueing): avg goes from ~0.15s (serial) to ~0.5s (128 workers). The server throttles gracefully rather than failing.

### Client-side crashes (not server-related)
- **ptdata `set_env` segfault**: `ptdata._common.set_env()` does `os.environ.clear()` + `os.environ.update()` which is unsafe in forked worker processes. Crashes at high volume (10000 shots × 18 signals × 16 workers). Located in `ptdata/_common.py:30-31`.
- **MDSplus GC segfault**: `MDSplus.tree.Tree.__del__` calls `close()` on stale C pointers during garbage collection in forked loky workers. Triggers at ~10000 shots with MDS signals. Non-functional (results already collected before crash).

### Recommended concurrency
- **Sweet spot: 16–32 workers** for ptdata signals
- **8–16 workers** for MDS signals (more memory per shot, GC pressure)
- Beyond 32 workers, wall-clock time increases due to server-side queueing
