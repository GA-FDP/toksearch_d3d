# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Decode the sections of a PCS setup file into a :class:`Setup`.

The PCS archives its setup by walking tables of ``struct field_def``
(d3d_pcs ``core/infra/setup_driver.c``): each table lists, in order, the
fields of one structure and where its children go. Scalars go to the
typed sections (strings to ascii, shorts to int16, and so on) and a
``struct indices`` record goes to the data section at each child
structure. ``unparcel_setup_data.c`` reads it back by walking the same
tables; this module is a line-for-line port of that walk, with the
tables written out below. Every table starts with a VERSION entry: the
archive stores the table version as one int16, and the reader picks the
matching table, so old setups decode with the tables of their time.

Parameter data (the per-phase "static data" blocks) is archived by
``pcs_forarchive`` (``core/infra/waveparams.c`` lines 176-489) in a
self-describing form: block name, flags and field descriptors (type,
count, offset) followed by the values. Nothing here depends on
algorithm definitions compiled into the PCS.
"""

from __future__ import annotations

import numpy as np

from .model import (Algorithm, Category, ParamBlock, ParamField, Phase,
                    PhaseWaveform, Sequence, Setup, WaveformDef)
from .wa10 import Wa10FormatError, Wa10Sections

# Field types (core/infra/setup_driver.h lines 136-160).
CHAR, SHORT, INT, FLOAT, DOUBLE, FLOATD = 1, 2, 3, 4, 5, 6
CATEGORY, PHASESEQ, SEQ_WAVEFORM, SEQ_WAVELIST = 11, 12, 13, 14
ALGORITHM, PHASE, PHASEALG, SUBSET = 16, 17, 18, 19
ALG_WAVEFORM, WAVE_WAVELIST, VERTEX, PARAMETER = 20, 21, 22, 23
FIRST_STRING, CHANGES = 24, 25

# Restore-side field_def tables (core/infra/setup_driver.c lines 113-386),
# keyed by table name then archived VERSION. Scalar entries carry the
# attribute name the value is stored under.
TABLES = {
    "install": {
        4: [(INT, "version"), (FLOATD, "hold_onetick"),
            (INT, "hold_onetick_fs"), (FLOATD, "hold_primary_start_time"),
            (INT, "hold_primary_start_time_fs"), (INT, "category_count"),
            (INT, "rtcpu_count"), (INT, "catalg_count"),
            (INT, "waveform_count"), (INT, "nchanges"),
            (CHAR, "release_identifier"), (CHANGES, None)],
        3: [(INT, "version"), (FLOATD, "hold_onetick"),
            (INT, "hold_onetick_fs"), (FLOATD, "hold_primary_start_time"),
            (INT, "hold_primary_start_time_fs"), (INT, "category_count"),
            (INT, "rtcpu_count"), (INT, "catalg_count"),
            (INT, "waveform_count"), (CHAR, "release_identifier")],
        2: [(FLOATD, "hold_onetick"), (INT, "hold_onetick_fs"),
            (FLOATD, "hold_primary_start_time"),
            (INT, "hold_primary_start_time_fs"), (INT, "category_count"),
            (INT, "rtcpu_count"), (INT, "catalg_count"),
            (INT, "waveform_count"), (CHAR, "release_identifier")],
        1: [(FLOATD, "hold_onetick"), (INT, "hold_onetick_fs"),
            (FLOATD, "hold_primary_start_time"),
            (INT, "hold_primary_start_time_fs"), (INT, "category_count"),
            (INT, "rtcpu_count"), (INT, "catalg_count"),
            (INT, "waveform_count")],
    },
    "global": {1: [(INT, "baseline_count"), (INT, "timetostop"),
                   (FLOAT, "maggain"), (CATEGORY, None)]},
    "category": {1: [(CHAR, "name"), (CHAR, "identifier"), (INT, "version"),
                     (PHASESEQ, None), (ALGORITHM, None), (PHASE, None)]},
    "phase": {
        2: [(INT, "number"), (CHAR, "name"), (INT, "entry_behavior"),
            (FLOAT, "anchor_time"), (INT, "access_control"),
            (PHASEALG, None), (WAVE_WAVELIST, None), (PARAMETER, None)],
        1: [(INT, "number"), (CHAR, "name"), (INT, "entry_behavior"),
            (PHASEALG, None), (WAVE_WAVELIST, None), (PARAMETER, None)],
    },
    "phaseseq": {1: [(CHAR, "name"), (SEQ_WAVEFORM, None),
                     (SEQ_WAVELIST, None)]},
    "seq_wavelist": {1: [(VERTEX, None)]},
    "vertex": {1: [(FLOATD, "x"), (FLOAT, "y")]},
    "phasealg": {1: [(CHAR, "identifier"), (INT, "version")]},
    "algorithm": {
        2: [(CHAR, "identifier"), (INT, "version"), (FIRST_STRING, "name"),
            (SUBSET, None), (ALG_WAVEFORM, None)],
        1: [(CHAR, "identifier"), (INT, "version"), (SUBSET, None),
            (ALG_WAVEFORM, None)],
    },
    "waveform": {1: [(CHAR, "name"), (CHAR, "description"), (INT, "subset")]},
    "wave_wavelist": {1: [(INT, "access_control"), (VERTEX, None)]},
}

# Parameter archive (core/infra/waveparams.c lines 227-228) and
# descriptor types (core/infra/descriptors.h lines 40-58).
ARCHIVE_FORMAT_VERSION = 19971
CHARTYPE, SHORTTYPE, INTTYPE, LONG32TYPE, FLOATTYPE = 1, 2, 3, 4, 5
DOUBLETYPE, LONGTYPE = 6, 7
DESCRIPTOR_TYPE_NAMES = {CHARTYPE: "char", SHORTTYPE: "short",
                         INTTYPE: "int", LONG32TYPE: "uint32",
                         FLOATTYPE: "float", DOUBLETYPE: "double",
                         LONGTYPE: "long"}


class _Cursor:
    """Read positions in the six sections, as ``struct indices``."""

    def __init__(self, s: Wa10Sections, strict: bool):
        self.s, self.strict = s, strict
        self.data = self.char = self.short = self.int = 0
        self.float = self.double = 0

    # scalars -----------------------------------------------------------
    def string(self) -> str:
        end = self.s.ascii.find(b"\0", self.char)
        if end < 0:
            raise Wa10FormatError(f"unterminated string at ascii offset {self.char}")
        text = self.s.ascii[self.char:end].decode("latin-1")
        self.char = end + 1
        return text

    def chars(self, n: int) -> bytes:
        out = self.s.ascii[self.char:self.char + n]
        self.char += n
        return out

    def short_(self) -> int:
        v = int(self.s.int16[self.short])
        self.short += 1
        return v

    def int_(self) -> int:
        v = int(self.s.int32[self.int])
        self.int += 1
        return v

    def float_(self) -> float:
        v = float(self.s.real32[self.float])
        self.float += 1
        return v

    def double_(self) -> float:
        v = float(self.s.real64[self.double])
        self.double += 1
        return v

    def take(self, kind: str, n: int) -> np.ndarray:
        arr = {"short": self.s.int16, "int": self.s.int32,
               "float": self.s.real32, "double": self.s.real64}[kind]
        start = getattr(self, kind)
        if start + n > arr.size:
            raise Wa10FormatError(f"{kind} section overrun at {start}+{n}")
        setattr(self, kind, start + n)
        return arr[start:start + n]

    # structure records ---------------------------------------------------
    def record(self, data_type: int, what: str) -> None:
        """Consume one index record; check it matches (check_indices)."""
        if self.data >= len(self.s.data):
            raise Wa10FormatError(f"data section ends before {what}")
        rec = self.s.data[self.data]
        if self.strict:
            want = (data_type, self.data, self.char, self.short, self.int,
                    self.float, self.double)
            if tuple(int(x) for x in rec) != want:
                raise Wa10FormatError(
                    f"index record {self.data} for {what} is {tuple(rec)}, "
                    f"expected {want}")
        self.data += 1


class _Decoder:
    """Port of read_buffers() in core/infra/unparcel_setup_data.c."""

    def __init__(self, sections: Wa10Sections, strict: bool = True):
        self.c = _Cursor(sections, strict)
        self.install: dict = {}
        self.change_history: list = []
        self.catalg: list = []  # categories first, then algorithms, as the PCS
        self.waveforms: list = []  # global waveform list
        self.first_wf: dict = {}  # catalg index -> first global waveform index
        self.categories: list = []

    # one field_def table -----------------------------------------------------
    def table(self, name: str) -> list:
        version = self.c.short_()
        if name == "install":
            self.install["table_version"] = version
        try:
            return TABLES[name][version]
        except KeyError:
            raise Wa10FormatError(
                f"{name} table version {version} is not one this reader "
                f"knows ({sorted(TABLES[name])})") from None

    def scalars(self, entries, out: dict):
        """Walk a table: read scalars into ``out``, yield structural kinds.

        Structural entries are interleaved with scalars in table order, so
        the caller handles each one as it is yielded, before the walk goes
        on to the next entry.
        """
        for kind, attr in entries:
            if kind in (CHAR, FIRST_STRING):
                out[attr] = self.c.string()
            elif kind == SHORT:
                out[attr] = self.c.short_()
            elif kind == INT:
                out[attr] = self.c.int_()
            elif kind == FLOAT:
                out[attr] = self.c.float_()
            elif kind in (FLOATD, DOUBLE):
                out[attr] = self.c.double_()
            else:
                yield kind

    # top level -------------------------------------------------------------
    def run(self) -> Setup:
        for kind in self.scalars(self.table("install"), self.install):
            if kind == CHANGES:
                self.changes()
        self.install.setdefault("version", 0)
        globals_ = {}
        for kind in self.scalars(self.table("global"), globals_):
            if kind == CATEGORY:
                self.read_categories()
        return Setup(install=dict(self.install), globals=globals_,
                     change_history=tuple(self.change_history),
                     categories=tuple(self.categories))

    def changes(self) -> None:
        n = self.c.int_()
        for i in range(n):
            self.c.record(CHANGES, f"change history entry {i}")
            self.change_history.append(self.c.string())

    def read_categories(self) -> None:
        ncat = self.install["category_count"]
        self.catalg = [None] * self.install["catalg_count"]
        self.alg_next = ncat  # global_algorithm_index
        for ci in range(ncat):
            self.c.record(CATEGORY, f"category {ci}")
            self.categories.append(self.category(ci))

    def category(self, ci: int) -> Category:
        f: dict = {}
        seqs, algs, phases = [], [], []
        self.cat_index = ci
        self.sub_alg = 1
        for kind in self.scalars(self.table("category"), f):
            if kind == PHASESEQ:
                for i in range(self.c.short_()):
                    self.c.record(PHASESEQ, f"category {ci} sequence {i}")
                    seqs.append(self.sequence())
            elif kind == ALGORITHM:
                for i in range(self.c.short_()):
                    self.c.record(ALGORITHM, f"category {ci} algorithm {i}")
                    algs.append(self.algorithm(f.get("name", "")))
            elif kind == PHASE:
                for i in range(self.c.short_()):
                    self.c.record(PHASE, f"category {ci} phase {i}")
                    phases.append(self.phase(f.get("name", "")))
        cat = Category(name=f["name"], identifier=f["identifier"],
                       version=f["version"], algorithms=tuple(algs),
                       phases=tuple(phases), sequences=tuple(seqs))
        self.catalg[ci] = cat
        return cat

    def waveform_def(self) -> dict:
        f: dict = {}
        for _ in self.scalars(self.table("waveform"), f):
            pass
        self.waveforms.append(f)
        return f

    def vertices(self, what: str) -> tuple:
        out = []
        for i in range(self.c.short_()):
            self.c.record(VERTEX, f"{what} vertex {i}")
            v: dict = {}
            for _ in self.scalars(self.table("vertex"), v):
                pass
            out.append((v["x"], v["y"]))
        return tuple(out)

    def sequence(self) -> Sequence:
        f: dict = {}
        wf, verts = None, ()
        for kind in self.scalars(self.table("phaseseq"), f):
            if kind == SEQ_WAVEFORM:
                self.c.record(SEQ_WAVEFORM, "sequence waveform")
                wf = self.waveform_def()
            elif kind == SEQ_WAVELIST:
                self.c.record(SEQ_WAVELIST, "sequence wavelist")
                for k2 in self.scalars(self.table("seq_wavelist"), {}):
                    if k2 == VERTEX:
                        verts = self.vertices(f"sequence {f.get('name')}")
        return Sequence(name=f["name"],
                        waveform=None if wf is None else _waveform_def(wf, ()),
                        vertices=verts)

    def algorithm(self, category: str) -> Algorithm:
        idx = self.alg_next
        self.alg_next += 1
        self.first_wf[idx] = len(self.waveforms)
        f: dict = {}
        subsets: tuple = ()
        wfs = []
        for kind in self.scalars(self.table("algorithm"), f):
            if kind == SUBSET:
                subsets = tuple(self.c.string() for _ in range(self.c.short_()))
            elif kind == ALG_WAVEFORM:
                for i in range(self.c.short_()):
                    self.c.record(ALG_WAVEFORM, f"algorithm {f.get('identifier')} waveform {i}")
                    wfs.append(self.waveform_def())
        alg = Algorithm(name=f.get("name", f["identifier"]),
                        identifier=f["identifier"], version=f["version"],
                        category=category, number=self.sub_alg,
                        subsets=subsets,
                        waveforms=tuple(_waveform_def(w, subsets) for w in wfs))
        self.sub_alg += 1
        self.catalg[idx] = alg
        return alg

    def find_alg(self, identifier: str, version: int) -> Algorithm:
        """r_get_cat_alg: the last cat_alg with this identifier and version."""
        for item in reversed(self.catalg):
            if (item is not None and item.identifier == identifier
                    and item.version == version):
                return item
        raise Wa10FormatError(
            f"phase algorithm {identifier!r} version {version} is not "
            "among the archived algorithms")

    def phase(self, category: str) -> Phase:
        f: dict = {}
        alg = None
        wavelist: tuple = ()
        params: tuple = ()
        for kind in self.scalars(self.table("phase"), f):
            if kind == PHASEALG:
                self.c.record(PHASEALG, f"phase {f.get('name')} algorithm")
                pa: dict = {}
                for _ in self.scalars(self.table("phasealg"), pa):
                    pass
                alg = self.find_alg(pa["identifier"], pa["version"])
            elif kind == WAVE_WAVELIST:
                entries = []
                for i in range(self.c.short_()):
                    self.c.record(WAVE_WAVELIST, f"phase {f.get('name')} waveform {i}")
                    w: dict = {}
                    verts: tuple = ()
                    for k2 in self.scalars(self.table("wave_wavelist"), w):
                        if k2 == VERTEX:
                            verts = self.vertices(f"phase {f.get('name')} waveform {i}")
                    entries.append((w.get("access_control", 0), verts))
                wavelist = tuple(entries)
            elif kind == PARAMETER:
                self.c.record(PARAMETER, f"phase {f.get('name')} parameters")
                params = self.parameters()
        wfdefs = alg.waveforms if alg is not None else ()
        if len(wavelist) != len(wfdefs):
            raise Wa10FormatError(
                f"phase {category}|{f.get('name')} has {len(wavelist)} "
                f"waveforms; its algorithm defines {len(wfdefs)}")
        waveforms = tuple(
            PhaseWaveform(definition=d, access_control=ac, vertices=v)
            for d, (ac, v) in zip(wfdefs, wavelist))
        return Phase(category=category, name=f["name"], number=f["number"],
                     entry_behavior=f["entry_behavior"],
                     anchor_time=f.get("anchor_time", 0.0),
                     access_control=f.get("access_control", 0),
                     algorithm=alg, waveforms=waveforms,
                     param_blocks=params)

    # parameter data ------------------------------------------------------
    def parameters(self) -> tuple:
        c = self.c
        if self.install["version"] < 3:
            counts = [c.short_() & 0xFFFF if i == 0 else c.short_()
                      for i in range(5)]
            # unparcel_setup_data.c lines 763-778: float counts > 32k were
            # stored truncated; recover them from the next index record.
            if counts[3] > 0 and c.data < len(c.s.data):
                nxt = int(c.s.data[c.data][5])
                if nxt != 0:
                    diff = nxt - c.float - counts[3]
                    if diff < 0:
                        diff &= 0xFFFF
                    if diff == 65536:
                        counts[3] += diff
        else:
            counts = [c.int_() for _ in range(5)]
        nchar, nshort, nint, nfloat, ndouble = counts
        chars = c.chars(nchar)
        shorts = c.take("short", nshort)
        ints = c.take("int", nint)
        floats = c.take("float", nfloat)
        doubles = c.take("double", ndouble)
        if nint == 0:
            return ()
        return _param_blocks(chars, shorts, ints, floats, doubles)


def _waveform_def(f: dict, subsets: tuple) -> WaveformDef:
    sub = f["subset"]
    name = subsets[sub - 1] if 1 <= sub <= len(subsets) else None
    return WaveformDef(name=f["name"], description=f["description"],
                       subset=sub, subset_name=name)


def _param_blocks(chars: bytes, shorts, ints, floats, doubles) -> tuple:
    """Decode one phase's pcs_forarchive arrays into ParamBlocks."""
    if int(ints[0]) != ARCHIVE_FORMAT_VERSION:
        # Setups from before pcs_forarchive (shots before ~2000) used
        # per-algorithm archive layouts; keep their arrays undecoded.
        raw = [ParamField(type=t, size=len(v), offset=0, value=v)
               for t, v in (("char", chars), ("short", shorts.copy()),
                            ("int", ints.copy()), ("float", floats.copy()),
                            ("double", doubles.copy()))]
        return (ParamBlock(name=f"(archive format {int(ints[0])})",
                           data_size=0, flags=0, insert_order=0, mem_align=0,
                           fields=tuple(raw)),)
    nblocks = int(ints[1])
    ii, ci, si, fi, di = 2, 0, 0, 0, 0
    blocks = []
    for _ in range(nblocks):
        namesize, data_size, flags, insert_order, mem_align, ndesc = (
            int(x) for x in ints[ii:ii + 6])
        ii += 6
        descs = ints[ii:ii + 3 * ndesc].reshape(-1, 3)
        ii += 3 * ndesc
        name = chars[ci:ci + namesize].split(b"\0", 1)[0].decode("latin-1")
        ci += namesize
        fields = []
        for dtype, size, offset in (tuple(int(x) for x in d) for d in descs):
            if dtype == FLOATTYPE:
                val, fi = floats[fi:fi + size].copy(), fi + size
            elif dtype == DOUBLETYPE:
                val, di = doubles[di:di + size].copy(), di + size
            elif dtype == SHORTTYPE:
                val, si = shorts[si:si + size].copy(), si + size
            elif dtype in (INTTYPE, LONGTYPE):
                val, ii = ints[ii:ii + size].copy(), ii + size
            elif dtype == LONG32TYPE:
                val, ii = ints[ii:ii + size].view(np.uint32).copy(), ii + size
            elif dtype == CHARTYPE:
                val, ci = chars[ci:ci + size], ci + size
            else:
                raise Wa10FormatError(
                    f"parameter block {name!r}: descriptor type {dtype} "
                    "should not survive pcs_forarchive's unrolling")
            fields.append(ParamField(type=DESCRIPTOR_TYPE_NAMES[dtype],
                                     size=size, offset=offset, value=val))
        blocks.append(ParamBlock(name=name, data_size=data_size, flags=flags,
                                 insert_order=insert_order,
                                 mem_align=mem_align, fields=tuple(fields)))
    if ii != len(ints):
        raise Wa10FormatError(
            f"parameter archive: {len(ints) - ii} int words left over")
    return tuple(blocks)


def decode(sections: Wa10Sections, strict: bool = True) -> Setup:
    """Decode split sections into a Setup.

    ``strict`` checks every index record against the read positions, as
    the PCS does; a mismatch raises :class:`Wa10FormatError`.
    """
    setup = _Decoder(sections, strict).run()
    object.__setattr__(setup, "header", sections.header)
    return setup
