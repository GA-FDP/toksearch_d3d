# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Tests for the pcssetup-to-wa10 console script.

Requires a configured FDP environment (run via `fdp run python testit.py`).
Targets shot 165920, the same shot the existing PtDataSignal tests use.
"""

import contextlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SHOT = 165920
# Shot 165920's PCSSETUP payload: 320565 int32 words = 1,282,260 bytes.
# Hardcoding this exact value is the regression guard: if pcssetup_bytes
# accidentally goes back to ical=1 (Full calibration), the result becomes
# float64 (8 bytes/sample) and doubles in size, failing this assertion.
EXPECTED_SIZE_165920 = 320_565 * 4


class TestPcssetupBytes(unittest.TestCase):
    def test_returns_raw_int32_payload(self):
        """pcssetup_bytes returns the raw int32 wa10 payload (not calibrated float64)."""
        from toksearch_d3d.tools.pcssetup_to_wa10 import pcssetup_bytes

        b = pcssetup_bytes(SHOT)

        self.assertIsInstance(b, bytes)
        # Exact size catches calibration-mode regression (would be 2x at ical=1).
        self.assertEqual(len(b), EXPECTED_SIZE_165920)


class TestMain(unittest.TestCase):
    def test_writes_file_with_default_name(self):
        """main(["<shot>"]) writes <shot>.wa10 in cwd, returns 0."""
        from toksearch_d3d.tools.pcssetup_to_wa10 import main, pcssetup_bytes

        expected = pcssetup_bytes(SHOT)

        with tempfile.TemporaryDirectory() as td:
            with contextlib.chdir(td), redirect_stdout(io.StringIO()):
                rc = main([str(SHOT)])

            out = Path(td) / f"{SHOT}.wa10"
            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())
            self.assertEqual(out.stat().st_size, len(expected))

    def test_writes_file_with_explicit_output(self):
        """main(["<shot>", "-o", path]) writes to that path, returns 0."""
        from toksearch_d3d.tools.pcssetup_to_wa10 import main, pcssetup_bytes

        expected = pcssetup_bytes(SHOT)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "custom.wa10"
            with redirect_stdout(io.StringIO()):
                rc = main([str(SHOT), "-o", str(out)])

            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())
            self.assertEqual(out.stat().st_size, len(expected))


if __name__ == "__main__":
    unittest.main()
