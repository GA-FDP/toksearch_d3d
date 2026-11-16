# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Write small synthetic PCS setup files for the pcssetup reader tests.

Mirrors the PCS archive order (d3d_pcs parcel_setup_data.c driven by the
field_def tables in setup_driver.c): every structure starts with its
table VERSION as one int16, and an index record goes to the data section
just before each child structure.
"""

from __future__ import annotations

import numpy as np

from toksearch_d3d.pcssetup.wa10 import build_wa10
from toksearch_d3d.pcssetup import decode as D

TYPES = {"char": D.CHARTYPE, "short": D.SHORTTYPE, "int": D.INTTYPE,
         "uint32": D.LONG32TYPE, "float": D.FLOATTYPE, "double": D.DOUBLETYPE}


class Writer:
    def __init__(self):
        self.ascii = bytearray()
        self.i16, self.i32, self.f32, self.f64, self.data = [], [], [], [], []

    # scalars ---------------------------------------------------------------
    def s(self, text):
        self.ascii += text.encode("latin-1") + b"\0"

    def h(self, v):
        self.i16.append(v)

    def i(self, v):
        self.i32.append(v)

    def f(self, v):
        self.f32.append(v)

    def d(self, v):
        self.f64.append(v)

    def rec(self, kind):
        self.data.append((kind, len(self.data), len(self.ascii), len(self.i16),
                          len(self.i32), len(self.f32), len(self.f64)))

    # structures --------------------------------------------------------------
    def vertices(self, verts):
        self.h(len(verts))
        for x, y in verts:
            self.rec(D.VERTEX)
            self.h(1)          # vertex table version
            self.d(x)          # FLOATD
            self.f(y)

    def waveform(self, name, desc, subset):
        self.h(1)
        self.s(name)
        self.s(desc)
        self.i(subset)

    def params(self, blocks, raw=None):
        """blocks: [(name, flags, [(type, values), ...]), ...] in pcs_forarchive form."""
        if raw is not None:
            chars, shorts, ints, floats, doubles = raw
        else:
            chars, shorts, floats, doubles = bytearray(), [], [], []
            ints = [D.ARCHIVE_FORMAT_VERSION, len(blocks)] if blocks else []
            for name, flags, fields in blocks:
                ints += [len(name) + 1, 0, flags, 0, 4, len(fields)]
                for t, vals in fields:
                    n = len(vals) if t != "char" else len(vals)
                    ints += [TYPES[t], n, 0]
                chars += name.encode() + b"\0"
                for t, vals in fields:
                    if t == "char":
                        chars += vals
                    elif t == "short":
                        shorts += list(vals)
                    elif t in ("int", "uint32"):
                        ints += [int(v) if t == "int" else
                                 int(np.uint32(v).view(np.int32)) for v in vals]
                    elif t == "float":
                        floats += list(vals)
                    else:
                        doubles += list(vals)
        for v in (len(chars), len(shorts), len(ints), len(floats), len(doubles)):
            self.i(v)
        self.ascii += bytes(chars)
        self.i16 += list(shorts)
        self.i32 += list(ints)
        self.f32 += list(floats)
        self.f64 += list(doubles)

    def category(self, cat):
        self.h(1)
        self.s(cat["name"])
        self.s(cat.get("identifier", cat["name"].lower()))
        self.i(1)
        seqs = cat.get("sequences", [])
        self.h(len(seqs))
        for name, verts in seqs:
            self.rec(D.PHASESEQ)
            self.h(1)
            self.s(name)
            self.rec(D.SEQ_WAVEFORM)
            self.waveform(name, "phase sequence", 1)
            self.rec(D.SEQ_WAVELIST)
            self.h(1)
            self.vertices(verts)
        algs = cat["algorithms"]
        self.h(len(algs))
        for a in algs:
            self.rec(D.ALGORITHM)
            self.h(2)
            self.s(a["identifier"])
            self.i(a.get("version", 1))
            self.s(a["name"].split(",")[0])  # FIRST_STRING: archived up to a comma
            self.h(len(a["subsets"]))
            for sub in a["subsets"]:
                self.s(sub)
            self.h(len(a["waveforms"]))
            for name, desc, subset in a["waveforms"]:
                self.rec(D.ALG_WAVEFORM)
                self.waveform(name, desc, subset)
        phases = cat["phases"]
        self.h(len(phases))
        for n, p in enumerate(phases, 1):
            alg = next(a for a in algs if a["identifier"] == p["alg"])
            self.rec(D.PHASE)
            self.h(2)
            self.i(n)
            self.s(p["name"])
            self.i(p.get("entry", 3))
            self.f(p.get("anchor", 0.0))
            self.i(0)
            self.rec(D.PHASEALG)
            self.h(1)
            self.s(alg["identifier"])
            self.i(alg.get("version", 1))
            wl = p.get("vertices", {})
            self.h(len(alg["waveforms"]))
            for name, _, _ in alg["waveforms"]:
                self.rec(D.WAVE_WAVELIST)
                self.h(1)
                self.i(0)
                self.vertices(wl.get(name, [(0.0, 0.0)]))
            self.rec(D.PARAMETER)
            self.params(p.get("params", []), p.get("raw_params"))

    def setup(self, categories, changes=("created",)):
        ncatalg = len(categories) + sum(len(c["algorithms"]) for c in categories)
        nwf = sum(len(a["waveforms"]) for c in categories for a in c["algorithms"]) + \
            sum(len(c.get("sequences", [])) for c in categories)
        self.h(4)                     # install table version
        self.i(4)                     # archive_version
        self.d(5e-5)
        self.i(50)
        self.d(-9.0)
        self.i(1000000)
        self.i(len(categories))
        self.i(9)
        self.i(ncatalg)
        self.i(nwf)
        self.i(len(changes))
        self.s("20\n/test/release\nuser\n")
        self.i(len(changes))          # CHANGES count
        for c in changes:
            self.rec(D.CHANGES)
            self.s(c)
        self.h(1)                     # global table version
        self.i(0)
        self.i(0)
        self.f(1.0)
        for cat in categories:
            self.rec(D.CATEGORY)
            self.category(cat)
        return self

    def bytes(self, shot=0, nbdata=32):
        a = bytes(self.ascii)
        if len(a) % 2:
            a += b"\0"
        i16 = list(self.i16) + ([0] if len(self.i16) % 2 else [])
        data = np.asarray(self.data, np.uint32).ravel()
        if nbdata == 16:
            data = data.astype(np.uint16)
            if data.size % 2:
                data = np.append(data, np.uint16(0))
        return build_wa10({"shot": shot}, a, i16, self.i32, self.f32, self.f64,
                          data, nbdata=nbdata)


def labels(*items):
    return b"".join(s.encode() + b"\0" for s in items) + b"\0"


def example(nbdata=32, shot=0):
    """A two-category setup exercising every structure and item kind."""
    shape = {
        "name": "Discharge Shape",
        "sequences": [("Primary", [(0.0, 1.0), (6.0, 1.0)])],
        "algorithms": [
            {"identifier": "isosnull", "name": "Isoflux Single Null,isosnull",
             "subsets": ["Discharge shape", "Parameter selection"],
             "waveforms": [("Rp", "major radius", 1),
                           ("Zp", "height", 1),
                           ("gains", "StaticData: Labeled Structure", 2),
                           ("flags", "StaticData: Labeled Integer Array", 2),
                           ("M", "StaticData: Labeled Matrices", 2),
                           ("input", "StaticData: file name", 2),
                           ("odd", "StaticData: Snap Setups", 2),
                           ("bad", "StaticData: Labeled Structure", 2),
                           ("nodata", "StaticData: Labeled Integer Array", 2)]},
            {"identifier": "dn", "name": "Do Nothing", "subsets": ["x"],
             "waveforms": []},
        ],
        "phases": [
            {"name": "ShotStart", "alg": "isosnull", "entry": 3, "anchor": 0.0,
             "vertices": {"Rp": [(0.0, 168.0), (6.0, 168.5)],
                          "Zp": [(0.5, -2.0)]},
             "params": [
                 ("gains :data", 3, [("int", [1]), ("float", [0.875]),
                                     ("short", [7])]),
                 ("gains :labels", 3, [("char", labels(
                     "title: Disable check: |no|yes",
                     "C79 multiplier",
                     "count,old count"))]),
                 ("flags :data", 3, [("int", [1, 0])]),
                 ("M dimensions", 3, [("int", [1]), ("int", [2]), ("int", [3]),
                                      ("int", [20])]),
                 ("M row names", 3, [("char", b"r1".ljust(20, b"\0") +
                                      b"r2".ljust(20, b"\0"))]),
                 ("M col names", 3, [("char", b"".join(
                     c.ljust(20, b"\0") for c in (b"a", b"b", b"c")))]),
                 ("M names", 3, [("char", b"m0".ljust(20, b"\0"))]),
                 ("M data", 3, [("float", [1, 2, 3, 4, 5, 6])]),
                 ("input :file name", 3, [("char", b"f.dat\0\0")]),
                 ("odd snap", 3, [("double", [2.5]), ("uint32", [4000000000])]),
                 ("bad :data", 3, [("float", [1.0, 2.0])]),
                 ("bad :labels", 3, [("char", labels("only one"))]),
                 ("nodata :labels", 3, [("char", labels("x", "y"))]),
             ]},
            {"name": "rampdown", "alg": "dn", "entry": 1, "anchor": 4.5},
        ],
    }
    acq = {
        "name": "Data Acquisition",
        "algorithms": [{"identifier": "acq", "name": "Collect baseline data",
                        "subsets": ["Parameter Data"],
                        "waveforms": [("operating setup data", "StaticData: Setup Data", 1)]}],
        "phases": [{"name": "ShotStart", "alg": "acq", "params": [
            ("operating setup data :infra", 3, [
                ("int", [0]), ("int", [2]), ("int", [123]), ("int", [6000000]),
                ("int", [42257]), ("char", b"simhost\0")]),
            ("operating setup data :infra cpu", 3,
             [("int", [v]) for v in (0, 100000, 10, 0, 0, 1, 0,
                                     0, 150000, 10, 0, 0, 1, 0)]),
        ]}],
    }
    return Writer().setup([shape, acq]).bytes(shot=shot, nbdata=nbdata)
