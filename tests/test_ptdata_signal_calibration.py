# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""PtDataSignal's `ical` flag must reach the engine's CalibrationMode through
ptdata's public `calibration_mode_for_ical` -- no local copy of the mapping.

The copy this replaced was missing `2: Volts` and fell back to Full for
anything it did not know, so `PtDataSignal(pt, ical=2)` silently returned
Full-calibrated data: a units error that looks like valid data.

These tests assert the *selected* CalibrationMode with a stub reader rather
than fetching real data, so they run offline (no shot files, no ptserver) and
check exactly the thing that used to be wrong.
"""

import unittest

import ptdata
from ptdata import _core

from toksearch_d3d.signal.ptdata import (
    PtDataSignal,
    PtDataReaderRegistry,
    RDataSignal,
)


class _StubResult:
    """Minimal stand-in for ptdata.ExtractedData as gather() consumes it."""

    data = [1.0, 2.0, 3.0]
    raw_integer = []
    times = [0.0, 1.0, 2.0]
    units = "AMPS"
    n_over = 0
    n_under = 0


class _RecordingReader:
    """Captures the ExtractionParams each fetch was issued with."""

    def __init__(self):
        self.calibrations = []

    def fetch(self, pointname, shot, params):
        self.calibrations.append(params.calibration)
        return _StubResult()


class TestPtDataSignalCalibrationMode(unittest.TestCase):
    SHOT = 165920
    PTNAME = "ip"

    def setUp(self):
        self.reader = _RecordingReader()
        # Seed the process-global registry so gather() picks up the stub
        # instead of building a real PtDataReader.
        registry = PtDataReaderRegistry()
        registry._reader = self.reader

    def tearDown(self):
        PtDataReaderRegistry().close()

    def _calibration_for(self, **kwargs):
        PtDataSignal(self.PTNAME, **kwargs).fetch(self.SHOT)
        self.assertEqual(len(self.reader.calibrations), 1)
        return self.reader.calibrations[0]

    def test_ical_2_selects_volts(self):
        # The regression: this used to silently come back as Full.
        self.assertEqual(self._calibration_for(ical=2),
                         _core.CalibrationMode.Volts)

    def test_default_ical_selects_full(self):
        self.assertEqual(self._calibration_for(), _core.CalibrationMode.Full)

    def test_ical_0_selects_raw(self):
        self.assertEqual(self._calibration_for(ical=0),
                         _core.CalibrationMode.Raw)

    def test_ical_4_selects_linear(self):
        self.assertEqual(self._calibration_for(ical=4),
                         _core.CalibrationMode.Linear)

    def test_signal_uses_ptdata_accessor(self):
        """Not a private copy of the mapping."""
        from toksearch_d3d.signal import ptdata as signal_ptdata
        self.assertFalse(hasattr(signal_ptdata, "_ICAL_MAP"))
        self.assertIs(signal_ptdata.calibration_mode_for_ical,
                      ptdata.calibration_mode_for_ical)

    def test_rdata_signal_still_fetches_full(self):
        """RDataSignal hardcodes ical=1; it must keep working."""
        RDataSignal().fetch(self.SHOT)
        self.assertEqual(self.reader.calibrations,
                         [_core.CalibrationMode.Full])


class TestPtDataSignalUnsupportedIcal(unittest.TestCase):
    """Behaviour change: an unsupported ical used to yield Full-calibrated
    data; it now raises."""

    SHOT = 165920
    PTNAME = "ip"

    def tearDown(self):
        PtDataReaderRegistry().close()

    def test_unsupported_ical_raises_at_construction(self):
        for ical in (3, 5, 10, 20, -1):
            with self.subTest(ical=ical):
                with self.assertRaises(ptdata.PtDataError) as ctx:
                    PtDataSignal(self.PTNAME, ical=ical)
                # 110 = InvalidConfiguration (not 14, InvalidCallType: a bad
                # ical is a bad argument, not a legacy call-type mismatch).
                self.assertEqual(ctx.exception.code, 110)

    def test_unsupported_ical_never_reaches_the_reader(self):
        reader = _RecordingReader()
        PtDataReaderRegistry()._reader = reader
        with self.assertRaises(ptdata.PtDataError):
            PtDataSignal(self.PTNAME, ical=3).fetch(self.SHOT)
        self.assertEqual(reader.calibrations, [])


if __name__ == "__main__":
    unittest.main()
