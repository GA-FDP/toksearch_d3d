# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Catalog data shipped by toksearch_d3d.

This module exposes Traversable references for each YAML so the
fdp_schema.catalogs entry-point group can find them without importing
fdp_schema or pydantic.
"""

from importlib.resources import files

d3d_yaml = files(__package__) / "d3d.yaml"
