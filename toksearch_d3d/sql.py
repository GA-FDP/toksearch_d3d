# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""D3D-specific SQL helpers. Thin wrappers over toksearch.sql.mssql
that pin the tokamak name; everything else is delegated to the
generic API."""

import toksearch.sql.mssql as _mssql


def connect_d3drdb(**overrides):
    """Connect to the D3D shot-metadata database.

    Reads host/port/database from the d3d.yaml SqlLocator(name='d3drdb').
    Keyword overrides match `connect_tokamak_sql`. Pre-existing callers
    like `connect_d3drdb(db='code_rundb')` keep working unchanged.
    """
    return _mssql.connect_tokamak_sql("d3d", "d3drdb", **overrides)


__all__ = ["connect_d3drdb"]
