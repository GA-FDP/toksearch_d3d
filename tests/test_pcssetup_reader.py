# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Offline tests for toksearch_d3d.pcssetup (the .wa10 reader).

All setups here are synthetic (pcssetup_synth.Writer); no real setup data
is checked in. Real-shot checks are in test_pcssetup_live.py.
"""

import struct
import unittest

import numpy as np

from toksearch_d3d.pcssetup import Wa10FormatError, read_wa10
from toksearch_d3d.pcssetup.wa10 import split_sections

import pcssetup_synth as synth

class TestFileLayout(unittest.TestCase):
    def test_header_and_sections(self):
        raw = synth.example(shot=204019)
        sec = split_sections(raw)
        self.assertEqual(sec.header.pfi, 42)
        self.assertEqual(sec.header.shot, 204019)
        self.assertEqual(sec.header.ptname, "PCSSETUP")
        self.assertEqual(sec.data.shape[1], 7)
        self.assertEqual(len(raw), 192 + 2 * (sec.header.nwascii + sec.header.nwint16
                                              + sec.header.nwint32 + sec.header.nwreal32
                                              + sec.header.nwreal64 + sec.header.nwdata))

    def test_rejects_wrong_pfi_and_little_endian(self):
        raw = bytearray(synth.example())
        le = struct.pack("<i", 42) + raw[4:]
        with self.assertRaisesRegex(Wa10FormatError, "little-endian"):
            read_wa10(bytes(le))
        with self.assertRaises(Wa10FormatError):
            read_wa10(b"\0" * 10)

    def test_truncated_file(self):
        with self.assertRaisesRegex(Wa10FormatError, "header says"):
            read_wa10(synth.example()[:-8])

    def test_index_record_mismatch_is_caught(self):
        raw = bytearray(synth.example())
        sec = split_sections(bytes(raw))
        # Corrupt the char index of the last index record.
        off = len(raw) - 4 * 5
        raw[off:off + 4] = struct.pack(">I", 999999)
        with self.assertRaisesRegex(Wa10FormatError, "index record"):
            read_wa10(bytes(raw))
        self.assertIsNotNone(read_wa10(bytes(raw), strict=False))
        self.assertGreater(len(sec.data), 10)

    def test_16_bit_data_words(self):
        s16 = read_wa10(synth.example(nbdata=16))
        s32 = read_wa10(synth.example(nbdata=32))
        self.assertEqual(s16.header.nbdata, 16)
        self.assertEqual(repr(s16.snapshot()), repr(s32.snapshot()))


class TestStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = read_wa10(synth.example(shot=7))

    def test_install_and_history(self):
        s = self.s
        self.assertEqual(s.install["table_version"], 4)
        self.assertEqual(s.install["category_count"], 2)
        self.assertEqual(s.release, "/test/release")
        self.assertEqual(s.change_history, ("created",))
        self.assertEqual(s.shot, 7)

    def test_categories_phases_algorithms(self):
        s = self.s
        self.assertEqual([c.name for c in s.categories], ["Discharge Shape", "Data Acquisition"])
        self.assertEqual(s.read("Discharge Shape|ShotStart"),
                         {"alg": "Isoflux Single Null", "entry_behavior": "timePhsReach",
                          "anchor_time": 0.0})
        self.assertEqual(s.read("Discharge Shape|rampdown"),
                         {"alg": "Do Nothing", "entry_behavior": "beginOfPhs",
                          "anchor_time": 4.5})
        cat = s.category("Discharge Shape")
        self.assertEqual([a.number for a in cat.algorithms], [1, 2])
        self.assertEqual(cat.sequences[0].name, "Primary")
        self.assertEqual(cat.sequences[0].vertices, ((0.0, 1.0), (6.0, 1.0)))
        self.assertEqual(s.subsets("Discharge Shape", "ShotStart"),
                         ("Discharge shape", "Parameter selection"))

    def test_paths(self):
        paths = self.s.paths("Discharge Shape|ShotStart|Discharge shape")
        self.assertEqual(paths, ["Discharge Shape|ShotStart|Discharge shape|Rp",
                                 "Discharge Shape|ShotStart|Discharge shape|Zp"])
        self.assertIn("Discharge Shape|ShotStart", self.s.paths())
        self.assertEqual(self.s.paths("Discharge Shape|rampdown"), ["Discharge Shape|rampdown"])

    def test_missing_paths_suggest(self):
        with self.assertRaisesRegex(KeyError, "did you mean"):
            self.s.read("Discharge Shape|ShotStrt")
        with self.assertRaises(KeyError):
            self.s.read("Discharge Shape|ShotStart|Discharge shape|Rq")
        with self.assertRaises(ValueError):
            self.s.read("Discharge Shape|ShotStart|Discharge shape")


class TestItems(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = read_wa10(synth.example())
        cls.snap = cls.s.snapshot()

    def p(self, name, phase="ShotStart", sub="Parameter selection", cat="Discharge Shape"):
        return f"{cat}|{phase}|{sub}|{name}"

    def test_waveform_vertices(self):
        self.assertEqual(self.s.read("Discharge Shape|ShotStart|Discharge shape|Rp"),
                         ((0.0, 168.0), (6.0, 168.5)))

    def test_generic_titles_follow_pcsapi(self):
        # 'title:' keeps the text after the colon verbatim; ',old name' is dropped.
        self.assertEqual(self.s.read(self.p("gains")),
                         {" Disable check: ": 1, "C79 multiplier": 0.875, "count": 7})
        kind, value = self.s.item(self.p("gains")).read()
        self.assertEqual(kind, "generic")
        self.assertEqual(value.items[0].widget, "ComboBox")
        self.assertEqual(value.items[0].options, {0: "no", 1: "yes"})

    def test_values_without_archived_labels(self):
        self.assertEqual(self.snap[self.p("flags")], ("values", (1, 0)))

    def test_labels_without_archived_values(self):
        self.assertEqual(self.snap[self.p("nodata")], ("labels", {"x": None, "y": None}))

    def test_matrix(self):
        m = self.s.read(self.p("M"))
        self.assertEqual(m.names, ("m0",))
        self.assertEqual(m.row_names, ("r1", "r2"))
        self.assertEqual(m.col_names, ("a", "b", "c"))
        np.testing.assert_array_equal(m.data, [[[1, 2, 3], [4, 5, 6]]])

    def test_file(self):
        self.assertEqual(self.s.read(self.p("input")), "f.dat")

    def test_opaque_keeps_blocks(self):
        blocks = self.s.read(self.p("odd"))
        self.assertEqual([b.name for b in blocks], ["odd snap"])
        self.assertEqual(blocks[0].fields[0].values(), [2.5])
        self.assertEqual(blocks[0].fields[1].values(), [4000000000])
        self.assertEqual(self.snap[self.p("odd")], ("opaque", "StaticData: Snap Setups"))

    def test_label_count_mismatch_is_unreadable(self):
        kind, msg = self.snap[self.p("bad")]
        self.assertEqual(kind, "unreadable")
        self.assertIn("mismatch labels and data count", msg)
        with self.assertRaises(ValueError):
            self.s.read(self.p("bad"))

    def test_opsetup(self):
        o = self.s.read("Data Acquisition|ShotStart|Parameter Data|operating setup data")
        self.assertEqual((o.shot_num, o.time_to_stop, o.op_mode, o.sim_host, o.sim_port),
                         (123, 6000000, "simulation", "simhost", 42257))
        self.assertEqual(o.n_samples, (100000, 150000))


if __name__ == "__main__":
    unittest.main()
