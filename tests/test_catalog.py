# Copyright 2024 General Atomics
# Licensed under the Apache License, Version 2.0.

"""Tests that the toksearch_d3d catalog data ships and validates."""

import unittest


class TestD3DCatalog(unittest.TestCase):
    def test_d3d_yaml_validates(self):
        from fdp_schema import load_tokamak
        from toksearch_d3d.data import d3d_yaml
        t = load_tokamak(d3d_yaml)
        self.assertEqual(t.name, "d3d")
        self.assertEqual(len(t.locators), 3)
        kinds = {l.kind for l in t.locators}
        self.assertEqual(kinds, {"mds_tree", "ptdata_indexed", "sql"})

    def test_entry_point_registered(self):
        from importlib.metadata import entry_points
        eps = list(entry_points(group="fdp_schema.catalogs"))
        names = [ep.name for ep in eps]
        self.assertIn("d3d", names)

    def test_entry_point_load_returns_readable_traversable(self):
        from importlib.metadata import entry_points
        from fdp_schema import load_tokamak
        eps = entry_points(group="fdp_schema.catalogs")
        d3d_ep = next(ep for ep in eps if ep.name == "d3d")
        source = d3d_ep.load()
        # Should be readable via load_tokamak directly.
        t = load_tokamak(source)
        self.assertEqual(t.name, "d3d")


if __name__ == "__main__":
    unittest.main()
