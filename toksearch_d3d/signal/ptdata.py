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

import os
import warnings

import numpy as np

from toksearch import Signal
from toksearch.utilities.utilities import set_env

import ptdata
# calibration_mode_for_ical is ptdata's single source of truth for the legacy
# `ical` flag -> CalibrationMode translation. It needs a newer ptdata than the
# >=2.0.13 floor pinned in pixi.toml / recipe/recipe.yaml -- unreleased as of
# this commit; bump both floors to the release that ships it.
from ptdata import _core, calibration_mode_for_ical


class PtDataReaderRegistry:
    """Process-global holder for a single shared ``ptdata.PtDataReader``.

    All ``PtDataSignal`` instances in a worker fetch through one reader, so the
    underlying ptserver connection (pooled inside ptdata >= 2.0.13) is reused
    across shots instead of re-dialed per fetch. The reader lives here rather
    than on the Signal instance so Signals stay picklable for
    multiprocessing/Ray workers -- the same pattern as
    ``toksearch.signal.mds.MdsTreeRegistry``.

    Pid-guarded: a forked worker gets a fresh registry (and rebuilds its own
    reader) rather than inheriting the parent's, mirroring
    ``toksearch.signal.SignalRegistry``. A reader carried across ``fork()``
    would be unsafe -- libfdpio (XrdCl + libcurl) is not fork-safe.
    """

    __instance = None

    def __new__(cls):
        inst = PtDataReaderRegistry.__instance
        pid = os.getpid()
        if inst is None or inst._pid != pid:
            inst = object.__new__(cls)
            inst._reader = None
            inst._pid = pid
            PtDataReaderRegistry.__instance = inst
        return inst

    def reader(self):
        """Return the shared reader, constructing it on first use.

        The reader captures its configuration from the environment
        (``SYS_D3``, ``PTDATA_JSON_INDEX_DIR``/``PTDATA_PLUGIN_LIB``,
        ``PTDATA_PTSERVERS``) at construction and reuses it until
        :meth:`close`; a mid-process env change only takes effect on the next
        chunk (after ``cleanup()``). Fine under ``fdp run``, where the
        environment is fixed per process.
        """
        if self._reader is None:
            self._reader = ptdata.PtDataReader()
        return self._reader

    def close(self):
        """Drop the shared reader. The pooled ptserver connection is owned by
        ptdata's process-global pool, so it survives for other users and is
        released at process exit."""
        self._reader = None


