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


SNAPSHOT_VAR = "FDP_SQL_SNAPSHOT_D3DRDB"
SNAPSHOT_ID = r"d3drdb_\d{8}T\d{6}Z"
# What a compute() over a saved snapshot exports or flags for the run.
# Each test starts and ends with none of it, so no test inherits a pin.
_RUN_VARS = (SNAPSHOT_VAR, "FDP_STORE_CATALOG", "FDP_STORE_SHARDS")


def _which_snapshot(rec):
    """Map function: the snapshot a worker's connect_d3drdb() reads."""
    import os
    from toksearch_d3d.sql import connect_d3drdb
    with connect_d3drdb() as conn:
        rec["sid"] = conn.snapshot
    rec["pid"] = os.getpid()
    return rec


def _fdp(*args):
    import subprocess
    return subprocess.run(["fdp", *args], capture_output=True, text=True)


@unittest.skipUnless(HAVE_TOKEN, "needs BEARER_TOKEN (run under `fdp run`)")
class TestPinning(unittest.TestCase):
    """D3: a saved snapshot records the d3drdb snapshot a run read, verifies
    its Parquet, and pins it for every worker of a replay."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        if not _published():
            raise unittest.SkipTest("no d3drdb snapshot is published yet (D1)")
        _quiet_notice(cls)
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.path = os.path.join(tmp.name, "s.json")
        cls.save = _fdp("snapshot", "save", "--shot", "165920", "-o", cls.path)
        if cls.save.returncode != 0:
            raise AssertionError("fdp snapshot save exited {}:\n{}{}".format(
                cls.save.returncode, cls.save.stdout, cls.save.stderr))
        import json
        with open(cls.path) as fh:
            cls.doc = json.load(fh)

    def setUp(self):
        from toksearch.signal import store_catalog
        from toksearch.sql import snapshot
        self._env_before = {k: os.environ.get(k) for k in _RUN_VARS}
        self._pinned_before = set(snapshot._pinned)
        self._catalog_pinned_before = store_catalog._PINNED_THIS_PROCESS
        self._clear()

    def tearDown(self):
        from toksearch.signal import store_catalog
        from toksearch.sql import snapshot
        self._clear()
        for k, v in self._env_before.items():
            if v is not None:
                os.environ[k] = v
        snapshot._pinned.update(self._pinned_before)
        store_catalog._PINNED_THIS_PROCESS = self._catalog_pinned_before

    @staticmethod
    def _clear():
        from toksearch.signal import store_catalog
        from toksearch.sql import snapshot
        for k in _RUN_VARS:
            os.environ.pop(k, None)
        snapshot._pinned.clear()
        store_catalog._PINNED_THIS_PROCESS = False

    def test_save_show_verify(self):
        from toksearch_d3d.sql import connect_d3drdb
        self.assertEqual(self.doc["schema"], "fdp-snapshot/2")
        sid = self.doc["sql_snapshots"]["d3drdb"]
        self.assertRegex(sid, "^" + SNAPSHOT_ID + "$")

        show = _fdp("snapshot", "show", self.path)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn(sid, show.stdout)

        verify = _fdp("snapshot", "verify", "--sample", "2", self.path)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("d3drdb", verify.stdout + verify.stderr)

        # Saved moments ago, so the newest then is the newest now.
        with connect_d3drdb() as conn:
            self.assertEqual(conn.snapshot, sid)

    def test_replay_pins_the_worker(self):
        from toksearch import Pipeline
        sid = self.doc["sql_snapshots"]["d3drdb"]
        pipe = Pipeline.from_snapshot(self.path)
        pipe.map(_which_snapshot)
        recs = list(pipe.compute_multiprocessing(num_workers=2))
        self.assertEqual([r["shot"] for r in recs], [165920])
        for rec in recs:
            # A map that raises is recorded, not propagated: show why.
            self.assertEqual(rec.errors, {}, "the worker's map failed")
            self.assertEqual(rec["sid"], sid)
            self.assertNotEqual(rec["pid"], os.getpid())
        self.assertEqual(os.environ.get(SNAPSHOT_VAR), sid)

    def test_env_pin_conflicts_with_the_file(self):
        from toksearch import Pipeline
        from toksearch.sql.snapshot import SnapshotConflict
        os.environ[SNAPSHOT_VAR] = "d3drdb_19700101T000000Z"
        with self.assertRaises(SnapshotConflict) as cm:
            Pipeline.from_snapshot(self.path).compute_serial()
        msg = str(cm.exception)
        self.assertIn("d3drdb_19700101T000000Z", msg)
        self.assertIn(self.doc["sql_snapshots"]["d3drdb"], msg)
        self.assertIn(SNAPSHOT_VAR, msg)
        # A user's export, not this process's settle: the message names the
        # file as the other pin and says which variable to unset. (The text
        # naming Pipeline.from_snapshot is for a pin this process settled.)
        self.assertIn("saved snapshot", msg)


if __name__ == "__main__":
    unittest.main()
