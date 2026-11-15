# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Byte layout of a DIII-D PCS setup file (``.wa10``).

A ``.wa10`` file is the on-disk form of the PCS ``struct pfi42``: a
192-byte fixed header, five variable-header sections (ascii, int16,
int32, real32, real64) and a data section, all big-endian. The PCS
writes it in ``store_shotsetup`` and reads it back in
``read_shotsetup_setupfile`` (d3d_pcs ``core/infra/setup_routines.c``
lines 115-377 and 386-548). The same ``pfi42`` is what the PCS stores
in PTDATA as pointname ``PCSSETUP`` at shot start.

This module only splits the file into its sections. The meaning of the
sections (categories, phases, waveforms, parameters) is decoded in
:mod:`toksearch_d3d.pcssetup.decode`. See the format note in
``docs/superpowers/specs/2026-11-15-pcssetup-reader-design.md``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from os import PathLike
from typing import Union

import numpy as np

FIXED_HEADER_BYTES = 192  # n42_nwpfi * 2 (core/infra/pfi.h)
PFI = 42

# struct pfi42 without its trailing pointer fields (core/infra/pfi.h).
_HEADER_FORMAT = ">3i4s4s12s3i3ii24s4si4f4i4si10i5i"
assert struct.calcsize(_HEADER_FORMAT) == FIXED_HEADER_BYTES


class Wa10FormatError(ValueError):
    """The bytes are not a PCS setup file this reader understands."""


@dataclass(frozen=True)
class FixedHeader:
    """The ``pfi42`` fixed header. Word counts are in 16-bit words."""

    pfi: int
    nwhead: int
    shot: int
    expname: str
    phasname: str
    ptname: str
    shtime: tuple
    shdate: tuple
    pttype: int
    ptdesc: str
    engunits: str
    nrev: int
    stime1: float
    dtime1: float
    rcg: float
    inhnum: float
    zoff: int
    dfi: int
    nwdata: int
    nbdata: int
    dtype: str
    compalg: int
    nwascii: int
    nwint16: int
    nwint32: int
    nwreal32: int
    nwreal64: int


@dataclass(frozen=True)
class Wa10Sections:
    """A setup file split into typed arrays (native byte order).

    ``data`` holds the index records: one ``struct indices`` (seven
    uint32) per structure the PCS archived, used to check the decode
    stays in step (core/infra/setup_driver.h lines 162-189).
    """

    header: FixedHeader
    ascii: bytes
    int16: np.ndarray
    int32: np.ndarray
    real32: np.ndarray
    real64: np.ndarray
    data: np.ndarray  # uint32, shape (n, 7)
    data_tail: tuple = ()  # words after the last whole record (padding)


