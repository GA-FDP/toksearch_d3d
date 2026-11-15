# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Live tests: fetch PCSSETUP from PTDATA and decode it.

Need a configured FDP environment (run under `fdp run`, which supplies
BEARER_TOKEN). Shot 204019's expected bytes and values were checked
against the PCS's own pcssetup_to_wa10 output for that shot (body
byte-identical; see docs/superpowers/specs/2026-11-15-pcssetup-reader-design.md).

TestWaveserverReference runs only with PCSSETUP_REFERENCE_DIR set, since its
reference setups are real machine data and are not checked in.
"""

import os
import unittest

SHOT = 204019
WA10_BYTES_204019 = 4_036_996

LIVE = bool(os.environ.get("BEARER_TOKEN")) and \
    os.environ.get("TOKSEARCH_PTDATA_TEST", "yes") != "no"


@unittest.skipUnless(LIVE, "needs BEARER_TOKEN (run under `fdp run`)")
class TestFetch(unittest.TestCase):
    def test_rebuilt_file(self):
        from toksearch_d3d.pcssetup import pcssetup_wa10_bytes, read_wa10
        b = pcssetup_wa10_bytes(SHOT)
        self.assertEqual(len(b), WA10_BYTES_204019)
        s = read_wa10(b)
        self.assertEqual(s.shot, SHOT)
        self.assertEqual(s.header.shdate, (6, 23, 2025))
        self.assertEqual(s.release, "/data/ops/release/3.1.69z")
        self.assertEqual(len(s.categories), 58)
        self.assertEqual(len(s.paths()), 7123)

    def test_values(self):
        from toksearch_d3d.pcssetup import pcssetup
        s = pcssetup(SHOT)
        self.assertEqual(s.read("Discharge Shape|ShotStart"),
                         {"alg": "Isoflux Single Null Divertor",
                          "entry_behavior": "timePhsReach", "anchor_time": 0.0})
        rp = s.read("Discharge Shape|ShotStart|Discharge shape|Rp")
        self.assertEqual(len(rp), 7)
        self.assertAlmostEqual(rp[-1][0], 12.8, places=5)
        p = s.read("Error Field|Icontrol|Shared EF & RWM waveforms|Parameters")
        self.assertEqual(p["Timeout waiting for rwmid (usec)"], 1000)
        self.assertAlmostEqual(p["C79 multiplier (when paired with C259)"], 0.875)

    def test_signal_in_pipeline(self):
        from toksearch import Pipeline
        from toksearch_d3d.pcssetup import PcsSetupSignal
        paths = ["Discharge Shape|ShotStart",
                 "Error Field|Icontrol|Shared EF & RWM waveforms|Parameters",
                 "No Such Category|ShotStart"]
        p = Pipeline([SHOT])
        p.fetch("setup", PcsSetupSignal(paths))
        rec = p.compute_serial()[0]
        data = rec["setup"]["data"]
        self.assertEqual(data["Discharge Shape|ShotStart"]["alg"],
                         "Isoflux Single Null Divertor")
        self.assertIsNone(data["No Such Category|ShotStart"])

    def test_signal_scope(self):
        from toksearch_d3d.pcssetup import PcsSetupSignal
        out = PcsSetupSignal(scope="Gas").fetch(SHOT)["data"]
        self.assertIn("Gas|ShotStart", out)
        self.assertTrue(all(p.startswith("Gas|") for p in out))

    def test_1997_setup(self):
        """16-bit data words and the pre-pcs_forarchive parameter layout."""
        from toksearch_d3d.pcssetup import pcssetup
        s = pcssetup(90000)
        self.assertEqual(s.header.nbdata, 16)
        self.assertEqual(s.install["table_version"], 2)
        self.assertEqual(len(s.categories), 11)
        snap = s.snapshot()
        self.assertEqual(sum(k == "phase" for k, _ in snap.values()), 19)
        self.assertEqual(sum(k == "waveform" for k, _ in snap.values()), 546)


def _same(a, b):
    import numpy as np
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, float) or isinstance(b, float):
        return np.float32(a) == np.float32(b)
    return a == b


REFERENCE_DIR = os.environ.get("PCSSETUP_REFERENCE_DIR")


@unittest.skipUnless(REFERENCE_DIR, "set PCSSETUP_REFERENCE_DIR to a directory of "
                     "<name>.wa10[.xz] + <name>.snapshot.json[.xz] pairs")
class TestWaveserverReference(unittest.TestCase):
    """Each setup file a waveserver wrote matches pcssetup's snapshot of it.

    The pairs are real setups, so they are kept outside the repository:
    the .wa10 is the waveserver's own setup file and the snapshot is
    pcssetup's Session._snapshot() taken just before the file was copied.
    """

    def _pairs(self):
        import glob
        for snap in sorted(glob.glob(os.path.join(REFERENCE_DIR, "*.snapshot.json*"))):
            stem = snap.split(".snapshot.json")[0]
            wa10 = [p for p in (stem + ".wa10", stem + ".wa10.xz") if os.path.exists(p)]
            if wa10:
                yield os.path.basename(stem), wa10[0], snap

    @staticmethod
    def _load(path):
        import lzma
        opener = lzma.open if path.endswith(".xz") else open
        with opener(path, "rb") as f:
            return f.read()

    def test_matches_waveserver_snapshot(self):
        import json
        from toksearch_d3d.pcssetup import read_wa10
        pairs = list(self._pairs())
        self.assertTrue(pairs, f"no reference pairs in {REFERENCE_DIR}")
        for name, wa10, snap in pairs:
            with self.subTest(name=name):
                ref = json.loads(self._load(snap))
                mine = read_wa10(self._load(wa10)).snapshot()
                self.assertEqual(set(mine), set(ref))
                for path, (rk, rv) in ref.items():
                    mk, mv = mine[path]
                    if rk in ("opaque", "unreadable"):
                        continue
                    if rk == "generic" and mk == "values":
                        # Labels not archived: same values, no titles.
                        self.assertTrue(_same(list(rv.values()), list(mv)), path)
                        continue
                    if rk == "generic" and mk == "labels":
                        # Values not archived: the waveserver shows defaults.
                        self.assertEqual(list(rv), list(mv), path)
                        continue
                    self.assertEqual(rk, mk, path)
                    if rk == "opsetup":
                        mv = dict(mv, n_samples=list(mv["n_samples"])[:len(rv["n_samples"])])
                    self.assertTrue(_same(rv, mv), f"{path}: {rv!r} != {mv!r}")


if __name__ == "__main__":
    unittest.main()
