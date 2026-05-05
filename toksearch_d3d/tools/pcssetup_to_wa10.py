# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
pcssetup-to-wa10: extract the PCSSETUP pointname for a shot and write
the raw bytes to a .wa10 file -- the inverse of the PCS-side write that
stores the wa10 file in PTDATA at shot start.

Working assumption: PCSSETUP's data payload is byte-for-byte identical
to the original wa10 file. See
docs/superpowers/specs/2026-05-04-pcssetup-to-wa10-design.md.
"""

from toksearch_d3d import PtDataSignal


def pcssetup_bytes(shot: int) -> bytes:
    """Return the raw PCSSETUP bytes for ``shot`` as a single ``bytes`` blob.

    The returned bytes are assumed to be the original wa10 file contents
    written into PTDATA by PCS at shot start.
    """
    result = PtDataSignal("PCSSETUP").fetch(int(shot))
    return result["data"].tobytes()


import argparse
import sys
from pathlib import Path

from ptdata import PtDataError


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``pcssetup-to-wa10``.

    Returns the int exit code so tests can drive it without ``sys.exit``.
    """
    parser = argparse.ArgumentParser(
        prog="pcssetup-to-wa10",
        description=(
            "Fetch the PCSSETUP pointname for a shot and write the raw "
            "bytes to a .wa10 file. Run under `fdp run`."
        ),
    )
    parser.add_argument("shot", type=int, help="shot number")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="output path (default: <shot>.wa10 in cwd)",
    )
    args = parser.parse_args(argv)

    out_path = args.output or Path(f"{args.shot}.wa10")

    try:
        data = pcssetup_bytes(args.shot)
    except PtDataError as e:
        print(f"error: PCSSETUP fetch failed for shot {args.shot}: {e}",
              file=sys.stderr)
        return 1

    try:
        out_path.write_bytes(data)
    except OSError as e:
        print(f"error: could not write {out_path}: {e}", file=sys.stderr)
        return 1

    print(f"wrote {len(data)} bytes to {out_path}")
    return 0
