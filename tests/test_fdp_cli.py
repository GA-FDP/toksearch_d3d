# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for toksearch_d3d.fdp.cli.apply_environment."""

import unittest

from toksearch_d3d.fdp.cli import DEFAULT_CONFIG, apply_environment


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


if __name__ == "__main__":
    unittest.main()
