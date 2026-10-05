# Copyright 2026 General Atomics
# Licensed under the Apache License, Version 2.0.

"""connect_d3drdb() against the origin, and against the live database.

The acceptance half needs BEARER_TOKEN and a published snapshot; CI's
live-fetch job has the token, and the test skips with the reason until
D1 publishes. The differential half additionally needs the live database
(on-site only): the same queries, bounded by the snapshot's shot ceiling,
must agree exactly. It is the one test that checks fidelity against SQL
Server rather than against our account of SQL Server.
"""

import os
import unittest
import warnings
from pathlib import Path

HAVE_TOKEN = bool(os.environ.get("BEARER_TOKEN"))
HAVE_LIVE = (Path("~/D3DRDB.sybase_login").expanduser().exists()
             or Path("~/.D3DRDB.sybase_login").expanduser().exists())


def _published():
    """True if at least one snapshot is published, False if the listing is empty.

    An unreachable origin is a failure to report, not a reason to skip: any
    SnapshotError raised while resolving the base or listing propagates, so
    setUpClass errors with the real message.
    """
    if not HAVE_TOKEN:
        return False
    from toksearch.sql import snapshot
    loc = snapshot.locator_for("d3d", "d3drdb")
    base = snapshot.resolve_base(loc.base_url)
    return bool(snapshot.list_ids(base, loc.id_pattern, os.environ["BEARER_TOKEN"]))


def _quiet_notice(cls):
    """Silence SnapshotNotice for this class only; restored at class cleanup."""
    from toksearch.sql.snapshot import SnapshotNotice
    ctx = warnings.catch_warnings()
    ctx.__enter__()
    cls.addClassCleanup(ctx.__exit__, None, None, None)
    warnings.simplefilter("ignore", SnapshotNotice)


@unittest.skipUnless(HAVE_TOKEN, "needs BEARER_TOKEN (run under `fdp run`)")
class TestAgainstTheOrigin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _published():
            raise unittest.SkipTest(
                "no d3drdb snapshot is published yet (D1); the client cannot be "
                "exercised end to end until one is")
        _quiet_notice(cls)

    def test_cohort_query_runs_unchanged(self):
        import pandas as pd
        from toksearch_d3d.sql import connect_d3drdb
        with connect_d3drdb() as conn:
            self.assertTrue(conn.snapshot.startswith("d3drdb_"))
            df = pd.read_sql(
                "SELECT s.shot, s.entered FROM shots s JOIN shots_type t ON s.shot = t.shot "
                "WHERE t.shot_type = 'plasma' AND s.entered BETWEEN '2024-06-01' AND '2024-08-01' "
                "ORDER BY s.shot", conn)
        self.assertGreater(len(df), 500)      # ~651 in the July 2026 dump
        self.assertLess(len(df), 800)

    def test_one_shot_of_disruption_warning(self):
        from toksearch_d3d.sql import connect_d3drdb
        with connect_d3drdb() as conn:
            cur = conn.cursor()
            cur.execute("SELECT TOP 5 time, beta_n FROM disruption_warning WHERE shot = %s ORDER BY time", (175552,))
            rows = cur.fetchall()
        self.assertEqual(len(rows), 5)

    def test_the_notice_names_the_snapshot(self):
        from toksearch.sql import snapshot
        from toksearch_d3d.sql import connect_d3drdb
        saved = set(snapshot._noticed)
        snapshot._noticed.clear()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                connect_d3drdb().close()
        finally:
            snapshot._noticed.update(saved)
        notices = [w for w in caught if issubclass(w.category, snapshot.SnapshotNotice)]
        self.assertEqual(len(notices), 1)
        self.assertIn("d3drdb_", str(notices[0].message))


@unittest.skipUnless(HAVE_TOKEN and HAVE_LIVE, "needs BEARER_TOKEN and the d3drdb credential file (on-site)")
class TestDifferential(unittest.TestCase):
    """Snapshot vs live, bounded by the snapshot's shot ceiling."""

    QUERIES = [
        "SELECT shot, shot_type FROM shots_type WHERE shot <= {c} AND shot > {c} - 5000 ORDER BY shot, shot_type",
        "SELECT shot, run, brief FROM shots WHERE shot <= {c} AND shot > {c} - 5000 ORDER BY shot",
        "SELECT run, brief FROM runs WHERE run IN (SELECT run FROM shots WHERE shot <= {c} AND shot > {c} - 2000) ORDER BY run",
        "SELECT count(*) AS n FROM shots_type WHERE shot_type = 'PLASMA' AND shot <= {c}",
        "SELECT count(*) AS n FROM shots WHERE brief LIKE '%elm%' AND shot <= {c}",
    ]

    @classmethod
    def setUpClass(cls):
        if not _published():
            raise unittest.SkipTest("no d3drdb snapshot is published yet (D1)")
        _quiet_notice(cls)

    def test_snapshot_and_live_agree_below_the_ceiling(self):
        import pandas as pd
        from toksearch_d3d.sql import connect_d3drdb
        with connect_d3drdb() as snap, connect_d3drdb(live=True) as live:
            ceiling = snap.manifest["source"]["shot_ceiling"]
            for q in self.QUERIES:
                sql = q.format(c=ceiling)
                a = pd.read_sql(sql, snap)
                b = pd.read_sql(sql, live)
                a.columns = [c.lower() for c in a.columns]
                b.columns = [c.lower() for c in b.columns]
                for frame in (a, b):
                    for col in frame.select_dtypes(include="object"):
                        frame[col] = frame[col].str.rstrip()
                pd.testing.assert_frame_equal(a, b, check_dtype=False, obj=sql)


if __name__ == "__main__":
    unittest.main()
