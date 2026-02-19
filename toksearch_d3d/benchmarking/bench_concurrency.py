"""Benchmark signal fetch concurrency against the FDP origin server.

Systematically varies the number of worker processes and measures
throughput, error rates, and per-shot fetch latency to characterize
server-side concurrency limits.

Supports two modes:
  ptdata — PtDataSignal (small scalar time-series, e.g. "ip")
  mds    — MdsSignal via Pelican (larger arrays, e.g. "\\psirz" from efit01)

Usage:
    fdp run python -m toksearch_d3d.benchmarking.bench_concurrency
    fdp run python -m toksearch_d3d.benchmarking.bench_concurrency --mode mds --shots 100
    fdp run python -m toksearch_d3d.benchmarking.bench_concurrency --workers 1,2,4,8,16 --shots 200
    fdp run python -m toksearch_d3d.benchmarking.bench_concurrency --output results.csv
"""

import argparse
import csv
import re
import statistics
import sys
import time

from toksearch import MdsSignal, Pipeline
from toksearch_d3d import PtDataSignal


def expand_signals(specs):
    """Expand bracket patterns in signal specs.

    Supports:
        [1-9]   → digits 1 through 9
        [a,b,c] → literal alternatives

    Examples:
        pcf[1-9]a      → pcf1a, pcf2a, ..., pcf9a
        pcf[1-9][a,b]  → pcf1a, pcf1b, pcf2a, pcf2b, ..., pcf9a, pcf9b
    """
    expanded = []
    for spec in specs:
        results = [spec]
        # Repeatedly expand the first bracket group until none remain
        changed = True
        while changed:
            changed = False
            new_results = []
            for s in results:
                m = re.search(r'\[([^\]]+)\]', s)
                if not m:
                    new_results.append(s)
                    continue
                changed = True
                inner = m.group(1)
                # Check for range pattern like 1-9
                range_match = re.fullmatch(r'(\d)-(\d)', inner)
                if range_match:
                    vals = [str(i) for i in range(int(range_match.group(1)),
                                                  int(range_match.group(2)) + 1)]
                else:
                    vals = [v.strip() for v in inner.split(",")]
                for v in vals:
                    new_results.append(s[:m.start()] + v + s[m.end():])
            results = new_results
        expanded.extend(results)
    return expanded


def make_signal(spec, mode):
    """Create a signal object from a spec string and mode."""
    if mode == "ptdata":
        return PtDataSignal(spec)
    else:
        # MDS mode: spec is "tree:signal" or just "signal" (default tree: efit01)
        if ":" in spec:
            tree, signal = spec.split(":", 1)
        else:
            tree, signal = "efit01", spec
        return MdsSignal(signal, tree, location=None)


def build_pipeline(shots, signal_specs, mode):
    """Build a pipeline that times each shot's fetch."""
    pipe = Pipeline(shots)

    @pipe.map
    def start_timer(rec):
        rec["_t0"] = time.time()

    for spec in signal_specs:
        label = spec.replace("\\", "").replace(":", "_")
        pipe.fetch(label, make_signal(spec, mode))

    @pipe.map
    def stop_timer(rec):
        rec["_elapsed"] = time.time() - rec["_t0"]
        rec["_ok"] = not bool(rec.errors)
        if rec.errors:
            rec["_error_msg"] = "; ".join(
                str(v) for v in rec.errors.values()
            )
        else:
            rec["_error_msg"] = ""

    pipe.keep(["_elapsed", "_ok", "_error_msg"])
    return pipe


def run_benchmark(shots, signal_specs, mode, num_workers):
    """Run a single benchmark pass and return per-shot results."""
    pipe = build_pipeline(shots, signal_specs, mode)

    t0 = time.time()
    if num_workers == 1:
        results = pipe.compute_serial()
    else:
        results = pipe.compute_multiprocessing(num_workers=num_workers)
    wall_time = time.time() - t0

    per_shot = []
    for rec in results:
        per_shot.append({
            "shot": rec.shot,
            "elapsed": rec.get("_elapsed", None),
            "ok": rec.get("_ok", False),
            "error_msg": rec.get("_error_msg", ""),
        })

    return wall_time, per_shot


def percentile(data, p):
    """Compute the p-th percentile of a sorted list."""
    if not data:
        return 0.0
    data = sorted(data)
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(data):
        return data[f]
    return data[f] + (k - f) * (data[c] - data[f])


