# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Tests for the pcssetup-to-wa10 console script.

Requires a configured FDP environment (run via `fdp run python testit.py`).
Targets shot 165920, the same shot the existing PtDataSignal tests use.
"""

import unittest
from pathlib import Path

SHOT = 165920
# PCSSETUP wa10 files are typically a few megabytes. 500 KB is well below
# the typical payload but well above any plausible header-only / parse-
# failure false positive.
MIN_REASONABLE_SIZE = 500_000


class TestPcssetupBytes(unittest.TestCase):
    def test_returns_realistic_size(self):
        """pcssetup_bytes returns the wa10 payload as bytes (a few MB)."""
        from toksearch_d3d.tools.pcssetup_to_wa10 import pcssetup_bytes

        b = pcssetup_bytes(SHOT)

        self.assertIsInstance(b, bytes)
        self.assertGreater(len(b), MIN_REASONABLE_SIZE)
