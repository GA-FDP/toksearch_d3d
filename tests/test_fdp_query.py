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

"""Tests for the `fdp query` and `fdp chat` CLI shims.

After PR 4 of the toksearch.llm migration, both subcommands are thin
re-exec shims that call `setup_environment()` (already invoked by
`main()` before dispatch) and then `os.execvpe` into
`python -m toksearch.llm.cli {query,chat} ...`.  These tests mock
`os.execvpe` to verify the argv and env are constructed correctly
without actually exec'ing.

`setup_environment` is patched on `cli` (not on `.environment`) because
`cli.py` does `from .environment import setup_environment`, binding the
name into the `cli` module namespace; that is the binding `main()` calls.
"""

import os
import sys
import unittest
from unittest import mock


class _ShimTestBase(unittest.TestCase):
    def _run_cli(self, argv):
        from toksearch_d3d.fdp import cli
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(cli, "setup_environment"), \
                mock.patch.object(cli.os, "execvpe") as execvpe_mock:
            # os.execvpe normally never returns; we don't want main() to
            # continue, so mock it to no-op.  In production it never returns
            # to Python because the process image is replaced.
            try:
                cli.main()
            except SystemExit:
                pass
        return execvpe_mock


class TestFdpQuery(_ShimTestBase):
    def test_query_dispatches_to_toksearch_llm_cli(self):
        m = self._run_cli(["fdp", "query", "hello"])
        m.assert_called_once()
        _, args, env = m.call_args.args
        self.assertEqual(args[0], sys.executable)
        self.assertEqual(args[1:4], ["-m", "toksearch.llm.cli", "query"])
        self.assertIn("hello", args)
        # Default --backend is amsc
        self.assertEqual(args[args.index("--backend") + 1], "amsc")
        # Env passes os.environ
        self.assertIs(env, os.environ)

    def test_query_backend_flag_forwarded(self):
        m = self._run_cli(
            ["fdp", "query", "--backend", "anthropic", "hi"])
        args = m.call_args.args[1]
        self.assertEqual(args[args.index("--backend") + 1], "anthropic")

    def test_query_max_iterations_flag_forwarded(self):
        m = self._run_cli(["fdp", "query", "-n", "3", "hi"])
        args = m.call_args.args[1]
        self.assertIn("-n", args)
        self.assertEqual(args[args.index("-n") + 1], "3")


class TestFdpChat(_ShimTestBase):
    def test_chat_dispatches_to_toksearch_llm_cli(self):
        m = self._run_cli(["fdp", "chat"])
        m.assert_called_once()
        _, args, env = m.call_args.args
        self.assertEqual(args[1:4], ["-m", "toksearch.llm.cli", "chat"])
        # Default --backend is amsc
        self.assertEqual(args[args.index("--backend") + 1], "amsc")
        self.assertIs(env, os.environ)

    def test_chat_backend_flag_forwarded(self):
        m = self._run_cli(["fdp", "chat", "--backend", "claude-max"])
        args = m.call_args.args[1]
        self.assertEqual(args[args.index("--backend") + 1], "claude-max")


if __name__ == "__main__":
    unittest.main()
