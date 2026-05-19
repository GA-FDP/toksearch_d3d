#!/usr/bin/env python

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


import argparse
import unittest
import sys
import os


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--noptdata", action="store_true")
    parser.add_argument("--nod3drdb", action="store_true")
    parser.add_argument(
        "--fast-exit", action="store_true",
        help="Use os._exit instead of sys.exit after the suite completes. "
             "Bypasses Python's interpreter shutdown, which can hang on "
             "C-extension worker threads (libfdpio/XRootD) that don't "
             "terminate cleanly. The exit code (0/1) is preserved; all "
             "TextTestRunner output is already on stderr before exit, so "
             "no test results are masked. Use in CI where you only need "
             "the exit code, not graceful shutdown.")

    args = parser.parse_args()

    os.environ["TOKSEARCH_INTEGRATION"] = "no" if args.mock else "yes"

    os.environ["TOKSEARCH_PTDATA_TEST"] = "no" if args.noptdata else "yes"

    loader = unittest.TestLoader()
    runner = unittest.TextTestRunner(verbosity=2)

    test_dir = "."
    tests = loader.discover(test_dir)

    res = runner.run(tests)
    exit_code = 0 if res.wasSuccessful() else 1
    if args.fast_exit:
        os._exit(exit_code)
    sys.exit(exit_code)