class PtDataSignal(Signal):
    """Fetch a DIII-D PTDATA diagnostic as a toksearch Signal.

    Fetches through the modern ``ptdata.PtDataReader`` (shared per process via
    ``PtDataReaderRegistry``): a single ``fetch`` yields data, times, and units
    together, so there is one ptserver round-trip per shot rather than the
    legacy ``PtDataFetcher``'s separate header read + data fetch. Times are in
    milliseconds.

    Args:
        pointname: PTDATA point name (case-insensitive), e.g. `'ip'`.
        remote: Retained for backward compatibility; sets `PTDATA_LOC` for the
            fetch. NOTE: `PTDATA_LOC` is a no-op in the ptdata 2.0 engine —
            routing (Pelican index vs local files vs ptserver/athena) is
            determined by the environment (`PTDATA_JSON_INDEX_DIR`, `SYS_D3`,
            `PTDATA_PTSERVERS`) set up by `fdp`, not by this flag.
        ical: Legacy PTDATA calibration flag, translated by
            `ptdata.calibration_mode_for_ical`. `1` (default) returns data in
            physics units; `0` returns raw digitizer counts; `2` returns volts
            into the digitizer; `4` returns the integrated signal (v-sec).
            Any other value raises `ptdata.PtDataError` (code 110,
            `InvalidConfiguration`) at construction rather than quietly
            substituting a calibration -- returning differently-calibrated
            data than the caller asked for is a units error that looks like
            valid data.
        keep_header: If True, include the raw PTDATA header (a
            `ptdata.PtDataHeader`) in the result under the `'header'` key.
            Note: this incurs an extra header read.
        fetch_times: If True (default), include a `'times'` array
            (milliseconds) in the result.
        fetch_units: If True (default), include a `'units'` dict in the
            result.
    """

    def __init__(
        self, pointname, remote=True, ical=1, keep_header=False, fetch_times=True, fetch_units=True
    ):
        super().__init__()
        self.pointname = pointname
        self.remote = remote
        # Reject an unsupported ical here, in the caller's own traceback,
        # rather than once per shot inside a pipeline worker. The resolved
        # mode is deliberately not cached on the instance: `ical` is a plain
        # attribute a caller can reassign, so gather() re-resolves it.
        calibration_mode_for_ical(ical)
        self.ical = ical
        self.keep_header = keep_header
        self.fetch_times = fetch_times
        self.with_units = fetch_units

        if self.fetch_times:
            dims = ["times"]
        else:
            dims = None
        self.set_dims(dims)

    def _spec_fields(self):
        # `fetch_units` is deliberately absent: __init__ stores it as the base
        # class's `with_units`, which Signal.spec() already records at the top
        # level. The resolved CalibrationMode is absent too -- `ical` is the
        # value the caller set and gather() re-resolves it per fetch.
        return {
            "pointname": self.pointname,
            "remote": self.remote,
            "ical": self.ical,
            "keep_header": self.keep_header,
            "fetch_times": self.fetch_times,
        }


    def gather(self, shot, record=None):
        dims = self.dims
        fetch_units = self.with_units

        fetch_times = self.fetch_times and (len(dims) > 0)

        ptdata_loc = '1' if self.remote else '0'
        with set_env('PTDATA_LOC', ptdata_loc):
            reader = PtDataReaderRegistry().reader()

            params = _core.ExtractionParams()
            params.fetch_times = fetch_times
            params.calibration = calibration_mode_for_ical(self.ical)

            # The version travels with the SHOT, not the signal: one
            # PtDataSignal serves every shot in a pipeline, so a constructor
            # kwarg would mean "v2 of everything". The shot list carries it --
            # Pipeline([{"shot": N, "version": V}]) -- and the framework hands
            # the record here without interpreting it.
            #
            # Record.get REQUIRES a default; it is not dict.get.
            version = record.get("version", None) if record is not None else None
            snapshot = record.get("snapshot", None) if record is not None else None

            result = reader.fetch(self.pointname, int(shot), params,
                                  version=version, snapshot=snapshot)

            # Raw calibration populates raw_integer rather than data; fall
            # through so 'data' is non-empty regardless of mode (matches the
            # legacy fetch_ptdata contract).
            data_source = result.data if len(result.data) > 0 else result.raw_integer
            results = {
                "data": np.array(data_source),
                "n_over": result.n_over,
                "n_under": result.n_under,
            }
            if fetch_times and len(result.times) > 0:
                results["times"] = np.array(result.times)

            if self.keep_header:
                # Opt-in: the header is not part of the single fetch, so this
                # costs one extra read. PtDataHeader is deprecated but returned
                # verbatim for output parity; suppress its per-call warning.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    results["header"] = ptdata.PtDataHeader(self.pointname, int(shot))

            if fetch_units:
                results["units"] = {}
                # ExtractedData.units is the raw 4-char field; match the legacy
                # PtDataHeader.units() normalization (lowercased, trimmed).
                results["units"]["data"] = result.units.strip().lower()
                if fetch_times:
                    results["units"][dims[0]] = "ms"

        return results


    def cleanup_shot(self, shot):
        pass

    def cleanup(self):
        PtDataReaderRegistry().close()

class RDataSignal(PtDataSignal):
    """Fetch the RDATA point from PTDATA as a toksearch Signal.

    RDATA is a DIII-D operations lookup array.  This signal always fetches
    the `RDATA` point with no time array and no units.

    Args:
        remote: If True (default), sets `PTDATA_LOC=1` for the fetch,
            routing to the Pelican/OSDF remote store.  If False, sets
            `PTDATA_LOC=0`, forcing local ptserver (athena) access.
        keep_header: If True, include the raw PTDATA header dict in the
            result under the `'header'` key.
    """

    def __init__(
        self, remote=True, keep_header=False
    ):
        pointname = "RDATA"
        fetch_times = False
        fetch_units = False
        ical = 1
        super().__init__(pointname, remote, ical, keep_header, fetch_times, fetch_units)
