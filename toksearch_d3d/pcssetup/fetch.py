# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Rebuild a shot's ``.wa10`` setup file from PTDATA pointname ``PCSSETUP``.

The PCS writes its setup ``struct pfi42`` to PTDATA as one point at shot
start (d3d_pcs ``pcsshotfile_ptdata.c`` ``pfi42_write``): the five
variable-header sections go into the point's variable header and the
index records into its data. A ``.wa10`` is the same struct written to a
file (``setup_routines.c`` ``store_shotsetup``). So the file is rebuilt
from the point's variable header plus its raw data words; the data words
alone (what ``PtDataSignal('PCSSETUP', ical=0)`` returns) are only the
index records and cannot be decoded without the variable header.
"""

from __future__ import annotations

import numpy as np

from .wa10 import build_wa10

POINTNAME = "PCSSETUP"
_PREHEADER_BYTES = 32
_FIXED_HEADER_BYTES = 192


def _reader():
    from toksearch_d3d.signal.ptdata import PtDataReaderRegistry
    return PtDataReaderRegistry().reader()


def _ascii(reader, shot: int, header) -> bytes:
    """The ascii variable header as bytes.

    ptdata hands the section to Python as ``str`` (UTF-8 decoded). PCS
    setups are plain ASCII in practice, so encoding it back is exact; if
    the length does not round-trip, read the bytes from the raw point.
    """
    n = 2 * header.fixed_header.ascii_count
    try:
        b = header.variable_header.ascii.encode("utf-8")
        if len(b) == n:
            return b
    except UnicodeError:
        pass
    raw = reader.read_point_bytes(POINTNAME, int(shot))
    start = _PREHEADER_BYTES + _FIXED_HEADER_BYTES
    return bytes(raw[start:start + n])


def pcssetup_wa10_bytes(shot: int) -> bytes:
    """``shot``'s setup as ``.wa10`` bytes, rebuilt from PTDATA.

    Byte-identical to what the PCS tool ``pcssetup_to_wa10`` writes,
    except that the header keeps the shot number and archive time from
    the point (the PCS tool writes them as zero).
    """
    from toksearch_d3d import PtDataSignal

    reader = _reader()
    hdr = reader.read_header(POINTNAME, int(shot))
    fh, vh = hdr.fixed_header, hdr.variable_header
    nbits = int(fh.bits_per_element)
    raw = PtDataSignal(POINTNAME, ical=0, fetch_times=False,
                       fetch_units=False).fetch(int(shot))["data"]
    # Raw integer words; the PCS reads them unsigned (setup_routines.c 536-543).
    data = np.asarray(raw).astype(np.int64) & ((1 << nbits) - 1)
    if data.size * nbits != fh.data_word_count * 16:
        raise ValueError(
            f"PCSSETUP {shot}: fetched {data.size} {nbits}-bit data words; "
            f"the header says {fh.data_word_count} 16-bit words")
    ts = fh.timestamp
    return build_wa10(
        {"shot": int(fh.shot) or int(shot),
         "shtime": (ts.hour, ts.minute, ts.second),
         "shdate": (ts.month, ts.day, ts.year)},
        _ascii(reader, shot, hdr), np.asarray(vh.int16), np.asarray(vh.int32),
        np.asarray(vh.real32), np.asarray(vh.real64), data, nbdata=nbits)
