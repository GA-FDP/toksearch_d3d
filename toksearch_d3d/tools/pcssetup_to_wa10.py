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
