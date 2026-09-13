"""A pinned shot's version must reach PtDataReader.

The version travels with the SHOT, not the signal: one PtDataSignal serves
every shot in a pipeline, so a constructor kwarg would mean "v2 of
everything". Pipeline already accepts dicts, so the shot list expresses it:

    Pipeline([{"shot": 165920, "version": 2}])

These tests assert what the READER RECEIVED, not what came back. The store
holds one version of every shot today, so a test checking only the returned
data would pass whether or not the pin was passed through.
"""

import unittest

from toksearch.record import Record
from toksearch_d3d.signal.ptdata import PtDataSignal, PtDataReaderRegistry


class _StubResult:
    data = [1.0, 2.0, 3.0]
    raw_integer = []
    times = [0.0, 1.0, 2.0]
    units = "AMPS"
    n_over = 0
    n_under = 0
    version = 1
    snapshot = "catalog_stub"


class _PinRecordingReader:
    """Captures the pin each fetch was issued with."""

    def __init__(self):
        self.calls = []

    def fetch(self, pointname, shot, params, source=None,
              version=None, snapshot=None):
        self.calls.append({"version": version, "snapshot": snapshot})
        return _StubResult()


class TestPtDataSignalPinning(unittest.TestCase):
    def setUp(self):
        self.reader = _PinRecordingReader()
        registry = PtDataReaderRegistry()
        registry._reader = self.reader
        self.addCleanup(setattr, registry, "_reader", None)

    def test_a_pinned_record_reaches_the_reader(self):
        sig = PtDataSignal("ip")
        rec = Record.from_dict({"shot": 165920, "version": 2,
                                "snapshot": "catalog_x"})
        sig.gather(165920, record=rec)

        self.assertEqual(self.reader.calls[-1]["version"], 2)
        self.assertEqual(self.reader.calls[-1]["snapshot"], "catalog_x")

    def test_an_unpinned_record_sends_no_pin(self):
        sig = PtDataSignal("ip")
        sig.gather(165920, record=Record.from_dict({"shot": 165920}))

        self.assertIsNone(self.reader.calls[-1]["version"])
        self.assertIsNone(self.reader.calls[-1]["snapshot"])

    def test_no_record_at_all_still_works(self):
        """gather() is public; a caller may invoke it without a record."""
        PtDataSignal("ip").gather(165920)
        self.assertIsNone(self.reader.calls[-1]["version"])
