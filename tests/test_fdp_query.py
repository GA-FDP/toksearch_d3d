# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for the `fdp query` CLI subcommand.

Each test patches `query_toksearch` at its source-module dotted path
(`toksearch_d3d.agents.claude_toksearch_agent.query_toksearch`). The production
handler `do_query` does a lazy `from ... import query_toksearch` inside the
function body, which resolves to whatever attribute `mock.patch` has installed
on the source module -- so the mock is picked up correctly. Note that entering
the `with mock.patch(...):` block still triggers a full import of the agent
module (and its transitive `toksearch` chain); the patch protects only the
attribute lookup, not the import itself. That is acceptable here because these
tests only exercise argparse plumbing -- they do not need an FDP-prepared
os.environ.

`setup_environment` is patched on `cli` (not on `.environment`) because
`cli.py` does `from .environment import setup_environment`, binding the name
into the `cli` module namespace; that is the binding the handler reads.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


class TestFdpQuery(unittest.TestCase):
    def _run_cli(self, argv):
        """Invoke `toksearch_d3d.fdp.cli.main` with patched sys.argv and a
        no-op setup_environment (we don't want the test to touch os.environ).
        Returns captured stdout.
        """
        from toksearch_d3d.fdp import cli
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(cli, "setup_environment"), \
                redirect_stdout(buf):
            cli.main()
        return buf.getvalue()

    def test_defaults(self):
        """`fdp query "hello"` forwards defaults: max_iterations=10,
        verbose=True, debug=False, api_key_file=None."""
        recorder = mock.MagicMock(return_value="ANSWER")
        with mock.patch(
            "toksearch_d3d.agents.claude_toksearch_agent.query_toksearch",
            recorder,
        ):
            self._run_cli(["fdp", "query", "hello"])
        recorder.assert_called_once_with(
            "hello",
            max_iterations=10,
            verbose=True,
            debug=False,
            api_key_file=None,
        )

    def test_all_flags(self):
        """All flags wire through correctly: -n, --quiet, --api-key-file, and
        top-level --debug."""
        recorder = mock.MagicMock(return_value="ANSWER")
        with mock.patch(
            "toksearch_d3d.agents.claude_toksearch_agent.query_toksearch",
            recorder,
        ):
            self._run_cli([
                "fdp", "--debug",
                "query", "hi",
                "-n", "3",
                "--quiet",
                "--api-key-file", "/tmp/key",
            ])
        recorder.assert_called_once_with(
            "hi",
            max_iterations=3,
            verbose=False,
            debug=True,
            api_key_file=Path("/tmp/key"),
        )

    def test_result_is_printed(self):
        """Whatever `query_toksearch` returns is printed to stdout."""
        recorder = mock.MagicMock(return_value="THE ANSWER")
        with mock.patch(
            "toksearch_d3d.agents.claude_toksearch_agent.query_toksearch",
            recorder,
        ):
            out = self._run_cli(["fdp", "query", "anything"])
        self.assertIn("THE ANSWER", out)


if __name__ == "__main__":
    unittest.main()