def summarize(wall_time, per_shot):
    """Compute summary statistics from a benchmark run."""
    ok_times = [s["elapsed"] for s in per_shot if s["ok"] and s["elapsed"] is not None]
    n_ok = sum(1 for s in per_shot if s["ok"])
    n_err = len(per_shot) - n_ok

    errors = {}
    for s in per_shot:
        if not s["ok"] and s["error_msg"]:
            msg = s["error_msg"][:120]
            errors[msg] = errors.get(msg, 0) + 1

    return {
        "wall_time": wall_time,
        "n_ok": n_ok,
        "n_err": n_err,
        "shots_per_sec": len(per_shot) / wall_time if wall_time > 0 else 0,
        "avg": statistics.mean(ok_times) if ok_times else 0,
        "median": statistics.median(ok_times) if ok_times else 0,
        "p95": percentile(ok_times, 95),
        "max": max(ok_times) if ok_times else 0,
        "errors": errors,
    }


def print_table(rows):
    """Print a formatted results table."""
    header = f"{'Workers':>7} | {'Wall(s)':>7} | {'OK':>4} | {'Err':>4} | {'Shots/s':>7} | {'Avg(s)':>6} | {'Med(s)':>6} | {'p95(s)':>6} | {'Max(s)':>6}"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for r in rows:
        print(
            f"{r['workers']:>7} | {r['wall_time']:>7.1f} | {r['n_ok']:>4} | {r['n_err']:>4} | "
            f"{r['shots_per_sec']:>7.1f} | {r['avg']:>6.2f} | {r['median']:>6.2f} | "
            f"{r['p95']:>6.2f} | {r['max']:>6.2f}"
        )


def write_csv(path, rows):
    """Write results to a CSV file."""
    fields = ["workers", "wall_time", "n_ok", "n_err", "shots_per_sec",
              "avg", "median", "p95", "max"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark signal fetch concurrency against FDP origin"
    )
    parser.add_argument(
        "--mode", choices=["ptdata", "mds"], default="ptdata",
        help="Signal type: ptdata (default) or mds"
    )
    parser.add_argument(
        "--workers", default="1,2,4,8,16,32",
        help="Comma-separated worker counts to test (default: 1,2,4,8,16,32)"
    )
    parser.add_argument(
        "--shots", type=int, default=100,
        help="Number of shots to fetch per run (default: 100)"
    )
    parser.add_argument(
        "--start-shot", type=int, default=None,
        help="First shot number (default: 165920 for ptdata, 190000 for mds)"
    )
    parser.add_argument(
        "--signals", default=None,
        help="Comma-separated signals with optional bracket expansion "
             "(e.g. 'pcf[1-9][a,b]' expands to pcf1a,pcf1b,...,pcf9a,pcf9b). "
             "Default: 'ip' for ptdata, '\\psirz,\\ipmhd' for mds"
    )
    parser.add_argument(
        "--warmup", type=int, default=5,
        help="Number of warmup shots run serially before timing (default: 5)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Path for CSV output (optional)"
    )
    args = parser.parse_args()

    # Apply mode-specific defaults
    if args.start_shot is None:
        args.start_shot = 190000 if args.mode == "mds" else 165920
    if args.signals is None:
        args.signals = r"\psirz,\ipmhd" if args.mode == "mds" else "ip"

    worker_counts = [int(x) for x in args.workers.split(",")]
    # Split on commas not inside brackets
    raw_specs = [s.strip() for s in re.split(r',(?![^\[]*\])', args.signals)]
    signal_specs = expand_signals(raw_specs)
    shots = list(range(args.start_shot, args.start_shot + args.shots))

    print(f"=== FDP Concurrency Benchmark ({args.mode}) ===")
    print(f"Shots: {args.shots} ({shots[0]}-{shots[-1]})  Signals: {', '.join(signal_specs)}")
    print(f"Worker counts: {worker_counts}")
    print()

    # Warmup: run a few shots serially to prime caches
    if args.warmup > 0:
        warmup_shots = shots[:args.warmup]
        print(f"Warmup: {args.warmup} shots (serial)...", end=" ", flush=True)
        wt, _ = run_benchmark(warmup_shots, signal_specs, args.mode, num_workers=1)
        print(f"done ({wt:.1f}s)")
        print()

    rows = []
    for nw in worker_counts:
        print(f"Running with {nw} worker(s)...", end=" ", flush=True)
        wall_time, per_shot = run_benchmark(shots, signal_specs, args.mode, num_workers=nw)
        s = summarize(wall_time, per_shot)
        s["workers"] = nw
        rows.append(s)
        print(f"{wall_time:.1f}s  ({s['n_ok']} ok, {s['n_err']} err)")

        if s["errors"]:
            for msg, count in sorted(s["errors"].items(), key=lambda x: -x[1])[:3]:
                print(f"  [{count}x] {msg}")

    print()
    print_table(rows)

    if args.output:
        write_csv(args.output, rows)
        print(f"\nCSV written to {args.output}")


if __name__ == "__main__":
    main()
