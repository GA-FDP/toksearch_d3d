"""Minimal reproducer for MDSplus _TreeClose segfault with Pelican/XRootD.

The crash is heap corruption in close_top_tree() (libTreeShr) when XRootD
background threads are still active while tree structures are being freed.

This uses loky (same backend as toksearch) to match the real crash scenario.
Plain mp.Pool with fork hits a different bug (fork-after-threading).

Run with:  fdp run python toksearch_d3d/benchmarking/repro_mds_segfault.py
"""

import argparse
import faulthandler
import sys

faulthandler.enable()


def worker(args):
    import MDSplus as mds
    shot, treename, expressions, do_close = args
    try:
        tree = mds.Tree(treename, shot, mode="READONLY")
        for expr in expressions:
            node = tree.getNode(expr)
            data = node.data()
        if do_close:
            tree.close()
        else:
            tree.public = True
        return ("ok", shot)
    except Exception as e:
        return ("err", shot, type(e).__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--start-shot", type=int, default=190000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--tree", default="efit01")
    parser.add_argument("--expression", action="append", dest="expressions",
                        default=None, metavar="EXPR",
                        help="MDSplus expression to fetch (may be repeated)")
    parser.add_argument("--no-close", action="store_true",
                        help="Skip tree.close() to confirm crash is in close path")
    parser.add_argument("--serial", action="store_true",
                        help="Run in single process (no multiprocessing)")
    parser.add_argument("--backend", choices=["loky", "spawn", "fork"],
                        default="loky",
                        help="Multiprocessing backend (default: loky, same as toksearch)")
    args = parser.parse_args()

    shots = list(range(args.start_shot, args.start_shot + args.shots))
    do_close = not args.no_close
    tasks = [(s, args.tree, args.expression, do_close) for s in shots]

    mode = "serial" if args.serial else f"{args.workers} workers ({args.backend})"
    print(f"{args.shots} shots, {mode}, tree={args.tree}, "
          f"expr={args.expression}, close={do_close}", flush=True)

    ok = err = 0

    if args.serial:
        for t in tasks:
            result = worker(t)
            ok += result[0] == "ok"
            err += result[0] != "ok"
            if (ok + err) % 100 == 0:
                print(f"  {ok+err}/{args.shots}  ok={ok} err={err}", flush=True)

    elif args.backend == "loky":
        from joblib import Parallel, delayed
        results = Parallel(n_jobs=args.workers, backend="loky", verbose=0)(
            delayed(worker)(t) for t in tasks
        )
        for result in results:
            ok += result[0] == "ok"
            err += result[0] != "ok"

    else:
        import multiprocessing as mp
        ctx = mp.get_context(args.backend)
        pool = ctx.Pool(args.workers)
        try:
            async_result = pool.map_async(worker, tasks, chunksize=4)
            results = async_result.get(timeout=300)
            for result in results:
                ok += result[0] == "ok"
                err += result[0] != "ok"
        except mp.TimeoutError:
            print("TIMEOUT", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
        finally:
            pool.terminate()
            pool.join()

    print(f"Done: {ok} ok, {err} errors")


if __name__ == "__main__":
    main()
