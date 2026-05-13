# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for toksearch_d3d.fdp.environment."""

import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from toksearch_d3d.fdp.environment import DEFAULT_CONFIG, apply_environment


class TestApplyEnvironment(unittest.TestCase):
    def test_path_always_overwritten(self):
        """PATH is overwritten because config["PATH"] already incorporates the existing PATH."""
        env = {"PATH": "/existing/bin"}
        config = {"PATH": "/new/bin:/existing/bin"}
        apply_environment(config, env)
        self.assertEqual(env["PATH"], "/new/bin:/existing/bin")

    def test_existing_value_not_clobbered(self):
        """User-set values for non-PATH keys are preserved."""
        env = {"PATH": "/p", "TDSVER": "8.0"}
        config = {"PATH": "/p", "TDSVER": "7.0"}
        apply_environment(config, env)
        self.assertEqual(env["TDSVER"], "8.0")

    def test_missing_value_filled_from_config(self):
        """Keys not present in env get the default from config."""
        env = {"PATH": "/p"}
        config = {"PATH": "/p", "MKL_NUM_THREADS": "1"}
        apply_environment(config, env)
        self.assertEqual(env["MKL_NUM_THREADS"], "1")

    def test_mutates_in_place(self):
        """env is mutated in place (no rebind), preserving os._Environ semantics."""
        env = {"PATH": "/p"}
        original_id = id(env)
        result = apply_environment({"PATH": "/p", "FOO": "bar"}, env)
        self.assertIsNone(result)
        self.assertEqual(id(env), original_id)
        self.assertEqual(env["FOO"], "bar")

    def test_real_default_config_against_synthetic_env(self):
        """End-to-end with the real DEFAULT_CONFIG: PATH applied, existing kept, missing filled."""
        env = {"PATH": "/system/bin", "OMP_NUM_THREADS": "4"}
        apply_environment(DEFAULT_CONFIG, env)
        # PATH always replaced with config's value (which prepends the env's bin_dir).
        self.assertEqual(env["PATH"], DEFAULT_CONFIG["PATH"])
        # User-set OMP_NUM_THREADS survives.
        self.assertEqual(env["OMP_NUM_THREADS"], "4")
        # TDSVER wasn't in env, gets the default.
        self.assertEqual(env["TDSVER"], "7.0")


class TestSetupEnvironment(unittest.TestCase):
    """setup_environment applies defaults, force-sets overrides, resolves bearer token."""

    def _isolated_env(self, **initial):
        """Return a mock.patch.dict context that fully replaces os.environ."""
        return mock.patch.dict(os.environ, initial, clear=True)

    def _isolated_home(self, tmpdir):
        """Patch Path.home() inside environment.py to point at tmpdir."""
        return mock.patch(
            "toksearch_d3d.fdp.environment.Path.home",
            return_value=Path(tmpdir),
        )

    def test_default_applied_when_env_empty(self):
        """DEFAULT_CONFIG values populate when env var is absent."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(), tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake")
            self.assertEqual(os.environ["TDSVER"], "7.0")

    def test_existing_env_preserved_against_default(self):
        """User-set env values win over DEFAULT_CONFIG (no override passed)."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(TDSVER="8.0"), \
                tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake")
            self.assertEqual(os.environ["TDSVER"], "8.0")

    def test_override_wins_over_existing_env(self):
        """A keyword override beats an already-set env var."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(PTDATA_LOC="9"), \
                tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake", PTDATA_LOC="1")
            self.assertEqual(os.environ["PTDATA_LOC"], "1")

    def test_override_stringifies_non_string_value(self):
        """Non-string override values are converted via str()."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(), tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake", PTDATA_LOC=2)
            self.assertEqual(os.environ["PTDATA_LOC"], "2")

    def test_bearer_token_arg_wins(self):
        """Explicit bearer_token arg beats existing BEARER_TOKEN env var."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(BEARER_TOKEN="from_env"), \
                tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="from_arg")
            self.assertEqual(os.environ["BEARER_TOKEN"], "from_arg")

    def test_bearer_token_falls_back_to_env(self):
        """When no arg given, existing BEARER_TOKEN env var is kept."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(BEARER_TOKEN="from_env"), \
                tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment()
            self.assertEqual(os.environ["BEARER_TOKEN"], "from_env")

    def test_bearer_token_falls_back_to_file(self):
        """When no arg and no env var, ~/.fdp/token is read."""
        from toksearch_d3d.fdp.environment import setup_environment
        with tempfile.TemporaryDirectory() as tmp:
            fdp_dir = Path(tmp) / ".fdp"
            fdp_dir.mkdir()
            (fdp_dir / "token").write_text("from_file\n")
            with self._isolated_env(), self._isolated_home(tmp):
                setup_environment()
                self.assertEqual(os.environ["BEARER_TOKEN"], "from_file")

    def test_bearer_token_warns_when_none_found(self):
        """Warns when no token can be resolved."""
        from toksearch_d3d.fdp.environment import setup_environment
        with tempfile.TemporaryDirectory() as tmp, \
                self._isolated_env(), self._isolated_home(tmp):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                setup_environment()
                messages = [str(w.message) for w in caught]
                self.assertTrue(
                    any("BEARER_TOKEN" in m for m in messages),
                    f"expected a BEARER_TOKEN warning, got: {messages}",
                )

    def test_safe_to_call_twice(self):
        """Calling setup_environment twice is idempotent."""
        from toksearch_d3d.fdp.environment import setup_environment
        with self._isolated_env(), tempfile.TemporaryDirectory() as tmp, \
                self._isolated_home(tmp):
            setup_environment(bearer_token="fake")
            first_path = os.environ["PATH"]
            setup_environment(bearer_token="fake")
            self.assertEqual(os.environ["PATH"], first_path)
            self.assertEqual(os.environ["TDSVER"], "7.0")


if __name__ == "__main__":
    unittest.main()
