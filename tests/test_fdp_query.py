# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for the `fdp query` CLI subcommand.

`do_query` runs the agent in a fresh Python subprocess so the child inherits
the FDP-prepared os.environ at startup (required for libXrdCl + MDSplus tree
opens via the Pelican-backed default_tree_path). These tests mock
`subprocess.run` to assert that the right command, environment, and stdin
payload are built from the CLI arguments -- they do not actually spawn a
subprocess or invoke the LLM.

`setup_environment` is patched on `cli` (not on `.environment`) because
`cli.py` does `from .environment import setup_environment`, binding the name
into the `cli` module namespace; that is the binding `main()` calls.
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock


class TestFdpQuery(unittest.TestCase):
    def _run_cli(self, argv, subprocess_returncode=0):
        """Invoke `toksearch_d3d.fdp.cli.main` with patched sys.argv, a
        no-op setup_environment, and a mocked subprocess.run.

        Returns (subprocess_run_mock, captured_stdout, sys_exit_code).
        """
        from toksearch_d3d.fdp import cli
        buf = io.StringIO()
        fake_proc = mock.MagicMock()
        fake_proc.returncode = subprocess_returncode
        exit_code = None
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(cli, "setup_environment"), \
                mock.patch.object(cli.subprocess, "run", return_value=fake_proc) as run_mock, \
                redirect_stdout(buf):
            try:
                cli.main()
            except SystemExit as e:
                exit_code = e.code
        return run_mock, buf.getvalue(), exit_code

    def _payload_from_call(self, run_mock):
        """Pull the JSON stdin payload out of the mocked subprocess.run call."""
        self.assertEqual(run_mock.call_count, 1)
        _args, kwargs = run_mock.call_args
        self.assertIn("input", kwargs)
        return json.loads(kwargs["input"])

    def test_defaults(self):
        """`fdp query "hello"` builds a payload with default kwargs."""
        run_mock, _, _ = self._run_cli(["fdp", "query", "hello"])
        payload = self._payload_from_call(run_mock)
        self.assertEqual(payload, {
            "prompt": "hello",
            "max_iterations": 10,
            "verbose": True,
            "debug": False,
            "api_key_file": None,
        })

    def test_all_flags(self):
        """All flags wire through: -n, --quiet, --api-key-file, top-level --debug."""
        run_mock, _, _ = self._run_cli([
            "fdp", "--debug",
            "query", "hi",
            "-n", "3",
            "--quiet",
            "--api-key-file", "/tmp/key",
        ])
        payload = self._payload_from_call(run_mock)
        self.assertEqual(payload, {
            "prompt": "hi",
            "max_iterations": 3,
            "verbose": False,
            "debug": True,
            "api_key_file": "/tmp/key",
        })

    def test_subprocess_command_shape(self):
        """The subprocess command is [sys.executable, '-c', runner_script]."""
        from toksearch_d3d.fdp import cli
        run_mock, _, _ = self._run_cli(["fdp", "query", "anything"])
        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1], "-c")
        self.assertEqual(cmd[2], cli.QUERY_RUNNER_SCRIPT)

    def test_subprocess_env_is_os_environ(self):
        """The subprocess inherits os.environ (populated by setup_environment)."""
        import os
        run_mock, _, _ = self._run_cli(["fdp", "query", "anything"])
        self.assertIs(run_mock.call_args.kwargs["env"], os.environ)

    def test_exit_code_propagates(self):
        """sys.exit is called with the subprocess's returncode."""
        _, _, exit_code = self._run_cli(["fdp", "query", "anything"],
                                        subprocess_returncode=7)
        self.assertEqual(exit_code, 7)


if __name__ == "__main__":
    unittest.main()