def _text(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin-1").rstrip()


def parse_header(raw: bytes) -> FixedHeader:
    if len(raw) < FIXED_HEADER_BYTES:
        raise Wa10FormatError(
            f"{len(raw)} bytes is shorter than the {FIXED_HEADER_BYTES}-byte "
            "pfi42 header")
    f = struct.unpack(_HEADER_FORMAT, raw[:FIXED_HEADER_BYTES])
    if f[0] != PFI:
        hint = ""
        if struct.unpack("<i", raw[:4])[0] == PFI:
            hint = " (it looks little-endian; setup files are big-endian)"
        raise Wa10FormatError(f"point format index is {f[0]}, not {PFI}{hint}")
    return FixedHeader(
        pfi=f[0], nwhead=f[1], shot=f[2], expname=_text(f[3]),
        phasname=_text(f[4]), ptname=_text(f[5]), shtime=tuple(f[6:9]),
        shdate=tuple(f[9:12]), pttype=f[12], ptdesc=_text(f[13]),
        engunits=_text(f[14]), nrev=f[15], stime1=f[16], dtime1=f[17],
        rcg=f[18], inhnum=f[19], zoff=f[20], dfi=f[21], nwdata=f[22],
        nbdata=f[23], dtype=_text(f[24]), compalg=f[25], nwascii=f[36],
        nwint16=f[37], nwint32=f[38], nwreal32=f[39], nwreal64=f[40])


def split_sections(raw: bytes) -> Wa10Sections:
    """Split setup-file bytes into header, variable-header arrays and data."""
    h = parse_header(raw)
    counts = (h.nwascii, h.nwint16, h.nwint32, h.nwreal32, h.nwreal64, h.nwdata)
    if min(counts) < 0:
        raise Wa10FormatError(f"negative section word count in {counts}")
    if h.nbdata not in (16, 32):
        raise Wa10FormatError(f"bits per data element is {h.nbdata}, not 16 or 32")
    need = FIXED_HEADER_BYTES + 2 * sum(counts)
    if len(raw) < need:
        raise Wa10FormatError(
            f"file has {len(raw)} bytes; its header says {need}")

    off = FIXED_HEADER_BYTES

    def take(dtype: str, nwords: int) -> np.ndarray:
        nonlocal off
        nbytes = 2 * nwords
        size = np.dtype(dtype).itemsize
        arr = np.frombuffer(raw, dtype, nbytes // size, off)
        off += nbytes
        return arr.astype(arr.dtype.newbyteorder("="))

    ascii_ = bytes(raw[off:off + 2 * h.nwascii])
    off += 2 * h.nwascii
    int16 = take(">i2", h.nwint16)
    int32 = take(">i4", h.nwint32)
    real32 = take(">f4", h.nwreal32)
    real64 = take(">f8", h.nwreal64)
    # Old setups stored 16-bit data words; read_shotsetup_setupfile widens
    # them to 32 bits (setup_routines.c lines 536-543).
    data = take(">u4" if h.nbdata == 32 else ">u2", h.nwdata).astype(np.uint32)
    # Old 16-bit setups pad the data section to an even byte count of
    # 32-bit words, leaving a word past the last 7-word record.
    tail = data.size % 7
    return Wa10Sections(header=h, ascii=ascii_, int16=int16, int32=int32,
                        real32=real32, real64=real64,
                        data=data[:data.size - tail].reshape(-1, 7),
                        data_tail=tuple(int(x) for x in data[data.size - tail:]))


def load_bytes(source: Union[bytes, bytearray, memoryview, str, PathLike]) -> bytes:
    """Return the bytes of ``source``: a bytes-like object or a file path."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    with open(source, "rb") as f:
        return f.read()


def build_wa10(header: dict, ascii_: bytes, int16, int32, real32, real64,
               data, nbdata: int = 32) -> bytes:
    """Assemble setup-file bytes the way ``store_shotsetup`` lays them out.

    ``header`` supplies the fixed-header fields that are not derived from
    the sections (shot, shtime, shdate; the rest take store_shotsetup's
    constants). Used to rebuild a ``.wa10`` from the ``PCSSETUP`` point.
    """
    int16 = np.asarray(int16, ">i2")
    int32 = np.asarray(int32, ">i4")
    real32 = np.asarray(real32, ">f4")
    real64 = np.asarray(real64, ">f8")
    data = np.asarray(data, ">u4" if nbdata == 32 else ">u2")
    if len(ascii_) % 2:
        raise ValueError("ascii section must be a whole number of 16-bit words")
    nw = [len(ascii_) // 2, int16.nbytes // 2, int32.nbytes // 2,
          real32.nbytes // 2, real64.nbytes // 2]
    nwdata = data.nbytes // 2
    nwhead = sum(nw) + FIXED_HEADER_BYTES // 2

    def field(s: str, n: int) -> bytes:
        return s.encode("latin-1")[:n].ljust(n, b" " if s else b"\0")

    fixed = struct.pack(
        _HEADER_FORMAT, PFI, nwhead, int(header.get("shot", 0)),
        field("PCS ", 4), field("PASY", 4),
        field(header.get("ptname", "PCSSETUP"), 12),
        *tuple(header.get("shtime", (0, 0, 0))),
        *tuple(header.get("shdate", (0, 0, 0))),
        7, field("Plasma Control System   ", 24), field("none", 4), 0,
        0.0, 0.001, 1.0, 1.0, 0, 2205, nwdata, nbdata, field("IN  ", 4), 0,
        *([0] * 10), *nw)
    return b"".join([fixed, bytes(ascii_), int16.tobytes(), int32.tobytes(),
                     real32.tobytes(), real64.tobytes(), data.tobytes()])
