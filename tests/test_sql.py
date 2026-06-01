# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for toksearch_d3d.sql.connect_d3drdb."""

import os
import unittest
from pathlib import Path
from unittest import mock


class TestConnectD3DRDB(unittest.TestCase):
    def test_delegates_to_connect_tokamak_sql(self):
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch(
            "toksearch.sql.mssql.connect_tokamak_sql",
            return_value=mock.sentinel.conn,
        ) as fn:
            result = connect_d3drdb()
        fn.assert_called_once_with("d3d", "d3drdb")
        self.assertIs(result, mock.sentinel.conn)

    def test_forwards_kwargs(self):
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch(
            "toksearch.sql.mssql.connect_tokamak_sql"
        ) as fn:
            connect_d3drdb(db="code_rundb", port=9999)
        fn.assert_called_once_with(
            "d3d", "d3drdb", db="code_rundb", port=9999
        )

    @unittest.skipUnless(
        Path("~/.D3DRDB.sybase_login").expanduser().exists()
        or Path("~/D3DRDB.sybase_login").expanduser().exists(),
        "needs ~/.D3DRDB.sybase_login (or ~/D3DRDB.sybase_login)",
    )
    def test_integration_select_1(self):
        """Hits the real d3drdb. Skipped unless the password file exists."""
        from toksearch_d3d.sql import connect_d3drdb
        with connect_d3drdb() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            self.assertEqual(cur.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
