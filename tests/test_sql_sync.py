# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Sync test: keep the d3d.yaml SqlLocator aligned with the hardcoded
defaults in toksearch.sql.mssql.connect_d3drdb.

This test exists because Phase 1 of the fdp-schema migration could not
migrate connect_d3drdb() to use the catalog (it would create a toksearch
→ fdp dependency cycle). The two sources of truth (hardcoded defaults vs
catalog) must stay aligned; this test fails loudly if either drifts.

Resolving the duplication permanently is tracked as follow-up work; see
the design spec's Non-Goals section.
"""

import unittest
from inspect import signature


class TestSqlLocatorSync(unittest.TestCase):
    def test_d3d_sql_locator_matches_connect_d3drdb_defaults(self):
        from fdp_schema import load_tokamak
        from toksearch_d3d.data import d3d_yaml
        from toksearch.sql.mssql import connect_d3drdb

        t = load_tokamak(d3d_yaml)
        sql = next(l for l in t.locators
                   if l.kind == "sql" and l.name == "d3drdb")

        sig = signature(connect_d3drdb)
        self.assertEqual(sql.host,     sig.parameters["host"].default,
                         "Catalog SqlLocator.host drifted from connect_d3drdb default")
        self.assertEqual(sql.port,     sig.parameters["port"].default,
                         "Catalog SqlLocator.port drifted from connect_d3drdb default")
        self.assertEqual(sql.database, sig.parameters["db"].default,
                         "Catalog SqlLocator.database drifted from connect_d3drdb default")
