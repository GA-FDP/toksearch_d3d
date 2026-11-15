# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
pcssetup-to-wa10: rebuild a shot's .wa10 setup file from the PCSSETUP
pointname -- the inverse of the PCS-side write that stores the setup in
PTDATA at shot start.

The 2026-05-04 design assumed PCSSETUP's data payload is the whole file.
It is not: the data words are only the setup's index records; the
values live in the point's variable header. The file is rebuilt from
both (toksearch_d3d.pcssetup.fetch); its body is byte-identical to what
the PCS's own pcssetup_to_wa10 writes. See
docs/superpowers/specs/2026-11-15-pcssetup-reader-design.md.
"""

import argparse
import sys
from pathlib import Path

from ptdata import PtDataError
from toksearch_d3d import PtDataSignal


def pcssetup_bytes(shot: int) -> bytes:
    """Return PCSSETUP's raw data words for ``shot`` as one ``bytes`` blob.

    Fetches in raw mode (``ical=0``) with no time or units fetches, so the
    returned bytes are the integer payload PTDATA stores (native int32).
    With default ``ical=1`` (Full calibration) the engine would return
    float64 calibrated values (8 bytes/sample, sign-flipped).

    These are only the setup's index records, not a ``.wa10`` file; use
    :func:`toksearch_d3d.pcssetup.pcssetup_wa10_bytes` for the file.
    """
    result = PtDataSignal(
        "PCSSETUP", ical=0, fetch_times=False, fetch_units=False
    ).fetch(int(shot))
    return result["data"].tobytes()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``pcssetup-to-wa10``.

    Returns the int exit code so tests can drive it without ``sys.exit``.
    """
    parser = argparse.ArgumentParser(
        prog="pcssetup-to-wa10",
        description=(
            "Rebuild a shot's .wa10 PCS setup file from its PCSSETUP "
            "pointname. Run under `fdp run`."
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

    from toksearch_d3d.pcssetup import pcssetup_wa10_bytes

    try:
        data = pcssetup_wa10_bytes(args.shot)
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
