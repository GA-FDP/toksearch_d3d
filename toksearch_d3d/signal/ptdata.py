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

from toksearch import Signal
from ptdata import PtDataFetcher


class PtDataSignal(Signal):
    def __init__(
        self, pointname, remote=True, ical=1, keep_header=False, fetch_times=True, fetch_units=True
    ):
        super().__init__()
        self.pointname = pointname
        self.remote = remote
        self.ical = ical
        self.remote = remote
        self.keep_header = keep_header
        self.fetch_times = fetch_times
        self.with_units = fetch_units

        if self.fetch_times:
            dims = ["times"]
        else:
            dims = None
        self.set_dims(dims)


    def gather(self, shot):

        dims = self.dims
        fetch_units = self.with_units
        results = {}


        fetch_times = self.fetch_times and (len(dims) > 0)

        fetcher = PtDataFetcher(self.pointname, shot)
        results = fetcher.fetch(fetch_times=fetch_times, ical=self.ical)

        if self.keep_header:
            results["header"] = fetcher.header

        if fetch_units:
            results["units"] = {}
            encoding = "utf-8"
            results["units"]["data"] = fetcher.units().decode(encoding)

            if fetch_times:
                results["units"][dims[0]] = "ms"

        return results


    def cleanup_shot(self, shot):
        pass

    def cleanup(self):
        pass

class RDataSignal(PtDataSignal):

    def __init__(
        self, remote=True, keep_header=False
    ):
        pointname = "RDATA"
        fetch_times = False
        fetch_units = False
        ical = 1
        super().__init__(pointname, remote, ical, keep_header, fetch_times, fetch_units)
