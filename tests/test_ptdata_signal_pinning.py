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

    def fetch(self, pointname, shot, params, source='',
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

    def test_version_without_snapshot(self):
        """The two pins are independent; either may travel alone."""
        sig = PtDataSignal("ip")
        sig.gather(165920, record=Record.from_dict({"shot": 165920,
                                                    "version": 7}))
        self.assertEqual(self.reader.calls[-1]["version"], 7)
        self.assertIsNone(self.reader.calls[-1]["snapshot"])

    def test_snapshot_without_version(self):
        sig = PtDataSignal("ip")
        sig.gather(165920, record=Record.from_dict({"shot": 165920,
                                                    "snapshot": "catalog_y"}))
        self.assertIsNone(self.reader.calls[-1]["version"])
        self.assertEqual(self.reader.calls[-1]["snapshot"], "catalog_y")

    def test_an_explicit_none_is_not_a_pin(self):
        """A field present but None must read the same as absent."""
        sig = PtDataSignal("ip")
        sig.gather(165920, record=Record.from_dict({"shot": 165920,
                                                    "version": None,
                                                    "snapshot": None}))
        self.assertIsNone(self.reader.calls[-1]["version"])
        self.assertIsNone(self.reader.calls[-1]["snapshot"])


class TestPinSurvivesTheFramework(unittest.TestCase):
    """The pin is only useful if the FRAMEWORK carries it to gather().

    Every test above calls gather(record=...) by hand, which proves the
    signal reads the record but not that anything ever hands it one. That
    gap is not academic: against a toksearch whose Signal.fetch is
    `fetch(self, shot)`, a pinned pipeline silently returns UNVERSIONED
    data -- no error, no warning, just the wrong shot. This test runs a
    real Pipeline so that case is a red test instead.
    """

    def setUp(self):
        self.reader = _PinRecordingReader()
        registry = PtDataReaderRegistry()
        registry._reader = self.reader
        self.addCleanup(setattr, registry, "_reader", None)

    def test_a_pinned_pipeline_reaches_the_reader(self):
        from toksearch import Pipeline

        pipe = Pipeline([{"shot": 165920, "version": 3,
                          "snapshot": "catalog_z"}])
        pipe.fetch("ip", PtDataSignal("ip"))
        records = pipe.compute_serial()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].errors, {})
        self.assertEqual(self.reader.calls[-1]["version"], 3)
        self.assertEqual(self.reader.calls[-1]["snapshot"], "catalog_z")
