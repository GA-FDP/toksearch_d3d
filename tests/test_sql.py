# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests for toksearch_d3d.sql.connect_d3drdb."""

import os
import unittest
from pathlib import Path
from unittest import mock


class TestConnectD3DRDB(unittest.TestCase):
    def test_default_is_a_snapshot(self):
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch("toksearch.sql.snapshot.connect_tokamak",
                        return_value=mock.sentinel.snap) as fn:
            result = connect_d3drdb()
        fn.assert_called_once_with("d3d", "d3drdb", snapshot=None)
        self.assertIs(result, mock.sentinel.snap)

    def test_explicit_snapshot_is_forwarded(self):
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch("toksearch.sql.snapshot.connect_tokamak") as fn:
            connect_d3drdb(snapshot="d3drdb_20261005T120000Z")
        fn.assert_called_once_with("d3d", "d3drdb", snapshot="d3drdb_20261005T120000Z")

    def test_live_is_the_old_path_unchanged(self):
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch("toksearch.sql.mssql.connect_tokamak_sql",
                        return_value=mock.sentinel.conn) as fn:
            result = connect_d3drdb(live=True)
        fn.assert_called_once_with("d3d", "d3drdb")
        self.assertIs(result, mock.sentinel.conn)

    def test_live_forwards_overrides(self):
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch("toksearch.sql.mssql.connect_tokamak_sql") as fn:
            connect_d3drdb(live=True, db="code_rundb", port=9999)
        fn.assert_called_once_with("d3d", "d3drdb", db="code_rundb", port=9999)

    def test_overrides_without_live_are_refused(self):
        # host/port/credentials are live-database knobs; silently ignoring
        # them against a snapshot would be the fallback this design forbids.
        from toksearch_d3d.sql import connect_d3drdb
        with self.assertRaises(TypeError) as cm:
            connect_d3drdb(db="code_rundb")
        self.assertIn("live=True", str(cm.exception))

    def test_live_and_snapshot_together_are_refused(self):
        from toksearch_d3d.sql import connect_d3drdb
        with self.assertRaises(ValueError):
            connect_d3drdb(live=True, snapshot="d3drdb_x")

    def test_snapshot_errors_are_not_caught(self):
        # No fallback to live: a SnapshotError propagates as itself.
        from toksearch.sql.snapshot import SnapshotError
        from toksearch_d3d.sql import connect_d3drdb
        with mock.patch("toksearch.sql.snapshot.connect_tokamak",
                        side_effect=SnapshotError("no snapshot x")):
            with self.assertRaises(SnapshotError):
                connect_d3drdb()

    @unittest.skipUnless(
        Path("~/.D3DRDB.sybase_login").expanduser().exists()
        or Path("~/D3DRDB.sybase_login").expanduser().exists(),
        "needs ~/.D3DRDB.sybase_login (or ~/D3DRDB.sybase_login)",
    )
    def test_integration_select_1(self):
        """Hits the real d3drdb. Skipped unless the password file exists."""
        from toksearch_d3d.sql import connect_d3drdb
        with connect_d3drdb(live=True) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            self.assertEqual(cur.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
