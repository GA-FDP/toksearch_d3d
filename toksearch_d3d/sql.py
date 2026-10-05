# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""D3D-specific SQL helpers.

`connect_d3drdb()` returns a connection to a published **snapshot** of
d3drdb -- the same thing on-site and off, so one script gives one answer
wherever it runs -- and `connect_d3drdb(live=True)` dials the live SQL
Server as before. Neither falls back to the other. Everything else is
delegated to the generic `toksearch.sql` API.
"""

import toksearch.sql.mssql as _mssql
import toksearch.sql.snapshot as _snapshot


def connect_d3drdb(*, live=False, snapshot=None, **overrides):
    """Connect to the D3D shot-metadata database.

    By default: the newest published snapshot of d3drdb (or the one this
    process is pinned to -- see `toksearch.sql.snapshot.resolve`), read
    remotely through DuckDB. Your T-SQL runs unchanged. The first call in
    a process issues a `SnapshotNotice` naming the snapshot.

    Arguments:
        live: dial the live SQL Server at d3drdb.gat.com instead. Needs
            the GA network and ~/D3DRDB.sybase_login. Keyword overrides
            (`db=`, `host=`, `port=`, `username=`, `password=`,
            `password_file=`) apply here and only here.
        snapshot: a snapshot id such as "d3drdb_20261005T120000Z", when
            you want a specific one. Incompatible with `live`.

    Returns a DB-API-shaped connection either way: `cursor()`, `with`,
    and `pd.read_sql(sql, conn)` all work.

    Raises:
        toksearch.sql.snapshot.SnapshotError: the snapshot could not be
            located or read. Never silently replaced by the live database.
        ValueError: `live=True` together with `snapshot=`.
        TypeError: overrides without `live=True`.
    """
    if live and snapshot is not None:
        raise ValueError("live=True and snapshot= are incompatible: a snapshot "
                         "is a published copy, not the live database")
    if live:
        return _mssql.connect_tokamak_sql("d3d", "d3drdb", **overrides)
    if overrides:
        raise TypeError(
            "{} apply to the live database only; pass live=True with them. "
            "A snapshot has no host, port or credentials of its own.".format(
                ", ".join(sorted(overrides))))
    return _snapshot.connect_tokamak("d3d", "d3drdb", snapshot=snapshot)


__all__ = ["connect_d3drdb"]
